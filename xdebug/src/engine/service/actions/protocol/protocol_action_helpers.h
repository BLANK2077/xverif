#pragma once

#include "service/config_store_error.h"
#include "service/engine_action_handler.h"
#include "service/engine_globals.h"
#include "waveform/apb/apb_analyzer.h"
#include "waveform/apb/apb_manager.h"
#include "waveform/axi/axi_analyzer.h"
#include "waveform/axi/axi_manager.h"

#include <utility>

namespace xdebug_design {

enum class ProtocolEnsureStatus {
    Ok,
    ConfigNotFound,
    StoreError,
    AnalysisError
};

struct ProtocolEnsureResult {
    ProtocolEnsureStatus status = ProtocolEnsureStatus::Ok;
    xdebug_waveform::StoreResult store;
    std::string message;

    ProtocolEnsureResult() = default;
    ProtocolEnsureResult(
        ProtocolEnsureStatus result_status,
        xdebug_waveform::StoreResult store_result,
        std::string result_message)
        : status(result_status),
          store(std::move(store_result)),
          message(std::move(result_message)) {}

    bool ok() const { return status == ProtocolEnsureStatus::Ok; }
};

inline bool analyze_apb_config(const std::string& name,
                               const xdebug_waveform::ApbConfig& config,
                               std::string& error) {
    if (xdebug_waveform::g_apb_analyzer.analyze(
            name, xdebug_waveform::g_fsdb_file, config)) {
        return true;
    }
    const auto& cache_error =
        xdebug_waveform::g_apb_analyzer.last_cache_error();
    error = cache_error.message.empty()
        ? "Failed to analyze APB: " + name : cache_error.message;
    return false;
}

inline ProtocolEnsureResult ensure_apb_analyzed(
    const std::string& name,
    xdebug_waveform::ApbConfig& config) {
    xdebug_waveform::ApbManager manager;
    xdebug_waveform::StoreResult loaded =
        manager.get_apb(xdebug_waveform::g_session_id, name, config);
    if (!loaded.ok()) {
        return {
            loaded.status == xdebug_waveform::StoreStatus::NotFound
                ? ProtocolEnsureStatus::ConfigNotFound
                : ProtocolEnsureStatus::StoreError,
            loaded,
            loaded.message
        };
    }
    std::string error;
    if (!analyze_apb_config(name, config, error)) {
        return {
            ProtocolEnsureStatus::AnalysisError,
            {},
            error
        };
    }
    return {};
}

inline bool analyze_axi_config(const std::string& name,
                               const xdebug_waveform::AxiConfig& config,
                               std::string& error) {
    if (xdebug_waveform::g_axi_analyzer.analyze(
            name, xdebug_waveform::g_fsdb_file, config)) {
        return true;
    }
    const auto& cache_error =
        xdebug_waveform::g_axi_analyzer.last_cache_error();
    error = cache_error.message.empty()
        ? "Failed to analyze AXI: " + name : cache_error.message;
    return false;
}

inline ProtocolEnsureResult ensure_axi_analyzed(
    const std::string& name,
    xdebug_waveform::AxiConfig& config) {
    xdebug_waveform::AxiManager manager;
    xdebug_waveform::StoreResult loaded =
        manager.get_axi(xdebug_waveform::g_session_id, name, config);
    if (!loaded.ok()) {
        return {
            loaded.status == xdebug_waveform::StoreStatus::NotFound
                ? ProtocolEnsureStatus::ConfigNotFound
                : ProtocolEnsureStatus::StoreError,
            loaded,
            loaded.message
        };
    }
    std::string error;
    if (!analyze_axi_config(name, config, error)) {
        return {
            ProtocolEnsureStatus::AnalysisError,
            {},
            error
        };
    }
    return {};
}

inline Json apb_config_json(const xdebug_waveform::ApbConfig& cfg) {
    Json out = {{"name", cfg.name}, {"sampling_mode", "clock_edge"},
                {"clock", cfg.clock_sample.clock},
                {"edge", xdebug_waveform::clock_edge_kind_text(cfg.clock_sample.edge)},
                {"reset", xdebug_waveform::reset_config_json(cfg.reset)}, {"paddr", cfg.paddr}, {"psel", cfg.psel},
                {"penable", cfg.penable}, {"pwrite", cfg.pwrite},
                {"pwdata", cfg.pwdata}, {"prdata", cfg.prdata}};
    if (cfg.clock_sample.edge != xdebug_waveform::ClockEdgeKind::Negedge)
        out["sample_point"] = xdebug_waveform::clock_sample_point_text(cfg.clock_sample.sample_point);
    if (!cfg.pready.empty()) out["pready"] = cfg.pready;
    if (!cfg.pslverr.empty()) out["pslverr"] = cfg.pslverr;
    return out;
}

inline Json axi_config_json(const xdebug_waveform::AxiConfig& cfg) {
    Json out = {{"name", cfg.name}, {"sampling_mode", "clock_edge"},
                {"clock", cfg.clock_sample.clock},
                {"edge", xdebug_waveform::clock_edge_kind_text(cfg.clock_sample.edge)},
                {"reset", xdebug_waveform::reset_config_json(cfg.reset)}};
    if (cfg.clock_sample.edge != xdebug_waveform::ClockEdgeKind::Negedge)
        out["sample_point"] = xdebug_waveform::clock_sample_point_text(cfg.clock_sample.sample_point);
    out["channels"] = {
        {"aw", {{"addr", cfg.awaddr}, {"id", cfg.awid}, {"len", cfg.awlen},
                {"size", cfg.awsize}, {"burst", cfg.awburst},
                {"valid", cfg.awvalid}, {"ready", cfg.awready}}},
        {"w", {{"data", cfg.wdata}, {"strb", cfg.wstrb}, {"last", cfg.wlast},
               {"valid", cfg.wvalid}, {"ready", cfg.wready}}},
        {"b", {{"id", cfg.bid}, {"resp", cfg.bresp},
               {"valid", cfg.bvalid}, {"ready", cfg.bready}}},
        {"ar", {{"addr", cfg.araddr}, {"id", cfg.arid}, {"len", cfg.arlen},
                {"size", cfg.arsize}, {"burst", cfg.arburst},
                {"valid", cfg.arvalid}, {"ready", cfg.arready}}},
        {"r", {{"id", cfg.rid}, {"data", cfg.rdata}, {"resp", cfg.rresp},
               {"last", cfg.rlast}, {"valid", cfg.rvalid}, {"ready", cfg.rready}}}
    };
    return out;
}

inline Json protocol_example_args(const std::string& action) {
    if (action == "axi.config.load") {
        return Json{{"name", "axi0"},
                    {"config", {{"clock", "top.u.clk"},
                                {"reset", {{"signal", "top.u.rst_n"}, {"polarity", "active_low"}}},
                                {"awvalid", "top.u.awvalid"},
                                {"awready", "top.u.awready"},
                                {"awaddr", "top.u.awaddr"},
                                {"awid", "top.u.awid"},
                                {"awlen", "top.u.awlen"},
                                {"awsize", "top.u.awsize"},
                                {"awburst", "top.u.awburst"},
                                {"wvalid", "top.u.wvalid"},
                                {"wready", "top.u.wready"},
                                {"wdata", "top.u.wdata"},
                                {"wstrb", "top.u.wstrb"},
                                {"wlast", "top.u.wlast"},
                                {"bvalid", "top.u.bvalid"},
                                {"bready", "top.u.bready"},
                                {"bid", "top.u.bid"},
                                {"bresp", "top.u.bresp"},
                                {"arvalid", "top.u.arvalid"},
                                {"arready", "top.u.arready"},
                                {"araddr", "top.u.araddr"},
                                {"arid", "top.u.arid"},
                                {"arlen", "top.u.arlen"},
                                {"arsize", "top.u.arsize"},
                                {"arburst", "top.u.arburst"},
                                {"rvalid", "top.u.rvalid"},
                                {"rready", "top.u.rready"},
                                {"rdata", "top.u.rdata"},
                                {"rid", "top.u.rid"},
                                {"rresp", "top.u.rresp"},
                                {"rlast", "top.u.rlast"}}}};
    }
    if (action == "apb.config.load") {
        return Json{{"name", "apb0"},
                    {"config", {{"clock", "top.u.clk"},
                                {"reset", {{"signal", "top.u.rst_n"}, {"polarity", "active_low"}}},
                                {"paddr", "top.u.paddr"},
                                {"psel", "top.u.psel"},
                                {"penable", "top.u.penable"},
                                {"pready", "top.u.pready"},
                                {"pslverr", "top.u.pslverr"},
                                {"pwrite", "top.u.pwrite"},
                                {"pwdata", "top.u.pwdata"},
                                {"prdata", "top.u.prdata"}}}};
    }
    if (action == "axi.export" || action == "apb.export") {
        return Json{{"name", action == "axi.export" ? "axi0" : "apb0"},
                    {"time_range", {{"begin", "0ns"}, {"end", "1000ns"}}},
                    {"output", {{"path", "xdebug-axi-export"}, {"file_format", "tsv"}}}};
    }
    if (action == "axi.transaction.cursor" || action == "apb.transaction.cursor") {
        return Json{{"name", action.rfind("axi.", 0) == 0 ? "axi0" : "apb0"},
                    {"op", "begin"},
                    {"direction", "all"}};
    }
    if (action == "axi.query" || action == "apb.query") {
        return Json{{"name", action.rfind("axi.", 0) == 0 ? "axi0" : "apb0"},
                    {"direction", action.rfind("axi.", 0) == 0 ? "write" : "all"},
                    {"query", {{"line_limit", 8}}}};
    }
    if (action == "axi.analysis") {
        return Json{{"name", "axi0"}, {"analysis", "latency"}, {"direction", "all"}};
    }
    return Json{{"name", action.rfind("axi.", 0) == 0 ? "axi0" : "apb0"}};
}

inline Json protocol_action_example(const std::string& action) {
    return Json{{"api_version", "xdebug.v1"},
                {"action", action},
                {"target", {{"session_id", "case_a"}}},
                {"args", protocol_example_args(action)}};
}

inline Json protocol_missing_name_error(const std::string& action,
                                        const std::string& protocol) {
    return make_handler_error(
        "MISSING_FIELD",
        "args.name is required",
        {{"invalid_arg", "args.name"},
         {"expected", "name of a loaded " + protocol + " config"},
         {"correct_example", protocol_action_example(action)},
         {"example_note", "Example only; load a config first or use an existing config name from " + protocol + ".config.list."},
         {"next_actions", Json::array({"Call " + protocol + ".config.list to inspect loaded configs.",
                                        "Call " + protocol + ".config.load before query/cursor/analysis/export."})}});
}

inline Json protocol_config_not_found_error(const std::string& action,
                                            const std::string& protocol,
                                            const std::string& name) {
    return make_handler_error(
        "CONFIG_NOT_FOUND",
        protocol + " config not found: " + name,
        {{"invalid_arg", "args.name"},
         {"expected", "name of a previously loaded " + protocol + " config"},
         {"missing_name", name},
         {"missing_resource", protocol + " config"},
         {"correct_example", protocol_action_example(action)},
         {"example_note", "Example only; choose an existing config name or load this config before using it."},
         {"next_actions", Json::array({"Call " + protocol + ".config.list to inspect loaded configs.",
                                        "Call " + protocol + ".config.load before this action."})}});
}

inline Json protocol_invalid_arg_error(const std::string& action,
                                       const std::string& invalid_arg,
                                       const std::string& message,
                                       const std::string& expected,
                                       const Json& extra = Json::object()) {
    Json details = {{"invalid_arg", invalid_arg},
                    {"expected", expected},
                    {"correct_example", protocol_action_example(action)},
                    {"example_note", "Example only; replace placeholders with active signal paths, names, and time values."}};
    for (auto it = extra.begin(); it != extra.end(); ++it) details[it.key()] = it.value();
    return make_handler_error("INVALID_ARGUMENT", message, details);
}

inline Json protocol_invalid_enum_error(const std::string& action,
                                        const std::string& invalid_arg,
                                        const std::string& message,
                                        const Json& available_values) {
    return make_handler_error(
        "INVALID_ENUM",
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", "one of available_values"},
         {"available_values", available_values},
         {"correct_example", protocol_action_example(action)},
         {"example_note", "Example only; choose a value from available_values."}});
}

inline Json protocol_time_error(const std::string& action,
                                const std::string& invalid_arg,
                                const std::string& message) {
    return make_handler_error(
        "INVALID_TIME",
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", "time strings in args.time_range.begin/end such as 0ns and 100ns"},
         {"correct_example", protocol_action_example(action)}});
}

inline Json protocol_analyze_error(const std::string& action,
                                   const std::string& protocol,
                                   const std::string& name,
                                   const std::string& message) {
    return make_handler_error(
        "ACTION_FAILED",
        message,
        {{"cause_code", "ANALYZE_FAILED"},
         {"invalid_arg", "args.name"},
         {"expected", "an analyzable " + protocol + " config in the active waveform session"},
         {"missing_name", name},
         {"correct_example", protocol_action_example(action)},
         {"next_actions", Json::array({"Confirm the config name with " + protocol + ".config.list.",
                                        "Validate signal paths in the loaded config against the active FSDB."})}});
}

} // namespace xdebug_design
