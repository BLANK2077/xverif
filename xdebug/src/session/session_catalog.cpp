#include "session/session_catalog.h"

#include "common/env_config.h"
#include "common/path_utils.h"
#include "session/session_registry_contract.h"

#include <algorithm>
#include <cerrno>
#include <dirent.h>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace xdebug {

namespace {

std::string canonical_registry_path() {
    std::string home = xdebug_core::env_raw_string("HOME");
    return (home.empty() ? xdebug_core::temporary_dir() : home) + "/.xdebug/engine/registry.json";
}

std::string canonical_sessions_dir() {
    std::string home = xdebug_core::env_raw_string("HOME");
    return (home.empty() ? xdebug_core::temporary_dir() : home) +
           "/.xdebug/engine/sessions";
}

std::string state_path(const std::string& id) {
    return canonical_sessions_dir() + "/" +
           xdebug_core::session_dir_name(id) + "/state.json";
}

SessionCatalogResult read_state(const std::string& path,
                                SessionRecord& record) {
    std::ifstream in(path.c_str());
    if (!in) {
        return access(path.c_str(), F_OK) != 0 && errno == ENOENT
            ? SessionCatalogResult(SessionCatalogStatus::NotFound,
                                   "SESSION_NOT_FOUND", "session not found")
            : SessionCatalogResult(SessionCatalogStatus::Invalid,
                                   "REGISTRY_INVALID", "cannot read per-session state");
    }
    try {
        const std::string text((std::istreambuf_iterator<char>(in)),
                               std::istreambuf_iterator<char>());
        xdebug_core::SessionRegistryJson value =
            xdebug_core::SessionRegistryJson::parse(text);
        xdebug_core::SessionInfo session;
        std::string error;
        if (!xdebug_core::session_registry_record_from_json(value, session, error)) {
            return {SessionCatalogStatus::Invalid, "REGISTRY_INVALID",
                    "per-session state is invalid: " + error};
        }
        record.id = session.session_id;
        record.lifecycle_state = session.lifecycle_state;
        record.daidir = session.dbdir_path;
        record.fsdb = session.fsdb_file;
        record.socket_path = session.socket_path;
        record.transport = session.transport;
        record.file_dir = session.file_dir;
        record.host = session.host;
        record.bind_host = session.bind_host;
        record.port = session.port;
        record.server_host = session.server_host;
        record.ownership_token_hash = session.ownership_token_hash;
        record.server_pid = static_cast<int>(session.server_pid);
        record.created_at = static_cast<long long>(session.created_at);
        record.last_active = static_cast<long long>(session.last_active);
        record.dbdir_mtime_ns = session.dbdir_mtime_ns;
        record.dbdir_size = session.dbdir_size;
        record.dbdir_dev = session.dbdir_dev;
        record.dbdir_inode = session.dbdir_inode;
        record.fsdb_mtime_ns = session.fsdb_mtime_ns;
        record.fsdb_size = session.fsdb_size;
        record.fsdb_dev = session.fsdb_dev;
        record.fsdb_inode = session.fsdb_inode;
        record.mode = !record.daidir.empty() && !record.fsdb.empty()
            ? "combined" : (!record.daidir.empty() ? "design" : "waveform");
        struct stat activity;
        const size_t slash = path.rfind('/');
        const std::string activity_path =
            path.substr(0, slash) + "/activity";
        if (stat(activity_path.c_str(), &activity) == 0 &&
            activity.st_mtime > record.last_active) {
            record.last_active = activity.st_mtime;
        }
        return {};
    } catch (const std::exception& exc) {
        return {SessionCatalogStatus::Invalid, "REGISTRY_INVALID",
                std::string("cannot parse per-session state: ") + exc.what()};
    }
}

bool fingerprint_is_zero(
    long long mtime_ns,
    long long size,
    unsigned long long dev,
    unsigned long long inode) {
    return mtime_ns == 0 && size == 0 && dev == 0 && inode == 0;
}

void validate_public_session_record(const SessionRecord& record) {
    if (!xdebug_core::is_valid_session_name(record.id))
        throw std::invalid_argument(
            "canonical session record has invalid session_id");

    const std::string expected_mode =
        !record.daidir.empty() && !record.fsdb.empty()
            ? "combined"
            : (!record.daidir.empty()
                   ? "design"
                   : (!record.fsdb.empty() ? "waveform" : ""));
    if (expected_mode.empty() || record.mode != expected_mode)
        throw std::invalid_argument(
            "canonical session record mode does not match its resources");
    if (record.lifecycle_state != "opening" &&
        record.lifecycle_state != "active" &&
        record.lifecycle_state != "cleanup_failed" &&
        record.lifecycle_state != "terminated_on_timeout") {
        throw std::invalid_argument(
            "canonical session record has invalid lifecycle_state");
    }
    if (record.daidir.empty() &&
        !fingerprint_is_zero(
            record.dbdir_mtime_ns,
            record.dbdir_size,
            record.dbdir_dev,
            record.dbdir_inode)) {
        throw std::invalid_argument(
            "canonical session record without daidir carries daidir metadata");
    }
    if (record.fsdb.empty() &&
        !fingerprint_is_zero(
            record.fsdb_mtime_ns,
            record.fsdb_size,
            record.fsdb_dev,
            record.fsdb_inode)) {
        throw std::invalid_argument(
            "canonical session record without fsdb carries fsdb metadata");
    }
    if (record.server_host.empty())
        throw std::invalid_argument(
            "canonical session record requires server_host");

    if (record.transport == "uds") {
        if (record.socket_path.empty() || !record.file_dir.empty() ||
            !record.host.empty() || !record.bind_host.empty() ||
            record.port != 0) {
            throw std::invalid_argument(
                "canonical uds session record has invalid endpoint fields");
        }
    } else if (record.transport == "tcp") {
        const bool active_port = record.port > 0 && record.port <= 65535;
        const bool pending_ephemeral_port =
            record.lifecycle_state != "active" && record.port == 0;
        if (!record.socket_path.empty() || !record.file_dir.empty() ||
            record.host.empty() || record.bind_host.empty() ||
            (!active_port && !pending_ephemeral_port)) {
            throw std::invalid_argument(
                "canonical tcp session record has invalid endpoint fields");
        }
    } else if (record.transport == "file") {
        if (!record.socket_path.empty() || record.file_dir.empty() ||
            !record.host.empty() || !record.bind_host.empty() ||
            record.port != 0) {
            throw std::invalid_argument(
                "canonical file session record has invalid endpoint fields");
        }
    } else {
        throw std::invalid_argument(
            "canonical session record has invalid transport");
    }

    if (record.server_pid < 0 || record.created_at < 0 ||
        record.last_active < 0 || record.dbdir_mtime_ns < 0 ||
        record.dbdir_size < 0 || record.fsdb_mtime_ns < 0 ||
        record.fsdb_size < 0) {
        throw std::invalid_argument(
            "canonical session record has negative public metadata");
    }
    if (record.lifecycle_state == "active" && record.server_pid <= 0) {
        throw std::invalid_argument(
            "canonical active session record requires server_pid");
    }
}

} // namespace

