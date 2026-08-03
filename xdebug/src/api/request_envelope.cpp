#include "api/request_envelope.h"

namespace xdebug {

RequestEnvelope RequestEnvelope::from_json(const Json& request) {
    RequestEnvelope envelope;
    envelope.raw = request;
    envelope.api_version = request.value("api_version", std::string());
    envelope.request_id = request.value("request_id", std::string());
    envelope.action = request.value("action", std::string());
    envelope.target = request.value("target", Json::object());
    envelope.args = request.value("args", Json::object());
    envelope.limits = request.value("limits", Json::object());
    return envelope;
}

} // namespace xdebug
