#include "event_manager.h"

#include "../common/xdebug_waveform_paths.h"

#include <climits>
#include <set>
#include <utility>

namespace xdebug_waveform {
namespace {

StoreJson field_to_json(const EventField& field) {
    return {
        {"signal", field.signal_alias},
        {"left", field.left},
        {"right", field.right}
    };
}

StoreJson config_to_json(
    const std::string& fsdb_file,
    const EventConfig& config) {
    StoreJson value = {
        {"fsdb_file", fsdb_file},
        {"name", config.name},
        {"clock", config.clock_sample.clock},
        {"edge", clock_edge_kind_text(config.clock_sample.edge)},
        {"signals", config.signals},
        {"fields", StoreJson::object()}
    };
    if (config.has_reset) {
        value["reset"] = reset_config_json(config.reset);
    }
    if (config.clock_sample.has_sample_point) {
        value["sample_point"] =
            clock_sample_point_text(config.clock_sample.sample_point);
    }
    for (const auto& entry : config.fields) {
        value["fields"][entry.first] = field_to_json(entry.second);
    }
    return value;
}

bool parse_nonnegative_int(const StoreJson& value, int& output) {
    if (!value.is_number_integer()) return false;
    const long long parsed = value.get<long long>();
    if (parsed < 0 || parsed > INT_MAX) return false;
    output = static_cast<int>(parsed);
    return true;
}

bool json_to_config(
    const StoreJson& value,
    std::string& fsdb_file,
    EventConfig& config,
    std::string& error) {
    if (!value.is_object()) {
        error = "event config must be an object";
        return false;
    }
    const bool has_reset = value.contains("reset");
    const bool has_sample_point = value.contains("sample_point");
    if (value.size() !=
        6U + (has_reset ? 1U : 0U) +
            (has_sample_point ? 1U : 0U)) {
        error = "event config contains unknown or missing fields";
        return false;
    }
    for (const char* field :
         {"fsdb_file", "name", "clock", "edge", "signals", "fields"}) {
        if (!value.contains(field)) {
            error = std::string("event config is missing field: ") + field;
            return false;
        }
    }
    for (const char* field : {"fsdb_file", "name", "clock", "edge"}) {
        if (!value[field].is_string() ||
            value[field].get<std::string>().empty()) {
            error =
                std::string(
                    "event config field must be a non-empty string: ") +
                field;
            return false;
        }
    }
    if (!value["signals"].is_object() || value["signals"].empty()) {
        error = "event signals must be a non-empty object";
        return false;
    }
    if (!value["fields"].is_object()) {
        error = "event fields must be an object";
        return false;
    }

    fsdb_file = value["fsdb_file"].get<std::string>();
    config = EventConfig{};
    config.name = value["name"].get<std::string>();
    config.clock_sample.clock = value["clock"].get<std::string>();
    config.has_reset = has_reset;

    std::string parse_error;
    if (has_reset &&
        !parse_reset_config(value["reset"], config.reset, parse_error)) {
        error = "event reset is invalid: " + parse_error;
        return false;
    }
    if (!parse_clock_edge_kind(
            value["edge"].get<std::string>(),
            config.clock_sample.edge,
            parse_error)) {
        error = "event edge is invalid: " + parse_error;
        return false;
    }
    config.clock_sample.has_sample_point = has_sample_point;
    if (has_sample_point) {
        if (!value["sample_point"].is_string()) {
            error = "event sample_point must be before or after";
            return false;
        }
        if (!parse_clock_sample_point_kind(
                value["sample_point"].get<std::string>(),
                config.clock_sample.sample_point,
                parse_error)) {
            error = "event sample_point is invalid: " + parse_error;
            return false;
        }
    }

    for (auto iterator = value["signals"].begin();
         iterator != value["signals"].end();
         ++iterator) {
        if (iterator.key().empty() || !iterator.value().is_string() ||
            iterator.value().get<std::string>().empty()) {
            error =
                "event signal aliases and paths must be non-empty strings";
            return false;
        }
        config.signals[iterator.key()] =
            iterator.value().get<std::string>();
    }
    for (auto iterator = value["fields"].begin();
         iterator != value["fields"].end();
         ++iterator) {
        if (iterator.key().empty() || !iterator.value().is_object() ||
            iterator.value().size() != 3 ||
            !iterator.value().contains("signal") ||
            !iterator.value()["signal"].is_string() ||
            iterator.value()["signal"].get<std::string>().empty() ||
            !iterator.value().contains("left") ||
            !iterator.value().contains("right")) {
            error = "event field entries must match signal/left/right";
            return false;
        }
        EventField field;
        field.signal_alias =
            iterator.value()["signal"].get<std::string>();
        if (!parse_nonnegative_int(iterator.value()["left"], field.left) ||
            !parse_nonnegative_int(iterator.value()["right"], field.right)) {
            error = "event field left/right must be non-negative integers";
            return false;
        }
        if (config.signals.find(field.signal_alias) ==
            config.signals.end()) {
            error =
                "event field references unknown signal alias: " +
                field.signal_alias;
            return false;
        }
        config.fields[iterator.key()] = field;
    }
    error.clear();
    return true;
}

StoreResult parse_configs(
    const StoreJson& items,
    std::vector<EventConfig>& configs,
    std::vector<std::string>& fsdb_files) {
    configs.clear();
    fsdb_files.clear();
    std::set<std::pair<std::string, std::string>> identities;
    for (size_t index = 0; index < items.size(); ++index) {
        EventConfig config;
        std::string fsdb_file;
        std::string error;
        if (!json_to_config(items[index], fsdb_file, config, error)) {
            return store_invalid(
                "events[" + std::to_string(index) + "]: " + error);
        }
        if (!identities.insert({fsdb_file, config.name}).second) {
            return store_invalid(
                "duplicate event config identity: " + fsdb_file +
                "#" + config.name);
        }
        configs.push_back(std::move(config));
        fsdb_files.push_back(std::move(fsdb_file));
    }
    return {};
}

StoreJson serialize_configs(
    const std::vector<EventConfig>& configs,
    const std::vector<std::string>& fsdb_files) {
    StoreJson items = StoreJson::array();
    for (size_t index = 0; index < configs.size(); ++index) {
        items.push_back(config_to_json(fsdb_files[index], configs[index]));
    }
    return items;
}

VersionedJsonStore store_for(const std::string& session_id) {
    return VersionedJsonStore(
        xdebug_waveform_events_path(session_id), "events");
}

} // namespace

StoreResult EventManager::load_session(
    const std::string& session_id,
    std::vector<EventConfig>& configs,
    std::vector<std::string>& fsdb_files) {
    StoreJson items;
    StoreResult loaded = store_for(session_id).load(items);
    if (!loaded.ok()) return loaded;
    return parse_configs(items, configs, fsdb_files);
}

StoreResult EventManager::create_event(
    const std::string& session_id,
    const std::string& fsdb_file,
    const EventConfig& config) {
    EventConfig validated;
    std::string validated_fsdb;
    std::string validation_error;
    if (!json_to_config(
            config_to_json(fsdb_file, config),
            validated_fsdb,
            validated,
            validation_error)) {
        return store_invalid(
            "cannot persist invalid event config: " + validation_error);
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return {
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot create event session directory"
        };
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<EventConfig> configs;
        std::vector<std::string> fsdb_files;
        StoreResult parsed = parse_configs(items, configs, fsdb_files);
        if (!parsed.ok()) return parsed;

        std::vector<EventConfig> kept_configs;
        std::vector<std::string> kept_fsdbs;
        for (size_t index = 0; index < configs.size(); ++index) {
            if (fsdb_files[index] == fsdb_file &&
                configs[index].name == config.name) {
                continue;
            }
            kept_configs.push_back(configs[index]);
            kept_fsdbs.push_back(fsdb_files[index]);
        }
        kept_configs.push_back(config);
        kept_fsdbs.push_back(fsdb_file);
        items = serialize_configs(kept_configs, kept_fsdbs);
        return StoreResult{};
    });
}

