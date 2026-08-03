#include "logging/action_log.h"

#include "common/env_config.h"
#include "common/path_utils.h"

#include <chrono>
#include <cstdlib>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

namespace xdebug_core {

namespace {

const size_t kMaxString = 4096;
const size_t kMaxArray = 64;
const size_t kMaxObject = 128;
const int kMaxDepth = 8;
const size_t kMaxLine = 256 * 1024;

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

std::string now_iso8601() {
    using namespace std::chrono;
    system_clock::time_point now = system_clock::now();
    std::time_t t = system_clock::to_time_t(now);
    std::tm tm;
    localtime_r(&t, &tm);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S");
    auto ms = duration_cast<milliseconds>(now.time_since_epoch()).count() % 1000;
    oss << "." << std::setfill('0') << std::setw(3) << ms;
    char tz[8] = {};
    std::strftime(tz, sizeof(tz), "%z", &tm);
    oss << tz;
    return oss.str();
}

std::string event_id() {
    using namespace std::chrono;
    long long us = duration_cast<microseconds>(system_clock::now().time_since_epoch()).count();
    static unsigned long counter = 0;
    std::ostringstream oss;
    oss << std::hex << us << "-" << getpid() << "-" << counter++;
    return oss.str();
}

std::string xdebug_home() {
    std::string home = env_raw_string("HOME");
    return (home.empty() ? temporary_dir() : home) + "/.xdebug";
}

std::string dirname_of(const std::string& path) {
    size_t slash = path.rfind('/');
    if (slash == std::string::npos) return ".";
    if (slash == 0) return "/";
    return path.substr(0, slash);
}

std::string basename_of(const std::string& path) {
    size_t slash = path.rfind('/');
    return slash == std::string::npos ? path : path.substr(slash + 1);
}

std::string strip_ndjson_suffix(const std::string& name) {
    const std::string suffix = ".ndjson";
    if (name.size() > suffix.size() &&
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0) {
        return name.substr(0, name.size() - suffix.size());
    }
    return name;
}

std::string fnv1a_hex(const std::string& s) {
    unsigned long long hash = 1469598103934665603ULL;
    for (unsigned char c : s) {
        hash ^= c;
        hash *= 1099511628211ULL;
    }
    std::ostringstream oss;
    oss << std::hex << hash;
    return oss.str();
}

bool write_file_atomic_append(const std::string& path, const std::string& payload, int mode = 0600) {
    int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, mode);
    if (fd < 0) return false;
    flock(fd, LOCK_EX);
    const char* data = payload.data();
    size_t left = payload.size();
    bool ok = true;
    while (left > 0) {
        ssize_t n = write(fd, data, left);
        if (n <= 0) {
            ok = false;
            break;
        }
        data += n;
        left -= static_cast<size_t>(n);
    }
    flock(fd, LOCK_UN);
    close(fd);
    return ok;
}

void append_health_event(const std::string& log_path,
                         const std::string& code,
                         const std::string& message,
                         const Json& detail = Json::object()) {
    try {
        std::string dir = dirname_of(log_path);
        if (!ensure_dir_recursive(dir)) dir = xdebug_home() + "/logs";
        if (!ensure_dir_recursive(dir)) return;
        Json event;
        event["ts"] = now_iso8601();
        event["event_id"] = event_id();
        event["pid"] = static_cast<int>(getpid());
        event["layer"] = "log";
        event["component"] = "xdebug";
        event["phase"] = "log_health";
        event["ok"] = false;
        event["code"] = code;
        event["message"] = message;
        event["log_path"] = log_path;
        if (!detail.is_null() && !(detail.is_object() && detail.empty())) event["detail"] = detail;
        std::string line = event.dump();
        line.push_back('\n');
        write_file_atomic_append(dir + "/log_health.ndjson", line);
    } catch (...) {
    }
}

bool write_sidecar(const std::string& path, const Json& payload, Json& sidecars, const std::string& key) {
    try {
        std::string dir = dirname_of(path);
        if (!ensure_dir_recursive(dir)) return false;
        std::string text = payload.dump(2);
        std::ofstream out(path.c_str(), std::ios::trunc);
        if (!out) return false;
        out << text << "\n";
        sidecars[key] = {{"path", path}, {"bytes", text.size()}, {"hash", fnv1a_hex(text)}};
        return true;
    } catch (...) {
        return false;
    }
}

void spill_large_context_to_sidecars(const std::string& path, Json& event) {
    if (!event.contains("context") || !event["context"].is_object()) return;
    Json& ctx = event["context"];
    std::string payload_dir = dirname_of(path) + "/" + strip_ndjson_suffix(basename_of(path)) + "_payload";
    std::string id = event.value("event_id", event_id());
    Json sidecars = Json::object();
    for (const char* key : {"request_compact", "response_compact"}) {
        if (!ctx.contains(key)) continue;
        std::string sidecar_path = payload_dir + "/" + id + "." + key + ".json";
        if (write_sidecar(sidecar_path, ctx[key], sidecars, key)) {
            ctx[key] = {{"sidecar", sidecars[key]}};
        } else {
            append_health_event(path, "SIDECAR_WRITE_FAILED", "failed to write log payload sidecar",
                                {{"sidecar_path", sidecar_path}});
        }
    }
    if (sidecars.empty()) {
        std::string sidecar_path = payload_dir + "/" + id + ".context.json";
        if (write_sidecar(sidecar_path, ctx, sidecars, "context")) {
            ctx = {{"sidecar", sidecars["context"]}};
        } else {
            append_health_event(path, "SIDECAR_WRITE_FAILED", "failed to write log context sidecar",
                                {{"sidecar_path", sidecar_path}});
        }
    }
    if (!sidecars.empty()) {
        event["payload_sidecars"] = sidecars;
        event["log_truncated"] = true;
    }
}

void rotate_if_needed(const std::string& path, size_t incoming_bytes) {
    long long max_bytes = xdebug_log_max_bytes();
    if (max_bytes <= 0) return;
    long long max_files = xdebug_log_max_files();
    if (max_files <= 0) max_files = 1;
    struct stat st;
    if (stat(path.c_str(), &st) != 0) return;
    if (st.st_size + static_cast<long long>(incoming_bytes) <= max_bytes) return;
    for (long long i = max_files - 1; i >= 1; --i) {
        std::string from = path + "." + std::to_string(i);
        std::string to = path + "." + std::to_string(i + 1);
        rename(from.c_str(), to.c_str());
    }
    if (rename(path.c_str(), (path + ".1").c_str()) != 0) {
        append_health_event(path, "ROTATION_FAILED", "failed to rotate log file",
                            {{"errno", errno}, {"message", strerror(errno)}});
    }
}

bool heavy_key(const std::string& key) {
    return key == "rows" || key == "raw_rows" || key == "samples" ||
           key == "all_samples" || key == "trace" || key == "expanded_queries" ||
           key == "source_text" || key == "module_body" || key == "transactions" ||
           key == "beats" || key == "timeline" || key == "raw_samples" ||
           key == "all_changes" || key == "all_events";
}

bool path_key(const std::string& key) {
    return key == "fsdb" || key == "daidir" || key == "dbdir" ||
           key == "file_dir" || key == "socket_path" ||
           key == "path" || key == "log_path" ||
           key.find("_path") != std::string::npos ||
           key.find("_dir") != std::string::npos;
}

std::string path_log_mode() {
    std::string mode = xdebug_log_path_mode();
    if (!mode.empty()) return mode;
    if (xdebug_log_redact_enabled()) return "hash";
    return "full";
}

std::string redact_path_for_log(const std::string& value) {
    std::string mode = path_log_mode();
    if (mode == "basename") return basename_of(value);
    if (mode == "hash") return std::string("<path:") + fnv1a_hex(value) + ">";
    return value;
}

Json sanitize_impl(const Json& value, int depth, bool& truncated) {
    if (depth > kMaxDepth) {
        truncated = true;
        return "<truncated:depth>";
    }
    if (value.is_string()) {
        std::string s = value.get<std::string>();
        if (s.size() > kMaxString) {
            truncated = true;
            return s.substr(0, kMaxString) + "...<truncated:string>";
        }
        return s;
    }
    if (value.is_array()) {
        Json out = Json::array();
        size_t count = 0;
        for (const auto& item : value) {
            if (count >= kMaxArray) {
                truncated = true;
                break;
            }
            out.push_back(sanitize_impl(item, depth + 1, truncated));
            count++;
        }
        if (value.size() > kMaxArray) out.push_back("<truncated:array>");
        return out;
    }
    if (value.is_object()) {
        Json out = Json::object();
        size_t count = 0;
        for (auto it = value.begin(); it != value.end(); ++it) {
            if (count >= kMaxObject) {
                truncated = true;
                break;
            }
            if (heavy_key(it.key())) {
                truncated = true;
                out[it.key()] = "<omitted:large-field>";
            } else if (path_key(it.key()) && it.value().is_string()) {
                out[it.key()] = redact_path_for_log(it.value().get<std::string>());
            } else {
                out[it.key()] = sanitize_impl(it.value(), depth + 1, truncated);
            }
            count++;
        }
        if (value.size() > kMaxObject) out["<truncated>"] = "object";
        return out;
    }
    return value;
}

void append_event(const std::string& path, Json event) {
    try {
        size_t slash = path.rfind('/');
        if (slash != std::string::npos && !ensure_dir_recursive(path.substr(0, slash))) {
            append_health_event(path, "DIR_CREATE_FAILED", "failed to create log directory");
            return;
        }
        std::string line = event.dump();
        if (line.size() > kMaxLine) {
            spill_large_context_to_sidecars(path, event);
            line = event.dump();
        }
        if (line.size() > kMaxLine) {
            event["log_truncated"] = true;
            event["context"] = {{"message", "log event exceeded max line size and was truncated"}};
            line = event.dump();
            append_health_event(path, "EVENT_TRUNCATED", "log event exceeded max line size after sidecar spill",
                                {{"line_bytes", line.size()}});
        }
        line.push_back('\n');
        rotate_if_needed(path, line.size());
        if (!write_file_atomic_append(path, line)) {
            append_health_event(path, "WRITE_FAILED", "failed to append log event",
                                {{"errno", errno}, {"message", strerror(errno)}});
        }
    } catch (...) {
    }
}

bool string_field(const Json& obj, const char* key, std::string& out) {
    if (!obj.is_object() || !obj.contains(key)) return false;
    if (!obj[key].is_string()) return false;
    out = obj[key].get<std::string>();
    return !out.empty();
}

void copy_correlation_field(Json& event, const Json& context, const char* key) {
    std::string value;
    if (string_field(context, key, value) ||
        string_field(context.value("request", Json::object()), key, value) ||
        string_field(context.value("response", Json::object()), key, value)) {
        event[key] = value;
    }
}

Json base_event(const std::string& layer,
                const std::string& component,
                const std::string& session_id,
                const std::string& action,
                const std::string& phase,
                bool ok,
                const Json& context) {
    Json event;
    event["ts"] = now_iso8601();
    event["event_id"] = event_id();
    event["pid"] = static_cast<int>(getpid());
    event["layer"] = layer;
    event["component"] = component;
    event["session_id"] = session_id.empty() ? "adhoc" : session_id;
    event["action"] = action;
    event["phase"] = phase;
    event["ok"] = ok;
    copy_correlation_field(event, context, "trace_id");
    copy_correlation_field(event, context, "request_id");
    copy_correlation_field(event, context, "span_id");
    copy_correlation_field(event, context, "parent_span_id");
    copy_correlation_field(event, context, "alias");
    bool truncated = false;
    event["context"] = sanitize_impl(context, 0, truncated);
    if (truncated) event["log_truncated"] = true;
    return event;
}

bool action_prefix_match(const std::string& action, const std::string& prefix) {
    return action.compare(0, prefix.size(), prefix) == 0;
}

void copy_arg_if_present(Json& out, const Json& args, const char* key) {
    if (args.is_object() && args.contains(key)) out[key] = sanitize_for_log(args[key]);
}

Json allowlisted_args_for_log(const std::string& action, const Json& args) {
    Json out = Json::object();
    if (!args.is_object()) return out;
    if (action == "value.at") {
        for (const char* k : {"signal", "time", "radix", "format"}) copy_arg_if_present(out, args, k);
    } else if (action == "event.find") {
        for (const char* k : {"signal", "start", "end", "edge", "limit"}) copy_arg_if_present(out, args, k);
    } else if (action == "trace.active_driver") {
        for (const char* k : {"signal", "time", "max_depth", "max_nodes", "direction"}) copy_arg_if_present(out, args, k);
    } else if (action_prefix_match(action, "axi.")) {
        for (const char* k : {"interface", "start", "end", "id", "addr", "channel", "limit"}) copy_arg_if_present(out, args, k);
    } else if (action_prefix_match(action, "apb.")) {
        for (const char* k : {"interface", "start", "end", "addr", "kind", "limit"}) copy_arg_if_present(out, args, k);
    } else if (action_prefix_match(action, "scope.")) {
        for (const char* k : {"scope", "pattern", "depth", "limit"}) copy_arg_if_present(out, args, k);
    }
    return out;
}

} // namespace

