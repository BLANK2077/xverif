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
    extra: dict[str, Any] | None = None,
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
        case_name,
        result,
        manifest=manifest,
        extra=extra,
    )
    pytest.fail(
        "%s failed rc=%s timeout=%s; artifacts=%s\nstdout:\n%s\nstderr:\n%s"
        % (
            case_name,
            result.returncode,
            result.timed_out,
            artifact_dir,
            result.stdout_raw[-8000:],
            result.stderr_raw[-8000:],
        )
    )


def _query(
    cli_runner: CliRunner,
    request: dict[str, Any],
    *,
    case_name: str,
    artifact_root: Path,
    manifest: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = cli_runner.run(request, timeout_sec=120)
    return _require_success(
        result,
        case_name=case_name,
        artifact_root=artifact_root,
        manifest=manifest,
        extra=extra,
    )


def _resources_ready(fixture_dir: Path, manifest: dict[str, Any]) -> bool:
    resources = manifest["resources"]
    fsdb = fixture_dir / resources["fsdb"]
    daidir = fixture_dir / resources["daidir"]
    sim_log = fixture_dir / resources["simulation_log"]
    return (
        fsdb.is_file()
        and fsdb.stat().st_size > 0
        and daidir.is_dir()
        and sim_log.is_file()
    )


def _apb_probe_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        row
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
        for row in [json.loads(line)]
        if row.get("protocol") == "apb"
    ]


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.apb
@pytest.mark.vip
@pytest.mark.regression
@pytest.mark.slow
def test_apb_vip_real_wait_state_and_error_actions(
    cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    tmp_path: Path,
    xverif_fixture: Any,
) -> None:
    fixture_dir = xdebug_root / "testdata" / "waveform" / "apb_vip_real"
    manifest = json.loads(
        (fixture_dir / "manifest.json").read_text(encoding="utf-8")
    )
    resources_root = xverif_fixture("xdebug.apb_vip")
    resources = manifest["resources"]
    fsdb = resources_root / resources["fsdb"]
    daidir = resources_root / resources["daidir"]
    sim_log = resources_root / resources["simulation_log"]
    assert fsdb.is_file() and fsdb.stat().st_size > 0
    assert daidir.is_dir()
    log_text = sim_log.read_text(encoding="utf-8", errors="replace")
    assert "UVM_ERROR :    0" in log_text
    assert "UVM_FATAL :    0" in log_text
    assert "APB VIP fixture completed: writes=5 reads=5 errors=1" in log_text

    probe_path = tmp_path / "apb-analysis-probe.jsonl"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(probe_path)

    open_response = _query(
        cli_runner,
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "apb_vip_real"},
        },
        case_name="apb-vip-session-open",
        artifact_root=artifact_root,
        manifest=manifest,
    )
    session = open_response["session"]
    session_id = session["session_id"]
    target = {"session_id": session_id}
    prefix = manifest["interface"]
    config = {
        "paddr": prefix + ".paddr",
        "pwdata": prefix + ".pwdata",
        "prdata": prefix + ".prdata[0]",
        "pwrite": prefix + ".pwrite",
        "penable": prefix + ".penable",
        "psel": prefix + ".psel[0]",
        "pready": prefix + ".pready[0]",
        "pslverr": prefix + ".pslverr[0]",
        "clock": manifest["top"] + ".clk",
        "reset": {"signal": manifest["top"] + ".rst_n", "polarity": "active_low"},
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
            case_name="apb-vip-config-load",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert loaded["data"]["config"]["pready"] == config["pready"]
        assert loaded["data"]["config"]["pslverr"] == config["pslverr"]
        assert "assumptions" not in loaded["data"]

        listed = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.config.list",
                "target": target,
                "args": {"name": "apb0"},
            },
            case_name="apb-vip-config-list",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert listed["summary"]["status"] == "found"
        assert listed["data"]["config"]["pready"] == config["pready"]
        assert listed["data"]["config"]["pslverr"] == config["pslverr"]

        for direction, expected_count in (("write", 5), ("read", 5)):
            queried = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.query",
                    "target": target,
                    "args": {"name": "apb0", "direction": direction},
                },
                case_name="apb-vip-query-" + direction,
                artifact_root=artifact_root,
                manifest=manifest,
                extra={"apb_config": config, "simulation_log": log_text},
            )
            assert queried["summary"]["count"] == expected_count

        all_query = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": target,
                "args": {"name": "apb0", "query": {"line_limit": 10}},
            },
            case_name="apb-vip-query-default-all",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert all_query["summary"]["direction"] == "all"
        assert all_query["summary"]["count"] == 10
        transaction_times = [
            float(item["time"].removesuffix("ns"))
            for item in all_query["data"]["transactions"]
        ]
        assert transaction_times == sorted(transaction_times)

        all_statistics = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.statistics",
                "target": target,
                "args": {"name": "apb0"},
            },
            case_name="apb-vip-statistics-all",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert all_statistics["summary"] == {
            "name": "apb0",
            "scanned_transaction_count": 10,
            "matched_transaction_count": 10,
            "matched_read_count": 5,
            "matched_write_count": 5,
            "unresolved_transaction_count": 0,
            "filter_applied": False,
            "analysis_complete": True,
            "analysis_quality": "complete",
            "full_scan_count": 1,
        }
        assert "含 X/Z 或不可解析" in all_statistics["data"]["notes"][
            "unresolved_transaction_count"
        ]

        filtered_statistics = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.statistics",
                "target": target,
                "args": {
                    "name": "apb0",
                    "filter": {
                        "direction": "write",
                        "address": {"mode": "exact", "values": ["'h4"]},
                    },
                },
            },
            case_name="apb-vip-statistics-filtered",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert filtered_statistics["summary"]["matched_transaction_count"] == 2
        assert filtered_statistics["summary"]["matched_read_count"] == 0
        assert filtered_statistics["summary"]["matched_write_count"] == 2
        assert filtered_statistics["summary"]["full_scan_count"] == 1

        range_statistics = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.statistics",
                "target": target,
                "args": {
                    "name": "apb0",
                    "filter": {"address": {"mode": "range",
                                           "begin": "'h4", "end": "'hc"}},
                },
            },
            case_name="apb-vip-statistics-range",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert range_statistics["summary"]["matched_transaction_count"] == 7
        assert range_statistics["summary"]["full_scan_count"] == 1

        mask_statistics = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.statistics",
                "target": target,
                "args": {
                    "name": "apb0",
                    "filter": {"address": {"mode": "mask",
                                           "value": "'h8", "mask": "'h8"}},
                },
            },
            case_name="apb-vip-statistics-mask",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert mask_statistics["summary"]["matched_transaction_count"] == 4
        assert mask_statistics["summary"]["full_scan_count"] == 1

        for missing_signal in ("pready", "pslverr"):
            incomplete = dict(config)
            incomplete.pop(missing_signal)
            rejected_result = cli_runner.run(
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.config.load",
                    "target": target,
                    "args": {"name": "apb_missing_" + missing_signal, "config": incomplete},
                },
                timeout_sec=120,
            )
            rejected = rejected_result.response
            assert rejected_result.returncode != 0
            assert isinstance(rejected, dict)
            assert rejected["ok"] is False
            assert rejected["error"]["invalid_arg"].startswith("args.config")

        address_rows = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": target,
                "args": {
                    "name": "apb0",
                    "direction": "write",
                    "address": "'h4",
                    "query": {"line_limit": 10},
                },
            },
            case_name="apb-vip-address-index-lines",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert address_rows["summary"]["count"] == 2
        indexed_transactions = address_rows["data"]["transactions"]
        assert [item["addr"] for item in indexed_transactions] == [
            "32'h00000004", "32'h00000004"
        ]
        assert [item["data"] for item in indexed_transactions] == [
            "32'h55667788", "32'h0000abcd"
        ]
        assert address_rows["summary"]["value_width_complete"] is True
        assert address_rows["summary"]["width_diagnostics"] == []

        decimal_rows = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": target,
                "args": {
                    "name": "apb0",
                    "direction": "write",
                    "address": "'h4",
                    "value_format": "dec",
                    "query": {"line_limit": 10},
                },
            },
            case_name="apb-vip-address-index-decimal",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert [item["addr"] for item in decimal_rows["data"]["transactions"]] == [
            "32'd4", "32'd4"
        ]
        for case_name, selector, expected in (
            ("first", {}, indexed_transactions[0]),
            ("index", {"query": {"index": 2}}, indexed_transactions[1]),
            ("last", {"last": True}, indexed_transactions[-1]),
        ):
            selected = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.query",
                    "target": target,
                    "args": {
                        "name": "apb0",
                        "direction": "write",
                        "address": "'h4",
                        **selector,
                    },
                },
                case_name="apb-vip-address-index-" + case_name,
                artifact_root=artifact_root,
                manifest=manifest,
            )
            assert selected["summary"]["found"] is True
            assert selected["data"]["transaction"] == expected

        error_txn = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": target,
                "args": {
                    "name": "apb0",
                    "direction": "read",
                    "address": "'hf0",
                },
            },
            case_name="apb-vip-error-response",
            artifact_root=artifact_root,
            manifest=manifest,
            extra={"apb_config": config},
        )
        assert error_txn["data"]["transaction"]["has_error"] is True

        window = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.transfer_window",
                "target": target,
                "args": {
                    "name": "apb0",
                    "time_range": {"begin": "0ns", "end": "1us"},
                    "line_limit": 20,
                },
            },
            case_name="apb-vip-transfer-window",
            artifact_root=artifact_root,
            manifest=manifest,
            extra={"apb_config": config},
        )
        assert window["summary"]["total_count"] == 10
        assert window["summary"]["returned_count"] == 10
        assert window["summary"]["analysis_complete"] is True
        assert window["summary"]["response_truncated"] is False
        assert sum(
            1
            for transaction in window["data"]["transactions"]
            if transaction["has_error"]
        ) == 1

        for op in ("begin", "next", "last"):
            cursor = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.transaction.cursor",
                    "target": target,
                    "args": {
                        "name": "apb0",
                        "op": op,
                        "direction": "all",
                    },
                },
                case_name="apb-vip-cursor-" + op,
                artifact_root=artifact_root,
                manifest=manifest,
            )
            assert cursor["summary"]["found"] is True

        probe_rows = _apb_probe_rows(probe_path)
        assert probe_rows and probe_rows[-1]["scanner_invocations"] == 1
        assert sum(row.get("event") == "build" for row in probe_rows) == 1
        assert sum(row.get("event") == "index_build" for row in probe_rows) >= 1
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.kill",
                "target": {"session_id": session_id},
            },
            timeout_sec=60,
        )

    lru_probe_path = tmp_path / "apb-lru-analysis-probe.jsonl"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_MAX_BYTES"] = "1"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES"] = "2147483648"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(lru_probe_path)
    lru_open = _query(
        cli_runner,
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "apb_soft_lru"},
        },
        case_name="apb-lru-session-open",
        artifact_root=artifact_root,
        manifest=manifest,
    )
    lru_session = lru_open["session"]
    lru_target = {"session_id": lru_session["session_id"]}
    try:
        before_config = dict(config)
        before_config["sample_point"] = "before"
        after_config = dict(config)
        after_config["sample_point"] = "after"
        for name, variant in (("apb_before", before_config),
                              ("apb_after", after_config)):
            _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "apb.config.load",
                    "target": lru_target,
                    "args": {"name": name, "config": variant},
                },
                case_name="apb-lru-config-" + name,
                artifact_root=artifact_root,
                manifest=manifest,
            )
        started = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.transaction.cursor",
                "target": lru_target,
                "args": {"name": "apb_before", "op": "begin",
                         "direction": "all"},
            },
            case_name="apb-lru-cursor-begin",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        advanced = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.transaction.cursor",
                "target": lru_target,
                "args": {"name": "apb_before", "op": "next",
                         "direction": "all"},
            },
            case_name="apb-lru-cursor-next",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert started["summary"]["index"] == 1
        assert advanced["summary"]["index"] == 2
        _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": lru_target,
                "args": {"name": "apb_after", "direction": "write"},
            },
            case_name="apb-lru-second-config-query",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        resumed = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.transaction.cursor",
                "target": lru_target,
                "args": {"name": "apb_before", "op": "next",
                         "direction": "all"},
            },
            case_name="apb-lru-cursor-resume",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        assert resumed["summary"]["found"] is True
        assert resumed["summary"]["index"] == 3
        lru_rows = _apb_probe_rows(lru_probe_path)
        assert lru_rows[-1]["scanner_invocations"] == 3
        assert lru_rows[-1]["evictions"] >= 2
        assert sum(row.get("event") == "scan" for row in lru_rows) == 3
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.kill",
                "target": lru_target,
            },
            timeout_sec=60,
        )

    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_MAX_BYTES"] = "1"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES"] = "1"
    hard_open = _query(
        cli_runner,
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "apb_hard_limit"},
        },
        case_name="apb-hard-limit-session-open",
        artifact_root=artifact_root,
        manifest=manifest,
    )
    hard_session = hard_open["session"]
    hard_target = {"session_id": hard_session["session_id"]}
    try:
        _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "apb.config.load",
                "target": hard_target,
                "args": {"name": "apb0", "config": config},
            },
            case_name="apb-hard-limit-config-load",
            artifact_root=artifact_root,
            manifest=manifest,
        )
        rejected_result = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "apb.query",
                "target": hard_target,
                "args": {"name": "apb0", "direction": "write"},
            },
            timeout_sec=120,
        )
        rejected = rejected_result.response
        assert rejected_result.returncode != 0
        assert isinstance(rejected, dict) and rejected["ok"] is False
        cache_error = rejected["error"]
        assert cache_error["code"] == "ANALYSIS_MEMORY_LIMIT_EXCEEDED"
        assert cache_error["recoverable"] is True
        assert cache_error["hard_max_bytes"] == 1
        assert cache_error["protocol"] == "apb"
        assert len(cache_error["next_actions"]) == 2
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.kill",
                "target": hard_target,
            },
            timeout_sec=60,
        )
