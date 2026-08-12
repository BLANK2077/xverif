#include "server.h"
#include "../design/common/xdebug_design_paths.h"
#include "../design/protocol/protocol.h"
#include "session/session_registry.h"
#include "session/session_manager.h"
#include "session/session_transport.h"
#include "core/common/env_config.h"
#include "core/diagnostic_error.h"
#include "core/logging/action_log.h"
#include "core/npi/time_contract.h"
#include "core/session/session_timeout.h"
#include "core/session/request_deadline.h"
#include "core/session/transport_common.h"
#include "core/schema/internal_request_contract.h"
#include "core/schema/runtime_schema_validator.h"
#include "core/transport/file_exchange.h"
#include "core/value/logic_value.h"
#include "waveform/cache/analysis_probe.h"
#include "waveform/cache/analysis_repository.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/stream/stream_analyzer.h"
#include "json.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <sstream>
#include <limits.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <sys/stat.h>
#include <signal.h>
#include <cstdarg>
#include <strings.h>
#include <thread>
#include <ctime>
#include <exception>
#include <mutex>

#include "npi.h"
#include "npi_fsdb.h"
#include "service/engine_action_registry.h"

namespace xdebug_waveform {
extern std::string g_session_id;
extern npiFsdbFileHandle g_fsdb_file;
extern std::string g_fsdb_file_path;
extern ApbAnalyzer g_apb_analyzer;
extern AxiAnalyzer g_axi_analyzer;
StreamAnalyzer g_stream_analyzer;
std::unique_ptr<AnalysisRepository> g_analysis_repository;
}

namespace xdebug_design {

using Json = nlohmann::ordered_json;
using xdebug_engine::SessionInfo;
using xdebug_engine::current_host_name;

// Global for cleanup — non-static: shared with handler registry.
std::string g_session_id;
static int g_srv_fd = -1;
static char g_sock_path[SOCK_PATH_LEN];
static std::string g_transport = "uds";
static std::string g_bind_host;
static std::string g_host;
static int g_port = 0;
static std::string g_auth_token;
static int g_idle_timeout_sec = 86400;
static FILE* g_debug_log = nullptr;
static std::string g_npi_startup_log_path;
static int g_crash_fd = -1;
static char g_crash_prefix[512] = {};
static char g_current_action[128] = {};
static char g_current_request_id[128] = {};
// A session process owns exactly one vendor NPI context.  Keep data actions
// strictly serialized even if a future transport implementation dispatches
// accepted clients concurrently.
static std::mutex g_npi_request_mutex;

static void touch_current_generation(
    xdebug_engine::SessionRegistry& registry,
    time_t last_active) {
    std::string generation;
    const bool marker_ok =
        xdebug_design_read_generation_marker(
            g_session_id, generation);
    const bool touched =
        marker_ok &&
        registry
            .touch_if_generation(
                g_session_id,
                generation,
                last_active)
            .ok();
    if (!touched) {
        xdebug_core::log_lifecycle_event(
            "engine",
            g_session_id,
            "server.touch_generation_failed",
            false);
    }
}

// Unified-engine resource state.
bool g_has_design = false;
bool g_has_waveform = false;
npiFsdbFileHandle g_fsdb_file = nullptr;
std::string g_fsdb_path;
std::string g_daidir_path;

const char* engine_startup_failure_phase(int exit_code) {
    switch (static_cast<xdebug_engine::EngineStartupExitCode>(exit_code)) {
        case xdebug_engine::EngineStartupExitCode::NpiInitFailed:
            return "npi_init";
        case xdebug_engine::EngineStartupExitCode::NpiLoadDesignFailed:
            return "npi_load_design";
        case xdebug_engine::EngineStartupExitCode::NpiFsdbOpenFailed:
            return "npi_fsdb_open";
        case xdebug_engine::EngineStartupExitCode::GenericFailure:
            break;
    }
    return "";
}

static void close_fsdb_file() {
    if (xdebug_waveform::g_analysis_repository) {
        xdebug_waveform::g_apb_analyzer.configure_repository(
            nullptr, std::string(), xdebug_waveform::FsdbIdentity());
        xdebug_waveform::g_axi_analyzer.configure_repository(
            nullptr, std::string(), xdebug_waveform::FsdbIdentity());
        xdebug_waveform::g_stream_analyzer.configure_repository(
            nullptr, std::string(), xdebug_waveform::FsdbIdentity());
        xdebug_waveform::g_analysis_repository->clear("session_exit");
        xdebug_waveform::g_analysis_repository.reset();
    }
    if (!g_fsdb_file) return;
    npi_fsdb_close(g_fsdb_file);
    g_fsdb_file = nullptr;
    xdebug_waveform::g_fsdb_file = nullptr;
    xdebug_waveform::g_fsdb_file_path.clear();
}

static bool server_debug_enabled() {
    return xdebug_core::xdebug_debug_enabled();
}

static void server_debug_open_log() {
    if (!server_debug_enabled() || g_session_id.empty()) return;
    xdebug_design_ensure_session_dir(g_session_id);
    char log_path[SOCK_PATH_LEN];
    get_debug_log_path(log_path, g_session_id);
    g_debug_log = fopen(log_path, "a");
    if (g_debug_log) {
        chmod(log_path, 0600);
        fprintf(g_debug_log, "=== xdebug engine server debug session=%s ===\n", g_session_id.c_str());
        fflush(g_debug_log);
    }
}

static void server_debug_log(const char* fmt, ...) {
    if (!g_debug_log) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_debug_log, fmt, ap);
    va_end(ap);
    fprintf(g_debug_log, "\n");
    fflush(g_debug_log);
}

static void cleanup_and_exit(int sig) {
    server_debug_log("signal_exit sig=%d", sig);
    xdebug_core::log_lifecycle_event("engine", g_session_id, "server.signal_exit", false,
                                     {{"signal", sig}});
    if (g_srv_fd >= 0) close(g_srv_fd);
    if (strlen(g_sock_path) > 0) unlink(g_sock_path);
    close_fsdb_file();
    if (g_debug_log) { fclose(g_debug_log); g_debug_log = nullptr; }
    if (g_crash_fd >= 0) { close(g_crash_fd); g_crash_fd = -1; }
    exit(0);
}

static void write_const(int fd, const char* s) {
    if (fd < 0 || !s) return;
    size_t len = 0;
    while (s[len] != '\0') len++;
    while (len > 0) {
        ssize_t n = write(fd, s, len);
        if (n <= 0) return;
        s += n;
        len -= static_cast<size_t>(n);
    }
}

