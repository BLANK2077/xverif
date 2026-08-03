#include "../server_internal.h"
#include "../../common/clock_sampling_response.h"

namespace xdebug_waveform {

namespace {

std::string json_type_name(const Json& value) {
    if (value.is_null()) return "null";
    if (value.is_boolean()) return "boolean";
    if (value.is_number()) return "number";
    if (value.is_string()) return "string";
    if (value.is_array()) return "array";
    if (value.is_object()) return "object";
    return "unknown";
}

Json invalid_signal_anomaly_inspect_checks(const std::string& invalid_arg,
                                    const std::string& message,
                                    const Json& received = Json()) {
    Json error;
    error["code"] = "INVALID_REQUEST";
    error["message"] = message;
    error["recoverable"] = true;
    error["next_actions"] = Json::array({
        "Use object checks such as {\"type\":\"unknown_xz\"}. String shorthand is not supported.",
        "Allowed check types are unknown_xz, glitch, and stuck."
    });

    Json out;
    out["error"] = error;
    out["message"] = message;
    out["invalid_arg"] = invalid_arg;
    out["expected"] = "args.checks must be an array of objects with a string type field";
    out["allowed_types"] = Json::array({"unknown_xz", "glitch", "stuck"});
    out["example"] = Json::array({
        Json{{"type", "unknown_xz"}},
        Json{{"type", "glitch"}, {"min_pulse_width", "1ns"}},
        Json{{"type", "stuck"}, {"min_duration", "1us"}}
    });
    if (!received.is_null()) out["received_type"] = json_type_name(received);
    return out;
}

}  // namespace

struct SampledEdgeRecord {
    npiFsdbTime time = 0;
    std::map<std::string, std::string> values;
};

Json sample_edge_json(const std::vector<SampledEdgeRecord>& edges, int idx) {
    if (idx < 0 || idx >= static_cast<int>(edges.size())) return Json(nullptr);
    return format_time(edges[idx].time);
}

int lower_sample_edge(const std::vector<SampledEdgeRecord>& edges, npiFsdbTime t) {
    auto it = std::lower_bound(edges.begin(), edges.end(), t,
        [](const SampledEdgeRecord& e, npiFsdbTime value) { return e.time < value; });
    return static_cast<int>(it - edges.begin());
}

int nearest_sample_edge(const std::vector<SampledEdgeRecord>& edges, npiFsdbTime t) {
    if (edges.empty()) return -1;
    int next = lower_sample_edge(edges, t);
    if (next <= 0) return 0;
    if (next >= static_cast<int>(edges.size())) return static_cast<int>(edges.size()) - 1;
    npiFsdbTime prev_dt = t >= edges[next - 1].time ? t - edges[next - 1].time : edges[next - 1].time - t;
    npiFsdbTime next_dt = edges[next].time >= t ? edges[next].time - t : t - edges[next].time;
    return prev_dt <= next_dt ? next - 1 : next;
}

Json sampled_valid_json(const std::vector<SampledEdgeRecord>& edges, int idx,
                        const std::string& valid_signal) {
    if (idx < 0 || idx >= static_cast<int>(edges.size())) return Json(nullptr);
    auto it = edges[idx].values.find("valid");
    if (it == edges[idx].values.end()) return Json(nullptr);
    return wave_value_json(it->second, 'b', valid_signal);
}

Json sampled_payloads_json(const std::vector<SampledEdgeRecord>& edges,
                                  int idx,
                                  const Json& payload_aliases) {
    Json out = Json::array();
    if (idx < 0 || idx >= static_cast<int>(edges.size())) return out;
    for (const auto& p : payload_aliases) {
        std::string alias = p.value("alias", std::string());
        std::string signal = p.value("signal", std::string());
        auto it = edges[idx].values.find(alias);
        if (it == edges[idx].values.end()) continue;
        out.push_back({{"alias", alias}, {"signal", signal},
                       {"value", wave_value_json(it->second, 'b', signal)}});
    }
    return out;
}

Json ai_signal_sampled_pulse_inspect(const Json& args, std::string& error) {
    ClockSampleSpec clock_sample;
    if (!clock_sample_from_args(args, clock_sample, error)) return Json();
    std::string clock = clock_sample.clock;
    std::string valid = args.value("valid", std::string());
    if (clock.empty() || valid.empty()) {
        error = "signal.sampled_pulse.inspect requires args.clock and args.valid";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();

    Json signals = {{"valid", valid}};
    Json payload_aliases = Json::array();
    auto add_payload = [&](const std::string& path) -> bool {
        if (path.empty()) {
            error = "payload signal paths must be non-empty";
            return false;
        }
        std::string alias = "payload" + std::to_string(payload_aliases.size());
        signals[alias] = path;
        payload_aliases.push_back({{"alias", alias}, {"signal", path}});
        return true;
    };
    if (args.contains("payloads")) {
        if (!args["payloads"].is_array() || args["payloads"].empty()) {
            error = "args.payloads must be a non-empty array of signal paths";
            return Json();
        }
        for (const auto& p : args["payloads"]) {
            if (!p.is_string() || !add_payload(p.get<std::string>())) {
                if (error.empty()) error = "args.payloads entries must be non-empty signal paths";
                return Json();
            }
        }
    }

    std::vector<std::string> aliases, paths;
    fsdbSigVec_t handles;
    if (!build_signal_alias_handles(signals, aliases, paths, handles, error)) return Json();
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < aliases.size(); ++i) {
        sample_signals.push_back({aliases[i], paths[i], handles[i]});
    }

    int max_findings = args.value("line_limit", 100);
    Json rules = args.value("rules", Json::object());
    std::string payload_reporting = rules.value(
        "payload_changed_without_sampled_valid", std::string("summary"));
    if (payload_reporting != "off" && payload_reporting != "summary" &&
        payload_reporting != "all") {
        error = "signal.sampled_pulse.inspect rules.payload_changed_without_sampled_valid must be off, summary, or all";
        return Json();
    }
    if (rules.contains("payload_changed_without_sampled_valid") &&
        payload_aliases.empty()) {
        error = "rules.payload_changed_without_sampled_valid requires args.payloads";
        return Json();
    }
    npiFsdbValType fmt = npiFsdbHexStrVal;
    if (!json_value_format(args, fmt, error)) return Json();
    char value_prefix = json_value_prefix(fmt);

    std::vector<SampledEdgeRecord> edges;
    int sample_count = 0;
    bool sample_truncated = false;
    int sampled_high = 0, sampled_low = 0, sampled_unknown = 0;
    npiFsdbTime first_high = 0, last_high = 0;
    ClockSampleScanner scanner(g_fsdb_file, clock_sample);
    if (!scanner.scan(sample_signals, begin, end, npiFsdbBinStrVal, 'b', -1,
        [&](const ClockSample& sample) -> bool {
            npiFsdbTime t = sample.time;
            std::map<std::string, std::string> values = clock_sample_value_map(sample_signals, sample.values);
            SampledEdgeRecord rec;
            rec.time = t;
            rec.values = values;
            edges.push_back(rec);
            auto it = values.find("valid");
            ExprTri v = it == values.end() ? ExprTri::Unknown : xdebug_waveform::expr_truth_value(it->second);
            if (v == ExprTri::True) {
                sampled_high++;
                if (first_high == 0) first_high = t;
                last_high = t;
            } else if (v == ExprTri::False) {
                sampled_low++;
            } else {
                sampled_unknown++;
            }
            return true;
        }, error, sample_count, sample_truncated)) return Json();

    fsdbTimeValPairVec_t valid_changes;
    bool valid_truncated = false;
    if (!read_signal_changes(valid, begin, end, npiFsdbBinStrVal, valid_changes, error, -1, &valid_truncated)) return Json();

    std::string init_valid;
    if (!read_sig_value_at(g_fsdb_file, valid.c_str(), begin, 'B', init_valid)) {
        error = "Failed to read initial valid value: " + valid;
        return Json();
    }
    std::string current_valid = with_value_prefix(init_valid, 'b');
    npiFsdbTime segment_begin = begin;
    Json findings = Json::array();
    bool findings_truncated = false;
    int risk_count = 0;
    int unsampled_pulse_count = 0;
    int payload_risk_count = 0;
    auto push_finding = [&](const Json& item) {
        ++risk_count;
        if (max_findings >= 0 && static_cast<int>(findings.size()) >= max_findings) {
            findings_truncated = true;
            return;
        }
        findings.push_back(item);
    };

    auto valid_sampled_high_between = [&](npiFsdbTime lo, npiFsdbTime hi) {
        int idx = lower_sample_edge(edges, lo);
        while (idx >= 0 && idx < static_cast<int>(edges.size()) && edges[idx].time < hi) {
            auto it = edges[idx].values.find("valid");
            if (it != edges[idx].values.end() && xdebug_waveform::expr_truth_value(it->second) == ExprTri::True) return true;
            ++idx;
        }
        return false;
    };
    auto emit_unsampled_pulse = [&](npiFsdbTime lo, npiFsdbTime hi, const std::string& raw_value) {
        if (hi <= lo) return;
        if (valid_sampled_high_between(lo, hi)) return;
        int next = lower_sample_edge(edges, lo);
        int prev = next - 1;
        int near = nearest_sample_edge(edges, lo);
        Json item;
        item["type"] = "unsampled_valid_pulse";
        item["severity"] = "warning";
        item["raw_begin"] = format_time(lo);
        item["raw_end"] = format_time(hi);
        item["previous_sample_edge"] = sample_edge_json(edges, prev);
        item["next_sample_edge"] = sample_edge_json(edges, next);
        item["nearest_sample_edge"] = sample_edge_json(edges, near);
        item["raw_valid"] = wave_value_json(raw_value, 'b', valid);
        item["sampled_valid"] = sampled_valid_json(edges, near, valid);
        item["sampled_payloads"] = sampled_payloads_json(edges, near, payload_aliases);
        item["reason"] = "valid was high between sample edges but not high at any sampled edge";
        ++unsampled_pulse_count;
        push_finding(item);
    };

    for (const auto& ch : valid_changes) {
        npiFsdbTime change_time = ch.first;
        std::string next_valid = with_value_prefix(ch.second, 'b');
        if (xdebug_waveform::expr_truth_value(current_valid) == ExprTri::True) {
            emit_unsampled_pulse(segment_begin, change_time, current_valid);
        }
        current_valid = next_valid;
        segment_begin = change_time;
    }
    if (xdebug_waveform::expr_truth_value(current_valid) == ExprTri::True) {
        emit_unsampled_pulse(segment_begin, end, current_valid);
    }

    int payload_transition_count = 0;
    bool payload_truncated = false;
    if (payload_reporting != "off") for (const auto& p : payload_aliases) {
        std::string alias = p.value("alias", std::string());
        std::string signal = p.value("signal", std::string());
        fsdbTimeValPairVec_t changes;
        bool one_truncated = false;
        if (!read_signal_changes(signal, begin, end, fmt, changes, error, -1, &one_truncated)) return Json();
        payload_transition_count += static_cast<int>(changes.size());
        if (one_truncated) payload_truncated = true;
        for (const auto& ch : changes) {
            int near = nearest_sample_edge(edges, ch.first);
            ExprTri sampled_valid = ExprTri::Unknown;
            if (near >= 0) {
                auto it = edges[near].values.find("valid");
                if (it != edges[near].values.end()) sampled_valid = xdebug_waveform::expr_truth_value(it->second);
            }
            if (sampled_valid == ExprTri::True) continue;
            int next = lower_sample_edge(edges, ch.first);
            int prev = next - 1;
            Json item;
            item["type"] = "payload_changed_without_sampled_valid";
            item["severity"] = "warning";
            item["raw_time"] = format_time(ch.first);
            item["previous_sample_edge"] = sample_edge_json(edges, prev);
            item["next_sample_edge"] = sample_edge_json(edges, next);
            item["nearest_sample_edge"] = sample_edge_json(edges, near);
            item["payload"] = {{"alias", alias}, {"signal", signal},
                               {"value", wave_value_json(
                                   ch.second, value_prefix, signal)}};
            item["sampled_valid"] = sampled_valid_json(edges, near, valid);
            item["sampled_payloads"] = sampled_payloads_json(edges, near, payload_aliases);
            item["reason"] = sampled_valid == ExprTri::Unknown
                ? "payload changed but sampled valid was unknown"
                : "payload changed but valid was not sampled high by the DUT clock";
            ++payload_risk_count;
            ++risk_count;
            if (payload_reporting == "all") {
                --risk_count;
                push_finding(item);
            }
        }
    }

    bool analysis_complete = !sample_truncated && !valid_truncated && !payload_truncated;
    Json data;
    data["summary"] = {
        {"sampling_mode", "clock_edge"},
        {"clock", clock_sample.clock},
        {"sample_time_semantics", "time is sample_time"},
        {"sample_count", sample_count},
        {"sampled_high_cycles", sampled_high},
        {"unsampled_valid_pulse_count", unsampled_pulse_count},
        {"payload_risk_count", payload_risk_count},
        {"payload_changed_without_sampled_valid_reporting", payload_reporting}
    };
    std::vector<std::string> truncation_scopes;
    if (sample_truncated) truncation_scopes.push_back("analysis_samples");
    if (valid_truncated) truncation_scopes.push_back("analysis_valid_changes");
    if (payload_truncated) truncation_scopes.push_back("analysis_payload_changes");
    if (findings_truncated) truncation_scopes.push_back("response_findings");
    xdebug_core::set_completeness(
        data["summary"],
        analysis_complete,
        analysis_complete,
        findings_truncated,
        static_cast<std::size_t>(risk_count),
        findings.size(),
        truncation_scopes);
    data["sampling"] = clock_sampling_contract_json(clock_sample);
    data["valid"] = valid;
    data["payloads"] = payload_aliases;
    data["begin"] = format_time(begin);
    data["end"] = format_time(end);
    data["sampled_low_cycles"] = sampled_low;
    data["sampled_unknown_cycles"] = sampled_unknown;
    data["raw_valid_transition_count"] = valid_changes.size();
    data["payload_transition_count"] = payload_transition_count;
    data["first_sampled_high_time"] = first_high == 0 ? Json(nullptr) : Json(format_time(first_high));
    data["last_sampled_high_time"] = last_high == 0 ? Json(nullptr) : Json(format_time(last_high));
    data["findings"] = findings;
    return data;
}

Json ai_protocol_handshake_inspect(const Json& args, std::string& error) {
    ClockSampleSpec clock_sample;
    if (!clock_sample_from_args(args, clock_sample, error)) return Json();
    std::string clock = clock_sample.clock;
    std::string valid = args.value("valid", std::string());
    std::string ready = args.value("ready", std::string());
    if (clock.empty() || valid.empty() || ready.empty()) {
        error = "protocol.handshake.inspect requires args.clock, args.valid and args.ready";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    Json signals = {{"valid", valid}, {"ready", ready}};
    bool has_data = false;
    if (args.contains("data") && args["data"].is_string()) {
        const std::string path = args["data"].get<std::string>();
        if (path.empty()) {
            error = "protocol.handshake.inspect args.data must not be empty";
            return Json();
        }
        signals["data0"] = path;
        has_data = true;
    } else if (args.contains("data") && args["data"].is_array()) {
        if (args["data"].empty()) {
            error = "protocol.handshake.inspect args.data array must not be empty";
            return Json();
        }
        int idx = 0;
        for (const auto& d : args["data"]) {
            if (!d.is_string() || d.get<std::string>().empty()) {
                error = "protocol.handshake.inspect args.data entries must be non-empty signal paths";
                return Json();
            }
            signals["data" + std::to_string(idx++)] =
                d.get<std::string>();
        }
        has_data = true;
    } else if (args.contains("data")) {
        error = "protocol.handshake.inspect args.data must be a non-empty signal path or signal-path array";
        return Json();
    }
    std::vector<std::string> aliases, paths;
    fsdbSigVec_t handles;
    if (!build_signal_alias_handles(signals, aliases, paths, handles, error)) return Json();
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < aliases.size(); ++i) {
        sample_signals.push_back({aliases[i], paths[i], handles[i]});
    }
    Json rules = args.value("rules", Json::object());
    int max_wait = rules.value("max_wait_cycles", 100);
    bool check_data = rules.value("check_data_stable_when_stalled", false);
    bool require_valid_hold = rules.value("require_valid_hold_until_handshake", true);
    std::string ready_reporting = rules.value("ready_without_valid", std::string("summary"));
    if (ready_reporting != "summary" && ready_reporting != "intervals" && ready_reporting != "all") {
        error = "protocol.handshake.inspect rules.ready_without_valid must be summary, intervals, or all";
        return Json();
    }
    if (has_data != check_data) {
        error = has_data
            ? "args.data requires rules.check_data_stable_when_stalled=true"
            : "rules.check_data_stable_when_stalled=true requires args.data";
        return Json();
    }
    int samples = 0, transfers = 0, stall_cycles = 0, max_stall = 0, ready_only = 0, data_violations = 0;
    int valid_hold_violations = 0;
    bool in_stall = false, scan_truncated = false;
    bool awaiting_handshake = false;
    npiFsdbTime valid_wait_begin = 0;
    npiFsdbTime stall_begin = 0;
    std::map<std::string, std::string> stall_data;
    Json findings = Json::array();
    const int finding_limit = args.value("line_limit", 100);
    int finding_count = 0;
    auto add_finding = [&](const Json& finding) {
        ++finding_count;
        if (finding_limit < 0 || static_cast<int>(findings.size()) < finding_limit)
            findings.push_back(finding);
    };
    bool in_ready_only = false;
    npiFsdbTime ready_only_begin = 0;
    npiFsdbTime ready_only_end = 0;
    int ready_only_interval_cycles = 0;
    int ready_only_interval_count = 0;
    Json ready_only_intervals = Json::array();
    auto finish_ready_only_interval = [&](npiFsdbTime interval_end, bool open_at_window_end) {
        if (!in_ready_only) return;
        ++ready_only_interval_count;
        if (ready_reporting == "intervals") {
            Json interval = {{"begin", format_time(ready_only_begin)},
                             {"end", format_time(interval_end)},
                             {"cycle_count", ready_only_interval_cycles}};
            if (open_at_window_end) interval["open_at_window_end"] = true;
            ready_only_intervals.push_back(interval);
        }
        in_ready_only = false;
        ready_only_interval_cycles = 0;
    };
    ClockSampleScanner scanner(g_fsdb_file, clock_sample);
    if (!scanner.scan(sample_signals, begin, end, npiFsdbBinStrVal, 'b', -1,
        [&](const ClockSample& sample) -> bool {
            npiFsdbTime t = sample.time;
            std::map<std::string, std::string> values = clock_sample_value_map(sample_signals, sample.values);
            ExprTri v = xdebug_waveform::expr_truth_value(values.at("valid"));
            ExprTri r = xdebug_waveform::expr_truth_value(values.at("ready"));
            bool transfer = v == ExprTri::True && r == ExprTri::True;
            bool stall = v == ExprTri::True && r == ExprTri::False;
            if (transfer) transfers++;
            if (require_valid_hold && awaiting_handshake) {
                if (transfer) {
                    awaiting_handshake = false;
                } else if (v != ExprTri::True) {
                    ++valid_hold_violations;
                    add_finding({{"type", "valid_dropped_before_handshake"},
                                 {"severity", "error"},
                                 {"begin", format_time(valid_wait_begin)},
                                 {"time", format_time(t)},
                                 {"observed_valid", wave_value_json(
                                     values.at("valid"), 'b', valid)},
                                 {"reason", v == ExprTri::Unknown
                                     ? "valid became unknown before a handshake"
                                     : "valid deasserted before a handshake"}});
                    awaiting_handshake = false;
                }
            }
            if (require_valid_hold && stall && !awaiting_handshake) {
                awaiting_handshake = true;
                valid_wait_begin = t;
            }
            if (r == ExprTri::True && v == ExprTri::False) {
                ready_only++;
                if (!in_ready_only) { in_ready_only = true; ready_only_begin = t; }
                ready_only_end = t;
                ++ready_only_interval_cycles;
                if (ready_reporting == "all")
                    add_finding({{"type", "ready_without_valid"}, {"severity", "info"},
                                 {"time", format_time(t)}});
            } else {
                finish_ready_only_interval(ready_only_end, false);
            }
            if (stall) {
                stall_cycles++;
                if (!in_stall) {
                    in_stall = true;
                    stall_begin = t;
                    stall_data = values;
                } else if (check_data) {
                    for (const auto& kv : values) {
                        if (kv.first.find("data") == 0 && stall_data[kv.first] != kv.second) {
                            data_violations++;
                            add_finding({{"type", "data_changed_while_stalled"}, {"severity", "warning"},
                                         {"begin", format_time(stall_begin)}, {"time", format_time(t)},
                                         {"signal", kv.first}});
                        }
                    }
                }
            } else if (in_stall) {
                int cycles = stall_cycles;
                if (cycles > max_stall) max_stall = cycles;
                if (cycles > max_wait) {
                    add_finding({{"type", "long_stall"}, {"severity", "warning"},
                                 {"begin", format_time(stall_begin)}, {"end", format_time(t)}, {"cycles", cycles}});
                }
                in_stall = false;
                stall_cycles = 0;
            }
            return true;
        }, error, samples, scan_truncated)) return Json();
    if (in_stall) {
        if (stall_cycles > max_stall) max_stall = stall_cycles;
        if (stall_cycles > max_wait) {
            add_finding({{"type", "long_stall"}, {"severity", "warning"},
                         {"begin", format_time(stall_begin)}, {"end", format_time(end)},
                         {"cycles", stall_cycles}, {"open_at_window_end", true}});
        }
    }
    finish_ready_only_interval(ready_only_end, true);
    const bool response_truncated = finding_limit >= 0 && finding_count > finding_limit;
    Json data;
    data["summary"] = {
        {"sampling_mode", "clock_edge"},
        {"clock", clock_sample.clock},
        {"sample_time_semantics", "time is sample_time"},
        {"sample_count", samples},
        {"transfer_count", transfers},
        {"max_stall_cycles", max_stall},
        {"ready_without_valid_cycles", ready_only},
        {"ready_without_valid_reporting", ready_reporting},
        {"ready_without_valid_interval_count", ready_only_interval_count},
        {"data_stability_violations", data_violations},
        {"require_valid_hold_until_handshake", require_valid_hold},
        {"valid_hold_violations", valid_hold_violations},
        {"valid_wait_open_at_window_end", awaiting_handshake}
    };
    std::vector<std::string> truncation_scopes;
    if (scan_truncated) truncation_scopes.push_back("analysis_samples");
    if (response_truncated) truncation_scopes.push_back("response_findings");
    xdebug_core::set_completeness(
        data["summary"],
        !scan_truncated,
        !scan_truncated,
        response_truncated,
        static_cast<std::size_t>(finding_count),
        findings.size(),
        truncation_scopes);
    data["sampling"] = clock_sampling_contract_json(clock_sample);
    if (ready_reporting == "intervals") data["ready_without_valid_intervals"] = ready_only_intervals;
    data["findings"] = findings;
    return data;
}

Json ai_signal_anomaly_inspect(const Json& args, std::string& error) {
    if (!args.contains("signals") || !args["signals"].is_array() ||
        args["signals"].empty()) {
        error = "signal.anomaly.inspect requires args.signals[]";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    Json checks = args.value("checks", Json::array());
    npiFsdbTime glitch_width = 0, stuck_duration = 0;
    bool check_glitch = false, check_stuck = false, check_unknown = false;
    std::set<std::string> configured_check_types;
    if (!checks.is_array()) {
        return invalid_signal_anomaly_inspect_checks(
            "args.checks",
            "args.checks must be an array of objects with a string type field; string shorthand is not supported.",
            checks);
    }
    for (size_t i = 0; i < checks.size(); ++i) {
        const Json& c = checks[i];
        std::string arg_path = "args.checks[" + std::to_string(i) + "]";
        if (!c.is_object()) {
            return invalid_signal_anomaly_inspect_checks(
                arg_path,
                arg_path + " must be an object with a string type field; string shorthand is not supported. Example: {\"type\":\"unknown_xz\"}",
                c);
        }
        if (!c.contains("type") || !c["type"].is_string()) {
            return invalid_signal_anomaly_inspect_checks(
                arg_path + ".type",
                arg_path + ".type must be a string; allowed types are unknown_xz, glitch, and stuck.",
                c.contains("type") ? c["type"] : Json(nullptr));
        }
        std::string type = c["type"].get<std::string>();
        if (!configured_check_types.insert(type).second) {
            return invalid_signal_anomaly_inspect_checks(
                arg_path + ".type",
                arg_path + ".type duplicates an earlier check; configure each check type at most once.",
                c["type"]);
        }
        if (type == "glitch") {
            bool unknown_field = false;
            for (auto it = c.begin(); it != c.end(); ++it) {
                if (it.key() != "type" && it.key() != "min_pulse_width")
                    unknown_field = true;
            }
            if (unknown_field) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path,
                    arg_path + " glitch check accepts only type and min_pulse_width",
                    c);
            }
            check_glitch = true;
            if (c.contains("min_pulse_width") && !c["min_pulse_width"].is_string()) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path + ".min_pulse_width",
                    arg_path + ".min_pulse_width must be a time string such as \"1ns\".",
                    c["min_pulse_width"]);
            }
            std::string v = c.value("min_pulse_width", std::string("1ns"));
            if (!parse_user_time(v.c_str(), false, glitch_width, error)) {
                std::string parse_error = error;
                error.clear();
                return invalid_signal_anomaly_inspect_checks(
                    arg_path + ".min_pulse_width",
                    arg_path + ".min_pulse_width must be a valid time string such as \"1ns\": " + parse_error,
                    c["min_pulse_width"]);
            }
            if (glitch_width == 0) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path + ".min_pulse_width",
                    arg_path + ".min_pulse_width must be greater than zero.",
                    c.value("min_pulse_width", Json("1ns")));
            }
        } else if (type == "stuck") {
            bool unknown_field = false;
            for (auto it = c.begin(); it != c.end(); ++it) {
                if (it.key() != "type" && it.key() != "min_duration")
                    unknown_field = true;
            }
            if (unknown_field) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path,
                    arg_path + " stuck check accepts only type and min_duration",
                    c);
            }
            check_stuck = true;
            if (c.contains("min_duration") && !c["min_duration"].is_string()) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path + ".min_duration",
                    arg_path + ".min_duration must be a time string such as \"1us\".",
                    c["min_duration"]);
            }
            std::string v = c.value("min_duration", std::string("1us"));
            if (!parse_user_time(v.c_str(), false, stuck_duration, error)) {
                std::string parse_error = error;
                error.clear();
                return invalid_signal_anomaly_inspect_checks(
                    arg_path + ".min_duration",
                    arg_path + ".min_duration must be a valid time string such as \"1us\": " + parse_error,
                    c["min_duration"]);
            }
            if (stuck_duration == 0) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path + ".min_duration",
                    arg_path + ".min_duration must be greater than zero.",
                    c.value("min_duration", Json("1us")));
            }
        } else if (type == "unknown_xz") {
            if (c.size() != 1) {
                return invalid_signal_anomaly_inspect_checks(
                    arg_path,
                    arg_path + " unknown_xz check accepts only type",
                    c);
            }
            check_unknown = true;
        } else {
            return invalid_signal_anomaly_inspect_checks(
                arg_path + ".type",
                arg_path + ".type has unsupported value \"" + type + "\"; allowed types are unknown_xz, glitch, and stuck.",
                c["type"]);
        }
    }
    if (checks.empty()) {
        check_unknown = true;
        check_stuck = true;
        parse_user_time("1us", false, stuck_duration, error);
        if (!error.empty()) return Json();
    }
    int max_findings = args.value("line_limit", 50);
    Json findings = Json::array();
    Json scan_status = Json::array();
    int finding_count = 0;
    bool analysis_complete = true;
    auto add_finding = [&](const Json& finding, int& signal_finding_count) {
        ++finding_count;
        ++signal_finding_count;
        if (max_findings < 0 || static_cast<int>(findings.size()) < max_findings)
            findings.push_back(finding);
    };
    for (const auto& s : args["signals"]) {
        if (!s.is_string() || s.get<std::string>().empty()) {
            error = "signal.anomaly.inspect args.signals entries must be non-empty signal paths";
            return Json();
        }
        std::string signal = s.get<std::string>();
        fsdbTimeValPairVec_t changes;
        std::string signal_error;
        if (!read_signal_changes(signal, begin, end, npiFsdbBinStrVal, changes, signal_error)) {
            analysis_complete = false;
            scan_status.push_back({{"signal", signal}, {"status", "error"},
                                   {"analysis_complete", false}, {"message", signal_error}});
            continue;
        }
        int signal_finding_count = 0;
        for (size_t i = 0; i < changes.size(); ++i) {
            if (check_unknown && contains_xz_value(changes[i].second)) {
                add_finding({{"type", "unknown_xz"}, {"signal", signal}, {"severity", "warning"},
                             {"time", format_time(changes[i].first)},
                             {"value", wave_value_json(
                                 changes[i].second, 'b', signal)}},
                            signal_finding_count);
            }
            if (check_glitch && i + 1 < changes.size()) {
                npiFsdbTime width = changes[i + 1].first >= changes[i].first ? changes[i + 1].first - changes[i].first : 0;
                if (width > 0 && width < glitch_width) {
                    add_finding({{"type", "glitch"}, {"signal", signal}, {"severity", "info"},
                                 {"time", format_time(changes[i].first)}, {"pulse_width", format_time(width)}},
                                signal_finding_count);
                }
            }
            if (check_stuck && i + 1 < changes.size()) {
                npiFsdbTime width = changes[i + 1].first >= changes[i].first ? changes[i + 1].first - changes[i].first : 0;
                if (width >= stuck_duration) {
                    add_finding({{"type", "stuck"}, {"signal", signal}, {"severity", "warning"},
                                 {"begin", format_time(changes[i].first)}, {"end", format_time(changes[i + 1].first)},
                                 {"duration", format_time(width)},
                                 {"value", wave_value_json(
                                     changes[i].second, 'b', signal)}},
                                signal_finding_count);
                }
            }
        }
        if (check_stuck && !changes.empty() && end >= changes.back().first &&
            end - changes.back().first >= stuck_duration) {
            npiFsdbTime width = end - changes.back().first;
            add_finding({{"type", "stuck"}, {"signal", signal}, {"severity", "warning"},
                         {"begin", format_time(changes.back().first)}, {"end", format_time(end)},
                         {"duration", format_time(width)},
                         {"value", wave_value_json(
                             changes.back().second, 'b', signal)},
                         {"open_at_window_end", true}}, signal_finding_count);
        }
        scan_status.push_back({{"signal", signal}, {"status", "ok"},
                               {"analysis_complete", true}, {"change_row_count", changes.size()},
                               {"finding_count", signal_finding_count},
                               {"no_finding_reason", signal_finding_count == 0
                                   ? Json("no configured rule matched in the requested window") : Json(nullptr)}});
    }
    const bool response_truncated = max_findings >= 0 && finding_count > max_findings;
    Json data;
    data["summary"] = {
        {"signal_count", scan_status.size()},
        {"checks", checks},
        {"glitch_threshold", check_glitch ? Json(format_time(glitch_width)) : Json(nullptr)},
        {"stuck_threshold", check_stuck ? Json(format_time(stuck_duration)) : Json(nullptr)}
    };
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_signals");
    if (response_truncated) truncation_scopes.push_back("response_findings");
    xdebug_core::set_completeness(
        data["summary"],
        analysis_complete,
        analysis_complete,
        response_truncated,
        static_cast<std::size_t>(finding_count),
        findings.size(),
        truncation_scopes);
    data["findings"] = findings;
    data["scan_status"] = scan_status;
    return data;
}


}  // namespace xdebug_waveform
