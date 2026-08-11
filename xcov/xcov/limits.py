"""Closed resource budgets for untrusted xcov requests and artifacts."""
from __future__ import annotations

import json
from typing import Any, Dict

from .errors import XcovError

Json = Dict[str, Any]

MAX_REQUEST_BYTES = 1 * 1024 * 1024
MAX_SCHEMA_STRING_CHARS = 64 * 1024
MAX_SCHEMA_ARRAY_ITEMS = 100_000
MAX_QUERY_PATTERNS = 64
MAX_EXPORT_SCOPES = 256
MAX_RESPONSE_ROWS = 10_000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_IR_SCOPES = 100_000
MAX_TYPED_ROWS = 500_000
MAX_GAP_ROWS = 100_000
MAX_CSV_BYTES = 64 * 1024 * 1024
MAX_CSV_RECORDS = 100_000
MAX_CSV_FIELD_CHARS = 16 * 1024
MAX_ARTIFACT_BYTES = 1 * 1024 * 1024 * 1024
MAX_ARTIFACT_TOTAL_BYTES = 2 * 1024 * 1024 * 1024


def enforce_request_budget(text: str) -> None:
    size = len(text.encode("utf-8"))
    if size > MAX_REQUEST_BYTES:
        raise XcovError(
            "REQUEST_BUDGET_EXCEEDED",
            "request exceeds the xcov transport byte budget",
            request_bytes=size,
            max_request_bytes=MAX_REQUEST_BYTES,
        )


def enforce_response_budget(response: Json) -> None:
    size = len(json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    if size > MAX_RESPONSE_BYTES:
        raise XcovError(
            "RESPONSE_BUDGET_EXCEEDED",
            "response exceeds the xcov inline byte budget; narrow the query",
            response_bytes=size,
            max_response_bytes=MAX_RESPONSE_BYTES,
        )


def enforce_count(kind: str, count: int, maximum: int) -> None:
    if count > maximum:
        raise XcovError(
            "RESOURCE_BUDGET_EXCEEDED",
            f"{kind} exceeds the configured xcov resource budget",
            resource_kind=kind,
            resource_count=count,
            max_resource_count=maximum,
        )
