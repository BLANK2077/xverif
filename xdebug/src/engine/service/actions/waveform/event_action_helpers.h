#pragma once

#include "service/engine_action_handler.h"

namespace xdebug_design {

inline Json event_action_example(const std::string& action) {
    return Json{{"api_version", "xdebug.v1"},
                {"action", action},
                {"target", {{"session_id", "case_a"}}},
                {"args", {{"clock", "top.clk"},
                          {"signals", {{"valid", "top.u.valid"}, {"ready", "top.u.ready"}}},
                          {"expr", "valid && ready"},
                          {"time_range", {{"begin", "0ns"}, {"end", "100ns"}}}}}};
}

inline Json event_config_example(const std::string& action) {
    Json example = event_action_example(action);
    example["args"] = {{"name", "fire_event"}, {"expr", "valid && ready"}};
    return example;
}

inline Json event_config_not_found_error(const std::string& action,
                                         const std::string& name) {
    return make_handler_error(
        "CONFIG_NOT_FOUND",
        "event config not found: " + name,
        {{"invalid_arg", "args.name"},
         {"expected", "name of a previously loaded event config"},
         {"missing_name", name},
         {"missing_resource", "event config"},
         {"correct_example", event_config_example(action)},
         {"example_note", "Example only; omit args.name and provide inline clock/signals/expr, or load the named config first."},
         {"next_actions", Json::array({"Call event.config.list to inspect loaded event configs.",
                                        "Call event.config.load before using a named event config."})}});
}

inline Json event_missing_field_error(const std::string& action,
                                      const std::string& invalid_arg,
                                      const std::string& expected) {
    return make_handler_error(
        "MISSING_FIELD",
        invalid_arg + " is required",
        {{"invalid_arg", invalid_arg},
         {"expected", expected},
         {"correct_example", event_action_example(action)},
         {"example_note", "Example only; event expressions use aliases, with real signal paths only in args.signals."}});
}

inline Json event_invalid_arg_error(const std::string& action,
                                    const std::string& invalid_arg,
                                    const std::string& message,
                                    const std::string& expected,
                                    const Json& available_values = Json()) {
    Json details = {{"invalid_arg", invalid_arg},
                    {"expected", expected},
                    {"correct_example", event_action_example(action)},
                    {"example_note", "Example only; replace placeholder values with the active event query."}};
    if (!available_values.is_null()) {
        details["available_values"] = available_values;
    }
    return make_handler_error("INVALID_ARGUMENT", message, details);
}

inline Json event_invalid_enum_error(const std::string& action,
                                     const std::string& invalid_arg,
                                     const std::string& message,
                                     const Json& available_values) {
    return make_handler_error(
        "INVALID_ENUM",
        message,
        {{"invalid_arg", invalid_arg},
         {"expected", "one of available_values"},
         {"available_values", available_values},
         {"correct_example", event_action_example(action)},
         {"example_note", "Example only; choose a value from available_values."}});
}

inline Json event_time_error(const std::string& action,
                             const std::string& message) {
    return make_handler_error(
        "INVALID_TIME",
        message,
        {{"invalid_arg", "args.time_range"},
         {"expected", "time_range.begin/end strings such as 0ns and 100ns"},
         {"correct_example", event_action_example(action)}});
}

inline Json event_expression_alias_error(const std::string& action,
                                         const std::string& message) {
    return make_handler_error(
        "INVALID_ARGUMENT",
        message,
        {{"invalid_arg", "args.expr"},
         {"expected", "use aliases in expr and put real signal paths in args.signals"},
         {"example_note", "Example only; do not put top.u.sig style real paths directly inside expr."},
         {"correct_example", event_action_example(action)}});
}

} // namespace xdebug_design
