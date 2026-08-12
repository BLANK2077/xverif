"""Exclude-only Synopsys Python NPI coverage helpers.

Coverage reading intentionally lives in :mod:`x_npi.urg`. Python NPI has no
bulk summary API and must recursively traverse coverage handles, so using it
for normal reads scales poorly and can drift from URG scoring semantics.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Sequence

if TYPE_CHECKING:
    from .exclusion_csv import ExclusionDocument


Json = Dict[str, Any]


class CoverageExclusionError(RuntimeError):
    """Raised when a native pynpi exclusion operation fails."""


def _cov() -> Any:
    from pynpi import cov  # type: ignore

    return cov


def _method(obj: Any, name: str) -> Callable[..., Any]:
    try:
        value = getattr(obj, name)
    except Exception as exc:
        raise CoverageExclusionError(f"missing pynpi method {name}") from exc
    if not callable(value):
        raise CoverageExclusionError(f"pynpi attribute {name} is not callable")
    return value


def _handles(obj: Any, name: str) -> List[Any]:
    try:
        value = _method(obj, name)()
    except CoverageExclusionError:
        raise
    except Exception as exc:
        raise CoverageExclusionError(f"pynpi {name} call failed") from exc
    if value is None:
        return []
    try:
        return list(value)
    except TypeError as exc:
        raise CoverageExclusionError(f"pynpi {name} did not return a handle list") from exc


def open_covdb(vdb: str, strict: bool = False) -> Any:
    """Open one VDB exactly once; never retry another cov.open signature."""

    cov = _cov()
    try:
        signature = inspect.signature(cov.open)
    except (TypeError, ValueError) as exc:
        raise CoverageExclusionError(f"cannot inspect cov.open signature: {exc}") from exc
    positional = [
        item for item in signature.parameters.values()
        if item.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    required = [item for item in positional if item.default is inspect.Parameter.empty]
    has_varargs = any(
        item.kind == inspect.Parameter.VAR_POSITIONAL
        for item in signature.parameters.values()
    )
    if has_varargs or len(required) != 1 or len(positional) not in (1, 2):
        raise CoverageExclusionError(f"unsupported cov.open signature: {signature}")
    if len(positional) == 1:
        if strict:
            raise CoverageExclusionError(
                "installed cov.open(vdb) does not support strict exclusion config_opt"
            )
        db = cov.open(vdb)
    else:
        config_opt = int(cov.ConfigOpt.ExclusionInStrictMode) if strict else 0
        db = cov.open(vdb, config_opt)
    if not db:
        raise CoverageExclusionError(f"cov.open failed: {vdb}")
    return db


def close_covdb(db: Any) -> None:
    try:
        _method(db, "close")()
    except CoverageExclusionError:
        raise
    except Exception as exc:
        raise CoverageExclusionError("pynpi database.close failed") from exc


def test_names(db: Any) -> List[str]:
    names = []
    for test in _handles(db, "test_handles"):
        try:
            names.append(str(_method(test, "name")()))
        except Exception as exc:
            raise CoverageExclusionError("pynpi test.name failed") from exc
    return sorted(names)


def merged_test_handle(db: Any) -> Any:
    cov = _cov()
    merged = None
    for test in _handles(db, "test_handles"):
        if merged is None:
            merged = test
            continue
        try:
            merged = cov.merge_test(merged, test)
        except Exception as exc:
            raise CoverageExclusionError("pynpi cov.merge_test failed") from exc
        if not merged:
            raise CoverageExclusionError("pynpi cov.merge_test returned no handle")
    if merged is None:
        raise CoverageExclusionError("coverage database has no tests")
    return merged


def load_exclusion_files(
    test: Any,
    paths: Sequence[str | os.PathLike[str]],
) -> List[Json]:
    """Load opaque native EL files in order; pynpi defines union semantics."""

    normalized = [os.fspath(path) for path in paths]
    for path in normalized:
        candidate = Path(path)
        if not candidate.is_file() or candidate.is_symlink():
            raise FileNotFoundError(f"exclusion file not found or unsafe: {path}")
    results: List[Json] = []
    loader = _method(test, "load_exclude_file")
    for path in normalized:
        try:
            value = loader(path)
        except Exception as exc:
            raise CoverageExclusionError("pynpi load_exclude_file call failed") from exc
        _require_exclusion_success("load_exclude_file", value, path=path)
        results.append({"path": path, "status": "loaded"})
    return results


def set_report_time_excluded(item: Any, test: Any, excluded: bool) -> Json:
    """Set one exact target's report-time exclusion and verify before/after."""

    target = bool(excluded)
    try:
        before = bool(_method(item, "has_status_excluded_at_report_time")(test))
        compile_time = bool(_method(item, "has_status_excluded_at_compile_time")(test))
    except Exception as exc:
        raise CoverageExclusionError("pynpi exclusion status query failed") from exc
    if not target and compile_time and not before:
        return {"status": "immutable_compile_time", "before": before, "after": before}
    if before == target:
        return {"status": "already_in_state", "before": before, "after": before}
    try:
        value = _method(item, "set_status_excluded_at_report_time")(
            test, 1 if target else 0,
        )
        after = bool(_method(item, "has_status_excluded_at_report_time")(test))
    except Exception as exc:
        raise CoverageExclusionError("pynpi report-time exclusion setter failed") from exc
    if value != 1 or after != target:
        status = "failed"
    elif not target and compile_time:
        status = "immutable_compile_time"
    else:
        status = "changed"
    return {"status": status, "before": before, "after": after}


