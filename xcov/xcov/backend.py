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

    def resolve_selector(self, selector: dict) -> dict:
        return {
            "valid": False, "coverage_ref": None,
            "errors": [{"field": None, "code": "NOT_SUPPORTED",
                        "message": "resolve_selector requires NpiCoverageBackend"}],
            "current_status": None,
            "note": "selector-based exclusion is only supported with NPI backend",
        }


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

    def resolve_selector(self, selector: dict) -> dict:
        return self._delegate.resolve_selector(selector)

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
    "line": "通过 export.code_coverage action 导出 modinfo.txt 查看准确的 scope、file、line。",
    "toggle": (
        "通过 export.code_coverage action 导出 modinfo.txt 查看准确的 signal 名和 transition 方向。"
        "URG modinfo Toggle 列: Toggle 0->1, Toggle 1->0"
    ),
    "branch": (
        "通过 export.code_coverage action 导出 modinfo.txt 查看准确的 branch 表达式和 arm 名。"
        "URG modinfo Branch arm 列: -1-, -2-, -3-, -4-（对应 case/if 的每个 arm）"
    ),
    "condition": (
        "通过 export.code_coverage action 导出 modinfo.txt 查看准确的 condition 表达式和 term 名。"
        "URG modinfo Condition term 列: -1-, -2-（对应表达式的每个 term）"
    ),
    "fsm": (
        "通过 export.code_coverage action 导出 modinfo.txt 查看准确的 FSM 状态名和转换。"
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
    coverage_ref_namespace: str = field(
        default_factory=lambda: secrets.token_hex(16)
    )
    # URG 即调缓存
    _urg_loaded: bool = field(default=False, init=False)
    _urg_scopes: Dict[str, Json] = field(default_factory=dict, init=False)
    _urg_metrics: List[str] = field(default_factory=list, init=False)
    _urg_top_scopes: List[Json] = field(default_factory=list, init=False)

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
            self._urg_loaded = False
            self._urg_scopes.clear()
            self._urg_metrics.clear()
            self._urg_top_scopes.clear()

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
        self._ensure_urg()
        return {"test_count": max(1, len(self.test_map)), "top_scope_count": len(self._urg_top_scopes)}

    def top_scopes(self) -> List[Json]:
        self._ensure_urg()
        result = []
        for s in self._urg_top_scopes:
            leaf = s["name"].rsplit(".", 1)[-1]
            result.append({"name": leaf, "full_name": s["name"],
                           "parent": None, "depth": 0, "type": "instance"})
        return result

    def scopes(self) -> List[Json]:
        self._ensure_urg()
        all_names = set(self._urg_scopes.keys())
        extra = set()
        for sname in all_names:
            parts = sname.split(".")
            for i in range(1, len(parts)):
                ancestor = ".".join(parts[:i])
                if ancestor not in all_names:
                    extra.add(ancestor)
        all_names |= extra
        result = []
        for sname in sorted(all_names):
            leaf = sname.rsplit(".", 1)[-1]
            parent = sname.rsplit(".", 1)[0] if "." in sname else None
            depth = sname.count(".")
            result.append({"name": leaf, "full_name": sname,
                           "parent": parent, "depth": depth, "type": "instance"})
        return result

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
        import subprocess, tempfile, xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory(prefix=".xcov-urg-") as cache_dir:
            xml_path = os.path.join(cache_dir, "session.xml")
            result = subprocess.run(
                ["urg", "-dir", self.vdb, "-report", cache_dir, "-format", "text", "-xml_verbose"],
                capture_output=True, text=True, encoding="utf-8", timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"URG failed (exit {result.returncode}): {result.stderr[:500]}")
            if not os.path.isfile(xml_path):
                raise RuntimeError(f"URG did not produce session.xml at {xml_path}")

            root = ET.parse(xml_path).getroot()
        hvp = root.find("hvp")
        if hvp is not None:
            datadef = hvp.find("datadef")
            if datadef is not None:
                self._urg_metrics = [
                    m.get("name", "") for m in datadef.findall("metdef") if m.get("builtin") == "1"
                ]
        old_cov = root.find("old_coverage")
        if old_cov is not None:
            self._urg_scopes = {}
            self._parse_urg_scopes(old_cov)
        self._urg_loaded = True

    def _parse_urg_scopes(self, element: Any, parent_name: str = "") -> None:
        for scope in element.findall("scope"):
            stype = scope.get("type", "")
            name = scope.get("name", "")
            full_name = name if not parent_name else (
                f"{parent_name}.{name}" if parent_name != name else name
            )
            if stype == "instance":
                metrics = {}
                for m in scope.findall("metric"):
                    mname = m.get("name", "")
                    val = m.get("value", "0/0")
                    excl = int(m.get("excl", 0))
                    if "/" in val:
                        covered_str, total_str = val.split("/", 1)
                        metrics[mname] = {"covered": int(covered_str),
                                          "coverable": int(total_str), "excluded": excl}
                self._urg_scopes[full_name] = {
                    "name": name, "full_name": full_name,
                    "type": "instance", "metrics": metrics,
                }
                if parent_name == "" or parent_name == name:
                    self._urg_top_scopes.append({"name": full_name, "full_name": full_name})
            self._parse_urg_scopes(scope, full_name)

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

    def resolve_selector(self, selector: dict) -> dict:
        """校验 selector 并解析为 coverage_ref。"""
        metric = selector.get("metric")
        errors: list = []

        if not isinstance(metric, str) or metric not in _VALID_METRICS:
            return {
                "valid": False, "coverage_ref": None,
                "errors": [{
                    "field": "metric", "code": "INVALID_METRIC",
                    "message": f"不支持的 metric: {metric}。合法值: {', '.join(sorted(_VALID_METRICS))}",
                }],
                "current_status": None,
                "note": _selector_note(metric or "line"),
            }

        required = _SELECTOR_FIELDS.get(metric, frozenset())
        missing = required - set(selector.keys())
        if missing:
            errors.append({
                "field": sorted(missing)[0], "code": "MISSING_FIELD",
                "message": f"{metric} selector 缺少必填字段: {', '.join(sorted(missing))}",
            })

        scope = selector.get("scope", "")
        if not isinstance(scope, str) or not scope:
            errors.append({"field": "scope", "code": "MISSING_FIELD", "message": "scope 是必填字段"})

        if errors:
            return {
                "valid": False, "coverage_ref": None, "errors": errors,
                "current_status": None, "note": _selector_note(metric),
            }

        items = self._npi_items(wanted_metrics=[metric] if metric != "functional" else None)
        if metric == "functional":
            items = self._npi_items(wanted_metrics=["functional"])

        matches = [row for row in items if _selector_matches(selector, row)]

        if len(matches) == 0:
            return {
                "valid": False, "coverage_ref": None,
                "errors": [{"field": None, "code": "NO_MATCH",
                            "message": f"selector 未匹配到任何 {metric} item。"}],
                "current_status": None, "note": _selector_note(metric),
            }
        if len(matches) > 1:
            return {
                "valid": False, "coverage_ref": None,
                "errors": [{"field": None, "code": "AMBIGUOUS_MATCH",
                            "message": f"selector 匹配到 {len(matches)} 个 item。"}],
                "current_status": None, "note": _selector_note(metric),
            }

        match = matches[0]
        ref = match.get("coverage_ref")
        if not isinstance(ref, str):
            return {
                "valid": False, "coverage_ref": None,
                "errors": [{"field": None, "code": "NPI_ERROR", "message": "item 缺少 coverage_ref"}],
                "current_status": None, "note": _selector_note(metric),
            }
        return {"valid": True, "coverage_ref": ref, "errors": [], "current_status": match.get("status", [])}

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
