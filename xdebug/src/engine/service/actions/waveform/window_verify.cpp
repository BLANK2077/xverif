#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_window_verify_handler() {
    return make_typed_waveform_action_handler(
        "window.verify",
        xdebug_waveform::ai_window_verify,
        {TypedWaveformCacheError::None, false, "args.conditions[].expr"});
}

}  // namespace xdebug_design
