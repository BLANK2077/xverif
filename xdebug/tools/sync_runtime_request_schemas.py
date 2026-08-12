#!/usr/bin/env python3
"""Sync strict runtime request schemas for xdebug actions."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

XDEBUG_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = XDEBUG_ROOT / "tools"
SPECS_ROOT = XDEBUG_ROOT / "specs"
for import_root in (TOOLS_ROOT, SPECS_ROOT):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from sync_action_schema_hints import PARAM_DESCRIPTIONS
from action_contracts import (
    actions_filter_schema,
    apply_argument_contract,
    complete_descriptions,
    reset_schema,
)


SPEC_PATH = XDEBUG_ROOT / "specs" / "actions" / "actions.yaml"
REQUEST_EXAMPLES = XDEBUG_ROOT / "examples" / "requests"


ADDITIONAL_ARG_SCHEMAS: dict[str, dict[str, Any]] = {
    "action": {"type": "string"},
    "analysis": {"type": "string", "enum": ["latency", "osd", "pending"]},
    "apb": {"type": "string", "minLength": 1},
    "address": {"type": "string"},
    "aggregate": {"type": "object"},
    "bind_host": {"type": "string", "minLength": 1},
    "cache_scope": {"type": "string", "enum": ["full", "range"], "default": "full"},
    "channel": {"type": "string"},
    "config": {"type": "object"},
    "data": {
        "oneOf": [
            {"type": "string", "minLength": 1},
            {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        ]
    },
    "dynamic": {"type": "boolean"},
    "edge": {"type": "string", "enum": ["posedge", "negedge", "dual"]},
    "expected_state": {
        "type": "string",
        "enum": ["x", "z"],
        "description": PARAM_DESCRIPTIONS["expected_state"],
    },
    "host": {"type": "string", "minLength": 1},
    "id": {"type": "string"},
    "include_patterns": {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    },
    "index": {"type": "integer", "minimum": 1},
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
    "protocol_query": {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "line_limit": {"type": "integer", "minimum": 1},
            "index": {"type": "integer", "minimum": 1},
        },
        "anyOf": [
            {"required": ["line_limit"]},
            {"required": ["index"]},
        ],
        "additionalProperties": False,
        "description": "Protocol query controls; use 1-based query.index and query.line_limit; legacy quantity fields are rejected.",
    },
    "max_events": {"type": "integer", "minimum": 1},
    "max_samples": {"type": "integer", "minimum": 1},
    "exclude_patterns": {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    },
    "no_statement_only": {"type": "boolean"},
    "output": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "file_format": {"type": "string"},
            "verbose": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    "ownership_token": {
        "type": "string",
        "minLength": 64,
        "maxLength": 64,
        "pattern": "^[0-9a-f]{64}$",
        "description": (
            "Opaque 256-bit conditional-cleanup token encoded as exactly 64 "
            "lowercase hexadecimal characters. A managed wrapper may supply it "
            "at session.open and provide it to session.close with "
            "args.mode=force as an optional "
            "match precondition, not as authorization. When session.open omits "
            "it, the frontend binds a fail-closed internally generated token; "
            "never log or publish either form."
        ),
    },
    "packet_index": {"type": "integer"},
    "path": {"type": "string"},
    "role": {"type": "string"},
    "rules": {"oneOf": [{"type": "array"}, {"type": "object"}]},
    "reset": reset_schema(),
    "sample_point": {"type": "string", "enum": ["before", "after"]},
    "signal": {"type": "string", "minLength": 1},
    "slice_hint": {"type": "object"},
    "source": {"type": "string"},
    "time_range": {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "begin": {"type": "string", "minLength": 1},
            "end": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    },
    "times": {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    },
    "render_time_unit": {"type": "string", "enum": ["auto", "ps", "ns", "us"]},
    "threshold": {"type": "string"},
    "time": {"type": "string", "minLength": 1},
    "top_n": {"type": "integer", "minimum": 1},
    "transport": {"type": "string", "enum": ["uds", "tcp", "file"]},
    "axi": {"type": "string", "minLength": 1},
    "stream": {"type": "string", "minLength": 1},
    "value_format": {
        "type": "string",
        "enum": ["hex", "bin", "dec"],
        "description": "仅控制响应中信号值的显示格式；不影响采样、时间或导出文件格式。",
    },
}


class RuntimeConsumerContract(NamedTuple):
    """Named runtime boundary that owns an action's public optional args."""

    consumer_id: str
    optional_args: set[str]


def _runtime_consumer_contract(
    action: str,
    optional_args: set[str] | None = None,
) -> RuntimeConsumerContract:
    return RuntimeConsumerContract(
        consumer_id=(
            f"EngineActionRegistry[action={action}]"
            "::run(ContractBoundRequest)"
        ),
        optional_args=set(optional_args or ()),
    )


def _named_runtime_consumer_contract(
    consumer_id: str,
    optional_args: set[str] | None = None,
) -> RuntimeConsumerContract:
    return RuntimeConsumerContract(
        consumer_id=consumer_id,
        optional_args=set(optional_args or ()),
    )


