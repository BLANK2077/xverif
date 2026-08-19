#!/usr/bin/env python3
"""Generate checked-in xverif references from canonical runtime metadata."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills" / "xverif"
ACTION_SPECS = ROOT / "xdebug" / "specs" / "actions" / "actions.yaml"
ACTION_OUTPUT = SKILL / "references" / "generated" / "xdebug-actions.md"
EXAMPLES = SKILL / "specs" / "examples.yaml"
SURFACE_OUTPUT = SKILL / "references" / "generated" / "surface-examples.md"


def _public_snippet(payload: dict, style: str) -> str:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if style == "json":
        return "```json\n" + rendered + "\n```"
    if style == "shell":
        return "printf '%s\\n' '" + rendered + "' | xdebug -"
    raise ValueError(f"unknown public snippet format: {style}")


def public_snippet_outputs(source: dict) -> dict[Path, str]:
    snippets = source.get("public_snippets", [])
    if not isinstance(snippets, list):
        raise ValueError(f"{EXAMPLES} public_snippets must be a list")
    outputs: dict[Path, str] = {}
    for entry in snippets:
        if not isinstance(entry, dict):
            raise ValueError(f"{EXAMPLES} public snippet must be an object")
        target = ROOT / entry["target"]
        source_path = ROOT / entry["source"]
        action = entry["action"]
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if payload.get("action") != action:
            raise ValueError(f"{source_path}: expected action {action}")
        text = outputs.get(target, target.read_text(encoding="utf-8"))
        marker_style = entry.get("marker_style", "html")
        if marker_style == "html":
            begin = f"<!-- xdebug-example:{action}:begin -->"
            end = f"<!-- xdebug-example:{action}:end -->"
        elif marker_style == "text":
            begin = f"# xdebug-example:{action}:begin"
            end = f"# xdebug-example:{action}:end"
        else:
            raise ValueError(
                f"{EXAMPLES}: unknown marker_style {marker_style!r}"
            )
        pattern = re.compile(
            r"(?m)^[ \t]*" + re.escape(begin)
            + r"\n.*?\n[ \t]*" + re.escape(end) + r"[ \t]*$",
            re.DOTALL,
        )
        matches = pattern.findall(text)
        if len(matches) != 1:
            raise ValueError(
                f"{target}: expected one marker pair for action {action}, "
                f"found {len(matches)}"
            )
        body = _public_snippet(payload, entry["format"])
        indent = " " * int(entry.get("indent", 0))
        body = "\n".join(indent + line for line in body.splitlines())
        replacement = indent + begin + "\n" + body + "\n" + indent + end
        # Use a callable replacement so the literal ``\\n`` in the shell
        # printf format is not interpreted by re.sub's replacement parser.
        text = pattern.sub(lambda _match: replacement, text)
        outputs[target] = text
    return outputs


def _required(entry: dict) -> str:
    variants = entry.get("resource_variants")
    if variants is not None:
        if not isinstance(variants, list) or not variants:
            raise ValueError(
                f"{entry.get('name', '<unknown>')} resource_variants must be non-empty"
            )
        return "; ".join(
            "{} (requires {}; required {}; forbids {})".format(
                variant["name"],
                variant["requires"],
                "/".join(variant["required_args"]),
                "/".join(variant["forbidden_args"]),
            )
            for variant in variants
        )
    parts = list(entry.get("required_args", []))
    groups = entry.get("required_arg_groups", [])
    if groups:
        parts.extend("one of " + "/".join(group) for group in groups)
    return ", ".join(parts) or "以 action schema 为准"


def _requires(entry: dict) -> str:
    variants = entry.get("resource_variants")
    if variants is None:
        return str(entry.get("requires", "-"))
    return "conditional: " + "; ".join(
        f"{variant['name']}={variant['requires']}" for variant in variants
    )


def _discoverability(entry: dict) -> tuple[list[str], list[str], list[dict]]:
    use_when = entry.get("use_when")
    do_not_use_when = entry.get("do_not_use_when")
    alternatives = entry.get("alternatives")
    if (
        not isinstance(use_when, list)
        or not use_when
        or not isinstance(do_not_use_when, list)
        or not do_not_use_when
        or not isinstance(alternatives, list)
    ):
        raise ValueError(
            f"{entry.get('name', '<unknown>')} has incomplete discoverability metadata"
        )
    return use_when, do_not_use_when, alternatives


def action_reference() -> str:
    payload = json.loads(ACTION_SPECS.read_text(encoding="utf-8"))
    lines = [
        "# xdebug 全量 Action 索引",
        "",
        "本文件由 `skills/xverif/scripts/generate_references.py` 从 canonical action specs 生成。",
        "用途是保证所有能力可发现；精确参数以 runtime catalog、action-specific schema 和 checked-in example 为准。",
        "",
        "| Action | Status | Category | Requires | Purposes | Use when | Do not use when | Alternatives | Required inputs | 中文说明 | English description | Request schema | Example |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    entries = payload["actions"]
    for entry in entries:
        use_when, do_not_use_when, alternatives = _discoverability(entry)
        request_schema = entry.get("schemas", {}).get("request")
        schema = "xdebug/" + request_schema if request_schema else "-"
        examples = entry.get("examples", {}).get("request", [])
        example = "xdebug/" + examples[0] if examples else "-"
        lines.append(
            f"| `{entry['name']}` | {entry.get('status', '-')} | {entry.get('category', '-')} | "
            f"{_requires(entry)} | {', '.join(entry.get('purposes', [])) or '-'} | "
            f"{'; '.join(use_when)} | "
            f"{'; '.join(do_not_use_when)} | "
            f"{json.dumps(alternatives, ensure_ascii=False)} | "
            f"{_required(entry)} | {entry.get('description_zh', '-')} | {entry.get('description_en', '-')} | "
            f"`{schema}` | `{example}` |"
        )
    lines.extend([
        "",
        f"共 {len(entries)} 个当前公开 action。主流程见 [xdebug capability](../capabilities/xdebug.md)。",
        "",
    ])
    return "\n".join(lines)


def surface_examples() -> str:
    source = yaml.safe_load(EXAMPLES.read_text(encoding="utf-8"))
    examples = source.get("examples", []) if isinstance(source, dict) else []
    if not examples or not isinstance(examples[0], dict):
        raise ValueError(f"{EXAMPLES} must contain at least one example object")
    example = examples[0]
    action = str(example["action"])
    session = str(example["session"])
    args = example["args"]
    if not isinstance(args, dict):
        raise ValueError(f"{EXAMPLES} example args must be an object")
    native = {"api_version": "xdebug.v1", "action": action,
              "target": {"session_id": session}, "args": args}
    mcp = {"tool": "xverif_debug_query", "args": {
        "session_id": session, "action": action, "args": args}}
    lsf = native
    blocks = [
        "# 生成的 Surface 示例", "",
        f"Canonical source: `{EXAMPLES.relative_to(ROOT)}`。", "",
    ]
    for title, value in (("CLI", native), ("MCP", mcp), ("SDK-free LSF CLI", lsf)):
        blocks.extend([f"## {title}", "", "```json",
                       json.dumps(value, indent=2, ensure_ascii=False), "```", ""])
    return "\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = yaml.safe_load(EXAMPLES.read_text(encoding="utf-8"))
    outputs = {ACTION_OUTPUT: action_reference(), SURFACE_OUTPUT: surface_examples()}
    outputs.update(public_snippet_outputs(source))
    stale = [path for path, text in outputs.items()
             if not path.exists() or path.read_text(encoding="utf-8") != text]
    if args.check:
        if stale:
            print("stale generated references:")
            for path in stale:
                print(path.relative_to(ROOT))
            return 1
        return 0
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
