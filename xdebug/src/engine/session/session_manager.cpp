#include "session_manager.h"
#include "session_lifecycle_lease.h"
#include "session_transport.h"
#include "../server.h"
#include "../../design/common/xdebug_design_paths.h"
#include "../../design/protocol/protocol.h"
#include "common/env_config.h"
#include "common/path_utils.h"
#include "logging/action_log.h"
#include "session/session_timeout.h"
#include "session/session_types.h"
#include "transport/file_exchange.h"

#include <cstdio>
#include <cstring>
#include <strings.h>
#include <cstdarg>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/time.h>
#include <signal.h>
#include <sys/stat.h>
#include <limits.h>
#include <fcntl.h>
#include <cerrno>
#include <algorithm>
#include <fstream>

namespace xdebug_engine {

using namespace xdebug_design;

namespace {

std::string default_transport_from_env() {
    return xdebug_core::xdebug_transport();
}

bool valid_transport(const std::string& transport) {
    return transport == "uds" || transport == "tcp" || transport == "file";
}

std::string startup_failure_status(int exit_code) {
    if (exit_code == static_cast<int>(EngineStartupExitCode::NpiInitFailed))
        return "npi_init_failed";
    if (exit_code == static_cast<int>(EngineStartupExitCode::NpiLoadDesignFailed))
        return "npi_load_design_failed";
    if (exit_code == static_cast<int>(EngineStartupExitCode::NpiFsdbOpenFailed))
        return "npi_fsdb_open_failed";
    return "startup_failed";
}

std::string startup_failure_message(int exit_code,
                                    const std::string& reason) {
    if (exit_code == static_cast<int>(EngineStartupExitCode::NpiInitFailed))
        return "NPI initialization failed during the initialize phase; inspect engine_npi_startup log";
    if (exit_code == static_cast<int>(EngineStartupExitCode::NpiLoadDesignFailed))
        return "NPI design loading failed during the design-load phase; inspect engine_npi_startup log";
    if (exit_code == static_cast<int>(EngineStartupExitCode::NpiFsdbOpenFailed))
        return "NPI waveform opening failed during the FSDB-open phase; inspect engine_npi_startup log";
    return "Server did not become ready: " + reason;
}

bool generate_session_generation(std::string& generation) {
    generation.clear();
    unsigned char bytes[32] = {};
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return false;
    size_t offset = 0;
    while (offset < sizeof(bytes)) {
        const ssize_t count =
            read(fd, bytes + offset, sizeof(bytes) - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) {
            close(fd);
            return false;
        }
        offset += static_cast<size_t>(count);
    }
    if (close(fd) != 0) return false;
    static const char hex[] = "0123456789abcdef";
    generation.reserve(sizeof(bytes) * 2);
    for (const unsigned char byte : bytes) {
        generation.push_back(hex[byte >> 4]);
        generation.push_back(hex[byte & 0x0f]);
    }
    return true;
}

SessionCleanupStatus cleanup_status_from_registry(
    SessionRegistryStatus status) {
    if (status == SessionRegistryStatus::NotFound)
        return SessionCleanupStatus::NotFound;
    return SessionCleanupStatus::RegistryInvalid;
}

}  // namespace

bool xdebug_engine_debug_enabled() {
    return xdebug_core::xdebug_debug_enabled();
}

void SessionManager::debug_log(const char* fmt, ...) const {
    if (!xdebug_engine_debug_enabled()) return;
    fprintf(stderr, "[xdebug_engine-debug] ");
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fprintf(stderr, "\n");
    fflush(stderr);
}

const char* session_health_status_name(SessionHealthStatus status) {
    switch (status) {
        case SessionHealthStatus::Healthy:
            return "healthy";
        case SessionHealthStatus::RegistryMissing:
            return "registry_missing";
        case SessionHealthStatus::RegistryInvalid:
            return "registry_invalid";
        case SessionHealthStatus::Opening:
            return "opening";
        case SessionHealthStatus::CleanupFailed:
            return "cleanup_failed";
        case SessionHealthStatus::ProcessExited:
            return "process_exited";
        case SessionHealthStatus::SocketMissing:
            return "socket_missing";
        case SessionHealthStatus::ConnectFailed:
            return "connect_failed";
        case SessionHealthStatus::PingFailed:
            return "ping_failed";
        case SessionHealthStatus::DbdirMissing:
            return "dbdir_missing";
        case SessionHealthStatus::DbdirChanged:
            return "dbdir_changed";
        case SessionHealthStatus::FsdbMissing:
            return "fsdb_missing";
        case SessionHealthStatus::FsdbChanged:
            return "fsdb_changed";
    }
    return "unknown";
}

SessionManager::SessionManager() : registry_(new SessionRegistry()) {
}

SessionManager::~SessionManager() {
    // A non-detached server is scoped to this manager.  Normal direct-resource
    // handling closes it explicitly; this path is the exception-safe ownership
    // boundary for early returns and interrupted requests.
    std::vector<std::pair<pid_t, std::string>> children(
        owned_children_.begin(), owned_children_.end());
    for (const auto& child : children) {
        SessionInfo session;
        SessionRegistryResult lookup =
            registry_->get(child.second, session);
        if (lookup.ok() && session.server_pid == child.first) {
            SessionCleanupPrecondition precondition;
            precondition.expected_generation =
                session.generation;
            if (kill_session(child.second, precondition).ok()) {
                continue;
            }
        }
        // Never mutate an alias record that no longer describes this owned
        // child.  Process ownership alone is sufficient to reap it safely.
        terminate_spawned_child(child.first, 1500);
    }
}

pid_t SessionManager::spawn_server(const std::string& session_id, const std::vector<std::string>& args,
                                   const SessionInfo& endpoint, bool detached) {
    // Get path to current executable
    char self_path[1024] = {};
    ssize_t len = readlink("/proc/self/exe", self_path, sizeof(self_path) - 1);
    if (len < 0) {
        return -1;
    }

    // Build server argv: [exe, "--server", session_id, ...design_args...]
    std::vector<char*> argv;
    argv.push_back(self_path);
    argv.push_back((char*)"--server");

    std::string session_id_arg = session_id;
    argv.push_back(const_cast<char*>(session_id_arg.c_str()));

    std::vector<std::string> arg_storage = args;  // Keep strings alive
    arg_storage.push_back("--transport");
    arg_storage.push_back(endpoint.transport);
    arg_storage.push_back("--bind");
    arg_storage.push_back(endpoint.bind_host);
    arg_storage.push_back("--host");
    arg_storage.push_back(endpoint.host);
    arg_storage.push_back("--port");
    arg_storage.push_back(std::to_string(endpoint.port));
    arg_storage.push_back("--auth");
    arg_storage.push_back(endpoint.auth_token);
    for (const auto& arg : arg_storage) {
        argv.push_back(const_cast<char*>(arg.c_str()));
    }
    argv.push_back(nullptr);

    pid_t pid = fork();
    if (pid < 0) {
        return -1;
    }

    if (pid == 0) {
        if (detached) {
            // Managed named sessions survive the short-lived session.open CLI.
            if (setsid() < 0) {
                _exit(1);
            }
            signal(SIGHUP, SIG_IGN);
        }

        // Close inherited file descriptors (fds > 2) to avoid leaking
        // pipe ends and other handles into the daemonised engine server.
        int max_fd = sysconf(_SC_OPEN_MAX);
        if (max_fd <= 0 || max_fd > 65536) max_fd = 256;
        for (int i = 3; i < max_fd; ++i) close(i);

        // Child process - exec server
        execv(self_path, argv.data());
        perror("execv");
        _exit(1);
    }

    return pid;
}

std::string SessionManager::canonicalize_dbdir_path(const std::string& dbdir_path) const {
    char resolved[PATH_MAX];
    if (realpath(dbdir_path.c_str(), resolved)) {
        return std::string(resolved);
    }
    return dbdir_path;
}

std::string SessionManager::canonicalize_fsdb_path(const std::string& fsdb_file) const {
    char resolved[PATH_MAX];
    if (realpath(fsdb_file.c_str(), resolved)) {
        return std::string(resolved);
    }
    return fsdb_file;
}

bool SessionManager::populate_dbdir_metadata(const std::string& dbdir_path, SessionInfo& session) const {
    struct stat st;
    if (stat(dbdir_path.c_str(), &st) != 0) return false;
    if (!S_ISDIR(st.st_mode)) return false;
    session.dbdir_path = dbdir_path;
    session.dbdir_mtime = static_cast<long>(st.st_mtime);
    session.dbdir_size = static_cast<long long>(st.st_size);
    session.dbdir_dev = static_cast<unsigned long long>(st.st_dev);
    session.dbdir_inode = static_cast<unsigned long long>(st.st_ino);
    return true;
}

bool SessionManager::current_dbdir_metadata(const SessionInfo& session, SessionInfo& current) const {
    if (session.dbdir_path.empty()) return false;
    current = session;
    return populate_dbdir_metadata(session.dbdir_path, current);
}

bool SessionManager::dbdir_metadata_matches(const SessionInfo& expected, const SessionInfo& current) const {
    return xdebug_core::resource_content_matches(expected.dbdir_mtime,
                                                 expected.dbdir_size,
                                                 current.dbdir_mtime,
                                                 current.dbdir_size);
}

bool SessionManager::populate_fsdb_metadata(const std::string& fsdb_file, SessionInfo& session) const {
    struct stat st;
    if (stat(fsdb_file.c_str(), &st) != 0) return false;
    if (!S_ISREG(st.st_mode)) return false;
    session.fsdb_file = fsdb_file;
    session.fsdb_mtime = static_cast<long>(st.st_mtime);
    session.fsdb_size = static_cast<long long>(st.st_size);
    session.fsdb_dev = static_cast<unsigned long long>(st.st_dev);
    session.fsdb_inode = static_cast<unsigned long long>(st.st_ino);
    return true;
}

bool SessionManager::current_fsdb_metadata(const SessionInfo& session, SessionInfo& current) const {
    if (session.fsdb_file.empty()) return false;
    current = session;
    return populate_fsdb_metadata(session.fsdb_file, current);
}

bool SessionManager::fsdb_metadata_matches(const SessionInfo& expected, const SessionInfo& current) const {
    return xdebug_core::resource_content_matches(expected.fsdb_mtime,
                                                 expected.fsdb_size,
                                                 current.fsdb_mtime,
                                                 current.fsdb_size);
}

bool SessionManager::local_process_alive(pid_t pid) const {
    if (pid <= 0) return false;
    if (kill(pid, 0) == 0) return true;
    return errno == EPERM;
}

bool SessionManager::process_matches_session(const SessionInfo& session) const {
    if (session.server_pid <= 0 || session.session_id.empty()) return false;
    std::ifstream input(("/proc/" + std::to_string(session.server_pid) + "/cmdline").c_str(),
                        std::ios::in | std::ios::binary);
    if (!input) return false;
    std::string cmdline((std::istreambuf_iterator<char>(input)),
                        std::istreambuf_iterator<char>());
    const std::string marker = std::string("--server") + '\0' + session.session_id + '\0';
    return cmdline.find(marker) != std::string::npos;
}

bool SessionManager::wait_for_process_exit(pid_t pid, int timeout_ms) const {
    const int sleep_us = 50000;
    const int loops = timeout_ms > 0 ? (timeout_ms * 1000 + sleep_us - 1) / sleep_us : 1;
    for (int i = 0; i < loops; ++i) {
        if (!local_process_alive(pid)) return true;
        usleep(sleep_us);
    }
    return !local_process_alive(pid);
}

bool SessionManager::wait_for_owned_child_exit(pid_t pid, int timeout_ms) {
    auto owned = owned_children_.find(pid);
    if (owned == owned_children_.end()) return false;

    const int sleep_us = 10000;
    const int loops =
        timeout_ms > 0
            ? (timeout_ms * 1000 + sleep_us - 1) / sleep_us
            : 1;
    for (int i = 0; i < loops; ++i) {
        int status = 0;
        pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            owned_children_.erase(pid);
            return true;
        }
        if (waited < 0) {
            if (errno == EINTR) continue;
            if (errno == ECHILD) {
                owned_children_.erase(pid);
                // The process is no longer our child.  Treat ownership as
                // discharged and never signal a possibly reused PID.
                return true;
            }
            return false;
        }
        usleep(sleep_us);
    }

