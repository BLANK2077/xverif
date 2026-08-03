"""Surface IR → Sequence Graph IR lowering.

将 SurfaceIR 的 antecedent_raw / consequent_raw 解析为 SeqNode 列表。
"""

from __future__ import annotations

from xsva.ir.common import LoweringStatus
from xsva.ir.diagnostics import DiagnosticBag
from xsva.ir.surface import SurfaceIR
from xsva.ir.sequence import SeqNode, SequenceIR

from xsva.parser.scanner import Scanner
from xsva.parser.sequence_parser import SequenceParser


def lower_surface_to_sequence(
    surface: SurfaceIR,
    diag: DiagnosticBag | None = None,
) -> SequenceIR:
    """将 SurfaceIR lowering 为 SequenceIR。

    步骤：
    1. 解析 antecedent_raw → SeqNode 列表
    2. 解析 consequent_raw → SeqNode 列表
    3. implication、antecedent 和 consequent 分字段保存，不插入兼容 marker node
    """
    if diag is None:
        diag = DiagnosticBag()

    antecedent: list[SeqNode] = []
    consequent: list[SeqNode] = []

    # 1. 解析 antecedent
    if surface.antecedent_raw.strip():
        scanner = Scanner(surface.antecedent_raw, file="<antecedent>")
        seq_parser = SequenceParser(scanner, diag)
        antecedent = seq_parser.parse_sequence()

    # 2. 解析 consequent
    if surface.consequent_raw.strip():
        scanner = Scanner(surface.consequent_raw, file="<consequent>")
        seq_parser = SequenceParser(scanner, diag)
        consequent = seq_parser.parse_sequence()

    statuses = [surface.lowering_status]
    statuses.extend(node.lowering_status for node in _walk_nodes(antecedent + consequent))
    lowering_status = max(statuses, key=_status_rank)

    return SequenceIR(
        name=surface.name,
        implication=surface.implication,
        antecedent=antecedent,
        consequent=consequent,
        lowering_status=lowering_status,
        diagnostics=list(diag.diagnostics),
    )


def _walk_nodes(nodes: list[SeqNode]):
    for node in nodes:
        yield node
        yield from _walk_nodes(node.children)


def _status_rank(status: LoweringStatus) -> int:
    return {
        LoweringStatus.EXACT: 0,
        LoweringStatus.PARTIAL: 1,
        LoweringStatus.OPAQUE: 2,
        LoweringStatus.UNSUPPORTED: 3,
        LoweringStatus.UNSAFE_TO_EXPLAIN: 4,
    }[status]
