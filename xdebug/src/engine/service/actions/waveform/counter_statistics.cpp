#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_counter_statistics_handler() {
    return make_typed_waveform_action_handler(
        "counter.statistics",
        xdebug_waveform::ai_counter_statistics,
        {TypedWaveformCacheError::None, true, nullptr});
}

}  // namespace xdebug_design