    int status = 0;
    pid_t waited = waitpid(pid, &status, WNOHANG);
    if (waited == pid) {
        owned_children_.erase(pid);
        return true;
    }
    if (waited < 0 && errno == ECHILD) {
        owned_children_.erase(pid);
        return true;
    }
    return false;
}

bool SessionManager::wait_for_session_process_exit(pid_t pid, int timeout_ms) {
    if (owned_children_.find(pid) != owned_children_.end()) {
        return wait_for_owned_child_exit(pid, timeout_ms);
    }
    return wait_for_process_exit(pid, timeout_ms);
}

bool SessionManager::terminate_spawned_child(pid_t pid, int timeout_ms) {
    if (pid <= 0) return true;
    if (owned_children_.find(pid) == owned_children_.end()) return true;
    if (kill(pid, SIGTERM) != 0 && errno != ESRCH) return false;
    if (wait_for_session_process_exit(pid, timeout_ms)) return true;
    if (kill(pid, SIGKILL) != 0 && errno != ESRCH) return false;
    return wait_for_session_process_exit(pid, timeout_ms);
}

bool SessionManager::parse_open_args(const std::vector<std::string>& args,
                                     std::string& canonical_dbdir,
                                     std::string& canonical_fsdb,
                                     std::vector<std::string>& canonical_args) const {
    // The unified engine accepts both -dbdir and/or -fsdb.
    canonical_args = args;
    bool has_daidir = false;
    bool has_fsdb = false;

    for (size_t i = 0; i + 1 < args.size(); ++i) {
        if (args[i] == "-dbdir") {
            std::string dbdir = args[i + 1];
            while (dbdir.size() > 1 && dbdir.back() == '/') dbdir.pop_back();
            const std::string suffix = ".daidir";
            if (dbdir.size() < suffix.size() ||
                dbdir.compare(dbdir.size() - suffix.size(), suffix.size(), suffix) != 0)
                return false;
            canonical_dbdir = canonicalize_dbdir_path(dbdir);
            SessionInfo metadata;
            if (!populate_dbdir_metadata(canonical_dbdir, metadata))
                return false;
            canonical_args[i + 1] = canonical_dbdir;
            has_daidir = true;
        } else if (args[i] == "-fsdb" || args[i] == "-ssf") {
            canonical_fsdb = canonicalize_fsdb_path(args[i + 1]);
            SessionInfo metadata;
            if (!populate_fsdb_metadata(canonical_fsdb, metadata))
                return false;
            canonical_args[i + 1] = canonical_fsdb;
            has_fsdb = true;
        }
    }

    // At least one resource is required.
    if (!has_daidir && !has_fsdb)
        return false;
    return true;
}

