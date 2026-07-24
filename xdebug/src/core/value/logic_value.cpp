#include "logic_value.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <set>

namespace xdebug_core {

namespace {

std::string trim(std::string s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.front()))) s.erase(s.begin());
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    return s;
}

std::string clean_lower(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }
    return out;
}

bool decimal_only(const std::string& text) {
    if (text.empty()) return false;
    for (char c : text) {
        if (!std::isdigit(static_cast<unsigned char>(c))) return false;
    }
    return true;
}

std::string dec_to_bits(const std::string& text) {
    std::string clean = clean_lower(text);
    if (!decimal_only(clean)) return std::string();
    const size_t first = clean.find_first_not_of('0');
    if (first == std::string::npos) return "0";
    clean.erase(0, first);
    std::string bits;
    while (clean != "0") {
        std::string quotient;
        int carry = 0;
        for (char digit : clean) {
            const int value = carry * 10 + (digit - '0');
            const int q = value / 2;
            carry = value % 2;
            if (!quotient.empty() || q != 0)
                quotient.push_back(static_cast<char>('0' + q));
        }
        bits.push_back(carry ? '1' : '0');
        clean = quotient.empty() ? "0" : quotient;
    }
    std::reverse(bits.begin(), bits.end());
    return bits;
}

std::string bin_to_bits(const std::string& text) {
    std::string out;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        char lower = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if (lower != '0' && lower != '1' && lower != 'x' && lower != 'z')
            return std::string();
        out.push_back(lower);
    }
    return out.empty() ? "0" : out;
}

std::string hex_to_bits(const std::string& text) {
    std::string out;
    for (char c : text) {
        if (c == '_' || std::isspace(static_cast<unsigned char>(c))) continue;
        char lower = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        if (lower == 'x' || lower == 'z') {
            out.append(4, lower);
            continue;
        }
        int v = -1;
        if (lower >= '0' && lower <= '9') v = lower - '0';
        else if (lower >= 'a' && lower <= 'f') v = 10 + lower - 'a';
        if (v < 0) return std::string();
        for (int bit = 3; bit >= 0; --bit) out.push_back((v & (1 << bit)) ? '1' : '0');
    }
    return out.empty() ? "0" : out;
}

std::string bits_to_hex(std::string bits) {
    bits = clean_lower(bits);
    if (bits.empty()) return "0";
    size_t pad = (4 - bits.size() % 4) % 4;
    bits.insert(bits.begin(), pad, '0');
    static const char* hex = "0123456789abcdef";
    std::string out;
    for (size_t i = 0; i < bits.size(); i += 4) {
        bool has_x = false;
        bool has_z = false;
        int value = 0;
        for (size_t j = 0; j < 4; ++j) {
            char c = bits[i + j];
            if (c == 'x') has_x = true;
            else if (c == 'z') has_z = true;
            value = (value << 1) | (c == '1' ? 1 : 0);
        }
        if (has_x) out.push_back('x');
        else if (has_z) out.push_back('z');
        else out.push_back(hex[value]);
    }
    return out.empty() ? "0" : out;
}

std::string bits_to_decimal(const std::string& bits) {
    std::string decimal("0");
    for (char bit : bits) {
        int carry = bit == '1' ? 1 : 0;
        for (size_t i = decimal.size(); i > 0; --i) {
            int value = (decimal[i - 1] - '0') * 2 + carry;
            decimal[i - 1] = static_cast<char>('0' + value % 10);
            carry = value / 10;
        }
        if (carry) decimal.insert(decimal.begin(), static_cast<char>('0' + carry));
    }
    const size_t first = decimal.find_first_not_of('0');
    return first == std::string::npos ? "0" : decimal.substr(first);
}

std::string sv_literal(const LogicValue& value, char radix, const std::string& body) {
    const std::string width = value.width_reliable && value.width > 0
        ? std::to_string(value.width) : std::string();
    return width + "'" + radix + body;
}

