from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "x-npi"
CONFIGS = ROOT / "skills" / "tests" / "data" / "x_npi"


def _run_perf_probe(fsdb: Path, mode: str, edge: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL / "scripts")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/tests/x_npi_perf_probe.py"),
            "--fsdb",
            str(fsdb),
            "--config",
            str(CONFIGS / "axi_vip.json"),
            "--mode",
            mode,
            "--edge",
            edge,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-8000:]
    return json.loads(proc.stdout)


def test_x_npi_streaming_performance_guard(xverif_fixture: Any) -> None:
    thresholds = json.loads(
        (CONFIGS / "performance_thresholds.v1.json").read_text(encoding="utf-8")
    )
    assert thresholds["schema"] == "x-npi.performance-thresholds.v1"
    resources = xverif_fixture("xdebug.axi_vip")
    fsdb = resources / "out/regression/test/axi_fixed_delay/waves.fsdb"
    neg_pairs: list[dict[str, Any]] = []
    expected_sample_count: int | None = None
    for round_index in range(5):
        execution_order = (
            ("legacy", "stream")
            if round_index % 2 == 0
            else ("stream", "legacy")
        )
        pair: dict[str, Any] = {
            "round": round_index + 1,
            "execution_order": list(execution_order),
            "samples": {},
        }
        neg_pairs.append(pair)
        for mode in execution_order:
            sample = _run_perf_probe(fsdb, mode, "negedge")
            pair["samples"][mode] = sample
            sample_count = int(sample["sample_count"])
            if expected_sample_count is None:
                expected_sample_count = sample_count
            assert sample_count == expected_sample_count, (
                "negedge probe sample_count mismatch: "
                f"expected={expected_sample_count}, actual={sample_count}, "
                f"round={round_index + 1}, mode={mode}, "
                f"samples={json.dumps(neg_pairs, sort_keys=True)}"
            )

    neg_legacy_samples = [pair["samples"]["legacy"] for pair in neg_pairs]
    neg_stream_samples = [pair["samples"]["stream"] for pair in neg_pairs]
    neg_samples_json = json.dumps(neg_pairs, sort_keys=True)
    neg_legacy_cpu = float(median(sample["cpu_sec"] for sample in neg_legacy_samples))
    neg_stream_cpu = float(median(sample["cpu_sec"] for sample in neg_stream_samples))
    assert neg_legacy_cpu > 0.0, (
        f"negedge legacy median CPU must be positive: samples={neg_samples_json}"
    )
    neg_cpu_ratio = neg_stream_cpu / neg_legacy_cpu
    neg_cpu_target = thresholds["informational_targets"][
        "negedge_median_cpu_ratio"
    ]
    neg_legacy_rss = float(median(sample["max_rss_kb"] for sample in neg_legacy_samples))
    neg_stream_rss = float(median(sample["max_rss_kb"] for sample in neg_stream_samples))
    assert neg_legacy_rss > 0.0, (
        f"negedge legacy median RSS must be positive: samples={neg_samples_json}"
    )
    neg_rss_ratio = neg_stream_rss / neg_legacy_rss
    neg_rss_limit = thresholds["hard_regression_limits"][
        "negedge_median_rss_ratio"
    ]
    assert neg_rss_ratio <= neg_rss_limit, (
        "negedge median RSS regression: "
        f"legacy={neg_legacy_rss:.1f}, stream={neg_stream_rss:.1f}, "
        f"ratio={neg_rss_ratio:.9f}, limit={neg_rss_limit:.9f}, "
        f"samples={neg_samples_json}"
    )

    pos_legacy = _run_perf_probe(fsdb, "legacy", "posedge")
    pos_stream = _run_perf_probe(fsdb, "stream", "posedge")
    pos_samples = {"legacy": pos_legacy, "stream": pos_stream}
    pos_samples_json = json.dumps(pos_samples, sort_keys=True)
    assert pos_stream["sample_count"] == pos_legacy["sample_count"], (
        f"posedge probe sample_count mismatch: samples={pos_samples_json}"
    )
    assert pos_legacy["cpu_sec"] > 0.0, (
        f"posedge legacy CPU must be positive: samples={pos_samples_json}"
    )
    pos_cpu_ratio = pos_stream["cpu_sec"] / pos_legacy["cpu_sec"]
    pos_cpu_target = thresholds["informational_targets"]["posedge_cpu_ratio"]
    observations = {
        "negedge_median_cpu_ratio": neg_cpu_ratio,
        "negedge_median_cpu_target_met": neg_cpu_ratio <= neg_cpu_target,
        "negedge_median_rss_ratio": neg_rss_ratio,
        "posedge_cpu_ratio": pos_cpu_ratio,
        "posedge_cpu_target_met": pos_cpu_ratio <= pos_cpu_target,
    }
    print("X_NPI_PERFORMANCE_TARGETS=" + json.dumps(observations, sort_keys=True))


def test_x_npi_large_vdb_exclusion_scans_only_selected_metric(
    xverif_fixture: Any, tmp_path: Path,
) -> None:
    resources = xverif_fixture("xcov.large_summary")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL / "scripts")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/tests/x_npi_large_exclusion_probe.py"),
            "--vdb", str(resources / "large_summary.vdb"),
            "--output-root", str(tmp_path / "large-exclusion"),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-8000:] + "\n" + proc.stdout[-4000:]
    result = json.loads(proc.stdout)
    code, functional, assertion, container = result["items"]
    assert code["preflight_passes"] == 1
    assert code["apply_passes"] == 1
    assert code["matched_count"] == 1
    assert code["visited_handle_count"] > 0
    assert functional["visited_handle_count"] == 0
    assert assertion["visited_handle_count"] == 0
    assert container["preflight_passes"] == 0
    assert container["apply_passes"] == 0
    assert container["visited_handle_count"] == 0
    assert all(Path(item["path"]).is_file() for item in result["items"])
