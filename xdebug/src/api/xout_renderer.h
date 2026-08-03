#pragma once

#include "api/json_types.h"

#include <string>

namespace xdebug {

std::string render_xout_response(const Json& response);
std::string render_xout_response(const Json& response,
                                 const std::string& handler_xout);
std::string render_xout_transport_payload(const Json& response);
std::string render_xout_transport_payload(const Json& response,
                                          const std::string& handler_xout);

} // namespace xdebug
