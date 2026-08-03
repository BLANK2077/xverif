#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"
#include "protocol_query_filter.h"

#include "core/npi/time_contract.h"
#include "core/output/completeness.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_transaction_json.h"

#include <memory>
#include <string>
#include <vector>

namespace xdebug_design {
namespace {

enum class AxiDataProjection { None, Default, All };

const char* data_scope(AxiDataProjection projection) {
    if (projection == AxiDataProjection::All)
        return "all_returned_transactions_full";
    if (projection == AxiDataProjection::Default)
        return "first_beat_each_with_first_transaction_full";
    return "none";
}

Json projected_transaction(
    const xdebug_waveform::AxiTransaction& transaction,
    AxiDataProjection projection,
    size_t returned_index) {
    const bool include_all =
        projection == AxiDataProjection::All ||
        (projection == AxiDataProjection::Default &&
         returned_index == 0);
    const bool include_first =
        projection == AxiDataProjection::Default &&
        returned_index > 0;
    return xdebug_waveform::axi_transaction_to_json(
        xdebug_waveform::g_fsdb_file,
        transaction,
        include_all,
        include_first);
}

bool parse_time_range(
    ContractJsonView args,
    bool& enabled,
    npiFsdbTime& begin,
    npiFsdbTime& end,
    Json& canonical,
    Json& failure,
    const char* action) {
    enabled = args["time_range"].exists();
    if (!enabled) return true;

    npi_fsdb_min_time(xdebug_waveform::g_fsdb_file, &begin);
    npi_fsdb_max_time(xdebug_waveform::g_fsdb_file, &end);
    auto time_range = args["time_range"];
    const std::string begin_text =
        time_range.value("begin", std::string());
    const std::string end_text =
        time_range.value("end", std::string());
    std::string error;
    if (!begin_text.empty() &&
        !xdebug_waveform::parse_user_time(
            begin_text.c_str(), false, begin, error)) {
        failure = protocol_time_error(
            action, "args.time_range.begin", error);
        return false;
    }
    if (!end_text.empty() &&
        !xdebug_waveform::parse_user_time(
            end_text.c_str(), true, end, error)) {
        failure = protocol_time_error(
            action, "args.time_range.end", error);
        return false;
    }
    if (begin > end) {
        failure = protocol_invalid_arg_error(
            action,
            "args.time_range",
            "time_range begin must not exceed end",
            "closed range with begin <= end");
        return false;
    }
    canonical = {
        {"begin", xdebug_core::format_time(
            xdebug_waveform::g_fsdb_file, begin)},
        {"end", xdebug_core::format_time(
            xdebug_waveform::g_fsdb_file, end)},
    };
    return true;
}

void set_query_summary(
    Json& summary,
    const xdebug_waveform::AxiDiagnostics& diagnostics,
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

class AxiQueryHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "axi.query"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext&) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        const std::string name = args.value("name", std::string());
        if (name.empty())
            return protocol_missing_name_error(action_name(), "axi");

        auto output = args["output"];
        AxiDataProjection projection = AxiDataProjection::Default;
        if (output.contains("include_data")) {
            projection = output.value("include_data", false)
                ? AxiDataProjection::All
                : AxiDataProjection::None;
        }

        AxiConfig config;
        std::string analysis_error;
        if (!ensure_axi_analyzed(name, config, analysis_error)) {
            if (analysis_error.rfind("AXI config not found:", 0) == 0)
                return protocol_config_not_found_error(
                    action_name(), "axi", name);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return protocol_analyze_error(
                action_name(), "axi", name, analysis_error);
        }

        const AxiResult* result = g_axi_analyzer.get_result(name);
        if (!result)
            return protocol_analyze_error(
                action_name(), "axi", name,
                "canonical AXI result unavailable");

