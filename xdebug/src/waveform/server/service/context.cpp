#include "../server_internal.h"
#include "core/npi/time_contract.h"
#include "session/session_types.h"
#include "waveform/value/logic_value.h"

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;

// Global for cleanup
std::string g_session_id;
int g_srv_fd = -1;
char g_sock_path[SOCK_PATH_LEN];
std::string g_transport = "uds";
std::string g_bind_host;
std::string g_host;
int g_port = 0;
std::string g_auth_token;
npiFsdbFileHandle g_fsdb_file = nullptr;
std::string g_fsdb_file_path;
long g_fsdb_mtime = 0;
long long g_fsdb_size = 0;
unsigned long long g_fsdb_dev = 0;
unsigned long long g_fsdb_inode = 0;
xdebug_waveform::ApbAnalyzer g_apb_analyzer;
xdebug_waveform::AxiAnalyzer g_axi_analyzer;
xdebug_waveform::EventAnalyzer g_event_analyzer;
FILE* g_debug_log = nullptr;

bool send_all(int fd, const char* buf, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = write(fd, buf + sent, len - sent);
        if (n <= 0) return false;
        sent += n;
    }
    return true;
}

bool read_command_line(int fd, char* line, size_t line_size) {
    if (!line || line_size == 0) return false;
    size_t total = 0;
    while (total < line_size - 1) {
        ssize_t n = read(fd, line + total, 1);
        if (n <= 0) return false;
        if (line[total] == '\n') break;
        total++;
    }
    line[total] = '\0';
    return true;
}

char* trim_command(char* cmd) {
    while (*cmd == ' ' || *cmd == '\t') cmd++;
    size_t len = strlen(cmd);
    while (len > 0 && (cmd[len - 1] == '\n' || cmd[len - 1] == '\r' || cmd[len - 1] == ' ')) {
        cmd[len - 1] = '\0';
        len--;
    }
    return cmd;
}

std::string json_response(const Json& j) {
    return j.dump() + "\n" + END_MARKER;
}

bool contains_xz_value(const std::string& value) {
    return logic_value_has_xz(logic_value_from_fsdb_raw(value, 'h'));
}

std::string with_value_prefix(const std::string& value, char prefix) {
    if (value.size() >= 2 && value[0] == '\'') return value;
    char p = static_cast<char>(std::tolower(static_cast<unsigned char>(prefix)));
    return std::string("'") + p + value;
}

Json wave_value_json(const std::string& raw, char prefix) {
    return logic_value_json(logic_value_from_fsdb_raw(raw, prefix));
}

Json wave_value_json(const std::string& raw, char prefix,
                     const std::string& signal_path) {
    FsdbSignalWidth width = fsdb_signal_width(g_fsdb_file, signal_path);
    return logic_value_json(logic_value_from_fsdb_raw(
        raw, prefix, width.reliable ? width.width : 0));
}

bool stat_fsdb(long& mtime,
                      long long& size,
                      unsigned long long& dev,
                      unsigned long long& inode) {
    struct stat st;
    if (stat(g_fsdb_file_path.c_str(), &st) != 0) return false;
    mtime = static_cast<long>(st.st_mtime);
    size = static_cast<long long>(st.st_size);
    dev = static_cast<unsigned long long>(st.st_dev);
    inode = static_cast<unsigned long long>(st.st_ino);
    return true;
}

bool fsdb_changed() {
    long mtime = 0;
    long long size = 0;
    unsigned long long dev = 0;
    unsigned long long inode = 0;
    if (!stat_fsdb(mtime, size, dev, inode)) return true;
    return !xdebug_core::resource_content_matches(g_fsdb_mtime,
                                                  g_fsdb_size,
                                                  mtime,
                                                  size);
}

void send_error(int client_fd, const std::string& message) {
    std::string err = std::string(ERROR_PREFIX) + message + "\n" + END_MARKER;
    send_all(client_fd, err.c_str(), err.length());
}

std::string fsdb_time_scale() {
    const char* scale = g_fsdb_file ? npi_fsdb_time_scale_unit(g_fsdb_file) : nullptr;
    return scale ? scale : "unknown";
}

