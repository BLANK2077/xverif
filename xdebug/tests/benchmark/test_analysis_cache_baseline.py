from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

from runner import CliRunner, HybridCliRunner


SAMPLE_COUNT = 3
STREAM_PACKET_GOLDEN = {
    "summary": {
        "stream": "ready_packet",
        "transfer_count": 20000,
        "complete_packet_count": 5000,
        "partial_packet_count": 0,
        "packet_count_status": "exact",
        "analysis_complete": True,
    },
    "packet": {
        "packet_index": 3,
        "start_cycle": 18,
        "start_time": "185ns",
        "end_cycle": 21,
        "end_time": "215ns",
        "beat_count": 4,
        "partial_begin": False,
        "partial_end": False,
        "opcode": "8'ha3",
        "first_data": "32'h4000000c",
        "last_data": "32'h4000000f",
        "first_seq": "16'h000c",
        "last_seq": "16'h000f",
    },
}
STREAM_XOUT_GOLDEN_LINES = [
    "packet_stable_fields    : opcode=8'ha3",
    "18     185ns  0           data=32'h4000000c seq=16'hc",
]


def _require_success(result: Any, action: str) -> dict[str, Any]:
    assert result.returncode == 0 and not result.timed_out, (
        f"{action} failed rc={result.returncode} timeout={result.timed_out}\n"
        f"stdout:\n{result.stdout_raw[-4000:]}\nstderr:\n{result.stderr_raw[-4000:]}"
    )
    assert isinstance(result.response, dict) and result.response.get("ok") is True
    return result.response


def _query(
    runner: CliRunner,
    action: str,
    *,
    target: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
    output_format: str = "json",
    timeout_sec: float = 240.0,
) -> Any:
    request: dict[str, Any] = {
        "api_version": "xdebug.v1",
        "action": action,
        "args": args or {},
    }
    if action not in {"session.open", "session.close"}:
        request["limits"] = {"timeout_ms": int(timeout_sec * 1000)}
    if target is not None:
        request["target"] = target
    result = runner.run(
        request,
        output_format=output_format,
        timeout_sec=timeout_sec + 30.0,
    )
    if output_format == "xout":
        assert result.returncode == 0 and not result.timed_out
        assert isinstance(result.response, str)
        return result
    _require_success(result, action)
    return result


def _query_expect_error(
    runner: CliRunner,
    action: str,
    *,
    target: dict[str, Any],
    args: dict[str, Any],
    expected_code: str,
    timeout_sec: float = 240.0,
) -> Any:
    request = {
        "api_version": "xdebug.v1",
        "action": action,
        "target": target,
        "args": args,
        "limits": {"timeout_ms": int(timeout_sec * 1000)},
    }
    result = runner.run(
        request,
        output_format="json",
        timeout_sec=timeout_sec + 30.0,
    )
    assert result.returncode == 1 and not result.timed_out, (
        f"{action} unexpectedly succeeded or timed out\n"
        f"stdout:\n{result.stdout_raw[-4000:]}\n"
        f"stderr:\n{result.stderr_raw[-4000:]}"
    )
    assert isinstance(result.response, dict)
    assert result.response.get("ok") is False
    assert result.response.get("action") == action
    error = result.response.get("error")
    assert isinstance(error, dict)
    assert error.get("code") == expected_code
    assert error.get("error_layer") == "handler"
    return result


def _open_session(
    runner: CliRunner,
    fsdb: Path,
    name: str,
    probe_path: Path,
) -> tuple[dict[str, str], int]:
    result = _query(
        runner,
        "session.open",
        target={"fsdb": str(fsdb)},
        args={"name": name},
    )
    response = result.response
    session = response["session"]
    initialized = [
        row for row in _all_probe_rows(probe_path)
        if row["event"] == "engine_initialized"
    ]
    assert initialized, "engine did not publish the test-only initialized probe"
    return {"session_id": session["session_id"]}, int(initialized[-1]["pid"])


def _kill_session(runner: CliRunner, target: dict[str, str]) -> None:
    _query(runner, "session.close", args={"mode": "force"}, target=target, timeout_sec=60.0)


def _rss_bytes(pid: int) -> int:
    status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise AssertionError(f"VmRSS is missing for engine pid {pid}")


def _all_probe_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _probe_rows(path: Path, pid: int) -> list[dict[str, Any]]:
    return [row for row in _all_probe_rows(path) if int(row["pid"]) == pid]


