"""Real MCP stdio wire tests backed by xdebug and xcov databases."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = ROOT / "xverif_mcp" / "src"


def _payload(result) -> dict:
    assert result.content and result.content[0].type == "text"
    return json.loads(result.content[0].text)


def test_real_mcp_wire_reaches_xdebug_and_xcov(
    tmp_path: Path,
    xverif_fixture,
) -> None:
    combined = xverif_fixture("xdebug.active_driver") / "out"
    comprehensive_vdb = xverif_fixture("xcov.comprehensive") / "comprehensive.vdb"
    exclusion_vdb = xverif_fixture("xcov.exclusion") / "exclusion.vdb"
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    pythonpath = os.pathsep.join(
        value for value in (str(MCP_SRC), str(ROOT), env.get("PYTHONPATH", ""))
        if value
    )
    env.update({
        "HOME": str(home),
        "PYTHONPATH": pythonpath,
        "XVERIF_HOME": str(ROOT),
        "XVERIF_MCP_BACKEND": "direct",
        "XVERIF_MCP_LOG_DIR": str(tmp_path / "mcp-logs"),
        "XVERIF_LOOP_LOG_DIR": str(tmp_path / "loop-logs"),
        "XVERIF_TEST_TMPDIR": str(tmp_path / "state"),
        "XVERIF_XCOV_EXPORT_ROOTS": str(tmp_path),
    })
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xverif_mcp.server"],
        env=env,
        cwd=str(ROOT),
    )

    async def run() -> None:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "xverif"
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {
                    "xverif_debug_session_open",
                    "xverif_debug_query",
                    "xverif_cov_session_open",
                    "xverif_cov_query",
                } <= names

                opened = _payload(await session.call_tool(
                    "xverif_debug_session_open",
                    {
                        "name": "wire_debug",
                        "daidir": str(combined / "simv.daidir"),
                        "fsdb": str(combined / "waves.fsdb"),
                    },
                ))
                assert opened["ok"] is True, opened
                traced = _payload(await session.call_tool(
                    "xverif_debug_query",
                    {
                        "session_id": "wire_debug",
                        "action": "trace.active_driver",
                        "args": {
                            "signal": "active_driver_tb.u_dut.q",
                            "time": "20ns",
                        },
                        "output_format": "json",
                    },
                ))
                assert traced["ok"] is True, traced
                assert traced["data"]["paths"]
                closed = _payload(await session.call_tool(
                    "xverif_debug_session_close", {"session_id": "wire_debug"}
                ))
                assert closed["ok"] is True

                opened = _payload(await session.call_tool(
                    "xverif_cov_session_open",
                    {"name": "wire_cov", "vdb": str(comprehensive_vdb)},
                ))
                assert opened["ok"] is True, opened
                summary = _payload(await session.call_tool(
                    "xverif_cov_query",
                    {
                        "session_id": "wire_cov",
                        "action": "code_coverage.summary",
                        "args": {"group_by": "metric"},
                        "output_format": "json",
                    },
                ))
                assert summary["ok"] is True, summary
                assert {row["metric"] for row in summary["data"]["items"]} >= {
                    "line", "toggle", "branch", "condition", "fsm"
                }
                exported = _payload(await session.call_tool(
                    "xverif_cov_query",
                    {
                        "session_id": "wire_cov",
                        "action": "export.code_coverage",
                        "args": {
                            "scopes": ["top.u_core1"], "metrics": ["toggle"],
                            "output": {
                                "path": str(tmp_path / "wire-coverage"),
                                "allow_absolute_path": True,
                            },
                        },
                        "output_format": "json",
                    },
                ))
                assert exported["ok"] is True, exported
                gap_path = Path(exported["data"]["items"][0]["directory"]) / "toggle.json"
                gap_payload = json.loads(gap_path.read_text(encoding="utf-8"))
                gap_id = gap_payload["gaps"][0]["gap_id"]
                added = _payload(await session.call_tool(
                    "xverif_cov_query",
                    {
                        "session_id": "wire_cov", "action": "exclude.add",
                        "args": {"exports": [{"path": str(gap_path), "items": [{
                            "gap_id": gap_id, "reason": "真实 MCP stdio gap 排除验证",
                        }]}]}, "output_format": "json",
                    },
                ))
                assert added["ok"] is True, added
                assert added["data"]["items"][0]["status"] == "changed"
                csv_exported = _payload(await session.call_tool(
                    "xverif_cov_query",
                    {
                        "session_id": "wire_cov",
                        "action": "exclude.csv.export",
                        "args": {
                            "directory": str(tmp_path / "wire-exclusions"),
                            "allow_absolute_path": True,
                        },
                        "output_format": "json",
                    },
                ))
                assert csv_exported["ok"] is True, csv_exported
                el_exported = _payload(await session.call_tool(
                    "xverif_cov_query",
                    {
                        "session_id": "wire_cov",
                        "action": "export.exclude",
                        "args": {"output": {
                            "path": str(tmp_path / "wire-exclusions" / "merged.el"),
                            "allow_absolute_path": True,
                        }},
                        "output_format": "json",
                    },
                ))
                assert el_exported["ok"] is True, el_exported
                assert _payload(await session.call_tool(
                    "xverif_cov_session_close", {"session_id": "wire_cov"}
                ))["ok"] is True

                debug_sessions = _payload(
                    await session.call_tool("xverif_debug_session_list", {})
                )
                cov_sessions = _payload(
                    await session.call_tool("xverif_cov_session_list", {})
                )
                assert debug_sessions.get("sessions", []) == []
                assert cov_sessions.get("sessions", []) == []

    anyio.run(run)
