import json
import os
import re
from typing import Dict, Iterator, Optional

from .errors import XlocError

LOC_ID_RE = re.compile(
    r'(?<![A-Za-z0-9_])L_[0-9A-F]{8}(?![A-Za-z0-9_])'
)
MAP_FIELDS = frozenset({"loc_id", "file"})


class _DuplicateJsonField(ValueError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def _closed_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonField(str(key))
        value[key] = item
    return value


def load_map(map_path: str) -> Dict[str, dict]:
    """Load one closed-schema UTF-8 JSONL sidecar."""

    if not isinstance(map_path, str) or not map_path:
        raise XlocError("INVALID_MAP_PATH", "map path must be a non-empty string")

    entries: Dict[str, dict] = {}
    try:
        with open(map_path, "r", encoding="utf-8", newline="") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.rstrip("\r\n")
                if not line.strip():
                    raise XlocError(
                        "MAP_INVALID_JSONL",
                        f"blank JSONL record at line {line_number}",
                        path=map_path,
                        line=line_number,
                    )
                try:
                    entry = json.loads(line, object_pairs_hook=_closed_json_object)
                except _DuplicateJsonField as exc:
                    raise XlocError(
                        "MAP_DUPLICATE_FIELD",
                        f"duplicate JSON object field {exc.field!r} at line {line_number}",
                        path=map_path,
                        line=line_number,
                    ) from exc
                except json.JSONDecodeError as exc:
                    raise XlocError(
                        "MAP_INVALID_JSON",
                        f"invalid JSON at line {line_number}, column {exc.colno}: {exc.msg}",
                        path=map_path,
                        line=line_number,
                    ) from exc
                if not isinstance(entry, dict):
                    raise XlocError(
                        "MAP_INVALID_ENTRY",
                        f"map line {line_number} must be a JSON object",
                        path=map_path,
                        line=line_number,
                    )
                actual_fields = set(entry)
                if actual_fields != MAP_FIELDS:
                    unknown = sorted(actual_fields - MAP_FIELDS)
                    missing = sorted(MAP_FIELDS - actual_fields)
                    details = []
                    if unknown:
                        details.append(f"unknown fields={unknown}")
                    if missing:
                        details.append(f"missing fields={missing}")
                    raise XlocError(
                        "MAP_SCHEMA_VIOLATION",
                        f"map line {line_number} must contain exactly loc_id and file ({'; '.join(details)})",
                        path=map_path,
                        line=line_number,
                    )
                loc_id = entry["loc_id"]
                file_path = entry["file"]
                if not isinstance(loc_id, str) or LOC_ID_RE.fullmatch(loc_id) is None:
                    raise XlocError(
                        "MAP_INVALID_LOC_ID",
                        f"map line {line_number} loc_id must match L_[0-9A-F]{{8}}",
                        path=map_path,
                        line=line_number,
                    )
                if (
                    not isinstance(file_path, str)
                    or not file_path
                    or any(
                        ord(char) < 0x20 or 0xD800 <= ord(char) <= 0xDFFF
                        for char in file_path
                    )
                ):
                    raise XlocError(
                        "MAP_INVALID_FILE",
                        f"map line {line_number} file must be a non-empty Unicode string without control characters",
                        path=map_path,
                        line=line_number,
                        loc_id=loc_id,
                    )
                if loc_id in entries:
                    raise XlocError(
                        "MAP_DUPLICATE_LOC_ID",
                        f"duplicate loc_id {loc_id} at line {line_number}",
                        path=map_path,
                        line=line_number,
                        loc_id=loc_id,
                    )
                entries[loc_id] = {"loc_id": loc_id, "file": file_path}
    except FileNotFoundError as exc:
        raise XlocError(
            "MAP_FILE_NOT_FOUND", f"map file not found: {map_path}", path=map_path
        ) from exc
    except UnicodeDecodeError as exc:
        raise XlocError(
            "MAP_INVALID_UTF8",
            f"map is not valid UTF-8 at byte {exc.start}: {map_path}",
            path=map_path,
        ) from exc
    except XlocError:
        raise
    except OSError as exc:
        raise XlocError(
            "MAP_READ_ERROR", f"cannot read map file {map_path}: {exc}", path=map_path
        ) from exc
    return entries


def resolve_loc(entries: Dict[str, dict], loc_id: str) -> Optional[dict]:
    """Look up a single loc_id in the loaded map."""
    return entries.get(loc_id)


def iter_loc_ids(text: str) -> Iterator[str]:
    """Yield every strict loc_id occurrence from left to right."""
    for match in LOC_ID_RE.finditer(text):
        yield match.group()


def find_map_file(log_path: str) -> Optional[str]:
    """Return the adjacent sidecar map when it is a regular file."""
    candidate = log_path + '.xloc.jsonl'
    if os.path.isfile(candidate):
        return candidate
    return None
