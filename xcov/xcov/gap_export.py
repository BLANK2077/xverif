"""Structured assertion and functional coverage gap artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import re
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
        })
    source_files = sorted({
        str((gap.get("evidence") or {}).get("file"))
        for gap in gaps if (gap.get("evidence") or {}).get("file")
    })
    return {
        "artifact_format": f"xcov_{metric}_gaps.v1",
        "metric": metric,
        "exclusion_locator": {
            "version": "xcov.urg_semantic.v1",
            "vdb": str(Path(vdb).resolve()),
        },
        "source_files": source_files,
        "gap_count": len(gaps),
        "gaps": gaps,
    }


def parse_urg_gap_report(metric: str, report_path: str | Path) -> List[Json]:
    """Parse URG text detail without importing or invoking pynpi."""
    path = Path(report_path)
    text = path.read_text(encoding="utf-8", errors="strict")
    if metric == "assert":
        return _parse_assert_gaps(text)
    if metric == "functional":
        return _parse_functional_gaps(text)
    raise ValueError(f"unsupported URG gap metric: {metric}")


def _parse_assert_gaps(text: str) -> List[Json]:
    rows: List[Json] = []
    sections = (
        ("Assertions Uncovered:", "npiCovAssert"),
        ("Cover Properties Uncovered:", "npiCovCoverProperty"),
        ("Cover Sequences Uncovered:", "npiCovCoverSequence"),
    )
    for heading, kind in sections:
        start = text.find(heading)
        if start < 0:
            continue
        end_match = re.search(r"^-{20,}\s*$", text[start:], re.MULTILINE)
        end = start + end_match.start() if end_match else len(text)
        for line in text[start + len(heading):end].splitlines():
            fields = line.split()
            if len(fields) < 5 or not fields[0].startswith(("top.", "top::")):
                continue
            numeric = fields[1:]
            if not all(value.isdigit() for value in numeric):
                continue
            full_name = fields[0]
            scope, name = full_name.rsplit(".", 1)
            count = int(numeric[-3]) if kind == "npiCovAssert" else int(numeric[-2])
            rows.append({
                "metric": "assert",
                "type": kind,
                "scope": scope,
                "name": name,
                "full_name": full_name,
                "covered": 0,
                "coverable": 1,
                "count": count,
                "evidence": {},
            })
    return rows


def _parse_functional_gaps(text: str) -> List[Json]:
    rows: List[Json] = []
    headers = list(re.finditer(
        r"^Group(?: Instance)? :\s*(\S.*?)\s*$",
        text,
        re.MULTILINE,
    ))
    for index, header in enumerate(headers):
        block_end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[header.end():block_end]
        # Skip the short preamble before URG repeats the first real block.
        if "Summary for " not in block:
            continue
        identity = header.group(1).strip()
        group_match = re.search(r"(?:^|\s)(\S+::\S+_cg|\S+::\S+)\s*$", block, re.MULTILINE)
        covergroup = group_match.group(1) if group_match else identity
        scope = covergroup.split("::", 1)[0] if "::" in covergroup else ""
        if "." in identity and "::" not in identity:
            scope = identity.rsplit(".", 1)[0]
        source_match = re.search(
            r"^Source File\(s\)\s*:\s*\n+(\S+)",
            block,
            re.MULTILINE,
        )
        evidence = {"file": source_match.group(1), "line": None} if source_match else {}
        summaries = list(re.finditer(
            r"^Summary for (Variable|Cross)\s+(\S+)\s*$",
            block,
            re.MULTILINE,
        ))
        for summary_index, summary in enumerate(summaries):
            section_end = (
                summaries[summary_index + 1].start()
                if summary_index + 1 < len(summaries) else len(block)
            )
            section = block[summary.end():section_end]
            marker = re.search(r"^Uncovered bins\s*$", section, re.MULTILINE)
            if not marker:
                continue
            lines = section[marker.end():].splitlines()
            table_header = next((pos for pos, line in enumerate(lines) if "COUNT" in line and "AT LEAST" in line), None)
            if table_header is None:
                continue
            object_name = summary.group(2)
            for line in lines[table_header + 1:]:
                stripped = line.strip()
                if not stripped:
                    continue
                if set(stripped) <= {"-", " "}:
                    break
                fields = stripped.split()
                if len(fields) < 4 or not all(value.isdigit() for value in fields[-3:]):
                    continue
                bin_name = " ".join(fields[:-3])
                count = int(fields[-3])
                full_name = ".".join(
                    value for value in (scope, covergroup, object_name, bin_name) if value
                )
                row = {
                    "metric": "functional",
                    "type": "npiCovCoverBin",
                    "scope": scope or None,
                    "name": bin_name,
                    "full_name": full_name,
                    "covergroup": covergroup,
                    "coverpoint": object_name if summary.group(1) == "Variable" else None,
                    "cross": object_name if summary.group(1) == "Cross" else None,
                    "bin": bin_name,
                    "covered": 0,
                    "coverable": 1,
                    "count": count,
                    "evidence": evidence,
                }
                rows.append(row)
    # URG may emit both covergroup-type and group-instance views of the same
    # semantic bin. Preserve distinct scopes but remove exact duplicate views.
    unique: Dict[tuple[Any, ...], Json] = {}
    for row in rows:
        key = (
            row.get("scope"), row.get("covergroup"), row.get("coverpoint"),
            row.get("cross"), row.get("bin"), row.get("full_name"),
        )
        unique.setdefault(key, row)
    return list(unique.values())


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
