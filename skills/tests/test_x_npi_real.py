from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "x-npi"
EXAMPLES = SKILL / "scripts" / "examples"
CONFIGS = ROOT / "skills" / "tests" / "data" / "x_npi"


def _run_example(name: str, *args: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL / "scripts")
    proc = subprocess.run(
        [sys.executable, str(EXAMPLES / name), *map(str, args)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-8000:] + "\n" + proc.stdout[-4000:]
    document = json.loads(proc.stdout)
    assert document["ok"] is True
    assert document["meta"]["analysis_complete"] is True
    assert document["meta"]["time_base"] == "fsdb_tick"
    assert "NPI - Native Programming Interface" not in proc.stdout
    return document


def test_x_npi_axi_fixed_and_random_cached_waveforms(
    xverif_fixture: Any, tmp_path: Path
) -> None:
    resources = xverif_fixture("xdebug.axi_vip")
    fixed_report = tmp_path / "axi-fixed-transactions.json"
    fixed = _run_example(
        "axi_summary.py",
        "--fsdb", resources / "out/regression/test/axi_fixed_delay/waves.fsdb",
        "--config", CONFIGS / "axi_vip.json",
        "--detail", "transactions",
        "--output", fixed_report,
    )
    assert fixed["summary"]["writes"] == 32
    assert fixed["summary"]["reads"] == 32
    detail = json.loads(fixed_report.read_text(encoding="utf-8"))
    writes = detail["data"]["transactions"]["writes"]
    assert len(writes) == 32
    assert any(txn["phase_order"] == "w_before_aw" for txn in writes)

    random = _run_example(
        "axi_summary.py",
        "--fsdb", resources / "out/regression/test/axi_random_seed_7/waves.fsdb",
        "--config", CONFIGS / "axi_vip.json",
    )
    assert random["summary"]["writes"] > 0
    assert random["summary"]["reads"] > 0
    assert random["summary"]["final_write_outstanding"] == 0
    assert random["summary"]["final_read_outstanding"] == 0


def test_x_npi_apb_cached_waveform(xverif_fixture: Any) -> None:
    resources = xverif_fixture("xdebug.apb_vip")
    report = _run_example(
        "apb_summary.py",
        "--fsdb", resources / "out/regression/test/apb_vip_test/waves.fsdb",
        "--config", CONFIGS / "apb_vip.json",
    )
    assert report["summary"]["total"] == 10
    assert report["summary"]["writes"] == 5
    assert report["summary"]["reads"] == 5
    assert report["summary"]["errors"] == 1
    assert report["summary"]["wait_cycles"] == 23


def test_x_npi_stream_posedge_after_cached_waveform(xverif_fixture: Any) -> None:
    resources = xverif_fixture("xdebug.stream_v1")
    report = _run_example(
        "stream_summary.py",
        "--fsdb", resources / "out/waves.fsdb",
        "--config", CONFIGS / "stream_ready_packet.json",
    )
    assert report["meta"]["edge"] == "posedge"
    assert report["meta"]["sample_point"] == "after"
    assert report["summary"]["transfers"] == 20000
    assert report["summary"]["packets"] == 5000


def test_x_npi_exclusion_helpers_against_real_vdb(
    xverif_fixture: Any, tmp_path: Path,
) -> None:
    resources = xverif_fixture("xcov.exclusion")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL / "scripts")
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("x_npi_exclusion_probe.py")),
            str(resources / "exclusion.vdb"),
            str(tmp_path / "x-npi.el"),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-8000:] + "\n" + proc.stdout[-4000:]
    result = json.loads(proc.stdout)
    assert result["statuses"] == ["changed", "already_in_state", "changed"]
    assert result["loaded"] == [
        {"path": str(tmp_path / "x-npi.el"), "status": "loaded"},
    ]
    assert result["after_load"] is True
    assert result["after_unload"] is False


def test_x_npi_urg_reads_all_coverage_types_without_npi(
    xverif_fixture: Any, tmp_path: Path,
) -> None:
    resources = xverif_fixture("xcov.exclusion")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL / "scripts")
    proc = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES / "coverage_summary.py"),
            "--vdb", str(resources / "exclusion.vdb"),
            "--report", str(tmp_path / "urg-summary"),
            "--limit", "200",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-8000:] + "\n" + proc.stdout[-4000:]
    document = json.loads(proc.stdout)
    assert document["ok"] is True
    assert document["summary"]["data_source"] == "urg_fixed_summary"
    assert document["summary"]["npi_initialized"] is False
    assert document["summary"]["tests"] == ["variant0", "variant1"]
    assert document["summary"]["scope_count"] == 2
    assert document["summary"]["functional_row_count"] == 8
    assert document["summary"]["assertion_row_count"] == 2
    assert document["summary"]["root_score_pct"] == 60.8961
    kinds = {row["coverage_kind"] for row in document["data"]["items"]}
    assert kinds == {"code", "functional", "assertion"}
    assert "NPI - Native Programming Interface" not in proc.stdout
    assert "NPI - Native Programming Interface" not in proc.stderr
