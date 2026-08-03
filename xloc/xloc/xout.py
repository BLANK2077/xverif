import json
import re

from .contracts import validate_response


def to_xout(payload: dict, *, action: str | None = None) -> str:
    """Render action-specific, token-efficient xloc evidence."""
    validate_response(payload)
    resolved_action = str(action or payload.get("action") or "error")
    out = TextResponseBuilder("xloc")
    out.emit_header(resolved_action)
    if not payload["ok"]:
        out.emit_section("error")
        for key, value in payload["error"].items():
            out.emit_kv(key, value)
        _emit_diagnostics(out, payload)
        return out.render()
    if resolved_action == "resolve":
        out.emit_section("target")
        for key in ("loc_id", "file", "map"):
            out.emit_kv(key, payload.get(key))
    elif resolved_action == "context":
        out.emit_section("target")
        for key in ("loc_id", "file", "line", "map", "before", "after"):
            out.emit_kv(key, payload.get(key))
        out.emit_section("context")
        for row in payload.get("context", []):
            out.emit_row(">" if row.get("hit") else " ", row.get("line"), row.get("text", ""))
    elif resolved_action == "stats":
        out.emit_section("summary")
        for key in (
            "log", "map", "unique_location_count", "resolved_location_count",
            "unresolved_location_count", "unique_file_count", "total_occurrence_count",
        ):
            out.emit_kv(key, payload.get(key))
        out.emit_section("locations")
        for row in payload.get("rows", []):
            out.emit_row(row.get("loc_id"), row.get("count"), row.get("resolution_status"), row.get("file"))
    elif resolved_action == "annotate":
        out.emit_section("summary")
        for key in ("log", "map", "status", "annotation_count", "resolved_location_count", "unresolved_location_count"):
            out.emit_kv(key, payload.get(key))
        out.emit_section("data")
        for line in payload.get("lines", []):
            out.emit_row(str(line).rstrip("\r\n"))
    else:
        out.emit_section("summary")
        for key, value in payload.items():
            if key not in {"ok", "action", "diagnostics"} and not isinstance(value, (list, dict)):
                out.emit_kv(key, value)
        out.emit_section("data")
        for key, value in payload.items():
            if isinstance(value, (list, dict)) and key != "diagnostics":
                out.emit_kv(key, value)
    _emit_diagnostics(out, payload)
    return out.render()


def _key(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value)) or "field"


def _value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    return text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", " ")


class TextResponseBuilder:
    def __init__(self, tool: str):
        self.tool = tool
        self.lines: list[str] = []
        self.pending: str | None = None
        self.in_section = False
        self.wrote = False

    def emit_header(self, action: str) -> None:
        self.lines.append(f"@{self.tool}.{action}.v1")

    def emit_section(self, name: str) -> None:
        self.pending = _key(name)

    def _ensure(self) -> bool:
        nested = self.in_section or self.pending is not None
        if self.pending is not None:
            if self.wrote:
                self.lines.append("")
            self.lines.append(f"{self.pending}:")
            self.pending = None
            self.in_section = True
            self.wrote = True
        elif not self.wrote:
            self.lines.append("")
            self.wrote = True
        return nested

    def emit_kv(self, key: str, value: object) -> None:
        if value is None or value == {} or value == []:
            return
        nested = self._ensure()
        self.lines.append(f"{'  ' if nested else ''}{_key(key)}: {_value(value)}")

    def emit_row(self, *columns: object) -> None:
        row = " ".join(" ".join(_value(col).split()) for col in columns if _value(col))
        if row:
            nested = self._ensure()
            self.lines.append(f"{'  ' if nested else ''}{row}")

    def render(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def _emit_diagnostics(out: TextResponseBuilder, payload: dict) -> None:
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        out.emit_section("warnings")
        for item in diagnostics:
            if isinstance(item, dict):
                out.emit_row(item.get("code"), item.get("message"), item.get("loc_id"), item.get("path"))
            else:
                out.emit_row(item)


def dumps(payload: dict) -> str:
    validate_response(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)
