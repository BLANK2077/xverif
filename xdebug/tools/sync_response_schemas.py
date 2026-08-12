#!/usr/bin/env python3
"""Generate every public xdebug action response schema from one source.

Domain contract sources own correlated success variants and reusable business
objects; checked-in examples are mandatory witnesses for those contracts.
Sampling families that are intentionally witness-derived still use explicit
root overrides and conditional contracts.  The generator closes every object
and projects all actions into one strict success/error envelope.  Dynamic-key
JSON is allowed only through the explicitly marked ``jsonObject`` component.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft7Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "specs"))
from action_contracts import actions_filter_schema, reset_schema
from non_sampling_response_contracts import (
    NON_SAMPLING_RESPONSE_ACTIONS,
    non_sampling_explicit_response_schema,
    non_sampling_required_external_definitions,
    non_sampling_response_contract_definitions,
    non_sampling_success_response_variants,
)
from session_batch_response_contracts import (
    BatchResultContract,
    SESSION_RESPONSE_ACTIONS,
    build_batch_result_contract,
    session_explicit_response_schema,
    session_response_contract_definitions,
    session_success_response_variants,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "specs" / "actions" / "actions.yaml"
SCHEMA_DIR = ROOT / "schemas" / "v1" / "actions"
GENERIC_ERROR_SCHEMA_PATH = ROOT / "schemas" / "v1" / "xdebug.error.schema.json"
RETIRED_SCHEMA_PATHS = (
    ROOT / "schemas" / "v1" / "xdebug.request.schema.json",
    ROOT / "schemas" / "v1" / "xdebug.response.schema.json",
    ROOT / "schemas" / "v1" / "common" / "meta.schema.json",
    ROOT / "schemas" / "v1" / "common" / "error.schema.json",
    ROOT / "schemas" / "v1" / "common" / "evidence.schema.json",
    ROOT / "schemas" / "v1" / "common" / "limits.schema.json",
    ROOT / "schemas" / "v1" / "common" / "output.schema.json",
    ROOT / "schemas" / "v1" / "common" / "source_location.schema.json",
    ROOT / "schemas" / "v1" / "common" / "target.schema.json",
    ROOT / "schemas" / "v1" / "common" / "warning.schema.json",
    ROOT / "schemas" / "v1" / "common" / "waveform_sample.schema.json",
)

LEGACY_COMPLETENESS_FIELDS = {"truncated", "truncation_scope"}

COMMON_BLOCK_ACTIONS = {
    "trace.driver",
    "trace.load",
    "trace.active_driver",
    "trace.active_driver_chain",
}

VALUE_ACTIONS = {
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

CLOCK_CONTEXT_ACTIONS = {
    "expr.eval_at",
    "value.at",
    "verify.conditions",
}

SAMPLING_CONTRACT_ACTIONS = {
    "counter.statistics",
    "event.export",
    "event.find",
    "protocol.handshake.inspect",
    "signal.sampled_pulse.inspect",
    "signal.statistics",
    "window.verify",
}

RAW_OR_CLOCK_ACTIONS = {
    "signal.statistics",
    "value.at",
}

NEGEDGE_SAMPLE_POINT_REASON = (
    "negedge keeps the established current-value sampling semantics"
)

JSON_VALUE_REF = {"$ref": "#/$defs/jsonValue"}
POINTER_SEPARATOR = "/"
DATA_POINTER = POINTER_SEPARATOR + "data"
SUMMARY_POINTER = POINTER_SEPARATOR + "summary"


def closed(
    properties: dict[str, Any],
    required: Iterable[str] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    required_list = sorted(set(required))
    if required_list:
        schema["required"] = required_list
    return schema


def array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def json_definitions() -> dict[str, Any]:
    return {
        "jsonValue": {
            "anyOf": [
                {"type": "null"},
                {"type": "boolean"},
                {"type": "number"},
                {"type": "string"},
                {"type": "array", "items": JSON_VALUE_REF},
                {"$ref": "#/$defs/jsonObject"},
            ]
        },
        "jsonObject": {
            "type": "object",
            "additionalProperties": JSON_VALUE_REF,
            "x-dynamic-map": True,
            "description": "显式动态键 JSON 对象；每个 value 仍受 jsonValue 递归合同约束。",
        },
    }


def value_width_diagnostic_schema() -> dict[str, Any]:
    return closed(
        {
            "signal": {"type": ["string", "null"]},
            "role": {"type": "string"},
            "reason": {
                "enum": [
                    "npi_range_size_unavailable",
                    "conflicting_signal_widths",
                    "derived_width_unavailable",
                ]
            },
        },
        ("signal", "role", "reason"),
    )


def tool_schema() -> dict[str, Any]:
    fields = {
        "name": {"type": "string"},
        "version": {"type": "string"},
        "build_id": {"type": "string"},
        "git_revision": {"type": "string"},
        "schema_revision": {"type": "string"},
    }
    return closed(fields, ("name", "version"))


def session_schema() -> dict[str, Any]:
    string_fields = (
        "session_id",
        "mode",
        "daidir",
        "fsdb",
        "socket_path",
        "transport",
        "file_dir",
        "host",
        "bind_host",
        "server_host",
    )
    integer_fields = (
        "port",
        "server_pid",
        "created_at",
        "last_active",
        "daidir_mtime_ns",
        "daidir_size",
        "daidir_dev",
        "daidir_inode",
        "fsdb_mtime_ns",
        "fsdb_size",
        "fsdb_dev",
        "fsdb_inode",
    )
    properties = {name: {"type": "string"} for name in string_fields}
    properties.update({name: {"type": "integer"} for name in integer_fields})
    return closed(properties)


def session_record_schema() -> dict[str, Any]:
    schema = session_schema()
    schema["properties"]["session_id"] = {
        "type": "string",
        "minLength": 1,
    }
    schema["properties"]["mode"] = {
        "enum": ["design", "waveform", "combined"]
    }
    schema["properties"]["transport"] = {
        "enum": ["uds", "tcp", "file"]
    }
    for field in (
        "daidir",
        "fsdb",
        "socket_path",
        "file_dir",
        "host",
        "bind_host",
        "server_host",
    ):
        schema["properties"][field] = {
            "type": "string",
            "minLength": 1,
        }
    for field in (
        "server_pid",
        "created_at",
        "last_active",
        "daidir_mtime_ns",
        "daidir_size",
        "daidir_dev",
        "daidir_inode",
        "fsdb_mtime_ns",
        "fsdb_size",
        "fsdb_dev",
        "fsdb_inode",
    ):
        schema["properties"][field] = {
            "type": "integer",
            "minimum": 1,
        }
    schema["properties"]["port"] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 65535,
    }
    schema["required"] = ["session_id", "mode", "transport"]
    schema["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {"mode": {"const": "design"}},
                    "required": ["mode", "daidir"],
                    "not": {
                        "anyOf": [
                            {"required": [field]}
                            for field in (
                                "fsdb",
                                "fsdb_mtime_ns",
                                "fsdb_size",
                                "fsdb_dev",
                                "fsdb_inode",
                            )
                        ]
                    },
                },
                {
                    "properties": {"mode": {"const": "waveform"}},
                    "required": ["mode", "fsdb"],
                    "not": {
                        "anyOf": [
                            {"required": [field]}
                            for field in (
                                "daidir",
                                "daidir_mtime_ns",
                                "daidir_size",
                                "daidir_dev",
                                "daidir_inode",
                            )
                        ]
                    },
                },
                {
                    "properties": {"mode": {"const": "combined"}},
                    "required": ["mode", "daidir", "fsdb"],
                },
            ]
        },
        {
            "oneOf": [
                {
                    "properties": {"transport": {"const": "uds"}},
                    "required": [
                        "transport",
                        "socket_path",
                        "server_host",
                    ],
                    "not": {
                        "anyOf": [
                            {"required": ["file_dir"]},
                            {"required": ["host"]},
                            {"required": ["bind_host"]},
                            {"required": ["port"]},
                        ]
                    },
                },
                {
                    "properties": {"transport": {"const": "tcp"}},
                    "required": [
                        "transport",
                        "host",
                        "bind_host",
                        "port",
                        "server_host",
                    ],
                    "not": {
                        "anyOf": [
                            {"required": ["socket_path"]},
                            {"required": ["file_dir"]},
                        ]
                    },
                },
                {
                    "properties": {"transport": {"const": "file"}},
                    "required": [
                        "transport",
                        "file_dir",
                        "server_host",
                    ],
                    "not": {
                        "anyOf": [
                            {"required": ["socket_path"]},
                            {"required": ["host"]},
                            {"required": ["bind_host"]},
                            {"required": ["port"]},
                        ]
                    },
                },
            ]
        },
    ]
    return schema


def session_list_record_schema() -> dict[str, Any]:
    """Return the compact-first, read-only session.list record contract."""

    # session.list compact mode deliberately omits resource paths and endpoint
    # details, so it must not inherit sessionRecord's mode/transport-dependent
    # required-field conditions. The same closed property set remains available
    # as optional verbose detail.
    schema = session_schema()
    schema["properties"]["session_id"] = {
        "type": "string",
        "minLength": 1,
    }
    schema["properties"]["mode"] = {
        "enum": ["design", "waveform", "combined"]
    }
    schema["properties"]["transport"] = {
        "enum": ["uds", "tcp", "file"]
    }
    schema["properties"].update(
        {
            "lifecycle_state": {
                "enum": [
                    "opening",
                    "active",
                    "cleanup_failed",
                    "terminated_on_timeout",
                ]
            },
            "expired": {"type": "boolean"},
            "recommended_action": {
                "enum": ["session.doctor", "session.gc"]
            },
            "last_active": {"type": "integer", "minimum": 0},
        }
    )
    schema["required"] = [
        "session_id",
        "mode",
        "transport",
        "lifecycle_state",
        "expired",
        "recommended_action",
        "last_active",
    ]
    return schema


def run_manifest_resource_schema() -> dict[str, Any]:
    return closed(
        {
            "path": {
                "type": "string",
                "minLength": 1,
                "pattern": "^[^/].*",
            },
            "size_bytes": {"type": "integer", "minimum": 0},
            "sha256": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
        },
        ("path", "size_bytes", "sha256"),
    )


def run_manifest_response_schema() -> dict[str, Any]:
    return closed(
        {
            "schema_version": {"const": "xdebug.run-manifest.v1"},
            "state": {"const": "published"},
            "resources": closed(
                {
                    "fsdb": {"$ref": "#/$defs/runManifestResource"},
                    "daidir": {"$ref": "#/$defs/runManifestResource"},
                },
                ("fsdb",),
            ),
            "manifest_path": {
                "type": "string",
                "minLength": 1,
            },
        },
        ("schema_version", "state", "resources", "manifest_path"),
    )


def scope_wave_root_schema() -> dict[str, Any]:
    properties = {
        "path": {"type": "string"},
        "name": {"type": "string"},
        "full_name": {"type": "string"},
        "def_name": {"type": "string"},
        "type": {"type": "integer"},
        "queryable": {"const": True},
    }
    return closed(properties, properties)


def scope_design_root_schema() -> dict[str, Any]:
    properties = {
        "path": {"type": "string"},
        "name": {"type": "string"},
        "full_name": {"type": "string"},
        "def_name": {"type": "string"},
        "kind": {
            "enum": ["module", "interface", "program", "scope"],
        },
        "discovery": {
            "enum": ["npi_top", "verified_wave_root"],
        },
        "traceable": {"const": True},
    }
    return closed(properties, properties)


def scope_merged_root_schema() -> dict[str, Any]:
    common = {"path": {"type": "string"}}
    return {
        "oneOf": [
            closed(
                {
                    **common,
                    "sources": {"const": ["design", "wave"]},
                    "status": {"const": "matched"},
                    "wave": scope_wave_root_schema(),
                    "design": scope_design_root_schema(),
                },
                ("path", "sources", "status", "wave", "design"),
            ),
            closed(
                {
                    **common,
                    "sources": {"const": ["design"]},
                    "status": {"const": "design_only"},
                    "wave": {"type": "null"},
                    "design": scope_design_root_schema(),
                },
                ("path", "sources", "status", "wave", "design"),
            ),
            closed(
                {
                    **common,
                    "sources": {"const": ["wave"]},
                    "status": {"const": "wave_only"},
                    "wave": scope_wave_root_schema(),
                    "design": {"type": "null"},
                },
                ("path", "sources", "status", "wave", "design"),
            ),
        ]
    }


def scope_roots_summary_schema() -> dict[str, Any]:
    properties = {
        "source": {"enum": ["auto", "wave", "design"]},
        "wave_available": {"type": "boolean"},
        "design_available": {"type": "boolean"},
        "resource_available": {"type": "boolean"},
        "root_count": {"type": "integer", "minimum": 0},
        "wave_count": {"type": "integer", "minimum": 0},
        "design_count": {"type": "integer", "minimum": 0},
        "matched_count": {"type": "integer", "minimum": 0},
        "recommended_root": {"type": ["null", "string"]},
        "recommended_reason": {
            "enum": [
                "unique root",
                "unique matched root",
                "no roots discovered",
                "multiple matched roots",
                "multiple roots or design/wave mismatch",
            ]
        },
        "scan_complete": {"type": "boolean"},
        "analysis_complete": {"type": "boolean"},
        "response_truncated": {"const": False},
        "total_count": {"type": "integer", "minimum": 0},
        "returned_count": {"type": "integer", "minimum": 0},
        "truncation_scopes": array({"enum": ["analysis_sources"]}),
    }
    return closed(properties, properties)


def scope_roots_data_schema() -> dict[str, Any]:
    return closed(
        {
            "roots": array(scope_merged_root_schema()),
            "wave_roots": array(scope_wave_root_schema()),
            "design_roots": array(scope_design_root_schema()),
            "limitations": array({"type": "string"}),
        },
        ("roots", "wave_roots", "design_roots"),
    )


def warning_schema() -> dict[str, Any]:
    diagnostic = closed(
        {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "severity": {"type": "string"},
            "path": {"type": "string"},
            "signal": {"type": "string"},
            "time": {"type": "string"},
            "details": JSON_VALUE_REF,
        },
        ("code", "message"),
    )
    return {"anyOf": [{"type": "string"}, diagnostic]}


def duplicate_resource_advisory_schema() -> dict[str, Any]:
    return closed(
        {
            "code": {"const": "RESOURCE_SESSION_ALREADY_ALIVE"},
            "severity": {"const": "info"},
            "match_kind": {
                "enum": [
                    "same_daidir",
                    "same_fsdb",
                    "same_combined_resource",
                    "same_resource",
                ]
            },
            "existing_session_id": {"type": "string", "minLength": 1},
            "existing_mode": {
                "enum": ["design", "waveform", "combined"]
            },
            "message": {"type": "string", "minLength": 1},
        },
        (
            "code",
            "severity",
            "match_kind",
            "existing_session_id",
            "existing_mode",
            "message",
        ),
    )


def validation_issue_schema() -> dict[str, Any]:
    return closed(
        {
            "path": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
        },
        ("path", "message"),
    )


def error_schema(action: str) -> dict[str, Any]:
    resource_identity = closed(
        {
            "canonical_path": {"type": "string", "minLength": 1},
            "device": {"type": "integer", "minimum": 0},
            "inode": {"type": "integer", "minimum": 0},
            "size_bytes": {"type": "integer", "minimum": 0},
            "mtime_ns": {"type": "integer", "minimum": 0},
        },
        ("canonical_path", "device", "inode", "size_bytes", "mtime_ns"),
    )
    advisory = closed(
        {
            "code": {"type": "string"},
            "severity": {"type": "string"},
            "message": {"type": "string"},
        },
        ("code", "severity", "message"),
    )
    properties = {
        "code": {"type": "string"},
        "message": {"type": "string"},
        "recoverable": {"type": "boolean"},
        "error_layer": {
            "enum": [
                "schema",
                "handler",
                "wrapper",
                "session_manager",
                "transport",
                "internal",
            ]
        },
        "invalid_arg": {"type": "string"},
        "expected": {"type": "string"},
        "received": JSON_VALUE_REF,
        "received_type": {"type": "string"},
        "received_redacted": {"type": "boolean"},
        "available_values": array({"type": "string", "minLength": 1}),
        "did_you_mean": {"type": "string", "minLength": 1},
        "schema_path": {"type": "string"},
        "required_any_of": array({"type": "string"}),
        "missing_name": {"type": "string"},
        "missing_resource": {"type": "string"},
        "next_actions": array({"type": "string", "minLength": 1}),
        "example_note": {"type": "string"},
        "correct_example": JSON_VALUE_REF,
        "cause_code": {"type": "string"},
        "validation": JSON_VALUE_REF,
        "current_estimated_bytes": {"type": "integer", "minimum": 0},
        "hard_max_bytes": {"type": "integer", "minimum": 0},
        "limit_name": {"enum": ["request_bytes"]},
        "received_bytes": {"type": "integer", "minimum": 0},
        "max_bytes": {"type": "integer", "minimum": 1},
        "transport": {"enum": ["stdio", "uds", "tcp", "file"]},
        "phase": {
            "enum": [
                "public_request",
                "internal_request",
                "transport_request",
                "transport_response",
            ]
        },
        "config_key": {"type": "string", "minLength": 1},
        "config_source": {
            "enum": ["environment", "default", "request"]
        },
        "protocol": {"enum": ["apb", "axi", "stream"]},
        "key_summary": {"type": "string"},
        "manifest_path": {"type": "string", "minLength": 1},
        "resource": {"enum": ["daidir", "fsdb"]},
        "expected_path": {"type": "string", "minLength": 1},
        "actual_path": {"type": "string", "minLength": 1},
        "expected_size_bytes": {"type": "integer", "minimum": 0},
        "actual_size_bytes": {
            "type": ["null", "integer"],
            "minimum": 0,
        },
        "expected_sha256": {
            "type": "string",
            "pattern": "^[0-9a-fA-F]{64}$",
        },
        "actual_sha256": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "string",
                    "pattern": "^[0-9a-fA-F]{64}$",
                },
            ]
        },
        "manifest_schema_version": {"type": "string", "minLength": 1},
        "manifest_state": {"type": "string", "minLength": 1},
        "session_id": {"type": "string", "minLength": 1},
        "session_mode": {
            "enum": ["design", "waveform", "combined"]
        },
        "session_transport": {"enum": ["uds", "tcp", "file"]},
        "idle_sec": {"type": "integer", "minimum": 0},
        "idle_timeout_sec": {"type": "integer", "minimum": 0},
        "cleanup_succeeded": {"type": "boolean"},
        "termination_confirmed": {"type": "boolean"},
        "cancel_state": {"enum": ["confirmed", "unknown"]},
        "session_state": {
            "enum": [
                "cleanup_failed",
                "terminated_on_timeout",
            ]
        },
        "lifecycle_state": {"enum": ["cleanup_failed"]},
        "compensation_status": {
            "enum": [
                "cleaned",
                "not_created",
                "token_mismatch",
                "cleanup_failed",
            ]
        },
        "backend_error_code": {"type": "string", "minLength": 1},
        "timeout_ms": {"type": "integer", "minimum": 1},
        "exit_status": {"type": "integer"},
        "health_status": {"type": "string", "minLength": 1},
        "resource_path": {"type": "string", "minLength": 1},
        "change_kind": {
            "enum": [
                "missing",
                "type_changed",
                "path_changed",
                "fingerprint_upgrade_required",
                "identity_changed",
                "metadata_changed",
                "identity_and_metadata_changed",
            ]
        },
        "expected_resource_identity": resource_identity,
        "actual_resource_identity": {
            "anyOf": [{"type": "null"}, resource_identity]
        },
        "requested_count": {"type": "integer", "minimum": 0},
        "removed_count": {"type": "integer", "minimum": 0},
        "retained_count": {"type": "integer", "minimum": 0},
        "failed_session_ids": array(
            {"type": "string", "minLength": 1}
        ),
        "failure_kind": {"type": "string"},
        "failure_phase": {
            "enum": ["npi_init", "npi_load_design", "npi_fsdb_open"]
        },
        "startup_reason": {"type": "string"},
        "native_error_summary": {"type": "string"},
        "diagnostic_log": {"type": "string"},
        "advisories": array(advisory),
        "validation_issues": {
            "type": "array",
            "items": {"$ref": "#/$defs/validationIssue"},
            "minItems": 1,
        },
    }
    if action in {"trace.x_origin", "value.at"}:
        properties.update(
            {
                "signal": {"type": "string"},
                "time": {"type": "string"},
            }
        )
    schema = closed(
        properties,
        ("code", "message", "recoverable", "error_layer"),
    )
    operational_contracts = [
        {
            "if": {
                "properties": {"code": {"const": "REQUEST_TOO_LARGE"}},
                "required": ["code"],
            },
            "then": {
                "properties": {"recoverable": {"const": False}},
                "required": [
                    "limit_name",
                    "received_bytes",
                    "max_bytes",
                    "transport",
                    "phase",
                    "next_actions",
                ],
            },
        },
        {
            "if": {
                "properties": {"code": {"const": "INVALID_CONFIG"}},
                "required": ["code"],
            },
            "then": {
                "properties": {"recoverable": {"const": False}},
                "required": [
                    "config_key",
                    "config_source",
                    "expected",
                    "next_actions",
                ],
            },
        },
    ]
    schema["allOf"] = operational_contracts
    if action == "signal.canonicalize":
        signal_candidate = closed(
            {
                "path": {"type": "string"},
                "type": {"type": "string"},
                "file": {"type": ["string", "null"]},
                "line": {"type": ["integer", "null"], "minimum": 1},
            },
            ("path", "type", "file", "line"),
        )
        properties.update(
            {
                "query": {"type": "string"},
                "scan_complete": {"type": "boolean"},
                "analysis_complete": {"type": "boolean"},
                "response_truncated": {"const": False},
                "total_count": {"type": "integer", "minimum": 2},
                "returned_count": {"type": "integer", "minimum": 2},
                "truncation_scopes": {
                    "type": "array",
                    "items": {"const": "design_signal_scan"},
                    "maxItems": 1,
                    "uniqueItems": True,
                },
                "available_values": {
                    "type": "array",
                    "items": signal_candidate,
                    "minItems": 2,
                },
            }
        )
        schema.setdefault("allOf", []).extend([
            {
                "if": {
                    "properties": {"code": {"const": "AMBIGUOUS_SIGNAL"}},
                    "required": ["code"],
                },
                "then": {
                    "properties": {
                        "invalid_arg": {"const": "args.signal"},
                    },
                    "required": [
                        "invalid_arg",
                        "expected",
                        "query",
                        "available_values",
                        "scan_complete",
                        "analysis_complete",
                        "response_truncated",
                        "total_count",
                        "returned_count",
                        "truncation_scopes",
                    ],
                },
            },
            {
                "if": {
                    "properties": {
                        "code": {"const": "AMBIGUOUS_SIGNAL"},
                        "scan_complete": {"const": True},
                    },
                    "required": ["code", "scan_complete"],
                },
                "then": {
                    "properties": {
                        "analysis_complete": {"const": True},
                        "truncation_scopes": {"maxItems": 0},
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "code": {"const": "AMBIGUOUS_SIGNAL"},
                        "scan_complete": {"const": False},
                    },
                    "required": ["code", "scan_complete"],
                },
                "then": {
                    "properties": {
                        "analysis_complete": {"const": False},
                        "truncation_scopes": {
                            "minItems": 1,
                            "maxItems": 1,
                        },
                    }
                },
            },
        ])
    return schema


def suggested_next_action_schema() -> dict[str, Any]:
    args = closed(
        {
            "signal": {"type": "string"},
            "time": {"type": "string"},
            "value_format": {"type": "string"},
        }
    )
    limits = closed(
        {
            "max_depth": {"type": "integer", "minimum": 1},
            "max_chains": {"type": "integer", "minimum": 1},
            "max_paths": {"type": "integer", "minimum": 1},
            "max_nodes": {"type": "integer", "minimum": 1},
            "max_time_steps": {"type": "integer", "minimum": 1},
            "max_trace_signals": {"type": "integer", "minimum": 1},
            "max_results": {"type": "integer", "minimum": 1},
            "timeout_ms": {"type": "integer", "minimum": 1},
        }
    )
    return closed(
        {
            "action": {"type": "string"},
            "reason": {"type": "string"},
            "chain_id": {"type": "string"},
            "tool": {"type": "string"},
            "args": args,
            "limits": limits,
        },
        ("action", "reason"),
    )


def common_finding_schema() -> dict[str, Any]:
    return closed(
        {
            "type": {"type": "string"},
            "code": {"type": "string"},
            "severity": {"type": "string"},
            "message": {"type": "string"},
            "signal": {"type": "string"},
            "time": {"type": "string"},
            "begin": {"type": "string"},
            "end": {"type": "string"},
            "value": JSON_VALUE_REF,
            "details": JSON_VALUE_REF,
        }
    )


def common_block_schema() -> dict[str, Any]:
    return closed(
        {
            "message": {"type": "string", "minLength": 1},
            "file": {"type": "string", "minLength": 1},
            "card": {"type": "string", "minLength": 1},
        },
        ("message", "file", "card"),
    )


def sampling_selection_schema() -> dict[str, Any]:
    return closed(
        {
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "sample_point": {
                "type": ["null", "string"],
                "enum": [None, "before", "after"],
            },
        },
        ("edge", "sample_point"),
    )


def sampling_resolution_variants(
    requested_key: str,
    effective_key: str,
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []

    def add(
        edge: str,
        requested_sample_point: str | None,
        effective_sample_point: str | None,
        *,
        applied: bool,
        ignored: bool,
    ) -> None:
        properties: dict[str, Any] = {
            requested_key: {
                "const": {
                    "edge": edge,
                    "sample_point": requested_sample_point,
                }
            },
            effective_key: {
                "const": {
                    "edge": edge,
                    "sample_point": effective_sample_point,
                }
            },
            "sample_point_applied": {"const": applied},
            "sample_point_ignored_for_negedge": {"const": ignored},
        }
        branch: dict[str, Any] = {
            "properties": properties,
            "required": [
                requested_key,
                effective_key,
                "sample_point_applied",
                "sample_point_ignored_for_negedge",
            ],
        }
        if ignored:
            properties["sample_point_not_applied_reason"] = {
                "const": NEGEDGE_SAMPLE_POINT_REASON
            }
            branch["required"].append(
                "sample_point_not_applied_reason"
            )
        else:
            branch["not"] = {
                "required": ["sample_point_not_applied_reason"]
            }
        variants.append(branch)

    add(
        "negedge",
        None,
        None,
        applied=False,
        ignored=False,
    )
    for requested_sample_point in ("before", "after"):
        add(
            "negedge",
            requested_sample_point,
            None,
            applied=False,
            ignored=True,
        )
    for edge in ("posedge", "dual"):
        add(
            edge,
            None,
            "before",
            applied=True,
            ignored=False,
        )
        for requested_sample_point in ("before", "after"):
            add(
                edge,
                requested_sample_point,
                requested_sample_point,
                applied=True,
                ignored=False,
            )
    return variants


def sampling_contract_schema() -> dict[str, Any]:
    schema = closed(
        {
            "requested": {"$ref": "#/$defs/samplingSelection"},
            "effective": {"$ref": "#/$defs/samplingSelection"},
            "sample_point_applied": {"type": "boolean"},
            "sample_point_ignored_for_negedge": {
                "type": "boolean"
            },
            "sample_point_not_applied_reason": {
                "const": NEGEDGE_SAMPLE_POINT_REASON
            },
        },
        (
            "requested",
            "effective",
            "sample_point_applied",
            "sample_point_ignored_for_negedge",
        ),
    )
    schema["allOf"] = [
        {
            "oneOf": sampling_resolution_variants(
                "requested",
                "effective",
            )
        }
    ]
    return schema


def clock_hit_resolution_variants() -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for requested_edge in ("posedge", "negedge", "dual"):
        variants.append(
            {
                "properties": {
                    "requested_sampling": {
                        "properties": {
                            "edge": {"const": requested_edge}
                        },
                        "required": ["edge"],
                    },
                    "clock_edge_kind": {"const": None},
                    "requested_any_edge_hit": {"const": False},
                    "requested_target_edge_hit": {"const": False},
                },
                "required": [
                    "requested_sampling",
                    "clock_edge_kind",
                    "requested_any_edge_hit",
                    "requested_target_edge_hit",
                ],
            }
        )
        for actual_edge in ("posedge", "negedge"):
            variants.append(
                {
                    "properties": {
                        "requested_sampling": {
                            "properties": {
                                "edge": {"const": requested_edge}
                            },
                            "required": ["edge"],
                        },
                        "clock_edge_kind": {
                            "const": actual_edge
                        },
                        "requested_any_edge_hit": {"const": True},
                        "requested_target_edge_hit": {
                            "const": (
                                requested_edge == "dual"
                                or requested_edge == actual_edge
                            )
                        },
                    },
                    "required": [
                        "requested_sampling",
                        "clock_edge_kind",
                        "requested_any_edge_hit",
                        "requested_target_edge_hit",
                    ],
                }
            )
    return variants


def clock_context_schema() -> dict[str, Any]:
    properties = {
        "clock": {"type": "string", "minLength": 1},
        "requested_sampling": {
            "$ref": "#/$defs/samplingSelection"
        },
        "effective_sampling": {
            "$ref": "#/$defs/samplingSelection"
        },
        "sample_point_applied": {"type": "boolean"},
        "sample_point_ignored_for_negedge": {"type": "boolean"},
        "sample_point_not_applied_reason": {
            "const": NEGEDGE_SAMPLE_POINT_REASON
        },
        "requested_time": {"type": "string", "minLength": 1},
        "requested_any_edge_hit": {"type": "boolean"},
        "clock_edge_kind": {
            "type": ["null", "string"],
            "enum": [None, "posedge", "negedge"],
        },
        "requested_target_edge_hit": {"type": "boolean"},
        "previous_sample_time": {
            "type": ["null", "string"],
            "minLength": 1,
        },
        "next_sample_time": {
            "type": ["null", "string"],
            "minLength": 1,
        },
        "bracket_complete": {"type": "boolean"},
    }
    schema = closed(
        properties,
        (
            "clock",
            "requested_sampling",
            "effective_sampling",
            "sample_point_applied",
            "sample_point_ignored_for_negedge",
            "requested_time",
            "requested_any_edge_hit",
            "clock_edge_kind",
            "requested_target_edge_hit",
            "previous_sample_time",
            "next_sample_time",
            "bracket_complete",
        ),
    )
    schema["allOf"] = [
        {
            "oneOf": sampling_resolution_variants(
                "requested_sampling",
                "effective_sampling",
            )
        },
        {
            "oneOf": [
                {
                    "properties": {
                        "bracket_complete": {"const": True},
                        "previous_sample_time": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "next_sample_time": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    "required": [
                        "bracket_complete",
                        "previous_sample_time",
                        "next_sample_time",
                    ],
                },
                {
                    "properties": {
                        "bracket_complete": {"const": False},
                    },
                    "required": [
                        "bracket_complete",
                        "previous_sample_time",
                        "next_sample_time",
                    ],
                    "anyOf": [
                        {
                            "properties": {
                                "previous_sample_time": {
                                    "type": "null"
                                }
                            }
                        },
                        {
                            "properties": {
                                "next_sample_time": {
                                    "type": "null"
                                }
                            }
                        },
                    ],
                },
            ]
        },
        {
            "oneOf": clock_hit_resolution_variants(),
        },
    ]
    return schema


def event_config_response_schema() -> dict[str, Any]:
    reset = closed(
        {
            "signal": {"type": "string", "minLength": 1},
            "polarity": {"enum": ["active_low", "active_high"]},
        },
        ("signal", "polarity"),
    )
    field = closed(
        {
            "signal": {"type": "string", "minLength": 1},
            "left": {"type": "integer", "minimum": 0},
            "right": {"type": "integer", "minimum": 0},
        },
        ("signal", "left", "right"),
    )
    return closed(
        {
            "name": {"type": "string", "minLength": 1},
            "clock": {"type": "string", "minLength": 1},
            "reset": reset,
            "edge": {"enum": ["posedge", "negedge", "dual"]},
            "sample_point": {"enum": ["before", "after"]},
            "signals": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "string",
                    "minLength": 1,
                },
                "x-dynamic-map": True,
            },
            "fields": {
                "type": "object",
                "additionalProperties": field,
                "x-dynamic-map": True,
            },
        },
        ("name", "clock", "edge", "signals", "fields"),
    )


def forbidden_properties(*names: str) -> dict[str, Any]:
    return {
        "not": {
            "anyOf": [
                {"required": [name]}
                for name in names
            ]
        }
    }


def completeness_properties() -> dict[str, Any]:
    return {
        "scan_complete": {"type": "boolean"},
        "analysis_complete": {"type": "boolean"},
        "response_truncated": {"type": "boolean"},
        "total_count": {"type": "integer", "minimum": 0},
        "returned_count": {"type": "integer", "minimum": 0},
        "truncation_scopes": array({"type": "string", "minLength": 1}),
    }


def completeness_required() -> tuple[str, ...]:
    return tuple(completeness_properties())


def logic_value_schema() -> dict[str, Any]:
    properties = {
        "value": {"type": "string", "minLength": 1},
        "known": {"type": "boolean"},
        "width": {"type": "integer", "minimum": 1},
        "bits": {"type": "string", "minLength": 1},
        "has_x": {"type": "boolean"},
        "has_z": {"type": "boolean"},
        "requested_value_format": {"const": "dec"},
        "effective_value_format": {"const": "bin"},
        "value_format_reason": {
            "const": "decimal cannot preserve per-bit X/Z"
        },
    }
    schema = closed(properties, ("value", "known"))
    schema["allOf"] = [
        {
            "oneOf": [
                {"required": ["width", "bits"]},
                forbidden_properties("width", "bits"),
            ]
        },
        {
            "oneOf": [
                {
                    "properties": {"known": {"const": True}},
                    "required": ["known"],
                    **forbidden_properties(
                        "has_x",
                        "has_z",
                        "requested_value_format",
                        "effective_value_format",
                        "value_format_reason",
                    ),
                },
                {
                    "properties": {
                        "known": {"const": False},
                        "has_x": {"type": "boolean"},
                        "has_z": {"type": "boolean"},
                    },
                    "required": ["known", "has_x", "has_z"],
                    "anyOf": [
                        {"properties": {"has_x": {"const": True}}},
                        {"properties": {"has_z": {"const": True}}},
                    ],
                    **forbidden_properties(
                        "requested_value_format",
                        "effective_value_format",
                        "value_format_reason",
                    ),
                },
                {
                    "properties": {
                        "known": {"const": False},
                        "has_x": {"type": "boolean"},
                        "has_z": {"type": "boolean"},
                        "requested_value_format": {"const": "dec"},
                        "effective_value_format": {"const": "bin"},
                        "value_format_reason": {
                            "const": (
                                "decimal cannot preserve per-bit X/Z"
                            )
                        },
                    },
                    "required": [
                        "known",
                        "has_x",
                        "has_z",
                        "requested_value_format",
                        "effective_value_format",
                        "value_format_reason",
                    ],
                    "anyOf": [
                        {"properties": {"has_x": {"const": True}}},
                        {"properties": {"has_z": {"const": True}}},
                    ],
                },
            ]
        },
    ]
    return schema


def logic_value_map_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": {"$ref": "#/$defs/logicValue"},
        "x-dynamic-map": True,
    }


def event_record_schema() -> dict[str, Any]:
    return closed(
        {
            "time": {"type": "string", "minLength": 1},
            "signals": logic_value_map_schema(),
            "fields": logic_value_map_schema(),
        },
        ("time", "signals", "fields"),
    )


def event_summary_properties() -> dict[str, Any]:
    return {
        "sample_count": {"type": "integer", "minimum": 0},
        "mode": {"enum": ["first", "last", "all", "export"]},
        "inline": {"type": "boolean"},
        "sampling_mode": {"const": "clock_edge"},
        "clock": {"type": "string", "minLength": 1},
        "sample_time_semantics": {"const": "time is sample_time"},
        "first": {"type": "string", "minLength": 1},
        "last": {"type": "string", "minLength": 1},
        "begin": {"type": "string", "minLength": 1},
        "end": {"type": "string", "minLength": 1},
        **completeness_properties(),
    }


def require_nonempty_first_last(
    discriminator: str,
) -> dict[str, Any]:
    return {
        "oneOf": [
            {
                "properties": {discriminator: {"const": 0}},
                "required": [discriminator],
                **forbidden_properties("first", "last"),
            },
            {
                "properties": {
                    discriminator: {
                        "type": "integer",
                        "minimum": 1,
                    }
                },
                "required": [discriminator, "first", "last"],
            },
        ]
    }


def event_find_summary_schema() -> dict[str, Any]:
    properties = event_summary_properties()
    properties["mode"] = {"enum": ["first", "last", "all"]}
    required = (
        "sample_count",
        "mode",
        "inline",
        "sampling_mode",
        "clock",
        "sample_time_semantics",
        "begin",
        "end",
        *completeness_required(),
    )
    schema = closed(properties, required)
    schema["allOf"] = [require_nonempty_first_last("total_count")]
    return schema


def event_find_data_schema() -> dict[str, Any]:
    return closed(
        {
            "events": array({"$ref": "#/$defs/eventRecord"}),
            "sampling": {"$ref": "#/$defs/samplingContract"},
        },
        ("events", "sampling"),
    )


def event_aggregate_schema() -> dict[str, Any]:
    return closed(
        {
            "count": {"type": "integer", "minimum": 0},
            "groups": {
                "type": "object",
                "additionalProperties": {
                    "type": "integer",
                    "minimum": 1,
                },
                "x-dynamic-map": True,
            },
            "group_count": {"type": "integer", "minimum": 0},
        },
        ("count", "groups", "group_count"),
    )


def event_export_summary_schema() -> dict[str, Any]:
    properties = {
        **event_summary_properties(),
        "status": {"enum": ["preview", "written"]},
        "output_written": {"type": "boolean"},
        "row_count": {"type": "integer", "minimum": 0},
        "line_limit": {"type": "integer"},
        "output": closed(
            {
                "path": {"type": "string", "minLength": 1},
                "file_format": {"const": "json"},
            },
            ("path", "file_format"),
        ),
    }
    properties["mode"] = {"const": "export"}
    required = (
        "sample_count",
        "mode",
        "inline",
        "sampling_mode",
        "clock",
        "sample_time_semantics",
        "begin",
        "end",
        "status",
        "output_written",
        "row_count",
        "line_limit",
        *completeness_required(),
    )
    schema = closed(properties, required)
    schema["allOf"] = [
        require_nonempty_first_last("row_count"),
        {
            "oneOf": [
                {
                    "properties": {
                        "output_written": {"const": False},
                        "status": {"const": "preview"},
                    },
                    "required": ["output_written", "status"],
                    **forbidden_properties("output"),
                },
                {
                    "properties": {
                        "output_written": {"const": True},
                        "status": {"const": "written"},
                    },
                    "required": [
                        "output_written",
                        "status",
                        "output",
                    ],
                },
            ]
        },
    ]
    return schema


def event_export_data_schema() -> dict[str, Any]:
    return closed(
        {
            "events": array({"$ref": "#/$defs/eventRecord"}),
            "aggregate": {"$ref": "#/$defs/eventAggregate"},
            "sampling": {"$ref": "#/$defs/samplingContract"},
        },
        ("sampling",),
    )


def counter_predicate_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            {"type": "string", "minLength": 1},
            closed(
                {
                    "expr": {"type": "string", "minLength": 1},
                    "signals": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "x-dynamic-map": True,
                    },
                },
                ("expr", "signals"),
            ),
        ]
    }


def counter_evidence_schema() -> dict[str, Any]:
    common = {
        "time": {"type": "string", "minLength": 1},
        "kind": {
            "enum": [
                "initial",
                "value_change",
                "unknown_valid",
                "unknown_counter",
            ]
        },
        "value": {
            "anyOf": [
                {"type": "null"},
                {"$ref": "#/$defs/logicValue"},
            ]
        },
    }
    schema = closed(common, common)
    schema["oneOf"] = [
        {
            "properties": {
                "kind": {
                    "enum": ["unknown_valid", "unknown_counter"]
                },
                "value": {"type": "null"},
            }
        },
        {
            "properties": {
                "kind": {"enum": ["initial", "value_change"]},
                "value": {"$ref": "#/$defs/logicValue"},
            }
        },
    ]
    return schema


def counter_statistics_summary_schema() -> dict[str, Any]:
    properties = {
        "sample_count": {"type": "integer", "minimum": 0},
        "valid_count": {"type": "integer", "minimum": 0},
        "sampling_mode": {"const": "clock_edge"},
        "clock": {"type": "string", "minLength": 1},
        "sample_time_semantics": {"const": "time is sample_time"},
        "begin": {"type": "string", "minLength": 1},
        "end": {"type": "string", "minLength": 1},
        "valid_false_count": {"type": "integer", "minimum": 0},
        "unknown_count": {"type": "integer", "minimum": 0},
        "min_value": {"$ref": "#/$defs/logicValue"},
        "max_value": {"$ref": "#/$defs/logicValue"},
        "average_value": {
            "type": "string",
            "pattern": "^[0-9]+(?:\\.[0-9]+)?$",
        },
        **completeness_properties(),
    }
    required = (
        "sample_count",
        "valid_count",
        "sampling_mode",
        "clock",
        "sample_time_semantics",
        "begin",
        "end",
        "valid_false_count",
        "unknown_count",
        *completeness_required(),
    )
    schema = closed(properties, required)
    schema["oneOf"] = [
        {
            "properties": {"valid_count": {"const": 0}},
            "required": ["valid_count"],
            **forbidden_properties(
                "min_value",
                "max_value",
                "average_value",
            ),
        },
        {
            "properties": {
                "valid_count": {"type": "integer", "minimum": 1}
            },
            "required": [
                "valid_count",
                "min_value",
                "max_value",
                "average_value",
            ],
        },
    ]
    return schema


def counter_statistics_data_schema() -> dict[str, Any]:
    return closed(
        {
            "cnt": {"type": "string", "minLength": 1},
            "vld": {"$ref": "#/$defs/counterPredicate"},
            "evidence": array({"$ref": "#/$defs/counterEvidence"}),
            "min_count": {"type": "integer", "minimum": 1},
            "max_count": {"type": "integer", "minimum": 1},
            "min_first_time": {"type": "string", "minLength": 1},
            "max_first_time": {"type": "string", "minLength": 1},
            "sampling": {"$ref": "#/$defs/samplingContract"},
        },
        ("cnt", "vld", "evidence", "sampling"),
    )


def signal_statistics_evidence_schema() -> dict[str, Any]:
    return closed(
        {
            "time": {"type": "string", "minLength": 1},
            "kind": {"enum": ["initial", "value_change", "unknown"]},
            "value": {"$ref": "#/$defs/logicValue"},
        },
        ("time", "kind", "value"),
    )


def signal_activity_schema(clock_sampled: bool) -> dict[str, Any]:
    return closed(
        {
            "high_burst_count": {"type": "integer", "minimum": 0},
            "first_high_time": {
                "type": ["null", "string"],
                "minLength": 1,
            },
            "last_high_time": {
                "type": ["null", "string"],
                "minLength": 1,
            },
            "last_fall_time": {
                "type": ["null", "string"],
                "minLength": 1,
            },
            "max_high_cycles": (
                {"type": "integer", "minimum": 0}
                if clock_sampled
                else {"type": "null"}
            ),
        },
        (
            "high_burst_count",
            "first_high_time",
            "last_high_time",
            "last_fall_time",
            "max_high_cycles",
        ),
    )


def raw_signal_statistics_summary_schema() -> dict[str, Any]:
    properties = {
        "signal": {"type": "string", "minLength": 1},
        "sampling_mode": {"const": "raw_value_changes"},
        "begin": {"type": "string", "minLength": 1},
        "end": {"type": "string", "minLength": 1},
        "actual_transition_count": {
            "type": "integer",
            "minimum": 0,
        },
        **completeness_properties(),
    }
    return closed(properties, properties)


def raw_signal_statistics_data_schema() -> dict[str, Any]:
    return closed(
        {
            "includes_initial_value": {"type": "boolean"},
            "initial_value": {"$ref": "#/$defs/logicValue"},
            "final_value": {"$ref": "#/$defs/logicValue"},
            "first_change_time": {"type": "string", "minLength": 1},
            "last_change_time": {"type": "string", "minLength": 1},
            "activity": {"$ref": "#/$defs/rawSignalActivity"},
            "evidence": array(
                {"$ref": "#/$defs/signalStatisticsEvidence"}
            ),
        },
        ("includes_initial_value", "activity", "evidence"),
    )


def clock_signal_statistics_summary_schema() -> dict[str, Any]:
    properties = {
        "signal": {"type": "string", "minLength": 1},
        "sampling_mode": {"const": "clock_edge"},
        "clock": {"type": "string", "minLength": 1},
        "sample_time_semantics": {"const": "time is sample_time"},
        "sample_count": {"type": "integer", "minimum": 0},
        "known_count": {"type": "integer", "minimum": 0},
        "unknown_count": {"type": "integer", "minimum": 0},
        "begin": {"type": "string", "minLength": 1},
        "end": {"type": "string", "minLength": 1},
        **completeness_properties(),
    }
    return closed(properties, properties)


def clock_signal_statistics_data_schema() -> dict[str, Any]:
    properties = {
        "evidence": array(
            {"$ref": "#/$defs/signalStatisticsEvidence"}
        ),
        "transition_count": {"type": "integer", "minimum": 0},
        "first": {"$ref": "#/$defs/logicValue"},
        "final": {"$ref": "#/$defs/logicValue"},
        "min": {"$ref": "#/$defs/logicValue"},
        "max": {"$ref": "#/$defs/logicValue"},
        "low_cycles": {"type": "integer", "minimum": 0},
        "high_cycles": {"type": "integer", "minimum": 0},
        "high_ratio": {"type": "number", "minimum": 0, "maximum": 1},
        "first_change_time": {"type": "string", "minLength": 1},
        "last_change_time": {"type": "string", "minLength": 1},
        "activity": {"$ref": "#/$defs/clockSignalActivity"},
        "sampling": {"$ref": "#/$defs/samplingContract"},
    }
    schema = closed(
        properties,
        ("evidence", "transition_count", "sampling"),
    )
    schema["oneOf"] = [
        {
            "properties": {"transition_count": {"const": 0}},
            "required": ["transition_count"],
            **forbidden_properties(
                "first_change_time",
                "last_change_time",
            ),
        },
        {
            "properties": {
                "transition_count": {
                    "type": "integer",
                    "minimum": 1,
                }
            },
            "required": [
                "transition_count",
                "first_change_time",
                "last_change_time",
            ],
        },
    ]
    return schema


def ready_without_valid_interval_schema() -> dict[str, Any]:
    return closed(
        {
            "begin": {"type": "string", "minLength": 1},
            "end": {"type": "string", "minLength": 1},
            "cycle_count": {"type": "integer", "minimum": 1},
            "open_at_window_end": {"const": True},
        },
        ("begin", "end", "cycle_count"),
    )


def protocol_handshake_finding_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            closed(
                {
                    "type": {"const": "ready_without_valid"},
                    "severity": {"const": "info"},
                    "time": {"type": "string", "minLength": 1},
                },
                ("type", "severity", "time"),
            ),
            closed(
                {
                    "type": {
                        "const": "valid_dropped_before_handshake"
                    },
                    "severity": {"const": "error"},
                    "begin": {"type": "string", "minLength": 1},
                    "time": {"type": "string", "minLength": 1},
                    "observed_valid": {
                        "$ref": "#/$defs/logicValue"
                    },
                    "reason": {"type": "string", "minLength": 1},
                },
                (
                    "type",
                    "severity",
                    "begin",
                    "time",
                    "observed_valid",
                    "reason",
                ),
            ),
            closed(
                {
                    "type": {
                        "const": "data_changed_while_stalled"
                    },
                    "severity": {"const": "warning"},
                    "begin": {"type": "string", "minLength": 1},
                    "time": {"type": "string", "minLength": 1},
                    "signal": {"type": "string", "minLength": 1},
                },
                ("type", "severity", "begin", "time", "signal"),
            ),
            closed(
                {
                    "type": {"const": "long_stall"},
                    "severity": {"const": "warning"},
                    "begin": {"type": "string", "minLength": 1},
                    "end": {"type": "string", "minLength": 1},
                    "cycles": {"type": "integer", "minimum": 1},
                    "open_at_window_end": {"const": True},
                },
                ("type", "severity", "begin", "end", "cycles"),
            ),
        ]
    }


def protocol_handshake_summary_schema() -> dict[str, Any]:
    properties = {
        "sampling_mode": {"const": "clock_edge"},
        "clock": {"type": "string", "minLength": 1},
        "sample_time_semantics": {"const": "time is sample_time"},
        "sample_count": {"type": "integer", "minimum": 0},
        "transfer_count": {"type": "integer", "minimum": 0},
        "max_stall_cycles": {"type": "integer", "minimum": 0},
        "ready_without_valid_cycles": {
            "type": "integer",
            "minimum": 0,
        },
        "ready_without_valid_reporting": {
            "enum": ["summary", "intervals", "all"]
        },
        "ready_without_valid_interval_count": {
            "type": "integer",
            "minimum": 0,
        },
        "data_stability_violations": {
            "type": "integer",
            "minimum": 0,
        },
        "require_valid_hold_until_handshake": {"type": "boolean"},
        "valid_hold_violations": {"type": "integer", "minimum": 0},
        "valid_wait_open_at_window_end": {"type": "boolean"},
        **completeness_properties(),
    }
    return closed(properties, properties)


def protocol_handshake_data_schema() -> dict[str, Any]:
    return closed(
        {
            "findings": array(
                {"$ref": "#/$defs/protocolHandshakeFinding"}
            ),
            "ready_without_valid_intervals": array(
                {"$ref": "#/$defs/readyWithoutValidInterval"}
            ),
            "sampling": {"$ref": "#/$defs/samplingContract"},
        },
        ("findings", "sampling"),
    )


def xbit_hints_schema() -> dict[str, Any]:
    slice_schema = closed(
        {
            "index": {"type": "integer", "minimum": 0},
            "range": {"type": "string", "minLength": 1},
        },
        ("index", "range"),
    )
    return closed(
        {
            "status": {"const": "ready"},
            "signal": {"type": "string", "minLength": 1},
            "raw_value": {"type": "string", "minLength": 1},
            "chunk_width": {"type": "integer", "minimum": 1},
            "count": {"type": "integer", "minimum": 1},
            "slices": {
                "type": "array",
                "minItems": 1,
                "items": slice_schema,
            },
            "commands": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
        (
            "status",
            "signal",
            "raw_value",
            "chunk_width",
            "count",
            "slices",
            "commands",
        ),
    )


def value_at_data_schema() -> dict[str, Any]:
    signal_entry = closed(
        {
            "key": {"type": "string", "minLength": 1},
            "kind": {"const": "signal"},
            "path": {"type": "string", "minLength": 1},
        },
        ("key", "kind", "path"),
    )
    expression_entry = closed(
        {
            "key": {"type": "string", "minLength": 1},
            "kind": {"const": "expression"},
            "expression": {"type": "string", "minLength": 1},
            "dependencies": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            },
        },
        ("key", "kind", "expression", "dependencies"),
    )
    ok_cell = closed(
        {
            "key": {"type": "string", "minLength": 1},
            "status": {"const": "ok"},
            "value": {"$ref": "#/$defs/logicValue"},
            "xbit_hints": {"$ref": "#/$defs/xbitHints"},
        },
        ("key", "status", "value"),
    )
    unavailable_cell = closed(
        {
            "key": {"type": "string", "minLength": 1},
            "status": {
                "enum": ["signal_not_found", "missing_value"]
            },
        },
        ("key", "status"),
    )
    dependency_cell = closed(
        {
            "key": {"type": "string", "minLength": 1},
            "status": {"const": "missing_dependency"},
            "missing_dependencies": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
        },
        ("key", "status", "missing_dependencies"),
    )
    value_cell = {
        "oneOf": [ok_cell, unavailable_cell, dependency_cell]
    }
    sample_common = {
        "time": {"type": "string", "minLength": 1},
        "sampling_mode": {"enum": ["raw_time", "clock_sampled"]},
        "values": array(value_cell) | {"minItems": 1},
        "clock_context": {"$ref": "#/$defs/clockContext"},
    }
    sample = {
        "oneOf": [
            closed(
                {
                    **sample_common,
                    "sampling_mode": {"const": "raw_time"},
                },
                ("time", "sampling_mode", "values"),
            )
            | forbidden_properties("clock_context"),
            closed(
                {
                    **sample_common,
                    "sampling_mode": {"const": "clock_sampled"},
                },
                ("time", "sampling_mode", "values", "clock_context"),
            ),
        ]
    }
    return closed(
        {
            "entries": array(
                {"oneOf": [signal_entry, expression_entry]}
            ) | {"minItems": 1},
            "samples": array(sample) | {"minItems": 1},
        },
        ("entries", "samples"),
    )


def verify_check_schema() -> dict[str, Any]:
    common = {
        "time": {"type": "string", "minLength": 1},
        "expr": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "known": {"type": "boolean"},
        "status": {"enum": ["pass", "fail", "unknown"]},
        "pass": {"type": ["boolean", "null"]},
        "value": {"$ref": "#/$defs/logicValue"},
        "error_code": {"type": "string", "minLength": 1},
        "error": {"type": "string", "minLength": 1},
    }
    base_required = ("time", "expr", "known", "status", "pass")
    return {
        "oneOf": [
            closed(
                common,
                (*base_required, "value"),
            )
            | {
                "properties": {
                    **common,
                    "known": {"const": True},
                    "status": {"enum": ["pass", "fail"]},
                    "pass": {"type": "boolean"},
                },
                **forbidden_properties("error_code", "error"),
            },
            closed(
                common,
                (*base_required, "value"),
            )
            | {
                "properties": {
                    **common,
                    "known": {"const": False},
                    "status": {"const": "unknown"},
                    "pass": {"type": "null"},
                },
                **forbidden_properties("error_code", "error"),
            },
            closed(
                common,
                (*base_required, "error_code", "error"),
            )
            | {
                "properties": {
                    **common,
                    "known": {"const": False},
                    "status": {"const": "unknown"},
                    "pass": {"type": "null"},
                },
                **forbidden_properties("value"),
            },
        ]
    }


def sampled_payload_schema(with_value: bool) -> dict[str, Any]:
    properties = {
        "alias": {"type": "string", "minLength": 1},
        "signal": {"type": "string", "minLength": 1},
    }
    required = ["alias", "signal"]
    if with_value:
        properties["value"] = {"$ref": "#/$defs/logicValue"}
        required.append("value")
    return closed(properties, required)


def nullable_time_schema() -> dict[str, Any]:
    return {"type": ["null", "string"], "minLength": 1}


def sampled_pulse_finding_schema() -> dict[str, Any]:
    edge_fields = {
        "previous_sample_edge": nullable_time_schema(),
        "next_sample_edge": nullable_time_schema(),
        "nearest_sample_edge": nullable_time_schema(),
    }
    sampled_value = {
        "anyOf": [
            {"type": "null"},
            {"$ref": "#/$defs/logicValue"},
        ]
    }
    return {
        "oneOf": [
            closed(
                {
                    "type": {"const": "unsampled_valid_pulse"},
                    "severity": {"const": "warning"},
                    "raw_begin": {"type": "string", "minLength": 1},
                    "raw_end": {"type": "string", "minLength": 1},
                    **edge_fields,
                    "raw_valid": {"$ref": "#/$defs/logicValue"},
                    "sampled_valid": sampled_value,
                    "sampled_payloads": array(
                        {"$ref": "#/$defs/sampledPayloadValue"}
                    ),
                    "reason": {"type": "string", "minLength": 1},
                },
                (
                    "type",
                    "severity",
                    "raw_begin",
                    "raw_end",
                    *edge_fields,
                    "raw_valid",
                    "sampled_valid",
                    "sampled_payloads",
                    "reason",
                ),
            ),
            closed(
                {
                    "type": {
                        "const": "payload_changed_without_sampled_valid"
                    },
                    "severity": {"const": "warning"},
                    "raw_time": {"type": "string", "minLength": 1},
                    **edge_fields,
                    "payload": {
                        "$ref": "#/$defs/sampledPayloadValue"
                    },
                    "sampled_valid": sampled_value,
                    "sampled_payloads": array(
                        {"$ref": "#/$defs/sampledPayloadValue"}
                    ),
                    "reason": {"type": "string", "minLength": 1},
                },
                (
                    "type",
                    "severity",
                    "raw_time",
                    *edge_fields,
                    "payload",
                    "sampled_valid",
                    "sampled_payloads",
                    "reason",
                ),
            ),
        ]
    }


def sampled_pulse_data_schema() -> dict[str, Any]:
    properties = {
        "valid": {"type": "string", "minLength": 1},
        "payloads": array({"$ref": "#/$defs/sampledPayload"}),
        "begin": {"type": "string", "minLength": 1},
        "end": {"type": "string", "minLength": 1},
        "sampled_low_cycles": {"type": "integer", "minimum": 0},
        "sampled_unknown_cycles": {"type": "integer", "minimum": 0},
        "raw_valid_transition_count": {
            "type": "integer",
            "minimum": 0,
        },
        "payload_transition_count": {
            "type": "integer",
            "minimum": 0,
        },
        "first_sampled_high_time": nullable_time_schema(),
        "last_sampled_high_time": nullable_time_schema(),
        "findings": array({"$ref": "#/$defs/sampledPulseFinding"}),
        "sampling": {"$ref": "#/$defs/samplingContract"},
    }
    return closed(properties, properties)


def window_condition_schema() -> dict[str, Any]:
    properties = {
        "expr": {"type": "string", "minLength": 1},
        "mode": {"enum": ["always", "eventually", "never"]},
        "passed": {"type": "boolean"},
        "pass_samples": {"type": "integer", "minimum": 0},
        "failed_samples": {"type": "integer", "minimum": 0},
        "unknown_samples": {"type": "integer", "minimum": 0},
    }
    return closed(properties, properties)


def window_finding_schema() -> dict[str, Any]:
    return closed(
        {
            "time": {"type": "string", "minLength": 1},
            "expr": {"type": "string", "minLength": 1},
            "mode": {"enum": ["always", "eventually", "never"]},
            "status": {"enum": ["fail", "unknown"]},
            "signals": logic_value_map_schema(),
        },
        ("time", "expr", "mode", "status", "signals"),
    )


def window_summary_schema() -> dict[str, Any]:
    scanned_range = closed(
        {
            "begin": nullable_time_schema(),
            "end": nullable_time_schema(),
        },
        ("begin", "end"),
    )
    properties = {
        "execution_ok": {"const": True},
        "verdict": {"enum": ["pass", "fail", "inconclusive"]},
        "all_passed": {"type": ["boolean", "null"]},
        "sample_count": {"type": "integer", "minimum": 0},
        "failed_samples": {"type": "integer", "minimum": 0},
        "unknown_samples": {"type": "integer", "minimum": 0},
        "proof_begin": {"type": "string", "minLength": 1},
        "proof_end": {"type": "string", "minLength": 1},
        "scanned_range": scanned_range,
        "stop_reason": {
            "enum": ["decisive_result", "max_samples", "window_end"]
        },
        "sampling_mode": {"const": "clock_edge"},
        "clock": {"type": "string", "minLength": 1},
        "sample_time_semantics": {"const": "time is sample_time"},
        **completeness_properties(),
    }
    schema = closed(properties, properties)
    schema["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {
                        "analysis_complete": {"const": True},
                        "all_passed": {"type": "boolean"},
                        "verdict": {"enum": ["pass", "fail"]},
                    }
                },
                {
                    "properties": {
                        "analysis_complete": {"const": False},
                        "all_passed": {"type": "null"},
                        "verdict": {"const": "inconclusive"},
                    }
                },
            ]
        },
        {
            "oneOf": [
                {
                    "properties": {
                        "sample_count": {"const": 0},
                        "scanned_range": {
                            "properties": {
                                "begin": {"type": "null"},
                                "end": {"type": "null"},
                            }
                        },
                    }
                },
                {
                    "properties": {
                        "sample_count": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "scanned_range": {
                            "properties": {
                                "begin": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                                "end": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                            }
                        },
                    }
                },
            ]
        },
    ]
    return schema


def window_data_schema() -> dict[str, Any]:
    return closed(
        {
            "conditions": array({"$ref": "#/$defs/windowCondition"}),
            "findings": array({"$ref": "#/$defs/windowFinding"}),
            "sampling": {"$ref": "#/$defs/samplingContract"},
        },
        ("conditions", "findings", "sampling"),
    )


def apb_config_response_schema() -> dict[str, Any]:
    reset = closed(
        {
            "signal": {"type": "string", "minLength": 1},
            "polarity": {"enum": ["active_low", "active_high"]},
        },
        ("signal", "polarity"),
    )
    required = (
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
    )
    properties = {
        "name": {"type": "string", "minLength": 1},
        "sampling_mode": {"const": "clock_edge"},
        "clock": {"type": "string", "minLength": 1},
        "edge": {"enum": ["posedge", "negedge", "dual"]},
        "sample_point": {"enum": ["before", "after"]},
        "reset": reset,
        "paddr": {"type": "string", "minLength": 1},
        "psel": {"type": "string", "minLength": 1},
        "penable": {"type": "string", "minLength": 1},
        "pwrite": {"type": "string", "minLength": 1},
        "pwdata": {"type": "string", "minLength": 1},
        "prdata": {"type": "string", "minLength": 1},
        "pready": {"type": "string", "minLength": 1},
        "pslverr": {"type": "string", "minLength": 1},
    }
    negedge = copy.deepcopy(properties)
    negedge.pop("sample_point")
    negedge["edge"] = {"const": "negedge"}
    sampled = copy.deepcopy(properties)
    sampled["edge"] = {"enum": ["posedge", "dual"]}
    return {
        "oneOf": [
            closed(negedge, required),
            closed(sampled, required + ("sample_point",)),
        ]
    }


def add_common_blocks_to_data_schema(
    action: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(schema)
    if action not in COMMON_BLOCK_ACTIONS:
        return result

    def add_to_root(node: dict[str, Any]) -> None:
        if node.get("type") == "object" and isinstance(
            node.get("properties"), dict
        ):
            node["properties"]["common_blocks"] = array(
                {"$ref": "#/$defs/commonBlock"}
            )
            return
        for keyword in ("allOf", "anyOf", "oneOf"):
            variants = node.get(keyword)
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if isinstance(variant, dict):
                    add_to_root(variant)

    add_to_root(result)
    return result


def action_descriptor_schema() -> dict[str, Any]:
    alternative = closed(
        {
            "action": {"type": "string", "minLength": 1},
            "when": {"type": "string", "minLength": 1},
        },
        ("action", "when"),
    )
    variant = closed(
        {
            "name": {"type": "string", "minLength": 1},
            "requires": {
                "enum": ["none", "design", "waveform", "combined", "any", "session"]
            },
            "required_args": array({"type": "string"}),
            "forbidden_args": array({"type": "string"}),
        },
        ("name", "requires", "required_args", "forbidden_args"),
    )
    properties = {
        "name": {"type": "string"},
        "category": {"type": "string"},
        "status": {"type": "string"},
        "requires": {"type": "string"},
        "request_schema": {"type": "string"},
        "response_schema": {"type": "string"},
        "handler_kind": {"type": "string"},
        "request_examples": array({"type": "string"}),
        "response_examples": array({"type": "string"}),
        "required_args": array({"type": "string"}),
        "allowed_values": {
            "type": "object",
            "additionalProperties": array({"type": "string"}),
            "x-dynamic-map": True,
        },
        "description_en": {"type": "string", "minLength": 1},
        "description_zh": {"type": "string", "minLength": 1},
        "purposes": array({"type": "string"}),
        "use_when": array({"type": "string"}),
        "do_not_use_when": array({"type": "string"}),
        "alternatives": array(alternative),
        "resource_variants": array(variant),
    }
    return closed(properties, properties)


def issue_schema() -> dict[str, Any]:
    return closed(
        {
            "code": {"type": "string"},
            "severity": {"type": "string"},
            "message": {"type": "string"},
            "path": {"type": "string"},
            "field": {"type": "string"},
            "signal": {"type": "string"},
            "details": JSON_VALUE_REF,
        }
    )


def empty_array_item_schema(action: str, pointer: str) -> dict[str, Any]:
    field = pointer.rsplit("/", 1)[-1]
    if action == "session.list" and pointer == DATA_POINTER + "/sessions":
        return {"$ref": "#/$defs/sessionListRecord"}
    if action == "actions" and pointer.startswith(DATA_POINTER + "/modes/"):
        return {"type": "string"}
    if field in {"failed_indexes"}:
        return {"type": "integer", "minimum": 0}
    if field in {
        "failed_codes",
        "failed_layers",
        "constraints",
        "limitations",
        "truncation_scopes",
    }:
        return {"type": "string"}
    if field == "findings":
        return common_finding_schema()
    if field == "issues":
        return issue_schema()
    if field == "examples":
        return closed(
            {
                "kind": {"type": "string"},
                "path": {"type": "string"},
                "description": {"type": "string"},
                "value": JSON_VALUE_REF,
            }
        )
    raise ValueError(
        f"{action}: empty array at {pointer} needs an explicit item contract"
    )


def explicit_schema(action: str, pointer: str) -> dict[str, Any] | None:
    non_sampling_schema_override = (
        non_sampling_explicit_response_schema(action, pointer)
    )
    if non_sampling_schema_override is not None:
        return non_sampling_schema_override
    session_schema_override = session_explicit_response_schema(
        action,
        pointer,
    )
    if session_schema_override is not None:
        return session_schema_override
    if action == "event.find":
        if pointer == SUMMARY_POINTER:
            return event_find_summary_schema()
        if pointer == DATA_POINTER:
            return event_find_data_schema()
    if action == "event.export":
        if pointer == SUMMARY_POINTER:
            return event_export_summary_schema()
        if pointer == DATA_POINTER:
            return event_export_data_schema()
    if action == "counter.statistics":
        if pointer == SUMMARY_POINTER:
            return counter_statistics_summary_schema()
        if pointer == DATA_POINTER:
            return counter_statistics_data_schema()
    if action == "signal.statistics":
        if pointer == SUMMARY_POINTER:
            return {
                "oneOf": [
                    raw_signal_statistics_summary_schema(),
                    clock_signal_statistics_summary_schema(),
                ]
            }
        if pointer == DATA_POINTER:
            return {
                "oneOf": [
                    raw_signal_statistics_data_schema(),
                    clock_signal_statistics_data_schema(),
                ]
            }
    if action == "protocol.handshake.inspect":
        if pointer == SUMMARY_POINTER:
            return protocol_handshake_summary_schema()
        if pointer == DATA_POINTER:
            return protocol_handshake_data_schema()
    if action == "signal.sampled_pulse.inspect" and pointer == DATA_POINTER:
        return sampled_pulse_data_schema()
    if action == "window.verify":
        if pointer == SUMMARY_POINTER:
            return window_summary_schema()
        if pointer == DATA_POINTER:
            return window_data_schema()
    if action == "value.at" and pointer == DATA_POINTER:
        return value_at_data_schema()
    if (
        action in CLOCK_CONTEXT_ACTIONS
        and pointer == DATA_POINTER + "/clock_context"
    ):
        return {"$ref": "#/$defs/clockContext"}
    if (
        action in SAMPLING_CONTRACT_ACTIONS
        and pointer == DATA_POINTER + "/sampling"
    ):
        return {"$ref": "#/$defs/samplingContract"}
    if action == "scope.roots":
        if pointer == SUMMARY_POINTER:
            return scope_roots_summary_schema()
        if pointer == DATA_POINTER:
            return scope_roots_data_schema()
    if action == "schema" and pointer in {
        DATA_POINTER + "/schema",
        DATA_POINTER + "/examples/*/value",
    }:
        return copy.deepcopy(JSON_VALUE_REF)
    if action == "schema" and pointer == SUMMARY_POINTER:
        return closed(
            {
                "action": {"type": "string", "minLength": 1},
                "kind": {"enum": ["request", "response"]},
                "response_detail": {"enum": ["summary", "child", "full"]},
                "selected_child": {
                    "type": ["string", "null"],
                },
            },
            ("action", "kind", "response_detail", "selected_child"),
        )
    if action == "schema" and pointer == DATA_POINTER + "/relation":
        return {
            "anyOf": [
                {"type": "null"},
                closed(
                    {
                        "full_schema_path": {"type": "string", "minLength": 1},
                        "completeness": {
                            "enum": [
                                "outer-envelope-only",
                                "selected-child-response",
                                "complete-recursive-union",
                            ]
                        },
                        "child_selector": {"const": "args.child_action"},
                    },
                    ("full_schema_path", "completeness", "child_selector"),
                ),
            ]
        }
    if action == "apb.config.load" and pointer == DATA_POINTER + "/config":
        return apb_config_response_schema()
    if action == "apb.config.list" and pointer in {
        DATA_POINTER + "/config",
        DATA_POINTER + "/configs/*",
    }:
        return apb_config_response_schema()
    if action in {"event.config.load", "event.config.list"} and (
        pointer == DATA_POINTER + "/config"
    ):
        return {"$ref": "#/$defs/eventConfig"}
    if action == "value.at" and pointer.endswith(
        "/xbit_hints"
    ):
        return {"$ref": "#/$defs/xbitHints"}
    if (
        action in {
            "list.load",
            "apb.config.load",
            "stream.config.load",
            "axi.config.load",
        }
        and pointer == DATA_POINTER + "/recommended_actions"
    ):
        return array(
            closed(
                {
                    "action": {"type": "string", "minLength": 1},
                    "purpose": {"type": "string", "minLength": 1},
                },
                ("action", "purpose"),
            )
        )
    if action == "expr.eval_at":
        if pointer == DATA_POINTER + "/expr_value":
            return {"type": ["boolean", "null"]}
        if pointer == DATA_POINTER + "/operands/*":
            return closed(
                {
                    "alias": {"type": "string", "minLength": 1},
                    "signal": {"type": "string", "minLength": 1},
                    "value": {"$ref": "#/$defs/logicValue"},
                },
                ("alias", "signal", "value"),
            )
        if pointer == DATA_POINTER + "/expr_samples":
            return closed(
                {
                    "before": {
                        "enum": ["true", "false", "unknown", "missing_edge"]
                    },
                    "middle": {
                        "enum": ["true", "false", "unknown"]
                    },
                    "after": {
                        "enum": ["true", "false", "unknown", "missing_edge"]
                    },
                },
                ("before", "middle", "after"),
            )
    if action == "verify.conditions" and pointer == DATA_POINTER + "/checks/*":
        return {"$ref": "#/$defs/verifyCheck"}
    if action == "actions" and pointer == DATA_POINTER + "/actions/*":
        return {
            "anyOf": [
                {"type": "string"},
                action_descriptor_schema(),
            ]
        }
    if action == "actions" and pointer == DATA_POINTER + "/filters":
        return actions_filter_schema()
    if action == "session.open" and pointer == (
        DATA_POINTER + "/run_manifest"
    ):
        return {
            "anyOf": [
                {"type": "null"},
                {"$ref": "#/$defs/runManifest"},
            ]
        }
    if action == "session.list" and pointer == DATA_POINTER + "/sessions/*":
        return {"$ref": "#/$defs/sessionListRecord"}
    return None


def success_response_conditions(action: str) -> list[dict[str, Any]]:
    if action == "session.open":
        run_manifest_is_present = {
            "properties": {
                "data": {
                    "properties": {
                        "run_manifest": {
                            "not": {"type": "null"}
                        }
                    },
                    "required": ["run_manifest"],
                }
            },
            "required": ["data"],
        }
        daidir_condition = {
            "properties": {
                "session": {
                    "properties": {
                        "daidir": {"type": "string"}
                    },
                    "required": ["daidir"],
                }
            },
            "required": ["session"],
        }
        resources_daidir_required = {
            "properties": {
                "data": {
                    "properties": {
                        "run_manifest": {
                            "properties": {
                                "resources": {
                                    "required": ["daidir"]
                                }
                            },
                            "required": ["resources"],
                        }
                    },
                    "required": ["run_manifest"],
                }
            },
            "required": ["data"],
        }
        resources_daidir_forbidden = {
            "properties": {
                "data": {
                    "properties": {
                        "run_manifest": {
                            "properties": {
                                "resources": {
                                    "not": {
                                        "required": ["daidir"]
                                    }
                                }
                            },
                            "required": ["resources"],
                        },
                    },
                    "required": ["run_manifest"],
                },
            },
            "required": ["data"],
        }
        return [
            {
                "if": run_manifest_is_present,
                "then": {
                    "properties": {
                        "session": {
                            "properties": {
                                "fsdb": {"type": "string"}
                            },
                            "required": ["fsdb"],
                        }
                    },
                    "required": ["session"],
                },
            },
            {
                "if": {
                    "allOf": [
                        run_manifest_is_present,
                        daidir_condition,
                    ]
                },
                "then": resources_daidir_required,
            },
            {
                "if": {
                    "allOf": [
                        run_manifest_is_present,
                        {"not": daidir_condition},
                    ]
                },
                "then": resources_daidir_forbidden,
            },
        ]
    if action == "value.at":
        return [
            {
                "oneOf": [
                    {
                        "properties": {
                            "summary": {
                                "properties": {
                                    "sampling_mode": {
                                        "const": "raw_time"
                                    }
                                },
                                "required": ["sampling_mode"],
                            },
                            "data": {
                                "properties": {
                                    "samples": {
                                        "items": {
                                            "properties": {
                                                "sampling_mode": {
                                                    "const": "raw_time"
                                                }
                                            },
                                            "required": ["sampling_mode"],
                                            **forbidden_properties(
                                                "clock_context"
                                            ),
                                        }
                                    }
                                },
                                "required": ["samples"],
                            },
                        },
                        "required": ["summary", "data"],
                    },
                    {
                        "properties": {
                            "summary": {
                                "properties": {
                                    "sampling_mode": {
                                        "const": "clock_sampled"
                                    }
                                },
                                "required": ["sampling_mode"],
                            },
                            "data": {
                                "properties": {
                                    "samples": {
                                        "items": {
                                            "properties": {
                                                "sampling_mode": {
                                                    "const": "clock_sampled"
                                                }
                                            },
                                            "required": [
                                                "sampling_mode",
                                                "clock_context",
                                            ],
                                        }
                                    }
                                },
                                "required": ["samples"],
                            },
                        },
                        "required": ["summary", "data"],
                    },
                ]
            }
        ]
    if action == "expr.eval_at":
        return [
            {
                "oneOf": [
                    {
                        "properties": {
                            "summary": {
                                "properties": {
                                    "known": {"const": True},
                                    "status": {"const": "true"},
                                },
                                "required": ["known", "status"],
                            },
                            "data": {
                                "properties": {
                                    "expr_value": {"const": True}
                                },
                                "required": ["expr_value"],
                            },
                        },
                        "required": ["summary", "data"],
                    },
                    {
                        "properties": {
                            "summary": {
                                "properties": {
                                    "known": {"const": True},
                                    "status": {"const": "false"},
                                },
                                "required": ["known", "status"],
                            },
                            "data": {
                                "properties": {
                                    "expr_value": {"const": False}
                                },
                                "required": ["expr_value"],
                            },
                        },
                        "required": ["summary", "data"],
                    },
                    {
                        "properties": {
                            "summary": {
                                "properties": {
                                    "known": {"const": False},
                                    "status": {"const": "unknown"},
                                },
                                "required": ["known", "status"],
                            },
                            "data": {
                                "properties": {
                                    "expr_value": {"type": "null"}
                                },
                                "required": ["expr_value"],
                            },
                        },
                        "required": ["summary", "data"],
                    },
                ]
            }
        ]
    if action == "event.export":
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "output_written": {"const": True}
                            },
                            "required": ["output_written"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": forbidden_properties("events")
                    }
                },
                "else": {
                    "properties": {
                        "data": {
                            "anyOf": [
                                {"required": ["events"]},
                                {"required": ["aggregate"]},
                            ]
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {"row_count": {"const": 0}},
                            "required": ["row_count"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "total_count": {"const": 0}
                            }
                        },
                        "data": {
                            "properties": {
                                "events": {"maxItems": 0},
                                "aggregate": {
                                    "properties": {
                                        "count": {"const": 0}
                                    }
                                },
                            }
                        },
                    }
                },
                "else": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "total_count": {
                                    "type": "integer",
                                    "minimum": 1,
                                }
                            }
                        },
                        "data": {
                            "properties": {
                                "aggregate": {
                                    "properties": {
                                        "count": {
                                            "type": "integer",
                                            "minimum": 1,
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            },
        ]
    if action == "event.find":
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "total_count": {"const": 0}
                            },
                            "required": ["total_count"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": {
                            "properties": {
                                "events": {"maxItems": 0}
                            }
                        }
                    }
                },
            }
        ]
    if action == "counter.statistics":
        no_value_fields = (
            "min_count",
            "max_count",
            "min_first_time",
            "max_first_time",
        )
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "valid_count": {"const": 0}
                            },
                            "required": ["valid_count"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": forbidden_properties(*no_value_fields)
                    }
                },
                "else": {
                    "properties": {
                        "data": {"required": list(no_value_fields)}
                    }
                },
            }
        ]
    if action == "signal.statistics":
        known_fields = (
            "first",
            "final",
            "min",
            "max",
            "low_cycles",
            "high_cycles",
            "high_ratio",
            "activity",
        )
        raw_value_fields = (
            "initial_value",
            "final_value",
            "first_change_time",
            "last_change_time",
        )
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sampling_mode": {
                                    "const": "clock_edge"
                                }
                            },
                            "required": ["sampling_mode"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": clock_signal_statistics_data_schema()
                    }
                },
                "else": {
                    "properties": {
                        "data": raw_signal_statistics_data_schema()
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sampling_mode": {
                                    "const": "clock_edge"
                                },
                                "known_count": {"const": 0},
                            },
                            "required": [
                                "sampling_mode",
                                "known_count",
                            ],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": {
                            "properties": {
                                "transition_count": {"const": 0}
                            },
                            **forbidden_properties(*known_fields),
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sampling_mode": {
                                    "const": "clock_edge"
                                },
                                "known_count": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                            },
                            "required": [
                                "sampling_mode",
                                "known_count",
                            ],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": {"required": list(known_fields)}
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sampling_mode": {
                                    "const": "raw_value_changes"
                                },
                                "total_count": {"const": 0},
                            },
                            "required": [
                                "sampling_mode",
                                "total_count",
                            ],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "actual_transition_count": {"const": 0}
                            }
                        },
                        "data": {
                            "properties": {
                                "includes_initial_value": {
                                    "const": False
                                }
                            },
                            "required": ["includes_initial_value"],
                            **forbidden_properties(*raw_value_fields),
                        }
                    }
                },
            },
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sampling_mode": {
                                    "const": "raw_value_changes"
                                },
                                "total_count": {
                                    "type": "integer",
                                    "minimum": 1,
                                },
                            },
                            "required": [
                                "sampling_mode",
                                "total_count",
                            ],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": {
                            "properties": {
                                "includes_initial_value": {
                                    "const": True
                                }
                            },
                            "required": [
                                "includes_initial_value",
                                *raw_value_fields,
                            ],
                        }
                    }
                },
            },
        ]
    if action == "protocol.handshake.inspect":
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "ready_without_valid_reporting": {
                                    "const": "intervals"
                                }
                            },
                            "required": [
                                "ready_without_valid_reporting"
                            ],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": {
                            "required": [
                                "ready_without_valid_intervals"
                            ]
                        }
                    }
                },
                "else": {
                    "properties": {
                        "data": forbidden_properties(
                            "ready_without_valid_intervals"
                        )
                    }
                },
            }
        ]
    if action == "signal.sampled_pulse.inspect":
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sampled_high_cycles": {"const": 0}
                            },
                            "required": ["sampled_high_cycles"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "data": {
                            "properties": {
                                "first_sampled_high_time": {
                                    "type": "null"
                                },
                                "last_sampled_high_time": {
                                    "type": "null"
                                },
                            }
                        }
                    }
                },
                "else": {
                    "properties": {
                        "data": {
                            "properties": {
                                "first_sampled_high_time": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                                "last_sampled_high_time": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                            }
                        }
                    }
                },
            }
        ]
    if action == "window.verify":
        return [
            {
                "if": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "sample_count": {"const": 0}
                            },
                            "required": ["sample_count"],
                        }
                    },
                    "required": ["summary"],
                },
                "then": {
                    "properties": {
                        "summary": {
                            "properties": {
                                "failed_samples": {"const": 0},
                                "unknown_samples": {"const": 0},
                            }
                        },
                        "data": {
                            "properties": {
                                "findings": {"maxItems": 0}
                            }
                        }
                    }
                },
            }
        ]
    return []


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(type(value))


def infer_schema(action: str, values: list[Any], pointer: str) -> dict[str, Any]:
    if (
        action in RAW_OR_CLOCK_ACTIONS | SAMPLING_CONTRACT_ACTIONS
        and pointer == SUMMARY_POINTER + "/sampling_mode"
        and len(set(values)) == 1
        and isinstance(values[0], str)
    ):
        return {"const": values[0]}
    if (
        action in SAMPLING_CONTRACT_ACTIONS
        and pointer == SUMMARY_POINTER + "/sample_time_semantics"
    ):
        return {"const": "time is sample_time"}
    if values and all(
        isinstance(value, dict)
        and {"value", "known"} <= set(value)
        and set(value)
        <= {
            "value",
            "known",
            "width",
            "bits",
            "has_x",
            "has_z",
            "requested_value_format",
            "effective_value_format",
            "value_format_reason",
        }
        for value in values
    ):
        return {"$ref": "#/$defs/logicValue"}
    explicit = explicit_schema(action, pointer)
    if explicit is not None:
        return explicit

    grouped: dict[str, list[Any]] = {}
    for value in values:
        grouped.setdefault(json_type(value), []).append(value)

    if set(grouped) <= {"integer", "number"}:
        return {"type": "number" if "number" in grouped else "integer"}

    if len(grouped) > 1:
        simple_types = set(grouped) <= {
            "null",
            "boolean",
            "integer",
            "number",
            "string",
        }
        if simple_types:
            scalar_types = set(grouped)
            if "number" in scalar_types:
                scalar_types.discard("integer")
            order = ("null", "boolean", "integer", "number", "string")
            return {"type": [kind for kind in order if kind in scalar_types]}
        return {
            "anyOf": [
                infer_schema(action, branch, pointer)
                for _, branch in sorted(grouped.items())
            ]
        }

    kind, branch = next(iter(grouped.items()))
    if kind in {"null", "boolean", "integer", "number", "string"}:
        return {"type": kind}

    if kind == "array":
        elements = [item for value in branch for item in value]
        item_schema = (
            infer_schema(action, elements, pointer + "/*")
            if elements
            else empty_array_item_schema(action, pointer)
        )
        return array(item_schema)

    keys = set().union(*(value.keys() for value in branch))
    required = set(keys)
    for value in branch:
        required.intersection_update(value)
    properties = {
        key: infer_schema(
            action,
            [value[key] for value in branch if key in value],
            pointer + "/" + key.replace("~", "~0").replace("/", "~1"),
        )
        for key in sorted(keys)
    }
    return closed(properties, required)


def load_action_entries() -> list[dict[str, Any]]:
    catalog = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return catalog["actions"]


def response_examples(entry: dict[str, Any]) -> list[dict[str, Any]]:
    paths = entry.get("examples", {}).get("response", [])
    if not paths:
        raise ValueError(f"{entry['name']}: response example list is empty")
    examples: list[dict[str, Any]] = []
    for relative in paths:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        if value.get("action") != entry["name"]:
            raise ValueError(
                f"{relative}: action {value.get('action')!r} != {entry['name']!r}"
            )
        if not isinstance(value.get("ok"), bool):
            raise ValueError(f"{relative}: response witness must declare boolean ok")
        examples.append(value)
    return examples


def find_legacy_completeness(value: Any, pointer: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = pointer + "/" + key
            if key in LEGACY_COMPLETENESS_FIELDS:
                errors.append(child_pointer)
            errors.extend(find_legacy_completeness(child, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(find_legacy_completeness(child, pointer + f"/{index}"))
    return errors


def add_shared_success_fields(
    action: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    if action not in VALUE_ACTIONS:
        return summary
    result = copy.deepcopy(summary)

    def add_to_root(node: dict[str, Any]) -> None:
        if node.get("type") == "object" and isinstance(
            node.get("properties"), dict
        ):
            node["properties"]["value_width_complete"] = {
                "type": "boolean"
            }
            node["properties"]["width_diagnostics"] = array(
                value_width_diagnostic_schema()
            )
            return
        for keyword in ("allOf", "anyOf", "oneOf"):
            for branch in node.get(keyword, []):
                if isinstance(branch, dict):
                    add_to_root(branch)

    add_to_root(result)
    return result


def schema_object_fields(schema: dict[str, Any]) -> list[str]:
    names = set(schema.get("properties", {}))
    for keyword in ("anyOf", "oneOf", "allOf"):
        for branch in schema.get(keyword, []):
            if isinstance(branch, dict):
                names.update(schema_object_fields(branch))
    for keyword in ("if", "then", "else"):
        branch = schema.get(keyword)
        if isinstance(branch, dict):
            names.update(schema_object_fields(branch))
    return sorted(names)


def output_notes(action: str, summary: dict[str, Any], data: dict[str, Any]) -> str:
    summary_names = schema_object_fields(summary)
    data_names = schema_object_fields(data)

    def qualified(location: str, names: list[str]) -> str:
        return ", ".join(f"{location}.{name}" for name in names) or "（空对象）"

    notes = (
        f"{action} 成功响应的 summary 字段为 "
        f"{qualified('summary', summary_names)}；"
        f"data 字段为 {qualified('data', data_names)}。"
        "未知字段会被拒绝。"
    )
    completeness_locations = [
        f"{location}.{field}"
        for location, names in (
            ("summary", set(summary_names)),
            ("data", set(data_names)),
        )
        for field in completeness_properties()
        if field in names
    ]
    if completeness_locations:
        notes += (
            "完整性和裁剪事实使用 "
            + ", ".join(completeness_locations)
            + "。"
        )
    return notes


def merge_definitions(
    destination: dict[str, Any],
    source: dict[str, Any],
    *,
    owner: str,
) -> None:
    collisions = sorted(set(destination) & set(source))
    if collisions:
        raise ValueError(
            f"{owner}: response definition collision: "
            + ", ".join(collisions)
        )
    destination.update(copy.deepcopy(source))


def install_definition(
    definitions: dict[str, Any],
    name: str,
    schema: dict[str, Any],
    *,
    owner: str,
) -> None:
    existing = definitions.get(name)
    if existing is not None and existing != schema:
        raise ValueError(
            f"{owner}: canonical response definition differs: {name}"
        )
    definitions[name] = copy.deepcopy(schema)


def local_definition_references(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, list):
        for item in value:
            references.update(local_definition_references(item))
        return references
    if not isinstance(value, dict):
        return references
    reference = value.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        encoded_name = reference[len("#/$defs/") :].split("/", 1)[0]
        references.add(
            encoded_name.replace("~1", "/").replace("~0", "~")
        )
    for child in value.values():
        references.update(local_definition_references(child))
    return references


def referenced_definition_closure(
    roots: Iterable[dict[str, Any]],
    available: dict[str, Any],
    *,
    external: set[str] | frozenset[str],
    owner: str,
) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    pending: set[str] = set()
    for root in roots:
        pending.update(local_definition_references(root))
    while pending:
        name = min(pending)
        pending.remove(name)
        if name in external or name in selected:
            continue
        definition = available.get(name)
        if definition is None:
            raise ValueError(
                f"{owner}: unresolved response definition: {name}"
            )
        selected[name] = copy.deepcopy(definition)
        pending.update(local_definition_references(definition))
    return {name: selected[name] for name in sorted(selected)}


def apply_batch_result_contract(
    data_schema: dict[str, Any],
    contract: BatchResultContract,
) -> dict[str, Any]:
    result = copy.deepcopy(data_schema)
    properties = result.get("properties")
    if not isinstance(properties, dict):
        raise ValueError(
            "batch: success data must be a closed object with results"
        )
    results = properties.get("results")
    if not isinstance(results, dict) or results.get("type") != "array":
        raise ValueError(
            "batch: data.results must be an array in every success witness"
        )
    results["items"] = copy.deepcopy(contract.item_schema)
    return result


def response_schema(
    entry: dict[str, Any],
    *,
    batch_result_contract: BatchResultContract | None = None,
) -> dict[str, Any]:
    action = entry["name"]
    if action == "batch" and batch_result_contract is None:
        entries = load_action_entries()
        non_batch_schemas = {
            candidate["name"]: response_schema(candidate)
            for candidate in entries
            if candidate["name"] != "batch"
        }
        batch_result_contract = build_batch_result_contract(
            non_batch_schemas,
            known_actions=(candidate["name"] for candidate in entries),
        )
    examples = response_examples(entry)
    success_examples = [example for example in examples if example["ok"]]
    if not success_examples:
        raise ValueError(f"{action}: at least one success response witness is required")
    legacy = [
        f"{entry['examples']['response'][index]}:{pointer}"
        for index, example in enumerate(examples)
        for pointer in find_legacy_completeness(example)
    ]
    if legacy:
        raise ValueError(
            f"{action}: legacy completeness fields remain: {', '.join(legacy)}"
        )

    success_variants: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if action in NON_SAMPLING_RESPONSE_ACTIONS:
        success_variants = [
            (
                add_shared_success_fields(
                    action, copy.deepcopy(variant.summary)
                ),
                copy.deepcopy(variant.data),
            )
            for variant in non_sampling_success_response_variants(action)
        ]
    elif action in SESSION_RESPONSE_ACTIONS:
        success_variants = [
            (
                copy.deepcopy(variant.summary),
                copy.deepcopy(variant.data),
            )
            for variant in session_success_response_variants(action)
        ]
    else:
        seen_variants: set[str] = set()
        for example in success_examples:
            summary_shape = add_shared_success_fields(
                action,
                infer_schema(
                    action,
                    [example["summary"]],
                    SUMMARY_POINTER,
                ),
            )
            data_shape = add_common_blocks_to_data_schema(
                action,
                infer_schema(
                    action,
                    [example["data"]],
                    DATA_POINTER,
                ),
            )
            if action == "batch":
                if batch_result_contract is None:
                    raise ValueError(
                        "batch: strict result contract was not constructed"
                    )
                data_shape = apply_batch_result_contract(
                    data_shape,
                    batch_result_contract,
                )
            key = json.dumps(
                [summary_shape, data_shape],
                sort_keys=True,
                ensure_ascii=False,
            )
            if key in seen_variants:
                continue
            seen_variants.add(key)
            success_variants.append((summary_shape, data_shape))

    if len(success_variants) == 1:
        success_summary, success_data = success_variants[0]
    else:
        success_summary = {
            "anyOf": [shape for shape, _ in success_variants]
        }
        success_data = {
            "anyOf": [shape for _, shape in success_variants]
        }
    error_summary = closed(
        {
            "status": {"const": "error"},
            "error_code": {"type": "string"},
        },
        ("status", "error_code"),
    )
    strict_error = error_schema(action)
    definitions = json_definitions()
    definitions.update(
        {
            "successSummary": success_summary,
            "successData": success_data,
            "errorSummary": error_summary,
            "validationIssue": validation_issue_schema(),
            "error": strict_error,
            "tool": tool_schema(),
            "sessionRecord": session_record_schema(),
            "suggestedNextAction": suggested_next_action_schema(),
            "finding": common_finding_schema(),
            "warning": warning_schema(),
            "logicValue": logic_value_schema(),
        }
    )
    if action == "batch":
        # The batch envelope can fail before a child action is selected.  Only
        # that envelope references the action-agnostic error definition; child
        # action schemas use their own strict ``error`` definition.
        definitions["genericError"] = error_schema("__generic__")
    merge_definitions(
        definitions,
        session_response_contract_definitions(),
        owner=action,
    )
    if action in {"session.list", "batch"}:
        definitions["sessionListRecord"] = session_list_record_schema()
    if action in NON_SAMPLING_RESPONSE_ACTIONS:
        external_definitions = {
            "commonBlock": common_block_schema(),
            "logicValue": logic_value_schema(),
            "reset": reset_schema(),
            "suggestedNextAction": suggested_next_action_schema(),
            "valueWidthDiagnostic": value_width_diagnostic_schema(),
        }
        required_external = (
            non_sampling_required_external_definitions()
        )
        if set(external_definitions) != set(required_external):
            raise ValueError(
                f"{action}: non-sampling external definition drift"
            )
        for name in sorted(required_external):
            install_definition(
                definitions,
                name,
                external_definitions[name],
                owner=action,
            )
        domain_definitions = non_sampling_response_contract_definitions()
        selected_domain_definitions = referenced_definition_closure(
            (
                schema
                for summary_shape, data_shape in success_variants
                for schema in (summary_shape, data_shape)
            ),
            domain_definitions,
            external=required_external,
            owner=action,
        )
        merge_definitions(
            definitions,
            selected_domain_definitions,
            owner=action,
        )
    if action == "batch":
        if batch_result_contract is None:
            raise ValueError(
                "batch: strict result contract was not constructed"
            )
        merge_definitions(
            definitions,
            batch_result_contract.definitions,
            owner="batch",
        )
    if action in CLOCK_CONTEXT_ACTIONS | SAMPLING_CONTRACT_ACTIONS:
        definitions.update(
            {
                "samplingSelection": sampling_selection_schema(),
                "samplingContract": sampling_contract_schema(),
                "clockContext": clock_context_schema(),
            }
        )
    if action in {"event.config.load", "event.config.list"}:
        definitions["eventConfig"] = event_config_response_schema()
    if action == "session.open":
        definitions.update(
            {
                "runManifestResource": run_manifest_resource_schema(),
                "runManifest": run_manifest_response_schema(),
            }
        )
    if action in {"event.find", "event.export"}:
        definitions["eventRecord"] = event_record_schema()
    if action == "event.export":
        definitions["eventAggregate"] = event_aggregate_schema()
    if action == "counter.statistics":
        definitions.update(
            {
                "counterPredicate": counter_predicate_schema(),
                "counterEvidence": counter_evidence_schema(),
            }
        )
    if action == "signal.statistics":
        definitions.update(
            {
                "signalStatisticsEvidence": (
                    signal_statistics_evidence_schema()
                ),
                "rawSignalActivity": signal_activity_schema(False),
                "clockSignalActivity": signal_activity_schema(True),
            }
        )
    if action == "protocol.handshake.inspect":
        definitions.update(
            {
                "readyWithoutValidInterval": (
                    ready_without_valid_interval_schema()
                ),
                "protocolHandshakeFinding": (
                    protocol_handshake_finding_schema()
                ),
            }
        )
    if action == "value.at":
        definitions["xbitHints"] = xbit_hints_schema()
    if action == "verify.conditions":
        definitions["verifyCheck"] = verify_check_schema()
    if action == "signal.sampled_pulse.inspect":
        definitions.update(
            {
                "sampledPayload": sampled_payload_schema(False),
                "sampledPayloadValue": sampled_payload_schema(True),
                "sampledPulseFinding": sampled_pulse_finding_schema(),
            }
        )
    if action == "window.verify":
        definitions.update(
            {
                "windowCondition": window_condition_schema(),
                "windowFinding": window_finding_schema(),
            }
        )
    for index, (summary_shape, data_shape) in enumerate(success_variants):
        definitions[f"successSummary{index}"] = summary_shape
        definitions[f"successData{index}"] = data_shape

    if action in NON_SAMPLING_RESPONSE_ACTIONS | SESSION_RESPONSE_ACTIONS:
        pairing_schema = {
            "$defs": definitions,
            "oneOf": [
                {
                    "properties": {
                        "summary": summary_shape,
                        "data": data_shape,
                    },
                    "required": ["summary", "data"],
                }
                for summary_shape, data_shape in success_variants
            ],
        }
        validator = Draft7Validator(pairing_schema)
        for example in success_examples:
            instance = {
                "summary": example["summary"],
                "data": example["data"],
            }
            errors = list(validator.iter_errors(instance))
            if errors:
                first = errors[0]
                raise ValueError(
                    f"{action}: success witness does not match exactly one "
                    f"strict correlated variant at {first.json_path}: "
                    f"{first.message}"
                )

    properties = {
        "api_version": {"const": "xdebug.v1"},
        "request_id": {"type": "string"},
        "ok": {"type": "boolean"},
        "action": {"const": action},
        "tool": {"$ref": "#/$defs/tool"},
        "session": {
            "anyOf": [
                {"type": "null"},
                {"$ref": "#/$defs/sessionRecord"},
            ]
        },
        "schema_version": {"type": "string"},
        "suggested_next_actions": array(
            {"$ref": "#/$defs/suggestedNextAction"}
        ),
        "summary": {
            "anyOf": [
                {"$ref": "#/$defs/successSummary"},
                {"$ref": "#/$defs/errorSummary"},
            ]
        },
        "data": {
            "anyOf": [
                {"$ref": "#/$defs/successData"},
                {"type": "null"},
            ]
        },
        "findings": array({"$ref": "#/$defs/finding"}),
        "warnings": array({"$ref": "#/$defs/warning"}),
        "error": {
            "anyOf": [
                {"type": "null"},
                {"$ref": "#/$defs/error"},
            ]
        },
    }
    if action == "session.open":
        definitions["duplicateResourceAdvisory"] = (
            duplicate_resource_advisory_schema()
        )
        properties["advisories"] = array(
            {"$ref": "#/$defs/duplicateResourceAdvisory"}
        )
    required = (
        "api_version",
        "ok",
        "action",
        "tool",
        "session",
        "summary",
        "data",
        "error",
    )
    success_branch: dict[str, Any] = {
        "properties": {
            "ok": {"const": True},
            "error": {"type": "null"},
        },
        "required": list(required),
    }
    if action in {"session.open", "session.doctor"}:
        success_branch["properties"]["session"] = {
            "$ref": "#/$defs/sessionRecord"
        }
    elif action.startswith("session."):
        success_branch["properties"]["session"] = {"type": "null"}
    if len(success_variants) == 1:
        success_branch["properties"].update(
            {
                "summary": {"$ref": "#/$defs/successSummary0"},
                "data": {"$ref": "#/$defs/successData0"},
            }
        )
    else:
        success_branch["oneOf"] = [
            {
                "properties": {
                    "summary": {
                        "$ref": f"#/$defs/successSummary{index}"
                    },
                    "data": {"$ref": f"#/$defs/successData{index}"},
                },
                "required": ["summary", "data"],
            }
            for index in range(len(success_variants))
        ]
    conditions = success_response_conditions(action)
    if conditions:
        success_branch["allOf"] = conditions
    error_branch = {
        "properties": {
            "ok": {"const": False},
            "session": {"type": "null"},
            "summary": {"$ref": "#/$defs/errorSummary"},
            "data": {"type": "null"},
            "error": {"$ref": "#/$defs/error"},
        },
        "required": list(required),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"xdebug.{action}.response.v1",
        "title": f"{action} response",
        "description": entry["description_en"],
        "x-description-zh": entry["description_zh"],
        "x-output_notes": output_notes(action, success_summary, success_data),
        "$defs": definitions,
        "type": "object",
        "properties": properties,
        "required": list(required),
        "oneOf": [success_branch, error_branch],
        "additionalProperties": False,
    }


def generic_error_response_schema() -> dict[str, Any]:
    error_summary = closed(
        {
            "status": {"const": "error"},
            "error_code": {"type": "string"},
        },
        ("status", "error_code"),
    )
    definitions = json_definitions()
    definitions.update(
        {
            "errorSummary": error_summary,
            "validationIssue": validation_issue_schema(),
            "error": error_schema("__generic__"),
            "tool": tool_schema(),
            "warning": warning_schema(),
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "xdebug.error.v1",
        "title": "xdebug error response",
        "description": (
            "Strict public error envelope used before an action-specific "
            "response contract can be selected."
        ),
        "$defs": definitions,
        "type": "object",
        "properties": {
            "api_version": {"const": "xdebug.v1"},
            "request_id": {"type": "string"},
            "ok": {"const": False},
            "action": {"type": "string"},
            "tool": {"$ref": "#/$defs/tool"},
            "session": {"type": "null"},
            "schema_version": {"const": "xdebug.error.v1"},
            "summary": {"$ref": "#/$defs/errorSummary"},
            "data": {"type": "null"},
            "warnings": array({"$ref": "#/$defs/warning"}),
            "error": {"$ref": "#/$defs/error"},
        },
        "required": [
            "api_version",
            "ok",
            "action",
            "tool",
            "session",
            "summary",
            "data",
            "error",
        ],
        "additionalProperties": False,
    }


def render(entry: dict[str, Any]) -> str:
    return json.dumps(
        response_schema(entry),
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def build_response_schema_catalog(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    names = [entry["name"] for entry in entries]
    if len(names) != len(set(names)):
        duplicates = sorted(
            name for name in set(names) if names.count(name) > 1
        )
        raise ValueError(
            "duplicate public response action(s): "
            + ", ".join(duplicates)
        )
    batch_entries = [entry for entry in entries if entry["name"] == "batch"]
    if len(batch_entries) != 1:
        raise ValueError(
            "public response catalog must contain exactly one batch action"
        )

    schemas = {
        entry["name"]: response_schema(entry)
        for entry in entries
        if entry["name"] != "batch"
    }
    batch_contract = build_batch_result_contract(
        schemas,
        known_actions=names,
    )
    schemas["batch"] = response_schema(
        batch_entries[0],
        batch_result_contract=batch_contract,
    )
    return schemas


def sync(
    *,
    check: bool,
    selected_actions: set[str] | None = None,
) -> int:
    all_entries = load_action_entries()
    entries = all_entries
    full_sync = selected_actions is None
    if selected_actions is not None:
        entries = [entry for entry in entries if entry["name"] in selected_actions]
        missing = selected_actions - {entry["name"] for entry in entries}
        if missing:
            print("unknown or removed response action(s):", ", ".join(sorted(missing)))
            return 1

    stale: list[str] = []
    try:
        schemas = build_response_schema_catalog(all_entries)
        rendered = {
            entry["name"]: (
                json.dumps(
                    schemas[entry["name"]],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            for entry in entries
        }
        generic_error = (
            json.dumps(
                generic_error_response_schema(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(f"response schema source error: {exc}")
        return 1

    for entry in entries:
        action = entry["name"]
        path = ROOT / entry["schemas"]["response"]
        content = rendered[action]
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(content, encoding="utf-8")

    if full_sync:
        if check:
            if (
                not GENERIC_ERROR_SCHEMA_PATH.exists()
                or GENERIC_ERROR_SCHEMA_PATH.read_text(encoding="utf-8")
                != generic_error
            ):
                stale.append(str(GENERIC_ERROR_SCHEMA_PATH.relative_to(ROOT)))
        else:
            GENERIC_ERROR_SCHEMA_PATH.write_text(generic_error, encoding="utf-8")
        for path in RETIRED_SCHEMA_PATHS:
            if path.exists():
                stale.append(
                    f"{path.relative_to(ROOT)} (retired schema must be removed)"
                )

    if stale:
        print("response schema drift:")
        for relative in stale:
            print(f"  {relative}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--action", action="append", default=[])
    args = parser.parse_args(argv)
    selected = set(args.action) if args.action else None
    return sync(check=args.check, selected_actions=selected)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
