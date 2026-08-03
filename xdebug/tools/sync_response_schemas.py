#!/usr/bin/env python3
"""Synchronize the single checked-in response schema for every public action.

The 53a baseline already owns the domain response objects.  This rebuild keeps
those objects and projects canonical action renames/new catalog entries through
one response-schema entry point instead of introducing per-domain generators.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "specs" / "actions" / "actions.yaml"

SEED_ACTION = {
    "apb.transaction.cursor": "apb.cursor",
    "axi.transaction.cursor": "axi.cursor",
    "waveform.cursor.delete": "cursor.delete",
    "waveform.cursor.get": "cursor.get",
    "waveform.cursor.list": "cursor.list",
    "waveform.cursor.set": "cursor.set",
    "waveform.cursor.use": "cursor.use",
    "signal.anomaly.inspect": "detect_abnormal",
    "protocol.handshake.inspect": "handshake.inspect",
    "list.first_change": "list.diff",
    "nwave.rc.generate": "rc.generate",
    "signal.sampled_pulse.inspect": "sampled_pulse.inspect",
    "stream.describe": "stream.show",
    "trace.x_origin": "trace.x",
    "list.load": "list.create",
    "stream.config.get": "stream.config.list",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def rename_strings(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {key: rename_strings(item, old, new)
                for key, item in value.items()}
    if isinstance(value, list):
        return [rename_strings(item, old, new) for item in value]
    if isinstance(value, str):
        return value.replace(old, new)
    return value


def projected_schema(action: str, target: Path) -> dict[str, Any]:
    if target.exists():
        return load(target)
    else:
        seed = SEED_ACTION.get(action)
        if seed is None:
            raise ValueError(f"{action}: response schema is missing and has no seed")
        source = target.with_name(seed + ".response.schema.json")
        if not source.exists():
            raise ValueError(f"{action}: response schema seed is missing: {source}")
        schema = rename_strings(copy.deepcopy(load(source)), seed, action)
    schema["title"] = f"{action} response"
    action_schema = schema.setdefault("properties", {}).setdefault(
        "action", {"type": "string"})
    action_schema.pop("const", None)
    action_schema["enum"] = [action]
    return schema


def sync(check: bool) -> list[str]:
    errors: list[str] = []
    for spec in load(CATALOG)["actions"]:
        if spec.get("status") == "removed":
            continue
        action = spec["name"]
        target = ROOT / spec["schemas"]["response"]
        try:
            expected = projected_schema(action, target)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        actual = load(target) if target.exists() else None
        if actual == expected:
            continue
        if check:
            errors.append(f"{spec['schemas']['response']}: response schema is not synced")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dump(expected), encoding="utf-8")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    errors = sync(args.check)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("response schemas are synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
