from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

import jsonschema
import pytest

from runner import CliRunner, StdioLoopRunner


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_catalog(cli_runner: CliRunner) -> Dict[str, Any]:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "actions",
            "args": {"output": {"verbose": True}},
        },
        output_format="json",
    )
    assert result.ok, result.stderr_raw
    return result.response


def _request_schema_args_required(schema: Dict[str, Any]) -> list[str]:
    args_schema = schema.get("properties", {}).get("args", {})
    return list(args_schema.get("required", []))


def _example_satisfies_groups(args: Dict[str, Any], groups: list[list[str]]) -> bool:
    return any(all(key in args for key in group) for group in groups)


def _required_related_args(spec: Dict[str, Any]) -> set[str]:
    keys = set(spec.get("required_args", []))
    for group in spec.get("required_arg_groups", []):
        keys.update(group)
    for conditional in spec.get("conditional_required_args", []):
        keys.update(conditional.get("when", {}).keys())
        keys.update(conditional.get("required", []))
    return keys


@pytest.mark.contract
def test_runtime_catalog_matches_specs_and_referenced_files(
    cli_runner: CliRunner, xdebug_root: Path
) -> None:
    catalog = _runtime_catalog(cli_runner)
    specs = _load_json(xdebug_root / "specs" / "actions" / "actions.yaml")[
        "actions"
    ]
    specs_by_name = {spec["name"]: spec for spec in specs}
    descriptors = {
        descriptor["name"]: descriptor
        for descriptor in catalog["data"]["actions"]
    }

    expected_implemented = set(specs_by_name)
    assert "removed" not in catalog["data"]
    assert set(descriptors) == expected_implemented

    for name, descriptor in descriptors.items():
        spec = specs_by_name[name]
        assert descriptor["category"] == spec["category"]
        assert descriptor["status"] == spec["status"]
        assert descriptor["requires"] == spec["requires"]
        assert descriptor["handler_kind"] == spec["handler_kind"]
        assert descriptor["request_schema"] == spec["schemas"]["request"]
        assert descriptor["response_schema"] == spec["schemas"]["response"]
        assert descriptor["request_examples"] == spec["examples"]["request"]
        for field in ("description_en", "description_zh", "purposes", "use_when",
                      "do_not_use_when", "alternatives"):
            assert descriptor[field] == spec[field]
        assert set(spec["examples"]["response"]).issubset(
            descriptor["response_examples"]
        )
        for reference in (
            descriptor["request_schema"],
            descriptor["response_schema"],
            *descriptor["request_examples"],
            *descriptor["response_examples"],
        ):
            assert (xdebug_root / reference).is_file(), reference


@pytest.mark.contract
def test_runtime_catalog_default_is_compact_without_duplicate_names(
    cli_runner: CliRunner,
) -> None:
    result = cli_runner.run(
        {"api_version": "xdebug.v1", "action": "actions", "args": {}},
        output_format="json",
    )
    assert result.ok, result.response
    assert result.response["summary"]["verbose"] is False
    assert result.response["summary"]["filtered"] is False
    assert result.response["summary"]["action_count"] == result.response["summary"]["total_action_count"]
    assert "implemented" not in result.response["data"]
    assert result.response["data"]["actions"]
    assert all(isinstance(name, str) for name in result.response["data"]["actions"])


@pytest.mark.contract
def test_runtime_catalog_filters_and_bilingual_keyword_search(
    cli_runner: CliRunner,
) -> None:
    filtered = cli_runner.run({
        "api_version": "xdebug.v1", "action": "actions",
        "args": {"filter": {"category": ["waveform"], "requires": ["waveform"],
                            "purposes": ["query"], "keyword": "AXI"}},
    }, output_format="json")
    assert filtered.ok, filtered.response
    assert filtered.response["summary"]["filtered"] is True
    names = filtered.response["data"]["actions"]
    assert "axi.query" in names
    assert "value.at" in names
    assert all(name.startswith("axi.") or name == "value.at" for name in names)

    chinese = cli_runner.run({
        "api_version": "xdebug.v1", "action": "actions",
        "args": {"filter": {"keyword": "握手"}},
    }, output_format="json")
    assert chinese.ok, chinese.response
    assert "protocol.handshake.inspect" in chinese.response["data"]["actions"]


@pytest.mark.contract
def test_action_schemas_have_bilingual_descriptions(xdebug_root: Path) -> None:
    specs = _load_json(xdebug_root / "specs/actions/actions.yaml")["actions"]
    for spec in specs:
        for kind in ("request", "response"):
            schema = _load_json(xdebug_root / spec["schemas"][kind])
            assert schema["description"] == spec["description_en"]
            assert schema["x-description-zh"] == spec["description_zh"]


@pytest.mark.contract
def test_runtime_schema_unknown_action_suggests_nearby_names(
    cli_runner: CliRunner,
) -> None:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "schema",
            "args": {"action": "value.a", "kind": "request"},
        },
        output_format="json",
    )
    assert result.returncode == 1
    error = result.response["error"]
    assert error["code"] == "UNKNOWN_ACTION"
    assert error["error_layer"] == "handler"
    assert "value.at" in error["available_values"]
    assert "value.batch_at" not in error["available_values"]
    assert "did_you_mean" not in error
    assert "suggested_actions" not in error


@pytest.mark.contract
def test_runtime_unknown_action_suggests_nearby_names(
    cli_runner: CliRunner,
) -> None:
    result = cli_runner.run(
        {"api_version": "xdebug.v1", "action": "signal.statistcs", "args": {}},
        output_format="json",
    )
    assert result.returncode == 1
    error = result.response["error"]
    assert error["code"] == "UNKNOWN_ACTION"
    assert error["error_layer"] == "handler"
    assert "signal.statistics" in error["available_values"]
    assert "did_you_mean" not in error
    assert "suggested_actions" not in error


