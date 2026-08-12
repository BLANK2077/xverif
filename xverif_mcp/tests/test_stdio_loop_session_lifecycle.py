"""Lifecycle tests for XdebugLoopSession failure handling (fake process).

Verifies:
- open failure when process exits before ready
- query failure when process crashes mid-request
- backend SESSION_DEAD → SESSION_LOST
- ordinary errors do NOT tear down session
- stale alive open rejection
- open after SESSION_LOST eviction
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from xverif_loop.config import resolve_mcp_runtime_config
from xverif_loop.lsf.bsub import BsubRunner
from xverif_loop.lsf.protocol import JsonlProcess, ProtocolError
from xverif_loop.logging import resolve_logger
from xverif_loop.sessions.launchers import DirectLauncher, LsfLauncher
from xverif_loop.sessions.loop_session import XdebugLoopSession
from xverif_loop.sessions.session_manager import McpSessionManager


# ---------------------------------------------------------------------------
# fake --stdio-loop scripts
# ---------------------------------------------------------------------------


def _make_fake_script(path: Path, lines: list[str]) -> str:
    path.write_text("#!/usr/bin/env python3\n" + "\n".join(lines) + "\n")
    path.chmod(0o755)
    return str(path)


def _fake_loop_script(dirpath: Path, fail_open: bool = False, fail_query: bool = False) -> str:
    return _make_fake_script(dirpath / "fake_xdebug", [
        "import json, sys, os",
        "",
        f"_fail_open = {fail_open}",
        f"_fail_query = {fail_query}",
        "",
        "if _fail_open:",
        '    sys.stderr.write("fake xdebug exiting before ready")',
        "    sys.exit(1)",
        "",
        'print(json.dumps({"type":"ready","protocol":"xdebug-stdio-loop","version":1,"pid":os.getpid()}))',
        "sys.stdout.flush()",
        "",
        "_handled_open = False",
        "",
        "for line in sys.stdin:",
        "    line = line.strip()",
        "    if not line: continue",
        "    try: req = json.loads(line)",
        "    except Exception: continue",
        '    rid = req.get("request_id", req.get("id", "unknown"))',
        '    action = req.get("action", "")',
        "",
        '    if action == "session.open":',
        "        _handled_open = True",
        "",
        '    if action == "stdio.quit":',
        "        sys.exit(0)",
        "",
        '    if _fail_query and _handled_open and action != "session.open":',
        '        sys.stderr.write("fake xdebug crashing")',
        "        sys.exit(1)",
        "",
        '    wants_json = (req.get("output", {}).get("format") == "json" or',
        '                  req.get("output", {}).get("response_format") == "json" or',
        '                  req.get("payload_format") == "json")',
        '    if req.get("api_version") == "xcov.v1":',
        '        completeness = {"total_count": 1 if action == "session.open" else 0,',
        '                        "returned_count": 1 if action == "session.open" else 0,',
        '                        "response_truncated": False, "scan_complete": True,',
        '                        "analysis_complete": True, "truncation_scopes": []}',
        '        if action == "session.open":',
        '            name = req.get("args", {}).get("name", "test")',
        '            result = {"ok": True, "api_version": "xcov.v1", "request_id": rid,',
        '                      "action": action, "summary": completeness,',
        '                      "data": {"session": {"session_id": name, "state": "alive",',
        '                                           "vdb": req.get("target", {}).get("vdb"),',
        '                                           "test_count": 1, "top_scope_count": 1,',
        '                                           "worker": "fake"},',
        '                               "resource_snapshot": {',
        '                                   "vdb": req.get("target", {}).get("vdb"),',
        '                                   "run_manifest": None}}, "warnings": []}',
        '        else:',
        '            result = {"ok": True, "api_version": "xcov.v1", "request_id": rid,',
        '                      "action": action, "summary": completeness,',
        '                      "data": {}, "warnings": []}',
        '        rsp = {"id": rid, "ok": True, "payload_format": "xout",',
        '               "json": result, "xout": "@xcov.v1 ok action=" + action + " request_id=unit\\n"}',
        "    elif wants_json:",
        '        if action == "session.open":',
        '            result = {"ok": True, "action": action,',
        '                      "session": {"session_id": req.get("args", {}).get("name", "test"), "mode": "waveform"},',
        '                      "summary": {"status": "opened"}}',
        '        else:',
        '            result = {"ok": True, "action": action, "summary": {"echo": action}}',
        '        rsp = {"id": rid, "ok": True, "payload_format": "json", "json": result}',
        "    else:",
        '        if action == "session.open":',
        '            result = {"ok": True, "action": action,',
        '                      "session": {"session_id": req.get("args", {}).get("name", "test"), "mode": "waveform"},',
        '                      "summary": {"status": "opened"}}',
        '        else:',
        '            result = {"ok": True, "action": action, "summary": {"echo": action}}',
        '        xout = "@xdebug." + action + ".v1\\n"',
        '        rsp = {"id": rid, "ok": True, "payload_format": "xout", "json": result, "xout": xout}',
        "    print(json.dumps(rsp))",
        "    sys.stdout.flush()",
    ])


def _fake_loop_dead_session(dirpath: Path) -> str:
    return _make_fake_script(dirpath / "fake_dead", [
        "import json, sys, os",
        "",
        'print(json.dumps({"type":"ready","protocol":"xdebug-stdio-loop","version":1,"pid":os.getpid()}))',
        "sys.stdout.flush()",
        "",
        "for line in sys.stdin:",
        "    line = line.strip()",
        "    if not line: continue",
        "    try: req = json.loads(line)",
        "    except Exception: continue",
        '    rid = req.get("request_id", req.get("id", "unknown"))',
        '    action = req.get("action", "")',
        "",
        '    if action == "stdio.quit":',
        "        sys.exit(0)",
        '    if action == "session.open":',
        '        name = req.get("args", {}).get("name", "test")',
        '        result = {"ok": True, "action": "session.open",',
        '                  "session": {"session_id": name, "mode": "combined"},',
        '                  "summary": {"status": "opened"}}',
        '        rsp = {"id": rid, "ok": True, "payload_format": "json", "json": result}',
        "    else:",
        '        rsp = {"id": rid, "ok": False,',
        '               "error": {"code": "SESSION_DEAD", "message": "backend session is dead"}}',
        "    print(json.dumps(rsp))",
        "    sys.stdout.flush()",
    ])


def _fake_native_admin_cli(dirpath: Path, capture_path: Path) -> str:
    return _make_fake_script(dirpath / "fake_native_admin", [
        "import json, sys",
        f"capture_path = {str(capture_path)!r}",
        "request = json.loads(sys.stdin.read())",
        "with open(capture_path, 'a', encoding='utf-8') as stream:",
        "    stream.write(json.dumps(request) + '\\n')",
        "if 'output' in request:",
        "    print(json.dumps({'ok': False, 'error': {'code': 'SCHEMA_VALIDATION_FAILED',",
        "                      'message': 'unexpected top-level output'}}))",
        "    sys.exit(0)",
        "print(json.dumps({'ok': True, 'action': request['action'],",
        "                  'summary': {'session_id': request['target']['session_id']}}))",
    ])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _new_session(fake_bin: str, alias: str = "test") -> XdebugLoopSession:
    runtime = _runtime()
    return XdebugLoopSession(
        alias=alias, fsdb="t.fsdb", daidir=None,
        launcher=DirectLauncher(), runtime=runtime,
        logger=resolve_logger(runtime), xdebug_bin=fake_bin,
    )


def _runtime(
    *,
    backend: str = "direct",
    request_timeout_sec: float = 3.0,
):
    return resolve_mcp_runtime_config().with_overrides(
        backend=backend,
        startup_timeout_sec=3.0,
        request_timeout_sec=request_timeout_sec,
    )


def _new_manager(
    *,
    backend: str = "xdebug",
    request_timeout_sec: float = 3.0,
    **kwargs,
) -> McpSessionManager:
    runtime = _runtime(
        request_timeout_sec=request_timeout_sec,
    )
    return McpSessionManager(
        runtime=runtime,
        backend=backend,
        logger=resolve_logger(runtime),
        **kwargs,
    )


def _cleanup(s: XdebugLoopSession):
    try:
        if s.state == "alive":
            s.close()
        else:
            s.abort("test cleanup", source="test")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolated_mcp_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("XVERIF_MCP_LOG_DIR", str(tmp_path / "mcp_logs"))


def _read_ndjson(path: Path) -> list[dict]:
    assert path.exists(), path
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _session_events(tmp_path: Path, alias: str, name: str = "session") -> list[dict]:
    paths = sorted(
        (tmp_path / "mcp_logs" / "sessions" / alias).glob(
            f"owners/*/{name}.ndjson"
        )
    )
    assert paths
    return [event for path in paths for event in _read_ndjson(path)]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestOpenFailure:
    def test_missing_resource_is_rejected_before_launch(self):
        mgr = _new_manager()
        r = mgr.open_session("missing_resource")
        assert not r.get("ok")
        assert r["error"]["code"] == "RESOURCE_REQUIRED"
        assert mgr.sessions == {}

    def test_exit_before_ready(self, tmp_path):
        fake = _fake_loop_script(tmp_path, fail_open=True)
        s = _new_session(fake)
        r = s.open()
        assert not r.get("ok"), r
        assert r["error"]["code"] == "SESSION_OPEN_FAILED"
        assert s.state == "dead"
        assert s.process_alive() is False
        session_events = _session_events(tmp_path, "test")
        stdio_events = _session_events(tmp_path, "test", "stdio")
        assert any(e["phase"] == "session.open.begin" for e in session_events)
        assert any(e["phase"] == "session.open.end" and not e["ok"] for e in session_events)
        assert any(e["phase"] == "ready.process_exited" for e in stdio_events)

    def test_no_session_after_failure(self, tmp_path):
        fake = _fake_loop_script(tmp_path, fail_open=True)
        mgr = _new_manager()
        mgr.xdebug_bin = fake
        r = mgr.open_session("doomed", fsdb="test.fsdb")
        assert not r.get("ok")
        assert "doomed" not in mgr.sessions

    def test_mcp_log_path_uses_stable_safe_evidence(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake
        r = mgr.open_session("redact_case", fsdb="/very/private/wave.fsdb")
        assert r.get("ok"), r
        events = _session_events(tmp_path, "redact_case")
        begin = next(e for e in events if e["phase"] == "manager.open.begin")
        assert begin["fsdb"]["basename"] == "wave.fsdb"
        assert len(begin["fsdb"]["sha256"]) == 64
        assert "/very/private" not in json.dumps(events)


class TestStrictJsonlProtocol:
    def test_ready_rejects_non_json_stdout_without_echoing_it(self, tmp_path):
        fake = _make_fake_script(tmp_path / "polluted_ready", [
            "import sys, time",
            "print('private stdout pollution', flush=True)",
            "time.sleep(10)",
        ])
        runtime = _runtime()
        handle = JsonlProcess.start(
            [fake],
            runtime=runtime,
            logger=resolve_logger(runtime),
        )
        try:
            with pytest.raises(ProtocolError) as caught:
                handle.wait_ready("xdebug-stdio-loop", timeout_sec=2.0)
            assert str(caught.value) == (
                "non-JSON stdout before the ready envelope"
            )
            assert "private stdout pollution" not in str(caught.value)
        finally:
            handle.terminate()

    def test_ready_rejects_non_finite_json_extension(self, tmp_path):
        fake = _make_fake_script(tmp_path / "nan_ready", [
            "import time",
            "print('{\"type\":\"ready\",\"protocol\":\"xdebug-stdio-loop\","
            "\"version\":NaN}', flush=True)",
            "time.sleep(10)",
        ])
        runtime = _runtime()
        handle = JsonlProcess.start(
            [fake],
            runtime=runtime,
            logger=resolve_logger(runtime),
        )
        try:
            with pytest.raises(
                ProtocolError,
                match="non-JSON stdout before the ready envelope",
            ):
                handle.wait_ready("xdebug-stdio-loop", timeout_sec=2.0)
        finally:
            handle.terminate()

    def test_request_rejects_missing_id_and_non_finite_value_before_write(
        self,
        tmp_path,
    ):
        fake = _make_fake_script(tmp_path / "strict_request", [
            "import json, os, sys, time",
            "print(json.dumps({'type':'ready',"
            "'protocol':'xdebug-stdio-loop','version':1,'pid':os.getpid()}),"
            "flush=True)",
            "time.sleep(10)",
        ])
        runtime = _runtime()
        handle = JsonlProcess.start(
            [fake],
            runtime=runtime,
            logger=resolve_logger(runtime),
        )
        try:
            handle.wait_ready("xdebug-stdio-loop", timeout_sec=2.0)
            with pytest.raises(
                ProtocolError,
                match="non-empty string request_id or id",
            ):
                handle.request({"action": "actions"}, timeout_sec=1.0)
            with pytest.raises(
                ProtocolError,
                match="JSONL message is not strict JSON",
            ):
                handle.request(
                    {
                        "request_id": "nan",
                        "action": "actions",
                        "args": {"value": float("nan")},
                    },
                    timeout_sec=1.0,
                )
        finally:
            handle.terminate()

    def test_response_rejects_non_finite_json_without_echoing_output(
        self,
        tmp_path,
    ):
        fake = _make_fake_script(tmp_path / "nan_response", [
            "import json, os, sys",
            "print(json.dumps({'type':'ready',"
            "'protocol':'xdebug-stdio-loop','version':1,'pid':os.getpid()}),"
            "flush=True)",
            "for line in sys.stdin:",
            "    request = json.loads(line)",
            "    print('{\"id\":' + json.dumps(request['request_id']) + "
            "',\"ok\":true,\"private\":NaN}', flush=True)",
        ])
        runtime = _runtime()
        handle = JsonlProcess.start(
            [fake],
            runtime=runtime,
            logger=resolve_logger(runtime),
        )
        try:
            handle.wait_ready("xdebug-stdio-loop", timeout_sec=2.0)
            with pytest.raises(ProtocolError) as caught:
                handle.request(
                    {"request_id": "nan-response", "action": "actions"},
                    timeout_sec=2.0,
                )
            assert str(caught.value) == "non-JSON stdout after ready"
            assert "private" not in str(caught.value)
        finally:
            handle.terminate()


class TestQueryFailure:
    def test_crash_mid_query(self, tmp_path):
        fake = _fake_loop_script(tmp_path, fail_query=True)
        s = _new_session(fake)
        s.open()
        assert s.state == "alive"

        r = s.query("value.at", {"signal": "x"})
        assert not r.get("ok"), r
        assert r["error"]["code"] == "SESSION_LOST"
        assert r["error"]["terminal_source"] in ("transport", "unexpected")
        assert s.state == "dead"
        session_events = _session_events(tmp_path, "test")
        stdio_events = _session_events(tmp_path, "test", "stdio")
        assert any(e["phase"] == "query.begin" and e["action"] == "value.at" for e in session_events)
        assert any(e["phase"] == "query.end" and not e["ok"] for e in session_events)
        assert any(e["phase"] == "request.error" and not e["ok"] for e in stdio_events)


class TestBackendSessionDead:
    def test_backend_returns_session_dead(self, tmp_path):
        fake = _fake_loop_dead_session(tmp_path)
        s = _new_session(fake)
        s.open()
        assert s.state == "alive"

        r = s.query("value.at", {"signal": "x"}, output_format="json")
        assert not r.get("ok")
        assert r["error"]["code"] == "SESSION_LOST"
        assert r["error"]["terminal_source"] == "backend_response"
        assert r["error"]["backend_response"] is not None
        assert s.state == "dead"


class TestOrdinaryError:
    def test_signal_not_found_preserves_session(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        s = _new_session(fake)
        s.open()

        # Simulate a non-terminal error by monkey-patching _call_raw
        def fake_call_raw(req, timeout=None):
            return {
                "id": req["request_id"],
                "ok": False,
                "error": {"code": "SIGNAL_NOT_FOUND", "message": "nope"},
            }
        orig = s._call_raw
        s._call_raw = fake_call_raw
        try:
            r = s.query("value.at", {"signal": "x"}, output_format="json")
            assert not r.get("ok")
            assert r["error"]["code"] == "SIGNAL_NOT_FOUND"
            assert s.state == "alive"
        finally:
            s._call_raw = orig


class TestManagerEvict:
    def test_dead_session_evicted_after_query(self, tmp_path):
        fake = _fake_loop_dead_session(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake
        mgr.open_session("evict_me", fsdb="test.fsdb")
        assert "evict_me" in mgr.sessions

        r = mgr.query("evict_me", "value.at", {"signal": "x"}, output_format="json")
        assert "SESSION_LOST" in str(r)
        assert "evict_me" not in mgr.sessions
        assert mgr.tombstones["evict_me"].state == "orphan_suspected"

    def test_stale_alive_open_returns_session_stale(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake

        # First open
        mgr.open_session("stale_test", fsdb="test.fsdb")
        s = mgr.sessions["stale_test"]
        # Kill the process underneath
        s.handle.terminate()
        time.sleep(0.5)
        assert not s.process_alive()
        # Still marked alive in manager
        assert s.state == "alive"

        # Same-name open must not evict or replace the stale record implicitly.
        r = mgr.open_session("stale_test", fsdb="test.fsdb")
        assert not r.get("ok"), r
        assert r["error"]["code"] == "SESSION_STALE"
        assert "stale_test" in mgr.sessions

    def test_close_dead_session(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake
        mgr.open_session("close_me", fsdb="test.fsdb")
        s = mgr.sessions["close_me"]
        s.handle.terminate()
        s.state = "dead"

        r = mgr.close_session("close_me")
        assert not r.get("ok"), r
        assert r["error"]["code"] == "SESSION_CLEANUP_REQUIRED"
        assert "close_me" not in mgr.sessions
        assert mgr.tombstones["close_me"].state == "orphan_suspected"

    def test_close_all_closes_each_live_session_normally(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake
        mgr.open_session("close_all_a", fsdb="a.fsdb")
        mgr.open_session("close_all_b", fsdb="b.fsdb")
        sessions = {
            id(session): session for session in mgr.sessions.values()
        }

        result = mgr.close_all()

        assert mgr.sessions == {}
        assert result["ok"] is True
        assert result["summary"] == {"closed_count": 2, "unresolved_count": 0}
        assert all(session.state == "closed" for session in sessions.values())
        assert all(not session.process_alive() for session in sessions.values())

    def test_native_close_failure_is_tombstoned_with_manager_layer(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake
        mgr.open_session("partial_close", fsdb="test.fsdb")
        session = mgr.sessions["partial_close"]
        session.close = lambda: {
            "ok": False,
            "error": {
                "code": "SESSION_CLEANUP_PARTIAL_FAILURE",
                "message": "native close failed",
                "cleanup": {"native_backend": "failed"},
            },
        }

        result = mgr.close_session("partial_close")

        assert result["ok"] is False
        assert result["error"]["error_layer"] == "session_manager"
        assert result["error"]["cleanup"]["manager_record"] == "evicted"
        assert result["error"]["cleanup"]["tombstone"] == "retained_unresolved"
        assert "partial_close" not in mgr.sessions
        assert mgr.tombstones["partial_close"].state == "cleanup_partial"

    def test_cov_gc_confirms_dead_loop_without_native_fallback(self, tmp_path):
        fake = _fake_loop_script(tmp_path)
        mgr = _new_manager(
            backend="xcov",
            api_version="xcov.v1",
            ready_protocol="xdebug-stdio-loop",
            target_key="vdb",
        )
        mgr.xdebug_bin = fake
        opened = mgr.open_session("dead_cov", fsdb="merged.vdb")
        assert opened["ok"] is True
        session = mgr.sessions["dead_cov"]
        session.handle.terminate()

        result = mgr.gc_sessions()

        assert result["summary"]["removed_count"] == 1
        assert result["summary"]["unresolved_count"] == 0
        assert "dead_cov" not in mgr.sessions
        assert "dead_cov" not in mgr.tombstones


class TestOpenAfterLost:
    def test_open_after_session_lost_eviction(self, tmp_path):
        fake = _fake_loop_dead_session(tmp_path)
        mgr = _new_manager()
        mgr.xdebug_bin = fake

        mgr.open_session("reopen_me", fsdb="test.fsdb")
        mgr.query("reopen_me", "value.at", {"signal": "x"}, output_format="json")
        assert "reopen_me" not in mgr.sessions

        # Tombstone blocks implicit reopen until exact cleanup is confirmed.
        fake2 = _fake_loop_script(tmp_path)
        mgr.xdebug_bin = fake2
        r = mgr.open_session("reopen_me", fsdb="test.fsdb")
        assert not r.get("ok"), r
        assert r["error"]["code"] == "SESSION_TOMBSTONE_EXISTS"
        tombstone = mgr.tombstones["reopen_me"]
        tombstone._call_native_admin = (
            lambda action, **kwargs: {"ok": True, "action": action}
        )
        killed = mgr.kill_session("reopen_me")
        assert killed.get("ok"), killed
        gc = mgr.gc_sessions()
        assert gc["summary"]["removed_count"] == 1
        r = mgr.open_session("reopen_me", fsdb="test.fsdb")
        assert r.get("ok"), r
        assert "reopen_me" in mgr.sessions


class TestFixedNativeAdminPath:
    def test_dead_loop_doctor_and_kill_send_schema_valid_cli_requests(self, tmp_path):
        capture_path = tmp_path / "native_admin_requests.ndjson"
        session = _new_session(_fake_native_admin_cli(tmp_path, capture_path), alias="dead_admin")
        session.session_id = "native-session"
        session.state = "dead"
        token = "ab" * 32
        session._ownership_token = token

        doctor = session.doctor(verbose=True)
        killed = session.kill()

        assert doctor["summary"]["source"] == "fixed_native_admin"
        assert doctor["summary"]["backend_healthy"] is True
        assert doctor["backend_response"]["action"] == "session.doctor"
        assert killed["ok"] is True
        assert killed["cleanup"]["native_kill"] == "ok"

        requests = _read_ndjson(capture_path)
        assert [request["action"] for request in requests] == [
            "session.doctor",
            "session.close",
        ]
        assert requests[0] == {
            "api_version": "xdebug.v1",
            "action": "session.doctor",
            "target": {"session_id": "native-session"},
        }
        assert requests[1] == {
            "api_version": "xdebug.v1",
            "action": "session.close",
            "target": {"session_id": "native-session"},
            "args": {"mode": "force", "ownership_token": token},
        }
        assert token not in json.dumps(doctor, sort_keys=True)
        assert token not in json.dumps(killed, sort_keys=True)
        for request in requests:
            schema_path = (
                Path(__file__).resolve().parents[2]
                / "xdebug"
                / "schemas"
                / "v1"
                / "actions"
                / f"{request['action']}.request.schema.json"
            )
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(request)


class TestXoutFormatOnLost:
    def test_session_lost_in_json_even_with_xout_default(self, tmp_path):
        """When output_format=xout but session is dead, error still returns as dict."""
        s = _new_session(_fake_loop_script(tmp_path))
        r = s.query("value.at", {"signal": "x"})
        # Session not opened — should return dict error, not string
        assert isinstance(r, dict)
        assert not r.get("ok")
        assert r["error"]["code"] == "SESSION_DEAD"


# ---------------------------------------------------------------------------
# timeout helpers
# ---------------------------------------------------------------------------


def _fake_slow_script(dirpath: Path) -> str:
    """Fake xdebug that sleeps forever on any query (triggering timeout)."""
    return _make_fake_script(dirpath / "fake_slow", [
        "import json, sys, os, time",
        "",
        'print(json.dumps({"type":"ready","protocol":"xdebug-stdio-loop","version":1,"pid":os.getpid()}))',
        "sys.stdout.flush()",
        "",
        "for line in sys.stdin:",
        "    line = line.strip()",
        "    if not line: continue",
        "    try: req = json.loads(line)",
        "    except Exception: continue",
        '    rid = req.get("request_id", req.get("id", "unknown"))',
        '    action = req.get("action", "")',
        "",
        '    if action == "stdio.quit":',
        "        sys.exit(0)",
        "",
        '    if action == "session.open":',
        '        name = req.get("args", {}).get("name", "slow")',
        '        result = {"ok": True, "action": "session.open",',
        '                  "session": {"session_id": name, "mode": "combined"},',
        '                  "summary": {"status": "opened"}}',
        '        rsp = {"id": rid, "ok": True, "payload_format": "json", "json": result}',
        "        print(json.dumps(rsp))",
        "        sys.stdout.flush()",
        "    else:",
        "        # Sleep long enough to trigger timeout",
        "        time.sleep(99999)",
    ])


class TestTimeoutSessionLost:
    """Verify that query timeout results in SESSION_LOST and manager eviction."""

    def test_timeout_during_query(self, tmp_path):
        fake = _fake_slow_script(tmp_path)
        mgr = _new_manager(request_timeout_sec=0.5)
        mgr.xdebug_bin = fake

        r = mgr.open_session("slow", fsdb="test.fsdb")
        assert r.get("ok"), r
        assert "slow" in mgr.sessions
        assert mgr.sessions["slow"].state == "alive"

        # This query will timeout because fake script sleeps forever
        r = mgr.query("slow", "value.at", {"signal": "x"}, output_format="json")
        assert not r.get("ok"), r
        assert r["error"]["code"] == "SESSION_LOST"
        assert r["error"]["terminal_source"] == "transport"

        # Manager must have evicted the dead session
        assert "slow" not in mgr.sessions
        session_events = _session_events(tmp_path, "slow")
        stdio_events = _session_events(tmp_path, "slow", "stdio")
        assert any(e["phase"] == "manager.evict" for e in session_events)
        assert any(e["phase"] == "response.timeout" for e in stdio_events)


class TestLsfStructuredLog:
    def test_fake_lsf_logs_bsub_job_and_cleanup(self, tmp_path, monkeypatch):
        fake = _fake_loop_script(tmp_path)
        monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
        monkeypatch.setenv("FAKE_BSUB_SCHEDULER_FRAMING", "1")
        monkeypatch.setenv(
            "XVERIF_LSF_BKILL",
            shlex.join([sys.executable, "-c", "raise SystemExit(0)"]),
        )
        runner = BsubRunner(f"{sys.executable} -m xverif_loop.lsf.fake_bsub")
        runtime = _runtime(backend="lsf")
        s = XdebugLoopSession(
            alias="lsf_log", fsdb="t.fsdb", daidir=None,
            launcher=LsfLauncher(runner), runtime=runtime,
            logger=resolve_logger(runtime), xdebug_bin=fake,
            queue="interactive", resource="select[type==any]",
            job_name="xverif_lsf_log_test",
        )
        r = s.open()
        assert r.get("ok"), r
        s.close()

        lsf_events = _session_events(tmp_path, "lsf_log", "lsf")
        phases = [e["phase"] for e in lsf_events]
        assert "launcher.lsf.start" in phases
        assert "bsub.start" in phases
        assert "job_id.detected" in phases
        assert any(e.get("job_id") == "123" for e in lsf_events)
        assert any(e.get("queue") == "interactive" for e in lsf_events)

    def test_xcov_fake_lsf_uses_one_process_per_session_and_reports_queue_truth(
        self, tmp_path, monkeypatch,
    ):
        fake = _fake_loop_script(tmp_path)
        monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
        monkeypatch.setenv(
            "XVERIF_LSF_BKILL",
            shlex.join([sys.executable, "-c", "raise SystemExit(0)"]),
        )
        runtime = _runtime(backend="lsf")
        manager = McpSessionManager(
            runtime=runtime,
            xdebug_bin=fake,
            backend="xcov",
            api_version="xcov.v1",
            ready_protocol="xdebug-stdio-loop",
            target_key="vdb",
            recovery_tool="xverif_cov_session_open",
            logger=resolve_logger(runtime),
        )
        manager.launcher = LsfLauncher(
            BsubRunner(f"{sys.executable} -m xverif_loop.lsf.fake_bsub")
        )

        first = manager.open_session(
            "cov_lsf_a",
            fsdb="a.vdb",
            queue="cov_queue",
            resource="select[mem>1024]",
        )
        second = manager.open_session("cov_lsf_b", fsdb="b.vdb")
        try:
            assert first["ok"] is True, first
            assert second["ok"] is True, second
            first_session = manager.sessions["cov_lsf_a"]
            second_session = manager.sessions["cov_lsf_b"]
            assert first_session.handle.proc.pid != second_session.handle.proc.pid
            assert first_session.handle.argv[-2:] == [fake, "--stdio-loop"]
            first_argv = first_session.handle.argv
            assert first_argv[first_argv.index("-q") + 1] == "cov_queue"
            assert first_argv[first_argv.index("-R") + 1] == "select[mem>1024]"
            assert first_argv[first_argv.index("-J") + 1] == first_session.job_name
            scheduler = first["session"]["scheduler"]
            assert scheduler == {
                "mode": "lsf",
                "status": "ready",
                "requested": {
                    "queue": "cov_queue",
                    "resource": "select[mem>1024]",
                },
                "effective": {
                    "queue": "cov_queue",
                    "resource": "select[mem>1024]",
                },
                "submitted": {
                    "queue": "cov_queue",
                    "resource": "select[mem>1024]",
                    "job_name": first_session.job_name,
                    "job_id": "123",
                },
            }
            default_scheduler = second["session"]["scheduler"]
            assert default_scheduler["requested"] == {
                "queue": None, "resource": None,
            }
            assert default_scheduler["effective"] == {
                "queue": "interactive", "resource": None,
            }
            assert default_scheduler["submitted"]["queue"] == "interactive"
        finally:
            closed = manager.close_all()
            assert closed["ok"] is True, closed

    def test_xcov_fake_lsf_pending_timeout_reports_status_and_cleans_job(
        self, tmp_path, monkeypatch,
    ):
        fake = _fake_loop_script(tmp_path)
        monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
        monkeypatch.setenv("FAKE_BSUB_PENDING_DELAY_MS", "250")
        monkeypatch.setenv(
            "XVERIF_LSF_BKILL",
            shlex.join([sys.executable, "-c", "raise SystemExit(0)"]),
        )
        runtime = _runtime(backend="lsf").with_overrides(
            startup_timeout_sec=0.05,
        )
        session = XdebugLoopSession(
            alias="cov_lsf_pending",
            fsdb="pending.vdb",
            daidir=None,
            launcher=LsfLauncher(
                BsubRunner(f"{sys.executable} -m xverif_loop.lsf.fake_bsub")
            ),
            runtime=runtime,
            logger=resolve_logger(runtime),
            xdebug_bin=fake,
            backend="xcov",
            api_version="xcov.v1",
            ready_protocol="xdebug-stdio-loop",
            target_key="vdb",
            requested_queue=None,
            queue="interactive",
            job_name="xverif_cov_pending_test",
        )

        response = session.open()

        assert response["ok"] is False
        assert response["error"]["code"] == "SESSION_OPEN_FAILED"
        assert response["error"]["scheduler"]["status"] == "startup_timeout"
        assert response["error"]["scheduler"]["submitted"]["queue"] == "interactive"
        assert response["error"]["cleanup"]["subprocess"] == "terminated"
        assert response["error"]["cleanup"]["lsf_job"] == "confirmed"

    def test_xcov_fake_lsf_rejection_is_typed_and_never_runs_direct(
        self, tmp_path, monkeypatch,
    ):
        fake = _fake_loop_script(tmp_path)
        monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
        monkeypatch.setenv("FAKE_BSUB_EXIT_BEFORE_READY", "1")
        monkeypatch.setenv(
            "XVERIF_LSF_BKILL",
            shlex.join([sys.executable, "-c", "raise SystemExit(0)"]),
        )
        runtime = _runtime(backend="lsf")
        session = XdebugLoopSession(
            alias="cov_lsf_rejected",
            fsdb="rejected.vdb",
            daidir=None,
            launcher=LsfLauncher(
                BsubRunner(f"{sys.executable} -m xverif_loop.lsf.fake_bsub")
            ),
            runtime=runtime,
            logger=resolve_logger(runtime),
            xdebug_bin=fake,
            backend="xcov",
            api_version="xcov.v1",
            ready_protocol="xdebug-stdio-loop",
            target_key="vdb",
            requested_queue="reject_queue",
            queue="reject_queue",
            job_name="xverif_cov_rejection_test",
        )

        response = session.open()

        assert response["ok"] is False
        assert response["error"]["code"] == "SESSION_OPEN_FAILED"
        scheduler = response["error"]["scheduler"]
        assert scheduler["mode"] == "lsf"
        assert scheduler["status"] == "startup_rejected"
        assert scheduler["submitted"]["queue"] == "reject_queue"
        assert scheduler["submitted"]["job_id"] == "123"
        assert response["error"]["cleanup"]["subprocess"] == "terminated"
        assert response["error"]["cleanup"]["lsf_job"] == "confirmed"
        assert session.launcher.mode == "lsf"
