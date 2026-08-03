"""Strict action-specific response contracts for xentry.v1."""

from __future__ import annotations

import re
from typing import Any


ACTIONS = frozenset({"decode", "explain", "validate"})
_BITS = re.compile(r"^\[(\d+):(\d+)\]$")
_HEX = re.compile(r"^0x[0-9a-f]+$")
_BIN = re.compile(r"^[01]+$")


class ResponseContractError(ValueError):
    pass


def _require(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ResponseContractError(f"{path}: {message}")


def _exact(
    value: Any,
    required: set[str],
    optional: set[str] = frozenset(),
    path: str = "$",
) -> None:
    _require(isinstance(value, dict), path, "expected object")
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    _require(not missing, path, f"missing required fields {missing!r}")
    _require(not unknown, path, f"unknown fields {unknown!r}")


def _string(value: Any, path: str, *, nonempty: bool = False) -> None:
    _require(
        isinstance(value, str) and (not nonempty or bool(value)),
        path,
        "expected non-empty string" if nonempty else "expected string",
    )


def _integer(value: Any, path: str, *, minimum: int | None = None) -> None:
    _require(
        isinstance(value, int)
        and not isinstance(value, bool)
        and (minimum is None or value >= minimum),
        path,
        "expected integer" if minimum is None else f"expected integer >= {minimum}",
    )


def _schema(value: Any) -> None:
    _exact(value, {"name", "version"}, path="$.schema")
    _string(value["name"], "$.schema.name", nonempty=True)
    _integer(value["version"], "$.schema.version", minimum=1)


def _bit_range(value: Any, path: str) -> tuple[int, int]:
    match = _BITS.fullmatch(value) if isinstance(value, str) else None
    _require(match is not None, path, "expected canonical [msb:lsb]")
    assert match is not None
    msb, lsb = int(match.group(1)), int(match.group(2))
    _require(msb >= lsb, path, "msb must be >= lsb")
    _require(value == f"[{msb}:{lsb}]", path, "expected canonical [msb:lsb]")
    return msb, lsb


def _metadata(value: dict[str, Any], path: str) -> None:
    for field in ("entry_id", "time"):
        if field in value:
            item = value[field]
            _require(
                (isinstance(item, str) and bool(item))
                or (isinstance(item, int) and not isinstance(item, bool)),
                f"{path}.{field}",
                "expected non-empty string or integer",
            )
    for field in ("source", "tag"):
        if field in value:
            _string(value[field], f"{path}.{field}", nonempty=True)
    if "line" in value:
        _integer(value["line"], f"{path}.line", minimum=1)


def _source(value: Any, path: str) -> tuple[int, int]:
    _exact(
        value,
        {"seq", "entry_bits", "fragment_bits"},
        {"entry_id", "time", "source", "line", "tag"},
        path,
    )
    _integer(value["seq"], f"{path}.seq", minimum=0)
    entry_msb, entry_lsb = _bit_range(value["entry_bits"], f"{path}.entry_bits")
    fragment_msb, fragment_lsb = _bit_range(
        value["fragment_bits"], f"{path}.fragment_bits"
    )
    _require(
        entry_msb - entry_lsb == fragment_msb - fragment_lsb,
        path,
        "entry_bits and fragment_bits must have equal width",
    )
    _metadata(value, path)
    return entry_msb, entry_lsb


def _warning(value: Any, path: str) -> None:
    _exact(value, {"code", "message", "field", "overlaps"}, path=path)
    _require(value["code"] == "FIELD_OVERLAP", f"{path}.code", "unknown warning code")
    _string(value["message"], f"{path}.message", nonempty=True)
    _string(value["field"], f"{path}.field", nonempty=True)
    overlaps = value["overlaps"]
    _require(
        isinstance(overlaps, list)
        and bool(overlaps)
        and all(isinstance(item, str) and item for item in overlaps),
        f"{path}.overlaps",
        "expected non-empty string array",
    )


def _warnings(value: Any) -> None:
    _require(isinstance(value, list), "$.warnings", "expected array")
    for index, warning in enumerate(value):
        _warning(warning, f"$.warnings[{index}]")


def _layout(value: Any, path: str, *, named: bool) -> tuple[int, int, int]:
    required = {"bits", "msb", "lsb", "width"} | ({"name"} if named else set())
    _exact(value, required, {"description"}, path)
    if named:
        _string(value["name"], f"{path}.name", nonempty=True)
    bits_msb, bits_lsb = _bit_range(value["bits"], f"{path}.bits")
    _integer(value["msb"], f"{path}.msb", minimum=0)
    _integer(value["lsb"], f"{path}.lsb", minimum=0)
    _integer(value["width"], f"{path}.width", minimum=1)
    _require(value["msb"] >= value["lsb"], path, "msb must be >= lsb")
    _require(
        value["width"] == value["msb"] - value["lsb"] + 1,
        f"{path}.width",
        "does not match msb/lsb",
    )
    _require(
        (bits_msb, bits_lsb) == (value["msb"], value["lsb"]),
        f"{path}.bits",
        "does not match msb/lsb",
    )
    if "description" in value:
        _string(value["description"], f"{path}.description")
    return bits_msb, bits_lsb, value["width"]


def _decode_field(name: str, value: Any) -> None:
    path = f"$.fields.{name}"
    _exact(
        value,
        {"bits", "msb", "lsb", "width", "raw_hex", "raw_bin", "source"},
        {"description"},
        path,
    )
    layout = {key: value[key] for key in ("bits", "msb", "lsb", "width")}
    if "description" in value:
        layout["description"] = value["description"]
    _layout(layout, path, named=False)
    _require(
        isinstance(value["raw_hex"], str) and _HEX.fullmatch(value["raw_hex"]) is not None,
        f"{path}.raw_hex",
        "expected canonical hexadecimal string",
    )
    _require(
        isinstance(value["raw_bin"], str) and _BIN.fullmatch(value["raw_bin"]) is not None,
        f"{path}.raw_bin",
        "expected binary string",
    )
    _require(len(value["raw_bin"]) == value["width"], f"{path}.raw_bin", "width mismatch")
    _require(
        len(value["raw_hex"]) - 2 == (value["width"] + 3) // 4,
        f"{path}.raw_hex",
        "digit count does not match width",
    )
    _require(
        int(value["raw_hex"], 16) == int(value["raw_bin"], 2),
        path,
        "raw encodings conflict",
    )
    sources = value["source"]
    _require(isinstance(sources, list) and bool(sources), f"{path}.source", "expected non-empty array")
    next_lsb = value["lsb"]
    for index, source in enumerate(sources):
        source_path = f"{path}.source[{index}]"
        entry_msb, entry_lsb = _source(source, source_path)
        _require(
            entry_lsb == next_lsb,
            f"{source_path}.entry_bits",
            "source ranges must cover field in ascending order without gaps or overlaps",
        )
        _require(entry_msb <= value["msb"], f"{source_path}.entry_bits", "range exceeds field")
        next_lsb = entry_msb + 1
    _require(next_lsb == value["msb"] + 1, f"{path}.source", "does not cover all field bits")


def _error(value: Any) -> None:
    _exact(value, {"code", "message"}, {"details"}, "$.error")
    _string(value["code"], "$.error.code", nonempty=True)
    _string(value["message"], "$.error.message", nonempty=True)
    if "details" not in value:
        return
    details = value["details"]
    allowed = {
        "actual_type", "bits", "data", "field", "fragment_width", "key",
        "line", "message", "seq", "total_bits", "total_valid_bits",
        "valid_lsb", "valid_width", "value",
    }
    _exact(details, set(), allowed, "$.error.details")
    _require(bool(details), "$.error.details", "must not be empty")
    string_fields = {"actual_type", "bits", "data", "field", "key", "message"}
    integer_fields = {
        "fragment_width", "line", "seq", "total_bits", "total_valid_bits",
        "valid_lsb", "valid_width",
    }
    for field, item in details.items():
        if field in string_fields:
            _string(item, f"$.error.details.{field}", nonempty=True)
        elif field in integer_fields:
            _integer(item, f"$.error.details.{field}")
        else:
            _require(
                (isinstance(item, str) and bool(item))
                or (isinstance(item, int) and not isinstance(item, bool)),
                "$.error.details.value",
                "expected non-empty string or integer",
            )


def validate_response(payload: Any, *, expected_action: str | None = None) -> None:
    _require(isinstance(payload, dict), "$", "expected object")
    _require(isinstance(payload.get("ok"), bool), "$.ok", "expected boolean")
    _require(payload.get("api_version") == "xentry.v1", "$.api_version", "unexpected version")
    action = payload.get("action")
    _require(
        action in ACTIONS or (not payload["ok"] and action == "error"),
        "$.action",
        "unknown action",
    )
    if expected_action is not None:
        _require(expected_action in ACTIONS or expected_action == "error", "expected_action", "unknown action")
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
        _schema(payload["schema"])
        _integer(payload["total_bits"], "$.total_bits", minimum=1)
        _warnings(payload["warnings"])
        if action == "decode":
            entry_raw = payload["entry_raw"]
            _require(isinstance(entry_raw, str) and _HEX.fullmatch(entry_raw) is not None, "$.entry_raw", "expected canonical hex")
            _require(len(entry_raw) - 2 == (payload["total_bits"] + 3) // 4, "$.entry_raw", "digit count does not match total_bits")
            entry_value = int(entry_raw, 16)
            _require(entry_value < (1 << payload["total_bits"]), "$.entry_raw", "value exceeds total_bits")
            fields = payload["fields"]
            _require(isinstance(fields, dict) and bool(fields), "$.fields", "expected non-empty object")
            for name, field in fields.items():
                _string(name, "$.fields.<key>", nonempty=True)
                _decode_field(name, field)
                _require(field["msb"] < payload["total_bits"], f"$.fields.{name}.msb", "exceeds total_bits")
                field_value = (entry_value >> field["lsb"]) & ((1 << field["width"]) - 1)
                _require(field_value == int(field["raw_bin"], 2), f"$.fields.{name}", "does not match entry_raw")
        elif action == "explain":
            _require(payload["fragment_byte_order"] in {"msb_first", "lsb_first"}, "$.fragment_byte_order", "invalid order")
            _require(payload["bit_numbering"] in {"byte_lsb0", "byte_msb0"}, "$.bit_numbering", "invalid numbering")
            fields = payload["fields"]
            _require(isinstance(fields, list) and bool(fields), "$.fields", "expected non-empty array")
            for index, field in enumerate(fields):
                _layout(field, f"$.fields[{index}]", named=True)
                _require(field["msb"] < payload["total_bits"], f"$.fields[{index}].msb", "exceeds total_bits")
    else:
        _exact(payload, common | {"error"}, optional, "$")
        _require(payload["warnings"] == [], "$.warnings", "must be empty")
        _error(payload["error"])

    if "request_id" in payload:
        _string(payload["request_id"], "$.request_id", nonempty=True)
