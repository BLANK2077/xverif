from __future__ import annotations

import os
from pathlib import Path
import hashlib
import inspect
import json
import secrets
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional

from .coverage_contract import (
    ASSERT_COUNT_TYPES,
    METRICS as CONTRACT_METRICS,
    SCORE_TYPES_BY_METRIC,
    canonicalize_backend_scopes,
    canonicalize_backend_summary,
    canonicalize_backend_tests,
    canonicalize_coverage_items,
    coverage_identity_for_row,
    coverage_ref_for_row,
    is_score_bearing_row,
)
from .eda import import_pynpi
from .errors import XcovError
from .logging import log_lifecycle_event
from .urg_summary import UrgSummaryIndex
from .urg_cache import load_cached_urg_summary
from .urg_runner import UrgRunner

Json = Dict[str, Any]

METRICS = list(CONTRACT_METRICS)
METRIC_METHODS = {
    "line": "line_metric_handle",
    "toggle": "toggle_metric_handle",
    "branch": "branch_metric_handle",
    "condition": "condition_metric_handle",
    "fsm": "fsm_metric_handle",
    "assert": "assert_metric_handle",
    "functional": "testbench_metric_handle",
    "power": "power_metric_handle",
}


def _toggle_gap_object(value: str) -> tuple[str, Optional[set[int]]]:
    match = __import__("re").match(r"^(.*)\[(\d+)(?::(\d+))?\]$", value)
    if not match:
        return value, None
    base = match.group(1)
    left = int(match.group(2))
    right = int(match.group(3)) if match.group(3) is not None else left
    low, high = sorted((left, right))
    return base, set(range(low, high + 1))


def _coverage_ref_from_path(
    namespace: str,
    metric: str,
    scope: str,
    typ: str,
    traversal_path: tuple[int, ...],
) -> str:
    payload = json.dumps(
        {
            "namespace": namespace,
            "metric": metric,
            "scope": scope,
            "type": typ,
            "traversal_path": list(traversal_path),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "xcovref.v1:" + hashlib.sha256(payload).hexdigest()


def _locator_key(locator: Json) -> str:
    return json.dumps(locator, sort_keys=True, separators=(",", ":"))


def _semantic_gap_key(metric: str, row: Json) -> tuple[Any, ...]:
    if metric == "assert":
        full_name = str(row.get("full_name") or "")
        full_name = __import__("re").sub(r"\.assert\.\d+\.", ".", full_name)
        return (
            str(row.get("kind") or row.get("type") or ""),
            full_name,
        )
    bin_name = str(row.get("bin") or row.get("name") or "")
    bin_name = bin_name.replace("] [", "|")
    return (
        str(row.get("scope") or ""),
        str(row.get("covergroup") or ""),
        str(row.get("coverpoint") or ""),
        str(row.get("cross") or ""),
        bin_name,
    )


def _load_urg_summary(
    vdb: str,
    *,
    cache_root: str | None = None,
    el_path: str | None = None,
    run_manifest_digest: str | None = None,
) -> UrgSummaryIndex:
    index, _ = load_cached_urg_summary(
        vdb,
        cache_root=cache_root,
        el_path=el_path,
        run_manifest_digest=run_manifest_digest,
    )
    return index


def _namespaced_coverage_ref(namespace: str, row: Json) -> str:
    payload = json.dumps(
        {
            "namespace": namespace,
            "identity": coverage_identity_for_row(row),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "xcovref.v1:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class NpiCallFailure:
    operation: str
    object_type: str
    method: str
    expected_signature: str
    cause_type: str
    cause_message: str


class NpiContractViolation(XcovError):
    def __init__(self, failure: NpiCallFailure) -> None:
        self.failure = failure
        super().__init__(
            "NPI_CONTRACT_VIOLATION",
            (
                f"NPI operation {failure.operation} violated "
                f"{failure.expected_signature}"
            ),
            error_layer="backend",
            operation=failure.operation,
            object_type=failure.object_type,
            method=failure.method,
            expected_signature=failure.expected_signature,
            cause_type=failure.cause_type,
            cause_message=failure.cause_message,
        )


@dataclass(frozen=True)
class NpiMethodContract:
    method: str
    positional_args: tuple[str, ...]
    result_kind: Literal["value", "list"]

    @property
    def signature(self) -> str:
        return f"{self.method}({', '.join(self.positional_args)})"


def _contract(
    method: str,
    *positional_args: str,
    result_kind: Literal["value", "list"] = "value",
) -> NpiMethodContract:
    return NpiMethodContract(method, tuple(positional_args), result_kind)


NPI_METHOD_CONTRACTS: Dict[str, NpiMethodContract] = {
    "npisys.init": _contract("init", "argv"),
    "npisys.end": _contract("end"),
    "cov.open": _contract("open", "vdb", "config_opt"),
    "cov.merge_test": _contract("merge_test", "left_test", "right_test"),
    "cov.release_handle": _contract("release_handle", "handle"),
    "database.close": _contract("close"),
    "database.test_handles": _contract("test_handles", result_kind="list"),
    "database.instance_handles": _contract(
        "instance_handles", result_kind="list"
    ),
    "test.name": _contract("name"),
    "test.testbench_metric_handle": _contract("testbench_metric_handle"),
    "test.load_exclude_file": _contract("load_exclude_file", "path"),
    "test.save_exclude_file": _contract("save_exclude_file", "path", "mode"),
    "test.unload_exclusion": _contract("unload_exclusion"),
    "instance.name": _contract("name"),
    "instance.full_name": _contract("full_name"),
    "instance.type": _contract("type"),
    "instance.def_name": _contract("def_name"),
    "instance.file_name": _contract("file_name"),
    "instance.line_no": _contract("line_no"),
    "instance.instance_handles": _contract(
        "instance_handles", result_kind="list"
    ),
    "coverage.child_handles": _contract(
        "child_handles", result_kind="list"
    ),
    "coverage.condition_term_handles": _contract(
        "condition_term_handles", result_kind="list"
    ),
    "coverage.branch_term_handles": _contract(
        "branch_term_handles", result_kind="list"
    ),
    "coverage.name": _contract("name"),
    "coverage.full_name": _contract("full_name"),
    "coverage.type": _contract("type"),
    "coverage.file_name": _contract("file_name"),
    "coverage.line_no": _contract("line_no", "test"),
    "coverage.covered": _contract("covered", "test"),
    "coverage.coverable": _contract("coverable", "test"),
    "coverage.count": _contract("count", "test"),
    "coverage.value": _contract("value", "test"),
    "coverage.toggle_type": _contract("toggle_type", "test"),
    "coverage.is_port": _contract("is_port", "test"),
    "coverage.severity": _contract("severity", "test"),
    "coverage.category": _contract("category", "test"),
    "coverage.set_status_excluded_at_report_time": _contract(
        "set_status_excluded_at_report_time",
        "test",
        "value",
    ),
}


def _cov_open_contract(open_fn: Callable[..., Any]) -> NpiMethodContract:
    try:
        signature = inspect.signature(open_fn)
    except (TypeError, ValueError) as exc:
        raise XcovError(
            "NPI_CONTRACT_VIOLATION",
            "cannot inspect pynpi.cov.open signature",
            operation="cov.open",
            cause_type=type(exc).__name__,
            cause_message=str(exc),
        ) from exc
    parameters = list(signature.parameters.values())
    positional = [
        item for item in parameters
        if item.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(item.kind == inspect.Parameter.VAR_POSITIONAL for item in parameters)
    required = [item for item in positional if item.default is inspect.Parameter.empty]
    if has_varargs or len(required) != 1 or len(positional) not in (1, 2):
        raise XcovError(
            "NPI_CONTRACT_VIOLATION",
            "unsupported pynpi.cov.open signature",
            operation="cov.open",
            actual_signature=str(signature),
            supported_signatures=["open(vdb)", "open(vdb, config_opt=0)"],
        )
    return _contract("open", "vdb", *(() if len(positional) == 1 else ("config_opt",)))
for _metric_method in METRIC_METHODS.values():
    NPI_METHOD_CONTRACTS[f"instance.{_metric_method}"] = _contract(
        _metric_method
    )
for _status_method in (
    "has_status_excluded",
    "has_status_partially_excluded",
    "has_status_excluded_at_compile_time",
    "has_status_excluded_at_report_time",
    "has_status_unreachable",
    "has_status_illegal",
    "has_status_proven",
    "has_status_attempted",
    "has_status_partially_attempted",
):
    NPI_METHOD_CONTRACTS[f"coverage.{_status_method}"] = _contract(
        _status_method,
        "test",
    )


class NpiApiBinding:
    """Single-signature Python NPI invocation boundary.

    Each operation resolves one declared method and calls it exactly once.
    Missing methods, signature mismatches, call failures, and invalid traversal
    results become a typed public backend error; no alternate arity is tried.
    """

    def __init__(self, cov: Any, npisys: Any) -> None:
        # Freeze the supported operation/signature set for this backend
        # lifetime. Runtime calls never negotiate or rewrite contracts.
        self._contracts = dict(NPI_METHOD_CONTRACTS)
        self._module_objects = {"cov": cov, "npisys": npisys}
        self._module_methods: Dict[str, Callable[..., Any]] = {}
        for operation in (
            "npisys.init",
            "npisys.end",
            "cov.open",
            "cov.merge_test",
            "cov.release_handle",
        ):
            owner = operation.split(".", 1)[0]
            self._module_methods[operation] = self._bind(
                operation,
                self._module_objects[owner],
            )

    def module_call(self, operation: str, *args: Any) -> Any:
        return self._invoke(
            operation,
            self._module_objects[operation.split(".", 1)[0]],
            self._module_methods[operation],
            args,
        )

    def call(self, operation: str, obj: Any, *args: Any) -> Any:
        return self._invoke(
            operation,
            obj,
            self._bind(operation, obj),
            args,
        )

    def expect(
        self,
        operation: str,
        obj: Any,
        value: Any,
        *,
        expected: str,
        predicate: Callable[[Any], bool],
    ) -> Any:
        if predicate(value):
            return value
        raise self._violation(
            operation,
            obj,
            "NpiResultTypeError",
            f"expected {expected}, got {type(value).__name__}",
        )

    def _bind(self, operation: str, obj: Any) -> Callable[..., Any]:
        contract = self._contract(operation)
        try:
            method = getattr(obj, contract.method)
        except Exception as exc:
            raise self._violation(
                operation,
                obj,
                type(exc).__name__,
                str(exc),
            ) from exc
        if not callable(method):
            raise self._violation(
                operation,
                obj,
                "NpiMethodNotCallable",
                f"{contract.method} is not callable",
            )
        return method

    def _invoke(
        self,
        operation: str,
        obj: Any,
        method: Callable[..., Any],
        args: tuple[Any, ...],
    ) -> Any:
        contract = self._contract(operation)
        if len(args) != len(contract.positional_args):
            raise RuntimeError(
                f"internal NPI binding error for {operation}: "
                f"expected {len(contract.positional_args)} args, got {len(args)}"
            )
        try:
            value = method(*args)
            if contract.result_kind == "list":
                if value is None:
                    raise TypeError("traversal returned None instead of an iterable")
                if isinstance(value, (str, bytes, bytearray, dict)):
                    raise TypeError(
                        "traversal returned a scalar or mapping instead of "
                        "an iterable of handles"
                    )
                return list(value)
            return value
        except NpiContractViolation:
            raise
        except Exception as exc:
            raise self._violation(
                operation,
                obj,
                type(exc).__name__,
                str(exc),
            ) from exc

    def _contract(self, operation: str) -> NpiMethodContract:
        try:
            return self._contracts[operation]
        except KeyError as exc:
            raise RuntimeError(
                f"undeclared NPI operation: {operation}"
            ) from exc

    def _violation(
        self,
        operation: str,
        obj: Any,
        cause_type: str,
        cause_message: str,
    ) -> NpiContractViolation:
        contract = self._contract(operation)
        return NpiContractViolation(
            NpiCallFailure(
                operation=operation,
                object_type=type(obj).__name__,
                method=contract.method,
                expected_signature=contract.signature,
                cause_type=cause_type,
                cause_message=cause_message,
            )
        )


def _missing(covered: int, coverable: int) -> int:
    return coverable - covered


def _raw_coverage_pct(covered: int, coverable: int) -> float | None:
    """Project typed NPI integers; the canonical boundary validates semantics."""

    if coverable <= 0:
        return None
    return round(covered / coverable * 100.0, 4)


def _npi_score_payload(
    metric: str,
    typ: str,
    covered: int,
    coverable: int,
    count: int,
) -> Json:
    score_type = typ in SCORE_TYPES_BY_METRIC.get(metric, ())
    assert_count_type = metric == "assert" and typ in ASSERT_COUNT_TYPES
    if not score_type and covered == -1 and coverable == -1:
        canonical_covered: int | None = None
        canonical_coverable: int | None = None
        canonical_missing: int | None = None
        canonical_pct: float | None = None
    else:
        canonical_covered = covered
        canonical_coverable = coverable
        canonical_missing = _missing(covered, coverable)
        canonical_pct = _raw_coverage_pct(covered, coverable)
    canonical_count = (
        None
        if count == -1 and not assert_count_type
        else count
    )
    return {
        "covered": canonical_covered,
        "coverable": canonical_coverable,
        "missing": canonical_missing,
        "count": canonical_count,
        "coverage_pct": canonical_pct,
    }


class CoverageBackend:
    worker_kind = "custom"

    def close(self) -> None:
        pass

    def tests(self) -> List[Json]:
        raise NotImplementedError

    def summary(self) -> Json:
        raise NotImplementedError

    def top_scopes(self) -> List[Json]:
        raise NotImplementedError

    def scopes(self) -> List[Json]:
        raise NotImplementedError

    def scope_metrics(self) -> Dict[str, Json]:
        raise NotImplementedError

    def scope_functional_from_urg(self) -> List[Json]:
        raise NotImplementedError

    def scope_assert_from_urg(self) -> List[Json]:
        raise NotImplementedError

    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
        raise NotImplementedError

    def gap_items(self, metric: str, scope: Optional[str] = None,
                  test: str = "merged") -> List[Json]:
        """Internal export rows including direct exclusion locators."""
        raise NotImplementedError

    def load_exclusions(self, paths: List[str], test: str = "merged") -> List[Json]:
        raise NotImplementedError

    def set_exclusion(
        self,
        coverage_ref: str,
        excluded: bool,
        test: str = "merged",
    ) -> Json:
        raise NotImplementedError

    def save_exclusions(self, path: str, test: str = "merged") -> None:
        raise NotImplementedError

    def unload_exclusions(self, test: str = "merged") -> None:
        raise NotImplementedError

    def resolve_gap_payload(self, payload: Json, test: str = "merged") -> Json:
        """Resolve an URG semantic gap payload into transient exclusion targets."""
        raise NotImplementedError

    def resolve_container_records(self, records: List[Json], test: str = "merged") -> List[Json]:
        """Resolve exact instance/functional container selectors into NPI locators."""
        raise NotImplementedError


def _canonical_scope_metric(scope: str, metric: Any, values: Any) -> Json:
    operation = "scope_metrics.canonicalize"
    if metric not in METRICS:
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope_metrics contains an unsupported metric",
            operation=operation,
            field="metric",
            scope=scope,
            metric=metric,
        )
    if not isinstance(values, dict):
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope metric must be an object",
            operation=operation,
            field="metric_values",
            scope=scope,
            metric=metric,
        )
    required = {"covered", "coverable", "missing", "pct"}
    allowed = {*required, "excluded"}
    unknown = set(values) - allowed
    if unknown:
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope metric contains unknown fields",
            operation=operation,
            field="metric_values",
            scope=scope,
            metric=metric,
            unknown_fields=sorted(unknown),
        )
    if not required.issubset(values):
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope metric is missing required score fields",
            operation=operation,
            field="metric_values",
            scope=scope,
            metric=metric,
            missing=sorted(required - set(values)),
        )
    covered = values["covered"]
    coverable = values["coverable"]
    missing = values["missing"]
    pct = values["pct"]
    for field_name, value in (
        ("covered", covered),
        ("coverable", coverable),
        ("missing", missing),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise XcovError(
                "BACKEND_CONTRACT_VIOLATION",
                "scope metric count must be a non-negative integer",
                operation=operation,
                field=field_name,
                scope=scope,
                metric=metric,
            )
    if covered > coverable or missing != coverable - covered:
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope metric counts are inconsistent",
            operation=operation,
            field="covered/coverable/missing",
            scope=scope,
            metric=metric,
        )
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not 0 <= pct <= 100:
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope metric pct must be a finite number in 0..100",
            operation=operation,
            field="pct",
            scope=scope,
            metric=metric,
        )
    expected = round(100.0 * covered / coverable, 4) if coverable else 0.0
    if metric != "functional" and abs(float(pct) - expected) > 0.01:
        raise XcovError(
            "BACKEND_CONTRACT_VIOLATION",
            "scope metric pct disagrees with covered/coverable",
            operation=operation,
            field="pct",
            scope=scope,
            metric=metric,
        )
    out = {
        "covered": covered,
        "coverable": coverable,
        "missing": missing,
        "pct": float(pct),
    }
    if "excluded" in values:
        excluded = values["excluded"]
        if isinstance(excluded, bool) or not isinstance(excluded, int) or excluded < 0:
            raise XcovError(
                "BACKEND_CONTRACT_VIOLATION",
                "scope metric excluded count must be a non-negative integer",
                operation=operation,
                field="excluded",
                scope=scope,
                metric=metric,
            )
        out["excluded"] = excluded
    return out


