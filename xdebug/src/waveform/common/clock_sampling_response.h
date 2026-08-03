#pragma once

#include "clock_sampling.h"
#include "json.hpp"

namespace xdebug_waveform {

using ClockSamplingJson = nlohmann::ordered_json;

ClockSamplingJson clock_sampling_contract_json(
    const ClockSampleSpec& spec);

ClockSamplingJson clock_point_context_json(
    npiFsdbFileHandle fsdb,
    const ClockSampleSpec& spec,
    const ClockPointContext& context);

} // namespace xdebug_waveform
