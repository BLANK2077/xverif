from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from runner import CliRunner


pytestmark = pytest.mark.contract


_FAKE_ENGINE = """#!/usr/bin/env python3
import json
import os
import sys

request = json.load(sys.stdin)
capture_path = os.environ["XDEBUG_FAKE_ENGINE_CAPTURE"]
with open(capture_path, "a", encoding="utf-8") as capture:
    capture.write(json.dumps(request, sort_keys=True) + "\\n")

mode = os.environ.get("XDEBUG_FAKE_ENGINE_MODE", "healthy")
kill_mode = os.environ.get("XDEBUG_FAKE_ENGINE_KILL_MODE", "cleaned")
if mode == "open_invalid_json" and request["action"] == "session.open":
    sys.stdout.write("{invalid-json")
    raise SystemExit(0)
elif mode == "open_echo_token_error" and request["action"] == "session.open":
    token = request["args"]["ownership_token"]
    response = {
        "api_version": "xdebug.internal.v1",
        "ok": False,
        "action": request["action"],
        "summary": {
            "status": "error",
            "error_code": "OPEN_REJECTED",
        },
        "data": None,
        "error": {
            "code": "OPEN_REJECTED",
            "message": "rejected internal cleanup token " + token,
            "recoverable": False,
            "error_layer": "internal",
        },
    }
elif mode == "open_schema_invalid" and request["action"] == "session.open":
    response = {
        "api_version": "xdebug.internal.v1",
        "ok": False,
        "action": request["action"],
        "summary": {
            "status": "error",
            "error_code": "OPEN_REJECTED",
        },
        "data": None,
        "error": {
            "code": "OPEN_REJECTED",
            "message": "canonical backend rejection",
            "recoverable": False,
            "error_layer": "internal",
            "private_marker": True,
        },
    }
elif mode.startswith("open_") and request["action"] == "session.open":
    session = {
        "session_id": request["args"]["name"],
        "transport": "uds",
                "socket_path": "fixtures/fake-session.sock",
        "server_host": "fake-host",
    }
    if mode == "open_missing_transport":
        session.pop("transport")
    elif mode == "open_invalid_transport":
        session["transport"] = "invalid"
    elif mode == "open_noncanonical":
        session.pop("server_host")
    response = {
        "api_version": "xdebug.internal.v1",
        "ok": True,
        "action": request["action"],
        "session": session,
        "summary": {"status": "healthy"},
        "data": {"session": session},
        "error": None,
    }
elif mode.startswith("open_") and request["action"] == "session.kill":
    if kill_mode == "cleaned":
        response = {
            "api_version": "xdebug.internal.v1",
            "ok": True,
            "action": request["action"],
            "summary": {"killed": True},
            "data": {},
            "error": None,
        }
    else:
        code = {
            "not_found": "SESSION_NOT_FOUND",
            "token_mismatch": "SESSION_OWNERSHIP_TOKEN_MISMATCH",
            "cleanup_failed": "SESSION_CLEANUP_FAILED",
        }[kill_mode]
        response = {
            "api_version": "xdebug.internal.v1",
            "ok": False,
            "action": request["action"],
            "summary": {"status": "error", "error_code": code},
            "data": None,
            "error": {
                "code": code,
                "message": "conditional cleanup result",
                "recoverable": kill_mode == "cleanup_failed",
                "error_layer": "session_manager",
            },
        }
elif mode == "healthy":
    response = {
        "api_version": "xdebug.internal.v1",
        "ok": True,
        "action": request["action"],
        "summary": {"healthy": True, "status": "healthy"},
        "data": {},
        "error": None,
    }
elif mode == "unhealthy":
    response = {
        "api_version": "xdebug.internal.v1",
        "ok": False,
        "action": request["action"],
        "summary": {
            "status": "error",
            "error_code": "SESSION_UNHEALTHY",
            "health_status": "summary-must-not-win",
        },
        "data": None,
        "error": {
            "code": "SESSION_UNHEALTHY",
            "message": "fake engine is unreachable",
            "recoverable": True,
            "error_layer": "transport",
            "health_status": "transport_failed",
        },
    }
else:
    raise SystemExit("unknown XDEBUG_FAKE_ENGINE_MODE: " + mode)

json.dump(response, sys.stdout)
sys.stdout.write("\\n")
"""


