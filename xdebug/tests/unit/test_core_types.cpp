#include "ai/ai_response.h"
#include "common/path_utils.h"
#include "npi/time_contract.h"
#include "protocol/core_protocol.h"
#include "session/session_endpoint_contract.h"
#include "session/request_deadline.h"
#include "session/session_timeout.h"
#include "session/transport_common.h"
#include "session/session_types.h"
#include "test_temp_path.h"

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct ScriptedReadStep {
    ssize_t result;
    int error;
};

std::vector<ScriptedReadStep> g_read_steps;
size_t g_read_step = 0;
unsigned char g_next_random_byte = 0;

ssize_t scripted_secure_random_read(int, void* buffer, size_t size) {
    assert(g_read_step < g_read_steps.size());
    const ScriptedReadStep step = g_read_steps[g_read_step++];
    if (step.result < 0) {
        errno = step.error;
        return step.result;
    }
    const size_t count = static_cast<size_t>(step.result);
    assert(count <= size);
    unsigned char* bytes = static_cast<unsigned char*>(buffer);
    for (size_t i = 0; i < count; ++i) {
        bytes[i] = g_next_random_byte++;
    }
    return step.result;
}

}  // namespace

int main() {
    assert(!xdebug_core::request_deadline_expired());
    {
        xdebug_core::ScopedRequestDeadline deadline(
            std::chrono::steady_clock::now() -
            std::chrono::milliseconds(1));
        assert(xdebug_core::request_deadline_expired());
        bool threw = false;
        try {
            xdebug_core::request_deadline_checkpoint();
        } catch (const xdebug_core::RequestDeadlineExceeded&) {
            threw = true;
        }
        assert(threw);
        {
            xdebug_core::ScopedRequestDeadline nested(1000);
            assert(xdebug_core::request_deadline_expired());
        }
        assert(xdebug_core::request_deadline_expired());
    }
    assert(!xdebug_core::request_deadline_expired());

    unsigned char random_bytes[8] = {};
    std::string random_error;
    g_read_steps = {{-1, EINTR}, {2, 0}, {1, 0}, {5, 0}};
    g_read_step = 0;
    g_next_random_byte = 0;
    assert(xdebug_core::fill_secure_random_bytes(
        0, random_bytes, sizeof(random_bytes), random_error,
        scripted_secure_random_read));
    assert(g_read_step == g_read_steps.size());
    for (size_t i = 0; i < sizeof(random_bytes); ++i) {
        assert(random_bytes[i] == static_cast<unsigned char>(i));
    }

    g_read_steps = {{2, 0}, {0, 0}};
    g_read_step = 0;
    g_next_random_byte = 0;
    random_error.clear();
    assert(!xdebug_core::fill_secure_random_bytes(
        0, random_bytes, sizeof(random_bytes), random_error,
        scripted_secure_random_read));
    assert(random_error.find("ended before") != std::string::npos);

    g_read_steps = {{-1, EIO}};
    g_read_step = 0;
    random_error.clear();
    assert(!xdebug_core::fill_secure_random_bytes(
        0, random_bytes, sizeof(random_bytes), random_error,
        scripted_secure_random_read));
    assert(random_error.find("failed to read") != std::string::npos);

    std::string auth_token;
    assert(xdebug_core::generate_auth_token(auth_token, random_error));
    assert(auth_token.size() == 48);
    for (const char c : auth_token) {
        assert((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'));
    }

    xdebug_core::TimeRenderUnit render_unit = xdebug_core::TimeRenderUnit::Ns;
    std::string render_unit_error;
    assert(xdebug_core::parse_time_render_unit(
        "auto", render_unit, render_unit_error));
    assert(render_unit == xdebug_core::TimeRenderUnit::Auto);
    assert(xdebug_core::parse_time_render_unit(
        "ps", render_unit, render_unit_error));
    assert(render_unit == xdebug_core::TimeRenderUnit::Ps);
    assert(xdebug_core::parse_time_render_unit(
        "ns", render_unit, render_unit_error));
    assert(render_unit == xdebug_core::TimeRenderUnit::Ns);
    assert(xdebug_core::parse_time_render_unit(
        "us", render_unit, render_unit_error));
    assert(render_unit == xdebug_core::TimeRenderUnit::Us);
    for (const char* invalid : {"", "n", "NS", "fs", "ms", "s"}) {
        render_unit_error.clear();
        assert(!xdebug_core::parse_time_render_unit(
            invalid, render_unit, render_unit_error));
        assert(!render_unit_error.empty());
    }

    xdebug_core::ToolConfig config = xdebug_core::make_tool_config("xdebug", ".xdebug", "xdebug", "1.0");
    assert(config.tool_name == "xdebug");
    assert(config.home_dir_name == ".xdebug");

    xdebug_core::SessionInfo session;
    session.dbdir_path = "fixtures/simv.daidir";
    assert(session.database_kind() == xdebug_core::DatabaseKind::Daidir);
    assert(std::string(xdebug_core::database_kind_name(session.database_kind())) == "daidir");

    session.dbdir_path.clear();
    session.fsdb_file = "fixtures/waves.fsdb";
    assert(session.database_kind() == xdebug_core::DatabaseKind::Fsdb);
    assert(std::string(xdebug_core::database_kind_name(session.database_kind())) == "fsdb");

    session.dbdir_path = "fixtures/simv.daidir";
    assert(session.database_kind() == xdebug_core::DatabaseKind::Combined);
    assert(std::string(xdebug_core::database_kind_name(session.database_kind())) == "combined");

    xdebug_core::AiResponse error = xdebug_core::make_ai_error("trace.driver", "failed");
    assert(!error.ok);
    assert(error.action == "trace.driver");

    assert(std::string(xdebug_core::CMD_PING) == "PING");
    assert(xdebug_core::registry_path(config).find(".xdebug/registry.json") != std::string::npos);
    assert(xdebug_core::is_valid_session_name("A"));
    assert(xdebug_core::is_valid_session_name("case_1"));
    assert(xdebug_core::is_valid_session_name("Case_0123456789_abc"));
    assert(xdebug_core::is_valid_session_name(std::string("A") + std::string(63, 'x')));
    assert(!xdebug_core::is_valid_session_name(""));
    assert(!xdebug_core::is_valid_session_name("1case"));
    assert(!xdebug_core::is_valid_session_name("_case"));
    assert(!xdebug_core::is_valid_session_name("case-a"));
    assert(!xdebug_core::is_valid_session_name("case.a"));
    assert(!xdebug_core::is_valid_session_name("case a"));
    assert(!xdebug_core::is_valid_session_name(std::string("A") + std::string(64, 'x')));
    const std::string dir_name = xdebug_core::session_dir_name("abcdefghijklmnopXYZ");
    assert(dir_name.find("abcdefghijklmnop_") == 0);
    assert(dir_name.size() == 16 + 1 + 16);
    assert(dir_name == xdebug_core::session_dir_name("abcdefghijklmnopXYZ"));
    assert(dir_name != xdebug_core::session_dir_name("abcdefghijklmnopXYA"));
    assert(xdebug_core::session_dir_name("bad/name").find("bad_name_") == 0);
    assert(xdebug_core::socket_path(config, "case_a").find(".xdebug/sessions/case_a_") != std::string::npos);
    const char* old_home = std::getenv("HOME");
    const std::string saved_home = old_home ? old_home : "";
    const std::string long_home = test_temp_root() +
        "/pytest-of-user/pytest-999/test_a_very_long_xdebug_session_home_path/home";
    setenv("HOME", long_home.c_str(), 1);
    const std::string short_socket = xdebug_core::socket_path(config, "case_a");
    assert(short_socket.find(test_temp_root() + "/xdebug-") == 0);
    assert(short_socket.size() < 104);

    const char* old_test_tmp = std::getenv("XVERIF_TEST_TMPDIR");
    const std::string saved_test_tmp = old_test_tmp ? old_test_tmp : "";
    const std::string runtime_home = test_temp_root() + "/runtime_home";
    mkdir(runtime_home.c_str(), 0700);
    unsetenv("XVERIF_TEST_TMPDIR");
    setenv("HOME", runtime_home.c_str(), 1);
    assert(xdebug_core::temporary_dir() == runtime_home + "/.xdebug/tmp");
    if (old_test_tmp) setenv("XVERIF_TEST_TMPDIR", saved_test_tmp.c_str(), 1);
    else unsetenv("XVERIF_TEST_TMPDIR");
    if (old_home) setenv("HOME", saved_home.c_str(), 1);
    else unsetenv("HOME");

    assert(xdebug_core::resource_content_matches(100, 4096, 100, 4096));
    assert(!xdebug_core::resource_identity_differs(10, 20, 10, 20));
    assert(xdebug_core::resource_identity_differs(10, 20, 11, 20));
    assert(xdebug_core::resource_identity_differs(10, 20, 10, 21));
    assert(!xdebug_core::resource_content_matches(100, 4096, 101, 4096));
    assert(!xdebug_core::resource_content_matches(100, 4096, 100, 8192));
    assert(!xdebug_core::resource_content_matches(
        100000000001LL, 4096, 100000000002LL, 4096));

    xdebug_core::SessionEndpointJson endpoint_json;
    std::string endpoint_error;
    xdebug_core::SessionInfo endpoint;
    endpoint.session_id = "case_1";
    endpoint.transport = "uds";
    endpoint.socket_path = "session-endpoints/case_1.sock";
    endpoint.server_host = "worker";
    assert(xdebug_core::session_endpoint_document_to_json(
        endpoint, endpoint_json, endpoint_error));
    assert(endpoint_json == xdebug_core::SessionEndpointJson({
        {"version", 1},
        {"endpoint", {
            {"transport", "uds"},
            {"socket_path", "session-endpoints/case_1.sock"},
            {"server_host", "worker"},
        }},
    }));
    xdebug_core::SessionInfo parsed_endpoint;
    assert(xdebug_core::session_endpoint_document_from_json(
        endpoint_json, "case_1", parsed_endpoint, endpoint_error));
    assert(parsed_endpoint.transport == "uds");
    assert(parsed_endpoint.socket_path == "session-endpoints/case_1.sock");

    endpoint.transport = "tcp";
    endpoint.socket_path.clear();
    endpoint.host = "worker";
    endpoint.bind_host = "127.0.0.1";
    endpoint.port = 43123;
    endpoint.auth_token = "secret";
    assert(xdebug_core::session_endpoint_document_to_json(
        endpoint, endpoint_json, endpoint_error));
    assert(endpoint_json["endpoint"].size() == 6);
    assert(!endpoint_json["endpoint"].contains("socket_path"));
    assert(xdebug_core::session_endpoint_document_from_json(
        endpoint_json, "case_1", parsed_endpoint, endpoint_error));
    assert(parsed_endpoint.port == 43123);
    assert(parsed_endpoint.auth_token == "secret");

    endpoint.transport = "file";
    endpoint.host.clear();
    endpoint.bind_host.clear();
    endpoint.port = 0;
    endpoint.auth_token.clear();
    endpoint.file_dir = "session-endpoints/case_1.exchange";
    assert(xdebug_core::session_endpoint_document_to_json(
        endpoint, endpoint_json, endpoint_error));
    assert(endpoint_json["endpoint"].size() == 3);
    assert(xdebug_core::session_endpoint_document_from_json(
        endpoint_json, "case_1", parsed_endpoint, endpoint_error));
    assert(parsed_endpoint.file_dir == "session-endpoints/case_1.exchange");

    auto invalid_endpoint = endpoint_json;
    invalid_endpoint["endpoint"]["socket_path"] = "session-endpoints/alias.sock";
    assert(!xdebug_core::session_endpoint_document_from_json(
        invalid_endpoint, "case_1", parsed_endpoint, endpoint_error));
    invalid_endpoint = endpoint_json;
    invalid_endpoint["version"] = 2;
    assert(!xdebug_core::session_endpoint_document_from_json(
        invalid_endpoint, "case_1", parsed_endpoint, endpoint_error));
    invalid_endpoint = endpoint_json;
    invalid_endpoint["endpoint"]["file_dir"] = "";
    assert(!xdebug_core::session_endpoint_document_from_json(
        invalid_endpoint, "case_1", parsed_endpoint, endpoint_error));
    invalid_endpoint = endpoint_json;
    invalid_endpoint["endpoint"]["transport"] = "uds";
    assert(!xdebug_core::session_endpoint_document_from_json(
        invalid_endpoint, "case_1", parsed_endpoint, endpoint_error));

    unsetenv("XDEBUG_SESSION_IDLE_TIMEOUT_SEC");
    unsetenv("XDEBUG_SESSION_START_TIMEOUT_SEC");
    int timeout = 0;
    std::string timeout_error;
    assert(xdebug_core::session_idle_timeout_sec(timeout, timeout_error));
    assert(timeout == 86400);
    assert(xdebug_core::session_start_timeout_sec(timeout, timeout_error));
    assert(timeout == 300);
    assert(setenv("XDEBUG_SESSION_IDLE_TIMEOUT_SEC", "7", 1) == 0);
    assert(xdebug_core::session_idle_timeout_sec(timeout, timeout_error));
    assert(timeout == 7);
    assert(setenv("XDEBUG_SESSION_START_TIMEOUT_SEC", "11", 1) == 0);
    assert(xdebug_core::session_start_timeout_sec(timeout, timeout_error));
    assert(timeout == 11);
    assert(setenv("XDEBUG_SESSION_IDLE_TIMEOUT_SEC", "0", 1) == 0);
    timeout_error.clear();
    assert(!xdebug_core::session_idle_timeout_sec(timeout, timeout_error));
    assert(timeout_error.find("XDEBUG_SESSION_IDLE_TIMEOUT_SEC") != std::string::npos);
    assert(setenv("XDEBUG_SESSION_START_TIMEOUT_SEC", "abc", 1) == 0);
    timeout_error.clear();
    assert(!xdebug_core::session_start_timeout_sec(timeout, timeout_error));
    assert(timeout_error.find("XDEBUG_SESSION_START_TIMEOUT_SEC") != std::string::npos);
    unsetenv("XDEBUG_SESSION_IDLE_TIMEOUT_SEC");
    unsetenv("XDEBUG_SESSION_START_TIMEOUT_SEC");

    const char* strict_env_names[] = {
        "XDEBUG_FILE_TRANSPORT_TIMEOUT_MS",
        "XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS",
        "XDEBUG_FILE_POLL_INTERVAL_MS",
        "XDEBUG_FILE_MAX_JSON_BYTES",
        "XDEBUG_FILE_CLAIM_TIMEOUT_MS",
        "XDEBUG_FILE_KEEP_HISTORY",
        "XDEBUG_FILE_DONE_TTL_SEC",
        "XDEBUG_FILE_FAILED_TTL_SEC",
        "XDEBUG_LOG_MAX_BYTES",
        "XDEBUG_LOG_MAX_FILES",
        "XDEBUG_LOG_PATH_MODE",
        "XDEBUG_LOG_REDACT",
    };
    for (const char* name : strict_env_names) unsetenv(name);

    xdebug_core::FileTransportEnvConfig file_config;
    std::string config_error;
    assert(xdebug_core::xdebug_file_transport_env_config(
        file_config, config_error));
    assert(file_config.request_timeout_ms == 300000);
    assert(file_config.ping_timeout_ms == 2000);
    assert(file_config.poll_interval_ms == 20);
    assert(file_config.max_json_bytes == 67108864);
    assert(file_config.claim_timeout_ms == 600000);
    assert(file_config.keep_history);
    assert(file_config.done_ttl_sec == 7LL * 24LL * 60LL * 60LL);
    assert(file_config.failed_ttl_sec == 30LL * 24LL * 60LL * 60LL);

    assert(setenv("XDEBUG_FILE_TRANSPORT_TIMEOUT_MS", "700000", 1) == 0);
    assert(setenv("XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS", "17", 1) == 0);
    assert(setenv("XDEBUG_FILE_POLL_INTERVAL_MS", "9", 1) == 0);
    assert(setenv("XDEBUG_FILE_MAX_JSON_BYTES", "4096", 1) == 0);
    assert(setenv("XDEBUG_FILE_KEEP_HISTORY", "false", 1) == 0);
    assert(setenv("XDEBUG_FILE_DONE_TTL_SEC", "0", 1) == 0);
    assert(setenv("XDEBUG_FILE_FAILED_TTL_SEC", "11", 1) == 0);
    assert(xdebug_core::xdebug_file_transport_env_config(
        file_config, config_error));
    assert(file_config.request_timeout_ms == 700000);
    assert(file_config.ping_timeout_ms == 17);
    assert(file_config.poll_interval_ms == 9);
    assert(file_config.max_json_bytes == 4096);
    assert(file_config.claim_timeout_ms == 1400000);
    assert(!file_config.keep_history);
    assert(file_config.done_ttl_sec == 0);
    assert(file_config.failed_ttl_sec == 11);

    for (const char* name : strict_env_names) unsetenv(name);
    const char* invalid_file_env_names[] = {
        "XDEBUG_FILE_TRANSPORT_TIMEOUT_MS",
        "XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS",
        "XDEBUG_FILE_POLL_INTERVAL_MS",
        "XDEBUG_FILE_MAX_JSON_BYTES",
        "XDEBUG_FILE_CLAIM_TIMEOUT_MS",
        "XDEBUG_FILE_DONE_TTL_SEC",
        "XDEBUG_FILE_FAILED_TTL_SEC",
    };
    for (const char* name : invalid_file_env_names) {
        assert(setenv(name, "bad", 1) == 0);
        config_error.clear();
        assert(!xdebug_core::xdebug_file_transport_env_config(
            file_config, config_error));
        assert(config_error.find(name) != std::string::npos);
        unsetenv(name);
    }
    for (const char* value : {"", "20ms", "0", "10001"}) {
        assert(setenv("XDEBUG_FILE_POLL_INTERVAL_MS", value, 1) == 0);
        config_error.clear();
        assert(!xdebug_core::xdebug_file_transport_env_config(
            file_config, config_error));
        assert(config_error.find("XDEBUG_FILE_POLL_INTERVAL_MS") !=
               std::string::npos);
    }
    unsetenv("XDEBUG_FILE_POLL_INTERVAL_MS");
    for (const char* value : {"", "maybe"}) {
        assert(setenv("XDEBUG_FILE_KEEP_HISTORY", value, 1) == 0);
        config_error.clear();
        assert(!xdebug_core::xdebug_file_transport_env_config(
            file_config, config_error));
        assert(config_error.find("XDEBUG_FILE_KEEP_HISTORY") !=
               std::string::npos);
    }
    unsetenv("XDEBUG_FILE_KEEP_HISTORY");

    xdebug_core::LogEnvConfig log_config;
    assert(xdebug_core::xdebug_log_env_config(log_config, config_error));
    assert(log_config.max_bytes == 0);
    assert(log_config.max_files == 3);
    assert(log_config.path_mode.empty());
    assert(!log_config.redact);
    assert(setenv("XDEBUG_LOG_MAX_BYTES", "1024", 1) == 0);
    assert(setenv("XDEBUG_LOG_MAX_FILES", "5", 1) == 0);
    assert(setenv("XDEBUG_LOG_PATH_MODE", "basename", 1) == 0);
    assert(setenv("XDEBUG_LOG_REDACT", "true", 1) == 0);
    assert(xdebug_core::xdebug_log_env_config(log_config, config_error));
    assert(log_config.max_bytes == 1024);
    assert(log_config.max_files == 5);
    assert(log_config.path_mode == "basename");
    assert(log_config.redact);

    for (const char* name : strict_env_names) unsetenv(name);
    for (const char* name : {
             "XDEBUG_LOG_MAX_BYTES", "XDEBUG_LOG_MAX_FILES",
             "XDEBUG_LOG_PATH_MODE", "XDEBUG_LOG_REDACT"}) {
        assert(setenv(name, "invalid", 1) == 0);
        config_error.clear();
        assert(!xdebug_core::xdebug_log_env_config(
            log_config, config_error));
        assert(config_error.find(name) != std::string::npos);
        unsetenv(name);
    }
    assert(setenv("XDEBUG_FILE_POLL_INTERVAL_MS", "0", 1) == 0);
    bool strict_getter_threw = false;
    try {
        (void)xdebug_core::xdebug_file_poll_interval_ms();
    } catch (const std::invalid_argument& exc) {
        strict_getter_threw =
            std::string(exc.what()).find(
                "XDEBUG_FILE_POLL_INTERVAL_MS") != std::string::npos;
    }
    assert(strict_getter_threw);
    unsetenv("XDEBUG_FILE_POLL_INTERVAL_MS");
    assert(xdebug_core::xdebug_file_and_log_env_config_valid(config_error));
    return 0;
}
