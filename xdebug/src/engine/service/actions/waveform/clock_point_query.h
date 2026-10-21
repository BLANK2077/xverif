#pragma once

#include "api/json_types.h"
#include "waveform/common/clock_sampling.h"

#include "npi_fsdb.h"

#include <string>
#include <vector>

namespace xdebug_design {

using Json = xdebug::Json;

struct PointSignalSpec {
    std::string label;
    std::string path;
};

struct ClockPointQueryResult {
    Json clock_context;
    Json rows;
    Json samples;
};

bool parse_point_clock_args(const Json& args,
                            xdebug_waveform::ClockSampleSpec& spec,
                            Json& error);

bool build_clock_point_query(npiFsdbFileHandle fsdb,
                             const xdebug_waveform::ClockSampleSpec& spec,
                             npiFsdbTime requested_time,
                             const std::string& formatted_requested_time,
                             const std::vector<PointSignalSpec>& signals,
                             npiFsdbValType value_type,
                             char value_prefix,
                             const std::string& action,
                             const std::string& invalid_arg,
                             ClockPointQueryResult& out,
                             Json& error);

Json point_cell_value(const Json& row, const char* key);

} // namespace xdebug_design