RUNTIME_CONSUMER_CONTRACTS_BY_ACTION: dict[
    str, RuntimeConsumerContract
] = {
    "actions": _named_runtime_consumer_contract(
        "xdebug::catalog_actions_response(const Json&)",
        {"filter", "output"},
    ),
    "apb.transaction.cursor": _runtime_consumer_contract(
        "apb.transaction.cursor", {"direction"}
    ),
    "apb.config.list": _runtime_consumer_contract("apb.config.list", {"name"}),
    "apb.config.load": _runtime_consumer_contract(
        "apb.config.load", {"config", "config_path"}
    ),
    "apb.export": _runtime_consumer_contract(
        "apb.export", {"direction", "address", "output", "time_range"}
    ),
    "apb.query": _runtime_consumer_contract(
        "apb.query", {"direction", "address", "query", "last"}
    ),
    "apb.statistics": _runtime_consumer_contract(
        "apb.statistics", {"filter"}
    ),
    "apb.transfer_window": _runtime_consumer_contract(
        "apb.transfer_window", {"line_limit", "time_range"}
    ),
    "axi.analysis": _runtime_consumer_contract(
        "axi.analysis", {"analysis", "direction", "line_limit"}
    ),
    "axi.channel_stall": _runtime_consumer_contract(
        "axi.channel_stall", {"channel", "line_limit", "rules", "time_range"}
    ),
    "axi.config.list": _runtime_consumer_contract("axi.config.list", {"name"}),
    "axi.config.load": _runtime_consumer_contract(
        "axi.config.load", {"config", "config_path"}
    ),
    "axi.transaction.cursor": _runtime_consumer_contract(
        "axi.transaction.cursor", {"direction"}
    ),
    "axi.export": _runtime_consumer_contract(
        "axi.export", {"output", "time_range"}
    ),
    "axi.latency_outlier": _runtime_consumer_contract(
        "axi.latency_outlier",
        {"direction", "line_limit", "method", "threshold", "time_range", "top_n"},
    ),
    "axi.outstanding_timeline": _runtime_consumer_contract(
        "axi.outstanding_timeline", {"direction", "line_limit", "time_range"}
    ),
    "axi.query": _runtime_consumer_contract(
        "axi.query",
        {
            "direction", "address", "id", "query", "last", "output",
            "time_range",
        },
    ),
    "axi.request_response_pair": _runtime_consumer_contract(
        "axi.request_response_pair", {"direction", "line_limit", "time_range"}
    ),
    "axi.statistics": _runtime_consumer_contract(
        "axi.statistics", {"filter"}
    ),
    "batch": _named_runtime_consumer_contract(
        "xdebug::Dispatcher::handle_batch(const Json&, const Json&)",
        {"mode"},
    ),
    "counter.statistics": _runtime_consumer_contract(
        "counter.statistics", {"edge", "line_limit", "max_samples", "sample_point"}
    ),
    "signal.anomaly.inspect": _runtime_consumer_contract(
        "signal.anomaly.inspect",
        {"checks", "line_limit", "time_range"},
    ),
    "event.config.list": _runtime_consumer_contract(
        "event.config.list", {"line_limit", "name"}
    ),
    "event.config.load": _runtime_consumer_contract(
        "event.config.load", {"config_path"}
    ),
    "event.export": _runtime_consumer_contract(
        "event.export",
        {
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
    ),
    "event.find": _runtime_consumer_contract(
        "event.find",
        {
            "edge",
            "line_limit",
            "max_samples",
            "mode",
            "name",
            "reset",
            "sample_point",
            "time_range",
        },
    ),
    "expr.eval_at": _runtime_consumer_contract(
        "expr.eval_at", {"edge", "sample_point", "time_range"}
    ),
    "expr.normalize": _runtime_consumer_contract(
        "expr.normalize", {"expr", "line_limit", "no_statement_only", "role", "signal"}
    ),
    "protocol.handshake.inspect": _runtime_consumer_contract(
        "protocol.handshake.inspect",
        {"data", "edge", "line_limit", "rules", "sample_point", "time_range"},
    ),
    "list.add": _runtime_consumer_contract("list.add"),
    "list.create": _runtime_consumer_contract("list.create", {"signals"}),
    "list.load": _runtime_consumer_contract(
        "list.load", {"config", "config_path", "mode"}
    ),
    "list.delete": _runtime_consumer_contract("list.delete", {"index"}),
    "list.first_change": _runtime_consumer_contract(
        "list.first_change"
    ),
    "list.export": _runtime_consumer_contract(
        "list.export", {"line_limit", "output", "time_range"}
    ),
    "list.show": _runtime_consumer_contract("list.show", {"name"}),
    "list.validate": _runtime_consumer_contract("list.validate"),
    "nwave.rc.generate": _runtime_consumer_contract("nwave.rc.generate"),
    "signal.sampled_pulse.inspect": _runtime_consumer_contract(
        "signal.sampled_pulse.inspect",
        {
            "edge",
            "line_limit",
            "payloads",
            "rules",
            "sample_point",
            "time_range",
        },
    ),
    "schema": _named_runtime_consumer_contract(
        "xdebug::catalog_schema_response(const Json&)",
        {"kind"},
    ),
    "scope.list": _runtime_consumer_contract(
        "scope.list",
        {"exclude_patterns", "include_patterns", "kind", "level", "path", "source"},
    ),
    "scope.roots": _runtime_consumer_contract("scope.roots", {"source"}),
    "session.close": _named_runtime_consumer_contract(
        "xdebug/src/engine/engine_query.cpp"
        "::handle_session_action[action=session.close](ContractBoundRequest&)",
        {"mode", "ownership_token"},
    ),
    "session.doctor": _named_runtime_consumer_contract(
        "xdebug/src/engine/engine_query.cpp"
        "::handle_session_action[action=session.doctor](ContractBoundRequest&)"
    ),
    "session.gc": _named_runtime_consumer_contract(
        "xdebug::Dispatcher::handle_session[action=session.gc]"
    ),
    "session.list": _named_runtime_consumer_contract(
        "xdebug::Dispatcher::handle_session[action=session.list]",
        {"output"},
    ),
    "session.open": _named_runtime_consumer_contract(
        "xdebug/src/engine/engine_query.cpp"
        "::handle_session_action[action=session.open](ContractBoundRequest&)",
        {"bind_host", "host", "ownership_token", "port", "transport"},
    ),
    "signal.changes": _runtime_consumer_contract(
        "signal.changes",
        {"line_limit", "mode", "time_range"},
    ),
    "signal.canonicalize": _runtime_consumer_contract("signal.canonicalize"),
    "signal.resolve": _runtime_consumer_contract("signal.resolve"),
    "signal.stability": _runtime_consumer_contract(
        "signal.stability", {"time_range"}
    ),
    "signal.statistics": _runtime_consumer_contract(
        "signal.statistics",
        {
            "clock",
            "edge",
            "line_limit",
            "max_samples",
            "sample_point",
            "time_range",
        },
    ),
    "signal.xz_verify": _runtime_consumer_contract(
        "signal.xz_verify", {"match_mode"}
    ),
    "stream.config.load": _runtime_consumer_contract(
        "stream.config.load", {"config", "config_path", "mode"}
    ),
    "stream.config.list": _runtime_consumer_contract(
        "stream.config.list", {"output"}
    ),
    "stream.config.get": _runtime_consumer_contract("stream.config.get"),
    "stream.export": _runtime_consumer_contract(
        "stream.export",
        {"cache_scope", "channel", "kind", "line_limit", "output", "time_range"},
    ),
    "stream.query": _runtime_consumer_contract(
        "stream.query",
        {"cache_scope", "channel", "filter", "line_limit", "packet_index", "time_range"},
    ),
    "stream.describe": _runtime_consumer_contract("stream.describe"),
    "stream.validate": _runtime_consumer_contract(
        "stream.validate",
        {"cache_scope", "channel", "dynamic", "line_limit", "time_range"},
    ),
    "trace.active_driver": _runtime_consumer_contract("trace.active_driver"),
    "trace.active_driver_chain": _runtime_consumer_contract(
        "trace.active_driver_chain"
    ),
    "trace.x_origin": _runtime_consumer_contract(
        "trace.x_origin"
    ),
    "trace.driver": _runtime_consumer_contract(
        "trace.driver", {"no_statement_only", "role"}
    ),
    "trace.load": _runtime_consumer_contract(
        "trace.load", {"no_statement_only", "role"}
    ),
    "value.at": _runtime_consumer_contract(
        "value.at",
        {
            "signal", "list", "apb", "stream", "axi",
            "time", "times", "clock", "edge", "sample_point",
            "slice_hint",
        },
    ),
    "verify.conditions": _runtime_consumer_contract(
        "verify.conditions", {"edge", "sample_point", "signals"}
    ),
    "waveform.cursor.delete": _runtime_consumer_contract(
        "waveform.cursor.delete"
    ),
    "waveform.cursor.get": _runtime_consumer_contract("waveform.cursor.get"),
    "waveform.cursor.list": _runtime_consumer_contract("waveform.cursor.list"),
    "waveform.cursor.set": _runtime_consumer_contract("waveform.cursor.set"),
    "waveform.cursor.use": _runtime_consumer_contract("waveform.cursor.use"),
    "window.verify": _runtime_consumer_contract(
        "window.verify",
        {"edge", "line_limit", "max_samples", "sample_point", "signals", "time_range"},
    ),
}

OUTPUT_SCHEMAS_BY_ACTION: dict[str, dict[str, Any]] = {
    "actions": {
        "type": "object",
        "properties": {
            "verbose": {
                "type": "boolean",
                "default": False,
                "description": "Return full action descriptors instead of the compact action-name list.",
            },
        },
        "additionalProperties": False,
    },
    "session.list": {
        "type": "object",
        "properties": {
            "verbose": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Return verbose session records instead of the default "
                    "compact representation."
                ),
            },
        },
        "additionalProperties": False,
    },
    "stream.config.list": {
        "type": "object",
        "properties": {
            "verbose": {
                "type": "boolean",
                "default": False,
                "description": "Include each saved configuration object with the name list.",
            },
        },
        "additionalProperties": False,
    },
    "apb.export": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Output path prefix; omit it to return at most eight APB transactions in data.preview.",
            },
            "file_format": {
                "type": "string",
                "enum": ["tsv", "csv"],
                "default": "tsv",
                "description": "APB transaction artifact file format.",
            },
        },
        "allOf": [
            {
                "if": {"required": ["file_format"]},
                "then": {"required": ["path"]},
            }
        ],
        "additionalProperties": False,
    },
    "axi.query": {
        "type": "object",
        "properties": {
            "include_data": {
                "type": "boolean",
                "default": False,
                "description": "Include AXI beat payload data in transaction results.",
            },
        },
        "additionalProperties": False,
    },
    "axi.export": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Output path prefix; omit it to return an in-response preview.",
            },
            "file_format": {
                "type": "string",
                "enum": ["tsv", "csv"],
                "default": "tsv",
                "description": "AXI artifact file format.",
            },
        },
        "allOf": [
            {
                "if": {"required": ["file_format"]},
                "then": {"required": ["path"]},
            }
        ],
        "additionalProperties": False,
    },
    "event.export": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Artifact path; omit it to return an in-response preview.",
            },
            "file_format": {
                "type": "string",
                "enum": ["json"],
                "default": "json",
                "description": "Event artifact file format.",
            },
        },
        "allOf": [
            {
                "if": {"required": ["file_format"]},
                "then": {"required": ["path"]},
            }
        ],
        "additionalProperties": False,
    },
    "list.export": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Artifact directory; omit it to return an in-response preview.",
            },
            "file_format": {
                "type": "string",
                "enum": ["u64bin"],
                "default": "u64bin",
                "description": "Waveform-list artifact format; the manifest publishes u64bin.v1.",
            },
        },
        "allOf": [
            {
                "if": {"required": ["file_format"]},
                "then": {"required": ["path"]},
            }
        ],
        "additionalProperties": False,
    },
    "stream.export": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Artifact path; omit it to return an in-response preview.",
            },
            "file_format": {
                "type": "string",
                "enum": ["tsv", "csv", "xout"],
                "default": "tsv",
                "description": "Stream artifact file format.",
            },
        },
        "allOf": [
            {
                "if": {"required": ["file_format"]},
                "then": {"required": ["path"]},
            }
        ],
        "additionalProperties": False,
    },
    "nwave.rc.generate": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "description": "Required destination path for the generated waveform RC artifact.",
            },
        },
        "additionalProperties": False,
    },
}

