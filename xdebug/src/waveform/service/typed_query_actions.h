#pragma once

#include "json.hpp"

#include <string>

namespace xdebug_waveform {

using TypedWaveformAction = nlohmann::ordered_json (*)(
    const nlohmann::ordered_json& args,
    std::string& error);

nlohmann::ordered_json ai_expr_eval_at(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_window_verify(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_signal_changes(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_signal_stability(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_signal_xz_verify(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_signal_statistics(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_counter_statistics(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_signal_sampled_pulse_inspect(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_signal_anomaly_inspect(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_protocol_handshake_inspect(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_apb_transfer_window(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_axi_transactions_window(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_axi_latency_outlier(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_axi_outstanding_timeline(
    const nlohmann::ordered_json& args, std::string& error);
nlohmann::ordered_json ai_axi_channel_stall(
    const nlohmann::ordered_json& args, std::string& error);

}  // namespace xdebug_waveform
