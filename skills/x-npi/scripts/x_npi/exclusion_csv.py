"""Strict, portable CSV sidecars for x-npi exclusion workflows."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List


Json = Dict[str, Any]
KINDS = ("code", "functional", "assertion", "container")
FILE_NAMES = {
    "code": "code_exclusions.csv",
    "functional": "functional_exclusions.csv",
    "assertion": "assertion_exclusions.csv",
    "container": "container_exclusions.csv",
}
SCHEMA_VERSIONS = {
    "code": "xcov-code-exclusions.v1",
    "functional": "xcov-functional-exclusions.v1",
    "assertion": "xcov-assertion-exclusions.v1",
    "container": "xcov-container-exclusions.v1",
}
FIELDS = {
    "code": ("scope", "metric", "line", "object", "bin", "reason"),
    "functional": (
        "scope", "line", "covergroup", "coverpoint", "cross", "bin", "reason",
    ),
    "assertion": ("scope", "line", "assertion", "assertion_kind", "reason"),
    "container": (
        "target_kind", "scope", "covergroup", "item", "expansion_root", "reason",
    ),
}
CODE_METRICS = ("line", "toggle", "branch", "condition", "fsm")
ASSERTION_KINDS = ("assertion", "cover_property", "cover_sequence")
CONTAINER_KINDS = ("instance", "covergroup", "coverpoint", "cross")
MAX_CSV_BYTES = 64 * 1024 * 1024
MAX_CSV_RECORDS = 100_000
MAX_CSV_FIELD_CHARS = 16 * 1024


class ExclusionCsvError(ValueError):
    def __init__(self, message: str, *, path: Path | None = None, line: int = 0):
        super().__init__(message)
        self.path = path
        self.line = line


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
    documents = []
    for kind, path in exclusion_paths(directory).items():
        if kind == "container" and not path.exists():
            documents.append(ExclusionDocument(kind, path, []))
        else:
            documents.append(parse_document(path, kind))
    return documents


def validate_directory(directory: str | os.PathLike[str]) -> List[Json]:
    return [
        {
            "coverage_kind": document.kind,
            "path": str(document.path),
            "group_count": len(document.groups),
            "record_count": document.row_count,
            "status": "valid",
        }
        for document in parse_directory(directory)
    ]


def parse_document(path: Path, expected_kind: str) -> ExclusionDocument:
    if expected_kind not in KINDS:
        raise ExclusionCsvError(f"unknown coverage kind {expected_kind!r}")
    if not path.is_file() or path.is_symlink():
        raise ExclusionCsvError("exclusion CSV does not exist or is a symlink", path=path)
    if path.stat().st_size > MAX_CSV_BYTES:
        raise ExclusionCsvError("exclusion CSV exceeds 64 MiB", path=path)
    entries = _logical_entries(path.read_text(encoding="utf-8"), path)
    metadata: Json = {}
    header: List[str] | None = None
    groups: List[ExclusionGroup] = []
    current: ExclusionGroup | None = None
    seen_files: set[str] = set()
    seen_rows: set[tuple[str, ...]] = set()
    for entry_kind, payload, line_no in entries:
        if entry_kind == "meta":
            key, value = payload
            if key in ("schema_version", "coverage_kind"):
                if header is not None or groups or current is not None:
                    _error(path, line_no, f"{key} must precede the CSV header")
                if key in metadata:
                    _error(path, line_no, f"duplicate metadata key {key!r}")
                metadata[key] = value
            elif key == "source_file":
                if header is None:
                    _error(path, line_no, "source_file must follow the CSV header")
                source = Path(value)
                if (
                    not value or source.is_absolute() or any(part == ".." for part in source.parts)
                ):
                    _error(path, line_no, "source_file must be a portable relative path")
                if value in seen_files:
                    _error(path, line_no, "source_file group is not contiguous")
                current = ExclusionGroup(value, [])
                groups.append(current)
                seen_files.add(value)
            else:
                _error(path, line_no, f"unknown metadata key {key!r}")
            continue
        record = _parse_csv_record(payload, path, line_no)
        if header is None:
            header = record
            expected = list(FIELDS[expected_kind])
            if header != expected:
                _error(path, line_no, f"header must be exactly {expected!r}")
            continue
        if current is None and expected_kind == "container":
            current = ExclusionGroup("", [])
            groups.append(current)
        if current is None:
            _error(path, line_no, "data row requires a source_file group")
        if len(record) != len(header):
            _error(path, line_no, "data row field count does not match header")
        row = dict(zip(header, record))
        _validate_row(path, line_no, expected_kind, row)
        identity = (current.source_file, *record[:-1])
        if identity in seen_rows:
            _error(path, line_no, "duplicate exclusion identity")
        seen_rows.add(identity)
        row["_source_file"] = current.source_file
        row["_line_no"] = line_no
        current.rows.append(row)
    if header is None:
        _error(path, 0, "missing CSV header")
    if metadata.get("schema_version") != SCHEMA_VERSIONS[expected_kind]:
        _error(path, 0, "schema_version does not match file kind")
    if metadata.get("coverage_kind") != expected_kind:
        _error(path, 0, "coverage_kind does not match file kind")
    if any(not group.rows for group in groups):
        _error(path, 0, "empty source_file groups are not allowed")
    return ExclusionDocument(expected_kind, path, groups)


def _logical_entries(text: str, path: Path) -> List[tuple[str, Any, int]]:
    entries: List[tuple[str, Any, int]] = []
    buffer: List[str] = []
    start_line = 0
    quoted = False
    records = 0
    for line_no, physical in enumerate(text.splitlines(keepends=True), 1):
        if not buffer and not physical.strip():
            continue
        if not buffer and physical.lstrip().startswith("#"):
            metadata = physical.lstrip()[1:].strip()
            if not metadata or "=" not in metadata:
                continue
            key, value = metadata.split("=", 1)
            entries.append(("meta", (key.strip(), value.strip()), line_no))
            continue
        if not buffer:
            start_line = line_no
        buffer.append(physical)
        quoted = _advance_quote_state(physical, quoted)
        if not quoted:
            entries.append(("csv", "".join(buffer), start_line))
            buffer = []
            records += 1
            if records > MAX_CSV_RECORDS:
                _error(path, line_no, "exclusion CSV exceeds 100000 records")
    if buffer or quoted:
        _error(path, start_line, "unterminated quoted CSV field")
    return entries


def _advance_quote_state(text: str, quoted: bool) -> bool:
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
        records = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        _error(path, line_no, str(exc))
    if len(records) != 1:
        _error(path, line_no, "expected one logical CSV record")
    for field in records[0]:
        if len(field) > MAX_CSV_FIELD_CHARS:
            _error(path, line_no, "CSV field exceeds 16384 characters")
    return records[0]


def _validate_row(path: Path, line_no: int, kind: str, row: Json) -> None:
    if not row["reason"].strip():
        _error(path, line_no, "reason is required")
    if not row["scope"].strip():
        _error(path, line_no, "scope is required")
    if kind == "container":
        target_kind = row["target_kind"]
        if target_kind not in CONTAINER_KINDS:
            _error(path, line_no, f"target_kind must be one of {CONTAINER_KINDS!r}")
        covergroup = row["covergroup"].strip()
        item = row["item"].strip()
        expansion_root = row["expansion_root"].strip()
        if target_kind == "instance":
            if covergroup or item:
                _error(path, line_no, "instance requires empty covergroup and item")
            if not expansion_root:
                _error(path, line_no, "instance requires expansion_root")
        else:
            if not covergroup:
                _error(path, line_no, f"{target_kind} requires covergroup")
            if expansion_root:
                _error(path, line_no, f"{target_kind} requires empty expansion_root")
            if target_kind == "covergroup" and item:
                _error(path, line_no, "covergroup requires empty item")
            if target_kind in {"coverpoint", "cross"} and not item:
                _error(path, line_no, f"{target_kind} requires item")
        return
    line_text = row["line"].strip()
    if not (kind == "code" and row.get("metric") == "toggle" and not line_text):
        try:
            line = int(line_text)
        except ValueError:
            _error(path, line_no, "line must be a positive integer")
        if line <= 0 or str(line) != line_text:
            _error(path, line_no, "line must be a canonical positive integer")
    if kind == "code":
        metric = row["metric"]
        if metric not in CODE_METRICS:
            _error(path, line_no, f"metric must be one of {CODE_METRICS!r}")
        required = {
            "line": (),
            "toggle": ("object", "bin"),
            "branch": ("object", "bin"),
            "condition": ("object", "bin"),
            "fsm": ("object", "bin"),
        }[metric]
        for field in required:
            if not row[field].strip():
                _error(path, line_no, f"{metric} requires {field}")
        if metric == "line" and (row["object"].strip() or row["bin"].strip()):
            _error(path, line_no, "line requires empty object and bin")
    elif kind == "functional":
        if not row["covergroup"].strip() or not row["bin"].strip():
            _error(path, line_no, "functional requires covergroup and bin")
        if bool(row["coverpoint"].strip()) == bool(row["cross"].strip()):
            _error(path, line_no, "functional requires exactly one coverpoint or cross")
    else:
        if not row["assertion"].strip():
            _error(path, line_no, "assertion is required")
        if row["assertion_kind"] not in ASSERTION_KINDS:
            _error(path, line_no, f"assertion_kind must be one of {ASSERTION_KINDS!r}")


def format_document(document: ExclusionDocument) -> str:
    output = io.StringIO(newline="")
    output.write(f"# schema_version={SCHEMA_VERSIONS[document.kind]}\n")
    output.write(f"# coverage_kind={document.kind}\n")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(FIELDS[document.kind])
    sort_fields = {
        "code": ("scope", "line", "metric", "object", "bin"),
        "functional": ("scope", "line", "covergroup", "coverpoint", "cross", "bin"),
        "assertion": ("scope", "line", "assertion", "assertion_kind"),
        "container": ("target_kind", "scope", "covergroup", "item", "expansion_root"),
    }[document.kind]
    for group in sorted(document.groups, key=lambda value: value.source_file):
        if document.kind != "container":
            output.write("\n")
            output.write(f"# source_file={group.source_file}\n")
        for row in sorted(group.rows, key=lambda value: tuple(
            int(value[key]) if key == "line" and value[key] else 0 if key == "line" else value[key]
            for key in sort_fields
        )):
            writer.writerow([row[field] for field in FIELDS[document.kind]])
    return output.getvalue()


def format_directory(directory: str | os.PathLike[str], *, write: bool = False) -> List[Json]:
    documents = parse_directory(directory)
    formatted = {document.kind: format_document(document) for document in documents}
    changed = {
        document.kind: (
            not document.path.exists()
            or document.path.read_text(encoding="utf-8") != formatted[document.kind]
        )
        for document in documents
    }
    if write and any(changed.values()):
        root = Path(directory).resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix=".x-npi-csv-format-", dir=root) as temp:
            stage = Path(temp)
            backups: Dict[str, Path] = {}
            replaced: List[str] = []
            try:
                for document in documents:
                    if not changed[document.kind]:
                        continue
                    staged = stage / FILE_NAMES[document.kind]
                    staged.write_text(formatted[document.kind], encoding="utf-8")
                    backup = stage / f"{FILE_NAMES[document.kind]}.previous"
                    if document.path.exists():
                        os.replace(document.path, backup)
                        backups[document.kind] = backup
                    os.replace(staged, document.path)
                    replaced.append(document.kind)
            except Exception:
                for document in reversed(documents):
                    if document.kind in replaced and document.path.exists():
                        document.path.unlink()
                    if document.kind in backups:
                        os.replace(backups[document.kind], document.path)
                raise
    return [
        {
            "path": str(document.path),
            "status": (
                "formatted" if write and changed[document.kind]
                else "needs_format" if changed[document.kind]
                else "current"
            ),
        }
        for document in documents
    ]


def _error(path: Path, line: int, message: str) -> None:
    raise ExclusionCsvError(message, path=path, line=line)
