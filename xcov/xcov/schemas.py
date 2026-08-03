from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Dict, Iterable, List

from .coverage_contract import (
    METRICS as CONTRACT_METRICS,
    STATUS_VALUES,
)
from .errors import XcovError

Json = Dict[str, Any]

METRICS = list(CONTRACT_METRICS)
CODE_METRICS = ["line", "toggle", "branch", "condition", "fsm", "assert"]
FUNCTIONAL_LEVELS = ["covergroup", "coverpoint", "cross", "bin"]
OVERFLOW = ["truncate", "error", "summary_only"]

_COVERAGE_FACT_QUERY_FIELDS = (
    "metric",
    "type",
    "scope",
    "name",
    "full_name",
    "file",
    "toggle_signal",
    "toggle_bit",
    "toggle_transition",
    "branch",
    "branch_bin",
    "branch_terms",
    "condition",
    "condition_bin",
    "condition_terms",
    "assert_kind",
    "assert_object",
    "assert_bin",
    "fsm",
    "covergroup",
    "coverpoint",
    "cross",
    "bin",
)

# Query and sort selectors are part of each action contract.  Runtime helpers
# consume these exact declarations as a defensive invariant; they are not
# free-form backend field names.
QUERY_FIELD_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "tests.list": {
        "default": "name",
        "allowed": ("name",),
    },
    "scope.summary": {
        "default": "full_name",
        "allowed": ("name", "full_name", "file"),
    },
    "scope.children": {
        "default": "full_name",
        "allowed": ("name", "full_name"),
    },
    "scope.search": {
        "default": "full_name",
        "allowed": ("name", "full_name"),
    },
    "code_coverage.summary": {
        "default": "full_name",
        "allowed": (
            "metric",
            "scope",
            "source_file",
            "type",
            "name",
            "full_name",
        ),
    },
    "code_coverage.holes": {
        "default": "full_name",
        "allowed": ("name", "full_name"),
    },
    "functional_coverage.summary": {
        "default": "full_name",
        "allowed": (
            "name",
            "full_name",
            "covergroup",
            "coverpoint",
            "cross",
            "bin",
        ),
    },
    "functional_coverage.holes": {
        "default": "full_name",
        "allowed": (
            "name",
            "full_name",
            "covergroup",
            "coverpoint",
            "cross",
            "bin",
        ),
    },
    "source.map": {
        "default": "full_name",
        "allowed": _COVERAGE_FACT_QUERY_FIELDS,
    },
    "source.annotate": {
        "default": "full_name",
        "allowed": _COVERAGE_FACT_QUERY_FIELDS,
    },
    "assert.summary": {
        "default": "full_name",
        "allowed": ("kind", "name", "full_name", "category", "severity"),
    },
}

SORT_FIELD_CONTRACTS: Dict[str, tuple[str, ...]] = {
    "scope.summary": (
        "name",
        "full_name",
        "covered",
        "coverable",
        "missing",
        "coverage_pct",
        "line_pct",
        "toggle_pct",
        "branch_pct",
        "condition_pct",
        "fsm_pct",
        "assert_pct",
        "functional_pct",
        "file",
        "line",
    ),
    "scope.children": ("name", "full_name", "coverage_pct"),
    "scope.search": ("name", "full_name", "coverage_pct"),
    "code_coverage.summary": (
        "metric",
        "scope",
        "source_file",
        "type",
        "covered",
        "coverable",
        "missing",
        "coverage_pct",
    ),
    "code_coverage.holes": (
        "name",
        "full_name",
        "coverage_pct",
        "line_pct",
        "toggle_pct",
        "branch_pct",
        "condition_pct",
        "fsm_pct",
        "assert_pct",
    ),
    "functional_coverage.summary": (
        "covergroup",
        "coverpoint",
        "cross",
        "bin",
        "covered",
        "coverable",
        "missing",
        "coverage_pct",
    ),
    "functional_coverage.holes": (
        "covergroup",
        "coverpoint",
        "cross",
        "bin",
        "covered",
        "coverable",
        "count",
        "coverage_pct",
        "status",
        "file",
        "line",
    ),
    "assert.summary": (
        "name",
        "full_name",
        "covered",
        "coverable",
        "missing",
        "coverage_pct",
        "status",
        "attempts",
        "real_successes",
        "without_attempts",
    ),
}


def _string(*, enum: Iterable[str] | None = None, min_length: int | None = None) -> Json:
    out: Json = {"type": "string"}
    if enum is not None:
        out["enum"] = list(enum)
    if min_length is not None:
        out["minLength"] = min_length
    return out


def _bool() -> Json:
    return {"type": "boolean"}


def _integer(minimum: int | None = None) -> Json:
    out: Json = {"type": "integer"}
    if minimum is not None:
        out["minimum"] = minimum
    return out


def _number(minimum: float | None = None, maximum: float | None = None) -> Json:
    out: Json = {"type": "number"}
    if minimum is not None:
        out["minimum"] = minimum
    if maximum is not None:
        out["maximum"] = maximum
    return out


def _nullable(schema: Json) -> Json:
    return {"anyOf": [schema, {"type": "null"}]}


def _array(items: Json, *, min_items: int | None = None) -> Json:
    out: Json = {"type": "array", "items": items}
    if min_items is not None:
        out["minItems"] = min_items
    return out


def _object(props: Json | None = None, required: Iterable[str] = ()) -> Json:
    out: Json = {
        "type": "object",
        "properties": props or {},
        "additionalProperties": False,
    }
    required_list = list(required)
    if required_list:
        out["required"] = required_list
    return out


def _string_array(
    values: Iterable[str] | None = None,
    *,
    min_items: int | None = None,
) -> Json:
    return _array(_string(enum=values), min_items=min_items)


SCHEMA_NODE: Json = {
    "type": "object",
    "x-schema-node": True,
}


def query_contract_for_action(action: str) -> Dict[str, Any]:
    try:
        contract = QUERY_FIELD_CONTRACTS[action]
    except KeyError as exc:
        raise KeyError(f"action {action!r} has no query contract") from exc
    return {
        "default": contract["default"],
        "allowed": tuple(contract["allowed"]),
    }


def sort_fields_for_action(action: str) -> tuple[str, ...]:
    try:
        return tuple(SORT_FIELD_CONTRACTS[action])
    except KeyError as exc:
        raise KeyError(f"action {action!r} has no sort contract") from exc


