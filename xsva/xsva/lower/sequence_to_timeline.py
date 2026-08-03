"""Sequence Graph IR → Obligation Timeline IR lowering（核心）。对齐 spec 第十六~十八章。

处理：
  16.x - 基础 lowering (|->, |=>, ##N, ##[m:n], [*N], $stable, $past, $rose, $fell)
  17.x - local variable lowering (capture in antecedent, multi-var, capture in path, update)
  18.x - 高级 sequence (first_match, intersect, throughout, within, [->N], [=N])
"""

from __future__ import annotations

import re

from xsva.ir.common import LoweringStatus
from xsva.ir.diagnostics import DiagnosticBag
from xsva.ir.expr import ExprIR, SignalRef
from xsva.ir.sequence import SeqNode, SeqNodeKind, SequenceIR
from xsva.ir.timeline import (
    CaptureIR,
    FailureConditionIR,
    MatchPathIR,
    ObligationIR,
    ObligationKind,
    SemanticNoteIR,
    TimelineIR,
    TriggerIR,
    WindowIR,
)
from xsva.ir.surface import ClockIR


def _worst_status(a: str, b: str) -> str:
    order = {"exact": 0, "partial": 1, "opaque": 2, "unsupported": 3, "unsafe_to_explain": 4}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _signal_refs(expr_ir: ExprIR | None) -> list[SignalRef]:
    if expr_ir is None:
        return []
    return list(expr_ir.signals)


# ── main lowering ──

