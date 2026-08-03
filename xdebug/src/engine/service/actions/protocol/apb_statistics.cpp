#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"
#include "protocol_statistics_filter.h"
#include "waveform/server/fsdb_value_reader.h"
#include "core/output/completeness.h"

#include "waveform/apb/apb_analyzer.h"
#include "waveform/apb/apb_manager.h"

#include <memory>

namespace xdebug_design {
namespace {

class ApbStatisticsHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.statistics"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext&) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        const std::string name = args.value("name", std::string());
        if (name.empty()) return protocol_missing_name_error(action_name(), "apb");

        StatisticsFilter filter;
        StatisticsFilterError filter_error;
        Json filter_args = Json::object();
        if (args["filter"].exists()) {
            filter_args["filter"] = args["filter"].consume_subtree(
                "apb_statistics_filter_parser");
        }
        if (!parse_statistics_filter(
                filter_args, false, filter, filter_error))
            return protocol_invalid_arg_error(
                action_name(), filter_error.invalid_arg, filter_error.message,
                filter_error.expected);

        ApbConfig config;
        ProtocolEnsureResult ensured = ensure_apb_analyzed(name, config);
        if (!ensured.ok()) {
            if (ensured.status == ProtocolEnsureStatus::ConfigNotFound)
                return protocol_config_not_found_error(
                    action_name(), "apb", name);
            if (ensured.status == ProtocolEnsureStatus::StoreError)
                return make_config_store_error(ensured.store);
            if (!g_apb_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_apb_analyzer.last_cache_error());
            return protocol_analyze_error(action_name(), "apb", name,
                                          ensured.message);
        }
        if (filter.address_mode != StatisticsAddressMode::None &&
            !g_apb_analyzer.ensure_address_index(name))
            return make_analysis_cache_error(
                g_apb_analyzer.last_cache_error());

        const ApbResult* result = g_apb_analyzer.get_result(name);
        if (!result)
            return protocol_analyze_error(action_name(), "apb", name,
                                          "canonical APB result unavailable");

        size_t matched_read = 0;
        size_t matched_write = 0;
        size_t unresolved = 0;
        for (const ApbTransaction* transaction : result->all) {
            if (!transaction) continue;
            const StatisticsMatch match = match_statistics_transaction(
                filter, {transaction->is_write, transaction->addr, std::string()});
            if (match == StatisticsMatch::Unresolved) {
                ++unresolved;
            } else if (match == StatisticsMatch::Yes) {
                if (transaction->is_write) ++matched_write;
                else ++matched_read;
            }
        }

        const ApbDiagnostics& diagnostics = result->diagnostics;
        const bool ambiguous = unresolved > 0 || !diagnostics.analysis_complete;
        const size_t matched_count = matched_read + matched_write;
        Json out;
        out["summary"] = {
            {"name", name},
            {"scanned_transaction_count", result->all.size()},
            {"matched_transaction_count", matched_count},
            {"matched_read_count", matched_read},
            {"matched_write_count", matched_write},
            {"unresolved_transaction_count", unresolved},
            {"filter_applied", filter.filter_applied},
            {"analysis_quality", ambiguous ? "ambiguous" : "complete"},
            {"full_scan_count", diagnostics.full_scan_count},
        };
        xdebug_core::set_completeness(
            out["summary"],
            diagnostics.analysis_complete,
            diagnostics.analysis_complete,
            false,
            matched_count,
            matched_count,
            diagnostics.analysis_complete
                ? std::vector<std::string>{}
                : std::vector<std::string>{"analysis_transactions"});
        const FsdbSignalWidth address_width =
            fsdb_signal_width(g_fsdb_file, config.paddr);
        out["filter"] = statistics_filter_json(
            filter, false,
            address_width.reliable ? address_width.width : 0);
        out["notes"] = {{"unresolved_transaction_count",
                         statistics_unresolved_note()}};
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return render_tabular_xout(action_name(), response);
    }

};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_statistics_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbStatisticsHandler);
}

}  // namespace xdebug_design
