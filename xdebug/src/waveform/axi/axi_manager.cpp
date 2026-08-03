#include "axi_manager.h"

#include "../common/xdebug_waveform_paths.h"

#include <set>
#include <utility>

namespace xdebug_waveform {
namespace {

const std::vector<std::string>& axi_signal_fields() {
    static const std::vector<std::string> fields = {
        "awaddr", "awid", "awlen", "awsize", "awburst",
        "awvalid", "awready",
        "wdata", "wstrb", "wlast", "wvalid", "wready",
        "bid", "bresp", "bvalid", "bready",
        "araddr", "arid", "arlen", "arsize", "arburst",
        "arvalid", "arready",
        "rid", "rdata", "rresp", "rlast", "rvalid", "rready"
    };
    return fields;
}

StoreJson axi_to_json(const AxiConfig& config) {
    StoreJson value = {
        {"name", config.name},
        {"awaddr", config.awaddr},
        {"awid", config.awid},
        {"awlen", config.awlen},
        {"awsize", config.awsize},
        {"awburst", config.awburst},
        {"awvalid", config.awvalid},
        {"awready", config.awready},
        {"wdata", config.wdata},
        {"wstrb", config.wstrb},
        {"wlast", config.wlast},
        {"wvalid", config.wvalid},
        {"wready", config.wready},
        {"bid", config.bid},
        {"bresp", config.bresp},
        {"bvalid", config.bvalid},
        {"bready", config.bready},
        {"araddr", config.araddr},
        {"arid", config.arid},
        {"arlen", config.arlen},
        {"arsize", config.arsize},
        {"arburst", config.arburst},
        {"arvalid", config.arvalid},
        {"arready", config.arready},
        {"rid", config.rid},
        {"rdata", config.rdata},
        {"rresp", config.rresp},
        {"rlast", config.rlast},
        {"rvalid", config.rvalid},
        {"rready", config.rready},
        {"clock", config.clock_sample.clock},
        {"reset", reset_config_json(config.reset)},
        {"edge", clock_edge_kind_text(config.clock_sample.edge)}
    };
    if (config.clock_sample.edge != ClockEdgeKind::Negedge) {
        value["sample_point"] =
            clock_sample_point_text(config.clock_sample.sample_point);
    }
    return value;
}

bool json_to_axi(
    const StoreJson& value,
    AxiConfig& config,
    std::string& error) {
    if (!value.is_object()) {
        error = "AXI config must be an object";
        return false;
    }

    const bool has_sample_point = value.contains("sample_point");
    const size_t expected_fields =
        1U + axi_signal_fields().size() + 3U +
        (has_sample_point ? 1U : 0U);
    if (value.size() != expected_fields) {
        error = "AXI config contains unknown or missing fields";
        return false;
    }
    for (const char* field : {"name", "clock", "reset", "edge"}) {
        if (!value.contains(field)) {
            error = std::string("AXI config is missing field: ") + field;
            return false;
        }
    }
    for (const auto& field : axi_signal_fields()) {
        if (!value.contains(field)) {
            error = "AXI config is missing field: " + field;
            return false;
        }
    }
    for (const char* field : {"name", "clock", "edge"}) {
        if (!value[field].is_string() ||
            value[field].get<std::string>().empty()) {
            error =
                std::string("AXI config field must be a non-empty string: ") +
                field;
            return false;
        }
    }
    for (const auto& field : axi_signal_fields()) {
        if (!value[field].is_string() ||
            value[field].get<std::string>().empty()) {
            error =
                "AXI config field must be a non-empty string: " + field;
            return false;
        }
    }

    config.name = value["name"].get<std::string>();
    config.awaddr = value["awaddr"].get<std::string>();
    config.awid = value["awid"].get<std::string>();
    config.awlen = value["awlen"].get<std::string>();
    config.awsize = value["awsize"].get<std::string>();
    config.awburst = value["awburst"].get<std::string>();
    config.awvalid = value["awvalid"].get<std::string>();
    config.awready = value["awready"].get<std::string>();
    config.wdata = value["wdata"].get<std::string>();
    config.wstrb = value["wstrb"].get<std::string>();
    config.wlast = value["wlast"].get<std::string>();
    config.wvalid = value["wvalid"].get<std::string>();
    config.wready = value["wready"].get<std::string>();
    config.bid = value["bid"].get<std::string>();
    config.bresp = value["bresp"].get<std::string>();
    config.bvalid = value["bvalid"].get<std::string>();
    config.bready = value["bready"].get<std::string>();
    config.araddr = value["araddr"].get<std::string>();
    config.arid = value["arid"].get<std::string>();
    config.arlen = value["arlen"].get<std::string>();
    config.arsize = value["arsize"].get<std::string>();
    config.arburst = value["arburst"].get<std::string>();
    config.arvalid = value["arvalid"].get<std::string>();
    config.arready = value["arready"].get<std::string>();
    config.rid = value["rid"].get<std::string>();
    config.rdata = value["rdata"].get<std::string>();
    config.rresp = value["rresp"].get<std::string>();
    config.rlast = value["rlast"].get<std::string>();
    config.rvalid = value["rvalid"].get<std::string>();
    config.rready = value["rready"].get<std::string>();
    config.clock_sample.clock = value["clock"].get<std::string>();

    std::string parse_error;
    if (!parse_reset_config(value["reset"], config.reset, parse_error)) {
        error = "AXI reset is invalid: " + parse_error;
        return false;
    }
    if (!parse_clock_edge_kind(
            value["edge"].get<std::string>(),
            config.clock_sample.edge,
            parse_error)) {
        error = "AXI edge is invalid: " + parse_error;
        return false;
    }
    if (config.clock_sample.edge == ClockEdgeKind::Negedge) {
        if (has_sample_point) {
            error = "AXI negedge config must not contain sample_point";
            return false;
        }
        config.clock_sample.has_sample_point = false;
    } else {
        if (!has_sample_point || !value["sample_point"].is_string()) {
            error = "AXI non-negedge config requires sample_point";
            return false;
        }
        config.clock_sample.has_sample_point = true;
        if (!parse_clock_sample_point_kind(
                value["sample_point"].get<std::string>(),
                config.clock_sample.sample_point,
                parse_error)) {
            error = "AXI sample_point is invalid: " + parse_error;
            return false;
        }
    }
    error.clear();
    return true;
}

StoreResult parse_configs(
    const StoreJson& items,
    std::vector<AxiConfig>& configs) {
    configs.clear();
    std::set<std::string> names;
    for (size_t index = 0; index < items.size(); ++index) {
        AxiConfig config;
        std::string error;
        if (!json_to_axi(items[index], config, error)) {
            return store_invalid(
                "AXI configs[" + std::to_string(index) + "]: " + error);
        }
        if (!names.insert(config.name).second) {
            return store_invalid("duplicate AXI config name: " + config.name);
        }
        configs.push_back(std::move(config));
    }
    return {};
}

StoreJson serialize_configs(const std::vector<AxiConfig>& configs) {
    StoreJson items = StoreJson::array();
    for (const auto& config : configs) items.push_back(axi_to_json(config));
    return items;
}

VersionedJsonStore store_for(const std::string& session_id) {
    return VersionedJsonStore(
        xdebug_waveform_axi_path(session_id), "configs");
}

} // namespace

StoreResult AxiManager::load_session(
    const std::string& session_id,
    std::vector<AxiConfig>& configs) {
    StoreJson items;
    StoreResult loaded = store_for(session_id).load(items);
    if (!loaded.ok()) return loaded;
    return parse_configs(items, configs);
}

StoreResult AxiManager::create_axi(
    const std::string& session_id,
    const AxiConfig& config) {
    AxiConfig validated;
    std::string validation_error;
    if (!json_to_axi(axi_to_json(config), validated, validation_error)) {
        return store_invalid(
            "cannot persist invalid AXI config: " + validation_error);
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return {
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot create AXI session directory"
        };
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<AxiConfig> configs;
        StoreResult parsed = parse_configs(items, configs);
        if (!parsed.ok()) return parsed;
        for (const auto& existing : configs) {
            if (existing.name == config.name) {
                return store_conflict(
                    "AXI config already exists: " + config.name);
            }
        }
        configs.push_back(config);
        items = serialize_configs(configs);
        return StoreResult{};
    });
}

