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
#include "core/value/logic_value.h"
#include "core/output/completeness.h"
#include "core/npi/time_contract.h"

#include <fstream>
#include <memory>
#include <ctime>
#include <sstream>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>

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
    auto exact_count = [](double value) -> std::int64_t {
        double integral = 0.0;
        if (!std::isfinite(value) || value < 0.0 ||
            std::modf(value, &integral) != 0.0 ||
            integral >= std::ldexp(
                1.0, std::numeric_limits<std::int64_t>::digits)) {
            throw std::logic_error(
                "AXI outstanding extrema must be exact non-negative integers");
        }
        return static_cast<std::int64_t>(integral);
    };
    return Json{{"samples", stat.samples},
                {"min", exact_count(stat.min)},
                {"max", exact_count(stat.max)},
                {"avg", stat.avg}};
}

static Json pending_txn_json(const xdebug_waveform::AxiTransaction& txn,
                             npiFsdbTime scan_end) {
    using namespace xdebug_waveform;
    Json out = {{"direction", txn.is_write ? "write" : "read"},
                {"id", xdebug_core::render_logic_value(
                    xdebug_core::logic_value_from_fsdb_raw(
                        txn.id, 'h', txn.id_width))},
                {"addr", xdebug_core::render_logic_value(
                    xdebug_core::logic_value_from_fsdb_raw(
                        txn.addr, 'h', txn.addr_width))},
                {"len", xdebug_core::render_logic_value(
                    xdebug_core::logic_value_from_fsdb_raw(
                        txn.len, 'h', txn.len_width))},
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
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        std::string name = args.value("name", "");
        if (name.empty()) return protocol_missing_name_error(action_name(), "axi");

        AxiConfig cfg;
        ProtocolEnsureResult ensured = ensure_axi_analyzed(name, cfg);
        if (!ensured.ok()) {
            if (ensured.status == ProtocolEnsureStatus::ConfigNotFound)
                return protocol_config_not_found_error(action_name(), "axi", name);
            if (ensured.status == ProtocolEnsureStatus::StoreError)
                return make_config_store_error(ensured.store);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return protocol_analyze_error(
                action_name(), "axi", name, ensured.message);
        }

        std::string analysis = args.value("analysis", "latency");
        if (analysis != "pending" && args.contains("line_limit"))
            return protocol_invalid_arg_error(
                action_name(), "args.line_limit",
                "line_limit is only valid for analysis=pending",
                "omit line_limit or set analysis to pending");
        std::string dir = args.value("direction", "all");
        int filter = (dir == "write") ? 1 : (dir == "read") ? 2 : 0;
        const AxiResult* canonical = g_axi_analyzer.get_result(name);
        if (!canonical)
            return protocol_analyze_error(action_name(), "axi", name,
                                          "canonical AXI result unavailable");
        const AxiDiagnostics& diag = canonical->diagnostics;
        Json out;
        out["summary"] = {{"name", name}, {"analysis", analysis}, {"direction", dir},
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
        std::size_t total_count = 0;
        std::size_t returned_count = 0;
        bool response_truncated = false;

        if (analysis == "latency") {
            AxiStatResult selected, read, write;
            g_axi_analyzer.get_latency_stats(name, filter, nullptr, selected);
            g_axi_analyzer.get_latency_stats(name, 2, nullptr, read);
            g_axi_analyzer.get_latency_stats(name, 1, nullptr, write);
            Json selected_json = latency_stat_json(selected);
            total_count = selected.samples;
            returned_count = selected.samples;
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
            const Json selected_json = outstanding_stat_json(selected);
            const Json read_json = outstanding_stat_json(read);
            const Json write_json = outstanding_stat_json(write);
            out["summary"]["max"] = selected_json["max"];
            out["summary"]["min"] = selected_json["min"];
            out["summary"]["avg"] = selected_json["avg"];
            out["summary"]["samples"] = selected_json["samples"];
            total_count = selected.samples;
            returned_count = selected.samples;
            out["osd"] = {{"read", read_json},
                          {"write", write_json},
                          {"final_read", diag.final_read_outstanding},
                          {"final_write", diag.final_write_outstanding},
                          {"definitions", {{"read", "increment on AR handshake, decrement on RLAST handshake"},
                                           {"write", "increment on AW handshake, decrement on B handshake"}}}};
        } else if (analysis == "pending") {
            int line_limit = args.value("line_limit", 20);
            Json transactions = Json::array();
            size_t matching_count = 0;
            auto append_pending = [&](const std::vector<AxiTransaction>& pending, int kind) {
                for (const auto& txn : pending) {
                    if (filter != 0 && filter != kind) continue;
                    ++matching_count;
                    if (line_limit < 0 ||
                        static_cast<int>(transactions.size()) < line_limit)
                        transactions.push_back(pending_txn_json(txn, diag.scan_end));
                }
            };
            append_pending(canonical->pending_writes, 1);
            append_pending(canonical->pending_reads, 2);
            total_count = matching_count;
            returned_count = transactions.size();
            response_truncated = returned_count < total_count;
            out["pending_transactions"] = transactions;
        } else {
            return protocol_invalid_enum_error(
                action_name(), "args.analysis", "analysis must be latency, osd, or pending",
                Json::array({"latency", "osd", "pending"}));
        }
        std::vector<std::string> truncation_scopes;
        if (!diag.analysis_complete)
            truncation_scopes.push_back("analysis_transactions");
        if (response_truncated)
            truncation_scopes.push_back("response_transactions");
        xdebug_core::set_completeness(
            out["summary"],
            diag.analysis_complete,
            diag.analysis_complete,
            response_truncated,
            total_count,
            returned_count,
            truncation_scopes);
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_analysis_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiAnalysisHandler);
}

}  // namespace xdebug_design
