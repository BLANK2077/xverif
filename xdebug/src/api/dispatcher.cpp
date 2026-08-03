#include "api/dispatcher.h"
#include "api/action_catalog.h"
#include "api/action_registry_init.h"
#include "core/diagnostic_error.h"
#include "api/request_envelope.h"
#include "api/request_validator.h"
#include "api/resource_resolver.h"
#include "api/response.h"
#include "common/path_utils.h"
#include "core/session/session_timeout.h"
#include "core/session/session_types.h"
#include "core/common/sha256.h"
#include "logging/action_log.h"

#include <cerrno>
#include <chrono>
#include <ctime>
#include <limits.h>
#include <stdexcept>
#include <string>
#include <cstring>
#include <fstream>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/un.h>

namespace xdebug {

using xdebug_core::DiagnosticErrorBuilder;

namespace {

bool has_string(const Json& object, const char* key) {
    return object.contains(key) && object[key].is_string() &&
           !object[key].get<std::string>().empty();
}

void append_recommended_actions(Json& response, const ActionSpec& spec) {
    if (!response.value("ok", false) || spec.recommended_actions.empty()) return;
    if (!response.contains("data") || !response["data"].is_object()) {
        throw std::runtime_error(
            "successful load response requires an object data payload");
    }
    Json recommendations = Json::array();
    for (const ActionRecommendation& recommendation : spec.recommended_actions) {
        recommendations.push_back({
            {"action", recommendation.action},
            {"purpose", recommendation.purpose},
        });
    }
    response["data"]["recommended_actions"] = std::move(recommendations);
}

bool fingerprint_recorded(long mtime, long long size,
                          unsigned long long dev, unsigned long long inode) {
    return mtime != 0 || size != 0 || dev != 0 || inode != 0;
}

std::string dirname_of(const std::string& path) {
    const size_t slash = path.find_last_of('/');
    return slash == std::string::npos ? "." : (slash == 0 ? "/" : path.substr(0, slash));
}

bool canonical_path(const std::string& path, std::string& out) {
    char resolved[PATH_MAX] = {};
    if (!realpath(path.c_str(), resolved)) return false;
    out = resolved;
    return true;
}

Json manifest_mismatch(const Json& request, const std::string& message, const Json& details) {
    Json response = make_error(request, "session.open", "RESOURCE_PROVENANCE_MISMATCH", message);
    response["summary"] = {{"status", "manifest_mismatch"}};
    response["data"] = {{"manifest", details}};
    return response;
}

bool validate_manifest_resource(const Json& request, const std::string& manifest_path,
                                const std::string& key, const std::string& target_path,
                                Json& details, Json& error_response) {
    if (!details.contains("resources") || !details["resources"].is_object() ||
        !details["resources"].contains(key) || !details["resources"][key].is_object()) {
        error_response = manifest_mismatch(request, "run manifest does not declare resource: " + key, details);
        return false;
    }
    const Json& declared = details["resources"][key];
    const std::string relative = declared.value("path", std::string());
    const long long size = declared.value("size_bytes", -1LL);
    const std::string expected_sha = declared.value("sha256", std::string());
    if (relative.empty() || size < 0 || expected_sha.size() != 64) {
        error_response = manifest_mismatch(request, "run manifest has incomplete resource declaration: " + key, details);
        return false;
    }
    std::string expected_path, actual_path;
    if (!canonical_path(dirname_of(manifest_path) + "/" + relative, expected_path) ||
        !canonical_path(target_path, actual_path) || expected_path != actual_path) {
        details["resource"] = key;
        details["expected_path"] = relative;
        error_response = manifest_mismatch(request, "run manifest resource path does not match target: " + key, details);
        return false;
    }
    struct stat st;
    if (stat(actual_path.c_str(), &st) != 0 || static_cast<long long>(st.st_size) != size) {
        details["resource"] = key;
        details["expected_size_bytes"] = size;
        details["actual_size_bytes"] = stat(actual_path.c_str(), &st) == 0 ? Json(static_cast<long long>(st.st_size)) : Json(nullptr);
        error_response = manifest_mismatch(request, "run manifest resource size does not match target: " + key, details);
        return false;
    }
    std::string actual_sha, sha_error;
    const bool is_directory = S_ISDIR(st.st_mode);
    const bool digest_ok = is_directory
        ? xdebug_core::sha256_directory_tree(actual_path, actual_sha, sha_error)
        : xdebug_core::sha256_file(actual_path, actual_sha, sha_error);
    if (!digest_ok || actual_sha != expected_sha) {
        details["resource"] = key;
        details["expected_sha256"] = expected_sha;
        details["actual_sha256"] = actual_sha.empty() ? Json(nullptr) : Json(actual_sha);
        error_response = manifest_mismatch(request, "run manifest resource SHA-256 does not match target: " + key, details);
        return false;
    }
    return true;
}

bool validate_run_manifest(const Json& request, const Json& target, Json& details, Json& error_response) {
    if (!has_string(target, "run_manifest")) return true;
    std::string manifest_path;
    if (!canonical_path(target["run_manifest"].get<std::string>(), manifest_path)) {
        error_response = manifest_mismatch(request, "run manifest is missing or cannot be resolved", Json::object());
        return false;
    }
    std::ifstream input(manifest_path.c_str());
    if (!input.good()) { error_response = manifest_mismatch(request, "run manifest cannot be opened", Json::object()); return false; }
    try { input >> details; } catch (...) { error_response = manifest_mismatch(request, "run manifest is not valid JSON", Json::object()); return false; }
    if (details.value("schema_version", std::string()) != "xdebug.run-manifest.v1" ||
        details.value("state", std::string()) != "published") {
        error_response = manifest_mismatch(request, "run manifest must be xdebug.run-manifest.v1 in published state", details);
        return false;
    }
    if (has_string(target, "fsdb") && !validate_manifest_resource(request, manifest_path, "fsdb", target["fsdb"].get<std::string>(), details, error_response)) return false;
    if (has_string(target, "daidir") && !validate_manifest_resource(request, manifest_path, "daidir", target["daidir"].get<std::string>(), details, error_response)) return false;
    details["manifest_path"] = manifest_path;
    return true;
}

bool resource_changed(const std::string& path,
                      long expected_mtime,
                      long long expected_size,
                      unsigned long long expected_dev,
                      unsigned long long expected_inode,
                      std::string& message) {
    if (path.empty() ||
        !fingerprint_recorded(expected_mtime, expected_size, expected_dev, expected_inode)) {
        return false;
    }
    struct stat st;
    if (stat(path.c_str(), &st) != 0) {
        message = "resource is missing or cannot be stat'ed: " + path;
        return true;
    }
    bool content_changed = !xdebug_core::resource_content_matches(
        expected_mtime, expected_size,
        static_cast<long>(st.st_mtime), static_cast<long long>(st.st_size));
    bool identity_changed = xdebug_core::resource_identity_differs(
        expected_dev, expected_inode,
        static_cast<unsigned long long>(st.st_dev),
        static_cast<unsigned long long>(st.st_ino));
    if (!content_changed && !identity_changed) return false;
    message = "resource changed since session was opened: " + path;
    return true;
}

bool session_resource_changed(const SessionRecord& record, std::string& message) {
    return resource_changed(record.daidir, record.dbdir_mtime, record.dbdir_size,
                            record.dbdir_dev, record.dbdir_inode, message) ||
           resource_changed(record.fsdb, record.fsdb_mtime, record.fsdb_size,
                            record.fsdb_dev, record.fsdb_inode, message);
}

bool session_idle_expired(const SessionRecord& record,
                          int idle_timeout_sec,
                          time_t now,
                          long long& idle_sec) {
    long long last_active = record.last_active > 0 ? record.last_active : record.created_at;
    if (last_active <= 0) return false;
    idle_sec = static_cast<long long>(now) - last_active;
    return idle_sec >= idle_timeout_sec;
}

std::string requested_name(const Json& request) {
    Json args = request.value("args", Json::object());
    Json target = request.value("target", Json::object());
    if (has_string(args, "name")) return args["name"].get<std::string>();
    if (has_string(target, "name")) return target["name"].get<std::string>();
    return "";
}

Json engine_error(const Json& request, const std::string& action, const std::string& message) {
    return make_error(request, action,
                      DiagnosticErrorBuilder::transport("INTERNAL_ENGINE_FAILED", message).to_json());
}

int request_timeout_ms(const Json& request) {
    Json limits = request.value("limits", Json::object());
    if (!limits.is_object() || !limits.contains("timeout_ms") ||
        !limits["timeout_ms"].is_number_integer()) {
        return 30000;
    }
    int timeout_ms = limits["timeout_ms"].get<int>();
    if (timeout_ms < 0) return 0;
    return timeout_ms;
}

bool is_socket_timeout_errno(int err) {
    return err == EAGAIN || err == EWOULDBLOCK || err == EINPROGRESS;
}

long long elapsed_ms_since(std::chrono::steady_clock::time_point begin) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - begin).count();
}

