#!/usr/bin/env python3
"""Validate positive examples and canonical invalid request witnesses.

Requests must have the same verdict under the public Draft 2020-12 declaration
and the embedded runtime's Draft-7 interpretation.  Invalid witnesses are
manifested separately so MCP projections and the C++ validator consume the
same executable counterexamples.
"""

import json
import sys
from pathlib import Path
from typing import Any, List

from jsonschema import Draft7Validator, Draft202012Validator, ValidationError as JsonSchemaValidationError


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        fail(f"{path}: cannot parse JSON: {exc}")


def action_schema_path(schemas: Path, action: str, kind: str) -> Path:
    candidate = schemas / "actions" / f"{action}.{kind}.schema.json"
    if candidate.exists():
        return candidate
    fail(f"missing action-specific {kind} schema for {action}: {candidate}")


def validate_file(path: Path, schemas: Path) -> None:
    doc = load_json(path)
    if path.parent.name == "errors":
        schema_path = schemas / "xdebug.error.schema.json"
        kind = "response"
    else:
        if not isinstance(doc, dict) or not isinstance(doc.get("action"), str):
            fail(f"{path}: example must contain string action")
        kind = "request" if path.parent.name == "requests" else "response"
        schema_path = action_schema_path(schemas, doc["action"], kind)
    schema = load_json(schema_path)
    validator = Draft7Validator(schema) if kind == "request" else Draft202012Validator(schema)
    try:
        validator.validate(doc)
    except JsonSchemaValidationError as exc:
        fail(f"{path}: does not match {schema_path}: {exc}")


def validate_invalid_witnesses(examples: Path, schemas: Path) -> int:
    manifest_path = examples / "requests-invalid" / "manifest.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        fail(f"{manifest_path}: expected version 1 invalid-witness manifest")
    witnesses = manifest.get("witnesses")
    if not isinstance(witnesses, list) or not witnesses:
        fail(f"{manifest_path}: witnesses must be a non-empty array")
    seen_paths: set[str] = set()
    root = examples.parent
    for index, entry in enumerate(witnesses):
        if not isinstance(entry, dict):
            fail(f"{manifest_path}: witnesses[{index}] must be an object")
        action = entry.get("action")
        relative = entry.get("path")
        description = entry.get("description")
        violations = entry.get("violates")
        if not all(isinstance(value, str) and value for value in
                   (action, relative, description)):
            fail(f"{manifest_path}: witnesses[{index}] has incomplete metadata")
        if not isinstance(violations, list) or not violations or not all(
                isinstance(value, str) and value for value in violations):
            fail(f"{manifest_path}: witnesses[{index}].violates must be non-empty")
        if relative in seen_paths:
            fail(f"{manifest_path}: duplicate witness path {relative}")
        seen_paths.add(relative)
        witness_path = root / relative
        request = load_json(witness_path)
        if not isinstance(request, dict) or request.get("action") != action:
            fail(f"{witness_path}: action does not match manifest entry {action}")
        schema_path = action_schema_path(schemas, action, "request")
        schema = load_json(schema_path)
        draft7_valid = Draft7Validator(schema).is_valid(request)
        draft202012_valid = Draft202012Validator(schema).is_valid(request)
        if draft7_valid != draft202012_valid:
            fail(f"{witness_path}: Draft-7 and Draft 2020-12 verdicts differ")
        if draft7_valid:
            fail(f"{witness_path}: canonical invalid witness was accepted")
    actual = {
        str(path.relative_to(root))
        for path in (examples / "requests-invalid").glob("*.json")
        if path.name != "manifest.json"
    }
    missing = actual - seen_paths
    stale = seen_paths - actual
    if missing or stale:
        fail(f"{manifest_path}: unmanifested={sorted(missing)} missing={sorted(stale)}")
    return len(witnesses)


def main(argv: List[str]) -> int:
    examples = Path(argv[1]) if len(argv) > 1 else Path("xdebug/examples")
    schemas = Path(argv[2]) if len(argv) > 2 else Path("xdebug/schemas/v1")
    if not examples.exists():
        fail(f"examples root does not exist: {examples}")
    if not schemas.exists():
        fail(f"schemas root does not exist: {schemas}")
    invalid_root = examples / "requests-invalid"
    files = sorted(
        path for path in examples.rglob("*.json")
        if invalid_root not in path.parents and path != invalid_root
    )
    if not files:
        fail(f"no examples found under {examples}")
    for path in files:
        validate_file(path, schemas)
    invalid_count = validate_invalid_witnesses(examples, schemas)
    print(f"validated {len(files)} examples and {invalid_count} invalid request witnesses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
