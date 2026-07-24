from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from runner import CliRunner, NormalizeOptions, normalize_response


REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_SRC = REPO_ROOT / "xverif_mcp" / "src"
XDEBUG_ROOT = REPO_ROOT / "xdebug"
sys.path = [
    path
    for path in sys.path
    if Path(path or os.getcwd()).resolve() != XDEBUG_ROOT
]
if str(MCP_SRC) not in sys.path:
    sys.path.insert(0, str(MCP_SRC))

sys.modules.pop("mcp", None)
pytest.importorskip("mcp")


_PORTALS: dict[int, tuple[Any, Any]] = {}


def _portal(server):
    key = id(server)
    existing = _PORTALS.get(key)
    if existing is not None:
        return existing[1]
    manager = anyio.from_thread.start_blocking_portal()
    portal = manager.__enter__()
    _PORTALS[key] = (manager, portal)
    return portal


def _close_loaded_server() -> None:
    server = sys.modules.get("xverif_mcp.server")
    if server is None:
        return
    for adapter_name in ("debug", "cov"):
        adapter = getattr(server, adapter_name, None)
        sessions = getattr(adapter, "_sessions", None)
        if sessions is not None:
            sessions.close_all()
    entry = _PORTALS.pop(id(server), None)
    if entry is not None:
        entry[0].__exit__(None, None, None)


