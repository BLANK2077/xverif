from __future__ import annotations

import csv
from dataclasses import dataclass
from copy import deepcopy
import difflib
import io
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, Iterable, List, Sequence

from .coverage_contract import coverage_ref_for_row, is_score_bearing_row
from .errors import XcovError

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
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class ExclusionGroup:
    source_file: str
    source_commit: str
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
    if not path.is_file():
        raise XcovError(
            "EXCLUSION_CSV_NOT_FOUND",
            "exclusion CSV does not exist",
            path=str(path),
        )
    entries = _logical_entries(path.read_text(encoding="utf-8"))
    metadata: Json = {}
    header: List[str] | None = None
    groups: List[ExclusionGroup] = []
    current: ExclusionGroup | None = None
    seen_files: set[str] = set()
    seen_rows: set[tuple[str, ...]] = set()
    pending_file: str | None = None

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
                if pending_file is not None:
                    _csv_error(path, line_no, "source_file requires source_commit")
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
                pending_file = value
            elif key == "source_commit":
                if pending_file is None:
                    _csv_error(path, line_no, "source_commit requires source_file")
                if not SHA_RE.fullmatch(value):
                    _csv_error(path, line_no, "source_commit must be a 40-character lowercase SHA")
                current = ExclusionGroup(pending_file, value, [])
                groups.append(current)
                seen_files.add(pending_file)
                pending_file = None
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
            _csv_error(path, line_no, "data row requires a source_file/source_commit group")
        if len(row) != len(header):
            _csv_error(path, line_no, "data row field count does not match header")
        item = dict(zip(header, row))
        _validate_row(path, line_no, expected_kind, item)
        identity = (current.source_file, *row[:-1])
        if identity in seen_rows:
            _csv_error(path, line_no, "duplicate exclusion")
        seen_rows.add(identity)
        item["_source_file"] = current.source_file
        item["_source_commit"] = current.source_commit
        item["_line_no"] = line_no
        current.rows.append(item)

    if pending_file is not None:
        _csv_error(path, 0, "source_file requires source_commit")
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
        in_quotes = _quotes_open("".join(buffer))
        if not in_quotes:
            entries.append(("csv", "".join(buffer), start_line))
            buffer = []
    if buffer or in_quotes:
        raise XcovError(
            "EXCLUSION_CSV_INVALID",
            "unterminated quoted CSV field",
            line=start_line,
        )
    return entries


def _quotes_open(text: str) -> bool:
    quoted = False
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
    return rows[0]


def _validate_row(path: Path, line_no: int, kind: str, row: Json) -> None:
    if not row["reason"].strip():
        _csv_error(path, line_no, "reason is required")
    if not row["scope"].strip():
        _csv_error(path, line_no, "scope is required")
    try:
        line = int(row["line"])
    except ValueError:
        _csv_error(path, line_no, "line must be a positive integer")
    if line <= 0 or str(line) != row["line"].strip():
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
                    "source_commit": group.source_commit,
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
    if (
        row.get("scope") != record["scope"]
        or evidence.get("line") != int(record["line"])
        or not _file_matches(evidence.get("file"), record["_source_file"])
    ):
        return False
    if kind == "code":
        metric = record["metric"]
        if row.get("metric") != metric:
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
        output.write(f"# source_commit={group.source_commit}\n")
        for row in sorted(
            group.rows,
            key=lambda item: tuple(
                int(item[key]) if key == "line" else item[key]
                for key in sort_fields
            ),
        ):
            writer.writerow([row[field] for field in FIELDS[document.kind]])
    return output.getvalue()


def format_directory(directory: str, write: bool = False) -> List[Json]:
    results: List[Json] = []
    for document in parse_directory(directory):
        formatted = format_document(document)
        current = document.path.read_text(encoding="utf-8")
        changed = current != formatted
        if write and changed:
            document.path.write_text(formatted, encoding="utf-8")
        results.append({
            "path": str(document.path),
            "status": "formatted" if write and changed else "needs_format" if changed else "current",
        })
    return results


def git_group_status(
    documents: Sequence[ExclusionDocument],
    repo_root: str,
) -> List[Json]:
    root = Path(repo_root).resolve()
    results: List[Json] = []
    for document in documents:
        for group in document.groups:
            results.append(_one_git_group_status(root, document.kind, group))
    return results