# Only actions whose public response can contain canonical time values expose
# the display-only render_time_unit selector. It is not a generic engine knob.
TIME_RENDERING_ACTIONS = {
    "apb.transaction.cursor",
    "apb.export",
    "apb.query",
    "apb.transfer_window",
    "axi.analysis",
    "axi.export",
    "axi.channel_stall",
    "axi.transaction.cursor",
    "axi.latency_outlier",
    "axi.outstanding_timeline",
    "axi.query",
    "axi.request_response_pair",
    "counter.statistics",
    "waveform.cursor.get",
    "waveform.cursor.list",
    "waveform.cursor.set",
    "waveform.cursor.use",
    "signal.anomaly.inspect",
    "event.export",
    "event.find",
    "expr.eval_at",
    "protocol.handshake.inspect",
    "list.first_change",
    "list.export",
    "signal.sampled_pulse.inspect",
    "signal.changes",
    "signal.stability",
    "signal.statistics",
    "signal.xz_verify",
    "trace.active_driver",
    "trace.active_driver_chain",
    "trace.x_origin",
    "nwave.rc.generate",
    "value.at",
    "verify.conditions",
    "window.verify",
    "stream.validate",
    "stream.query",
    "stream.export",
}

# Every action that can publish sampled or derived logic values exposes the
# same display-only selector.  Keep this list centralized so protocol, stream,
# event and waveform actions cannot drift independently.
VALUE_BEARING_ACTIONS = {
    "apb.transaction.cursor",
    "apb.export",
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
    "trace.active_driver_chain",
    "trace.x_origin",
    "value.at",
    "verify.conditions",
    "window.verify",
}
for _action in TIME_RENDERING_ACTIONS:
    RUNTIME_CONSUMER_CONTRACTS_BY_ACTION[_action].optional_args.add(
        "render_time_unit"
    )
for _action in VALUE_BEARING_ACTIONS:
    RUNTIME_CONSUMER_CONTRACTS_BY_ACTION[_action].optional_args.add(
        "value_format"
    )


ARGS_REQUIRED_EXCEPTIONS = {
    "session.close",
}


TOP_LEVEL_PROPERTIES: dict[str, dict[str, Any]] = {
    "api_version": {"type": "string", "enum": ["xdebug.v1"]},
    "request_id": {"type": "string", "minLength": 1},
    "action": {"type": "string"},
    "target": {"type": "object"},
    "args": {"type": "object"},
    "limits": {"type": "object"},
}

TARGET_FIELD_SCHEMAS: dict[str, dict[str, Any]] = {
    "session_id": {"type": "string", "minLength": 1},
    "daidir": {"type": "string", "minLength": 1},
    "fsdb": {"type": "string", "minLength": 1},
    "run_manifest": {"type": "string", "minLength": 1},
}

RUNTIME_SIGNED_INT_MAX = 2_147_483_647

LIMIT_PROPERTIES_BY_ACTION: dict[str, dict[str, dict[str, Any]]] = {
    "batch": {
        "timeout_ms": {
            "type": "integer",
            "minimum": 1,
            "maximum": RUNTIME_SIGNED_INT_MAX,
            "description": (
                "Total wall-clock budget for the ordered batch. Remaining "
                "time is projected into each engine-forward child and no "
                "later child starts after the deadline."
            ),
        },
    },
    "scope.list": {
        "max_rows": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum hierarchy rows returned by the scope traversal.",
        },
    },
    "trace.driver": {
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": RUNTIME_SIGNED_INT_MAX,
            "description": "Maximum static driver paths returned.",
        },
    },
    "trace.load": {
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": RUNTIME_SIGNED_INT_MAX,
            "description": "Maximum static load paths returned.",
        },
    },
    "trace.active_driver": {
        "max_depth": {
            "type": "integer", "minimum": 1, "default": 8,
            "description": "Maximum active-driver recursion depth.",
        },
        "max_nodes": {
            "type": "integer", "minimum": 1, "default": 50,
            "description": "Maximum active-trace nodes analyzed.",
        },
        "max_time_steps": {
            "type": "integer", "minimum": 1, "default": 128,
            "description": "Maximum distinct waveform times visited by active tracing.",
        },
        "max_trace_signals": {
            "type": "integer", "minimum": 1, "default": 64,
            "description": "Maximum candidate signals sampled for active-driver evidence.",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": RUNTIME_SIGNED_INT_MAX,
            "default": 10,
            "description": "Maximum simplified active-driver paths returned.",
        },
    },
    "trace.active_driver_chain": {
        "max_depth": {
            "type": "integer", "minimum": 1, "default": 8,
            "description": "Maximum recursive depth of the active-driver chain.",
        },
        "max_nodes": {
            "type": "integer", "minimum": 1, "default": 50,
            "description": "Maximum active-driver chain nodes analyzed.",
        },
        "max_trace_signals": {
            "type": "integer", "minimum": 1, "default": 64,
            "description": "Maximum candidate signals sampled for ambiguity evidence.",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": RUNTIME_SIGNED_INT_MAX,
            "default": 10,
            "description": "Maximum simplified chain evidence paths returned.",
        },
    },
    "trace.x_origin": {
        "max_depth": {
            "type": "integer", "minimum": 1, "default": 8,
            "description": "Maximum X-origin recursion depth.",
        },
        "max_nodes": {
            "type": "integer", "minimum": 1, "default": 50,
            "description": "Maximum X-origin nodes analyzed across all branches.",
        },
        "max_time_steps": {
            "type": "integer", "minimum": 1, "default": 128,
            "description": "Maximum distinct waveform times visited across X-origin branches.",
        },
        "max_trace_signals": {
            "type": "integer", "minimum": 1, "default": 64,
            "description": "Maximum dependency candidates sampled at one X-origin step.",
        },
        "max_chains": {
            "type": "integer", "minimum": 1, "default": 8,
            "description": "Maximum effective X-semantic chains returned.",
        },
    },
}


