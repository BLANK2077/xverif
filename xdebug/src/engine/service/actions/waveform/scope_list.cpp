#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"

#include "core/output/completeness.h"
#include "design/hierarchy/relationship_walker.h"

#include "npi_fsdb.h"

#include <algorithm>
#include <cctype>
#include <fnmatch.h>
#include <functional>
#include <memory>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace xdebug_design {
namespace {

struct ScopeItem {
    std::string kind;
    std::string name;
    Json value;
};

std::string trim_copy(const std::string& text) {
    size_t begin = 0;
    while (begin < text.size() &&
           std::isspace(static_cast<unsigned char>(text[begin]))) {
        ++begin;
    }
    size_t end = text.size();
    while (end > begin &&
           std::isspace(static_cast<unsigned char>(text[end - 1]))) {
        --end;
    }
    return text.substr(begin, end - begin);
}

std::string fsdb_scope_string(npiFsdbScopePropertyType property,
                              npiFsdbScopeHandle scope) {
    const NPI_BYTE8* value =
        scope ? npi_fsdb_scope_property_str(property, scope) : nullptr;
    return value ? std::string(value) : std::string();
}

std::string fsdb_signal_string(npiFsdbSigPropertyType property,
                               npiFsdbSigHandle signal) {
    const NPI_BYTE8* value =
        signal ? npi_fsdb_sig_property_str(property, signal) : nullptr;
    return value ? std::string(value) : std::string();
}

bool fsdb_scope_integer(npiFsdbScopePropertyType property,
                        npiFsdbScopeHandle scope,
                        int& value) {
    value = 0;
    return scope &&
           npi_fsdb_scope_property(property, scope, &value);
}

bool fsdb_signal_integer(npiFsdbSigPropertyType property,
                         npiFsdbSigHandle signal,
                         int& value) {
    value = 0;
    return signal &&
           npi_fsdb_sig_property(property, signal, &value);
}

bool is_module_scope(npiFsdbScopeHandle scope) {
    int type = npiFsdbScopeUnknown;
    if (!fsdb_scope_integer(npiFsdbScopeType, scope, type)) return false;
    return type == npiFsdbScopeSvModule ||
           type == npiFsdbScopeVhArchitecture ||
           type == npiFsdbScopeScModule;
}

bool is_interface_instance_scope(npiFsdbScopeHandle scope) {
    int type = npiFsdbScopeUnknown;
    if (!fsdb_scope_integer(npiFsdbScopeType, scope, type)) return false;
    return type == npiFsdbScopeSvInterface;
}

bool is_interface_port_scope(npiFsdbScopeHandle scope) {
    int type = npiFsdbScopeUnknown;
    if (!fsdb_scope_integer(npiFsdbScopeType, scope, type)) return false;
    return type == npiFsdbScopeSvInterfacePort ||
           type == npiFsdbScopeSvModport ||
           type == npiFsdbScopeSvModportPort;
}

std::string relative_name(const std::string& full_name,
                          const std::string& base_path) {
    if (base_path.empty()) return full_name;
    if (full_name == base_path) return std::string();
    const std::string prefix = base_path + ".";
    if (full_name.compare(0, prefix.size(), prefix) == 0) {
        return full_name.substr(prefix.size());
    }
    return full_name;
}

bool contains_regex_hint(const std::string& pattern) {
    static const std::string hints = "[]{}^$()|+";
    return pattern.find_first_of(hints) != std::string::npos;
}

bool matches_any(const Json& patterns, const std::string& value) {
    for (const auto& pattern : patterns) {
        if (fnmatch(pattern.get<std::string>().c_str(), value.c_str(), 0) == 0) {
            return true;
        }
    }
    return false;
}

class ScopeListHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "scope.list"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return false; }

    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string requested_path = trim_copy(
            args.value("path", std::string("")));
        if (requested_path == ".") requested_path.clear();
        int level = args.value("level", 0);
        const std::string source = args.value("source", std::string("wave"));
        std::string kind = args.value("kind", std::string("all"));
        Json include_patterns = args["include_patterns"].exists()
            ? args["include_patterns"].consume_subtree(
                  "scope.list.include_patterns")
            : Json::array();
        Json exclude_patterns = args["exclude_patterns"].exists()
            ? args["exclude_patterns"].consume_subtree(
                  "scope.list.exclude_patterns")
            : Json::array();
        const std::set<std::string> supported_kinds = {
            "all", "module", "interface", "interface_array", "gen_scope",
            "internal_scope", "modport", "mpport", "port", "signal"};
        if (source != "wave" && source != "design" && source != "merged") {
            return make_handler_error(
                "INVALID_REQUEST",
                "scope.list args.source must be wave, design, or merged",
                {{"invalid_arg", "args.source"},
                 {"available_values", Json::array({"wave", "design", "merged"})}});
        }
        if (supported_kinds.find(kind) == supported_kinds.end()) {
            return make_handler_error(
                "INVALID_REQUEST",
                "scope.list args.kind is not supported",
                {{"invalid_arg", "args.kind"},
                 {"available_values",
                  Json::array({"all", "module", "interface", "interface_array",
                               "gen_scope", "internal_scope", "modport", "mpport",
                               "port", "signal"})}});
        }
        const bool want_wave = source == "wave" || source == "merged";
        const bool want_design = source == "design" || source == "merged";
        const bool wave_available = g_has_waveform && g_fsdb_file;
        const bool design_available = g_has_design;
        if ((want_wave && !wave_available) || (want_design && !design_available)) {
            return make_handler_error(
                "RESOURCE_UNAVAILABLE",
                "scope.list requested a source that is not loaded",
                {{"invalid_arg", "args.source"},
                 {"missing_resource", !wave_available && want_wave
                                          ? "waveform" : "design database"}});
        }
        for (const char* field : {"include_patterns", "exclude_patterns"}) {
            const Json& patterns =
                std::string(field) == "include_patterns"
                    ? include_patterns : exclude_patterns;
            for (const auto& pattern : patterns) {
                const std::string value = pattern.get<std::string>();
                if (contains_regex_hint(value)) {
                    return make_handler_error(
                        "REGEX_NOT_SUPPORTED",
                        "scope.list supports only glob '*' and '?' patterns",
                        {{"invalid_arg", std::string("args.") + field},
                         {"expected", "glob patterns using only '*' and '?'"},
                         {"received", value}});
                }
            }
        }
        auto limits = request.limits();
        int max_rows = limits.value("max_rows", -1);

        npiFsdbScopeHandle root_scope = nullptr;
        std::string path = requested_path;
        if (want_wave && !requested_path.empty()) {
            root_scope = npi_fsdb_scope_by_name(
                g_fsdb_file, requested_path.c_str(), nullptr);
            if (root_scope) {
                path = fsdb_scope_string(
                    npiFsdbScopeFullName, root_scope);
                if (path.empty()) path = requested_path;
            }
        }
        if (want_wave && !requested_path.empty() && !root_scope) {
            return make_handler_error(
                "SCOPE_NOT_FOUND",
                "waveform scope not found: " + requested_path,
                {{"invalid_arg", "args.path"},
                 {"missing_name", requested_path},
                 {"missing_resource", "waveform scope"},
                 {"expected", "existing waveform scope path; use an empty path only for roots"},
                 {"correct_example", {{"api_version", "xdebug.v1"},
                                       {"action", "scope.list"},
                                       {"target", {{"session_id", "wave0"}}},
                                       {"args", {{"path", "top"},
                                                 {"level", 0}}}}},
                 {"next_actions", Json::array({"Call scope.roots to discover valid root paths."})}});
        }

        size_t scanned_row_count = 0;
        std::vector<ScopeItem> matched_items;
        std::map<std::pair<std::string, std::string>, std::size_t> item_indexes;
        std::set<std::string> declared_composite_objects;

        auto add_item = [&](const std::string& item_kind,
                            const std::string& name,
                            const Json& value) {
            if (name.empty()) return;
            ++scanned_row_count;
            if (kind != "all" && kind != item_kind) return;
            if (!include_patterns.empty() &&
                !matches_any(include_patterns, name)) {
                return;
            }
            if (!exclude_patterns.empty() &&
                matches_any(exclude_patterns, name)) {
                return;
            }
            Json normalized = value;
            if (!normalized.contains("name")) normalized["name"] = name;
            if (!normalized.contains("path"))
                normalized["path"] = path.empty() ? name : path + "." + name;
            normalized["kind"] = item_kind;
            if (!normalized.contains("sources"))
                normalized["sources"] = Json::array({"wave"});
            if (!normalized.contains("queryable")) normalized["queryable"] = true;
            if (!normalized.contains("traceable")) normalized["traceable"] = false;
            const auto identity = std::make_pair(
                item_kind, normalized.value("path", name));
            const auto existing = item_indexes.find(identity);
            if (existing == item_indexes.end()) {
                item_indexes.emplace(identity, matched_items.size());
                matched_items.push_back({item_kind, name, normalized});
                return;
            }
            Json& prior = matched_items[existing->second].value;
            for (const auto& item_source : normalized["sources"]) {
                bool present = false;
                for (const auto& prior_source : prior["sources"])
                    if (prior_source == item_source) present = true;
                if (!present) prior["sources"].push_back(item_source);
            }
            prior["queryable"] = prior.value("queryable", false) ||
                                   normalized.value("queryable", false);
            prior["traceable"] = prior.value("traceable", false) ||
                                  normalized.value("traceable", false);
        };

        auto add_signals = [&](npiFsdbScopeHandle scope) {
            const std::string scope_path = fsdb_scope_string(
                npiFsdbScopeFullName, scope);
            npiFsdbSigIter iter = ctx.resources.own_fsdb_sig_iter(
                npi_fsdb_iter_sig(scope));
            if (!iter) return;
            while (npiFsdbSigHandle signal =
                       npi_fsdb_iter_sig_next(iter)) {
                const std::string full_name = fsdb_signal_string(
                    npiFsdbSigFullName, signal);
                int member_direction = npiFsdbDirNone;
                const bool member_has_direction = fsdb_signal_integer(
                    npiFsdbSigDirection, signal, member_direction);
                npiFsdbSigHandle declared_signal = signal;
                while (npiFsdbSigHandle parent =
                           npi_fsdb_parent_sig(declared_signal)) {
                    declared_signal = parent;
                }
                if (declared_signal != signal) {
                    const std::string declared_full_name =
                        fsdb_signal_string(
                            npiFsdbSigFullName, declared_signal);
                    const std::string declared_name =
                        relative_name(declared_full_name, path);
                    if (declared_composite_objects.insert(
                            declared_name).second) {
                        int declared_direction = npiFsdbDirNone;
                        const bool declared_has_direction =
                            fsdb_signal_integer(
                                npiFsdbSigDirection,
                                declared_signal,
                                declared_direction);
                        int declared_width_value = 0;
                        const bool declared_has_width =
                            fsdb_signal_integer(
                                npiFsdbSigRangeSize,
                                declared_signal,
                                declared_width_value) &&
                            declared_width_value > 0;
                        Json declared_width = declared_has_width
                            ? Json(declared_width_value) : Json(nullptr);
                        if (declared_has_direction &&
                            (declared_direction == npiFsdbDirInput ||
                             declared_direction == npiFsdbDirOutput ||
                             declared_direction == npiFsdbDirInout)) {
                            const std::string direction_name =
                                declared_direction == npiFsdbDirInput
                                    ? "input"
                                    : declared_direction == npiFsdbDirOutput
                                        ? "output" : "inout";
                            add_item(
                                "port", declared_name,
                                {{"name", declared_name},
                                 {"direction", direction_name},
                                 {"width", declared_width}});
                        } else if (
                            member_has_direction &&
                            (member_direction == npiFsdbDirInput ||
                             member_direction == npiFsdbDirOutput ||
                             member_direction == npiFsdbDirInout)) {
                            add_item(
                                "port", declared_name,
                                {{"name", declared_name},
                                 {"direction", "interface"},
                                 {"width", nullptr}});
                        } else {
                            add_item(
                                "signal", declared_name,
                                {{"name", declared_name},
                                 {"width", declared_width}});
                        }
                    }
                    continue;
                }
                const std::string scope_relative_name =
                    relative_name(full_name, scope_path);
                const size_t separator =
                    scope_relative_name.find('.');
                if (separator != std::string::npos) {
                    const std::string candidate_path =
                        scope_path + "." +
                        scope_relative_name.substr(0, separator);
                    npiFsdbScopeHandle candidate_scope =
                        npi_fsdb_scope_by_name(
                            g_fsdb_file, candidate_path.c_str(), nullptr);
                    if (!candidate_scope ||
                        is_interface_instance_scope(candidate_scope) ||
                        is_interface_port_scope(candidate_scope)) {
                        const std::string interface_name =
                            relative_name(candidate_path, path);
                        if (declared_composite_objects.insert(
                                interface_name).second) {
                            add_item("port", interface_name,
                                     {{"name", interface_name},
                                      {"direction", "interface"},
                                      {"width", nullptr}});
                        }
                        continue;
                    }
                }
                const std::string name = relative_name(full_name, path);
                int width_value = 0;
                const bool has_width = fsdb_signal_integer(
                    npiFsdbSigRangeSize, signal, width_value) &&
                    width_value > 0;
                Json width = has_width ? Json(width_value) : Json(nullptr);
                if (member_has_direction &&
                    (member_direction == npiFsdbDirInput ||
                     member_direction == npiFsdbDirOutput ||
                     member_direction == npiFsdbDirInout)) {
                    std::string direction_name =
                        member_direction == npiFsdbDirInput ? "input" :
                        member_direction == npiFsdbDirOutput
                            ? "output" : "inout";
                    add_item("port", name,
                             {{"name", name},
                              {"direction", direction_name},
                              {"width", width}});
                } else {
                    add_item("signal", name,
                             {{"name", name}, {"width", width}});
                }
            }
        };

        std::function<void(npiFsdbScopeHandle, int)> visit_scope;
        visit_scope = [&](npiFsdbScopeHandle scope, int entered_depth) {
            add_signals(scope);
            npiFsdbScopeIter iter = ctx.resources.own_fsdb_scope_iter(
                npi_fsdb_iter_child_scope(scope));
            if (!iter) return;
            while (npiFsdbScopeHandle child =
                       npi_fsdb_iter_scope_next(iter)) {
                if (is_module_scope(child)) {
                    const std::string full_name = fsdb_scope_string(
                        npiFsdbScopeFullName, child);
                    const std::string name =
                        relative_name(full_name, path);
                    const std::string module_name = fsdb_scope_string(
                        npiFsdbScopeDefName, child);
                    add_item("module", name,
                             {{"name", name},
                              {"module_name",
                               module_name.empty()
                                   ? Json(nullptr) : Json(module_name)}});
                    if (entered_depth < level) {
                        visit_scope(child, entered_depth + 1);
                    }
                } else if (is_interface_instance_scope(child)) {
                    const std::string full_name = fsdb_scope_string(
                        npiFsdbScopeFullName, child);
                    const std::string name =
                        relative_name(full_name, path);
                    add_item("signal", name,
                             {{"name", name}, {"width", nullptr}});
                } else if (is_interface_port_scope(child)) {
                    const std::string full_name = fsdb_scope_string(
                        npiFsdbScopeFullName, child);
                    const std::string name =
                        relative_name(full_name, path);
                    add_item("port", name,
                             {{"name", name},
                              {"direction", "interface"},
                              {"width", nullptr}});
                } else {
                    visit_scope(child, entered_depth);
                }
            }
        };

        if (want_wave && root_scope &&
            !is_interface_instance_scope(root_scope) &&
            !is_interface_port_scope(root_scope)) {
            visit_scope(root_scope, 0);
        } else if (want_wave && !root_scope) {
            npiFsdbScopeIter iter = ctx.resources.own_fsdb_scope_iter(
                npi_fsdb_iter_top_scope(g_fsdb_file));
            if (!iter) {
                return make_handler_error(
                    "SCOPE_LIST_FAILED",
                    "failed to list waveform roots",
                    {{"missing_resource", "waveform scope roots"}});
            }
            while (npiFsdbScopeHandle top =
                       npi_fsdb_iter_scope_next(iter)) {
                if (is_module_scope(top)) {
                    const std::string full_name = fsdb_scope_string(
                        npiFsdbScopeFullName, top);
                    const std::string name = relative_name(full_name, path);
                    const std::string module_name = fsdb_scope_string(
                        npiFsdbScopeDefName, top);
                    add_item("module", name,
                             {{"name", name},
                              {"module_name",
                               module_name.empty()
                                   ? Json(nullptr) : Json(module_name)}});
                    if (level > 0) visit_scope(top, 1);
                } else if (is_interface_instance_scope(top)) {
                    const std::string full_name = fsdb_scope_string(
                        npiFsdbScopeFullName, top);
                    const std::string name =
                        relative_name(full_name, path);
                    add_item("signal", name,
                             {{"name", name}, {"width", nullptr}});
                } else if (is_interface_port_scope(top)) {
                    const std::string full_name = fsdb_scope_string(
                        npiFsdbScopeFullName, top);
                    const std::string name =
                        relative_name(full_name, path);
                    add_item("port", name,
                             {{"name", name},
                              {"direction", "interface"},
                              {"width", nullptr}});
                } else if (level > 0) {
                    visit_scope(top, 1);
                }
            }
        }

        const size_t wave_visited_count = scanned_row_count;
        DesignRelationshipWalkResult design_result;
        if (want_design) {
            constexpr std::size_t kDesignObjectBudget = 100000;
            design_result = walk_design_relationships(
                requested_path, level, kDesignObjectBudget, ctx.resources);
            if (!requested_path.empty() && !design_result.root_found) {
                return make_handler_error(
                    "SCOPE_NOT_FOUND",
                    "design scope not found: " + requested_path,
                    {{"invalid_arg", "args.path"},
                     {"missing_name", requested_path},
                     {"missing_resource", "design scope"}});
            }
            for (const auto& item : design_result.items) {
                Json value = {
                    {"name", item.name},
                    {"path", item.path},
                    {"kind", item.kind},
                    {"sources", Json::array({"design"})},
                    {"queryable", true},
                    {"traceable", item.kind == "module" ||
                                      item.kind == "interface" ||
                                      item.kind == "port" ||
                                      item.kind == "signal" ||
                                      item.kind == "mpport"}
                };
                if (!item.module_name.empty())
                    value["module_name"] = item.module_name;
                if (!item.direction.empty()) value["direction"] = item.direction;
                if (!item.array_path.empty()) value["array_path"] = item.array_path;
                add_item(item.kind, relative_name(item.path, path), value);
            }
        }

        std::sort(
            matched_items.begin(), matched_items.end(),
            [](const ScopeItem& lhs, const ScopeItem& rhs) {
                if (lhs.name != rhs.name) return lhs.name < rhs.name;
                return lhs.kind < rhs.kind;
            });

        size_t total_module_count = 0;
        size_t total_port_count = 0;
        size_t total_signal_count = 0;
        for (const auto& item : matched_items) {
            if (item.kind == "module") ++total_module_count;
            else if (item.kind == "port") ++total_port_count;
            else if (item.kind == "signal") ++total_signal_count;
        }

        Json modules = Json::array();
        Json ports = Json::array();
        Json signals = Json::array();
        Json interfaces = Json::array();
        Json interface_arrays = Json::array();
        Json gen_scopes = Json::array();
        Json internal_scopes = Json::array();
        Json modports = Json::array();
        Json mpports = Json::array();
        const size_t returned_limit =
            max_rows < 0
                ? matched_items.size()
                : std::min(matched_items.size(),
                           static_cast<size_t>(max_rows));
        for (size_t index = 0; index < returned_limit; ++index) {
            const ScopeItem& item = matched_items[index];
            if (item.kind == "module") modules.push_back(item.value);
            else if (item.kind == "port") ports.push_back(item.value);
            else if (item.kind == "signal") signals.push_back(item.value);
            else if (item.kind == "interface") interfaces.push_back(item.value);
            else if (item.kind == "interface_array") interface_arrays.push_back(item.value);
            else if (item.kind == "gen_scope") gen_scopes.push_back(item.value);
            else if (item.kind == "internal_scope") internal_scopes.push_back(item.value);
            else if (item.kind == "modport") modports.push_back(item.value);
            else if (item.kind == "mpport") mpports.push_back(item.value);
        }

        const size_t matched_row_count = matched_items.size();
        const size_t returned_row_count =
            modules.size() + ports.size() + signals.size() + interfaces.size() +
            interface_arrays.size() + gen_scopes.size() + internal_scopes.size() +
            modports.size() + mpports.size();
        const bool truncated = returned_row_count < matched_row_count;
        Json out;
        out["summary"] = {
            {"path", path},
            {"source", source},
            {"level", level},
            {"kind", kind},
            {"include_patterns", include_patterns},
            {"exclude_patterns", exclude_patterns},
            {"visited_count", static_cast<int>(
                wave_visited_count + design_result.visited_count)},
            {"scanned_row_count", static_cast<int>(scanned_row_count)},
            {"returned_module_count", static_cast<int>(modules.size())},
            {"returned_port_count", static_cast<int>(ports.size())},
            {"returned_signal_count", static_cast<int>(signals.size())},
            {"total_module_count", static_cast<int>(total_module_count)},
            {"total_port_count", static_cast<int>(total_port_count)},
            {"total_signal_count", static_cast<int>(total_signal_count)}
        };
        xdebug_core::set_completeness(
            out["summary"],
            !design_result.budget_exhausted,
            !design_result.budget_exhausted,
            truncated || design_result.budget_exhausted,
            matched_row_count,
            returned_row_count,
            design_result.budget_exhausted
                ? std::vector<std::string>{"analysis_objects"}
                : truncated
                    ? std::vector<std::string>{"response_rows"}
                    : std::vector<std::string>{});
        out["modules"] = modules;
        out["ports"] = ports;
        out["signals"] = signals;
        out["interfaces"] = interfaces;
        out["interface_arrays"] = interface_arrays;
        out["gen_scopes"] = gen_scopes;
        out["internal_scopes"] = internal_scopes;
        out["modports"] = modports;
        out["mpports"] = mpports;
        return out;
    }

    std::string render_xout(const Json& response) const override {
        Json projected = response;
        projected["summary"] = project_xout_summary_fields(
            response.value("summary", Json::object()),
            {"path", "source", "level", "kind", "scan_complete",
             "analysis_complete", "response_truncated", "total_count",
             "returned_count", "truncation_scopes"});
        return render_tabular_xout(action_name(), projected);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_scope_list_handler() {
    return std::unique_ptr<EngineActionHandler>(new ScopeListHandler);
}

}  // namespace xdebug_design
