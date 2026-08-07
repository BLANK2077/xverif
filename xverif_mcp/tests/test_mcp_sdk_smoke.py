"""FastMCP registration tests for xverif-mcp."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest

XDEBUG_DIR = Path(__file__).resolve().parents[2] / "xdebug"
sys.path = [
    path for path in sys.path
    if Path(path or os.getcwd()).resolve() != XDEBUG_DIR
]

sys.modules.pop("mcp", None)
pytest.importorskip("mcp")


POLICY_ENV = [
    "XVERIF_MCP_ENABLE_COMMON",
    "XVERIF_MCP_ENABLE_DEBUG",
    "XVERIF_MCP_ENABLE_COV",
    "XVERIF_MCP_ENABLE_BIT",
    "XVERIF_MCP_ENABLE_ENTRY",
    "XVERIF_MCP_ENABLE_LOC",
    "XVERIF_MCP_ENABLE_SVA",
]


def _server(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str] | None = None):
    for name in POLICY_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in (overrides or {}).items():
        monkeypatch.setenv(name, value)
    if "xverif_mcp.server" in sys.modules:
        return importlib.reload(sys.modules["xverif_mcp.server"])
    return importlib.import_module("xverif_mcp.server")


def _tool_names(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str] | None = None) -> set[str]:
    server = _server(monkeypatch, overrides)

    async def _run() -> set[str]:
        tools = await server.mcp.list_tools()
        return {tool.name for tool in tools}

    return anyio.run(_run)


def _call_tool(monkeypatch: pytest.MonkeyPatch, name: str, args: dict | None = None,
               overrides: dict[str, str] | None = None):
    server = _server(monkeypatch, overrides)

    async def _run():
        result = await server.mcp.call_tool(name, args or {})
        if isinstance(result, tuple):
            return result
        return result, None

    return anyio.run(_run)


def _call_server_tool(server, name: str, args: dict | None = None):
    async def _run():
        result = await server.mcp.call_tool(name, args or {})
        return result if isinstance(result, tuple) else (result, None)

    return anyio.run(_run)


def test_mcp_server_initialize(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)
    assert server.mcp.name == "xverif"


def test_stateful_cleanup_calls_debug_and_cov(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)
    calls: list[str] = []

    class DummyAdapter:
        def __init__(self, name: str) -> None:
            self.name = name

        def close_all(self) -> None:
            calls.append(self.name)

    monkeypatch.setattr(server, "debug", DummyAdapter("debug"))
    monkeypatch.setattr(server, "cov", DummyAdapter("cov"))

    server._cleanup_stateful_sessions()

    assert calls == ["debug", "cov"]


def test_stateful_cleanup_logs_and_continues_after_failure(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)
    calls: list[str] = []
    events: list[dict] = []

    class FailingAdapter:
        mode = "direct"

        def close_all(self) -> None:
            calls.append("debug")
            raise RuntimeError("close failed")

    class HealthyAdapter:
        def close_all(self) -> None:
            calls.append("cov")

    monkeypatch.setattr(server, "debug", FailingAdapter())
    monkeypatch.setattr(server, "cov", HealthyAdapter())
    class CaptureLogger:
        def try_server(self, phase, ok, **fields):
            events.append({"phase": phase, "ok": ok, **fields})

    monkeypatch.setattr(server, "MCP_LOGGER", CaptureLogger())

    server._cleanup_stateful_sessions()

    assert calls == ["debug", "cov"]
    assert events == [{
        "phase": "mcp.shutdown.cleanup_failed",
        "ok": False,
        "backend": "direct",
        "error_type": "RuntimeError",
    }]


def test_lifespan_cleanup_runs_on_exit(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)
    calls: list[str] = []

    class DummyAdapter:
        def __init__(self, name: str) -> None:
            self.name = name

        def close_all(self) -> None:
            calls.append(self.name)

    monkeypatch.setattr(server, "debug", DummyAdapter("debug"))
    monkeypatch.setattr(server, "cov", DummyAdapter("cov"))

    async def _run() -> None:
        async with server._mcp_lifespan(server.mcp):
            assert calls == []

    anyio.run(_run)

    assert calls == ["debug", "cov"]


def test_mcp_tools_list(monkeypatch: pytest.MonkeyPatch):
    """tools/list must include all expected read-only tool names by default."""
    names = _tool_names(monkeypatch)
    assert "xverif_ping" in names
    assert "xverif_debug_query" in names
    assert "xverif_debug_session_open" in names
    assert "xverif_cov_session_open" in names
    assert "xverif_cov_query" in names
    assert "xverif_debug_list_actions" in names
    assert "xverif_debug_get_schema" in names
    assert "xverif_debug_session_list" in names
    assert "xverif_debug_session_doctor" in names
    assert "xverif_debug_session_use" not in names
    assert "xverif_debug_session_close" in names
    assert "xverif_debug_session_kill" in names
    assert "xverif_debug_session_gc" in names
    assert "xverif_cov_session_list" in names
    assert "xverif_cov_session_doctor" in names
    assert "xverif_cov_session_close" in names
    assert "xverif_cov_session_kill" in names
    assert "xverif_cov_session_gc" in names
    assert "xverif_session_open" not in names
    assert "xverif_session_list" not in names
    assert "xverif_session_use" not in names
    assert "xverif_session_close" not in names
    assert "xverif_debug_raw_request" not in names
    assert "xverif_cov_raw_request" not in names
    assert "xverif_wave_value_at" not in names
    assert "xverif_wave_changes" not in names
    assert "xverif_wave_generate_rc" not in names
    assert "xverif_waveform_render_list" not in names
    assert "xverif_design_trace_driver" not in names
    assert "xverif_tools" in names
    assert "xverif_bit_eval" in names
    assert "xverif_entry_decode" in names
    assert "xverif_loc_resolve" in names
    assert "xverif_sva_explain_property" in names
    assert all(not name.startswith("xverif_" + "context") for name in names)


def test_cov_tools_use_session_id_contract(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)

    async def _schemas():
        return {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}

    schemas = anyio.run(_schemas)
    for name in (
        "xverif_cov_query", "xverif_cov_session_doctor",
        "xverif_cov_session_close", "xverif_cov_session_kill",
    ):
        properties = schemas[name]["properties"]
        assert "session_id" in properties
        assert "session" not in properties
        assert "name" not in properties
    query_properties = schemas["xverif_cov_query"]["properties"]
    assert "limits" not in query_properties
    assert "output" not in query_properties


def test_debug_lifecycle_uses_only_required_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)

    async def _schemas():
        return {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}

    schemas = anyio.run(_schemas)
    for name in (
        "xverif_debug_session_doctor",
        "xverif_debug_session_close",
        "xverif_debug_session_kill",
    ):
        schema = schemas[name]
        assert schema["additionalProperties"] is False
        assert "session_id" in schema["required"]
        assert "name" not in schema["properties"]


def test_public_finite_parameters_publish_enum_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)

    async def _schemas():
        return {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}

    schemas = anyio.run(_schemas)
    expected = {
        ("xverif_debug_get_schema", "kind"): ["request", "response"],
        ("xverif_debug_get_schema", "view"): ["mcp", "response"],
        ("xverif_debug_query", "output_format"): ["xout", "json", "envelope"],
        ("xverif_cov_get_schema", "kind"): ["request", "response"],
        ("xverif_cov_query", "output_format"): ["xout", "json", "envelope"],
        ("xverif_bit_convert", "state"): ["2", "4"],
        ("xverif_bit_convert", "output_format"): ["xout", "json"],
        ("xverif_bit_eval", "state"): ["2", "4"],
        ("xverif_bit_slice", "state"): ["2", "4"],
        ("xverif_bit_check", "state"): ["2", "4"],
        ("xverif_entry_decode", "output_format"): ["xout", "json"],
        ("xverif_sva_parse_property", "emit"): [
            "surface-ir", "sequence-ir", "timeline-ir",
        ],
        ("xverif_sva_explain_property", "output_format"): [
            "xout", "json", "markdown",
        ],
    }
    for (tool_name, parameter), values in expected.items():
        assert schemas[tool_name]["properties"][parameter]["enum"] == values


def test_public_tool_argument_models_reject_type_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    server = _server(monkeypatch)
    tool = server.mcp._tool_manager.get_tool("xverif_bit_slice")
    assert tool.fn_metadata.arg_model.model_config["extra"] == "forbid"
    assert tool.fn_metadata.arg_model.model_config["strict"] is True

    async def _run() -> None:
        with pytest.raises(ToolError, match="valid integer"):
            await server.mcp.call_tool(
                "xverif_bit_slice",
                {"value": "8'hff", "msb": "7", "lsb": 0},
            )

    anyio.run(_run)


def test_debug_query_exposes_conditional_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)

    async def _schema():
        tools = await server.mcp.list_tools()
        return next(tool.inputSchema for tool in tools if tool.name == "xverif_debug_query")

    schema = anyio.run(_schema)
    assert "session_id" not in schema["required"]
    assert "action" in schema["required"]
    assert "requires:none" in schema["properties"]["session_id"]["description"]


def test_xverif_tools_returns_complete_runtime_action_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)
    server.debug.actions = lambda verbose=False: {
        "ok": True,
        "data": {"actions": [
            {
                "name": "list.load",
                "status": "stable",
                "description_en": "Load named waveform lists.",
                "use_when": ["Need a reusable set of key waveform signals."],
            },
            {
                "name": "trace.x_origin",
                "status": "experimental",
                "description_en": "Trace dynamic X origins.",
                "use_when": ["Need evidence for the first unknown source."],
            },
        ]},
    }
    content, _ = _call_server_tool(server, "xverif_tools")
    guide = content[0].text
    assert guide.startswith("xdebug actions (2 total).")
    assert "list.load [stable]" in guide
    assert "trace.x_origin [experimental]" in guide

    async def _schema():
        tools = await server.mcp.list_tools()
        return next(tool.inputSchema for tool in tools if tool.name == "xverif_tools")

    schema = anyio.run(_schema)
    assert set(schema["properties"]) == {
        "xverif_output_path", "xverif_output_append",
    }


def test_mcp_instructions_are_bounded_and_route_xdebug_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)
    assert len(server.INSTRUCTIONS.encode("utf-8")) <= 2048
    assert len(server.INSTRUCTIONS.split("\n\n", 1)[0]) <= 512
    assert "call xverif_tools once" in server.INSTRUCTIONS
    assert "signal/list/apb/stream/axi selector" in server.INSTRUCTIONS
    assert "recommended_actions" in server.INSTRUCTIONS
    assert "Never auto-retry/reopen/fallback" in server.INSTRUCTIONS


def test_action_guide_fails_closed_on_malformed_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)
    with pytest.raises(RuntimeError, match="malformed"):
        server._xdebug_action_guide({"ok": True, "data": {"actions": []}})
    with pytest.raises(RuntimeError, match="violates"):
        server._xdebug_action_guide({
            "ok": True,
            "data": {"actions": [{
                "name": "actions",
                "status": "stable",
                "description_en": "List actions.",
            }]},
        })


def test_loc_context_requires_explicit_log_line(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)

    async def _schema():
        tools = await server.mcp.list_tools()
        return next(tool.inputSchema for tool in tools if tool.name == "xverif_loc_context")

    schema = anyio.run(_schema)
    assert schema["properties"]["line"]["type"] == "integer"
    assert "line" in schema["required"]


def test_session_open_tools_expose_run_manifest_and_forward_it(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)
    calls = []

    class DummyAdapter:
        def session_open(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "session": kwargs}

    monkeypatch.setattr(server, "debug", DummyAdapter())
    monkeypatch.setattr(server, "cov", DummyAdapter())

    async def _run():
        schemas = {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}
        for name in ("xverif_debug_session_open", "xverif_cov_session_open"):
            assert "run_manifest" in schemas[name]["properties"]
        await server.mcp.call_tool("xverif_debug_session_open", {
            "name": "debug_manifest", "fsdb": "waves.fsdb",
            "run_manifest": "debug-run-manifest.json",
        })
        await server.mcp.call_tool("xverif_cov_session_open", {
            "name": "cov_manifest", "vdb": "merged.vdb",
            "run_manifest": "cov-run-manifest.json",
        })

    anyio.run(_run)
    assert calls == [
        {"name": "debug_manifest", "daidir": None, "fsdb": "waves.fsdb",
         "run_manifest": "debug-run-manifest.json", "queue": None, "resource": None},
        {"name": "cov_manifest", "vdb": "merged.vdb",
         "run_manifest": "cov-run-manifest.json", "queue": None, "resource": None},
    ]


def test_mcp_ping_call(monkeypatch: pytest.MonkeyPatch):
    """Calling xverif_ping returns one strict JSON object containing pong."""
    content, structured = _call_tool(monkeypatch, "xverif_ping")
    assert json.loads(content[0].text) == {"ok": True, "result": "pong"}
    assert structured is None


def test_debug_list_actions_verbose_maps_to_native_catalog_projection(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = []
    server = _server(monkeypatch)
    monkeypatch.setattr(
        server.XverifDebugAdapter,
        "actions",
        lambda self, **kwargs: calls.append(kwargs) or {"ok": True},
    )

    content, _ = _call_tool(monkeypatch, "xverif_debug_list_actions", {"verbose": True})

    assert json.loads(content[0].text)["ok"] is True
    assert calls == [{"verbose": True, "category": None, "requires": None,
                      "purposes": None, "keyword": None}]


def test_debug_list_actions_forwards_catalog_filters(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = []
    server = _server(monkeypatch)
    monkeypatch.setattr(
        server.XverifDebugAdapter,
        "actions",
        lambda self, **kwargs: calls.append(kwargs) or {"ok": True},
    )
    content, _ = _call_tool(monkeypatch, "xverif_debug_list_actions", {
        "category": ["waveform"], "requires": ["waveform"],
        "purposes": ["query"], "keyword": "AXI",
    })
    assert json.loads(content[0].text)["ok"] is True
    assert calls == [{"verbose": False, "category": ["waveform"],
                      "requires": ["waveform"], "purposes": ["query"],
                      "keyword": "AXI"}]


def test_tool_group_disable_sva(monkeypatch: pytest.MonkeyPatch):
    env = {"XVERIF_MCP_ENABLE_SVA": "0"}
    names = _tool_names(monkeypatch, env)
    assert "xverif_sva_explain_property" not in names
    assert "xverif_debug_query" in names

    server = _server(monkeypatch, env)
    server.debug.actions = lambda verbose=False: {
        "ok": True,
        "data": {"actions": [{
            "name": "actions",
            "status": "stable",
            "description_en": "List the public xdebug action catalog.",
            "use_when": ["Need runtime action discovery."],
        }]},
    }
    content, _ = _call_server_tool(server, "xverif_tools")
    assert "actions [stable]" in content[0].text


def test_tool_group_disable_debug(monkeypatch: pytest.MonkeyPatch):
    names = _tool_names(monkeypatch, {"XVERIF_MCP_ENABLE_DEBUG": "0"})
    assert "xverif_debug_query" not in names
    assert "xverif_debug_session_open" not in names
    assert "xverif_wave_value_at" not in names
    assert "xverif_waveform_render_list" not in names
    assert "xverif_cov_query" in names
    assert "xverif_bit_eval" in names


def test_tool_group_disable_cov(monkeypatch: pytest.MonkeyPatch):
    names = _tool_names(monkeypatch, {"XVERIF_MCP_ENABLE_COV": "0"})
    assert "xverif_cov_query" not in names
    assert "xverif_cov_session_open" not in names
    assert "xverif_debug_query" in names


def _resolve_smoke_test_vdb() -> str:
    xverif_home = os.environ.get("XVERIF_HOME") or str(
        Path(__file__).resolve().parents[2]
    )
    candidates = [
        os.path.join(xverif_home, "xcov", "fixtures", "comprehensive", "out", "comprehensive.vdb"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    pytest.skip("comprehensive VDB not found; run: pytest --xverif-prepare xcov.comprehensive")


def test_cov_session_real_lifecycle(monkeypatch: pytest.MonkeyPatch):
    """通过真实 xcov --stdio-loop 子进程测试 session 生命周期."""
    overrides = {
        "XVERIF_HOME": str(Path(__file__).resolve().parents[2]),
        "XVERIF_MCP_BACKEND": "direct",
    }
    test_vdb = _resolve_smoke_test_vdb()
    server = _server(monkeypatch, overrides)

    async def _run():
        opened = await server.mcp.call_tool(
            "xverif_cov_session_open",
            {"name": "cov_real", "vdb": test_vdb},
        )
        queried_json = await server.mcp.call_tool(
            "xverif_cov_query",
            {"session_id": "cov_real", "action": "code_coverage.holes",
             "args": {"metrics": ["toggle", "branch"], "limits": {"max_items": 1}},
             "output_format": "json"},
        )
        queried_xout = await server.mcp.call_tool(
            "xverif_cov_query",
            {"session_id": "cov_real", "action": "code_coverage.summary",
             "args": {"group_by": "metric"},
             "output_format": "xout"},
        )
        closed = await server.mcp.call_tool(
            "xverif_cov_session_close",
            {"session_id": "cov_real"},
        )
        return opened, queried_json, queried_xout, closed

    opened, queried_json, queried_xout, _ = anyio.run(_run)
    opened_payload = json.loads(opened[0].text)
    queried_payload = json.loads(queried_json[0].text)
    queried_xout_text = queried_xout[0].text
    assert opened_payload["ok"] is True
    assert opened_payload["session"]["state"] == "alive"
    assert queried_payload["summary"]["returned_count"] == 1
    assert queried_xout_text.startswith("@xcov.code_coverage.summary.v1")
    assert "XOUT_BEGIN" not in queried_xout_text
    assert "XOUT_END" not in queried_xout_text


@pytest.mark.parametrize(
    ("env_name", "missing", "present"),
    [
        ("XVERIF_MCP_ENABLE_BIT", "xverif_bit_eval", "xverif_entry_decode"),
        ("XVERIF_MCP_ENABLE_ENTRY", "xverif_entry_decode", "xverif_bit_eval"),
        ("XVERIF_MCP_ENABLE_LOC", "xverif_loc_resolve", "xverif_bit_eval"),
    ],
)
def test_tool_group_disable_stateless_groups(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    missing: str,
    present: str,
):
    names = _tool_names(monkeypatch, {env_name: "0"})
    assert missing not in names
    assert present in names


def test_tool_group_disable_common(monkeypatch: pytest.MonkeyPatch):
    names = _tool_names(monkeypatch, {"XVERIF_MCP_ENABLE_COMMON": "0"})
    assert "xverif_ping" not in names
    assert "xverif_tools" not in names
    assert "xverif_tool_help" not in names
    assert "xverif_debug_query" in names


def test_invalid_bool_policy_fails_closed_with_typed_config_error(
    monkeypatch: pytest.MonkeyPatch,
):
    from xverif_loop.config import ConfigError

    with pytest.raises(ConfigError, match="XVERIF_MCP_ENABLE_SVA"):
        _server(monkeypatch, {"XVERIF_MCP_ENABLE_SVA": "maybe"})


def test_tool_help_disabled_tool_is_hidden(monkeypatch: pytest.MonkeyPatch):
    content, _ = _call_tool(
        monkeypatch,
        "xverif_tool_help",
        {"name": "xverif_sva_explain_property"},
        {"XVERIF_MCP_ENABLE_SVA": "0"},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "TOOL_NOT_ENABLED"


def test_output_path_in_tool_schema(monkeypatch: pytest.MonkeyPatch):
    """xverif_ping schema must expose xverif_output_path and xverif_output_append."""
    server = _server(monkeypatch)

    async def _run():
        tools = await server.mcp.list_tools()
        ping = next(t for t in tools if t.name == "xverif_ping")
        schema = ping.inputSchema
        props = schema.get("properties", {})
        assert "xverif_output_path" in props
        assert "xverif_output_append" in props

    anyio.run(_run)


def test_output_path_writes_response(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Calling a tool with xverif_output_path writes the response to that file."""
    output_file = tmp_path / "rsp.txt"
    content, _ = _call_tool(
        monkeypatch,
        "xverif_ping",
        {"xverif_output_path": str(output_file)},
    )
    assert "pong" in content[0].text.lower()
    assert output_file.exists()
    assert "pong" in output_file.read_text().lower()


