#!/usr/bin/env python3
"""Generate the strict xdebug.internal.v1 engine request schema.

The internal wire contract is derived from the checked-in public action request
schemas, but it is not a public schema alias.  Each engine-consumed action is
inlined as a closed branch and receives one additional, closed ``routing``
object.  This keeps frontend-only transport metadata and resolved resources out
of the public ``xdebug.v1`` contract without opening any nested payload object.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]
ACTION_SPEC = ROOT / "specs" / "actions" / "actions.yaml"
OUTPUT = ROOT / "schemas" / "v1" / "internal" / "engine.request.schema.json"

INTERNAL_API_VERSION = "xdebug.internal.v1"
PUBLIC_PAYLOAD_FIELDS = ("target", "args", "limits")
INTERNAL_SESSION_ACTIONS = {"session.open", "session.kill", "session.doctor"}
INTERNAL_CONTROL_ACTIONS = ("server.ping", "server.version", "server.quit")
PUBLIC_ONLY_ENVELOPE_FIELDS = {
    "id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "auth_token",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _routing_schema(
    *,
    accepted_modes: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "minLength": 1,
                "description": "Resolved engine session destination.",
            },
            "daidir": {
                "type": "string",
                "minLength": 1,
                "description": "Resolved design database path used to open an engine.",
            },
            "fsdb": {
                "type": "string",
                "minLength": 1,
                "description": "Resolved waveform database path used to open an engine.",
            },
            "mode": {
                "type": "string",
                "enum": ["design", "waveform", "combined"],
                "description": "Resource mode derived by the frontend from resolved resources.",
            },
            "transport_auth_token": {
                "type": "string",
                "minLength": 1,
                "description": "TCP transport credential; never part of xdebug.v1.",
            },
        },
        "additionalProperties": False,
    }
    variants: list[dict[str, Any]] = []
    if "design" in accepted_modes:
        variants.append(
            {
                "required": ["daidir", "mode"],
                "properties": {"mode": {"const": "design"}},
                "not": {"required": ["fsdb"]},
            }
        )
    if "waveform" in accepted_modes:
        variants.append(
            {
                "required": ["fsdb", "mode"],
                "properties": {"mode": {"const": "waveform"}},
                "not": {"required": ["daidir"]},
            }
        )
    if "combined" in accepted_modes:
        variants.append(
            {
                "required": ["daidir", "fsdb", "mode"],
                "properties": {"mode": {"const": "combined"}},
            }
        )
    if variants:
        schema["oneOf"] = variants
    return schema


def _accepted_resource_modes(requires: str) -> tuple[str, ...]:
    if requires == "design":
        return ("design", "combined")
    if requires == "waveform":
        return ("waveform", "combined")
    if requires == "combined":
        return ("combined",)
    if requires == "any":
        return ("design", "waveform", "combined")
    raise ValueError(f"unsupported internal resource requirement: {requires}")


def _observability_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "string",
                "minLength": 1,
            }
            for key in (
                "request_id",
                "trace_id",
                "span_id",
                "parent_span_id",
            )
        },
        "additionalProperties": False,
    }


def _strip_annotations(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep validation behavior while dropping public discovery annotations."""
    result = copy.deepcopy(schema)
    for key in list(result):
        if key.startswith("x-") or key in {
            "$schema",
            "$id",
            "title",
            "description",
            "examples",
            "default",
        }:
            result.pop(key, None)
    return result


