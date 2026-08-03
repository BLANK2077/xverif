#include "clock_sampling_response.h"

#include "core/npi/time_contract.h"

namespace xdebug_waveform {
namespace {

constexpr const char* kNegedgeSamplePointIgnoredReason =
    "negedge keeps the established current-value sampling semantics";

ClockSamplingJson requested_sampling_json(
    const ClockSampleSpec& spec) {
    return {
        {"edge", clock_edge_kind_text(spec.edge)},
        {"sample_point", spec.has_sample_point
            ? ClockSamplingJson(clock_sample_point_text(spec.sample_point))
            : ClockSamplingJson(nullptr)}
    };
}

ClockSamplingJson effective_sampling_json(
    const ClockSampleSpec& spec) {
    return {
        {"edge", clock_edge_kind_text(spec.edge)},
        {"sample_point", spec.edge == ClockEdgeKind::Negedge
            ? ClockSamplingJson(nullptr)
            : ClockSamplingJson(clock_sample_point_text(spec.sample_point))}
    };
}

void append_sample_point_resolution(
    const ClockSampleSpec& spec,
    ClockSamplingJson& output) {
    const bool applied = spec.edge != ClockEdgeKind::Negedge;
    const bool ignored =
        spec.edge == ClockEdgeKind::Negedge && spec.has_sample_point;
    output["sample_point_applied"] = applied;
    output["sample_point_ignored_for_negedge"] = ignored;
    if (ignored) {
        output["sample_point_not_applied_reason"] =
            kNegedgeSamplePointIgnoredReason;
    }
}

} // namespace

ClockSamplingJson clock_sampling_contract_json(
    const ClockSampleSpec& spec) {
    ClockSamplingJson output = {
        {"requested", requested_sampling_json(spec)},
        {"effective", effective_sampling_json(spec)}
    };
    append_sample_point_resolution(spec, output);
    return output;
}

ClockSamplingJson clock_point_context_json(
    npiFsdbFileHandle fsdb,
    const ClockSampleSpec& spec,
    const ClockPointContext& context) {
    const ClockSamplingJson sampling =
        clock_sampling_contract_json(spec);
    ClockSamplingJson output = {
        {"clock", spec.clock},
        {"requested_sampling", sampling["requested"]},
        {"effective_sampling", sampling["effective"]},
        {"sample_point_applied", sampling["sample_point_applied"]},
        {"sample_point_ignored_for_negedge",
         sampling["sample_point_ignored_for_negedge"]},
        {"requested_time",
         xdebug_core::format_time(fsdb, context.requested_time)},
        {"requested_any_edge_hit", context.clock_edge_hit},
        {"clock_edge_kind", context.has_clock_edge_kind
            ? ClockSamplingJson(clock_edge_kind_text(context.clock_edge_kind))
            : ClockSamplingJson(nullptr)},
        {"requested_target_edge_hit", context.target_edge_hit},
        {"previous_sample_time", context.has_previous_sample_time
            ? ClockSamplingJson(
                xdebug_core::format_time(fsdb, context.previous_sample_time))
            : ClockSamplingJson(nullptr)},
        {"next_sample_time", context.has_next_sample_time
            ? ClockSamplingJson(
                xdebug_core::format_time(fsdb, context.next_sample_time))
            : ClockSamplingJson(nullptr)},
        {"bracket_complete", context.bracket_complete}
    };
    if (sampling.contains("sample_point_not_applied_reason")) {
        output["sample_point_not_applied_reason"] =
            sampling["sample_point_not_applied_reason"];
    }
    return output;
}

} // namespace xdebug_waveform
