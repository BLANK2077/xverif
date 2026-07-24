#include "../server_internal.h"
#include "../../common/expression.h"
#include "../../value/logic_value.h"

namespace xdebug_waveform {

bool clock_sample_from_args(const Json& args, ClockSampleSpec& spec, std::string& error) {
    static const char* legacy[] = {"clk", "sampling", "clock_edge", "posedge", "sample_offset", nullptr};
    for (int i = 0; legacy[i]; ++i) {
        if (args.contains(legacy[i])) {
            error = std::string("invalid legacy clock sampling field args.") + legacy[i] +
                    "; use args.clock, args.edge, and args.sample_point";
            return false;
        }
    }
    spec = ClockSampleSpec();
    spec.clock = args.value("clock", std::string());
    if (!parse_clock_edge_kind(args.value("edge", std::string("negedge")), spec.edge, error)) {
        return false;
    }
    if (args.contains("sample_point")) {
        if (!args["sample_point"].is_string()) {
            error = "args.sample_point must be a string: before or after";
            return false;
        }
        spec.has_sample_point = true;
        if (!parse_clock_sample_point_kind(args["sample_point"].get<std::string>(),
                                           spec.sample_point,
                                           error)) {
            return false;
        }
    }
    if (!normalize_clock_sample_spec(g_fsdb_file, spec, error)) {
        return false;
    }
    return true;
}

bool read_signal_changes(const std::string& signal,
                                npiFsdbTime begin,
                                npiFsdbTime end,
                                npiFsdbValType fmt,
                                fsdbTimeValPairVec_t& changes,
                                std::string& error,
                                int max_changes,
                                bool* truncated) {
    changes.clear();
    if (truncated) *truncated = false;
    npiFsdbSigHandle sig = npi_fsdb_sig_by_name(g_fsdb_file, signal.c_str(), NULL);
    if (!sig) {
        error = "Signal not found: " + signal;
        return false;
    }
    TimeBasedVcIterGuard guard;
    npiFsdbTimeBasedVcIter& iter = guard.iter();
    iter.add(sig);
    guard.start(begin, end);
    npiFsdbTime t = 0;
    npiFsdbSigHandle changed_sig = nullptr;
    while (iter.iter_next(t, changed_sig) > 0) {
        if (max_changes >= 0 && static_cast<int>(changes.size()) >= max_changes) {
            if (truncated) *truncated = true;
            break;
        }
        npiFsdbValue val;
        val.format = fmt;
        std::string value;
        if (!iter.get_value(val) || !val.value.str) continue;
        value = val.value.str;
        changes.push_back(std::make_pair(t, value));
    }
    return true;
}

Json changes_to_json(const fsdbTimeValPairVec_t& changes,
                     char prefix,
                     const std::string& signal,
                     int limit,
                     bool& truncated) {
    Json arr = Json::array();
    truncated = false;
    for (size_t i = 0; i < changes.size(); ++i) {
        if (limit >= 0 && static_cast<int>(arr.size()) >= limit) {
            truncated = true;
            break;
        }
        Json item;
        item["time"] = format_time(changes[i].first);
        item["value"] = wave_value_json(changes[i].second, prefix, signal);
        arr.push_back(item);
    }
    return arr;
}

bool build_signal_alias_handles(const Json& signals,
                                       std::vector<std::string>& aliases,
                                       std::vector<std::string>& paths,
                                       fsdbSigVec_t& handles,
                                       std::string& error) {
    if (!signals.is_object()) {
        error = "signals must be an object";
        return false;
    }
    std::map<std::string, std::string> seen;
    for (auto it = signals.begin(); it != signals.end(); ++it) {
        if (!it.value().is_string()) {
            error = "signal path must be string for alias: " + it.key();
            return false;
        }
        std::string alias = it.key();
        std::string path = it.value().get<std::string>();
        auto prev = seen.find(alias);
        if (prev != seen.end() && prev->second != path) {
            error = "alias maps to different signals: " + alias;
            return false;
        }
        if (prev != seen.end()) continue;
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(g_fsdb_file, path.c_str(), NULL);
        if (!sig) {
            error = "Signal not found: " + path;
            return false;
        }
        seen[alias] = path;
        aliases.push_back(alias);
        paths.push_back(path);
        handles.push_back(sig);
    }
    return true;
}

namespace {

std::string trim_copy(const std::string& text) {
    size_t begin = 0;
    while (begin < text.size() && std::isspace(static_cast<unsigned char>(text[begin]))) ++begin;
    size_t end = text.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return text.substr(begin, end - begin);
}

std::string bit_string_from_value(const std::string& value) {
    std::string bits = xdebug_waveform::expr_bits_only(value);
    for (char& c : bits) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return bits;
}

Json bit_value_json(const std::string& bits, int width) {
    return logic_value_json(
        logic_value_from_fsdb_raw(bits, 'b', width));
}

std::string pad_bits_for_compare(const std::string& bits, size_t width) {
    if (bits.size() >= width) return bits;
    return std::string(width - bits.size(), '0') + bits;
}

int compare_bit_strings(const std::string& lhs, const std::string& rhs) {
    size_t width = std::max(lhs.size(), rhs.size());
    std::string a = pad_bits_for_compare(lhs, width);
    std::string b = pad_bits_for_compare(rhs, width);
    if (a == b) return 0;
    return a < b ? -1 : 1;
}

bool bits_to_u64(const std::string& bits, uint64_t& out, std::string& error) {
    if (bits.empty()) {
        error = "INVALID_REQUEST: counter value is empty";
        return false;
    }
    if (bits.size() > 64) {
        error = "INVALID_REQUEST: counter width exceeds 64 bits";
        return false;
    }
    if (xdebug_waveform::expr_value_has_unknown(bits)) {
        return false;
    }
    uint64_t value = 0;
    for (char c : bits) {
        if (c != '0' && c != '1') {
            error = "INVALID_REQUEST: counter value contains non-binary data";
            return false;
        }
        value = (value << 1) | (c == '1' ? 1ULL : 0ULL);
    }
    out = value;
    return true;
}

std::string u64_to_decimal(uint64_t value) {
    std::ostringstream oss;
    oss << value;
    return oss.str();
}

std::string long_double_to_decimal(long double value) {
    std::ostringstream oss;
    oss.setf(std::ios::fixed);
    oss.precision(6);
    oss << static_cast<double>(value);
    std::string text = oss.str();
    while (text.size() > 1 && text.back() == '0') text.pop_back();
    if (!text.empty() && text.back() == '.') text.pop_back();
    return text;
}

bool add_signal_alias(Json& signals,
                      const std::string& alias,
                      const std::string& path,
                      std::string& error) {
    if (path.empty()) {
        error = "INVALID_REQUEST: signal path must not be empty";
        return false;
    }
    if (signals.contains(alias) && signals[alias].get<std::string>() != path) {
        error = "INVALID_REQUEST: duplicate alias maps to different signals: " + alias;
        return false;
    }
    signals[alias] = path;
    return true;
}

struct CounterInput {
    std::string expr;
    std::vector<std::string> aliases;
    std::vector<std::string> paths;
};

bool parse_counter_concat(const std::string& text,
                          CounterInput& out,
                          std::string& error) {
    std::string trimmed = trim_copy(text);
    if (trimmed.empty()) {
        error = "INVALID_REQUEST: counter.statistics requires non-empty args.cnt";
        return false;
    }
    if (trimmed.front() != '{') {
        out.aliases.push_back("__cnt0");
        out.paths.push_back(trimmed);
        return true;
    }
    if (trimmed.size() < 3 || trimmed.back() != '}') {
        error = "INVALID_REQUEST: counter concat must be {signal[,signal...]}";
        return false;
    }
    std::string body = trimmed.substr(1, trimmed.size() - 2);
    size_t start = 0;
    int index = 0;
    while (start <= body.size()) {
        size_t comma = body.find(',', start);
        std::string part = trim_copy(body.substr(start, comma == std::string::npos ? std::string::npos : comma - start));
        if (part.empty() || part.find('{') != std::string::npos || part.find('}') != std::string::npos ||
            part.find('\'') != std::string::npos) {
            error = "INVALID_REQUEST: counter concat supports signal paths only";
            return false;
        }
        out.aliases.push_back("__cnt" + std::to_string(index++));
        out.paths.push_back(part);
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return !out.paths.empty();
}

bool build_counter_inputs(const Json& args,
                          Json& signal_union,
                          std::string& valid_expr,
                          CounterInput& counter,
                          std::string& error) {
    if (!args.contains("vld")) {
        error = "MISSING_FIELD: counter.statistics requires args.vld";
        return false;
    }
    if (!args.contains("cnt")) {
        error = "MISSING_FIELD: counter.statistics requires args.cnt";
        return false;
    }

    const Json& vld = args["vld"];
    if (vld.is_string()) {
        valid_expr = "__vld";
        if (!add_signal_alias(signal_union, "__vld", vld.get<std::string>(), error)) return false;
    } else if (vld.is_object()) {
        valid_expr = server_compact_expr_ws(vld.value("expr", std::string()));
        if (valid_expr.empty() || !vld.contains("signals") || !vld["signals"].is_object()) {
            error = "INVALID_REQUEST: object args.vld requires expr and signals";
            return false;
        }
        for (auto it = vld["signals"].begin(); it != vld["signals"].end(); ++it) {
            if (!it.value().is_string()) {
                error = "INVALID_REQUEST: args.vld.signals values must be string paths";
                return false;
            }
            if (!add_signal_alias(signal_union, it.key(), it.value().get<std::string>(), error)) return false;
        }
    } else {
        error = "INVALID_REQUEST: args.vld must be a signal path or expression object";
        return false;
    }

    if (!args["cnt"].is_string()) {
        error = "INVALID_REQUEST: counter.statistics args.cnt must be a signal path or concat string";
        return false;
    }
    if (!parse_counter_concat(args["cnt"].get<std::string>(), counter, error)) return false;
    for (size_t i = 0; i < counter.aliases.size(); ++i) {
        if (!add_signal_alias(signal_union, counter.aliases[i], counter.paths[i], error)) return false;
    }
    return true;
}

std::string counter_bits_from_values(const CounterInput& counter,
                                     const std::map<std::string, std::string>& values) {
    std::string bits;
    for (const auto& alias : counter.aliases) {
        auto it = values.find(alias);
        if (it == values.end()) return "";
        bits += bit_string_from_value(it->second);
    }
    return bits;
}

bool validate_expression_alias_contract(const std::string& expr, std::string& error) {
    Expression parsed;
    std::string parse_error;
    if (!parsed.parse(expr, parse_error)) {
        error = parse_error;
        return false;
    }
    std::vector<std::string> bad_aliases =
        expression_aliases_that_look_like_paths(parsed.aliases());
    if (!bad_aliases.empty()) {
        error = "expression operands must be aliases, not direct signal paths: " +
                bad_aliases.front() +
                "; put real signal paths in args.signals";
        return false;
    }
    return true;
}

} // namespace

Json ai_signal_changes(const Json& args, std::string& error) {
    std::string signal = args.value("signal", std::string());
    if (signal.empty()) {
        error = "signal.changes requires args.signal";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    int limit = args.value("line_limit", 1000);
    std::string mode = args.value("mode", std::string("head"));
    bool aggregate_only = args.value("aggregate_only", false);
    npiFsdbValType fmt = json_value_format(args);
    fsdbTimeValPairVec_t changes;
    bool truncated = false;
    if (!read_signal_changes(signal, begin, end, fmt, changes, error, -1, &truncated)) return Json();
    const size_t total_rows = changes.size();
    const bool includes_initial = total_rows > 0;
    const size_t actual_transitions = includes_initial ? total_rows - 1 : 0;
    fsdbTimeValPairVec_t selected = changes;
    bool response_truncated = false;
    if (!aggregate_only && limit >= 0 && selected.size() > static_cast<size_t>(limit)) {
        response_truncated = true;
        if (mode == "tail") selected.erase(selected.begin(), selected.end() - limit);
        else selected.erase(selected.begin() + limit, selected.end());
    }
    Json data;
    data["summary"] = {
        {"signal", signal},
        {"total_change_rows", static_cast<int>(total_rows)},
        {"returned_change_rows", aggregate_only ? 0 : static_cast<int>(selected.size())},
        {"actual_transition_count", static_cast<int>(actual_transitions)},
        {"analysis_complete", !truncated},
        {"truncated", response_truncated || truncated},
        {"truncation_scope", truncated ? "analysis_samples" :
                              response_truncated ? "response_rows" : "none"}
    };
    data["begin"] = format_time(begin);
    data["end"] = format_time(end);
    data["includes_initial_value"] = includes_initial;
    data["semantic_note"] = "signal.changes returns value-change rows for timeline inspection. Do not use row counts as sampled high cycles; use signal.statistics.high_cycles for clock-sampled activity.";
    if (!changes.empty()) {
        data["initial_value"] = wave_value_json(
            changes.front().second, json_value_prefix(fmt), signal);
        data["final_value"] = wave_value_json(
            changes.back().second, json_value_prefix(fmt), signal);
        data["first_change"] = format_time(changes.front().first);
        data["last_change"] = format_time(changes.back().first);
    }
    if (!aggregate_only) {
        data["mode"] = mode == "tail" ? "tail" : "head";
        bool rows_truncated = false;
        data["changes"] = changes_to_json(
            selected, json_value_prefix(fmt), signal, -1, rows_truncated);
    }
    return data;
}

Json ai_signal_stability(const Json& args, std::string& error) {
    std::string signal = args.value("signal", std::string());
    if (signal.empty()) {
        error = "signal.stability requires args.signal";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    npiFsdbValType fmt = json_value_format(args);
    npiFsdbSigHandle sig = npi_fsdb_sig_by_name(g_fsdb_file, signal.c_str(), NULL);
    if (!sig) {
        error = "Signal not found: " + signal;
        return Json();
    }
    Json arr = Json::array();
    bool stable = true;
    std::string first;
    TimeBasedVcIterGuard guard;
    npiFsdbTimeBasedVcIter& iter = guard.iter();
    iter.add(sig);
    guard.start(begin, end);
    npiFsdbTime change_time = 0;
    npiFsdbSigHandle changed_sig = nullptr;
    while (iter.iter_next(change_time, changed_sig) > 0) {
        npiFsdbValue val;
        val.format = fmt;
        if (!iter.get_value(val) || !val.value.str) continue;
        std::string text = value_with_prefix(val.value.str, json_value_prefix(fmt));
        Json item;
        item["time"] = format_time(change_time);
        item["value"] = wave_value_json(
            val.value.str, json_value_prefix(fmt), signal);
        arr.push_back(item);
        if (first.empty()) {
            first = text;
        } else if (text != first) {
            stable = false;
            break;
        }
    }

    Json data;
    data["begin"] = format_time(begin);
    data["end"] = format_time(end);
    data["changes"] = arr;
    const size_t change_row_count = arr.size();
    const size_t actual_transition_count = stable ? 0 : 1;
    Json summary = {
        {"signal", signal}, {"stable", stable},
        {"change_row_count", static_cast<int>(change_row_count)},
        {"actual_transition_count", static_cast<int>(actual_transition_count)},
        {"analysis_complete", true},
        {"scan_stopped_on_first_transition", !stable}
    };
    if (stable && !arr.empty()) summary["value"] = arr[0]["value"];
    data["summary"] = summary;
    data["includes_initial_value"] = change_row_count > 0;
    if (!arr.empty()) {
        data["initial_value"] = arr[0]["value"];
        data["final_value"] = arr[arr.size() - 1]["value"];
        data["first_change"] = arr[0]["time"];
        data["last_change"] = arr[arr.size() - 1]["time"];
    }
    if (!stable) {
        for (const auto& item : arr) {
            if (item["value"]["value"].get<std::string>() != first) {
                data["first_change_time"] = item["time"];
                break;
            }
        }
    }
    return data;
}

Json ai_signal_xz_verify(const Json& args, std::string& error) {
    const std::string signal = args.value("signal", std::string());
    const std::string expected_state = args.value("expected_state", std::string());
    const std::string match_mode = args.value("match_mode", std::string("exact"));
    if (signal.empty() || expected_state.empty()) {
        error = "INVALID_REQUEST: signal.xz_verify requires args.signal and args.expected_state";
        return Json();
    }
    if (expected_state != "x" && expected_state != "z") {
        error = "INVALID_REQUEST: args.expected_state must be x or z";
        return Json();
    }
    if (match_mode != "exact" && match_mode != "contains") {
        error = "INVALID_REQUEST: args.match_mode must be exact or contains";
        return Json();
    }

    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    npiFsdbSigHandle sig = npi_fsdb_sig_by_name(g_fsdb_file, signal.c_str(), nullptr);
    if (!sig) {
        error = "Signal not found: " + signal;
        return Json();
    }

    const char expected_bit = expected_state[0];
    bool always_matched = true;
    bool have_value = false;
    int checked_value_count = 0;
    Json initial_value = nullptr;
    Json first_mismatch = nullptr;
    TimeBasedVcIterGuard guard;
    npiFsdbTimeBasedVcIter& iter = guard.iter();
    iter.add(sig);
    guard.start(begin, end);
    npiFsdbTime sample_time = 0;
    npiFsdbSigHandle changed_sig = nullptr;
    while (iter.iter_next(sample_time, changed_sig) > 0) {
        npiFsdbValue raw;
        raw.format = npiFsdbBinStrVal;
        if (!iter.get_value(raw) || !raw.value.str) continue;
        LogicValue value = logic_value_from_fsdb_signal(sig, raw.value.str, 'b');
        if (!value.valid || value.bits.empty()) continue;
        Json value_json = logic_value_json(value);
        if (!have_value) {
            initial_value = value_json;
            have_value = true;
        }
        ++checked_value_count;
        const bool matched = match_mode == "exact"
            ? std::all_of(value.bits.begin(), value.bits.end(),
                          [expected_bit](char bit) { return bit == expected_bit; })
            : value.bits.find(expected_bit) != std::string::npos;
        if (!matched) {
            always_matched = false;
            first_mismatch = {
                {"sample_time", format_time(sample_time)},
                {"value", value_json}
            };
            break;
        }
    }
    if (!have_value) {
        error = "VALUE_NOT_AVAILABLE: no waveform value is available for signal " +
                signal + " in the requested window";
        return Json();
    }

    Json data;
    data["summary"] = {
        {"signal", signal},
        {"expected_state", expected_state},
        {"match_mode", match_mode},
        {"verdict", always_matched ? "pass" : "fail"},
        {"always_matched", always_matched},
        {"analysis_complete", true},
        {"scan_complete", always_matched},
        {"checked_value_count", checked_value_count},
        {"stop_reason", always_matched ? "window_end" : "first_mismatch"}
    };
    data["time_range"] = {
        {"begin", format_time(begin)},
        {"end", format_time(end)}
    };
    data["initial_value"] = initial_value;
    data["first_mismatch"] = first_mismatch;
    data["sample_time_semantics"] =
        "sample_time is the finalized raw waveform value-change time in the closed interval";
    return data;
}

Json ai_expr_eval_at(const Json& args, std::string& error) {
    std::string time_s = args.value("at", args.value("time", std::string()));
    std::string expr = server_compact_expr_ws(args.value("expr", std::string()));
    if (time_s.empty() || expr.empty() || !args.contains("signals")) {
        error = "expr.eval_at requires args.time/args.at, args.expr and args.signals";
        return Json();
    }
    if (!validate_expression_alias_contract(expr, error)) return Json();
    ClockSampleSpec clock_sample;
    if (!clock_sample_from_args(args, clock_sample, error)) return Json();
    npiFsdbTime t = 0;
    if (!parse_user_time(time_s.c_str(), false, t, error)) return Json();
    std::vector<std::string> aliases, paths;
    fsdbSigVec_t handles;
    if (!build_signal_alias_handles(args["signals"], aliases, paths, handles, error)) return Json();

    std::vector<ClockPointSignal> point_signals;
    for (size_t i = 0; i < aliases.size(); ++i) {
        point_signals.push_back({aliases[i], paths[i], handles[i]});
    }
    ClockPointResult point_result;
    ClockPointSampler sampler(g_fsdb_file, clock_sample);
    std::string sampler_error;
    if (!sampler.sample(t, point_signals, npiFsdbBinStrVal, 'b', point_result, sampler_error)) {
        error = sampler_error;
        return Json();
    }

    auto eval_cells = [&](const char* column, Json& operands, ExprTri& result, bool required) -> bool {
        std::map<std::string, std::string> value_map;
        operands = Json::array();
        for (size_t i = 0; i < point_result.rows.size(); ++i) {
            const ClockPointCell* cell = &point_result.rows[i].middle;
            if (std::string(column) == "before") cell = &point_result.rows[i].before;
            else if (std::string(column) == "after") cell = &point_result.rows[i].after;
            if (cell->status != "ok") {
                if (required) error = "Failed to read expression operand: " + paths[i];
                return false;
            }
            value_map[aliases[i]] = cell->raw_value;
            operands.push_back({{"alias", aliases[i]},
                                {"signal", paths[i]},
                                {"value", wave_value_json(
                                    cell->raw_value, 'b', paths[i])}});
        }
        if (!xdebug_waveform::eval_event_expression(expr, value_map, result, error)) return false;
        return true;
    };

    Json operands;
    ExprTri result = ExprTri::Unknown;
    if (!eval_cells("middle", operands, result, true)) return Json();
    Json before_operands = Json::array(), after_operands = Json::array();
    ExprTri before_result = ExprTri::Unknown, after_result = ExprTri::Unknown;
    bool have_before_result = point_result.context.has_previous_sample_time &&
        eval_cells("before", before_operands, before_result, false);
    if (!have_before_result && !error.empty()) return Json();
    bool have_after_result = point_result.context.has_next_sample_time &&
        eval_cells("after", after_operands, after_result, false);
    if (!have_after_result && !error.empty()) return Json();
    Json data;
    data["summary"] = {
        {"expr", expr},
        {"time", format_time(t)},
        {"status", xdebug_waveform::expr_tri_text(result)},
        {"known", result != ExprTri::Unknown},
        {"requested_any_edge_hit", point_result.context.clock_edge_hit},
        {"requested_target_edge_hit", point_result.context.target_edge_hit},
        {"bracket_complete", point_result.context.bracket_complete}
    };
    data["expr_value"] = result == ExprTri::True ? Json(true) : result == ExprTri::False ? Json(false) : Json(nullptr);
    data["operands"] = operands;
    data["clock_context"] = {
        {"clock", clock_sample.clock},
        {"edge", clock_edge_kind_text(clock_sample.edge)},
        {"requested_time", format_time(t)},
        {"requested_any_edge_hit", point_result.context.clock_edge_hit},
        {"clock_edge_kind", point_result.context.has_clock_edge_kind
            ? Json(clock_edge_kind_text(point_result.context.clock_edge_kind)) : Json(nullptr)},
        {"requested_target_edge_hit", point_result.context.target_edge_hit},
        {"sample_point_applied", point_result.context.target_edge_hit && clock_sample.edge != ClockEdgeKind::Negedge
            ? Json(clock_sample_point_text(clock_sample.sample_point)) : Json(nullptr)},
        {"previous_sample_time", point_result.context.has_previous_sample_time
            ? Json(format_time(point_result.context.previous_sample_time)) : Json(nullptr)},
        {"next_sample_time", point_result.context.has_next_sample_time
            ? Json(format_time(point_result.context.next_sample_time)) : Json(nullptr)},
        {"bracket_complete", point_result.context.bracket_complete}
    };
    data["expr_samples"] = {
        {"before", have_before_result ? Json(expr_tri_text(before_result)) : Json("missing_edge")},
        {"middle", expr_tri_text(result)},
        {"after", have_after_result ? Json(expr_tri_text(after_result)) : Json("missing_edge")}
    };
    return data;
}

Json ai_window_verify(const Json& args, std::string& error) {
    ClockSampleSpec clock_sample;
    if (!clock_sample_from_args(args, clock_sample, error)) return Json();
    std::string clock = clock_sample.clock;
    if (clock.empty() || !args.contains("conditions") || !args["conditions"].is_array()) {
        error = "window.verify requires args.clock and args.conditions[]";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    const int evidence_limit = args.value("line_limit", 100);
    const int max_samples = args.value("max_samples", -1);

    if (!args.contains("signals") || !args["signals"].is_object()) {
        error = "window.verify requires args.signals as alias-to-signal-path object";
        return Json();
    }
    Json signal_union = args["signals"];
    for (const auto& cond : args["conditions"]) {
        if (!cond.contains("expr") || !cond["expr"].is_string()) {
            error = "each condition requires string expr";
            return Json();
        }
        std::string cond_expr = server_compact_expr_ws(cond.value("expr", std::string()));
        if (!validate_expression_alias_contract(cond_expr, error)) return Json();
    }
    std::vector<std::string> aliases, paths;
    fsdbSigVec_t handles;
    if (!build_signal_alias_handles(signal_union, aliases, paths, handles, error)) return Json();
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < aliases.size(); ++i) {
        sample_signals.push_back({aliases[i], paths[i], handles[i]});
    }
    struct CondState { std::string expr; std::string mode; int pass = 0; int fail = 0; int unknown = 0; };
    std::vector<CondState> states;
    for (const auto& cond : args["conditions"]) {
        CondState st;
        st.expr = server_compact_expr_ws(cond.value("expr", std::string()));
        st.mode = cond.value("mode", std::string("always"));
        states.push_back(st);
    }

    int samples = 0;
    bool truncated = false;
    bool decisive_proof = false;
    Json findings = Json::array();
    int finding_count = 0;
    bool have_sample = false;
    npiFsdbTime first_sample_time = 0;
    npiFsdbTime last_sample_time = 0;
    ClockSampleScanner scanner(g_fsdb_file, clock_sample);
    bool ok = scanner.scan(sample_signals, begin, end, npiFsdbBinStrVal, 'b', max_samples,
        [&](const ClockSample& sample) -> bool {
            if (!have_sample) {
                first_sample_time = sample.time;
                have_sample = true;
            }
            last_sample_time = sample.time;
            std::map<std::string, std::string> values = clock_sample_value_map(sample_signals, sample.values);
            bool has_eventually = false;
            bool all_eventually_seen = true;
            for (auto& st : states) {
                ExprTri r = ExprTri::Unknown;
                std::string eval_error;
                if (!xdebug_waveform::eval_event_expression(st.expr, values, r, eval_error)) {
                    error = eval_error;
                    return false;
                }
                bool pass = false;
                if (st.mode == "eventually") pass = (r == ExprTri::True);
                else if (st.mode == "never") pass = (r == ExprTri::False);
                else pass = (r == ExprTri::True);
                if (r == ExprTri::Unknown) st.unknown++;
                else if (pass) st.pass++;
                else st.fail++;
                if (r == ExprTri::Unknown || !pass) {
                    ++finding_count;
                    if (evidence_limit < 0 || static_cast<int>(findings.size()) < evidence_limit) {
                        findings.push_back({{"time", format_time(sample.time)},
                                            {"expr", st.expr}, {"mode", st.mode},
                                            {"status", r == ExprTri::Unknown ? "unknown" : "fail"},
                                            {"signals", values}});
                    }
                }
                if (st.mode == "eventually") {
                    has_eventually = true;
                    if (st.pass == 0) all_eventually_seen = false;
                } else if (r == ExprTri::Unknown || !pass) {
                    decisive_proof = true;
                    return false;
                }
            }
            if (has_eventually && all_eventually_seen) {
                decisive_proof = true;
                return false;
            }
            return true;
        }, error, samples, truncated);
    if (!ok) return Json();

    Json conds = Json::array();
    bool all_passed = true;
    int failed_samples = 0, unknown_samples = 0;
    for (const auto& st : states) {
        bool passed = false;
        if (st.mode == "eventually") passed = st.pass > 0;
        else passed = st.fail == 0 && st.unknown == 0;
        if (!passed) all_passed = false;
        failed_samples += st.fail;
        unknown_samples += st.unknown;
        conds.push_back({{"expr", st.expr}, {"mode", st.mode}, {"passed", passed},
                         {"pass_samples", st.pass}, {"failed_samples", st.fail}, {"unknown_samples", st.unknown}});
    }
    const bool scan_complete = !truncated;
    const bool validation_complete = decisive_proof || scan_complete;
    const bool response_truncated = evidence_limit >= 0 && finding_count > evidence_limit;
    const std::string verdict = !validation_complete ? "inconclusive" :
                                all_passed ? "pass" : "fail";
    Json data;
    data["summary"] = {
        {"execution_ok", true},
        {"verdict", verdict},
        {"all_passed", validation_complete ? Json(all_passed) : Json(nullptr)},
        {"sample_count", samples},
        {"failed_samples", failed_samples},
        {"unknown_samples", unknown_samples},
        {"scan_complete", scan_complete},
        {"response_truncated", response_truncated},
        {"truncated", truncated || response_truncated},
        {"validation_complete", validation_complete},
        {"proof_begin", format_time(begin)},
        {"proof_end", format_time(end)},
        {"scanned_range", {{"begin", have_sample ? Json(format_time(first_sample_time)) : Json(nullptr)},
                            {"end", have_sample ? Json(format_time(last_sample_time)) : Json(nullptr)}}},
        {"truncation_scopes", Json::array()},
        {"stop_reason", decisive_proof ? Json("decisive_result") :
                         truncated ? Json("max_samples") : Json("window_end")},
        {"sampling_mode", "clock_edge"},
        {"clock", clock_sample.clock},
        {"edge", clock_edge_kind_text(clock_sample.edge)},
        {"sample_time_semantics", "time is sample_time"}
    };
    if (truncated) data["summary"]["truncation_scopes"].push_back("analysis_samples");
    if (response_truncated) data["summary"]["truncation_scopes"].push_back("response_findings");
    if (clock_sample.edge != ClockEdgeKind::Negedge)
        data["summary"]["sample_point"] = clock_sample_point_text(clock_sample.sample_point);
    data["conditions"] = conds;
    data["findings"] = findings;
    data["summary"]["finding_count"] = finding_count;
    data["summary"]["returned_finding_count"] = findings.size();
    return data;
}

Json ai_signal_statistics(const Json& args, std::string& error) {
    std::string signal = args.value("signal", std::string());
    ClockSampleSpec clock_sample;
    if (!clock_sample_from_args(args, clock_sample, error)) return Json();
    std::string clock = clock_sample.clock;
    if (signal.empty()) {
        error = "signal.statistics requires args.signal";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();

    if (clock.empty()) {
        const int evidence_limit = args.value("line_limit", 100);
        npiFsdbValType fmt = json_value_format(args);
        fsdbTimeValPairVec_t changes;
        bool truncated = false;
        if (!read_signal_changes(signal, begin, end, fmt, changes, error, -1, &truncated)) return Json();
        Json data;
        data["summary"] = {{"signal", signal}, {"sampling_mode", "raw_value_changes"},
                           {"begin", format_time(begin)}, {"end", format_time(end)},
                           {"sample_count", changes.size()},
                           {"actual_transition_count", changes.empty() ? 0 : changes.size() - 1},
                           {"analysis_complete", !truncated}, {"truncated", truncated},
                           {"truncation_scope", truncated ? Json("analysis_rows") : Json(nullptr)}};
        data["returned_change_rows"] = changes.size();
        data["includes_initial_value"] = !changes.empty();
        int high_bursts = 0;
        npiFsdbTime first_high = 0, last_high = 0, last_fall = 0;
        bool prev_high = false;
        for (const auto& item : changes) {
            bool high = !contains_xz_value(item.second) && xdebug_waveform::expr_bits_only(item.second).find('1') != std::string::npos;
            if (high) {
                if (!prev_high) high_bursts++;
                if (first_high == 0) first_high = item.first;
                last_high = item.first;
            } else if (prev_high) {
                last_fall = item.first;
            }
            prev_high = high;
        }
        data["activity"] = {
            {"high_burst_count", high_bursts},
            {"first_high_time", first_high ? Json(format_time(first_high)) : Json(nullptr)},
            {"last_high_time", last_high ? Json(format_time(last_high)) : Json(nullptr)},
            {"last_fall_time", last_fall ? Json(format_time(last_fall)) : Json(nullptr)},
            {"max_high_cycles", nullptr}
        };
        if (!changes.empty()) {
            data["initial_value"] = wave_value_json(
                changes.front().second, json_value_prefix(fmt), signal);
            data["final_value"] = wave_value_json(
                changes.back().second, json_value_prefix(fmt), signal);
            data["first_change_time"] = format_time(changes.front().first);
            data["last_change_time"] = format_time(changes.back().first);
        }
        Json evidence = Json::array();
        for (size_t i = 0; i < changes.size() &&
             (evidence_limit < 0 || static_cast<int>(i) < evidence_limit); ++i) {
            evidence.push_back({{"time", format_time(changes[i].first)},
                                {"kind", i == 0 ? "initial" : "value_change"},
                                {"value", wave_value_json(
                                    changes[i].second, json_value_prefix(fmt), signal)}});
        }
        const bool response_truncated = evidence_limit >= 0 && changes.size() > static_cast<size_t>(evidence_limit);
        data["summary"]["scan_complete"] = !truncated;
        data["summary"]["response_truncated"] = response_truncated;
        data["summary"]["truncated"] = truncated || response_truncated;
        data["summary"]["truncation_scopes"] = Json::array();
        if (truncated) data["summary"]["truncation_scopes"].push_back("analysis_rows");
        if (response_truncated) data["summary"]["truncation_scopes"].push_back("response_evidence");
        data["summary"]["evidence_count"] = changes.size();
        data["summary"]["returned_evidence_count"] = evidence.size();
        data["evidence"] = evidence;
        return data;
    }

    Json signals = {{"sig", signal}};
    std::vector<std::string> aliases, paths;
    fsdbSigVec_t handles;
    if (!build_signal_alias_handles(signals, aliases, paths, handles, error)) return Json();
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < aliases.size(); ++i) {
        sample_signals.push_back({aliases[i], paths[i], handles[i]});
    }
    const FsdbSignalWidth signal_width = fsdb_signal_width(handles[0]);

    const int evidence_limit = args.value("line_limit", 100);
    const int max_samples = args.value("max_samples", -1);
    int samples = 0, known = 0, unknown = 0;
    int high_cycles = 0, low_cycles = 0;
    int high_bursts = 0, current_high = 0, max_high_cycles = 0;
    int transitions = 0;
    bool truncated = false;
    bool have_known = false;
    std::string first_bits, final_bits, min_bits, max_bits, prev_bits;
    npiFsdbTime first_change_time = 0, last_change_time = 0;
    npiFsdbTime first_high_time = 0, last_high_time = 0, last_fall_time = 0;
    bool prev_high = false;
    Json evidence = Json::array();
    int evidence_count = 0;
    auto add_evidence = [&](npiFsdbTime time, const std::string& kind, const std::string& value) {
        ++evidence_count;
        if (evidence_limit < 0 || static_cast<int>(evidence.size()) < evidence_limit)
            evidence.push_back({{"time", format_time(time)}, {"kind", kind},
                                {"value", wave_value_json(value, 'b', signal)}});
    };

    ClockSampleScanner scanner(g_fsdb_file, clock_sample);
    if (!scanner.scan(sample_signals, begin, end, npiFsdbBinStrVal, 'b', max_samples,
        [&](const ClockSample& sample) -> bool {
            npiFsdbTime t = sample.time;
            std::map<std::string, std::string> values = clock_sample_value_map(sample_signals, sample.values);
            auto it = values.find("sig");
            if (it == values.end() || contains_xz_value(it->second)) {
                unknown++;
                add_evidence(t, "unknown", it == values.end() ? std::string("'bx") : it->second);
                if (prev_high) {
                    if (current_high > max_high_cycles) max_high_cycles = current_high;
                    current_high = 0;
                    last_fall_time = t;
                    prev_high = false;
                }
                return true;
            }
            std::string bits = bit_string_from_value(it->second);
            if (bits.empty()) {
                unknown++;
                return true;
            }
            known++;
            bool nonzero = bits.find('1') != std::string::npos;
            bool high = (nonzero && bits.size() == 1);
            if (!nonzero) low_cycles++;
            else if (high) high_cycles++;
            if (high) {
                if (!prev_high) {
                    high_bursts++;
                    current_high = 0;
                    if (first_high_time == 0) first_high_time = t;
                }
                current_high++;
                last_high_time = t;
            } else if (prev_high) {
                if (current_high > max_high_cycles) max_high_cycles = current_high;
                current_high = 0;
                last_fall_time = t;
            }
            prev_high = high;
            if (!have_known) {
                first_bits = final_bits = min_bits = max_bits = prev_bits = bits;
                have_known = true;
            } else {
                if (compare_bit_strings(bits, prev_bits) != 0) {
                    transitions++;
                    add_evidence(t, "value_change", it->second);
                    if (first_change_time == 0) first_change_time = t;
                    last_change_time = t;
                }
                if (compare_bit_strings(bits, min_bits) < 0) min_bits = bits;
                if (compare_bit_strings(bits, max_bits) > 0) max_bits = bits;
                prev_bits = final_bits = bits;
            }
            return true;
        }, error, samples, truncated)) return Json();
    if (prev_high && current_high > max_high_cycles) max_high_cycles = current_high;

    Json data;
    data["summary"] = {
        {"signal", signal},
        {"sampling_mode", "clock_edge"},
        {"clock", clock},
        {"edge", clock_edge_kind_text(clock_sample.edge)},
        {"sample_time_semantics", "time is sample_time"},
        {"sample_count", samples},
        {"known_count", known},
        {"unknown_count", unknown},
        {"begin", format_time(begin)},
        {"end", format_time(end)},
        {"scan_complete", !truncated},
        {"analysis_complete", !truncated},
        {"response_truncated", evidence_limit >= 0 && evidence_count > evidence_limit},
        {"truncated", truncated || (evidence_limit >= 0 && evidence_count > evidence_limit)},
        {"truncation_scopes", Json::array()}
    };
    if (truncated) data["summary"]["truncation_scopes"].push_back("analysis_samples");
    if (evidence_limit >= 0 && evidence_count > evidence_limit)
        data["summary"]["truncation_scopes"].push_back("response_evidence");
    data["summary"]["evidence_count"] = evidence_count;
    data["summary"]["returned_evidence_count"] = evidence.size();
    data["evidence"] = evidence;
    if (clock_sample.edge != ClockEdgeKind::Negedge)
        data["summary"]["sample_point"] = clock_sample_point_text(clock_sample.sample_point);
    data["transition_count"] = transitions;
    if (have_known) {
        const int width = signal_width.reliable ? signal_width.width : 0;
        data["first"] = bit_value_json(first_bits, width);
        data["final"] = bit_value_json(final_bits, width);
        data["min"] = bit_value_json(min_bits, width);
        data["max"] = bit_value_json(max_bits, width);
        data["low_cycles"] = low_cycles;
        data["high_cycles"] = high_cycles;
        data["high_ratio"] = known > 0 ? static_cast<double>(high_cycles) / static_cast<double>(known) : 0.0;
        if (first_change_time != 0) data["first_change_time"] = format_time(first_change_time);
        if (last_change_time != 0) data["last_change_time"] = format_time(last_change_time);
        data["activity"] = {
            {"high_burst_count", high_bursts},
            {"first_high_time", first_high_time ? Json(format_time(first_high_time)) : Json(nullptr)},
            {"last_high_time", last_high_time ? Json(format_time(last_high_time)) : Json(nullptr)},
            {"last_fall_time", last_fall_time ? Json(format_time(last_fall_time)) : Json(nullptr)},
            {"max_high_cycles", max_high_cycles}
        };
    }
    return data;
}

Json ai_counter_statistics(const Json& args, std::string& error) {
    ClockSampleSpec clock_sample;
    if (!clock_sample_from_args(args, clock_sample, error)) return Json();
    std::string clock = clock_sample.clock;
    if (clock.empty()) {
        error = "MISSING_FIELD: counter.statistics requires args.clock";
        return Json();
    }
    if (!args.contains("time_range") && !args.contains("begin") && !args.contains("end") &&
        !args.contains("from") && !args.contains("to") && !args.contains("around")) {
        error = "MISSING_FIELD: counter.statistics requires args.time_range";
        return Json();
    }

    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();

    Json signal_union = Json::object();
    std::string valid_expr;
    CounterInput counter;
    if (!build_counter_inputs(args, signal_union, valid_expr, counter, error)) return Json();

    std::vector<std::string> aliases, paths;
    fsdbSigVec_t handles;
    if (!build_signal_alias_handles(signal_union, aliases, paths, handles, error)) return Json();
    std::vector<ClockSampleSignal> sample_signals;
    for (size_t i = 0; i < aliases.size(); ++i) {
        sample_signals.push_back({aliases[i], paths[i], handles[i]});
    }

    const int evidence_limit = args.value("line_limit", 100);
    const int max_samples = args.value("max_samples", -1);
    int samples = 0;
    bool truncated = false;
    int valid_count = 0, valid_false_count = 0, unknown_count = 0;
    bool have_value = false;
    uint64_t min_value = 0, max_value = 0;
    int min_count = 0, max_count = 0;
    npiFsdbTime min_first_time = 0, max_first_time = 0;
    long double sum = 0.0;
    Json evidence = Json::array();
    int evidence_count = 0;
    bool have_previous_value = false;
    uint64_t previous_value = 0;
    auto add_evidence = [&](npiFsdbTime time, const std::string& kind, const Json& value) {
        ++evidence_count;
        if (evidence_limit < 0 || static_cast<int>(evidence.size()) < evidence_limit)
            evidence.push_back({{"time", format_time(time)}, {"kind", kind}, {"value", value}});
    };

    ClockSampleScanner scanner(g_fsdb_file, clock_sample);
    if (!scanner.scan(sample_signals, begin, end, npiFsdbBinStrVal, 'b', max_samples,
        [&](const ClockSample& sample) -> bool {
            npiFsdbTime t = sample.time;
            std::map<std::string, std::string> values = clock_sample_value_map(sample_signals, sample.values);
            ExprTri valid = ExprTri::Unknown;
            std::string eval_error;
            if (!xdebug_waveform::eval_event_expression(valid_expr, values, valid, eval_error)) {
                error = eval_error;
                return false;
            }
            if (valid == ExprTri::False) {
                valid_false_count++;
                return true;
            }
            if (valid == ExprTri::Unknown) {
                unknown_count++;
                add_evidence(t, "unknown_valid", nullptr);
                return true;
            }

            std::string bits = counter_bits_from_values(counter, values);
            uint64_t value = 0;
            std::string parse_error;
            if (!bits_to_u64(bits, value, parse_error)) {
                if (!parse_error.empty()) {
                    error = parse_error;
                    return false;
                }
                unknown_count++;
                add_evidence(t, "unknown_counter", nullptr);
                return true;
            }

            if (!have_previous_value || value != previous_value) {
                add_evidence(t, have_previous_value ? "value_change" : "initial", u64_to_decimal(value));
                previous_value = value;
                have_previous_value = true;
            }

            valid_count++;
            sum += static_cast<long double>(value);
            if (!have_value) {
                have_value = true;
                min_value = max_value = value;
                min_count = max_count = 1;
                min_first_time = max_first_time = t;
                return true;
            }
            if (value < min_value) {
                min_value = value;
                min_count = 1;
                min_first_time = t;
            } else if (value == min_value) {
                min_count++;
            }
            if (value > max_value) {
                max_value = value;
                max_count = 1;
                max_first_time = t;
            } else if (value == max_value) {
                max_count++;
            }
            return true;
        }, error, samples, truncated)) return Json();

    Json data;
    data["summary"] = {
        {"sample_count", samples},
        {"valid_count", valid_count}
    };
    data["clock"] = clock;
    data["edge"] = clock_edge_kind_text(clock_sample.edge);
    if (clock_sample.edge != ClockEdgeKind::Negedge)
        data["sample_point"] = clock_sample_point_text(clock_sample.sample_point);
    data["sample_time_semantics"] = "time is sample_time";
    data["sampling_mode"] = "clock_edge";
    data["begin"] = format_time(begin);
    data["end"] = format_time(end);
    data["valid_false_count"] = valid_false_count;
    data["unknown_count"] = unknown_count;
    const bool response_truncated = evidence_limit >= 0 && evidence_count > evidence_limit;
    data["summary"]["scan_complete"] = !truncated;
    data["summary"]["analysis_complete"] = !truncated;
    data["summary"]["response_truncated"] = response_truncated;
    data["summary"]["truncated"] = truncated || response_truncated;
    data["summary"]["truncation_scopes"] = Json::array();
    if (truncated) data["summary"]["truncation_scopes"].push_back("analysis_samples");
    if (response_truncated) data["summary"]["truncation_scopes"].push_back("response_evidence");
    data["evidence"] = evidence;
    data["summary"]["evidence_count"] = evidence_count;
    data["summary"]["returned_evidence_count"] = evidence.size();
    data["cnt"] = args["cnt"];
    data["vld"] = args["vld"];
    if (have_value) {
        data["summary"]["min_value"] = u64_to_decimal(min_value);
        data["summary"]["max_value"] = u64_to_decimal(max_value);
        data["summary"]["average_value"] =
            long_double_to_decimal(sum / static_cast<long double>(valid_count));
        data["min_count"] = min_count;
        data["max_count"] = max_count;
        data["min_first_time"] = format_time(min_first_time);
        data["max_first_time"] = format_time(max_first_time);
    }
    return data;
}


}  // namespace xdebug_waveform
