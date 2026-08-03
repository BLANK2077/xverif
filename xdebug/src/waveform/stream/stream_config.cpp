#include "stream_config.h"

#include "core/common/sha256.h"

#include <cctype>
#include <set>
#include <utility>

namespace xdebug_waveform {

namespace {

bool get_nonempty_string_if_present(
    const Json& obj,
    const std::string& stream_name,
    const char* key,
    std::string& out,
    std::string& error) {
    auto it = obj.find(key);
    if (it == obj.end()) {
        out.clear();
        return true;
    }
    if (!it->is_string() || it->get<std::string>().empty()) {
        error = "stream " + stream_name + " " + key +
                " must be a non-empty string when present";
        return false;
    }
    out = it->get<std::string>();
    return true;
}

bool get_bool_if_present(
    const Json& obj,
    const std::string& stream_name,
    const char* key,
    bool& out,
    std::string& error) {
    auto it = obj.find(key);
    if (it == obj.end()) return true;
    if (!it->is_boolean()) {
        error = "stream " + stream_name + " " + key +
                " must be boolean when present";
        return false;
    }
    out = it->get<bool>();
    return true;
}

bool parse_field_map(const Json& item,
                     const std::string& stream_name,
                     const char* key,
                     std::map<std::string, std::string>& out,
                     std::string& error) {
    auto fields_it = item.find(key);
    if (fields_it == item.end()) return true;
    if (!fields_it->is_object()) {
        error = "stream " + stream_name + " " + key + " must be an object";
        return false;
    }
    if (fields_it->empty()) {
        error = "stream " + stream_name + " " + key +
                " must be non-empty when present";
        return false;
    }
    for (auto it = fields_it->begin(); it != fields_it->end(); ++it) {
        if (!stream_field_name_valid(it.key())) {
            error = "invalid or reserved data field name: " + it.key();
            return false;
        }
        if (!it.value().is_string() || it.value().get<std::string>().empty()) {
            error = std::string(key) + " field " + it.key() + " must map to a non-empty expression";
            return false;
        }
        if (out.find(it.key()) != out.end()) {
            error = std::string("duplicate field name in ") + key + ": " + it.key();
            return false;
        }
        out[it.key()] = it.value().get<std::string>();
    }
    return true;
}

bool parse_signal_map(const Json& item,
                      const std::string& stream_name,
                      std::map<std::string, std::string>& out,
                      std::string& error) {
    auto signals_it = item.find("signals");
    if (signals_it == item.end() || !signals_it->is_object()) {
        error = "stream " + stream_name + " requires signals object mapping alias to signal path";
        return false;
    }
    for (auto it = signals_it->begin(); it != signals_it->end(); ++it) {
        if (!stream_name_valid(it.key())) {
            error = "invalid signal alias in stream " + stream_name + ": " + it.key();
            return false;
        }
        if (!it.value().is_string() || it.value().get<std::string>().empty()) {
            error = "stream " + stream_name + " signals." + it.key() +
                    " must be a non-empty signal path string";
            return false;
        }
        out[it.key()] = it.value().get<std::string>();
    }
    if (out.empty()) {
        error = "stream " + stream_name + " requires at least one signal alias";
        return false;
    }
    return true;
}

bool is_ident_start(char c) {
    return std::isalpha(static_cast<unsigned char>(c)) || c == '_';
}

bool is_ident_char(char c) {
    return std::isalnum(static_cast<unsigned char>(c)) || c == '_';
}

} // namespace

bool stream_name_valid(const std::string& name) {
    if (name.empty() || !is_ident_start(name[0])) return false;
    for (char c : name) {
        if (!is_ident_char(c)) return false;
    }
    return true;
}

bool stream_field_name_valid(const std::string& name) {
    static const std::set<std::string> reserved = {
        "time", "cycle", "vld", "rdy", "bp", "sop", "eop",
        "transfer", "stall", "packet_index", "beat_index"
    };
    return stream_name_valid(name) && reserved.find(name) == reserved.end();
}

bool parse_stream_config_json(const Json& item, StreamConfig& config, std::string& error) {
    if (!item.is_object()) {
        error = "stream config must be an object";
        return false;
    }
    if (item.contains("stable_fields")) {
        error = "stream config field stable_fields is not supported; use packet_stable_fields";
        return false;
    }
    if (item.contains("data_fields")) {
        error = "stream config field data_fields is not supported; use beat_fields";
        return false;
    }
    static const std::set<std::string> allowed_fields = {
        "name", "signals", "clock", "edge", "sample_point", "reset",
        "vld", "rdy", "bp", "sop", "eop", "data", "beat_fields",
        "packet_stable_fields", "channel_id", "channel_id_valid",
        "allow_interleaving", "description"
    };
    for (auto it = item.begin(); it != item.end(); ++it) {
        if (allowed_fields.find(it.key()) == allowed_fields.end()) {
            error = "stream config contains unknown field: " + it.key();
            return false;
        }
    }
    config = StreamConfig();
    static const char* legacy[] = {"clk", "sampling", "clock_edge", "posedge", "sample_offset", nullptr};
    for (int i = 0; legacy[i]; ++i) {
        if (item.contains(legacy[i])) {
            error = std::string("stream config uses legacy clock sampling field: ") +
                    legacy[i] + "; use clock, edge, and sample_point";
            return false;
        }
    }
    if (!get_nonempty_string_if_present(
            item, "<unnamed>", "name", config.name, error)) {
        return false;
    }
    if (!stream_name_valid(config.name)) {
        error = "invalid stream name: " + config.name;
        return false;
    }
    if (!parse_signal_map(item, config.name, config.signals, error)) return false;
    if (!get_nonempty_string_if_present(
            item, config.name, "clock", config.clock_sample.clock, error)) {
        return false;
    }
    config.has_reset = item.contains("reset");
    if (config.has_reset && !parse_reset_config(item["reset"], config.reset, error)) {
        error = "invalid stream reset for " + config.name + ": " + error;
        return false;
    }
    const std::pair<const char*, std::string*> string_fields[] = {
        {"vld", &config.vld}, {"rdy", &config.rdy},
        {"bp", &config.bp}, {"sop", &config.sop},
        {"eop", &config.eop}, {"data", &config.data},
        {"channel_id", &config.channel_id},
        {"channel_id_valid", &config.channel_id_valid},
        {"description", &config.description},
    };
    for (const auto& field : string_fields) {
        if (!get_nonempty_string_if_present(
                item, config.name, field.first, *field.second, error)) {
            return false;
        }
    }
    if (!get_bool_if_present(
            item,
            config.name,
            "allow_interleaving",
            config.allow_interleaving,
            error)) {
        return false;
    }

    std::string edge;
    if (!get_nonempty_string_if_present(
            item, config.name, "edge", edge, error)) {
        return false;
    }
    if (!parse_clock_edge_kind(edge.empty() ? "negedge" : edge, config.clock_sample.edge, error)) {
        error = "invalid stream edge for " + config.name + ": " + error;
        return false;
    }
    std::string sample_point;
    if (item.contains("sample_point")) {
        if (!get_nonempty_string_if_present(
                item,
                config.name,
                "sample_point",
                sample_point,
                error)) {
            return false;
        }
        config.clock_sample.has_sample_point = true;
        if (!parse_clock_sample_point_kind(sample_point,
                                           config.clock_sample.sample_point,
                                           error)) {
            error = "invalid stream sample_point for " + config.name + ": " + error;
            return false;
        }
    }
    if (config.clock_sample.edge == ClockEdgeKind::Negedge &&
        config.clock_sample.has_sample_point) {
        error = "stream " + config.name + " sample_point is only valid with edge:posedge or edge:dual";
        return false;
    }

    if (config.clock_sample.clock.empty()) {
        error = "stream " + config.name + " requires clock";
        return false;
    }
    if (config.vld.empty()) {
        error = "stream " + config.name + " requires vld";
        return false;
    }

    if (config.channel_id_valid.empty()) config.channel_id_valid = "every_beat";
    if (config.channel_id_valid != "sop" &&
        config.channel_id_valid != "eop" &&
        config.channel_id_valid != "every_beat") {
        error = "stream " + config.name + " channel_id_valid must be sop, eop, or every_beat";
        return false;
    }
    if (!parse_field_map(item, config.name, "packet_stable_fields", config.packet_stable_fields, error)) return false;
    if (!parse_field_map(item, config.name, "beat_fields", config.beat_fields, error)) return false;
    if (!config.data.empty()) {
        if (config.beat_fields.find("data") != config.beat_fields.end()) {
            error = "data and beat_fields must not share field name: data";
            return false;
        }
    }
    for (const auto& kv : config.packet_stable_fields) {
        if (config.beat_fields.find(kv.first) != config.beat_fields.end() ||
            (!config.data.empty() && kv.first == "data")) {
            error = "packet_stable_fields and beat_fields must not share field name: " + kv.first;
            return false;
        }
    }
    if (config.data.empty() && config.beat_fields.empty() &&
        config.packet_stable_fields.empty()) {
        error = "stream " + config.name + " requires data, packet_stable_fields, or beat_fields";
        return false;
    }
    if ((config.sop.empty()) != (config.eop.empty())) {
        error = "stream " + config.name + " requires sop and eop to be configured together";
        return false;
    }
    if ((config.channel_id_valid == "sop" || config.channel_id_valid == "eop") && !stream_packet_enabled(config)) {
        error = "stream " + config.name + " channel_id_valid=" + config.channel_id_valid + " requires sop/eop";
        return false;
    }
    if ((config.channel_id_valid == "sop" || config.channel_id_valid == "eop") && config.channel_id.empty()) {
        error = "stream " + config.name + " channel_id_valid=" + config.channel_id_valid + " requires channel_id";
        return false;
    }
    if (config.allow_interleaving) {
        if (!stream_packet_enabled(config)) {
            error = "stream " + config.name + " allow_interleaving requires sop/eop";
            return false;
        }
        if (config.channel_id.empty()) {
            error = "stream " + config.name + " allow_interleaving requires channel_id";
            return false;
        }
        if (config.channel_id_valid != "every_beat") {
            error = "stream " + config.name + " allow_interleaving requires channel_id_valid=every_beat";
            return false;
        }
    }
    return true;
}

Json stream_config_json(const StreamConfig& c) {
    Json j;
    j["name"] = c.name;
    j["signals"] = Json::object();
    for (const auto& kv : c.signals) j["signals"][kv.first] = kv.second;
    j["clock"] = c.clock_sample.clock;
    j["edge"] = clock_edge_kind_text(c.clock_sample.edge);
    if (c.clock_sample.edge != ClockEdgeKind::Negedge)
        j["sample_point"] = clock_sample_point_text(c.clock_sample.sample_point);
    if (c.has_reset) j["reset"] = reset_config_json(c.reset);
    j["vld"] = c.vld;
    if (!c.rdy.empty()) j["rdy"] = c.rdy;
    if (!c.bp.empty()) j["bp"] = c.bp;
    if (!c.sop.empty()) j["sop"] = c.sop;
    if (!c.eop.empty()) j["eop"] = c.eop;
    if (!c.data.empty()) j["data"] = c.data;
    if (!c.packet_stable_fields.empty()) {
        j["packet_stable_fields"] = Json::object();
        for (const auto& kv : c.packet_stable_fields) j["packet_stable_fields"][kv.first] = kv.second;
    }
    if (!c.beat_fields.empty()) {
        j["beat_fields"] = Json::object();
        for (const auto& kv : c.beat_fields) j["beat_fields"][kv.first] = kv.second;
    }
    if (!c.channel_id.empty()) j["channel_id"] = c.channel_id;
    j["channel_id_valid"] = c.channel_id_valid.empty() ? "every_beat" : c.channel_id_valid;
    j["allow_interleaving"] = c.allow_interleaving;
    if (!c.description.empty()) j["description"] = c.description;
    return j;
}

std::string stream_handshake_text(const StreamConfig& c) {
    if (!c.rdy.empty() && !c.bp.empty()) return "vld/rdy/bp";
    if (!c.rdy.empty()) return "vld/rdy";
    if (!c.bp.empty()) return "vld/bp";
    return "vld";
}

bool stream_packet_enabled(const StreamConfig& c) {
    return !c.sop.empty() && !c.eop.empty();
}

std::string normalized_stream_config_semantics(const StreamConfig& config) {
    Json normalized = stream_config_json(config);
    normalized.erase("name");
    normalized.erase("description");
    return normalized.dump();
}

std::string stream_config_semantic_fingerprint(const StreamConfig& config) {
    return xdebug_core::sha256_text(normalized_stream_config_semantics(config));
}

} // namespace xdebug_waveform
