#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_axi_latency_outlier_handler() {
    return make_typed_waveform_action_handler(
        "axi.latency_outlier",
        xdebug_waveform::ai_axi_latency_outlier,
        {TypedWaveformCacheError::Axi, true, nullptr});
}

}  // namespace xdebug_design
