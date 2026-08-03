#include "core/schema/runtime_schema_validator.h"

#include "common/env_config.h"
#include "core/diagnostic_error.h"
#include "core/schema/internal_request_contract.h"

#include "nlohmann/json-schema.hpp"

#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <vector>

namespace xdebug_core {

namespace {

using PlainJson = nlohmann::json;
using Validator = nlohmann::json_schema::json_validator;
using JsonUri = nlohmann::json_uri;

struct CachedValidator {
    std::string schema_path;
    std::unique_ptr<Validator> validator;
    PlainJson schema;
    OrderedJson example;
};

struct ValidationIssue {
    std::string pointer;
    std::string message;
};

struct CachedBatchValidators {
    CachedValidator envelope;
    CachedValidator unknown_child;
    std::set<std::string> known_actions;
};

struct CachedResponseVariantValidators {
    PlainJson source;
    std::map<std::string, std::unique_ptr<CachedValidator> > variants;
};

struct CachedInternalRequestValidators {
    // Small generated catalog only: known-action validation must not read or
    // construct the complete large-union schema.
    std::map<std::string, std::string> schema_refs;
    std::map<std::string, std::string> helper_dispatch_kinds;
    std::map<std::string, std::string> helper_schema_refs;
    std::map<std::string, std::unique_ptr<CachedValidator> > actions;
    std::map<std::string, std::unique_ptr<CachedValidator> > helper_actions;
};

std::mutex& cache_mutex() {
    static std::mutex m;
    return m;
}

std::map<std::string, std::unique_ptr<CachedValidator> >& validator_cache() {
    static std::map<std::string, std::unique_ptr<CachedValidator> > cache;
    return cache;
}

std::map<std::string, std::unique_ptr<CachedBatchValidators> >&
batch_validator_cache() {
    static std::map<std::string, std::unique_ptr<CachedBatchValidators> > cache;
    return cache;
}

std::map<std::string, std::unique_ptr<CachedResponseVariantValidators> >&
response_variant_validator_cache() {
    static std::map<
        std::string,
        std::unique_ptr<CachedResponseVariantValidators> > cache;
    return cache;
}

std::map<std::string, std::unique_ptr<CachedInternalRequestValidators> >&
internal_request_validator_cache() {
    static std::map<
        std::string,
        std::unique_ptr<CachedInternalRequestValidators> > cache;
    return cache;
}

bool file_exists(const std::string& path) {
    struct stat st;
    return stat(path.c_str(), &st) == 0;
}

std::string request_schema_ref_for_action(
    const std::string& action,
    const std::string& schema_ref) {
    if (!schema_ref.empty()) return schema_ref;
    return "schemas/v1/actions/" + action + ".request.schema.json";
}

std::string response_schema_ref_for_action(
    const std::string& action,
    const std::string& schema_ref) {
    if (!schema_ref.empty()) return schema_ref;
    return "schemas/v1/actions/" + action + ".response.schema.json";
}

std::string repo_file_path(const std::string& rel) {
    std::string home = env_raw_string("XVERIF_HOME");
    if (!home.empty()) {
        std::string p = home + "/xdebug/" + rel;
        if (file_exists(p)) return p;
    }
    std::string p = "xdebug/" + rel;
    if (file_exists(p)) return p;
    if (file_exists(rel)) return rel;
    return p;
}

bool read_plain_json(const std::string& path, PlainJson& out, std::string& error) {
    std::ifstream input(path.c_str());
    if (!input.good()) {
        error = "schema file not found: " + path;
        return false;
    }
    try {
        input >> out;
    } catch (const std::exception& e) {
        error = "failed to parse schema file " + path + ": " + e.what();
        return false;
    }
    return true;
}

OrderedJson read_ordered_json_or_null(const std::string& path) {
    std::ifstream input(path.c_str());
    if (!input.good()) return OrderedJson(nullptr);
    try {
        OrderedJson out;
        input >> out;
        return out;
    } catch (...) {
        return OrderedJson(nullptr);
    }
}

std::string example_path_for_action(const std::string& action) {
    return repo_file_path("examples/requests/" + action + ".basic.json");
}

void no_external_schema_loader(const JsonUri& id, PlainJson&) {
    throw std::runtime_error("external schema loading is disabled: " + id.to_string());
}

PlainJson runtime_schema_copy(PlainJson schema) {
    schema["$schema"] = "http://json-schema.org/draft-07/schema#";
    return schema;
}

std::string local_definition_name(const std::string& reference) {
    const std::string prefix = "#/$defs/";
    if (reference.compare(0, prefix.size(), prefix) != 0) return "";
    return reference.substr(prefix.size());
}

void collect_local_definition_refs(
    const PlainJson& value,
    std::set<std::string>& refs) {
    if (value.is_object()) {
        PlainJson::const_iterator ref = value.find("$ref");
        if (ref != value.end() && ref->is_string()) {
            const std::string name =
                local_definition_name(ref->get<std::string>());
            if (!name.empty()) refs.insert(name);
        }
        for (PlainJson::const_iterator it = value.begin();
             it != value.end();
             ++it) {
            collect_local_definition_refs(it.value(), refs);
        }
    } else if (value.is_array()) {
        for (PlainJson::const_iterator it = value.begin();
             it != value.end();
             ++it) {
            collect_local_definition_refs(*it, refs);
        }
    }
}

bool attach_definition_closure(
    PlainJson& projected,
    const PlainJson& definitions,
    RuntimeSchemaValidationResult& result,
    const std::string& schema_ref) {
    std::set<std::string> pending;
    collect_local_definition_refs(projected, pending);
    PlainJson selected = PlainJson::object();
    while (!pending.empty()) {
        const std::string name = *pending.begin();
        pending.erase(pending.begin());
        if (selected.contains(name)) continue;
        if (!definitions.contains(name)) {
            result.ok = false;
            result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
            result.message =
                "response projection references missing definition: " +
                name;
            result.error =
                DiagnosticErrorBuilder::internal(
                    result.code,
                    result.message)
                    .schema_path(schema_ref)
                    .to_json();
            return false;
        }
        selected[name] = definitions[name];
        std::set<std::string> nested;
        collect_local_definition_refs(definitions[name], nested);
        pending.insert(nested.begin(), nested.end());
    }
    projected["$defs"] = selected;
    return true;
}

const PlainJson* resolve_local_schema(
    const PlainJson& schema,
    const PlainJson& definitions) {
    if (!schema.is_object() || !schema.contains("$ref") ||
        !schema["$ref"].is_string()) {
        return &schema;
    }
    const std::string name =
        local_definition_name(schema["$ref"].get<std::string>());
    if (name.empty() || !definitions.contains(name)) return nullptr;
    return &definitions[name];
}

bool discriminator_allows_value(
    const PlainJson& schema,
    const OrderedJson& value) {
    if (!schema.is_object()) return true;
    const std::string encoded = value.dump();
    if (schema.contains("const")) {
        if (schema["const"].dump() != encoded) return false;
    }
    if (schema.contains("enum") && schema["enum"].is_array()) {
        bool found = false;
        for (const PlainJson& candidate : schema["enum"]) {
            if (candidate.dump() == encoded) {
                found = true;
                break;
            }
        }
        if (!found) return false;
    }
    return true;
}

bool top_response_branch_possible(
    const PlainJson& branch,
    const OrderedJson& response) {
    if (!branch.is_object() || !branch.contains("properties") ||
        !branch["properties"].is_object() ||
        !branch["properties"].contains("ok")) {
        return true;
    }
    return discriminator_allows_value(
        branch["properties"]["ok"], response["ok"]);
}

bool summary_variant_possible(
    const PlainJson& variant,
    const PlainJson& definitions,
    const OrderedJson& summary) {
    if (!variant.is_object() || !variant.contains("properties") ||
        !variant["properties"].is_object() ||
        !variant["properties"].contains("summary")) {
        return true;
    }
    const PlainJson* summary_schema = resolve_local_schema(
        variant["properties"]["summary"], definitions);
    if (!summary_schema || !summary_schema->is_object() ||
        !summary_schema->contains("properties") ||
        !(*summary_schema)["properties"].is_object()) {
        return true;
    }

    // Generated response variants currently use these stable summary fields
    // as their mutually exclusive discriminator.  Other fields remain under
    // the selected projected schema and are still validated in full.
    for (const char* field : {"query_mode", "found"}) {
        const PlainJson& properties = (*summary_schema)["properties"];
        if (!properties.contains(field)) continue;
        if (!summary.contains(field)) continue;
        if (!discriminator_allows_value(
                properties[field], summary[field])) {
            return false;
        }
    }
    return true;
}

bool select_unique_response_branch(
    const PlainJson& source,
    const OrderedJson& response,
    size_t& top_index,
    bool& has_nested_variant,
    size_t& nested_index) {
    has_nested_variant = false;
    if (!response.is_object() || !response.contains("ok") ||
        !response["ok"].is_boolean() ||
        !source.contains("oneOf") || !source["oneOf"].is_array() ||
        !source.contains("$defs") || !source["$defs"].is_object()) {
        return false;
    }

    std::vector<size_t> top_candidates;
    for (size_t index = 0; index < source["oneOf"].size(); ++index) {
        if (top_response_branch_possible(source["oneOf"][index], response)) {
            top_candidates.push_back(index);
        }
    }
    if (top_candidates.size() != 1) return false;
    top_index = top_candidates.front();

    const PlainJson& top = source["oneOf"][top_index];
    if (!top.contains("oneOf")) return true;
    if (!top["oneOf"].is_array() || !response.contains("summary") ||
        !response["summary"].is_object()) {
        return false;
    }

    std::vector<size_t> nested_candidates;
    for (size_t index = 0; index < top["oneOf"].size(); ++index) {
        if (summary_variant_possible(
                top["oneOf"][index],
                source["$defs"],
                response["summary"])) {
            nested_candidates.push_back(index);
        }
    }
    if (nested_candidates.size() != 1) return false;
    has_nested_variant = true;
    nested_index = nested_candidates.front();
    return true;
}

bool schema_contains_alternative(
    const PlainJson& general_schema,
    const PlainJson& selected_schema,
    const PlainJson& definitions,
    size_t depth) {
    if (depth > 32) return false;
    const PlainJson* general =
        resolve_local_schema(general_schema, definitions);
    const PlainJson* selected =
        resolve_local_schema(selected_schema, definitions);
    if (!general || !selected) return false;
    if (*general == *selected) return true;
    if (!general->is_object() || !general->contains("anyOf") ||
        !(*general)["anyOf"].is_array()) {
        return false;
    }
    for (const PlainJson& alternative_schema : (*general)["anyOf"]) {
        if (schema_contains_alternative(
                alternative_schema,
                selected_schema,
                definitions,
                depth + 1)) {
            return true;
        }
    }
    return false;
}

bool schema_is_same_or_alternative(
    const PlainJson& general_schema,
    const PlainJson& selected_schema,
    const PlainJson& definitions) {
    return schema_contains_alternative(
        general_schema, selected_schema, definitions, 0);
}

void merge_required_fields(
    PlainJson& projected,
    const PlainJson& selected) {
    if (!selected.contains("required") ||
        !selected["required"].is_array()) {
        return;
    }
    if (!projected.contains("required") ||
        !projected["required"].is_array()) {
        projected["required"] = PlainJson::array();
    }
    for (const PlainJson& field : selected["required"]) {
        bool present = false;
        for (const PlainJson& existing : projected["required"]) {
            if (existing == field) {
                present = true;
                break;
            }
        }
        if (!present) projected["required"].push_back(field);
    }
}

void apply_selected_response_branch(
    PlainJson& projected,
    const PlainJson& selected,
    const PlainJson& definitions) {
    if (selected.contains("properties") &&
        selected["properties"].is_object()) {
        if (!projected.contains("properties") ||
            !projected["properties"].is_object()) {
            projected["properties"] = PlainJson::object();
        }
        for (PlainJson::const_iterator property =
                 selected["properties"].begin();
             property != selected["properties"].end(); ++property) {
            if (!projected["properties"].contains(property.key())) {
                projected["properties"][property.key()] = property.value();
                continue;
            }
            PlainJson& general =
                projected["properties"][property.key()];
            if (schema_is_same_or_alternative(
                    general, property.value(), definitions)) {
                general = property.value();
            } else {
                PlainJson original = general;
                general = {
                    {"allOf", PlainJson::array(
                        {original, property.value()})}
                };
            }
        }
    }
    merge_required_fields(projected, selected);

    PlainJson residual = selected;
    residual.erase("properties");
    residual.erase("required");
    residual.erase("oneOf");
    if (!residual.empty()) {
        if (!projected.contains("allOf") ||
            !projected["allOf"].is_array()) {
            projected["allOf"] = PlainJson::array();
        }
        projected["allOf"].push_back(residual);
    }
}

bool compile_projected_validator(
    CachedValidator& cached,
    const PlainJson& schema,
    const std::string& schema_ref,
    RuntimeSchemaValidationResult& result);

const CachedValidator* get_cached_response_variant_validator(
    const std::string& schema_ref,
    const OrderedJson& response,
    bool& projection_selected,
    RuntimeSchemaValidationResult& result) {
    projection_selected = false;
    std::lock_guard<std::mutex> lock(cache_mutex());
    std::map<
        std::string,
        std::unique_ptr<CachedResponseVariantValidators> >& cache =
        response_variant_validator_cache();
    std::map<
        std::string,
        std::unique_ptr<CachedResponseVariantValidators> >::iterator found =
        cache.find(schema_ref);
    if (found == cache.end()) {
        std::unique_ptr<CachedResponseVariantValidators> created(
            new CachedResponseVariantValidators());
        std::string error;
        if (!read_plain_json(
                repo_file_path(schema_ref), created->source, error)) {
            result.ok = false;
            result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
            result.message = error;
            result.error =
                DiagnosticErrorBuilder::internal(
                    result.code, result.message)
                    .schema_path(schema_ref)
                    .to_json();
            return nullptr;
        }
        found = cache.insert(
            std::make_pair(schema_ref, std::move(created))).first;
    }

    CachedResponseVariantValidators& variants = *found->second;
    size_t top_index = 0;
    size_t nested_index = 0;
    bool has_nested_variant = false;
    if (!select_unique_response_branch(
            variants.source,
            response,
            top_index,
            has_nested_variant,
            nested_index)) {
        return nullptr;
    }

    const std::string variant_key =
        "top:" + std::to_string(top_index) +
        (has_nested_variant
             ? "/nested:" + std::to_string(nested_index)
             : std::string());
    std::map<std::string, std::unique_ptr<CachedValidator> >::iterator
        cached = variants.variants.find(variant_key);
    if (cached != variants.variants.end()) {
        projection_selected = true;
        return cached->second.get();
    }

    const PlainJson& definitions = variants.source["$defs"];
    PlainJson projected = variants.source;
    projected.erase("$defs");
    projected.erase("oneOf");
    const PlainJson& top = variants.source["oneOf"][top_index];
    apply_selected_response_branch(projected, top, definitions);
    if (has_nested_variant) {
        apply_selected_response_branch(
            projected, top["oneOf"][nested_index], definitions);
    }
    if (!attach_definition_closure(
            projected, definitions, result, schema_ref)) {
        return nullptr;
    }

    std::unique_ptr<CachedValidator> compiled(new CachedValidator());
    if (!compile_projected_validator(
            *compiled, projected, schema_ref, result)) {
        return nullptr;
    }
    const CachedValidator* out = compiled.get();
    variants.variants[variant_key] = std::move(compiled);
    projection_selected = true;
    return out;
}

bool compile_projected_validator(
    CachedValidator& cached,
    const PlainJson& schema,
    const std::string& schema_ref,
    RuntimeSchemaValidationResult& result) {
    cached.schema_path = schema_ref;
    cached.schema = runtime_schema_copy(schema);
    cached.example = OrderedJson(nullptr);
    try {
        cached.validator.reset(new Validator(no_external_schema_loader));
        cached.validator->set_root_schema(cached.schema);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            "failed to compile runtime schema " + schema_ref + ": " +
            e.what();
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref)
                .to_json();
        return false;
    }
    return true;
}

bool internal_action_discriminator_matches(
    const PlainJson& branch,
    const std::string& action,
    bool& has_discriminator) {
    has_discriminator = false;
    if (!branch.is_object() || !branch.contains("properties") ||
        !branch["properties"].is_object() ||
        !branch["properties"].contains("action")) {
        return false;
    }
    const PlainJson& discriminator =
        branch["properties"]["action"];
    if (!discriminator.is_object()) return false;
    if (discriminator.contains("const")) {
        has_discriminator = true;
        return discriminator["const"].is_string() &&
               discriminator["const"].get<std::string>() == action;
    }
    if (!discriminator.contains("enum") ||
        !discriminator["enum"].is_array()) {
        return false;
    }
    has_discriminator = true;
    for (const PlainJson& value : discriminator["enum"]) {
        if (value.is_string() && value.get<std::string>() == action) {
            return true;
        }
    }
    return false;
}

bool safe_internal_action_name(const std::string& action) {
    if (action.empty()) return false;
    for (size_t index = 0; index < action.size(); ++index) {
        const char ch = action[index];
        const bool alphanumeric =
            (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9');
        if (alphanumeric) continue;
        if ((ch != '.' && ch != '_') || index == 0 ||
            index + 1 == action.size()) {
            return false;
        }
        const char next = action[index + 1];
        const bool next_alphanumeric =
            (next >= 'a' && next <= 'z') ||
            (next >= '0' && next <= '9');
        if (!next_alphanumeric) return false;
    }
    return true;
}

const CachedInternalRequestValidators* get_cached_internal_request_manifest(
    RuntimeSchemaValidationResult& result) {
    std::lock_guard<std::mutex> lock(cache_mutex());
    std::map<
        std::string,
        std::unique_ptr<CachedInternalRequestValidators> >& cache =
        internal_request_validator_cache();
    std::map<
        std::string,
        std::unique_ptr<CachedInternalRequestValidators> >::iterator found =
        cache.find(kInternalRequestManifest);
    if (found != cache.end()) return found->second.get();

    PlainJson manifest;
    std::string error;
    if (!read_plain_json(
            repo_file_path(kInternalRequestManifest), manifest, error)) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = error;
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(kInternalRequestManifest)
                .to_json();
        return nullptr;
    }
    const std::set<std::string> allowed_fields = {
        "schema_version",
        "api_version",
        "aggregate_schema_ref",
        "action_count",
        "actions",
        "helper_dispatch_kinds",
        "helper_envelope_schemas",
    };
    bool valid = manifest.is_object();
    if (valid) {
        for (PlainJson::const_iterator field = manifest.begin();
             field != manifest.end(); ++field) {
            if (allowed_fields.count(field.key()) == 0) valid = false;
        }
    }
    valid = valid && manifest.size() == allowed_fields.size() &&
            manifest.value("schema_version", std::string()) ==
                "xdebug.internal-request-manifest.v1" &&
            manifest.value("api_version", std::string()) ==
                kInternalApiVersion &&
            manifest.value("aggregate_schema_ref", std::string()) ==
                kInternalRequestSchema &&
            manifest.contains("action_count") &&
            manifest["action_count"].is_number_unsigned() &&
            manifest.contains("actions") &&
            manifest["actions"].is_object() &&
            manifest.contains("helper_dispatch_kinds") &&
            manifest["helper_dispatch_kinds"].is_object() &&
            manifest.contains("helper_envelope_schemas") &&
            manifest["helper_envelope_schemas"].is_object();
    if (!valid ||
        manifest["action_count"].get<size_t>() !=
            manifest["actions"].size() ||
        manifest["helper_dispatch_kinds"].size() !=
            manifest["actions"].size()) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            "internal request manifest is missing or inconsistent";
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(kInternalRequestManifest)
                .to_json();
        return nullptr;
    }

