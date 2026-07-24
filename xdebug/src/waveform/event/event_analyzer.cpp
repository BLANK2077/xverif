#include "event_analyzer.h"
#include "../common/clock_sampling.h"
#include "../server/fsdb_value_reader.h"
#include "../server/fsdb_scan_utils.h"

#include "npi_L1.h"
#include <algorithm>
#include <cctype>
#include <cstring>
#include <cstdlib>
#include <sstream>

namespace xdebug_waveform {

static std::string strip_value_prefix(const std::string& value) {
    if (value.size() >= 2 && value[0] == '\'' &&
        (value[1] == 'b' || value[1] == 'B' || value[1] == 'h' || value[1] == 'H' ||
         value[1] == 'd' || value[1] == 'D')) {
        return value.substr(2);
    }
    return value;
}

static std::string bits_only(const std::string& value) {
    std::string raw = strip_value_prefix(value);
    std::string out;
    for (char c : raw) {
        if (c == '0' || c == '1' || c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        }
    }
    return out;
}

enum class TriValue {
    False,
    True,
    Unknown
};

static TriValue tri_not(TriValue value) {
    if (value == TriValue::True) return TriValue::False;
    if (value == TriValue::False) return TriValue::True;
    return TriValue::Unknown;
}

static TriValue tri_and(TriValue lhs, TriValue rhs) {
    if (lhs == TriValue::False || rhs == TriValue::False) return TriValue::False;
    if (lhs == TriValue::True && rhs == TriValue::True) return TriValue::True;
    return TriValue::Unknown;
}

static TriValue tri_or(TriValue lhs, TriValue rhs) {
    if (lhs == TriValue::True || rhs == TriValue::True) return TriValue::True;
    if (lhs == TriValue::False && rhs == TriValue::False) return TriValue::False;
    return TriValue::Unknown;
}

static bool has_unknown_bit(const std::string& value) {
    for (char c : value) {
        if (c == 'x' || c == 'X' || c == 'z' || c == 'Z') return true;
    }
    return false;
}

static TriValue truth_value(const std::string& value) {
    std::string bits = bits_only(value);
    if (bits.empty()) {
        std::string raw = strip_value_prefix(value);
        if (raw == "1") return TriValue::True;
        if (raw == "0") return TriValue::False;
        return TriValue::Unknown;
    }
    if (has_unknown_bit(bits)) return TriValue::Unknown;
    for (char c : bits) {
        if (c == '1') return TriValue::True;
    }
    return TriValue::False;
}

static std::string hex_to_bits(const std::string& hex) {
    std::string out;
    for (char c : hex) {
        if (c == '_' || c == ' ') continue;
        int v = -1;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = 10 + c - 'a';
        else if (c >= 'A' && c <= 'F') v = 10 + c - 'A';
        if (v < 0) return "";
        for (int bit = 3; bit >= 0; --bit) out.push_back((v & (1 << bit)) ? '1' : '0');
    }
    size_t first_one = out.find('1');
    if (first_one == std::string::npos) return "0";
    return out.substr(first_one);
}

static std::string dec_to_bits(const std::string& dec) {
    std::string clean;
    for (char c : dec) {
        if (c != '_') clean.push_back(c);
    }
    char* end = nullptr;
    unsigned long long v = strtoull(clean.c_str(), &end, 10);
    if (!end || *end != '\0') return "";
    if (v == 0) return "0";
    std::string out;
    while (v) {
        out.push_back((v & 1ULL) ? '1' : '0');
        v >>= 1;
    }
    std::reverse(out.begin(), out.end());
    return out;
}

static std::string literal_to_bits(const std::string& literal) {
    std::string s = literal;
    size_t tick = s.find('\'');
    if (tick != std::string::npos && tick + 1 < s.size()) {
        char base = static_cast<char>(std::tolower(static_cast<unsigned char>(s[tick + 1])));
        std::string body = s.substr(tick + 2);
        if (base == 'b') return bits_only(body);
        if (base == 'h') return hex_to_bits(body);
        if (base == 'd') return dec_to_bits(body);
    }
    if (s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) return hex_to_bits(s.substr(2));
    if (s.size() > 2 && s[0] == '0' && (s[1] == 'b' || s[1] == 'B')) return bits_only(s.substr(2));
    return dec_to_bits(s);
}

static bool is_decimal_literal_text(const std::string& value) {
    bool saw_digit = false;
    for (char c : value) {
        if (c == '_') continue;
        if (!std::isdigit(static_cast<unsigned char>(c))) return false;
        saw_digit = true;
    }
    return saw_digit;
}

static std::string normalize_for_compare(const std::string& value, size_t min_width) {
    std::string bits;
    if (value.size() > 2 && value[0] == '0' && (value[1] == 'x' || value[1] == 'X' || value[1] == 'b' || value[1] == 'B')) {
        bits = literal_to_bits(value);
    } else if (value.find('\'') != std::string::npos) {
        bits = literal_to_bits(value);
        if (bits.empty()) bits = bits_only(value);
    } else if (is_decimal_literal_text(value)) {
        bits = literal_to_bits(value);
    } else {
        bits = bits_only(value);
        if (bits.empty()) bits = literal_to_bits(value);
    }
    if (bits.empty()) return value;
    size_t first = bits.find_first_not_of('0');
    if (first == std::string::npos) bits = "0";
    else bits = bits.substr(first);
    while (bits.size() < min_width) bits.insert(bits.begin(), '0');
    return bits;
}

static std::string extract_slice_value(const std::string& value, int left, int right) {
    std::string bits = bits_only(value);
    if (bits.empty()) return "";
    int hi = std::max(left, right);
    int lo = std::min(left, right);
    if (hi < 0 || lo < 0 || static_cast<size_t>(hi) >= bits.size()) return "";
    size_t start = bits.size() - 1 - static_cast<size_t>(hi);
    size_t end = bits.size() - 1 - static_cast<size_t>(lo);
    if (start > end || end >= bits.size()) return "";
    return "'b" + bits.substr(start, end - start + 1);
}

class ExprParser {
public:
    ExprParser(const std::string& expr, const std::map<std::string, std::string>& values)
        : expr_(expr), values_(values) {}

