#include "list_manager.h"

#include "../common/xdebug_waveform_paths.h"

#include <algorithm>
#include <functional>
#include <map>
#include <set>
#include <utility>

namespace xdebug_waveform {
namespace {

StoreJson list_to_json(const SignalList& list) {
    return {
        {"name", list.name},
        {"signals", list.signals}
    };
}

bool json_to_list(
    const StoreJson& value,
    SignalList& list,
    std::string& error) {
    if (!value.is_object() || value.size() != 2 ||
        !value.contains("name") || !value["name"].is_string() ||
        value["name"].get<std::string>().empty() ||
        !value.contains("signals") || !value["signals"].is_array()) {
        error =
            "signal list must contain only non-empty name and signals array";
        return false;
    }
    list.name = value["name"].get<std::string>();
    list.signals.clear();
    std::set<std::string> signals;
    for (size_t index = 0; index < value["signals"].size(); ++index) {
        const auto& signal = value["signals"][index];
        if (!signal.is_string() || signal.get<std::string>().empty()) {
            error =
                "signals[" + std::to_string(index) +
                "] must be a non-empty string";
            return false;
        }
        const std::string path = signal.get<std::string>();
        if (!signals.insert(path).second) {
            error = "duplicate signal path: " + path;
            return false;
        }
        list.signals.push_back(path);
    }
    error.clear();
    return true;
}

StoreResult parse_lists(
    const StoreJson& items,
    std::vector<SignalList>& lists) {
    lists.clear();
    std::set<std::string> names;
    for (size_t index = 0; index < items.size(); ++index) {
        SignalList list;
        std::string error;
        if (!json_to_list(items[index], list, error)) {
            return store_invalid(
                "lists[" + std::to_string(index) + "]: " + error);
        }
        if (!names.insert(list.name).second) {
            return store_invalid("duplicate signal list name: " + list.name);
        }
        lists.push_back(std::move(list));
    }
    return {};
}

StoreJson serialize_lists(const std::vector<SignalList>& lists) {
    StoreJson items = StoreJson::array();
    for (const auto& list : lists) items.push_back(list_to_json(list));
    return items;
}

VersionedJsonStore store_for(const std::string& session_id) {
    return VersionedJsonStore(
        xdebug_waveform_lists_path(session_id), "lists");
}

using SignalListMutation =
    std::function<StoreResult(SignalList&)>;

StoreResult update_named_list(
    const std::string& session_id,
    const std::string& list_name,
    const SignalListMutation& mutation) {
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<SignalList> lists;
        StoreResult parsed = parse_lists(items, lists);
        if (!parsed.ok()) return parsed;
        for (size_t list_index = 0;
             list_index < lists.size();
             ++list_index) {
            if (lists[list_index].name != list_name) continue;
            StoreResult mutated = mutation(lists[list_index]);
            if (!mutated.ok()) return mutated;
            SignalList modified =
                std::move(lists[list_index]);
            lists.erase(lists.begin() + list_index);
            lists.push_back(std::move(modified));
            items = serialize_lists(lists);
            return StoreResult{};
        }
        return store_not_found(
            "signal list not found: " + list_name);
    });
}

StoreResult signal_index_out_of_range(
    const std::string& list_name,
    size_t one_based_index,
    size_t signal_count) {
    return {
        StoreStatus::Invalid,
        "PRECONDITION_FAILED",
        "signal index " + std::to_string(one_based_index) +
            " is outside the one-based range for list " +
            list_name + " with " +
            std::to_string(signal_count) + " signals"
    };
}

} // namespace

StoreResult ListManager::load_session(
    const std::string& session_id,
    std::vector<SignalList>& lists) {
    StoreJson items;
    StoreResult loaded = store_for(session_id).load(items);
    if (!loaded.ok()) return loaded;
    return parse_lists(items, lists);
}

StoreResult ListManager::load_lists(
    const std::string& session_id,
    const std::vector<SignalList>& incoming,
    const std::string& mode) {
    if (mode != "replace" && mode != "append") {
        return store_invalid("list.load mode must be replace or append");
    }
    std::vector<SignalList> validated;
    StoreResult incoming_result =
        parse_lists(serialize_lists(incoming), validated);
    if (!incoming_result.ok()) {
        incoming_result.message =
            "cannot persist invalid signal list config: " +
            incoming_result.message;
        return incoming_result;
    }
    if (validated.empty()) {
        return store_invalid("list.load requires at least one list");
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return {
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot create signal-list session directory"
        };
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<SignalList> current;
        StoreResult parsed = parse_lists(items, current);
        if (!parsed.ok()) return parsed;
        if (mode == "append") {
            std::set<std::string> names;
            for (const auto& list : current) names.insert(list.name);
            for (const auto& list : validated) {
                if (!names.insert(list.name).second) {
                    return store_conflict(
                        "signal list already exists: " + list.name);
                }
                current.push_back(list);
            }
            items = serialize_lists(current);
            return StoreResult{};
        }
        std::map<std::string, SignalList> by_name;
        for (const auto& list : current) by_name[list.name] = list;
        for (const auto& list : validated) by_name[list.name] = list;
        std::vector<SignalList> replaced;
        for (const auto& entry : by_name) replaced.push_back(entry.second);
        items = serialize_lists(replaced);
        return StoreResult{};
    });
}

