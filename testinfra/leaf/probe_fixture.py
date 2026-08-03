#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path


def _matches(root: Path, pattern: str) -> list[Path]:
    return sorted(path for path in root.glob(pattern) if path.exists())


def _query(xdebug: Path, home: Path, request: dict) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(home)
    result = subprocess.run(
        [str(xdebug), "--json", "-"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=env,
        timeout=180,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"xdebug probe returned invalid JSON: {result.stdout[-1000:]}") from exc
    if result.returncode != 0 or response.get("ok") is not True:
        raise RuntimeError(f"xdebug probe failed: {response.get('error')}")
    return response


def _probe_database(root: Path, xdebug: Path, fsdb_glob: str | None, daidir_glob: str | None) -> None:
    fsdbs = _matches(root, fsdb_glob) if fsdb_glob else []
    daidirs = _matches(root, daidir_glob) if daidir_glob else []
    if fsdb_glob and not fsdbs:
        raise RuntimeError(f"FSDB probe glob matched nothing: {fsdb_glob}")
    if daidir_glob and not daidirs:
        raise RuntimeError(f"daidir probe glob matched nothing: {daidir_glob}")

    pairs: list[tuple[Path | None, Path | None]] = []
    if len(fsdbs) <= 1 and len(daidirs) <= 1:
        pairs.append((fsdbs[0] if fsdbs else None, daidirs[0] if daidirs else None))
    elif fsdbs and daidirs:
        for fsdb in fsdbs:
            candidates = [path for path in daidirs if path.parent == fsdb.parent]
            if len(candidates) != 1:
                raise RuntimeError(f"cannot pair FSDB with daidir: {fsdb}")
            pairs.append((fsdb, candidates[0]))
    else:
        pairs.extend((path, None) for path in fsdbs)
        pairs.extend((None, path) for path in daidirs)

    with tempfile.TemporaryDirectory(prefix="xverif-fixture-probe-") as home_value:
        home = Path(home_value)
        for fsdb, daidir in pairs:
            name = "fixture_probe_" + uuid.uuid4().hex[:12]
            target = {}
            if fsdb is not None:
                target["fsdb"] = str(fsdb.resolve())
            if daidir is not None:
                target["daidir"] = str(daidir.resolve())
            opened = _query(
                xdebug,
                home,
                {
                    "api_version": "xdebug.v1",
                    "action": "session.open",
                    "target": target,
                    "args": {"name": name},
                },
            )
            session = opened["session"]
            session_id = session["session_id"]
            try:
                roots = _query(
                    xdebug,
                    home,
                    {
                        "api_version": "xdebug.v1",
                        "action": "scope.roots",
                        "target": {"session_id": session_id},
                        "args": {},
                    },
                )
                if not roots.get("data"):
                    raise RuntimeError(f"scope.roots returned no data for {target}")
            finally:
                _query(
                    xdebug,
                    home,
                    {
                        "api_version": "xdebug.v1",
                        "action": "session.close",
                        "target": {"session_id": session_id},
                        "args": {},
                    },
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--xdebug", type=Path)
    parser.add_argument("--fsdb-glob")
    parser.add_argument("--daidir-glob")
    parser.add_argument("--json-glob", action="append", default=[])
    parser.add_argument("--text-glob", action="append", default=[])
    parser.add_argument("--executable-glob", action="append", default=[])
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--require-text", action="append", default=[])
    parser.add_argument("--reject-text", action="append", default=[])
    parser.add_argument("--uvm-zero", action="store_true")
    args = parser.parse_args()
    root = args.resources.resolve()

    if args.fsdb_glob or args.daidir_glob:
        if args.xdebug is None:
            parser.error("--xdebug is required for database probes")
        _probe_database(root, args.xdebug.resolve(), args.fsdb_glob, args.daidir_glob)

    for pattern in args.json_glob:
        matches = _matches(root, pattern)
        if len(matches) < args.min_count:
            raise RuntimeError(f"JSON probe matched {len(matches)} files, expected {args.min_count}: {pattern}")
        for path in matches:
            json.loads(path.read_text(encoding="utf-8"))

    for pattern in args.text_glob:
        matches = _matches(root, pattern)
        if len(matches) < args.min_count:
            raise RuntimeError(f"text probe matched {len(matches)} files, expected {args.min_count}: {pattern}")
        for path in matches:
            text = path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                raise RuntimeError(f"text probe found empty file: {path}")
            for required in args.require_text:
                if required not in text:
                    raise RuntimeError(f"text probe missing {required!r}: {path}")
            for rejected in args.reject_text:
                if rejected in text:
                    raise RuntimeError(f"text probe found {rejected!r}: {path}")
            if args.uvm_zero:
                for severity in ("UVM_ERROR", "UVM_FATAL"):
                    match = re.search(
                        rf"^{severity}\s*:\s*(\d+)\s*$", text, flags=re.MULTILINE
                    )
                    if match is None or int(match.group(1)) != 0:
                        raise RuntimeError(
                            f"text probe requires {severity} summary count 0: {path}"
                        )

    for pattern in args.executable_glob:
        matches = _matches(root, pattern)
        if len(matches) < args.min_count:
            raise RuntimeError(f"executable probe matched {len(matches)} files, expected {args.min_count}: {pattern}")
        for path in matches:
            if not path.is_file() or not os.access(path, os.X_OK):
                raise RuntimeError(f"probe output is not executable: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