static void write_int(int fd, int value) {
    char buf[32];
    size_t i = sizeof(buf);
    bool neg = value < 0;
    unsigned int v = neg ? static_cast<unsigned int>(-value) : static_cast<unsigned int>(value);
    buf[--i] = '\0';
    do {
        buf[--i] = static_cast<char>('0' + (v % 10));
        v /= 10;
    } while (v > 0 && i > 0);
    if (neg && i > 0) buf[--i] = '-';
    write_const(fd, &buf[i]);
}

static void crash_signal_exit(int sig) {
    write_const(g_crash_fd, g_crash_prefix);
    if (g_current_action[0] != '\0') {
        write_const(g_crash_fd, " current_action=");
        write_const(g_crash_fd, g_current_action);
    }
    if (g_current_request_id[0] != '\0') {
        write_const(g_crash_fd, " request_id=");
        write_const(g_crash_fd, g_current_request_id);
    }
    write_const(g_crash_fd, " sig=");
    write_int(g_crash_fd, sig);
    write_const(g_crash_fd, "\n");
    _exit(128 + sig);
}

static void open_crash_marker() {
    std::string path = xdebug_core::component_log_path("engine", g_session_id, "crash_marker");
    g_crash_fd = open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
    snprintf(g_crash_prefix, sizeof(g_crash_prefix),
             "signal_exit pid=%d session_id=%s", static_cast<int>(getpid()), g_session_id.c_str());
}

static void install_crash_signal_handlers() {
    signal(SIGSEGV, crash_signal_exit);
    signal(SIGABRT, crash_signal_exit);
}

static void update_current_request_marker(const Json& request) {
    std::string action = request.value("action", std::string());
    std::string request_id;
    Json observability =
        request.value("observability", Json::object());
    if (observability.is_object() &&
        observability.contains("request_id") &&
        observability["request_id"].is_string()) {
        request_id =
            observability["request_id"].get<std::string>();
    }
    snprintf(g_current_action, sizeof(g_current_action), "%s", action.c_str());
    snprintf(g_current_request_id, sizeof(g_current_request_id), "%s", request_id.c_str());
}

static std::string getenv_string(const char* name) {
    return xdebug_core::env_raw_string(name);
}

static std::string hash_string_hex(const std::string& value) {
    unsigned long long h = 1469598103934665603ULL;
    for (unsigned char c : value) {
        h ^= c;
        h *= 1099511628211ULL;
    }
    char buf[32];
    snprintf(buf, sizeof(buf), "%016llx", h);
    return std::string(buf);
}

static void log_environment_snapshot(int argc, char** argv) {
    char cwd[PATH_MAX] = {};
    char host[256] = {};
    Json context;
    if (gethostname(host, sizeof(host)) == 0) context["hostname"] = host;
    if (getcwd(cwd, sizeof(cwd))) context["cwd_path"] = cwd;
    context["argv_count"] = argc;
    if (argc > 0 && argv && argv[0]) context["argv0_path"] = argv[0];
    context["build"] = {{"date", __DATE__}, {"time", __TIME__}};
    Json eda;
    std::string verdi_home = getenv_string("VERDI_HOME");
    std::string vcs_home = getenv_string("VCS_HOME");
    if (!verdi_home.empty()) eda["verdi_home_path"] = verdi_home;
    if (!vcs_home.empty()) eda["vcs_home_path"] = vcs_home;
    if (!eda.empty()) context["eda"] = eda;
    Json lsf;
    std::string lsb_jobid = getenv_string("LSB_JOBID");
    std::string lsb_queue = getenv_string("LSB_QUEUE");
    if (!lsb_jobid.empty()) lsf["job_id"] = lsb_jobid;
    if (!lsb_queue.empty()) lsf["queue"] = lsb_queue;
    if (!lsf.empty()) context["lsf"] = lsf;
    std::string ld_library_path = getenv_string("LD_LIBRARY_PATH");
    if (!ld_library_path.empty()) {
        context["paths"] = {{"ld_library_path_hash", hash_string_hex(ld_library_path)}};
    }
    context["license_env"] = {
        {"snpslmd_license_file_present", !getenv_string("SNPSLMD_LICENSE_FILE").empty()},
        {"lm_license_file_present", !getenv_string("LM_LICENSE_FILE").empty()}
    };
    xdebug_core::log_lifecycle_event("engine", g_session_id, "env.snapshot", true, context);
}

static void maybe_run_crash_marker_test_hook() {
    if (!xdebug_core::xdebug_engine_test_crash_marker_enabled()) return;

    std::string action = xdebug_core::xdebug_engine_test_crash_action();
    std::string request_id = xdebug_core::xdebug_engine_test_crash_request_id();
    if (!action.empty()) {
        snprintf(g_current_action, sizeof(g_current_action), "%s", action.c_str());
    }
    if (!request_id.empty()) {
        snprintf(g_current_request_id, sizeof(g_current_request_id), "%s", request_id.c_str());
    }
    install_crash_signal_handlers();
    raise(SIGABRT);
}

static void daemonize_io() {
    int devnull = open("/dev/null", O_RDWR);
    if (devnull >= 0) {
        dup2(devnull, STDIN_FILENO);
        dup2(devnull, STDOUT_FILENO);
        dup2(devnull, STDERR_FILENO);
        close(devnull);
    }
}

static bool begin_npi_startup_capture() {
    int devnull = open("/dev/null", O_RDWR);
    if (devnull >= 0) {
        dup2(devnull, STDIN_FILENO);
        close(devnull);
    }

    g_npi_startup_log_path = xdebug_design_npi_startup_log_path(g_session_id);
    int fd = open(g_npi_startup_log_path.c_str(),
                  O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) {
        xdebug_core::log_lifecycle_event(
            "engine", g_session_id, "npi_startup.capture_failed", false,
            {{"diagnostic_log_path", g_npi_startup_log_path},
             {"errno", errno}, {"message", strerror(errno)}});
        daemonize_io();
        return false;
    }
    chmod(g_npi_startup_log_path.c_str(), 0600);
    dprintf(fd, "=== xdebug NPI startup diagnostics session=%s ===\n", g_session_id.c_str());
    fflush(stdout);
    fflush(stderr);
    dup2(fd, STDOUT_FILENO);
    dup2(fd, STDERR_FILENO);
    close(fd);
    return true;
}

