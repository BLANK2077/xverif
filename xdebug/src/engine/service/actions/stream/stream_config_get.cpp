#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"
#include "service/engine_globals.h"

#include "waveform/stream/stream_manager.h"

#include <memory>

namespace xdebug_design {
namespace {

class StreamConfigGetHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "stream.config.get"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext&) const override {
        const Json args = request.value("args", Json::object());
        const std::string name = args.value("name", std::string());
        if (name.empty()) {
            return make_handler_error(
                "MISSING_FIELD", "args.name is required",
                {{"invalid_arg", "args.name"},
                 {"expected", "name returned by stream.config.list"}});
        }
        xdebug_waveform::StreamManager manager;
        xdebug_waveform::StreamConfig config;
        if (!manager.get_stream(xdebug_waveform::g_session_id, name, config)) {
            return make_handler_error(
                "CONFIG_NOT_FOUND", "stream config not found: " + name,
                {{"invalid_arg", "args.name"},
                 {"expected", "name returned by stream.config.list"},
                 {"missing_name", name},
                 {"missing_resource", "stream config"},
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
