#include "service/engine_action_registry.h"

#include <memory>

namespace xdebug_design {

std::unique_ptr<EngineActionHandler> make_value_at_handler();
std::unique_ptr<EngineActionHandler> make_scope_list_handler();
std::unique_ptr<EngineActionHandler> make_scope_roots_handler();
std::unique_ptr<EngineActionHandler> make_list_create_handler();
std::unique_ptr<EngineActionHandler> make_list_load_handler();
std::unique_ptr<EngineActionHandler> make_list_add_handler();
std::unique_ptr<EngineActionHandler> make_list_delete_handler();
std::unique_ptr<EngineActionHandler> make_list_show_handler();
std::unique_ptr<EngineActionHandler> make_list_validate_handler();
std::unique_ptr<EngineActionHandler> make_list_first_change_handler();
std::unique_ptr<EngineActionHandler> make_list_export_handler();
std::unique_ptr<EngineActionHandler> make_nwave_rc_generate_handler();
std::unique_ptr<EngineActionHandler> make_verify_conditions_handler();
std::unique_ptr<EngineActionHandler> make_cursor_set_handler();
std::unique_ptr<EngineActionHandler> make_cursor_get_handler();
std::unique_ptr<EngineActionHandler> make_cursor_list_handler();
std::unique_ptr<EngineActionHandler> make_cursor_delete_handler();
std::unique_ptr<EngineActionHandler> make_cursor_use_handler();
std::unique_ptr<EngineActionHandler> make_signal_changes_handler();
std::unique_ptr<EngineActionHandler> make_signal_stability_handler();
std::unique_ptr<EngineActionHandler> make_signal_xz_verify_handler();
std::unique_ptr<EngineActionHandler> make_signal_statistics_handler();
std::unique_ptr<EngineActionHandler> make_counter_statistics_handler();
std::unique_ptr<EngineActionHandler> make_expr_eval_at_handler();
std::unique_ptr<EngineActionHandler> make_window_verify_handler();
std::unique_ptr<EngineActionHandler> make_signal_sampled_pulse_inspect_handler();
std::unique_ptr<EngineActionHandler> make_signal_anomaly_inspect_handler();
std::unique_ptr<EngineActionHandler> make_protocol_handshake_inspect_handler();
std::unique_ptr<EngineActionHandler> make_apb_transfer_window_handler();
std::unique_ptr<EngineActionHandler> make_axi_channel_stall_handler();
std::unique_ptr<EngineActionHandler> make_axi_outstanding_timeline_handler();
std::unique_ptr<EngineActionHandler> make_axi_request_response_pair_handler();
std::unique_ptr<EngineActionHandler> make_axi_latency_outlier_handler();
std::unique_ptr<EngineActionHandler> make_event_config_load_handler();
std::unique_ptr<EngineActionHandler> make_event_config_list_handler();
std::unique_ptr<EngineActionHandler> make_event_find_handler();
std::unique_ptr<EngineActionHandler> make_event_export_handler();

void register_waveform_handlers(EngineActionRegistry& r) {
    r.add(make_value_at_handler());
    r.add(make_scope_list_handler());
    r.add(make_scope_roots_handler());
    r.add(make_list_create_handler());
    r.add(make_list_load_handler());
    r.add(make_list_add_handler());
    r.add(make_list_delete_handler());
    r.add(make_list_show_handler());
    r.add(make_list_validate_handler());
    r.add(make_list_first_change_handler());
    r.add(make_list_export_handler());
    r.add(make_nwave_rc_generate_handler());
    r.add(make_verify_conditions_handler());
    r.add(make_cursor_set_handler());
    r.add(make_cursor_get_handler());
    r.add(make_cursor_list_handler());
    r.add(make_cursor_delete_handler());
    r.add(make_cursor_use_handler());
    r.add(make_signal_changes_handler());
    r.add(make_signal_stability_handler());
    r.add(make_signal_xz_verify_handler());
    r.add(make_signal_statistics_handler());
    r.add(make_counter_statistics_handler());
    r.add(make_expr_eval_at_handler());
    r.add(make_window_verify_handler());
    r.add(make_signal_sampled_pulse_inspect_handler());
    r.add(make_signal_anomaly_inspect_handler());
    r.add(make_protocol_handshake_inspect_handler());
    r.add(make_apb_transfer_window_handler());
    r.add(make_axi_channel_stall_handler());
    r.add(make_axi_outstanding_timeline_handler());
    r.add(make_axi_request_response_pair_handler());
    r.add(make_axi_latency_outlier_handler());
    r.add(make_event_config_load_handler());
    r.add(make_event_config_list_handler());
    r.add(make_event_find_handler());
    r.add(make_event_export_handler());
}

} // namespace xdebug_design
