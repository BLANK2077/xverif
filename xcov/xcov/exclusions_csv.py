from __future__ import annotations

import csv
from dataclasses import dataclass
from copy import deepcopy
import io
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Iterable, List, Sequence

from .coverage_contract import coverage_ref_for_row, is_score_bearing_row
from .errors import XcovError
from .limits import (
    MAX_CSV_BYTES,
    MAX_CSV_FIELD_CHARS,
    MAX_CSV_RECORDS,
)

Json = Dict[str, Any]

KINDS = ("code", "functional", "assertion")
FILE_NAMES = {
    "code": "code_exclusions.csv",
    "functional": "functional_exclusions.csv",
    "assertion": "assertion_exclusions.csv",
}
SCHEMA_VERSIONS = {
    "code": "xcov-code-exclusions.v1",
    "functional": "xcov-functional-exclusions.v1",
    "assertion": "xcov-assertion-exclusions.v1",
}
FIELDS = {
    "code": ("scope", "metric", "line", "object", "bin", "reason"),
    "functional": (
        "scope",
        "line",
        "covergroup",
        "coverpoint",
        "cross",
        "bin",
        "reason",
    ),
    "assertion": (
        "scope",
        "line",
        "assertion",
        "assertion_kind",
        "reason",
    ),
}
CODE_METRICS = ("line", "toggle", "branch", "condition", "fsm")
ASSERTION_KINDS = ("assertion", "cover_property", "cover_sequence")


@dataclass
class ExclusionGroup:
    source_file: str
    rows: List[Json]


@dataclass
class ExclusionDocument:
    kind: str
    path: Path
    groups: List[ExclusionGroup]

    @property
    def row_count(self) -> int:
        return sum(len(group.rows) for group in self.groups)


def exclusion_paths(directory: str | os.PathLike[str]) -> Dict[str, Path]:
    root = Path(directory)
    return {kind: root / name for kind, name in FILE_NAMES.items()}


def parse_directory(directory: str | os.PathLike[str]) -> List[ExclusionDocument]:
    return [
        parse_document(path, kind)
        for kind, path in exclusion_paths(directory).items()
    ]


def parse_document(path: Path, expected_kind: str) -> ExclusionDocument:
    if not path.is_file() or path.is_symlink():
        raise XcovError(
            "EXCLUSION_CSV_NOT_FOUND",
            "exclusion CSV does not exist",
            path=str(path),
        )
    size = path.stat().st_size
    if size > MAX_CSV_BYTES:
        raise XcovError(
            "RESOURCE_BUDGET_EXCEEDED",
            "exclusion CSV exceeds the byte budget",
            resource_kind="csv_bytes",
            resource_count=size,
            max_resource_count=MAX_CSV_BYTES,
        )
    entries = _logical_entries(path.read_text(encoding="utf-8"))
    metadata: Json = {}
    header: List[str] | None = None
    groups: List[ExclusionGroup] = []
    current: ExclusionGroup | None = None
    seen_files: set[str] = set()
    seen_rows: set[tuple[str, ...]] = set()

    for kind, payload, line_no in entries:
        if kind == "meta":
            key, value = payload
            if key in ("schema_version", "coverage_kind"):
                if header is not None or groups or current is not None:
                    _csv_error(path, line_no, f"{key} must precede the CSV header")
                if key in metadata:
                    _csv_error(path, line_no, f"duplicate metadata key {key!r}")
                metadata[key] = value
            elif key == "source_file":
                if header is None:
                    _csv_error(path, line_no, "source_file must follow the CSV header")
                if value in seen_files:
                    _csv_error(path, line_no, "source_file group is not contiguous")
                source_path = Path(value)
                if (
                    not value
                    or source_path.is_absolute()
                    or any(part == ".." for part in source_path.parts)
                ):
                    _csv_error(
                        path,
                        line_no,
                        "source_file must be a non-empty portable relative path",
                    )
                current = ExclusionGroup(value, [])
                groups.append(current)
                seen_files.add(value)
            else:
                _csv_error(path, line_no, f"unknown metadata key {key!r}")
            continue

        row = _parse_csv_record(payload, path, line_no)
        if header is None:
            header = row
            expected_header = list(FIELDS[expected_kind])
            if header != expected_header:
                _csv_error(
                    path,
                    line_no,
                    f"header must be exactly {expected_header!r}",
                )
            continue
        if current is None:
            _csv_error(path, line_no, "data row requires a source_file group")
        if len(row) != len(header):
            _csv_error(path, line_no, "data row field count does not match header")
        item = dict(zip(header, row))
        _validate_row(path, line_no, expected_kind, item)
        identity = (current.source_file, *row[:-1])
        if identity in seen_rows:
            _csv_error(path, line_no, "duplicate exclusion")
        seen_rows.add(identity)
        item["_source_file"] = current.source_file
        item["_line_no"] = line_no
        current.rows.append(item)

    if header is None:
        _csv_error(path, 0, "missing CSV header")
    if metadata.get("schema_version") != SCHEMA_VERSIONS[expected_kind]:
        _csv_error(path, 0, "schema_version does not match file kind")
    if metadata.get("coverage_kind") != expected_kind:
        _csv_error(path, 0, "coverage_kind does not match file kind")
    if any(not group.rows for group in groups):
        _csv_error(path, 0, "empty source_file groups are not allowed")
    return ExclusionDocument(expected_kind, path, groups)


