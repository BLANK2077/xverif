#include "api/dispatcher.h"
#include "api/help_text.h"
#include "api/request_parser.h"
#include "api/response.h"
#include "api/stdio_loop.h"
#include "api/xout_renderer.h"
#include "common/env_config.h"
#include "common/path_utils.h"
#include "logging/action_log.h"
#include "process/process_runner.h"

#include <deque>
#include <fstream>
#include <cstdlib>
#include <cstdio>
#include <iostream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace {

std::string read_stream(std::istream& input) {
    std::ostringstream text;
    text << input.rdbuf();
    return text.str();
}

enum class OutputFormat { Xout, Json };

struct CliOptions {
    OutputFormat format = OutputFormat::Xout;
    std::string input_arg;
};

bool env_wants_json() {
    return xdebug_core::env_raw_string("XVERIF_OUTPUT") == "json";
}

void print_response(const xdebug::Json& response, OutputFormat format) {
    if (format == OutputFormat::Json) {
        std::cout << response.dump(2) << "\n";
    } else {
        std::cout << xdebug::render_xout_response(response);
    }
}

void print_response(const xdebug::Json& response, OutputFormat format,
                    const std::string& handler_xout) {
    if (format == OutputFormat::Json)
        std::cout << response.dump(2) << "\n";
    else
        std::cout << xdebug::render_xout_response(response, handler_xout);
}

std::string executable_dir() {
    char path[4096] = {};
    ssize_t length = readlink("/proc/self/exe", path, sizeof(path) - 1);
    if (length <= 0) return ".";
    std::string full(path, static_cast<size_t>(length));
    size_t slash = full.rfind('/');
    return slash == std::string::npos ? "." : full.substr(0, slash);
}

std::string parent_dir(const std::string& path) {
    size_t slash = path.rfind('/');
    if (slash == std::string::npos) return ".";
    if (slash == 0) return "/";
    return path.substr(0, slash);
}

bool file_exists(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0;
}