WaitForServerResult SessionManager::wait_for_server(const std::string& session_id, pid_t pid) {
    WaitForServerResult result;

    int timeout_sec = 0;
    std::string timeout_error;
    if (!xdebug_core::session_start_timeout_sec(timeout_sec, timeout_error)) {
        result.reason = "invalid_config: " + timeout_error;
        xdebug_core::log_lifecycle_event("engine", session_id, "wait_for_server.invalid_config", false,
                                         {{"message", timeout_error}});
        return result;
    }
    int loops = timeout_sec * 10;
    debug_log("wait_for_server: session=%s pid=%d timeout_sec=%d",
              session_id.c_str(), pid, timeout_sec);
    xdebug_core::log_lifecycle_event("engine", session_id, "wait_for_server.begin", true,
                                     {{"pid", static_cast<int>(pid)}, {"timeout_sec", timeout_sec}});

    for (int i = 0; i < loops; ++i) {
        usleep(100000);  // 100ms
        result.elapsed_ms = (i + 1) * 100L;

        SessionInfo endpoint;
        bool endpoint_ready = read_endpoint_file(session_id, endpoint);
        result.endpoint_valid = endpoint_ready;
        if (endpoint_ready) {
            if (is_file_transport(endpoint)) {
                result.connect_ok = true;
                result.ping_ok = ping_session_endpoint(endpoint);
                if (result.ping_ok) {
                    result.ok = true;
                    result.reason = "ready";
                    result.endpoint = endpoint;
                    xdebug_core::log_lifecycle_event("engine", session_id, "wait_for_server.ready", true,
                                                     {{"elapsed_ms", result.elapsed_ms}, {"endpoint_valid", result.endpoint_valid},
                                                      {"connect_ok", result.connect_ok}, {"ping_ok", result.ping_ok},
                                                      {"transport", result.endpoint.transport},
                                                      {"file_dir", result.endpoint.file_dir}});
                    return result;
                }
            } else {
            int fd = connect_session_endpoint(endpoint);
            if (fd >= 0) {
                result.connect_ok = true;
                close(fd);
                result.ping_ok = ping_session_endpoint(endpoint);
                if (result.ping_ok) {
                    result.ok = true;
                    result.reason = "ready";
                    result.endpoint = endpoint;
                    debug_log("wait_for_server: endpoint_valid=1 connect_ok=1 ping_ok=1 elapsed_ms=%ld",
                              result.elapsed_ms);
                    xdebug_core::log_lifecycle_event("engine", session_id, "wait_for_server.ready", true,
                                                     {{"elapsed_ms", result.elapsed_ms}, {"endpoint_valid", result.endpoint_valid},
                                                      {"connect_ok", result.connect_ok}, {"ping_ok", result.ping_ok},
                                                      {"transport", result.endpoint.transport},
                                                      {"socket_path", result.endpoint.socket_path},
                                                      {"host", result.endpoint.host}, {"port", result.endpoint.port}});
                    return result;
                }
            }
            }
        }

        int status;
        if (waitpid(pid, &status, WNOHANG) > 0) {
            owned_children_.erase(pid);
            result.child_exited = true;
            result.child_status = status;
            if (WIFEXITED(status)) {
                result.child_exit_code = WEXITSTATUS(status);
                result.failure_phase =
                    xdebug_design::engine_startup_failure_phase(result.child_exit_code);
            }
            result.reason = "child_exited";
            debug_log("wait_for_server: child_exited status=%d elapsed_ms=%ld endpoint_valid=%d connect_ok=%d ping_ok=%d",
                      status, result.elapsed_ms, result.endpoint_valid ? 1 : 0,
                      result.connect_ok ? 1 : 0, result.ping_ok ? 1 : 0);
            xdebug_core::log_lifecycle_event("engine", session_id, "wait_for_server.child_exited", false,
                                             {{"elapsed_ms", result.elapsed_ms}, {"child_status", status},
                                              {"child_exit_code", result.child_exit_code},
                                              {"failure_phase", result.failure_phase},
                                              {"endpoint_valid", result.endpoint_valid}, {"connect_ok", result.connect_ok},
                                              {"ping_ok", result.ping_ok}});
            return result;
        }
    }

    result.reason = result.endpoint_valid
        ? (result.connect_ok ? "ping_failed" : "endpoint_connect_failed")
        : "timeout_waiting_endpoint";
    debug_log("wait_for_server: timeout reason=%s elapsed_ms=%ld endpoint_valid=%d connect_ok=%d ping_ok=%d",
              result.reason.c_str(), result.elapsed_ms, result.endpoint_valid ? 1 : 0,
              result.connect_ok ? 1 : 0, result.ping_ok ? 1 : 0);
    xdebug_core::log_lifecycle_event("engine", session_id, "wait_for_server.timeout", false,
                                     {{"reason", result.reason}, {"elapsed_ms", result.elapsed_ms},
                                      {"endpoint_valid", result.endpoint_valid}, {"connect_ok", result.connect_ok},
                                      {"ping_ok", result.ping_ok}});
    return result;
}

