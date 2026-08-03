#!/usr/bin/env python3
"""Keep request/response examples aligned with the canonical action names."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

NEW = {
    ("requests", "list.load.basic.json"): {
        "api_version": "xdebug.v1", "action": "list.load",
        "target": {"session_id": "case_a"},
        "args": {"config": {"lists": [{"name": "ctrl_context", "signals": ["top.u.clk", "top.u.valid", "top.u.ready"]}]}, "mode": "replace"},
    },
    ("requests", "list.load.file.json"): {
        "api_version": "xdebug.v1", "action": "list.load",
        "target": {"session_id": "case_a"},
        "args": {"config_path": "xdebug/configs/debug-lists.json", "mode": "append"},
    },
    ("responses", "list.load.basic.json"): {
        "api_version": "xdebug.v1", "ok": True, "action": "list.load",
        "summary": {"loaded": 1, "mode": "replace"},
        "data": {"lists": ["ctrl_context"], "validation": [{"name": "ctrl_context", "status": "ok", "signals": [{"signal": "top.u.clk", "status": "ok"}]}]},
    },
    ("responses", "list.load.file.json"): {
        "api_version": "xdebug.v1", "ok": True, "action": "list.load",
        "summary": {"loaded": 1, "mode": "append"},
        "data": {"lists": ["ctrl_context"], "validation": [{"name": "ctrl_context", "status": "ok", "signals": [{"signal": "top.u.clk", "status": "ok"}]}]},
    },
    ("requests", "stream.config.get.basic.json"): {
        "api_version": "xdebug.v1", "action": "stream.config.get",
        "target": {"session_id": "wave0"}, "args": {"name": "req_stream"},
    },
    ("responses", "stream.config.get.basic.json"): {
        "api_version": "xdebug.v1", "ok": True, "action": "stream.config.get",
        "summary": {"name": "req_stream"},
        "data": {"stream": {"name": "req_stream", "signals": {"clk": "top.clk", "vld": "top.req_vld", "rdy": "top.req_rdy"}, "clock": "clk", "edge": "posedge", "sample_point": "before", "vld": "vld", "rdy": "rdy"}},
    },
}


def expected_files() -> dict[Path, Any]:
    out: dict[Path, Any] = {}
    for (kind, name), value in NEW.items():
        out[ROOT / "examples" / kind / name] = value
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    errors = []
    for path, value in expected_files().items():
        text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
        if path.exists() and path.read_text() == text:
            continue
        if args.check:
            errors.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(text, encoding="utf-8")
    for item in errors:
        print(f"ERROR: {item}: sample is not synced")
    if errors:
        return 1
    print("JSON samples are synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