Json transport_context(const Json& request,
                       const std::string& phase,
                       const std::string& session_id,
                       const std::string& socket_path,
                       int timeout_ms) {
    Json ctx = {
        {"phase", phase},
        {"session_id", session_id},
        {"action", request.value("action", std::string())},
        {"request", xdebug_core::request_summary_for_log(request)}
    };
    if (!socket_path.empty()) ctx["socket_path"] = socket_path;
    if (timeout_ms >= 0) ctx["timeout_ms"] = timeout_ms;
    Json summary = xdebug_core::request_summary_for_log(request);
    if (summary.contains("trace_id")) ctx["trace_id"] = summary["trace_id"];
    if (summary.contains("request_id")) ctx["request_id"] = summary["request_id"];
    if (summary.contains("span_id")) ctx["span_id"] = summary["span_id"];
    if (summary.contains("parent_span_id")) ctx["parent_span_id"] = summary["parent_span_id"];
    return ctx;
}

void log_engine_transport(const std::string& session_id,
                          const std::string& phase,
                          bool ok,
                          Json context) {
    context["transport_phase"] = phase;
    xdebug_core::log_transport_event("engine", session_id, phase, ok, context);
}

void set_socket_timeout(int fd, int timeout_ms) {
    if (timeout_ms <= 0) return;
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
}