SessionEnsureResult SessionManager::ensure_session(const std::vector<std::string>& design_args, const std::string& session_name) {
    SessionTransportOptions transport;
    return ensure_session(design_args, session_name, transport, "");
}

SessionEnsureResult SessionManager::ensure_session(const std::vector<std::string>& design_args,
                                                   const std::string& session_name,
                                                   const SessionTransportOptions& transport_options) {
    return ensure_session(
        design_args,
        session_name,
        transport_options,
        "");
}

SessionEnsureResult SessionManager::ensure_session(
    const std::vector<std::string>& design_args,
    const std::string& session_name,
    const SessionTransportOptions& transport_options,
    const std::string& ownership_token_hash) {
    SessionEnsureResult result;

    std::string canonical_dbdir;
    std::string canonical_fsdb;
    std::vector<std::string> canonical_args;
    if (!parse_open_args(design_args, canonical_dbdir, canonical_fsdb, canonical_args)) {
        debug_log("ensure_session: reason=invalid_args");
        xdebug_core::log_lifecycle_event("engine", session_name, "ensure_session.invalid_args", false);
        result.status = "invalid_args";
        result.message = "Usage: open [-dbdir <simv.daidir>] [-fsdb <waves.fsdb>] ...";
        return result;
    }
    debug_log("ensure_session: canonical_dbdir=%s canonical_fsdb=%s",
              canonical_dbdir.c_str(), canonical_fsdb.c_str());
    xdebug_core::log_lifecycle_event("engine", session_name, "ensure_session.canonicalized", true,
                                     {{"dbdir", canonical_dbdir}, {"fsdb", canonical_fsdb}});

    if (!SessionRegistry::is_valid_session_name(session_name)) {
        result.status = "invalid_session_id";
        result.message = xdebug_core::session_name_rule();
        debug_log("ensure_session: reason=invalid_session_id name=%s", session_name.c_str());
        xdebug_core::log_lifecycle_event("engine", session_name, "ensure_session.invalid_session_id", false);
        return result;
    }
    std::string requested_transport = transport_options.transport.empty() ? default_transport_from_env() : transport_options.transport;
    if (!valid_transport(requested_transport)) {
        result.status = "invalid_transport";
        result.message = "transport must be uds, tcp, or file";
        xdebug_core::log_lifecycle_event("engine", session_name, "ensure_session.invalid_transport", false,
                                         {{"transport", requested_transport}});
        return result;
    }

    SessionLifecycleLease lease(session_name);
    if (!lease.locked()) {
        result.status = "lifecycle_lock_failed";
        result.message = "Failed to acquire the session lifecycle lease";
        return result;
    }

    SessionInfo session;
    session.session_id = session_name;
    session.lifecycle_state = "opening";
    session.transport = requested_transport;
    session.server_host = current_host_name();
    session.ownership_token_hash = ownership_token_hash;
    session.created_at = time(nullptr);
    session.last_active = session.created_at;
    if (!generate_session_generation(session.generation)) {
        result.status = "generation_failed";
        result.message = "Failed to create a session lifecycle generation";
        return result;
    }
    if (requested_transport == "uds") {
        session.socket_path =
            xdebug_design_socket_path(session_name);
    } else if (requested_transport == "file") {
        session.file_dir = xdebug_core::file_transport_dir(
            xdebug_design_session_dir(session_name));
    } else {
        session.bind_host = transport_options.bind_host.empty()
            ? "127.0.0.1"
            : transport_options.bind_host;
        session.host = transport_options.host.empty()
            ? (session.bind_host == "0.0.0.0" ||
                       session.bind_host == "::"
                   ? current_host_name()
                   : session.bind_host)
            : transport_options.host;
        session.port = transport_options.port;
        session.auth_token = generate_auth_token();
    }
    if (!canonical_dbdir.empty() &&
        !populate_dbdir_metadata(canonical_dbdir, session)) {
        result.status = "resource_changed";
        result.message =
            "Daidir became unavailable before session reservation";
        return result;
    }
    if (!canonical_fsdb.empty() &&
        !populate_fsdb_metadata(canonical_fsdb, session)) {
        result.status = "resource_changed";
        result.message =
            "FSDB became unavailable before session reservation";
        return result;
    }

    SessionRegistryResult reserved =
        registry_->reserve_opening(session);
    if (!reserved.ok()) {
        result.status =
            reserved.status == SessionRegistryStatus::Conflict
                ? "session_id_exists"
                : "registry_failed";
        result.message =
            reserved.status == SessionRegistryStatus::Conflict
                ? "Session id already exists: " + session_name
                : reserved.message;
        return result;
    }

    bool marker_committed =
        xdebug_design_write_generation_marker(
            session_name, session.generation);
    if (!marker_committed) {
        marker_committed =
            xdebug_design_generation_matches(
                session_name, session.generation);
    }
    if (!marker_committed) {
        SessionRegistryResult removed =
            registry_->remove_if_generation(
                session_name, session.generation);
        result.status = "generation_marker_failed";
        result.message =
            "Failed to persist the session generation marker";
        result.cleanup_succeeded = removed.ok();
        result.compensation_status =
            removed.ok() ? "cleaned" : "cleanup_failed";
        if (!removed.ok()) {
            session.lifecycle_state = "cleanup_failed";
            const SessionRegistryResult retained =
                registry_->mark_cleanup_failed(
                    session, session.generation);
            if (retained.ok()) {
                result.lifecycle_state =
                    "cleanup_failed";
            } else {
                result.message +=
                    "; failed to persist cleanup_failed lifecycle state";
            }
            result.info = session;
        }
        return result;
    }

    const auto compensate =
        [&](const std::string& failure_status,
            const std::string& failure_message) {
            result.status = failure_status;
            result.message = failure_message;
            SessionCleanupResult cleanup =
                cleanup_session_locked(session);
            result.cleanup_succeeded =
                cleanup.cleanup_succeeded;
            result.compensation_status =
                cleanup.ok() ? "cleaned" : "cleanup_failed";
            result.lifecycle_state =
                cleanup.ok()
                    ? std::string()
                    : "cleanup_failed";
            result.info = cleanup.info;
        };

    pid_t pid = spawn_server(
        session_name,
        canonical_args,
        session,
        transport_options.detached);
    if (pid < 0) {
        compensate(
            "spawn_failed",
            "Failed to spawn xdebug engine server");
        return result;
    }
    owned_children_[pid] = session_name;
    session.server_pid = pid;
    xdebug_core::log_lifecycle_event(
        "engine",
        session_name,
        "ensure_session.spawned_server",
        true,
        {{"pid", static_cast<int>(pid)}});
    SessionRegistryResult opening_updated =
        registry_->update_opening(
            session, session.generation);
    if (!opening_updated.ok()) {
        compensate(
            "registry_failed",
            "Failed to persist opening process evidence");
        return result;
    }

    debug_log(
        "ensure_session: spawned_server session=%s pid=%d",
        session_name.c_str(),
        pid);
    WaitForServerResult wait =
        wait_for_server(session_name, pid);
    if (!wait.ok) {
        result.startup_reason = wait.reason;
        result.failure_phase = wait.failure_phase;
        if (!wait.failure_phase.empty()) {
            result.diagnostic_log = "engine_npi_startup";
        }
        compensate(
            startup_failure_status(wait.child_exit_code),
            startup_failure_message(
                wait.child_exit_code, wait.reason));
        return result;
    }

    if (wait.endpoint.session_id != session_name ||
        wait.endpoint.transport != requested_transport) {
        compensate(
            "endpoint_mismatch",
            "Server endpoint does not match the reserved session generation");
        return result;
    }
    session.socket_path = wait.endpoint.socket_path;
    session.file_dir = wait.endpoint.file_dir;
    session.host = wait.endpoint.host;
    session.bind_host = wait.endpoint.bind_host;
    session.port = wait.endpoint.port;
    session.server_host = wait.endpoint.server_host;
    session.auth_token = wait.endpoint.auth_token;
    opening_updated =
        registry_->update_opening(
            session, session.generation);
    if (!opening_updated.ok()) {
        compensate(
            "registry_failed",
            "Failed to persist ready endpoint evidence");
        return result;
    }

    SessionInfo current = session;
    if (!canonical_dbdir.empty() &&
        (!populate_dbdir_metadata(canonical_dbdir, current) ||
         !dbdir_metadata_matches(session, current))) {
        compensate(
            "resource_changed",
            "Daidir changed while opening the session");
        return result;
    }
    if (!canonical_fsdb.empty() &&
        (!populate_fsdb_metadata(canonical_fsdb, current) ||
         !fsdb_metadata_matches(session, current))) {
        compensate(
            "resource_changed",
            "FSDB changed while opening the session");
        return result;
    }
    session = current;
    session.lifecycle_state = "active";
    session.last_active = time(nullptr);
    SessionRegistryResult finalized =
        registry_->finalize_opening(
            session, session.generation);
    if (!finalized.ok()) {
        session.lifecycle_state = "opening";
        compensate(
            "registry_failed",
            "Failed to finalize the session generation");
        return result;
    }
    if (transport_options.detached) {
        owned_children_.erase(pid);
    }

    result.ok = true;
    result.reused = false;
    result.session_id = session_name;
    result.status = "healthy";
    result.message = "Created healthy session";
    result.lifecycle_state = "active";
    result.info = session;
    debug_log(
        "ensure_session: success session=%s pid=%d",
        session_name.c_str(),
        pid);
    xdebug_core::log_lifecycle_event("engine", session_name, "ensure_session.success", true,
                                     {{"pid", static_cast<int>(pid)}, {"socket_path", session.socket_path},
                                      {"dbdir", session.dbdir_path}, {"fsdb", session.fsdb_file}});
    return result;
}

