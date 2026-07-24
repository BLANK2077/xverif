#include "waveform/value/logic_value.h"

#include <cassert>

using namespace xdebug_waveform;

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

    LogicValue legacy = parse_user_logic_literal("0x22");
    assert(!legacy.valid);
    assert(legacy.error.find("0x prefix is not accepted") != std::string::npos);

    return 0;
}
