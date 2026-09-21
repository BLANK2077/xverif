from __future__ import annotations

from pathlib import Path
import json
import re

import anyio
import jsonschema

import xverif_mcp.server as server

from xcov.schemas import schema_actions, stdio_control_actions


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = [
    ROOT / "README.md",
    ROOT / "xdebug/README.md",
    ROOT / "xcov/README.md",
    ROOT / "xverif_mcp/README.md",
    ROOT / "xverif_mcp/src/xverif_mcp/server.py",
]

PUBLIC_JSON_SURFACES = [
    ROOT / "README.md",
    ROOT / "xdebug/README.md",
    ROOT / "xdebug/docs/AGENT_GUIDE.md",
    ROOT / "xverif_mcp/README.md",
    *sorted((ROOT / "skills/xverif").rglob("*.md")),
]
FENCED_JSON_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def _mcp_tools() -> dict[str, object]:
    async def collect() -> dict[str, object]:
        return {tool.name: tool for tool in await server.mcp.list_tools()}
    return anyio.run(collect)


def test_removed_recommendations_do_not_appear_in_public_docs() -> None:
    forbidden = {
        "cov.holes", "xverif_cov_raw_request", "xverif_cov_session_use",
        "xverif_wave_value_at", "xverif_design_trace_driver", "按需 include",
        "skills/xverif-cli", "skills/xverif-mcp", "trace.drivers",
    }
    text = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC)
    found = sorted(term for term in forbidden if term in text)
    assert not found, found


def test_public_skill_links_target_new_layout() -> None:
    root = (ROOT / "README.md").read_text()
    root_zh = (ROOT / "README.zh-CN.md").read_text()
    assert "skills/xverif/SKILL.md" in root
    assert "skills/xverif-admin/SKILL.md" in root
    assert "skills/xsimdebug/SKILL.md" in root
    assert "skills/xsimdebug/SKILL.md" in root_zh


def test_component_readme_action_names_exist_in_current_catalogs() -> None:
    xdebug_specs = json.loads((ROOT / "xdebug/specs/actions/actions.yaml").read_text())
    xdebug_actions = {entry["name"] for entry in xdebug_specs["actions"]}
    xdebug_documented = set(re.findall(
        r'"action"\s*:\s*"([^"]+)"', (ROOT / "xdebug/README.md").read_text()
    ))
    assert xdebug_documented <= xdebug_actions

    xcov_actions = set(schema_actions()) | set(stdio_control_actions())
    xcov_documented = set(re.findall(
        r'"action"\s*:\s*"([^"]+)"', (ROOT / "xcov/README.md").read_text()
    ))
    assert xcov_documented <= xcov_actions


def test_all_complete_public_json_fences_parse_and_validate_action_tokens() -> None:
    """Every strict JSON fence is parseable; complete calls use live contracts.

    JSON fragments belong in a differently labelled fence (for example
    ``jsonc``). This test intentionally does not scan arbitrary dotted inline
    words as action names.
    """
    xdebug_specs = json.loads(
        (ROOT / "xdebug/specs/actions/actions.yaml").read_text(encoding="utf-8")
    )
    xdebug_actions = {entry["name"] for entry in xdebug_specs["actions"]}
    tools = _mcp_tools()
    checked_calls = 0
    for path in PUBLIC_JSON_SURFACES:
        text = path.read_text(encoding="utf-8")
        for index, raw in enumerate(FENCED_JSON_RE.findall(text), start=1):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AssertionError(
                    f"{path.relative_to(ROOT)} JSON fence {index} is not "
                    f"complete strict JSON: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                continue
            if payload.get("api_version") == "xdebug.v1":
                action = payload.get("action")
                assert action in xdebug_actions, (
                    path.relative_to(ROOT), index, action
                )
                kind = "response" if isinstance(payload.get("ok"), bool) else "request"
                schema_path = (
                    ROOT / "xdebug/schemas/v1/actions" /
                    f"{action}.{kind}.schema.json"
                )
                jsonschema.Draft202012Validator(
                    json.loads(schema_path.read_text(encoding="utf-8"))
                ).validate(payload)
                checked_calls += 1
            elif isinstance(payload.get("tool"), str):
                tool_name = payload["tool"]
                assert tool_name in tools, (
                    path.relative_to(ROOT), index, tool_name
                )
                jsonschema.Draft202012Validator(
                    tools[tool_name].inputSchema
                ).validate(payload.get("args", {}))
                checked_calls += 1
    assert checked_calls >= 20


# The root README pair is one document in two languages. These two assertions
# keep them structurally aligned: a section added to one side, or a
# documentation link listed only on one side, fails here instead of drifting.
README_SECTION_MAP = {
    "Tool overview": "工具概览",
    "Recommended shell entry points": "推荐 Shell 入口",
    "Synchronizing agent environment variables": "同步 Agent 环境变量",
    "Requirements": "环境要求",
    "Build and test": "构建与测试",
    "Documentation": "文档入口",
    "Star History": "Star History",
}


def _readme_sections(text: str) -> list[str]:
    return re.findall(r"(?m)^##\s+(.+?)\s*$", text)


def _documentation_links(text: str) -> list[str]:
    match = re.search(r"(?ms)^##\s*(?:Documentation|文档入口)\s*\n(.*)\Z", text)
    assert match is not None, "README pair must expose a documentation section"
    return re.findall(r"\]\(([^)]+)\)", match.group(1))


def test_readme_pair_keeps_matching_sections_and_documentation_links() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    english_sections = _readme_sections(english)
    chinese_sections = _readme_sections(chinese)
    assert len(english_sections) == len(chinese_sections), (
        english_sections, chinese_sections,
    )
    expected_english = list(README_SECTION_MAP)
    assert english_sections == expected_english, (
        "README.md sections changed; update README_SECTION_MAP and "
        "README.zh-CN.md together", english_sections,
    )
    assert chinese_sections == [
        README_SECTION_MAP[name] for name in expected_english
    ], chinese_sections

    english_links = _documentation_links(english)
    chinese_links = _documentation_links(chinese)
    assert len(english_links) == len(set(english_links)), english_links
    assert len(chinese_links) == len(set(chinese_links)), chinese_links
    assert set(english_links) == set(chinese_links), (
        "documentation links drifted between README.md and README.zh-CN.md",
        sorted(set(english_links) - set(chinese_links)),
        sorted(set(chinese_links) - set(english_links)),
    )
