"""Resolve xloc IDs and retrieve strict source context."""

from __future__ import annotations

from typing import Any

from .contracts import error_response, success_base, validate_response
from .errors import XlocError
from .mapfile import LOC_ID_RE, load_map, resolve_loc
from .xout import to_xout


def _require_loc_id(loc_id: str) -> None:
    if not isinstance(loc_id, str) or LOC_ID_RE.fullmatch(loc_id) is None:
        raise XlocError(
            "INVALID_LOC_ID",
            "loc_id must match L_[0-9A-F]{8}",
            loc_id=loc_id if isinstance(loc_id, str) and loc_id else None,
        )


def _require_non_negative(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise XlocError("INVALID_ARGUMENT", f"{name} must be a non-negative integer")


def _resolve_entry(loc_id: str, map_path: str) -> dict[str, str]:
    _require_loc_id(loc_id)
    entries = load_map(map_path)
    entry = resolve_loc(entries, loc_id)
    if entry is None:
        raise XlocError(
            "LOC_ID_NOT_FOUND",
            f"{loc_id} not found in map {map_path}",
            path=map_path,
            loc_id=loc_id,
        )
    return entry


def resolve_payload(loc_id: str, map_path: str) -> dict[str, Any]:
    try:
        entry = _resolve_entry(loc_id, map_path)
    except XlocError as exc:
        return error_response("resolve", exc)
    payload = success_base(
        "resolve", analysis_complete=True, response_truncated=False,
        total_count=1, returned_count=1, truncation_scopes=[], diagnostics=[],
    )
    payload.update({"map": map_path, "loc_id": entry["loc_id"], "file": entry["file"]})
    return validate_response(payload)


def _strip_line_ending(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n") or text.endswith("\r"):
        return text[:-1]
    return text


def context_payload(
    loc_id: str,
    map_path: str,
    line: int,
    before: int = 20,
    after: int = 20,
) -> dict[str, Any]:
    try:
        if not isinstance(line, int) or isinstance(line, bool) or line <= 0:
            raise XlocError("INVALID_LINE", "line must be a positive integer")
        _require_non_negative(before, "before")
        _require_non_negative(after, "after")
        entry = _resolve_entry(loc_id, map_path)
        filepath = entry["file"]
        try:
            with open(filepath, "r", encoding="utf-8", newline="") as stream:
                source_lines = stream.readlines()
        except FileNotFoundError as exc:
            raise XlocError(
                "SOURCE_FILE_NOT_FOUND", f"source file not found: {filepath}",
                path=filepath, loc_id=loc_id,
            ) from exc
        except UnicodeDecodeError as exc:
            raise XlocError(
                "SOURCE_INVALID_UTF8",
                f"source is not valid UTF-8 at byte {exc.start}: {filepath}",
                path=filepath, loc_id=loc_id,
            ) from exc
        except OSError as exc:
            raise XlocError(
                "SOURCE_READ_ERROR", f"cannot read source file {filepath}: {exc}",
                path=filepath, loc_id=loc_id,
            ) from exc
        if line > len(source_lines):
            raise XlocError(
                "SOURCE_LINE_OUT_OF_RANGE",
                f"source line {line} is outside {filepath} (line_count={len(source_lines)})",
                path=filepath, line=line, loc_id=loc_id, count=len(source_lines),
            )
    except XlocError as exc:
        return error_response("context", exc)

    start = max(0, line - before - 1)
    end = min(len(source_lines), line + after)
    context = [
        {"line": index + 1, "hit": index == line - 1, "text": _strip_line_ending(source_lines[index])}
        for index in range(start, end)
    ]
    payload = success_base(
        "context", analysis_complete=True, response_truncated=False,
        total_count=len(context), returned_count=len(context),
        truncation_scopes=[], diagnostics=[],
    )
    payload.update({
        "map": map_path, "loc_id": entry["loc_id"], "file": entry["file"],
        "line": line, "before": before, "after": after, "context": context,
    })
    return validate_response(payload)


def render_payload(payload: dict[str, Any]) -> str:
    return to_xout(payload)


def cmd_resolve(loc_id: str, map_path: str) -> int:
    payload = resolve_payload(loc_id, map_path)
    print(render_payload(payload), end="")
    return 0 if payload["ok"] else 1


def cmd_context(
    loc_id: str, map_path: str, line: int, before: int = 20, after: int = 20,
) -> int:
    payload = context_payload(loc_id, map_path, line, before, after)
    print(render_payload(payload), end="")
    return 0 if payload["ok"] else 1
