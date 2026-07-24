#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"

#include "waveform/apb/apb_manager.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_exporter.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/server/fsdb_value_reader.h"
#include "waveform/value/logic_value.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>
#include <algorithm>

namespace xdebug_design {
namespace {
class AxiExportHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "axi.export"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(const Json& r, EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        Json a = r.value("args", Json::object());
        std::string name = a.value("name", "");
        if (name.empty()) return protocol_missing_name_error(action_name(), "axi");

        AxiManager am;
        AxiConfig cfg;
        if (!am.get_axi(g_session_id, name, cfg))
            return protocol_config_not_found_error(action_name(), "axi", name);

        Json tr = a.value("time_range", Json::object());
        std::string begin_s;
        std::string end_s;
        if (tr.is_object()) {
            begin_s = tr.value("begin", std::string());
            end_s = tr.value("end", std::string());
        }
        if (begin_s.empty() || end_s.empty())
            return make_handler_error(
                "MISSING_FIELD",
                "axi.export requires args.time_range.begin/end",
                {{"invalid_arg", "args.time_range"},
                 {"expected", "args.time_range.begin and args.time_range.end"},
                 {"correct_example", protocol_action_example(action_name())}});

        npiFsdbTime begin = 0, end = 0;
        std::string time_err;
        if (!parse_user_time(begin_s.c_str(), false, begin, time_err))
            return protocol_time_error(action_name(), "args.time_range.begin", time_err);
        if (!parse_user_time(end_s.c_str(), true, end, time_err))
            return protocol_time_error(action_name(), "args.time_range.end", time_err);
        if (end < begin)
            return protocol_time_error(action_name(), "args.time_range",
                                       "axi.export end time is before begin time");

        Json output = a.value("output", Json::object());
        std::string format = output.value("file_format", std::string("tsv"));
        if (format != "tsv" && format != "csv")
            return protocol_invalid_enum_error(
                action_name(), "args.output.file_format",
                "output.file_format must be tsv or csv",
                Json::array({"tsv", "csv"}));

        std::string output_prefix = output.value("path", std::string());
        if (output_prefix.empty()) {
            std::ostringstream oss;
            oss << xdebug_waveform_axi_exports_dir(g_session_id)
                << "/" << name << "_" << begin << "_" << end << "_" << std::time(nullptr);
            output_prefix = oss.str();
        }

        AxiExporter exporter;
        AxiExportResult result;
        result.format = format;
        std::string error;
        if (!analyze_axi_config(name, cfg, error)) {
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return make_handler_error("ACTION_FAILED", error,
                                      {{"cause_code", "ANALYZE_FAILED"},
                                       {"correct_example", protocol_action_example(action_name())}});
        }
        const AxiResult* canonical = g_axi_analyzer.get_result(name);
        if (!canonical)
            return make_handler_error("ACTION_FAILED", "AXI canonical result unavailable: " + name,
                                      {{"cause_code", "ANALYZE_FAILED"},
                                       {"correct_example", protocol_action_example(action_name())}});
        exporter.build(*canonical, cfg, begin, end, result);
        result.format = format;

        auto txn_json = [&](const AxiExportTransaction& txn) {
            auto render = [&](const std::string& raw,
                              const std::string& signal) {
                const FsdbSignalWidth width =
                    fsdb_signal_width(g_fsdb_file, signal);
                return render_logic_value(logic_value_from_fsdb_raw(
                    raw, 'h', width.reliable ? width.width : 0));
            };
            const bool write = txn.is_write;
            npiFsdbTime latency = txn.completion_time >= txn.addr_time ? txn.completion_time - txn.addr_time : 0;
            return Json{{"seq", txn.seq},
                        {"direction", txn.is_write ? "write" : "read"},
                        {"completion_time", format_time(txn.completion_time)},
                        {"addr_time", format_time(txn.addr_time)},
                        {"first_data_time", format_time(txn.first_data_time)},
                        {"last_data_time", format_time(txn.last_data_time)},
                        {"latency", format_duration(latency)},
                        {"phase_order", txn.phase_order},
                        {"response_dependency_violation", txn.response_dependency_violation},
                        {"id", render(txn.id, write ? cfg.awid : cfg.arid)},
                        {"addr", render(txn.addr, write ? cfg.awaddr : cfg.araddr)},
                        {"len", render(txn.len, write ? cfg.awlen : cfg.arlen)},
                        {"size", render(txn.size, write ? cfg.awsize : cfg.arsize)},
                        {"burst", render(txn.burst, write ? cfg.awburst : cfg.arburst)},
                        {"resp", render(txn.resp, write ? cfg.bresp : cfg.rresp)},
                        {"beat_count", txn.beat_count},
                        {"expected_beat_count", txn.expected_beat_count}};
        };

        Json summary = {{"name", name},
                        {"write_count", result.writes.size()},
                        {"read_count", result.reads.size()},
                        {"total_count", result.writes.size() + result.reads.size()},
                        {"row_count", result.writes.size() + result.reads.size()},
                        {"format", format},
                        {"status", output_prefix.empty() ? "preview" : "written"},
                        {"output_written", !output_prefix.empty()},
                        {"truncated", false},
                        {"analysis_complete", result.analysis_complete},
                        {"sample_count", result.sample_count},
                        {"full_scan_count", result.full_scan_count},
                        {"incomplete_write_count", result.incomplete_write_count},
                        {"incomplete_read_count", result.incomplete_read_count},
                        {"buffered_w_beat_count", result.buffered_w_beat_count},
                        {"buffered_w_burst_count", result.buffered_w_burst_count},
                        {"orphan_w_beat_count", result.orphan_w_beat_count},
                        {"orphan_b_count", result.orphan_b_count},
                        {"orphan_r_beat_count", result.orphan_r_beat_count},
                        {"response_dependency_violation_count", result.response_dependency_violation_count},
                        {"requested_range", {{"begin", format_time(begin)}, {"end", format_time(end)}}},
                        {"scanned_range", {{"begin", format_time(result.scan_begin)},
                                            {"end", format_time(result.scan_end)}}}};

        if (output_prefix.empty()) {
            Json preview;
            preview["writes"] = Json::array();
            preview["reads"] = Json::array();
            size_t wlimit = std::min<size_t>(result.writes.size(), 8);
            size_t rlimit = std::min<size_t>(result.reads.size(), 8);
            for (size_t i = 0; i < wlimit; ++i) preview["writes"].push_back(txn_json(result.writes[i]));
            for (size_t i = 0; i < rlimit; ++i) preview["reads"].push_back(txn_json(result.reads[i]));
            Json out;
            out["summary"] = summary;
            out["preview"] = preview;
            return out;
        }

        std::string write_file, read_file, meta_file;
        if (!exporter.write_files(output_prefix, result, write_file, read_file, meta_file, error))
            return make_handler_error("ACTION_FAILED", error,
                                      {{"cause_code", "EXPORT_FAILED"},
                                       {"invalid_arg", "args.output.path"},
                                       {"expected", "writable output path prefix"},
                                       {"correct_example", protocol_action_example(action_name())}});

        Json out;
        summary["output"] = {{"path", output_prefix},
                             {"write_path", write_file},
                             {"read_path", read_file},
                             {"meta_path", meta_file},
                             {"file_format", format}};
        out["summary"] = summary;
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_export_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiExportHandler);
}

}  // namespace xdebug_design
