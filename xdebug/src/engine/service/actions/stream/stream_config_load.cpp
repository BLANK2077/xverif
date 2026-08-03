#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"

#include "waveform/common/xdebug_waveform_paths.h"
#include "waveform/cache/analysis_repository.h"
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
#include <tuple>
#include <vector>

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
Json stream_config_load_example() {
    return Json{{"api_version", "xdebug.v1"},
                {"action", "stream.config.load"},
                {"target", {{"session_id", "case_a"}}},
                {"args", {{"config", {{"streams", Json::array({Json{
                    {"name", "req_stream"},
                    {"signals", {{"clk", "top.u.clk"},
                                  {"req_vld", "top.u.req_vld"},
                                  {"req_data", "top.u.req_data"}}},
                    {"clock", "clk"},
                    {"vld", "req_vld"},
                    {"data", "req_data"}}})}}}}}};
}

class StreamConfigLoadHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "stream.config.load"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }
    Json run(
        ContractBoundRequest& request,
        EngineActionContext& ctx) const override {
        auto args = request.args();
        Json loader_args = Json::object();
        if (args["config"].exists()) {
            loader_args["config"] = args["config"].consume_subtree(
                "stream_config_document_parser");
        }
        if (args["config_path"].exists()) {
            loader_args["config_path"] =
                args["config_path"].get<std::string>();
        }
        Json root;
        std::string error;
        if (!xdebug_waveform::load_stream_config_arg(
                loader_args, root, error))
            return err("INVALID_ARGUMENT", error,
                       {{"invalid_arg", "args"},
                        {"expected", "one of args.config or args.config_path"},
                        {"required_any_of", Json::array({"args.config", "args.config_path"})},
                        {"correct_example", stream_config_load_example()},
                        {"example_note", "Example only; use aliases in stream fields and real paths only in signals map."}});
        std::vector<StreamConfig> streams;
        if (!xdebug_waveform::parse_stream_config_list(root, streams, error))
            return err("INVALID_ARGUMENT", error,
                       {{"invalid_arg", "args.config.streams"},
                        {"expected", "stream config with signals map and alias-based clock/vld/data fields"},
                        {"correct_example", stream_config_load_example()},
                        {"example_note", "Example only; stream config fields must reference aliases, not raw signal paths."}});

        StreamAnalyzer analyzer;
        Json validation = Json::array();
        for (const auto& stream : streams) {
            std::vector<xdebug_waveform::StreamValidationIssue> issues;
            std::string validate_error;
            analyzer.validate_static(g_fsdb_file, stream, issues, validate_error);
            for (const auto& issue : issues) validation.push_back(
                {{"stream", stream.name}, {"severity", issue.severity},
                 {"code", issue.code}, {"message", issue.message}});
            for (const auto& issue : issues) {
                if (issue.severity == "ERROR")
                    return err("INVALID_ARGUMENT", issue.message,
                               {{"invalid_arg", "args.config.streams"},
                                {"expected", "stream config whose aliases resolve to existing waveform signals"},
                                {"correct_example", stream_config_load_example()},
                                {"example_note", "Example only; inspect issue message and fix the referenced alias/path."},
                                {"next_actions", Json::array({"Use value.at on candidate leaf signals to confirm paths.",
                                                               "Keep real signal paths only in signals map values."})}});
            }
        }

        std::string mode = args.value("mode", std::string("replace"));
        StreamManager manager;
        std::vector<xdebug_waveform::StreamConfigChange> changes;
        xdebug_waveform::StoreResult stored =
            manager.load_configs(
                xdebug_waveform::g_session_id,
                streams,
                mode,
                &changes);
        if (!stored.ok()) {
            return make_config_store_error(stored);
        }
        if (xdebug_waveform::g_analysis_repository) {
            std::vector<std::tuple<std::string, std::string, std::string>>
                fingerprint_changes;
            for (const auto& change : changes) {
                fingerprint_changes.emplace_back(
                    change.name, change.old_semantic_fingerprint,
                    change.new_semantic_fingerprint);
            }
            xdebug_waveform::g_analysis_repository->notify_stream_config_changes(
                xdebug_waveform::g_session_id, fingerprint_changes);
        }
        Json out;
        out["summary"] = {{"loaded", streams.size()}, {"mode", mode}};
        out["streams"] = Json::array();
        for (const auto& stream : streams) out["streams"].push_back(stream.name);
        out["issues"] = validation;
        out["validation"] = Json::array();
        for (const auto& stream : streams) {
            Json item = xdebug_waveform::stream_static_validation_json(g_fsdb_file, stream);
            item["stream"] = stream.name;
            out["validation"].push_back(item);
        }
        return out;
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_stream_config_load_handler() {
    return std::unique_ptr<EngineActionHandler>(new StreamConfigLoadHandler);
}

}  // namespace xdebug_design
