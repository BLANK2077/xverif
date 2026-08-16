"""xsva lint 模块 — 静态规则检查。对齐 spec 第十九章。

规则表:
  XSVA-W001  missing disable iff
  XSVA-W002  antecedent is constant false (vacuous)
  XSVA-W003  antecedent is constant true
  XSVA-W004  large delay range
  XSVA-W005  unbounded delay
  XSVA-W006  advanced construct detected
  XSVA-W007  local variable update inside repetition
  XSVA-W008  multi-clock property
  XSVA-W009  macro detected
  XSVA-W010  unsupported assignment form
  XSVA-W011  sampled function dependency is incomplete
"""

from __future__ import annotations

from xsva.ir.common import DiagnosticIR
from xsva.ir.timeline import TimelineIR

from . import vacuity, temporal, local_var


def lint_timeline(
    timeline: TimelineIR,
    surface_ir=None,
) -> list[DiagnosticIR]:
    """对 TimelineIR 执行所有 lint 规则，返回诊断列表。"""
    results: list[DiagnosticIR] = []

    results.extend(vacuity.check(timeline))
    results.extend(temporal.check(timeline))
    results.extend(local_var.check(timeline))

    if surface_ir:
        from xsva.frontend.macros import detect_macros
        if hasattr(surface_ir, 'raw_text'):
            results.extend(detect_macros(surface_ir.raw_text))

    return results