def _percentile(values: list[int], percentile: float) -> int:
    assert values
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _summarize(
    cold_ms: list[int],
    hot_ms: list[int],
    rss_delta_bytes: list[int],
    estimated_bytes: list[int],
    scanner_invocations: list[int],
    canonical_entry_counts: list[int],
    index_counts: list[int],
) -> dict[str, Any]:
    ratios = [
        delta / estimate
        for delta, estimate in zip(rss_delta_bytes, estimated_bytes)
        if delta > 0 and estimate > 0
    ]
    return {
        "sample_count": len(cold_ms),
        "cold_ms": cold_ms,
        "cold_p50_ms": int(statistics.median(cold_ms)),
        "cold_p95_ms": _percentile(cold_ms, 0.95),
        "hot_ms": hot_ms,
        "hot_p50_ms": int(statistics.median(hot_ms)),
        "hot_p95_ms": _percentile(hot_ms, 0.95),
        "rss_delta_bytes": rss_delta_bytes,
        "max_rss_delta_bytes": max(rss_delta_bytes),
        "estimated_bytes": estimated_bytes,
        "max_estimated_bytes": max(estimated_bytes),
        "max_rss_to_estimate_ratio": max(ratios, default=0.0),
        "scanner_invocations": scanner_invocations,
        "canonical_entry_counts": canonical_entry_counts,
        "max_canonical_entries": max(canonical_entry_counts),
        "index_counts": index_counts,
        "max_indexes": max(index_counts),
    }


def _apb_config(manifest: dict[str, Any]) -> dict[str, Any]:
    prefix = manifest["interface"]
    top = manifest["top"]
    return {
        "paddr": prefix + ".paddr",
        "pwdata": prefix + ".pwdata",
        "prdata": prefix + ".prdata[0]",
        "pwrite": prefix + ".pwrite",
        "penable": prefix + ".penable",
        "psel": prefix + ".psel[0]",
        "pready": prefix + ".pready[0]",
        "pslverr": prefix + ".pslverr[0]",
        "clock": top + ".clk",
        "reset": {"signal": top + ".rst_n", "polarity": "active_low"},
        "edge": "posedge",
    }


def _axi_config(manifest: dict[str, Any]) -> dict[str, Any]:
    prefix = manifest["interface"]
    config = {
        name: prefix + "." + name
        for name in (
            "awaddr", "awid", "awlen", "awsize", "awburst", "awvalid", "awready",
            "wdata", "wstrb", "wlast", "wvalid", "wready",
            "bid", "bresp", "bvalid", "bready",
            "araddr", "arid", "arlen", "arsize", "arburst", "arvalid", "arready",
            "rid", "rdata", "rresp", "rlast", "rvalid", "rready",
        )
    }
    config.update({
        "clock": manifest["top"] + ".clk",
        "reset": {
            "signal": manifest["top"] + ".rst_n",
            "polarity": "active_low",
        },
        "edge": "posedge",
    })
    return config


def _stream_packet_projection(response: dict[str, Any]) -> dict[str, Any]:
    summary = response["summary"]
    packet = response["data"]["packet"]
    return {
        "summary": {
            key: summary[key]
            for key in STREAM_PACKET_GOLDEN["summary"]
        },
        "packet": {
            "packet_index": packet["packet_index"],
            "start_cycle": packet["start_cycle"],
            "start_time": packet["start_time"],
            "end_cycle": packet["end_cycle"],
            "end_time": packet["end_time"],
            "beat_count": packet["beat_count"],
            "partial_begin": packet["partial_begin"],
            "partial_end": packet["partial_end"],
            "opcode": packet["packet_stable_fields"]["opcode"]["value"],
            "first_data": packet["first_fields"]["data"]["value"],
            "last_data": packet["last_fields"]["data"]["value"],
            "first_seq": packet["first_fields"]["seq"]["value"],
            "last_seq": packet["last_fields"]["seq"]["value"],
        },
    }