    std::unique_ptr<CachedInternalRequestValidators> created(
        new CachedInternalRequestValidators());
    std::set<std::string> unique_refs;
    for (PlainJson::const_iterator entry = manifest["actions"].begin();
         entry != manifest["actions"].end(); ++entry) {
        const std::string action = entry.key();
        const std::string expected_ref =
            "schemas/v1/internal/actions/" + action +
            ".request.schema.json";
        if (!safe_internal_action_name(action) ||
            !entry.value().is_string() ||
            entry.value().get<std::string>() != expected_ref ||
            !unique_refs.insert(expected_ref).second) {
            result.ok = false;
            result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
            result.message =
                "internal request manifest contains an invalid or duplicate "
                "action mapping";
            result.error =
                DiagnosticErrorBuilder::internal(
                    result.code, result.message)
                    .schema_path(kInternalRequestManifest)
                    .to_json();
            return nullptr;
        }
        created->schema_refs[action] = expected_ref;
    }
    const std::set<std::string> allowed_dispatch_kinds = {
        "server_forward",
        "session_local",
        "server_control",
        "hybrid_local_forward",
    };
    for (PlainJson::const_iterator entry =
             manifest["helper_dispatch_kinds"].begin();
         entry != manifest["helper_dispatch_kinds"].end(); ++entry) {
        if (created->schema_refs.count(entry.key()) == 0 ||
            !entry.value().is_string() ||
            allowed_dispatch_kinds.count(
                entry.value().get<std::string>()) == 0) {
            result.ok = false;
            result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
            result.message =
                "internal request manifest contains an invalid helper "
                "dispatch kind";
            result.error =
                DiagnosticErrorBuilder::internal(
                    result.code, result.message)
                    .schema_path(kInternalRequestManifest)
                    .to_json();
            return nullptr;
        }
        created->helper_dispatch_kinds[entry.key()] =
            entry.value().get<std::string>();
    }
    std::set<std::string> unique_helper_refs;
    for (PlainJson::const_iterator entry =
             manifest["helper_envelope_schemas"].begin();
         entry != manifest["helper_envelope_schemas"].end(); ++entry) {
        const std::string action = entry.key();
        const std::string expected_ref =
            "schemas/v1/internal/helper-actions/" + action +
            ".request.schema.json";
        if (created->schema_refs.count(action) == 0 ||
            created->helper_dispatch_kinds.count(action) == 0 ||
            created->helper_dispatch_kinds.find(action)->second !=
                "server_forward" ||
            !entry.value().is_string() ||
            entry.value().get<std::string>() != expected_ref ||
            !unique_helper_refs.insert(expected_ref).second) {
            result.ok = false;
            result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
            result.message =
                "internal request manifest contains an invalid or duplicate "
                "helper envelope mapping";
            result.error =
                DiagnosticErrorBuilder::internal(
                    result.code, result.message)
                    .schema_path(kInternalRequestManifest)
                    .to_json();
            return nullptr;
        }
        created->helper_schema_refs[action] = expected_ref;
    }
    for (std::map<std::string, std::string>::const_iterator entry =
             created->helper_dispatch_kinds.begin();
         entry != created->helper_dispatch_kinds.end(); ++entry) {
        const bool has_helper_schema =
            created->helper_schema_refs.count(entry->first) != 0;
        if ((entry->second == "server_forward") != has_helper_schema) {
            result.ok = false;
            result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
            result.message =
                "helper dispatch catalog and envelope schemas differ";
            result.error =
                DiagnosticErrorBuilder::internal(
                    result.code, result.message)
                    .schema_path(kInternalRequestManifest)
                    .to_json();
            return nullptr;
        }
    }
    const CachedInternalRequestValidators* out = created.get();
    cache[kInternalRequestManifest] = std::move(created);
    return out;
}

