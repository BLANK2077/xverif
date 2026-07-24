#pragma once

#include "json.hpp"

#include <string>

namespace xdebug_core {

using LogicJson = nlohmann::ordered_json;

struct LogicValue {
    std::string raw;
    std::string display;
    std::string bits;
    int width = 0;
    bool width_reliable = false;
    bool known = true;
    bool has_x = false;
    bool has_z = false;
    bool valid = true;
    std::string error;
};

enum class ValueRenderFormat { Hex, Bin, Dec };

bool parse_value_render_format(const std::string& text, ValueRenderFormat& out);
std::string value_render_format_text(ValueRenderFormat format);

LogicValue logic_value_from_fsdb_raw(const std::string& raw, char radix,
                                     int width_hint = 0);
LogicValue logic_value_from_bits(const std::string& bits, int width_hint = 0);
LogicValue parse_user_logic_literal(const std::string& text);

LogicJson logic_value_json(const LogicValue& value,
                           ValueRenderFormat format = ValueRenderFormat::Hex);
// Re-render every logic-value JSON object in a response tree.  Only objects
// carrying the canonical bits field are touched, so unrelated strings such as
// times, paths and exported-file metadata keep their original meaning.
void apply_value_render_format(LogicJson& response, ValueRenderFormat format);
// Inspect canonical LogicValue objects and compact SV literal strings in an
// action data tree.  When values are present, publish width completeness in
// data.summary and list every unsized value by response role.
void apply_value_width_summary(LogicJson& response);
std::string logic_value_compact_string(const LogicValue& value);
std::string logic_value_compare_key(const LogicValue& value);
bool logic_value_has_xz(const LogicValue& value);

bool is_legacy_0x_literal(const std::string& text);
std::string value_format_invalid_message(const std::string& value);

} // namespace xdebug_core
