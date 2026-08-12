#include "api/request_validator.h"
#include "core/diagnostic_error.h"
#include "api/response.h"

namespace xdebug {

using xdebug_core::DiagnosticErrorBuilder;

namespace {

bool has_string_field(const Json& object, const std::string& field) {
    return object.is_object() && object.contains(field) && object[field].is_string() &&
           !object[field].get<std::string>().empty();
}

bool is_missing_session_selector(const RequestEnvelope& request) {
    if (request.action != "session.close") return false;
    if (has_string_field(request.target, "session_id")) return false;
    return true;
}

Json session_target_example(const std::string& action) {
    return {
        {"api_version", "xdebug.v1"},
        {"action", action},
        {"target", {{"session_id", "case_a"}}},
        {"args", Json::object()}
    };
}

void normalize_session_selector_error(const RequestEnvelope& request, ValidationResult& result) {
    if (!is_missing_session_selector(request)) return;
    const std::string expected = "target.session_id";
    result.message = expected + " is required";
    result.error = DiagnosticErrorBuilder::schema("INVALID_REQUEST", result.message)
        .invalid_arg(expected)
        .expected("non-empty string session id")
        .correct_example(session_target_example(request.action))
        .to_json();
}

bool reject_invalid_session_selector(const RequestEnvelope& request, ValidationResult& result) {
    if (!request.target.is_object() || !request.target.contains("session_id")) return false;
    if (request.target["session_id"].is_string() &&
        !request.target["session_id"].get<std::string>().empty()) {
        return false;
    }
    result.ok = false;
    result.code = "INVALID_REQUEST";
    result.message = "invalid parameter target.session_id: expected non-empty string session id";
    result.error = DiagnosticErrorBuilder::schema("INVALID_REQUEST", result.message)
        .invalid_arg("target.session_id")
        .expected("non-empty string session id")
        .received_type(request.target["session_id"].type_name())
        .correct_example(session_target_example(request.action))
        .to_json();
    return true;
}

} // namespace

ValidationResult RequestValidator::validate(const RequestEnvelope& request, const ActionSpec& spec) const {
    ValidationResult result;
    if (request.api_version != kApiVersion) {
        result.ok = false;
        result.code = "UNSUPPORTED_API_VERSION";
        result.message = "expected xdebug.v1";
        result.error = DiagnosticErrorBuilder::schema(result.code, result.message)
            .invalid_arg("api_version")
            .expected("xdebug.v1")
            .to_json();
        return result;
    }
    if (request.action != spec.name) {
        result.ok = false;
        result.code = "UNKNOWN_ACTION";
        result.message = "request action does not match ActionSpec";
        result.error = DiagnosticErrorBuilder::schema(result.code, result.message)
            .invalid_arg("action")
            .expected(spec.name)
            .to_json();
        return result;
    }

    if (reject_invalid_session_selector(request, result)) return result;

    xdebug_core::RuntimeSchemaValidator validator;
    xdebug_core::RuntimeSchemaValidationResult schema_result =
        validator.validate_request(spec.name, request.raw, spec.request_schema);
    if (!schema_result.ok) {
        result.ok = false;
        result.code = schema_result.code.empty() ? "INVALID_REQUEST" : schema_result.code;
        result.message = schema_result.message;
        result.error = schema_result.error;
        normalize_session_selector_error(request, result);
        return result;
    }
    return result;
}

} // namespace xdebug
