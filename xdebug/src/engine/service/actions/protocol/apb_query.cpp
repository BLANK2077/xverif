#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"
#include "protocol_query_filter.h"

#include "core/npi/time_contract.h"
#include "core/output/completeness.h"
#include "core/value/logic_value.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/apb/apb_manager.h"

#include <algorithm>
#include <memory>
#include <vector>

namespace xdebug_design {
namespace {

Json apb_transaction_json(const xdebug_waveform::ApbTransaction& txn) {
    Json out;
    out["time"] = xdebug_core::format_time(
        xdebug_waveform::g_fsdb_file, txn.time);
    out["addr"] = xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(
            txn.addr, 'h', txn.addr_width));
    out["data"] = xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(
            txn.data, 'h', txn.data_width));
    out["is_write"] = txn.is_write;
    out["has_error"] = txn.has_error;
    return out;
}

void set_query_summary(
    Json& summary,
    const xdebug_waveform::ApbDiagnostics& diagnostics,
    size_t total_count,
    size_t returned_count,
    bool response_truncated) {
    std::vector<std::string> scopes;
    if (!diagnostics.analysis_complete)
        scopes.push_back("analysis_transactions");
    if (response_truncated)
        scopes.push_back("response_transactions");
    xdebug_core::set_completeness(
        summary,
        diagnostics.analysis_complete,
        diagnostics.analysis_complete,
        response_truncated,
        total_count,
        returned_count,
        scopes);
}

class ApbQueryHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.query"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext&) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        const std::string name = args.value("name", std::string());
        if (name.empty())
            return protocol_missing_name_error(action_name(), "apb");

        const std::string direction =
            args.value("direction", std::string("all"));
        Json address;
        if (args["address"].exists()) {
            address = args["address"].consume_subtree(
                "apb_query_address_filter");
        }
        ProtocolQueryFilter filter;
        ProtocolQueryFilterError filter_error;
        if (!parse_protocol_query_filter(
                address, Json(), false, filter, filter_error)) {
            return protocol_invalid_arg_error(
                action_name(), filter_error.invalid_arg,
                filter_error.message, filter_error.expected);
        }

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
            return protocol_analyze_error(
                action_name(), "apb", name, ensured.message);
        }

        const ApbResult* result = g_apb_analyzer.get_result(name);
        if (!result)
            return protocol_analyze_error(
                action_name(), "apb", name,
                "canonical APB result unavailable");

        auto query = args["query"];
        const int index = query.value("index", -1);
        const int line_limit = query.value("line_limit", -1);
        const bool last = args.value("last", false);
        const size_t begin = index > 0
            ? static_cast<size_t>(index - 1) : 0;
        const size_t keep_limit = line_limit > 0
            ? static_cast<size_t>(line_limit) : 0;
        size_t matched_count = 0;
        const ApbTransaction* selected = nullptr;
        std::vector<const ApbTransaction*> page;
        if (keep_limit > 0) page.reserve(keep_limit);
        for (const ApbTransaction* transaction : result->all) {
            if (!transaction ||
                !protocol_direction_matches(transaction->is_write, direction)) {
                continue;
            }
            if (match_protocol_query_filter(
                filter, transaction->addr,
                    transaction->addr_width) ==
                ValueFilterMatch::Yes) {
                const size_t match_index = matched_count++;
                if (last) {
                    selected = transaction;
                } else if (index > 0 && line_limit < 0) {
                    if (match_index == begin) selected = transaction;
                } else if (keep_limit > 0 && match_index >= begin &&
                           page.size() < keep_limit) {
                    page.push_back(transaction);
                }
            }
        }
        Json out;
        out["summary"] = {
            {"name", name},
            {"direction", direction},
        };
        out["filter"] = {{"direction", direction}};
        if (filter.has_address)
            out["filter"]["address"] = filter.address_json;

        if (last) {
            const bool found = selected != nullptr;
            out["summary"]["query_mode"] = "last";
            out["summary"]["found"] = found;
            if (found)
                out["transaction"] =
                    apb_transaction_json(*selected);
            set_query_summary(
                out["summary"], result->diagnostics,
                matched_count, found ? 1 : 0, false);
            return out;
        }

        if (index > 0 && line_limit < 0) {
            const bool found = selected != nullptr;
            out["summary"]["query_mode"] = "index";
            out["summary"]["found"] = found;
            if (found)
                out["transaction"] =
                    apb_transaction_json(*selected);
            set_query_summary(
                out["summary"], result->diagnostics,
                matched_count, found ? 1 : 0, false);
            return out;
        }

        if (line_limit > 0) {
            Json transactions = Json::array();
            for (const ApbTransaction* transaction : page) {
                transactions.push_back(
                    apb_transaction_json(*transaction));
            }
            const bool truncated =
                begin + transactions.size() < matched_count;
            out["summary"]["query_mode"] = "list";
            out["transactions"] = std::move(transactions);
            set_query_summary(
                out["summary"], result->diagnostics,
                matched_count, out["transactions"].size(), truncated);
            return out;
        }

        out["summary"]["query_mode"] = "count";
        set_query_summary(
            out["summary"], result->diagnostics,
            matched_count, 0, false);
        return out;
    }

    std::string render_xout(const Json& response) const override {
        return render_tabular_xout(action_name(), response);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_query_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbQueryHandler);
}

}  // namespace xdebug_design
