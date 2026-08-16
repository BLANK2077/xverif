"""Strict action-specific contracts for public xsva JSON/XOUT responses."""

from __future__ import annotations

from typing import Any


ACTIONS = frozenset({"list", "scan", "lint", "explain", "parse"})
LOWERING_STATUS = frozenset({
    "exact",
    "partial",
    "opaque",
    "unsupported",
    "unsafe_to_explain",
})
SEMANTIC_PRECISION = {
    "exact": "complete",
    "partial": "partial",
    "opaque": "opaque",
    "unsupported": "unavailable",
    "unsafe_to_explain": "unsafe",
}


class ResponseContractError(ValueError):
    pass


def _contract(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ResponseContractError(f"{path}: {message}")


def _exact(
    value: Any,
    required: set[str],
    *,
    optional: set[str] = frozenset(),
    path: str,
) -> None:
    _contract(isinstance(value, dict), path, "expected object")
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    _contract(not missing, path, f"missing required fields {missing!r}")
    _contract(not unknown, path, f"unknown fields {unknown!r}")


def _string(value: Any, path: str, *, nonempty: bool = False) -> None:
    _contract(
        isinstance(value, str) and (not nonempty or bool(value)),
        path,
        "expected string" if not nonempty else "expected non-empty string",
    )


def _boolean(value: Any, path: str) -> None:
    _contract(isinstance(value, bool), path, "expected boolean")


def _integer(value: Any, path: str, *, nonnegative: bool = False) -> None:
    _contract(
        isinstance(value, int)
        and not isinstance(value, bool)
        and (not nonnegative or value >= 0),
        path,
        "expected integer" if not nonnegative else "expected non-negative integer",
    )


def _nullable_integer(
    value: Any,
    path: str,
    *,
    nonnegative: bool = False,
) -> None:
    if value is not None:
        _integer(value, path, nonnegative=nonnegative)


def _string_array(value: Any, path: str) -> None:
    _contract(
        isinstance(value, list)
        and all(isinstance(item, str) for item in value),
        path,
        "expected string array",
    )


def _span(value: Any, path: str) -> None:
    _exact(
        value,
        {"file", "begin_line", "begin_col", "end_line", "end_col"},
        path=path,
    )
    _string(value["file"], f"{path}.file")
    for field in ("begin_line", "begin_col", "end_line", "end_col"):
        _integer(value[field], f"{path}.{field}", nonnegative=True)


def _diagnostic(value: Any, path: str) -> None:
    _exact(value, {"code", "severity", "message", "span"}, path=path)
    _string(value["code"], f"{path}.code", nonempty=True)
    _contract(
        value["severity"] in {"info", "warning", "error"},
        f"{path}.severity",
        "expected info, warning, or error",
    )
    _string(value["message"], f"{path}.message", nonempty=True)
    _span(value["span"], f"{path}.span")


def _analysis(payload: dict[str, Any]) -> None:
    lowering = payload["lowering_status"]
    _contract(
        lowering in LOWERING_STATUS,
        "$.lowering_status",
        "unknown lowering status",
    )

    precision = payload["precision"]
    _exact(
        precision,
        {"semantic_model", "path_enumeration", "reason_codes"},
        path="$.precision",
    )
    _contract(
        precision["semantic_model"] == SEMANTIC_PRECISION[lowering],
        "$.precision.semantic_model",
        "does not match lowering_status",
    )
    _contract(
        precision["path_enumeration"]
        in {"not_applicable", "complete", "partial"},
        "$.precision.path_enumeration",
        "unknown path enumeration state",
    )
    _string_array(precision["reason_codes"], "$.precision.reason_codes")
    _contract(
        len(set(precision["reason_codes"])) == len(precision["reason_codes"]),
        "$.precision.reason_codes",
        "reason codes must be unique",
    )

    diagnostics = payload["diagnostics"]
    _contract(isinstance(diagnostics, list), "$.diagnostics", "expected array")
    for index, diagnostic in enumerate(diagnostics):
        _diagnostic(diagnostic, f"$.diagnostics[{index}]")

    completeness = payload["completeness"]
    _exact(
        completeness,
        {
            "scan_complete",
            "analysis_complete",
            "response_truncated",
            "path_enumeration_complete",
            "total_path_count",
            "returned_path_count",
            "truncation_scopes",
        },
        path="$.completeness",
    )
    for field in ("scan_complete", "analysis_complete", "response_truncated"):
        _boolean(completeness[field], f"$.completeness.{field}")
    total = completeness["total_path_count"]
    returned = completeness["returned_path_count"]
    path_complete = completeness["path_enumeration_complete"]
    _nullable_integer(total, "$.completeness.total_path_count", nonnegative=True)
    _nullable_integer(
        returned,
        "$.completeness.returned_path_count",
        nonnegative=True,
    )

    if total is None:
        _contract(
            returned is None and path_complete is None,
            "$.completeness",
            "non-applicable path counts must all be null",
        )
        expected_truncated = False
        expected_path_state = "not_applicable"
    else:
        _contract(
            isinstance(path_complete, bool),
            "$.completeness.path_enumeration_complete",
            "expected boolean when path counts are available",
        )
        _contract(
            returned is not None and returned <= total,
            "$.completeness.returned_path_count",
            "must be present and not exceed total_path_count",
        )
        expected_truncated = (not path_complete) or returned < total
        _contract(
            path_complete == (returned == total),
            "$.completeness.path_enumeration_complete",
            "must agree with returned_path_count and total_path_count",
        )
        expected_path_state = "partial" if expected_truncated else "complete"

    _contract(
        completeness["response_truncated"] is expected_truncated,
        "$.completeness.response_truncated",
        "does not match path completeness/counts",
    )
    expected_scopes = ["analysis.match_paths"] if expected_truncated else []
    _contract(
        completeness["truncation_scopes"] == expected_scopes,
        "$.completeness.truncation_scopes",
        "does not match response_truncated",
    )
    _contract(
        precision["path_enumeration"] == expected_path_state,
        "$.precision.path_enumeration",
        "does not match completeness",
    )
    expected_analysis_complete = (
        completeness["scan_complete"]
        and lowering == "exact"
        and not expected_truncated
    )
    _contract(
        completeness["analysis_complete"] is expected_analysis_complete,
        "$.completeness.analysis_complete",
        "does not match scan/lowering/path completeness",
    )


def _list_result(value: Any) -> None:
    _exact(value, {"properties", "assertions"}, path="$.result")
    for field in ("properties", "assertions"):
        _contract(isinstance(value[field], list), f"$.result.{field}", "expected array")
    for index, item in enumerate(value["properties"]):
        path = f"$.result.properties[{index}]"
        _exact(item, {"type", "name"}, path=path)
        _contract(item["type"] == "property", f"{path}.type", "expected property")
        _string(item["name"], f"{path}.name", nonempty=True)
    for index, item in enumerate(value["assertions"]):
        path = f"$.result.assertions[{index}]"
        _exact(item, {"type", "name", "label"}, path=path)
        _contract(
            item["type"] in {"assert", "assume", "cover"},
            f"{path}.type",
            "unknown assertion kind",
        )
        _string(item["name"], f"{path}.name", nonempty=True)
        _string(item["label"], f"{path}.label")


def _scan_result(value: Any) -> None:
    _exact(
        value,
        {"property_blocks", "inline_assertions", "operators"},
        path="$.result",
    )
    for field in ("property_blocks", "inline_assertions"):
        _integer(value[field], f"$.result.{field}", nonnegative=True)
    operators = value["operators"]
    _contract(isinstance(operators, dict), "$.result.operators", "expected object")
    for operator, count in operators.items():
        _string(operator, "$.result.operators.<key>", nonempty=True)
        _integer(count, f"$.result.operators.{operator}", nonnegative=True)


def _local_var(value: Any, path: str) -> None:
    _exact(
        value,
        {"name", "var_type", "scope", "lifetime", "span"},
        path=path,
    )
    for field in ("name", "var_type", "scope", "lifetime"):
        _string(value[field], f"{path}.{field}")
    _span(value["span"], f"{path}.span")


def _surface_result(value: Any) -> None:
    _exact(
        value,
        {
            "schema_version",
            "name",
            "label",
            "kind",
            "raw_text",
            "clock",
            "disable_expr",
            "local_vars",
            "antecedent_raw",
            "implication",
            "consequent_raw",
            "is_named_property",
            "is_inline_property",
            "span",
        },
        path="$.result",
    )
    _contract(
        value["schema_version"] == "xsva.surface_ir.v1",
        "$.result.schema_version",
        "unexpected schema version",
    )
    for field in (
        "name",
        "label",
        "raw_text",
        "disable_expr",
        "antecedent_raw",
        "implication",
        "consequent_raw",
    ):
        _string(value[field], f"$.result.{field}")
    _contract(
        value["kind"] in {"assert", "assume", "cover", "property"},
        "$.result.kind",
        "unknown assertion kind",
    )
    clock = value["clock"]
    _exact(clock, {"edge", "signal", "supported"}, path="$.result.clock")
    _string(clock["edge"], "$.result.clock.edge", nonempty=True)
    _string(clock["signal"], "$.result.clock.signal")
    _boolean(clock["supported"], "$.result.clock.supported")
    _contract(isinstance(value["local_vars"], list), "$.result.local_vars", "expected array")
    for index, item in enumerate(value["local_vars"]):
        _local_var(item, f"$.result.local_vars[{index}]")
    for field in ("is_named_property", "is_inline_property"):
        _boolean(value[field], f"$.result.{field}")
    _span(value["span"], "$.result.span")


def _sequence_node(value: Any, path: str) -> None:
    _exact(
        value,
        {
            "kind",
            "lowering_status",
            "raw",
            "expr",
            "guard_expr",
            "actions",
            "delay",
            "repeat",
            "children",
            "semantic_risk",
            "diagnostics",
        },
        path=path,
    )
    for field in ("kind", "raw", "semantic_risk"):
        _string(value[field], f"{path}.{field}")
    _contract(
        value["lowering_status"] in LOWERING_STATUS,
        f"{path}.lowering_status",
        "unknown lowering status",
    )
    for field in ("expr", "guard_expr"):
        _contract(
            value[field] is None or isinstance(value[field], str),
            f"{path}.{field}",
            "expected string or null",
        )
    _contract(isinstance(value["actions"], list), f"{path}.actions", "expected array")
    for index, action in enumerate(value["actions"]):
        action_path = f"{path}.actions[{index}]"
        _exact(action, {"lhs", "rhs", "action_kind"}, path=action_path)
        for field in ("lhs", "rhs", "action_kind"):
            _string(action[field], f"{action_path}.{field}")
    if value["delay"] is not None:
        delay = value["delay"]
        _exact(delay, {"min", "max", "unbounded"}, path=f"{path}.delay")
        _integer(delay["min"], f"{path}.delay.min", nonnegative=True)
        _nullable_integer(delay["max"], f"{path}.delay.max", nonnegative=True)
        _boolean(delay["unbounded"], f"{path}.delay.unbounded")
    if value["repeat"] is not None:
        repeat = value["repeat"]
        _exact(
            repeat,
            {"kind", "min", "max", "unbounded"},
            path=f"{path}.repeat",
        )
        _string(repeat["kind"], f"{path}.repeat.kind", nonempty=True)
        _integer(repeat["min"], f"{path}.repeat.min", nonnegative=True)
        _nullable_integer(repeat["max"], f"{path}.repeat.max", nonnegative=True)
        _boolean(repeat["unbounded"], f"{path}.repeat.unbounded")
    _contract(isinstance(value["children"], list), f"{path}.children", "expected array")
    for index, child in enumerate(value["children"]):
        _sequence_node(child, f"{path}.children[{index}]")
    _contract(
        isinstance(value["diagnostics"], list),
        f"{path}.diagnostics",
        "expected array",
    )
    for index, diagnostic in enumerate(value["diagnostics"]):
        _diagnostic(diagnostic, f"{path}.diagnostics[{index}]")


def _sequence_result(value: Any) -> None:
    _exact(
        value,
        {"schema_version", "name", "implication", "antecedent", "consequent"},
        path="$.result",
    )
    _contract(
        value["schema_version"] == "xsva.sequence_ir.v1",
        "$.result.schema_version",
        "unexpected schema version",
    )
    _string(value["name"], "$.result.name", nonempty=True)
    _string(value["implication"], "$.result.implication")
    for field in ("antecedent", "consequent"):
        _contract(isinstance(value[field], list), f"$.result.{field}", "expected array")
        for index, node in enumerate(value[field]):
            _sequence_node(node, f"$.result.{field}[{index}]")


def _timeline_result(value: Any) -> None:
    _exact(
        value,
        {
            "schema_version",
            "property",
            "kind",
            "clock",
            "disable_expr",
            "trigger",
            "obligations",
            "match_paths",
            "failure_conditions",
            "semantic_notes",
        },
        path="$.result",
    )
    _contract(
        value["schema_version"] == "xsva.timeline_ir.v1",
        "$.result.schema_version",
        "unexpected schema version",
    )
    _string(value["property"], "$.result.property", nonempty=True)
    _string(value["kind"], "$.result.kind", nonempty=True)
    clock = value["clock"]
    _exact(clock, {"edge", "signal"}, path="$.result.clock")
    _string(clock["edge"], "$.result.clock.edge", nonempty=True)
    _string(clock["signal"], "$.result.clock.signal")
    _string(value["disable_expr"], "$.result.disable_expr")

    trigger = value["trigger"]
    _exact(trigger, {"cycle", "expr", "captures"}, path="$.result.trigger")
    _integer(trigger["cycle"], "$.result.trigger.cycle")
    _string(trigger["expr"], "$.result.trigger.expr")
    _contract(
        isinstance(trigger["captures"], list),
        "$.result.trigger.captures",
        "expected array",
    )
    for index, capture in enumerate(trigger["captures"]):
        path = f"$.result.trigger.captures[{index}]"
        _exact(capture, {"var", "value_expr", "relative_cycle"}, path=path)
        _string(capture["var"], f"{path}.var")
        _string(capture["value_expr"], f"{path}.value_expr")
        _integer(capture["relative_cycle"], f"{path}.relative_cycle")

    _contract(
        isinstance(value["obligations"], list),
        "$.result.obligations",
        "expected array",
    )
    obligation_ids: set[str] = set()
    for index, obligation in enumerate(value["obligations"]):
        path = f"$.result.obligations[{index}]"
        _exact(
            obligation,
            {
                "id",
                "kind",
                "expr",
                "has_window",
                "window",
                "depends_on_captures",
                "signals_to_query",
                "requirement",
                "failure_condition",
            },
            path=path,
        )
        for field in ("id", "kind", "expr", "requirement"):
            _string(obligation[field], f"{path}.{field}")
        _contract(
            bool(obligation["id"]),
            f"{path}.id",
            "expected non-empty canonical obligation id",
        )
        _contract(
            obligation["id"] not in obligation_ids,
            f"{path}.id",
            "canonical obligation ids must be unique",
        )
        obligation_ids.add(obligation["id"])
        _boolean(obligation["has_window"], f"{path}.has_window")
        if obligation["window"] is not None:
            window = obligation["window"]
            _exact(window, {"start", "end", "unbounded"}, path=f"{path}.window")
            _integer(window["start"], f"{path}.window.start")
            _integer(window["end"], f"{path}.window.end")
            _boolean(window["unbounded"], f"{path}.window.unbounded")
        _contract(
            obligation["has_window"] is (obligation["window"] is not None),
            f"{path}.has_window",
            "must agree bidirectionally with window presence",
        )
        _string_array(
            obligation["depends_on_captures"],
            f"{path}.depends_on_captures",
        )
        _string_array(
            obligation["signals_to_query"],
            f"{path}.signals_to_query",
        )
        _contract(
            len(set(obligation["signals_to_query"])) == len(obligation["signals_to_query"]),
            f"{path}.signals_to_query",
            "canonical signal dependencies must be unique",
        )
        _contract(
            obligation["failure_condition"] is None
            or isinstance(obligation["failure_condition"], str),
            f"{path}.failure_condition",
            "expected string or null",
        )

    _contract(
        isinstance(value["match_paths"], list),
        "$.result.match_paths",
        "expected array",
    )
    for index, match_path in enumerate(value["match_paths"]):
        path = f"$.result.match_paths[{index}]"
        _exact(match_path, {"id", "description", "obligations"}, path=path)
        _string(match_path["id"], f"{path}.id")
        _string(match_path["description"], f"{path}.description")
        _string_array(match_path["obligations"], f"{path}.obligations")
        for obligation_index, obligation_id in enumerate(
            match_path["obligations"]
        ):
            _contract(
                obligation_id in obligation_ids,
                f"{path}.obligations[{obligation_index}]",
                "must reference a canonical result.obligations id",
            )

    _string_array(value["failure_conditions"], "$.result.failure_conditions")
    expected_failure_conditions = [
        obligation["failure_condition"]
        for obligation in value["obligations"]
        if obligation["failure_condition"] is not None
    ]
    _contract(
        value["failure_conditions"] == expected_failure_conditions,
        "$.result.failure_conditions",
        "must equal the canonical non-null obligation failure conditions",
    )
    _contract(
        isinstance(value["semantic_notes"], list),
        "$.result.semantic_notes",
        "expected array",
    )
    for index, note in enumerate(value["semantic_notes"]):
        path = f"$.result.semantic_notes[{index}]"
        _exact(note, {"kind", "expr", "text"}, path=path)
        for field in ("kind", "expr", "text"):
            _string(note[field], f"{path}.{field}")


def _success_result(payload: dict[str, Any]) -> None:
    action = payload["action"]
    if action == "list":
        _list_result(payload["result"])
    elif action == "scan":
        _scan_result(payload["result"])
    elif action == "lint":
        _exact(payload["result"], {"issue_count"}, path="$.result")
        _integer(payload["result"]["issue_count"], "$.result.issue_count", nonnegative=True)
        _contract(
            payload["result"]["issue_count"] == len(payload["diagnostics"]),
            "$.result.issue_count",
            "must equal the number of diagnostics",
        )
    elif action == "explain":
        _timeline_result(payload["result"])
    elif action == "parse":
        emit = payload["emit"]
        _contract(
            emit in {"surface-ir", "sequence-ir", "timeline-ir"},
            "$.emit",
            "unknown emit target",
        )
        {
            "surface-ir": _surface_result,
            "sequence-ir": _sequence_result,
            "timeline-ir": _timeline_result,
        }[emit](payload["result"])


def validate_response(
    payload: Any,
    *,
    expected_action: str | None = None,
) -> None:
    _contract(isinstance(payload, dict), "$", "expected object")
    common = {
        "ok",
        "tool",
        "action",
        "lowering_status",
        "precision",
        "diagnostics",
        "completeness",
    }
    _contract(isinstance(payload.get("ok"), bool), "$.ok", "expected boolean")
    _contract(payload.get("tool") == "xsva", "$.tool", "expected xsva")
    action = payload.get("action")
    _contract(
        action in ACTIONS or (not payload["ok"] and action == "error"),
        "$.action",
        "unknown action",
    )
    if expected_action is not None:
        _contract(action == expected_action, "$.action", "does not match request")

    if payload["ok"]:
        action_fields = {
            "list": {"file", "result"},
            "scan": {"file", "result"},
            "lint": {"file", "property", "result"},
            "explain": {"file", "property", "result"},
            "parse": {"file", "property", "emit", "result"},
        }[action]
        _exact(payload, common | action_fields, path="$")
        _string(payload["file"], "$.file", nonempty=True)
        if "property" in action_fields:
            if action == "lint":
                _contract(
                    payload["property"] is None
                    or isinstance(payload["property"], str),
                    "$.property",
                    "expected string or null",
                )
            else:
                _string(payload["property"], "$.property", nonempty=True)
        _analysis(payload)
        _success_result(payload)
        if action == "explain" or (
            action == "parse" and payload.get("emit") == "timeline-ir"
        ):
            returned_path_count = payload["completeness"][
                "returned_path_count"
            ]
            _contract(
                returned_path_count == len(payload["result"]["match_paths"]),
                "$.completeness.returned_path_count",
                "must equal the number of returned result.match_paths",
            )
        return

    _exact(payload, common | {"error"}, path="$")
    _analysis(payload)
    error = payload["error"]
    _exact(error, {"code", "message"}, optional={"details"}, path="$.error")
    _string(error["code"], "$.error.code", nonempty=True)
    _string(error["message"], "$.error.message", nonempty=True)
    if "details" in error:
        details = error["details"]
        _exact(
            details,
            set(),
            optional={"file", "property", "emit"},
            path="$.error.details",
        )
        _contract(bool(details), "$.error.details", "must not be empty")
        for field, value in details.items():
            _string(value, f"$.error.details.{field}", nonempty=True)