    bool eval(TriValue& result, std::string& error) {
        pos_ = 0;
        error.clear();
        result = parse_or(error);
        skip_ws();
        if (error.empty() && pos_ != expr_.size()) {
            error = "Unexpected token near: " + expr_.substr(pos_);
        }
        return error.empty();
    }

private:
    TriValue parse_or(std::string& error) {
        TriValue lhs = parse_and(error);
        while (error.empty()) {
            skip_ws();
            if (!consume("||")) break;
            TriValue rhs = parse_and(error);
            lhs = tri_or(lhs, rhs);
        }
        return lhs;
    }

    TriValue parse_and(std::string& error) {
        TriValue lhs = parse_unary(error);
        while (error.empty()) {
            skip_ws();
            if (!consume("&&")) break;
            TriValue rhs = parse_unary(error);
            lhs = tri_and(lhs, rhs);
        }
        return lhs;
    }

    TriValue parse_unary(std::string& error) {
        skip_ws();
        if (consume("!")) return tri_not(parse_unary(error));
        return parse_primary(error);
    }

    TriValue parse_primary(std::string& error) {
        skip_ws();
        if (consume("(")) {
            TriValue v = parse_or(error);
            if (error.empty() && !consume(")")) error = "Missing ')'";
            return v;
        }

        std::string lhs = parse_atom(error);
        if (!error.empty()) return TriValue::False;
        skip_ws();
        if (consume("==") || consume("=")) {
            std::string rhs = parse_atom(error);
            if (!error.empty()) return TriValue::False;
            return compare(lhs, rhs);
        }
        if (consume("!=")) {
            std::string rhs = parse_atom(error);
            if (!error.empty()) return TriValue::False;
            TriValue eq = compare(lhs, rhs);
            if (eq == TriValue::Unknown) return TriValue::Unknown;
            return eq == TriValue::True ? TriValue::False : TriValue::True;
        }
        if (consume(">=")) {
            std::string rhs = parse_atom(error);
            if (!error.empty()) return TriValue::False;
            return compare_order(lhs, rhs, ">=");
        }
        if (consume("<=")) {
            std::string rhs = parse_atom(error);
            if (!error.empty()) return TriValue::False;
            return compare_order(lhs, rhs, "<=");
        }
        if (consume(">")) {
            std::string rhs = parse_atom(error);
            if (!error.empty()) return TriValue::False;
            return compare_order(lhs, rhs, ">");
        }
        if (consume("<")) {
            std::string rhs = parse_atom(error);
            if (!error.empty()) return TriValue::False;
            return compare_order(lhs, rhs, "<");
        }
        return truth_value(lhs);
    }

