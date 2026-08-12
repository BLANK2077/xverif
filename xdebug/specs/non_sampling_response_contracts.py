"""Strict response contracts for non-sampling public xdebug actions.

The checked-in response generator historically inferred a business contract
from one success example.  That is not sufficient for actions whose handler
has multiple reachable success shapes.  This module is the source of truth
for those shapes.  It is intentionally independent from the generator so it
can be imported without creating a schema-generation cycle.

Only Draft-7-compatible validation keywords are emitted.  ``$defs`` is used
as a local JSON-Pointer container, matching the rest of xdebug's generated
schemas.  Every business object is closed.  The only objects with dynamic
keys are explicitly marked maps whose values have a narrow schema.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


Schema = dict[str, Any]
SUMMARY_POINTER = "/summary"
DATA_POINTER = "/data"


NON_SAMPLING_RESPONSE_ACTIONS = frozenset(
    {
        "apb.config.list",
        "apb.config.load",
        "apb.query",
        "apb.statistics",
        "apb.transaction.cursor",
        "apb.transfer_window",
        "axi.analysis",
        "axi.channel_stall",
        "axi.config.list",
        "axi.config.load",
        "axi.export",
        "axi.latency_outlier",
        "axi.outstanding_timeline",
        "axi.query",
        "axi.request_response_pair",
        "axi.statistics",
        "axi.transaction.cursor",
        "expr.normalize",
        "event.config.list",
        "event.config.load",
        "list.add",
        "list.create",
        "list.load",
        "list.delete",
        "list.export",
        "list.first_change",
        "list.show",
        "list.validate",
        "nwave.rc.generate",
        "signal.anomaly.inspect",
        "signal.canonicalize",
        "signal.changes",
        "signal.resolve",
        "signal.stability",
        "signal.xz_verify",
        "scope.list",
        "stream.config.get",
        "stream.config.list",
        "stream.config.load",
        "stream.describe",
        "stream.export",
        "stream.query",
        "stream.validate",
        "trace.active_driver",
        "trace.active_driver_chain",
        "trace.driver",
        "trace.load",
        "trace.x_origin",
        "waveform.cursor.delete",
        "waveform.cursor.get",
        "waveform.cursor.list",
        "waveform.cursor.set",
        "waveform.cursor.use",
    }
)


@dataclass(frozen=True)
class NonSamplingSuccessVariant:
    """One correlated public ``summary``/``data`` success shape."""

    name: str
    summary: Schema
    data: Schema


def _closed(
    properties: Mapping[str, Schema],
    required: Iterable[str] = (),
) -> Schema:
    schema: Schema = {
        "type": "object",
        "properties": copy.deepcopy(dict(properties)),
        "additionalProperties": False,
    }
    required_fields = sorted(set(required))
    if required_fields:
        schema["required"] = required_fields
    return schema


def _array(
    items: Schema,
    *,
    min_items: int | None = None,
    max_items: int | None = None,
) -> Schema:
    schema: Schema = {"type": "array", "items": copy.deepcopy(items)}
    if min_items is not None:
        schema["minItems"] = min_items
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _ref(name: str) -> Schema:
    return {"$ref": f"#/$defs/{name}"}


def _string(*, nonempty: bool = True) -> Schema:
    schema: Schema = {"type": "string"}
    if nonempty:
        schema["minLength"] = 1
    return schema


def _integer(*, minimum: int | None = 0) -> Schema:
    schema: Schema = {"type": "integer"}
    if minimum is not None:
        schema["minimum"] = minimum
    return schema


def _recommended_actions() -> Schema:
    return _array(
        _closed(
            {
                "action": _string(),
                "purpose": _string(),
            },
            ("action", "purpose"),
        ),
        min_items=1,
    )


def _nullable(schema: Schema) -> Schema:
    return {"anyOf": [{"type": "null"}, copy.deepcopy(schema)]}


def _forbid(*names: str) -> Schema:
    return {"not": {"anyOf": [{"required": [name]} for name in names]}}


def _dynamic_map(value_schema: Schema, description: str) -> Schema:
    return {
        "type": "object",
        "additionalProperties": copy.deepcopy(value_schema),
        "x-dynamic-map": True,
        "description": description,
    }


def _completeness_properties() -> dict[str, Schema]:
    return {
        "scan_complete": {"type": "boolean"},
        "analysis_complete": {"type": "boolean"},
        "response_truncated": {"type": "boolean"},
        "total_count": _integer(),
        "returned_count": _integer(),
        "truncation_scopes": _array(_string()),
    }


def _completeness_required() -> tuple[str, ...]:
    return tuple(_completeness_properties())


def _value_width_properties() -> dict[str, Schema]:
    return {
        "value_width_complete": {"type": "boolean"},
        "width_diagnostics": _array(_ref("valueWidthDiagnostic")),
    }


def _summary(
    properties: Mapping[str, Schema],
    required: Iterable[str],
    *,
    complete: bool = False,
    value_width: bool = False,
) -> Schema:
    merged = copy.deepcopy(dict(properties))
    required_fields = list(required)
    if complete:
        merged.update(_completeness_properties())
        required_fields.extend(_completeness_required())
    if value_width:
        # These fields are inserted by apply_value_width_summary only when a
        # canonical logic-value object is present in the final payload.
        merged.update(_value_width_properties())
    return _closed(merged, required_fields)


def _variant(name: str, summary: Schema, data: Schema) -> NonSamplingSuccessVariant:
    return NonSamplingSuccessVariant(name, summary, data)


def _edge_closed(
    properties: Mapping[str, Schema],
    required: Iterable[str],
) -> Schema:
    """Close an object and correlate edge with sample_point presence."""

    schema = _closed(properties, required)
    schema["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {"edge": {"const": "negedge"}},
                    "required": ["edge"],
                    **_forbid("sample_point"),
                },
                {
                    "properties": {
                        "edge": {"enum": ["posedge", "dual"]},
                        "sample_point": {"enum": ["before", "after"]},
                    },
                    "required": ["edge", "sample_point"],
                },
            ]
        }
    ]
    return schema


def _expr_ast_schema() -> Schema:
    return {
        "oneOf": [
            _closed(
                {"type": {"const": "unknown"}, "text": {"type": "string"}},
                ("type", "text"),
            ),
            _closed(
                {"type": {"const": "const"}, "value": _string()},
                ("type", "value"),
            ),
            _closed(
                {"type": {"const": "signal"}, "name": _string()},
                ("type", "name"),
            ),
            _closed(
                {
                    "op": {"const": "not"},
                    "args": _array(
                        _ref("nonSamplingExprAst"),
                        min_items=1,
                        max_items=1,
                    ),
                },
                ("op", "args"),
            ),
            _closed(
                {
                    "op": {
                        "enum": [
                            "or",
                            "and",
                            "neq",
                            "eq",
                            "ge",
                            "le",
                            "gt",
                            "lt",
                            "add",
                            "sub",
                            "mul",
                        ]
                    },
                    "args": _array(
                        _ref("nonSamplingExprAst"),
                        min_items=2,
                        max_items=2,
                    ),
                },
                ("op", "args"),
            ),
            _closed(
                {
                    "op": {"const": "ternary"},
                    "args": _array(
                        _ref("nonSamplingExprAst"),
                        min_items=3,
                        max_items=3,
                    ),
                },
                ("op", "args"),
            ),
        ]
    }


def _npi_expr_ast_schema() -> Schema:
    """Strict recursive shape emitted by ``AstExtractor::expr_to_json``."""

    common_optional = {
        "ref_text": _string(nonempty=False),
    }
    unknown = _closed(
        {
            "kind": {"const": "unknown"},
            "text": _string(nonempty=False),
            "npi_type": _integer(),
            **common_optional,
        },
        ("kind", "text"),
    )
    constant = _closed(
        {
            "kind": {"const": "const"},
            "text": _string(nonempty=False),
            "parameter": {"type": "boolean"},
            "npi_type": _integer(),
            **common_optional,
        },
        ("kind", "text", "npi_type"),
    )
    signal = _closed(
        {
            "kind": {"const": "signal"},
            "name": _string(nonempty=False),
            "text": _string(nonempty=False),
            "npi_type": _integer(),
            **common_optional,
        },
        ("kind", "name"),
    )
    select = _closed(
        {
            "kind": {
                "enum": [
                    "bit_select",
                    "indexed_part_select",
                    "part_select",
                ]
            },
            "text": _string(nonempty=False),
            "base": {
                "oneOf": [
                    _closed({}),
                    _ref("nonSamplingNpiExprAst"),
                ]
            },
            "base_signal": _string(nonempty=False),
            "index": _ref("nonSamplingNpiExprAst"),
            "left": _ref("nonSamplingNpiExprAst"),
            "right": _ref("nonSamplingNpiExprAst"),
            "width": _ref("nonSamplingNpiExprAst"),
            **common_optional,
        },
        ("kind", "text", "base"),
    )
    operation = _closed(
        {
            "kind": {"const": "operation"},
            "op": _string(),
            "op_type": _integer(),
            "npi_type": _integer(),
            "args": _array(_ref("nonSamplingNpiExprAst")),
            "text": _string(nonempty=False),
            **common_optional,
        },
        ("kind", "op", "args", "text"),
    )
    operation["allOf"] = [
        {
            "oneOf": [
                {
                    "required": ["op_type"],
                    **_forbid("npi_type"),
                },
                {
                    "required": ["npi_type"],
                    **_forbid("op_type"),
                },
            ]
        }
    ]
    return {"oneOf": [unknown, constant, signal, select, operation]}


def _apb_config_schema() -> Schema:
    properties = {
        "name": _string(),
        "sampling_mode": {"const": "clock_edge"},
        "clock": _string(),
        "edge": {"enum": ["posedge", "negedge", "dual"]},
        "sample_point": {"enum": ["before", "after"]},
        "reset": _ref("reset"),
        "paddr": _string(),
        "psel": _string(),
        "penable": _string(),
        "pwrite": _string(),
        "pwdata": _string(),
        "prdata": _string(),
        "pready": _string(),
        "pslverr": _string(),
    }
    return _edge_closed(
        properties,
        (
            "name",
            "sampling_mode",
            "clock",
            "edge",
            "reset",
            "paddr",
            "psel",
            "penable",
            "pwrite",
            "pwdata",
            "prdata",
        ),
    )


def _axi_config_schema() -> Schema:
    channels = _closed(
        {
            "aw": _closed(
                {
                    name: _string()
                    for name in (
                        "addr",
                        "id",
                        "len",
                        "size",
                        "burst",
                        "valid",
                        "ready",
                    )
                },
                ("addr", "id", "len", "size", "burst", "valid", "ready"),
            ),
            "w": _closed(
                {
                    name: _string()
                    for name in ("data", "strb", "last", "valid", "ready")
                },
                ("data", "strb", "last", "valid", "ready"),
            ),
            "b": _closed(
                {
                    name: _string()
                    for name in ("id", "resp", "valid", "ready")
                },
                ("id", "resp", "valid", "ready"),
            ),
            "ar": _closed(
                {
                    name: _string()
                    for name in (
                        "addr",
                        "id",
                        "len",
                        "size",
                        "burst",
                        "valid",
                        "ready",
                    )
                },
                ("addr", "id", "len", "size", "burst", "valid", "ready"),
            ),
            "r": _closed(
                {
                    name: _string()
                    for name in (
                        "id",
                        "data",
                        "resp",
                        "last",
                        "valid",
                        "ready",
                    )
                },
                ("id", "data", "resp", "last", "valid", "ready"),
            ),
        },
        ("aw", "w", "b", "ar", "r"),
    )
    return _edge_closed(
        {
            "name": _string(),
            "sampling_mode": {"const": "clock_edge"},
            "clock": _string(),
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "sample_point": {"enum": ["before", "after"]},
            "reset": _ref("reset"),
            "channels": channels,
        },
        (
            "name",
            "sampling_mode",
            "clock",
            "edge",
            "reset",
            "channels",
        ),
    )


def _axi_validation_schema() -> Schema:
    validated_fields = (
        "clock",
        "reset",
        "awvalid",
        "awready",
        "awaddr",
        "awid",
        "awlen",
        "awsize",
        "awburst",
        "wvalid",
        "wready",
        "wdata",
        "wstrb",
        "wlast",
        "bvalid",
        "bready",
        "bid",
        "bresp",
        "arvalid",
        "arready",
        "araddr",
        "arid",
        "arlen",
        "arsize",
        "arburst",
        "rvalid",
        "rready",
        "rdata",
        "rid",
        "rresp",
        "rlast",
    )
    signal = _closed(
        {
            "field": {"enum": list(validated_fields)},
            "requested_path": _string(),
            "resolved_path": _string(),
            "width": _integer(),
            "status": {"const": "ok"},
        },
        (
            "field",
            "requested_path",
            "resolved_path",
            "width",
            "status",
        ),
    )
    signals = _array(
        signal,
        min_items=len(validated_fields),
        max_items=len(validated_fields),
    )
    signals["allOf"] = [
        {
            "contains": {
                "properties": {"field": {"const": field}},
                "required": ["field"],
            }
        }
        for field in validated_fields
    ]
    return _closed(
        {
            "status": {"const": "ok"},
            "clock": _closed(
                {
                    "status": {"const": "ok"},
                    "edge": {"enum": ["posedge", "negedge", "dual"]},
                    "first_edge": _integer(),
                },
                ("status", "edge", "first_edge"),
            ),
            "signals": signals,
        },
        ("status", "clock", "signals"),
    )


def _apb_transaction_schema(*, include_type: bool) -> Schema:
    properties = {
        "time": _string(),
        "addr": _string(),
        "data": _string(),
        "has_error": {"type": "boolean"},
    }
    required = ["time", "addr", "data", "has_error"]
    if include_type:
        properties["type"] = {"enum": ["WR", "RD"]}
        required.append("type")
    else:
        properties["is_write"] = {"type": "boolean"}
        required.append("is_write")
    return _closed(properties, required)


def _axi_beat_schema(*, write: bool) -> Schema:
    properties = {
        "index": _integer(minimum=1),
        "handshake_time": _string(),
        "data": _string(),
        "last": {"type": "boolean"},
    }
    if write:
        properties["wstrb"] = _string()
    else:
        properties["resp"] = _string()
    return _closed(
        properties,
        ("index", "handshake_time", "data", "last"),
    )


def _axi_transaction_direction_schema(
    *,
    write: bool,
    require_match_time: bool,
) -> Schema:
    address = _closed(
        {
            "channel": {"const": "aw" if write else "ar"},
            "valid_begin_time": _string(),
            "handshake_time": _string(),
            "addr": _string(),
            "id": _string(),
            "len": _string(),
            "size": _string(),
            "burst": _string(),
        },
        ("channel", "handshake_time", "addr", "id", "len", "size", "burst"),
    )
    data = _closed(
        {
            "channel": {"const": "w" if write else "r"},
            "valid_begin_time": _string(),
            "first_handshake_time": _string(),
            "last_handshake_time": _string(),
            "beat_count": _integer(),
            "expected_beat_count": _integer(),
            "beats": _array(_axi_beat_schema(write=write)),
            "first_beat": _axi_beat_schema(write=write),
        },
        (
            "channel",
            "first_handshake_time",
            "last_handshake_time",
            "beat_count",
            "expected_beat_count",
        ),
    )
    response = _closed(
        {
            "channel": {"const": "b" if write else "r"},
            "handshake_time": _string(),
            "resp": _string(),
        },
        ("channel", "handshake_time", "resp"),
    )
    properties = {
        "direction": {"const": "write" if write else "read"},
        "latency": _string(),
        "response_dependency_violation": {"type": "boolean"},
        "address": address,
        "data": data,
        "response": response,
    }
    required = [
        "direction",
        "latency",
        "response_dependency_violation",
        "address",
        "response",
    ]
    if write:
        properties["phase_order"] = {
            "enum": ["aw_before_w", "same_cycle", "w_before_aw", "unknown"]
        }
        required.append("phase_order")
    if require_match_time:
        properties["match_time"] = _string()
        required.append("match_time")
    return _closed(properties, required)


def _axi_transaction_schema(*, require_match_time: bool = False) -> Schema:
    return {
        "oneOf": [
            _axi_transaction_direction_schema(
                write=True,
                require_match_time=require_match_time,
            ),
            _axi_transaction_direction_schema(
                write=False,
                require_match_time=require_match_time,
            ),
        ]
    }


def _axi_pending_transaction_schema() -> Schema:
    common = {
        "direction": {"type": "string"},
        "id": _string(),
        "addr": _string(),
        "len": _string(),
        "request_time": _string(),
        "age": _string(),
        "observed_beat_count": _integer(),
        "expected_beat_count": _integer(),
        "data_complete": {"type": "boolean"},
    }
    required = tuple(common)
    read = copy.deepcopy(common)
    read["direction"] = {"const": "read"}
    write = copy.deepcopy(common)
    write["direction"] = {"const": "write"}
    write["phase_order"] = {
        "enum": ["aw_before_w", "same_cycle", "w_before_aw", "unknown"]
    }
    return {
        "oneOf": [
            _closed(read, required),
            _closed(write, (*required, "phase_order")),
        ]
    }


def _source_line_schema() -> Schema:
    return _closed(
        {
            "line": _integer(minimum=1),
            "text": {"type": "string"},
            "active": {"type": "boolean"},
        },
        ("line", "text", "active"),
    )


def _source_path_schema() -> Schema:
    return _closed(
        {
            "file": _string(),
            "line": _integer(minimum=1),
            "source_context": _array(_ref("nonSamplingSourceLine")),
            "signal_path": _array(_string(), min_items=1),
        },
        ("file", "line", "source_context", "signal_path"),
    )


def _trace_hop_schema() -> Schema:
    return _closed(
        {
            "index": _integer(),
            "chain_id": _string(),
            "signal": _string(),
            "time": {"type": "string"},
            "active_time": {"type": "string"},
            "value": {"type": "string"},
            "relation": _string(),
            "file": _string(),
            "line": _integer(minimum=1),
            "source_context": _array(_ref("nonSamplingSourceLine")),
            "signal_path": _array(_string(), min_items=1),
        },
        (
            "index",
            "chain_id",
            "signal",
            "time",
            "active_time",
            "value",
            "relation",
            "file",
            "line",
            "source_context",
            "signal_path",
        ),
    )


def _stream_config_schema() -> Schema:
    signal_map = _dynamic_map(
        _string(),
        "Caller-defined stream alias to a non-empty waveform signal path.",
    )
    signal_map["minProperties"] = 1
    alias = _string()
    packet_fields = _dynamic_map(
        alias,
        "Caller-defined packet field to a configured stream alias.",
    )
    packet_fields["minProperties"] = 1
    beat_fields = _dynamic_map(
        alias,
        "Caller-defined beat field to a configured stream alias.",
    )
    beat_fields["minProperties"] = 1
    properties = {
        "name": _string(),
        "signals": signal_map,
        "clock": alias,
        "edge": {"enum": ["posedge", "negedge", "dual"]},
        "sample_point": {"enum": ["before", "after"]},
        "reset": _ref("reset"),
        "vld": alias,
        "rdy": alias,
        "bp": alias,
        "sop": alias,
        "eop": alias,
        "data": alias,
        "packet_stable_fields": packet_fields,
        "beat_fields": beat_fields,
        "channel_id": alias,
        "channel_id_valid": {"enum": ["every_beat", "sop", "eop"]},
        "allow_interleaving": {"type": "boolean"},
        "description": _string(),
    }
    return _edge_closed(
        properties,
        (
            "name",
            "signals",
            "clock",
            "edge",
            "vld",
            "channel_id_valid",
            "allow_interleaving",
        ),
    )


def _stream_issue_schema(*, include_stream: bool) -> Schema:
    properties = {
        "severity": {"enum": ["ERROR", "WARNING", "INFO"]},
        "code": _string(),
        "message": _string(),
    }
    required = ["severity", "code", "message"]
    if include_stream:
        properties["stream"] = _string()
        required.append("stream")
    return _closed(properties, required)


def _stream_static_validation_schema(*, include_stream: bool) -> Schema:
    signal = _closed(
        {
            "alias": _string(),
            "requested_path": _string(),
            "resolved_path": _string(),
            "width": _integer(),
            "status": {"enum": ["ok", "signal_not_found"]},
        },
        ("alias", "requested_path", "status"),
    )
    signal["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {"status": {"const": "ok"}},
                    "required": ["status", "resolved_path", "width"],
                },
                {
                    "properties": {
                        "status": {"const": "signal_not_found"}
                    },
                    "required": ["status"],
                    **_forbid("resolved_path", "width"),
                },
            ]
        }
    ]
    properties = {
        "status": {"enum": ["ok", "error"]},
        "signals": _array(signal),
        "sampling": _closed(
            {
                "clock": _string(),
                "edge": {"enum": ["posedge", "negedge", "dual"]},
                "sample_point": {
                    "enum": [None, "before", "after"]
                },
            },
            ("clock", "edge", "sample_point"),
        ),
        "packet_rules": _closed(
            {
                "packet_enabled": {"type": "boolean"},
                "channel_id_valid": {
                    "enum": ["every_beat", "sop", "eop"]
                },
                "allow_interleaving": {"type": "boolean"},
            },
            (
                "packet_enabled",
                "channel_id_valid",
                "allow_interleaving",
            ),
        ),
    }
    required = ["status", "signals", "sampling", "packet_rules"]
    if include_stream:
        properties["stream"] = _string()
        required.append("stream")
    return _closed(properties, required)


def _stream_field_map_schema() -> Schema:
    return _dynamic_map(
        _ref("logicValue"),
        "Caller-defined stream field to a canonical logic-value object.",
    )


def _stream_row_schema() -> Schema:
    return _closed(
        {
            "cycle": _integer(),
            "time": _string(),
            "vld": {"type": "boolean"},
            "rdy": {"type": "boolean"},
            "bp": {"type": "boolean"},
            "sop": {"type": "boolean"},
            "eop": {"type": "boolean"},
            "transfer": {"type": "boolean"},
            "stall": {"type": "boolean"},
            "stall_reason": _string(),
            "packet_index": _integer(),
            "beat_index": _integer(),
            "fields": _ref("nonSamplingStreamFieldMap"),
            "packet_stable_fields": _ref("nonSamplingStreamFieldMap"),
            "channel_id": _ref("logicValue"),
        },
        (
            "cycle",
            "time",
            "vld",
            "rdy",
            "bp",
            "sop",
            "eop",
            "transfer",
            "stall",
            "beat_index",
            "fields",
        ),
    )


def _stream_stall_schema() -> Schema:
    return _closed(
        {
            "start_cycle": _integer(),
            "end_cycle": _integer(),
            "start_time": _string(),
            "end_time": _string(),
            "cycles": _integer(minimum=1),
            "reason": _string(),
        },
        (
            "start_cycle",
            "end_cycle",
            "start_time",
            "end_time",
            "cycles",
            "reason",
        ),
    )


def _stream_beat_schema() -> Schema:
    return _closed(
        {
            "cycle": _integer(),
            "time": _string(),
            "beat_index": _integer(),
            "fields": _ref("nonSamplingStreamFieldMap"),
        },
        ("cycle", "time", "beat_index", "fields"),
    )


def _stream_beat_preview_schema() -> Schema:
    return _closed(
        {
            "head": _array(_ref("nonSamplingStreamBeat")),
            "tail": _array(_ref("nonSamplingStreamBeat")),
            **_completeness_properties(),
        },
        ("head", "tail", *_completeness_required()),
    )


def _stream_packet_schema() -> Schema:
    mismatch = _closed(
        {
            "field": _string(),
            "cycle": _integer(),
            "time": _string(),
            "expected": _ref("logicValue"),
            "actual": _ref("logicValue"),
        },
        ("field", "cycle", "time", "expected", "actual"),
    )
    return _closed(
        {
            "packet_index": _integer(),
            "start_cycle": _integer(),
            "end_cycle": _integer(),
            "start_time": _string(),
            "end_time": _string(),
            "beat_count": _integer(),
            "partial_begin": {"type": "boolean"},
            "partial_end": {"type": "boolean"},
            "packet_stable_fields": _ref("nonSamplingStreamFieldMap"),
            "packet_stable_mismatches": _array(mismatch),
            "beat_fields_preview": _ref("nonSamplingStreamBeatPreview"),
            "first_fields": _ref("nonSamplingStreamFieldMap"),
            "last_fields": _ref("nonSamplingStreamFieldMap"),
            "channel_id": _ref("logicValue"),
        },
        (
            "packet_index",
            "start_cycle",
            "end_cycle",
            "start_time",
            "end_time",
            "beat_count",
            "partial_begin",
            "partial_end",
            "packet_stable_fields",
            "packet_stable_mismatches",
            "beat_fields_preview",
            "first_fields",
            "last_fields",
        ),
    )


def _stream_filter_schema(*, packet: bool) -> Schema:
    literal = _string()
    exact = _closed(
        {
            "mode": {"const": "exact"},
            "values": _array(literal, min_items=1),
        },
        ("mode", "values"),
    )
    value_range = _closed(
        {
            "mode": {"const": "range"},
            "begin": literal,
            "end": literal,
        },
        ("mode", "begin", "end"),
    )
    mask = _closed(
        {
            "mode": {"const": "mask"},
            "value": literal,
            "mask": literal,
        },
        ("mode", "value", "mask"),
    )
    fields = _dynamic_map(
        {"oneOf": [exact, value_range, mask]},
        "Caller-defined stream field to an exact/range/mask filter.",
    )
    fields["minProperties"] = 1
    properties = {"fields": fields}
    required = ["fields"]
    if packet:
        properties["position"] = {"enum": ["sop", "eop"]}
        required.append("position")
    return _closed(properties, required)


def _stream_summary_properties() -> dict[str, Schema]:
    return {
        "stream": _string(),
        "sampling_mode": {"const": "clock_edge"},
        "clock": _string(),
        "edge": {"enum": ["posedge", "negedge", "dual"]},
        "sample_point": {"enum": ["before", "after"]},
        "sample_time_semantics": {"const": "time is sample_time"},
        "handshake": {"enum": ["vld", "vld/rdy", "vld/bp", "vld/rdy/bp"]},
        "packet_enabled": {"type": "boolean"},
        "clock_edges": _integer(),
        "vld_cycles": _integer(),
        "transfer_count": _integer(),
        "stall_cycles": _integer(),
        "stall_windows": _integer(),
        "complete_packet_count": _integer(),
        "partial_packet_count": _integer(),
        "packet_count_status": {
            "enum": ["exact", "not_configured", "ambiguous"]
        },
        "control_xz_count": _integer(),
        "data_xz_count": _integer(),
        "ready_bp_conflict_count": _integer(),
        "packet_stable_mismatch_count": _integer(),
        **_completeness_properties(),
        "requested_range": _ref("nonSamplingTimeRange"),
        "scanned_range": _ref("nonSamplingNullableTimeRange"),
        "first_transfer_time": _string(),
        "last_transfer_time": _string(),
        "first_stall_time": _string(),
        "last_stall_time": _string(),
        **_value_width_properties(),
    }


def _stream_summary_schema(
    extra_properties: Mapping[str, Schema] = (),
    extra_required: Iterable[str] = (),
    *,
    include_completeness: bool = True,
) -> Schema:
    properties = _stream_summary_properties()
    required = [
        "stream",
        "sampling_mode",
        "clock",
        "edge",
        "sample_time_semantics",
        "handshake",
        "packet_enabled",
        "clock_edges",
        "vld_cycles",
        "transfer_count",
        "stall_cycles",
        "stall_windows",
        "complete_packet_count",
        "partial_packet_count",
        "packet_count_status",
        "control_xz_count",
        "data_xz_count",
        "ready_bp_conflict_count",
        "packet_stable_mismatch_count",
        "requested_range",
        "scanned_range",
    ]
    if include_completeness:
        required.extend(_completeness_required())
    else:
        for name in _completeness_required():
            properties.pop(name)
    properties.update(copy.deepcopy(dict(extra_properties)))
    required.extend(extra_required)
    return _edge_closed(properties, required)


def _definitions() -> dict[str, Schema]:
    return {
        "nonSamplingTimeRange": _closed(
            {"begin": _string(), "end": _string()},
            ("begin", "end"),
        ),
        "nonSamplingNullableTimeRange": _closed(
            {
                "begin": _nullable(_string()),
                "end": _nullable(_string()),
            },
            ("begin", "end"),
        ),
        "nonSamplingApbConfig": _apb_config_schema(),
        "nonSamplingEventConfig": _event_config_schema(),
        "nonSamplingAxiConfig": _axi_config_schema(),
        "nonSamplingAxiValidation": _axi_validation_schema(),
        "nonSamplingApbTransaction": _apb_transaction_schema(
            include_type=False
        ),
        "nonSamplingApbWindowTransaction": _apb_transaction_schema(
            include_type=True
        ),
        "nonSamplingAxiTransaction": _axi_transaction_schema(),
        "nonSamplingMatchedAxiTransaction": _axi_transaction_schema(
            require_match_time=True
        ),
        "nonSamplingAxiPendingTransaction": (
            _axi_pending_transaction_schema()
        ),
        "nonSamplingExprAst": _expr_ast_schema(),
        "nonSamplingNpiExprAst": _npi_expr_ast_schema(),
        "nonSamplingSourceLine": _source_line_schema(),
        "nonSamplingSourcePath": _source_path_schema(),
        "nonSamplingTraceHop": _trace_hop_schema(),
        "nonSamplingActiveChainDepthFrontier": (
            _active_chain_depth_frontier_schema()
        ),
        "nonSamplingActiveChainAmbiguity": (
            _active_chain_ambiguity_schema()
        ),
        "nonSamplingXOriginQuery": _x_origin_point_schema("query_time"),
        "nonSamplingXOriginCurrent": _x_origin_point_schema(
            "x_onset_time"
        ),
        "nonSamplingXOriginHop": _x_origin_hop_schema(),
        "nonSamplingXOriginPending": _x_origin_pending_schema(),
        "nonSamplingXOriginChain": _x_origin_chain_schema(),
        "nonSamplingXOriginDepthFrontier": _closed(
            {
                "signal": _string(),
                "continue_time": _string(),
                "value": _ref("logicValue"),
                "x_mask": _string(),
                "chain_id": _string(),
                "stopped_after_depth": _integer(minimum=1),
            },
            (
                "signal",
                "continue_time",
                "value",
                "x_mask",
                "chain_id",
                "stopped_after_depth",
            ),
        ),
        "nonSamplingStreamConfig": _stream_config_schema(),
        "nonSamplingStreamCompactConfig": (
            _stream_compact_config_schema()
        ),
        "nonSamplingStreamIssue": _stream_issue_schema(
            include_stream=False
        ),
        "nonSamplingStreamLoadIssue": _stream_issue_schema(
            include_stream=True
        ),
        "nonSamplingStreamValidation": (
            _stream_static_validation_schema(include_stream=False)
        ),
        "nonSamplingStreamLoadValidation": (
            _stream_static_validation_schema(include_stream=True)
        ),
        "nonSamplingStreamFieldMap": _stream_field_map_schema(),
        "nonSamplingStreamRow": _stream_row_schema(),
        "nonSamplingStreamStall": _stream_stall_schema(),
        "nonSamplingStreamBeat": _stream_beat_schema(),
        "nonSamplingStreamBeatPreview": (
            _stream_beat_preview_schema()
        ),
        "nonSamplingStreamPacket": _stream_packet_schema(),
        "nonSamplingStreamBeatFilter": _stream_filter_schema(
            packet=False
        ),
        "nonSamplingStreamPacketFilter": _stream_filter_schema(
            packet=True
        ),
        "nonSamplingStreamDynamicValidation": (
            _stream_summary_schema(include_completeness=False)
        ),
    }


def _protocol_statistics_filter_schema(*, axi: bool) -> Schema:
    base = {
        "direction": {"enum": ["all", "read", "write"]},
    }
    if axi:
        base["ids"] = _array(_string(), min_items=1)
    absent = _closed(base, ("direction",))
    exact_props = copy.deepcopy(base)
    exact_props["address"] = _closed(
        {
            "mode": {"const": "exact"},
            "values": _array(_string(), min_items=1),
        },
        ("mode", "values"),
    )
    value_range_props = copy.deepcopy(base)
    value_range_props["address"] = _closed(
        {
            "mode": {"const": "range"},
            "begin": _string(),
            "end": _string(),
        },
        ("mode", "begin", "end"),
    )
    mask_props = copy.deepcopy(base)
    mask_props["address"] = _closed(
        {
            "mode": {"const": "mask"},
            "value": _string(),
            "mask": _string(),
        },
        ("mode", "value", "mask"),
    )
    return {
        "oneOf": [
            absent,
            _closed(exact_props, ("direction", "address")),
            _closed(value_range_props, ("direction", "address")),
            _closed(mask_props, ("direction", "address")),
        ]
    }


def _protocol_statistics_contract(action: str, *, axi: bool) -> tuple[NonSamplingSuccessVariant, ...]:
    summary = _summary(
        {
            "name": _string(),
            "scanned_transaction_count": _integer(),
            "matched_transaction_count": _integer(),
            "matched_read_count": _integer(),
            "matched_write_count": _integer(),
            "unresolved_transaction_count": _integer(),
            "filter_applied": {"type": "boolean"},
            "analysis_quality": {"enum": ["complete", "ambiguous"]},
            "full_scan_count": _integer(),
            **_value_width_properties(),
        },
        (
            "name",
            "scanned_transaction_count",
            "matched_transaction_count",
            "matched_read_count",
            "matched_write_count",
            "unresolved_transaction_count",
            "filter_applied",
            "analysis_quality",
            "full_scan_count",
        ),
        complete=True,
    )
    data = _closed(
        {
            "filter": _protocol_statistics_filter_schema(axi=axi),
            "notes": _closed(
                {"unresolved_transaction_count": _string()},
                ("unresolved_transaction_count",),
            ),
        },
        ("filter", "notes"),
    )
    return (_variant("statistics", summary, data),)


def _apb_config_list_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "list",
            _summary({"count": _integer()}, ("count",)),
            _closed(
                {"configs": _array(_ref("nonSamplingApbConfig"))},
                ("configs",),
            ),
        ),
        _variant(
            "named",
            _summary(
                {"name": _string(), "status": {"const": "found"}},
                ("name", "status"),
            ),
            _closed(
                {"config": _ref("nonSamplingApbConfig")},
                ("config",),
            ),
        ),
    )


def _axi_config_list_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "list",
            _summary({"count": _integer()}, ("count",)),
            _closed(
                {"configs": _array(_ref("nonSamplingAxiConfig"))},
                ("configs",),
            ),
        ),
        _variant(
            "named",
            _summary(
                {"name": _string(), "status": {"const": "found"}},
                ("name", "status"),
            ),
            _closed(
                {"config": _ref("nonSamplingAxiConfig")},
                ("config",),
            ),
        ),
    )


def _axi_config_load_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "loaded",
            _summary(
                {"name": _string(), "status": {"const": "loaded"}},
                ("name", "status"),
            ),
            _closed(
                {
                    "config": _ref("nonSamplingAxiConfig"),
                    "validation": _ref("nonSamplingAxiValidation"),
                    "recommended_actions": _recommended_actions(),
                },
                ("config", "validation", "recommended_actions"),
            ),
        ),
    )


def _protocol_query_value_filter(*, allow_mask: bool) -> Schema:
    exact = _closed(
        {
            "mode": {"const": "exact"},
            "values": _array(_string(), min_items=1),
        },
        ("mode", "values"),
    )
    value_range = _closed(
        {
            "mode": {"const": "range"},
            "begin": _string(),
            "end": _string(),
        },
        ("mode", "begin", "end"),
    )
    branches = [exact, value_range]
    if allow_mask:
        branches.append(
            _closed(
                {
                    "mode": {"const": "mask"},
                    "value": _string(),
                    "mask": _string(),
                },
                ("mode", "value", "mask"),
            )
        )
    return {"oneOf": branches}


def _protocol_query_echo_filter(*, axi: bool) -> Schema:
    properties: dict[str, Schema] = {
        "direction": {
            "enum": ["read", "write"] if axi
            else ["all", "read", "write"]
        },
        "address": _protocol_query_value_filter(allow_mask=True),
    }
    if axi:
        properties["id"] = _protocol_query_value_filter(
            allow_mask=False
        )
        properties["time_range"] = _closed(
            {"begin": _string(), "end": _string()},
            ("begin", "end"),
        )
    return _closed(properties, ("direction",))


def _apb_query_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    filter_schema = _protocol_query_echo_filter(axi=False)
    common = {
        "name": _string(),
        "direction": {"enum": ["all", "read", "write"]},
    }
    count = _variant(
        "count",
        _summary(
            {**common, "query_mode": {"const": "count"}},
            ("name", "direction", "query_mode"),
            complete=True,
        ),
        _closed({"filter": filter_schema}, ("filter",)),
    )
    listed = _variant(
        "list",
        _summary(
            {**common, "query_mode": {"const": "list"}},
            ("name", "direction", "query_mode"),
            complete=True,
        ),
        _closed(
            {
                "filter": filter_schema,
                "transactions": _array(
                    _ref("nonSamplingApbTransaction")
                )
            },
            ("filter", "transactions"),
        ),
    )
    single_found = _variant(
        "single_found",
        _summary(
            {
                **common,
                "query_mode": {"enum": ["index", "last"]},
                "found": {"const": True},
            },
            ("name", "direction", "query_mode", "found"),
            complete=True,
        ),
        _closed(
            {
                "filter": filter_schema,
                "transaction": _ref("nonSamplingApbTransaction"),
            },
            ("filter", "transaction"),
        ),
    )
    single_not_found = _variant(
        "single_not_found",
        _summary(
            {
                **common,
                "query_mode": {"enum": ["index", "last"]},
                "found": {"const": False},
            },
            ("name", "direction", "query_mode", "found"),
            complete=True,
        ),
        _closed({"filter": filter_schema}, ("filter",)),
    )
    return count, listed, single_found, single_not_found


def _axi_query_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    filter_schema = _protocol_query_echo_filter(axi=True)
    data_scope = {
        "enum": [
            "none",
            "first_beat_each_with_first_transaction_full",
            "all_returned_transactions_full",
        ]
    }
    common = {
        "name": _string(),
        "direction": {"enum": ["read", "write"]},
        "data_scope": data_scope,
        "data_hint": _string(),
    }
    handshake_match = _closed(
        {
            "channel": {"enum": ["aw", "w", "b", "ar", "r"]},
            "handshake_time": _string(),
            "direction": {"enum": ["write", "read"]},
            "beat_index": _integer(minimum=1),
        },
        ("channel", "handshake_time"),
    )
    handshake_found = _variant(
        "handshake_found",
        _summary(
            {
                "name": _string(),
                "query_mode": {"const": "handshake"},
                "found": {"const": True},
                "data_scope": data_scope,
                "data_hint": _string(),
            },
            ("name", "query_mode", "found", "data_scope"),
            complete=True,
        ),
        _closed(
            {
                "match": handshake_match,
                "transaction": _ref("nonSamplingAxiTransaction"),
            },
            ("match", "transaction"),
        ),
    )
    handshake_not_found = _variant(
        "handshake_not_found",
        _summary(
            {
                "name": _string(),
                "query_mode": {"const": "handshake"},
                "found": {"const": False},
                "data_scope": {"const": "none"},
            },
            ("name", "query_mode", "found", "data_scope"),
            complete=True,
        ),
        _closed(
            {
                "match": _closed(
                    {
                        "channel": {
                            "enum": ["aw", "w", "b", "ar", "r"]
                        },
                        "handshake_time": _string(),
                    },
                    ("channel", "handshake_time"),
                )
            },
            ("match",),
        ),
    )
    count = _variant(
        "transaction_count",
        _summary(
            {
                **common,
                "query_mode": {"const": "count"},
                "data_scope": {"const": "none"},
            },
            ("name", "direction", "query_mode", "data_scope"),
            complete=True,
        ),
        _closed({"filter": filter_schema}, ("filter",)),
    )
    listed = _variant(
        "transaction_list",
        _summary(
            {**common, "query_mode": {"const": "list"}},
            ("name", "direction", "query_mode", "data_scope"),
            complete=True,
        ),
        _closed(
            {
                "filter": filter_schema,
                "transactions": _array(
                    _ref("nonSamplingAxiTransaction")
                )
            },
            ("filter", "transactions"),
        ),
    )
    single_found = _variant(
        "transaction_found",
        _summary(
            {
                **common,
                "query_mode": {"enum": ["index", "last"]},
                "found": {"const": True},
            },
            ("name", "direction", "query_mode", "found", "data_scope"),
            complete=True,
        ),
        _closed(
            {
                "filter": filter_schema,
                "transaction": _ref("nonSamplingAxiTransaction"),
            },
            ("filter", "transaction"),
        ),
    )
    single_not_found = _variant(
        "transaction_not_found",
        _summary(
            {
                **common,
                "query_mode": {"enum": ["index", "last"]},
                "data_scope": {"const": "none"},
                "found": {"const": False},
            },
            (
                "name", "direction", "query_mode", "found",
                "data_scope",
            ),
            complete=True,
        ),
        _closed({"filter": filter_schema}, ("filter",)),
    )
    return (
        handshake_found,
        handshake_not_found,
        count,
        listed,
        single_found,
        single_not_found,
    )


def _transaction_cursor_contract(*, axi: bool) -> tuple[NonSamplingSuccessVariant, ...]:
    common = {
        "name": _string(),
        "op": {"enum": ["begin", "next", "prev", "last"]},
        "direction": {"enum": ["all", "read", "write"]},
        "found": {"type": "boolean"},
        "index": {"type": ["integer", "null"], "minimum": 1},
        "index_base": {"const": 1},
        "at_begin": {"type": "boolean"},
        "at_end": {"type": "boolean"},
        **_value_width_properties(),
    }
    required = (
        "name",
        "op",
        "direction",
        "found",
        "index",
        "index_base",
        "at_begin",
        "at_end",
    )
    found_props = copy.deepcopy(common)
    found_props["found"] = {"const": True}
    found_props["index"] = _integer(minimum=1)
    missing_props = copy.deepcopy(common)
    missing_props["found"] = {"const": False}
    missing_props["index"] = {"type": "null"}
    transaction = (
        _ref("nonSamplingAxiTransaction")
        if axi
        else _ref("nonSamplingApbTransaction")
    )
    return (
        _variant(
            "found",
            _summary(found_props, required, complete=True),
            _closed({"transaction": transaction}, ("transaction",)),
        ),
        _variant(
            "not_found",
            _summary(missing_props, required, complete=True),
            _closed({}),
        ),
    )


def _axi_analysis_common_summary() -> tuple[dict[str, Schema], tuple[str, ...]]:
    properties = {
        "name": _string(),
        "analysis": {"enum": ["latency", "osd", "pending"]},
        "direction": {"enum": ["all", "read", "write"]},
        "sample_count": _integer(),
        "full_scan_count": _integer(),
        "scanned_range": _ref("nonSamplingTimeRange"),
        "completed_read_count": _integer(),
        "completed_write_count": _integer(),
        "incomplete_read_count": _integer(),
        "incomplete_write_count": _integer(),
        "buffered_w_beat_count": _integer(),
        "buffered_w_burst_count": _integer(),
        "orphan_w_beat_count": _integer(),
        "orphan_b_count": _integer(),
        "orphan_r_beat_count": _integer(),
        "response_dependency_violation_count": _integer(),
        "channel_handshakes": _closed(
            {
                channel: _integer()
                for channel in ("aw", "w", "b", "ar", "r")
            },
            ("aw", "w", "b", "ar", "r"),
        ),
        **_value_width_properties(),
    }
    return properties, tuple(
        name for name in properties if name not in _value_width_properties()
    )


def _latency_stat_schema() -> Schema:
    return {
        "oneOf": [
            _closed(
                {
                    "samples": {"const": 0},
                    "status": {"const": "empty"},
                    **{
                        name: {"type": "null"}
                        for name in ("min", "max", "avg", "p50", "p95", "p99")
                    },
                },
                ("samples", "status", "min", "max", "avg", "p50", "p95", "p99"),
            ),
            _closed(
                {
                    "samples": _integer(minimum=1),
                    **{
                        name: _string()
                        for name in ("min", "max", "avg", "p50", "p95", "p99")
                    },
                },
                ("samples", "min", "max", "avg", "p50", "p95", "p99"),
            ),
        ]
    }


def _axi_analysis_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common, common_required = _axi_analysis_common_summary()
    latency_container = _closed(
        {
            "read": _latency_stat_schema(),
            "write": _latency_stat_schema(),
            "definitions": _closed(
                {"read": _string(), "write": _string()},
                ("read", "write"),
            ),
            "write_phase_order_counts": _closed(
                {
                    name: _integer()
                    for name in (
                        "aw_before_w",
                        "same_cycle",
                        "w_before_aw",
                        "unknown",
                    )
                },
                ("aw_before_w", "same_cycle", "w_before_aw", "unknown"),
            ),
        },
        ("read", "write", "definitions", "write_phase_order_counts"),
    )
    latency_fields = {
        **common,
        "analysis": {"const": "latency"},
        "samples": _integer(),
        **{
            name: _string()
            for name in ("min", "max", "avg", "p50", "p95", "p99")
        },
    }
    latency_required = (
        *common_required,
        "samples",
        "min",
        "max",
        "avg",
        "p50",
        "p95",
        "p99",
    )
    latency_nonempty = _variant(
        "latency_nonempty",
        _summary(latency_fields, latency_required, complete=True),
        _closed(
            {
                "latency": latency_container,
                "slowest": _ref("nonSamplingAxiTransaction"),
            },
            ("latency", "slowest"),
        ),
    )
    latency_empty_fields = {
        **common,
        "analysis": {"const": "latency"},
        "samples": {"const": 0},
        "status": {"const": "empty"},
        **{
            name: {"type": "null"}
            for name in ("min", "max", "avg", "p50", "p95", "p99")
        },
    }
    latency_empty = _variant(
        "latency_empty",
        _summary(
            latency_empty_fields,
            (
                *common_required,
                "samples",
                "status",
                "min",
                "max",
                "avg",
                "p50",
                "p95",
                "p99",
            ),
            complete=True,
        ),
        _closed({"latency": latency_container}, ("latency",)),
    )
    outstanding_stat = {
        "oneOf": [
            _closed(
                {
                    "samples": {"const": 0},
                    "status": {"const": "empty"},
                    "min": {"const": 0},
                    "max": {"const": 0},
                    "avg": {"type": "number"},
                },
                ("samples", "status", "min", "max", "avg"),
            ),
            _closed(
                {
                    "samples": _integer(minimum=1),
                    "min": _integer(),
                    "max": _integer(),
                    "avg": {"type": "number"},
                },
                ("samples", "min", "max", "avg"),
            ),
        ]
    }
    osd_fields = {
        **common,
        "analysis": {"const": "osd"},
        "samples": _integer(),
        "min": _integer(),
        "max": _integer(),
        "avg": {"type": "number"},
    }
    osd = _variant(
        "osd",
        _summary(
            osd_fields,
            (*common_required, "samples", "min", "max", "avg"),
            complete=True,
        ),
        _closed(
            {
                "osd": _closed(
                    {
                        "read": outstanding_stat,
                        "write": outstanding_stat,
                        "final_read": _integer(),
                        "final_write": _integer(),
                        "definitions": _closed(
                            {"read": _string(), "write": _string()},
                            ("read", "write"),
                        ),
                    },
                    (
                        "read",
                        "write",
                        "final_read",
                        "final_write",
                        "definitions",
                    ),
                )
            },
            ("osd",),
        ),
    )
    pending_fields = {**common, "analysis": {"const": "pending"}}
    pending = _variant(
        "pending",
        _summary(
            pending_fields,
            common_required,
            complete=True,
        ),
        _closed(
            {
                "pending_transactions": _array(
                    _ref("nonSamplingAxiPendingTransaction")
                )
            },
            ("pending_transactions",),
        ),
    )
    return latency_nonempty, latency_empty, osd, pending


def _axi_export_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    # output.path omission is converted to a generated non-empty prefix before
    # the branch, so the source's later preview block is currently unreachable.
    properties = {
        "name": _string(),
        "write_count": _integer(),
        "read_count": _integer(),
        "row_count": _integer(),
        "format": {"enum": ["tsv", "csv"]},
        "status": {"const": "written"},
        "output_written": {"const": True},
        "sample_count": _integer(),
        "full_scan_count": _integer(),
        "incomplete_write_count": _integer(),
        "incomplete_read_count": _integer(),
        "buffered_w_beat_count": _integer(),
        "buffered_w_burst_count": _integer(),
        "orphan_w_beat_count": _integer(),
        "orphan_b_count": _integer(),
        "orphan_r_beat_count": _integer(),
        "response_dependency_violation_count": _integer(),
        "requested_range": _ref("nonSamplingTimeRange"),
        "scanned_range": _ref("nonSamplingTimeRange"),
        "output": _closed(
            {
                "path": _string(),
                "write_path": _string(),
                "read_path": _string(),
                "meta_path": _string(),
                "file_format": {"enum": ["tsv", "csv"]},
            },
            (
                "path",
                "write_path",
                "read_path",
                "meta_path",
                "file_format",
            ),
        ),
        **_value_width_properties(),
    }
    required = tuple(
        name for name in properties if name not in _value_width_properties()
    )
    return (
        _variant(
            "written",
            _summary(properties, required, complete=True),
            _closed({}),
        ),
    )


def _apb_transfer_window_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "window",
            _summary(
                {
                    "name": _string(),
                    "begin": _string(),
                    "end": _string(),
                    **_value_width_properties(),
                },
                ("name", "begin", "end"),
                complete=True,
            ),
            _closed(
                {
                    "transactions": _array(
                        _ref("nonSamplingApbWindowTransaction")
                    )
                },
                ("transactions",),
            ),
        ),
    )


def _axi_diagnostics_schema() -> Schema:
    return _closed(
        {
            "full_scan_count": _integer(),
            "incomplete_write_count": _integer(),
            "incomplete_read_count": _integer(),
            "buffered_w_beat_count": _integer(),
            "buffered_w_burst_count": _integer(),
            "orphan_w_beat_count": _integer(),
            "orphan_b_count": _integer(),
            "orphan_r_beat_count": _integer(),
            "response_dependency_violation_count": _integer(),
        },
        (
            "full_scan_count",
            "incomplete_write_count",
            "incomplete_read_count",
            "buffered_w_beat_count",
            "buffered_w_burst_count",
            "orphan_w_beat_count",
            "orphan_b_count",
            "orphan_r_beat_count",
            "response_dependency_violation_count",
        ),
    )


def _axi_request_response_pair_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "window",
            _summary(
                {
                    "name": _string(),
                    "begin": _string(),
                    "end": _string(),
                    **_value_width_properties(),
                },
                ("name", "begin", "end"),
                complete=True,
            ),
            _closed(
                {
                    "pairing_rule": _closed(
                        {
                            "write_data": _string(),
                            "write_response": _string(),
                            "read_response": _string(),
                        },
                        (
                            "write_data",
                            "write_response",
                            "read_response",
                        ),
                    ),
                    "diagnostics": _axi_diagnostics_schema(),
                    "transactions": _array(
                        _ref("nonSamplingMatchedAxiTransaction")
                    ),
                },
                ("pairing_rule", "diagnostics", "transactions"),
            ),
        ),
    )


def _axi_latency_outlier_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    summary = _summary(
        {
            "name": _string(),
            "begin": _string(),
            "end": _string(),
            "candidate_count": _integer(),
            **_value_width_properties(),
        },
        ("name", "begin", "end", "candidate_count"),
        complete=True,
    )
    common = {
        "method": {"enum": ["top_n", "threshold"]},
        "classification": {
            "enum": ["slowest_ranking", "threshold_exceeded"]
        },
        "outliers": _array(_ref("nonSamplingMatchedAxiTransaction")),
    }
    top_n = copy.deepcopy(common)
    top_n["method"] = {"const": "top_n"}
    top_n["classification"] = {"const": "slowest_ranking"}
    top_n["top_n"] = _integer(minimum=1)
    threshold = copy.deepcopy(common)
    threshold["method"] = {"const": "threshold"}
    threshold["classification"] = {"const": "threshold_exceeded"}
    threshold["threshold"] = _string()
    return (
        _variant(
            "top_n",
            summary,
            _closed(
                top_n,
                ("method", "classification", "top_n", "outliers"),
            ),
        ),
        _variant(
            "threshold",
            summary,
            _closed(
                threshold,
                (
                    "method",
                    "classification",
                    "threshold",
                    "outliers",
                ),
            ),
        ),
    )


def _axi_outstanding_timeline_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common = {"time": _string()}
    both = _closed(
        {
            **common,
            "read": _integer(),
            "write": _integer(),
            "read_delta": _integer(minimum=None),
            "write_delta": _integer(minimum=None),
            "read_event": {
                "enum": ["ar_handshake", "rlast_handshake", "none"]
            },
            "write_event": {
                "enum": ["aw_handshake", "b_handshake", "none"]
            },
        },
        (
            "time",
            "read",
            "write",
            "read_delta",
            "write_delta",
            "read_event",
            "write_event",
        ),
    )
    read = _closed(
        {
            **common,
            "read": _integer(),
            "read_delta": _integer(minimum=None),
            "read_event": {
                "enum": ["ar_handshake", "rlast_handshake", "none"]
            },
        },
        ("time", "read", "read_delta", "read_event"),
    )
    write = _closed(
        {
            **common,
            "write": _integer(),
            "write_delta": _integer(minimum=None),
            "write_event": {
                "enum": ["aw_handshake", "b_handshake", "none"]
            },
        },
        ("time", "write", "write_delta", "write_event"),
    )
    change_points = {
        "oneOf": [
            _array(both, max_items=0),
            _array(both, min_items=1),
            _array(read, min_items=1),
            _array(write, min_items=1),
        ]
    }
    summary = _edge_closed(
        {
            "name": _string(),
            "sampling_mode": {"const": "clock_edge"},
            "clock": _string(),
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "sample_point": {"enum": ["before", "after"]},
            "sample_time_semantics": {"const": "time is sample_time"},
            "sample_count": _integer(),
            "peak_read": _integer(),
            "peak_write": _integer(),
            "peak_read_time": _nullable(_string()),
            "peak_write_time": _nullable(_string()),
            "first_nonzero_time": _nullable(_string()),
            "final_read": _nullable(_integer()),
            "final_write": _nullable(_integer()),
            "requested_range": _ref("nonSamplingTimeRange"),
            **_completeness_properties(),
        },
        (
            "name",
            "sampling_mode",
            "clock",
            "edge",
            "sample_time_semantics",
            "sample_count",
            "peak_read",
            "peak_write",
            "peak_read_time",
            "peak_write_time",
            "first_nonzero_time",
            "final_read",
            "final_write",
            "requested_range",
            *_completeness_required(),
        ),
    )
    return (
        _variant(
            "timeline",
            summary,
            _closed({"change_points": change_points}, ("change_points",)),
        ),
    )


def _axi_channel_stall_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    finding = _closed(
        {
            "type": {"const": "long_stall"},
            "severity": {"const": "warning"},
            "begin": _string(),
            "end": _string(),
            "cycles": _integer(minimum=1),
            "open_at_window_end": {"type": "boolean"},
        },
        ("type", "severity", "begin", "end", "cycles"),
    )
    summary = _edge_closed(
        {
            "name": _string(),
            "channel": {"enum": ["aw", "w", "b", "ar", "r"]},
            "sampling_mode": {"const": "clock_edge"},
            "clock": _string(),
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "sample_point": {"enum": ["before", "after"]},
            "sample_time_semantics": {"const": "time is sample_time"},
            "sample_count": _integer(),
            "transfer_count": _integer(),
            "max_stall_cycles": _integer(),
            "ready_without_valid_cycles": _integer(),
            "first_activity_time": _nullable(_string()),
            "scanned_range": _ref("nonSamplingTimeRange"),
            **_completeness_properties(),
        },
        (
            "name",
            "channel",
            "sampling_mode",
            "clock",
            "edge",
            "sample_time_semantics",
            "sample_count",
            "transfer_count",
            "max_stall_cycles",
            "ready_without_valid_cycles",
            "first_activity_time",
            "scanned_range",
            *_completeness_required(),
        ),
    )
    return (
        _variant(
            "stall",
            summary,
            _closed({"findings": _array(finding)}, ("findings",)),
        ),
    )


def _event_config_schema() -> Schema:
    field = _closed(
        {
            "signal": _string(),
            "left": _integer(),
            "right": _integer(),
        },
        ("signal", "left", "right"),
    )
    properties = {
        "name": _string(),
        "clock": _string(),
        "reset": _ref("reset"),
        "edge": {"enum": ["posedge", "negedge", "dual"]},
        "sample_point": {"enum": ["before", "after"]},
        "signals": {
            **_dynamic_map(
                _string(),
                "Event alias to a non-empty waveform signal path.",
            ),
            "minProperties": 1,
        },
        "fields": _dynamic_map(
            field,
            "Event field name to a strict alias/slice definition.",
        ),
    }
    schema = _closed(
        properties,
        ("name", "clock", "edge", "signals", "fields"),
    )
    return schema


def _apb_config_load_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "loaded",
            _summary(
                {"name": _string(), "status": {"const": "loaded"}},
                ("name", "status"),
            ),
            _closed(
                {
                    "config": _ref("nonSamplingApbConfig"),
                    "recommended_actions": _recommended_actions(),
                },
                ("config", "recommended_actions"),
            ),
        ),
    )


def _event_config_load_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "loaded",
            _summary({"status": {"const": "loaded"}}, ("status",)),
            _closed(
                {"config": _ref("nonSamplingEventConfig")},
                ("config",),
            ),
        ),
    )


def _event_config_list_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "list",
            _summary({}, (), complete=True),
            _closed({"events": _array(_string())}, ("events",)),
        ),
        _variant(
            "named",
            _summary({"status": {"const": "found"}}, ("status",)),
            _closed(
                {"config": _ref("nonSamplingEventConfig")},
                ("config",),
            ),
        ),
    )


def _list_add_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "added",
            _summary(
                {
                    "name": _string(),
                    "signal": _string(),
                    "status": {"const": "added"},
                    "added": {"const": True},
                },
                ("name", "signal", "status", "added"),
            ),
            _closed({}),
        ),
    )


def _list_create_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "created",
            _summary(
                {
                    "name": _string(),
                    "status": {"const": "created"},
                    "created": {"const": True},
                    "signal_count": _integer(),
                },
                ("name", "status", "created", "signal_count"),
            ),
            _closed({"signals": _array(_string())}, ("signals",)),
        ),
    )


def _list_load_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    signal_validation = _closed(
        {
            "signal": _string(),
            "status": {"const": "ok"},
        },
        ("signal", "status"),
    )
    list_validation = _closed(
        {
            "name": _string(),
            "status": {"const": "ok"},
            "signals": _array(signal_validation),
        },
        ("name", "status", "signals"),
    )
    return (
        _variant(
            "loaded",
            _summary(
                {
                    "loaded": _integer(minimum=1),
                    "mode": {"enum": ["replace", "append"]},
                },
                ("loaded", "mode"),
            ),
            _closed(
                {
                    "lists": _array(_string()),
                    "validation": _array(list_validation),
                    "recommended_actions": _recommended_actions(),
                },
                ("lists", "validation", "recommended_actions"),
            ),
        ),
    )


def _list_delete_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "deleted",
            _summary(
                {
                    "name": _string(),
                    "deleted": {"const": True},
                    "removed": _string(),
                },
                ("name", "deleted", "removed"),
            ),
            _closed({}),
        ),
    )


def _list_show_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    item = _closed(
        {"index": _integer(minimum=1), "signal": _string()},
        ("index", "signal"),
    )
    return (
        _variant(
            "shown",
            _summary(
                {"name": _string(), "signal_count": _integer()},
                ("name", "signal_count"),
            ),
            _closed({"signals": _array(item)}, ("signals",)),
        ),
    )


def _list_validate_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    ok_item = _closed(
        {"signal": _string(), "status": {"const": "ok"}},
        ("signal", "status"),
    )
    checked_item = _closed(
        {
            "signal": _string(),
            "status": {"enum": ["ok", "not_found"]},
        },
        ("signal", "status"),
    )
    not_found_item = _closed(
        {"signal": _string(), "status": {"const": "not_found"}},
        ("signal", "status"),
    )
    failed_signals = _array(checked_item, min_items=1)
    failed_signals["contains"] = not_found_item
    return (
        _variant(
            "all_found",
            _summary(
                {"name": _string(), "all_found": {"const": True}},
                ("name", "all_found"),
            ),
            _closed({"signals": _array(ok_item)}, ("signals",)),
        ),
        _variant(
            "not_all_found",
            _summary(
                {"name": _string(), "all_found": {"const": False}},
                ("name", "all_found"),
            ),
            _closed({"signals": failed_signals}, ("signals",)),
        ),
    )


def _list_first_change_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    changed = _closed(
        {
            "signal": _string(),
            "before_time": _string(),
            "change_time": _string(),
            "before": _ref("logicValue"),
            "after": _ref("logicValue"),
        },
        (
            "signal",
            "before_time",
            "change_time",
            "before",
            "after",
        ),
    )
    return (
        _variant(
            "found",
            _summary(
                {
                    "name": _string(),
                    "diff_found": {"const": True},
                    "diff_time": _string(),
                    "changed_signal_count": _integer(minimum=1),
                    **_value_width_properties(),
                },
                (
                    "name",
                    "diff_found",
                    "diff_time",
                    "changed_signal_count",
                ),
            ),
            _closed(
                {
                    "changed_signals": _array(
                        changed,
                        min_items=1,
                    )
                },
                ("changed_signals",),
            ),
        ),
        _variant(
            "not_found",
            _summary(
                {
                    "name": _string(),
                    "diff_found": {"const": False},
                    "diff_time": {"type": "null"},
                    "changed_signal_count": {"const": 0},
                },
                (
                    "name",
                    "diff_found",
                    "diff_time",
                    "changed_signal_count",
                ),
            ),
            _closed(
                {
                    "changed_signals": _array(
                        changed,
                        max_items=0,
                    )
                },
                ("changed_signals",),
            ),
        ),
    )


def _list_export_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common = {
        "name": _string(),
        "row_count": _integer(),
        "format": {"const": "u64bin.v1"},
        "begin": _string(),
        "end": _string(),
    }
    preview = _summary(
        {
            **common,
            "row_count": {"const": 0},
            "status": {"const": "preview"},
            "output_written": {"const": False},
            "line_limit": _integer(minimum=None),
        },
        (
            "name",
            "row_count",
            "format",
            "status",
            "output_written",
            "line_limit",
            "begin",
            "end",
        ),
        complete=True,
    )
    written = _summary(
        {
            **common,
            "status": {"const": "written"},
            "output_written": {"const": True},
            "output": _closed(
                {"path": _string(), "manifest_path": _string()},
                ("path", "manifest_path"),
            ),
        },
        (
            "name",
            "row_count",
            "format",
            "status",
            "output_written",
            "begin",
            "end",
            "output",
        ),
        complete=True,
    )
    signal = _closed(
        {"index": _integer(), "signal": _string()},
        ("index", "signal"),
    )
    return (
        _variant(
            "preview",
            preview,
            _closed({"signals": _array(signal)}, ("signals",)),
        ),
        _variant("written", written, _closed({})),
    )


def _scope_list_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    kinds = (
        "module", "interface", "interface_array", "gen_scope",
        "internal_scope", "modport", "mpport", "port", "signal",
    )

    def hierarchy_item(kind: str) -> Schema:
        return _closed(
            {
                "name": _string(),
                "path": _string(),
                "kind": {"const": kind},
                "sources": {
                    **_array(
                        {"enum": ["wave", "design"]},
                        min_items=1,
                    ),
                    "uniqueItems": True,
                },
                "queryable": {"type": "boolean"},
                "traceable": {"type": "boolean"},
                "module_name": _nullable(_string()),
                "direction": {
                    "enum": ["input", "output", "inout", "interface"]
                },
                "width": _nullable(_integer(minimum=1)),
                "array_path": _string(),
            },
            ("name", "path", "kind", "sources", "queryable", "traceable"),
        )

    group_kinds = {
        "modules": "module",
        "interfaces": "interface",
        "interface_arrays": "interface_array",
        "gen_scopes": "gen_scope",
        "internal_scopes": "internal_scope",
        "modports": "modport",
        "mpports": "mpport",
        "ports": "port",
        "signals": "signal",
    }
    return (
        _variant(
            "listed",
            _summary(
                {
                    "source": {"enum": ["wave", "design", "merged"]},
                    "path": {"type": "string"},
                    "level": _integer(),
                    "kind": {"enum": ["all", *kinds]},
                    "include_patterns": _array(_string()),
                    "exclude_patterns": _array(_string()),
                    "visited_count": _integer(),
                    "scanned_row_count": _integer(),
                    "returned_module_count": _integer(),
                    "returned_port_count": _integer(),
                    "returned_signal_count": _integer(),
                    "total_module_count": _integer(),
                    "total_port_count": _integer(),
                    "total_signal_count": _integer(),
                },
                (
                    "source",
                    "path",
                    "level",
                    "kind",
                    "include_patterns",
                    "exclude_patterns",
                    "visited_count",
                    "scanned_row_count",
                    "returned_module_count",
                    "returned_port_count",
                    "returned_signal_count",
                    "total_module_count",
                    "total_port_count",
                    "total_signal_count",
                ),
                complete=True,
            ),
            _closed(
                {
                    group: _array(hierarchy_item(kind))
                    for group, kind in group_kinds.items()
                },
                tuple(group_kinds),
            ),
        ),
    )


def _cursor_metadata_schema() -> Schema:
    return _closed(
        {
            "note": _string(nonempty=False),
            "origin": _string(nonempty=False),
            "clock": _string(nonempty=False),
        },
        ("note", "origin", "clock"),
    )


def _cursor_set_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "set",
            _summary(
                {
                    "name": _string(),
                    "time": _string(),
                    "status": {"const": "set"},
                    "active": {"type": "boolean"},
                },
                ("name", "time", "status", "active"),
            ),
            _closed(
                {
                    "resolved_time": _closed(
                        {"source": _string(), "time": _string()},
                        ("source", "time"),
                    ),
                    "metadata": _cursor_metadata_schema(),
                },
                ("resolved_time", "metadata"),
            ),
        ),
    )


def _cursor_get_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "found",
            _summary(
                {
                    "name": _string(),
                    "time": _string(),
                    "status": {"const": "found"},
                },
                ("name", "time", "status"),
            ),
            _closed(
                {"metadata": _cursor_metadata_schema()},
                ("metadata",),
            ),
        ),
    )


def _cursor_list_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    cursor = _closed(
        {
            "name": _string(),
            "time": _string(),
            "note": _string(nonempty=False),
            "origin": _string(nonempty=False),
            "clock": _string(nonempty=False),
            "created_at": _integer(),
            "updated_at": _integer(),
        },
        (
            "name",
            "time",
            "note",
            "origin",
            "clock",
            "created_at",
            "updated_at",
        ),
    )
    return (
        _variant(
            "listed",
            _summary(
                {
                    "cursor_count": _integer(),
                    "active_cursor": _nullable(_string()),
                },
                ("cursor_count", "active_cursor"),
            ),
            _closed({"cursors": _array(cursor)}, ("cursors",)),
        ),
    )


def _cursor_delete_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "deleted",
            _summary(
                {
                    "status": {"const": "deleted"},
                    "name": _string(),
                    "deleted": {"const": True},
                },
                ("status", "name", "deleted"),
            ),
            _closed({}),
        ),
    )


def _cursor_use_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "active",
            _summary(
                {
                    "status": {"const": "active"},
                    "active_cursor": _string(),
                    "time": _string(),
                },
                ("status", "active_cursor", "time"),
            ),
            _closed(
                {"metadata": _cursor_metadata_schema()},
                ("metadata",),
            ),
        ),
    )


def _expr_normalize_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    direct_data = _closed(
        {
            "expr": _ref("nonSamplingExprAst"),
            "parsed": {"const": True},
            "confidence_reason": _string(),
        },
        ("expr", "parsed", "confidence_reason"),
    )
    local_data = _closed(
        {
            "expr": _ref("nonSamplingExprAst"),
            "confidence": {"const": "syntax_validated"},
            "confidence_reason": _string(),
        },
        ("expr", "confidence", "confidence_reason"),
    )
    assignment = _closed(
        {
            "kind": {
                "enum": [
                    "continuous_assignment",
                    "procedural_assignment",
                    "statement_only",
                ]
            },
            "lhs": _ref("nonSamplingNpiExprAst"),
            "rhs": _ref("nonSamplingNpiExprAst"),
            "source": _string(nonempty=False),
            "location": _closed(
                {
                    "file": _string(nonempty=False),
                    "line": _integer(),
                },
                ("file", "line"),
            ),
            "npi_type": _integer(),
            "rhs_signals": _array(_string()),
        },
        ("kind", "lhs", "rhs", "source", "location", "npi_type"),
    )
    signal_summary = _summary(
        {
            "signal": _string(),
            "source": {"const": "npi_trace_assignment"},
            "confidence": {
                "enum": ["high", "medium", "low", "unknown"]
            },
        },
        ("signal", "source", "confidence"),
    )
    return (
        _variant(
            "local_expression",
            _summary(
                {
                    "expr": _string(),
                    "source": {"const": "deterministic_syntax_parser"},
                    "confidence": {"const": "syntax_validated"},
                },
                ("expr", "source", "confidence"),
            ),
            local_data,
        ),
        _variant(
            "engine_expression",
            _summary(
                {
                    "status": {"const": "parsed"},
                    "source": {"const": "deterministic_syntax_parser"},
                    "confidence": {"const": "syntax_validated"},
                },
                ("status", "source", "confidence"),
            ),
            direct_data,
        ),
        _variant(
            "signal_assignment",
            signal_summary,
            _closed(
                {
                    "expr": _ref("nonSamplingNpiExprAst"),
                    "assignment": assignment,
                    "rhs_signals": _array(_string()),
                },
                ("expr", "assignment", "rhs_signals"),
            ),
        ),
        _variant(
            "signal_without_assignment",
            signal_summary,
            _closed(
                {
                    "expr": _closed({}),
                    "assignment": _closed({}),
                    "rhs_signals": _array(_string(), max_items=0),
                },
                ("expr", "assignment", "rhs_signals"),
            ),
        ),
    )


def _nwave_rc_generate_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "written",
            _summary(
                {
                    "written": {"const": True},
                    "config_path": _string(),
                    "output": _closed(
                        {"path": _string()},
                        ("path",),
                    ),
                    "valid": {"const": True},
                    "group_count": _integer(),
                    "signal_count": _integer(),
                },
                ("written", "config_path", "output", "valid"),
            ),
            _closed(
                {
                    "validation": _closed(
                        {
                            "signals": _integer(),
                            "times": _integer(),
                        },
                        ("signals", "times"),
                    ),
                    "rc_preview": _array(
                        _string(nonempty=False)
                    ),
                },
                ("validation", "rc_preview"),
            ),
        ),
    )


def _signal_anomaly_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    check = {
        "oneOf": [
            _closed(
                {"type": {"const": "unknown_xz"}},
                ("type",),
            ),
            _closed(
                {
                    "type": {"const": "glitch"},
                    "min_pulse_width": _string(),
                },
                ("type",),
            ),
            _closed(
                {
                    "type": {"const": "stuck"},
                    "min_duration": _string(),
                },
                ("type",),
            ),
        ]
    }
    finding = {
        "oneOf": [
            _closed(
                {
                    "type": {"const": "unknown_xz"},
                    "signal": _string(),
                    "severity": {"const": "warning"},
                    "time": _string(),
                    "value": _ref("logicValue"),
                },
                ("type", "signal", "severity", "time", "value"),
            ),
            _closed(
                {
                    "type": {"const": "glitch"},
                    "signal": _string(),
                    "severity": {"const": "info"},
                    "time": _string(),
                    "pulse_width": _string(),
                },
                (
                    "type",
                    "signal",
                    "severity",
                    "time",
                    "pulse_width",
                ),
            ),
            _closed(
                {
                    "type": {"const": "stuck"},
                    "signal": _string(),
                    "severity": {"const": "warning"},
                    "begin": _string(),
                    "end": _string(),
                    "duration": _string(),
                    "value": _ref("logicValue"),
                    "open_at_window_end": {"type": "boolean"},
                },
                (
                    "type",
                    "signal",
                    "severity",
                    "begin",
                    "end",
                    "duration",
                    "value",
                ),
            ),
        ]
    }
    scan_ok = _closed(
        {
            "signal": _string(),
            "status": {"const": "ok"},
            "analysis_complete": {"const": True},
            "change_row_count": _integer(),
            "finding_count": _integer(),
            "no_finding_reason": _nullable(_string()),
        },
        (
            "signal",
            "status",
            "analysis_complete",
            "change_row_count",
            "finding_count",
            "no_finding_reason",
        ),
    )
    scan_error = _closed(
        {
            "signal": _string(),
            "status": {"const": "error"},
            "analysis_complete": {"const": False},
            "message": _string(),
        },
        ("signal", "status", "analysis_complete", "message"),
    )
    return (
        _variant(
            "inspection",
            _summary(
                {
                    "signal_count": _integer(),
                    "checks": _array(check),
                    "glitch_threshold": _nullable(_string()),
                    "stuck_threshold": _nullable(_string()),
                    **_value_width_properties(),
                },
                (
                    "signal_count",
                    "checks",
                    "glitch_threshold",
                    "stuck_threshold",
                ),
                complete=True,
            ),
            _closed(
                {
                    "findings": _array(finding),
                    "scan_status": _array(
                        {"oneOf": [scan_ok, scan_error]}
                    ),
                },
                ("findings", "scan_status"),
            ),
        ),
    )


def _signal_changes_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    summary = _summary(
        {
            "signal": _string(),
            "actual_transition_count": _integer(),
            **_value_width_properties(),
        },
        ("signal", "actual_transition_count"),
        complete=True,
    )
    row = _closed(
        {"time": _string(), "value": _ref("logicValue")},
        ("time", "value"),
    )
    common = {
        "begin": _string(),
        "end": _string(),
        "includes_initial_value": {"type": "boolean"},
        "semantic_note": _string(),
    }
    populated = {
        **common,
        "includes_initial_value": {"const": True},
        "initial_value": _ref("logicValue"),
        "final_value": _ref("logicValue"),
        "first_change": _string(),
        "last_change": _string(),
    }
    return (
        _variant(
            "summary_empty",
            summary,
            _closed(
                {
                    **common,
                    "includes_initial_value": {"const": False},
                    "mode": {"const": "summary"},
                },
                (*common, "mode"),
            ),
        ),
        _variant(
            "summary_populated",
            summary,
            _closed(
                {
                    **populated,
                    "mode": {"const": "summary"},
                },
                (*populated, "mode"),
            ),
        ),
        _variant(
            "timeline_empty",
            summary,
            _closed(
                {
                    **common,
                    "includes_initial_value": {"const": False},
                    "mode": {"const": "timeline"},
                    "changes": _array(row, max_items=0),
                },
                (*common, "mode", "changes"),
            ),
        ),
        _variant(
            "timeline_populated",
            summary,
            _closed(
                {
                    **populated,
                    "mode": {"const": "timeline"},
                    "changes": _array(row, min_items=1),
                },
                (*populated, "mode", "changes"),
            ),
        ),
    )


def _signal_stability_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    row = _closed(
        {"time": _string(), "value": _ref("logicValue")},
        ("time", "value"),
    )
    base_data = {
        "signal": _string(),
        "begin": _string(),
        "end": _string(),
        "changes": _array(row),
        "includes_initial_value": {"type": "boolean"},
    }
    base_summary = {
        "stable": {"type": "boolean"},
        "change_row_count": _integer(),
        "actual_transition_count": _integer(),
        "scan_stopped_on_first_transition": {"type": "boolean"},
        **_value_width_properties(),
    }

    def stability_summary(
        properties: Mapping[str, Schema],
        required: Iterable[str],
        *,
        scan_complete: bool,
        truncation_scopes: list[str],
    ) -> Schema:
        schema = _summary(properties, required, complete=True)
        schema["properties"].update(
            {
                "scan_complete": {"const": scan_complete},
                "analysis_complete": {"const": True},
                "response_truncated": {"const": False},
                "truncation_scopes": {
                    "const": truncation_scopes,
                },
            }
        )
        return schema

    return (
        _variant(
            "stable_empty",
            stability_summary(
                {
                    **base_summary,
                    "stable": {"const": True},
                    "change_row_count": {"const": 0},
                    "actual_transition_count": {"const": 0},
                    "scan_stopped_on_first_transition": {"const": False},
                },
                (
                    "stable",
                    "change_row_count",
                    "actual_transition_count",
                    "scan_stopped_on_first_transition",
                ),
                scan_complete=True,
                truncation_scopes=[],
            ),
            _closed(
                {
                    **base_data,
                    "changes": _array(row, max_items=0),
                    "includes_initial_value": {"const": False},
                },
                tuple(base_data),
            ),
        ),
        _variant(
            "stable_populated",
            stability_summary(
                {
                    **base_summary,
                    "stable": {"const": True},
                    "actual_transition_count": {"const": 0},
                    "scan_stopped_on_first_transition": {"const": False},
                },
                (
                    "stable",
                    "change_row_count",
                    "actual_transition_count",
                    "scan_stopped_on_first_transition",
                ),
                scan_complete=True,
                truncation_scopes=[],
            ),
            _closed(
                {
                    **base_data,
                    "changes": _array(row, min_items=1),
                    "includes_initial_value": {"const": True},
                },
                tuple(base_data),
            ),
        ),
        _variant(
            "unstable",
            stability_summary(
                {
                    **base_summary,
                    "stable": {"const": False},
                    "actual_transition_count": {"const": 1},
                    "scan_stopped_on_first_transition": {"const": True},
                },
                (
                    "stable",
                    "change_row_count",
                    "actual_transition_count",
                    "scan_stopped_on_first_transition",
                ),
                scan_complete=False,
                truncation_scopes=["scan_after_first_transition"],
            ),
            _closed(
                {
                    **base_data,
                    "changes": _array(row, min_items=2),
                    "includes_initial_value": {"const": True},
                },
                tuple(base_data),
            ),
        ),
    )


def _signal_xz_verify_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common_summary = {
        "signal": _string(),
        "expected_state": {"enum": ["x", "z"]},
        "match_mode": {"enum": ["exact", "contains"]},
        "verdict": {"enum": ["pass", "fail"]},
        "always_matched": {"type": "boolean"},
        "checked_value_count": _integer(minimum=1),
        "stop_reason": {"enum": ["window_end", "first_mismatch"]},
        **_value_width_properties(),
    }
    common_data = {
        "time_range": _ref("nonSamplingTimeRange"),
        "initial_value": _ref("logicValue"),
        "sample_time_semantics": _string(),
    }
    mismatch = _closed(
        {
            "sample_time": _string(),
            "value": _ref("logicValue"),
        },
        ("sample_time", "value"),
    )
    return (
        _variant(
            "pass",
            _summary(
                {
                    **common_summary,
                    "verdict": {"const": "pass"},
                    "always_matched": {"const": True},
                    "stop_reason": {"const": "window_end"},
                },
                (
                    "signal",
                    "expected_state",
                    "match_mode",
                    "verdict",
                    "always_matched",
                    "checked_value_count",
                    "stop_reason",
                ),
                complete=True,
            ),
            _closed(
                {**common_data, "first_mismatch": {"type": "null"}},
                (*common_data, "first_mismatch"),
            ),
        ),
        _variant(
            "fail",
            _summary(
                {
                    **common_summary,
                    "verdict": {"const": "fail"},
                    "always_matched": {"const": False},
                    "stop_reason": {"const": "first_mismatch"},
                },
                (
                    "signal",
                    "expected_state",
                    "match_mode",
                    "verdict",
                    "always_matched",
                    "checked_value_count",
                    "stop_reason",
                ),
                complete=True,
            ),
            _closed(
                {**common_data, "first_mismatch": mismatch},
                (*common_data, "first_mismatch"),
            ),
        ),
    )


def _signal_resolve_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    match = _closed(
        {
            "signal": _string(),
            "type": _string(nonempty=False),
            "file": _string(nonempty=False),
            "line": _integer(),
        },
        ("signal", "type", "file", "line"),
    )
    return (
        _variant(
            "found",
            _summary(
                {"status": {"const": "found"}, "query": _string()},
                ("status", "query"),
                complete=True,
            ),
            _closed({"matches": _array(match, min_items=1)}, ("matches",)),
        ),
    )


def _signal_canonicalize_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    summary = _summary(
        {
            "status": {"const": "found"},
            "query": _string(),
            "match_count": {"const": 1},
            "canonicalization_scope": {
                "const": "static_design_connectivity"
            },
        },
        (
            "status",
            "query",
            "match_count",
            "canonicalization_scope",
        ),
    )
    connection = _closed(
        {
            "instance": _string(nonempty=False),
            "port": _string(nonempty=False),
            "direction": {"enum": ["input_or_inout", "output"]},
            "evidence": {"const": "npi_static_port_connection"},
        },
        ("instance", "port", "direction", "evidence"),
    )
    common = {
        "resolved_path": _string(),
        "connected_path": _nullable(_string()),
        "canonical_path": _string(),
        "mapping_kind": {
            "enum": ["identity", "static_port_connection"]
        },
        "selection_basis": {"const": "unique_exact_design_match"},
        "scope": _string(nonempty=False),
        "leaf": _string(),
        "connection": {"anyOf": [{"type": "null"}, connection]},
    }
    return (
        _variant(
            "identity_without_port",
            summary,
            _closed(
                {
                    **common,
                    "connected_path": {"type": "null"},
                    "mapping_kind": {"const": "identity"},
                    "connection": {"type": "null"},
                },
                tuple(common),
            ),
        ),
        _variant(
            "identity_port_without_target",
            summary,
            _closed(
                {
                    **common,
                    "connected_path": {"type": "null"},
                    "mapping_kind": {"const": "identity"},
                    "connection": connection,
                },
                tuple(common),
            ),
        ),
        _variant(
            "static_port_connection",
            summary,
            _closed(
                {
                    **common,
                    "connected_path": _string(),
                    "mapping_kind": {
                        "const": "static_port_connection"
                    },
                    "connection": connection,
                },
                tuple(common),
            ),
        ),
    )


def _with_optional_common_blocks(properties: Mapping[str, Schema]) -> dict[str, Schema]:
    result = copy.deepcopy(dict(properties))
    result["common_blocks"] = _array(_ref("commonBlock"))
    return result


def _trace_static_contract(mode: str) -> tuple[NonSamplingSuccessVariant, ...]:
    summary = _summary(
        {
            "signal": _string(),
            "mode": {"const": mode},
            "limit_hint": _string(),
        },
        ("signal", "mode"),
        complete=True,
    )
    return (
        _variant(
            "paths",
            summary,
            _closed(
                _with_optional_common_blocks(
                    {"paths": _array(_ref("nonSamplingSourcePath"))}
                ),
                ("paths",),
            ),
        ),
    )


def _trace_active_driver_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "paths",
            _summary(
                {
                    "signal": _string(),
                    "time": _string(),
                    "active_time": _string(nonempty=False),
                    "termination": _string(),
                    "termination_detail": _string(),
                    "limit_hint": _string(),
                },
                (
                    "signal",
                    "time",
                    "active_time",
                    "termination",
                    "termination_detail",
                ),
                complete=True,
            ),
            _closed(
                _with_optional_common_blocks(
                    {"paths": _array(_ref("nonSamplingSourcePath"))}
                ),
                ("paths",),
            ),
        ),
    )


def _active_chain_depth_frontier_schema() -> Schema:
    return _closed(
        {
            "chain_id": _string(),
            "signal": _string(),
            "time": _string(),
            "value": _string(nonempty=False),
            "stopped_after_depth": _integer(minimum=1),
        },
        (
            "chain_id",
            "signal",
            "time",
            "value",
            "stopped_after_depth",
        ),
    )


def _active_chain_ambiguity_schema() -> Schema:
    value = {
        "oneOf": [
            _closed(
                {
                    "status": {"const": "ok"},
                    "value": _string(nonempty=False),
                    "known": {"type": "boolean"},
                    "value_time": _nullable(_string()),
                },
                ("status", "value", "known", "value_time"),
            ),
            _closed(
                {
                    "status": {
                        "enum": ["missing_value", "signal_not_found"]
                    },
                    "value": {"type": "null"},
                    "known": {"type": "null"},
                    "value_time": {"type": "null"},
                },
                ("status", "value", "known", "value_time"),
            ),
        ]
    }
    sample = _closed(
        {
            "signal": _string(),
            "before": value,
            "after": value,
            "changed": {"type": ["boolean", "null"]},
        },
        ("signal", "before", "after", "changed"),
    )
    statement = _closed(
        {
            "kind": _string(),
            "driver": _string(nonempty=False),
            "file": _string(nonempty=False),
            "line": _integer(),
            "rhs_signal_count": _integer(),
            "returned_rhs_signal_count": _integer(),
            "complete": {"type": "boolean"},
            "rhs_samples": _array(sample),
        },
        (
            "kind",
            "driver",
            "file",
            "line",
            "rhs_signal_count",
            "returned_rhs_signal_count",
            "complete",
            "rhs_samples",
        ),
    )
    return _closed(
        {
            "kind": _string(),
            "signal": _string(),
            "active_time": _string(),
            "hop_index": _integer(),
            "statement_count": _integer(),
            "rhs_signal_count": _integer(),
            "returned_rhs_signal_count": _integer(),
            "omitted_rhs_signal_count": _integer(),
            "analysis_complete": {"type": "boolean"},
            "truncation_scopes": _array(
                {"const": "ambiguity_rhs_samples"}
            ),
            "statements": _array(statement),
        },
        (
            "kind",
            "signal",
            "active_time",
            "hop_index",
            "statement_count",
            "rhs_signal_count",
            "returned_rhs_signal_count",
            "omitted_rhs_signal_count",
            "analysis_complete",
            "truncation_scopes",
            "statements",
        ),
    )


def _trace_active_driver_chain_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common = {
        "signal": _string(),
        "time": _string(),
        "termination": _string(),
        "termination_detail": _string(),
        "limit_hint": _string(),
    }
    required = ("signal", "time", "termination", "termination_detail")
    base_data = _with_optional_common_blocks(
        {"hops": _array(_ref("nonSamplingTraceHop"))}
    )
    normal = _variant(
        "normal",
        _summary(
            common,
            required,
            complete=True,
            value_width=True,
        ),
        _closed(base_data, ("hops",)),
    )
    depth_data = {
        **base_data,
        "depth_frontiers": _array(
            _ref("nonSamplingActiveChainDepthFrontier"),
            min_items=1,
        ),
        # The engine wrapper hoists only the handler's summary.  Continuation
        # advice therefore remains under public data.
        "suggested_next_actions": _array(
            _ref("suggestedNextAction"),
            min_items=1,
        ),
    }
    depth = _variant(
        "depth_limited",
        _summary(
            {
                **common,
                "termination": {"const": "limit"},
                "termination_detail": {"const": "max_depth"},
            },
            required,
            complete=True,
            value_width=True,
        ),
        _closed(
            depth_data,
            ("hops", "depth_frontiers", "suggested_next_actions"),
        ),
    )
    ambiguity = _variant(
        "ambiguous",
        _summary(
            {**common, "termination": {"const": "ambiguous"}},
            required,
            complete=True,
            value_width=True,
        ),
        _closed(
            {
                **base_data,
                "ambiguity_evidence": _ref(
                    "nonSamplingActiveChainAmbiguity"
                ),
            },
            ("hops", "ambiguity_evidence"),
        ),
    )
    return normal, depth, ambiguity


def _x_origin_point_schema(time_field: str) -> Schema:
    return _closed(
        {
            "signal": _string(),
            time_field: _string(),
            "value": _ref("logicValue"),
            "x_mask": _string(),
        },
        ("signal", time_field, "value", "x_mask"),
    )


def _x_origin_hop_schema() -> Schema:
    return _closed(
        {
            "index": _integer(),
            "chain_id": _string(),
            "signal": _string(),
            "x_onset_time": _string(),
            "active_time": _string(nonempty=False),
            "value": _ref("logicValue"),
            "x_mask": _string(),
            "relation": _string(),
            "file": _string(nonempty=False),
            "line": _integer(),
            "signal_path": _array(_string(), min_items=1),
        },
        (
            "index",
            "chain_id",
            "signal",
            "x_onset_time",
            "active_time",
            "value",
            "x_mask",
            "relation",
            "file",
            "line",
            "signal_path",
        ),
    )


def _x_origin_pending_schema() -> Schema:
    limited_signal = _closed(
        {
            "signal": _string(),
            "relation": _string(),
            "reason": {"const": "max_trace_signals"},
        },
        ("signal", "relation", "reason"),
    )
    semantic = _closed(
        {
            "signal": _string(),
            "relation": _string(),
            "x_onset_time": _string(),
            "sample_time": _string(),
            "value": _ref("logicValue"),
            "x_mask": _string(),
        },
        ("signal", "relation", "x_onset_time"),
    )
    return {"oneOf": [limited_signal, semantic]}


def _x_origin_chain_schema() -> Schema:
    origin = _closed(
        {
            "signal": _string(),
            "x_onset_time": _string(),
            "kind": _string(nonempty=False),
            "reason": _string(),
            "evidence_status": {"enum": ["proven", "best_effort"]},
            "file": _string(nonempty=False),
            "line": _integer(),
        },
        (
            "signal",
            "x_onset_time",
            "kind",
            "reason",
            "evidence_status",
            "file",
            "line",
        ),
    )
    pending = _ref("nonSamplingXOriginPending")
    event = _closed(
        {
            "hop_index": _integer(),
            "reason": {"const": "max_chains"},
            "x_dependency_count": _integer(minimum=1),
            "returned_x_dependency_count": _integer(minimum=1),
            "omitted_x_dependency_count": _integer(minimum=1),
            "pending_x_dependencies": _array(pending, min_items=1),
        },
        (
            "hop_index",
            "reason",
            "x_dependency_count",
            "returned_x_dependency_count",
            "omitted_x_dependency_count",
            "pending_x_dependencies",
        ),
    )
    return _closed(
        {
            "chain_id": _string(),
            "status": _string(),
            "termination_detail": _string(nonempty=False),
            "complete": {"type": "boolean"},
            "current": _ref("nonSamplingXOriginCurrent"),
            "hops": _array(_ref("nonSamplingXOriginHop")),
            "origin": origin,
            "pending_x_dependencies": _array(pending, min_items=1),
            "branch_events": _array(event, min_items=1),
        },
        (
            "chain_id",
            "status",
            "termination_detail",
            "complete",
            "current",
            "hops",
        ),
    )


def _trace_x_origin_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common = {
        "signal": _string(),
        "query_time": _string(),
        "termination": _string(),
        "evidence_status": {
            "enum": ["unresolved", "best_effort", "proven"]
        },
        "chain_count": _integer(),
        "completed_chain_count": _integer(),
        "limited_chain_count": _integer(),
        "hop_count": _integer(),
        "origin_count": _integer(),
        **_value_width_properties(),
    }
    required = (
        "signal",
        "query_time",
        "termination",
        "evidence_status",
        "chain_count",
        "completed_chain_count",
        "limited_chain_count",
        "hop_count",
        "origin_count",
    )
    not_x_summary = {
        **common,
        "termination": {"const": "not_x_at_query_time"},
        "evidence_status": {"const": "proven"},
        "chain_count": {"const": 0},
        "completed_chain_count": {"const": 0},
        "limited_chain_count": {"const": 0},
        "hop_count": {"const": 0},
        "origin_count": {"const": 0},
    }
    traced_data = {
        "query": _ref("nonSamplingXOriginQuery"),
        "chains": _array(_ref("nonSamplingXOriginChain")),
        "limitations": _array(_string()),
        "depth_frontiers": _array(
            _ref("nonSamplingXOriginDepthFrontier"),
            min_items=1,
        ),
        # This field is public data after the handler payload is wrapped.
        "suggested_next_actions": _array(
            _ref("suggestedNextAction"),
            min_items=1,
        ),
    }
    return (
        _variant(
            "not_x",
            _summary(not_x_summary, required, complete=True),
            _closed(
                {
                    "query": _ref("nonSamplingXOriginQuery"),
                    "chains": _array(
                        _ref("nonSamplingXOriginChain"),
                        max_items=0,
                    ),
                    "limitations": _array(_string(), max_items=0),
                },
                ("query", "chains", "limitations"),
            ),
        ),
        _variant(
            "traced",
            _summary(
                {
                    **common,
                    "termination": {
                        "enum": [
                            "origin_found",
                            "partial",
                            "limit",
                            "x_not_observable_upstream",
                            "loop_detected",
                            "pending",
                        ]
                    },
                },
                required,
                complete=True,
            ),
            _closed(
                traced_data,
                ("query", "chains", "limitations"),
            ),
        ),
    )


def _stream_config_load_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "loaded",
            _summary(
                {
                    "loaded": _integer(),
                    "mode": {"enum": ["replace", "append"]},
                },
                ("loaded", "mode"),
            ),
            _closed(
                {
                    "streams": _array(_string()),
                    "issues": _array(
                        _ref("nonSamplingStreamLoadIssue")
                    ),
                    "validation": _array(
                        _ref("nonSamplingStreamLoadValidation")
                    ),
                    "recommended_actions": _recommended_actions(),
                },
                (
                    "streams",
                    "issues",
                    "validation",
                    "recommended_actions",
                ),
            ),
        ),
    )


def _stream_compact_config_schema() -> Schema:
    return _edge_closed(
        {
            "name": _string(),
            "sampling_mode": {"const": "clock_edge"},
            "clock": _string(),
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "sample_point": {"enum": ["before", "after"]},
            "handshake": {
                "enum": ["vld", "vld/rdy", "vld/bp", "vld/rdy/bp"]
            },
            "packet": {"enum": ["sop/eop", "none"]},
            "field_count": _integer(),
            "channel_id_valid": {"enum": ["every_beat", "sop", "eop"]},
            "allow_interleaving": {"type": "boolean"},
        },
        (
            "name",
            "sampling_mode",
            "clock",
            "edge",
            "handshake",
            "packet",
            "field_count",
            "channel_id_valid",
            "allow_interleaving",
        ),
    )


def _stream_config_list_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    summary = _summary({"count": _integer()}, ("count",))
    return (
        _variant(
            "empty",
            _summary({"count": {"const": 0}}, ("count",)),
            _closed(
                {
                    "streams": _array(
                        _ref("nonSamplingStreamConfig"),
                        max_items=0,
                    )
                },
                ("streams",),
            ),
        ),
        _variant(
            "compact",
            summary,
            _closed(
                {
                    "streams": _array(
                        _ref("nonSamplingStreamCompactConfig"),
                        min_items=1,
                    )
                },
                ("streams",),
            ),
        ),
        _variant(
            "verbose",
            summary,
            _closed(
                {
                    "streams": _array(
                        _ref("nonSamplingStreamConfig"),
                        min_items=1,
                    )
                },
                ("streams",),
            ),
        ),
    )


def _stream_config_get_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "found",
            _summary({"name": _string()}, ("name",)),
            _closed(
                {"stream": _ref("nonSamplingStreamConfig")},
                ("stream",),
            ),
        ),
    )


def _stream_describe_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    return (
        _variant(
            "described",
            _summary(
                {
                    "stream": _string(),
                    "handshake": {
                        "enum": [
                            "vld",
                            "vld/rdy",
                            "vld/bp",
                            "vld/rdy/bp",
                        ]
                    },
                    "packet_enabled": {"type": "boolean"},
                },
                ("stream", "handshake", "packet_enabled"),
            ),
            _closed(
                {
                    "config": _ref("nonSamplingStreamConfig"),
                    "issues": _array(_ref("nonSamplingStreamIssue")),
                    "validation": _ref(
                        "nonSamplingStreamValidation"
                    ),
                    "semantics": _closed(
                        {
                            "transfer": {
                                "enum": [
                                    "vld",
                                    "vld/rdy",
                                    "vld/bp",
                                    "vld/rdy/bp",
                                ]
                            },
                            "stall": {"enum": ["none", "enabled"]},
                        },
                        ("transfer", "stall"),
                    ),
                },
                ("config", "issues", "validation", "semantics"),
            ),
        ),
    )


def _stream_validate_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    common = {
        "stream": _string(),
        "ok": {"type": "boolean"},
        "static_validation_complete": {"const": True},
        "dynamic_requested": {"type": "boolean"},
    }
    data_common = {"issues": _array(_ref("nonSamplingStreamIssue"))}
    return (
        _variant(
            "static_only",
            _summary(
                {**common, "dynamic_requested": {"const": False}},
                tuple(common),
                complete=True,
            ),
            _closed(
                {**data_common, "dynamic": _closed({})},
                ("issues", "dynamic"),
            ),
        ),
        _variant(
            "dynamic_skipped_after_static_error",
            _summary(
                {
                    **common,
                    "ok": {"const": False},
                    "dynamic_requested": {"const": True},
                },
                tuple(common),
                complete=True,
            ),
            _closed(
                {**data_common, "dynamic": _closed({})},
                ("issues", "dynamic"),
            ),
        ),
        _variant(
            "dynamic",
            _summary(
                {
                    **common,
                    "ok": {"const": True},
                    "dynamic_requested": {"const": True},
                },
                tuple(common),
                complete=True,
            ),
            _closed(
                {
                    **data_common,
                    "dynamic": _ref(
                        "nonSamplingStreamDynamicValidation"
                    ),
                },
                ("issues", "dynamic"),
            ),
        ),
    )


def _stream_query_summary(
    query: str,
    *,
    filter_kind: str = "none",
    returned_count: int | None = None,
    truncated: bool | None = None,
) -> Schema:
    extra: dict[str, Schema] = {
        "query": {"const": query},
        "filter_applied": {"const": filter_kind != "none"},
    }
    required = ["query", "filter_applied"]
    if filter_kind == "beat":
        extra.update(
            {
                "packet_enabled": {"const": False},
                "unresolved_filter_count": _integer(),
                "matched_transfer_count": _integer(),
            }
        )
        required.extend(
            ("unresolved_filter_count", "matched_transfer_count")
        )
    elif filter_kind == "packet":
        extra.update(
            {
                "packet_enabled": {"const": True},
                "unresolved_filter_count": _integer(),
                "matched_packet_count": _integer(),
                "retained_packet_count": _integer(),
            }
        )
        required.extend(
            (
                "unresolved_filter_count",
                "matched_packet_count",
                "retained_packet_count",
            )
        )
    if returned_count is not None:
        extra["returned_count"] = {"const": returned_count}
    if truncated is not None:
        extra["response_truncated"] = {"const": truncated}
    return _stream_summary_schema(extra, required)


def _stream_filter_data(
    properties: Mapping[str, Schema],
    *,
    packet: bool,
) -> dict[str, Schema]:
    return {
        **copy.deepcopy(dict(properties)),
        "filter": _ref(
            "nonSamplingStreamPacketFilter"
            if packet
            else "nonSamplingStreamBeatFilter"
        ),
        "notes": _closed(
            {"unresolved_filter_count": _string()},
            ("unresolved_filter_count",),
        ),
    }


def _stream_query_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    variants: list[NonSamplingSuccessVariant] = []

    for filter_kind in ("none", "beat", "packet"):
        data_props: dict[str, Schema] = {}
        required: tuple[str, ...] = ()
        if filter_kind != "none":
            data_props = _stream_filter_data(
                data_props,
                packet=filter_kind == "packet",
            )
            required = ("filter", "notes")
        variants.append(
            _variant(
                f"summary_{filter_kind}",
                _stream_query_summary(
                    "summary",
                    filter_kind=filter_kind,
                    returned_count=0,
                    truncated=False,
                ),
                _closed(data_props, required),
            )
        )

    for query in ("first_transfer", "last_transfer"):
        for filter_kind in ("none", "beat"):
            extra = (
                _stream_filter_data({}, packet=False)
                if filter_kind != "none"
                else {}
            )
            required = (
                ("filter", "notes")
                if filter_kind != "none"
                else ()
            )
            variants.extend(
                (
                    _variant(
                        f"{query}_{filter_kind}_found",
                        _stream_query_summary(
                            query,
                            filter_kind=filter_kind,
                            returned_count=1,
                            truncated=False,
                        ),
                        _closed(
                            {
                                **extra,
                                "row": _ref(
                                    "nonSamplingStreamRow"
                                ),
                            },
                            (*required, "row"),
                        ),
                    ),
                    _variant(
                        f"{query}_{filter_kind}_empty",
                        _stream_query_summary(
                            query,
                            filter_kind=filter_kind,
                            returned_count=0,
                            truncated=False,
                        ),
                        _closed(extra, required),
                    ),
                )
            )

    def add_window(
        query: str,
        key: str,
        item_ref: str,
        filter_kinds: tuple[str, ...],
    ) -> None:
        for filter_kind in filter_kinds:
            core = {key: _array(_ref(item_ref))}
            if filter_kind != "none":
                core = _stream_filter_data(
                    core,
                    packet=filter_kind == "packet",
                )
            required = tuple(core)
            variants.extend(
                (
                    _variant(
                        f"{query}_{filter_kind}_complete",
                        _stream_query_summary(
                            query,
                            filter_kind=filter_kind,
                            truncated=False,
                        ),
                        _closed(core, required),
                    ),
                    _variant(
                        f"{query}_{filter_kind}_truncated",
                        _stream_query_summary(
                            query,
                            filter_kind=filter_kind,
                            truncated=True,
                        ),
                        _closed(
                            {**core, "hint": _string()},
                            (*required, "hint"),
                        ),
                    ),
                )
            )

    add_window(
        "transfer_window",
        "rows",
        "nonSamplingStreamRow",
        ("none", "beat"),
    )

    for query in ("first_stall", "last_stall"):
        variants.extend(
            (
                _variant(
                    f"{query}_found",
                    _stream_query_summary(
                        query,
                        returned_count=1,
                        truncated=False,
                    ),
                    _closed(
                        {
                            "stall": _ref(
                                "nonSamplingStreamStall"
                            )
                        },
                        ("stall",),
                    ),
                ),
                _variant(
                    f"{query}_empty",
                    _stream_query_summary(
                        query,
                        returned_count=0,
                        truncated=False,
                    ),
                    _closed({}),
                ),
            )
        )

    add_window(
        "stall_window",
        "stalls",
        "nonSamplingStreamStall",
        ("none",),
    )

    for query in ("first_packet", "last_packet"):
        for filter_kind in ("none", "packet"):
            extra = (
                _stream_filter_data({}, packet=True)
                if filter_kind == "packet"
                else {}
            )
            required = (
                ("filter", "notes")
                if filter_kind == "packet"
                else ()
            )
            variants.extend(
                (
                    _variant(
                        f"{query}_{filter_kind}_found",
                        _stream_query_summary(
                            query,
                            filter_kind=filter_kind,
                            returned_count=1,
                            truncated=False,
                        ),
                        _closed(
                            {
                                **extra,
                                "found": {"const": True},
                                "packet": _ref(
                                    "nonSamplingStreamPacket"
                                ),
                            },
                            (*required, "found", "packet"),
                        ),
                    ),
                    _variant(
                        f"{query}_{filter_kind}_empty",
                        _stream_query_summary(
                            query,
                            filter_kind=filter_kind,
                            returned_count=0,
                            truncated=False,
                        ),
                        _closed(
                            {
                                **extra,
                                "found": {"const": False},
                                "packet": {"type": "null"},
                            },
                            (*required, "found", "packet"),
                        ),
                    ),
                )
            )

    for found in (False, True):
        variants.append(
            _variant(
                f"packet_at_{'found' if found else 'empty'}",
                _stream_query_summary(
                    "packet_at",
                    returned_count=1 if found else 0,
                    truncated=False,
                ),
                _closed(
                    {
                        "found": {"const": found},
                        "packet": (
                            _ref("nonSamplingStreamPacket")
                            if found
                            else {"type": "null"}
                        ),
                    },
                    ("found", "packet"),
                ),
            )
        )

    add_window(
        "packet_window",
        "packets",
        "nonSamplingStreamPacket",
        ("none", "packet"),
    )
    return tuple(variants)


def _stream_export_contract() -> tuple[NonSamplingSuccessVariant, ...]:
    variants: list[NonSamplingSuccessVariant] = []
    for kind in ("transfer", "packet_beats", "packet"):
        item = (
            _ref("nonSamplingStreamPacket")
            if kind == "packet"
            else _ref("nonSamplingStreamRow")
        )
        preview_summary = _stream_summary_schema(
            {
                "status": {"const": "preview"},
                "output_written": {"const": False},
                "row_count": _integer(),
                "line_limit": _integer(minimum=None),
                "kind": {"const": kind},
            },
            (
                "status",
                "output_written",
                "row_count",
                "line_limit",
                "kind",
            ),
        )
        variants.append(
            _variant(
                f"{kind}_preview",
                preview_summary,
                _closed(
                    {"preview": _array(item)},
                    ("preview",),
                ),
            )
        )
        written_summary = _stream_summary_schema(
            {
                "status": {"const": "written"},
                "output_written": {"const": True},
                "row_count": _integer(),
                "line_limit": _integer(minimum=None),
                "kind": {"const": kind},
                "output": _closed(
                    {
                        "path": _string(),
                        "meta_path": _string(),
                        "file_format": {
                            "enum": ["tsv", "csv", "xout"]
                        },
                    },
                    ("path", "meta_path", "file_format"),
                ),
            },
            (
                "status",
                "output_written",
                "row_count",
                "line_limit",
                "kind",
                "output",
            ),
        )
        variants.append(
            _variant(
                f"{kind}_written",
                written_summary,
                _closed({}),
            )
        )
    return tuple(variants)


NON_SAMPLING_EXTERNAL_DEFINITIONS = frozenset(
    {
        "commonBlock",
        "logicValue",
        "reset",
        "suggestedNextAction",
        "valueWidthDiagnostic",
    }
)


_CONTRACT_BUILDERS = {
    "apb.config.list": _apb_config_list_contract,
    "apb.config.load": _apb_config_load_contract,
    "apb.query": _apb_query_contract,
    "apb.statistics": lambda: _protocol_statistics_contract(
        "apb.statistics",
        axi=False,
    ),
    "apb.transaction.cursor": lambda: _transaction_cursor_contract(
        axi=False
    ),
    "apb.transfer_window": _apb_transfer_window_contract,
    "axi.analysis": _axi_analysis_contract,
    "axi.channel_stall": _axi_channel_stall_contract,
    "axi.config.list": _axi_config_list_contract,
    "axi.config.load": _axi_config_load_contract,
    "axi.export": _axi_export_contract,
    "axi.latency_outlier": _axi_latency_outlier_contract,
    "axi.outstanding_timeline": _axi_outstanding_timeline_contract,
    "axi.query": _axi_query_contract,
    "axi.request_response_pair": _axi_request_response_pair_contract,
    "axi.statistics": lambda: _protocol_statistics_contract(
        "axi.statistics",
        axi=True,
    ),
    "axi.transaction.cursor": lambda: _transaction_cursor_contract(
        axi=True
    ),
    "event.config.list": _event_config_list_contract,
    "event.config.load": _event_config_load_contract,
    "expr.normalize": _expr_normalize_contract,
    "list.add": _list_add_contract,
    "list.create": _list_create_contract,
    "list.load": _list_load_contract,
    "list.delete": _list_delete_contract,
    "list.export": _list_export_contract,
    "list.first_change": _list_first_change_contract,
    "list.show": _list_show_contract,
    "list.validate": _list_validate_contract,
    "nwave.rc.generate": _nwave_rc_generate_contract,
    "scope.list": _scope_list_contract,
    "signal.anomaly.inspect": _signal_anomaly_contract,
    "signal.canonicalize": _signal_canonicalize_contract,
    "signal.changes": _signal_changes_contract,
    "signal.resolve": _signal_resolve_contract,
    "signal.stability": _signal_stability_contract,
    "signal.xz_verify": _signal_xz_verify_contract,
    "stream.config.get": _stream_config_get_contract,
    "stream.config.list": _stream_config_list_contract,
    "stream.config.load": _stream_config_load_contract,
    "stream.describe": _stream_describe_contract,
    "stream.export": _stream_export_contract,
    "stream.query": _stream_query_contract,
    "stream.validate": _stream_validate_contract,
    "trace.active_driver": _trace_active_driver_contract,
    "trace.active_driver_chain": _trace_active_driver_chain_contract,
    "trace.driver": lambda: _trace_static_contract("driver"),
    "trace.load": lambda: _trace_static_contract("load"),
    "trace.x_origin": _trace_x_origin_contract,
    "waveform.cursor.delete": _cursor_delete_contract,
    "waveform.cursor.get": _cursor_get_contract,
    "waveform.cursor.list": _cursor_list_contract,
    "waveform.cursor.set": _cursor_set_contract,
    "waveform.cursor.use": _cursor_use_contract,
}


if frozenset(_CONTRACT_BUILDERS) != NON_SAMPLING_RESPONSE_ACTIONS:
    missing = sorted(NON_SAMPLING_RESPONSE_ACTIONS - _CONTRACT_BUILDERS.keys())
    extra = sorted(_CONTRACT_BUILDERS.keys() - NON_SAMPLING_RESPONSE_ACTIONS)
    raise RuntimeError(
        "non-sampling response contract registry drift: "
        f"missing={missing}, extra={extra}"
    )


def non_sampling_required_external_definitions() -> frozenset[str]:
    """Return canonical ``$defs`` that the main generator must inject."""

    return NON_SAMPLING_EXTERNAL_DEFINITIONS


def non_sampling_response_contract_definitions() -> dict[str, Schema]:
    """Return independent domain definitions used by the strict variants."""

    return copy.deepcopy(_definitions())


def non_sampling_success_response_variants(
    action: str,
) -> tuple[NonSamplingSuccessVariant, ...]:
    """Return all reachable, correlated success variants for ``action``."""

    try:
        variants = _CONTRACT_BUILDERS[action]()
    except KeyError as exc:
        raise ValueError(
            f"{action}: no non-sampling response contract"
        ) from exc
    if not variants:
        raise RuntimeError(f"{action}: response contract has no variants")
    names = [variant.name for variant in variants]
    if len(names) != len(set(names)):
        raise RuntimeError(
            f"{action}: duplicate response variant names: {names}"
        )
    return tuple(
        NonSamplingSuccessVariant(
            variant.name,
            copy.deepcopy(variant.summary),
            copy.deepcopy(variant.data),
        )
        for variant in variants
    )


def _deduplicated_schemas(schemas: Iterable[Schema]) -> list[Schema]:
    result: list[Schema] = []
    seen: set[str] = set()
    for schema in schemas:
        key = json.dumps(schema, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        result.append(copy.deepcopy(schema))
    return result


def non_sampling_explicit_response_schema(
    action: str,
    pointer: str,
) -> Schema | None:
    """Project strict variants onto ``/summary`` or ``/data``.

    Unknown actions and non-root pointers deliberately return ``None`` so the
    main generator can route only actions owned by this module.  A covered
    action never receives an inferred or permissive schema.
    """

    if action not in NON_SAMPLING_RESPONSE_ACTIONS:
        return None
    if pointer not in {SUMMARY_POINTER, DATA_POINTER}:
        return None
    variants = non_sampling_success_response_variants(action)
    schemas = _deduplicated_schemas(
        (
            variant.summary
            if pointer == SUMMARY_POINTER
            else variant.data
        )
        for variant in variants
    )
    if len(schemas) == 1:
        return schemas[0]
    return {"anyOf": schemas}


def non_sampling_success_pairing_schema(action: str) -> Schema:
    """Return an action-level ``oneOf`` preserving summary/data correlation."""

    variants = non_sampling_success_response_variants(action)
    return {
        "oneOf": [
            {
                "properties": {
                    "summary": copy.deepcopy(variant.summary),
                    "data": copy.deepcopy(variant.data),
                },
                "required": ["summary", "data"],
                "x-success-variant": variant.name,
            }
            for variant in variants
        ]
    }


__all__ = [
    "DATA_POINTER",
    "NON_SAMPLING_EXTERNAL_DEFINITIONS",
    "NON_SAMPLING_RESPONSE_ACTIONS",
    "NonSamplingSuccessVariant",
    "SUMMARY_POINTER",
    "non_sampling_explicit_response_schema",
    "non_sampling_required_external_definitions",
    "non_sampling_response_contract_definitions",
    "non_sampling_success_pairing_schema",
    "non_sampling_success_response_variants",
]