const CachedValidator* get_cached_internal_request_validator(
    const std::string& action,
    bool helper_envelope,
    RuntimeSchemaValidationResult& result) {
    std::lock_guard<std::mutex> lock(cache_mutex());
    std::map<
        std::string,
        std::unique_ptr<CachedInternalRequestValidators> >& cache =
        internal_request_validator_cache();
    std::map<
        std::string,
        std::unique_ptr<CachedInternalRequestValidators> >::iterator found =
        cache.find(kInternalRequestManifest);
    if (found == cache.end()) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = "internal request manifest was not loaded";
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(kInternalRequestManifest)
                .to_json();
        return nullptr;
    }
    CachedInternalRequestValidators& actions = *found->second;
    std::map<std::string, std::unique_ptr<CachedValidator> >& validators =
        helper_envelope ? actions.helper_actions : actions.actions;
    std::map<std::string, std::unique_ptr<CachedValidator> >::iterator
        cached = validators.find(action);
    if (cached != validators.end()) return cached->second.get();
    const std::map<std::string, std::string>& schema_refs =
        helper_envelope ? actions.helper_schema_refs : actions.schema_refs;
    std::map<std::string, std::string>::const_iterator schema_ref =
        schema_refs.find(action);
    if (schema_ref == schema_refs.end()) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            helper_envelope
                ? "server-forward action is missing its helper envelope schema"
                : "known internal action is missing its runtime schema mapping";
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(kInternalRequestManifest)
                .to_json();
        return nullptr;
    }

    PlainJson schema;
    std::string error;
    if (!read_plain_json(repo_file_path(schema_ref->second), schema, error)) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = error;
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref->second)
                .to_json();
        return nullptr;
    }
    bool has_discriminator = false;
    const bool exact_action = helper_envelope
        ? internal_action_discriminator_matches(
              schema, action, has_discriminator)
        : schema.contains("allOf") && schema["allOf"].is_array() &&
              schema["allOf"].size() == 1 &&
              internal_action_discriminator_matches(
                  schema["allOf"][0], action, has_discriminator);
    if (!has_discriminator || !exact_action) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            "internal request runtime schema discriminator does not match "
            "its manifest action";
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref->second)
                .to_json();
        return nullptr;
    }
    std::unique_ptr<CachedValidator> compiled(new CachedValidator());
    if (!compile_projected_validator(
            *compiled, schema, schema_ref->second, result)) {
        return nullptr;
    }
    const CachedValidator* out = compiled.get();
    validators[action] = std::move(compiled);
    return out;
}

