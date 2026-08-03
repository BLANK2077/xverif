#include "service/engine_action_registry.h"

#include <memory>

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_apb_config_load_handler();
std::unique_ptr<EngineActionHandler> make_apb_config_list_handler();
std::unique_ptr<EngineActionHandler> make_apb_query_handler();
std::unique_ptr<EngineActionHandler> make_apb_statistics_handler();
std::unique_ptr<EngineActionHandler> make_apb_transaction_cursor_handler();
std::unique_ptr<EngineActionHandler> make_axi_config_load_handler();
std::unique_ptr<EngineActionHandler> make_axi_config_list_handler();
std::unique_ptr<EngineActionHandler> make_axi_query_handler();
std::unique_ptr<EngineActionHandler> make_axi_statistics_handler();
std::unique_ptr<EngineActionHandler> make_axi_transaction_cursor_handler();
std::unique_ptr<EngineActionHandler> make_axi_analysis_handler();
std::unique_ptr<EngineActionHandler> make_axi_export_handler();

void register_protocol_handlers(EngineActionRegistry& r) {
    r.add(make_apb_config_load_handler());
    r.add(make_apb_config_list_handler());
    r.add(make_apb_query_handler());
    r.add(make_apb_statistics_handler());
    r.add(make_apb_transaction_cursor_handler());
    r.add(make_axi_config_load_handler());
    r.add(make_axi_config_list_handler());
    r.add(make_axi_query_handler());
    r.add(make_axi_statistics_handler());
    r.add(make_axi_transaction_cursor_handler());
    r.add(make_axi_analysis_handler());
    r.add(make_axi_export_handler());
}

} // namespace xdebug_design
