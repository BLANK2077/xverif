"""文本解释生成器 — 从 TimelineIR 生成人类可读文本解释。"""

from __future__ import annotations

from xsva.ir.timeline import TimelineIR


def render_timeline_text(timeline: TimelineIR) -> str:
    """从 TimelineIR 生成文本解释。"""

    lines: list[str] = []
    sep = "═" * 50

    lines.append(sep)
    lines.append(f"Property: {timeline.property_name}")

    # Clock
    if timeline.clock.signal:
        lines.append(f"Clock: @({timeline.clock.edge} {timeline.clock.signal})")

    # Disable
    if timeline.disable_expr:
        lines.append(f"Disable: disable iff ({timeline.disable_expr})")

    lines.append(f"Lowering status: {timeline.lowering_status.value}")
    lines.append(
        "Path enumeration: "
        f"{timeline.path_returned_count}/{timeline.path_total_count} "
        f"({'complete' if timeline.path_enumeration_complete else 'partial'})"
    )
    lines.append("")

    # Trigger
    if timeline.trigger:
        lines.append(f"Trigger:")
        lines.append(f"  cycle 0: {_describe_trigger(timeline)}")
        lines.append("")

    if timeline.semantic_notes:
        lines.append("Semantic notes:")
        for note in timeline.semantic_notes:
            lines.append(f"  - {note.text}")
        lines.append("")
        _append_diagnostics(lines, timeline)
        lines.append(sep)
        return "\n".join(lines)

    # Obligations / paths for timelines without user-facing summaries.
    if len(timeline.match_paths) == 1 and len(timeline.match_paths[0].obligations) == 1:
        # 单 obligation — 简化输出
        ob = timeline.match_paths[0].obligations[0]
        lines.append(f"Obligation:")
        lines.append(f"  {ob.description}")
        if ob.window:
            end = "∞" if ob.window.unbounded else str(ob.window.end)
            lines.append(f"  Window: cycle +{ob.window.start} to +{end}")
        if ob.failure_condition:
            lines.append(f"  Failure: {ob.failure_condition}")
    elif len(timeline.match_paths) == 1:
        # 单路径多 obligation
        lines.append("Obligations:")
        for ob in timeline.match_paths[0].obligations:
            lines.append(f"  [{ob.kind.value}] {ob.description}")
    else:
        # 多路径
        lines.append(f"Obligations ({len(timeline.match_paths)} paths):")
        for path in timeline.match_paths:
            lines.append(f"  {path.description}:")
            for ob in path.obligations:
                lines.append(f"    [{ob.kind.value}] {ob.description}")

    # Failure conditions
    if timeline.failure_conditions:
        lines.append("")
        lines.append("Failure conditions:")
        for fc in timeline.failure_conditions:
            lines.append(f"  {fc.condition}")

    _append_diagnostics(lines, timeline)

    lines.append(sep)
    return "\n".join(lines)


def _append_diagnostics(lines: list[str], timeline: TimelineIR) -> None:
    if timeline.diagnostics:
        lines.append("")
        lines.append("Diagnostics:")
        for d in timeline.diagnostics:
            lines.append(f"  [{d.severity}] {d.code}: {d.message}")


def _describe_trigger(timeline: TimelineIR) -> str:
    """描述触发条件。"""
    if timeline.trigger.expr:
        desc = timeline.trigger.expr
    else:
        desc = "trigger condition"

    # Add capture info
    if timeline.trigger.captures:
        caps = []
        for capture in timeline.trigger.captures:
            caps.append(f"{capture.var} = {capture.value_expr}")
        desc += f" (captures: {', '.join(caps)})"

    return desc