void apply_width(LogicValue& value, int width_hint) {
    if (width_hint <= 0) return;
    value.width = width_hint;
    value.width_reliable = true;
    if (value.bits.empty()) return;
    if (static_cast<int>(value.bits.size()) < width_hint)
        value.bits.insert(value.bits.begin(), width_hint - value.bits.size(), '0');
    if (static_cast<int>(value.bits.size()) > width_hint)
        value.bits = value.bits.substr(value.bits.size() - width_hint);
}

void finalize(LogicValue& value, const std::string& body_if_no_bits) {
    value.has_x = value.bits.find('x') != std::string::npos ||
                  body_if_no_bits.find('x') != std::string::npos;
    value.has_z = value.bits.find('z') != std::string::npos ||
                  body_if_no_bits.find('z') != std::string::npos;
    value.known = !value.has_x && !value.has_z;
    if (value.width_reliable && value.width <= 0 && !value.bits.empty())
        value.width = static_cast<int>(value.bits.size());

    std::string hex = value.bits.empty() ? clean_lower(body_if_no_bits) : bits_to_hex(value.bits);
    if (hex.empty()) hex = "0";
    value.display = value.width_reliable && value.width > 0
        ? std::to_string(value.width) + "'h" + hex
        : "'h" + hex;
}

LogicValue invalid_literal(const std::string& raw, const std::string& error) {
    LogicValue value;
    value.raw = raw;
    value.valid = false;
    value.known = false;
    value.error = error;
    return value;
}

LogicValue from_body(const std::string& raw, char radix, const std::string& body,
                     int width_hint, bool explicit_width) {
    LogicValue value;
    value.raw = raw;
    value.width = explicit_width ? width_hint : 0;
    value.width_reliable = explicit_width && width_hint > 0;
    char r = static_cast<char>(std::tolower(static_cast<unsigned char>(radix)));
    std::string clean = clean_lower(body);
    if (r == 'b') {
        value.bits = bin_to_bits(clean);
        if (!value.width_reliable) {
            value.width = static_cast<int>(value.bits.size());
            value.width_reliable = !value.bits.empty();
        }
    } else if (r == 'd') {
        if (clean.find_first_of("xz") != std::string::npos)
            return invalid_literal(raw, "decimal logic literal cannot contain x or z");
        value.bits = dec_to_bits(clean);
    } else {
        value.bits = hex_to_bits(clean);
    }
    if (value.bits.empty()) return invalid_literal(raw, "invalid logic value literal: " + raw);
    apply_width(value, width_hint);
    finalize(value, clean);
    return value;
}

} // namespace

bool parse_value_render_format(const std::string& text, ValueRenderFormat& out) {
    const std::string normalized = clean_lower(text);
    if (normalized == "h" || normalized == "hex") { out = ValueRenderFormat::Hex; return true; }
    if (normalized == "b" || normalized == "bin" || normalized == "binary") { out = ValueRenderFormat::Bin; return true; }
    if (normalized == "d" || normalized == "dec" || normalized == "decimal") { out = ValueRenderFormat::Dec; return true; }
    return false;
}

std::string value_render_format_text(ValueRenderFormat format) {
    switch (format) {
    case ValueRenderFormat::Hex: return "hex";
    case ValueRenderFormat::Bin: return "bin";
    case ValueRenderFormat::Dec: return "dec";
    }
    return "hex";
}

bool is_legacy_0x_literal(const std::string& text) {
    std::string s = trim(text);
    return s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X');
}

std::string value_format_invalid_message(const std::string& value) {
    return "invalid value literal: " + value +
           "; 0x prefix is not accepted in xdebug JSON requests; use SystemVerilog literal such as 32'h22 or 'h22";
}

LogicValue logic_value_from_fsdb_raw(const std::string& raw, char radix, int width_hint) {
    std::string s = trim(raw);
    if (s.empty()) return invalid_literal(raw, "empty logic value");

    int explicit_width = 0;
    char r = radix ? radix : 'h';
    std::string body = s;
    size_t tick = s.find('\'');
    if (tick != std::string::npos && tick + 1 < s.size()) {
        if (tick > 0) explicit_width = std::atoi(s.substr(0, tick).c_str());
        r = s[tick + 1];
        body = s.substr(tick + 2);
    } else if (is_legacy_0x_literal(s)) {
        r = 'h';
        body = s.substr(2);
    } else if (s.size() > 2 && s[0] == '0' && (s[1] == 'b' || s[1] == 'B')) {
        r = 'b';
        body = s.substr(2);
    }
    int width = width_hint > 0 ? width_hint : explicit_width;
    return from_body(raw, r, body, width, width > 0);
}

