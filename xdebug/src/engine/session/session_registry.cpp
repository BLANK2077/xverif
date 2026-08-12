#include "session_registry.h"
#include "../../design/common/xdebug_design_paths.h"
#include "common/path_utils.h"
#include "session/session_registry_contract.h"
#include "json.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <dirent.h>
#include <fcntl.h>
#include <fstream>
#include <iterator>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace xdebug_engine {

using json = nlohmann::json;
using namespace xdebug_design;

namespace {

bool sync_directory(const std::string& path) {
    int fd = open(path.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return false;
    const bool synced = fsync(fd) == 0;
    const bool closed = close(fd) == 0;
    return synced && closed;
}

bool ensure_directory(const std::string& path) {
    if (mkdir(path.c_str(), 0700) == 0) return true;
    struct stat st;
    return errno == EEXIST && stat(path.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

bool write_atomic_file(const std::string& path, const std::string& data) {
    std::string pattern = path + ".tmp.XXXXXX";
    std::vector<char> writable(pattern.begin(), pattern.end());
    writable.push_back('\0');
    int fd = mkstemp(writable.data());
    if (fd < 0) return false;
    bool ok = fchmod(fd, 0600) == 0;
    size_t offset = 0;
    while (ok && offset < data.size()) {
        const ssize_t count = write(fd, data.data() + offset, data.size() - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            ok = false;
            break;
        }
        offset += static_cast<size_t>(count);
    }
    if (ok) ok = fsync(fd) == 0;
    if (close(fd) != 0) ok = false;
    if (ok) ok = rename(writable.data(), path.c_str()) == 0;
    if (!ok) unlink(writable.data());
    if (!ok) return false;
    const size_t slash = path.rfind('/');
    return sync_directory(slash == std::string::npos ? "." : path.substr(0, slash));
}

SessionRegistryResult parse_record_file(
    const std::string& path,
    SessionInfo& session) {
    std::ifstream input(path.c_str(), std::ios::in | std::ios::binary);
    if (!input) {
        return errno == ENOENT
            ? SessionRegistryResult(SessionRegistryStatus::NotFound,
                                    "session generation is not in registry")
            : SessionRegistryResult(SessionRegistryStatus::IoError,
                                    "cannot read per-session state");
    }
    try {
        const std::string text((std::istreambuf_iterator<char>(input)),
                               std::istreambuf_iterator<char>());
        json value = json::parse(text);
        std::string error;
        if (!xdebug_core::session_registry_record_from_json(value, session, error)) {
            return {SessionRegistryStatus::Invalid,
                    "per-session state is invalid: " + error};
        }
        return {};
    } catch (const std::exception&) {
        return {SessionRegistryStatus::Invalid,
                "per-session state is not strict JSON"};
    }
}

}  // namespace

SessionRegistry::SessionRegistry()
    : registry_path_(xdebug_design_registry_path()) {
    xdebug_design_ensure_home();
}

SessionRegistry::~SessionRegistry() = default;

SessionRegistryResult SessionRegistry::check_legacy_registry() {
    std::ifstream input(registry_path_.c_str(), std::ios::in | std::ios::binary);
    if (!input) {
        return access(registry_path_.c_str(), F_OK) != 0 && errno == ENOENT
            ? SessionRegistryResult()
            : SessionRegistryResult(SessionRegistryStatus::IoError,
                                    "cannot inspect legacy session registry");
    }
    try {
        const std::string text((std::istreambuf_iterator<char>(input)),
                               std::istreambuf_iterator<char>());
        json root = json::parse(text);
        std::vector<SessionInfo> legacy;
        std::string error;
        if (!xdebug_core::session_registry_document_from_json(root, legacy, error)) {
            return {SessionRegistryStatus::Invalid,
                    "legacy registry is invalid: " + error};
        }
        if (!legacy.empty()) {
            return {SessionRegistryStatus::Invalid,
                    "REGISTRY_MIGRATION_REQUIRED: close or gc every legacy session with the old binary before upgrading"};
        }
        const std::string retired = registry_path_ + ".v3.retired";
        if (rename(registry_path_.c_str(), retired.c_str()) != 0 && errno != ENOENT) {
            return {SessionRegistryStatus::IoError,
                    "cannot archive empty legacy session registry"};
        }
        const size_t slash = registry_path_.rfind('/');
        if (!sync_directory(slash == std::string::npos ? "." : registry_path_.substr(0, slash))) {
            return {SessionRegistryStatus::IoError,
                    "cannot sync legacy registry archive"};
        }
        return {};
    } catch (const std::exception&) {
        return {SessionRegistryStatus::Invalid,
                "legacy registry is not strict JSON"};
    }
}

SessionRegistryResult SessionRegistry::read_one(
    const std::string& session_id,
    SessionInfo& session) {
    SessionRegistryResult legacy = check_legacy_registry();
    if (!legacy.ok()) return legacy;
    SessionRegistryResult result = parse_record_file(
        xdebug_design_session_state_path(session_id), session);
    if (!result.ok()) return result;
    if (session.session_id != session_id) {
        return {SessionRegistryStatus::Invalid,
                "per-session state identity does not match its directory"};
    }
    struct stat activity;
    if (stat(xdebug_design_session_activity_path(session_id).c_str(), &activity) == 0 &&
        activity.st_mtime > session.last_active) {
        session.last_active = activity.st_mtime;
    }
    return {};
}

bool SessionRegistry::write_one(const SessionInfo& session) {
    if (!xdebug_design_ensure_session_dir(session.session_id)) return false;
    const std::string data =
        xdebug_core::session_registry_record_to_json(session).dump(2) + "\n";
    return write_atomic_file(
        xdebug_design_session_state_path(session.session_id), data);
}

SessionRegistryResult SessionRegistry::load_all(
    std::vector<SessionInfo>& sessions) {
    sessions.clear();
    SessionRegistryResult legacy = check_legacy_registry();
    if (!legacy.ok()) return legacy;
    DIR* directory = opendir(xdebug_design_sessions_dir().c_str());
    if (!directory) {
        return errno == ENOENT
            ? SessionRegistryResult()
            : SessionRegistryResult(SessionRegistryStatus::IoError,
                                    "cannot enumerate per-session registry");
    }
    errno = 0;
    while (dirent* entry = readdir(directory)) {
        const std::string name = entry->d_name;
        if (name == "." || name == "..") continue;
        const std::string state_path =
            xdebug_design_sessions_dir() + "/" + name + "/state.json";
        SessionInfo session;
        SessionRegistryResult parsed = parse_record_file(state_path, session);
        if (!parsed.ok()) {
            errno = 0;
            continue;  // Corruption is isolated to one session.
        }
        struct stat activity;
        const std::string activity_path =
            xdebug_design_sessions_dir() + "/" + name + "/activity";
        if (stat(activity_path.c_str(), &activity) == 0 &&
            activity.st_mtime > session.last_active) {
            session.last_active = activity.st_mtime;
        }
        sessions.push_back(session);
        errno = 0;
    }
    const int read_errno = errno;
    const bool closed = closedir(directory) == 0;
    if (read_errno != 0 || !closed) {
        sessions.clear();
        return {SessionRegistryStatus::IoError,
                "cannot complete per-session registry enumeration"};
    }
    std::sort(sessions.begin(), sessions.end(),
              [](const SessionInfo& lhs, const SessionInfo& rhs) {
                  return lhs.session_id < rhs.session_id;
              });
    return {};
}

SessionRegistryResult SessionRegistry::reserve_opening(const SessionInfo& session) {
    if (session.lifecycle_state != "opening") {
        return {SessionRegistryStatus::Invalid,
                "new session reservation must use lifecycle_state=opening"};
    }
    SessionInfo current;
    SessionRegistryResult existing = read_one(session.session_id, current);
    if (existing.ok()) {
        return {SessionRegistryStatus::Conflict,
                "session id already has a lifecycle generation"};
    }
    if (existing.status != SessionRegistryStatus::NotFound) return existing;
    return write_one(session)
        ? SessionRegistryResult()
        : SessionRegistryResult(SessionRegistryStatus::IoError,
                                "failed to persist opening session reservation");
}

SessionRegistryResult SessionRegistry::update_opening(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if (session.lifecycle_state != "opening" ||
        session.generation != expected_generation) {
        return {SessionRegistryStatus::Invalid,
                "opening update requires the expected generation in opening state"};
    }
    SessionInfo current;
    SessionRegistryResult found = read_one(session.session_id, current);
    if (!found.ok()) return found;
    if (current.generation != expected_generation)
        return {SessionRegistryStatus::GenerationMismatch,
                "opening update no longer matches expected generation"};
    if (current.lifecycle_state != "opening")
        return {SessionRegistryStatus::Conflict,
                "opening reservation is no longer opening"};
    return write_one(session)
        ? SessionRegistryResult()
        : SessionRegistryResult(SessionRegistryStatus::IoError,
                                "failed to persist opening session evidence");
}

SessionRegistryResult SessionRegistry::finalize_opening(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if (session.lifecycle_state != "active" ||
        session.generation != expected_generation) {
        return {SessionRegistryStatus::Invalid,
                "session finalization requires the expected generation in active state"};
    }
    SessionInfo current;
    SessionRegistryResult found = read_one(session.session_id, current);
    if (!found.ok()) return found;
    if (current.generation != expected_generation)
        return {SessionRegistryStatus::GenerationMismatch,
                "opening reservation no longer matches expected generation"};
    if (current.lifecycle_state != "opening")
        return {SessionRegistryStatus::Conflict,
                "opening reservation is no longer opening"};
    return write_one(session)
        ? SessionRegistryResult()
        : SessionRegistryResult(SessionRegistryStatus::IoError,
                                "failed to finalize opening session generation");
}

SessionRegistryResult SessionRegistry::mark_cleanup_failed(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if (session.lifecycle_state != "cleanup_failed") {
        return {SessionRegistryStatus::Invalid,
                "cleanup failure must use lifecycle_state=cleanup_failed"};
    }
    return mark_terminal_state(session, expected_generation);
}

SessionRegistryResult SessionRegistry::mark_terminal_state(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if ((session.lifecycle_state != "cleanup_failed" &&
         session.lifecycle_state != "terminated_on_timeout") ||
        session.generation != expected_generation) {
        return {SessionRegistryStatus::Invalid,
                "terminal session state must preserve the expected generation"};
    }
    SessionInfo current;
    SessionRegistryResult found = read_one(session.session_id, current);
    if (!found.ok()) return found;
    if (current.generation != expected_generation)
        return {SessionRegistryStatus::GenerationMismatch,
                "terminal state generation no longer matches registry"};
    return write_one(session)
        ? SessionRegistryResult()
        : SessionRegistryResult(SessionRegistryStatus::IoError,
                                "failed to preserve terminal session generation");
}

SessionRegistryResult SessionRegistry::touch_if_generation(
    const std::string& session_id,
    const std::string& expected_generation,
    time_t last_active) {
    SessionInfo current;
    SessionRegistryResult found = read_one(session_id, current);
    if (!found.ok()) return found;
    if (current.generation != expected_generation)
        return {SessionRegistryStatus::GenerationMismatch,
                "touch generation no longer matches registry"};
    if (current.last_active >= last_active) return {};
    const std::string path = xdebug_design_session_activity_path(session_id);
    int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_CLOEXEC, 0600);
    if (fd < 0) return {SessionRegistryStatus::IoError,
                        "failed to open session activity marker"};
    const struct timespec times[2] = {{last_active, 0}, {last_active, 0}};
    const bool ok = futimens(fd, times) == 0 && close(fd) == 0;
    return ok ? SessionRegistryResult()
              : SessionRegistryResult(SessionRegistryStatus::IoError,
                                      "failed to update session activity marker");
}

SessionRegistryResult SessionRegistry::remove_if_generation(
    const std::string& session_id,
    const std::string& expected_generation) {
    SessionInfo current;
    SessionRegistryResult found = read_one(session_id, current);
    if (!found.ok()) return found;
    if (current.generation != expected_generation)
        return {SessionRegistryStatus::GenerationMismatch,
                "remove generation no longer matches registry"};
    const std::string history = xdebug_design_session_dir(session_id) + "/history";
    if (!ensure_directory(history))
        return {SessionRegistryStatus::IoError,
                "failed to prepare session history"};
    json closed = xdebug_core::session_registry_record_to_json(current);
    closed["closed_at"] = static_cast<long long>(time(nullptr));
    closed["final_state"] = "closed";
    if (!write_atomic_file(history + "/" + expected_generation + ".json",
                           closed.dump(2) + "\n")) {
        return {SessionRegistryStatus::IoError,
                "failed to archive closed session generation"};
    }
    if (unlink(xdebug_design_session_state_path(session_id).c_str()) != 0 &&
        errno != ENOENT) {
        return {SessionRegistryStatus::IoError,
                "failed to retire closed session state"};
    }
    unlink(xdebug_design_session_activity_path(session_id).c_str());
    return sync_directory(xdebug_design_session_dir(session_id))
        ? SessionRegistryResult()
        : SessionRegistryResult(SessionRegistryStatus::IoError,
                                "failed to sync retired session state");
}

SessionRegistryResult SessionRegistry::get(
    const std::string& session_id,
    SessionInfo& session) {
    return read_one(session_id, session);
}

SessionRegistryResult SessionRegistry::get_latest(SessionInfo& session) {
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all(sessions);
    if (!loaded.ok()) return loaded;
    if (sessions.empty())
        return {SessionRegistryStatus::NotFound,
                "per-session registry is empty"};
    session = *std::max_element(
        sessions.begin(), sessions.end(),
        [](const SessionInfo& lhs, const SessionInfo& rhs) {
            return lhs.created_at < rhs.created_at;
        });
    return {};
}

bool SessionRegistry::is_valid_session_name(const std::string& name) {
    return xdebug_core::is_valid_session_name(name);
}

}  // namespace xdebug_engine
