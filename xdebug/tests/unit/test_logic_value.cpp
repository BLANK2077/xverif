#include "core/value/logic_value.h"

#include <cassert>

using namespace xdebug_core;

using Json = nlohmann::ordered_json;

int main() {
    LogicValue fsdb_hex = logic_value_from_fsdb_raw("22", 'h');
    assert(fsdb_hex.valid);
    assert(fsdb_hex.known);
    assert(logic_value_compact_string(fsdb_hex) == "'h22");

    LogicValue fsdb_sized = logic_value_from_fsdb_raw("22", 'h', 8);
    assert(fsdb_sized.valid);
    assert(fsdb_sized.known);
    assert(fsdb_sized.width == 8);
    assert(logic_value_compact_string(fsdb_sized) == "8'h22");
    assert(logic_value_json(fsdb_sized)["bits"] == "00100010");
    assert(logic_value_json(fsdb_sized, ValueRenderFormat::Dec)["value"] == "8'd34");
    assert(logic_value_json(fsdb_sized, ValueRenderFormat::Bin)["value"] == "8'b00100010");
    {
        ScopedValueRenderFormat scoped(ValueRenderFormat::Dec);
        assert(current_value_render_format() == ValueRenderFormat::Dec);
        assert(render_logic_value(fsdb_sized) == "8'd34");
    }
    assert(current_value_render_format() == ValueRenderFormat::Hex);
    assert(render_logic_value(fsdb_sized) == "8'h22");

    LogicValue unsized_binary = logic_value_from_fsdb_raw("00100010", 'b');
    assert(!unsized_binary.width_reliable);
    assert(render_logic_value(unsized_binary) == "'h22");

    LogicValue unknown = logic_value_from_fsdb_raw("xz", 'h', 8);
    assert(unknown.valid);
    assert(!unknown.known);
    assert(unknown.has_x);
    assert(unknown.has_z);
    assert(logic_value_compact_string(unknown) == "8'hxz");
    Json unknown_dec = logic_value_json(unknown, ValueRenderFormat::Dec);
    assert(unknown_dec["value"] == "8'bxxxxzzzz");
    assert(unknown_dec["requested_value_format"] == "dec");
    assert(unknown_dec["effective_value_format"] == "bin");

    const std::string known_aggregate_text =
        "'b{01011010,0011,0010,1010010101011010}";
    LogicValue known_aggregate = logic_value_from_fsdb_raw(
        known_aggregate_text, 'h', 32);
    assert(known_aggregate.valid);
    assert(known_aggregate.known);
    assert(!known_aggregate.has_x);
    assert(!known_aggregate.has_z);
    assert(known_aggregate.bits.empty());
    assert(!known_aggregate.width_reliable);
    assert(known_aggregate.width == 0);
    assert(logic_value_compact_string(known_aggregate) ==
           known_aggregate_text);
    assert(logic_value_compare_key(known_aggregate).empty());
    assert(logic_value_json(known_aggregate)["value"] ==
           known_aggregate_text);
    for (ValueRenderFormat format : {
             ValueRenderFormat::Hex,
             ValueRenderFormat::Bin,
             ValueRenderFormat::Dec}) {
        Json rendered = logic_value_json(known_aggregate, format);
        assert(rendered["value"] == known_aggregate_text);
        assert(rendered["known"] == true);
        assert(!rendered.contains("width"));
        assert(!rendered.contains("bits"));
        assert(!rendered.contains("has_x"));
        assert(!rendered.contains("has_z"));
        assert(render_logic_value(known_aggregate, format) ==
               known_aggregate_text);
    }

    const std::string x_aggregate_text = "'b{010x,0011}";
    LogicValue x_aggregate = logic_value_from_fsdb_raw(
        x_aggregate_text, 'b');
    assert(x_aggregate.valid);
    assert(!x_aggregate.known);
    assert(x_aggregate.has_x);
    assert(!x_aggregate.has_z);
    assert(x_aggregate.bits.empty());
    assert(logic_value_json(x_aggregate)["value"] == x_aggregate_text);
    Json x_aggregate_dec = logic_value_json(
        x_aggregate, ValueRenderFormat::Dec);
    assert(x_aggregate_dec["value"] == x_aggregate_text);
    assert(x_aggregate_dec["known"] == false);
    assert(x_aggregate_dec["has_x"] == true);
    assert(x_aggregate_dec["has_z"] == false);
    assert(!x_aggregate_dec.contains("requested_value_format"));
    assert(!x_aggregate_dec.contains("effective_value_format"));
    for (ValueRenderFormat format : {
             ValueRenderFormat::Hex,
             ValueRenderFormat::Bin,
             ValueRenderFormat::Dec}) {
        assert(logic_value_json(x_aggregate, format)["value"] ==
               x_aggregate_text);
        assert(render_logic_value(x_aggregate, format) ==
               x_aggregate_text);
    }

    const std::string z_aggregate_text = "'b{0101,00z1}";
    LogicValue z_aggregate = logic_value_from_fsdb_raw(
        z_aggregate_text, 'h');
    assert(z_aggregate.valid);
    assert(!z_aggregate.known);
    assert(!z_aggregate.has_x);
    assert(z_aggregate.has_z);
    assert(z_aggregate.bits.empty());
    assert(logic_value_json(z_aggregate)["value"] == z_aggregate_text);
    Json z_aggregate_hex = logic_value_json(
        z_aggregate, ValueRenderFormat::Hex);
    assert(z_aggregate_hex["value"] == z_aggregate_text);
    assert(z_aggregate_hex["known"] == false);
    assert(z_aggregate_hex["has_x"] == false);
    assert(z_aggregate_hex["has_z"] == true);
    for (ValueRenderFormat format : {
             ValueRenderFormat::Hex,
             ValueRenderFormat::Bin,
             ValueRenderFormat::Dec}) {
        assert(logic_value_json(z_aggregate, format)["value"] ==
               z_aggregate_text);
        assert(render_logic_value(z_aggregate, format) ==
               z_aggregate_text);
    }

    LogicValue invalid_aggregate = logic_value_from_fsdb_raw(
        "'b{0101,bad}", 'b');
    assert(!invalid_aggregate.valid);
    assert(!invalid_aggregate.known);

    Json nested = {{"stable", unknown_dec},
                   {"changes", Json::array({{{"value", logic_value_json(fsdb_sized)}}})},
                   {"time", "10ns"}};
    apply_value_render_format(nested, ValueRenderFormat::Dec);
    assert(nested["stable"]["value"] == "8'bxxxxzzzz");
    assert(nested["changes"][0]["value"]["value"] == "8'd34");
    assert(nested["time"] == "10ns");
    apply_value_width_summary(nested);
    assert(nested["summary"]["value_width_complete"] == true);
    assert(nested["summary"]["width_diagnostics"].empty());

    Json incomplete = {
        {"signal", "top.u.data"},
        {"value", logic_value_json(fsdb_hex)}
    };
    apply_value_width_summary(incomplete);
    assert(incomplete["summary"]["value_width_complete"] == false);
    assert(incomplete["summary"]["width_diagnostics"].size() == 1);
    assert(incomplete["summary"]["width_diagnostics"][0]["signal"] ==
           "top.u.data");
    assert(incomplete["summary"]["width_diagnostics"][0]["reason"] ==
           "npi_range_size_unavailable");

    Json stream_incomplete = {
        {"summary", {{"stream", "pipe0"}}},
        {"transfers", Json::array({{{"data", "'h22"}}})}
    };
    apply_value_width_summary(stream_incomplete);
    assert(stream_incomplete["summary"]["value_width_complete"] == false);
    assert(stream_incomplete["summary"]["width_diagnostics"][0]["reason"] ==
           "derived_width_unavailable");

    Json conflicting = {
        {"summary",
         {{"width_diagnostics",
           Json::array({{{"signal", nullptr},
                         {"role", "filter.addresses[0]"},
                         {"reason", "conflicting_signal_widths"}}})}}},
        {"filter", {{"addresses", Json::array({"'h22"})}}}
    };
    apply_value_width_summary(conflicting);
    assert(conflicting["summary"]["width_diagnostics"].size() == 1);
    assert(conflicting["summary"]["width_diagnostics"][0]["reason"] ==
           "conflicting_signal_widths");

    LogicValue user_sv = parse_user_logic_literal("8'h22");
    assert(user_sv.valid);
    assert(user_sv.known);
    assert(logic_value_compact_string(user_sv) == "8'h22");
    assert(logic_value_compare_key(user_sv) == "22");

    LogicValue user_bin = parse_user_logic_literal("'b1010");
    assert(user_bin.valid);
    assert(user_bin.width == 4);
    assert(logic_value_compact_string(user_bin) == "4'ha");

    LogicValue user_dec = parse_user_logic_literal("34");
    assert(user_dec.valid);
    assert(logic_value_compact_string(user_dec) == "'h22");

    LogicValue wide_dec = parse_user_logic_literal(
        "128'd340282366920938463463374607431768211455");
    assert(wide_dec.valid);
    assert(wide_dec.bits.size() == 128);
    assert(wide_dec.bits.find('0') == std::string::npos);

    LogicValue c_hex = parse_user_logic_literal("0x22");
    assert(!c_hex.valid);
    assert(c_hex.error.find("0x prefix is not accepted") != std::string::npos);

    return 0;
}
