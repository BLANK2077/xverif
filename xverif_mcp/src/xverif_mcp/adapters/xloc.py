"""Stateless xloc adapter using the strict in-process xloc contract."""

from __future__ import annotations

from typing import Any, Literal, Optional

from xverif_mcp.import_paths import ensure_tool_import_paths

ensure_tool_import_paths()

from xloc.annotate import annotate_payload
from xloc.contracts import error_response
from xloc.errors import XlocError
from xloc.resolver import context_payload, render_payload, resolve_payload
from xloc.stats import render_stats, stats_payload
from xloc.xout import to_xout

OutputFormat = Literal["xout", "json"]


def _emit(action: str, payload: dict[str, Any], output_format: str) -> Any:
    if output_format == "json":
        return payload
    if output_format == "xout":
        if action == "stats":
            return render_stats(payload)
        if action in {"resolve", "context"}:
            return render_payload(payload)
        return to_xout(payload)
    return error_response(
        action,
        XlocError(
            "INVALID_OUTPUT_FORMAT",
            "output_format must be one of: json, xout",
        ),
    )


def loc_resolve(
    loc_id: str, map_path: str, output_format: OutputFormat = "xout",
) -> Any:
    """Resolve a strict loc_id (L_XXXXXXXX) to a source file."""
    return _emit("resolve", resolve_payload(loc_id, map_path), output_format)


def loc_context(
    loc_id: str,
    map_path: str,
    line: int,
    before: int = 20,
    after: int = 20,
    output_format: OutputFormat = "xout",
) -> Any:
    """Resolve a loc_id and show source context at an explicit line."""
    return _emit(
        "context",
        context_payload(loc_id, map_path, line, before, after),
        output_format,
    )


def loc_stats(
    log_path: str,
    map_path: Optional[str] = None,
    top: int = 20,
    output_format: OutputFormat = "xout",
) -> Any:
    """Count loc_id frequency in a simulation log."""
    return _emit("stats", stats_payload(log_path, map_path, top), output_format)


def loc_annotate(
    log_path: str,
    map_path: Optional[str] = None,
    output_format: OutputFormat = "xout",
) -> Any:
    """Return a strict annotated-log response without a raw-text fallback."""
    return _emit("annotate", annotate_payload(log_path, map_path), output_format)
