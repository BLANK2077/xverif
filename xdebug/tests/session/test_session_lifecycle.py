from __future__ import annotations

import json
import os
import signal
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
    path = isolated_home / ".xdebug" / "engine" / "registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _registry_session(isolated_home: Path, session_id: str) -> dict:
    sessions = _registry(isolated_home).get("sessions", [])
    return next(item for item in sessions if item["session_id"] == session_id)


def _kill_all(cli_runner: CliRunner) -> None:
    cli_runner.run(_request("session.kill", target={"session_id": "all"}))


def _write_registry_session(isolated_home: Path, record: dict) -> None:
    path = isolated_home / ".xdebug" / "engine" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sessions": [record]}, indent=2), encoding="utf-8")


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
            f"{session_prefix}_*/logs/transport.ndjson"
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
            f"{directory_prefix}_*/logs/{log_name}.ndjson"
        )
    )
    assert len(matches) == 1, f"expected one {log_name}.ndjson for {session_prefix}, got {matches}"
    return matches[0]


def _single_npi_startup_log(isolated_home: Path, session_prefix: str) -> Path:
    directory_prefix = session_prefix[:16]
    matches = sorted(
        (isolated_home / ".xdebug" / "engine" / "sessions").glob(
            f"{directory_prefix}_*/logs/npi_startup.log"
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
            "daidir": str(uart / "simv.daidir")
        },
        "waveform": {
            "fsdb": str(wave / "out/waves.fsdb")
        },
        "combined": {
            "daidir": str(combined / "out/simv.daidir"),
            "fsdb": str(combined / "out/waves.fsdb"),
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
            )
        )
        assert opened.ok
        assert opened.response["summary"]["mode"] == mode

        listed = cli_runner.run(_request("session.list"))
        records = listed.response["data"]["sessions"]
        assert any(item["session_id"] == name and item["mode"] == mode for item in records)

        doctor = cli_runner.run(
            _request("session.doctor", target={"session_id": name})
        )
        assert doctor.ok
        assert doctor.response["summary"]["healthy"] is True

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
        assert closed.response["summary"]["session_id"] == name
        assert closed.response["summary"]["removed"] is True
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
    assert result.response["error"]["code"] in ("MISSING_FIELD", "INVALID_SESSION_NAME")


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
        assert gc.response["data"]["removed"][0]["session_id"] == name
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
        assert doctor.response["summary"]["status"] == "resource_changed"
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
            )
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
        assert queried.response["data"]["value"]["known"] is True

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
def test_session_uds_direct_query_times_out_without_spawn_fallback(
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
                "limits": {"timeout_ms": 100},
            },
            timeout_sec=5.0,
        )
        elapsed = time.monotonic() - started_at

        assert accepted.wait(timeout=1.0)
        assert not result.timed_out
        assert result.returncode != 0
        assert isinstance(result.response, dict)
        assert result.response["ok"] is False
        assert result.response["error"]["code"] == "SESSION_TRANSPORT_FAILED"
        assert "direct session socket timed out" in result.response["error"]["message"]
        assert result.response["summary"]["transport"] == "uds"
        assert result.response["summary"]["timeout_ms"] == 100
        assert elapsed < 2.0

        events = _engine_transport_events(isolated_home, "hung_uds")
        phases = [event["phase"] for event in events]
        assert "socket.connect.begin" in phases
        assert "socket.connect.ok" in phases
        assert "socket.read.timeout" in phases
        timeout_event = next(event for event in events if event["phase"] == "socket.read.timeout")
        assert timeout_event["session_id"] == "hung_uds"
        assert timeout_event["action"] == "value.at"
        assert timeout_event["context"]["socket_path"] == str(socket_path)
        assert timeout_event["context"]["timeout_ms"] == 100
    finally:
        stop.set()
        thread.join(timeout=2.0)
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
            "limits": {"timeout_ms": 100},
        },
        timeout_sec=5.0,
    )

    assert not result.ok
    assert result.response["error"]["code"] == "SESSION_TRANSPORT_FAILED"
    events = _engine_transport_events(isolated_home, "dead_uds")
    failed = next(event for event in events if event["phase"] == "socket.connect.failed")
    assert failed["session_id"] == "dead_uds"
    assert failed["action"] == "value.at"
    assert failed["context"]["socket_path"] == str(socket_path)
    assert failed["context"]["timeout_ms"] == 100
    assert failed["context"]["errno"] != 0


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
                "limits": {"timeout_ms": 100},
            },
            timeout_sec=5.0,
        )

        assert not result.ok
        assert result.response["error"]["code"] == "SESSION_TRANSPORT_FAILED"
        events = _engine_transport_events(isolated_home, "bad_json")
        phases = [event["phase"] for event in events]
        assert "socket.connect.ok" in phases
        parsed = next(event for event in events if event["phase"] == "socket.response_parse_failed")
        assert parsed["session_id"] == "bad_json"
        assert parsed["action"] == "value.at"
        assert parsed["context"]["socket_path"] == str(socket_path)
        assert parsed["context"]["response_bytes"] > 0
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

    lifecycle = _read_ndjson(_single_engine_log(isolated_home, "crashmark", "lifecycle"))
    snapshot = next(event for event in lifecycle if event["phase"] == "env.snapshot")
    context = snapshot["context"]
    assert context["argv_count"] == 2
    assert context["cwd_path"] == str(repo_root)
    assert context["eda"]["verdi_home_path"] == str(fake_verdi)
    assert context["eda"]["vcs_home_path"] == str(fake_vcs)
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

    lifecycle = _read_ndjson(_single_engine_log(isolated_home, name, "lifecycle"))
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
