#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"

#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/stream/legacy_stream_analyzer_adapter.h"
#include "waveform/stream/stream_exporter.h"
#include "waveform/stream/stream_manager.h"
#include "core/output/completeness.h"
#include "core/npi/time_contract.h"

#include "npi_fsdb.h"
#include "npi_L1.h"

#include <ctime>
#include <memory>
#include <sstream>
#include <sys/stat.h>

namespace xdebug_design {
namespace {

using xdebug_waveform::Json;
using xdebug_waveform::StreamAnalysis;
using xdebug_waveform::analyze_stream_cached_with_legacy_differential;
using xdebug_waveform::AnalysisCacheScope;
using xdebug_waveform::StreamConfig;
using xdebug_waveform::StreamExporter;
using xdebug_waveform::StreamManager;
using xdebug_waveform::StreamQueryOptions;

Json err(const std::string& code, const std::string& message, const Json& details) {
    return make_handler_error(code, message, details);
}
Json stream_export_example(const std::string& stream = "req_stream",
                           const std::string& kind = "transfer") {
    return Json{{"api_version", "xdebug.v1"},
                {"action", "stream.export"},
                {"target", {{"session_id", "case_a"}}},
                {"args", {{"stream", stream},
                          {"kind", kind},
                          {"output", {{"path", "stream.tsv"}, {"file_format", "tsv"}}}}}};
}
Json stream_name_error(const std::string& name) {
    Json details = {{"invalid_arg", "args.stream"},
                    {"expected", "name of a previously loaded stream config"},
                    {"correct_example", stream_export_example()},
                    {"example_note", "Example only; replace target.session_id, args.stream, and output.path with the active case values."},
                    {"next_actions", Json::array({"Call stream.config.list to inspect loaded stream names.",
                                                   "Call stream.config.load before exporting a stream."})}};
    if (!name.empty()) {
        details["missing_name"] = name;
        details["missing_resource"] = "stream config";
    }
    return err(name.empty() ? "MISSING_FIELD" : "CONFIG_NOT_FOUND",
               name.empty() ? "args.stream is required" : "stream config not found: " + name,
               details);
}
size_t row_count_for_kind(const StreamAnalysis& analysis, const std::string& kind) {
    if (kind == "packet") return analysis.packets.size();
    if (kind == "packet_beats") return analysis.transfer_count;
    return analysis.transfers.size();
}
Json preview_for_kind(const StreamAnalysis& analysis, const std::string& kind, int line_limit) {
    Json rows = Json::array();
    int limit = line_limit > 0 ? line_limit : 16;
    if (kind == "packet") {
        for (size_t i = 0; i < analysis.packets.size() && static_cast<int>(i) < limit; ++i)
            rows.push_back(xdebug_waveform::stream_packet_json(analysis.packets[i]));
    } else {
        for (size_t i = 0; i < analysis.transfers.size() && static_cast<int>(i) < limit; ++i)
            rows.push_back(xdebug_waveform::stream_row_json(analysis.transfers[i]));
    }
    return rows;
}
std::string code_for_stream_error(const std::string& message, const std::string& default_code) {
    return message.find("0x prefix is not accepted") != std::string::npos ||
           message.find("invalid value literal") != std::string::npos
        ? "VALUE_FORMAT_INVALID"
        : default_code;
}
Json stream_time_error(const std::string& message) {
    return err("INVALID_TIME", message,
               {{"invalid_arg", "args.time_range"},
                {"expected", "args.time_range.begin/end time strings such as 0ns and 100ns"},
                {"correct_example", stream_export_example()},
                {"example_note", "Example only; omit time_range for full waveform or use begin/end strings with units."},
                {"next_actions", Json::array({"Fix args.time_range.begin/end to include a valid unit.",
                                               "Omit args.time_range to export the whole waveform window."})}});
}
Json stream_analyze_error(const std::string& message) {
    return err(code_for_stream_error(message, "ACTION_FAILED"), message,
               {{"cause_code", "STREAM_ANALYZE_FAILED"},
                {"expected", "loaded stream config whose aliased signal paths exist in the active FSDB"},
                {"correct_example", stream_export_example()},
                {"next_actions", Json::array({"Call stream.describe to inspect config signal aliases.",
                                               "Call stream.validate before exporting large stream results."})}});
}
bool parse_time_arg(const std::string& text, bool allow_max, npiFsdbTime& out, std::string& error) {
    if (text.empty()) {
        out = 0;
        return true;
    }
    xdebug_core::TimeParseOptions options;
    options.allow_max = allow_max;
    options.use_fsdb_max = true;
    options.default_unit = "ns";
    return xdebug_core::parse_time(g_fsdb_file, text, options, out, error);
}
bool range_from_args(
    ContractJsonView args,
    StreamQueryOptions& options,
    std::string& error) {
    npiFsdbTime min_t = 0, max_t = 0;
    npi_fsdb_min_time(g_fsdb_file, &min_t);
    npi_fsdb_max_time(g_fsdb_file, &max_t);
    auto time_range = args["time_range"];
    std::string start =
        time_range.value("begin", std::string());
    std::string end =
        time_range.value("end", std::string("max"));
    if (start.empty()) options.begin = min_t;
    else if (!parse_time_arg(start, false, options.begin, error)) return false;
    if (end.empty() || end == "max") options.end = max_t;
    else if (!parse_time_arg(end, true, options.end, error)) return false;
    options.limit = args.value("line_limit", 32);
    if (options.limit <= 0) options.limit = 32;
    options.channel_filter = args.value("channel", std::string());
    return true;
}
bool get_config(
    ContractJsonView args,
    StreamConfig& config,
    Json& fail) {
    std::string name = args.value("stream", std::string());
    if (name.empty()) {
        fail = stream_name_error(name);
        return false;
    }
    StreamManager manager;
    xdebug_waveform::StoreResult loaded =
        manager.get_stream(
            xdebug_waveform::g_session_id,
            name,
            config);
    if (!loaded.ok()) {
        fail =
            loaded.status == xdebug_waveform::StoreStatus::NotFound
                ? stream_name_error(name)
                : make_config_store_error(loaded);
        return false;
    }
    return true;
}

class StreamExportHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "stream.export"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        auto args = request.args();
        Json fail;
        StreamConfig config;
        if (!get_config(args, config, fail)) return fail;
        StreamQueryOptions options;
        std::string error;
        const std::string cache_scope =
            args.value("cache_scope", std::string("full"));
        if (cache_scope != "full" && cache_scope != "range")
            return err("INVALID_ENUM", "cache_scope must be full or range",
                       {{"invalid_arg", "args.cache_scope"},
                        {"expected", "one of full, range"},
                        {"available_values", Json::array({"full", "range"})},
                        {"correct_example", stream_export_example(config.name)}});
        if (cache_scope == "range" &&
            (!args.contains("time_range") ||
             !args["time_range"].is_object() ||
             args["time_range"].empty())) {
            Json example = stream_export_example(config.name);
            example["args"]["cache_scope"] = "range";
            example["args"]["time_range"] = {
                {"begin", "0ns"}, {"end", "100ns"}};
            return err(
                "INVALID_ARGUMENT",
                "cache_scope=range requires a non-empty time_range",
                {{"invalid_arg", "args.time_range"},
                 {"expected", "time_range with begin and/or end"},
                 {"correct_example", example}});
        }
        if (!range_from_args(args, options, error))
            return stream_time_error(error);
        options.limit = 0;
        StreamAnalysis analysis;
        if (!analyze_stream_cached_with_legacy_differential(
                xdebug_waveform::g_stream_analyzer, g_fsdb_file, config,
                options,
                cache_scope == "range" ? AnalysisCacheScope::Range
                                       : AnalysisCacheScope::Full,
                analysis, error)) {
            if (!xdebug_waveform::g_stream_analyzer.last_cache_error().empty())
                return make_analysis_cache_error(
                    xdebug_waveform::g_stream_analyzer.last_cache_error());
            return stream_analyze_error(error);
        }
        std::string kind = args.value("kind", std::string("transfer"));
        auto output_arg = args["output"];
        std::string format = output_arg.value("file_format", std::string("tsv"));
        if (format != "tsv" && format != "csv" && format != "xout")
            return err("INVALID_ENUM", "output.file_format must be tsv, csv, or xout",
                       {{"invalid_arg", "args.output.file_format"},
                        {"expected", "one of tsv, csv, xout"},
                        {"available_values", Json::array({"tsv", "csv", "xout"})},
                        {"correct_example", stream_export_example(config.name)},
                        {"example_note", "Example only; output.file_format controls exported file content, not MCP output_format."}});
        std::string output = output_arg.value("path", std::string());
        if (output_arg.contains("file_format") && output.empty())
            return err(
                "INVALID_REQUEST",
                "stream.export output.file_format requires a non-empty output.path",
                {{"invalid_arg", "args.output.file_format"},
                 {"expected", "output object with both path and file_format"}});
        if (!output.empty() && args.contains("line_limit"))
            return err("INVALID_REQUEST",
                       "stream.export args.line_limit only controls preview rows and is not valid for file export",
                       {{"invalid_arg", "args.line_limit"},
                        {"expected", "omit line_limit when args.output.path is present"}});
        size_t row_count = row_count_for_kind(analysis, kind);
        Json summary = xdebug_waveform::stream_summary_json(config, analysis);
        summary["status"] = output.empty() ? "preview" : "written";
        summary["output_written"] = !output.empty();
        summary["row_count"] = row_count;
        summary["line_limit"] = args.value("line_limit", 16);
        summary["kind"] = kind;
        if (output.empty()) {
            Json preview =
                preview_for_kind(analysis, kind, summary["line_limit"].get<int>());
            const bool response_truncated = preview.size() < row_count;
            std::vector<std::string> truncation_scopes;
            if (!analysis.analysis_complete)
                truncation_scopes.push_back("analysis_samples");
            if (response_truncated)
                truncation_scopes.push_back("response_preview");
            xdebug_core::set_completeness(
                summary,
                analysis.analysis_complete,
                analysis.analysis_complete,
                response_truncated,
                row_count,
                preview.size(),
                truncation_scopes);
            return Json{{"summary", summary}, {"preview", preview}};
        }
        std::string meta;
        StreamExporter exporter;
        bool ok = false;
        if (kind == "packet") ok = exporter.export_packet_file(output, format, config, analysis, meta, error);
        else if (kind == "packet_beats") ok = exporter.export_packet_beats_file(output, format, config, analysis, meta, error);
        else if (kind == "transfer") ok = exporter.export_transfer_file(output, format, config, analysis, meta, error);
        else return err("INVALID_ENUM", "kind must be transfer, packet, or packet_beats",
                        {{"invalid_arg", "args.kind"},
                         {"expected", "one of transfer, packet, packet_beats"},
                         {"available_values", Json::array({"transfer", "packet", "packet_beats"})},
                         {"correct_example", stream_export_example(config.name, "transfer")},
                         {"example_note", "Example only; choose kind from available_values."}});
        if (!ok) return err("ACTION_FAILED", error,
                            {{"cause_code", "EXPORT_FAILED"},
                             {"invalid_arg", "args.output.path"},
                             {"expected", "writable output path"},
                             {"correct_example", stream_export_example(config.name, kind)}});
        Json output_info = {{"path", output}, {"meta_path", meta}, {"file_format", format}};
        summary["output"] = output_info;
        xdebug_core::set_completeness(
            summary,
            analysis.analysis_complete,
            analysis.analysis_complete,
            false,
            row_count,
            row_count,
            analysis.analysis_complete
                ? std::vector<std::string>{}
                : std::vector<std::string>{"analysis_samples"});
        return Json{{"summary", summary}};
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_stream_export_handler() {
    return std::unique_ptr<EngineActionHandler>(new StreamExportHandler);
}

}  // namespace xdebug_design
