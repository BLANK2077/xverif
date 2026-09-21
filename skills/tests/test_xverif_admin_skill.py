from pathlib import Path

from skill_test_utils import assert_markdown_links


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/xverif-admin"


def _skill_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in SKILL.rglob("*.md"))


def test_admin_links_and_scope() -> None:
    assert_markdown_links(SKILL)
    text = _skill_text()
    for term in ("SDK-free", "LSF", "transport", "session", "不自动"):
        assert term in text
    assert "action-reference.md" not in text


def test_admin_routes_the_ssh_remote_mcp_entrypoint() -> None:
    """Adding a program means routing it; `mcp_ssh` was once documented but unrouted.

    AGENTS.md requires SKILL.md, references and agents/openai.yaml to move together when a
    CLI or MCP entrypoint changes. The reference section exists, so this asserts that the
    skill's frontmatter and routing table actually lead to it.
    """
    main = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = main.split("---", 2)[1]
    assert "mcp_ssh" in frontmatter
    routing = main.split("## 路由", 1)[1].split("## ", 1)[0]
    assert "远端 ssh backend" in routing

    metadata = (SKILL / "agents/openai.yaml").read_text(encoding="utf-8")
    assert "mcp_ssh" in metadata


def test_admin_states_the_remote_session_location_correctly() -> None:
    """The remote session lives on the EDA host; a shared home directory is not required.

    An earlier revision of `references/mcp/overview.md` claimed the two machines must share
    `$HOME`, which contradicted the implementation (the bridge does not forward `HOME`) and
    the root README. Pin the corrected claim and forbid the old wording.
    """
    reference = (SKILL / "references/mcp/overview.md").read_text(encoding="utf-8")
    assert "不需要共享 `$HOME`" in reference
    assert "两机 `$HOME` 必须指向同一份共享存储" not in reference
    assert "cluster file transport" in reference

    text = _skill_text()
    assert "两机 `$HOME` 必须指向同一份共享存储" not in text


def test_admin_check_description_matches_no_value_disclosure() -> None:
    """`--check` prints variable names and counts; it must never be documented as printing values."""
    reference = (SKILL / "references/mcp/overview.md").read_text(encoding="utf-8")
    assert "不打印任何变量取值" in reference
    # The retired wording described the output as "帧大小", which the command does not print.
    assert "帧大小" not in reference
