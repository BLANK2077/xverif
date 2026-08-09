"""UDS JSONL tests for the SDK-free loop wrapper."""

from __future__ import annotations

import json
import shlex
import socket
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from xverif_loop.wrapper import LoopWrapperServer, LoopWrapperService, send_requests


def _make_fake_loop(path: Path, *, protocol: str, api_version: str, slow_query: bool = False) -> str:
    path.write_text(
        f"""#!/usr/bin/env python3
import json, os, sys, time

print(json.dumps({{"type":"ready","protocol":{protocol!r},"version":1,"pid":os.getpid()}}))
sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    rid = req.get("request_id", req.get("id", "unknown"))
    action = req.get("action", "")
    output = req.get("output", {{}})
    wants_json = (output.get("format") == "json" or
                  output.get("response_format") == "json" or
                  req.get("payload_format") == "json")
    if action == "stdio.quit":
        rsp = {{"id": rid, "ok": True, "payload_format": "json", "json": {{"ok": True, "action": "stdio.quit"}}}}
        print(json.dumps(rsp)); sys.stdout.flush(); sys.exit(0)
    if action == "session.open":
        name = req.get("args", {{}}).get("name", "fake")
        if {api_version!r} == "xcov":
            result = {{
                "ok": True,
                "api_version": "xcov.v1",
                "request_id": rid,
                "action": action,
                "summary": {{
                    "total_count": 1,
                    "returned_count": 1,
                    "response_truncated": False,
                    "scan_complete": True,
                    "analysis_complete": True,
                    "truncation_scopes": [],
                }},
                "data": {{
                    "session": {{
                        "session_id": name,
                        "state": "alive",
                        "vdb": req.get("target", {{}}).get("vdb"),
                        "test_count": 1,
                        "top_scope_count": 1,
                        "worker": "fake",
                    }},
                    "resource_snapshot": {{
                        "vdb": req.get("target", {{}}).get("vdb"),
                        "run_manifest": None,
                    }},
                }},
                "warnings": [],
            }}
        else:
            result = {{"ok": True, "action": action,
                       "session": {{"session_id": name, "mode": "fake"}},
                       "summary": {{"status": "opened"}}}}
    else:
        if {slow_query!r}:
            time.sleep(999)
        if {api_version!r} == "xcov":
            result = {{
                "ok": True,
                "api_version": "xcov.v1",
                "request_id": rid,
                "action": action,
                "summary": {{
                    "total_count": 0,
                    "returned_count": 0,
                    "response_truncated": False,
                    "scan_complete": True,
                    "analysis_complete": True,
                    "truncation_scopes": [],
                }},
                "data": {{"echo_args": req.get("args", {{}})}},
                "warnings": [],
            }}
        else:
            result = {{"ok": True, "action": action, "summary": {{"echo_args": req.get("args", {{}})}}}}
    if {api_version!r} == "xcov":
        rsp = {{"id": rid, "ok": True, "payload_format": "xout",
               "json": result, "xout": "@xcov.v1 ok action=" + action + " request_id=unit\\n"}}
    elif wants_json:
        rsp = {{"id": rid, "ok": True, "payload_format": "json", "json": result}}
    else:
        rsp = {{"id": rid, "ok": True, "payload_format": "xout", "xout": "@{api_version}." + action + ".v1\\n"}}
    print(json.dumps(rsp)); sys.stdout.flush()
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def _start_server(tmp_path: Path, service: LoopWrapperService) -> tuple[LoopWrapperServer, threading.Thread, str]:
    sock = str(tmp_path / "wrapper.sock")
    server = LoopWrapperServer(sock, service=service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.wait_until_ready(timeout_sec=5.0)
    return server, thread, sock


def _send_raw(socket_path: str, payload: str) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(socket_path)
        reader = sock.makefile("r", encoding="utf-8")
        writer = sock.makefile("w", encoding="utf-8")
        writer.write(payload + "\n")
        writer.flush()
        return json.loads(reader.readline())


def _read_ndjson(path: Path) -> list[dict]:
    assert path.exists(), path
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _session_log(root: Path, alias: str, name: str) -> list[dict]:
    return _read_ndjson(root / "sessions" / alias / f"{name}.ndjson")


@pytest.mark.parametrize("kind", ("file", "symlink"))
def test_loop_wrapper_rejects_unsafe_existing_socket_path(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(tmp_path / "logs"))
    target = tmp_path / "target"
    target.write_text("do not delete")
    socket_path = tmp_path / "wrapper.sock"
    if kind == "file":
        socket_path.write_text("do not delete")
    else:
        socket_path.symlink_to(target)
    server = LoopWrapperServer(str(socket_path), service=LoopWrapperService(mode="direct"))
    with pytest.raises(RuntimeError, match="SOCKET_PATH_UNSAFE"):
        server.serve_forever()
    assert target.read_text() == "do not delete"


def test_loop_wrapper_reports_bad_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(tmp_path / "logs"))
    debug = _make_fake_loop(tmp_path / "fake_xdebug", protocol="xdebug-stdio-loop", api_version="xdebug")
    cov = _make_fake_loop(tmp_path / "fake_xcov", protocol="xcov-stdio-loop", api_version="xcov")
    service = LoopWrapperService(mode="direct", xdebug_bin=debug, xcov_bin=cov)
    server, thread, sock = _start_server(tmp_path, service)
    try:
        invalid = _send_raw(sock, "{private-invalid-json")
        assert invalid["ok"] is False
        assert invalid["error"]["code"] == "INVALID_JSON"
        assert invalid["error"]["message"] == (
            "request must be one strict JSON object"
        )
        non_finite = _send_raw(
            sock,
            '{"id":"private-request-id","method":"server.ping",'
            '"params":{"value":NaN}}',
        )
        assert non_finite["ok"] is False
        assert non_finite["error"]["code"] == "INVALID_JSON"
        unknown = send_requests(sock, [{"id": "u", "method": "missing.method", "params": {}}])[0]
        assert unknown["ok"] is False
        assert unknown["error"]["code"] == "UNKNOWN_METHOD"
        missing = send_requests(
            sock,
            [{
                "id": "m",
                "method": "debug.query",
                "params": {"session_id": "d0"},
            }],
        )[0]
        assert missing["ok"] is False
        assert missing["error"]["code"] == "INVALID_PARAMS"
        unsupported_output = send_requests(sock, [{
            "id": "o",
            "method": "debug.query",
            "params": {
                "session_id": "d0",
                "action": "value.at",
                "output": {"response_format": "json"},
            },
        }])[0]
        assert unsupported_output["ok"] is False
        assert unsupported_output["error"]["code"] == "INVALID_PARAMS"
        for method, params in (
            ("debug.session.doctor", {"session": "d0"}),
            ("debug.session.close", {"name": "d0"}),
            ("debug.session.kill", {"session": "d0"}),
            ("debug.query", {"session": "d0", "action": "value.at"}),
            ("cov.session.doctor", {"session": "c0"}),
            ("cov.session.close", {"name": "c0"}),
            ("cov.session.kill", {"session": "c0"}),
            ("cov.query", {"session": "c0", "action": "code_coverage.summary"}),
        ):
            legacy = send_requests(
                sock,
                [{"id": "legacy", "method": method, "params": params}],
            )[0]
            assert legacy["ok"] is False
            assert legacy["error"]["code"] == "INVALID_PARAMS"
            assert "unexpected params" in legacy["error"]["message"]
        invalid_shutdown = send_requests(
            sock,
            [{
                "id": "shutdown-invalid",
                "method": "server.shutdown",
                "params": False,
            }],
        )[0]
        assert invalid_shutdown["ok"] is False
        assert invalid_shutdown["error"]["code"] == "INVALID_REQUEST"
        still_running = send_requests(
            sock,
            [{"id": "still-running", "method": "server.ping", "params": {}}],
        )[0]
        assert still_running["ok"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "request_payload",
    [
        False,
        [],
        {"id": "case", "method": "server.ping"},
        {"id": "case", "params": {}},
        {"method": "server.ping", "params": {}},
        {
            "id": "case",
            "method": "server.ping",
            "params": {},
            "unknown": True,
        },
        {"id": 1, "method": "server.ping", "params": {}},
        {"id": False, "method": "server.ping", "params": {}},
        {"id": "case", "method": False, "params": {}},
        {"id": "case", "method": "server.ping", "params": False},
        {"id": "case", "method": "server.ping", "params": []},
    ],
)
def test_loop_wrapper_envelope_is_exact_and_closed(request_payload):
    service = LoopWrapperService(
        mode="direct",
        xdebug_bin="false",
        xcov_bin="false",
    )
    rsp = service.dispatch(request_payload)
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("server.ping", {"unknown": True}),
        ("debug.session.list", {"verbose": 1}),
        ("debug.session.list", {"include_tombstones": "false"}),
        ("debug.session.open", {"name": 1, "fsdb": "wave.fsdb"}),
        ("debug.session.open", {"name": "case", "fsdb": False}),
        ("debug.session.open", {"name": "case", "fsdb": ""}),
        (
            "debug.query",
            {"session_id": "case", "action": "value.at", "args": False},
        ),
        (
            "debug.query",
            {"session_id": "case", "action": "value.at", "args": []},
        ),
        (
            "debug.query",
            {"session_id": "case", "action": "value.at", "args": None},
        ),
        (
            "debug.query",
            {"session_id": "case", "action": "value.at", "limits": False},
        ),
        (
            "debug.query",
            {
                "session_id": "case",
                "action": "value.at",
                "output_format": 1,
            },
        ),
        (
            "debug.query",
            {
                "session_id": "case",
                "action": "value.at",
                "output_format": "yaml",
            },
        ),
        (
            "cov.query",
            {
                "session_id": "case",
                "action": "code_coverage.summary",
                "args": False,
            },
        ),
        (
            "cov.session.doctor",
            {"session_id": 1, "verbose": False},
        ),
        ("cov.session.gc", {"verbose": 0}),
    ],
)
def test_loop_wrapper_method_params_use_exact_types(method, params):
    service = LoopWrapperService(
        mode="direct",
        xdebug_bin="false",
        xcov_bin="false",
    )
    rsp = service.dispatch(
        {"id": "contract", "method": method, "params": params},
    )
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "INVALID_PARAMS"


def test_loop_wrapper_query_timeout_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(tmp_path / "logs"))
    debug = _make_fake_loop(
        tmp_path / "fake_xdebug",
        protocol="xdebug-stdio-loop",
        api_version="xdebug",
        slow_query=True,
    )
    cov = _make_fake_loop(tmp_path / "fake_xcov", protocol="xcov-stdio-loop", api_version="xcov")
    service = LoopWrapperService(
        mode="direct",
        xdebug_bin=debug,
        xcov_bin=cov,
        startup_timeout_sec=2.0,
        request_timeout_sec=0.2,
    )
    server, thread, sock = _start_server(tmp_path, service)
    try:
        open_rsp = send_requests(sock, [
            {"id": "open", "method": "debug.session.open", "params": {"name": "slow", "fsdb": "wave.fsdb"}}
        ])[0]
        assert open_rsp["ok"] is True
        query_rsp = send_requests(sock, [
            {"id": "query", "method": "debug.query", "params": {
                "session_id": "slow", "action": "value.at", "args": {"signal": "clk"}, "output_format": "json"}}
        ], timeout_sec=2.0)[0]
        assert query_rsp["ok"] is False
        assert query_rsp["error"]["code"] == "SESSION_LOST"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_loop_wrapper_logs_invalid_json_and_redacts_paths(tmp_path, monkeypatch):
    log_root = tmp_path / "logs"
    private_dir = tmp_path / "very" / "private"
    private_dir.mkdir(parents=True)
    private_fsdb = private_dir / "wave.fsdb"
    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(log_root))
    debug = _make_fake_loop(tmp_path / "fake_xdebug", protocol="xdebug-stdio-loop", api_version="xdebug")
    cov = _make_fake_loop(tmp_path / "fake_xcov", protocol="xcov-stdio-loop", api_version="xcov")
    service = LoopWrapperService(mode="direct", xdebug_bin=debug, xcov_bin=cov)
    server, thread, sock = _start_server(tmp_path, service)
    try:
        invalid = _send_raw(sock, "{private-invalid-json")
        assert invalid["ok"] is False
        non_finite = _send_raw(
            sock,
            '{"id":"private-request-id","method":"server.ping",'
            '"params":{"value":NaN}}',
        )
        assert non_finite["ok"] is False
        opened = send_requests(sock, [
            {"id": "open", "method": "debug.session.open", "params": {"name": "redact", "fsdb": str(private_fsdb)}}
        ])[0]
        assert opened["ok"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)

    uds_text = (log_root / "logs" / "uds.ndjson").read_text(encoding="utf-8")
    session_text = (log_root / "sessions" / "redact" / "session.ndjson").read_text(encoding="utf-8")
    assert "uds.request.invalid_json" in uds_text
    assert "private-invalid-json" not in uds_text
    assert "private-request-id" not in uds_text
    assert "wave.fsdb" in session_text
    assert str(private_dir) not in session_text
    assert str(tmp_path) not in uds_text


def test_loop_wrapper_fake_lsf_logs_job_and_cleanup(tmp_path, monkeypatch):
    log_root = tmp_path / "logs"
    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(log_root))
    monkeypatch.setenv("XVERIF_LOOP_FAKE_LSF", "1")
    monkeypatch.setenv("FAKE_BSUB_STDOUT_NOISE_BEFORE_READY", "1")
    monkeypatch.setenv(
        "XVERIF_LSF_BKILL",
        shlex.join([sys.executable, "-c", "raise SystemExit(0)"]),
    )
    debug = _make_fake_loop(tmp_path / "fake_xdebug", protocol="xdebug-stdio-loop", api_version="xdebug")
    cov = _make_fake_loop(tmp_path / "fake_xcov", protocol="xcov-stdio-loop", api_version="xcov")
    service = LoopWrapperService(
        mode="lsf",
        xdebug_bin=debug,
        xcov_bin=cov,
        startup_timeout_sec=3.0,
        request_timeout_sec=3.0,
    )
    server, thread, sock = _start_server(tmp_path, service)
    try:
        responses = send_requests(sock, [
            {"id": "open", "method": "debug.session.open", "params": {"name": "lsfcase", "fsdb": "wave.fsdb"}},
            {
                "id": "close",
                "method": "debug.session.close",
                "params": {"session_id": "lsfcase"},
            },
        ], timeout_sec=10.0)
        assert [r["ok"] for r in responses] == [True, True]
    finally:
        server.shutdown()
        thread.join(timeout=5)

    lsf_events = _session_log(log_root, "lsfcase", "lsf")
    phases = [e["phase"] for e in lsf_events]
    assert "launcher.lsf.start" in phases
    assert "bsub.start" in phases
    assert "job_id.detected" in phases
    assert any(e.get("job_id") == "123" for e in lsf_events)
    assert any(e["phase"].startswith("bkill.") for e in lsf_events)