class CanonicalCoverageBackend(CoverageBackend):
    """Mandatory backend-to-action contract boundary.

    SessionManager installs this wrapper around every backend returned by its
    factory.  Therefore NPI, the deterministic fake, and injected/custom
    backends all pass through the same metric/type-aware row contract before an
    action can observe any coverage item.
    """

    def __init__(self, delegate: CoverageBackend) -> None:
        self._delegate = delegate
        self.worker_kind = delegate.worker_kind
        self._backend_type = type(delegate).__name__

    def close(self) -> None:
        self._delegate.close()

    @property
    def cache_info(self) -> Json | None:
        value = getattr(self._delegate, "cache_info", None)
        return dict(value) if isinstance(value, dict) else None

    @property
    def npi_initialized(self) -> bool:
        return bool(getattr(self._delegate, "npi_initialized", False))

    def tests(self) -> List[Json]:
        return canonicalize_backend_tests(
            self._delegate.tests(),
            backend_type=self._backend_type,
            worker_kind=self.worker_kind,
        )

    def summary(self) -> Json:
        return canonicalize_backend_summary(
            self._delegate.summary(),
            backend_type=self._backend_type,
            worker_kind=self.worker_kind,
        )

    def top_scopes(self) -> List[Json]:
        return [
            scope
            for scope in self.scopes()
            if scope["depth"] == 0
        ]

    def scopes(self) -> List[Json]:
        return canonicalize_backend_scopes(
            self._delegate.scopes(),
            backend_type=self._backend_type,
            worker_kind=self.worker_kind,
        )

    def scope_metrics(self) -> Dict[str, Json]:
        raw = self._delegate.scope_metrics()
        if not isinstance(raw, dict):
            raise XcovError(
                "BACKEND_CONTRACT_VIOLATION",
                "scope_metrics must return an object",
                operation="scope_metrics.canonicalize",
                field="scope_metrics",
            )
        out: Dict[str, Json] = {}
        for scope, metrics in raw.items():
            if not isinstance(scope, str) or not scope or not isinstance(metrics, dict):
                raise XcovError(
                    "BACKEND_CONTRACT_VIOLATION",
                    "scope_metrics contains an invalid scope entry",
                    operation="scope_metrics.canonicalize",
                    field="scope",
                )
            canonical_metrics: Json = {}
            for metric, values in metrics.items():
                canonical_metrics[metric] = _canonical_scope_metric(
                    scope,
                    metric,
                    values,
                )
            out[scope] = canonical_metrics
        return out

    def scope_functional_from_urg(self) -> List[Json]:
        return self._delegate.scope_functional_from_urg()

    def scope_assert_from_urg(self) -> List[Json]:
        return self._delegate.scope_assert_from_urg()

    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
        raw_items = self._delegate.items(
            metrics=metrics,
            scope=scope,
            test=test,
            functional_only=functional_only,
        )
        return canonicalize_coverage_items(
            raw_items,
            backend_type=self._backend_type,
            worker_kind=self.worker_kind,
        )

    def gap_items(self, metric: str, scope: Optional[str] = None,
                  test: str = "merged") -> List[Json]:
        return self._delegate.gap_items(metric, scope=scope, test=test)

    def load_exclusions(self, paths: List[str], test: str = "merged") -> List[Json]:
        return self._delegate.load_exclusions(paths, test=test)

    def set_exclusion(
        self,
        coverage_ref: str,
        excluded: bool,
        test: str = "merged",
    ) -> Json:
        return self._delegate.set_exclusion(
            coverage_ref,
            excluded,
            test=test,
        )

    @property
    def vdb(self) -> str:
        return self._delegate.vdb

    def attach_gap_locators(self, payload: Json, test: str = "merged") -> Json:
        return self._delegate.attach_gap_locators(payload, test=test)

    def set_exclusion_locator(self, locator: Json, excluded: bool = True,
                              test: str = "merged") -> Json:
        return self._delegate.set_exclusion_locator(locator, excluded, test=test)

    def save_exclusions(self, path: str, test: str = "merged") -> None:
        self._delegate.save_exclusions(path, test=test)

    def unload_exclusions(self, test: str = "merged") -> None:
        self._delegate.unload_exclusions(test=test)

    def resolve_gap_payload(self, payload: Json, test: str = "merged") -> Json:
        return self._delegate.resolve_gap_payload(payload, test=test)

    def resolve_container_records(self, records: List[Json], test: str = "merged") -> List[Json]:
        return self._delegate.resolve_container_records(records, test=test)

    def set_summary_exclusion(self, el_path: str | None) -> None:
        setter = getattr(self._delegate, "set_summary_exclusion", None)
        if setter is not None:
            setter(el_path)

    def invalidate_summary(self) -> None:
        invalidator = getattr(self._delegate, "invalidate_summary", None)
        if invalidator is not None:
            invalidator()

    def _npi_items(self, wanted_metrics=None):
        return self._delegate._npi_items(wanted_metrics=wanted_metrics)


