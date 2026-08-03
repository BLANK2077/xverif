from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Dict, List, Optional

from .errors import XcovError

Json = Dict[str, Any]

API_VERSION = "xcov.v1"
_ACTION_TOKEN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._-"
)


def _reject_nonfinite_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON number {token!r} is not allowed")


def _closed_json_object(pairs: List[tuple[str, Any]]) -> Json:
    out: Json = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON object key {key!r}")
        out[key] = value
    return out


def strict_json_loads(text: str) -> Any:
    """Parse RFC JSON without duplicate keys or non-finite number extensions."""
    return json.loads(
        text,
        parse_constant=_reject_nonfinite_constant,
        object_pairs_hook=_closed_json_object,
    )


def validate_action_token(action: Any) -> str:
    """Return one XOUT-header-safe action token or raise a public schema error."""
    if (
        not isinstance(action, str)
        or not action
        or any(char not in _ACTION_TOKEN_CHARS for char in action)
    ):
        raise XcovError(
            "SCHEMA_INVALID",
            "action must be a non-empty header-safe token using [A-Za-z0-9_.-]",
            path="$.action",
        )
    return action


def parse_request(text: str) -> Json:
    """Parse only the transport JSON envelope without adding defaults.

    Action-specific validation intentionally runs on the caller's original
    object in :class:`xcov.actions.Dispatcher`.  This keeps missing/unknown
    fields visible to the public contract instead of normalizing them away.
    """
    try:
        req = strict_json_loads(text)
    except Exception as exc:
        raise XcovError("INVALID_JSON", str(exc)) from exc
    if not isinstance(req, dict):
        raise XcovError("SCHEMA_INVALID", "request must be a JSON object", path="$")
    if req.get("api_version") != API_VERSION:
        raise XcovError(
            "API_VERSION_UNSUPPORTED",
            "api_version must be xcov.v1",
            path="$.api_version",
        )
    validate_action_token(req.get("action"))
    return req


def normalize_request(req: Json) -> Json:
    """Return an isolated, defaulted request after strict validation."""
    normalized = deepcopy(req)
    normalized.setdefault("request_id", "req-unknown")
    normalized.setdefault("target", {})
    normalized.setdefault("args", {})
    return normalized


def ok_response(
    req: Json,
    summary: Optional[Json] = None,
    data: Optional[Json] = None,
    warnings: Optional[List[str]] = None,
) -> Json:
    return {
        "ok": True,
        "api_version": API_VERSION,
        "request_id": req.get("request_id", "req-unknown"),
        "action": req.get("action", ""),
        "summary": dict(summary or {}),
        "data": dict(data or {}),
        "warnings": list(warnings or []),
    }


def completeness_summary(
    total_count: int,
    returned_count: int,
    *,
    response_truncated: bool = False,
    scan_complete: bool = True,
    analysis_complete: bool = True,
    truncation_scopes: Optional[List[str]] = None,
) -> Json:
    return {
        "total_count": total_count,
        "returned_count": returned_count,
        "response_truncated": response_truncated,
        "scan_complete": scan_complete,
        "analysis_complete": analysis_complete,
        "truncation_scopes": list(truncation_scopes or []),
    }


def render_xout(rsp: Json) -> str:
    """Render the original human-oriented xcov summary and tables."""
    action = _validated_response_action(rsp)
    return _render_human_xout(rsp, action=action, include_envelope=True)


