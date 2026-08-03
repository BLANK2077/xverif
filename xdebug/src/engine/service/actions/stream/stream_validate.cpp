#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"

#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/stream/legacy_stream_analyzer_adapter.h"
#include "waveform/stream/stream_analyzer.h"
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
using xdebug_waveform::analyze_stream_cached_with_legacy_differential;
using xdebug_waveform::AnalysisCacheScope;
using xdebug_waveform::StreamAnalysis;
using xdebug_waveform::StreamAnalyzer;
using xdebug_waveform::StreamConfig;
using xdebug_waveform::StreamExporter;
using xdebug_waveform::StreamManager;
using xdebug_waveform::StreamQueryOptions;

Json err(const std::string& code, const std::string& message, const Json& details) {
    return make_handler_error(code, message, details);
}
Json stream_validate_example(const std::string& stream = "req_stream") {
    return Json{{"api_version", "xdebug.v1"},
                {"action", "stream.validate"},
                {"target", {{"session_id", "case_a"}}},
                {"args", {{"stream", stream}, {"dynamic", true}}}};
}
Json stream_name_error(const std::string& name) {
    Json details = {{"invalid_arg", "args.stream"},
                    {"expected", "name of a previously loaded stream config"},
                    {"correct_example", stream_validate_example()},
                    {"example_note", "Example only; replace target.session_id and args.stream with active case values."},
                    {"next_actions", Json::array({"Call stream.config.list to inspect loaded stream names.",
                                                   "Call stream.config.load before validating a stream."})}};
    if (!name.empty()) {
        details["missing_name"] = name;
        details["missing_resource"] = "stream config";
    }
    return err(name.empty() ? "MISSING_FIELD" : "CONFIG_NOT_FOUND",
               name.empty() ? "args.stream is required" : "stream config not found: " + name,
               details);
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
                {"correct_example", stream_validate_example()},
                {"example_note", "Example only; omit time_range for full waveform or use begin/end strings with units."},
                {"next_actions", Json::array({"Fix args.time_range.begin/end to include a valid unit.",
                                               "Omit args.time_range to validate the whole waveform window."})}});
}
Json stream_analyze_error(const std::string& message) {
    return err(code_for_stream_error(message, "ACTION_FAILED"), message,
               {{"cause_code", "STREAM_ANALYZE_FAILED"},
                {"expected", "loaded stream config whose aliased signal paths exist in the active FSDB"},
                {"correct_example", stream_validate_example()},
                {"next_actions", Json::array({"Call stream.describe to inspect config signal aliases.",
                                               "Call stream.config.load again after fixing signal paths."})}});
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
Json issue_json(const std::vector<xdebug_waveform::StreamValidationIssue>& issues) {
    Json arr = Json::array();
    for (const auto& issue : issues) {
        arr.push_back({{"severity", issue.severity}, {"code", issue.code}, {"message", issue.message}});
    }
    return arr;
}
void add_issue(std::vector<xdebug_waveform::StreamValidationIssue>& issues,
               const std::string& severity,
               const std::string& code,
               const std::string& message) {
    issues.push_back(xdebug_waveform::StreamValidationIssue{severity, code, message});
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

class StreamValidateHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "stream.validate"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        auto args = request.args();
        Json fail;
        StreamConfig config;
        if (!get_config(args, config, fail)) return fail;
        const bool dynamic = args.value("dynamic", true);
        std::string static_only_arg;
        for (const char* field : {
                 "cache_scope", "time_range", "line_limit", "channel"}) {
            if (args.contains(field)) {
                static_only_arg = field;
                break;
            }
        }
        if (!dynamic && !static_only_arg.empty()) {
            Json example = stream_validate_example(config.name);
            example["args"]["dynamic"] = false;
            return err(
                "INVALID_ARGUMENT",
                static_only_arg +
                    " is only valid when stream.validate dynamic=true",
                {{"invalid_arg", "args." + static_only_arg},
                 {"expected",
                  "omit cache_scope, time_range, line_limit, and channel "
                  "for static validation"},
                 {"correct_example", example}});
        }
        const std::string cache_scope =
            args.value("cache_scope", std::string("full"));
        if (cache_scope != "full" && cache_scope != "range")
            return err("INVALID_ENUM", "cache_scope must be full or range",
                       {{"invalid_arg", "args.cache_scope"},
                        {"expected", "one of full, range"},
                        {"available_values", Json::array({"full", "range"})},
                        {"correct_example", stream_validate_example(config.name)}});
        if (cache_scope == "range" &&
            (!args.contains("time_range") ||
             !args["time_range"].is_object() ||
             args["time_range"].empty())) {
            Json example = stream_validate_example(config.name);
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
        StreamAnalyzer analyzer;
        std::vector<xdebug_waveform::StreamValidationIssue> issues;
        std::string error;
        bool static_ok = analyzer.validate_static(g_fsdb_file, config, issues, error);

        Json dyn = Json::object();
        bool dynamic_complete = !dynamic;
        if (static_ok && dynamic) {
            StreamQueryOptions options;
            if (!range_from_args(args, options, error))
                return stream_time_error(error);
            options.limit = args.value("line_limit", 256);
            options.query_kind = "validate";
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
            if (analysis.vld_cycles == 0) add_issue(issues, "WARNING", "VLD_NEVER_TRUE", "vld was never true in validation window");
            if (analysis.transfer_count == 0) add_issue(issues, "WARNING", "NO_TRANSFER", "no transfer observed in validation window");
            if (analysis.ready_bp_conflict_count > 0) add_issue(issues, "WARNING", "READY_BP_CONFLICT", "observed vld=1,rdy=1,bp=1");
            if (analysis.packet_stable_mismatch_count > 0) add_issue(issues, "WARNING", "PACKET_STABLE_FIELD_MISMATCH", "observed packet_stable_fields changing within packet");
            dyn = xdebug_waveform::stream_summary_json(config, analysis);
            for (const char* field : {
                     "scan_complete",
                     "analysis_complete",
                     "response_truncated",
                     "total_count",
                     "returned_count",
                     "truncation_scopes"}) {
                dyn.erase(field);
            }
            dynamic_complete = analysis.analysis_complete;
        }
        bool has_error = false;
        for (const auto& issue : issues) if (issue.severity == "ERROR") has_error = true;
        Json out = {
            {"summary", {{"stream", config.name}, {"ok", !has_error},
                         {"static_validation_complete", true},
                         {"dynamic_requested", dynamic}}},
            {"issues", issue_json(issues)},
            {"dynamic", dyn}
        };
        const bool analysis_complete = static_ok && dynamic_complete;
        xdebug_core::set_completeness(
            out["summary"],
            analysis_complete,
            analysis_complete,
            false,
            issues.size(),
            issues.size(),
            analysis_complete
                ? std::vector<std::string>{}
                : std::vector<std::string>{"analysis_validation"});
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_stream_validate_handler() {
    return std::unique_ptr<EngineActionHandler>(new StreamValidateHandler);
}

}  // namespace xdebug_design
