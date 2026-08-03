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

bool direction_matches(
    const xdebug_waveform::ApbTransaction& transaction,
    const std::string& direction) {
    return direction == "all" ||
        (direction == "write" && transaction.is_write) ||
        (direction == "read" && !transaction.is_write);
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
        std::string analysis_error;
        if (!ensure_apb_analyzed(name, config, analysis_error)) {
            if (analysis_error.rfind("APB config not found:", 0) == 0)
                return protocol_config_not_found_error(
                    action_name(), "apb", name);
            if (!g_apb_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_apb_analyzer.last_cache_error());
            return protocol_analyze_error(
                action_name(), "apb", name, analysis_error);
        }

        const ApbResult* result = g_apb_analyzer.get_result(name);
        if (!result)
            return protocol_analyze_error(
                action_name(), "apb", name,
                "canonical APB result unavailable");

        std::vector<const ApbTransaction*> matches;
        matches.reserve(result->all.size());
        for (const ApbTransaction* transaction : result->all) {
            if (!transaction ||
                !direction_matches(*transaction, direction)) {
                continue;
            }
            if (match_protocol_query_filter(
                    filter, transaction->addr,
                    transaction->addr_width) ==
                ValueFilterMatch::Yes) {
                matches.push_back(transaction);
            }
        }

        auto query = args["query"];
        const int index = query.value("index", -1);
        const int line_limit = query.value("line_limit", -1);
        const bool last = args.value("last", false);
        Json out;
        out["summary"] = {
            {"name", name},
            {"direction", direction},
        };
        out["filter"] = {{"direction", direction}};
        if (filter.has_address)
            out["filter"]["address"] = filter.address_json;

        if (last) {
            const bool found = !matches.empty();
            out["summary"]["query_mode"] = "last";
            out["summary"]["found"] = found;
            if (found)
                out["transaction"] =
                    apb_transaction_json(*matches.back());
            set_query_summary(
                out["summary"], result->diagnostics,
                matches.size(), found ? 1 : 0, false);
            return out;
        }

        if (index > 0 && line_limit < 0) {
            const size_t offset = static_cast<size_t>(index - 1);
            const bool found = offset < matches.size();
            out["summary"]["query_mode"] = "index";
            out["summary"]["found"] = found;
            if (found)
                out["transaction"] =
                    apb_transaction_json(*matches[offset]);
            set_query_summary(
                out["summary"], result->diagnostics,
                matches.size(), found ? 1 : 0, false);
            return out;
        }

        if (line_limit > 0) {
            const size_t begin = index > 0
                ? static_cast<size_t>(index - 1) : 0;
            Json transactions = Json::array();
            for (size_t i = begin;
                 i < matches.size() &&
                 transactions.size() <
                     static_cast<size_t>(line_limit);
                 ++i) {
                transactions.push_back(
                    apb_transaction_json(*matches[i]));
            }
            const bool truncated =
                begin + transactions.size() < matches.size();
            out["summary"]["query_mode"] = "list";
            out["transactions"] = std::move(transactions);
            set_query_summary(
                out["summary"], result->diagnostics,
                matches.size(), out["transactions"].size(), truncated);
            return out;
        }

        out["summary"]["query_mode"] = "count";
        set_query_summary(
            out["summary"], result->diagnostics,
            matches.size(), 0, false);
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
