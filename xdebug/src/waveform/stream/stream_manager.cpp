#include "stream_manager.h"

#include "../common/xdebug_waveform_paths.h"

#include <fstream>
#include <map>
#include <set>
#include <utility>

namespace xdebug_waveform {

namespace {

StoreJson serialize_streams(
    const std::vector<StreamConfig>& configs) {
    StoreJson items = StoreJson::array();
    for (const auto& config : configs) {
        items.push_back(stream_config_json(config));
    }
    return items;
}

StoreResult parse_stored_streams(
    const StoreJson& items,
    std::vector<StreamConfig>& configs) {
    configs.clear();
    std::set<std::string> names;
    for (size_t index = 0; index < items.size(); ++index) {
        StreamConfig config;
        std::string error;
        if (!parse_stream_config_json(items[index], config, error)) {
            return store_invalid(
                "streams[" + std::to_string(index) + "]: " + error);
        }
        if (stream_config_json(config) != items[index]) {
            return store_invalid(
                "streams[" + std::to_string(index) +
                "] is not in canonical stream config form");
        }
        if (!names.insert(config.name).second) {
            return store_invalid(
                "duplicate stream config name: " + config.name);
        }
        configs.push_back(std::move(config));
    }
    return {};
}

VersionedJsonStore store_for(const std::string& session_id) {
    return VersionedJsonStore(
        xdebug_waveform_streams_path(session_id),
        "streams");
}

StoreResult session_dir_error() {
    return {
        StoreStatus::IoError,
        "CONFIG_STORE_IO_ERROR",
        "cannot create stream config session directory"
    };
}

} // namespace

bool load_stream_config_arg(const Json& args, Json& root, std::string& error) {
    if (args.contains("config")) {
        if (!args["config"].is_object()) {
            error = "args.config must be an object";
            return false;
        }
        root = args["config"];
        return true;
    }
    std::string path = args.value("config_path", std::string());
    if (path.empty()) {
        error = "stream.config.load requires args.config or args.config_path";
        return false;
    }
    std::ifstream input(path.c_str());
    if (!input) {
        error = "config file not found: " + path;
        return false;
    }
    try {
        input >> root;
    } catch (const std::exception& e) {
        error = std::string("invalid JSON in stream config file: ") + e.what();
        return false;
    }
    if (!root.is_object()) {
        error = "stream config file must contain a JSON object";
        return false;
    }
    return true;
}

bool parse_stream_config_list(const Json& root, std::vector<StreamConfig>& streams, std::string& error) {
    streams.clear();
    if (!root.is_object() || root.size() != 1 ||
        !root.contains("streams")) {
        error = "stream config document must contain exactly one root field: streams";
        return false;
    }
    Json arr = root["streams"];
    if (!arr.is_array() || arr.empty()) {
        error = "stream config streams must be a non-empty array";
        return false;
    }
    std::set<std::string> names;
    for (const auto& item : arr) {
        StreamConfig config;
        if (!parse_stream_config_json(item, config, error)) return false;
        if (!names.insert(config.name).second) {
            error = "duplicate stream name in config: " + config.name;
            return false;
        }
        streams.push_back(config);
    }
    return true;
}

StoreResult StreamManager::load_session(
    const std::string& session_id,
    std::vector<StreamConfig>& configs) {
    StoreJson items;
    StoreResult loaded = store_for(session_id).load(items);
    if (!loaded.ok()) return loaded;
    return parse_stored_streams(items, configs);
}

StoreResult StreamManager::load_configs(
    const std::string& session_id,
    const std::vector<StreamConfig>& incoming,
    const std::string& mode,
    std::vector<StreamConfigChange>* changes) {
    if (changes) changes->clear();
    if (mode != "replace" && mode != "append") {
        return {
            StoreStatus::Invalid,
            "INVALID_ARGUMENT",
            "stream.config.load mode must be replace or append"
        };
    }

    std::vector<StreamConfig> validated_incoming;
    StoreResult incoming_result =
        parse_stored_streams(
            serialize_streams(incoming),
            validated_incoming);
    if (!incoming_result.ok()) {
        incoming_result.message =
            "cannot persist invalid stream config: " +
            incoming_result.message;
        return incoming_result;
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return session_dir_error();
    }

    std::vector<StreamConfigChange> committed_changes;
    StoreResult updated =
        store_for(session_id).update([&](StoreJson& items) {
            std::vector<StreamConfig> current;
            StoreResult parsed =
                parse_stored_streams(items, current);
            if (!parsed.ok()) return parsed;

            std::vector<StreamConfig> out;
            if (mode == "append") {
                out = current;
                std::set<std::string> names;
                for (const auto& item : current) {
                    names.insert(item.name);
                }
                for (const auto& item : validated_incoming) {
                    if (!names.insert(item.name).second) {
                        return store_conflict(
                            "stream config already exists: " +
                            item.name);
                    }
                    out.push_back(item);
                }
            } else {
                std::map<std::string, StreamConfig> by_name;
                for (const auto& item : current) {
                    by_name[item.name] = item;
                }
                for (const auto& item : validated_incoming) {
                    by_name[item.name] = item;
                }
                for (const auto& entry : by_name) {
                    out.push_back(entry.second);
                }
            }

            std::map<std::string, StreamConfig> old_by_name;
            for (const auto& item : current) {
                old_by_name[item.name] = item;
            }
            std::vector<StreamConfigChange> pending;
            for (const auto& item : out) {
                StreamConfigChange change;
                change.name = item.name;
                auto old = old_by_name.find(item.name);
                if (old != old_by_name.end()) {
                    change.old_semantic_fingerprint =
                        stream_config_semantic_fingerprint(
                            old->second);
                }
                change.new_semantic_fingerprint =
                    stream_config_semantic_fingerprint(item);
                pending.push_back(std::move(change));
            }
            items = serialize_streams(out);
            committed_changes = std::move(pending);
            return StoreResult{};
        });
    if (updated.ok() && changes) {
        *changes = std::move(committed_changes);
    }
    return updated;
}

StoreResult StreamManager::get_stream(
    const std::string& session_id,
    const std::string& name,
    StreamConfig& config) {
    std::vector<StreamConfig> configs;
    StoreResult loaded = load_session(session_id, configs);
    if (!loaded.ok()) return loaded;
    for (const auto& item : configs) {
        if (item.name != name) continue;
        config = item;
        return {};
    }
    return store_not_found(
        "stream config not found: " + name);
}

StoreResult StreamManager::list_streams(
    const std::string& session_id,
    std::vector<StreamConfig>& configs) {
    return load_session(session_id, configs);
}

} // namespace xdebug_waveform
