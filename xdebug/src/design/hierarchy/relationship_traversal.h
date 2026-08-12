#pragma once

#include <cstddef>
#include <string>

namespace xdebug_design {

inline std::string relationship_child_path(const std::string& parent,
                                           const std::string& child) {
    return parent.empty() ? child : parent + "." + child;
}

inline int relationship_child_depth(int parent_depth) {
    return parent_depth + 1;
}

inline int relationship_side_depth(int parent_depth) {
    return parent_depth;
}

class RelationshipObjectBudget {
public:
    explicit RelationshipObjectBudget(std::size_t limit) : limit_(limit) {}

    bool consume() {
        if (visited_ >= limit_) return false;
        ++visited_;
        return true;
    }
    std::size_t visited() const { return visited_; }
    bool exhausted() const { return visited_ >= limit_; }

private:
    std::size_t limit_;
    std::size_t visited_ = 0;
};

}  // namespace xdebug_design
