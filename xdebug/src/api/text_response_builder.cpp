#include "api/text_response_builder.h"
#include "core/value/logic_value.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <iomanip>
#include <set>

namespace xdebug {

namespace {

constexpr size_t kMaxValueLength = 4096;

bool is_empty_json(const Json& value) {
    return value.is_null() ||
           (value.is_array() && value.empty()) ||
           (value.is_object() && value.empty());
}

bool split_logic_literal(const std::string& text, std::string& width,
                         char& radix, std::string& body) {
    const size_t tick = text.find('\'');
    if (tick == std::string::npos || tick + 2 > text.size()) return false;
    width = text.substr(0, tick);
    for (char character : width) {
        if (!std::isdigit(static_cast<unsigned char>(character))) return false;
    }
    radix = static_cast<char>(std::tolower(
        static_cast<unsigned char>(text[tick + 1])));
    if (radix != 'h' && radix != 'b' && radix != 'd') return false;
    body = text.substr(tick + 2);
    return !body.empty();
}

bool is_value_object(const Json& value) {
    if (!value.is_object() || !value.contains("value") ||
        !value["value"].is_string() ||
        !(value.contains("known") || value.contains("bits") ||
          value.contains("width"))) {
        return false;
    }
    std::string width, body;
    char radix = 0;
    return split_logic_literal(
        value["value"].get<std::string>(), width, radix, body);
}

std::string compact_hex_body(std::string body) {
    body.erase(std::remove(body.begin(), body.end(), '_'), body.end());
    if (body.empty()) return "0";
    const bool all_x = std::all_of(body.begin(), body.end(), [](char value) {
        return value == 'x' || value == 'X';
    });
    if (all_x) return "x";
    const bool all_z = std::all_of(body.begin(), body.end(), [](char value) {
        return value == 'z' || value == 'Z';
    });
    if (all_z) return "z";
    const size_t first = body.find_first_not_of('0');
    return first == std::string::npos ? "0" : body.substr(first);
}

std::string grouped_bits(std::string bits) {
    bits.erase(std::remove(bits.begin(), bits.end(), '_'), bits.end());
    if (bits.size() <= 4) return bits;
    std::string out;
    const size_t first = bits.size() % 4 == 0 ? 4 : bits.size() % 4;
    out.append(bits, 0, first);
    for (size_t offset = first; offset < bits.size(); offset += 4) {
        out.push_back('_');
        out.append(bits, offset, 4);
    }
    return out;
}

std::string logic_value_xout(const Json& value) {
    std::string width, body;
    char radix = 0;
    const std::string literal = value["value"].get<std::string>();
    split_logic_literal(literal, width, radix, body);
    std::string out = width + "'" + radix +
        (radix == 'h' ? compact_hex_body(body) : body);
    const bool known = value.value("known", true);
    if (!known && radix == 'h' && value.contains("bits") &&
        value["bits"].is_string()) {
        out += " bits=" + grouped_bits(value["bits"].get<std::string>());
    }
    if (!known && value.value("requested_value_format", std::string()) == "dec")
        out += " requested=dec reason=X/Z";
    const bool sized_literal = !width.empty();
    const bool reliable_width = value.contains("width") &&
        value["width"].is_number_integer() && value["width"].get<int>() > 0;
    if (!sized_literal && !reliable_width) out += " width_unknown";
    return out;
}

bool is_field_map(const Json& value) {
    if (!value.is_object() || value.empty() || is_value_object(value)) return false;
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (!is_value_object(it.value())) return false;
    }
    return true;
}

bool has_scalar_value(const Json& object, const char* key) {
    return object.is_object() && object.contains(key) &&
           is_xout_scalar_json(object[key]);
}

bool scalar_values_equal(const Json& object, const char* lhs, const char* rhs) {
    return has_scalar_value(object, lhs) && has_scalar_value(object, rhs) &&
           object[lhs] == object[rhs];
}

bool status_is(const Json& summary, const char* value) {
    return summary.is_object() && summary.value("status", std::string()) == value;
}

bool omit_redundant_summary_key(const Json& summary, const std::string& key,
                                const Json& value) {
    if (key == "known" && value.is_boolean() && value.get<bool>()) return true;
    if (key == "output_written" && summary.contains("status")) return true;
    if (key == "all_passed" && summary.contains("verdict")) return true;
    if (key == "termination_detail" &&
        scalar_values_equal(summary, "termination", "termination_detail")) return true;
    if (key == "total_action_count" &&
        !summary.value("filtered", false) &&
        scalar_values_equal(summary, "action_count", "total_action_count")) return true;
    if (key == "row_count" &&
        (scalar_values_equal(summary, "row_count", "returned_count") ||
         scalar_values_equal(summary, "row_count", "total_count"))) return true;
    if (key == "checked_value_count" &&
        scalar_values_equal(summary, "checked_value_count", "total_count") &&
        scalar_values_equal(summary, "checked_value_count", "returned_count")) return true;
    if (key == "full_scan_count" && value.is_number() && value == 1 &&
        summary.value("scan_complete", false)) return true;
    if (key == "analysis_quality" && summary.contains("analysis_complete")) return true;
    if ((key == "scanned_transaction_count" ||
         key == "matched_transaction_count") &&
        !summary.value("filter_applied", false) &&
        summary.contains("total_count") && value == summary["total_count"])
        return true;
    if ((key == "at_begin" || key == "at_end") &&
        (summary.value("op", std::string()) == "begin" ||
         summary.value("op", std::string()) == "end")) return true;
    if (key == "always_matched" && summary.contains("verdict")) return true;
    if (key == "added" && value.is_boolean() && value.get<bool>() &&
        status_is(summary, "added")) return true;
    if (key == "created" && value.is_boolean() && value.get<bool>() &&
        status_is(summary, "created")) return true;
    if (key == "deleted" && value.is_boolean() && value.get<bool>() &&
        status_is(summary, "deleted")) return true;
    return false;
}

std::string compact_range(const Json& range) {
    if (!range.is_object()) return std::string();
    std::string begin = range.value("begin", std::string());
    std::string end = range.value("end", std::string());
    if (begin.empty() || end.empty()) return std::string();
    return begin + ".." + end;
}

std::string compact_scalar_array(const Json& values) {
    if (!values.is_array() || values.empty()) return std::string();
    std::string text;
    for (const auto& value : values) {
        if (!is_xout_scalar_json(value)) return std::string();
        if (!text.empty()) text += ",";
        text += json_to_xout_value(value);
    }
    return text;
}

void emit_output_summary(TextResponseBuilder& out, const Json& output) {
    if (!output.is_object()) return;
    static const char* keys[] = {
        "path", "data_path", "write_path", "read_path", "meta_path",
        "manifest_path", "file_format"
    };
    for (const char* key : keys) {
        if (has_scalar_value(output, key))
            out.emit_kv(std::string("output.") + key, output[key]);
    }
}

void emit_session_identity(TextResponseBuilder& out, const Json& session,
                           bool include_resources) {
    if (!session.is_object()) return;
    for (const char* key : {"session_id", "mode", "transport"}) {
        if (has_scalar_value(session, key)) out.emit_kv(key, session[key]);
    }
    if (!include_resources) return;
    for (const char* key : {"daidir", "fsdb"})
        if (has_scalar_value(session, key)) out.emit_kv(key, session[key]);
}

std::string compact_field_map(const Json& value) {
    std::string out;
    if (!value.is_object()) return out;
    for (auto it = value.begin(); it != value.end(); ++it) {
        std::string cell = sanitize_xout_key(it.key()) + "=" + logic_value_xout(it.value());
        if (!out.empty()) out.push_back(' ');
        out += cell;
    }
    return out;
}

std::string collapse_row_column(const std::string& input) {
    std::string out;
    bool in_space = false;
    for (char ch : input) {
        unsigned char uch = static_cast<unsigned char>(ch);
        if (std::isspace(uch)) {
            if (!in_space && !out.empty()) out.push_back(' ');
            in_space = true;
        } else {
            out.push_back(ch);
            in_space = false;
        }
    }
    if (!out.empty() && out.back() == ' ') out.pop_back();
    return out;
}

struct TableColumn {
    std::string label;
    std::string parent;
    std::string key;
};

void collect_table_columns_from_item(const Json& item,
                                     std::vector<TableColumn>& columns,
                                     std::set<std::string>& seen) {
    if (!item.is_object()) return;
    for (auto it = item.begin(); it != item.end(); ++it) {
        if (is_xout_scalar_json(it.value())) {
            std::string label = sanitize_xout_key(it.key());
            if (seen.insert(label).second) columns.push_back({label, std::string(), it.key()});
        } else if (it.value().is_object()) {
            for (auto child = it.value().begin(); child != it.value().end(); ++child) {
                if (!is_xout_scalar_json(child.value())) continue;
                std::string label = it.key() == "signals"
                    ? sanitize_xout_key(child.key())
                    : sanitize_xout_key(it.key() + "." + child.key());
                if (seen.insert(label).second) columns.push_back({label, it.key(), child.key()});
            }
        }
    }
}

std::string table_cell_value(const Json& item, const TableColumn& column) {
    if (!item.is_object()) return std::string();
    if (column.parent.empty()) {
        auto it = item.find(column.key);
        if (it == item.end()) return std::string();
        return json_to_xout_value(*it);
    }
    auto parent = item.find(column.parent);
    if (parent == item.end() || !parent->is_object()) return std::string();
    auto child = parent->find(column.key);
    if (child == parent->end()) return std::string();
    return json_to_xout_value(*child);
}

} // namespace

