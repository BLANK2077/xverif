#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "clock_point_query.h"
#include "waveform_action_error_helpers.h"

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
#include "waveform/value/logic_value.h"
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

static bool contains_xz(const std::string& v) {
    return xdebug_waveform::logic_value_has_xz(
        xdebug_waveform::logic_value_from_fsdb_raw(v, 'h'));
}
static std::string trim_copy(const std::string& text) {
    size_t begin = 0;
    while (begin < text.size() && std::isspace(static_cast<unsigned char>(text[begin]))) ++begin;
    size_t end = text.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return text.substr(begin, end - begin);
}
static std::string with_value_prefix(const std::string& raw, char fmt) {
    std::string text = trim_copy(raw);
    if (text.size() >= 2 && text[0] == '\'') return text;
    return std::string("'") + static_cast<char>(std::tolower(static_cast<unsigned char>(fmt))) + text;
}
static Json make_xbit_hints(const Json& args,
                            const std::string& signal,
                            const std::string& raw) {
    if (!args.contains("slice_hint") || !args["slice_hint"].is_object()) return Json();
    Json hint = args["slice_hint"];
    long long width = hint.value("chunk_width", 0LL);
    long long count = hint.value("count", 1LL);
    if (width <= 0) {
        return Json{{"status", "needs_slice_hint"}, {"signal", signal},
                    {"raw_value", trim_copy(raw)}};
    }
    if (count <= 0) count = 1;
    Json slices = Json::array();
    Json commands = Json::array();
    for (long long i = 0; i < count; ++i) {
        long long lo = i * width;
        long long hi = lo + width - 1;
        slices.push_back({{"index", i},
                          {"range", "[" + std::to_string(hi) + ":" + std::to_string(lo) + "]"}});
        commands.push_back("tools/xbit slice \"" + trim_copy(raw) + "\" " +
                           std::to_string(hi) + " " + std::to_string(lo) + " --json");
    }
    return Json{{"status", "ready"}, {"signal", signal}, {"raw_value", trim_copy(raw)},
                {"chunk_width", width}, {"count", count}, {"slices", slices},
                {"commands", commands}};
}

class ValueAtHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "value.at"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext& ctx) const override {
        Json args = request.value("args", Json::object());
        std::string signal = args.value("signal", std::string());
        std::string time_str = args.value("time", args.value("at", std::string()));
        if (signal.empty() || time_str.empty())
            return waveform_missing_field_error(
                action_name(),
                signal.empty() ? "args.signal" : "args.time",
                "args.signal and args.time are required");

        const bool clock_sampled = args.contains("clock");
        if (!clock_sampled && (args.contains("edge") || args.contains("sample_point"))) {
            return waveform_invalid_arg_error(
                action_name(), args.contains("edge") ? "args.edge" : "args.sample_point",
                "edge and sample_point require args.clock",
                "omit edge/sample_point for a raw-time read, or provide args.clock");
        }
        xdebug_waveform::ClockSampleSpec clock_spec;
        Json clock_error;
        if (clock_sampled && !parse_point_clock_args(args, clock_spec, clock_error)) return clock_error;

        if (args.value("format", std::string()) == "array_indexed") {
            return make_handler_error("UNSUPPORTED_AGGREGATE_QUERY",
                "aggregate and indexed-element reads are not supported by this FSDB/NPI capability profile",
                {{"invalid_arg", "args.format"}, {"received", "array_indexed"},
                 {"supported", Json::array({"h", "hex", "b", "bin", "d", "dec"})},
                 {"reason", "xdebug does not rewrite aggregate paths or infer indexed leaves"}});
        }

        if (args.contains("format") && args.contains("value_format") &&
            args["format"].is_string() && args["value_format"].is_string() &&
            args["format"].get<std::string>() != "array_indexed") {
            xdebug_waveform::ValueRenderFormat legacy, requested;
            if (xdebug_waveform::parse_value_render_format(args["format"].get<std::string>(), legacy) &&
                xdebug_waveform::parse_value_render_format(args["value_format"].get<std::string>(), requested) &&
                legacy != requested)
                return waveform_invalid_arg_error(action_name(), "args.value_format",
                    "value_format must match legacy args.format when both are provided",
                    "the same normalized value format as args.format");
        }
        npiFsdbTime fsdb_time = 0;
        std::string time_error;
        if (!xdebug_waveform::parse_user_time(time_str.c_str(), false, fsdb_time, time_error))
            return waveform_time_error(action_name(), "args.time",
                                       time_error.empty() ? "failed to parse time: " + time_str : time_error);

