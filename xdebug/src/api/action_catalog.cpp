#include "api/action_catalog.h"
#include "api/action_registry_init.h"
#include "api/text_response_builder.h"
#include "core/diagnostic_error.h"
#include "api/response.h"
#include "common/env_config.h"

#include <fstream>
#include <algorithm>
#include <cctype>
#include <limits>
#include <sstream>
#include <vector>

namespace xdebug {

using xdebug_core::DiagnosticErrorBuilder;

namespace {

const std::size_t kActionGuideMaxBytes = 10000;

std::set<std::string> actions_for_category(const std::string& category) {
    std::set<std::string> out;
    std::vector<ActionSpec> specs = default_action_registry().list_specs();
    for (size_t i = 0; i < specs.size(); ++i) {
        if (specs[i].category == category) out.insert(specs[i].name);
    }
    return out;
}

std::string lower_ascii(std::string value) {
    for (char& ch : value) {
        unsigned char uch = static_cast<unsigned char>(ch);
        if (uch < 128) ch = static_cast<char>(std::tolower(uch));
    }
    return value;
}

bool string_array_contains(const Json& values, const std::string& candidate) {
    if (!values.is_array()) return true;
    for (const auto& value : values)
        if (value.is_string() && value.get<std::string>() == candidate) return true;
    return false;
}

bool purpose_matches(const Json& requested, const std::vector<std::string>& actual) {
    if (!requested.is_array()) return true;
    for (const auto& value : requested) {
        if (!value.is_string()) continue;
        if (std::find(actual.begin(), actual.end(), value.get<std::string>()) != actual.end())
            return true;
    }
    return false;
}

bool action_matches_filter(const ActionSpec& spec, const Json& filter) {
    if (!filter.is_object() || filter.empty()) return true;
    if (filter.contains("category") &&
        !string_array_contains(filter["category"], spec.category)) return false;
    if (filter.contains("requires") &&
        !string_array_contains(filter["requires"], to_string(spec.resource))) return false;
    if (filter.contains("purposes") &&
        !purpose_matches(filter["purposes"], spec.purposes)) return false;
    if (filter.contains("keyword")) {
        std::string keyword = lower_ascii(filter.value("keyword", std::string()));
        std::string name = lower_ascii(spec.name);
        std::string en = lower_ascii(spec.description_en);
        std::string zh = lower_ascii(spec.description_zh);
        if (name.find(keyword) == std::string::npos &&
            en.find(keyword) == std::string::npos &&
            zh.find(keyword) == std::string::npos) return false;
    }
    return true;
}

std::vector<ActionSpec> filtered_specs(const Json& filter) {
    std::vector<ActionSpec> out;
    for (const auto& spec : default_action_registry().list_specs())
        if (action_matches_filter(spec, filter)) out.push_back(spec);
    return out;
}

Json filtered_action_payload(const std::vector<ActionSpec>& specs, bool verbose) {
    Json out = Json::array();
    for (const auto& spec : specs)
        out.push_back(verbose ? action_spec_descriptor(spec) : Json(spec.name));
    return out;
}

Json filtered_modes(const std::vector<ActionSpec>& specs) {
    Json modes = {{"design", Json::array()}, {"waveform", Json::array()},
                  {"combined", Json::array()}, {"builtin", Json::array()},
                  {"session", Json::array()}};
    for (const auto& spec : specs) modes[spec.category].push_back(spec.name);
    return modes;
}

std::string concise_action_guide(const std::vector<ActionSpec>& specs) {
    std::ostringstream out;
    out << "xdebug actions: " << specs.size()
        << ". Select one, then query its schema.";
    for (const auto& spec : specs) {
        out << "\n" << spec.name << ": " << spec.description_en;
    }
    return out.str();
}

std::string schema_root() {
    std::string home = xdebug_core::env_raw_string("XVERIF_HOME");
    if (!home.empty()) return home + "/xdebug/schemas/v1/actions/";
    return "xdebug/schemas/v1/actions/";
}

std::string repo_root() {
    std::string home = xdebug_core::env_raw_string("XVERIF_HOME");
    if (!home.empty()) return home + "/xdebug/";
    return "xdebug/";
}

Json compact_batch_response_schema(const std::vector<ActionSpec>& specs) {
    Json child_actions = Json::array();
    for (const auto& spec : specs) {
        if (spec.name != "batch") child_actions.push_back(spec.name);
    }
    std::sort(child_actions.begin(), child_actions.end());
    return {
        {"$schema", "https://json-schema.org/draft/2020-12/schema"},
        {"$id", "xdebug.batch.response.summary.v1"},
        {"title", "batch response compact selector contract"},
        {"description",
         "Token-efficient batch outer-envelope contract. Child payloads are "
         "action-discriminated and require response_detail=child for exact "
         "validation; request response_detail=full only when the complete "
         "recursive union is required."},
        {"type", "object"},
        {"required", Json::array(
             {"api_version", "ok", "action", "tool", "session", "summary",
              "data", "error"})},
        {"properties",
         {
             {"api_version", {{"const", "xdebug.v1"}}},
             {"request_id", {{"type", "string"}, {"minLength", 1}}},
             {"ok", {{"type", "boolean"}}},
             {"action", {{"const", "batch"}}},
             {"tool", {{"type", "object"}}},
             {"session", {{"type", Json::array({"object", "null"})}}},
             {"summary",
              {{"type", "object"},
               {"required", Json::array(
                    {"count", "all_ok", "failed_count", "failed_indexes",
                     "failed_codes", "failed_layers"})},
               {"properties",
                {
                    {"count", {{"type", "integer"}, {"minimum", 0}}},
                    {"all_ok", {{"type", "boolean"}}},
                    {"failed_count", {{"type", "integer"}, {"minimum", 0}}},
                    {"failed_indexes", {{"type", "array"},
                                        {"items", {{"type", "integer"},
                                                   {"minimum", 0}}}}},
                    {"failed_codes", {{"type", "array"},
                                      {"items", {{"type", "string"}}}}},
                    {"failed_layers", {{"type", "array"},
                                       {"items", {{"type", "string"}}}}},
                }},
               {"additionalProperties", false}}},
             {"data",
              {{"type", "object"},
               {"required", Json::array({"results"})},
               {"properties",
                {{"results",
                  {{"type", "array"},
                   {"items",
                    {{"type", "object"},
                     {"required", Json::array({"ok", "action"})},
                     {"properties",
                      {{"ok", {{"type", "boolean"}}},
                       {"action", {{"type", "string"}}}}},
                     {"additionalProperties", true},
                     {"x-exact-child-schema",
                      "schema(action=batch, kind=response, "
                      "response_detail=child, child_action=<result.action>)"}}}}}}},
               {"additionalProperties", false}}},
             {"error", {{"type", Json::array({"object", "null"})}}},
         }},
        {"additionalProperties", false},
        {"x-contract-completeness", "outer-envelope-only"},
        {"x-child-action-count", child_actions.size()},
        {"x-child-actions", child_actions},
        {"x-selector",
         {{"summary", "response_detail=summary"},
          {"child", "response_detail=child + child_action"},
          {"full", "response_detail=full"}}},
    };
}

std::string schema_type_text(const Json& property) {
    if (!property.is_object() || !property.contains("type")) return "any";
    const Json& type = property["type"];
    if (type.is_string()) return type.get<std::string>();
    if (!type.is_array()) return "any";
    std::string out;
    for (const auto& item : type) {
        if (!item.is_string()) continue;
        if (!out.empty()) out += "|";
        out += item.get<std::string>();
    }
    return out.empty() ? "any" : out;
}

std::string schema_property_notes(const Json& property) {
    if (!property.is_object()) return std::string();
    std::string notes = property.value("description", std::string());
    if (property.contains("enum") && property["enum"].is_array()) {
        std::string values;
        for (const auto& item : property["enum"]) {
            if (!item.is_string()) continue;
            if (!values.empty()) values += "|";
            values += item.get<std::string>();
        }
        if (!values.empty()) {
            if (!notes.empty()) notes += " ";
            notes += "values=" + values;
        }
    }
    if (property.contains("default") && property["default"].is_primitive()) {
        if (!notes.empty()) notes += " ";
        notes += "default=" + xdebug::json_to_xout_value(property["default"]);
    }
    return notes;
}

void emit_schema_properties(xdebug::TextResponseBuilder& out,
                            const std::string& section,
                            const Json& object_schema) {
    if (!object_schema.is_object()) return;
    const Json properties = object_schema.value("properties", Json::object());
    if (!properties.is_object() || properties.empty()) return;
    std::set<std::string> required;
    const Json required_json = object_schema.value("required", Json::array());
    if (required_json.is_array()) {
        for (const auto& item : required_json) {
            if (item.is_string()) required.insert(item.get<std::string>());
        }
    }
    std::vector<std::vector<std::string> > rows;
    for (auto it = properties.begin(); it != properties.end(); ++it) {
        rows.push_back({it.key(), schema_type_text(it.value()),
                        required.count(it.key()) ? "yes" : "no",
                        schema_property_notes(it.value())});
    }
    out.emit_section(section);
    out.emit_table({"name", "type", "required", "description"}, rows);
}

std::string render_catalog_schema_xout(const Json& response) {
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_header("schema");
    const Json summary = response.value("summary", Json::object());
    const Json data = response.value("data", Json::object());
    const Json schema = data.value("schema", Json::object());
    out.emit_section("summary");
    if (summary.contains("action")) out.emit_kv("action", summary["action"]);
    if (summary.contains("kind")) out.emit_kv("kind", summary["kind"]);
    if (summary.contains("response_detail"))
        out.emit_kv("response_detail", summary["response_detail"]);
    if (summary.contains("selected_child") && !summary["selected_child"].is_null())
        out.emit_kv("selected_child", summary["selected_child"]);
    if (data.contains("schema_path")) out.emit_kv("schema_path", data["schema_path"]);
    for (const char* key : {"x-purpose", "x-how_it_works", "x-when_to_use"}) {
        if (schema.contains(key) && schema[key].is_string())
            out.emit_kv(key, schema[key]);
    }
    const Json top_properties = schema.value("properties", Json::object());
    if (top_properties.is_object() && top_properties.contains("args"))
        emit_schema_properties(out, "arguments", top_properties["args"]);
    else
        emit_schema_properties(out, "fields", schema);
    if (top_properties.is_object() && top_properties.contains("limits"))
        emit_schema_properties(out, "limits", top_properties["limits"]);
    const Json constraints = data.value("constraints", Json::array());
    if (constraints.is_array() && !constraints.empty()) {
        out.emit_section("constraints");
        for (const auto& item : constraints) {
            if (item.is_string()) out.emit_row({item.get<std::string>()});
        }
    }
    const Json examples = data.value("examples", Json::array());
    if (examples.is_array() && !examples.empty()) {
        out.emit_section("examples");
        for (const auto& example : examples) {
            if (example.is_object() && example.contains("path") &&
                example["path"].is_string()) {
                out.emit_row({example["path"].get<std::string>()});
            }
        }
    }
    return out.str();
}

std::string render_catalog_actions_xout(const Json& response) {
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_header("actions");
    const Json summary = response.value("summary", Json::object());
    const Json data = response.value("data", Json::object());
    out.emit_section("summary");
    for (const char* key : {"action_count", "total_action_count", "verbose", "filtered",
                            "view", "guide_bytes", "guide_limit_bytes"}) {
        if (summary.contains(key)) out.emit_kv(key, summary[key]);
    }
    if (summary.value("view", std::string()) == "guide") {
        const std::string guide = data.value("guide", std::string());
        out.emit_section("guide");
        std::istringstream lines(guide);
        std::string line;
        while (std::getline(lines, line)) out.emit_row({line});
        return out.str();
    }
    const bool verbose = summary.value("verbose", false);
    const Json actions = data.value("actions", Json::array());
    if (verbose && actions.is_array()) {
        std::vector<std::vector<std::string> > rows;
        for (const auto& action : actions) {
            if (!action.is_object()) continue;
            rows.push_back({action.value("name", std::string()),
                            action.value("category", std::string()),
                            action.value("requires", std::string()),
                            action.value("description_zh", std::string())});
        }
        out.emit_section("actions");
        out.emit_table({"name", "category", "requires", "description"}, rows);
    } else {
        const Json modes = data.value("modes", Json::object());
        for (const char* category : {"builtin", "session", "design", "waveform", "combined"}) {
            if (!modes.contains(category) || !modes[category].is_array() ||
                modes[category].empty()) continue;
            out.emit_section(category);
            for (const auto& action : modes[category]) {
                if (action.is_string()) out.emit_row({action.get<std::string>()});
            }
        }
    }
    return out.str();
}

bool read_json_file(const std::string& path, Json& out) {
    std::ifstream input(path.c_str());
    if (!input.good()) return false;
    try {
        input >> out;
    } catch (...) {
        return false;
    }
    return true;
}

size_t edit_distance(const std::string& lhs, const std::string& rhs) {
    std::vector<size_t> previous(rhs.size() + 1);
    std::vector<size_t> current(rhs.size() + 1);
    for (size_t j = 0; j <= rhs.size(); ++j) previous[j] = j;
    for (size_t i = 1; i <= lhs.size(); ++i) {
        current[0] = i;
        for (size_t j = 1; j <= rhs.size(); ++j) {
            const size_t substitution = previous[j - 1] + (lhs[i - 1] == rhs[j - 1] ? 0 : 1);
            current[j] = std::min(std::min(previous[j] + 1, current[j - 1] + 1), substitution);
        }
        previous.swap(current);
    }
    return previous[rhs.size()];
}

} // namespace

const std::set<std::string>& design_actions() {
    static const std::set<std::string> actions = actions_for_category("design");
    return actions;
}

const std::set<std::string>& waveform_actions() {
    static const std::set<std::string> actions = actions_for_category("waveform");
    return actions;
}

Json suggested_action_names(const std::string& action, size_t limit) {
    std::vector<std::pair<size_t, std::string> > ranked;
    for (const auto& spec : default_action_registry().list_specs()) {
        size_t score = edit_distance(action, spec.name);
        const size_t dot = action.find('.');
        if (dot != std::string::npos && spec.name.compare(0, dot + 1, action, 0, dot + 1) == 0) {
            score = score > 2 ? score - 2 : 0;
        }
        ranked.push_back(std::make_pair(score, spec.name));
    }
    std::sort(ranked.begin(), ranked.end());
    Json out = Json::array();
    for (size_t i = 0; i < ranked.size() && i < limit; ++i) out.push_back(ranked[i].second);
    return out;
}

Json catalog_schema_response(const Json& request) {
    Json response = make_response(request, "schema");
    Json args = request.value("args", Json::object());
    std::string action = args.value("action", std::string());
    std::string kind = args.value("kind", std::string());
    if (kind.empty()) kind = "request";
    const bool has_response_detail = args.contains("response_detail");
    const bool has_child_action = args.contains("child_action");
    const std::string response_detail =
        args.value("response_detail", std::string("full"));
    const std::string child_action =
        args.value("child_action", std::string());
    const ActionSpec* spec = default_action_registry().find_spec(action);
    if (!spec) {
        Json suggestions = suggested_action_names(action);
        Json error = DiagnosticErrorBuilder::handler(
                         "UNKNOWN_ACTION", "unknown action: " + action)
                         .invalid_arg("args.action")
                         .received(action)
                         .available_values(suggestions)
                         .to_json();
        return make_error(request, "schema", error);
    }
    std::string rel;
    if (kind == "request") rel = spec->request_schema;
    else if (kind == "response") rel = spec->response_schema;
    else {
        Json example = {
            {"api_version", "xdebug.v1"},
            {"action", "schema"},
            {"args", {{"action", action}, {"kind", "request"}}}
        };
        Json error = DiagnosticErrorBuilder::handler("INVALID_ENUM",
                                           "schema args.kind must be request or response")
                         .invalid_arg("args.kind")
                         .expected("one of request, response")
                         .received(kind)
                         .available_values(Json::array({"request", "response"}))
                         .example_note("示例仅说明 schema action 的 native JSON 形态；kind 必须是 request 或 response。")
                         .correct_example(example)
                         .to_json();
        return make_error(request, "schema", error);
    }
    if ((has_response_detail || has_child_action) &&
        (action != "batch" || kind != "response")) {
        return make_error(
            request, "schema",
            DiagnosticErrorBuilder::handler(
                "INVALID_ARGUMENT",
                "response_detail and child_action are only valid for "
                "action=batch with kind=response")
                .invalid_arg(has_child_action ? "args.child_action"
                                              : "args.response_detail")
                .expected("action=batch and kind=response")
                .to_json());
    }
    if (response_detail != "summary" && response_detail != "child" &&
        response_detail != "full") {
        return make_error(
            request, "schema",
            DiagnosticErrorBuilder::handler(
                "INVALID_ENUM",
                "schema args.response_detail must be summary, child, or full")
                .invalid_arg("args.response_detail")
                .expected("one of summary, child, full")
                .received(response_detail)
                .available_values(
                    Json::array({"summary", "child", "full"}))
                .to_json());
    }
    if (action == "batch" && kind == "response" &&
        ((response_detail == "child") != has_child_action)) {
        return make_error(
            request, "schema",
            DiagnosticErrorBuilder::handler(
                "INVALID_ARGUMENT",
                response_detail == "child"
                    ? "args.child_action is required when response_detail=child"
                    : "args.child_action is forbidden unless response_detail=child")
                .invalid_arg("args.child_action")
                .expected(response_detail == "child"
                              ? "one exact public non-batch action"
                              : "omit child_action")
                .to_json());
    }
    const std::string prefix = "schemas/v1/actions/";
    std::string path = rel;
    if (path.compare(0, prefix.size(), prefix) == 0) path = schema_root() + path.substr(prefix.size());
    Json schema;
    std::string selected_schema_path = rel;
    if (action == "batch" && kind == "response" &&
        response_detail == "summary") {
        schema = compact_batch_response_schema(
            default_action_registry().list_specs());
        selected_schema_path.clear();
    } else if (action == "batch" && kind == "response" &&
               response_detail == "child") {
        const ActionSpec* child_spec =
            default_action_registry().find_spec(child_action);
        if (!child_spec || child_action == "batch") {
            Json suggestions = suggested_action_names(child_action);
            return make_error(
                request, "schema",
                DiagnosticErrorBuilder::handler(
                    "UNKNOWN_ACTION",
                    "unknown or recursive batch child action: " + child_action)
                    .invalid_arg("args.child_action")
                    .received(child_action)
                    .available_values(suggestions)
                    .to_json());
        }
        selected_schema_path = child_spec->response_schema;
        std::string child_path = selected_schema_path;
        if (child_path.compare(0, prefix.size(), prefix) == 0)
            child_path = schema_root() + child_path.substr(prefix.size());
        if (selected_schema_path.empty() ||
            !read_json_file(child_path, schema)) {
            return make_error(
                request, "schema", "ACTION_SCHEMA_NOT_FOUND",
                "schema not found for batch child " + child_action +
                    " response");
        }
    } else if (rel.empty() || !read_json_file(path, schema)) {
        return make_error(request, "schema", "ACTION_SCHEMA_NOT_FOUND", "schema not found for " + action + " " + kind);
    }
    Json examples = Json::array();
    const ActionSpec* example_spec = spec;
    if (action == "batch" && kind == "response" &&
        response_detail == "child")
        example_spec = default_action_registry().find_spec(child_action);
    const std::vector<std::string>& example_paths = kind == "request"
        ? example_spec->request_examples : example_spec->response_examples;
    for (const auto& example_rel : example_paths) {
        Json example;
        if (read_json_file(repo_root() + example_rel, example)) {
            examples.push_back({{"path", example_rel}, {"value", example}});
        }
    }
    Json constraints = schema.value("x-agent", Json::object()).value("constraints", Json::array());
    response["summary"] = {{"action", action}, {"kind", kind},
                           {"response_detail", response_detail},
                           {"selected_child", has_child_action
                                ? Json(child_action) : Json(nullptr)}};
    response["data"] = {{"schema", schema},
                        {"schema_path", selected_schema_path},
                        {"examples", examples}, {"constraints", constraints},
                        {"relation", nullptr}};
    if (action == "batch" && kind == "response") {
        response["data"]["relation"] = {
            {"full_schema_path", spec->response_schema},
            {"completeness", response_detail == "full"
                ? "complete-recursive-union"
                : response_detail == "child"
                    ? "selected-child-response"
                    : "outer-envelope-only"},
            {"child_selector", "args.child_action"},
        };
    }
    response["__xout"] = render_catalog_schema_xout(response);
    return response;
}

Json catalog_actions_response(const Json& request) {
    Json response = make_response(request, "actions");
    Json args = request.value("args", Json::object());
    Json output = args.value("output", Json::object());
    const std::string view = output.value("view", std::string());
    const bool verbose = output.value("verbose", false);
    Json filter = args.value("filter", Json::object());
    std::vector<ActionSpec> specs = filtered_specs(filter);
    if (view == "guide") {
        const std::string guide = concise_action_guide(specs);
        if (guide.size() > kActionGuideMaxBytes) {
            return make_error(
                request,
                "actions",
                "ACTION_GUIDE_TOO_LARGE",
                "action guide exceeds the 10000-byte limit",
                false);
        }
        response["summary"] = {
            {"action_count", specs.size()},
            {"total_action_count", default_action_registry().list_specs().size()},
            {"filtered", !filter.empty()},
            {"view", "guide"},
            {"guide_bytes", guide.size()},
            {"guide_limit_bytes", kActionGuideMaxBytes}
        };
        response["data"] = {
            {"guide", guide},
            {"filters", filter}
        };
        response["__xout"] = render_catalog_actions_xout(response);
        return response;
    }
    Json actions = filtered_action_payload(specs, verbose);
    response["summary"] = {
        {"action_count", actions.size()},
        {"total_action_count", default_action_registry().list_specs().size()},
        {"verbose", verbose},
        {"filtered", !filter.empty()}
    };
    response["data"] = {
        {"actions", actions},
        {"modes", filtered_modes(specs)},
        {"filters", filter}
    };
    response["__xout"] = render_catalog_actions_xout(response);
    return response;
}

} // namespace xdebug