Json direct_socket_timeout_error(const Json& request,
                                 const std::string& action,
                                 const std::string& socket_path,
                                 int timeout_ms) {
    Json response = make_error(
        request,
        action,
        DiagnosticErrorBuilder::transport("SESSION_TRANSPORT_FAILED",
                                "direct session socket timed out after " +
                                    std::to_string(timeout_ms) + "ms: " + socket_path)
            .to_json());
    response["summary"] = {
        {"transport", "uds"},
        {"socket_path", socket_path},
        {"timeout_ms", timeout_ms}
    };
    return response;
}

Json direct_socket_failed_error(const Json& request,
                                const std::string& action,
                                const SessionRecord& record) {
    Json response = make_error(
        request,
        action,
        DiagnosticErrorBuilder::transport("SESSION_TRANSPORT_FAILED",
                                "direct session transport failed for session: " + record.id)
            .to_json());
    response["summary"] = {
        {"session_id", record.id},
        {"mode", record.mode},
        {"transport", record.transport.empty() ? "uds" : record.transport}
    };
    if (!record.socket_path.empty()) response["summary"]["socket_path"] = record.socket_path;
    if (!record.file_dir.empty()) response["summary"]["file_dir"] = record.file_dir;
    return response;
}

bool backend_cleanup_ok(const Json& response) {
    if (response.value("ok", false)) return true;
    Json error = response.value("error", Json::object());
    std::string code = error.value("code", std::string());
    return code == "SESSION_NOT_FOUND";
}

std::string stable_resource_path(const std::string& path) {
    if (path.empty() || path[0] == '/') return path;
    char cwd[PATH_MAX] = {};
    return getcwd(cwd, sizeof(cwd)) ? std::string(cwd) + "/" + path : path;
}

void stabilize_resource_paths(Json& target) {
    if (has_string(target, "daidir")) {
        target["daidir"] = stable_resource_path(target["daidir"].get<std::string>());
    }
    if (has_string(target, "fsdb")) {
        target["fsdb"] = stable_resource_path(target["fsdb"].get<std::string>());
    }
    if (has_string(target, "run_manifest")) {
        target["run_manifest"] = stable_resource_path(target["run_manifest"].get<std::string>());
    }
}

std::string request_log_session_id(const Json& request, const Json& response = Json()) {
    Json target = request.value("target", Json::object());
    Json args = request.value("args", Json::object());
    if (has_string(target, "session_id")) return target["session_id"].get<std::string>();
    if (has_string(args, "session_id")) return args["session_id"].get<std::string>();
    if (has_string(args, "id") && args["id"].get<std::string>() != "all") return args["id"].get<std::string>();
    if (has_string(args, "name")) return args["name"].get<std::string>();
    if (has_string(target, "name")) return target["name"].get<std::string>();
    if (response.is_object()) {
        Json session = response.value("session", Json::object());
        if (has_string(session, "id")) return session["id"].get<std::string>();
        if (has_string(session, "session_id")) return session["session_id"].get<std::string>();
        Json summary = response.value("summary", Json::object());
        if (has_string(summary, "session_id")) return summary["session_id"].get<std::string>();
        if (has_string(summary, "id")) return summary["id"].get<std::string>();
    }
    return "adhoc";
}

std::string target_mode_for_log(const Json& request, const Json& response = Json()) {
    Json target = request.value("target", Json::object());
    if (has_string(target, "mode")) return target["mode"].get<std::string>();
    Json summary = response.value("summary", Json::object());
    if (has_string(summary, "mode")) return summary["mode"].get<std::string>();
    bool daidir = has_string(target, "daidir");
    bool fsdb = has_string(target, "fsdb");
    if (daidir && fsdb) return "combined";
    if (daidir) return "design";
    if (fsdb) return "waveform";
    return "";
}

bool same_resource(const SessionRecord& a, const SessionRecord& b) {
    if (a.mode != b.mode) return false;
    if (a.mode == "design") return a.daidir == b.daidir;
    if (a.mode == "waveform") return a.fsdb == b.fsdb;
    if (a.mode == "combined") return a.daidir == b.daidir && a.fsdb == b.fsdb;
    return false;
}

std::string resource_match_kind(const SessionRecord& record) {
    if (record.mode == "design") return "same_daidir";
    if (record.mode == "waveform") return "same_fsdb";
    if (record.mode == "combined") return "same_combined_resource";
    return "same_resource";
}

Json duplicate_resource_advisories(const std::vector<SessionRecord>& records,
                                   const SessionRecord& opened) {
    Json advisories = Json::array();
    for (const auto& existing : records) {
        if (existing.id == opened.id || !same_resource(existing, opened)) continue;
        advisories.push_back({
            {"code", "RESOURCE_SESSION_ALREADY_ALIVE"},
            {"severity", "info"},
            {"match_kind", resource_match_kind(opened)},
            {"existing_session_id", existing.id},
            {"existing_mode", existing.mode},
            {"message", "same resource already has an alive session; consider closing one to save resources"}
        });
    }
    return advisories;
}

} // namespace

Dispatcher::Dispatcher(const std::string& executable_dir)
    : adapter_(executable_dir) {}

std::string Dispatcher::mode_for_target(const Json& target) const {
    const bool daidir = has_string(target, "daidir");
    const bool fsdb = has_string(target, "fsdb");
    if (daidir && fsdb) return "combined";
    if (daidir) return "design";
    if (fsdb) return "waveform";
    return "";
}