def _write_registry(
    home: Path,
    *,
    session_id: str,
    daidir: str = "",
    fsdb: str = "",
    last_active: int | None = None,
    ownership_token_hash: str = "",
) -> None:
    now = int(time.time())
    record = {
        "session_id": session_id,
        "transport": "uds",
        "socket_path": str(home / f"{session_id}.sock"),
        "file_dir": "",
        "host": "",
        "bind_host": "",
        "port": 0,
        "server_host": "localhost",
        "auth_token": "",
        "ownership_token_hash": ownership_token_hash,
        "generation": "01" * 32,
        "lifecycle_state": "active",
        "dbdir_path": daidir,
        "fsdb_file": fsdb,
        "server_pid": os.getpid(),
        "created_at": now - 10,
        "last_active": now if last_active is None else last_active,
        "dbdir_mtime": 0,
        "dbdir_size": 0,
        "dbdir_dev": 0,
        "dbdir_inode": 0,
        "fsdb_mtime": 0,
        "fsdb_size": 0,
        "fsdb_dev": 0,
        "fsdb_inode": 0,
    }
    path = home / ".xdebug" / "engine" / "registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"version": 2, "sessions": [record]}, indent=2) + "\n",
        encoding="utf-8",
    )


def _isolated_frontend(
    tmp_path: Path,
    *,
    repo_root: Path,
    xdebug_root: Path,
    mode: str,
    kill_mode: str = "cleaned",
) -> tuple[CliRunner, Path, Path]:
    frontend_dir = tmp_path / "frontend"
    libexec_dir = frontend_dir / "libexec"
    libexec_dir.mkdir(parents=True)

    frontend = frontend_dir / "xdebug"
    shutil.copy2(xdebug_root / "xdebug", frontend)

    engine = libexec_dir / "xdebug-engine"
    engine.write_text(_FAKE_ENGINE, encoding="utf-8")
    engine.chmod(0o700)

    home = tmp_path / "home"
    home.mkdir()
    capture_path = tmp_path / "engine-requests.ndjson"
    runner = CliRunner(
        frontend,
        cwd=repo_root,
        base_env={
            "HOME": str(home),
            "XVERIF_HOME": str(repo_root),
            "XDEBUG_FAKE_ENGINE_CAPTURE": str(capture_path),
            "XDEBUG_FAKE_ENGINE_MODE": mode,
            "XDEBUG_FAKE_ENGINE_KILL_MODE": kill_mode,
        },
    )
    return runner, home, capture_path


def _captured_requests(path: Path) -> list[dict]:
    assert path.is_file(), path
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _assert_secret_absent(
    *,
    response: dict,
    home: Path,
    secret: str,
) -> None:
    assert secret not in json.dumps(response, sort_keys=True)
    for log_path in (home / ".xdebug").rglob("*.ndjson"):
        assert secret not in log_path.read_text(encoding="utf-8")
    for sidecar_path in (home / ".xdebug").rglob("*.json"):
        assert secret not in sidecar_path.read_text(
            encoding="utf-8", errors="replace"
        )


@pytest.mark.parametrize(
    ("engine_mode", "expected_code", "expected_health_status"),
    [
        ("healthy", "SESSION_ID_EXISTS", "healthy"),
        ("unhealthy", "SESSION_STALE", "transport_failed"),
    ],
)
def test_duplicate_open_uses_canonical_doctor_request_and_strict_health_error(
    engine_mode: str,
    expected_code: str,
    expected_health_status: str,
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode=engine_mode,
    )
    daidir = tmp_path / "simv.daidir"
    daidir.mkdir()
    _write_registry(
        home,
        session_id="duplicate_case",
        daidir=str(daidir),
    )

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "request_id": "duplicate-open-request",
            "action": "session.open",
            "target": {"daidir": str(daidir)},
            "args": {"name": "duplicate_case"},
            "limits": {},
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    assert result.response["error"]["code"] == expected_code
    assert (
        result.response["error"]["health_status"]
        == expected_health_status
    )
    if engine_mode == "unhealthy":
        assert (
            result.response["error"]["backend_error_code"]
            == "SESSION_UNHEALTHY"
        )
        assert (
            result.response["error"]["health_status"]
            != "summary-must-not-win"
        )

    requests = _captured_requests(capture_path)
    assert len(requests) == 1
    doctor = requests[0]
    assert doctor == {
        "api_version": "xdebug.internal.v1",
        "action": "session.doctor",
        "observability": {
            "request_id": "duplicate-open-request",
        },
        "routing": {
            "session_id": "duplicate_case",
        },
        "target": {
            "session_id": "duplicate_case",
        },
        "args": {},
    }
    assert "name" not in doctor["args"]
    assert "limits" not in doctor