def test_analysis_cache_phase0_baseline(
        persistent_cli_runner: HybridCliRunner,
        xdebug_root: Path,
        tmp_path: Path,
        xverif_fixture: Any,
) -> None:
    cli_runner = persistent_cli_runner
    probe_path = tmp_path / "analysis-probe.jsonl"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(probe_path)

    apb_manifest = json.loads(
        (xdebug_root / "testdata/waveform/apb_vip_real/manifest.json").read_text()
    )
    axi_manifest = json.loads(
        (xdebug_root / "testdata/waveform/axi_vip_real/manifest.json").read_text()
    )
    stream_config = xdebug_root / "testdata/waveform/stream_v1/config/streams.json"
    thresholds = json.loads(
        (Path(__file__).with_name("analysis_cache_thresholds.v1.json")).read_text()
    )
    assert thresholds["schema"] == "xdebug.analysis-cache-thresholds.v1"
    assert thresholds["sample_count"] == SAMPLE_COUNT
    apb_resources = xverif_fixture("xdebug.apb_vip")
    axi_resources = xverif_fixture("xdebug.axi_vip")
    stream_resources = xverif_fixture("xdebug.stream_v1")

    metrics: dict[str, dict[str, Any]] = {}
    for protocol in ("apb", "axi", "stream"):
        cold_ms: list[int] = []
        hot_ms: list[int] = []
        rss_delta_bytes: list[int] = []
        estimated_bytes: list[int] = []
        scanner_invocations: list[int] = []
        canonical_entry_counts: list[int] = []
        index_counts: list[int] = []

        for sample in range(SAMPLE_COUNT):
            if protocol == "apb":
                fsdb = apb_resources / apb_manifest["resources"]["fsdb"]
            elif protocol == "axi":
                fsdb = axi_resources / axi_manifest["runs"][0]["fsdb"]
            else:
                fsdb = stream_resources / "out/waves.fsdb"
            target, pid = _open_session(
                cli_runner, fsdb, f"cache_baseline_{protocol}_{sample}", probe_path
            )
            try:
                if protocol == "apb":
                    action = "apb.query"
                    args = {"name": "apb0", "direction": "all"}
                    warmup_args = {
                        "name": "__analysis_cache_validator_warmup__",
                        "direction": "all",
                    }
                elif protocol == "axi":
                    action = "axi.query"
                    args = {
                        "name": "axi0",
                        "direction": "write",
                        "query": {"index": 1},
                    }
                    warmup_args = {
                        "name": "__analysis_cache_validator_warmup__",
                        "direction": "write",
                        "query": {"index": 1},
                    }
                else:
                    action = "stream.query"
                    args = {
                        "stream": "ready_packet",
                        "query": "packet_at",
                        "packet_index": 3,
                        "time_range": {"begin": "0ns", "end": "250us"},
                    }
                    warmup_args = {
                        "stream": "__analysis_cache_validator_warmup__",
                        "query": "summary",
                    }

                # The RSS delta below measures the analysis repository, not
                # the server's one-time per-action schema validator.  Exercise
                # the strict action boundary with a guaranteed missing config;
                # this must return before any waveform analysis or cache event.
                probe_before_warmup = _probe_rows(probe_path, pid)
                assert probe_before_warmup
                assert int(probe_before_warmup[-1]["scanner_invocations"]) == 0
                _query_expect_error(
                    cli_runner,
                    action,
                    target=target,
                    args=warmup_args,
                    expected_code="CONFIG_NOT_FOUND",
                )
                probe_after_warmup = _probe_rows(probe_path, pid)
                assert probe_after_warmup == probe_before_warmup
                assert int(probe_after_warmup[-1]["scanner_invocations"]) == 0

                if protocol == "apb":
                    _query(
                        cli_runner, "apb.config.load", target=target,
                        args={"name": "apb0", "config": _apb_config(apb_manifest)},
                    )
                elif protocol == "axi":
                    _query(
                        cli_runner, "axi.config.load", target=target,
                        args={"name": "axi0", "config": _axi_config(axi_manifest)},
                    )
                else:
                    _query(
                        cli_runner, "stream.config.load", target=target,
                        args={"config_path": str(stream_config), "mode": "replace"},
                    )

                rss_before = _rss_bytes(pid)
                cold = _query(cli_runner, action, target=target, args=args)
                cold_ms.append(cold.elapsed_ms)
                if protocol == "stream" and sample == 0:
                    assert _stream_packet_projection(cold.response) == STREAM_PACKET_GOLDEN
                for _ in range(2):
                    hot = _query(cli_runner, action, target=target, args=args)
                    hot_ms.append(hot.elapsed_ms)
                    assert hot.response["summary"] == cold.response["summary"]
                    assert hot.response["data"] == cold.response["data"]
                if protocol == "stream" and sample == 0:
                    xout = _query(
                        cli_runner, action, target=target, args={**args, "line_limit": 1},
                        output_format="xout",
                    )
                    for golden_line in STREAM_XOUT_GOLDEN_LINES:
                        assert golden_line in xout.response
                    assert "bits:" not in xout.response
                    assert "known: true" not in xout.response

                rss_delta_bytes.append(max(0, _rss_bytes(pid) - rss_before))
                rows = _probe_rows(probe_path, pid)
                assert rows and all(row["schema"] == "xdebug.analysis-probe.v1" for row in rows)
                assert [row["access_sequence"] for row in rows] == list(
                    range(1, len(rows) + 1)
                )
                scanner_invocations.append(int(rows[-1]["scanner_invocations"]))
                canonical_entry_counts.append(max(
                    int(row["entry_count"]) for row in rows
                ))
                index_counts.append(max(int(row["index_count"]) for row in rows))
                estimated_bytes.append(max(
                    int(row["resident_bytes"] or row["build_bytes"])
                    for row in rows
                ))
            finally:
                _kill_session(cli_runner, target)

        metrics[protocol] = _summarize(
            cold_ms, hot_ms, rss_delta_bytes, estimated_bytes, scanner_invocations,
            canonical_entry_counts, index_counts,
        )

    # AXI, APB, and Stream are repository-backed after Phases 2, 3, and 4B.
    # A total of one scan per engine means every hot request, including the
    # Stream XOUT projection, added zero scanner invocations.
    assert metrics["apb"]["scanner_invocations"] == [1, 1, 1]
    assert metrics["axi"]["scanner_invocations"] == [1, 1, 1]
    assert metrics["stream"]["scanner_invocations"] == [1, 1, 1]
    for protocol, values in metrics.items():
        limits = thresholds["phase0_hard_regression_limits"][protocol]
        # RSS is page-granular; the checked-in artifact owns the measured noise budget.
        assert values["max_rss_delta_bytes"] <= (
            limits["max_rss_delta_bytes"]
            + thresholds["rss_measurement_tolerance_bytes"]
        )
        assert values["max_estimated_bytes"] <= limits["max_estimated_bytes"]
        assert values["max_canonical_entries"] <= limits["max_canonical_entries"]
        assert values["max_indexes"] <= limits["max_indexes"]

    # Latency and phase targets describe optimization progress. They are
    # reported, but only deterministic memory/scanner limits fail regression.
    latency_observations = {
        protocol: {
            key: metrics[protocol][key] <= value
            for key, value in targets.items()
        }
        for protocol, targets in thresholds["phase0_latency_targets"].items()
    }
    axi_target = thresholds["phase_targets"]["axi_repository"]
    apb_target = thresholds["phase_targets"]["apb_repository"]
    stream_target = thresholds["phase_targets"]["stream_columnar"]
    baseline_stream_rss = thresholds["phase0_baseline"]["stream"][
        "max_rss_delta_bytes"
    ]
    rss_reduction_percent = 100.0 * (
        baseline_stream_rss - metrics["stream"]["max_rss_delta_bytes"]
    ) / baseline_stream_rss
    cached_stream_target = thresholds["phase_targets"]["stream_cached"]
    phase_observations = {
        "phase0_latency": latency_observations,
        "axi_repository": {
            key: metrics["axi"][key] <= value
            for key, value in axi_target.items()
            if key != "hot_scanner_invocations"
        },
        "apb_repository": {
            key: metrics["apb"][key] <= value
            for key, value in apb_target.items()
            if key != "hot_scanner_invocations"
        },
        "stream_columnar": {
            "cold_p95_ms": metrics["stream"]["cold_p95_ms"]
            <= stream_target["cold_p95_ms"],
            "max_rss_delta_bytes": metrics["stream"]["max_rss_delta_bytes"]
            <= stream_target["max_rss_delta_bytes"],
            "minimum_rss_reduction_percent": rss_reduction_percent
            >= stream_target["minimum_rss_reduction_percent"],
        },
        "stream_cached": {
            "hot_p95_ms": metrics["stream"]["hot_p95_ms"]
            <= cached_stream_target["hot_p95_ms"],
        },
    }
    print("ANALYSIS_CACHE_PHASE_TARGETS=" + json.dumps(
        phase_observations, sort_keys=True
    ))
    print("ANALYSIS_CACHE_BASELINE=" + json.dumps(metrics, sort_keys=True))
