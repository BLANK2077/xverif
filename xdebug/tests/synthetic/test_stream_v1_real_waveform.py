from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from runner import (
    ArtifactWriter,
    CliRunner,
    RunResult,
)


@pytest.fixture
def cli_runner(persistent_cli_runner: CliRunner) -> CliRunner:
    return persistent_cli_runner


def _require_success(
    result: RunResult,
    *,
    case_name: str,
    artifact_root: Path,
    extra: dict[str, Any] | None = None,
) -> str:
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
    extra: dict[str, Any] | None = None,
    timeout_sec: float = 180.0,
) -> dict[str, Any]:
    result = cli_runner.run(request, timeout_sec=timeout_sec)
    return _require_success(
        result,
        case_name=case_name,
        artifact_root=artifact_root,
        extra=extra,
    )


def _query_xout_equivalent(
    cli_runner: CliRunner,
    request: dict[str, Any],
    expected_json: dict[str, Any],
    *,
    case_name: str,
    artifact_root: Path,
    timeout_sec: float = 180.0,
) -> dict[str, Any]:
    result = cli_runner.run(request, output_format="xout", timeout_sec=timeout_sec)
    if result.returncode == 0 and not result.timed_out and isinstance(result.response, str):
        assert result.response.startswith(
            "@xdebug.%s.v1\n" % request["action"]
        )
        assert "pointer\tkind\tvalue" not in result.response
        for key, expected in expected_json["summary"].items():
            if isinstance(expected, (str, int, float, bool)):
                assert key in result.response
        return result.response
    artifact_dir = ArtifactWriter(artifact_root).write(case_name, result)
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


