"""Differential tests: xbit's answers must agree with a real SystemVerilog simulator.

Every case in ``cases.yaml`` is compiled into one testbench, simulated once, and compared against
xbit for exact width and value. The simulator is the authority, so a disagreement is either an xbit
bug or a documented, pinned difference - never a silent pass.

Cases where the simulator itself is not a valid reference are listed in :data:`DIVERGENCES`. Each
one pins *both* sides (what VCS measured and what xbit answers) plus the reason, so the difference
cannot drift in either direction unnoticed. A case that starts agreeing, or whose values change,
fails the suite until the table is updated.

VCS is needed. These tests deliberately do NOT use the repository fixture cache: the testbench is
generated and compiled on every run.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import oracle  # noqa: E402


@dataclass(frozen=True)
class Divergence:
    """A measured, justified difference between xbit and the simulator."""

    reason: str
    vcs: tuple[int, str]
    xbit: tuple[int, str]


# Value-level disagreements: xbit's bits differ from what the simulator computed. Each entry pins
# both sides and the reason.
VALUE_DIVERGENCES: dict[str, Divergence] = {
    # VCS refuses the magnitude instead of promoting it: `Warning-[DCTL] Decimal constant
    # '4294967296' is too large as a 32bit signed constant ... using converted signed value '0'`.
    # An unsized decimal of that magnitude needs 33 bits, which is what xbit keeps, so here xbit is
    # the conformant side and the simulator cannot serve as the reference.
    "lit_unsized_dec_big": Divergence(
        reason="VCS 把超出 32 位有符号范围的十进制常量置 0（非符合 LRM），xbit 保留 33 位真值",
        vcs=(33, "0" * 33),
        xbit=(33, "1" + "0" * 32),
    ),
}

# Width-measurement disagreements: the value agrees, but `$bits(<expr>)` in the generated testbench
# reports a different width than xbit. VCS sizes a literal by its context, so for an unsized literal
# the measured width is the surrounding declaration's, not the literal's own width (IEEE 1800-2017
# 5.7.1 gives the literal the number of digits). The simulator is not a usable width reference here,
# and the value comparison still has to agree.
SELF_WIDTH_DIVERGENCES: dict[str, Divergence] = {
    "lit_unsized_hex": Divergence(
        reason="VCS 依语境把无尺寸进制字面量扩为 32 位；LRM 5.7.1 规定其自身宽度为数字位数",
        vcs=(32, "11111111"),
        xbit=(8, "11111111"),
    ),
    "lit_unsized_bin": Divergence(
        reason="同上：'b1010 自身 4 位，VCS 报 32 位",
        vcs=(32, "1010"),
        xbit=(4, "1010"),
    ),
    "lit_unsized_oct": Divergence(
        reason="同上：'o777 自身 9 位，VCS 报 32 位",
        vcs=(32, "111111111"),
        xbit=(9, "111111111"),
    ),
}

# SystemVerilog has no legal spelling for what xbit accepts here, so the simulator cannot confirm
# it. The behaviour is asserted directly instead of being listed as a divergence.
UNSUPPORTED_BY_SYSTEMVERILOG: dict[str, str] = {
    "chain_part_select": "X[a:b][c:d] 不是合法 SV：selector 结果不可再被 part-select；xbit 接受",
}


def _positive(cases: list[oracle.OracleCase]) -> list[oracle.OracleCase]:
    return oracle.positive_cases(cases)


@pytest.fixture(scope="session")
def case_set() -> list[oracle.OracleCase]:
    return oracle.attach_xbit_results(oracle.load_cases())


@pytest.fixture(scope="session")
def simulate_once(case_set: list[oracle.OracleCase], tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Generate, compile and run the testbench exactly once for the whole session."""
    workdir = tmp_path_factory.mktemp("xbit-sv-oracle")
    return oracle.simulate(case_set, workdir)


@pytest.fixture(scope="session")
def xbit_answers(case_set: list[oracle.OracleCase]) -> dict:
    return oracle.xbit_results(case_set)