static long long npi_startup_log_bytes() {
    struct stat st;
    if (g_npi_startup_log_path.empty() ||
        stat(g_npi_startup_log_path.c_str(), &st) != 0) return -1;
    return static_cast<long long>(st.st_size);
}

static Json npi_startup_context(const std::string& failure_phase) {
    Json context = {
        {"failure_phase", failure_phase},
        {"diagnostic_log", "engine_npi_startup"},
        {"diagnostic_log_path", g_npi_startup_log_path},
        {"diagnostic_log_bytes", npi_startup_log_bytes()}
    };
    context["license_env"] = {
        {"snpslmd_license_file_present", !getenv_string("SNPSLMD_LICENSE_FILE").empty()},
        {"lm_license_file_present", !getenv_string("LM_LICENSE_FILE").empty()}
    };
    return context;
}

static void end_npi_startup_capture() {
    fflush(stdout);
    fflush(stderr);
    daemonize_io();
}

static bool send_all(int fd, const char* buf, size_t len) {
    return xdebug_core::write_all_deadline(fd, buf, len) ==
           xdebug_core::TransportIoStatus::Ok;
}

static Json ok_response(const Json& data = Json::object()) {
    return {{"api_version", INTERNAL_API_VERSION}, {"ok", true}, {"data", data}, {"error", nullptr}};
}

static Json error_response(Json error) {
    error = xdebug_core::normalize_diagnostic_error(error, "handler");
    return {{"api_version", INTERNAL_API_VERSION}, {"ok", false},
            {"status", "server_error"}, {"data", nullptr}, {"error", error}};
}

static Json error_response(const std::string& code, const std::string& message) {
    return error_response(
        xdebug_core::DiagnosticErrorBuilder::handler(code, message).to_json());
}

static Json request_too_large_response() {
    const std::string message =
        "JSON request exceeds the session transport limit";
    Json error = xdebug_core::DiagnosticErrorBuilder::transport(
                     "REQUEST_TOO_LARGE", message)
                     .recoverable(false)
                     .to_json();
    error["limit_name"] = "request_bytes";
    error["received_bytes"] = xdebug_core::kMaxSessionJsonBytes + 1U;
    error["max_bytes"] = xdebug_core::kMaxSessionJsonBytes;
    error["transport"] = g_transport;
    error["phase"] = "transport_request";
    error["next_actions"] = Json::array({
        "Split the batch into smaller requests or use a bounded export action."
    });
    return error_response(error);
}

static void patch_example_path(Json& example, const std::string& invalid_arg, const Json& value) {
    if (!example.is_object()) return;
    if (invalid_arg == "args.time_range.begin" || invalid_arg == "args.time_range.end") {
        Json& args = example["args"];
        if (!args.is_object()) args = Json::object();
        args["time_range"] = {{"begin", "0ns"}, {"end", "100ns"}};
    } else if (invalid_arg == "args.channel") {
        example["args"]["channel"] = value;
    }
}

static void enrich_runtime_parameter_error(const Json& request, Json& error) {
    std::string action = request.value("action", std::string());
    std::string message = error.value("message", std::string());
    if (message.find("INVALID_REQUEST:") == 0) error["code"] = "INVALID_REQUEST";
    if (message.find("TIME_RANGE_INVALID:") == 0) error["code"] = "TIME_RANGE_INVALID";
    if (message.find("TIME_SPEC_INVALID:") == 0) error["code"] = "TIME_SPEC_INVALID";
    Json example = xdebug_core::valid_request_example(action);
    const auto infer_parameter = [&](const std::string& invalid_arg,
                                     const std::string& expected) {
        if (error.contains("invalid_arg")) return;
        error["invalid_arg"] = invalid_arg;
        error["expected"] = expected;
    };
    if (message.find("end time is before begin time") != std::string::npos ||
        message.find("args.time_range.end is before args.time_range.begin") != std::string::npos) {
        if (!error.contains("invalid_arg")) {
            infer_parameter(
                "args.time_range.end",
                "time_range.end must be greater than or equal to time_range.begin");
            patch_example_path(example, "args.time_range.end", Json());
        }
    } else if (message.find("Invalid time") != std::string::npos ||
               message.find("TIME_SPEC_INVALID") != std::string::npos) {
        std::string invalid = "args.time";
        Json args = request.value("args", Json::object());
        if (args.is_object() && args.contains("time_range") && args["time_range"].is_object()) {
            Json tr = args["time_range"];
            if (tr.contains("begin")) invalid = "args.time_range.begin";
            if (tr.contains("end") && message.find("end") != std::string::npos)
                invalid = "args.time_range.end";
        }
        if (!error.contains("invalid_arg")) {
            infer_parameter(
                invalid,
                "time string such as 10ns, 100ps, or max for end");
            patch_example_path(example, invalid, Json());
        }
    } else if (message.find("Clock signal not found") != std::string::npos) {
        infer_parameter("args.clock", "existing clock signal path");
    } else if (message.find("Signal not found") != std::string::npos ||
               message.find("signal not found") != std::string::npos) {
        infer_parameter("args.signal", "existing signal path");
    } else if (message.find("AXI config not found") != std::string::npos ||
               message.find("APB config not found") != std::string::npos ||
               message.find("CONFIG_NOT_FOUND") != std::string::npos) {
        infer_parameter(
            "args.name",
            "name of a previously loaded config");
    }
    Json args = request.value("args", Json::object());
    if (action == "axi.channel_stall" && args.is_object() && args.contains("channel") &&
        args["channel"].is_string()) {
        std::string c = args["channel"].get<std::string>();
        if (c != "aw" && c != "w" && c != "b" && c != "ar" && c != "r") {
            error["invalid_arg"] = "args.channel";
            error["expected"] = "one of aw, w, b, ar, r";
            error["available_values"] = Json::array({"aw", "w", "b", "ar", "r"});
            patch_example_path(example, "args.channel", "ar");
        }
    }
    if (error.contains("invalid_arg")) {
        if (!error.contains("correct_example")) error["correct_example"] = example;
    }
}

static Json action_error_response(const Json& request, const Json& data) {
    Json error = data.value("error", Json());
    std::string code = "ACTION_FAILED";
    std::string message = data.value("message", std::string("action failed"));
    if (error.is_object()) {
        code = error.value("code", code);
        message = error.value("message", message);
    } else if (error.is_string()) {
        code = error.get<std::string>();
        if (code.find("Signal not found") != std::string::npos) {
            message = code;
            code = "SIGNAL_NOT_FOUND";
        }
    }
    Json canonical_error = error.is_object()
        ? error
        : Json{{"code", code}, {"message", message}, {"recoverable", true},
               {"error_layer", "handler"}};
    if (!canonical_error.contains("code")) canonical_error["code"] = code;
    if (!canonical_error.contains("message")) canonical_error["message"] = message;
    if (!canonical_error.contains("error_layer")) canonical_error["error_layer"] = "handler";
    enrich_runtime_parameter_error(request, canonical_error);
    return error_response(canonical_error);
}

