#include "engine_query.h"

#include "api/response.h"
#include "core/common/sha256.h"
#include "core/common/env_config.h"
#include "core/diagnostic_error.h"
#include "core/schema/internal_request_contract.h"
#include "core/schema/runtime_schema_validator.h"
#include "logging/action_log.h"

#include "session/client.h"
#include "session/session_manager.h"
#include "../design/protocol/protocol.h"
#include "../design/service/action_support.h"
#include "service/contract_bound_request.h"
#include "service/design_postprocess.h"

#include "json.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <climits>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <signal.h>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

namespace xdebug_design {

namespace {

using OrderedJson = nlohmann::ordered_json;
using Json = nlohmann::json;
using xdebug_engine::SessionEnsureResult;
using xdebug_engine::SessionCleanupPrecondition;
using xdebug_engine::SessionCleanupResult;
using xdebug_engine::SessionCleanupStatus;
using xdebug_engine::SessionHealth;
using xdebug_engine::SessionHealthStatus;
using xdebug_engine::SessionInfo;
using xdebug_engine::SessionManager;
using xdebug_engine::SessionTransportOptions;
using xdebug_engine::send_request_capture;
using xdebug_engine::session_health_status_name;

volatile sig_atomic_t g_query_termination_requested = 0;
std::chrono::steady_clock::time_point g_query_started_at;

void query_sigterm_handler(int) {
    g_query_termination_requested = 1;
}

bool install_query_sigterm_handler() {
    struct sigaction action = {};
    action.sa_handler = query_sigterm_handler;
    sigemptyset(&action.sa_mask);
    action.sa_flags = 0;
    return sigaction(SIGTERM, &action, nullptr) == 0;
}

bool direct_resource_test_pause_ms(
    int& pause_ms,
    std::string& error) {
    return xdebug_core::env_int(
        "XDEBUG_ENGINE_TEST_DIRECT_RESOURCE_PAUSE_MS",
        0,
        0,
        INT_MAX,
        pause_ms,
        error);
}

void interruptible_test_pause(int pause_ms) {
    const auto begin = std::chrono::steady_clock::now();
    while (!g_query_termination_requested) {
        const long long elapsed =
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - begin)
                .count();
        if (elapsed >= pause_ms) return;
        const long long remaining = pause_ms - elapsed;
        const useconds_t sleep_us = static_cast<useconds_t>(
            std::min<long long>(remaining, 100) * 1000);
        usleep(sleep_us);
    }
}

int remaining_request_timeout_ms(
    const OrderedJson& request) {
    const OrderedJson limits =
        request.value("limits", OrderedJson::object());
    if (!limits.is_object() ||
        !limits.contains("timeout_ms") ||
        !limits["timeout_ms"].is_number_integer()) {
        return -1;
    }
    const int timeout_ms =
        limits["timeout_ms"].get<int>();
    if (timeout_ms <= 0) return timeout_ms;
    const long long elapsed_ms =
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() -
            g_query_started_at)
            .count();
    if (elapsed_ms >= timeout_ms) return 0;
    return static_cast<int>(timeout_ms - elapsed_ms);
}

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
    std::string request_id;
    if (request.is_object() &&
        request.contains("observability") &&
        request["observability"].is_object() &&
        request["observability"].contains("request_id") &&
        request["observability"]["request_id"].is_string()) {
        request_id =
            request["observability"]["request_id"].get<std::string>();
    }
    response["request_id"] = request_id;
    response["ok"] = ok;
    response["action"] = action;
    response["tool"] = xdebug::tool_metadata();
    response["session"] = nullptr;
    response["summary"] = OrderedJson::object();
    response["data"] = OrderedJson::object();
    response["error"] = nullptr;
    return response;
}

