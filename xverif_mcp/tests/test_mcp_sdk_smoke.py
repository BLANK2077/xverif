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


REMOVED_ENV = [
    "XVERIF_MCP_ENABLE_COMMON",
    "XVERIF_MCP_ENABLE_DEBUG",
    "XVERIF_MCP_ENABLE_COV",
    "XVERIF_MCP_ENABLE_BIT",
    "XVERIF_MCP_ENABLE_ENTRY",
    "XVERIF_MCP_ENABLE_LOC",
    "XVERIF_MCP_ENABLE_SVA",
    "XVERIF_MCP_ENABLE_MUTATION",
    "XVERIF_MCP_ENABLE_ARTIFACT_WRITE",
    "XVERIF_MCP_ARTIFACT_ROOT",
]

POLICY_ENV = REMOVED_ENV + [
    "XVERIF_MCP_BATCH_MAX_INPUT_BYTES",
    "XVERIF_MCP_BATCH_MAX_REQUESTS",
    "XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES",
]


def _server(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str] | None = None,
):
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


def test_public_defaults_register_lifecycle_and_artifact_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)

    async def _schemas():
        return {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}

    schemas = anyio.run(_schemas)
    assert "xverif_debug_session_open" in schemas
    assert "xverif_debug_session_close" in schemas
    assert "xverif_cov_session_open" in schemas
    assert "xverif_cov_session_close" in schemas
    assert "xverif_batch" in schemas
    assert "xverif_output_path" in schemas["xverif_ping"]["properties"]
    assert set(server.MCP_TOOL_POLICY.summary()) == {"batch_limits"}


def test_public_defaults_bind_session_open_without_mutation_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)
    tool = server.mcp._tool_manager.get_tool("xverif_debug_session_open")

    assert tool is not None
    assert tool.fn is server.xverif_debug_session_open


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
    assert "xverif_debug_session_kill" not in names
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
    calls = []
    guide = (
        "xdebug actions: 2. Select one, then query its schema.\n"
        "list.load: Load named waveform lists.\n"
        "trace.x_origin: Trace dynamic X origins."
    )
    server.debug.actions = lambda **kwargs: calls.append(kwargs) or {
        "ok": True,
        "summary": {
            "action_count": 2,
            "total_action_count": 2,
            "filtered": False,
            "view": "guide",
            "guide_bytes": len(guide.encode("utf-8")),
            "guide_limit_bytes": 10_000,
        },
        "data": {"guide": guide, "filters": {}},
    }
    content, _ = _call_server_tool(server, "xverif_tools")
    assert content[0].text == guide
    assert calls == [{"view": "guide"}]

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
        server._xdebug_action_guide({"ok": True, "data": {}})


def test_xverif_tools_rejects_oversized_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)
    guide = "x" * (server.XVERIF_TOOLS_MAX_BYTES + 1)
    payload = {
        "ok": True,
        "summary": {
            "action_count": 1,
            "view": "guide",
            "guide_bytes": len(guide),
            "guide_limit_bytes": server.XVERIF_TOOLS_MAX_BYTES,
        },
        "data": {"guide": guide},
    }

    with pytest.raises(RuntimeError, match="bounded guide contract"):
        server._xdebug_action_guide(payload)


def test_xverif_tools_real_runtime_guide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server(monkeypatch)
    catalog_path = Path(__file__).parents[2] / "xdebug/specs/actions/actions.yaml"
    actions = json.loads(catalog_path.read_text(encoding="utf-8"))["actions"]

    content, _ = _call_server_tool(server, "xverif_tools")
    guide = content[0].text

    assert guide.splitlines()[1:] == sorted(
        f"{entry['name']}: {entry['description_en']}" for entry in actions
    )
    assert len(guide.encode("utf-8")) <= server.XVERIF_TOOLS_MAX_BYTES


def test_loc_context_requires_explicit_log_line(monkeypatch: pytest.MonkeyPatch):
    server = _server(monkeypatch)

    async def _schema():
        tools = await server.mcp.list_tools()
        return next(tool.inputSchema for tool in tools if tool.name == "xverif_loc_context")

    schema = anyio.run(_schema)
    assert schema["properties"]["line"]["type"] == "integer"
    assert "line" in schema["required"]


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