def lower_sequence_to_timeline(
    seq_ir: SequenceIR,
    surface_ir=None,
    max_paths: int = 10,
    diag: DiagnosticBag | None = None,
) -> TimelineIR:
    if diag is None:
        diag = DiagnosticBag()

    trigger_nodes = _flatten_concat(seq_ir.antecedent)
    obligation_nodes = _flatten_concat(seq_ir.consequent)
    nodes = trigger_nodes + obligation_nodes
    if not nodes:
        return TimelineIR(
            property_name=seq_ir.name,
            lowering_status=LoweringStatus.OPAQUE,
            diagnostics=list(diag.diagnostics),
            path_total_count=0,
            path_returned_count=0,
            path_enumeration_complete=True,
        )

    offset = 1 if seq_ir.implication == "|=>" else 0

    # 3. 用户语义摘要 + 路径展开
    summary_nodes = obligation_nodes if seq_ir.implication else trigger_nodes
    if offset:
        summary_nodes = [SeqNode.delay_cycles(offset)] + summary_nodes
    semantic_notes = _collect_semantic_notes(summary_nodes)
    has_first_match_summary = any(n.kind == "first_match" for n in semantic_notes)

    from .path_expand import PathExpansionResult, expand_first_match, expand_paths
    if has_first_match_summary:
        expansion = PathExpansionResult(paths=[[]], total_path_count=1)
    else:
        expansion = expand_paths(obligation_nodes, max_paths=max_paths)
        expansion = PathExpansionResult(
            paths=expand_first_match(expansion.paths),
            total_path_count=expansion.total_path_count,
        )
    paths = expansion.paths

    # 4. 提取 trigger
    trigger_expr = ""
    trigger_captures: list[CaptureIR] = []

    for node in trigger_nodes:
        if node.kind == SeqNodeKind.EXPR and node.expr:
            if trigger_expr:
                trigger_expr += " && "
            trigger_expr += node.expr.raw
            for s in node.expr.signals:
                if s.name not in [c.var for c in trigger_captures]:
                    pass  # signals in the trigger expression
        elif node.kind in (SeqNodeKind.MATCH_ITEM,):
            if node.guard_expr and node.guard_expr.raw and node.guard_expr.raw != "1":
                if trigger_expr:
                    trigger_expr += " && "
                trigger_expr += node.guard_expr.raw
            for action in node.actions:
                trigger_captures.append(CaptureIR(
                    var=action.lhs,
                    value_expr=action.rhs,
                    relative_cycle=0,
                    meaning=f"{action.action_kind} {action.lhs} at trigger cycle",
                ))

    trigger = TriggerIR(cycle=0, expr=trigger_expr, captures=trigger_captures)

    # 5. 评估 lowering status
    overall_status = seq_ir.lowering_status.value
    for node in nodes:
        status_val = node.lowering_status.value
        overall_status = _worst_status(overall_status, status_val)
        if node.kind in (SeqNodeKind.FIRST_MATCH, SeqNodeKind.INTERSECT,
                         SeqNodeKind.THROUGHOUT, SeqNodeKind.WITHIN):
            overall_status = _worst_status(overall_status, "partial")
            diag.warning("XSVA-W006",
                         f"{node.kind.value} uses advanced sequence semantics; see semantic notes")
        if node.kind == SeqNodeKind.DELAY and node.unbounded:
            overall_status = _worst_status(overall_status, "partial")
            diag.warning(
                "XSVA-L002",
                "unbounded delay produces an open-ended obligation; later sequence "
                "timing cannot be enumerated exactly",
            )
    if expansion.truncated:
        overall_status = _worst_status(overall_status, "partial")
        diag.warning(
            "XSVA-L001",
            "path enumeration limit reached: returned "
            f"{expansion.returned_path_count} of {expansion.total_path_count} candidate paths",
        )

    # 6. 构建 obligations + paths
    all_obligations: list[ObligationIR] = []
    match_paths: list[MatchPathIR] = []
    failure_conditions: list[FailureConditionIR] = []

    for pi, path in enumerate(paths):
        path_obligations: list[ObligationIR] = []
        path_captures: list[CaptureIR] = list(trigger_captures)  # inherit trigger captures
        cycle = offset  # start from implication offset

        i = 0
        while i < len(path):
            node = path[i]

            # Range delay + single expr → windowed eventually
            if (node.kind in (SeqNodeKind.DELAY,)
                    and (node.is_finite_range_delay() or node.unbounded)
                    and i + 1 < len(path)
                    and path[i + 1].kind == SeqNodeKind.EXPR
                    and path[i + 1].expr
                    and (i + 2 >= len(path) or path[i + 2].kind == SeqNodeKind.DELAY)):
                # Merge into single eventually obligation
                next_node = path[i + 1]
                win = WindowIR(
                    start=cycle + node.min_delay,
                    end=cycle + node.max_delay,
                    unbounded=node.unbounded,
                )
                if win.unbounded:
                    req = (
                        f"{next_node.expr.raw} must become true at least once from "
                        f"cycle +{win.start} onward"
                    )
                    fcond = (
                        f"{next_node.expr.raw} is never true from cycle +{win.start} onward"
                    )
                else:
                    req = (
                        f"{next_node.expr.raw} must become true at least once between "
                        f"cycle +{win.start} and +{win.end}"
                    )
                    fcond = (
                        f"{next_node.expr.raw} is never true from cycle +{win.start} "
                        f"to +{win.end}"
                    )
                obl = ObligationIR(
                    id=f"ob_{pi}_{i}", kind=ObligationKind.EVENTUALLY,
                    expr=next_node.expr.raw, expr_ir=next_node.expr,
                    has_cycle=False, has_window=True, window=win,
                    signals_to_query=_signal_refs(next_node.expr),
                    description=req, failure_condition=fcond,
                    depends_on_captures=_find_capture_deps(next_node.expr, path_captures),
                )
                path_obligations.append(obl)
                i += 2
                cycle += node.max_delay
                continue

            # Fixed delay ##N
            if node.kind == SeqNodeKind.DELAY:
                if node.is_fixed_delay():
                    cycle += node.min_delay
                    i += 1
                    continue
                # Otherwise: range delay already handled above
                cycle += node.min_delay
                i += 1
                continue

            # Expression match
            if node.kind == SeqNodeKind.EXPR and node.expr:
                note = _semantic_note_from_raw(node.expr.raw)
                if note:
                    _append_unique_note(semantic_notes, note)
                    overall_status = _worst_status(overall_status, "partial")
                    i += 1
                    continue
                obl = _expr_to_obligation(node, cycle, pi, i, path_captures)
                if obl:
                    path_obligations.append(obl)
                i += 1
                continue

            if node.kind in (SeqNodeKind.MATCH_ITEM,):
                if node.guard_expr and node.guard_expr.raw and node.guard_expr.raw != "1":
                    guard_node = SeqNode.expr_node(node.guard_expr.raw, node.guard_expr)
                    obl = _expr_to_obligation(guard_node, cycle, pi, i, path_captures)
                    if obl:
                        path_obligations.append(obl)
                for action in node.actions:
                    path_captures.append(CaptureIR(
                        var=action.lhs,
                        value_expr=action.rhs,
                        relative_cycle=cycle,
                        meaning=f"{action.action_kind} {action.lhs} at cycle +{cycle}",
                    ))
                i += 1
                continue

            # Intersect — mark partial
            if node.kind in (SeqNodeKind.INTERSECT,):
                overall_status = _worst_status(overall_status, "partial")
                i += 1
                continue

            # First_match — mark and skip (handled by path_expand)
            if node.kind in (SeqNodeKind.FIRST_MATCH,):
                overall_status = _worst_status(overall_status, "partial")
                i += 1
                continue

            # Throughout / Within — mark partial
            if node.kind in (SeqNodeKind.THROUGHOUT, SeqNodeKind.WITHIN):
                overall_status = _worst_status(overall_status, "partial")
                i += 1
                continue

            # Anything else
            i += 1

        # Collect obligations
        all_obligations.extend(path_obligations)

        # Build MatchPathIR
        path_desc = f"Path {pi}: " + " → ".join(
            f"{ob.description[:50]}" for ob in path_obligations
        ) if path_obligations else f"Path {pi}: (empty)"

        match_paths.append(MatchPathIR(
            id=f"path_{pi}",
            captures=path_captures,
            obligations=tuple(path_obligations),
            pass_condition="all obligations in this path must hold",
            failure_condition="any obligation in this path fails",
            is_partial=(overall_status != "exact"),
            description=path_desc,
        ))

    # 7. Failure conditions (aggregate)
    for ob in all_obligations:
        if ob.failure_condition:
            failure_conditions.append(FailureConditionIR(
                obligation_id=ob.id, condition=ob.failure_condition,
            ))

    # 8. Clock & disable
    clock = ClockIR(edge="posedge", signal="", supported=True)
    disable_expr = ""
    if surface_ir:
        clock = surface_ir.clock or clock
        disable_expr = surface_ir.disable_expr

    # 9. Vacuity checks
    vacuity: list[str] = []
    if not disable_expr:
        vacuity.append("XSVA-W001: missing disable iff")
    if trigger_expr in ("0", "1'b0"):
        vacuity.append("XSVA-W002: antecedent is constant false")

    disable_obligation = None
    if disable_expr:
        disable_obligation = ObligationIR(
            id="disable", kind=ObligationKind.POINT,
            description=(
                f"disable iff ({disable_expr}): if true, the current attempt is "
                "immediately terminated"
            ),
            failure_condition=f"{disable_expr} becomes true during the attempt",
        )

    timeline = TimelineIR(
        schema_version="xsva.timeline_ir.v1",
        property_name=seq_ir.name,
        kind=surface_ir.kind if surface_ir else "assert",
        clock=clock,
        disable_expr=disable_expr,
        trigger=trigger,
        obligations=all_obligations,
        match_paths=match_paths,
        failure_conditions=failure_conditions,
        disable_obligation=disable_obligation,
        semantic_notes=semantic_notes,
        vacuity_checks=vacuity,
        lowering_status=LoweringStatus(overall_status),
        diagnostics=list(diag.diagnostics) if diag else [],
        path_total_count=expansion.total_path_count,
        path_returned_count=expansion.returned_path_count,
        path_enumeration_complete=expansion.enumeration_complete,
    )
    return timeline