const CachedBatchValidators* get_cached_batch_validators(
    const std::string& schema_ref,
    RuntimeSchemaValidationResult& result) {
    std::lock_guard<std::mutex> lock(cache_mutex());
    std::map<std::string, std::unique_ptr<CachedBatchValidators> >& cache =
        batch_validator_cache();
    std::map<std::string, std::unique_ptr<CachedBatchValidators> >::
        const_iterator found = cache.find(schema_ref);
    if (found != cache.end()) return found->second.get();

    PlainJson source;
    std::string error;
    if (!read_plain_json(repo_file_path(schema_ref), source, error)) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = error;
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref)
                .to_json();
        return nullptr;
    }
    if (!source.contains("$defs") || !source["$defs"].is_object() ||
        !source["$defs"].contains("successData") ||
        !source["$defs"].contains("successData0") ||
        !source["$defs"].contains("batchChild__unknown_child_error")) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            "batch response schema is missing projection definitions";
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref)
                .to_json();
        return nullptr;
    }

    PlainJson definitions = source["$defs"];
    try {
        definitions["successData"]["properties"]["results"]["items"] =
            PlainJson::object();
        definitions["successData0"]["properties"]["results"]["items"] =
            PlainJson::object();
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            std::string("batch response projection failed: ") + e.what();
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref)
                .to_json();
        return nullptr;
    }
    PlainJson envelope = source;
    envelope.erase("$defs");
    if (!attach_definition_closure(
            envelope, definitions, result, schema_ref)) {
        return nullptr;
    }

    PlainJson unknown_child =
        definitions["batchChild__unknown_child_error"];
    if (!attach_definition_closure(
            unknown_child, definitions, result, schema_ref)) {
        return nullptr;
    }

    std::unique_ptr<CachedBatchValidators> cached(
        new CachedBatchValidators());
    const PlainJson& action_schema =
        definitions["batchChild__unknown_child_error"]["properties"]["action"];
    if (action_schema.contains("not") &&
        action_schema["not"].contains("enum") &&
        action_schema["not"]["enum"].is_array()) {
        for (const PlainJson& action : action_schema["not"]["enum"]) {
            if (action.is_string()) {
                cached->known_actions.insert(action.get<std::string>());
            }
        }
    }
    if (cached->known_actions.empty()) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            "batch unknown-child schema has no known-action exclusion set";
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(schema_ref)
                .to_json();
        return nullptr;
    }
    if (!compile_projected_validator(
            cached->envelope, envelope, schema_ref, result) ||
        !compile_projected_validator(
            cached->unknown_child, unknown_child, schema_ref, result)) {
        return nullptr;
    }

    const CachedBatchValidators* out = cached.get();
    cache[schema_ref] = std::move(cached);
    return out;
}