def _one_git_group_status(root: Path, kind: str, group: ExclusionGroup) -> Json:
    _git(root, "cat-file", "-e", f"{group.source_commit}^{{commit}}")
    source = root / group.source_file
    dirty = bool(_git(root, "status", "--porcelain", "--", group.source_file).strip())
    current_commit = _git(
        root,
        "log",
        "-1",
        "--format=%H",
        "--",
        group.source_file,
    ).strip() or None
    status = "current"
    renamed_to = None
    line_map: Dict[int, int] = {}
    if dirty:
        status = "worktree_dirty"
    elif not source.exists():
        renamed_to = _unique_rename(root, group.source_commit, group.source_file)
        status = "file_renamed" if renamed_to else "file_deleted"
    else:
        old = _git_bytes(root, "show", f"{group.source_commit}:{group.source_file}")
        new = source.read_bytes()
        if old == new:
            status = (
                "current"
                if current_commit == group.source_commit
                else "commit_changed_content_equal"
            )
        else:
            line_map = _equal_line_map(old, new)
            relevant = [int(row["line"]) for row in group.rows]
            if relevant and all(line in line_map for line in relevant):
                status = "line_shifted"
            else:
                status = "content_changed"
    return {
        "coverage_kind": kind,
        "source_file": group.source_file,
        "source_commit": group.source_commit,
        "current_commit": current_commit,
        "status": status,
        "renamed_to": renamed_to,
        "line_updates": [
            {"old_line": old, "new_line": line_map[old]}
            for old in sorted({int(row["line"]) for row in group.rows})
            if old in line_map and line_map[old] != old
        ],
    }


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise XcovError(
            "EXCLUSION_GIT_FAILED",
            proc.stderr.strip() or "git command failed",
            operation="git " + " ".join(args[:2]),
        )
    return proc.stdout


def _git_bytes(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise XcovError(
            "EXCLUSION_GIT_FAILED",
            proc.stderr.decode("utf-8", "replace").strip(),
            operation="git " + " ".join(args[:2]),
        )
    return proc.stdout


def _unique_rename(root: Path, commit: str, source_file: str) -> str | None:
    output = _git(
        root,
        "diff",
        "--find-renames",
        "--name-status",
        f"{commit}...HEAD",
    )
    candidates = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[0].startswith("R") and fields[1] == source_file:
            candidates.append(fields[2])
    return candidates[0] if len(candidates) == 1 else None


def _equal_line_map(old: bytes, new: bytes) -> Dict[int, int]:
    old_lines = old.decode("utf-8", "replace").splitlines()
    new_lines = new.decode("utf-8", "replace").splitlines()
    mapping: Dict[int, int] = {}
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset + 1] = block.b + offset + 1
    return mapping


def rebase_suggestions(
    documents: Sequence[ExclusionDocument],
    repo_root: str,
) -> List[Json]:
    statuses = git_group_status(documents, repo_root)
    suggestions: List[Json] = []
    for status in statuses:
        if status["status"] == "file_renamed":
            suggestions.append({
                **status,
                "action": "rename_source_file",
                "automatic": True,
            })
        elif status["status"] == "line_shifted":
            suggestions.append({
                **status,
                "action": "update_line_numbers",
                "automatic": True,
            })
        elif status["status"] in ("content_changed", "file_deleted"):
            suggestions.append({
                **status,
                "action": "manual_review",
                "automatic": False,
            })
    return suggestions


def suggested_patches(
    documents: Sequence[ExclusionDocument],
    suggestions: Sequence[Json],
) -> List[Json]:
    by_group = {
        (row["coverage_kind"], row["source_file"]): row
        for row in suggestions
        if row.get("automatic")
    }
    patches: List[Json] = []
    for document in documents:
        updated = deepcopy(document)
        changed = False
        for group in updated.groups:
            suggestion = by_group.get((document.kind, group.source_file))
            if not suggestion:
                continue
            if suggestion["action"] == "rename_source_file":
                group.source_file = suggestion["renamed_to"]
                for row in group.rows:
                    row["_source_file"] = group.source_file
                changed = True
            elif suggestion["action"] == "update_line_numbers":
                mapping = {
                    item["old_line"]: item["new_line"]
                    for item in suggestion["line_updates"]
                }
                for row in group.rows:
                    old_line = int(row["line"])
                    if old_line in mapping:
                        row["line"] = str(mapping[old_line])
                        changed = True
        if not changed:
            continue
        before = document.path.read_text(encoding="utf-8").splitlines(keepends=True)
        after = format_document(updated).splitlines(keepends=True)
        patch = "".join(difflib.unified_diff(
            before,
            after,
            fromfile=str(document.path),
            tofile=str(document.path),
        ))
        patches.append({
            "coverage_kind": document.kind,
            "path": str(document.path),
            "status": "suggested_patch",
            "patch": patch,
        })
    return patches


