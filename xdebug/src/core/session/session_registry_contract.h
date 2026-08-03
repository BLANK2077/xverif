#pragma once

#include "session/session_types.h"
#include "json.hpp"

#include <string>
#include <vector>

namespace xdebug_core {

using SessionRegistryJson = nlohmann::json;

SessionRegistryJson session_registry_record_to_json(
    const SessionInfo& session);

bool session_registry_record_from_json(
    const SessionRegistryJson& value,
    SessionInfo& session,
    std::string& error);

bool session_registry_document_from_json(
    const SessionRegistryJson& value,
    std::vector<SessionInfo>& sessions,
    std::string& error);

bool session_registry_document_to_json(
    const std::vector<SessionInfo>& sessions,
    SessionRegistryJson& value,
    std::string& error);

} // namespace xdebug_core