bool convert_duration_to_time(const DurationSpec& duration,
                                     npiFsdbTime& out_time,
                                     std::string& error) {
    if (duration.cycle) {
        error = "TIME_SPEC_INVALID: cycle duration requires a cursor or around base time";
        return false;
    }
    if (duration.value < 0) {
        error = "TIME_SPEC_INVALID: negative duration is not allowed here";
        return false;
    }
    return xdebug_core::convert_time(g_fsdb_file,
                                     duration.value,
                                     duration.unit,
                                     out_time,
                                     error);
}

bool resolve_cycle_offset(npiFsdbTime base,
                                 const DurationSpec& offset,
                                 npiFsdbTime& out_time,
                                 std::string& error) {
    if (!std::isfinite(offset.value)) {
        error = "TIME_SPEC_INVALID: cycle offset is not finite";
        return false;
    }
    double rounded = std::round(offset.value);
    if (std::fabs(offset.value - rounded) > 1e-9) {
        error = "TIME_SPEC_INVALID: cycle offset must be an integer";
        return false;
    }
    long long cycles = static_cast<long long>(rounded);
    if (cycles == 0) {
        out_time = base;
        return true;
    }
    npiFsdbSigHandle clk = npi_fsdb_sig_by_name(g_fsdb_file, offset.clock.c_str(), NULL);
    if (!clk) {
        error = "SIGNAL_NOT_FOUND: Clock signal not found: " + offset.clock;
        return false;
    }
    ClockEdgeCursor cursor(clk, offset.posedge);
    if (!cursor.valid()) {
        error = "WAVE_QUERY_FAILED: failed to create clock edge cursor for " + offset.clock;
        return false;
    }

    npiFsdbTime edge_time = 0;
    if (cycles > 0) {
        if (!cursor.first_at_or_after(base, edge_time)) {
            error = "TIME_OUT_OF_RANGE: no clock edge after cursor time";
            return false;
        }
        if (edge_time <= base && !cursor.next(edge_time)) {
            error = "TIME_OUT_OF_RANGE: no clock edge after cursor time";
            return false;
        }
        for (long long i = 1; i < cycles; ++i) {
            if (!cursor.next(edge_time)) {
                error = "TIME_OUT_OF_RANGE: cycle offset exceeds waveform end";
                return false;
            }
        }
    } else {
        if (!cursor.prev_before(base, edge_time)) {
            error = "TIME_OUT_OF_RANGE: no clock edge before cursor time";
            return false;
        }
        for (long long i = -1; i > cycles; --i) {
            if (!cursor.prev_before(edge_time, edge_time)) {
                error = "TIME_OUT_OF_RANGE: cycle offset is before waveform start";
                return false;
            }
        }
    }
    out_time = edge_time;
    return true;
}

bool apply_duration_offset(npiFsdbTime base,
                                  DurationSpec offset,
                                  npiFsdbTime& out_time,
                                  std::string& error) {
    if (offset.cycle) {
        return resolve_cycle_offset(base, offset, out_time, error);
    }
    npiFsdbTime delta = 0;
    double sign = offset.value < 0 ? -1.0 : 1.0;
    offset.value = std::fabs(offset.value);
    if (!convert_duration_to_time(offset, delta, error)) return false;
    if (sign < 0) {
        if (base < delta) {
            error = "TIME_OUT_OF_RANGE: resolved time is before waveform start";
            return false;
        }
        out_time = base - delta;
    } else {
        out_time = base + delta;
        if (out_time < base) {
            error = "TIME_OUT_OF_RANGE: resolved time is after waveform end";
            return false;
        }
    }
    return true;
}

bool parse_user_time(const char* text,
                            bool allow_max,
                            npiFsdbTime& out_time,
                            std::string& error) {
    if (!text || text[0] == '\0') {
        error = "Invalid time: empty";
        return false;
    }
    if (allow_max && (strcasecmp(text, "max") == 0 || strcasecmp(text, "inf") == 0)) {
        out_time = 0xFFFFFFFFFFFFFFFFULL;
        return true;
    }
    ParsedTimeSpec spec;
    if (!parse_time_spec_text(text, spec, error)) return false;

    if (spec.kind == TimeSpecKind::Absolute) {
        xdebug_core::TimeParseOptions options;
        options.allow_max = allow_max;
        options.default_unit = "ns";
        return xdebug_core::parse_time(g_fsdb_file, spec.absolute_text, options, out_time, error);
    }

    std::string cursor_name = spec.cursor_name;
    CursorManager cm;
    if (spec.use_active_cursor && !cm.get_active_cursor(g_session_id, cursor_name)) {
        error = "CURSOR_NOT_FOUND: active cursor is not set";
        return false;
    }
    Cursor cursor;
    if (!cm.get_cursor(g_session_id, cursor_name, cursor)) {
        error = "CURSOR_NOT_FOUND: Cursor '" + cursor_name + "' does not exist";
        return false;
    }
    uint64_t resolved = cursor.time;
    if (spec.has_offset) {
        npiFsdbTime adjusted = 0;
        if (!apply_duration_offset(resolved, spec.offset, adjusted, error)) return false;
        resolved = adjusted;
    }
    out_time = static_cast<npiFsdbTime>(resolved);
    return true;
}