TextResponseBuilder::TextResponseBuilder(std::string tool) : tool_(std::move(tool)) {}

void TextResponseBuilder::emit_header(const std::string& action) {
    if (wrote_header_) return;
    out_ << "@" << tool_ << "." << action << ".v1\n";
    wrote_header_ = true;
}

void TextResponseBuilder::emit_section(const std::string& name) {
    flush_kv_block();
    pending_section_ = sanitize_xout_key(name);
}

void TextResponseBuilder::emit_kv(const std::string& key, const Json& value) {
    if (is_empty_json(value)) return;
    const std::string text = json_to_xout_value(value);
    if (text.empty()) return;
    const bool nested = in_section_ || !pending_section_.empty();
    ensure_section();
    pending_kv_.push_back({std::string(nested ? "  " : ""), sanitize_xout_key(key), text});
}

void TextResponseBuilder::emit_kv(const std::string& key, const std::string& value) {
    if (value.empty()) return;
    const bool nested = in_section_ || !pending_section_.empty();
    ensure_section();
    pending_kv_.push_back({std::string(nested ? "  " : ""),
                           sanitize_xout_key(key),
                           sanitize_xout_value(value)});
}

void TextResponseBuilder::emit_kv(const std::string& key, const char* value) {
    if (value == nullptr) return;
    emit_kv(key, std::string(value));
}

