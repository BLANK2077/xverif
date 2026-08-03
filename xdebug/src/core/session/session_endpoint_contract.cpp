#include "session/session_endpoint_contract.h"

#include "common/path_utils.h"

#include <exception>
#include <set>
#include <utility>

namespace xdebug_core {
namespace {

bool fail(std::string& error, const std::string& message) {
    error = message;
    return false;
}

bool has_exact_fields(
    const SessionEndpointJson& value,
    const std::set<std::string>& fields) {
    if (!value.is_object() || value.size() != fields.size()) return false;
    for (const auto& field : fields) {
        if (!value.contains(field)) return false;
    }
    return true;
}

bool require_nonempty_string(
    const SessionEndpointJson& value,
    const char* field,
    std::string& output,
    std::string& error) {
    if (!value[field].is_string() || value[field].get_ref<const std::string&>().empty())
        return fail(error, std::string("endpoint field must be a nonempty string: ") + field);
    output = value[field].get<std::string>();
    return true;
}

bool validate_common(
    const SessionInfo& endpoint,
    std::string& error) {
    if (!is_valid_session_name(endpoint.session_id))
        return fail(error, "endpoint session_id is invalid");
    if (endpoint.server_host.empty())
        return fail(error, "endpoint server_host must be nonempty");
    return true;
}

}  // namespace

bool session_endpoint_document_to_json(
    const SessionInfo& endpoint,
    SessionEndpointJson& value,
    std::string& error) {
    if (!validate_common(endpoint, error)) return false;

    SessionEndpointJson fields;
    if (endpoint.transport == "uds") {
        if (endpoint.socket_path.empty())
            return fail(error, "uds endpoint requires socket_path");
        fields = {
            {"transport", "uds"},
            {"socket_path", endpoint.socket_path},
            {"server_host", endpoint.server_host},
        };
    } else if (endpoint.transport == "tcp") {
        if (endpoint.host.empty() || endpoint.bind_host.empty() ||
            endpoint.auth_token.empty() || endpoint.port <= 0 ||
            endpoint.port > 65535) {
            return fail(
                error,
                "tcp endpoint requires host, bind_host, auth_token, and port in 1..65535");
        }
        fields = {
            {"transport", "tcp"},
            {"host", endpoint.host},
            {"bind_host", endpoint.bind_host},
            {"port", endpoint.port},
            {"server_host", endpoint.server_host},
            {"auth_token", endpoint.auth_token},
        };
    } else if (endpoint.transport == "file") {
        if (endpoint.file_dir.empty())
            return fail(error, "file endpoint requires file_dir");
        fields = {
            {"transport", "file"},
            {"file_dir", endpoint.file_dir},
            {"server_host", endpoint.server_host},
        };
    } else {
        return fail(error, "endpoint transport must be uds, tcp, or file");
    }

    value = {{"version", 1}, {"endpoint", std::move(fields)}};
    error.clear();
    return true;
}

bool session_endpoint_document_from_json(
    const SessionEndpointJson& value,
    const std::string& expected_session_id,
    SessionInfo& endpoint,
    std::string& error) {
    if (!is_valid_session_name(expected_session_id))
        return fail(error, "expected endpoint session_id is invalid");
    if (!has_exact_fields(value, {"version", "endpoint"}) ||
        !value["version"].is_number_integer() ||
        value["version"].get<int>() != 1 ||
        !value["endpoint"].is_object()) {
        return fail(error, "endpoint document must match schema version 1");
    }

    const SessionEndpointJson& fields = value["endpoint"];
    if (!fields.contains("transport") || !fields["transport"].is_string())
        return fail(error, "endpoint transport must be a string");

    SessionInfo parsed;
    parsed.session_id = expected_session_id;
    parsed.transport = fields["transport"].get<std::string>();

    if (parsed.transport == "uds") {
        if (!has_exact_fields(fields, {"transport", "socket_path", "server_host"}))
            return fail(error, "uds endpoint fields do not match schema version 1");
        if (!require_nonempty_string(
                fields, "socket_path", parsed.socket_path, error) ||
            !require_nonempty_string(
                fields, "server_host", parsed.server_host, error)) {
            return false;
        }
    } else if (parsed.transport == "tcp") {
        if (!has_exact_fields(
                fields,
                {"transport", "host", "bind_host", "port", "server_host", "auth_token"})) {
            return fail(error, "tcp endpoint fields do not match schema version 1");
        }
        if (!require_nonempty_string(fields, "host", parsed.host, error) ||
            !require_nonempty_string(fields, "bind_host", parsed.bind_host, error) ||
            !require_nonempty_string(
                fields, "server_host", parsed.server_host, error) ||
            !require_nonempty_string(
                fields, "auth_token", parsed.auth_token, error)) {
            return false;
        }
        if (!fields["port"].is_number_integer()) {
            return fail(error, "endpoint port must be an integer in 1..65535");
        }
        try {
            parsed.port = fields["port"].get<int>();
        } catch (const std::exception&) {
            return fail(error, "endpoint port must be an integer in 1..65535");
        }
        if (parsed.port <= 0 || parsed.port > 65535)
            return fail(error, "endpoint port must be an integer in 1..65535");
    } else if (parsed.transport == "file") {
        if (!has_exact_fields(fields, {"transport", "file_dir", "server_host"}))
            return fail(error, "file endpoint fields do not match schema version 1");
        if (!require_nonempty_string(fields, "file_dir", parsed.file_dir, error) ||
            !require_nonempty_string(
                fields, "server_host", parsed.server_host, error)) {
            return false;
        }
    } else {
        return fail(error, "endpoint transport must be uds, tcp, or file");
    }

    endpoint = std::move(parsed);
    error.clear();
    return true;
}

}  // namespace xdebug_core