def apply_rebase_suggestions(
    documents: Sequence[ExclusionDocument],
    suggestions: Sequence[Json],
) -> List[Json]:
    by_group = {
        (row["coverage_kind"], row["source_file"]): row
        for row in suggestions
        if row.get("automatic")
    }
    results: List[Json] = []
    for document in documents:
        changed = False
        for group in document.groups:
            suggestion = by_group.get((document.kind, group.source_file))
            if not suggestion:
                continue
            if suggestion["action"] == "rename_source_file":
                group.source_file = suggestion["renamed_to"]
                for row in group.rows:
                    row["_source_file"] = group.source_file
                changed = True
            elif suggestion["action"] == "update_line_numbers":
                mapping = {
                    item["old_line"]: item["new_line"]
                    for item in suggestion["line_updates"]
                }
                for row in group.rows:
                    old_line = int(row["line"])
                    if old_line in mapping:
                        row["line"] = str(mapping[old_line])
                        changed = True
        if changed:
            document.path.write_text(format_document(document), encoding="utf-8")
            results.append({
                "coverage_kind": document.kind,
                "path": str(document.path),
                "status": "rebased",
            })
    return results


def stamp_documents(
    documents: Sequence[ExclusionDocument],
    repo_root: str,
    resolution_rows: Sequence[Json],
) -> List[Json]:
    root = Path(repo_root).resolve()
    resolved = {
        (row["coverage_kind"], row["source_file"])
        for row in resolution_rows
        if row["status"] == "matched"
    }
    failed = {
        (row["coverage_kind"], row["source_file"])
        for row in resolution_rows
        if row["status"] != "matched"
    }
    results: List[Json] = []
    for document in documents:
        changed = False
        for group in document.groups:
            key = (document.kind, group.source_file)
            status = _one_git_group_status(root, document.kind, group)
            if key not in resolved or key in failed:
                results.append({**status, "stamp_status": "not_verified"})
                continue
            if status["status"] == "worktree_dirty":
                results.append({**status, "stamp_status": "worktree_dirty"})
                continue
            current_commit = status["current_commit"]
            if not current_commit:
                results.append({**status, "stamp_status": "no_current_commit"})
                continue
            if group.source_commit != current_commit:
                group.source_commit = current_commit
                changed = True
                results.append({**status, "stamp_status": "stamped"})
            else:
                results.append({**status, "stamp_status": "unchanged"})
        if changed:
            document.path.write_text(format_document(document), encoding="utf-8")
    return results


def review_markdown(
    statuses: Sequence[Json],
    resolutions: Sequence[Json] = (),
) -> str:
    by_file: Dict[str, List[Json]] = {}
    for row in statuses:
        key = row.get("source_file") or row.get("path") or "unknown"
        by_file.setdefault(key, []).append(row)
    resolution_by_file: Dict[str, List[Json]] = {}
    for row in resolutions:
        resolution_by_file.setdefault(row["source_file"], []).append(row)
    lines = ["# Coverage exclusion review", ""]
    for source_file in sorted(set(by_file) | set(resolution_by_file)):
        lines.extend([f"## `{source_file}`", ""])
        for row in by_file.get(source_file, []):
            if row["status"] == "suggested_patch":
                lines.extend(["- Suggested patch:", "", "```diff", row["patch"].rstrip(), "```"])
            else:
                lines.append(
                    f"- Git: `{row['status']}`"
                    + (f"，rename → `{row['renamed_to']}`" if row.get("renamed_to") else "")
                )
        for row in resolution_by_file.get(source_file, []):
            lines.append(
                f"- CSV line {row['csv_line']}: `{row['status']}`"
                f" / `{row.get('validity', 'unknown')}`，{row['reason']}"
            )
        lines.append("")
    return "\n".join(lines)
