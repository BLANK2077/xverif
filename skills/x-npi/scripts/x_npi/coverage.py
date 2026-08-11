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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Protocol, Sequence

if TYPE_CHECKING:
    from .exclusion_csv import ExclusionDocument


Json = Dict[str, Any]


class CoverageExclusionError(RuntimeError):
    """Raised when a native pynpi exclusion operation fails."""


class ExclusionTargetContext(Protocol):
    """A resolver-owned, short-lived exact NPI target handle context."""

    def __enter__(self) -> Any: ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool | None: ...


TargetResolver = Callable[[str, str, Json], ExclusionTargetContext]


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
    test: Any,
    csv_directory: str | os.PathLike[str],
    output_directory: str | os.PathLike[str],
    resolve_target: TargetResolver,
) -> List[Json]:
    """Compile strict three-file CSV sidecars into opaque per-kind EL files.

    ``resolve_target(kind, source_file, row)`` must return a context manager
    yielding exactly one freshly traversed NPI score handle. The compiler never
    caches handles across rows. A resolver must fail on zero/ambiguous matches.
    Any failure restores the baseline native exclusion state and publishes no
    new EL set. CSV ``reason`` remains only in CSV and is never written to EL.
    """

    from .exclusion_csv import parse_directory

    documents = parse_directory(csv_directory)
    output_root = Path(output_directory).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".x-npi-csv-el-", dir=output_root) as temp:
        stage = Path(temp)
        baseline = stage / "baseline.el"
        save_exclusion_file(test, baseline)
        staged: Dict[str, Path] = {}
        try:
            unload_exclusions(test)
            for document in documents:
                _apply_document(test, document, resolve_target)
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
            for kind in ("code", "functional", "assertion")
        }
        backups: Dict[str, Path] = {}
        replaced: List[str] = []
        try:
            for kind in ("code", "functional", "assertion"):
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
                [destinations[kind] for kind in ("code", "functional", "assertion")],
            )
        except Exception:
            for kind in reversed(("code", "functional", "assertion")):
                destination = destinations[kind]
                if kind in replaced and destination.exists():
                    destination.unlink()
                if kind in backups:
                    os.replace(backups[kind], destination)
            unload_exclusions(test)
            load_exclusion_files(test, [baseline])
            raise
    return [
        {"coverage_kind": kind, "path": str(destinations[kind]), "status": "published"}
        for kind in ("code", "functional", "assertion")
    ]


def _apply_document(
    test: Any,
    document: ExclusionDocument,
    resolve_target: TargetResolver,
) -> None:
    for group in document.groups:
        for row in group.rows:
            context = resolve_target(document.kind, group.source_file, dict(row))
            if not hasattr(context, "__enter__") or not hasattr(context, "__exit__"):
                raise CoverageExclusionError(
                    "resolve_target must return a handle context manager"
                )
            with context as target:
                if target is None:
                    raise CoverageExclusionError("resolver returned no exclusion target")
                result = set_report_time_excluded(target, test, True)
                if result["status"] not in {"changed", "already_in_state"}:
                    raise CoverageExclusionError(
                        f"failed to apply {document.kind} exclusion: {result['status']}"
                    )


def _require_exclusion_success(
    operation: str,
    value: Any,
    path: str | None = None,
) -> None:
    if value == 1:
        return
    suffix = f": {path}" if path is not None else ""
    raise CoverageExclusionError(f"pynpi {operation} returned failure{suffix}")