def save_exclusion_file(test: Any, path: str | os.PathLike[str]) -> str:
    """Save exclusions as one opaque native EL file using mode ``w`` only."""

    normalized = os.fspath(path)
    try:
        value = _method(test, "save_exclude_file")(normalized, "w")
    except Exception as exc:
        raise CoverageExclusionError("pynpi save_exclude_file call failed") from exc
    _require_exclusion_success("save_exclude_file", value, path=normalized)
    return normalized


def unload_exclusions(test: Any) -> None:
    """Unload all report-time exclusions from the current merged test."""

    try:
        value = _method(test, "unload_exclusion")()
    except Exception as exc:
        raise CoverageExclusionError("pynpi unload_exclusion call failed") from exc
    _require_exclusion_success("unload_exclusion", value)


def compile_csv_to_el(
    db: Any,
    test: Any,
    csv_directory: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
) -> List[Json]:
    """Compile strict CSV sidecars into four opaque per-kind EL files.

    The built-in resolver performs exactly two streaming traversals per non-empty
    coverage kind: a read-only uniqueness preflight followed by an apply pass.
    It indexes CSV selectors and never scans the VDB once per CSV row, retains
    native handles across traversal callbacks, or materializes all coverage
    rows. Any failure restores the baseline native exclusion state and publishes
    no new EL set. CSV ``reason`` remains only in CSV and is never written to EL.
    """

    from .exclusion_csv import parse_directory

    documents = parse_directory(csv_directory)
    output_root = Path(output_directory).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    indexes = {
        document.kind: _SelectorIndex(document)
        for document in documents
    }
    for document in documents:
        index = indexes[document.kind]
        if index.record_count:
            _scan_document(db, test, index, apply=False)
            index.require_unique("preflight")

    with tempfile.TemporaryDirectory(prefix=".x-npi-csv-el-", dir=output_root) as temp:
        stage = Path(temp)
        baseline = stage / "baseline.el"
        save_exclusion_file(test, baseline)
        staged: Dict[str, Path] = {}
        try:
            unload_exclusions(test)
            for document in documents:
                index = indexes[document.kind]
                if index.record_count:
                    index.begin_apply()
                    _scan_document(db, test, index, apply=True)
                    index.require_unique("apply")
                path = stage / f"{document.kind}.el"
                save_exclusion_file(test, path)
                staged[document.kind] = path
                unload_exclusions(test)
        except Exception:
            unload_exclusions(test)
            load_exclusion_files(test, [baseline])
            raise

        destinations = {
            kind: output_root / f"{kind}.el"
            for kind in ("code", "functional", "assertion", "container")
        }
        backups: Dict[str, Path] = {}
        replaced: List[str] = []
        try:
            for kind in ("code", "functional", "assertion", "container"):
                destination = destinations[kind]
                if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                    raise CoverageExclusionError(f"unsafe EL output target: {destination}")
                if destination.exists():
                    backup = stage / f"{kind}.previous.el"
                    os.replace(destination, backup)
                    backups[kind] = backup
                os.replace(staged[kind], destination)
                replaced.append(kind)
            load_exclusion_files(
                test,
                [destinations[kind] for kind in ("code", "functional", "assertion", "container")],
            )
        except Exception:
            for kind in reversed(("code", "functional", "assertion", "container")):
                destination = destinations[kind]
                if kind in replaced and destination.exists():
                    destination.unlink()
                if kind in backups:
                    os.replace(backups[kind], destination)
            unload_exclusions(test)
            load_exclusion_files(test, [baseline])
            raise
    return [indexes[kind].published(str(destinations[kind]))
            for kind in ("code", "functional", "assertion", "container")]