def _query(action: str) -> Json:
    contract = query_contract_for_action(action)
    return _object({
        "include_patterns": _string_array(),
        "exclude_patterns": _string_array(),
        "match_field": _string(enum=contract["allowed"]),
        "pattern_mode": {"const": "glob"},
        "case_sensitive": _bool(),
    })


def _sort(action: str) -> Json:
    return _object({
        "by": _string(enum=sort_fields_for_action(action)),
        "order": _string(enum=["asc", "desc"]),
    }, required=["by"])


def _limits() -> Json:
    return _object({
        "max_items": _nullable(_integer(0)),
        "overflow": _string(enum=OVERFLOW),
    })


def _export_output() -> Json:
    return _object({
        "path": _string(min_length=1),
        "allow_absolute_path": _bool(),
    }, required=["path"])


def _target(props: Json | None = None, required: Iterable[str] = ()) -> Json:
    return _object(props, required)


def _args(props: Json | None = None, required: Iterable[str] = ()) -> Json:
    return _object(props, required)


SESSION_TARGET = _target(
    {"session_id": _string(min_length=1)},
    required=["session_id"],
)

def _query_props(action: str) -> Json:
    props: Json = {
        "query": _query(action),
        "limits": _limits(),
    }
    if action in SORT_FIELD_CONTRACTS:
        props["sort"] = _sort(action)
    return props


def _coverage_query_props(
    action: str,
    *,
    metrics: Iterable[str] = METRICS,
) -> Json:
    return {
        **_query_props(action),
        "metrics": _string_array(metrics, min_items=1),
        "scope": _string(min_length=1),
        "test": _string(min_length=1),
    }


def _request(
    action: str,
    *,
    target: Json | None = None,
    args: Json | None = None,
    require_target: bool = False,
    require_args: bool = False,
) -> Json:
    required = ["api_version", "action"]
    if require_target:
        required.append("target")
    if require_args:
        required.append("args")
    return _object({
        "api_version": {"const": "xcov.v1"},
        "request_id": _string(min_length=1),
        "action": {"const": action},
        "target": target or _target(),
        "args": args or _args(),
    }, required=required)


STDIO_QUIT_REQUEST = _object({
    "api_version": {"const": "xcov.v1"},
    "request_id": _string(min_length=1),
    "action": {"const": "stdio.quit"},
}, required=["api_version", "request_id", "action"])


def _completeness_summary(extra: Json | None = None) -> Json:
    props: Json = {
        "total_count": _integer(0),
        "returned_count": _integer(0),
        "response_truncated": _bool(),
        "scan_complete": _bool(),
        "analysis_complete": _bool(),
        "truncation_scopes": _string_array(),
    }
    if extra:
        props.update(extra)
    return _object(
        props,
        required=[
            "total_count",
            "returned_count",
            "response_truncated",
            "scan_complete",
            "analysis_complete",
            "truncation_scopes",
        ],
    )


def _error_schema(action: str | None = None) -> Json:
    error_details: Json = {
        "detail.actual_type": _string(min_length=1),
        "detail.backend_type": _string(min_length=1),
        "detail.cause_message": _string(),
        "detail.cause_type": _string(min_length=1),
        "detail.coverable": _integer(0),
        "detail.coverage_type": _string(min_length=1),
        "detail.covered": _integer(0),
        "detail.error_layer": _string(min_length=1),
        "detail.expected": _string(min_length=1),
        "detail.expected_signature": _string(min_length=1),
        "detail.field": _string(min_length=1),
        "detail.failed_count": _integer(0),
        "detail.group_by": _string(min_length=1),
        "detail.kind": _string(min_length=1),
        "detail.coverage_kind": _string(min_length=1),
        "detail.line": _integer(0),
        "detail.match_field": _string(min_length=1),
        "detail.max_items": _integer(0),
        "detail.method": _string(min_length=1),
        "detail.object_type": _string(min_length=1),
        "detail.operation": _string(min_length=1),
        "detail.overflow": _string(min_length=1),
        "detail.path": _string(min_length=1),
        "detail.pattern": _string(),
        "detail.pattern_mode": _string(min_length=1),
        "detail.registry_action": _string(min_length=1),
        "detail.requested_action": _string(),
        "detail.row_index": _integer(0),
        "detail.scope": _string(min_length=1),
        "detail.session_id": _string(min_length=1),
        "detail.supported": _string(min_length=1),
        "detail.test": _string(min_length=1),
        "detail.total_count": _integer(0),
        "detail.unknown_fields": _string_array(),
        "detail.unknown_status": _string_array(),
        "detail.vdb": _string(min_length=1),
    }
    error = _object({
        "code": _string(min_length=1),
        "message": _string(),
        **error_details,
    }, required=["code", "message"])
    return _object({
        "ok": {"const": False},
        "api_version": {"const": "xcov.v1"},
        "request_id": _string(min_length=1),
        "action": {"const": action} if action is not None else _string(),
        "summary": _completeness_summary(),
        "data": _object(),
        "warnings": _string_array(),
        "error": error,
    }, required=[
        "ok", "api_version", "request_id", "action", "summary", "data",
        "warnings", "error",
    ])


def _response(action: str, summary: Json, data: Json) -> Json:
    success = _object({
        "ok": {"const": True},
        "api_version": {"const": "xcov.v1"},
        "request_id": _string(min_length=1),
        "action": {"const": action},
        "summary": summary,
        "data": data,
        "warnings": _string_array(),
    }, required=[
        "ok", "api_version", "request_id", "action", "summary", "data", "warnings",
    ])
    return {"oneOf": [success, _error_schema(action)]}


def _schema_entry(action: str, request: Json, summary: Json, data: Json) -> Json:
    return {
        "request": request,
        "response": _response(action, summary, data),
    }


SCALAR: Json = {"type": ["string", "number", "boolean", "null"]}
NULLABLE_NUMBER = _nullable(_number(0.0, 100.0))
NULLABLE_INTEGER = _nullable(_integer(0))
NULLABLE_POSITIVE_INTEGER = _nullable(_integer(1))
NULLABLE_STRING = _nullable(_string())
NULLABLE_NONEMPTY_STRING = _nullable(_string(min_length=1))

def _filters(action: str) -> Json:
    contract = query_contract_for_action(action)
    return _object({
        "include": _string_array(),
        "exclude": _string_array(),
        "match_field": _string(enum=contract["allowed"]),
    }, required=["include", "exclude", "match_field"])

SESSION = _object({
    "session_id": _string(min_length=1),
    "state": _string(min_length=1),
    "vdb": _string(min_length=1),
    "test_count": _integer(0),
    "top_scope_count": _nullable(_integer(0)),
    "worker": _string(min_length=1),
    "exclusion_policy": _string(enum=["default", "strict"]),
}, required=[
    "session_id", "state", "vdb", "test_count", "top_scope_count", "worker",
    "exclusion_policy",
])