# ── Selector resolution constants ──

_VALID_METRICS = {"line", "toggle", "branch", "condition", "fsm", "assert", "functional"}

_SELECTOR_FIELDS: dict[str, frozenset[str]] = {
    "line": frozenset({"metric", "scope", "file", "line"}),
    "toggle": frozenset({"metric", "scope", "signal", "transition"}),
    "branch": frozenset({"metric", "scope", "branch", "arm"}),
    "condition": frozenset({"metric", "scope", "condition", "term"}),
    "fsm": frozenset({"metric", "scope", "fsm", "transition"}),
    "assert": frozenset({"metric", "scope", "name"}),
    "functional": frozenset({"metric", "scope", "covergroup", "coverpoint", "bin"}),
}

_SELECTOR_EXAMPLES: dict[str, list[str]] = {
    "line": [
        '{"metric":"line","scope":"top.u_dut","file":"ctrl.sv","line":42}',
    ],
    "toggle": [
        '{"metric":"toggle","scope":"top.u_dut","signal":"clk","transition":"0->1"}',
        '{"metric":"toggle","scope":"top.u_dut","signal":"rst_n","transition":"1->0"}',
    ],
    "branch": [
        '{"metric":"branch","scope":"top.u_dut","branch":"case (state)","arm":"-3-"}',
        '{"metric":"branch","scope":"top.u_dut","branch":"if (enable)","arm":"else"}',
    ],
    "condition": [
        '{"metric":"condition","scope":"top.u_dut","condition":"(en && (sel == 2\'b1))","term":"-2-"}',
    ],
    "fsm": [
        '{"metric":"fsm","scope":"top.u_dut","fsm":"state","transition":"IDLE->RUN"}',
    ],
    "assert": [
        '{"metric":"assert","scope":"top.u_dut","name":"a_no_unknown"}',
    ],
    "functional": [
        '{"metric":"functional","scope":"top","covergroup":"top::behavior_cg","coverpoint":"sel_cp","bin":"other"}',
    ],
}

_SELECTOR_EXPORT_HINT: dict[str, str] = {
    "line": "通过 export.code_coverage action 导出 line JSON/XOUT 查看准确的 scope、file、line。",
    "toggle": (
        "通过 export.code_coverage action 导出 toggle JSON/XOUT 查看准确的 signal 名和缺失边沿。"
    ),
    "branch": (
        "通过 export.code_coverage action 导出 branch JSON/XOUT 查看准确的表达式、URG vector 和 arm。"
    ),
    "condition": (
        "通过 export.code_coverage action 导出 condition JSON/XOUT 查看准确的表达式和 term vector。"
    ),
    "fsm": (
        "通过 export.code_coverage action 导出 FSM JSON/XOUT 查看准确的状态名和转换。"
    ),
    "assert": (
        "通过 export.assert action 导出 asserts.txt 查看准确的 assertion 名。"
    ),
    "functional": (
        "通过 export.functional_coverage action 导出 grpinfo.txt 查看准确的 covergroup、coverpoint、bin 名称。"
        "URG grpinfo: 直接使用 uncovered bin 名称（如 'other', 'zero' 等）"
    ),
}


def _selector_note(metric: str) -> str:
    """生成 selector 使用说明 note。"""
    fields = _SELECTOR_FIELDS.get(metric, frozenset())
    field_list = ", ".join(sorted(fields))
    examples = _SELECTOR_EXAMPLES.get(metric, [])
    hint = _SELECTOR_EXPORT_HINT.get(metric, "")
    lines = [f"{metric} selector 需要: {field_list}。", "示例:"]
    for ex in examples:
        lines.append(f"  {ex}")
    if hint:
        lines.append(f"提示: {hint}")
    return "\n".join(lines)


def _portable_csv_row(row: Json) -> Optional[Json]:
    metric = str(row.get("metric") or "")
    evidence = row.get("evidence") or {}
    source_file = str(evidence.get("file") or "")
    if os.path.isabs(source_file):
        relative = os.path.relpath(source_file, os.getcwd())
        source_file = os.path.basename(source_file) if relative.startswith(".." + os.sep) else relative
    line = evidence.get("line")
    if not source_file or not isinstance(line, int) or line < 1:
        return None
    if metric in {"line", "toggle", "branch", "condition", "fsm"}:
        object_value, bin_value = {
            "line": ("", ""),
            "toggle": (row.get("toggle_signal") or row.get("name") or "", row.get("value") or ""),
            "branch": (row.get("branch") or "", row.get("branch_bin") or row.get("name") or ""),
            "condition": (row.get("condition") or "", row.get("condition_bin") or row.get("name") or ""),
            "fsm": (row.get("fsm") or "", row.get("name") or ""),
        }[metric]
        return {"coverage_kind": "code", "source_file": source_file,
                "scope": row.get("scope") or "", "metric": metric,
                "line": str(line), "object": str(object_value), "bin": str(bin_value)}
    if metric == "functional":
        return {"coverage_kind": "functional", "source_file": source_file,
                "scope": row.get("scope") or "", "line": str(line),
                "covergroup": row.get("covergroup") or "",
                "coverpoint": row.get("coverpoint") or "", "cross": row.get("cross") or "",
                "bin": row.get("bin") or ""}
    if metric == "assert":
        return {"coverage_kind": "assertion", "source_file": source_file,
                "scope": row.get("scope") or "", "line": str(line),
                "assertion": row.get("full_name") or row.get("name") or "",
                "assertion_kind": row.get("type") or ""}
    return None


def _selector_matches(selector: dict, row: dict) -> bool:
    """检查一个 coverage item 是否匹配 selector。"""
    metric = selector["metric"]
    if row.get("metric") != metric:
        return False
    if row.get("scope") != selector.get("scope"):
        return False

    if metric == "line":
        ev = row.get("evidence") or {}
        sel_file = selector.get("file", "")
        row_file = ev.get("file") or ""
        if sel_file and row_file:
            if row_file != sel_file and not row_file.endswith("/" + sel_file):
                return False
        return ev.get("line") == selector.get("line")

    if metric == "toggle":
        if not _field_match(row, "toggle_signal", selector.get("signal")):
            return False
        sel_trans = selector.get("transition", "")
        # Normalize: accept "0->1", "0 -> 1", or NPI enum names
        row_trans = _normalize_transition(row.get("toggle_transition") or row.get("name", ""))
        return _normalize_transition(sel_trans) == row_trans

    if metric == "branch":
        return (_field_match(row, "branch", selector.get("branch"))
                and selector.get("arm") == (row.get("branch_bin") or row.get("name", "")))

    if metric == "condition":
        return (_field_match(row, "condition", selector.get("condition"))
                and selector.get("term") == (row.get("condition_bin") or row.get("name", "")))

    if metric == "fsm":
        return (_field_match(row, "fsm", selector.get("fsm"))
                and selector.get("transition") == row.get("name", ""))

    if metric == "assert":
        sel_name = selector.get("name", "")
        if sel_name and row.get("name") != sel_name:
            return False
        sel_kind = selector.get("kind")
        if sel_kind and row.get("assert_kind") != sel_kind:
            return False
        return True

    if metric == "functional":
        if row.get("covergroup") != selector.get("covergroup"):
            return False
        if row.get("coverpoint") != selector.get("coverpoint"):
            return False
        sel_cross = selector.get("cross")
        if sel_cross and row.get("cross") != sel_cross:
            return False
        return row.get("bin") == selector.get("bin")

    return False


def _field_match(row: dict, field: str, expected: str | None) -> bool:
    if not expected:
        return True
    return str(row.get(field, "")) == expected


def _normalize_transition(value: str) -> str:
    """Normalize toggle transition to a canonical form like '0->1'."""
    # NPI enum → human-readable
    npi_map = {
        "npiCovToggle01": "0->1",
        "npiCovToggle10": "1->0",
        "npiCovToggle0X": "0->X",
        "npiCovToggleX0": "X->0",
        "npiCovToggle1X": "1->X",
        "npiCovToggleX1": "X->1",
        "npiCovToggleZX": "Z->X",
        "npiCovToggleXZ": "X->Z",
    }
    if value in npi_map:
        return npi_map[value]
    # Remove spaces: "0 -> 1" → "0->1"
    return value.replace(" ", "")


