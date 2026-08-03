#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
#include "event_action_helpers.h"

#include "design/protocol/protocol.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/event/event_manager.h"
#include "waveform/event/event_analyzer.h"
#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"
#include "waveform/export/waveform_exporter.h"
#include "waveform/common/expression.h"
#include "waveform/common/clock_sampling_response.h"
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

static Json value_object(const std::string& raw) {
    return xdebug_core::logic_value_json(
        xdebug_core::logic_value_from_fsdb_raw(raw, 'h'));
}

static Json expression_alias_error(const char* action, const std::string& message) {
    return event_expression_alias_error(action, message);
}

static Json validate_expr_aliases(const std::string& action, const std::string& expr) {
    xdebug_waveform::Expression parsed;
    std::string error;
    if (!parsed.parse(expr, error)) {
        return expression_alias_error(action.c_str(), error);
    }
    std::vector<std::string> bad_aliases =
        xdebug_waveform::expression_aliases_that_look_like_paths(parsed.aliases());
    if (!bad_aliases.empty()) {
        return expression_alias_error(
            action.c_str(),
            "expression operands must be aliases, not direct signal paths: " +
            bad_aliases.front() + "; put real signal paths in args.signals");
    }
    return Json();
}

class EventHandler : public EngineActionHandler {
    bool export_mode_;
public:
    explicit EventHandler(bool export_mode) : export_mode_(export_mode) {}
    const char* action_name() const override { return export_mode_ ? "event.export" : "event.find"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(ContractBoundRequest& request, EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        std::string name = args.value("name", "");
        EventConfig config;

        if (!name.empty()) {
            EventManager em;
            StoreResult loaded =
                em.get_event(g_session_id, g_fsdb_file_path, name, config);
            if (loaded.status == StoreStatus::NotFound)
                return event_config_not_found_error(action_name(), name);
            if (!loaded.ok()) return make_config_store_error(loaded);
        } else {
            static const char* legacy[] = {"clk", "sampling", "clock_edge", "posedge", "sample_offset", nullptr};
            for (int i = 0; legacy[i]; ++i) {
                if (args.contains(legacy[i])) {
                    return event_invalid_arg_error(
                        action_name(),
                        std::string("args.") + legacy[i],
                        "legacy clock sampling field is not supported; use args.clock, args.edge, and args.sample_point",
                        "args.clock, args.edge, and args.sample_point");
                }
            }
            std::string clock = args.value("clock", "");
            if (clock.empty())
                return event_missing_field_error(action_name(), "args.clock", "clock alias or signal path for inline event config");
            config.clock_sample.clock = clock;
            std::string edge_error;
            ContractJsonView reset = args["reset"];
            config.has_reset = reset.exists();
            if (config.has_reset) {
                Json reset_config = {
                    {"signal", reset.value("signal", std::string())},
                    {"polarity", reset.value("polarity", std::string())}
                };
                if (!parse_reset_config(
                        reset_config,
                        config.reset,
                        edge_error)) {
                    return event_invalid_arg_error(
                        action_name(),
                        "args.reset",
                        edge_error,
                        "reset object with signal and polarity");
                }
            }
            if (!parse_clock_edge_kind(args.value("edge", std::string("negedge")),
                                       config.clock_sample.edge,
                                       edge_error)) {
                return event_invalid_enum_error(action_name(), "args.edge", edge_error,
                                                Json::array({"posedge", "negedge", "dual"}));
            }
            if (args.contains("sample_point")) {
                if (!args["sample_point"].is_string())
                    return event_invalid_arg_error(action_name(), "args.sample_point",
                                                   "args.sample_point must be before or after",
                                                   "before or after",
                                                   Json::array({"before", "after"}));
                config.clock_sample.has_sample_point = true;
                if (!parse_clock_sample_point_kind(args["sample_point"].get<std::string>(),
                                                   config.clock_sample.sample_point,
                                                   edge_error))
                    return event_invalid_enum_error(action_name(), "args.sample_point", edge_error,
                                                    Json::array({"before", "after"}));
            }
            ContractJsonView signals = args["signals"];
            Json sigs = signals.exists()
                ? signals.consume_subtree(
                      "event_inline_signal_map_parser")
                : Json::object();
            if (!sigs.is_object() || sigs.empty()) {
                return event_missing_field_error(
                    action_name(),
                    "args.signals",
                    "non-empty alias to real signal path map");
            }
            for (auto it = sigs.begin(); it != sigs.end(); ++it) {
                if (it.key().empty() || !it.value().is_string() ||
                    it.value().get<std::string>().empty()) {
                    return event_invalid_arg_error(
                        action_name(),
                        "args.signals",
                        "event signal aliases and paths must be non-empty strings",
                        "non-empty alias to non-empty waveform path map");
                }
                config.signals[it.key()] = it.value().get<std::string>();
            }
        }
        std::string clock_resolution_error;
        if (!normalize_clock_sample_spec(
                g_fsdb_file,
                config.clock_sample,
                clock_resolution_error)) {
            return make_handler_error_from_message(clock_resolution_error);
        }

        npiFsdbTime tbegin = 0, tend = ~0ULL;
        ContractJsonView time_range = args["time_range"];
        auto parse_t = [](const std::string& s, bool allow_max, npiFsdbTime& t, std::string& error) -> bool {
            if (s.empty()) return true;
            xdebug_core::TimeParseOptions options;
            options.allow_max = allow_max;
            options.default_unit = "ns";
            return xdebug_core::parse_time(g_fsdb_file, s, options, t, error);
        };
        std::string time_error;
        if (!parse_t(
                time_range.value("begin", ""),
                false,
                tbegin,
                time_error) ||
            !parse_t(
                time_range.value("end", ""),
                true,
                tend,
                time_error)) {
            return event_time_error(action_name(), time_error);
        }

        EventQuery query;
        query.expr = args.value("expr", "");
        Json expr_error = validate_expr_aliases(action_name(), query.expr);
        if (!expr_error.is_null()) return expr_error;
        query.begin = tbegin;
        query.end = tend;
        query.max_samples = args.value("max_samples", -1);
        EventScanStats scan_stats;
        query.stats = &scan_stats;
        std::string mode = args.value("mode", export_mode_ ? "export" : "first");
        if (!export_mode_ && mode != "first" && mode != "last" && mode != "all") {
            return event_invalid_enum_error(action_name(), "args.mode",
                                            "args.mode must be first, last, or all",
                                            Json::array({"first", "last", "all"}));
        }

        if (export_mode_) {
            int max_events = args.value("max_events", -1);
            query.limit = max_events > 0 ? max_events + 1 : -1;
        } else if (mode == "first") {
            query.limit = 1;
            // The candidate-change fast path can skip a match when a sampled
            // signal changes on the same timestamp as the clock edge. Use the
            // full clock-edge scan here so "first" is semantically exact.
            query.fast_find = false;
        } else if (mode == "last") {
            int limit = args.value("line_limit", 10000);
            query.limit = limit > 0 ? limit : 10000;
        } else {
            int limit = args.value("line_limit", 1000);
            query.limit = limit > 0 ? limit : 1000;
        }

        std::vector<EventRecord> records;
        std::string error;
        if (!g_event_analyzer.analyze(g_fsdb_file, config, query, records, error))
            return make_handler_error("ACTION_FAILED", error, {{"cause_code", "EVENT_FAILED"}});
        if (!export_mode_ && mode == "last" && records.size() > 1) {
            EventRecord last = records.back();
            records.assign(1, last);
        }

        const int max_events = args.value("max_events", -1);
        const bool event_budget_exhausted = max_events > 0 &&
            static_cast<int>(records.size()) > max_events;
        if (event_budget_exhausted) records.resize(max_events);
        const size_t matched_count = records.size();
        const int response_limit = args.value("line_limit", 1000);
        Json arr = Json::array();
        for (auto& rec : records) {
            Json je;
            je["time"] = xdebug_core::format_time(g_fsdb_file, rec.time);
            Json signal_values = Json::object();
            for (const auto& value : rec.signals)
                signal_values[value.first] = value_object(value.second);
            Json field_values = Json::object();
            for (const auto& value : rec.fields)
                field_values[value.first] = value_object(value.second);
            je["signals"] = signal_values;
            je["fields"] = field_values;
            arr.push_back(je);
        }
        Json preview_arr = Json::array();
        for (size_t i = 0; i < arr.size() &&
             (response_limit < 0 || static_cast<int>(i) < response_limit); ++i)
            preview_arr.push_back(arr[i]);
        Json out;
        bool include_events = true;
        ContractJsonView aggregate_args = args["aggregate"];
        if (export_mode_ && aggregate_args.exists()) {
            Json aggregate;
            aggregate["count"] = arr.size();
            Json groups = Json::object();
            ContractJsonView group_by_view = aggregate_args["group_by"];
            Json group_by = group_by_view.exists()
                ? group_by_view.consume_subtree(
                      "event_export_group_by_parser")
                : Json::array();
            if (group_by_view.exists() &&
                (!group_by.is_array() || group_by.empty())) {
                return event_invalid_arg_error(
                    action_name(),
                    "args.aggregate.group_by",
                    "group_by must be a non-empty array when present",
                    "configured event signal aliases or field names");
            }
            for (const auto& field : group_by) {
                if (!field.is_string() ||
                    field.get<std::string>().empty()) {
                    return event_invalid_arg_error(
                        action_name(),
                        "args.aggregate.group_by",
                        "group_by entries must be non-empty strings",
                        "configured event signal aliases or field names");
                }
                const std::string group_name =
                    field.get<std::string>();
                if (config.fields.find(group_name) ==
                        config.fields.end() &&
                    config.signals.find(group_name) ==
                        config.signals.end()) {
                    return event_invalid_arg_error(
                        action_name(),
                        "args.aggregate.group_by",
                        "unknown event group_by name: " + group_name,
                        "configured event signal aliases or field names");
                }
            }
            if (!group_by.empty()) {
                for (const auto& event : arr) {
                    std::string key;
                    for (const auto& field : group_by) {
                        std::string name = field.get<std::string>();
                        Json value;
                        if (event["fields"].contains(name)) value = event["fields"][name]["value"];
                        else if (event["signals"].contains(name)) value = event["signals"][name]["value"];
                        if (!key.empty()) key += "|";
                        key += name + "=" + value.get<std::string>();
                    }
                    groups[key] = groups.value(key, 0) + 1;
                }
            }
            aggregate["groups"] = groups;
            aggregate["group_count"] = groups.size();
            out["aggregate"] = aggregate;
            include_events = aggregate_args.value("events", true);
            if (!include_events && args.contains("line_limit")) {
                return event_invalid_arg_error(
                    action_name(),
                    "args.line_limit",
                    "event.export args.line_limit has no effect when aggregate.events=false",
                    "omit line_limit or set aggregate.events=true");
            }
        }
        if (include_events) {
            out["events"] = preview_arr;
        }
        out["summary"] = {
            {"sample_count", scan_stats.sample_count},
            {"mode", mode},
            {"inline", name.empty()},
            {"sampling_mode", "clock_edge"},
            {"clock", config.clock_sample.clock},
            {"sample_time_semantics", "time is sample_time"}
        };
        out["sampling"] =
            clock_sampling_contract_json(config.clock_sample);
        if (!arr.empty()) {
            out["summary"]["first"] = arr[0]["time"];
            out["summary"]["last"] = arr[arr.size()-1]["time"];
        }
        auto formatted_range = xdebug_core::format_time_range(g_fsdb_file, tbegin, tend);
        out["summary"]["begin"] = formatted_range.first;
        out["summary"]["end"] = formatted_range.second;
        ContractJsonView output = args["output"];
        std::string output_path = output.value("path", std::string());
        std::string file_format = output.value("file_format", std::string("json"));
        if (!output_path.empty() && args.contains("line_limit")) {
            return event_invalid_arg_error(
                action_name(),
                "args.line_limit",
                "event.export args.line_limit only controls preview rows and is not valid for file export",
                "omit line_limit when args.output.path is present");
        }
        if (output.contains("file_format") && output_path.empty()) {
            return event_invalid_arg_error(
                action_name(),
                "args.output.file_format",
                "output.file_format requires a non-empty output.path",
                "output object with both path and file_format");
        }
        if (file_format != "json")
            return event_invalid_enum_error(action_name(), "args.output.file_format",
                                            "event.export output.file_format must be json",
                                            Json::array({"json"}));
        out["summary"]["status"] = output_path.empty() ? "preview" : "written";
        out["summary"]["output_written"] = !output_path.empty();
        out["summary"]["row_count"] = static_cast<int>(arr.size());
        out["summary"]["line_limit"] = response_limit;
        const bool analysis_complete =
            !event_budget_exhausted && !scan_stats.sample_budget_exhausted;
        const bool response_truncated = preview_arr.size() < matched_count;
        std::vector<std::string> truncation_scopes;
        if (event_budget_exhausted) truncation_scopes.push_back("analysis_events");
        if (scan_stats.sample_budget_exhausted) truncation_scopes.push_back("analysis_samples");
        if (response_truncated) truncation_scopes.push_back("response_events");
        xdebug_core::set_completeness(
            out["summary"],
            analysis_complete,
            analysis_complete,
            response_truncated,
            matched_count,
            preview_arr.size(),
            truncation_scopes);
        if (!output_path.empty()) {
            std::string write_error;
            Json artifact = out;
            if (include_events) artifact["events"] = arr;
            if (!xdebug_waveform::write_text_file_creating_dirs(output_path, artifact.dump(2) + "\n", write_error))
                return make_handler_error("ACTION_FAILED", write_error, {{"cause_code", "EXPORT_FAILED"}});
            Json output_info = {{"path", output_path}, {"file_format", file_format}};
            out["summary"]["output"] = output_info;
            out.erase("events");
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_event_export_handler() {
    return std::unique_ptr<EngineActionHandler>(new EventHandler(true));
}

}  // namespace xdebug_design
