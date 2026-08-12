#include "service/trace_source_path_formatter.h"
#include "service/contract_bound_request.h"

#include "api/text_response_builder.h"
#include "common/env_config.h"
#include "core/output/completeness.h"
#include "core/value/logic_value.h"

#include "npi.h"
#include "npi_hdl.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>

namespace xdebug_design {

namespace {

const int kDefaultTraceResultLimit = 10;

std::string scalar_text(const Json& object, const char* key) {
    if (!object.is_object() || !object.contains(key)) return std::string();
    const Json& value = object[key];
    if (!xdebug::is_xout_scalar_json(value)) return std::string();
    return xdebug::json_to_xout_value(value);
}

std::string ambiguous_xout_value(const Json& value) {
    if (value.is_null()) return "null";
    if (!value.is_string()) return xdebug::json_to_xout_value(value);

    std::string text = value.get<std::string>();
    size_t tick = text.find('\'');
    if (tick != std::string::npos && tick + 1 < text.size()) {
        char radix = static_cast<char>(std::tolower(
            static_cast<unsigned char>(text[tick + 1])));
        bool valid_width = tick == 0;
        if (tick > 0) {
            valid_width = true;
            for (size_t i = 0; i < tick; ++i) {
                if (!std::isdigit(static_cast<unsigned char>(text[i]))) {
                    valid_width = false;
                    break;
                }
            }
        }
        if (valid_width && (radix == 'h' || radix == 'b' || radix == 'd')) return text;
    }

    std::string bits;
    bits.reserve(text.size());
    for (char ch : text) {
        char lower = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        if (lower == '_' || std::isspace(static_cast<unsigned char>(lower))) continue;
        if (lower != '0' && lower != '1' && lower != 'x' && lower != 'z') return text;
        bits.push_back(lower);
    }
    if (bits.empty()) return text;
    return xdebug_core::logic_value_compact_string(
        xdebug_core::logic_value_from_bits(bits, static_cast<int>(bits.size())));
}

std::string render_ambiguous_rhs_xout(const Json& ambiguity) {
    if (!ambiguity.is_object()) return std::string();
    std::vector<std::vector<std::string>> rows;
    const std::string active_time = ambiguity.value("active_time", std::string());
    const Json statements = ambiguity.value("statements", Json::array());
    if (statements.is_array()) {
        for (const auto& statement : statements) {
            const Json samples = statement.value("rhs_samples", Json::array());
            if (!samples.is_array()) continue;
            for (const auto& sample : samples) {
                const Json before = sample.value("before", Json::object());
                const Json after = sample.value("after", Json::object());
                rows.push_back({
                    sample.value("signal", std::string()),
                    active_time,
                    ambiguous_xout_value(before.value("value", Json())),
                    ambiguous_xout_value(after.value("value", Json()))
                });
            }
        }
    }
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_section("ambiguous_rhs_samples");
    out.emit_table({"signal", "time", "before", "after"}, rows);
    return out.str();
}

std::string trim_copy(const std::string& input) {
    size_t begin = 0;
    while (begin < input.size() && std::isspace(static_cast<unsigned char>(input[begin]))) ++begin;
    size_t end = input.size();
    while (end > begin && std::isspace(static_cast<unsigned char>(input[end - 1]))) --end;
    return input.substr(begin, end - begin);
}

bool looks_like_signal_name(const std::string& text) {
    if (text.empty() || text.find("npi") == 0) return false;
    size_t last_dot = text.rfind('.');
    if (last_dot != std::string::npos) {
        std::string tail = text.substr(last_dot + 1);
        if (tail == "if" || tail == "assign") return false;
    }
    bool has_dot = false;
    bool has_alpha = false;
    for (char ch : text) {
        unsigned char uch = static_cast<unsigned char>(ch);
        if (std::isalpha(uch) || ch == '_') has_alpha = true;
        if (ch == '.') has_dot = true;
        if (std::isalnum(uch) || ch == '_' || ch == '$' || ch == '.' ||
            ch == '[' || ch == ']' || ch == ':') {
            continue;
        }
        return false;
    }
    return has_alpha && has_dot;
}

std::string signal_name_from_text(std::string text) {
    text = trim_copy(text);
    if (looks_like_signal_name(text)) return text;
    size_t comma = text.find(',');
    if (comma != std::string::npos) text = trim_copy(text.substr(comma + 1));
    size_t cut = text.find_first_of(",;={ \t");
    if (cut != std::string::npos) text = trim_copy(text.substr(0, cut));
    return looks_like_signal_name(text) ? text : std::string();
}

int scalar_int(const Json& object, const char* key) {
    if (!object.is_object() || !object.contains(key)) return 0;
    const Json& value = object[key];
    if (value.is_number_integer()) return value.get<int>();
    if (value.is_number_unsigned()) return static_cast<int>(value.get<unsigned int>());
    if (value.is_string()) {
        try { return std::stoi(value.get<std::string>()); } catch (...) { return 0; }
    }
    return 0;
}

int resolved_context_lines(int context_lines) {
    return context_lines >= 0 ? context_lines : xdebug_core::xdebug_trace_source_context_lines();
}

Json source_lines_from_file_range(const std::string& file,
                                  int first_line,
                                  int last_line,
                                  const std::set<int>& active_lines,
                                  int context_lines);

void append_unique(std::vector<std::string>& out, const std::string& value) {
    if (value.empty()) return;
    if (std::find(out.begin(), out.end(), value) == out.end()) out.push_back(value);
}

void append_signal(std::vector<std::string>& out, const std::string& value) {
    append_unique(out, signal_name_from_text(value));
}

Json strings_to_json(const std::vector<std::string>& values) {
    Json out = Json::array();
    for (const auto& value : values) out.push_back(value);
    return out;
}

std::vector<std::string> signal_path_from_edge(const Json& edge,
                                               const std::string& signal,
                                               const std::string& mode) {
    std::vector<std::string> path;
    std::string from = scalar_text(edge, "from");
    std::string to = scalar_text(edge, "to");
    if (mode == "load") {
        append_signal(path, from.empty() ? signal : from);
        append_signal(path, to);
    } else {
        append_signal(path, from);
        append_signal(path, to.empty() ? signal : to);
    }
    if (path.empty()) append_signal(path, signal);
    return path;
}

std::vector<std::string> signal_path_from_record(const Json& record,
                                                 const std::string& signal,
                                                 const std::string& mode) {
    std::vector<std::string> path;
    std::string related = scalar_text(record, "signal");
    if (mode == "load") {
        append_signal(path, signal);
        append_signal(path, related);
    } else {
        append_signal(path, related);
        append_signal(path, signal);
    }
    if (path.empty()) append_signal(path, signal);
    return path;
}

void add_path_if_valid(Json& paths,
                       std::set<std::string>& seen,
                       const std::string& file,
                       int line,
                       const std::vector<std::string>& signal_path) {
    if (file.empty() || line <= 0 || signal_path.empty()) return;
    std::ostringstream key;
    key << file << ":" << line;
    for (const auto& signal : signal_path) key << "|" << signal;
    if (!seen.insert(key.str()).second) return;
    Json item = make_source_path_item_from_location(file, line, signal_path);
    if (!item.empty()) paths.push_back(item);
}

int resolved_result_limit(int max_results) {
    return max_results > 0 ? max_results : kDefaultTraceResultLimit;
}

bool apply_result_limit(Json& items, int max_results) {
    if (!items.is_array()) return false;
    int limit = resolved_result_limit(max_results);
    if (static_cast<int>(items.size()) <= limit) return false;
    Json limited = Json::array();
    for (int i = 0; i < limit; ++i) limited.push_back(items[static_cast<size_t>(i)]);
    items = limited;
    return true;
}

std::string limit_hint(int max_results) {
    int limit = resolved_result_limit(max_results);
    return "returned first " + std::to_string(limit) +
           " trace entries; increase limits.max_results to return all results";
}

void add_limit_hint(Json& summary, bool truncated, int max_results) {
    if (!truncated || !summary.is_object()) return;
    summary["limit_hint"] = limit_hint(max_results);
}

std::vector<std::string> trace_analysis_truncation_scopes(const Json& raw,
                                                          bool analysis_complete) {
    const Json& scopes = raw.at("truncation_scopes");
    if (!scopes.is_array()) {
        throw std::logic_error("trace truncation_scopes must be an array");
    }
    std::vector<std::string> out;
    for (const auto& scope : scopes) {
        if (!scope.is_string()) {
            throw std::logic_error("trace truncation_scopes entries must be strings");
        }
        append_unique(out, scope.get<std::string>());
    }
    const bool has_analysis_scope =
        std::find(out.begin(), out.end(), "analysis_trace_resolution") != out.end() ||
        std::find(out.begin(), out.end(), "analysis_internal_json") != out.end();
    if (analysis_complete && !out.empty()) {
        throw std::logic_error("complete trace analysis cannot declare a truncation scope");
    }
    if (!analysis_complete && !has_analysis_scope) {
        throw std::logic_error(
            "incomplete trace analysis must declare an analysis truncation scope");
    }
    return out;
}

Json source_lines_from_file(const std::string& file, int line, int context_lines) {
    std::set<int> active_lines;
    active_lines.insert(line);
    return source_lines_from_file_range(file, line, line, active_lines, context_lines);
}

Json source_lines_from_file_range(const std::string& file,
                                  int first_line,
                                  int last_line,
                                  const std::set<int>& active_lines,
                                  int context_lines) {
    Json context = Json::array();
    if (file.empty() || first_line <= 0 || last_line <= 0) return context;
    if (first_line > last_line) std::swap(first_line, last_line);
    std::ifstream in(file);
    if (!in) return context;
    std::vector<std::string> lines;
    std::string text;
    while (std::getline(in, text)) lines.push_back(text);
    if (first_line > static_cast<int>(lines.size())) return context;
    int begin = std::max(1, first_line - context_lines);
    int end = std::min(static_cast<int>(lines.size()), last_line + context_lines);
    for (int i = begin; i <= end; ++i) {
        context.push_back({{"line", i}, {"text", lines[i - 1]}, {"active", active_lines.count(i) > 0}});
    }
    return context;
}

std::string signal_path_text(const Json& item) {
    const Json signal_path = item.value("signal_path", Json::array());
    std::ostringstream path;
    if (!signal_path.is_array()) return std::string();
    for (size_t i = 0; i < signal_path.size(); ++i) {
        if (!signal_path[i].is_string()) continue;
        if (path.tellp() > 0) path << " -> ";
        path << signal_path[i].get<std::string>();
    }
    return path.str();
}

struct SourceRenderItem {
    std::string file;
    int line = 0;
    int hop = 0;
    bool has_hop = false;
    std::string chain_id;
    std::string time;
    std::string active_time;
    bool has_x_onset_time = false;
    std::string relation;
    std::string signal_path;
};

struct SourceRenderGroup {
    std::string file;
    int first_line = 0;
    int last_line = 0;
    int last_seen_line = 0;
    std::vector<SourceRenderItem> items;
};

std::vector<SourceRenderItem> collect_source_items(const Json& items, bool chain) {
    std::vector<SourceRenderItem> out;
    if (!items.is_array()) return out;
    for (const auto& item : items) {
        if (!item.is_object()) continue;
        SourceRenderItem render_item;
        render_item.file = scalar_text(item, "file");
        render_item.line = scalar_int(item, "line");
        render_item.signal_path = signal_path_text(item);
        render_item.has_hop = chain;
        render_item.hop = item.value("index", static_cast<int>(out.size()));
        render_item.chain_id = scalar_text(item, "chain_id");
        render_item.has_x_onset_time = item.contains("x_onset_time");
        render_item.time = render_item.has_x_onset_time
            ? scalar_text(item, "x_onset_time") : scalar_text(item, "time");
        render_item.active_time = scalar_text(item, "active_time");
        render_item.relation = scalar_text(item, "relation");
        if (render_item.file.empty() || render_item.line <= 0 || render_item.signal_path.empty()) continue;
        out.push_back(render_item);
    }
    return out;
}

std::vector<SourceRenderGroup> group_source_items(const std::vector<SourceRenderItem>& items,
                                                  int merge_threshold_lines) {
    std::vector<SourceRenderGroup> groups;
    for (const auto& item : items) {
        bool merged = false;
        if (!groups.empty()) {
            SourceRenderGroup& last = groups.back();
            if (last.file == item.file && std::abs(item.line - last.last_seen_line) < merge_threshold_lines) {
                last.first_line = std::min(last.first_line, item.line);
                last.last_line = std::max(last.last_line, item.line);
                last.last_seen_line = item.line;
                last.items.push_back(item);
                merged = true;
            }
        }
        if (!merged) {
            SourceRenderGroup group;
            group.file = item.file;
            group.first_line = item.line;
            group.last_line = item.line;
            group.last_seen_line = item.line;
            group.items.push_back(item);
            groups.push_back(group);
        }
    }
    return groups;
}

void append_source_context_text(std::string& text, const Json& context) {
    if (context.is_array()) {
        for (const auto& row : context) {
            if (!row.is_object()) continue;
            int row_line = scalar_int(row, "line");
            std::ostringstream prefix;
            prefix << (row.value("active", false) ? ">" : " ")
                   << std::setw(4) << row_line << " | ";
            text += prefix.str() + row.value("text", std::string()) + "\n";
        }
    }
}

std::string active_signals_table(const SourceRenderGroup& group) {
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_section("active_signals");
    std::vector<std::vector<std::string>> rows;
    std::set<std::string> seen;
    bool x_time_semantics = false;
    for (const auto& item : group.items) {
        if (item.has_x_onset_time) {
            x_time_semantics = true;
            break;
        }
    }
    for (const auto& item : group.items) {
        std::ostringstream key;
        if (item.has_hop) key << item.chain_id << "|" << item.hop << "|";
        key << item.line << "|" << item.signal_path;
        if (!seen.insert(key.str()).second) continue;
        if (item.has_hop) {
            if (x_time_semantics) {
                rows.push_back({item.chain_id.empty() ? "c0" : item.chain_id,
                                std::to_string(item.hop), item.time,
                                item.active_time, item.relation,
                                std::to_string(item.line), item.signal_path});
            } else {
                rows.push_back({item.chain_id.empty() ? "c0" : item.chain_id,
                                std::to_string(item.hop), item.time, item.relation,
                                std::to_string(item.line), item.signal_path});
            }
        } else {
            rows.push_back({std::to_string(item.line), item.signal_path});
        }
    }
    if (rows.empty()) return std::string();
    if (group.items.empty() || !group.items.front().has_hop) {
        out.emit_table({"line", "signal_path"}, rows);
    } else if (x_time_semantics) {
        out.emit_table({"chain", "hop", "x_onset_time", "active_time",
                        "relation", "line", "signal_path"}, rows);
    } else {
        out.emit_table({"chain", "hop", "time", "relation", "line", "signal_path"}, rows);
    }
    return out.str();
}

void emit_source_group_xout(std::string& text, const SourceRenderGroup& group, int context_lines) {
    if (group.file.empty() || group.items.empty()) return;
    std::set<int> active_lines;
    for (const auto& item : group.items) active_lines.insert(item.line);
    Json context = source_lines_from_file_range(group.file,
                                                group.first_line,
                                                group.last_line,
                                                active_lines,
                                                context_lines);
    if (context.empty()) return;
    if (!text.empty() && text.back() != '\n') text.push_back('\n');
    if (!text.empty()) text.push_back('\n');
    text += "source: " + group.file + ":" + std::to_string(group.first_line);
    if (group.last_line != group.first_line) text += "-" + std::to_string(group.last_line);
    text += "\n";
    append_source_context_text(text, context);
    std::string table = active_signals_table(group);
    if (!table.empty()) {
        if (!text.empty() && text.back() != '\n') text.push_back('\n');
        text.push_back('\n');
        text += table;
    }
}

void append_depth_frontiers_xout(std::string& text, const Json& frontiers) {
    if (!frontiers.is_array() || frontiers.empty()) return;
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_section("depth_frontiers");
    std::vector<std::vector<std::string>> rows;
    bool has_continue_time = false;
    for (const auto& item : frontiers) {
        if (!item.is_object()) continue;
        has_continue_time = has_continue_time || item.contains("continue_time");
        rows.push_back({scalar_text(item, "chain_id"), scalar_text(item, "signal"),
                        item.contains("continue_time")
                            ? scalar_text(item, "continue_time") : scalar_text(item, "time"),
                        scalar_text(item, "value"),
                        scalar_text(item, "x_mask"),
                        scalar_text(item, "stopped_after_depth")});
    }
    if (rows.empty()) return;
    out.emit_table({"chain", "signal", has_continue_time ? "continue_time" : "time",
                    "value", "x_mask", "stopped_after_depth"}, rows);
    while (!text.empty() && text.back() == '\n') text.pop_back();
    text += "\n\n" + out.str();
}

void append_next_actions_xout(std::string& text, const Json& actions) {
    if (!actions.is_array() || actions.empty()) return;
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_section("next");
    std::vector<std::vector<std::string>> rows;
    for (const auto& item : actions) {
        if (!item.is_object()) continue;
        Json args = item.value("args", Json::object());
        Json limits = item.value("limits", Json::object());
        rows.push_back({scalar_text(item, "chain_id"), scalar_text(item, "reason"),
                        scalar_text(item, "action"), scalar_text(args, "signal"),
                        scalar_text(args, "time"), scalar_text(limits, "max_depth"),
                        scalar_text(limits, "max_chains")});
    }
    if (rows.empty()) return;
    out.emit_table({"chain", "mode", "action", "signal", "time", "max_depth",
                    "max_chains"}, rows);
    while (!text.empty() && text.back() == '\n') text.pop_back();
    text += "\n\n" + out.str();
}

void append_chain_states_xout(std::string& text, const Json& chains) {
    if (!chains.is_array() || chains.empty()) return;
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_section("chains");
    std::vector<std::vector<std::string>> rows;
    bool has_x_onset_time = false;
    for (const auto& chain : chains) {
        if (!chain.is_object()) continue;
        Json current = chain.value("current", Json::object());
        has_x_onset_time = has_x_onset_time || current.contains("x_onset_time");
        std::string reason = scalar_text(chain, "termination_detail");
        if (reason.empty()) reason = scalar_text(chain, "status");
        rows.push_back({scalar_text(chain, "chain_id"), scalar_text(chain, "status"),
                        scalar_text(current, "signal"),
                        current.contains("x_onset_time")
                            ? scalar_text(current, "x_onset_time") : scalar_text(current, "time"),
                        scalar_text(current, "value"), reason});
    }
    if (rows.empty()) return;
    out.emit_table({"chain", "status", "current_signal",
                    has_x_onset_time ? "current_x_onset_time" : "current_time",
                    "value", "reason"}, rows);
    while (!text.empty() && text.back() == '\n') text.pop_back();
    text += "\n\n" + out.str();
}

} // namespace

int trace_result_limit_from_request(ContractBoundRequest& request) {
    auto limits = request.limits();
    ContractJsonView max_results = limits["max_results"];
    if (!max_results.exists()) return kDefaultTraceResultLimit;

    const Json value = max_results.consume_subtree(
        "trace_result_limit_parser");
    const Json::number_unsigned_t maximum =
        static_cast<Json::number_unsigned_t>(
            std::numeric_limits<int>::max());
    if (value.is_number_unsigned()) {
        const Json::number_unsigned_t parsed =
            value.get<Json::number_unsigned_t>();
        if (parsed == 0 || parsed > maximum) {
            throw std::out_of_range(
                "limits.max_results must be within the positive int range");
        }
        return static_cast<int>(parsed);
    }
    if (value.is_number_integer()) {
        const Json::number_integer_t parsed =
            value.get<Json::number_integer_t>();
        if (parsed <= 0 ||
            static_cast<Json::number_unsigned_t>(parsed) > maximum) {
            throw std::out_of_range(
                "limits.max_results must be within the positive int range");
        }
        return static_cast<int>(parsed);
    }
    throw std::invalid_argument(
        "limits.max_results must be a positive integer");
}

Json source_window_from_location(const std::string& file, int line, int context_lines) {
    return source_lines_from_file(file, line, std::max(0, resolved_context_lines(context_lines)));
}

Json source_window_from_npi_handle(npiHandle handle, int context_lines) {
    if (!handle) return Json::array();
    int line = npi_get(npiLineNo, handle);
    const char* raw_file = npi_get_str(npiFile, handle);
    return source_window_from_location(raw_file ? raw_file : "", line, context_lines);
}

Json make_source_path_item_from_location(const std::string& file,
                                         int line,
                                         const std::vector<std::string>& signal_path,
                                         int context_lines) {
    Json context = source_window_from_location(file, line, context_lines);
    if (context.empty()) return Json::object();
    Json item;
    item["file"] = file;
    item["line"] = line;
    item["source_context"] = context;
    item["signal_path"] = strings_to_json(signal_path);
    return item;
}

Json make_source_path_item_from_npi_handle(npiHandle handle,
                                           const std::vector<std::string>& signal_path,
                                           int context_lines) {
    if (!handle) return Json::object();
    int line = npi_get(npiLineNo, handle);
    const char* raw_file = npi_get_str(npiFile, handle);
    return make_source_path_item_from_location(raw_file ? raw_file : "",
                                               line,
                                               signal_path,
                                               context_lines);
}

Json simplify_trace_driver_load_payload(const Json& raw,
                                        const std::string& action,
                                        const std::string& signal,
                                        const std::string& mode,
                                        int max_results) {
    Json paths = Json::array();
    std::set<std::string> seen;
    Json edges = raw.value("dependency_edges", Json::array());
    if (edges.is_array()) {
        for (const auto& edge : edges) {
            add_path_if_valid(paths, seen, scalar_text(edge, "file"), scalar_int(edge, "line"),
                              signal_path_from_edge(edge, signal, mode));
        }
    }
    Json results = raw.value("results", Json::array());
    if (results.is_array()) {
        for (const auto& record : results) {
            add_path_if_valid(paths, seen, scalar_text(record, "file"), scalar_int(record, "line"),
                              signal_path_from_record(record, signal, mode));
        }
    }

    const std::size_t total_count = paths.size();
    const bool response_truncated = apply_result_limit(paths, max_results);
    const bool scan_complete = raw.at("scan_complete").get<bool>();
    const bool analysis_complete = raw.at("analysis_complete").get<bool>();

    Json out;
    out["summary"] = {
        {"signal", signal},
        {"mode", mode}
    };
    std::vector<std::string> truncation_scopes =
        trace_analysis_truncation_scopes(raw, analysis_complete);
    if (response_truncated) truncation_scopes.push_back("response_paths");
    xdebug_core::set_completeness(
        out["summary"],
        scan_complete,
        analysis_complete,
        response_truncated,
        total_count,
        paths.size(),
        truncation_scopes);
    add_limit_hint(out["summary"], response_truncated, max_results);
    out["paths"] = paths;
    const Json diagnostics = raw.value("diagnostics", Json::array());
    if (!diagnostics.is_array()) {
        throw std::logic_error("trace diagnostics must be an array");
    }
    if (!diagnostics.empty()) out["diagnostics"] = diagnostics;
    (void)action;
    return out;
}

Json simplify_active_driver_payload(const Json& raw,
                                    const std::string& signal,
                                    const std::string& requested_time,
                                    int max_results) {
    Json paths = Json::array();
    std::set<std::string> seen;
    Json raw_summary = raw.value("summary", Json::object());
    std::string active_time = raw_summary.value("active_time", std::string());
    Json trace_nodes = raw.value("trace", Json::object()).value("nodes", Json::array());
    if (trace_nodes.is_array()) {
        for (const auto& node : trace_nodes) {
            std::vector<std::string> path;
            Json signals = node.value("signals", Json::array());
            if (signals.is_array()) {
                for (const auto& item : signals) {
                    if (item.is_string()) append_signal(path, item.get<std::string>());
                }
            }
            append_signal(path, scalar_text(node, "next_signal"));
            append_signal(path, scalar_text(node, "signal"));
            if (active_time.empty()) active_time = scalar_text(node, "active_time");
            add_path_if_valid(paths, seen, scalar_text(node, "file"), scalar_int(node, "line"), path);
        }
    }
    if (paths.empty()) {
        Json driver = raw.value("driver", Json::object());
        if (driver.is_object()) {
            std::vector<std::string> path;
            Json signals = driver.value("signals", Json::array());
            if (signals.is_array()) {
                for (const auto& item : signals) {
                    if (item.is_string()) append_signal(path, item.get<std::string>());
                }
            }
            append_signal(path, signal);
            add_path_if_valid(paths, seen, scalar_text(driver, "file"), scalar_int(driver, "line"), path);
        }
    }

    const std::size_t total_count = paths.size();
    const bool response_truncated = apply_result_limit(paths, max_results);
    const bool analysis_complete =
        raw_summary.at("analysis_complete").get<bool>();

    Json out;
    out["summary"] = {
        {"signal", signal},
        {"time", requested_time},
        {"active_time", active_time},
        {"termination", raw_summary.value("termination", std::string("unresolved"))},
        {"termination_detail", raw_summary.value(
            "termination_detail", raw_summary.value("termination", std::string("unresolved")))}
    };
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_trace");
    if (response_truncated) truncation_scopes.push_back("response_paths");
    xdebug_core::set_completeness(
        out["summary"],
        analysis_complete,
        analysis_complete,
        response_truncated,
        total_count,
        paths.size(),
        truncation_scopes);
    add_limit_hint(out["summary"], response_truncated, max_results);
    out["paths"] = paths;
    return out;
}

Json simplify_active_driver_chain_payload(const Json& raw,
                                          const std::string& signal,
                                          const std::string& start_time,
                                          int max_results) {
    Json hops = Json::array();
    Json chain_object = raw.value("chain", Json::object());
    Json chain = chain_object.is_object() ? chain_object.value("chain", Json::array()) : Json::array();
    if (chain.is_array()) {
        std::set<std::string> seen;
        for (const auto& node : chain) {
            std::vector<std::string> path;
            append_signal(path, scalar_text(node, "next"));
            append_signal(path, scalar_text(node, "signal"));
            std::string file = scalar_text(node, "file");
            int line = scalar_int(node, "line");
            if (file.empty() || line <= 0 || path.empty()) continue;
            std::ostringstream key;
            key << node.value("index", 0) << "|" << file << ":" << line;
            for (const auto& item : path) key << "|" << item;
            if (!seen.insert(key.str()).second) continue;
            Json hop = make_source_path_item_from_location(file, line, path);
            if (hop.empty()) continue;
            hop["index"] = node.value("index", static_cast<int>(hops.size()));
            hop["chain_id"] = "c0";
            hop["signal"] = scalar_text(node, "signal");
            hop["time"] = scalar_text(node, "time");
            hop["active_time"] = scalar_text(node, "active_time");
            if (node.contains("value")) hop["value"] = node["value"];
            hop["relation"] = hop["index"].get<int>() == 0 ? "root" : "driver";
            hops.push_back(hop);
        }
    }

    const std::size_t total_count = hops.size();
    const bool response_truncated = apply_result_limit(hops, max_results);

    Json summary = raw.value("summary", Json::object());
    const bool analysis_complete =
        summary.at("analysis_complete").get<bool>();
    Json out;
    out["summary"] = {
        {"signal", signal},
        {"time", start_time},
        {"termination", summary.value("termination", raw.value("termination", std::string("unresolved")))},
        {"termination_detail", summary.value(
            "termination_detail",
            summary.value("termination", raw.value("termination", std::string("unresolved"))))}
    };
    std::vector<std::string> truncation_scopes;
    if (!analysis_complete) truncation_scopes.push_back("analysis_trace");
    if (response_truncated) truncation_scopes.push_back("response_hops");
    xdebug_core::set_completeness(
        out["summary"],
        analysis_complete,
        analysis_complete,
        response_truncated,
        total_count,
        hops.size(),
        truncation_scopes);
    add_limit_hint(out["summary"], response_truncated, max_results);
    out["hops"] = hops;
    Json depth_frontiers = chain_object.value("depth_frontiers", Json::array());
    if (depth_frontiers.is_array() && !depth_frontiers.empty()) {
        out["depth_frontiers"] = depth_frontiers;
    }
    Json ambiguity_evidence = chain_object.value("ambiguity_evidence", Json());
    if (ambiguity_evidence.is_object()) {
        out["ambiguity_evidence"] = ambiguity_evidence;
    }
    Json suggested_next_actions = raw.value("suggested_next_actions", Json::array());
    if (suggested_next_actions.is_array() && !suggested_next_actions.empty()) {
        out["suggested_next_actions"] = suggested_next_actions;
    }
    return out;
}

std::string render_source_path_xout(const std::string& action, const Json& response) {
    xdebug::TextResponseBuilder out("xdebug");
    out.emit_header(action);
    Json summary = response.value("summary", Json::object());
    if (summary.is_object() && !summary.empty()) {
        out.emit_section("summary");
        for (auto it = summary.begin(); it != summary.end(); ++it) {
            if (xdebug::is_xout_scalar_json(it.value())) out.emit_kv(it.key(), it.value());
        }
        const Json truncation_scopes = summary.value("truncation_scopes", Json());
        if (truncation_scopes.is_array() && truncation_scopes.empty()) {
            out.emit_kv("truncation_scopes", "[empty]");
        } else if (truncation_scopes.is_array()) {
            out.emit_section("truncation_scopes");
            for (const auto& scope : truncation_scopes) {
                if (scope.is_string()) out.emit_row({scope.get<std::string>()});
            }
        }
    }
    const Json data = response.value("data", Json::object());
    std::string text = out.str();
    const Json query = data.value("query", Json());
    if (query.is_object() && !query.empty()) {
        xdebug::TextResponseBuilder query_out("xdebug");
        query_out.emit_section("query");
        if (query.contains("query_time")) {
            query_out.emit_kv("query_time", query["query_time"]);
        }
        Json value = query.value("value", Json());
        if (value.is_object() && value.contains("value")) {
            query_out.emit_kv("value", value["value"]);
        }
        if (query.contains("x_mask")) query_out.emit_kv("x_mask", query["x_mask"]);
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text += "\n\n" + query_out.str();
    }
    const Json paths = data.value("paths", Json::array());
    const Json diagnostics = data.value("diagnostics", Json::array());
    if (diagnostics.is_array() && !diagnostics.empty()) {
        xdebug::TextResponseBuilder diagnostic_out("xdebug");
        diagnostic_out.emit_section("diagnostics");
        diagnostic_out.emit_table(
            {"code", "stage", "artifact_kind", "first_index",
             "failure_count", "message"},
            [&]() {
                std::vector<std::vector<std::string> > rows;
                for (const auto& diagnostic : diagnostics) {
                    if (!diagnostic.is_object()) continue;
                    rows.push_back({
                        diagnostic.value("code", std::string()),
                        diagnostic.value("stage", std::string()),
                        diagnostic.value("artifact_kind", std::string()),
                        std::to_string(diagnostic.value("first_index", 0U)),
                        std::to_string(diagnostic.value("failure_count", 0U)),
                        diagnostic.value("message", std::string()),
                    });
                }
                return rows;
            }());
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text += "\n\n" + diagnostic_out.str();
    }
    int context_lines = xdebug_core::xdebug_trace_source_context_lines();
    int merge_threshold_lines = xdebug_core::xdebug_trace_source_merge_threshold_lines();
    if (paths.is_array()) {
        std::vector<SourceRenderGroup> groups =
            group_source_items(collect_source_items(paths, false), merge_threshold_lines);
        for (const auto& group : groups) emit_source_group_xout(text, group, context_lines);
    }
    const Json hops = data.value("hops", Json::array());
    if (hops.is_array()) {
        std::vector<SourceRenderGroup> groups =
            group_source_items(collect_source_items(hops, true), merge_threshold_lines);
        for (const auto& group : groups) emit_source_group_xout(text, group, context_lines);
    }
    const Json chains = data.value("chains", Json::array());
    if (chains.is_array()) {
        Json chain_hops = Json::array();
        for (const auto& chain : chains) {
            if (!chain.is_object()) continue;
            Json items = chain.value("hops", Json::array());
            if (!items.is_array()) continue;
            for (auto item : items) {
                if (!item.is_object()) continue;
                if (!item.contains("chain_id")) item["chain_id"] = chain.value("chain_id", "");
                chain_hops.push_back(item);
            }
        }
        std::vector<SourceRenderGroup> groups =
            group_source_items(collect_source_items(chain_hops, true), merge_threshold_lines);
        for (const auto& group : groups) emit_source_group_xout(text, group, context_lines);
    }
    const Json ambiguity = data.value("ambiguity_evidence", Json());
    if (ambiguity.is_object()) {
        std::string ambiguity_text = render_ambiguous_rhs_xout(ambiguity);
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text += "\n\n" + ambiguity_text;
    }
    append_chain_states_xout(text, chains);
    append_depth_frontiers_xout(text, data.value("depth_frontiers", Json::array()));
    append_next_actions_xout(text, data.value("suggested_next_actions", Json::array()));
    Json limitations = data.value("limitations", Json::array());
    if (limitations.is_array() && !limitations.empty()) {
        xdebug::TextResponseBuilder limitations_out("xdebug");
        limitations_out.emit_section("limitations");
        for (const auto& item : limitations) {
            if (item.is_string()) limitations_out.emit_row({item.get<std::string>()});
        }
        while (!text.empty() && text.back() == '\n') text.pop_back();
        text += "\n\n" + limitations_out.str();
    }
    while (!text.empty() && text.back() == '\n') text.pop_back();
    text.push_back('\n');
    return text;
}

} // namespace xdebug_design
