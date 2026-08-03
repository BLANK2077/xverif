#include "xdebug_waveform_paths.h"

#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>

#include "common/path_utils.h"

namespace xdebug_waveform {

namespace {

const xdebug_core::ToolConfig& tool_config() {
    static const xdebug_core::ToolConfig config =
        xdebug_core::make_tool_config("xdebug-waveform", ".xdebug/waveform", "xdebug-waveform-engine", "1.0");
    return config;
}

std::string xdebug_home_dir() {
    return xdebug_core::home_dir() + "/.xdebug";
}

bool ensure_dir(const std::string& path) {
    if (mkdir(path.c_str(), 0700) == 0) return true;
    struct stat st;
    return stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

bool remove_file_if_exists(const std::string& path) {
    if (unlink(path.c_str()) == 0) return true;
    return access(path.c_str(), F_OK) != 0;
}

} // namespace

std::string xdebug_waveform_home_dir() {
    return xdebug_core::tool_home_dir(tool_config());
}

std::string xdebug_waveform_sessions_dir() {
    return xdebug_core::tool_sessions_dir(tool_config());
}

std::string xdebug_waveform_session_dir(int session_id) {
    return xdebug_waveform_session_dir(std::to_string(session_id));
}

std::string xdebug_waveform_session_dir(const std::string& session_id) {
    return xdebug_core::tool_session_dir(tool_config(), session_id);
}

std::string xdebug_waveform_registry_path() {
    return xdebug_core::registry_path(tool_config());
}

std::string xdebug_waveform_registry_lock_path() {
    return xdebug_core::registry_lock_path(tool_config());
}

std::string xdebug_waveform_session_json_path(int session_id) {
    return xdebug_waveform_session_json_path(std::to_string(session_id));
}

std::string xdebug_waveform_session_json_path(const std::string& session_id) {
    return xdebug_core::session_json_path(tool_config(), session_id);
}

std::string xdebug_waveform_socket_path(int session_id) {
    return xdebug_waveform_socket_path(std::to_string(session_id));
}

std::string xdebug_waveform_socket_path(const std::string& session_id) {
    return xdebug_core::socket_path(tool_config(), session_id);
}

std::string xdebug_waveform_endpoint_path(const std::string& session_id) {
    return xdebug_core::endpoint_path(tool_config(), session_id);
}

std::string xdebug_waveform_debug_log_path(int session_id) {
    return xdebug_waveform_debug_log_path(std::to_string(session_id));
}

std::string xdebug_waveform_debug_log_path(const std::string& session_id) {
    return xdebug_core::debug_log_path(tool_config(), session_id);
}

std::string xdebug_waveform_lists_path(int session_id) {
    return xdebug_waveform_lists_path(std::to_string(session_id));
}

std::string xdebug_waveform_lists_path(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/lists.json";
}

std::string xdebug_waveform_apb_path(int session_id) {
    return xdebug_waveform_apb_path(std::to_string(session_id));
}

std::string xdebug_waveform_apb_path(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/apb.json";
}

std::string xdebug_waveform_axi_path(int session_id) {
    return xdebug_waveform_axi_path(std::to_string(session_id));
}

std::string xdebug_waveform_axi_path(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/axi.json";
}

std::string xdebug_waveform_axi_exports_dir(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/axi_exports";
}

std::string xdebug_waveform_list_exports_dir(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/list_exports";
}

std::string xdebug_waveform_events_path(int session_id) {
    return xdebug_waveform_events_path(std::to_string(session_id));
}

std::string xdebug_waveform_events_path(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/events.json";
}

std::string xdebug_waveform_streams_path(int session_id) {
    return xdebug_waveform_streams_path(std::to_string(session_id));
}

std::string xdebug_waveform_streams_path(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/streams.json";
}

std::string xdebug_waveform_stream_exports_dir(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/stream_exports";
}

std::string xdebug_waveform_cursors_path(int session_id) {
    return xdebug_waveform_cursors_path(std::to_string(session_id));
}

std::string xdebug_waveform_cursors_path(const std::string& session_id) {
    return xdebug_waveform_session_dir(session_id) + "/cursors.json";
}

bool xdebug_waveform_ensure_home() {
    return ensure_dir(xdebug_home_dir()) &&
           ensure_dir(xdebug_waveform_home_dir()) &&
           ensure_dir(xdebug_waveform_sessions_dir());
}

bool xdebug_waveform_ensure_session_dir(int session_id) {
    return xdebug_waveform_ensure_session_dir(std::to_string(session_id));
}

bool xdebug_waveform_ensure_session_dir(const std::string& session_id) {
    return xdebug_waveform_ensure_home() && ensure_dir(xdebug_waveform_session_dir(session_id));
}

bool xdebug_waveform_remove_session_dir(int session_id) {
    return xdebug_waveform_remove_session_dir(std::to_string(session_id));
}

bool xdebug_waveform_remove_session_dir(const std::string& session_id) {
    std::string dir = xdebug_waveform_session_dir(session_id);
    remove_file_if_exists(dir + "/session.json");
    remove_file_if_exists(dir + "/socket");
    remove_file_if_exists(xdebug_waveform_socket_path(session_id));
    remove_file_if_exists(dir + "/lists.json");
    remove_file_if_exists(dir + "/apb.json");
    remove_file_if_exists(dir + "/axi.json");
    remove_file_if_exists(dir + "/events.json");
    remove_file_if_exists(dir + "/streams.json");
    remove_file_if_exists(dir + "/streams.json.lock");
    remove_file_if_exists(dir + "/cursors.json");
    remove_file_if_exists(dir + "/endpoint.json");
    // Preserve debug.log and logs/ for post-failure diagnostics.
    return true;
}

} // namespace xdebug_waveform
