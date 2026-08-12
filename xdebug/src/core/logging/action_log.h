#pragma once

#include <string>

#include "json.hpp"

namespace xdebug_core {

using Json = nlohmann::json;

struct LoggingHealthSnapshot {
    bool degraded = false;
    unsigned long long failure_count = 0;
    std::string first_code;
    std::string first_operation;
};

std::string public_session_dir(const std::string& session_id);
std::string public_action_log_path(const std::string& session_id);
std::string public_stdio_log_path(const std::string& session_id);
std::string component_log_path(const std::string& component,
                               const std::string& session_id,
                               const std::string& log_name);

Json sanitize_for_log(const Json& value);
Json request_summary_for_log(const Json& request);
Json response_summary_for_log(const Json& response);
LoggingHealthSnapshot logging_health_snapshot();

bool update_public_session_manifest(const std::string& session_id,
                                    const std::string& mode,
                                    const std::string& daidir,
                                    const std::string& fsdb);

void log_action_event(const std::string& layer,
                      const std::string& component,
                      const std::string& session_id,
                      const std::string& action,
                      const std::string& phase,
                      bool ok,
                      long long elapsed_ms,
                      const Json& context = Json::object());

void log_lifecycle_event(const std::string& component,
                         const std::string& session_id,
                         const std::string& phase,
                         bool ok,
                         const Json& context = Json::object());

void log_transport_event(const std::string& component,
                         const std::string& session_id,
                         const std::string& phase,
                         bool ok,
                         const Json& context = Json::object());

void log_stdio_event(const std::string& session_id,
                     const std::string& phase,
                     bool ok,
                     const Json& context = Json::object());

} // namespace xdebug_core
