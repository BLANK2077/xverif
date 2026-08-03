from __future__ import annotations

from pathlib import Path
import json
import re

from xcov.schemas import schema_actions, stdio_control_actions


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = [
    ROOT / "README.md",
    ROOT / "xdebug/README.md",
    ROOT / "xcov/README.md",
    ROOT / "xverif_mcp/README.md",
    ROOT / "xverif_mcp/src/xverif_mcp/server.py",
]


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
    assert "skills/xverif/SKILL.md" in root
    assert "skills/xverif-admin/SKILL.md" in root


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