@dataclass
class NpiCoverageBackend(CoverageBackend):
    worker_kind = "npi_python"

    vdb: str
    exclusion_policy: str = "default"
    python_kind: str = "current"
    cov: Any = None
    npisys: Any = None
    api: NpiApiBinding | None = field(default=None, init=False)
    db: Any = None
    merged_test: Any = None
    test_map: Dict[str, Any] = field(default_factory=dict)
    coverage_identities: Dict[str, Json] = field(default_factory=dict)
    locator_handles: Dict[str, Any] = field(default_factory=dict, init=False)
    _pinned_handle_ids: set[int] = field(default_factory=set, init=False)
    coverage_ref_namespace: str = field(
        default_factory=lambda: secrets.token_hex(16)
    )
    # URG 即调缓存
    _urg_loaded: bool = field(default=False, init=False)
    _urg_scopes: Dict[str, Json] = field(default_factory=dict, init=False)
    _urg_metrics: List[str] = field(default_factory=list, init=False)
    _urg_top_scopes: List[Json] = field(default_factory=list, init=False)
    _urg_groups: List[Json] = field(default_factory=list, init=False)
    _urg_asserts: List[Json] = field(default_factory=list, init=False)
    _urg_index: UrgSummaryIndex | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        log_lifecycle_event("adhoc", "npi.init.begin", True, {"vdb": self.vdb})
        try:
            self.cov, self.npisys = import_pynpi()
        except XcovError as exc:
            log_lifecycle_event("adhoc", "npi.init.failed", False,
                                {"vdb": self.vdb, "error": str(exc)})
            raise
        self.api = NpiApiBinding(self.cov, self.npisys)
        cov_open_contract = _cov_open_contract(self.cov.open)
        self.api._contracts["cov.open"] = cov_open_contract
        with _redirect_stdout_to_stderr():
            init_ok = self.api.module_call("npisys.init", sys.argv)
        if init_ok != 1:
            log_lifecycle_event("adhoc", "npi.init.failed", False,
                                {"vdb": self.vdb, "init_ok": init_ok})
            raise XcovError("NPI_INIT_FAILED", "npisys.init failed")
        log_lifecycle_event("adhoc", "npi.init.ok", True, {"vdb": self.vdb})
        try:
            log_lifecycle_event("adhoc", "vdb.open.begin", True, {"vdb": self.vdb})
            with _redirect_stdout_to_stderr():
                config_opt = (
                    int(self.cov.ConfigOpt.ExclusionInStrictMode)
                    if self.exclusion_policy == "strict"
                    else 0
                )
            if len(cov_open_contract.positional_args) == 1:
                if config_opt:
                    raise XcovError(
                        "NPI_COV_OPEN_STRICT_UNSUPPORTED",
                        "installed pynpi.cov.open does not accept config_opt; strict exclusion is unavailable",
                        actual_signature="open(vdb)",
                    )
                self.db = self.api.module_call("cov.open", self.vdb)
            else:
                self.db = self.api.module_call("cov.open", self.vdb, config_opt)
            if not self.db:
                log_lifecycle_event("adhoc", "vdb.open.failed", False, {"vdb": self.vdb})
                raise XcovError(
                    "VDB_OPEN_FAILED",
                    "cov.open returned empty handle",
                    vdb=self.vdb,
                )
            log_lifecycle_event("adhoc", "vdb.open.ok", True, {"vdb": self.vdb})
            tests = self.api.call("database.test_handles", self.db)
            if not tests:
                raise XcovError(
                    "VDB_OPEN_FAILED",
                    "coverage database contains no test handles",
                    vdb=self.vdb,
                )
            for test in tests:
                name = self.api.call("test.name", test)
                name = self.api.expect(
                    "test.name",
                    test,
                    name,
                    expected="non-empty string",
                    predicate=lambda value: isinstance(value, str) and bool(value),
                )
                self.test_map[name] = test
            self.merged_test = None
            for test in tests:
                if self.merged_test is None:
                    self.merged_test = test
                else:
                    self.merged_test = self.api.module_call(
                        "cov.merge_test",
                        self.merged_test,
                        test,
                    )
                    self.api.expect(
                        "cov.merge_test",
                        self.cov,
                        self.merged_test,
                        expected="non-empty merged test handle",
                        predicate=bool,
                    )
        except Exception:
            try:
                if self.db:
                    with _redirect_stdout_to_stderr():
                        self.api.call("database.close", self.db)
            finally:
                with _redirect_stdout_to_stderr():
                    self.api.module_call("npisys.end")
                self.npisys = None
            raise

    def close(self) -> None:
        try:
            for handle in self.locator_handles.values():
                self._api().module_call("cov.release_handle", handle)
            self.locator_handles.clear()
            self._pinned_handle_ids.clear()
            if self.db:
                log_lifecycle_event("adhoc", "vdb.close.begin", True, {"vdb": self.vdb})
                with _redirect_stdout_to_stderr():
                    self._api().call("database.close", self.db)
                log_lifecycle_event("adhoc", "vdb.close.ok", True, {"vdb": self.vdb})
        finally:
            if self.npisys:
                log_lifecycle_event("adhoc", "npi.end.begin", True, {"vdb": self.vdb})
                with _redirect_stdout_to_stderr():
                    self._api().module_call("npisys.end")
                log_lifecycle_event("adhoc", "npi.end.ok", True, {"vdb": self.vdb})
            self._urg_loaded = False
            self._urg_scopes.clear()
            self._urg_metrics.clear()
            self._urg_top_scopes.clear()
            self._urg_groups.clear()
            self._urg_asserts.clear()
            self._urg_index = None

    def _api(self) -> NpiApiBinding:
        if self.api is None:
            raise RuntimeError("NPI API binding is not initialized")
        return self.api

    def tests(self) -> List[Json]:
        self._ensure_urg()
        assert self._urg_index is not None
        return [{"name": name} for name in self._urg_index.tests]

    def _test_handle(self, test: str) -> Any:
        if test in ("merged", "", None):
            return self.merged_test
        if test == "each":
            raise XcovError("TEST_MODE_NOT_SUPPORTED",
                            'test="each" is not implemented yet; use test="merged" or a concrete test name')
        if test in self.test_map:
            return self.test_map[test]
        raise XcovError("TEST_NOT_FOUND", "test not found", test=test)

    def summary(self) -> Json:
        self._ensure_urg()
        assert self._urg_index is not None
        return {
            "test_count": len(self._urg_index.tests),
            "top_scope_count": len(self._urg_index.top_scopes),
        }

    def top_scopes(self) -> List[Json]:
        self._ensure_urg()
        assert self._urg_index is not None
        return [dict(row) for row in self._urg_index.top_scopes]

    def scope_metrics(self) -> Dict[str, Json]:
        """Return URG session.xml subtree ratios keyed by elaborated instance."""
        self._ensure_urg()
        assert self._urg_index is not None
        return {
            scope: {metric: dict(values) for metric, values in metrics.items()}
            for scope, metrics in self._urg_index.scope_metrics.items()
        }

    def scopes(self) -> List[Json]:
        self._ensure_urg()
        assert self._urg_index is not None
        return [dict(row) for row in self._urg_index.scopes]

    def _walk_scopes(self, inst: Any, rows: List[Json]) -> None:
        rows.append(self._scope_row_from_inst(inst))
        for child in self._api().call("instance.instance_handles", inst):
            try:
                self._walk_scopes(child, rows)
            finally:
                self.release_if_handle(child)

    # ── URG XML 数据源 ──

    def _ensure_urg(self) -> None:
        if self._urg_loaded:
            return
        index = _load_urg_summary(self.vdb)
        self._urg_index = index
        self._urg_metrics = list(index.metric_names)
        self._urg_scopes = {
            row["full_name"]: {
                "name": row["name"],
                "full_name": row["full_name"],
                "type": row["type"],
                "metrics": index.scope_metrics[row["full_name"]],
            }
            for row in index.scopes
        }
        self._urg_top_scopes = [dict(row) for row in index.top_scopes]
        self._urg_groups = [dict(row) for row in index.functional_rows]
        self._urg_asserts = [dict(row) for row in index.assertion_rows]
        self._urg_loaded = True

    def scope_functional_from_urg(self) -> List[Json]:
        self._ensure_urg()
        return list(self._urg_groups)

    def scope_assert_from_urg(self) -> List[Json]:
        self._ensure_urg()
        return list(self._urg_asserts)

    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
        """NPI 详细数据（有 evidence）。URG scope 聚合数据在 scopes/summary 中。"""
        test_hdl = self._test_handle(test)
        wanted = METRICS if metrics is None else metrics
        if functional_only and "functional" not in wanted:
            wanted = ["functional"]
        rows: List[Json] = []
        design_metrics = [metric for metric in wanted if metric != "functional"]
        if design_metrics and not functional_only:
            for inst in self._api().call("database.instance_handles", self.db):
                try:
                    self._walk_items(inst, test_hdl, design_metrics, scope, rows)
                finally:
                    self.release_if_handle(inst)
        if "functional" in wanted:
            self._walk_functional_items(test_hdl, scope, rows)
        for row in rows:
            ref = row.get("coverage_ref")
            if isinstance(ref, str):
                self.coverage_identities[ref] = coverage_identity_for_row(row)
            row.pop("_exclude_targets", None)
        return rows

    def gap_items(self, metric: str, scope: Optional[str] = None,
                  test: str = "merged") -> List[Json]:
        if metric not in {"assert", "functional"}:
            raise XcovError("INVALID_METRIC", "structured gap export only supports assert/functional",
                            metric=metric)
        test_hdl = self._test_handle(test)
        rows: List[Json] = []

        def pin(handle: Any, row: Json) -> None:
            key = _locator_key(row["_exclude_targets"][0])
            if key not in self.locator_handles:
                self.locator_handles[key] = handle
                self._pinned_handle_ids.add(id(handle))

        if metric == "functional":
            self._walk_functional_items(test_hdl, scope, rows, pin)
        else:
            for inst in self._api().call("database.instance_handles", self.db):
                try:
                    self._walk_items(inst, test_hdl, [metric], scope, rows, pin)
                finally:
                    self.release_if_handle(inst)
        return rows

    def _npi_items(self, wanted_metrics: Optional[List[str]] = None) -> List[Json]:
        """NPI 详细遍历（有 evidence）。"""
        return self.items(metrics=wanted_metrics)

    def load_exclusions(self, paths: List[str], test: str = "merged") -> List[Json]:
        test_hdl = self._merged_only(test)
        results: List[Json] = []
        for path in paths:
            value = self._api().call(
                "test.load_exclude_file",
                test_hdl,
                path,
            )
            if value != 1:
                raise XcovError(
                    "EXCLUSION_LOAD_FAILED",
                    "pynpi load_exclude_file returned failure",
                    path=path,
                )
            results.append({"path": path, "status": "loaded"})
        return results

    def attach_gap_locators(self, payload: Json, test: str = "merged") -> Json:
        """Attach direct, scope-local NPI paths to URG gap IDs."""
        metric = payload["metric"]
        scope = payload["scope"]
        test_hdl = self._merged_only(test)
        inst = self.db.handle_by_name(scope)
        if not inst:
            raise XcovError("EXPORT_GAP_RESOLVE_MISSING", "NPI scope is missing", scope=scope)
        metric_hdl = getattr(inst, METRIC_METHODS[metric])()
        if not metric_hdl:
            self.release_if_handle(inst)
            raise XcovError("EXPORT_GAP_RESOLVE_MISSING", "NPI metric is missing", scope=scope, metric=metric)
        leaf_types = {
            "line": {"npiCovStmtBin"},
            "condition": {"npiCovConditionBin"},
            "branch": {"npiCovBranchBin"},
            "toggle": {"npiCovToggleBin"},
            "fsm": {"npiCovStateBin", "npiCovTransBin", "npiCovSeqBin"},
        }[metric]
        records: List[Json] = []

        def walk(handle: Any, path: tuple[int, ...], ancestors: List[Json],
                 inherited_file: str = "", inherited_line: int = 0) -> None:
            typ = handle.type()
            name = str(handle.name() or "")
            current = {"type": typ, "name": name}
            try:
                handle_file = str(handle.file_name() or "")
            except Exception:
                handle_file = ""
            try:
                handle_line = int(handle.line_no(test_hdl) or 0)
            except Exception:
                handle_line = 0
            source_file = handle_file or inherited_file
            source_line = handle_line or inherited_line
            if typ in leaf_types:
                covered = int(handle.covered(test_hdl))
                coverable = int(handle.coverable(test_hdl))
                if covered < coverable:
                    records.append({
                        "path": list(path),
                        "type": typ,
                        "name": name,
                        "missing": coverable - covered,
                        "ancestors": [*ancestors, current],
                        "source_file": source_file,
                        "source_line": source_line,
                    })
            children = handle.child_handles()
            for index, child in enumerate(children):
                try:
                    walk(
                        child, (*path, index), [*ancestors, current],
                        source_file, source_line,
                    )
                finally:
                    self.release_if_handle(child)

        try:
            walk(metric_hdl, (), [])
        finally:
            self.release_if_handle(metric_hdl)
            self.release_if_handle(inst)

        def locator(record: Json) -> Json:
            ancestors = record["ancestors"]
            object_types = {
                "toggle": {"npiCovSignal", "npiCovSignalBit"},
                "branch": {"npiCovBranch"},
                "condition": {"npiCovCondition"},
                "fsm": {"npiCovFSM", "npiCovFsm"},
            }.get(metric, set())
            csv_object = next(
                (item["name"] for item in reversed(ancestors[:-1]) if item["type"] in object_types),
                "",
            )
            return {
                "scope": scope,
                "metric": metric,
                "path": record["path"],
                "type": record["type"],
                "name": record["name"],
                "csv_object": csv_object,
                "csv_bin": record["name"].replace(" -> ", "->"),
                "csv_source_file": record["source_file"],
                "csv_line": record["source_line"],
            }

        if metric == "line":
            gaps = [gap for group in payload["line_groups"] for gap in group["uncovered"]]
            units = gaps
            leaves = [record for record in records for _ in range(record["missing"])]
            self._assign_ordered_gap_locators(metric, scope, units, leaves, locator)
        elif metric == "branch":
            gaps = [gap for group in payload["decision_groups"] for gap in group["uncovered"]]
            leaves = [record for record in records for _ in range(record["missing"])]
            self._assign_ordered_gap_locators(metric, scope, gaps, leaves, locator)
        elif metric == "condition":
            units = []
            for group in payload["condition_groups"]:
                for gap in group["uncovered"]:
                    units.extend([gap] * len(gap.get("origins") or [None]))
            leaves = [record for record in records for _ in range(record["missing"])]
            self._assign_ordered_gap_locators(metric, scope, units, leaves, locator)
        elif metric == "toggle":
            for gap in payload["gaps"]:
                base, indices = _toggle_gap_object(gap["object"])
                wanted_edges = {edge.replace("->", " -> ") for edge in gap["missing_edges"]}
                matched = []
                for record in records:
                    names = [item["name"] for item in record["ancestors"]]
                    signal_match = base in names
                    bit_names = {name for name in names if name.startswith(base + "[")}
                    bit_match = indices is None or any(
                        int(name.rsplit("[", 1)[1][:-1]) in indices for name in bit_names
                    ) or (indices == {0} and base in names and not bit_names)
                    if signal_match and bit_match and record["name"] in wanted_edges:
                        matched.append(locator(record))
                if not matched:
                    raise XcovError("EXPORT_GAP_RESOLVE_MISSING", "toggle gap has no direct NPI target", gap_id=gap["gap_id"])
                gap["_exclude_targets"] = matched
        else:
            for group in payload["fsm_groups"]:
                fsm_name = group["fsm"]
                for gap in group["gaps"]:
                    expected_type = {
                        "state": "npiCovStateBin",
                        "transition": "npiCovTransBin",
                        "sequence": "npiCovSeqBin",
                    }[gap["object_kind"]]
                    matched = [
                        locator(record) for record in records
                        if record["type"] == expected_type
                        and record["name"] == gap["object"]
                        and any(item["type"] in {"npiCovFSM", "npiCovFsm"} and item["name"] == fsm_name
                                for item in record["ancestors"])
                    ]
                    if not matched:
                        gap["_exclude_targets"] = []
                        gap["_exclude_error"] = "NPI target is unavailable"
                    else:
                        gap["_exclude_targets"] = matched
        payload["exclusion_locator"] = {
            "version": "xcov.npi_path.v1",
            "vdb": os.path.realpath(self.vdb),
        }
        return payload

    @staticmethod
    def _assign_ordered_gap_locators(metric: str, scope: str, gaps: List[Json],
                                     leaves: List[Json], make_locator: Callable[[Json], Json]) -> None:
        if len(gaps) != len(leaves):
            raise XcovError(
                "EXPORT_GAP_RESOLVE_AMBIGUOUS",
                "URG gaps and direct NPI coverage units do not align",
                metric=metric, scope=scope, gap_units=len(gaps), npi_units=len(leaves),
            )
        for gap, record in zip(gaps, leaves):
            target = make_locator(record)
            targets = gap.setdefault("_exclude_targets", [])
            if target not in targets:
                targets.append(target)

    def set_exclusion_locator(self, locator: Json, excluded: bool = True,
                              test: str = "merged") -> Json:
        test_hdl = self._merged_only(test)
        pinned = self.locator_handles.get(_locator_key(locator))
        if pinned:
            current = pinned
        elif locator.get("root") == "instance":
            current = self.db.handle_by_name(locator["scope"])
        elif locator.get("root") == "functional":
            current = self._api().call("test.testbench_metric_handle", test_hdl)
        else:
            inst = self.db.handle_by_name(locator["scope"])
            if not inst:
                return {"status": "failed", "reason": "scope_missing"}
            current = getattr(inst, METRIC_METHODS[locator["metric"]])()
            self.release_if_handle(inst)
        if not current:
            return {"status": "failed", "reason": "metric_missing"}
        if not pinned:
            for index in locator["path"]:
                children = current.child_handles()
                if not isinstance(index, int) or index < 0 or index >= len(children):
                    for child in children:
                        self.release_if_handle(child)
                    self.release_if_handle(current)
                    return {"status": "failed", "reason": "path_missing"}
                selected = children[index]
                for child_index, child in enumerate(children):
                    if child_index != index:
                        self.release_if_handle(child)
                self.release_if_handle(current)
                current = selected
        try:
            if current.type() != locator["type"] or str(current.name() or "") != locator["name"]:
                return {"status": "failed", "reason": "identity_mismatch"}
            before = bool(current.has_status_excluded_at_report_time(test_hdl))
            if before == excluded:
                return {"status": "already_in_state", "before": before, "after": before}
            value = current.set_status_excluded_at_report_time(test_hdl, 1 if excluded else 0)
            after = bool(current.has_status_excluded_at_report_time(test_hdl))
            return {
                "status": "changed" if value == 1 and after == excluded else "failed",
                "before": before,
                "after": after,
            }
        finally:
            if not pinned:
                self.release_if_handle(current)

    def resolve_container_records(self, records: List[Json], test: str = "merged") -> List[Json]:
        self._merged_only(test)
        functional_rows: List[Json] | None = None
        results: List[Json] = []
        for record in records:
            target_kind = str(record["target_kind"])
            matches: List[Json] = []
            if target_kind == "instance":
                handle = self.db.handle_by_name(record["scope"])
                if handle:
                    try:
                        if str(handle.type()) == "npiCovInstance" and str(handle.full_name()) == record["scope"]:
                            matches = [{
                                "root": "instance", "scope": record["scope"],
                                "path": [], "type": "npiCovInstance",
                                "name": str(handle.name() or record["scope"].rsplit(".", 1)[-1]),
                            }]
                    finally:
                        self.release_if_handle(handle)
            else:
                if functional_rows is None:
                    functional_rows = self.items(metrics=["functional"], test=test, functional_only=True)
                expected_type = {
                    "covergroup": "npiCovCovergroup",
                    "coverpoint": "npiCovCoverpoint",
                    "cross": "npiCovCross",
                }[target_kind]
                for row in functional_rows:
                    if row.get("type") != expected_type or row.get("scope") != record["scope"]:
                        continue
                    if row.get("covergroup") != record["covergroup"]:
                        continue
                    if target_kind != "covergroup" and row.get(target_kind) != record["item"]:
                        continue
                    matches.extend(row.get("_exclude_targets") or [])
            results.append({
                "coverage_kind": "container",
                "source_file": "",
                "csv_line": record["_line_no"],
                "status": "matched" if len(matches) == 1 else "missing" if not matches else "ambiguous",
                "validity": "still_valid" if len(matches) == 1 else "coverage_object_missing" if not matches else "ambiguous",
                "match_count": len(matches),
                "reason": record["reason"],
                "coverage_refs": [],
                "locators": matches,
            })
        return results

    def resolve_gap_payload(self, payload: Json, test: str = "merged") -> Json:
        """Resolve an URG-only artifact after the user requests exclusion.

        Code coverage keeps the existing strict URG-to-NPI alignment logic.
        Assertion and functional coverage are matched by their stable semantic
        fields; NPI traversal is intentionally delayed until this method.
        """
        metric = payload.get("metric")
        if metric in {"line", "condition", "branch", "toggle", "fsm"}:
            return self.attach_gap_locators(payload, test=test)
        if metric not in {"assert", "functional"}:
            raise XcovError(
                "EXPORT_FILE_INVALID",
                "unsupported semantic gap metric",
                metric=metric,
            )
        rows = self.gap_items(metric, test=test)
        available: Dict[tuple[Any, ...], List[Json]] = {}
        for row in rows:
            key = _semantic_gap_key(metric, row)
            available.setdefault(key, []).append(row)
        for gap in payload.get("gaps") or []:
            matches = available.get(_semantic_gap_key(metric, gap), [])
            if len(matches) != 1:
                gap["_exclude_targets"] = []
                gap["_exclude_error"] = (
                    "NPI semantic target is missing"
                    if not matches else
                    "NPI semantic target is ambiguous"
                )
                continue
            matched = matches[0]
            evidence = matched.get("evidence") or {}
            gap["_resolved_evidence"] = dict(evidence)
            gap["_exclude_targets"] = list(matched.get("_exclude_targets") or [])
        payload["exclusion_locator"] = {
            "version": "xcov.npi_path.v1",
            "vdb": os.path.realpath(self.vdb),
        }
        return payload

    def set_exclusion(
        self,
        coverage_ref: str,
        excluded: bool,
        test: str = "merged",
    ) -> Json:
        test_hdl = self._merged_only(test)
        expected_identity = self.coverage_identities.get(coverage_ref)
        if expected_identity is None:
            return {
                "coverage_ref": coverage_ref,
                "status": "failed",
                "match_count": 0,
            }
        readable_matches = [
            row
            for row in self._npi_items()
            if (row.get("coverage_ref") or coverage_ref_for_row(row))
            == coverage_ref
            and coverage_identity_for_row(row) == expected_identity
        ]
        if len(readable_matches) != 1:
            return {
                "coverage_ref": coverage_ref,
                "status": "failed",
                "match_count": len(readable_matches),
            }
        readable = readable_matches[0]
        csv_row = _portable_csv_row(readable)
        before = "excluded_at_report_time" in readable["status"]
        compile_immutable = (
            not excluded
            and "excluded_at_compile_time" in readable["status"]
        )
        if compile_immutable and not before:
            return {
                "coverage_ref": coverage_ref,
                "status": "immutable_compile_time",
                "before": before,
                "after": before,
                "_csv_row": csv_row,
            }
        if before == excluded:
            return {
                "coverage_ref": coverage_ref,
                "status": "already_in_state",
                "before": before,
                "after": before,
                "_csv_row": csv_row,
            }
        results: List[Json] = []

        def mutate(hdl: Any, row: Json) -> None:
            if (
                (row.get("coverage_ref") or coverage_ref_for_row(row))
                != coverage_ref
                or coverage_identity_for_row(row) != expected_identity
            ):
                return
            value = self._api().call(
                "coverage.set_status_excluded_at_report_time",
                hdl,
                test_hdl,
                1 if excluded else 0,
            )
            after_value = self._api().call(
                "coverage.has_status_excluded_at_report_time",
                hdl,
                test_hdl,
            )
            after = bool(after_value)
            results.append({
                "coverage_ref": coverage_ref,
                "status": (
                    "immutable_compile_time"
                    if value == 1 and after == excluded and compile_immutable
                    else "changed"
                    if value == 1 and after == excluded
                    else "failed"
                ),
                "before": before,
                "after": after,
                "_csv_row": csv_row,
            })

        self._scan_score_handles(test_hdl, mutate)
        if len(results) != 1:
            return {
                "coverage_ref": coverage_ref,
                "status": "failed",
                "match_count": len(results),
            }
        return results[0]

    def save_exclusions(self, path: str, test: str = "merged") -> None:
        test_hdl = self._merged_only(test)
        value = self._api().call(
            "test.save_exclude_file",
            test_hdl,
            path,
            "w",
        )
        if value != 1:
            raise XcovError(
                "EXCLUSION_EXPORT_FAILED",
                'pynpi save_exclude_file(path, "w") returned failure',
                path=path,
            )

    def unload_exclusions(self, test: str = "merged") -> None:
        test_hdl = self._merged_only(test)
        value = self._api().call(
            "test.unload_exclusion",
            test_hdl,
        )
        if value != 1:
            raise XcovError(
                "EXCLUSION_UNLOAD_FAILED",
                "pynpi unload_exclusion returned failure",
            )

    def _merged_only(self, test: str) -> Any:
        if test != "merged":
            raise XcovError(
                "TEST_MODE_NOT_SUPPORTED",
                'exclusion management requires test="merged"',
                test=test,
            )
        return self._test_handle(test)

    def _scan_score_handles(
        self,
        test_hdl: Any,
        callback: Callable[[Any, Json], None],
    ) -> None:
        rows: List[Json] = []
        for inst in self._api().call("database.instance_handles", self.db):
            try:
                self._walk_items(
                    inst,
                    test_hdl,
                    [metric for metric in METRICS if metric != "functional"],
                    None,
                    rows,
                    callback,
                )
            finally:
                self.release_if_handle(inst)
        self._walk_functional_items(test_hdl, None, rows, callback)

    def _walk_items(
        self,
        inst: Any,
        test_hdl: Any,
        wanted: List[str],
        scope: Optional[str],
        rows: List[Json],
        handle_callback: Optional[Callable[[Any, Json], None]] = None,
    ) -> None:
        api = self._api()
        inst_full = _required_string(api, "instance.full_name", inst)
        if scope is None or str(inst_full).startswith(scope):
            for metric in wanted:
                method = METRIC_METHODS.get(metric)
                if not method:
                    raise RuntimeError(f"undeclared coverage metric: {metric}")
                metric_hdl = api.call(f"instance.{method}", inst)
                if metric_hdl:
                    try:
                        self._walk_metric(
                            metric_hdl,
                            metric,
                            inst_full,
                            test_hdl,
                            rows,
                            handle_callback,
                        )
                    finally:
                        self.release_if_handle(metric_hdl)
        for child in api.call("instance.instance_handles", inst):
            try:
                self._walk_items(
                    child,
                    test_hdl,
                    wanted,
                    scope,
                    rows,
                    handle_callback,
                )
            finally:
                self.release_if_handle(child)

    def release_if_handle(self, hdl: Any) -> None:
        if hdl and id(hdl) not in self._pinned_handle_ids:
            self._api().module_call("cov.release_handle", hdl)

    def _walk_metric(
        self,
        hdl: Any,
        metric: str,
        scope: str,
        test_hdl: Any,
        rows: List[Json],
        handle_callback: Optional[Callable[[Any, Json], None]] = None,
    ) -> None:
        if metric == "functional":
            raise RuntimeError(
                "functional coverage must use the authoritative functional walker"
            )
        for index, child in enumerate(
            self._api().call("coverage.child_handles", hdl)
        ):
            try:
                self._walk_leaf(
                    child,
                    metric,
                    scope,
                    test_hdl,
                    rows,
                    {},
                    None,
                    handle_callback,
                    (index,),
                )
            finally:
                self.release_if_handle(child)

    def _walk_functional_items(
        self,
        test_hdl: Any,
        scope: Optional[str],
        rows: List[Json],
        handle_callback: Optional[Callable[[Any, Json], None]] = None,
    ) -> None:
        metric_hdl = self._api().call(
            "test.testbench_metric_handle",
            test_hdl,
        )
        if not metric_hdl:
            return
        try:
            for index, child in enumerate(self._api().call(
                "coverage.child_handles",
                metric_hdl,
            )):
                try:
                    self._walk_functional_leaf(
                        child,
                        test_hdl,
                        rows,
                        {},
                        scope,
                        None,
                        handle_callback,
                        (index,),
                    )
                finally:
                    self.release_if_handle(child)
        finally:
            self.release_if_handle(metric_hdl)

    def _walk_functional_leaf(
        self,
        hdl: Any,
        test_hdl: Any,
        rows: List[Json],
        functional_path: Json,
        scope_filter: Optional[str],
        parent_source: Optional[Json],
        handle_callback: Optional[Callable[[Any, Json], None]] = None,
        traversal_path: tuple[int, ...] = (),
    ) -> None:
        api = self._api()
        typ = _required_string(api, "coverage.type", hdl)
        name = _required_string(api, "coverage.name", hdl)
        path = dict(functional_path)
        if typ == "npiCovCovergroup":
            path = {"covergroup": name}
        elif typ == "npiCovCoverpoint":
            path["coverpoint"] = name
        elif typ == "npiCovCross":
            path["cross"] = name
        elif typ == "npiCovCoverBin":
            path["bin"] = name
        full_name = _optional_string(api, "coverage.full_name", hdl)
        if not full_name:
            full_name = ".".join(
                value for value in (
                    str(path.get("covergroup") or ""),
                    str(path.get("coverpoint") or path.get("cross") or ""),
                    str(path.get("bin") or ""),
                ) if value
            ) or name
        scope = _validate_functional_identity(api, hdl, full_name, path)
        raw_evidence = {
            "file": _optional_string(api, "coverage.file_name", hdl),
            "line": _optional_source_line(
                api,
                "coverage.line_no",
                hdl,
                test_hdl,
            ),
        }
        own_source = _functional_source(typ, name, full_name, raw_evidence)
        row_source = own_source or parent_source
        evidence = dict(row_source["evidence"]) if row_source else raw_evidence
        if scope_filter is None or str(scope or full_name).startswith(scope_filter):
            covered = _required_integer(
                api,
                "coverage.covered",
                hdl,
                test_hdl,
            )
            coverable = _required_integer(
                api,
                "coverage.coverable",
                hdl,
                test_hdl,
            )
            count = _required_integer(
                api,
                "coverage.count",
                hdl,
                test_hdl,
            )
            status = _status_flags(
                api,
                hdl,
                test_hdl,
                covered,
                coverable,
            )
            score_payload = _npi_score_payload(
                "functional",
                typ,
                covered,
                coverable,
                count,
            )
            rows.append({
                "metric": "functional",
                "type": typ,
                "scope": scope,
                "name": name,
                "full_name": full_name,
                **score_payload,
                "status": status,
                "evidence": evidence,
                "coverage_ref": _coverage_ref_from_path(
                    self.coverage_ref_namespace,
                    "functional",
                    str(scope or ""),
                    typ,
                    traversal_path,
                ),
                "_exclude_targets": [{
                    "root": "functional", "metric": "functional",
                    "path": list(traversal_path), "type": typ, "name": name,
                }],
                **path,
            })
            if row_source and row_source is not own_source:
                rows[-1]["evidence_source"] = {
                    "inherited": True,
                    "type": row_source.get("type"),
                    "name": row_source.get("name"),
                    "full_name": row_source.get("full_name"),
                }
            if handle_callback is not None and is_score_bearing_row(rows[-1]):
                handle_callback(hdl, rows[-1])
        for index, child in enumerate(
            api.call("coverage.child_handles", hdl)
        ):
            try:
                self._walk_functional_leaf(
                    child,
                    test_hdl,
                    rows,
                    path,
                    scope_filter,
                    own_source or parent_source,
                    handle_callback,
                    (*traversal_path, index),
                )
            finally:
                self.release_if_handle(child)

    def _walk_leaf(
        self,
        hdl: Any,
        metric: str,
        scope: str,
        test_hdl: Any,
        rows: List[Json],
        coverage_path: Json,
        parent_source: Optional[Json],
        handle_callback: Optional[Callable[[Any, Json], None]] = None,
        traversal_path: tuple[int, ...] = (),
    ) -> None:
        api = self._api()
        typ = _required_string(api, "coverage.type", hdl)
        name = _required_string(api, "coverage.name", hdl)
        full_name = _optional_string(api, "coverage.full_name", hdl)
        if not full_name:
            full_name = f"{scope}.{metric}.{'.'.join(map(str, traversal_path))}.{name}"
        path = _code_coverage_path(
            api,
            metric,
            typ,
            hdl,
            test_hdl,
            name,
            full_name,
            coverage_path,
            self.release_if_handle,
        )
        covered = _required_integer(
            api,
            "coverage.covered",
            hdl,
            test_hdl,
        )
        coverable = _required_integer(
            api,
            "coverage.coverable",
            hdl,
            test_hdl,
        )
        count = _required_integer(
            api,
            "coverage.count",
            hdl,
            test_hdl,
        )
        raw_evidence = {
            "file": _optional_string(api, "coverage.file_name", hdl),
            "line": _optional_source_line(
                api,
                "coverage.line_no",
                hdl,
                test_hdl,
            ),
        }
        own_source = _coverage_source(typ, name, full_name, raw_evidence)
        row_source = own_source or parent_source
        evidence = dict(row_source["evidence"]) if row_source else raw_evidence
        status = _status_flags(api, hdl, test_hdl, covered, coverable)
        score_payload = _npi_score_payload(
            metric,
            typ,
            covered,
            coverable,
            count,
        )
        row = {
            "metric": metric,
            "type": typ,
            "scope": scope,
            "name": name,
            "full_name": full_name,
            **score_payload,
            "status": status,
            "evidence": evidence,
            "coverage_ref": _coverage_ref_from_path(
                self.coverage_ref_namespace,
                metric,
                scope,
                typ,
                traversal_path,
            ),
            "_exclude_targets": [{
                "root": "instance", "scope": scope, "metric": metric,
                "path": list(traversal_path), "type": typ, "name": name,
            }],
            **path,
        }
        value = _coverage_value(api, hdl, test_hdl)
        if value is not None:
            row["value"] = value
        if metric == "toggle":
            transition = _toggle_transition(api, hdl, test_hdl)
            if transition is not None:
                row["toggle_transition"] = transition
        if row_source and row_source is not own_source:
            row["evidence_source"] = {
                "inherited": True,
                "type": row_source.get("type"),
                "name": row_source.get("name"),
                "full_name": row_source.get("full_name"),
            }
        if (metric == "branch" and typ == "npiCovBranchBin"
                and _branch_mask_hint_enabled()
                and "branch_bin" in row):
            bv = row["branch_bin"]
            if isinstance(bv, str):
                hint = _branch_mask_hint(bv)
                if hint is not None:
                    row["branch_mask"] = hint
        rows.append(row)
        if handle_callback is not None and is_score_bearing_row(row):
            handle_callback(hdl, row)
        for index, child in enumerate(
            api.call("coverage.child_handles", hdl)
        ):
            try:
                self._walk_leaf(
                    child,
                    metric,
                    scope,
                    test_hdl,
                    rows,
                    path,
                    own_source or parent_source,
                    handle_callback,
                    (*traversal_path, index),
                )
            finally:
                self.release_if_handle(child)


