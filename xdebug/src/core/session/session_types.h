#pragma once

#include <ctime>
#include <string>
#include <vector>
#include <sys/types.h>

namespace xdebug_core {

enum class DatabaseKind {
    Fsdb,
    Daidir,
    Combined
};

struct Fingerprint {
    long mtime;
    long long size;
    unsigned long long dev;
    unsigned long long inode;

    Fingerprint();
};

struct DatabaseRef {
    DatabaseKind kind;
    std::string canonical_path;
    std::vector<std::string> original_args;

    DatabaseRef();
};

struct SessionInfo {
    // Common fields
    std::string session_id;
    // Opaque identity of one incarnation of session_id.  Every registry
    // mutation and artifact cleanup is conditional on this value.
    std::string generation;
    // Strict registry lifecycle state: opening, active, cleanup_failed, or
    // terminated_on_timeout.  The latter is a diagnostic tombstone and must
    // never be reused as a live NPI context.
    std::string lifecycle_state;
    std::string transport;
    std::string socket_path;
    std::string file_dir;
    std::string host;
    std::string bind_host;
    int port = 0;
    std::string server_host;
    std::string auth_token;
    // Private proof used only to authorize conditional lifecycle cleanup.
    // The raw ownership token is never persisted.
    std::string ownership_token_hash;
    pid_t server_pid = 0;
    time_t created_at = 0;
    time_t last_active = 0;

    // Design resource fields
    std::string dbdir_path;
    long dbdir_mtime = 0;
    long long dbdir_size = 0;
    unsigned long long dbdir_dev = 0;
    unsigned long long dbdir_inode = 0;

    // Waveform resource fields
    std::string fsdb_file;
    long fsdb_mtime = 0;
    long long fsdb_size = 0;
    unsigned long long fsdb_dev = 0;
    unsigned long long fsdb_inode = 0;

    DatabaseKind database_kind() const {
        if (!dbdir_path.empty() && !fsdb_file.empty()) return DatabaseKind::Combined;
        return dbdir_path.empty() ? DatabaseKind::Fsdb : DatabaseKind::Daidir;
    }
};

const char* database_kind_name(DatabaseKind kind);
bool resource_content_matches(long expected_mtime,
                              long long expected_size,
                              long current_mtime,
                              long long current_size);
bool resource_identity_differs(unsigned long long expected_dev,
                               unsigned long long expected_inode,
                               unsigned long long current_dev,
                               unsigned long long current_inode);

} // namespace xdebug_core
