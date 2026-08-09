from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


CASE_DOC = yaml.safe_load(
    (Path(__file__).with_name("cases.v1.yaml")).read_text(encoding="utf-8")
)


def cases(group: str) -> list[dict[str, object]]:
    return list(CASE_DOC["groups"][group])


def run_case(
    runner: Path, resources: Path, case: dict[str, object], work_dir: Path
) -> dict[str, object]:
    out = resources / "cases" / str(case["case"]) / "out"
    argv = [
            str(runner),
            "-dbdir",
            str(out / "simv.daidir"),
            "-ssf",
            str(out / "waves.fsdb"),
            "-signal",
            str(case["signal"]),
            "-time",
            str(case["time"]),
        ]
    if case.get("stop_on_temporal"):
        argv.append("--stop-on-temporal")
    proc = subprocess.run(
        argv,
        cwd=work_dir,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    start = proc.stdout.find("{")
    assert start >= 0, proc.stdout + proc.stderr
    result, _ = json.JSONDecoder().raw_decode(proc.stdout[start:])
    assert result["truncated"] is False
    assert result["active_trace_calls"] == result["total_hops"]
    if "hops" in case:
        assert result["total_hops"] == case["hops"]
    if "termination" in case:
        assert result["termination"] == case["termination"]
    if "temporal_boundaries" in case:
        assert result["temporal_boundaries"] == case["temporal_boundaries"]
    return result
