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
def test_cli_runner_stdin_and_file(tmp_path: Path) -> None:
    runner = CliRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    request = {"api_version": "xdebug.v1", "action": "actions"}

    stdin_result = runner.run(request, input_mode="stdin", output_format="json")
    file_result = runner.run(request, input_mode="file", output_format="json")

    assert stdin_result.ok
    assert file_result.ok
    assert stdin_result.response["summary"]["value"] == 7
    assert "pid" not in stdin_result.normalized_response["summary"]
    assert stdin_result.normalized_response == file_result.normalized_response


@pytest.mark.unit
def test_cli_runner_xout(tmp_path: Path) -> None:
    runner = CliRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    result = runner.run(
        {"api_version": "xdebug.v1", "action": "actions"},
        output_format="xout",
    )
    assert result.ok
    assert result.response.startswith("@xdebug.fake.v1")


@pytest.mark.unit
def test_stdio_loop_json_and_quit(tmp_path: Path) -> None:
    loop = StdioLoopRunner(_fake_xdebug(tmp_path), cwd=tmp_path, default_json=True)
    ready = loop.start()
    assert ready["protocol"] == "xdebug-stdio-loop"
    result = loop.request(
        {
            "api_version": "xdebug.v1",
            "action": "value.at",
            "args": {"signal": "top.clk", "clock": "top.clk", "time": "0ns"},
        }
    )
    assert result.ok
    assert result.envelope["payload_format"] == "json"
    assert result.response["summary"]["value"] == 7
    quit_result = loop.quit()
    assert quit_result is not None and quit_result.ok


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
def test_hybrid_runner_explicit_restart_applies_environment_changes(
    tmp_path: Path,
) -> None:
    runner = HybridCliRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    try:
        first = runner.run({"api_version": "xdebug.v1", "action": "actions"})
        runner.base_env["HYBRID_PHASE"] = "second"
        runner.restart()
        second = runner.run({"api_version": "xdebug.v1", "action": "actions"})
        assert first.response["summary"]["pid"] != second.response["summary"]["pid"]
    finally:
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
def test_artifact_writer_redacts_and_writes_diff(tmp_path: Path) -> None:
    runner = CliRunner(
        _fake_xdebug(tmp_path),
        cwd=tmp_path,
        base_env={"SERVICE_TOKEN": "secret-value"},
    )
    result = runner.run(
        {"api_version": "xdebug.v1", "action": "actions"},
        output_format="json",
    )
    case_dir = ArtifactWriter(tmp_path / "artifacts", run_id="run").write(
        "demo/case",
        result,
        expected={"ok": True, "summary": {"value": 8}},
        extra={"trace_tree": {"root": "top.clk"}},
    )
    assert (case_dir / "command.json").exists()
    assert (case_dir / "diff.txt").read_text(encoding="utf-8")
    env = json.loads((case_dir / "env.json").read_text(encoding="utf-8"))
    assert env["SERVICE_TOKEN"] == "<redacted>"
    assert (case_dir / "trace_tree.json").exists()


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


@pytest.mark.unit
def test_runners_record_history_for_failure_artifacts(tmp_path: Path) -> None:
    cli = CliRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    cli_result = cli.run({"api_version": "xdebug.v1", "action": "actions"})
    assert cli.history == [cli_result]

    command = CommandRunner(cwd=tmp_path)
    command_result = command.run(
        [sys.executable, "-c", "print('history-ok')"],
        timeout_sec=5,
    )
    assert command.history == [command_result]

    loop = StdioLoopRunner(_fake_xdebug(tmp_path), cwd=tmp_path)
    loop.start()
    try:
        loop_result = loop.request({"api_version": "xdebug.v1", "action": "actions"})
        assert loop.history == [loop_result]
    finally:
        loop.terminate()
