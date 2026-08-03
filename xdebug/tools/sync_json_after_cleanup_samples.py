#!/usr/bin/env python3
"""Sync current JSON contract samples from canonical action examples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


XDEBUG_ROOT = Path(__file__).resolve().parents[1]
ACTION_CATALOG = XDEBUG_ROOT / "specs" / "actions" / "actions.yaml"
SAMPLE_ROOT = XDEBUG_ROOT / "doc" / "json_after_cleanup"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _sample_name(action: str) -> str:
    return action.replace(".", "_") + ".json"


def expected_samples() -> dict[Path, str]:
    catalog = _load_json(ACTION_CATALOG)
    entries = catalog.get("actions")
    if not isinstance(entries, list):
        raise ValueError("actions.yaml must contain an actions array")

    rendered: dict[Path, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("actions.yaml entries must be objects")
        action = entry.get("name")
        examples = entry.get("examples")
        if not isinstance(action, str) or not action:
            raise ValueError("action entry has no nonempty name")
        if not isinstance(examples, dict):
            raise ValueError(f"{action}: examples must be an object")
        request_paths = examples.get("request")
        response_paths = examples.get("response")
        if not isinstance(request_paths, list) or not request_paths:
            raise ValueError(f"{action}: request examples are missing")
        if not isinstance(response_paths, list) or not response_paths:
            raise ValueError(f"{action}: response examples are missing")

        request_path = XDEBUG_ROOT / request_paths[0]
        response_path = XDEBUG_ROOT / response_paths[0]
        request = _load_json(request_path)
        response = _load_json(response_path)
        if not isinstance(request, dict) or request.get("action") != action:
            raise ValueError(
                f"{action}: primary request example has a different action"
            )
        if not isinstance(response, dict) or response.get("action") != action:
            raise ValueError(
                f"{action}: primary response example has a different action"
            )
        sample_path = SAMPLE_ROOT / _sample_name(action)
        if sample_path in rendered:
            raise ValueError(f"{action}: duplicate generated sample path")
        rendered[sample_path] = _render(
            {
                "request": request,
                "response": response,
                "stderr": "",
            }
        )
    return rendered


def sync(*, check: bool) -> list[str]:
    errors: list[str] = []
    try:
        expected = expected_samples()
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return [f"sample source error: {exc}"]

    actual_paths = set(SAMPLE_ROOT.glob("*.json"))
    expected_paths = set(expected)
    for path in sorted(actual_paths - expected_paths):
        errors.append(
            f"retired current sample must be removed: "
            f"{path.relative_to(XDEBUG_ROOT)}"
        )
    for path, content in sorted(expected.items()):
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                errors.append(
                    f"current sample drift: {path.relative_to(XDEBUG_ROOT)}"
                )
        else:
            path.write_text(content, encoding="utf-8")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    errors = sync(check=args.check)
    if errors:
        print("\n".join(errors))
        return 1
    if args.check:
        print("current JSON contract samples are synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
