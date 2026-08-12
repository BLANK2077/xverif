#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler>
make_protocol_handshake_inspect_handler() {
    return make_typed_waveform_action_handler(
        "protocol.handshake.inspect",
        xdebug_waveform::ai_protocol_handshake_inspect,
        {TypedWaveformCacheError::None, true, nullptr});
}

}  // namespace xdebug_design
