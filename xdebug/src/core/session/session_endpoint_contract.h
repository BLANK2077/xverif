#pragma once

#include "json.hpp"
#include "session/session_types.h"

#include <string>

namespace xdebug_core {

using SessionEndpointJson = nlohmann::json;

// Endpoint documents are a strict, versioned, transport-discriminated
// contract.  Non-applicable transport fields are absent rather than emitted
// as empty placeholders.
bool session_endpoint_document_to_json(
    const SessionInfo& endpoint,
    SessionEndpointJson& value,
    std::string& error);

bool session_endpoint_document_from_json(
    const SessionEndpointJson& value,
    const std::string& expected_session_id,
    SessionInfo& endpoint,
    std::string& error);

}  // namespace xdebug_core