def _load_server(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    *,
    backend: str,
    extra_env: dict[str, str] | None = None,
):
    _close_loaded_server()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("XVERIF_HOME", str(REPO_ROOT))
    monkeypatch.setenv("XVERIF_MCP_BACKEND", backend)
    monkeypatch.setenv("XVERIF_MCP_STARTUP_TIMEOUT_SEC", "30")
    monkeypatch.setenv("XVERIF_MCP_REQUEST_TIMEOUT_SEC", "60")
    pythonpath = str(MCP_SRC)
    if os.environ.get("PYTHONPATH"):
        pythonpath += os.pathsep + os.environ["PYTHONPATH"]
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    for name in (
        "XVERIF_MCP_FAKE_LSF",
        "FAKE_BSUB_PENDING_DELAY_MS",
        "FAKE_BSUB_STDOUT_NOISE_BEFORE_READY",
        "FAKE_BSUB_STDERR_LINES",
        "FAKE_BSUB_EXIT_BEFORE_READY",
        "FAKE_BSUB_EXIT_AFTER_READY",
        "FAKE_BSUB_KILL_CHILD_AFTER_MS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in (extra_env or {}).items():
        monkeypatch.setenv(name, value)
    if "xverif_mcp.server" in sys.modules:
        return importlib.reload(sys.modules["xverif_mcp.server"])
    return importlib.import_module("xverif_mcp.server")


def _call(server, name: str, args: dict[str, Any] | None = None):
    return _portal(server).call(server.mcp.call_tool, name, args or {})


def _text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    assert content
    return content[0].text


def _json(result) -> dict[str, Any]:
    return json.loads(_text(result))


def _list_tools(server) -> set[str]:
    return {tool.name for tool in _portal(server).call(server.mcp.list_tools)}


def _kill_native_sessions(isolated_home: Path) -> None:
    subprocess.run(
        [str(REPO_ROOT / "tools" / "xdebug"), "--json", "-"],
        input=json.dumps(
            {
                "api_version": "xdebug.v1",
                "action": "session.kill",
                "target": {"session_id": "all"},
            }
        )
        + "\n",
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        env={**os.environ, "HOME": str(isolated_home)},
    )


@pytest.fixture
def mcp_resources(xverif_fixture) -> dict[str, str]:
    uart = xverif_fixture("xdebug.design_uart")
    wave = xverif_fixture("xdebug.ai_complex_wave")
    combined = xverif_fixture("xdebug.active_driver")
    return {
        "daidir": str(uart / "simv.daidir"),
        "fsdb": str(wave / "out/waves.fsdb"),
        "combined_daidir": str(combined / "out/simv.daidir"),
        "combined_fsdb": str(combined / "out/waves.fsdb"),
    }


@pytest.mark.mcp
@pytest.mark.mcp_direct
def test_mcp_direct_tools_discovery_schema_and_one_shot_actions(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
) -> None:
    server = _load_server(monkeypatch, isolated_home, backend="direct")
    try:
        names = _list_tools(server)
        assert {
            "xverif_debug_list_actions",
            "xverif_debug_get_schema",
            "xverif_debug_session_open",
            "xverif_debug_query",
            "xverif_debug_session_close",
        } <= names

        actions = _json(_call(server, "xverif_debug_list_actions"))
        assert actions["ok"] is True
        assert "value.at" in actions["data"]["actions"]

        schema = _json(
            _call(
                server,
                "xverif_debug_get_schema",
                {"action": "value.at", "kind": "request"},
            )
        )
        assert schema["ok"] is True
        assert schema["summary"]["action"] == "value.at"
        assert schema["summary"]["view"] == "mcp"
        assert schema["data"]["args_schema"]["properties"]["signal"]["type"] == "string"
        assert schema["data"]["minimal_call"]["action"] == "value.at"
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_direct
def test_mcp_direct_real_waveform_design_and_combined_sessions(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
) -> None:
    server = _load_server(monkeypatch, isolated_home, backend="direct")
    try:
        wave_open = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {"name": "mcp_wave", "fsdb": mcp_resources["fsdb"]},
            )
        )
        assert wave_open["ok"] is True
        wave = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "mcp_wave",
                    "action": "value.at",
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "clock": "ai_complex_top.clk",
                        "time": "75ns",
                        "value_format": "hex",
                    },
                    "output_format": "json",
                },
            )
        )
        assert wave["ok"] is True
        assert wave["data"]["value"]["known"] is True

        ordinary_error = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "mcp_wave",
                    "action": "value.at",
                    "args": {
                        "signal": "ai_complex_top.no_such",
                        "clock": "ai_complex_top.clk",
                        "time": "10ns",
                    },
                    "output_format": "json",
                },
            )
        )
        assert ordinary_error["ok"] is False
        assert ordinary_error["error"]["code"] == "SIGNAL_NOT_FOUND"
        listed = _json(_call(server, "xverif_debug_session_list"))
        assert any(row["alias"] == "mcp_wave" for row in listed["sessions"])

        design_open = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {
                    "name": "mcp_design",
                    "daidir": mcp_resources["daidir"],
                },
            )
        )
        assert design_open["ok"] is True, design_open
        design = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "mcp_design",
                    "action": "trace.driver",
                    "args": {"signal": "uart_16550.RXDin"},
                    "output_format": "json",
                },
            )
        )
        assert design["ok"] is True
        assert design["data"]["paths"]
        assert design["summary"]["path_count"] == len(design["data"]["paths"])

        combined_open = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {
                    "name": "mcp_combined",
                    "daidir": mcp_resources["combined_daidir"],
                    "fsdb": mcp_resources["combined_fsdb"],
                },
            )
        )
        assert combined_open["ok"] is True
        combined = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "mcp_combined",
                    "action": "trace.active_driver",
                    "args": {
                        "signal": "active_driver_tb.u_dut.q",
                        "time": "20ns",
                    },
                    "output_format": "json",
                },
            )
        )
        assert combined["ok"] is True
        assert combined["data"]["paths"]
        assert combined["summary"]["path_count"] == len(combined["data"]["paths"])

        for name in ("mcp_combined", "mcp_design", "mcp_wave"):
            closed = _json(
                _call(server, "xverif_debug_session_close", {"name": name})
            )
            assert closed["ok"] is True
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_direct
def test_mcp_direct_matches_cli_normalized_json_response(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
    cli_runner: CliRunner,
) -> None:
    server = _load_server(monkeypatch, isolated_home, backend="direct")
    try:
        opened = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {"name": "mcp_cli_equiv", "fsdb": mcp_resources["fsdb"]},
            )
        )
        assert opened["ok"] is True

        mcp_response = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "mcp_cli_equiv",
                    "action": "value.at",
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "clock": "ai_complex_top.clk",
                        "time": "75ns",
                        "value_format": "hex",
                    },
                    "output_format": "json",
                },
            )
        )
        assert mcp_response["ok"] is True

        cli_response = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "value.at",
                "target": {"session_id": "mcp_cli_equiv"},
                "args": {
                    "signal": "ai_complex_top.sig_a",
                    "clock": "ai_complex_top.clk",
                    "time": "75ns",
                    "value_format": "hex",
                },
            },
            output_format="json",
            env={"HOME": str(isolated_home), "XVERIF_HOME": str(REPO_ROOT)},
        )
        assert cli_response.ok, cli_response.response

        opts = NormalizeOptions(
            volatile_keys={
                "created_at",
                "elapsed_ms",
                "elapsed_us",
                "ended_at",
                "job_id",
                "last_active",
                "pid",
                "ppid",
                "request_id",
                "server_host",
                "socket_path",
                "started_at",
                "timestamp",
                "updated_at",
            }
        )
        assert normalize_response(mcp_response, opts) == normalize_response(
            cli_response.response,
            opts,
        )

        closed = _json(
            _call(server, "xverif_debug_session_close", {"name": "mcp_cli_equiv"})
        )
        assert closed["ok"] is True
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_direct
def test_mcp_batch_runs_real_session_workflow(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
    tmp_path: Path,
) -> None:
    server = _load_server(monkeypatch, isolated_home, backend="direct")
    batch_file = tmp_path / "requests.ndjson"
    output_file = tmp_path / "results.ndjson"
    rows = [
        {
            "tool": "xverif_debug_session_open",
            "args": {"name": "batch_wave", "fsdb": mcp_resources["fsdb"]},
        },
        {
            "tool": "xverif_debug_query",
            "args": {
                "session_id": "batch_wave",
                "action": "value.at",
                "args": {"signal": "ai_complex_top.sig_a", "clock": "ai_complex_top.clk", "time": "75ns"},
                "output_format": "json",
            },
        },
        {
            "tool": "xverif_debug_session_close",
            "args": {"name": "batch_wave"},
        },
    ]
    batch_file.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    try:
        result = _json(
            _call(
                server,
                "xverif_batch",
                {
                    "batch_file": str(batch_file),
                    "output_file": str(output_file),
                },
            )
        )
        assert result == {
            "ok": True,
            "total": 3,
            "ok_count": 3,
            "failed_count": 0,
            "output_file": str(output_file),
        }
        output_rows = [
            json.loads(line)
            for line in output_file.read_text(encoding="utf-8").splitlines()
        ]
        assert [row["ok"] for row in output_rows] == [True, True, True]
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_fake_lsf
def test_mcp_fake_lsf_launches_real_xdebug_stdio_loop(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
) -> None:
    server = _load_server(
        monkeypatch,
        isolated_home,
        backend="lsf",
        extra_env={
            "XVERIF_MCP_FAKE_LSF": "1",
            "FAKE_BSUB_PENDING_DELAY_MS": "100",
            "FAKE_BSUB_STDOUT_NOISE_BEFORE_READY": "1",
            "FAKE_BSUB_STDERR_LINES": "50",
        },
    )
    try:
        opened = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {"name": "fake_lsf_wave", "fsdb": mcp_resources["fsdb"]},
            )
        )
        assert opened["ok"] is True
        assert opened["session"]["launcher"] == "lsf"
        assert "job_id" not in opened["session"]
        listed = _json(
            _call(
                server,
                "xverif_debug_session_list",
                {"verbose": True},
            )
        )
        assert listed["sessions"][0]["job_id"] == "123"

        queried = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "fake_lsf_wave",
                    "action": "value.at",
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "clock": "ai_complex_top.clk",
                        "time": "75ns",
                    },
                    "output_format": "json",
                },
            )
        )
        assert queried["ok"] is True

        closed = _json(
            _call(
                server,
                "xverif_debug_session_close",
                {"name": "fake_lsf_wave"},
            )
        )
        assert closed["ok"] is True
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_fake_lsf
def test_mcp_fake_lsf_reports_exit_before_ready(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
) -> None:
    server = _load_server(
        monkeypatch,
        isolated_home,
        backend="lsf",
        extra_env={
            "XVERIF_MCP_FAKE_LSF": "1",
            "FAKE_BSUB_EXIT_BEFORE_READY": "1",
        },
    )
    try:
        opened = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {"name": "fake_lsf_no_ready", "fsdb": mcp_resources["fsdb"]},
            )
        )
        assert opened["ok"] is False
        assert opened["error"]["code"] == "SESSION_OPEN_FAILED"
        listed = _json(_call(server, "xverif_debug_session_list"))
        assert listed["sessions"] == []
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_fake_lsf
def test_mcp_fake_lsf_child_crash_evicts_session(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
) -> None:
    server = _load_server(
        monkeypatch,
        isolated_home,
        backend="lsf",
        extra_env={
            "XVERIF_MCP_FAKE_LSF": "1",
            "FAKE_BSUB_KILL_CHILD_AFTER_MS": "1000",
        },
    )
    try:
        opened = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {"name": "fake_lsf_crash", "fsdb": mcp_resources["fsdb"]},
            )
        )
        assert opened["ok"] is True
        time.sleep(1.2)
        queried = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "fake_lsf_crash",
                    "action": "value.at",
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "clock": "ai_complex_top.clk",
                        "time": "75ns",
                    },
                    "output_format": "json",
                },
            )
        )
        assert queried["ok"] is False
        assert queried["error"]["code"] == "SESSION_LOST"
        listed = _json(_call(server, "xverif_debug_session_list"))
        assert listed["sessions"] == []
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)