_METRIC_METHODS = {
    "line": "line_metric_handle",
    "toggle": "toggle_metric_handle",
    "branch": "branch_metric_handle",
    "condition": "condition_metric_handle",
    "fsm": "fsm_metric_handle",
    "assert": "assert_metric_handle",
}
_LEAF_TYPES = {
    "line": frozenset({"npiCovStmtBin"}),
    "toggle": frozenset({"npiCovToggleBin"}),
    "branch": frozenset({"npiCovBranchBin"}),
    "condition": frozenset({"npiCovConditionBin"}),
    "fsm": frozenset({"npiCovStateBin", "npiCovTransBin", "npiCovSeqBin"}),
    "assertion": frozenset({
        "npiCovAssert", "npiCovCoverProperty", "npiCovCoverSequence",
    }),
    "functional": frozenset({"npiCovCoverBin"}),
}
_ASSERT_KINDS = {
    "npiCovAssert": "assertion",
    "npiCovCoverProperty": "cover_property",
    "npiCovCoverSequence": "cover_sequence",
}


def _normalized_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def _path_suffixes(value: Any) -> Iterable[str]:
    parts = [part for part in _normalized_path(value).split("/") if part]
    for index in range(len(parts)):
        yield "/".join(parts[index:])


def _normalized_transition(value: Any) -> str:
    return str(value or "").replace(" ", "")


def _optional_call(obj: Any, name: str, *args: Any) -> Any:
    try:
        return _method(obj, name)(*args)
    except CoverageExclusionError:
        raise
    except Exception as exc:
        raise CoverageExclusionError(f"pynpi {name} call failed") from exc


def _string_call(obj: Any, name: str, *args: Any) -> str:
    value = _optional_call(obj, name, *args)
    if not isinstance(value, str) or not value:
        raise CoverageExclusionError(f"pynpi {name} did not return a non-empty string")
    return value


def _optional_string_call(obj: Any, name: str, *args: Any) -> str:
    value = _optional_call(obj, name, *args)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CoverageExclusionError(f"pynpi {name} did not return a string or null")
    return value


def _release(handle: Any) -> None:
    if handle:
        try:
            _cov().release_handle(handle)
        except Exception as exc:
            raise CoverageExclusionError("pynpi cov.release_handle failed") from exc


class _SelectorRecord:
    def __init__(self, record_id: int, source_file: str, csv_line: int, row: Json) -> None:
        self.record_id = record_id
        self.source_file = source_file
        self.csv_line = csv_line
        self.row = row
        self.preflight_matches = 0
        self.apply_matches = 0
        self.changed = 0
        self.already = 0
        self.locator: Json | None = None


class _WalkContext:
    def __init__(
        self,
        source_file: str = "",
        source_line: int = 0,
        toggle_objects: tuple[str, ...] = (),
        branch: str = "",
        condition: str = "",
        fsm: str = "",
        covergroup: str = "",
        coverpoint: str = "",
        cross: str = "",
    ) -> None:
        self.source_file = source_file
        self.source_line = source_line
        self.toggle_objects = toggle_objects
        self.branch = branch
        self.condition = condition
        self.fsm = fsm
        self.covergroup = covergroup
        self.coverpoint = coverpoint
        self.cross = cross


