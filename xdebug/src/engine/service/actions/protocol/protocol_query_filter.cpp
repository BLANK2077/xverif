#include "protocol_query_filter.h"

#include "core/value/logic_value.h"

namespace xdebug_design {

namespace {

void copy_error(
    const xdebug_waveform::ValueFilterError& source,
    ProtocolQueryFilterError& target) {
    target = {source.invalid_arg, source.message, source.expected};
}

}  // namespace

bool parse_protocol_query_filter(
    const Json& address,
    const Json& id,
    bool allow_id,
    ProtocolQueryFilter& out,
    ProtocolQueryFilterError& error) {
    out = ProtocolQueryFilter();
    xdebug_waveform::ValueFilterParseOptions options;
    options.max_bits = 64;

    if (!address.is_null()) {
        out.has_address = true;
        out.address_json = address;
        options.require_nonzero_mask = true;
        xdebug_waveform::ValueFilterError parse_error;
        if (!xdebug_waveform::parse_value_filter(
                address, "args.address", options, out.address, parse_error)) {
            copy_error(parse_error, error);
            return false;
        }
    }

    if (!id.is_null()) {
        if (!allow_id) {
            error = {"args.id", "APB query does not support transaction IDs",
                     "omit id for apb.query"};
            return false;
        }
        out.has_id = true;
        out.id_json = id;
        options.require_nonzero_mask = false;
        xdebug_waveform::ValueFilterError parse_error;
        if (!xdebug_waveform::parse_value_filter(
                id, "args.id", options, out.id, parse_error)) {
            copy_error(parse_error, error);
            return false;
        }
        if (out.id.mode == xdebug_waveform::ValueFilterMode::Mask) {
            error = {"args.id.mode", "AXI query ID filter does not support mask",
                     "one of exact or range"};
            return false;
        }
    }
    return true;
}

xdebug_waveform::ValueFilterMatch match_protocol_query_filter(
    const ProtocolQueryFilter& filter,
    const std::string& address,
    int address_width,
    const std::string& id,
    int id_width) {
    using xdebug_waveform::ValueFilterMatch;
    ValueFilterMatch result = ValueFilterMatch::Yes;
    if (filter.has_address) {
        const xdebug_core::LogicValue value =
            xdebug_core::logic_value_from_fsdb_raw(
                address, 'h', address_width);
        result = xdebug_waveform::value_filter_and(
            result,
            xdebug_waveform::match_value_filter(filter.address, value));
    }
    if (filter.has_id) {
        const xdebug_core::LogicValue value =
            xdebug_core::logic_value_from_fsdb_raw(id, 'h', id_width);
        result = xdebug_waveform::value_filter_and(
            result,
            xdebug_waveform::match_value_filter(filter.id, value));
    }
    return result;
}

bool protocol_direction_matches(bool is_write,
                                const std::string& direction) {
    return direction == "all" ||
           (direction == "write" && is_write) ||
           (direction == "read" && !is_write);
}

}  // namespace xdebug_design