def exclusive_target_schema(
    direct_fields: tuple[str, ...],
    *,
    require_all_direct: bool,
) -> dict[str, Any]:
    """Choose exactly one target source: session lookup or direct resources."""
    properties = {
        key: copy.deepcopy(TARGET_FIELD_SCHEMAS[key])
        for key in ("session_id",) + direct_fields
    }
    session_branch = {
        "required": ["session_id"],
        "not": {
            "anyOf": [{"required": [key]} for key in direct_fields],
        },
    }
    direct_required = list(direct_fields) if require_all_direct else []
    direct_branch: dict[str, Any] = {
        "not": {"required": ["session_id"]},
    }
    if require_all_direct:
        direct_branch["required"] = direct_required
    else:
        direct_branch["anyOf"] = [
            {"required": [key]} for key in direct_fields
        ]
    return {
        "type": "object",
        "properties": properties,
        "oneOf": [session_branch, direct_branch],
        "additionalProperties": False,
    }


def target_schema_for_spec(spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    action = spec["name"]
    if action == "session.open":
        return ({
            "type": "object",
            "properties": {
                key: copy.deepcopy(TARGET_FIELD_SCHEMAS[key])
                for key in ("daidir", "fsdb", "run_manifest")
            },
            "anyOf": [{"required": ["daidir"]}, {"required": ["fsdb"]}],
            "allOf": [
                {
                    "if": {"required": ["run_manifest"]},
                    "then": {"required": ["fsdb"]},
                }
            ],
            "additionalProperties": False,
        }, True)

    required_target = list(spec.get("required_target", []))
    if required_target:
        return ({
            "type": "object",
            "properties": {
                key: copy.deepcopy(TARGET_FIELD_SCHEMAS[key])
                for key in required_target
            },
            "required": required_target,
            "additionalProperties": False,
        }, True)

    requirement = spec.get("requires", "none")
    if action == "expr.normalize":
        return ({
            "type": "object",
            "properties": {
                "session_id": copy.deepcopy(TARGET_FIELD_SCHEMAS["session_id"]),
                "daidir": copy.deepcopy(TARGET_FIELD_SCHEMAS["daidir"]),
            },
            "additionalProperties": False,
        }, False)
    if requirement == "design":
        return (
            exclusive_target_schema(("daidir",), require_all_direct=True),
            True,
        )
    if requirement == "waveform":
        return (
            exclusive_target_schema(("fsdb",), require_all_direct=True),
            True,
        )
    if requirement == "combined":
        return (
            exclusive_target_schema(
                ("daidir", "fsdb"), require_all_direct=True
            ),
            True,
        )
    if requirement == "any":
        return (
            exclusive_target_schema(
                ("daidir", "fsdb"), require_all_direct=False
            ),
            True,
        )
    if requirement == "session":
        return ({
            "type": "object",
            "properties": {
                "session_id": copy.deepcopy(TARGET_FIELD_SCHEMAS["session_id"]),
            },
            "required": ["session_id"],
            "additionalProperties": False,
        }, True)
    return ({"type": "object", "properties": {}, "additionalProperties": False}, False)


def limits_schema_for_spec(spec: dict[str, Any]) -> dict[str, Any]:
    properties = copy.deepcopy(LIMIT_PROPERTIES_BY_ACTION.get(spec["name"], {}))
    if spec.get("handler_kind") == "engine_forward":
        properties["timeout_ms"] = {
            "type": "integer",
            "minimum": 1,
            "maximum": RUNTIME_SIGNED_INT_MAX,
            "description": (
                "Positive public frontend-to-engine request timeout in "
                "milliseconds. Omit limits.timeout_ms to disable the public "
                "watchdog."
            ),
        }
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
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
    # Checked-in request schemas are generated artifacts, not contract
    # sources.  They may still contain a field removed from the declarative
    # runtime-consumer contract at the beginning of a regeneration.  Only
    # collect templates for fields that the current source contract publishes
    # so a retired field cannot keep itself alive or block its own removal.
    published_args = {
        arg
        for spec in specs
        for arg in allowed_args_for_spec(spec)
    }
    arg_schemas: dict[str, dict[str, Any]] = {}
    for spec in specs:
        for kind in ("request",):
            path = XDEBUG_ROOT / spec["schemas"][kind]
            if not path.exists():
                continue
            schema = load_json(path)
            props = schema.get("properties", {}).get("args", {}).get("properties", {})
            if isinstance(props, dict):
                for key, value in props.items():
                    if not isinstance(value, dict):
                        continue
                    if key not in published_args:
                        continue
                    if key not in arg_schemas:
                        arg_schemas[key] = copy.deepcopy(value)
    for key, value in ADDITIONAL_ARG_SCHEMAS.items():
        arg_schemas.setdefault(key, copy.deepcopy(value))
    # Sensitive conditional-cleanup semantics must come from the generator,
    # never from a previously checked-in schema artifact.  Otherwise the
    # first schema encountered can keep stale managed-wrapper wording alive.
    arg_schemas["ownership_token"] = copy.deepcopy(
        ADDITIONAL_ARG_SCHEMAS["ownership_token"]
    )
    # Keep generic channel open for stream/APB-style uses; action-specific
    # channel enums are applied in sync_schema().
    arg_schemas["channel"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["channel"])
    # list.delete owns the only top-level args.index contract.  Do not let a
    # previously generated string-compatible schema re-enter the source
    # templates: the canonical index is a one-based positive integer.
    arg_schemas["index"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["index"])
    arg_schemas["output"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["output"])
    arg_schemas["time_range"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["time_range"])
    arg_schemas["render_time_unit"] = copy.deepcopy(
        ADDITIONAL_ARG_SCHEMAS["render_time_unit"]
    )

    arg_schemas["checks"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 3,
        "uniqueItems": True,
        "items": {
            "oneOf": [
                {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {"const": "unknown_xz"},
                    },
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {"const": "glitch"},
                        "min_pulse_width": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {"const": "stuck"},
                        "min_duration": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
            ],
        },
        "description": (
            "signal.anomaly.inspect checks. Each check type has a closed, "
            "type-specific object contract; string shorthand is not supported."
        ),
    }
    arg_schemas["direction"] = {"type": "string", "enum": ["write", "read", "all"]}
    arg_schemas["kind"] = {
        "type": "string", "enum": ["request", "response"], "default": "request",
        "description": "schema action 要返回的 JSON Schema 类别：request 或 response。",
    }
    arg_schemas["filter"] = actions_filter_schema()
    arg_schemas["mode"] = {"type": "string"}
    arg_schemas["op"] = {"type": "string", "enum": ["begin", "next", "prev", "pre", "last"]}
    arg_schemas["port"] = {
        "type": "integer",
        "minimum": 0,
        "maximum": 65535,
    }
    arg_schemas["query"] = {"oneOf": [{"type": "string"}, {"type": "object"}]}
    arg_schemas["vld"] = {
        "oneOf": [
            {
                "type": "string",
                "minLength": 1,
                "description": "Signal path used directly as the counter-valid predicate.",
            },
            {
                "type": "object",
                "required": ["expr", "signals"],
                "properties": {
                    "expr": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Boolean expression over aliases declared in signals.",
                    },
                    "signals": {
                        "type": "object",
                        "minProperties": 1,
                        "propertyNames": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "additionalProperties": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "x-dynamic-map": True,
                        "description": "Alias-to-waveform-signal map consumed by expr.",
                    },
                },
                "additionalProperties": False,
                "description": "Expression predicate with an explicit alias-to-signal map.",
            },
        ]
    }
    arg_schemas["slice_hint"] = {
        "type": "object",
        "required": ["chunk_width"],
        "properties": {
            "chunk_width": {
                "type": "integer",
                "minimum": 1,
                "description": "Width in bits of each deterministic xbit slice.",
            },
            "count": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "Number of consecutive chunks starting at bit zero.",
            },
        },
        "additionalProperties": False,
    }
    return arg_schemas


