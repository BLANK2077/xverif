#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"

#include "api/text_response_builder.h"
#include "design/protocol/protocol.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/event/event_manager.h"
#include "waveform/event/event_analyzer.h"
#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"
#include "waveform/export/waveform_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/service/action_support.h"
#include "waveform/service/rc_generator.h"
#include "core/value/logic_value.h"
#include "core/output/completeness.h"
#include "core/npi/time_contract.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"
#include "npi_hdl.h"

#include <fstream>
#include <memory>
#include <algorithm>
#include <map>
#include <sstream>
#include <vector>

namespace xdebug_design {
namespace {

static std::string trim_copy(const std::string& text) {
    size_t begin = 0;
    while (begin < text.size() && std::isspace(static_cast<unsigned char>(text[begin]))) ++begin;
    size_t end = text.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return text.substr(begin, end - begin);
}
static std::string npi_str(NPI_INT32 property, npiHandle hdl) {
    const char* value = hdl ? npi_get_str(property, hdl) : nullptr;
    return value ? std::string(value) : std::string();
}
static std::string fsdb_scope_str(npiFsdbScopePropertyType property,
                                  npiFsdbScopeHandle scope) {
    const char* value = scope ? npi_fsdb_scope_property_str(property, scope) : nullptr;
    return value ? std::string(value) : std::string();
}
static int fsdb_scope_int(npiFsdbScopePropertyType property,
                          npiFsdbScopeHandle scope) {
    int value = 0;
    if (!scope || !npi_fsdb_scope_property(property, scope, &value)) return 0;
    return value;
}
static std::string normalize_root_path(std::string path) {
    path = trim_copy(path);
    while (!path.empty() && path[0] == '/') path.erase(path.begin());
    while (!path.empty() && path.back() == '/') path.pop_back();
    return path;
}
static std::string join_strings(const Json& arr) {
    std::ostringstream os;
    if (!arr.is_array()) return "";
    for (size_t i = 0; i < arr.size(); ++i) {
        if (i) os << ",";
        os << arr[i].get<std::string>();
    }
    return os.str();
}
static std::string object_string_field(const Json& obj, const char* key) {
    if (!obj.is_object()) return "";
    return obj.value(key, std::string());
}
class ScopeRootsHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "scope.roots"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return false; }

    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        auto args = request.args();
        std::string source = args.value("source", std::string("auto"));
        if (source.empty()) source = "auto";
        if (source != "auto" && source != "wave" && source != "design")
            return make_handler_error(
                "INVALID_ENUM",
                "args.source must be auto, wave, or design",
                {{"invalid_arg", "args.source"},
                 {"expected", "one of auto, wave, design"},
                 {"available_values", Json::array({"auto", "wave", "design"})},
                 {"correct_example", {{"api_version", "xdebug.v1"},
                                      {"action", "scope.roots"},
                                      {"target", {{"session_id", "case_a"}}},
                                      {"args", {{"source", "auto"}}}}},
                 {"example_note", "Example only; choose args.source from allowed_values."}});

        const bool want_wave = source == "auto" || source == "wave";
        const bool want_design = source == "auto" || source == "design";
        const bool wave_available = g_has_waveform && g_fsdb_file;
        const bool design_available = g_has_design;
        if ((source == "wave" && !wave_available) ||
            (source == "design" && !design_available)) {
            return make_handler_error(
                "RESOURCE_UNAVAILABLE",
                source + " roots requested but the resource is not loaded",
                {{"invalid_arg", "args.source"},
                 {"missing_resource", source == "wave" ? "waveform" : "design database"},
                 {"expected", source == "wave" ? "session with FSDB loaded" : "session with daidir loaded"},
                 {"correct_example", {{"api_version", "xdebug.v1"},
                                       {"action", "scope.roots"},
                                       {"target", {{"session_id", "case_a"}}},
                                       {"args", {{"source", "auto"}}}}},
                 {"next_actions", Json::array({"Open a session containing the requested resource.",
                                                "Use args.source=auto to inspect resources already loaded."})}});
        }
        Json limitations = Json::array();
        Json wave_roots = Json::array();
        Json wave_root_candidates = Json::array();
        Json design_roots = Json::array();

