from __future__ import annotations

import re

from .bitvector import BitVector
from .errors import ParseError, ValueError2State

_BASED_RE = re.compile(
    r"^(?P<neg>-)?(?P<size>\d+)?'(?P<signed>[sS])?(?P<base>[bBoOdDhH])(?P<digits>[+-]?[0-9a-fA-F_xXzZ?]+)$"
)
_DEC_RE = re.compile(r"^[+-]?\d[\d_]*$")


def _digits_width(base: str, digits: str) -> int:
    clean = digits.replace("_", "").lstrip("+-")
    if base == "b":
        return len(clean) or 1
    if base == "o":
        return max(1, len(clean) * 3)
    if base == "h":
        return max(1, len(clean) * 4)
    return max(32, int(clean or "0").bit_length() or 1)


def _parse_based_digits(base: str, digits: str, width: int, state: str) -> tuple[int, int, int, bool]:
    clean = digits.replace("_", "")
    negative = clean.startswith("-")
    if clean[:1] in "+-":
        clean = clean[1:]
    if any(ch in clean.lower() for ch in "xz?"):
        if state != "4state":
            raise ValueError2State("literal contains x/z/? bits; pass --state 4 to preserve them", literal=digits)
        value = 0
        x_mask = 0
        z_mask = 0
        bit = 0
        per_digit = {"b": 1, "o": 3, "h": 4}[base]
        for ch in reversed(clean.lower()):
            if ch == "?":
                ch = "x"
            if ch == "x":
                x_mask |= ((1 << per_digit) - 1) << bit
            elif ch == "z":
                z_mask |= ((1 << per_digit) - 1) << bit
            else:
                value |= int(ch, {"b": 2, "o": 8, "h": 16}[base]) << bit
            bit += per_digit
        mask = (1 << width) - 1
        return value & mask, x_mask & mask, z_mask & mask, negative
    if base == "d":
        value = int(clean or "0", 10)
    else:
        value = int(clean or "0", {"b": 2, "o": 8, "h": 16}[base])
    if negative:
        value = -value
    return value, 0, 0, negative


def parse_value(text: str | int | bool | BitVector, *, state: str = "2state", default_signed: bool = False) -> BitVector:
    if isinstance(text, BitVector):
        return text
    if isinstance(text, bool):
        return BitVector.bool(text)
    if isinstance(text, int):
        return BitVector.from_int(text, signed=default_signed)
    raw = str(text).strip()
    if not raw:
        raise ParseError("empty value")
    based = _BASED_RE.match(raw)
    if based:
        base = based.group("base").lower()
        digits = based.group("digits")
        size_text = based.group("size")
        width = int(size_text) if size_text else _digits_width(base, digits)
        signed = bool(based.group("signed")) or default_signed
        value, x_mask, z_mask, digit_negative = _parse_based_digits(base, digits, width, state)
        if based.group("neg"):
            value = -value
            signed = True
        if digit_negative:
            signed = True
        return BitVector(width, value, signed=signed, state=state, x_mask=x_mask, z_mask=z_mask)
    if _DEC_RE.match(raw):
        value = int(raw.replace("_", ""), 10)
        # An unsized decimal integer literal is signed in SystemVerilog.
        signed = True
        return BitVector.from_int(value, signed=signed)
    raise ParseError("unsupported value literal", literal=raw)
