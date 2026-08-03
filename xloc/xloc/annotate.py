"""Strict log annotation built on the canonical xloc scanner."""

from __future__ import annotations

import sys
from typing import Any

from .contracts import error_response, success_base, validate_response
from .errors import XlocError, warning
from .mapfile import find_map_file, iter_loc_ids, load_map
from .scan import scan_log
from .xout import dumps, to_xout


def _load_optional_map(log_path: str, map_path: str | None) -> tuple[str | None, dict[str, dict]]:
    selected = map_path if map_path is not None else find_map_file(log_path)
    if selected is None:
        return None, {}
    return selected, load_map(selected)


def annotate_payload(log_path: str, map_path: str | None = None) -> dict[str, Any]:
    """Build a complete response without inventing unresolved file names."""
    try:
        scan = scan_log(log_path, retain_lines=True)
        selected_map, entries = _load_optional_map(log_path, map_path)
    except XlocError as exc:
        return error_response("annotate", exc)

    seen: set[str] = set()
    unresolved: list[str] = []
    lines: list[str] = []
    annotation_count = 0
    for line in scan.lines:
        for loc_id in iter_loc_ids(line):
            if loc_id in seen:
                continue
            seen.add(loc_id)
            entry = entries.get(loc_id)
            if entry is None:
                unresolved.append(loc_id)
                continue
            if line.endswith("\r\n"):
                line_ending = "\r\n"
            elif line.endswith("\n"):
                line_ending = "\n"
            elif line.endswith("\r"):
                line_ending = "\r"
            else:
                line_ending = "\n"
            lines.append(f"[loc] {loc_id} -> {entry['file']}{line_ending}")
            annotation_count += 1
        lines.append(line)

    diagnostics: list[dict[str, Any]] = []
    if seen and selected_map is None:
        diagnostics.append(warning(
            "MAP_UNAVAILABLE",
            "no sidecar map was supplied or found; unresolved locations were not annotated",
            path=log_path + ".xloc.jsonl", count=len(unresolved),
        ))
    diagnostics.extend(
        warning(
            "LOC_ID_UNRESOLVED",
            f"{loc_id} is present in the log but absent from the map",
            path=selected_map if selected_map is not None else log_path,
            loc_id=loc_id,
        )
        for loc_id in unresolved
    )
    payload = success_base(
        "annotate", analysis_complete=not unresolved,
        response_truncated=False, total_count=len(seen),
        returned_count=annotation_count, truncation_scopes=[],
        diagnostics=diagnostics,
    )
    payload.update({
        "log": log_path, "map": selected_map,
        "source_line_count": scan.line_count,
        "unique_location_count": len(seen),
        "annotation_count": annotation_count,
        "unresolved_location_count": len(unresolved),
        "lines": lines,
    })
    return validate_response(payload)


def render_raw(payload: dict[str, Any]) -> str:
    validate_response(payload)
    if not payload["ok"]:
        error = payload["error"]
        raise XlocError(error["code"], error["message"])
    if payload["status"] != "complete":
        raise XlocError(
            "RAW_OUTPUT_INCOMPLETE",
            "raw annotate output requires complete location resolution; use JSON or XOUT to inspect diagnostics",
            count=payload["unresolved_location_count"],
        )
    return "".join(payload["lines"])


def cmd_annotate(
    log_path: str, map_path: str | None = None, output_format: str = "xout",
) -> int:
    payload = annotate_payload(log_path, map_path)
    if output_format == "raw":
        try:
            rendered = render_raw(payload)
        except XlocError as exc:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
            return 1
        print(rendered, end="")
    elif output_format == "json":
        print(dumps(payload))
    elif output_format == "xout":
        print(to_xout(payload), end="")
    else:
        raise XlocError("INVALID_OUTPUT_FORMAT", "output_format must be one of: xout, json, raw")
    return 0 if payload["ok"] else 1
