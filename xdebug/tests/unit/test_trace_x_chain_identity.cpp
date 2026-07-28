#include "combined/trace_x_chain_identity.h"

#include <cassert>
#include <set>
#include <string>
#include <vector>

using xdebug::TraceXSemanticHop;

namespace {

std::vector<TraceXSemanticHop> alias_variant(
    const std::string& final_signal,
    const std::string& final_relation,
    int variant) {
    std::vector<TraceXSemanticHop> hops;
    hops.push_back(TraceXSemanticHop("top.out", "10ns", "root"));
    if (variant & 1) {
        hops.push_back(TraceXSemanticHop(
            "top.u_sink.out", "10ns", "port"));
    }
    hops.push_back(TraceXSemanticHop("top.mid", "10ns", "rhs"));
    if (variant & 2) {
        hops.push_back(TraceXSemanticHop(
            "top.bus.data", "10ns", "port"));
    }
    if (variant & 4) {
        hops.push_back(TraceXSemanticHop(
            "top.u_source.bus.data", "10ns", "port"));
    }
    hops.push_back(TraceXSemanticHop(final_signal, "5ns", final_relation));
    return hops;
}

} // namespace

int main() {
    assert(xdebug::trace_x_is_transparent_relation("port"));
    assert(!xdebug::trace_x_is_transparent_relation("rhs"));
    assert(!xdebug::trace_x_is_transparent_relation("control"));
    assert(!xdebug::trace_x_is_transparent_relation("port+rhs"));
    assert(xdebug::trace_x_semantic_relation("port").empty());
    assert(xdebug::trace_x_semantic_relation("port+rhs") == "rhs");
    assert(xdebug::trace_x_semantic_relation("control+port+rhs") ==
           "control+rhs");

    std::set<std::string> effective_keys;
    for (int variant = 0; variant < 6; ++variant) {
        effective_keys.insert(xdebug::trace_x_semantic_chain_key(
            alias_variant("top.source_a", "rhs", variant)));
        effective_keys.insert(xdebug::trace_x_semantic_chain_key(
            alias_variant("top.source_b", "control", variant)));
    }
    assert(effective_keys.size() == 2);

    const auto direct = alias_variant("top.source_a", "rhs", 0);
    const auto through_module_and_modport =
        alias_variant("top.source_a", "rhs", 7);
    assert(xdebug::trace_x_semantic_chain_key(direct) ==
           xdebug::trace_x_semantic_chain_key(through_module_and_modport));
    assert(xdebug::trace_x_common_semantic_prefix(
               direct, through_module_and_modport) == direct.size());

    const auto different_rhs = alias_variant("top.source_b", "rhs", 0);
    const auto different_relation = alias_variant("top.source_a", "control", 0);
    assert(xdebug::trace_x_semantic_chain_key(direct) !=
           xdebug::trace_x_semantic_chain_key(different_rhs));
    assert(xdebug::trace_x_semantic_chain_key(direct) !=
           xdebug::trace_x_semantic_chain_key(different_relation));
    auto composite_relation = direct;
    composite_relation.back().relation = "port+rhs";
    assert(xdebug::trace_x_semantic_chain_key(direct) ==
           xdebug::trace_x_semantic_chain_key(composite_relation));

    std::vector<TraceXSemanticHop> root{
        TraceXSemanticHop("top.out", "10ns", "root")};
    assert(xdebug::trace_x_exploration_state_key(
               root, "top.u0.bus.data", "10ns") !=
           xdebug::trace_x_exploration_state_key(
               root, "top.u1.bus.data", "10ns"));

    root.push_back(TraceXSemanticHop("top.source_a", "5ns", "rhs"));
    const std::string converged = xdebug::trace_x_exploration_state_key(
        root, "top.source_a", "5ns");
    assert(converged == xdebug::trace_x_exploration_state_key(
                            root, "top.source_a", "5ns"));
    return 0;
}
