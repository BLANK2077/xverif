#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_apb_transfer_window_handler() {
    return make_typed_waveform_action_handler(
        "apb.transfer_window",
        xdebug_waveform::ai_apb_transfer_window,
        {TypedWaveformCacheError::Apb, true, nullptr});
}

}  // namespace xdebug_design
