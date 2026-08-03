"""Obligation Timeline IR：面向人类解释和 Agent 消费的最终 IR。

对齐 spec 第十一章：
- TriggerIR, CaptureIR, ObligationIR, WindowIR, MatchPathIR, FailureConditionIR, TimelineIR
- ObligationKind Enum 用于类型安全
- disable 显式表达为 ObligationIR
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .common import LoweringStatus, SourceSpan
from .diagnostics import DiagnosticIR
from .expr import ExprIR, SignalRef
from .surface import ClockIR


# ── 枚举 ──

@enum.unique
class ObligationKind(enum.Enum):
    """Obligation 类型。对齐 spec 11.2。"""

    POINT = "point"  # 固定周期检查
    EVENTUALLY = "eventually"  # 窗口内至少发生一次
    HOLD = "hold"  # 窗口内保持
    STABLE = "stable"  # $stable
    ROSE = "rose"  # $rose
    FELL = "fell"  # $fell
    COMPARE_PAST = "compare_past"  # $past 比较
    SEQUENCE_PATH = "sequence_path"  # path-based sequence obligation


# ── 核心 IR ──

@dataclass
class CaptureIR:
    """local variable capture。对齐 spec 11.1。"""

    var: str = ""
    value_expr: str = ""
    relative_cycle: int = 0
    meaning: str = ""


@dataclass
class TriggerIR:
    """触发条件。对齐 spec 11.1。"""

    cycle: int = 0
    expr: str = ""
    captures: list[CaptureIR] = field(default_factory=list)


@dataclass(frozen=True)
class WindowIR:
    """时间窗口：[start, end]，相对 trigger 偏移。对齐 spec 11.1。"""

    start: int = 0
    end: int = 0
    unbounded: bool = False
    description: str = ""


@dataclass(frozen=True)
class ObligationIR:
    """单个 obligation。对齐 spec 11.1。

    kind: ObligationKind Enum 确保类型安全。
    signals_to_query: 标准化信号查询接口，方便 Evidence IR 对接。
    """

    id: str = ""
    kind: ObligationKind = ObligationKind.POINT
    expr: str = ""  # spec 用 str，同时保留 ExprIR 引用
    expr_ir: ExprIR | None = None

    has_cycle: bool = False
    cycle: int = 0

    has_window: bool = False
    window: WindowIR | None = None

    depends_on_captures: list[str] = field(default_factory=list)
    requirement: str = ""
    signals_to_query: list[SignalRef] = field(default_factory=list)
    failure_condition: str | None = None
    description: str = ""


@dataclass(frozen=True)
class MatchPathIR:
    """展开后的匹配路径。对齐 spec 11.1。"""

    id: str = ""
    captures: list[CaptureIR] = field(default_factory=list)
    obligations: tuple[ObligationIR, ...] = ()
    pass_condition: str = ""
    failure_condition: str = ""
    is_partial: bool = False
    description: str = ""


@dataclass(frozen=True)
class FailureConditionIR:
    """obligation 失败条件。"""

    obligation_id: str = ""
    condition: str = ""


@dataclass(frozen=True)
class SemanticNoteIR:
    """面向用户的高级语法语义摘要。"""

    kind: str = ""
    expr: str = ""
    text: str = ""


@dataclass
class TimelineIR:
    """Obligation Timeline IR — 最终输出 IR。对齐 spec 11.1。"""

    schema_version: str = "xsva.timeline_ir.v1"

    property_name: str = ""  # spec 用 "property"，但 Python @property 冲突
    kind: str = "assert"  # assert / assume / cover

    clock: ClockIR = field(default_factory=ClockIR)
    disable_expr: str = ""

    # 触发
    trigger: TriggerIR = field(default_factory=TriggerIR)

    # obligations（扁平列表）
    obligations: list[ObligationIR] = field(default_factory=list)

    # 展开路径
    match_paths: list[MatchPathIR] = field(default_factory=list)

    # failure
    failure_conditions: list[FailureConditionIR] = field(default_factory=list)
    disable_obligation: ObligationIR | None = None

    # 高级 sequence / sampled function 的用户语义摘要
    semantic_notes: list[SemanticNoteIR] = field(default_factory=list)

    # vacuity
    vacuity_checks: list[str] = field(default_factory=list)

    # lowering
    lowering_status: LoweringStatus = LoweringStatus.EXACT
    diagnostics: list[DiagnosticIR] = field(default_factory=list)
    path_total_count: int = 0
    path_returned_count: int = 0
    path_enumeration_complete: bool = True
