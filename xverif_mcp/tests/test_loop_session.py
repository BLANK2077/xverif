"""Unit tests for XdebugLoopSession (fake process)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from xverif_loop.config import (
    default_xdebug_bin,
    resolve_mcp_runtime_config,
)
from xverif_loop.lsf.protocol import JsonlProcess
from xverif_loop.logging import resolve_logger
from xverif_loop.sessions.launchers import DirectLauncher, LaunchConfig
from xverif_loop.sessions.loop_session import XdebugLoopSession, _safe_name
from xverif_loop.sessions.session_manager import McpSessionManager

TEST_RUNTIME = resolve_mcp_runtime_config().with_overrides(
    backend="direct",
    startup_timeout_sec=5.0,
    request_timeout_sec=5.0,
)
TEST_LOGGER = resolve_logger(TEST_RUNTIME)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_xdebug_script(tmpdir: Path) -> str:
    """Create a tiny fake xdebug that speaks the --stdio-loop protocol."""
    script = tmpdir / "fake_xdebug"
    script.write_text(r"""#!/usr/bin/env python3
import json, sys, os, time

if "--stdio-loop" not in sys.argv:
    request = json.loads(sys.stdin.readline())
    print(json.dumps({
        "api_version": "xdebug.v1",
        "action": request.get("action"),
        "ok": True,
        "summary": {"removed": True},
        "data": {},
    }))
    sys.exit(0)

# ready
print(json.dumps({"type":"ready","protocol":"xdebug-stdio-loop","version":1,"pid":os.getpid()}))
sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception:
        continue

    rid = req.get("request_id", req.get("id", "unknown"))
    action = req.get("action", "")
    args = req.get("args", {})
    target = req.get("target", {})
    limits = req.get("limits", {})
    output = req.get("output", {})
    wants_json = (output.get("format") == "json" or
                  output.get("response_format") == "json" or
                  req.get("payload_format") == "json")

    if action == "stdio.quit":
        rsp = {"id": rid, "ok": True, "payload_format": "json", "json": {"ok": True, "action": "stdio.quit"}}
        print(json.dumps(rsp))
        sys.stdout.flush()
        sys.exit(0)

    if action == "session.open":
        name = args.get("name", "unknown")
        returned_name = "unexpected_backend_id" if name == "mismatch_test" else name
        result = {
            "ok": True, "action": "session.open",
            "session": {"session_id": returned_name, "mode": "combined"},
            "summary": {
                "status": "opened",
                "open_args": args,
                "open_target": target,
            },
        }
    elif action == "value.at":
        delay = float(args.get("sleep", 0))
        if delay:
            time.sleep(delay)
        result = {"ok": True, "action": "value.at",
                  "summary": {"signal": args.get("signal"), "value": "1"}}
    elif action == "bad.args":
        result = {
            "ok": False,
            "action": "bad.args",
            "error": {
                "code": "INVALID_REQUEST",
                "message": "invalid parameter args.bad",
                "recoverable": True,
                "error_layer": "schema",
                "invalid_arg": "args.bad",
                "expected": "no additional properties allowed",
                "correct_example": {
                    "api_version": "xdebug.v1",
                    "action": "bad.args",
                    "target": {"session_id": "native_session"},
                    "args": {}
                }
            }
        }
    else:
        result = {"ok": True, "action": action,
                  "summary": {"echo_args": args, "echo_target": target, "echo_limits": limits}}

    if not result.get("ok"):
        if wants_json:
            rsp = {"id": rid, "ok": False, "payload_format": "json", "error": result["error"], "json": result}
        else:
            xout = "@xdebug.error.v1\naction: " + action + "\ncode: " + result["error"]["code"] + "\n"
            rsp = {"id": rid, "ok": False, "payload_format": "xout", "error": result["error"], "json": result, "xout": xout}
        print(json.dumps(rsp))
        sys.stdout.flush()
        continue

    if wants_json:
        rsp = {"id": rid, "ok": True, "payload_format": "json", "json": result}
    else:
        xout = f"@xdebug.{action}.v1\n\nsummary:\n  signal: {args.get('signal','?')}\n  value: 0x1\n"
        rsp = {"id": rid, "ok": True, "payload_format": "xout", "xout": xout}

    print(json.dumps(rsp))
    sys.stdout.flush()
