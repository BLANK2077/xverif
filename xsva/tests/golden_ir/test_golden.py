"""Golden IR 基线测试。

对每个 golden_ir/<case>/input.sva：
1. 解析 → SurfaceIR
2. 编译 → SequenceIR
3. 编译 → TimelineIR
4. 与 golden *.json diff 比较
"""

import json
from pathlib import Path

from xsva.parser.scanner import Scanner
from xsva.ir.diagnostics import DiagnosticBag
from xsva.parser.property_parser import PropertyParser
from xsva.lower.surface_to_sequence import lower_surface_to_sequence
from xsva.lower.sequence_to_timeline import lower_sequence_to_timeline
from xsva.cli import _serialize_timeline_ir, _serialize_sequence_ir, _serialize_surface_ir


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_golden_surface_ir(run_golden_case):
    """验证 SurfaceIR 与 golden surface_ir.json 匹配。"""
    surface, seq_ir, timeline, diag, case_dir = run_golden_case
    golden = _load_json(case_dir / "surface_ir.json")

    actual = _serialize_surface_ir(surface)
    assert actual == golden


def test_golden_sequence_ir(run_golden_case):
    """验证 SequenceIR 与 golden sequence_ir.json 匹配。"""
    surface, seq_ir, timeline, diag, case_dir = run_golden_case
    golden = _load_json(case_dir / "sequence_ir.json")

    actual = _serialize_sequence_ir(seq_ir)
    assert actual == golden


def test_golden_timeline_ir(run_golden_case):
    """验证 TimelineIR 与 golden timeline_ir.json 匹配。"""
    surface, seq_ir, timeline, diag, case_dir = run_golden_case
    golden = _load_json(case_dir / "timeline_ir.json")

    actual = _serialize_timeline_ir(timeline)
    assert actual == golden


def test_golden_no_errors(run_golden_case):
    """验证 golden case 不会产生诊断错误。"""
    surface, seq_ir, timeline, diag, case_dir = run_golden_case
    errors = diag.errors()
    assert len(errors) == 0, f"Unexpected errors: {[e.message for e in errors]}"
