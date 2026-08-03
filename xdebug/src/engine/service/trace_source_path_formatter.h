#pragma once

#include "json.hpp"

#include "npi_hdl.h"

#include <string>
#include <vector>

namespace xdebug_design {

using Json = nlohmann::ordered_json;
class ContractBoundRequest;

Json source_window_from_location(const std::string& file, int line, int context_lines = -1);
Json source_window_from_npi_handle(npiHandle handle, int context_lines = -1);
Json make_source_path_item_from_location(const std::string& file,
                                         int line,
                                         const std::vector<std::string>& signal_path,
                                         int context_lines = -1);
Json make_source_path_item_from_npi_handle(npiHandle handle,
                                           const std::vector<std::string>& signal_path,
                                           int context_lines = -1);

int trace_result_limit_from_request(const Json& request);
int trace_result_limit_from_request(ContractBoundRequest& request);

Json simplify_trace_driver_load_payload(const Json& raw,
                                        const std::string& action,
                                        const std::string& signal,
                                        const std::string& mode,
                                        int max_results = -1);
Json simplify_active_driver_payload(const Json& raw,
                                    const std::string& signal,
                                    const std::string& requested_time,
                                    int max_results = -1);
Json simplify_active_driver_chain_payload(const Json& raw,
                                          const std::string& signal,
                                          const std::string& start_time,
                                          int max_results = -1);

std::string render_source_path_xout(const std::string& action, const Json& response);

} // namespace xdebug_design
