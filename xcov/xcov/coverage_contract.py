from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Literal

from .errors import XcovError

Json = Dict[str, Any]
RowKind = Literal["score", "context", "assert_count"]

METRICS = (
    "line",
    "toggle",
    "branch",
    "condition",
    "fsm",
    "assert",
    "functional",
)

SCORE_TYPES_BY_METRIC = {
    "line": frozenset({"npiCovStmtBin"}),
    "toggle": frozenset({"npiCovToggleBin"}),
    "branch": frozenset({"npiCovBranchBin"}),
    "condition": frozenset({"npiCovConditionBin"}),
    "fsm": frozenset({"npiCovTransBin"}),
    "assert": frozenset({
        "npiCovAssert",
        "npiCovCoverProperty",
        "npiCovCoverSequence",
    }),
    "functional": frozenset({
        "npiCovCovergroup",
        "npiCovCoverpoint",
        "npiCovCross",
        "npiCovCoverBin",
    }),
}

CONTEXT_TYPES_BY_METRIC = {
    "line": frozenset({"npiCovBlock", "npiCovStmt"}),
    "toggle": frozenset({"npiCovSignal", "npiCovSignalBit"}),
    "branch": frozenset({"npiCovBranch", "npiCovBranchTerm"}),
    "condition": frozenset({"npiCovCondition", "npiCovConditionTerm"}),
    "fsm": frozenset({
        "npiCovFSM",
        "npiCovFsm",
        "npiCovState",
        "npiCovStateBin",
        "npiCovStates",
        "npiCovTrans",
        "npiCovTransitions",
        "npiCovSequences",
    }),
    "assert": frozenset(),
    "functional": frozenset(),
}

ASSERT_COUNT_TYPES = frozenset({
    "npiCovAttemptBin",
    "npiCovSuccessBin",
    "npiCovFailureBin",
    "npiCovIncompleteBin",
    "npiCovFirstmatchBin",
})

STATUS_VALUES = frozenset({
    "covered",
    "not_covered",
    "excluded",
    "partially_excluded",
    "excluded_at_compile_time",
    "excluded_at_report_time",
    "unreachable",
    "illegal",
    "proven",
    "attempted",
    "partially_attempted",
})

BASE_FIELDS = frozenset({
    "metric",
    "type",
    "scope",
    "name",
    "full_name",
    "covered",
    "coverable",
    "missing",
    "count",
    "coverage_pct",
    "status",
    "evidence",
})

OPTIONAL_STRING_FIELDS = frozenset({
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
    "coverage_ref",
})

OPTIONAL_FIELDS = frozenset({
    *OPTIONAL_STRING_FIELDS,
    "evidence_source",
    "value",
    "toggle_is_port",
    "branch_mask",
    "severity",
    "category",
})

ALLOWED_FIELDS = BASE_FIELDS | OPTIONAL_FIELDS


def canonicalize_coverage_items(
    raw_items: Any,
    *,
    backend_type: str,
    worker_kind: str,
) -> List[Json]:
    """Validate and canonicalize every backend coverage row.

    This is the sole backend-to-action item boundary.  It deliberately accepts
    only a concrete list so an invalid traversal result cannot be reinterpreted
    as an empty result or consumed lazily after the action has begun emitting
    facts.
    """

    error_code = _contract_error_code(worker_kind)
    if not isinstance(raw_items, list):
        _violation(
            error_code,
            backend_type,
            None,
            "items",
            "list of coverage row objects",
            raw_items,
        )
    rows = [
        _canonicalize_row(
            row,
            row_index=index,
            backend_type=backend_type,
            error_code=error_code,
        )
        for index, row in enumerate(raw_items)
    ]
    for row in rows:
        row.setdefault("coverage_ref", coverage_ref_for_row(row))
    return rows