StoreResult ListManager::create_list(
    const std::string& session_id,
    const std::string& name,
    const std::vector<std::string>& signals) {
    if (name.empty()) {
        return store_invalid("signal list name must be non-empty");
    }
    std::set<std::string> unique_signals;
    for (const auto& signal : signals) {
        if (signal.empty()) {
            return store_invalid("signal list paths must be non-empty");
        }
        if (!unique_signals.insert(signal).second) {
            return store_conflict(
                "duplicate signal in new list " + name + ": " + signal);
        }
    }
    if (!xdebug_waveform_ensure_session_dir(session_id)) {
        return {
            StoreStatus::IoError,
            "CONFIG_STORE_IO_ERROR",
            "cannot create signal-list session directory"
        };
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<SignalList> lists;
        StoreResult parsed = parse_lists(items, lists);
        if (!parsed.ok()) return parsed;
        for (const auto& list : lists) {
            if (list.name == name) {
                return store_conflict(
                    "signal list already exists: " + name);
            }
        }
        SignalList list;
        list.name = name;
        list.signals = signals;
        lists.push_back(std::move(list));
        items = serialize_lists(lists);
        return StoreResult{};
    });
}

StoreResult ListManager::delete_list(
    const std::string& session_id,
    const std::string& name) {
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<SignalList> lists;
        StoreResult parsed = parse_lists(items, lists);
        if (!parsed.ok()) return parsed;
        std::vector<SignalList> kept;
        bool found = false;
        for (const auto& list : lists) {
            if (list.name == name) found = true;
            else kept.push_back(list);
        }
        if (!found) {
            return store_not_found("signal list not found: " + name);
        }
        items = serialize_lists(kept);
        return StoreResult{};
    });
}

StoreResult ListManager::add_signal(
    const std::string& session_id,
    const std::string& list_name,
    const std::string& signal) {
    if (list_name.empty() || signal.empty()) {
        return store_invalid(
            "signal list name and signal path must be non-empty");
    }
    return store_for(session_id).update([&](StoreJson& items) {
        std::vector<SignalList> lists;
        StoreResult parsed = parse_lists(items, lists);
        if (!parsed.ok()) return parsed;
        for (size_t index = 0; index < lists.size(); ++index) {
            if (lists[index].name != list_name) continue;
            for (const auto& existing : lists[index].signals) {
                if (existing == signal) {
                    return store_conflict(
                        "signal is already present in list " + list_name +
                        ": " + signal);
                }
            }
            lists[index].signals.push_back(signal);
            SignalList modified = lists[index];
            lists.erase(lists.begin() + index);
            lists.push_back(std::move(modified));
            items = serialize_lists(lists);
            return StoreResult{};
        }
        return store_not_found("signal list not found: " + list_name);
    });
}

StoreResult ListManager::delete_signal_by_path(
    const std::string& session_id,
    const std::string& list_name,
    const std::string& signal_path) {
    if (list_name.empty() || signal_path.empty()) {
        return store_invalid(
            "signal list name and signal path must be non-empty");
    }
    return update_named_list(
        session_id,
        list_name,
        [&](SignalList& list) {
            auto found = std::find(
                list.signals.begin(),
                list.signals.end(),
                signal_path);
            if (found == list.signals.end()) {
                return store_not_found(
                    "signal is not present in list " +
                    list_name + ": " + signal_path);
            }
            list.signals.erase(found);
            return StoreResult{};
        });
}

StoreResult ListManager::delete_signal_by_one_based_index(
    const std::string& session_id,
    const std::string& list_name,
    size_t one_based_index,
    std::string& removed_signal) {
    removed_signal.clear();
    if (list_name.empty()) {
        return store_invalid(
            "signal list name must be non-empty");
    }
    std::string removed_candidate;
    StoreResult deleted = update_named_list(
        session_id,
        list_name,
        [&](SignalList& list) {
            if (one_based_index == 0 ||
                one_based_index > list.signals.size()) {
                return signal_index_out_of_range(
                    list_name,
                    one_based_index,
                    list.signals.size());
            }
            const size_t zero_based_index =
                one_based_index - 1;
            removed_candidate =
                list.signals[zero_based_index];
            list.signals.erase(
                list.signals.begin() + zero_based_index);
            return StoreResult{};
        });
    if (deleted.ok()) {
        removed_signal = std::move(removed_candidate);
    }
    return deleted;
}

StoreResult ListManager::get_list(
    const std::string& session_id,
    const std::string& name,
    SignalList& list) {
    std::vector<SignalList> lists;
    StoreResult loaded = load_session(session_id, lists);
    if (!loaded.ok()) return loaded;
    for (const auto& current : lists) {
        if (current.name != name) continue;
        list = current;
        return {};
    }
    return store_not_found("signal list not found: " + name);
}

StoreResult ListManager::get_latest_list(
    const std::string& session_id,
    std::string& name) {
    std::vector<SignalList> lists;
    StoreResult loaded = load_session(session_id, lists);
    if (!loaded.ok()) return loaded;
    if (lists.empty()) {
        return store_not_found("no signal lists are loaded");
    }
    name = lists.back().name;
    return {};
}

StoreResult ListManager::list_all(
    const std::string& session_id,
    std::vector<SignalList>& lists) {
    return load_session(session_id, lists);
}

} // namespace xdebug_waveform
