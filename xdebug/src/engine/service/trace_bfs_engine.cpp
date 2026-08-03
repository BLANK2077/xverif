#include "trace_bfs_engine.h"
#include "design_postprocess.h"

namespace xdebug_design {
namespace detail {

namespace {

json normalize_trace_error(const json& trace) {
    json error = trace.value("error", json());
    if (error.is_object()) {
        if (!error.contains("code")) error["code"] = "TRACE_QUERY_FAILED";
        if (!error.contains("message")) error["message"] = "trace query failed during expansion";
        if (!error.contains("recoverable")) error["recoverable"] = true;
        return error;
    }

    std::string message = error.is_string()
        ? error.get<std::string>()
        : trace.value("message", std::string("trace query failed during expansion"));
    std::string code = message.find("Signal not found") != std::string::npos
        ? "SIGNAL_NOT_FOUND"
        : "TRACE_QUERY_FAILED";
    return {
        {"code", code},
        {"message", message},
        {"recoverable", true}
    };
}

}  // namespace

BfsResult run_trace_bfs(const BfsOptions& opts, const SingleTraceFn& trace_fn) {
    BfsResult result;
    std::set<std::string> visited;
    std::set<std::string> seen_edges;
    std::vector<std::pair<std::string, int>> queue = {{opts.root, 0}};

    for (size_t qi = 0; qi < queue.size(); ++qi) {
        std::string current = queue[qi].first;
        int depth = queue[qi].second;
        result.reached_depth = std::max(result.reached_depth, depth);

        if (visited.count(current)) continue;
        if ((int)visited.size() >= opts.max_nodes) {
            result.truncated = true;
            break;
        }
        visited.insert(current);
        if (depth >= opts.max_depth) continue;

        // Call trace function for this signal
        json trace = trace_fn(current);
        if (trace.empty() || trace.contains("error")) {
            result.failed_query_count++;
            if (depth == 0) {
                // Root trace failed — cannot continue
                result.root_error = normalize_trace_error(trace);
                result.warnings.push_back(
                    compact_trace_error_warning(current, depth, trace).dump());
                break;
            }
            result.warnings.push_back(compact_trace_error_warning(current, depth, trace).dump());
            continue;
        }

        if (result.first_confidence == "unknown")
            result.first_confidence = trace.value("confidence", "unknown");

        json trace_edges = trace.value("dependency_edges", json::array());
        const bool trace_analysis_complete =
            trace.at("analysis_complete").get<bool>();
        result.expanded_queries.push_back({
            {"query", current}, {"depth", depth},
            {"edge_count", trace_edges.size()},
            {"analysis_complete", trace_analysis_complete},
            {"confidence", trace.value("confidence", "unknown")}
        });

        if (!trace_analysis_complete) result.truncated = true;

        for (const auto& e : trace_edges) {
            if (!edge_type_allowed(opts.edge_type_filter, e)) continue;
            if ((int)result.all_edges.size() >= opts.max_edges) {
                result.truncated = true;
                break;
            }
            result.raw_edge_count++;
            if (!seen_edges.insert(edge_dedupe_key(e)).second) {
                result.duplicate_edge_count++;
                continue;
            }
            result.all_edges.push_back(e);

            std::string next = opts.direction == "load"
                ? e.value("to", "")
                : e.value("from", "");
            if (!next.empty() && !visited.count(next) && (int)queue.size() < opts.max_nodes)
                queue.push_back({next, depth + 1});
            else if ((int)queue.size() >= opts.max_nodes)
                result.truncated = true;
        }
        if ((int)result.all_edges.size() >= opts.max_edges) {
            result.truncated = true;
            break;
        }
    }

    return result;
}

}  // namespace detail
}  // namespace xdebug_design
