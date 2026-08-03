#include "service/engine_action_registry.h"

#include <memory>

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_trace_driver_handler();
std::unique_ptr<EngineActionHandler> make_trace_load_handler();
std::unique_ptr<EngineActionHandler> make_signal_resolve_handler();
std::unique_ptr<EngineActionHandler> make_signal_canonicalize_handler();
std::unique_ptr<EngineActionHandler> make_expr_normalize_handler();

void register_design_handlers(EngineActionRegistry& r) {
    r.add(make_trace_driver_handler());
    r.add(make_trace_load_handler());
    r.add(make_signal_resolve_handler());
    r.add(make_signal_canonicalize_handler());
    r.add(make_expr_normalize_handler());
}

} // namespace xdebug_design