class _SelectorIndex:
    def __init__(self, document: ExclusionDocument) -> None:
        self.document = document
        self.records: List[_SelectorRecord] = []
        self.keys: Dict[tuple[Any, ...], List[int]] = {}
        self.visited_handles = 0
        self.preflight_passes = 0
        self.apply_passes = 0
        for group in document.groups:
            for row in group.rows:
                record = _SelectorRecord(
                    len(self.records), _normalized_path(group.source_file),
                    int(row.get("_line_no") or 0), dict(row),
                )
                self.records.append(record)
                self.keys.setdefault(self._record_key(record), []).append(record.record_id)

    @property
    def kind(self) -> str:
        return self.document.kind

    @property
    def record_count(self) -> int:
        return len(self.records)

    @property
    def scopes(self) -> frozenset[str]:
        return frozenset(str(record.row["scope"]) for record in self.records)

    @property
    def metrics(self) -> tuple[str, ...]:
        if self.kind == "code":
            return tuple(sorted({str(record.row["metric"]) for record in self.records}))
        if self.kind == "assertion":
            return ("assert",)
        return ("functional",)

    def _record_key(self, record: _SelectorRecord) -> tuple[Any, ...]:
        row = record.row
        if self.kind == "code":
            metric = str(row["metric"])
            line = None if metric == "toggle" else int(row["line"])
            bin_name = (_normalized_transition(row["bin"])
                        if metric in {"toggle", "fsm"} else str(row["bin"]))
            return (self.kind, str(row["scope"]), metric, record.source_file,
                    line, str(row["object"]), bin_name)
        if self.kind == "functional":
            return (self.kind, str(row["scope"]), record.source_file,
                    int(row["line"]), str(row["covergroup"]),
                    str(row["coverpoint"]), str(row["cross"]), str(row["bin"]))
        if self.kind == "container":
            return (
                self.kind, str(row["target_kind"]), str(row["scope"]),
                str(row["covergroup"]), str(row["item"]),
            )
        return (self.kind, str(row["scope"]), record.source_file,
                int(row["line"]), str(row["assertion"]), str(row["assertion_kind"]))

    def candidate_ids(self, keys: Iterable[tuple[Any, ...]]) -> set[int]:
        result: set[int] = set()
        for key in keys:
            result.update(self.keys.get(key, ()))
        return result

    def has_functional_prefix(self, scope: str, covergroup: str) -> bool:
        for record in self.records:
            row = record.row
            if str(row.get("scope") or "") != scope:
                continue
            if str(row.get("covergroup") or "") == covergroup:
                return True
        return False

    def observe(
        self, ids: Iterable[int], target: Any, test: Any, apply: bool,
        locator: Json,
    ) -> None:
        selected = set(ids)
        if len(selected) > 1:
            lines = sorted(self.records[record_id].csv_line for record_id in selected)
            raise CoverageExclusionError(
                f"TARGET_AMBIGUOUS: one {self.kind} NPI target is selected by "
                f"multiple CSV rows {lines}"
            )
        for record_id in selected:
            record = self.records[record_id]
            if not apply:
                record.preflight_matches += 1
                if record.locator is None:
                    record.locator = dict(locator)
                continue
            record.apply_matches += 1
            result = set_report_time_excluded(target, test, True)
            if result["status"] == "changed":
                record.changed += 1
            elif result["status"] == "already_in_state":
                record.already += 1
            else:
                raise CoverageExclusionError(
                    f"failed to apply {self.kind} exclusion at CSV line "
                    f"{record.csv_line}: {result['status']}"
                )

    def begin_apply(self) -> None:
        for record in self.records:
            record.apply_matches = 0
            record.changed = 0
            record.already = 0

    def require_unique(self, phase: str) -> None:
        attribute = "preflight_matches" if phase == "preflight" else "apply_matches"
        for record in self.records:
            count = int(getattr(record, attribute))
            if count != 1:
                reason = "TARGET_MISSING" if count == 0 else "TARGET_AMBIGUOUS"
                if phase == "apply" and record.preflight_matches == 1:
                    reason = "TARGET_CHANGED_BETWEEN_PASSES"
                raise CoverageExclusionError(
                    f"{reason}: {self.kind} CSV line {record.csv_line} "
                    f"matched {count} NPI targets"
                )

    def published(self, path: str) -> Json:
        return {
            "coverage_kind": self.kind,
            "path": path,
            "status": "published",
            "record_count": self.record_count,
            "preflight_passes": self.preflight_passes,
            "apply_passes": self.apply_passes,
            "visited_handle_count": self.visited_handles,
            "matched_count": sum(record.apply_matches for record in self.records),
            "changed_count": sum(record.changed for record in self.records),
            "already_in_state_count": sum(record.already for record in self.records),
        }


