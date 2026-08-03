#!/usr/bin/env python3
"""Ensure every runtime request schema stays executable by the Draft-7 validator.

The public files retain their Draft 2020-12 declaration for tooling, but the
C++ runtime relabels and compiles request schemas with its embedded Draft-7
validator.  A request schema must therefore not introduce later-draft-only
keywords.  Response schemas are discovery artifacts and are not loaded by the
runtime validator.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {
    "$anchor", "$dynamicAnchor", "$dynamicRef", "$defs", "$vocabulary",
    "dependentRequired", "dependentSchemas", "maxContains", "minContains",
    "prefixItems", "unevaluatedItems", "unevaluatedProperties",
}


def walk(value: object, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN:
                errors.append(f"{path}: runtime Draft-7 request schema forbids {key}")
            walk(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]", errors)


def main() -> int:
    errors: list[str] = []
    paths = list(
        (ROOT / "schemas" / "v1" / "actions").glob(
            "*.request.schema.json"
        )
    )
    paths.extend(
        (ROOT / "schemas" / "v1" / "internal").rglob(
            "*.request.schema.json"
        )
    )
    for path in sorted(set(paths)):
        if not path.is_file():
            errors.append(
                f"{path.relative_to(ROOT)}: runtime request schema is missing"
            )
            continue
        schema = json.loads(path.read_text(encoding="utf-8"))
        walk(schema, "$", errors)
        try:
            Draft7Validator.check_schema(schema)
        except Exception as exc:  # jsonschema reports the precise invalid keyword.
            errors.append(f"{path.relative_to(ROOT)}: Draft-7 metaschema rejected schema: {exc}")
    if errors:
        print("runtime request schema compatibility audit failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("runtime request schemas are Draft-7 compatible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
