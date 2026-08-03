from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import EntryConfig, normalize_config
from .contracts import validate_response
from .errors import FragmentError
from .fragments import Fragment, normalize_fragments


@dataclass(frozen=True)
class EntryBitSource:
    seq: int
    fragment_bit: int
    metadata: dict


def decode_entry(config_data: dict, fragment_data: list[dict]) -> dict:
    config, warnings = normalize_config(config_data)
    fragments = normalize_fragments(fragment_data, config)
    entry_bits, bit_sources = build_entry_bits(config, fragments)
    fields = {}
    for field in config.fields:
        value_bits = entry_bits[field.lsb : field.msb + 1]
        fields[field.name] = {
            "bits": field.bits,
            "msb": field.msb,
            "lsb": field.lsb,
            "width": field.width,
            "raw_hex": bits_to_hex(value_bits),
            "raw_bin": bits_to_bin(value_bits),
            "source": provenance_for_field(field.lsb, field.msb, bit_sources),
        }
        if field.description is not None:
            fields[field.name]["description"] = field.description
    payload = {
        "ok": True,
        "api_version": "xentry.v1",
        "action": "decode",
        "schema": config.schema_result(),
        "total_bits": config.total_bits,
        "entry_raw": bits_to_hex(entry_bits),
        "fields": fields,
        "warnings": warnings,
    }
    validate_response(payload, expected_action="decode")
    return payload


def validate_entry(config_data: dict, fragment_data: list[dict] | None = None) -> dict:
    config, warnings = normalize_config(config_data)
    if fragment_data is not None:
        fragments = normalize_fragments(fragment_data, config)
        build_entry_bits(config, fragments)
    payload = {
        "ok": True,
        "api_version": "xentry.v1",
        "action": "validate",
        "schema": config.schema_result(),
        "total_bits": config.total_bits,
        "warnings": warnings,
    }
    validate_response(payload, expected_action="validate")
    return payload


def explain_config(config_data: dict) -> dict:
    config, warnings = normalize_config(config_data)
    fields = [
        {
            "name": field.name,
            "bits": field.bits,
            "msb": field.msb,
            "lsb": field.lsb,
            "width": field.width,
            **({"description": field.description} if field.description is not None else {}),
        }
        for field in config.fields
    ]
    payload = {
        "ok": True,
        "api_version": "xentry.v1",
        "action": "explain",
        "schema": config.schema_result(),
        "total_bits": config.total_bits,
        "fragment_byte_order": config.fragment_byte_order,
        "bit_numbering": config.bit_numbering,
        "fields": fields,
        "warnings": warnings,
    }
    validate_response(payload, expected_action="explain")
    return payload


def build_entry_bits(config: EntryConfig, fragments: list[Fragment]) -> tuple[list[int], list[EntryBitSource]]:
    entry_bits: list[int] = []
    sources: list[EntryBitSource] = []
    for fragment in fragments:
        for offset in range(fragment.valid_width):
            fragment_bit = fragment.valid_lsb + offset
            entry_bits.append(fragment.bits[fragment_bit])
            sources.append(EntryBitSource(fragment.seq, fragment_bit, fragment.metadata))
    if len(entry_bits) != config.total_bits:
        raise FragmentError("total valid bits must equal config.total_bits", total_valid_bits=len(entry_bits), total_bits=config.total_bits)
    return entry_bits, sources


def provenance_for_field(lsb: int, msb: int, sources: list[EntryBitSource]) -> list[dict]:
    segments: list[dict] = []
    start_entry = lsb
    prev_entry = lsb - 1
    prev_source: EntryBitSource | None = None
    for entry_bit in range(lsb, msb + 1):
        source = sources[entry_bit]
        contiguous = (
            prev_source is not None
            and source.seq == prev_source.seq
            and source.metadata == prev_source.metadata
            and source.fragment_bit == prev_source.fragment_bit + 1
            and entry_bit == prev_entry + 1
        )
        if prev_source is not None and not contiguous:
            segments.append(_source_segment(start_entry, prev_entry, sources[start_entry], sources[prev_entry]))
            start_entry = entry_bit
        prev_entry = entry_bit
        prev_source = source
    if prev_source is not None:
        segments.append(_source_segment(start_entry, prev_entry, sources[start_entry], sources[prev_entry]))
    return segments


def _source_segment(entry_start: int, entry_end: int, first: EntryBitSource, last: EntryBitSource) -> dict:
    item: dict[str, Any] = {
        "seq": first.seq,
        "entry_bits": range_text(entry_end, entry_start),
        "fragment_bits": range_text(last.fragment_bit, first.fragment_bit),
    }
    item.update(first.metadata)
    return item


def range_text(msb: int, lsb: int) -> str:
    return f"[{msb}:{lsb}]" if msb != lsb else f"[{lsb}:{lsb}]"


def bits_to_int(bits: list[int]) -> int:
    value = 0
    for idx, bit in enumerate(bits):
        if bit:
            value |= 1 << idx
    return value


def bits_to_hex(bits: list[int]) -> str:
    width = max(1, (len(bits) + 3) // 4)
    return "0x" + format(bits_to_int(bits), f"0{width}x")


def bits_to_bin(bits: list[int]) -> str:
    return "".join("1" if bits[idx] else "0" for idx in range(len(bits) - 1, -1, -1)) or "0"