@pytest.mark.contract
def test_schema_catalog_requires_an_explicit_action(
    cli_runner: CliRunner,
) -> None:
    result = cli_runner.run(
        {"api_version": "xdebug.v1", "action": "schema", "args": {}},
        output_format="json",
    )

    assert not result.ok
    error = result.response["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["error_layer"] == "schema"
    assert error["invalid_arg"] == "args.action"


@pytest.mark.contract
def test_action_required_args_match_runtime_schema_and_examples(
    cli_runner: CliRunner, xdebug_root: Path
) -> None:
    catalog = _runtime_catalog(cli_runner)
    specs = _load_json(xdebug_root / "specs" / "actions" / "actions.yaml")[
        "actions"
    ]
    descriptors = {
        descriptor["name"]: descriptor
        for descriptor in catalog["data"]["actions"]
    }

    for spec in specs:
        name = spec["name"]
        required_args = list(spec.get("required_args", []))
        descriptor = descriptors[name]
        assert list(descriptor.get("required_args", [])) == required_args

        request_schema = _load_json(xdebug_root / spec["schemas"]["request"])
        assert _request_schema_args_required(request_schema) == required_args

        for example_ref in spec["examples"]["request"]:
            example = _load_json(xdebug_root / example_ref)
            args = example.get("args", {})
            for key in required_args:
                assert key in args, "%s example is missing args.%s" % (name, key)
            for group in spec.get("required_arg_groups", []):
                assert _example_satisfies_groups(args, [group]) or _example_satisfies_groups(
                    args, spec["required_arg_groups"]
                ), "%s example does not satisfy any required_arg_groups" % name
            for conditional in spec.get("conditional_required_args", []):
                when = conditional.get("when", {})
                if all(args.get(key) == value for key, value in when.items()):
                    for key in conditional.get("required", []):
                        assert key in args, "%s example is missing conditional args.%s" % (
                            name,
                            key,
                        )


@pytest.mark.contract
def test_action_schema_hints_are_synced(xdebug_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(xdebug_root / "tools" / "sync_action_schema_hints.py"),
            "--check",
        ],
        cwd=xdebug_root.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.contract
def test_all_response_schemas_are_strict_and_synced(xdebug_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(xdebug_root / "tools" / "sync_response_schemas.py"),
            "--check",
        ],
        cwd=xdebug_root.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    specs = _load_json(xdebug_root / "specs" / "actions" / "actions.yaml")[
        "actions"
    ]
    for spec in specs:
        schema = _load_json(xdebug_root / spec["schemas"]["response"])
        assert schema.get("additionalProperties") is False, spec["name"]
        assert len(schema.get("oneOf", [])) == 2, spec["name"]
        assert {
            "api_version", "ok", "action", "tool", "session",
            "summary", "data", "error",
        }.issubset(schema.get("required", [])), spec["name"]
        validator = jsonschema.Draft202012Validator(schema)
        response_examples = [
            _load_json(xdebug_root / relative)
            for relative in spec["examples"]["response"]
        ]
        for response_example in response_examples:
            validator.validate(response_example)
        success_example = next(
            example for example in response_examples if example["ok"] is True
        )
        success_with_typo = dict(success_example)
        success_with_typo["summray"] = success_with_typo["summary"]
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(success_with_typo)
        success_with_nested_typo = dict(success_example)
        success_with_nested_typo["summary"] = dict(success_example["summary"])
        success_with_nested_typo["summary"]["unknown_contract_field"] = True
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(success_with_nested_typo)
        validator.validate(
            {
                "api_version": "xdebug.v1",
                "ok": False,
                "action": spec["name"],
                "tool": success_example["tool"],
                "session": None,
                "summary": {
                    "status": "error",
                    "error_code": "CONTRACT_TEST_ERROR",
                },
                "data": None,
                "error": {
                    "code": "CONTRACT_TEST_ERROR",
                    "message": "canonical strict error branch",
                    "recoverable": True,
                    "error_layer": "handler",
                },
            }
        )
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(
                {
                    "api_version": "xdebug.v1",
                    "ok": False,
                    "action": spec["name"],
                    "tool": success_example["tool"],
                    "session": None,
                    "summary": {
                        "status": "error",
                        "error_code": "CONTRACT_TEST_ERROR",
                    },
                    "data": None,
                    "error": {
                        "code": "CONTRACT_TEST_ERROR",
                        "message": "canonical strict error branch",
                        "recoverable": True,
                        "error_layer": "handler",
                        "unknown_detail": True,
                    },
                }
            )

    canonicalize_schema = _load_json(
        xdebug_root
        / "schemas"
        / "v1"
        / "actions"
        / "signal.canonicalize.response.schema.json"
    )
    canonicalize = jsonschema.Draft202012Validator(canonicalize_schema)
    ambiguous = _load_json(
        xdebug_root
        / "examples"
        / "responses"
        / "signal.canonicalize.ambiguous.json"
    )
    canonicalize.validate(ambiguous)
    for missing_field in (
        "scan_complete",
        "analysis_complete",
        "response_truncated",
        "total_count",
        "returned_count",
        "truncation_scopes",
    ):
        incomplete_error = copy.deepcopy(ambiguous)
        del incomplete_error["error"][missing_field]
        with pytest.raises(jsonschema.ValidationError):
            canonicalize.validate(incomplete_error)
    contradictory_error = copy.deepcopy(ambiguous)
    contradictory_error["error"]["scan_complete"] = False
    contradictory_error["error"]["analysis_complete"] = True
    contradictory_error["error"]["truncation_scopes"] = []
    with pytest.raises(jsonschema.ValidationError):
        canonicalize.validate(contradictory_error)

    session_open_schema = _load_json(
        xdebug_root
        / "schemas"
        / "v1"
        / "actions"
        / "session.open.response.schema.json"
    )
    session_open = jsonschema.Draft202012Validator(session_open_schema)
    session_open_with_advisory = _load_json(
        xdebug_root
        / "examples"
        / "responses"
        / "session.open.basic.json"
    )
    session_open_with_advisory["advisories"] = [
        {
            "code": "RESOURCE_SESSION_ALREADY_ALIVE",
            "severity": "info",
            "match_kind": "same_combined_resource",
            "existing_session_id": "case_existing",
            "existing_mode": "combined",
            "message": "same resource already has an alive session",
        }
    ]
    session_open.validate(session_open_with_advisory)
    advisory_with_typo = copy.deepcopy(session_open_with_advisory)
    advisory_with_typo["advisories"][0]["existing_session"] = "case_existing"
    with pytest.raises(jsonschema.ValidationError):
        session_open.validate(advisory_with_typo)

    generic_error_schema = _load_json(
        xdebug_root / "schemas" / "v1" / "xdebug.error.schema.json"
    )
    generic_error = jsonschema.Draft202012Validator(generic_error_schema)
    for path in sorted((xdebug_root / "examples" / "errors").glob("*.error.json")):
        generic_error.validate(_load_json(path))
    unknown_action = _load_json(
        xdebug_root / "examples" / "errors" / "unknown_action.error.json"
    )
    error_with_legacy_meta = copy.deepcopy(unknown_action)
    error_with_legacy_meta["meta"] = {"truncated": False}
    with pytest.raises(jsonschema.ValidationError):
        generic_error.validate(error_with_legacy_meta)
    error_with_unknown_detail = copy.deepcopy(unknown_action)
    error_with_unknown_detail["error"]["unknown_detail"] = True
    with pytest.raises(jsonschema.ValidationError):
        generic_error.validate(error_with_unknown_detail)
    for retired in (
        xdebug_root / "schemas" / "v1" / "xdebug.request.schema.json",
        xdebug_root / "schemas" / "v1" / "xdebug.response.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "meta.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "error.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "evidence.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "limits.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "output.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "source_location.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "target.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "warning.schema.json",
        xdebug_root / "schemas" / "v1" / "common" / "waveform_sample.schema.json",
    ):
        assert not retired.exists()


@pytest.mark.contract
def test_runtime_request_schemas_are_strict_and_synced(xdebug_root: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(xdebug_root / "tools" / "sync_runtime_request_schemas.py"),
            "--check",
        ],
        cwd=xdebug_root.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    specs = _load_json(xdebug_root / "specs" / "actions" / "actions.yaml")[
        "actions"
    ]
    for spec in specs:
        schema = _load_json(xdebug_root / spec["schemas"]["request"])
        assert schema.get("additionalProperties") is False, spec["name"]
        args_schema = schema.get("properties", {}).get("args", {})
        assert args_schema.get("additionalProperties") is False, spec["name"]


@pytest.mark.contract
def test_axi_response_schemas_are_strict(xdebug_root: Path) -> None:
    actions = (
        "axi.analysis", "axi.channel_stall", "axi.config.list", "axi.config.load",
        "axi.transaction.cursor", "axi.export", "axi.latency_outlier",
        "axi.outstanding_timeline", "axi.query", "axi.request_response_pair",
    )

    def assert_closed_business_objects(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert (
                    node.get("additionalProperties") is False
                    or (
                        node.get("x-dynamic-map") is True
                        and isinstance(node.get("additionalProperties"), dict)
                    )
                ), path
            for key, value in node.items():
                assert_closed_business_objects(value, "%s.%s" % (path, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                assert_closed_business_objects(value, "%s[%d]" % (path, index))

    for action in actions:
        schema = _load_json(
            xdebug_root / "schemas" / "v1" / "actions" /
            ("%s.response.schema.json" % action)
        )
        assert schema.get("additionalProperties") is False, action
        summary = schema["$defs"]["successSummary"]
        data = schema["$defs"]["successData"]
        assert_closed_business_objects(summary, "%s.summary" % action)
        assert_closed_business_objects(data, "%s.data" % action)

        example = _load_json(
            xdebug_root / "examples" / "responses" / ("%s.basic.json" % action)
        )
        jsonschema.Draft202012Validator(schema).validate(example)


@pytest.mark.contract
def test_protocol_statistics_response_schemas_are_strict(
    xdebug_root: Path,
) -> None:
    for action in ("apb.statistics", "axi.statistics"):
        schema = _load_json(
            xdebug_root / "schemas" / "v1" / "actions" /
            ("%s.response.schema.json" % action)
        )
        assert schema.get("additionalProperties") is False, action
        example = _load_json(
            xdebug_root / "examples" / "responses" / ("%s.basic.json" % action)
        )
        jsonschema.Draft202012Validator(schema).validate(example)


@pytest.mark.contract
def test_protocol_statistics_request_filter_contract(xdebug_root: Path) -> None:
    def validator(action: str) -> jsonschema.Draft202012Validator:
        return jsonschema.Draft202012Validator(_load_json(
            xdebug_root / "schemas" / "v1" / "actions" /
            ("%s.request.schema.json" % action)
        ))

    target = {"session_id": "case_a"}
    apb = validator("apb.statistics")
    axi = validator("axi.statistics")
    apb.validate({
        "api_version": "xdebug.v1", "action": "apb.statistics",
        "target": target, "args": {"name": "apb0"},
    })
    for address in (
        {"mode": "exact", "values": ["0", "'h4"]},
        {"mode": "range", "begin": "'h0", "end": "'hff"},
        {"mode": "mask", "value": "'h10", "mask": "'hf0"},
    ):
        apb.validate({
            "api_version": "xdebug.v1", "action": "apb.statistics",
            "target": target,
            "args": {"name": "apb0", "filter": {"address": address}},
        })
    axi.validate({
        "api_version": "xdebug.v1", "action": "axi.statistics",
        "target": target,
        "args": {"name": "axi0", "filter": {
            "direction": "write", "ids": ["1", "3"],
            "address": {"mode": "exact", "values": ["'h1000"]},
        }},
    })

    invalid_requests = (
        (apb, {"name": "apb0", "filter": {"ids": ["1"]}}),
        (apb, {"name": "apb0", "filter": {"address": {
            "mode": "exact", "values": [],
        }}}),
        (axi, {"name": "axi0", "filter": {"ids": []}}),
        (axi, {"name": "axi0", "filter": {
            "address": {"mode": "exact", "values": ["0x1000"]},
        }}),
        (axi, {"name": "axi0", "filter": {"address": {
            "mode": "range", "begin": "0", "end": "1", "mask": "1",
        }}}),
    )
    for current_validator, args in invalid_requests:
        with pytest.raises(jsonschema.ValidationError):
            current_validator.validate({
                "api_version": "xdebug.v1",
                "action": "axi.statistics" if current_validator is axi else "apb.statistics",
                "target": target,
                "args": args,
            })

    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1", "action": "axi.statistics",
            "args": {"name": "axi0"},
        })


@pytest.mark.contract
def test_waveform_expression_contract_schemas_are_strict(xdebug_root: Path) -> None:
    target = {"session_id": "strict-request-shape-session"}
    list_value_schema = _load_json(
        xdebug_root / "schemas" / "v1" / "actions" / "value.at.request.schema.json"
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "api_version": "xdebug.v1",
                "action": "value.at",
                "target": target,
                "args": {
                    "list": "debug_context",
                    "times": "10ns",
                },
            },
            list_value_schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "api_version": "xdebug.v1",
                "action": "value.at",
                "target": target,
                "args": {
                    "list": "debug_context",
                    "times": ["10ns"],
                    "edge": "posedge",
                },
            },
            list_value_schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {
                "api_version": "xdebug.v1",
                "action": "value.at",
                "target": target,
                "args": {
                    "list": "debug_context",
                    "stream": "stream0",
                    "times": ["10ns"],
                },
            },
            list_value_schema,
        )

    for action in ("verify.conditions", "window.verify"):
        schema = _load_json(
            xdebug_root / "schemas" / "v1" / "actions" / f"{action}.request.schema.json"
        )
        args = {
            "clock": "top.u.clk",
            "signals": {"a": "top.u.a"},
            "conditions": [{}],
        }
        if action == "verify.conditions":
            args["time"] = "10ns"
        else:
            args["time_range"] = {"begin": "0ns", "end": "10ns"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {
                    "api_version": "xdebug.v1",
                    "action": action,
                    "target": target,
                    "args": args,
                },
                schema,
            )


