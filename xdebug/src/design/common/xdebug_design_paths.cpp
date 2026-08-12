#include "xdebug_design_paths.h"

#include <cstdio>
#include <cerrno>
#include <dirent.h>
#include <fcntl.h>
#include <fstream>
#include <iterator>
#include <sys/stat.h>
#include <unistd.h>

#include "common/path_utils.h"

namespace xdebug_design {

namespace {

const xdebug_core::ToolConfig& tool_config() {
    static const xdebug_core::ToolConfig config =
        xdebug_core::make_tool_config("xdebug-engine", ".xdebug/engine", "xdebug-engine", "1.2");
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
    return errno == ENOENT;
}

bool valid_generation(const std::string& generation) {
    if (generation.size() != 64) return false;
    for (const char c : generation) {
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool remove_tree_if_exists(const std::string& path) {
    struct stat st;
    if (lstat(path.c_str(), &st) != 0) {
        return errno == ENOENT;
    }
    if (!S_ISDIR(st.st_mode) || S_ISLNK(st.st_mode)) {
        return remove_file_if_exists(path);
    }

    DIR* directory = opendir(path.c_str());
    if (!directory) return false;
    bool ok = true;
    errno = 0;
    while (dirent* entry = readdir(directory)) {
        const std::string name = entry->d_name;
        if (name == "." || name == "..") continue;
        if (!remove_tree_if_exists(path + "/" + name)) {
            ok = false;
        }
        errno = 0;
    }
    if (errno != 0) ok = false;
    if (closedir(directory) != 0) ok = false;
    if (ok && rmdir(path.c_str()) != 0 && errno != ENOENT) {
        ok = false;
    }
    return ok;
}

bool sync_directory(const std::string& path) {
    int fd = open(path.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return false;
    const bool ok = fsync(fd) == 0;
    const bool closed = close(fd) == 0;
    return ok && closed;
}

} // namespace

std::string xdebug_design_home_dir() {
    return xdebug_core::tool_home_dir(tool_config());
}

std::string xdebug_design_sessions_dir() {
    return xdebug_core::tool_sessions_dir(tool_config());
}

std::string session_dir_name(const std::string& session_id) {
    return xdebug_core::session_dir_name(session_id);
}

std::string xdebug_design_session_dir(const std::string& session_id) {
    return xdebug_core::tool_session_dir(tool_config(), session_id);
}

std::string xdebug_design_registry_path() {
    return xdebug_core::registry_path(tool_config());
}

std::string xdebug_design_registry_lock_path() {
    return xdebug_core::registry_lock_path(tool_config());
}

std::string xdebug_design_lifecycle_locks_dir() {
    return xdebug_design_home_dir() + "/lifecycle-locks";
}

std::string xdebug_design_session_lifecycle_lock_path(
    const std::string& session_id) {
    return xdebug_design_lifecycle_locks_dir() + "/" +
           xdebug_core::session_dir_name(session_id) + ".lock";
}

std::string xdebug_design_session_json_path(const std::string& session_id) {
    return xdebug_core::session_json_path(tool_config(), session_id);
}

std::string xdebug_design_session_state_path(const std::string& session_id) {
    return xdebug_design_session_dir(session_id) + "/state.json";
}

std::string xdebug_design_session_activity_path(const std::string& session_id) {
    return xdebug_design_session_dir(session_id) + "/activity";
}

std::string xdebug_design_generation_marker_path(
    const std::string& session_id) {
    return xdebug_design_session_dir(session_id) + "/generation";
}

std::string xdebug_design_socket_path(const std::string& session_id) {
    return xdebug_core::socket_path(tool_config(), session_id);
}

std::string xdebug_design_endpoint_path(const std::string& session_id) {
    return xdebug_core::endpoint_path(tool_config(), session_id);
}

std::string xdebug_design_debug_log_path(const std::string& session_id) {
    return xdebug_core::debug_log_path(tool_config(), session_id);
}

std::string xdebug_design_npi_startup_log_path(const std::string& session_id) {
    return xdebug_design_session_dir(session_id) + "/logs/npi_startup.log";
}

bool xdebug_design_ensure_home() {
    bool ok = ensure_dir(xdebug_home_dir()) &&
              ensure_dir(xdebug_design_home_dir()) &&
              ensure_dir(xdebug_design_sessions_dir()) &&
              ensure_dir(xdebug_design_lifecycle_locks_dir());
    return ok;
}

bool xdebug_design_ensure_session_dir(const std::string& session_id) {
    return xdebug_design_ensure_home() && ensure_dir(xdebug_design_session_dir(session_id));
}

bool xdebug_design_write_generation_marker(
    const std::string& session_id,
    const std::string& generation) {
    if (!valid_generation(generation) ||
        !xdebug_design_ensure_session_dir(session_id)) {
        return false;
    }
    const std::string path =
        xdebug_design_generation_marker_path(session_id);
    const std::string temp =
        path + ".tmp." + generation;
    int fd = open(
        temp.c_str(),
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
        0600);
    if (fd < 0) return false;
    const std::string payload = generation + "\n";
    size_t offset = 0;
    bool ok = true;
    while (offset < payload.size()) {
        const ssize_t count = write(
            fd, payload.data() + offset, payload.size() - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            ok = false;
            break;
        }
        offset += static_cast<size_t>(count);
    }
    if (ok) ok = fsync(fd) == 0;
    if (close(fd) != 0) ok = false;
    if (ok) ok = rename(temp.c_str(), path.c_str()) == 0;
    if (ok) ok = sync_directory(xdebug_design_session_dir(session_id));
    if (!ok) remove_file_if_exists(temp);
    return ok;
}

bool xdebug_design_read_generation_marker(
    const std::string& session_id,
    std::string& generation) {
    generation.clear();
    std::ifstream input(
        xdebug_design_generation_marker_path(session_id).c_str(),
        std::ios::in | std::ios::binary);
    if (!input) return false;
    const std::string payload(
        (std::istreambuf_iterator<char>(input)),
        std::istreambuf_iterator<char>());
    if (payload.size() != 65 || payload.back() != '\n') {
        return false;
    }
    for (size_t index = 0; index < 64; ++index) {
        const char c = payload[index];
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    generation = payload.substr(0, 64);
    return true;
}

bool xdebug_design_generation_matches(
    const std::string& session_id,
    const std::string& generation) {
    if (generation.empty()) return false;
    std::string actual;
    return xdebug_design_read_generation_marker(session_id, actual) &&
           actual == generation;
}

bool xdebug_design_remove_session_generation(
    const std::string& session_id,
    const std::string& expected_generation) {
    if (!xdebug_design_generation_matches(
            session_id, expected_generation)) {
        return false;
    }
    std::string dir = xdebug_design_session_dir(session_id);
    bool ok = true;
    ok = remove_file_if_exists(dir + "/session.json") && ok;
    ok = remove_file_if_exists(dir + "/socket") && ok;
    ok = remove_file_if_exists(xdebug_design_socket_path(session_id)) && ok;
    ok = remove_file_if_exists(dir + "/endpoint.json") && ok;
    ok = remove_tree_if_exists(dir + "/transport") && ok;
    if (ok) ok = sync_directory(dir);
    // Retain the marker as the last completed-generation guard.  A later
    // open atomically replaces it under the stable lifecycle lease.
    // Preserve debug.log and logs/ for post-failure diagnostics.
    return ok;
}

} // namespace xdebug_design
