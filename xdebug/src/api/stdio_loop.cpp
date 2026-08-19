#include "api/stdio_loop.h"

#include "api/dispatcher.h"
#include "api/request_parser.h"
#include "api/response.h"
#include "api/xout_renderer.h"
#include "logging/action_log.h"

#include <cstdlib>
#include <iostream>
#include <set>
#include <string>
#include <unistd.h>

namespace xdebug {

namespace {

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

bool write_jsonl(const Json& obj) {
    std::cout << obj.dump() << "\n" << std::flush;
    return std::cout.good();
}

std::string environment_fingerprint() {
    const char* verified = std::getenv("XVERIF_LSF_ENV_VERIFIED_FINGERPRINT");
    if (verified != nullptr && *verified != '\0') return std::string(verified);
    return std::string();
}

Json ready_envelope(int pid) {
    Json ready = {
        {"type", "ready"},
        {"protocol", "xdebug-stdio-loop"},
        {"version", 1},
        {"pid", pid},
    };
    const std::string fingerprint = environment_fingerprint();
    if (!fingerprint.empty()) ready["environment_fingerprint"] = fingerprint;
    return ready;
}

Json quit_envelope(const std::string& id) {
    return {
        {"id", id},
        {"ok", true},
        {"api_version", kApiVersion},
        {"action", "stdio.quit"},
        {"payload_format", "json"},
        {"json", {{"ok", true}, {"action", "stdio.quit"}}},
    };
}

Json loop_error(const std::string& id, const std::string& code, const std::string& message) {
    return {
        {"id", id},
        {"ok", false},
        {"error", {{"code", code}, {"message", message}}},
    };
}

bool has_string(const Json& object, const char* key) {
    return object.is_object() && object.contains(key) && object[key].is_string() &&
           !object[key].get<std::string>().empty();
}

struct LoopMetadata {
    std::string id;
    bool wants_json = false;
    Json observability = Json::object();
};

bool consume_loop_metadata(Json& request,
                           int seq,
                           bool default_json,
                           LoopMetadata& metadata,
                           std::string& error) {
    metadata.id = "req-" + std::to_string(seq);
    metadata.wants_json = default_json;

    if (request.contains("id")) {
        if (!has_string(request, "id")) {
            error = "stdio-loop id must be a non-empty string";
            return false;
        }
        metadata.id = request["id"].get<std::string>();
        request.erase("id");
    } else if (has_string(request, "request_id")) {
        metadata.id = request["request_id"].get<std::string>();
    }

    if (request.contains("payload_format")) {
        if (!request["payload_format"].is_string()) {
            error = "stdio-loop payload_format must be json or xout";
            return false;
        }
        const std::string format = request["payload_format"].get<std::string>();
        if (format == "json") {
            metadata.wants_json = true;
        } else if (format == "xout") {
            metadata.wants_json = false;
        } else {
            error = "stdio-loop payload_format must be json or xout";
            return false;
        }
        request.erase("payload_format");
    }

    metadata.observability["request_id"] =
        has_string(request, "request_id")
            ? request["request_id"].get<std::string>()
            : metadata.id;
    for (const char* field : {"trace_id", "span_id", "parent_span_id"}) {
        if (!request.contains(field)) continue;
        if (!has_string(request, field)) {
            error = std::string("stdio-loop ") + field + " must be a non-empty string";
            return false;
        }
        metadata.observability[field] = request[field];
        request.erase(field);
    }
    return true;
}

std::string log_session_id(const Json& req) {
    Json target = req.value("target", Json::object());
    Json args = req.value("args", Json::object());
    if (has_string(target, "session_id")) return target["session_id"].get<std::string>();
    if (has_string(args, "name")) return args["name"].get<std::string>();
    return "adhoc";
}

Json stdio_context(const Json& req,
                   const Json& observability,
                   const std::string& id,
                   int seq) {
    Json ctx = {
        {"request_id", id},
        {"seq", seq},
        {"request", xdebug_core::request_summary_for_log(req)}
    };
    std::string action = req.value("action", std::string());
    if (!action.empty()) ctx["action"] = action;
    for (const char* field : {"trace_id", "span_id", "parent_span_id"}) {
        if (observability.contains(field)) ctx[field] = observability[field];
    }
    return ctx;
}

void log_stdout_write_failed(const std::string& session_id, const Json& context) {
    xdebug_core::log_stdio_event(session_id, "loop.stdout_write_failed", false, context);
}

std::string render_transport_xout(const Json& response,
                                  const std::string& handler_xout) {
    if (response.value("ok", false) && !handler_xout.empty()) {
        std::string text = handler_xout;
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text.push_back('\n');
        return text;
    }
    return render_xout_response(response);
}

bool validate_quit_request(const Json& request, std::string& error) {
    static const std::set<std::string> allowed = {
        "api_version",
        "request_id",
        "action",
    };
    for (auto it = request.begin(); it != request.end(); ++it) {
        if (allowed.find(it.key()) == allowed.end()) {
            error = "stdio.quit does not accept field: " + it.key();
            return false;
        }
    }
    if (request.value("api_version", std::string()) != kApiVersion) {
        error = "stdio.quit requires api_version xdebug.v1";
        return false;
    }
    if (request.value("action", std::string()) != "stdio.quit") {
        error = "stdio.quit action is required";
        return false;
    }
    if (request.contains("request_id") && !has_string(request, "request_id")) {
        error = "stdio.quit request_id must be a non-empty string";
        return false;
    }
    return true;
}

Json make_envelope(const std::string& id, const Json& req, const Json& rsp,
                   bool wants_json, const std::string& handler_xout) {
    Json out;
    out["id"] = id;
    out["ok"] = rsp.value("ok", false);
    out["api_version"] = rsp.value("api_version", std::string(kApiVersion));
    out["action"] = rsp.value("action", req.value("action", std::string()));

    if (!rsp.value("ok", false)) {
        out["error"] = rsp.value("error", Json::object());
        out["json"] = rsp;
        if (!wants_json) {
            out["payload_format"] = "xout";
            out["xout"] = render_transport_xout(rsp, handler_xout);
        } else {
            out["payload_format"] = "json";
        }
        return out;
    }

    if (wants_json) {
        out["payload_format"] = "json";
        out["json"] = rsp;
    } else {
        out["payload_format"] = "xout";
        out["xout"] = render_transport_xout(rsp, handler_xout);
    }

    return out;
}

} // namespace

// ---------------------------------------------------------------------------
// main loop
// ---------------------------------------------------------------------------

int run_stdio_loop(const std::string& executable_dir, bool default_json) {
    Dispatcher dispatcher(executable_dir);

    // Announce the loop is ready
    Json ready = ready_envelope(static_cast<int>(getpid()));
    bool ready_written = write_jsonl(ready);
    xdebug_core::log_stdio_event("adhoc", "loop.ready", ready_written,
                                 {{"pid", static_cast<int>(getpid())}});
    if (!ready_written) {
        log_stdout_write_failed("adhoc", {{"phase", "loop.ready"}});
    }

    std::string line;
    int seq = 0;

    while (std::getline(std::cin, line)) {
        ++seq;
        if (line.empty()) continue;

        // Parse the JSON request
        Json req;
        std::string error;
        if (!parse_request_text(line, req, error)) {
            const std::string id = "req-" + std::to_string(seq);
            Json ctx = {{"request_id", id}, {"seq", seq}, {"line_size", line.size()}, {"error", error}};
            Json err = loop_error(id, "INVALID_JSON", error);
            bool written = write_jsonl(err);
            xdebug_core::log_stdio_event("adhoc", "loop.invalid_json", false, ctx);
            if (!written) log_stdout_write_failed("adhoc", ctx);
            continue;
        }

        LoopMetadata metadata;
        if (!consume_loop_metadata(req, seq, default_json, metadata, error)) {
            Json err = loop_error(metadata.id, "INVALID_REQUEST", error);
            bool written = write_jsonl(err);
            Json ctx = {
                {"request_id", metadata.id},
                {"seq", seq},
                {"error", error},
            };
            xdebug_core::log_stdio_event("adhoc", "loop.metadata_invalid", false, ctx);
            if (!written) log_stdout_write_failed("adhoc", ctx);
            continue;
        }
        const std::string& id = metadata.id;
        const bool wants_json = metadata.wants_json;
        const std::string action =
            has_string(req, "action")
                ? req["action"].get<std::string>()
                : std::string();
        const std::string sid = log_session_id(req);
        Json base_ctx = stdio_context(req, metadata.observability, id, seq);
        xdebug_core::log_stdio_event(sid, "request.begin", true, base_ctx);

        // Handle quit
        if (action == "stdio.quit") {
            if (!validate_quit_request(req, error)) {
                Json err = loop_error(id, "INVALID_REQUEST", error);
                bool written = write_jsonl(err);
                Json ctx = base_ctx;
                ctx["error"] = {{"code", "INVALID_REQUEST"}, {"message", error}};
                xdebug_core::log_stdio_event(sid, "loop.validate_failed", false, ctx);
                if (!written) log_stdout_write_failed(sid, ctx);
                continue;
            }
            Json rsp = quit_envelope(id);
            bool written = write_jsonl(rsp);
            xdebug_core::log_stdio_event(sid, "loop.quit", written, base_ctx);
            xdebug_core::log_stdio_event(sid, "request.end", written,
                                         {{"request_id", id}, {"seq", seq}, {"action", action},
                                          {"response", {{"ok", true}, {"action", action}}}});
            if (!written) log_stdout_write_failed(sid, base_ctx);
            return 0;
        }

        // Validate
        std::string validated_action;
        if (!validate_request(req, validated_action, error)) {
            const std::string code =
                req.value("api_version", std::string()) == kApiVersion
                    ? "INVALID_REQUEST"
                    : "UNSUPPORTED_API_VERSION";

            Json rsp = make_error(req, req.value("action", std::string()), code, error, false);
            Json envelope = make_envelope(id, req, rsp, wants_json, "");
            bool written = write_jsonl(envelope);
            Json ctx = base_ctx;
            ctx["error"] = {{"code", code}, {"message", error}};
            xdebug_core::log_stdio_event(sid, "loop.validate_failed", false, ctx);
            xdebug_core::log_stdio_event(sid, "request.end", false,
                                         {{"request_id", id}, {"seq", seq}, {"action", action},
                                          {"response", xdebug_core::response_summary_for_log(rsp)}});
            if (!written) log_stdout_write_failed(sid, ctx);
            continue;
        }

        // Dispatch
        Json rsp = dispatcher.dispatch(req, metadata.observability);
        Json envelope = make_envelope(
            id, req, rsp, wants_json, dispatcher.last_xout());
        bool written = write_jsonl(envelope);
        xdebug_core::log_stdio_event(log_session_id(req), "request.end",
                                     written && rsp.value("ok", false),
                                     {{"request_id", id}, {"seq", seq}, {"action", action},
                                      {"response", xdebug_core::response_summary_for_log(rsp)}});
        if (!written) log_stdout_write_failed(sid, base_ctx);
    }

    xdebug_core::log_stdio_event("adhoc", "loop.stdin_eof", true,
                                 {{"seq", seq}, {"pid", static_cast<int>(getpid())}});
    return 0;
}

} // namespace xdebug
