#!/usr/bin/env python3
"""Export the canonical xcov action catalog to JSON.

The JSON file becomes the runtime catalog for the C++ implementation and keeps
action metadata in one place, mirroring the schema export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "xcov"))

from xcov.actions import ACTION_REGISTRY  # noqa: E402

CATALOG_PATH = ROOT / "xcov" / "xcov" / "schemas_data" / "v1" / "actions.json"


def build_document() -> dict:
    items = []
    for name, contract in ACTION_REGISTRY.items():
        items.append(
            {
                "name": name,
                "handler": contract.handler,
                "needs_session": contract.needs_session,
                "use_when": contract.use_when,
                "do_not_use_when": contract.do_not_use_when,
            }
        )
    return {
        "catalog_version": "xcov.action-catalog.v1",
        "actions": items,
    }


def render(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(build_document())
    if args.check:
        if not CATALOG_PATH.is_file():
            print(f"missing: {CATALOG_PATH}", file=sys.stderr)
            return 1
        if CATALOG_PATH.read_text(encoding="utf-8") != text:
            print(f"stale: {CATALOG_PATH}", file=sys.stderr)
            return 1
        print("action catalog up to date")
        return 0
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