@pytest.mark.mcp
@pytest.mark.mcp_real_lsf
@pytest.mark.optional_lsf
@pytest.mark.nightly
@pytest.mark.slow
def test_mcp_real_lsf_optional_waveform_smoke(
    monkeypatch: pytest.MonkeyPatch,
    isolated_home: Path,
    mcp_resources: dict[str, str],
) -> None:
    if os.environ.get("XDEBUG_ENABLE_REAL_LSF") != "1":
        pytest.skip("real LSF is optional; set XDEBUG_ENABLE_REAL_LSF=1")

    server = _load_server(
        monkeypatch,
        isolated_home,
        backend="lsf",
        extra_env={
            "XDEBUG_ENABLE_REAL_LSF": "1",
        },
    )
    try:
        opened = _json(
            _call(
                server,
                "xverif_debug_session_open",
                {
                    "name": "real_lsf_wave",
                    "fsdb": mcp_resources["fsdb"],
                },
            )
        )
        assert opened["ok"] is True, opened
        assert opened["session"]["launcher"] == "lsf"
        assert "job_id" not in opened["session"]
        assert "job_name" not in opened["session"]
        listed = _json(
            _call(
                server,
                "xverif_debug_session_list",
                {"verbose": True},
            )
        )
        assert listed["sessions"][0].get("job_id") or listed["sessions"][0].get("job_name")

        queried = _json(
            _call(
                server,
                "xverif_debug_query",
                {
                    "session_id": "real_lsf_wave",
                    "action": "value.at",
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "clock": "ai_complex_top.clk",
                        "time": "75ns",
                    },
                    "output_format": "json",
                },
            )
        )
        assert queried["ok"] is True
        assert queried["data"]["value"]["known"] is True

        closed = _json(
            _call(
                server,
                "xverif_debug_session_close",
                {"name": "real_lsf_wave"},
            )
        )
        assert closed["ok"] is True
        assert closed["summary"]["status"] == "closed"
        assert closed["summary"]["cleanup_complete"] is True
    finally:
        _close_loaded_server()
        _kill_native_sessions(isolated_home)
