"""Structured assertion and functional coverage gap artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

Json = Dict[str, Any]


def build_gap_payload(metric: str, vdb: str, rows: Iterable[Json]) -> Json:
    prefix = "A" if metric == "assert" else "FC"
    leaf_type = "npiCovCoverBin" if metric == "functional" else None
    gaps: List[Json] = []
    for row in rows:
        if leaf_type and row.get("type") != leaf_type:
            continue
        if int(row.get("coverable") or 0) <= int(row.get("covered") or 0):
            continue
        targets = row.get("_exclude_targets")
        if not isinstance(targets, list) or not targets:
            continue
        gaps.append({
            "gap_id": f"{prefix}{len(gaps) + 1:04d}",
            "scope": row.get("scope"),
            "kind": row.get("type"),
            "name": row.get("name"),
            "full_name": row.get("full_name"),
            "covergroup": row.get("covergroup"),
            "coverpoint": row.get("coverpoint"),
            "cross": row.get("cross"),
            "bin": row.get("bin"),
            "covered": row.get("covered"),
            "coverable": row.get("coverable"),
            "count": row.get("count"),
            "evidence": row.get("evidence") or {},
            "_exclude_targets": targets,
        })
    source_files = sorted({
        str((gap.get("evidence") or {}).get("file"))
        for gap in gaps if (gap.get("evidence") or {}).get("file")
    })
    return {
        "artifact_format": f"xcov_{metric}_gaps.v1",
        "metric": metric,
        "exclusion_locator": {"version": "xcov.npi_path.v1", "vdb": vdb},
        "source_files": source_files,
        "gap_count": len(gaps),
        "gaps": gaps,
    }


def write_gap_artifacts(output_dir: str, metric: str, payload: Json) -> Json:
    root = Path(output_dir)
    json_path = root / f"{metric}.json"
    xout_path = root / f"{metric}.xout"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["gap_id", "scope", "kind", "name", "covergroup", "coverpoint", "cross", "bin", "covered", "coverable"]
    lines = ["\t".join(columns)]
    for gap in payload["gaps"]:
        lines.append("\t".join("" if gap.get(key) is None else str(gap[key]) for key in columns))
    xout_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"metric": metric, "json": str(json_path), "xout": str(xout_path), "gap_count": payload["gap_count"]}
