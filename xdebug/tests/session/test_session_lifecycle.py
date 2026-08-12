from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from runner import CliRunner


def _request(action: str, *, target=None, args=None):
    request = {"api_version": "xdebug.v1", "action": action}
    if target is not None:
        request["target"] = target
    if args is not None:
        request["args"] = args
    return request


def _wave_value_at_args() -> dict:
    return {
        "signal": "ai_complex_top.sig_a",
        "time": "75ns",
        "clock": "ai_complex_top.clk",
        "value_format": "hex",
    }


def _registry(isolated_home: Path) -> dict:
    sessions_root = isolated_home / ".xdebug" / "engine" / "sessions"
    sessions = []
    for path in sorted(sessions_root.glob("*/state.json")):
        sessions.append(json.loads(path.read_text(encoding="utf-8")))
    return {"version": 4, "sessions": sessions}


def _registry_session(isolated_home: Path, session_id: str) -> dict:
    sessions = _registry(isolated_home).get("sessions", [])
    return next(item for item in sessions if item["session_id"] == session_id)


def _kill_all(cli_runner: CliRunner) -> None:
    cli_runner.run(_request("session.close", target={"session_id": "all"}, args={"mode": "force"}))


def _write_registry_session(isolated_home: Path, record: dict) -> None:
    canonical = {
        "session_id": "",
        "generation": "1" * 64,
        "lifecycle_state": "active",
        "transport": "uds",
        "socket_path": "",
        "file_dir": "",
        "host": "",
        "bind_host": "",
        "port": 0,
        "server_host": "localhost",
        "auth_token": "",
        "ownership_token_hash": "",
        "dbdir_path": "",
        "fsdb_file": "",
        "server_pid": 0,
        "created_at": int(time.time()),
        "last_active": int(time.time()),
        "dbdir_mtime_ns": 0,
        "dbdir_size": 0,
        "dbdir_dev": 0,
        "dbdir_inode": 0,
        "fsdb_mtime_ns": 0,
        "fsdb_size": 0,
        "fsdb_dev": 0,
        "fsdb_inode": 0,
    }
    canonical.update(record)
    for prefix, path_field in (
        ("dbdir", "dbdir_path"),
        ("fsdb", "fsdb_file"),
    ):
        resource_path = canonical[path_field]
        if not resource_path or canonical[f"{prefix}_mtime_ns"] != 0:
            continue
        path_object = Path(resource_path)
        if not path_object.exists():
            continue
        stat_result = path_object.stat()
        canonical[f"{prefix}_mtime_ns"] = stat_result.st_mtime_ns
        canonical[f"{prefix}_size"] = stat_result.st_size
        canonical[f"{prefix}_dev"] = stat_result.st_dev
        canonical[f"{prefix}_inode"] = stat_result.st_ino
    session_id = canonical["session_id"]
    path_hash = 1469598103934665603
    for byte in session_id.encode("utf-8"):
        path_hash ^= byte
        path_hash = (path_hash * 1099511628211) & ((1 << 64) - 1)
    session_dir = (
        isolated_home
        / ".xdebug"
        / "engine"
        / "sessions"
        / f"{session_id[:16]}_{path_hash:016x}"
    )
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "state.json").write_text(
        json.dumps(canonical, indent=2) + "\n",
        encoding="utf-8",
    )
    (session_dir / "generation").write_text(
        canonical["generation"] + "\n",
        encoding="utf-8",
    )


def _direct_engine_directories(isolated_home: Path) -> list[Path]:
    return sorted(
        (isolated_home / ".xdebug" / "engine" / "sessions").glob(
            "direct_*"
        )
    )


def _assert_no_active_direct_resource_artifacts(
    isolated_home: Path,
) -> None:
    registry = _registry(isolated_home)
    assert not [
        item
        for item in registry.get("sessions", [])
        if item["session_id"].startswith("direct_")
    ]
    for directory in _direct_engine_directories(isolated_home):
        for name in ("session.json", "socket", "endpoint.json"):
            assert not (directory / name).exists(), directory / name


def _direct_spawned_pids(isolated_home: Path) -> list[int]:
    pids: list[int] = []
    for directory in _direct_engine_directories(isolated_home):
        for lifecycle in directory.glob("owners/*/logs/lifecycle.ndjson"):
            for event in _read_ndjson(lifecycle):
                if event.get("phase") != "ensure_session.spawned_server":
                    continue
                pid = event.get("context", {}).get("pid")
                if isinstance(pid, int) and pid > 0:
                    pids.append(pid)
    return pids