def render_transport_xout(rsp: Json) -> str:
    """Render only the semantic body; stdio envelope owns response framing."""
    action = _validated_response_action(rsp)
    return _render_human_xout(rsp, action=action, include_envelope=False)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_scalar(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _flatten_item(item: Json) -> Json:
    flat: Json = {}
    for key, value in item.items():
        if key == "evidence" and isinstance(value, dict):
            for field in ("file", "line"):
                if value.get(field) is not None:
                    flat[field] = value[field]
        elif key in {"evidence_source", "branch_mask", "toggle_0_to_1", "toggle_1_to_0"} and isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flat[f"{key}.{nested_key}"] = nested_value
        elif key in {"annotations", "bits"} and isinstance(value, list):
            flat[f"{key}_count"] = len(value)
        else:
            flat[key] = value
    return flat


def _render_table(items: List[Json], indent: str = "  ") -> List[str]:
    rows = [_flatten_item(item) for item in items]
    if not rows:
        return []
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    values = [{key: _scalar(row.get(key)) for key in columns} for row in rows]
    widths = {key: max(len(key), *(len(row[key]) for row in values)) for key in columns}
    def line(row: Dict[str, str] | None = None) -> str:
        return indent + "  ".join((key if row is None else row[key]).ljust(widths[key]) for key in columns).rstrip()
    return [line(), *(line(row) for row in values)]


_SCOPE_COLUMNS = ["name", "full_name", "covered", "coverable", "missing", "coverage_pct"]
_SCOPE_METRICS = [("line", "line_pct"), ("toggle", "toggle_pct"), ("branch", "branch_pct"), ("condition", "condition_pct"), ("fsm", "fsm_pct"), ("assert", "assert_pct"), ("functional", "functional_pct")]


def _render_human_xout(rsp: Json, *, action: str, include_envelope: bool) -> str:
    status = "ok" if rsp["ok"] else "error"
    rid = rsp.get("request_id", "req-unknown")
    header = f"@xcov.v1 {status} action={action} request_id={rid}" if include_envelope else f"@xcov.{action}.v1"
    lines = [header, ""]
    if not rsp["ok"]:
        lines.append("error:")
        lines.extend(f"  {key}: {_scalar(value)}" for key, value in rsp.get("error", {}).items())
    else:
        lines.append("summary:")
        lines.extend(f"  {key}: {_scalar(value)}" for key, value in rsp.get("summary", {}).items())
        data = rsp.get("data", {})
        filters = data.get("filters") if isinstance(data, dict) else None
        if isinstance(filters, dict):
            lines.extend(["", "filters:"])
            lines.extend(f"  {key}: {_scalar(value)}" for key, value in filters.items())
        sections = data.get("sections") if isinstance(data, dict) else None
        if isinstance(sections, dict):
            lines.extend(["", "sections:"])
            for key, value in sections.items():
                lines.append(f"  {key}:")
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    lines.extend(_render_table(value, "    "))
                elif isinstance(value, list):
                    lines.extend(f"    - {_scalar(item)}" for item in value)
                else:
                    lines.append(f"    {_scalar(value)}")
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            rows = [item for item in items if isinstance(item, dict)]
            lines.extend(["", "items:"])
            if action == "scope.summary" and len(rows) == len(items):
                projected = [{key: row.get(key) for key in _SCOPE_COLUMNS} for row in rows]
                lines.extend(_render_table(projected))
                coverage = []
                for row in rows:
                    for metric, field in _SCOPE_METRICS:
                        if row.get(field) is not None:
                            coverage_row: Json = {
                                "metric": metric,
                                "coverage_pct": row[field],
                            }
                            if len(rows) > 1:
                                coverage_row = {
                                    "full_name": row.get("full_name"),
                                    **coverage_row,
                                }
                            coverage.append(coverage_row)
                if coverage:
                    lines.extend(["", "coverage:", *_render_table(coverage)])
            elif len(rows) == len(items):
                lines.extend(_render_table(rows))
            else:
                lines.extend(f"  - {_scalar(item)}" for item in items)
    warnings = rsp.get("warnings") or []
    if warnings:
        lines.extend(["", "warnings:", *(f"  - {_scalar(item)}" for item in warnings)])
    return "\n".join(lines).rstrip() + "\n"


def _validated_response_action(rsp: Json) -> str:
    if not isinstance(rsp, dict):
        raise XcovError("RESPONSE_SCHEMA_INVALID", "response must be an object", path="$")
    action = rsp.get("action")
    if not isinstance(action, str) or not action:
        raise XcovError(
            "RESPONSE_SCHEMA_INVALID",
            "response action must be a non-empty string",
            path="$.action",
        )
    from .schemas import validate_response

    validate_response(action, rsp)
    return action


def json_dumps(obj: Json) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False)