static Json schema_validation_error_response(const Json& request,
                                             const std::string& action,
                                             const xdebug_core::RuntimeSchemaValidationResult& validation) {
    Json canonical_error = validation.error;
    if (!canonical_error.is_object()) canonical_error = Json::object();
    canonical_error["code"] = validation.code.empty() ? "INVALID_REQUEST" : validation.code;
    canonical_error["message"] = validation.message;
    canonical_error["error_layer"] = "schema";
    (void)request;
    (void)action;
    return error_response(canonical_error);
}

static bool send_response(int fd, const Json& response) {
    std::string wire = response.dump() + "\n";
    return send_all(fd, wire.c_str(), wire.size());
}

static bool handle_client(int client_fd, bool& should_quit);

static bool run_file_request_through_handler(const Json& request, Json& response, bool& should_quit) {
    should_quit = false;
    int sv[2] = {-1, -1};
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, sv) != 0) return false;
    bool handler_quit = false;
    std::thread worker([&]() {
        handle_client(sv[1], handler_quit);
        shutdown(sv[1], SHUT_WR);
        close(sv[1]);
    });
    std::string wire = request.dump() + "\n";
    send_all(sv[0], wire.c_str(), wire.size());
    shutdown(sv[0], SHUT_WR);
    std::string output;
    char buf[4096];
    while (true) {
        ssize_t n = read(sv[0], buf, sizeof(buf));
        if (n <= 0) break;
        output.append(buf, n);
    }
    close(sv[0]);
    worker.join();
    should_quit = handler_quit;
    try {
        response = Json::parse(output);
        return response.is_object();
    } catch (...) {
        response = error_response("INVALID_RESPONSE", "file transport handler returned invalid JSON");
        return false;
    }
}

static int file_transport_loop(const std::string& file_dir) {
    if (!xdebug_core::ensure_file_transport_layout(file_dir)) {
        xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.file_layout_failed", false,
                                         {{"file_dir", file_dir}});
        return 1;
    }
    SessionInfo endpoint;
    endpoint.session_id = g_session_id;
    endpoint.transport = "file";
    endpoint.file_dir = file_dir;
    endpoint.server_host = current_host_name();
    bool endpoint_ok = xdebug_engine::write_endpoint_file(endpoint);
    xdebug_core::log_lifecycle_event("engine", g_session_id,
                                     endpoint_ok ? "endpoint.write_ok" : "endpoint.write_failed",
                                     endpoint_ok,
                                     {{"transport", endpoint.transport}, {"file_dir", endpoint.file_dir}});
    if (!endpoint_ok) return 1;

    const std::string agent_id = current_host_name() + "-" + std::to_string(getpid());
    xdebug_engine::SessionRegistry registry;
    time_t last_active = time(nullptr);
    touch_current_generation(registry, last_active);
    xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.file_loop_begin", true,
                                     {{"file_dir", file_dir}, {"idle_timeout_sec", g_idle_timeout_sec}});
    while (true) {
        time_t now = time(nullptr);
        if (now > last_active && static_cast<long long>(now - last_active) >= g_idle_timeout_sec) {
            xdebug_core::log_lifecycle_event("engine", g_session_id, "server.idle_timeout", true,
                                             {{"idle_sec", static_cast<long long>(now - last_active)},
                                              {"idle_timeout_sec", g_idle_timeout_sec}});
            break;
        }
        xdebug_core::Json worker = {{"agent_id", agent_id}, {"host", current_host_name()},
                                    {"pid", static_cast<int>(getpid())}};
        xdebug_core::atomic_write_json_file_ex(file_dir + "/heartbeat/" + agent_id + ".json",
                                               {{"version", xdebug_core::kFileRpcVersion},
                                                {"ok", true}, {"session_id", g_session_id},
                                                {"transport", "file"}, {"worker", worker},
                                                {"updated_at_us", xdebug_core::file_exchange_now_us()}},
                                               xdebug_core::AtomicWriteMode::Replace,
                                               file_dir + "/" + "tmp");
        xdebug_core::file_exchange_scan_stale_claims(
            file_dir, agent_id, xdebug_core::file_exchange_claim_timeout_ms(0));
        xdebug_core::FileClaimResult claim = xdebug_core::file_exchange_claim_one(file_dir, agent_id);
        if (!claim.claimed) {
            usleep(static_cast<useconds_t>(xdebug_core::file_exchange_poll_interval_ms()) * 1000);
            continue;
        }
        last_active = time(nullptr);
        touch_current_generation(registry, last_active);
        Json response = error_response("INVALID_REQUEST", "invalid file transport request");
        bool quit = false;
        bool ok = claim.ready &&
                  run_file_request_through_handler(Json::parse(claim.request.dump()), response, quit);
        std::string status = ok && response.value("ok", false) ? "ok" :
                             (ok ? "action_error" : "server_error");
        std::string message = ok ? std::string() : "file transport handler returned invalid response";
        xdebug_core::Json error = xdebug_core::Json::object();
        if (status != "ok") {
            if (response.contains("error") && response["error"].is_object()) {
                error = xdebug_core::Json::parse(response["error"].dump());
            } else {
                error = {{"code", status}, {"message", message}};
            }
        }
        if (claim.ready) {
            xdebug_core::file_exchange_complete_claim(file_dir, claim,
                                                      xdebug_core::Json::parse(response.dump()),
                                                      status == "ok", status, message, worker, error);
        }
        if (quit) break;
    }
    xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.file_loop_end", true);
    return 0;
}