SessionEnsureResult SessionManager::create_session(const std::vector<std::string>& design_args, const std::string& session_name) {
    return ensure_session(design_args, session_name);
}

SessionEnsureResult SessionManager::create_session(const std::vector<std::string>& design_args,
                                                   const std::string& session_name,
                                                   const SessionTransportOptions& transport) {
    return ensure_session(design_args, session_name, transport);
}

SessionCleanupResult SessionManager::cleanup_session_locked(
    SessionInfo session) {
    SessionCleanupResult result;
    result.info = session;

    session.lifecycle_state = "cleanup_failed";
    SessionRegistryResult preserved =
        registry_->mark_cleanup_failed(
            session, session.generation);
    if (!preserved.ok()) {
        result.status =
            cleanup_status_from_registry(preserved.status);
        result.message = preserved.message;
        return result;
    }
    result.info = session;

    const bool has_process = session.server_pid > 0;
    const bool quit_sent =
        has_process && send_quit_to_endpoint(session);
    const bool owned_child =
        owned_children_.find(session.server_pid) !=
        owned_children_.end();
    bool stopped = !has_process;

    if (has_process && is_local_session_host(session)) {
        stopped = wait_for_session_process_exit(
            session.server_pid,
            quit_sent ? 1500 : 100);
        if (!stopped && !owned_child &&
            !process_matches_session(session)) {
            // The recorded process is gone or the PID was reused.  Never
            // signal an unrelated process; the recorded generation is stale.
            stopped = true;
        }
        if (!stopped) {
            if (kill(session.server_pid, SIGTERM) == 0 ||
                errno == ESRCH) {
                stopped = wait_for_session_process_exit(
                    session.server_pid, 1500);
            }
        }
        if (!stopped) {
            if (kill(session.server_pid, SIGKILL) == 0 ||
                errno == ESRCH) {
                stopped = wait_for_session_process_exit(
                    session.server_pid, 1500);
            }
        }
    } else if (has_process && quit_sent) {
        for (int i = 0; i < 15; ++i) {
            if (!ping_session_endpoint(session)) {
                stopped = true;
                break;
            }
            usleep(100000);
        }
    }

    if (!stopped) {
        result.status = SessionCleanupStatus::CleanupFailed;
        result.message =
            "session process could not be proven stopped";
        return result;
    }
    if (!xdebug_design_remove_session_generation(
            session.session_id,
            session.generation)) {
        result.status = SessionCleanupStatus::CleanupFailed;
        result.message =
            "session artifacts do not match or could not be removed";
        return result;
    }

    SessionRegistryResult removed =
        registry_->remove_if_generation(
            session.session_id,
            session.generation);
    if (!removed.ok()) {
        result.status =
            cleanup_status_from_registry(removed.status);
        result.message = removed.message;
        return result;
    }

    result.status = SessionCleanupStatus::Cleaned;
    result.cleanup_succeeded = true;
    result.message = "session generation cleaned";
    return result;
}