def _scope_is_relevant(scope: str, wanted: frozenset[str]) -> bool:
    return any(
        candidate == scope or candidate.startswith(scope + ".")
        for candidate in wanted
    )


def _scan_document(db: Any, test: Any, index: _SelectorIndex, *, apply: bool) -> None:
    if apply:
        index.apply_passes += 1
    else:
        index.preflight_passes += 1
    if apply:
        _replay_document(db, test, index)
        return
    if index.kind == "container":
        for record in index.records:
            if record.row["target_kind"] != "instance":
                continue
            handle = _optional_call(db, "handle_by_name", record.row["scope"])
            if not handle:
                continue
            try:
                if _string_call(handle, "type") != "npiCovInstance":
                    raise CoverageExclusionError("container instance target has wrong NPI type")
                index.visited_handles += 1
                index.observe((record.record_id,), handle, test, apply, {
                    "root": "instance", "scope": str(record.row["scope"]),
                    "path": [], "type": "npiCovInstance",
                    "name": _string_call(handle, "name"),
                })
            finally:
                _release(handle)
        if not any(record.row["target_kind"] != "instance" for record in index.records):
            return
    if index.kind in {"functional", "container"}:
        metric = _optional_call(test, "testbench_metric_handle")
        if not metric:
            return
        try:
            _walk_functional(metric, test, index, _WalkContext(), apply)
        finally:
            _release(metric)
        return
    for scope in sorted(index.scopes):
        instance = _optional_call(db, "handle_by_name", scope)
        if not instance:
            continue
        try:
            if _string_call(instance, "type") != "npiCovInstance":
                raise CoverageExclusionError(
                    f"exact coverage scope {scope!r} is not an npiCovInstance"
                )
            _walk_exact_instance(instance, scope, test, index, apply)
        finally:
            _release(instance)


def _walk_exact_instance(
    instance: Any, scope: str, test: Any, index: _SelectorIndex, apply: bool,
) -> None:
    actual_scope = _string_call(instance, "full_name")
    if actual_scope != scope:
        raise CoverageExclusionError(
            f"handle_by_name identity mismatch: requested {scope!r}, got {actual_scope!r}"
        )
    for metric_name in index.metrics:
        metric = _optional_call(instance, _METRIC_METHODS[metric_name])
        if not metric:
            continue
        try:
            if index.kind == "assertion":
                _walk_assertion(metric, scope, test, index, _WalkContext(), apply)
            else:
                _walk_code(metric, metric_name, scope, test, index, _WalkContext(), apply)
        finally:
            _release(metric)


def _source_context(handle: Any, test: Any, parent: _WalkContext) -> _WalkContext:
    source_file = _optional_call(handle, "file_name")
    source_line = _optional_call(handle, "line_no", test)
    updates: Dict[str, Any] = {}
    if isinstance(source_file, str) and source_file:
        updates["source_file"] = source_file
    elif source_file is not None and not isinstance(source_file, str):
        raise CoverageExclusionError("pynpi file_name did not return a string or null")
    if isinstance(source_line, int) and not isinstance(source_line, bool) and source_line > 0:
        updates["source_line"] = source_line
    elif source_line not in (None, -1):
        raise CoverageExclusionError(
            "pynpi line_no did not return a positive integer, -1, or null"
        )
    if updates:
        return _WalkContext(**{
            **parent.__dict__,
            **updates,
        })
    return parent


