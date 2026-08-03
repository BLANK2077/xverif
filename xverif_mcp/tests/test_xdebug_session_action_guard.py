from __future__ import annotations

import pytest

from xverif_loop.wrapper import LoopWrapperService
import xverif_mcp.server as server
from xverif_mcp.server import xverif_cov_query, xverif_debug_query


def test_debug_query_rejects_native_session_action() -> None:
    rsp = xverif_debug_query(session_id="case_a", action="session.close", args={})
    assert rsp["ok"] is False
    error = rsp["error"]
    assert error["code"] == "NATIVE_SESSION_ACTION_FORBIDDEN"
    assert error["error_layer"] == "wrapper"
    assert error["correct_example"]["tool"] == "xverif_debug_session_close"


def test_loop_wrapper_rejects_native_session_action() -> None:
    service = LoopWrapperService(mode="direct", xdebug_bin="false", xcov_bin="false")
    rsp = service.dispatch(
        {
            "id": "q0",
            "method": "debug.query",
            "params": {"session_id": "case_a", "action": "session.open", "args": {}},
        }
    )
    assert rsp["ok"] is False
    error = rsp["error"]
    assert error["code"] == "NATIVE_SESSION_ACTION_FORBIDDEN"
    assert error["error_layer"] == "wrapper"
    assert error["correct_example"]["tool"] == "xverif_debug_session_open"


@pytest.mark.parametrize("action", ["session.open", "session.status", "session.close"])
def test_cov_query_rejects_native_session_action_with_cov_guidance(action: str) -> None:
    rsp = xverif_cov_query(session_id="cov_a", action=action, args={})
    assert rsp["ok"] is False
    error = rsp["error"]
    assert error["code"] == "NATIVE_SESSION_ACTION_FORBIDDEN"
    expected = {
        "session.open": "xverif_cov_session_open",
        "session.status": "xverif_cov_session_doctor",
        "session.close": "xverif_cov_session_close",
    }
    assert error["correct_example"]["tool"] == expected[action]
    assert "xverif_cov_query" in error["example_note"]
    assert "xverif_debug_query" not in error["example_note"]


def test_loop_wrapper_cov_query_rejects_native_session_action() -> None:
    service = LoopWrapperService(mode="direct", xdebug_bin="false", xcov_bin="false")
    rsp = service.dispatch(
        {
            "id": "q1",
            "method": "cov.query",
            "params": {"session_id": "cov_a", "action": "session.gc", "args": {}},
        }
    )
    assert rsp["ok"] is False
    error = rsp["error"]
    assert error["code"] == "NATIVE_SESSION_ACTION_FORBIDDEN"
    assert error["correct_example"]["tool"] == "xverif_cov_session_gc"


@pytest.mark.parametrize("field", ["limits", "output"])
def test_loop_wrapper_cov_query_rejects_removed_outer_field(field: str) -> None:
    service = LoopWrapperService(mode="direct", xdebug_bin="false", xcov_bin="false")
    rsp = service.dispatch({
        "id": "q-contract",
        "method": "cov.query",
        "params": {
            "session_id": "cov_a",
            "action": "code_coverage.holes",
            field: {},
        },
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "INVALID_PARAMS"


class _RecordingDebug:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def query(self, **kwargs):
        self.calls.append(("session", kwargs))
        return {"ok": True, "path": "session"}

    def query_one_shot(self, **kwargs):
        self.calls.append(("one_shot", kwargs))
        return {"ok": True, "path": "one_shot"}


def test_debug_query_dispatches_resource_free_variant_without_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug = _RecordingDebug()
    monkeypatch.setattr(server, "debug", debug)
    monkeypatch.setattr(
        server,
        "query_session_requirement",
        lambda action, args: (
            {"parameter": "session_id", "mode": "conditional", "variants": []},
            {
                "name": "expression",
                "requires": "none",
                "session_id": "forbidden",
            },
        ),
    )
    rsp = server.xverif_debug_query(
        action="expr.normalize",
        args={"expr": "a && b"},
        output_format="json",
    )
    assert rsp == {"ok": True, "path": "one_shot"}
    assert debug.calls == [(
        "one_shot",
        {
            "action": "expr.normalize",
            "args": {"expr": "a && b"},
            "limits": None,
            "output_format": "json",
        },
    )]


def test_debug_query_requires_session_for_resource_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug = _RecordingDebug()
    monkeypatch.setattr(server, "debug", debug)
    monkeypatch.setattr(
        server,
        "query_session_requirement",
        lambda action, args: (
            {"parameter": "session_id", "mode": "conditional", "variants": []},
            {
                "name": "design_signal",
                "requires": "design",
                "session_id": "required",
            },
        ),
    )
    missing = server.xverif_debug_query(
        action="expr.normalize",
        args={"signal": "top.valid"},
        output_format="json",
    )
    assert missing["error"]["code"] == "SESSION_REQUIRED"
    assert debug.calls == []
    ok = server.xverif_debug_query(
        action="expr.normalize",
        session_id="design_a",
        args={"signal": "top.valid"},
        output_format="json",
    )
    assert ok == {"ok": True, "path": "session"}
    assert debug.calls[0][1]["session_id"] == "design_a"


def test_debug_query_forbids_session_for_resource_free_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug = _RecordingDebug()
    monkeypatch.setattr(server, "debug", debug)
    monkeypatch.setattr(
        server,
        "query_session_requirement",
        lambda action, args: (
            {
                "parameter": "session_id",
                "mode": "forbidden",
                "requires": "none",
                "session_id": "forbidden",
            },
            None,
        ),
    )
    rsp = server.xverif_debug_query(
        action="actions",
        session_id="case_a",
        args={},
    )
    assert rsp["error"]["code"] == "SESSION_FORBIDDEN"
    assert debug.calls == []


def test_debug_query_rejects_unmatched_resource_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug = _RecordingDebug()
    variants = [
        {
            "name": "expression",
            "requires": "none",
            "required_args": ["expr"],
            "forbidden_args": ["signal"],
            "session_id": "forbidden",
        },
        {
            "name": "design_signal",
            "requires": "design",
            "required_args": ["signal"],
            "forbidden_args": ["expr"],
            "session_id": "required",
        },
    ]
    monkeypatch.setattr(server, "debug", debug)
    monkeypatch.setattr(
        server,
        "query_session_requirement",
        lambda action, args: (
            {"parameter": "session_id", "mode": "conditional", "variants": variants},
            None,
        ),
    )
    for args in ({}, {"expr": "a", "signal": "top.a"}):
        rsp = server.xverif_debug_query(
            action="expr.normalize",
            args=args,
            output_format="json",
        )
        assert rsp["error"]["code"] == "INVALID_RESOURCE_VARIANT"
        assert rsp["error"]["variants"] == variants
    assert debug.calls == []


def test_debug_query_rejects_unknown_action_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug = _RecordingDebug()
    monkeypatch.setattr(server, "debug", debug)
    monkeypatch.setattr(server, "query_session_requirement", lambda action, args: (None, None))
    rsp = server.xverif_debug_query(
        action="trace.x",
        session_id="case_a",
        args={"signal": "top.a", "time": "10ns"},
    )
    assert rsp["error"]["code"] == "UNKNOWN_ACTION"
    assert debug.calls == []
