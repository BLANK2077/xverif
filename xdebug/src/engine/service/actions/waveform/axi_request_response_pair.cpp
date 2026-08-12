#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_axi_request_response_pair_handler() {
    return make_typed_waveform_action_handler(
        "axi.request_response_pair",
        xdebug_waveform::ai_axi_transactions_window,
        {TypedWaveformCacheError::Axi, true, nullptr});
}

}  // namespace xdebug_design
