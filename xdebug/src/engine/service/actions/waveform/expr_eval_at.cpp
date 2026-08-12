#include "typed_waveform_action_adapter.h"

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_expr_eval_at_handler() {
    return make_typed_waveform_action_handler(
        "expr.eval_at",
        xdebug_waveform::ai_expr_eval_at,
        {TypedWaveformCacheError::None, false, "args.expr"});
}

}  // namespace xdebug_design