    TriValue compare(const std::string& lhs, const std::string& rhs) {
        size_t width = std::max(bits_only(lhs).size(), bits_only(rhs).size());
        std::string lhs_norm = normalize_for_compare(lhs, width);
        std::string rhs_norm = normalize_for_compare(rhs, width);
        if (has_unknown_bit(lhs_norm) || has_unknown_bit(rhs_norm)) return TriValue::Unknown;
        return lhs_norm == rhs_norm ? TriValue::True : TriValue::False;
    }

    TriValue compare_order(const std::string& lhs, const std::string& rhs, const char* op) {
        size_t width = std::max(bits_only(lhs).size(), bits_only(rhs).size());
        std::string lhs_norm = normalize_for_compare(lhs, width);
        std::string rhs_norm = normalize_for_compare(rhs, width);
        if (has_unknown_bit(lhs_norm) || has_unknown_bit(rhs_norm)) return TriValue::Unknown;
        int cmp = lhs_norm.compare(rhs_norm);
        bool result = false;
        if (std::strcmp(op, ">=") == 0) result = cmp >= 0;
        else if (std::strcmp(op, "<=") == 0) result = cmp <= 0;
        else if (std::strcmp(op, ">") == 0) result = cmp > 0;
        else if (std::strcmp(op, "<") == 0) result = cmp < 0;
        return result ? TriValue::True : TriValue::False;
    }

    std::string parse_atom(std::string& error) {
        skip_ws();
        if (pos_ >= expr_.size()) {
            error = "Unexpected end of expression";
            return "";
        }
        if (expr_[pos_] == '\'' || std::isdigit(static_cast<unsigned char>(expr_[pos_]))) {
            return parse_literal();
        }
        if (is_ident_start(expr_[pos_])) {
            std::string name = parse_identifier();
            auto it = values_.find(name);
            if (it == values_.end()) {
                error = "Unknown alias in expression: " + name;
                return "";
            }
            return it->second;
        }
        error = "Unexpected token near: " + expr_.substr(pos_);
        return "";
    }

    std::string parse_literal() {
        size_t start = pos_;
        if (expr_[pos_] == '\'') {
            pos_++;
            if (pos_ < expr_.size()) pos_++;
            while (pos_ < expr_.size() && is_literal_char(expr_[pos_])) pos_++;
            return expr_.substr(start, pos_ - start);
        }
        while (pos_ < expr_.size() && is_literal_char(expr_[pos_])) pos_++;
        return expr_.substr(start, pos_ - start);
    }

    std::string parse_identifier() {
        size_t start = pos_;
        pos_++;
        while (pos_ < expr_.size() && is_ident_char(expr_[pos_])) pos_++;
        return expr_.substr(start, pos_ - start);
    }

    bool consume(const char* token) {
        skip_ws();
        size_t n = strlen(token);
        if (expr_.compare(pos_, n, token) == 0) {
            pos_ += n;
            return true;
        }
        return false;
    }

