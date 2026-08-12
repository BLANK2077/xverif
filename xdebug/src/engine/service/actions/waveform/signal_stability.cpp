#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_signal_stability_handler() {
    return make_typed_waveform_action_handler(
        "signal.stability", xdebug_waveform::ai_signal_stability);
}

}  // namespace xdebug_design
