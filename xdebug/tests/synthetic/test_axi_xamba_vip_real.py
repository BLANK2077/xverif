from __future__ import annotations

import json
import re
from collections import Counter
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


def _axi_config(prefix: str) -> dict[str, Any]:
    names = (
        "awaddr", "awid", "awlen", "awsize", "awburst", "awvalid",
        "awready", "wdata", "wstrb", "wlast", "wvalid", "wready",
        "bid", "bresp", "bvalid", "bready", "araddr", "arid", "arlen",
        "arsize", "arburst", "arvalid", "arready", "rid", "rdata",
        "rresp", "rlast", "rvalid", "rready",
    )
    return {
        **{name: prefix + "." + name for name in names},
        "clock": prefix + ".aclk",
        "reset": {"signal": prefix + ".aresetn", "polarity": "active_low"},
        "edge": "posedge",
    }


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.axi
@pytest.mark.vip
@pytest.mark.regression
@pytest.mark.slow
def test_axi_xamba_vip_waveform_actions(
    cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    xverif_fixture: Any,
) -> None:
    fixture_dir = xdebug_root / "testdata" / "waveform" / "axi_xamba_vip_real"
    manifest = json.loads(
        (fixture_dir / "manifest.json").read_text(encoding="utf-8")
    )
    resources_root = xverif_fixture("xdebug.axi_xamba_vip")
    resources = manifest["resources"]
    fsdb = resources_root / resources["fsdb"]
    daidir = resources_root / resources["daidir"]
    sim_log = resources_root / resources["simulation_log"]
    oracle_path = resources_root / resources["handshake_oracle"]
    run_manifest = resources_root / resources["run_manifest"]
    extra_sources_manifest = resources_root / resources["extra_sources_manifest"]
    resolved_filelist = resources_root / resources["resolved_filelist"]

    assert fsdb.is_file() and fsdb.stat().st_size > 1024
    assert daidir.is_dir()
    assert run_manifest.is_file()
    assert "count=2" in extra_sources_manifest.read_text(encoding="utf-8")
    resolved_text = resolved_filelist.read_text(encoding="utf-8")
    assert "/tb_clean/" not in resolved_text
    assert "/src_clean/axi/xam_axi_pkg.sv" in resolved_text
    oracle = [
        json.loads(line)
        for line in oracle_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    channels = Counter(row["channel"] for row in oracle)
    write_count = channels["b"]
    read_count = sum(
        row["channel"] == "r" and row["last"] == 1 for row in oracle
    )
    assert channels["aw"] == write_count
    assert channels["ar"] == read_count
    assert write_count + read_count == manifest["expected"]["transactions"]

    log_text = sim_log.read_text(encoding="utf-8", errors="replace")
    assert "UVM_ERROR :    0" in log_text
    assert "UVM_FATAL :    0" in log_text
    assert manifest["expected"]["pass_marker"] in log_text
    marker = re.search(r"ops=64 writes=(\d+) reads=(\d+) events=(\d+)", log_text)
    assert marker is not None
    assert (int(marker.group(1)), int(marker.group(2))) == (
        write_count, read_count
    )

    opened = _query(
        cli_runner,
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "axi_xamba_vip_real"},
        },
        case_name="axi-xamba-session-open",
        artifact_root=artifact_root,
        manifest=manifest,
    )
    session_id = opened["session"]["session_id"]
    target = {"session_id": session_id}

    try:
        loaded = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "axi.config.load",
                "target": target,
                "args": {
                    "name": "axi0",
                    "config": _axi_config(manifest["interface"]),
                },
            },
            case_name="axi-xamba-config-load",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert loaded["summary"]["status"] == "loaded"

        for direction, expected_count in (
            ("write", write_count), ("read", read_count)
        ):
            counted = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "axi.query",
                    "target": target,
                    "args": {"name": "axi0", "direction": direction},
                },
                case_name="axi-xamba-query-" + direction,
                artifact_root=artifact_root,
                manifest=manifest,
            )
            assert counted["summary"]["total_count"] == expected_count
            assert counted["summary"]["returned_count"] == 0
            assert counted["summary"]["scan_complete"] is True
            assert counted["summary"]["analysis_complete"] is True

        statistics = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "axi.statistics",
                "target": target,
                "args": {"name": "axi0"},
            },
            case_name="axi-xamba-statistics",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        summary = statistics["summary"]
        assert summary["scanned_transaction_count"] == write_count + read_count
        assert summary["matched_write_count"] == write_count
        assert summary["matched_read_count"] == read_count
        assert summary["unresolved_transaction_count"] == 0
        assert summary["full_scan_count"] == 1

        first_write = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "axi.query",
                "target": target,
                "args": {
                    "name": "axi0",
                    "direction": "write",
                    "query": {"index": 1},
                },
            },
            case_name="axi-xamba-first-write",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        transaction = first_write["data"]["transaction"]
        assert transaction["direction"] == "write"
        assert transaction["phase_order"] in {
            "aw_before_w", "w_before_aw", "same_cycle"
        }
        assert transaction["response"]["resp"] in {"2'h0", "2'h2", "2'h3"}

        time_range = {"begin": "0ns", "end": "1ms"}
        paired = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "axi.request_response_pair",
                "target": target,
                "args": {
                    "name": "axi0", "time_range": time_range,
                    "line_limit": 1000,
                },
            },
            case_name="axi-xamba-request-response-pair",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert paired["summary"]["total_count"] == write_count + read_count
        assert paired["summary"]["returned_count"] == write_count + read_count
        assert paired["summary"]["analysis_complete"] is True
        assert paired["summary"]["response_truncated"] is False

        pending = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "axi.analysis",
                "target": target,
                "args": {
                    "name": "axi0", "analysis": "pending", "direction": "all"
                },
            },
            case_name="axi-xamba-pending",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert pending["summary"]["total_count"] == 0
        assert pending["data"]["pending_transactions"] == []

        for op in ("begin", "last"):
            cursor = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "axi.transaction.cursor",
                    "target": target,
                    "args": {"name": "axi0", "op": op, "direction": "all"},
                },
                case_name="axi-xamba-cursor-" + op,
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
