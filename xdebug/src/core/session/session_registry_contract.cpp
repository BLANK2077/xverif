#include "session/session_registry_contract.h"

#include "common/path_utils.h"

#include <cstdint>
#include <exception>
#include <limits>
#include <set>

namespace xdebug_core {
namespace {

const std::set<std::string>& record_fields() {
    static const std::set<std::string> fields = {
        "session_id", "generation", "lifecycle_state",
        "transport", "socket_path", "file_dir", "host",
        "bind_host", "port", "server_host", "auth_token",
        "ownership_token_hash", "dbdir_path",
        "fsdb_file", "server_pid", "created_at", "last_active",
        "dbdir_mtime", "dbdir_size", "dbdir_dev", "dbdir_inode",
        "fsdb_mtime", "fsdb_size", "fsdb_dev", "fsdb_inode"
    };
    return fields;
}

bool fail(std::string& error, const std::string& message) {
    error = message;
    return false;
}

bool read_nonnegative_u64(
    const SessionRegistryJson& value,
    uint64_t& output) {
    try {
        if (value.is_number_unsigned()) {
            output = value.get<uint64_t>();
            return true;
        }
        if (!value.is_number_integer()) return false;
        const int64_t signed_value = value.get<int64_t>();
        if (signed_value < 0) return false;
        output = static_cast<uint64_t>(signed_value);
        return true;
    } catch (const std::exception&) {
        return false;
    }
}

template <typename T>
bool read_bounded_nonnegative(
    const SessionRegistryJson& value,
    T& output) {
    uint64_t parsed = 0;
    if (!read_nonnegative_u64(value, parsed)) return false;
    const uint64_t maximum =
        static_cast<uint64_t>(std::numeric_limits<T>::max());
    if (parsed > maximum) return false;
    output = static_cast<T>(parsed);
    return true;
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

bool valid_optional_sha256(const std::string& digest) {
    if (digest.empty()) return true;
    if (digest.size() != 64) return false;
    for (const char c : digest) {
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool resource_fingerprint_is_zero(
    long mtime,
    long long size,
    unsigned long long dev,
    unsigned long long inode) {
    return mtime == 0 && size == 0 && dev == 0 && inode == 0;
}

bool validate_resource_invariants(
    const SessionInfo& session,
    std::string& error) {
    if (session.dbdir_path.empty() && session.fsdb_file.empty())
        return fail(error, "session requires dbdir_path or fsdb_file");
    if (session.dbdir_path.empty() &&
        !resource_fingerprint_is_zero(
            session.dbdir_mtime,
            session.dbdir_size,
            session.dbdir_dev,
            session.dbdir_inode)) {
        return fail(
            error,
            "session without dbdir_path must not carry dbdir fingerprint fields");
    }
    if (session.fsdb_file.empty() &&
        !resource_fingerprint_is_zero(
            session.fsdb_mtime,
            session.fsdb_size,
            session.fsdb_dev,
            session.fsdb_inode)) {
        return fail(
            error,
            "session without fsdb_file must not carry fsdb fingerprint fields");
    }
    return true;
}

bool validate_transport_invariants(
    const SessionInfo& session,
    std::string& error) {
    if (session.server_host.empty())
        return fail(error, "session requires nonempty server_host");

    if (session.transport == "uds") {
        if (session.socket_path.empty())
            return fail(error, "uds session requires socket_path");
        if (!session.file_dir.empty() || !session.host.empty() ||
            !session.bind_host.empty() || session.port != 0 ||
            !session.auth_token.empty()) {
            return fail(
                error,
                "uds session forbids file_dir, host, bind_host, port, and auth_token");
        }
        return true;
    }

    if (session.transport == "tcp") {
        const bool active_port =
            session.port > 0 && session.port <= 65535;
        const bool pending_ephemeral_port =
            session.lifecycle_state != "active" &&
            session.port == 0;
        if (session.host.empty() || session.bind_host.empty() ||
            session.auth_token.empty() ||
            (!active_port && !pending_ephemeral_port)) {
            return fail(
                error,
                "tcp session requires host, bind_host, auth_token, and an active port in 1..65535");
        }
        if (!session.socket_path.empty() || !session.file_dir.empty()) {
            return fail(
                error,
                "tcp session forbids socket_path and file_dir");
        }
        return true;
    }

    if (session.transport == "file") {
        if (session.file_dir.empty())
            return fail(error, "file session requires file_dir");
        if (!session.socket_path.empty() || !session.host.empty() ||
            !session.bind_host.empty() || session.port != 0 ||
            !session.auth_token.empty()) {
            return fail(
                error,
                "file session forbids socket_path, host, bind_host, port, and auth_token");
        }
        return true;
    }

    return fail(error, "transport must be uds, tcp, or file");
}

bool validate_lifecycle_invariants(
    const SessionInfo& session,
    std::string& error) {
    if (!valid_generation(session.generation))
        return fail(
            error,
            "generation must be 64 lowercase hexadecimal characters");
    if (session.lifecycle_state != "opening" &&
        session.lifecycle_state != "active" &&
        session.lifecycle_state != "cleanup_failed") {
        return fail(
            error,
            "lifecycle_state must be opening, active, or cleanup_failed");
    }
    if (session.lifecycle_state == "active" &&
        session.server_pid <= 0) {
        return fail(
            error,
            "active session requires a positive server_pid");
    }
    return true;
}

} // namespace

SessionRegistryJson session_registry_record_to_json(
    const SessionInfo& session) {
    return SessionRegistryJson{
        {"session_id", session.session_id},
        {"generation", session.generation},
        {"lifecycle_state", session.lifecycle_state},
        {"transport", session.transport},
        {"socket_path", session.socket_path},
        {"file_dir", session.file_dir},
        {"host", session.host},
        {"bind_host", session.bind_host},
        {"port", session.port},
        {"server_host", session.server_host},
        {"auth_token", session.auth_token},
        {"ownership_token_hash", session.ownership_token_hash},
        {"dbdir_path", session.dbdir_path},
        {"fsdb_file", session.fsdb_file},
        {"server_pid", session.server_pid},
        {"created_at", static_cast<long long>(session.created_at)},
        {"last_active", static_cast<long long>(session.last_active)},
        {"dbdir_mtime", session.dbdir_mtime},
        {"dbdir_size", session.dbdir_size},
        {"dbdir_dev", session.dbdir_dev},
        {"dbdir_inode", session.dbdir_inode},
        {"fsdb_mtime", session.fsdb_mtime},
        {"fsdb_size", session.fsdb_size},
        {"fsdb_dev", session.fsdb_dev},
        {"fsdb_inode", session.fsdb_inode}
    };
}

bool session_registry_record_from_json(
    const SessionRegistryJson& value,
    SessionInfo& session,
    std::string& error) {
    if (!value.is_object())
        return fail(error, "session record must be an object");
    if (value.size() != record_fields().size())
        return fail(error, "session record fields do not match schema version 2");
    for (const auto& field : record_fields()) {
        if (!value.contains(field))
            return fail(error, "session record is missing field: " + field);
    }
    for (const char* field : {
             "session_id", "generation", "lifecycle_state",
             "transport", "socket_path", "file_dir", "host",
             "bind_host", "server_host", "auth_token",
             "ownership_token_hash", "dbdir_path",
             "fsdb_file"}) {
        if (!value[field].is_string())
            return fail(error, std::string("session field must be string: ") + field);
    }
    try {
        session.session_id = value["session_id"].get<std::string>();
        session.generation = value["generation"].get<std::string>();
        session.lifecycle_state =
            value["lifecycle_state"].get<std::string>();
        session.transport = value["transport"].get<std::string>();
        session.socket_path = value["socket_path"].get<std::string>();
        session.file_dir = value["file_dir"].get<std::string>();
        session.host = value["host"].get<std::string>();
        session.bind_host = value["bind_host"].get<std::string>();
        session.server_host = value["server_host"].get<std::string>();
        session.auth_token = value["auth_token"].get<std::string>();
        session.ownership_token_hash =
            value["ownership_token_hash"].get<std::string>();
        session.dbdir_path = value["dbdir_path"].get<std::string>();
        session.fsdb_file = value["fsdb_file"].get<std::string>();
    } catch (const std::exception& exc) {
        return fail(error, std::string("session field is out of range: ") + exc.what());
    }
    if (!read_bounded_nonnegative(value["port"], session.port) ||
        session.port > 65535)
        return fail(error, "session port must be in range 0..65535");
    if (!read_bounded_nonnegative(
            value["server_pid"], session.server_pid))
        return fail(error, "session server_pid is out of range");
    if (!read_bounded_nonnegative(
            value["created_at"], session.created_at))
        return fail(error, "session created_at is out of range");
    if (!read_bounded_nonnegative(
            value["last_active"], session.last_active))
        return fail(error, "session last_active is out of range");
    if (!read_bounded_nonnegative(
            value["dbdir_mtime"], session.dbdir_mtime))
        return fail(error, "session dbdir_mtime is out of range");
    if (!read_bounded_nonnegative(
            value["dbdir_size"], session.dbdir_size))
        return fail(error, "session dbdir_size is out of range");
    if (!read_bounded_nonnegative(
            value["dbdir_dev"], session.dbdir_dev))
        return fail(error, "session dbdir_dev is out of range");
    if (!read_bounded_nonnegative(
            value["dbdir_inode"], session.dbdir_inode))
        return fail(error, "session dbdir_inode is out of range");
    if (!read_bounded_nonnegative(
            value["fsdb_mtime"], session.fsdb_mtime))
        return fail(error, "session fsdb_mtime is out of range");
    if (!read_bounded_nonnegative(
            value["fsdb_size"], session.fsdb_size))
        return fail(error, "session fsdb_size is out of range");
    if (!read_bounded_nonnegative(
            value["fsdb_dev"], session.fsdb_dev))
        return fail(error, "session fsdb_dev is out of range");
    if (!read_bounded_nonnegative(
            value["fsdb_inode"], session.fsdb_inode))
        return fail(error, "session fsdb_inode is out of range");

    if (!is_valid_session_name(session.session_id))
        return fail(error, "session_id is invalid");
    if (!valid_optional_sha256(session.ownership_token_hash)) {
        return fail(
            error,
            "ownership_token_hash must be empty or 64 lowercase hexadecimal characters");
    }
    if (!validate_lifecycle_invariants(session, error)) return false;
    if (!validate_resource_invariants(session, error)) return false;
    if (!validate_transport_invariants(session, error)) return false;
    error.clear();
    return true;
}

bool session_registry_document_from_json(
    const SessionRegistryJson& value,
    std::vector<SessionInfo>& sessions,
    std::string& error) {
    sessions.clear();
    uint64_t version = 0;
    if (!value.is_object() || value.size() != 2 ||
        !value.contains("version") ||
        !read_nonnegative_u64(value["version"], version) ||
        version != 2 ||
        !value.contains("sessions") || !value["sessions"].is_array()) {
        return fail(error, "registry must match schema version 2");
    }
    std::set<std::string> ids;
    for (size_t index = 0; index < value["sessions"].size(); ++index) {
        SessionInfo session;
        std::string record_error;
        if (!session_registry_record_from_json(
                value["sessions"][index], session, record_error)) {
            return fail(error, "sessions[" + std::to_string(index) +
                "]: " + record_error);
        }
        if (!ids.insert(session.session_id).second)
            return fail(error, "duplicate session_id: " + session.session_id);
        sessions.push_back(session);
    }
    error.clear();
    return true;
}

bool session_registry_document_to_json(
    const std::vector<SessionInfo>& sessions,
    SessionRegistryJson& value,
    std::string& error) {
    value = {{"version", 2}, {"sessions", SessionRegistryJson::array()}};
    std::set<std::string> ids;
    for (const auto& session : sessions) {
        if (!ids.insert(session.session_id).second)
            return fail(error, "duplicate session_id: " + session.session_id);
        SessionRegistryJson record = session_registry_record_to_json(session);
        SessionInfo verified;
        std::string record_error;
        if (!session_registry_record_from_json(record, verified, record_error))
            return fail(error, "session " + session.session_id + ": " + record_error);
        value["sessions"].push_back(std::move(record));
    }
    error.clear();
    return true;
}

} // namespace xdebug_core