def _stream_probe_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        row for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if row.get("protocol") == "stream"
    ]


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.stream
@pytest.mark.regression
@pytest.mark.slow
def test_stream_v1_real_waveform_actions(
    cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    tmp_path: Path,
    xverif_fixture: Any,
) -> None:
    fixture_dir = xdebug_root / "testdata" / "waveform" / "stream_v1"
    config_path = fixture_dir / "config" / "streams.json"

    resources = xverif_fixture("xdebug.stream_v1")
    fsdb = resources / "out" / "waves.fsdb"
    expected_path = resources / "out" / "stream_expected.json"
    assert fsdb.is_file() and fsdb.stat().st_size > 0
    assert expected_path.is_file()
    expected = json.loads(expected_path.read_text(encoding="utf-8"))["streams"]
    cli_runner.base_env["XDEBUG_TEST_STREAM_DIFFERENTIAL"] = "1"
    probe_path = tmp_path / "stream-analysis-probe.jsonl"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(probe_path)

    open_response = _query(
        cli_runner,
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "stream_v1_real"},
        },
        case_name="stream-v1-session-open",
        artifact_root=artifact_root,
    )
    session = open_response["session"]
    target = {"session_id": session["session_id"]}

    try:
        loaded = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.config.load",
                "target": target,
                "args": {"config_path": str(config_path), "mode": "replace"},
            },
            case_name="stream-v1-config-load",
            artifact_root=artifact_root,
            extra={"config": json.loads(config_path.read_text(encoding="utf-8"))},
        )
        assert loaded["summary"]["loaded"] == len(expected)
        assert len(loaded["data"]["validation"]) == len(expected)
        ready_preflight = next(
            item for item in loaded["data"]["validation"]
            if item["stream"] == "ready_packet"
        )
        assert ready_preflight["status"] == "ok"
        assert ready_preflight["sampling"] == {
            "clock": "clk", "edge": "posedge", "sample_point": "before"
        }
        assert ready_preflight["packet_rules"] == {
            "packet_enabled": True,
            "channel_id_valid": "every_beat",
            "allow_interleaving": False,
        }
        assert all(
            signal["status"] == "ok"
            and signal["resolved_path"]
            and signal["width"] > 0
            for signal in ready_preflight["signals"]
        )

        removed_data_fields_path = tmp_path / "removed-data-fields.json"
        removed_data_fields_path.write_text(
            json.dumps({
                "streams": [{
                    "name": "removed_data_fields",
                    "signals": {
                        "clk": "stream_v1_top.clk",
                        "vld": "stream_v1_top.vo_vld",
                        "payload": "stream_v1_top.vo_data",
                    },
                    "clock": "clk",
                    "vld": "vld",
                    "data_fields": {"payload": "payload"},
                }]
            }),
            encoding="utf-8",
        )
        removed_data_fields = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "stream.config.load",
                "target": target,
                "args": {"config_path": str(removed_data_fields_path), "mode": "append"},
            },
            timeout_sec=120,
        )
        assert removed_data_fields.response is not None
        assert removed_data_fields.response["ok"] is False
        assert removed_data_fields.response["error"]["code"] == "INVALID_ARGUMENT"
        assert "data_fields is not supported; use beat_fields" in removed_data_fields.response["error"]["message"]

        listed = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.config.list",
                "target": target,
                "args": {},
            },
            case_name="stream-v1-config-list",
            artifact_root=artifact_root,
        )
        assert listed["summary"]["count"] == len(expected)
        assert {
            row["name"] for row in listed["data"]["streams"]
        } == set(expected.keys())

        invalid_interleaving = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "stream.config.load",
                "target": target,
                "args": {
                    "mode": "append",
                    "config": {
                        "streams": [
                            {
                                "name": "bad_interleave_channel_valid",
                                "signals": {
                                    "clk": "stream_v1_top.clk",
                                    "vld": "stream_v1_top.ipkt_vld",
                                    "rdy": "stream_v1_top.ipkt_rdy",
                                    "sop": "stream_v1_top.ipkt_sop",
                                    "eop": "stream_v1_top.ipkt_eop",
                                    "chid": "stream_v1_top.ipkt_chid",
                                    "data": "stream_v1_top.ipkt_data",
                                },
                                "clock": "clk",
                                "vld": "vld",
                                "rdy": "rdy",
                                "sop": "sop",
                                "eop": "eop",
                                "channel_id": "chid",
                                "channel_id_valid": "sop",
                                "allow_interleaving": True,
                                "beat_fields": {"data": "data"},
                            }
                        ]
                    },
                },
            },
            timeout_sec=120,
        )
        assert invalid_interleaving.response is not None
        assert invalid_interleaving.response["ok"] is False
        invalid_error = invalid_interleaving.response["error"]
        assert invalid_error["code"] == "INVALID_ARGUMENT"
        assert invalid_error["error_layer"] == "handler"
        assert invalid_error["invalid_arg"] == "args.config.streams"
        assert "allow_interleaving requires channel_id_valid=every_beat" in invalid_error["message"]

        for stream_name, counts in expected.items():
            shown = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.describe",
                    "target": target,
                    "args": {"stream": stream_name},
                },
                case_name="stream-v1-show-" + stream_name,
                artifact_root=artifact_root,
            )
            assert shown["summary"]["stream"] == stream_name
            assert shown["data"]["validation"]["status"] == "ok"

            validated = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.validate",
                    "target": target,
                    "args": {
                        "stream": stream_name,
                        "time_range": {"begin": "0ns", "end": "250us"},
                        "line_limit": 512,
                    },
                },
                case_name="stream-v1-validate-" + stream_name,
                artifact_root=artifact_root,
            )
            assert validated["summary"]["ok"] is True

            summary = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.query",
                    "target": target,
                    "args": {
                        "stream": stream_name,
                        "query": "summary",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    },
                },
                case_name="stream-v1-summary-" + stream_name,
                artifact_root=artifact_root,
            )["summary"]
            assert summary["transfer_count"] == counts["transfer_count"]
            assert summary["transfer_count"] >= 10000
            assert summary["analysis_complete"] is True
            assert summary["response_truncated"] is False
            assert summary["returned_count"] == 0
            assert summary["total_count"] == counts.get(
                "packet_count",
                counts["transfer_count"],
            )
            assert summary["truncation_scopes"] == []
            if "stall_cycles" in counts:
                assert summary["stall_cycles"] == counts["stall_cycles"]
                assert summary["stall_windows"] > 0
            if "packet_count" in counts:
                assert summary["complete_packet_count"] == counts["packet_count"]
                assert summary["partial_packet_count"] == 0
                assert summary["packet_count_status"] == "exact"
                assert summary["complete_packet_count"] > 0
            else:
                assert summary["complete_packet_count"] == 0
                assert summary["partial_packet_count"] == 0
                assert summary["packet_count_status"] == "not_configured"
            if "ready_bp_conflict_count" in counts:
                assert (
                    summary["ready_bp_conflict_count"]
                    == counts["ready_bp_conflict_count"]
                )

            first = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.query",
                    "target": target,
                    "args": {
                        "stream": stream_name,
                        "query": "first_transfer",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    },
                },
                case_name="stream-v1-first-transfer-" + stream_name,
                artifact_root=artifact_root,
            )
            assert first["data"]["row"]["transfer"] is True

            last = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.query",
                    "target": target,
                    "args": {
                        "stream": stream_name,
                        "query": "last_transfer",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    },
                },
                case_name="stream-v1-last-transfer-" + stream_name,
                artifact_root=artifact_root,
            )
            assert last["data"]["row"]["transfer"] is True
            assert last["data"]["row"]["time"] == summary["last_transfer_time"]

            window = _query(
                cli_runner,
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.query",
                    "target": target,
                    "args": {
                        "stream": stream_name,
                        "query": "transfer_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                        "line_limit": 8,
                    },
                },
                case_name="stream-v1-transfer-window-" + stream_name,
                artifact_root=artifact_root,
            )
            assert len(window["data"]["rows"]) == 8
            assert window["summary"]["analysis_complete"] is True
            assert window["summary"]["response_truncated"] is True
            assert window["summary"]["returned_count"] == 8
            assert window["summary"]["total_count"] > 8
            assert window["summary"]["truncation_scopes"] == ["response_transfers"]

        partial_packet = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "query": "summary",
                    "time_range": {"begin": "65ns", "end": "75ns"},
                },
            },
            case_name="stream-v1-partial-packet-count",
            artifact_root=artifact_root,
        )["summary"]
        assert partial_packet["complete_packet_count"] == 0
        assert partial_packet["partial_packet_count"] == 1
        assert partial_packet["packet_count_status"] == "ambiguous"

        first_packet = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "query": "first_packet",
                    "time_range": {"begin": "0ns", "end": "250us"},
                },
            },
            case_name="stream-v1-first-packet",
            artifact_root=artifact_root,
        )
        assert first_packet["data"]["found"] is True
        assert first_packet["data"]["packet"]["packet_index"] == 0
        assert first_packet["data"]["packet"]["packet_stable_fields"]["opcode"]["value"] == "8'ha0"
        beat_preview = first_packet["data"]["packet"]["beat_fields_preview"]
        assert beat_preview["total_count"] == 4
        assert beat_preview["returned_count"] == 4
        assert beat_preview["response_truncated"] is False
        assert "total_beats" not in beat_preview
        assert beat_preview["head"][0]["fields"]["data"]["value"] == "32'h40000000"

        packet_at_request = {
            "request_id": "stream-v1-packet-at-xout-roundtrip",
            "api_version": "xdebug.v1",
            "action": "stream.query",
            "target": target,
            "args": {
                "stream": "ready_packet",
                "query": "packet_at",
                "packet_index": 3,
                "time_range": {"begin": "0ns", "end": "250us"},
                "line_limit": 1,
            },
        }
        packet_at = _query(
            cli_runner,
            packet_at_request,
            case_name="stream-v1-packet-at",
            artifact_root=artifact_root,
        )
        assert packet_at["data"]["found"] is True
        assert packet_at["data"]["packet"]["packet_index"] == 3
        assert packet_at["data"]["packet"]["packet_stable_fields"]["opcode"]["value"] == "8'ha3"
        packet_at_xout = _query_xout_equivalent(
            cli_runner,
            packet_at_request,
            packet_at,
            case_name="stream-v1-packet-at-xout",
            artifact_root=artifact_root,
        )
        for evidence in (
            "packet:", "3", "data=32'h4000000c",
            "seq=16'hc", "data=32'h4000000f", "seq=16'hf",
        ):
            assert evidence in packet_at_xout
        assert "\npackets:\n" not in packet_at_xout
        assert '{"data":{"value"' not in packet_at_xout
        assert '"bits":' not in packet_at_xout

        packet_oob = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "query": "packet_at",
                    "packet_index": 999999,
                    "time_range": {"begin": "0ns", "end": "250us"},
                },
            },
            case_name="stream-v1-packet-at-oob",
            artifact_root=artifact_root,
        )
        assert packet_oob["data"]["found"] is False
        assert packet_oob["data"]["packet"] is None

        mismatch_packet = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "bp_packet",
                    "query": "first_packet",
                    "time_range": {"begin": "0ns", "end": "250us"},
                },
            },
            case_name="stream-v1-stable-mismatch",
            artifact_root=artifact_root,
        )
        assert mismatch_packet["data"]["packet"]["packet_stable_mismatches"]
        assert mismatch_packet["summary"]["packet_stable_mismatch_count"] > 0

        stalls = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_stream",
                    "query": "stall_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 4,
                },
            },
            case_name="stream-v1-ready-stall-window",
            artifact_root=artifact_root,
        )
        assert stalls["data"]["stalls"]
        assert stalls["data"]["stalls"][0]["reason"] == "rdy_low"

        packets = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_bp_packet_negedge",
                    "query": "packet_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 4,
                },
            },
            case_name="stream-v1-negedge-packet-window",
            artifact_root=artifact_root,
        )
        assert len(packets["data"]["packets"]) == 4
        assert packets["summary"]["edge"] == "negedge"
        packets_xout_request = {
            "request_id": "stream-v1-packet-window-xout-roundtrip",
            "api_version": "xdebug.v1",
            "action": "stream.query",
            "target": target,
            "args": {
                "stream": "ready_bp_packet_negedge",
                "query": "packet_window",
                "time_range": {"begin": "0ns", "end": "250us"},
                "line_limit": 2,
            },
        }
        packets_xout_json = _query(
            cli_runner,
            packets_xout_request,
            case_name="stream-v1-packet-window-json",
            artifact_root=artifact_root,
        )
        packets_xout = _query_xout_equivalent(
            cli_runner,
            packets_xout_request,
            packets_xout_json,
            case_name="stream-v1-packet-window-xout",
            artifact_root=artifact_root,
        )
        for evidence in (
            "packets:", "data=32'h60000000", "seq=16'h0",
            "data=32'h60000003", "seq=16'h3", "2'h0",
        ):
            assert evidence in packets_xout
        assert '{"data":{"value"' not in packets_xout
        assert '"bits":' not in packets_xout

        interleaved = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "interleaved_packet",
                    "query": "packet_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 4,
                },
            },
            case_name="stream-v1-interleaved-packet-window",
            artifact_root=artifact_root,
        )
        assert len(interleaved["data"]["packets"]) == 4
        assert {packet["channel_id"]["value"] for packet in interleaved["data"]["packets"]} == {"2'h0", "2'h1"}
        assert all(packet["beat_count"] == 4 for packet in interleaved["data"]["packets"])

        match = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_stream",
                    "query": "transfer_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 8,
                    "filter": {"fields": {
                        "low8": {"mode": "exact", "values": ["8'h5a", "8'h5b"]},
                        "is_wr": {"mode": "range", "begin": "1'b0", "end": "1'b1"},
                        "data": {"mode": "mask", "value": "32'h0000005a", "mask": "32'h000000ff"},
                    }},
                },
            },
            case_name="stream-v1-filter-beat-fields",
            artifact_root=artifact_root,
        )
        assert match["summary"]["matched_transfer_count"] > 8
        assert match["summary"]["filter_applied"] is True
        assert match["summary"]["unresolved_filter_count"] == 0
        assert len(match["data"]["rows"]) == 8
        assert match["data"]["rows"][0]["fields"]["low8"]["value"] == "8'h5a"
        match_xout_request = {
            "request_id": "stream-v1-filter-beat-fields-xout-roundtrip",
            "api_version": "xdebug.v1",
            "action": "stream.query",
            "target": target,
            "args": {
                "stream": "ready_stream",
                "query": "transfer_window",
                "time_range": {"begin": "0ns", "end": "250us"},
                "line_limit": 2,
                "filter": {"fields": {
                    "low8": {"mode": "exact", "values": ["8'h5a"]},
                }},
            },
        }
        match_xout_json = _query(
            cli_runner,
            match_xout_request,
            case_name="stream-v1-filter-beat-fields-json",
            artifact_root=artifact_root,
        )
        match_xout = _query_xout_equivalent(
            cli_runner,
            match_xout_request,
            match_xout_json,
            case_name="stream-v1-filter-beat-fields-xout",
            artifact_root=artifact_root,
        )
        for evidence in (
            "rows:", "low8", "8'h5a", "data", "32'h2000015a",
            "channel",
        ):
            assert evidence in match_xout
        assert '{"addr":{"value"' not in match_xout
        assert '"bits":' not in match_xout

        scalar_data_filter = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "valid_only",
                    "query": "transfer_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 2,
                    "filter": {"fields": {
                        "data": {"mode": "exact", "values": ["32'h1000005a"]},
                    }},
                },
            },
            case_name="stream-v1-filter-scalar-data",
            artifact_root=artifact_root,
        )
        assert scalar_data_filter["summary"]["matched_transfer_count"] == 1
        assert scalar_data_filter["data"]["rows"][0]["fields"]["data"]["value"] == "32'h1000005a"

        for case_name, stream_name, query, invalid_filter, invalid_arg in (
            (
                "packet-position-required", "ready_packet", "packet_window",
                {"fields": {"opcode": {"mode": "exact", "values": ["8'ha0"]}}},
                "args.filter.position",
            ),
            (
                "beat-position-forbidden", "ready_stream", "transfer_window",
                {"position": "sop", "fields": {"low8": {"mode": "exact", "values": ["8'h5a"]}}},
                "args.filter.position",
            ),
            (
                "filter-query-mismatch", "ready_stream", "stall_window",
                {"fields": {"low8": {"mode": "exact", "values": ["8'h5a"]}}},
                "args.query",
            ),
        ):
            invalid = cli_runner.run(
                {
                    "api_version": "xdebug.v1",
                    "action": "stream.query",
                    "target": target,
                    "args": {
                        "stream": stream_name,
                        "query": query,
                        "time_range": {"begin": "0ns", "end": "250us"},
                        "filter": invalid_filter,
                    },
                },
                timeout_sec=120,
            )
            assert invalid.response is not None and invalid.response["ok"] is False, case_name
            assert invalid.response["error"]["code"] == "INVALID_ARGUMENT"
            assert invalid.response["error"]["invalid_arg"] == invalid_arg

        packet_filter = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "query": "packet_window",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 1,
                    "filter": {
                        "position": "sop",
                        "fields": {
                            "opcode": {"mode": "exact", "values": ["8'ha3"]},
                            "seq": {"mode": "range", "begin": "16'd12", "end": "16'd12"},
                            "data": {"mode": "mask", "value": "32'h0c", "mask": "32'hff"},
                        },
                    },
                },
            },
            case_name="stream-v1-filter-packet-sop",
            artifact_root=artifact_root,
        )
        assert packet_filter["summary"]["matched_packet_count"] == 1
        assert packet_filter["summary"]["unresolved_filter_count"] == 0
        assert packet_filter["data"]["packets"][0]["packet_index"] == 3
        assert packet_filter["data"]["packets"][0]["beat_count"] == 4

        partial_filter = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "query": "summary",
                    "time_range": {"begin": "65ns", "end": "75ns"},
                    "filter": {
                        "position": "eop",
                        "fields": {"opcode": {"mode": "exact", "values": ["8'ha0"]}},
                    },
                },
            },
            case_name="stream-v1-filter-partial-boundary",
            artifact_root=artifact_root,
        )
        assert partial_filter["summary"]["matched_packet_count"] == 0
        assert partial_filter["summary"]["unresolved_filter_count"] == 1

        channel = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.query",
                "target": target,
                "args": {
                    "stream": "ready_stream",
                    "query": "transfer_window",
                    "channel": "3",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "line_limit": 8,
                },
            },
            case_name="stream-v1-channel-filter",
            artifact_root=artifact_root,
        )
        assert channel["data"]["rows"]
        assert all(row["channel_id"]["value"] == "2'h3" for row in channel["data"]["rows"])

        transfer_out = tmp_path / "ready_stream.tsv"
        exported = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.export",
                "target": target,
                "args": {
                    "stream": "ready_stream",
                    "kind": "transfer",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "output": {"path": str(transfer_out), "file_format": "tsv"},
                },
            },
            case_name="stream-v1-export-transfer",
            artifact_root=artifact_root,
        )
        assert Path(exported["summary"]["output"]["path"]).is_file()
        assert Path(exported["summary"]["output"]["meta_path"]).is_file()
        assert exported["summary"]["row_count"] == expected["ready_stream"]["transfer_count"]

        packet_out = tmp_path / "ready_packet.tsv"
        packet_exported = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.export",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "kind": "packet",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "output": {"path": str(packet_out), "file_format": "tsv"},
                },
            },
            case_name="stream-v1-export-packet",
            artifact_root=artifact_root,
        )
        assert Path(packet_exported["summary"]["output"]["path"]).is_file()
        assert Path(packet_exported["summary"]["output"]["meta_path"]).is_file()
        assert packet_exported["summary"]["row_count"] == expected["ready_packet"]["packet_count"]

        packet_beats_out = tmp_path / "ready_packet_beats.tsv"
        packet_beats_exported = _query(
            cli_runner,
            {
                "api_version": "xdebug.v1",
                "action": "stream.export",
                "target": target,
                "args": {
                    "stream": "ready_packet",
                    "kind": "packet_beats",
                    "time_range": {"begin": "0ns", "end": "250us"},
                    "output": {"path": str(packet_beats_out), "file_format": "tsv"},
                },
            },
            case_name="stream-v1-export-packet-beats",
            artifact_root=artifact_root,
        )
        assert Path(packet_beats_exported["summary"]["output"]["path"]).is_file()
        assert Path(packet_beats_exported["summary"]["output"]["meta_path"]).is_file()
        assert packet_beats_exported["summary"]["row_count"] == expected["ready_packet"]["transfer_count"]
        assert "packet_index\tchannel_id\tbeat_index" in packet_beats_out.read_text(encoding="utf-8").splitlines()[0]
        probe_rows = _stream_probe_rows(probe_path)
        assert probe_rows and probe_rows[-1]["scanner_invocations"] == len(expected)
        assert sum(row["event"] == "scan" for row in probe_rows) == len(expected)
        assert sum(row["event"] == "build" for row in probe_rows) == len(expected)
        assert sum(row["event"] == "hit" for row in probe_rows) > len(expected)
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close", "args": {"mode": "force"},
                "target": target,
            },
            timeout_sec=60,
        )


