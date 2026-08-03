#include "engine/service/actions/protocol/protocol_statistics_filter.h"
#include "waveform/filter/value_filter.h"

#include <cassert>
#include <string>

using namespace xdebug_design;

int main() {
    {
        xdebug_waveform::ValueFilter wide_filter;
        xdebug_waveform::ValueFilterError wide_error;
        xdebug_waveform::ValueFilterParseOptions wide_options;
        Json spec = {{"mode", "range"},
                     {"begin", "128'h10000000000000000000000000000000"},
                     {"end", "128'h1fffffffffffffffffffffffffffffff"}};
        assert(xdebug_waveform::parse_value_filter(
            spec, "args.filter.fields.data", wide_options, wide_filter, wide_error));
        assert(xdebug_waveform::match_value_filter(
            wide_filter,
            xdebug_core::logic_value_from_bits(
                "00011000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
                128)) == xdebug_waveform::ValueFilterMatch::Yes);

        Json mask_spec = {{"mode", "mask"}, {"value", "8'ha0"}, {"mask", "8'hf0"}};
        assert(xdebug_waveform::parse_value_filter(
            mask_spec, "args.filter.fields.data", wide_options, wide_filter, wide_error));
        assert(xdebug_waveform::match_value_filter(
            wide_filter, xdebug_core::logic_value_from_bits("1010xxxx", 8)) ==
            xdebug_waveform::ValueFilterMatch::Yes);
        assert(xdebug_waveform::match_value_filter(
            wide_filter, xdebug_core::logic_value_from_bits("x0100000", 8)) ==
            xdebug_waveform::ValueFilterMatch::Unresolved);
    }

    StatisticsFilter filter;
    StatisticsFilterError error;

    Json c_hex_args = {{"filter", {{"address", {
        {"mode", "exact"}, {"values", Json::array({"0x10"})},
    }}}}};
    assert(!parse_statistics_filter(c_hex_args, false, filter, error));
    assert(error.invalid_arg == "args.filter.address.values[0]");

    Json exact_args = {{"filter", {
        {"direction", "all"},
        {"address", {{"mode", "exact"},
                     {"values", Json::array({"'h10", "'h20"})}}},
    }}};
    assert(parse_statistics_filter(exact_args, false, filter, error));
    assert(filter.address_mode == StatisticsAddressMode::Exact);
    assert(filter.address_values.size() == 2);
    assert(match_statistics_transaction(filter, {false, "10", ""}) ==
           StatisticsMatch::Yes);
    assert(match_statistics_transaction(filter, {true, "30", ""}) ==
           StatisticsMatch::No);
    assert(match_statistics_transaction(filter, {true, "x0", ""}) ==
           StatisticsMatch::Unresolved);

    Json duplicate_args = {{"filter", {{"address", {
        {"mode", "exact"}, {"values", Json::array({"16", "'h10"})},
    }}}}};
    assert(!parse_statistics_filter(duplicate_args, false, filter, error));
    assert(error.invalid_arg == "args.filter.address.values");

    Json range_args = {{"filter", {
        {"direction", "read"},
        {"ids", Json::array({"1", "3"})},
        {"address", {{"mode", "range"}, {"begin", "'h1000"},
                     {"end", "'h1fff"}}},
    }}};
    assert(parse_statistics_filter(range_args, true, filter, error));
    assert(match_statistics_transaction(filter, {false, "1004", "1"}) ==
           StatisticsMatch::Yes);
    assert(match_statistics_transaction(filter, {false, "1004", "2"}) ==
           StatisticsMatch::No);
    assert(match_statistics_transaction(filter, {true, "x", "x"}) ==
           StatisticsMatch::No);
    assert(match_statistics_transaction(filter, {false, "x", "1"}) ==
           StatisticsMatch::Unresolved);

    Json mask_args = {{"filter", {{"address", {
        {"mode", "mask"}, {"value", "'h1200"}, {"mask", "'hff00"},
    }}}}};
    assert(parse_statistics_filter(mask_args, false, filter, error));
    assert(match_statistics_transaction(filter, {true, "12ab", ""}) ==
           StatisticsMatch::Yes);
    assert(match_statistics_transaction(filter, {true, "13ab", ""}) ==
           StatisticsMatch::No);

    Json zero_mask = {{"filter", {{"address", {
        {"mode", "mask"}, {"value", "0"}, {"mask", "0"},
    }}}}};
    assert(!parse_statistics_filter(zero_mask, false, filter, error));
    assert(error.invalid_arg == "args.filter.address.mask");

    Json ids_for_apb = {{"filter", {{"ids", Json::array({"1"})}}}};
    assert(!parse_statistics_filter(ids_for_apb, false, filter, error));
    assert(error.invalid_arg == "args.filter.ids");

    Json no_filter = Json::object();
    assert(parse_statistics_filter(no_filter, true, filter, error));
    assert(!filter.filter_applied);
    assert(match_statistics_transaction(filter, {false, "x", "x"}) ==
           StatisticsMatch::Yes);

    assert(std::string(statistics_unresolved_note()).find("X/Z") != std::string::npos);

    Json response = {
        {"summary", {
            {"name", "axi0"},
            {"scanned_transaction_count", 64},
            {"matched_transaction_count", 6},
            {"matched_read_count", 2},
            {"matched_write_count", 4},
            {"unresolved_transaction_count", 0},
            {"filter_applied", true},
            {"scan_complete", true},
            {"analysis_complete", true},
            {"response_truncated", false},
        }},
        {"data", {
            {"filter", {
                {"direction", "all"},
                {"ids", Json::array({"4'h1", "4'h3"})},
                {"address", {{"mode", "range"}, {"begin", "16'h1000"},
                             {"end", "16'h1fff"}}},
            }},
        }},
    };
    const std::string xout = render_statistics_xout("axi.statistics", response);
    assert(xout.find("@xdebug.axi.statistics.v1") == 0);
    assert(xout.find("scanned_transaction_count   : 64") != std::string::npos);
    assert(xout.find("unresolved_transaction_count: 0") != std::string::npos);
    assert(xout.find("direction    : all") != std::string::npos);
    assert(xout.find("ids          : [4'h1, 4'h3]") != std::string::npos);
    assert(xout.find("address_begin: 16'h1000") != std::string::npos);
    assert(xout.find(std::string("notes:\n  unresolved_transaction_count: ") +
                     statistics_unresolved_note()) != std::string::npos);
    assert(xout.find("pointer\tkind\tvalue") == std::string::npos);
    assert(xout.find("XOUT_BEGIN") == std::string::npos);
    assert(xout.find("XOUT_END") == std::string::npos);
    return 0;
}
