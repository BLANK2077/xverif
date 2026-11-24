#pragma once

#include <json.hpp>

#include <exception>
#include <string>

namespace xcov {

/// Public, schema-visible failure. Mirrors xcov.errors.XcovError in Python.
class Error : public std::exception {
public:
    Error(std::string code, std::string message, nlohmann::json detail = nlohmann::json::object());

    const char* what() const noexcept override { return message_.c_str(); }

    const std::string& code() const { return code_; }
    const std::string& message() const { return message_; }
    const nlohmann::json& detail() const { return detail_; }

    /// Error payload as placed inside response.error (detail.* flattened).
    nlohmann::json to_json() const;

private:
    std::string code_;
    std::string message_;
    nlohmann::json detail_;
};

/// Build the canonical error response envelope.
nlohmann::json error_response(const std::string& action,
                              const std::string& request_id,
                              const Error& error);

} // namespace xcov