def coverage_ref_for_row(row: Json) -> str:
    """Return a session-local opaque reference from canonical readable identity.

    The reference deliberately contains no native handle.  A backend must
    re-traverse the VDB and re-check the readable identity before mutating an
    object.
    """

    identity = coverage_identity_for_row(row)
    payload = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "xcovref.v1:" + hashlib.sha256(payload).hexdigest()


def coverage_identity_for_row(row: Json) -> Json:
    identity = {
        key: row.get(key)
        for key in (
            "metric",
            "scope",
            "type",
            "full_name",
            "name",
            "toggle_bit",
            "toggle_transition",
            "branch",
            "branch_bin",
            "condition",
            "condition_bin",
            "fsm",
            "assert_kind",
            "assert_object",
            "covergroup",
            "coverpoint",
            "cross",
            "bin",
        )
    }
    evidence = row.get("evidence")
    identity["evidence"] = (
        {"file": evidence.get("file"), "line": evidence.get("line")}
        if isinstance(evidence, dict)
        else None
    )
    return identity


def canonicalize_backend_summary(
    raw: Any,
    *,
    backend_type: str,
    worker_kind: str,
) -> Json:
    error_code = _contract_error_code(worker_kind)
    if not isinstance(raw, dict) or set(raw) != {
        "test_count",
        "top_scope_count",
    }:
        _violation(
            error_code,
            backend_type,
            None,
            "summary",
            "closed {test_count, top_scope_count} object",
            raw,
        )
    test_count = _strict_integer(
        raw["test_count"],
        "summary.test_count",
        error_code,
        backend_type,
        None,
    )
    if test_count < 0:
        _violation(
            error_code,
            backend_type,
            None,
            "summary.test_count",
            "non-negative integer",
            test_count,
        )
    top_scope_count = raw["top_scope_count"]
    if top_scope_count is not None:
        top_scope_count = _strict_integer(
            top_scope_count,
            "summary.top_scope_count",
            error_code,
            backend_type,
            None,
        )
        if top_scope_count < 0:
            _violation(
                error_code,
                backend_type,
                None,
                "summary.top_scope_count",
                "non-negative integer or null",
                top_scope_count,
            )
    return {
        "test_count": test_count,
        "top_scope_count": top_scope_count,
    }


def canonicalize_backend_tests(
    raw: Any,
    *,
    backend_type: str,
    worker_kind: str,
) -> List[Json]:
    error_code = _contract_error_code(worker_kind)
    if not isinstance(raw, list):
        _violation(
            error_code,
            backend_type,
            None,
            "tests",
            "list of closed {name} objects",
            raw,
        )
    rows: List[Json] = []
    seen = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != {"name"}:
            _violation(
                error_code,
                backend_type,
                index,
                "tests",
                "closed {name} object",
                item,
            )
        name = _required_nonempty_string(
            item,
            "name",
            error_code,
            backend_type,
            index,
            public_field="tests.name",
        )
        if name in seen:
            _violation(
                error_code,
                backend_type,
                index,
                "tests.name",
                "unique test name",
                name,
            )
        seen.add(name)
        rows.append({"name": name})
    return rows


