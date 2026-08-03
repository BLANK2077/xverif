"""Markdown 解释生成器。对齐 spec 第二十章。

从 TimelineIR 生成 markdown 格式解释。
"""

from __future__ import annotations

from xsva.ir.timeline import TimelineIR


def render_timeline_markdown(timeline: TimelineIR) -> str:
    """从 TimelineIR 生成 markdown 解释。"""
    lines: list[str] = []

    lines.append(f"# Property: {timeline.property_name}")
    lines.append("")

    # Kind
    lines.append(f"**Kind:** {timeline.kind}")
    lines.append("")
    lines.append(f"**Lowering status:** `{timeline.lowering_status.value}`")
    lines.append(
        "**Path enumeration:** "
        f"`{timeline.path_returned_count}/{timeline.path_total_count}` "
        f"({'complete' if timeline.path_enumeration_complete else 'partial'})"
    )
    lines.append("")

    # Clock
    if timeline.clock.signal:
        lines.append(f"**Clock:** `@({timeline.clock.edge} {timeline.clock.signal})`")
        lines.append("")

    # Disable
    if timeline.disable_expr:
        lines.append(f"**Disable:** `disable iff ({timeline.disable_expr})`")
        lines.append("")

    # Trigger
    if timeline.trigger:
        lines.append("## Trigger")
        lines.append(f"**cycle 0:** `{timeline.trigger.expr}`")
        if timeline.trigger.captures:
            lines.append("")
            for c in timeline.trigger.captures:
                lines.append(f"- `{c.var} = {c.value_expr}` (cycle {c.relative_cycle})")
        lines.append("")

    if timeline.semantic_notes:
        lines.append("## Semantic Notes")
        for note in timeline.semantic_notes:
            lines.append(f"- {note.text}")
        lines.append("")
        _append_failure_conditions(lines, timeline)
        _append_diagnostics(lines, timeline)
        return "\n".join(lines)

    # Obligations for timelines without user-facing summaries.
    lines.append("## Obligations")

    if len(timeline.match_paths) == 1 and timeline.match_paths[0].obligations:
        for ob in timeline.match_paths[0].obligations:
            lines.append(f"- **[{ob.kind.value}]** {ob.description}")
            if ob.window:
                lines.append(f"  - Window: `+{ob.window.start}` to `+{ob.window.end if not ob.window.unbounded else '$'}`")
            if ob.failure_condition:
                lines.append(f"  - Failure: {ob.failure_condition}")
    elif len(timeline.match_paths) > 1:
        lines.append(f"**{len(timeline.match_paths)} candidate paths:**")
        lines.append("")
        for path in timeline.match_paths:
            lines.append(f"### {path.description}")
            for ob in path.obligations:
                lines.append(f"- [{ob.kind.value}] {ob.description}")
            lines.append("")
    lines.append("")

    _append_failure_conditions(lines, timeline)
    _append_diagnostics(lines, timeline)

    return "\n".join(lines)


def _append_failure_conditions(lines: list[str], timeline: TimelineIR) -> None:
    if timeline.failure_conditions:
        lines.append("## Failure Conditions")
        for fc in timeline.failure_conditions:
            lines.append(f"- `{fc.condition}`")
        lines.append("")


def _append_diagnostics(lines: list[str], timeline: TimelineIR) -> None:
    if timeline.diagnostics:
        lines.append("## Diagnostics")
        for d in timeline.diagnostics:
            lines.append(f"- [{d.severity}] **{d.code}**: {d.message}")
        lines.append("")
