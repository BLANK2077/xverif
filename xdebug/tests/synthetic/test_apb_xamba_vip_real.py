from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runner import ArtifactWriter, CliRunner, RunResult


def _require_success(
    result: RunResult,
    *,
    case_name: str,
    artifact_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    response = result.response
    if (
        result.returncode == 0
        and not result.timed_out
        and isinstance(response, dict)
        and response.get("ok") is True
    ):
        return response
    artifact_dir = ArtifactWriter(artifact_root).write(
        case_name, result, manifest=manifest
    )
    pytest.fail(
        f"{case_name} failed rc={result.returncode} "
        f"timeout={result.timed_out}; artifacts={artifact_dir}\n"
        f"stdout:\n{result.stdout_raw[-8000:]}\n"
        f"stderr:\n{result.stderr_raw[-8000:]}"
    )


def _query(
    cli_runner: CliRunner,
    request: dict[str, Any],
    *,
    case_name: str,
    artifact_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    return _require_success(
        cli_runner.run(request, timeout_sec=180),
        case_name=case_name,
        artifact_root=artifact_root,
        manifest=manifest,
    )


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.apb
@pytest.mark.vip
@pytest.mark.regression
@pytest.mark.slow
def test_apb_xamba_vip_waveform_actions(
    cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    xverif_fixture: Any,
) -> None:
    fixture_dir = xdebug_root / "testdata" / "waveform" / "apb_xamba_vip_real"
    manifest = json.loads(
        (fixture_dir / "manifest.json").read_text(encoding="utf-8")
    )
    resources_root = xverif_fixture("xdebug.apb_xamba_vip")
    resources = manifest["resources"]
    fsdb = resources_root / resources["fsdb"]
    daidir = resources_root / resources["daidir"]
    sim_log = resources_root / resources["simulation_log"]
    run_manifest = resources_root / resources["run_manifest"]

    assert fsdb.is_file() and fsdb.stat().st_size > 1024
    assert daidir.is_dir()
    assert run_manifest.is_file()
    log_text = sim_log.read_text(encoding="utf-8", errors="replace")
    assert "UVM_ERROR :    0" in log_text
    assert "UVM_FATAL :    0" in log_text
    assert manifest["expected"]["pass_marker"] in log_text

    opened = _query(
        cli_runner,
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "apb_xamba_vip_real"},
        },
        case_name="apb-xamba-session-open",
        artifact_root=artifact_root,
        manifest=manifest,
    )
    session_id = opened["session"]["session_id"]
    target = {"session_id": session_id}
    prefix = manifest["interface"]
    config = {
        "paddr": prefix + ".paddr",
        "pwdata": prefix + ".pwdata",
        "prdata": prefix + ".prdata",
        "pwrite": prefix + ".pwrite",
        "penable": prefix + ".penable",
        "psel": prefix + ".psel",
        "pready": prefix + ".pready",
        "pslverr": prefix + ".pslverr",
        "clock": prefix + ".pclk",
        "reset": {"signal": prefix + ".presetn", "polarity": "active_low"},
        "edge": "posedge",
    }

    try:
        loaded = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.config.load",
                "target": target,
                "args": {"name": "apb0", "config": config},
            },
            case_name="apb-xamba-config-load",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert loaded["summary"]["status"] == "loaded"

        statistics = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.statistics",
                "target": target,
                "args": {"name": "apb0"},
            },
            case_name="apb-xamba-statistics",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        expected = manifest["expected"]
        summary = statistics["summary"]
        assert summary["scanned_transaction_count"] == expected["transactions"]
        assert summary["matched_transaction_count"] == expected["transactions"]
        assert summary["matched_write_count"] == expected["writes"]
        assert summary["matched_read_count"] == expected["reads"]
        assert summary["unresolved_transaction_count"] == 0
        assert summary["scan_complete"] is True
        assert summary["analysis_complete"] is True
        assert summary["full_scan_count"] == 1

        listed = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": target,
                "args": {"name": "apb0", "query": {"line_limit": 20}},
            },
            case_name="apb-xamba-query",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert listed["summary"]["total_count"] == expected["transactions"]
        assert listed["summary"]["returned_count"] == 20
        transactions = listed["data"]["transactions"]
        times = [float(item["time"].removesuffix("ns")) for item in transactions]
        assert times == sorted(times)
        assert {item["is_write"] for item in transactions} == {False, True}
        assert any(item["has_error"] for item in transactions)

        window = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.transfer_window",
                "target": target,
                "args": {
                    "name": "apb0",
                    "time_range": {"begin": "0ns", "end": "20us"},
                    "line_limit": 20,
                },
            },
            case_name="apb-xamba-transfer-window",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert window["summary"]["total_count"] == expected["transactions"]
        assert window["summary"]["returned_count"] == 20
        assert window["summary"]["analysis_complete"] is True
        assert window["summary"]["response_truncated"] is True

        for op in ("begin", "last"):
            cursor = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.transaction.cursor",
                    "target": target,
                    "args": {"name": "apb0", "op": op, "direction": "all"},
                },
                case_name="apb-xamba-cursor-" + op,
                artifact_root=artifact_root,
                manifest=manifest,
            )
            assert cursor["summary"]["found"] is True
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": {"session_id": session_id},
                "args": {"mode": "force"},
            },
            timeout_sec=60,
        )
