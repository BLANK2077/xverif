#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_signal_xz_verify_handler() {
    return make_typed_waveform_action_handler(
        "signal.xz_verify", xdebug_waveform::ai_signal_xz_verify);
}

}  // namespace xdebug_design
