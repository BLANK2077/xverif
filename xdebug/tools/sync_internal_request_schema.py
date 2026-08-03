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
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]
ACTION_SPEC = ROOT / "specs" / "actions" / "actions.yaml"
OUTPUT = ROOT / "schemas" / "v1" / "internal" / "engine.request.schema.json"
MANIFEST_OUTPUT = (
    ROOT / "schemas" / "v1" / "internal" / "engine.request.manifest.json"
)
ACTION_OUTPUT_DIR = ROOT / "schemas" / "v1" / "internal" / "actions"
HELPER_OUTPUT_DIR = ROOT / "schemas" / "v1" / "internal" / "helper-actions"

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
ACTION_NAME_RE = re.compile(r"^[a-z0-9]+(?:[._][a-z0-9]+)*$")


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


def _opaque_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": {
            "type": [
                "array",
                "boolean",
                "integer",
                "null",
                "number",
                "object",
                "string",
            ]
        },
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
    if len(names) != len(set(names)):
        raise ValueError("internal action names must be unique")
    invalid_names = [name for name in names if not ACTION_NAME_RE.fullmatch(name)]
    if invalid_names:
        raise ValueError(
            f"internal action names are not safe schema filenames: {invalid_names}"
        )
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


def _branch_action(branch: dict[str, Any]) -> str:
    action_schema = branch.get("properties", {}).get("action", {})
    if not isinstance(action_schema, dict):
        raise ValueError("internal branch action discriminator must be an object")
    if "const" in action_schema:
        values = [action_schema["const"]]
    else:
        values = action_schema.get("enum", [])
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], str)
    ):
        raise ValueError(
            "each internal branch must have exactly one string action discriminator"
        )
    return values[0]


def generate_runtime_artifacts(
    aggregate: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    branches = aggregate.get("oneOf")
    declared = aggregate.get("x-internal-actions")
    if not isinstance(branches, list) or not isinstance(declared, list):
        raise ValueError("aggregate internal schema is missing its action union")

    outer = {
        key: copy.deepcopy(value)
        for key, value in aggregate.items()
        if key not in {"oneOf", "x-internal-actions"}
    }
    action_schemas: dict[str, dict[str, Any]] = {}
    branches_by_action: dict[str, dict[str, Any]] = {}
    for branch in branches:
        if not isinstance(branch, dict):
            raise ValueError("internal action branch must be an object")
        action = _branch_action(branch)
        if action in action_schemas:
            raise ValueError(f"duplicate internal action branch: {action}")
        projected = copy.deepcopy(outer)
        projected["$id"] = f"xdebug.internal.engine.request.v1.action.{action}"
        projected["title"] = f"xdebug.internal.v1 {action} engine request"
        projected["description"] = (
            "Generated strict per-action projection of the private "
            "frontend-to-engine request contract."
        )
        projected["allOf"] = [copy.deepcopy(branch)]
        _assert_closed_objects(projected)
        Draft7Validator.check_schema(projected)
        action_schemas[action] = projected
        branches_by_action[action] = branch

    declared_actions = sorted(declared)
    if declared_actions != sorted(action_schemas):
        raise ValueError(
            "aggregate action catalog and discriminated branches differ"
        )
    refs = {
        action: f"schemas/v1/internal/actions/{action}.request.schema.json"
        for action in declared_actions
    }
    spec = _load(ACTION_SPEC)
    action_contracts = {
        action["name"]: action for action in spec.get("actions", [])
    }
    dispatch_kinds: dict[str, str] = {}
    helper_schemas: dict[str, dict[str, Any]] = {}
    helper_refs: dict[str, str] = {}
    for action in declared_actions:
        if action in INTERNAL_SESSION_ACTIONS:
            dispatch_kinds[action] = "session_local"
            continue
        if action in INTERNAL_CONTROL_ACTIONS:
            dispatch_kinds[action] = "server_control"
            continue
        contract = action_contracts.get(action)
        if not isinstance(contract, dict):
            raise ValueError(f"internal action is missing from actions.yaml: {action}")
        variants = contract.get("resource_variants", [])
        requirements = (
            [variant["requires"] for variant in variants]
            if variants
            else [contract.get("requires")]
        )
        if (
            contract.get("handler_kind") != "engine_forward"
            or "none" in requirements
        ):
            dispatch_kinds[action] = "hybrid_local_forward"
            continue

        dispatch_kinds[action] = "server_forward"
        accepted_modes: list[str] = []
        for requires in requirements:
            for mode in _accepted_resource_modes(requires):
                if mode not in accepted_modes:
                    accepted_modes.append(mode)
        branch = branches_by_action[action]
        branch_properties = branch.get("properties", {})
        properties: dict[str, Any] = {
            "api_version": copy.deepcopy(branch_properties["api_version"]),
            "action": copy.deepcopy(branch_properties["action"]),
            "observability": _observability_schema(),
            "routing": _routing_schema(
                accepted_modes=tuple(accepted_modes)
            ),
            # The helper only transports these typed payload objects.  The
            # persistent server validates every nested action-specific field.
            "target": _opaque_object_schema(),
            "args": _opaque_object_schema(),
        }
        if "limits" in branch_properties:
            properties["limits"] = copy.deepcopy(
                branch_properties["limits"]
            )
        helper_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"xdebug.internal.engine.helper-envelope.v1.{action}",
            "title": f"xdebug internal helper envelope for {action}",
            "description": (
                "Generated strict short-lived-helper envelope. The persistent "
                "engine server validates the complete action payload."
            ),
            "type": "object",
            "required": ["api_version", "action", "routing"],
            "properties": properties,
            "additionalProperties": False,
        }
        _assert_closed_objects(helper_schema)
        Draft7Validator.check_schema(helper_schema)
        helper_schemas[action] = helper_schema
        helper_refs[action] = (
            f"schemas/v1/internal/helper-actions/{action}.request.schema.json"
        )

    manifest = {
        "schema_version": "xdebug.internal-request-manifest.v1",
        "api_version": INTERNAL_API_VERSION,
        "aggregate_schema_ref": (
            "schemas/v1/internal/engine.request.schema.json"
        ),
        "action_count": len(refs),
        "actions": refs,
        "helper_dispatch_kinds": dispatch_kinds,
        "helper_envelope_schemas": helper_refs,
    }
    if set(dispatch_kinds) != set(refs):
        raise ValueError("helper dispatch catalog differs from internal actions")
    if set(helper_refs) != {
        action
        for action, kind in dispatch_kinds.items()
        if kind == "server_forward"
    }:
        raise ValueError("helper envelope catalog differs from server-forward actions")
    return manifest, action_schemas, helper_schemas