def _assert_processes_gone(pids: list[int]) -> None:
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def _read_ndjson(path: Path) -> list[dict]:
    assert path.exists(), path
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _engine_transport_events(isolated_home: Path, session_prefix: str) -> list[dict]:
    matches = sorted(
        (isolated_home / ".xdebug" / "engine" / "sessions").glob(
            f"{session_prefix}_*/owners/*/logs/transport.ndjson"
        )
    )
    assert matches, f"missing engine transport log for {session_prefix}"
    rows: list[dict] = []
    for path in matches:
        rows.extend(_read_ndjson(path))
    return rows


def _single_engine_log(isolated_home: Path, session_prefix: str, log_name: str) -> Path:
    directory_prefix = session_prefix[:16]
    matches = sorted(
        (isolated_home / ".xdebug" / "engine" / "sessions").glob(
            f"{directory_prefix}_*/owners/*/logs/{log_name}.ndjson"
        )
    )
    assert len(matches) == 1, f"expected one {log_name}.ndjson for {session_prefix}, got {matches}"
    return matches[0]


def _engine_log_events(
    isolated_home: Path, session_prefix: str, log_name: str
) -> list[dict]:
    directory_prefix = session_prefix[:16]
    matches = sorted(
        (isolated_home / ".xdebug" / "engine" / "sessions").glob(
            f"{directory_prefix}_*/owners/*/logs/{log_name}.ndjson"
        )
    )
    assert matches, f"missing {log_name}.ndjson for {session_prefix}"
    rows: list[dict] = []
    for path in matches:
        rows.extend(_read_ndjson(path))
    return rows


def _single_npi_startup_log(isolated_home: Path, session_prefix: str) -> Path:
    directory_prefix = session_prefix[:16]
    matches = sorted(
        (isolated_home / ".xdebug" / "engine" / "sessions").glob(
            f"{directory_prefix}_*/owners/*/logs/npi_startup.log"
        )
    )
    assert len(matches) == 1, f"expected one npi_startup.log for {session_prefix}, got {matches}"
    return matches[0]


@pytest.fixture
def resource_targets(xverif_fixture):
    uart = xverif_fixture("xdebug.design_uart")
    wave = xverif_fixture("xdebug.ai_complex_wave")
    combined = xverif_fixture("xdebug.active_driver")
    return {
        "design": {
            "daidir": str((uart / "simv.daidir").resolve())
        },
        "waveform": {
            "fsdb": str((wave / "out/waves.fsdb").resolve())
        },
        "combined": {
            "daidir": str((combined / "out/simv.daidir").resolve()),
            "fsdb": str((combined / "out/waves.fsdb").resolve()),
        },
    }