OrderedJson internal_validation_error(
    const OrderedJson& request,
    const xdebug_core::RuntimeSchemaValidationResult& validation) {
    const std::string action =
        request.is_object() && request.contains("action") &&
                request["action"].is_string()
            ? request["action"].get<std::string>()
            : std::string();
    OrderedJson error = validation.error;
    if (!error.is_object()) error = OrderedJson::object();
    error["code"] =
        validation.code.empty() ? "INVALID_REQUEST" : validation.code;
    if (!error.contains("message") ||
        !error["message"].is_string()) {
        error["message"] = validation.message;
    }
    error["recoverable"] = false;
    error["error_layer"] = "schema";
    OrderedJson response = make_response(request, action, false);
    response["summary"] = {
        {"status", "error"},
        {"error_code", error["code"]}
    };
    response["data"] = nullptr;
    response["error"] =
        xdebug_core::normalize_diagnostic_error(error, "schema");
    return response;
}

OrderedJson make_error(const OrderedJson& request,
                       const std::string& action,
                       OrderedJson error) {
    error = xdebug_core::normalize_diagnostic_error(
        error,
        "handler");
    OrderedJson response = make_response(request, action, false);
    response["summary"] = {
        {"status", "error"},
        {"error_code",
         error.value("code", std::string("ACTION_FAILED"))}
    };
    response["data"] = nullptr;
    response["error"] = error;
    return response;
}

OrderedJson make_error(const OrderedJson& request,
                       const std::string& action,
                       const std::string& code,
                       const std::string& message,
                       bool recoverable = true,
                       const OrderedJson& details = OrderedJson::object()) {
    OrderedJson error = {
        {"code", code},
        {"message", message},
        {"recoverable", recoverable},
        {"error_layer", "handler"}
    };
    if (details.is_object()) {
        for (auto it = details.begin(); it != details.end(); ++it) {
            error[it.key()] = it.value();
        }
    }
    return make_error(request, action, error);
}

OrderedJson session_to_json(const SessionInfo& s) {
    OrderedJson item = {
        {"session_id", s.session_id},
        {"mode",
         !s.dbdir_path.empty() && !s.fsdb_file.empty()
             ? "combined"
             : (!s.dbdir_path.empty() ? "design" : "waveform")},
        {"transport", s.transport},
    };
    if (!s.dbdir_path.empty()) item["daidir"] = s.dbdir_path;
    if (!s.fsdb_file.empty()) item["fsdb"] = s.fsdb_file;
    if (s.server_pid > 0) item["server_pid"] = s.server_pid;
    if (!s.socket_path.empty()) item["socket_path"] = s.socket_path;
    if (!s.file_dir.empty()) item["file_dir"] = s.file_dir;
    if (!s.host.empty()) item["host"] = s.host;
    if (!s.bind_host.empty()) item["bind_host"] = s.bind_host;
    if (s.port > 0) item["port"] = s.port;
    if (!s.server_host.empty()) item["server_host"] = s.server_host;
    if (s.created_at > 0) {
        item["created_at"] =
            static_cast<long long>(s.created_at);
    }
    if (s.last_active > 0) {
        item["last_active"] =
            static_cast<long long>(s.last_active);
    }
    if (s.dbdir_mtime) item["daidir_mtime"] = s.dbdir_mtime;
    if (s.dbdir_size) item["daidir_size"] = s.dbdir_size;
    if (s.dbdir_dev) item["daidir_dev"] = s.dbdir_dev;
    if (s.dbdir_inode) item["daidir_inode"] = s.dbdir_inode;
    if (s.fsdb_mtime) item["fsdb_mtime"] = s.fsdb_mtime;
    if (s.fsdb_size) item["fsdb_size"] = s.fsdb_size;
    if (s.fsdb_dev) item["fsdb_dev"] = s.fsdb_dev;
    if (s.fsdb_inode) item["fsdb_inode"] = s.fsdb_inode;
    return item;
}

std::string session_mode(const SessionInfo& session) {
    if (!session.dbdir_path.empty() && !session.fsdb_file.empty()) {
        return "combined";
    }
    if (!session.dbdir_path.empty()) return "design";
    if (!session.fsdb_file.empty()) return "waveform";
    return "";
}