@pytest.mark.contract
def test_signal_xz_verify_request_schema_is_strict(xdebug_root: Path) -> None:
    schema = _load_json(
        xdebug_root / "schemas" / "v1" / "actions" /
        "signal.xz_verify.request.schema.json"
    )
    validator = jsonschema.Draft202012Validator(schema)
    base = {
        "api_version": "xdebug.v1",
        "action": "signal.xz_verify",
        "target": {"session_id": "strict-request-shape-session"},
        "args": {
            "signal": "top.xz_bus",
            "expected_state": "x",
            "time_range": {"begin": "10ns", "end": "20ns"},
        },
    }
    validator.validate(base)
    for mode in ("exact", "contains"):
        validator.validate({
            **base,
            "args": {**base["args"], "expected_state": "z", "match_mode": mode},
        })
    for bad_args in (
        {**base["args"], "expected_state": "unknown"},
        {**base["args"], "match_mode": "any"},
        {**base["args"], "clock": "top.clk"},
        {key: value for key, value in base["args"].items() if key != "time_range"},
    ):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({**base, "args": bad_args})


@pytest.mark.contract
def test_bad_parameter_schema_errors_include_ai_repair_hints(
    cli_runner: CliRunner,
) -> None:
    target = {"session_id": "strict-request-shape-session"}
    cases = [
        (
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": target,
                "args": {"name": "apb0", "direction": "read", "limit": 10},
            },
            "args.limit",
            "args.query.line_limit",
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "event.find",
                "target": target,
                "args": {"expr": "valid"},
            },
            "args",
            None,
            ["args.name", "args.clock + args.signals"],
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "stream.config.load",
                "target": target,
                "args": {},
            },
            "args",
            None,
            ["args.config", "args.config_path"],
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "trace.active_driver_chain",
                "target": target,
                "args": {"signal": "top.q", "time": "10ns", "depth": 4},
            },
            "args.depth",
            "limits.max_depth",
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {"name": "req_stream", "query": "summary"},
            },
            "args.name",
            "args.stream",
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "session.doctor",
                "target": {"session_id": 123},
            },
            "target.session_id",
            None,
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "session.list",
                "target": {"session_id": 123},
            },
            "target.session_id",
            None,
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "axi.channel_stall",
                "target": target,
                "args": {"name": "if0", "channel": "zz"},
            },
            "args.channel",
            None,
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "trace.active_driver",
                "target": target,
                "args": {"signal": "top.q", "time": "10ns", "include_trace": True},
            },
            "args.include_trace",
            None,
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "list.delete",
                "target": target,
                "args": {"name": "", "index": 1},
            },
            "args.name",
            None,
            None,
        ),
        (
            {
                "api_version": "xdebug.v1",
                "action": "list.delete",
                "target": target,
                "args": {"name": "basic", "signal": ""},
            },
            "args.signal",
            None,
            None,
        ),
        *[
            (
                {
                    "api_version": "xdebug.v1",
                    "action": action,
                    "target": target,
                    "args": (
                        {"signal": "top.q", "time": "10ns"}
                        if action in {
                            "trace.active_driver",
                            "trace.active_driver_chain",
                        }
                        else {"signal": "top.q"}
                    ),
                    "limits": {"max_results": 2_147_483_648},
                },
                "limits.max_results",
                None,
                None,
            )
            for action in (
                "trace.driver",
                "trace.load",
                "trace.active_driver",
                "trace.active_driver_chain",
            )
        ],
        (
            {
                "api_version": "xdebug.v1",
                "action": "event.find",
                "target": target,
                "args": {
                    "expr": "valid",
                    "clock": "top.clk",
                    "signals": {"valid": "top.valid"},
                    "time_range": {"start": "0ns", "end": "10ns"},
                },
            },
            "args.time_range.start",
            "args.time_range.begin",
            None,
        ),
    ]
    for request, invalid_arg, _retired_hint, required_any_of in cases:
        result = cli_runner.run(request, output_format="json")
        assert not result.ok, request
        error = result.response["error"]
        assert error["code"] == "INVALID_REQUEST"
        assert error["error_layer"] == "schema"
        assert error["invalid_arg"] == invalid_arg
        assert "correct_example" in error
        assert "data" not in result.response or result.response["data"] is None
        assert invalid_arg in error["message"]
        assert "did_you_mean" not in error
        assert "allowed_values" not in error
        assert "candidates" not in error
        assert "suggestions" not in error
        assert "suggested_actions" not in error
        if required_any_of is not None:
            assert error["required_any_of"] == required_any_of
            for item in required_any_of:
                assert item in error["message"]


@pytest.mark.contract
def test_all_actions_unknown_args_report_correct_example(
    stateless_stdio_loop: StdioLoopRunner,
    xdebug_root: Path,
) -> None:
    catalog_result = stateless_stdio_loop.request(
        {
            "api_version": "xdebug.v1",
            "action": "actions",
            "args": {"output": {"verbose": True}},
        }
    )
    assert catalog_result.ok, catalog_result.stderr_raw
    catalog = catalog_result.response
    for descriptor in catalog["data"]["actions"]:
        action = descriptor["name"]
        request_examples = descriptor["request_examples"]
        assert request_examples, action
        request = copy.deepcopy(_load_json(xdebug_root / request_examples[0]))
        request.setdefault("args", {})["__bad_param__"] = True
        result = stateless_stdio_loop.request(request)
        assert not result.ok, action
        error = result.response["error"]
        assert error["code"] == "INVALID_REQUEST", action
        assert error["error_layer"] == "schema", action
        assert error["invalid_arg"] == "args.__bad_param__", action
        assert "correct_example" in error, action


@pytest.mark.contract
def test_schema_error_has_canonical_shape_and_all_validation_issues(
    cli_runner: CliRunner,
) -> None:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "stream.describe",
            "target": {"session_id": "strict-request-shape-session"},
            "args": {"__bad_param__": True},
        },
        output_format="json",
    )
    assert not result.ok
    response = result.response
    assert response["summary"] == {
        "status": "error",
        "error_code": "INVALID_REQUEST",
    }
    assert response.get("data") is None
    error = response["error"]
    assert error["error_layer"] == "schema"
    assert len(error["validation_issues"]) >= 2
    assert "did_you_mean" not in error
    assert "allowed_values" not in error
    assert "candidates" not in error
    assert "suggestions" not in error
    assert "suggested_actions" not in error


@pytest.mark.contract
def test_schema_handler_enum_error_uses_diagnostic_error(cli_runner: CliRunner) -> None:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "schema",
            "args": {"action": "value.at", "kind": "bad_kind"},
        },
        output_format="json",
    )
    assert not result.ok
    error = result.response["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["error_layer"] == "schema"
    assert error["invalid_arg"] == "args.kind"
    assert error["available_values"] == ["request", "response"]
    assert error["correct_example"]["args"]["kind"] == "request"
    assert "data" not in result.response or result.response["data"] is None


@pytest.mark.contract
def test_bad_parameter_xout_shows_correct_example(cli_runner: CliRunner) -> None:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "apb.query",
            "target": {"session_id": "strict-request-shape-session"},
            "args": {"name": "apb0", "direction": "read", "limit": 10},
        },
        output_format="xout",
    )
    assert not result.ok
    assert result.response.startswith("@xdebug.error.v1\n")
    assert "invalid_arg" in result.response
    assert "args.limit" in result.response
    assert "line_limit" in result.response
    assert "pointer\tkind\tvalue" not in result.response