RUN_MANIFEST_RESOURCE = _object({
    "path": {
        "type": "string",
        "minLength": 1,
        "pattern": r"^(?!/)(?!\.\.(?:/|$))(?!.*\/\.\.(?:\/|$)).+$",
    },
    "size_bytes": _integer(0),
    "sha256": {
        "type": "string",
        "minLength": 64,
        "maxLength": 64,
        "pattern": "^[0-9a-f]{64}$",
    },
}, required=["path", "size_bytes", "sha256"])

RUN_MANIFEST_INPUT = _object({
    "schema_version": {"const": "xcov.run-manifest.v1"},
    "state": {"const": "published"},
    "resources": _object({"vdb": RUN_MANIFEST_RESOURCE}, required=["vdb"]),
}, required=["schema_version", "state", "resources"])

RUN_MANIFEST = deepcopy(RUN_MANIFEST_INPUT)
RUN_MANIFEST["properties"] = {
    **RUN_MANIFEST["properties"],
    "manifest_path": _string(min_length=1),
}
RUN_MANIFEST["required"] = [
    *RUN_MANIFEST_INPUT["required"],
    "manifest_path",
]

RESOURCE_SNAPSHOT = _object({
    "vdb": _string(min_length=1),
    "run_manifest": _nullable(RUN_MANIFEST),
}, required=["vdb", "run_manifest"])

ACTION_ITEM = _object({
    "name": _string(min_length=1),
    "status": {"const": "p0"},
    "api_version": {"const": "xcov.v1"},
    "use_when": _string(min_length=1),
    "do_not_use_when": _string(min_length=1),
}, required=["name", "status", "api_version", "use_when", "do_not_use_when"])

TEST_ITEM = _object({"name": _string(min_length=1)}, required=["name"])

COVERAGE_SCORE_PROPS: Json = {
    "covered": NULLABLE_INTEGER,
    "coverable": NULLABLE_INTEGER,
    "missing": NULLABLE_INTEGER,
    "coverage_pct": NULLABLE_NUMBER,
}

METRIC_ITEM = _object({
    "metric": _string(min_length=1),
    **COVERAGE_SCORE_PROPS,
}, required=["metric", *COVERAGE_SCORE_PROPS])

SCOPE_BRIEF_ITEM = _object({
    "name": _string(min_length=1),
    "full_name": _string(min_length=1),
    "coverage_pct": NULLABLE_NUMBER,
}, required=["name", "full_name", "coverage_pct"])

SCOPE_SUMMARY_ITEM = _object({
    "name": _string(min_length=1),
    "full_name": _string(min_length=1),
    **COVERAGE_SCORE_PROPS,
    "line_pct": NULLABLE_NUMBER,
    "toggle_pct": NULLABLE_NUMBER,
    "branch_pct": NULLABLE_NUMBER,
    "condition_pct": NULLABLE_NUMBER,
    "fsm_pct": NULLABLE_NUMBER,
    "assert_pct": NULLABLE_NUMBER,
    "functional_pct": NULLABLE_NUMBER,
    "file": NULLABLE_NONEMPTY_STRING,
    "line": NULLABLE_POSITIVE_INTEGER,
}, required=[
    "name", "full_name", *COVERAGE_SCORE_PROPS,
    "line_pct", "toggle_pct", "branch_pct", "condition_pct", "fsm_pct",
    "assert_pct", "functional_pct", "file", "line",
])

def _code_summary_item_variant(group_by: str) -> Json:
    if group_by == "metric":
        identity = {"metric": _string(enum=CODE_METRICS)}
        required = ["metric"]
    else:
        identity = {
            "metric": {"const": "summary"},
            group_by: _string(min_length=1),
        }
        required = ["metric", group_by]
    return _object(
        {**identity, **COVERAGE_SCORE_PROPS},
        required=[*required, *COVERAGE_SCORE_PROPS],
    )


CODE_SUMMARY_ITEM = {
    "oneOf": [
        _code_summary_item_variant(group_by)
        for group_by in ("metric", "scope", "source_file", "type")
    ],
}

CODE_HOLE_ITEM = _object({
    "name": _string(min_length=1),
    "full_name": _string(min_length=1),
    "coverage_pct": NULLABLE_NUMBER,
    "line_pct": NULLABLE_NUMBER,
    "toggle_pct": NULLABLE_NUMBER,
    "branch_pct": NULLABLE_NUMBER,
    "condition_pct": NULLABLE_NUMBER,
    "fsm_pct": NULLABLE_NUMBER,
    "assert_pct": NULLABLE_NUMBER,
}, required=[
    "name", "full_name", "coverage_pct", "line_pct", "toggle_pct",
    "branch_pct", "condition_pct", "fsm_pct", "assert_pct",
])

FUNCTIONAL_SUMMARY_ITEM = {
    "oneOf": [
        _object(
            {
                group_by: _string(min_length=1),
                **COVERAGE_SCORE_PROPS,
            },
            required=[group_by, *COVERAGE_SCORE_PROPS],
        )
        for group_by in FUNCTIONAL_LEVELS
    ],
}

FUNCTIONAL_HOLE_ITEM = _object({
    "covergroup": NULLABLE_STRING,
    "coverpoint": NULLABLE_STRING,
    "cross": NULLABLE_STRING,
    "bin": NULLABLE_STRING,
    "covered": NULLABLE_INTEGER,
    "coverable": NULLABLE_INTEGER,
    "count": NULLABLE_INTEGER,
    "coverage_pct": NULLABLE_NUMBER,
    "status": _array(_string(enum=sorted(STATUS_VALUES)), min_items=1),
    "file": NULLABLE_NONEMPTY_STRING,
    "line": NULLABLE_POSITIVE_INTEGER,
}, required=[
    "covergroup", "coverpoint", "cross", "bin", "covered", "coverable",
    "count", "coverage_pct", "status", "file", "line",
])

EVIDENCE = _object({
    "file": NULLABLE_NONEMPTY_STRING,
    "line": NULLABLE_POSITIVE_INTEGER,
}, required=["file", "line"])

EVIDENCE_SOURCE = _object({
    "inherited": {"const": True},
    "type": _string(min_length=1),
    "name": _string(min_length=1),
    "full_name": _string(min_length=1),
}, required=["inherited", "type", "name", "full_name"])