OrderedJson session_error_evidence(const SessionInfo& session) {
    OrderedJson evidence = {
        {"session_id", session.session_id}
    };
    const std::string mode = session_mode(session);
    if (!mode.empty()) evidence["session_mode"] = mode;
    if (!session.transport.empty()) {
        evidence["session_transport"] = session.transport;
    }
    return evidence;
}

std::string direct_resource_session_name() {
    const unsigned long long ticks =
        static_cast<unsigned long long>(
            std::chrono::steady_clock::now()
                .time_since_epoch()
                .count());
    return "direct_" +
           std::to_string(static_cast<long long>(getpid())) +
           "_" +
           std::to_string(ticks);
}

SessionTransportOptions request_transport_options(
    ContractBoundRequest& request) {
    SessionTransportOptions transport;
    auto args = request.args();
    transport.transport = args.value("transport", std::string());
    transport.bind_host =
        args.value("bind_host", std::string());
    transport.host = args.value("host", std::string());
    transport.port = args.value("port", 0);
    return transport;
}

std::vector<std::string> target_resource_args(const OrderedJson& request) {
    std::vector<std::string> args;
    const OrderedJson routing =
        request.value("routing", OrderedJson::object());
    std::string dbdir =
        routing.value("daidir", std::string());
    if (!dbdir.empty()) {
        args.push_back("-dbdir");
        args.push_back(dbdir);
    }
    std::string fsdb =
        routing.value("fsdb", std::string());
    if (!fsdb.empty()) {
        args.push_back("-fsdb");
        args.push_back(fsdb);
    }
    return args;
}

std::string request_session_name(ContractBoundRequest& request) {
    auto args = request.args();
    if (args.contains("name") && args["name"].is_string()) return args["name"].get<std::string>();
    return "";
}

std::string request_ownership_token(ContractBoundRequest& request) {
    auto args = request.args();
    if (args.contains("ownership_token") &&
        args["ownership_token"].is_string()) {
        return args["ownership_token"].get<std::string>();
    }
    return "";
}

