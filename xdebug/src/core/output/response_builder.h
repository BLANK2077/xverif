#pragma once

#include "json.hpp"

#include <string>
#include <vector>

namespace xdebug_core {

// Builder for standard xdebug action responses.
// Provides a consistent way to build response JSON across actions.
//
// Usage:
//   ResponseBuilder rb(req, action, elapsed_ms);
//   rb.ok().session(info).data(payload).summary({{"key", val}}).warning("...");
//   print_json(rb.build());
class ResponseBuilder {
public:
    ResponseBuilder(const nlohmann::json& req, const std::string& action,
                    long long elapsed_ms)
        : req_(req), action_(action), elapsed_ms_(elapsed_ms) {
        out_["ok"] = true;
        out_["action"] = action_;
        out_["elapsed_ms"] = elapsed_ms_;
    }

    // Mark response as successful (default)
    ResponseBuilder& ok() {
        out_["ok"] = true;
        return *this;
    }

    // Mark response as failed with error info
    ResponseBuilder& error(const std::string& code, const std::string& message,
                           bool recoverable = true) {
        out_["ok"] = false;
        out_["error"] = {{"code", code}, {"message", message},
                         {"recoverable", recoverable}};
        return *this;
    }

    // Fill session metadata into response (session_id, fsdb, daidir, etc.)
    ResponseBuilder& session(const nlohmann::json& session_info) {
        out_["session"] = session_info;
        return *this;
    }

    // Set the data payload
    ResponseBuilder& data(const nlohmann::json& payload) {
        out_["data"] = payload;
        return *this;
    }

    // Set the summary
    ResponseBuilder& summary(const nlohmann::json& s) {
        out_["summary"] = s;
        return *this;
    }

    // Add a warning
    ResponseBuilder& warning(const nlohmann::json& w) {
        if (!out_.contains("warnings")) out_["warnings"] = nlohmann::json::array();
        out_["warnings"].push_back(w);
        return *this;
    }

    // Add a warning with code and message
    ResponseBuilder& warning(const std::string& code, const std::string& message) {
        nlohmann::json w = {{"code", code}, {"message", message}};
        return warning(w);
    }

    // Get the built response (caller should finalize/print)
    nlohmann::json build() const { return out_; }

private:
    const nlohmann::json& req_;
    std::string action_;
    long long elapsed_ms_;
    nlohmann::json out_ = nlohmann::json::object();
};

} // namespace xdebug_core