@pytest.mark.parametrize("env_name", REMOVED_ENV)
@pytest.mark.parametrize("value", ["0", "1", "invalid", ""])
def test_removed_env_does_not_change_tools_or_schemas(monkeypatch, env_name, value):
    def schemas(server):
        async def read():
            return {tool.name: tool.inputSchema for tool in await server.mcp.list_tools()}
        return anyio.run(read)
    expected = schemas(_server(monkeypatch))
    actual = schemas(_server(monkeypatch, {env_name: value}))
    assert actual == expected
    assert {"xverif_ping", "xverif_debug_query", "xverif_cov_query", "xverif_batch",
            "xverif_bit_eval", "xverif_entry_decode", "xverif_loc_resolve",
            "xverif_sva_explain_property"} <= actual.keys()
    for schema in actual.values():
        assert {"xverif_output_path", "xverif_output_append"} <= schema["properties"].keys()


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
            {"session_id": "cov_real", "action": "code_coverage.summary",
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
    ("env_name", "invalid"),
    [
        ("XVERIF_MCP_BATCH_MAX_INPUT_BYTES", "0"),
        ("XVERIF_MCP_BATCH_MAX_REQUESTS", "-1"),
        ("XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES", "many"),
    ],
)
def test_new_policy_environment_errors_fail_server_initialization(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    invalid: str,
) -> None:
    from xverif_loop.config import ConfigError

    with pytest.raises(ConfigError, match=env_name):
        _server(
            monkeypatch,
            {env_name: invalid},
        )


@pytest.mark.parametrize(
    ("backend", "action", "args"),
    [
        ("debug", "apb.config.load", {"name": "apb0", "config": {}}),
        ("debug", "apb.export", {"name": "apb0", "output": {"path": "exports/apb0"}}),
        ("debug", "batch", {"requests": [
            {"action": "apb.export", "args": {"output": {"path": "../export"}}}]}),
        ("cov", "exclude.add", {"name": "exclusion"}),
        ("cov", "export.assert", {"output": {"path": "/outside/report.md"}}),
        ("cov", "export.assert", {"output": {"path": "relative-report"}}),
        ("cov", "export.assert", {"output": {"path": "/outside", "allow_absolute_path": True}}),
        ("cov", "exclude.csv.compile", {"output_directory": "compiled"}),
        ("cov", "exclude.csv.export", {"directory": "csv"}),
        ("cov", "exclude.csv.format", {"directory": "formatted", "write": True}),
    ],
)
def test_actions_reach_backend_without_policy_or_path_rewrite(monkeypatch, backend, action, args):
    server = _server(monkeypatch, {name: "0" for name in REMOVED_ENV})
    calls = []
    adapter = server.debug if backend == "debug" else server.cov
    monkeypatch.setattr(adapter, "query_one_shot" if action == "batch" else "query",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})
    content, _ = _call_server_tool(server, f"xverif_{backend}_query", {
        **({} if action == "batch" else {"session_id": "s0"}),
        "action": action, "args": args, "output_format": "json",
    })
    assert json.loads(content[0].text)["ok"] is True
    assert len(calls) == 1
    assert calls[0]["args"] == args


def test_tool_help_has_only_resource_policy(monkeypatch):
    content, _ = _call_tool(monkeypatch, "xverif_tool_help",
                           {"name": "xverif_sva_explain_property"})
    payload = json.loads(content[0].text)
    assert payload["ok"] is True
    assert set(payload["policy"]) == {"batch_limits"}
    assert {"group", "mutation", "artifact_write"} <= payload["tool"].keys()


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
                     "args": {"session_id": "cov_real", "action": "code_coverage.summary",
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
        {"batch_file": str(batch_file),
         "output_file": str(tmp_path / "nonexistent/results.ndjson")},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BATCH_OUTPUT_WRITE_FAILED"


@pytest.mark.parametrize("alias_kind", ["same", "hardlink", "symlink"])
def test_batch_rejects_same_input_object_through_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
):
    batch_file = tmp_path / "batch.ndjson"
    batch_file.write_text(json.dumps({"tool": "xverif_ping", "args": {}}) + "\n")
    output_file = tmp_path / "output.ndjson"
    if alias_kind == "same":
        output_file = batch_file
    elif alias_kind == "hardlink":
        os.link(batch_file, output_file)
    else:
        output_file.symlink_to(batch_file)
    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
    )
    payload = json.loads(content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "BATCH_INPUT_OUTPUT_SAME_FILE"


def test_batch_output_is_create_new_and_preserves_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch_file = tmp_path / "batch.ndjson"
    output_file = tmp_path / "output.ndjson"
    batch_file.write_text(json.dumps({"tool": "xverif_ping", "args": {}}) + "\n")
    output_file.write_text("keep\n")
    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
    )
    payload = json.loads(content[0].text)
    assert payload["error"]["code"] == "BATCH_OUTPUT_EXISTS"
    assert output_file.read_text() == "keep\n"