bool valid_ownership_token(const std::string& token) {
    if (token.size() != 64) return false;
    for (const char c : token) {
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

std::string session_id_from_request(const OrderedJson& request) {
    const OrderedJson routing =
        request.value("routing", OrderedJson::object());
    if (routing.contains("session_id") &&
        routing["session_id"].is_string()) {
        return routing["session_id"].get<std::string>();
    }
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
    if (result.status == "registry_failed") return "REGISTRY_INVALID";
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
    if (!result.compensation_status.empty()) {
        details["cleanup_succeeded"] =
            result.cleanup_succeeded;
        details["compensation_status"] =
            result.compensation_status;
    }
    if (result.lifecycle_state == "cleanup_failed") {
        details["lifecycle_state"] =
            "cleanup_failed";
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
    if (status == SessionHealthStatus::RegistryInvalid)
        return "REGISTRY_INVALID";
    if (status == SessionHealthStatus::CleanupFailed)
        return "SESSION_CLEANUP_FAILED";
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

OrderedJson handle_query(const OrderedJson& request);

OrderedJson handle_local_zero_resource_action(
    const OrderedJson& request,
    ContractBoundRequest& bound_request,
                                              const std::string& action,
    bool& handled) {
    handled = false;
    if (action == "expr.normalize") {
        auto args = bound_request.args();
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

        OrderedJson summary = {
            {"expr", expr},
            {"source", "deterministic_syntax_parser"},
            {"confidence", "syntax_validated"}
        };
        OrderedJson data;
        data["expr"] = OrderedJson::parse(parse_expr_ast(expr).dump());
        data["confidence"] = "syntax_validated";
        data["confidence_reason"] =
            "expression syntax was validated and parsed without design-resource semantics";
        OrderedJson response = make_response(request, action);
        response["summary"] = summary;
        response["data"] = data;
        return response;
    }

    return make_response(request, action, false);
}

OrderedJson handle_session_action(
    const OrderedJson& request,
    ContractBoundRequest& bound_request,
    const std::string& action) {
    SessionManager manager;
    if (action == "session.open") {
        std::vector<std::string> open_args = target_resource_args(request);
        if (open_args.empty()) {
            return make_error(
                request,
                action,
                "INVALID_TARGET",
                "routing.daidir or routing.fsdb is required");
        }
        std::string name = request_session_name(bound_request);
        if (name.empty()) return make_error(request, action, "MISSING_FIELD", "args.name is required");
        const std::string ownership_token =
            request_ownership_token(bound_request);
        if (!ownership_token.empty() &&
            !valid_ownership_token(ownership_token)) {
            return make_error(
                request,
                action,
                "INVALID_ARGUMENT",
                "args.ownership_token must be 64 lowercase hexadecimal characters",
                false,
                {{"invalid_arg", "args.ownership_token"},
                 {"expected", "64 lowercase hexadecimal characters"}});
        }
        const std::string ownership_token_hash =
            ownership_token.empty()
                ? std::string()
                : xdebug_core::sha256_text(ownership_token);
        SessionEnsureResult result = manager.ensure_session(
            open_args,
            name,
            request_transport_options(bound_request),
            ownership_token_hash);
        if (!result.ok) return make_error(request, action, ensure_error_code(result), result.message,
                                          true, session_open_failure_details(result));
        OrderedJson response = make_response(request, action);
        response["session"] = session_to_json(result.info);
        response["session"]["healthy"] = true;
        response["summary"] = {
            {"session_id", result.session_id},
            {"status", result.status}
        };
        response["data"] = {{"session", response["session"]}};
        return response;
    }
    if (action == "session.doctor") {
        std::string sid = session_id_from_request(request);
        if (sid.empty()) {
            return make_error(
                request,
                action,
                "MISSING_FIELD",
                "routing.session_id is required");
        }
        SessionHealth health = manager.diagnose_session(sid);
        const std::string health_status =
            session_health_status_name(health.status);
        if (!health.healthy) {
            OrderedJson evidence =
                session_error_evidence(health.info);
            evidence["session_id"] = sid;
            evidence["health_status"] = health_status;
            evidence["error_layer"] = "session_manager";
            if (health.status ==
                SessionHealthStatus::CleanupFailed) {
                evidence["cleanup_succeeded"] = false;
                evidence["lifecycle_state"] =
                    "cleanup_failed";
            }
            if (health.status == SessionHealthStatus::FsdbChanged ||
                health.status == SessionHealthStatus::FsdbMissing) {
                evidence["resource_path"] = health.info.fsdb_file;
            } else if (
                health.status == SessionHealthStatus::DbdirChanged ||
                health.status == SessionHealthStatus::DbdirMissing) {
                evidence["resource_path"] = health.info.dbdir_path;
            }
            return make_error(
                request,
                action,
                health_error_code(health.status),
                health.message,
                health.status !=
                    SessionHealthStatus::RegistryInvalid,
                evidence);
        }
        OrderedJson response = make_response(request, action);
        response["session"] = session_to_json(health.info);
        response["summary"] = {{"session_id", sid}, {"healthy", true},
                               {"status", health_status}, {"message", health.message}};
        return response;
    }
    if (action == "session.kill") {
        std::string sid = session_id_from_request(request);
        const std::string ownership_token =
            request_ownership_token(bound_request);
        if (sid == "all") {
            if (!ownership_token.empty()) {
                return make_error(
                    request,
                    action,
                    "SESSION_OWNERSHIP_TOKEN_FORBIDDEN",
                    "args.ownership_token is only valid for one exact session_id",
                    false,
                    {{"invalid_arg", "args.ownership_token"},
                     {"expected", "omit ownership_token when target.session_id is all"}});
            }
            std::vector<SessionInfo> before;
            const xdebug_engine::SessionRegistryResult listed =
                manager.list_sessions_checked(before);
            if (!listed.ok()) {
                return make_error(
                    request,
                    action,
                    "REGISTRY_INVALID",
                    listed.message,
                    false,
                    {{"error_layer", "session_manager"}});
            }
            bool ok = manager.kill_all_sessions();
            if (!ok) {
                std::vector<SessionInfo> remaining;
                const xdebug_engine::SessionRegistryResult relisted =
                    manager.list_sessions_checked(remaining);
                if (!relisted.ok()) {
                    return make_error(
                        request,
                        action,
                        "REGISTRY_INVALID",
                        relisted.message,
                        false,
                        {{"error_layer", "session_manager"}});
                }
                OrderedJson failed_session_ids =
                    OrderedJson::array();
                for (const auto& session : remaining) {
                    failed_session_ids.push_back(
                        session.session_id);
                }
                const size_t removed_count =
                    before.size() >= remaining.size()
                        ? before.size() - remaining.size()
                        : 0;
                return make_error(
                    request,
                    action,
                    "SESSION_CLEANUP_PARTIAL_FAILURE",
                    "failed to stop one or more session engines",
                    true,
                    {{"error_layer", "session_manager"},
                     {"requested_count", before.size()},
                     {"removed_count", removed_count},
                     {"failed_session_ids",
                      failed_session_ids}});
            }
            OrderedJson response = make_response(request, action, ok);
            response["summary"] = {{"target", "all"}, {"killed", ok}};
            return response;
        }
        if (sid.empty()) return make_error(request, action, "MISSING_FIELD", "session id string is required");
        if (!ownership_token.empty() &&
            !valid_ownership_token(ownership_token)) {
            return make_error(
                request,
                action,
                "SESSION_OWNERSHIP_TOKEN_MISMATCH",
                "the supplied ownership token does not match this session.open record",
                false,
                {{"session_id", sid},
                 {"error_layer", "session_manager"}});
        }
        SessionCleanupPrecondition precondition;
        if (!ownership_token.empty()) {
            precondition.require_ownership_match = true;
            precondition.ownership_token_hash =
                xdebug_core::sha256_text(ownership_token);
        }
        SessionCleanupResult cleanup =
            manager.kill_session(sid, precondition);
        if (!cleanup.ok()) {
            OrderedJson evidence =
                session_error_evidence(cleanup.info);
            evidence["session_id"] = sid;
            evidence["error_layer"] = "session_manager";
            if (cleanup.status ==
                SessionCleanupStatus::NotFound) {
                return make_error(
                    request,
                    action,
                    "SESSION_NOT_FOUND",
                    "session not found: " + sid,
                    true,
                    evidence);
            }
            if (cleanup.status ==
                SessionCleanupStatus::OwnershipMismatch) {
                return make_error(
                    request,
                    action,
                    "SESSION_OWNERSHIP_TOKEN_MISMATCH",
                    cleanup.message,
                    false,
                    evidence);
            }
            if (cleanup.status ==
                SessionCleanupStatus::RegistryInvalid) {
                return make_error(
                    request,
                    action,
                    "REGISTRY_INVALID",
                    cleanup.message,
                    false,
                    evidence);
            }
            evidence["cleanup_succeeded"] = false;
            evidence["lifecycle_state"] =
                "cleanup_failed";
            return make_error(
                request,
                action,
                "SESSION_CLEANUP_FAILED",
                cleanup.message.empty()
                    ? "failed to stop session engine or update registry"
                    : cleanup.message,
                true,
                evidence);
        }
        OrderedJson response = make_response(request, action);
        response["summary"] = {{"session_id", sid}, {"killed", true}};
        return response;
    }
    return make_error(request, action, "UNKNOWN_ACTION", "unknown session action: " + action);
}

OrderedJson handle_engine_forward(const OrderedJson& request, const std::string& action) {
    std::string sid = session_id_from_request(request);
    SessionManager manager;
    SessionInfo session_info;
    bool ephemeral = false;
    bool have_session_info = false;
    if (sid.empty()) {
        int test_pause_ms = 0;
        std::string test_pause_error;
        if (!direct_resource_test_pause_ms(
                test_pause_ms,
                test_pause_error)) {
            return make_error(
                request,
                action,
                "INVALID_CONFIG",
                test_pause_error,
                false);
        }
        const std::vector<std::string> resources =
            target_resource_args(request);
        if (resources.empty()) {
            return make_error(
                request,
                action,
                "RESOURCE_REQUIRED",
                "routing.session_id or routing.daidir/fsdb is required");
        }
        const std::string direct_name =
            direct_resource_session_name();
        xdebug_core::log_lifecycle_event(
            "engine",
            direct_name,
            "direct_resource.open.begin",
            true,
            {{"action", action},
             {"routing",
              request.value("routing", OrderedJson::object())}});
        SessionTransportOptions direct_transport;
        direct_transport.detached = false;
        SessionEnsureResult opened =
            manager.ensure_session(resources, direct_name, direct_transport);
        if (!opened.ok) {
            OrderedJson evidence =
                session_open_failure_details(opened);
            evidence["error_layer"] = "session_manager";
            xdebug_core::log_lifecycle_event(
                "engine",
                direct_name,
                "direct_resource.open.end",
                false,
                {{"action", action},
                 {"status", opened.status},
                 {"message", opened.message}});
            return make_error(
                request,
                action,
                ensure_error_code(opened),
                opened.message,
                true,
                evidence);
        }
        sid = opened.session_id;
        session_info = opened.info;
        ephemeral = true;
        xdebug_core::log_lifecycle_event(
            "engine",
            sid,
            "direct_resource.open.end",
            true,
            {{"action", action},
             {"mode", session_mode(session_info)},
             {"transport", session_info.transport}});
        if (test_pause_ms > 0) {
            xdebug_core::log_lifecycle_event(
                "engine",
                sid,
                "direct_resource.test_pause.begin",
                true,
                {{"action", action},
                 {"pause_ms", test_pause_ms}});
            interruptible_test_pause(test_pause_ms);
            xdebug_core::log_lifecycle_event(
                "engine",
                sid,
                "direct_resource.test_pause.end",
                !g_query_termination_requested,
                {{"action", action},
                 {"termination_requested",
                  g_query_termination_requested != 0}});
        }
    } else {
        have_session_info =
            manager.get_session(sid, session_info);
    }

    Json transport_request = nlohmann::json::parse(request.dump());
    transport_request["routing"]["session_id"] = sid;
    Json data;
    std::string status;
    std::string message;
    Json engine_error;
    OrderedJson pending_error;
    bool sent = false;
    const int remaining_timeout_ms =
        remaining_request_timeout_ms(request);
    if (g_query_termination_requested ||
        remaining_timeout_ms == 0) {
        OrderedJson evidence = {
            {"error_layer", "transport"}
        };
        const OrderedJson limits =
            request.value("limits", OrderedJson::object());
        if (limits.contains("timeout_ms")) {
            evidence["timeout_ms"] =
                limits["timeout_ms"];
        }
        pending_error = make_error(
            request,
            action,
            "ENGINE_TIMEOUT",
            "internal engine request exceeded limits.timeout_ms",
            true,
            evidence);
    } else {
        if (remaining_timeout_ms > 0) {
            transport_request["limits"]["timeout_ms"] =
                remaining_timeout_ms;
        }
        sent = send_request_capture(
            sid,
            transport_request,
            data,
            status,
            message,
            engine_error);
    }
    if (!sent && pending_error.is_null()) {
        if (!engine_error.is_null()) {
            pending_error = make_error(
                request,
                action,
                OrderedJson::parse(engine_error.dump()));
        } else {
            OrderedJson evidence =
                session_error_evidence(session_info);
            evidence["session_id"] = sid;
            evidence["health_status"] =
                status.empty() ? "transport_failed" : status;
            evidence["error_layer"] = "transport";
            pending_error = make_error(
                request,
                action,
                "SESSION_UNHEALTHY",
                message.empty() ? status : message,
                true,
                evidence);
        }
    }

    if (ephemeral) {
        xdebug_core::log_lifecycle_event(
            "engine",
            sid,
            "direct_resource.close.begin",
            true,
            {{"action", action}});
        const SessionCleanupResult cleanup =
            manager.kill_session(sid);
        const bool cleanup_ok = cleanup.ok();
        xdebug_core::log_lifecycle_event(
            "engine",
            sid,
            "direct_resource.close.end",
            cleanup_ok,
            {{"action", action}});
        if (!cleanup_ok) {
            OrderedJson evidence =
                session_error_evidence(session_info);
            evidence["cleanup_succeeded"] = false;
            evidence["error_layer"] = "session_manager";
            if (pending_error.is_object() &&
                pending_error.contains("error") &&
                pending_error["error"].is_object()) {
                const std::string cause =
                    pending_error["error"].value(
                        "code",
                        std::string());
                if (!cause.empty()) {
                    evidence["cause_code"] = cause;
                }
            }
            return make_error(
                request,
                action,
                "SESSION_CLEANUP_FAILED",
                "direct-resource engine completed but could not be closed",
                true,
                evidence);
        }
    }
    if (!pending_error.is_null()) {
        return pending_error;
    }

    OrderedJson ordered_data = OrderedJson::parse(data.dump());
    OrderedJson response = make_response(request, action);
    if (have_session_info) response["session"] = session_to_json(session_info);
    if (ordered_data.contains("__xout") &&
        ordered_data["__xout"].is_string()) {
        response["__xout"] = ordered_data["__xout"];
        ordered_data.erase("__xout");
    }
    response["summary"] = scalar_summary(ordered_data);
    if (ordered_data.is_object() && ordered_data.contains("summary")) ordered_data.erase("summary");
    response["data"] = ordered_data;
    return response;
}

OrderedJson handle_query(const OrderedJson& request) {
    xdebug_core::RuntimeSchemaValidator validator;
    xdebug_core::RuntimeSchemaValidationResult validation =
        validator.validate_internal_request(request);
    if (!validation.ok) {
        return internal_validation_error(request, validation);
    }
    const std::string action =
        request["action"].get<std::string>();
    if (action == "session.open" ||
        action == "session.kill" ||
        action == "session.doctor") {
        ContractBoundRequest bound_request(request, action);
        OrderedJson response =
            handle_session_action(request, bound_request, action);
        const std::vector<std::string> unconsumed =
            bound_request.unconsumed_paths();
        if (response.value("ok", false) && !unconsumed.empty()) {
            return make_error(
                request,
                action,
                xdebug_core::request_consumption_violation(unconsumed));
        }
        return response;
    }
    if (action.compare(0, 7, "server.") == 0) {
        return make_error(
            request,
            action,
            "UNKNOWN_ACTION",
            "internal control action is only valid on a live engine server",
            false);
    }
    bool handled = false;
    ContractBoundRequest bound_request(request, action);
    OrderedJson local = handle_local_zero_resource_action(
        request, bound_request, action, handled);
    if (handled) {
        const std::vector<std::string> unconsumed =
            bound_request.unconsumed_paths();
        if (local.value("ok", false) && !unconsumed.empty()) {
            return make_error(
                request,
                action,
                xdebug_core::request_consumption_violation(unconsumed));
        }
        return local;
    }
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
    g_query_termination_requested = 0;
    g_query_started_at = std::chrono::steady_clock::now();
    if (!install_query_sigterm_handler()) {
        OrderedJson req = {
            {"api_version", INTERNAL_API_VERSION},
            {"action", ""}
        };
        return print_json_and_return(
            make_error(
                req,
                "",
                "INTERNAL_SIGNAL_SETUP_FAILED",
                "failed to install engine query SIGTERM handler",
                false));
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