@dataclass
class UrgCoverageBackend(CoverageBackend):
    """URG read backend with an exclude-only, lazily-created NPI context."""

    worker_kind = "urg"

    vdb: str
    exclusion_policy: str = "default"
    urg_cache_dir: str | None = None
    run_manifest_digest: str | None = None
    session_id: str | None = None
    npi_factory: Callable[..., CoverageBackend] = field(
        default=NpiCoverageBackend,
        repr=False,
    )
    _urg_index: UrgSummaryIndex | None = field(default=None, init=False, repr=False)
    _summary_el_path: str | None = field(default=None, init=False, repr=False)
    cache_info: Json | None = field(default=None, init=False)
    _npi: CoverageBackend | None = field(default=None, init=False, repr=False)

    @property
    def npi_initialized(self) -> bool:
        return self._npi is not None

    def _summary_index(self) -> UrgSummaryIndex:
        if self._urg_index is None:
            self._urg_index, self.cache_info = load_cached_urg_summary(
                self.vdb,
                cache_root=self.urg_cache_dir,
                el_path=self._summary_el_path,
                run_manifest_digest=self.run_manifest_digest,
                runner=UrgRunner(session_id=self.session_id),
            )
        return self._urg_index

    def set_summary_exclusion(self, el_path: str | None) -> None:
        canonical = str(Path(el_path).resolve()) if el_path else None
        if canonical != self._summary_el_path:
            self._summary_el_path = canonical
            self._urg_index = None
            self.cache_info = None

    def invalidate_summary(self) -> None:
        self._urg_index = None

    def _exclude_backend(self) -> CoverageBackend:
        if self._npi is None:
            self._npi = self.npi_factory(
                self.vdb,
                exclusion_policy=self.exclusion_policy,
            )
        return self._npi

    def close(self) -> None:
        if self._npi is not None:
            try:
                self._npi.close()
            finally:
                self._npi = None
        self._urg_index = None

    def tests(self) -> List[Json]:
        return [{"name": name} for name in self._summary_index().tests]

    def summary(self) -> Json:
        index = self._summary_index()
        return {
            "test_count": len(index.tests),
            "top_scope_count": len(index.top_scopes),
        }

    def top_scopes(self) -> List[Json]:
        return [dict(row) for row in self._summary_index().top_scopes]

    def scopes(self) -> List[Json]:
        return [dict(row) for row in self._summary_index().scopes]

    def scope_metrics(self) -> Dict[str, Json]:
        return {
            scope: {metric: dict(values) for metric, values in metrics.items()}
            for scope, metrics in self._summary_index().scope_metrics.items()
        }

    def scope_functional_from_urg(self) -> List[Json]:
        return [dict(row) for row in self._summary_index().functional_rows]

    def scope_assert_from_urg(self) -> List[Json]:
        return [dict(row) for row in self._summary_index().assertion_rows]

    # These methods belong exclusively to exclusion workflows. They are the
    # only normal-session path allowed to create the NPI context.
    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
        return self._exclude_backend().items(
            metrics=metrics, scope=scope, test=test,
            functional_only=functional_only,
        )

    def gap_items(self, metric: str, scope: Optional[str] = None,
                  test: str = "merged") -> List[Json]:
        return self._exclude_backend().gap_items(metric, scope=scope, test=test)

    def load_exclusions(self, paths: List[str], test: str = "merged") -> List[Json]:
        return self._exclude_backend().load_exclusions(paths, test=test)

    def set_exclusion(self, coverage_ref: str, excluded: bool,
                      test: str = "merged") -> Json:
        return self._exclude_backend().set_exclusion(
            coverage_ref, excluded, test=test,
        )

    def save_exclusions(self, path: str, test: str = "merged") -> None:
        self._exclude_backend().save_exclusions(path, test=test)

    def unload_exclusions(self, test: str = "merged") -> None:
        self._exclude_backend().unload_exclusions(test=test)

    def resolve_gap_payload(self, payload: Json, test: str = "merged") -> Json:
        return self._exclude_backend().resolve_gap_payload(payload, test=test)

    def resolve_container_records(self, records: List[Json], test: str = "merged") -> List[Json]:
        return self._exclude_backend().resolve_container_records(records, test=test)

    def set_exclusion_locator(self, locator: Json, excluded: bool = True,
                              test: str = "merged") -> Json:
        return self._exclude_backend().set_exclusion_locator(
            locator, excluded, test=test,
        )


