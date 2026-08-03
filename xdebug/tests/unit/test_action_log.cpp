#include "logging/action_log.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <dirent.h>
#include <fstream>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

using xdebug_core::Json;

static std::string read_file(const std::string& path) {
    std::ifstream in(path.c_str());
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

static Json read_last_json_line(const std::string& path) {
    std::ifstream in(path.c_str());
    std::string line;
    std::string last;
    while (std::getline(in, line)) {
        if (!line.empty()) last = line;
    }
    assert(!last.empty());
    return Json::parse(last);
}

static std::vector<Json> read_json_lines(const std::string& path) {
    std::ifstream in(path.c_str());
    std::vector<Json> rows;
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty()) rows.push_back(Json::parse(line));
    }
    return rows;
}

static bool exists(const std::string& path) {
    return access(path.c_str(), F_OK) == 0;
}

static std::vector<std::string> read_regular_files(
    const std::string& directory) {
    std::vector<std::string> contents;
    DIR* dir = opendir(directory.c_str());
    assert(dir != nullptr);
    while (dirent* entry = readdir(dir)) {
        const std::string name = entry->d_name;
        if (name == "." || name == "..") continue;
        const std::string path = directory + "/" + name;
        struct stat st;
        if (stat(path.c_str(), &st) == 0 && S_ISREG(st.st_mode)) {
            contents.push_back(read_file(path));
        }
    }
    closedir(dir);
    return contents;
}

