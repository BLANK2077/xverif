from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import anyio
import jsonschema

import xverif_mcp.server as server
from skill_test_utils import assert_markdown_links, fenced_json
from xcov.schemas import schema_for_action
from xverif_loop.wrapper import validate_method_params


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "xverif"


def _tools() -> dict[str, object]:
    async def collect() -> dict[str, object]:
        return {tool.name: tool for tool in await server.mcp.list_tools()}
    return anyio.run(collect)


def test_links_and_all_references_are_reachable() -> None:
    assert_markdown_links(SKILL)
    text = "\n".join(path.read_text(encoding="utf-8") for path in SKILL.rglob("*.md"))
    for reference in sorted((SKILL / "references").rglob("*.md")):
        assert reference.name in text or str(reference.relative_to(SKILL)) in text, reference


def test_generated_action_inventory_matches_canonical_registry() -> None:
    specs = json.loads((ROOT / "xdebug/specs/actions/actions.yaml").read_text())
    expected = {entry["name"] for entry in specs["actions"] if entry["status"] != "removed"}
    generated = (SKILL / "references/generated/xdebug-actions.md").read_text()
    documented = set(re.findall(r"^\| `([^`]+)` \|", generated, re.MULTILINE))
    assert documented == expected
    assert len(expected) == 74


def test_generated_references_are_current() -> None:
    subprocess.run(
        [sys.executable, str(SKILL / "scripts/generate_references.py"), "--check"],
        cwd=ROOT, check=True,
    )


def test_native_and_mcp_examples_validate() -> None:
    tools = _tools()
    validated = 0
    for path, payload in fenced_json(SKILL):
        if payload.get("api_version") == "xdebug.v1":
            action = payload["action"]
            schema = json.loads((ROOT / "xdebug/schemas/v1/actions" /
                                 f"{action}.request.schema.json").read_text())
            jsonschema.Draft202012Validator(schema).validate(payload)
            validated += 1
        elif payload.get("api_version") == "xcov.v1":
            jsonschema.Draft202012Validator(
                schema_for_action(payload["action"], "request")
            ).validate(payload)
            validated += 1
        elif isinstance(payload.get("tool"), str):
            tool = tools[payload["tool"]]
            jsonschema.Draft202012Validator(tool.inputSchema).validate(payload.get("args", {}))
            validated += 1
        elif isinstance(payload.get("method"), str):
            validate_method_params(payload["method"], payload.get("params", {}))
            validated += 1
    assert validated >= 20


def test_xdebug_main_workflow_has_required_decisions_and_routes() -> None:
    text = (SKILL / "references/capabilities/xdebug.md").read_text()
    required = {
        "scope.roots", "scope.list", "trace.driver", "trace.load", "source.context",
        "trace.active_driver", "trace.active_driver_chain", "value.at", "value.batch_at",
        "signal.changes", "signal.statistics", "signal.xz_verify", "event.find", "verify.conditions",
        "window.verify", "detect_abnormal", "sampled_pulse.inspect", "handshake.inspect",
        "stream.config.load", "stream.query", "list.export", "xwaveform", "rc.generate",
        "xdebug/configs/", "xdebug/signals.md", "全量 xdebug action 索引",
    }
    missing = sorted(item for item in required if item not in text)
    assert not missing, missing
    assert "不限 AXI/APB" in text
    assert "图片不是唯一证据" in text


def test_only_xverif_is_generic_trigger() -> None:
    main = (SKILL / "SKILL.md").read_text()
    assert "唯一通用隐式入口" in main
    for name in ("xverif-admin", "x-npi", "xwiki"):
        assert name in main


def test_routing_goldens_cover_capability_boundaries() -> None:
    routing = (SKILL / "specs/routing.yaml").read_text()
    for prompt, capability in (
        ("ready 为什么在 1024ns 拉低", "xdebug"),
        ("data[47:32] 等于多少", "xbit"),
        ("merged.vdb 中 uart 的 toggle hole", "xcov"),
        ("把这 100 个信号在 1ms 内的活动率生成 CSV", "x-npi"),
        ("观察一段长窗口内多个 stream 的 stall 分布", "xdebug"),
    ):
        assert prompt in routing
        block = routing.split(f"prompt: {prompt}", 1)[1].split("- prompt:", 1)[0]
        assert f"capability: {capability}" in block


def test_public_component_inventory_is_routed() -> None:
    main = (SKILL / "SKILL.md").read_text()
    for component in ("xdebug", "xcov", "xbit", "xentry", "xloc", "xsva", "xwaveform"):
        assert component in main