BRANCH_MASK = _object({
    "encoding": _string(min_length=1),
    "branch_arm_index": _integer(0),
    "one_positions": _array(_integer(0)),
    "dontcare_bits": _integer(0),
    "active_bits": _integer(0),
})

COVERAGE_ITEM = _object({
    "coverage_ref": _string(min_length=1),
    "metric": _string(min_length=1),
    "type": _string(min_length=1),
    "scope": NULLABLE_STRING,
    "name": _string(min_length=1),
    "full_name": _string(min_length=1),
    **COVERAGE_SCORE_PROPS,
    "count": NULLABLE_INTEGER,
    "status": _array(_string(enum=sorted(STATUS_VALUES)), min_items=1),
    "evidence": EVIDENCE,
    "evidence_source": EVIDENCE_SOURCE,
    "value": SCALAR,
    "toggle_signal": NULLABLE_STRING,
    "toggle_bit": NULLABLE_STRING,
    "toggle_transition": NULLABLE_STRING,
    "toggle_is_port": _nullable(_bool()),
    "branch": NULLABLE_STRING,
    "branch_bin": NULLABLE_STRING,
    "branch_terms": NULLABLE_STRING,
    "branch_mask": BRANCH_MASK,
    "condition": NULLABLE_STRING,
    "condition_bin": NULLABLE_STRING,
    "condition_terms": NULLABLE_STRING,
    "assert_kind": NULLABLE_STRING,
    "assert_object": NULLABLE_STRING,
    "assert_bin": NULLABLE_STRING,
    "severity": SCALAR,
    "category": SCALAR,
    "fsm": NULLABLE_STRING,
    "covergroup": NULLABLE_STRING,
    "coverpoint": NULLABLE_STRING,
    "cross": NULLABLE_STRING,
    "bin": NULLABLE_STRING,
}, required=[
    "metric", "type", "scope", "name", "full_name", *COVERAGE_SCORE_PROPS,
    "count", "status", "evidence", "coverage_ref",
])

EXCLUSION_ITEM = _object({
    "coverage_ref": _string(min_length=1),
    "metric": _string(min_length=1),
    "type": _string(min_length=1),
    "scope": NULLABLE_STRING,
    "name": _string(min_length=1),
    "full_name": _string(min_length=1),
    "file": NULLABLE_NONEMPTY_STRING,
    "line": NULLABLE_POSITIVE_INTEGER,
    "compile_time": _bool(),
    "report_time": _bool(),
    "status": _array(_string(enum=sorted(STATUS_VALUES)), min_items=1),
}, required=[
    "coverage_ref", "metric", "type", "scope", "name", "full_name",
    "file", "line", "compile_time", "report_time", "status",
])

EXCLUSION_LOAD_ITEM = _object({
    "path": _string(min_length=1),
    "status": {"const": "loaded"},
}, required=["path", "status"])

EXCLUSION_SET_ITEM = _object({
    "coverage_ref": _string(min_length=1),
    "status": _string(enum=[
        "changed",
        "already_in_state",
        "immutable_compile_time",
        "failed",
    ]),
    "before": _bool(),
    "after": _bool(),
    "match_count": _integer(0),
}, required=["coverage_ref", "status"])

EXCLUSION_UNLOAD_ITEM = _object({
    "before_count": _integer(0),
    "after_count": _integer(0),
    "status": {"const": "changed"},
}, required=["before_count", "after_count", "status"])

LINE_UPDATE = _object({
    "old_line": _integer(1),
    "new_line": _integer(1),
}, required=["old_line", "new_line"])

CSV_WORKFLOW_ITEM = _object({
    "coverage_kind": _string(enum=["code", "functional", "assertion"]),
    "path": _string(min_length=1),
    "group_count": _integer(0),
    "record_count": _integer(0),
    "source_file": _string(min_length=1),
    "source_commit": _string(min_length=1),
    "current_commit": NULLABLE_STRING,
    "csv_line": _integer(1),
    "status": _string(min_length=1),
    "validity": _string(enum=[
        "still_valid",
        "now_covered",
        "coverage_object_missing",
        "ambiguous",
    ]),
    "renamed_to": NULLABLE_STRING,
    "line_updates": _array(LINE_UPDATE),
    "match_count": _integer(0),
    "reason": _string(min_length=1),
    "coverage_refs": _array(_string(min_length=1)),
    "action": _string(min_length=1),
    "automatic": _bool(),
    "stamp_status": _string(min_length=1),
    "patch": _string(min_length=1),
}, required=["status"])

ANNOTATION = _object({
    "metric": NULLABLE_STRING,
    "type": NULLABLE_STRING,
    "name": NULLABLE_STRING,
    "full_name": NULLABLE_STRING,
    "covered": NULLABLE_INTEGER,
    "coverable": NULLABLE_INTEGER,
    "missing": NULLABLE_INTEGER,
    "status": _array(_string(enum=sorted(STATUS_VALUES)), min_items=1),
    "file": NULLABLE_NONEMPTY_STRING,
    "line": NULLABLE_POSITIVE_INTEGER,
    "branch": SCALAR,
    "branch_bin": SCALAR,
    "branch_terms": SCALAR,
    "condition": SCALAR,
    "condition_bin": SCALAR,
    "condition_terms": SCALAR,
    "toggle_signal": SCALAR,
    "toggle_bit": SCALAR,
    "toggle_transition": SCALAR,
    "assert_kind": SCALAR,
    "assert_object": SCALAR,
}, required=[
    "metric", "type", "name", "full_name", "covered", "coverable", "missing",
    "status", "file", "line",
])

ANNOTATED_SOURCE_ITEM = _object({
    "file": _string(),
    "line": _integer(),
    "source": NULLABLE_STRING,
    "annotations": _array(ANNOTATION),
    "annotation_count": _integer(0),
}, required=["file", "line", "source", "annotations", "annotation_count"])

ASSERT_SUMMARY_ITEM = _object({
    "name": NULLABLE_STRING,
    "full_name": NULLABLE_STRING,
    **COVERAGE_SCORE_PROPS,
    "status": _array(_string(enum=sorted(STATUS_VALUES)), min_items=1),
    "attempts": _integer(0),
    "real_successes": _integer(0),
    "without_attempts": _integer(0),
}, required=[
    "name", "full_name", *COVERAGE_SCORE_PROPS, "status", "attempts",
    "real_successes", "without_attempts",
])


def _items_data(item: Json, *, filters_action: str | None = None) -> Json:
    props: Json = {"items": _array(item)}
    required = ["items"]
    if filters_action is not None:
        props["filters"] = _filters(filters_action)
        required.insert(0, "filters")
    return _object(props, required=required)


