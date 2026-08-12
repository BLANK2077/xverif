from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _query(
    binary: Path,
    home: Path,
    action: str,
    *,
    args: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    output_format: str = "json",
) -> dict[str, Any] | str:
    request: dict[str, Any] = {
        "api_version": "xdebug.v1",
        "action": action,
        "args": args or {},
    }
    if target is not None:
        request["target"] = target
    command = [str(binary)]
    if output_format == "json":
        command.append("--json")
    command.append("-")
    env = os.environ.copy()
    env["HOME"] = str(home)
    result = subprocess.run(
        command,
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        cwd=ROOT.parent,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if output_format == "xout":
        return result.stdout
    response = json.loads(result.stdout)
    assert response["ok"] is True, response
    return response


def test_xif_event_queries_published_fsdb(xverif_fixture) -> None:
    resources = xverif_fixture("xdebug.xif_event")
    script = ROOT / "testdata/waveform/xif_agent_event/scripts/check_event_waves.py"
    fsdb = resources / "out/waves/xif_event_multi_if_test.fsdb"
    result = subprocess.run(
        [
            "python3",
            str(script),
            "--xdebug",
            str(ROOT.parent / "tools/xdebug"),
            "--fsdb",
            str(fsdb),
        ],
        text=True,
        capture_output=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: xdebug event direct struct checks" in result.stdout


def test_event_find_preserves_canonical_json_and_flat_xout(
    xverif_fixture,
    tmp_path: Path,
) -> None:
    resources = xverif_fixture("xdebug.xif_event")
    fsdb = resources / "out/waves/xif_event_multi_if_test.fsdb"
    binary = ROOT.parent / "tools/xdebug"
    session_id = "xif_event_xout_contract"
    target = {"session_id": session_id}
    _query(
        binary,
        tmp_path,
        "session.open",
        args={"name": session_id},
        target={"fsdb": str(fsdb)},
    )
    try:
        _query(
            binary,
            tmp_path,
            "event.config.load",
            args={
                "name": "rdy",
                "config_path": str(
                    ROOT / "testdata/waveform/xif_agent_event/event_rdy.json"
                ),
            },
            target=target,
        )
        find_args = {
            "name": "rdy",
            "expr": "vld && rdy",
            "mode": "all",
            "line_limit": 2,
        }
        response = _query(
            binary,
            tmp_path,
            "event.find",
            args=find_args,
            target=target,
        )
        assert isinstance(response, dict)
        summary = response["summary"]
        for key in (
            "scan_complete",
            "analysis_complete",
            "response_truncated",
            "total_count",
            "returned_count",
            "truncation_scopes",
        ):
            assert key in summary
        for legacy in (
            "event_count",
            "returned_event_count",
            "truncated",
            "edge",
            "sample_point",
        ):
            assert legacy not in summary
        assert "sampling" in response["data"]
        assert "width_diagnostics" in summary

        xout = _query(
            binary,
            tmp_path,
            "event.find",
            args=find_args,
            target=target,
            output_format="xout",
        )
        assert isinstance(xout, str)
        assert xout.startswith("@xdebug.event.find.v1\n")
        for required in ("requested:", "effective:", "events:", "time", "vld", "rdy"):
            assert required in xout
        assert "'b{01011010,0011,0010,1010010101011010}" in xout
        for forbidden in (
            '"',
            ':{',
            ':[{',
            "known=true",
            "width_diagnostics",
            "XOUT_BEGIN",
            "XOUT_END",
            "pointer\tkind\tvalue",
        ):
            assert forbidden not in xout
        assert xout.endswith("\n") and not xout.endswith("\n\n")
    finally:
        _query(
            binary,
            tmp_path,
            "session.close",
            args={"mode": "force"},
            target={"session_id": "all"},
        )