const CachedValidator* get_cached_validator(const std::string& action,
                                            const std::string& schema_ref,
                                            RuntimeSchemaValidationResult& result) {
    const std::string rel = schema_ref;
    std::lock_guard<std::mutex> lock(cache_mutex());
    std::map<std::string, std::unique_ptr<CachedValidator> >& cache = validator_cache();
    std::map<std::string, std::unique_ptr<CachedValidator> >::const_iterator it = cache.find(rel);
    if (it != cache.end()) return it->second.get();

    std::string path = repo_file_path(rel);
    PlainJson schema;
    std::string error;
    if (!read_plain_json(path, schema, error)) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message = error;
        result.error = DiagnosticErrorBuilder::internal(result.code, result.message)
            .schema_path(rel).to_json();
        return nullptr;
    }

    std::unique_ptr<CachedValidator> cached(new CachedValidator());
    cached->schema_path = rel;
    cached->schema = runtime_schema_copy(schema);
    cached->example =
        rel == kInternalRequestSchema ||
                rel.find(".response.schema.json") != std::string::npos
            ? OrderedJson(nullptr)
            : read_ordered_json_or_null(example_path_for_action(action));
    try {
        cached->validator.reset(new Validator(no_external_schema_loader));
        cached->validator->set_root_schema(cached->schema);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "SCHEMA_VALIDATION_CONFIG_ERROR";
        result.message =
            "failed to compile runtime schema " + rel + ": " + e.what();
        result.error = DiagnosticErrorBuilder::internal(result.code, result.message)
            .schema_path(rel).to_json();
        return nullptr;
    }

    const CachedValidator* out = cached.get();
    cache[rel] = std::move(cached);
    return out;
}

std::string plain_type_name(const PlainJson& value) {
    if (value.is_null()) return "null";
    if (value.is_boolean()) return "boolean";
    if (value.is_number_integer() || value.is_number_unsigned()) return "integer";
    if (value.is_number()) return "number";
    if (value.is_string()) return "string";
    if (value.is_array()) return "array";
    if (value.is_object()) return "object";
    return "unknown";
}

