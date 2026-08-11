"""Strict run-manifest validation for coverage database inputs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import struct
from typing import Any, Dict

from .errors import XcovError
from .protocol import strict_json_loads
from .schemas import SchemaValidationError, validate_run_manifest_document

Json = Dict[str, Any]

RESOURCE_HASH_VERSION = "sha256-entry-tree-v2"
_HASH_DOMAIN = b"xcov.resource.v2\0"


def _canonical(path: str) -> Path:
    try:
        return Path(path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise XcovError(
            "RESOURCE_PROVENANCE_MISMATCH",
            "run manifest is missing or cannot be resolved",
        ) from exc


def _file_digest(path: Path) -> tuple[bytes, int]:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"resource entry is not a regular file: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    after = path.stat(follow_symlinks=False)
    if _stat_changed(before, after):
        raise OSError(f"resource changed while it was hashed: {path}")
    return digest.digest(), size


def _stat_changed(before: os.stat_result, after: os.stat_result) -> bool:
    stable_fields = (
        "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
    )
    return any(getattr(before, key) != getattr(after, key) for key in stable_fields)


def _update_entry(
    digest: "hashlib._Hash",
    entry_type: bytes,
    relative: bytes,
    size: int,
    entry_digest: bytes,
) -> None:
    """Append one unambiguous length-prefixed tree entry."""

    digest.update(entry_type)
    digest.update(struct.pack(">Q", len(relative)))
    digest.update(relative)
    digest.update(struct.pack(">Q", size))
    digest.update(struct.pack(">Q", len(entry_digest)))
    digest.update(entry_digest)


def resource_identity(path: Path) -> Json:
    """Return the strict v2 identity for a regular file or directory tree.

    Symlinks are hashed by link target and never followed; special files are
    rejected. ``size_bytes`` is the sum of regular-file bytes, never a
    directory inode size. Every visited directory and symlink is checked again
    after traversal so a mixed concurrent tree snapshot fails closed.
    """

    path = Path(path)
    top = path.stat(follow_symlinks=False)
    digest = hashlib.sha256()
    digest.update(_HASH_DOMAIN)
    if stat.S_ISREG(top.st_mode):
        content_digest, size = _file_digest(path)
        _update_entry(digest, b"F", b"", size, content_digest)
        return {
            "kind": "file",
            "hash_version": RESOURCE_HASH_VERSION,
            "size_bytes": size,
            "file_count": 1,
            "directory_count": 0,
            "symlink_count": 0,
            "sha256": digest.hexdigest(),
        }
    if not stat.S_ISDIR(top.st_mode):
        raise OSError(f"resource is neither a regular file nor a directory: {path}")

    entries: list[tuple[bytes, bytes, int, bytes]] = []
    pending = [path]
    directory_snapshots: list[tuple[Path, os.stat_result]] = []
    directory_count = 1
    file_count = 0
    symlink_count = 0
    total_size = 0
    while pending:
        directory = pending.pop()
        directory_before = directory.stat(follow_symlinks=False)
        if not stat.S_ISDIR(directory_before.st_mode):
            raise OSError(f"resource directory changed during hashing: {directory}")
        directory_snapshots.append((directory, directory_before))
        with os.scandir(directory) as iterator:
            for entry in iterator:
                resource = Path(entry.path)
                relative = os.fsencode(os.path.relpath(resource, path))
                entry_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    target = os.fsencode(os.readlink(resource))
                    link_after = resource.stat(follow_symlinks=False)
                    if _stat_changed(entry_stat, link_after):
                        raise OSError(
                            f"resource symlink changed while it was hashed: {resource}"
                        )
                    entries.append((b"L", relative, len(target), hashlib.sha256(target).digest()))
                    symlink_count += 1
                    continue
                if stat.S_ISDIR(entry_stat.st_mode):
                    entries.append((b"D", relative, 0, b""))
                    directory_count += 1
                    pending.append(resource)
                    continue
                if not stat.S_ISREG(entry_stat.st_mode):
                    raise OSError(f"resource tree contains a special file: {resource}")
                content_digest, size = _file_digest(resource)
                entries.append((b"F", relative, size, content_digest))
                file_count += 1
                total_size += size

    for directory, before in directory_snapshots:
        after = directory.stat(follow_symlinks=False)
        if _stat_changed(before, after):
            raise OSError(
                f"resource directory changed while it was hashed: {directory}"
            )

    for entry_type, relative, size, entry_digest in sorted(
        entries, key=lambda item: (item[1], item[0]),
    ):
        _update_entry(digest, entry_type, relative, size, entry_digest)
    return {
        "kind": "directory",
        "hash_version": RESOURCE_HASH_VERSION,
        "size_bytes": total_size,
        "file_count": file_count,
        "directory_count": directory_count,
        "symlink_count": symlink_count,
        "sha256": digest.hexdigest(),
    }


def resource_sha256(path: Path) -> str:
    """Return the unambiguous digest used by ``xcov.run-manifest.v2``."""

    return str(resource_identity(path)["sha256"])


def _mismatch(message: str) -> XcovError:
    """Create a closed public provenance error without echoing input data."""

    return XcovError("RESOURCE_PROVENANCE_MISMATCH", message)


def validate_run_manifest(target: Json) -> Json | None:
    """Validate optional ``xcov.run-manifest.v2`` against ``target.vdb``."""

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

    declared = details["resources"]["vdb"]
    vdb = target.get("vdb")
    if not isinstance(vdb, str) or not vdb:
        raise _mismatch("target.vdb is required when run_manifest is provided")
    expected_path = _canonical(str(manifest_path.parent / declared["path"]))
    actual_path = _canonical(vdb)
    if expected_path != actual_path:
        raise _mismatch("run manifest resource path does not match target: vdb")
    try:
        actual_identity = resource_identity(actual_path)
    except OSError as exc:
        raise _mismatch("run manifest resource cannot be hashed: vdb") from exc
    for field in (
        "kind", "hash_version", "size_bytes", "file_count",
        "directory_count", "symlink_count", "sha256",
    ):
        if actual_identity[field] != declared[field]:
            raise _mismatch(
                f"run manifest resource {field} does not match target: vdb"
            )
    details["manifest_path"] = str(manifest_path)
    return details
