#include "backend/engine_adapter.h"
#include "api/response.h"
#include "core/diagnostic_error.h"
#include "core/process/process_runner.h"
#include "core/schema/internal_request_contract.h"
#include "logging/action_log.h"
#include "runtime/work_dir.h"

#include <limits>
#include <string>

namespace xdebug {

namespace {

const int kDirectResourceTerminationGraceMs = 5000;
const int kSessionDiagnosticCompletionGraceMs = 250;

std::string request_session_id_for_log(const Json& request) {
    Json target = request.value("target", Json::object());
    auto get_str = [](const Json& obj, const char* key) -> std::string {
        auto it = obj.find(key);
        return it != obj.end() && it->is_string() ? it->get<std::string>() : std::string();
    };
    std::string sid = get_str(target, "session_id");
    return sid.empty() ? "adhoc" : sid;
}

} // namespace

EngineAdapter::EngineAdapter(const std::string& executable_dir)
    : executable_dir_(executable_dir) {}

std::string EngineAdapter::engine_path() const {
    return executable_dir_ + "/libexec/xdebug-engine";
}

std::string EngineAdapter::engine_workdir() const {
    return runtime_work_dir("engine");
}

bool EngineAdapter::invoke(const Json& public_request,
                           const Json& resolved_target,
                           const Json& observability,
                           Json& response,
                           Json& error) const {
    const std::string component = "engine";
    const std::string log_sid =
        request_session_id_for_log(resolved_target.empty()
            ? public_request
            : Json{{"target", resolved_target}});
    const std::string path = engine_path();
    const std::string workdir = engine_workdir();

    if (!ensure_runtime_work_dir(workdir)) {
        const std::string message =
            std::string("failed to create engine working directory: ") +
            workdir;
        error = xdebug_core::DiagnosticErrorBuilder::transport(
                    "ENGINE_WORKDIR_FAILED",
                    message)
                    .to_json();
        xdebug_core::log_lifecycle_event(component, log_sid, "engine.workdir_failed", false,
                                         {{"workdir", workdir}, {"engine_path", path}});
        return false;
    }

    Json internal_request;
    try {
        internal_request = xdebug_core::make_internal_request(
            public_request,
            xdebug_core::internal_routing_from_target(resolved_target),
            observability);
    } catch (const std::exception& e) {
        const std::string message =
            "failed to build strict internal request";
        error = xdebug_core::DiagnosticErrorBuilder::internal(
                    "INTERNAL_REQUEST_PROJECTION_FAILED",
                    message)
                    .to_json();
        xdebug_core::log_lifecycle_event(
            component,
            log_sid,
            "engine.request_projection_failed",
            false,
            {{"message", message},
             {"exception", e.what()},
             {"action", public_request.value("action", std::string())},
             {"observability", observability}});
        return false;
    }
    std::string stdin_text = internal_request.dump();
    stdin_text.push_back('\n');

    ProcessRequest process_req;
    process_req.executable = path;
    process_req.argv = {"ai", "query", "-"};
    process_req.stdin_text = stdin_text;
    process_req.working_dir = workdir;
    const int public_timeout_ms =
        public_request.value("limits", Json::object())
            .value("timeout_ms", 0);
    process_req.timeout_ms = public_timeout_ms;
    const bool direct_resource =
        !resolved_target.contains("session_id") &&
        (resolved_target.contains("daidir") ||
         resolved_target.contains("fsdb"));
    if (direct_resource) {
        process_req.termination_grace_ms =
            kDirectResourceTerminationGraceMs;
    } else if (resolved_target.contains("session_id") &&
               public_timeout_ms > 0 &&
               public_timeout_ms <=
                   std::numeric_limits<int>::max() -
                       kSessionDiagnosticCompletionGraceMs) {
        // The helper enforces the public deadline on its session socket.  Give
        // it a small, non-operational completion window to persist the timeout
        // event and serialize the canonical error before the parent kills it.
        process_req.timeout_ms =
            public_timeout_ms + kSessionDiagnosticCompletionGraceMs;
    }

    xdebug_core::log_lifecycle_event(
        component,
        log_sid,
        "engine.spawning",
        true,
        {{"engine_path", path},
         {"workdir", workdir},
         {"action", public_request.value("action", std::string())},
         {"termination_grace_ms", process_req.termination_grace_ms},
         {"observability", observability}});

    ProcessRunner runner;
    ProcessResult result = runner.run(process_req);

    if (result.timed_out) {
        const std::string message =
            "internal engine request exceeded limits.timeout_ms";
        error = xdebug_core::DiagnosticErrorBuilder::transport(
                    "ENGINE_TIMEOUT",
                    message)
                    .to_json();
        error["timeout_ms"] = public_timeout_ms;
        xdebug_core::log_lifecycle_event(component, log_sid, "engine.process_timeout", false,
                                         {{"timeout_ms", public_timeout_ms},
                                          {"process_timeout_ms", process_req.timeout_ms},
                                          {"message", message}, {"engine_path", path},
                                          {"stderr_bytes", result.stderr_text.size()}});
        return false;
    }

    if (result.exit_code != 0 && !result.stderr_text.empty()) {
        const std::string message =
            "internal engine process failed before returning a response";
        error = xdebug_core::DiagnosticErrorBuilder::internal(
                    "INTERNAL_ENGINE_FAILED",
                    message)
                    .to_json();
        error["exit_status"] = result.exit_code;
        xdebug_core::log_lifecycle_event(component, log_sid, "engine.process_failed", false,
                                         {{"exit_code", result.exit_code}, {"message", message},
                                          {"stderr_bytes", result.stderr_text.size()},
                                          {"engine_path", path}});
        return false;
    }

    try {
        response = normalize_engine_response(Json::parse(result.stdout_text));
    } catch (const std::exception& e) {
        const std::string message =
            "internal engine returned an invalid response (exit=" +
            std::to_string(result.exit_code) + ")";
        error = xdebug_core::DiagnosticErrorBuilder::internal(
                    "INTERNAL_ENGINE_RESPONSE_INVALID",
                    message)
                    .to_json();
        Json ctx = {{"message", message},
                    {"exception", e.what()},
                    {"raw_response", result.stdout_text},
                    {"action", public_request.value("action", std::string())},
                    {"exit_status", result.exit_code}};
        xdebug_core::log_lifecycle_event(component, log_sid, "engine.response_parse_failed", false, ctx);
        return false;
    }

    Json ctx = {{"action", public_request.value("action", std::string())},
                {"ok", response.value("ok", false)},
                {"exit_status", result.exit_code}};
    if (!observability.empty()) ctx["observability"] = observability;
    xdebug_core::log_lifecycle_event(component, log_sid, "engine.completed",
                                     response.value("ok", true), ctx);
    return true;
}

} // namespace xdebug
