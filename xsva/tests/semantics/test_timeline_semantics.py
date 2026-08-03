"""Timeline semantics tests for the xsva MVP subset."""

from xsva.ir.diagnostics import DiagnosticBag
from xsva.lower.sequence_to_timeline import lower_sequence_to_timeline
from xsva.lower.surface_to_sequence import lower_surface_to_sequence
from xsva.parser.property_parser import PropertyParser
from xsva.parser.scanner import Scanner


def _timeline(source: str, name: str, *, max_paths: int = 10):
    diag = DiagnosticBag()
    parser = PropertyParser(Scanner(source, file="<test>"), diag)
    surfaces = parser.parse_file()
    surface = next(s for s in surfaces if s.name == name)
    seq = lower_surface_to_sequence(surface, diag)
    timeline = lower_sequence_to_timeline(
        seq,
        surface_ir=surface,
        max_paths=max_paths,
        diag=diag,
    )
    return timeline


def _single_obligation(source: str, name: str):
    timeline = _timeline(source, name)
    assert len(timeline.obligations) == 1
    return timeline.obligations[0]


def test_overlapped_implication_cycle_zero():
    ob = _single_obligation("""
property p;
  req |-> ack;
endproperty
""", "p")
    assert ob.expr == "ack"
    assert ob.cycle == 0


def test_nonoverlapped_implication_cycle_one():
    ob = _single_obligation("""
property p;
  req |=> ack;
endproperty
""", "p")
    assert ob.expr == "ack"
    assert ob.cycle == 1


def test_fixed_delay_cycles_accumulate_after_implication():
    ob = _single_obligation("""
property p;
  req |-> ##2 ack;
endproperty
""", "p")
    assert ob.cycle == 2

    ob = _single_obligation("""
property p;
  req |=> ##2 ack;
endproperty
""", "p")
    assert ob.cycle == 3


def test_delay_range_becomes_eventually_window():
    ob = _single_obligation("""
property p;
  req |-> ##[1:4] ack;
endproperty
""", "p")
    assert ob.kind.value == "eventually"
    assert ob.window.start == 1
    assert ob.window.end == 4


def test_delay_range_suffix_expands_paths():
    timeline = _timeline("""
property p;
    req |-> ##[1:3] ack ##1 done;
endproperty
""", "p")
    cycles = [[ob.cycle for ob in path.obligations] for path in timeline.match_paths]
    assert cycles == [[1, 2], [2, 3], [3, 4]]
    assert timeline.path_total_count == 3
    assert timeline.path_returned_count == 3
    assert timeline.path_enumeration_complete is True


def test_local_capture_in_trigger_and_dependency():
    timeline = _timeline("""
property p;
  logic [31:0] v;
  @(posedge clk) disable iff (!rst_n)
  (req, v = data) |-> ##[1:4] ack && rsp == v;
endproperty
""", "p")
    assert timeline.clock.signal == "clk"
    assert timeline.disable_expr == "! rst_n"
    assert timeline.trigger.expr == "req"
    assert [(c.var, c.value_expr) for c in timeline.trigger.captures] == [("v", "data")]
    assert timeline.obligations[0].depends_on_captures == ["v"]


def test_first_match_uses_semantic_note_not_misleading_fixed_cycle():
    timeline = _timeline("""
property p;
  req |-> first_match(##[1:4] ack) ##1 done;
endproperty
""", "p")
    note_text = " ".join(n.text for n in timeline.semantic_notes)
    assert "first match at cycle +1 to +4" in note_text
    assert "done must be true 1 clk after that first ack" in note_text
    assert all(ob.expr != "done" or ob.cycle != 5 for ob in timeline.obligations)


def test_advanced_sequence_raw_exprs_become_semantic_notes_not_point_obligations():
    cases = {
        "throughout": """
property p;
  req |-> valid throughout (ack ##1 done);
endproperty
""",
        "intersect": """
property p;
  req |-> (a ##1 b) intersect (c ##1 d);
endproperty
""",
        "within": """
property p;
  req |-> (a ##1 b) within (c ##[1:3] d);
endproperty
""",
    }
    for kind, source in cases.items():
        timeline = _timeline(source, "p")
        assert any(n.kind == kind for n in timeline.semantic_notes)
        assert not timeline.obligations


