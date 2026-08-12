#include "client.h"

#include "../../design/protocol/protocol.h"
#include "core/schema/internal_request_contract.h"
#include "core/diagnostic_error.h"
#include "json_line_reader.h"
#include "session_lifecycle_lease.h"
#include "session_manager.h"
#include "session_transport.h"
#include "logging/action_log.h"
#include "session/transport_timeout.h"

#include <cerrno>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

namespace xdebug_engine {

static Json request_too_large_error(std::size_t received_bytes,
                                    const std::string& transport) {
    const std::string message =
        "JSON request exceeds the session transport limit";
    Json error = xdebug_core::DiagnosticErrorBuilder::transport(
                     "REQUEST_TOO_LARGE", message)
                     .recoverable(false)
                     .to_json();
    error["limit_name"] = "request_bytes";
    error["received_bytes"] = received_bytes;
    error["max_bytes"] = xdebug_core::kMaxSessionJsonBytes;
    error["transport"] = transport;
    error["phase"] = "transport_request";
    error["next_actions"] = Json::array({
        "Split the batch into smaller requests or use a bounded export action."
    });
    return error;
}

static xdebug_core::TransportIoStatus write_json_line(
    int fd, const Json& request,
    const xdebug_core::TransportDeadline& deadline) {
    std::string wire = request.dump() + "\n";
    if (wire.size() - 1 > xdebug_core::kMaxSessionJsonBytes)
        return xdebug_core::TransportIoStatus::TooLarge;
    return xdebug_core::write_all_deadline(
        fd, wire.c_str(), wire.size(), deadline);
}

static Json transport_timeout_log_context(
    Json context,
    const SessionInfo& session,
    const xdebug_core::TransportTimeoutOverrideMs& timeout_override_ms) {
    if (timeout_override_ms.present) {
        context["timeout_source"] = "public";
        context["timeout_ms"] = timeout_override_ms.value_ms;
    } else {
        context["timeout_source"] = "transport_native";
        if (is_file_transport(session)) {
            context["transport_timeout_ms"] =
                xdebug_core::file_transport_request_timeout_ms();
        }
    }
    return context;
}

bool send_request_capture(const std::string& session_id,
                          const Json& request,
                          Json& data,
                          std::string& status,
                          std::string& message,
                          Json& engine_error,
                          Json& timeout_containment) {
    engine_error = Json();  // null by default
    timeout_containment = Json();
    const std::string action =
        request.value("action", std::string());
    SessionManager manager;
    SessionInfo session;
    {
        // The lifecycle lease protects only the registry/generation snapshot.
        // Holding it across a vendor request would prevent a timed-out helper
        // from terminating the blocked engine process from outside.
        SessionLifecycleLease lease(session_id);
        if (!lease.locked()) {
            status = "lifecycle_lock_failed";
            message =
                "failed to acquire the session lifecycle lease";
            return false;
        }
        SessionRegistryResult lookup =
            manager.lookup_session(session_id, session);
        if (!lookup.ok()) {
            status =
                lookup.status == SessionRegistryStatus::NotFound
                    ? "session_not_found"
                    : "registry_invalid";
            message =
                lookup.status == SessionRegistryStatus::NotFound
                    ? "session not found"
                    : lookup.message;
            xdebug_core::log_transport_event(
                "engine", session_id, "send_request.session_not_found", false,
                {{"action", action}});
            return false;
        }
        if (session.lifecycle_state != "active") {
            status = session.lifecycle_state;
            message =
                session.lifecycle_state == "cleanup_failed"
                    ? "session cleanup failed and retained managed evidence"
                    : "session is not active";
            return false;
        }
        if (!xdebug_design::xdebug_design_generation_matches(
                session_id, session.generation)) {
            status = "registry_invalid";
            message =
                "session registry and generation marker do not match";
            return false;
        }
    }
    Json rpc = request;
    const xdebug_core::TransportTimeoutOverrideMs timeout_override_ms =
        xdebug_core::public_request_timeout_override_ms(request);
    if (is_file_transport(session)) {
        Json response;
        const SessionFileExchangeResult exchange =
            exchange_file_request_with_endpoint(
                session, rpc, response, timeout_override_ms);
        if (exchange.detail_status == "request_too_large") {
            status = "request_too_large";
            message = exchange.message.empty()
                          ? "JSON request exceeds the session transport limit"
                          : exchange.message;
            engine_error = request_too_large_error(
                rpc.dump().size(), session.transport);
            return false;
        }
        if (exchange.status !=
            SessionFileExchangeStatus::Completed) {
            const bool transport_timeout =
                exchange.status == SessionFileExchangeStatus::Timeout;
            status = transport_timeout
                         ? "transport_timeout"
                         : "transport_failed";
            message = transport_timeout
                          ? "file session transport exceeded its request deadline"
                          : (exchange.message.empty()
                                 ? "failed to exchange file transport request"
                                 : exchange.message);
            xdebug_core::log_transport_event("engine", session_id, "send_request.file_exchange_failed", false,
                                             transport_timeout_log_context(
                                                 {{"action", action},
                                                  {"status", status}, {"message", message},
                                                  {"transport", session.transport},
                                                  {"exchange_status", exchange.detail_status},
                                                  {"file_dir", session.file_dir},
                                                  {"pid", session.server_pid}},
                                                 session,
                                                 timeout_override_ms));
            if (transport_timeout) {
                const SessionTimeoutContainmentResult containment =
                    manager.terminate_on_timeout(
                        session_id, session.generation);
                timeout_containment = {
                    {"cancel_state", containment.cancel_state},
                    {"session_state", containment.session_state},
                    {"cleanup_succeeded", containment.cleanup_succeeded},
                    {"termination_confirmed",
                     containment.termination_confirmed}
                };
                xdebug_core::log_lifecycle_event(
                    "engine",
                    session_id,
                    "request_timeout.force_close",
                    containment.termination_confirmed,
                    {{"action", action},
                     {"transport", session.transport},
                     {"cancel_state", containment.cancel_state},
                     {"session_state", containment.session_state},
                     {"cleanup_succeeded", containment.cleanup_succeeded}});
            }
            return false;
        }
        if (!response.value("ok", false)) {
            status = response.value("status", std::string("server_error"));
            message = response.value("error", Json::object()).value("message", std::string("server request failed"));
            engine_error = response.value("error", Json::object());
            xdebug_core::log_transport_event("engine", session_id, "send_request.server_error", false,
                                             {{"action", action},
                                              {"status", status}, {"message", message},
                                              {"response", xdebug_core::sanitize_for_log(response)}});
            return false;
        }
        data = response.value("data", Json::object());
        if (response.contains("__xout") && response["__xout"].is_string())
            data["__xout"] = response["__xout"];
        if (!manager.touch_session(
                session_id, session.generation)) {
            status = "registry_invalid";
            message =
                "failed to persist activity for the expected session generation";
            return false;
        }
        status = "ok";
        message.clear();
        xdebug_core::log_transport_event("engine", session_id, "send_request.ok", true,
                                         {{"action", action},
                                          {"transport", session.transport}, {"file_dir", session.file_dir}});
        return true;
    }
    const xdebug_core::TransportDeadline socket_deadline(
        timeout_override_ms.present ? timeout_override_ms.value_ms : 0);
    int fd = connect_session_endpoint(session, socket_deadline);
    if (fd < 0) {
        const bool connect_timeout =
            timeout_override_ms.present && errno == ETIMEDOUT;
        status = connect_timeout ? "transport_timeout" : "connect_failed";
        message = connect_timeout
                      ? "session transport exceeded limits.timeout_ms while connecting"
                      : "server endpoint cannot be connected";
        xdebug_core::log_transport_event("engine", session_id, "send_request.connect_failed", false,
                                         transport_timeout_log_context(
                                             {{"action", action},
                                              {"status", status}, {"message", message},
                                              {"transport", session.transport},
                                              {"socket_path", session.socket_path},
                                              {"host", session.host},
                                              {"port", session.port},
                                              {"pid", session.server_pid}},
                                             session,
                                             timeout_override_ms));
        return false;
    }
    if (is_tcp_transport(session)) {
        rpc = xdebug_core::with_internal_transport_auth(
            rpc,
            session.auth_token);
    }
    Json response;
    errno = 0;
    const xdebug_core::TransportIoStatus write_status =
        write_json_line(fd, rpc, socket_deadline);
    JsonLineReadStatus read_status = JsonLineReadStatus::IoError;
    if (write_status == xdebug_core::TransportIoStatus::Ok) {
        read_status = read_bounded_json_line_status(
            fd, response, kMaxSessionJsonResponseBytes, socket_deadline);
    }
    const bool received =
        write_status == xdebug_core::TransportIoStatus::Ok &&
        read_status == JsonLineReadStatus::Ok;
    const int exchange_errno = errno;
    close(fd);
    if (!received) {
        const bool request_too_large =
            write_status == xdebug_core::TransportIoStatus::TooLarge;
        const bool response_too_large =
            read_status == JsonLineReadStatus::TooLarge;
        const bool public_timeout = timeout_override_ms.present &&
            (write_status == xdebug_core::TransportIoStatus::Timeout ||
             read_status == JsonLineReadStatus::Timeout ||
             exchange_errno == ETIMEDOUT);
        if (request_too_large) {
            status = "request_too_large";
            message = "JSON request exceeds the session transport limit";
            engine_error = request_too_large_error(
                rpc.dump().size(), session.transport);
            return false;
        }
        if (response_too_large) {
            status = "transport_failed";
            message = "JSON response exceeds the session transport limit";
            return false;
        }
        status = public_timeout
                     ? "transport_timeout"
                     : "transport_failed";
        message = public_timeout
                      ? "session transport exceeded limits.timeout_ms"
                      : "failed to exchange JSON request with session";
        xdebug_core::log_transport_event("engine", session_id, "send_request.exchange_failed", false,
                                         transport_timeout_log_context(
                                             {{"action", action},
                                              {"transport", session.transport},
                                              {"socket_path", session.socket_path},
                                              {"host", session.host},
                                              {"port", session.port}},
                                             session,
                                             timeout_override_ms));
        if (public_timeout) {
            const SessionTimeoutContainmentResult containment =
                manager.terminate_on_timeout(
                    session_id, session.generation);
            timeout_containment = {
                {"cancel_state", containment.cancel_state},
                {"session_state", containment.session_state},
                {"cleanup_succeeded", containment.cleanup_succeeded},
                {"termination_confirmed",
                 containment.termination_confirmed}
            };
            xdebug_core::log_lifecycle_event(
                "engine",
                session_id,
                "request_timeout.force_close",
                containment.termination_confirmed,
                {{"action", action},
                 {"transport", session.transport},
                 {"cancel_state", containment.cancel_state},
                 {"session_state", containment.session_state},
                 {"cleanup_succeeded", containment.cleanup_succeeded}});
        }
        return false;
    }
    if (!response.value("ok", false)) {
        status = response.value("status", std::string("server_error"));
        message = response.value("error", Json::object()).value("message", std::string("server request failed"));
        engine_error = response.value("error", Json::object());
        xdebug_core::log_transport_event("engine", session_id, "send_request.server_error", false,
                                         {{"action", action},
                                          {"status", status}, {"message", message},
                                          {"response", xdebug_core::sanitize_for_log(response)}});
        return false;
    }
    data = response.value("data", Json::object());
    if (response.contains("__xout") && response["__xout"].is_string())
        data["__xout"] = response["__xout"];
    if (!manager.touch_session(
            session_id, session.generation)) {
        status = "registry_invalid";
        message =
            "failed to persist activity for the expected session generation";
        return false;
    }
    xdebug_core::log_transport_event("engine", session_id, "send_request.ok", true,
                                     {{"action", action}});
    status = "ok";
    message.clear();
    return true;
}

bool session_ping(const std::string& session_id) {
    Json data;
    std::string status;
    std::string message;
    Json engine_error;
    Json timeout_containment;
    return send_request_capture(session_id,
                                xdebug_core::make_internal_control_request(
                                    "server.ping"),
                                data, status, message, engine_error,
                                timeout_containment) &&
           data.value("pong", false);
}

}  // namespace xdebug_engine
