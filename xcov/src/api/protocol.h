#pragma once

#include <json.hpp>

#include <string>
#include <vector>

namespace xcov {

constexpr const char* kApiVersion = "xcov.v1";

/// Parse the transport envelope without adding defaults.
nlohmann::json parse_request(const std::string& text);

/// Validate the action token is header-safe.
std::string validate_action_token(const nlohmann::json& action);

/// Apply the documented defaults to an already validated request.
nlohmann::json normalize_request(const nlohmann::json& req);

nlohmann::json completeness_summary(
    std::size_t total_count,
    std::size_t returned_count,
    bool response_truncated = false,
    bool scan_complete = true,
    bool analysis_complete = true,
    const std::vector<std::string>& truncation_scopes = {});

nlohmann::json ok_response(const nlohmann::json& req,
                           const nlohmann::json& summary,
                           const nlohmann::json& data,
                           const std::vector<std::string>& warnings = {});

/// Canonical JSON serialisation (sorted keys, no NaN, UTF-8 preserved).
std::string json_dumps(const nlohmann::json& value);

/// Human-oriented XOUT rendering shared by CLI and stdio-loop.
std::string render_xout(const nlohmann::json& rsp);
std::string render_transport_xout(const nlohmann::json& rsp);

} // namespace xcov
