"""Content-addressed, process-safe cache for the fixed URG summary report."""

from __future__ import annotations

import functools
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

from .eda import get_urg_path
from .errors import XcovError
from .provenance import resource_sha256
from .urg_runner import UrgRunner
from .urg_summary import (
    REQUIRED_ARTIFACTS,
    UrgSummaryIndex,
    parse_urg_summary,
    validate_summary_artifacts,
)

Json = Dict[str, Any]

CACHE_SCHEMA_VERSION = "xcov.urg-summary-cache.v1"
PARSER_SCHEMA_VERSION = "xcov.urg-summary-ir.v1"
CACHE_CAPACITY_CONTRACT = "best_effort_soft_admission"
FIXED_SUMMARY_OPTIONS = (
    "-xml_verbose", "-format", "text", "-show", "summary",
)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 128
ABANDONED_STAGING_SECONDS = 24 * 60 * 60
KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def default_cache_root() -> Path:
    configured = os.environ.get("XVERIF_XCOV_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve() / "urg-summary"
    return Path.cwd().resolve() / ".xverif" / "xcov" / "cache" / "urg-summary"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@functools.lru_cache(maxsize=8)
def _probe_urg(path_text: str, size_bytes: int, mtime_ns: int) -> Json:
    path = Path(path_text)
    try:
        completed = subprocess.run(
            [path_text, "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            "failed to query the configured URG version",
        ) from exc
    combined = completed.stdout + completed.stderr
    version_line = next(
        (line.strip() for line in combined.splitlines() if "URG Version " in line),
        None,
    )
    covdb_line = next(
        (line.strip() for line in combined.splitlines() if line.startswith("CovDB version:")),
        None,
    )
    if completed.returncode != 0 or not version_line or not covdb_line:
        raise XcovError(
            "EDA_PROVENANCE_INVALID",
            "configured URG did not return a canonical version response",
        )
    release = version_line.split("URG Version ", 1)[1].split("Copyright", 1)[0].strip()
    return {
        "path": path_text,
        "release": release,
        "covdb_version": covdb_line.split(":", 1)[1].strip(),
        "binary_sha256": _file_sha256(path),
        "version_output_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        "size_bytes": size_bytes,
        "mtime_ns": mtime_ns,
    }


def _urg_identity() -> Json:
    path = Path(get_urg_path()).resolve(strict=True)
    stat = path.stat()
    return _probe_urg(str(path), stat.st_size, stat.st_mtime_ns)


def _cache_identity(
    vdb: str,
    el_path: Optional[str],
    run_manifest_digest: Optional[str],
) -> Json:
    canonical_vdb = Path(vdb).resolve(strict=True)
    if not canonical_vdb.is_dir():
        raise XcovError("VDB_OPEN_FAILED", "coverage database is not a directory", vdb=vdb)
    exclusion = None
    if el_path:
        canonical_el = Path(el_path).resolve(strict=True)
        exclusion = {
            "sha256": _file_sha256(canonical_el),
            "size_bytes": canonical_el.stat().st_size,
        }
    return {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "parser_schema": PARSER_SCHEMA_VERSION,
        "vdb_sha256": resource_sha256(canonical_vdb),
        "urg": _urg_identity(),
        "options": list(FIXED_SUMMARY_OPTIONS),
        "merged_selection": "merged",
        "run_manifest_sha256": run_manifest_digest,
        "exclusion": exclusion,
    }


def _identity_key(identity: Json) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_metadata(report: Path) -> Json:
    paths = validate_summary_artifacts(report)
    return {
        name: {
            "size_bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for name, path in sorted(paths.items())
    }


def _semantic_counts(index: UrgSummaryIndex) -> Json:
    return {
        "metric_count": len(index.metric_names),
        "test_count": len(index.tests),
        "scope_count": len(index.scopes),
        "functional_row_count": len(index.functional_rows),
        "assertion_row_count": len(index.assertion_rows),
    }


def _read_manifest(path: Path) -> Json | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_valid_entry(
    entry: Path,
    identity: Json,
    key: str,
) -> UrgSummaryIndex | None:
    manifest = _read_manifest(entry / "manifest.json")
    if manifest is None:
        return None
    try:
        complete_value = (entry / "COMPLETE").read_text(
            encoding="ascii", errors="ignore"
        ).strip()
    except OSError:
        return None
    if (
        manifest.get("schema_version") != CACHE_SCHEMA_VERSION
        or manifest.get("key") != key
        or manifest.get("identity") != identity
        or manifest.get("complete") is not True
        or complete_value != key
    ):
        return None
    try:
        artifacts = _artifact_metadata(entry / "report")
        index = parse_urg_summary(entry / "report")
    except (OSError, XcovError):
        return None
    if artifacts != manifest.get("artifacts"):
        return None
    if _semantic_counts(index) != manifest.get("semantic_counts"):
        return None
    return index


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _configured_limit(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise XcovError("XCOV_CACHE_CONFIG_INVALID", f"{name} must be an integer") from exc
    if value <= 0:
        raise XcovError("XCOV_CACHE_CONFIG_INVALID", f"{name} must be greater than zero")
    return value


def _tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _cleanup_abandoned_staging(staging: Path) -> None:
    cutoff = time.time() - ABANDONED_STAGING_SECONDS
    for candidate in staging.iterdir():
        if not candidate.is_dir() or candidate.stat().st_mtime >= cutoff:
            continue
        if candidate.parent != staging or not KEY_PATTERN.match(candidate.name[:64]):
            continue
        if candidate.exists():
            shutil.rmtree(candidate)


def _enforce_soft_capacity_before_build(root: Path) -> None:
    """Apply a published-entry snapshot before admitting one cold build.

    This check intentionally does not serialize different cache keys or reserve
    bytes for active staging directories. Distinct-key builds can therefore
    oversubscribe the configured thresholds when they pass the same snapshot.
    Once oversubscribed, later cold admissions fail until explicit maintenance
    removes immutable entries; warm hits remain available.
    """
    entries = root / "entries"
    max_entries = _configured_limit("XVERIF_XCOV_CACHE_MAX_ENTRIES", DEFAULT_MAX_ENTRIES)
    max_bytes = _configured_limit("XVERIF_XCOV_CACHE_MAX_BYTES", DEFAULT_MAX_BYTES)
    rows = [
        entry for entry in entries.iterdir()
        if entry.is_dir() and KEY_PATTERN.fullmatch(entry.name)
    ]
    total_bytes = sum(_tree_size(entry) for entry in rows)
    if len(rows) >= max_entries or total_bytes >= max_bytes:
        raise XcovError(
            "XCOV_CACHE_CAPACITY_EXCEEDED",
            "URG cache soft admission threshold is exhausted; remove old immutable entries in an explicit maintenance window before retrying",
            entry_count=len(rows),
            max_entries=max_entries,
            size_bytes=total_bytes,
            max_bytes=max_bytes,
        )


def _quarantine(entry: Path, quarantine_root: Path, key: str) -> None:
    quarantine_root.mkdir(parents=True, exist_ok=True)
    destination = quarantine_root / f"{key}-{time.time_ns()}-{os.getpid()}"
    os.replace(entry, destination)


def load_cached_urg_summary(
    vdb: str,
    *,
    cache_root: str | Path | None = None,
    el_path: Optional[str] = None,
    run_manifest_digest: Optional[str] = None,
    runner: Optional[UrgRunner] = None,
) -> tuple[UrgSummaryIndex, Json]:
    """Return parsed fixed-summary IR and observable cache metadata."""
    root = Path(cache_root).resolve() if cache_root else default_cache_root()
    entries = root / "entries"
    claims = root / "claims"
    staging = root / "staging"
    quarantine = root / "quarantine"
    for directory in (entries, claims, staging):
        directory.mkdir(parents=True, exist_ok=True)
    identity = _cache_identity(vdb, el_path, run_manifest_digest)
    # Validate the selected URG execution backend even on a cache hit.  A bad
    # LSF configuration must not appear healthy merely because another process
    # populated this key earlier.
    active_runner = runner or UrgRunner()
    key = _identity_key(identity)
    entry = entries / key
    claim = claims / key
    deadline = time.monotonic() + 300.0
    claimed = False
    while not claimed:
        cached_index = _read_valid_entry(entry, identity, key)
        if cached_index is not None:
            return cached_index, {
                "key": key,
                "hit": True,
                "entry": str(entry),
                "urg_execution": _cache_hit_execution(active_runner),
            }
        try:
            claim.mkdir(mode=0o700)
            claimed = True
        except FileExistsError:
            try:
                stale = time.time() - claim.stat().st_mtime > ABANDONED_STAGING_SECONDS
            except FileNotFoundError:
                continue
            if stale:
                quarantine.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(
                        claim,
                        quarantine / f"claim-{key}-{time.time_ns()}-{os.getpid()}",
                    )
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise XcovError(
                    "XCOV_CACHE_CLAIM_TIMEOUT",
                    "timed out waiting for the URG cache build owner",
                    key=key,
                )
            time.sleep(0.05)

    try:
        (claim / "owner.json").write_text(
            json.dumps(
                {"pid": os.getpid(), "created_at_unix_ns": time.time_ns()},
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        cached_index = _read_valid_entry(entry, identity, key)
        if cached_index is not None:
            return cached_index, {
                "key": key,
                "hit": True,
                "entry": str(entry),
                "urg_execution": _cache_hit_execution(active_runner),
            }
        if entry.exists():
            _quarantine(entry, quarantine, key)
        _cleanup_abandoned_staging(staging)
        _enforce_soft_capacity_before_build(root)

        with tempfile.TemporaryDirectory(prefix=f"{key}.", dir=staging) as stage_name:
            stage = Path(stage_name)
            report = stage / "report"
            report.mkdir()
            argv = [
                "urg", "-full64", "-dir", str(Path(vdb).resolve()),
                "-report", str(report), *FIXED_SUMMARY_OPTIONS,
            ]
            if el_path:
                argv.extend(["-elfile", str(Path(el_path).resolve())])
            result = active_runner.run(argv, timeout=300)
            if result.returncode != 0:
                raise XcovError(
                    "URG_SUMMARY_FAILED",
                    "URG summary generation failed",
                    returncode=result.returncode,
                    stderr_tail=result.stderr[-500:],
                    urg_execution=getattr(result, "scheduler", None),
                )
            index = parse_urg_summary(report)
            artifacts = _artifact_metadata(report)
            manifest = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "key": key,
                "identity": identity,
                "artifacts": artifacts,
                "semantic_counts": _semantic_counts(index),
                "generated_at_unix_ns": time.time_ns(),
                "complete": True,
            }
            manifest_tmp = stage / "manifest.json.tmp"
            manifest_tmp.write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(manifest_tmp, stage / "manifest.json")
            (stage / "COMPLETE").write_text(key + "\n", encoding="ascii")
            for artifact_name in REQUIRED_ARTIFACTS:
                _fsync_file(report / artifact_name)
            _fsync_file(stage / "manifest.json")
            _fsync_file(stage / "COMPLETE")
            _fsync_directory(report)
            _fsync_directory(stage)
            os.replace(stage, entry)
            _fsync_directory(entries)
            return index, {
                "key": key,
                "hit": False,
                "entry": str(entry),
                "urg_execution": _run_execution(result),
            }
    finally:
        shutil.rmtree(claim, ignore_errors=True)


def _cache_hit_execution(runner: Any) -> Json:
    method = getattr(runner, "cache_hit_metadata", None)
    if callable(method):
        value = method()
        if isinstance(value, dict):
            return dict(value)
    return {
        "backend": "injected",
        "submitted": False,
        "status": "cache_hit",
        "queue": None,
        "resource": None,
        "job_name": None,
        "job_id": None,
        "exit_status": None,
    }


def _run_execution(result: Any) -> Json:
    value = getattr(result, "scheduler", None)
    if isinstance(value, dict):
        return dict(value)
    return {
        "backend": "injected",
        "submitted": True,
        "status": "completed",
        "queue": None,
        "resource": None,
        "job_name": None,
        "job_id": None,
        "exit_status": getattr(result, "returncode", None),
    }