LogicValue logic_value_from_bits(const std::string& bits, int width_hint) {
    LogicValue value;
    value.raw = bits;
    value.bits = bin_to_bits(bits);
    if (value.bits.empty()) return invalid_literal(bits, "invalid bit string");
    int width = width_hint > 0 ? width_hint : static_cast<int>(value.bits.size());
    apply_width(value, width);
    finalize(value, value.bits);
    return value;
}

LogicValue parse_user_logic_literal(const std::string& text) {
    std::string s = trim(text);
    if (s.empty()) return invalid_literal(text, "empty value literal");
    if (is_legacy_0x_literal(s)) return invalid_literal(text, value_format_invalid_message(text));

    size_t tick = s.find('\'');
    if (tick != std::string::npos && tick + 1 < s.size()) {
        int width = tick > 0 ? std::atoi(s.substr(0, tick).c_str()) : 0;
        char radix = s[tick + 1];
        std::string body = s.substr(tick + 2);
        return from_body(text, radix, body, width, width > 0);
    }

    if (!decimal_only(clean_lower(s)))
        return invalid_literal(text, "invalid value literal: " + text + "; use SystemVerilog literal such as 32'h22 or 'h22");
    return from_body(text, 'd', s, 0, false);
}

LogicJson logic_value_json(const LogicValue& value, ValueRenderFormat format) {
    LogicJson out;
    if (format == ValueRenderFormat::Bin) {
        out["value"] = sv_literal(value, 'b', value.bits.empty() ? logic_value_compact_string(value) : value.bits);
    } else if (format == ValueRenderFormat::Dec && value.known && !value.bits.empty()) {
        out["value"] = sv_literal(value, 'd', bits_to_decimal(value.bits));
    } else {
        out["value"] = logic_value_compact_string(value);
        if (format == ValueRenderFormat::Dec && !value.known) {
            out["requested_value_format"] = "dec";
            out["effective_value_format"] = "bin";
            out["value_format_reason"] = "decimal cannot preserve per-bit X/Z";
            out["value"] = sv_literal(value, 'b', value.bits.empty() ? logic_value_compact_string(value) : value.bits);
        }
    }
    out["known"] = value.known;
    if (value.width_reliable && value.width > 0) out["width"] = value.width;
    if (value.width_reliable && !value.bits.empty()) out["bits"] = value.bits;
    if (!value.known) {
        out["has_x"] = value.has_x;
        out["has_z"] = value.has_z;
    }
    return out;
}

void apply_value_render_format(LogicJson& response, ValueRenderFormat format) {
    if (response.is_array()) {
        for (auto& item : response) apply_value_render_format(item, format);
        return;
    }
    if (!response.is_object()) return;

    // A canonical logic value always has a bit-accurate representation.  Do
    // not infer a value object from its display string alone: arbitrary action
    // payloads may also use a key named "value".
    if (response.contains("bits") && response["bits"].is_string() &&
        response.contains("value") && response["value"].is_string()) {
        const int width = response.value("width", 0);
        LogicValue value = logic_value_from_bits(response["bits"].get<std::string>(), width);
        LogicJson rendered = logic_value_json(value, format);
        for (auto it = rendered.begin(); it != rendered.end(); ++it) response[it.key()] = it.value();
    }
    for (auto it = response.begin(); it != response.end(); ++it)
        apply_value_render_format(it.value(), format);
}

