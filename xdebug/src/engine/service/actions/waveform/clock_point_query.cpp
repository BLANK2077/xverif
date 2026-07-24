#include "clock_point_query.h"

#include "service/engine_action_handler.h"

#include "core/npi/time_contract.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/value/logic_value.h"

#include "npi_L1.h"

namespace xdebug_design {
namespace {

using xdebug_waveform::ClockEdgeKind;

Json invalid_arg(const std::string& arg, const std::string& expected) {
    return make_handler_error(
        "INVALID_ARGUMENT",
        "invalid clock sampling argument: " + arg,
        {{"invalid_arg", arg},
         {"expected", expected},
         {"correct_example", {{"api_version", "xdebug.v1"},
                              {"action", "value.at"},
                              {"target", {{"session_id", "case_a"}}},
                              {"args", {{"signal", "top.u.valid"},
                                        {"time", "10ns"},
                                        {"clock", "top.u.clk"}}}}},
         {"example_note", "Example only; use the same clock fields on value/list/verify actions that sample waveform values."}});
}

Json value_object(npiFsdbSigHandle signal, const std::string& raw, char fmt) {
    // The raw FSDB radix only affects parsing.  Display formatting is applied
    // once at the engine response boundary so all value-bearing fields agree.
    return xdebug_waveform::logic_value_json(
        xdebug_waveform::logic_value_from_fsdb_signal(signal, raw, fmt));
}

Json missing_edge_cell() {
    return Json{{"status", "missing_edge"}, {"value", nullptr}};
}

Json cell_json(npiFsdbFileHandle fsdb,
               npiFsdbSigHandle signal,
               const xdebug_waveform::ClockPointCell& cell,
               char prefix) {
    if (cell.status == "missing_edge") return missing_edge_cell();
    Json out = {{"status", cell.status.empty() ? "missing_value" : cell.status}};
    if (cell.status == "ok") {
        if (cell.has_value_time) out["time"] = xdebug_core::format_time(fsdb, cell.value_time);
        out["value"] = value_object(signal, cell.raw_value, prefix);
    } else {
        out["value"] = nullptr;
    }
    return out;
}

Json sample_rows_json(npiFsdbFileHandle fsdb,
                      const std::vector<xdebug_waveform::ClockPointRow>& rows,
                      const std::vector<xdebug_waveform::ClockPointSignal>& signals,
                      const char* key,
                      const Json& time,
                      char prefix) {
    if (time.is_null()) return Json::array();
    Json out = Json::array();
    for (size_t index = 0; index < rows.size(); ++index) {
        const auto& row = rows[index];
        const xdebug_waveform::ClockPointCell* cell = &row.middle;
        if (std::string(key) == "before") cell = &row.before;
        else if (std::string(key) == "after") cell = &row.after;
        out.push_back({{"signal", row.label},
                       {"path", row.path},
                       {"time", time},
                       {"cell", cell_json(
                           fsdb,
                           index < signals.size() ? signals[index].handle : nullptr,
                           *cell,
                           prefix)}});
    }
    return out;
}

} // namespace

bool parse_point_clock_args(const Json& args,
                            xdebug_waveform::ClockSampleSpec& spec,
                            Json& error) {
    static const char* legacy[] = {"clk", "sampling", "clock_edge", "posedge", "sample_offset", nullptr};
    for (int i = 0; legacy[i]; ++i) {
        if (args.contains(legacy[i])) {
            error = invalid_arg(std::string("args.") + legacy[i],
                                "use args.clock, args.edge, and args.sample_point");
            return false;
        }
    }
    spec = xdebug_waveform::ClockSampleSpec();
    if (!args.contains("clock") || !args["clock"].is_string() || args["clock"].get<std::string>().empty()) {
        error = make_handler_error(
            "MISSING_FIELD",
            "args.clock is required",
            {{"invalid_arg", "args.clock"},
             {"expected", "existing clock signal path"},
             {"correct_example", {{"api_version", "xdebug.v1"},
                                  {"action", "value.at"},
                                  {"target", {{"session_id", "case_a"}}},
                                  {"args", {{"signal", "top.u.valid"},
                                            {"time", "10ns"},
                                            {"clock", "top.u.clk"}}}}}});
        return false;
    }
    spec.clock = args["clock"].get<std::string>();
    std::string parse_error;
    if (!xdebug_waveform::parse_clock_edge_kind(args.value("edge", std::string("negedge")),
                                                spec.edge,
                                                parse_error)) {
        error = invalid_arg("args.edge", "posedge, negedge, or dual");
        error["message"] = parse_error;
        return false;
    }
    if (args.contains("sample_point")) {
        if (!args["sample_point"].is_string()) {
            error = invalid_arg("args.sample_point", "before or after");
            return false;
        }
        spec.has_sample_point = true;
        if (!xdebug_waveform::parse_clock_sample_point_kind(args["sample_point"].get<std::string>(),
                                                            spec.sample_point,
                                                            parse_error)) {
            error = invalid_arg("args.sample_point", "before or after");
            error["message"] = parse_error;
            return false;
        }
    }
    if (!xdebug_waveform::normalize_clock_sample_spec(nullptr, spec, parse_error)) return false;
    return true;
}

bool build_clock_point_query(npiFsdbFileHandle fsdb,
                             const xdebug_waveform::ClockSampleSpec& spec,
                             npiFsdbTime requested_time,
                             const std::string& formatted_requested_time,
                             const std::vector<PointSignalSpec>& signals,
                             npiFsdbValType value_type,
                             char value_prefix,
                             ClockPointQueryResult& out,
                             Json& error) {
    (void)formatted_requested_time;
    std::vector<xdebug_waveform::ClockPointSignal> point_signals;
    point_signals.reserve(signals.size());
    for (const auto& sig : signals) {
        point_signals.push_back({sig.label, sig.path,
            npi_fsdb_sig_by_name(fsdb, sig.path.c_str(), nullptr)});
    }

    xdebug_waveform::ClockPointResult point_result;
    std::string sampler_error;
    xdebug_waveform::ClockPointSampler sampler(fsdb, spec);
    if (!sampler.sample(requested_time, point_signals, value_type, value_prefix,
                        point_result, sampler_error)) {
        error = make_handler_error_from_message(sampler_error);
        return false;
    }

    Json rows = Json::array();
    for (size_t index = 0; index < point_result.rows.size(); ++index) {
        const auto& row_result = point_result.rows[index];
        npiFsdbSigHandle signal =
            index < point_signals.size() ? point_signals[index].handle : nullptr;
        Json row;
        row["signal"] = row_result.label;
        row["path"] = row_result.path;
        row["before"] = cell_json(fsdb, signal, row_result.before, value_prefix);
        row["middle"] = cell_json(fsdb, signal, row_result.middle, value_prefix);
        row["after"] = cell_json(fsdb, signal, row_result.after, value_prefix);
        rows.push_back(row);
    }

    Json context;
    context["clock"] = spec.clock;
    context["edge"] = xdebug_waveform::clock_edge_kind_text(spec.edge);
    context["requested_sampling"] = {{"edge", xdebug_waveform::clock_edge_kind_text(spec.edge)},
                                      {"sample_point", spec.has_sample_point
                                          ? Json(xdebug_waveform::clock_sample_point_text(spec.sample_point))
                                          : Json(nullptr)}};
    context["effective_sampling"] = {{"edge", xdebug_waveform::clock_edge_kind_text(spec.edge)},
                                      {"sample_point", spec.edge == ClockEdgeKind::Negedge
                                          ? Json(nullptr)
                                          : Json(xdebug_waveform::clock_sample_point_text(spec.sample_point))}};
    context["requested_time"] = xdebug_core::format_time(fsdb, point_result.context.requested_time);
    context["requested_any_edge_hit"] = point_result.context.clock_edge_hit;
    context["clock_edge_kind"] = point_result.context.has_clock_edge_kind
        ? Json(xdebug_waveform::clock_edge_kind_text(point_result.context.clock_edge_kind))
        : Json(nullptr);
    context["requested_target_edge_hit"] = point_result.context.target_edge_hit;
    context["sample_point_applied"] =
        point_result.context.target_edge_hit && spec.edge != ClockEdgeKind::Negedge
        ? Json(xdebug_waveform::clock_sample_point_text(spec.sample_point))
        : Json(nullptr);
    context["sample_point_ignored_for_negedge"] = spec.edge == ClockEdgeKind::Negedge && spec.has_sample_point;
    context["previous_sample_time"] = point_result.context.has_previous_sample_time
        ? Json(xdebug_core::format_time(fsdb, point_result.context.previous_sample_time)) : Json(nullptr);
    context["next_sample_time"] = point_result.context.has_next_sample_time
        ? Json(xdebug_core::format_time(fsdb, point_result.context.next_sample_time)) : Json(nullptr);
    context["bracket_complete"] = point_result.context.bracket_complete;

    out.clock_context = context;
    out.rows = rows;
    out.samples = {
        {"before", sample_rows_json(fsdb, point_result.rows, point_signals, "before",
            context["previous_sample_time"], value_prefix)},
        {"middle", sample_rows_json(fsdb, point_result.rows, point_signals, "middle",
            context["requested_time"], value_prefix)},
        {"after", sample_rows_json(fsdb, point_result.rows, point_signals, "after",
            context["next_sample_time"], value_prefix)}
    };
    return true;
}

Json point_cell_value(const Json& row, const char* key) {
    if (!row.contains(key) || !row[key].is_object()) return Json();
    const Json& cell = row[key];
    if (cell.value("status", std::string()) != "ok") return cell.value("status", std::string());
    return cell.value("value", Json());
}

} // namespace xdebug_design
