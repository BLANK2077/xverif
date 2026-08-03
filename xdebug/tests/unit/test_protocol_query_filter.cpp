#include "engine/service/actions/protocol/protocol_query_filter.h"

#include <cassert>

using namespace xdebug_design;

int main() {
    ProtocolQueryFilter filter;
    ProtocolQueryFilterError error;

    const Json exact = {
        {"mode", "exact"},
        {"values", Json::array({"32'h1000", "32'h2000"})},
    };
    assert(parse_protocol_query_filter(
        exact, Json(), false, filter, error));
    assert(filter.has_address);
    assert(!filter.has_id);
    assert(match_protocol_query_filter(
        filter, "1000", 32) ==
        xdebug_waveform::ValueFilterMatch::Yes);
    assert(match_protocol_query_filter(
        filter, "3000", 32) ==
        xdebug_waveform::ValueFilterMatch::No);

    const Json range = {
        {"mode", "range"},
        {"begin", "32'h1000"},
        {"end", "32'h1fff"},
    };
    const Json id_range = {
        {"mode", "range"},
        {"begin", "4'h2"},
        {"end", "4'h5"},
    };
    assert(parse_protocol_query_filter(
        range, id_range, true, filter, error));
    assert(match_protocol_query_filter(
        filter, "1010", 32, "3", 4) ==
        xdebug_waveform::ValueFilterMatch::Yes);
    assert(match_protocol_query_filter(
        filter, "1010", 32, "7", 4) ==
        xdebug_waveform::ValueFilterMatch::No);
    assert(match_protocol_query_filter(
        filter, "xxxx", 32, "3", 4) ==
        xdebug_waveform::ValueFilterMatch::Unresolved);

    const Json mask = {
        {"mode", "mask"},
        {"value", "32'h1200"},
        {"mask", "32'hff00"},
    };
    assert(parse_protocol_query_filter(
        mask, Json(), false, filter, error));
    assert(match_protocol_query_filter(
        filter, "12ab", 32) ==
        xdebug_waveform::ValueFilterMatch::Yes);
    assert(match_protocol_query_filter(
        filter, "13ab", 32) ==
        xdebug_waveform::ValueFilterMatch::No);

    const Json zero_mask = {
        {"mode", "mask"},
        {"value", "0"},
        {"mask", "0"},
    };
    assert(!parse_protocol_query_filter(
        zero_mask, Json(), false, filter, error));
    assert(error.invalid_arg == "args.address.mask");

    assert(!parse_protocol_query_filter(
        Json(), id_range, false, filter, error));
    assert(error.invalid_arg == "args.id");

    assert(!parse_protocol_query_filter(
        Json(),
        Json{
            {"mode", "mask"},
            {"value", "4'h2"},
            {"mask", "4'hf"},
        },
        true,
        filter,
        error));
    assert(error.invalid_arg == "args.id.mode");
    return 0;
}
