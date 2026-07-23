#include "service/engine_action_handler.h"
#include "service/engine_action_registry.h"

#include "waveform/server/server_internal.h"

#include <memory>
#include <string>

namespace xdebug_design {
namespace {

class SignalXzVerifyHandler : public EngineActionHandler {
public:
    const char* action_name() const override { return "signal.xz_verify"; }
    bool needs_design() const override { return false; }
    bool needs_waveform() const override { return true; }

    Json run(const Json& request, EngineActionContext&) const override {
        std::string error;
        Json result = xdebug_waveform::ai_dispatch_query(request, error);
        if (!error.empty()) return make_handler_error_from_message(error);
        return result;
    }
};

} // namespace

std::unique_ptr<EngineActionHandler> make_signal_xz_verify_handler() {
    return std::unique_ptr<EngineActionHandler>(new SignalXzVerifyHandler);
}

} // namespace xdebug_design
