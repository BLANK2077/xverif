"""Strict single-instance URG code-coverage artifact conversion."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


Json = Dict[str, Any]
PUBLIC_METRICS = ("line", "condition", "branch", "toggle", "fsm")
URG_METRICS = {
    "line": "line",
    "condition": "cond",
    "branch": "branch",
    "toggle": "tgl",
    "fsm": "fsm",
}
_HEADINGS = {
    "line": "Line",
    "condition": "Cond",
    "branch": "Branch",
    "toggle": "Toggle",
    "fsm": "FSM",
}


class CoverageExportParseError(RuntimeError):
    def __init__(self, metric: str, scope: str, reason: str) -> None:
        super().__init__(reason)
        self.metric = metric
        self.scope = scope
        self.reason = reason


def _instance_has_no_self_metric(text: str, scope: str) -> bool:
    header = re.search(rf"^Module Instance : {re.escape(scope)}\s*$", text, re.MULTILINE)
    if not header:
        return False
    following = re.search(r"^={8,}\nModule : \S+", text[header.end():], re.MULTILINE)
    block = text[header.end():header.end() + following.start() if following else len(text)]
    return bool(re.search(r"^Instance\s*:\s*\n(?:.*\n){0,4}\s*(?:--\s+)+\s*$", block, re.MULTILINE))


def _module_has_only_target(text: str, module: str, scope: str) -> bool:
    header = re.search(rf"^Module : {re.escape(module)}\s*$", text, re.MULTILINE)
    if not header:
        return False
    following = re.search(r"^={8,}\nModule : \S+", text[header.end():], re.MULTILINE)
    block = text[header.end():header.end() + following.start() if following else len(text)]
    table = re.search(r"^Module self-instances\s*:\s*$", block, re.MULTILINE)
    if not table:
        return False
    end = re.search(r"^-{8,}\s*$", block[table.end():], re.MULTILINE)
    rows = block[table.end():table.end() + end.start() if end else len(block)]
    instances = re.findall(r"(?:^|\s)(top(?:\.\S+)+)\s*$", rows, re.MULTILINE)
    return instances == [scope]


def _section(text: str, metric: str, scope: str, module: str) -> str:
    heading = _HEADINGS[metric]
    pattern = re.compile(
        rf"^{heading} Coverage for Instance : {re.escape(scope)}\s*$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        if _instance_has_no_self_metric(text, scope):
            return ""
        if module == "unknown" or not _module_has_only_target(text, module, scope):
            raise CoverageExportParseError(metric, scope, "target instance detail section is missing")
        pattern = re.compile(
            rf"^{heading} Coverage for Module : {re.escape(module)}(?:\s|\().*$",
            re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            raise CoverageExportParseError(metric, scope, "exact target module detail is missing")
    following = re.search(
        r"^(?:={8,}|Module(?: Instance)? :|(?:Line|Cond|Branch|Toggle|FSM) Coverage for (?:Module|Instance) :)\s*",
        text[match.end():],
        re.MULTILINE,
    )
    end = match.end() + following.start() if following else len(text)
    return text[match.end():end]


def _module_name(text: str, scope: str) -> str:
    headers = list(re.finditer(r"^Module : (\S+)\s*$", text, re.MULTILINE))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[header.end():end]
        table = re.search(r"^Module self-instances\s*:\s*$", block, re.MULTILINE)
        if table and re.search(rf"(?:^|\s){re.escape(scope)}(?:\s|$)", block[table.end():]):
            return header.group(1)
    return "unknown"


def _source_files(text: str, module: str) -> List[str]:
    if module == "unknown":
        return sorted(set(re.findall(r"^(/\S+\.(?:sv|svh|v|vh))$", text, re.MULTILINE)))
    header = re.search(rf"^Module : {re.escape(module)}(?:\s|$)", text, re.MULTILINE)
    if not header:
        return []
    following = re.search(r"^Module(?: Instance)? :", text[header.end():], re.MULTILINE)
    block = text[header.end():header.end() + following.start() if following else len(text)]
    return sorted(set(re.findall(r"^(/\S+\.(?:sv|svh|v|vh))$", block, re.MULTILINE)))


def _source_context(files: List[str]) -> Tuple[str, List[str]]:
    if not files:
        return "", []
    root = os.path.commonpath([os.path.dirname(path) for path in files])
    return root, [os.path.relpath(path, root) for path in files]


def _at(source_files: List[str], line: int | None) -> str | None:
    if line is None or not source_files:
        return None
    return f"{source_files[0]}:{line}"


def _coverage(section: str, metric: str) -> Json:
    if not section:
        return {"covered": 0, "coverable": 0, "missing": 0, "pct": 0.0}
    patterns = {
        "line": r"^TOTAL\s+(\d+)\s+(\d+)\s+([\d.]+)",
        "condition": r"^Conditions\s+(\d+)\s+(\d+)\s+([\d.]+)",
        "branch": r"^Branches\s+(\d+)\s+(\d+)\s+([\d.]+)",
        "toggle": r"^Total Bits\s+(\d+)\s+(\d+)\s+([\d.]+)",
        "fsm": r"^Transitions\s+(\d+)\s+(\d+)\s+([\d.]+)",
    }
    match = re.search(patterns[metric], section, re.MULTILINE)
    if not match:
        raise CoverageExportParseError(metric, "", "coverage total is missing")
    coverable, covered = int(match.group(1)), int(match.group(2))
    return {
        "covered": covered,
        "coverable": coverable,
        "missing": coverable - covered,
        "pct": round(float(match.group(3)), 2),
    }


def _logical_terms(expression: str) -> List[str]:
    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    terms = [part.strip().strip("() ") for part in re.split(r"\s*(?:&&|\|\|)\s*", value)]
    return [term for term in terms if term]


def _not_covered_vectors(block: str) -> Tuple[List[int], List[List[str]]]:
    header = re.search(r"^\s*((?:-\d+-\s+)+)Status\s*$", block, re.MULTILINE)
    if not header:
        return [], []
    ids = [int(value) for value in re.findall(r"-(\d+)-", header.group(1))]
    rows: List[List[str]] = []
    for line in block[header.end():].splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) == {"-"}:
            if rows:
                break
            continue
        if not stripped.endswith("Not Covered"):
            continue
        values = stripped.removesuffix("Not Covered").split()
        if len(values) == len(ids):
            rows.append(values)
    return ids, rows


def _strip_balanced_outer_parens(value: str) -> str:
    result = value.strip()
    while result.startswith("(") and result.endswith(")"):
        depth = 0
        encloses_all = True
        for index, char in enumerate(result):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(result) - 1:
                    encloses_all = False
                    break
        if not encloses_all or depth != 0:
            break
        result = result[1:-1].strip()
    return result


def _condition_terms(label_line: str, annotation_line: str, ids: List[int]) -> List[Json]:
    label = re.match(r"^\s*(?:EXPRESSION|SUB-EXPRESSION)\s+(.+)$", label_line)
    if not label:
        raise CoverageExportParseError("condition", "", "condition expression label is missing")
    expression = label.group(1)
    expression_column = label.start(1)
    spans = list(re.finditer(r"-+(\d+)-+", annotation_line))
    by_id: Dict[int, str] = {}
    for span in spans:
        start = max(0, span.start() - expression_column)
        end = max(start, span.end() - expression_column)
        term = _strip_balanced_outer_parens(expression[start:end])
        by_id[int(span.group(1))] = term
    if any(term_id not in by_id or not by_id[term_id] for term_id in ids):
        raise CoverageExportParseError("condition", "", "condition marker cannot be mapped to expression")
    return [{"marker": f"-{term_id}-", "expression": by_id[term_id]} for term_id in ids]


def _condition_groups(section: str, source_files: List[str]) -> Tuple[List[Json], int]:
    starts = list(re.finditer(r"^\s*LINE\s+(\d+)\s*$", section, re.MULTILINE))
    groups: List[Json] = []
    by_terms: Dict[Tuple[Any, ...], Json] = {}
    coverage_object_gap_count = 0
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section)
        block = section[start.end():end]
        lines = block.splitlines()
        label_index = next((position for position, line in enumerate(lines)
                            if re.match(r"^\s*(?:EXPRESSION|SUB-EXPRESSION)\s+", line)), None)
        if label_index is None or label_index + 1 >= len(lines):
            continue
        label_line = lines[label_index]
        label = re.match(r"^\s*(EXPRESSION|SUB-EXPRESSION)\s+(.+)$", label_line)
        if not label:
            continue
        kind = label.group(1).lower().replace("-", "_")
        raw_expression = label.group(2).strip()
        ids, vectors = _not_covered_vectors(block)
        if not vectors:
            continue
        terms = _condition_terms(label_line, lines[label_index + 1], ids)
        at = _at(source_files, int(start.group(1)))
        group_key = (at, tuple((term["marker"], term["expression"]) for term in terms))
        group = by_terms.get(group_key)
        if group is None:
            group = {
                "condition": {"at": at, "expression": raw_expression},
                "terms": terms,
                "uncovered": [],
                "_by_values": {},
            }
            by_terms[group_key] = group
            groups.append(group)
        elif kind == "expression" and group["condition"]["expression"] != raw_expression:
            group["condition"]["expression"] = raw_expression
        origin = {"kind": kind, "raw_expression": raw_expression}
        for values in vectors:
            coverage_object_gap_count += 1
            values_key = tuple(values)
            row = group["_by_values"].get(values_key)
            if row is None:
                row = {"values": values, "origins": []}
                group["_by_values"][values_key] = row
                group["uncovered"].append(row)
            if origin not in row["origins"]:
                row["origins"].append(origin)
    gap_index = 1
    for group_index, group in enumerate(groups, 1):
        group["group_id"] = f"CG{group_index:04d}"
        group.pop("_by_values")
        for row in group["uncovered"]:
            row["gap_id"] = f"C{gap_index:04d}"
            gap_index += 1
    return groups, coverage_object_gap_count


def _source_statement(source_path: str | None, start_line: int) -> str:
    if not source_path or not os.path.isfile(source_path):
        raise CoverageExportParseError("branch", "", "branch ternary source file is unavailable")
    lines = Path(source_path).read_text(encoding="utf-8", errors="replace").splitlines()
    if start_line < 1 or start_line > len(lines):
        raise CoverageExportParseError("branch", "", "branch ternary source line is out of range")
    parts: List[str] = []
    for source in lines[start_line - 1:]:
        parts.append(source.strip())
        if ";" in source:
            break
    statement = " ".join(part for part in parts if part)
    if not statement or ";" not in statement:
        raise CoverageExportParseError("branch", "", "branch ternary source statement is incomplete")
    return statement


def _assignment_rhs(source: str) -> str | None:
    match = re.search(r"(?:<=|(?<![=!<>])=(?!=))\s*(.+)$", source)
    return match.group(1).strip() if match else None


def _branch_terms(block: str, source_files: List[str], absolute_sources: List[str]) -> List[Json]:
    terms: List[Json] = []
    source_lines = block.splitlines()
    prior_numbered: Tuple[int, str] | None = None
    for index, line in enumerate(source_lines):
        numbered = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if not numbered:
            continue
        line_no, source = int(numbered.group(1)), numbered.group(2).strip()
        if index + 1 >= len(source_lines):
            continue
        marker_ids = [int(value) for value in re.findall(r"-(\d+)-", source_lines[index + 1])]
        for term_id in marker_ids:
            case_match = re.search(r"\b(casez|casex|case)\s*\((.+)\)", source)
            if_match = re.search(r"\bif\s*\((.+)\)", source)
            if case_match:
                kind, expression = case_match.group(1), case_match.group(2).strip()
                at_line = line_no
                rendered_source = source
            elif if_match:
                kind, expression = "if", if_match.group(1).strip()
                at_line = line_no
                rendered_source = source
            elif "?" in source:
                before_question = source.split("?", 1)[0].strip()
                if before_question:
                    expression = before_question.strip("() ")
                    at_line = line_no
                    start_line = prior_numbered[0] if prior_numbered and prior_numbered[1].rstrip().endswith(("=", "<=", ">=")) else line_no
                elif prior_numbered:
                    expression = _assignment_rhs(prior_numbered[1]) or prior_numbered[1]
                    expression = expression.strip("() ")
                    at_line = prior_numbered[0]
                    start_line = prior_numbered[0]
                else:
                    raise CoverageExportParseError("branch", "", "branch ternary condition is missing")
                kind = "ternary"
                rendered_source = _source_statement(absolute_sources[0] if len(absolute_sources) == 1 else None, start_line)
            else:
                raise CoverageExportParseError("branch", "", "branch marker source is unsupported")
            term: Json = {
                "id": term_id,
                "marker": f"-{term_id}-",
                "kind": kind,
                "at": _at(source_files, at_line),
                "expression": expression,
                "source": rendered_source,
            }
            terms.append(term)
        prior_numbered = (line_no, source)
    unique = {item["id"]: item for item in terms}
    return [unique[key] for key in sorted(unique)]


def _branch_tables(section: str) -> List[Tuple[str, List[int], List[List[str]]]]:
    tables: List[Tuple[str, List[int], List[List[str]]]] = []
    cursor = 0
    for label in re.finditer(r"^Branches:\s*$", section, re.MULTILINE):
        source_block = section[cursor:label.start()]
        suffix = section[label.end():]
        header = re.search(r"^\s*((?:-\d+-\s+)+)Status\s*$", suffix, re.MULTILINE)
        if not header:
            raise CoverageExportParseError("branch", "", "branch status header is missing")
        ids = [int(value) for value in re.findall(r"-(\d+)-", header.group(1))]
        marker_starts = [match.start() for match in re.finditer(r"-\d+-", header.group(1))]
        vectors: List[List[str]] = []
        saw_status = False
        consumed = header.end()
        for row in re.finditer(r"^.*$", suffix[header.end():], re.MULTILINE):
            stripped = row.group(0).strip()
            consumed = header.end() + row.end()
            if not stripped:
                if saw_status:
                    break
                continue
            status = re.match(r"^(.*?)\s+(Covered|Not Covered)\s*$", stripped)
            if not status:
                if saw_status:
                    break
                continue
            saw_status = True
            value_text = status.group(1)
            values = [
                value_text[start:marker_starts[value_index + 1]].strip()
                if value_index + 1 < len(marker_starts)
                else value_text[start:].strip()
                for value_index, start in enumerate(marker_starts)
            ]
            if len(values) != len(ids):
                raise CoverageExportParseError("branch", "", "branch vector width does not match markers")
            if status.group(2) == "Not Covered":
                vectors.append(values)
        if not saw_status:
            raise CoverageExportParseError("branch", "", "branch status rows are missing")
        tables.append((source_block, ids, vectors))
        cursor = label.end() + consumed
    return tables


def _branch_groups(section: str, source_files: List[str], absolute_sources: List[str]) -> List[Json]:
    groups: List[Json] = []
    by_path: Dict[Tuple[Tuple[Any, ...], ...], Json] = {}
    for source_block, ids, vectors in _branch_tables(section):
        if not vectors:
            continue
        if len(source_files) != 1:
            raise CoverageExportParseError("branch", "", "branch source location is not unique")
        by_id = {item["id"]: item for item in _branch_terms(source_block, source_files, absolute_sources)}
        if any(term_id not in by_id for term_id in ids):
            raise CoverageExportParseError("branch", "", "branch marker cannot be mapped to source")
        path = []
        for term_id in ids:
            item = {key: by_id[term_id][key]
                    for key in ("marker", "kind", "at", "expression", "source")}
            path.append(item)
        path_key = tuple(tuple(
            item.get(key)
            for key in ("marker", "kind", "at", "expression", "source")
        ) for item in path)
        group = by_path.get(path_key)
        if group is None:
            group = {"decision_path": path, "uncovered": []}
            by_path[path_key] = group
            groups.append(group)
        group["uncovered"].extend({"values": values, "status": "not_covered"} for values in vectors)
    gap_index = 1
    for group_index, group in enumerate(groups, 1):
        group["group_id"] = f"D{group_index:04d}"
        for row in group["uncovered"]:
            row["gap_id"] = f"B{gap_index:04d}"
            gap_index += 1
    return groups


def _line_gaps(section: str, source_files: List[str]) -> List[Json]:
    return [
        {
            "at": _at(source_files, int(match.group(1))),
            "statement": match.group(2).strip(),
            "hits": 0,
            "required": "execute this statement",
        }
        for match in re.finditer(r"^\s*(\d+)\s+0/\d+\s+==>\s+(.+)$", section, re.MULTILINE)
    ]


def _line_groups(section: str, source_files: List[str]) -> List[Json]:
    contexts: List[Json] = []
    for match in re.finditer(
        r"^\s*([A-Z][A-Z0-9_-]*)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s*$",
        section,
        re.MULTILINE,
    ):
        kind, line_no, coverable, covered, pct = match.groups()
        contexts.append({
            "kind": kind.lower(),
            "line": int(line_no),
            "at": _at(source_files, int(line_no)),
            "covered": int(covered),
            "coverable": int(coverable),
            "missing": int(coverable) - int(covered),
            "pct": round(float(pct), 2),
            "uncovered": [],
        })
    if not contexts:
        return []
    contexts.sort(key=lambda item: item["line"])
    gaps = _line_gaps(section, source_files)
    for gap_index, gap in enumerate(gaps, 1):
        line_no = int(str(gap["at"]).rsplit(":", 1)[1])
        owner = None
        for index, context in enumerate(contexts):
            next_line = contexts[index + 1]["line"] if index + 1 < len(contexts) else None
            if line_no >= context["line"] and (next_line is None or line_no < next_line):
                owner = context
                break
        if owner is None:
            raise CoverageExportParseError("line", "", "line gap cannot be mapped to a construct")
        owner["uncovered"].append({
            "gap_id": f"L{gap_index:04d}",
            "at": gap["at"],
            "statement": gap["statement"],
        })
    groups: List[Json] = []
    for context in contexts:
        if not context["uncovered"]:
            continue
        if len(context["uncovered"]) != context["missing"]:
            raise CoverageExportParseError("line", "", "line construct missing count does not match gaps")
        groups.append({
            "group_id": f"LG{len(groups) + 1:04d}",
            "context": {key: context[key] for key in (
                "kind", "at", "covered", "coverable", "missing", "pct"
            )},
            "uncovered": context["uncovered"],
        })
    return groups


def _toggle_gaps(section: str) -> List[Json]:
    gaps: List[Json] = []
    kind: str | None = None
    for line in section.splitlines():
        stripped = line.strip()
        if stripped == "Port Details":
            kind = "port"
            continue
        if stripped == "Signal Details":
            kind = "signal"
            continue
        if kind is None or not stripped or stripped.startswith(("Toggle ", "Direction ")):
            continue
        fields = stripped.split()
        if len(fields) < 4 or fields[1] not in {"Yes", "No"}:
            continue
        missing = []
        if fields[2] == "No":
            missing.append("1->0")
        if fields[3] == "No":
            missing.append("0->1")
        if not missing:
            continue
        gap: Json = {
            "object_kind": kind,
            "object": fields[0],
            "missing_edges": missing,
            "required": "observe every bit in this range completing the missing edges",
        }
        if kind == "port" and len(fields) > 4:
            gap["direction"] = fields[4]
        gaps.append(gap)
    return gaps


def _fsm_block_gaps(block: str, fsm: str, source_files: List[str]) -> List[Json]:
    gaps: List[Json] = []
    kind: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("states") and "line no." in lowered:
            kind = "state"
            continue
        if lowered.startswith("transitions") and "line no." in lowered:
            kind = "transition"
            continue
        if lowered.startswith("sequences") and "line no." in lowered:
            kind = "sequence"
            continue
        if kind is None or not stripped.endswith("Not Covered"):
            continue
        fields = stripped.removesuffix("Not Covered").split()
        if len(fields) < 2 or not fields[-1].isdigit():
            continue
        line_no = int(fields[-1])
        obj = " ".join(fields[:-1])
        verb = {"state": "enter", "transition": "traverse", "sequence": "observe"}[kind]
        gaps.append({
            "object_kind": kind,
            "object": obj,
            "at": _at(source_files, line_no),
        })
    return gaps


def _fsm_groups(section: str, source_files: List[str]) -> Tuple[List[Json], Json]:
    starts = list(re.finditer(r"^Summary for FSM :: (.+)$", section, re.MULTILINE))
    if not starts:
        raise CoverageExportParseError("fsm", "", "FSM summary is missing")
    groups: List[Json] = []
    total_covered = 0
    total_coverable = 0
    gap_index = 1
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(section)
        block = section[start.end():end]
        coverage_match = re.search(
            r"^Transitions\s+(\d+)\s+(\d+)\s+([\d.]+)", block, re.MULTILINE
        )
        if not coverage_match:
            raise CoverageExportParseError("fsm", "", "FSM transition coverage is missing")
        coverable, covered = int(coverage_match.group(1)), int(coverage_match.group(2))
        total_coverable += coverable
        total_covered += covered
        gaps = _fsm_block_gaps(block, start.group(1).strip(), source_files)
        for gap in gaps:
            gap["gap_id"] = f"F{gap_index:04d}"
            gap_index += 1
        if gaps:
            groups.append({
                "fsm": start.group(1).strip(),
                "transition_coverage": {
                    "covered": covered,
                    "coverable": coverable,
                    "missing": coverable - covered,
                    "pct": round(float(coverage_match.group(3)), 2),
                },
                "gaps": gaps,
            })
    missing = total_coverable - total_covered
    aggregate = {
        "covered": total_covered,
        "coverable": total_coverable,
        "missing": missing,
        "pct": round(100.0 * total_covered / total_coverable, 2) if total_coverable else 0.0,
    }
    return groups, aggregate


def _non_actionable(section: str) -> List[Json]:
    rows: List[Json] = []
    for line in section.splitlines():
        match = re.match(r"^\s*(.+?)\s+(Excluded|Unreachable|Illegal)\s*$", line, re.IGNORECASE)
        if match:
            rows.append({"object": match.group(1).strip(), "status": match.group(2).lower()})
    return rows


def parse_metric_report(text: str, scope: str, metric: str) -> Json:
    if metric not in PUBLIC_METRICS:
        raise ValueError(metric)
    module = _module_name(text, scope)
    section = _section(text, metric, scope, module)
    absolute_sources = _source_files(text, module)
    source_root, sources = _source_context(absolute_sources)
    parsers = {"toggle": lambda: _toggle_gaps(section)}
    coverage = _coverage(section, metric)
    if metric == "line":
        groups = _line_groups(section, sources)
        gap_count = sum(len(group["uncovered"]) for group in groups)
        if gap_count != coverage["missing"]:
            raise CoverageExportParseError(metric, scope, "line gap count does not match coverage missing")
        return {
            "schema": "xcov.code_coverage.line.v2",
            "scope": scope,
            "module": module,
            "source_root": source_root,
            "source_files": sources,
            "metric": metric,
            "coverage_basis": "self",
            "coverage": coverage,
            "line_group_count": len(groups),
            "gap_count": gap_count,
            "non_actionable_count": len(_non_actionable(section)),
            "analysis_complete": True,
            "line_groups": groups,
            "non_actionable": _non_actionable(section),
        }
    if metric == "condition":
        groups, coverage_object_gap_count = _condition_groups(section, sources)
        gap_count = sum(len(group["uncovered"]) for group in groups)
        if coverage_object_gap_count != coverage["missing"]:
            raise CoverageExportParseError(
                metric, scope, "condition coverage object gap count does not match coverage missing"
            )
        return {
            "schema": "xcov.code_coverage.condition.v2",
            "scope": scope,
            "module": module,
            "source_root": source_root,
            "source_files": sources,
            "metric": metric,
            "coverage_basis": "self",
            "coverage": coverage,
            "condition_group_count": len(groups),
            "coverage_object_gap_count": coverage_object_gap_count,
            "gap_count": gap_count,
            "non_actionable_count": len(_non_actionable(section)),
            "analysis_complete": True,
            "condition_groups": groups,
            "non_actionable": _non_actionable(section),
        }
    if metric == "branch":
        groups = _branch_groups(section, sources, absolute_sources)
        gap_count = sum(len(group["uncovered"]) for group in groups)
        if coverage["missing"] and not gap_count:
            raise CoverageExportParseError(metric, scope, "uncovered objects could not be resolved")
        return {
            "schema": "xcov.code_coverage.branch.v2",
            "scope": scope,
            "module": module,
            "source_root": source_root,
            "source_files": sources,
            "metric": metric,
            "coverage_basis": "self",
            "coverage": coverage,
            "decision_group_count": len(groups),
            "gap_count": gap_count,
            "non_actionable_count": len(_non_actionable(section)),
            "analysis_complete": True,
            "decision_groups": groups,
            "non_actionable": _non_actionable(section),
        }
    if metric == "fsm":
        groups, aggregate = _fsm_groups(section, sources)
        gap_count = sum(len(group["gaps"]) for group in groups)
        if aggregate["missing"] and not gap_count:
            raise CoverageExportParseError(metric, scope, "uncovered objects could not be resolved")
        return {
            "schema": "xcov.code_coverage.fsm.v2",
            "scope": scope,
            "module": module,
            "source_root": source_root,
            "source_files": sources,
            "metric": metric,
            "coverage_basis": "self",
            "coverage": aggregate,
            "fsm_group_count": len(groups),
            "gap_count": gap_count,
            "non_actionable_count": len(_non_actionable(section)),
            "analysis_complete": True,
            "fsm_groups": groups,
            "non_actionable": _non_actionable(section),
        }
    gaps = parsers[metric]()
    if coverage["missing"] and not gaps:
        raise CoverageExportParseError(metric, scope, "uncovered objects could not be resolved")
    prefix = {"line": "L", "condition": "C", "branch": "B", "toggle": "T", "fsm": "F"}[metric]
    for index, gap in enumerate(gaps, 1):
        gap["gap_id"] = f"{prefix}{index:04d}"
    return {
        "schema": f"xcov.code_coverage.{metric}.v1",
        "scope": scope,
        "module": module,
        "source_root": source_root,
        "source_files": sources,
        "metric": metric,
        "coverage_basis": "self",
        "coverage": coverage,
        "gap_count": len(gaps),
        "non_actionable_count": len(_non_actionable(section)),
        "analysis_complete": True,
        "gaps": gaps,
        "non_actionable": _non_actionable(section),
    }


def _scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ",".join(str(item) for item in value) + "]"
    return str(value)


def render_metric_xout(payload: Json, raw_name: str) -> str:
    if payload["metric"] == "line" and payload["schema"] == "xcov.code_coverage.line.v2":
        return _render_line_xout(payload, raw_name)
    if payload["metric"] == "condition" and payload["schema"] == "xcov.code_coverage.condition.v2":
        return _render_condition_xout(payload, raw_name)
    if payload["metric"] == "branch" and payload["schema"] == "xcov.code_coverage.branch.v2":
        return _render_branch_xout(payload, raw_name)
    if payload["metric"] == "fsm" and payload["schema"] == "xcov.code_coverage.fsm.v2":
        return _render_fsm_xout(payload, raw_name)
    coverage = payload["coverage"]
    lines = [
        f"@{payload['schema']}",
        f"scope: {_scalar(payload['scope'])}",
        f"module: {_scalar(payload['module'])}",
        f"source_root: {_scalar(payload['source_root'])}",
        "coverage_basis: self",
        "coverage: " + " ".join(
            f"{key}={coverage[key]}" for key in ("covered", "coverable", "missing", "pct")
        ),
        f"gap_count: {payload['gap_count']}",
        f"non_actionable_count: {payload['non_actionable_count']}",
        "analysis_complete: true",
        f"raw: {raw_name}",
        "",
        "gaps:",
    ]
    for gap in payload["gaps"]:
        lines.append(f"- gap_id: {gap['gap_id']}")
        for key, value in gap.items():
            if key in {"gap_id", "terms"} or value is None:
                continue
            lines.append(f"  {key}: {_scalar(value)}")
    lines.extend(["", "non_actionable:"])
    for item in payload["non_actionable"]:
        lines.append(f"- object: {_scalar(item['object'])}")
        lines.append(f"  status: {item['status']}")
    return "\n".join(lines) + "\n"


def _aligned_table(headers: List[str], rows: List[List[Any]], indent: str = "    ") -> List[str]:
    text_rows = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in text_rows:
        widths = [max(width, len(row[index])) for index, width in enumerate(widths)]
    rendered = [indent + "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)).rstrip()]
    for row in text_rows:
        rendered.append(indent + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip())
    return rendered


def _render_line_xout(payload: Json, raw_name: str) -> str:
    coverage = payload["coverage"]
    lines = [
        "@xcov.code_coverage.line.v2",
        f"scope: {_scalar(payload['scope'])}",
        f"module: {_scalar(payload['module'])}",
        f"source_root: {_scalar(payload['source_root'])}",
        "coverage_basis: self",
        "coverage: " + " ".join(
            f"{key}={coverage[key]}" for key in ("covered", "coverable", "missing", "pct")
        ),
        f"line_group_count: {payload['line_group_count']}",
        f"gap_count: {payload['gap_count']}",
        f"non_actionable_count: {payload['non_actionable_count']}",
        "analysis_complete: true",
        f"raw: {raw_name}",
        "",
        "line_groups:",
    ]
    for group in payload["line_groups"]:
        context = group["context"]
        lines.extend([f"- group_id: {group['group_id']}", "  context:"])
        lines.extend(_aligned_table(
            ["kind", "at", "covered", "coverable", "missing", "pct"],
            [[context[key] for key in ("kind", "at", "covered", "coverable", "missing", "pct")]],
        ))
        lines.append("  uncovered:")
        lines.extend(_aligned_table(
            ["gap_id", "at", "statement"],
            [[row[key] for key in ("gap_id", "at", "statement")] for row in group["uncovered"]],
        ))
    lines.extend(["", "non_actionable:"])
    for item in payload["non_actionable"]:
        lines.append(f"- object: {_scalar(item['object'])}")
        lines.append(f"  status: {item['status']}")
    return "\n".join(lines) + "\n"


def _render_condition_xout(payload: Json, raw_name: str) -> str:
    coverage = payload["coverage"]
    lines = [
        "@xcov.code_coverage.condition.v2",
        f"scope: {_scalar(payload['scope'])}",
        f"module: {_scalar(payload['module'])}",
        f"source_root: {_scalar(payload['source_root'])}",
        "coverage_basis: self",
        "coverage: " + " ".join(
            f"{key}={coverage[key]}" for key in ("covered", "coverable", "missing", "pct")
        ),
        f"condition_group_count: {payload['condition_group_count']}",
        f"coverage_object_gap_count: {payload['coverage_object_gap_count']}",
        f"gap_count: {payload['gap_count']}",
        f"non_actionable_count: {payload['non_actionable_count']}",
        "analysis_complete: true",
        f"raw: {raw_name}",
        "",
        "condition_groups:",
    ]
    for group in payload["condition_groups"]:
        condition = group["condition"]
        lines.extend([f"- group_id: {group['group_id']}", "  condition:"])
        lines.extend(_aligned_table(
            ["at", "expression"],
            [[condition["at"], condition["expression"]]],
        ))
        lines.append("  terms:")
        lines.extend(_aligned_table(
            ["marker", "expression"],
            [[term["marker"], term["expression"]] for term in group["terms"]],
        ))
        lines.append("  uncovered:")
        markers = [term["marker"] for term in group["terms"]]
        lines.extend(_aligned_table(
            ["gap_id", *markers],
            [[row["gap_id"], *row["values"]] for row in group["uncovered"]],
        ))
    lines.extend(["", "non_actionable:"])
    for item in payload["non_actionable"]:
        lines.append(f"- object: {_scalar(item['object'])}")
        lines.append(f"  status: {item['status']}")
    return "\n".join(lines) + "\n"


def _render_branch_xout(payload: Json, raw_name: str) -> str:
    coverage = payload["coverage"]
    lines = [
        "@xcov.code_coverage.branch.v2",
        f"scope: {_scalar(payload['scope'])}",
        f"module: {_scalar(payload['module'])}",
        f"source_root: {_scalar(payload['source_root'])}",
        "coverage_basis: self",
        "coverage: " + " ".join(
            f"{key}={coverage[key]}" for key in ("covered", "coverable", "missing", "pct")
        ),
        f"decision_group_count: {payload['decision_group_count']}",
        f"gap_count: {payload['gap_count']}",
        f"non_actionable_count: {payload['non_actionable_count']}",
        "analysis_complete: true",
        f"raw: {raw_name}",
        "",
        "decision_groups:",
    ]
    for group in payload["decision_groups"]:
        lines.extend([f"- group_id: {group['group_id']}", "  decision_path:"])
        lines.extend(_aligned_table(
            ["marker", "kind", "at", "expression", "source"],
            [[item["marker"], item["kind"], item["at"], item["expression"],
              item["source"]]
             for item in group["decision_path"]],
        ))
        lines.append("  uncovered:")
        markers = [item["marker"] for item in group["decision_path"]]
        lines.extend(_aligned_table(
            ["gap_id", *markers],
            [[row["gap_id"], *row["values"]] for row in group["uncovered"]],
        ))
    lines.extend(["", "non_actionable:"])
    for item in payload["non_actionable"]:
        lines.append(f"- object: {_scalar(item['object'])}")
        lines.append(f"  status: {item['status']}")
    return "\n".join(lines) + "\n"


def _render_fsm_xout(payload: Json, raw_name: str) -> str:
    coverage = payload["coverage"]
    lines = [
        "@xcov.code_coverage.fsm.v2",
        f"scope: {_scalar(payload['scope'])}",
        f"module: {_scalar(payload['module'])}",
        f"source_root: {_scalar(payload['source_root'])}",
        "coverage_basis: self",
        "coverage: " + " ".join(
            f"{key}={coverage[key]}" for key in ("covered", "coverable", "missing", "pct")
        ),
        f"fsm_group_count: {payload['fsm_group_count']}",
        f"gap_count: {payload['gap_count']}",
        f"non_actionable_count: {payload['non_actionable_count']}",
        "analysis_complete: true",
        f"raw: {raw_name}",
        "",
        "fsm_groups:",
    ]
    for index, group in enumerate(payload["fsm_groups"]):
        if index:
            lines.append("")
        group_coverage = group["transition_coverage"]
        lines.append(f"- fsm: {group['fsm']}")
        lines.append("  transition_coverage: " + " ".join(
            f"{key}={group_coverage[key]}"
            for key in ("covered", "coverable", "missing", "pct")
        ))
        lines.append("  gaps:")
        lines.extend(_aligned_table(
            ["gap_id", "kind", "object", "at"],
            [[gap["gap_id"], gap["object_kind"], gap["object"], gap["at"]]
             for gap in group["gaps"]],
        ))
    lines.extend(["", "non_actionable:"])
    for item in payload["non_actionable"]:
        lines.append(f"- object: {_scalar(item['object'])}")
        lines.append(f"  status: {item['status']}")
    return "\n".join(lines) + "\n"


def navigation_payload(scope: str, scope_metrics: Dict[str, Json], children: Iterable[str]) -> Json:
    def metrics_for(name: str) -> Json:
        source = scope_metrics.get(name, {})
        return {metric: source.get(metric) for metric in PUBLIC_METRICS}

    return {
        "schema": "xcov.code_coverage.navigation.v1",
        "scope": scope,
        "source": "urg_session_xml",
        "statistics_basis": "subtree",
        "detail_boundary": "selected_instance_self_only",
        "instruction": "Children contain subtree statistics only. Export a child as a new scope to obtain its detail.",
        "analysis_complete": True,
        "selected": metrics_for(scope),
        "children": [{"scope": child, "metrics": metrics_for(child)} for child in sorted(children)],
    }


def render_navigation_xout(payload: Json) -> str:
    lines = [
        "@xcov.code_coverage.navigation.v1",
        f"scope: {_scalar(payload['scope'])}",
        "source: urg_session_xml",
        "statistics_basis: subtree",
        "detail_boundary: selected_instance_self_only",
        f"instruction: {_scalar(payload['instruction'])}",
        "analysis_complete: true",
        "",
        "selected:",
    ]
    lines.extend(_render_navigation_metrics(payload["selected"], "  "))
    lines.extend(["", "children:"])
    for child in payload["children"]:
        lines.append(f"- scope: {_scalar(child['scope'])}")
        lines.extend(_render_navigation_metrics(child["metrics"], "  "))
    return "\n".join(lines) + "\n"


def _render_navigation_metrics(metrics: Json, indent: str) -> List[str]:
    lines = []
    for metric in PUBLIC_METRICS:
        row = metrics.get(metric)
        if not row:
            lines.append(f"{indent}{metric}: unavailable")
            continue
        lines.append(
            f"{indent}{metric}: covered={row['covered']} coverable={row['coverable']} "
            f"missing={row['missing']} pct={row['pct']:.2f}"
        )
    return lines


def write_json(path: Path, payload: Json) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
