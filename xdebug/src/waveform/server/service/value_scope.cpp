#include "../server_internal.h"
#include "../../export/waveform_exporter.h"
#include "../../axi/axi_transaction_json.h"

namespace xdebug_waveform {

void handle_value(int client_fd, const char* signal_path, npiFsdbTime time, char fmt) {
    std::string value;
    if (read_sig_value_at(g_fsdb_file, signal_path, time, fmt, value)) {
        char fmt_lower = std::tolower(static_cast<unsigned char>(fmt));
        std::string response = std::string("'") + fmt_lower + value + "\n" + END_MARKER;
        send_all(client_fd, response.c_str(), response.length());
    } else {
        std::string err = std::string(ERROR_PREFIX) + "Failed to read value for signal: " + signal_path + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_list_value(int client_fd, const char* list_name, npiFsdbTime time, char fmt, bool json) {
    SignalList list;
    if (!read_list_from_storage(g_session_id, list_name, list)) {
        std::string err = std::string(ERROR_PREFIX) + "List not found: " + list_name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    if (list.signals.empty()) {
        std::string err = std::string(ERROR_PREFIX) + "List is empty: " + list_name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    std::vector<std::string> values;
    std::vector<bool> found;
    bool all_found = read_sig_vec_value_at_with_status(g_fsdb_file, list.signals, time, fmt, values, found);

    std::string response;
    if (json) {
        Json j = Json::object();
        Json missing = Json::array();
        Json value_obj = Json::object();
        for (size_t i = 0; i < list.signals.size(); ++i) {
            value_obj[list.signals[i]] = values[i];
            if (!found[i]) missing.push_back(list.signals[i]);
        }
        if (all_found) {
            response = json_response(value_obj);
        } else {
            j["error"] = "List contains missing signals";
            j["values"] = value_obj;
            j["missing"] = missing;
            response = std::string(ERROR_PREFIX) + j.dump() + "\n" + END_MARKER;
        }
    } else {
        char fmt_lower = std::tolower(static_cast<unsigned char>(fmt));
        for (size_t i = 0; i < list.signals.size(); ++i) {
            if (found[i]) response += list.signals[i] + ":'" + fmt_lower + values[i] + "\n";
            else response += list.signals[i] + ":NOT_FOUND\n";
        }
        if (!all_found) response = std::string(ERROR_PREFIX) + "List contains missing signals\n" + response;
        response += END_MARKER;
    }
    send_all(client_fd, response.c_str(), response.length());
}

void handle_signal_check(int client_fd, const char* signal_path) {
    if (npi_fsdb_sig_by_name(g_fsdb_file, signal_path, NULL)) {
        std::string resp = std::string("OK\n") + END_MARKER;
        send_all(client_fd, resp.c_str(), resp.length());
    } else {
        std::string err = std::string(ERROR_PREFIX) + "Signal not found: " + signal_path + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_list_validate(int client_fd, const char* list_name, bool json) {
    SignalList list;
    if (!read_list_from_storage(g_session_id, list_name, list)) {
        std::string err = std::string(ERROR_PREFIX) + "List not found: " + list_name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    bool all_found = true;
    std::string text;
    Json out = Json::array();
    for (const auto& signal : list.signals) {
        bool found = npi_fsdb_sig_by_name(g_fsdb_file, signal.c_str(), NULL) != nullptr;
        if (!found) all_found = false;
        if (json) {
            Json item;
            item["signal"] = signal;
            item["status"] = found ? "ok" : "not_found";
            out.push_back(item);
        } else {
            text += signal + ": " + (found ? "OK" : "NOT_FOUND") + "\n";
        }
    }

    std::string resp;
    if (json) {
        resp = all_found ? json_response(out) : std::string(ERROR_PREFIX) + out.dump() + "\n" + END_MARKER;
    } else {
        if (!all_found) resp = std::string(ERROR_PREFIX) + "List contains missing signals\n";
        resp += text;
        resp += END_MARKER;
    }
    send_all(client_fd, resp.c_str(), resp.length());
}

void handle_scope(int client_fd, const char* scope_path, bool recursive, bool json) {
    FILE* fp = tmpfile();
    if (!fp) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to create temporary scope output\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    int ok = npi_fsdb_hier_tree_dump_sig(g_fsdb_file, fp, scope_path, recursive ? 1 : 0);
    fflush(fp);
    rewind(fp);

    std::vector<std::string> lines;
    char line[4096];
    while (fgets(line, sizeof(line), fp)) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) line[--len] = '\0';
        if (len > 0) lines.push_back(line);
    }
    fclose(fp);

    if (!ok) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to list scope: " + scope_path + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    std::string resp;
    if (json) {
        Json arr = Json::array();
        for (const auto& l : lines) arr.push_back(l);
        resp = json_response(arr);
    } else {
        for (const auto& l : lines) resp += l + "\n";
        if (lines.empty()) resp += "(no signals found)\n";
        resp += END_MARKER;
    }
    send_all(client_fd, resp.c_str(), resp.length());
}

// Helper: read an APB config from the registry file by session_id and name
bool read_apb_from_registry(const std::string& session_id, const char* name, xdebug_waveform::ApbConfig& out_config) {
    xdebug_waveform::ApbManager am;
    return am.get_apb(session_id, name, out_config);
}

bool read_axi_from_registry(const std::string& session_id, const char* name, xdebug_waveform::AxiConfig& out_config) {
    xdebug_waveform::AxiManager am;
    return am.get_axi(session_id, name, out_config);
}

void handle_list_diff(int client_fd, const char* list_name, npiFsdbTime begin_time, npiFsdbTime end_time) {
    SignalList list;
    if (!read_list_from_storage(g_session_id, list_name, list)) {
        std::string err = std::string(ERROR_PREFIX) + "List not found: " + list_name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    if (list.signals.empty()) {
        std::string err = std::string(ERROR_PREFIX) + "List is empty: " + list_name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    npiFsdbTime diff_time;
    if (find_list_diff(g_fsdb_file, list.signals, begin_time, end_time, diff_time)) {
        std::string response = format_time(diff_time) + "\n" + END_MARKER;
        send_all(client_fd, response.c_str(), response.length());
    } else {
        std::string response = "(no diff found)\n" + std::string(END_MARKER);
        send_all(client_fd, response.c_str(), response.length());
    }
}

void handle_list_export(int client_fd, const char* list_name, npiFsdbTime begin_time,
                        npiFsdbTime end_time, const char* output_dir,
                        const char* format) {
    SignalList list;
    if (!read_list_from_storage(g_session_id, list_name, list)) {
        std::string err = std::string(ERROR_PREFIX) + "List not found: " + list_name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    ListExportOptions options;
    options.session_id = g_session_id;
    options.list_name = list.name;
    options.begin = begin_time;
    options.end = end_time;
    options.format = format && *format ? format : "u64bin";
    options.output_dir = output_dir && *output_dir ? output_dir :
        xdebug_waveform_list_exports_dir(g_session_id) + "/" + list.name + "_" +
        std::to_string(begin_time) + "_" + std::to_string(end_time) + "_" +
        std::to_string(static_cast<long long>(time(nullptr)));

    ListExportResult result;
    std::string error;
    if (!export_signal_list(g_fsdb_file, list, options, result, error)) {
        std::string err = std::string(ERROR_PREFIX) + error + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    Json out;
    out["output_dir"] = result.output_dir;
    out["manifest_file"] = result.manifest_file;
    out["format"] = result.format;
    out["signal_count"] = result.signal_count;
    out["row_count"] = result.row_count;
    out["signals"] = result.signals;
    auto range = format_time_range(begin_time, end_time);
    out["begin"] = range.first;
    out["end"] = range.second;
    std::string response = json_response(out);
    send_all(client_fd, response.c_str(), response.length());
}

std::string format_apb_txn(const xdebug_waveform::ApbTransaction* txn) {
    if (!txn) return "";
    return "time=" + format_time(txn->time) + " addr='h" + txn->addr + " data='h" + txn->data;
}

std::string format_apb_txn_with_type(const xdebug_waveform::ApbTransaction* txn) {
    if (!txn) return "";
    return "time=" + format_time(txn->time) + " type=" + (txn->is_write ? "WR" : "RD")
           + " addr='h" + txn->addr + " data='h" + txn->data;
}

std::string format_apb_count_json(size_t count) {
    Json j;
    j["count"] = count;
    return json_response(j);
}

Json apb_txn_to_json(const xdebug_waveform::ApbTransaction* txn, bool include_type) {
    Json j;
    if (!txn) return j;
    j["time"] = format_time(txn->time);
    if (include_type) j["type"] = txn->is_write ? "WR" : "RD";
    j["addr"] = xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(txn->addr, 'h', txn->addr_width));
    j["data"] = xdebug_core::render_logic_value(
        xdebug_core::logic_value_from_fsdb_raw(txn->data, 'h', txn->data_width));
    j["has_error"] = txn->has_error;
    return j;
}

std::string format_apb_txn_json(const xdebug_waveform::ApbTransaction* txn) {
    if (!txn) return std::string(END_MARKER);
    Json j = apb_txn_to_json(txn, false);
    return json_response(j);
}

std::string format_apb_txn_json_with_type(const xdebug_waveform::ApbTransaction* txn) {
    if (!txn) return std::string(END_MARKER);
    Json j = apb_txn_to_json(txn, true);
    return json_response(j);
}

void handle_apb_wr(int client_fd, const char* name, const char* addr_str,
                          int num, bool last_flag, bool json) {
    xdebug_waveform::ApbConfig config;
    if (!read_apb_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    const xdebug_waveform::ApbTransaction* txn = nullptr;
    if (!addr_str && num < 0 && !last_flag) {
        size_t count = g_apb_analyzer.get_write_count(name);
        if (json) {
            std::string resp = format_apb_count_json(count);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = std::to_string(count) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
        return;
    }

    bool ok = false;
    if (addr_str) {
        uint64_t addr = strtoull(addr_str, nullptr, 0);
        if (num > 0) ok = g_apb_analyzer.get_write_by_addr_num(name, addr, (size_t)num, txn);
        else if (last_flag) ok = g_apb_analyzer.get_write_by_addr_last(name, addr, txn);
        else ok = g_apb_analyzer.get_write_by_addr(name, addr, txn);
    } else if (num > 0) {
        ok = g_apb_analyzer.get_write_by_num(name, (size_t)num, txn);
    } else if (last_flag) {
        ok = g_apb_analyzer.get_write_last(name, txn);
    }

    if (ok && txn) {
        if (json) {
            std::string resp = format_apb_txn_json(txn);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = format_apb_txn(txn) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
    } else {
        std::string err = std::string(ERROR_PREFIX) + "Not found\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_apb_rd(int client_fd, const char* name, const char* addr_str,
                          int num, bool last_flag, bool json) {
    xdebug_waveform::ApbConfig config;
    if (!read_apb_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }

    const xdebug_waveform::ApbTransaction* txn = nullptr;
    if (!addr_str && num < 0 && !last_flag) {
        size_t count = g_apb_analyzer.get_read_count(name);
        if (json) {
            std::string resp = format_apb_count_json(count);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = std::to_string(count) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
        return;
    }

    bool ok = false;
    if (addr_str) {
        uint64_t addr = strtoull(addr_str, nullptr, 0);
        if (num > 0) ok = g_apb_analyzer.get_read_by_addr_num(name, addr, (size_t)num, txn);
        else if (last_flag) ok = g_apb_analyzer.get_read_by_addr_last(name, addr, txn);
        else ok = g_apb_analyzer.get_read_by_addr(name, addr, txn);
    } else if (num > 0) {
        ok = g_apb_analyzer.get_read_by_num(name, (size_t)num, txn);
    } else if (last_flag) {
        ok = g_apb_analyzer.get_read_last(name, txn);
    }

    if (ok && txn) {
        if (json) {
            std::string resp = format_apb_txn_json(txn);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = format_apb_txn(txn) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
    } else {
        std::string err = std::string(ERROR_PREFIX) + "Not found\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_apb_begin(int client_fd, const char* name, int filter, bool json) {
    xdebug_waveform::ApbConfig config;
    if (!read_apb_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    const xdebug_waveform::ApbTransaction* txn = nullptr;
    if (g_apb_analyzer.cursor_begin(name, filter, txn) && txn) {
        if (json) {
            std::string resp = format_apb_txn_json_with_type(txn);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = format_apb_txn_with_type(txn) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
    } else {
        std::string err = std::string(ERROR_PREFIX) + "No transaction found\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_apb_next(int client_fd, const char* name, int filter, bool json) {
    xdebug_waveform::ApbConfig config;
    if (!read_apb_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    const xdebug_waveform::ApbTransaction* txn = nullptr;
    if (g_apb_analyzer.cursor_next(name, filter, txn) && txn) {
        if (json) {
            std::string resp = format_apb_txn_json_with_type(txn);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = format_apb_txn_with_type(txn) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
    } else {
        std::string err = std::string(ERROR_PREFIX) + "No more transactions\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_apb_prev(int client_fd, const char* name, int filter, bool json) {
    xdebug_waveform::ApbConfig config;
    if (!read_apb_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    const xdebug_waveform::ApbTransaction* txn = nullptr;
    if (g_apb_analyzer.cursor_prev(name, filter, txn) && txn) {
        if (json) {
            std::string resp = format_apb_txn_json_with_type(txn);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = format_apb_txn_with_type(txn) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
    } else {
        std::string err = std::string(ERROR_PREFIX) + "Already at beginning\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

void handle_apb_last(int client_fd, const char* name, int filter, bool json) {
    xdebug_waveform::ApbConfig config;
    if (!read_apb_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "APB config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    if (!g_apb_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze APB: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return;
    }
    const xdebug_waveform::ApbTransaction* txn = nullptr;
    if (g_apb_analyzer.cursor_last(name, filter, txn) && txn) {
        if (json) {
            std::string resp = format_apb_txn_json_with_type(txn);
            send_all(client_fd, resp.c_str(), resp.length());
        } else {
            std::string resp = format_apb_txn_with_type(txn) + "\n" + END_MARKER;
            send_all(client_fd, resp.c_str(), resp.length());
        }
    } else {
        std::string err = std::string(ERROR_PREFIX) + "No transaction found\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
    }
}

bool ensure_axi_analyzed(int client_fd, const char* name) {
    xdebug_waveform::AxiConfig config;
    if (!read_axi_from_registry(g_session_id, name, config)) {
        std::string err = std::string(ERROR_PREFIX) + "AXI config not found: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return false;
    }
    if (!g_axi_analyzer.analyze(name, g_fsdb_file, config)) {
        std::string err = std::string(ERROR_PREFIX) + "Failed to analyze AXI: " + name + "\n" + END_MARKER;
        send_all(client_fd, err.c_str(), err.length());
        return false;
    }
    return true;
}

Json json_array_hex(const std::vector<std::string>& values) {
    Json out = Json::array();
    for (size_t i = 0; i < values.size(); ++i) {
        out.push_back("'h" + values[i]);
    }
    return out;
}

std::string format_axi_txn(const xdebug_waveform::AxiTransaction* txn) {
    if (!txn) return "";
    std::string out = "addr_time=" + format_time(txn->addr_time)
        + " type=" + (txn->is_write ? "WR" : "RD")
        + " id='h" + txn->id
        + " addr='h" + txn->addr
        + " len='h" + txn->len
        + " beats=" + std::to_string(txn->data.size())
        + " first_data_time=" + format_time(txn->first_data_time)
        + " last_data_time=" + format_time(txn->last_data_time)
        + " resp_time=" + format_time(txn->resp_time)
        + " resp='h" + txn->resp;
    if (!txn->data.empty()) out += " data0='h" + txn->data.front();
    return out;
}

Json axi_txn_to_json(const xdebug_waveform::AxiTransaction* txn, bool include_data) {
    if (!txn) return Json();
    return axi_transaction_to_json(g_fsdb_file, *txn, include_data);
}

std::string format_axi_txn_json(const xdebug_waveform::AxiTransaction* txn) {
    if (!txn) return std::string(END_MARKER);
    Json j = axi_txn_to_json(txn, true);
    return json_response(j);
}


}  // namespace xdebug_waveform
