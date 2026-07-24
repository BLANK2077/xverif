#!/usr/bin/env python3
"""Generate strict response schemas for APB/AXI statistics actions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from sync_axi_response_schemas import (
    BOOL,
    STRING,
    UINT,
    array,
    closed,
    error_schema,
    session_schema,
    tool_schema,
)
from sync_value_response_schemas import inject as inject_value_contract


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "v1" / "actions"
SPEC_PATH = ROOT / "specs" / "actions" / "actions.yaml"
ACTIONS = ("apb.statistics", "axi.statistics")


def descriptions() -> dict[str, tuple[str, str]]:
    entries = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["actions"]
    return {
        entry["name"]: (entry["description_en"], entry["description_zh"])
        for entry in entries
        if entry["name"] in ACTIONS
    }


def shapes(allow_ids: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = closed({
        "name": STRING,
        "scanned_transaction_count": UINT,
        "matched_transaction_count": UINT,
        "matched_read_count": UINT,
        "matched_write_count": UINT,
        "unresolved_transaction_count": UINT,
        "filter_applied": BOOL,
        "analysis_complete": BOOL,
        "analysis_quality": {"enum": ["complete", "ambiguous"]},
        "full_scan_count": UINT,
    }, [
        "name", "scanned_transaction_count", "matched_transaction_count",
        "matched_read_count", "matched_write_count",
        "unresolved_transaction_count", "filter_applied",
        "analysis_complete", "analysis_quality", "full_scan_count",
    ])
    address = closed({
        "mode": {"enum": ["exact", "range", "mask"]},
        "values": array(STRING), "begin": STRING, "end": STRING,
        "value": STRING, "mask": STRING,
    }, ["mode"])
    filter_properties: dict[str, Any] = {
        "direction": {"enum": ["all", "read", "write"]},
        "address": address,
    }
    if allow_ids:
        filter_properties["ids"] = array(STRING)
    normalized_filter = closed(filter_properties, ["direction"])
    notes = closed({"unresolved_transaction_count": STRING},
                   ["unresolved_transaction_count"])
    return summary, closed({"filter": normalized_filter, "notes": notes},
                           ["filter", "notes"])


def envelope(action: str, description: tuple[str, str]) -> dict[str, Any]:
    summary, data = shapes(allow_ids=action.startswith("axi."))
    error_summary = closed(
        {"status": {"const": "error"}, "error_code": STRING},
        ["status", "error_code"],
    )
    return inject_value_contract({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"xdebug.{action}.response.v1",
        "title": f"{action} response",
        "description": description[0],
        "x-description-zh": description[1],
        "x-output_notes": "返回该 action 的 summary/data/error/meta；具体字段以 response schema 和 response example 为准。",
        "type": "object",
        "required": ["api_version", "ok", "action", "summary", "data"],
        "properties": {
            "api_version": {"const": "xdebug.v1"},
            "request_id": STRING,
            "ok": BOOL,
            "action": {"const": action},
            "tool": tool_schema(),
            "session": {"oneOf": [session_schema(), {"type": "null"}]},
            "schema_version": STRING,
            "text": STRING,
            "summary": {"oneOf": [summary, error_summary]},
            "data": {"oneOf": [data, {"type": "null"}]},
            "error": {"oneOf": [error_schema(), {"type": "null"}]},
            "meta": closed({"truncated": BOOL}),
        },
        "additionalProperties": False,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    action_descriptions = descriptions()
    stale: list[str] = []
    for action in ACTIONS:
        path = SCHEMA_DIR / f"{action}.response.schema.json"
        rendered = json.dumps(
            envelope(action, action_descriptions[action]),
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(rendered, encoding="utf-8")
    if stale:
        print("protocol statistics response schema drift:")
        for item in stale:
            print(f"  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
