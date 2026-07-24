#!/usr/bin/env python3
"""Generate strict response schemas for every public AXI action."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from sync_value_response_schemas import inject as inject_value_contract


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "v1" / "actions"
SPEC_PATH = ROOT / "specs" / "actions" / "actions.yaml"

AXI_ACTIONS = (
    "axi.analysis",
    "axi.channel_stall",
    "axi.config.list",
    "axi.config.load",
    "axi.cursor",
    "axi.export",
    "axi.latency_outlier",
    "axi.outstanding_timeline",
    "axi.query",
    "axi.request_response_pair",
)
AXI_VALUE_ACTIONS = {
    "axi.analysis",
    "axi.cursor",
    "axi.export",
    "axi.latency_outlier",
    "axi.query",
    "axi.request_response_pair",
}

PURPOSES = {
    "axi.analysis": "汇总 AXI 行为。",
    "axi.channel_stall": "实验性 AXI stall 分析。",
    "axi.config.list": "列出 AXI 配置。",
    "axi.config.load": "加载 AXI 配置。",
    "axi.cursor": "在 AXI transfer 间移动游标。",
    "axi.export": "导出 AXI 数据。",
    "axi.latency_outlier": "实验性 AXI latency 异常。",
    "axi.outstanding_timeline": "实验性 AXI outstanding 时间线。",
    "axi.query": "查询 AXI channel/transaction。",
    "axi.request_response_pair": "实验性 AXI 请求响应配对。",
}


def action_descriptions() -> dict[str, tuple[str, str]]:
    entries = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["actions"]
    return {
        entry["name"]: (entry["description_en"], entry["description_zh"])
        for entry in entries
        if entry["name"] in AXI_ACTIONS
    }


DESCRIPTIONS = action_descriptions()


def closed(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        out["required"] = required
    return out


def array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


STRING = {"type": "string"}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}
UINT = {"type": "integer", "minimum": 0}
NUMBER = {"type": "number"}
TIME = {"type": "string", "description": "规范化时间字符串。"}
NULLABLE_TIME = {"type": ["string", "null"], "description": "规范化时间字符串；无样本时为 null。"}
NULLABLE_UINT = {"type": ["integer", "null"], "minimum": 0}
NULLABLE_STRING = {"type": ["string", "null"]}
VALUE = {"oneOf": [{"type": "integer"}, {"type": "string"}]}


def stats() -> dict[str, Any]:
    return closed(
        {
            "samples": UINT,
            "status": STRING,
            "min": NULLABLE_TIME,
            "avg": NULLABLE_TIME,
            "max": NULLABLE_TIME,
            "p50": NULLABLE_TIME,
            "p95": NULLABLE_TIME,
            "p99": NULLABLE_TIME,
        }
    )


def beat() -> dict[str, Any]:
    return closed(
        {
            "index": {"type": "integer", "minimum": 1},
            "handshake_time": TIME,
            "data": VALUE,
            "last": BOOL,
            "wstrb": VALUE,
            "resp": VALUE,
        },
        ["index", "handshake_time", "data", "last"],
    )


def transaction() -> dict[str, Any]:
    address = closed(
        {
            "channel": {"enum": ["aw", "ar"]},
            "valid_begin_time": TIME,
            "handshake_time": TIME,
            "addr": VALUE,
            "id": VALUE,
            "len": VALUE,
            "size": VALUE,
            "burst": VALUE,
        },
        ["channel", "handshake_time", "addr", "id", "len", "size", "burst"],
    )
    data = closed(
        {
            "channel": {"enum": ["w", "r"]},
            "valid_begin_time": TIME,
            "first_handshake_time": TIME,
            "last_handshake_time": TIME,
            "beat_count": UINT,
            "expected_beat_count": UINT,
            "beats": array(beat()),
        },
        ["channel", "first_handshake_time", "last_handshake_time", "beat_count", "expected_beat_count"],
    )
    response = closed(
        {
            "channel": {"enum": ["b", "r"]},
            "handshake_time": TIME,
            "resp": VALUE,
        },
        ["channel", "handshake_time", "resp"],
    )
    return closed(
        {
            "direction": {"enum": ["write", "read"]},
            "latency": TIME,
            "phase_order": STRING,
            "response_dependency_violation": BOOL,
            "match_time": TIME,
            "address": address,
            "data": data,
            "response": response,
        },
        ["direction", "latency", "response_dependency_violation", "address", "response"],
    )


def pending_transaction() -> dict[str, Any]:
    return closed(
        {
            "direction": {"enum": ["write", "read"]},
            "id": VALUE,
            "addr": VALUE,
            "len": VALUE,
            "request_time": TIME,
            "age": TIME,
            "observed_beat_count": UINT,
            "expected_beat_count": UINT,
            "data_complete": BOOL,
            "phase_order": STRING,
        },
        ["direction", "id", "addr", "len", "request_time", "age", "observed_beat_count", "expected_beat_count", "data_complete"],
    )


def signal_map(*fields: str) -> dict[str, Any]:
    return closed({field: STRING for field in fields}, list(fields))


def config() -> dict[str, Any]:
    channels = closed({
        "aw": signal_map("addr", "id", "len", "size", "burst", "valid", "ready"),
        "w": signal_map("data", "strb", "last", "valid", "ready"),
        "b": signal_map("id", "resp", "valid", "ready"),
        "ar": signal_map("addr", "id", "len", "size", "burst", "valid", "ready"),
        "r": signal_map("id", "data", "resp", "last", "valid", "ready"),
    }, ["aw", "w", "b", "ar", "r"])
    return closed(
        {
            "name": STRING,
            "sampling_mode": STRING,
            "clock": STRING,
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "reset": closed({
                "signal": STRING,
                "polarity": {"enum": ["active_low", "active_high"]},
            }, ["signal", "polarity"]),
            "sample_point": STRING,
            "channels": channels,
        },
        ["name", "clock", "edge"],
    )


def common_summary(extra: dict[str, Any]) -> dict[str, Any]:
    props = {
        "name": STRING,
        "sampling_mode": STRING,
        "clock": STRING,
        "edge": STRING,
        "sample_point": STRING,
        "sample_time_semantics": STRING,
        "sample_count": UINT,
        "full_scan_count": UINT,
        "analysis_complete": BOOL,
        "truncated": BOOL,
        "truncation_scope": NULLABLE_STRING,
        "requested_range": closed({"begin": TIME, "end": TIME}),
        "scanned_range": closed({"begin": TIME, "end": TIME}),
    }
    props.update(extra)
    return closed(props)


def analysis_shapes() -> tuple[dict[str, Any], dict[str, Any]]:
    summary = common_summary({
        "analysis": {"enum": ["latency", "osd", "pending"]},
        "direction": {"enum": ["read", "write", "all"]},
        "status": STRING,
        "completed_read_count": UINT, "completed_write_count": UINT,
        "incomplete_read_count": UINT, "incomplete_write_count": UINT,
        "buffered_w_beat_count": UINT, "buffered_w_burst_count": UINT,
        "orphan_w_beat_count": UINT, "orphan_b_count": UINT,
        "orphan_r_beat_count": UINT, "response_dependency_violation_count": UINT,
        "channel_handshakes": closed({key: UINT for key in ("aw", "w", "b", "ar", "r")}),
        "min": {"type": ["string", "number", "null"]},
        "avg": {"type": ["string", "number", "null"]},
        "max": {"type": ["string", "number", "null"]},
        "p50": NULLABLE_TIME, "p95": NULLABLE_TIME, "p99": NULLABLE_TIME, "samples": UINT,
        "pending_count": UINT, "returned_pending_count": UINT,
    })
    latency = closed({
        "read": stats(), "write": stats(),
        "definitions": closed({"write": STRING, "read": STRING}),
        "write_phase_order_counts": closed({
            "aw_before_w": UINT, "same_cycle": UINT, "w_before_aw": UINT, "unknown": UINT,
        }),
    })
    osd_stat = closed({"min": NUMBER, "avg": NUMBER, "max": NUMBER, "samples": UINT, "status": STRING})
    osd = closed({
        "read": osd_stat, "write": osd_stat,
        "final_read": UINT, "final_write": UINT,
        "definitions": closed({"read": STRING, "write": STRING}),
    })
    data = closed({
        "latency": latency,
        "osd": osd,
        "slowest": transaction(),
        "pending_transactions": array(pending_transaction()),
    })
    return summary, data


def action_shapes(action: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if action == "axi.analysis":
        return analysis_shapes()
    if action == "axi.query":
        summary = closed({
            "name": STRING, "direction": {"enum": ["read", "write", "all"]},
            "query_mode": {"enum": ["handshake"]}, "found": BOOL, "count": UINT,
        }, ["name"])
        match = closed({
            "channel": {"enum": ["aw", "w", "b", "ar", "r"]},
            "handshake_time": TIME,
            "direction": {"enum": ["read", "write"]},
            "beat_index": {"type": "integer", "minimum": 1},
        }, ["channel", "handshake_time"])
        return summary, closed({"match": match, "transaction": transaction(), "transactions": array(transaction())})
    if action == "axi.cursor":
        return closed({
            "name": STRING, "op": STRING, "direction": {"enum": ["read", "write", "all"]},
            "found": BOOL, "index": NULLABLE_UINT, "index_base": UINT, "total_count": UINT,
            "at_begin": BOOL, "at_end": BOOL,
        }, ["name", "op", "direction", "found"]), closed({"transaction": transaction()})
    if action in {"axi.request_response_pair", "axi.latency_outlier"}:
        summary = closed({"name": STRING, "transaction_count": UINT, "begin": TIME, "end": TIME}, ["name"])
        if action == "axi.latency_outlier":
            return summary, closed({
                "method": STRING, "classification": STRING,
                "candidate_count": UINT, "matched_outlier_count": UINT, "outlier_count": UINT,
                "top_n": UINT, "threshold": TIME, "truncated": BOOL, "truncation_scope": STRING,
                "outliers": array(transaction()),
            })
        diagnostics = closed({
            "analysis_complete": BOOL, "full_scan_count": UINT,
            "incomplete_write_count": UINT, "incomplete_read_count": UINT,
            "buffered_w_beat_count": UINT, "buffered_w_burst_count": UINT,
            "orphan_w_beat_count": UINT, "orphan_b_count": UINT,
            "orphan_r_beat_count": UINT, "response_dependency_violation_count": UINT,
        })
        return summary, closed({
            "matched_transaction_count": UINT, "returned_transaction_count": UINT,
            "pairing_rule": closed({"write_data": STRING, "write_response": STRING, "read_response": STRING}),
            "diagnostics": diagnostics, "transactions": array(transaction()),
            "truncated": BOOL, "truncation_scope": NULLABLE_STRING,
        })
    if action == "axi.channel_stall":
        summary = common_summary({
            "channel": {"enum": ["aw", "w", "b", "ar", "r"]},
            "transfer_count": UINT, "max_stall_cycles": UINT,
            "ready_without_valid_cycles": UINT, "finding_count": UINT,
            "returned_finding_count": UINT, "first_activity_time": NULLABLE_TIME,
        })
        finding = closed({
            "type": STRING, "severity": STRING, "begin": TIME, "end": TIME,
            "cycles": UINT, "open_at_window_end": BOOL,
        }, ["type", "begin", "end", "cycles"])
        return summary, closed({"findings": array(finding)})
    if action == "axi.outstanding_timeline":
        summary = common_summary({
            "change_point_count": UINT, "returned": UINT, "returned_change_point_count": UINT,
            "peak_read": UINT, "peak_write": UINT,
            "peak_read_time": NULLABLE_TIME, "peak_write_time": NULLABLE_TIME,
            "first_nonzero_time": NULLABLE_TIME,
            "final_read": NULLABLE_UINT, "final_write": NULLABLE_UINT,
        })
        point = closed({
            "time": TIME, "read": UINT, "write": UINT,
            "read_delta": INT, "write_delta": INT,
            "read_event": STRING, "write_event": STRING,
        }, ["time"])
        return summary, closed({"change_points": array(point)})
    if action == "axi.config.list":
        return closed({"count": UINT, "name": STRING, "status": STRING}), closed(
            {"configs": array(config()), "config": config()}
        )
    if action == "axi.config.load":
        signal = closed({
            "field": STRING, "requested_path": STRING, "resolved_path": STRING,
            "width": UINT, "status": STRING,
        }, ["field", "requested_path", "resolved_path", "width", "status"])
        validation = closed({
            "status": STRING,
            "clock": closed({"status": STRING, "edge": STRING, "first_edge": UINT}),
            "signals": array(signal),
        }, ["status", "clock", "signals"])
        return closed({"name": STRING, "status": STRING}, ["name", "status"]), closed(
            {"config": config(), "validation": validation}, ["config", "validation"]
        )
    if action == "axi.export":
        summary = common_summary({
            "write_count": UINT, "read_count": UINT, "total_count": UINT, "row_count": UINT,
            "format": STRING, "status": STRING, "output_written": BOOL,
            "incomplete_write_count": UINT, "incomplete_read_count": UINT,
            "buffered_w_beat_count": UINT, "buffered_w_burst_count": UINT,
            "orphan_w_beat_count": UINT, "orphan_b_count": UINT,
            "orphan_r_beat_count": UINT, "response_dependency_violation_count": UINT,
            "output": closed({
                "path": STRING, "write_path": STRING, "read_path": STRING,
                "meta_path": STRING, "file_format": STRING,
            }),
        })
        row = closed({
            "seq": UINT, "direction": {"enum": ["read", "write"]},
            "completion_time": TIME, "addr_time": TIME, "first_data_time": TIME,
            "last_data_time": TIME, "latency": TIME, "phase_order": STRING,
            "response_dependency_violation": BOOL, "id": VALUE, "addr": VALUE,
            "len": VALUE, "size": VALUE, "burst": VALUE, "resp": VALUE,
            "beat_count": UINT, "expected_beat_count": UINT,
        })
        preview = closed({"writes": array(row), "reads": array(row)}, ["writes", "reads"])
        return summary, closed({"preview": preview})
    raise AssertionError(action)


def tool_schema() -> dict[str, Any]:
    return closed({
        "name": STRING, "version": STRING, "build_id": STRING,
        "git_revision": STRING, "schema_revision": STRING,
    }, ["name", "version", "build_id", "git_revision", "schema_revision"])


def session_schema() -> dict[str, Any]:
    string_fields = (
        "id", "session_id", "mode", "daidir", "dbdir", "dbdir_path",
        "design_file", "fsdb", "fsdb_file", "socket_path", "transport",
        "file_dir", "host", "bind_host", "server_host",
    )
    integer_fields = (
        "pid", "port", "server_pid", "created_at", "last_active",
        "dbdir_mtime", "dbdir_size", "dbdir_dev", "dbdir_inode",
        "fsdb_mtime", "fsdb_size", "fsdb_dev", "fsdb_inode",
    )
    props = {name: STRING for name in string_fields}
    props.update({name: INT for name in integer_fields})
    props["healthy"] = BOOL
    return closed(props)


def error_schema() -> dict[str, Any]:
    return closed(
        {
            "code": STRING,
            "message": STRING,
            "recoverable": BOOL,
            "error_layer": STRING,
            "invalid_arg": STRING,
            "expected": STRING,
            "received": {},
            "received_type": STRING,
            "allowed_values": {},
            "available_values": {},
            "did_you_mean": {},
            "schema_path": STRING,
            "required_any_of": {},
            "missing_name": STRING,
            "missing_resource": STRING,
            "next_actions": {},
            "example_note": STRING,
            "correct_example": {},
            "cause_code": STRING,
            "validation": {},
            "current_estimated_bytes": {"type": "integer", "minimum": 0},
            "hard_max_bytes": {"type": "integer", "minimum": 0},
            "protocol": {"type": "string", "enum": ["apb", "axi", "stream"]},
            "key_summary": STRING,
            "suggestions": {"type": "array", "items": STRING},
        },
        ["code", "message", "recoverable", "error_layer"],
    )


def envelope(action: str) -> dict[str, Any]:
    summary, data = action_shapes(action)
    error_summary = closed({"status": {"const": "error"}, "error_code": STRING}, ["status", "error_code"])
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"xdebug.{action}.response.v1",
        "title": f"{action} response",
        "description": DESCRIPTIONS[action][0],
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
        "x-description-zh": DESCRIPTIONS[action][1],
    }
    return inject_value_contract(schema) if action in AXI_VALUE_ACTIONS else schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale: list[str] = []
    for action in AXI_ACTIONS:
        path = SCHEMA_DIR / f"{action}.response.schema.json"
        rendered = json.dumps(envelope(action), indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != rendered:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(rendered)
    if stale:
        print("AXI response schema drift:")
        for item in stale:
            print(f"  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