@pytest.mark.contract
def test_bad_parameter_runtime_errors_include_ai_repair_hints(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
) -> None:
    fsdb = complex_wave_fsdb
    session_name = "bad_param_runtime_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        cases = [
            {
                "api_version": "xdebug.v1",
                "action": "window.verify",
                "target": target,
                "args": {
                    "clock": "ai_complex_top.clk",
                    "signals": {"a": "ai_complex_top.sig_a"},
                    "conditions": [
                        {
                            "expr": "a == 8'h22",
                            "mode": "always",
                        }
                    ],
                    "time_range": {"begin": "100ns", "end": "0ns"},
                },
            },
            {
                "api_version": "xdebug.v1",
                "action": "counter.statistics",
                "target": target,
                "args": {
                    "clock": "ai_complex_top.clk",
                    "time_range": {"begin": "100ns", "end": "0ns"},
                    "vld": {"expr": "vld", "signals": {"vld": "ai_complex_top.hs_valid"}},
                    "cnt": "ai_complex_top.sig_a",
                },
            },
        ]
        for request in cases:
            result = cli_runner.run(request, output_format="json", timeout_sec=120)
            assert not result.ok, result.stdout_raw + result.stderr_raw
            error = result.response["error"]
            assert error["code"] == "TIME_RANGE_INVALID"
            assert error["invalid_arg"] == "args.time_range.end"
            assert "correct_example" in error
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_stream_handler_errors_include_current_entry_examples(
    cli_runner: CliRunner,
    xdebug_root: Path,
    stream_wave_fsdb: Path,
) -> None:
    fsdb = stream_wave_fsdb
    session_name = "stream_error_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        config_path = xdebug_root / "testdata" / "waveform" / "stream_v1" / "config" / "streams.json"
        loaded = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "stream.config.load",
                "target": target,
                "args": {"config_path": str(config_path)},
            },
            output_format="json",
            timeout_sec=120,
        )
        assert loaded.ok, loaded.stdout_raw + loaded.stderr_raw
        cases = [
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.config.get",
                    "target": target,
                    "args": {"name": "missing_stream"},
                },
                "args.name",
                "stream.config.get",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.describe",
                    "target": target,
                    "args": {"stream": "missing_stream"},
                },
                "args.stream",
                "stream.describe",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.query",
                    "target": target,
                    "args": {
                        "stream": "ready_stream",
                        "query": "summary",
                        "time_range": {"begin": "not_time", "end": "100ns"},
                    },
                },
                "args.time_range.begin",
                "stream.query",
                "INVALID_TIME",
            ),
        ]
        for case in cases:
            if len(case) == 3:
                request, invalid_arg, example_action = case
                code = "CONFIG_NOT_FOUND"
            else:
                request, invalid_arg, example_action, code = case
            result = cli_runner.run(request, output_format="json", timeout_sec=120)
            assert not result.ok, result.stdout_raw + result.stderr_raw
            error = result.response["error"]
            assert error["code"] == code
            assert error["error_layer"] == "handler"
            assert error["invalid_arg"] == invalid_arg
            if code == "CONFIG_NOT_FOUND":
                assert error["missing_resource"] == "stream config"
            assert "next_actions" in error
            assert "example_note" in error
            assert error["correct_example"]["action"] == example_action
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_list_handler_errors_include_current_entry_examples(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
) -> None:
    fsdb = complex_wave_fsdb
    session_name = "list_error_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        create = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "list.create",
                "target": target,
                "args": {"name": "list_contract"},
            },
            output_format="json",
            timeout_sec=120,
        )
        assert create.ok, create.stdout_raw + create.stderr_raw
        cases = [
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "list.show",
                    "target": target,
                    "args": {"name": "missing_list"},
                },
                "LIST_NOT_FOUND",
                "args.name",
                "list.show",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "list.add",
                    "target": target,
                    "args": {"name": "list_contract", "signal": "ai_complex_top.no_such"},
                },
                "SIGNAL_NOT_FOUND",
                "args.signal",
                "list.add",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "list.delete",
                    "target": target,
                    "args": {"name": "list_contract", "index": 1},
                },
                "PRECONDITION_FAILED",
                "args.index",
                "list.delete",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "list.delete",
                    "target": target,
                    "args": {
                        "name": "list_contract",
                        "index": 2**63,
                    },
                },
                "PRECONDITION_FAILED",
                "args.index",
                "list.delete",
            ),
        ]
        for request, code, invalid_arg, example_action in cases:
            result = cli_runner.run(request, output_format="json", timeout_sec=120)
            assert not result.ok, result.stdout_raw + result.stderr_raw
            error = result.response["error"]
            assert error["code"] == code
            assert error["error_layer"] == "handler"
            assert error["invalid_arg"] == invalid_arg
            assert "expected" in error
            assert "example_note" in error
            assert error["correct_example"]["action"] == example_action

        missing_signal = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "list.delete",
                "target": target,
                "args": {
                    "name": "list_contract",
                    "signal": "ai_complex_top.sig_a",
                },
            },
            output_format="json",
            timeout_sec=120,
        )
        assert not missing_signal.ok
        assert (
            missing_signal.response["error"]["code"]
            == "CONFIG_NOT_FOUND"
        )
        assert (
            missing_signal.response["error"]["error_layer"]
            == "handler"
        )

        typed_create = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "list.create",
                "target": target,
                "args": {
                    "name": "typed_delete_contract",
                    "signals": [
                        "ai_complex_top.sig_a",
                        "ai_complex_top.sig_b",
                    ],
                },
            },
            output_format="json",
            timeout_sec=120,
        )
        assert typed_create.ok, (
            typed_create.stdout_raw + typed_create.stderr_raw
        )
        typed_delete = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "list.delete",
                "target": target,
                "args": {
                    "name": "typed_delete_contract",
                    "index": 2,
                },
            },
            output_format="json",
            timeout_sec=120,
        )
        assert typed_delete.ok, (
            typed_delete.stdout_raw + typed_delete.stderr_raw
        )
        assert (
            typed_delete.response["summary"]["removed"]
            == "ai_complex_top.sig_b"
        )
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_event_handler_errors_include_current_entry_examples(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
) -> None:
    fsdb = complex_wave_fsdb
    session_name = "event_error_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        cases = [
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "event.find",
                    "target": target,
                    "args": {"name": "missing_event", "expr": "valid"},
                },
                "CONFIG_NOT_FOUND",
                "args.name",
                "event.find",
                "handler",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "event.find",
                    "target": target,
                    "args": {
                        "clock": "ai_complex_top.clk",
                        "signals": {"valid": "ai_complex_top.hs_valid"},
                        "expr": "ai_complex_top.hs_valid",
                    },
                },
                "INVALID_ARGUMENT",
                "args.expr",
                "event.find",
                "handler",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "event.find",
                    "target": target,
                    "args": {
                        "clock": "ai_complex_top.clk",
                        "signals": {"valid": "ai_complex_top.hs_valid"},
                        "expr": "valid",
                        "mode": "middle",
                    },
                },
                "INVALID_REQUEST",
                "args.mode",
                "event.find",
                "schema",
            ),
        ]
        for request, code, invalid_arg, example_action, error_layer in cases:
            result = cli_runner.run(request, output_format="json", timeout_sec=120)
            assert not result.ok, result.stdout_raw + result.stderr_raw
            error = result.response["error"]
            assert error["code"] == code
            assert error["error_layer"] == error_layer
            assert error["invalid_arg"] == invalid_arg
            assert "expected" in error
            if error_layer == "handler":
                assert "example_note" in error
            assert error["correct_example"]["action"] == example_action
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_value_and_verify_handler_errors_include_current_entry_examples(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
) -> None:
    fsdb = complex_wave_fsdb
    session_name = "value_verify_error_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        cases = [
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "value.at",
                    "target": target,
                    "args": {
                        "signal": "ai_complex_top.no_such_signal",
                        "time": "10ns",
                        "clock": "ai_complex_top.clk",
                    },
                },
                "SIGNAL_NOT_FOUND",
                "args.signal",
                "value.at",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "list.load",
                    "target": target,
                    "args": {
                        "config": {
                            "lists": [{
                                "name": "invalid_context",
                                "signals": [
                                    "ai_complex_top.no_such_signal"
                                ],
                            }],
                        },
                    },
                },
                "SIGNAL_NOT_FOUND",
                "args.config.lists[0].signals[0]",
                "list.load",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "verify.conditions",
                    "target": target,
                    "args": {
                        "clock": "ai_complex_top.clk",
                        "time": "10ns",
                        "signals": {"valid": "ai_complex_top.hs_valid"},
                        "conditions": [{"expr": "ai_complex_top.hs_valid"}],
                    },
                },
                "INVALID_ARGUMENT",
                "args.conditions[].expr",
                "verify.conditions",
            ),
        ]
        for request, code, invalid_arg, example_action in cases:
            result = cli_runner.run(request, output_format="json", timeout_sec=120)
            assert not result.ok, result.stdout_raw + result.stderr_raw
            error = result.response["error"]
            assert error["code"] == code
            assert error["error_layer"] == "handler"
            assert error["invalid_arg"] == invalid_arg
            assert "expected" in error
            assert "correct_example" in error
            assert error["correct_example"]["action"] == example_action
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_protocol_handler_errors_include_current_entry_examples(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
    tmp_path: Path,
) -> None:
    fsdb = complex_wave_fsdb
    session_name = "protocol_error_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        cases = [
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "axi.config.list",
                    "target": target,
                    "args": {"name": "missing_axi"},
                },
                "CONFIG_NOT_FOUND",
                "args.name",
                "axi.config.list",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.config.list",
                    "target": target,
                    "args": {"name": "missing_apb"},
                },
                "CONFIG_NOT_FOUND",
                "args.name",
                "apb.config.list",
            ),
            (
                {
                    "api_version": "xdebug.v1",
                    "action": "axi.export",
                    "target": target,
                    "args": {
                        "name": "missing_axi",
                        "time_range": {"begin": "0ns", "end": "10ns"},
                        "output": {
                            "path": str(tmp_path / "missing_axi.tsv"),
                            "file_format": "tsv",
                        },
                    },
                },
                "CONFIG_NOT_FOUND",
                "args.name",
                "axi.export",
            ),
        ]
        for request, code, invalid_arg, example_action in cases:
            result = cli_runner.run(request, output_format="json", timeout_sec=120)
            assert not result.ok, result.stdout_raw + result.stderr_raw
            error = result.response["error"]
            assert error["code"] == code
            assert error["error_layer"] == "handler"
            assert error["invalid_arg"] == invalid_arg
            assert "expected" in error
            assert "correct_example" in error
            assert error["correct_example"]["action"] == example_action
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
@pytest.mark.parametrize(
    "retired_action",
    [
        "cursor.set",
        "cursor.get",
        "cursor.list",
        "cursor.use",
        "cursor.delete",
        "apb.cursor",
        "axi.cursor",
        "detect_abnormal",
        "handshake.inspect",
        "sampled_pulse.inspect",
        "list.diff",
        "stream.show",
        "trace.x",
        "rc.generate",
        "source.context",
    ],
)
def test_retired_actions_have_no_runtime_alias(
    cli_runner: CliRunner,
    retired_action: str,
) -> None:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": retired_action,
        },
        output_format="json",
    )
    assert not result.ok
    assert result.response["error"]["code"] == "UNKNOWN_ACTION"
    assert result.response["error"]["error_layer"] == "handler"


