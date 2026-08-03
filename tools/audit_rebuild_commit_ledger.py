#!/usr/bin/env python3
"""Build and validate an atom-complete ledger for the a3d reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "doc/XDEBUG_A3D_REBUILD_COMMIT_LEDGER_2026-08-03.json"
DEFAULT_INVENTORY = ROOT / "doc/XDEBUG_A3D_REBUILD_DIFF_ATOMS_2026-08-03.jsonl"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def disposition_for(entry: dict[str, Any], path: str) -> str:
    for rule in entry.get("rules", []):
        if re.search(rule["path"], path):
            return rule["disposition"]
    return entry["default"]


def metadata_atoms(entry: dict[str, Any]) -> list[dict[str, Any]]:
    sha = entry["sha"]
    raw = git("diff-tree", "--no-commit-id", "--raw", "-r", "-M", "-C", sha)
    atoms: list[dict[str, Any]] = []
    for line in raw.splitlines():
        meta, *paths = line.split("\t")
        fields = meta.split()
        old_mode = fields[0][1:]
        new_mode, old_blob, new_blob, status = fields[1:5]
        old_path = paths[0]
        new_path = paths[-1]
        path = new_path if not status.startswith("D") else old_path
        payload = (line + "\n").encode()
        atoms.append({
            "id": f"{sha}:metadata:{hashlib.sha256(payload).hexdigest()}",
            "commit": sha,
            "kind": "metadata",
            "old_path": old_path,
            "new_path": new_path,
            "status": status,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "old_blob": old_blob,
            "new_blob": new_blob,
            "patch_sha256": hashlib.sha256(payload).hexdigest(),
            "disposition": disposition_for(entry, path),
        })
    return atoms


def hunk_atoms(entry: dict[str, Any]) -> list[dict[str, Any]]:
    sha = entry["sha"]
    patch = git("show", "--format=", "--find-renames", "--binary", "--unified=0", sha)
    lines = patch.splitlines(keepends=True)
    old_path = new_path = ""
    atoms: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            old_path = line[4:].strip()
            old_path = old_path[2:] if old_path.startswith("a/") else old_path
        elif line.startswith("+++ "):
            new_path = line[4:].strip()
            new_path = new_path[2:] if new_path.startswith("b/") else new_path
        elif line.startswith("@@ "):
            match = HUNK_RE.match(line)
            if not match:
                raise RuntimeError(f"cannot parse hunk header: {line.rstrip()}")
            end = index + 1
            while end < len(lines) and not lines[end].startswith(("@@ ", "diff --git ")):
                end += 1
            payload = "".join(lines[index:end]).encode()
            digest = hashlib.sha256(payload).hexdigest()
            path = new_path if new_path != "/dev/null" else old_path
            atoms.append({
                "id": f"{sha}:hunk:{path}:{match.group(1)}:{match.group(3)}:{digest}",
                "commit": sha,
                "kind": "hunk",
                "old_path": old_path,
                "new_path": new_path,
                "old_start": int(match.group(1)),
                "old_count": int(match.group(2) or "1"),
                "new_start": int(match.group(3)),
                "new_count": int(match.group(4) or "1"),
                "patch_sha256": digest,
                "disposition": disposition_for(entry, path),
            })
            index = end - 1
        index += 1
    return atoms


def build_inventory(data: dict[str, Any]) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for entry in data["commits"]:
        atoms.extend(metadata_atoms(entry))
        atoms.extend(hunk_atoms(entry))
    return atoms


def write_inventory(path: Path, data: dict[str, Any], atoms: list[dict[str, Any]]) -> None:
    header = {
        "kind": "header",
        "schema_version": data["schema_version"],
        "baseline": data["baseline"],
        "reference_head": data["reference_head"],
        "commit_count": len(data["commits"]),
        "atom_count": len(atoms),
    }
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(header, ensure_ascii=False, sort_keys=True) + "\n")
        for atom in atoms:
            stream.write(json.dumps(atom, ensure_ascii=False, sort_keys=True) + "\n")


def read_inventory(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return records[0], records[1:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--write-inventory", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.ledger.read_text(encoding="utf-8"))
    allowed = set(data["allowed_dispositions"])
    entries = data["commits"]
    shas = [entry["sha"] for entry in entries]
    expected = git("rev-list", "--reverse", f'{data["baseline"]}..{data["reference_head"]}').splitlines()
    errors: list[str] = []

    if shas != expected:
        errors.append("ledger SHA sequence does not exactly match rev-list")
    duplicates = [sha for sha, count in Counter(shas).items() if count != 1]
    if duplicates:
        errors.append("duplicate SHA entries: " + ", ".join(duplicates))
    for entry in entries:
        if entry.get("default") not in allowed:
            errors.append(f'{entry["sha"]}: invalid commit-wide disposition')
        for rule in entry.get("rules", []):
            if rule.get("disposition") not in allowed:
                errors.append(f'{entry["sha"]}: invalid rule disposition')
            try:
                re.compile(rule["path"])
            except re.error as exc:
                errors.append(f'{entry["sha"]}: invalid path regex: {exc}')
    if errors:
        for error in errors:
            print("ERROR:", error)
        return 1

    atoms = build_inventory(data)
    atom_ids = [atom["id"] for atom in atoms]
    if len(atom_ids) != len(set(atom_ids)):
        print("ERROR: duplicate atom ids")
        return 1
    if any(atom["disposition"] not in allowed for atom in atoms):
        print("ERROR: unclassified atom")
        return 1

    if args.write_inventory:
        write_inventory(args.inventory, data, atoms)
    if not args.inventory.exists():
        print("ERROR: explicit atom inventory is missing")
        return 1
    header, recorded = read_inventory(args.inventory)
    expected_header = {
        "kind": "header", "schema_version": data["schema_version"],
        "baseline": data["baseline"], "reference_head": data["reference_head"],
        "commit_count": len(entries), "atom_count": len(atoms),
    }
    if header != expected_header:
        print("ERROR: inventory header drift")
        return 1
    if recorded != atoms:
        print("ERROR: inventory atoms drift from immutable Git diff")
        return 1

    counts = Counter(atom["disposition"] for atom in atoms)
    kinds = Counter(atom["kind"] for atom in atoms)
    print(f'PASS commits={len(entries)} atoms={len(atoms)} metadata={kinds["metadata"]} hunks={kinds["hunk"]}')
    print(" ".join(f"{key}={counts[key]}" for key in sorted(allowed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
