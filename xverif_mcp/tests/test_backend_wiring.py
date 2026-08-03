"""Verify MCP backend wiring and adapter-local response shaping."""

import anyio
import json
from types import SimpleNamespace

import pytest

from xverif_mcp.adapters.xcov import XverifCoverageAdapter
from xverif_mcp.adapters.xdebug import XverifDebugAdapter
from xverif_loop.config import resolve_mcp_runtime_config
from xverif_loop.sessions.launchers import (
    DirectLauncher,
    LauncherTerminationError,
    LsfLauncher,
)
from xverif_loop.sessions.session_manager import McpSessionManager


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (False, "INVALID_BATCH_REQUEST"),
        ([], "INVALID_BATCH_REQUEST"),
        ({"tool": "xverif_ping"}, "INVALID_BATCH_REQUEST"),
        ({"args": {}}, "INVALID_BATCH_REQUEST"),
        ({"tool": "xverif_ping", "args": {}, "unknown": True}, "INVALID_BATCH_REQUEST"),
        ({"tool": False, "args": {}}, "INVALID_BATCH_REQUEST"),
        ({"tool": "xverif_ping", "args": False}, "INVALID_BATCH_ARGUMENTS"),
    ],
)
def test_batch_line_contract_is_exact_and_closed(payload: object, code: str) -> None:
    from xverif_mcp.server import _BatchRequestError, _validate_batch_request

    with pytest.raises(_BatchRequestError) as caught:
        _validate_batch_request(payload)
    assert caught.value.error["code"] == code


def test_batch_line_contract_accepts_only_exact_tool_and_args() -> None:
    from xverif_mcp.server import _validate_batch_request

    args = {"expr": "2 + 3"}
    assert _validate_batch_request(
        {"tool": "xverif_bit_eval", "args": args},
    ) == ("xverif_bit_eval", args)


def test_batch_tool_args_use_strict_closed_fastmcp_model() -> None:
    from xverif_mcp import server

    tool = server.mcp._tool_manager.get_tool("xverif_ping")
    assert tool is not None
    assert tool.fn_metadata.arg_model.model_config["extra"] == "forbid"
    assert tool.fn_metadata.arg_model.model_config["strict"] is True

    async def run():
        return await server._execute_one("xverif_ping", {"unknown": True})

    ok, error, _, response = anyio.run(run)
    assert ok is False
    assert error is not None
    assert error["code"] == "MCP_CALL_ERROR"
    assert response is None


def test_backend_uses_session_manager():
    backend = XverifDebugAdapter(mode="direct")
    assert isinstance(backend._sessions, McpSessionManager)


def test_lsf_mode_rejected():
    from xverif_loop.config import ConfigError
    with pytest.raises(ConfigError, match=r"invalid mode='invalid'; expected 'direct' or 'lsf'"):
        resolve_mcp_runtime_config().with_overrides(backend="invalid")


def test_direct_launcher_propagates_unconfirmed_process_termination() -> None:
    class FailingHandle:
        def terminate(self):
            raise RuntimeError("process termination was not confirmed")

    with pytest.raises(LauncherTerminationError) as caught:
        DirectLauncher().terminate(FailingHandle())
    assert caught.value.result["ok"] is False
    assert caught.value.result["stage"] == "process"
    assert caught.value.result["error_type"] == "RuntimeError"
    assert isinstance(caught.value.result["elapsed_ms"], int)


def test_lsf_launcher_returns_confirmed_process_and_scheduler_truth(monkeypatch) -> None:
    calls = []
    events = []

    class Handle:
        job_id = "123"
        job_name = "ignored"
        log_alias = "unit"

        def terminate(self):
            return {"ok": True, "status": "terminated", "returncode": -15}

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("XVERIF_LSF_BKILL", "bkill")
    monkeypatch.setattr("xverif_loop.sessions.launchers.subprocess.run", fake_run)
    handle = Handle()
    handle.runtime = resolve_mcp_runtime_config().with_overrides(backend="lsf")
    handle.logger = SimpleNamespace(
        try_lsf=lambda alias, phase, ok, **fields: events.append(
            {"alias": alias, "phase": phase, "ok": ok, **fields}
        )
    )

    result = LsfLauncher.__new__(LsfLauncher).terminate(handle)

    assert result["ok"] is True
    assert result["process"]["status"] == "terminated"
    assert result["scheduler"]["ok"] is True
    assert calls[0][0][-1] == "123"
    assert calls[0][1]["check"] is False
    assert events[-1]["phase"] == "launcher.lsf.terminate"
    assert events[-1]["ok"] is True


