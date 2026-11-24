#!/usr/bin/env python3
"""Export the checked-in xcov schemas to canonical JSON files.

The JSON files under ``xcov/xcov/schemas_data/v1`` become the single source of
truth for both the Python and the C++ implementation.  Run with ``--check`` to
verify the checked-in files still match the code that builds them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "xcov"))

from xcov import schemas  # noqa: E402

SCHEMA_ROOT = ROOT / "xcov" / "xcov" / "schemas_data" / "v1"
SCHEMA_VERSION = "xcov.schema.v1"


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_files() -> dict[Path, str]:
    files: dict[Path, str] = {}
    for action in sorted(schemas.BUILT_SCHEMAS):
        entry = schemas.BUILT_SCHEMAS[action]
        for kind in ("request", "response"):
            path = SCHEMA_ROOT / "actions" / f"{action}.{kind}.schema.json"
            files[path] = _dump(entry[kind])
    files[SCHEMA_ROOT / "internal" / "run_manifest.input.schema.json"] = _dump(
        schemas.BUILT_RUN_MANIFEST_INPUT
    )
    files[SCHEMA_ROOT / "internal" / "stdio_quit.request.schema.json"] = _dump(
        schemas.BUILT_STDIO_QUIT_REQUEST
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "xcov/tools/export_schemas.py",
        "actions": {
            action: {
                "request": _digest(files[SCHEMA_ROOT / "actions" / f"{action}.request.schema.json"]),
                "response": _digest(files[SCHEMA_ROOT / "actions" / f"{action}.response.schema.json"]),
            }
            for action in sorted(schemas.BUILT_SCHEMAS)
        },
        "internal": {
            "run_manifest": _digest(
                files[SCHEMA_ROOT / "internal" / "run_manifest.input.schema.json"]
            ),
            "stdio_quit": _digest(
                files[SCHEMA_ROOT / "internal" / "stdio_quit.request.schema.json"]
            ),
        },
    }
    files[SCHEMA_ROOT / "manifest.json"] = _dump(manifest)
    return files


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_files(files: dict[Path, str]) -> list[Path]:
    written: list[Path] = []
    for path, text in sorted(files.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def check_files(files: dict[Path, str]) -> list[str]:
    problems: list[str] = []
    for path, text in sorted(files.items()):
        if not path.is_file():
            problems.append(f"missing: {_rel(path)}")
            continue
        if path.read_text(encoding="utf-8") != text:
            problems.append(f"stale: {_rel(path)}")
    known = set(files)
    if SCHEMA_ROOT.is_dir():
        for path in sorted(SCHEMA_ROOT.rglob("*.json")):
            if path in known:
                continue
            # Action metadata is produced by export_actions.py.
            if path == SCHEMA_ROOT / "actions.json":
                continue
            problems.append(f"unexpected: {_rel(path)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    files = build_files()
    if args.check:
        problems = check_files(files)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print(f"schemas up to date ({len(files)} files)")
        return 0
    written = write_files(files)
    print(f"wrote {len(written)} schema files under {_rel(SCHEMA_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