@pytest.mark.session
@pytest.mark.parametrize("mode", ["design", "waveform", "combined"])
def test_session_open_list_doctor_close_for_each_resource_mode(
    mode: str,
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "lifecycle_%s" % mode
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target=resource_targets[mode],
                args={"name": name},
            ),
            env={"XDEBUG_ENGINE_TEST_SECURE_RANDOM_FAIL": "1"},
        )
        assert opened.ok
        assert opened.response["summary"] == {"status": "opened"}
        assert opened.response["session"]["mode"] == mode
        assert opened.response["data"] == {"run_manifest": None}

        listed = cli_runner.run(_request("session.list"))
        assert listed.ok, listed.response
        records = listed.response["data"]["sessions"]
        assert any(item["session_id"] == name and item["mode"] == mode for item in records)

        doctor = cli_runner.run(
            _request("session.doctor", target={"session_id": name})
        )
        assert doctor.ok
        assert doctor.response["summary"]["healthy"] is True
        assert doctor.response["session"]["mode"] == mode
        assert doctor.response["data"]["message"]

        roots = cli_runner.run(
            _request("scope.roots", target={"session_id": name})
        )
        assert roots.ok, roots.response
        assert roots.response["summary"]["source"] == "auto"
        if mode == "combined":
            assert roots.response["summary"]["analysis_complete"] is True
            assert "limitations" not in roots.response["data"]
            assert all(
                root["status"] == "matched"
                for root in roots.response["data"]["roots"]
            )
        elif mode == "design":
            assert roots.response["summary"]["analysis_complete"] is False
            assert (
                "wave roots unavailable: waveform not loaded"
                in roots.response["data"]["limitations"]
            )
            assert all(
                root["status"] == "design_only"
                and root["wave"] is None
                and root["design"]["discovery"]
                in {"npi_top", "verified_wave_root"}
                for root in roots.response["data"]["roots"]
            )
        else:
            assert roots.response["summary"]["analysis_complete"] is False
            assert (
                "design roots unavailable: design not loaded"
                in roots.response["data"]["limitations"]
            )
            assert all(
                root["status"] == "wave_only" and root["design"] is None
                for root in roots.response["data"]["roots"]
            )

        native = _registry_session(isolated_home, name)
        assert native["session_id"] == name
        assert native["server_pid"] > 0
        assert Path(native["socket_path"]).exists()

        closed = cli_runner.run(
            _request("session.close", target={"session_id": name})
        )
        assert closed.ok
        assert closed.response["summary"]["removed"] is True
        assert not Path(native["socket_path"]).exists()
        assert not any(
            item["session_id"] == name
            for item in _registry(isolated_home).get("sessions", [])
        )
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
def test_session_list_is_read_only_and_projects_compact_or_verbose(
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    session_id = "expired_discovery"
    _write_registry_session(
        isolated_home,
        {
            "session_id": session_id,
            "lifecycle_state": "cleanup_failed",
            "socket_path": str(isolated_home / "missing.sock"),
            "fsdb_file": "/private/fixtures/expired.fsdb",
            "server_pid": 999999999,
            "created_at": 1,
            "last_active": 1,
        },
    )
    before = _registry(isolated_home)
    env = {"XDEBUG_SESSION_IDLE_TIMEOUT_SEC": "1"}

    compact = cli_runner.run(_request("session.list"), env=env)
    assert compact.ok, compact.response
    assert compact.response["summary"] == {
        "session_count": 1,
        "expired_count": 1,
        "verbose": False,
    }
    assert compact.response["data"]["sessions"] == [
        {
            "session_id": session_id,
            "mode": "waveform",
            "transport": "uds",
            "lifecycle_state": "cleanup_failed",
            "expired": True,
            "recommended_action": "session.gc",
            "last_active": 1,
        }
    ]
    assert _registry(isolated_home) == before

    verbose = cli_runner.run(
        _request(
            "session.list",
            args={"output": {"verbose": True}},
        ),
        env=env,
    )
    assert verbose.ok, verbose.response
    assert verbose.response["summary"]["verbose"] is True
    record = verbose.response["data"]["sessions"][0]
    assert record["session_id"] == session_id
    assert record["lifecycle_state"] == "cleanup_failed"
    assert record["expired"] is True
    assert record["recommended_action"] == "session.gc"
    assert record["fsdb"] == "/private/fixtures/expired.fsdb"
    assert record["server_pid"] == 999999999
    assert record["socket_path"] == str(isolated_home / "missing.sock")
    assert _registry(isolated_home) == before


@pytest.mark.session
@pytest.mark.waveform
def test_session_close_accepts_target_session_id(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "close_target_only"
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target=resource_targets["waveform"],
                args={"name": name},
            )
        )
        assert opened.ok

        closed = cli_runner.run(_request("session.close", target={"session_id": name}))
        assert closed.ok
        assert closed.response["summary"]["removed"] is True
        assert (
            closed.response["data"]["removed_session"]["session_id"]
            == name
        )
        assert not any(
            item["session_id"] == name
            for item in _registry(isolated_home).get("sessions", [])
        )
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.waveform
@pytest.mark.parametrize(
    "close_kind,close_request",
    [
        ("args_session_id", lambda name: _request("session.close", args={"session_id": name})),
        ("args_id", lambda name: _request("session.close", args={"id": name})),
    ],
)
def test_session_close_rejects_args_session_id_aliases(
    close_kind: str,
    close_request,
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "close_alias_%s" % close_kind
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target=resource_targets["waveform"],
                args={"name": name},
            )
        )
        assert opened.ok

        closed = cli_runner.run(close_request(name))
        assert not closed.ok
        assert closed.response["error"]["code"] == "INVALID_REQUEST"
        assert closed.response["error"]["invalid_arg"] == "target.session_id"
        assert any(
            item["session_id"] == name
            for item in _registry(isolated_home).get("sessions", [])
        )
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
def test_session_close_without_session_id_still_fails(cli_runner: CliRunner) -> None:
    missing = cli_runner.run(_request("session.close", args={}))
    assert not missing.ok
    assert missing.response["error"]["code"] == "INVALID_REQUEST"
    assert missing.response["error"]["message"] == "target.session_id is required"
    assert missing.response["error"]["invalid_arg"] == "target.session_id"


