#include "../server_internal.h"

namespace xdebug_waveform {

std::string format_axi_count_json(size_t count) {
    Json j;
    j["count"] = count;
    return json_response(j);
}

size_t count_axi_by_id(const char* name, bool is_write, const char* id_str) {
    if (!id_str) return is_write ? g_axi_analyzer.get_write_count(name) : g_axi_analyzer.get_read_count(name);
    size_t count = 0;
    const xdebug_waveform::AxiTransaction* txn = nullptr;
    while (true) {
        bool ok = is_write
            ? g_axi_analyzer.get_write_by_num(name, id_str, count + 1, txn)
            : g_axi_analyzer.get_read_by_num(name, id_str, count + 1, txn);
        if (!ok) break;
        ++count;
    }
    return count;
}

void send_axi_txn_or_error(int client_fd, bool ok, const xdebug_waveform::AxiTransaction* txn, bool json) {
    if (ok && txn) {
        std::string resp = json ? format_axi_txn_json(txn) : (format_axi_txn(txn) + "\n" + END_MARKER);
        send_all(client_fd, resp.c_str(), resp.length());
    } else {
        std::string err = std::string(ERROR_PREFIX) + "Not found\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_axi_rw(int client_fd, const char* name, bool is_write, const char* addr_str,
                          const char* id_str, int num, bool last_flag, bool json) {
    if (!ensure_axi_analyzed(client_fd, name)) return;
    const xdebug_waveform::AxiTransaction* txn = nullptr;
    if (!addr_str && num < 0 && !last_flag) {
        size_t count = count_axi_by_id(name, is_write, id_str);
        std::string resp = json ? format_axi_count_json(count) : (std::to_string(count) + "\n" + END_MARKER);
        send_all(client_fd, resp.c_str(), resp.length());
        return;
    }

    bool ok = false;
    if (addr_str) {
        uint64_t addr = strtoull(addr_str, nullptr, 0);
        if (is_write) {
            if (num > 0) ok = g_axi_analyzer.get_write_by_addr_num(name, addr, id_str, (size_t)num, txn);
            else if (last_flag) ok = g_axi_analyzer.get_write_by_addr_last(name, addr, id_str, txn);
            else ok = g_axi_analyzer.get_write_by_addr(name, addr, id_str, txn);
        } else {
            if (num > 0) ok = g_axi_analyzer.get_read_by_addr_num(name, addr, id_str, (size_t)num, txn);
            else if (last_flag) ok = g_axi_analyzer.get_read_by_addr_last(name, addr, id_str, txn);
            else ok = g_axi_analyzer.get_read_by_addr(name, addr, id_str, txn);
        }
    } else if (num > 0) {
        ok = is_write
            ? g_axi_analyzer.get_write_by_num(name, id_str, (size_t)num, txn)
            : g_axi_analyzer.get_read_by_num(name, id_str, (size_t)num, txn);
    } else if (last_flag) {
        ok = is_write
            ? g_axi_analyzer.get_write_last(name, id_str, txn)
            : g_axi_analyzer.get_read_last(name, id_str, txn);
    }
    send_axi_txn_or_error(client_fd, ok, txn, json);
}

void handle_axi_cursor(int client_fd, const char* name, int cmd_type, int filter, bool json) {
    if (!ensure_axi_analyzed(client_fd, name)) return;
    const xdebug_waveform::AxiTransaction* txn = nullptr;
    bool ok = false;
    if (cmd_type == 1) ok = g_axi_analyzer.cursor_begin(name, filter, txn);
    else if (cmd_type == 2) ok = g_axi_analyzer.cursor_next(name, filter, txn);
    else if (cmd_type == 3) ok = g_axi_analyzer.cursor_prev(name, filter, txn);
    else ok = g_axi_analyzer.cursor_last(name, filter, txn);

    if (ok && txn) {
        std::string resp = json ? format_axi_txn_json(txn) : (format_axi_txn(txn) + "\n" + END_MARKER);
        send_all(client_fd, resp.c_str(), resp.length());
    } else {
        std::string err = std::string(ERROR_PREFIX) + "No transaction found\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

std::string format_axi_stat(const char* label, const xdebug_waveform::AxiStatResult& stat, bool json) {
    if (json) {
        Json j;
        j[label] = {
            {"max", stat.max},
            {"min", stat.min},
            {"avg", stat.avg},
            {"samples", stat.samples}
        };
        return json_response(j);
    }
    return std::string(label) + " max=" + std::to_string(stat.max)
        + " min=" + std::to_string(stat.min)
        + " avg=" + std::to_string(stat.avg)
        + " samples=" + std::to_string(stat.samples) + "\n" + END_MARKER;
}

const char* relation_to_event(npiFsdbTime t, npiFsdbTime event_time) {
    if (t < event_time) return "before_event";
    if (t > event_time) return "after_event";
    return "at_event";
}

void handle_axi_stat(int client_fd, const char* name, bool latency, int filter,
                            const char* id_str, bool json) {
    if (!ensure_axi_analyzed(client_fd, name)) return;
    xdebug_waveform::AxiStatResult stat;
    bool ok = latency
        ? g_axi_analyzer.get_latency_stats(name, filter, id_str, stat)
        : g_axi_analyzer.get_outstanding_stats(name, filter, id_str, stat);
    if (!ok) {
        std::string err = std::string(ERROR_PREFIX) + "No data\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    std::string resp = format_axi_stat(latency ? "latency" : "outstanding", stat, json);
    send_all(client_fd, resp.c_str(), resp.length());
}

Json event_record_to_json(const xdebug_waveform::EventRecord& rec) {
    Json j;
    j["time"] = format_time(rec.time);
    j["signals"] = Json::object();
    j["fields"] = Json::object();
    for (const auto& item : rec.signals) {
        auto width = rec.signal_widths.find(item.first);
        j["signals"][item.first] = xdebug_core::render_logic_value(
            xdebug_core::logic_value_from_fsdb_raw(
                item.second, 'b',
                width == rec.signal_widths.end() ? 0 : width->second));
    }
    for (const auto& item : rec.fields) {
        auto width = rec.field_widths.find(item.first);
        j["fields"][item.first] = xdebug_core::render_logic_value(
            xdebug_core::logic_value_from_fsdb_raw(
                item.second, 'b',
                width == rec.field_widths.end() ? 0 : width->second));
    }
    return j;
}

std::string format_event_records_text(const std::vector<xdebug_waveform::EventRecord>& records) {
    if (records.empty()) return std::string("(no event found)\n") + END_MARKER;
    std::string out;
    for (size_t i = 0; i < records.size(); ++i) {
        const auto& rec = records[i];
        out += "idx=" + std::to_string(i) + " time=" + format_time(rec.time);
        for (const auto& kv : rec.signals) out += " " + kv.first + "=" + kv.second;
        for (const auto& kv : rec.fields) out += " " + kv.first + "=" + kv.second;
        out += "\n";
    }
    out += END_MARKER;
    return out;
}

std::string format_event_records_json(const std::vector<xdebug_waveform::EventRecord>& records) {
    Json j = Json::array();
    for (const auto& rec : records) j.push_back(event_record_to_json(rec));
    return json_response(j);
}

Json axi_context_to_json(const char* axi_name,
                                npiFsdbTime event_time,
                                npiFsdbTime window_ps,
                                const std::vector<xdebug_waveform::AxiContextTransaction>& txns) {
    Json ctx;
    ctx["name"] = axi_name ? axi_name : "";
    ctx["window"] = format_duration(window_ps);
    ctx["transactions"] = Json::array();
    for (const auto& item : txns) {
        Json txn = axi_txn_to_json(item.txn, true);
        txn["match_time"] = format_time(item.match_time);
        txn["relation"] = relation_to_event(item.match_time, event_time);
        npiFsdbTime delta = item.match_time >= event_time
            ? item.match_time - event_time
            : event_time - item.match_time;
        txn["delta"] = (item.match_time < event_time ? "-" : "") + format_duration(delta);
        ctx["transactions"].push_back(txn);
    }
    return ctx;
}

Json apb_context_to_json(const char* apb_name,
                                npiFsdbTime event_time,
                                npiFsdbTime window_ps,
                                const std::vector<xdebug_waveform::ApbContextTransaction>& txns) {
    Json ctx;
    ctx["name"] = apb_name ? apb_name : "";
    ctx["window"] = format_duration(window_ps);
    ctx["transactions"] = Json::array();
    for (const auto& item : txns) {
        Json txn = apb_txn_to_json(item.txn, true);
        npiFsdbTime t = item.txn ? item.txn->time : 0;
        txn["relation"] = relation_to_event(t, event_time);
        npiFsdbTime delta = t >= event_time ? t - event_time : event_time - t;
        txn["delta"] = (t < event_time ? "-" : "") + format_duration(delta);
        ctx["transactions"].push_back(txn);
    }
    return ctx;
}

std::string format_event_records_with_context_json(
        const std::vector<xdebug_waveform::EventRecord>& records,
        const std::vector<std::vector<xdebug_waveform::AxiContextTransaction>>& axi_contexts,
        const std::vector<std::vector<xdebug_waveform::ApbContextTransaction>>& apb_contexts,
        const char* axi_name,
        const char* apb_name,
        npiFsdbTime window_ps) {
    Json j = Json::array();
    for (size_t i = 0; i < records.size(); ++i) {
        Json rec = event_record_to_json(records[i]);
        Json context;
        if (axi_name) context["axi"] = axi_context_to_json(axi_name, records[i].time, window_ps, axi_contexts[i]);
        if (apb_name) context["apb"] = apb_context_to_json(apb_name, records[i].time, window_ps, apb_contexts[i]);
        rec["context"] = context;
        j.push_back(rec);
    }
    return json_response(j);
}

std::string format_event_records_with_context_text(
        const std::vector<xdebug_waveform::EventRecord>& records,
        const std::vector<std::vector<xdebug_waveform::AxiContextTransaction>>& axi_contexts,
        const std::vector<std::vector<xdebug_waveform::ApbContextTransaction>>& apb_contexts,
        const char* axi_name,
        const char* apb_name,
        npiFsdbTime window_ps) {
    if (records.empty()) return std::string("(no event found)\n") + END_MARKER;
    std::string out;
    for (size_t i = 0; i < records.size(); ++i) {
        const auto& rec = records[i];
        out += "idx=" + std::to_string(i) + " time=" + format_time(rec.time);
        for (const auto& kv : rec.signals) out += " " + kv.first + "=" + kv.second;
        for (const auto& kv : rec.fields) out += " " + kv.first + "=" + kv.second;
        out += "\n";
        if (axi_name) {
            out += "  axi_context name=" + std::string(axi_name)
                + " window=" + format_time(window_ps);
            if (axi_contexts[i].empty()) {
                out += ": none\n";
            } else {
                out += "\n";
                for (const auto& item : axi_contexts[i]) {
                    out += "    " + format_axi_txn(item.txn)
                        + " match_time=" + format_time(item.match_time)
                        + " relation=" + relation_to_event(item.match_time, rec.time)
                        + " delta=" + std::string(item.match_time < rec.time ? "-" : "")
                        + format_duration(item.match_time >= rec.time
                                          ? item.match_time - rec.time
                                          : rec.time - item.match_time)
                        + "\n";
                }
            }
        }
        if (apb_name) {
            out += "  apb_context name=" + std::string(apb_name)
                + " window=" + format_time(window_ps);
            if (apb_contexts[i].empty()) {
                out += ": none\n";
            } else {
                out += "\n";
                for (const auto& item : apb_contexts[i]) {
                    npiFsdbTime t = item.txn ? item.txn->time : 0;
                    out += "    " + format_apb_txn_with_type(item.txn)
                        + " relation=" + relation_to_event(t, rec.time)
                        + " delta=" + std::string(t < rec.time ? "-" : "")
                        + format_duration(t >= rec.time ? t - rec.time : rec.time - t)
                        + "\n";
                }
            }
        }
    }
    out += END_MARKER;
    return out;
}

void handle_event_query(int client_fd,
                               const char* name,
                               npiFsdbTime begin_time,
                               npiFsdbTime end_time,
                               int limit,
                               bool use_json,
                               bool fast_find,
                               const char* expr,
                               const char* axi_context_name,
                               const char* apb_context_name,
                               npiFsdbTime context_window) {
    xdebug_waveform::EventManager em;
    xdebug_waveform::EventConfig config;
    if (!em.get_event(g_session_id, g_fsdb_file_path, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Event config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    xdebug_waveform::EventQuery query;
    query.expr = expr ? expr : "";
    query.begin = begin_time;
    query.end = end_time;
    query.limit = limit;
    query.fast_find = fast_find;
    std::vector<xdebug_waveform::EventRecord> records;
    std::string error;
    if (!g_event_analyzer.analyze(g_fsdb_file, config, query, records, error)) {
        std::string err = std::string(ERROR_PREFIX) + error + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    bool use_axi_context = axi_context_name && strcmp(axi_context_name, "-") != 0;
    bool use_apb_context = apb_context_name && strcmp(apb_context_name, "-") != 0;

    std::string resp;
    if (use_axi_context || use_apb_context) {
        std::vector<std::vector<xdebug_waveform::AxiContextTransaction>> axi_contexts(records.size());
        std::vector<std::vector<xdebug_waveform::ApbContextTransaction>> apb_contexts(records.size());

        if (use_axi_context) {
            xdebug_waveform::AxiConfig axi_config;
            if (!read_axi_from_registry(g_session_id, axi_context_name, axi_config)) {
                std::string err = std::string(ERROR_PREFIX) + "AXI config not found: " + axi_context_name + "\n" + END_MARKER;
                send_all(client_fd, err.c_str(), err.length());
                return;
            }
            if (!g_axi_analyzer.analyze(axi_context_name, g_fsdb_file, axi_config)) {
                std::string err = std::string(ERROR_PREFIX) + "Failed to analyze AXI: " + axi_context_name + "\n" + END_MARKER;
                send_all(client_fd, err.c_str(), err.length());
                return;
            }
            for (size_t i = 0; i < records.size(); ++i) {
                npiFsdbTime ctx_begin = records[i].time > context_window ? records[i].time - context_window : 0;
                npiFsdbTime ctx_end = records[i].time + context_window;
                if (ctx_end < records[i].time) ctx_end = 0xFFFFFFFFFFFFFFFFULL;
                if (!g_axi_analyzer.get_transactions_in_range(axi_context_name, ctx_begin, ctx_end, axi_contexts[i])) {
                    std::string err = std::string(ERROR_PREFIX) + "AXI config not analyzed: " + axi_context_name + "\n" + END_MARKER;
                    send_all(client_fd, err.c_str(), err.length());
                    return;
                }
            }
        }
        if (use_apb_context) {
            xdebug_waveform::ApbConfig apb_config;
            if (!read_apb_from_registry(g_session_id, apb_context_name, apb_config)) {
                std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + apb_context_name + "\n" + END_MARKER;
                send_all(client_fd, err.c_str(), err.length());
                return;
            }
            if (!g_apb_analyzer.analyze(apb_context_name, g_fsdb_file, apb_config)) {
                std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + apb_context_name + "\n" + END_MARKER;
                send_all(client_fd, err.c_str(), err.length());
                return;
            }
            for (size_t i = 0; i < records.size(); ++i) {
                npiFsdbTime ctx_begin = records[i].time > context_window ? records[i].time - context_window : 0;
                npiFsdbTime ctx_end = records[i].time + context_window;
                if (ctx_end < records[i].time) ctx_end = 0xFFFFFFFFFFFFFFFFULL;
                if (!g_apb_analyzer.get_transactions_in_range(apb_context_name, ctx_begin, ctx_end, apb_contexts[i])) {
                    std::string err = std::string(ERROR_PREFIX) + "APB config not analyzed: " + apb_context_name + "\n" + END_MARKER;
                    send_all(client_fd, err.c_str(), err.length());
                    return;
                }
            }
        }
        resp = use_json
            ? format_event_records_with_context_json(records, axi_contexts, apb_contexts,
                                                     use_axi_context ? axi_context_name : nullptr,
                                                     use_apb_context ? apb_context_name : nullptr,
                                                     context_window)
            : format_event_records_with_context_text(records, axi_contexts, apb_contexts,
                                                     use_axi_context ? axi_context_name : nullptr,
                                                     use_apb_context ? apb_context_name : nullptr,
                                                     context_window);
    } else {
        resp = use_json ? format_event_records_json(records) : format_event_records_text(records);
    }
    send_all(client_fd, resp.c_str(), resp.length());
}


}  // namespace xdebug_waveform
