#pragma once

#include <string>

namespace xdebug_design {

std::string xdebug_design_home_dir();
std::string xdebug_design_sessions_dir();
std::string xdebug_design_session_dir(const std::string& session_id);
std::string xdebug_design_registry_path();
std::string xdebug_design_registry_lock_path();
std::string xdebug_design_lifecycle_locks_dir();
std::string xdebug_design_session_lifecycle_lock_path(
    const std::string& session_id);
std::string xdebug_design_session_json_path(const std::string& session_id);
std::string xdebug_design_session_state_path(const std::string& session_id);
std::string xdebug_design_session_activity_path(const std::string& session_id);
std::string xdebug_design_generation_marker_path(
    const std::string& session_id);
std::string xdebug_design_socket_path(const std::string& session_id);
std::string xdebug_design_endpoint_path(const std::string& session_id);
std::string xdebug_design_debug_log_path(const std::string& session_id);
std::string xdebug_design_npi_startup_log_path(const std::string& session_id);

bool xdebug_design_ensure_home();
bool xdebug_design_ensure_session_dir(const std::string& session_id);
bool xdebug_design_write_generation_marker(
    const std::string& session_id,
    const std::string& generation);
bool xdebug_design_read_generation_marker(
    const std::string& session_id,
    std::string& generation);
bool xdebug_design_generation_matches(
    const std::string& session_id,
    const std::string& generation);
bool xdebug_design_remove_session_generation(
    const std::string& session_id,
    const std::string& expected_generation);

} // namespace xdebug_design