def _code_coverage_path(api: NpiApiBinding, metric: str, typ: Any,
                        hdl: Any, test_hdl: Any, name: Any,
                        full_name: Any, coverage_path: Json,
                        release_handle: Any) -> Json:
    path = dict(coverage_path)
    label = str(full_name)
    short = str(name)
    if metric == "toggle":
        if typ == "npiCovSignal":
            path["toggle_signal"] = short
            is_port = _optional_flag(
                api,
                "coverage.is_port",
                hdl,
                test_hdl,
            )
            if is_port not in (None, -1, "-1"):
                path["toggle_is_port"] = bool(is_port)
        elif typ == "npiCovSignalBit":
            path["toggle_bit"] = short
            if short and short != "None":
                parent = _parent_from_bit(short)
                path.setdefault("toggle_signal", parent if parent else short)
            is_port = _optional_flag(
                api,
                "coverage.is_port",
                hdl,
                test_hdl,
            )
            if is_port not in (None, -1, "-1"):
                path["toggle_is_port"] = bool(is_port)
        elif typ == "npiCovToggleBin":
            transition = _toggle_transition(api, hdl, test_hdl)
            path.setdefault(
                "toggle_transition",
                transition if transition is not None else short,
            )
    elif metric == "assert":
        kind = _assert_kind(typ)
        if kind:
            path["assert_kind"] = kind
            path["assert_object"] = label
            severity = _optional_integer(
                api,
                "coverage.severity",
                hdl,
                test_hdl,
            )
            category = _optional_integer(
                api,
                "coverage.category",
                hdl,
                test_hdl,
            )
            if severity not in (None, -1, "-1"):
                path["severity"] = severity
            if category not in (None, -1, "-1"):
                path["category"] = category
        elif typ in ASSERT_BIN_TYPES:
            path.setdefault("assert_bin", short)
    elif metric == "condition":
        if typ == "npiCovCondition":
            path["condition"] = short
            terms = _term_summary(
                api,
                hdl,
                "coverage.condition_term_handles",
                test_hdl,
                release_handle,
            )
            if terms:
                path["condition_terms"] = terms
        elif typ == "npiCovConditionBin":
            value = _coverage_value(api, hdl, test_hdl)
            path["condition_bin"] = value if value is not None else short
    elif metric == "branch":
        if typ == "npiCovBranch":
            path["branch"] = short
            terms = _term_summary(
                api,
                hdl,
                "coverage.branch_term_handles",
                test_hdl,
                release_handle,
            )
            if terms:
                path["branch_terms"] = terms
        elif typ == "npiCovBranchBin":
            value = _coverage_value(api, hdl, test_hdl)
            path["branch_bin"] = value if value is not None else short
    elif metric == "fsm":
        if typ in ("npiCovFSM", "npiCovFsm"):
            path["fsm"] = short
    return {k: v for k, v in path.items() if v not in (None, "")}


