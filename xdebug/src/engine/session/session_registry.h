#pragma once

#include "core/session/session_types.h"

#include <string>
#include <vector>
#include <ctime>
#include <sys/types.h>

namespace xdebug_engine {

// Unified SessionInfo from core — design fields are dbdir_*.
using SessionInfo = xdebug_core::SessionInfo;

enum class SessionRegistryStatus {
    Ok,
    NotFound,
    Conflict,
    GenerationMismatch,
    Invalid,
    IoError
};

struct SessionRegistryResult {
    SessionRegistryStatus status = SessionRegistryStatus::Ok;
    std::string message;

    SessionRegistryResult() = default;
    SessionRegistryResult(
        SessionRegistryStatus result_status,
        const std::string& result_message = std::string())
        : status(result_status), message(result_message) {}

    bool ok() const { return status == SessionRegistryStatus::Ok; }
};

// Session registry - manages persistent storage of session info
class SessionRegistry {
public:
    SessionRegistry();
    ~SessionRegistry();

    // Load all sessions from registry file
    SessionRegistryResult load_all(std::vector<SessionInfo>& sessions);

    // Reserve one new generation in opening state.
    SessionRegistryResult reserve_opening(const SessionInfo& session);

    // Compare-and-swap an opening reservation to active.
    SessionRegistryResult update_opening(
        const SessionInfo& session,
        const std::string& expected_generation);

    SessionRegistryResult finalize_opening(
        const SessionInfo& session,
        const std::string& expected_generation);

    // Preserve a failed cleanup as a managed generation.
    SessionRegistryResult mark_cleanup_failed(
        const SessionInfo& session,
        const std::string& expected_generation);

    // Persist a non-active diagnostic state with generation CAS semantics.
    SessionRegistryResult mark_terminal_state(
        const SessionInfo& session,
        const std::string& expected_generation);

    SessionRegistryResult touch_if_generation(
        const std::string& session_id,
        const std::string& expected_generation,
        time_t last_active);

    SessionRegistryResult remove_if_generation(
        const std::string& session_id,
        const std::string& expected_generation);

    SessionRegistryResult get(
        const std::string& session_id,
        SessionInfo& session);
    SessionRegistryResult get_latest(SessionInfo& session);
    static bool is_valid_session_name(const std::string& name);

private:
    std::string registry_path_;

    int acquire_registry_lock();
    bool release_registry_lock(int fd);
    SessionRegistryResult load_all_unlocked(
        std::vector<SessionInfo>& sessions);
    bool save_all_unlocked(const std::vector<SessionInfo>& sessions);
};

} // namespace xdebug_engine
