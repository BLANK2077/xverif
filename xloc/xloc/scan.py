"""Canonical deterministic Python log scanner."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import XlocError
from .mapfile import iter_loc_ids


@dataclass(frozen=True)
class LogScan:
    loc_ids: tuple[str, ...]
    lines: tuple[str, ...]
    line_count: int


def scan_log(log_path: str, *, retain_lines: bool) -> LogScan:
    """Scan one UTF-8 log without external commands or alternate scanners."""

    if not isinstance(log_path, str) or not log_path:
        raise XlocError("INVALID_LOG_PATH", "log path must be a non-empty string")

    loc_ids: list[str] = []
    lines: list[str] = []
    line_count = 0
    try:
        with open(log_path, "r", encoding="utf-8", newline="") as stream:
            for line in stream:
                line_count += 1
                loc_ids.extend(iter_loc_ids(line))
                if retain_lines:
                    lines.append(line)
    except FileNotFoundError as exc:
        raise XlocError(
            "LOG_FILE_NOT_FOUND",
            f"log file not found: {log_path}",
            path=log_path,
        ) from exc
    except UnicodeDecodeError as exc:
        raise XlocError(
            "LOG_INVALID_UTF8",
            f"log is not valid UTF-8 at byte {exc.start}: {log_path}",
            path=log_path,
        ) from exc
    except OSError as exc:
        raise XlocError(
            "LOG_READ_ERROR",
            f"cannot read log file {log_path}: {exc}",
            path=log_path,
        ) from exc

    return LogScan(tuple(loc_ids), tuple(lines), line_count)
