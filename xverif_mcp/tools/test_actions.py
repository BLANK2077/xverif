#!/usr/bin/env python3
"""逐个测试 xdebug action，通过 MCP client 调用 FastMCP server。

用法:
    conda activate xverif-mcp
    PYTHONPATH=xverif_mcp/src python xverif_mcp/tools/test_actions.py -c my_config.json

选项:
    -c, --config      指定 JSON 配置文件（必填）
    --schema-only     只测试 schema（快，不需要 FSDB）
    --runtime-only    只测试运行时调用，跳过全量 schema 扫描
    --level L1|L2|L3  测试级别（默认 all）
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
import time
from types import SimpleNamespace
from typing import Any

# Add project to path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, ROOT)

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from xverif_mcp.framing import validate_xout_text
from xverif_mcp.xdebug_contracts import query_session_requirement

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """加载 JSON 配置文件。"""
    with open(config_path) as f:
        cfg = json.load(f)
    for key in ("daidir", "fsdb"):
        value = cfg.get(key)
        if isinstance(value, str) and value:
            cfg[key] = os.path.abspath(os.path.expandvars(os.path.expanduser(value)))
    cfg.setdefault("session_name", "action_test")
    return cfg


def build_action_args(sig: str, clk: str, session_name: str) -> dict[str, dict]:
    """根据信号名构建 L2 测试用 action 参数表。"""
    list_name = f"l2_test_list_{int(time.time())}"
    return {
    "scope.list": {"path": "", "level": 1},
    "signal.resolve": {"signal": sig},
    "expr.normalize": {"expr": "a && b"},
    "protocol.handshake.inspect": {"clock": clk, "valid": sig, "ready": sig},
    "signal.anomaly.inspect": {"signals": [sig, clk], "time_range": {"begin": "0ns", "end": "200ns"}},
    "signal.xz_verify": {
        "signal": sig,
        "expected_state": "x",
        "time_range": {"begin": "0ns", "end": "200ns"},
    },
    "event.config.list": {},
    "waveform.cursor.list": {},
    "list.create": {"name": list_name, "signals": [sig]},
    "list.load": {
        "config": {
            "lists": [{
                "name": f"{list_name}_loaded",
                "signals": [sig, clk],
            }],
        },
    },
    "value.at": {
        "list": f"{list_name}_loaded",
        "times": ["1ns", "2ns"],
    },
    "event.export": {"expr": "clk == 1", "clock": clk, "signals": {"clk": clk}, "line_limit": 2},
    "trace.load": {"signal": sig},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Colors:
    """ANSI color codes — only active when stdout is a terminal."""
    _on = sys.stdout.isatty()
    GREEN = "\033[92m" if _on else ""
    RED = "\033[91m" if _on else ""
    YELLOW = "\033[93m" if _on else ""
    CYAN = "\033[96m" if _on else ""
    RESET = "\033[0m" if _on else ""
    BOLD = "\033[1m" if _on else ""


def _server_env() -> dict:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{SRC}:{ROOT}:{existing}".strip(":")
    return env


class InProcessSession:
    """Small adapter with the ClientSession.call_tool shape used below."""

    def __init__(self):
        self._server = None

    async def initialize(self) -> None:
        if "xverif_mcp.server" in sys.modules:
            self._server = importlib.reload(sys.modules["xverif_mcp.server"])
        else:
            self._server = importlib.import_module("xverif_mcp.server")

    async def call_tool(self, name: str, args: dict | None = None):
        if self._server is None:
            await self.initialize()
        result = await self._server.mcp.call_tool(name, args or {})
        content = result[0] if isinstance(result, tuple) else result
        return SimpleNamespace(content=content)

    async def close(self) -> None:
        if self._server is None:
            return
        debug = getattr(self._server, "debug", None)
        sessions = getattr(debug, "_sessions", None)
        if sessions is not None:
            sessions.close_all()
        cov = getattr(self._server, "cov", None)
        sessions = getattr(cov, "_sessions", None)
        if sessions is not None:
            sessions.close_all()


async def _call_json(session, tool: str, args: dict | None = None) -> dict:
    result = await session.call_tool(tool, args or {})
    return json.loads(result.content[0].text)


async def discover_actions(session) -> list[str]:
    data = await _call_json(session, "xverif_debug_list_actions", {})
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions or not all(isinstance(a, str) for a in actions):
        raise RuntimeError("runtime action catalog did not return compact data.actions names")
    return sorted(actions)


def _debug_query_args(
    action: str,
    args: dict,
    session_id: str,
    *,
    output_format: str = "json",
) -> dict:
    """Construct one MCP call from the canonical resource contract."""
    contract, variant = query_session_requirement(action, args)
    if contract is None:
        raise RuntimeError(f"action missing from canonical registry: {action}")
    if contract["mode"] == "conditional":
        if variant is None:
            raise RuntimeError(
                f"args do not match exactly one resource variant: {action}"
            )
        state = variant["session_id"]
    else:
        state = contract["session_id"]
    call = {"action": action, "args": args, "output_format": output_format}
    if state == "required":
        call["session_id"] = session_id
    return call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_close(fn):
    """Helper: return (session_name, daidir, fsdb) from config."""
    pass  # unused, kept for symmetry


async def _open_session(session, cfg):
    """Open session using config."""
    sn = cfg["session_name"]
    rv = await session.call_tool("xverif_debug_session_open", {
        "name": sn, "daidir": cfg["daidir"], "fsdb": cfg["fsdb"],
    })
    d = json.loads(rv.content[0].text)
    if not d.get("ok"):
        print(f"  {Colors.RED}FAIL session.open: {d.get('error')}{Colors.RESET}", flush=True)
        return False
    record = d.get("session", {})
    print(
        f"  Session '{sn}' opened (backend={record.get('backend', '?')}, "
        f"launcher={record.get('launcher', '?')})",
        flush=True,
    )
    return True


async def _close_session(session, cfg):
    result = await session.call_tool(
        "xverif_debug_session_close",
        {"session_id": cfg["session_name"]},
    )
    data = json.loads(result.content[0].text)
    if not data.get("ok"):
        raise RuntimeError(
            "failed to close managed session {}: {}".format(
                cfg["session_name"], data.get("error")
            )
        )


# ---------------------------------------------------------------------------
# Test runners
# ---------------------------------------------------------------------------


async def test_all_schemas(session) -> tuple[int, int]:
    """L1: 用 xdebug_schema tool 逐个验证全部 action 的 request/response schema。"""
    actions = await discover_actions(session)
    print(f"\n{Colors.BOLD}=== L1: Schema 验证 ({len(actions) * 2} tests) ==={Colors.RESET}", flush=True)
    passed = 0
    failed = 0

    for kind in ["request", "response"]:
        for action in actions:
            request = {"action": action, "kind": kind}
            if kind == "response":
                request["view"] = "response"
            result = await session.call_tool("xverif_debug_get_schema", {
                **request,
            })
            data = json.loads(result.content[0].text)

            if data.get("ok"):
                passed += 1
                print(f"  {Colors.GREEN}OK{Colors.RESET}  schema {kind:8s} {action}", flush=True)
            else:
                failed += 1
                err = data.get("error", {}).get("message", str(data))
                print(f"  {Colors.RED}FAIL{Colors.RESET} schema {kind:8s} {action}: {err}", flush=True)

    return passed, failed


async def test_l2_basic(session: ClientSession, cfg: dict, action_args: dict) -> tuple[int, int]:
    """L2: 对已知 args 的 action 进行基础调用测试。"""
    sn = cfg["session_name"]
    print(f"\n{Colors.BOLD}=== L2: 基础调用 ({len(action_args)} actions) ==={Colors.RESET}")
    passed = 0
    failed = 0

    if not await _open_session(session, cfg):
        return 0, 1

    for action, args in action_args.items():
        result = await session.call_tool(
            "xverif_debug_query",
            _debug_query_args(action, args, sn),
        )
        data = json.loads(result.content[0].text)
        if isinstance(data, dict) and data.get("ok") is True:
            passed += 1
            print(f"  {Colors.GREEN}OK{Colors.RESET}  (ok ) {action} {json.dumps(args)}")
        else:
            failed += 1
            error = data.get("error") if isinstance(data, dict) else {"response_type": type(data).__name__}
            print(f"  {Colors.RED}FAIL{Colors.RESET} {action}: {error}")

    await _close_session(session, cfg)
    return passed, failed


async def test_with_signal(session: ClientSession, cfg: dict, signal: str) -> tuple[int, int]:
    """L3: 对已知信号进行完整数据验证。"""
    sn, clk = cfg["session_name"], cfg["clock"]
    print(f"\n{Colors.BOLD}=== L3: 信号验证 (signal={signal}) ==={Colors.RESET}")
    passed = 0
    failed = 0

    if not await _open_session(session, cfg):
        return 0, 1

    list_name = f"l3_signal_context_{int(time.time())}"
    l3_actions = [
        ("value.at", {"signal": signal, "time": "1ns", "clock": clk}),
        ("list.load", {
            "config": {
                "lists": [{
                    "name": list_name,
                    "signals": [signal, clk],
                }],
            },
        }),
        ("value.at", {
            "list": list_name,
            "times": ["1ns", "2ns"],
            "clock": clk,
        }),
        ("signal.statistics", {"signal": signal}),
        ("counter.statistics", {"clock": clk, "time_range": {"begin": "0ns", "end": "200ns"}, "vld": signal, "cnt": signal}),
        ("signal.changes", {"signal": signal, "time_range": {"begin": "0ns", "end": "200ns"}, "mode": "summary"}),
        ("signal.stability", {"signal": signal, "time_range": {"begin": "0ns", "end": "200ns"}}),
        ("signal.canonicalize", {"signal": signal}),
        ("trace.driver", {"signal": signal}),
        ("trace.active_driver", {"signal": signal, "time": "1ns"}),
        ("expr.eval_at", {"expr": "sig == 1", "time": "1ns", "signals": {"sig": signal}, "clock": clk}),
        ("event.find", {"expr": "clk == 1", "clock": clk, "signals": {"clk": clk}, "mode": "all", "line_limit": 3}),
        ("window.verify", {"conditions": [
            {"expr": "sig == 1"}
        ], "signals": {"sig": signal}, "time_range": {"begin": "0ns", "end": "1us"}, "clock": clk}),
    ]

    for action, args in l3_actions:
        result = await session.call_tool(
            "xverif_debug_query",
            _debug_query_args(action, args, sn),
        )
        data = json.loads(result.content[0].text)
        if isinstance(data, dict) and data.get("ok") is True:
            passed += 1
            print(f"  {Colors.GREEN}OK{Colors.RESET} {action}")
        else:
            failed += 1
            error = data.get("error") if isinstance(data, dict) else {"response_type": type(data).__name__}
            print(f"  {Colors.RED}FAIL{Colors.RESET} {action}: {error}")

    # XOUT format test
    print(f"\n{Colors.CYAN}--- 输出格式测试 ---{Colors.RESET}")
    result = await session.call_tool(
        "xverif_debug_query",
        _debug_query_args(
            "value.at",
            {"signal": signal, "time": "1ns", "clock": clk},
            sn,
            output_format="xout",
        ),
    )
    xout_text = result.content[0].text
    try:
        validate_xout_text(xout_text)
        xout_ok = (
            xout_text.startswith("@xdebug.value.at.v1\n")
            and signal in xout_text
            and "pointer\tkind\tvalue" not in xout_text
        )
    except ValueError as exc:
        xout_ok = False
        xout_error = type(exc).__name__
    if xout_ok:
        print(f"  {Colors.GREEN}OK{Colors.RESET} xout_format: compact token-efficient text.")
        passed += 1
    else:
        print(
            f"  {Colors.RED}FAIL{Colors.RESET} "
            f"xout_format: {locals().get('xout_error', 'text contract')}"
        )
        failed += 1

    await _close_session(session, cfg)
    return passed, failed


async def discover_signal(session: ClientSession, cfg: dict) -> str | None:
    """尝试在真实数据中发现可用信号。优先用 config 中的 signal/clock。"""
    sn = cfg["session_name"]
    if not await _open_session(session, cfg):
        raise RuntimeError("failed to open managed discovery session {}".format(sn))

    # Strategy 0: try config signal/clock first
    for key in ("signal", "clock"):
        sig = cfg.get(key)
        if sig:
            result = await session.call_tool(
                "xverif_debug_query",
                _debug_query_args(
                    "value.at",
                    {"signal": sig, "time": "1ns", "clock": cfg.get("clock", sig)},
                    sn,
                ),
            )
            d = json.loads(result.content[0].text)
            if isinstance(d, dict) and d.get("ok"):
                await _close_session(session, cfg)
                return sig

    # Strategy 1: scope.list
    result = await session.call_tool(
        "xverif_debug_query",
        _debug_query_args(
            "scope.list",
            {"path": "", "level": 1},
            sn,
        ),
    )
    d = json.loads(result.content[0].text)
    if isinstance(d, dict):
        scopes = d.get("data", {}).get("scopes", d.get("data", {}).get("signals_preview", []))
        if scopes:
            name = scopes[0] if isinstance(scopes[0], str) else scopes[0].get("name", "")
            if name:
                await _close_session(session, cfg)
                return name

    await _close_session(session, cfg)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test xdebug actions via MCP server")
    parser.add_argument("-c", "--config", required=True, help="JSON config file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--schema-only",
        action="store_true",
        help="Only run L1 schema tests",
    )
    mode.add_argument(
        "--runtime-only",
        action="store_true",
        help="Run L2/L3 runtime smoke without the exhaustive L1 schema scan",
    )
    parser.add_argument("--level", choices=["L1", "L2", "L3", "all"], default="all",
                        help="Test level (default: all)")
    parser.add_argument("--transport", choices=["inprocess", "stdio"], default="inprocess",
                        help="MCP transport for this smoke test (default: inprocess)")
    args = parser.parse_args(argv)
    if args.runtime_only and args.level == "L1":
        parser.error("--runtime-only cannot be combined with --level L1")
    return args


async def main():
    args = parse_args()

    cfg = load_config(args.config)
    print(f"Config: daidir={cfg['daidir']}  fsdb={cfg['fsdb']}  signal={cfg.get('signal')}  clock={cfg.get('clock')}", flush=True)

    async def run_suite(session) -> tuple[int, int]:
        total_pass = 0
        total_fail = 0

        # --- L1: Schema (always run) ---
        if not args.runtime_only and (
            args.level in ("L1", "all") or args.schema_only
        ):
            p, f = await test_all_schemas(session)
            total_pass += p
            total_fail += f

        if args.schema_only or args.level == "L1":
            pass  # skip L2/L3
        elif args.level in ("L2", "all"):
            # --- L2: Basic invocation ---
            base_session_name = cfg["session_name"]
            l2_cfg = {**cfg, "session_name": f"{base_session_name}_l2"}
            action_args = build_action_args(cfg["signal"], cfg["clock"], l2_cfg["session_name"])
            p, f = await test_l2_basic(session, l2_cfg, action_args)
            total_pass += p
            total_fail += f

            # --- Signal discovery ---
            print(f"\n{Colors.CYAN}Discovering signal...{Colors.RESET}", flush=True)
            discover_cfg = {**cfg, "session_name": f"{base_session_name}_discover"}
            signal = await discover_signal(session, discover_cfg)
            if signal:
                print(f"  {Colors.GREEN}Found: {signal}{Colors.RESET}", flush=True)

                # --- L3: Full verification ---
                if args.level in ("L3", "all"):
                    l3_cfg = {**cfg, "session_name": f"{base_session_name}_l3"}
                    p, f = await test_with_signal(session, l3_cfg, signal)
                    total_pass += p
                    total_fail += f
            else:
                print(f"  {Colors.YELLOW}No signal found, skipping L3{Colors.RESET}", flush=True)

        return total_pass, total_fail

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xverif_mcp.server"],
        env=_server_env(),
        cwd=ROOT,
    )

    started = time.time()

    if args.transport == "stdio":
        stdio_timeout = False
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=30)
                    print(f"{Colors.CYAN}Connected to xverif-mcp FastMCP server (stdio){Colors.RESET}", flush=True)
                    total_pass, total_fail = await run_suite(session)
        except* TimeoutError:
            stdio_timeout = True
        if stdio_timeout:
            print(
                f"{Colors.RED}FAIL{Colors.RESET} stdio initialize timed out after 30s; "
                "use the default inprocess transport for schema smoke, or debug the MCP SDK stdio transport separately.",
                flush=True,
            )
            return 2
    else:
        session = InProcessSession()
        try:
            await session.initialize()
            print(f"{Colors.CYAN}Connected to xverif-mcp FastMCP server (inprocess){Colors.RESET}", flush=True)
            total_pass, total_fail = await run_suite(session)
        finally:
            await session.close()

    # Summary
    elapsed = time.time() - started
    print(f"\n{Colors.BOLD}=== 结果: {total_pass} passed, {total_fail} failed ({elapsed:.1f}s) ==={Colors.RESET}", flush=True)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
