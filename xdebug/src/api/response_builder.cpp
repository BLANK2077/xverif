#include "api/response_builder.h"
#include "api/response.h"

namespace xdebug {

Json ResponseBuilder::success(const RequestEnvelope& request, const ActionSpec& spec, const ActionResult& result) const {
    if (result.envelope.is_object()) return result.envelope;
    Json response = make_response(request.raw, spec.name, result.ok);
    if (result.summary.is_object() && !result.summary.empty()) response["summary"] = result.summary;
    if (!result.data.is_null()) response["data"] = result.data;
    if (result.warnings.is_array() && !result.warnings.empty()) response["warnings"] = result.warnings;
    if (!result.ok && !result.error.is_null()) response["error"] = result.error;
    if (!spec.response_schema.empty()) response["schema_version"] = spec.response_schema;
    return response;
}

Json ResponseBuilder::error(const RequestEnvelope& request,
                            const std::string& action,
                            const std::string& code,
                            const std::string& message,
                            bool recoverable) const {
    Json response = make_error(request.raw, action, code, message, recoverable);
    response["schema_version"] = "xdebug.error.v1";
    return response;
}

} // namespace xdebug
