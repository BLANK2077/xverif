#pragma once

#include "api/json_types.h"

#include <string>
#include <utility>
#include <vector>

namespace xdebug {

struct SessionRecord {
    std::string id;
    // Canonical registry lifecycle state.  Frontend discovery must preserve
    // this fact instead of flattening opening/active/cleanup_failed records.
    std::string lifecycle_state;
    std::string mode;
    std::string daidir;
    std::string fsdb;
    std::string socket_path;
    std::string transport;
    std::string file_dir;
    std::string host;
    std::string bind_host;
    int port = 0;
    std::string server_host;
    // Internal-only conditional-cleanup match digest.  It is not an
    // authorization secret, and public session JSON must never expose it.
    std::string ownership_token_hash;
    int server_pid = 0;
    long long created_at = 0;
    long long last_active = 0;
    long long dbdir_mtime_ns = 0;
    long long dbdir_size = 0;
    unsigned long long dbdir_dev = 0;
    unsigned long long dbdir_inode = 0;
    long long fsdb_mtime_ns = 0;
    long long fsdb_size = 0;
    unsigned long long fsdb_dev = 0;
    unsigned long long fsdb_inode = 0;
};

enum class SessionCatalogStatus {
    Ok,
    NotFound,
    Invalid
};

struct SessionCatalogResult {
    SessionCatalogStatus status = SessionCatalogStatus::Ok;
    std::string code;
    std::string message;

    SessionCatalogResult() = default;
    SessionCatalogResult(
        SessionCatalogStatus result_status,
        std::string result_code,
        std::string result_message)
        : status(result_status),
          code(std::move(result_code)),
          message(std::move(result_message)) {}

    bool ok() const { return status == SessionCatalogStatus::Ok; }
};

// Read-only view of the canonical engine registry.
// Session lifecycle mutations are owned by the engine SessionRegistry.
class SessionCatalog {
public:
    SessionCatalog();

    SessionCatalogResult get(
        const std::string& id,
        SessionRecord& record) const;
    SessionCatalogResult list(
        std::vector<SessionRecord>& records) const;

private:
    std::string path_;
    SessionCatalogResult read_all(
        std::vector<SessionRecord>& records) const;
};

Json session_record_json(const SessionRecord& record);
Json session_list_record_json(
    const SessionRecord& record,
    bool verbose,
    bool expired,
    const std::string& recommended_action);

} // namespace xdebug
