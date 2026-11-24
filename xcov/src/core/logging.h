#pragma once

#include <json.hpp>

#include <string>

namespace xcov {

/// True when observability logging is enabled.
bool logging_enabled();

std::string log_root();

/// Append one NDJSON lifecycle/action record. Never throws.
void log_event(const std::string& kind,
               const std::string& session_id,
               const std::string& action,
               bool ok,
               long elapsed_ms,
               const nlohmann::json& detail);

} // namespace xcov
