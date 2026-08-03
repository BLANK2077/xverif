#!/usr/bin/env python3
"""Audit xdebug JSON responses for public contract redundancy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EMPTY_TOP_LEVEL_ARRAYS = {
    "warnings",
    "findings",
    "suggested_next_actions",
}

SAME_MEANING_KEYS = [
    ("event_count", "count"),
    ("signal_count", "total_signals"),
    ("sample_count", "valid_count"),
    ("statement_count", "trace_node_count"),
]

COMPLETENESS_FIELDS = {
    "scan_complete",
    "analysis_complete",
    "response_truncated",
    "total_count",
    "returned_count",
    "truncation_scopes",
}

LEGACY_COMPLETENESS_FIELDS = {"truncated", "truncation_scope"}
RETIRED_RESPONSE_FIELDS = {"driver_last_change_time"}
RETIRED_ERROR_SUGGESTION_FIELDS = {
    "allowed_values",
    "candidates",
    "did_you_mean",
    "suggested_actions",
    "suggestions",
}
SESSION_ACTIONS = {
    "session.open",
    "session.list",
    "session.doctor",
    "session.close",
    "session.kill",
    "session.gc",
}
LIVE_SESSION_ACTIONS = {"session.open", "session.doctor"}
SESSION_OPEN_MANIFEST_POINTER = "/data" + "/run_manifest"
SESSION_SUCCESS_SHAPES = {
    "session.open": (
        {"status"},
        {"run_manifest"},
    ),
    "session.list": (
        {"session_count", "expired_removed_count"},
        {"sessions"},
    ),
    "session.doctor": (
        {"healthy"},
        {"message"},
    ),
    "session.gc": (
        {"before_count", "kept_count", "removed_count"},
        {"kept_sessions", "removed"},
    ),
}
SIGNAL_STABILITY_RETIRED_FIELDS = {
    "initial_value",
    "final_value",
    "first_change",
    "last_change",
    "first_change_time",
}


def _is_response(obj: Any) -> bool:
    return isinstance(obj, dict) and "action" in obj and "ok" in obj


def _response_from_file_root(obj: Any) -> dict[str, Any] | None:
    if _is_response(obj):
        return obj
    if isinstance(obj, dict) and _is_response(obj.get("response")):
        return obj["response"]
    return None


def _json_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == ".json":
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
    return sorted(files)


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _same_json(a: Any, b: Any) -> bool:
    return a == b


def _retired_response_paths(
    value: Any,
    pointer: str = "",
    *,
    inside_error: bool = False,
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{key}"
            child_is_error = inside_error or key == "error"
            if key in LEGACY_COMPLETENESS_FIELDS | RETIRED_RESPONSE_FIELDS:
                paths.append(child_pointer)
            if child_is_error and key in RETIRED_ERROR_SUGGESTION_FIELDS:
                paths.append(child_pointer)
            paths.extend(
                _retired_response_paths(
                    child,
                    child_pointer,
                    inside_error=child_is_error,
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(
                _retired_response_paths(
                    child,
                    f"{pointer}/{index}",
                    inside_error=inside_error,
                )
            )
    return paths


def _nested_response_paths(
    value: Any,
    pointer: str = "",
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        if pointer and _is_response(value):
            paths.append(pointer)
        for key, child in value.items():
            paths.extend(
                _nested_response_paths(child, f"{pointer}/{key}")
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(
                _nested_response_paths(child, f"{pointer}/{index}")
            )
    return paths


def _field_paths(
    value: Any,
    field: str,
    pointer: str = "",
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{key}"
            if key == field:
                paths.append(child_pointer)
            paths.extend(_field_paths(child, field, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(
                _field_paths(child, field, f"{pointer}/{index}")
            )
    return paths


def _is_non_negative_integer(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _session_ids(records: Any) -> list[str] | None:
    if not isinstance(records, list):
        return None
    identifiers: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            return None
        session_id = record.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        identifiers.append(session_id)
    return identifiers


def _removed_session_ids(records: Any) -> list[str] | None:
    if not isinstance(records, list):
        return None
    removed_records: list[Any] = []
    for item in records:
        if not isinstance(item, dict):
            return None
        removed_records.append(item.get("removed_session"))
    return _session_ids(removed_records)


def _audit_count_equals_length(
    path: Path,
    action: str,
    summary: dict[str, Any],
    count_field: str,
    records: Any,
    records_pointer: str,
) -> list[str]:
    count = summary.get(count_field)
    if not _is_non_negative_integer(count):
        return [
            f"{path}: {action} summary.{count_field} must be a "
            "non-negative integer"
        ]
    if not isinstance(records, list):
        return [
            f"{path}: {action} {records_pointer} must be an array"
        ]
    if count != len(records):
        return [
            f"{path}: {action} summary.{count_field}={count} does not "
            f"match {records_pointer} length {len(records)}"
        ]
    return []


def _audit_unique_disjoint_session_sets(
    path: Path,
    action: str,
    left_name: str,
    left_ids: list[str] | None,
    right_name: str | None = None,
    right_ids: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if left_ids is not None and len(left_ids) != len(set(left_ids)):
        errors.append(
            f"{path}: {action} {left_name} contains duplicate session_id"
        )
    if right_name is None:
        return errors
    if right_ids is not None and len(right_ids) != len(set(right_ids)):
        errors.append(
            f"{path}: {action} {right_name} contains duplicate session_id"
        )
    if left_ids is not None and right_ids is not None:
        overlap = sorted(set(left_ids) & set(right_ids))
        if overlap:
            errors.append(
                f"{path}: {action} {left_name} and {right_name} overlap: "
                f"{overlap}"
            )
    return errors


def _audit_session_success(
    path: Path,
    response: dict[str, Any],
) -> list[str]:
    action = response.get("action")
    if action not in SESSION_ACTIONS or response.get("ok") is not True:
        return []

    errors: list[str] = []
    session = response.get("session")
    if action in LIVE_SESSION_ACTIONS:
        if not isinstance(session, dict):
            errors.append(
                f"{path}: {action} success requires one live top-level session"
            )
    elif session is not None:
        errors.append(
            f"{path}: {action} success must not publish a live top-level session"
        )

    data = response.get("data")
    summary = response.get("summary")
    if not isinstance(data, dict) or not isinstance(summary, dict):
        return errors

    nested = _nested_response_paths(data, "/data")
    for pointer in nested:
        errors.append(
            f"{path}: {action} must not embed a public response envelope at "
            f"{pointer}"
        )

    if action in SESSION_SUCCESS_SHAPES:
        expected_summary, required_data = SESSION_SUCCESS_SHAPES[action]
        if set(summary) != expected_summary:
            errors.append(
                f"{path}: {action} summary fields must be "
                f"{sorted(expected_summary)}, got {sorted(summary)}"
            )
        data_fields = set(data)
        allowed_data = set(required_data)
        if action == "session.list":
            allowed_data.add("removed")
        if not required_data <= data_fields or not data_fields <= allowed_data:
            errors.append(
                f"{path}: {action} data fields must be within "
                f"{sorted(allowed_data)} and include "
                f"{sorted(required_data)}, got {sorted(data_fields)}"
            )
    elif action in {"session.close", "session.kill"}:
        single = (
            set(summary) == {"removed"}
            and set(data) == {"removed_session"}
        )
        bulk = (
            set(summary) == {"requested_count", "removed_count"}
            and set(data) == {"removed_sessions"}
        )
        if not (single or bulk):
            errors.append(
                f"{path}: {action} success must use the canonical single "
                "removed_session or bulk removed_sessions shape"
            )

    if action == "session.open":
        if summary.get("status") != "opened":
            errors.append(
                f"{path}: session.open success summary.status must be opened"
            )
    elif action == "session.doctor":
        if summary.get("healthy") is not True:
            errors.append(
                f"{path}: session.doctor success summary.healthy must be true"
            )
    elif action == "session.list":
        sessions = data.get("sessions")
        removed = data.get("removed", [])
        errors.extend(
            _audit_count_equals_length(
                path,
                action,
                summary,
                "session_count",
                sessions,
                "data.sessions",
            )
        )
        errors.extend(
            _audit_count_equals_length(
                path,
                action,
                summary,
                "expired_removed_count",
                removed,
                "data.removed",
            )
        )
        if "removed" in data and removed == []:
            errors.append(
                f"{path}: session.list data.removed must be omitted when no "
                "expired session was removed"
            )
        errors.extend(
            _audit_unique_disjoint_session_sets(
                path,
                action,
                "data.sessions",
                _session_ids(sessions),
                "data.removed",
                _removed_session_ids(removed),
            )
        )
    elif action in {"session.close", "session.kill"}:
        if set(data) == {"removed_session"}:
            if summary.get("removed") is not True:
                errors.append(
                    f"{path}: {action} single success summary.removed must "
                    "be true"
                )
        elif set(data) == {"removed_sessions"}:
            removed_sessions = data.get("removed_sessions")
            for count_field in ("requested_count", "removed_count"):
                errors.extend(
                    _audit_count_equals_length(
                        path,
                        action,
                        summary,
                        count_field,
                        removed_sessions,
                        "data.removed_sessions",
                    )
                )
            if summary.get("requested_count") != summary.get(
                "removed_count"
            ):
                errors.append(
                    f"{path}: {action} successful bulk cleanup requires "
                    "requested_count == removed_count"
                )
            errors.extend(
                _audit_unique_disjoint_session_sets(
                    path,
                    action,
                    "data.removed_sessions",
                    _session_ids(removed_sessions),
                )
            )
    elif action == "session.gc":
        kept_sessions = data.get("kept_sessions")
        removed = data.get("removed")
        errors.extend(
            _audit_count_equals_length(
                path,
                action,
                summary,
                "kept_count",
                kept_sessions,
                "data.kept_sessions",
            )
        )
        errors.extend(
            _audit_count_equals_length(
                path,
                action,
                summary,
                "removed_count",
                removed,
                "data.removed",
            )
        )
        before_count = summary.get("before_count")
        kept_count = summary.get("kept_count")
        removed_count = summary.get("removed_count")
        if not _is_non_negative_integer(before_count):
            errors.append(
                f"{path}: session.gc summary.before_count must be a "
                "non-negative integer"
            )
        elif (
            _is_non_negative_integer(kept_count)
            and _is_non_negative_integer(removed_count)
            and before_count != kept_count + removed_count
        ):
            errors.append(
                f"{path}: session.gc summary.before_count={before_count} "
                "must equal kept_count + removed_count"
            )
        errors.extend(
            _audit_unique_disjoint_session_sets(
                path,
                action,
                "data.kept_sessions",
                _session_ids(kept_sessions),
                "data.removed",
                _removed_session_ids(removed),
            )
        )

    manifest_paths = _field_paths(response, "run_manifest")
    if action == "session.open":
        if manifest_paths != [SESSION_OPEN_MANIFEST_POINTER]:
            errors.append(
                f"{path}: session.open run_manifest must appear exactly once "
                f"at {SESSION_OPEN_MANIFEST_POINTER}, got {manifest_paths}"
            )
    elif manifest_paths:
        errors.append(
            f"{path}: {action} must not publish run_manifest at "
            f"{manifest_paths}"
        )
    return errors


def _audit_signal_stability(
    path: Path,
    response: dict[str, Any],
) -> list[str]:
    if (
        response.get("action") != "signal.stability"
        or response.get("ok") is not True
    ):
        return []
    errors: list[str] = []
    summary = response.get("summary")
    data = response.get("data")
    if isinstance(summary, dict):
        forbidden = {"signal", "value"}.intersection(summary)
        if forbidden:
            errors.append(
                f"{path}: signal.stability summary contains evidence fields "
                f"{sorted(forbidden)}"
            )
    if isinstance(data, dict):
        if not isinstance(data.get("signal"), str) or not data["signal"]:
            errors.append(
                f"{path}: signal.stability data.signal is required"
            )
        retired = SIGNAL_STABILITY_RETIRED_FIELDS.intersection(data)
        if retired:
            errors.append(
                f"{path}: signal.stability data contains derivable fields "
                f"{sorted(retired)}"
            )
    return errors


def audit_response(path: Path, response: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    data = response.get("data")
    summary = response.get("summary")

    for pointer in _retired_response_paths(response):
        errors.append(f"{path}: retired response field is forbidden at {pointer}")

    errors.extend(_audit_session_success(path, response))
    errors.extend(_audit_signal_stability(path, response))

    if isinstance(data, dict) and "summary" in data:
        errors.append(f"{path}: public data.summary is forbidden")

    if isinstance(summary, dict) and isinstance(data, dict):
        for key, value in summary.items():
            if key in data and _same_json(value, data[key]):
                errors.append(f"{path}: summary.{key} duplicates data.{key}")

    for key in EMPTY_TOP_LEVEL_ARRAYS:
        if key in response and response[key] == []:
            errors.append(f"{path}: top-level {key} is an empty default array")

    if "meta" in response:
        errors.append(
            f"{path}: public response.meta is retired; publish action facts in "
            "summary/data"
        )

    if isinstance(summary, dict):
        present = COMPLETENESS_FIELDS.intersection(summary)
        if present and present != COMPLETENESS_FIELDS:
            errors.append(
                f"{path}: partial completeness contract in summary; missing "
                f"{sorted(COMPLETENESS_FIELDS - present)}"
            )
        if present == COMPLETENESS_FIELDS:
            total = summary["total_count"]
            returned = summary["returned_count"]
            scopes = summary["truncation_scopes"]
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                errors.append(f"{path}: summary.total_count must be a non-negative integer")
            if not isinstance(returned, int) or isinstance(returned, bool) or returned < 0:
                errors.append(f"{path}: summary.returned_count must be a non-negative integer")
            if (
                isinstance(total, int)
                and not isinstance(total, bool)
                and isinstance(returned, int)
                and not isinstance(returned, bool)
                and returned > total
            ):
                errors.append(f"{path}: summary.returned_count exceeds total_count")
            if not isinstance(scopes, list) or not all(
                isinstance(scope, str) and scope for scope in scopes
            ):
                errors.append(f"{path}: summary.truncation_scopes must be a string array")
            incomplete = (
                summary["scan_complete"] is False
                or summary["analysis_complete"] is False
                or summary["response_truncated"] is True
            )
            if incomplete and scopes == []:
                errors.append(
                    f"{path}: incomplete/truncated response requires truncation_scopes"
                )

    if isinstance(data, dict):
        misplaced = COMPLETENESS_FIELDS.intersection(data)
        if misplaced:
            errors.append(
                f"{path}: top-level data duplicates summary completeness fields: "
                f"{sorted(misplaced)}"
            )
        for left, right in SAME_MEANING_KEYS:
            if left in data and right in data and data[left] == data[right]:
                errors.append(f"{path}: data.{left} duplicates data.{right}")

    if response.get("action") == "trace.active_driver_chain" and isinstance(data, dict):
        chain = data.get("chain")
        if isinstance(chain, dict):
            for key in [
                "evidence_source",
                "static_candidate_count",
                "active_check_count",
                "truncated",
            ]:
                if key in data and key in chain and data[key] == chain[key]:
                    errors.append(f"{path}: data.{key} duplicates data.chain.{key}")
            stats = chain.get("stats")
            if (
                isinstance(stats, dict)
                and "temporal_boundaries" in data
                and data["temporal_boundaries"] == stats.get("temporal_boundaries")
            ):
                errors.append(
                    f"{path}: data.temporal_boundaries duplicates "
                    "data.chain.stats.temporal_boundaries"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    errors: list[str] = []
    checked = 0
    for path in _json_files(args.paths):
        obj = _load(path)
        response = _response_from_file_root(obj)
        if response is None:
            continue
        checked += 1
        errors.extend(audit_response(path, response))

    if errors:
        print("\n".join(errors))
        print(f"checked={checked} errors={len(errors)}")
        return 1
    print(f"checked={checked} errors=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
