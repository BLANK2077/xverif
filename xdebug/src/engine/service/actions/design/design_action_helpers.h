#pragma once

#include "service/engine_action_handler.h"
#include "design/signal/signal_finder.h"

namespace xdebug_design {

inline Json design_action_example(const std::string& action) {
    Json args = {{"signal", "top.u.valid"}};
    if (action == "trace.driver" || action == "trace.load") {
        args["line_limit"] = 16;
    }
    return Json{{"api_version", "xdebug.v1"},
                {"action", action},
                {"target", {{"session_id", "case_a"}}},
                {"args", args}};
}

inline Json design_missing_signal_error(const std::string& action) {
    return make_handler_error(
        "MISSING_FIELD",
        "args.signal is required",
        {{"invalid_arg", "args.signal"},
         {"expected", "design signal path or signal name accepted by the design database"},
         {"correct_example", design_action_example(action)},
         {"example_note", "Example only; replace target.session_id and args.signal with active design values."},
         {"next_actions", Json::array({"Use scope/list style discovery or signal.resolve to identify the signal path."})}});
}

inline Json design_signal_not_found_error(const std::string& action,
                                          const std::string& signal) {
    return make_handler_error(
        "SIGNAL_NOT_FOUND",
        "design signal not found: " + signal,
        {{"invalid_arg", "args.signal"},
         {"missing_name", signal},
         {"missing_resource", "design signal"},
         {"expected", "existing design signal path"},
         {"correct_example", design_action_example(action)},
         {"example_note", "Example only; replace target.session_id and args.signal with active design values."},
         {"next_actions", Json::array({"Call signal.resolve with a known design path.",
                                        "Use scope discovery to find the exact signal path."})}});
}

inline bool resolve_design_signal(const std::string& action,
                                  const std::string& signal,
                                  SignalResolveResult& result,
                                  Json& failure) {
    SignalFinder finder;
    result = finder.resolve(signal);
    if (result.ok && !result.matches.empty()) return true;
    failure = design_signal_not_found_error(action, signal);
    return false;
}

} // namespace xdebug_design
