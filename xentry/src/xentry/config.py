from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .errors import ConfigError, UnsupportedConfigField


BITS_RE = re.compile(r"^\[(\d+):(\d+)\]$")
SUPPORTED_TOP = {"name", "version", "total_bits", "fragment_byte_order", "bit_numbering", "fields"}
SUPPORTED_FIELD = {"name", "bits", "description"}
UNSUPPORTED_FIELD = {"type", "enum", "alias_of", "ipv4", "mac", "bool"}


@dataclass(frozen=True)
class FieldConfig:
    name: str
    bits: str
    msb: int
    lsb: int
    width: int
    description: str | None = None


@dataclass(frozen=True)
class EntryConfig:
    name: str
    version: int
    total_bits: int
    fragment_byte_order: str
    bit_numbering: str
    fields: list[FieldConfig]

    def schema_result(self) -> dict:
        return {"name": self.name, "version": self.version}


def parse_bits(bits: str) -> tuple[int, int, int]:
    if not isinstance(bits, str):
        raise ConfigError("field bits must be a string like [msb:lsb]")
    m = BITS_RE.match(bits.strip())
    if not m:
        raise ConfigError("field bits must use [msb:lsb] format", bits=bits)
    msb = int(m.group(1))
    lsb = int(m.group(2))
    if msb < lsb:
        raise ConfigError("field bits must have msb >= lsb", bits=bits)
    return msb, lsb, msb - lsb + 1


def load_config_text(text: str) -> dict:
    stripped = text.lstrip()
    if not stripped:
        raise ConfigError("config is empty")
    if stripped[0] in "{[":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON config: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("config JSON must be an object")
        return data
    return parse_yaml_subset(text)


def load_config_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return load_config_text(fh.read())


def normalize_config(data: dict) -> tuple[EntryConfig, list[dict]]:
    if not isinstance(data, dict):
        raise ConfigError("config must be an object")
    for key in data:
        if key not in SUPPORTED_TOP:
            raise ConfigError("unsupported top-level config field", field=key)
    required = ["name", "version", "total_bits", "fragment_byte_order", "bit_numbering", "fields"]
    for key in required:
        if key not in data:
            raise ConfigError("missing required config field", field=key)
    name = data["name"]
    if not isinstance(name, str) or not name:
        raise ConfigError("name must be a non-empty string", field="name")
    version = _positive_int(data["version"], "version")
    total_bits = _positive_int(data["total_bits"], "total_bits")
    fragment_byte_order = data["fragment_byte_order"]
    bit_numbering = data["bit_numbering"]
    if not isinstance(fragment_byte_order, str):
        raise ConfigError("fragment_byte_order must be a string", field="fragment_byte_order")
    if not isinstance(bit_numbering, str):
        raise ConfigError("bit_numbering must be a string", field="bit_numbering")
    if fragment_byte_order not in {"msb_first", "lsb_first"}:
        raise ConfigError("fragment_byte_order must be msb_first or lsb_first", value=fragment_byte_order)
    if bit_numbering not in {"byte_lsb0", "byte_msb0"}:
        raise ConfigError("bit_numbering must be byte_lsb0 or byte_msb0", value=bit_numbering)
    raw_fields = data["fields"]
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ConfigError("fields must be a non-empty list")
    fields: list[FieldConfig] = []
    names: set[str] = set()
    warnings: list[dict] = []
    occupied: dict[int, str] = {}
    for raw in raw_fields:
        if not isinstance(raw, dict):
            raise ConfigError("each field must be an object")
        for key in raw:
            if key in UNSUPPORTED_FIELD or key not in SUPPORTED_FIELD:
                raise UnsupportedConfigField("unsupported field config key", field=raw.get("name", ""), key=key)
        if "name" not in raw or "bits" not in raw:
            raise ConfigError("field requires name and bits")
        fname = raw["name"]
        if not isinstance(fname, str) or not fname:
            raise ConfigError("field name must be a non-empty string", field="name")
        if fname in names:
            raise ConfigError("duplicate field name", field=fname)
        names.add(fname)
        msb, lsb, width = parse_bits(raw["bits"])
        if msb >= total_bits:
            raise ConfigError("field range exceeds total_bits", field=fname, bits=raw["bits"], total_bits=total_bits)
        description = raw.get("description")
        if description is not None and not isinstance(description, str):
            raise ConfigError("field description must be a string", field=fname)
        field = FieldConfig(fname, raw["bits"], msb, lsb, width, description)
        fields.append(field)
        overlaps = sorted({occupied[bit] for bit in range(lsb, msb + 1) if bit in occupied})
        if overlaps:
            warnings.append({
                "code": "FIELD_OVERLAP",
                "message": f"field {fname} overlaps existing fields",
                "field": fname,
                "overlaps": overlaps,
            })
        for bit in range(lsb, msb + 1):
            occupied.setdefault(bit, fname)
    return EntryConfig(name, version, total_bits, fragment_byte_order, bit_numbering, fields), warnings


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{field} must be a positive integer")
    if value <= 0:
        raise ConfigError(f"{field} must be positive", value=value)
    return value


def parse_yaml_subset(text: str) -> dict:
    root: dict[str, Any] = {}
    lines = [(idx + 1, _strip_comment(line.rstrip("\n"))) for idx, line in enumerate(text.splitlines())]
    i = 0
    while i < len(lines):
        lineno, line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith(" "):
            raise ConfigError("top-level YAML keys must not be indented", line=lineno)
        key, value = _split_key_value(line, lineno)
        if key == "fields" and value == "":
            fields, i = _parse_fields(lines, i + 1)
            root[key] = fields
            continue
        root[key] = _parse_scalar(value)
        i += 1
    return root


def _parse_fields(lines: list[tuple[int, str]], start: int) -> tuple[list[dict], int]:
    fields: list[dict] = []
    current: dict[str, Any] | None = None
    i = start
    while i < len(lines):
        lineno, line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not line.startswith(" "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            if current is not None:
                fields.append(current)
            current = {}
            rest = stripped[2:]
            if rest:
                key, value = _split_key_value(rest, lineno)
                current[key] = _parse_scalar(value)
        else:
            if current is None:
                raise ConfigError("field property found before field item", line=lineno)
            key, value = _split_key_value(stripped, lineno)
            current[key] = _parse_scalar(value)
        i += 1
    if current is not None:
        fields.append(current)
    return fields, i


def _strip_comment(line: str) -> str:
    in_quote = False
    quote = ""
    for idx, ch in enumerate(line):
        if ch in {"'", '"'}:
            if not in_quote:
                in_quote = True
                quote = ch
            elif quote == ch:
                in_quote = False
        elif ch == "#" and not in_quote:
            return line[:idx].rstrip()
    return line.rstrip()


def _split_key_value(line: str, lineno: int) -> tuple[str, str]:
    if ":" not in line:
        raise ConfigError("expected key: value", line=lineno)
    key, value = line.split(":", 1)
    key = key.strip()
    if not key:
        raise ConfigError("empty YAML key", line=lineno)
    return key, value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value
