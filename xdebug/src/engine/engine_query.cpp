#include "engine_query.h"

#include "api/response.h"
#include "core/common/env_config.h"

#include "session/client.h"
#include "session/session_manager.h"
#include "../design/protocol/protocol.h"
#include "../design/service/action_support.h"
#include "service/design_postprocess.h"

#include "json.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace xdebug_design {

namespace {

using OrderedJson = nlohmann::ordered_json;
using Json = nlohmann::json;
using xdebug_engine::SessionEnsureResult;
using xdebug_engine::SessionHealth;
using xdebug_engine::SessionHealthStatus;
using xdebug_engine::SessionInfo;
using xdebug_engine::SessionManager;
using xdebug_engine::SessionTransportOptions;
using xdebug_engine::send_request_capture;
using xdebug_engine::session_health_status_name;

std::string read_stream(std::istream& in) {
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

bool read_file(const std::string& path, std::string& out) {
    std::ifstream in(path.c_str());
    if (!in) return false;
    out = read_stream(in);
    return true;
}

OrderedJson make_response(const OrderedJson& request, const std::string& action, bool ok = true) {
    OrderedJson response;
    response["api_version"] = INTERNAL_API_VERSION;
    response["request_id"] = request.value("request_id", std::string());
    response["ok"] = ok;
    response["action"] = action;
    response["tool"] = xdebug::tool_metadata();
    response["session"] = nullptr;
    response["summary"] = OrderedJson::object();
    response["data"] = OrderedJson::object();
    response["error"] = nullptr;
    return response;
}

OrderedJson make_error(const OrderedJson& request,
                       const std::string& action,
                       const std::string& code,
                       const std::string& message,
                       bool recoverable = true,
                       const OrderedJson& details = OrderedJson::object()) {
    OrderedJson response = make_response(request, action, false);
    response["data"] = nullptr;
    response["error"] = {
        {"code", code},
        {"message", message},
        {"recoverable", recoverable},
        {"error_layer", "handler"}
    };
    if (details.is_object()) {
        for (auto it = details.begin(); it != details.end(); ++it) {
            response["error"][it.key()] = it.value();
        }
    }
    return response;
}

OrderedJson session_to_json(const SessionInfo& s) {
    return {
        {"id", s.session_id},
        {"session_id", s.session_id},
        {"dbdir", s.dbdir_path},
        {"dbdir_path", s.dbdir_path},
        {"design_file", s.design_file},
        {"fsdb", s.fsdb_file},
        {"fsdb_file", s.fsdb_file},
        {"pid", s.server_pid},
        {"transport", s.transport},
        {"socket_path", s.socket_path},
        {"file_dir", s.file_dir},
        {"host", s.host},
        {"bind_host", s.bind_host},
        {"port", s.port},
        {"server_host", s.server_host},
        {"created_at", static_cast<long long>(s.created_at)},
        {"last_active", static_cast<long long>(s.last_active)},
        {"dbdir_mtime", s.dbdir_mtime},
        {"dbdir_size", s.dbdir_size},
        {"dbdir_dev", s.dbdir_dev},
        {"dbdir_inode", s.dbdir_inode},
        {"fsdb_mtime", s.fsdb_mtime},
        {"fsdb_size", s.fsdb_size},
        {"fsdb_dev", s.fsdb_dev},
        {"fsdb_inode", s.fsdb_inode}
    };
}

SessionTransportOptions request_transport_options(const OrderedJson& request) {
    SessionTransportOptions transport;
    const OrderedJson target = request.value("target", OrderedJson::object());
    const OrderedJson args = request.value("args", OrderedJson::object());
    transport.transport = args.value("transport", target.value("transport", std::string()));
    transport.bind_host = args.value("bind_host", args.value("bind", target.value("bind_host", target.value("bind", std::string()))));
    transport.host = args.value("host", target.value("host", std::string()));
    transport.port = args.value("port", target.value("port", 0));
    return transport;
}

std::vector<std::string> target_resource_args(const OrderedJson& request) {
    std::vector<std::string> args;
    const OrderedJson target = request.value("target", OrderedJson::object());
    std::string dbdir = target.value("dbdir", target.value("daidir", std::string()));
    if (!dbdir.empty()) {
        args.push_back("-dbdir");
        args.push_back(dbdir);
    }
    std::string fsdb = target.value("fsdb", std::string());
    if (!fsdb.empty()) {
        args.push_back("-fsdb");
        args.push_back(fsdb);
    }
    return args;
}

std::string request_session_name(const OrderedJson& request) {
    const OrderedJson target = request.value("target", OrderedJson::object());
    const OrderedJson args = request.value("args", OrderedJson::object());
    if (args.contains("name") && args["name"].is_string()) return args["name"].get<std::string>();
    if (target.contains("name") && target["name"].is_string()) return target["name"].get<std::string>();
    return "";
}

std::string session_id_from_request(const OrderedJson& request) {
    const OrderedJson target = request.value("target", OrderedJson::object());
    if (target.contains("session_id") && target["session_id"].is_string()) return target["session_id"].get<std::string>();
    return "";
}

std::string ensure_error_code(const SessionEnsureResult& result) {
    if (result.status == "session_id_exists") return "SESSION_ID_EXISTS";
    if (result.status == "invalid_session_id") return "INVALID_SESSION_ID";
    if (result.status == "invalid_args") return "INVALID_REQUEST";
    if (result.status == "invalid_transport") return "INVALID_REQUEST";
    if (result.message.find("invalid_config:") != std::string::npos) return "INVALID_CONFIG";
    if (result.status == "npi_init_failed") return "NPI_INIT_FAILED";
    if (result.status == "npi_load_design_failed") return "NPI_LOAD_DESIGN_FAILED";
    if (result.status == "npi_fsdb_open_failed") return "NPI_FSDB_OPEN_FAILED";
    if (result.status == "startup_failed") return "ENGINE_START_FAILED";
    return "SESSION_UNHEALTHY";
}

OrderedJson session_open_failure_details(const SessionEnsureResult& result) {
    std::string summary = result.message;
    if (summary.size() > 512) summary.resize(512);
    std::string reason = result.startup_reason.empty() ? "unknown" : result.startup_reason;
    const std::string marker = "Server did not become ready: ";
    if (reason == "unknown" && summary.compare(0, marker.size(), marker) == 0)
        reason = summary.substr(marker.size());
    const bool npi_failure = !result.failure_phase.empty();
    OrderedJson details = {
        {"failure_kind", npi_failure ? "npi_startup_failed" :
            (result.status == "startup_failed" ? "engine_startup_failed" : "session_open_failed")},
        {"startup_reason", reason},
        {"native_error_summary", summary}
    };
    if (npi_failure) {
        details["failure_phase"] = result.failure_phase;
        details["diagnostic_log"] = result.diagnostic_log;
    }
    if (result.status == "npi_init_failed" &&
        xdebug_core::env_raw_string("SNPSLMD_LICENSE_FILE").empty() &&
        xdebug_core::env_raw_string("LM_LICENSE_FILE").empty()) {
        details["advisories"] = OrderedJson::array({{
            {"code", "LICENSE_ENV_NOT_EXPLICIT"},
            {"severity", "info"},
            {"message", "SNPSLMD_LICENSE_FILE and LM_LICENSE_FILE are both absent; another licensing mechanism may still be configured"}
        }});
    }
    return details;
}

std::string health_error_code(SessionHealthStatus status) {
    if (status == SessionHealthStatus::FsdbChanged ||
        status == SessionHealthStatus::DbdirChanged) return "RESOURCE_CHANGED";
    if (status == SessionHealthStatus::FsdbMissing ||
        status == SessionHealthStatus::DbdirMissing) return "RESOURCE_MISSING";
    return "SESSION_UNHEALTHY";
}

OrderedJson scalar_summary(const OrderedJson& data) {
    OrderedJson summary = OrderedJson::object();
    if (!data.is_object()) return summary;
    OrderedJson existing = data.value("summary", OrderedJson::object());
    if (existing.is_object() && !existing.empty()) return existing;
    return summary;
}

OrderedJson handle_batch(const OrderedJson& request);
OrderedJson handle_query(const OrderedJson& request);

OrderedJson handle_local_zero_resource_action(const OrderedJson& request,
                                              const std::string& action,
                                              bool& handled) {
    handled = false;
    if (action == "expr.normalize") {
        OrderedJson args = request.value("args", OrderedJson::object());
        std::string signal = args.value("signal", std::string());
        std::string expr = args.value("expr", std::string());
        if (!signal.empty() || expr.empty()) return make_response(request, action, false);
        handled = true;

        ExprSyntaxValidation syntax = validate_expr_syntax(expr);
        if (!syntax.ok) {
            return make_error(
                request, action, "EXPR_SYNTAX_INVALID", syntax.message, true,
                {{"invalid_arg", "args.expr"},
                 {"received", expr},
                 {"expected", "balanced expression with complete operands and operators"},
                 {"correct_example", {{"api_version", "xdebug.v1"},
                                      {"action", "expr.normalize"},
                                      {"args", {{"expr", "valid && ready"}}}}},
                 {"next_actions", OrderedJson::array({"Fix the expression syntax before using it for debug queries."})}});
        }

        OrderedJson summary = {{"expr", expr}, {"source", "string_fallback"}, {"confidence", "low"}};
        OrderedJson data;
        data["expr"] = OrderedJson::parse(parse_expr_ast(expr).dump());
        data["confidence_reason"] = "parsed from raw string without NPI handle";
        OrderedJson response = make_response(request, action);
        response["summary"] = summary;
        response["data"] = data;
        return response;
    }

    return make_response(request, action, false);
}

OrderedJson handle_session_action(const OrderedJson& request, const std::string& action) {
    SessionManager manager;
    if (action == "session.open") {
        std::vector<std::string> open_args = target_resource_args(request);
        if (open_args.empty()) return make_error(request, action, "INVALID_TARGET", "target.daidir or target.fsdb is required");
        std::string name = request_session_name(request);
        if (name.empty()) return make_error(request, action, "MISSING_FIELD", "args.name is required");
        SessionEnsureResult result = manager.ensure_session(open_args, name, request_transport_options(request));
        if (!result.ok) return make_error(request, action, ensure_error_code(result), result.message,
                                          true, session_open_failure_details(result));
        OrderedJson response = make_response(request, action);
        response["session"] = session_to_json(result.info);
        response["session"]["healthy"] = true;
        response["summary"] = {{"id", result.session_id}, {"session_id", result.session_id}, {"status", result.status}};
        response["data"] = {{"session", response["session"]}};
        return response;
    }
    if (action == "session.list") {
        OrderedJson sessions = OrderedJson::array();
        for (const auto& s : manager.list_sessions()) sessions.push_back(session_to_json(s));
        OrderedJson response = make_response(request, action);
        response["summary"] = {{"count", sessions.size()}};
        response["data"] = {{"sessions", sessions}};
        return response;
    }
    if (action == "session.doctor") {
        std::string sid = session_id_from_request(request);
        if (sid.empty()) return make_error(request, action, "MISSING_FIELD", "target.session_id is required");
        SessionHealth health = manager.diagnose_session(sid);
        OrderedJson response = make_response(request, action, health.healthy);
        response["session"] = session_to_json(health.info);
        response["summary"] = {{"id", sid}, {"session_id", sid}, {"healthy", health.healthy},
                               {"status", session_health_status_name(health.status)}, {"message", health.message}};
        response["data"] = {{"health", response["summary"]}};
        if (!health.healthy) {
            response["error"] = {{"code", health_error_code(health.status)}, {"message", health.message},
                                 {"recoverable", true}, {"candidates", OrderedJson::array()}, {"suggested_actions", OrderedJson::array()}};
        }
        return response;
    }
    if (action == "session.kill" || action == "session.close") {
        std::string sid = session_id_from_request(request);
        if (sid == "all") {
            bool ok = manager.kill_all_sessions();
            OrderedJson response = make_response(request, action, ok);
            response["summary"] = {{"target", "all"}, {"killed", ok}};
            return response;
        }
        if (sid.empty()) return make_error(request, action, "MISSING_FIELD", "session id string is required");
        bool ok = manager.kill_session(sid);
        OrderedJson response = make_response(request, action, ok);
        response["summary"] = {{"id", sid}, {"session_id", sid}, {"killed", ok}};
        if (!ok) {
            response["error"] = {{"code", "SESSION_CLEANUP_FAILED"},
                                 {"message", "failed to stop session engine or update registry"},
                                 {"recoverable", true}, {"candidates", OrderedJson::array()}, {"suggested_actions", OrderedJson::array()}};
        }
        return response;
    }
    return make_error(request, action, "UNKNOWN_ACTION", "unknown session action: " + action);
}

OrderedJson handle_engine_forward(const OrderedJson& request, const std::string& action) {
    std::string sid = session_id_from_request(request);
    if (sid.empty()) {
        return make_error(request, action, "SESSION_REQUIRED",
                          "target.session_id is required; open a session explicitly first");
    }
    SessionManager manager;
    SessionInfo session_info;
    bool have_session_info = manager.get_session(sid, session_info);
    Json transport_request = nlohmann::json::parse(request.dump());
    Json data;
    std::string status;
    std::string message;
    Json engine_error;
    if (!send_request_capture(sid, transport_request, data, status, message, engine_error)) {
        if (!engine_error.is_null()) {
            OrderedJson response = make_response(request, action, false);
            response["data"] = nullptr;
            response["error"] = OrderedJson::parse(engine_error.dump());
            return response;
        }
        return make_error(request, action, "SESSION_UNHEALTHY", message.empty() ? status : message);
    }
    OrderedJson ordered_data = OrderedJson::parse(data.dump());
    OrderedJson response = make_response(request, action);
    if (have_session_info) response["session"] = session_to_json(session_info);
    response["summary"] = scalar_summary(ordered_data);
    if (ordered_data.is_object() && ordered_data.contains("summary")) ordered_data.erase("summary");
    bool truncated = false;
    if (ordered_data.is_object() && ordered_data.contains("truncated") &&
        ordered_data["truncated"].is_boolean()) {
        truncated = ordered_data["truncated"].get<bool>();
        ordered_data.erase("truncated");
    }
    if (response["summary"].is_object() &&
        response["summary"].contains("truncated") &&
        response["summary"]["truncated"].is_boolean()) {
        truncated = truncated || response["summary"]["truncated"].get<bool>();
        response["summary"].erase("truncated");
    }
    if (truncated) response["meta"] = {{"truncated", true}};
    response["data"] = ordered_data;
    return response;
}

OrderedJson handle_batch(const OrderedJson& request) {
    OrderedJson args = request.value("args", OrderedJson::object());
    OrderedJson children = args.value("requests", OrderedJson::array());
    if (!children.is_array()) return make_error(request, "batch", "MISSING_FIELD", "args.requests[] is required");
    OrderedJson results = OrderedJson::array();
    bool all_ok = true;
    std::string mode = args.value("mode", std::string("continue_on_error"));
    for (auto child : children) {
        if (!child.contains("api_version")) child["api_version"] = INTERNAL_API_VERSION;
        OrderedJson result = handle_query(child);
        if (!result.value("ok", false)) all_ok = false;
        results.push_back(result);
        if (!result.value("ok", false) && mode == "stop_on_error") break;
    }
    OrderedJson response = make_response(request, "batch", all_ok);
    response["summary"] = {{"count", results.size()}, {"all_ok", all_ok}};
    response["data"] = {{"results", results}};
    if (!all_ok) {
        response["error"] = {{"code", "BATCH_PARTIAL_FAILURE"}, {"message", "one or more child requests failed"},
                             {"recoverable", true}, {"candidates", OrderedJson::array()}, {"suggested_actions", OrderedJson::array()}};
    }
    return response;
}

OrderedJson handle_query(const OrderedJson& request) {
    std::string action = request.value("action", std::string());
    std::string api_ver = request.value("api_version", std::string(INTERNAL_API_VERSION));
    if (api_ver != INTERNAL_API_VERSION && api_ver != "xdebug.v1") {
        return make_error(request, action, "UNSUPPORTED_API_VERSION",
                          "expected xdebug.internal.v1 or xdebug.v1", false);
    }
    if (action.empty()) return make_error(request, action, "MISSING_FIELD", "action is required");
    if (action == "batch") return handle_batch(request);
    if (action.compare(0, 8, "session.") == 0) return handle_session_action(request, action);
    bool handled = false;
    OrderedJson local = handle_local_zero_resource_action(request, action, handled);
    if (handled) return local;
    return handle_engine_forward(request, action);
}

int print_json_and_return(const OrderedJson& response) {
    std::printf("%s\n", response.dump(2).c_str());
    return response.value("ok", false) ? 0 : 1;
}

} // namespace

int engine_query_main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "Usage: %s ai <query> <request.json>|-|--json '<json>'\n", argv[0]);
        return 1;
    }
    std::string subcmd = argv[2];
    if (subcmd != "query") {
        OrderedJson req = {{"api_version", INTERNAL_API_VERSION}, {"action", ""}};
        return print_json_and_return(make_error(req, "", "UNKNOWN_ACTION", "unknown ai subcommand: " + subcmd));
    }

    std::string input;
    if (argc >= 5 && std::string(argv[3]) == "--json") {
        input = argv[4];
    } else if (argc >= 4 && std::string(argv[3]) == "-") {
        input = read_stream(std::cin);
    } else if (argc >= 4) {
        if (!read_file(argv[3], input)) {
            OrderedJson req = {{"api_version", INTERNAL_API_VERSION}, {"action", ""}};
            return print_json_and_return(make_error(req, "", "INVALID_REQUEST", "failed to read request file"));
        }
    } else {
        OrderedJson req = {{"api_version", INTERNAL_API_VERSION}, {"action", ""}};
        return print_json_and_return(make_error(req, "", "INVALID_REQUEST", "ai query requires a file, -, or --json"));
    }

    try {
        OrderedJson request = OrderedJson::parse(input);
        if (!request.is_object()) {
            return print_json_and_return(make_error(OrderedJson::object(), "", "INVALID_REQUEST", "request must be a JSON object"));
        }
        return print_json_and_return(handle_query(request));
    } catch (const std::exception& e) {
        OrderedJson req = {{"api_version", INTERNAL_API_VERSION}, {"action", ""}};
        return print_json_and_return(make_error(req, "", "INVALID_REQUEST", e.what()));
    }
}

} // namespace xdebug_design