std::string pointer_to_arg_path(const std::string& pointer) {
    if (pointer.empty()) return "$";
    std::string out;
    size_t i = 0;
    while (i < pointer.size()) {
        if (pointer[i] == '/') ++i;
        size_t slash = pointer.find('/', i);
        std::string token = pointer.substr(i, slash == std::string::npos ? std::string::npos : slash - i);
        std::string decoded;
        for (size_t j = 0; j < token.size(); ++j) {
            if (token[j] == '~' && j + 1 < token.size()) {
                if (token[j + 1] == '0') { decoded.push_back('~'); ++j; continue; }
                if (token[j + 1] == '1') { decoded.push_back('/'); ++j; continue; }
            }
            decoded.push_back(token[j]);
        }
        bool numeric = !decoded.empty();
        for (size_t j = 0; j < decoded.size(); ++j) {
            if (decoded[j] < '0' || decoded[j] > '9') {
                numeric = false;
                break;
            }
        }
        if (numeric) {
            out += "[" + decoded + "]";
        } else {
            if (!out.empty()) out += ".";
            out += decoded;
        }
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    return out.empty() ? "$" : out;
}

std::string parse_quoted_property(const std::string& message) {
    size_t begin = message.find('\'');
    if (begin == std::string::npos) begin = message.find('"');
    if (begin == std::string::npos) return "";
    char quote = message[begin];
    size_t end = message.find(quote, begin + 1);
    if (end == std::string::npos || end <= begin + 1) return "";
    return message.substr(begin + 1, end - begin - 1);
}

bool is_required_error(const std::string& message) {
    return message.find("required") != std::string::npos &&
           (message.find("not found") != std::string::npos ||
            message.find("missing") != std::string::npos);
}

bool is_additional_property_error(const std::string& message) {
    return message.find("additional property") != std::string::npos;
}

bool is_legacy_clock_sampling_field(const std::string& field) {
    return field == "clk" || field == "sampling" ||
           field == "clock_edge" || field == "posedge";
}

bool plain_pointer_get(const PlainJson& root, const std::string& pointer, PlainJson& out) {
    try {
        if (pointer.empty()) {
            out = root;
            return true;
        }
        out = root.at(PlainJson::json_pointer(pointer));
        return true;
    } catch (...) {
        return false;
    }
}

std::string child_pointer(const std::string& parent, const std::string& child) {
    if (child.empty()) return parent;
    std::string escaped;
    for (size_t i = 0; i < child.size(); ++i) {
        if (child[i] == '~') escaped += "~0";
        else if (child[i] == '/') escaped += "~1";
        else escaped.push_back(child[i]);
    }
    return parent + "/" + escaped;
}

const PlainJson* schema_for_pointer(const PlainJson& schema, const std::string& pointer) {
    const PlainJson* node = &schema;
    size_t i = 0;
    while (i < pointer.size()) {
        if (pointer[i] == '/') ++i;
        size_t slash = pointer.find('/', i);
        std::string token = pointer.substr(i, slash == std::string::npos ? std::string::npos : slash - i);
        std::string decoded;
        for (size_t j = 0; j < token.size(); ++j) {
            if (token[j] == '~' && j + 1 < token.size()) {
                if (token[j + 1] == '0') { decoded.push_back('~'); ++j; continue; }
                if (token[j + 1] == '1') { decoded.push_back('/'); ++j; continue; }
            }
            decoded.push_back(token[j]);
        }
        bool numeric = !decoded.empty();
        for (size_t j = 0; j < decoded.size(); ++j) {
            if (decoded[j] < '0' || decoded[j] > '9') {
                numeric = false;
                break;
            }
        }
        if (node->is_object() && !numeric && node->contains("properties") &&
            (*node)["properties"].is_object() && (*node)["properties"].contains(decoded)) {
            node = &(*node)["properties"][decoded];
        } else if (numeric && node->is_object() && node->contains("items") && (*node)["items"].is_object()) {
            node = &(*node)["items"];
        } else {
            return nullptr;
        }
        if (slash == std::string::npos) break;
        i = slash + 1;
    }
    return node;
}

OrderedJson plain_to_ordered(const PlainJson& value) {
    return OrderedJson::parse(value.dump());
}

OrderedJson enum_values_from_schema(const PlainJson* schema) {
    if (!schema || !schema->is_object() || !schema->contains("enum") || !(*schema)["enum"].is_array()) {
        return OrderedJson();
    }
    return plain_to_ordered((*schema)["enum"]);
}

OrderedJson compact_correct_example(const OrderedJson& example) {
    if (!example.is_object()) return OrderedJson();
    OrderedJson out = OrderedJson::object();
    if (example.contains("api_version")) out["api_version"] = example["api_version"];
    if (example.contains("action")) out["action"] = example["action"];
    if (example.contains("target")) out["target"] = example["target"];
    if (example.contains("args")) out["args"] = example["args"];
    if (example.contains("limits")) out["limits"] = example["limits"];
    if (example.contains("output")) out["output"] = example["output"];
    return out;
}

OrderedJson required_any_of_for(const std::string& action, const std::string& invalid_arg) {
    if (invalid_arg != "args" && invalid_arg != "$") return OrderedJson();
    if (action == "event.find" || action == "event.export")
        return OrderedJson::array({"args.name", "args.clock + args.signals"});
    if (action == "apb.config.load" || action == "axi.config.load")
        return OrderedJson::array({"args.config", "args.config_path"});
    if (action == "stream.config.load")
        return OrderedJson::array({"args.config", "args.config_path"});
    if (action == "axi.export")
        return OrderedJson::array({"args.time_range"});
    if (action == "list.delete")
        return OrderedJson::array({"args.signal", "args.index"});
    return OrderedJson();
}

std::string join_json_array(const OrderedJson& values) {
    if (!values.is_array()) return "";
    std::ostringstream oss;
    for (size_t i = 0; i < values.size(); ++i) {
        if (i) oss << " or ";
        if (values[i].is_string()) oss << values[i].get<std::string>();
        else oss << values[i].dump();
    }
    return oss.str();
}

std::string friendly_validation_message(const std::string& raw,
                                        const std::string& invalid_arg,
                                        const std::string& expected,
                                        const OrderedJson& available,
                                        const OrderedJson& required_any_of) {
    std::ostringstream oss;
    oss << "invalid parameter " << invalid_arg << ": " << raw;
    if (required_any_of.is_array() && !required_any_of.empty())
        oss << "; provide one of: " << join_json_array(required_any_of);
    else if (!expected.empty())
        oss << "; expected " << expected;
    if (available.is_array() && !available.empty())
        oss << "; available values: " << available.dump();
    return oss.str();
}

std::string expected_from_schema(const PlainJson* schema, const std::string& fallback_message) {
    if (!schema || !schema->is_object()) return fallback_message;
    if (schema->contains("type")) {
        return "type " + (*schema)["type"].dump();
    }
    if (schema->contains("enum")) {
        return "one of " + (*schema)["enum"].dump();
    }
    if (schema->contains("oneOf")) return "oneOf schema";
    if (schema->contains("anyOf")) return "anyOf schema";
    if (schema->contains("allOf")) return "allOf schema";
    return fallback_message;
}

class CollectingErrorHandler : public nlohmann::json_schema::error_handler {
public:
    std::vector<ValidationIssue> issues;

    void error(const PlainJson::json_pointer& ptr,
               const PlainJson&,
               const std::string& message) override {
        ValidationIssue issue;
        issue.pointer = ptr.to_string();
        issue.message = message;
        issues.push_back(issue);
    }
};

RuntimeSchemaValidationResult make_validation_error(const CachedValidator& cached,
                                                    const PlainJson& instance,
                                                    const std::string& action,
                                                    const ValidationIssue& issue) {
    RuntimeSchemaValidationResult result;
    result.ok = false;
    result.code = "INVALID_REQUEST";
    result.message = issue.message;

    std::string pointer = issue.pointer;
    std::string missing_property;
    std::string extra_property;
    bool additional_property = false;
    if (is_required_error(issue.message)) {
        missing_property = parse_quoted_property(issue.message);
        if (!missing_property.empty()) pointer = child_pointer(pointer, missing_property);
    } else if (is_additional_property_error(issue.message)) {
        extra_property = parse_quoted_property(issue.message);
        if (!extra_property.empty()) pointer = child_pointer(pointer, extra_property);
        additional_property = true;
    }

    const PlainJson* schema_node = schema_for_pointer(cached.schema, pointer);
    PlainJson received;
    bool has_received = plain_pointer_get(instance, pointer, received);
    std::string invalid_arg = pointer_to_arg_path(pointer);
    if (missing_property == "stream" && action.compare(0, 7, "stream.") == 0 &&
        instance.is_object() && instance.contains("args") && instance["args"].is_object() &&
        instance["args"].contains("name")) {
        invalid_arg = "args.name";
        pointer = "/args/name";
        has_received = plain_pointer_get(instance, pointer, received);
    }
    std::string expected = additional_property ? "no additional properties allowed" :
                                                 expected_from_schema(schema_node, issue.message);
    if (additional_property && is_legacy_clock_sampling_field(extra_property)) {
        expected = "use clock, edge, and sample_point";
    }
    DiagnosticErrorBuilder builder =
        DiagnosticErrorBuilder::schema(result.code, result.message)
            .invalid_arg(invalid_arg)
            .expected(expected)
            .schema_path(cached.schema_path);
    if (has_received) {
        builder.received_type(plain_type_name(received));
    } else if (!missing_property.empty()) {
        builder.received_type("missing");
    }
    OrderedJson available = enum_values_from_schema(schema_node);
    if (!available.is_null()) builder.available_values(available);
    OrderedJson correct_example = compact_correct_example(cached.example);
    if (!correct_example.is_null()) builder.correct_example(correct_example);
    OrderedJson required_any_of = required_any_of_for(action, invalid_arg);
    if (!required_any_of.is_null()) builder.required_any_of(required_any_of);
    result.message = sensitive_diagnostic_path(invalid_arg)
        ? "sensitive request field failed validation"
        : friendly_validation_message(
              issue.message,
              invalid_arg,
              expected,
              available,
              required_any_of);
    result.error = builder.to_json();
    result.error["message"] = result.message;
    return result;
}

RuntimeSchemaValidationResult validate_with_cached_schema(
    const CachedValidator& cached,
    const std::string& action,
    const OrderedJson& request) {
    RuntimeSchemaValidationResult result;
    PlainJson instance;
    try {
        instance = PlainJson::parse(request.dump());
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "INVALID_REQUEST";
        result.message =
            std::string("request must be a JSON object: ") + e.what();
        result.error =
            DiagnosticErrorBuilder::schema(result.code, result.message)
                .invalid_arg("$")
                .schema_path(cached.schema_path)
                .to_json();
        return result;
    }

    CollectingErrorHandler handler;
    try {
        cached.validator->validate(instance, handler);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "INVALID_REQUEST";
        result.message = e.what();
        DiagnosticErrorBuilder builder =
            DiagnosticErrorBuilder::schema(result.code, result.message)
                .invalid_arg("$")
                .schema_path(cached.schema_path);
        OrderedJson example = compact_correct_example(cached.example);
        if (!example.is_null()) builder.correct_example(example);
        result.error = builder.to_json();
        return result;
    }
    if (!handler.issues.empty()) {
        RuntimeSchemaValidationResult failure =
            make_validation_error(
                cached,
                instance,
                action,
                handler.issues.front());
        OrderedJson issues = OrderedJson::array();
        for (const ValidationIssue& issue : handler.issues) {
            const std::string issue_path =
                pointer_to_arg_path(issue.pointer);
            issues.push_back({
                {"path", issue_path},
                {"message",
                 sensitive_diagnostic_path(issue_path)
                     ? "sensitive request field failed validation"
                     : issue.message},
            });
        }
        if (issues.size() > 1) {
            failure.error["validation_issues"] = issues;
        }
        return failure;
    }
    return result;
}

RuntimeSchemaValidationResult validate_response_with_cached_schema(
    const CachedValidator& cached,
    const OrderedJson& response) {
    RuntimeSchemaValidationResult result;
    PlainJson instance;
    try {
        instance = PlainJson::parse(response.dump());
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "INTERNAL_RESPONSE_SCHEMA_VIOLATION";
        result.message =
            std::string("public response is not valid JSON: ") + e.what();
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(cached.schema_path)
                .to_json();
        return result;
    }

    CollectingErrorHandler handler;
    try {
        cached.validator->validate(instance, handler);
    } catch (const std::exception& e) {
        result.ok = false;
        result.code = "INTERNAL_RESPONSE_SCHEMA_VIOLATION";
        result.message =
            std::string("public response validation failed: ") + e.what();
        result.error =
            DiagnosticErrorBuilder::internal(result.code, result.message)
                .schema_path(cached.schema_path)
                .to_json();
        return result;
    }
    if (handler.issues.empty()) return result;

    result.ok = false;
    result.code = "INTERNAL_RESPONSE_SCHEMA_VIOLATION";
    result.message =
        "handler response violated its action-specific response schema";
    result.error =
        DiagnosticErrorBuilder::internal(result.code, result.message)
            .schema_path(cached.schema_path)
            .to_json();
    OrderedJson issues = OrderedJson::array();
    for (const ValidationIssue& issue : handler.issues) {
        issues.push_back({
            {"path", pointer_to_arg_path(issue.pointer)},
            {"message", issue.message},
        });
    }
    result.error["validation"] = {
        {"issues", issues}
    };
    return result;
}

}  // namespace