        if (want_wave) {
            if (g_has_waveform && g_fsdb_file) {
                wave_roots = collect_wave_roots(ctx, limitations);
                wave_root_candidates = wave_roots;
            } else {
                limitations.push_back("wave roots unavailable: waveform not loaded");
            }
        }
        if (want_design) {
            if (g_has_design) {
                if (wave_root_candidates.empty() && g_has_waveform && g_fsdb_file) {
                    Json candidate_limitations = Json::array();
                    wave_root_candidates = collect_wave_roots(ctx, candidate_limitations);
                }
                design_roots = collect_design_roots(ctx, limitations, wave_root_candidates);
            } else {
                limitations.push_back("design roots unavailable: design not loaded");
            }
        }

        Json roots = merge_roots(wave_roots, design_roots);
        int matched_count = 0;
        for (const auto& root : roots) {
            if (root.value("status", "") == "matched") ++matched_count;
        }

        Json recommended = nullptr;
        std::string reason = "none";
        if (roots.size() == 1) {
            recommended = roots[0].value("path", "");
            reason = "unique root";
        } else if (matched_count == 1) {
            for (const auto& root : roots) {
                if (root.value("status", "") == "matched") {
                    recommended = root.value("path", "");
                    reason = "unique matched root";
                    break;
                }
            }
        } else if (roots.empty()) {
            reason = "no roots discovered";
        } else if (matched_count > 1) {
            reason = "multiple matched roots";
        } else {
            reason = "multiple roots or design/wave mismatch";
        }

        Json out;
        out["roots"] = roots;
        out["wave_roots"] = wave_roots;
        out["design_roots"] = design_roots;
        const bool analysis_complete =
            (!want_wave || wave_available) &&
            (!want_design || design_available);
        out["summary"] = {
            {"source", source},
            {"wave_available", wave_available},
            {"design_available", design_available},
            {"resource_available", source == "wave" ? wave_available :
                                   source == "design" ? design_available :
                                   (wave_available || design_available)},
            {"root_count", static_cast<int>(roots.size())},
            {"wave_count", static_cast<int>(wave_roots.size())},
            {"design_count", static_cast<int>(design_roots.size())},
            {"matched_count", matched_count},
            {"recommended_root", recommended},
            {"recommended_reason", reason}
        };
        xdebug_core::set_completeness(
            out["summary"],
            analysis_complete,
            analysis_complete,
            false,
            roots.size(),
            roots.size(),
            analysis_complete
                ? std::vector<std::string>{}
                : std::vector<std::string>{"analysis_sources"});
        if (!limitations.empty()) out["limitations"] = limitations;
        return out;
    }

    std::string render_xout(const Json& response) const override {
        xdebug::TextResponseBuilder out("xdebug");
        out.emit_header(action_name());
        const Json summary = response.value("summary", Json::object());
        out.emit_section("summary");
        out.emit_kv("recommended",
                    summary.value("recommended_root", Json(nullptr)).is_null()
                        ? "none (" + summary.value("recommended_reason", std::string("unknown")) + ")"
                        : summary.value("recommended_root", std::string()));
        out.emit_kv("source", summary.value("source", std::string("auto")));
        out.emit_kv("roots", summary.value("root_count", 0));
        out.emit_kv("matched", summary.value("matched_count", 0));
        out.emit_kv("wave", summary.value("wave_count", 0));
        out.emit_kv("design", summary.value("design_count", 0));

        const Json data = response.value("data", Json::object());
        const Json roots = data.value("roots", Json::array());
        out.emit_section("roots");
        std::vector<std::vector<std::string>> rows;
        for (const auto& root : roots) {
            rows.push_back({
                root.value("path", std::string()),
                root.value("status", std::string()),
                join_strings(root.value("sources", Json::array())),
                object_string_field(root.value("wave", Json()), "full_name"),
                object_string_field(root.value("design", Json()), "full_name")
            });
        }
        if (roots.empty()) rows.push_back({"[empty]", "", "", "", ""});
        out.emit_table({"path", "status", "sources", "wave", "design"}, rows);

        const Json limitations = data.value("limitations", Json::array());
        if (!limitations.empty()) {
            out.emit_section("limitations");
            for (const auto& item : limitations)
                out.emit_row({xdebug::json_to_xout_value(item)});
        }
        return out.str();
    }

