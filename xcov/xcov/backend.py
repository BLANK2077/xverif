from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
import secrets
import sys
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
from .errors import XcovError
from .logging import log_lifecycle_event

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

    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
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

    def save_exclusions(self, path: str, test: str = "merged") -> None:
        self._delegate.save_exclusions(path, test=test)

    def unload_exclusions(self, test: str = "merged") -> None:
        self._delegate.unload_exclusions(test=test)


class FakeCoverageBackend(CoverageBackend):
    """Deterministic test double selected only through backend-factory DI."""

    worker_kind = "fake"

    def __init__(
        self,
        vdb: str = "fake.vdb",
        exclusion_policy: str = "default",
    ) -> None:
        self.vdb = vdb
        self.exclusion_policy = exclusion_policy
        self._coverage_ref_namespace = secrets.token_hex(16)
        self._loaded_exclusion_files: List[str] = []
        self._saved_exclusion_sets: Dict[str, set[str]] = {}
        self._saved_exclusion_sets_by_name: Dict[str, set[str]] = {}
        self._report_excluded: set[str] = set()
        self._items = [
            {"metric": "line", "type": "npiCovStmtBin", "scope": "top.u_dut",
             "name": "stmt_12", "full_name": "top.u_dut.stmt_12",
             "covered": 1, "coverable": 1, "missing": 0, "count": 5,
             "coverage_pct": 100.0, "status": ["covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 12}},
            {"metric": "toggle", "type": "npiCovToggleBin", "scope": "top.u_dut.u_fifo",
             "name": "0 -> 1", "full_name": "top.u_dut.u_fifo.credit[0].0 -> 1",
             "toggle_signal": "top.u_dut.u_fifo.credit",
             "toggle_bit": "top.u_dut.u_fifo.credit[0]",
             "toggle_transition": "0 -> 1",
             "toggle_is_port": False,
             "covered": 0, "coverable": 1, "missing": 1, "count": 0,
             "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "rtl/fifo.sv", "line": 44}},
            {"metric": "toggle", "type": "npiCovToggleBin", "scope": "top.u_dut",
             "name": "1 -> 0", "full_name": "top.u_dut.PRESETn.1 -> 0",
             "toggle_signal": "top.u_dut.PRESETn",
             "toggle_bit": "top.u_dut.PRESETn",
             "toggle_transition": "1 -> 0",
             "toggle_is_port": True,
             "covered": 0, "coverable": 1, "missing": 1, "count": 0,
             "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "rtl/uart_top.sv", "line": 5}},
            {"metric": "branch", "type": "npiCovBranchBin", "scope": "top.u_dut.u_ctrl",
             "name": "else", "full_name": "top.u_dut.u_ctrl.branch_8.else",
             "branch": "if (enable)",
             "branch_bin": "else",
             "covered": 0, "coverable": 1, "missing": 1, "count": 0,
             "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 88}},
            {"metric": "branch", "type": "npiCovBranchBin", "scope": "top.u_dut.u_ctrl",
             "name": "000000100", "full_name": "top.u_dut.u_ctrl.branch_9.000000100",
             "branch": "case (filter)",
             "branch_bin": "000000100",
             "branch_mask": {"encoding": "one_hot", "branch_arm_index": 2},
             "covered": 0, "coverable": 1, "missing": 1, "count": 0,
             "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 95}},
            {"metric": "condition", "type": "npiCovConditionBin", "scope": "top.u_dut.u_ctrl",
             "name": "10", "full_name": "top.u_dut.u_ctrl.cond_9.10",
             "condition": "(enable && ready)",
             "condition_bin": "10",
             "condition_terms": "enable;ready",
             "covered": 0, "coverable": 1, "missing": 1, "count": 0,
             "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 91},
             "evidence_source": {"inherited": True, "type": "npiCovCondition",
                                 "name": "(enable && ready)",
                                 "full_name": "top.u_dut.u_ctrl.cond_9"}},
            {"metric": "assert", "type": "npiCovAssert", "scope": "top.u_dut.u_ctrl",
             "name": "p_ready", "full_name": "top.u_dut.u_ctrl.p_ready",
             "assert_kind": "assertion", "assert_object": "top.u_dut.u_ctrl.p_ready",
             "severity": 0, "category": 0,
             "covered": 0, "coverable": 1, "missing": 1, "count": None,
             "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 120}},
            {"metric": "assert", "type": "npiCovAttemptBin", "scope": "top.u_dut.u_ctrl",
             "name": "Attempt", "full_name": "top.u_dut.u_ctrl.p_ready.Attempt",
             "assert_kind": "assertion", "assert_object": "top.u_dut.u_ctrl.p_ready",
             "covered": None, "coverable": None, "missing": None, "count": 10,
             "coverage_pct": None, "status": ["attempted"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 120}},
            {"metric": "assert", "type": "npiCovSuccessBin", "scope": "top.u_dut.u_ctrl",
             "name": "Success", "full_name": "top.u_dut.u_ctrl.p_ready.Success",
             "assert_kind": "assertion", "assert_object": "top.u_dut.u_ctrl.p_ready",
             "covered": None, "coverable": None, "missing": None, "count": 8,
             "coverage_pct": None, "status": ["covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 120}},
            {"metric": "assert", "type": "npiCovFailureBin", "scope": "top.u_dut.u_ctrl",
             "name": "Failure", "full_name": "top.u_dut.u_ctrl.p_ready.Failure",
             "assert_kind": "assertion", "assert_object": "top.u_dut.u_ctrl.p_ready",
             "covered": None, "coverable": None, "missing": None, "count": 1,
             "coverage_pct": None, "status": ["not_covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 120}},
            {"metric": "assert", "type": "npiCovIncompleteBin", "scope": "top.u_dut.u_ctrl",
             "name": "Incomplete", "full_name": "top.u_dut.u_ctrl.p_ready.Incomplete",
             "assert_kind": "assertion", "assert_object": "top.u_dut.u_ctrl.p_ready",
             "covered": None, "coverable": None, "missing": None, "count": 1,
             "coverage_pct": None, "status": ["not_covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 120}},
            {"metric": "assert", "type": "npiCovCoverSequence", "scope": "top.u_dut.u_ctrl",
             "name": "seq_ready", "full_name": "top.u_dut.u_ctrl.seq_ready",
             "assert_kind": "cover_sequence", "assert_object": "top.u_dut.u_ctrl.seq_ready",
             "severity": 0, "category": 0,
             "covered": 1, "coverable": 1, "missing": 0, "count": None,
             "coverage_pct": 100.0, "status": ["covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 130}},
            {"metric": "assert", "type": "npiCovFirstmatchBin", "scope": "top.u_dut.u_ctrl",
             "name": "Firstmatch", "full_name": "top.u_dut.u_ctrl.seq_ready.Firstmatch",
             "assert_kind": "cover_sequence", "assert_object": "top.u_dut.u_ctrl.seq_ready",
             "covered": None, "coverable": None, "missing": None, "count": 3,
             "coverage_pct": None, "status": ["covered"],
             "evidence": {"file": "rtl/ctrl.sv", "line": 130}},
            {"metric": "functional", "type": "npiCovCovergroup", "scope": "top.u_dut",
             "name": "cg_credit", "full_name": "top.u_dut.cg_credit",
             "covergroup": "cg_credit", "covered": 0, "coverable": 1, "missing": 1,
             "count": None, "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "verif/env/uart_coverage.sv", "line": 21}},
            {"metric": "functional", "type": "npiCovCoverpoint", "scope": "top.u_dut",
             "name": "cp_level", "full_name": "top.u_dut.cg_credit.cp_level",
             "covergroup": "cg_credit", "coverpoint": "cp_level", "covered": 0,
             "coverable": 1, "missing": 1, "count": None, "coverage_pct": 0.0,
             "status": ["not_covered"],
             "evidence": {"file": "verif/env/uart_coverage.sv", "line": 22}},
            {"metric": "functional", "type": "npiCovCoverBin", "scope": "top.u_dut",
             "name": "zero_credit", "full_name": "top.u_dut.cg_credit.cp_level.zero_credit",
             "covergroup": "cg_credit", "coverpoint": "cp_level", "cross": None,
             "bin": "zero_credit", "covered": 0, "coverable": 1, "missing": 1,
             "count": 0, "coverage_pct": 0.0, "status": ["not_covered"],
             "evidence": {"file": "verif/env/uart_coverage.sv", "line": 22},
             "evidence_source": {"inherited": True, "type": "npiCovCoverpoint",
                                 "name": "cp_level",
                                 "full_name": "top.u_dut.cg_credit.cp_level"}},
        ]

    def tests(self) -> List[Json]:
        return [{"name": f"{self.vdb}/test"}]

    def summary(self) -> Json:
        return {"test_count": 1, "top_scope_count": len(self.top_scopes())}

    def top_scopes(self) -> List[Json]:
        top_names = sorted({str(i["scope"]).split(".")[0] for i in self._items})
        return [_scope_row(n) for n in top_names]

    def scopes(self) -> List[Json]:
        names = sorted(_scope_closure(i["scope"] for i in self._items))
        return [_scope_row(n) for n in names]

    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
        self._check_test(test)
        rows = list(self._items)
        if metrics is not None:
            rows = [r for r in rows if r.get("metric") in metrics]
        if scope:
            rows = [r for r in rows if str(r.get("scope", "")).startswith(scope)]
        if functional_only:
            rows = [r for r in rows if r.get("metric") == "functional"]
        out: List[Json] = []
        for raw in rows:
            row = dict(raw)
            ref = _namespaced_coverage_ref(
                self._coverage_ref_namespace,
                row,
            )
            row["coverage_ref"] = ref
            status = list(row["status"])
            if ref in self._report_excluded:
                for value in ("excluded", "excluded_at_report_time"):
                    if value not in status:
                        status.append(value)
            else:
                status = [
                    value
                    for value in status
                    if value != "excluded_at_report_time"
                    and not (
                        value == "excluded"
                        and "excluded_at_compile_time" not in status
                    )
                ]
            row["status"] = status
            out.append(row)
        return out

    def load_exclusions(self, paths: List[str], test: str = "merged") -> List[Json]:
        self._check_test(test)
        results: List[Json] = []
        for path in paths:
            refs = self._saved_exclusion_sets.get(os.path.abspath(path))
            if refs is None:
                refs = self._saved_exclusion_sets_by_name.get(Path(path).name)
            if refs is not None:
                self._report_excluded.update(refs)
            self._loaded_exclusion_files.append(path)
            results.append({"path": path, "status": "loaded"})
        return results

    def set_exclusion(
        self,
        coverage_ref: str,
        excluded: bool,
        test: str = "merged",
    ) -> Json:
        self._check_test(test)
        matches = [
            row
            for row in self.items(test=test)
            if row.get("coverage_ref") == coverage_ref
        ]
        if len(matches) != 1:
            return {
                "coverage_ref": coverage_ref,
                "status": "failed",
                "match_count": len(matches),
            }
        row = matches[0]
        before = "excluded_at_report_time" in row["status"]
        if not excluded and "excluded_at_compile_time" in row["status"]:
            if before:
                self._report_excluded.discard(coverage_ref)
            return {
                "coverage_ref": coverage_ref,
                "status": "immutable_compile_time",
                "before": before,
                "after": False,
            }
        if (
            excluded
            and self.exclusion_policy == "strict"
            and (row.get("covered") or 0) > 0
        ):
            return {
                "coverage_ref": coverage_ref,
                "status": "failed",
                "before": before,
                "after": before,
            }
        if before == excluded:
            return {
                "coverage_ref": coverage_ref,
                "status": "already_in_state",
                "before": before,
                "after": before,
            }
        if excluded:
            self._report_excluded.add(coverage_ref)
        else:
            self._report_excluded.discard(coverage_ref)
        after = coverage_ref in self._report_excluded
        return {
            "coverage_ref": coverage_ref,
            "status": "changed" if after == excluded else "failed",
            "before": before,
            "after": after,
        }

    def save_exclusions(self, path: str, test: str = "merged") -> None:
        self._check_test(test)
        absolute = os.path.abspath(path)
        self._saved_exclusion_sets[absolute] = set(self._report_excluded)
        self._saved_exclusion_sets_by_name[Path(absolute).name] = set(
            self._report_excluded
        )
        with open(absolute, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("# fake native exclusion file; content is opaque to xcov\n")
            stream.write(f"# exclusion_count={len(self._report_excluded)}\n")

    def unload_exclusions(self, test: str = "merged") -> None:
        self._check_test(test)
        self._report_excluded.clear()

    def _check_test(self, test: str) -> None:
        if test == "each":
            raise XcovError("TEST_MODE_NOT_SUPPORTED",
                            'test="each" is not implemented yet; use test="merged" or a concrete test name')


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
    coverage_ref_namespace: str = field(
        default_factory=lambda: secrets.token_hex(16)
    )

    def __post_init__(self) -> None:
        log_lifecycle_event("adhoc", "npi.init.begin", True, {"vdb": self.vdb})
        verdi_home = os.environ.get("XVERIF_XCOV_VERDI_HOME") or os.environ.get("VERDI_HOME")
        if not verdi_home:
            log_lifecycle_event("adhoc", "npi.init.failed", False,
                                {"vdb": self.vdb, "reason": "VERDI_HOME is required"})
            raise XcovError("NPI_INIT_FAILED", "VERDI_HOME is required")
        sys.path.append(os.path.abspath(os.path.join(verdi_home, "share/NPI/python")))
        try:
            from pynpi import cov, npisys  # type: ignore
        except Exception as exc:
            log_lifecycle_event("adhoc", "npi.import.failed", False,
                                {"vdb": self.vdb, "error": str(exc)})
            raise XcovError("NPI_INIT_FAILED", f"failed to import pynpi: {exc}") from exc
        self.cov = cov
        self.npisys = npisys
        self.api = NpiApiBinding(cov, npisys)
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
                self.db = self.api.module_call(
                    "cov.open",
                    self.vdb,
                    config_opt,
                )
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

    def _api(self) -> NpiApiBinding:
        if self.api is None:
            raise RuntimeError("NPI API binding is not initialized")
        return self.api

    def tests(self) -> List[Json]:
        return [{"name": name} for name in sorted(self.test_map)]

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
        return {"test_count": len(self.test_map), "top_scope_count": None}

    def top_scopes(self) -> List[Json]:
        rows: List[Json] = []
        for inst in self._api().call("database.instance_handles", self.db):
            try:
                rows.append(self._scope_row_from_inst(inst))
            finally:
                self.release_if_handle(inst)
        return rows

    def scopes(self) -> List[Json]:
        rows: List[Json] = []
        for inst in self._api().call("database.instance_handles", self.db):
            try:
                self._walk_scopes(inst, rows)
            finally:
                self.release_if_handle(inst)
        return rows

    def _scope_row_from_inst(self, inst: Any) -> Json:
        api = self._api()
        name = _required_string(api, "instance.name", inst)
        full_name = _required_string(api, "instance.full_name", inst)
        return {
            "name": name,
            "full_name": full_name,
            "parent": _scope_parent(full_name),
            "depth": _scope_depth(full_name),
            "type": _required_string(api, "instance.type", inst),
            "def_name": _optional_string(api, "instance.def_name", inst),
            "evidence": {
                "file": _optional_string(api, "instance.file_name", inst),
                "line": _optional_source_line(api, "instance.line_no", inst),
            },
        }

    def _walk_scopes(self, inst: Any, rows: List[Json]) -> None:
        rows.append(self._scope_row_from_inst(inst))
        for child in self._api().call("instance.instance_handles", inst):
            try:
                self._walk_scopes(child, rows)
            finally:
                self.release_if_handle(child)

    def items(self, metrics: Optional[List[str]] = None,
              scope: Optional[str] = None, test: str = "merged",
              functional_only: bool = False) -> List[Json]:
        test_hdl = self._test_handle(test)
        wanted = METRICS if metrics is None else metrics
        if functional_only and "functional" not in wanted:
            wanted = ["functional"]
        rows: List[Json] = []
        design_metrics = [metric for metric in wanted if metric != "functional"]
        if design_metrics and not functional_only:
            for inst in self._api().call("database.instance_handles", self.db):
                try:
                    self._walk_items(
                        inst,
                        test_hdl,
                        design_metrics,
                        scope,
                        rows,
                    )
                finally:
                    self.release_if_handle(inst)
        if "functional" in wanted:
            self._walk_functional_items(test_hdl, scope, rows)
        for row in rows:
            ref = row.get("coverage_ref")
            if isinstance(ref, str):
                self.coverage_identities[ref] = coverage_identity_for_row(row)
        return rows

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
            for row in self.items(test=test)
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
            }
        if before == excluded:
            return {
                "coverage_ref": coverage_ref,
                "status": "already_in_state",
                "before": before,
                "after": before,
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
        if hdl:
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


def _code_coverage_path(api: NpiApiBinding, metric: str, typ: Any,
                        hdl: Any, test_hdl: Any, name: Any,
                        full_name: Any, coverage_path: Json,
                        release_handle: Any) -> Json:
    path = dict(coverage_path)
    label = str(full_name)
    short = str(name)
    if metric == "toggle":
        if typ == "npiCovSignal":
            path["toggle_signal"] = label
            is_port = _optional_flag(
                api,
                "coverage.is_port",
                hdl,
                test_hdl,
            )
            if is_port not in (None, -1, "-1"):
                path["toggle_is_port"] = bool(is_port)
        elif typ == "npiCovSignalBit":
            path["toggle_bit"] = label
            parent = _parent_from_bit(label)
            if parent:
                path.setdefault("toggle_signal", parent)
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
            path["condition"] = label
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
            path["branch"] = label
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
    else:
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