Json Dispatcher::resolve_target(const Json& request) const {
    Json target = request.value("target", Json::object());
    if (has_string(target, "session_id")) {
        SessionRecord record;
        if (sessions_.get(target["session_id"].get<std::string>(), record)) {
            if (!record.daidir.empty()) target["daidir"] = record.daidir;
            if (!record.fsdb.empty()) target["fsdb"] = record.fsdb;
            target["mode"] = record.mode;
        }
    }
    stabilize_resource_paths(target);
    return target;
}

Json Dispatcher::forward_action(const Json& request) {
    Json forwarded = request;
    Json target = forwarded.value("target", Json::object());
    Json args = forwarded.value("args", Json::object());
    if (!has_string(target, "session_id") && has_string(args, "name") && !has_string(target, "name")) {
        target["name"] = args["name"];
    }
    forwarded["target"] = target;
    Json response;
    std::string error;
    if (!adapter_.invoke(forwarded, response, error)) {
        return engine_error(request, request.value("action", std::string()), error);
    }
    return response;
}

Json Dispatcher::resource_error(const Json& request, const ActionSpec& spec, const Json& target) const {
    RequestEnvelope envelope = RequestEnvelope::from_json(request);
    envelope.target = target;
    ResourceResolver resolver;
    ResourceResolution resolution = resolver.resolve(envelope, spec);
    if (resolution.ok) return Json();
    return make_error(request, spec.name, resolution.code, resolution.message);
}

Json Dispatcher::kill_session_record(const Json& request,
                                     const SessionRecord& record,
                                     const std::string& reason) {
    Json kill_req = request;
    kill_req["action"] = "session.kill";
    kill_req["target"] = {{"session_id", record.id}};
    kill_req["args"] = Json::object();
    Json kill_result = forward_action(kill_req);
    return {{"session_id", record.id},
            {"mode", record.mode},
            {"reason", reason},
            {"kill_ok", backend_cleanup_ok(kill_result)},
            {"result", kill_result}};
}

bool Dispatcher::cleanup_expired_sessions(const Json& request, Json& removed, Json& error_response) {
    int idle_timeout_sec = 0;
    std::string timeout_error;
    if (!xdebug_core::session_idle_timeout_sec(idle_timeout_sec, timeout_error)) {
        error_response = make_error(request,
                                    request.value("action", std::string()),
                                    "INVALID_CONFIG",
                                    timeout_error,
                                    false);
        return false;
    }

    removed = Json::array();
    const time_t now = time(nullptr);
    for (const auto& record : sessions_.list()) {
        long long idle_sec = 0;
        if (!session_idle_expired(record, idle_timeout_sec, now, idle_sec)) continue;
        Json removed_item = kill_session_record(request, record, "idle_timeout");
        removed_item["idle_sec"] = idle_sec;
        removed_item["idle_timeout_sec"] = idle_timeout_sec;
        removed.push_back(removed_item);
    }
    return true;
}

Json Dispatcher::handle_engine_forward(const Json& request, const ActionSpec& spec) {
    Json target = resolve_target(request);
    Json err_resp = resource_error(request, spec, target);
    if (!err_resp.is_null()) return err_resp;
    Json routed = request;
    routed["target"] = target;

    // Direct socket path: if session has a known socket, talk to the
    // engine server directly instead of spawning a per-request process.
    std::string sid = target.value("session_id", "");
    if (!sid.empty()) {
        SessionRecord record;
        if (!sessions_.get(sid, record)) {
            return make_error(request, spec.name, "SESSION_NOT_FOUND", "session not found: " + sid);
        }
        int idle_timeout_sec = 0;
        std::string timeout_error;
        if (!xdebug_core::session_idle_timeout_sec(idle_timeout_sec, timeout_error)) {
            return make_error(request, spec.name, "INVALID_CONFIG", timeout_error, false);
        }
        long long idle_sec = 0;
        if (session_idle_expired(record, idle_timeout_sec, time(nullptr), idle_sec)) {
            Json removed = kill_session_record(request, record, "idle_timeout");
            Json response = make_error(request, spec.name, "SESSION_EXPIRED",
                                       "session idle timeout exceeded: " + sid, true);
            response["summary"] = {{"session_id", sid},
                                   {"mode", record.mode},
                                   {"idle_sec", idle_sec},
                                   {"idle_timeout_sec", idle_timeout_sec},
                                   {"removed", removed.value("kill_ok", false)}};
            response["data"] = {{"removed", removed}};
            return response;
        }
        if (!record.transport.empty() && record.transport != "uds") {
            Json ctx = transport_context(routed, "fallback.invoke.begin", sid, "", request_timeout_ms(routed));
            ctx["transport"] = record.transport;
            log_engine_transport(sid, "fallback.invoke.begin", true, ctx);
            auto begin = std::chrono::steady_clock::now();
            Json response = forward_action(routed);
            Json end_ctx = transport_context(routed, "fallback.invoke.end", sid, "", request_timeout_ms(routed));
            end_ctx["transport"] = record.transport;
            end_ctx["elapsed_ms"] = elapsed_ms_since(begin);
            end_ctx["response"] = xdebug_core::response_summary_for_log(response);
            log_engine_transport(sid, "fallback.invoke.end", response.value("ok", false), end_ctx);
            return response;
        }
        if (record.socket_path.empty()) return direct_socket_failed_error(request, spec.name, record);
        Json response;
        if (send_to_socket(sid, record.socket_path, spec.category, routed, response)) return response;
        return direct_socket_failed_error(request, spec.name, record);
    }

    Json ctx = transport_context(routed, "fallback.invoke.begin", request_log_session_id(routed), "", request_timeout_ms(routed));
    log_engine_transport(request_log_session_id(routed), "fallback.invoke.begin", true, ctx);
    auto begin = std::chrono::steady_clock::now();
    Json response = forward_action(routed);
    Json end_ctx = transport_context(routed, "fallback.invoke.end", request_log_session_id(routed, response), "", request_timeout_ms(routed));
    end_ctx["elapsed_ms"] = elapsed_ms_since(begin);
    end_ctx["response"] = xdebug_core::response_summary_for_log(response);
    log_engine_transport(request_log_session_id(routed, response), "fallback.invoke.end", response.value("ok", false), end_ctx);
    return response;
}

