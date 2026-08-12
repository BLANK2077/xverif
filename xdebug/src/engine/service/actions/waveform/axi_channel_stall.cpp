#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_axi_channel_stall_handler() {
    return make_typed_waveform_action_handler(
        "axi.channel_stall",
        xdebug_waveform::ai_axi_channel_stall,
        {TypedWaveformCacheError::Axi, true, nullptr});
}

}  // namespace xdebug_design
