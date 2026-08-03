#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"

#include "core/output/completeness.h"

#include "npi_fsdb.h"

#include <algorithm>
#include <cctype>
#include <fnmatch.h>
#include <functional>
#include <memory>
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
    bool needs_waveform() const override { return true; }

    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string requested_path = trim_copy(
            args.value("path", std::string("")));
        if (requested_path == ".") requested_path.clear();
        int level = args.value("level", 0);
        std::string kind = args.value("kind", std::string("all"));
        Json include_patterns = args["include_patterns"].exists()
            ? args["include_patterns"].consume_subtree(
                  "scope.list.include_patterns")
            : Json::array();
        Json exclude_patterns = args["exclude_patterns"].exists()
            ? args["exclude_patterns"].consume_subtree(
                  "scope.list.exclude_patterns")
            : Json::array();
        if (kind != "all" && kind != "module" &&
            kind != "port" && kind != "signal") {
            return make_handler_error(
                "INVALID_REQUEST",
                "scope.list args.kind must be all, module, port, or signal",
                {{"invalid_arg", "args.kind"},
                 {"available_values",
                  Json::array({"all", "module", "port", "signal"})}});
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
        std::string path;
        if (!requested_path.empty()) {
            root_scope = npi_fsdb_scope_by_name(
                g_fsdb_file, requested_path.c_str(), nullptr);
            if (root_scope) {
                path = fsdb_scope_string(
                    npiFsdbScopeFullName, root_scope);
                if (path.empty()) path = requested_path;
            }
        }
        if (!requested_path.empty() && !root_scope) {
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
            matched_items.push_back({item_kind, name, value});
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

        if (root_scope &&
            !is_interface_instance_scope(root_scope) &&
            !is_interface_port_scope(root_scope)) {
            visit_scope(root_scope, 0);
        } else if (!root_scope) {
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
            else ++total_signal_count;
        }

        Json modules = Json::array();
        Json ports = Json::array();
        Json signals = Json::array();
        const size_t returned_limit =
            max_rows < 0
                ? matched_items.size()
                : std::min(matched_items.size(),
                           static_cast<size_t>(max_rows));
        for (size_t index = 0; index < returned_limit; ++index) {
            const ScopeItem& item = matched_items[index];
            if (item.kind == "module") modules.push_back(item.value);
            else if (item.kind == "port") ports.push_back(item.value);
            else signals.push_back(item.value);
        }

        const size_t matched_row_count = matched_items.size();
        const size_t returned_row_count =
            modules.size() + ports.size() + signals.size();
        const bool truncated = returned_row_count < matched_row_count;
        Json out;
        out["summary"] = {
            {"path", path},
            {"level", level},
            {"kind", kind},
            {"include_patterns", include_patterns},
            {"exclude_patterns", exclude_patterns},
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
            true,
            true,
            truncated,
            matched_row_count,
            returned_row_count,
            truncated
                ? std::vector<std::string>{"response_rows"}
                : std::vector<std::string>{});
        out["modules"] = modules;
        out["ports"] = ports;
        out["signals"] = signals;
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return render_tabular_xout(action_name(), response);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_scope_list_handler() {
    return std::unique_ptr<EngineActionHandler>(new ScopeListHandler);
}

}  // namespace xdebug_design