def _render(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    aggregate = generate()
    manifest, action_schemas, helper_schemas = generate_runtime_artifacts(
        aggregate
    )
    expected = {
        OUTPUT: _render(aggregate),
        MANIFEST_OUTPUT: _render(manifest),
    }
    expected.update(
        {
            ACTION_OUTPUT_DIR / f"{action}.request.schema.json": _render(schema)
            for action, schema in action_schemas.items()
        }
    )
    expected.update(
        {
            HELPER_OUTPUT_DIR / f"{action}.request.schema.json": _render(schema)
            for action, schema in helper_schemas.items()
        }
    )
    expected_action_paths = {
        path for path in expected if path.parent == ACTION_OUTPUT_DIR
    }
    actual_action_paths = (
        set(ACTION_OUTPUT_DIR.glob("*.request.schema.json"))
        if ACTION_OUTPUT_DIR.is_dir()
        else set()
    )
    expected_helper_paths = {
        path for path in expected if path.parent == HELPER_OUTPUT_DIR
    }
    actual_helper_paths = (
        set(HELPER_OUTPUT_DIR.glob("*.request.schema.json"))
        if HELPER_OUTPUT_DIR.is_dir()
        else set()
    )
    if args.check:
        stale = sorted(
            (actual_action_paths - expected_action_paths)
            | (actual_helper_paths - expected_helper_paths)
        )
        missing_or_changed = [
            path
            for path, rendered in expected.items()
            if not path.exists() or path.read_text(encoding="utf-8") != rendered
        ]
        if stale or missing_or_changed:
            for path in missing_or_changed:
                print(f"internal request artifact is out of date: {path}")
            for path in stale:
                print(f"stale internal request action schema: {path}")
            return 1
        print(
            "internal request schemas are synchronized "
            f"({len(action_schemas)} actions, "
            f"{len(helper_schemas)} helper envelopes)"
        )
        return 0

    ACTION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HELPER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(
        (actual_action_paths - expected_action_paths)
        | (actual_helper_paths - expected_helper_paths)
    ):
        path.unlink()
        print(f"removed stale {path}")
    for path, rendered in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
