from __future__ import annotations

from dataclasses import fields

from xsva.ir.sequence import SeqNode, SeqNodeKind, SequenceIR
from xsva.ir.timeline import MatchPathIR, ObligationIR, TimelineIR, WindowIR


def _field_names(cls) -> set[str]:
    return {item.name for item in fields(cls)}


def test_sequence_ir_exposes_only_canonical_node_contract():
    assert {kind.value for kind in SeqNodeKind} == {
        "expr", "match_item", "delay", "concat", "repeat", "and", "or",
        "intersect", "throughout", "within", "first_match", "strong", "weak", "opaque",
    }
    assert {"delay", "capture_var", "capture_expr"}.isdisjoint(_field_names(SeqNode))
    assert {"nodes", "captures"}.isdisjoint(_field_names(SequenceIR))
    assert {"implication", "antecedent", "consequent"} <= _field_names(SequenceIR)
    for legacy_factory in ("sequence", "signal_match", "capture", "update", "empty"):
        assert not hasattr(SeqNode, legacy_factory)


def test_timeline_ir_exposes_only_canonical_fields():
    assert {"min_cycle", "max_cycle"}.isdisjoint(_field_names(WindowIR))
    assert "cycle_offset" not in _field_names(ObligationIR)
    assert "trigger_condition" not in _field_names(MatchPathIR)
    assert {
        "trigger", "match_paths", "disable_obligation", "path_total_count",
        "path_returned_count", "path_enumeration_complete",
    } <= _field_names(TimelineIR)
    for legacy_member in (
        "trigger_expr", "trigger_captures", "paths", "add_disable_obligation", "_compat_disable_obl",
    ):
        assert not hasattr(TimelineIR, legacy_member)
