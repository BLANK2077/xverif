from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .config import EntryConfig
from .errors import FragmentError


HEX_RE = re.compile(r"^(?:0x)?[0-9a-fA-F_ ]+$")
META_KEYS = ("entry_id", "time", "source", "line", "tag")
REQUIRED_FRAGMENT_KEYS = ("seq", "data", "valid_lsb", "valid_width")
ALLOWED_FRAGMENT_KEYS = set(REQUIRED_FRAGMENT_KEYS) | set(META_KEYS)


@dataclass(frozen=True)
class Fragment:
    seq: int
    data: str
    bytes_value: bytes
    bits: list[int]
    valid_lsb: int
    valid_width: int
    metadata: dict


def load_fragments_file(path: str) -> list[dict]:
    out: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FragmentError("invalid JSONL fragment", line=lineno, message=str(exc)) from exc
            if not isinstance(obj, dict):
                raise FragmentError("JSONL fragment must be an object", line=lineno)
            out.append(obj)
    return out


def normalize_fragments(raw_fragments: list[dict], config: EntryConfig) -> list[Fragment]:
    if not isinstance(raw_fragments, list) or not raw_fragments:
        raise FragmentError("fragments must be a non-empty list")
    seen: set[int] = set()
    fragments: list[Fragment] = []
    for raw in raw_fragments:
        if not isinstance(raw, dict):
            raise FragmentError("each fragment must be an object")
        unknown = sorted(set(raw) - ALLOWED_FRAGMENT_KEYS)
        if unknown:
            raise FragmentError("fragment contains unsupported fields", field=unknown[0])
        for key in REQUIRED_FRAGMENT_KEYS:
            if key not in raw:
                raise FragmentError("fragment missing required field", field=key)
        seq = _int(raw["seq"], "seq")
        if seq < 0:
            raise FragmentError("seq must be non-negative", seq=seq)
        if seq in seen:
            raise FragmentError("duplicate fragment seq", seq=seq)
        seen.add(seq)
        data = raw["data"]
        if not isinstance(data, str):
            raise FragmentError("data must be a string")
        bytes_value = parse_hex_bytes(data)
        bits = bytes_to_bits(bytes_value, config.fragment_byte_order, config.bit_numbering)
        valid_lsb = _int(raw["valid_lsb"], "valid_lsb")
        valid_width = _int(raw["valid_width"], "valid_width")
        if valid_lsb < 0:
            raise FragmentError("valid_lsb must be non-negative", seq=seq, valid_lsb=valid_lsb)
        if valid_width <= 0:
            raise FragmentError("valid_width must be positive", seq=seq, valid_width=valid_width)
        if valid_lsb + valid_width > len(bits):
            raise FragmentError(
                "valid bit range exceeds fragment width",
                seq=seq,
                valid_lsb=valid_lsb,
                valid_width=valid_width,
                fragment_width=len(bits),
            )
        metadata = {key: raw[key] for key in META_KEYS if key in raw}
        fragments.append(Fragment(seq, data, bytes_value, bits, valid_lsb, valid_width, metadata))
    return sorted(fragments, key=lambda item: item.seq)


def parse_hex_bytes(text: str) -> bytes:
    compact = text.strip()
    if compact.startswith(("0x", "0X")):
        compact = compact[2:]
    compact = compact.replace("_", "").replace(" ", "")
    if not compact:
        raise FragmentError("data must not be empty")
    if not re.fullmatch(r"[0-9a-fA-F]+", compact):
        raise FragmentError("data must be hex bytes", data=text)
    if len(compact) % 2:
        raise FragmentError("data hex digit count must be even", data=text)
    return bytes.fromhex(compact)


def bytes_to_bits(data: bytes, byte_order: str, bit_numbering: str) -> list[int]:
    width = len(data) * 8
    bits = [0] * width
    for idx, byte in enumerate(data):
        byte_offset = idx * 8 if byte_order == "lsb_first" else (len(data) - 1 - idx) * 8
        for logical_bit in range(8):
            physical_bit = logical_bit if bit_numbering == "byte_lsb0" else 7 - logical_bit
            bits[byte_offset + logical_bit] = (byte >> physical_bit) & 1
    return bits


def _int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FragmentError(f"{field} must be an integer")
    return value