@pytest.mark.session
def test_session_duplicate_stale_and_advisory_contract(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "strict_open"
    target = resource_targets["design"]
    try:
        opened = cli_runner.run(
            _request("session.open", target=target, args={"name": name})
        )
        assert opened.ok
        first = _registry_session(isolated_home, name)

        duplicate = cli_runner.run(
            _request("session.open", target=target, args={"name": name})
        )
        assert not duplicate.ok
        assert duplicate.response["error"]["code"] == "SESSION_ID_EXISTS"
        assert duplicate.response["summary"] == {
            "status": "error",
            "error_code": "SESSION_ID_EXISTS",
        }
        assert duplicate.response["error"]["health_status"] == "healthy"

        old_reuse = cli_runner.run(
            _request(
                "session.open",
                target=target,
                args={"name": name, "reuse": True},
            )
        )
        assert not old_reuse.ok
        assert old_reuse.response["error"]["code"] == "INVALID_REQUEST"

        ensured = cli_runner.run(
            _request("session.ensure", target=target, args={"name": name})
        )
        assert not ensured.ok
        assert ensured.response["error"]["code"] == "UNKNOWN_ACTION"

        same_resource = cli_runner.run(
            _request(
                "session.open",
                target=target,
                args={"name": "strict_open_b"},
            )
        )
        assert same_resource.ok
        advisories = same_resource.response.get("advisories", [])
        assert advisories
        assert advisories[0]["code"] == "RESOURCE_SESSION_ALREADY_ALIVE"
        assert advisories[0]["existing_session_id"] == name

        os.kill(first["server_pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(first["server_pid"], 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        stale = cli_runner.run(
            _request("session.open", target=target, args={"name": name})
        )
        assert not stale.ok
        assert stale.response["error"]["code"] == "SESSION_STALE"
        assert stale.response["summary"] == {
            "status": "error",
            "error_code": "SESSION_STALE",
        }
        assert stale.response["error"]["health_status"] != "error"
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.parametrize("name", ["", "1case", "_case", "case-a", "case.a", "case a", "A" * 65])
def test_session_open_rejects_invalid_name(
    name: str,
    resource_targets: dict,
    cli_runner: CliRunner,
) -> None:
    result = cli_runner.run(
        _request("session.open", target=resource_targets["design"], args={"name": name})
    )
    assert not result.ok
    error = result.response["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["error_layer"] == "schema"
    assert error["invalid_arg"] == "args.name"


@pytest.mark.session
def test_session_gc_removes_crashed_engine(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "crash_gc"
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target=resource_targets["design"],
                args={"name": name},
            )
        )
        assert opened.ok
        native = _registry_session(isolated_home, name)
        os.kill(native["server_pid"], signal.SIGKILL)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(native["server_pid"], 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)

        gc = cli_runner.run(_request("session.gc"))
        assert gc.ok
        assert gc.response["summary"]["removed_count"] == 1
        assert (
            gc.response["data"]["removed"][0]["removed_session"][
                "session_id"
            ]
            == name
        )
        assert gc.response["data"]["removed"][0]["reason"] == "unhealthy"
        assert not Path(native["socket_path"]).exists()
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.waveform
def test_session_doctor_reports_resource_changed_for_stale_fsdb(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "stale_fsdb"
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target=resource_targets["waveform"],
                args={"name": name},
            )
        )
        assert opened.ok
        native = _registry_session(isolated_home, name)
        native["fsdb_size"] = int(native.get("fsdb_size", 0)) + 1
        _write_registry_session(isolated_home, native)

        doctor = cli_runner.run(_request("session.doctor", target={"session_id": name}))
        assert not doctor.ok
        assert doctor.response["error"]["code"] == "RESOURCE_CHANGED"
        assert doctor.response["summary"] == {
            "status": "error",
            "error_code": "RESOURCE_CHANGED",
        }
        assert doctor.response["error"]["health_status"] == "resource_changed"
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.waveform
def test_session_query_rejects_atomically_replaced_fsdb(
    resource_targets: dict,
    cli_runner: CliRunner,
    tmp_path: Path,
) -> None:
    source = Path(resource_targets["waveform"]["fsdb"])
    mutable_fsdb = tmp_path / "waves.fsdb"
    shutil.copy2(source, mutable_fsdb)
    name = "replaced_fsdb"
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target={"fsdb": str(mutable_fsdb)},
                args={"name": name},
            )
        )
        assert opened.ok, opened.response
        baseline = cli_runner.run(
            _request(
                "value.at",
                target={"session_id": name},
                args={"signal": "ai_complex_top.sig_a", "time": "10ns"},
            )
        )
        assert baseline.ok, baseline.response

        original = mutable_fsdb.stat()
        staged = tmp_path / "staged.fsdb"
        shutil.copy2(source, staged)
        os.utime(
            staged,
            ns=(original.st_atime_ns, original.st_mtime_ns),
        )
        os.replace(staged, mutable_fsdb)
        assert mutable_fsdb.stat().st_ino != original.st_ino

        changed = cli_runner.run(
            _request(
                "value.at",
                target={"session_id": name},
                args={"signal": "ai_complex_top.sig_a", "time": "10ns"},
            )
        )
        assert not changed.ok, changed.response
        assert changed.response["error"]["code"] == "RESOURCE_CHANGED"
        assert changed.response["error"]["change_kind"] == "identity_changed"
        listed = cli_runner.run(_request("session.list"))
        assert listed.ok
        assert any(
            item["session_id"] == name
            for item in listed.response["data"]["sessions"]
        )
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.waveform
def test_session_file_transport_open_query_doctor_and_close(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "file_transport_wave"
    try:
        opened = cli_runner.run(
            _request(
                "session.open",
                target=resource_targets["waveform"],
                args={"name": name, "transport": "file"},
            ),
            env={"XDEBUG_ENGINE_TEST_SECURE_RANDOM_FAIL": "1"},
        )
        assert opened.ok
        assert opened.response["session"]["transport"] == "file"
        file_dir = Path(opened.response["session"]["file_dir"])
        assert file_dir.is_dir()
        assert {
            "requests",
            "claims",
            "responses",
            "done",
            "failed",
            "tmp",
            "heartbeat",
        } <= {child.name for child in file_dir.iterdir() if child.is_dir()}

        native = _registry_session(isolated_home, name)
        assert native["transport"] == "file"
        assert Path(native["file_dir"]) == file_dir

        queried = cli_runner.run(
            _request(
                "value.at",
                target={"session_id": name},
                args=_wave_value_at_args(),
            )
        )
        assert queried.ok
        assert queried.response["session"]["transport"] == "file"
        assert queried.response["data"]["entries"][0]["key"] == (
            _wave_value_at_args()["signal"]
        )
        assert (
            queried.response["data"]["samples"][0]["values"][0]["value"]["known"]
            is True
        )

        doctor = cli_runner.run(
            _request("session.doctor", target={"session_id": name})
        )
        assert doctor.ok
        assert doctor.response["session"]["transport"] == "file"
        assert doctor.response["session"]["file_dir"] == str(file_dir)
        assert doctor.response["summary"]["healthy"] is True

        closed = cli_runner.run(
            _request("session.close", target={"session_id": name})
        )
        assert closed.ok
        assert closed.response["summary"]["removed"] is True
        assert not any(
            item["session_id"] == name
            for item in _registry(isolated_home).get("sessions", [])
        )
    finally:
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.waveform
def test_session_tcp_auth_secure_random_failure_fails_closed(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = "tcp_secure_random_failure"
    opened = cli_runner.run(
        _request(
            "session.open",
            target=resource_targets["waveform"],
            args={"name": name, "transport": "tcp"},
        ),
        env={"XDEBUG_ENGINE_TEST_SECURE_RANDOM_FAIL": "1"},
    )

    assert not opened.ok, opened.response
    assert opened.response["error"]["code"] == "SECURE_RANDOM_UNAVAILABLE"
    assert opened.response["summary"] == {
        "status": "error",
        "error_code": "SECURE_RANDOM_UNAVAILABLE",
    }
    assert not any(
        item["session_id"] == name
        for item in _registry(isolated_home).get("sessions", [])
    )


@pytest.mark.session
@pytest.mark.waveform
def test_direct_resource_query_closes_ephemeral_engine(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    result = cli_runner.run(
        _request(
            "value.at",
            target=resource_targets["waveform"],
            args=_wave_value_at_args(),
        ),
        timeout_sec=120,
    )

    assert result.ok, result.stdout_raw + result.stderr_raw
    assert result.response["session"] is None
    _assert_no_active_direct_resource_artifacts(isolated_home)
    spawned = _direct_spawned_pids(isolated_home)
    assert spawned
    _assert_processes_gone(spawned)


@pytest.mark.session
@pytest.mark.waveform
def test_direct_resource_timeout_cleans_process_and_registry(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    started_at = time.monotonic()
    result = cli_runner.run(
        {
            **_request(
                "value.at",
                target=resource_targets["waveform"],
                args=_wave_value_at_args(),
            ),
            "limits": {"timeout_ms": 10_000},
        },
        env={"XDEBUG_ENGINE_TEST_DIRECT_RESOURCE_PAUSE_MS": "60000"},
        timeout_sec=20,
    )
    elapsed = time.monotonic() - started_at

    assert not result.timed_out
    assert result.returncode != 0
    assert result.response["ok"] is False
    assert result.response["error"]["code"] == "ENGINE_TIMEOUT"
    assert result.response["error"]["timeout_ms"] == 10_000
    assert result.response["summary"] == {
        "status": "error",
        "error_code": "ENGINE_TIMEOUT",
    }
    assert result.response["data"] is None
    assert elapsed < 18

    phases = []
    for directory in _direct_engine_directories(isolated_home):
        for lifecycle in directory.glob("owners/*/logs/lifecycle.ndjson"):
            phases.extend(
                event["phase"]
                for event in _read_ndjson(lifecycle)
            )
    assert "direct_resource.open.end" in phases
    assert "direct_resource.test_pause.begin" in phases
    assert "direct_resource.close.end" in phases
    _assert_no_active_direct_resource_artifacts(isolated_home)
    spawned = _direct_spawned_pids(isolated_home)
    assert spawned
    _assert_processes_gone(spawned)


@pytest.mark.session
def test_invalid_session_state_is_isolated_for_list_and_fails_targeted_lookup(
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    session_id = "invalid_state"
    path_hash = 1469598103934665603
    for byte in session_id.encode("utf-8"):
        path_hash ^= byte
        path_hash = (path_hash * 1099511628211) & ((1 << 64) - 1)
    directory = (
        isolated_home / ".xdebug" / "engine" / "sessions" /
        f"{session_id[:16]}_{path_hash:016x}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text("{not-json\n", encoding="utf-8")

    listed = cli_runner.run(_request("session.list"), timeout_sec=5)
    assert listed.ok
    assert listed.response["data"]["sessions"] == []

    lookup = cli_runner.run(
        _request(
            "value.at",
            target={"session_id": session_id},
            args=_wave_value_at_args(),
        ),
        timeout_sec=5,
    )
    assert not lookup.ok
    assert lookup.response["error"]["code"] == "REGISTRY_INVALID"


@pytest.mark.session
@pytest.mark.waveform
def test_session_uds_query_timeout_uses_single_engine_invocation(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "hung-engine.sock"
    ready = threading.Event()
    accepted = threading.Event()
    stop = threading.Event()
    server_error: list[BaseException] = []

    def serve_hung_socket() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                server.settimeout(5.0)
                ready.set()
                conn, _ = server.accept()
                with conn:
                    accepted.set()
                    conn.settimeout(1.0)
                    try:
                        conn.recv(65536)
                    except socket.timeout:
                        pass
                    stop.wait(timeout=2.0)
        except BaseException as exc:
            server_error.append(exc)
            ready.set()

    thread = threading.Thread(target=serve_hung_socket, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    assert not server_error

    _write_registry_session(
        isolated_home,
        {
            "session_id": "hung_uds",
            "transport": "uds",
            "fsdb_file": resource_targets["waveform"]["fsdb"],
            "socket_path": str(socket_path),
            "server_pid": os.getpid(),
        },
    )

    try:
        started_at = time.monotonic()
        result = cli_runner.run(
            {
                **_request(
                    "value.at",
                    target={"session_id": "hung_uds"},
                    args=_wave_value_at_args(),
                ),
                "limits": {"timeout_ms": 1000},
            },
            timeout_sec=5.0,
        )
        elapsed = time.monotonic() - started_at

        assert accepted.wait(timeout=1.0)
        assert not result.timed_out
        assert result.returncode != 0
        assert isinstance(result.response, dict)
        assert result.response["ok"] is False
        assert result.response["error"]["code"] == "ENGINE_TIMEOUT"
        assert result.response["error"]["timeout_ms"] == 1000
        assert result.response["error"]["cancel_state"] == "confirmed"
        assert result.response["error"]["session_state"] == (
            "terminated_on_timeout"
        )
        assert result.response["error"]["cleanup_succeeded"] is True
        assert result.response["error"]["termination_confirmed"] is True
        assert result.response["summary"] == {
            "status": "error",
            "error_code": "ENGINE_TIMEOUT",
        }
        assert result.response["data"] is None
        assert elapsed < 2.0

        events = _engine_transport_events(isolated_home, "hung_uds")
        phases = [event["phase"] for event in events]
        exchange_failures = [
            event
            for event in events
            if event["phase"] == "send_request.exchange_failed"
        ]
        assert len(exchange_failures) == 1
        assert phases.count("send_request.connect_failed") == 0
        timeout_event = exchange_failures[0]
        assert timeout_event["session_id"] == "hung_uds"
        assert timeout_event["action"] == "value.at"
        assert timeout_event["context"]["socket_path"].startswith("<path:sha256:")
        assert str(socket_path) not in json.dumps(timeout_event)
        assert 0 < timeout_event["context"]["timeout_ms"] <= 1000
        retained = _registry_session(isolated_home, "hung_uds")
        assert retained["lifecycle_state"] == "terminated_on_timeout"
    finally:
        stop.set()
        thread.join(timeout=2.0)
        _kill_all(cli_runner)


@pytest.mark.session
@pytest.mark.waveform
def test_session_file_query_timeout_retains_terminated_tombstone(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    session_id = "hung_file"
    file_dir = tmp_path / "hung-file-exchange"
    _write_registry_session(
        isolated_home,
        {
            "session_id": session_id,
            "transport": "file",
            "fsdb_file": resource_targets["waveform"]["fsdb"],
            "file_dir": str(file_dir),
            "server_pid": os.getpid(),
        },
    )

    try:
        result = cli_runner.run(
            {
                **_request(
                    "value.at",
                    target={"session_id": session_id},
                    args=_wave_value_at_args(),
                ),
                "limits": {"timeout_ms": 100},
            },
            timeout_sec=5.0,
        )

        assert not result.timed_out
        assert result.returncode != 0
        assert result.response["error"]["code"] == "ENGINE_TIMEOUT"
        assert result.response["error"]["cancel_state"] == "confirmed"
        assert result.response["error"]["session_state"] == (
            "terminated_on_timeout"
        )
        assert result.response["error"]["cleanup_succeeded"] is True
        assert result.response["error"]["termination_confirmed"] is True
        retained = _registry_session(isolated_home, session_id)
        assert retained["lifecycle_state"] == "terminated_on_timeout"
    finally:
        _kill_all(cli_runner)


def test_session_uds_connect_failure_is_logged(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "missing-engine.sock"
    _write_registry_session(
        isolated_home,
        {
            "session_id": "dead_uds",
            "transport": "uds",
            "fsdb_file": resource_targets["waveform"]["fsdb"],
            "socket_path": str(socket_path),
            "server_pid": os.getpid(),
        },
    )

    result = cli_runner.run(
        {
            **_request(
                "value.at",
                target={"session_id": "dead_uds"},
                args=_wave_value_at_args(),
            ),
            "limits": {"timeout_ms": 2000},
        },
        timeout_sec=5.0,
    )

    assert not result.ok
    assert result.response["error"]["code"] == "SESSION_UNHEALTHY"
    events = _engine_transport_events(isolated_home, "dead_uds")
    failures = [
        event
        for event in events
        if event["phase"] == "send_request.connect_failed"
    ]
    assert len(failures) == 1
    assert not any(
        event["phase"] == "send_request.exchange_failed"
        for event in events
    )
    failed = failures[0]
    assert failed["session_id"] == "dead_uds"
    assert failed["action"] == "value.at"
    assert failed["context"]["socket_path"].startswith("<path:sha256:")
    assert str(socket_path) not in json.dumps(failed)
    assert 0 < failed["context"]["timeout_ms"] <= 2000


def test_session_uds_invalid_json_response_is_logged(
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "bad-json-engine.sock"
    ready = threading.Event()
    server_error: list[BaseException] = []

    def serve_invalid_json() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                server.settimeout(5.0)
                ready.set()
                conn, _ = server.accept()
                with conn:
                    conn.recv(65536)
                    conn.sendall(b"{not-json}\n")
        except BaseException as exc:
            server_error.append(exc)
            ready.set()

    thread = threading.Thread(target=serve_invalid_json, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    assert not server_error

    _write_registry_session(
        isolated_home,
        {
            "session_id": "bad_json",
            "transport": "uds",
            "fsdb_file": resource_targets["waveform"]["fsdb"],
            "socket_path": str(socket_path),
            "server_pid": os.getpid(),
        },
    )

    try:
        result = cli_runner.run(
            {
                **_request(
                    "value.at",
                    target={"session_id": "bad_json"},
                    args=_wave_value_at_args(),
                ),
                "limits": {"timeout_ms": 2000},
            },
            timeout_sec=5.0,
        )

        assert not result.ok
        assert result.response["error"]["code"] == "SESSION_UNHEALTHY"
        events = _engine_transport_events(isolated_home, "bad_json")
        phases = [event["phase"] for event in events]
        exchange_failures = [
            event
            for event in events
            if event["phase"] == "send_request.exchange_failed"
        ]
        assert len(exchange_failures) == 1
        assert phases.count("send_request.connect_failed") == 0
        parsed = exchange_failures[0]
        assert parsed["session_id"] == "bad_json"
        assert parsed["action"] == "value.at"
        assert parsed["context"]["socket_path"].startswith("<path:sha256:")
        assert str(socket_path) not in json.dumps(parsed)
        assert 0 < parsed["context"]["timeout_ms"] <= 2000
    finally:
        thread.join(timeout=2.0)
        _kill_all(cli_runner)


def test_engine_crash_marker_is_written_by_signal_handler(
    repo_root: Path,
    xdebug_root: Path,
    isolated_home: Path,
) -> None:
    engine = xdebug_root / "libexec" / "xdebug-engine"
    fake_eda = isolated_home / "fake-eda"
    fake_verdi = fake_eda / "verdi"
    fake_vcs = fake_eda / "vcs"
    fake_library_path = f"{fake_eda / 'lib'}:{isolated_home / 'project-lib'}"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(isolated_home),
            "XVERIF_HOME": str(repo_root),
            "XDEBUG_ENGINE_TEST_CRASH_MARKER": "1",
            "XDEBUG_ENGINE_TEST_CRASH_ACTION": "value.at",
            "XDEBUG_ENGINE_TEST_CRASH_REQUEST_ID": "crash-req-1",
            "VERDI_HOME": str(fake_verdi),
            "VCS_HOME": str(fake_vcs),
            "LSB_JOBID": "987654",
            "LSB_QUEUE": "normal",
            "LD_LIBRARY_PATH": fake_library_path,
            "SNPSLMD_LICENSE_FILE": "27000@license.example",
            "LM_LICENSE_FILE": "27001@license.example",
        }
    )

    proc = subprocess.run(
        [str(engine), "--server", "crashmark"],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5.0,
    )

    assert proc.returncode == 128 + signal.SIGABRT
    marker = _single_engine_log(isolated_home, "crashmark", "crash_marker")
    text = marker.read_text(encoding="utf-8")
    assert "signal_exit" in text
    assert "session_id=crashmark" in text
    assert "current_action=value.at" in text
    assert "request_id=crash-req-1" in text
    assert f"sig={signal.SIGABRT}" in text

    lifecycle = _engine_log_events(isolated_home, "crashmark", "lifecycle")
    snapshot = next(event for event in lifecycle if event["phase"] == "env.snapshot")
    context = snapshot["context"]
    assert context["argv_count"] == 2
    assert context["cwd_path"].startswith("<path:sha256:")
    assert context["eda"]["verdi_home_path"].startswith("<path:sha256:")
    assert context["eda"]["vcs_home_path"].startswith("<path:sha256:")
    assert str(repo_root) not in json.dumps(context)
    assert str(fake_verdi) not in json.dumps(context)
    assert str(fake_vcs) not in json.dumps(context)
    assert context["lsf"] == {"job_id": "987654", "queue": "normal"}
    assert context["paths"]["ld_library_path_hash"]
    assert str(fake_eda / "lib") not in json.dumps(context)
    assert context["license_env"] == {
        "snpslmd_license_file_present": True,
        "lm_license_file_present": True,
    }
    assert "27000@license.example" not in json.dumps(context)
    assert "27001@license.example" not in json.dumps(context)


@pytest.mark.session
@pytest.mark.parametrize(
    ("phase", "hook", "target_key", "error_code", "marker"),
    [
        ("npi_init", "XDEBUG_ENGINE_TEST_NPI_INIT_FAIL", "waveform",
         "NPI_INIT_FAILED", "XDEBUG_TEST_NPI_INIT_FAIL"),
        ("npi_load_design", "XDEBUG_ENGINE_TEST_NPI_LOAD_DESIGN_FAIL", "design",
         "NPI_LOAD_DESIGN_FAILED", "XDEBUG_TEST_NPI_LOAD_DESIGN_FAIL"),
        ("npi_fsdb_open", "XDEBUG_ENGINE_TEST_NPI_FSDB_OPEN_FAIL", "waveform",
         "NPI_FSDB_OPEN_FAILED", "XDEBUG_TEST_NPI_FSDB_OPEN_FAIL"),
    ],
)
def test_npi_startup_failure_is_classified_and_captured(
    phase: str,
    hook: str,
    target_key: str,
    error_code: str,
    marker: str,
    resource_targets: dict,
    cli_runner: CliRunner,
    isolated_home: Path,
) -> None:
    name = f"forced_{phase}"
    opened = cli_runner.run(
        _request("session.open", target=resource_targets[target_key], args={"name": name}),
        env={hook: "1"},
        timeout_sec=120,
    )

    assert not opened.ok, opened.stdout_raw + opened.stderr_raw
    error = opened.response["error"]
    assert error["code"] == error_code
    assert error["failure_kind"] == "npi_startup_failed"
    assert error["failure_phase"] == phase
    assert error["startup_reason"] == "child_exited"
    assert error["diagnostic_log"] == "engine_npi_startup"

    startup_log = _single_npi_startup_log(isolated_home, name)
    assert startup_log.stat().st_mode & 0o777 == 0o600
    assert marker in startup_log.read_text(encoding="utf-8", errors="replace")

    lifecycle = _engine_log_events(isolated_home, name, "lifecycle")
    failure = next(event for event in lifecycle if event["phase"] == f"{phase}.failed")
    assert failure["context"]["failure_phase"] == phase
    assert failure["context"]["diagnostic_log"] == "engine_npi_startup"
    assert failure["context"]["diagnostic_log_bytes"] > 0


@pytest.mark.session
def test_npi_init_failure_without_license_env_returns_advisory_and_xout_diagnostics(
    resource_targets: dict,
    cli_runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SNPSLMD_LICENSE_FILE", raising=False)
    monkeypatch.delenv("LM_LICENSE_FILE", raising=False)
    opened = cli_runner.run(
        _request(
            "session.open",
            target=resource_targets["waveform"],
            args={"name": "missing_license_env"},
        ),
        output_format="xout",
        timeout_sec=120,
    )

    assert not opened.ok, opened.stdout_raw + opened.stderr_raw
    assert "code" in opened.stdout_raw and "NPI_INIT_FAILED" in opened.stdout_raw
    assert "failure_phase" in opened.stdout_raw and "npi_init" in opened.stdout_raw
    assert "diagnostic_log" in opened.stdout_raw and "engine_npi_startup" in opened.stdout_raw
    assert "LICENSE_ENV_NOT_EXPLICIT" in opened.stdout_raw
