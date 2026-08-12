#pragma once

#include <algorithm>
#include <chrono>
#include <stdexcept>

namespace xdebug_core {

// Cooperative request deadlines are intentionally process-local.  They do
// not attempt to cancel a vendor NPI call: actions may checkpoint between
// bounded units of work, while a caller that cannot regain control must stop
// the engine process from outside the NPI context.
class RequestDeadlineExceeded : public std::runtime_error {
public:
    RequestDeadlineExceeded()
        : std::runtime_error(
              "internal engine request exceeded limits.timeout_ms") {}
};

struct RequestDeadlineState {
    bool active = false;
    std::chrono::steady_clock::time_point expires_at;
};

inline RequestDeadlineState& current_request_deadline_state() {
    static thread_local RequestDeadlineState state;
    return state;
}

class ScopedRequestDeadline {
public:
    explicit ScopedRequestDeadline(int timeout_ms)
        : previous_(current_request_deadline_state()) {
        RequestDeadlineState next;
        if (timeout_ms > 0) {
            next.active = true;
            next.expires_at =
                std::chrono::steady_clock::now() +
                std::chrono::milliseconds(timeout_ms);
            if (previous_.active) {
                next.expires_at =
                    std::min(next.expires_at, previous_.expires_at);
            }
        } else if (previous_.active) {
            next = previous_;
        }
        current_request_deadline_state() = next;
    }

    explicit ScopedRequestDeadline(
        const std::chrono::steady_clock::time_point& expires_at)
        : previous_(current_request_deadline_state()) {
        RequestDeadlineState next;
        next.active = true;
        next.expires_at = previous_.active
                              ? std::min(expires_at, previous_.expires_at)
                              : expires_at;
        current_request_deadline_state() = next;
    }

    ~ScopedRequestDeadline() {
        current_request_deadline_state() = previous_;
    }

    ScopedRequestDeadline(const ScopedRequestDeadline&) = delete;
    ScopedRequestDeadline& operator=(const ScopedRequestDeadline&) = delete;

private:
    RequestDeadlineState previous_;
};

inline bool request_deadline_expired() {
    const RequestDeadlineState& state =
        current_request_deadline_state();
    return state.active &&
           std::chrono::steady_clock::now() >= state.expires_at;
}

inline void request_deadline_checkpoint() {
    if (request_deadline_expired()) {
        throw RequestDeadlineExceeded();
    }
}

}  // namespace xdebug_core
