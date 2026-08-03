#include "client.h"

#include "../../design/protocol/protocol.h"
#include "core/schema/internal_request_contract.h"
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

static bool write_json_line(int fd, const Json& request) {
    std::string wire = request.dump() + "\n";
    return write(fd, wire.c_str(), wire.size()) == static_cast<ssize_t>(wire.size());
}

static void set_public_socket_timeout_override(
    int fd,
    const xdebug_core::TransportTimeoutOverrideMs& timeout_override_ms) {
    if (!timeout_override_ms.present) return;
    const int timeout_ms = timeout_override_ms.value_ms;
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
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
                          Json& engine_error) {
    engine_error = Json();  // null by default
    const std::string action =
        request.value("action", std::string());
    SessionLifecycleLease lease(session_id);
    if (!lease.locked()) {
        status = "lifecycle_lock_failed";
        message =
            "failed to acquire the session lifecycle lease";
        return false;
    }
    SessionManager manager;
    SessionInfo session;
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
    Json rpc = request;
    const xdebug_core::TransportTimeoutOverrideMs timeout_override_ms =
        xdebug_core::public_request_timeout_override_ms(request);
    if (is_file_transport(session)) {
        Json response;
        if (!send_file_request_to_endpoint(
                session,
                rpc,
                response,
                timeout_override_ms)) {
            status = "transport_failed";
            message =
                "failed to exchange file transport request";
            xdebug_core::log_transport_event("engine", session_id, "send_request.file_exchange_failed", false,
                                             transport_timeout_log_context(
                                                 {{"action", action},
                                                  {"status", status}, {"message", message},
                                                  {"transport", session.transport},
                                                  {"file_dir", session.file_dir},
                                                  {"pid", session.server_pid}},
                                                 session,
                                                 timeout_override_ms));
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
    int fd = connect_session_endpoint(session);
    if (fd < 0) {
        status = "connect_failed";
        message =
            "server endpoint cannot be connected";
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
    set_public_socket_timeout_override(fd, timeout_override_ms);

    if (is_tcp_transport(session)) {
        rpc = xdebug_core::with_internal_transport_auth(
            rpc,
            session.auth_token);
    }
    Json response;
    errno = 0;
    const bool received =
        write_json_line(fd, rpc) && read_bounded_json_line(fd, response);
    const int exchange_errno = errno;
    close(fd);
    if (!received) {
        const bool public_timeout =
            timeout_override_ms.present &&
            (exchange_errno == EAGAIN || exchange_errno == EWOULDBLOCK);
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
    return send_request_capture(session_id,
                                xdebug_core::make_internal_control_request(
                                    "server.ping"),
                                data, status, message, engine_error) &&
           data.value("pong", false);
}

}  // namespace xdebug_engine