std::string public_session_dir(const std::string& session_id) {
    return xdebug_home() + "/sessions/" +
           session_dir_name(session_id.empty() ? "adhoc" : session_id);
}

std::string public_action_log_path(const std::string& session_id) {
    return public_session_dir(session_id) + "/logs/actions.ndjson";
}

std::string public_stdio_log_path(const std::string& session_id) {
    return public_session_dir(session_id) + "/logs/stdio.ndjson";
}

std::string component_log_path(const std::string& component,
                               const std::string& session_id,
                               const std::string& log_name) {
    return xdebug_home() + "/" + component + "/sessions/" +
           session_dir_name(session_id.empty() ? "adhoc" : session_id) +
           "/logs/" + log_name + ".ndjson";
}

Json sanitize_for_log(const Json& value) {
    bool truncated = false;
    Json out = sanitize_impl(value, 0, truncated);
    if (truncated && out.is_object()) out["log_truncated"] = true;
    return out;
}

Json request_summary_for_log(const Json& request) {
    Json target = request.value("target", Json::object());
    Json args = request.value("args", Json::object());
    Json out;
    if (request.contains("trace_id")) out["trace_id"] = request["trace_id"];
    if (request.contains("request_id")) out["request_id"] = request["request_id"];
    else if (request.contains("id") && request["id"].is_string()) out["request_id"] = request["id"];
    if (request.contains("span_id")) out["span_id"] = request["span_id"];
    if (request.contains("parent_span_id")) out["parent_span_id"] = request["parent_span_id"];
    std::string action = request.value("action", std::string());
    out["action"] = action;
    if (target.is_object()) {
        Json t;
        for (const char* k : {"session_id", "name", "mode", "daidir", "dbdir", "fsdb", "transport", "host", "bind_host", "port"}) {
            if (target.contains(k)) t[k] = target[k];
        }
        out["target"] = sanitize_for_log(t);
    }
    if (args.is_object()) {
        Json keys = Json::array();
        for (auto it = args.begin(); it != args.end(); ++it) keys.push_back(it.key());
        out["arg_keys"] = keys;
        if (args.contains("name")) out["name"] = args["name"];
        if (args.contains("session_id")) out["arg_session_id"] = args["session_id"];
        Json allowlisted = allowlisted_args_for_log(action, args);
        if (!allowlisted.empty()) out["args"] = allowlisted;
    }
    if (request.contains("limits")) out["limits"] = sanitize_for_log(request["limits"]);
    if (request.contains("output")) out["output"] = sanitize_for_log(request["output"]);
    return out;
}