namespace {

bool sv_literal_width(const std::string& text, bool& sized) {
    std::string value = trim(text);
    const size_t tick = value.find('\'');
    if (tick == std::string::npos || tick + 2 > value.size()) return false;
    sized = tick > 0;
    for (size_t i = 0; i < tick; ++i) {
        if (!std::isdigit(static_cast<unsigned char>(value[i]))) return false;
    }
    char radix = static_cast<char>(
        std::tolower(static_cast<unsigned char>(value[tick + 1])));
    if (radix != 'h' && radix != 'b' && radix != 'd') return false;
    if (tick + 2 == value.size()) return false;
    for (size_t i = tick + 2; i < value.size(); ++i) {
        char c = static_cast<char>(
            std::tolower(static_cast<unsigned char>(value[i])));
        if (c == '_') continue;
        if (radix == 'h') {
            if (!std::isdigit(static_cast<unsigned char>(c)) &&
                (c < 'a' || c > 'f') && c != 'x' && c != 'z') return false;
        } else if (radix == 'b') {
            if (c != '0' && c != '1' && c != 'x' && c != 'z') return false;
        } else if (!std::isdigit(static_cast<unsigned char>(c))) {
            return false;
        }
    }
    return true;
}

bool canonical_value_object(const LogicJson& value) {
    return value.is_object() && value.contains("value") &&
           value["value"].is_string() &&
           (value.contains("known") || value.contains("bits") ||
            value.contains("width"));
}

void collect_width_diagnostics(const LogicJson& value,
                               const std::string& role,
                               const std::string& inherited_signal,
                               LogicJson& diagnostics,
                               std::set<std::string>& seen,
                               bool& found_value) {
    std::string signal = inherited_signal;
    if (value.is_object() && value.contains("signal") &&
        value["signal"].is_string()) {
        signal = value["signal"].get<std::string>();
    }

    auto record_literal = [&](const std::string& literal,
                              const std::string& literal_role) {
        bool sized = false;
        if (!sv_literal_width(literal, sized)) return;
        found_value = true;
        if (sized) return;
        const std::string key = signal + "\x1f" + literal_role;
        if (!seen.insert(key).second) return;
        diagnostics.push_back({
            {"signal", signal.empty() ? LogicJson(nullptr) : LogicJson(signal)},
            {"role", literal_role},
            {"reason", "npi_range_size_unavailable"}
        });
    };

    if (canonical_value_object(value)) {
        record_literal(value["value"].get<std::string>(), role);
        return;
    }
    if (value.is_string()) {
        record_literal(value.get<std::string>(), role);
        return;
    }
    if (value.is_array()) {
        for (size_t index = 0; index < value.size(); ++index) {
            collect_width_diagnostics(
                value[index],
                role + "[" + std::to_string(index) + "]",
                signal,
                diagnostics,
                seen,
                found_value);
        }
        return;
    }
    if (!value.is_object()) return;
    for (auto it = value.begin(); it != value.end(); ++it) {
        if (it.key() == "summary" || it.key() == "width_diagnostics") continue;
        const std::string child_role =
            role.empty() ? it.key() : role + "." + it.key();
        collect_width_diagnostics(
            it.value(), child_role, signal, diagnostics, seen, found_value);
    }
}

} // namespace

void apply_value_width_summary(LogicJson& response) {
    if (!response.is_object()) return;
    std::string root_signal;
    if (response.contains("summary") && response["summary"].is_object() &&
        response["summary"].contains("signal") &&
        response["summary"]["signal"].is_string()) {
        root_signal = response["summary"]["signal"].get<std::string>();
    }
    LogicJson diagnostics = LogicJson::array();
    std::set<std::string> seen;
    bool found_value = false;
    collect_width_diagnostics(
        response, std::string(), root_signal, diagnostics, seen, found_value);
    if (!found_value) return;
    if (!response.contains("summary") || !response["summary"].is_object())
        response["summary"] = LogicJson::object();
    response["summary"]["value_width_complete"] = diagnostics.empty();
    response["summary"]["width_diagnostics"] = diagnostics;
}

std::string logic_value_compact_string(const LogicValue& value) {
    return value.display.empty() ? trim(value.raw) : value.display;
}

std::string logic_value_compare_key(const LogicValue& value) {
    if (!value.valid || !value.known) return std::string();
    std::string key = value.bits.empty() ? logic_value_compact_string(value) : bits_to_hex(value.bits);
    size_t first = key.find_first_not_of('0');
    return first == std::string::npos ? "0" : key.substr(first);
}

bool logic_value_has_xz(const LogicValue& value) {
    return !value.known || value.has_x || value.has_z;
}

} // namespace xdebug_core