    void skip_ws() {
        while (pos_ < expr_.size() && std::isspace(static_cast<unsigned char>(expr_[pos_]))) pos_++;
    }

    static bool is_ident_start(char c) {
        return std::isalpha(static_cast<unsigned char>(c)) || c == '_';
    }

    static bool is_ident_char(char c) {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '.';
    }

    static bool is_literal_char(char c) {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '_' || c == '\'' || c == 'x' || c == 'X';
    }

    std::string expr_;
    const std::map<std::string, std::string>& values_;
    size_t pos_ = 0;
};

bool EventAnalyzer::validate_config(npiFsdbFileHandle file,
                                    const EventConfig& config,
                                    std::vector<std::string>& ordered_aliases,
                                    std::vector<std::string>& ordered_paths,
                                    std::string& error) {
    ordered_aliases.clear();
    ordered_paths.clear();
    if (config.clock_sample.clock.empty()) {
        error = "Event config requires clock";
        return false;
    }
    if (config.signals.empty()) {
        error = "Event config requires at least one signal alias";
        return false;
    }
    if (!npi_fsdb_sig_by_name(file, config.clock_sample.clock.c_str(), NULL)) {
        error = "Clock signal not found: " + config.clock_sample.clock;
        return false;
    }
    if (config.has_reset && !npi_fsdb_sig_by_name(file, config.reset.signal.c_str(), NULL)) {
        error = "Reset signal not found: " + config.reset.signal;
        return false;
    }
    for (const auto& kv : config.signals) {
        if (!npi_fsdb_sig_by_name(file, kv.second.c_str(), NULL)) {
            error = "Signal not found for alias " + kv.first + ": " + kv.second;
            return false;
        }
        ordered_aliases.push_back(kv.first);
        ordered_paths.push_back(kv.second);
    }
    for (const auto& kv : config.fields) {
        if (config.signals.find(kv.second.signal_alias) == config.signals.end()) {
            error = "Field " + kv.first + " references unknown signal alias: " + kv.second.signal_alias;
            return false;
        }
        if (kv.second.left < 0 || kv.second.right < 0) {
            error = "Field " + kv.first + " has negative bit index";
            return false;
        }
    }
    return true;
}

bool EventAnalyzer::analyze(npiFsdbFileHandle file,
                            const EventConfig& config,
                            const EventQuery& query,
                            std::vector<EventRecord>& records,
                            std::string& error) {
    records.clear();
    ClockSampleSpec clock_sample = config.clock_sample;
    if (!normalize_clock_sample_spec(file, clock_sample, error)) return false;
    std::vector<std::string> aliases;
    std::vector<std::string> paths;
    if (!validate_config(file, config, aliases, paths, error)) return false;

    std::map<std::string, std::string> dummy_values;
    for (const auto& alias : aliases) dummy_values[alias] = "'b0";
    for (const auto& kv : config.fields) dummy_values[kv.first] = "'b0";
    TriValue ignored = TriValue::False;
    ExprParser validator(query.expr, dummy_values);
    if (!validator.eval(ignored, error)) return false;

    npiFsdbSigHandle rst = nullptr;
    if (config.has_reset) {
        rst = npi_fsdb_sig_by_name(file, config.reset.signal.c_str(), NULL);
        if (!rst) {
            error = "Reset signal not found: " + config.reset.signal;
            return false;
        }
        NPI_INT32 reset_width = 0;
        if (!npi_fsdb_sig_property(npiFsdbSigRangeSize, rst, &reset_width) || reset_width != 1) {
            error = "Reset signal must be one bit: " + config.reset.signal;
            return false;
        }
    }

    fsdbSigVec_t signal_handles;
    for (const auto& path : paths) {
        npiFsdbSigHandle sig = npi_fsdb_sig_by_name(file, path.c_str(), NULL);
        if (!sig) {
            error = "Signal not found: " + path;
            return false;
        }
        signal_handles.push_back(sig);
    }
    std::vector<ClockSampleSignal> sample_signals;
    if (rst) sample_signals.push_back({"__reset", config.reset.signal, rst});
    for (size_t i = 0; i < aliases.size(); ++i) {
        sample_signals.push_back({aliases[i], paths[i], signal_handles[i]});
    }

    int matched_count = 0;
    npiFsdbTime first_match_time = 0;
    npiFsdbTime last_match_time = 0;
    auto process_edge = [&](npiFsdbTime t,
                            const std::string& sampled_rst_value,
                            const std::vector<std::string>& sampled_values,
                            std::string& process_error) -> bool {
        if (t < query.begin || t > query.end) return true;

        if (config.has_reset) {
            if (reset_is_active(config.reset, sampled_rst_value)) return true;
        }

        std::map<std::string, std::string> value_map;
        for (size_t i = 0; i < aliases.size(); ++i) value_map[aliases[i]] = sampled_values[i];

        std::map<std::string, std::string> field_map;
        for (const auto& kv : config.fields) {
            auto sig_it = value_map.find(kv.second.signal_alias);
            if (sig_it == value_map.end()) continue;
            std::string sliced = extract_slice_value(sig_it->second, kv.second.left, kv.second.right);
            if (sliced.empty()) {
                process_error = "Failed to slice field " + kv.first;
                return false;
            }
            field_map[kv.first] = sliced;
            value_map[kv.first] = sliced;
        }

        TriValue matched = TriValue::False;
        ExprParser parser(query.expr, value_map);
        if (!parser.eval(matched, process_error)) return false;
        if (matched == TriValue::True) {
            ++matched_count;
            if (matched_count == 1) first_match_time = t;
            last_match_time = t;
            EventRecord rec;
            rec.time = t;
            rec.signals = value_map;
            for (const auto& kv : config.fields) rec.signals.erase(kv.first);
            rec.fields = field_map;
            for (size_t i = 0; i < aliases.size(); ++i) {
                FsdbSignalWidth width = fsdb_signal_width(signal_handles[i]);
                rec.signal_widths[aliases[i]] =
                    width.reliable ? width.width : 0;
            }
            for (const auto& kv : config.fields) {
                rec.field_widths[kv.first] =
                    std::abs(kv.second.left - kv.second.right) + 1;
            }
            if (query.retain_last_only && !records.empty()) records[0] = rec;
            else records.push_back(rec);
        }
        return true;
    };

    ClockSampleScanner scanner(file, clock_sample);
    int sample_count = 0;
    bool truncated = false;
    if (!scanner.scan(sample_signals, query.begin, query.end, npiFsdbBinStrVal, 'b', query.max_samples,
        [&](const ClockSample& sample) -> bool {
            size_t offset = 0;
            std::string sampled_rst_value = "'b1";
            if (rst) {
                if (sample.values.empty()) {
                    error = "Failed to sample reset signal";
                    return false;
                }
                sampled_rst_value = sample.values[0];
                offset = 1;
            }
            std::vector<std::string> sampled_values(aliases.size(), "'b0");
            for (size_t i = 0; i < aliases.size() && offset + i < sample.values.size(); ++i) {
                sampled_values[i] = sample.values[offset + i];
            }
            if (!process_edge(sample.time, sampled_rst_value, sampled_values, error)) return false;
            return query.limit <= 0 || static_cast<int>(records.size()) < query.limit;
        }, error, sample_count, truncated)) {
        return false;
    }

    if (!error.empty()) {
        return false;
    }

    if (query.stats) {
        query.stats->sample_count = sample_count;
        query.stats->matched_count = matched_count;
        query.stats->first_match_time = first_match_time;
        query.stats->last_match_time = last_match_time;
        query.stats->sample_budget_exhausted = truncated;
    }

    return true;
}

} // namespace xdebug_waveform
