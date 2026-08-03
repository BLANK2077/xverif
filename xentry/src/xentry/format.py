from __future__ import annotations

import json
import re
from typing import Any

from .contracts import ACTIONS, validate_response
from .errors import XentryError


def dumps(payload: dict, *, pretty: bool = False) -> str:
    validate_response(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None, sort_keys=False)


def _sanitize_key(key: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))
    return text or "field"


def _sanitize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", " ")
    if len(text) > 4096:
        text = text[:4096] + "..."
    return text


def _row_value(value: Any) -> str:
    return " ".join(_sanitize_value(value).split())


class TextResponseBuilder:
    def __init__(self, tool: str):
        self.tool = tool
        self.lines: list[str] = []
        self.pending_section: str | None = None
        self.in_section = False
        self.wrote_content = False

    def emit_header(self, action: str) -> None:
        if not self.lines:
            self.lines.append(f"@{self.tool}.{action}.v1")

    def emit_section(self, name: str) -> None:
        self.pending_section = _sanitize_key(name)

    def _ensure_section(self) -> bool:
        if self.pending_section is None:
            return self.in_section
        if self.wrote_content:
            self.lines.append("")
        self.lines.append(f"{self.pending_section}:")
        self.pending_section = None
        self.in_section = True
        self.wrote_content = True
        return True

    def emit_kv(self, key: str, value: Any) -> None:
        if value is None or value == {} or value == []:
            return
        text = _sanitize_value(value)
        if not text:
            return
        nested = self.in_section or self.pending_section is not None
        self._ensure_section()
        if not self.wrote_content:
            self.lines.append("")
            self.wrote_content = True
        self.lines.append(f"{'  ' if nested else ''}{_sanitize_key(key)}: {text}")

    def emit_row(self, *columns: Any) -> None:
        row = " ".join(part for part in (_row_value(col) for col in columns) if part)
        if not row:
            return
        nested = self.in_section or self.pending_section is not None
        self._ensure_section()
        if not self.wrote_content:
            self.lines.append("")
            self.wrote_content = True
        self.lines.append(f"{'  ' if nested else ''}{row}")

    def emit_warning(self, code: str, message: str) -> None:
        self.emit_section("warnings")
        self.emit_row(code, message)

    def emit_error(self, error: dict) -> None:
        self.emit_kv("code", error.get("code"))
        self.emit_kv("message", error.get("message"))

    def render(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def to_xout(payload: dict) -> str:
    validate_response(payload)
    action = payload["action"]
    out = TextResponseBuilder("xentry")
    out.emit_header(str(action or "unknown"))
    if not payload.get("ok"):
        out.emit_kv("action", action)
        out.emit_error(payload["error"])
        return out.render()
    if payload.get("action") == "decode":
        out.emit_section("target")
        out.emit_kv("schema", payload.get("schema"))
        out.emit_kv("total_bits", payload.get("total_bits"))
        out.emit_section("summary")
        out.emit_kv("fields", len(payload.get("fields", {})))
        out.emit_kv("warnings", len(payload.get("warnings", [])))
        out.emit_kv("entry_raw", payload.get("entry_raw"))
        out.emit_section("fields")
        for name, field in payload.get("fields", {}).items():
            sources = []
            for src in field.get("source", []):
                seq = src.get("seq")
                entry_bits = src.get("entry_bits")
                fragment_bits = src.get("fragment_bits")
                sources.append(f"seq{seq}{fragment_bits}->entry{entry_bits}")
            out.emit_row(name, field.get("bits"), field.get("width"), field.get("raw_hex"), field.get("raw_bin"), ",".join(sources))
    elif payload.get("action") == "explain":
        out.emit_section("summary")
        out.emit_kv("schema", payload.get("schema"))
        out.emit_kv("total_bits", payload.get("total_bits"))
        out.emit_kv("fragment_byte_order", payload.get("fragment_byte_order"))
        out.emit_kv("bit_numbering", payload.get("bit_numbering"))
        out.emit_section("fields")
        for field in payload.get("fields", []):
            out.emit_row(field.get("name"), field.get("bits"), field.get("width"), field.get("description", ""))
    else:
        out.emit_section("summary")
        out.emit_kv("schema", payload.get("schema"))
        out.emit_kv("total_bits", payload.get("total_bits"))
        out.emit_kv("warnings", len(payload.get("warnings", [])))
    for warning in payload.get("warnings", []):
        if isinstance(warning, dict):
            out.emit_warning(str(warning.get("code", "warning")), str(warning.get("message", warning)))
        else:
            out.emit_warning("warning", str(warning))
    return out.render()


def error_response(exc: Exception, *, action: str = "", request_id: Any = None) -> dict:
    if isinstance(exc, XentryError):
        error = {"code": exc.code, "message": exc.message}
        if exc.details:
            error["details"] = exc.details
    else:
        error = {"code": "INTERNAL_ERROR", "message": str(exc)}
    canonical_action = action if action in ACTIONS else "error"
    payload = {
        "ok": False,
        "api_version": "xentry.v1",
        "action": canonical_action,
        "error": error,
        "warnings": [],
    }
    if isinstance(request_id, str) and request_id:
        payload["request_id"] = request_id
    validate_response(payload, expected_action=canonical_action)
    return payload