def test_output_path_append(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """xverif_output_append=True appends instead of overwriting."""
    output_file = tmp_path / "rsp.txt"
    output_file.write_text("existing\n")
    _call_tool(monkeypatch, "xverif_ping",
               {"xverif_output_path": str(output_file), "xverif_output_append": True})
    text = output_file.read_text()
    assert text.startswith("existing\n")
    assert "pong" in text.lower()


def test_output_path_does_not_affect_response(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Not passing xverif_output_path has no effect on normal response."""
    content, _ = _call_tool(monkeypatch, "xverif_ping", {})
    assert "pong" in content[0].text.lower()


def test_output_path_invalid_dir_returns_structured_failure(monkeypatch: pytest.MonkeyPatch):
    """A requested output file is part of the tool contract."""
    content, _ = _call_tool(
        monkeypatch,
        "xverif_ping",
        {"xverif_output_path": "/nonexistent/dir/rsp.txt"},
    )
    assert content.isError is True
    payload = json.loads(content.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "OUTPUT_WRITE_FAILED"
    assert payload["error"]["output_path"] == "/nonexistent/dir/rsp.txt"
    assert "data" not in payload
    assert content.structuredContent is None


def test_batch_real_lifecycle(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """xverif_batch with real cov session + ping + bit_eval in one file."""
    batch_file = tmp_path / "batch.ndjson"
    output_file = tmp_path / "results.ndjson"

    overrides = {
        "XVERIF_HOME": str(Path(__file__).resolve().parents[2]),
        "XVERIF_MCP_BACKEND": "direct",
    }
    test_vdb = _resolve_smoke_test_vdb()
    server = _server(monkeypatch, overrides)

    batch_file.write_text("\n".join([
        json.dumps({"tool": "xverif_cov_session_open",
                     "args": {"name": "cov_real", "vdb": test_vdb}}),
        json.dumps({"tool": "xverif_cov_query",
                     "args": {"session_id": "cov_real", "action": "code_coverage.holes",
                              "args": {"metrics": ["line"], "limits": {"max_items": 2}},
                              "output_format": "json"}}),
        json.dumps({"tool": "xverif_cov_session_close",
                     "args": {"session_id": "cov_real"}}),
        json.dumps({"tool": "xverif_ping", "args": {}}),
        json.dumps({"tool": "xverif_bit_eval",
                     "args": {"expr": "2 + 3"}}),
    ]) + "\n")

    content, _ = _call_server_tool(
        server,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["total"] == 5
    assert payload["ok_count"] == 5
    assert payload["failed_count"] == 0

    lines = [json.loads(l) for l in output_file.read_text().splitlines() if l]
    assert len(lines) == 5
    assert all(r["ok"] for r in lines)


def test_batch_format_errors(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Invalid JSON and missing tool field are written as errors, not executed."""
    batch_file = tmp_path / "batch.ndjson"
    output_file = tmp_path / "results.ndjson"

    overrides = {
        "XVERIF_HOME": str(Path(__file__).resolve().parents[2]),
        "XVERIF_MCP_BACKEND": "direct",
    }

    batch_file.write_text("\n".join([
        "not json at all",
        json.dumps({"args": {"expr": "1+1"}}),  # missing tool
        json.dumps({"tool": "xverif_bit_eval", "args": "1+1"}),
        json.dumps({"tool": "xverif_no_such_tool", "args": {}}),
        json.dumps({"tool": "xverif_ping", "args": {}}),
    ]) + "\n")

    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
        overrides,
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert payload["total"] == 5
    assert payload["ok_count"] == 1
    assert payload["failed_count"] == 4

    lines = [json.loads(l) for l in output_file.read_text().splitlines() if l]
    assert len(lines) == 5
    assert lines[0]["tool"] is None
    assert lines[0]["ok"] is False
    assert lines[0]["error"]["code"] == "INVALID_JSON"
    assert lines[0]["line_number"] == 1
    assert lines[1]["tool"] is None
    assert lines[1]["ok"] is False
    assert lines[1]["error"]["code"] == "INVALID_BATCH_REQUEST"
    assert lines[1]["line_number"] == 2
    assert lines[2]["tool"] == "xverif_bit_eval"
    assert lines[2]["ok"] is False
    assert lines[2]["error"]["code"] == "INVALID_BATCH_ARGUMENTS"
    assert lines[2]["line_number"] == 3
    assert lines[3]["tool"] == "xverif_no_such_tool"
    assert lines[3]["ok"] is False
    assert lines[3]["line_number"] == 4
    assert lines[4]["tool"] == "xverif_ping"
    assert lines[4]["ok"] is True
    assert lines[4]["line_number"] == 5


def test_batch_accepts_nonempty_compact_text_without_parsing_xout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)

    def plain_pong() -> Any:
        return "pong"

    def at_prefixed_text() -> Any:
        return "@looks.structured.v1\nbut is intentionally compact text\n"

    server.mcp.add_tool(plain_pong, name="test_plain_pong")
    server.mcp.add_tool(at_prefixed_text, name="test_at_prefixed_text")

    async def _run():
        return (
            await server._execute_one("test_plain_pong", {}),
            await server._execute_one("test_at_prefixed_text", {}),
        )

    pong, at_text = anyio.run(_run)
    assert pong[0] is True and pong[1] is None and pong[3] == "pong"
    assert at_text[0] is True and at_text[1] is None
    assert at_text[3].startswith("@looks.structured.v1")


def test_batch_file_not_found(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """xverif_batch on a nonexistent file returns FILE_NOT_FOUND error."""
    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": "/nonexistent/batch.ndjson",
         "output_file": str(tmp_path / "out.ndjson")},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "FILE_NOT_FOUND"


def test_batch_output_file_failure_is_explicit(tmp_path, monkeypatch: pytest.MonkeyPatch):
    batch_file = tmp_path / "batch.ndjson"
    batch_file.write_text(json.dumps({"tool": "xverif_ping", "args": {}}) + "\n")
    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": "/nonexistent/dir/results.ndjson"},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BATCH_OUTPUT_WRITE_FAILED"
