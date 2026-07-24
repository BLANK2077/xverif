#pragma once

#include "core/value/logic_value.h"

// Transitional source-compatibility surface for waveform code.  The canonical
// implementation lives in core/value so frontend XOUT and the engine use the
// same parser and renderer.
namespace xdebug_waveform {

using xdebug_core::LogicValue;
using xdebug_core::ValueRenderFormat;
using xdebug_core::apply_value_render_format;
using xdebug_core::apply_value_width_summary;
using xdebug_core::is_legacy_0x_literal;
using xdebug_core::logic_value_compare_key;
using xdebug_core::logic_value_compact_string;
using xdebug_core::logic_value_from_bits;
using xdebug_core::logic_value_from_fsdb_raw;
using xdebug_core::logic_value_has_xz;
using xdebug_core::logic_value_json;
using xdebug_core::parse_user_logic_literal;
using xdebug_core::parse_value_render_format;
using xdebug_core::value_format_invalid_message;
using xdebug_core::value_render_format_text;

using Json = nlohmann::ordered_json;

} // namespace xdebug_waveform
