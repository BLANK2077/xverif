#pragma once

#include "api/action_handler.h"
#include "api/action_spec.h"

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace xdebug {

class ActionRegistry {
public:
    bool register_spec(const ActionSpec& spec);
    bool register_handler(std::unique_ptr<ActionHandler> handler);

    const ActionSpec* find_spec(const std::string& name) const;
    ActionHandler* find_handler(const std::string& name) const;

    std::vector<ActionSpec> list_specs() const;
    Json list_descriptors() const;

private:
    std::map<std::string, ActionSpec> specs_;
    std::map<std::string, std::unique_ptr<ActionHandler> > handlers_;
};

} // namespace xdebug