void TextResponseBuilder::emit_kv(const std::string& key, bool value) {
    emit_kv(key, std::string(value ? "true" : "false"));
}

void TextResponseBuilder::emit_kv(const std::string& key, int value) {
    emit_kv(key, std::to_string(value));
}

void TextResponseBuilder::emit_kv(const std::string& key, long long value) {
    emit_kv(key, std::to_string(value));
}

void TextResponseBuilder::emit_row(std::initializer_list<std::string> columns) {
    emit_row(std::vector<std::string>(columns.begin(), columns.end()));
}

void TextResponseBuilder::emit_row(const std::vector<std::string>& columns) {
    flush_kv_block();
    std::string row;
    for (const auto& col : columns) {
        std::string text = collapse_row_column(sanitize_xout_value(col));
        if (text.empty()) continue;
        if (!row.empty()) row.push_back(' ');
        row += text;
    }
    if (row.empty()) return;
    const bool nested = in_section_ || !pending_section_.empty();
    ensure_section();
    write_line(std::string(nested ? "  " : "") + row);
}

void TextResponseBuilder::emit_table(const std::vector<std::string>& columns,
                                     const std::vector<std::vector<std::string>>& rows) {
    flush_kv_block();
    if (columns.empty()) return;
    std::vector<size_t> widths(columns.size(), 0);
    std::vector<std::string> safe_columns;
    safe_columns.reserve(columns.size());
    for (size_t i = 0; i < columns.size(); ++i) {
        safe_columns.push_back(collapse_row_column(sanitize_xout_key(columns[i])));
        widths[i] = safe_columns.back().size();
    }

    std::vector<std::vector<std::string>> safe_rows;
    safe_rows.reserve(rows.size());
    for (const auto& row : rows) {
        std::vector<std::string> safe_row;
        safe_row.reserve(columns.size());
        for (size_t i = 0; i < columns.size(); ++i) {
            std::string cell;
            if (i < row.size()) cell = collapse_row_column(sanitize_xout_value(row[i]));
            widths[i] = std::max(widths[i], cell.size());
            safe_row.push_back(cell);
        }
        safe_rows.push_back(std::move(safe_row));
    }

    auto emit_cells = [&](const std::vector<std::string>& cells) {
        std::string line;
        for (size_t i = 0; i < columns.size(); ++i) {
            if (i) line += "  ";
            std::string cell = i < cells.size() ? cells[i] : std::string();
            line += cell;
            if (i + 1 < columns.size() && cell.size() < widths[i])
                line.append(widths[i] - cell.size(), ' ');
        }
        while (!line.empty() && line.back() == ' ') line.pop_back();
        const bool nested = in_section_ || !pending_section_.empty();
        ensure_section();
        write_line(std::string(nested ? "  " : "") + line);
    };

    emit_cells(safe_columns);
    for (const auto& row : safe_rows) emit_cells(row);
}

