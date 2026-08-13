"""Strict URG coverage export and typed summary parsing for x-npi."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Dict, List, Sequence, Tuple
import xml.etree.ElementTree as ET


Json = Dict[str, Any]
FIXED_SUMMARY_OPTIONS = (
    "-xml_verbose", "-format", "text", "-show", "summary",
)
REQUIRED_ARTIFACTS = (
    "session.xml", "tests.txt", "dashboard.txt", "modlist.txt",
    "groups.txt", "asserts.txt",
)
PUBLIC_METRICS = {
    "Line": "line",
    "Cond": "condition",
    "Toggle": "toggle",
    "FSM": "fsm",
    "Branch": "branch",
    "Assert": "assert",
}
FUNCTIONAL_TYPES = {
    "Covergroup Variant", "Coverage Instance", "Coverage Point", "Cross Coverage",
}
ASSERTION_TYPES = {"Assertion", "Cover Property"}
KNOWN_SCOPE_TYPES = {
    "instance", "Groups", "Asserts", "assert", "Cover Group",
    *FUNCTIONAL_TYPES, *ASSERTION_TYPES,
}


class UrgCoverageError(RuntimeError):
    """Raised for strict URG provenance, execution, or parse failures."""


@dataclass(frozen=True)
class UrgSummary:
    report_dir: Path
    tests: Tuple[str, ...]
    scopes: Tuple[Json, ...]
    functional: Tuple[Json, ...]
    assertions: Tuple[Json, ...]
    xml_instances: Tuple[str, ...] = ()
    xml_instance_parent: Dict[str, str | None] = field(default_factory=dict)
    xml_instance_children: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    def expand_xml_instances(self, root: str, *, recursive: bool) -> Tuple[str, ...]:
        if root not in self.xml_instance_parent:
            raise UrgCoverageError(
                f"scope is not a real instance in fixed URG XML: {root!r}"
            )
        if not recursive:
            return (root,)
        result: List[str] = []
        pending = [root]
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(reversed(self.xml_instance_children.get(current, ())))
        return tuple(result)

    def rows(
        self,
        *,
        metrics: Sequence[str] | None = None,
        scope: str | None = None,
    ) -> List[Json]:
        wanted = set(metrics or [*PUBLIC_METRICS.values(), "functional"])
        out: List[Json] = []
        for scope_row in self.scopes:
            full_name = str(scope_row["full_name"])
            if scope is not None and not (
                full_name == scope or full_name.startswith(scope + ".")
            ):
                continue
            for metric, ratio in scope_row["metrics"].items():
                if metric in wanted and metric != "functional":
                    out.append({
                        "coverage_kind": "code",
                        "scope": full_name,
                        "metric": metric,
                        **ratio,
                    })
        if "functional" in wanted:
            out.extend(
                dict(row) for row in self.functional
                if scope is None or row.get("scope") in (None, scope)
                or str(row.get("scope") or "").startswith(scope + ".")
            )
        if "assert" in wanted:
            out.extend(
                dict(row) for row in self.assertions
                if scope is None or row.get("scope") in (None, scope)
                or str(row.get("scope") or "").startswith(scope + ".")
            )
        return out


def urg_path() -> Path:
    raw = os.environ.get("VCS_HOME")
    if not raw or raw != raw.strip():
        raise UrgCoverageError("VCS_HOME must identify the URG installation")
    home = Path(raw).resolve(strict=True)
    candidate = (home / "bin" / "urg").resolve(strict=True)
    try:
        candidate.relative_to(home)
    except ValueError as exc:
        raise UrgCoverageError("VCS_HOME/bin/urg escapes VCS_HOME") from exc
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise UrgCoverageError("VCS_HOME/bin/urg is not executable")
    return candidate


def export_summary(
    vdb: str | os.PathLike[str],
    report_dir: str | os.PathLike[str],
    *,
    elfile: str | os.PathLike[str] | None = None,
    timeout_sec: int = 600,
) -> UrgSummary:
    """Run the one supported full64 URG summary command and publish atomically."""

    database = Path(vdb).resolve(strict=True)
    report = Path(report_dir).resolve(strict=False)
    if report.exists() or report.is_symlink():
        raise UrgCoverageError("report_dir must not already exist")
    report.parent.mkdir(parents=True, exist_ok=True)
    exclusion = None
    if elfile is not None:
        exclusion = Path(elfile).resolve(strict=True)
        if not exclusion.is_file() or exclusion.is_symlink():
            raise UrgCoverageError("elfile must be a regular non-symlink file")
    with tempfile.TemporaryDirectory(prefix=".x-npi-urg-", dir=report.parent) as temp:
        staging = Path(temp) / "report"
        staging.mkdir()
        argv = [
            str(urg_path()), "-full64", "-dir", str(database),
            "-report", str(staging), *FIXED_SUMMARY_OPTIONS,
        ]
        if exclusion is not None:
            argv.extend(["-elfile", str(exclusion)])
        completed = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False,
        )
        if completed.returncode != 0:
            raise UrgCoverageError(
                f"URG summary failed with {completed.returncode}: "
                f"{completed.stderr[-1000:]}"
            )
        parsed = parse_summary(staging)
        os.replace(staging, report)
    return UrgSummary(
        report_dir=report,
        tests=parsed.tests,
        scopes=parsed.scopes,
        functional=parsed.functional,
        assertions=parsed.assertions,
        xml_instances=parsed.xml_instances,
        xml_instance_parent=parsed.xml_instance_parent,
        xml_instance_children=parsed.xml_instance_children,
    )


def parse_summary(report_dir: str | os.PathLike[str]) -> UrgSummary:
    report = Path(report_dir).resolve(strict=True)
    artifacts = {name: report / name for name in REQUIRED_ARTIFACTS}
    invalid = [
        name for name, path in artifacts.items()
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0
    ]
    if invalid:
        raise UrgCoverageError(f"fixed URG summary artifacts are invalid: {invalid}")
    tests = _parse_tests(artifacts["tests.txt"])
    scopes: List[Json] = []
    functional: List[Json] = []
    assertions: List[Json] = []
    stack: List[Json] = []
    saw_old_coverage = False
    try:
        for event, elem in ET.iterparse(
            artifacts["session.xml"], events=("start", "end"),
        ):
            if event == "start":
                if elem.tag == "old_coverage":
                    saw_old_coverage = True
                elif elem.tag == "scope":
                    stack.append(_scope_context(elem, stack))
                continue
            if elem.tag == "metric" and stack:
                stack[-1]["metrics"][required_attr(elem, "name")] = _ratio(elem)
            elif elem.tag == "attr" and stack:
                name = elem.get("type") or elem.get("name")
                if not name:
                    raise UrgCoverageError("session.xml attr lacks name/type")
                stack[-1]["attrs"][name] = required_attr(elem, "value")
            elif elem.tag == "scope":
                if not stack:
                    raise UrgCoverageError("session.xml scope stack underflow")
                context = stack.pop()
                _finish_scope(context, scopes, functional, assertions)
                elem.clear()
    except ET.ParseError as exc:
        raise UrgCoverageError(f"session.xml is not well formed: {exc}") from exc
    if stack or not saw_old_coverage or not scopes:
        raise UrgCoverageError("session.xml does not contain a complete old_coverage tree")
    _attach_functional_scope_metrics(scopes, functional)
    xml_instances = tuple(sorted(str(row["full_name"]) for row in scopes))
    xml_instance_parent = {
        str(row["full_name"]): row.get("parent") for row in scopes
    }
    child_lists: Dict[str, List[str]] = {name: [] for name in xml_instances}
    for name, parent in xml_instance_parent.items():
        if parent is not None:
            child_lists.setdefault(str(parent), []).append(name)
    xml_instance_children = {
        name: tuple(sorted(children)) for name, children in child_lists.items()
    }
    return UrgSummary(
        report, tests, tuple(scopes), tuple(functional), tuple(assertions),
        xml_instances, xml_instance_parent, xml_instance_children,
    )


def _scope_context(elem: ET.Element, stack: List[Json]) -> Json:
    scope_type = required_attr(elem, "type")
    name = required_attr(elem, "name")
    if scope_type not in KNOWN_SCOPE_TYPES:
        raise UrgCoverageError(
            f"session.xml contains unsupported scope type {scope_type!r}"
        )
    parent_instance = next(
        (item["full_name"] for item in reversed(stack) if item["type"] == "instance"),
        None,
    )
    full_name = None
    if scope_type == "instance":
        full_name = name if parent_instance is None else f"{parent_instance}.{name}"
    return {
        "type": scope_type,
        "name": name,
        "full_name": full_name,
        "parent_instance": parent_instance,
        "covergroup_type": next(
            (item["name"] for item in reversed(stack) if item["type"] == "Cover Group"),
            None,
        ),
        "variant": next(
            (item["name"] for item in reversed(stack) if item["type"] == "Covergroup Variant"),
            name if scope_type == "Covergroup Variant" else None,
        ),
        "instance": next(
            (item["name"] for item in reversed(stack) if item["type"] == "Coverage Instance"),
            name if scope_type == "Coverage Instance" else None,
        ),
        "group_instance_summary": next(
            (
                item["attrs"].get("Group Instance Summary")
                for item in reversed(stack)
                if item["type"] == "Groups"
            ),
            None,
        ),
        "metrics": {},
        "attrs": {},
    }


def _finish_scope(
    context: Json,
    scopes: List[Json],
    functional: List[Json],
    assertions: List[Json],
) -> None:
    scope_type = context["type"]
    if scope_type == "instance":
        scopes.append({
            "name": context["name"],
            "full_name": context["full_name"],
            "parent": context["parent_instance"],
            "depth": str(context["full_name"]).count("."),
            "metrics": {
                PUBLIC_METRICS[name]: dict(value)
                for name, value in context["metrics"].items()
                if name in PUBLIC_METRICS
            },
        })
        return
    if scope_type in FUNCTIONAL_TYPES:
        metric_name = {
            "Covergroup Variant": "Group",
            "Coverage Instance": "Group",
            "Coverage Point": "Point",
            "Cross Coverage": "Cross",
        }[scope_type]
        ratio = context["metrics"].get(metric_name)
        if ratio is None:
            if context.get("group_instance_summary") == "0/0":
                ratio = {
                    "covered": 0,
                    "coverable": 0,
                    "missing": 0,
                    "coverage_pct": None,
                    "excluded": 0,
                }
            else:
                raise UrgCoverageError(
                    f"functional node {context['name']!r} lacks {metric_name!r} metric"
                )
        variant = context.get("variant")
        scope = (
            variant.split("::", 1)[0]
            if isinstance(variant, str) and "::" in variant else None
        )
        row = {
            "coverage_kind": "functional",
            "node_kind": scope_type,
            "name": context["name"],
            "covergroup_type": context.get("covergroup_type"),
            "covergroup": variant,
            "variant": variant,
            "instance": context.get("instance"),
            "scope": scope,
            **ratio,
        }
        if scope_type == "Coverage Point":
            row["coverpoint"] = context["name"]
        elif scope_type == "Cross Coverage":
            row["cross"] = context["name"]
        functional.append(row)
        return
    if scope_type in ASSERTION_TYPES:
        attrs = context["attrs"]
        attempts = _nonnegative_int(attrs.get("attempt", "0"), "attempt")
        success_name = "success" if scope_type == "Assertion" else "all match"
        failure_name = "failure" if scope_type == "Assertion" else "mismatches"
        successes = _nonnegative_int(attrs.get(success_name, "0"), success_name)
        failures = _nonnegative_int(attrs.get(failure_name, "0"), failure_name)
        incomplete = _nonnegative_int(attrs.get("incomplete", "0"), "incomplete")
        covered = 1 if successes > 0 else 0
        full_name = context["name"]
        assertions.append({
            "coverage_kind": "assertion",
            "node_kind": scope_type,
            "kind": "assertion" if scope_type == "Assertion" else "cover_property",
            "name": full_name.rsplit(".", 1)[-1],
            "full_name": full_name,
            "scope": full_name.rsplit(".", 1)[0] if "." in full_name else None,
            "attempts": attempts,
            "real_successes": successes,
            "failures": failures,
            "incomplete": incomplete,
            "without_attempts": 1 if attempts == 0 else 0,
            "covered": covered,
            "coverable": 1,
            "missing": 1 - covered,
            "coverage_pct": float(covered * 100),
        })


def _attach_functional_scope_metrics(scopes: List[Json], rows: List[Json]) -> None:
    """Attach one GROUP score per scope without double-counting variant/instance."""

    instance_variants = {
        row.get("variant") for row in rows
        if row.get("node_kind") == "Coverage Instance"
    }
    groups: Dict[str, List[Json]] = {}
    for row in rows:
        kind = row.get("node_kind")
        if kind == "Coverage Instance":
            pass
        elif kind == "Covergroup Variant" and row.get("variant") not in instance_variants:
            pass
        else:
            continue
        scope = row.get("scope")
        if scope:
            groups.setdefault(str(scope), []).append(row)
    by_name = {str(row["full_name"]): row for row in scopes}
    for scope, values in groups.items():
        if scope not in by_name:
            continue
        covered = sum(int(row["covered"]) for row in values)
        coverable = sum(int(row["coverable"]) for row in values)
        percentages = [
            float(row["coverage_pct"])
            for row in values if row["coverage_pct"] is not None
        ]
        by_name[scope]["metrics"]["functional"] = {
            "covered": covered,
            "coverable": coverable,
            "missing": max(coverable - covered, 0),
            "coverage_pct": (
                round(sum(percentages) / len(percentages), 4)
                if percentages else None
            ),
        }


def _ratio(elem: ET.Element) -> Json:
    value = required_attr(elem, "value")
    pieces = value.split("/", 1)
    if len(pieces) != 2:
        raise UrgCoverageError(f"metric value is not covered/coverable: {value!r}")
    try:
        covered, coverable = int(pieces[0]), int(pieces[1])
    except ValueError as exc:
        raise UrgCoverageError(f"metric ratio is not numeric: {value!r}") from exc
    if covered < 0 or coverable < 0 or covered > coverable:
        raise UrgCoverageError(f"metric ratio is outside valid bounds: {value!r}")
    return {
        "covered": covered,
        "coverable": coverable,
        "missing": max(coverable - covered, 0),
        "coverage_pct": (
            round(100.0 * covered / coverable, 4) if coverable > 0 else None
        ),
        "excluded": _nonnegative_int(elem.get("excl", "0"), "excl"),
    }


def required_attr(elem: ET.Element, name: str) -> str:
    value = elem.get(name)
    if value is None or value == "":
        raise UrgCoverageError(f"session.xml {elem.tag} lacks {name}")
    return value


def _nonnegative_int(value: str, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise UrgCoverageError(f"assertion {field!r} is not an integer") from exc
    if parsed < 0:
        raise UrgCoverageError(f"assertion {field!r} is negative")
    return parsed


def _parse_tests(path: Path) -> Tuple[str, ...]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    marker = "Data from the following tests was used to generate this report"
    try:
        start = lines.index(marker) + 1
    except ValueError as exc:
        raise UrgCoverageError("tests.txt lacks canonical test-list marker") from exc
    declared = None
    for line in lines:
        match = re.fullmatch(r"Total tests in report:\s*(\d+)", line.strip())
        if match:
            declared = int(match.group(1))
            break
    if declared is None:
        raise UrgCoverageError("tests.txt does not declare total tests")
    names: List[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or set(stripped) == {"-"}:
            continue
        name = Path(stripped).name
        if name and name not in names:
            names.append(name)
    if declared != len(names):
        raise UrgCoverageError("tests.txt declared count mismatch")
    return tuple(names)