SessionCleanupResult SessionManager::kill_session(
    const std::string& session_id,
    const SessionCleanupPrecondition& precondition) {
    SessionCleanupResult result;
    SessionLifecycleLease lease(session_id);
    if (!lease.locked()) {
        result.status = SessionCleanupStatus::CleanupFailed;
        result.message =
            "failed to acquire the session lifecycle lease";
        return result;
    }

    SessionInfo session;
    SessionRegistryResult lookup =
        registry_->get(session_id, session);
    if (!lookup.ok()) {
        result.status =
            cleanup_status_from_registry(lookup.status);
        result.message = lookup.message;
        return result;
    }
    result.info = session;

    if (!precondition.expected_generation.empty() &&
        session.generation !=
            precondition.expected_generation) {
        result.status =
            SessionCleanupStatus::NotFound;
        result.message =
            "session generation no longer matches cleanup precondition";
        return result;
    }
    if (!precondition.expected_lifecycle_state.empty() &&
        session.lifecycle_state !=
            precondition.expected_lifecycle_state) {
        result.status =
            SessionCleanupStatus::NotFound;
        result.message =
            "session lifecycle state no longer matches cleanup precondition";
        return result;
    }
    if (precondition.require_ownership_match &&
        (precondition.ownership_token_hash.empty() ||
         session.ownership_token_hash.empty() ||
         session.ownership_token_hash !=
             precondition.ownership_token_hash)) {
        result.status =
            SessionCleanupStatus::OwnershipMismatch;
        result.message =
            "the supplied ownership token does not match this session generation";
        return result;
    }

    xdebug_core::log_lifecycle_event(
        "engine",
        session_id,
        "kill_session.begin",
        true,
        {{"pid", session.server_pid},
         {"lifecycle_state", session.lifecycle_state}});
    result = cleanup_session_locked(session);
    xdebug_core::log_lifecycle_event(
        "engine",
        session_id,
        "kill_session.end",
        result.ok(),
        {{"pid", session.server_pid},
         {"cleanup_succeeded", result.cleanup_succeeded},
         {"lifecycle_state",
          result.ok() ? "removed" : "cleanup_failed"}});
    return result;
}

