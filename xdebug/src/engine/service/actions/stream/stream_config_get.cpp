#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"
#include "service/config_store_error.h"

#include "waveform/stream/stream_manager.h"

#include <memory>

namespace xdebug_design {
namespace {

using xdebug_waveform::Json;
using xdebug_waveform::StreamConfig;
using xdebug_waveform::StreamManager;

Json stream_config_get_example() {
    return Json{{"api_version", "xdebug.v1"},
                {"action", "stream.config.get"},
                {"target", {{"session_id", "case_a"}}},
                {"args", {{"name", "req_stream"}}}};
}

class StreamConfigGetHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "stream.config.get"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(
        ContractBoundRequest& request,
        EngineActionContext&) const override {
        auto args = request.args();
        const std::string name = args.value("name", std::string());
        if (name.empty()) {
            return make_handler_error(
                "MISSING_FIELD",
                "args.name is required",
                {{"invalid_arg", "args.name"},
                 {"expected", "name of a previously loaded stream config"},
                 {"correct_example", stream_config_get_example()},
                 {"example_note",
                  "Example only; replace target.session_id and args.name "
                  "with the active session and loaded stream name."}});
        }

        StreamManager manager;
        StreamConfig config;
        xdebug_waveform::StoreResult loaded =
            manager.get_stream(
                xdebug_waveform::g_session_id,
                name,
                config);
        if (!loaded.ok() &&
            loaded.status !=
                xdebug_waveform::StoreStatus::NotFound) {
            return make_config_store_error(loaded);
        }
        if (!loaded.ok()) {
            return make_handler_error(
                "CONFIG_NOT_FOUND",
                "stream config not found: " + name,
                {{"invalid_arg", "args.name"},
                 {"expected", "name returned by stream.config.list"},
                 {"missing_name", name},
                 {"missing_resource", "stream config"},
                 {"correct_example", stream_config_get_example()},
                 {"example_note",
                  "Example only; call stream.config.list and replace "
                  "args.name with an existing stream config name."},
                 {"next_actions", Json::array({
                     "Call stream.config.list to inspect loaded stream names.",
                     "Call stream.config.load before reading a named stream config."
                 })}});
        }
        return Json{{"summary", {{"name", name}}},
                    {"stream", xdebug_waveform::stream_config_json(config)}};
    }
};

}  // namespace

std::unique_ptr<EngineActionHandler> make_stream_config_get_handler() {
    return std::unique_ptr<EngineActionHandler>(new StreamConfigGetHandler);
}

}  // namespace xdebug_design
