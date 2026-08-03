"""Strict public response contracts for xloc."""

from __future__ import annotations

from typing import Any

from .errors import XlocError

API_VERSION = "xloc.v1"
SUPPORTED_ACTIONS = frozenset({"resolve", "context", "stats", "annotate"})
_COMMON_SUCCESS = {
    "api_version", "ok", "action", "status", "scan_complete",
    "analysis_complete", "response_truncated", "total_count",
    "returned_count", "truncation_scopes", "diagnostics",
}
_ACTION_SUCCESS = {
    "resolve": {"map", "loc_id", "file"},
    "context": {"map", "loc_id", "file", "line", "before", "after", "context"},
    "stats": {
        "log", "map", "unique_location_count", "resolved_location_count",
        "unresolved_location_count", "unique_file_count",
        "total_occurrence_count", "rows",
    },
    "annotate": {
        "log", "map", "source_line_count", "unique_location_count",
        "annotation_count", "unresolved_location_count", "lines",
    },
}
_ERROR_KEYS = {"api_version", "ok", "action", "status", "error", "diagnostics"}
_DIAGNOSTIC_KEYS = {"code", "message", "severity", "path", "line", "loc_id", "count"}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    parts = []
    if unknown:
        parts.append(f"unknown fields: {', '.join(unknown)}")
    if missing:
        parts.append(f"missing fields: {', '.join(missing)}")
    raise ValueError(f"{where} contract violation ({'; '.join(parts)})")


def _require_non_negative(value: Any, where: str) -> None:
    if not _is_int(value) or value < 0:
        raise ValueError(f"{where} must be a non-negative integer")


