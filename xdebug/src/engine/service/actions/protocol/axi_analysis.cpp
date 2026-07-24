#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"

#include "waveform/apb/apb_manager.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_exporter.h"
#include "waveform/axi/axi_transaction_json.h"
#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/value/logic_value.h"
#include "core/npi/time_contract.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>

namespace xdebug_design {
namespace {

static Json latency_stat_json(const xdebug_waveform::AxiStatResult& stat) {
    using namespace xdebug_waveform;
    Json out = {{"samples", stat.samples}};
    if (stat.samples == 0) {
        out["status"] = "empty";
        out["min"] = nullptr;
        out["max"] = nullptr;
        out["avg"] = nullptr;
        out["p50"] = nullptr;
        out["p95"] = nullptr;
        out["p99"] = nullptr;
        return out;
    }
    out["min"] = xdebug_core::format_duration(g_fsdb_file, static_cast<npiFsdbTime>(stat.min));
    out["max"] = xdebug_core::format_duration(g_fsdb_file, static_cast<npiFsdbTime>(stat.max));
    out["avg"] = xdebug_core::format_duration(g_fsdb_file, static_cast<npiFsdbTime>(stat.avg));
    out["p50"] = xdebug_core::format_duration(g_fsdb_file, static_cast<npiFsdbTime>(stat.p50));
    out["p95"] = xdebug_core::format_duration(g_fsdb_file, static_cast<npiFsdbTime>(stat.p95));
    out["p99"] = xdebug_core::format_duration(g_fsdb_file, static_cast<npiFsdbTime>(stat.p99));
    return out;
}

static Json outstanding_stat_json(const xdebug_waveform::AxiStatResult& stat) {
    if (stat.samples == 0)
        return Json{{"samples", 0}, {"status", "empty"}, {"min", 0}, {"max", 0}, {"avg", 0.0}};
    return Json{{"samples", stat.samples}, {"min", stat.min}, {"max", stat.max}, {"avg", stat.avg}};
}

static Json pending_txn_json(const xdebug_waveform::AxiTransaction& txn,
                             npiFsdbTime scan_end) {
    using namespace xdebug_waveform;
    Json out = {{"direction", txn.is_write ? "write" : "read"},
                {"id", render_logic_value(
                    logic_value_from_fsdb_raw(txn.id, 'h', txn.id_width))},
                {"addr", render_logic_value(
                    logic_value_from_fsdb_raw(txn.addr, 'h', txn.addr_width))},
                {"len", render_logic_value(
                    logic_value_from_fsdb_raw(txn.len, 'h', txn.len_width))},
                {"request_time", xdebug_core::format_time(g_fsdb_file, txn.addr_time)},
                {"age", xdebug_core::format_duration(
                    g_fsdb_file, scan_end >= txn.addr_time ? scan_end - txn.addr_time : 0)},
                {"observed_beat_count", txn.data.size()},
                {"expected_beat_count", txn.expected_beat_count},
                {"data_complete", txn.data_complete}};
    if (txn.is_write) out["phase_order"] = txn.phase_order;
    return out;
}

class AxiAnalysisHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "axi.analysis"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(const Json& r, EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        Json a = r.value("args", Json::object());
        std::string name = a.value("name", "");
        if (name.empty()) return protocol_missing_name_error(action_name(), "axi");

        AxiConfig cfg; std::string err;
        if (!ensure_axi_analyzed(name, cfg, err)) {
            if (err.rfind("AXI config not found:", 0) == 0)
                return protocol_config_not_found_error(action_name(), "axi", name);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return protocol_analyze_error(action_name(), "axi", name, err);
        }

        std::string analysis = a.value("analysis", "latency");
        if (analysis != "pending" && a.contains("line_limit"))
            return protocol_invalid_arg_error(
                action_name(), "args.line_limit",
                "line_limit is only valid for analysis=pending",
                "omit line_limit or set analysis to pending");
        std::string dir = a.value("direction", "all");
        int filter = (dir == "write") ? 1 : (dir == "read") ? 2 : 0;
        const AxiResult* canonical = g_axi_analyzer.get_result(name);
        if (!canonical)
            return protocol_analyze_error(action_name(), "axi", name,
                                          "canonical AXI result unavailable");
        const AxiDiagnostics& diag = canonical->diagnostics;
        Json out;
        out["summary"] = {{"name", name}, {"analysis", analysis}, {"direction", dir},
            {"analysis_complete", diag.analysis_complete},
            {"sample_count", diag.sample_count},
            {"full_scan_count", diag.full_scan_count},
            {"scanned_range", {{"begin", xdebug_core::format_time(g_fsdb_file, diag.scan_begin)},
                                {"end", xdebug_core::format_time(g_fsdb_file, diag.scan_end)}}},
            {"completed_read_count", canonical->reads.size()},
            {"completed_write_count", canonical->writes.size()},
            {"incomplete_read_count", diag.incomplete_read_count},
            {"incomplete_write_count", diag.incomplete_write_count},
            {"buffered_w_beat_count", diag.buffered_w_beat_count},
            {"buffered_w_burst_count", diag.buffered_w_burst_count},
            {"orphan_w_beat_count", diag.orphan_w_beat_count},
            {"orphan_b_count", diag.orphan_b_count},
            {"orphan_r_beat_count", diag.orphan_r_beat_count},
            {"response_dependency_violation_count", diag.response_dependency_violation_count},
            {"channel_handshakes", {{"aw", diag.handshakes.aw}, {"w", diag.handshakes.w},
                                     {"b", diag.handshakes.b}, {"ar", diag.handshakes.ar},
                                     {"r", diag.handshakes.r}}}};

        if (analysis == "latency") {
            AxiStatResult selected, read, write;
            g_axi_analyzer.get_latency_stats(name, filter, nullptr, selected);
            g_axi_analyzer.get_latency_stats(name, 2, nullptr, read);
            g_axi_analyzer.get_latency_stats(name, 1, nullptr, write);
            Json selected_json = latency_stat_json(selected);
            for (Json::const_iterator it = selected_json.begin(); it != selected_json.end(); ++it)
                out["summary"][it.key()] = it.value();
            out["latency"] = {
                {"read", latency_stat_json(read)},
                {"write", latency_stat_json(write)},
                {"definitions", {{"read", "AR handshake to RLAST handshake"},
                                  {"write", "AW handshake to B handshake"}}}
            };
            Json phase_counts = {{"aw_before_w", 0}, {"same_cycle", 0}, {"w_before_aw", 0},
                                 {"unknown", 0}};
            for (const auto& txn : canonical->writes) {
                const std::string key = phase_counts.contains(txn.phase_order)
                    ? txn.phase_order : "unknown";
                phase_counts[key] = phase_counts[key].get<int>() + 1;
            }
            out["latency"]["write_phase_order_counts"] = phase_counts;
            if (selected.max_txn) {
                out["slowest"] = axi_transaction_to_json(
                    g_fsdb_file, *selected.max_txn, false);
            }
        } else if (analysis == "osd") {
            AxiStatResult selected, read, write;
            g_axi_analyzer.get_outstanding_stats(name, filter, nullptr, selected);
            g_axi_analyzer.get_outstanding_stats(name, 2, nullptr, read);
            g_axi_analyzer.get_outstanding_stats(name, 1, nullptr, write);
            out["summary"]["max"] = selected.max;
            out["summary"]["min"] = selected.min;
            out["summary"]["avg"] = selected.avg;
            out["summary"]["samples"] = selected.samples;
            out["osd"] = {{"read", outstanding_stat_json(read)},
                          {"write", outstanding_stat_json(write)},
                          {"final_read", diag.final_read_outstanding},
                          {"final_write", diag.final_write_outstanding},
                          {"definitions", {{"read", "increment on AR handshake, decrement on RLAST handshake"},
                                           {"write", "increment on AW handshake, decrement on B handshake"}}}};
        } else if (analysis == "pending") {
            int line_limit = a.value("line_limit", 20);
            Json transactions = Json::array();
            size_t matching_count = 0;
            auto append_pending = [&](const std::vector<AxiTransaction>& pending, int kind) {
                for (const auto& txn : pending) {
                    if (filter != 0 && filter != kind) continue;
                    ++matching_count;
                    if (static_cast<int>(transactions.size()) < line_limit)
                        transactions.push_back(pending_txn_json(txn, diag.scan_end));
                }
            };
            append_pending(canonical->pending_writes, 1);
            append_pending(canonical->pending_reads, 2);
            out["summary"]["pending_count"] = matching_count;
            out["summary"]["returned_pending_count"] = transactions.size();
            out["summary"]["truncated"] = transactions.size() < matching_count;
            out["summary"]["truncation_scope"] = transactions.size() < matching_count
                ? Json("response_transactions") : Json(nullptr);
            out["pending_transactions"] = transactions;
        } else {
            return protocol_invalid_enum_error(
                action_name(), "args.analysis", "analysis must be latency, osd, or pending",
                Json::array({"latency", "osd", "pending"}));
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_analysis_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiAnalysisHandler);
}

}  // namespace xdebug_design
