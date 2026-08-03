#!/usr/bin/env python3
"""Sync strict runtime request schemas for xdebug actions."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from sync_action_schema_hints import PARAM_DESCRIPTIONS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "specs"))
from action_contracts import apply_argument_contract, complete_descriptions, reset_schema


XDEBUG_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = XDEBUG_ROOT / "specs" / "actions" / "actions.yaml"
REQUEST_EXAMPLES = XDEBUG_ROOT / "examples" / "requests"

RENAMED_FROM = {
    "apb.transaction.cursor": "apb.cursor",
    "axi.transaction.cursor": "axi.cursor",
    "waveform.cursor.delete": "cursor.delete",
    "waveform.cursor.get": "cursor.get",
    "waveform.cursor.list": "cursor.list",
    "waveform.cursor.set": "cursor.set",
    "waveform.cursor.use": "cursor.use",
    "signal.anomaly.inspect": "detect_abnormal",
    "protocol.handshake.inspect": "handshake.inspect",
    "list.first_change": "list.diff",
    "nwave.rc.generate": "rc.generate",
    "signal.sampled_pulse.inspect": "sampled_pulse.inspect",
    "stream.describe": "stream.show",
    "trace.x_origin": "trace.x",
    "list.load": "list.create",
    "stream.config.get": "stream.config.list",
}


ADDITIONAL_ARG_SCHEMAS: dict[str, dict[str, Any]] = {
    "action": {"type": "string"},
    "analysis": {"type": "string", "enum": ["latency", "osd", "pending"]},
    "apb": {"type": "string", "minLength": 1},
    "address": {"type": "string"},
    "addr": {"type": "string"},
    "aggregate": {"type": "object"},
    "aggregate_only": {"type": "boolean"},
    "auth_token": {"type": "string"},
    "bind": {"type": "string"},
    "bind_host": {"type": "string"},
    "cache_scope": {"type": "string", "enum": ["full", "range"], "default": "full"},
    "channel": {"type": "string"},
    "config": {"type": "object"},
    "context_lines": {"type": "integer"},
    "data": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
    "dependency_types": {"type": "array", "items": {"type": "string"}},
    "dynamic": {"type": "boolean"},
    "edge": {"type": "string", "enum": ["posedge", "negedge", "dual"]},
    "expected_state": {
        "type": "string",
        "enum": ["x", "z"],
        "description": PARAM_DESCRIPTIONS["expected_state"],
    },
    "events": {"type": "boolean"},
    "group_by": {"type": "array"},
    "host": {"type": "string"},
    "include_alias_candidates": {"type": "boolean"},
    "include_compat_fields": {"type": "boolean"},
    "include_control": {"type": "boolean"},
    "include_parity": {"type": "boolean"},
    "include_preview": {"type": "boolean"},
    "include_statement_only": {"type": "boolean"},
    "include_patterns": {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    },
    "id": {"type": "string"},
    "last": {"type": "boolean"},
    "level": {"type": "integer", "minimum": 0, "default": 0},
    "line_limit": {"type": "integer", "minimum": 1},
    "list": {"type": "string", "minLength": 1},
    "method": {"type": "string", "enum": ["top_n", "threshold"]},
    "match_mode": {
        "type": "string",
        "enum": ["exact", "contains"],
        "default": "exact",
        "description": PARAM_DESCRIPTIONS["match_mode"],
    },
    "limits": {"type": "object"},
    "protocol_query": {
        "type": "object",
        "properties": {
            "line_limit": {"type": "integer", "minimum": 1},
            "index": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
        "description": "Protocol query controls; use 1-based query.index and query.line_limit; legacy quantity fields are rejected.",
    },
    "max_depth": {"type": "integer"},
    "max_edges": {"type": "integer"},
    "max_events": {"type": "integer", "minimum": 1},
    "max_rows": {"type": "integer"},
    "max_samples": {"type": "integer", "minimum": 1},
    "name_pattern": {"type": "string"},
    "exclude_patterns": {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    },
    "no_statement_only": {"type": "boolean"},
    "note": {"type": "string"},
    "origin": {"type": "string"},
    "output": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "file_format": {"type": "string"},
            "verbose": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "payload": {"type": "string"},
    "packet_index": {"type": "integer"},
    "path": {"type": "string"},
    "role": {"type": "string"},
    "rules": {"oneOf": [{"type": "array"}, {"type": "object"}]},
    "reset": reset_schema(),
    "sample_point": {"type": "string", "enum": ["before", "after"]},
    "signal": {"type": "string", "minLength": 1},
    "slice_hint": {"type": "object"},
    "source": {"type": "string"},
    "symbol": {"type": "string"},
    "time_range": {
        "type": "object",
        "properties": {
            "begin": {"type": "string"},
            "end": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "time_unit": {"type": "string", "enum": ["auto", "fs", "ps", "ns", "us", "ms", "s"]},
    "threshold": {"type": "string"},
    "time": {"type": "string", "minLength": 1},
    "times": {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    },
    "top_n": {"type": "integer", "minimum": 1},
    "transport": {"type": "string", "enum": ["uds", "tcp", "file"]},
    "axi": {"type": "string", "minLength": 1},
    "stream": {"type": "string", "minLength": 1},
    "verbose": {"type": "boolean"},
    "value_format": {
        "type": "string",
        "enum": ["hex", "bin", "dec"],
        "description": "仅控制响应中信号值的显示格式；不影响采样、时间或导出文件格式。",
    },
}


EXTRA_ARGS_BY_ACTION: dict[str, set[str]] = {
    "actions": {"filter", "output"},
    "apb.transaction.cursor": {"direction"},
    "apb.config.list": {"name"},
    "apb.config.load": {"config", "config_path"},
    "apb.query": {"direction", "address", "addr", "query", "last"},
    "apb.statistics": {"filter"},
    "apb.transfer_window": {"line_limit", "time_range"},
    "axi.analysis": {"analysis", "direction", "line_limit"},
    "axi.channel_stall": {"channel", "line_limit", "rules", "time_range"},
    "axi.config.list": {"name"},
    "axi.config.load": {"config", "config_path"},
    "axi.transaction.cursor": {"direction"},
    "axi.export": {"output", "time_range"},
    "axi.latency_outlier": {"direction", "line_limit", "method", "output", "threshold", "time_range", "top_n"},
    "axi.outstanding_timeline": {"direction", "line_limit", "time_range"},
    "axi.query": {"direction", "address", "addr", "id", "query", "last", "output"},
    "axi.request_response_pair": {"direction", "line_limit", "time_range", "output"},
    "axi.statistics": {"filter"},
    "batch": {"mode"},
    "counter.statistics": {"edge", "line_limit", "max_samples", "sample_point"},
    "signal.anomaly.inspect": {"line_limit", "time_range", "value_format"},
    "event.config.list": {"line_limit", "name"},
    "event.config.load": {"config_path"},
    "event.export": {
        "aggregate",
        "edge",
        "line_limit",
        "max_events",
        "max_samples",
        "mode",
        "name",
        "output",
        "reset",
        "sample_point",
        "time_range",
    },
    "event.find": {
        "edge",
        "line_limit",
        "max_samples",
        "mode",
        "name",
        "reset",
        "sample_point",
        "time_range",
    },
    "expr.eval_at": {"edge", "sample_point", "time_range"},
    "expr.normalize": {"line_limit", "no_statement_only", "role", "signal"},
    "protocol.handshake.inspect": {"data", "edge", "line_limit", "rules", "sample_point", "time_range"},
    "list.delete": {"index"},
    "list.first_change": {"value_format"},
    "list.load": {"config", "config_path", "mode"},
    "list.export": {"line_limit", "output", "time_range"},
    "list.show": {"name"},
    "signal.sampled_pulse.inspect": {
        "edge",
        "line_limit",
        "payload",
        "payloads",
        "rules",
        "sample_point",
        "time_range",
    },
    "scope.list": {"exclude_patterns", "include_patterns", "kind", "level", "path"},
    "session.close": set(),
    "session.doctor": set(),
    "session.gc": set(),
    "session.kill": set(),
    "session.list": set(),
    "session.open": {"bind", "bind_host", "host", "port", "session_id", "transport"},
    "signal.changes": {"aggregate_only", "line_limit", "mode", "time_range", "value_format"},
    "signal.stability": {"conditions", "mode", "signals", "time_range"},
    "signal.statistics": {"clock", "conditions", "edge", "line_limit", "max_samples", "mode", "sample_point", "signals", "time_range"},
    "signal.xz_verify": {"match_mode"},
    "stream.config.load": {"config", "config_path", "file", "mode"},
    "stream.config.list": {"name", "output"},
    "stream.config.get": set(),
    "stream.export": {"cache_scope", "channel", "line_limit", "output", "time_range"},
    "stream.query": {"cache_scope", "channel", "filter", "line_limit", "packet_index", "time_range"},
    "stream.describe": set(),
    "stream.validate": {"cache_scope", "channel", "line_limit", "time_range"},
    "trace.active_driver": {
        "limits",
    },
    "trace.active_driver_chain": set(),
    "trace.x_origin": {"value_format"},
    "trace.driver": {"line_limit", "no_statement_only", "role"},
    "trace.load": {"line_limit", "no_statement_only", "role"},
    "value.at": {
        "signal", "list", "apb", "stream", "axi",
        "time", "times", "clock", "edge", "sample_point",
        "slice_hint", "value_format",
    },
    "verify.conditions": {"edge", "sample_point", "signals", "value_format"},
    "window.verify": {"edge", "line_limit", "max_samples", "sample_point", "signals", "time_range"},
}

# Every action that can publish sampled or derived logic values exposes the
# same display-only selector.  Keep this list centralized so protocol, stream,
# event and waveform actions cannot drift independently.
VALUE_BEARING_ACTIONS = {
    "apb.transaction.cursor",
    "apb.query",
    "apb.statistics",
    "apb.transfer_window",
    "axi.analysis",
    "axi.transaction.cursor",
    "axi.export",
    "axi.latency_outlier",
    "axi.query",
    "axi.request_response_pair",
    "axi.statistics",
    "counter.statistics",
    "signal.anomaly.inspect",
    "event.export",
    "event.find",
    "expr.eval_at",
    "protocol.handshake.inspect",
    "list.first_change",
    "signal.sampled_pulse.inspect",
    "signal.changes",
    "signal.stability",
    "signal.statistics",
    "signal.xz_verify",
    "stream.export",
    "stream.query",
    "trace.x_origin",
    "value.at",
    "verify.conditions",
    "window.verify",
}
for _action in VALUE_BEARING_ACTIONS:
    EXTRA_ARGS_BY_ACTION[_action].add("value_format")


ENGINE_FORWARD_TIME_UNIT_EXCLUDE = {
    "actions",
    "batch",
    "schema",
    "session.close",
    "session.gc",
    "session.kill",
    "session.list",
    "session.open",
}


ARGS_REQUIRED_EXCEPTIONS = {
    "session.close",
    "session.kill",
}


TOP_LEVEL_PROPERTIES: dict[str, dict[str, Any]] = {
    "api_version": {"type": "string", "enum": ["xdebug.v1"]},
    "request_id": {"type": "string"},
    "id": {"type": "string"},
    "trace_id": {"type": "string"},
    "span_id": {"type": "string"},
    "parent_span_id": {"type": "string"},
    "action": {"type": "string"},
    "target": {"type": "object"},
    "args": {"type": "object"},
    "limits": {"type": "object"},
    "auth_token": {"type": "string"},
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def action_specs() -> list[dict[str, Any]]:
    return load_json(SPEC_PATH)["actions"]


def required_related_args(spec: dict[str, Any]) -> set[str]:
    keys = set(spec.get("required_args", []))
    for group in spec.get("required_arg_groups", []):
        keys.update(group)
    for conditional in spec.get("conditional_required_args", []):
        keys.update(conditional.get("when", {}).keys())
        keys.update(conditional.get("required", []))
    return keys


def example_args(action: str) -> set[str]:
    path = REQUEST_EXAMPLES / f"{action}.basic.json"
    if not path.exists():
        return set()
    data = load_json(path)
    args = data.get("args", {})
    return set(args) if isinstance(args, dict) else set()


def collect_arg_schemas(specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    arg_schemas: dict[str, dict[str, Any]] = {}
    for spec in specs:
        for kind in ("request",):
            path = XDEBUG_ROOT / spec["schemas"][kind]
            if not path.exists() and spec["name"] in RENAMED_FROM:
                path = path.with_name(
                    RENAMED_FROM[spec["name"]] + ".request.schema.json")
            if not path.exists():
                continue
            schema = load_json(path)
            props = schema.get("properties", {}).get("args", {}).get("properties", {})
            if isinstance(props, dict):
                for key, value in props.items():
                    if not isinstance(value, dict):
                        continue
                    if key not in arg_schemas:
                        arg_schemas[key] = copy.deepcopy(value)
    for key, value in ADDITIONAL_ARG_SCHEMAS.items():
        arg_schemas.setdefault(key, copy.deepcopy(value))
    # Keep generic channel open for stream/APB-style uses; action-specific
    # channel enums are applied in sync_schema().
    arg_schemas["channel"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["channel"])
    arg_schemas["output"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["output"])
    arg_schemas["time_range"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["time_range"])

    arg_schemas["checks"] = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": ["unknown_xz", "glitch", "stuck"]},
                "min_pulse_width": {"type": "string"},
                "min_duration": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "description": "detect_abnormal checks. Each item must be an object with type; string shorthand is not supported.",
    }
    arg_schemas["direction"] = {"type": "string", "enum": ["write", "read", "all"]}
    arg_schemas["format"] = {
        "type": "string",
        "enum": [
            "h",
            "hex",
            "b",
            "bin",
            "binary",
            "d",
            "dec",
            "decimal",
            "array_indexed",
            "json",
            "tsv",
            "csv",
            "u64bin",
        ],
    }
    arg_schemas["kind"] = {
        "type": "string", "enum": ["request", "response"], "default": "request",
        "description": "schema action 要返回的 JSON Schema 类别：request 或 response。",
    }
    string_filter = lambda values: {
        "type": "array", "minItems": 1, "uniqueItems": True,
        "items": {"type": "string", "enum": values},
    }
    arg_schemas["filter"] = {
        "type": "object",
        "properties": {
            "category": string_filter(["builtin", "design", "waveform", "combined", "session"]),
            "requires": string_filter(["none", "design", "waveform", "combined", "any", "session"]),
            "purposes": string_filter(["discover", "configure", "query", "inspect", "analyze", "trace", "verify", "export", "manage", "transform", "orchestrate"]),
            "keyword": {"type": "string", "pattern": ".*\\S.*"},
        },
        "additionalProperties": False,
    }
    arg_schemas["mode"] = {"type": "string"}
    arg_schemas["op"] = {"type": "string", "enum": ["begin", "next", "prev", "pre", "last"]}
    arg_schemas["port"] = {"type": "integer"}
    arg_schemas["query"] = {"oneOf": [{"type": "string"}, {"type": "object"}]}
    arg_schemas["vld"] = {"oneOf": [{"type": "string"}, {"type": "object"}]}
    return arg_schemas


def allowed_args_for_spec(spec: dict[str, Any]) -> set[str]:
    action = spec["name"]
    keys = set(example_args(action))
    keys.update(required_related_args(spec))
    keys.update(EXTRA_ARGS_BY_ACTION.get(action, set()))
    if spec.get("handler_kind") == "engine_forward" and action not in ENGINE_FORWARD_TIME_UNIT_EXCLUDE:
        keys.add("time_unit")
    return keys


def protocol_config_schema(required_signals: list[str], description: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for signal in required_signals:
        properties[signal] = {"type": "string", "minLength": 1}
        if signal == "clock" and "paddr" in required_signals:
            properties["edge"] = {"type": "string", "enum": ["posedge", "negedge", "dual"]}
            properties["sample_point"] = {"type": "string", "enum": ["before", "after"]}
    if "edge" not in properties:
        properties["edge"] = {"type": "string", "enum": ["posedge", "negedge", "dual"]}
        properties["sample_point"] = {"type": "string", "enum": ["before", "after"]}
    properties["reset"] = reset_schema()
    return {
        "type": "object",
        "description": description,
        "properties": properties,
        "required": required_signals + ["reset"],
        "additionalProperties": False,
    }


def protocol_statistics_filter_schema(allow_ids: bool) -> dict[str, Any]:
    literal = {
        "type": "string",
        "minLength": 1,
        "description": "Known integer, hexadecimal, or SystemVerilog literal up to 64 bits.",
        "x-description-zh": "不含 X/Z、宽度不超过 64 bit 的整数、十六进制或 SystemVerilog literal。",
    }
    exact = {
        "type": "object",
        "required": ["mode", "values"],
        "properties": {
            "mode": {"const": "exact"},
            "values": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": copy.deepcopy(literal),
            },
        },
        "additionalProperties": False,
    }
    range_filter = {
        "type": "object",
        "required": ["mode", "begin", "end"],
        "properties": {
            "mode": {"const": "range"},
            "begin": copy.deepcopy(literal),
            "end": copy.deepcopy(literal),
        },
        "additionalProperties": False,
    }
    mask = {
        "type": "object",
        "required": ["mode", "value", "mask"],
        "properties": {
            "mode": {"const": "mask"},
            "value": copy.deepcopy(literal),
            "mask": copy.deepcopy(literal),
        },
        "additionalProperties": False,
    }
    properties: dict[str, Any] = {
        "direction": {
            "type": "string", "enum": ["all", "read", "write"], "default": "all",
            "description": "Transaction direction filter.",
            "x-description-zh": "事务方向过滤；默认 all。",
        },
        "address": {
            "oneOf": [exact, range_filter, mask],
            "description": "Exactly one address filtering mode: exact queue, inclusive range, or value/mask.",
            "x-description-zh": "地址只能选择精确值队列、闭区间或 value/mask 三种模式之一。",
        },
    }
    if allow_ids:
        properties["ids"] = {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": copy.deepcopy(literal),
            "description": "AXI transaction ID queue; values are ORed within the queue.",
            "x-description-zh": "AXI ID 队列，队列内部取 OR。",
        }
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
        "description": "Completed-transaction filters; direction, IDs, and address are combined with AND.",
        "x-description-zh": "已完成事务过滤；方向、ID 和地址三类条件取 AND。",
    }


def stream_query_filter_schema() -> dict[str, Any]:
    literal = {
        "type": "string",
        "minLength": 1,
        "description": "Known unsigned integer or SystemVerilog literal of arbitrary width; X/Z and 0x are rejected.",
        "x-description-zh": "任意位宽的已知无符号整数或 SystemVerilog literal；不允许 X/Z 和 0x。",
    }
    exact = {
        "type": "object",
        "required": ["mode", "values"],
        "properties": {
            "mode": {"const": "exact"},
            "values": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": copy.deepcopy(literal),
            },
        },
        "additionalProperties": False,
    }
    range_filter = {
        "type": "object",
        "required": ["mode", "begin", "end"],
        "properties": {
            "mode": {"const": "range"},
            "begin": copy.deepcopy(literal),
            "end": copy.deepcopy(literal),
        },
        "additionalProperties": False,
    }
    mask = {
        "type": "object",
        "required": ["mode", "value", "mask"],
        "properties": {
            "mode": {"const": "mask"},
            "value": copy.deepcopy(literal),
            "mask": copy.deepcopy(literal),
        },
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "required": ["fields"],
        "properties": {
            "position": {"type": "string", "enum": ["sop", "eop"]},
            "fields": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"oneOf": [exact, range_filter, mask]},
            },
        },
        "additionalProperties": False,
        "description": "AND-combined Stream field filters; each field selects exact queue, inclusive range, or value/mask.",
        "x-description-zh": "Stream 字段间取 AND；每个字段只能选择精确值队列、闭区间或 value/mask。packet stream 必须指定 SOP/EOP position。",
    }


def sync_schema(schema: dict[str, Any], spec: dict[str, Any], arg_schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    action = spec["name"]
    updated = copy.deepcopy(schema)
    updated["type"] = "object"
    updated["required"] = ["api_version", "action"]
    if spec.get("required_args") and action not in ARGS_REQUIRED_EXCEPTIONS:
        updated["required"].append("args")

    properties = updated.setdefault("properties", {})
    for key in list(properties):
        if key not in TOP_LEVEL_PROPERTIES:
            del properties[key]
    for key, value in TOP_LEVEL_PROPERTIES.items():
        properties.setdefault(key, copy.deepcopy(value))
    properties["action"] = {"type": "string", "enum": [action]}
    if spec.get("required_target"):
        updated["required"].append("target")
        target_properties = {
            "session_id": {"type": "string", "description": PARAM_DESCRIPTIONS["session_id"]},
        }
        # engine_forward requests are enriched by Dispatcher::resolve_target()
        # before the already-open session receives and validates them.  Keep
        # that internal routed form inside the same strict schema contract.
        if spec.get("handler_kind") == "engine_forward":
            target_properties.update({
                "daidir": {"type": "string"},
                "fsdb": {"type": "string"},
                "mode": {"type": "string", "enum": ["design", "waveform", "combined"]},
            })
        properties["target"] = {
            "type": "object",
            "required": list(spec["required_target"]),
            "properties": target_properties,
            "additionalProperties": False,
        }
    else:
        properties.setdefault("target", copy.deepcopy(TOP_LEVEL_PROPERTIES["target"]))

    args = properties.setdefault("args", {"type": "object"})
    args["type"] = "object"
    args["required"] = list(spec.get("required_args", []))
    selected_props: dict[str, Any] = {}
    for key in sorted(allowed_args_for_spec(spec)):
        if key not in arg_schemas:
            raise ValueError(f"{action}: missing schema template for args.{key}")
        selected_props[key] = apply_argument_contract(action, key, arg_schemas[key])
        if key in PARAM_DESCRIPTIONS:
            selected_props[key].setdefault("description", PARAM_DESCRIPTIONS[key])
    if action == "value.at":
        selected_props.pop("format", None)
    if action in ("apb.query", "axi.query") and "query" in selected_props:
        selected_props["query"] = copy.deepcopy(arg_schemas["protocol_query"])
        if action == "axi.query" and "direction" in selected_props:
            selected_props["direction"] = {"type": "string", "enum": ["write", "read"]}
    if action in ("apb.statistics", "axi.statistics"):
        selected_props["filter"] = protocol_statistics_filter_schema(
            allow_ids=action == "axi.statistics"
        )
    if action == "stream.query":
        selected_props["filter"] = stream_query_filter_schema()
    if action == "axi.analysis" and "analysis" in selected_props:
        selected_props["analysis"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["analysis"])
    if action == "apb.config.load" and "config" in selected_props:
        selected_props["config"] = protocol_config_schema(
            [
                "clock", "paddr", "psel", "penable", "pready",
                "pslverr", "pwrite", "pwdata", "prdata",
            ],
            PARAM_DESCRIPTIONS["config"],
        )
    if action == "axi.config.load" and "config" in selected_props:
        selected_props["config"] = protocol_config_schema(
            [
                "clock",
                "awvalid", "awready", "awaddr", "awid", "awlen", "awsize", "awburst",
                "wvalid", "wready", "wdata", "wstrb", "wlast",
                "bvalid", "bready", "bid", "bresp",
                "arvalid", "arready", "araddr", "arid", "arlen", "arsize", "arburst",
                "rvalid", "rready", "rdata", "rid", "rresp", "rlast",
            ],
            PARAM_DESCRIPTIONS["config"],
        )
    if action == "stream.config.load":
        field_map = {
            "type": "object", "additionalProperties": {"type": "string"},
        }
        stream_item = {
            "type": "object",
            "required": ["name", "signals", "clock", "vld"],
            "properties": {
                "name": {"type": "string"},
                "signals": {"type": "object", "minProperties": 1,
                            "additionalProperties": {"type": "string", "minLength": 1}},
                "clock": {"type": "string"},
                "edge": {"type": "string", "enum": ["posedge", "negedge", "dual"]},
                "sample_point": {"type": "string", "enum": ["before", "after"]},
                "reset": reset_schema(), "vld": {"type": "string"},
                "rdy": {"type": "string"}, "bp": {"type": "string"},
                "sop": {"type": "string"}, "eop": {"type": "string"},
                "data": {"type": "string"},
                "beat_fields": copy.deepcopy(field_map),
                "packet_stable_fields": copy.deepcopy(field_map),
                "channel_id": {"type": "string"},
                "channel_id_valid": {"type": "string", "enum": ["sop", "eop", "every_beat"]},
                "allow_interleaving": {"type": "boolean"},
                "description": {"type": "string"},
            },
            "additionalProperties": False,
        }
        streams = {
            "type": "array", "minItems": 1, "items": stream_item,
            "description": PARAM_DESCRIPTIONS["streams"],
        }
        selected_props["streams"] = copy.deepcopy(streams)
        selected_props["config"] = {
            "type": "object", "required": ["streams"],
            "properties": {"streams": copy.deepcopy(streams)},
            "additionalProperties": False,
            "description": PARAM_DESCRIPTIONS["config"],
        }
        selected_props["mode"] = {"type": "string", "enum": ["replace", "append"]}
    if action == "axi.query" and "query" in selected_props:
        selected_props["query"] = {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "line_limit": {"type": "integer", "minimum": 1},
                        "index": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": ["channel", "handshake_time"],
                    "properties": {
                        "channel": {"type": "string", "enum": ["aw", "w", "b", "ar", "r"]},
                        "handshake_time": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            ],
            "description": "Select transactions by 1-based index/line_limit, or exactly match an AXI channel handshake time.",
        }
    if action in {"axi.query", "axi.request_response_pair", "axi.latency_outlier"} and "output" in selected_props:
        selected_props["output"] = {
            "type": "object",
            "properties": {
                "include_data": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
            "description": "AXI payload display controls; beat data is omitted unless include_data is true.",
        }
    if action == "list.export" and "format" in selected_props:
        selected_props["format"] = {
            "type": "string",
            "enum": ["u64bin"],
            "description": "list.export input format. The response manifest uses versioned format u64bin.v1.",
        }
    if action == "list.export" and "output" in selected_props:
        selected_props["output"]["properties"]["file_format"] = {
            "type": "string",
            "enum": ["u64bin"],
            "description": "list.export file format; response manifest uses versioned format u64bin.v1.",
        }
    if action == "axi.export" and "output" in selected_props:
        selected_props["output"]["properties"]["file_format"] = {
            "type": "string",
            "enum": ["tsv", "csv"],
            "description": "axi.export file format.",
        }
    if action == "event.export" and "output" in selected_props:
        selected_props["output"]["properties"]["file_format"] = {
            "type": "string",
            "enum": ["json"],
            "description": "event.export file format.",
        }
    if action == "stream.export":
        if "output" in selected_props:
            selected_props["output"]["properties"]["file_format"] = {
                "type": "string",
                "enum": ["tsv", "csv", "xout"],
                "description": "stream.export file format.",
            }
        if "kind" in selected_props:
            selected_props["kind"] = {
                "type": "string",
                "enum": ["transfer", "packet", "packet_beats"],
                "description": "导出或查询的结果类型。",
            }
    if action in VALUE_BEARING_ACTIONS and "value_format" in selected_props:
        selected_props["value_format"]["default"] = "hex"
    if action == "trace.active_driver_chain":
        properties["limits"] = {
            "type": "object",
            "description": "Resource limits for the recursive active trace.",
            "properties": {
                "max_depth": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 8,
                    "description": "Maximum recursion depth through pass-through assignments and aliases.",
                },
                "max_nodes": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 50,
                    "description": "Maximum number of trace nodes before truncation.",
                },
                "max_trace_signals": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 64,
                    "description": "Maximum signal count for ambiguity evidence lookup.",
                },
            },
            "additionalProperties": False,
        }
    if action == "trace.x_origin":
        properties["limits"] = {
            "type": "object",
            "properties": {
                "max_depth": {"type": "integer", "minimum": 1, "default": 8},
                "max_nodes": {"type": "integer", "minimum": 1, "default": 50},
                "max_time_steps": {"type": "integer", "minimum": 1, "default": 128},
                "max_trace_signals": {"type": "integer", "minimum": 1, "default": 64},
                "max_chains": {"type": "integer", "minimum": 1, "default": 8},
            },
            "additionalProperties": False,
        }
    if action in {"verify.conditions", "window.verify"} and "conditions" in selected_props:
        selected_props["conditions"] = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["expr"],
                "properties": {
                    "expr": {
                        "type": "string",
                        "description": "Expression using aliases from args.signals.",
                    },
                    "name": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["always", "eventually", "never"],
                    },
                },
                "additionalProperties": False,
            },
            "description": PARAM_DESCRIPTIONS["conditions"],
        }
    if action == "axi.channel_stall" and "channel" in selected_props:
        selected_props["channel"] = {
            "type": "string",
            "enum": ["aw", "w", "b", "ar", "r"],
            "description": "AXI channel to inspect.",
        }
    if action == "scope.list":
        selected_props["kind"] = {
            "type": "string",
            "enum": ["all", "module", "port", "signal"],
            "default": "all",
            "description": "只返回 module、port、signal，或三者都返回。",
        }
    if action == "protocol.handshake.inspect":
        selected_props["rules"] = {
            "type": "object",
            "properties": {
                "max_wait_cycles": {"type": "integer", "minimum": 0},
                "check_data_stable_when_stalled": {"type": "boolean"},
                "require_valid_hold_until_handshake": {"type": "boolean", "default": True},
                "ready_without_valid": {
                    "type": "string",
                    "enum": ["summary", "intervals", "all"],
                    "default": "summary",
                },
            },
            "additionalProperties": False,
        }
    if action == "signal.sampled_pulse.inspect":
        selected_props["rules"] = {
            "type": "object",
            "properties": {
                "payload_changed_without_sampled_valid": {
                    "type": "string",
                    "enum": ["off", "summary", "all"],
                    "default": "summary",
                }
            },
            "additionalProperties": False,
        }
    if action == "event.find":
        selected_props["mode"] = {
            "type": "string",
            "enum": ["first", "last", "all"],
            "default": "first",
        }
    if action == "event.export":
        selected_props["mode"] = {"type": "string", "enum": ["export"], "default": "export"}
    for key, value in list(selected_props.items()):
        selected_props[key] = complete_descriptions(
            apply_argument_contract(action, key, value), f"args.{key}"
        )
    args["properties"] = selected_props
    args["additionalProperties"] = False
    groups = spec.get("required_arg_groups", [])
    if groups:
        args["anyOf"] = [{"required": list(group)} for group in groups]
    else:
        args.pop("anyOf", None)
    conditionals = spec.get("conditional_required_args", [])
    if conditionals:
        args["allOf"] = [
            {
                "if": {"properties": {key: {"const": value} for key, value in conditional.get("when", {}).items()}},
                "then": {"required": list(conditional.get("required", []))},
            }
            for conditional in conditionals
        ]
    else:
        args.pop("allOf", None)
    if action == "value.at":
        selectors = ("signal", "list", "apb", "stream", "axi")
        selector_variants = []
        for selector in selectors:
            selector_variants.append({
                "required": [selector],
                "not": {
                    "anyOf": [
                        {"required": [other]}
                        for other in selectors
                        if other != selector
                    ]
                },
            })
        args.pop("oneOf", None)
        args["allOf"] = [
            {
                "description": (
                    "Select exactly one value source: a direct signal or a "
                    "loaded list, APB, stream, or AXI configuration."
                ),
                "oneOf": selector_variants,
            },
            {
                "description": (
                    "Select exactly one time form: time for one point or "
                    "times for one or more ordered unique points."
                ),
                "oneOf": [
                    {"required": ["time"], "not": {"required": ["times"]}},
                    {"required": ["times"], "not": {"required": ["time"]}},
                ],
            },
            {
                "if": {"required": ["slice_hint"]},
                "then": {"required": ["signal"]},
            },
        ]
        args["allOf"].append({
            "if": {"not": {"required": ["clock"]}},
            "then": {
                "not": {
                    "anyOf": [
                        {"required": ["edge"]},
                        {"required": ["sample_point"]},
                    ]
                }
            },
        })
    if action == "axi.query":
        query_constraints = [
            {
                "if": {
                    "required": ["query"],
                    "properties": {"query": {"required": ["channel"]}},
                },
                "then": {
                    "not": {
                        "anyOf": [
                            {"required": [key]}
                            for key in ("direction", "address", "addr", "id", "last")
                        ]
                    }
                },
            },
            {"not": {"required": ["address", "addr"]}},
        ]
        args["allOf"] = list(args.get("allOf", [])) + query_constraints
    if action == "event.find":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "anyOf": [
                    {"required": ["mode"], "properties": {"mode": {"const": "all"}}},
                    {"not": {"required": ["line_limit"]}},
                ]
            },
            {"not": {"anyOf": [
                {"required": ["name", "clock"]}, {"required": ["name", "signals"]},
                {"required": ["name", "edge"]}, {"required": ["name", "sample_point"]},
                {"required": ["name", "reset"]},
            ]}},
        ]
    if action == "event.export":
        args["allOf"] = list(args.get("allOf", [])) + [{"not": {"anyOf": [
            {"required": ["name", "clock"]}, {"required": ["name", "signals"]},
            {"required": ["name", "edge"]}, {"required": ["name", "sample_point"]},
            {"required": ["name", "reset"]},
        ]}}]
    if action == "event.config.list":
        args["allOf"] = list(args.get("allOf", [])) + [
            {"not": {"required": ["name", "line_limit"]}}
        ]
    if action == "expr.normalize":
        args["allOf"] = list(args.get("allOf", [])) + [
            {"anyOf": [{"required": ["signal"]}, {"not": {"required": ["line_limit"]}}]}
        ]
    if action in {"list.export", "stream.export"}:
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "required": ["output"],
                    "properties": {
                        "output": {
                            "required": ["path"],
                            "properties": {"path": {"type": "string", "minLength": 1}},
                        }
                    },
                },
                "then": {"not": {"required": ["line_limit"]}},
            }
        ]
    if action == "stream.validate":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "required": ["dynamic"],
                    "properties": {"dynamic": {"const": False}},
                },
                "then": {"not": {"required": ["cache_scope"]}},
            }
        ]
    if action == "axi.analysis":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "anyOf": [
                    {"required": ["analysis"], "properties": {"analysis": {"const": "pending"}}},
                    {"not": {"required": ["line_limit"]}},
                ]
            }
        ]
    updated.pop("anyOf", None)
    updated.pop("allOf", None)
    updated.pop("oneOf", None)
    updated["additionalProperties"] = False
    return updated


def value_at_schema_is_unified(schema: dict[str, Any]) -> bool:
    args = schema.get("properties", {}).get("args", {})
    properties = args.get("properties", {})
    required_properties = {
        "signal", "list", "apb", "stream", "axi",
        "time", "times", "clock", "edge", "sample_point",
        "slice_hint", "value_format",
    }
    if not required_properties.issubset(properties):
        return False
    if properties["times"].get("uniqueItems") is not True:
        return False
    if properties["times"].get("minItems") != 1:
        return False
    all_of = args.get("allOf", [])
    return isinstance(all_of, list) and len(all_of) >= 4


def scope_list_schema_is_hierarchical(schema: dict[str, Any]) -> bool:
    properties = schema.get("properties", {}).get(
        "args", {}).get("properties", {})
    required = {
        "path", "level", "kind", "include_patterns", "exclude_patterns",
    }
    if not required.issubset(properties):
        return False
    return properties["kind"].get("enum") == [
        "all", "module", "port", "signal",
    ]


def scope_roots_schema_has_source_selection(schema: dict[str, Any]) -> bool:
    properties = schema.get("properties", {}).get(
        "args", {}).get("properties", {})
    source = properties.get("source", {})
    return (source.get("enum") == ["auto", "wave", "design"] and
            source.get("default") == "auto")


def sync(check: bool, selected_actions: set[str] | None = None) -> list[str]:
    specs = [spec for spec in action_specs() if spec.get("status") != "removed"]
    arg_schemas = collect_arg_schemas(specs)
    errors: list[str] = []

    for spec in specs:
        if selected_actions and spec["name"] not in selected_actions:
            continue
        path = XDEBUG_ROOT / spec["schemas"]["request"]
        source_path = path
        if not source_path.exists() and spec["name"] in RENAMED_FROM:
            source_path = path.with_name(
                RENAMED_FROM[spec["name"]] + ".request.schema.json")
        if not source_path.exists():
            errors.append(f"{spec['name']}: request schema seed is missing")
            continue
        schema = load_json(source_path)
        if spec["name"] == "value.at" and value_at_schema_is_unified(schema):
            continue
        if (spec["name"] == "scope.list" and
                scope_list_schema_is_hierarchical(schema)):
            continue
        if (spec["name"] == "scope.roots" and
                scope_roots_schema_has_source_selection(schema)):
            continue
        try:
            updated = sync_schema(schema, spec, arg_schemas)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if schema != updated:
            if check:
                errors.append(f"{spec['schemas']['request']}: runtime request schema is not synced")
            else:
                path.write_text(dump_json(updated), encoding="utf-8")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="only check, do not update files")
    parser.add_argument("--action", action="append", default=[], help="sync only the named action; repeatable")
    args = parser.parse_args(argv)

    errors = sync(check=args.check, selected_actions=set(args.action) or None)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("runtime request schemas are synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
    properties["reset"] = reset_schema()