Json response_summary_for_log(const Json& response) {
    Json out;
    out["ok"] = response.value("ok", false);
    out["action"] = response.value("action", std::string());
    if (response.contains("trace_id")) out["trace_id"] = response["trace_id"];
    if (response.contains("request_id")) out["request_id"] = response["request_id"];
    if (response.contains("span_id")) out["span_id"] = response["span_id"];
    if (response.contains("parent_span_id")) out["parent_span_id"] = response["parent_span_id"];
    if (response.contains("session")) out["session"] = sanitize_for_log(response["session"]);
    if (response.contains("summary")) out["summary"] = sanitize_for_log(response["summary"]);
    if (response.contains("meta")) out["meta"] = sanitize_for_log(response["meta"]);
    if (response.contains("error") && !response["error"].is_null()) out["error"] = sanitize_for_log(response["error"]);
    return out;
}

void update_public_session_manifest(const std::string& session_id,
                                    const std::string& mode,
                                    const std::string& daidir,
                                    const std::string& fsdb) {
    try {
        std::string dir = public_session_dir(session_id);
        if (!ensure_dir_recursive(dir)) return;
        Json manifest;
        manifest["session_id"] = session_id.empty() ? "adhoc" : session_id;
        if (!mode.empty()) manifest["mode"] = mode;
        if (!daidir.empty()) manifest["daidir"] = daidir;
        if (!fsdb.empty()) manifest["fsdb"] = fsdb;
        manifest["last_log_at"] = now_iso8601();
        std::string path = dir + "/session.json";
        Json old;
        std::ifstream in(path.c_str());
        if (in) {
            try { in >> old; } catch (...) {}
        }
        if (old.is_object() && old.contains("created_at")) manifest["created_at"] = old["created_at"];
        else manifest["created_at"] = manifest["last_log_at"];
        manifest["log_path"] = public_action_log_path(session_id);
        Json logs = old.is_object() ? old.value("logs", Json::object()) : Json::object();
        if (!logs.is_object()) logs = Json::object();
        logs["public_actions"] = public_action_log_path(session_id);
        logs["public_stdio"] = public_stdio_log_path(session_id);
        manifest["logs"] = logs;
        std::ofstream out(path.c_str(), std::ios::trunc);
        if (out) out << manifest.dump(2) << "\n";
    } catch (...) {
    }
}

