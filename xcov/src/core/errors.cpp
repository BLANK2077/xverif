#include "core/errors.h"

#include <utility>

namespace xcov {

Error::Error(std::string code, std::string message, nlohmann::json detail)
    : code_(std::move(code)),
      message_(std::move(message)),
      detail_(std::move(detail)) {}

nlohmann::json Error::to_json() const {
    nlohmann::json err = nlohmann::json::object();
    err["code"] = code_;
    err["message"] = message_;
    if (detail_.is_object()) {
        for (auto it = detail_.begin(); it != detail_.end(); ++it) {
            err["detail." + it.key()] = it.value();
        }
    }
    return err;
}

nlohmann::json error_response(const std::string& action,
                              const std::string& request_id,
                              const Error& error) {
    nlohmann::json rsp = nlohmann::json::object();
    rsp["ok"] = false;
    rsp["api_version"] = "xcov.v1";
    rsp["request_id"] = request_id;
    rsp["action"] = action.empty() ? "error" : action;
    rsp["summary"] = {
        {"total_count", 0},
        {"returned_count", 0},
        {"response_truncated", false},
        {"scan_complete", false},
        {"analysis_complete", false},
        {"truncation_scopes", nlohmann::json::array()},
    };
    rsp["data"] = nlohmann::json::object();
    rsp["error"] = error.to_json();
    rsp["warnings"] = nlohmann::json::array();
    return rsp;
}

} // namespace xcov
