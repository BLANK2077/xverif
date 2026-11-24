#pragma once

#include <json.hpp>

#include <map>
#include <string>
#include <utility>
#include <vector>

namespace xcov {

/// Loads the canonical JSON schemas and validates requests/responses.
///
/// The Python implementation is the reference for error wording; this class
/// mirrors the same keyword subset (Draft-7 compatible) used by schemas.py.
class SchemaCatalog {
public:
    static const SchemaCatalog& instance();

    bool has_action(const std::string& action) const;
    std::vector<std::string> action_names() const;

    const nlohmann::json& request_schema(const std::string& action) const;
    const nlohmann::json& response_schema(const std::string& action) const;
    const nlohmann::json& run_manifest_schema() const { return run_manifest_; }
    const nlohmann::json& stdio_quit_schema() const { return stdio_quit_; }

    void validate_request(const nlohmann::json& req) const;
    void validate_stdio_request(const nlohmann::json& req) const;
    void validate_response(const std::string& action, const nlohmann::json& rsp) const;
    void validate_run_manifest(const nlohmann::json& doc) const;

    /// Used by the `schema` action response validation path.
    static bool is_schema_node(const nlohmann::json& value);

private:
    SchemaCatalog();

    std::map<std::string, std::pair<nlohmann::json, nlohmann::json>> schemas_;
    nlohmann::json run_manifest_;
    nlohmann::json stdio_quit_;
};

/// Validate one JSON value against one schema node; throws Error(SCHEMA_INVALID).
void validate_node(const nlohmann::json& value,
                   const nlohmann::json& schema,
                   const std::string& path);

/// Same but throws with a caller-selected error code.
void validate_node_as(const nlohmann::json& value,
                      const nlohmann::json& schema,
                      const std::string& path,
                      const std::string& code);

} // namespace xcov