def test_repeat_summaries():
    cases = {
        "repeat_consecutive": ("req |-> ack[*3];", "hold continuously for 3 clk cycles"),
        "repeat_goto": ("req |-> ack[->2];", "2nd occurrence of ack"),
        "repeat_nonconsecutive": ("req |-> ack[=2];", "match 2 times in total"),
    }
    for kind, (body, expected) in cases.items():
        timeline = _timeline(f"""
property p;
  {body}
endproperty
""", "p")
        note_text = " ".join(n.text for n in timeline.semantic_notes)
        assert any(n.kind == kind for n in timeline.semantic_notes)
        assert expected in note_text
        assert not timeline.obligations


def test_range_suffix_has_user_summary_while_preserving_paths():
    timeline = _timeline("""
property p;
    req |-> ##[1:3] ack ##1 done;
endproperty
""", "p")
    note_text = " ".join(n.text for n in timeline.semantic_notes)
    cycles = [[ob.cycle for ob in path.obligations] for path in timeline.match_paths]
    assert "ack must be true at cycle +1 to +3" in note_text
    assert "done must be true 1 clk after ack" in note_text
    assert cycles == [[1, 2], [2, 3], [3, 4]]


def test_local_capture_range_suffix_summary():
    timeline = _timeline("""
property p;
  logic [7:0] v;
  req |-> ##[1:3] (ack, v = id) ##1 done_id == v;
endproperty
""", "p")
    note_text = " ".join(n.text for n in timeline.semantic_notes)
    assert "ack must be true at cycle +1 to +3" in note_text
    assert "capturing v = id at that matching cycle" in note_text
    assert "done_id == v must be true 1 clk after ack" in note_text


def test_binary_advanced_sequence_summaries_name_each_sequence_and_relation():
    timeline = _timeline("""
property p;
  req |-> (a ##1 b) within (c ##[1:3] d);
endproperty
""", "p")
    texts = [n.text for n in timeline.semantic_notes]
    assert "Sequence 1: a must be true; b must be true 1 clk after a." in texts
    assert "Sequence 2: c must be true; d must be true 1 to 3 clk after c." in texts
    assert "Relation: sequence 1's matched interval must be contained within sequence 2's matched interval." in texts

    timeline = _timeline("""
property p;
  req |-> (a ##1 b) intersect (c ##1 d);
endproperty
""", "p")
    texts = [n.text for n in timeline.semantic_notes]
    assert "Sequence 1: a must be true; b must be true 1 clk after a." in texts
    assert "Sequence 2: c must be true; d must be true 1 clk after c." in texts
    assert "Relation: sequence 1 and sequence 2 must start on the same clk and end on the same clk." in texts


def test_disable_obligation_is_preserved():
    timeline = _timeline("""
property p;
  @(posedge clk) disable iff (!rst_n)
  req |-> ack;
endproperty
""", "p")
    assert timeline.disable_expr == "! rst_n"
    assert timeline.disable_obligation is not None
    assert timeline.disable_obligation.id == "disable"


def test_path_budget_marks_timeline_partial_with_exact_total():
    timeline = _timeline("""
property p;
  req |-> ##[1:20] x ##[1:10] y ##1 z;
endproperty
""", "p", max_paths=5)
    assert timeline.lowering_status.value == "partial"
    assert timeline.path_total_count == 200
    assert timeline.path_returned_count == 5
    assert timeline.path_enumeration_complete is False
    assert all(path.is_partial for path in timeline.match_paths)
    assert any(
        item.code == "XSVA-L001"
        and "returned 5 of 200 candidate paths" in item.message
        for item in timeline.diagnostics
    )


def test_nonoverlap_fixed_delay_still_accumulates():
    ob = _single_obligation("""
property p;
  req |=> ##2 ack;
endproperty
""", "p")
    assert ob.cycle == 3
