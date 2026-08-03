"""Strict JSON and compact XOUT boundary helpers."""

from __future__ import annotations

import re
from typing import Any

from xverif_loop.json_contract import strict_json_loads


_XDEBUG_HEADER = re.compile(r"^@xdebug\.(?P<action>.+)\.v1$")
_XCOV_HEADER = re.compile(
    r"^@xcov\.v1\s+(?:ok|error)\s+action=(?P<action>\S+)(?:\s|$)"
)


def validate_xout_text(
    text: str,
    *,
    tool: str | None = None,
    expected_action: str | None = None,
) -> None:
    """Validate native XOUT without attempting to reconstruct JSON."""

    if not isinstance(text, str) or not text.strip():
        raise ValueError("XOUT response must be non-empty text")
    if "\x00" in text:
        raise ValueError("XOUT response must not contain NUL characters")
    first_line = text.splitlines()[0]
    if tool == "xdebug":
        match = _XDEBUG_HEADER.fullmatch(first_line)
        if match is None:
            raise ValueError("xdebug XOUT header must be @xdebug.<action>.v1")
        if expected_action is not None and match.group("action") != expected_action:
            raise ValueError("xdebug XOUT action does not match request")
    elif tool == "xcov":
        match = _XCOV_HEADER.match(first_line)
        if match is None:
            raise ValueError(
                "xcov XOUT header must be @xcov.v1 <status> action=<action> ..."
            )
        if expected_action is not None and match.group("action") != expected_action:
            raise ValueError("xcov XOUT action does not match request")


def frame_transport_xout(envelope: dict[str, Any]) -> str:
    """Validate transport metadata and return native xdebug XOUT unchanged."""

    if envelope.get("payload_format") != "xout":
        raise ValueError("transport envelope payload_format must be xout")
    action = envelope.get("action")
    api_version = envelope.get("api_version")
    request_id = envelope.get("id")
    ok = envelope.get("ok")
    text = envelope.get("xout")
    if not isinstance(action, str) or not action:
        raise ValueError("transport envelope requires a non-empty action")
    if not isinstance(api_version, str) or not api_version:
        raise ValueError("transport envelope requires a non-empty api_version")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("transport envelope requires a non-empty id")
    if not isinstance(ok, bool):
        raise ValueError("transport envelope requires a boolean ok")
    validate_xout_text(text, tool="xdebug", expected_action=action)
    return text
