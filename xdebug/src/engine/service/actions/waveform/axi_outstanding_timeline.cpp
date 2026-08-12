#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_axi_outstanding_timeline_handler() {
    return make_typed_waveform_action_handler(
        "axi.outstanding_timeline",
        xdebug_waveform::ai_axi_outstanding_timeline,
        {TypedWaveformCacheError::Axi, true, nullptr});
}

}  // namespace xdebug_design
