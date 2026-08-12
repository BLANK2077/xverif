#pragma once

#include "service/action_resource_scope.h"

#include <cstddef>
#include <string>
#include <vector>

namespace xdebug_design {

struct DesignRelationshipItem {
    std::string kind;
    std::string name;
    std::string path;
    std::string module_name;
    std::string direction;
    std::string array_path;
};

struct DesignRelationshipWalkResult {
    std::vector<DesignRelationshipItem> items;
    std::size_t visited_count = 0;
    bool budget_exhausted = false;
    bool root_found = false;
};

// The hierarchy depth limit and visited-object budget are intentionally
// independent: side relationships such as modport -> mpport consume budget,
// but do not consume hierarchy depth.
DesignRelationshipWalkResult walk_design_relationships(
    const std::string& root_path, int level, std::size_t object_budget,
    ActionResourceScope& resources);

}  // namespace xdebug_design
