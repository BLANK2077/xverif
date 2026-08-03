"""Strict action-specific response contracts for xentry.v1."""

from __future__ import annotations

import re
from typing import Any


ACTIONS = frozenset({"decode", "explain", "validate"})
_BITS = re.compile(r"^\[(\d+):(\d+)\]$")


class ResponseContractError(ValueError):
    pass


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ResponseContractError(f"{path}: {message}")


def _exact(value: Any, required: set[str], optional: set[str], path: str) -> None:
    _require(isinstance(value, dict), path, "expected object")
    _require(not (required - set(value)), path, "missing required fields")
    unknown = sorted(set(value) - required - optional)
    _require(not unknown, path, f"unknown fields {unknown!r}")


def _layout(value: Any, path: str, *, named: bool) -> tuple[int, int, int]:
    required = {"bits", "msb", "lsb", "width"} | ({"name"} if named else set())
    _exact(value, required, {"description"}, path)
    match = _BITS.fullmatch(value["bits"]) if isinstance(value["bits"], str) else None
    _require(match is not None, f"{path}.bits", "expected [msb:lsb]")
    msb, lsb = (int(match.group(1)), int(match.group(2)))
    _require(all(isinstance(value[field], int) and not isinstance(value[field], bool)
                 for field in ("msb", "lsb", "width")), path, "integer layout required")
    _require((value["msb"], value["lsb"], value["width"])
             == (msb, lsb, msb - lsb + 1), path, "contradictory layout")
    return msb, lsb, value["width"]


def validate_response(payload: Any, *, expected_action: str | None = None) -> None:
    _require(isinstance(payload, dict), "$", "expected object")
    _require(isinstance(payload.get("ok"), bool), "$.ok", "expected boolean")
    _require(payload.get("api_version") == "xentry.v1", "$.api_version", "unexpected version")
    action = payload.get("action")
    _require(action in ACTIONS or (not payload["ok"] and action == "error"),
             "$.action", "unknown action")
    if expected_action is not None:
        _require(action == expected_action, "$.action", "does not match request")
    common = {"ok", "api_version", "action", "warnings"}
    optional = {"request_id"}
    if payload["ok"]:
        action_fields = {
            "decode": {"schema", "total_bits", "entry_raw", "fields"},
            "explain": {"schema", "total_bits", "fragment_byte_order", "bit_numbering", "fields"},
            "validate": {"schema", "total_bits"},
        }[action]
        _exact(payload, common | action_fields, optional, "$")
        _exact(payload["schema"], {"name", "version"}, set(), "$.schema")
        _require(isinstance(payload["total_bits"], int) and not isinstance(payload["total_bits"], bool)
                 and payload["total_bits"] > 0, "$.total_bits", "expected positive integer")
        _require(isinstance(payload["warnings"], list), "$.warnings", "expected array")
        if action == "decode":
            _require(isinstance(payload["entry_raw"], str)
                     and re.fullmatch(r"0x[0-9a-f]+", payload["entry_raw"]) is not None,
                     "$.entry_raw", "expected canonical hex")
            fields = payload["fields"]
            _require(isinstance(fields, dict) and fields, "$.fields", "expected object")
            entry_value = int(payload["entry_raw"], 16)
            for name, field in fields.items():
                path = f"$.fields.{name}"
                _exact(field, {"bits", "msb", "lsb", "width", "raw_hex", "raw_bin", "source"},
                       {"description"}, path)
                msb, lsb, width = _layout({k: field[k] for k in ("bits", "msb", "lsb", "width")}, path, named=False)
                _require(len(field["raw_bin"]) == width
                         and int(field["raw_bin"], 2) == int(field["raw_hex"], 16),
                         path, "raw encodings conflict")
                _require(((entry_value >> lsb) & ((1 << width) - 1)) == int(field["raw_bin"], 2),
                         path, "field conflicts with entry_raw")
                _require(isinstance(field["source"], list) and field["source"],
                         f"{path}.source", "expected provenance")
        elif action == "explain":
            _require(payload["fragment_byte_order"] in {"msb_first", "lsb_first"},
                     "$.fragment_byte_order", "invalid order")
            _require(payload["bit_numbering"] in {"byte_lsb0", "byte_msb0"},
                     "$.bit_numbering", "invalid numbering")
            _require(isinstance(payload["fields"], list) and payload["fields"],
                     "$.fields", "expected array")
            for index, field in enumerate(payload["fields"]):
                _layout(field, f"$.fields[{index}]", named=True)
    else:
        _exact(payload, common | {"error"}, optional, "$")
        _require(payload["warnings"] == [], "$.warnings", "must be empty")
        _exact(payload["error"], {"code", "message"}, {"details"}, "$.error")
        if "details" in payload["error"]:
            allowed = {"actual_type", "bits", "data", "field", "fragment_width", "key",
                       "line", "message", "seq", "total_bits", "total_valid_bits",
                       "valid_lsb", "valid_width", "value"}
            _require(isinstance(payload["error"]["details"], dict)
                     and payload["error"]["details"]
                     and not (set(payload["error"]["details"]) - allowed),
                     "$.error.details", "unknown or empty details")
    if "request_id" in payload:
        _require(isinstance(payload["request_id"], str) and payload["request_id"],
                 "$.request_id", "expected non-empty string")