bool ensure_dir(const std::string& path) {
    if (path.empty()) return false;
    if (mkdir(path.c_str(), 0700) == 0) return true;
    struct stat st;
    return stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

bool ensure_dir_recursive(const std::string& path) {
    if (path.empty()) return false;
    std::string cur;
    size_t i = 0;
    if (path[0] == '/') {
        cur = "/";
        i = 1;
    }
    while (i <= path.size()) {
        size_t slash = path.find('/', i);
        std::string part = path.substr(i, slash == std::string::npos ? std::string::npos : slash - i);
        if (!part.empty()) {
            if (cur.size() > 1) cur += "/";
            cur += part;
            if (!ensure_dir(cur)) return false;
        }
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    return true;
}

long long file_size(const std::string& path) {
    struct stat st;
    if (stat(path.c_str(), &st) != 0) return -1;
    return static_cast<long long>(st.st_size);
}

std::string xdebug_home_from_session(const std::string& session_id) {
    std::string public_dir = xdebug_core::public_session_dir(session_id);
    return parent_dir(parent_dir(public_dir));
}

std::string component_session_dir(const std::string& component, const std::string& session_id) {
    return parent_dir(parent_dir(xdebug_core::component_log_path(component, session_id, "lifecycle")));
}

xdebug::Json log_paths_for_session(const std::string& session_id) {
    xdebug::Json paths;
    paths["public_session"] = xdebug_core::public_session_dir(session_id);
    paths["public_actions"] = xdebug_core::public_action_log_path(session_id);
    paths["public_stdio"] = xdebug_core::public_stdio_log_path(session_id);
    paths["engine_session"] = component_session_dir("engine", session_id);
    paths["engine_lifecycle"] = xdebug_core::component_log_path("engine", session_id, "lifecycle");
    paths["engine_transport"] = xdebug_core::component_log_path("engine", session_id, "transport");
    paths["engine_crash_marker"] = xdebug_core::component_log_path("engine", session_id, "crash_marker");
    paths["engine_npi_startup"] =
        parent_dir(paths["engine_lifecycle"].get<std::string>()) + "/npi_startup.log";
    paths["engine_log_health"] = parent_dir(paths["engine_lifecycle"].get<std::string>()) + "/log_health.ndjson";
    paths["public_log_health"] = parent_dir(paths["public_actions"].get<std::string>()) + "/log_health.ndjson";
    return paths;
}

xdebug::Json log_doctor_response(const std::string& session_id) {
    xdebug::Json response;
    response["ok"] = true;
    response["action"] = "log.doctor";
    response["summary"] = {{"session_id", session_id}};
    xdebug::Json paths = log_paths_for_session(session_id);
    xdebug::Json rows = xdebug::Json::array();
    for (auto it = paths.begin(); it != paths.end(); ++it) {
        std::string path = it.value().get<std::string>();
        rows.push_back({{"name", it.key()}, {"path", path}, {"exists", file_exists(path)}, {"bytes", file_size(path)}});
    }
    response["data"] = {{"logs", rows}};
    return response;
}

void print_log_tail_file(const std::string& name, const std::string& path, int lines) {
    std::ifstream in(path.c_str());
    if (!in) return;
    std::deque<std::string> tail;
    std::string line;
    while (std::getline(in, line)) {
        tail.push_back(line);
        while (static_cast<int>(tail.size()) > lines) tail.pop_front();
    }
    if (tail.empty()) return;
    std::cout << "== " << name << " " << path << " ==\n";
    for (const auto& item : tail) std::cout << item << "\n";
}

int run_log_tail(const std::string& session_id, int lines) {
    xdebug::Json paths = log_paths_for_session(session_id);
    for (const char* name : {"public_actions", "public_stdio", "engine_lifecycle", "engine_transport",
                             "engine_crash_marker", "engine_npi_startup"}) {
        print_log_tail_file(name, paths[name].get<std::string>(), lines);
    }
    return 0;
}

int run_log_bundle(const std::string& session_id, const std::string& out_path) {
    std::string home = xdebug_home_from_session(session_id);
    xdebug::Json paths = log_paths_for_session(session_id);
    std::vector<std::string> rels;
    for (const char* name : {"public_session", "engine_session"}) {
        std::string path = paths[name].get<std::string>();
        if (file_exists(path) && path.compare(0, home.size() + 1, home + "/") == 0) {
            rels.push_back(path.substr(home.size() + 1));
        }
    }
    if (rels.empty()) {
        std::cerr << "no log directories found for session: " << session_id << "\n";
        return 1;
    }
    xdebug::ProcessRequest req;
    req.executable = "tar";
    req.argv.push_back("-czf");
    req.argv.push_back(out_path);
    req.argv.push_back("-C");
    req.argv.push_back(home);
    for (const auto& rel : rels) req.argv.push_back(rel);
    req.timeout_ms = 30000;
    xdebug::ProcessResult result = xdebug::ProcessRunner().run(req);
    if (result.exit_code != 0) {
        std::cerr << result.stderr_text;
        return result.exit_code == 0 ? 1 : result.exit_code;
    }
    std::cout << out_path << "\n";
    return 0;
}

bool write_redacted_log_copy(const std::string& source, const std::string& dest) {
    std::ifstream in(source.c_str());
    if (!in) return false;
    if (!ensure_dir_recursive(parent_dir(dest))) return false;
    std::ofstream out(dest.c_str(), std::ios::trunc);
    if (!out) return false;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) {
            out << "\n";
            continue;
        }
        try {
            xdebug_core::Json j = xdebug_core::Json::parse(line);
            out << xdebug_core::sanitize_for_log(j).dump() << "\n";
        } catch (...) {
            out << line << "\n";
        }
    }
    return true;
}

int run_redacted_log_bundle(const std::string& session_id, const std::string& out_path) {
    std::string old_mode = xdebug_core::xdebug_log_path_mode();
    setenv("XDEBUG_LOG_PATH_MODE", "hash", 1);
    std::string tmp = xdebug_core::temporary_dir() + "/xdebug-log-bundle-" + std::to_string(getpid());
    ensure_dir_recursive(tmp);
    xdebug::Json paths = log_paths_for_session(session_id);
    for (const char* name : {"public_actions", "public_stdio", "engine_lifecycle", "engine_transport",
                             "engine_crash_marker", "engine_log_health", "public_log_health"}) {
        std::string source = paths[name].get<std::string>();
        if (!file_exists(source)) continue;
        write_redacted_log_copy(source, tmp + "/" + std::string(name) + ".ndjson");
    }
    if (!old_mode.empty()) setenv("XDEBUG_LOG_PATH_MODE", old_mode.c_str(), 1);
    else unsetenv("XDEBUG_LOG_PATH_MODE");

    xdebug::ProcessRequest req;
    req.executable = "tar";
    req.argv.push_back("-czf");
    req.argv.push_back(out_path);
    req.argv.push_back("-C");
    req.argv.push_back(tmp);
    req.argv.push_back(".");
    req.timeout_ms = 30000;
    xdebug::ProcessResult result = xdebug::ProcessRunner().run(req);
    if (result.exit_code != 0) {
        std::cerr << result.stderr_text;
        return result.exit_code == 0 ? 1 : result.exit_code;
    }
    std::cout << out_path << "\n";
    return 0;
}

