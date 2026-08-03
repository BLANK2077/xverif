from __future__ import annotations

import json
import sys
from typing import Any

from .. import ops
from ..check import extract_values, run_check
from ..errors import EvalError
from ..eval import eval_expr
from ..format import failure, success, validate_response
from ..literal import parse_value


_METHOD_PARAMS = {
    "xbit.conv": ({"value"}, {"state"}),
    "xbit.eval": ({"expr"}, {"vars", "state"}),
    "xbit.slice": ({"value", "msb", "lsb"}, {"state"}),
    "xbit.concat": ({"values"}, {"state"}),
    "xbit.repeat": ({"count", "value"}, {"state"}),
    "xbit.mask": ({"width"}, {"lsb"}),
    "xbit.popcount": ({"value"}, {"state"}),
    "xbit.check": ({"expr"}, {"vars", "state"}),
}


def _validate_request(request: Any) -> tuple[str, dict]:
    if not isinstance(request, dict):
        raise EvalError("request must be an object")
    if set(request) - {"id", "jsonrpc", "method", "params"}:
        raise EvalError("request contains unknown top-level fields")
    if "jsonrpc" in request and request["jsonrpc"] != "2.0":
        raise EvalError("jsonrpc must equal 2.0")
    if "id" in request and (
        not isinstance(request["id"], (str, int))
        or isinstance(request["id"], bool)
    ):
        raise EvalError("id must be a string or integer")
    method = request.get("method")
    if not isinstance(method, str) or method not in _METHOD_PARAMS:
        raise EvalError("unknown method", method=method)
    params = request.get("params")
    if not isinstance(params, dict):
        raise EvalError("params must be an object")
    required, optional = _METHOD_PARAMS[method]
    if required - set(params):
        raise EvalError("params are missing required fields")
    if set(params) - required - optional:
        raise EvalError("params contain unknown fields")
    state = params.get("state", "2state")
    if state not in {"2state", "4state"}:
        raise EvalError("state must be 2state or 4state", state=state)
    for field in ("value", "expr"):
        if field in params and not isinstance(params[field], str):
            raise EvalError(f"params.{field} must be a string")
    for field in ("msb", "lsb", "count", "width"):
        if field in params and (
            not isinstance(params[field], int) or isinstance(params[field], bool)
        ):
            raise EvalError(f"params.{field} must be an integer")
    if "values" in params and (
        not isinstance(params["values"], list)
        or not params["values"]
        or any(not isinstance(item, str) for item in params["values"])
    ):
        raise EvalError("params.values must be a non-empty string array")
    if "vars" in params and (
        not isinstance(params["vars"], dict)
        or any(not isinstance(name, str) or not name
               or not isinstance(value, (str, int)) or isinstance(value, bool)
               for name, value in params["vars"].items())
    ):
        raise EvalError("params.vars must map names to string or integer literals")
    return method, params


def dispatch(request: dict) -> dict:
    method, params = _validate_request(request)
    state = params.get("state", "2state")
    if method == "xbit.conv":
        return success("conv", result=parse_value(params["value"], state=state))
    if method == "xbit.eval":
        variables = extract_values(params.get("vars", {}), state=state)
        return success("eval", result=eval_expr(params["expr"], variables, state=state))
    if method == "xbit.slice":
        value = parse_value(params["value"], state=state)
        return success("slice", result=ops.slice_bits(value, params["msb"], params["lsb"]))
    if method == "xbit.concat":
        return success("concat", result=ops.concat([parse_value(v, state=state) for v in params["values"]]))
    if method == "xbit.repeat":
        return success("repeat", result=ops.repeat(params["count"], parse_value(params["value"], state=state)))
    if method == "xbit.mask":
        return success("mask", result=ops.mask(params["width"], params.get("lsb", 0)))
    if method == "xbit.popcount":
        return success("popcount", result=ops.popcount(parse_value(params["value"], state=state)))
    if method == "xbit.check":
        result = run_check(
            params["expr"],
            values_payload=params.get("vars", {}),
            state=state,
        )
        return success("check", result=result["result"], matched=result["matched"], evaluated=result["evaluated"])
    raise RuntimeError("validated xbit method has no dispatcher")


def wrap_response(request: dict[str, Any], payload: dict) -> dict:
    validate_response(payload)
    response = dict(payload)
    if "id" in request and isinstance(request["id"], (str, int)) and not isinstance(request["id"], bool):
        response["id"] = request["id"]
    if request.get("jsonrpc") == "2.0":
        response["jsonrpc"] = "2.0"
    return response


def serve() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        request: Any = None
        try:
            request = json.loads(line)
            payload = dispatch(request)
        except Exception as exc:
            request = request if isinstance(request, dict) else {}
            payload = failure(exc)
        response = wrap_response(request, payload)
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0
