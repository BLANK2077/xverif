from __future__ import annotations

from pathlib import Path


XDEBUG = Path(__file__).resolve().parents[2]
ROOT = XDEBUG.parent


def test_error_renderer_and_handler_notes_use_available_values_only() -> None:
    renderer = (XDEBUG / "src/api/text_response_builder.cpp").read_text(
        encoding="utf-8"
    )
    assert 'error.contains("available_values")' in renderer
    assert 'error.contains("allowed_values")' not in renderer

    scope_roots = (
        XDEBUG / "src/engine/service/actions/waveform/scope_roots.cpp"
    ).read_text(encoding="utf-8")
    assert "choose args.source from available_values" in scope_roots
    assert "choose args.source from allowed_values" not in scope_roots


def test_public_guidance_distinguishes_error_and_catalog_value_fields() -> None:
    paths = (
        ROOT / "doc/agents/xdebug/coding-standards.md",
        ROOT / "doc/agents/xdebug/schema-validation.md",
        ROOT / "skills/xverif/references/xdebug/action-reference.md",
        ROOT / "skills/xverif/references/capabilities/xdebug.md",
        ROOT / "skills/xverif/agents/openai.yaml",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "available_values" in text, path
        assert "allowed_values" in text, path
        assert "catalog" in text.lower(), path


def test_every_catalog_action_has_actionable_alternatives() -> None:
    import json

    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(encoding="utf-8")
    )["actions"]
    names = {entry["name"] for entry in catalog}
    for entry in catalog:
        alternatives = entry.get("alternatives")
        assert alternatives, entry["name"]
        for alternative in alternatives:
            assert alternative["action"] in names, (entry["name"], alternative)
            assert alternative["action"] != entry["name"], alternative
            assert alternative["when"].strip(), alternative
