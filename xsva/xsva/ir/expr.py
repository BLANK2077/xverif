"""Expression IR：信号的轻量级语义提取。

对齐 spec 第九章。
评审意见 #2 改进：SignalRef 独立类型，区分层次化路径和位选。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .common import SourceSpan


@dataclass(frozen=True)
class SignalRef:
    """单一信号引用，区分层次路径与位选。

    示例：
      - "req"          → segments=("req",), bit_select=None
      - "data[7:0]"    → segments=("data",), bit_select=(7, 0)
      - "top.u.sig"    → segments=("top", "u", "sig"), bit_select=None, is_hierarchical=True
    """

    segments: tuple[str, ...]
    bit_select: tuple[int, int] | None = None
    is_hierarchical: bool = False

    @property
    def name(self) -> str:
        if self.is_hierarchical:
            return ".".join(self.segments)
        return self.segments[0] if self.segments else ""

    @classmethod
    def from_string(cls, raw: str) -> "SignalRef":
        """从原始字符串解析信号引用。处理 '.' 和 '[]' 位选。"""
        # 去掉位选部分
        bit_select: tuple[int, int] | None = None
        name_part = raw
        if "[" in raw and raw.endswith("]"):
            idx = raw.index("[")
            name_part = raw[:idx]
            sel = raw[idx + 1 : -1]
            if ":" in sel:
                left, right = sel.split(":", 1)
                bit_select = (int(left.strip()), int(right.strip()))
            else:
                bit = int(sel.strip())
                bit_select = (bit, bit)

        # 检查层次化
        is_hierarchical = "." in name_part
        segments = tuple(name_part.split(".")) if is_hierarchical else (name_part,)
        return cls(segments=segments, bit_select=bit_select, is_hierarchical=is_hierarchical)


@enum.unique
class ExprKind(str, enum.Enum):
    """表达式种类。对齐 spec 第九章。"""

    RAW = "raw"
    IDENTIFIER = "identifier"
    LITERAL = "literal"
    SYSTEM_FUNC = "system_func"
    UNARY = "unary"
    BINARY = "binary"
    OPAQUE = "opaque"


@dataclass
class SampleDependencyIR:
    """sampled value function 的依赖信息。对齐 spec 第九章。"""

    func: str  # $past / $rose / $fell / $stable / $changed / $isunknown
    expr: str
    current_cycle: int = 0
    reference_cycle: int | None = None
    depth: int | None = None


@dataclass
class ExprIR:
    """表达式的轻量语义提取。

    当前表达式 IR 不构造完整 AST，只提取：
    - 信号列表（含层次路径、位选）
    - sampled function 调用
    - local variable 引用
    无法精确解析时标记 kind=OPAQUE，保留 raw 原文。
    """

    kind: ExprKind = ExprKind.RAW
    raw: str = ""

    # 操作符（BINARY / UNARY）
    op: str = ""

    # 信号引用（提取后区分层次+位选）
    signals: list[SignalRef] = field(default_factory=list)

    # local variable 引用
    local_refs: list[str] = field(default_factory=list)

    # sampled functions
    sampled_funcs: list[str] = field(default_factory=list)
    sample_dependencies: list[SampleDependencyIR] = field(default_factory=list)

    contains_x_sensitive_op: bool = False
    contains_sampled_func: bool = False

    span: SourceSpan = field(default_factory=SourceSpan)