def test_expired_session_cleanup_does_not_inherit_query_args_or_limits(
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="healthy",
    )
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()
    _write_registry(
        home,
        session_id="expired_case",
        fsdb=str(fsdb),
        last_active=int(time.time()) - 60,
    )

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "request_id": "expired-query-request",
            "action": "value.at",
            "target": {"session_id": "expired_case"},
            "args": {
                "signal": "top.clk",
                "time": "10ns",
            },
            "limits": {
                "timeout_ms": 750,
            },
        },
        env={"XDEBUG_SESSION_IDLE_TIMEOUT_SEC": "1"},
        timeout_sec=5,
    )

    assert not result.ok, result.response
    assert result.response["error"]["code"] == "SESSION_EXPIRED"
    assert result.response["error"]["cleanup_succeeded"] is True

    requests = _captured_requests(capture_path)
    assert len(requests) == 1
    kill = requests[0]
    assert kill == {
        "api_version": "xdebug.internal.v1",
        "action": "session.kill",
        "observability": {
            "request_id": "expired-query-request",
        },
        "routing": {
            "session_id": "expired_case",
        },
        "target": {
            "session_id": "expired_case",
        },
        "args": {},
    }
    assert "signal" not in kill["args"]
    assert "time" not in kill["args"]
    assert "limits" not in kill


def test_conditional_kill_matches_private_open_record_before_forwarding(
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="healthy",
    )
    token = "ab" * 32
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()
    _write_registry(
        home,
        session_id="conditional_case",
        fsdb=str(fsdb),
        ownership_token_hash=token_hash,
    )

    mismatch = runner.run(
        {
            "api_version": "xdebug.v1",
            "request_id": "conditional-mismatch",
            "action": "session.kill",
            "target": {"session_id": "conditional_case"},
            "args": {"ownership_token": "cd" * 32},
        },
        timeout_sec=5,
    )

    assert not mismatch.ok, mismatch.response
    assert (
        mismatch.response["error"]["code"]
        == "SESSION_OWNERSHIP_TOKEN_MISMATCH"
    )
    assert not capture_path.exists()

    matched = runner.run(
        {
            "api_version": "xdebug.v1",
            "request_id": "conditional-match",
            "action": "session.kill",
            "target": {"session_id": "conditional_case"},
            "args": {"ownership_token": token},
        },
        timeout_sec=5,
    )

    assert matched.ok, matched.response
    requests = _captured_requests(capture_path)
    assert requests == [
        {
            "api_version": "xdebug.internal.v1",
            "action": "session.kill",
            "observability": {
                "request_id": "conditional-match",
            },
            "routing": {
                "session_id": "conditional_case",
            },
            "target": {
                "session_id": "conditional_case",
            },
            "args": {
                "ownership_token": token,
            },
        }
    ]
    assert token not in json.dumps(matched.response, sort_keys=True)
    registry_text = (
        home / ".xdebug" / "engine" / "registry.json"
    ).read_text(encoding="utf-8")
    assert token not in registry_text
    assert token_hash in registry_text
    for log_path in (home / ".xdebug").rglob("*.ndjson"):
        assert token not in log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("location", ["top_level", "args"])
def test_invalid_ownership_token_is_never_echoed_or_logged(
    location: str,
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="healthy",
    )
    secret = "invalid-managed-token-must-not-be-echoed"
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()
    request = {
        "api_version": "xdebug.v1",
        "request_id": f"invalid-token-{location}",
        "action": "session.open",
        "target": {"fsdb": str(fsdb)},
        "args": {"name": "invalid_token_case"},
    }
    if location == "top_level":
        request["ownership_token"] = secret
    else:
        request["args"]["ownership_token"] = secret

    result = runner.run(request, timeout_sec=5)

    assert not result.ok, result.response
    error = result.response["error"]
    expected_path = (
        "ownership_token"
        if location == "top_level"
        else "args.ownership_token"
    )
    assert error["invalid_arg"] == expected_path
    assert error["received_type"] == "string"
    assert error["received_redacted"] is True
    assert "received" not in error
    assert not _contains_key(
        error.get("correct_example"), "ownership_token"
    )
    assert not capture_path.exists()
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=secret,
    )


