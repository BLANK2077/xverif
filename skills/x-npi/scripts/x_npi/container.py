"""Standalone exact container exclusion planning for x-npi."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .exclusion_csv import (
    ExclusionDocument,
    ExclusionGroup,
    FILE_NAMES,
    KINDS,
    format_document,
)
from .urg import UrgSummary


Json = Dict[str, Any]


def plan_container_records(
    summary: UrgSummary,
    *,
    instances: Sequence[str] = (),
    recursive_instances: Sequence[str] = (),
    covergroups: Sequence[Tuple[str, str]] = (),
    coverpoints: Sequence[Tuple[str, str, str]] = (),
    crosses: Sequence[Tuple[str, str, str]] = (),
    reason: str,
) -> List[Json]:
    """Expand requests into stable exact targets without opening pynpi."""
    if not reason.strip():
        raise ValueError("reason must be non-empty")
    rows: List[Json] = []
    for root in instances:
        rows.extend(_instance_rows(summary, root, False, reason))
    for root in recursive_instances:
        rows.extend(_instance_rows(summary, root, True, reason))
    for scope, group in covergroups:
        rows.append(_functional_row("covergroup", scope, group, "", reason))
    for scope, group, item in coverpoints:
        rows.append(_functional_row("coverpoint", scope, group, item, reason))
    for scope, group, item in crosses:
        rows.append(_functional_row("cross", scope, group, item, reason))
    if not rows:
        raise ValueError("at least one container target is required")
    unique: Dict[tuple[str, str, str, str], Json] = {}
    for row in rows:
        key = tuple(str(row[field]) for field in (
            "target_kind", "scope", "covergroup", "item",
        ))
        previous = unique.get(key)
        if previous is not None and previous != row:
            raise ValueError(f"TARGET_OWNERSHIP_CONFLICT: {key!r}")
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (
        row["target_kind"], row["scope"], row["covergroup"], row["item"],
    ))


def write_csv_set(directory: str | Path, container_rows: Iterable[Json]) -> List[str]:
    """Create missing empty leaf sidecars and atomically replace container CSV."""
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for kind in KINDS[:3]:
        path = root / FILE_NAMES[kind]
        if path.exists():
            continue
        path.write_text(format_document(ExclusionDocument(kind, path, [])), encoding="utf-8")
        written.append(str(path))
    path = root / FILE_NAMES["container"]
    document = ExclusionDocument("container", path, [
        ExclusionGroup("", [dict(row) for row in container_rows]),
    ])
    temporary = root / f".{path.name}.new"
    temporary.write_text(format_document(document), encoding="utf-8")
    temporary.replace(path)
    written.append(str(path))
    return written


def _instance_rows(summary: UrgSummary, root: str, recursive: bool, reason: str) -> List[Json]:
    return [{
        "target_kind": "instance", "scope": scope,
        "covergroup": "", "item": "", "expansion_root": root,
        "reason": reason,
    } for scope in summary.expand_xml_instances(root, recursive=recursive)]


def _functional_row(kind: str, scope: str, group: str, item: str, reason: str) -> Json:
    if not scope or not group or (kind != "covergroup" and not item):
        raise ValueError(f"incomplete {kind} selector")
    return {
        "target_kind": kind, "scope": scope, "covergroup": group,
        "item": item, "expansion_root": "", "reason": reason,
    }