def _logical_entries(text: str) -> List[tuple[str, Any, int]]:
    entries: List[tuple[str, Any, int]] = []
    buffer: List[str] = []
    start_line = 0
    in_quotes = False
    record_count = 0
    for line_no, physical in enumerate(text.splitlines(keepends=True), 1):
        if not buffer and not physical.strip():
            continue
        if not buffer and physical.lstrip().startswith("#"):
            meta = physical.lstrip()[1:].strip()
            if not meta:
                continue
            if "=" not in meta:
                continue
            key, value = meta.split("=", 1)
            entries.append(("meta", (key.strip(), value.strip()), line_no))
            continue
        if not buffer:
            start_line = line_no
        buffer.append(physical)
        in_quotes = _advance_quote_state(physical, in_quotes)
        if not in_quotes:
            entries.append(("csv", "".join(buffer), start_line))
            record_count += 1
            if record_count > MAX_CSV_RECORDS:
                raise XcovError(
                    "RESOURCE_BUDGET_EXCEEDED",
                    "exclusion CSV exceeds the record budget",
                    resource_kind="csv_records",
                    resource_count=record_count,
                    max_resource_count=MAX_CSV_RECORDS,
                )
            buffer = []
    if buffer or in_quotes:
        raise XcovError(
            "EXCLUSION_CSV_INVALID",
            "unterminated quoted CSV field",
            line=start_line,
        )
    return entries


def _advance_quote_state(text: str, quoted: bool) -> bool:
    """Scan only newly received characters; never rescan the full buffer."""

    index = 0
    while index < len(text):
        if text[index] == '"':
            if quoted and index + 1 < len(text) and text[index + 1] == '"':
                index += 2
                continue
            quoted = not quoted
        index += 1
    return quoted


def _parse_csv_record(text: str, path: Path, line_no: int) -> List[str]:
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        _csv_error(path, line_no, str(exc))
    if len(rows) != 1:
        _csv_error(path, line_no, "expected one logical CSV record")
    oversized = [index for index, field in enumerate(rows[0]) if len(field) > MAX_CSV_FIELD_CHARS]
    if oversized:
        raise XcovError(
            "RESOURCE_BUDGET_EXCEEDED",
            "exclusion CSV field exceeds the character budget",
            resource_kind="csv_field_chars",
            resource_count=len(rows[0][oversized[0]]),
            max_resource_count=MAX_CSV_FIELD_CHARS,
        )
    return rows[0]