static bool handle_client(int client_fd, bool& should_quit) {
    should_quit = false;
    std::string line;
    const xdebug_core::TransportIoStatus read_status =
        xdebug_core::read_bounded_line_deadline(
            client_fd, line, xdebug_core::kMaxSessionJsonBytes);
    if (read_status == xdebug_core::TransportIoStatus::TooLarge) {
        return send_response(client_fd, request_too_large_response());
    }
    if (read_status != xdebug_core::TransportIoStatus::Ok) return false;
    Json request;
    try {
        request = Json::parse(line);
    } catch (...) {
        return send_response(client_fd, error_response("INVALID_JSON", "request must be a JSON object"));
    }
    xdebug_core::RuntimeSchemaValidator schema_validator;
    xdebug_core::RuntimeSchemaValidationResult schema_validation =
        schema_validator.validate_internal_request(request);
    if (!schema_validation.ok) {
        return send_response(
            client_fd,
            schema_validation_error_response(
                request,
                request.value("action", std::string()),
                schema_validation));
    }
    const Json routing =
        request.value("routing", Json::object());
    if (g_transport == "tcp" &&
        routing.value("transport_auth_token", std::string()) !=
            g_auth_token) {
        return send_response(client_fd, error_response("AUTH_FAILED", "authentication failed"));
    }
    update_current_request_marker(request);
    const std::string action = request.value("action", std::string());

    // ── meta ──
    if (action == "server.quit")   { send_response(client_fd, ok_response()); should_quit = true; return true; }
    if (action == "server.ping")   return send_response(client_fd, ok_response({{"pong", true}}));
    if (action == "server.version")return send_response(client_fd, ok_response({{"api_version", INTERNAL_API_VERSION}}));

    // ── data actions: registry lookup ──
    const EngineActionHandler* h = engine_action_registry().find(action);
    if (!h)
        return send_response(client_fd, error_response("UNKNOWN_ACTION", "unknown action: " + action));
    if (h->needs_design() && !g_has_design)
        return send_response(client_fd, error_response("DESIGN_NOT_LOADED",
            "design not loaded; open session with -dbdir"));
    if (h->needs_waveform() && !g_has_waveform)
        return send_response(client_fd, error_response("WAVEFORM_NOT_LOADED",
            "waveform not loaded; open session with -fsdb"));

    xdebug_design::ContractBoundRequest bound_request(
        request, action, true);
    auto args = bound_request.args();
    auto limits = bound_request.limits();
    int request_timeout_ms = 0;
    if (limits.contains("timeout_ms")) {
        request_timeout_ms = limits["timeout_ms"].get<int>();
        limits["timeout_ms"].consume("engine_request_deadline");
    }

    xdebug_core::TimeRenderOptions time_render_options;
    if (args.contains("render_time_unit")) {
        if (!args["render_time_unit"].is_string())
            return send_response(client_fd, error_response("TIME_UNIT_INVALID",
                "args.render_time_unit must be ns, ps, us, or auto"));
        std::string render_time_unit_error;
        if (!xdebug_core::parse_time_render_unit(args["render_time_unit"].get<std::string>(),
                                                 time_render_options.unit,
                                                 render_time_unit_error)) {
            return send_response(client_fd, error_response("TIME_UNIT_INVALID", render_time_unit_error));
        }
    }
    xdebug_core::ScopedTimeRenderOptions time_render_scope(time_render_options);

    std::string value_format = args.value("value_format", std::string("hex"));
    xdebug_core::ValueRenderFormat render_format =
        xdebug_core::ValueRenderFormat::Hex;
    xdebug_core::parse_value_render_format(value_format, render_format);
    xdebug_core::ScopedValueRenderFormat value_render_scope(render_format);
    Json data;
    try {
        std::lock_guard<std::mutex> execution_guard(
            g_npi_request_mutex);
        // The resource scope lives inside the guarded try block so all owned
        // vendor handles are released before a cooperative timeout is
        // reported as confirmed to the caller.
        ActionResourceScope resources;
        EngineActionContext ctx(g_session_id, action, resources);
        xdebug_core::ScopedRequestDeadline deadline(
            request_timeout_ms);
        xdebug_core::request_deadline_checkpoint();
        data = h->run(bound_request, ctx);
        xdebug_core::request_deadline_checkpoint();
    } catch (const xdebug_core::RequestDeadlineExceeded& e) {
        Json timeout_error =
            xdebug_core::DiagnosticErrorBuilder::handler(
                "ENGINE_TIMEOUT", e.what())
                .to_json();
        timeout_error["cancel_state"] = "confirmed";
        timeout_error["session_state"] = "active";
        timeout_error["cleanup_succeeded"] = true;
        timeout_error["termination_confirmed"] = false;
        return send_response(
            client_fd, error_response(timeout_error));
    } catch (const std::exception& e) {
        return send_response(client_fd, error_response(
            "INTERNAL_ENGINE_EXCEPTION",
            "unhandled exception while running action " + action + ": " + e.what()));
    } catch (...) {
        return send_response(client_fd, error_response(
            "INTERNAL_ENGINE_EXCEPTION",
            "unhandled exception while running action " + action));
    }
    if (data.contains("error"))
        return send_response(client_fd, action_error_response(request, data));
    const std::vector<std::string> unconsumed_paths =
        bound_request.unconsumed_paths();
    if (!unconsumed_paths.empty()) {
        return send_response(
            client_fd,
            error_response(
                xdebug_core::request_consumption_violation(
                    unconsumed_paths)));
    }
    xdebug_core::apply_value_render_format(data, render_format);
    xdebug_core::apply_value_width_summary(data);
    Json resp = ok_response(data);
    Json xout_response = {
        {"data", data},
    };
    if (data.contains("summary") && data["summary"].is_object())
        xout_response["summary"] = data["summary"];
    // Internal-only sidecar.  The public frontend removes this field before
    // response-schema validation and keeps it only for XOUT presentation.
    resp["__xout"] = h->render_xout(xout_response);
    return send_response(client_fd, resp);
}

