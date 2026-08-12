#include "stream_differential/legacy_stream_oracle.h"

namespace xdebug_stream_differential {
namespace {

using xdebug_waveform::Json;
using xdebug_waveform::StreamAnalysis;
using xdebug_waveform::StreamConfig;
using xdebug_waveform::StreamPacket;
using xdebug_waveform::StreamQueryOptions;

Json analysis_snapshot(const StreamConfig& config,
                       const StreamQueryOptions& options,
                       const StreamAnalysis& analysis) {
    Json transfers = Json::array();
    for (const auto& row : analysis.transfers)
        transfers.push_back(xdebug_waveform::stream_row_json(row));
    Json stalls = Json::array();
    for (const auto& stall : analysis.stalls)
        stalls.push_back(xdebug_waveform::stream_stall_json(stall));
    Json packets = Json::array();
    auto append_packet = [&](const StreamPacket& packet) {
        packets.push_back(xdebug_waveform::stream_packet_json(packet));
    };
    if (options.query_kind.empty()) {
        for (const auto& packet : analysis.packets) append_packet(packet);
    } else if (!options.filter.enabled && options.query_kind == "first_packet") {
        if (!analysis.packets.empty()) append_packet(analysis.packets.front());
    } else if (!options.filter.enabled && options.query_kind == "last_packet") {
        if (!analysis.packets.empty()) append_packet(analysis.packets.back());
    } else if (!options.filter.enabled && options.query_kind == "packet_at") {
        for (const auto& packet : analysis.packets) {
            if (packet.packet_index == options.packet_index) {
                append_packet(packet);
                break;
            }
        }
    } else if (options.query_kind == "packet_window") {
        for (std::size_t i = 0; i < analysis.packets.size() &&
             (options.limit <= 0 || static_cast<int>(i) < options.limit); ++i)
            append_packet(analysis.packets[i]);
    }
    Json out = {
        {"summary", xdebug_waveform::stream_summary_json(config, analysis)},
        {"transfers", transfers},
        {"stalls", stalls},
        {"packets", packets},
        {"matched_transfer_count", analysis.matched_transfer_count},
        {"matched_packet_count", analysis.matched_packet_count},
        {"unresolved_filter_count", analysis.unresolved_filter_count},
        {"has_transfer_evidence", analysis.has_transfer_evidence},
        {"has_matched_packet_evidence", analysis.has_matched_packet_evidence},
    };
    if (analysis.has_transfer_evidence) {
        out["first_transfer"] =
            xdebug_waveform::stream_row_json(analysis.first_transfer);
        out["last_transfer"] =
            xdebug_waveform::stream_row_json(analysis.last_transfer);
    }
    if (analysis.has_matched_packet_evidence) {
        out["first_matched_packet"] = xdebug_waveform::stream_packet_json(
            analysis.first_matched_packet);
        out["last_matched_packet"] = xdebug_waveform::stream_packet_json(
            analysis.last_matched_packet);
    }
    return out;
}

}  // namespace

bool analyze_stream_cached_and_compare_legacy(
    xdebug_waveform::StreamAnalyzer& analyzer, npiFsdbFileHandle file,
    const StreamConfig& config, const StreamQueryOptions& options,
    xdebug_waveform::AnalysisCacheScope cache_scope, StreamAnalysis& analysis,
    std::string& error) {
    if (!analyzer.analyze_cached(
            file, config, options, cache_scope, analysis, error))
        return false;

    xdebug_waveform::StreamAnalyzer legacy_analyzer;
    StreamAnalysis expected;
    std::string legacy_error;
    if (!legacy_analyzer.analyze_legacy(
            file, config, options, expected, legacy_error, false)) {
        error = "legacy stream differential oracle failed: " + legacy_error;
        return false;
    }
    if (analysis_snapshot(config, options, analysis) !=
        analysis_snapshot(config, options, expected)) {
        error = "stream columnar differential mismatch for " + config.name;
        return false;
    }
    return true;
}

}  // namespace xdebug_stream_differential
