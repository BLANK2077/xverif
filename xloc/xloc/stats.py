"""Deterministic xloc hotspot statistics."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .contracts import error_response, success_base, validate_response
from .errors import XlocError, warning
from .mapfile import find_map_file, load_map
from .scan import scan_log
from .xout import to_xout


def _load_optional_map(log_path: str, map_path: str | None) -> tuple[str | None, dict[str, dict]]:
    selected = map_path if map_path is not None else find_map_file(log_path)
    if selected is None:
        return None, {}
    return selected, load_map(selected)


def stats_payload(log_path: str, map_path: str | None = None, top: int = 20) -> dict[str, Any]:
    try:
        if not isinstance(top, int) or isinstance(top, bool) or top <= 0:
            raise XlocError("INVALID_TOP", "top must be a positive integer")
        scan = scan_log(log_path, retain_lines=False)
        selected_map, entries = _load_optional_map(log_path, map_path)
    except XlocError as exc:
        return error_response("stats", exc)

    counts = Counter(scan.loc_ids)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    unresolved = [loc_id for loc_id, _ in ordered if loc_id not in entries]
    resolved = [loc_id for loc_id, _ in ordered if loc_id in entries]
    diagnostics: list[dict[str, Any]] = []
    if ordered and selected_map is None:
        diagnostics.append(warning(
            "MAP_UNAVAILABLE",
            "no sidecar map was supplied or found; location resolution is incomplete",
            path=log_path + ".xloc.jsonl", count=len(unresolved),
        ))
    diagnostics.extend(
        warning(
            "LOC_ID_UNRESOLVED",
            f"{loc_id} is present in the log but absent from the map",
            path=selected_map if selected_map is not None else log_path,
            loc_id=loc_id, count=counts[loc_id],
        )
        for loc_id in unresolved
    )
    rows: list[dict[str, Any]] = []
    for loc_id, count in ordered[:top]:
        row: dict[str, Any] = {
            "loc_id": loc_id,
            "count": count,
            "resolution_status": "resolved" if loc_id in entries else "unresolved",
        }
        if loc_id in entries:
            row["file"] = entries[loc_id]["file"]
        rows.append(row)
    response_truncated = len(ordered) > top
    payload = success_base(
        "stats", analysis_complete=not unresolved,
        response_truncated=response_truncated, total_count=len(ordered),
        returned_count=len(rows),
        truncation_scopes=["rows"] if response_truncated else [],
        diagnostics=diagnostics,
    )
    payload.update({
        "log": log_path, "map": selected_map,
        "unique_location_count": len(ordered),
        "resolved_location_count": len(resolved),
        "unresolved_location_count": len(unresolved),
        "unique_file_count": len({entries[loc_id]["file"] for loc_id in resolved}),
        "total_occurrence_count": sum(counts.values()), "rows": rows,
    })
    return validate_response(payload)


def render_stats(payload: dict[str, Any]) -> str:
    return to_xout(payload)


def cmd_stats(log_path: str, map_path: str | None = None, top: int = 20) -> int:
    payload = stats_payload(log_path, map_path, top)
    print(render_stats(payload), end="")
    return 0 if payload["ok"] else 1
