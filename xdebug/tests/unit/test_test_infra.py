from __future__ import annotations

import json
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from runner import (
    ArtifactWriter,
    CliRunner,
    CommandRunner,
    HybridCliRunner,
    InvariantError,
    NormalizeOptions,
    StdioLoopRunner,
    assert_invariants,
    normalize_response,
)


def _fake_xdebug(tmp_path: Path) -> Path:
    script = tmp_path / "fake_xdebug"
    script.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time

if "--stdio-loop" in sys.argv:
    print(json.dumps({"type": "ready", "protocol": "xdebug-stdio-loop",
                      "version": 1, "pid": os.getpid()}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        rid = req.get("request_id", req.get("id", "missing"))
        if req.get("action") == "stdio.quit":
            print(json.dumps({"id": rid, "ok": True, "payload_format": "json",
                              "json": {"ok": True, "action": "stdio.quit"}}),
                  flush=True)
            break
        if req.get("args", {}).get("stderr_lines"):
            for i in range(int(req["args"]["stderr_lines"])):
                print("diagnostic-%d" % i, file=sys.stderr, flush=True)
        if req.get("args", {}).get("pollute_stdout"):
            print("unexpected banner", flush=True)
        if req.get("args", {}).get("exit_now"):
            raise SystemExit(17)
        if req.get("args", {}).get("sleep"):
            time.sleep(float(req["args"]["sleep"]))
        payload = {"ok": True, "action": req.get("action"),
                   "summary": {"pid": os.getpid(), "value": 7}}
        if req.get("output", {}).get("format") == "json" or "--json" in sys.argv:
            envelope = {"id": rid, "ok": True, "payload_format": "json",
                        "json": payload}
        else:
            envelope = {"id": rid, "ok": True, "payload_format": "xout",
                        "xout": "@xdebug.fake.v1\\nsummary:\\n  value: 7\\n"}
        print(json.dumps(envelope), flush=True)
    raise SystemExit(0)

input_path = next((x for x in sys.argv[1:] if not x.startswith("-")), "-")
text = sys.stdin.read() if input_path == "-" else open(input_path).read()
req = json.loads(text)
payload = {"ok": True, "action": req.get("action"),
           "summary": {"pid": os.getpid(), "value": 7}}
if "--json" in sys.argv or req.get("output", {}).get("format") == "json":
    print(json.dumps(payload))
else:
    print("@xdebug.fake.v1\\nsummary:\\n  value: 7")
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.mark.unit
def test_stdio_loop_timeout_terminates_desynchronized_process(tmp_path: Path) -> None:
    loop = StdioLoopRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    loop.start()
    result = loop.request(
        {
            "api_version": "xdebug.v1",
            "action": "actions",
            "args": {"sleep": 30},
        },
        timeout_sec=0.1,
    )
    assert result.timed_out
    assert loop.proc is not None and loop.proc.poll() is not None


@pytest.mark.unit
def test_stdio_loop_detects_stdout_pollution_after_ready(tmp_path: Path) -> None:
    loop = StdioLoopRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    try:
        loop.start()
        result = loop.request(
            {
                "api_version": "xdebug.v1",
                "action": "actions",
                "args": {"pollute_stdout": True},
            }
        )
        assert not result.ok
        assert "stdout protocol pollution" in result.stderr_raw
    finally:
        loop.terminate()


@pytest.mark.unit
def test_stdio_loop_drains_large_stderr_without_polluting_stdout(
    tmp_path: Path,
) -> None:
    loop = StdioLoopRunner(_fake_xdebug(tmp_path), cwd=tmp_path, default_json=True)
    try:
        loop.start()
        result = loop.request(
            {
                "api_version": "xdebug.v1",
                "action": "actions",
                "args": {"stderr_lines": 1000},
            }
        )
        assert result.ok
        assert "diagnostic-999" in result.stderr_raw
        assert result.envelope["payload_format"] == "json"
    finally:
        loop.terminate()


@pytest.mark.unit
def test_stdio_loop_reports_child_exit(tmp_path: Path) -> None:
    loop = StdioLoopRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    loop.start()
    result = loop.request(
        {
            "api_version": "xdebug.v1",
            "action": "actions",
            "args": {"exit_now": True},
        }
    )
    assert not result.ok
    assert "stdio-loop exited: rc=17" in result.stderr_raw


@pytest.mark.unit
def test_hybrid_runner_timeout_terminates_persistent_frontend(
    tmp_path: Path,
) -> None:
    runner = HybridCliRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "actions",
            "args": {"sleep": 30},
        },
        timeout_sec=0.1,
    )
    assert result.timed_out
    assert runner._loop is not None
    assert runner._loop.proc is not None
    assert runner._loop.proc.poll() is not None
    runner.close()


@pytest.mark.unit
def test_normalize_replaces_paths_and_sorts_selected_list() -> None:
    value = {
        "elapsed_ms": 3,
        "path": str(Path(tempfile.gettempdir()) / "xdebug-case/a"),
        "rows": [{"name": "b"}, {"name": "a"}],
    }
    normalized = normalize_response(
        value,
        NormalizeOptions(unordered_list_paths={"rows"}),
    )
    assert normalized == {
        "path": "<tmp>/a",
        "rows": [{"name": "a"}, {"name": "b"}],
    }


@pytest.mark.unit
def test_invariant_assertions() -> None:
    response = {
        "ok": True,
        "summary": {"count": 2, "status": "resolved"},
        "data": {"rows": [{"signal": "a"}, {"signal": "b"}]},
    }
    assert_invariants(
        response,
        {
            "ok": True,
            "required_paths": ["summary.count", "data.rows.0.signal"],
            "absent_paths": ["summary.truncated", "meta.truncated"],
            "non_empty": ["data.rows"],
            "equals": {"summary.count": 2},
            "min": {"summary.count": 1},
            "max": {"summary.count": 3},
            "allowed_values": {"summary.status": ["resolved", "control_only"]},
            "contains": {"data.rows": {"signal": "a"}},
        },
    )
    with pytest.raises(InvariantError):
        assert_invariants(response, {"equals": {"summary.count": 3}})
    with pytest.raises(InvariantError):
        assert_invariants(response, {"absent_paths": ["summary.count"]})


@pytest.mark.unit
def test_command_runner_success_and_timeout(tmp_path: Path) -> None:
    runner = CommandRunner(cwd=tmp_path)
    success = runner.run(
        [sys.executable, "-c", "print('fixture-ok')"],
        timeout_sec=5,
    )
    assert success.ok
    assert success.stdout_raw.strip() == "fixture-ok"

    timeout = runner.run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_sec=0.1,
    )
    assert timeout.timed_out
    assert timeout.returncode == -1


