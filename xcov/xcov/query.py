from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .coverage_contract import strict_coverage_pct
from .errors import XcovError
from .schemas import query_contract_for_action, sort_fields_for_action

Json = Dict[str, Any]

DEFAULT_LIMITS = {
    "tests.list": 1000,
    "metrics.list": None,
    "scope.children": 100,
    "scope.search": 100,
    "scope.summary": 100,
    "code_coverage.summary": 100,
    "code_coverage.holes": 100,
    "functional_coverage.summary": 100,
    "functional_coverage.holes": 100,
    "assert.summary": 100,
}

REGEX_HINT_CHARS = ("[", "]", "{", "}", "^", "$", "(", ")", "|", "+")


def query_args(action: str, args: Json) -> Json:
    contract = query_contract_for_action(action)
    query = dict(args.get("query") or {})
    query.setdefault("include_patterns", [])
    query.setdefault("exclude_patterns", [])
    query.setdefault("match_field", contract["default"])
    query.setdefault("pattern_mode", "glob")
    query.setdefault("case_sensitive", True)
    if query.get("pattern_mode") != "glob":
        raise XcovError("REGEX_NOT_SUPPORTED", "only glob wildcard patterns are supported",
                        pattern_mode=query.get("pattern_mode"))
    for pat in list(query["include_patterns"]) + list(query["exclude_patterns"]):
        if any(ch in str(pat) for ch in REGEX_HINT_CHARS):
            raise XcovError("REGEX_NOT_SUPPORTED", "only glob wildcard patterns are supported",
                            pattern=pat, supported="*,?")
    mf = query.get("match_field")
    if (
        not isinstance(mf, str)
        or not mf
        or mf not in contract["allowed"]
    ):
        raise XcovError("INVALID_QUERY_FIELD",
                        f"query.match_field is not supported for {action}",
                        match_field=repr(mf),
                        supported=",".join(contract["allowed"]))
    return query


def filters_summary(query: Json) -> Json:
    return {
        "include": query.get("include_patterns") or [],
        "exclude": query.get("exclude_patterns") or [],
        "match_field": query.get("match_field") or "full_name",
    }


def _field_value(item: Json, field: str) -> str | None:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    if field == "file":
        value = evidence.get("file") or item.get("file")
    else:
        value = item.get(field)
    return str(value) if value is not None else None


def filter_items(items: Iterable[Json], query: Json) -> List[Json]:
    include = [str(p) for p in (query.get("include_patterns") or [])]
    exclude = [str(p) for p in (query.get("exclude_patterns") or [])]
    field = str(query.get("match_field") or "full_name")
    case_sensitive = bool(query.get("case_sensitive", True))

    def norm(s: str) -> str:
        return s if case_sensitive else s.lower()

    def match_any(patterns: List[str], value: str) -> bool:
        if not patterns:
            return False
        nval = norm(value) if value else ""
        for pat in patterns:
            if fnmatch.fnmatchcase(nval, norm(pat)):
                return True
        return False

    rows: List[Json] = []
    for item in items:
        value = _field_value(item, field)
        if value is None:
            continue
        if include and not match_any(include, value):
            continue
        if exclude and match_any(exclude, value):
            continue
        rows.append(item)
    return rows


def sort_items(action: str, items: List[Json], sort: Json | None) -> List[Json]:
    if sort is None:
        return items
    allowed = sort_fields_for_action(action)
    key = sort.get("by")
    if not isinstance(key, str) or key not in allowed:
        raise XcovError(
            "INVALID_SORT_FIELD",
            f"sort.by is not supported for {action}",
            field=repr(key),
            supported=",".join(allowed),
        )
    order = sort.get("order", "asc")
    if order not in ("asc", "desc"):
        raise XcovError(
            "INVALID_SORT_ORDER",
            "sort.order must be asc or desc",
        )
    reverse = order == "desc"
    missing = [
        index
        for index, item in enumerate(items)
        if key not in item
    ]
    if missing:
        raise XcovError(
            "INVALID_SORT_FIELD",
            f"sort.by is not present in the {action} response variant",
            field=key,
            row_index=missing[0],
        )

    def item_key(item: Json):
        value = item.get(key)
        if value is None and key in ("file", "line"):
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            value = evidence.get(key)
        return (value is None, value)

    return sorted(items, key=item_key, reverse=reverse)


def limit_args(action: str, args: Json) -> Json:
    default = DEFAULT_LIMITS.get(action, 100)
    limits = dict(args.get("limits") or {})
    if "max_items" not in limits:
        limits["max_items"] = default
    limits.setdefault("overflow", "truncate")
    max_items = limits.get("max_items")
    if max_items is not None and (not isinstance(max_items, int) or max_items < 0):
        raise XcovError("INVALID_LIMIT", "limits.max_items must be a non-negative integer")
    if limits["overflow"] not in ("truncate", "error", "summary_only"):
        raise XcovError("INVALID_LIMIT", "unsupported limits.overflow",
                        overflow=limits["overflow"])
    return limits


def resolve_artifact_path(path: str, allow_absolute_path: bool = False) -> str:
    raw = Path(path)
    if raw.is_absolute():
        if not allow_absolute_path:
            raise XcovError("OUTPUT_PATH_UNSAFE",
                            "absolute output.path requires output.allow_absolute_path=true",
                            path=path)
        return str(raw)
    if any(part == ".." for part in raw.parts):
        raise XcovError("OUTPUT_PATH_UNSAFE", "output.path must not contain '..'",
                        path=path)
    return str(Path(".xverif") / "xcov_exports" / raw)


def apply_output(action: str, args: Json, items: List[Json]) -> Tuple[Json, List[Json], List[str]]:
    limits = limit_args(action, args)
    total_count = len(items)
    max_items = limits.get("max_items")
    overflow = limits.get("overflow")
    warnings: List[str] = []
    exceeds_limit = bool(max_items is not None and total_count > max_items)
    if overflow == "error" and exceeds_limit:
        raise XcovError(
            "INVALID_LIMIT",
            "result exceeds limits.max_items",
            total_count=total_count,
            max_items=max_items,
        )
    if overflow == "summary_only":
        inline: List[Json] = []
    elif max_items is None:
        inline = items
    else:
        inline = items[:max_items]
    response_truncated = len(inline) < total_count
    summary = {
        "total_count": total_count,
        "returned_count": len(inline),
        "response_truncated": response_truncated,
        "scan_complete": True,
        "analysis_complete": True,
        "truncation_scopes": ["data.items"] if response_truncated else [],
    }
    return summary, inline, warnings


def coverage_pct(covered: int, coverable: int) -> float | None:
    if (
        not isinstance(covered, int)
        or isinstance(covered, bool)
        or not isinstance(coverable, int)
        or isinstance(coverable, bool)
        or covered < 0
        or coverable < 0
        or covered > coverable
    ):
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "coverage aggregation requires canonical non-negative counts",
            covered=covered,
            coverable=coverable,
        )
    return strict_coverage_pct(covered, coverable)
