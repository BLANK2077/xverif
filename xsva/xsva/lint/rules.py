"""Lint 规则注册表。对齐 spec 第十九章。

诊断码表:
  XSVA-W001  missing disable iff
  XSVA-W002  antecedent is constant false
  XSVA-W003  antecedent is constant true
  XSVA-W004  large delay range
  XSVA-W005  unbounded delay
  XSVA-W006  advanced construct detected
  XSVA-W007  local variable update inside repetition
  XSVA-W008  multi-clock property
  XSVA-W009  macro detected
  XSVA-W010  unsupported assignment form
  XSVA-W011  sampled function dependency is incomplete
  XSVA-E001  failed to parse property
  XSVA-E002  property not found
  XSVA-E003  unbalanced parentheses
  XSVA-E004  top-level implication not found
"""

from __future__ import annotations

RULES: dict[str, dict] = {
    "XSVA-W001": {"severity": "warning", "msg": "Property has no disable iff. Reset behavior may be unclear."},
    "XSVA-W002": {"severity": "warning", "msg": "Antecedent is constant false. Assertion may be vacuous."},
    "XSVA-W003": {"severity": "warning", "msg": "Antecedent is constant true. Property starts a new attempt every cycle."},
    "XSVA-W004": {"severity": "warning", "msg": "Large delay range may create many candidate match paths."},
    "XSVA-W005": {"severity": "warning", "msg": "Unbounded delay cannot be represented as a finite timeline."},
    "XSVA-W006": {"severity": "warning", "msg": "Advanced SVA construct detected. Timeline lowering may be partial."},
    "XSVA-W007": {"severity": "warning", "msg": "Local variable update inside repetition creates path-dependent state."},
    "XSVA-W008": {"severity": "warning", "msg": "Multi-clock property is not fully supported."},
    "XSVA-W009": {"severity": "warning", "msg": "Macro detected. Preprocess source for accurate parsing."},
    "XSVA-W010": {"severity": "warning", "msg": "Unsupported assignment form."},
    "XSVA-W011": {"severity": "warning", "msg": "Sampled function dependency is incomplete."},
    "XSVA-E001": {"severity": "error", "msg": "Failed to parse property."},
    "XSVA-E002": {"severity": "error", "msg": "Property not found."},
    "XSVA-E003": {"severity": "error", "msg": "Unbalanced parentheses."},
    "XSVA-E004": {"severity": "error", "msg": "Top-level implication not found."},
}


def rule_message(code: str) -> str:
    return RULES.get(code, {}).get("msg", code)


def rule_severity(code: str) -> str:
    return RULES.get(code, {}).get("severity", "warning")
