#pragma once

#include <string>

namespace xdebug_waveform {

std::string xdebug_waveform_home_dir();
std::string xdebug_waveform_sessions_dir();
std::string xdebug_waveform_session_dir(int session_id);
std::string xdebug_waveform_session_dir(const std::string& session_id);
std::string xdebug_waveform_registry_path();
std::string xdebug_waveform_registry_lock_path();
std::string xdebug_waveform_session_json_path(int session_id);
std::string xdebug_waveform_session_json_path(const std::string& session_id);
std::string xdebug_waveform_socket_path(int session_id);
std::string xdebug_waveform_socket_path(const std::string& session_id);
std::string xdebug_waveform_endpoint_path(const std::string& session_id);
std::string xdebug_waveform_debug_log_path(int session_id);
std::string xdebug_waveform_debug_log_path(const std::string& session_id);
std::string xdebug_waveform_lists_path(int session_id);
std::string xdebug_waveform_lists_path(const std::string& session_id);
std::string xdebug_waveform_apb_path(int session_id);
std::string xdebug_waveform_apb_path(const std::string& session_id);
std::string xdebug_waveform_axi_path(int session_id);
std::string xdebug_waveform_axi_path(const std::string& session_id);
std::string xdebug_waveform_axi_exports_dir(const std::string& session_id);
std::string xdebug_waveform_list_exports_dir(const std::string& session_id);
std::string xdebug_waveform_events_path(int session_id);
std::string xdebug_waveform_events_path(const std::string& session_id);
std::string xdebug_waveform_streams_path(int session_id);
std::string xdebug_waveform_streams_path(const std::string& session_id);
std::string xdebug_waveform_stream_exports_dir(const std::string& session_id);
std::string xdebug_waveform_cursors_path(int session_id);
std::string xdebug_waveform_cursors_path(const std::string& session_id);

bool xdebug_waveform_ensure_home();
bool xdebug_waveform_ensure_session_dir(int session_id);
bool xdebug_waveform_ensure_session_dir(const std::string& session_id);
bool xdebug_waveform_remove_session_dir(int session_id);
bool xdebug_waveform_remove_session_dir(const std::string& session_id);

} // namespace xdebug_waveform
