#pragma once

#include "json.hpp"

#include <cstddef>
#include <string>
#include <vector>

namespace xdebug_core {

template <typename Json>
inline void set_completeness(Json& summary,
                             bool scan_complete,
                             bool analysis_complete,
                             bool response_truncated,
                             std::size_t total_count,
                             std::size_t returned_count,
                             const std::vector<std::string>& truncation_scopes) {
    if (!summary.is_object()) summary = Json::object();
    summary["scan_complete"] = scan_complete;
    summary["analysis_complete"] = analysis_complete;
    summary["response_truncated"] = response_truncated;
    summary["total_count"] = total_count;
    summary["returned_count"] = returned_count;
    summary["truncation_scopes"] = truncation_scopes;
}

} // namespace xdebug_core