bool SessionManager::kill_all_sessions() {
    std::vector<SessionInfo> sessions;
    if (!registry_->load_all(sessions).ok()) return false;
    std::sort(
        sessions.begin(),
        sessions.end(),
        [](const SessionInfo& lhs, const SessionInfo& rhs) {
            return lhs.session_id < rhs.session_id;
        });
    xdebug_core::log_lifecycle_event("engine", "adhoc", "kill_all.begin", true,
                                     {{"count", sessions.size()}});
    bool all_ok = true;
    for (const auto& session : sessions) {
        SessionCleanupPrecondition precondition;
        precondition.expected_generation =
            session.generation;
        if (!kill_session(
                 session.session_id,
                 precondition)
                 .ok()) {
            all_ok = false;
        }
    }
    xdebug_core::log_lifecycle_event("engine", "adhoc", "kill_all.end", all_ok);
    return all_ok;
}

bool SessionManager::get_session(const std::string& session_id, SessionInfo& info) {
    return lookup_session(session_id, info).ok();
}

SessionRegistryResult SessionManager::lookup_session(
    const std::string& session_id,
    SessionInfo& info) {
    return registry_->get(session_id, info);
}

bool SessionManager::get_latest_session(SessionInfo& info) {
    return registry_->get_latest(info).ok();
}

bool SessionManager::touch_session(
    const std::string& session_id,
    const std::string& expected_generation) {
    return registry_->touch_if_generation(
        session_id,
        expected_generation,
        time(nullptr))
        .ok();
}

std::vector<SessionInfo> SessionManager::list_sessions() {
    cleanup();
    std::vector<SessionInfo> sessions;
    if (!list_sessions_checked(sessions).ok()) {
        sessions.clear();
    }
    return sessions;
}

SessionRegistryResult SessionManager::list_sessions_checked(
    std::vector<SessionInfo>& sessions) {
    return registry_->load_all(sessions);
}

SessionHealth SessionManager::diagnose_session(const std::string& session_id) {
    SessionHealth health;
    health.session_id = session_id;

    SessionLifecycleLease lease(session_id);
    if (!lease.locked()) {
        health.status = SessionHealthStatus::RegistryInvalid;
        health.message =
            "Session lifecycle lease could not be acquired";
        return health;
    }
    SessionInfo session;
    SessionRegistryResult lookup =
        registry_->get(session_id, session);
    if (!lookup.ok()) {
        health.status =
            lookup.status == SessionRegistryStatus::NotFound
                ? SessionHealthStatus::RegistryMissing
                : SessionHealthStatus::RegistryInvalid;
        health.message =
            lookup.status == SessionRegistryStatus::NotFound
                ? "Session is not present in the registry"
                : lookup.message;
        xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.registry_missing", false);
        return health;
    }
    return diagnose_session_locked(session);
}

