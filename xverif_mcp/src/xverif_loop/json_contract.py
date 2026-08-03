"""Strict RFC 8259 JSON primitives shared by every loop transport surface."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any


_SENSITIVE_KEY_RE = re.compile(
    r"(?:auth|bearer|cookie|credential|password|refresh|secret|token)",
    re.IGNORECASE,
)
_REDACTED_FIELD = {"redacted": True}
_REDACTED_TEXT = "<redacted>"


def _reject_non_finite_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def is_sensitive_json_key(key: str) -> bool:
    """Return whether a JSON field name carries secret material."""

    return bool(_SENSITIVE_KEY_RE.search(key))


def redact_sensitive_json(
    value: Any,
    *,
    secret_values: Iterable[str] = (),
) -> Any:
    """Copy a public JSON value while recursively removing secret material."""

    secrets = tuple(
        secret
        for secret in secret_values
        if isinstance(secret, str) and secret
    )

    def redact_text(text: str) -> str:
        for secret in secrets:
            text = text.replace(secret, _REDACTED_TEXT)
        return text

    def redact(item: Any, key: str = "") -> Any:
        if key and is_sensitive_json_key(key):
            return dict(_REDACTED_FIELD)
        if isinstance(item, str):
            return redact_text(item)
        if isinstance(item, (list, tuple)):
            return [redact(nested) for nested in item]
        if isinstance(item, dict):
            return {
                redact_text(str(nested_key)): redact(
                    nested_value,
                    str(nested_key),
                )
                for nested_key, nested_value in item.items()
            }
        return item

    return redact(value)


def strict_json_loads(text: str) -> Any:
    """Decode JSON while rejecting Python's NaN/Infinity extensions."""
    return json.loads(text, parse_constant=_reject_non_finite_constant)


def strict_json_dumps(
    value: Any,
    *,
    ensure_ascii: bool = False,
    separators: tuple[str, str] | None = None,
    sort_keys: bool = False,
) -> str:
    """Encode JSON while rejecting non-finite floats and unsupported values."""
    return json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        separators=separators,
        sort_keys=sort_keys,
        allow_nan=False,
    )