def _expr_to_obligation(
    node: SeqNode, cycle: int, pi: int, i: int, captures: list[CaptureIR],
) -> ObligationIR | None:
    """将 Expr/ExprMatch 节点转为对应的 ObligationIR。"""
    expr = node.expr
    if not expr:
        return None

    # Sampled functions
    if expr.sampled_funcs:
        func = expr.sampled_funcs[0]
        if func == "$past":
            depth = expr.sample_dependencies[0].depth or 1
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.COMPARE_PAST,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} compares with the value sampled {depth} clk earlier",
                depends_on_captures=_find_capture_deps(expr, captures),
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$rose":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.ROSE,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} detects a rising edge at cycle +{cycle}",
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$fell":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.FELL,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} detects a falling edge at cycle +{cycle}",
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$stable":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.STABLE,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} stays the same as the previous clk sample",
                depends_on_captures=_find_capture_deps(expr, captures),
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$changed":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.POINT,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} changes from the previous clk sample",
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$isunknown":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.POINT,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} checks whether the expression contains X/Z unknown bits",
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$onehot":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.POINT,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} checks that exactly one bit is set",
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$onehot0":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.POINT,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} checks that zero or one bit is set",
                signals_to_query=_signal_refs(expr),
            )
        elif func == "$countones":
            return ObligationIR(
                id=f"ob_{pi}_{i}", kind=ObligationKind.POINT,
                expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
                description=f"{expr.raw} counts the number of set bits",
                signals_to_query=_signal_refs(expr),
            )

    # Capture reference in obligation
    deps = _find_capture_deps(expr, captures)

    # Hold: B[*3] pattern — handled by lowering caller or separate logic
    # Point: default
    return ObligationIR(
        id=f"ob_{pi}_{i}", kind=ObligationKind.POINT,
        expr=expr.raw, expr_ir=expr, has_cycle=True, cycle=cycle,
        description=f"{expr.raw} must be true at cycle +{cycle}",
        failure_condition=f"{expr.raw} is false at cycle +{cycle}" if cycle >= 0 else None,
        depends_on_captures=deps,
        signals_to_query=_signal_refs(expr),
    )


