#include "api/action_registry.h"

namespace xdebug {

bool ActionRegistry::register_spec(const ActionSpec& spec) {
    if (spec.name.empty()) return false;
    return specs_.insert(std::make_pair(spec.name, spec)).second;
}

bool ActionRegistry::register_handler(std::unique_ptr<ActionHandler> handler) {
    if (!handler || handler->name().empty()) return false;
    const std::string name = handler->name();
    return handlers_.insert(std::make_pair(name, std::move(handler))).second;
}

const ActionSpec* ActionRegistry::find_spec(const std::string& name) const {
    std::map<std::string, ActionSpec>::const_iterator it = specs_.find(name);
    return it == specs_.end() ? nullptr : &it->second;
}

ActionHandler* ActionRegistry::find_handler(const std::string& name) const {
    std::map<std::string, std::unique_ptr<ActionHandler> >::const_iterator it = handlers_.find(name);
    return it == handlers_.end() ? nullptr : it->second.get();
}

std::vector<ActionSpec> ActionRegistry::list_specs() const {
    std::vector<ActionSpec> specs;
    for (std::map<std::string, ActionSpec>::const_iterator it = specs_.begin(); it != specs_.end(); ++it) {
        specs.push_back(it->second);
    }
    return specs;
}

Json ActionRegistry::list_descriptors() const {
    Json out = Json::array();
    std::vector<ActionSpec> specs = list_specs();
    for (size_t i = 0; i < specs.size(); ++i) out.push_back(action_spec_descriptor(specs[i]));
    return out;
}

} // namespace xdebug