def _query_summary(extra: Json | None = None) -> Json:
    return _completeness_summary(extra)


def _csv_workflow_args(action: str) -> Json:
    props: Json = {"directory": _string(min_length=1)}
    if action in {
        "exclude.csv.status",
        "exclude.csv.impact",
        "exclude.csv.rebase",
        "exclude.csv.stamp_changed",
    }:
        props["repo_root"] = _string(min_length=1)
    if action in {
        "exclude.csv.resolve",
        "exclude.csv.apply",
        "exclude.csv.compile",
        "exclude.csv.stamp_changed",
    }:
        props["test"] = {"const": "merged"}
    if action == "exclude.csv.compile":
        props["output_directory"] = _string(min_length=1)
        props["allow_absolute_path"] = _bool()
    if action == "exclude.csv.format":
        props["write"] = _bool()
    if action == "exclude.csv.rebase":
        props["review_output"] = _export_output()
        props["write"] = _bool()
    return _args(props)


SCHEMAS: Dict[str, Json] = {
    "actions": _schema_entry(
        "actions",
        _request("actions"),
        _completeness_summary(),
        _items_data(ACTION_ITEM),
    ),
    "schema": _schema_entry(
        "schema",
        _request(
            "schema",
            args=_args({
                "action": _string(min_length=1),
                "kind": _string(enum=["request", "response"]),
            }, required=["action"]),
            require_args=True,
        ),
        _completeness_summary(),
        _object(
            {"schema": SCHEMA_NODE},
            required=["schema"],
        ),
    ),
    "session.open": _schema_entry(
        "session.open",
        _request(
            "session.open",
            target=_target({
                "vdb": _string(min_length=1),
                "run_manifest": _string(min_length=1),
            }, required=["vdb"]),
            args=_args({
                "name": _string(min_length=1),
                "exclusion_policy": _string(enum=["default", "strict"]),
            }),
            require_target=True,
        ),
        _completeness_summary(),
        _object({
            "session": SESSION,
            "resource_snapshot": RESOURCE_SNAPSHOT,
        }, required=["session", "resource_snapshot"]),
    ),
    "session.status": _schema_entry(
        "session.status",
        _request("session.status", target=SESSION_TARGET, require_target=True),
        _completeness_summary(),
        _object({
            "session": SESSION,
            "cached_indexes": {"const": "lazy"},
        }, required=["session", "cached_indexes"]),
    ),
    "session.close": _schema_entry(
        "session.close",
        _request("session.close", target=SESSION_TARGET, require_target=True),
        _completeness_summary(),
        _object({"session": SESSION}, required=["session"]),
    ),
    "tests.list": _schema_entry(
        "tests.list",
        _request(
            "tests.list",
            target=SESSION_TARGET,
            args=_args({
                "query": _query("tests.list"),
                "limits": _limits(),
            }),
            require_target=True,
        ),
        _query_summary({"session_id": _string(min_length=1)}),
        _items_data(TEST_ITEM, filters_action="tests.list"),
    ),
    "metrics.list": _schema_entry(
        "metrics.list",
        _request(
            "metrics.list",
            target=SESSION_TARGET,
            args=_args({
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
                "limits": _limits(),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
        }),
        _items_data(METRIC_ITEM),
    ),
    "scope.summary": _schema_entry(
        "scope.summary",
        _request(
            "scope.summary",
            target=SESSION_TARGET,
            args=_args(_coverage_query_props("scope.summary")),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
        }),
        _items_data(SCOPE_SUMMARY_ITEM, filters_action="scope.summary"),
    ),
    "scope.children": _schema_entry(
        "scope.children",
        _request(
            "scope.children",
            target=SESSION_TARGET,
            args=_args({
                **_coverage_query_props("scope.children"),
                "recursive": _bool(),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
        }),
        _items_data(SCOPE_BRIEF_ITEM, filters_action="scope.children"),
    ),
    "scope.search": _schema_entry(
        "scope.search",
        _request(
            "scope.search",
            target=SESSION_TARGET,
            args=_args(_coverage_query_props("scope.search")),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
        }),
        _items_data(SCOPE_BRIEF_ITEM, filters_action="scope.search"),
    ),
    "code_coverage.summary": _schema_entry(
        "code_coverage.summary",
        _request(
            "code_coverage.summary",
            target=SESSION_TARGET,
            args=_args({
                **_coverage_query_props(
                    "code_coverage.summary",
                    metrics=CODE_METRICS,
                ),
                "group_by": _string(enum=["metric", "scope", "source_file", "type"]),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
            "metrics": _string_array(CODE_METRICS, min_items=1),
        }),
        _items_data(
            CODE_SUMMARY_ITEM,
            filters_action="code_coverage.summary",
        ),
    ),
    "code_coverage.holes": _schema_entry(
        "code_coverage.holes",
        _request(
            "code_coverage.holes",
            target=SESSION_TARGET,
            args=_args(_coverage_query_props(
                "code_coverage.holes",
                metrics=CODE_METRICS,
            )),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
            "metrics": _string_array(CODE_METRICS, min_items=1),
            "note": _string(min_length=1),
        }),
        _items_data(
            CODE_HOLE_ITEM,
            filters_action="code_coverage.holes",
        ),
    ),
    "functional_coverage.summary": _schema_entry(
        "functional_coverage.summary",
        _request(
            "functional_coverage.summary",
            target=SESSION_TARGET,
            args=_args({
                **_query_props("functional_coverage.summary"),
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
                "group_by": _string(enum=FUNCTIONAL_LEVELS),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "test": _string(min_length=1),
        }),
        _items_data(
            FUNCTIONAL_SUMMARY_ITEM,
            filters_action="functional_coverage.summary",
        ),
    ),
    "functional_coverage.holes": _schema_entry(
        "functional_coverage.holes",
        _request(
            "functional_coverage.holes",
            target=SESSION_TARGET,
            args=_args({
                **_query_props("functional_coverage.holes"),
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
                "levels": _string_array(
                    FUNCTIONAL_LEVELS,
                    min_items=1,
                ),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "test": _string(min_length=1),
        }),
        _items_data(
            FUNCTIONAL_HOLE_ITEM,
            filters_action="functional_coverage.holes",
        ),
    ),
    "source.map": _schema_entry(
        "source.map",
        _request(
            "source.map",
            target=SESSION_TARGET,
            args=_args({
                "file": _string(min_length=1),
                "line": _integer(1),
                "window": _integer(0),
                "metrics": _string_array(METRICS, min_items=1),
                "test": _string(min_length=1),
                "query": _query("source.map"),
                "limits": _limits(),
            }, required=["file", "line"]),
            require_target=True,
            require_args=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "file": _string(min_length=1),
            "line": _integer(1),
            "window": _integer(0),
        }),
        _items_data(COVERAGE_ITEM, filters_action="source.map"),
    ),
    "source.annotate": _schema_entry(
        "source.annotate",
        _request(
            "source.annotate",
            target=SESSION_TARGET,
            args=_args({
                "file": _string(min_length=1),
                "line": _integer(1),
                "window": _integer(0),
                "metrics": _string_array(METRICS, min_items=1),
                "test": _string(min_length=1),
                "query": _query("source.annotate"),
                "limits": _limits(),
                "include_source_text": _bool(),
                "include_covered": _bool(),
            }, required=["file", "line"]),
            require_target=True,
            require_args=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "file": _string(min_length=1),
            "line": _integer(1),
            "window": _integer(0),
            "include_source_text": _bool(),
        }),
        _items_data(
            ANNOTATED_SOURCE_ITEM,
            filters_action="source.annotate",
        ),
    ),
    "assert.summary": _schema_entry(
        "assert.summary",
        _request(
            "assert.summary",
            target=SESSION_TARGET,
            args=_args({
                "query": _query("assert.summary"),
                "limits": _limits(),
                "sort": _sort("assert.summary"),
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
        }),
        _items_data(ASSERT_SUMMARY_ITEM, filters_action="assert.summary"),
    ),
    "export.code_coverage": _schema_entry(
        "export.code_coverage",
        _request(
            "export.code_coverage",
            target=SESSION_TARGET,
            args=_args({
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
                "metrics": _string_array(CODE_METRICS, min_items=1),
                "threshold_pct": _number(0.0, 100.0),
                "output": _export_output(),
            }, required=["output"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
            "threshold_pct": _number(0.0, 100.0),
            "output_mode": {"const": "file"},
            "output_path": _string(min_length=1),
            "artifact_format": {"const": "md"},
            "note": _string(min_length=1),
        }),
        _object(),
    ),
    "export.functional_coverage": _schema_entry(
        "export.functional_coverage",
        _request(
            "export.functional_coverage",
            target=SESSION_TARGET,
            args=_args({
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
                "covergroup": _string(min_length=1),
                "threshold_pct": _number(0.0, 100.0),
                "output": _export_output(),
            }, required=["output"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
            "threshold_pct": _number(0.0, 100.0),
            "output_mode": {"const": "file"},
            "output_path": _string(min_length=1),
            "artifact_format": {"const": "md"},
            "note": _string(min_length=1),
        }),
        _object(),
    ),
    "export.assert": _schema_entry(
        "export.assert",
        _request(
            "export.assert",
            target=SESSION_TARGET,
            args=_args({
                "scope": _string(min_length=1),
                "test": _string(min_length=1),
                "threshold_pct": _number(0.0, 100.0),
                "output": _export_output(),
            }, required=["output"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary({
            "session_id": _string(min_length=1),
            "scope": NULLABLE_STRING,
            "test": _string(min_length=1),
            "threshold_pct": _number(0.0, 100.0),
            "output_mode": {"const": "file"},
            "output_path": _string(min_length=1),
            "artifact_format": {"const": "md"},
            "note": _string(min_length=1),
        }),
        _object(),
    ),
    "exclude.list": _schema_entry(
        "exclude.list",
        _request(
            "exclude.list",
            target=SESSION_TARGET,
            args=_args({
                "test": {"const": "merged"},
                "limits": _limits(),
            }),
            require_target=True,
        ),
        _query_summary({
            "session_id": _string(min_length=1),
            "test": {"const": "merged"},
        }),
        _items_data(EXCLUSION_ITEM),
    ),
    "exclude.load": _schema_entry(
        "exclude.load",
        _request(
            "exclude.load",
            target=SESSION_TARGET,
            args=_args({
                "paths": _array(_string(min_length=1), min_items=1),
                "allow_absolute_path": _bool(),
                "test": {"const": "merged"},
            }, required=["paths"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary(),
        _items_data(EXCLUSION_LOAD_ITEM),
    ),
    "exclude.add": _schema_entry(
        "exclude.add",
        _request(
            "exclude.add",
            target=SESSION_TARGET,
            args=_args({
                "coverage_refs": _array(_string(min_length=1), min_items=1),
                "test": {"const": "merged"},
            }, required=["coverage_refs"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary(),
        _items_data(EXCLUSION_SET_ITEM),
    ),
    "exclude.remove": _schema_entry(
        "exclude.remove",
        _request(
            "exclude.remove",
            target=SESSION_TARGET,
            args=_args({
                "coverage_refs": _array(_string(min_length=1), min_items=1),
                "test": {"const": "merged"},
            }, required=["coverage_refs"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary(),
        _items_data(EXCLUSION_SET_ITEM),
    ),
    "export.exclude": _schema_entry(
        "export.exclude",
        _request(
            "export.exclude",
            target=SESSION_TARGET,
            args=_args({
                "test": {"const": "merged"},
                "output": _export_output(),
            }, required=["output"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary({
            "session_id": _string(min_length=1),
            "test": {"const": "merged"},
            "output_mode": {"const": "file"},
            "output_path": _string(min_length=1),
            "artifact_format": {"const": "el"},
            "exported_count": _integer(0),
        }),
        _object(),
    ),
    "exclude.unload_all": _schema_entry(
        "exclude.unload_all",
        _request(
            "exclude.unload_all",
            target=SESSION_TARGET,
            args=_args({
                "test": {"const": "merged"},
                "confirm": _bool(),
            }, required=["confirm"]),
            require_target=True,
            require_args=True,
        ),
        _completeness_summary(),
        _items_data(EXCLUSION_UNLOAD_ITEM),
    ),
    **{
        action: _schema_entry(
            action,
            _request(
                action,
                target=SESSION_TARGET if action in {
                    "exclude.csv.resolve",
                    "exclude.csv.apply",
                    "exclude.csv.compile",
                    "exclude.csv.stamp_changed",
                } else _target(),
                args=_csv_workflow_args(action),
                require_target=action in {
                    "exclude.csv.resolve",
                    "exclude.csv.apply",
                    "exclude.csv.compile",
                    "exclude.csv.stamp_changed",
                },
            ),
            _completeness_summary(),
            _items_data(
                EXCLUSION_SET_ITEM
                if action == "exclude.csv.apply"
                else CSV_WORKFLOW_ITEM
            ),
        )
        for action in (
            "exclude.csv.validate",
            "exclude.csv.status",
            "exclude.csv.impact",
            "exclude.csv.resolve",
            "exclude.csv.apply",
            "exclude.csv.compile",
            "exclude.csv.rebase",
            "exclude.csv.stamp_changed",
            "exclude.csv.format",
        )
    },
}


class SchemaValidationError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


_SCHEMA_NODE_KEYWORDS = {
    "type",
    "const",
    "enum",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "pattern",
    "properties",
    "additionalProperties",
    "required",
    "items",
    "anyOf",
    "oneOf",
    "x-schema-node",
}
_SCHEMA_NODE_TYPES = {
    "object",
    "array",
    "string",
    "boolean",
    "integer",
    "number",
    "null",
}


def _validate_schema_node(value: Any, path: str) -> None:
    if not isinstance(value, dict) or not value:
        raise SchemaValidationError(path, "must be a non-empty schema object")
    unknown = sorted(set(value) - _SCHEMA_NODE_KEYWORDS)
    if unknown:
        raise SchemaValidationError(
            path,
            f"contains unsupported schema keywords {unknown!r}",
        )

    if "x-schema-node" in value:
        if value != SCHEMA_NODE:
            raise SchemaValidationError(
                path,
                "x-schema-node must be the exact declared dynamic schema node",
            )
        return

    declared_type = value.get("type")
    declared_types: List[str] = []
    if declared_type is not None:
        declared_types = (
            [declared_type]
            if isinstance(declared_type, str)
            else declared_type
        )
        if (
            not isinstance(declared_types, list)
            or not declared_types
            or any(item not in _SCHEMA_NODE_TYPES for item in declared_types)
            or len(set(declared_types)) != len(declared_types)
        ):
            raise SchemaValidationError(path, "contains an invalid type declaration")
    declared_type_set = set(declared_types)

    properties = value.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise SchemaValidationError(path, "properties must be an object")
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise SchemaValidationError(path, "property names must be non-empty strings")
            _validate_schema_node(child, f"{path}.properties.{name}")

    if "object" in declared_type_set or properties is not None:
        if properties is not None and "object" not in declared_type_set:
            raise SchemaValidationError(path, "properties requires type=object")
        if value.get("additionalProperties") is not False:
            raise SchemaValidationError(
                path,
                "object schemas must declare additionalProperties=false",
            )
    elif "additionalProperties" in value:
        raise SchemaValidationError(
            path,
            "additionalProperties is only valid for object schemas",
        )

    required = value.get("required")
    if required is not None:
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(item, str) or not item for item in required)
            or len(set(required)) != len(required)
        ):
            raise SchemaValidationError(path, "required must be a unique string list")
        if not isinstance(properties, dict) or not set(required) <= set(properties):
            raise SchemaValidationError(
                path,
                "required entries must name declared properties",
            )

    if "array" in declared_type_set and "items" not in value:
        raise SchemaValidationError(path, "array schemas must declare items")
    if "items" in value:
        if "array" not in declared_type_set:
            raise SchemaValidationError(path, "items requires type=array")
        _validate_schema_node(value["items"], f"{path}.items")

    for keyword in ("anyOf", "oneOf"):
        if keyword not in value:
            continue
        variants = value[keyword]
        if not isinstance(variants, list) or not variants:
            raise SchemaValidationError(path, f"{keyword} must be a non-empty list")
        for index, child in enumerate(variants):
            _validate_schema_node(child, f"{path}.{keyword}[{index}]")

    enum = value.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        raise SchemaValidationError(path, "enum must be a non-empty list")

    for keyword in ("minimum", "maximum"):
        if keyword in value and (
            not isinstance(value[keyword], (int, float))
            or isinstance(value[keyword], bool)
            or not math.isfinite(float(value[keyword]))
        ):
            raise SchemaValidationError(path, f"{keyword} must be numeric")
    if (
        "minimum" in value
        and "maximum" in value
        and value["minimum"] > value["maximum"]
    ):
        raise SchemaValidationError(path, "minimum must not exceed maximum")

    for keyword in ("minLength", "maxLength", "minItems"):
        if keyword in value and (
            not isinstance(value[keyword], int)
            or isinstance(value[keyword], bool)
            or value[keyword] < 0
        ):
            raise SchemaValidationError(
                path,
                f"{keyword} must be a non-negative integer",
            )
    if (
        "minLength" in value
        and "maxLength" in value
        and value["minLength"] > value["maxLength"]
    ):
        raise SchemaValidationError(path, "minLength must not exceed maxLength")
    if "pattern" in value:
        pattern = value["pattern"]
        if not isinstance(pattern, str):
            raise SchemaValidationError(path, "pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise SchemaValidationError(path, f"pattern is invalid: {exc}") from exc


def _validate(value: Any, schema: Json, path: str = "$") -> None:
    if not schema:
        raise SchemaValidationError(path, "validator received an empty schema")
    if schema.get("x-schema-node") is True:
        _validate_schema_node(value, path)
        return
    if "oneOf" in schema:
        matches = 0
        failures: List[str] = []
        for candidate in schema["oneOf"]:
            try:
                _validate(value, candidate, path)
                matches += 1
            except SchemaValidationError as exc:
                failures.append(str(exc))
        if matches != 1:
            raise SchemaValidationError(
                path,
                f"must match exactly one schema variant (matched={matches}); "
                f"first failure: {failures[0] if failures else 'none'}",
            )
        return
    if "anyOf" in schema:
        failures = []
        for candidate in schema["anyOf"]:
            try:
                _validate(value, candidate, path)
                return
            except SchemaValidationError as exc:
                failures.append(str(exc))
        raise SchemaValidationError(
            path,
            f"must match one schema variant; first failure: "
            f"{failures[0] if failures else 'none'}",
        )
    if "const" in schema:
        expected_const = schema["const"]
        if type(value) is not type(expected_const) or value != expected_const:
            raise SchemaValidationError(
                path,
                f"must equal {expected_const!r} with the same JSON type",
            )
    if "enum" in schema and not any(
        type(value) is type(candidate) and value == candidate
        for candidate in schema["enum"]
    ):
        raise SchemaValidationError(path, f"must be one of {schema['enum']!r}")
    expected = schema.get("type")
    if expected is not None:
        expected_types = [expected] if isinstance(expected, str) else list(expected)
        if not any(_is_type(value, item) for item in expected_types):
            raise SchemaValidationError(path, f"expected type {expected_types!r}")
    if (
        isinstance(value, float)
        and not math.isfinite(value)
    ):
        raise SchemaValidationError(path, "must be a finite JSON number")
    if isinstance(value, dict) and (
        expected == "object" or "properties" in schema or "additionalProperties" in schema
    ):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaValidationError(path, f"missing required property {key!r}")
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                _validate(item, properties[key], child_path)
                continue
            additional = schema.get("additionalProperties", False)
            if additional is False:
                raise SchemaValidationError(path, f"unknown property {key!r}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaValidationError(path, f"requires at least {schema['minItems']} items")
    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        raise SchemaValidationError(path, f"requires length >= {schema['minLength']}")
    if isinstance(value, str) and "maxLength" in schema and len(value) > schema["maxLength"]:
        raise SchemaValidationError(path, f"requires length <= {schema['maxLength']}")
    if isinstance(value, str) and "pattern" in schema:
        if re.search(schema["pattern"], value) is None:
            raise SchemaValidationError(
                path,
                f"must match pattern {schema['pattern']!r}",
            )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaValidationError(path, f"must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaValidationError(path, f"must be <= {schema['maximum']}")


def validate_request(req: Json) -> None:
    action = req.get("action")
    if not isinstance(action, str) or not action:
        raise XcovError("SCHEMA_INVALID", "action is required", path="$.action")
    entry = SCHEMAS.get(action)
    if entry is None:
        raise XcovError("UNKNOWN_ACTION", "unknown action", action=action)
    try:
        _validate(req, entry["request"])
    except SchemaValidationError as exc:
        raise XcovError("SCHEMA_INVALID", exc.message, path=exc.path) from exc


def validate_run_manifest_document(document: Any) -> Json:
    """Validate and isolate one strict xcov run-manifest input document."""
    _validate(document, RUN_MANIFEST_INPUT, "$")
    return deepcopy(document)


def validate_stdio_request(req: Json) -> None:
    if req.get("action") == "stdio.quit":
        schema = STDIO_QUIT_REQUEST
    else:
        action = req.get("action")
        entry = SCHEMAS.get(action) if isinstance(action, str) else None
        if entry is None:
            if (
                not isinstance(req.get("request_id"), str)
                or not req["request_id"]
            ):
                raise XcovError(
                    "SCHEMA_INVALID",
                    "stdio request_id is required",
                    path="$.request_id",
                )
            return
        schema = deepcopy(entry["request"])
        required = schema.setdefault("required", [])
        if "request_id" not in required:
            required.append("request_id")
    try:
        _validate(req, schema)
    except SchemaValidationError as exc:
        raise XcovError("SCHEMA_INVALID", exc.message, path=exc.path) from exc


def validate_response(action: str, rsp: Json) -> None:
    entry = SCHEMAS.get(action)
    schema = entry["response"] if entry is not None else _error_schema()
    try:
        _validate(rsp, schema)
        _validate_response_semantics(rsp)
    except SchemaValidationError as exc:
        raise XcovError("RESPONSE_SCHEMA_INVALID", exc.message, path=exc.path) from exc


def _validate_response_semantics(rsp: Json) -> None:
    summary = rsp["summary"]
    total_count = summary["total_count"]
    returned_count = summary["returned_count"]
    response_truncated = summary["response_truncated"]
    truncation_scopes = summary["truncation_scopes"]

    if returned_count > total_count:
        raise SchemaValidationError(
            "$.summary.returned_count",
            "must not exceed summary.total_count",
        )
    if response_truncated and returned_count >= total_count:
        raise SchemaValidationError(
            "$.summary.response_truncated",
            "requires returned_count < total_count",
        )
    if response_truncated and not truncation_scopes:
        raise SchemaValidationError(
            "$.summary.truncation_scopes",
            "must identify every truncated response scope",
        )
    if not response_truncated and truncation_scopes:
        raise SchemaValidationError(
            "$.summary.truncation_scopes",
            "must be empty when response_truncated=false",
        )

    data = rsp["data"]
    if not rsp["ok"]:
        if total_count != 0 or returned_count != 0:
            raise SchemaValidationError(
                "$.summary",
                "error responses must report total_count=returned_count=0",
            )
        if data:
            raise SchemaValidationError(
                "$.data",
                "error responses must not publish success data",
            )
        return

    action = rsp["action"]
    if "items" in data:
        items = data["items"]
        if returned_count != len(items):
            raise SchemaValidationError(
                "$.summary.returned_count",
                "must equal the number of returned data.items",
            )
        expected_truncated = returned_count < total_count
        if response_truncated != expected_truncated:
            raise SchemaValidationError(
                "$.summary.response_truncated",
                "must state whether data.items omits analyzed items",
            )
        expected_scopes = ["data.items"] if expected_truncated else []
        if truncation_scopes != expected_scopes:
            raise SchemaValidationError(
                "$.summary.truncation_scopes",
                "must be exactly ['data.items'] when data.items is truncated",
            )
        if action == "source.annotate":
            for index, item in enumerate(items):
                if item["annotation_count"] != len(item["annotations"]):
                    raise SchemaValidationError(
                        f"$.data.items[{index}].annotation_count",
                        "must equal the number of annotations",
                    )
        return

    if action == "schema" or action in {
        "session.open",
        "session.status",
        "session.close",
    }:
        if total_count != 1 or returned_count != 1:
            raise SchemaValidationError(
                "$.summary",
                f"{action} must report exactly one returned object",
            )
        if response_truncated:
            raise SchemaValidationError(
                "$.summary.response_truncated",
                f"{action} cannot truncate its singleton object",
            )
        return

    if action in {
        "export.code_coverage",
        "export.functional_coverage",
        "export.assert",
        "export.exclude",
    }:
        if returned_count != 0 or response_truncated:
            raise SchemaValidationError(
                "$.summary",
                "export responses return no inline rows and cannot be response-truncated",
            )
        return

    raise SchemaValidationError(
        "$.data",
        f"action {action!r} has no completeness-to-data binding",
    )


def schema_for_action(action: str, kind: str = "request") -> Json:
    entry = SCHEMAS.get(action)
    if not entry:
        raise KeyError(action)
    if kind not in ("request", "response"):
        raise KeyError(kind)
    return deepcopy(entry[kind])


def schema_actions() -> List[str]:
    return sorted(SCHEMAS)


def stdio_control_actions() -> List[str]:
    """Return transport-control actions declared by the stdio request contract."""
    return [STDIO_QUIT_REQUEST["properties"]["action"]["const"]]