def canonicalize_backend_scopes(
    raw: Any,
    *,
    backend_type: str,
    worker_kind: str,
) -> List[Json]:
    error_code = _contract_error_code(worker_kind)
    if not isinstance(raw, list):
        _violation(
            error_code,
            backend_type,
            None,
            "scopes",
            "list of canonical scope objects",
            raw,
        )
    allowed = {
        "name",
        "full_name",
        "parent",
        "depth",
        "type",
        "def_name",
        "evidence",
    }
    required = {"name", "full_name", "parent", "depth", "type"}
    rows: List[Json] = []
    seen = set()
    for index, item in enumerate(raw):
        if (
            not isinstance(item, dict)
            or not required.issubset(item)
            or set(item) - allowed
        ):
            _violation(
                error_code,
                backend_type,
                index,
                "scopes",
                "closed canonical scope object",
                item,
            )
        name = _required_nonempty_string(
            item,
            "name",
            error_code,
            backend_type,
            index,
            public_field="scopes.name",
        )
        full_name = _required_nonempty_string(
            item,
            "full_name",
            error_code,
            backend_type,
            index,
            public_field="scopes.full_name",
        )
        parent = _nullable_nonempty_string(
            item["parent"],
            "scopes.parent",
            error_code,
            backend_type,
            index,
        )
        depth = _strict_integer(
            item["depth"],
            "scopes.depth",
            error_code,
            backend_type,
            index,
        )
        expected_depth = full_name.count(".")
        if depth != expected_depth:
            _violation(
                error_code,
                backend_type,
                index,
                "scopes.depth",
                f"full_name hierarchy depth ({expected_depth})",
                depth,
            )
        expected_parent = (
            full_name.rsplit(".", 1)[0] if "." in full_name else None
        )
        if parent != expected_parent:
            _violation(
                error_code,
                backend_type,
                index,
                "scopes.parent",
                f"parent derived from full_name ({expected_parent!r})",
                parent,
            )
        expected_name = full_name.rsplit(".", 1)[-1]
        if name != expected_name:
            _violation(
                error_code,
                backend_type,
                index,
                "scopes.name",
                f"leaf name derived from full_name ({expected_name!r})",
                name,
            )
        if full_name in seen:
            _violation(
                error_code,
                backend_type,
                index,
                "scopes.full_name",
                "unique scope full_name",
                full_name,
            )
        seen.add(full_name)
        rows.append({
            "name": name,
            "full_name": full_name,
            "parent": parent,
            "depth": depth,
            "type": _required_nonempty_string(
                item,
                "type",
                error_code,
                backend_type,
                index,
                public_field="scopes.type",
            ),
            "def_name": _nullable_nonempty_string(
                item.get("def_name"),
                "scopes.def_name",
                error_code,
                backend_type,
                index,
            ),
            "evidence": _canonical_evidence(
                item.get("evidence"),
                provided="evidence" in item,
                error_code=error_code,
                backend_type=backend_type,
                row_index=index,
            ),
        })
    all_names = {row["full_name"] for row in rows}
    for index, row in enumerate(rows):
        if row["parent"] is not None and row["parent"] not in all_names:
            _violation(
                error_code,
                backend_type,
                index,
                "scopes.parent",
                "parent scope present in the same canonical scope set",
                row["parent"],
            )
    return rows


def coverage_row_kind(row: Json) -> RowKind:
    metric = row["metric"]
    typ = row["type"]
    if typ in SCORE_TYPES_BY_METRIC[metric]:
        return "score"
    if metric == "assert" and typ in ASSERT_COUNT_TYPES:
        return "assert_count"
    return "context"


def is_score_bearing_row(row: Json) -> bool:
    return coverage_row_kind(row) == "score"


def strict_coverage_pct(covered: int, coverable: int) -> float | None:
    if coverable == 0:
        return None
    return round(covered / coverable * 100.0, 4)


