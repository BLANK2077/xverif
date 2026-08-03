#pragma once

#include "json.hpp"
#include "core/value/logic_value.h"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace xdebug_waveform {

using Json = nlohmann::ordered_json;

enum class ValueFilterMode { Exact, Range, Mask };
enum class ValueFilterMatch { No, Yes, Unresolved };

struct ValueFilter {
    ValueFilterMode mode = ValueFilterMode::Exact;
    std::vector<std::string> values;
    std::string begin;
    std::string end;
    std::string value;
    std::string mask;
};

struct ValueFilterParseOptions {
    size_t max_bits = 0;
    bool require_nonzero_mask = false;
};

struct ValueFilterError {
    std::string invalid_arg;
    std::string message;
    std::string expected;
};

bool parse_value_filter(const Json& spec, const std::string& path,
                        const ValueFilterParseOptions& options,
                        ValueFilter& out, ValueFilterError& error);
ValueFilterMatch match_value_filter(const ValueFilter& filter,
                                    const xdebug_core::LogicValue& value);
ValueFilterMatch value_filter_and(ValueFilterMatch lhs,
                                  ValueFilterMatch rhs);
int compare_unsigned_filter_bits(const std::string& lhs,
                                 const std::string& rhs);
bool filter_bits_to_uint64(const std::string& bits, uint64_t& out);

}  // namespace xdebug_waveform