bool read_list_from_storage(const std::string& session_id, const char* list_name, SignalList& out_list) {
    ListManager lm;
    return lm.get_list(session_id, list_name, out_list);
}

std::string format_time(npiFsdbTime t) {
    return xdebug_core::format_time(g_fsdb_file, t);
}

std::string format_duration(npiFsdbTime t) {
    return xdebug_core::format_duration(g_fsdb_file, t);
}

std::pair<std::string, std::string> format_time_range(npiFsdbTime begin, npiFsdbTime end) {
    return xdebug_core::format_time_range(g_fsdb_file, begin, end);
}

bool json_time_range(const Json& args,
                            npiFsdbTime& begin,
                            npiFsdbTime& end,
                            std::string& error) {
    begin = 0;
    end = 0xFFFFFFFFFFFFFFFFULL;
    Json tr = args.value("time_range", Json::object());
    bool has_begin = (tr.is_object() && (tr.contains("begin") || tr.contains("from"))) || args.contains("begin") || args.contains("from");
    bool has_end   = (tr.is_object() && (tr.contains("end")   || tr.contains("to")))   || args.contains("end")   || args.contains("to");
    if (has_begin || has_end || !args.contains("around")) {
        auto read_time_key = [&](const char* primary, const char* alias, const char* default_val) -> std::string {
            if (tr.is_object()) {
                if (tr.contains(primary)) return tr[primary].get<std::string>();
                if (tr.contains(alias))   return tr[alias].get<std::string>();
            }
            if (args.contains(primary)) return args[primary].get<std::string>();
            if (args.contains(alias))   return args[alias].get<std::string>();
            return default_val;
        };
        std::string begin_s = read_time_key("begin", "from", "0ns");
        std::string end_s   = read_time_key("end",   "to",   "max");
        if (!parse_user_time(begin_s.c_str(), false, begin, error) ||
            !parse_user_time(end_s.c_str(), true, end, error)) {
            return false;
        }
        if (end < begin) {
            error = "TIME_RANGE_INVALID: args.time_range.end is before args.time_range.begin";
            return false;
        }
        return true;
    }

    std::string around_s = args.value("around", std::string());
    npiFsdbTime around = 0;
    if (!parse_user_time(around_s.c_str(), false, around, error)) return false;

    auto apply_window_duration = [&](const std::string& text,
                                     bool before,
                                     npiFsdbTime& out) -> bool {
        DurationSpec duration;
        if (!parse_duration_spec(text, duration, error)) return false;
        if (duration.value < 0) {
            error = "TIME_SPEC_INVALID: before/after duration must be non-negative";
            return false;
        }
        if (before) duration.value = -duration.value;
        return apply_duration_offset(around, duration, out, error);
    };

    std::string before_s = args.value("before", std::string("0ns"));
    std::string after_s = args.value("after", std::string("0ns"));
    return apply_window_duration(before_s, true, begin) &&
           apply_window_duration(after_s, false, end);
}

npiFsdbValType json_value_format(const Json& args) {
    std::string fmt = args.value("format", std::string("binary"));
    if (fmt == "hex" || fmt == "h") return npiFsdbHexStrVal;
    if (fmt == "decimal" || fmt == "dec" || fmt == "d") return npiFsdbDecStrVal;
    return npiFsdbBinStrVal;
}

std::string server_compact_expr_ws(const std::string& expr) {
    std::string out;
    for (char c : expr) {
        if (!std::isspace(static_cast<unsigned char>(c))) out.push_back(c);
    }
    return out;
}

char json_value_prefix(npiFsdbValType fmt) {
    if (fmt == npiFsdbHexStrVal) return 'h';
    if (fmt == npiFsdbDecStrVal) return 'd';
    return 'b';
}


}  // namespace xdebug_waveform
