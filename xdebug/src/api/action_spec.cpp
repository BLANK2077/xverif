#include "api/action_spec.h"

#include <stdexcept>

namespace xdebug {

std::string to_string(ActionStatus status) {
    switch (status) {
    case ActionStatus::Experimental: return "experimental";
    case ActionStatus::Stable: return "stable";
    }
    throw std::invalid_argument("unknown ActionStatus value");
}

std::string to_string(ResourceRequirement resource) {
    switch (resource) {
    case ResourceRequirement::None: return "none";
    case ResourceRequirement::Design: return "design";
    case ResourceRequirement::Waveform: return "waveform";
    case ResourceRequirement::Combined: return "combined";
    case ResourceRequirement::Any: return "any";
    case ResourceRequirement::Session: return "session";
    }
    throw std::invalid_argument("unknown ResourceRequirement value");
}

ActionStatus action_status_from_string(const std::string& value) {
    if (value == "stable") return ActionStatus::Stable;
    if (value == "experimental") return ActionStatus::Experimental;
    throw std::invalid_argument("unknown action status: " + value);
}

ResourceRequirement resource_requirement_from_string(const std::string& value) {
    if (value == "design") return ResourceRequirement::Design;
    if (value == "waveform") return ResourceRequirement::Waveform;
    if (value == "combined") return ResourceRequirement::Combined;
    if (value == "any") return ResourceRequirement::Any;
    if (value == "session") return ResourceRequirement::Session;
    if (value == "none") return ResourceRequirement::None;
    throw std::invalid_argument("unknown resource requirement: " + value);
}

Json action_spec_descriptor(const ActionSpec& spec) {
    Json descriptor = {
        {"name", spec.name},
        {"category", spec.category},
        {"status", to_string(spec.status)},
        {"requires", to_string(spec.resource)},
        {"request_schema", spec.request_schema},
        {"response_schema", spec.response_schema},
        {"handler_kind", spec.handler_kind},
        {"request_examples", spec.request_examples},
        {"response_examples", spec.response_examples},
        {"required_args", spec.args.required},
        {"allowed_values", Json::object()},
        {"description_en", spec.description_en},
        {"description_zh", spec.description_zh},
        {"purposes", spec.purposes},
        {"use_when", spec.use_when},
        {"do_not_use_when", spec.do_not_use_when},
        {"alternatives", spec.alternatives}
    };
    descriptor["resource_variants"] = Json::array();
    for (const ResourceVariant& variant : spec.resource_variants) {
        descriptor["resource_variants"].push_back({
            {"name", variant.name},
            {"requires", to_string(variant.resource)},
            {"required_args", variant.required_args},
            {"forbidden_args", variant.forbidden_args}
        });
    }
    for (std::map<std::string, std::vector<std::string> >::const_iterator it = spec.args.allowed_values.begin();
         it != spec.args.allowed_values.end(); ++it) {
        descriptor["allowed_values"][it->first] = it->second;
    }
    return descriptor;
}

} // namespace xdebug