def allowed_args_for_spec(spec: dict[str, Any]) -> set[str]:
    action = spec["name"]
    if action not in RUNTIME_CONSUMER_CONTRACTS_BY_ACTION:
        raise ValueError(
            f"{action}: missing runtime optional-argument consumer declaration"
        )
    return (
        required_related_args(spec)
        | RUNTIME_CONSUMER_CONTRACTS_BY_ACTION[action].optional_args
    )


def protocol_config_schema(
    required_signals: list[str],
    description: str,
    *,
    optional_signals: list[str] | None = None,
) -> dict[str, Any]:
    optional_signals = optional_signals or []
    properties: dict[str, Any] = {}
    for signal in required_signals + optional_signals:
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


def signal_alias_map_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "minProperties": 1,
        "propertyNames": {"type": "string", "minLength": 1},
        "additionalProperties": {"type": "string", "minLength": 1},
        "x-dynamic-map": True,
        "x-dynamic-contract": (
            "Every non-empty property key is an expression alias and every "
            "value is the non-empty waveform path resolved for that alias."
        ),
        "description": description,
    }


def signal_path_array_schema(
    description: str,
    *,
    min_items: int = 1,
) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": min_items,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
        "description": description,
    }


def known_unsigned_literal_schema(*, max_bits: int | None = None) -> dict[str, Any]:
    width_note = f" up to {max_bits} bits" if max_bits is not None else ""
    return {
        "type": "string",
        "minLength": 1,
        "oneOf": [
            {"pattern": "^[0-9]+$"},
            {"pattern": "^(?:[1-9][0-9]*)?'[bB][01](?:_?[01])*$"},
            {"pattern": "^(?:[1-9][0-9]*)?'[dD][0-9](?:_?[0-9])*$"},
            {"pattern": "^(?:[1-9][0-9]*)?'[hH][0-9a-fA-F](?:_?[0-9a-fA-F])*$"},
        ],
        "description": (
            f"Known unsigned decimal or b/d/h SystemVerilog literal{width_note}; "
            "X/Z and C-style 0x are rejected."
        ),
        "x-description-zh": (
            f"不含 X/Z 的无符号十进制或 b/d/h SystemVerilog literal"
            f"{'，宽度不超过 ' + str(max_bits) + ' bit' if max_bits is not None else ''}；"
            "不接受 C 风格 0x。"
        ),
    }


