from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator


XDEBUG = Path(__file__).resolve().parents[2]


def _load_contract_module():
    path = XDEBUG / "specs" / "session_batch_response_contracts.py"
    spec = importlib.util.spec_from_file_location(
        "xdebug_session_batch_response_contracts",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACTS = _load_contract_module()


def _load_audit_module():
    path = XDEBUG / "tools" / "audit_json_responses.py"
    spec = importlib.util.spec_from_file_location(
        "xdebug_json_response_audit",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit_module()
DATA_POINTER = "/data"


def _closed(
    properties: dict[str, dict[str, Any]],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _base_definitions() -> dict[str, dict[str, Any]]:
    return {
        "tool": _closed(
            {
                "name": {"type": "string"},
                "version": {"type": "string"},
            },
            ("name", "version"),
        ),
        "session": _closed(
            {
                "session_id": {"type": "string", "minLength": 1},
                "mode": {"enum": list(CONTRACTS.SESSION_MODES)},
                "transport": {
                    "enum": list(CONTRACTS.SESSION_TRANSPORTS)
                },
            },
            ("session_id", "mode", "transport"),
        ),
        "sessionRecord": _closed(
            {
                "session_id": {"type": "string", "minLength": 1},
                "mode": {"enum": list(CONTRACTS.SESSION_MODES)},
                "transport": {
                    "enum": list(CONTRACTS.SESSION_TRANSPORTS)
                },
            },
            ("session_id", "mode", "transport"),
        ),
        "genericError": _closed(
            {
                "code": {"type": "string", "minLength": 1},
                "message": {"type": "string", "minLength": 1},
                "recoverable": {"type": "boolean"},
                "error_layer": {
                    "enum": [
                        "schema",
                        "handler",
                        "wrapper",
                        "session_manager",
                        "transport",
                        "internal",
                    ]
                },
                "invalid_arg": {"type": "string"},
                "expected": {"type": "string"},
                "health_status": {"type": "string"},
                "backend_error_code": {"type": "string"},
            },
            ("code", "message", "recoverable", "error_layer"),
        ),
    }


def _schema_for_definition(name: str) -> dict[str, Any]:
    definitions = _base_definitions()
    definitions.update(
        CONTRACTS.session_response_contract_definitions()
    )
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$defs": definitions,
        "$ref": f"#/$defs/{name}",
    }
    Draft7Validator.check_schema(schema)
    return schema


def _tool() -> dict[str, Any]:
    return {"name": "xdebug", "version": "1"}


def _session() -> dict[str, Any]:
    return {
        "session_id": "case_a",
        "mode": "combined",
        "transport": "uds",
    }


def _error(
    code: str,
    *,
    layer: str = "session_manager",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": f"{code} message",
        "recoverable": True,
        "error_layer": layer,
    }


def _idle_cleanup() -> dict[str, Any]:
    return {
        "removed_session": _session(),
        "reason": "idle_timeout",
        "idle_sec": 301,
        "idle_timeout_sec": 300,
    }


def _unhealthy_cleanup() -> dict[str, Any]:
    return {
        "removed_session": _session(),
        "reason": "unhealthy",
        "health_evidence": {
            "code": "SESSION_UNHEALTHY",
            "message": "server process exited",
            "health_status": "process_exited",
        },
    }


def test_session_contract_definitions_are_compact_evidence_only() -> None:
    definitions = CONTRACTS.session_response_contract_definitions()
    assert set(definitions) == {
        "sessionCleanupItem",
        "sessionHealthFailureEvidence",
    }
    serialized = repr(definitions)
    for retired in (
        "sessionBackendResponse",
        "sessionBulkResult",
        "sessionKillLifecycleSuccess",
        "api_version",
        "request_id",
    ):
        assert retired not in serialized


def test_session_success_contracts_are_explicit_correlated_variants() -> None:
    expected = {
        "session.open": {"opened"},
        "session.list": {
            "without_expired_cleanup",
            "with_expired_cleanup",
        },
        "session.doctor": {"healthy"},
        "session.close": {"single", "bulk_empty", "bulk_populated"},
        "session.kill": {"single", "bulk_empty", "bulk_populated"},
        "session.gc": {
            "empty",
            "kept_only",
            "removed_only",
            "kept_and_removed",
        },
    }
    assert set(CONTRACTS.SESSION_RESPONSE_ACTIONS) == set(expected)
    for action, variant_names in expected.items():
        variants = CONTRACTS.session_success_response_variants(action)
        assert {variant.name for variant in variants} == variant_names
        for variant in variants:
            for schema in (variant.summary, variant.data):
                assert schema["type"] == "object"
                assert schema["additionalProperties"] is False
                assert schema["required"]

    with pytest.raises(ValueError):
        CONTRACTS.session_success_response_variants("session.unknown")


def test_session_cleanup_reason_and_evidence_are_correlated() -> None:
    validator = Draft7Validator(
        _schema_for_definition("sessionCleanupItem")
    )
    idle = _idle_cleanup()
    unhealthy = _unhealthy_cleanup()
    for item in (idle, unhealthy):
        assert validator.is_valid(item), list(
            validator.iter_errors(item)
        )

    idle_with_health = copy.deepcopy(idle)
    idle_with_health["health_evidence"] = unhealthy["health_evidence"]
    assert not validator.is_valid(idle_with_health)

    unhealthy_with_idle = copy.deepcopy(unhealthy)
    unhealthy_with_idle["idle_sec"] = 1
    assert not validator.is_valid(unhealthy_with_idle)

    nested_envelope = copy.deepcopy(idle)
    nested_envelope["result"] = {
        "api_version": "xdebug.v1",
        "ok": True,
        "action": "session.kill",
    }
    assert not validator.is_valid(nested_envelope)

    bad_status = copy.deepcopy(unhealthy)
    bad_status["health_evidence"]["health_status"] = "error"
    assert not validator.is_valid(bad_status)

    missing_message = copy.deepcopy(unhealthy)
    missing_message["health_evidence"].pop("message")
    assert not validator.is_valid(missing_message)


def test_session_generator_pointer_hook_is_explicit() -> None:
    expected = {
        ("session.close", DATA_POINTER + "/removed_session"):
            "#/$defs/sessionRecord",
        ("session.kill", DATA_POINTER + "/removed_session"):
            "#/$defs/sessionRecord",
        ("session.close", DATA_POINTER + "/removed_sessions/*"):
            "#/$defs/sessionRecord",
        ("session.kill", DATA_POINTER + "/removed_sessions/*"):
            "#/$defs/sessionRecord",
        ("session.gc", DATA_POINTER + "/kept_sessions/*"):
            "#/$defs/sessionRecord",
        ("session.gc", DATA_POINTER + "/removed/*"):
            "#/$defs/sessionCleanupItem",
        ("session.list", DATA_POINTER + "/removed/*"):
            "#/$defs/sessionCleanupItem",
    }
    for (action, pointer), reference in expected.items():
        assert CONTRACTS.session_explicit_response_schema(
            action,
            pointer,
        ) == {"$ref": reference}
    assert (
        CONTRACTS.session_explicit_response_schema(
            "session.gc",
            DATA_POINTER + "/before/*",
        )
        is None
    )


def test_response_audit_rejects_nested_lifecycle_envelopes_and_derived_stability() -> None:
    response_dir = XDEBUG / "examples" / "responses"
    for name in (
        "session.open.basic.json",
        "session.list.expired_removed.json",
        "session.doctor.basic.json",
        "session.close.basic.json",
        "session.kill.all.json",
        "session.gc.basic.json",
        "signal.stability.basic.json",
    ):
        path = response_dir / name
        response = json.loads(
            path.read_text(encoding="utf-8")
        )
        assert AUDIT.audit_response(path, response) == []

    close_path = response_dir / "session.close.basic.json"
    close = json.loads(
        close_path.read_text(encoding="utf-8")
    )
    close["data"]["backend"] = {
        "api_version": "xdebug.v1",
        "ok": True,
        "action": "session.kill",
    }
    assert any(
        "must not embed a public response envelope" in error
        for error in AUDIT.audit_response(close_path, close)
    )

    stability_path = response_dir / "signal.stability.basic.json"
    stability = json.loads(
        stability_path.read_text(encoding="utf-8")
    )
    stability["data"]["initial_value"] = copy.deepcopy(
        stability["data"]["changes"][0]["value"]
    )
    assert any(
        "contains derivable fields" in error
        for error in AUDIT.audit_response(stability_path, stability)
    )

    list_path = response_dir / "session.list.expired_removed.json"
    list_response = json.loads(list_path.read_text(encoding="utf-8"))
    list_response["summary"]["expired_removed_count"] = 2
    assert any(
        "does not match data.removed length" in error
        for error in AUDIT.audit_response(list_path, list_response)
    )

    bulk_path = response_dir / "session.kill.all.json"
    bulk = json.loads(bulk_path.read_text(encoding="utf-8"))
    bulk["summary"]["requested_count"] = 2
    assert any(
        "does not match data.removed_sessions length" in error
        for error in AUDIT.audit_response(bulk_path, bulk)
    )

    gc_path = response_dir / "session.gc.basic.json"
    gc = json.loads(gc_path.read_text(encoding="utf-8"))
    gc["summary"]["before_count"] = 3
    assert any(
        "must equal kept_count + removed_count" in error
        for error in AUDIT.audit_response(gc_path, gc)
    )


def _action_response_schema(
    action: str,
    payload_schema: dict[str, Any],
) -> dict[str, Any]:
    definitions = {
        # Both representative actions deliberately use identical local
        # definition names with different payload types.
        "tool": _closed(
            {
                "name": {"type": "string"},
                "version": {"type": "string"},
            },
            ("name", "version"),
        ),
        "session": _closed(
            {
                "session_id": {"type": "string"},
                "mode": {"enum": list(CONTRACTS.SESSION_MODES)},
                "transport": {
                    "enum": list(CONTRACTS.SESSION_TRANSPORTS)
                },
            },
            ("session_id", "mode", "transport"),
        ),
        "payload": payload_schema,
        "successSummary": _closed(
            {"status": {"const": "ok"}},
            ("status",),
        ),
        "successData": _closed(
            {"payload": {"$ref": "#/$defs/payload"}},
            ("payload",),
        ),
        "errorSummary": _closed(
            {
                "status": {"const": "error"},
                "error_code": {"type": "string"},
            },
            ("status", "error_code"),
        ),
        "error": _closed(
            {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "recoverable": {"type": "boolean"},
                "error_layer": {"type": "string"},
            },
            ("code", "message", "recoverable", "error_layer"),
        ),
    }
    properties = {
        "api_version": {"const": "xdebug.v1"},
        "ok": {"type": "boolean"},
        "action": {"const": action},
        "tool": {"$ref": "#/$defs/tool"},
        "session": {
            "anyOf": [
                {"type": "null"},
                {"$ref": "#/$defs/session"},
            ]
        },
        "summary": {
            "oneOf": [
                {"$ref": "#/$defs/successSummary"},
                {"$ref": "#/$defs/errorSummary"},
            ]
        },
        "data": {
            "oneOf": [
                {"$ref": "#/$defs/successData"},
                {"type": "null"},
            ]
        },
        "error": {
            "oneOf": [
                {"type": "null"},
                {"$ref": "#/$defs/error"},
            ]
        },
    }
    success = {
        "properties": {
            "ok": {"const": True},
            "summary": {"$ref": "#/$defs/successSummary"},
            "data": {"$ref": "#/$defs/successData"},
            "error": {"type": "null"},
        },
        "required": ["ok", "summary", "data"],
    }
    error = {
        "properties": {
            "ok": {"const": False},
            "summary": {"$ref": "#/$defs/errorSummary"},
            "data": {"type": "null"},
            "error": {"$ref": "#/$defs/error"},
        },
        "required": ["ok", "summary", "data", "error"],
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"xdebug.{action}.response.v1",
        "$defs": definitions,
        "type": "object",
        "properties": properties,
        "required": [
            "api_version",
            "ok",
            "action",
            "summary",
            "data",
        ],
        "oneOf": [success, error],
        "additionalProperties": False,
    }


def _action_success(
    action: str,
    payload: Any,
) -> dict[str, Any]:
    return {
        "api_version": "xdebug.v1",
        "ok": True,
        "action": action,
        "tool": _tool(),
        "session": _session(),
        "summary": {"status": "ok"},
        "data": {"payload": payload},
        "error": None,
    }


def _action_error(action: str) -> dict[str, Any]:
    return {
        "api_version": "xdebug.v1",
        "ok": False,
        "action": action,
        "tool": _tool(),
        "session": None,
        "summary": {
            "status": "error",
            "error_code": "INVALID_REQUEST",
        },
        "data": None,
        "error": _error("INVALID_REQUEST", layer="schema"),
    }


def _unknown_action_error(action: str = "unknown.action") -> dict[str, Any]:
    return {
        "api_version": "xdebug.v1",
        "ok": False,
        "action": action,
        "tool": _tool(),
        "session": None,
        "summary": {
            "status": "error",
            "error_code": "UNKNOWN_ACTION",
        },
        "data": None,
        "error": _error("UNKNOWN_ACTION", layer="handler"),
    }


def _batch_summary(count: int, failed: int = 0) -> dict[str, Any]:
    return {
        "count": count,
        "all_ok": failed == 0,
        "failed_count": failed,
        "failed_indexes": [] if failed == 0 else [count - 1],
        "failed_codes": [] if failed == 0 else ["INVALID_REQUEST"],
        "failed_layers": [] if failed == 0 else ["schema"],
    }


def _batch_success(results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = sum(not result["ok"] for result in results)
    return {
        "api_version": "xdebug.v1",
        "ok": True,
        "action": "batch",
        "tool": _tool(),
        "session": None,
        "summary": _batch_summary(len(results), failed),
        "data": {"results": results},
        "error": None,
    }


def _batch_root_schema(
    contract,
) -> dict[str, Any]:
    definitions = _base_definitions()
    definitions.update(contract.definitions)
    summary = _closed(
        {
            "count": {"type": "integer", "minimum": 0},
            "all_ok": {"type": "boolean"},
            "failed_count": {"type": "integer", "minimum": 0},
            "failed_indexes": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0},
            },
            "failed_codes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "failed_layers": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        (
            "count",
            "all_ok",
            "failed_count",
            "failed_indexes",
            "failed_codes",
            "failed_layers",
        ),
    )
    data = _closed(
        {
            "results": {
                "type": "array",
                "items": contract.item_schema,
            }
        },
        ("results",),
    )
    properties = {
        "api_version": {"const": "xdebug.v1"},
        "ok": {"type": "boolean"},
        "action": {"const": "batch"},
        "tool": {"$ref": "#/$defs/tool"},
        "session": {
            "oneOf": [
                {"type": "null"},
                {"$ref": "#/$defs/session"},
            ]
        },
        "summary": summary,
        "data": data,
        "error": {"type": "null"},
    }
    schema = _closed(
        properties,
        (
            "api_version",
            "ok",
            "action",
            "summary",
            "data",
        ),
    )
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["$defs"] = definitions
    schema["properties"]["ok"] = {"const": True}
    Draft7Validator.check_schema(schema)
    return schema


def _batch_contract():
    schemas = {
        "alpha": _action_response_schema(
            "alpha",
            {"type": "string"},
        ),
        "beta": _action_response_schema(
            "beta",
            {"type": "integer"},
        ),
    }
    return CONTRACTS.build_batch_result_contract(
        schemas,
        known_actions={"batch", "alpha", "beta"},
    )


def test_batch_union_is_action_discriminated_local_and_recursive() -> None:
    contract = _batch_contract()
    schema = _batch_root_schema(contract)
    validator = Draft7Validator(schema)

    alpha = _action_success("alpha", "value")
    beta = _action_success("beta", 7)
    beta_error = _action_error("beta")
    unknown_error = _unknown_action_error()
    nested = _batch_success([alpha])
    response = _batch_success(
        [alpha, beta, beta_error, unknown_error, nested]
    )
    assert validator.is_valid(response), list(
        validator.iter_errors(response)
    )

    wrong_payload = _batch_success(
        [_action_success("alpha", 7)]
    )
    assert not validator.is_valid(wrong_payload)

    unknown_success = _batch_success(
        [_action_success("unknown.action", "value")]
    )
    assert not validator.is_valid(unknown_success)

    known_action_cannot_use_unknown_branch = _batch_success(
        [_unknown_action_error("alpha")]
    )
    # It remains valid only because alpha's own strict error contract accepts
    # the response.  The unknown branch explicitly excludes alpha.
    assert validator.is_valid(known_action_cannot_use_unknown_branch)

    refs: list[str] = []

    def collect_refs(value: Any) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                refs.append(value["$ref"])
            for child in value.values():
                collect_refs(child)
        elif isinstance(value, list):
            for child in value:
                collect_refs(child)

    collect_refs(contract.item_schema)
    collect_refs(contract.definitions)
    assert refs
    assert all(reference.startswith("#") for reference in refs)
    assert not any("jsonValue" in reference for reference in refs)

    def has_scope_keyword(value: Any) -> bool:
        if isinstance(value, dict):
            if "$id" in value or "$schema" in value:
                return True
            return any(has_scope_keyword(child) for child in value.values())
        if isinstance(value, list):
            return any(has_scope_keyword(child) for child in value)
        return False

    assert not has_scope_keyword(contract.definitions)


def test_batch_nested_mutation_matrix_rejects_unknown_fields() -> None:
    validator = Draft7Validator(_batch_root_schema(_batch_contract()))
    base = _batch_success([_action_success("alpha", "value")])
    assert validator.is_valid(base)

    mutations = []

    summary_unknown = copy.deepcopy(base)
    summary_unknown["data"]["results"][0]["summary"]["unknown"] = True
    mutations.append(summary_unknown)

    data_unknown = copy.deepcopy(base)
    data_unknown["data"]["results"][0]["data"]["unknown"] = True
    mutations.append(data_unknown)

    session_unknown = copy.deepcopy(base)
    session_unknown["data"]["results"][0]["session"]["unknown"] = True
    mutations.append(session_unknown)

    envelope_unknown = copy.deepcopy(base)
    envelope_unknown["data"]["results"][0]["unknown"] = True
    mutations.append(envelope_unknown)

    unknown_error_summary = _batch_success(
        [_unknown_action_error()]
    )
    unknown_error_summary["data"]["results"][0]["summary"][
        "unknown"
    ] = True
    mutations.append(unknown_error_summary)

    unknown_error_session = _batch_success(
        [_unknown_action_error()]
    )
    unknown_error_session["data"]["results"][0]["session"] = {
        **_session(),
        "unknown": True,
    }
    mutations.append(unknown_error_session)

    nested_batch = _batch_success(
        [_batch_success([_action_success("alpha", "value")])]
    )
    nested_batch["data"]["results"][0]["data"]["results"][0][
        "data"
    ]["unknown"] = True
    mutations.append(nested_batch)

    for response in mutations:
        assert not validator.is_valid(response)


def test_batch_builder_rejects_partial_catalog_and_external_refs() -> None:
    alpha = _action_response_schema(
        "alpha",
        {"type": "string"},
    )
    with pytest.raises(ValueError, match="missing: beta"):
        CONTRACTS.build_batch_result_contract(
            {"alpha": alpha},
            known_actions={"batch", "alpha", "beta"},
        )

    external = copy.deepcopy(alpha)
    external["$defs"]["successData"]["properties"]["payload"] = {
        "$ref": "other.schema.json"
    }
    with pytest.raises(ValueError, match="external"):
        CONTRACTS.build_batch_result_contract(
            {"alpha": external},
            known_actions={"batch", "alpha"},
        )

    nested_scope = copy.deepcopy(alpha)
    nested_scope["$defs"]["payload"]["$id"] = "nested"
    with pytest.raises(ValueError, match="scope"):
        CONTRACTS.build_batch_result_contract(
            {"alpha": nested_scope},
            known_actions={"batch", "alpha"},
        )

    wrong_discriminator = copy.deepcopy(alpha)
    wrong_discriminator["properties"]["action"]["const"] = "beta"
    with pytest.raises(ValueError, match="discriminator"):
        CONTRACTS.build_batch_result_contract(
            {"alpha": wrong_discriminator},
            known_actions={"batch", "alpha"},
        )
