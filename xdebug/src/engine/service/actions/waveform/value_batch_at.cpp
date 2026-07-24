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
#include <cctype>
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
class ValueBatchAtHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "value.batch_at"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext& ctx) const override {
        Json args = request.value("args", Json::object());
        Json signals_j = args.value("signals", Json::array());
        std::string time_str = args.value("time", args.value("at", std::string()));
        if (!signals_j.is_array() || signals_j.empty() || time_str.empty())
            return waveform_missing_field_error(
                action_name(),
                (!signals_j.is_array() || signals_j.empty()) ? "args.signals" : "args.time",
                "args.signals[] and args.time are required");

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

        npiFsdbTime fsdb_time = 0;
        std::string time_error;
        if (!xdebug_waveform::parse_user_time(time_str.c_str(), false, fsdb_time, time_error))
            return waveform_time_error(action_name(), "args.time",
                                       time_error.empty() ? "failed to parse time: " + time_str : time_error);

        std::vector<std::string> names;
        for (const auto& s : signals_j)
            if (s.is_string()) names.push_back(s.get<std::string>());

        const char read_format = 'b';
        Json out;
        std::string formatted_time = xdebug_core::format_time(g_fsdb_file, fsdb_time);
        std::vector<PointSignalSpec> specs;
        for (const auto& name : names) specs.push_back({name, name});
        ClockPointQueryResult point;
        if (clock_sampled) {
            Json point_error;
            if (!build_clock_point_query(g_fsdb_file,
                                         clock_spec,
                                         fsdb_time,
                                         formatted_time,
                                         specs,
                                         xdebug_waveform::parse_format(read_format),
                                         read_format,
                                         point,
                                         point_error)) {
                return point_error;
            }
        } else {
            point.rows = Json::array();
            for (const auto& name : names) {
                Json row = {{"signal", name}, {"path", name}};
                npiFsdbSigHandle signal_handle = npi_fsdb_sig_by_name(g_fsdb_file, name.c_str(), nullptr);
                std::string raw_value;
                if (!signal_handle) {
                    row["middle"] = {{"status", "signal_not_found"}, {"value", nullptr}};
                } else if (!npi_fsdb_sig_hdl_value_at(signal_handle, fsdb_time, raw_value,
                                                       xdebug_waveform::parse_format(read_format))) {
                    row["middle"] = {{"status", "not_dumped_or_unreadable"}, {"value", nullptr}};
                } else {
                    row["middle"] = {
                        {"status", "ok"},
                        {"value", xdebug_waveform::logic_value_json(
                            xdebug_waveform::logic_value_from_fsdb_signal(
                                signal_handle, raw_value, read_format))}
                    };
                }
                point.rows.push_back(row);
            }
        }
        Json batch = Json::array();
        Json missing_by_reason = Json::object();
        int missing_count = 0;
        int unknown_count = 0;
        for (size_t i = 0; i < names.size() && i < point.rows.size(); ++i) {
            Json item;
            item["signal"] = names[i];
            Json middle = point.rows[i].value("middle", Json::object());
            if (middle.value("status", std::string()) == "ok") {
                item["status"] = "ok";
                item["value"] = middle.value("value", Json());
                if (item["value"].is_object() && contains_xz(item["value"].value("value", std::string()))) unknown_count++;
                std::string raw;
                if (npi_fsdb_sig_value_at(g_fsdb_file, names[i].c_str(), fsdb_time, raw, xdebug_waveform::parse_format(read_format))) {
                    raw = with_value_prefix(raw, read_format);
                    Json hints = make_xbit_hints(args, names[i], raw);
                    if (!hints.is_null()) item["xbit_hints"] = hints;
                }
            } else {
                item["status"] = middle.value("status", std::string("signal_not_found"));
                item["value"] = nullptr;
                item["reason"] = "Signal path was not found in the FSDB: " + names[i];
                missing_count++;
                missing_by_reason[item["status"].get<std::string>()] =
                    missing_by_reason.value(item["status"].get<std::string>(), 0) + 1;
            }
            batch.push_back(item);
        }
        out["values"] = batch;
        if (clock_sampled) out["clock_context"] = point.clock_context;
        const std::string sampling_mode = clock_sampled ? "clock_sampled" : "raw_time";
        out["summary"] = {{"time", formatted_time}, {"signal_count", batch.size()},
                          {"sampling_mode", sampling_mode},
                          {"unknown_count", unknown_count},
                          {"missing_count", missing_count},
                          {"missing_by_reason", missing_by_reason}};
        return out;
    }

private:
    std::string render_xout(const Json& r) const override {
        xdebug::TextResponseBuilder out("xdebug");
        out.emit_header(action_name());
        const Json& d = r.value("data", Json::object());
        const Json& s = r.value("summary", Json::object());
        out.emit_section("target");
        if (s.contains("time")) out.emit_kv("time", s["time"]);
        if (s.contains("signal_count")) out.emit_kv("signal_count", s["signal_count"]);
        out.emit_section("values");
        if (d.contains("sample_rows") && d["sample_rows"].is_array()) {
            std::vector<std::vector<std::string>> rows;
            for (const auto& row : d["sample_rows"]) {
                rows.push_back({row.value("signal", std::string()),
                                xdebug::json_to_xout_value(point_cell_value(row, "before")),
                                xdebug::json_to_xout_value(point_cell_value(row, "middle")),
                                xdebug::json_to_xout_value(point_cell_value(row, "after"))});
            }
            out.emit_table({"signal", "before", "middle", "after"}, rows);
        } else if (d.contains("values") && d["values"].is_array()) {
            std::vector<std::vector<std::string>> rows;
            for (const auto& item : d["values"]) {
                if (!item.is_object()) continue;
                rows.push_back({item.value("signal", std::string()),
                                xdebug::json_to_xout_value(item.value("value", Json())),
                                item.value("status", std::string())});
            }
            out.emit_table({"signal", "value", "status"}, rows);
        } else if (d.contains("values") && d["values"].is_object()) {
            std::vector<std::vector<std::string>> rows;
            for (auto it = d["values"].begin(); it != d["values"].end(); ++it)
                rows.push_back({it.key(), xdebug::json_to_xout_value(it.value())});
            out.emit_table({"signal", "value"}, rows);
        }
        if (d.contains("values") && d["values"].is_array()) {
            std::vector<std::vector<std::string>> hint_rows;
            for (const auto& item : d["values"]) {
                if (!item.is_object() || !item.contains("xbit_hints")) continue;
                const Json& hints = item["xbit_hints"];
                std::string commands;
                if (hints.contains("commands") && hints["commands"].is_array()) {
                    for (const auto& command : hints["commands"]) {
                        if (!command.is_string()) continue;
                        if (!commands.empty()) commands += "; ";
                        commands += command.get<std::string>();
                    }
                }
                hint_rows.push_back({item.value("signal", std::string()),
                                     hints.value("status", std::string()),
                                     commands});
            }
            if (!hint_rows.empty()) {
                out.emit_section("xbit_hints");
                out.emit_table({"signal", "status", "commands"}, hint_rows);
            }
        }
        return out.str();
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_value_batch_at_handler() {
    return std::unique_ptr<EngineActionHandler>(new ValueBatchAtHandler);
}

}  // namespace xdebug_design
