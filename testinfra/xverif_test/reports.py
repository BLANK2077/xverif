from __future__ import annotations

import json
import tempfile
import os
import shutil
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


class ResultManager:
    def __init__(self, repo_root: Path, gate: str, catalog_version: str) -> None:
        self.repo_root = repo_root
        self.run_dir = create_run_dir(repo_root)
        (self.run_dir / "RUNNING").write_text("\n", encoding="utf-8")
        self.gate = gate
        self.catalog_version = catalog_version
        self.items: list[dict[str, Any]] = []
        self.started_at = datetime.now().astimezone().isoformat()
        self.started_monotonic = time.monotonic()

    @classmethod
    def attach(cls, repo_root: Path, run_dir: Path) -> "ResultManager":
        manager = object.__new__(cls)
        manager.repo_root = repo_root
        manager.run_dir = run_dir
        manager.gate = "worker"
        manager.catalog_version = "worker"
        manager.items = []
        manager.started_at = ""
        manager.started_monotonic = time.monotonic()
        return manager

    def relative_suite_dir(self, suite_id: str) -> str:
        return (Path(".xverif-test-results") / self.run_dir.name / "suites" / suite_id).as_posix()

    def suite_dir(self, suite_id: str) -> Path:
        path = self.run_dir / "suites" / suite_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_external_logs(self, suite_id: str, stdout: str, stderr: str) -> None:
        path = self.suite_dir(suite_id)
        (path / "stdout.log").write_text(stdout, encoding="utf-8")
        (path / "stderr.log").write_text(stderr, encoding="utf-8")

    def environment_path(self) -> Path:
        return self.run_dir / "environment.json"

    def record_report(self, report: Any) -> None:
        if report.when not in {"setup", "call", "teardown"}:
            return
        suite_id = next(
            (value for key, value in report.user_properties if key == "xverif_suite"),
            "unmapped",
        )
        if report.when == "call" or report.failed or report.skipped:
            self.items.append(
                {
                    "nodeid": report.nodeid,
                    "suite_id": suite_id,
                    "phase": report.when,
                    "outcome": report.outcome,
                    "duration_sec": report.duration,
                    "error_layer": _error_layer(report),
                }
            )
        if report.capstdout or report.capstderr:
            directory = self.suite_dir(str(suite_id))
            with (directory / "pytest-captured.log").open("a", encoding="utf-8") as stream:
                if report.capstdout:
                    stream.write(report.capstdout)
                if report.capstderr:
                    stream.write(report.capstderr)

    def finish(self, exitstatus: int) -> None:
        counts: dict[str, int] = defaultdict(int)
        suite_duration: dict[str, float] = defaultdict(float)
        for item in self.items:
            counts[item["outcome"]] += 1
            suite_duration[item["suite_id"]] += float(item["duration_sec"])
        payload = {
            "schema_version": "xverif-execution-report.v1",
            "gate": self.gate,
            "catalog_version": self.catalog_version,
            "exitstatus": int(exitstatus),
            "started_at": self.started_at,
            "finished_at": datetime.now().astimezone().isoformat(),
            "duration_sec": time.monotonic() - self.started_monotonic,
            "counts": dict(sorted(counts.items())),
            "suite_duration_sec": dict(sorted(suite_duration.items())),
            "items": self.items,
        }
        parent = os.environ.get("XVERIF_PARENT_REPORT")
        if parent:
            payload["parent_report"] = parent
        (self.run_dir / "report.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (self.run_dir / "RUNNING").unlink(missing_ok=True)


def create_run_dir(repo_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    results_root = repo_root / ".xverif-test-results"
    results_root.mkdir(parents=True, exist_ok=True)
    _prune_results(results_root)
    run_dir = Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=results_root))
    (run_dir / "RUNNING").write_text("\n", encoding="utf-8")
    return run_dir


def _prune_results(root: Path) -> None:
    now = time.time()
    runs = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
    referenced: set[Path] = set()
    records: list[tuple[Path, bool, float]] = []
    for path in runs:
        if (path / "RUNNING").exists() or (path / ".pin").exists():
            continue
        report_path = path / "report.json"
        timing_path = path / "timing.json"
        try:
            if report_path.is_file():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                success = report.get("exitstatus") == 0
            else:
                report = json.loads(timing_path.read_text(encoding="utf-8"))
                success = report.get("outcome") == "passed"
        except (OSError, json.JSONDecodeError):
            continue
        parent = report.get("parent_report")
        if parent:
            referenced.add(Path(parent).resolve().parent)
        records.append((path, success, path.stat().st_mtime))

    successful = [record for record in records if record[1]]
    delete: set[Path] = {path for path, _, _ in successful[:-20]}
    delete.update(
        path
        for path, success, modified in records
        if not success and now - modified > 30 * 24 * 60 * 60
    )
    for path in sorted(delete):
        if path.resolve() not in referenced:
            shutil.rmtree(path, ignore_errors=True)

    limit = 10 * 1024**3
    remaining = [path for path, _, _ in records if path.exists()]
    size = sum(_tree_size(path) for path in remaining)
    for path, success, _ in records:
        if size <= limit:
            break
        if not success or not path.exists() or path.resolve() in referenced:
            continue
        path_size = _tree_size(path)
        shutil.rmtree(path, ignore_errors=True)
        size -= path_size
    if size > limit:
        raise RuntimeError(
            "xverif results exceed 10 GiB and no successful unreferenced run can be removed"
        )


def _tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _error_layer(report: Any) -> str | None:
    if report.passed or report.skipped:
        return None
    text = str(report.longrepr)
    marker = "error_layer="
    if marker in text:
        return text.split(marker, 1)[1].split(";", 1)[0].splitlines()[0]
    if report.when == "call":
        return "assertion"
    return "runner"
