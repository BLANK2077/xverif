#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"

#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/stream/stream_analyzer.h"
#include "waveform/stream/stream_exporter.h"
#include "waveform/stream/stream_manager.h"
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
using xdebug_waveform::StreamAnalyzer;
using xdebug_waveform::StreamConfig;
using xdebug_waveform::StreamExporter;
using xdebug_waveform::StreamManager;
using xdebug_waveform::StreamQueryOptions;

Json err(const std::string& code, const std::string& message, const Json& details) {
    return make_handler_error(code, message, details);
}
Json stream_describe_example(const std::string& stream = "req_stream") {
    return Json{{"api_version", "xdebug.v1"},
                {"action", "stream.describe"},
                {"target", {{"session_id", "case_a"}}},
                {"args", {{"stream", stream}}}};
}
Json stream_name_error(const std::string& name) {
    Json details = {{"invalid_arg", "args.stream"},
                    {"expected", "name of a previously loaded stream config"},
                    {"correct_example", stream_describe_example()},
                    {"example_note", "Example only; replace target.session_id and args.stream with active case values."},
                    {"next_actions", Json::array({"Call stream.config.list to inspect loaded stream names.",
                                                   "Call stream.config.load before showing a stream."})}};
    if (!name.empty()) {
        details["missing_name"] = name;
        details["missing_resource"] = "stream config";
    }
    return err(name.empty() ? "MISSING_FIELD" : "CONFIG_NOT_FOUND",
               name.empty() ? "args.stream is required" : "stream config not found: " + name,
               details);
}
Json issue_json(const std::vector<xdebug_waveform::StreamValidationIssue>& issues) {
    Json arr = Json::array();
    for (const auto& issue : issues) {
        arr.push_back({{"severity", issue.severity}, {"code", issue.code}, {"message", issue.message}});
    }
    return arr;
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

class StreamDescribeHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "stream.describe"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    bool include_xout_summary() const override { return false; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        Json fail;
        StreamConfig config;
        if (!get_config(request.args(), config, fail)) return fail;
        StreamAnalyzer analyzer;
        std::vector<xdebug_waveform::StreamValidationIssue> issues;
        std::string error;
        analyzer.validate_static(g_fsdb_file, config, issues, error);
        Json out;
        out["summary"] = {{"stream", config.name}, {"handshake", xdebug_waveform::stream_handshake_text(config)},
                          {"packet_enabled", xdebug_waveform::stream_packet_enabled(config)}};
        out["config"] = xdebug_waveform::stream_config_json(config);
        out["issues"] = issue_json(issues);
        out["validation"] = xdebug_waveform::stream_static_validation_json(g_fsdb_file, config);
        out["semantics"] = {{"transfer", xdebug_waveform::stream_handshake_text(config)},
                            {"stall", config.rdy.empty() && config.bp.empty() ? "none" : "enabled"}};
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_stream_describe_handler() {
    return std::unique_ptr<EngineActionHandler>(new StreamDescribeHandler);
}

}  // namespace xdebug_design
