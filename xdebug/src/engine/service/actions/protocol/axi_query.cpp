#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"
#include "protocol_query_filter.h"

#include "api/text_response_builder.h"
#include "core/npi/time_contract.h"
#include "core/output/completeness.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_manager.h"
#include "waveform/axi/axi_transaction_json.h"

#include <memory>
#include <set>
#include <string>
#include <vector>

namespace xdebug_design {
namespace {

enum class AxiDataProjection { None, Default, All };

std::string xout_scalar(const Json& object, const char* key) {
    if (!object.is_object() || !object.contains(key) ||
        !xdebug::is_xout_scalar_json(object[key])) {
        return std::string();
    }
    return xdebug::json_to_xout_value(object[key]);
}

void emit_axi_scalar_section(
    xdebug::TextResponseBuilder& out,
    const std::string& name,
    const Json& object,
    std::initializer_list<const char*> preferred) {
    if (!object.is_object() || object.empty()) return;
    out.emit_section(name);
    std::set<std::string> emitted;
    for (const char* key : preferred) {
        if (!object.contains(key) || !xdebug::is_xout_scalar_json(object[key])) continue;
        out.emit_kv(key, object[key]);
        emitted.insert(key);
    }
    for (auto it = object.begin(); it != object.end(); ++it) {
        if (emitted.count(it.key()) || !xdebug::is_xout_scalar_json(it.value())) continue;
        out.emit_kv(it.key(), it.value());
    }
}

void emit_axi_transaction_domains(
    xdebug::TextResponseBuilder& out,
    const Json& transaction,
    const std::string& prefix) {
    emit_axi_scalar_section(
        out, prefix + "_address", transaction.value("address", Json::object()),
        {"channel", "valid_begin_time", "handshake_time", "addr", "id",
         "len", "size", "burst"});

    const Json data = transaction.value("data", Json::object());
    emit_axi_scalar_section(
        out, prefix + "_data", data,
        {"channel", "valid_begin_time", "first_handshake_time",
         "last_handshake_time", "beat_count", "expected_beat_count"});
    Json beats = data.value("beats", Json::array());
    if ((!beats.is_array() || beats.empty()) &&
        data.contains("first_beat") && data["first_beat"].is_object()) {
        beats = Json::array({data["first_beat"]});
    }
    if (beats.is_array() && !beats.empty()) {
        std::vector<std::vector<std::string>> rows;
        for (const auto& beat : beats) {
            rows.push_back({
                xout_scalar(beat, "index"), xout_scalar(beat, "handshake_time"),
                xout_scalar(beat, "data"), xout_scalar(beat, "wstrb"),
                xout_scalar(beat, "resp"), xout_scalar(beat, "last")});
        }
        out.emit_section(prefix + "_beats");
        out.emit_table(
            {"index", "handshake_time", "data", "wstrb", "resp", "last"},
            rows);
    }

    emit_axi_scalar_section(
        out, prefix + "_response", transaction.value("response", Json::object()),
        {"channel", "handshake_time", "resp"});
}

std::string render_axi_query_xout(const Json& response) {
    Json metadata = response;
    if (metadata.contains("data") && metadata["data"].is_object()) {
        metadata["data"].erase("transaction");
        metadata["data"].erase("transactions");
    }
    std::string text = render_tabular_xout("axi.query", metadata);
    const Json data = response.value("data", Json::object());

    xdebug::TextResponseBuilder out("xdebug");
    const Json transaction = data.value("transaction", Json());
    if (transaction.is_object() && !transaction.empty()) {
        emit_axi_scalar_section(
            out, "transaction", transaction,
            {"direction", "phase_order", "latency",
             "response_dependency_violation", "match_time"});
        emit_axi_transaction_domains(out, transaction, "transaction");
    }

    const Json transactions = data.value("transactions", Json::array());
    if (transactions.is_array() && !transactions.empty()) {
        std::vector<std::vector<std::string>> rows;
        for (size_t i = 0; i < transactions.size(); ++i) {
            const Json& item = transactions[i];
            rows.push_back({
                std::to_string(i + 1), xout_scalar(item, "direction"),
                xout_scalar(item, "phase_order"), xout_scalar(item, "latency"),
                xout_scalar(item, "response_dependency_violation"),
                xout_scalar(item, "match_time")});
        }
        out.emit_section("transactions");
        out.emit_table(
            {"index", "direction", "phase_order", "latency",
             "response_dependency_violation", "match_time"}, rows);
        for (size_t i = 0; i < transactions.size(); ++i) {
            emit_axi_transaction_domains(
                out, transactions[i], "transaction_" + std::to_string(i + 1));
        }
    }

    std::string details = out.str();
    if (details == "\n") return text;
    while (!text.empty() && text.back() == '\n') text.pop_back();
    return text + "\n\n" + details;
}

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
        ProtocolEnsureResult ensured = ensure_axi_analyzed(name, config);
        if (!ensured.ok()) {
            if (ensured.status == ProtocolEnsureStatus::ConfigNotFound)
                return protocol_config_not_found_error(
                    action_name(), "axi", name);
            if (ensured.status == ProtocolEnsureStatus::StoreError)
                return make_config_store_error(ensured.store);
            if (!g_axi_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    g_axi_analyzer.last_cache_error());
            return protocol_analyze_error(
                action_name(), "axi", name, ensured.message);
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
        const int index = query.value("index", -1);
        const int line_limit = query.value("line_limit", -1);
        const bool last = args.value("last", false);
        const size_t begin = index > 0
            ? static_cast<size_t>(index - 1) : 0;
        const size_t keep_limit = line_limit > 0
            ? static_cast<size_t>(line_limit) : 0;
        size_t matched_count = 0;
        const AxiTransaction* selected = nullptr;
        std::vector<const AxiTransaction*> page;
        if (keep_limit > 0) page.reserve(keep_limit);
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
                const size_t match_index = matched_count++;
                if (last) {
                    selected = &transaction;
                } else if (index > 0 && line_limit < 0) {
                    if (match_index == begin) selected = &transaction;
                } else if (keep_limit > 0 && match_index >= begin &&
                           page.size() < keep_limit) {
                    page.push_back(&transaction);
                }
            }
        }
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
            const bool found = selected != nullptr;
            out["summary"]["query_mode"] = "last";
            out["summary"]["found"] = found;
            if (found)
                out["transaction"] =
                    projected_transaction(*selected, projection, 0);
            set_projection_summary(found ? 1 : 0);
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
                    projected_transaction(
                        *selected, projection, 0);
            set_projection_summary(found ? 1 : 0);
            set_query_summary(
                out["summary"], result->diagnostics,
                matched_count, found ? 1 : 0, false);
            return out;
        }

        if (line_limit > 0) {
            Json transactions = Json::array();
            for (const AxiTransaction* transaction : page) {
                transactions.push_back(projected_transaction(
                    *transaction, projection, transactions.size()));
            }
            const bool truncated =
                begin + transactions.size() < matched_count;
            out["summary"]["query_mode"] = "list";
            out["transactions"] = std::move(transactions);
            set_projection_summary(out["transactions"].size());
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
        return render_axi_query_xout(response);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_axi_query_handler() {
    return std::unique_ptr<EngineActionHandler>(new AxiQueryHandler);
}

}  // namespace xdebug_design
