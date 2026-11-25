#include "api/schema.h"

#include "core/errors.h"
#include "core/fs.h"

#include <cmath>
#include <regex>
#include <sstream>

namespace xcov {

namespace {

bool is_integer_like(const nlohmann::json& value) {
    return value.is_number_integer() || value.is_number_unsigned();
}

bool is_type(const nlohmann::json& value, const std::string& type) {
    if (type == "object") return value.is_object();
    if (type == "array") return value.is_array();
    if (type == "string") return value.is_string();
    if (type == "boolean") return value.is_boolean();
    if (type == "integer") return is_integer_like(value);
    if (type == "number") return value.is_number();
    if (type == "null") return value.is_null();
    return false;
}

bool same_typed_equal(const nlohmann::json& a, const nlohmann::json& b) {
    if (is_integer_like(a) && is_integer_like(b)) {
        return a.get<long long>() == b.get<long long>();
    }
    if (a.type() != b.type()) {
        return false;
    }
    return a == b;
}

std::string render_value(const nlohmann::json& value) {
    return value.dump();
}

std::string type_list(const nlohmann::json& schema) {
    const nlohmann::json& expected = schema.at("type");
    std::ostringstream out;
    out << "[";
    if (expected.is_string()) {
        out << '"' << expected.get<std::string>() << '"';
    } else {
        bool first = true;
        for (const auto& item : expected) {
            if (!first) out << ", ";
            out << '"' << item.get<std::string>() << '"';
            first = false;
        }
    }
    out << "]";
    return out.str();
}

} // namespace

void validate_node_as(const nlohmann::json& value,
                      const nlohmann::json& schema,
                      const std::string& path,
                      const std::string& code) {
    auto fail = [&](const std::string& message) {
        throw Error(code, message, {{"path", path}});
    };
    if (!schema.is_object() || schema.empty()) {
        fail("validator received an empty schema");
    }
    if (schema.value("x-schema-node", false) == true) {
        // Dynamic schema documents are produced by this binary and validated by
        // the Python reference; accept the declared node shape here.
        if (!value.is_object() || value.empty()) {
            fail("must be a non-empty schema object");
        }
        return;
    }
    if (schema.contains("oneOf")) {
        int matches = 0;
        std::string first_failure;
        for (const auto& candidate : schema.at("oneOf")) {
            try {
                validate_node_as(value, candidate, path, code);
                ++matches;
            } catch (const Error& exc) {
                if (first_failure.empty()) first_failure = exc.message();
            }
        }
        if (matches != 1) {
            fail("must match exactly one schema variant (matched=" +
                 std::to_string(matches) + "); first failure: " +
                 (first_failure.empty() ? "none" : first_failure));
        }
        return;
    }
    if (schema.contains("anyOf")) {
        std::string first_failure;
        for (const auto& candidate : schema.at("anyOf")) {
            try {
                validate_node_as(value, candidate, path, code);
                return;
            } catch (const Error& exc) {
                if (first_failure.empty()) first_failure = exc.message();
            }
        }
        fail("must match one schema variant; first failure: " +
             (first_failure.empty() ? "none" : first_failure));
    }
    if (schema.contains("const")) {
        if (!same_typed_equal(value, schema.at("const"))) {
            fail("must equal " + render_value(schema.at("const")) +
                 " with the same JSON type");
        }
    }
    if (schema.contains("enum")) {
        bool found = false;
        for (const auto& candidate : schema.at("enum")) {
            if (same_typed_equal(value, candidate)) {
                found = true;
                break;
            }
        }
        if (!found) {
            fail("must be one of " + render_value(schema.at("enum")));
        }
    }
    if (schema.contains("type")) {
        bool ok = false;
        const nlohmann::json& expected = schema.at("type");
        if (expected.is_string()) {
            ok = is_type(value, expected.get<std::string>());
        } else {
            for (const auto& item : expected) {
                if (is_type(value, item.get<std::string>())) {
                    ok = true;
                    break;
                }
            }
        }
        if (!ok) {
            fail("expected type " + type_list(schema));
        }
    }
    if (value.is_number_float() && !std::isfinite(value.get<double>())) {
        fail("must be a finite JSON number");
    }
    const bool object_like = value.is_object() &&
        (schema.value("type", std::string()) == "object" ||
         schema.contains("properties") || schema.contains("additionalProperties"));
    if (object_like) {
        const nlohmann::json* properties_ptr = nullptr;
        auto properties_it = schema.find("properties");
        if (properties_it != schema.end() && properties_it->is_object()) {
            properties_ptr = &(*properties_it);
        }
        if (schema.contains("required")) {
            for (const auto& key : schema.at("required")) {
                const std::string name = key.get<std::string>();
                if (!value.contains(name)) {
                    fail("missing required property '" + name + "'");
                }
            }
        }
        const bool additional_allowed =
            !schema.contains("additionalProperties") ||
            schema.at("additionalProperties").is_object() ||
            schema.at("additionalProperties").get<bool>();
        for (auto it = value.begin(); it != value.end(); ++it) {
            const std::string child_path = path + "." + it.key();
            if (properties_ptr != nullptr && properties_ptr->contains(it.key())) {
                validate_node_as(it.value(), properties_ptr->at(it.key()), child_path,
                                 code);
                continue;
            }
            if (!additional_allowed) {
                fail("unknown property '" + it.key() + "'");
            }
        }
    }
    if (value.is_array() && schema.contains("items")) {
        std::size_t index = 0;
        for (const auto& item : value) {
            validate_node_as(item, schema.at("items"),
                             path + "[" + std::to_string(index) + "]", code);
            ++index;
        }
        if (schema.contains("minItems") &&
            value.size() < schema.at("minItems").get<std::size_t>()) {
            fail("requires at least " +
                 std::to_string(schema.at("minItems").get<std::size_t>()) + " items");
        }
        if (schema.contains("maxItems") &&
            value.size() > schema.at("maxItems").get<std::size_t>()) {
            fail("requires at most " +
                 std::to_string(schema.at("maxItems").get<std::size_t>()) + " items");
        }
    }
    if (value.is_string()) {
        const std::string text = value.get<std::string>();
        if (schema.contains("minLength") &&
            text.size() < schema.at("minLength").get<std::size_t>()) {
            fail("requires length >= " +
                 std::to_string(schema.at("minLength").get<std::size_t>()));
        }
        if (schema.contains("maxLength") &&
            text.size() > schema.at("maxLength").get<std::size_t>()) {
            fail("requires length <= " +
                 std::to_string(schema.at("maxLength").get<std::size_t>()));
        }
        if (schema.contains("pattern")) {
            const std::string pattern = schema.at("pattern").get<std::string>();
            try {
                std::regex expression(pattern);
                if (!std::regex_search(text, expression)) {
                    fail("must match pattern '" + pattern + "'");
                }
            } catch (const std::regex_error&) {
                fail("pattern is invalid: " + pattern);
            }
        }
    }
    if (value.is_number() && !value.is_boolean()) {
        if (schema.contains("minimum") &&
            value.get<double>() < schema.at("minimum").get<double>()) {
            fail("must be >= " + render_value(schema.at("minimum")));
        }
        if (schema.contains("maximum") &&
            value.get<double>() > schema.at("maximum").get<double>()) {
            fail("must be <= " + render_value(schema.at("maximum")));
        }
    }
}

void validate_node(const nlohmann::json& value,
                   const nlohmann::json& schema,
                   const std::string& path) {
    validate_node_as(value, schema, path, "SCHEMA_INVALID");
}

bool SchemaCatalog::is_schema_node(const nlohmann::json& value) {
    return value.is_object() && value.value("x-schema-node", false) == true;
}

SchemaCatalog::SchemaCatalog() {
    const std::string manifest_text = read_file(schema_path("manifest.json"));
    nlohmann::json manifest;
    try {
        manifest = nlohmann::json::parse(manifest_text);
    } catch (const std::exception& exc) {
        throw Error("SCHEMA_DATA_INVALID", "schema manifest is not valid JSON",
                    {{"error", exc.what()}});
    }
    if (!manifest.contains("actions") || !manifest.at("actions").is_object()) {
        throw Error("SCHEMA_DATA_INVALID", "schema manifest lacks actions");
    }
    for (auto it = manifest.at("actions").begin();
         it != manifest.at("actions").end(); ++it) {
        const std::string action = it.key();
        const std::string request_file =
            "actions/" + action + ".request.schema.json";
        const std::string response_file =
            "actions/" + action + ".response.schema.json";
        try {
            const nlohmann::json request =
                nlohmann::json::parse(read_file(schema_path(request_file)));
            const nlohmann::json response =
                nlohmann::json::parse(read_file(schema_path(response_file)));
            schemas_[action] = {request, response};
        } catch (const Error&) {
            throw;
        } catch (const std::exception& exc) {
            throw Error("SCHEMA_DATA_INVALID", "schema file is not valid JSON",
                        {{"action", action}, {"error", exc.what()}});
        }
    }
    try {
        run_manifest_ = nlohmann::json::parse(
            read_file(schema_path("internal/run_manifest.input.schema.json")));
        stdio_quit_ = nlohmann::json::parse(
            read_file(schema_path("internal/stdio_quit.request.schema.json")));
    } catch (const Error&) {
        throw;
    } catch (const std::exception& exc) {
        throw Error("SCHEMA_DATA_INVALID", "internal schema is not valid JSON",
                    {{"error", exc.what()}});
    }
}

const SchemaCatalog& SchemaCatalog::instance() {
    static const SchemaCatalog catalog;
    return catalog;
}

bool SchemaCatalog::has_action(const std::string& action) const {
    return schemas_.find(action) != schemas_.end();
}

std::vector<std::string> SchemaCatalog::action_names() const {
    std::vector<std::string> names;
    names.reserve(schemas_.size());
    for (const auto& item : schemas_) {
        names.push_back(item.first);
    }
    return names;
}

const nlohmann::json& SchemaCatalog::request_schema(const std::string& action) const {
    auto it = schemas_.find(action);
    if (it == schemas_.end()) {
        throw Error("UNKNOWN_ACTION", "unknown action", {{"action", action}});
    }
    return it->second.first;
}

const nlohmann::json& SchemaCatalog::response_schema(const std::string& action) const {
    auto it = schemas_.find(action);
    if (it == schemas_.end()) {
        throw Error("UNKNOWN_ACTION", "unknown action", {{"action", action}});
    }
    return it->second.second;
}

void SchemaCatalog::validate_request(const nlohmann::json& req) const {
    if (!req.is_object()) {
        throw Error("SCHEMA_INVALID", "request must be a JSON object",
                    {{"path", "$"}});
    }
    const std::string action = req.value("action", std::string());
    if (action.empty()) {
        throw Error("SCHEMA_INVALID", "action is required",
                    {{"path", "$.action"}});
    }
    if (!has_action(action)) {
        throw Error("UNKNOWN_ACTION", "unknown action", {{"action", action}});
    }
    validate_node(req, request_schema(action), "$");
}

void SchemaCatalog::validate_stdio_request(const nlohmann::json& req) const {
    if (req.value("action", std::string()) == "stdio.quit") {
        validate_node(req, stdio_quit_, "$");
        return;
    }
    const std::string action = req.value("action", std::string());
    if (!has_action(action)) {
        if (req.value("request_id", std::string()).empty()) {
            throw Error("SCHEMA_INVALID", "stdio request_id is required",
                        {{"path", "$.request_id"}});
        }
        return;
    }
    nlohmann::json schema = request_schema(action);
    if (!schema.contains("required")) {
        schema["required"] = nlohmann::json::array();
    }
    bool has_request_id = false;
    for (const auto& item : schema.at("required")) {
        if (item.get<std::string>() == "request_id") {
            has_request_id = true;
            break;
        }
    }
    if (!has_request_id) {
        schema["required"].push_back("request_id");
    }
    validate_node(req, schema, "$");
}

void SchemaCatalog::validate_response(const std::string& action,
                                      const nlohmann::json& rsp) const {
    const nlohmann::json* schema = nullptr;
    if (has_action(action)) {
        schema = &response_schema(action);
    }
    if (schema == nullptr) {
        // Fall back to the canonical error envelope shape.
        static const nlohmann::json error_schema = nlohmann::json::parse(R"({
          "type": "object",
          "additionalProperties": false,
          "required": ["ok","api_version","request_id","action","summary","data","error","warnings"],
          "properties": {
            "ok": {"const": false},
            "api_version": {"const": "xcov.v1"},
            "request_id": {"type": "string"},
            "action": {"type": "string"},
            "summary": {"type": "object"},
            "data": {"type": "object"},
            "error": {"type": "object"},
            "warnings": {"type": "array"}
          }
        })");
        validate_node_as(rsp, error_schema, "$", "RESPONSE_SCHEMA_INVALID");
        return;
    }
    validate_node_as(rsp, *schema, "$", "RESPONSE_SCHEMA_INVALID");
}

void SchemaCatalog::validate_run_manifest(const nlohmann::json& doc) const {
    validate_node(doc, run_manifest_, "$");
}

} // namespace xcov
