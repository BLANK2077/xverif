from __future__ import annotations

import copy
import functools
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator


XDEBUG = Path(__file__).resolve().parents[2]
GENERATOR_PATH = XDEBUG / "tools" / "sync_response_schemas.py"
RUNTIME_VALIDATOR_PATH = (
    XDEBUG / "src" / "core" / "schema" / "runtime_schema_validator.cpp"
)


def _generator():
    spec = importlib.util.spec_from_file_location(
        "xdebug_validation_issue_response_generator",
        GENERATOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=1)
def _catalog() -> tuple[Any, dict[str, dict[str, Any]]]:
    generator = _generator()
    return (
        generator,
        generator.build_response_schema_catalog(
            generator.load_action_entries()
        ),
    )


def _error_response(
    action: str,
    *,
    validation_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": "INVALID_REQUEST",
        "message": "request schema validation failed",
        "recoverable": True,
        "error_layer": "schema",
    }
    if validation_issues is not None:
        error["validation_issues"] = validation_issues
    return {
        "api_version": "xdebug.v1",
        "ok": False,
        "action": action,
        "tool": {"name": "xdebug", "version": "test"},
        "session": None,
        "summary": {
            "status": "error",
            "error_code": "INVALID_REQUEST",
        },
        "data": None,
        "error": error,
    }


def _canonical_issues() -> list[dict[str, str]]:
    return [
        {
            "path": "args.signals",
            "message": "required property is missing",
        },
        {
            "path": "args.__bad_param__",
            "message": "additional property is not allowed",
        },
    ]


def _invalid_issue_arrays() -> list[list[Any]]:
    issues = _canonical_issues()
    missing_path = copy.deepcopy(issues)
    del missing_path[0]["path"]
    missing_message = copy.deepcopy(issues)
    del missing_message[0]["message"]
    empty_path = copy.deepcopy(issues)
    empty_path[0]["path"] = ""
    empty_message = copy.deepcopy(issues)
    empty_message[0]["message"] = ""
    unknown_field = copy.deepcopy(issues)
    unknown_field[0]["schema_keyword"] = "required"
    return [
        [],
        missing_path,
        missing_message,
        empty_path,
        empty_message,
        unknown_field,
        ["not-an-object"],
    ]


def _ref_name(reference: str) -> str:
    prefix = "#/$defs/"
    assert reference.startswith(prefix)
    return reference[len(prefix) :].replace("~1", "/").replace("~0", "~")


def _local_refs(value: Any) -> set[str]:
    if isinstance(value, list):
        return set().union(*(_local_refs(item) for item in value), set())
    if not isinstance(value, dict):
        return set()
    references: set[str] = set()
    reference = value.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        references.add(_ref_name(reference))
    for child in value.values():
        references.update(_local_refs(child))
    return references


def _definition_closure(
    definitions: dict[str, dict[str, Any]],
    root_name: str,
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    pending = {root_name}
    while pending:
        name = pending.pop()
        assert name in definitions
        if name in selected:
            continue
        selected[name] = definitions[name]
        pending.update(_local_refs(definitions[name]) - set(selected))
    return selected


def _error_response_projection(
    schema: dict[str, Any],
) -> dict[str, Any]:
    if "oneOf" not in schema:
        return schema

    error_branches = [
        branch
        for branch in schema["oneOf"]
        if branch.get("properties", {}).get("ok", {}).get("const") is False
    ]
    assert len(error_branches) == 1
    projected = {
        "$schema": schema["$schema"],
        "type": schema["type"],
        "properties": schema["properties"],
        "required": schema["required"],
        "oneOf": error_branches,
        "additionalProperties": schema["additionalProperties"],
    }
    definitions = schema["$defs"]
    selected: dict[str, dict[str, Any]] = {}
    for root_name in _local_refs(projected):
        selected.update(_definition_closure(definitions, root_name))
    projected["$defs"] = selected
    return projected


def test_validation_issue_is_one_closed_canonical_definition() -> None:
    generator = _generator()
    expected = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
        },
        "required": ["message", "path"],
        "additionalProperties": False,
    }
    assert generator.validation_issue_schema() == expected

    generic = generator.generic_error_response_schema()
    assert generic["$defs"]["validationIssue"] == expected
    assert generic["$defs"]["error"]["properties"]["validation_issues"] == {
        "type": "array",
        "items": {"$ref": "#/$defs/validationIssue"},
        "minItems": 1,
    }


