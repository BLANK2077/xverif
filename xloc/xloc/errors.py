"""Typed xloc domain failures."""

from __future__ import annotations

from typing import Any


class XlocError(Exception):
    """A deterministic, machine-readable xloc failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        line: int | None = None,
        loc_id: str | None = None,
        count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.line = line
        self.loc_id = loc_id
        self.count = count

    def diagnostic(self, *, severity: str = "error") -> dict[str, Any]:
        item: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": severity,
        }
        if self.path is not None:
            item["path"] = self.path
        if self.line is not None:
            item["line"] = self.line
        if self.loc_id is not None:
            item["loc_id"] = self.loc_id
        if self.count is not None:
            item["count"] = self.count
        return item


def warning(
    code: str,
    message: str,
    *,
    path: str | None = None,
    line: int | None = None,
    loc_id: str | None = None,
    count: int | None = None,
) -> dict[str, Any]:
    """Build one strict warning diagnostic."""

    return XlocError(
        code,
        message,
        path=path,
        line=line,
        loc_id=loc_id,
        count=count,
    ).diagnostic(severity="warning")
