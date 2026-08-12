#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_signal_sampled_pulse_inspect_handler() {
    return make_typed_waveform_action_handler(
        "signal.sampled_pulse.inspect",
        xdebug_waveform::ai_signal_sampled_pulse_inspect);
}

}  // namespace xdebug_design