        auto query = args["query"];
        const std::string channel =
            query.value("channel", std::string());
        const std::string handshake_text =
            query.value("handshake_time", std::string());
        if (!channel.empty() || !handshake_text.empty()) {
            npiFsdbTime handshake_time = 0;
            std::string error;
            if (!parse_user_time(
                    handshake_text.c_str(), false,
                    handshake_time, error)) {
                return protocol_invalid_arg_error(
                    action_name(),
                    "args.query.handshake_time",
                    error,
                    "canonical time string such as 120ns");
            }
            AxiHandshakeMatch match;
            const bool found = g_axi_analyzer.get_by_handshake(
                name, channel, handshake_time, match);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            Json out;
            out["summary"] = {
                {"name", name},
                {"query_mode", "handshake"},
                {"found", found},
                {"data_scope", found
                    ? data_scope(projection) : "none"},
            };
            if (projection == AxiDataProjection::Default && found) {
                out["summary"]["data_hint"] =
                    "Each transaction includes its first beat and the first "
                    "transaction includes all beats. To inspect complete data "
                    "for another transaction, narrow it with query.index, last, "
                    "address, id, or time_range, then set "
                    "output.include_data=true.";
            }
            out["match"] = {
                {"channel", channel},
                {"handshake_time", xdebug_core::format_time(
                    g_fsdb_file, handshake_time)},
            };
            if (found && match.txn) {
                out["match"]["direction"] =
                    match.txn->is_write ? "write" : "read";
                if (match.beat_index > 0)
                    out["match"]["beat_index"] = match.beat_index;
                out["transaction"] =
                    projected_transaction(*match.txn, projection, 0);
            }
            set_query_summary(
                out["summary"], result->diagnostics,
                found ? 1 : 0, found ? 1 : 0, false);
            return out;
        }

        Json address;
        Json id;
        if (args["address"].exists()) {
            address = args["address"].consume_subtree(
                "axi_query_address_filter");
        }
        if (args["id"].exists()) {
            id = args["id"].consume_subtree(
                "axi_query_id_filter");
        }
        ProtocolQueryFilter filter;
        ProtocolQueryFilterError filter_error;
        if (!parse_protocol_query_filter(
                address, id, true, filter, filter_error)) {
            return protocol_invalid_arg_error(
                action_name(), filter_error.invalid_arg,
                filter_error.message, filter_error.expected);
        }

        bool has_time_range = false;
        npiFsdbTime time_begin = 0;
        npiFsdbTime time_end = 0;
        Json canonical_time_range;
        Json time_failure;
        if (!parse_time_range(
                args, has_time_range, time_begin, time_end,
                canonical_time_range, time_failure,
                action_name())) {
            return time_failure;
        }

        const std::string direction =
            args.value("direction", std::string("write"));
        const std::vector<AxiTransaction>& source =
            direction == "read" ? result->reads : result->writes;
        std::vector<const AxiTransaction*> matches;
        matches.reserve(source.size());
        for (const AxiTransaction& transaction : source) {
            if (has_time_range &&
                (transaction.addr_time < time_begin ||
                 transaction.addr_time > time_end)) {
                continue;
            }
            if (match_protocol_query_filter(
                    filter,
                    transaction.addr,
                    transaction.addr_width,
                    transaction.id,
                    transaction.id_width) ==
                ValueFilterMatch::Yes) {
                matches.push_back(&transaction);
            }
        }

        const int index = query.value("index", -1);
        const int line_limit = query.value("line_limit", -1);
        const bool last = args.value("last", false);
        Json out;
        out["summary"] = {
            {"name", name},
            {"direction", direction},
            {"data_scope", "none"},
        };
        out["filter"] = {{"direction", direction}};
        if (filter.has_address)
            out["filter"]["address"] = filter.address_json;
        if (filter.has_id)
            out["filter"]["id"] = filter.id_json;
        if (has_time_range)
            out["filter"]["time_range"] = canonical_time_range;

        auto set_projection_summary = [&](size_t returned_count) {
            out["summary"]["data_scope"] = returned_count == 0
                ? "none" : data_scope(projection);
            if (returned_count > 0 &&
                projection == AxiDataProjection::Default) {
                out["summary"]["data_hint"] =
                    "Each transaction includes its first beat and the first "
                    "transaction includes all beats. To inspect complete data "
                    "for another transaction, narrow it with query.index, last, "
                    "address, id, or time_range, then set "
                    "output.include_data=true.";
            }
        };

        if (last) {
            const bool found = !matches.empty();
            out["summary"]["query_mode"] = "last";
            out["summary"]["found"] = found;
            if (found)
                out["transaction"] =
                    projected_transaction(*matches.back(), projection, 0);
            set_projection_summary(found ? 1 : 0);
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
                    projected_transaction(
                        *matches[offset], projection, 0);
            set_projection_summary(found ? 1 : 0);
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
                transactions.push_back(projected_transaction(
                    *matches[i], projection, transactions.size()));
            }
            const bool truncated =
                begin + transactions.size() < matches.size();
            out["summary"]["query_mode"] = "list";
            out["transactions"] = std::move(transactions);
            set_projection_summary(out["transactions"].size());
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

std::unique_ptr<EngineActionHandler> make_axi_query_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiQueryHandler);
}

}  // namespace xdebug_design