ASSERT_OBJECT_KINDS = {
    "npiCovAssert": "assertion",
    "npiCovCoverProperty": "cover_property",
    "npiCovCoverSequence": "cover_sequence",
}

ASSERT_BIN_TYPES = {
    "npiCovAttemptBin",
    "npiCovSuccessBin",
    "npiCovFailureBin",
    "npiCovIncompleteBin",
    "npiCovFirstmatchBin",
}


def _assert_kind(typ: Any) -> str | None:
    return ASSERT_OBJECT_KINDS.get(str(typ or ""))


def _parent_from_bit(label: str) -> str | None:
    if "[" in label and label.endswith("]"):
        return label.rsplit("[", 1)[0]
    if "." in label:
        return label.rsplit(".", 1)[0]
    return None


def _coverage_value(
    api: NpiApiBinding,
    hdl: Any,
    test_hdl: Any,
) -> Any:
    value = api.call("coverage.value", hdl, test_hdl)
    if value in (None, ""):
        return None
    if value == -1 or value == "-1":
        return None
    return value


def _toggle_transition(
    api: NpiApiBinding,
    hdl: Any,
    test_hdl: Any,
) -> str | None:
    value = api.call("coverage.toggle_type", hdl, test_hdl)
    if value in (None, "", -1, "-1"):
        return None
    return str(value) if value not in (None, "") else None


