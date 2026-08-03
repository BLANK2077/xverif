#include "apb_manager.h"

#include "../common/xdebug_waveform_paths.h"

#include <set>

namespace xdebug_waveform {
namespace {

StoreJson apb_to_json(const ApbConfig& config) {
    StoreJson value = {
        {"name", config.name},
        {"paddr", config.paddr},
        {"pwdata", config.pwdata},
        {"prdata", config.prdata},
        {"pwrite", config.pwrite},
        {"penable", config.penable},
        {"psel", config.psel},
        {"clock", config.clock_sample.clock},
        {"reset", reset_config_json(config.reset)},
        {"edge", clock_edge_kind_text(config.clock_sample.edge)}
    };
    if (!config.pready.empty()) value["pready"] = config.pready;
    if (!config.pslverr.empty()) value["pslverr"] = config.pslverr;
    if (config.clock_sample.edge != ClockEdgeKind::Negedge) {
        value["sample_point"] =
            clock_sample_point_text(config.clock_sample.sample_point);
    }
    return value;
}

bool json_to_apb(
    const StoreJson& value,
    ApbConfig& config,
    std::string& error) {
    if (!value.is_object()) {
        error = "APB config must be an object";
        return false;
    }
    static const std::set<std::string> base_fields = {
        "name", "paddr", "pwdata", "prdata", "pwrite", "penable",
        "psel", "clock", "reset", "edge"
    };
    const bool has_pready = value.contains("pready");
    const bool has_pslverr = value.contains("pslverr");
    const bool has_sample_point = value.contains("sample_point");
    if (value.size() !=
        base_fields.size() +
            (has_pready ? 1U : 0U) +
            (has_pslverr ? 1U : 0U) +
            (has_sample_point ? 1U : 0U)) {
        error = "APB config contains unknown or missing fields";
        return false;
    }
    for (const auto& field : base_fields) {
        if (!value.contains(field)) {
            error = "APB config is missing field: " + field;
            return false;
        }
    }
    for (const char* field : {
             "name", "paddr", "pwdata", "prdata", "pwrite", "penable",
             "psel", "clock", "edge"}) {
        if (!value[field].is_string() ||
            value[field].get<std::string>().empty()) {
            error = std::string("APB config field must be a non-empty string: ") +
                    field;
            return false;
        }
    }
    for (const char* field : {"pready", "pslverr"}) {
        if (value.contains(field) &&
            (!value[field].is_string() ||
             value[field].get<std::string>().empty())) {
            error =
                std::string(
                    "APB optional config field must be a non-empty string: ") +
                field;
            return false;
        }
    }

    config.name = value["name"].get<std::string>();
    config.paddr = value["paddr"].get<std::string>();
    config.pwdata = value["pwdata"].get<std::string>();
    config.prdata = value["prdata"].get<std::string>();
    config.pwrite = value["pwrite"].get<std::string>();
    config.penable = value["penable"].get<std::string>();
    config.psel = value["psel"].get<std::string>();
    config.pready =
        has_pready ? value["pready"].get<std::string>() : std::string();
    config.pslverr =
        has_pslverr ? value["pslverr"].get<std::string>() : std::string();
    config.clock_sample.clock = value["clock"].get<std::string>();
    std::string parse_error;
    if (!parse_reset_config(value["reset"], config.reset, parse_error)) {
        error = "APB reset is invalid: " + parse_error;
        return false;
    }
    if (!parse_clock_edge_kind(
            value["edge"].get<std::string>(),
            config.clock_sample.edge,
            parse_error)) {
        error = "APB edge is invalid: " + parse_error;
        return false;
    }
    if (config.clock_sample.edge == ClockEdgeKind::Negedge) {
        if (has_sample_point) {
            error = "APB negedge config must not contain sample_point";
            return false;
        }
        config.clock_sample.has_sample_point = false;
    } else {
        if (!has_sample_point || !value["sample_point"].is_string()) {
            error = "APB non-negedge config requires sample_point";
            return false;
        }
        config.clock_sample.has_sample_point = true;
        if (!parse_clock_sample_point_kind(
                value["sample_point"].get<std::string>(),
                config.clock_sample.sample_point,
                parse_error)) {
            error = "APB sample_point is invalid: " + parse_error;
            return false;
        }
    }
    error.clear();
    return true;
}

StoreResult parse_configs(
    const StoreJson& items,
    std::vector<ApbConfig>& configs) {
    configs.clear();
    std::set<std::string> names;
    for (size_t index = 0; index < items.size(); ++index) {
        ApbConfig config;
        std::string error;
        if (!json_to_apb(items[index], config, error)) {
            return store_invalid(
                "APB configs[" + std::to_string(index) + "]: " + error);
        }
        if (!names.insert(config.name).second) {
            return store_invalid("duplicate APB config name: " + config.name);
        }
        configs.push_back(std::move(config));
    }
    return {};
}

StoreJson serialize_configs(const std::vector<ApbConfig>& configs) {
    StoreJson items = StoreJson::array();
    for (const auto& config : configs) items.push_back(apb_to_json(config));
    return items;
}

VersionedJsonStore store_for(const std::string& session_id) {
    return VersionedJsonStore(
        xdebug_waveform_apb_path(session_id), "configs");
}

} // namespace

StoreResult ApbManager::load_session(
    const std::string& session_id,
    std::vector<ApbConfig>& configs) {
    StoreJson items;
    StoreResult loaded = store_for(session_id).load(items);
    if (!loaded.ok()) return loaded;
    return parse_configs(items, configs);
}

StoreResult ApbManager::create_apb(
    const std::string& session_id,
    const ApbConfig& config) {
    ApbConfig validated;
    std::string validation_error;
    if (!json_to_apb(apb_to_json(config), validated, validation_error)) {
        return store_invalid(
            "cannot persist invalid APB config: " + validation_error);
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return {
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot create APB session directory"
        };
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<ApbConfig> configs;
        StoreResult parsed = parse_configs(items, configs);
        if (!parsed.ok()) return parsed;
        for (const auto& existing : configs) {
            if (existing.name == config.name)
                return store_conflict("APB config already exists: " + config.name);
        }
        configs.push_back(config);
        items = serialize_configs(configs);
        return StoreResult{};
    });
}

