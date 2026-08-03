#pragma once

#include "api/json_types.h"

#include <string>

namespace xdebug {

static const char* const kApiVersion = "xdebug.v1";
static const char* const kToolVersion = "0.1.0";

Json tool_metadata();

Json make_response(const Json& request, const std::string& action, bool ok = true);
Json make_error(const Json& request,
                const std::string& action,
                const std::string& code,
                const std::string& message,
                bool recoverable = true);
Json make_error(const Json& request,
                const std::string& action,
                const Json& error);
Json normalize_engine_response(const Json& response);

} // namespace xdebug