int server_main(int argc, char** argv) {
    // argv: [exe, session_id, ...design_args...]
    if (argc < 2) {
        fprintf(stderr, "Server mode requires session_id argument\n");
        return 1;
    }

    // A client may leave after its public deadline while the server is still
    // unwinding cooperatively.  Convert the late response into EPIPE rather
    // than letting SIGPIPE terminate the engine outside lifecycle accounting.
    signal(SIGPIPE, SIG_IGN);

    int arg_idx = 1;

    // Parse session ID
    g_session_id = argv[arg_idx];
    if (g_session_id.empty()) {
        fprintf(stderr, "Invalid session ID: %s\n", argv[arg_idx]);
        return 1;
    }
    arg_idx++;
    std::string runtime_config_error;
    if (!xdebug_core::xdebug_file_and_log_env_config_valid(
            runtime_config_error)) {
        fprintf(stderr, "%s\n", runtime_config_error.c_str());
        return 1;
    }
    server_debug_open_log();
    server_debug_log("server_main: parsed session_id=%s argc=%d", g_session_id.c_str(), argc);
    xdebug_core::log_lifecycle_event("engine", g_session_id, "server.start", true,
                                     {{"argc", argc}});
    std::string timeout_error;
    if (!xdebug_core::session_idle_timeout_sec(g_idle_timeout_sec, timeout_error)) {
        fprintf(stderr, "%s\n", timeout_error.c_str());
        xdebug_core::log_lifecycle_event("engine", g_session_id, "server.invalid_config", false,
                                         {{"message", timeout_error}});
        return 1;
    }
    xdebug_waveform::AnalysisCacheConfig cache_config;
    std::string cache_config_error;
    if (!xdebug_waveform::analysis_cache_config_from_environment(
            cache_config, cache_config_error)) {
        fprintf(stderr, "%s\n", cache_config_error.c_str());
        xdebug_core::log_lifecycle_event(
            "engine", g_session_id, "server.invalid_config", false,
            {{"message", cache_config_error}, {"component", "analysis_cache"}});
        return 1;
    }
    xdebug_waveform::g_analysis_repository.reset(
        new xdebug_waveform::AnalysisRepository(
            cache_config, [](const xdebug_waveform::AnalysisCacheEvent& event) {
                const bool ok = event.event != "build_failed";
                xdebug_core::log_lifecycle_event(
                    "engine", event.session_id, "analysis_cache." + event.event,
                    ok,
                    {{"protocol", event.protocol},
                     {"key_summary", event.key_summary},
                     {"object_kind", event.object_kind},
                     {"reason", event.reason},
                     {"estimated_bytes", event.estimated_bytes},
                     {"resident_estimated_bytes", event.resident_estimated_bytes},
                     {"build_estimated_bytes", event.build_estimated_bytes},
                     {"access_sequence", event.access_sequence},
                     {"generation", event.generation}});
            }));
    xdebug_core::log_lifecycle_event(
        "engine", g_session_id, "analysis_cache.initialized", true,
        {{"soft_max_bytes", cache_config.soft_max_bytes},
         {"hard_max_bytes", cache_config.hard_max_bytes},
         {"estimator_safety_factor", cache_config.estimator_safety_factor}});
    log_environment_snapshot(argc, argv);
    open_crash_marker();
    maybe_run_crash_marker_test_hook();

    std::vector<std::string> design_args;
    std::string fsdb_arg;
    while (arg_idx < argc) {
        std::string opt = argv[arg_idx++];
        if (opt == "--transport" && arg_idx < argc) g_transport = argv[arg_idx++];
        else if (opt == "--bind" && arg_idx < argc) g_bind_host = argv[arg_idx++];
        else if (opt == "--host" && arg_idx < argc) g_host = argv[arg_idx++];
        else if (opt == "--port" && arg_idx < argc) g_port = atoi(argv[arg_idx++]);
        else if (opt == "--auth" && arg_idx < argc) g_auth_token = argv[arg_idx++];
        else if ((opt == "-fsdb" || opt == "-ssf") && arg_idx < argc) fsdb_arg = argv[arg_idx++];
        else design_args.push_back(opt);
    }
    bool has_daidir = !design_args.empty();
    bool has_fsdb = !fsdb_arg.empty();
    if (!has_daidir && !has_fsdb) {
        fprintf(stderr, "Server requires at least -dbdir or -fsdb\n");
        return 1;
    }

    if (g_transport == "tcp") {
        if (g_bind_host.empty()) g_bind_host = "127.0.0.1";
        if (g_host.empty())
            g_host = (g_bind_host == "0.0.0.0" || g_bind_host == "::") ? current_host_name() : g_bind_host;
    }
    server_debug_log("server_main: transport=%s bind=%s host=%s port=%d daidir=%d fsdb=%s",
                     g_transport.c_str(), g_bind_host.c_str(), g_host.c_str(), g_port,
                     has_daidir ? 1 : 0, has_fsdb ? fsdb_arg.c_str() : "(none)");
    xdebug_core::log_lifecycle_event("engine", g_session_id, "server.transport_config", true,
                                     {{"transport", g_transport}, {"bind_host", g_bind_host},
                                      {"host", g_host}, {"port", g_port},
                                      {"has_daidir", has_daidir}, {"has_fsdb", has_fsdb}});

    // Sync waveform library globals.
    xdebug_waveform::g_session_id = g_session_id;

    // Store daidir path for response metadata.
    if (has_daidir && design_args.size() >= 2 && design_args[0] == "-dbdir")
        g_daidir_path = design_args[1];

    // Build NPI argv: [exe, ...design_args..., -ssf, fsdb_path]
    // NPI requires -ssf at init/load_design time for active-trace binding.
    int npi_argc = 1 + static_cast<int>(design_args.size())
                   + (has_fsdb ? 2 : 0);
    char** npi_argv = new char*[npi_argc];
    npi_argv[0] = argv[0];
    int npi_idx = 1;
    for (size_t i = 0; i < design_args.size(); i++)
        npi_argv[npi_idx++] = const_cast<char*>(design_args[i].c_str());
    if (has_fsdb) {
        npi_argv[npi_idx++] = const_cast<char*>("-ssf");
        npi_argv[npi_idx++] = const_cast<char*>(fsdb_arg.c_str());
    }

    begin_npi_startup_capture();

    // ── npi_init (always; once per session) ──
    server_debug_log("npi_init: begin argc=%d", npi_argc);
    xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_init.begin", true,
                                     {{"argc", npi_argc}});
    int result = 0;
    if (xdebug_core::xdebug_engine_test_npi_init_fail_enabled()) {
        fprintf(stderr, "XDEBUG_TEST_NPI_INIT_FAIL: forced npi_init failure\n");
    } else {
        result = npi_init(npi_argc, npi_argv);
    }
    if (result == 0) {
        server_debug_log("npi_init: failed");
        fflush(stdout);
        fflush(stderr);
        xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_init.failed", false,
                                         npi_startup_context("npi_init"));
        end_npi_startup_capture();
        delete[] npi_argv;
        return static_cast<int>(xdebug_engine::EngineStartupExitCode::NpiInitFailed);
    }
    server_debug_log("npi_init: ok");
    xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_init.ok", true);

    // ── npi_load_design (if daidir provided) ──
    if (has_daidir) {
        server_debug_log("npi_load_design: begin");
        xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_load_design.begin", true);
        int load_result = 0;
        if (xdebug_core::xdebug_engine_test_npi_load_design_fail_enabled()) {
            fprintf(stderr, "XDEBUG_TEST_NPI_LOAD_DESIGN_FAIL: forced npi_load_design failure\n");
        } else {
            load_result = npi_load_design(npi_argc, npi_argv);
        }
        if (load_result == 0) {
            server_debug_log("npi_load_design: failed");
            fflush(stdout);
            fflush(stderr);
            xdebug_core::log_lifecycle_event(
                "engine", g_session_id, "npi_load_design.failed", false,
                npi_startup_context("npi_load_design"));
            close_fsdb_file();
            npi_end();
            end_npi_startup_capture();
            delete[] npi_argv;
            return static_cast<int>(xdebug_engine::EngineStartupExitCode::NpiLoadDesignFailed);
        }
        g_has_design = true;
        server_debug_log("npi_load_design: ok");
        xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_load_design.ok", true);
    }

    // ── npi_fsdb_open (if fsdb provided) ──
    if (has_fsdb) {
        g_fsdb_path = fsdb_arg;
        server_debug_log("npi_fsdb_open: begin fsdb=%s", g_fsdb_path.c_str());
        xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_fsdb_open.begin", true,
                                         {{"fsdb", g_fsdb_path}});
        if (xdebug_core::xdebug_engine_test_npi_fsdb_open_fail_enabled()) {
            fprintf(stderr, "XDEBUG_TEST_NPI_FSDB_OPEN_FAIL: forced npi_fsdb_open failure\n");
            g_fsdb_file = nullptr;
        } else {
            g_fsdb_file = npi_fsdb_open(g_fsdb_path.c_str());
        }
        if (!g_fsdb_file) {
            server_debug_log("npi_fsdb_open: failed");
            fflush(stdout);
            fflush(stderr);
            xdebug_core::log_lifecycle_event(
                "engine", g_session_id, "npi_fsdb_open.failed", false,
                npi_startup_context("npi_fsdb_open"));
            close_fsdb_file();
            npi_end();
            end_npi_startup_capture();
            delete[] npi_argv;
            return static_cast<int>(xdebug_engine::EngineStartupExitCode::NpiFsdbOpenFailed);
        }
        g_has_waveform = true;
        xdebug_waveform::g_fsdb_file = g_fsdb_file;
        xdebug_waveform::g_fsdb_file_path = g_fsdb_path;
        xdebug_waveform::FsdbIdentity fsdb_identity;
        std::string identity_error;
        if (!xdebug_waveform::read_fsdb_identity(
                g_fsdb_path, fsdb_identity, identity_error)) {
            server_debug_log("fsdb identity failed: %s", identity_error.c_str());
            xdebug_core::log_lifecycle_event(
                "engine", g_session_id, "analysis_cache.fsdb_identity_failed",
                false, {{"message", identity_error}});
            close_fsdb_file();
            npi_end();
            end_npi_startup_capture();
            delete[] npi_argv;
            return static_cast<int>(xdebug_engine::EngineStartupExitCode::GenericFailure);
        }
        if (!xdebug_waveform::xdebug_waveform_ensure_session_dir(
                g_session_id)) {
            const std::string session_dir =
                xdebug_waveform::xdebug_waveform_session_dir(
                    g_session_id);
            server_debug_log(
                "waveform state directory provisioning failed: %s",
                session_dir.c_str());
            xdebug_core::log_lifecycle_event(
                "engine", g_session_id,
                "waveform_state.provision_failed", false,
                {{"session_dir", session_dir}});
            close_fsdb_file();
            npi_end();
            end_npi_startup_capture();
            delete[] npi_argv;
            return static_cast<int>(
                xdebug_engine::EngineStartupExitCode::GenericFailure);
        }
        xdebug_core::log_lifecycle_event(
            "engine", g_session_id,
            "waveform_state.provisioned", true,
            {{"session_dir",
              xdebug_waveform::xdebug_waveform_session_dir(
                  g_session_id)}});
        xdebug_waveform::g_axi_analyzer.configure_repository(
            xdebug_waveform::g_analysis_repository.get(), g_session_id,
            fsdb_identity);
        xdebug_waveform::g_apb_analyzer.configure_repository(
            xdebug_waveform::g_analysis_repository.get(), g_session_id,
            fsdb_identity);
        xdebug_waveform::g_stream_analyzer.configure_repository(
            xdebug_waveform::g_analysis_repository.get(), g_session_id,
            fsdb_identity);
        server_debug_log("npi_fsdb_open: ok");
        xdebug_core::log_lifecycle_event("engine", g_session_id, "npi_fsdb_open.ok", true,
                                         {{"fsdb", g_fsdb_path}});
        npiFsdbTime tmin, tmax;
        npi_fsdb_min_time(g_fsdb_file, &tmin);
        npi_fsdb_max_time(g_fsdb_file, &tmax);
        server_debug_log("fsdb_time: min=%llu max=%llu", tmin, tmax);
    }

    fflush(stdout);
    fflush(stderr);
    xdebug_core::log_lifecycle_event(
        "engine", g_session_id, "npi_startup.capture_complete", true,
        npi_startup_context("ready"));
    end_npi_startup_capture();

    xdebug_waveform::analysis_probe().record(
        "engine_initialized", "engine", g_session_id);
    delete[] npi_argv;

    // Set up signal handlers
    signal(SIGTERM, cleanup_and_exit);
    signal(SIGINT, cleanup_and_exit);
    install_crash_signal_handlers();

    get_sock_path(g_sock_path, g_session_id);
    if (g_transport == "file") {
        std::string file_dir = xdebug_core::file_transport_dir(xdebug_design_session_dir(g_session_id));
        int rc = file_transport_loop(file_dir);
        close_fsdb_file();
        npi_end();
        xdebug_core::log_lifecycle_event("engine", g_session_id, "server.normal_exit", rc == 0);
        if (g_debug_log) {
            fclose(g_debug_log);
            g_debug_log = nullptr;
        }
        if (g_crash_fd >= 0) {
            close(g_crash_fd);
            g_crash_fd = -1;
        }
        return rc;
    }

    if (g_transport == "tcp") {
        struct addrinfo hints;
        memset(&hints, 0, sizeof(hints));
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_STREAM;
        hints.ai_flags = AI_PASSIVE;
        struct addrinfo* res = nullptr;
        std::string port_s = std::to_string(g_port);
        int gai = getaddrinfo(g_bind_host.c_str(), port_s.c_str(), &hints, &res);
        if (gai != 0) {
            server_debug_log("tcp getaddrinfo failed: %s", gai_strerror(gai));
            xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.tcp_getaddrinfo_failed", false,
                                             {{"message", gai_strerror(gai)}, {"bind_host", g_bind_host}, {"port", g_port}});
            close_fsdb_file();
            npi_end();
            return 1;
        }
        for (struct addrinfo* p = res; p; p = p->ai_next) {
            g_srv_fd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
            if (g_srv_fd < 0) continue;
            int one = 1;
            setsockopt(g_srv_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
            if (bind(g_srv_fd, p->ai_addr, p->ai_addrlen) == 0) break;
            close(g_srv_fd);
            g_srv_fd = -1;
        }
        freeaddrinfo(res);
        if (g_srv_fd < 0) {
            server_debug_log("tcp bind failed");
            xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.tcp_bind_failed", false,
                                             {{"bind_host", g_bind_host}, {"port", g_port}});
            close_fsdb_file();
            npi_end();
            return 1;
        }
        struct sockaddr_storage ss;
        socklen_t slen = sizeof(ss);
        if (getsockname(g_srv_fd, reinterpret_cast<struct sockaddr*>(&ss), &slen) == 0) {
            if (ss.ss_family == AF_INET) g_port = ntohs(reinterpret_cast<struct sockaddr_in*>(&ss)->sin_port);
            else if (ss.ss_family == AF_INET6) g_port = ntohs(reinterpret_cast<struct sockaddr_in6*>(&ss)->sin6_port);
        }
        server_debug_log("tcp bind ok host=%s port=%d", g_host.c_str(), g_port);
        xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.tcp_bind_ok", true,
                                         {{"host", g_host}, {"port", g_port}});
    } else {
        g_srv_fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (g_srv_fd < 0) {
            server_debug_log("socket: failed");
            xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.uds_socket_failed", false);
            close_fsdb_file();
            npi_end();
            return 1;
        }
        unlink(g_sock_path);
        server_debug_log("socket_path: %s", g_sock_path);
        struct sockaddr_un addr;
        memset(&addr, 0, sizeof(addr));
        addr.sun_family = AF_UNIX;
        strncpy(addr.sun_path, g_sock_path, sizeof(addr.sun_path) - 1);
        if (bind(g_srv_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
            server_debug_log("bind: failed path=%s", g_sock_path);
            xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.uds_bind_failed", false,
                                             {{"socket_path", g_sock_path}});
            close(g_srv_fd);
            close_fsdb_file();
            npi_end();
            return 1;
        }
        chmod(g_sock_path, 0600);
        server_debug_log("bind: ok");
        xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.uds_bind_ok", true,
                                         {{"socket_path", g_sock_path}});
    }

    if (listen(g_srv_fd, 8) < 0) {
        server_debug_log("listen: failed");
        xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.listen_failed", false,
                                         {{"transport", g_transport}, {"socket_path", g_sock_path}, {"port", g_port}});
        close(g_srv_fd);
        unlink(g_sock_path);
        close_fsdb_file();
        npi_end();
        return 1;
    }
    server_debug_log("listen: ok");
    xdebug_core::log_lifecycle_event("engine", g_session_id, "transport.listen_ok", true,
                                     {{"transport", g_transport}, {"socket_path", g_sock_path}, {"host", g_host}, {"port", g_port}});

    {
        SessionInfo endpoint;
        endpoint.session_id = g_session_id;
        endpoint.transport = g_transport;
        endpoint.socket_path = g_sock_path;
        endpoint.host = g_transport == "tcp" ? g_host : "";
        endpoint.bind_host = g_transport == "tcp" ? g_bind_host : "";
        endpoint.port = g_transport == "tcp" ? g_port : 0;
        endpoint.server_host = current_host_name();
        endpoint.auth_token = g_transport == "tcp" ? g_auth_token : "";
        bool endpoint_ok = xdebug_engine::write_endpoint_file(endpoint);
        xdebug_core::log_lifecycle_event("engine", g_session_id,
                                         endpoint_ok ? "endpoint.write_ok" : "endpoint.write_failed",
                                         endpoint_ok,
                                         {{"transport", endpoint.transport}, {"socket_path", endpoint.socket_path},
                                          {"host", endpoint.host}, {"port", endpoint.port}});
        if (!endpoint_ok) {
            close(g_srv_fd);
            g_srv_fd = -1;
            if (g_transport == "uds") unlink(g_sock_path);
            close_fsdb_file();
            npi_end();
            return 1;
        }
    }

    xdebug_engine::SessionRegistry registry;
    time_t last_active = time(nullptr);
    touch_current_generation(registry, last_active);

    // Accept loop
    while (true) {
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(g_srv_fd, &rfds);
        struct timeval tv;
        tv.tv_sec = 1;
        tv.tv_usec = 0;
        int ready = select(g_srv_fd + 1, &rfds, nullptr, nullptr, &tv);
        if (ready < 0) {
            if (errno == EINTR) continue;
            break;
        }
        time_t now = time(nullptr);
        if (ready == 0) {
            if (now > last_active && static_cast<long long>(now - last_active) >= g_idle_timeout_sec) {
                xdebug_core::log_lifecycle_event("engine", g_session_id, "server.idle_timeout", true,
                                                 {{"idle_sec", static_cast<long long>(now - last_active)},
                                                  {"idle_timeout_sec", g_idle_timeout_sec}});
                break;
            }
            continue;
        }

        int client_fd = accept(g_srv_fd, nullptr, nullptr);
        if (client_fd < 0) continue;

        bool quit = false;
        handle_client(client_fd, quit);
        close(client_fd);
        last_active = time(nullptr);
        touch_current_generation(registry, last_active);

        if (quit) break;
    }

    // Cleanup
    server_debug_log("normal_exit: cleanup begin");
    xdebug_core::log_lifecycle_event("engine", g_session_id, "server.cleanup_begin", true);
    close(g_srv_fd);
    unlink(g_sock_path);
    close_fsdb_file();
    npi_end();
    server_debug_log("normal_exit: cleanup done");
    xdebug_core::log_lifecycle_event("engine", g_session_id, "server.normal_exit", true);
    if (g_debug_log) {
        fclose(g_debug_log);
        g_debug_log = nullptr;
    }
    if (g_crash_fd >= 0) {
        close(g_crash_fd);
        g_crash_fd = -1;
    }

    return 0;
}

} // namespace xdebug_design
