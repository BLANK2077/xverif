#include "design/hierarchy/relationship_traversal.h"

#include <cassert>

using namespace xdebug_design;

int main() {
    assert(relationship_child_path("top.links[0]", "producer") ==
           "top.links[0].producer");
    assert(relationship_child_path("", "top") == "top");
    assert(relationship_child_depth(1) == 2);
    assert(relationship_side_depth(1) == 1);

    RelationshipObjectBudget budget(2);
    assert(budget.consume());
    assert(budget.consume());
    assert(!budget.consume());
    assert(budget.visited() == 2);
    assert(budget.exhausted());
    return 0;
}