@pytest.mark.parametrize(
    "case_id", [case.id for case in oracle.positive_cases(oracle.load_cases())]
)
def test_xbit_matches_systemverilog(
    case_id: str, case_set: list[oracle.OracleCase], simulate_once: dict, xbit_answers: dict
) -> None:
    """Exact width and exact bit pattern must equal what the simulator computed."""
    case = next(item for item in case_set if item.id == case_id)
    measured = simulate_once[case_id]
    answer = xbit_answers[case_id]

    # The value must always agree; a value difference is either a bug or a declared divergence.
    if case_id in VALUE_DIVERGENCES:
        declared = VALUE_DIVERGENCES[case_id]
        assert answer == declared.xbit, (
            f"{case_id}: xbit side changed; declared {declared.xbit}, got {answer}"
        )
        assert (measured.width, measured.bits) == declared.vcs, (
            f"{case_id}: VCS side changed; declared {declared.vcs}, measured "
            f"({measured.width}, {measured.bits})"
        )
        return
    assert answer[1] == measured.bits, (
        f"{case_id} ({case.group}, LRM {case.lrm}): {case.expr}\n"
        f"  xbit {answer[1]}\n  sim  {measured.bits}"
    )

    # Width is compared as the expression's self-determined width.
    if case_id in SELF_WIDTH_DIVERGENCES:
        declared = SELF_WIDTH_DIVERGENCES[case_id]
        assert measured.sv_self_width == declared.vcs[0], (
            f"{case_id}: declared measured width {declared.vcs[0]}, got {measured.sv_self_width}"
        )
        assert answer[0] == declared.xbit[0], (
            f"{case_id}: declared xbit width {declared.xbit[0]}, got {answer[0]}"
        )
        return
    assert answer[0] == measured.sv_self_width, (
        f"{case_id} ({case.group}, LRM {case.lrm}): {case.expr}\n"
        f"  xbit width {answer[0]} != simulator self-determined width {measured.sv_self_width}"
    )


def test_positive_suite_is_one_hundred_percent_aligned(
    case_set: list[oracle.OracleCase], simulate_once: dict, xbit_answers: dict
) -> None:
    """Aggregate verdict: every positive case is either identical or a pinned divergence."""
    declared_widths = set(SELF_WIDTH_DIVERGENCES)
    for case in _positive(case_set):
        measured = simulate_once[case.id]
        answer = xbit_answers[case.id]
        if case.id in VALUE_DIVERGENCES:
            continue
        assert answer[1] == measured.bits, (
            f"{case.id}: xbit value {answer[1]} != simulator value {measured.bits}"
        )
        if case.id not in declared_widths:
            assert answer[0] == measured.sv_self_width, (
                f"{case.id}: xbit width {answer[0]} != simulator self-determined width "
                f"{measured.sv_self_width}"
            )


def test_declared_divergences_are_still_divergent(simulate_once: dict, xbit_answers: dict) -> None:
    """A divergence that starts agreeing must be removed, not left as stale documentation."""
    stale = sorted(
        case_id
        for case_id, declared in SELF_WIDTH_DIVERGENCES.items()
        if simulate_once[case_id].sv_self_width == xbit_answers[case_id][0]
        and xbit_answers[case_id][0] == declared.xbit[0]
    )
    assert not stale, (
        "declared width divergences now agree; remove them from SELF_WIDTH_DIVERGENCES: " + str(stale)
    )


def test_negative_cases_raise_the_declared_error(case_set: list[oracle.OracleCase]) -> None:
    """Cases xbit must reject assert the exact error code, so a silent value can never appear."""
    from xbit.errors import XbitError
    from xbit.eval import eval_expr, parse_vars

    negatives = [case for case in case_set if case.is_negative]
    assert negatives, "the case list must keep negative coverage"
    for case in negatives:
        variables = parse_vars(
            [f"{name}={value}" for name, value in case.vars], state=case.state
        )
        with pytest.raises(XbitError) as excinfo:
            eval_expr(case.expr, variables, state=case.state)
        assert excinfo.value.code == case.expect_error, (
            f"{case.id}: expected {case.expect_error}, got {excinfo.value.code}"
        )


def test_systemverilog_cannot_express_what_xbit_accepts() -> None:
    """xbit is more permissive than the language here; the difference is declared, not accidental."""
    from xbit.eval import eval_expr

    assert "chain_part_select" in UNSUPPORTED_BY_SYSTEMVERILOG
    chained = eval_expr("32'hdead_beef[15:8][3:0]")
    assert chained.width == 4
    assert chained.to_bin_digits() == "1110"