Json Dispatcher::handle_batch(const Json& request) {
    Json args = request.value("args", Json::object());
    Json requests = args.value("requests", Json());
    if (!requests.is_array()) {
        return make_error(request, "batch", "MISSING_FIELD", "args.requests[] is required");
    }
    Json response = make_response(request, "batch");
    Json results = Json::array();
    Json failed_indexes = Json::array();
    Json failed_codes = Json::array();
    Json failed_layers = Json::array();
    bool all_ok = true;
    std::string mode = args.value("mode", std::string("continue_on_error"));
    for (auto child : requests) {
        if (!child.contains("api_version")) child["api_version"] = kApiVersion;
        Json result = dispatch(child);
        results.push_back(result);
        if (!result.value("ok", false)) {
            all_ok = false;
            failed_indexes.push_back(results.size() - 1);
            Json error = result.value("error", Json::object());
            failed_codes.push_back(error.value("code", std::string("ACTION_FAILED")));
            failed_layers.push_back(error.value("error_layer", std::string("handler")));
            if (mode == "stop_on_error") break;
        }
    }
    response["ok"] = all_ok;
    response["summary"] = {{"count", results.size()}, {"all_ok", all_ok},
                           {"failed_count", failed_indexes.size()},
                           {"failed_indexes", failed_indexes},
                           {"failed_codes", failed_codes},
                           {"failed_layers", failed_layers}};
    response["data"] = {{"results", results}};
    if (!all_ok) response["error"] = {{"code", "BATCH_PARTIAL_FAILURE"},
                                      {"message", "one or more child requests failed"},
                                      {"recoverable", true},
                                      {"error_layer", "handler"}};
    return response;
}