int run_log_command(int argc, char** argv, OutputFormat format) {
    if (argc < 3) {
        std::cerr << "usage: xdebug log tail|doctor|bundle --session <id> [--lines N] [--out file]\n";
        return 1;
    }
    std::string sub(argv[2]);
    std::string session_id;
    std::string out_path;
    int lines = 40;
    bool redact = false;
    for (int i = 3; i < argc; ++i) {
        std::string arg(argv[i]);
        if (arg == "--session" && i + 1 < argc) session_id = argv[++i];
        else if (arg == "--out" && i + 1 < argc) out_path = argv[++i];
        else if (arg == "--lines" && i + 1 < argc) lines = std::atoi(argv[++i]);
        else if (arg == "--redact") redact = true;
        else if (arg == "--json") format = OutputFormat::Json;
        else {
            std::cerr << "unknown log argument: " << arg << "\n";
            return 1;
        }
    }
    if (session_id.empty()) {
        std::cerr << "missing --session\n";
        return 1;
    }
    if (sub == "doctor") {
        print_response(log_doctor_response(session_id), format);
        return 0;
    }
    if (sub == "tail") return run_log_tail(session_id, lines <= 0 ? 40 : lines);
    if (sub == "bundle") {
        if (out_path.empty()) {
            std::cerr << "missing --out\n";
            return 1;
        }
        if (redact) return run_redacted_log_bundle(session_id, out_path);
        return run_log_bundle(session_id, out_path);
    }
    std::cerr << "unknown log subcommand: " << sub << "\n";
    return 1;
}

} // namespace

int main(int argc, char** argv) {
    if (argc == 2) {
        std::string arg(argv[1]);
        if (arg == "-h" || arg == "-help") {
            std::cout << xdebug::help_text();
            return 0;
        }
    }

    CliOptions options;
    options.format = env_wants_json() ? OutputFormat::Json : OutputFormat::Xout;
    if (argc >= 2 && std::string(argv[1]) == "log") {
        return run_log_command(argc, argv, options.format);
    }
    bool stdio_loop = false;
    for (int i = 1; i < argc; ++i) {
        std::string arg(argv[i]);
        if (arg == "--stdio-loop") {
            stdio_loop = true;
        } else if (arg == "--json") {
            options.format = OutputFormat::Json;
        } else if (arg == "--text" || arg == "--xout") {
            options.format = OutputFormat::Xout;
        } else if (options.input_arg.empty()) {
            options.input_arg = arg;
        } else {
            xdebug::Json request = xdebug::Json::object();
            xdebug::Json response = xdebug::make_error(request, "", "JSON_ONLY",
                                                       "usage: xdebug [--json|--text] [request.json|-]");
            print_response(response, options.format);
            return 1;
        }
    }

    if (stdio_loop) {
        return xdebug::run_stdio_loop(executable_dir(),
                                      options.format == OutputFormat::Json);
    }

    std::string input;
    if (options.input_arg.empty() || options.input_arg == "-") {
        input = read_stream(std::cin);
    } else {
        std::ifstream file(options.input_arg);
        if (!file) {
            xdebug::Json request = xdebug::Json::object();
            xdebug::Json response = xdebug::make_error(request, "", "INVALID_INPUT",
                                                       "failed to open JSON request file");
            print_response(response, options.format);
            return 1;
        }
        input = read_stream(file);
    }

    xdebug::Json request;
    std::string error;
    if (!xdebug::parse_request_text(input, request, error)) {
        xdebug::Json response = xdebug::make_error(xdebug::Json::object(), "", "INVALID_JSON", error);
        xdebug_core::log_action_event("public", "xdebug", "adhoc", "", "parse_failed", false, 0,
                                      {{"error", response["error"]}});
        print_response(response, options.format);
        return 1;
    }
    std::string action;
    if (!xdebug::validate_request(request, action, error)) {
        const std::string code = request.value("api_version", std::string()) == xdebug::kApiVersion
            ? "INVALID_REQUEST" : "UNSUPPORTED_API_VERSION";
        xdebug::Json response = xdebug::make_error(request, request.value("action", std::string()),
                                                   code, error, false);
        xdebug_core::log_action_event("public", "xdebug", "adhoc", request.value("action", std::string()),
                                      "validate_failed", false, 0,
                                      {{"request", xdebug_core::sanitize_for_log(request)}, {"error", response["error"]}});
        print_response(response, options.format);
        return 1;
    }

    xdebug::Dispatcher dispatcher(executable_dir());
    xdebug::Json response = dispatcher.dispatch(request);
    print_response(response, options.format, dispatcher.last_xout());
    return response.value("ok", false) ? 0 : 1;
}