def _validate_row(path: Path, line_no: int, kind: str, row: Json) -> None:
    if not row["reason"].strip():
        _csv_error(path, line_no, "reason is required")
    if not row["scope"].strip():
        _csv_error(path, line_no, "scope is required")
    line_text = row["line"].strip()
    if not (kind == "code" and row.get("metric") == "toggle" and not line_text):
        try:
            line = int(line_text)
        except ValueError:
            _csv_error(path, line_no, "line must be a positive integer")
        if line <= 0 or str(line) != line_text:
            _csv_error(path, line_no, "line must be a canonical positive integer")
    if kind == "code":
        metric = row["metric"]
        if metric not in CODE_METRICS:
            _csv_error(path, line_no, f"metric must be one of {CODE_METRICS!r}")
        required = {
            "line": (),
            "toggle": ("object", "bin"),
            "branch": ("object", "bin"),
            "condition": ("object", "bin"),
            "fsm": ("object", "bin"),
        }[metric]
        forbidden = {"line": ("object", "bin")}.get(metric, ())
        for field in required:
            if not row[field].strip():
                _csv_error(path, line_no, f"{metric} requires {field}")
        for field in forbidden:
            if row[field].strip():
                _csv_error(path, line_no, f"{metric} requires empty {field}")
    elif kind == "functional":
        if not row["covergroup"].strip() or not row["bin"].strip():
            _csv_error(path, line_no, "functional exclusion requires covergroup and bin")
        if bool(row["coverpoint"].strip()) == bool(row["cross"].strip()):
            _csv_error(
                path,
                line_no,
                "functional exclusion requires exactly one of coverpoint or cross",
            )
    else:
        if not row["assertion"].strip():
            _csv_error(path, line_no, "assertion is required")
        if row["assertion_kind"] not in ASSERTION_KINDS:
            _csv_error(
                path,
                line_no,
                f"assertion_kind must be one of {ASSERTION_KINDS!r}",
            )


def _csv_error(path: Path, line: int, message: str) -> None:
    raise XcovError(
        "EXCLUSION_CSV_INVALID",
        message,
        path=str(path),
        line=line,
    )


def resolve_documents(
    documents: Sequence[ExclusionDocument],
    coverage_rows: Sequence[Json],
) -> List[Json]:
    score_rows = [row for row in coverage_rows if is_score_bearing_row(row)]
    results: List[Json] = []
    for document in documents:
        for group in document.groups:
            for record in group.rows:
                matches = [
                    row
                    for row in score_rows
                    if _matches(document.kind, record, row)
                ]
                status = (
                    "matched"
                    if len(matches) == 1
                    else "missing"
                    if not matches
                    else "ambiguous"
                )
                if len(matches) == 1:
                    matched = matches[0]
                    validity = (
                        "now_covered"
                        if (
                            isinstance(matched.get("covered"), int)
                            and isinstance(matched.get("coverable"), int)
                            and matched["coverable"] > 0
                            and matched["covered"] >= matched["coverable"]
                        )
                        else "still_valid"
                    )
                elif not matches:
                    validity = "coverage_object_missing"
                else:
                    validity = "ambiguous"
                result = {
                    "coverage_kind": document.kind,
                    "source_file": group.source_file,
                    "csv_line": record["_line_no"],
                    "status": status,
                    "validity": validity,
                    "match_count": len(matches),
                    "reason": record["reason"],
                    "coverage_refs": [
                        row.get("coverage_ref") or coverage_ref_for_row(row)
                        for row in matches
                    ],
                }
                results.append(result)
    return results