RuntimeSchemaValidationResult RuntimeSchemaValidator::validate_request(const std::string& action,
                                                                       const OrderedJson& request,
                                                                       const std::string& schema_ref) const {
    RuntimeSchemaValidationResult result;
    const CachedValidator* cached = get_cached_validator(
        action,
        request_schema_ref_for_action(action, schema_ref),
        result);
    if (!cached) return result;
    return validate_with_cached_schema(*cached, action, request);
}

RuntimeSchemaValidationResult
RuntimeSchemaValidator::validate_response(
    const std::string& action,
    const OrderedJson& response,
    const std::string& schema_ref) const {
    RuntimeSchemaValidationResult result;
    const std::string resolved_schema_ref =
        response_schema_ref_for_action(action, schema_ref);
    bool projection_selected = false;
    const CachedValidator* cached =
        get_cached_response_variant_validator(
            resolved_schema_ref,
            response,
            projection_selected,
            result);
    if (!result.ok) return result;
    if (projection_selected) {
        return validate_response_with_cached_schema(*cached, response);
    }

    // Some response schemas do not expose a unique ok/query_mode/found
    // discriminator.  Preserve exact public-schema semantics by using the
    // complete validator whenever a projection cannot be proven unique.
    cached = get_cached_validator(
        action,
        resolved_schema_ref,
        result);
    if (!cached) return result;
    return validate_response_with_cached_schema(*cached, response);
}

