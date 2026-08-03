#ifndef XDEBUG_COMBINED_TRACE_X_ORIGIN_CHAIN_IDENTITY_H
#define XDEBUG_COMBINED_TRACE_X_ORIGIN_CHAIN_IDENTITY_H

#include <cstddef>
#include <string>
#include <vector>

namespace xdebug {

struct TraceXOriginSemanticHop {
    std::string signal;
    std::string x_onset_time;
    std::string relation;
    std::string sample_time;

    TraceXOriginSemanticHop() = default;
    TraceXOriginSemanticHop(const std::string& signal_value,
                            const std::string& onset_value,
                            const std::string& relation_value,
                            const std::string& sample_value = std::string())
        : signal(signal_value),
          x_onset_time(onset_value),
          relation(relation_value),
          sample_time(sample_value) {}
};

inline bool trace_x_origin_is_transparent_relation(const std::string& relation) {
    return relation == "port";
}

inline std::string trace_x_origin_semantic_relation(const std::string& relation) {
    std::string semantic;
    std::size_t begin = 0;
    while (begin <= relation.size()) {
        const std::size_t end = relation.find('+', begin);
        const std::string token = relation.substr(
            begin, end == std::string::npos ? std::string::npos : end - begin);
        if (!token.empty() && token != "port") {
            if (!semantic.empty()) semantic += "+";
            semantic += token;
        }
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    return semantic;
}

inline void trace_x_origin_append_identity_field(std::string& key,
                                                 const std::string& value) {
    key += std::to_string(value.size());
    key += ":";
    key += value;
}

inline std::string trace_x_origin_semantic_chain_key(
    const std::vector<TraceXOriginSemanticHop>& hops) {
    std::string key;
    for (const auto& hop : hops) {
        const std::string relation =
            trace_x_origin_semantic_relation(hop.relation);
        if (relation.empty()) continue;
        trace_x_origin_append_identity_field(key, relation);
        trace_x_origin_append_identity_field(key, hop.signal);
        trace_x_origin_append_identity_field(key, hop.x_onset_time);
    }
    return key;
}

inline std::string trace_x_origin_exploration_state_key(
    const std::vector<TraceXOriginSemanticHop>& semantic_hops,
    const std::string& current_signal,
    const std::string& current_x_onset_time) {
    std::string key = trace_x_origin_semantic_chain_key(semantic_hops);
    trace_x_origin_append_identity_field(key, current_signal);
    trace_x_origin_append_identity_field(key, current_x_onset_time);
    return key;
}

inline std::size_t trace_x_origin_common_semantic_prefix(
    const std::vector<TraceXOriginSemanticHop>& lhs,
    const std::vector<TraceXOriginSemanticHop>& rhs) {
    std::size_t lhs_index = 0;
    std::size_t rhs_index = 0;
    std::size_t common = 0;
    while (true) {
        while (lhs_index < lhs.size() &&
               trace_x_origin_semantic_relation(
                   lhs[lhs_index].relation).empty()) {
            ++lhs_index;
        }
        while (rhs_index < rhs.size() &&
               trace_x_origin_semantic_relation(
                   rhs[rhs_index].relation).empty()) {
            ++rhs_index;
        }
        if (lhs_index >= lhs.size() || rhs_index >= rhs.size()) break;
        const std::string lhs_relation =
            trace_x_origin_semantic_relation(lhs[lhs_index].relation);
        const std::string rhs_relation =
            trace_x_origin_semantic_relation(rhs[rhs_index].relation);
        if (lhs[lhs_index].signal != rhs[rhs_index].signal ||
            lhs[lhs_index].x_onset_time != rhs[rhs_index].x_onset_time ||
            lhs_relation != rhs_relation) {
            break;
        }
        ++common;
        ++lhs_index;
        ++rhs_index;
    }
    return common;
}

} // namespace xdebug

#endif
