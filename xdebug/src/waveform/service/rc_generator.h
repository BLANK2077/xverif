#pragma once

#include "json.hpp"
#include "npi_fsdb.h"

#include <map>
#include <string>
#include <vector>

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;

struct RcAnalogOptions {
    std::string display_style;
    bool grid_x = false;
    bool grid_y = false;
    bool reverse_x = false;
    bool reverse_y = false;
    std::string unit;
    std::vector<std::string> options;
};

struct RcSignal {
    std::string input_path;
    std::string rc_path;
    std::string radix;
    std::string notation;
    int height = -1;
    std::string color;
    std::string line_style;
    int line_width = -1;
    std::string waveform;
    RcAnalogOptions analog;
    std::vector<std::string> options;
};

struct RcExprSignal {
    std::string name;
    int bit_size = -1;
    std::string notation;
    std::string expr;
    std::string raw_expr;
    bool allow_raw_expr = false;
    std::map<std::string, std::string> alias_paths;
    std::map<std::string, std::string> alias_rc_paths;
    std::string rendered_expr;
};

struct RcGroup {
    std::string name;
    std::vector<RcSignal> signals;
    std::vector<RcExprSignal> expr_signals;
    std::vector<RcGroup> subgroups;
};

struct RcUserMarker {
    std::string name;
    std::string time;
    std::string color;
    std::string linestyle;
};

struct RcConfig {
    std::string file_time_scale = "1ns";
    int signal_spacing = 5;
    std::string cursor;
    std::string main_marker;
    std::string zoom_begin;
    std::string zoom_end;
    int top = 0;
    std::string cur_status = "ByValue";
    std::vector<RcGroup> groups;
    std::vector<RcUserMarker> user_markers;
};

struct RcSignalRef {
    std::string kind;
    std::string input_path;
    std::string rc_path;
    std::string owner;
    RcSignalRef() {}
    RcSignalRef(const std::string& k, const std::string& in, const std::string& rc, const std::string& own)
        : kind(k), input_path(in), rc_path(rc), owner(own) {}
};

struct RcTimeRef {
    std::string kind;
    std::string spec;
    std::string owner;
    bool allow_max = false;
    RcTimeRef() {}
    RcTimeRef(const std::string& k, const std::string& s, const std::string& own, bool max_ok)
        : kind(k), spec(s), owner(own), allow_max(max_ok) {}
};

bool parse_rc_config_json(const Json& doc, RcConfig& cfg, std::string& err);
bool validate_rc_time_refs(const RcConfig& cfg, npiFsdbFileHandle fsdb, std::string& err);
bool normalize_rc_user_marker_times(RcConfig& cfg, npiFsdbFileHandle fsdb, std::string& err);
std::string rc_dot_path_to_slash(const std::string& path, std::string& err);
std::string render_signal_rc(const RcConfig& cfg);
std::vector<RcSignalRef> collect_rc_signal_refs(const RcConfig& cfg);
std::vector<RcTimeRef> collect_rc_time_refs(const RcConfig& cfg);
Json rc_config_counts(const RcConfig& cfg);
Json rc_preview_lines(const std::string& text, int max_lines);
bool write_text_file_creating_dirs(const std::string& path, const std::string& text, std::string& err);

} // namespace xdebug_waveform
