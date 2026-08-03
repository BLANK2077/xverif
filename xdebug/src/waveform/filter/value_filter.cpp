#include "value_filter.h"

#include <algorithm>
#include <set>

namespace xdebug_waveform {
namespace {

std::string trim_unsigned_bits(const std::string& bits) {
    const size_t first = bits.find_first_not_of('0');
    return first == std::string::npos ? "0" : bits.substr(first);
}

bool parse_literal(const std::string& text, const std::string& path,
                   const ValueFilterParseOptions& options,
                   std::string& bits, ValueFilterError& error) {
    xdebug_core::LogicValue value =
        xdebug_core::parse_user_logic_literal(text);
    if (!value.valid) {
        error = {path, value.error, "known integer, hexadecimal, or SystemVerilog literal"};
        return false;
    }
    if (xdebug_core::logic_value_has_xz(value)) {
        error = {path, "value literal must not contain X/Z: " + text,
                 "known integer, hexadecimal, or SystemVerilog literal"};
        return false;
    }
    if (options.max_bits > 0 && value.bits.size() > options.max_bits) {
        error = {path, "value literal must be at most " +
                       std::to_string(options.max_bits) + " bits: " + text,
                 "known literal up to " + std::to_string(options.max_bits) + " bits"};
        return false;
    }
    bits = value.bits;
    return true;
}

bool mask_is_zero(const std::string& bits) {
    return bits.find('1') == std::string::npos;
}

}  // namespace

int compare_unsigned_filter_bits(const std::string& lhs,
                                 const std::string& rhs) {
    const std::string a = trim_unsigned_bits(lhs);
    const std::string b = trim_unsigned_bits(rhs);
    if (a.size() != b.size()) return a.size() < b.size() ? -1 : 1;
    if (a == b) return 0;
    return a < b ? -1 : 1;
}

bool parse_value_filter(const Json& spec, const std::string& path,
                        const ValueFilterParseOptions& options,
                        ValueFilter& out, ValueFilterError& error) {
    out = ValueFilter();
    const std::string mode = spec.value("mode", std::string());
    if (mode == "exact") {
        out.mode = ValueFilterMode::Exact;
        const Json values = spec.value("values", Json::array());
        if (!values.is_array() || values.empty()) {
            error = {path + ".values", "exact filter requires a non-empty values queue",
                     "non-empty queue of numerically distinct known literals"};
            return false;
        }
        std::set<std::string> seen;
        for (size_t index = 0; index < values.size(); ++index) {
            std::string bits;
            const std::string item_path = path + ".values[" + std::to_string(index) + "]";
            if (!parse_literal(values[index].get<std::string>(), item_path,
                               options, bits, error)) return false;
            const std::string normalized = trim_unsigned_bits(bits);
            if (!seen.insert(normalized).second) {
                error = {path + ".values",
                         "values must remain unique after numeric normalization",
                         "non-empty queue of numerically distinct known literals"};
                return false;
            }
            out.values.push_back(bits);
        }
        return true;
    }
    if (mode == "range") {
        out.mode = ValueFilterMode::Range;
        if (!parse_literal(spec.value("begin", std::string()), path + ".begin",
                           options, out.begin, error)) return false;
        if (!parse_literal(spec.value("end", std::string()), path + ".end",
                           options, out.end, error)) return false;
        if (compare_unsigned_filter_bits(out.begin, out.end) > 0) {
            error = {path + ".end", "range begin must not exceed end",
                     "inclusive range with begin <= end"};
            return false;
        }
        return true;
    }
    if (mode == "mask") {
        out.mode = ValueFilterMode::Mask;
        if (!parse_literal(spec.value("value", std::string()), path + ".value",
                           options, out.value, error)) return false;
        if (!parse_literal(spec.value("mask", std::string()), path + ".mask",
                           options, out.mask, error)) return false;
        if (options.require_nonzero_mask && mask_is_zero(out.mask)) {
            error = {path + ".mask", "mask must be non-zero", "non-zero mask"};
            return false;
        }
        return true;
    }
    error = {path + ".mode", "filter mode must be exact, range, or mask",
             "one of exact, range, or mask"};
    return false;
}

ValueFilterMatch match_value_filter(const ValueFilter& filter,
                                    const xdebug_core::LogicValue& value) {
    if (filter.mode == ValueFilterMode::Mask) {
        const size_t width = std::max(value.bits.size(),
            std::max(filter.value.size(), filter.mask.size()));
        for (size_t offset = 0; offset < width; ++offset) {
            const auto from_lsb = [offset](const std::string& bits) -> char {
                return offset < bits.size() ? bits[bits.size() - 1 - offset] : '0';
            };
            if (from_lsb(filter.mask) != '1') continue;
            const char actual = from_lsb(value.bits);
            if (actual != '0' && actual != '1') return ValueFilterMatch::Unresolved;
            if (actual != from_lsb(filter.value)) return ValueFilterMatch::No;
        }
        return ValueFilterMatch::Yes;
    }
    if (!value.valid || xdebug_core::logic_value_has_xz(value))
        return ValueFilterMatch::Unresolved;
    if (filter.mode == ValueFilterMode::Exact) {
        for (const auto& expected : filter.values) {
            if (compare_unsigned_filter_bits(value.bits, expected) == 0)
                return ValueFilterMatch::Yes;
        }
        return ValueFilterMatch::No;
    }
    return compare_unsigned_filter_bits(value.bits, filter.begin) >= 0 &&
           compare_unsigned_filter_bits(value.bits, filter.end) <= 0
        ? ValueFilterMatch::Yes : ValueFilterMatch::No;
}

ValueFilterMatch value_filter_and(ValueFilterMatch lhs,
                                  ValueFilterMatch rhs) {
    if (lhs == ValueFilterMatch::No || rhs == ValueFilterMatch::No)
        return ValueFilterMatch::No;
    if (lhs == ValueFilterMatch::Unresolved || rhs == ValueFilterMatch::Unresolved)
        return ValueFilterMatch::Unresolved;
    return ValueFilterMatch::Yes;
}

bool filter_bits_to_uint64(const std::string& bits, uint64_t& out) {
    if (bits.size() > 64 || bits.find_first_not_of("01") != std::string::npos)
        return false;
    out = 0;
    for (char bit : bits) {
        out <<= 1U;
        if (bit == '1') out |= 1U;
    }
    return true;
}

}  // namespace xdebug_waveform
