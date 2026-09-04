#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/config_store_error.h"
#include "service/engine_globals.h"
#include "protocol_action_helpers.h"
#include "protocol_query_filter.h"

#include "core/npi/time_contract.h"
#include "core/output/completeness.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/apb/apb_exporter.h"
#include "waveform/server/fsdb_value_reader.h"

#include <algorithm>
#include <memory>
#include <string>
#include <vector>

namespace xdebug_design {
namespace {

class ApbExportHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "apb.export"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(ContractBoundRequest& request,
             EngineActionContext&) const override {
        using namespace xdebug_waveform;
        auto args = request.args();
        const std::string name = args.value("name", std::string());
        if (name.empty())
            return protocol_missing_name_error(action_name(), "apb");

        const std::string direction =
            args.value("direction", std::string("all"));
        if (direction != "all" && direction != "write" &&
            direction != "read") {
            return protocol_invalid_enum_error(
                action_name(), "args.direction",
                "direction must be all, write, or read",
                Json::array({"all", "write", "read"}));
        }

        Json address;
        if (args["address"].exists())
            address = args["address"].consume_subtree(
                "apb_export_address_filter");
        ProtocolQueryFilter filter;
        ProtocolQueryFilterError filter_error;
        if (!parse_protocol_query_filter(
                address, Json(), false, filter, filter_error)) {
            return protocol_invalid_arg_error(
                action_name(), filter_error.invalid_arg,
                filter_error.message, filter_error.expected);
        }

        auto time_range = args["time_range"];
        const std::string begin_text =
            time_range.value("begin", std::string());
        const std::string end_text =
            time_range.value("end", std::string());
        if (begin_text.empty() || end_text.empty()) {
            return make_handler_error(
                "MISSING_FIELD",
                "apb.export requires non-empty args.time_range.begin/end",
                {{"invalid_arg", "args.time_range"},
                 {"expected", "non-empty begin and end in a closed time range"},
                 {"correct_example", protocol_action_example(action_name())}});
        }
        npiFsdbTime begin = 0;
        npiFsdbTime end = 0;
        std::string time_error;
        if (!parse_user_time(begin_text.c_str(), false, begin, time_error))
            return protocol_time_error(
                action_name(), "args.time_range.begin", time_error);
        if (!parse_user_time(end_text.c_str(), true, end, time_error))
            return protocol_time_error(
                action_name(), "args.time_range.end", time_error);
        if (end < begin)
            return protocol_time_error(
                action_name(), "args.time_range",
                "apb.export end time is before begin time");

        auto output = args["output"];
        const std::string output_path =
            output.value("path", std::string());
        const std::string format =
            output.value("file_format", std::string("tsv"));
        if (output.contains("file_format") && output_path.empty()) {
            return protocol_invalid_arg_error(
                action_name(), "args.output.file_format",
                "output.file_format requires a non-empty output.path",
                "output object with both path and file_format");
        }
        if (format != "tsv" && format != "csv") {
            return protocol_invalid_enum_error(
                action_name(), "args.output.file_format",
                "output.file_format must be tsv or csv",
                Json::array({"tsv", "csv"}));
        }

        ApbConfig config;
        const ProtocolEnsureResult ensured =
            ensure_apb_analyzed(name, config);
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
        const ApbResult* canonical = g_apb_analyzer.get_result(name);
        if (!canonical)
            return protocol_analyze_error(
                action_name(), "apb", name,
                "canonical APB result unavailable");

        ApbExportResult result;
        result.format = format;
        ApbExporter exporter;
        exporter.build(
            name, *canonical,
            [&](const ApbTransaction& transaction) {
                if (!protocol_direction_matches(
                        transaction.is_write, direction))
                    return ValueFilterMatch::No;
                return match_protocol_query_filter(
                    filter, transaction.addr, transaction.addr_width);
            },
            begin, end, result);

        const std::size_t preview_count = output_path.empty()
            ? std::min<std::size_t>(8, result.transactions.size()) : 0;
        Json summary = {
            {"name", name},
            {"direction", direction},
            {"status", output_path.empty() ? "preview" : "written"},
            {"output_written", !output_path.empty()},
            {"scanned_transaction_count", result.scanned_transaction_count},
            {"in_range_transaction_count", result.in_range_count},
            {"matched_transaction_count", result.transactions.size()},
            {"matched_write_count", result.write_count},
            {"matched_read_count", result.read_count},
            {"unresolved_filter_count", result.unresolved_filter_count},
            {"preview_row_count", preview_count},
            {"sample_count", result.sample_count},
            {"full_scan_count", result.full_scan_count},
            {"value_width_complete", result.value_width_complete},
            {"width_diagnostics", result.width_diagnostics},
            {"requested_range", {{"begin", xdebug_core::format_time(g_fsdb_file, begin)},
                                  {"end", xdebug_core::format_time(g_fsdb_file, end)}}},
            {"scanned_range", {{"begin", xdebug_core::format_time(g_fsdb_file, result.scan_begin)},
                                {"end", xdebug_core::format_time(g_fsdb_file, result.scan_end)}}}
        };

        Json out;
        if (output_path.empty()) {
            Json preview = Json::array();
            for (std::size_t index = 0; index < preview_count; ++index) {
                preview.push_back(apb_export_transaction_json(
                    g_fsdb_file, *result.transactions[index]));
            }
            const bool response_truncated =
                preview_count < result.transactions.size();
            std::vector<std::string> scopes;
            if (!result.analysis_complete)
                scopes.push_back("analysis_transactions");
            if (response_truncated)
                scopes.push_back("response_preview");
            xdebug_core::set_completeness(
                summary, result.analysis_complete,
                result.analysis_complete, response_truncated,
                result.transactions.size(), preview_count, scopes);
            out["summary"] = summary;
            out["preview"] = std::move(preview);
            return out;
        }

        std::string data_path;
        std::string meta_path;
        std::uint64_t data_bytes = 0;
        std::string export_error;
        if (!exporter.write_files(output_path, g_fsdb_file, result,
                                  data_path, meta_path, data_bytes,
                                  export_error)) {
            return make_handler_error(
                "ACTION_FAILED", export_error,
                {{"cause_code", "EXPORT_FAILED"},
                 {"invalid_arg", "args.output.path"},
                 {"expected", "writable APB output path prefix"},
                 {"correct_example", protocol_action_example(action_name())}});
        }
        summary["artifact_bytes"] = data_bytes;
        summary["output"] = {{"path", output_path},
                             {"data_path", data_path},
                             {"meta_path", meta_path},
                             {"file_format", format}};
        std::vector<std::string> scopes;
        if (!result.analysis_complete)
            scopes.push_back("analysis_transactions");
        xdebug_core::set_completeness(
            summary, result.analysis_complete, result.analysis_complete,
            false, result.transactions.size(), result.transactions.size(),
            scopes);
        out["summary"] = summary;
        return out;
    }

    std::string render_xout(const Json& response) const override {
        Json projected = response;
        projected["summary"] = project_xout_summary_fields(
            response.value("summary", Json::object()),
            {"name", "direction", "status", "matched_transaction_count",
             "matched_write_count", "matched_read_count",
             "unresolved_filter_count", "preview_row_count", "row_count",
             "requested_range", "scanned_range", "output",
             "scan_complete", "analysis_complete", "response_truncated",
             "total_count", "returned_count", "truncation_scopes",
             "value_width_complete", "width_diagnostics"});
        return render_tabular_xout(action_name(), projected);
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_apb_export_handler() {
    return std::unique_ptr<EngineActionHandler>(new ApbExportHandler);
}

}  // namespace xdebug_design