def _canonicalize_row(
    raw: Any,
    *,
    row_index: int,
    backend_type: str,
    error_code: str,
) -> Json:
    if not isinstance(raw, dict):
        _violation(
            error_code,
            backend_type,
            row_index,
            "row",
            "coverage row object",
            raw,
        )
    unknown = sorted(set(raw) - ALLOWED_FIELDS)
    if unknown:
        raise XcovError(
            error_code,
            "coverage backend returned unknown row fields",
            error_layer="backend",
            operation="items.canonicalize",
            backend_type=backend_type,
            row_index=row_index,
            field="row",
            expected="closed canonical coverage row",
            unknown_fields=unknown,
        )

    metric = _required_nonempty_string(
        raw,
        "metric",
        error_code,
        backend_type,
        row_index,
    )
    if metric not in METRICS:
        _violation(
            error_code,
            backend_type,
            row_index,
            "metric",
            f"one of {', '.join(METRICS)}",
            metric,
        )
    typ = _required_nonempty_string(
        raw,
        "type",
        error_code,
        backend_type,
        row_index,
    )
    kind = _classify_type(
        metric,
        typ,
        error_code,
        backend_type,
        row_index,
    )

    scope = _nullable_nonempty_string(
        raw.get("scope"),
        "scope",
        error_code,
        backend_type,
        row_index,
    )
    name = _required_nonempty_string(
        raw,
        "name",
        error_code,
        backend_type,
        row_index,
    )
    full_name = _required_nonempty_string(
        raw,
        "full_name",
        error_code,
        backend_type,
        row_index,
    )
    status = _canonical_status(
        raw.get("status"),
        error_code,
        backend_type,
        row_index,
    )
    evidence = _canonical_evidence(
        raw.get("evidence", None),
        provided="evidence" in raw,
        error_code=error_code,
        backend_type=backend_type,
        row_index=row_index,
    )
    covered, coverable, missing, pct = _canonical_score(
        raw,
        kind,
        error_code,
        backend_type,
        row_index,
    )
    count = _canonical_count(
        raw.get("count"),
        kind,
        error_code,
        backend_type,
        row_index,
    )
    if covered is not None:
        expected_status = (
            "covered"
            if coverable is not None and coverable > 0 and covered >= coverable
            else "not_covered"
        )
        opposite = "not_covered" if expected_status == "covered" else "covered"
        if expected_status not in status or opposite in status:
            _violation(
                error_code,
                backend_type,
                row_index,
                "status",
                f"status consistent with covered={covered}, coverable={coverable}",
                status,
            )

    row: Json = {
        "metric": metric,
        "type": typ,
        "scope": scope,
        "name": name,
        "full_name": full_name,
        "covered": covered,
        "coverable": coverable,
        "missing": missing,
        "count": count,
        "coverage_pct": pct,
        "status": status,
        "evidence": evidence,
    }
    _copy_optional_fields(
        raw,
        row,
        error_code,
        backend_type,
        row_index,
    )
    _validate_type_specific_fields(
        row,
        kind,
        error_code,
        backend_type,
        row_index,
    )
    return row