def test_generic_and_every_action_error_accept_only_strict_issues() -> None:
    generator, schemas = _catalog()
    expected = generator.validation_issue_schema()
    for action, schema in schemas.items():
        assert schema["$defs"]["validationIssue"] == expected, action
        for definition_name in ("error",):
            assert schema["$defs"][definition_name]["properties"][
                "validation_issues"
            ] == {
                "type": "array",
                "items": {"$ref": "#/$defs/validationIssue"},
                "minItems": 1,
            }, (action, definition_name)

    representatives = {
        "__generic__": generator.generic_error_response_schema(),
        "actions": schemas["actions"],
        "signal.canonicalize": schemas["signal.canonicalize"],
        "batch": schemas["batch"],
    }
    for action, schema in representatives.items():
        response_action = (
            "unknown.action" if action == "__generic__" else action
        )
        valid = _error_response(response_action, validation_issues=_canonical_issues())
        error_schema = _error_response_projection(schema)
        for validator_class in (Draft7Validator, Draft202012Validator):
            validator_class.check_schema(error_schema)
            validator = validator_class(error_schema)
            validator.validate(valid)
            for invalid_issues in _invalid_issue_arrays():
                invalid = copy.deepcopy(valid)
                invalid["error"]["validation_issues"] = invalid_issues
                assert not validator.is_valid(invalid), (
                    action,
                    validator_class.__name__,
                    invalid_issues,
                )


def test_every_batch_child_error_keeps_the_namespaced_issue_contract() -> None:
    generator, schemas = _catalog()
    entries = generator.load_action_entries()
    batch_schema = schemas["batch"]
    definitions = batch_schema["$defs"]
    expected = generator.validation_issue_schema()

    non_batch_actions = {
        entry["name"] for entry in entries if entry["name"] != "batch"
    }
    child_roots: dict[str, tuple[str, dict[str, Any]]] = {}
    for name, definition in definitions.items():
        action = (
            definition.get("properties", {})
            .get("action", {})
            .get("const")
        )
        if action in non_batch_actions and "oneOf" in definition:
            child_roots[action] = (name, definition)
    assert set(child_roots) == non_batch_actions

    for action, (root_name, root) in child_roots.items():
        stem = root_name.removesuffix("__response")
        assert root_name.endswith("__response"), action
        issue_name = f"{stem}__validationIssue"
        error_name = f"{stem}__error"
        assert definitions[issue_name] == expected, action
        for candidate in (error_name,):
            issue_array = definitions[candidate]["properties"][
                "validation_issues"
            ]
            assert issue_array == {
                "type": "array",
                "items": {"$ref": f"#/$defs/{issue_name}"},
                "minItems": 1,
            }, (action, candidate)
        error_branches = [
            branch
            for branch in root["oneOf"]
            if branch["properties"]["ok"].get("const") is False
        ]
        assert len(error_branches) == 1, action
        assert (
            _ref_name(
                error_branches[0]["properties"]["error"]["$ref"]
            )
            == error_name
        )

    child = _error_response(
        "session.list",
        validation_issues=_canonical_issues(),
    )
    child_root_name = child_roots["session.list"][0]
    child_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": _definition_closure(definitions, child_root_name),
        "$ref": f"#/$defs/{child_root_name}",
    }
    for validator_class in (Draft7Validator, Draft202012Validator):
        validator_class.check_schema(child_schema)
        validator = validator_class(child_schema)
        validator.validate(child)
        for invalid_issues in _invalid_issue_arrays():
            invalid = copy.deepcopy(child)
            invalid["error"]["validation_issues"] = invalid_issues
            assert not validator.is_valid(invalid), (
                validator_class.__name__,
                invalid_issues,
            )


def test_runtime_multi_issue_publisher_uses_exact_nonempty_fields() -> None:
    source = RUNTIME_VALIDATOR_PATH.read_text(encoding="utf-8")
    push = re.search(
        r"issues\.push_back\s*\(\s*\{"
        r'\s*\{\s*"path"\s*,\s*'
        r"pointer_to_arg_path\s*\(\s*issue\.pointer\s*\)\s*\}\s*,"
        r'\s*\{\s*"message"\s*,\s*issue\.message\s*\}\s*,?'
        r"\s*\}\s*\)\s*;",
        source,
        re.DOTALL,
    )
    assert push is not None
    assert re.search(
        r"if\s*\(\s*issues\.size\s*\(\s*\)\s*>\s*1\s*\)"
        r'\s*\{\s*failure\.error\s*\[\s*"validation_issues"\s*\]'
        r"\s*=\s*issues\s*;",
        source,
        re.DOTALL,
    )


def test_operational_error_contracts_are_strict_and_actionable() -> None:
    generator = _generator()
    schema = generator.generic_error_response_schema()
    for validator_class in (Draft7Validator, Draft202012Validator):
        validator = validator_class(schema)
        for name in (
            "request_too_large.error.json",
            "invalid_config.error.json",
        ):
            response = json.loads(
                (XDEBUG / "examples" / "errors" / name).read_text(
                    encoding="utf-8"
                )
            )
            validator.validate(response)
            missing_evidence = copy.deepcopy(response)
            if response["error"]["code"] == "REQUEST_TOO_LARGE":
                missing_evidence["error"].pop("max_bytes")
            else:
                missing_evidence["error"].pop("config_key")
            assert not validator.is_valid(missing_evidence)

            retryable = copy.deepcopy(response)
            retryable["error"]["recoverable"] = True
            assert not validator.is_valid(retryable)
