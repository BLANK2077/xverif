"""Focused tests for the MCP action smoke script."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "test_actions.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("test_actions_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, args: dict | None = None):
        args = args or {}
        self.calls.append((name, args))
        if name == "xverif_debug_list_actions":
            payload = {
                "ok": True,
                "data": {"actions": ["counter.statistics", "value.at"]},
            }
        elif name == "xverif_debug_get_schema":
            payload = {
                "ok": True,
                "data": {"action": args["action"], "kind": args["kind"]},
            }
        elif name == "xverif_debug_session_open":
            payload = {"ok": True, "session": {"backend": "xdebug", "launcher": "direct"}}
        else:
            payload = {"ok": True}
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


def test_schema_smoke_uses_runtime_action_catalog():
    script = _load_script()
    session = FakeSession()

    passed, failed = asyncio.run(script.test_all_schemas(session))

    assert (passed, failed) == (4, 0)
    schema_calls = [
        args for name, args in session.calls
        if name == "xverif_debug_get_schema"
    ]
    assert schema_calls == [
        {"action": "counter.statistics", "kind": "request"},
        {"action": "value.at", "kind": "request"},
        {"action": "counter.statistics", "kind": "response", "view": "response"},
        {"action": "value.at", "kind": "response", "view": "response"},
    ]


def test_runtime_only_is_distinct_from_schema_only_and_l1():
    script = _load_script()

    runtime = script.parse_args(["-c", "config.json", "--runtime-only"])
    assert runtime.runtime_only is True
    assert runtime.schema_only is False
    assert runtime.level == "all"

    with pytest.raises(SystemExit):
        script.parse_args([
            "-c",
            "config.json",
            "--runtime-only",
            "--schema-only",
        ])
    with pytest.raises(SystemExit):
        script.parse_args([
            "-c",
            "config.json",
            "--runtime-only",
            "--level",
            "L1",
        ])


def test_action_discovery_rejects_malformed_catalog_without_fallback():
    script = _load_script()

    class MalformedCatalogSession(FakeSession):
        async def call_tool(self, name: str, args: dict | None = None):
            if name == "xverif_debug_list_actions":
                payload = {"ok": True, "data": {"actions": []}}
                return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])
            return await super().call_tool(name, args)

    with pytest.raises(RuntimeError, match="runtime action catalog"):
        asyncio.run(script.discover_actions(MalformedCatalogSession()))


def test_open_session_does_not_send_removed_reuse_arg():
    script = _load_script()
    session = FakeSession()
    cfg = {
        "session_name": "smoke_session",
        "daidir": "simv.daidir",
        "fsdb": "waves.fsdb",
    }

    assert asyncio.run(script._open_session(session, cfg)) is True

    open_calls = [
        args for name, args in session.calls
        if name == "xverif_debug_session_open"
    ]
    assert open_calls == [{
        "name": "smoke_session",
        "daidir": "simv.daidir",
        "fsdb": "waves.fsdb",
    }]


def test_query_args_follow_canonical_resource_variant():
    script = _load_script()

    expression = script._debug_query_args(
        "expr.normalize",
        {"expr": "a && b"},
        "case_a",
    )
    design_signal = script._debug_query_args(
        "expr.normalize",
        {"signal": "top.a"},
        "case_a",
    )

    assert expression == {
        "action": "expr.normalize",
        "args": {"expr": "a && b"},
        "output_format": "json",
    }
    assert design_signal == {
        "action": "expr.normalize",
        "session_id": "case_a",
        "args": {"signal": "top.a"},
        "output_format": "json",
    }