def _classify_type(
    metric: str,
    typ: str,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> RowKind:
    if typ in SCORE_TYPES_BY_METRIC[metric]:
        return "score"
    if metric == "assert" and typ in ASSERT_COUNT_TYPES:
        return "assert_count"
    if typ in CONTEXT_TYPES_BY_METRIC[metric]:
        return "context"

    known_metric = next(
        (
            candidate
            for candidate in METRICS
            if typ in SCORE_TYPES_BY_METRIC[candidate]
            or typ in CONTEXT_TYPES_BY_METRIC[candidate]
            or (candidate == "assert" and typ in ASSERT_COUNT_TYPES)
        ),
        None,
    )
    expected = (
        f"coverage type compatible with metric {metric}"
        if known_metric is not None
        else f"declared score, context, or assertion-count type for metric {metric}"
    )
    _violation(
        error_code,
        backend_type,
        row_index,
        "type",
        expected,
        typ,
    )
    raise AssertionError("unreachable")


def _canonical_score(
    raw: Json,
    kind: RowKind,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> tuple[int | None, int | None, int | None, float | None]:
    for field in ("covered", "coverable", "missing", "coverage_pct"):
        if field not in raw:
            _violation(
                error_code,
                backend_type,
                row_index,
                field,
                "required coverage score field",
                None,
                cause_type="MissingField",
            )
    covered = raw["covered"]
    coverable = raw["coverable"]
    if covered is None or coverable is None:
        if (
            kind == "score"
            or covered is not None
            or coverable is not None
            or raw["missing"] is not None
            or raw["coverage_pct"] is not None
        ):
            _violation(
                error_code,
                backend_type,
                row_index,
                "covered/coverable",
                (
                    "non-negative score for score-bearing row; otherwise all "
                    "score fields must be null when not applicable"
                ),
                [covered, coverable],
            )
        return None, None, None, None

    covered = _strict_integer(
        covered,
        "covered",
        error_code,
        backend_type,
        row_index,
    )
    coverable = _strict_integer(
        coverable,
        "coverable",
        error_code,
        backend_type,
        row_index,
    )
    if covered < 0 or coverable < 0:
        _violation(
            error_code,
            backend_type,
            row_index,
            "covered/coverable",
            "non-negative integers or canonical nulls",
            [covered, coverable],
        )
    if kind == "assert_count":
        _violation(
            error_code,
            backend_type,
            row_index,
            "covered/coverable",
            "null score fields for assertion count row",
            [covered, coverable],
        )
    if covered > coverable:
        _violation(
            error_code,
            backend_type,
            row_index,
            "covered",
            "covered <= coverable",
            covered,
        )
    missing = _strict_integer(
        raw["missing"],
        "missing",
        error_code,
        backend_type,
        row_index,
    )
    expected_missing = coverable - covered
    if missing != expected_missing:
        _violation(
            error_code,
            backend_type,
            row_index,
            "missing",
            f"coverable - covered ({expected_missing})",
            missing,
        )

    expected_pct = strict_coverage_pct(covered, coverable)
    pct = raw["coverage_pct"]
    if expected_pct is None:
        if pct is not None:
            _violation(
                error_code,
                backend_type,
                row_index,
                "coverage_pct",
                "null when coverable is zero",
                pct,
            )
        canonical_pct = None
    else:
        canonical_pct = _strict_number(
            pct,
            "coverage_pct",
            error_code,
            backend_type,
            row_index,
        )
        if canonical_pct < 0.0 or canonical_pct > 100.0:
            _violation(
                error_code,
                backend_type,
                row_index,
                "coverage_pct",
                "number in [0, 100]",
                pct,
            )
        if canonical_pct != expected_pct:
            _violation(
                error_code,
                backend_type,
                row_index,
                "coverage_pct",
                f"round(covered / coverable * 100, 4) ({expected_pct})",
                pct,
            )
    return covered, coverable, missing, canonical_pct


def _canonical_count(
    value: Any,
    kind: RowKind,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> int | None:
    if value is None:
        if kind == "assert_count":
            _violation(
                error_code,
                backend_type,
                row_index,
                "count",
                "non-negative assertion count",
                value,
            )
        return None
    count = _strict_integer(
        value,
        "count",
        error_code,
        backend_type,
        row_index,
    )
    if kind == "assert_count":
        if count < 0:
            _violation(
                error_code,
                backend_type,
                row_index,
                "count",
                "non-negative assertion count",
                count,
            )
        return count
    if count < 0:
        _violation(
            error_code,
            backend_type,
            row_index,
            "count",
            "non-negative count or canonical null",
            count,
        )
    return count


def _canonical_status(
    value: Any,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> List[str]:
    if not isinstance(value, list) or not value:
        _violation(
            error_code,
            backend_type,
            row_index,
            "status",
            "non-empty list of canonical status strings",
            value,
        )
    if any(not isinstance(item, str) or not item for item in value):
        _violation(
            error_code,
            backend_type,
            row_index,
            "status",
            "non-empty list of canonical status strings",
            value,
        )
    if len(set(value)) != len(value):
        _violation(
            error_code,
            backend_type,
            row_index,
            "status",
            "status list without duplicates",
            value,
        )
    unknown = sorted(set(value) - STATUS_VALUES)
    if unknown:
        raise XcovError(
            error_code,
            "coverage backend returned unknown status values",
            error_layer="backend",
            operation="items.canonicalize",
            backend_type=backend_type,
            row_index=row_index,
            field="status",
            expected="canonical coverage status values",
            unknown_status=unknown,
        )
    return list(value)


def _canonical_evidence(
    value: Any,
    *,
    provided: bool,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> Json:
    if not provided or value is None:
        return {"file": None, "line": None}
    if not isinstance(value, dict):
        _violation(
            error_code,
            backend_type,
            row_index,
            "evidence",
            "null or closed {file, line} object",
            value,
        )
    if set(value) != {"file", "line"}:
        _violation(
            error_code,
            backend_type,
            row_index,
            "evidence",
            "closed object containing exactly file and line",
            value,
        )
    file_name = _nullable_nonempty_string(
        value["file"],
        "evidence.file",
        error_code,
        backend_type,
        row_index,
    )
    line = value["line"]
    if line is not None:
        line = _strict_integer(
            line,
            "evidence.line",
            error_code,
            backend_type,
            row_index,
        )
        if line <= 0:
            _violation(
                error_code,
                backend_type,
                row_index,
                "evidence.line",
                "positive integer or null",
                line,
            )
    if line is not None and file_name is None:
        _violation(
            error_code,
            backend_type,
            row_index,
            "evidence",
            "file must be present when line is present",
            value,
        )
    return {"file": file_name, "line": line}


def _copy_optional_fields(
    raw: Json,
    row: Json,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> None:
    for field in OPTIONAL_STRING_FIELDS:
        if field in raw:
            row[field] = _nullable_nonempty_string(
                raw[field],
                field,
                error_code,
                backend_type,
                row_index,
            )
    if "toggle_is_port" in raw:
        value = raw["toggle_is_port"]
        if value is not None and not isinstance(value, bool):
            _violation(
                error_code,
                backend_type,
                row_index,
                "toggle_is_port",
                "boolean or null",
                value,
            )
        row["toggle_is_port"] = value
    for field in ("severity", "category"):
        if field in raw:
            value = raw[field]
            valid = (
                value is None
                or (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                )
                or (isinstance(value, str) and bool(value))
            )
            if not valid:
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    field,
                    "non-negative integer, non-empty string, or null",
                    value,
                )
            row[field] = value
    if "value" in raw:
        value = raw["value"]
        if (
            value is None
            or isinstance(value, (dict, list))
            or not isinstance(value, (str, int, float, bool))
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            _violation(
                error_code,
                backend_type,
                row_index,
                "value",
                "non-null finite JSON scalar",
                value,
            )
        row["value"] = value
    if "evidence_source" in raw:
        row["evidence_source"] = _canonical_evidence_source(
            raw["evidence_source"],
            error_code,
            backend_type,
            row_index,
        )
        if row["evidence"]["file"] is None:
            _violation(
                error_code,
                backend_type,
                row_index,
                "evidence_source",
                "inherited source paired with concrete canonical evidence",
                raw["evidence_source"],
            )
    if "branch_mask" in raw:
        row["branch_mask"] = _canonical_branch_mask(
            raw["branch_mask"],
            error_code,
            backend_type,
            row_index,
        )


def _validate_type_specific_fields(
    row: Json,
    kind: RowKind,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> None:
    metric = row["metric"]
    typ = row["type"]
    if metric == "assert":
        expected_kind = {
            "npiCovAssert": "assertion",
            "npiCovCoverProperty": "cover_property",
            "npiCovCoverSequence": "cover_sequence",
        }
        if kind == "score":
            _require_equal_field(
                row,
                "assert_kind",
                expected_kind[typ],
                error_code,
                backend_type,
                row_index,
            )
            _require_equal_field(
                row,
                "assert_object",
                row["full_name"],
                error_code,
                backend_type,
                row_index,
            )
        elif kind == "assert_count":
            assert_object = row.get("assert_object")
            if not isinstance(assert_object, str) or not assert_object:
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    "assert_object",
                    "non-empty parent assertion identity",
                    assert_object,
                )
            expected_bin_kind = {
                "npiCovFirstmatchBin": "cover_sequence",
            }.get(typ)
            actual_kind = row.get("assert_kind")
            if expected_bin_kind is not None and actual_kind != expected_bin_kind:
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    "assert_kind",
                    expected_bin_kind,
                    actual_kind,
                )
            if actual_kind not in {
                "assertion",
                "cover_property",
                "cover_sequence",
            }:
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    "assert_kind",
                    "canonical assertion kind",
                    actual_kind,
                )
    elif metric == "functional":
        _require_nonempty_field(
            row,
            "covergroup",
            error_code,
            backend_type,
            row_index,
        )
        if typ == "npiCovCoverpoint":
            _require_nonempty_field(
                row,
                "coverpoint",
                error_code,
                backend_type,
                row_index,
            )
        elif typ == "npiCovCross":
            _require_nonempty_field(
                row,
                "cross",
                error_code,
                backend_type,
                row_index,
            )
        elif typ == "npiCovCoverBin":
            _require_nonempty_field(
                row,
                "bin",
                error_code,
                backend_type,
                row_index,
            )
            parents = [
                field
                for field in ("coverpoint", "cross")
                if isinstance(row.get(field), str) and row[field]
            ]
            if len(parents) != 1:
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    "coverpoint/cross",
                    "exactly one functional-bin parent identity",
                    parents,
                )
    elif kind == "score" and metric == "toggle":
        for field in ("toggle_signal", "toggle_bit", "toggle_transition"):
            _require_nonempty_field(
                row,
                field,
                error_code,
                backend_type,
                row_index,
            )
    elif kind == "score" and metric == "branch":
        for field in ("branch", "branch_bin"):
            _require_nonempty_field(
                row,
                field,
                error_code,
                backend_type,
                row_index,
            )
    elif kind == "score" and metric == "condition":
        for field in ("condition", "condition_bin"):
            _require_nonempty_field(
                row,
                field,
                error_code,
                backend_type,
                row_index,
            )


def _require_nonempty_field(
    row: Json,
    field: str,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> None:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        _violation(
            error_code,
            backend_type,
            row_index,
            field,
            "required non-empty string for metric/type",
            value,
        )


def _require_equal_field(
    row: Json,
    field: str,
    expected: str,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> None:
    value = row.get(field)
    if value != expected:
        _violation(
            error_code,
            backend_type,
            row_index,
            field,
            expected,
            value,
        )


def _canonical_evidence_source(
    value: Any,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> Json:
    required = {"inherited", "type", "name", "full_name"}
    if not isinstance(value, dict) or set(value) != required:
        _violation(
            error_code,
            backend_type,
            row_index,
            "evidence_source",
            "closed inherited/type/name/full_name object",
            value,
        )
    if value["inherited"] is not True:
        _violation(
            error_code,
            backend_type,
            row_index,
            "evidence_source.inherited",
            "true",
            value["inherited"],
        )
    return {
        "inherited": True,
        "type": _required_nonempty_string(
            value,
            "type",
            error_code,
            backend_type,
            row_index,
            public_field="evidence_source.type",
        ),
        "name": _required_nonempty_string(
            value,
            "name",
            error_code,
            backend_type,
            row_index,
            public_field="evidence_source.name",
        ),
        "full_name": _required_nonempty_string(
            value,
            "full_name",
            error_code,
            backend_type,
            row_index,
            public_field="evidence_source.full_name",
        ),
    }


def _canonical_branch_mask(
    value: Any,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> Json:
    if not isinstance(value, dict):
        _violation(
            error_code,
            backend_type,
            row_index,
            "branch_mask",
            "closed branch-mask object",
            value,
        )
    allowed = {
        "encoding",
        "branch_arm_index",
        "one_positions",
        "dontcare_bits",
        "active_bits",
    }
    if set(value) - allowed:
        _violation(
            error_code,
            backend_type,
            row_index,
            "branch_mask",
            "closed branch-mask object",
            value,
        )
    encoding = value.get("encoding")
    required_by_encoding = {
        "one_hot": {"encoding", "branch_arm_index"},
        "multi_bit": {"encoding", "one_positions"},
        "path": {"encoding", "dontcare_bits", "active_bits"},
    }
    if encoding not in required_by_encoding or set(value) != required_by_encoding[encoding]:
        _violation(
            error_code,
            backend_type,
            row_index,
            "branch_mask",
            "encoding-specific canonical branch-mask fields",
            value,
        )
    out: Json = {"encoding": encoding}
    for field in required_by_encoding[encoding] - {"encoding"}:
        raw_field = value[field]
        if field == "one_positions":
            if (
                not isinstance(raw_field, list)
                or not raw_field
                or any(
                    not isinstance(item, int)
                    or isinstance(item, bool)
                    or item < 0
                    for item in raw_field
                )
                or len(set(raw_field)) != len(raw_field)
            ):
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    f"branch_mask.{field}",
                    "non-empty unique list of non-negative integers",
                    raw_field,
                )
            out[field] = list(raw_field)
        else:
            integer = _strict_integer(
                raw_field,
                f"branch_mask.{field}",
                error_code,
                backend_type,
                row_index,
            )
            if integer < 0:
                _violation(
                    error_code,
                    backend_type,
                    row_index,
                    f"branch_mask.{field}",
                    "non-negative integer",
                    raw_field,
                )
            out[field] = integer
    return out


def _required_nonempty_string(
    mapping: Json,
    key: str,
    error_code: str,
    backend_type: str,
    row_index: int,
    *,
    public_field: str | None = None,
) -> str:
    if key not in mapping:
        _violation(
            error_code,
            backend_type,
            row_index,
            public_field or key,
            "required non-empty string",
            None,
            cause_type="MissingField",
        )
    value = mapping[key]
    if not isinstance(value, str) or not value:
        _violation(
            error_code,
            backend_type,
            row_index,
            public_field or key,
            "non-empty string",
            value,
        )
    return value


def _nullable_nonempty_string(
    value: Any,
    field: str,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        _violation(
            error_code,
            backend_type,
            row_index,
            field,
            "non-empty string or null",
            value,
        )
    return value


def _strict_integer(
    value: Any,
    field: str,
    error_code: str,
    backend_type: str,
    row_index: int | None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _violation(
            error_code,
            backend_type,
            row_index,
            field,
            "integer",
            value,
        )
    return value


def _strict_number(
    value: Any,
    field: str,
    error_code: str,
    backend_type: str,
    row_index: int,
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        _violation(
            error_code,
            backend_type,
            row_index,
            field,
            "finite number",
            value,
        )
    return float(value)


def _violation(
    error_code: str,
    backend_type: str,
    row_index: int | None,
    field: str,
    expected: str,
    actual: Any,
    *,
    cause_type: str = "InvalidCoverageFact",
) -> None:
    operation = "items.canonicalize"
    if field == "summary" or field.startswith("summary."):
        operation = "summary.canonicalize"
    elif field == "tests" or field.startswith("tests."):
        operation = "tests.canonicalize"
    elif field == "scopes" or field.startswith("scopes."):
        operation = "scopes.canonicalize"
    detail: Json = {
        "error_layer": "backend",
        "operation": operation,
        "backend_type": backend_type,
        "field": field,
        "expected": expected,
        "cause_type": cause_type,
        "actual_type": type(actual).__name__,
    }
    if row_index is not None:
        detail["row_index"] = row_index
    raise XcovError(
        error_code,
        "coverage backend returned a value outside the canonical fact contract",
        **detail,
    )


def _contract_error_code(worker_kind: str) -> str:
    return (
        "NPI_CONTRACT_VIOLATION"
        if worker_kind.startswith("npi")
        else "BACKEND_CONTRACT_VIOLATION"
    )
