#include "service/engine_action_registry.h"

#include <memory>

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_trace_active_driver_handler();
std::unique_ptr<EngineActionHandler> make_trace_active_driver_chain_handler();
std::unique_ptr<EngineActionHandler> make_trace_x_origin_handler();

void register_combined_handlers(EngineActionRegistry& r) {
    r.add(make_trace_active_driver_handler());
    r.add(make_trace_active_driver_chain_handler());
    r.add(make_trace_x_origin_handler());
}

} // namespace xdebug_design
