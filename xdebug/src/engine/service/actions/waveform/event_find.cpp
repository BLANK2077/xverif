#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
#include "event_action_helpers.h"

#include "api/text_response_builder.h"
#include "design/protocol/protocol.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/event/event_manager.h"
#include "waveform/event/event_analyzer.h"
#include "waveform/list/list_manager.h"
#include "waveform/list/signal_list.h"
#include "waveform/export/waveform_exporter.h"
#include "waveform/common/clock_sampling_response.h"
#include "waveform/common/expression.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/service/action_support.h"
#include "waveform/service/rc_generator.h"
#include "core/value/logic_value.h"
#include "core/npi/time_contract.h"

#include "npi.h"
#include "npi_fsdb.h"
#include "npi_L1.h"
#include "npi_hdl.h"

#include <fstream>
#include <memory>
#include <algorithm>
#include <map>
#include <set>
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

std::string render_event_find_xout(const Json& response) {
    Json metadata = response;
    if (metadata.contains("summary") && metadata["summary"].is_object()) {
        metadata["summary"].erase("width_diagnostics");
    }
    if (metadata.contains("data") && metadata["data"].is_object()) {
        metadata["data"].erase("events");
        metadata["data"].erase("sampling");
        if (metadata["data"].contains("summary") &&
            metadata["data"]["summary"].is_object()) {
            metadata["data"]["summary"].erase("width_diagnostics");
        }
    }
    std::string text = render_tabular_xout("event.find", metadata);

    const Json data = response.value("data", Json::object());
    const Json sampling = data.value("sampling", Json::object());
    const Json events = data.value("events", Json::array());
    if (sampling.is_object() && !sampling.empty()) {
        xdebug::TextResponseBuilder sampling_out("xdebug");
        const Json requested = sampling.value("requested", Json::object());
        sampling_out.emit_section("requested");
        if (requested.contains("edge")) sampling_out.emit_kv("edge", requested["edge"]);
        if (requested.contains("sample_point"))
            sampling_out.emit_kv("sample_point", requested["sample_point"]);
        const Json effective = sampling.value("effective", Json::object());
        sampling_out.emit_section("effective");
        if (effective.contains("edge")) sampling_out.emit_kv("edge", effective["edge"]);
        if (effective.contains("sample_point"))
            sampling_out.emit_kv("sample_point", effective["sample_point"]);
        if (sampling.contains("sample_point_applied"))
            sampling_out.emit_kv("sample_point_applied", sampling["sample_point_applied"]);
        if (sampling.contains("sample_point_ignored_for_negedge")) {
            sampling_out.emit_kv(
                "sample_point_ignored_for_negedge",
                sampling["sample_point_ignored_for_negedge"]);
        }
        if (sampling.contains("sample_point_not_applied_reason")) {
            sampling_out.emit_kv(
                "sample_point_not_applied_reason",
                sampling["sample_point_not_applied_reason"]);
        }
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text += "\n\n" + sampling_out.str();
    }
    if (!events.is_array() || events.empty()) return text;

    std::vector<std::string> columns{"time"};
    std::vector<std::string> signal_columns;
    std::vector<std::string> field_columns;
    std::set<std::string> seen_signals;
    std::set<std::string> seen_fields;
    for (const auto& event : events) {
        if (!event.is_object()) continue;
        const Json signals = event.value("signals", Json::object());
        if (signals.is_object()) {
            for (auto it = signals.begin(); it != signals.end(); ++it) {
                if (seen_signals.insert(it.key()).second) {
                    signal_columns.push_back(it.key());
                    columns.push_back(it.key());
                }
            }
        }
        const Json fields = event.value("fields", Json::object());
        if (fields.is_object()) {
            for (auto it = fields.begin(); it != fields.end(); ++it) {
                if (seen_fields.insert(it.key()).second) {
                    field_columns.push_back(it.key());
                    columns.push_back("field." + it.key());
                }
            }
        }
    }

    std::vector<std::vector<std::string>> rows;
    for (const auto& event : events) {
        if (!event.is_object()) continue;
        std::vector<std::string> row{
            xdebug::json_to_xout_value(event.value("time", Json()))};
        const Json signals = event.value("signals", Json::object());
        for (const auto& column : signal_columns) {
            row.push_back(signals.is_object() && signals.contains(column)
                ? xdebug::json_to_xout_value(signals[column])
                : std::string());
        }
        const Json fields = event.value("fields", Json::object());
        for (const auto& column : field_columns) {
            row.push_back(fields.is_object() && fields.contains(column)
                ? xdebug::json_to_xout_value(fields[column])
                : std::string());
        }
        rows.push_back(std::move(row));
    }

    xdebug::TextResponseBuilder out("xdebug");
    out.emit_section("events");
    out.emit_table(columns, rows);
    while (!text.empty() && text.back() == '\n') text.pop_back();
    text += "\n\n" + out.str();
    return text;
}

class EventFindHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "event.find"; }
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
                if (!parse_reset_config(reset_config, config.reset, edge_error))
                    return event_invalid_arg_error(action_name(), "args.reset", edge_error,
                                                   "reset object with signal and polarity");
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
            if (config.clock_sample.edge == ClockEdgeKind::Negedge &&
                config.clock_sample.has_sample_point)
                return event_invalid_arg_error(action_name(), "args.sample_point",
                                               "args.sample_point is only valid with edge:posedge or edge:dual",
                                               "omit sample_point for negedge, or use edge posedge/dual");
            ContractJsonView signals = args["signals"];
            Json sigs = signals.exists()
                ? signals.consume_subtree("event_find_inline_signal_map_parser")
                : Json::object();
            for (auto it = sigs.begin(); it != sigs.end(); ++it) {
                if (it->is_string()) config.signals[it.key()] = it->get<std::string>();
            }
            if (config.signals.empty())
                return event_missing_field_error(action_name(), "args.signals", "alias to real signal path map");
        }

        std::string clock_resolution_error;
        if (!normalize_clock_sample_spec(
                g_fsdb_file, config.clock_sample, clock_resolution_error)) {
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
        if (!parse_t(time_range.value("begin", ""), false, tbegin, time_error) ||
            !parse_t(time_range.value("end", ""), true, tend, time_error)) {
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
        std::string mode = args.value("mode", std::string("first"));
        if (mode == "head") mode = "first";
        if (mode == "tail") mode = "last";
        if (mode != "first" && mode != "last" && mode != "all") {
            return event_invalid_enum_error(action_name(), "args.mode",
                                            "args.mode must be first, last, or all",
                                            Json::array({"first", "last", "all"}));
        }

        if (mode == "first") {
            if (args.contains("line_limit"))
                return event_invalid_enum_error(action_name(), "args.line_limit",
                                                "line_limit is only valid with mode=all",
                                                Json::array({"omit line_limit"}));
            query.limit = 1;
            // The candidate-change fast path can skip a match when a sampled
            // signal changes on the same timestamp as the clock edge. Use the
            // full clock-edge scan here so "first" is semantically exact.
            query.fast_find = false;
        } else if (mode == "last") {
            if (args.contains("line_limit"))
                return event_invalid_enum_error(action_name(), "args.line_limit",
                                                "line_limit is only valid with mode=all",
                                                Json::array({"omit line_limit"}));
            query.limit = -1;
            query.retain_last_only = true;
        } else {
            query.limit = -1;
        }

        std::vector<EventRecord> records;
        std::string error;
        if (!g_event_analyzer.analyze(g_fsdb_file, config, query, records, error))
            return make_handler_error("ACTION_FAILED", error, {{"cause_code", "EVENT_FAILED"}});
        if (mode == "last" && records.size() > 1) {
            EventRecord last = records.back();
            records.assign(1, last);
        }

        const size_t matched_count = static_cast<size_t>(scan_stats.matched_count);
        const int response_limit = args.value("line_limit", 1000);
        Json arr = Json::array();
        size_t response_count = 0;
        for (auto& rec : records) {
            if (mode == "all" && response_limit >= 0 &&
                static_cast<int>(response_count) >= response_limit) break;
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
            ++response_count;
        }
        Json out;
        out["events"] = arr;
        out["summary"] = {
            {"total_count", static_cast<int>(matched_count)},
            {"returned_count", static_cast<int>(arr.size())},
            {"response_truncated", mode == "all" && arr.size() < matched_count},
            {"scan_complete", !scan_stats.sample_budget_exhausted},
            {"analysis_complete", !scan_stats.sample_budget_exhausted},
            {"sample_count", scan_stats.sample_count},
            {"mode", mode},
            {"inline", name.empty()},
            {"sampling_mode", "clock_edge"},
            {"clock", config.clock_sample.clock},
            {"sample_time_semantics", "time is sample_time"},
            {"truncation_scopes", Json::array()}
        };
        const bool response_truncated = mode == "all" && arr.size() < matched_count;
        if (scan_stats.sample_budget_exhausted)
            out["summary"]["truncation_scopes"].push_back("analysis_samples");
        if (response_truncated)
            out["summary"]["truncation_scopes"].push_back("response_events");
        if (scan_stats.matched_count > 0) {
            out["summary"]["first"] = xdebug_core::format_time(g_fsdb_file, scan_stats.first_match_time);
            out["summary"]["last"] = xdebug_core::format_time(g_fsdb_file, scan_stats.last_match_time);
        }
        auto formatted_range = xdebug_core::format_time_range(g_fsdb_file, tbegin, tend);
        out["summary"]["begin"] = formatted_range.first;
        out["summary"]["end"] = formatted_range.second;
        out["sampling"] = clock_sampling_contract_json(config.clock_sample);
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return render_event_find_xout(response);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_event_find_handler() {
    return std::unique_ptr<EngineActionHandler>(new EventFindHandler);
}

}  // namespace xdebug_design
