#include "session_registry.h"
#include "../../design/common/xdebug_design_paths.h"
#include "common/path_utils.h"
#include "session/session_registry_contract.h"
#include "json.hpp"

#include <fcntl.h>
#include <unistd.h>
#include <cstdio>
#include <cerrno>
#include <cstdlib>
#include <signal.h>
#include <sys/file.h>
#include <sys/stat.h>

namespace xdebug_engine {

using json = nlohmann::json;
using namespace xdebug_design;

namespace {

const SessionInfo* find_generation(
    const std::vector<SessionInfo>& sessions,
    const std::string& session_id,
    const std::string& generation) {
    for (const auto& session : sessions) {
        if (session.session_id == session_id &&
            session.generation == generation) {
            return &session;
        }
    }
    return nullptr;
}

bool same_registry_record(
    const SessionInfo& lhs,
    const SessionInfo& rhs) {
    return xdebug_core::session_registry_record_to_json(lhs) ==
           xdebug_core::session_registry_record_to_json(rhs);
}

} // namespace

SessionRegistry::SessionRegistry() {
    xdebug_design_ensure_home();
    registry_path_ = xdebug_design_registry_path();
}

SessionRegistry::~SessionRegistry() {
}

int SessionRegistry::acquire_registry_lock() {
    int fd = open(xdebug_design_registry_lock_path().c_str(),
                  O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    if (flock(fd, LOCK_EX) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

bool SessionRegistry::release_registry_lock(int fd) {
    const bool unlocked = flock(fd, LOCK_UN) == 0;
    const bool closed = close(fd) == 0;
    return unlocked && closed;
}

static bool write_atomic_file(const std::string& path,
                              const std::string& data) {
    std::string pattern = path + ".tmp.XXXXXX";
    std::vector<char> writable(pattern.begin(), pattern.end());
    writable.push_back('\0');
    int fd = mkstemp(writable.data());
    if (fd < 0) return false;
    bool ok = fchmod(fd, 0600) == 0;
    size_t offset = 0;
    while (ok && offset < data.size()) {
        ssize_t count = write(fd, data.data() + offset, data.size() - offset);
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
    const std::string directory =
        slash == std::string::npos ? "." : path.substr(0, slash);
    int dir_fd = open(directory.c_str(), O_RDONLY | O_DIRECTORY);
    if (dir_fd < 0) return false;
    const bool synced = fsync(dir_fd) == 0;
    const bool closed = close(dir_fd) == 0;
    return synced && closed;
}

SessionRegistryResult SessionRegistry::load_all_unlocked(
    std::vector<SessionInfo>& sessions) {
    sessions.clear();
    if (!xdebug_design_ensure_home()) {
        return {
            SessionRegistryStatus::IoError,
            "cannot prepare canonical session registry directory"};
    }

    int fd = open(registry_path_.c_str(), O_RDONLY);
    if (fd < 0) {
        return errno == ENOENT
            ? SessionRegistryResult()
            : SessionRegistryResult(
                  SessionRegistryStatus::IoError,
                  "cannot open canonical session registry");
    }

    std::string text;
    char buf[4096];
    bool read_ok = true;
    while (true) {
        const ssize_t count = read(fd, buf, sizeof(buf));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) {
            read_ok = false;
            break;
        }
        if (count == 0) break;
        text.append(buf, static_cast<size_t>(count));
    }
    if (close(fd) != 0) read_ok = false;
    if (!read_ok) {
        return {
            SessionRegistryStatus::IoError,
            "cannot read canonical session registry"};
    }

    if (text.empty()) {
        return {
            SessionRegistryStatus::Invalid,
            "canonical session registry is empty"};
    }
    try {
        json root = json::parse(text);
        std::string contract_error;
        if (!xdebug_core::session_registry_document_from_json(
                root, sessions, contract_error)) {
            sessions.clear();
            return {
                SessionRegistryStatus::Invalid,
                "canonical session registry is invalid: " +
                    contract_error};
        }
        return {};
    } catch (...) {
        sessions.clear();
        return {
            SessionRegistryStatus::Invalid,
            "canonical session registry is not strict JSON"};
    }
}

SessionRegistryResult SessionRegistry::load_all(
    std::vector<SessionInfo>& sessions) {
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    SessionRegistryResult result = load_all_unlocked(sessions);
    if (!release_registry_lock(lock_fd) && result.ok()) {
        return {
            SessionRegistryStatus::IoError,
            "cannot release canonical session registry lock"};
    }
    return result;
}

bool SessionRegistry::save_all_unlocked(
    const std::vector<SessionInfo>& sessions) {
    if (!xdebug_design_ensure_home()) return false;
    json root;
    std::string contract_error;
    if (!xdebug_core::session_registry_document_to_json(
            sessions, root, contract_error)) return false;
    std::string data = root.dump(2) + "\n";
    return write_atomic_file(registry_path_, data);
}

SessionRegistryResult SessionRegistry::reserve_opening(
    const SessionInfo& session) {
    if (session.lifecycle_state != "opening") {
        return {
            SessionRegistryStatus::Invalid,
            "new session reservation must use lifecycle_state=opening"};
    }
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all_unlocked(sessions);
    if (!loaded.ok()) {
        release_registry_lock(lock_fd);
        return loaded;
    }
    for (const auto& s : sessions) {
        if (s.session_id == session.session_id) {
            release_registry_lock(lock_fd);
            return {
                SessionRegistryStatus::Conflict,
                "session id already has a lifecycle generation"};
        }
    }
    sessions.push_back(session);
    bool saved = save_all_unlocked(sessions);
    if (!saved) {
        std::vector<SessionInfo> current;
        SessionRegistryResult confirmed =
            load_all_unlocked(current);
        const SessionInfo* persisted =
            confirmed.ok()
                ? find_generation(
                      current,
                      session.session_id,
                      session.generation)
                : nullptr;
        saved =
            persisted != nullptr &&
            same_registry_record(*persisted, session);
    }
    release_registry_lock(lock_fd);
    return saved
        ? SessionRegistryResult()
        : SessionRegistryResult(
              SessionRegistryStatus::IoError,
              "failed to persist opening session reservation");
}

SessionRegistryResult SessionRegistry::finalize_opening(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if (session.lifecycle_state != "active" ||
        session.generation != expected_generation) {
        return {
            SessionRegistryStatus::Invalid,
            "session finalization requires the expected generation in active state"};
    }
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all_unlocked(sessions);
    if (!loaded.ok()) {
        release_registry_lock(lock_fd);
        return loaded;
    }
    SessionRegistryStatus mismatch =
        SessionRegistryStatus::NotFound;
    bool replaced = false;
    for (auto& s : sessions) {
        if (s.session_id != session.session_id) continue;
        if (s.generation != expected_generation) {
            mismatch = SessionRegistryStatus::GenerationMismatch;
            break;
        }
        if (s.lifecycle_state != "opening") {
            mismatch = SessionRegistryStatus::Conflict;
            break;
        }
        s = session;
        replaced = true;
        break;
    }
    if (!replaced) {
        release_registry_lock(lock_fd);
        return {
            mismatch,
            "opening reservation no longer matches expected generation"};
    }
    bool saved = save_all_unlocked(sessions);
    if (!saved) {
        std::vector<SessionInfo> current;
        const SessionRegistryResult confirmed =
            load_all_unlocked(current);
        const SessionInfo* persisted =
            confirmed.ok()
                ? find_generation(
                      current,
                      session.session_id,
                      expected_generation)
                : nullptr;
        saved =
            persisted != nullptr &&
            same_registry_record(*persisted, session);
    }
    release_registry_lock(lock_fd);
    return saved
        ? SessionRegistryResult()
        : SessionRegistryResult(
              SessionRegistryStatus::IoError,
              "failed to finalize opening session generation");
}

SessionRegistryResult SessionRegistry::update_opening(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if (session.lifecycle_state != "opening" ||
        session.generation != expected_generation) {
        return {
            SessionRegistryStatus::Invalid,
            "opening update requires the expected generation in opening state"};
    }
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all_unlocked(sessions);
    if (!loaded.ok()) {
        release_registry_lock(lock_fd);
        return loaded;
    }
    SessionRegistryStatus mismatch = SessionRegistryStatus::NotFound;
    bool replaced = false;
    for (auto& current : sessions) {
        if (current.session_id != session.session_id) continue;
        if (current.generation != expected_generation) {
            mismatch = SessionRegistryStatus::GenerationMismatch;
            break;
        }
        if (current.lifecycle_state != "opening") {
            mismatch = SessionRegistryStatus::Conflict;
            break;
        }
        current = session;
        replaced = true;
        break;
    }
    if (!replaced) {
        release_registry_lock(lock_fd);
        return {
            mismatch,
            "opening update no longer matches expected generation"};
    }
    bool saved = save_all_unlocked(sessions);
    if (!saved) {
        std::vector<SessionInfo> current;
        const SessionRegistryResult confirmed =
            load_all_unlocked(current);
        const SessionInfo* persisted =
            confirmed.ok()
                ? find_generation(
                      current,
                      session.session_id,
                      expected_generation)
                : nullptr;
        saved =
            persisted != nullptr &&
            same_registry_record(*persisted, session);
    }
    release_registry_lock(lock_fd);
    return saved
        ? SessionRegistryResult()
        : SessionRegistryResult(
              SessionRegistryStatus::IoError,
              "failed to persist opening session evidence");
}

SessionRegistryResult SessionRegistry::mark_cleanup_failed(
    const SessionInfo& session,
    const std::string& expected_generation) {
    if (session.lifecycle_state != "cleanup_failed") {
        return {
            SessionRegistryStatus::Invalid,
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
        return {
            SessionRegistryStatus::Invalid,
            "terminal session state must preserve the expected generation"};
    }
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all_unlocked(sessions);
    if (!loaded.ok()) {
        release_registry_lock(lock_fd);
        return loaded;
    }
    bool found = false;
    for (auto& current : sessions) {
        if (current.session_id != session.session_id) continue;
        if (current.generation != expected_generation) {
            release_registry_lock(lock_fd);
            return {
                SessionRegistryStatus::GenerationMismatch,
                "terminal state generation no longer matches registry"};
        }
        current = session;
        found = true;
        break;
    }
    if (!found) {
        release_registry_lock(lock_fd);
        return {
            SessionRegistryStatus::NotFound,
            "terminal state generation is not in registry"};
    }
    bool saved = save_all_unlocked(sessions);
    if (!saved) {
        std::vector<SessionInfo> current;
        const SessionRegistryResult confirmed =
            load_all_unlocked(current);
        const SessionInfo* persisted =
            confirmed.ok()
                ? find_generation(
                      current,
                      session.session_id,
                      expected_generation)
                : nullptr;
        saved =
            persisted != nullptr &&
            same_registry_record(*persisted, session);
    }
    release_registry_lock(lock_fd);
    return saved
        ? SessionRegistryResult()
        : SessionRegistryResult(
              SessionRegistryStatus::IoError,
              "failed to preserve terminal session generation");
}

SessionRegistryResult SessionRegistry::touch_if_generation(
    const std::string& session_id,
    const std::string& expected_generation,
    time_t last_active) {
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all_unlocked(sessions);
    if (!loaded.ok()) {
        release_registry_lock(lock_fd);
        return loaded;
    }
    bool found = false;
    for (auto& session : sessions) {
        if (session.session_id != session_id) continue;
        if (session.generation != expected_generation) {
            release_registry_lock(lock_fd);
            return {
                SessionRegistryStatus::GenerationMismatch,
                "touch generation no longer matches registry"};
        }
        // Activity timestamps have one-second resolution, while both the
        // server and its helper may touch the same request.  Do not repeat the
        // atomic file write and fsync sequence when it cannot advance the
        // durable timestamp.  Treat an older observation as success as well so
        // concurrent requests can never move last_active backwards.
        if (session.last_active >= last_active) {
            release_registry_lock(lock_fd);
            return SessionRegistryResult();
        }
        session.last_active = last_active;
        found = true;
        break;
    }
    if (!found) {
        release_registry_lock(lock_fd);
        return {
            SessionRegistryStatus::NotFound,
            "touch generation is not in registry"};
    }
    bool saved = save_all_unlocked(sessions);
    if (!saved) {
        std::vector<SessionInfo> current;
        const SessionRegistryResult confirmed =
            load_all_unlocked(current);
        const SessionInfo* persisted =
            confirmed.ok()
                ? find_generation(
                      current,
                      session_id,
                      expected_generation)
                : nullptr;
        saved = persisted != nullptr &&
                persisted->last_active == last_active;
    }
    release_registry_lock(lock_fd);
    return saved
        ? SessionRegistryResult()
        : SessionRegistryResult(
              SessionRegistryStatus::IoError,
              "failed to persist session activity");
}

SessionRegistryResult SessionRegistry::remove_if_generation(
    const std::string& session_id,
    const std::string& expected_generation) {
    int lock_fd = acquire_registry_lock();
    if (lock_fd < 0) {
        return {
            SessionRegistryStatus::IoError,
            "cannot acquire canonical session registry lock"};
    }
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all_unlocked(sessions);
    if (!loaded.ok()) {
        release_registry_lock(lock_fd);
        return loaded;
    }
    std::vector<SessionInfo> kept;
    bool found = false;
    for (const auto& session : sessions) {
        if (session.session_id != session_id) {
            kept.push_back(session);
            continue;
        }
        if (session.generation != expected_generation) {
            release_registry_lock(lock_fd);
            return {
                SessionRegistryStatus::GenerationMismatch,
                "remove generation no longer matches registry"};
        }
        found = true;
    }
    if (!found) {
        release_registry_lock(lock_fd);
        return {
            SessionRegistryStatus::NotFound,
            "remove generation is not in registry"};
    }
    bool saved = save_all_unlocked(kept);
    if (!saved) {
        std::vector<SessionInfo> current;
        SessionRegistryResult confirmed =
            load_all_unlocked(current);
        saved = confirmed.ok();
        for (const auto& item : current) {
            if (item.session_id == session_id &&
                item.generation == expected_generation) {
                saved = false;
                break;
            }
        }
    }
    release_registry_lock(lock_fd);
    return saved
        ? SessionRegistryResult()
        : SessionRegistryResult(
              SessionRegistryStatus::IoError,
              "failed to remove expected session generation");
}

SessionRegistryResult SessionRegistry::get(
    const std::string& session_id,
    SessionInfo& session) {
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all(sessions);
    if (!loaded.ok()) return loaded;
    for (const auto& s : sessions) {
        if (s.session_id == session_id) {
            session = s;
            return {};
        }
    }
    return {
        SessionRegistryStatus::NotFound,
        "session generation is not in registry"};
}

SessionRegistryResult SessionRegistry::get_latest(SessionInfo& session) {
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded = load_all(sessions);
    if (!loaded.ok()) return loaded;
    if (sessions.empty()) {
        return {
            SessionRegistryStatus::NotFound,
            "canonical session registry is empty"};
    }
    size_t latest_idx = 0;
    for (size_t i = 1; i < sessions.size(); ++i) {
        if (sessions[i].created_at > sessions[latest_idx].created_at) latest_idx = i;
    }
    session = sessions[latest_idx];
    return {};
}

bool SessionRegistry::is_valid_session_name(const std::string& name) {
    return xdebug_core::is_valid_session_name(name);
}

} // namespace xdebug_engine
