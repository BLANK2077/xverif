from xsva.ir.diagnostics import DiagnosticBag
from xsva.parser.expr_parser import ExprParser
from xsva.parser.scanner import Scanner


def _parse(source: str):
    diagnostics = DiagnosticBag()
    expression = ExprParser(Scanner(source, file="<expr>"), diagnostics).parse_expr()
    return expression, diagnostics


def _canonical(signal) -> str:
    suffix = ""
    if signal.bit_select:
        msb, lsb = signal.bit_select
        suffix = f"[{msb}]" if msb == lsb else f"[{msb}:{lsb}]"
    return signal.name + suffix


def test_sampled_argument_recursively_extracts_one_canonical_hierarchical_signal():
    expression, diagnostics = _parse("$past(top.u_bus.data[3:0], 2)")

    assert [_canonical(signal) for signal in expression.signals] == [
        "top.u_bus.data[3:0]",
    ]
    assert expression.sampled_funcs == ["$past"]
    assert len(expression.sample_dependencies) == 1
    assert expression.sample_dependencies[0].expr == "top . u_bus . data [ 3 : 0 ]"
    assert expression.sample_dependencies[0].depth == 2
    assert expression.sample_dependencies[0].reference_cycle == -2
    assert expression.dependency_complete is True
    assert diagnostics.diagnostics == []


def test_hierarchical_cursor_consumes_path_and_select_without_suffix_duplicates():
    expression, _ = _parse("top.u.sig[7] && top.u.sig[7] && other")

    assert [_canonical(signal) for signal in expression.signals] == [
        "top.u.sig[7]",
        "other",
    ]


def test_nested_sampled_functions_and_dynamic_select_dependencies_are_recursive():
    expression, diagnostics = _parse("$past($stable(top.gen[0].u.data[index]), 3)")

    assert [_canonical(signal) for signal in expression.signals] == [
        "top.gen[0].u.data",
        "index",
    ]
    assert expression.sampled_funcs == ["$past", "$stable"]
    assert [dependency.func for dependency in expression.sample_dependencies] == [
        "$past",
        "$stable",
    ]
    assert expression.dependency_complete is True
    assert diagnostics.diagnostics == []


def test_nested_past_dependencies_preserve_outer_to_inner_depth_order():
    expression, diagnostics = _parse("$past($past(top.sig, 2), 3)")

    assert [dependency.depth for dependency in expression.sample_dependencies] == [3, 2]
    assert [_canonical(signal) for signal in expression.signals] == ["top.sig"]
    assert diagnostics.diagnostics == []


def test_malformed_sampled_function_returns_typed_partial_diagnostic():
    expression, diagnostics = _parse("$past")

    assert expression.dependency_complete is False
    assert expression.signals == []
    assert expression.sample_dependencies[0].func == "$past"
    assert [item.code for item in diagnostics.diagnostics] == ["XSVA-W011"]


def test_empty_or_invalid_past_arguments_are_partial_not_internal_errors():
    empty, empty_diagnostics = _parse("$past()")
    invalid_depth, depth_diagnostics = _parse("$past(top.sig, depth)")

    assert empty.dependency_complete is False
    assert [item.code for item in empty_diagnostics.diagnostics] == ["XSVA-W011"]
    assert invalid_depth.dependency_complete is False
    assert [_canonical(signal) for signal in invalid_depth.signals] == ["top.sig"]
    assert invalid_depth.sample_dependencies[0].depth is None
    assert [item.code for item in depth_diagnostics.diagnostics] == ["XSVA-W011"]