def _term_summary(api: NpiApiBinding, hdl: Any, operation: str,
                  test_hdl: Any, release_handle: Any) -> str | None:
    parts: List[str] = []
    for term in api.call(operation, hdl):
        try:
            label = _required_string(api, "coverage.name", term)
            value = _coverage_value(api, term, test_hdl)
            if label and value is not None and str(value) != str(label):
                parts.append(f"{label}:{value}")
            elif label:
                parts.append(str(label))
            elif value is not None:
                parts.append(str(value))
        finally:
            release_handle(term)
    return ";".join(parts) if parts else None


def _coverage_source(typ: Any, name: Any, full_name: Any, evidence: Json) -> Json | None:
    if not _valid_evidence(evidence):
        return None
    return {
        "type": typ,
        "name": name,
        "full_name": full_name,
        "evidence": dict(evidence),
    }


def _required_string(
    api: NpiApiBinding,
    operation: str,
    obj: Any,
    *args: Any,
) -> str:
    value = api.call(operation, obj, *args)
    return api.expect(
        operation,
        obj,
        value,
        expected="non-empty string",
        predicate=lambda item: isinstance(item, str) and bool(item),
    )


def _optional_string(
    api: NpiApiBinding,
    operation: str,
    obj: Any,
    *args: Any,
) -> str | None:
    value = api.call(operation, obj, *args)
    return api.expect(
        operation,
        obj,
        value,
        expected="string or null",
        predicate=lambda item: item is None or isinstance(item, str),
    )


def _required_integer(
    api: NpiApiBinding,
    operation: str,
    obj: Any,
    *args: Any,
) -> int:
    value = api.call(operation, obj, *args)
    return api.expect(
        operation,
        obj,
        value,
        expected="integer",
        predicate=lambda item: (
            isinstance(item, int) and not isinstance(item, bool)
        ),
    )


def _optional_integer(
    api: NpiApiBinding,
    operation: str,
    obj: Any,
    *args: Any,
) -> int | None:
    value = api.call(operation, obj, *args)
    return api.expect(
        operation,
        obj,
        value,
        expected="integer or null",
        predicate=lambda item: (
            item is None
            or (isinstance(item, int) and not isinstance(item, bool))
        ),
    )


def _optional_source_line(
    api: NpiApiBinding,
    operation: str,
    obj: Any,
    *args: Any,
) -> int | None:
    value = _optional_integer(api, operation, obj, *args)
    if value in (None, -1):
        return None
    return api.expect(
        operation,
        obj,
        value,
        expected="positive source line integer, -1 sentinel, or null",
        predicate=lambda item: isinstance(item, int) and item > 0,
    )


def _optional_flag(
    api: NpiApiBinding,
    operation: str,
    obj: Any,
    *args: Any,
) -> bool | int | None:
    value = api.call(operation, obj, *args)
    return api.expect(
        operation,
        obj,
        value,
        expected="boolean, integer, or null",
        predicate=lambda item: (
            item is None
            or isinstance(item, bool)
            or (isinstance(item, int) and not isinstance(item, bool))
        ),
    )


def _scope_parent(full_name: str) -> str | None:
    if "." not in full_name:
        return None
    return full_name.rsplit(".", 1)[0]


def _scope_depth(full_name: str) -> int:
    return full_name.count(".")


def _scope_row(full_name: str) -> Json:
    return {
        "name": full_name.rsplit(".", 1)[-1],
        "full_name": full_name,
        "parent": _scope_parent(full_name),
        "depth": _scope_depth(full_name),
        "type": "npiCovInstance",
    }


def _scope_closure(scopes: Iterable[str]) -> List[str]:
    names = set()
    for scope in scopes:
        parts = str(scope).split(".")
        for idx in range(1, len(parts) + 1):
            names.add(".".join(parts[:idx]))
    return sorted(names)


def _functional_identity_parts(value: Any) -> List[str]:
    return [
        part
        for part in str(value).replace("::", ".").split(".")
        if part
    ]


def _functional_identity_leaf(value: Any) -> str:
    parts = _functional_identity_parts(value)
    return parts[-1] if parts else ""


def _validate_functional_identity(
    api: NpiApiBinding,
    hdl: Any,
    full_name: str,
    path: Json,
) -> str | None:
    """Validate component evidence against the authoritative NPI identity.

    ``coverage.full_name`` is the only canonical identity.  Covergroup,
    coverpoint/cross, and bin names are traversal evidence and therefore must
    form an exact suffix of that identity.  This preserves instance scope and
    rejects contradictory NPI facts instead of manufacturing a second name.
    """

    component_values = [
        path.get("covergroup"),
        path.get("coverpoint") or path.get("cross"),
        path.get("bin"),
    ]
    expected_suffix = [
        _functional_identity_leaf(value)
        for value in component_values
        if value not in (None, "")
    ]
    full_name_parts = _functional_identity_parts(full_name)
    api.expect(
        "coverage.full_name",
        hdl,
        full_name,
        expected=(
            "a non-empty functional identity whose suffix matches "
            f"{expected_suffix!r}"
        ),
        predicate=lambda _value: (
            bool(expected_suffix)
            and len(full_name_parts) >= len(expected_suffix)
            and full_name_parts[-len(expected_suffix):] == expected_suffix
        ),
    )
    scope_parts = full_name_parts[:-len(expected_suffix)]
    return ".".join(scope_parts) or None


def _functional_source(typ: Any, name: Any, full_name: Any, evidence: Json) -> Json | None:
    if not _valid_evidence(evidence):
        return None
    return {
        "type": typ,
        "name": name,
        "full_name": full_name,
        "evidence": dict(evidence),
    }


def _valid_evidence(evidence: Json) -> bool:
    if not evidence.get("file"):
        return False
    line = evidence.get("line")
    return isinstance(line, int) and not isinstance(line, bool) and line > 0


def _status_flags(api: NpiApiBinding, hdl: Any, test_hdl: Any,
                  covered: int, coverable: int) -> List[str]:
    flags: List[str] = []
    for method, flag in [
        ("has_status_excluded", "excluded"),
        ("has_status_partially_excluded", "partially_excluded"),
        ("has_status_excluded_at_compile_time", "excluded_at_compile_time"),
        ("has_status_excluded_at_report_time", "excluded_at_report_time"),
        ("has_status_unreachable", "unreachable"),
        ("has_status_illegal", "illegal"),
        ("has_status_proven", "proven"),
        ("has_status_attempted", "attempted"),
        ("has_status_partially_attempted", "partially_attempted"),
    ]:
        value = _optional_flag(
            api,
            f"coverage.{method}",
            hdl,
            test_hdl,
        )
        if value not in (None, False, 0, -1):
            flags.append(flag)
    if covered >= coverable and coverable > 0:
        flags.insert(0, "covered")
    elif covered >= 0 or coverable > 0 or not flags:
        flags.insert(0, "not_covered")
    return flags


def _branch_mask_hint_enabled() -> bool:
    return str(os.environ.get("XVERIF_XCOV_BRANCH_MASK_HINT", "1")).lower() not in {
        "0", "false", "no", "off",
    }


def _branch_mask_hint(mask: str) -> dict | None:
    """Decode branch bin bitmask into human-readable hints.

    Returns None when *mask* is empty or contains characters other than
    ``0``, ``1``, or ``-``.

    Encoding classifications:

    * ``path``      — mask contains ``-`` (don't-care) positions; used for
                      FSM always-block branches.
    * ``one_hot``   — exactly one ``1``, no ``-``; bit position (LSB=0)
                      indexes the case item or branch arm.
    * ``multi_bit`` — multiple ``1`` positions, no ``-``; encodes a path
                      through nested if-else chains.
    """
    if not mask or not all(c in "01-" for c in mask):
        return None
    ones = [i for i, ch in enumerate(reversed(mask)) if ch == "1"]
    zeros = [i for i, ch in enumerate(reversed(mask)) if ch == "0"]
    dontcares = sum(1 for ch in mask if ch == "-")
    hint: dict = {}
    if dontcares > 0:
        hint["encoding"] = "path"
        hint["active_bits"] = len(ones) + len(zeros)
        hint["dontcare_bits"] = dontcares
    elif len(ones) == 1:
        hint["encoding"] = "one_hot"
        hint["branch_arm_index"] = ones[0]
    else:
        hint["encoding"] = "multi_bit"
        hint["one_positions"] = ones
    return hint


@contextmanager
def _redirect_stdout_to_stderr():
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
