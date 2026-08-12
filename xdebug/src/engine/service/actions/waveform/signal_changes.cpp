#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_signal_changes_handler() {
    return make_typed_waveform_action_handler(
        "signal.changes", xdebug_waveform::ai_signal_changes);
}

}  // namespace xdebug_design
