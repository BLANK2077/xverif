#pragma once

#include "common/env_config.h"
#include "json.hpp"

#include <limits>
#include <stdexcept>

namespace xdebug_core {

// Centralized timeout configuration for session transport.
// Both design and waveform engines share the same env vars and defaults.

inline int file_transport_request_timeout_ms() {
    return xdebug_file_transport_timeout_ms();
}

inline int file_transport_ping_timeout_ms() {
    return xdebug_file_transport_ping_timeout_ms();
}

struct TransportTimeoutOverrideMs {
    bool present;
    int value_ms;

    TransportTimeoutOverrideMs() : present(false), value_ms(0) {}

    explicit TransportTimeoutOverrideMs(int value)
        : present(true), value_ms(value) {
        if (value <= 0) {
            throw std::invalid_argument(
                "public timeout override must be positive");
        }
    }
};

// A public request timeout is an override, not a transport default.  Public
// schema validation already requires a positive integer; keep this parser
// fail-closed so an invalid internal envelope cannot be reinterpreted as
// "timeout omitted".
inline TransportTimeoutOverrideMs public_request_timeout_override_ms(
    const nlohmann::json& request) {
    if (!request.is_object()) {
        throw std::invalid_argument("request must be an object");
    }
    const auto limits_it = request.find("limits");
    if (limits_it == request.end()) return TransportTimeoutOverrideMs();
    if (!limits_it->is_object()) {
        throw std::invalid_argument("limits must be an object");
    }
    const auto timeout_it = limits_it->find("timeout_ms");
    if (timeout_it == limits_it->end()) return TransportTimeoutOverrideMs();
    if (!timeout_it->is_number_integer()) {
        throw std::invalid_argument(
            "limits.timeout_ms must be a positive integer");
    }
    const long long timeout_ms = timeout_it->get<long long>();
    if (timeout_ms <= 0 ||
        timeout_ms > std::numeric_limits<int>::max()) {
        throw std::invalid_argument(
            "limits.timeout_ms must be a positive 32-bit integer");
    }
    return TransportTimeoutOverrideMs(static_cast<int>(timeout_ms));
}

inline int effective_file_transport_request_timeout_ms(
    const TransportTimeoutOverrideMs& timeout_override_ms) {
    return timeout_override_ms.present
               ? timeout_override_ms.value_ms
               : file_transport_request_timeout_ms();
}

} // namespace xdebug_core
