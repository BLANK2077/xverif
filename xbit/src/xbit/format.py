from __future__ import annotations

import json
import re
from typing import Any

from .bitvector import BitVector
from .errors import XbitError


SCHEMA_RESULT = "xbit.result.v1"
SCHEMA_ERROR = "xbit.error.v1"
OPS = frozenset({
    "conv", "eval", "slice", "index", "concat", "repeat", "trunc",
    "zext", "sext", "reverse", "mask", "align", "popcount", "onehot",
    "onehot0", "gray2bin", "bin2gray", "check",
})
_BOOL_RESULT_OPS = frozenset({"eval", "onehot", "onehot0"})
_ERROR_DETAIL_TYPES = {
    "actual": str, "char": str, "count": int, "expected": str,
    "from_width": int, "literal": str, "lsb": int, "method": str,
    "msb": int, "name": str, "op": str, "pos": int, "state": str,
    "to": int, "to_width": int, "token": str, "var": str, "width": int,
}


class ResponseContractError(ValueError):
    pass


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ResponseContractError(f"{path}: {message}")


def _exact(value: Any, required: set[str], optional: set[str], path: str) -> None:
    _require(isinstance(value, dict), path, "expected object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    _require(not missing, path, f"missing required fields {missing!r}")
    _require(not unknown, path, f"unknown fields {unknown!r}")


def _validate_result(value: Any, op: str) -> None:
    required = {
        "width", "signed", "known", "unsigned", "signed_value",
        "hex", "bin", "sv",
    }
    if op in _BOOL_RESULT_OPS:
        required.add("bool")
    _exact(value, required, {"x_mask", "z_mask"}, "$.result")
    width = value["width"]
    _require(isinstance(width, int) and not isinstance(width, bool) and width > 0,
             "$.result.width", "expected positive integer")
    _require(isinstance(value["signed"], bool), "$.result.signed", "expected boolean")
    _require(isinstance(value["known"], bool), "$.result.known", "expected boolean")
    for field in ("hex", "bin", "sv"):
        _require(isinstance(value[field], str) and bool(value[field]),
                 f"$.result.{field}", "expected non-empty string")
    if value["known"]:
        _require("x_mask" not in value and "z_mask" not in value,
                 "$.result", "known values must not publish masks")
        unsigned = value["unsigned"]
        _require(isinstance(unsigned, int) and not isinstance(unsigned, bool),
                 "$.result.unsigned", "expected integer")
        canonical = BitVector(width, unsigned, signed=value["signed"]).to_result()
    else:
        _require(value["unsigned"] is None and value["signed_value"] is None,
                 "$.result", "unknown values must publish null integers")
        digits = value["bin"].replace("_", "")
        _require(len(digits) == width and all(char in "01xz" for char in digits),
                 "$.result.bin", "expected width-sized four-state bits")
        masks = {}
        for field in ("x_mask", "z_mask"):
            text = value.get(field)
            _require(isinstance(text, str) and re.fullmatch(r"0x[0-9a-f]+", text) is not None,
                     f"$.result.{field}", "expected canonical hexadecimal mask")
            masks[field] = int(text, 16)
        _require(not (masks["x_mask"] & masks["z_mask"]),
                 "$.result", "x/z masks must be disjoint")
        unsigned = x_mask = z_mask = 0
        for bit, char in enumerate(reversed(digits)):
            if char == "1": unsigned |= 1 << bit
            elif char == "x": x_mask |= 1 << bit
            elif char == "z": z_mask |= 1 << bit
        _require((x_mask, z_mask) == (masks["x_mask"], masks["z_mask"]),
                 "$.result", "masks contradict binary value")
        canonical = BitVector(width, unsigned, signed=value["signed"],
                              state="4state", x_mask=x_mask, z_mask=z_mask).to_result()
    for field, expected in canonical.items():
        _require(value[field] == expected, f"$.result.{field}", "contradicts canonical value")
    if op in _BOOL_RESULT_OPS:
        _require(value["known"] and isinstance(value["bool"], bool),
                 "$.result.bool", "expected known boolean")
        _require(value["bool"] is (value["unsigned"] != 0),
                 "$.result.bool", "contradicts unsigned value")


def validate_response(response: Any, *, expected_op: str | None = None) -> None:
    _require(isinstance(response, dict), "$", "expected object")
    _require(isinstance(response.get("ok"), bool), "$.ok", "expected boolean")
    if response["ok"]:
        op = response.get("op")
        required = {"ok", "schema", "op", "result", "warnings"}
        if op == "check":
            required |= {"matched", "evaluated"}
        _exact(response, required, set(), "$")
        _require(response["schema"] == SCHEMA_RESULT, "$.schema", "unexpected schema")
        _require(op in OPS, "$.op", "unsupported operation")
        if expected_op is not None:
            _require(op == expected_op, "$.op", "does not match requested operation")
        _validate_result(response["result"], op)
        _require(isinstance(response["warnings"], list)
                 and all(isinstance(item, str) for item in response["warnings"]),
                 "$.warnings", "expected string array")
        if op == "check":
            _require(isinstance(response["matched"], bool), "$.matched", "expected boolean")
            _require(isinstance(response["evaluated"], dict)
                     and all(isinstance(k, str) and k and isinstance(v, str)
                             for k, v in response["evaluated"].items()),
                     "$.evaluated", "expected string mapping")
        return
    _exact(response, {"ok", "schema", "error"}, {"op"}, "$")
    _require(response["schema"] == SCHEMA_ERROR, "$.schema", "unexpected schema")
    if "op" in response:
        _require(response["op"] in OPS, "$.op", "unsupported operation")
    error = response["error"]
    _exact(error, {"code", "message"}, {"details"}, "$.error")
    _require(all(isinstance(error[field], str) and error[field]
                 for field in ("code", "message")), "$.error", "invalid code/message")
    if "details" in error:
        details = error["details"]
        _require(isinstance(details, dict) and details, "$.error.details", "expected object")
        for field, value in details.items():
            _require(field in _ERROR_DETAIL_TYPES, f"$.error.details.{field}", "unknown field")
            expected = _ERROR_DETAIL_TYPES[field]
            _require(isinstance(value, expected) and not (expected is int and isinstance(value, bool)),
                     f"$.error.details.{field}", f"expected {expected.__name__}")


def success(op: str, *, result: Any, warnings: list[str] | None = None,
            matched: bool | None = None,
            evaluated: dict[str, str] | None = None) -> dict:
    result_payload = result.to_result() if isinstance(result, BitVector) else result
    if isinstance(result, BitVector) and op in _BOOL_RESULT_OPS:
        result_payload["bool"] = result.truthy()
    response = {"ok": True, "schema": SCHEMA_RESULT, "op": op,
                "result": result_payload, "warnings": list(warnings or [])}
    if op == "check":
        response["matched"] = matched
        response["evaluated"] = evaluated
    elif matched is not None or evaluated is not None:
        raise ResponseContractError("matched/evaluated are check-only")
    validate_response(response, expected_op=op)
    return response


def failure(error: Exception, *, op: str | None = None) -> dict:
    if isinstance(error, XbitError):
        err = error.to_error()
    else:
        err = {"code": "INTERNAL_ERROR", "message": str(error)}
    response = {"ok": False, "schema": SCHEMA_ERROR, "error": err}
    if op:
        response["op"] = op
    validate_response(response, expected_op=op)
    return response


def dumps(payload: dict, *, pretty: bool = False) -> str:
    validate_response(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)


def to_xout(payload: dict) -> str:
    validate_response(payload)
    op = str(payload.get("op") or "error")
    if not payload.get("ok"):
        error = payload["error"]
        return f"@xbit.error.v1\n\ncode: {error['code']}\nmessage: {error['message']}\n"
    result = payload["result"]
    lines = [f"@xbit.{op}.v1", "", "summary:",
             f"  result: {result['sv']}", f"  width: {result['width']}"]
    if result["known"]:
        lines.extend((f"  unsigned: {result['unsigned']}",
                      f"  signed: {result['signed_value']}"))
    if "bool" in result:
        lines.append(f"  bool: {str(result['bool']).lower()}")
    if "matched" in payload:
        lines.append(f"  matched: {str(payload['matched']).lower()}")
    return "\n".join(lines) + "\n"


def xout_result(payload: dict) -> str:
    return to_xout(payload)
