#include "action_support.h"
#include "core/value/logic_value.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <vector>

namespace xdebug_waveform {

std::string compact_expr_ws(const std::string& expr) {
    std::string out;
    out.reserve(expr.size());
    for (char c : expr) {
        if (!std::isspace(static_cast<unsigned char>(c))) out.push_back(c);
    }
    return out;
}

bool contains_xz(const std::string& value) {
    return xdebug_core::logic_value_has_xz(
        xdebug_core::logic_value_from_fsdb_raw(value, 'h'));
}

std::string normalize_numeric(std::string value) {
    xdebug_core::LogicValue parsed =
        xdebug_core::logic_value_from_fsdb_raw(value, 'h');
    return xdebug_core::logic_value_compare_key(parsed);
}

Json make_value_object(const std::string& raw) {
    return xdebug_core::logic_value_json(
        xdebug_core::logic_value_from_fsdb_raw(raw, 'h'));
}

Json make_value_map(const Json& raw_map) {
    Json out = Json::object();
    if (!raw_map.is_object()) return out;
    for (auto it = raw_map.begin(); it != raw_map.end(); ++it) {
        if (it.value().is_string()) out[it.key()] = make_value_object(it.value().get<std::string>());
        else out[it.key()] = it.value();
    }
    return out;
}

Json simplify_event_value_objects(Json events) {
    if (!events.is_array()) return events;
    for (auto& ev : events) {
        if (!ev.is_object()) continue;
        if (ev.contains("signals")) ev["signals"] = make_value_map(ev["signals"]);
        if (ev.contains("fields")) ev["fields"] = make_value_map(ev["fields"]);
    }
    return events;
}

namespace {

std::string event_group_value(const Json& ev, const std::string& key) {
    auto get = [&](const char* section) -> std::string {
        if (!ev.contains(section) || !ev[section].is_object()) return std::string();
        auto it = ev[section].find(key);
        if (it == ev[section].end()) return std::string();
        if (it->is_string()) return it->get<std::string>();
        if (it->is_object() && it->contains("value") && (*it)["value"].is_string()) return (*it)["value"].get<std::string>();
        return std::string();
    };
    std::string v = get("fields");
    if (v.empty()) v = get("signals");
    if (v.empty() || v == "?" || contains_xz(v)) return "unknown";
    return v;
}

} // namespace

Json aggregate_events(const Json& events, const Json& aggregate_args, int limit) {
    bool want_count = aggregate_args.value("count", true);
    Json group_by_json = aggregate_args.value("group_by", Json::array());
    std::vector<std::string> group_by;
    if (group_by_json.is_array()) {
        for (const auto& item : group_by_json) if (item.is_string()) group_by.push_back(item.get<std::string>());
    }

    Json out = Json::object();
    size_t event_count = events.is_array() ? events.size() : 0;
    if (want_count) out["count"] = event_count;
    out["limited"] = limit > 0 && event_count >= static_cast<size_t>(limit);

    if (!group_by.empty() && events.is_array()) {
        struct GroupState {
            Json key;
            int count = 0;
            std::string first_time;
            std::string last_time;
        };
        std::map<std::string, GroupState> groups;
        for (const auto& ev : events) {
            Json key_obj = Json::object();
            for (const auto& key : group_by) key_obj[key] = event_group_value(ev, key);
            std::string group_id = key_obj.dump();
            GroupState& st = groups[group_id];
            if (st.count == 0) {
                st.key = key_obj;
                st.first_time = ev.value("time", std::string());
            }
            st.count++;
            st.last_time = ev.value("time", std::string());
        }
        Json arr = Json::array();
        for (const auto& kv : groups) {
            arr.push_back({{"key", kv.second.key},
                           {"count", kv.second.count},
                           {"first_time", kv.second.first_time},
                           {"last_time", kv.second.last_time}});
        }
        out["groups"] = arr;
        out["group_count"] = arr.size();
    }
    return out;
}

} // namespace xdebug_waveform