def _validate_diagnostics(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("diagnostics must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"diagnostics[{index}] must be an object")
        unknown = set(item) - _DIAGNOSTIC_KEYS
        missing = {"code", "message", "severity"} - set(item)
        if unknown or missing:
            raise ValueError(
                f"diagnostics[{index}] contract violation "
                f"(unknown={sorted(unknown)}, missing={sorted(missing)})"
            )
        if (
            not isinstance(item["code"], str) or not item["code"]
            or not isinstance(item["message"], str) or not item["message"]
            or item["severity"] not in {"warning", "error"}
        ):
            raise ValueError(f"diagnostics[{index}] has invalid required fields")
        for key in ("path", "loc_id"):
            if key in item and (not isinstance(item[key], str) or not item[key]):
                raise ValueError(f"diagnostics[{index}].{key} must be non-empty")
        for key in ("line", "count"):
            if key in item:
                _require_non_negative(item[key], f"diagnostics[{index}].{key}")


def _validate_common_success(payload: dict[str, Any]) -> None:
    if payload["status"] not in {"complete", "partial"}:
        raise ValueError("success status must be complete or partial")
    for field in ("scan_complete", "analysis_complete", "response_truncated"):
        if not isinstance(payload[field], bool):
            raise ValueError(f"{field} must be boolean")
    if not payload["scan_complete"]:
        raise ValueError("a successful response cannot publish an incomplete scan")
    _require_non_negative(payload["total_count"], "total_count")
    _require_non_negative(payload["returned_count"], "returned_count")
    if payload["returned_count"] > payload["total_count"]:
        raise ValueError("returned_count cannot exceed total_count")
    scopes = payload["truncation_scopes"]
    if (
        not isinstance(scopes, list)
        or any(not isinstance(scope, str) or not scope for scope in scopes)
        or len(scopes) != len(set(scopes))
    ):
        raise ValueError("truncation_scopes must contain unique non-empty strings")
    if payload["response_truncated"] != bool(scopes):
        raise ValueError("response_truncated must equal whether truncation_scopes is non-empty")
    complete = payload["analysis_complete"] and not payload["response_truncated"]
    if (payload["status"] == "complete") != complete:
        raise ValueError("status disagrees with completeness fields")
    _validate_diagnostics(payload["diagnostics"])


def _validate_context_rows(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("context must be an array")
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"context[{index}] must be an object")
        _require_exact_keys(row, {"line", "hit", "text"}, f"context[{index}]")
        if not _is_int(row["line"]) or row["line"] <= 0:
            raise ValueError(f"context[{index}].line must be positive")
        if not isinstance(row["hit"], bool) or not isinstance(row["text"], str):
            raise ValueError(f"context[{index}] has invalid field types")


def _validate_stats_rows(value: Any) -> None:
    if not isinstance(value, list):
        raise ValueError("rows must be an array")
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise ValueError(f"rows[{index}] must be an object")
        resolved = row.get("resolution_status") == "resolved"
        expected = {"loc_id", "count", "resolution_status"} | ({"file"} if resolved else set())
        _require_exact_keys(row, expected, f"rows[{index}]")
        if row["resolution_status"] not in {"resolved", "unresolved"}:
            raise ValueError(f"rows[{index}].resolution_status is invalid")
        if not isinstance(row["loc_id"], str) or not row["loc_id"]:
            raise ValueError(f"rows[{index}].loc_id must be non-empty")
        if not _is_int(row["count"]) or row["count"] <= 0:
            raise ValueError(f"rows[{index}].count must be positive")
        if resolved and (not isinstance(row["file"], str) or not row["file"]):
            raise ValueError(f"rows[{index}].file must be non-empty")


def validate_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and return one strict action-specific response."""
    if not isinstance(payload, dict):
        raise TypeError("xloc response root must be an object")
    if payload.get("api_version") != API_VERSION:
        raise ValueError(f"api_version must be {API_VERSION}")
    action = payload.get("action")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported xloc response action: {action!r}")
    if not isinstance(payload.get("ok"), bool):
        raise ValueError("ok must be boolean")

    if not payload["ok"]:
        _require_exact_keys(payload, _ERROR_KEYS, f"{action} error response")
        if payload["status"] != "error":
            raise ValueError("failed response status must be error")
        error = payload["error"]
        if not isinstance(error, dict):
            raise ValueError("error must be an object")
        _require_exact_keys(error, {"code", "message"}, "error")
        if not all(isinstance(error[key], str) and error[key] for key in ("code", "message")):
            raise ValueError("error code and message must be non-empty strings")
        _validate_diagnostics(payload["diagnostics"])
        if not payload["diagnostics"]:
            raise ValueError("failed response must contain an error diagnostic")
        return payload

    _require_exact_keys(payload, _COMMON_SUCCESS | _ACTION_SUCCESS[action], f"{action} success response")
    _validate_common_success(payload)
    if action in {"resolve", "context"}:
        for field in ("map", "loc_id", "file"):
            if not isinstance(payload[field], str) or not payload[field]:
                raise ValueError(f"{field} must be a non-empty string")
    if action == "resolve":
        if payload["total_count"] != 1 or payload["returned_count"] != 1:
            raise ValueError("resolve count fields must both equal one")
    elif action == "context":
        if not _is_int(payload["line"]) or payload["line"] <= 0:
            raise ValueError("line must be a positive integer")
        for field in ("before", "after"):
            _require_non_negative(payload[field], field)
        _validate_context_rows(payload["context"])
        hits = [row for row in payload["context"] if row["hit"]]
        if len(hits) != 1:
            raise ValueError("context must contain exactly one hit row")
        if hits[0]["line"] != payload["line"]:
            raise ValueError("context hit row must match the requested line")
        if payload["total_count"] != len(payload["context"]):
            raise ValueError("context total_count must equal context length")
        if payload["returned_count"] != len(payload["context"]):
            raise ValueError("context returned_count must equal context length")
    elif action == "stats":
        if not isinstance(payload["log"], str) or not payload["log"]:
            raise ValueError("log must be a non-empty string")
        if payload["map"] is not None and (not isinstance(payload["map"], str) or not payload["map"]):
            raise ValueError("map must be null or a non-empty string")
        for field in ("unique_location_count", "resolved_location_count", "unresolved_location_count", "unique_file_count", "total_occurrence_count"):
            _require_non_negative(payload[field], field)
        _validate_stats_rows(payload["rows"])
        if payload["total_count"] != payload["unique_location_count"]:
            raise ValueError("stats total_count must equal unique_location_count")
        if payload["returned_count"] != len(payload["rows"]):
            raise ValueError("stats returned_count must equal rows length")
        if payload["resolved_location_count"] + payload["unresolved_location_count"] != payload["unique_location_count"]:
            raise ValueError("stats resolution counts do not sum to total")
    else:
        if not isinstance(payload["log"], str) or not payload["log"]:
            raise ValueError("log must be a non-empty string")
        if payload["map"] is not None and (not isinstance(payload["map"], str) or not payload["map"]):
            raise ValueError("map must be null or a non-empty string")
        for field in ("source_line_count", "unique_location_count", "annotation_count", "unresolved_location_count"):
            _require_non_negative(payload[field], field)
        if not isinstance(payload["lines"], list) or any(not isinstance(line, str) for line in payload["lines"]):
            raise ValueError("lines must be an array of strings")
        if payload["annotation_count"] + payload["unresolved_location_count"] != payload["unique_location_count"]:
            raise ValueError("annotate resolution counts do not sum to total")
        if payload["total_count"] != payload["unique_location_count"]:
            raise ValueError("annotate total_count must equal unique_location_count")
        if payload["returned_count"] != payload["annotation_count"]:
            raise ValueError("annotate returned_count must equal annotation_count")
    return payload


def error_response(action: str, error: XlocError) -> dict[str, Any]:
    return validate_response({
        "api_version": API_VERSION,
        "ok": False,
        "action": action,
        "status": "error",
        "error": {"code": error.code, "message": error.message},
        "diagnostics": [error.diagnostic()],
    })


def success_base(
    action: str,
    *,
    analysis_complete: bool,
    response_truncated: bool,
    total_count: int,
    returned_count: int,
    truncation_scopes: list[str],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "ok": True,
        "action": action,
        "status": "complete" if analysis_complete and not response_truncated else "partial",
        "scan_complete": True,
        "analysis_complete": analysis_complete,
        "response_truncated": response_truncated,
        "total_count": total_count,
        "returned_count": returned_count,
        "truncation_scopes": truncation_scopes,
        "diagnostics": diagnostics,
    }
