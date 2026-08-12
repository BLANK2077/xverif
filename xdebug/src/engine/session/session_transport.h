#pragma once

#include "session_registry.h"
#include "json.hpp"
#include "session/transport_common.h"
#include "session/transport_timeout.h"

#include <string>

namespace xdebug_engine {

std::string current_host_name();
bool generate_auth_token(std::string& token, std::string& error);
bool is_tcp_transport(const SessionInfo& session);
bool is_file_transport(const SessionInfo& session);
bool is_local_session_host(const SessionInfo& session);

enum class SessionFileExchangeStatus {
    Completed,
    Timeout,
    Failed
};

struct SessionFileExchangeResult {
    SessionFileExchangeStatus status =
        SessionFileExchangeStatus::Failed;
    std::string detail_status;
    std::string message;
};

bool write_endpoint_file(const SessionInfo& session);
bool read_endpoint_file(const std::string& session_id, SessionInfo& endpoint);

int connect_session_endpoint(
    const SessionInfo& session,
    const xdebug_core::TransportDeadline& deadline =
        xdebug_core::TransportDeadline());
bool send_file_request_to_endpoint(const SessionInfo& session,
                                   const nlohmann::json& request,
                                   nlohmann::json& response,
                                   const xdebug_core::TransportTimeoutOverrideMs&
                                       timeout_override_ms =
                                           xdebug_core::
                                               TransportTimeoutOverrideMs());
SessionFileExchangeResult exchange_file_request_with_endpoint(
    const SessionInfo& session,
    const nlohmann::json& request,
    nlohmann::json& response,
    const xdebug_core::TransportTimeoutOverrideMs& timeout_override_ms =
        xdebug_core::TransportTimeoutOverrideMs());
bool ping_session_endpoint(const SessionInfo& session);
bool protocol_version_matches_endpoint(const SessionInfo& session);
bool send_quit_to_endpoint(const SessionInfo& session);

} // namespace xdebug_engine
