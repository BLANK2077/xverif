#pragma once

#include "service/engine_action_handler.h"

namespace xdebug_design {

inline Json list_action_example(const std::string& action) {
    Json args = Json::object();
    if (action == "list.create") {
        args = {{"name", "debug_list"},
                {"signals", Json::array({"top.u.valid", "top.u.ready"})}};
    } else if (action == "list.add") {
        args = {{"name", "debug_list"}, {"signal", "top.u.valid"}};
    } else if (action == "list.delete") {
        args = {{"name", "debug_list"}, {"index", 1}};
    } else if (action == "list.first_change" || action == "list.export") {
        args = {{"name", "debug_list"},
                {"time_range", {{"begin", "0ns"}, {"end", "500ns"}}}};
        if (action == "list.export") {
            args["output"] = {{"path", "xdebug-list-export"}, {"file_format", "u64bin"}};
        }
    } else {
        args = {{"name", "debug_list"}};
    }
    return Json{{"api_version", "xdebug.v1"},
                {"action", action},
                {"target", {{"session_id", "case_a"}}},
                {"args", args}};
}

inline Json list_missing_field_error(const std::string& action,
                                     const std::string& invalid_arg,
                                     const std::string& expected) {
    return make_handler_error(
        "MISSING_FIELD",
        invalid_arg + " is required",
        {{"invalid_arg", invalid_arg},
         {"expected", expected},
         {"correct_example", list_action_example(action)},
         {"example_note", "Example only; replace target.session_id, list name, signal paths, and time values with the active case values."}});
}

inline Json list_not_found_error(const std::string& action, const std::string& name) {
    return make_handler_error(
        "LIST_NOT_FOUND",
        "list not found: " + name,
        {{"invalid_arg", "args.name"},
         {"expected", "name of a list created in this session"},
         {"missing_name", name},
         {"missing_resource", "signal list"},
         {"correct_example", list_action_example(action)},
         {"example_note", "Example only; create or choose an existing list name before calling this action."},
         {"next_actions", Json::array({"Call list.create to create the list.",
                                        "Call list.show with an existing name to inspect list contents."})}});
}

inline Json list_signal_not_found_error(const std::string& action, const std::string& signal) {
    return make_handler_error(
        "SIGNAL_NOT_FOUND",
        "signal not found: " + signal,
        {{"invalid_arg", "args.signal"},
         {"expected", "existing waveform signal path"},
         {"missing_name", signal},
         {"missing_resource", "signal"},
         {"correct_example", list_action_example(action)},
         {"example_note", "Example only; replace args.signal with a signal path that exists in the active FSDB."},
         {"next_actions", Json::array({"Use signal.resolve or scope.list to find the exact signal path."})}});
}

inline Json list_invalid_arg_error(const std::string& action,
                                   const std::string& invalid_arg,
                                   const std::string& expected,
                                   const Json& received = Json()) {
    Json details = {{"invalid_arg", invalid_arg},
                    {"expected", expected},
                    {"correct_example", list_action_example(action)},
                    {"example_note", "Example only; replace placeholder values with active case values."}};
    if (!received.is_null()) details["received"] = received;
    return make_handler_error("INVALID_ARGUMENT", invalid_arg + " is invalid", details);
}

} // namespace xdebug_design
