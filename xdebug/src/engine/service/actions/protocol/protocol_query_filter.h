#pragma once

#include "json.hpp"
#include "waveform/filter/value_filter.h"

#include <string>

namespace xdebug_design {

using Json = nlohmann::ordered_json;

struct ProtocolQueryFilterError {
    std::string invalid_arg;
    std::string message;
    std::string expected;
};

struct ProtocolQueryFilter {
    bool has_address = false;
    bool has_id = false;
    xdebug_waveform::ValueFilter address;
    xdebug_waveform::ValueFilter id;
    Json address_json;
    Json id_json;
};

bool parse_protocol_query_filter(
    const Json& address,
    const Json& id,
    bool allow_id,
    ProtocolQueryFilter& out,
    ProtocolQueryFilterError& error);

xdebug_waveform::ValueFilterMatch match_protocol_query_filter(
    const ProtocolQueryFilter& filter,
    const std::string& address,
    int address_width,
    const std::string& id = std::string(),
    int id_width = 0);

bool protocol_direction_matches(bool is_write,
                                const std::string& direction);

}  // namespace xdebug_design