Json Dispatcher::handle_session(const Json& request, const std::string& action) {
    Json target = resolve_target(request);
    Json args = request.value("args", Json::object());
    if (action == "session.list") {
        Json expired_removed;
        Json cleanup_error;
        if (!cleanup_expired_sessions(request, expired_removed, cleanup_error)) return cleanup_error;
        Json response = make_response(request, action);
        Json records = Json::array();
        for (const auto& record : sessions_.list()) records.push_back(session_record_json(record));
        response["summary"] = {{"session_count", records.size()},
                               {"expired_removed_count", expired_removed.size()}};
        response["data"] = {{"sessions", records}};
        if (!expired_removed.empty()) response["data"]["removed"] = expired_removed;
        return response;
    }
    if (action == "session.gc") {
        Json before = Json::array();
        for (const auto& record : sessions_.list()) before.push_back(session_record_json(record));
        Json removed = Json::array();
        Json cleanup_error;
        if (!cleanup_expired_sessions(request, removed, cleanup_error)) return cleanup_error;
        Json kept = Json::array();
        for (const auto& record : sessions_.list()) {
            Json doctor_req = request;
            doctor_req["action"] = "session.doctor";
            doctor_req["target"] = {{"session_id", record.id}};
            Json health = forward_action(doctor_req);
            bool healthy = health.value("ok", false);
            if (healthy) {
                kept.push_back({{"session_id", record.id}, {"mode", record.mode}});
            } else {
                Json removed_item = kill_session_record(request, record, "unhealthy");
                removed_item["health"] = health;
                removed.push_back(removed_item);
            }
        }
        Json response = make_response(request, action);
        response["summary"] = {{"status", "completed"},
                               {"before_count", before.size()},
                               {"kept_count", kept.size()},
                               {"removed_count", removed.size()}};
        response["data"] = {{"before", before}, {"kept", kept}, {"removed", removed}};
        return response;
    }
    if (action == "session.open") {
        const std::string name = requested_name(request);
        const std::string mode = mode_for_target(target);
        if (name.empty()) return make_error(request, action, "MISSING_FIELD", "args.name is required");
        if (!xdebug_core::is_valid_session_name(name)) {
            return make_error(request, action, "INVALID_SESSION_NAME", xdebug_core::session_name_rule());
        }
        if (args.contains("reuse") || args.contains("reopen")) {
            return make_error(request, action, "INVALID_REQUEST",
                              "session.open does not accept args.reuse or args.reopen; close or gc existing sessions explicitly");
        }
        if (mode.empty()) return make_error(request, action, "RESOURCE_REQUIRED", "target.daidir or target.fsdb is required");
        Json manifest_details;
        Json manifest_error;
        if (!validate_run_manifest(request, target, manifest_details, manifest_error)) return manifest_error;
        Json expired_removed;
        Json cleanup_error;
        if (!cleanup_expired_sessions(request, expired_removed, cleanup_error)) return cleanup_error;
        std::vector<SessionRecord> before_records = sessions_.list();
        SessionRecord existing;
        if (sessions_.get(name, existing)) {
            Json doctor_req = request;
            doctor_req["action"] = "session.doctor";
            doctor_req["target"] = {{"session_id", name}};
            Json health = forward_action(doctor_req);
            if (health.value("ok", false)) {
                Json err = make_error(request, action, "SESSION_ID_EXISTS",
                                      "session id already exists: " + name);
                err["summary"] = {{"session_id", name}, {"existing", session_record_json(existing)},
                                  {"health", health}};
                return err;
            }
            Json err = make_error(request, action, "SESSION_STALE",
                                  "session id exists but is stale: " + name +
                                      "; close it explicitly or run session.gc before opening again");
            err["summary"] = {{"session_id", name}, {"existing", session_record_json(existing)},
                              {"health", health}};
            return err;
        }
        // Spawn ONE unified engine (handles design, waveform, or both).
        Json open_request = request;
        open_request["action"] = "session.open";
        open_request["target"] = target;
        Json result = forward_action(open_request);
        if (!result.value("ok", false)) return result;
        SessionRecord record;
        record.id = name;
        record.mode = mode;
        record.daidir = target.value("daidir", std::string());
        record.fsdb = target.value("fsdb", std::string());
        // Extract socket_path from engine response for direct socket communication
        Json backend_session = result.value("session", Json::object());
        record.socket_path = backend_session.value("socket_path", "");
        record.transport = backend_session.value("transport", std::string("uds"));
        record.file_dir = backend_session.value("file_dir", std::string());
        record.host = backend_session.value("host", std::string());
        record.bind_host = backend_session.value("bind_host", std::string());
        record.port = backend_session.value("port", 0);
        record.server_host = backend_session.value("server_host", std::string());
        xdebug_core::update_public_session_manifest(record.id, record.mode, record.daidir, record.fsdb);
        Json response = make_response(request, action);
        response["session"] = session_record_json(record);
        response["summary"] = {{"session_id", name}, {"mode", mode},
                               {"resource_snapshot", {{"daidir", record.daidir.empty() ? Json(nullptr) : Json(record.daidir)},
                                                      {"fsdb", record.fsdb.empty() ? Json(nullptr) : Json(record.fsdb)},
                                                      {"run_manifest", manifest_details.empty() ? Json(nullptr) : manifest_details}}}};
        response["data"] = {{"session", response["session"]}};
        Json advisories = duplicate_resource_advisories(before_records, record);
        if (!advisories.empty()) response["advisories"] = advisories;
        return response;
    }
    std::string id = target.value("session_id", std::string());
    if (id == "all") {
        Json results = Json::array();
        int removed_count = 0;
        for (const auto& record : sessions_.list()) {
            Json kill_req = request;
            kill_req["target"] = {{"session_id", record.id}};
            kill_req["args"] = Json::object();
            Json result = handle_session(kill_req, "session.kill");
            if (result.value("ok", false)) removed_count++;
            results.push_back({{"session_id", record.id}, {"mode", record.mode}, {"result", result}});
        }
        Json response = make_response(request, action);
        response["ok"] = removed_count == static_cast<int>(results.size());
        response["summary"] = {{"status", "removed"}, {"target", "all"},
                               {"requested_count", results.size()}, {"removed_count", removed_count}};
        response["data"] = {{"results", results}};
        if (!response["ok"].get<bool>()) {
            response["error"] = {{"code", "SESSION_CLEANUP_PARTIAL_FAILURE"},
                                 {"message", "one or more session engines could not be stopped"},
                                 {"recoverable", true}};
        }
        return response;
    }
    if (id.empty()) return make_error(request, action, "MISSING_FIELD", "target.session_id is required");
    SessionRecord record;
    if (!sessions_.get(id, record)) return make_error(request, action, "SESSION_NOT_FOUND", "session not found: " + id);
    if (action == "session.kill" || action == "session.close") {
        Json inner = request;
        inner["action"] = "session.kill";
        inner["target"] = {{"session_id", id}};
        Json r = forward_action(inner);
        bool ok = backend_cleanup_ok(r);
        Json response = make_response(request, action, ok);
        response["summary"] = {{"session_id", id}, {"mode", record.mode}, {"removed", ok}};
        response["data"] = {{"session", session_record_json(record)}, {"backends", r}};
        if (!ok) response["error"] = {{"code", "SESSION_CLEANUP_FAILED"},
                                      {"message", "backend cleanup failed; the session record was preserved for retry and diagnosis"},
                                      {"recoverable", true}};
        return response;
    }
    if (action == "session.doctor") {
        std::string resource_message;
        if (session_resource_changed(record, resource_message)) {
            Json response = make_response(request, action, false);
            response["session"] = session_record_json(record);
            response["summary"] = {{"session_id", id}, {"mode", record.mode},
                                   {"healthy", false}, {"status", "resource_changed"},
                                   {"message", resource_message}};
            response["data"] = {{"health", response["summary"]}};
            response["error"] = {{"code", "RESOURCE_CHANGED"},
                                 {"message", resource_message},
                                 {"recoverable", true}};
            return response;
        }
        Json inner = request;
        inner["target"] = {{"session_id", id}};
        Json health = forward_action(inner);
        Json response = make_response(request, action);
        response["ok"] = health.value("ok", false);
        response["session"] = session_record_json(record);
        response["summary"] = {{"session_id", id}, {"mode", record.mode}, {"healthy", health.value("ok", false)}};
        response["data"] = {{"health", health}};
        if (!response["ok"].get<bool>()) response["error"] = {{"code", "SESSION_UNHEALTHY"}, {"message", "session engine is unhealthy"}, {"recoverable", true}};
        return response;
    }
    return make_error(request, action, "UNKNOWN_ACTION", "unknown session action: " + action);
}