StoreResult AxiManager::delete_axi(
    const std::string& session_id,
    const std::string& name) {
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<AxiConfig> configs;
        StoreResult parsed = parse_configs(items, configs);
        if (!parsed.ok()) return parsed;
        std::vector<AxiConfig> kept;
        bool found = false;
        for (const auto& config : configs) {
            if (config.name == name) found = true;
            else kept.push_back(config);
        }
        if (!found) return store_not_found("AXI config not found: " + name);
        items = serialize_configs(kept);
        return StoreResult{};
    });
}

StoreResult AxiManager::get_axi(
    const std::string& session_id,
    const std::string& name,
    AxiConfig& config) {
    std::vector<AxiConfig> configs;
    StoreResult loaded = load_session(session_id, configs);
    if (!loaded.ok()) return loaded;
    for (const auto& current : configs) {
        if (current.name != name) continue;
        config = current;
        return {};
    }
    return store_not_found("AXI config not found: " + name);
}

StoreResult AxiManager::get_latest_axi(
    const std::string& session_id,
    std::string& name) {
    std::vector<AxiConfig> configs;
    StoreResult loaded = load_session(session_id, configs);
    if (!loaded.ok()) return loaded;
    if (configs.empty()) return store_not_found("no AXI configs are loaded");
    name = configs.back().name;
    return {};
}

StoreResult AxiManager::list_all(
    const std::string& session_id,
    std::vector<AxiConfig>& configs) {
    return load_session(session_id, configs);
}

} // namespace xdebug_waveform
