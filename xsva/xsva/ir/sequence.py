"""Sequence Graph IR：SVA sequence 的结构化表示。

对齐 spec 第十章：
- SeqNodeKind 完整枚举（EXPR, MATCH_ITEM, DELAY, CONCAT, REPEAT, AND, OR,
  INTERSECT, THROUGHOUT, WITHIN, FIRST_MATCH, STRONG, WEAK, OPAQUE）
- SeqNode 扁平 dataclass 配工厂方法和 spec 字段
- AssignActionIR（spec 10.2）
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .common import LoweringStatus, SourceSpan
from .diagnostics import DiagnosticIR
from .expr import ExprIR


@enum.unique
class SeqNodeKind(str, enum.Enum):
    """Sequence 节点类型。对齐 spec 10.1。"""

    EXPR = "expr"  # 普通布尔表达式
    MATCH_ITEM = "match_item"  # 带 guard 和 action 的匹配项
    DELAY = "delay"  # ##N / ##[m:n] / ##[m:$]
    CONCAT = "concat"  # sequence 串接
    REPEAT = "repeat"  # [*], [->], [=]
    AND = "and"  # sequence-level and
    OR = "or"  # sequence-level or
    INTERSECT = "intersect"  # 同时开始且同时结束
    THROUGHOUT = "throughout"  # expr 在 sequence 匹配区间内保持
    WITHIN = "within"  # sequence 匹配区间包含关系
    FIRST_MATCH = "first_match"  # 最早匹配
    STRONG = "strong"  # strong sequence/property wrapper
    WEAK = "weak"  # weak sequence/property wrapper
    OPAQUE = "opaque"  # 能识别但不能安全展开


@dataclass
class AssignActionIR:
    """local variable assignment action。对齐 spec 10.2。

    判定规则：
    - RHS 不引用 LHS → action_kind="capture"
    - RHS 引用 LHS → action_kind="update"
    """

    lhs: str
    rhs: str
    action_kind: str = "capture"  # capture / update
    span: SourceSpan = field(default_factory=SourceSpan)


@dataclass
class SeqNode:
    """Sequence Graph IR 节点。对齐 spec 10.3。

    扁平 dataclass，用 kind 区分类型。通过工厂方法创建以保证字段一致性。
    """

    kind: SeqNodeKind = SeqNodeKind.EXPR
    lowering_status: LoweringStatus = LoweringStatus.EXACT

    raw: str = ""

    # EXPR / MATCH_ITEM / THROUGHOUT
    expr: ExprIR | None = None

    # MATCH_ITEM
    guard_expr: ExprIR | None = None
    actions: list[AssignActionIR] = field(default_factory=list)

    # DELAY
    min_delay: int = 0
    max_delay: int = 0
    unbounded: bool = False  # ##[m:$] 或 [*0:$]

    # REPEAT
    repeat_kind: str = ""  # consecutive / goto / nonconsecutive
    repeat_min: int = 0
    repeat_max: int = 0
    repeat_unbounded: bool = False

    # Tree (CONCAT / AND / OR / INTERSECT / WITHIN / FIRST_MATCH / STRONG / WEAK)
    children: list["SeqNode"] = field(default_factory=list)

    # 语义风险
    semantic_risk: str = ""
    span: SourceSpan = field(default_factory=SourceSpan)
    diagnostics: list[DiagnosticIR] = field(default_factory=list)

    # ── 工厂方法 ──

    @classmethod
    def expr_node(cls, raw: str, expr_ir: ExprIR | None = None) -> "SeqNode":
        return cls(kind=SeqNodeKind.EXPR, raw=raw, expr=expr_ir)

    @classmethod
    def match_item(cls, guard: ExprIR, actions: list[AssignActionIR], raw: str = "") -> "SeqNode":
        return cls(kind=SeqNodeKind.MATCH_ITEM, raw=raw, guard_expr=guard, actions=actions)

    @classmethod
    def delay_cycles(cls, min_c: int, max_c: int | None = None, infinite: bool = False) -> "SeqNode":
        if min_c < 0:
            raise ValueError("delay minimum must be non-negative")
        if max_c is not None and max_c < min_c:
            raise ValueError("delay maximum must be greater than or equal to the minimum")
        if infinite and max_c is not None:
            raise ValueError("an unbounded delay cannot also have a finite maximum")
        return cls(kind=SeqNodeKind.DELAY, min_delay=min_c,
                   max_delay=max_c if max_c is not None else min_c,
                   unbounded=infinite)

    def is_fixed_delay(self) -> bool:
        return self.kind == SeqNodeKind.DELAY and not self.unbounded and self.min_delay == self.max_delay

    def is_finite_range_delay(self) -> bool:
        return self.kind == SeqNodeKind.DELAY and not self.unbounded and self.min_delay != self.max_delay

    @classmethod
    def concat(cls, children: list["SeqNode"], raw: str = "") -> "SeqNode":
        return cls(kind=SeqNodeKind.CONCAT, children=children, raw=raw)

    @classmethod
    def repeat(cls, child: "SeqNode", kind: str, min_c: int, max_c: int = 0,
               unbounded: bool = False, raw: str = "") -> "SeqNode":
        return cls(kind=SeqNodeKind.REPEAT, children=[child], repeat_kind=kind,
                   repeat_min=min_c, repeat_max=max_c, repeat_unbounded=unbounded, raw=raw)

    @classmethod
    def first_match(cls, child: "SeqNode") -> "SeqNode":
        return cls(kind=SeqNodeKind.FIRST_MATCH, children=[child])

    @classmethod
    def intersect(cls, left: "SeqNode", right: "SeqNode") -> "SeqNode":
        return cls(kind=SeqNodeKind.INTERSECT, children=[left, right])

    @classmethod
    def throughout(cls, expr: ExprIR, seq: "SeqNode") -> "SeqNode":
        return cls(kind=SeqNodeKind.THROUGHOUT, expr=expr, children=[seq])

    @classmethod
    def within(cls, inner: "SeqNode", outer: "SeqNode") -> "SeqNode":
        return cls(kind=SeqNodeKind.WITHIN, children=[inner, outer])

    @classmethod
    def strong(cls, child: "SeqNode") -> "SeqNode":
        return cls(kind=SeqNodeKind.STRONG, children=[child])

    @classmethod
    def weak(cls, child: "SeqNode") -> "SeqNode":
        return cls(kind=SeqNodeKind.WEAK, children=[child])

    @classmethod
    def opaque(cls, raw: str, risk: str = "") -> "SeqNode":
        return cls(kind=SeqNodeKind.OPAQUE, raw=raw, semantic_risk=risk,
                   lowering_status=LoweringStatus.OPAQUE)

@dataclass
class SequenceIR:
    """完整的 Sequence Graph IR。

    implication 是 property 关系，不伪装成 sequence node；antecedent 与
    consequent 也不再依赖 marker 节点切分。
    """

    schema_version: str = "xsva.sequence_ir.v1"
    name: str = ""
    implication: str = ""
    antecedent: list[SeqNode] = field(default_factory=list)
    consequent: list[SeqNode] = field(default_factory=list)
    lowering_status: LoweringStatus = LoweringStatus.EXACT
    diagnostics: list[DiagnosticIR] = field(default_factory=list)
