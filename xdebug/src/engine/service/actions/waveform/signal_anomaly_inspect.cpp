#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_signal_anomaly_inspect_handler() {
    return make_typed_waveform_action_handler(
        "signal.anomaly.inspect",
        xdebug_waveform::ai_signal_anomaly_inspect,
        {TypedWaveformCacheError::None, true, nullptr});
}

}  // namespace xdebug_design
