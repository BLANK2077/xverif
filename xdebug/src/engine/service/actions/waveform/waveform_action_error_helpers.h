#pragma once

#include "service/engine_action_handler.h"

namespace xdebug_design {

inline Json waveform_action_example(const std::string& action) {
    Json args = Json::object();
    if (action == "verify.conditions") {
        args = {{"clock", "top.u.clk"},
                {"time", "10ns"},
                {"signals", {{"valid", "top.u.valid"}, {"ready", "top.u.ready"}}},
                {"conditions", Json::array({{{"expr", "valid && ready"}}})}};
    } else if (action == "window.verify") {
        args = {{"clock", "top.u.clk"},
                {"time_range", {{"begin", "0ns"}, {"end", "100ns"}}},
                {"signals", {{"valid", "top.u.valid"}, {"ready", "top.u.ready"}}},
                {"conditions", Json::array({{{"expr", "valid && ready"}, {"mode", "always"}}})}};
    } else if (action == "expr.eval_at") {
        args = {{"clock", "top.u.clk"},
                {"time", "10ns"},
                {"signals", {{"valid", "top.u.valid"}, {"ready", "top.u.ready"}}},
                {"expr", "valid && !ready"}};
    } else {
        args = {{"signal", "top.u.valid"}, {"time", "10ns"}, {"clock", "top.u.clk"}};
    }
    return Json{{"api_version", "xdebug.v1"},
                {"action", action},
                {"target", {{"session_id", "case_a"}}},
                {"args", args}};
}

inline Json waveform_missing_field_error(const std::string& action,
                                         const std::string& invalid_arg,
                                         const std::string& expected) {
    return make_handler_error(
        "MISSING_FIELD",
        invalid_arg + " is required",
        {{"invalid_arg", invalid_arg},
         {"expected", expected},
         {"correct_example", waveform_action_example(action)},
         {"example_note", "Example only; replace signal paths, clock, time, and session id with active case values."}});
}

inline Json waveform_invalid_arg_error(const std::string& action,
                                       const std::string& invalid_arg,
                                       const std::string& message,
                                       const std::string& expected) {
    return make_handler_error(
        "INVALID_ARGUMENT",
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", expected},
         {"correct_example", waveform_action_example(action)},
         {"example_note", "Example only; replace placeholders with active case values."}});
}

inline Json waveform_time_error(const std::string& action,
                                const std::string& invalid_arg,
                                const std::string& message) {
    return make_handler_error(
        "INVALID_TIME",
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", "time string with units, such as 10ns"},
         {"correct_example", waveform_action_example(action)}});
}

inline Json waveform_signal_not_found_error(const std::string& action,
                                            const std::string& signal) {
    return make_handler_error(
        "SIGNAL_NOT_FOUND",
        "signal not found: " + signal,
        {{"invalid_arg", "args.signal"},
         {"expected", "existing waveform signal path"},
         {"missing_name", signal},
         {"missing_resource", "signal"},
         {"correct_example", waveform_action_example(action)},
         {"next_actions", Json::array({"Use scope.list or signal.resolve to find the exact waveform signal path."})}});
}

inline Json waveform_expression_alias_error(const std::string& action,
                                            const std::string& invalid_arg,
                                            const std::string& message) {
    return make_handler_error(
        "INVALID_ARGUMENT",
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", "use aliases in expr and put real signal paths in args.signals"},
         {"example_note", "Example only; do not put top.u.sig style real paths directly inside expr."},
         {"correct_example", waveform_action_example(action)}});
}

} // namespace xdebug_design
