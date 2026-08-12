#include "session_transport.h"
#include "../../design/common/xdebug_design_paths.h"
#include "json.hpp"
#include "../../design/protocol/protocol.h"
#include "core/schema/internal_request_contract.h"
#include "session/session_endpoint_contract.h"
#include "transport/file_exchange.h"
#include "session/transport_timeout.h"
#include "session/transport_common.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <unistd.h>

namespace xdebug_engine {

using Json = nlohmann::json;
using namespace xdebug_design;

// --- Re-exported shared utilities (called by session_manager, server, etc.) ---

std::string current_host_name() {
    return xdebug_core::current_host_name();
}

bool generate_auth_token(std::string& token, std::string& error) {
    return xdebug_core::generate_auth_token(token, error);
}

// --- Transport type helpers (thin wrappers around shared utils) ---

bool is_tcp_transport(const SessionInfo& session) {
    return xdebug_core::is_tcp_transport(session.transport);
}

bool is_file_transport(const SessionInfo& session) {
    return xdebug_core::is_file_transport(session.transport);
}

bool is_local_session_host(const SessionInfo& session) {
    return xdebug_core::is_local_session_host(session.server_host);
}

// --- Endpoint file I/O (component-specific paths) ---

bool write_endpoint_file(const SessionInfo& session) {
    Json root;
    std::string error;
    if (!xdebug_core::session_endpoint_document_to_json(
            session, root, error)) {
        return false;
    }
    if (!xdebug_design_ensure_session_dir(session.session_id)) return false;
    return xdebug_core::atomic_write_json_file(xdebug_design_endpoint_path(session.session_id), root);
}

bool read_endpoint_file(const std::string& session_id, SessionInfo& endpoint) {
    FILE* fp = fopen(xdebug_design_endpoint_path(session_id).c_str(), "r");
    if (!fp) return false;
    std::string text;
    char buf[1024];
    while (fgets(buf, sizeof(buf), fp)) text += buf;
    fclose(fp);
    try {
        Json root = Json::parse(text);
        std::string error;
        return xdebug_core::session_endpoint_document_from_json(
            root, session_id, endpoint, error);
    } catch (...) {
        return false;
    }
}

// --- Connection management (uses shared socket helpers) ---

int connect_session_endpoint(const SessionInfo& session) {
    if (is_file_transport(session)) return -1;
    if (is_tcp_transport(session)) {
        return xdebug_core::connect_tcp(session.host, session.port);
    }
    if (session.transport != "uds" || session.socket_path.empty()) return -1;
    return xdebug_core::connect_uds(session.socket_path);
}

// --- File transport request ---

bool send_file_request_to_endpoint(
    const SessionInfo& session,
    const Json& request,
    Json& response,
    const xdebug_core::TransportTimeoutOverrideMs&
        timeout_override_ms) {
    if (!is_file_transport(session) || session.file_dir.empty()) return false;
    const int effective_timeout_ms =
        xdebug_core::effective_file_transport_request_timeout_ms(
            timeout_override_ms);
    xdebug_core::FileExchangeResult result =
        xdebug_core::file_exchange_send_request(
            session.file_dir, request, effective_timeout_ms);
    if (!(result.status == "ok" || result.status == "action_error" || result.status == "server_error")) return false;
    if (!result.response.is_object()) return false;
    response = result.response;
    return true;
}

// --- Simple request/response ---

static bool request_simple(const SessionInfo& session, const std::string& action, Json& data) {
    if (is_file_transport(session)) {
        Json request =
            xdebug_core::make_internal_control_request(action);
        Json response;
        if (!send_file_request_to_endpoint(
                session,
                request,
                response,
                xdebug_core::TransportTimeoutOverrideMs(
                    xdebug_core::file_transport_ping_timeout_ms())))
            return false;
        bool ok = response.value("ok", false);
        data = response.value("data", Json::object());
        return ok;
    }
    int fd = connect_session_endpoint(session);
    if (fd < 0) return false;
    Json request =
        xdebug_core::make_internal_control_request(action);
    if (is_tcp_transport(session)) {
        request = xdebug_core::with_internal_transport_auth(
            request,
            session.auth_token);
    }
    std::string msg = request.dump() + "\n";
    bool ok = write(fd, msg.c_str(), msg.size()) == static_cast<ssize_t>(msg.size());
    std::string line;
    if (ok) {
        ok = xdebug_core::read_line_timeout(fd, line);
        if (ok) {
            try {
                Json response = Json::parse(line);
                ok = response.value("ok", false);
                data = response.value("data", Json::object());
            } catch (...) {
                ok = false;
            }
        }
    }
    close(fd);
    return ok;
}

bool ping_session_endpoint(const SessionInfo& session) {
    Json data;
    return request_simple(session, "server.ping", data) && data.value("pong", false);
}

bool protocol_version_matches_endpoint(const SessionInfo& session) {
    Json data;
    return request_simple(session, "server.version", data) &&
           data.value("api_version", std::string()) == INTERNAL_API_VERSION;
}

bool send_quit_to_endpoint(const SessionInfo& session) {
    Json data;
    return request_simple(session, "server.quit", data);
}

} // namespace xdebug_engine
