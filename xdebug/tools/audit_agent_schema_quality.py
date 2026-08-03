#!/usr/bin/env python3
"""Audit that public request schemas are discoverable to an agent."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_PREFIXES = (
    "Action-specific ",
    "Structured ",
    "Ordered ",
    "action-specific 参数值",
    "组合参数对象",
    "有序项目列表",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(node: Any, path: str, errors: list[str], business: bool = True) -> None:
    if not isinstance(node, dict):
        return
    typ = node.get("type")
    if business and (typ in {"string", "integer", "number", "boolean", "object", "array"} or "oneOf" in node):
        description = node.get("description")
        if not description and not node.get("x-description-zh"):
            errors.append(f"{path}: missing description")
        elif isinstance(description, str) and description.startswith(PLACEHOLDER_PREFIXES):
            errors.append(f"{path}: placeholder description is forbidden")
    if typ == "array" and "items" not in node:
        errors.append(f"{path}: array missing items")
    if typ == "object" or "properties" in node:
        props = node.get("properties", {})
        if isinstance(props, dict):
            for name, child in props.items():
                _walk(child, f"{path}.{name}", errors)
    if isinstance(node.get("items"), dict):
        _walk(node["items"], path + "[]", errors)
    if isinstance(node.get("additionalProperties"), dict):
        _walk(node["additionalProperties"], path + ".*", errors)
    for key in ("oneOf", "anyOf", "allOf"):
        for index, child in enumerate(node.get(key, [])):
            _walk(child, f"{path}.{key}[{index}]", errors)


def main() -> int:
    specs = _load(ROOT / "specs" / "actions" / "actions.yaml")["actions"]
    errors: list[str] = []
    for spec in specs:
        schema = _load(ROOT / spec["schemas"]["request"])
        args = schema.get("properties", {}).get("args", {})
        _walk(args, f"{spec['name']}.args", errors, business=False)
        for name, child in args.get("properties", {}).items():
            _walk(child, f"{spec['name']}.args.{name}", errors)
    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        return 1
    print("agent schema quality audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
