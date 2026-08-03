#pragma once

#include <cstddef>

#include "json.hpp"

namespace xdebug_engine {

constexpr std::size_t kMaxSessionJsonResponseBytes =
    64U * 1024U * 1024U;

bool read_bounded_json_line(
    int fd,
    nlohmann::json& response,
    std::size_t max_bytes = kMaxSessionJsonResponseBytes);

}  // namespace xdebug_engine
