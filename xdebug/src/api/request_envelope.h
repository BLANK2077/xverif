#pragma once

#include "api/json_types.h"

#include <string>

namespace xdebug {

struct RequestEnvelope {
    std::string api_version;
    std::string request_id;
    std::string action;
    Json target = Json::object();
    Json args = Json::object();
    Json limits = Json::object();
    Json raw = Json::object();

    static RequestEnvelope from_json(const Json& request);
};

} // namespace xdebug