StoreResult ApbManager::delete_apb(
    const std::string& session_id,
    const std::string& name) {
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<ApbConfig> configs;
        StoreResult parsed = parse_configs(items, configs);
        if (!parsed.ok()) return parsed;
        std::vector<ApbConfig> kept;
        bool found = false;
        for (const auto& config : configs) {
            if (config.name == name) found = true;
            else kept.push_back(config);
        }
        if (!found) return store_not_found("APB config not found: " + name);
        items = serialize_configs(kept);
        return StoreResult{};
    });
}

StoreResult ApbManager::get_apb(
    const std::string& session_id,
    const std::string& name,
    ApbConfig& config) {
    std::vector<ApbConfig> configs;
    StoreResult loaded = load_session(session_id, configs);
    if (!loaded.ok()) return loaded;
    for (const auto& current : configs) {
        if (current.name != name) continue;
        config = current;
        return {};
    }
    return store_not_found("APB config not found: " + name);
}

StoreResult ApbManager::get_latest_apb(
    const std::string& session_id,
    std::string& name) {
    std::vector<ApbConfig> configs;
    StoreResult loaded = load_session(session_id, configs);
    if (!loaded.ok()) return loaded;
    if (configs.empty()) return store_not_found("no APB configs are loaded");
    name = configs.back().name;
    return {};
}

StoreResult ApbManager::list_all(
    const std::string& session_id,
    std::vector<ApbConfig>& configs) {
    return load_session(session_id, configs);
}

} // namespace xdebug_waveform