def _collect_semantic_notes(nodes: list[SeqNode]) -> list[SemanticNoteIR]:
    notes: list[SemanticNoteIR] = []
    for idx, node in enumerate(nodes):
        if node.kind == SeqNodeKind.FIRST_MATCH:
            suffix_delay = _fixed_delay_at(nodes, idx + 1)
            suffix_expr = _expr_at(nodes, idx + 2) if suffix_delay is not None else ""
            _append_unique_note(notes, SemanticNoteIR(
                kind="first_match", expr=_node_raw(node),
                text=_first_match_text(node, suffix_delay, suffix_expr)))
        elif node.kind == SeqNodeKind.INTERSECT:
            for note in _binary_sequence_notes("intersect", node):
                _append_unique_note(notes, note)
        elif node.kind == SeqNodeKind.THROUGHOUT:
            raw = _node_raw(node)
            seq_summary = _summarize_sequence(node.children[0], absolute=False) if node.children else "the sequence must match"
            _append_unique_note(notes, SemanticNoteIR(kind="throughout_sequence", expr=raw,
                                                      text=f"Sequence: {seq_summary}"))
            expr = node.expr.raw if node.expr else "The expression"
            _append_unique_note(notes, SemanticNoteIR(kind="throughout", expr=raw,
                                                      text=f"Relation: {expr} must hold throughout the entire matched interval of the sequence."))
        elif node.kind == SeqNodeKind.WITHIN:
            for note in _binary_sequence_notes("within", node):
                _append_unique_note(notes, note)
        elif node.kind == SeqNodeKind.REPEAT:
            _append_unique_note(notes, SemanticNoteIR(
                kind=f"repeat_{node.repeat_kind}", expr=_node_raw(node),
                text=_repeat_text(_node_raw(node.children[0]) if node.children else node.raw,
                                  node.repeat_kind, node.repeat_min, node.repeat_max)))
        elif node.kind == SeqNodeKind.EXPR and node.expr:
            note = _semantic_note_from_raw(node.expr.raw)
            if note:
                _append_unique_note(notes, note)
    if not notes:
        summary = _summarize_sequence(nodes, absolute=True)
        if summary:
            _append_unique_note(notes, SemanticNoteIR(kind="summary", expr=_nodes_raw(nodes), text=summary))
    return notes


def _append_unique_note(notes: list[SemanticNoteIR], note: SemanticNoteIR) -> None:
    if not any(n.kind == note.kind and n.expr == note.expr and n.text == note.text for n in notes):
        notes.append(note)