def _public_action_branch(action: dict[str, Any]) -> dict[str, Any]:
    name = action["name"]
    schema_path = ROOT / action["schemas"]["request"]
    public_schema = _load(schema_path)
    branch = _strip_annotations(public_schema)

    public_properties = public_schema.get("properties")
    if not isinstance(public_properties, dict):
        raise ValueError(f"{schema_path}: properties must be an object")

    properties: dict[str, Any] = {
        "api_version": {
            "type": "string",
            "enum": [INTERNAL_API_VERSION],
        },
        "action": {"type": "string", "enum": [name]},
        "observability": _observability_schema(),
        "routing": _routing_schema(),
    }
    for field in PUBLIC_PAYLOAD_FIELDS:
        if field in public_properties:
            properties[field] = copy.deepcopy(public_properties[field])
    if name == "session.open":
        target_schema = properties.get("target")
        if isinstance(target_schema, dict):
            target_properties = target_schema.get("properties")
            if isinstance(target_properties, dict):
                target_properties.pop("run_manifest", None)

    leaked = PUBLIC_ONLY_ENVELOPE_FIELDS.intersection(public_properties)
    # The public generator is repaired independently.  Never reproduce leaked
    # framing/transport fields in the internal contract while that repair lands.
    for field in leaked:
        properties.pop(field, None)

    branch["type"] = "object"
    branch["properties"] = properties
    branch["additionalProperties"] = False
    required = [
        field
        for field in public_schema.get("required", [])
        if field in properties
        and field not in PUBLIC_ONLY_ENVELOPE_FIELDS
        and field != "request_id"
    ]
    for field in ("api_version", "action"):
        if field not in required:
            required.insert(0 if field == "api_version" else 1, field)
    branch["required"] = required
    if name == "session.open":
        if "routing" not in branch["required"]:
            branch["required"].append("routing")
        branch["properties"]["routing"]["required"] = ["mode"]
        branch["properties"]["routing"]["oneOf"] = [
            {
                "required": ["daidir"],
                "properties": {"mode": {"const": "design"}},
                "not": {"required": ["fsdb"]},
            },
            {
                "required": ["fsdb"],
                "properties": {"mode": {"const": "waveform"}},
                "not": {"required": ["daidir"]},
            },
            {
                "required": ["daidir", "fsdb"],
                "properties": {"mode": {"const": "combined"}},
            },
        ]
    elif name in {"session.kill", "session.doctor"}:
        if "routing" not in branch["required"]:
            branch["required"].append("routing")
        branch["properties"]["routing"]["required"] = ["session_id"]
    elif action.get("resource_variants"):
        variants = action["resource_variants"]
        branch_variants = branch.get("oneOf")
        if (
            not isinstance(branch_variants, list)
            or len(branch_variants) != len(variants)
        ):
            raise ValueError(
                f"{schema_path}: resource variants do not align with schema oneOf"
            )
        for contract_variant, schema_variant in zip(
            variants, branch_variants, strict=True
        ):
            requires = contract_variant["requires"]
            if requires == "none":
                schema_variant["not"] = {"required": ["routing"]}
                continue
            schema_variant.setdefault("required", []).append("routing")
            schema_variant.setdefault("properties", {})["routing"] = (
                _routing_schema(
                    accepted_modes=_accepted_resource_modes(requires)
                )
            )
    elif action.get("handler_kind") == "engine_forward":
        requires = action["requires"]
        if requires != "none":
            if "routing" not in branch["required"]:
                branch["required"].append("routing")
            branch["properties"]["routing"] = _routing_schema(
                accepted_modes=_accepted_resource_modes(requires)
            )
    return branch


def _control_branch(action: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["api_version", "action", "args"],
        "properties": {
            "api_version": {
                "type": "string",
                "enum": [INTERNAL_API_VERSION],
            },
            "action": {"type": "string", "enum": [action]},
            "observability": _observability_schema(),
            "args": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "routing": _routing_schema(),
        },
        "additionalProperties": False,
    }


def _assert_closed_objects(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            additional = node.get("additionalProperties")
            if additional is not False and not (
                isinstance(additional, dict) and bool(additional)
            ):
                raise ValueError(
                    f"{path}: internal object must be closed or an explicitly typed map"
                )
        for key, child in node.items():
            _assert_closed_objects(child, f"{path}.{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _assert_closed_objects(child, f"{path}[{index}]")


def generate() -> dict[str, Any]:
    spec = _load(ACTION_SPEC)
    actions = []
    for action in spec.get("actions", []):
        handler_kind = action.get("handler_kind")
        if handler_kind == "engine_forward" or action.get("name") in INTERNAL_SESSION_ACTIONS:
            actions.append(action)
    actions.sort(key=lambda item: item["name"])

    names = [action["name"] for action in actions]
    names.extend(INTERNAL_CONTROL_ACTIONS)
    branches = [_public_action_branch(action) for action in actions]
    branches.extend(_control_branch(action) for action in INTERNAL_CONTROL_ACTIONS)

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "xdebug.internal.engine.request.v1",
        "title": "xdebug.internal.v1 engine request",
        "description": (
            "Private frontend-to-engine request contract. Public requests use "
            "xdebug.v1 and cannot carry routing fields."
        ),
        "type": "object",
        "required": ["api_version", "action"],
        # This outer allowlist closes the wire envelope.  The oneOf branches
        # below provide every nested shape; these empty property schemas do not
        # form a permissive path because exactly one strict branch must match.
        "properties": {
            field: {}
            for field in (
                "api_version",
                "action",
                "observability",
                "routing",
                "target",
                "args",
                "limits",
            )
        },
        "additionalProperties": False,
        "oneOf": branches,
        "x-internal-actions": sorted(names),
    }
    _assert_closed_objects(schema)
    Draft7Validator.check_schema(schema)
    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    rendered = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"internal request schema is out of date: {OUTPUT}")
            return 1
        print("internal request schema is synchronized")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