def test_batch_request_budget_is_checked_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch_file = tmp_path / "batch.ndjson"
    output_file = tmp_path / "output.ndjson"
    line = json.dumps({"tool": "xverif_ping", "args": {}})
    batch_file.write_text(line + "\n" + line + "\n")
    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
        {"XVERIF_MCP_BATCH_MAX_REQUESTS": "1"},
    )
    payload = json.loads(content[0].text)
    assert payload["error"]["code"] == "BATCH_REQUEST_LIMIT_EXCEEDED"
    assert not output_file.exists()


def test_batch_input_and_output_byte_budgets_leave_no_partial_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch_file = tmp_path / "batch.ndjson"
    output_file = tmp_path / "output.ndjson"
    batch_file.write_text(json.dumps({"tool": "xverif_ping", "args": {}}) + "\n")
    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
        {"XVERIF_MCP_BATCH_MAX_INPUT_BYTES": "1"},
    )
    payload = json.loads(content[0].text)
    assert payload["error"]["code"] == "BATCH_INPUT_LIMIT_EXCEEDED"
    assert not output_file.exists()

    content, _ = _call_tool(
        monkeypatch,
        "xverif_batch",
        {"batch_file": str(batch_file), "output_file": str(output_file)},
        {"XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES": "1"},
    )
    payload = json.loads(content[0].text)
    assert payload["error"]["code"] == "BATCH_OUTPUT_LIMIT_EXCEEDED"
    assert not output_file.exists()
    assert not list(tmp_path.glob(".output.ndjson.stage-*"))

@pytest.mark.parametrize("path", ["", " ", " bad", "bad ", "bad\0path"])
def test_invalid_output_path_is_a_write_failure(monkeypatch, path):
    content, _ = _call_tool(monkeypatch, "xverif_ping", {"xverif_output_path": path})
    assert content.isError
    assert json.loads(content.content[0].text)["error"]["code"] == "OUTPUT_WRITE_FAILED"


def test_relative_output_overwrites_in_server_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "response.txt"
    target.write_text("old output")
    _call_tool(monkeypatch, "xverif_ping", {"xverif_output_path": "response.txt"},
               {name: "invalid" for name in REMOVED_ENV})
    assert "pong" in target.read_text()
    assert "old output" not in target.read_text()


def test_relative_batch_output_uses_server_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requests.ndjson").write_text('{"tool":"xverif_ping","args":{}}\n')
    content, _ = _call_tool(monkeypatch, "xverif_batch", {
        "batch_file": "requests.ndjson", "output_file": "results.ndjson",
    })
    assert json.loads(content[0].text)["ok"] is True
    assert json.loads((tmp_path / "results.ndjson").read_text())["ok"] is True


@pytest.mark.parametrize("asynchronous", [False, True])
def test_output_serialization_failure_preserves_existing_file(monkeypatch, tmp_path, asynchronous):
    server = _server(monkeypatch)
    def result():
        return {"unserializable": object()}
    async def async_result():
        return result()
    wrapped = server._wrap_with_output(async_result if asynchronous else result)
    target = tmp_path / "existing.txt"
    target.write_text("preserve")
    if asynchronous:
        async def call():
            return await wrapped(xverif_output_path=str(target))
        response = anyio.run(call)
    else:
        response = wrapped(xverif_output_path=str(target))
    assert response.isError
    assert json.loads(response.content[0].text)["error"]["code"] == "OUTPUT_SERIALIZATION_FAILED"
    assert target.read_text() == "preserve"
