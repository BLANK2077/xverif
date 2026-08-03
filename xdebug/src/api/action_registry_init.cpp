#include "api/action_registry_init.h"

namespace xdebug {

namespace {

ActionRegistry* build_registry() {
    ActionRegistry* registry_ptr = new ActionRegistry();
    ActionRegistry& registry = *registry_ptr;
#include "api/generated_action_metadata.inc"
    return registry_ptr;
}

} // namespace

const ActionRegistry& default_action_registry() {
    static ActionRegistry* registry = build_registry();
    return *registry;
}

} // namespace xdebug