void TextResponseBuilder::emit_json_table(const Json& items, int max_rows) {
    flush_kv_block();
    if (!items.is_array() || items.empty()) return;
    std::vector<TableColumn> columns;
    std::set<std::string> seen;
    int count = std::min(max_rows, static_cast<int>(items.size()));
    for (int i = 0; i < count; ++i)
        collect_table_columns_from_item(items[i], columns, seen);
    if (columns.empty()) return;

    std::vector<std::string> headers;
    headers.reserve(columns.size());
    for (const auto& column : columns) headers.push_back(column.label);

    std::vector<std::vector<std::string>> rows;
    rows.reserve(count);
    for (int i = 0; i < count; ++i) {
        std::vector<std::string> row;
        row.reserve(columns.size());
        for (const auto& column : columns)
            row.push_back(table_cell_value(items[i], column));
        rows.push_back(std::move(row));
    }
    emit_table(headers, rows);
}

void TextResponseBuilder::emit_warning(const std::string& code, const std::string& message) {
    emit_section("warnings");
    emit_table({"code", "message"}, {{code, message}});
}

void TextResponseBuilder::emit_raw(const std::string& text) {
    flush_kv_block();
    wrote_content_ = true;
    out_ << text;
}

void TextResponseBuilder::emit_error(const Json& error) {
    if (!error.is_object()) return;
    if (error.contains("code")) emit_kv("code", error["code"]);
    if (error.contains("message")) emit_kv("message", error["message"]);
    if (error.contains("recoverable")) emit_kv("recoverable", error["recoverable"]);
    if (error.contains("error_layer")) emit_kv("error_layer", error["error_layer"]);
    if (error.contains("invalid_arg")) emit_kv("invalid_arg", error["invalid_arg"]);
    if (error.contains("expected")) emit_kv("expected", error["expected"]);
    if (error.contains("received")) emit_kv("received", error["received"]);
    if (error.contains("received_type")) emit_kv("received_type", error["received_type"]);
    if (error.contains("available_values")) emit_kv("available_values", error["available_values"]);
    if (error.contains("missing_name")) emit_kv("missing_name", error["missing_name"]);
    if (error.contains("missing_resource")) emit_kv("missing_resource", error["missing_resource"]);
    if (error.contains("required_any_of")) emit_kv("required_any_of", error["required_any_of"]);
    if (error.contains("did_you_mean")) emit_kv("did_you_mean", error["did_you_mean"]);
    if (error.contains("cause_code")) emit_kv("cause_code", error["cause_code"]);
    if (error.contains("failure_kind")) emit_kv("failure_kind", error["failure_kind"]);
    if (error.contains("failure_phase")) emit_kv("failure_phase", error["failure_phase"]);
    if (error.contains("startup_reason")) emit_kv("startup_reason", error["startup_reason"]);
    if (error.contains("diagnostic_log")) emit_kv("diagnostic_log", error["diagnostic_log"]);
    if (error.contains("native_error_summary"))
        emit_kv("native_error_summary", error["native_error_summary"]);
    if (error.contains("example_note")) emit_kv("example_note", error["example_note"]);
    if (error.contains("correct_example")) {
        emit_section("correct_example");
        emit_kv("json", error["correct_example"]);
    }
    if (error.contains("next_actions") && error["next_actions"].is_array()) {
        emit_section("next_actions");
        for (const auto& action : error["next_actions"]) emit_row({json_to_xout_value(action)});
    }
    if (error.contains("advisories") && error["advisories"].is_array()) {
        emit_section("advisories");
        for (const auto& advisory : error["advisories"])
            emit_row({json_to_xout_value(advisory)});
    }
}

std::string TextResponseBuilder::str() {
    flush_kv_block();
    std::string text = out_.str();
    while (!text.empty() && text.back() == '\n') text.pop_back();
    text.push_back('\n');
    return text;
}

void TextResponseBuilder::flush_kv_block() {
    if (pending_kv_.empty()) return;
    size_t max_key_width = 0;
    for (const auto& item : pending_kv_)
        max_key_width = std::max(max_key_width, item.key.size());
    for (const auto& item : pending_kv_) {
        write_line(item.indent + item.key +
                   std::string(max_key_width - item.key.size(), ' ') + ": " + item.value);
    }
    pending_kv_.clear();
}

