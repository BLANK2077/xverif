#pragma once

#include <cstddef>

#include "json.hpp"
#include "session/transport_common.h"

namespace xdebug_engine {

constexpr std::size_t kMaxSessionJsonResponseBytes =
    xdebug_core::kMaxSessionJsonBytes;

enum class JsonLineReadStatus {
    Ok,
    EndOfFile,
    Timeout,
    TooLarge,
    IoError,
    InvalidJson,
};

JsonLineReadStatus read_bounded_json_line_status(
    int fd,
    nlohmann::json& response,
    std::size_t max_bytes = kMaxSessionJsonResponseBytes,
    const xdebug_core::TransportDeadline& deadline =
        xdebug_core::TransportDeadline());

bool read_bounded_json_line(
    int fd,
    nlohmann::json& response,
    std::size_t max_bytes = kMaxSessionJsonResponseBytes);

}  // namespace xdebug_engine
