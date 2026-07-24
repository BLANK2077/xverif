#!/usr/bin/env python3
"""Synchronize the shared value-width summary contract in response schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "v1" / "actions"

VALUE_ACTIONS = {
    "apb.cursor",
    "apb.query",
    "apb.statistics",
    "apb.transfer_window",
    "axi.analysis",
    "axi.cursor",
    "axi.export",
    "axi.latency_outlier",
    "axi.query",
    "axi.request_response_pair",
    "axi.statistics",
    "counter.statistics",
    "detect_abnormal",
    "event.export",
    "event.find",
    "expr.eval_at",
    "handshake.inspect",
    "list.diff",
    "list.value_at",
    "sampled_pulse.inspect",
    "signal.changes",
    "signal.stability",
    "signal.statistics",
    "signal.xz_verify",
    "stream.export",
    "stream.query",
    "trace.x",
    "value.at",
    "value.batch_at",
    "verify.conditions",
    "window.verify",
}


def diagnostic_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "signal": {"type": ["string", "null"]},
            "role": {"type": "string"},
            "reason": {
                "type": "string",
                "enum": [
                    "npi_range_size_unavailable",
                    "conflicting_signal_widths",
                    "derived_width_unavailable",
                ],
            },
        },
        "required": ["signal", "role", "reason"],
        "additionalProperties": False,
    }


def inject(schema: dict) -> dict:
    summary = schema["properties"]["summary"]
    candidates = summary.get("oneOf", [summary])
    success = next(
        item
        for item in candidates
        if item.get("type") == "object"
        and item.get("properties", {}).get("status", {}).get("const") != "error"
    )
    properties = success.setdefault("properties", {})
    properties["value_width_complete"] = {"type": "boolean"}
    properties["width_diagnostics"] = {
        "type": "array",
        "items": diagnostic_schema(),
    }
    return schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale: list[str] = []
    for action in sorted(VALUE_ACTIONS):
        path = SCHEMA_DIR / f"{action}.response.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        rendered = json.dumps(inject(schema), indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if path.read_text(encoding="utf-8") != rendered:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(rendered, encoding="utf-8")
    if stale:
        print("value response schema drift:")
        for item in stale:
            print(f"  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