        // New value_format needs bit-accurate input so decimal can preserve
        // X/Z by reporting an effective binary format.  Preserve legacy
        // format's NPI radix and its historical display shape otherwise.
        char read_format = 'h';
        if (args.contains("value_format")) {
            read_format = 'b';
        } else {
            const std::string legacy_format = args.value("format", std::string("h"));
            if (!legacy_format.empty()) {
                const char candidate = static_cast<char>(std::tolower(
                    static_cast<unsigned char>(legacy_format[0])));
                if (candidate == 'h' || candidate == 'b' || candidate == 'd') read_format = candidate;
            }
        }
        npiFsdbValType vtype = xdebug_waveform::parse_format(read_format);

        std::string formatted_time = xdebug_core::format_time(g_fsdb_file, fsdb_time);
        Json out;
        Json middle_value;
        std::string status = "ok";
        if (clock_sampled) {
            ClockPointQueryResult point;
            Json point_error;
            if (!build_clock_point_query(g_fsdb_file,
                                         clock_spec,
                                         fsdb_time,
                                         formatted_time,
                                         std::vector<PointSignalSpec>{{signal, signal}},
                                         vtype,
                                         read_format,
                                         point,
                                         point_error)) {
                return point_error;
            }
            Json middle_cell = point.rows.empty() ? Json() : point.rows[0].value("middle", Json::object());
            if (middle_cell.value("status", std::string()) == "signal_not_found")
                return waveform_signal_not_found_error(action_name(), signal);
            middle_value = middle_cell.value("value", Json());
            status = middle_cell.value("status", std::string("unknown"));
            out["clock_context"] = point.clock_context;
        } else {
            npiFsdbSigHandle signal_handle = npi_fsdb_sig_by_name(g_fsdb_file, signal.c_str(), nullptr);
            if (!signal_handle) return waveform_signal_not_found_error(action_name(), signal);
            std::string raw_value;
            if (!npi_fsdb_sig_hdl_value_at(signal_handle, fsdb_time, raw_value, vtype)) {
                return make_handler_error("VALUE_NOT_AVAILABLE",
                    "failed to read value for signal at requested time",
                    {{"signal", signal}, {"time", formatted_time}});
            }
            middle_value = xdebug_waveform::logic_value_json(
                xdebug_waveform::logic_value_from_fsdb_signal(
                    signal_handle, raw_value, read_format));
        }
        out["value"] = middle_value;
        const std::string sampling_mode = clock_sampled ? "clock_sampled" : "raw_time";
        bool known = middle_value.is_object() ? !contains_xz(middle_value.value("value", std::string())) : false;
        // xbit hints require the raw FSDB scalar. Keep the old direct middle read for hints only.
        std::string raw;
        if (npi_fsdb_sig_value_at(g_fsdb_file, signal.c_str(), fsdb_time, raw, vtype)) {
            raw = with_value_prefix(raw, read_format);
            Json hints = make_xbit_hints(args, signal, raw);
            if (!hints.is_null()) out["xbit_hints"] = hints;
        }
        out["summary"] = {{"signal", signal}, {"time", formatted_time},
                          {"sampling_mode", sampling_mode},
                          {"known", known}, {"status", status}};
        return out;
    }

private:
    std::string render_xout(const Json& r) const override {
        xdebug::TextResponseBuilder out("xdebug");
        out.emit_header(action_name());
        const Json& d = r.value("data", Json::object());
        out.emit_section("target");
        if (d.contains("signal")) out.emit_kv("signal", d["signal"]);
        if (d.contains("time")) out.emit_kv("time", d["time"]);
        if (d.contains("clock_context")) {
            out.emit_kv("clock", d["clock_context"].value("clock", std::string()));
            out.emit_kv("edge", d["clock_context"].value("edge", std::string()));
            out.emit_kv("requested_any_edge_hit", d["clock_context"].value("requested_any_edge_hit", false));
            out.emit_kv("requested_target_edge_hit", d["clock_context"].value("requested_target_edge_hit", false));
        }
        out.emit_section("summary");
        if (r.contains("summary") && r["summary"].contains("status"))
            out.emit_kv("status", r["summary"]["status"]);
        if (d.contains("sample_rows") && d["sample_rows"].is_array()) {
            std::vector<std::vector<std::string>> rows;
            for (const auto& row : d["sample_rows"]) {
                rows.push_back({row.value("signal", std::string()),
                                xdebug::json_to_xout_value(point_cell_value(row, "before")),
                                xdebug::json_to_xout_value(point_cell_value(row, "middle")),
                                xdebug::json_to_xout_value(point_cell_value(row, "after"))});
            }
            out.emit_table({"signal", "before", "middle", "after"}, rows);
        } else if (d.contains("value")) {
            out.emit_kv("value", d["value"]);
        }
        return out.str();
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_value_at_handler() {
    return std::unique_ptr<EngineActionHandler>(new ValueAtHandler);
}

}  // namespace xdebug_design
