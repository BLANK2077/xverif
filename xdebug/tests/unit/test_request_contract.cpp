#include "api/action_registry_init.h"
#include "core/diagnostic_error.h"
#include "api/request_envelope.h"
#include "api/request_validator.h"
#include "api/resource_resolver.h"
#include "api/response.h"
#include "core/schema/internal_request_contract.h"
#include "core/schema/runtime_schema_validator.h"
#include "session/transport_timeout.h"

#include <cassert>
#include <stdexcept>

int main() {
    using namespace xdebug;

    const ActionRegistry& registry = default_action_registry();
    const ActionSpec* value_spec = registry.find_spec("value.at");
    const ActionSpec* trace_spec = registry.find_spec("trace.driver");
    const ActionSpec* active_spec = registry.find_spec("trace.active_driver");
    const ActionSpec* active_chain_spec =
        registry.find_spec("trace.active_driver_chain");
    const ActionSpec* session_open_spec =
        registry.find_spec("session.open");
    const ActionSpec* actions_spec = registry.find_spec("actions");
    const ActionSpec* abnormal_spec = registry.find_spec("signal.anomaly.inspect");
    const ActionSpec* list_delete_spec = registry.find_spec("list.delete");
    const ActionSpec* apb_query_spec = registry.find_spec("apb.query");
    const ActionSpec* stream_describe_spec = registry.find_spec("stream.describe");
    assert(value_spec && trace_spec && active_spec && active_chain_spec &&
           session_open_spec &&
           actions_spec && abnormal_spec && list_delete_spec &&
           apb_query_spec && stream_describe_spec);
    Json value_descriptor = action_spec_descriptor(*value_spec);
    // value.at uses schema-level exactly-one constraints for
    // signal|list|apb|stream|axi and time|times, so no argument is
    // unconditionally required at the directory metadata layer.
    assert(value_descriptor["required_args"].empty());
    assert(value_descriptor["allowed_values"].is_object());
    assert(value_descriptor["allowed_values"].empty());

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

    const auto omitted_public_timeout =
        xdebug_core::public_request_timeout_override_ms(
            Json{{"api_version", "xdebug.internal.v1"},
                 {"action", "value.at"}});
    assert(!omitted_public_timeout.present);
    const auto empty_limits_public_timeout =
        xdebug_core::public_request_timeout_override_ms(
            Json{{"limits", Json::object()}});
    assert(!empty_limits_public_timeout.present);
    const auto explicit_public_timeout =
        xdebug_core::public_request_timeout_override_ms(
            Json{{"limits", {{"timeout_ms", 17}}}});
    assert(explicit_public_timeout.present);
    assert(explicit_public_timeout.value_ms == 17);

    for (const Json& invalid_timeout : {
             Json(0),
             Json(-1),
             Json("30000"),
             Json(2147483648LL),
         }) {
        bool rejected = false;
        try {
            (void)xdebug_core::public_request_timeout_override_ms(
                Json{{"limits", {{"timeout_ms", invalid_timeout}}}});
        } catch (const std::invalid_argument&) {
            rejected = true;
        }
        assert(rejected);
    }

    Json zero_timeout_json = value_json;
    zero_timeout_json["limits"]["timeout_ms"] = 0;
    RequestEnvelope zero_timeout =
        RequestEnvelope::from_json(zero_timeout_json);
    validation = validator.validate(zero_timeout, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "limits.timeout_ms");

    Json missing_time_json = value_json;
    missing_time_json["args"].erase("time");
    RequestEnvelope missing_time = RequestEnvelope::from_json(missing_time_json);
    validation = validator.validate(missing_time, *value_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args");

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

    for (const char* transport_field : {
             "id", "trace_id", "span_id", "parent_span_id", "auth_token"}) {
        Json transport_metadata_json = value_json;
        transport_metadata_json[transport_field] = "transport-only";
        RequestEnvelope transport_metadata =
            RequestEnvelope::from_json(transport_metadata_json);
        validation = validator.validate(transport_metadata, *value_spec);
        assert(!validation.ok);
        assert(validation.code == "INVALID_REQUEST");
        assert(validation.error["invalid_arg"] == transport_field);
    }

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

    Json trace_json = {
        {"api_version", "xdebug.v1"},
        {"action", "trace.driver"},
        {"target", {{"daidir", "simv.daidir"}}},
        {"args", {{"signal", "top.q"}}},
        {"limits", {{"max_results", 4}}}
    };
    RequestEnvelope trace = RequestEnvelope::from_json(trace_json);
    validation = validator.validate(trace, *trace_spec);
    assert(validation.ok);

    Json removed_trace_line_limit_json = trace_json;
    removed_trace_line_limit_json["args"]["line_limit"] = 4;
    RequestEnvelope removed_trace_line_limit =
        RequestEnvelope::from_json(removed_trace_line_limit_json);
    validation =
        validator.validate(removed_trace_line_limit, *trace_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] == "args.line_limit");

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
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error["invalid_arg"] ==
           "limits.max_alias_candidates");

    Json bad_abnormal_checks_json = {
        {"api_version", "xdebug.v1"},
        {"request_id", "r1"},
        {"action", "signal.anomaly.inspect"},
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

    Json bad_stream_describe_json = {
        {"api_version", "xdebug.v1"},
        {"action", "stream.describe"},
        {"args", {{"__bad_param__", true}}}
    };
    RequestEnvelope bad_stream_describe =
        RequestEnvelope::from_json(bad_stream_describe_json);
    validation = validator.validate(
        bad_stream_describe,
        *stream_describe_spec);
    assert(!validation.ok);
    assert(validation.code == "INVALID_REQUEST");
    assert(validation.error.contains("validation_issues"));
    assert(validation.error["validation_issues"].is_array());
    assert(validation.error["validation_issues"].size() >= 2);
    for (const Json& issue : validation.error["validation_issues"]) {
        assert(issue.is_object());
        assert(issue.size() == 2);
        assert(issue.contains("path"));
        assert(issue["path"].is_string());
        assert(!issue["path"].get<std::string>().empty());
        assert(issue.contains("message"));
        assert(issue["message"].is_string());
        assert(!issue["message"].get<std::string>().empty());
    }
    assert(!validation.error.contains("did_you_mean"));
    assert(!validation.error.contains("allowed_values"));
    assert(!validation.error.contains("candidates"));
    assert(!validation.error.contains("suggestions"));
    assert(!validation.error.contains("suggested_actions"));

    Json checked_example = xdebug_core::valid_request_example("waveform.cursor.set");
    assert(checked_example["api_version"] == "xdebug.v1");
    assert(checked_example["action"] == "waveform.cursor.set");
    assert(checked_example["args"]["time"].is_string());

    Json built_error = xdebug_core::DiagnosticErrorBuilder::schema("INVALID_REQUEST", "bad stream")
        .invalid_arg("args.stream")
        .available_values(Json::array({"args.stream"}))
        .to_json();
    assert(!built_error.contains("did_you_mean"));
    assert(built_error["available_values"] == Json::array({"args.stream"}));

    Json public_error =
        make_error(bad_stream_describe_json, "stream.describe", built_error);
    assert(public_error["summary"]["status"] == "error");
    assert(public_error["summary"]["error_code"] == "INVALID_REQUEST");
    assert(public_error["data"].is_null());

    const std::string sensitive_value =
        "managed-token-value-must-never-be-published";
    Json sensitive_error =
        xdebug_core::DiagnosticErrorBuilder::schema(
            "INVALID_REQUEST",
            "invalid token: " + sensitive_value)
            .invalid_arg("args.ownership_token")
            .expected("64 lowercase hexadecimal characters")
            .received(sensitive_value)
            .received_type("string")
            .correct_example({
                {"api_version", "xdebug.v1"},
                {"action", "session.open"},
                {"args", {
                    {"name", "managed"},
                    {"ownership_token", sensitive_value},
                }},
            })
            .to_json();
    assert(sensitive_error["invalid_arg"] ==
           "args.ownership_token");
    assert(sensitive_error["received_type"] == "string");
    assert(sensitive_error["received_redacted"] == true);
    assert(!sensitive_error.contains("received"));
    assert(sensitive_error["message"] ==
           "sensitive request field failed validation");
    assert(sensitive_error.dump().find(sensitive_value) ==
           std::string::npos);
    assert(
        sensitive_error["correct_example"]["args"].count(
            "ownership_token") == 0);

    Json invalid_managed_open = {
        {"api_version", "xdebug.v1"},
        {"action", "session.open"},
        {"target", {{"fsdb", "waves.fsdb"}}},
        {"args", {
            {"name", "managed"},
            {"ownership_token", sensitive_value},
        }},
    };
    RequestEnvelope invalid_managed_envelope =
        RequestEnvelope::from_json(invalid_managed_open);
    validation = validator.validate(
        invalid_managed_envelope,
        *session_open_spec);
    assert(!validation.ok);
    assert(validation.error["invalid_arg"] ==
           "args.ownership_token");
    assert(validation.error["received_type"] == "string");
    assert(validation.error["received_redacted"] == true);
    assert(!validation.error.contains("received"));
    assert(validation.error.dump().find(sensitive_value) ==
           std::string::npos);

    Json consumption_error =
        xdebug_core::request_consumption_violation(
            {"args.unused", "limits.unused"});
    assert(consumption_error["code"] ==
           "INTERNAL_REQUEST_CONSUMPTION_VIOLATION");
    assert(consumption_error["recoverable"] == false);
    assert(consumption_error["error_layer"] == "internal");
    assert(consumption_error["invalid_arg"] == "request");
    assert(consumption_error["received"] ==
           Json::array({"args.unused", "limits.unused"}));
    assert(!consumption_error.contains("action"));
    assert(!consumption_error.contains("unconsumed_paths"));
    Json consumption_response =
        make_error(
            bad_stream_describe_json,
            "stream.describe",
            consumption_error);
    assert(consumption_response["error"] == consumption_error);

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

    xdebug_core::RuntimeSchemaValidator runtime_validator;
    Json large_list_index_request = {
        {"api_version", "xdebug.v1"},
        {"action", "list.delete"},
        {"target", {{"session_id", "case_a"}}},
        {"args", {
            {"name", "basic"},
            {"index", Json::number_unsigned_t(1ULL << 63)},
        }},
    };
    xdebug_core::RuntimeSchemaValidationResult large_list_index_validation =
        runtime_validator.validate_request(
            "list.delete",
            large_list_index_request,
            list_delete_spec->request_schema);
    assert(large_list_index_validation.ok);

    Json bounded_large_integer_request = large_list_index_request;
    bounded_large_integer_request["limits"] = {
        {"timeout_ms", Json::number_unsigned_t(1ULL << 63)},
    };
    xdebug_core::RuntimeSchemaValidationResult bounded_large_integer_validation =
        runtime_validator.validate_request(
            "list.delete",
            bounded_large_integer_request,
            list_delete_spec->request_schema);
    assert(!bounded_large_integer_validation.ok);
    assert(bounded_large_integer_validation.error["invalid_arg"] ==
           "limits.timeout_ms");

    xdebug_core::RuntimeSchemaValidationResult response_validation =
        runtime_validator.validate_response(
            "stream.describe",
            public_error,
            stream_describe_spec->response_schema);
    assert(response_validation.ok);

    Json invalid_public_error = public_error;
    invalid_public_error["unexpected"] = true;
    response_validation =
        runtime_validator.validate_response(
            "stream.describe",
            invalid_public_error,
            stream_describe_spec->response_schema);
    assert(!response_validation.ok);
    assert(response_validation.code ==
           "INTERNAL_RESPONSE_SCHEMA_VIOLATION");
    assert(response_validation.error["error_layer"] == "internal");
    assert(response_validation.error["validation"]["issues"].is_array());

    Json apb_count_response =
        make_response(Json::object(), "apb.query");
    apb_count_response["summary"] = {
        {"name", "apb0"},
        {"direction", "all"},
        {"query_mode", "count"},
        {"scan_complete", true},
        {"analysis_complete", true},
        {"response_truncated", false},
        {"total_count", 2},
        {"returned_count", 0},
        {"truncation_scopes", Json::array()},
    };
    apb_count_response["data"] = {
        {"filter", {{"direction", "all"}}},
    };

    Json apb_list_response = apb_count_response;
    apb_list_response["summary"]["query_mode"] = "list";
    apb_list_response["summary"]["returned_count"] = 1;
    apb_list_response["data"]["transactions"] = Json::array({
        {
            {"time", "105ns"},
            {"addr", "32'h00001020"},
            {"data", "32'h00000012"},
            {"is_write", false},
            {"has_error", false},
        },
    });

    // Exercise both the initial compile and repeated cache-hit validation.
    // The APB count/list variants deliberately share most fields, so these
    // responses also force oneOf to inspect the non-selected branches.
    for (int iteration = 0; iteration < 3; ++iteration) {
        response_validation =
            runtime_validator.validate_response(
                "apb.query",
                apb_count_response,
                apb_query_spec->response_schema);
        assert(response_validation.ok);
        response_validation =
            runtime_validator.validate_response(
                "apb.query",
                apb_list_response,
                apb_query_spec->response_schema);
        assert(response_validation.ok);
    }

    Json apb_mismatched_count = apb_list_response;
    apb_mismatched_count["summary"]["query_mode"] = "count";
    response_validation =
        runtime_validator.validate_response(
            "apb.query",
            apb_mismatched_count,
            apb_query_spec->response_schema);
    assert(!response_validation.ok);
    assert(response_validation.code ==
           "INTERNAL_RESPONSE_SCHEMA_VIOLATION");
    assert(response_validation.error["validation"]["issues"].is_array());
    assert(!response_validation.error["validation"]["issues"].empty());

    Json apb_missing_discriminator = apb_count_response;
    apb_missing_discriminator["summary"].erase("query_mode");
    response_validation =
        runtime_validator.validate_response(
            "apb.query",
            apb_missing_discriminator,
            apb_query_spec->response_schema);
    assert(!response_validation.ok);
    assert(response_validation.code ==
           "INTERNAL_RESPONSE_SCHEMA_VIOLATION");

    Json apb_mismatched_list = apb_count_response;
    apb_mismatched_list["summary"]["query_mode"] = "list";
    response_validation =
        runtime_validator.validate_response(
            "apb.query",
            apb_mismatched_list,
            apb_query_spec->response_schema);
    assert(!response_validation.ok);

    Json apb_unexpected_top = apb_count_response;
    apb_unexpected_top["unexpected"] = true;
    response_validation =
        runtime_validator.validate_response(
            "apb.query",
            apb_unexpected_top,
            apb_query_spec->response_schema);
    assert(!response_validation.ok);

    Json apb_unexpected_filter = apb_count_response;
    apb_unexpected_filter["data"]["filter"]["address"] = {
        {"mode", "exact"},
        {"values", Json::array({"32'h00001020"})},
        {"unexpected", true},
    };
    response_validation =
        runtime_validator.validate_response(
            "apb.query",
            apb_unexpected_filter,
            apb_query_spec->response_schema);
    assert(!response_validation.ok);

    Json apb_unexpected_transaction = apb_list_response;
    apb_unexpected_transaction["data"]["transactions"][0]["unexpected"] =
        true;
    response_validation =
        runtime_validator.validate_response(
            "apb.query",
            apb_unexpected_transaction,
            apb_query_spec->response_schema);
    assert(!response_validation.ok);

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
    response_validation =
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

    Json session_response =
        make_response(
            value_json,
            "session.open",
            true);
    session_response["summary"] = {{"status", "opened"}};
    session_response["data"] = {{"run_manifest", nullptr}};
    session_response["session"] = {
        {"session_id", "case_a"},
        {"mode", "combined"},
        {"transport", "uds"},
        {"socket_path", "case_a.sock"},
        {"server_host", "localhost"},
        {"server_pid", 123},
        {"daidir", "simv.daidir"},
        {"fsdb", "waves.fsdb"},
    };
    response_validation =
        runtime_validator.validate_response(
            "session.open",
            session_response,
            session_open_spec->response_schema);
    assert(response_validation.ok);
    session_response["session"]["id"] = "case_a";
    response_validation =
        runtime_validator.validate_response(
            "session.open",
            session_response,
            session_open_spec->response_schema);
    assert(!response_validation.ok);

    Json public_open = {
        {"api_version", "xdebug.v1"},
        {"request_id", "open-1"},
        {"action", "session.open"},
        {"target", {
            {"daidir", "simv.daidir"},
            {"run_manifest", "run.manifest.json"},
        }},
        {"args", {{"name", "case_a"}}},
    };
    for (const char* removed_field : {"bind", "session_id"}) {
        Json removed_alias = public_open;
        removed_alias["args"][removed_field] = "legacy";
        xdebug_core::RuntimeSchemaValidationResult rejected =
            runtime_validator.validate_request(
                "session.open",
                removed_alias,
                session_open_spec->request_schema);
        assert(!rejected.ok);
        assert(rejected.code == "INVALID_REQUEST");
        assert(rejected.error["invalid_arg"] ==
               std::string("args.") + removed_field);
    }
    Json open_routing =
        xdebug_core::internal_routing_from_target(
            {{"daidir", "/resolved/simv.daidir"}});
    Json internal_open =
        xdebug_core::make_internal_request(
            public_open,
            open_routing,
            {{"trace_id", "trace-1"},
             {"span_id", "span-1"},
             {"parent_span_id", "span-0"}});
    assert(internal_open["api_version"] == "xdebug.internal.v1");
    assert(internal_open["routing"]["daidir"] ==
           "/resolved/simv.daidir");
    assert(internal_open["routing"]["mode"] == "design");
    assert(internal_open["observability"]["request_id"] == "open-1");
    assert(internal_open["observability"]["trace_id"] == "trace-1");
    assert(!internal_open["target"].contains("run_manifest"));
    assert(!internal_open.contains("request_id"));
    assert(!internal_open.contains("trace_id"));
    assert(!internal_open.contains("auth_token"));

    xdebug_core::RuntimeSchemaValidationResult internal_validation =
        runtime_validator.validate_internal_request(internal_open);
    assert(internal_validation.ok);
    // Revalidate the same action to exercise the per-action compiled cache.
    internal_validation =
        runtime_validator.validate_internal_request(internal_open);
    assert(internal_validation.ok);

    Json helper_apb = {
        {"api_version", "xdebug.internal.v1"},
        {"action", "apb.query"},
        {"target", {{"session_id", "case_a"}}},
        {"args", {{"name", "apb0"}, {"direction", "all"}}},
        {"limits", {{"timeout_ms", 1000}}},
        {"routing", {
            {"session_id", "case_a"},
            {"fsdb", "/resolved/waves.fsdb"},
            {"mode", "waveform"},
        }},
    };
    bool used_forward_envelope = false;
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            helper_apb, used_forward_envelope);
    assert(internal_validation.ok);
    assert(used_forward_envelope);

    Json helper_apb_unknown_arg = helper_apb;
    helper_apb_unknown_arg["args"]["legacy"] = true;
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            helper_apb_unknown_arg, used_forward_envelope);
    assert(internal_validation.ok);
    assert(used_forward_envelope);
    internal_validation = runtime_validator.validate_internal_request(
        helper_apb_unknown_arg);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json helper_apb_unknown_top = helper_apb;
    helper_apb_unknown_top["unexpected"] = true;
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            helper_apb_unknown_top, used_forward_envelope);
    assert(!internal_validation.ok);
    assert(used_forward_envelope);

    Json helper_apb_unknown_routing = helper_apb;
    helper_apb_unknown_routing["routing"]["unexpected"] = true;
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            helper_apb_unknown_routing, used_forward_envelope);
    assert(!internal_validation.ok);
    assert(used_forward_envelope);

    Json helper_apb_unknown_limits = helper_apb;
    helper_apb_unknown_limits["limits"]["unexpected"] = true;
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            helper_apb_unknown_limits, used_forward_envelope);
    assert(!internal_validation.ok);
    assert(used_forward_envelope);

    Json direct_apb = helper_apb;
    direct_apb["target"] = {{"fsdb", "waves.fsdb"}};
    direct_apb["routing"] = {
        {"fsdb", "/resolved/waves.fsdb"},
        {"mode", "waveform"},
    };
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            direct_apb, used_forward_envelope);
    assert(internal_validation.ok);
    assert(!used_forward_envelope);
    direct_apb["args"]["legacy"] = true;
    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            direct_apb, used_forward_envelope);
    assert(!internal_validation.ok);
    assert(!used_forward_envelope);

    internal_validation =
        runtime_validator.validate_internal_request_for_helper(
            internal_open, used_forward_envelope);
    assert(internal_validation.ok);
    assert(!used_forward_envelope);

    Json internal_open_missing_name = internal_open;
    internal_open_missing_name["args"].erase("name");
    internal_validation = runtime_validator.validate_internal_request(
        internal_open_missing_name);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json internal_open_extra_arg = internal_open;
    internal_open_extra_arg["args"]["legacy"] = true;
    internal_validation = runtime_validator.validate_internal_request(
        internal_open_extra_arg);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json internal_open_extra_target = internal_open;
    internal_open_extra_target["target"]["run_manifest"] =
        "run.manifest.json";
    internal_validation = runtime_validator.validate_internal_request(
        internal_open_extra_target);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json internal_open_extra_routing = internal_open;
    internal_open_extra_routing["routing"]["auth_token"] = "legacy";
    internal_validation = runtime_validator.validate_internal_request(
        internal_open_extra_routing);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json ping =
        xdebug_core::make_internal_control_request("server.ping");
    internal_validation =
        runtime_validator.validate_internal_request(ping);
    assert(internal_validation.ok);
    Json authenticated_ping =
        xdebug_core::with_internal_transport_auth(ping, "token");
    assert(authenticated_ping["routing"]["transport_auth_token"] ==
           "token");
    internal_validation =
        runtime_validator.validate_internal_request(authenticated_ping);
    assert(internal_validation.ok);

    Json public_version_internal = value_json;
    public_version_internal["api_version"] = "xdebug.internal.v1";
    internal_validation = runtime_validator.validate_request(
        "value.at",
        public_version_internal,
        value_spec->request_schema);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json unknown_internal = ping;
    unknown_internal["action"] = "server.pign";
    internal_validation =
        runtime_validator.validate_internal_request(unknown_internal);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "UNKNOWN_ACTION");
    assert(internal_validation.error["invalid_arg"] == "action");

    Json missing_internal_action = ping;
    missing_internal_action.erase("action");
    internal_validation = runtime_validator.validate_internal_request(
        missing_internal_action);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    internal_validation = runtime_validator.validate_internal_request(
        Json::array());
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json typo_internal = ping;
    typo_internal["routing"] = {{"auth_token", "legacy"}};
    internal_validation =
        runtime_validator.validate_internal_request(typo_internal);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json leaked_internal = ping;
    leaked_internal["auth_token"] = "legacy";
    internal_validation =
        runtime_validator.validate_internal_request(leaked_internal);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "INVALID_REQUEST");

    Json public_internal_version = ping;
    public_internal_version["api_version"] = "xdebug.v1";
    internal_validation =
        runtime_validator.validate_internal_request(
            public_internal_version);
    assert(!internal_validation.ok);
    assert(internal_validation.code == "UNSUPPORTED_API_VERSION");

    bool rejected_observability_typo = false;
    try {
        (void)xdebug_core::make_internal_request(
            public_open,
            open_routing,
            {{"trace", "legacy"}});
    } catch (const std::invalid_argument&) {
        rejected_observability_typo = true;
    }
    assert(rejected_observability_typo);

    return 0;
}