def _semantic_note_from_raw(raw: str) -> SemanticNoteIR | None:
    norm = _clean_raw(raw)
    repeat = _repeat_note_from_raw(norm)
    if repeat:
        return repeat
    if " throughout " in f" {norm} ":
        return SemanticNoteIR(kind="throughout", expr=norm, text=_throughout_text(norm))
    if " intersect " in f" {norm} ":
        return SemanticNoteIR(kind="intersect", expr=norm, text=_intersect_text(norm))
    if " within " in f" {norm} ":
        return SemanticNoteIR(kind="within", expr=norm, text=_within_text(norm))
    return None


def _repeat_note_from_raw(raw: str) -> SemanticNoteIR | None:
    match = re.search(r"(.+?)\s*\[\s*(\*|->|=)\s*(\d+)(?:\s*:\s*(\d+|\$))?\s*\]\s*$", raw)
    if not match:
        return None
    expr = match.group(1).strip()
    op = match.group(2)
    min_c = int(match.group(3))
    max_s = match.group(4)
    max_c = 0 if max_s is None or max_s == "$" else int(max_s)
    repeat_kind = {"*": "consecutive", "->": "goto", "=": "nonconsecutive"}[op]
    return SemanticNoteIR(kind=f"repeat_{repeat_kind}", expr=raw,
                          text=_repeat_text(expr, repeat_kind, min_c, max_c))


def _repeat_text(expr: str, repeat_kind: str, min_c: int, max_c: int = 0) -> str:
    clean_expr = _clean_raw(expr)
    if repeat_kind == "consecutive":
        if max_c and max_c != min_c:
            return f"{clean_expr} needs to hold continuously for {min_c} to {max_c} clk cycles."
        return f"{clean_expr} needs to hold continuously for {min_c} clk cycles."
    if repeat_kind == "goto":
        return f"Wait for the {_ordinal(min_c)} occurrence of {clean_expr}; the match ends on that clk."
    if repeat_kind == "nonconsecutive":
        return f"{clean_expr} needs to match {min_c} times in total, with non-matching clk cycles allowed in between."
    return f"{clean_expr} uses {repeat_kind} repetition."


def _first_match_text(node: SeqNode, suffix_delay: int | None = None, suffix_expr: str = "") -> str:
    raw = _node_raw(node)
    window = _first_delay_window(node)
    first_expr = _first_expr_after_delay(node)
    suffix_delay = suffix_delay if suffix_delay is not None else _suffix_delay_after_first_match(raw)
    if window and first_expr and suffix_delay is not None and suffix_expr:
        return (f"{first_expr} must be the first match at cycle +{window[0]} to +{window[1]}; "
                f"{suffix_expr} must be true {suffix_delay} clk after that first {first_expr}.")
    if window and first_expr and suffix_delay is not None:
        return (f"{first_expr} must be the first match at cycle +{window[0]} to +{window[1]}; "
                f"the following sequence is checked {suffix_delay} clk after that first match.")
    if window and first_expr:
        return f"{first_expr} must be the first match at cycle +{window[0]} to +{window[1]}."
    return "The first_match sequence selects the earliest matching path, and later checks are relative to that first match."


def _first_delay_window(node: SeqNode) -> tuple[int, int] | None:
    for child in _walk_nodes(node):
        if child.is_finite_range_delay():
            return (child.min_delay, child.max_delay)
    return None


def _first_expr_after_delay(node: SeqNode) -> str:
    seen_delay = False
    for child in _walk_nodes(node):
        if child.kind == SeqNodeKind.DELAY:
            seen_delay = True
            continue
        if seen_delay and child.expr:
            return child.expr.raw
    return ""


def _suffix_delay_after_first_match(raw: str) -> int | None:
    match = re.search(r"\)\s*##\s*(\d+)", raw)
    return int(match.group(1)) if match else None


def _fixed_delay_at(nodes: list[SeqNode], idx: int) -> int | None:
    if idx >= len(nodes):
        return None
    node = nodes[idx]
    if node.is_fixed_delay():
        return node.min_delay
    return None


