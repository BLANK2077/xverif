#include "api/action_catalog.h"
#include "api/action_registry_init.h"
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
    if (!action.empty()) {
        if (kind.empty()) kind = "request";
        const ActionSpec* spec = default_action_registry().find_spec(action);
        if (!spec) {
            Json suggestions = suggested_action_names(action);
            Json error = DiagnosticErrorBuilder::handler(
                             "UNKNOWN_ACTION", "unknown action: " + action)
                             .invalid_arg("args.action")
                             .received(action)
                             .available_values(suggestions)
                             .did_you_mean(suggestions.empty() ? "" : suggestions[0].get<std::string>())
                             .to_json();
            error["suggested_actions"] = suggestions;
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
                             .allowed_values(Json::array({"request", "response"}))
                             .example_note("示例仅说明 schema action 的 native JSON 形态；kind 必须是 request 或 response。")
                             .correct_example(example)
                             .to_json();
            return make_error(request, "schema", error);
        }
        const std::string prefix = "schemas/v1/actions/";
        std::string path = rel;
        if (path.compare(0, prefix.size(), prefix) == 0) path = schema_root() + path.substr(prefix.size());
        Json schema;
        if (rel.empty() || !read_json_file(path, schema)) {
            return make_error(request, "schema", "ACTION_SCHEMA_NOT_FOUND", "schema not found for " + action + " " + kind);
        }
        Json examples = Json::array();
        const std::vector<std::string>& example_paths =
            kind == "request" ? spec->request_examples : spec->response_examples;
        for (const auto& example_rel : example_paths) {
            Json example;
            if (read_json_file(repo_root() + example_rel, example)) {
                examples.push_back({{"path", example_rel}, {"value", example}});
            }
        }
        Json constraints = schema.value("x-agent", Json::object()).value("constraints", Json::array());
        response["summary"] = {{"action", action}, {"kind", kind}};
        response["data"] = {{"schema", schema}, {"schema_path", rel},
                            {"examples", examples}, {"constraints", constraints}};
        return response;
    }
    response["data"] = {
        {"api_version", kApiVersion},
        {"request", {
            {"required", Json::array({"api_version", "action"})},
            {"target_resources", Json::array({"daidir", "fsdb", "session_id"})},
            {"modes", Json::array({"design", "waveform", "combined"})}
        }},
        {"combined_action", {
            {"action", "trace.active_driver"},
            {"required_target", Json::array({"daidir", "fsdb"})},
            {"required_args", Json::array({"signal", "time"})},
            {"optional_args", Json::array({"include_control", "include_parity"})}
        }},
        {"contract", {
            {"source", "ActionRegistry"},
            {"schema_root", "xdebug/schemas/v1"},
            {"action_count", default_action_registry().list_specs().size()}
        }}
    };
    return response;
}

Json catalog_actions_response(const Json& request) {
    Json response = make_response(request, "actions");
    Json args = request.value("args", Json::object());
    Json output = args.value("output", Json::object());
    const bool verbose = output.value("verbose", false);
    Json filter = args.value("filter", Json::object());
    std::vector<ActionSpec> specs = filtered_specs(filter);
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
    return response;
}

} // namespace xdebug