Json Dispatcher::dispatch_impl(const Json& request) {
    const std::string action = request.value("action", std::string());
    const ActionSpec* spec = default_action_registry().find_spec(action);
    if (!spec) {
        Json suggestions = suggested_action_names(action);
        Json error = DiagnosticErrorBuilder::handler(
                         "UNKNOWN_ACTION", "unknown action: " + action)
                         .invalid_arg("action")
                         .received(action)
                         .available_values(suggestions)
                         .did_you_mean(suggestions.empty() ? "" : suggestions[0].get<std::string>())
                         .to_json();
        error["suggested_actions"] = suggestions;
        return make_error(request, action, error);
    }

    RequestEnvelope envelope = RequestEnvelope::from_json(request);
    RequestValidator validator;
    ValidationResult validation = validator.validate(envelope, *spec);
    if (!validation.ok) {
        Json error = validation.error;
        if (!error.is_object()) {
            error = DiagnosticErrorBuilder::schema(
                validation.code.empty() ? "INVALID_REQUEST" : validation.code,
                validation.message).to_json();
        }
        Json response = make_error(request, action, error);
        return response;
    }

    if (spec->handler_kind == "schema") return catalog_schema_response(request);
    if (spec->handler_kind == "actions") return catalog_actions_response(request);
    if (spec->handler_kind == "batch") return handle_batch(request);
    if (spec->handler_kind == "session") return handle_session(request, action);
    if (spec->handler_kind == "engine_forward") {
        return handle_engine_forward(request, *spec);
    }
    return make_error(request, action, "NOT_IMPLEMENTED", "no handler registered for action: " + action);
}

Json Dispatcher::dispatch(const Json& request) {
    using clock = std::chrono::steady_clock;
    const auto begin = clock::now();
    const std::string action = request.value("action", std::string());
    const std::string begin_session = request_log_session_id(request);
    Json begin_context = {
        {"request", xdebug_core::request_summary_for_log(request)}
    };
    xdebug_core::log_action_event("public", "xdebug", begin_session, action, "begin", true, 0, begin_context);

    Json response;
    try {
        response = dispatch_impl(request);
        if (!action.empty()) {
            const ActionSpec* completed_spec =
                default_action_registry().find_spec(action);
            if (completed_spec) append_recommended_actions(response, *completed_spec);
        }
    } catch (const std::exception& e) {
        response = make_error(request, action, "INTERNAL_ERROR", e.what(), false);
    } catch (...) {
        response = make_error(request, action, "INTERNAL_ERROR", "unhandled exception", false);
    }

    const auto end = clock::now();
    long long elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(end - begin).count();
    const bool ok = response.value("ok", false);
    const std::string session_id = request_log_session_id(request, response);
    Json context = {
        {"request", xdebug_core::request_summary_for_log(request)},
        {"response", xdebug_core::response_summary_for_log(response)},
        {"mode", target_mode_for_log(request, response)}
    };
    if (!ok) {
        context["request_compact"] = xdebug_core::sanitize_for_log(request);
        context["response_compact"] = xdebug_core::sanitize_for_log(response);
    }
    xdebug_core::log_action_event("public", "xdebug", session_id, action, "end", ok, elapsed_ms, context);
    return response;
}

