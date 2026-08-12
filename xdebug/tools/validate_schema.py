#!/usr/bin/env python3
"""Parse and sanity-check xdebug JSON schema files.

This intentionally avoids third-party dependencies. It validates schema files
well enough to catch malformed JSON and common authoring mistakes before the
runtime contract tests run.
"""

import json
import sys
from pathlib import Path
from typing import Any, List


ALLOWED_TYPES = {
    "array",
    "boolean",
    "integer",
    "null",
    "number",
    "object",
    "string",
}

LEGACY_RESPONSE_COMPLETENESS_FIELDS = {"truncated", "truncation_scope"}
RETIRED_RESPONSE_FIELDS = {
    "driver_last_change_time",
}
RETIRED_ERROR_SUGGESTION_FIELDS = {
    "allowed_values",
    "candidates",
    "suggested_actions",
    "suggestions",
}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def check_schema_node(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        return
    if "type" in node:
        types = node["type"]
        if isinstance(types, str):
            types = [types]
        if not isinstance(types, list) or not all(t in ALLOWED_TYPES for t in types):
            fail(f"{path}: invalid type {node['type']!r}")
    if "required" in node:
        required = node["required"]
        if not isinstance(required, list) or not all(isinstance(v, str) for v in required):
            fail(f"{path}: required must be a string array")
    if "enum" in node:
        enum = node["enum"]
        if not isinstance(enum, list) or not enum:
            fail(f"{path}: enum must be a non-empty array")
    if "properties" in node:
        props = node["properties"]
        if not isinstance(props, dict):
            fail(f"{path}: properties must be an object")
        for name, child in props.items():
            check_schema_node(child, f"{path}.properties.{name}")
    if "items" in node:
        check_schema_node(node["items"], f"{path}.items")


def check_strict_response_node(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        return
    if not node:
        fail(f"{path}: empty response schema node is forbidden")
    if node.get("type") == "object":
        additional = node.get("additionalProperties")
        dynamic_map = node.get("x-dynamic-map") is True
        if additional is not False:
            if not dynamic_map or not isinstance(additional, dict) or not additional:
                fail(
                    f"{path}: response object must be closed or an explicitly "
                    "typed x-dynamic-map"
                )
    properties = node.get("properties")
    if isinstance(properties, dict):
        retired_fields = (
            LEGACY_RESPONSE_COMPLETENESS_FIELDS | RETIRED_RESPONSE_FIELDS
        )
        if ".$defs.error" in path or ".$defs.genericError" in path:
            retired_fields |= RETIRED_ERROR_SUGGESTION_FIELDS
        retired = retired_fields.intersection(properties)
        if retired:
            fail(
                f"{path}: retired response fields are forbidden: "
                f"{sorted(retired)}"
            )
    for key, child in node.items():
        if key in {"properties", "$defs", "patternProperties"}:
            if isinstance(child, dict):
                for name, schema in child.items():
                    check_strict_response_node(
                        schema,
                        f"{path}.{key}.{name}",
                    )
            continue
        if isinstance(child, dict):
            check_strict_response_node(child, f"{path}.{key}")
        elif isinstance(child, list):
            for index, item in enumerate(child):
                check_strict_response_node(item, f"{path}.{key}[{index}]")


def check_strict_request_node(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        additional = node.get("additionalProperties")
        if additional is not False:
            typed_dynamic_map = (
                node.get("x-dynamic-map") is True
                and isinstance(additional, dict)
                and additional
            )
            deferred_action_validation = (
                node.get("x-deferred-action-validation") is True
                and isinstance(node.get("description"), str)
                and bool(node["description"].strip())
            )
            if not typed_dynamic_map and not deferred_action_validation:
                fail(
                    f"{path}: request object must be closed or an explicitly "
                    "typed x-dynamic-map/deferred action payload"
                )
    for key, child in node.items():
        if isinstance(child, dict):
            check_strict_request_node(child, f"{path}.{key}")
        elif isinstance(child, list):
            for index, item in enumerate(child):
                check_strict_request_node(item, f"{path}.{key}[{index}]")


def check_action_request_schema(schema: dict[str, Any], path: str) -> None:
    if schema.get("additionalProperties") is not False:
        fail(f"{path}: action request envelope must close unknown fields")
    required = set(schema.get("required", []))
    missing = {"api_version", "action"} - required
    if missing:
        fail(f"{path}: request envelope missing required fields {sorted(missing)}")
    forbidden = {
        "id",
        "trace_id",
        "span_id",
        "parent_span_id",
        "auth_token",
        "output",
    }
    leaked = forbidden.intersection(schema.get("properties", {}))
    if leaked:
        fail(f"{path}: transport/output fields leaked into public request: {sorted(leaked)}")
    check_strict_request_node(schema, path)


def check_action_response_schema(schema: dict[str, Any], path: str) -> None:
    if schema.get("additionalProperties") is not False:
        fail(f"{path}: action response envelope must close unknown fields")
    required = set(schema.get("required", []))
    missing = {"api_version", "ok", "action", "summary", "data"} - required
    if missing:
        fail(f"{path}: response envelope missing required fields {sorted(missing)}")
    if len(schema.get("oneOf", [])) != 2:
        fail(f"{path}: response envelope must have strict success/error branches")
    notes = schema.get("x-output_notes")
    if not isinstance(notes, str) or "具体字段以 response schema" in notes:
        fail(f"{path}: x-output_notes must describe the action-specific shape")
    check_strict_response_node(schema, path)


def check_generic_error_response_schema(schema: dict[str, Any], path: str) -> None:
    if schema.get("additionalProperties") is not False:
        fail(f"{path}: generic error envelope must close unknown fields")
    required = set(schema.get("required", []))
    missing = {
        "api_version",
        "ok",
        "action",
        "summary",
        "data",
        "error",
    } - required
    if missing:
        fail(f"{path}: generic error envelope missing fields {sorted(missing)}")
    if schema.get("properties", {}).get("ok", {}).get("const") is not False:
        fail(f"{path}: generic error envelope must require ok=false")
    if schema.get("properties", {}).get("data", {}).get("type") != "null":
        fail(f"{path}: generic error envelope must require data=null")
    check_strict_response_node(schema, path)


def main(argv: List[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("xdebug/schemas/v1")
    if not root.exists():
        fail(f"schema root does not exist: {root}")
    files = sorted(root.rglob("*.schema.json"))
    if not files:
        fail(f"no schema files found under {root}")
    for path in files:
        try:
            with path.open("r", encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            fail(f"{path}: cannot parse JSON: {exc}")
        if not isinstance(schema, dict):
            fail(f"{path}: top-level schema must be an object")
        if "$schema" not in schema:
            fail(f"{path}: missing $schema")
        if "title" not in schema:
            fail(f"{path}: missing title")
        check_schema_node(schema, str(path))
        if (
            path.parent.name == "actions"
            and path.name.endswith(".response.schema.json")
        ):
            check_action_response_schema(schema, str(path))
        elif (
            path.parent.name == "actions"
            and path.name.endswith(".request.schema.json")
        ):
            check_action_request_schema(schema, str(path))
        elif path.name == "xdebug.error.schema.json":
            check_generic_error_response_schema(schema, str(path))
    print(f"validated {len(files)} schema files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