SessionCatalog::SessionCatalog() : path_(canonical_registry_path()) {}

SessionCatalogResult SessionCatalog::read_all(
    std::vector<SessionRecord>& records) const {
    records.clear();
    DIR* directory = opendir(canonical_sessions_dir().c_str());
    if (!directory)
        return errno == ENOENT ? SessionCatalogResult()
                              : SessionCatalogResult(SessionCatalogStatus::Invalid,
                                                     "REGISTRY_INVALID",
                                                     "cannot enumerate session states");
    errno = 0;
    while (dirent* entry = readdir(directory)) {
        const std::string name = entry->d_name;
        if (name == "." || name == "..") continue;
        SessionRecord record;
        const SessionCatalogResult read = read_state(
            canonical_sessions_dir() + "/" + name + "/state.json", record);
        if (!read.ok()) {
            errno = 0;
            continue;
        }
        records.push_back(record);
        errno = 0;
    }
    const int read_errno = errno;
    const bool closed = closedir(directory) == 0;
    if (read_errno != 0 || !closed) {
        records.clear();
        return {SessionCatalogStatus::Invalid, "REGISTRY_INVALID",
                "cannot complete session state enumeration"};
    }
    std::sort(records.begin(), records.end(),
              [](const SessionRecord& lhs, const SessionRecord& rhs) {
                  return lhs.id < rhs.id;
              });
    return {};
}

SessionCatalogResult SessionCatalog::get(
    const std::string& id,
    SessionRecord& record) const {
    SessionCatalogResult result = read_state(state_path(id), record);
    if (result.status == SessionCatalogStatus::NotFound)
        result.message = "session not found: " + id;
    if (result.ok() && record.id != id)
        return {SessionCatalogStatus::Invalid, "REGISTRY_INVALID",
                "per-session state identity does not match its directory"};
    return result;
}

SessionCatalogResult SessionCatalog::list(
    std::vector<SessionRecord>& records) const {
    return read_all(records);
}

Json session_record_json(const SessionRecord& record) {
    validate_public_session_record(record);
    Json item = {
        {"session_id", record.id},
        {"mode", record.mode},
        {"transport", record.transport},
        {"server_host", record.server_host}
    };
    if (!record.daidir.empty()) item["daidir"] = record.daidir;
    if (!record.fsdb.empty()) item["fsdb"] = record.fsdb;
    if (!record.socket_path.empty()) item["socket_path"] = record.socket_path;
    if (!record.file_dir.empty()) item["file_dir"] = record.file_dir;
    if (!record.host.empty()) item["host"] = record.host;
    if (!record.bind_host.empty()) item["bind_host"] = record.bind_host;
    if (record.port > 0) item["port"] = record.port;
    if (record.server_pid > 0) item["server_pid"] = record.server_pid;
    if (record.created_at > 0) item["created_at"] = record.created_at;
    if (record.last_active > 0) item["last_active"] = record.last_active;
    if (record.dbdir_mtime_ns)
        item["daidir_mtime_ns"] = record.dbdir_mtime_ns;
    if (record.dbdir_size) item["daidir_size"] = record.dbdir_size;
    if (record.dbdir_dev) item["daidir_dev"] = record.dbdir_dev;
    if (record.dbdir_inode) item["daidir_inode"] = record.dbdir_inode;
    if (record.fsdb_mtime_ns)
        item["fsdb_mtime_ns"] = record.fsdb_mtime_ns;
    if (record.fsdb_size) item["fsdb_size"] = record.fsdb_size;
    if (record.fsdb_dev) item["fsdb_dev"] = record.fsdb_dev;
    if (record.fsdb_inode) item["fsdb_inode"] = record.fsdb_inode;
    return item;
}

Json session_list_record_json(
    const SessionRecord& record,
    bool verbose,
    bool expired,
    const std::string& recommended_action) {
    validate_public_session_record(record);
    Json item = verbose ? session_record_json(record) : Json{
        {"session_id", record.id},
        {"mode", record.mode},
        {"transport", record.transport}
    };
    item["lifecycle_state"] = record.lifecycle_state;
    item["expired"] = expired;
    item["recommended_action"] = recommended_action;
    item["last_active"] = record.last_active;
    return item;
}

} // namespace xdebug