SessionHealth SessionManager::diagnose_session_locked(
    const SessionInfo& session) {
    SessionHealth health;
    const std::string& session_id = session.session_id;
    health.session_id = session.session_id;
    health.info = session;

    if (session.lifecycle_state == "opening") {
        health.status = SessionHealthStatus::Opening;
        health.message = "Session generation is still opening";
        return health;
    }
    if (session.lifecycle_state == "cleanup_failed") {
        health.status = SessionHealthStatus::CleanupFailed;
        health.message =
            "Session generation retained evidence after cleanup failure";
        return health;
    }
    if (session.lifecycle_state != "active" ||
        !xdebug_design_generation_matches(
            session.session_id,
            session.generation)) {
        health.status = SessionHealthStatus::RegistryInvalid;
        health.message =
            "Session registry and generation marker do not match";
        return health;
    }

    SessionInfo current;
    if (!session.dbdir_path.empty()) {
        if (!current_dbdir_metadata(session, current)) {
            health.status = SessionHealthStatus::DbdirMissing;
            health.message = "Daidir path is missing, is not a directory, or lacks metadata";
            xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.dbdir_missing", false,
                                             {{"dbdir", session.dbdir_path}});
            return health;
        }
        if (!dbdir_metadata_matches(session, current)) {
            bool identity_changed = xdebug_core::resource_identity_differs(session.dbdir_dev,
                                                                           session.dbdir_inode,
                                                                           current.dbdir_dev,
                                                                           current.dbdir_inode);
            health.status = SessionHealthStatus::DbdirChanged;
            health.message = "Daidir metadata changed since session was opened";
            xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.dbdir_changed", false,
                                             {{"dbdir", session.dbdir_path},
                                              {"old_mtime", session.dbdir_mtime}, {"new_mtime", current.dbdir_mtime},
                                              {"old_size", session.dbdir_size}, {"new_size", current.dbdir_size},
                                              {"old_dev", session.dbdir_dev}, {"new_dev", current.dbdir_dev},
                                              {"old_inode", session.dbdir_inode}, {"new_inode", current.dbdir_inode},
                                              {"identity_changed", identity_changed}});
            return health;
        }
        if (xdebug_core::resource_identity_differs(session.dbdir_dev,
                                                   session.dbdir_inode,
                                                   current.dbdir_dev,
                                                   current.dbdir_inode)) {
            debug_log("diagnose_session: dbdir_identity_changed old_dev=%llu new_dev=%llu old_inode=%llu new_inode=%llu content_match=1",
                      (unsigned long long)session.dbdir_dev,
                      (unsigned long long)current.dbdir_dev,
                      (unsigned long long)session.dbdir_inode,
                      (unsigned long long)current.dbdir_inode);
            xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.dbdir_identity_changed", true,
                                             {{"dbdir", session.dbdir_path},
                                              {"old_dev", session.dbdir_dev}, {"new_dev", current.dbdir_dev},
                                              {"old_inode", session.dbdir_inode}, {"new_inode", current.dbdir_inode},
                                              {"content_match", true}, {"identity_changed", true}});
        }
    }

    if (!session.fsdb_file.empty()) {
        if (!current_fsdb_metadata(session, current)) {
            health.status = SessionHealthStatus::FsdbMissing;
            health.message = "FSDB path is missing, is not a regular file, or lacks metadata";
            xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.fsdb_missing", false,
                                             {{"fsdb", session.fsdb_file}});
            return health;
        }
        if (!fsdb_metadata_matches(session, current)) {
            bool identity_changed = xdebug_core::resource_identity_differs(session.fsdb_dev,
                                                                           session.fsdb_inode,
                                                                           current.fsdb_dev,
                                                                           current.fsdb_inode);
            health.status = SessionHealthStatus::FsdbChanged;
            health.message = "FSDB metadata changed since session was opened";
            xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.fsdb_changed", false,
                                             {{"fsdb", session.fsdb_file},
                                              {"old_mtime", session.fsdb_mtime}, {"new_mtime", current.fsdb_mtime},
                                              {"old_size", session.fsdb_size}, {"new_size", current.fsdb_size},
                                              {"old_dev", session.fsdb_dev}, {"new_dev", current.fsdb_dev},
                                              {"old_inode", session.fsdb_inode}, {"new_inode", current.fsdb_inode},
                                              {"identity_changed", identity_changed}});
            return health;
        }
    }

    if (is_local_session_host(session) &&
        !local_process_alive(session.server_pid)) {
        health.status = SessionHealthStatus::ProcessExited;
        health.message = "Server process is not running";
        xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.process_exited", false,
                                         {{"pid", session.server_pid}});
        return health;
    }

    if (!is_tcp_transport(session) && !is_file_transport(session) && access(session.socket_path.c_str(), F_OK) != 0) {
        health.status = SessionHealthStatus::SocketMissing;
        health.message = "Server socket file is missing";
        xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.socket_missing", false,
                                         {{"socket_path", session.socket_path}});
        return health;
    }

    if (!is_file_transport(session)) {
        int fd = connect_session_endpoint(session);
        if (fd < 0) {
            health.status = SessionHealthStatus::ConnectFailed;
            health.message = "Server socket exists but cannot be connected";
            xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.connect_failed", false,
                                             {{"transport", session.transport}, {"socket_path", session.socket_path},
                                              {"host", session.host}, {"port", session.port}});
            return health;
        }
        close(fd);
    }

    if (!ping_session_endpoint(session)) {
        health.status = SessionHealthStatus::PingFailed;
        health.message = "Server did not respond to PING";
        xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.ping_failed", false,
                                         {{"socket_path", session.socket_path}});
        return health;
    }

    health.healthy = true;
    health.status = SessionHealthStatus::Healthy;
    health.message = "Session is healthy";
    xdebug_core::log_lifecycle_event("engine", session_id, "diagnose.healthy", true,
                                     {{"pid", session.server_pid}, {"transport", session.transport}});
    return health;
}

bool SessionManager::is_session_alive(const std::string& session_id) {
    return diagnose_session(session_id).healthy;
}

std::string SessionManager::get_socket_path(const std::string& session_id) {
    char path[SOCK_PATH_LEN];
    get_sock_path(path, session_id);
    return std::string(path);
}

void SessionManager::cleanup() {
    debug_log("cleanup: begin");
    xdebug_core::log_lifecycle_event("engine", "adhoc", "cleanup.begin", true);
    std::vector<SessionInfo> sessions;
    SessionRegistryResult loaded =
        registry_->load_all(sessions);
    if (!loaded.ok()) {
        xdebug_core::log_lifecycle_event(
            "engine",
            "adhoc",
            "cleanup.registry_invalid",
            false,
            {{"message", loaded.message}});
        xdebug_core::log_lifecycle_event(
            "engine",
            "adhoc",
            "cleanup.end",
            false);
        return;
    }
    std::sort(
        sessions.begin(),
        sessions.end(),
        [](const SessionInfo& lhs, const SessionInfo& rhs) {
            return lhs.session_id < rhs.session_id;
        });
    bool all_ok = true;
    for (const auto& snapshot : sessions) {
        bool stale =
            snapshot.lifecycle_state != "active";
        if (!stale && is_local_session_host(snapshot)) {
            stale =
                !local_process_alive(snapshot.server_pid) ||
                !process_matches_session(snapshot);
        }
        if (!stale && !is_tcp_transport(snapshot) &&
            !is_file_transport(snapshot)) {
            stale =
                access(snapshot.socket_path.c_str(), F_OK) != 0;
        }
        if (!stale &&
            (is_tcp_transport(snapshot) ||
             is_file_transport(snapshot))) {
            stale =
                access(
                    xdebug_design_endpoint_path(
                        snapshot.session_id)
                        .c_str(),
                    F_OK) != 0;
        }
        if (!stale) continue;

        SessionCleanupPrecondition precondition;
        precondition.expected_generation =
            snapshot.generation;
        precondition.expected_lifecycle_state =
            snapshot.lifecycle_state;
        SessionCleanupResult cleanup_result =
            kill_session(
                snapshot.session_id,
                precondition);
        if (!cleanup_result.ok() &&
            cleanup_result.status !=
                SessionCleanupStatus::NotFound) {
            all_ok = false;
        }
    }
    debug_log("cleanup: done");
    xdebug_core::log_lifecycle_event(
        "engine",
        "adhoc",
        "cleanup.end",
        all_ok);
}

} // namespace xdebug_engine
