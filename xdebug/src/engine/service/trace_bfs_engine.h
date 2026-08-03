#pragma once

// Shared BFS trace expansion engine.
// Pure computation — no I/O, no NPI, no socket.
// Takes a trace callback that is called for each signal in the BFS queue.

#include "../../design/service/action_support.h"

#include <functional>
#include <set>
#include <string>
#include <vector>

namespace xdebug_design {
namespace detail {

struct BfsOptions {
    std::string root;
    std::string direction;  // "driver" | "load"
    int max_depth = 1;
    int max_nodes = 100;
    int max_edges = 200;
    json edge_type_filter;  // args for edge_type_allowed (dependency_types, etc.)
};

struct BfsResult {
    json all_edges;            // raw edges (unaggregated)
    json expanded_queries;     // per-node query metadata
    json root_error;           // normalized root-query error, when expansion cannot start
    bool truncated = false;
    int reached_depth = 0;
    int raw_edge_count = 0;
    int duplicate_edge_count = 0;
    int failed_query_count = 0;
    std::string first_confidence = "unknown";
    std::vector<std::string> warnings;
};

// Callback: signal name → enriched trace JSON.
// The returned json should contain: dependency_edges[], confidence,
// analysis_complete.
// On failure, return json with "error" key or empty object.
using SingleTraceFn = std::function<json(const std::string& signal)>;

// Run BFS trace expansion.
// Returns raw results (edges, queries, stats).  Callers apply
// aggregate_edges_by_relation / graph_from_trace / explanation_from_edge
// as needed.
BfsResult run_trace_bfs(const BfsOptions& opts, const SingleTraceFn& trace_fn);

}  // namespace detail
}  // namespace xdebug_design
