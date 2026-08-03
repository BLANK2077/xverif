#include "service/engine_action_registry.h"

#include <memory>

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_stream_config_load_handler();
std::unique_ptr<EngineActionHandler> make_stream_config_list_handler();
std::unique_ptr<EngineActionHandler> make_stream_config_get_handler();
std::unique_ptr<EngineActionHandler> make_stream_describe_handler();
std::unique_ptr<EngineActionHandler> make_stream_validate_handler();
std::unique_ptr<EngineActionHandler> make_stream_query_handler();
std::unique_ptr<EngineActionHandler> make_stream_export_handler();

void register_stream_handlers(EngineActionRegistry& r) {
    r.add(make_stream_config_load_handler());
    r.add(make_stream_config_list_handler());
    r.add(make_stream_config_get_handler());
    r.add(make_stream_describe_handler());
    r.add(make_stream_validate_handler());
    r.add(make_stream_query_handler());
    r.add(make_stream_export_handler());
}

} // namespace xdebug_design