int main() {
    std::vector<char> home_storage = test_temp_template("xdebug_action_log_test_XXXXXX");
    char* home_dir = mkdtemp(home_storage.data());
    assert(home_dir != nullptr);
    std::string home = home_dir;
    setenv("HOME", home.c_str(), 1);
    unsetenv("XDEBUG_LOG_PATH_MODE");
    unsetenv("XDEBUG_LOG_REDACT");

    Json request = {
        {"api_version", "xdebug.v1"},
        {"request_id", "case-a-1"},
        {"observability", {
            {"trace_id", "trace-case-a"},
            {"span_id", "span-dispatch"}
        }},
        {"action", "value.at"},
        {"target", {{"session_id", "case_a"}, {"daidir", "fixtures/foo.daidir"}}},
        {"args", {{"signal", "top.u.ready"}, {"time", "75ns"}, {"value_format", "hex"},
                  {"include_trace", true}, {"samples", Json::array({1, 2, 3})}}},
        {"output", {{"verbosity", "compact"}}}
    };
    Json response = {
        {"ok", false},
        {"request_id", "case-a-1"},
        {"action", "value.at"},
        {"summary", {
            {"signal", "top.u.ready"},
            {"scan_complete", true},
            {"analysis_complete", true},
            {"response_truncated", false},
            {"total_count", 1},
            {"returned_count", 1},
            {"truncation_scopes", Json::array()}
        }},
        {"data", {{"trace", Json::array({1, 2, 3})}, {"small", true}}},
        {"error", {{"code", "SIGNAL_NOT_FOUND"}, {"message", "missing"}}}
    };

    Json sanitized = xdebug_core::sanitize_for_log(response);
    assert(sanitized["data"]["trace"] == "<omitted:large-field>");
    assert(sanitized.value("log_truncated", false));

    xdebug_core::update_public_session_manifest("case_a", "design", "fixtures/foo.daidir", "");
    std::string manifest_path = xdebug_core::public_session_dir("case_a") + "/session.json";
    Json manifest = Json::parse(read_file(manifest_path));
    assert(manifest["session_id"] == "case_a");
    assert(manifest["mode"] == "design");
    assert(manifest["daidir"] == "fixtures/foo.daidir");
    assert(manifest["logs"]["public_actions"] == xdebug_core::public_action_log_path("case_a"));
    assert(manifest["logs"]["public_stdio"] == xdebug_core::public_stdio_log_path("case_a"));

    Json summary = xdebug_core::request_summary_for_log(request);
    assert(summary["request_id"] == "case-a-1");
    assert(summary["trace_id"] == "trace-case-a");
    assert(summary["args"]["signal"] == "top.u.ready");
    assert(summary["args"]["time"] == "75ns");
    assert(summary["args"]["value_format"] == "hex");
    assert(!summary["args"].contains("include_trace"));
    assert(!summary["args"].contains("samples"));
    assert(
        summary["target"]["daidir"].get<std::string>().find(
            "<path:sha256:") == 0);

    setenv("XDEBUG_LOG_PATH_MODE", "basename", 1);
    Json basename_summary = xdebug_core::request_summary_for_log(request);
    assert(basename_summary["target"]["daidir"] == "foo.daidir");
    setenv("XDEBUG_LOG_PATH_MODE", "hash", 1);
    Json hash_summary = xdebug_core::request_summary_for_log(request);
    assert(hash_summary["target"]["daidir"].get<std::string>().find("<path:sha256:") == 0);
    setenv("XDEBUG_LOG_PATH_MODE", "invalid-mode", 1);
    Json invalid_mode_summary =
        xdebug_core::request_summary_for_log(request);
    assert(
        invalid_mode_summary["target"]["daidir"]
            .get<std::string>()
            .find("<path:sha256:") == 0);
    unsetenv("XDEBUG_LOG_PATH_MODE");

    const std::string sensitive_value =
        "managed-token-value-must-never-reach-a-log";
    Json sensitive_diagnostic = {
        {"invalid_arg", "args.ownership_token"},
        {"received", sensitive_value},
        {"received_type", "string"},
        {"message", "bad token: " + sensitive_value},
        {"correct_example", {
            {"args", {
                {"name", "managed"},
                {"ownership_token", sensitive_value},
            }},
        }},
    };
    Json sanitized_sensitive =
        xdebug_core::sanitize_for_log(sensitive_diagnostic);
    assert(
        sanitized_sensitive.dump().find(sensitive_value) ==
        std::string::npos);
    assert(sanitized_sensitive["sensitive_values_redacted"] == true);
    assert(!sanitized_sensitive.contains("received"));
    Json opaque_evidence = xdebug_core::sanitize_for_log({
        {"exception", sensitive_value},
        {"raw_response", sensitive_value},
    });
    for (const char* key : {"exception", "raw_response"}) {
        assert(opaque_evidence[key]["present"] == true);
        assert(
            opaque_evidence[key]["bytes"] ==
            sensitive_value.size());
        assert(
            opaque_evidence[key]["sha256"]
                .get<std::string>()
                .size() == 64);
    }
    assert(
        opaque_evidence.dump().find(sensitive_value) ==
        std::string::npos);

    xdebug_core::log_action_event("public", "xdebug", "case_a", "value.at", "end", false, 12,
                                  {{"request", xdebug_core::request_summary_for_log(request)},
                                   {"response", xdebug_core::response_summary_for_log(response)},
                                   {"request_compact", xdebug_core::sanitize_for_log(request)},
                                   {"response_compact", xdebug_core::sanitize_for_log(response)}});
    Json event = read_last_json_line(xdebug_core::public_action_log_path("case_a"));
    assert(event["layer"] == "public");
    assert(event["component"] == "xdebug");
    assert(event["session_id"] == "case_a");
    assert(event["request_id"] == "case-a-1");
    assert(event["trace_id"] == "trace-case-a");
    assert(event["action"] == "value.at");
    assert(event["phase"] == "end");
    assert(event["ok"] == false);
    assert(event["elapsed_ms"] == 12);

    xdebug_core::log_lifecycle_event("waveform", "case_a", "npi_fsdb_open.failed", false,
                                     {{"fsdb", "fixtures/a.fsdb"}});
    Json lifecycle_event = read_last_json_line(xdebug_core::component_log_path("waveform", "case_a", "lifecycle"));
    assert(lifecycle_event["component"] == "waveform");
    assert(lifecycle_event["phase"] == "npi_fsdb_open.failed");

    xdebug_core::log_stdio_event("case_a", "loop.validate_failed", false,
                                 {{"request_id", "stdio-1"}, {"action", "actions"},
                                  {"error", {{"code", "UNSUPPORTED_API_VERSION"}}}});
    Json stdio_event = read_last_json_line(xdebug_core::public_stdio_log_path("case_a"));
    assert(stdio_event["component"] == "xdebug");
    assert(stdio_event["request_id"] == "stdio-1");
    assert(stdio_event["phase"] == "loop.validate_failed");

    Json huge = request;
    huge["request_id"] = "huge-1";
    Json huge_rsp = response;
    huge_rsp["request_id"] = "huge-1";
    huge["args"]["ownership_token"] = sensitive_value;
    huge_rsp["error"] = sensitive_diagnostic;
    for (int i = 0; i < 150; ++i) {
        huge["args"][std::string("field_") + std::to_string(i)] = std::string(4096, 'x');
        huge_rsp["data"][std::string("field_") + std::to_string(i)] = std::string(4096, 'y');
    }
    xdebug_core::log_action_event("public", "xdebug", "huge_case", "value.at", "end", false, 9,
                                  {{"request", xdebug_core::request_summary_for_log(huge)},
                                   {"response", xdebug_core::response_summary_for_log(huge_rsp)},
                                   {"request_compact", huge},
                                   {"response_compact", huge_rsp}});
    Json huge_event = read_last_json_line(xdebug_core::public_action_log_path("huge_case"));
    assert(huge_event.value("log_truncated", false));
    assert(huge_event.contains("payload_sidecars"));
    assert(huge_event["payload_sidecars"].contains("request_compact"));
    assert(huge_event["payload_sidecars"].contains("response_compact"));
    for (const char* key : {"request_compact", "response_compact"}) {
        const Json sidecar =
            huge_event["payload_sidecars"][key];
        assert(
            sidecar["path"].get<std::string>().find(
                "<path:sha256:") == 0);
        assert(sidecar["sha256"].is_string());
        assert(sidecar["sha256"].get<std::string>().size() == 64);
    }
    const std::string payload_dir =
        xdebug_core::public_session_dir("huge_case") +
        "/logs/actions_payload";
    const std::vector<std::string> payloads =
        read_regular_files(payload_dir);
    assert(payloads.size() >= 2);
    for (const std::string& payload : payloads) {
        assert(payload.find(sensitive_value) == std::string::npos);
    }
    assert(
        read_file(xdebug_core::public_action_log_path("huge_case"))
            .find(sensitive_value) == std::string::npos);

    xdebug_core::log_action_event(
        "public",
        "xdebug",
        "health_case",
        "actions",
        "begin",
        true,
        0,
        Json::object());
    const std::string health_payload_dir =
        xdebug_core::public_session_dir("health_case") +
        "/logs/actions_payload";
    {
        std::ofstream blocker(health_payload_dir.c_str());
        assert(blocker.good());
        blocker << "block sidecar directory creation\n";
    }
    xdebug_core::log_action_event(
        "public",
        "xdebug",
        "health_case",
        "actions",
        "end",
        false,
        1,
        {{"request_compact", huge},
         {"response_compact", huge_rsp}});
    const std::string health_log =
        xdebug_core::public_session_dir("health_case") +
        "/logs/log_health.ndjson";
    const std::vector<Json> health_events =
        read_json_lines(health_log);
    assert(!health_events.empty());
    for (const Json& health : health_events) {
        assert(
            health["log_path"].get<std::string>().find(
                "<path:sha256:") == 0);
        assert(
            health.dump().find(health_payload_dir) ==
            std::string::npos);
        assert(
            health.dump().find(sensitive_value) ==
            std::string::npos);
    }

    setenv("XDEBUG_LOG_MAX_BYTES", "1200", 1);
    setenv("XDEBUG_LOG_MAX_FILES", "2", 1);
    for (int i = 0; i < 8; ++i) {
        xdebug_core::log_action_event("public", "xdebug", "rotate_case", "actions", "end", true, i,
                                      {{"request_id", std::string("rotate-") + std::to_string(i)},
                                       {"padding", std::string(300, 'r')}});
    }
    unsetenv("XDEBUG_LOG_MAX_BYTES");
    unsetenv("XDEBUG_LOG_MAX_FILES");
    assert(exists(xdebug_core::public_action_log_path("rotate_case") + ".1"));

    const int child_count = 4;
    const int events_per_child = 20;
    for (int child = 0; child < child_count; ++child) {
        pid_t pid = fork();
        assert(pid >= 0);
        if (pid == 0) {
            for (int i = 0; i < events_per_child; ++i) {
                xdebug_core::log_action_event("public", "xdebug", "concurrent_case", "actions", "end", true, i,
                                              {{"request_id", std::string("child-") + std::to_string(child) +
                                                               "-" + std::to_string(i)}});
            }
            _exit(0);
        }
    }
    for (int child = 0; child < child_count; ++child) {
        int status = 0;
        assert(wait(&status) > 0);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    std::vector<Json> concurrent = read_json_lines(xdebug_core::public_action_log_path("concurrent_case"));
    assert(concurrent.size() == static_cast<size_t>(child_count * events_per_child));
    for (const auto& row : concurrent) {
        assert(row["session_id"] == "concurrent_case");
        assert(row["phase"] == "end");
    }

    return 0;
}
