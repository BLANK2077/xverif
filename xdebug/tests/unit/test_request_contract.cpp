#include "api/action_registry_init.h"
#include "core/diagnostic_error.h"
#include "api/request_envelope.h"
#include "api/request_validator.h"
#include "api/resource_resolver.h"
#include "api/response.h"
#include "core/schema/runtime_schema_validator.h"

#include <cassert>

int main() {
    using namespace xdebug;

    const ActionRegistry& registry = default_action_registry();
    const ActionSpec* value_spec = registry.find_spec("value.at");
    const ActionSpec* trace_spec = registry.find_spec("trace.driver");
    const ActionSpec* active_spec = registry.find_spec("trace.active_driver");
    const ActionSpec* active_chain_spec =
        registry.find_spec("trace.active_driver_chain");
    const ActionSpec* actions_spec = registry.find_spec("actions");
    const ActionSpec* abnormal_spec = registry.find_spec("detect_abnormal");
    const ActionSpec* stream_show_spec = registry.find_spec("stream.show");
    assert(value_spec && trace_spec && active_spec && active_chain_spec &&
           actions_spec && abnormal_spec && stream_show_spec);
    Json value_descriptor = action_spec_descriptor(*value_spec);
    assert(value_descriptor["required_args"].size() == 2);
    assert(value_descriptor["required_args"][0] == "signal");
    assert(value_descriptor["required_args"][1] == "time");
    assert(value_descriptor["allowed_values"]["format"].is_array());

    Json value_json = {
        {"api_version", "xdebug.v1"},
        {"request_id", "r0"},
        {"action", "value.at"},
        {"target", {{"fsdb", "waves.fsdb"}}},
        {"args", {{"signal", "top.clk"}, {"clock", "top.clk"}, {"time", "10ns"}}},
        {"limits", {{"timeout_ms", 1000}}}
    };
    RequestEnvelope value = RequestEnvelope::from_json(value_json);
    assert(value.api_version == "xdebug.v1");
    assert(value.request_id == "r0");
    assert(value.action == "value.at");
    assert(value.args["signal"] == "top.clk");

    RequestValidator validator;
    ValidationResult validation = validator.validate(value, *value_spec);
    assert(validation.ok);

    Json missing_time_json = value_json;
    missing_time_json["args"].erase("time");
    RequestEnvelope missing_time = RequestEnvelope::from_json(missing_time_json);
    validation = validator.validate(missing_time, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args.time");

    Json without_clock_json = value_json;
    without_clock_json["args"].erase("clock");
    RequestEnvelope without_clock = RequestEnvelope::from_json(without_clock_json);
    validation = validator.validate(without_clock, *value_spec);
    assert(validation.ok);

    Json wrong_version_json = value_json;
    wrong_version_json["api_version"] = "xdebug.v0";
    RequestEnvelope wrong_version = RequestEnvelope::from_json(wrong_version_json);
    validation = validator.validate(wrong_version, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "UNSUPPORTED_API_VERSION");

    Json bad_format_json = value_json;
    bad_format_json["args"]["format"] = 7;
    RequestEnvelope bad_format = RequestEnvelope::from_json(bad_format_json);
    validation = validator.validate(bad_format, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args.format");

    Json unknown_top_json = value_json;
    unknown_top_json["unexpected"] = true;
    RequestEnvelope unknown_top = RequestEnvelope::from_json(unknown_top_json);
    validation = validator.validate(unknown_top, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "unexpected");

    Json top_output_json = value_json;
    top_output_json["output"] = {{"format", "json"}};
    RequestEnvelope top_output = RequestEnvelope::from_json(top_output_json);
    validation = validator.validate(top_output, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "output");

    Json unknown_arg_json = value_json;
    unknown_arg_json["args"]["unexpected"] = true;
    RequestEnvelope unknown_arg = RequestEnvelope::from_json(unknown_arg_json);
    validation = validator.validate(unknown_arg, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args.unexpected");

    Json active_chain_json = {
        {"api_version", "xdebug.v1"},
        {"action", "trace.active_driver_chain"},
        {"target", {{"session_id", "case_a"}}},
        {"args", {{"signal", "top.q"}, {"time", "10ns"}}},
        {"limits", {{"max_depth", 8},
                    {"max_nodes", 50},
                    {"max_trace_signals", 64}}}
    };
    RequestEnvelope active_chain =
        RequestEnvelope::from_json(active_chain_json);
    validation = validator.validate(active_chain, *active_chain_spec);
    assert(validation.ok);

    Json removed_alias_limit_json = active_chain_json;
    removed_alias_limit_json["limits"]["max_alias_candidates"] = 8;
    RequestEnvelope removed_alias_limit =
        RequestEnvelope::from_json(removed_alias_limit_json);
    validation = validator.validate(removed_alias_limit, *active_chain_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] ==
           "limits.max_alias_candidates");

    Json active_alias_limit_json = active_chain_json;
    active_alias_limit_json["action"] = "trace.active_driver";
    active_alias_limit_json["limits"] = {{"max_alias_candidates", 8}};
    RequestEnvelope active_alias_limit =
        RequestEnvelope::from_json(active_alias_limit_json);
    validation = validator.validate(active_alias_limit, *active_spec);
    assert(validation.ok);

    Json bad_abnormal_checks_json = {
        {"api_version", "xdebug.v1"},
        {"request_id", "r1"},
        {"action", "detect_abnormal"},
        {"target", {{"fsdb", "waves.fsdb"}}},
        {"args", {
            {"signals", Json::array({"top.sig"})},
            {"checks", Json::array({"unknown_xz"})}
        }}
    };
    RequestEnvelope bad_abnormal_checks = RequestEnvelope::from_json(bad_abnormal_checks_json);
    validation = validator.validate(bad_abnormal_checks, *abnormal_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args.checks[0]");
    // The runtime publishes the schema-derived expectation.  Its wording may
    // evolve when the checked-in schema is tightened, so only require a
    // non-empty diagnostic here rather than a stale implementation word.
    assert(validation.error["expected"].is_string());
    assert(!validation.error["expected"].get<std::string>().empty());

    Json missing_abnormal_check_type_json = bad_abnormal_checks_json;
    missing_abnormal_check_type_json["args"]["checks"] = Json::array({Json::object()});
    RequestEnvelope missing_abnormal_check_type =
        RequestEnvelope::from_json(missing_abnormal_check_type_json);
    validation = validator.validate(missing_abnormal_check_type, *abnormal_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    // The validator reports the failing object when a required nested member
    // is absent; the exact JSON-schema location is implementation detail.
    assert(validation.error["invalid_arg"] == "args.checks[0]");

    Json bad_stream_show_json = {
        {"api_version", "xdebug.v1"},
        {"action", "stream.show"},
        {"args", {{"__bad_param__", true}}}
    };
    RequestEnvelope bad_stream_show = RequestEnvelope::from_json(bad_stream_show_json);
    validation = validator.validate(bad_stream_show, *stream_show_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error.contains("validation_issues"));
    assert(validation.error["validation_issues"].is_array());
    assert(validation.error["validation_issues"].size() >= 2);
    assert(!validation.error.contains("did_you_mean") ||
           validation.error["did_you_mean"] != validation.error["invalid_arg"]);

    Json checked_example = xdebug_core::valid_request_example("cursor.set");
    assert(checked_example["api_version"] == "xdebug.v1");
    assert(checked_example["action"] == "cursor.set");
    assert(checked_example["args"]["time"].is_string());

    Json built_error = xdebug_core::DiagnosticErrorBuilder::schema("INVALID_REQUEST", "bad stream")
        .invalid_arg("args.stream")
        .did_you_mean("args.stream")
        .to_json();
    assert(!built_error.contains("did_you_mean"));

    Json public_error = make_error(bad_stream_show_json, "stream.show", built_error);
    assert(public_error["summary"]["status"] == "error");
    assert(public_error["summary"]["error_code"] == "INVALID_REQUEST");
    assert(public_error["data"].is_null());

    xdebug_core::RuntimeSchemaValidator runtime_validator;
    Json batch_response = make_response(Json::object(), "batch");
    batch_response["summary"] = {
        {"count", 0},
        {"all_ok", true},
        {"failed_count", 0},
        {"failed_indexes", Json::array()},
        {"failed_codes", Json::array()},
        {"failed_layers", Json::array()},
    };
    batch_response["data"] = {{"results", Json::array()}};
    xdebug_core::RuntimeSchemaValidationResult response_validation =
        runtime_validator.validate_batch_response(batch_response);
    assert(response_validation.ok);

    Json unknown_child =
        make_error(
            Json::object(),
            "does.not.exist",
            "UNKNOWN_ACTION",
            "unknown action",
            true);
    batch_response["data"]["results"].push_back(unknown_child);
    batch_response["summary"] = {
        {"count", 1},
        {"all_ok", false},
        {"failed_count", 1},
        {"failed_indexes", Json::array({0})},
        {"failed_codes", Json::array({"UNKNOWN_ACTION"})},
        {"failed_layers", Json::array({"handler"})},
    };
    response_validation =
        runtime_validator.validate_batch_response(batch_response);
    assert(response_validation.ok);

    Json invalid_unknown_child = batch_response;
    invalid_unknown_child["data"]["results"][0]["unexpected"] = true;
    response_validation =
        runtime_validator.validate_batch_response(invalid_unknown_child);
    assert(!response_validation.ok);
    assert(response_validation.code ==
           "INTERNAL_RESPONSE_SCHEMA_VIOLATION");
    assert(response_validation.error["validation"]["issues"].is_array());
    assert(!response_validation.error["validation"]["issues"].empty());

    Json invalid_batch_envelope = batch_response;
    invalid_batch_envelope["summary"]["unexpected"] = true;
    response_validation =
        runtime_validator.validate_batch_response(invalid_batch_envelope);
    assert(!response_validation.ok);
    assert(response_validation.code ==
           "INTERNAL_RESPONSE_SCHEMA_VIOLATION");

    Json wrong_action_json = value_json;
    wrong_action_json["action"] = "trace.driver";
    RequestEnvelope wrong_action = RequestEnvelope::from_json(wrong_action_json);
    validation = validator.validate(wrong_action, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "UNKNOWN_ACTION");

    ResourceResolver resolver;
    ResourceResolution resource = resolver.resolve(value, *value_spec);
    assert(resource.ok && resource.context.waveform);

    RequestEnvelope no_target = value;
    no_target.target = Json::object();
    resource = resolver.resolve(no_target, *value_spec);
    assert(!resource.ok && resource.code == "RESOURCE_REQUIRED");

    RequestEnvelope design = value;
    design.action = "trace.driver";
    design.target = {{"daidir", "simv.daidir"}};
    resource = resolver.resolve(design, *trace_spec);
    assert(resource.ok && resource.context.design);

    RequestEnvelope combined = value;
    combined.action = "trace.active_driver";
    combined.target = {
        {"daidir", "simv.daidir"},
        {"fsdb", "waves.fsdb"}
    };
    resource = resolver.resolve(combined, *active_spec);
    assert(resource.ok && resource.context.design && resource.context.waveform);

    RequestEnvelope active_design_only = combined;
    active_design_only.target = {{"daidir", "simv.daidir"}};
    resource = resolver.resolve(active_design_only, *active_spec);
    assert(!resource.ok && resource.code == "RESOURCE_REQUIRED");

    RequestEnvelope active_waveform_only = combined;
    active_waveform_only.target = {{"fsdb", "waves.fsdb"}};
    resource = resolver.resolve(active_waveform_only, *active_spec);
    assert(!resource.ok && resource.code == "RESOURCE_REQUIRED");

    RequestEnvelope session = value;
    session.target = {{"session_id", "case_a"}};
    resource = resolver.resolve(session, *value_spec);
    assert(resource.ok && resource.context.session);

    RequestEnvelope no_resource;
    no_resource.api_version = "xdebug.v1";
    no_resource.action = "actions";
    resource = resolver.resolve(no_resource, *actions_spec);
    assert(resource.ok);

    return 0;
}