private:
    static Json collect_wave_roots(EngineActionContext& ctx, Json& limitations) {
        Json roots = Json::array();
        npiFsdbScopeIter iter = ctx.resources.own_fsdb_scope_iter(
            npi_fsdb_iter_top_scope(g_fsdb_file));
        if (!iter) {
            limitations.push_back("wave root iterator returned no scopes");
            return roots;
        }
        while (npiFsdbScopeHandle scope = npi_fsdb_iter_scope_next(iter)) {
            Json root;
            std::string full_name = fsdb_scope_str(npiFsdbScopeFullName, scope);
            std::string name = fsdb_scope_str(npiFsdbScopeName, scope);
            if (full_name.empty()) full_name = name;
            root["path"] = normalize_root_path(full_name);
            root["name"] = name;
            root["full_name"] = full_name;
            root["def_name"] = fsdb_scope_str(npiFsdbScopeDefName, scope);
            root["type"] = fsdb_scope_int(npiFsdbScopeType, scope);
            root["queryable"] = true;
            roots.push_back(root);
        }
        return roots;
    }

    static Json collect_design_roots(EngineActionContext& ctx, Json& limitations, const Json& wave_candidates) {
        Json roots = Json::array();
        npiHandle iter = ctx.resources.own_npi(npi_iterate(npiTop, nullptr));
        if (iter) {
            while (npiHandle hdl = ctx.resources.own_npi(npi_scan(iter))) {
                Json root = design_root_from_handle(hdl, "npi_top");
                if (!root.value("path", std::string()).empty()) roots.push_back(root);
            }
        }
        if (!roots.empty()) return roots;

        for (const auto& candidate : wave_candidates) {
            std::string path = candidate.value("path", std::string());
            if (path.empty()) continue;
            npiHandle hdl = ctx.resources.own_npi(npi_handle_by_name(path.c_str(), nullptr));
            if (!hdl) continue;
            int type = npi_get(npiType, hdl);
            if (type != npiModule && type != npiInterface && type != npiProgram) continue;
            Json root = design_root_from_handle(hdl, "verified_wave_root");
            if (!root.value("path", std::string()).empty()) roots.push_back(root);
        }
        if (roots.empty()) limitations.push_back("design root discovery returned no top handles");
        return roots;
    }

    static Json design_root_from_handle(npiHandle hdl, const std::string& discovery) {
        Json root;
        std::string full_name = npi_str(npiFullName, hdl);
        std::string name = npi_str(npiName, hdl);
        if (full_name.empty()) full_name = name;
        root["path"] = normalize_root_path(full_name);
        root["name"] = name;
        root["full_name"] = full_name;
        root["def_name"] = npi_str(npiDefName, hdl);
        int type = npi_get(npiType, hdl);
        if (type == npiModule) root["kind"] = "module";
        else if (type == npiInterface) root["kind"] = "interface";
        else if (type == npiProgram) root["kind"] = "program";
        else root["kind"] = "scope";
        root["discovery"] = discovery;
        root["traceable"] = true;
        return root;
    }

    static Json merge_roots(const Json& wave_roots, const Json& design_roots) {
        struct Entry {
            Json wave = nullptr;
            Json design = nullptr;
        };
        std::map<std::string, Entry> by_path;
        for (const auto& root : wave_roots) {
            std::string path = normalize_root_path(root.value("path", std::string()));
            if (!path.empty()) by_path[path].wave = root;
        }
        for (const auto& root : design_roots) {
            std::string path = normalize_root_path(root.value("path", std::string()));
            if (!path.empty()) by_path[path].design = root;
        }

        Json roots = Json::array();
        for (auto& kv : by_path) {
            Json item;
            item["path"] = kv.first;
            item["sources"] = Json::array();
            item["wave"] = kv.second.wave;
            item["design"] = kv.second.design;
            const bool has_wave = !kv.second.wave.is_null();
            const bool has_design = !kv.second.design.is_null();
            if (has_design) item["sources"].push_back("design");
            if (has_wave) item["sources"].push_back("wave");
            if (has_design && has_wave) item["status"] = "matched";
            else if (has_design) item["status"] = "design_only";
            else item["status"] = "wave_only";
            roots.push_back(item);
        }
        return roots;
    }

};

}  // namespace

std::unique_ptr<EngineActionHandler> make_scope_roots_handler() {
    return std::unique_ptr<EngineActionHandler>(new ScopeRootsHandler);
}

}  // namespace xdebug_design