void log_action_event(const std::string& layer,
                      const std::string& component,
                      const std::string& session_id,
                      const std::string& action,
                      const std::string& phase,
                      bool ok,
                      long long elapsed_ms,
                      const Json& context) {
    Json event = base_event(layer, component, session_id, action, phase, ok, context);
    event["elapsed_ms"] = elapsed_ms;
    if (layer == "public") {
        append_event(public_action_log_path(session_id), event);
    } else {
        append_event(component_log_path(component, session_id, "actions"), event);
    }
}

void log_lifecycle_event(const std::string& component,
                         const std::string& session_id,
                         const std::string& phase,
                         bool ok,
                         const Json& context) {
    Json event = base_event("backend", component, session_id, "", phase, ok, context);
    append_event(component_log_path(component, session_id, "lifecycle"), event);
}

void log_transport_event(const std::string& component,
                         const std::string& session_id,
                         const std::string& phase,
                         bool ok,
                         const Json& context) {
    std::string action = context.value("action", std::string());
    Json event = base_event("backend", component, session_id, action, phase, ok, context);
    append_event(component_log_path(component, session_id, "transport"), event);
}

void log_stdio_event(const std::string& session_id,
                     const std::string& phase,
                     bool ok,
                     const Json& context) {
    std::string action = context.value("action", std::string());
    Json event = base_event("public", "xdebug", session_id, action, phase, ok, context);
    append_event(public_stdio_log_path(session_id), event);
}

} // namespace xdebug_core
