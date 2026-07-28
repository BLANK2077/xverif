#include "rc_generator.h"

#include "core/npi/time_contract.h"

#include <cerrno>
#include <cctype>
#include <cstring>
#include <fstream>
#include <sstream>
#include <sys/stat.h>
#include <sys/types.h>

namespace xdebug_waveform {

namespace {

bool get_string_field(const Json& obj, const char* key, std::string& out) {
    auto it = obj.find(key);
    if (it == obj.end() || !it->is_string()) return false;
    out = it->get<std::string>();
    return true;
}

std::string string_field_or(const Json& obj, const char* key, const std::string& def) {
    std::string v;
    return get_string_field(obj, key, v) ? v : def;
}

bool bool_field_or(const Json& obj, const char* key, bool def) {
    auto it = obj.find(key);
    if (it == obj.end() || !it->is_boolean()) return def;
    return it->get<bool>();
}

int int_field_or(const Json& obj, const char* key, int def) {
    auto it = obj.find(key);
    if (it == obj.end() || !it->is_number_integer()) return def;
    return it->get<int>();
}

std::string lower(std::string s) {
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

std::string quote_rc(const std::string& s) {
    std::string out = "\"";
    for (char c : s) {
        if (c == '\\' || c == '"') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('"');
    return out;
}

std::string quote_if_needed(const std::string& s) {
    if (s.empty()) return "\"\"";
    for (char c : s) {
        if (std::isspace(static_cast<unsigned char>(c)) || c == '"' || c == ';') return quote_rc(s);
    }
    return s;
}

bool parse_string_array(const Json& arr, std::vector<std::string>& out, std::string& err, const std::string& field) {
    if (!arr.is_array()) {
        err = field + " must be a string array";
        return false;
    }
    for (const auto& item : arr) {
        if (!item.is_string()) {
            err = field + " must contain only strings";
            return false;
        }
        out.push_back(item.get<std::string>());
    }
    return true;
}

std::string radix_option(const std::string& radix, std::string& err) {
    if (radix.empty()) return "";
    std::string r = lower(radix);
    if (r == "hex") return "-HEX";
    if (r == "bin" || r == "binary") return "-BIN";
    if (r == "udec" || r == "dec" || r == "unsigned_decimal") return "-UDEC";
    if (r == "oct") return "-OCT";
    if (r == "asc" || r == "ascii") return "-ASC";
    if (r == "ieee754") return "-IEEE754";
    err = "unsupported radix: " + radix;
    return "";
}

std::string notation_option(const std::string& notation, std::string& err) {
    if (notation.empty()) return "";
    std::string n = lower(notation);
    if (n == "unsigned" || n == "u") return "-UNSIGNED";
    if (n == "2comp" || n == "twos_complement") return "-2COMP";
    if (n == "1comp" || n == "ones_complement") return "-1COMP";
    if (n == "magn" || n == "magnitude") return "-MAGN";
    err = "unsupported notation: " + notation;
    return "";
}

bool append_signal_options(const RcSignal& sig, std::vector<std::string>& parts, std::string& err) {
    if (sig.waveform == "analog") {
        parts.push_back("-w");
        parts.push_back("analog");
        if (!sig.analog.display_style.empty()) {
            std::string ds = lower(sig.analog.display_style);
            if (ds != "pwl" && ds != "point") {
                err = "analog.display_style must be pwl or point";
                return false;
            }
            parts.push_back("-ds");
            parts.push_back(sig.analog.display_style);
        }
        if (sig.analog.grid_x) parts.push_back("-gx");
        if (sig.analog.grid_y) parts.push_back("-gy");
        if (sig.analog.reverse_x) parts.push_back("-rx");
        if (sig.analog.reverse_y) parts.push_back("-ry");
        if (!sig.analog.unit.empty()) {
            parts.push_back("-us");
            parts.push_back(sig.analog.unit);
        }
        for (const auto& opt : sig.analog.options) parts.push_back(opt);
    }
    if (sig.height >= 0) {
        parts.push_back("-h");
        parts.push_back(std::to_string(sig.height));
    }
    if (!sig.color.empty()) {
        parts.push_back("-c");
        parts.push_back(sig.color);
    }
    if (!sig.line_style.empty()) {
        parts.push_back("-ls");
        parts.push_back(sig.line_style);
    }
    if (sig.line_width >= 0) {
        parts.push_back("-lw");
        parts.push_back(std::to_string(sig.line_width));
    }
    std::string notation = notation_option(sig.notation, err);
    if (!err.empty()) return false;
    if (!notation.empty()) parts.push_back(notation);
    std::string radix = radix_option(sig.radix, err);
    if (!err.empty()) return false;
    if (!radix.empty()) parts.push_back(radix);
    for (const auto& opt : sig.options) parts.push_back(opt);
    return true;
}

std::string join_parts(const std::vector<std::string>& parts) {
    std::ostringstream os;
    for (size_t i = 0; i < parts.size(); ++i) {
        if (i) os << ' ';
        os << parts[i];
    }
    return os.str();
}

bool parse_signal_obj(const Json& item, RcSignal& sig, std::string& err) {
    if (item.is_string()) {
        sig.input_path = item.get<std::string>();
    } else if (item.is_object()) {
        if (!get_string_field(item, "path", sig.input_path) && !get_string_field(item, "signal", sig.input_path)) {
            err = "signal object requires path";
            return false;
        }
        sig.radix = string_field_or(item, "radix", "");
        sig.notation = string_field_or(item, "notation", "");
        sig.height = int_field_or(item, "height", -1);
        sig.color = string_field_or(item, "color", "");
        sig.line_style = string_field_or(item, "line_style", "");
        sig.line_width = int_field_or(item, "line_width", -1);
        sig.waveform = lower(string_field_or(item, "waveform", ""));
        if (item.contains("options") && !parse_string_array(item["options"], sig.options, err, "signal.options")) return false;
        if (item.contains("analog")) {
            if (!item["analog"].is_object()) {
                err = "analog must be an object";
                return false;
            }
            sig.waveform = "analog";
            const Json& a = item["analog"];
            sig.analog.display_style = string_field_or(a, "display_style", "");
            sig.analog.grid_x = bool_field_or(a, "grid_x", false);
            sig.analog.grid_y = bool_field_or(a, "grid_y", false);
            sig.analog.reverse_x = bool_field_or(a, "reverse_x", false);
            sig.analog.reverse_y = bool_field_or(a, "reverse_y", false);
            sig.analog.unit = string_field_or(a, "unit", "");
            if (a.contains("options") && !parse_string_array(a["options"], sig.analog.options, err, "analog.options")) return false;
        }
    } else {
        err = "signal must be a string or object";
        return false;
    }
    sig.rc_path = rc_dot_path_to_slash(sig.input_path, err);
    if (!err.empty()) return false;
    std::vector<std::string> unused;
    if (!append_signal_options(sig, unused, err)) return false;
    return err.empty();
}

bool parse_alias_map(const Json& obj, RcExprSignal& expr, std::string& err) {
    if (!obj.is_object()) {
        err = "expr_signals[].signals must be an object";
        return false;
    }
    for (auto it = obj.begin(); it != obj.end(); ++it) {
        if (!it.value().is_string()) {
            err = "expr signal alias path must be string: " + it.key();
            return false;
        }
        std::string rc = rc_dot_path_to_slash(it.value().get<std::string>(), err);
        if (!err.empty()) return false;
        expr.alias_paths[it.key()] = it.value().get<std::string>();
        expr.alias_rc_paths[it.key()] = rc;
    }
    return true;
}

bool is_alias_char(char c) {
    return std::isalnum(static_cast<unsigned char>(c)) || c == '_';
}

bool render_expr_aliases(RcExprSignal& expr, std::string& err) {
    if (!expr.raw_expr.empty()) {
        if (!expr.allow_raw_expr) {
            err = "raw_expr requires allow_raw_expr:true";
            return false;
        }
        expr.rendered_expr = expr.raw_expr;
        return true;
    }
    if (expr.expr.empty()) {
        err = "expr_signals[] requires expr or raw_expr";
        return false;
    }
    if (expr.alias_paths.empty()) {
        err = "expr_signals[] with expr requires signals alias map";
        return false;
    }
    std::string out;
    for (size_t i = 0; i < expr.expr.size();) {
        if (expr.expr[i] != '$') {
            out.push_back(expr.expr[i++]);
            continue;
        }
        size_t start = i + 1;
        size_t end = start;
        while (end < expr.expr.size() && is_alias_char(expr.expr[end])) ++end;
        if (end == start) {
            out.push_back(expr.expr[i++]);
            continue;
        }
        std::string alias = expr.expr.substr(start, end - start);
        auto it = expr.alias_rc_paths.find(alias);
        if (it == expr.alias_rc_paths.end()) {
            err = "unknown expr alias: " + alias;
            return false;
        }
        out += quote_rc(it->second);
        i = end;
    }
    expr.rendered_expr = out;
    return true;
}

bool parse_expr_signal(const Json& item, RcExprSignal& expr, std::string& err) {
    if (!item.is_object()) {
        err = "expr_signals[] item must be an object";
        return false;
    }
    if (!get_string_field(item, "name", expr.name) || expr.name.empty()) {
        err = "expr_signals[] requires name";
        return false;
    }
    expr.bit_size = int_field_or(item, "bit_size", -1);
    expr.notation = string_field_or(item, "notation", "");
    expr.expr = string_field_or(item, "expr", "");
    expr.raw_expr = string_field_or(item, "raw_expr", "");
    expr.allow_raw_expr = bool_field_or(item, "allow_raw_expr", false);
    if (item.contains("signals") && !parse_alias_map(item["signals"], expr, err)) return false;
    return render_expr_aliases(expr, err);
}

bool parse_group(const Json& item, RcGroup& group, std::string& err);

bool parse_groups_array(const Json& arr, std::vector<RcGroup>& groups, std::string& err) {
    if (!arr.is_array()) {
        err = "groups/subgroups must be an array";
        return false;
    }
    for (const auto& item : arr) {
        RcGroup g;
        if (!parse_group(item, g, err)) return false;
        groups.push_back(g);
    }
    return true;
}

bool parse_group(const Json& item, RcGroup& group, std::string& err) {
    if (!item.is_object()) {
        err = "group item must be an object";
        return false;
    }
    if (!get_string_field(item, "name", group.name) || group.name.empty()) {
        err = "group requires name";
        return false;
    }
    if (item.contains("expanded")) {
        err = "group.expanded is not supported; rc.generate emits addGroup/addSubGroup without -e";
        return false;
    }
    if (item.contains("signals")) {
        if (!item["signals"].is_array()) {
            err = "group.signals must be an array";
            return false;
        }
        for (const auto& s : item["signals"]) {
            RcSignal sig;
            if (!parse_signal_obj(s, sig, err)) return false;
            group.signals.push_back(sig);
        }
    }
    if (item.contains("expr_signals")) {
        if (!item["expr_signals"].is_array()) {
            err = "group.expr_signals must be an array";
            return false;
        }
        for (const auto& e : item["expr_signals"]) {
            RcExprSignal expr;
            if (!parse_expr_signal(e, expr, err)) return false;
            group.expr_signals.push_back(expr);
        }
    }
    if (item.contains("subgroups") && !parse_groups_array(item["subgroups"], group.subgroups, err)) return false;
    return true;
}

bool parse_user_markers(const Json& arr, std::vector<RcUserMarker>& markers, std::string& err) {
    if (!arr.is_array()) {
        err = "user_markers must be an array";
        return false;
    }
    for (const auto& item : arr) {
        if (!item.is_object()) {
            err = "user_markers[] must be an object";
            return false;
        }
        RcUserMarker marker;
        if (!get_string_field(item, "name", marker.name) || marker.name.empty()) {
            err = "user_markers[] requires name";
            return false;
        }
        if (!get_string_field(item, "time", marker.time) || marker.time.empty()) {
            err = "user_markers[] requires time";
            return false;
        }
        marker.color = string_field_or(item, "color", "");
        marker.linestyle = string_field_or(item, "linestyle", "");
        markers.push_back(marker);
    }
    return true;
}

void collect_group_signals(const RcGroup& group, std::vector<RcSignalRef>& refs) {
    for (const auto& sig : group.signals) {
        refs.push_back({"signal", sig.input_path, sig.rc_path, group.name});
    }
    for (const auto& expr : group.expr_signals) {
        for (const auto& kv : expr.alias_paths) {
            refs.push_back({"expr_alias", kv.second, expr.alias_rc_paths.at(kv.first), expr.name + "." + kv.first});
        }
    }
    for (const auto& sub : group.subgroups) collect_group_signals(sub, refs);
}

void count_group(const RcGroup& group, int& group_count, int& signal_count, int& expr_count) {
    group_count++;
    signal_count += static_cast<int>(group.signals.size());
    expr_count += static_cast<int>(group.expr_signals.size());
    for (const auto& sub : group.subgroups) count_group(sub, group_count, signal_count, expr_count);
}

void render_expr_definitions(std::ostringstream& os, const RcGroup& group) {
    for (const auto& expr : group.expr_signals) {
        std::vector<std::string> parts;
        parts.push_back("addExprSig");
        if (expr.bit_size >= 0) {
            parts.push_back("-b");
            parts.push_back(std::to_string(expr.bit_size));
        }
        if (!expr.notation.empty()) {
            parts.push_back("-n");
            parts.push_back(expr.notation);
        }
        parts.push_back(quote_if_needed(expr.name));
        os << join_parts(parts) << " " << expr.rendered_expr << "\n";
    }
    for (const auto& sub : group.subgroups) render_expr_definitions(os, sub);
}

void render_group(std::ostringstream& os, const RcGroup& group, bool subgroup) {
    os << (subgroup ? "addSubGroup" : "addGroup");
    os << " " << quote_rc(group.name) << "\n";
    for (const auto& sig : group.signals) {
        std::vector<std::string> parts;
        parts.push_back("addSignal");
        std::string err;
        append_signal_options(sig, parts, err);
        parts.push_back(sig.rc_path);
        os << join_parts(parts) << "\n";
    }
    for (const auto& expr : group.expr_signals) {
        os << "addSignal -h 18 " << quote_if_needed("/" + expr.name) << "\n";
    }
    for (const auto& sub : group.subgroups) render_group(os, sub, true);
}

bool mkdir_one(const std::string& path, std::string& err) {
    if (path.empty()) return true;
    struct stat st;
    if (stat(path.c_str(), &st) == 0) {
        if (S_ISDIR(st.st_mode)) return true;
        err = "path exists but is not a directory: " + path;
        return false;
    }
    if (mkdir(path.c_str(), 0775) == 0) return true;
    if (errno == EEXIST) return true;
    err = "failed to create directory " + path + ": " + std::strerror(errno);
    return false;
}

bool mkdir_parent_dirs(const std::string& file, std::string& err) {
    size_t slash = file.find_last_of('/');
    if (slash == std::string::npos) return true;
    std::string dir = file.substr(0, slash);
    if (dir.empty()) return true;
    std::string cur;
    size_t pos = 0;
    if (dir[0] == '/') {
        cur = "/";
        pos = 1;
    }
    while (pos <= dir.size()) {
        size_t next = dir.find('/', pos);
        std::string part = dir.substr(pos, next == std::string::npos ? std::string::npos : next - pos);
        if (!part.empty()) {
            if (!cur.empty() && cur[cur.size() - 1] != '/') cur += "/";
            cur += part;
            if (!mkdir_one(cur, err)) return false;
        }
        if (next == std::string::npos) break;
        pos = next + 1;
    }
    return true;
}

} // namespace

std::string rc_dot_path_to_slash(const std::string& path, std::string& err) {
    if (path.empty()) {
        err = "signal path must not be empty";
        return "";
    }
    if (path[0] == '/') {
        err = "signal path must use dot hierarchy, not rc slash path: " + path;
        return "";
    }
    for (char c : path) {
        if (std::isspace(static_cast<unsigned char>(c))) {
            err = "signal path must not contain whitespace: " + path;
            return "";
        }
    }
    std::string out = "/";
    for (char c : path) out.push_back(c == '.' ? '/' : c);
    return out;
}

bool parse_rc_config_json(const Json& doc, RcConfig& cfg, std::string& err) {
    if (!doc.is_object()) {
        err = "rc config JSON must be an object";
        return false;
    }
    cfg.file_time_scale = string_field_or(doc, "file_time_scale", cfg.file_time_scale);
    if (doc.contains("window_time_unit")) {
        err = "window_time_unit is not supported; rc.generate always emits windowTimeUnit 1ns";
        return false;
    }
    cfg.signal_spacing = int_field_or(doc, "signal_spacing", cfg.signal_spacing);
    cfg.cursor = string_field_or(doc, "cursor", "");
    cfg.main_marker = string_field_or(doc, "main_marker", "");
    cfg.top = int_field_or(doc, "top", 0);
    cfg.cur_status = string_field_or(doc, "cur_status", "ByValue");
    if (doc.contains("zoom")) {
        if (!doc["zoom"].is_object()) {
            err = "zoom must be an object";
            return false;
        }
        cfg.zoom_begin = string_field_or(doc["zoom"], "begin", "");
        cfg.zoom_end = string_field_or(doc["zoom"], "end", "");
        if (cfg.zoom_begin.empty() != cfg.zoom_end.empty()) {
            err = "zoom requires both begin and end";
            return false;
        }
    }
    if (!doc.contains("groups") || !parse_groups_array(doc["groups"], cfg.groups, err)) return false;
    if (doc.contains("user_markers") && !parse_user_markers(doc["user_markers"], cfg.user_markers, err)) return false;
    return true;
}

bool validate_rc_time_refs(const RcConfig& cfg, npiFsdbFileHandle fsdb, std::string& err) {
    for (const auto& ref : collect_rc_time_refs(cfg)) {
        xdebug_core::TimeParseOptions options;
        options.allow_max = ref.allow_max;
        options.use_fsdb_max = ref.allow_max;
        options.default_unit = "ns";
        npiFsdbTime value = 0;
        std::string parse_error;
        if (!xdebug_core::parse_time(fsdb, ref.spec, options, value, parse_error)) {
            err = ref.kind + " '" + ref.owner + "': " + parse_error;
            return false;
        }
    }
    return true;
}

bool normalize_rc_user_marker_times(RcConfig& cfg, npiFsdbFileHandle fsdb, std::string& err) {
    for (auto& marker : cfg.user_markers) {
        if (!xdebug_core::has_explicit_time_unit(marker.time)) {
            err = "user_marker '" + marker.name + "' time must include an explicit unit";
            return false;
        }
        xdebug_core::TimeParseOptions options;
        options.default_unit = "ns";
        npiFsdbTime value = 0;
        std::string parse_error;
        if (!xdebug_core::parse_time(fsdb, marker.time, options, value, parse_error)) {
            err = "user_marker '" + marker.name + "': " + parse_error;
            return false;
        }
        std::string formatted;
        if (!xdebug_core::format_time_in_unit(fsdb, value, "ns", formatted, parse_error)) {
            err = "user_marker '" + marker.name + "': " + parse_error;
            return false;
        }
        if (formatted.size() < 2 || formatted.substr(formatted.size() - 2) != "ns") {
            err = "user_marker '" + marker.name + "': failed to format time in ns";
            return false;
        }
        marker.time = formatted.substr(0, formatted.size() - 2);
    }
    return true;
}

std::string render_signal_rc(const RcConfig& cfg) {
    std::ostringstream os;
    os << "; Generated by xdebug rc.generate\n";
    os << "; Signal list/view rc only; open the FSDB separately in nWave.\n";
    os << "windowTimeUnit 1ns\n";
    os << "fileTimeScale " << cfg.file_time_scale << "\n";
    os << "signalSpacing " << cfg.signal_spacing << "\n";
    if (!cfg.zoom_begin.empty() && !cfg.zoom_end.empty()) os << "zoom " << cfg.zoom_begin << " " << cfg.zoom_end << "\n";
    if (!cfg.cursor.empty()) os << "cursor " << cfg.cursor << "\n";
    if (!cfg.main_marker.empty()) os << "marker " << cfg.main_marker << "\n";
    os << "top " << cfg.top << "\n";
    os << "curSTATUS " << cfg.cur_status << "\n";
    for (const auto& marker : cfg.user_markers) {
        os << "userMarker " << marker.time << " " << quote_if_needed(marker.name);
        if (!marker.color.empty()) os << " " << marker.color;
        if (!marker.linestyle.empty()) os << " " << marker.linestyle;
        os << "\n";
    }
    for (const auto& group : cfg.groups) render_expr_definitions(os, group);
    for (const auto& group : cfg.groups) render_group(os, group, false);
    return os.str();
}

std::vector<RcSignalRef> collect_rc_signal_refs(const RcConfig& cfg) {
    std::vector<RcSignalRef> refs;
    for (const auto& group : cfg.groups) collect_group_signals(group, refs);
    return refs;
}

std::vector<RcTimeRef> collect_rc_time_refs(const RcConfig& cfg) {
    std::vector<RcTimeRef> refs;
    if (!cfg.cursor.empty()) refs.push_back({"cursor", cfg.cursor, "cursor", false});
    if (!cfg.main_marker.empty()) refs.push_back({"main_marker", cfg.main_marker, "main_marker", false});
    if (!cfg.zoom_begin.empty()) refs.push_back({"zoom.begin", cfg.zoom_begin, "zoom", false});
    if (!cfg.zoom_end.empty()) refs.push_back({"zoom.end", cfg.zoom_end, "zoom", true});
    for (const auto& marker : cfg.user_markers) refs.push_back({"user_marker", marker.time, marker.name, false});
    return refs;
}

Json rc_config_counts(const RcConfig& cfg) {
    int group_count = 0;
    int signal_count = 0;
    int expr_count = 0;
    for (const auto& group : cfg.groups) count_group(group, group_count, signal_count, expr_count);
    return {{"group_count", group_count},
            {"signal_count", signal_count},
            {"expr_signal_count", expr_count},
            {"marker_count", cfg.user_markers.size()}};
}

Json rc_preview_lines(const std::string& text, int max_lines) {
    Json out = Json::array();
    if (max_lines <= 0) return out;
    std::istringstream is(text);
    std::string line;
    int count = 0;
    while (count < max_lines && std::getline(is, line)) {
        out.push_back(line);
        ++count;
    }
    return out;
}

bool write_text_file_creating_dirs(const std::string& path, const std::string& text, std::string& err) {
    if (path.empty()) {
        err = "rc_path must not be empty";
        return false;
    }
    if (!mkdir_parent_dirs(path, err)) return false;
    std::ofstream os(path.c_str(), std::ios::out | std::ios::trunc);
    if (!os) {
        err = "failed to open rc_path for write: " + path;
        return false;
    }
    os << text;
    if (!os) {
        err = "failed to write rc_path: " + path;
        return false;
    }
    return true;
}

} // namespace xdebug_waveform
