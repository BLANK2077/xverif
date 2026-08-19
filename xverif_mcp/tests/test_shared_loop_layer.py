"""Tests for the SDK-free shared loop backend layer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys
import threading
import tomllib
from types import SimpleNamespace

import pytest


def test_xverif_loop_imports_without_mcp_sdk() -> None:
    import xverif_loop
    from xverif_loop.lsf.protocol import JsonlProcess, ProtocolError
    from xverif_loop.sessions.session_manager import McpSessionManager

    assert xverif_loop is not None
    assert JsonlProcess is not None
    assert ProtocolError is not None
    assert McpSessionManager is not None


def test_xverif_loop_package_has_no_mcp_sdk_imports() -> None:
    package_root = Path(__file__).resolve().parents[1] / "src" / "xverif_loop"
    offenders: list[str] = []
    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("from mcp", "import mcp", "xverif_mcp.server"):
            if needle in text:
                offenders.append(f"{path.relative_to(package_root)}:{needle}")
    assert offenders == []


def test_sdk_free_runtime_has_no_mcp_compatibility_reexports() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src"
    forbidden = [
        src_root / "xverif_mcp/config.py",
        src_root / "xverif_mcp/logging.py",
        src_root / "xverif_mcp/xdebug_errors.py",
        src_root / "xverif_mcp/sessions/__init__.py",
        src_root / "xverif_mcp/sessions/launchers.py",
        src_root / "xverif_mcp/sessions/loop_session.py",
        src_root / "xverif_mcp/sessions/session_errors.py",
        src_root / "xverif_mcp/sessions/session_manager.py",
        src_root / "xverif_mcp/lsf/bsub.py",
        src_root / "xverif_mcp/lsf/fake_bsub.py",
        src_root / "xverif_mcp/lsf/protocol.py",
    ]
    assert [str(path.relative_to(src_root)) for path in forbidden if path.exists()] == []

    offenders: list[str] = []
    for path in (src_root / "xverif_mcp").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in (
            "from xverif_mcp.config",
            "from xverif_mcp.logging",
            "from xverif_mcp.xdebug_errors",
            "from xverif_mcp.sessions",
            "from xverif_mcp.lsf.bsub",
            "from xverif_mcp.lsf.protocol",
        ):
            if needle in text:
                offenders.append(f"{path.relative_to(src_root)}:{needle}")
    assert offenders == []


def test_runtime_packaging_is_separate_from_testinfra() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    root_project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    runtime_project = tomllib.loads(
        (repo_root / "xverif_mcp/pyproject.toml").read_text(encoding="utf-8")
    )

    assert root_project["project"]["name"] == "xverif-testinfra"
    assert root_project["tool"]["setuptools"]["packages"]["find"]["include"] == ["testinfra*"]
    assert runtime_project["project"]["name"] == "xverif-mcp"
    assert runtime_project["project"]["scripts"] == {
        "xverif-mcp": "xverif_mcp.server:main",
        "xdebug_lsf": "xverif_loop.native_cli:xdebug_main",
        "xcov_lsf": "xverif_loop.native_cli:xcov_main",
    }


def test_runtime_defaults_use_user_xverif_home(monkeypatch, tmp_path: Path) -> None:
    from xverif_loop.config import resolve_mcp_runtime_config
    from xverif_loop.logging import resolve_logger
    from xverif_loop.wrapper import default_socket_path

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XVERIF_TEST_TMPDIR", raising=False)
    monkeypatch.delenv("XVERIF_MCP_LOG_DIR", raising=False)
    monkeypatch.delenv("XVERIF_LOOP_SOCKET", raising=False)

    runtime = resolve_mcp_runtime_config()
    logger = resolve_logger(runtime)
    assert logger.log_root() == home / ".xverif" / "mcp"
    assert default_socket_path() == str(
        home / ".xverif" / "loop-wrapper" / f"xverif-loop-{os.getuid()}.sock"
    )


def test_test_runtime_defaults_use_repository_tmp(monkeypatch, tmp_path: Path) -> None:
    from xverif_loop.config import resolve_mcp_runtime_config
    from xverif_loop.logging import resolve_logger
    from xverif_loop.wrapper import default_socket_path

    test_tmp = tmp_path / "repo" / "tmp"
    monkeypatch.setenv("XVERIF_TEST_TMPDIR", str(test_tmp))
    monkeypatch.delenv("XVERIF_MCP_LOG_DIR", raising=False)
    monkeypatch.delenv("XVERIF_LOOP_SOCKET", raising=False)

    runtime = resolve_mcp_runtime_config()
    logger = resolve_logger(runtime)
    assert logger.log_root() == test_tmp / ".xverif" / "mcp"
    assert default_socket_path() == str(test_tmp / f"xverif-loop-{os.getuid()}.sock")


def test_mcp_and_loop_wrapper_loggers_remain_owner_bound_when_interleaved(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_loop.config import (
        resolve_loop_wrapper_runtime_config,
        resolve_mcp_runtime_config,
    )
    from xverif_loop.logging import resolve_logger
    from xverif_loop.wrapper import LoopWrapperService
    from xverif_mcp.adapters.xdebug import XverifDebugAdapter

    mcp_root = tmp_path / "mcp"
    wrapper_root = tmp_path / "loop-wrapper"
    monkeypatch.setenv("XVERIF_MCP_LOG_DIR", str(mcp_root))
    monkeypatch.setenv("XVERIF_LOOP_LOG_DIR", str(wrapper_root))

    mcp_runtime = resolve_mcp_runtime_config()
    mcp_logger = resolve_logger(mcp_runtime)
    wrapper_runtime = resolve_loop_wrapper_runtime_config()
    wrapper_logger = resolve_logger(wrapper_runtime)

    adapter = XverifDebugAdapter(
        runtime=mcp_runtime,
        logger=mcp_logger,
    )
    adapter.session_list()
    wrapper = LoopWrapperService(
        mode="direct",
        xdebug_bin="xdebug",
        xcov_bin="xcov",
        runtime=wrapper_runtime,
        logger=wrapper_logger,
    )
    wrapper.debug.list_sessions()
    adapter.session_list()

    assert adapter._sessions.logger is mcp_logger
    assert wrapper.debug.logger is wrapper_logger
    assert wrapper.cov.logger is wrapper_logger

    mcp_events = [
        json.loads(line)
        for line in mcp_logger.server_log_path()
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    wrapper_events = [
        json.loads(line)
        for line in wrapper_logger.server_log_path()
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(mcp_events) >= 2
    assert all(
        event["layer"] == "mcp"
        and event["component"] == "xverif-mcp"
        for event in mcp_events
    )
    assert wrapper_events
    assert all(
        event["layer"] == "loop-wrapper"
        and event["component"] == "xverif-loop-wrapper"
        for event in wrapper_events
    )


@pytest.mark.parametrize(
    "request_payload",
    [
        False,
        [],
        {"id": "case", "method": "server.ping"},
        {
            "id": "case",
            "method": "server.ping",
            "params": {},
            "unknown": True,
        },
        {"id": 1, "method": "server.ping", "params": {}},
        {"id": "case", "method": False, "params": {}},
        {"id": "case", "method": "server.ping", "params": False},
    ],
)
def test_sdk_free_wrapper_envelope_is_exact_and_closed(
    request_payload: object,
) -> None:
    from xverif_loop.wrapper import LoopWrapperService

    service = LoopWrapperService(
        mode="direct",
        xdebug_bin="false",
        xcov_bin="false",
    )
    response = service.dispatch(request_payload)
    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("server.ping", {"unknown": True}),
        ("debug.session.list", {"verbose": 1}),
        ("debug.session.open", {"name": "case", "fsdb": False}),
        (
            "debug.query",
            {"session_id": "case", "action": "value.at", "args": False},
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
                "output_format": "yaml",
            },
        ),
        (
            "cov.query",
            {
                "session_id": "case",
                "action": "code_coverage.summary",
                "args": [],
            },
        ),
        ("cov.session.gc", {"verbose": 0}),
    ],
)
def test_sdk_free_wrapper_params_use_exact_types(
    method: str,
    params: dict,
) -> None:
    from xverif_loop.wrapper import LoopWrapperService

    service = LoopWrapperService(
        mode="direct",
        xdebug_bin="false",
        xcov_bin="false",
    )
    response = service.dispatch(
        {"id": "contract", "method": method, "params": params},
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_PARAMS"


@pytest.mark.parametrize("value", ["DIRECT", " direct", "direct ", "", "auto"])
def test_backend_config_is_exact_and_typed(monkeypatch, value: str) -> None:
    from xverif_loop.config import (
        ConfigError,
        resolve_mcp_runtime_config,
    )

    monkeypatch.setenv("XVERIF_MCP_BACKEND", value)
    with pytest.raises(ConfigError) as caught:
        resolve_mcp_runtime_config()
    assert caught.value.env_name == "XVERIF_MCP_BACKEND"
    assert caught.value.value == value
    assert caught.value.expected == "'direct' or 'lsf'"


@pytest.mark.parametrize(
    ("field_name", "env_name"),
    [
        ("default_timeout_sec", "XVERIF_MCP_TIMEOUT_SEC"),
        ("startup_timeout_sec", "XVERIF_MCP_STARTUP_TIMEOUT_SEC"),
        ("request_timeout_sec", "XVERIF_MCP_REQUEST_TIMEOUT_SEC"),
        ("close_timeout_sec", "XVERIF_MCP_CLOSE_TIMEOUT_SEC"),
        ("bkill_timeout_sec", "XVERIF_MCP_BKILL_TIMEOUT_SEC"),
    ],
)
@pytest.mark.parametrize("value", ["", "0", "-1", "nan", "inf", " 1", "1 ", "bad"])
def test_timeout_config_requires_finite_positive_exact_value(
    monkeypatch,
    field_name: str,
    env_name: str,
    value: str,
) -> None:
    from xverif_loop import config

    monkeypatch.setenv(env_name, value)
    with pytest.raises(config.ConfigError) as caught:
        config.resolve_mcp_runtime_config()
    assert caught.value.env_name == env_name
    assert caught.value.value == value
    assert caught.value.expected == "a finite positive number"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "1"])
def test_stateless_runner_rejects_invalid_explicit_timeout(value: object) -> None:
    from xverif_loop.config import ConfigError
    from xverif_mcp.runner import StatelessCliRunner

    with pytest.raises(ConfigError) as caught:
        StatelessCliRunner(timeout_sec=value)
    assert caught.value.env_name == "timeout_sec"
    assert caught.value.expected == "a finite positive number"


def test_fake_lsf_flag_is_strict_and_namespace_local(monkeypatch) -> None:
    from xverif_loop import config

    monkeypatch.delenv("XVERIF_LOOP_FAKE_LSF", raising=False)
    monkeypatch.setenv("XVERIF_MCP_FAKE_LSF", "1")
    assert (
        config.resolve_loop_wrapper_runtime_config().fake_lsf
        is False
    )

    monkeypatch.setenv("XVERIF_LOOP_FAKE_LSF", "true")
    with pytest.raises(
        config.ConfigError,
        match=(
            r"invalid XVERIF_LOOP_FAKE_LSF='true'; "
            r"expected '0' or '1'"
        ),
    ):
        config.resolve_loop_wrapper_runtime_config()

    monkeypatch.setenv("XVERIF_LOOP_FAKE_LSF", "1")
    assert (
        config.resolve_loop_wrapper_runtime_config().fake_lsf
        is True
    )

    assert config.resolve_mcp_runtime_config().fake_lsf is True


def test_fake_lsf_resolves_paired_scheduler_commands_at_composition_root(
    tmp_path: Path,
) -> None:
    from xverif_loop.config import (
        resolve_loop_wrapper_runtime_config,
        resolve_mcp_runtime_config,
    )

    fake_bsub = [sys.executable, "-m", "xverif_loop.lsf.fake_bsub"]
    fake_bkill = [sys.executable, "-m", "xverif_loop.lsf.fake_bkill"]
    runtimes = (
        resolve_mcp_runtime_config(
            {
                "HOME": str(tmp_path),
                "XVERIF_MCP_FAKE_LSF": "1",
            }
        ),
        resolve_loop_wrapper_runtime_config(
            {
                "HOME": str(tmp_path),
                "XVERIF_LOOP_FAKE_LSF": "1",
            }
        ),
    )

    for runtime in runtimes:
        assert shlex.split(runtime.lsf_bsub_command) == fake_bsub
        assert shlex.split(runtime.lsf_bkill_command) == fake_bkill

    overridden = resolve_mcp_runtime_config(
        {
            "HOME": str(tmp_path),
            "XVERIF_MCP_FAKE_LSF": "1",
            "XVERIF_LSF_BSUB": "custom-bsub --interactive",
            "XVERIF_LSF_BKILL": "custom-bkill --confirmed",
        }
    )
    assert overridden.lsf_bsub_command == "custom-bsub --interactive"
    assert overridden.lsf_bkill_command == "custom-bkill --confirmed"


@pytest.mark.parametrize("env_name", ["XVERIF_LSF_BSUB", "XVERIF_LSF_BKILL"])
@pytest.mark.parametrize("value", ["", " ", "'"])
def test_lsf_command_config_rejects_empty_or_invalid_command(
    tmp_path: Path,
    env_name: str,
    value: str,
) -> None:
    from xverif_loop.config import ConfigError, resolve_mcp_runtime_config

    with pytest.raises(ConfigError) as caught:
        resolve_mcp_runtime_config(
            {
                "HOME": str(tmp_path),
                env_name: value,
            }
        )
    assert caught.value.env_name == env_name
    assert caught.value.value == value
    assert caught.value.expected == (
        "a non-empty shell command with valid quoting"
    )


@pytest.mark.parametrize(
    "env_name",
    ["XVERIF_LSF_SESSION_QUEUE", "XVERIF_LSF_SESSION_RESOURCE"],
)
@pytest.mark.parametrize("value", ["", " ", " queue", "queue "])
def test_lsf_queue_and_resource_config_are_strict(
    tmp_path: Path,
    env_name: str,
    value: str,
) -> None:
    from xverif_loop.config import ConfigError, resolve_mcp_runtime_config

    with pytest.raises(ConfigError) as caught:
        resolve_mcp_runtime_config({
            "HOME": str(tmp_path),
            env_name: value,
        })
    assert caught.value.env_name == env_name
    assert caught.value.value == value
    assert caught.value.expected == (
        "a non-empty string without surrounding whitespace"
    )


@pytest.mark.parametrize(
    ("option", "value"),
    [("queue", ""), ("queue", " queue"), ("resource", " ")],
)
def test_session_open_rejects_invalid_explicit_lsf_options(
    tmp_path: Path,
    option: str,
    value: str,
) -> None:
    from xverif_loop.sessions.session_manager import McpSessionManager

    runtime, logger = _runtime_and_logger(tmp_path)
    manager = McpSessionManager(
        runtime=runtime,
        xdebug_bin="must-not-start",
        backend="xcov",
        logger=logger,
    )

    response = manager.open_session(
        "invalid_lsf_option",
        fsdb="merged.vdb",
        **{option: value},
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "INVALID_LSF_OPTION"
    assert response["error"]["option"] == option
    assert manager.sessions == {}


def _runtime_and_logger(tmp_path: Path):
    from xverif_loop.config import resolve_mcp_runtime_config
    from xverif_loop.logging import resolve_logger

    runtime = resolve_mcp_runtime_config(
        environ={
            "HOME": str(tmp_path / "home"),
            "XVERIF_MCP_LOG_DIR": str(tmp_path / "logs"),
        },
    )
    return runtime, resolve_logger(runtime)


def _fail_logging_phases(
    monkeypatch,
    phases: set[str],
) -> None:
    from xverif_loop.logging import (
        StructuredLogger,
        StructuredLoggingError,
    )

    original = StructuredLogger._append

    def injected_failure(self, path, event):
        phase = str(event.get("phase", "unknown"))
        if phase in phases:
            error = StructuredLoggingError(
                operation="append",
                path=path,
                error_type="InjectedLoggingFailure",
            )
            self._record_failure(error, phase=phase)
            raise error
        return original(self, path, event)

    monkeypatch.setattr(
        StructuredLogger,
        "_append",
        injected_failure,
    )


@pytest.mark.parametrize(
    ("open_ok", "terminal_state"),
    [
        pytest.param(True, "alive", id="session"),
        pytest.param(False, "orphan_suspected", id="tombstone"),
    ],
)
def test_same_alias_open_cannot_cross_terminal_publication(
    monkeypatch,
    tmp_path: Path,
    open_ok: bool,
    terminal_state: str,
) -> None:
    from xverif_loop.sessions import session_manager as manager_module
    from xverif_loop.sessions.session_manager import McpSessionManager

    runtime, logger = _runtime_and_logger(tmp_path)
    manager = McpSessionManager(
        runtime=runtime,
        xdebug_bin="xdebug",
        logger=logger,
    )
    result_observed = threading.Event()
    allow_publication = threading.Event()
    constructed: list[object] = []

    class PausingResult(dict):
        def get(self, key, default=None):
            if key == "ok" and not result_observed.is_set():
                result_observed.set()
                if not allow_publication.wait(timeout=5):
                    raise AssertionError("manager did not release open result")
            return super().get(key, default)

    class FakeSession:
        def __init__(self, *, alias, **kwargs):
            self.alias = alias
            self.index = len(constructed)
            self.state = terminal_state if self.index == 0 else "alive"
            self.session_id = alias if self.state == "alive" else None
            constructed.append(self)

        def open(self):
            if self.index:
                return {"ok": True}
            if open_ok:
                return PausingResult({"ok": True})
            return PausingResult({
                "ok": False,
                "error": {"code": "SESSION_OPEN_TRANSPORT_FAILED"},
            })

        def process_alive(self):
            return True

        def public_json(self):
            return {
                "session_id": self.session_id,
                "state": self.state,
            }

    monkeypatch.setattr(
        manager_module,
        "XdebugLoopSession",
        FakeSession,
    )
    first: dict[str, object] = {}

    def run_first_open() -> None:
        try:
            first["response"] = manager.open_session(
                "atomic_case",
                fsdb="waves.fsdb",
            )
        except BaseException as exc:  # pragma: no cover - assertion evidence
            first["exception"] = exc

    thread = threading.Thread(target=run_first_open)
    thread.start()
    try:
        assert result_observed.wait(timeout=5)
        second = manager.open_session(
            "atomic_case",
            fsdb="waves.fsdb",
        )
    finally:
        allow_publication.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert "exception" not in first
    assert second["ok"] is False
    assert second["error"]["code"] == "SESSION_ID_EXISTS"
    assert len(constructed) == 1
    assert "atomic_case" not in manager._opening
    if open_ok:
        assert first["response"]["ok"] is True
        assert manager.sessions["atomic_case"] is constructed[0]
        assert "atomic_case" not in manager.tombstones
    else:
        assert first["response"]["ok"] is False
        assert "atomic_case" not in manager.sessions
        assert manager.tombstones["atomic_case"] is constructed[0]
        assert (
            first["response"]["error"]["manager_record"]
            == "retained_unresolved"
        )


def test_open_logging_failures_leave_one_terminal_manager_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_loop.sessions import session_manager as manager_module
    from xverif_loop.sessions.session_manager import McpSessionManager

    runtime, logger = _runtime_and_logger(tmp_path)
    manager = McpSessionManager(
        runtime=runtime,
        xdebug_bin="xdebug",
        logger=logger,
    )

    with monkeypatch.context() as logging_failure:
        _fail_logging_phases(
            logging_failure,
            {"manager.open.begin"},
        )
        rejected = manager.open_session(
            "logger_case",
            fsdb="waves.fsdb",
        )

    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "OBSERVABILITY_FAILURE"
    assert rejected["error"]["operation_started"] is False
    assert "logger_case" not in manager._opening
    assert "logger_case" not in manager.sessions
    assert "logger_case" not in manager.tombstones

    class FakeSession:
        def __init__(self, *, alias, **kwargs):
            self.alias = alias
            self.session_id = alias
            self.state = "alive"

        def open(self):
            return {"ok": True}

        def process_alive(self):
            return True

        def public_json(self):
            return {
                "session_id": self.session_id,
                "state": self.state,
            }

    monkeypatch.setattr(
        manager_module,
        "XdebugLoopSession",
        FakeSession,
    )
    with monkeypatch.context() as logging_failure:
        _fail_logging_phases(
            logging_failure,
            {"manager.open.end"},
        )
        opened = manager.open_session(
            "logger_case",
            fsdb="waves.fsdb",
        )

    duplicate = manager.open_session(
        "logger_case",
        fsdb="waves.fsdb",
    )
    assert opened["ok"] is True
    assert opened["observability"]["ok"] is False
    assert manager.sessions["logger_case"].state == "alive"
    assert "logger_case" not in manager._opening
    assert "logger_case" not in manager.tombstones
    assert duplicate["ok"] is False
    assert duplicate["error"]["code"] == "SESSION_ID_EXISTS"


def test_logger_resolution_fails_closed_with_path_safe_evidence(
    tmp_path: Path,
) -> None:
    from xverif_loop.config import resolve_mcp_runtime_config
    from xverif_loop.logging import (
        StructuredLoggingError,
        resolve_logger,
    )

    blocked_root = tmp_path / "blocked-root"
    blocked_root.write_text("not a directory", encoding="utf-8")
    runtime = resolve_mcp_runtime_config(
        environ={
            "HOME": str(tmp_path / "home"),
            "XVERIF_MCP_LOG_DIR": str(blocked_root),
        },
    )

    with pytest.raises(StructuredLoggingError) as caught:
        resolve_logger(runtime)

    assert caught.value.operation == "resolve_sink"
    assert caught.value.path_basename == "server.ndjson"
    assert caught.value.error_type == "NotADirectoryError"
    assert str(blocked_root) not in str(caught.value)
    assert caught.value.failure_evidence["phase"] == "logger.resolve"


def test_structured_logger_never_publishes_conditional_cleanup_key(
    tmp_path: Path,
) -> None:
    _, logger = _runtime_and_logger(tmp_path)
    token = "ab" * 32

    logger.session(
        "private_case",
        "session.open.end",
        False,
        ownership_token=token,
        ownership_token_hash="cd" * 32,
        backend_response={
            "ok": False,
            "args": {"ownership_token": token},
            "error": {
                "code": "SESSION_OWNERSHIP_TOKEN_MISMATCH",
                "message": token,
            },
        },
        stderr=token,
    )

    text = logger.session_log_path(
        "private_case",
        "session",
    ).read_text(encoding="utf-8")
    assert token not in text
    event = json.loads(text)
    assert event["ownership_token"] == {"redacted": True}
    assert event["ownership_token_hash"] == {"redacted": True}
    assert event["backend_response"]["present"] is True
    assert event["stderr"]["present"] is True


def test_query_begin_log_failure_prevents_backend_dispatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_loop.sessions.loop_session import XdebugLoopSession

    runtime, logger = _runtime_and_logger(tmp_path)
    session = XdebugLoopSession(
        alias="query_case",
        fsdb="waves.fsdb",
        daidir=None,
        launcher=SimpleNamespace(mode="direct"),
        runtime=runtime,
        logger=logger,
    )
    session.state = "alive"
    session.session_id = "query_case"
    calls: list[dict] = []
    session._call_raw = lambda request, timeout=None: calls.append(
        request
    )
    _fail_logging_phases(monkeypatch, {"query.begin"})

    response = session.query(
        "value.at",
        {"signal": "top.clk"},
        output_format="json",
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "OBSERVABILITY_FAILURE"
    assert response["error"]["operation_started"] is False
    assert calls == []
    assert session.state == "alive"


def test_query_end_log_failure_reports_completed_backend_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_loop.sessions.loop_session import XdebugLoopSession

    runtime, logger = _runtime_and_logger(tmp_path)
    session = XdebugLoopSession(
        alias="query_end_case",
        fsdb="waves.fsdb",
        daidir=None,
        launcher=SimpleNamespace(mode="direct"),
        runtime=runtime,
        logger=logger,
    )
    session.state = "alive"
    session.session_id = "query_end_case"
    calls: list[dict] = []

    def completed(request, timeout=None):
        calls.append(request)
        return {
            "ok": True,
            "json": {
                "ok": True,
                "action": request["action"],
            },
        }

    session._call_raw = completed
    _fail_logging_phases(monkeypatch, {"query.end"})

    response = session.query(
        "value.at",
        {"signal": "top.clk"},
        output_format="json",
    )

    assert len(calls) == 1
    assert response["ok"] is False
    assert response["error"]["code"] == "OBSERVABILITY_FAILURE"
    assert response["error"]["operation_started"] is True
    assert response["error"]["backend_result"] == {
        "received": True,
        "ok": True,
        "output_format": "json",
    }
    assert session.state == "alive"


def test_kill_cleanup_completes_despite_begin_and_end_log_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_loop.sessions.loop_session import XdebugLoopSession

    runtime, logger = _runtime_and_logger(tmp_path)
    terminations: list[object] = []

    class Launcher:
        mode = "direct"

        def terminate(self, handle):
            terminations.append(handle)
            return {
                "ok": True,
                "status": "terminated",
            }

    handle = SimpleNamespace(job_id=None, job_name=None)
    session = XdebugLoopSession(
        alias="cleanup_case",
        fsdb="merged.vdb",
        daidir=None,
        launcher=Launcher(),
        runtime=runtime,
        logger=logger,
        backend="xcov",
        api_version="xcov.v1",
        target_key="vdb",
    )
    session.state = "alive"
    session.session_id = "cleanup_case"
    session.handle = handle
    _fail_logging_phases(
        monkeypatch,
        {"session.kill.begin", "session.kill.end"},
    )

    response = session.kill()

    assert response["ok"] is True
    assert response["cleanup"]["loop_terminate"] == "ok"
    assert terminations == [handle]
    assert session.handle is None
    assert session.state == "closed"
    assert response["observability"]["ok"] is False
    assert response["observability"]["failure_count"] == 2


def test_manager_eviction_is_atomic_when_event_publication_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_loop.sessions.loop_session import XdebugLoopSession
    from xverif_loop.sessions.session_manager import McpSessionManager

    runtime, logger = _runtime_and_logger(tmp_path)
    manager = McpSessionManager(
        runtime=runtime,
        xdebug_bin="xdebug",
        logger=logger,
    )
    session = XdebugLoopSession(
        alias="evict_case",
        fsdb="waves.fsdb",
        daidir=None,
        launcher=SimpleNamespace(mode="direct"),
        runtime=runtime,
        logger=logger,
    )
    session.state = "dead"
    session.session_id = "evict_case"
    manager.sessions["evict_case"] = session
    _fail_logging_phases(monkeypatch, {"manager.evict"})

    manager._evict_session(
        session,
        tombstone_state="closed",
    )

    assert "evict_case" not in manager.sessions
    assert manager.tombstones["evict_case"] is session
    assert manager.tombstones["evict_case"].state == "closed"
    status = logger.observability_status()
    assert status["ok"] is False
    assert status["failures"][-1]["phase"] == "manager.evict"


def test_manager_never_downgrades_a_closed_tombstone(
    tmp_path: Path,
) -> None:
    from xverif_loop.sessions.loop_session import XdebugLoopSession
    from xverif_loop.sessions.session_manager import McpSessionManager

    runtime, logger = _runtime_and_logger(tmp_path)
    manager = McpSessionManager(
        runtime=runtime,
        xdebug_bin="xdebug",
        logger=logger,
    )

    def managed_session(state: str) -> XdebugLoopSession:
        session = XdebugLoopSession(
            alias="precedence_case",
            fsdb="waves.fsdb",
            daidir=None,
            launcher=SimpleNamespace(mode="direct"),
            runtime=runtime,
            logger=logger,
        )
        session.state = state
        session.session_id = "precedence_case"
        return session

    closed = managed_session("closed")
    unresolved = managed_session("orphan_suspected")
    manager.tombstones["precedence_case"] = closed
    manager.sessions["precedence_case"] = unresolved

    manager._evict_session(unresolved)

    assert "precedence_case" not in manager.sessions
    assert manager.tombstones["precedence_case"] is closed
    assert manager.tombstones["precedence_case"].state == "closed"