""")
    script.chmod(0o755)
    return str(script)


@pytest.fixture
def fake_xdebug_bin(tmp_path):
    return _fake_xdebug_script(tmp_path)


@pytest.fixture
def session(fake_xdebug_bin):
    s = XdebugLoopSession(
        alias="test",
        fsdb="test.fsdb",
        daidir=None,
        launcher=DirectLauncher(),
        runtime=TEST_RUNTIME,
        logger=TEST_LOGGER,
        xdebug_bin=fake_xdebug_bin,
    )
    yield s
    try:
        s.close(force=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestSafeName:
    def test_basic(self):
        assert _safe_name("hello") == "hello"

    def test_special_chars(self):
        assert _safe_name("user.name") == "user_name"

    def test_empty(self):
        assert _safe_name("") == "unnamed"

    def test_max_len(self):
        long = "a" * 100
        assert len(_safe_name(long, max_len=32)) <= 32


class TestLoopSessionOpen:
    def test_open_alive(self, session):
        r = session.open()
        assert r.get("ok"), r
        assert session.state == "alive"
        assert session.session_id == "test"

    def test_open_does_not_send_reuse_or_reopen(self, fake_xdebug_bin):
        s = XdebugLoopSession(
            alias="test2", fsdb="t.fsdb", daidir=None,
            launcher=DirectLauncher(), runtime=TEST_RUNTIME,
            logger=TEST_LOGGER,
            xdebug_bin=fake_xdebug_bin,
        )
        try:
            r = s.open()
            assert r.get("ok")
            assert s.state == "alive"
            rsp = s.query("fake", {}, output_format="json")
            assert rsp["summary"]["echo_target"]["session_id"] == "test2"
        finally:
            s.close(force=True)

    def test_open_rejects_backend_session_id_mismatch_and_cleans_up(
        self,
        fake_xdebug_bin,
        tmp_path,
    ):
        runtime = resolve_mcp_runtime_config(
            environ={
                "HOME": str(tmp_path / "home"),
                "XVERIF_MCP_LOG_DIR": str(tmp_path / "logs"),
            },
        ).with_overrides(
            backend="direct",
            startup_timeout_sec=5.0,
            request_timeout_sec=5.0,
        )
        logger = resolve_logger(runtime)
        s = XdebugLoopSession(
            alias="mismatch_test",
            fsdb="t.fsdb",
            daidir=None,
            launcher=DirectLauncher(),
            runtime=runtime,
            logger=logger,
            xdebug_bin=fake_xdebug_bin,
        )
        requests = []
        admin_calls = []
        call_raw = s._call_raw

        def capture(request, timeout=None):
            requests.append(request)
            result = call_raw(request, timeout)
            if request["action"] == "session.open":
                result["json"]["summary"]["opaque_echo"] = (
                    "backend echoed "
                    + request["args"]["ownership_token"]
                )
            return result

        def conditional_cleanup(action, **kwargs):
            admin_calls.append((action, kwargs))
            return {"ok": True, "action": action}

        s._call_raw = capture
        s._call_native_admin = conditional_cleanup

        response = s.open()

        opened = next(
            request
            for request in requests
            if request["action"] == "session.open"
        )
        token = opened["args"]["ownership_token"]
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)
        assert admin_calls == [
            (
                "session.kill",
                {
                    "session_id": "mismatch_test",
                    "ownership_token": token,
                },
            )
        ]
        assert response["ok"] is False
        assert response["error"]["code"] == "BACKEND_SESSION_ID_MISMATCH"
        assert response["error"]["requested_session_id"] == "mismatch_test"
        assert response["error"]["backend_session_id"] == "unexpected_backend_id"
        assert response["error"]["cleanup_complete"] is True
        assert response["error"]["cleanup_outcome"] == "cleaned"
        assert response["error"]["cleanup"]["subprocess"] == "terminated"
        assert (
            response["error"]["cleanup"]["conditional_cleanup"]["outcome"]
            == "cleaned"
        )
        backend_summary = response["error"]["backend_response"]["summary"]
        assert backend_summary["open_args"]["ownership_token"] == {
            "redacted": True,
        }
        assert backend_summary["opaque_echo"] == (
            "backend echoed <redacted>"
        )
        assert token not in json.dumps(response, sort_keys=True)
        assert token not in json.dumps(s.public_json(), sort_keys=True)
        log_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in runtime.log_root.rglob("*.ndjson")
        )
        assert token not in log_text
        assert s.state == "closed"
        assert not s.process_alive()

    @pytest.mark.parametrize(
        (
            "admin_response",
            "cleanup_outcome",
            "cleanup_complete",
            "state",
        ),
        [
            (
                {"ok": True, "action": "session.kill"},
                "cleaned",
                True,
                "closed",
            ),
            (
                {
                    "ok": False,
                    "error": {
                        "code": "SESSION_NOT_FOUND",
                        "message": "not created",
                    },
                },
                "not_created",
                True,
                "closed",
            ),
            (
                {
                    "ok": False,
                    "error": {
                        "code": "SESSION_OWNERSHIP_TOKEN_MISMATCH",
                        "message": "different open record",
                    },
                },
                "token_mismatch",
                True,
                "closed",
            ),
            (
                {
                    "ok": False,
                    "error": {
                        "code": "SESSION_CLEANUP_FAILED",
                        "message": "cleanup failed",
                    },
                },
                "cleanup_failed",
                False,
                "orphan_suspected",
            ),
        ],
    )
    def test_rejected_open_has_exact_conditional_cleanup_outcome(
        self,
        fake_xdebug_bin,
        admin_response,
        cleanup_outcome,
        cleanup_complete,
        state,
    ):
        s = XdebugLoopSession(
            alias="rejected_open",
            fsdb="t.fsdb",
            daidir=None,
            launcher=DirectLauncher(),
            runtime=TEST_RUNTIME,
            logger=TEST_LOGGER,
            xdebug_bin=fake_xdebug_bin,
        )
        requests = []
        admin_calls = []

        def reject_open(request, timeout=None):
            requests.append(request)
            return {
                "ok": False,
                "json": {
                    "ok": False,
                    "action": "session.open",
                    "error": {
                        "code": "OPEN_REJECTED",
                        "message": "open rejected after dispatch",
                    },
                },
            }

        def conditional_cleanup(action, **kwargs):
            admin_calls.append((action, kwargs))
            return admin_response

        s._call_raw = reject_open
        s._call_native_admin = conditional_cleanup

        response = s.open()

        token = requests[0]["args"]["ownership_token"]
        assert admin_calls == [
            (
                "session.kill",
                {
                    "session_id": "rejected_open",
                    "ownership_token": token,
                },
            )
        ]
        assert response["ok"] is False
        assert response["error"]["code"] == "SESSION_OPEN_REJECTED"
        assert response["error"]["cleanup_outcome"] == cleanup_outcome
        assert response["error"]["cleanup_complete"] is cleanup_complete
        assert s.state == state
        assert token not in json.dumps(response, sort_keys=True)

    def test_open_forwards_run_manifest_in_native_target(self, fake_xdebug_bin):
        s = XdebugLoopSession(
            alias="manifest_test", fsdb="t.fsdb", daidir=None,
            run_manifest="run-manifest.json",
            launcher=DirectLauncher(), runtime=TEST_RUNTIME,
            logger=TEST_LOGGER,
            xdebug_bin=fake_xdebug_bin,
        )
        try:
            requests = []
            call_raw = s._call_raw

            def capture(request, timeout=None):
                requests.append(request)
                return call_raw(request, timeout)

            s._call_raw = capture
            response = s.open()
            assert response["ok"] is True
            opened = next(request for request in requests if request["action"] == "session.open")
            assert opened["target"]["run_manifest"] == "run-manifest.json"
        finally:
            s.close(force=True)

    def test_public_json_reports_stat_and_declared_manifest_identity(self, fake_xdebug_bin, tmp_path):
        fsdb = tmp_path / "waves.fsdb"
        manifest = tmp_path / "run-manifest.json"
        fsdb.write_bytes(b"fixture")
        manifest.write_text('{"state":"published"}\n', encoding="utf-8")
        s = XdebugLoopSession(
            alias="identity_test", fsdb=str(fsdb), daidir=None,
            run_manifest=str(manifest), launcher=DirectLauncher(),
            runtime=TEST_RUNTIME, logger=TEST_LOGGER,
            xdebug_bin=fake_xdebug_bin,
        )
        try:
            public = s.public_json()
            identity = public["resource_identity"]
            assert public["session_id"] is None
            assert "alias" not in public
            assert "resource_hash" not in public
            assert identity["content_identity"] == "manifest_declared"
            assert identity["stat"]["size_bytes"] == len(b"fixture")
            assert identity["manifest_sha256"]
        finally:
            s.close(force=True)

    def test_launcher_start_failure_returns_structured_open_error(self):
        class MissingLauncher(DirectLauncher):
            def start(self, cfg):
                raise FileNotFoundError("required launcher executable is unavailable")

        session = XdebugLoopSession(
            alias="missing_launcher",
            fsdb="test.fsdb",
            daidir=None,
            launcher=MissingLauncher(),
            runtime=TEST_RUNTIME,
            logger=TEST_LOGGER,
            xdebug_bin="/missing/xdebug",
        )

        result = session.open()

        assert result["ok"] is False
        assert result["error"]["code"] == "SESSION_OPEN_FAILED"
        assert result["error"]["message"] == (
            "session.open failed before native dispatch"
        )
        assert result["error"]["error_type"] == "FileNotFoundError"
        assert "launcher executable" not in json.dumps(
            result,
            sort_keys=True,
        )
        assert result["error"]["cleanup"]["subprocess"] == "not_started"
        assert session.state == "dead"


class TestLoopSessionQuery:
    def test_empty_args_object_is_preserved(self, session):
        assert session.open()["ok"] is True
        requests = []
        call_raw = session._call_raw

        def capture(request, timeout=None):
            requests.append(request)
            return call_raw(request, timeout)

        session._call_raw = capture
        response = session.query(
            "waveform.cursor.list",
            {},
            output_format="json",
        )

        assert response["ok"] is True
        assert requests[-1]["args"] == {}

    def test_xout_format(self, session):
        session.open()
        r = session.query("value.at", {"signal": "clk"}, output_format="xout")
        assert isinstance(r, str)
        assert r.startswith("@xdebug.")

    def test_json_format(self, session):
        session.open()
        r = session.query("value.at", {"signal": "clk"}, output_format="json")
        assert isinstance(r, dict)
        assert r.get("ok")

    def test_wrapper_error_stays_structured_instead_of_inventing_xout(self, session):
        session.open()
        r = session.query("bad.args", {"bad": True}, output_format="xout")
        assert isinstance(r, dict)
        assert r["ok"] is False
        assert r["error"]["error_layer"] == "schema"
        example = r["error"]["correct_example"]
        assert example["tool"] == "xverif_debug_query"
        assert example["args"]["session_id"] == "test"
        assert "api_version" not in example["args"]

    def test_json_error_uses_mcp_correct_example(self, session):
        session.open()
        r = session.query("bad.args", {"bad": True}, output_format="json")
        assert isinstance(r, dict)
        assert r["ok"] is False
        assert r["error"]["correct_example"]["tool"] == "xverif_debug_query"
        example_args = r["error"]["correct_example"]["args"]
        assert example_args["session_id"] == "test"
        assert example_args["action"] == "bad.args"
        assert "api_version" not in example_args

    def test_envelope_format(self, session):
        session.open()
        r = session.query("value.at", {"signal": "clk"}, output_format="envelope")
        assert isinstance(r, dict)

    def test_target_override_is_ignored(self, session):
        session.open()
        r = session.query("fake", {}, target={"fsdb": "override.fsdb"}, output_format="json")
        echo = r.get("summary", {}).get("echo_target", {})
        assert echo == {"session_id": "test"}

    def test_limits_passthrough(self, session):
        session.open()
        r = session.query("fake", {}, limits={"max_items": 42}, output_format="json")
        echo = r.get("summary", {}).get("echo_limits", {})
        assert echo.get("max_items") == 42

    def test_no_target_uses_session_id(self, session):
        session.open()
        r = session.query("fake", {}, output_format="json")
        echo = r.get("summary", {}).get("echo_target", {})
        assert echo.get("session_id") == "test"

    def test_request_lock_serial(self, session):
        """同一 session 的并发 query 应该串行执行。"""
        session.open()
        results = []
        errors = []

        def query_with_sleep():
            try:
                r = session.query("value.at", {"signal": "clk", "sleep": 0.1}, output_format="json")
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=query_with_sleep)
        t2 = threading.Thread(target=query_with_sleep)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(results) == 2, f"expected 2 results, got {len(results)}; errors={errors}"
        assert all(r.get("ok") for r in results)


class TestLoopSessionClose:
    def test_close_changes_state(self, session):
        session.open()
        r = session.close()
        assert r["ok"] is True
        assert r["cleanup"]["backend_close"] == "ok"
        assert r["cleanup"]["stdio_quit"] == "ok"
        assert r["cleanup"]["terminate"] == "ok"
        assert session.state == "closed"

    def test_dead_session_query_fails(self, session):
        session.open()
        session.close()
        r = session.query("value.at", {"signal": "clk"}, output_format="json")
        assert not r.get("ok")
        assert r["error"]["code"] == "SESSION_DEAD"

    def test_close_backend_failure_reports_partial_failure(self, session, monkeypatch):
        session.open()
        original_call_raw = session._call_raw

        def fail_backend_close(req, *args, **kwargs):
            if req.get("action") == "session.close":
                raise RuntimeError("backend close failed")
            return original_call_raw(req, *args, **kwargs)

        monkeypatch.setattr(session, "_call_raw", fail_backend_close)
        r = session.close()

        assert r["ok"] is False
        assert r["error"]["code"] == "SESSION_CLEANUP_PARTIAL_FAILURE"
        assert r["error"]["cleanup"]["backend_close"] == "failed"
        assert "backend close failed" in r["error"]["cleanup"]["errors"]["backend_close"]
        assert r["error"]["cleanup"]["stdio_quit"] == "ok"
        assert r["error"]["cleanup"]["terminate"] == "ok"
        assert session.state == "alive"

    def test_close_terminate_failure_reports_partial_failure(self, fake_xdebug_bin):
        class FailingTerminateLauncher(DirectLauncher):
            def terminate(self, handle):
                raise RuntimeError("terminate failed")

        s = XdebugLoopSession(
            alias="termfail",
            fsdb="test.fsdb",
            daidir=None,
            launcher=FailingTerminateLauncher(),
            runtime=TEST_RUNTIME,
            logger=TEST_LOGGER,
            xdebug_bin=fake_xdebug_bin,
        )
        try:
            assert s.open()["ok"] is True
            r = s.close()
            assert r["ok"] is False
            assert r["error"]["code"] == "SESSION_CLEANUP_PARTIAL_FAILURE"
            assert r["error"]["cleanup"]["terminate"] == "failed"
            assert "terminate failed" in r["error"]["cleanup"]["errors"]["terminate"]
            assert s.state == "alive"
        finally:
            try:
                DirectLauncher().terminate(s.handle)
            except Exception:
                pass

    def test_manager_tombstones_session_after_close_partial_failure(self, fake_xdebug_bin, monkeypatch):
        manager = McpSessionManager(
            runtime=TEST_RUNTIME,
            xdebug_bin=fake_xdebug_bin,
            logger=TEST_LOGGER,
        )
        assert manager.open_session("keep", fsdb="test.fsdb")["ok"] is True
        assert list(manager.sessions) == ["keep"]
        s = manager.sessions["keep"]
        original_call_raw = s._call_raw

        def fail_backend_close(req, *args, **kwargs):
            if req.get("action") == "session.close":
                raise RuntimeError("backend close failed")
            return original_call_raw(req, *args, **kwargs)

        monkeypatch.setattr(s, "_call_raw", fail_backend_close)
        r = manager.close_session("keep")

        assert r["ok"] is False
        assert r["error"]["code"] == "SESSION_CLEANUP_PARTIAL_FAILURE"
        assert r["error"]["error_layer"] == "session_manager"
        assert "keep" not in manager.sessions
        assert manager.tombstones["keep"] is s
        assert s.state == "cleanup_partial"