@pytest.mark.contract
def test_nwave_rc_schema_errors_are_explicit(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
) -> None:
    fsdb = complex_wave_fsdb
    session_name = "rc_error_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        rc_result = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "nwave.rc.generate",
                "target": target,
                "args": {"config_path": "xdebug_missing_rc_config.json", "output": {}},
            },
            output_format="json",
            timeout_sec=120,
        )
        assert not rc_result.ok
        rc_error = rc_result.response["error"]
        assert rc_error["code"] == "INVALID_REQUEST"
        assert rc_error["error_layer"] == "schema"
        assert rc_error["invalid_arg"].startswith("args.output")
        assert "correct_example" in rc_error
        assert rc_error["schema_path"].endswith(
            "nwave.rc.generate.request.schema.json"
        )
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_rc_generate_emits_fixed_window_unit_marker_and_grouped_expression(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "wave_view.json"
    rc_path = tmp_path / "signal.rc"
    config_path.write_text(
        json.dumps(
            {
                "file_time_scale": "1ns",
                "groups": [
                    {"name": "G1", "signals": ["ai_complex_top.clk"]},
                    {
                        "name": "G2",
                        "expr_signals": [
                            {
                                "name": "req_fire",
                                "bit_size": 1,
                                "notation": "UU",
                                "expr": "$valid & $ready",
                                "signals": {
                                    "valid": "ai_complex_top.hs_valid",
                                    "ready": "ai_complex_top.hs_ready",
                                },
                            }
                        ],
                        "subgroups": [{"name": "SG"}],
                    },
                ],
                "user_markers": [
                    {
                        "name": "test",
                        "time": "10347.651ns",
                        "color": "ID_CYAN5",
                        "linestyle": "long_dashed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    session_name = "rc_render_contract"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(complex_wave_fsdb)},
            "args": {"name": session_name},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    try:
        result = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "nwave.rc.generate",
                "target": target,
                "args": {"config_path": str(config_path), "output": {"path": str(rc_path)}},
            },
            output_format="json",
            timeout_sec=120,
        )
        assert result.ok, result.stdout_raw + result.stderr_raw
        payload = result.response["data"]
        assert payload["rc_preview"][2] == "windowTimeUnit 1ns"
        assert payload["validation"] == {"signals": 3, "times": 1}
        lines = rc_path.read_text(encoding="utf-8").splitlines()
        statements = [line for line in lines if line and not line.startswith(";")]
        assert statements[0] == "windowTimeUnit 1ns"
        assert "userMarker 10347.651 test ID_CYAN5 long_dashed" in lines
        expr = lines.index('addExprSig -b 1 -n UU req_fire "/ai_complex_top/hs_valid" & "/ai_complex_top/hs_ready"')
        g2 = lines.index('addGroup "G2"')
        expr_signal = lines.index("addSignal -h 18 /req_fire")
        subgroup = lines.index('addSubGroup "SG"')
        assert expr < g2 < expr_signal < subgroup
        assert not any(
            line.startswith(("addGroup -e ", "addSubGroup -e "))
            for line in lines
        )
        assert not any(line.startswith("addExprSig") for line in lines[g2:])

        removed_config_path = tmp_path / "removed_expanded.json"
        removed_rc_path = tmp_path / "removed_expanded.rc"
        removed_config_path.write_text(
            json.dumps(
                {
                    "groups": [
                        {"name": "Removed", "expanded": True},
                    ]
                }
            ),
            encoding="utf-8",
        )
        removed = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "nwave.rc.generate",
                "target": target,
                "args": {
                    "config_path": str(removed_config_path),
                    "output": {"path": str(removed_rc_path)},
                },
            },
            output_format="json",
            timeout_sec=120,
        )
        assert not removed.ok
        error = removed.response["error"]
        assert error["code"] == "INVALID_ARGUMENT"
        assert error["invalid_arg"] == "args.config_path"
        assert error["cause_code"] == "PARSE_FAILED"
        assert "group.expanded is not supported" in error["message"]
        assert not removed_rc_path.exists()
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )


@pytest.mark.contract
def test_action_schemas_explain_purpose_and_required_args(xdebug_root: Path) -> None:
    specs = _load_json(xdebug_root / "specs" / "actions" / "actions.yaml")[
        "actions"
    ]
    for spec in specs:
        name = spec["name"]
        request_schema = _load_json(xdebug_root / spec["schemas"]["request"])
        response_schema = _load_json(xdebug_root / spec["schemas"]["response"])

        for key in ("description", "x-purpose", "x-how_it_works", "x-when_to_use"):
            assert request_schema.get(key), "%s request schema missing %s" % (
                name,
                key,
            )
        assert response_schema.get("description"), "%s response schema missing description" % name

        args_properties = (
            request_schema.get("properties", {})
            .get("args", {})
            .get("properties", {})
        )
        for key in _required_related_args(spec):
            assert args_properties.get(key, {}).get("description"), (
                "%s request schema missing args.%s description" % (name, key)
            )


@pytest.mark.contract
def test_runtime_modes_are_derived_from_action_categories(
    cli_runner: CliRunner,
) -> None:
    catalog = _runtime_catalog(cli_runner)
    expected = defaultdict(set)
    for descriptor in catalog["data"]["actions"]:
        expected[descriptor["category"]].add(descriptor["name"])
    actual = {
        category: set(actions)
        for category, actions in catalog["data"]["modes"].items()
    }
    for category in ("builtin", "session", "design", "waveform", "combined"):
        assert actual[category] == expected[category]


@pytest.mark.contract
def test_action_inventory_matches_specs(xdebug_root: Path) -> None:
    specs = _load_json(xdebug_root / "specs" / "actions" / "actions.yaml")[
        "actions"
    ]
    expected = {
        spec["name"]: (spec["category"], spec["status"], spec["requires"])
        for spec in specs
    }
    inventory_text = (xdebug_root / "docs" / "action-inventory.md").read_text(
        encoding="utf-8"
    )
    actual = {}
    row_pattern = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*([^\n|]+?)\s*\|\s*([^\n|]+?)\s*\|"
        r"\s*([^\n|]+?)\s*\|",
        re.MULTILINE,
    )
    for match in row_pattern.finditer(inventory_text):
        name, category, status, requires = (
            item.strip() for item in match.groups()
        )
        if category not in {"builtin", "session", "design", "waveform", "combined"}:
            continue
        actual[name] = (category, status, requires)
    assert actual == expected


@pytest.mark.contract
def test_runtime_schema_action_returns_exact_checked_in_schema(
    stateless_stdio_loop: StdioLoopRunner, xdebug_root: Path
) -> None:
    catalog_result = stateless_stdio_loop.request(
        {
            "api_version": "xdebug.v1",
            "action": "actions",
            "args": {"output": {"verbose": True}},
        }
    )
    assert catalog_result.ok, catalog_result.stderr_raw
    catalog = catalog_result.response
    for descriptor in catalog["data"]["actions"]:
        for kind in ("request", "response"):
            result = stateless_stdio_loop.request(
                {
                    "api_version": "xdebug.v1",
                    "action": "schema",
                    "args": {"action": descriptor["name"], "kind": kind},
                }
            )
            assert result.ok, (descriptor["name"], kind, result.response)
            schema_path = xdebug_root / descriptor["%s_schema" % kind]
            assert result.response["data"]["schema_path"] == descriptor[
                "%s_schema" % kind
            ]
            assert result.response["data"]["schema"] == _load_json(schema_path)


