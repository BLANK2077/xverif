#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"
#include "protocol_statistics_filter.h"
#include "waveform/server/fsdb_value_reader.h"

#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_manager.h"

#include <memory>

namespace xdebug_design {
namespace {

class AxiStatisticsHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "axi.statistics"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext&) const override {
        using namespace xdebug_waveform;
        const Json args = request.value("args", Json::object());
        const std::string name = args.value("name", std::string());
        if (name.empty()) return protocol_missing_name_error(action_name(), "axi");

        StatisticsFilter filter;
        StatisticsFilterError filter_error;
        if (!parse_statistics_filter(args, true, filter, filter_error))
            return protocol_invalid_arg_error(
                action_name(), filter_error.invalid_arg, filter_error.message,
                filter_error.expected);

        AxiConfig config;
        std::string analysis_error;
        if (!ensure_axi_analyzed(name, config, analysis_error)) {
            if (analysis_error.rfind("AXI config not found:", 0) == 0)
                return protocol_config_not_found_error(
                    action_name(), "axi", name);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return protocol_analyze_error(action_name(), "axi", name,
                                          analysis_error);
        }

        if (filter.address_mode != StatisticsAddressMode::None &&
            !g_axi_analyzer.ensure_address_index(name))
            return make_analysis_cache_error(
                g_axi_analyzer.last_cache_error());
        if (filter.has_ids && !g_axi_analyzer.ensure_id_index(name))
            return make_analysis_cache_error(
                g_axi_analyzer.last_cache_error());

        const AxiResult* result = g_axi_analyzer.get_result(name);
        if (!result)
            return protocol_analyze_error(action_name(), "axi", name,
                                          "canonical AXI result unavailable");

        size_t matched_read = 0;
        size_t matched_write = 0;
        size_t unresolved = 0;
        for (const AxiTransaction& transaction : result->all) {
            const StatisticsMatch match = match_statistics_transaction(
                filter, {transaction.is_write, transaction.addr, transaction.id});
            if (match == StatisticsMatch::Unresolved) {
                ++unresolved;
            } else if (match == StatisticsMatch::Yes) {
                if (transaction.is_write) ++matched_write;
                else ++matched_read;
            }
        }

        const AxiDiagnostics& diagnostics = result->diagnostics;
        const bool ambiguous = unresolved > 0 || !diagnostics.analysis_complete;
        Json out;
        out["summary"] = {
            {"name", name},
            {"scanned_transaction_count", result->all.size()},
            {"matched_transaction_count", matched_read + matched_write},
            {"matched_read_count", matched_read},
            {"matched_write_count", matched_write},
            {"unresolved_transaction_count", unresolved},
            {"filter_applied", filter.filter_applied},
            {"analysis_complete", diagnostics.analysis_complete},
            {"analysis_quality", ambiguous ? "ambiguous" : "complete"},
            {"full_scan_count", diagnostics.full_scan_count},
        };
        const FsdbSignalWidth awaddr =
            fsdb_signal_width(g_fsdb_file, config.awaddr);
        const FsdbSignalWidth araddr =
            fsdb_signal_width(g_fsdb_file, config.araddr);
        const FsdbSignalWidth awid =
            fsdb_signal_width(g_fsdb_file, config.awid);
        const FsdbSignalWidth arid =
            fsdb_signal_width(g_fsdb_file, config.arid);
        auto select_width = [&](const FsdbSignalWidth& write,
                                const FsdbSignalWidth& read) {
            if (filter.direction == StatisticsDirection::Write)
                return write.reliable ? write.width : 0;
            if (filter.direction == StatisticsDirection::Read)
                return read.reliable ? read.width : 0;
            return write.reliable && read.reliable &&
                   write.width == read.width ? write.width : 0;
        };
        out["filter"] = statistics_filter_json(
            filter, true, select_width(awaddr, araddr),
            select_width(awid, arid));
        if (filter.direction == StatisticsDirection::All) {
            Json width_diagnostics = Json::array();
            if (awaddr.reliable && araddr.reliable &&
                awaddr.width != araddr.width) {
                for (size_t index = 0; index < filter.address_values.size();
                     ++index) {
                    width_diagnostics.push_back({
                        {"signal", nullptr},
                        {"role", "filter.addresses[" +
                             std::to_string(index) + "]"},
                        {"reason", "conflicting_signal_widths"}});
                }
            }
            if (awid.reliable && arid.reliable &&
                awid.width != arid.width) {
                for (size_t index = 0; index < filter.ids.size(); ++index) {
                    width_diagnostics.push_back({
                        {"signal", nullptr},
                        {"role", "filter.ids[" + std::to_string(index) + "]"},
                        {"reason", "conflicting_signal_widths"}});
                }
            }
            if (!width_diagnostics.empty())
                out["summary"]["width_diagnostics"] = width_diagnostics;
        }
        out["notes"] = {{"unresolved_transaction_count",
                         statistics_unresolved_note()}};
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return render_statistics_xout(action_name(), response);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_statistics_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiStatisticsHandler);
}

}  // namespace xdebug_design