def _walk_code(
    handle: Any,
    metric: str,
    scope: str,
    test: Any,
    index: _SelectorIndex,
    parent: _WalkContext,
    apply: bool,
    path: tuple[int, ...] = (),
) -> None:
    index.visited_handles += 1
    typ = _string_call(handle, "type")
    name = _string_call(handle, "name")
    context = _source_context(handle, test, parent)
    if metric == "toggle" and typ in {"npiCovSignal", "npiCovSignalBit"}:
        context = _WalkContext(**{
            **context.__dict__,
            "toggle_objects": (*context.toggle_objects, name),
        })
    elif metric == "branch" and typ == "npiCovBranch":
        context = _WalkContext(**{**context.__dict__, "branch": name})
    elif metric == "condition" and typ == "npiCovCondition":
        context = _WalkContext(**{**context.__dict__, "condition": name})
    elif metric == "fsm" and typ in {"npiCovFSM", "npiCovFsm"}:
        context = _WalkContext(**{**context.__dict__, "fsm": name})

    if typ in _LEAF_TYPES[index.kind if index.kind != "code" else metric]:
        keys = _code_candidate_keys(index, handle, test, scope, metric, name, context)
        index.observe(index.candidate_ids(keys), handle, test, apply, {
            "root": "metric", "scope": scope, "metric": metric,
            "path": list(path), "type": typ, "name": name,
        })
    for child_index, child in enumerate(_handles(handle, "child_handles")):
        try:
            _walk_code(child, metric, scope, test, index, context, apply, (*path, child_index))
        finally:
            _release(child)


def _code_candidate_keys(
    index: _SelectorIndex,
    handle: Any,
    test: Any,
    scope: str,
    metric: str,
    name: str,
    context: _WalkContext,
) -> Iterable[tuple[Any, ...]]:
    if metric == "toggle":
        transition = _optional_call(handle, "toggle_type", test)
        bin_names = {_normalized_transition(name), _normalized_transition(transition)}
        objects = set(context.toggle_objects)
        line: int | None = None
    else:
        bin_names = {
            "" if metric == "line"
            else _normalized_transition(name) if metric == "fsm"
            else name
        }
        objects = {
            "line": {""},
            "branch": {context.branch},
            "condition": {context.condition},
            "fsm": {context.fsm},
        }[metric]
        line = context.source_line
    for source_file in _path_suffixes(context.source_file):
        for object_name in objects:
            for bin_name in bin_names:
                yield ("code", scope, metric, source_file, line, object_name, bin_name)


def _walk_functional(
    handle: Any,
    test: Any,
    index: _SelectorIndex,
    parent: _WalkContext,
    apply: bool,
    path: tuple[int, ...] = (),
) -> None:
    index.visited_handles += 1
    typ = _string_call(handle, "type")
    name = _string_call(handle, "name")
    full_name = _optional_string_call(handle, "full_name")
    context = _source_context(handle, test, parent)
    if typ == "npiCovCovergroup":
        context = _WalkContext(**{
            **context.__dict__, "covergroup": name, "coverpoint": "", "cross": "",
        })
        scope, group = _functional_group_identity(name, full_name)
        if not index.has_functional_prefix(scope, group):
            return
    elif typ == "npiCovCoverpoint":
        context = _WalkContext(**{**context.__dict__, "coverpoint": name, "cross": ""})
    elif typ == "npiCovCross":
        context = _WalkContext(**{**context.__dict__, "cross": name, "coverpoint": ""})
    if index.kind == "container" and typ in {
        "npiCovCovergroup", "npiCovCoverpoint", "npiCovCross",
    }:
        target_kind = {
            "npiCovCovergroup": "covergroup",
            "npiCovCoverpoint": "coverpoint",
            "npiCovCross": "cross",
        }[typ]
        scope, group = _functional_group_identity(context.covergroup, full_name)
        item = "" if target_kind == "covergroup" else name
        key = ("container", target_kind, scope, group, item)
        index.observe(index.candidate_ids((key,)), handle, test, apply, {
            "root": "functional", "path": list(path), "type": typ, "name": name,
        })
    if index.kind == "functional" and typ in _LEAF_TYPES["functional"]:
        if not full_name:
            full_name = ".".join(
                value for value in (
                    context.covergroup,
                    context.coverpoint or context.cross,
                    name,
                ) if value
            )
        scope = _functional_scope(full_name, context, name)
        keys = (
            ("functional", scope, source_file, context.source_line,
             context.covergroup, context.coverpoint, context.cross, name)
            for source_file in _path_suffixes(context.source_file)
        )
        index.observe(index.candidate_ids(keys), handle, test, apply, {
            "root": "functional", "path": list(path), "type": typ, "name": name,
        })
    for child_index, child in enumerate(_handles(handle, "child_handles")):
        try:
            _walk_functional(child, test, index, context, apply, (*path, child_index))
        finally:
            _release(child)


