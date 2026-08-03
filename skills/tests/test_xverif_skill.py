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
    assert {entry["status"] for entry in specs["actions"]} <= {
        "stable", "experimental",
    }
    expected = {entry["name"] for entry in specs["actions"]}
    generated = (SKILL / "references/generated/xdebug-actions.md").read_text()
    documented = set(re.findall(r"^\| `([^`]+)` \|", generated, re.MULTILINE))
    assert documented == expected
    assert len(expected) == 73


def test_canonical_discoverability_has_no_generated_fallback_contract() -> None:
    specs = json.loads(
        (ROOT / "xdebug/specs/actions/actions.yaml").read_text(encoding="utf-8")
    )
    filler = {
        "Tasks outside this action's documented contract.",
        "不要把本 action 用作不属于其已声明业务对象的查询；当前没有更近的公开替代 action。",
    }
    for entry in specs["actions"]:
        assert {"use_for", "do_not_use_for", "preferred_alternative"}.isdisjoint(entry)
        assert entry["use_when"], entry["name"]
        assert entry["do_not_use_when"], entry["name"]
        assert isinstance(entry["alternatives"], list), entry["name"]
        assert not ((set(entry["use_when"]) | set(entry["do_not_use_when"])) & filler)


def test_expr_normalize_resource_variants_are_canonical() -> None:
    specs = json.loads(
        (ROOT / "xdebug/specs/actions/actions.yaml").read_text(encoding="utf-8")
    )
    entry = next(item for item in specs["actions"] if item["name"] == "expr.normalize")
    assert entry["resource_variants"] == [
        {
            "name": "expression", "requires": "none", "required_args": ["expr"],
            "forbidden_args": ["signal", "line_limit", "no_statement_only", "role"],
        },
        {
            "name": "design_signal", "requires": "design",
            "required_args": ["signal"], "forbidden_args": ["expr"],
        },
    ]


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
            contract_kind = "response" if isinstance(payload.get("ok"), bool) else "request"
            schema = json.loads((ROOT / "xdebug/schemas/v1/actions" /
                                 f"{action}.{contract_kind}.schema.json").read_text())
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
        "scope.roots", "scope.list", "trace.driver", "trace.load",
        "trace.active_driver", "trace.active_driver_chain", "value.at",
        "list.load", "value.at(list", "times=[",
        "signal.changes", "signal.statistics", "signal.xz_verify", "event.find", "verify.conditions",
        "window.verify", "signal.anomaly.inspect", "signal.sampled_pulse.inspect", "protocol.handshake.inspect",
        "stream.config.load", "stream.config.get", "stream.describe", "stream.query",
        "axi.config.load", "apb.config.load", "list.export", "xwaveform", "nwave.rc.generate",
        "xdebug/configs/", "xdebug/signals.md", "全量 xdebug action 索引",
    }
    missing = sorted(item for item in required if item not in text)
    assert not missing, missing
    assert "不限 AXI/APB" in text
    assert "图片不是唯一证据" in text


def test_xdebug_discovery_and_loaded_config_workflow_are_mandatory() -> None:
    main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    mcp = (SKILL / "references/surfaces/mcp.md").read_text(encoding="utf-8")
    combined = main + "\n" + mcp
    for term in (
        "先且只调用一次 `xverif_tools`", "完整读取", "list.load",
        "stream.config.load", "axi.config.load", "apb.config.load",
        "`signal`、`list`、`apb`、`stream`、`axi`", "recommended_actions",
        "不为多个信号或多个时间点反复调用 `xverif_batch`",
    ):
        assert term in combined
    assert "value.batch_at" not in "\n".join(
        path.read_text(encoding="utf-8") for path in SKILL.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".yml", ".json"}
    )


def test_xout_policy_is_token_first_and_has_no_transport_markers() -> None:
    text = "\n".join(
        (SKILL / relative).read_text(encoding="utf-8")
        for relative in (
            "SKILL.md", "references/core/output-formats.md",
            "references/surfaces/cli.md", "references/surfaces/mcp.md",
        )
    )
    assert "token-efficient XOUT" in text
    assert "反解析" in text and "重编码" in text
    assert "XOUT_BEGIN/XOUT_END" in text or (
        "XOUT_BEGIN" in text and "XOUT_END" in text
    )
    assert "添加 `XOUT_BEGIN` / `XOUT_END`" in text


def test_xverif_skill_contains_only_canonical_action_names() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in SKILL.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py", ".yaml", ".yml", ".json"}
    )
    removed = {
        "cursor.set", "cursor.get", "cursor.list", "cursor.use", "cursor.delete",
        "apb.cursor", "axi.cursor", "detect_abnormal", "handshake.inspect",
        "sampled_pulse.inspect", "list.diff", "stream.show", "trace.x",
        "rc.generate", "source.context", "function_coverage.summary",
        "function_coverage.holes", "export.function_coverage",
    }
    found = sorted(name for name in removed if f"`{name}`" in text)
    assert not found, found


def test_expr_normalize_docs_publish_the_canonical_parser_contract() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in SKILL.rglob("*.md"))
    assert "string_fallback" not in text
    assert "`deterministic_syntax_parser`" in text
    assert "`syntax_validated`" in text


def test_mcp_surface_documents_conditional_session_contract() -> None:
    text = (SKILL / "references/surfaces/mcp.md").read_text(encoding="utf-8")
    for term in ("session_contract", "requires:none", "禁止", "expr.normalize", "design session"):
        assert term in text


def test_only_xverif_is_generic_trigger() -> None:
    main = (SKILL / "SKILL.md").read_text()
    assert "唯一通用隐式入口" in main
    for name in ("xverif-admin", "x-npi", "xwiki"):
        assert name in main


def test_xout_policy_is_token_first_and_forbids_transport_markers() -> None:
    policy = (SKILL / "references/core/output-formats.md").read_text(
        encoding="utf-8"
    )
    main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    surfaces = "\n".join(
        (SKILL / "references/surfaces" / name).read_text(encoding="utf-8")
        for name in ("cli.md", "mcp.md")
    )

    for term in (
        "AI/LLM 上下文效率",
        "token-efficient XOUT",
        "稳定字段编程",
        "不反解析",
        "不重编码",
        "XOUT_BEGIN/XOUT_END",
    ):
        assert term in policy + "\n" + main + "\n" + surfaces
    assert "便于人读只是附带收益" in policy
    assert "统一 pointer" not in policy


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