@pytest.mark.synthetic
@pytest.mark.waveform
@pytest.mark.stream
@pytest.mark.regression
@pytest.mark.slow
def test_stream_v1_cache_scope_repository_contract(
    cli_runner: CliRunner,
    xdebug_root: Path,
    artifact_root: Path,
    tmp_path: Path,
    xverif_fixture: Any,
) -> None:
    resources = xverif_fixture("xdebug.stream_v1")
    fsdb = resources / "out" / "waves.fsdb"
    configs = json.loads((
        xdebug_root / "testdata/waveform/stream_v1/config/streams.json"
    ).read_text(encoding="utf-8"))["streams"]
    ready_packet = next(
        config for config in configs if config["name"] == "ready_packet"
    )
    range_a = {"begin": "0ns", "end": "5us"}
    range_b = {"begin": "5us", "end": "10us"}

    probe_path = tmp_path / "stream-cache-scope-probe.jsonl"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(probe_path)
    cli_runner.base_env["XDEBUG_TEST_STREAM_DIFFERENTIAL"] = "1"
    opened = _query(
        cli_runner,
        {"api_version": "xdebug.v1", "action": "session.open",
         "target": {"fsdb": str(fsdb)},
         "args": {"name": "stream_cache_scope"}},
        case_name="stream-cache-scope-open",
        artifact_root=artifact_root,
    )
    session = opened["session"]
    target = {"session_id": session["session_id"]}
    try:
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.config.load",
             "target": target,
             "args": {"config": {"streams": [ready_packet]}, "mode": "replace"}},
            case_name="stream-cache-scope-load",
            artifact_root=artifact_root,
        )
        static_validate = _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.validate",
             "target": target,
             "args": {"stream": "ready_packet", "dynamic": False}},
            case_name="stream-cache-scope-static-validate",
            artifact_root=artifact_root,
        )
        assert static_validate["summary"]["dynamic_requested"] is False
        assert not _stream_probe_rows(probe_path)

        first_range = _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range", "time_range": range_a}},
            case_name="stream-cache-scope-range-a",
            artifact_root=artifact_root,
        )
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.export",
             "target": target,
             "args": {"stream": "ready_packet", "kind": "packet",
                      "cache_scope": "range", "time_range": range_a,
                      "line_limit": 2}},
            case_name="stream-cache-scope-range-a-export-hit",
            artifact_root=artifact_root,
        )
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.validate",
             "target": target,
             "args": {"stream": "ready_packet", "dynamic": True,
                      "cache_scope": "range", "time_range": range_a}},
            case_name="stream-cache-scope-range-a-validate-hit",
            artifact_root=artifact_root,
        )
        second_range = _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range", "time_range": range_b}},
            case_name="stream-cache-scope-range-b",
            artifact_root=artifact_root,
        )
        assert first_range["summary"]["requested_range"] != \
            second_range["summary"]["requested_range"]
        rows = _stream_probe_rows(probe_path)
        assert rows[-1]["scanner_invocations"] == 2
        assert sum(row["event"] == "build" for row in rows) == 2

        full_from_range = _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "full", "time_range": range_a}},
            case_name="stream-cache-scope-full-build",
            artifact_root=artifact_root,
        )
        assert full_from_range["summary"] == first_range["summary"]
        rows = _stream_probe_rows(probe_path)
        assert rows[-1]["scanner_invocations"] == 3
        assert sum(row["event"] == "invalidate" for row in rows) == 2

        derived_range = _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range", "time_range": range_b}},
            case_name="stream-cache-scope-range-rebuild-after-full",
            artifact_root=artifact_root,
        )
        assert derived_range["summary"] == second_range["summary"]
        assert _stream_probe_rows(probe_path)[-1]["scanner_invocations"] == 4

        same_semantics = copy.deepcopy(ready_packet)
        same_semantics["description"] = "description-only replacement"
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.config.load",
             "target": target,
             "args": {"config": {"streams": [same_semantics]}, "mode": "replace"}},
            case_name="stream-cache-scope-description-replace",
            artifact_root=artifact_root,
        )
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "full", "time_range": range_a}},
            case_name="stream-cache-scope-description-hit",
            artifact_root=artifact_root,
        )
        assert _stream_probe_rows(probe_path)[-1]["scanner_invocations"] == 4

        changed_semantics = copy.deepcopy(same_semantics)
        changed_semantics["sample_point"] = "after"
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.config.load",
             "target": target,
             "args": {"config": {"streams": [changed_semantics]}, "mode": "replace"}},
            case_name="stream-cache-scope-semantic-replace",
            artifact_root=artifact_root,
        )
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "full", "time_range": range_a}},
            case_name="stream-cache-scope-semantic-rebuild",
            artifact_root=artifact_root,
        )
        assert _stream_probe_rows(probe_path)[-1]["scanner_invocations"] == 5
        invalid_range = cli_runner.run(
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range"}},
            timeout_sec=120,
        )
        assert invalid_range.returncode != 0
        assert invalid_range.response["error"]["code"] == "INVALID_REQUEST"
        assert invalid_range.response["error"]["error_layer"] == "schema"
        assert _stream_probe_rows(probe_path)[-1]["scanner_invocations"] == 5

        invalid_static = cli_runner.run(
            {"api_version": "xdebug.v1", "action": "stream.validate",
             "target": target,
             "args": {"stream": "ready_packet", "dynamic": False,
                      "cache_scope": "full"}},
            timeout_sec=120,
        )
        assert invalid_static.returncode != 0
        assert invalid_static.response["error"]["code"] == "INVALID_REQUEST"
        assert invalid_static.response["error"]["error_layer"] == "schema"
    finally:
        cli_runner.run(
            {"api_version": "xdebug.v1", "action": "session.close", "args": {"mode": "force"},
             "target": target}, timeout_sec=60,
        )

        batch_probe = tmp_path / "stream-batch-cache-probe.jsonl"
        cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(batch_probe)
        cli_runner.restart()
        batch_open = _query(
        cli_runner,
        {"api_version": "xdebug.v1", "action": "session.open",
         "target": {"fsdb": str(fsdb)},
         "args": {"name": "stream_cache_batch"}},
        case_name="stream-cache-batch-open",
        artifact_root=artifact_root,
    )
    batch_session = batch_open["session"]
    batch_target = {"session_id": batch_session["session_id"]}
    try:
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.config.load",
             "target": batch_target,
             "args": {"config": {"streams": [ready_packet]}, "mode": "replace"}},
            case_name="stream-cache-batch-load", artifact_root=artifact_root,
        )
        batch_requests = [
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": batch_target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range", "time_range": range_a}},
            {"api_version": "xdebug.v1", "action": "stream.export",
             "target": batch_target,
             "args": {"stream": "ready_packet", "kind": "packet",
                      "cache_scope": "range", "time_range": range_a,
                      "line_limit": 2}},
            {"api_version": "xdebug.v1", "action": "stream.validate",
             "target": batch_target,
             "args": {"stream": "ready_packet", "dynamic": True,
                      "cache_scope": "range", "time_range": range_a}},
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": batch_target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range", "time_range": range_b}},
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": batch_target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "full", "time_range": range_a}},
            {"api_version": "xdebug.v1", "action": "stream.query",
             "target": batch_target,
             "args": {"stream": "ready_packet", "query": "summary",
                      "cache_scope": "range", "time_range": range_b}},
        ]
        batch_result = cli_runner.run(
            {"api_version": "xdebug.v1", "action": "batch",
             "args": {"mode": "continue_on_error",
                      "requests": batch_requests}},
            timeout_sec=240,
        )
        assert batch_result.returncode == 0, batch_result.stderr
        assert batch_result.response["summary"] == {
            "count": 6,
            "all_ok": True,
            "failed_count": 0,
            "failed_indexes": [],
            "failed_codes": [],
            "failed_layers": [],
        }
        assert all(
            child["ok"] for child in batch_result.response["data"]["results"]
        )
        batch_rows = _stream_probe_rows(batch_probe)
        assert batch_rows[-1]["scanner_invocations"] == 4
        assert sum(row["event"] == "build" for row in batch_rows) == 4
        assert sum(row["event"] == "invalidate" for row in batch_rows) == 2
    finally:
        cli_runner.run(
            {"api_version": "xdebug.v1", "action": "session.close", "args": {"mode": "force"},
             "target": batch_target}, timeout_sec=60,
        )

    soft_probe = tmp_path / "stream-soft-lru-probe.jsonl"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_MAX_BYTES"] = "1"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES"] = "2147483648"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(soft_probe)
    cli_runner.restart()
    soft_open = _query(
        cli_runner,
        {"api_version": "xdebug.v1", "action": "session.open",
         "target": {"fsdb": str(fsdb)},
         "args": {"name": "stream_cache_soft_lru"}},
        case_name="stream-cache-soft-open",
        artifact_root=artifact_root,
    )
    soft_session = soft_open["session"]
    soft_target = {"session_id": soft_session["session_id"]}
    try:
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.config.load",
             "target": soft_target,
             "args": {"config": {"streams": [ready_packet]}, "mode": "replace"}},
            case_name="stream-cache-soft-load", artifact_root=artifact_root,
        )
        for index, time_range in enumerate((range_a, range_b, range_a)):
            _query(
                cli_runner,
                {"api_version": "xdebug.v1", "action": "stream.query",
                 "target": soft_target,
                 "args": {"stream": "ready_packet", "query": "summary",
                          "cache_scope": "range",
                          "time_range": time_range}},
                case_name="stream-cache-soft-range-%d" % index,
                artifact_root=artifact_root,
            )
        soft_rows = _stream_probe_rows(soft_probe)
        assert soft_rows[-1]["scanner_invocations"] == 3
        assert soft_rows[-1]["evictions"] >= 2
    finally:
        cli_runner.run(
            {"api_version": "xdebug.v1", "action": "session.close", "args": {"mode": "force"},
             "target": soft_target}, timeout_sec=60,
        )

    hard_probe = tmp_path / "stream-hard-limit-probe.jsonl"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_MAX_BYTES"] = "1"
    cli_runner.base_env["XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES"] = "1"
    cli_runner.base_env["XDEBUG_TEST_ANALYSIS_PROBE_PATH"] = str(hard_probe)
    cli_runner.restart()
    hard_open = _query(
        cli_runner,
        {"api_version": "xdebug.v1", "action": "session.open",
         "target": {"fsdb": str(fsdb)},
         "args": {"name": "stream_cache_hard_limit"}},
        case_name="stream-cache-hard-open",
        artifact_root=artifact_root,
    )
    hard_session = hard_open["session"]
    hard_target = {"session_id": hard_session["session_id"]}
    try:
        _query(
            cli_runner,
            {"api_version": "xdebug.v1", "action": "stream.config.load",
             "target": hard_target,
             "args": {"config": {"streams": [ready_packet]}, "mode": "replace"}},
            case_name="stream-cache-hard-load", artifact_root=artifact_root,
        )
        hard_request = {
            "api_version": "xdebug.v1", "action": "stream.query",
            "target": hard_target,
            "args": {"stream": "ready_packet", "query": "summary",
                     "cache_scope": "full", "time_range": range_a},
        }
        rejected = cli_runner.run(
            {"api_version": "xdebug.v1", "action": "batch",
             "args": {"mode": "continue_on_error",
                      "requests": [hard_request, copy.deepcopy(hard_request)]}},
            timeout_sec=120,
        )
        assert rejected.returncode == 0
        assert rejected.response["ok"] is True
        assert rejected.response["error"] is None
        assert rejected.response["summary"]["all_ok"] is False
        child_results = rejected.response["data"]["results"]
        assert len(child_results) == 2
        for child in child_results:
            cache_error = child["error"]
            assert cache_error["code"] == "ANALYSIS_MEMORY_LIMIT_EXCEEDED"
            assert cache_error["protocol"] == "stream"
            assert cache_error["hard_max_bytes"] == 1
            assert cache_error["recoverable"] is True
            assert len(cache_error["next_actions"]) == 2
        hard_rows = _stream_probe_rows(hard_probe)
        assert hard_rows[-1]["scanner_invocations"] == 0
        assert sum(row["event"] == "build_failed" for row in hard_rows) == 2
    finally:
        cli_runner.run(
            {"api_version": "xdebug.v1", "action": "session.close", "args": {"mode": "force"},
             "target": hard_target}, timeout_sec=60,
        )
