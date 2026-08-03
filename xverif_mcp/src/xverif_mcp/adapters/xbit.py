"""Stateless xbit adapter — deterministic bit/expression calculator."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from xverif_mcp.import_paths import ensure_tool_import_paths

ensure_tool_import_paths()

from xbit import cli
from xbit.errors import EvalError
from xbit.format import failure, validate_response, xout_result


def _state(state: str) -> str:
    if state == "2":
        return "2state"
    if state == "4":
        return "4state"
    if isinstance(state, str):
        raise EvalError("state must be 2 or 4", state=state)
    raise EvalError("state must be the string '2' or '4'")


def _sign(signed: bool, unsigned: bool) -> bool | None:
    if not isinstance(signed, bool) or not isinstance(unsigned, bool):
        raise EvalError("signed and unsigned must be booleans")
    if signed and unsigned:
        raise EvalError("signed and unsigned are mutually exclusive")
    return True if signed else False if unsigned else None


def _width(width: int) -> int | None:
    if not isinstance(width, int) or isinstance(width, bool) or width < 0:
        raise EvalError("width must be a non-negative integer")
    return width or None


def _var_items(vars: Optional[dict]) -> list[str]:
    if vars is None:
        return []
    if not isinstance(vars, dict):
        raise EvalError("vars must be an object")
    items = []
    for name, value in vars.items():
        if not isinstance(name, str) or not name:
            raise EvalError("vars names must be non-empty strings")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise EvalError("vars values must be string or integer literals", name=name)
        items.append(f"{name}={value}")
    return items


def _format(payload: dict, output_format: str) -> Any:
    validate_response(payload)
    if output_format == "json":
        return payload
    if output_format == "xout":
        return xout_result(payload)
    raise EvalError("output_format must be json or xout")


def _argument_failure(op: str, error: Exception, output_format: str) -> Any:
    payload = failure(error, op=op)
    if output_format in {"json", "xout"}:
        return _format(payload, output_format)
    return payload


def _call(op: str, output_format: str, **kwargs: Any) -> Any:
    if output_format not in {"json", "xout"}:
        return _argument_failure(op, EvalError("output_format must be json or xout"), output_format)
    args = SimpleNamespace(command=op, **kwargs)
    try:
        payload = {
            "conv": cli.cmd_conv,
            "eval": cli.cmd_eval,
            "slice": cli.cmd_slice,
            "check": cli.cmd_check,
        }[op](args)
    except Exception as exc:
        payload = failure(exc, op=op)
    return _format(payload, output_format)


def bit_conv(value: str, width: int = 0, signed: bool = False,
             unsigned: bool = False, state: str = "2",
             output_format: str = "xout") -> Any:
    """Convert a value between radices and SV literal formats."""
    try:
        return _call("conv", output_format, value=value, state=_state(state),
                     width=_width(width), signed=_sign(signed, unsigned))
    except Exception as exc:
        return _argument_failure("conv", exc, output_format)


def bit_eval(expr: str, vars: Optional[dict] = None, width: int = 0,
             signed: bool = False, unsigned: bool = False,
             state: str = "2", output_format: str = "xout") -> Any:
    """Evaluate a deterministic bit/expression calculation."""
    try:
        return _call("eval", output_format, expr=expr, var=_var_items(vars),
                     state=_state(state), width=_width(width),
                     signed=_sign(signed, unsigned))
    except Exception as exc:
        return _argument_failure("eval", exc, output_format)


def bit_slice(value: str, msb: int, lsb: int, state: str = "2",
              output_format: str = "xout") -> Any:
    """Extract a bit slice from a value."""
    try:
        if not isinstance(msb, int) or isinstance(msb, bool) or not isinstance(lsb, int) or isinstance(lsb, bool):
            raise EvalError("msb and lsb must be integers")
        return _call("slice", output_format, value=value, msb=msb, lsb=lsb,
                     state=_state(state))
    except Exception as exc:
        return _argument_failure("slice", exc, output_format)


def bit_check(expr: str, vars: Optional[dict] = None,
              values: Optional[str] = None, state: str = "2",
              output_format: str = "xout") -> Any:
    """Check a bit expression against expected values."""
    try:
        var_items = _var_items(vars)
        if values is not None and not isinstance(values, str):
            raise EvalError("values must be a JSON file path")
        if var_items and values is not None:
            raise EvalError("vars and values are mutually exclusive")
        return _call("check", output_format, expr=expr, var=var_items,
                     values=values, state=_state(state))
    except Exception as exc:
        return _argument_failure("check", exc, output_format)