StoreResult EventManager::delete_event(
    const std::string& session_id,
    const std::string& fsdb_file,
    const std::string& name) {
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<EventConfig> configs;
        std::vector<std::string> fsdb_files;
        StoreResult parsed = parse_configs(items, configs, fsdb_files);
        if (!parsed.ok()) return parsed;

        std::vector<EventConfig> kept_configs;
        std::vector<std::string> kept_fsdbs;
        bool removed = false;
        for (size_t index = 0; index < configs.size(); ++index) {
            if (fsdb_files[index] == fsdb_file &&
                configs[index].name == name) {
                removed = true;
                continue;
            }
            kept_configs.push_back(configs[index]);
            kept_fsdbs.push_back(fsdb_files[index]);
        }
        if (!removed) {
            return store_not_found("event config not found: " + name);
        }
        items = serialize_configs(kept_configs, kept_fsdbs);
        return StoreResult{};
    });
}

StoreResult EventManager::get_event(
    const std::string& session_id,
    const std::string& fsdb_file,
    const std::string& name,
    EventConfig& config) {
    std::vector<EventConfig> configs;
    std::vector<std::string> fsdb_files;
    StoreResult loaded =
        load_session(session_id, configs, fsdb_files);
    if (!loaded.ok()) return loaded;
    for (size_t index = 0; index < configs.size(); ++index) {
        if (fsdb_files[index] == fsdb_file &&
            configs[index].name == name) {
            config = configs[index];
            return {};
        }
    }
    return store_not_found("event config not found: " + name);
}

StoreResult EventManager::get_latest_event(
    const std::string& session_id,
    const std::string& fsdb_file,
    std::string& name) {
    std::vector<EventConfig> configs;
    std::vector<std::string> fsdb_files;
    StoreResult loaded =
        load_session(session_id, configs, fsdb_files);
    if (!loaded.ok()) return loaded;
    for (size_t index = configs.size(); index > 0; --index) {
        if (fsdb_files[index - 1] != fsdb_file) continue;
        name = configs[index - 1].name;
        return {};
    }
    return store_not_found(
        "no event configs are loaded for waveform: " + fsdb_file);
}

StoreResult EventManager::list_events(
    const std::string& session_id,
    const std::string& fsdb_file,
    std::vector<std::string>& names) {
    std::vector<EventConfig> configs;
    std::vector<std::string> fsdb_files;
    StoreResult loaded =
        load_session(session_id, configs, fsdb_files);
    if (!loaded.ok()) return loaded;
    names.clear();
    for (size_t index = 0; index < configs.size(); ++index) {
        if (fsdb_files[index] == fsdb_file) {
            names.push_back(configs[index].name);
        }
    }
    return {};
}

} // namespace xdebug_waveform
