"""Closed public response contract for xsva CLI and MCP boundaries."""

from __future__ import annotations

from typing import Any


class ResponseContractError(ValueError):
    """Raised when an xsva response violates its public contract."""


_ACTIONS = {"list", "scan", "lint", "parse", "explain", "error"}
_COMMON = {
    "ok", "tool", "action", "lowering_status", "precision",
    "diagnostics", "completeness",
}
_SUCCESS_FIELDS = {
    "list": {"file", "result"},
    "scan": {"file", "result"},
    "lint": {"file", "property", "result"},
    "parse": {"file", "property", "emit", "result"},
    "explain": {"file", "property", "result"},
}


def _fail(message: str) -> None:
    raise ResponseContractError(message)


def _exact(value: dict[str, Any], keys: set[str], where: str) -> None:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    actual = set(value)
    if actual != keys:
        _fail(
            f"{where} fields mismatch: unknown={sorted(actual - keys)}, "
            f"missing={sorted(keys - actual)}"
        )


def _string(value: Any, where: str, *, empty: bool = False) -> None:
    if not isinstance(value, str) or (not empty and not value):
        _fail(f"{where} must be {'a string' if empty else 'a non-empty string'}")


def _integer(value: Any, where: str, *, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        _fail(f"{where} must be an integer >= {minimum}")


def _diagnostics(value: Any) -> None:
    if not isinstance(value, list):
        _fail("diagnostics must be an array")
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            _fail(f"diagnostics[{index}] must be an object")
        allowed = {"code", "severity", "message", "span"}
        if set(item) - allowed or not {"code", "severity", "message"} <= set(item):
            _fail(f"diagnostics[{index}] has invalid fields")
        _string(item["code"], f"diagnostics[{index}].code")
        _string(item["message"], f"diagnostics[{index}].message")
        if item["severity"] not in {"info", "warning", "error"}:
            _fail(f"diagnostics[{index}].severity is invalid")
        if "span" in item:
            span = item["span"]
            _exact(span, {"file", "begin_line", "begin_col", "end_line", "end_col"}, f"diagnostics[{index}].span")
            _string(span["file"], f"diagnostics[{index}].span.file", empty=True)
            for key in ("begin_line", "begin_col", "end_line", "end_col"):
                _integer(span[key], f"diagnostics[{index}].span.{key}")


def _analysis(payload: dict[str, Any]) -> None:
    if payload["lowering_status"] not in {"exact", "partial", "opaque", "unsupported", "unsafe_to_explain"}:
        _fail("lowering_status is invalid")
    precision = payload["precision"]
    _exact(precision, {"semantic_model", "path_enumeration", "reason_codes"}, "precision")
    if precision["semantic_model"] not in {"complete", "partial", "opaque", "unavailable", "unsafe"}:
        _fail("precision.semantic_model is invalid")
    if precision["path_enumeration"] not in {"not_applicable", "complete", "partial"}:
        _fail("precision.path_enumeration is invalid")
    if not isinstance(precision["reason_codes"], list) or any(not isinstance(item, str) or not item for item in precision["reason_codes"]):
        _fail("precision.reason_codes must be strings")
    if len(precision["reason_codes"]) != len(set(precision["reason_codes"])):
        _fail("precision.reason_codes must be unique")
    _diagnostics(payload["diagnostics"])

    complete = payload["completeness"]
    keys = {
        "scan_complete", "analysis_complete", "response_truncated",
        "path_enumeration_complete", "total_path_count",
        "returned_path_count", "truncation_scopes",
    }
    _exact(complete, keys, "completeness")
    for key in ("scan_complete", "analysis_complete", "response_truncated"):
        if not isinstance(complete[key], bool):
            _fail(f"completeness.{key} must be boolean")
    total = complete["total_path_count"]
    returned = complete["returned_path_count"]
    path_complete = complete["path_enumeration_complete"]
    if total is None:
        if returned is not None or path_complete is not None:
            _fail("path counts and path_enumeration_complete must all be null together")
        truncated = False
        path_state = "not_applicable"
    else:
        _integer(total, "completeness.total_path_count")
        _integer(returned, "completeness.returned_path_count")
        if returned > total:
            _fail("returned_path_count cannot exceed total_path_count")
        if not isinstance(path_complete, bool) or path_complete != (returned == total):
            _fail("path_enumeration_complete disagrees with path counts")
        truncated = not path_complete or returned < total
        path_state = "partial" if truncated else "complete"
    if complete["response_truncated"] != truncated:
        _fail("response_truncated disagrees with path counts")
    expected_scopes = ["analysis.match_paths"] if truncated else []
    if complete["truncation_scopes"] != expected_scopes:
        _fail("truncation_scopes disagrees with response_truncated")
    if precision["path_enumeration"] != path_state:
        _fail("precision.path_enumeration disagrees with completeness")
    expected_analysis_complete = (
        complete["scan_complete"]
        and payload["lowering_status"] == "exact"
        and not truncated
    )
    if complete["analysis_complete"] != expected_analysis_complete:
        _fail("analysis_complete disagrees with analysis state")


def _named_items(value: Any, where: str, *, assertion: bool) -> None:
    if not isinstance(value, list):
        _fail(f"{where} must be an array")
    expected = {"type", "name", "label"} if assertion else {"type", "name"}
    for index, item in enumerate(value):
        _exact(item, expected, f"{where}[{index}]")
        for key in expected:
            _string(item[key], f"{where}[{index}].{key}", empty=key == "label")
        if assertion and item["type"] not in {"assert", "assume", "cover"}:
            _fail(f"{where}[{index}].type is invalid")
        if not assertion and item["type"] != "property":
            _fail(f"{where}[{index}].type is invalid")


def _timeline(value: Any, completeness: dict[str, Any]) -> None:
    keys = {
        "schema_version", "property", "kind", "clock", "disable_expr",
        "trigger", "obligations", "match_paths", "failure_conditions",
        "semantic_notes",
    }
    _exact(value, keys, "timeline result")
    if value["schema_version"] != "xsva.timeline_ir.v1":
        _fail("timeline schema_version is invalid")
    for field in ("property", "kind"):
        _string(value[field], f"timeline.{field}")
    _string(value["disable_expr"], "timeline.disable_expr", empty=True)
    _exact(value["clock"], {"edge", "signal"}, "timeline.clock")
    _string(value["clock"]["edge"], "timeline.clock.edge")
    _string(value["clock"]["signal"], "timeline.clock.signal", empty=True)
    trigger = value["trigger"]
    _exact(trigger, {"cycle", "expr", "captures"}, "timeline.trigger")
    _integer(trigger["cycle"], "timeline.trigger.cycle")
    _string(trigger["expr"], "timeline.trigger.expr", empty=True)
    if not isinstance(trigger["captures"], list):
        _fail("timeline.trigger.captures must be an array")
    for index, capture in enumerate(trigger["captures"]):
        _exact(capture, {"var", "value_expr", "relative_cycle"}, f"timeline.trigger.captures[{index}]")
        _string(capture["var"], "capture.var")
        _string(capture["value_expr"], "capture.value_expr")
        if not isinstance(capture["relative_cycle"], int) or isinstance(capture["relative_cycle"], bool):
            _fail("capture.relative_cycle must be an integer")
    if not isinstance(value["obligations"], list):
        _fail("timeline.obligations must be an array")
    ids: set[str] = set()
    for index, item in enumerate(value["obligations"]):
        expected = {"id", "kind", "expr", "has_window", "window", "depends_on_captures", "requirement", "failure_condition"}
        _exact(item, expected, f"timeline.obligations[{index}]")
        _string(item["id"], "obligation.id")
        if item["id"] in ids:
            _fail("obligation ids must be unique")
        ids.add(item["id"])
        if not isinstance(item["has_window"], bool):
            _fail("obligation.has_window must be boolean")
        if item["has_window"] != (item["window"] is not None):
            _fail("obligation has_window disagrees with window")
        if item["window"] is not None:
            _exact(item["window"], {"start", "end", "unbounded"}, "obligation.window")
    if not isinstance(value["match_paths"], list):
        _fail("timeline.match_paths must be an array")
    for index, path in enumerate(value["match_paths"]):
        _exact(path, {"id", "description", "obligations"}, f"timeline.match_paths[{index}]")
        if not isinstance(path["obligations"], list) or any(item not in ids for item in path["obligations"]):
            _fail("match path obligations must reference canonical obligation ids")
    returned = completeness["returned_path_count"]
    if returned is not None and returned != len(value["match_paths"]):
        _fail("returned_path_count must equal returned match_paths length")


def _validate_success(payload: dict[str, Any], action: str) -> None:
    _exact(payload, _COMMON | _SUCCESS_FIELDS[action], f"{action} response")
    _string(payload["file"], "file")
    if action in {"lint", "parse", "explain"}:
        if payload["property"] is not None:
            _string(payload["property"], "property")
    if action == "parse" and payload["emit"] not in {"surface-ir", "sequence-ir", "timeline-ir"}:
        _fail("emit is invalid")
    result = payload["result"]
    if action == "list":
        _exact(result, {"properties", "assertions"}, "list result")
        _named_items(result["properties"], "result.properties", assertion=False)
        _named_items(result["assertions"], "result.assertions", assertion=True)
    elif action == "scan":
        _exact(result, {"property_blocks", "inline_assertions", "operators"}, "scan result")
    elif action == "lint":
        _exact(result, {"issue_count"}, "lint result")
        _integer(result["issue_count"], "result.issue_count")
        if result["issue_count"] != len(payload["diagnostics"]):
            _fail("lint issue_count must equal diagnostics length")
    elif action in {"parse", "explain"} and (
        action == "explain" or payload["emit"] == "timeline-ir"
    ):
        _timeline(result, payload["completeness"])


def validate_response(payload: dict[str, Any], *, expected_action: str | None = None) -> dict[str, Any]:
    """Validate and return one closed action-specific xsva response."""
    if not isinstance(payload, dict):
        _fail("response root must be an object")
    if payload.get("tool") != "xsva" or not isinstance(payload.get("ok"), bool):
        _fail("response must declare tool=xsva and boolean ok")
    action = payload.get("action")
    if action not in _ACTIONS:
        _fail(f"unsupported response action: {action!r}")
    if expected_action is not None and action != expected_action:
        _fail(f"expected action {expected_action!r}, got {action!r}")
    _analysis(payload)
    if payload["ok"]:
        if action not in _SUCCESS_FIELDS:
            _fail("successful response action is invalid")
        _validate_success(payload, action)
    else:
        _exact(payload, _COMMON | {"error"}, f"{action} error response")
        error = payload["error"]
        if not isinstance(error, dict) or set(error) not in ({"code", "message"}, {"code", "message", "details"}):
            _fail("error must be a closed code/message/details object")
        _string(error.get("code"), "error.code")
        _string(error.get("message"), "error.message")
        if "details" in error and not isinstance(error["details"], dict):
            _fail("error.details must be an object")
    return payload
