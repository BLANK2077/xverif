#pragma once

#include "session_registry.h"
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace xdebug_engine {

enum class EngineStartupExitCode {
    GenericFailure = 1,
    NpiInitFailed = 20,
    NpiLoadDesignFailed = 21,
    NpiFsdbOpenFailed = 22
};

enum class SessionHealthStatus {
    Healthy,
    RegistryMissing,
    RegistryInvalid,
    Opening,
    CleanupFailed,
    TerminatedOnTimeout,
    ProcessExited,
    SocketMissing,
    ConnectFailed,
    PingFailed,
    DbdirMissing,
    DbdirChanged,
    FsdbMissing,
    FsdbChanged
};

struct SessionHealth {
    std::string session_id;
    bool healthy = false;
    SessionHealthStatus status = SessionHealthStatus::RegistryMissing;
    std::string message;
    SessionInfo info;
};

struct SessionEnsureResult {
    std::string session_id;
    bool ok = false;
    bool reused = false;
    std::string status;
    std::string message;
    std::string startup_reason;
    std::string failure_phase;
    std::string diagnostic_log;
    bool cleanup_succeeded = true;
    std::string lifecycle_state;
    std::string compensation_status;
    SessionInfo info;
};

struct SessionCleanupPrecondition {
    bool require_ownership_match = false;
    std::string ownership_token_hash;
    // Internal generation/state preconditions used by GC and manager-owned
    // child cleanup.  They are never public request fields.
    std::string expected_generation;
    std::string expected_lifecycle_state;
};

enum class SessionCleanupStatus {
    Cleaned,
    NotFound,
    OwnershipMismatch,
    RegistryInvalid,
    CleanupFailed
};

enum class SessionCloseMode {
    Graceful,
    Force
};

struct SessionCleanupResult {
    SessionCleanupStatus status = SessionCleanupStatus::CleanupFailed;
    bool cleanup_succeeded = false;
    std::string message;
    SessionInfo info;

    bool ok() const {
        return status == SessionCleanupStatus::Cleaned &&
               cleanup_succeeded;
    }
};

struct SessionTimeoutContainmentResult {
    bool termination_confirmed = false;
    bool cleanup_succeeded = false;
    std::string cancel_state = "unknown";
    std::string session_state = "cleanup_failed";
    std::string message;
    SessionInfo info;
};

struct SessionTransportOptions {
    std::string transport;
    std::string bind_host;
    std::string host;
    int port = 0;
    bool detached = true;
};

struct WaitForServerResult {
    bool ok = false;
    std::string reason;
    long elapsed_ms = 0;
    bool child_exited = false;
    int child_status = 0;
    int child_exit_code = -1;
    std::string failure_phase;
    bool endpoint_valid = false;
    bool connect_ok = false;
    bool ping_ok = false;
    SessionInfo endpoint;
};

const char* session_health_status_name(SessionHealthStatus status);

bool xdebug_engine_debug_enabled();

// Session manager - high-level session lifecycle management
class SessionManager {
public:
    SessionManager();
    ~SessionManager();

    // Create a new session, returns session ID (0 on failure)
    // This spawns the server process
    SessionEnsureResult create_session(const std::vector<std::string>& design_args, const std::string& session_name);
    SessionEnsureResult create_session(const std::vector<std::string>& design_args, const std::string& session_name,
                                       const SessionTransportOptions& transport);

    // Ensure a healthy session exists for a dbdir argument list.
    SessionEnsureResult ensure_session(const std::vector<std::string>& design_args, const std::string& session_name);
    SessionEnsureResult ensure_session(const std::vector<std::string>& design_args, const std::string& session_name,
                                       const SessionTransportOptions& transport);
    SessionEnsureResult ensure_session(
        const std::vector<std::string>& design_args,
        const std::string& session_name,
        const SessionTransportOptions& transport,
        const std::string& ownership_token_hash);

    // Close a specific session.  Graceful mode never sends a signal and
    // retains managed evidence unless process exit is proven.  Force mode may
    // terminate the generation-matched local engine process from outside its
    // NPI context.
    SessionCleanupResult close_session(
        const std::string& session_id,
        SessionCloseMode mode,
        const SessionCleanupPrecondition& precondition =
            SessionCleanupPrecondition());

    // Compatibility wrapper for internal callers that require hard cleanup.
    SessionCleanupResult kill_session(
        const std::string& session_id,
        const SessionCleanupPrecondition& precondition =
            SessionCleanupPrecondition());

    // Stop a generation after its public request deadline without deleting
    // the canonical record.  A confirmed stop is retained as the
    // terminated_on_timeout diagnostic tombstone.
    SessionTimeoutContainmentResult terminate_on_timeout(
        const std::string& session_id,
        const std::string& expected_generation);

    // Kill all sessions
    bool kill_all_sessions();

    // Get session info by ID
    bool get_session(const std::string& session_id, SessionInfo& info);
    SessionRegistryResult lookup_session(
        const std::string& session_id,
        SessionInfo& info);

    // Get the latest (most recent) session
    bool get_latest_session(SessionInfo& info);

    // Update activity timestamp
    bool touch_session(
        const std::string& session_id,
        const std::string& expected_generation);

    // List all active sessions
    std::vector<SessionInfo> list_sessions();
    SessionRegistryResult list_sessions_checked(
        std::vector<SessionInfo>& sessions);

    // Diagnose a session without mutating the registry
    SessionHealth diagnose_session(const std::string& session_id);

    // Check if a session is alive
    bool is_session_alive(const std::string& session_id);

    // Get socket path for a session
    std::string get_socket_path(const std::string& session_id);

    // Clean up stale sessions
    void cleanup();

private:
    std::unique_ptr<SessionRegistry> registry_;
    // Non-detached servers are children owned by this process.  Keep the
    // ownership relation explicit so their exit status is reaped with
    // waitpid(2), rather than mistaking a zombie for a live server.
    std::map<pid_t, std::string> owned_children_;

    // Fork and exec server process
    pid_t spawn_server(const std::string& session_id, const std::vector<std::string>& args,
                       const SessionInfo& endpoint, bool detached);

    // Wait until the server responds to PING
    WaitForServerResult wait_for_server(const std::string& session_id, pid_t pid);
    void debug_log(const char* fmt, ...) const;

    bool parse_open_args(const std::vector<std::string>& design_args,
                         std::string& canonical_dbdir,
                         std::string& canonical_fsdb,
                         std::vector<std::string>& canonical_args) const;
    bool populate_dbdir_metadata(const std::string& dbdir_path, SessionInfo& session) const;
    bool current_dbdir_metadata(const SessionInfo& session, SessionInfo& current) const;
    bool dbdir_metadata_matches(const SessionInfo& expected, const SessionInfo& current) const;
    bool populate_fsdb_metadata(const std::string& fsdb_file, SessionInfo& session) const;
    bool current_fsdb_metadata(const SessionInfo& session, SessionInfo& current) const;
    bool fsdb_metadata_matches(const SessionInfo& expected, const SessionInfo& current) const;
    std::string canonicalize_dbdir_path(const std::string& dbdir_path) const;
    std::string canonicalize_fsdb_path(const std::string& fsdb_file) const;
    bool local_process_alive(pid_t pid) const;
    bool process_matches_session(const SessionInfo& session) const;
    bool wait_for_process_exit(pid_t pid, int timeout_ms) const;
    bool wait_for_owned_child_exit(pid_t pid, int timeout_ms);
    bool wait_for_session_process_exit(pid_t pid, int timeout_ms);
    bool terminate_spawned_child(pid_t pid, int timeout_ms);
    SessionCleanupResult cleanup_session_locked(
        SessionInfo session,
        SessionCloseMode mode);
    SessionHealth diagnose_session_locked(
        const SessionInfo& session);
};

} // namespace xdebug_engine
