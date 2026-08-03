"""Command-specific human output for xsva responses."""

from __future__ import annotations

import json

from .contracts import validate_response
from .util.json import to_jsonable


def to_xout(payload: dict) -> str:
    normalized = to_jsonable(payload)
    if not isinstance(normalized, dict):
        raise TypeError("XOUT payload root must be an object")
    validate_response(normalized)
    action = str(normalized.get("action") or "error")
    if not normalized["ok"]:
        return f"xsva error: {normalized['error']['message']}\n"
    result = normalized["result"]
    if action == "list":
        lines = ["Properties:"]
        lines.extend(f"  {item['name']}" for item in result.get("properties", []))
        lines.append("Assertions:")
        for item in result.get("assertions", []):
            label = item.get("label", "")
            lines.append(f"  {label}{':' if label else ''} {item['type']} property ({item['name']})")
        return "\n".join(lines) + "\n"
    if action == "scan":
        lines = [
            f"File: {normalized['file']}",
            f"Property blocks: {result.get('property_blocks', 0)}",
            f"Inline assertions: {result.get('inline_assertions', 0)}",
            "Operators:",
        ]
        labels = {"##": "##N", "[*": "[*]", "[=": "[=]", "[->": "[->]"}
        for operator, count in result.get("operators", {}).items():
            if count:
                lines.append(f"  {labels.get(operator, operator):20s} {count}")
        return "\n".join(lines) + "\n"
    if action == "lint":
        diagnostics = normalized.get("diagnostics", [])
        if not diagnostics:
            return "No issues found.\n"
        return "".join(
            f"[{item['severity']}] {item['code']}: {item['message']}\n"
            for item in diagnostics
        )
    if action == "parse":
        return json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if action == "explain":
        return _render_explain(normalized)
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def _render_explain(payload: dict) -> str:
    timeline = payload["result"]
    sep = "═" * 50
    lines = [sep, f"Property: {timeline['property']}"]
    clock = timeline.get("clock") or {}
    if clock.get("signal"):
        lines.append(f"Clock: @({clock.get('edge')} {clock.get('signal')})")
    if timeline.get("disable_expr"):
        lines.append(f"Disable: disable iff ({timeline['disable_expr']})")
    lines.append(f"Lowering status: {payload['lowering_status']}")
    complete = payload["completeness"]
    if complete.get("total_path_count") is not None:
        state = "complete" if complete.get("path_enumeration_complete") else "partial"
        lines.append(f"Path enumeration: {complete['returned_path_count']}/{complete['total_path_count']} ({state})")
    lines.append("")
    trigger = timeline.get("trigger") or {}
    if trigger.get("expr"):
        description = trigger["expr"]
        captures = trigger.get("captures") or []
        if captures:
            description += " (captures: " + ", ".join(
                f"{item['var']} = {item['value_expr']}" for item in captures
            ) + ")"
        lines.extend(("Trigger:", f"  cycle 0: {description}", ""))
    notes = timeline.get("semantic_notes") or []
    if notes:
        lines.append("Semantic notes:")
        lines.extend(f"  - {item['text']}" for item in notes)
    else:
        obligations = {item["id"]: item for item in timeline.get("obligations", [])}
        paths = timeline.get("match_paths", [])
        lines.append("Obligations:" if len(paths) <= 1 else f"Obligations ({len(paths)} paths):")
        for path in paths:
            if len(paths) > 1:
                lines.append(f"  {path.get('description', path['id'])}:")
            for obligation_id in path.get("obligations", []):
                obligation = obligations.get(obligation_id, {})
                indent = "    " if len(paths) > 1 else "  "
                lines.append(f"{indent}[{obligation.get('kind', 'obligation')}] {obligation.get('requirement') or obligation.get('expr') or obligation_id}")
        failures = timeline.get("failure_conditions") or []
        if failures:
            lines.extend(("", "Failure conditions:"))
            lines.extend(f"  {condition}" for condition in failures)
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.extend(("", "Diagnostics:"))
        lines.extend(f"  [{item['severity']}] {item['code']}: {item['message']}" for item in diagnostics)
    lines.append(sep)
    return "\n".join(lines) + "\n"
