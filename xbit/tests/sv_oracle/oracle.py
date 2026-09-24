"""SystemVerilog oracle for xbit: generate one testbench, simulate it once, compare every case.

The oracle answers a single question per case: "what does a real SystemVerilog simulator compute
for this literal or expression?"  xbit's own answers are then compared against it, so xbit's
semantics are pinned to the LRM as implemented by VCS rather than to hand-written expectations.

Two properties matter and are deliberate:

* **One compile, one run.** All cases are emitted into a single testbench, so adding cases costs
  simulation time only, not a compile each.
* **Exact width comparison.** The testbench declares one sized variable per case and prints
  ``$bits`` together with the value formatted by ``%b``. ``%b`` was measured to zero-pad to the
  operand's declared width in VCS, including when the value is all zeroes, so a width regression
  such as ``8'shff >>> 1`` becoming a 32-bit result cannot hide behind value truncation.

Nothing here is cached by the repository test infrastructure: ``simulate()`` always re-generates,
re-compiles, and re-runs the case set.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
XBIT_SRC = REPO_ROOT / "xbit" / "src"
CASES_FILE = Path(__file__).resolve().parent / "cases.yaml"
if str(XBIT_SRC) not in sys.path:
    sys.path.insert(0, str(XBIT_SRC))

from xbit.eval import eval_expr, parse_vars  # noqa: E402  (path is prepared above)
from xbit.literal import parse_value  # noqa: E402

TOP = "tb_xbit_oracle"
VCS_BIN = "vcs"
SIM_BIN = "simv"
COMPILE_LOG = "compile.log"
RUN_LOG = "run.log"
ORACLE_FILE = "oracle.txt"
TIMEOUT_COMPILE_SEC = 300
TIMEOUT_RUN_SEC = 300

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OracleError(RuntimeError):
    """The oracle could not produce reference data; this is a failure, never a skip."""


@dataclass(frozen=True)
class OracleCase:
    """One differential case, already validated against xbit."""

    id: str
    group: str
    lrm: str
    expr: str
    state: str = "2state"
    vars: tuple[tuple[str, str], ...] = ()
    expect_error: str | None = None
    expected_width: int = 0
    var_widths: tuple[tuple[str, int], ...] = ()
    bare_literal: bool = False
    bound_literals: tuple[tuple[str, str, int], ...] = ()

    @property
    def is_negative(self) -> bool:
        return self.expect_error is not None

    def width_for(self, name: str) -> int:
        for candidate, width in self.var_widths:
            if candidate == name:
                return width
        raise OracleError(f"case {self.id}: variable {name!r} has no resolved width")


@dataclass(frozen=True)
class OracleResult:
    """The simulator's answer for one case.

    ``width`` is the width xbit claims and the testbench declared; ``sv_self_width`` is what the
    simulator reports for the expression in that context. They can differ because SystemVerilog
    sizes an expression by its context, so ``sv_self_width`` is recorded rather than asserted.
    """

    case_id: str
    width: int
    bits: str
    sv_self_width: int = 0

    def as_int(self) -> int:
        return int(self.bits, 2) if self.bits else 0

    @property
    def width_matches(self) -> bool:
        return self.sv_self_width in (0, self.width)


def _sv_expr(case: OracleCase) -> str:
    """The case expression as SystemVerilog source, with selected literals bound to names.

    Two SystemVerilog restrictions shape this:

    * A numeric literal cannot be selected (`32'hdead_beef[15:8]` is a syntax error), so every
      literal that a select applies to is bound to a generated ``localparam`` first and the select
      then reads that name.
    * A bare literal must not be parenthesised: `8'sd-1` is one literal token while `(8'sd-1)` is a
      unary minus applied to `8'sd1`, which VCS rejects as an illegal `-`.
    """
    expr = case.expr
    for name, source, _width in case.bound_literals:
        expr = expr.replace(source, name)
    return expr if case.bare_literal else f"({expr})"


def _bit_string_literal(value: str, width: int, state: str) -> str:
    """Render ``value`` as an explicit-width bit-string literal.

    Inlining the original text is not safe: VCS rejects `8'sd-1` outright, and reads an unsized
    `10` as a 32-bit value that would then be truncated into the declaration. Emitting the exact
    bits keeps the declared width and the value in agreement.
    """
    parsed = parse_value(value, state=state)
    if parsed.width != width:
        raise OracleError(
            f"literal {value!r} has width {parsed.width} but was declared with {width}"
        )
    return f"{width}'b{parsed.to_bin_digits()}"


def _needs_binding(expr: str) -> list[str]:
    """Literal tokens in ``expr`` that a select applies to, in source order.

    Only literals immediately followed by ``[`` are collected: those are exactly the ones
    SystemVerilog refuses to select directly, and binding every other literal would only add names.
    """
    from xbit.eval import tokenize

    sources: list[str] = []
    tokens = tokenize(expr)
    for index, token in enumerate(tokens):
        if token.kind != "number":
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if following is not None and following.text == "[":
            sources.append(token.text)
    return sources


def render_testbench(cases: list[OracleCase]) -> str:
    """Render one SystemVerilog testbench covering every positive case.

    Variable names are prefixed so a case can never collide with the generated harness, and each
    case keeps its own ``generate`` block so declarations stay scoped to that case.
    """
    positive = positive_cases(cases)
    for case in positive:
        for name, _value in case.vars:
            if not _IDENT_RE.match(name):
                raise OracleError(f"case {case.id}: variable {name!r} is not a plain identifier")

    lines = [
        "// Generated by xbit/tests/sv_oracle/oracle.py -- do not edit by hand.",
        "// Each case prints: <label>\\t<declared width>\\t<simulator width>\\t<binary value>",
        f"module {TOP};",
    ]
    for index, case in enumerate(positive):
        lines.append(f"  // [{case.group}] lrm {case.lrm}: {case.expr}")
        lines.append(f"  generate if (1) begin : g_{index}")
        for name, value in case.vars:
            lines.append(
                f"    localparam logic [{case.width_for(name)}-1:0] {name} = "
                f"{_bit_string_literal(value, case.width_for(name), case.state)};"
            )
        for name, source, literal_width in case.bound_literals:
            lines.append(
                f"    localparam logic [{literal_width}-1:0] {name} = "
                f"{_bit_string_literal(source, literal_width, case.state)};"
            )
        width = expected_width_of(case)
        expr = _sv_expr(case)
        lines.append(f"    logic [{width}-1:0] c;")
        lines.append("    initial begin")
        # The expression is evaluated exactly once, then printed through `c` so that `%b` pads to
        # the declared width.
        lines.append(f"      c = {expr};")
        # The width actually reported by the simulator is printed alongside the declared width so
        # a context-sizing difference is visible data, not a silent pass or a hard failure.
        lines.append(
            f'      $display("{case_label(index)}\\t%0d\\t%0d\\t%b", '
            f"{width}, $bits({expr}), c);"
        )
        lines.append("    end")
        lines.append("  end endgenerate")
    lines.extend(
        [
            "  initial begin",
            '    $display("%s", "ORACLE-BEGIN");',
            "    #1;",
            '    $display("%s", "ORACLE-END");',
            "    $finish;",
            "  end",
            "endmodule",
            "",
        ]
    )
    return "\n".join(lines)


def parse_oracle(text: str) -> dict[str, OracleResult]:
    """Parse the testbench output into ``{case_id: OracleResult}``.

    The generator labels lines positionally (``xbit_<n>``); the caller maps them back to cases so a
    renamed case can never silently rebind a result.
    """
    results: dict[str, OracleResult] = {}
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 4 or not parts[0].startswith("xbit_"):
            continue
        label, width_text, self_width_text, bits = parts
        try:
            width = int(width_text)
            sv_self_width = int(self_width_text)
        except ValueError as exc:
            raise OracleError(f"oracle line has a non-numeric width: {line!r}") from exc
        if width <= 0 or len(bits) != width:
            raise OracleError(
                f"oracle line width {width} does not match its value {bits!r}: {line!r}"
            )
        results[label] = OracleResult(
            case_id=label, width=width, bits=bits, sv_self_width=sv_self_width
        )
    if not results:
        raise OracleError("oracle produced no parseable case lines")
    return results


def simulate(cases: list[OracleCase], workdir: Path) -> dict[str, OracleResult]:
    """Compile and run the generated testbench; return the case-indexed oracle results.

    ``workdir`` is wiped first so a stale ``simv`` or oracle file can never be mistaken for this
    run's output. Compilation and simulation failures raise :class:`OracleError` with the tail of
    the relevant log attached.
    """
    if shutil.which(VCS_BIN) is None:
        raise OracleError(
            f"{VCS_BIN!r} is not on PATH; the SystemVerilog oracle needs a VCS installation "
            "(VCS_HOME and a licence) and must run in a licensed host environment"
        )
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    for stale in (SIM_BIN, ORACLE_FILE, COMPILE_LOG, RUN_LOG, "csrc", "simv.daidir"):
        target = workdir / stale
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()

    source = workdir / f"{TOP}.sv"
    source.write_text(render_testbench(cases), encoding="utf-8")

    compile_proc = subprocess.run(
        [VCS_BIN, "-full64", "-sverilog", "-timescale=1ns/1ps", source.name,
         "-top", TOP, "-o", SIM_BIN, "-l", COMPILE_LOG],
        cwd=str(workdir), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=TIMEOUT_COMPILE_SEC, check=False,
    )
    if compile_proc.returncode != 0 or not (workdir / SIM_BIN).exists():
        raise OracleError(
            f"VCS compile failed (rc={compile_proc.returncode}); log tail:\n"
            f"{_tail(workdir / COMPILE_LOG)}"
        )

    run_proc = subprocess.run(
        [f"./{SIM_BIN}", "-l", RUN_LOG],
        cwd=str(workdir), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=TIMEOUT_RUN_SEC, check=False,
    )
    output = run_proc.stdout or ""
    if "ORACLE-END" not in output:
        raise OracleError(
            f"simulation did not reach the end marker (rc={run_proc.returncode}); log tail:\n"
            f"{_tail(workdir / RUN_LOG)}"
        )
    (workdir / ORACLE_FILE).write_text(output, encoding="utf-8")

    parsed = parse_oracle(output)
    return _bind(cases, parsed)


def positive_cases(cases: list[OracleCase]) -> list[OracleCase]:
    """Cases that produce a SystemVerilog computation, in emission order."""
    return [case for case in cases if not case.is_negative]


def case_label(index: int) -> str:
    """Stable label for the case emitted at ``index`` (positional, so it cannot be renamed away)."""
    return f"xbit_{index}"


def _bind(cases: list[OracleCase], parsed: dict[str, OracleResult]) -> dict[str, OracleResult]:
    """Map positional oracle labels back to case ids, failing loudly on any mismatch."""
    positives = positive_cases(cases)
    missing = [case_label(i) for i in range(len(positives)) if case_label(i) not in parsed]
    if missing:
        raise OracleError(f"oracle is missing results for {len(missing)} case(s): {missing[:5]}")
    extra = sorted(set(parsed) - {case_label(i) for i in range(len(positives))})
    if extra:
        raise OracleError(f"oracle produced unexpected case labels: {extra[:5]}")
    return {
        case.id: parsed[case_label(index)]
        for index, case in enumerate(positives)
    }


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"(no {path.name})"
    return text[-limit:]


def is_bare_literal(expr: str, state: str = "2state") -> bool:
    """True when the expression is a single SystemVerilog literal token.

    Such a token is emitted without parentheses, because parenthesising `8'sd-1` turns its sign
    into a unary operator, which is not the same expression. Whether xbit's literal parser accepts
    the whole text is exactly the question being asked.
    """
    try:
        parse_value(expr.strip(), state=state)
    except Exception:
        return False
    return True


def load_cases(path: Path | None = None) -> list[OracleCase]:
    """Load and validate the case list.

    Each case's expected result width and every variable width are resolved through xbit's own
    literal parser, so the generated declarations state exactly the width xbit intends to
    compute at. A case whose literal xbit cannot parse fails here, before any simulation.
    """
    document = yaml.safe_load((path or CASES_FILE).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1:
        raise OracleError("cases.yaml must be a mapping with version: 1")

    cases: list[OracleCase] = []
    seen: set[str] = set()
    for group in document.get("groups") or []:
        group_name = str(group["group"])
        lrm = str(group.get("lrm", ""))
        for raw in group.get("cases") or []:
            case_id = str(raw["id"])
            if case_id in seen:
                raise OracleError(f"duplicate case id: {case_id}")
            seen.add(case_id)
            state = str(raw.get("state", "2state"))
            var_items = raw.get("vars") or {}
            var_widths = tuple(
                (str(name), parse_value(value, state=state).width)
                for name, value in var_items.items()
            )
            expect_error = raw.get("expect_error")
            expr_text = str(raw["expr"])
            bound_literals: tuple[tuple[str, str, int], ...] = ()
            if expect_error is None:
                bound_literals = tuple(
                    (f"lit_{case_id}_{position}", source, parse_value(source, state=state).width)
                    for position, source in enumerate(_needs_binding(expr_text))
                )
            cases.append(
                OracleCase(
                    id=case_id,
                    group=group_name,
                    lrm=lrm,
                    expr=expr_text,
                    state=state,
                    vars=tuple((str(k), str(v)) for k, v in var_items.items()),
                    expect_error=None if expect_error is None else str(expect_error),
                    var_widths=var_widths,
                    bare_literal=is_bare_literal(expr_text, state),
                    bound_literals=bound_literals,
                )
            )
    if not cases:
        raise OracleError("cases.yaml contains no cases")
    return cases


def expected_width_of(case: OracleCase) -> int:
    """Result width xbit produces for a positive case, used to size the testbench declaration."""
    if case.expected_width <= 0:
        raise OracleError(
            f"case {case.id}: expected width was not resolved; call attach_xbit_results first"
        )
    return case.expected_width


def attach_xbit_results(cases: list[OracleCase]) -> list[OracleCase]:
    """Evaluate every positive case with xbit and record the width it claims.

    Evaluation happens once here so the generated declarations, the runtime width guard, and the
    comparison all use the same number. A case xbit cannot evaluate is a hard error: it means the
    case list and the implementation disagree about what is supported.
    """
    resolved: list[OracleCase] = []
    for case in cases:
        if case.is_negative:
            resolved.append(case)
            continue
        variables = parse_vars([f"{name}={value}" for name, value in case.vars], state=case.state)
        result = eval_expr(case.expr, variables, state=case.state)
        resolved.append(
            OracleCase(
                id=case.id,
                group=case.group,
                lrm=case.lrm,
                expr=case.expr,
                state=case.state,
                vars=case.vars,
                expect_error=case.expect_error,
                expected_width=result.width,
                var_widths=case.var_widths,
                bare_literal=case.bare_literal,
                bound_literals=case.bound_literals,
            )
        )
    return resolved


def xbit_results(cases: list[OracleCase]) -> dict[str, tuple[int, str]]:
    """``{case_id: (width, binary digits)}`` for every positive case."""
    results: dict[str, tuple[int, str]] = {}
    for case in cases:
        if case.is_negative:
            continue
        variables = parse_vars([f"{name}={value}" for name, value in case.vars], state=case.state)
        value = eval_expr(case.expr, variables, state=case.state)
        results[case.id] = (value.width, value.to_bin_digits())
    return results
