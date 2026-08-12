#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_signal_statistics_handler() {
    return make_typed_waveform_action_handler(
        "signal.statistics",
        xdebug_waveform::ai_signal_statistics,
        {TypedWaveformCacheError::None, true, nullptr});
}

}  // namespace xdebug_design