@pytest.mark.parametrize(
    "open_mode",
    [
        "open_missing_transport",
        "open_invalid_transport",
        "open_noncanonical",
        "open_invalid_json",
    ],
)
def test_managed_open_backend_anomaly_uses_conditional_compensation(
    open_mode: str,
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode=open_mode,
    )
    token = "ab" * 32
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "request_id": f"compensate-{open_mode}",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {
                "name": "compensated_open",
                "ownership_token": token,
            },
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    assert (
        result.response["error"]["code"]
        == "INTERNAL_ENGINE_RESPONSE_INVALID"
    )
    assert result.response["error"]["cleanup_succeeded"] is True
    assert result.response["error"]["compensation_status"] == "cleaned"
    requests = _captured_requests(capture_path)
    assert [request["action"] for request in requests] == [
        "session.open",
        "session.kill",
    ]
    assert requests[1]["routing"] == {
        "session_id": "compensated_open"
    }
    assert requests[1]["args"] == {
        "ownership_token": token
    }
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=token,
    )


@pytest.mark.parametrize(
    ("kill_mode", "expected_status", "cleanup_succeeded"),
    [
        ("cleaned", "cleaned", True),
        ("not_found", "not_created", True),
        ("token_mismatch", "token_mismatch", False),
        ("cleanup_failed", "cleanup_failed", False),
    ],
)
def test_managed_open_compensation_status_is_explicit(
    kill_mode: str,
    expected_status: str,
    cleanup_succeeded: bool,
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="open_missing_transport",
        kill_mode=kill_mode,
    )
    token = "cd" * 32
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {
                "name": "compensation_status",
                "ownership_token": token,
            },
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    error = result.response["error"]
    assert error["compensation_status"] == expected_status
    assert error["cleanup_succeeded"] is cleanup_succeeded
    assert len(_captured_requests(capture_path)) == 2
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=token,
    )


def test_cli_open_anomaly_uses_frontend_generated_conditional_token(
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="open_missing_transport",
    )
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "unbound_open"},
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    error = result.response["error"]
    assert error["compensation_status"] == "cleaned"
    assert error["cleanup_succeeded"] is True
    requests = _captured_requests(capture_path)
    assert [request["action"] for request in requests] == [
        "session.open",
        "session.kill",
    ]
    generated_token = requests[0]["args"]["ownership_token"]
    assert len(generated_token) == 64
    assert all(
        character in "0123456789abcdef"
        for character in generated_token
    )
    assert requests[1]["args"] == {
        "ownership_token": generated_token
    }
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=generated_token,
    )


def test_cli_open_terminal_boundary_redacts_generated_token_plaintext(
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="open_echo_token_error",
    )
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "terminal_redaction"},
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    requests = _captured_requests(capture_path)
    assert [request["action"] for request in requests] == [
        "session.open",
    ]
    generated_token = requests[0]["args"]["ownership_token"]
    assert (
        result.response["error"]["message"]
        == "rejected internal cleanup token "
        "<redacted:sensitive-value>"
    )
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=generated_token,
    )


def test_open_error_response_schema_failure_is_conditionally_compensated(
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="open_schema_invalid",
    )
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {"name": "invalid_error_contract"},
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    assert (
        result.response["error"]["code"]
        == "INTERNAL_RESPONSE_SCHEMA_VIOLATION"
    )
    assert result.response["error"]["compensation_status"] == "cleaned"
    requests = _captured_requests(capture_path)
    assert [request["action"] for request in requests] == [
        "session.open",
        "session.kill",
    ]
    generated_token = requests[0]["args"]["ownership_token"]
    assert requests[1]["args"] == {
        "ownership_token": generated_token
    }
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=generated_token,
    )


def test_manifest_publish_failure_is_conditionally_compensated(
    repo_root: Path,
    xdebug_root: Path,
    tmp_path: Path,
) -> None:
    runner, home, capture_path = _isolated_frontend(
        tmp_path,
        repo_root=repo_root,
        xdebug_root=xdebug_root,
        mode="open_manifest_failure",
    )
    xdebug_home = home / ".xdebug"
    xdebug_home.mkdir()
    (xdebug_home / "sessions").write_text(
        "block public session directory creation\n",
        encoding="utf-8",
    )
    token = "ef" * 32
    fsdb = tmp_path / "waves.fsdb"
    fsdb.touch()

    result = runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(fsdb)},
            "args": {
                "name": "manifest_failure",
                "ownership_token": token,
            },
        },
        timeout_sec=5,
    )

    assert not result.ok, result.response
    error = result.response["error"]
    assert error["code"] == "SESSION_MANIFEST_WRITE_FAILED"
    assert error["compensation_status"] == "cleaned"
    assert error["cleanup_succeeded"] is True
    requests = _captured_requests(capture_path)
    assert [request["action"] for request in requests] == [
        "session.open",
        "session.kill",
    ]
    assert requests[1]["args"] == {
        "ownership_token": token
    }
    _assert_secret_absent(
        response=result.response,
        home=home,
        secret=token,
    )