void TextResponseBuilder::ensure_section() {
    if (pending_section_.empty()) return;
    if (wrote_content_) out_ << "\n";
    out_ << pending_section_ << ":\n";
    wrote_content_ = true;
    pending_section_.clear();
    in_section_ = true;
}

void TextResponseBuilder::write_line(const std::string& text) {
    if (!wrote_content_ && pending_section_.empty()) {
        if (wrote_header_) out_ << "\n";
        wrote_content_ = true;
        in_section_ = false;
    }
    out_ << text << "\n";
}

std::string sanitize_xout_key(const std::string& key) {
    std::string out;
    for (char ch : key) {
        unsigned char uch = static_cast<unsigned char>(ch);
        if (std::isalnum(uch) || ch == '_' || ch == '-' || ch == '.') {
            out.push_back(ch);
        } else {
            out.push_back('_');
        }
    }
    return out.empty() ? "field" : out;
}

std::string sanitize_xout_value(const std::string& value) {
    std::string out;
    out.reserve(std::min(value.size(), kMaxValueLength));
    for (char ch : value) {
        if (ch == '\n') {
            out += "\\n";
        } else if (ch == '\r') {
            out += "\\r";
        } else if (ch == '\t') {
            out.push_back(' ');
        } else {
            out.push_back(ch);
        }
        if (out.size() >= kMaxValueLength) {
            out += "...";
            break;
        }
    }
    return out;
}

std::string json_to_xout_value(const Json& value) {
    if (value.is_null()) return std::string();
    if (is_value_object(value)) return sanitize_xout_value(logic_value_xout(value));
    if (is_field_map(value)) return sanitize_xout_value(compact_field_map(value));
    if (value.is_string()) return sanitize_xout_value(value.get<std::string>());
    if (value.is_boolean()) return value.get<bool>() ? "true" : "false";
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number_unsigned()) return std::to_string(value.get<unsigned long long>());
    if (value.is_number_float()) return sanitize_xout_value(value.dump());
    return sanitize_xout_value(value.dump());
}

bool is_xout_scalar_json(const Json& value) {
    return value.is_string() || value.is_number() || value.is_boolean() ||
           is_value_object(value) || is_field_map(value);
}

bool is_xout_field_map_json(const Json& value) {
    return is_field_map(value);
}

void emit_xout_summary(TextResponseBuilder& out, const Json& summary) {
    if (!summary.is_object() || summary.empty()) return;
    out.emit_section("summary");
    for (auto it = summary.begin(); it != summary.end(); ++it) {
        if (omit_redundant_summary_key(summary, it.key(), it.value())) continue;
        if (is_xout_scalar_json(it.value())) {
            out.emit_kv(it.key(), it.value());
            continue;
        }
        if (it.key() == "output") {
            emit_output_summary(out, it.value());
            continue;
        }
        if (it.key() == "requested_range" || it.key() == "scanned_range") {
            const std::string range = compact_range(it.value());
            if (!range.empty()) out.emit_kv(it.key(), range);
            continue;
        }
        if (it.key() == "truncation_scopes") {
            const std::string scopes = compact_scalar_array(it.value());
            out.emit_kv(it.key(), scopes.empty() ? "[empty]" : scopes);
            continue;
        }
        if ((it.key() == "min_value" || it.key() == "max_value") &&
            it.value().is_object() && it.value().contains("value")) {
            out.emit_kv(it.key(), json_to_xout_value(it.value()));
        }
    }
}

void emit_xout_first_section(TextResponseBuilder& out, const Json& response,
                             bool include_summary) {
    if (include_summary) emit_xout_summary(out, response.value("summary", Json::object()));
    const Json data = response.value("data", Json::object());
    const Json findings = data.value("findings", Json::array());
    if (include_summary && findings.is_array() && !findings.empty()) {
        out.emit_kv("finding_count", Json(findings.size()));
        std::string highest;
        for (const char* severity : {"error", "warning", "info"}) {
            for (const auto& finding : findings) {
                if (finding.is_object() &&
                    finding.value("severity", std::string()) == severity) {
                    highest = severity;
                    break;
                }
            }
            if (!highest.empty()) break;
        }
        if (!highest.empty()) out.emit_kv("highest_severity", highest);
    }
    const std::string action = response.value("action", std::string());
    if (action == "session.open" || action == "session.doctor") {
        emit_session_identity(out, response.value("session", Json::object()),
                              action == "session.open");
    } else if (action == "session.close") {
        emit_session_identity(out, data.value("removed_session", Json::object()), false);
    }
}

} // namespace xdebug