def _functional_group_identity(name: str, full_name: str) -> tuple[str, str]:
    if "::" in name:
        return name.rsplit("::", 1)[0], name
    if full_name == name:
        return "", name
    suffix = "." + name
    if full_name.endswith(suffix):
        return full_name[:-len(suffix)], name
    return "", name


def _functional_parts(value: Any) -> List[str]:
    return [part for part in str(value).replace("::", ".").split(".") if part]


def _functional_scope(full_name: str, context: _WalkContext, bin_name: str) -> str:
    components = [context.covergroup, context.coverpoint or context.cross, bin_name]
    suffix = [_functional_parts(value)[-1] for value in components if value]
    parts = _functional_parts(full_name)
    if not suffix or len(parts) < len(suffix) or parts[-len(suffix):] != suffix:
        raise CoverageExclusionError(
            "pynpi functional full_name does not match traversal components"
        )
    return ".".join(parts[:-len(suffix)])


def _walk_assertion(
    handle: Any,
    scope: str,
    test: Any,
    index: _SelectorIndex,
    parent: _WalkContext,
    apply: bool,
    path: tuple[int, ...] = (),
) -> None:
    index.visited_handles += 1
    typ = _string_call(handle, "type")
    name = _string_call(handle, "name")
    full_name = _optional_string_call(handle, "full_name")
    context = _source_context(handle, test, parent)
    if typ in _LEAF_TYPES["assertion"]:
        names = {candidate for candidate in (name, full_name) if candidate}
        keys = (
            ("assertion", scope, source_file, context.source_line,
             assertion_name, _ASSERT_KINDS[typ])
            for source_file in _path_suffixes(context.source_file)
            for assertion_name in names
        )
        index.observe(index.candidate_ids(keys), handle, test, apply, {
            "root": "metric", "scope": scope, "metric": "assert",
            "path": list(path), "type": typ, "name": name,
        })
    for child_index, child in enumerate(_handles(handle, "child_handles")):
        try:
            _walk_assertion(child, scope, test, index, context, apply, (*path, child_index))
        finally:
            _release(child)


def _replay_document(db: Any, test: Any, index: _SelectorIndex) -> None:
    roots: Dict[tuple[Any, ...], Json] = {}
    for record in index.records:
        locator = record.locator
        if locator is None:
            continue
        root_key = (
            locator["root"], locator.get("scope", ""), locator.get("metric", ""),
        )
        node = roots.setdefault(root_key, {"children": {}, "records": []})
        for child_index in locator["path"]:
            node = node["children"].setdefault(
                child_index, {"children": {}, "records": []},
            )
        node["records"].append(record.record_id)

    for (root_kind, scope, metric), trie in roots.items():
        current = None
        try:
            if root_kind == "instance":
                current = _optional_call(db, "handle_by_name", scope)
            elif root_kind == "functional":
                current = _optional_call(test, "testbench_metric_handle")
            else:
                instance = _optional_call(db, "handle_by_name", scope)
                if not instance:
                    continue
                try:
                    current = _optional_call(instance, _METRIC_METHODS[metric])
                finally:
                    _release(instance)
            if not current:
                continue
            _replay_trie(current, trie, test, index)
        finally:
            if current:
                _release(current)


def _replay_trie(handle: Any, trie: Json, test: Any, index: _SelectorIndex) -> None:
    index.visited_handles += 1
    typ = _string_call(handle, "type")
    name = _string_call(handle, "name")
    for record_id in trie["records"]:
        locator = index.records[record_id].locator
        if locator and typ == locator["type"] and name == locator["name"]:
            index.observe((record_id,), handle, test, True, locator)
    if not trie["children"]:
        return
    children = _handles(handle, "child_handles")
    try:
        for child_index, child_trie in trie["children"].items():
            if 0 <= child_index < len(children):
                _replay_trie(children[child_index], child_trie, test, index)
    finally:
        for child in children:
            _release(child)


def _require_exclusion_success(
    operation: str,
    value: Any,
    path: str | None = None,
) -> None:
    if value == 1:
        return
    suffix = f": {path}" if path is not None else ""
    raise CoverageExclusionError(f"pynpi {operation} returned failure{suffix}")
