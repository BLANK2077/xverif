from __future__ import annotations

from typing import Any, Dict

Json = Dict[str, Any]


class XcovError(Exception):
    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_json(self) -> Json:
        err: Json = {"code": self.code, "message": self.message}
        for key, value in self.detail.items():
            err[f"detail.{key}"] = value
        return err


def error_response(action: str, request_id: str, code: str, message: str,
                   **detail: Any) -> Json:
    err = XcovError(code, message, **detail)
    response_action = action if action else "error"
    return {
        "ok": False,
        "api_version": "xcov.v1",
        "request_id": request_id,
        "action": response_action,
        "summary": {
            "total_count": 0,
            "returned_count": 0,
            "response_truncated": False,
            "scan_complete": False,
            "analysis_complete": False,
            "truncation_scopes": [],
        },
        "data": {},
        "error": err.to_json(),
        "warnings": [],
    }
