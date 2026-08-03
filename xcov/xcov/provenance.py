"""Strict run-manifest validation for coverage database inputs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict

from .errors import XcovError
from .protocol import strict_json_loads
from .schemas import SchemaValidationError, validate_run_manifest_document

Json = Dict[str, Any]


def _canonical(path: str) -> Path:
    try:
        return Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise XcovError("RESOURCE_PROVENANCE_MISMATCH",
                        "run manifest is missing or cannot be resolved") from exc


def _hash_file(path: Path, digest: "hashlib._Hash") -> None:
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)


def resource_sha256(path: Path) -> str:
    """Return the content digest used by ``xcov.run-manifest.v1``.

    Files hash their bytes. Directories use a deterministic, sorted tree hash
    over relative names, entry types, and file bytes, so a VDB directory is
    represented by its content rather than by volatile metadata.
    """
    digest = hashlib.sha256()
    if path.is_file():
        _hash_file(path, digest)
        return digest.hexdigest()
    if not path.is_dir():
        raise OSError(f"resource is neither a file nor a directory: {path}")
    for root, dirs, files in os.walk(path):
        root_path = Path(root)
        dirs.sort()
        files.sort()
        for name in dirs:
            relative = (root_path / name).relative_to(path).as_posix()
            digest.update(b"D\\0" + relative.encode("utf-8") + b"\\0")
        for name in files:
            resource = root_path / name
            relative = resource.relative_to(path).as_posix()
            digest.update(b"F\\0" + relative.encode("utf-8") + b"\\0")
            _hash_file(resource, digest)
    return digest.hexdigest()


def _mismatch(message: str) -> XcovError:
    """Create a closed public provenance error.

    The manifest is an input document, not a public error-detail contract.
    Publishing it verbatim made the response shape depend on arbitrary input
    keys and could disclose unrelated run metadata.
    """

    return XcovError("RESOURCE_PROVENANCE_MISMATCH", message)


def validate_run_manifest(target: Json) -> Json | None:
    """Validate optional ``xcov.run-manifest.v1`` against ``target.vdb``.

    The declared resource path is relative to the manifest file.  A mismatch
    raises before the caller opens the VDB/NPI backend.
    """
    run_manifest = target.get("run_manifest")
    if run_manifest is None:
        return None
    if not isinstance(run_manifest, str) or not run_manifest:
        raise _mismatch("target.run_manifest must be a non-empty path")
    manifest_path = _canonical(run_manifest)
    try:
        details: Any = strict_json_loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _mismatch("run manifest is not valid JSON") from exc
    try:
        details = validate_run_manifest_document(details)
    except SchemaValidationError as exc:
        raise _mismatch(
            f"run manifest violates the closed contract at {exc.path}: "
            f"{exc.message}"
        ) from exc

    resources = details.get("resources")
    declared = resources["vdb"]
    relative = declared.get("path")
    size = declared.get("size_bytes")
    expected_sha = declared.get("sha256")

    vdb = target.get("vdb")
    if not isinstance(vdb, str) or not vdb:
        raise _mismatch(
            "target.vdb is required when run_manifest is provided"
        )
    expected_path = _canonical(str(manifest_path.parent / relative))
    actual_path = _canonical(vdb)
    if expected_path != actual_path:
        raise _mismatch(
            "run manifest resource path does not match target: vdb"
        )
    actual_size = actual_path.stat().st_size
    if actual_size != size:
        raise _mismatch(
            "run manifest resource size does not match target: vdb"
        )
    try:
        actual_sha = resource_sha256(actual_path)
    except OSError as exc:
        raise _mismatch(
            "run manifest resource cannot be hashed: vdb"
        ) from exc
    if actual_sha != expected_sha:
        raise _mismatch(
            "run manifest resource SHA-256 does not match target: vdb"
        )
    details["manifest_path"] = str(manifest_path)
    return details
