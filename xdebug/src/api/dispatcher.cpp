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
#include "core/schema/runtime_schema_validator.h"
#include "engine/service/contract_bound_request.h"
#include "logging/action_log.h"

#include <chrono>
#include <cerrno>
#include <ctime>
#include <fcntl.h>
#include <initializer_list>
#include <limits.h>
#include <set>
#include <stdexcept>
#include <string>
#include <fstream>
#include <unistd.h>
#include <sys/stat.h>

namespace xdebug {

using xdebug_core::DiagnosticErrorBuilder;

namespace {

bool has_string(const Json& object, const char* key) {
    return object.contains(key) && object[key].is_string() &&
           !object[key].get<std::string>().empty();
}

void append_recommended_actions(
    Json& response,
    const ActionSpec& spec) {
    if (!response.value("ok", false) ||
        spec.recommended_actions.empty()) {
        return;
    }
    if (!response.contains("data") ||
        !response["data"].is_object()) {
        throw std::runtime_error(
            "successful load response requires an object data payload");
    }
    Json recommendations = Json::array();
    for (const ActionRecommendation& recommendation :
         spec.recommended_actions) {
        recommendations.push_back({
            {"action", recommendation.action},
            {"purpose", recommendation.purpose},
        });
    }
    response["data"]["recommended_actions"] =
        std::move(recommendations);
}

std::string request_action(const Json& request) {
    return has_string(request, "action")
        ? request["action"].get<std::string>()
        : std::string();
}

Json session_lifecycle_request(const Json& parent_request,
                               const std::string& action,
                               const std::string& session_id) {
    Json request = {
        {"api_version", kApiVersion},
        {"action", action},
        {"target", {{"session_id", session_id}}},
        {"args", Json::object()},
    };
    if (has_string(parent_request, "request_id")) {
        request["request_id"] = parent_request["request_id"];
    }
    if (action == "session.kill" &&
        parent_request.value("action", std::string()) ==
            "session.kill" &&
        parent_request.contains("args") &&
        parent_request["args"].is_object() &&
        has_string(parent_request["args"], "ownership_token")) {
        request["args"]["ownership_token"] =
            parent_request["args"]["ownership_token"];
    }
    return request;
}

Json public_envelope_error(const Json& request) {
    if (!request.is_object()) {
        return DiagnosticErrorBuilder::schema(
                   "INVALID_REQUEST",
                   "public request must be a JSON object")
            .expected("object")
            .received_type(request.type_name())
            .to_json();
    }
    static const std::set<std::string> allowed = {
        "api_version",
        "request_id",
        "action",
        "target",
        "args",
        "limits",
    };
    for (auto it = request.begin(); it != request.end(); ++it) {
        if (allowed.count(it.key()) != 0) continue;
        return DiagnosticErrorBuilder::schema(
                   "INVALID_REQUEST",
                   "public request contains unknown field: " + it.key())
            .invalid_arg(it.key())
            .expected(
                "one of api_version, request_id, action, target, args, limits")
            .received(it.value())
            .received_type(it.value().type_name())
            .to_json();
    }
    if (!has_string(request, "api_version") ||
        request["api_version"].get<std::string>() != kApiVersion) {
        Json error = DiagnosticErrorBuilder::schema(
                         "UNSUPPORTED_API_VERSION",
                         "expected xdebug.v1")
                         .invalid_arg("api_version")
                         .expected(kApiVersion)
                         .to_json();
        if (request.contains("api_version")) {
            error["received"] = request["api_version"];
        }
        return error;
    }
    if (!has_string(request, "action")) {
        Json error = DiagnosticErrorBuilder::schema(
                         "INVALID_REQUEST",
                         "action must be a non-empty string")
                         .invalid_arg("action")
                         .expected("non-empty action string")
                         .to_json();
        if (request.contains("action")) {
            error["received"] = request["action"];
            error["received_type"] =
                request["action"].type_name();
        }
        return error;
    }
    if (request.contains("request_id") &&
        (!request["request_id"].is_string() ||
         request["request_id"].get<std::string>().empty())) {
        return DiagnosticErrorBuilder::schema(
                   "INVALID_REQUEST",
                   "request_id must be a non-empty string")
            .invalid_arg("request_id")
            .expected("non-empty string")
            .received(request["request_id"])
            .received_type(request["request_id"].type_name())
            .to_json();
    }
    for (const char* field : {"target", "args", "limits"}) {
        if (!request.contains(field) ||
            request[field].is_object()) {
            continue;
        }
        return DiagnosticErrorBuilder::schema(
                   "INVALID_REQUEST",
                   std::string(field) + " must be an object")
            .invalid_arg(field)
            .expected("object")
            .received(request[field])
            .received_type(request[field].type_name())
            .to_json();
    }
    return Json();
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

Json manifest_mismatch(const Json& request,
                       const std::string& message,
                       const Json& evidence) {
    Json error =
        DiagnosticErrorBuilder::handler(
            "RESOURCE_PROVENANCE_MISMATCH",
            message)
            .to_json();
    for (const char* field : {
             "manifest_path",
             "resource",
             "expected_path",
             "actual_path",
             "expected_size_bytes",
             "actual_size_bytes",
             "expected_sha256",
             "actual_sha256"}) {
        if (evidence.contains(field)) {
            error[field] = evidence[field];
        }
    }
    if (evidence.contains("schema_version")) {
        error["manifest_schema_version"] = evidence["schema_version"];
    }
    if (evidence.contains("state")) {
        error["manifest_state"] = evidence["state"];
    }
    return make_error(request, "session.open", error);
}

Json manifest_evidence(const Json& manifest) {
    Json evidence = Json::object();
    for (const char* field :
         {"manifest_path", "schema_version", "state"}) {
        if (manifest.contains(field) &&
            manifest[field].is_string()) {
            evidence[field] = manifest[field];
        }
    }
    return evidence;
}

bool manifest_object_has_only(
    const Json& value,
    std::initializer_list<const char*> allowed_fields,
    std::string& unexpected) {
    if (!value.is_object()) return false;
    std::set<std::string> allowed;
    for (const char* field : allowed_fields) allowed.insert(field);
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (allowed.find(it.key()) == allowed.end()) {
            unexpected = it.key();
            return false;
        }
    }
    return true;
}

bool valid_manifest_sha256(const std::string& digest) {
    if (digest.size() != 64) return false;
    for (char c : digest) {
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool valid_conditional_cleanup_token(const std::string& token) {
    if (token.size() != 64) return false;
    for (const char c : token) {
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool generate_conditional_cleanup_token(std::string& token) {
    token.clear();
    unsigned char bytes[32] = {};
    int flags = O_RDONLY;
#ifdef O_CLOEXEC
    flags |= O_CLOEXEC;
#endif
    int fd = -1;
    do {
        fd = open("/dev/urandom", flags);
    } while (fd < 0 && errno == EINTR);
    if (fd < 0) return false;

    size_t offset = 0;
    while (offset < sizeof(bytes)) {
        const ssize_t count =
            read(fd, bytes + offset, sizeof(bytes) - offset);
        if (count > 0) {
            offset += static_cast<size_t>(count);
            continue;
        }
        if (count < 0 && errno == EINTR) continue;
        close(fd);
        return false;
    }
    close(fd);

    static const char hex[] = "0123456789abcdef";
    token.reserve(sizeof(bytes) * 2);
    for (const unsigned char byte : bytes) {
        token.push_back(hex[byte >> 4]);
        token.push_back(hex[byte & 0x0f]);
    }
    return true;
}

std::string redact_sensitive_text(
    std::string text,
    const std::string& sensitive_value) {
    if (sensitive_value.empty()) return text;
    size_t offset = 0;
    while ((offset = text.find(
                sensitive_value,
                offset)) != std::string::npos) {
        static const std::string replacement =
            "<redacted:sensitive-value>";
        text.replace(
            offset,
            sensitive_value.size(),
            replacement);
        offset += replacement.size();
    }
    return text;
}

void redact_sensitive_plaintext(
    Json& value,
    const std::string& sensitive_value) {
    if (sensitive_value.empty()) return;
    if (value.is_string()) {
        value = redact_sensitive_text(
            value.get<std::string>(),
            sensitive_value);
        return;
    }
    if (value.is_array()) {
        for (Json& item : value) {
            redact_sensitive_plaintext(
                item,
                sensitive_value);
        }
        return;
    }
    if (value.is_object()) {
        Json redacted = Json::object();
        for (auto it = value.begin();
             it != value.end();
             ++it) {
            Json child = it.value();
            redact_sensitive_plaintext(
                child,
                sensitive_value);
            redacted[
                redact_sensitive_text(
                    it.key(),
                    sensitive_value)] =
                child;
        }
        value = redacted;
    }
}

Json session_conditional_cleanup_error(
    const Json& request,
    const std::string& public_action,
    const SessionRecord& record) {
    const Json args =
        request.value("args", Json::object());
    const std::string ownership_token =
        has_string(args, "ownership_token")
            ? args["ownership_token"].get<std::string>()
            : std::string();

    // This is a conditional cleanup precondition, not a general lifecycle
    // authorization model.  Existing admin/GC calls that omit the key retain
    // their established unconditional semantics.  A supplied key, however,
    // must prove it refers to the record created by the corresponding open.
    if (public_action == "session.close" ||
        ownership_token.empty()) {
        return Json();
    }
    if (record.ownership_token_hash.empty() ||
        !valid_conditional_cleanup_token(ownership_token) ||
        xdebug_core::sha256_text(ownership_token) !=
            record.ownership_token_hash) {
        return make_error(
            request,
            public_action,
            "SESSION_OWNERSHIP_TOKEN_MISMATCH",
            "the supplied ownership token does not match this session.open record",
            false);
    }
    return Json();
}

bool parse_manifest_size_bytes(
    const Json& value,
    unsigned long long& size_bytes) {
    if (value.is_number_unsigned()) {
        size_bytes = value.get<unsigned long long>();
        return true;
    }
    if (!value.is_number_integer()) return false;
    const long long signed_size = value.get<long long>();
    if (signed_size < 0) return false;
    size_bytes = static_cast<unsigned long long>(signed_size);
    return true;
}

bool validate_manifest_resource_shape(
    const Json& resource,
    const std::string& key,
    std::string& message) {
    std::string unexpected;
    if (!manifest_object_has_only(
            resource,
            {"path", "size_bytes", "sha256"},
            unexpected)) {
        message = resource.is_object()
            ? "run manifest resource " + key +
                  " contains unknown field: " + unexpected
            : "run manifest resource " + key +
                  " must be a JSON object";
        return false;
    }
    unsigned long long size_bytes = 0;
    if (resource.size() != 3 ||
        !has_string(resource, "path") ||
        resource["path"].get<std::string>()[0] == '/' ||
        !resource.contains("size_bytes") ||
        !parse_manifest_size_bytes(
            resource["size_bytes"], size_bytes) ||
        !has_string(resource, "sha256") ||
        !valid_manifest_sha256(
            resource["sha256"].get<std::string>())) {
        message =
            "run manifest resource " + key +
            " must contain exactly relative path, non-negative "
            "size_bytes, and lowercase 64-hex sha256";
        return false;
    }
    return true;
}

bool validate_manifest_resource(const Json& request, const std::string& manifest_path,
                                const std::string& key, const std::string& target_path,
                                Json& details, Json& error_response) {
    Json evidence = manifest_evidence(details);
    evidence["manifest_path"] = manifest_path;
    evidence["resource"] = key;
    if (!details.contains("resources") || !details["resources"].is_object() ||
        !details["resources"].contains(key) || !details["resources"][key].is_object()) {
        error_response = manifest_mismatch(
            request,
            "run manifest does not declare resource: " + key,
            evidence);
        return false;
    }
    const Json& declared = details["resources"][key];
    const std::string relative =
        has_string(declared, "path")
            ? declared["path"].get<std::string>()
            : std::string();
    unsigned long long size = 0;
    const bool has_size =
        declared.contains("size_bytes") &&
        parse_manifest_size_bytes(declared["size_bytes"], size);
    const std::string expected_sha =
        has_string(declared, "sha256")
            ? declared["sha256"].get<std::string>()
            : std::string();
    if (!relative.empty()) evidence["expected_path"] = relative;
    if (has_size) evidence["expected_size_bytes"] = size;
    if (!expected_sha.empty()) evidence["expected_sha256"] = expected_sha;
    if (relative.empty() || !has_size || expected_sha.size() != 64) {
        error_response = manifest_mismatch(
            request,
            "run manifest has incomplete resource declaration: " + key,
            evidence);
        return false;
    }
    std::string expected_path, actual_path;
    if (!canonical_path(dirname_of(manifest_path) + "/" + relative, expected_path) ||
        !canonical_path(target_path, actual_path) || expected_path != actual_path) {
        if (!actual_path.empty()) evidence["actual_path"] = actual_path;
        error_response = manifest_mismatch(
            request,
            "run manifest resource path does not match target: " + key,
            evidence);
        return false;
    }
    evidence["actual_path"] = actual_path;
    struct stat st;
    const int stat_result = stat(actual_path.c_str(), &st);
    if (stat_result != 0 || st.st_size < 0 ||
        static_cast<unsigned long long>(st.st_size) != size) {
        evidence["expected_size_bytes"] = size;
        evidence["actual_size_bytes"] =
            stat_result == 0
                ? Json(static_cast<unsigned long long>(st.st_size))
                : Json(nullptr);
        error_response = manifest_mismatch(
            request,
            "run manifest resource size does not match target: " + key,
            evidence);
        return false;
    }
    std::string actual_sha, sha_error;
    const bool is_directory = S_ISDIR(st.st_mode);
    const bool digest_ok = is_directory
        ? xdebug_core::sha256_directory_tree(actual_path, actual_sha, sha_error)
        : xdebug_core::sha256_file(actual_path, actual_sha, sha_error);
    if (!digest_ok || actual_sha != expected_sha) {
        evidence["expected_sha256"] = expected_sha;
        evidence["actual_sha256"] =
            actual_sha.empty() ? Json(nullptr) : Json(actual_sha);
        error_response = manifest_mismatch(
            request,
            "run manifest resource SHA-256 does not match target: " + key,
            evidence);
        return false;
    }
    return true;
}

bool validate_run_manifest(const Json& request, const Json& target, Json& details, Json& error_response) {
    if (!has_string(target, "run_manifest")) return true;
    const std::string requested_manifest =
        target["run_manifest"].get<std::string>();
    std::string manifest_path;
    if (!canonical_path(requested_manifest, manifest_path)) {
        error_response = manifest_mismatch(
            request,
            "run manifest is missing or cannot be resolved",
            {{"manifest_path", requested_manifest}});
        return false;
    }
    std::ifstream input(manifest_path.c_str());
    if (!input.good()) {
        error_response = manifest_mismatch(
            request,
            "run manifest cannot be opened",
            {{"manifest_path", manifest_path}});
        return false;
    }
    Json parsed;
    try {
        input >> parsed;
    } catch (...) {
        error_response = manifest_mismatch(
            request,
            "run manifest is not valid JSON",
            {{"manifest_path", manifest_path}});
        return false;
    }
    if (!parsed.is_object()) {
        error_response = manifest_mismatch(
            request,
            "run manifest root must be a JSON object",
            {{"manifest_path", manifest_path}});
        return false;
    }
    std::string unexpected;
    if (!manifest_object_has_only(
            parsed,
            {"schema_version", "state", "resources"},
            unexpected)) {
        error_response = manifest_mismatch(
            request,
            "run manifest contains unknown root field: " + unexpected,
            {{"manifest_path", manifest_path}});
        return false;
    }
    const std::string manifest_schema_version =
        has_string(parsed, "schema_version")
            ? parsed["schema_version"].get<std::string>()
            : std::string();
    const std::string manifest_state =
        has_string(parsed, "state")
            ? parsed["state"].get<std::string>()
            : std::string();
    if (manifest_schema_version != "xdebug.run-manifest.v1" ||
        manifest_state != "published") {
        error_response = manifest_mismatch(
            request,
            "run manifest must be xdebug.run-manifest.v1 in published state",
            {{"manifest_path", manifest_path},
             {"schema_version", manifest_schema_version},
             {"state", manifest_state}});
        return false;
    }
    if (!parsed.contains("resources") ||
        !parsed["resources"].is_object()) {
        error_response = manifest_mismatch(
            request,
            "run manifest resources must be a JSON object",
            {{"manifest_path", manifest_path},
             {"schema_version", manifest_schema_version},
             {"state", manifest_state}});
        return false;
    }
    Json& resources = parsed["resources"];
    if (!manifest_object_has_only(
            resources, {"fsdb", "daidir"}, unexpected) ||
        !resources.contains("fsdb")) {
        error_response = manifest_mismatch(
            request,
            resources.contains("fsdb")
                ? "run manifest resources contains unknown field: " +
                      unexpected
                : "run manifest resources must declare fsdb",
            {{"manifest_path", manifest_path},
             {"schema_version", manifest_schema_version},
             {"state", manifest_state}});
        return false;
    }
    for (const char* key : {"fsdb", "daidir"}) {
        if (!resources.contains(key)) continue;
        std::string shape_error;
        if (!validate_manifest_resource_shape(
                resources[key], key, shape_error)) {
            error_response = manifest_mismatch(
                request,
                shape_error,
                {{"manifest_path", manifest_path},
                 {"schema_version", manifest_schema_version},
                 {"state", manifest_state},
                 {"resource", key}});
            return false;
        }
    }
    const bool target_has_fsdb = has_string(target, "fsdb");
    const bool target_has_daidir = has_string(target, "daidir");
    const bool manifest_has_daidir = resources.contains("daidir");
    if (!target_has_fsdb ||
        target_has_daidir != manifest_has_daidir) {
        error_response = manifest_mismatch(
            request,
            "run manifest resources must exactly match target.fsdb and "
            "optional target.daidir",
            {{"manifest_path", manifest_path},
             {"schema_version", manifest_schema_version},
             {"state", manifest_state}});
        return false;
    }
    if (!validate_manifest_resource(
            request,
            manifest_path,
            "fsdb",
            target["fsdb"].get<std::string>(),
            parsed,
            error_response)) {
        return false;
    }
    if (target_has_daidir &&
        !validate_manifest_resource(
            request,
            manifest_path,
            "daidir",
            target["daidir"].get<std::string>(),
            parsed,
            error_response)) {
        return false;
    }
    details = {
        {"schema_version", manifest_schema_version},
        {"state", manifest_state},
        {"resources", resources},
        {"manifest_path", manifest_path},
    };
    return true;
}

bool resource_changed(const std::string& path,
                      long expected_mtime,
                      long long expected_size,
                      unsigned long long expected_dev,
                      unsigned long long expected_inode,
                      std::string& message,
                      std::string& changed_path) {
    if (path.empty() ||
        !fingerprint_recorded(expected_mtime, expected_size, expected_dev, expected_inode)) {
        return false;
    }
    struct stat st;
    if (stat(path.c_str(), &st) != 0) {
        message = "resource is missing or cannot be stat'ed: " + path;
        changed_path = path;
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
    changed_path = path;
    return true;
}

bool session_resource_changed(const SessionRecord& record,
                              std::string& message,
                              std::string& changed_path) {
    return resource_changed(record.daidir, record.dbdir_mtime, record.dbdir_size,
                            record.dbdir_dev, record.dbdir_inode,
                            message, changed_path) ||
           resource_changed(record.fsdb, record.fsdb_mtime, record.fsdb_size,
                            record.fsdb_dev, record.fsdb_inode,
                            message, changed_path);
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
    return has_string(args, "name")
        ? args["name"].get<std::string>()
        : std::string();
}

bool backend_cleanup_ok(const Json& response) {
    if (response.value("ok", false)) return true;
    Json error = response.value("error", Json::object());
    std::string code = error.value("code", std::string());
    return code == "SESSION_NOT_FOUND";
}

std::string backend_error_code(const Json& response) {
    if (!response.is_object()) return "";
    const Json error = response.value("error", Json::object());
    return error.is_object()
        ? error.value("code", std::string())
        : std::string();
}

bool ambiguous_session_open_result(const Json& response) {
    if (!response.is_object() ||
        !response.contains("ok") ||
        !response["ok"].is_boolean() ||
        response["ok"].get<bool>()) {
        return true;
    }
    const Json error =
        response.value("error", Json::object());
    if (!error.is_object() ||
        !has_string(error, "code") ||
        !has_string(error, "message") ||
        !error.contains("recoverable") ||
        !error["recoverable"].is_boolean() ||
        !has_string(error, "error_layer")) {
        return true;
    }
    const std::string code = backend_error_code(response);
    return code == "ENGINE_TIMEOUT" ||
           code == "INTERNAL_ENGINE_FAILED" ||
           code == "INTERNAL_ENGINE_RESPONSE_INVALID";
}

Json session_error(const Json& request,
                   const std::string& action,
                   const std::string& code,
                   const std::string& message,
                   const SessionRecord& record) {
    Json error =
        DiagnosticErrorBuilder::session_manager(code, message).to_json();
    error["session_id"] = record.id;
    error["session_mode"] = record.mode;
    error["session_transport"] = record.transport;
    return make_error(request, action, error);
}

Json catalog_error(const Json& request,
                   const SessionCatalogResult& result) {
    const std::string code =
        result.code.empty()
            ? (result.status == SessionCatalogStatus::NotFound
                   ? "SESSION_NOT_FOUND"
                   : "REGISTRY_INVALID")
            : result.code;
    const std::string message =
        result.message.empty()
            ? (result.status == SessionCatalogStatus::NotFound
                   ? "session not found"
                   : "canonical session registry is invalid")
            : result.message;
    return make_error(
        request,
        request.value("action", std::string()),
        DiagnosticErrorBuilder::session_manager(code, message).to_json());
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
    Json target =
        request.is_object() && request.contains("target") &&
                request["target"].is_object()
            ? request["target"]
            : Json::object();
    Json args =
        request.is_object() && request.contains("args") &&
                request["args"].is_object()
            ? request["args"]
            : Json::object();
    if (has_string(target, "session_id")) return target["session_id"].get<std::string>();
    if (has_string(args, "name")) return args["name"].get<std::string>();
    if (response.is_object()) {
        Json session = response.value("session", Json::object());
        if (has_string(session, "session_id")) return session["session_id"].get<std::string>();
        Json summary = response.value("summary", Json::object());
        if (has_string(summary, "session_id")) return summary["session_id"].get<std::string>();
    }
    return "adhoc";
}

std::string target_mode_for_log(const Json& request, const Json& response = Json()) {
    Json target =
        request.is_object() && request.contains("target") &&
                request["target"].is_object()
            ? request["target"]
            : Json::object();
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

bool Dispatcher::resolve_target(const Json& request,
                                Json& target,
                                Json& error_response) const {
    target = request.value("target", Json::object());
    if (has_string(target, "session_id") &&
        target["session_id"].get<std::string>() != "all") {
        SessionRecord record;
        const SessionCatalogResult lookup =
            sessions_.get(target["session_id"].get<std::string>(), record);
        if (!lookup.ok()) {
            error_response = catalog_error(request, lookup);
            return false;
        }
        if (!record.daidir.empty()) target["daidir"] = record.daidir;
        if (!record.fsdb.empty()) target["fsdb"] = record.fsdb;
        target["mode"] = record.mode;
    }
    stabilize_resource_paths(target);
    return true;
}

Json Dispatcher::invoke_engine(const Json& request,
                               const Json& resolved_target,
                               const Json& observability) {
    Json response;
    Json error;
    if (!adapter_.invoke(request, resolved_target, observability,
                         response, error)) {
        return make_error(
            request,
            request.value("action", std::string()),
            error);
    }
    return response;
}

Json Dispatcher::compensate_failed_session_open(
    const Json& request,
    const std::string& session_id,
    const std::string& ownership_token,
    const Json& observability,
    const std::string& failure_code,
    const std::string& failure_message) {
    Json error =
        DiagnosticErrorBuilder::internal(
            failure_code,
            failure_message)
            .to_json();
    error["session_id"] = session_id;
    error["cleanup_succeeded"] = false;
    error["compensation_status"] = "cleanup_failed";

    if (!valid_conditional_cleanup_token(ownership_token)) {
        error["cause_code"] = "INTERNAL_CLEANUP_TOKEN_INVALID";
        return make_error(
            request,
            "session.open",
            error);
    }

    Json kill_request =
        session_lifecycle_request(
            request,
            "session.kill",
            session_id);
    kill_request["args"]["ownership_token"] = ownership_token;
    Json cleanup = invoke_engine(
        kill_request,
        kill_request["target"],
        observability);
    const std::string backend_code =
        backend_error_code(cleanup);
    if (cleanup.value("ok", false)) {
        error["cleanup_succeeded"] = true;
        error["compensation_status"] = "cleaned";
    } else if (backend_code == "SESSION_NOT_FOUND") {
        error["cleanup_succeeded"] = true;
        error["compensation_status"] = "not_created";
    } else if (
        backend_code ==
        "SESSION_OWNERSHIP_TOKEN_MISMATCH") {
        error["compensation_status"] =
            "token_mismatch";
    }
    if (!backend_code.empty()) {
        error["backend_error_code"] = backend_code;
    }
    return make_error(
        request,
        "session.open",
        error);
}

Json Dispatcher::resource_error(const Json& request, const ActionSpec& spec, const Json& target) const {
    RequestEnvelope envelope = RequestEnvelope::from_json(request);
    envelope.target = target;
    ResourceResolver resolver;
    ResourceResolution resolution = resolver.resolve(envelope, spec);
    if (resolution.ok) return Json();
    return make_error(request, spec.name, resolution.code, resolution.message);
}

bool Dispatcher::kill_session_record(
    const Json& request,
    const SessionRecord& record,
    const Json& observability,
    std::string& backend_code) {
    Json kill_req =
        session_lifecycle_request(request, "session.kill", record.id);
    Json kill_result = invoke_engine(
        kill_req,
        kill_req["target"],
        observability);
    backend_code = backend_error_code(kill_result);
    return backend_cleanup_ok(kill_result);
}

bool Dispatcher::cleanup_expired_sessions(const Json& request,
                                          Json& removed,
                                          Json& error_response,
                                          const Json& observability) {
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
    std::vector<SessionRecord> records;
    const SessionCatalogResult listed = sessions_.list(records);
    if (!listed.ok()) {
        error_response = catalog_error(request, listed);
        return false;
    }
    for (const auto& record : records) {
        long long idle_sec = 0;
        if (!session_idle_expired(record, idle_timeout_sec, now, idle_sec)) continue;
        std::string cleanup_backend_error;
        if (!kill_session_record(
                request,
                record,
                observability,
                cleanup_backend_error)) {
            error_response = session_error(
                request,
                request.value("action", std::string()),
                "SESSION_CLEANUP_FAILED",
                "expired session backend cleanup failed; the session record "
                "was preserved for retry and diagnosis",
                record);
            error_response["error"]["cleanup_succeeded"] = false;
            error_response["error"]["idle_sec"] = idle_sec;
            error_response["error"]["idle_timeout_sec"] =
                idle_timeout_sec;
            if (!cleanup_backend_error.empty()) {
                error_response["error"]["backend_error_code"] =
                    cleanup_backend_error;
            }
            return false;
        }
        Json removed_item = {
            {"removed_session", session_record_json(record)},
            {"reason", "idle_timeout"},
        };
        removed_item["idle_sec"] = idle_sec;
        removed_item["idle_timeout_sec"] = idle_timeout_sec;
        removed.push_back(removed_item);
    }
    return true;
}

Json Dispatcher::handle_engine_forward(const Json& request,
                                       const ActionSpec& spec,
                                       const Json& observability) {
    Json target;
    Json target_error;
    if (!resolve_target(request, target, target_error)) {
        return target_error;
    }
    Json err_resp = resource_error(request, spec, target);
    if (!err_resp.is_null()) return err_resp;

    const std::string sid = target.value("session_id", std::string());
    if (!sid.empty()) {
        SessionRecord record;
        const SessionCatalogResult lookup = sessions_.get(sid, record);
        if (!lookup.ok()) {
            return catalog_error(request, lookup);
        }
        int idle_timeout_sec = 0;
        std::string timeout_error;
        if (!xdebug_core::session_idle_timeout_sec(idle_timeout_sec, timeout_error)) {
            return make_error(request, spec.name, "INVALID_CONFIG", timeout_error, false);
        }
        long long idle_sec = 0;
        if (session_idle_expired(record, idle_timeout_sec, time(nullptr), idle_sec)) {
            std::string cleanup_backend_error;
            const bool cleanup_succeeded = kill_session_record(
                request,
                record,
                observability,
                cleanup_backend_error);
            Json error =
                DiagnosticErrorBuilder::session_manager(
                    "SESSION_EXPIRED",
                    "session idle timeout exceeded: " + sid)
                    .to_json();
            error["session_id"] = sid;
            error["session_mode"] = record.mode;
            error["session_transport"] = record.transport;
            error["idle_sec"] = idle_sec;
            error["idle_timeout_sec"] = idle_timeout_sec;
            error["cleanup_succeeded"] =
                cleanup_succeeded;
            if (!cleanup_backend_error.empty()) {
                error["backend_error_code"] =
                    cleanup_backend_error;
            }
            return make_error(request, spec.name, error);
        }
    }

    // EngineAdapter is the single public-to-internal invocation boundary.
    // It projects the strict internal envelope, while the internal engine
    // owns UDS/TCP/file routing and authentication.
    return invoke_engine(request, target, observability);
}

Json Dispatcher::handle_batch(const Json& request,
                              const Json& observability) {
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
        Json child_observability = observability;
        child_observability.erase("request_id");
        Json result = dispatch(child, child_observability);
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
    response["summary"] = {{"count", results.size()}, {"all_ok", all_ok},
                           {"failed_count", failed_indexes.size()},
                           {"failed_indexes", failed_indexes},
                           {"failed_codes", failed_codes},
                           {"failed_layers", failed_layers}};
    response["data"] = {{"results", results}};
    return response;
}

Json Dispatcher::handle_session(
    const Json& request,
    const std::string& action,
    const Json& observability,
    std::string& session_open_cleanup_token) {
    Json target;
    Json target_error;
    if (!resolve_target(request, target, target_error)) {
        return target_error;
    }
    Json args = request.value("args", Json::object());
    if (action == "session.list") {
        Json expired_removed;
        Json cleanup_error;
        if (!cleanup_expired_sessions(
                request, expired_removed, cleanup_error, observability)) {
            return cleanup_error;
        }
        Json response = make_response(request, action);
        Json records = Json::array();
        std::vector<SessionRecord> listed_records;
        const SessionCatalogResult listed =
            sessions_.list(listed_records);
        if (!listed.ok()) return catalog_error(request, listed);
        for (const auto& record : listed_records) {
            records.push_back(session_record_json(record));
        }
        response["summary"] = {{"session_count", records.size()},
                               {"expired_removed_count", expired_removed.size()}};
        response["data"] = {{"sessions", records}};
        if (!expired_removed.empty()) response["data"]["removed"] = expired_removed;
        return response;
    }
    if (action == "session.gc") {
        std::vector<SessionRecord> before_records;
        const SessionCatalogResult before_listed =
            sessions_.list(before_records);
        if (!before_listed.ok()) {
            return catalog_error(request, before_listed);
        }
        Json removed = Json::array();
        Json cleanup_error;
        if (!cleanup_expired_sessions(
                request, removed, cleanup_error, observability)) {
            return cleanup_error;
        }
        Json kept_sessions = Json::array();
        std::vector<SessionRecord> after_cleanup;
        const SessionCatalogResult after_listed =
            sessions_.list(after_cleanup);
        if (!after_listed.ok()) {
            return catalog_error(request, after_listed);
        }
        for (const auto& record : after_cleanup) {
            Json doctor_req =
                session_lifecycle_request(
                    request, "session.doctor", record.id);
            Json health = invoke_engine(
                doctor_req,
                doctor_req["target"],
                observability);
            bool healthy = health.value("ok", false);
            if (healthy) {
                kept_sessions.push_back(session_record_json(record));
            } else {
                const Json health_error =
                    health.value("error", Json::object());
                if (!has_string(health_error, "code") ||
                    !has_string(health_error, "message")) {
                    return make_error(
                        request,
                        action,
                        "INTERNAL_ENGINE_RESPONSE_INVALID",
                        "failed session.doctor backend response is missing "
                        "error.code or error.message",
                        false);
                }
                std::string cleanup_backend_error;
                if (!kill_session_record(
                        request,
                        record,
                        observability,
                        cleanup_backend_error)) {
                    Json response = session_error(
                        request,
                        action,
                        "SESSION_CLEANUP_FAILED",
                        "unhealthy session backend cleanup failed; the "
                        "session record was preserved for retry and diagnosis",
                        record);
                    response["error"]["cleanup_succeeded"] = false;
                    if (!cleanup_backend_error.empty()) {
                        response["error"]["backend_error_code"] =
                            cleanup_backend_error;
                    }
                    return response;
                }
                Json health_evidence = {
                    {"code", health_error["code"]},
                    {"message", health_error["message"]},
                };
                if (has_string(health_error, "health_status")) {
                    health_evidence["health_status"] =
                        health_error["health_status"];
                }
                Json removed_item = {
                    {"removed_session", session_record_json(record)},
                    {"reason", "unhealthy"},
                    {"health_evidence", health_evidence},
                };
                removed.push_back(removed_item);
            }
        }
        Json response = make_response(request, action);
        response["summary"] = {{"before_count", before_records.size()},
                               {"kept_count", kept_sessions.size()},
                               {"removed_count", removed.size()}};
        response["data"] = {
            {"kept_sessions", kept_sessions},
            {"removed", removed},
        };
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
        if (!cleanup_expired_sessions(
                request, expired_removed, cleanup_error, observability)) {
            return cleanup_error;
        }
        std::vector<SessionRecord> before_records;
        const SessionCatalogResult before_listed =
            sessions_.list(before_records);
        if (!before_listed.ok()) {
            return catalog_error(request, before_listed);
        }
        SessionRecord existing;
        const SessionCatalogResult existing_lookup =
            sessions_.get(name, existing);
        if (existing_lookup.status == SessionCatalogStatus::Invalid) {
            return catalog_error(request, existing_lookup);
        }
        if (existing_lookup.ok()) {
            Json doctor_req =
                session_lifecycle_request(
                    request, "session.doctor", name);
            Json health = invoke_engine(
                doctor_req,
                doctor_req["target"],
                observability);
            if (health.value("ok", false)) {
                Json err = session_error(
                    request,
                    action,
                    "SESSION_ID_EXISTS",
                    "session id already exists: " + name,
                    existing);
                err["error"]["health_status"] = "healthy";
                return err;
            }
            Json err = session_error(
                request,
                action,
                "SESSION_STALE",
                "session id exists but is stale: " + name +
                    "; close it explicitly or run session.gc before opening again",
                existing);
            err["error"]["health_status"] =
                health.value("error", Json::object())
                    .value("health_status", std::string("unhealthy"));
            const std::string health_code = backend_error_code(health);
            if (!health_code.empty()) {
                err["error"]["backend_error_code"] = health_code;
            }
            return err;
        }
        // Spawn ONE unified engine (handles design, waveform, or both).
        if (has_string(args, "ownership_token")) {
            session_open_cleanup_token =
                args["ownership_token"].get<std::string>();
        } else if (!generate_conditional_cleanup_token(
                       session_open_cleanup_token)) {
            return make_error(
                request,
                action,
                DiagnosticErrorBuilder::internal(
                    "SECURE_RANDOM_UNAVAILABLE",
                    "failed to generate the internal conditional-cleanup token")
                    .to_json());
        }
        Json open_request = request;
        open_request["action"] = "session.open";
        open_request["target"] = target;
        open_request["args"]["ownership_token"] =
            session_open_cleanup_token;
        Json result = invoke_engine(
            open_request,
            target,
            observability);
        if (!result.value("ok", false)) {
            if (!ambiguous_session_open_result(result)) {
                return make_error(
                    request,
                    action,
                    result["error"]);
            }
            const std::string failure_code =
                backend_error_code(result);
            return compensate_failed_session_open(
                request,
                name,
                session_open_cleanup_token,
                observability,
                failure_code,
                "session.open engine invocation did not return a canonical result");
        }
        SessionRecord record;
        record.id = name;
        record.mode = mode;
        record.daidir = target.value("daidir", std::string());
        record.fsdb = target.value("fsdb", std::string());
        // Extract socket_path from engine response for direct socket communication
        Json backend_session = result.value("session", Json::object());
        if (!has_string(backend_session, "transport")) {
            return compensate_failed_session_open(
                request,
                name,
                session_open_cleanup_token,
                observability,
                "INTERNAL_ENGINE_RESPONSE_INVALID",
                "successful session.open backend response is missing session.transport");
        }
        const std::string backend_transport =
            backend_session["transport"].get<std::string>();
        if (backend_transport != "uds" &&
            backend_transport != "tcp" &&
            backend_transport != "file") {
            return compensate_failed_session_open(
                request,
                name,
                session_open_cleanup_token,
                observability,
                "INTERNAL_ENGINE_RESPONSE_INVALID",
                "successful session.open backend response has invalid session.transport");
        }
        record.socket_path = backend_session.value("socket_path", "");
        record.transport = backend_transport;
        record.file_dir = backend_session.value("file_dir", std::string());
        record.host = backend_session.value("host", std::string());
        record.bind_host = backend_session.value("bind_host", std::string());
        record.port = backend_session.value("port", 0);
        record.server_host = backend_session.value("server_host", std::string());
        Json public_record;
        try {
            public_record = session_record_json(record);
        } catch (...) {
            return compensate_failed_session_open(
                request,
                name,
                session_open_cleanup_token,
                observability,
                "INTERNAL_ENGINE_RESPONSE_INVALID",
                "successful session.open backend response is not canonical");
        }
        if (!xdebug_core::update_public_session_manifest(
                record.id,
                record.mode,
                record.daidir,
                record.fsdb)) {
            return compensate_failed_session_open(
                request,
                name,
                session_open_cleanup_token,
                observability,
                "SESSION_MANIFEST_WRITE_FAILED",
                "failed to publish the public session manifest");
        }
        Json response = make_response(request, action);
        response["session"] = public_record;
        response["summary"] = {{"status", "opened"}};
        response["data"] = {
            {"run_manifest",
             manifest_details.empty() ? Json(nullptr) : manifest_details},
        };
        Json advisories = duplicate_resource_advisories(before_records, record);
        if (!advisories.empty()) response["advisories"] = advisories;
        return response;
    }
    std::string id = target.value("session_id", std::string());
    if (id == "all") {
        Json removed_sessions = Json::array();
        Json failed_session_ids = Json::array();
        int removed_count = 0;
        std::vector<SessionRecord> records;
        const SessionCatalogResult listed = sessions_.list(records);
        if (!listed.ok()) return catalog_error(request, listed);
        if (has_string(args, "ownership_token")) {
            return make_error(
                request,
                action,
                "SESSION_OWNERSHIP_TOKEN_FORBIDDEN",
                "args.ownership_token is only valid for one exact session_id",
                false);
        }
        for (const auto& record : records) {
            std::string cleanup_backend_error;
            if (kill_session_record(
                    request,
                    record,
                    observability,
                    cleanup_backend_error)) {
                removed_count++;
                removed_sessions.push_back(
                    session_record_json(record));
            } else {
                failed_session_ids.push_back(record.id);
            }
        }
        if (removed_count != static_cast<int>(records.size())) {
            Json error =
                DiagnosticErrorBuilder::session_manager(
                    "SESSION_CLEANUP_PARTIAL_FAILURE",
                    "one or more session engines could not be stopped")
                    .to_json();
            error["requested_count"] = records.size();
            error["removed_count"] = removed_count;
            error["failed_session_ids"] = failed_session_ids;
            return make_error(request, action, error);
        }
        Json response = make_response(request, action);
        response["summary"] = {
            {"requested_count", records.size()},
            {"removed_count", removed_count},
        };
        response["data"] = {
            {"removed_sessions", removed_sessions},
        };
        return response;
    }
    if (id.empty()) return make_error(request, action, "MISSING_FIELD", "target.session_id is required");
    SessionRecord record;
    const SessionCatalogResult lookup = sessions_.get(id, record);
    if (!lookup.ok()) return catalog_error(request, lookup);
    if (action == "session.kill" || action == "session.close") {
        Json conditional_cleanup_error =
            session_conditional_cleanup_error(
                request,
                action,
                record);
        if (!conditional_cleanup_error.is_null() &&
            !conditional_cleanup_error.empty()) {
            return conditional_cleanup_error;
        }
        Json inner =
            session_lifecycle_request(request, "session.kill", id);
        Json r = invoke_engine(
            inner,
            inner["target"],
            observability);
        bool ok = backend_cleanup_ok(r);
        if (!ok) {
            Json response = session_error(
                request,
                action,
                "SESSION_CLEANUP_FAILED",
                "backend cleanup failed; the session record was preserved for retry and diagnosis",
                record);
            const std::string code = backend_error_code(r);
            if (!code.empty()) {
                response["error"]["backend_error_code"] = code;
            }
            return response;
        }
        Json response = make_response(request, action, ok);
        response["summary"] = {{"removed", ok}};
        response["data"] = {
            {"removed_session", session_record_json(record)},
        };
        return response;
    }
    if (action == "session.doctor") {
        std::string resource_message;
        std::string changed_path;
        if (session_resource_changed(
                record, resource_message, changed_path)) {
            Json response = session_error(
                request,
                action,
                "RESOURCE_CHANGED",
                resource_message,
                record);
            response["error"]["health_status"] = "resource_changed";
            response["error"]["resource_path"] = changed_path;
            return response;
        }
        Json inner =
            session_lifecycle_request(
                request, "session.doctor", id);
        Json health = invoke_engine(
            inner,
            inner["target"],
            observability);
        if (!health.value("ok", false)) {
            Json response = session_error(
                request,
                action,
                "SESSION_UNHEALTHY",
                "session engine is unhealthy",
                record);
            response["error"]["health_status"] =
                health.value("error", Json::object())
                    .value("health_status", std::string("unhealthy"));
            const std::string code = backend_error_code(health);
            if (!code.empty()) {
                response["error"]["backend_error_code"] = code;
            }
            return response;
        }
        Json response = make_response(request, action);
        response["session"] = session_record_json(record);
        const Json health_summary =
            health.value("summary", Json::object());
        if (!has_string(health_summary, "message")) {
            return make_error(
                request,
                action,
                "INTERNAL_ENGINE_RESPONSE_INVALID",
                "successful session.doctor backend response is missing "
                "summary.message",
                false);
        }
        response["summary"] = {{"healthy", true}};
        response["data"] = {
            {"message", health_summary["message"]},
        };
        return response;
    }
    return make_error(request, action, "UNKNOWN_ACTION", "unknown session action: " + action);
}

Json Dispatcher::dispatch_impl(
    const Json& request,
    const Json& supplied_observability,
    std::string& session_open_cleanup_token) {
    const std::string action = request_action(request);
    const Json envelope_error =
        public_envelope_error(request);
    if (!envelope_error.is_null()) {
        return make_error(request, action, envelope_error);
    }
    const ActionSpec* spec = default_action_registry().find_spec(action);
    if (!spec) {
        Json suggestions = suggested_action_names(action);
        Json error = DiagnosticErrorBuilder::handler(
                         "UNKNOWN_ACTION", "unknown action: " + action)
                         .invalid_arg("action")
                         .received(action)
                         .available_values(suggestions)
                         .to_json();
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

    const bool frontend_owns_args =
        spec->handler_kind == "schema" ||
        spec->handler_kind == "actions" ||
        spec->handler_kind == "batch";
    xdebug_design::ContractBoundRequest public_boundary(
        request,
        action,
        frontend_owns_args,
        true,
        false);
    auto finalize_public_consumption =
        [&](Json response) -> Json {
        if (!response.value("ok", false)) return response;
        const std::vector<std::string> unconsumed =
            public_boundary.unconsumed_paths();
        if (unconsumed.empty()) return response;
        return make_error(
            request,
            action,
            xdebug_core::request_consumption_violation(unconsumed));
    };

    Json observability = supplied_observability;
    if (request.contains("request_id")) {
        const std::string request_id =
            request["request_id"].get<std::string>();
        if (observability.contains("request_id") &&
            observability["request_id"] != request_id) {
            return make_error(
                request,
                action,
                DiagnosticErrorBuilder::internal(
                    "OBSERVABILITY_CONFLICT",
                    "observability.request_id conflicts with public request_id")
                    .to_json());
        }
        observability["request_id"] = request_id;
    }

    if (spec->handler_kind == "schema") {
        if (public_boundary.args().exists()) {
            public_boundary.args().consume_subtree(
                "catalog_schema_response");
        }
        return finalize_public_consumption(
            catalog_schema_response(request));
    }
    if (spec->handler_kind == "actions") {
        if (public_boundary.args().exists()) {
            public_boundary.args().consume_subtree(
                "catalog_actions_response");
        }
        return finalize_public_consumption(
            catalog_actions_response(request));
    }
    if (spec->handler_kind == "batch") {
        if (public_boundary.args().exists()) {
            public_boundary.args().consume_subtree(
                "Dispatcher::handle_batch");
        }
        return finalize_public_consumption(
            handle_batch(request, observability));
    }
    if (spec->handler_kind == "session") {
        public_boundary.consume_target(
            "Dispatcher::handle_session");
        return finalize_public_consumption(
            handle_session(
                request,
                action,
                observability,
                session_open_cleanup_token));
    }
    if (spec->handler_kind == "engine_forward") {
        public_boundary.consume_target(
            "Dispatcher::resolve_target+ResourceResolver");
        return finalize_public_consumption(
            handle_engine_forward(request, *spec, observability));
    }
    return make_error(request, action, "NOT_IMPLEMENTED", "no handler registered for action: " + action);
}

Json Dispatcher::dispatch(const Json& request,
                          const Json& supplied_observability) {
    using clock = std::chrono::steady_clock;
    const auto begin = clock::now();
    const std::string action = request_action(request);
    const std::string begin_session = request_log_session_id(request);
    Json begin_context = {
        {"request", xdebug_core::request_summary_for_log(request)}
    };
    xdebug_core::log_action_event("public", "xdebug", begin_session, action, "begin", true, 0, begin_context);

    Json response;
    last_xout_.clear();
    std::string session_open_cleanup_token;
    auto compensate_open_exception =
        [&](const std::string& failure_code,
            const std::string& failure_message) -> Json {
        Json observability =
            supplied_observability.is_object()
                ? supplied_observability
                : Json::object();
        if (has_string(request, "request_id")) {
            observability["request_id"] =
                request["request_id"];
        }
        try {
            return compensate_failed_session_open(
                request,
                requested_name(request),
                session_open_cleanup_token,
                observability,
                failure_code,
                failure_message);
        } catch (...) {
            Json error =
                DiagnosticErrorBuilder::internal(
                    failure_code,
                    failure_message)
                    .to_json();
            error["session_id"] = requested_name(request);
            error["cleanup_succeeded"] = false;
            error["compensation_status"] = "cleanup_failed";
            return make_error(
                request,
                "session.open",
                error);
        }
    };
    try {
        Json observability = supplied_observability;
        if (!observability.is_object()) {
            throw std::invalid_argument(
                "observability must be an object");
        }
        response = dispatch_impl(
            request,
            observability,
            session_open_cleanup_token);
        if (response.contains("__xout")) {
            if (response["__xout"].is_string())
                last_xout_ = response["__xout"].get<std::string>();
            response.erase("__xout");
        } else {
            last_xout_.clear();
        }
        if (!action.empty()) {
            const ActionSpec* completed_spec =
                default_action_registry().find_spec(action);
            if (completed_spec) {
                append_recommended_actions(
                    response, *completed_spec);
            }
        }
    } catch (const std::exception& e) {
        xdebug_core::log_lifecycle_event(
            "public",
            begin_session,
            "dispatch.exception",
            false,
            {{"action", action}, {"exception", e.what()}});
        response =
            action == "session.open" &&
                    valid_conditional_cleanup_token(
                        session_open_cleanup_token)
                ? compensate_open_exception(
                      "INTERNAL_ERROR",
                      "session.open frontend dispatch failed")
                : make_error(
                      request,
                      action,
                      "INTERNAL_ERROR",
                      "request dispatch failed",
                      false);
    } catch (...) {
        response =
            action == "session.open" &&
                    valid_conditional_cleanup_token(
                        session_open_cleanup_token)
                ? compensate_open_exception(
                      "INTERNAL_ERROR",
                      "session.open frontend dispatch failed")
                : make_error(
                      request,
                      action,
                      "INTERNAL_ERROR",
                      "unhandled exception",
                      false);
    }

    if (action == "session.open" &&
        valid_conditional_cleanup_token(
            session_open_cleanup_token)) {
        redact_sensitive_plaintext(
            response,
            session_open_cleanup_token);
    }

    const ActionSpec* response_spec =
        action.empty()
            ? nullptr
            : default_action_registry().find_spec(action);
    if (response_spec) {
        xdebug_core::RuntimeSchemaValidator response_validator;
        const xdebug_core::RuntimeSchemaValidationResult
            response_validation =
                action == "batch"
                    ? response_validator.validate_batch_response(
                          response,
                          response_spec->response_schema)
                    : response_validator.validate_response(
                          action,
                          response,
                          response_spec->response_schema);
        if (!response_validation.ok) {
            last_xout_.clear();
            xdebug_core::log_lifecycle_event(
                "public",
                begin_session,
                "response.schema_validation_failed",
                false,
                {{"action", action},
                 {"response",
                  xdebug_core::sanitize_for_log(response)},
                 {"contract_error",
                  response_validation.error}});
            if (action == "session.open" &&
                valid_conditional_cleanup_token(
                    session_open_cleanup_token)) {
                response = compensate_open_exception(
                    "INTERNAL_RESPONSE_SCHEMA_VIOLATION",
                    "session.open response violated its public response contract");
            } else {
                response = make_error(
                    request,
                    action,
                    response_validation.error);
            }
        }
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

} // namespace xdebug
