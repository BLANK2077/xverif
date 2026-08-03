from __future__ import annotations

import json
from pathlib import Path
import sys

from xcov.backend import CanonicalCoverageBackend, NpiCoverageBackend


SCORE_TYPES = {
    "line": {"npiCovStmtBin"},
    "toggle": {"npiCovToggleBin"},
    "branch": {"npiCovBranchBin"},
    "condition": {"npiCovConditionBin"},
    "fsm": {"npiCovTransBin"},
    "assert": {"npiCovAssert", "npiCovCoverProperty", "npiCovCoverSequence"},
    "functional": {"npiCovCoverBin"},
}


def _target(rows: list[dict], metric: str, *, uncovered: bool = False) -> dict:
    candidates = [
        row
        for row in rows
        if row["metric"] == metric
        and row["type"] in SCORE_TYPES[metric]
        and (row["coverable"] or 0) > 0
    ]
    if uncovered:
        candidates = [
            row for row in candidates
            if (row["covered"] or 0) < (row["coverable"] or 0)
        ]
    if not candidates:
        raise RuntimeError(f"fixture has no {'uncovered ' if uncovered else ''}{metric} score object")
    return candidates[0]


def run_default(vdb: str, output_dir: Path) -> dict:
    backend = CanonicalCoverageBackend(NpiCoverageBackend(vdb))
    try:
        rows = backend.items(test="merged")
        matrix = {}
        targets = []
        for metric in SCORE_TYPES:
            target = _target(rows, metric)
            targets.append(target)
            added = backend.set_exclusion(target["coverage_ref"], True)
            repeated = backend.set_exclusion(target["coverage_ref"], True)
            removed = backend.set_exclusion(target["coverage_ref"], False)
            matrix[metric] = [added["status"], repeated["status"], removed["status"]]

        first_path = output_dir / "first.el"
        second_path = output_dir / "second.el"
        backend.set_exclusion(targets[0]["coverage_ref"], True)
        backend.save_exclusions(str(first_path))
        backend.set_exclusion(targets[0]["coverage_ref"], False)
        backend.set_exclusion(targets[1]["coverage_ref"], True)
        backend.save_exclusions(str(second_path))
        backend.set_exclusion(targets[1]["coverage_ref"], False)
        backend.load_exclusions([str(first_path), str(second_path)])
        after_union = {
            row["coverage_ref"]: row
            for row in backend.items(test="merged")
        }
        union = all(
            "excluded_at_report_time" in after_union[target["coverage_ref"]]["status"]
            for target in targets[:2]
        )
        persisted = output_dir / "persisted.el"
        backend.save_exclusions(str(persisted))
        backend.unload_exclusions()
        return {"matrix": matrix, "union": union, "persisted": str(persisted)}
    finally:
        backend.close()


def run_strict(vdb: str) -> dict:
    backend = CanonicalCoverageBackend(
        NpiCoverageBackend(vdb, exclusion_policy="strict")
    )
    try:
        rows = backend.items(metrics=["line"], test="merged")
        covered = next(
            row
            for row in rows
            if row["type"] == "npiCovStmtBin"
            and (row["coverable"] or 0) > 0
            and row["covered"] == row["coverable"]
        )
        uncovered = _target(rows, "line", uncovered=True)
        denied = backend.set_exclusion(covered["coverage_ref"], True)
        allowed = backend.set_exclusion(uncovered["coverage_ref"], True)
        return {"covered": denied["status"], "uncovered": allowed["status"]}
    finally:
        backend.close()


def run_reopen(vdb: str, persisted: Path) -> dict:
    backend = CanonicalCoverageBackend(NpiCoverageBackend(vdb))
    try:
        before = sum(
            "excluded_at_report_time" in row["status"]
            for row in backend.items(test="merged")
        )
        backend.load_exclusions([str(persisted)])
        after = sum(
            "excluded_at_report_time" in row["status"]
            for row in backend.items(test="merged")
        )
        return {"before": before, "after": after}
    finally:
        backend.close()


def main() -> int:
    mode = sys.argv[1]
    vdb = sys.argv[2]
    if mode == "default":
        result = run_default(vdb, Path(sys.argv[3]))
    elif mode == "strict":
        result = run_strict(vdb)
    elif mode == "reopen":
        result = run_reopen(vdb, Path(sys.argv[3]))
    else:
        raise RuntimeError(f"unknown mode: {mode}")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