def _matches(kind: str, record: Json, row: Json) -> bool:
    evidence = row.get("evidence") or {}
    if row.get("scope") != record["scope"]:
        return False
    if kind == "code":
        metric = record["metric"]
        if row.get("metric") != metric:
            return False
        if metric != "toggle" and (
            evidence.get("line") != int(record["line"])
            or not _file_matches(evidence.get("file"), record["_source_file"])
        ):
            return False
        if metric == "line":
            return True
        object_fields = {
            "toggle": ("toggle_bit", "toggle_signal"),
            "branch": ("branch",),
            "condition": ("condition",),
            "fsm": ("fsm", "full_name", "name"),
        }[metric]
        bin_fields = {
            "toggle": ("toggle_transition", "name"),
            "branch": ("branch_bin", "name"),
            "condition": ("condition_bin", "name"),
            "fsm": ("name", "value"),
        }[metric]
        return (
            record["object"] in {str(row.get(key, "")) for key in object_fields}
            and record["bin"] in {str(row.get(key, "")) for key in bin_fields}
        )
    if (
        evidence.get("line") != int(record["line"])
        or not _file_matches(evidence.get("file"), record["_source_file"])
    ):
        return False
    if kind == "functional":
        return (
            row.get("metric") == "functional"
            and row.get("type") == "npiCovCoverBin"
            and row.get("covergroup") == record["covergroup"]
            and (row.get("coverpoint") or "") == record["coverpoint"]
            and (row.get("cross") or "") == record["cross"]
            and row.get("bin") == record["bin"]
        )
    return (
        row.get("metric") == "assert"
        and row.get("assert_kind") == record["assertion_kind"]
        and record["assertion"]
        in {row.get("name"), row.get("assert_object"), row.get("full_name")}
    )


def _file_matches(actual: Any, requested: str) -> bool:
    if not isinstance(actual, str) or not actual:
        return False
    return actual == requested or actual.endswith("/" + requested)


def format_document(document: ExclusionDocument) -> str:
    output = io.StringIO(newline="")
    output.write(f"# schema_version={SCHEMA_VERSIONS[document.kind]}\n")
    output.write(f"# coverage_kind={document.kind}\n")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(FIELDS[document.kind])
    groups = sorted(document.groups, key=lambda group: group.source_file)
    sort_fields = {
        "code": ("scope", "line", "metric", "object", "bin"),
        "functional": (
            "scope",
            "line",
            "covergroup",
            "coverpoint",
            "cross",
            "bin",
        ),
        "assertion": ("scope", "line", "assertion", "assertion_kind"),
    }[document.kind]
    for group in groups:
        output.write("\n")
        output.write(f"# source_file={group.source_file}\n")
        for row in sorted(
            group.rows,
            key=lambda item: tuple(
                int(item[key]) if key == "line" and item[key] else 0 if key == "line" else item[key]
                for key in sort_fields
            ),
        ):
            writer.writerow([row[field] for field in FIELDS[document.kind]])
    return output.getvalue()


def format_directory(directory: str, write: bool = False) -> List[Json]:
    documents = parse_directory(directory)
    formatted_by_kind: Dict[str, str] = {}
    changed_by_kind: Dict[str, bool] = {}
    for document in documents:
        formatted = format_document(document)
        formatted_by_kind[document.kind] = formatted
        changed_by_kind[document.kind] = (
            document.path.read_text(encoding="utf-8") != formatted
        )

    if write and any(changed_by_kind.values()):
        root = Path(directory).resolve(strict=True)
        with tempfile.TemporaryDirectory(
            prefix=".xcov-csv-format-", dir=str(root),
        ) as temporary:
            stage = Path(temporary)
            staged: Dict[str, Path] = {}
            backups: Dict[str, Path] = {}
            replaced: list[str] = []
            try:
                for document in documents:
                    if not changed_by_kind[document.kind]:
                        continue
                    staged_path = stage / FILE_NAMES[document.kind]
                    staged_path.write_text(
                        formatted_by_kind[document.kind], encoding="utf-8",
                    )
                    with staged_path.open("rb") as stream:
                        os.fsync(stream.fileno())
                    staged[document.kind] = staged_path
                for document in documents:
                    kind = document.kind
                    if kind not in staged:
                        continue
                    backup = stage / f"{FILE_NAMES[kind]}.previous"
                    os.replace(document.path, backup)
                    backups[kind] = backup
                    os.replace(staged[kind], document.path)
                    replaced.append(kind)
                descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except Exception:
                for document in reversed(documents):
                    kind = document.kind
                    if kind in replaced and document.path.exists():
                        document.path.unlink()
                    if kind in backups:
                        os.replace(backups[kind], document.path)
                raise

    results: List[Json] = []
    for document in documents:
        changed = changed_by_kind[document.kind]
        results.append({
            "path": str(document.path),
            "status": "formatted" if write and changed else "needs_format" if changed else "current",
        })
    return results