def _expr_at(nodes: list[SeqNode], idx: int) -> str:
    if idx >= len(nodes):
        return ""
    return _match_expr(nodes[idx])


def _binary_sequence_notes(kind: str, node: SeqNode) -> list[SemanticNoteIR]:
    if len(node.children) < 2:
        raw = _node_raw(node)
        text = _intersect_text(raw) if kind == "intersect" else _within_text(raw)
        return [SemanticNoteIR(kind=kind, expr=raw, text=f"Relation: {text}")]

    raw = _node_raw(node)
    left = _summarize_sequence(node.children[0], absolute=False)
    right = _summarize_sequence(node.children[1], absolute=False)
    if kind == "intersect":
        relation = "sequence 1 and sequence 2 must start on the same clk and end on the same clk."
    else:
        relation = "sequence 1's matched interval must be contained within sequence 2's matched interval."
    return [
        SemanticNoteIR(kind=f"{kind}_sequence_1", expr=raw, text=f"Sequence 1: {left}"),
        SemanticNoteIR(kind=f"{kind}_sequence_2", expr=raw, text=f"Sequence 2: {right}"),
        SemanticNoteIR(kind=kind, expr=raw, text=f"Relation: {relation}"),
    ]


def _intersect_text(raw: str) -> str:
    return "The left and right sequences must start on the same clk and finish on the same clk."


def _throughout_text(raw: str) -> str:
    left = raw.split(" throughout ", 1)[0].strip() if " throughout " in raw else "The left expression"
    return f"{left} must hold for the entire matched interval of the sequence on the right."


def _within_text(raw: str) -> str:
    return "The left sequence must match entirely within the matched interval of the sequence on the right."


def _node_raw(node: SeqNode) -> str:
    if node.raw:
        return _clean_raw(node.raw)
    if node.expr:
        return _clean_raw(node.expr.raw)
    if node.kind == SeqNodeKind.DELAY:
        if node.is_fixed_delay():
            return f"##{node.min_delay}"
        end = "$" if node.unbounded else str(node.max_delay)
        return f"##[{node.min_delay}:{end}]"
    if node.kind == SeqNodeKind.FIRST_MATCH and node.children:
        return f"first_match({_node_raw(node.children[0])})"
    if node.children:
        return " ".join(_node_raw(c) for c in node.children if _node_raw(c))
    return node.kind.value


def _nodes_raw(nodes: list[SeqNode]) -> str:
    return " ".join(_node_raw(n) for n in nodes if _node_raw(n))


def _summarize_sequence(node_or_nodes, absolute: bool = False) -> str:
    nodes = node_or_nodes if isinstance(node_or_nodes, list) else [node_or_nodes]
    nodes = _flatten_concat(nodes)

    if len(nodes) == 1:
        node = nodes[0]
        if node.kind == SeqNodeKind.CONCAT:
            return _summarize_sequence(node.children, absolute=absolute)
        if node.kind == SeqNodeKind.REPEAT:
            return _repeat_text(_node_raw(node.children[0]) if node.children else node.raw,
                                node.repeat_kind, node.repeat_min, node.repeat_max)
        if node.kind == SeqNodeKind.FIRST_MATCH:
            return _first_match_text(node)
        if node.kind in (SeqNodeKind.EXPR, SeqNodeKind.MATCH_ITEM):
            expr = _match_expr(node)
            if not expr:
                return ""
            if absolute:
                return f"{expr} must be true at cycle +0."
            return f"{expr} must be true."
        if node.kind == SeqNodeKind.THROUGHOUT:
            expr = node.expr.raw if node.expr else "The expression"
            seq = _summarize_sequence(node.children[0], absolute=False) if node.children else "the sequence must match"
            return f"Sequence: {seq} Relation: {expr} must hold throughout the entire matched interval of the sequence."
        if node.kind in (SeqNodeKind.INTERSECT, SeqNodeKind.WITHIN):
            return " ".join(note.text for note in _binary_sequence_notes(node.kind.value, node))

    parts: list[str] = []
    cycle = 0
    last_expr = ""
    i = 0
    while i < len(nodes):
        node = nodes[i]
        if node.kind == SeqNodeKind.DELAY and i + 1 < len(nodes):
            target = nodes[i + 1]
            expr = _match_expr(target)
            if not expr:
                cycle += node.min_delay
                i += 1
                continue
            min_c = cycle + node.min_delay
            max_c = cycle + node.max_delay
            fixed_delay = node.is_fixed_delay()
            if last_expr and fixed_delay:
                phrase = f"{expr} must be true {_clk_count(node.min_delay)} after {last_expr}"
            elif last_expr:
                end = "$" if node.unbounded else str(max_c - cycle)
                phrase = f"{expr} must be true {node.min_delay} to {end} clk after {last_expr}"
            elif absolute:
                phrase = (
                    f"{expr} must be true at or after cycle +{min_c}"
                    if node.unbounded
                    else _absolute_delay_phrase(expr, min_c, max_c)
                )
            else:
                phrase = (
                    f"{expr} must be true {node.min_delay} or more clk later"
                    if node.unbounded
                    else _relative_delay_phrase(expr, node.min_delay, node.max_delay)
                )
            capture = _capture_phrase(target)
            if capture:
                phrase += f", {capture}"
            parts.append(phrase)
            last_expr = expr
            cycle = max_c
            i += 2
            continue

        expr = _match_expr(node)
        if expr:
            phrase = f"{expr} must be true" if not absolute else f"{expr} must be true at cycle +{cycle}"
            capture = _capture_phrase(node)
            if capture:
                phrase += f", {capture}"
            parts.append(phrase)
            last_expr = expr
        i += 1

    if not parts:
        return ""
    return _join_summary_parts(parts) + "."


