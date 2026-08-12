#pragma once

#ifndef XDEBUG_STREAM_DIFFERENTIAL_TEST_BUILD
#error "legacy stream oracle is only available in the differential test build"
#endif

#include "waveform/stream/stream_analyzer.h"

namespace xdebug_stream_differential {

bool analyze_stream_cached_and_compare_legacy(
    xdebug_waveform::StreamAnalyzer& analyzer, npiFsdbFileHandle file,
    const xdebug_waveform::StreamConfig& config,
    const xdebug_waveform::StreamQueryOptions& options,
    xdebug_waveform::AnalysisCacheScope cache_scope,
    xdebug_waveform::StreamAnalysis& analysis, std::string& error);

}  // namespace xdebug_stream_differential
