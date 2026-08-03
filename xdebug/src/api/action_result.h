#pragma once

#include "api/json_types.h"

namespace xdebug {

struct ActionResult {
    bool ok = true;
    Json envelope = nullptr;
    Json summary = Json::object();
    Json data = Json::object();
    Json warnings = Json::array();
    Json error = nullptr;
};

} // namespace xdebug
