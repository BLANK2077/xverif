#include "../server_internal.h"
#include "core/npi/time_contract.h"

#include <algorithm>
#include <limits>

namespace xdebug_waveform {

int direction_filter(const Json& args) {
    std::string direction = args.value("direction", std::string("all"));
    if (direction == "write") return 1;
    if (direction == "read") return 2;
    return 0;
}

bool ensure_apb_analyzed_for_ai(const std::string& name, std::string& error) {
    xdebug_waveform::ApbConfig config;
    StoreResult loaded =
        read_apb_from_registry(g_session_id, name.c_str(), config);
    if (!loaded.ok()) {
        error = store_error_text(loaded);
        return false;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        error = "Failed to analyze APB: " + name;
        return false;
    }
    return true;
}

bool ensure_axi_analyzed_for_ai(const std::string& name, std::string& error) {
    xdebug_waveform::AxiConfig config;
    StoreResult loaded =
        read_axi_from_registry(g_session_id, name.c_str(), config);
    if (!loaded.ok()) {
        error = store_error_text(loaded);
        return false;
    }
    if (!g_axi_analyzer.analyze(name, g_fsdb_file, config)) {
        error = "Failed to analyze AXI: " + name;
        return false;
    }
    return true;
}

Json ai_apb_transfer_window(const Json& args, std::string& error) {
    std::string name = args.value("name", std::string());
    if (name.empty()) {
        error = "apb.transfer_window requires args.name";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    if (!ensure_apb_analyzed_for_ai(name, error)) return Json();
    std::vector<xdebug_waveform::ApbContextTransaction> txns;
    int filter = direction_filter(args);
    int limit = args.value("line_limit", 1000);
    if (!g_apb_analyzer.get_transactions_in_range(name, begin, end, txns, -1)) {
        error = "APB config not analyzed: " + name;
        return Json();
    }
    Json arr = Json::array();
    size_t matched_count = 0;
    for (const auto& item : txns) {
        if (!item.txn) continue;
        if (filter == 1 && !item.txn->is_write) continue;
        if (filter == 2 && item.txn->is_write) continue;
        ++matched_count;
        if (limit >= 0 && static_cast<int>(arr.size()) >= limit) {
            continue;
        }
        Json txn = apb_txn_to_json(item.txn, true);
        arr.push_back(txn);
    }
    auto range = format_time_range(begin, end);
    Json out;
    out["summary"] = {{"name", name},
                      {"begin", range.first},
                      {"end", range.second}};
    const ApbResult* canonical = g_apb_analyzer.get_result(name);
    const bool analysis_complete =
        canonical && canonical->diagnostics.analysis_complete;
    const bool response_truncated = arr.size() < matched_count;
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_transactions");
    if (response_truncated) truncation_scopes.push_back("response_transactions");
    xdebug_core::set_completeness(
        out["summary"],
        analysis_complete,
        analysis_complete,
        response_truncated,
        matched_count,
        arr.size(),
        truncation_scopes);
    out["transactions"] = arr;
    return out;
}

Json ai_axi_transactions_window(const Json& args, std::string& error) {
    std::string name = args.value("name", std::string());
    if (name.empty()) {
        error = "AXI action requires args.name";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    if (!ensure_axi_analyzed_for_ai(name, error)) return Json();
    std::vector<xdebug_waveform::AxiContextTransaction> txns;
    int filter = direction_filter(args);
    const bool include_data = args.value("output", Json::object()).value("include_data", false);
    int limit = args.value("line_limit", 1000);
    if (!g_axi_analyzer.get_transactions_in_range(name, begin, end, txns, -1)) {
        error = "AXI config not analyzed: " + name;
        return Json();
    }
    Json arr = Json::array();
    size_t matched_count = 0;
    for (const auto& item : txns) {
        if (!item.txn) continue;
        if (filter == 1 && !item.txn->is_write) continue;
        if (filter == 2 && item.txn->is_write) continue;
        ++matched_count;
        if (limit >= 0 && static_cast<int>(arr.size()) >= limit) {
            continue;
        }
        Json txn = axi_txn_to_json(item.txn, include_data);
        txn["match_time"] = format_time(item.match_time);
        txn["latency"] = format_duration(
            item.txn->resp_time >= item.txn->addr_time ? item.txn->resp_time - item.txn->addr_time : 0);
        arr.push_back(txn);
    }
    auto range = format_time_range(begin, end);
    const AxiResult* canonical = g_axi_analyzer.get_result(name);
    Json diagnostics = Json::object();
    if (canonical) {
        const AxiDiagnostics& diag = canonical->diagnostics;
        diagnostics = {{"full_scan_count", diag.full_scan_count},
                       {"incomplete_write_count", diag.incomplete_write_count},
                       {"incomplete_read_count", diag.incomplete_read_count},
                       {"buffered_w_beat_count", diag.buffered_w_beat_count},
                       {"buffered_w_burst_count", diag.buffered_w_burst_count},
                       {"orphan_w_beat_count", diag.orphan_w_beat_count},
                       {"orphan_b_count", diag.orphan_b_count},
                       {"orphan_r_beat_count", diag.orphan_r_beat_count},
                       {"response_dependency_violation_count", diag.response_dependency_violation_count}};
    }
    Json data = {
        {"summary", {{"name", name}, {"begin", range.first}, {"end", range.second}}},
        {"pairing_rule", {{"write_data", "AXI4 W bursts bind in AW acceptance order"},
                          {"write_response", "BID binds to the oldest data-complete AW with the same ID"},
                          {"read_response", "RID binds to the oldest AR with the same ID"}}},
        {"diagnostics", diagnostics},
        {"transactions", arr}
    };
    const bool analysis_complete =
        canonical && canonical->diagnostics.analysis_complete;
    const bool response_truncated = arr.size() < matched_count;
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_transactions");
    if (response_truncated) truncation_scopes.push_back("response_transactions");
    xdebug_core::set_completeness(
        data["summary"],
        analysis_complete,
        analysis_complete,
        response_truncated,
        matched_count,
        arr.size(),
        truncation_scopes);
    return data;
}

Json ai_axi_latency_outlier(const Json& args, std::string& error) {
    const std::string name = args.value("name", std::string());
    if (name.empty()) {
        error = "axi.latency_outlier requires args.name";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    if (!ensure_axi_analyzed_for_ai(name, error)) return Json();
    const int filter = direction_filter(args);
    auto latency_key = [](const xdebug_waveform::AxiContextTransaction& item) -> npiFsdbTime {
        return item.txn->resp_time >= item.txn->addr_time
            ? item.txn->resp_time - item.txn->addr_time : 0;
    };
    const std::string method = args.value("method", std::string("top_n"));
    const int top_n = args.value("top_n", 10);
    const int line_limit = args.value("line_limit", 1000);
    npiFsdbTime threshold = 0;
    if (method == "threshold") {
        const std::string threshold_text = args.value("threshold", std::string());
        if (threshold_text.empty()) {
            error = "INVALID_REQUEST: args.threshold is required when args.method is threshold";
            return Json();
        }
        if (!parse_user_time(threshold_text.c_str(), false, threshold, error)) return Json();
    }
    std::vector<xdebug_waveform::AxiContextTransaction> candidates;
    size_t candidate_count = 0;
    size_t matched_outlier_count = 0;
    if (!g_axi_analyzer.get_latency_outliers_in_range(
            name, begin, end, filter, method == "threshold", threshold,
            static_cast<size_t>(top_n), line_limit, candidates,
            candidate_count, matched_outlier_count)) {
        error = "AXI config not analyzed: " + name;
        return Json();
    }
    Json out = Json::array();
    const bool include_data = args.value("output", Json::object()).value("include_data", false);
    for (size_t i = 0; i < candidates.size(); ++i) {
        Json txn = axi_txn_to_json(candidates[i].txn, include_data);
        txn["match_time"] = format_time(candidates[i].match_time);
        txn["latency"] = format_duration(latency_key(candidates[i]));
        out.push_back(std::move(txn));
    }
    const size_t returned_outlier_count = out.size();
    auto range = format_time_range(begin, end);
    Json data = {{"summary", {{"name", name}, {"begin", range.first}, {"end", range.second},
                              {"candidate_count", candidate_count}}}};
    data["outliers"] = std::move(out);
    data["method"] = method;
    data["classification"] = method == "threshold" ? "threshold_exceeded" : "slowest_ranking";
    if (method == "top_n") data["top_n"] = top_n;
    else data["threshold"] = format_duration(threshold);
    const AxiResult* canonical = g_axi_analyzer.get_result(name);
    const bool analysis_complete =
        canonical && canonical->diagnostics.analysis_complete;
    const bool response_truncated =
        returned_outlier_count < matched_outlier_count;
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_transactions");
    if (response_truncated) truncation_scopes.push_back("response_outliers");
    xdebug_core::set_completeness(
        data["summary"],
        analysis_complete,
        analysis_complete,
        response_truncated,
        matched_outlier_count,
        returned_outlier_count,
        truncation_scopes);
    return data;
}

Json ai_axi_outstanding_timeline(const Json& args, std::string& error) {
    std::string name = args.value("name", std::string());
    if (name.empty()) {
        error = "axi.outstanding_timeline requires args.name";
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    AxiConfig cfg;
    StoreResult loaded =
        read_axi_from_registry(g_session_id, name.c_str(), cfg);
    if (!loaded.ok()) {
        error = store_error_text(loaded);
        return Json();
    }
    ClockSampleSpec clock_sample = cfg.clock_sample;
    if (!normalize_clock_sample_spec(g_fsdb_file, clock_sample, error)) return Json();
    if (!ensure_axi_analyzed_for_ai(name, error)) return Json();
    int limit = args.value("line_limit", 1000);
    int filter = direction_filter(args);
    xdebug_waveform::AxiOutstandingSummary result;
    if (!g_axi_analyzer.summarize_outstanding_in_range(name, begin, end, filter, limit, result)) {
        error = "AXI config not analyzed: " + name;
        return Json();
    }
    Json change_points = Json::array();
    int previous_read = 0;
    int previous_write = 0;
    bool have_previous = false;
    for (const auto& s : result.change_points) {
        Json item;
        item["time"] = format_time(s.time);
        if (filter == 0 || filter == 2) item["read"] = s.read;
        if (filter == 0 || filter == 1) item["write"] = s.write;
        const int read_delta = have_previous ? s.read - previous_read : s.read;
        const int write_delta = have_previous ? s.write - previous_write : s.write;
        if (filter == 0 || filter == 2) {
            item["read_delta"] = read_delta;
            item["read_event"] = read_delta > 0 ? "ar_handshake"
                : read_delta < 0 ? "rlast_handshake" : "none";
        }
        if (filter == 0 || filter == 1) {
            item["write_delta"] = write_delta;
            item["write_event"] = write_delta > 0 ? "aw_handshake"
                : write_delta < 0 ? "b_handshake" : "none";
        }
        previous_read = s.read;
        previous_write = s.write;
        have_previous = true;
        change_points.push_back(item);
    }
    bool truncated = result.change_point_count > result.change_points.size();
    Json data;
    data["summary"] = {
        {"name", name},
        {"sampling_mode", "clock_edge"},
        {"clock", clock_sample.clock},
        {"edge", clock_edge_kind_text(clock_sample.edge)},
        {"sample_time_semantics", "time is sample_time"},
        {"sample_count", result.sample_count},
        {"peak_read", result.peak_read}, {"peak_write", result.peak_write},
        {"peak_read_time", result.peak_read > 0 ? Json(format_time(result.peak_read_time)) : Json(nullptr)},
        {"peak_write_time", result.peak_write > 0 ? Json(format_time(result.peak_write_time)) : Json(nullptr)},
        {"first_nonzero_time", result.has_first_nonzero
            ? Json(format_time(result.first_nonzero_time)) : Json(nullptr)},
        {"final_read", result.has_samples ? Json(result.final_read) : Json(nullptr)},
        {"final_write", result.has_samples ? Json(result.final_write) : Json(nullptr)},
        {"requested_range", {{"begin", format_time(begin)}, {"end", format_time(end)}}}
    };
    const AxiResult* canonical = g_axi_analyzer.get_result(name);
    const bool analysis_complete =
        canonical && canonical->diagnostics.analysis_complete;
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_transactions");
    if (truncated) truncation_scopes.push_back("response_change_points");
    xdebug_core::set_completeness(
        data["summary"],
        analysis_complete,
        analysis_complete,
        truncated,
        result.change_point_count,
        change_points.size(),
        truncation_scopes);
    if (clock_sample.edge != ClockEdgeKind::Negedge)
        data["summary"]["sample_point"] = clock_sample_point_text(clock_sample.sample_point);
    data["change_points"] = change_points;
    return data;
}

Json ai_axi_channel_stall(const Json& args, std::string& error) {
    std::string name = args.value("name", std::string());
    std::string channel = args.value("channel", std::string("ar"));
    xdebug_waveform::AxiConfig cfg;
    if (name.empty()) {
        error = "axi.channel_stall requires args.name";
        return Json();
    }
    StoreResult loaded =
        read_axi_from_registry(g_session_id, name.c_str(), cfg);
    if (!loaded.ok()) {
        error = store_error_text(loaded);
        return Json();
    }
    npiFsdbTime begin = 0, end = 0;
    if (!json_time_range(args, begin, end, error)) return Json();
    std::string valid, ready;
    if (channel == "aw") { valid = cfg.awvalid; ready = cfg.awready; }
    else if (channel == "w") { valid = cfg.wvalid; ready = cfg.wready; }
    else if (channel == "b") { valid = cfg.bvalid; ready = cfg.bready; }
    else if (channel == "r") { valid = cfg.rvalid; ready = cfg.rready; }
    else if (channel == "ar") { valid = cfg.arvalid; ready = cfg.arready; }
    else {
        error = "INVALID_REQUEST: args.channel must be one of aw, w, b, ar, r";
        return Json();
    }

    ClockSampleSpec clock_sample = cfg.clock_sample;
    if (!normalize_clock_sample_spec(g_fsdb_file, clock_sample, error)) return Json();
    npiFsdbSigHandle valid_h = npi_fsdb_sig_by_name(g_fsdb_file, valid.c_str(), NULL);
    npiFsdbSigHandle ready_h = npi_fsdb_sig_by_name(g_fsdb_file, ready.c_str(), NULL);
    if (!valid_h || !ready_h) {
        error = "AXI channel signal not found for channel: " + channel;
        return Json();
    }

    Json rules = args.value("rules", Json::object());
    int max_wait = rules.value("max_wait_cycles", 100);
    int finding_limit = args.value("line_limit", 100);
    int sample_count = 0, transfers = 0, ready_only = 0, max_stall = 0;
    bool truncated = false;
    Json findings = Json::array();
    int finding_count = 0;
    bool have_activity = false;
    npiFsdbTime first_activity_time = 0;
    auto add_finding = [&](const Json& finding) {
        ++finding_count;
        if (finding_limit < 0 || static_cast<int>(findings.size()) < finding_limit)
            findings.push_back(finding);
    };
    int stall_cycles = 0;
    npiFsdbTime stall_begin = 0;
    std::vector<ClockSampleSignal> sample_signals = {
        {"valid", valid, valid_h},
        {"ready", ready, ready_h}
    };
    ClockSampleScanner scanner(g_fsdb_file, clock_sample);
    if (!scanner.scan(sample_signals, begin, end, npiFsdbBinStrVal, 'b', -1,
        [&](const ClockSample& sample) -> bool {
            if (sample.values.size() < 2) return true;
            ExprTri v = xdebug_waveform::expr_truth_value(sample.values[0]);
            ExprTri r = xdebug_waveform::expr_truth_value(sample.values[1]);
            if (!have_activity && (v == ExprTri::True || r == ExprTri::True)) {
                have_activity = true;
                first_activity_time = sample.time;
            }
            if (v == ExprTri::True && r == ExprTri::True) {
                ++transfers;
                if (stall_cycles > 0) {
                    if (stall_cycles > max_stall) max_stall = stall_cycles;
                    if (stall_cycles > max_wait) {
                        add_finding({{"type", "long_stall"}, {"severity", "warning"},
                                     {"begin", format_time(stall_begin)}, {"end", format_time(sample.time)},
                                     {"cycles", stall_cycles}});
                    }
                    stall_cycles = 0;
                }
            } else if (v == ExprTri::True && r == ExprTri::False) {
                if (stall_cycles == 0) stall_begin = sample.time;
                ++stall_cycles;
            } else if (r == ExprTri::True && v == ExprTri::False) {
                ++ready_only;
            }
            return true;
        }, error, sample_count, truncated)) {
        return Json();
    }
    if (stall_cycles > 0) {
        if (stall_cycles > max_stall) max_stall = stall_cycles;
        if (stall_cycles > max_wait) {
            add_finding({{"type", "long_stall"}, {"severity", "warning"},
                         {"begin", format_time(stall_begin)}, {"end", format_time(end)},
                         {"cycles", stall_cycles}, {"open_at_window_end", true}});
        }
    }

    Json data;
    data["summary"] = {
        {"name", name}, {"channel", channel},
        {"sampling_mode", "clock_edge"},
        {"clock", clock_sample.clock},
        {"edge", clock_edge_kind_text(clock_sample.edge)},
        {"sample_time_semantics", "time is sample_time"},
        {"sample_count", sample_count},
        {"transfer_count", transfers},
        {"max_stall_cycles", max_stall},
        {"ready_without_valid_cycles", ready_only},
        {"first_activity_time", have_activity ? Json(format_time(first_activity_time)) : Json(nullptr)},
        {"scanned_range", {{"begin", format_time(begin)}, {"end", format_time(end)}}}
    };
    const bool response_truncated =
        finding_limit >= 0 && finding_count > finding_limit;
    std::vector<std::string> truncation_scopes;
    if (truncated) truncation_scopes.push_back("analysis_samples");
    if (response_truncated) truncation_scopes.push_back("response_findings");
    xdebug_core::set_completeness(
        data["summary"],
        !truncated,
        !truncated,
        response_truncated,
        static_cast<std::size_t>(finding_count),
        findings.size(),
        truncation_scopes);
    if (clock_sample.edge != ClockEdgeKind::Negedge)
        data["summary"]["sample_point"] = clock_sample_point_text(clock_sample.sample_point);
    data["findings"] = findings;
    return data;
}

Json cursor_to_json(const Cursor& c) {
    Json j;
    j["name"] = c.name;
    j["time"] = format_time(c.time);
    j["note"] = c.note;
    j["origin"] = c.origin;
    j["clock"] = c.clock;
    j["created_at"] = c.created_at;
    j["updated_at"] = c.updated_at;
    return j;
}

Json resolved_time_json(const std::string& spec, npiFsdbTime time) {
    Json j;
    j["source"] = spec;
    j["time"] = format_time(time);
    return j;
}

Json ai_cursor_action(const std::string& action, const Json& args, std::string& error) {
    CursorManager cm;
    if (action == "waveform.cursor.set") {
        std::string name = args.value("name", std::string());
        std::string spec = args.value("time", args.value("at", std::string()));
        if (name.empty() || spec.empty()) {
            error = "waveform.cursor.set requires args.name and args.time";
            return Json();
        }
        npiFsdbTime t = 0;
        if (!parse_user_time(spec.c_str(), false, t, error)) return Json();
        Cursor c;
        c.name = name;
        c.time = t;
        c.note = args.value("note", std::string());
        c.origin = args.value("origin", std::string("manual"));
        c.clock = args.value("clock", std::string());
        StoreResult stored =
            cm.set_cursor(
                g_session_id,
                c,
                args.value("active", true));
        if (!stored.ok()) {
            error = store_error_text(stored);
            return Json();
        }
        Cursor saved;
        StoreResult loaded =
            cm.get_cursor(g_session_id, name, saved);
        if (!loaded.ok()) {
            error = store_error_text(loaded);
            return Json();
        }
        Json data;
        data["summary"] = {{"name", name}, {"time", format_time(t)},
                           {"status", "set"}, {"active", args.value("active", true)}};
        data["resolved_time"] = resolved_time_json(spec, t);
        data["metadata"] = {{"note", saved.note}, {"origin", saved.origin}, {"clock", saved.clock}};
        return data;
    }
    if (action == "waveform.cursor.get") {
        std::string name = args.value("name", std::string());
        if (name.empty()) {
            error = "waveform.cursor.get requires args.name";
            return Json();
        }
        Cursor c;
        StoreResult loaded =
            cm.get_cursor(g_session_id, name, c);
        if (!loaded.ok()) {
            error = store_error_text(loaded);
            return Json();
        }
        Json data;
        data["summary"] = {{"name", c.name}, {"time", format_time(c.time)}, {"status", "found"}};
        data["metadata"] = {{"note", c.note}, {"origin", c.origin}, {"clock", c.clock}};
        return data;
    }
    if (action == "waveform.cursor.list") {
        std::vector<Cursor> cursors;
        StoreResult listed =
            cm.list_cursors(g_session_id, cursors);
        if (!listed.ok()) {
            error = store_error_text(listed);
            return Json();
        }
        Json arr = Json::array();
        for (const auto& c : cursors) {
            arr.push_back(cursor_to_json(c));
        }
        std::string active;
        StoreResult active_result =
            cm.get_active_cursor(g_session_id, active);
        if (!active_result.ok() &&
            active_result.status != StoreStatus::NotFound) {
            error = store_error_text(active_result);
            return Json();
        }
        Json data;
        data["summary"] = {{"cursor_count", arr.size()},
                           {"active_cursor", active.empty() ? Json(nullptr) : Json(active)}};
        data["cursors"] = arr;
        return data;
    }
    if (action == "waveform.cursor.delete") {
        std::string name = args.value("name", std::string());
        if (name.empty()) {
            error = "waveform.cursor.delete requires args.name";
            return Json();
        }
        StoreResult deleted =
            cm.delete_cursor(g_session_id, name);
        if (!deleted.ok()) {
            error = store_error_text(deleted);
            return Json();
        }
        Json data;
        data["summary"] = {{"status", "deleted"}, {"name", name}, {"deleted", true}};
        return data;
    }
    if (action == "waveform.cursor.use") {
        std::string name = args.value("name", std::string());
        if (name.empty()) {
            error = "waveform.cursor.use requires args.name";
            return Json();
        }
        StoreResult used =
            cm.use_cursor(g_session_id, name);
        if (!used.ok()) {
            error = store_error_text(used);
            return Json();
        }
        Cursor c;
        StoreResult loaded =
            cm.get_cursor(g_session_id, name, c);
        if (!loaded.ok()) {
            error = store_error_text(loaded);
            return Json();
        }
        Json data;
        data["summary"] = {{"status", "active"}, {"active_cursor", name},
                           {"time", format_time(c.time)}};
        data["metadata"] = {{"note", c.note}, {"origin", c.origin}, {"clock", c.clock}};
        return data;
    }
    error = "Unsupported cursor action: " + action;
    return Json();
}

}  // namespace xdebug_waveform