def test_lsf_launcher_raises_structured_partial_failure_without_output_leak(monkeypatch) -> None:
    events = []

    class Handle:
        job_id = "123"
        job_name = None
        log_alias = "unit"

        def terminate(self):
            return {"ok": True, "status": "already_exited", "returncode": 0}

    monkeypatch.setenv("XVERIF_LSF_BKILL", "bkill")
    monkeypatch.setattr(
        "xverif_loop.sessions.launchers.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=7,
            stdout="private scheduler stdout",
            stderr="private scheduler stderr",
        ),
    )
    handle = Handle()
    handle.runtime = resolve_mcp_runtime_config().with_overrides(backend="lsf")
    handle.logger = SimpleNamespace(
        try_lsf=lambda alias, phase, ok, **fields: events.append(
            {"alias": alias, "phase": phase, "ok": ok, **fields}
        )
    )

    with pytest.raises(LauncherTerminationError) as caught:
        LsfLauncher.__new__(LsfLauncher).terminate(handle)

    result = caught.value.result
    assert result["ok"] is False
    assert result["process"]["ok"] is True
    assert result["scheduler"]["returncode"] == 7
    assert result["scheduler"]["stdout_present"] is True
    assert result["scheduler"]["stderr_present"] is True
    assert "private scheduler" not in repr(result)
    assert events[-1]["phase"] == "launcher.lsf.terminate"
    assert events[-1]["ok"] is False


def test_lsf_launcher_rejects_missing_scheduler_identity() -> None:
    class Handle:
        job_id = None
        job_name = None
        log_alias = "unit"

        def terminate(self):
            return {"ok": True, "status": "terminated", "returncode": -15}

    handle = Handle()
    handle.runtime = resolve_mcp_runtime_config().with_overrides(backend="lsf")
    handle.logger = SimpleNamespace(try_lsf=lambda *args, **kwargs: None)

    with pytest.raises(LauncherTerminationError) as caught:
        LsfLauncher.__new__(LsfLauncher).terminate(handle)

    assert caught.value.result["scheduler"] == {
        "ok": False,
        "status": "job_identity_missing",
    }


def test_cov_adapter_one_shot_selects_format_only_with_cli(monkeypatch):
    calls = []

    class DummyRunner:
        def run_json(self, tool, argv, input_text):
            calls.append(("json", tool, argv, json.loads(input_text)))
            return {"ok": True, "action": "actions"}

        def run_xout(self, tool, argv, input_text):
            calls.append(("xout", tool, argv, json.loads(input_text)))
            return "@xcov.v1 ok action=metrics.list request_id=unit\n"

    monkeypatch.setattr("xverif_mcp.runner.StatelessCliRunner", DummyRunner)
    adapter = XverifCoverageAdapter(mode="direct")

    assert adapter.actions()["ok"] is True
    assert adapter.request(
        {"api_version": "xcov.v1", "action": "metrics.list"},
        output_format="xout",
    ).startswith("@xcov.v1 ok action=metrics.list")
    assert calls[0][0] == "json"
    assert calls[1][0] == "xout"


def test_mcp_adapter_restores_its_config_after_loop_wrapper(monkeypatch):
    from xverif_loop.wrapper import LoopWrapperService
    from xverif_mcp.adapters.xcov import XverifCoverageAdapter

    wrapper = LoopWrapperService(mode="direct", xdebug_bin="xdebug", xcov_bin="xcov")
    monkeypatch.setenv("XVERIF_MCP_BACKEND", "lsf")
    debug = XverifDebugAdapter()
    cov = XverifCoverageAdapter()
    assert wrapper.mode == "direct"
    assert debug.mode == "lsf"
    assert cov.mode == "lsf"


def test_debug_adapter_resource_free_query_is_a_true_one_shot(monkeypatch):
    calls = []

    class DummyRunner:
        def run_json(self, tool, argv, input_text):
            calls.append(("json", tool, argv, json.loads(input_text)))
            return {"ok": True, "action": "expr.normalize"}

        def run_xout(self, tool, argv, input_text):
            return "@xdebug.expr.normalize.v1\n"

    monkeypatch.setattr("xverif_mcp.runner.StatelessCliRunner", DummyRunner)
    adapter = XverifDebugAdapter(mode="direct")

    result = adapter.query_one_shot(
        action="expr.normalize",
        args={"expr": "a && b"},
        limits={"max_rows": 3},
        output_format="json",
    )

    assert result["ok"] is True
    assert calls[0][3] == {
        "api_version": "xdebug.v1",
        "action": "expr.normalize",
        "args": {"expr": "a && b"},
        "limits": {"max_rows": 3},
    }


def test_debug_adapter_resource_free_query_rejects_loop_envelope():
    adapter = XverifDebugAdapter(mode="direct")
    result = adapter.query_one_shot(
        action="expr.normalize",
        args={"expr": "a"},
        output_format="envelope",
    )
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert "managed stdio-loop session" in result["error"]["message"]


def test_debug_adapter_resource_free_error_uses_sessionless_mcp_example(monkeypatch):
    class DummyRunner:
        def run_json(self, tool, argv, input_text):
            return {
                "ok": False,
                "action": "expr.normalize",
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "bad expr",
                    "correct_example": {
                        "api_version": "xdebug.v1",
                        "action": "expr.normalize",
                        "args": {"expr": "a && b"},
                    },
                },
            }

    monkeypatch.setattr("xverif_mcp.runner.StatelessCliRunner", DummyRunner)
    adapter = XverifDebugAdapter(mode="direct")
    result = adapter.query_one_shot(
        action="expr.normalize",
        args={"expr": ""},
        output_format="json",
    )
    assert result["error"]["correct_example"] == {
        "tool": "xverif_debug_query",
        "args": {"action": "expr.normalize", "args": {"expr": "a && b"}},
    }