RuntimeSchemaValidationResult
RuntimeSchemaValidator::validate_batch_response(
    const OrderedJson& response,
    const std::string& schema_ref) const {
    RuntimeSchemaValidationResult result;
    const std::string resolved_schema_ref =
        response_schema_ref_for_action("batch", schema_ref);
    const CachedBatchValidators* cached =
        get_cached_batch_validators(resolved_schema_ref, result);
    if (!cached) return result;

    result =
        validate_response_with_cached_schema(cached->envelope, response);
    if (!result.ok) return result;
    if (!response.is_object() || !response.contains("data") ||
        !response["data"].is_object() ||
        !response["data"].contains("results") ||
        !response["data"]["results"].is_array()) {
        return result;
    }

    const OrderedJson& children = response["data"]["results"];
    for (size_t index = 0; index < children.size(); ++index) {
        const OrderedJson& child = children[index];
        const bool known_action =
            child.is_object() && child.contains("action") &&
            child["action"].is_string() &&
            cached->known_actions.count(
                child["action"].get<std::string>()) != 0;
        if (known_action) continue;

        RuntimeSchemaValidationResult child_result =
            validate_response_with_cached_schema(
                cached->unknown_child, child);
        if (child_result.ok) continue;

        if (child_result.error.contains("validation") &&
            child_result.error["validation"].is_object() &&
            child_result.error["validation"].contains("issues") &&
            child_result.error["validation"]["issues"].is_array()) {
            for (OrderedJson& issue :
                 child_result.error["validation"]["issues"]) {
                if (!issue.is_object() || !issue.contains("path") ||
                    !issue["path"].is_string()) {
                    continue;
                }
                const std::string child_path =
                    issue["path"].get<std::string>();
                const std::string prefix =
                    "data.results[" + std::to_string(index) + "]";
                issue["path"] =
                    child_path == "$"
                        ? prefix
                        : prefix + "." + child_path;
            }
        }
        return child_result;
    }
    return result;
}

RuntimeSchemaValidationResult
RuntimeSchemaValidator::validate_internal_request(
    const OrderedJson& request) const {
    RuntimeSchemaValidationResult result;
    const std::string action =
        request.is_object() && request.contains("action") &&
                request["action"].is_string()
            ? request["action"].get<std::string>()
            : std::string();
    if (!request.is_object()) {
        const CachedValidator* complete = get_cached_validator(
            action, kInternalRequestSchema, result);
        return complete
            ? validate_with_cached_schema(*complete, action, request)
            : result;
    }
    if (!request.contains("api_version") ||
        !request["api_version"].is_string() ||
        request["api_version"].get<std::string>() !=
            kInternalApiVersion) {
        result.ok = false;
        result.code = "UNSUPPORTED_API_VERSION";
        result.message = "expected xdebug.internal.v1";
        result.error =
            DiagnosticErrorBuilder::schema(
                result.code,
                result.message)
                .invalid_arg("api_version")
                .expected(kInternalApiVersion)
                .schema_path(kInternalRequestSchema)
                .to_json();
        return result;
    }
    if (action.empty()) {
        const CachedValidator* complete = get_cached_validator(
            action, kInternalRequestSchema, result);
        return complete
            ? validate_with_cached_schema(*complete, action, request)
            : result;
    }
    const CachedInternalRequestValidators* manifest =
        get_cached_internal_request_manifest(result);
    if (!manifest) return result;
    if (manifest->schema_refs.count(action) == 0) {
        result.ok = false;
        result.code = "UNKNOWN_ACTION";
        result.message = "unknown internal engine action: " + action;
        result.error =
            DiagnosticErrorBuilder::schema(
                result.code,
                result.message)
                .invalid_arg("action")
                .received(action)
                .schema_path(kInternalRequestSchema)
                .to_json();
        return result;
    }
    const CachedValidator* action_cached =
        get_cached_internal_request_validator(action, false, result);
    return action_cached
        ? validate_with_cached_schema(*action_cached, action, request)
        : result;
}

RuntimeSchemaValidationResult
RuntimeSchemaValidator::validate_internal_request_for_helper(
    const OrderedJson& request,
    bool& used_forward_envelope) const {
    used_forward_envelope = false;
    if (!request.is_object() || !request.contains("action") ||
        !request["action"].is_string() ||
        !request.contains("api_version") ||
        !request["api_version"].is_string() ||
        request["api_version"].get<std::string>() !=
            kInternalApiVersion) {
        return validate_internal_request(request);
    }
    const std::string action = request["action"].get<std::string>();
    const OrderedJson routing =
        request.value("routing", OrderedJson::object());
    const bool session_forward =
        routing.is_object() && routing.contains("session_id") &&
        routing["session_id"].is_string() &&
        !routing["session_id"].get<std::string>().empty();
    if (!session_forward) return validate_internal_request(request);

    RuntimeSchemaValidationResult result;
    const CachedInternalRequestValidators* manifest =
        get_cached_internal_request_manifest(result);
    if (!manifest) return result;
    std::map<std::string, std::string>::const_iterator dispatch =
        manifest->helper_dispatch_kinds.find(action);
    if (dispatch == manifest->helper_dispatch_kinds.end() ||
        dispatch->second != "server_forward") {
        return validate_internal_request(request);
    }
    const CachedValidator* envelope =
        get_cached_internal_request_validator(action, true, result);
    if (!envelope) return result;
    used_forward_envelope = true;
    return validate_with_cached_schema(*envelope, action, request);
}

OrderedJson valid_request_example(const std::string& action) {
    return compact_correct_example(
        read_ordered_json_or_null(example_path_for_action(action)));
}

}  // namespace xdebug_core