def protocol_statistics_filter_schema(allow_ids: bool) -> dict[str, Any]:
    literal = known_unsigned_literal_schema(max_bits=64)
    exact = {
        "type": "object",
        "description": "Exact-match branch: at least one listed value must equal the sampled field value.",
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
        "description": "Inclusive-range branch: the sampled field value must lie between begin and end.",
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
        "description": "Masked-match branch: compare only the bits selected by mask against value.",
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
    literal = known_unsigned_literal_schema()
    exact = {
        "type": "object",
        "description": "Exact-match branch: at least one listed value must equal the sampled stream field.",
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
        "description": "Inclusive-range branch: the sampled stream field must lie between begin and end.",
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
        "description": "Masked-match branch: compare only stream-field bits selected by mask against value.",
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
        properties[key] = copy.deepcopy(value)
    properties["action"] = {"type": "string", "enum": [action]}
    target_schema, target_required = target_schema_for_spec(spec)
    properties["target"] = target_schema
    if target_required:
        updated["required"].append("target")
    properties["limits"] = limits_schema_for_spec(spec)

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
    if "output" in selected_props:
        if action not in OUTPUT_SCHEMAS_BY_ACTION:
            raise ValueError(
                f"{action}: args.output is public but has no action-specific contract"
            )
        selected_props["output"] = copy.deepcopy(OUTPUT_SCHEMAS_BY_ACTION[action])
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
    if action == "batch":
        selected_props["mode"] = {
            "type": "string",
            "enum": ["continue_on_error", "stop_on_error"],
            "default": "continue_on_error",
            "description": (
                "Batch failure policy. continue_on_error executes every child; "
                "stop_on_error stops immediately after the first failed child."
            ),
        }
    if action == "session.close":
        selected_props["mode"] = {
            "type": "string",
            "enum": ["graceful", "force"],
            "default": "graceful",
            "description": (
                "graceful requests server shutdown and preserves the session "
                "record when exit is not confirmed; force may terminate a "
                "locally owned process after identity checks."
            ),
        }
    if action == "stream.query":
        selected_props["filter"] = stream_query_filter_schema()
    if action == "axi.analysis" and "analysis" in selected_props:
        selected_props["analysis"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["analysis"])
    if action == "apb.config.load" and "config" in selected_props:
        selected_props["config"] = protocol_config_schema(
            [
                "clock", "paddr", "psel", "penable",
                "pwrite", "pwdata", "prdata",
            ],
            PARAM_DESCRIPTIONS["config"],
            optional_signals=["pready", "pslverr"],
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
            "type": "object",
            "minProperties": 1,
            "propertyNames": {
                "type": "string",
                "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
            },
            "additionalProperties": {
                "type": "string",
                "minLength": 1,
            },
        }
        stream_item = {
            "type": "object",
            "required": ["name", "signals", "clock", "vld"],
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
                },
                "signals": {
                    "type": "object",
                    "minProperties": 1,
                    "propertyNames": {
                        "type": "string",
                        "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
                    },
                    "additionalProperties": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
                "clock": {"type": "string", "minLength": 1},
                "edge": {"type": "string", "enum": ["posedge", "negedge", "dual"]},
                "sample_point": {"type": "string", "enum": ["before", "after"]},
                "reset": reset_schema(),
                "vld": {"type": "string", "minLength": 1},
                "rdy": {"type": "string", "minLength": 1},
                "bp": {"type": "string", "minLength": 1},
                "sop": {"type": "string", "minLength": 1},
                "eop": {"type": "string", "minLength": 1},
                "data": {"type": "string", "minLength": 1},
                "beat_fields": copy.deepcopy(field_map),
                "packet_stable_fields": copy.deepcopy(field_map),
                "channel_id": {"type": "string", "minLength": 1},
                "channel_id_valid": {"type": "string", "enum": ["sop", "eop", "every_beat"]},
                "allow_interleaving": {"type": "boolean"},
                "description": {"type": "string", "minLength": 1},
            },
            "additionalProperties": False,
        }
        streams = {
            "type": "array", "minItems": 1, "items": stream_item,
            "description": PARAM_DESCRIPTIONS["streams"],
        }
        selected_props["config"] = {
            "type": "object", "required": ["streams"],
            "properties": {"streams": copy.deepcopy(streams)},
            "additionalProperties": False,
            "description": PARAM_DESCRIPTIONS["config"],
        }
        selected_props["mode"] = {"type": "string", "enum": ["replace", "append"]}
    if action == "list.load":
        list_item = {
            "type": "object",
            "required": ["name", "signals"],
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                },
                "signals": signal_path_array_schema(
                    "Non-empty unique final leaf waveform paths in this named list."
                ),
            },
            "additionalProperties": False,
            "description": (
                "One named collection of unique final leaf waveform signal paths."
            ),
        }
        selected_props["config"] = {
            "type": "object",
            "required": ["lists"],
            "properties": {
                "lists": {
                    "type": "array",
                    "minItems": 1,
                    "items": list_item,
                    "description": (
                        "One or more named waveform signal lists loaded atomically."
                    ),
                }
            },
            "additionalProperties": False,
            "description": PARAM_DESCRIPTIONS["config"],
        }
        selected_props["mode"] = {
            "type": "string",
            "enum": ["replace", "append"],
            "default": "replace",
        }
    if action in {
        "event.find",
        "event.export",
        "expr.eval_at",
        "verify.conditions",
        "window.verify",
    } and "signals" in selected_props:
        selected_props["signals"] = signal_alias_map_schema(
            PARAM_DESCRIPTIONS["signals"]
        )
    if action in {
        "signal.anomaly.inspect",
        "list.create",
    } and "signals" in selected_props:
        selected_props["signals"] = signal_path_array_schema(
            PARAM_DESCRIPTIONS["signals"]
        )
    if action == "axi.query" and "query" in selected_props:
        selected_props["query"] = {
            "oneOf": [
                {
                    "type": "object",
                    "minProperties": 1,
                    "properties": {
                        "line_limit": {"type": "integer", "minimum": 1},
                        "index": {"type": "integer", "minimum": 1},
                    },
                    "anyOf": [
                        {"required": ["line_limit"]},
                        {"required": ["index"]},
                    ],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": ["channel", "handshake_time"],
                    "properties": {
                        "channel": {"type": "string", "enum": ["aw", "w", "b", "ar", "r"]},
                        "handshake_time": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "additionalProperties": False,
                },
            ],
            "description": "Select transactions by 1-based index/line_limit, or exactly match an AXI channel handshake time.",
        }
    if action in {"apb.export", "apb.query", "axi.query"}:
        protocol_filter = protocol_statistics_filter_schema(allow_ids=True)
        address_filter = copy.deepcopy(
            protocol_filter["properties"]["address"]
        )
        if "address" in selected_props:
            selected_props["address"] = address_filter
        if action == "axi.query" and "id" in selected_props:
            selected_props["id"] = {
                "oneOf": copy.deepcopy(address_filter["oneOf"][:2]),
                "description": (
                    "Exactly one AXI ID filtering mode: exact queue or "
                    "inclusive range."
                ),
                "x-description-zh": (
                    "AXI ID 只能选择精确值队列或闭区间两种模式之一。"
                ),
            }
        if "last" in selected_props:
            selected_props["last"] = {
                "const": True,
                "description": (
                    "Select the final transaction matching the other "
                    "transaction filters."
                ),
            }
    if action == "apb.export" and "time_range" in selected_props:
        selected_props["time_range"]["required"] = ["begin", "end"]
    if action == "list.export" and "format" in selected_props:
        selected_props["format"] = {
            "type": "string",
            "enum": ["u64bin"],
            "description": "list.export input format. The response manifest uses versioned format u64bin.v1.",
        }
    if action == "stream.export":
        if "kind" in selected_props:
            selected_props["kind"] = {
                "type": "string",
                "enum": ["transfer", "packet", "packet_beats"],
                "description": "导出或查询的结果类型。",
            }
    if action in VALUE_BEARING_ACTIONS and "value_format" in selected_props:
        selected_props["value_format"]["default"] = "hex"
    if action in {"verify.conditions", "window.verify"} and "conditions" in selected_props:
        condition_properties = {
            "expr": {
                "type": "string",
                "description": "Expression using aliases from args.signals.",
            },
        }
        if action == "verify.conditions":
            condition_properties["name"] = {"type": "string"}
        else:
            condition_properties["mode"] = {
                "type": "string",
                "enum": ["always", "eventually", "never"],
            }
        selected_props["conditions"] = {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["expr"],
                "properties": condition_properties,
                "additionalProperties": False,
            },
            "description": PARAM_DESCRIPTIONS["conditions"],
        }
        selected_props["conditions"]["items"]["properties"]["expr"]["minLength"] = 1
        if action == "verify.conditions":
            selected_props["conditions"]["items"]["properties"]["name"]["minLength"] = 1
    if action == "axi.channel_stall" and "channel" in selected_props:
        selected_props["channel"] = {
            "type": "string",
            "enum": ["aw", "w", "b", "ar", "r"],
            "description": "AXI channel to inspect.",
        }
    if action == "scope.list":
        selected_props["source"] = {
            "type": "string",
            "enum": ["wave", "design", "merged"],
            "default": "wave",
            "description": (
                "Hierarchy evidence source. wave requires FSDB, design requires "
                "daidir, and merged requires both resources."
            ),
            "x-description-zh": (
                "层级证据来源：wave 要求 FSDB，design 要求 daidir，merged 要求两者。"
            ),
        }
        selected_props["kind"] = {
            "type": "string",
            "enum": [
                "all", "module", "interface", "interface_array",
                "gen_scope", "internal_scope", "modport", "mpport",
                "port", "signal",
            ],
            "default": "all",
            "description": "只返回指定层级对象 kind，或使用 all 返回全部 kind。",
        }
    if action == "scope.roots":
        selected_props["source"] = {
            "type": "string",
            "enum": ["auto", "wave", "design"],
            "default": "auto",
            "description": "scope roots 或证据的来源选择。",
        }
    if action == "protocol.handshake.inspect":
        selected_props["data"] = copy.deepcopy(ADDITIONAL_ARG_SCHEMAS["data"])
        selected_props["rules"] = {
            "type": "object",
            "properties": {
                "max_wait_cycles": {"type": "integer", "minimum": 0},
                "check_data_stable_when_stalled": {"const": True},
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
        if "payloads" in selected_props:
            selected_props["payloads"] = signal_path_array_schema(
                "Non-empty payload signal list inspected under one sampling contract."
            )
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
    if action == "event.export" and "aggregate" in selected_props:
        selected_props["aggregate"] = {
            "type": "object",
            "properties": {
                "events": {"type": "boolean", "default": True},
                "group_by": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "additionalProperties": False,
            "description": (
                "Event-export aggregation controls. Every group_by entry "
                "must name a configured event signal alias or field."
            ),
        }
    if action == "event.find":
        selected_props["mode"] = {
            "type": "string",
            "enum": ["first", "last", "all"],
            "default": "first",
        }
    if action == "event.export":
        selected_props["mode"] = {"type": "string", "enum": ["export"], "default": "export"}
    if action in {
        "apb.config.load",
        "axi.config.load",
        "event.config.load",
        "list.load",
        "stream.config.load",
        "nwave.rc.generate",
    }:
        for path_arg in ("config_path", "file"):
            if path_arg in selected_props:
                selected_props[path_arg] = {
                    "type": "string",
                    "minLength": 1,
                    "description": PARAM_DESCRIPTIONS[path_arg],
                }
    if action == "session.open":
        selected_props["name"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$",
            "description": (
                "Session name: start with an ASCII letter, then use only "
                "ASCII letters, digits, or underscores; maximum 64 characters."
            ),
        }
    for key, value in list(selected_props.items()):
        selected_props[key] = complete_descriptions(
            apply_argument_contract(action, key, value), f"args.{key}"
        )
    args["properties"] = selected_props
    args["additionalProperties"] = False
    if action == "session.close":
        args["allOf"] = [
            {
                "if": {
                    "required": ["ownership_token"],
                },
                "then": {
                    "properties": {"mode": {"const": "force"}},
                    "required": ["mode"],
                },
            }
        ]
    groups = spec.get("required_arg_groups", [])
    if groups:
        args["anyOf"] = [{"required": list(group)} for group in groups]
    else:
        args.pop("anyOf", None)
    if action == "list.delete":
        args.pop("anyOf", None)
        args["oneOf"] = [
            {
                "required": ["signal"],
                "not": {"required": ["index"]},
            },
            {
                "required": ["index"],
                "not": {"required": ["signal"]},
            },
        ]
    else:
        args.pop("oneOf", None)
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
        if action != "session.close":
            args.pop("allOf", None)
    exclusive_config_sources = {
        "apb.config.load": ("config", "config_path"),
        "axi.config.load": ("config", "config_path"),
        "list.load": ("config", "config_path"),
        "stream.config.load": ("config", "config_path"),
    }
    if action in exclusive_config_sources:
        args.pop("anyOf", None)
        args["oneOf"] = [
            {"required": [source]}
            for source in exclusive_config_sources[action]
        ]
    if action == "value.at":
        selectors = ("signal", "list", "apb", "stream", "axi")
        selector_variants = []
        for selector in selectors:
            selector_variants.append(
                {
                    "required": [selector],
                    "not": {
                        "anyOf": [
                            {"required": [other]}
                            for other in selectors
                            if other != selector
                        ]
                    },
                }
            )
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
                    {
                        "required": ["time"],
                        "not": {"required": ["times"]},
                    },
                    {
                        "required": ["times"],
                        "not": {"required": ["time"]},
                    },
                ]
            },
            {
                "if": {"required": ["slice_hint"]},
                "then": {"required": ["signal"]},
            },
        ]
    if action in {"apb.query", "axi.query"}:
        query_constraints: list[dict[str, Any]] = [
            {"not": {"required": ["last", "query"]}},
        ]
        if action == "axi.query":
            query_constraints.append(
                {
                    "if": {
                        "required": ["output"],
                        "properties": {
                            "output": {"required": ["include_data"]},
                        },
                    },
                    "then": {
                        "anyOf": [
                            {"required": ["last"]},
                            {"required": ["query"]},
                        ]
                    },
                }
            )
            query_constraints.append(
                {
                    "if": {
                        "required": ["query"],
                        "properties": {
                            "query": {"required": ["channel"]}
                        },
                    },
                    "then": {
                        "not": {
                            "anyOf": [
                                {"required": [key]}
                                for key in (
                                    "direction",
                                    "address",
                                    "id",
                                    "time_range",
                                    "last",
                                )
                            ]
                        }
                    },
                }
            )
        args["allOf"] = list(args.get("allOf", [])) + query_constraints
    if action == "protocol.handshake.inspect":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {"required": ["data"]},
                "then": {
                    "required": ["rules"],
                    "properties": {
                        "rules": {
                            "required": [
                                "check_data_stable_when_stalled"
                            ],
                            "properties": {
                                "check_data_stable_when_stalled": {
                                    "const": True
                                }
                            },
                        }
                    },
                },
            },
            {
                "if": {
                    "required": ["rules"],
                    "properties": {
                        "rules": {
                            "required": [
                                "check_data_stable_when_stalled"
                            ],
                        }
                    },
                },
                "then": {"required": ["data"]},
            },
        ]
    if action == "value.at":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {"not": {"required": ["clock"]}},
                "then": {
                    "not": {
                        "anyOf": [
                            {"required": ["edge"]},
                            {"required": ["sample_point"]},
                        ]
                    }
                },
            }
        ]
    if action == "signal.sampled_pulse.inspect":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "required": ["rules"],
                    "properties": {
                        "rules": {
                            "required": [
                                "payload_changed_without_sampled_valid"
                            ]
                        }
                    },
                },
                "then": {
                    "required": ["payloads"]
                },
            },
        ]
    if action == "signal.changes":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "required": ["mode"],
                    "properties": {"mode": {"const": "summary"}},
                },
                "then": {"not": {"required": ["line_limit"]}},
            }
        ]
    if action == "session.open":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "anyOf": [
                        {"required": ["host"]},
                        {"required": ["bind_host"]},
                        {"required": ["port"]},
                    ]
                },
                "then": {
                    "required": ["transport"],
                    "properties": {
                        "transport": {"const": "tcp"},
                    },
                },
            }
        ]
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
        args["oneOf"] = [
            {
                "required": ["expr"],
                "not": {
                    "anyOf": [
                        {"required": [key]}
                        for key in ("signal", "line_limit", "no_statement_only", "role")
                    ]
                },
            },
            {
                "required": ["signal"],
                "not": {"required": ["expr"]},
            },
        ]
        updated["oneOf"] = [
            {
                "required": ["args"],
                "properties": {
                    "args": {"required": ["expr"]},
                    "target": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            },
            {
                "required": ["args", "target"],
                "properties": {
                    "args": {"required": ["signal"]},
                    "target": {
                        "type": "object",
                        "properties": {
                            "session_id": copy.deepcopy(TARGET_FIELD_SCHEMAS["session_id"]),
                            "daidir": copy.deepcopy(TARGET_FIELD_SCHEMAS["daidir"]),
                        },
                        "oneOf": [
                            {
                                "required": ["session_id"],
                                "not": {"required": ["daidir"]},
                            },
                            {
                                "required": ["daidir"],
                                "not": {"required": ["session_id"]},
                            },
                        ],
                        "additionalProperties": False,
                    },
                },
            },
        ]
    if action in {"event.export", "list.export", "stream.export"}:
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
    if action == "event.export":
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "required": ["aggregate"],
                    "properties": {
                        "aggregate": {
                            "required": ["events"],
                            "properties": {"events": {"const": False}},
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
    if action in {"stream.query", "stream.export", "stream.validate"}:
        args["allOf"] = list(args.get("allOf", [])) + [
            {
                "if": {
                    "required": ["cache_scope"],
                    "properties": {"cache_scope": {"const": "range"}},
                },
                "then": {
                    "required": ["time_range"],
                    "properties": {
                        "time_range": {
                            "anyOf": [
                                {"required": ["begin"]},
                                {"required": ["end"]},
                            ]
                        }
                    },
                },
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
    if action == "session.close":
        updated["allOf"] = [
            {
                "not": {
                    "properties": {
                        "target": {
                            "properties": {
                                "session_id": {"const": "all"}
                            },
                            "required": ["session_id"],
                        },
                        "args": {
                            "required": ["ownership_token"]
                        },
                    },
                    "required": ["target", "args"],
                }
            }
        ]
    if action == "scope.list":
        updated["allOf"] = [
            {
                "if": {
                    "anyOf": [
                        {"not": {"required": ["args"]}},
                        {
                            "properties": {
                                "args": {"not": {"required": ["source"]}}
                            },
                            "required": ["args"],
                        },
                        {
                            "properties": {
                                "args": {
                                    "properties": {"source": {"const": "wave"}},
                                    "required": ["source"],
                                }
                            },
                            "required": ["args"],
                        },
                    ]
                },
                "then": {
                    "properties": {
                        "target": {
                            "anyOf": [
                                {"required": ["session_id"]},
                                {"required": ["fsdb"]},
                            ]
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "args": {
                            "properties": {"source": {"const": "design"}},
                            "required": ["source"],
                        }
                    },
                    "required": ["args"],
                },
                "then": {
                    "properties": {
                        "target": {
                            "anyOf": [
                                {"required": ["session_id"]},
                                {"required": ["daidir"]},
                            ]
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "args": {
                            "properties": {"source": {"const": "merged"}},
                            "required": ["source"],
                        }
                    },
                    "required": ["args"],
                },
                "then": {
                    "properties": {
                        "target": {
                            "anyOf": [
                                {"required": ["session_id"]},
                                {"required": ["daidir", "fsdb"]},
                            ]
                        }
                    }
                },
            },
        ]
    if action != "expr.normalize":
        updated.pop("oneOf", None)
    updated["additionalProperties"] = False
    return updated


def attach_strict_batch_child_envelope(
    generated: dict[str, dict[str, Any]],
) -> None:
    batch = generated.get("batch")
    if batch is None:
        raise ValueError("batch: generated request schema is missing")

    requests = (
        batch["properties"]["args"]["properties"]["requests"]
    )
    requests["type"] = "array"
    requests["minItems"] = 1
    requests["items"] = {
        "type": "object",
        "properties": {
            "api_version": {
                "type": "string",
                "description": (
                    "Child public API version. It is intentionally not "
                    "defaulted by batch."
                ),
            },
            "request_id": {
                "type": "string",
                "description": "Optional child request correlation id.",
            },
            "action": {
                "type": "string",
                "description": (
                    "Child action name selected for action-specific dispatch."
                ),
            },
            "target": {
                "type": "object",
                "x-deferred-action-validation": True,
                "description": (
                    "Child target, validated by the selected action contract."
                ),
            },
            "args": {
                "type": "object",
                "x-deferred-action-validation": True,
                "description": (
                    "Child arguments, validated by the selected action contract."
                ),
            },
            "limits": {
                "type": "object",
                "x-deferred-action-validation": True,
                "description": (
                    "Child limits, validated by the selected action contract."
                ),
            },
        },
        "additionalProperties": False,
        "x-deferred-action-validation": True,
        "description": (
            "Closed child envelope. Required fields and nested payload are "
            "validated by the child's action-specific public contract during "
            "child dispatch, so an invalid child is reported in data.results "
            "without turning the batch envelope into an outer schema error."
        ),
    }
    batch.pop("definitions", None)


def audit_runtime_consumer_contract(
    specs: list[dict[str, Any]],
    arg_schemas: dict[str, dict[str, Any]],
) -> list[str]:
    """Fail closed when a public arg has no explicit runtime owner.

    Required and conditional args are declared in actions.yaml.  Every
    optional top-level args leaf belongs to a named
    RUNTIME_CONSUMER_CONTRACTS_BY_ACTION boundary.  Request examples are
    witnesses, never an implicit allowlist source.
    """
    errors: list[str] = []
    action_names = {spec["name"] for spec in specs}
    declared_actions = set(RUNTIME_CONSUMER_CONTRACTS_BY_ACTION)
    if declared_actions != action_names:
        missing = sorted(action_names - declared_actions)
        unknown = sorted(declared_actions - action_names)
        if missing:
            errors.append(
                "runtime consumer declarations missing actions: " +
                ", ".join(missing)
            )
        if unknown:
            errors.append(
                "runtime consumer declarations reference unknown actions: " +
                ", ".join(unknown)
            )

    public_args: set[str] = set()
    for spec in specs:
        action = spec["name"]
        if action not in RUNTIME_CONSUMER_CONTRACTS_BY_ACTION:
            continue
        contract = RUNTIME_CONSUMER_CONTRACTS_BY_ACTION[action]
        if not contract.consumer_id.strip():
            errors.append(f"{action}: runtime consumer_id must be nonempty")
        declared = allowed_args_for_spec(spec)
        public_args.update(declared)
        undeclared_example_args = example_args(action) - declared
        if undeclared_example_args:
            errors.append(
                f"{action}: request example contains args without a runtime "
                "consumer declaration: " +
                ", ".join(sorted(undeclared_example_args))
            )

    component_only = {"protocol_query"}
    unused_additional = (
        set(ADDITIONAL_ARG_SCHEMAS) - public_args - component_only
    )
    if unused_additional:
        errors.append(
            "unused additional public arg definitions: " +
            ", ".join(sorted(unused_additional))
        )
    unused_collected = set(arg_schemas) - public_args - component_only
    if unused_collected:
        errors.append(
            "unused collected public arg definitions: " +
            ", ".join(sorted(unused_collected))
        )

    output_consumers = {
        action
        for action in action_names
        if "output" in (
            required_related_args(
                next(spec for spec in specs if spec["name"] == action)
            )
            | (
                RUNTIME_CONSUMER_CONTRACTS_BY_ACTION[action].optional_args
                if action in RUNTIME_CONSUMER_CONTRACTS_BY_ACTION
                else set()
            )
        )
    }
    output_definitions = set(OUTPUT_SCHEMAS_BY_ACTION)
    if output_definitions != output_consumers:
        missing = sorted(output_consumers - output_definitions)
        unused = sorted(output_definitions - output_consumers)
        if missing:
            errors.append(
                "args.output consumers missing action-specific schema: " +
                ", ".join(missing)
            )
        if unused:
            errors.append(
                "unused action-specific args.output schemas: " +
                ", ".join(unused)
            )
    return errors


def sync(check: bool, selected_actions: set[str] | None = None) -> list[str]:
    specs = action_specs()
    arg_schemas = collect_arg_schemas(specs)
    errors = audit_runtime_consumer_contract(specs, arg_schemas)
    if errors:
        return errors
    original: dict[str, dict[str, Any]] = {}
    generated: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}

    for spec in specs:
        path = XDEBUG_ROOT / spec["schemas"]["request"]
        schema = load_json(path)
        original[spec["name"]] = schema
        paths[spec["name"]] = path
        try:
            updated = sync_schema(schema, spec, arg_schemas)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        generated[spec["name"]] = updated

    if errors:
        return errors
    try:
        attach_strict_batch_child_envelope(generated)
    except ValueError as exc:
        return [str(exc)]

    selected = set(generated) if not selected_actions else set(selected_actions) | {"batch"}
    for action in sorted(selected):
        if action not in generated:
            errors.append(f"unknown action selected for request schema sync: {action}")
            continue
        schema = original[action]
        updated = generated[action]
        if schema != updated:
            if check:
                errors.append(
                    f"{paths[action].relative_to(XDEBUG_ROOT)}: "
                    "runtime request schema is not synced"
                )
            else:
                paths[action].write_text(dump_json(updated), encoding="utf-8")
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