@pytest.mark.contract
def test_all_examples_validate_against_action_schemas(xdebug_root: Path) -> None:
    for kind in ("request", "response"):
        for example_path in sorted((xdebug_root / "examples" / (kind + "s")).glob("*.json")):
            example = _load_json(example_path)
            action = example["action"]
            schema = _load_json(
                xdebug_root
                / "schemas"
                / "v1"
                / "actions"
                / ("%s.%s.schema.json" % (action, kind))
            )
            jsonschema.Draft202012Validator(schema).validate(example)


@pytest.mark.contract
def test_stream_query_filter_schema_is_strict_and_match_field_is_removed(
    xdebug_root: Path,
) -> None:
    schema = _load_json(
        xdebug_root / "schemas" / "v1" / "actions" / "stream.query.request.schema.json"
    )
    validator = jsonschema.Draft202012Validator(schema)
    valid = {
        "api_version": "xdebug.v1",
        "action": "stream.query",
        "target": {"session_id": "strict-request-shape-session"},
        "args": {
            "stream": "req_stream",
            "query": "packet_window",
            "filter": {
                "position": "sop",
                "fields": {
                    "opcode": {"mode": "exact", "values": ["8'h5a", "8'h5b"]},
                    "length": {"mode": "range", "begin": "16'd1", "end": "16'd8"},
                    "data": {"mode": "mask", "value": "128'h1200", "mask": "128'hff00"},
                },
            },
        },
    }
    validator.validate(valid)

    legacy = {
        "api_version": "xdebug.v1",
        "action": "stream.query",
        "target": {"session_id": "strict-request-shape-session"},
        "args": {
            "stream": "req_stream",
            "query": "match_field",
            "match": {"field": "opcode", "op": "==", "value": "8'h5a"},
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(legacy)

    for invalid_filter in (
        {"fields": {}},
        {"fields": {"opcode": {"mode": "exact", "values": []}}},
        {"fields": {"opcode": {"mode": "range", "begin": "0", "end": "1", "mask": "1"}}},
        {"position": "middle", "fields": {"opcode": {"mode": "exact", "values": ["1"]}}},
    ):
        request = {
            "api_version": "xdebug.v1",
            "action": "stream.query",
            "target": {"session_id": "strict-request-shape-session"},
            "args": {"stream": "req_stream", "query": "summary", "filter": invalid_filter},
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(request)


@pytest.mark.contract
def test_stream_cache_scope_schema_is_explicit_and_protocol_local(
    xdebug_root: Path,
) -> None:
    target = {"session_id": "strict-request-shape-session"}

    def schema(action: str) -> dict[str, Any]:
        return _load_json(
            xdebug_root / "schemas" / "v1" / "actions" /
            ("%s.request.schema.json" % action)
        )

    for action in ("stream.query", "stream.export", "stream.validate"):
        args_schema = schema(action)["properties"]["args"]
        cache_scope = args_schema["properties"]["cache_scope"]
        assert cache_scope["enum"] == ["full", "range"]
        assert cache_scope["default"] == "full"
        assert "requires a non-empty time_range" in cache_scope["description"]

    query = jsonschema.Draft202012Validator(schema("stream.query"))
    query.validate({
        "api_version": "xdebug.v1", "action": "stream.query",
        "target": target,
        "args": {"stream": "req", "query": "summary",
                 "cache_scope": "range",
                 "time_range": {"begin": "10ns", "end": "20ns"}},
    })
    with pytest.raises(jsonschema.ValidationError):
        query.validate({
            "api_version": "xdebug.v1", "action": "stream.query",
            "target": target,
            "args": {"stream": "req", "query": "summary",
                     "cache_scope": "automatic"},
        })
    for action in ("stream.query", "stream.export"):
        validator = jsonschema.Draft202012Validator(schema(action))
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({
                "api_version": "xdebug.v1", "action": action,
                "target": target,
                "args": {
                    "stream": "req",
                    "cache_scope": "range",
                },
            })
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({
                "api_version": "xdebug.v1", "action": action,
                "target": target,
                "args": {
                    "stream": "req",
                    "cache_scope": "range",
                    "time_range": {},
                },
            })

    validate = jsonschema.Draft202012Validator(schema("stream.validate"))
    validate.validate({
        "api_version": "xdebug.v1", "action": "stream.validate",
        "target": target,
        "args": {"stream": "req", "dynamic": True,
                 "cache_scope": "range",
                 "time_range": {"begin": "10ns", "end": "20ns"}},
    })
    validate.validate({
        "api_version": "xdebug.v1", "action": "stream.validate",
        "target": target,
        "args": {"stream": "req", "dynamic": False},
    })
    with pytest.raises(jsonschema.ValidationError):
        validate.validate({
            "api_version": "xdebug.v1", "action": "stream.validate",
            "target": target,
            "args": {"stream": "req", "dynamic": False,
                     "cache_scope": "full"},
        })
    with pytest.raises(jsonschema.ValidationError):
        validate.validate({
            "api_version": "xdebug.v1", "action": "stream.validate",
            "target": target,
            "args": {"stream": "req", "dynamic": True,
                     "cache_scope": "range"},
        })

    for action in ("apb.query", "axi.query"):
        assert "cache_scope" not in \
            schema(action)["properties"]["args"]["properties"]


@pytest.mark.contract
def test_line_limit_and_scan_budget_request_contracts_are_strict(
    xdebug_root: Path,
) -> None:
    resource_target = {"session_id": "strict-request-shape-session"}

    def validator(action: str) -> jsonschema.Draft202012Validator:
        return jsonschema.Draft202012Validator(_load_json(
            xdebug_root / "schemas" / "v1" / "actions" /
            ("%s.request.schema.json" % action)
        ))

    event_find = validator("event.find")
    base_event = {
        "api_version": "xdebug.v1",
        "action": "event.find",
        "target": resource_target,
        "args": {"name": "evt", "expr": "valid"},
    }
    event_find.validate({
        **base_event,
        "args": {**base_event["args"], "mode": "all", "line_limit": 4,
                 "max_samples": 100},
    })
    for mode in ("first", "last"):
        with pytest.raises(jsonschema.ValidationError):
            event_find.validate({
                **base_event,
                "args": {**base_event["args"], "mode": mode, "line_limit": 4},
            })

    event_export = validator("event.export")
    event_export.validate({
        "api_version": "xdebug.v1",
        "action": "event.export",
        "target": resource_target,
        "args": {"name": "evt", "expr": "valid", "line_limit": 4,
                 "max_events": 1000, "max_samples": 10000},
    })

    handshake = validator("protocol.handshake.inspect")
    handshake.validate({
        "api_version": "xdebug.v1",
        "action": "protocol.handshake.inspect",
        "target": resource_target,
        "args": {"clock": "top.clk", "valid": "top.valid", "ready": "top.ready",
                 "rules": {"require_valid_hold_until_handshake": True}},
    })
    with pytest.raises(jsonschema.ValidationError):
        handshake.validate({
            "api_version": "xdebug.v1",
            "action": "protocol.handshake.inspect",
            "target": resource_target,
            "args": {"clock": "top.clk", "valid": "top.valid", "ready": "top.ready",
                     "rules": {"unknown_rule": True}},
        })

    sampled = validator("signal.sampled_pulse.inspect")
    sampled.validate({
        "api_version": "xdebug.v1",
        "action": "signal.sampled_pulse.inspect",
        "target": resource_target,
        "args": {"clock": "top.clk", "valid": "top.valid",
                 "payloads": ["top.payload"],
                 "rules": {"payload_changed_without_sampled_valid": "summary"}},
    })

    scope = validator("scope.list")
    scope.validate({
        "api_version": "xdebug.v1",
        "action": "scope.list",
        "target": resource_target,
        "args": {
            "source": "wave",
            "path": "top",
            "level": 1,
            "kind": "port",
            "include_patterns": ["u_*.*"],
            "exclude_patterns": ["*debug*"],
        },
    })
    scope.validate({
        "api_version": "xdebug.v1",
        "action": "scope.list",
        "target": {"daidir": "simv.daidir"},
        "args": {"source": "design", "kind": "gen_scope"},
    })
    scope.validate({
        "api_version": "xdebug.v1",
        "action": "scope.list",
        "target": {"daidir": "simv.daidir", "fsdb": "waves.fsdb"},
        "args": {"source": "merged", "kind": "mpport"},
    })
    for args, target in (
        ({"source": "wave"}, {"daidir": "simv.daidir"}),
        ({"source": "design"}, {"fsdb": "waves.fsdb"}),
        ({"source": "merged"}, {"daidir": "simv.daidir"}),
    ):
        with pytest.raises(jsonschema.ValidationError):
            scope.validate({
                "api_version": "xdebug.v1",
                "action": "scope.list",
                "target": target,
                "args": args,
            })
    for legacy_args in (
        {"recursive": True},
        {"max_depth": 2},
        {"name_pattern": "top.*"},
    ):
        with pytest.raises(jsonschema.ValidationError):
            scope.validate({
                "api_version": "xdebug.v1",
                "action": "scope.list",
                "target": resource_target,
                "args": legacy_args,
            })
    with pytest.raises(jsonschema.ValidationError):
        scope.validate({
            "api_version": "xdebug.v1",
            "action": "scope.list",
            "target": resource_target,
            "args": {"level": -1},
        })

    for action in ("expr.eval_at", "signal.stability"):
        assert "line_limit" not in (
            validator(action).schema["properties"]["args"]["properties"]
        )

    axi_analysis = validator("axi.analysis")
    with pytest.raises(jsonschema.ValidationError):
        axi_analysis.validate({
            "api_version": "xdebug.v1", "action": "axi.analysis",
            "target": resource_target,
            "args": {"name": "axi0", "analysis": "latency", "line_limit": 8},
        })


@pytest.mark.contract
def test_ai_usability_high_risk_request_shapes_are_strict(
    xdebug_root: Path,
) -> None:
    resource_target = {"session_id": "strict-request-shape-session"}

    def schema_for(action: str) -> Dict[str, Any]:
        return _load_json(
            xdebug_root
            / "schemas"
            / "v1"
            / "actions"
            / ("%s.request.schema.json" % action)
        )

    apb = jsonschema.Draft202012Validator(schema_for("apb.query"))
    apb.validate({
        "api_version": "xdebug.v1",
        "action": "apb.query",
        "target": resource_target,
        "args": {"name": "apb0", "direction": "read", "query": {"index": 1, "line_limit": 1}},
    })
    with pytest.raises(jsonschema.ValidationError):
        apb.validate({
            "api_version": "xdebug.v1",
            "action": "apb.query",
            "target": resource_target,
            "args": {"name": "apb0", "direction": "read", "num": 1},
        })
    with pytest.raises(jsonschema.ValidationError):
        apb.validate({
            "api_version": "xdebug.v1",
            "action": "apb.query",
            "target": resource_target,
            "args": {"name": "apb0", "direction": "read", "limit": 1},
        })
    with pytest.raises(jsonschema.ValidationError):
        apb.validate({
            "api_version": "xdebug.v1",
            "action": "apb.query",
            "target": resource_target,
            "args": {"name": "apb0", "direction": "read", "query": {"limit": 1}},
        })
    apb.validate({
        "api_version": "xdebug.v1",
        "action": "apb.query",
        "target": resource_target,
        "args": {"name": "apb0", "direction": "all"},
    })

    apb_load = jsonschema.Draft202012Validator(schema_for("apb.config.load"))
    required_apb = {
        key: "top." + key
        for key in (
            "clock", "paddr", "psel", "penable",
            "pwrite", "pwdata", "prdata",
        )
    }
    required_apb["reset"] = {"signal": "top.rst_n", "polarity": "active_low"}
    apb_load.validate({
        "api_version": "xdebug.v1", "action": "apb.config.load",
        "target": resource_target,
        "args": {"name": "apb0", "config": required_apb},
    })
    for optional in ("pready", "pslverr"):
        with_optional = dict(required_apb)
        with_optional[optional] = "top." + optional
        apb_load.validate({
            "api_version": "xdebug.v1", "action": "apb.config.load",
            "target": resource_target,
            "args": {"name": "apb0", "config": with_optional},
        })
        empty_optional = dict(required_apb)
        empty_optional[optional] = ""
        with pytest.raises(jsonschema.ValidationError):
            apb_load.validate({
                "api_version": "xdebug.v1", "action": "apb.config.load",
                "target": resource_target,
                "args": {"name": "apb0", "config": empty_optional},
            })
    missing_core = dict(required_apb)
    missing_core.pop("penable")
    with pytest.raises(jsonschema.ValidationError):
        apb_load.validate({
            "api_version": "xdebug.v1", "action": "apb.config.load",
            "target": resource_target,
            "args": {"name": "apb0", "config": missing_core},
        })
    apb_load_response = jsonschema.Draft202012Validator(
        _load_json(
            xdebug_root
            / "schemas"
            / "v1"
            / "actions"
            / "apb.config.load.response.schema.json"
        )
    )
    apb_load_response.validate({
        "api_version": "xdebug.v1",
        "ok": True,
        "action": "apb.config.load",
        "tool": {"name": "xdebug", "version": "test"},
        "session": None,
        "summary": {"name": "apb0", "status": "loaded"},
        "data": {
            "config": {
                "name": "apb0",
                "sampling_mode": "clock_edge",
                "clock": "top.clock",
                "edge": "negedge",
                "reset": {
                    "signal": "top.rst_n",
                    "polarity": "active_low",
                },
                "paddr": "top.paddr",
                "psel": "top.psel",
                "penable": "top.penable",
                "pwrite": "top.pwrite",
                "pwdata": "top.pwdata",
                "prdata": "top.prdata",
            },
            "recommended_actions": [
                {"action": "value.at", "purpose": "按一个或多个指定时间读取单信号、命名信号列表或接口配置维护的值。"},
                {"action": "apb.query", "purpose": "查询 APB transfer。"},
                {"action": "apb.transaction.cursor", "purpose": "在 APB transfer 间移动游标。"},
                {"action": "apb.statistics", "purpose": "按方向和地址过滤统计已完成 APB 事务。"},
                {"action": "apb.transfer_window", "purpose": "实验性 APB 窗口分析。"},
            ],
        },
        "error": None,
    })

    axi_load = jsonschema.Draft202012Validator(schema_for("axi.config.load"))
    with pytest.raises(jsonschema.ValidationError):
        axi_load.validate({
            "api_version": "xdebug.v1", "action": "axi.config.load",
            "target": resource_target,
            "args": {"name": "axi0", "config": {"clock": "top.clk"}},
        })

    actions = jsonschema.Draft202012Validator(schema_for("actions"))
    actions.validate({
        "api_version": "xdebug.v1", "action": "actions",
        "args": {"filter": {"category": ["waveform"],
                            "purposes": ["query", "inspect"], "keyword": "AXI"}},
    })
    with pytest.raises(jsonschema.ValidationError):
        actions.validate({
            "api_version": "xdebug.v1", "action": "actions",
            "args": {"filter": {"status": ["stable"]}},
        })
    with pytest.raises(jsonschema.ValidationError):
        actions.validate({
            "api_version": "xdebug.v1", "action": "actions",
            "args": {"filter": {"purposes": []}},
        })

    stream_config = jsonschema.Draft202012Validator(schema_for("stream.config.load"))
    with pytest.raises(jsonschema.ValidationError):
        stream_config.validate({
            "api_version": "xdebug.v1", "action": "stream.config.load",
            "target": resource_target,
            "args": {"config": {"streams": [{"name": "s", "signals": {"clk": "top.clk", "v": "top.v"},
                                  "clock": "clk", "vld": "v",
                                  "stable_fields": {"opcode": "v"}}]}},
        })
    with pytest.raises(jsonschema.ValidationError):
        stream_config.validate({
            "api_version": "xdebug.v1", "action": "stream.config.load",
            "target": resource_target,
            "args": {"config": {"streams": [{"name": "s", "signals": {"clk": "top.clk", "v": "top.v"},
                                  "clock": "clk", "vld": "v",
                                  "data_fields": {"payload": "v"}}]}},
        })
    stream_config.validate({
        "api_version": "xdebug.v1", "action": "stream.config.load",
        "target": resource_target,
        "args": {"config": {"streams": [{"name": "s", "signals": {"clk": "top.clk", "v": "top.v"},
                              "clock": "clk", "vld": "v",
                              "beat_fields": {"payload": "v"}}]}},
    })

    axi = jsonschema.Draft202012Validator(schema_for("axi.query"))
    axi.validate({
        "api_version": "xdebug.v1",
        "action": "axi.query",
        "target": resource_target,
        "args": {"name": "axi0", "direction": "write", "query": {"index": 1, "line_limit": 1}},
    })
    axi.validate({
        "api_version": "xdebug.v1",
        "action": "axi.query",
        "target": resource_target,
        "args": {
            "name": "axi0",
            "query": {"channel": "w", "handshake_time": "110ns"},
            "output": {"include_data": True},
        },
    })
    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1",
            "action": "axi.query",
            "target": resource_target,
            "args": {"name": "axi0", "direction": "write", "num": 1},
        })
    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1",
            "action": "axi.query",
            "target": resource_target,
            "args": {"name": "axi0", "direction": "write", "query": {"limit": 1}},
        })
    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1",
            "action": "axi.query",
            "target": resource_target,
            "args": {"name": "axi0", "direction": "all"},
        })
    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1",
            "action": "axi.query",
            "target": resource_target,
            "args": {
                "name": "axi0", "query": {"index": 1},
                "output": {"verbose": True},
            },
        })
    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1",
            "action": "axi.query",
            "target": resource_target,
            "args": {"name": "axi0", "query": {"channel": "w"}},
        })
    with pytest.raises(jsonschema.ValidationError):
        axi.validate({
            "api_version": "xdebug.v1",
            "action": "axi.query",
            "target": resource_target,
            "args": {
                "name": "axi0", "direction": "write",
                "query": {"channel": "w", "handshake_time": "110ns"},
            },
        })

    stream_export = jsonschema.Draft202012Validator(schema_for("stream.export"))
    stream_export.validate({
        "api_version": "xdebug.v1",
        "action": "stream.export",
        "target": resource_target,
        "args": {"stream": "ready_stream", "kind": "packet_beats",
                 "output": {"path": "artifacts/ready.tsv", "file_format": "tsv"}},
    })
    with pytest.raises(jsonschema.ValidationError):
        stream_export.validate({
            "api_version": "xdebug.v1",
            "action": "stream.export",
            "target": resource_target,
            "args": {"stream": "ready_stream", "kind": "packet_beats",
                     "format": "tsv", "output": {"path": "artifacts/ready.tsv"}},
        })
    with pytest.raises(jsonschema.ValidationError):
        stream_export.validate({
            "api_version": "xdebug.v1",
            "action": "stream.export",
            "target": resource_target,
            "args": {"stream": "ready_stream", "kind": "beats",
                     "output": {"path": "artifacts/ready.tsv", "file_format": "tsv"}},
        })

    stream_config_list = jsonschema.Draft202012Validator(schema_for("stream.config.list"))
    stream_config_list.validate({
        "api_version": "xdebug.v1",
        "action": "stream.config.list",
        "target": resource_target,
        "args": {"output": {"verbose": True}},
    })
    with pytest.raises(jsonschema.ValidationError):
        stream_config_list.validate({
            "api_version": "xdebug.v1",
            "action": "stream.config.list",
            "target": resource_target,
            "args": {"verbose": True},
        })

    list_export = jsonschema.Draft202012Validator(schema_for("list.export"))
    list_export.validate({
        "api_version": "xdebug.v1",
        "action": "list.export",
        "target": resource_target,
        "args": {"name": "basic", "time_range": {"begin": "0ns", "end": "400ns"},
                 "output": {"path": "artifacts/basic", "file_format": "u64bin"}},
    })
    with pytest.raises(jsonschema.ValidationError):
        list_export.validate({
            "api_version": "xdebug.v1",
            "action": "list.export",
            "target": resource_target,
            "args": {"name": "basic", "format": "tsv",
                     "time_range": {"begin": "0ns", "end": "400ns"}},
        })

    axi_export = jsonschema.Draft202012Validator(schema_for("axi.export"))
    axi_export.validate({
        "api_version": "xdebug.v1",
        "action": "axi.export",
        "target": resource_target,
        "args": {"name": "axi0", "time_range": {"begin": "0ns", "end": "400ns"},
                 "output": {"path": "artifacts/axi0", "file_format": "tsv"}},
    })
    with pytest.raises(jsonschema.ValidationError):
        axi_export.validate({
            "api_version": "xdebug.v1",
            "action": "axi.export",
            "target": resource_target,
            "args": {"name": "axi0", "time_range": {"begin": "0ns", "end": "400ns"},
                     "format": "tsv", "output": {"path": "artifacts/axi0"}},
        })

    for action in ("apb.config.list", "axi.config.list", "event.config.list"):
        config_list = jsonschema.Draft202012Validator(schema_for(action))
        config_list.validate({
            "api_version": "xdebug.v1",
            "action": action,
            "target": resource_target,
        })
        config_list.validate({
            "api_version": "xdebug.v1",
            "action": action,
            "target": resource_target,
            "args": {"name": "if0"},
        })

    stream_config_list = jsonschema.Draft202012Validator(
        schema_for("stream.config.list")
    )
    stream_config_list.validate({
        "api_version": "xdebug.v1",
        "action": "stream.config.list",
        "target": resource_target,
    })
    with pytest.raises(jsonschema.ValidationError):
        stream_config_list.validate({
            "api_version": "xdebug.v1",
            "action": "stream.config.list",
            "target": resource_target,
            "args": {"name": "if0"},
        })

    stream_config_get = jsonschema.Draft202012Validator(
        schema_for("stream.config.get")
    )
    stream_config_get.validate({
        "api_version": "xdebug.v1",
        "action": "stream.config.get",
        "target": resource_target,
        "args": {"name": "if0"},
    })
    with pytest.raises(jsonschema.ValidationError):
        stream_config_get.validate({
            "api_version": "xdebug.v1",
            "action": "stream.config.get",
            "target": resource_target,
            "args": {},
        })

    list_delete = jsonschema.Draft202012Validator(schema_for("list.delete"))
    list_delete.validate({
        "api_version": "xdebug.v1",
        "action": "list.delete",
        "target": resource_target,
        "args": {"name": "basic", "index": 2},
    })
    list_delete.validate({
        "api_version": "xdebug.v1",
        "action": "list.delete",
        "target": resource_target,
        "args": {"name": "basic", "signal": "2"},
    })
    for invalid_args in (
        {"name": "basic"},
        {"name": "", "index": 1},
        {"name": "basic", "signal": ""},
        {"name": "basic", "index": "2"},
        {"name": "basic", "index": 0},
        {"name": "basic", "index": -1},
        {"name": "basic", "index": {"bad": 2}},
        {"name": "basic", "signal": "2", "index": 1},
    ):
        with pytest.raises(jsonschema.ValidationError):
            list_delete.validate({
                "api_version": "xdebug.v1",
                "action": "list.delete",
                "target": resource_target,
                "args": invalid_args,
            })

    active_chain_schema = schema_for("trace.active_driver_chain")
    active_chain_limits = active_chain_schema["properties"]["limits"]["properties"]
    assert active_chain_limits["max_depth"]["default"] == 8
    assert set(active_chain_limits) == {
        "max_depth",
        "max_nodes",
        "max_results",
        "max_trace_signals",
        "timeout_ms",
    }
    active_chain = jsonschema.Draft202012Validator(active_chain_schema)
    with pytest.raises(jsonschema.ValidationError):
        active_chain.validate({
            "api_version": "xdebug.v1",
            "action": "trace.active_driver_chain",
            "target": resource_target,
            "args": {"signal": "top.q", "time": "10ns", "depth": 4},
        })
    with pytest.raises(jsonschema.ValidationError):
        active_chain.validate({
            "api_version": "xdebug.v1",
            "action": "trace.active_driver_chain",
            "target": resource_target,
            "args": {"signal": "top.q", "time": "10ns",
                     "limits": {"max_depth": 4}},
        })
    with pytest.raises(jsonschema.ValidationError):
        active_chain.validate({
            "api_version": "xdebug.v1",
            "action": "trace.active_driver_chain",
            "target": resource_target,
            "args": {"signal": "top.q", "time": "10ns", "clk_period": "10ns"},
        })
    with pytest.raises(jsonschema.ValidationError):
        active_chain.validate({
            "api_version": "xdebug.v1",
            "action": "trace.active_driver_chain",
            "target": resource_target,
            "args": {"signal": "top.q", "time": "10ns"},
            "limits": {"max_alias_candidates": 8},
        })
    active_chain.validate({
        "api_version": "xdebug.v1",
        "action": "trace.active_driver_chain",
        "target": resource_target,
        "args": {"signal": "top.q", "time": "10ns"},
        "limits": {
            "max_depth": 4,
            "max_nodes": 20,
            "max_trace_signals": 16,
        },
    })

    active_driver = jsonschema.Draft202012Validator(
        schema_for("trace.active_driver"))
    with pytest.raises(jsonschema.ValidationError):
        active_driver.validate({
            "api_version": "xdebug.v1",
            "action": "trace.active_driver",
            "target": resource_target,
            "args": {"signal": "top.q", "time": "10ns"},
            "limits": {"max_alias_candidates": 8},
        })