def _match_expr(node: SeqNode) -> str:
    if node.kind == SeqNodeKind.EXPR and node.expr:
        return _clean_raw(node.expr.raw)
    if node.kind == SeqNodeKind.MATCH_ITEM:
        if node.guard_expr and node.guard_expr.raw and node.guard_expr.raw != "1":
            return _clean_raw(node.guard_expr.raw)
    return ""


def _capture_phrase(node: SeqNode) -> str:
    if node.kind != SeqNodeKind.MATCH_ITEM:
        return ""
    captures = []
    for action in node.actions:
        if action.action_kind == "capture":
            captures.append(f"capturing {action.lhs} = {_clean_raw(action.rhs)} at that matching cycle")
        else:
            captures.append(f"updating {action.lhs} = {_clean_raw(action.rhs)} at that matching cycle")
    return "; ".join(captures)


def _absolute_delay_phrase(expr: str, min_c: int, max_c: int) -> str:
    if min_c == max_c:
        return f"{expr} must be true at cycle +{min_c}"
    return f"{expr} must be true at cycle +{min_c} to +{max_c}"


def _relative_delay_phrase(expr: str, min_c: int, max_c: int) -> str:
    if min_c == max_c:
        return f"{expr} must be true {_clk_count(min_c)} later"
    return f"{expr} must be true {min_c} to {max_c} clk later"


def _clk_count(count: int) -> str:
    return f"{count} clk"


def _join_summary_parts(parts: list[str]) -> str:
    if len(parts) <= 1:
        return parts[0]
    first, rest = parts[0], parts[1:]
    joined = first
    for part in rest:
        if part.startswith("then "):
            joined += f", {part}"
        else:
            joined += f"; {part}"
    return joined


def _walk_nodes(node: SeqNode):
    yield node
    for child in node.children:
        yield from _walk_nodes(child)


def _clean_raw(raw: str) -> str:
    return " ".join(raw.split())


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def _flatten_concat(nodes: list[SeqNode]) -> list[SeqNode]:
    flat: list[SeqNode] = []
    for node in nodes:
        if node.kind == SeqNodeKind.CONCAT:
            flat.extend(_flatten_concat(node.children))
        else:
            flat.append(node)
    return flat


def _find_capture_deps(expr: ExprIR | None, captures: list[CaptureIR]) -> list[str]:
    """找出表达式中引用的 capture variable。"""
    if not expr or not captures:
        return []
    deps: list[str] = []
    for c in captures:
        if c.var in expr.raw:
            deps.append(c.var)
    return deps