bool Dispatcher::send_to_socket(const std::string& session_id,
                                const std::string& socket_path,
                                const std::string& category,
                                const Json& request,
                                Json& response) const {
    const std::string action = request.value("action", std::string());
    const int timeout_ms = request_timeout_ms(request);
    auto begin = std::chrono::steady_clock::now();
    log_engine_transport(session_id, "socket.connect.begin", true,
                         transport_context(request, "socket.connect.begin", session_id, socket_path, timeout_ms));
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        Json ctx = transport_context(request, "socket.create.failed", session_id, socket_path, timeout_ms);
        ctx["errno"] = errno;
        ctx["message"] = strerror(errno);
        ctx["elapsed_ms"] = elapsed_ms_since(begin);
        log_engine_transport(session_id, "socket.create.failed", false, ctx);
        return false;
    }
    set_socket_timeout(fd, timeout_ms);

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path.c_str(), sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        int err = errno;
        close(fd);
        Json ctx = transport_context(request, "socket.connect.failed", session_id, socket_path, timeout_ms);
        ctx["errno"] = err;
        ctx["message"] = strerror(err);
        ctx["elapsed_ms"] = elapsed_ms_since(begin);
        log_engine_transport(session_id, "socket.connect.failed", false, ctx);
        return false;
    }
    Json connect_ctx = transport_context(request, "socket.connect.ok", session_id, socket_path, timeout_ms);
    connect_ctx["elapsed_ms"] = elapsed_ms_since(begin);
    log_engine_transport(session_id, "socket.connect.ok", true, connect_ctx);

    // Build internal request for engine server
    Json rpc = request;
    rpc["api_version"] = "xdebug.internal.v1";
    std::string wire = rpc.dump() + "\n";
    ssize_t written = write(fd, wire.c_str(), wire.size());
    if (written != static_cast<ssize_t>(wire.size())) {
        int err = errno;
        close(fd);
        Json ctx = transport_context(request, "socket.write.failed", session_id, socket_path, timeout_ms);
        ctx["errno"] = err;
        ctx["message"] = strerror(err);
        ctx["bytes_expected"] = wire.size();
        ctx["bytes_written"] = written < 0 ? 0 : written;
        ctx["elapsed_ms"] = elapsed_ms_since(begin);
        if (is_socket_timeout_errno(err)) {
            response = direct_socket_timeout_error(request, action, socket_path, timeout_ms);
            log_engine_transport(session_id, "socket.write.timeout", false, ctx);
            return true;
        }
        log_engine_transport(session_id, "socket.write.failed", false, ctx);
        return false;
    }

    // Read response — engine server closes fd after sending.
    std::string line;
    char buf[65536];
    while (true) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            int err = errno;
            close(fd);
            Json ctx = transport_context(request, "socket.read.failed", session_id, socket_path, timeout_ms);
            ctx["errno"] = err;
            ctx["message"] = strerror(err);
            ctx["elapsed_ms"] = elapsed_ms_since(begin);
            if (is_socket_timeout_errno(err)) {
                response = direct_socket_timeout_error(request, action, socket_path, timeout_ms);
                log_engine_transport(session_id, "socket.read.timeout", false, ctx);
                return true;
            }
            log_engine_transport(session_id, "socket.read.failed", false, ctx);
            return false;
        }
        if (n <= 0) break;
        line.append(buf, static_cast<size_t>(n));
    }
    close(fd);

    Json engine_resp;
    try {
        engine_resp = Json::parse(line);
    } catch (...) {
        Json ctx = transport_context(request, "socket.response_parse_failed", session_id, socket_path, timeout_ms);
        ctx["response_bytes"] = line.size();
        ctx["elapsed_ms"] = elapsed_ms_since(begin);
        log_engine_transport(session_id, "socket.response_parse_failed", false, ctx);
        return false;
    }

    if (!engine_resp.value("ok", false)) {
        Json err = engine_resp.value("error", Json::object());
        response = make_error(request, action, err);
        Json ctx = transport_context(request, "socket.request.end", session_id, socket_path, timeout_ms);
        ctx["elapsed_ms"] = elapsed_ms_since(begin);
        ctx["engine_response"] = xdebug_core::sanitize_for_log(engine_resp);
        log_engine_transport(session_id, "socket.request.end", false, ctx);
        return true;
    }

    // Wrap engine response into xdebug.v1 format.
    // The engine owns summary construction. Do not infer public summary from
    // arbitrary data scalars because that creates two public sources for the
    // same fact.
    Json data_payload = engine_resp.value("data", Json::object());
    response = make_response(request, action, true);
    Json result_summary = data_payload.value("summary", Json::object());
    if (data_payload.is_object() && data_payload.contains("summary")) {
        data_payload.erase("summary");
    }
    bool truncated = false;
    if (data_payload.is_object() && data_payload.contains("truncated") &&
        data_payload["truncated"].is_boolean()) {
        truncated = data_payload["truncated"].get<bool>();
        data_payload.erase("truncated");
    }
    if (result_summary.is_object() &&
        result_summary.contains("truncated") && result_summary["truncated"].is_boolean()) {
        truncated = truncated || result_summary["truncated"].get<bool>();
        result_summary.erase("truncated");
    }
    if (result_summary.is_object() && !result_summary.empty()) response["summary"] = result_summary;
    if (data_payload.is_object() && data_payload.contains("suggested_next_actions") &&
        data_payload["suggested_next_actions"].is_array()) {
        response["suggested_next_actions"] = data_payload["suggested_next_actions"];
        data_payload.erase("suggested_next_actions");
    }
    if (truncated) response["meta"] = {{"truncated", true}};
    if (engine_resp.contains("text") && engine_resp["text"].is_string()) {
        response["text"] = engine_resp["text"];
    }
    response["data"] = data_payload;
    Json ctx = transport_context(request, "socket.request.end", session_id, socket_path, timeout_ms);
    ctx["elapsed_ms"] = elapsed_ms_since(begin);
    ctx["response"] = xdebug_core::response_summary_for_log(response);
    log_engine_transport(session_id, "socket.request.end", true, ctx);
    return true;
}

} // namespace xdebug
