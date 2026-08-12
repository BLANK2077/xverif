from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner import StdioLoopRunner


def _read_ndjson(path: Path) -> list[dict]:
    assert path.exists(), path
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _stdio_events(home: Path, session_prefix: str = "adhoc") -> list[dict]:
    matches = sorted(
        (home / ".xdebug" / "sessions").glob(
            f"{session_prefix}_*/owners/*/logs/stdio.ndjson"
        )
    )
    assert matches, f"missing stdio.ndjson for {session_prefix}"
    rows: list[dict] = []
    for path in matches:
        rows.extend(_read_ndjson(path))
    return rows


@pytest.fixture
def stdio_loop(xdebug_bin, repo_root, isolated_home):
    loop = StdioLoopRunner(
        xdebug_bin,
        cwd=repo_root,
        env={"HOME": str(isolated_home), "XVERIF_HOME": str(repo_root)},
    )
    loop.start()
    try:
        yield loop
    finally:
        loop.terminate()


@pytest.mark.session
@pytest.mark.stdio_loop
def test_stdio_loop_recovers_after_blank_malformed_and_invalid_request(
    stdio_loop: StdioLoopRunner,
    isolated_home: Path,
) -> None:
    assert stdio_loop.proc is not None and stdio_loop.proc.stdin is not None
    stdio_loop.proc.stdin.write("\n")
    stdio_loop.proc.stdin.flush()

    malformed = stdio_loop.send_raw("{not-json")
    assert malformed["ok"] is False
    assert malformed["error"]["code"] == "INVALID_JSON"

    invalid_version = stdio_loop.request(
        {
            "request_id": "bad-version",
            "api_version": "xdebug.v0",
            "action": "actions",
        }
    )
    assert not invalid_version.ok
    assert invalid_version.envelope["id"] == "bad-version"
    assert invalid_version.envelope["error"]["code"] == "UNSUPPORTED_API_VERSION"

    recovered = stdio_loop.request(
        {
            "request_id": "after-errors",
            "api_version": "xdebug.v1",
            "action": "actions",
        }
    )
    assert recovered.ok
    assert recovered.envelope["id"] == "after-errors"
    assert recovered.envelope["payload_format"] == "xout"

    events = _stdio_events(isolated_home)
    phases = [event["phase"] for event in events]
    assert "loop.ready" in phases
    assert "loop.invalid_json" in phases
    assert "loop.validate_failed" in phases
    assert "request.begin" in phases
    assert "request.end" in phases
    invalid = next(event for event in events if event["phase"] == "loop.invalid_json")
    assert invalid["request_id"].startswith("req-")
    validate = next(event for event in events if event["phase"] == "loop.validate_failed")
    assert validate["request_id"] == "bad-version"


@pytest.mark.session
@pytest.mark.stdio_loop
def test_stdio_loop_multiple_requests_keep_ids_and_xout_mode(
    stdio_loop: StdioLoopRunner,
) -> None:
    first = stdio_loop.request(
        {
            "request_id": "xout-1",
            "api_version": "xdebug.v1",
            "action": "actions",
        }
    )
    second = stdio_loop.request(
        {
            "id": "xout-2",
            "trace_id": "trace-xout-2",
            "span_id": "span-xout-2",
            "payload_format": "xout",
            "api_version": "xdebug.v1",
            "action": "schema",
            "args": {"action": "actions", "kind": "request"},
        }
    )
    third = stdio_loop.request(
        {
            "request_id": "xout-3",
            "api_version": "xdebug.v1",
            "action": "schema",
            "args": {"action": "actions", "kind": "response"},
        }
    )

    assert first.envelope["id"] == "xout-1"
    assert first.envelope["payload_format"] == "xout"
    assert second.envelope["id"] == "xout-2"
    assert second.envelope["payload_format"] == "xout"
    assert second.response.startswith("@xdebug.schema.v1")
    assert third.envelope["id"] == "xout-3"
    assert third.envelope["payload_format"] == "xout"


@pytest.mark.session
@pytest.mark.stdio_loop
def test_stdio_loop_rejects_invalid_or_legacy_transport_metadata(
    stdio_loop: StdioLoopRunner,
) -> None:
    invalid_trace = stdio_loop.request(
        {
            "request_id": "bad-trace",
            "trace_id": 7,
            "api_version": "xdebug.v1",
            "action": "actions",
        }
    )
    assert not invalid_trace.ok
    assert invalid_trace.envelope["error"]["code"] == "INVALID_REQUEST"
    assert "trace_id" in invalid_trace.envelope["error"]["message"]

    legacy_marker = stdio_loop.request(
        {
            "request_id": "legacy-marker",
            "__xverif_loop_payload_format": "json",
            "api_version": "xdebug.v1",
            "action": "actions",
        }
    )
    assert not legacy_marker.ok
    assert legacy_marker.envelope["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.session
@pytest.mark.stdio_loop
def test_stdio_loop_default_json_uses_outer_mode(
    xdebug_bin, repo_root, isolated_home
) -> None:
    loop = StdioLoopRunner(
        xdebug_bin,
        cwd=repo_root,
        env={"HOME": str(isolated_home), "XVERIF_HOME": str(repo_root)},
        default_json=True,
    )
    try:
        loop.start()
        result = loop.request(
            {
                "request_id": "outer-json",
                "api_version": "xdebug.v1",
                "action": "actions",
            }
        )
        assert result.ok
        assert result.envelope["id"] == "outer-json"
        assert result.envelope["payload_format"] == "json"
    finally:
        loop.terminate()


@pytest.mark.session
@pytest.mark.stdio_loop
def test_stdio_loop_quit_closes_process_cleanly(
    stdio_loop: StdioLoopRunner,
    isolated_home: Path,
) -> None:
    result = stdio_loop.quit()
    assert result is not None and result.ok
    assert result.envelope["json"]["action"] == "stdio.quit"
    assert stdio_loop.proc is not None
    assert stdio_loop.proc.poll() == 0
    events = _stdio_events(isolated_home)
    assert any(event["phase"] == "loop.quit" for event in events)


@pytest.mark.session
@pytest.mark.stdio_loop
def test_stdio_loop_stdout_is_jsonl_only(
    stdio_loop: StdioLoopRunner,
) -> None:
    result = stdio_loop.request(
        {
            "request_id": "clean-stdout",
            "api_version": "xdebug.v1",
            "action": "actions",
        }
    )
    assert result.ok
    assert not [
        item
        for item in stdio_loop.transcript
        if item.get("direction") == "stdout-noise"
    ]
    assert result.envelope["payload_format"] == "xout"
    assert result.envelope["xout"] == result.stdout_raw