@pytest.mark.contract
def test_response_examples_do_not_encode_removed_redundant_payloads(
    xdebug_root: Path,
) -> None:
    response_dir = xdebug_root / "examples" / "responses"
    cases = {
        "scope.list.basic.json": ["data.signals_preview", "data.examples"],
        "event.find.basic.json": ["data.examples"],
        "event.export.basic.json": ["data.examples"],
        "verify.conditions.basic.json": ["data.results", "data.examples"],
        "list.create.basic.json": ["data.summary", "data.examples"],
        "list.add.basic.json": ["data.summary", "data.examples"],
        "list.delete.basic.json": ["data.summary", "data.examples"],
        "list.show.basic.json": ["data.count", "data.summary", "data.examples"],
        "value.at.list.json": ["data.summary", "data.examples"],
        "list.validate.basic.json": ["data.summary", "data.examples"],
        "list.first_change.basic.json": ["data.time", "data.summary", "data.examples"],
        "list.export.basic.json": ["data.summary", "data.examples"],
        "trace.active_driver_chain.basic.json": ["data.text", "data.chain.text"],
    }
    for filename, forbidden_paths in cases.items():
        example = _load_json(response_dir / filename)
        for dotted_path in forbidden_paths:
            current = example
            found = True
            for part in dotted_path.split("."):
                if not isinstance(current, dict) or part not in current:
                    found = False
                    break
                current = current[part]
            assert not found, "%s must not contain %s" % (filename, dotted_path)


@pytest.mark.contract
@pytest.mark.parametrize("action", ["actions", "schema", "batch"])
def test_safe_request_examples_execute_with_real_binary(
    cli_runner: CliRunner, xdebug_root: Path, action: str
) -> None:
    request = _load_json(
        xdebug_root / "examples" / "requests" / ("%s.basic.json" % action)
    )
    result = cli_runner.run(request, output_format="json")
    assert result.ok, result.response
    response_schema = _load_json(
        xdebug_root
        / "schemas"
        / "v1"
        / "actions"
        / ("%s.response.schema.json" % action)
    )
    jsonschema.Draft202012Validator(response_schema).validate(result.response)
