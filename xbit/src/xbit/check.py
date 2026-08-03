from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .bitvector import BitVector
from .errors import ParseError
from .eval import eval_expr, parse_vars
from .literal import parse_value


def extract_values(payload: Any, *, state: str = "2state") -> dict[str, BitVector]:
    if isinstance(payload, (str, Path)):
        with open(payload, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ParseError("--values JSON must be an object")
    out: dict[str, BitVector] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key:
            raise ParseError("--values names must be non-empty strings")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ParseError("--values entries must be string or integer literals", name=key)
        out[key] = parse_value(value, state=state)
    return out


def run_check(
    expr: str,
    *,
    var_items: list[str] | None = None,
    values_file: str | None = None,
    values_payload: Any | None = None,
    state: str = "2state",
) -> dict:
    source_count = sum((bool(var_items), values_file is not None, values_payload is not None))
    if source_count > 1:
        raise ParseError("check accepts exactly one variable source: --var, --values, or values payload")
    variables: dict[str, BitVector] = {}
    if values_file is not None:
        variables = extract_values(values_file, state=state)
    elif values_payload is not None:
        variables = extract_values(values_payload, state=state)
    elif var_items:
        variables = parse_vars(var_items, state=state)
    result = eval_expr(expr, variables, state=state)
    matched = result.truthy()
    return {
        "matched": matched,
        "value": result.to_sv("b"),
        "result": result.to_result(),
        "evaluated": {name: value.to_sv("h") for name, value in sorted(variables.items())},
    }
