#include "session/session_catalog.h"

#include "common/env_config.h"
#include "common/path_utils.h"
#include "session/session_registry_contract.h"

#include <cerrno>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <unistd.h>

namespace xdebug {

namespace {

std::string canonical_registry_path() {
    std::string home = xdebug_core::env_raw_string("HOME");
    return (home.empty() ? xdebug_core::temporary_dir() : home) + "/.xdebug/engine/registry.json";
}

bool fingerprint_is_zero(
    long mtime,
    long long size,
    unsigned long long dev,
    unsigned long long inode) {
    return mtime == 0 && size == 0 && dev == 0 && inode == 0;
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
    if (record.daidir.empty() &&
        !fingerprint_is_zero(
            record.dbdir_mtime,
            record.dbdir_size,
            record.dbdir_dev,
            record.dbdir_inode)) {
        throw std::invalid_argument(
            "canonical session record without daidir carries daidir metadata");
    }
    if (record.fsdb.empty() &&
        !fingerprint_is_zero(
            record.fsdb_mtime,
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
        if (!record.socket_path.empty() || !record.file_dir.empty() ||
            record.host.empty() || record.bind_host.empty() ||
            record.port <= 0 || record.port > 65535) {
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
        record.last_active < 0 || record.dbdir_mtime < 0 ||
        record.dbdir_size < 0 || record.fsdb_mtime < 0 ||
        record.fsdb_size < 0) {
        throw std::invalid_argument(
            "canonical session record has negative public metadata");
    }
}

} // namespace

SessionCatalog::SessionCatalog() : path_(canonical_registry_path()) {}

SessionCatalogResult SessionCatalog::read_all(
    std::vector<SessionRecord>& records) const {
    records.clear();
    std::ifstream in(path_.c_str());
    if (!in) {
        if (access(path_.c_str(), F_OK) != 0 && errno == ENOENT)
            return {};
        return {
            SessionCatalogStatus::Invalid,
            "REGISTRY_INVALID",
            "cannot read canonical session registry"
        };
    }
    try {
        const std::string text(
            (std::istreambuf_iterator<char>(in)),
            std::istreambuf_iterator<char>());
        xdebug_core::SessionRegistryJson root =
            xdebug_core::SessionRegistryJson::parse(text);
        std::vector<xdebug_core::SessionInfo> sessions;
        std::string error;
        if (!xdebug_core::session_registry_document_from_json(
                root, sessions, error)) {
            return {
                SessionCatalogStatus::Invalid,
                "REGISTRY_INVALID",
                "canonical session registry is invalid: " + error
            };
        }
        for (const auto& session : sessions) {
            SessionRecord record;
            record.id = session.session_id;
            record.daidir = session.dbdir_path;
            record.fsdb = session.fsdb_file;
            record.socket_path = session.socket_path;
            record.transport = session.transport;
            record.file_dir = session.file_dir;
            record.host = session.host;
            record.bind_host = session.bind_host;
            record.port = session.port;
            record.server_host = session.server_host;
            record.ownership_token_hash =
                session.ownership_token_hash;
            record.server_pid = static_cast<int>(session.server_pid);
            record.created_at = static_cast<long long>(session.created_at);
            record.last_active = static_cast<long long>(session.last_active);
            record.dbdir_mtime = session.dbdir_mtime;
            record.dbdir_size = session.dbdir_size;
            record.dbdir_dev = session.dbdir_dev;
            record.dbdir_inode = session.dbdir_inode;
            record.fsdb_mtime = session.fsdb_mtime;
            record.fsdb_size = session.fsdb_size;
            record.fsdb_dev = session.fsdb_dev;
            record.fsdb_inode = session.fsdb_inode;
            record.mode = !record.daidir.empty() && !record.fsdb.empty()
                ? "combined"
                : (!record.daidir.empty() ? "design" : "waveform");
            records.push_back(std::move(record));
        }
        return {};
    } catch (const std::exception& exc) {
        return {
            SessionCatalogStatus::Invalid,
            "REGISTRY_INVALID",
            std::string("cannot parse canonical session registry: ") + exc.what()
        };
    }
}

SessionCatalogResult SessionCatalog::get(
    const std::string& id,
    SessionRecord& record) const {
    std::vector<SessionRecord> records;
    SessionCatalogResult result = read_all(records);
    if (!result.ok()) return result;
    for (const auto& candidate : records) {
        if (candidate.id != id) continue;
        record = candidate;
        return {};
    }
    return {
        SessionCatalogStatus::NotFound,
        "SESSION_NOT_FOUND",
        "session not found: " + id
    };
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
    if (record.dbdir_mtime) item["daidir_mtime"] = record.dbdir_mtime;
    if (record.dbdir_size) item["daidir_size"] = record.dbdir_size;
    if (record.dbdir_dev) item["daidir_dev"] = record.dbdir_dev;
    if (record.dbdir_inode) item["daidir_inode"] = record.dbdir_inode;
    if (record.fsdb_mtime) item["fsdb_mtime"] = record.fsdb_mtime;
    if (record.fsdb_size) item["fsdb_size"] = record.fsdb_size;
    if (record.fsdb_dev) item["fsdb_dev"] = record.fsdb_dev;
    if (record.fsdb_inode) item["fsdb_inode"] = record.fsdb_inode;
    return item;
}

} // namespace xdebug
