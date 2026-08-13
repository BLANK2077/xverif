"""Strict, streaming parser for the fixed URG summary artifact contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

from .errors import XcovError
from .limits import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_TOTAL_BYTES,
    MAX_IR_SCOPES,
    MAX_TYPED_ROWS,
    enforce_count,
)

Json = Dict[str, Any]

PUBLIC_METRICS = {
    "Line": "line",
    "Cond": "condition",
    "Toggle": "toggle",
    "FSM": "fsm",
    "Branch": "branch",
    "Assert": "assert",
}
FUNCTIONAL_TYPES = {
    "Cover Group",
    "Covergroup Variant",
    "Coverage Instance",
    "Coverage Point",
    "Cross Coverage",
}
KNOWN_SCOPE_TYPES = {
    "instance",
    "Groups",
    "Asserts",
    "Assertion",
    "Cover Property",
    "assert",
    *FUNCTIONAL_TYPES,
}
REQUIRED_ARTIFACTS = (
    "session.xml",
    "tests.txt",
    "dashboard.txt",
    "modlist.txt",
    "groups.txt",
    "asserts.txt",
)


@dataclass(frozen=True)
class UrgSummaryIndex:
    metric_names: Tuple[str, ...]
    tests: Tuple[str, ...]
    scopes: Tuple[Json, ...]
    scope_metrics: Dict[str, Json]
    functional_rows: Tuple[Json, ...]
    assertion_rows: Tuple[Json, ...]
    xml_instances: Tuple[str, ...] = ()
    xml_instance_parent: Dict[str, Optional[str]] = field(default_factory=dict)
    xml_instance_children: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    @property
    def top_scopes(self) -> Tuple[Json, ...]:
        return tuple(row for row in self.scopes if row["depth"] == 0)

    def expand_xml_instances(self, root: str, *, recursive: bool) -> Tuple[str, ...]:
        """Return one exact XML instance or its real XML subtree."""

        if root not in self.xml_instance_parent:
            raise XcovError(
                "SCOPE_NOT_FOUND",
                "scope is not a real instance in the fixed URG XML hierarchy",
                scope=root,
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


def validate_summary_artifacts(report_dir: str | Path) -> Dict[str, Path]:
    root = Path(report_dir)
    if not root.is_dir():
        raise XcovError(
            "URG_SUMMARY_INCOMPLETE",
            "URG summary report directory is missing",
            report_dir=str(root),
        )
    paths = {name: root / name for name in REQUIRED_ARTIFACTS}
    missing = [
        name for name, path in paths.items()
        if not path.is_file() or path.is_symlink()
    ]
    empty = [
        name for name, path in paths.items()
        if path.is_file() and path.stat().st_size == 0
    ]
    if missing or empty:
        raise XcovError(
            "URG_SUMMARY_INCOMPLETE",
            "URG summary report is missing required non-empty artifacts",
            report_dir=str(root),
            missing=missing,
            empty=empty,
        )
    sizes = {name: path.stat().st_size for name, path in paths.items()}
    oversized = [name for name, size in sizes.items() if size > MAX_ARTIFACT_BYTES]
    total_size = sum(sizes.values())
    if oversized or total_size > MAX_ARTIFACT_TOTAL_BYTES:
        raise XcovError(
            "RESOURCE_BUDGET_EXCEEDED",
            "URG summary artifacts exceed the xcov byte budget",
            resource_kind="urg_summary_artifacts",
            resource_count=total_size,
            max_resource_count=MAX_ARTIFACT_TOTAL_BYTES,
        )
    return paths


def parse_urg_summary(report_dir: str | Path) -> UrgSummaryIndex:
    paths = validate_summary_artifacts(report_dir)
    tests = _parse_tests(paths["tests.txt"])
    return _parse_xml(paths["session.xml"], tests)


def _parse_tests(path: Path) -> Tuple[str, ...]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    marker = "Data from the following tests was used to generate this report"
    try:
        start = lines.index(marker) + 1
    except ValueError as exc:
        raise XcovError(
            "URG_TESTS_PARSE_FAILED",
            "tests.txt does not contain the canonical test-list marker",
            path=str(path),
        ) from exc
    paths = [line.strip() for line in lines[start:] if line.strip() and set(line.strip()) != {"-"}]
    names: List[str] = []
    for raw in paths:
        name = Path(raw).name
        if name and name not in names:
            names.append(name)
    total = _declared_test_count(lines)
    if total != len(names):
        raise XcovError(
            "URG_TESTS_PARSE_FAILED",
            "tests.txt declared count does not match parsed test paths",
            path=str(path),
            declared=total,
            parsed=len(names),
        )
    return tuple(names)


def _declared_test_count(lines: Iterable[str]) -> int:
    for line in lines:
        match = re.fullmatch(r"Total tests in report:\s*(\d+)", line.strip())
        if match:
            return int(match.group(1))
    raise XcovError(
        "URG_TESTS_PARSE_FAILED",
        "tests.txt does not declare the total test count",
    )


def _parse_xml(xml_path: Path, tests: Tuple[str, ...]) -> UrgSummaryIndex:
    metric_names: List[str] = []
    scope_rows: Dict[str, Json] = {}
    functional_rows: List[Json] = []
    assertion_rows: List[Json] = []
    stack: List[Json] = []
    saw_old_coverage = False

    try:
        events = ET.iterparse(xml_path, events=("start", "end"))
        for event, elem in events:
            if event == "start":
                if elem.tag == "old_coverage":
                    saw_old_coverage = True
                elif elem.tag == "scope":
                    stack.append(_scope_context(elem, stack))
                continue

            if elem.tag == "metdef" and elem.get("builtin") == "1":
                name = _required_attr(elem, "name", xml_path)
                if name not in metric_names:
                    metric_names.append(name)
            elif elem.tag == "metric" and stack:
                name = _required_attr(elem, "name", xml_path)
                stack[-1]["metrics"][name] = _ratio(elem, xml_path)
            elif elem.tag == "attr" and stack:
                name = elem.get("type") or elem.get("name")
                if not name:
                    raise _xml_error(xml_path, "attr is missing type/name")
                stack[-1]["attrs"][name] = _required_attr(elem, "value", xml_path)
            elif elem.tag == "scope":
                if not stack:
                    raise _xml_error(xml_path, "scope stack underflow")
                ctx = stack.pop()
                _finish_scope(
                    ctx,
                    scope_rows,
                    functional_rows,
                    assertion_rows,
                    xml_path,
                )
                enforce_count("urg_ir_scopes", len(scope_rows), MAX_IR_SCOPES)
                enforce_count(
                    "urg_typed_rows",
                    len(functional_rows) + len(assertion_rows),
                    MAX_TYPED_ROWS,
                )
                elem.clear()
    except ET.ParseError as exc:
        raise XcovError(
            "URG_XML_PARSE_FAILED",
            "session.xml is not well-formed XML",
            path=str(xml_path),
            parse_error=str(exc),
        ) from exc

    if stack:
        raise _xml_error(xml_path, "scope stack is not empty at end of document")
    if not saw_old_coverage:
        raise _xml_error(xml_path, "session.xml is missing old_coverage")
    if not scope_rows:
        raise _xml_error(xml_path, "session.xml contains no instance scopes")
    if not metric_names:
        raise _xml_error(xml_path, "session.xml contains no builtin metric definitions")

    xml_instances = tuple(sorted(scope_rows))
    xml_instance_parent = {
        name: row["parent"] for name, row in scope_rows.items()
    }
    xml_instance_children_lists: Dict[str, List[str]] = {
        name: [] for name in xml_instances
    }
    for name, parent in xml_instance_parent.items():
        if parent is not None:
            xml_instance_children_lists.setdefault(parent, []).append(name)
    xml_instance_children = {
        name: tuple(sorted(children))
        for name, children in xml_instance_children_lists.items()
    }
    _add_synthetic_hierarchy_scopes(scope_rows)
    scopes = tuple(
        {
            key: value
            for key, value in scope_rows[name].items()
            if key != "metrics"
        }
        for name in sorted(scope_rows)
    )
    scope_metrics = {
        name: {metric: dict(values) for metric, values in row["metrics"].items()}
        for name, row in scope_rows.items()
    }
    selected_functional = _select_functional_summary_rows(functional_rows)
    _attach_functional_scope_metrics(
        scope_metrics,
        [
            *selected_functional,
            *(row for row in functional_rows if row["node_kind"] == "Groups Summary"),
        ],
    )
    return UrgSummaryIndex(
        metric_names=tuple(metric_names),
        tests=tests,
        scopes=scopes,
        scope_metrics=scope_metrics,
        functional_rows=tuple(selected_functional),
        assertion_rows=tuple(assertion_rows),
        xml_instances=xml_instances,
        xml_instance_parent=xml_instance_parent,
        xml_instance_children=xml_instance_children,
    )


def _add_synthetic_hierarchy_scopes(scope_rows: Dict[str, Json]) -> None:
    for full_name in list(scope_rows):
        parts = full_name.split(".")
        for index in range(1, len(parts)):
            ancestor = ".".join(parts[:index])
            if ancestor not in scope_rows:
                scope_rows[ancestor] = {
                    "name": parts[index - 1],
                    "full_name": ancestor,
                    "parent": (
                        ".".join(parts[: index - 1])
                        if index > 1 else None
                    ),
                    "depth": index - 1,
                    "type": "instance",
                    "metrics": {},
                }
    for full_name, row in scope_rows.items():
        row["name"] = full_name.rsplit(".", 1)[-1]
        row["parent"] = full_name.rsplit(".", 1)[0] if "." in full_name else None
        row["depth"] = full_name.count(".")


def _scope_context(elem: ET.Element, stack: List[Json]) -> Json:
    scope_type = elem.get("type") or ""
    name = elem.get("name") or ""
    if not scope_type or not name:
        raise XcovError(
            "URG_XML_CONTRACT_ERROR",
            "scope requires non-empty type and name",
            scope_type=scope_type,
            scope_name=name,
        )
    if scope_type not in KNOWN_SCOPE_TYPES:
        raise XcovError(
            "URG_XML_UNSUPPORTED_SCOPE_TYPE",
            "session.xml contains an unsupported scope type",
            scope_type=scope_type,
            scope_name=name,
        )
    parent_instance = next(
        (ctx["full_name"] for ctx in reversed(stack) if ctx["type"] == "instance"),
        None,
    )
    full_name: Optional[str] = None
    if scope_type == "instance":
        full_name = name if parent_instance is None else f"{parent_instance}.{name}"
    return {
        "type": scope_type,
        "name": name,
        "full_name": full_name,
        "parent_instance": parent_instance,
        "covergroup_type": next(
            (ctx["name"] for ctx in reversed(stack) if ctx["type"] == "Cover Group"),
            None,
        ),
        "variant": next(
            (ctx["name"] for ctx in reversed(stack) if ctx["type"] == "Covergroup Variant"),
            name if scope_type == "Covergroup Variant" else None,
        ),
        "instance": next(
            (ctx["name"] for ctx in reversed(stack) if ctx["type"] == "Coverage Instance"),
            name if scope_type == "Coverage Instance" else None,
        ),
        "group_instance_summary": next(
            (
                ctx["attrs"].get("Group Instance Summary")
                for ctx in reversed(stack)
                if ctx["type"] == "Groups"
            ),
            None,
        ),
        "metrics": {},
        "attrs": {},
    }


def _finish_scope(
    ctx: Json,
    scope_rows: Dict[str, Json],
    functional_rows: List[Json],
    assertion_rows: List[Json],
    xml_path: Path,
) -> None:
    scope_type = ctx["type"]
    if scope_type == "instance":
        full_name = ctx["full_name"]
        if full_name in scope_rows:
            raise _xml_error(xml_path, "duplicate instance scope", full_name=full_name)
        parent = ctx["parent_instance"]
        scope_rows[full_name] = {
            "name": ctx["name"],
            "full_name": full_name,
            "parent": parent,
            "depth": 0 if parent is None else full_name.count("."),
            "type": "instance",
            "metrics": _public_metrics(ctx["metrics"]),
        }
    elif scope_type in FUNCTIONAL_TYPES:
        row = _functional_row(ctx, xml_path)
        if row is not None:
            functional_rows.append(row)
    elif scope_type == "Groups":
        functional_rows.append(_groups_summary_row(ctx, xml_path))
    elif scope_type in {"Assertion", "Cover Property"}:
        assertion_rows.append(_assertion_row(ctx, xml_path))


def _public_metrics(metrics: Dict[str, Json]) -> Dict[str, Json]:
    return {
        PUBLIC_METRICS[name]: dict(values)
        for name, values in metrics.items()
        if name in PUBLIC_METRICS
    }


def _functional_row(ctx: Json, xml_path: Path) -> Optional[Json]:
    scope_type = ctx["type"]
    metric_name = {
        "Covergroup Variant": "Group",
        "Coverage Instance": "Group",
        "Coverage Point": "Point",
        "Cross Coverage": "Cross",
    }.get(scope_type)
    if metric_name is None:
        return None
    ratio = ctx["metrics"].get(metric_name)
    if ratio is None:
        if ctx.get("group_instance_summary") == "0/0":
            ratio = {
                "covered": 0,
                "coverable": 0,
                "missing": 0,
                "excluded": 0,
                "pct": None,
            }
        else:
            raise _xml_error(
                xml_path,
                "functional scope is missing its score metric",
                scope_type=scope_type,
                scope_name=ctx["name"],
                metric=metric_name,
            )
    variant = ctx.get("variant")
    scope = variant.split("::", 1)[0] if isinstance(variant, str) and "::" in variant else None
    score_pct = _percent_attr(ctx["attrs"].get("Score"), ratio["pct"], xml_path)
    row: Json = {
        "type": {
            "Covergroup Variant": "urgCovCovergroupVariant",
            "Coverage Instance": "npiCovCovergroup",
            "Coverage Point": "npiCovCoverpoint",
            "Cross Coverage": "npiCovCross",
        }[scope_type],
        "node_kind": scope_type,
        "scope": scope,
        "covergroup_type": ctx.get("covergroup_type"),
        "covergroup": variant,
        "variant": variant,
        "instance": ctx.get("instance"),
        "name": ctx["name"],
        "full_name": _functional_full_name(ctx),
        "metric": "functional",
        "covered": ratio["covered"],
        "coverable": ratio["coverable"],
        "missing": ratio["missing"],
        "coverage_pct": score_pct,
        "status": [],
        "evidence": {},
    }
    if scope_type == "Coverage Point":
        row["coverpoint"] = ctx["name"]
    elif scope_type == "Cross Coverage":
        row["cross"] = ctx["name"]
    return row


def _groups_summary_row(ctx: Json, xml_path: Path) -> Json:
    raw = ctx["attrs"].get("Group Summary")
    if raw is None:
        raise _xml_error(xml_path, "Groups scope is missing Group Summary")
    match = re.fullmatch(r"(\d+)/(\d+)", raw)
    if not match:
        raise _xml_error(xml_path, "Group Summary is not covered/coverable", value=raw)
    covered, coverable = map(int, match.groups())
    if covered > coverable:
        raise _xml_error(xml_path, "Group Summary covered exceeds coverable", value=raw)
    return {
        "type": "urgCovGroupsSummary",
        "node_kind": "Groups Summary",
        "scope": ctx["name"],
        "covered": covered,
        "coverable": coverable,
        "missing": coverable - covered,
        "coverage_pct": round(100.0 * covered / coverable, 4) if coverable else None,
    }


def _functional_full_name(ctx: Json) -> str:
    base = str(ctx.get("variant") or ctx.get("covergroup_type") or "")
    parts = [base]
    if ctx.get("instance"):
        parts.append(str(ctx["instance"]))
    if ctx["type"] in {"Coverage Point", "Cross Coverage"}:
        parts.append(str(ctx["name"]))
    return "::".join(part for part in parts if part)


def _select_functional_summary_rows(rows: List[Json]) -> List[Json]:
    instance_variants = {
        row["variant"] for row in rows
        if row["node_kind"] == "Coverage Instance"
    }
    selected: List[Json] = []
    for row in rows:
        kind = row["node_kind"]
        if kind == "Covergroup Variant":
            if row["variant"] not in instance_variants:
                fallback = dict(row)
                fallback["type"] = "npiCovCovergroup"
                selected.append(fallback)
        elif kind == "Coverage Instance":
            selected.append(row)
        elif kind in {"Coverage Point", "Cross Coverage"}:
            has_instance = bool(row.get("instance"))
            if has_instance or row["variant"] not in instance_variants:
                selected.append(row)
    return selected


def _attach_functional_scope_metrics(
    scope_metrics: Dict[str, Json],
    rows: List[Json],
) -> None:
    by_scope: Dict[str, List[float]] = {}
    ratio_by_scope: Dict[str, List[Json]] = {}
    for row in rows:
        if row["node_kind"] == "Groups Summary":
            scope = str(row["scope"])
            if scope in scope_metrics:
                scope_metrics[scope]["functional"] = {
                    "covered": int(row["covered"]),
                    "coverable": int(row["coverable"]),
                    "missing": int(row["missing"]),
                    "excluded": 0,
                    "pct": (
                        float(row["coverage_pct"])
                        if row["coverage_pct"] is not None else None
                    ),
                }
            continue
        if row["type"] != "npiCovCovergroup" or not row.get("scope"):
            continue
        scope = str(row["scope"])
        if row["coverage_pct"] is not None:
            by_scope.setdefault(scope, []).append(float(row["coverage_pct"]))
        ratio_by_scope.setdefault(scope, []).append(row)
    for scope, ratios in ratio_by_scope.items():
        if scope not in scope_metrics:
            continue
        percentages = by_scope.get(scope, [])
        covered = sum(int(row["covered"]) for row in ratios)
        coverable = sum(int(row["coverable"]) for row in ratios)
        scope_metrics[scope]["functional"] = {
            "covered": covered,
            "coverable": coverable,
            "missing": coverable - covered,
            "excluded": 0,
            "pct": (
                round(sum(percentages) / len(percentages), 4)
                if percentages else None
            ),
        }


def _assertion_row(ctx: Json, xml_path: Path) -> Json:
    attrs = ctx["attrs"]
    attempts = _nonnegative_int(attrs.get("attempt", "0"), "attempt", xml_path)
    success_name = "success" if ctx["type"] == "Assertion" else "all match"
    successes = _nonnegative_int(attrs.get(success_name, "0"), success_name, xml_path)
    failures_name = "failure" if ctx["type"] == "Assertion" else "mismatches"
    failures = _nonnegative_int(attrs.get(failures_name, "0"), failures_name, xml_path)
    incomplete = _nonnegative_int(attrs.get("incomplete", "0"), "incomplete", xml_path)
    covered = 1 if successes > 0 else 0
    full_name = ctx["name"]
    scope = full_name.rsplit(".", 1)[0] if "." in full_name else None
    return {
        "name": full_name.rsplit(".", 1)[-1],
        "full_name": full_name,
        "scope": scope,
        "kind": "assertion" if ctx["type"] == "Assertion" else "cover_property",
        "attempts": attempts,
        "real_successes": successes,
        "without_attempts": 1 if attempts == 0 else 0,
        "failures": failures,
        "incomplete": incomplete,
        "covered": covered,
        "coverable": 1,
        "missing": 1 - covered,
        "coverage_pct": float(covered * 100),
        "status": ["covered" if covered else "not_covered"],
        "evidence": {},
    }


def _ratio(elem: ET.Element, xml_path: Path) -> Json:
    value = _required_attr(elem, "value", xml_path)
    match = re.fullmatch(r"(\d+)/(\d+)", value)
    if not match:
        raise _xml_error(xml_path, "metric value is not covered/coverable", value=value)
    covered, coverable = map(int, match.groups())
    if covered > coverable:
        raise _xml_error(
            xml_path,
            "metric covered count exceeds coverable count",
            value=value,
        )
    excluded = _nonnegative_int(elem.get("excl", "0"), "excl", xml_path)
    pct = round(100.0 * covered / coverable, 4) if coverable else None
    return {
        "covered": covered,
        "coverable": coverable,
        "missing": coverable - covered,
        "excluded": excluded,
        "pct": pct,
    }


def _percent_attr(
    value: Optional[str],
    default: Optional[float],
    xml_path: Path,
) -> Optional[float]:
    if value is None:
        return default
    match = re.fullmatch(r"(\d+(?:\.\d+)?)%?", value)
    if not match:
        raise _xml_error(xml_path, "Score attribute is not a percentage", value=value)
    pct = float(match.group(1))
    if not 0.0 <= pct <= 100.0:
        raise _xml_error(xml_path, "Score attribute is outside 0..100", value=value)
    return pct


def _required_attr(elem: ET.Element, name: str, xml_path: Path) -> str:
    value = elem.get(name)
    if value is None or value == "":
        raise _xml_error(xml_path, "XML element is missing a required attribute", attribute=name)
    return value


def _nonnegative_int(value: str, field: str, xml_path: Path) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise _xml_error(xml_path, "attribute is not an integer", field=field, value=value) from exc
    if parsed < 0:
        raise _xml_error(xml_path, "attribute is negative", field=field, value=value)
    return parsed


def _xml_error(xml_path: Path, message: str, **detail: Any) -> XcovError:
    return XcovError(
        "URG_XML_CONTRACT_ERROR",
        message,
        path=str(xml_path),
        **detail,
    )
