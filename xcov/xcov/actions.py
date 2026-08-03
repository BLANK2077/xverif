from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional

from .backend import METRICS
from .coverage_contract import is_score_bearing_row
from .errors import XcovError, error_response
from .exclusions_csv import (
    apply_rebase_suggestions,
    exclusion_paths,
    format_directory,
    git_group_status,
    parse_directory,
    rebase_suggestions,
    resolve_documents,
    review_markdown,
    stamp_documents,
    suggested_patches,
)
from .logging import (log_action_event, request_summary_for_log,
                      response_summary_for_log, update_session_manifest)
from .protocol import (
    completeness_summary,
    normalize_request,
    ok_response,
    validate_action_token,
)
from .provenance import validate_run_manifest
from .query import (apply_output, coverage_pct, filter_items, filters_summary,
                    query_args, resolve_artifact_path, sort_items)
from .schemas import (
    schema_actions,
    schema_for_action,
    validate_request as validate_action_request,
    validate_response as validate_action_response,
)
from .session import SessionManager

Json = Dict[str, Any]


@dataclass(frozen=True)
class ActionContract:
    name: str
    handler: str
    needs_session: bool
    use_when: str
    do_not_use_when: str

    def validate_request(self, req: Json) -> None:
        if req.get("action") != self.name:
            raise XcovError(
                "INTERNAL_CONTRACT_ERROR",
                "registry action does not match request action",
                registry_action=self.name,
            )
        validate_action_request(req)

    @property
    def request_schema(self) -> Json:
        return schema_for_action(self.name, "request")

    @property
    def response_schema(self) -> Json:
        return schema_for_action(self.name, "response")

    def validate_response(self, rsp: Json) -> None:
        validate_action_response(self.name, rsp)


ACTION_REGISTRY: Dict[str, ActionContract] = {
    "actions": ActionContract(
        "actions", "_actions", False,
        "Discover every canonical xcov.v1 action and its selection boundary.",
        "Do not use when the exact request or response schema for one known action is needed.",
    ),
    "schema": ActionContract(
        "schema", "_schema", False,
        "Read the strict request or response contract for one canonical action.",
        "Do not use to execute a coverage query.",
    ),
    "session.open": ActionContract(
        "session.open", "_session_open", False,
        "Open exactly one requested VDB in a new named coverage session.",
        "Do not use an existing session_id; close it explicitly before opening another VDB under that name.",
    ),
    "session.status": ActionContract(
        "session.status", "_session_status", False,
        "Inspect one live coverage session without scanning coverage objects.",
        "Do not use to query coverage scores or holes.",
    ),
    "session.close": ActionContract(
        "session.close", "_session_close", False,
        "Close one live coverage session and release its backend.",
        "Do not use before all queries against that session are complete.",
    ),
    "tests.list": ActionContract(
        "tests.list", "_tests_list", True,
        "List coverage tests present in the opened VDB.",
        "Do not use for hierarchy scopes or coverage metrics.",
    ),
    "metrics.list": ActionContract(
        "metrics.list", "_metrics_list", True,
        "Summarize available coverage metrics for a scope and test.",
        "Do not use when hierarchy holes or individual source evidence are required.",
    ),
    "scope.summary": ActionContract(
        "scope.summary", "_scope", True,
        "Get the aggregate coverage score for one scope or top-level scopes.",
        "Do not use to enumerate child scopes or detailed uncovered objects.",
    ),
    "scope.children": ActionContract(
        "scope.children", "_scope", True,
        "Enumerate direct or recursive descendants of one hierarchy scope.",
        "Do not use for a name-pattern search across the selected subtree.",
    ),
    "scope.search": ActionContract(
        "scope.search", "_scope", True,
        "Find hierarchy scopes using query glob filters.",
        "Do not use when only direct children of a known scope are needed.",
    ),
    "code_coverage.summary": ActionContract(
        "code_coverage.summary", "_code_coverage", True,
        "Aggregate code-coverage scores by a declared grouping field.",
        "Do not use for hierarchy-level holes or detailed Markdown evidence.",
    ),
    "code_coverage.holes": ActionContract(
        "code_coverage.holes", "_code_coverage", True,
        "Find hierarchy scopes whose selected code metrics are below 100 percent.",
        "Do not use for individual uncovered bins; use export.code_coverage.",
    ),
    "functional_coverage.summary": ActionContract(
        "functional_coverage.summary", "_functional", True,
        "Aggregate functional coverage at covergroup, coverpoint, cross, or bin level.",
        "Do not use when only uncovered functional items are required.",
    ),
    "functional_coverage.holes": ActionContract(
        "functional_coverage.holes", "_functional", True,
        "List uncovered functional coverage items at selected levels.",
        "Do not use for code coverage or full Markdown export.",
    ),
    "source.map": ActionContract(
        "source.map", "_source_map", True,
        "Map a source file and line window to raw coverage objects.",
        "Do not use when source text plus per-line annotations are needed.",
    ),
    "source.annotate": ActionContract(
        "source.annotate", "_source_annotate", True,
        "Return source-window rows with coverage annotations.",
        "Do not use for a compact raw object lookup without source rows.",
    ),
    "assert.summary": ActionContract(
        "assert.summary", "_assert_report", True,
        "Summarize assertion attempts, successes, and basic coverage.",
        "Do not use for the detailed assertion Markdown report.",
    ),
    "export.code_coverage": ActionContract(
        "export.code_coverage", "_export", True,
        "Write detailed code-coverage holes to a Markdown artifact.",
        "Do not use for inline hierarchy summaries.",
    ),
    "export.functional_coverage": ActionContract(
        "export.functional_coverage", "_export", True,
        "Write detailed functional-coverage holes to a Markdown artifact.",
        "Do not use for inline functional coverage rows.",
    ),
    "export.assert": ActionContract(
        "export.assert", "_export", True,
        "Write detailed assertion coverage evidence to a Markdown artifact.",
        "Do not use for the compact assertion summary.",
    ),
    "exclude.list": ActionContract(
        "exclude.list", "_exclude_list", True,
        "List compile-time and report-time exclusions with session-local coverage references.",
        'Do not use with a concrete test; P0 exclusion management requires test="merged".',
    ),
    "exclude.load": ActionContract(
        "exclude.load", "_exclude_load", True,
        "Load one or more native EL files in order using pynpi union semantics.",
        "Do not concatenate or parse native EL text.",
    ),
    "exclude.add": ActionContract(
        "exclude.add", "_exclude_set", True,
        "Set report-time exclusion state for exact coverage references.",
        "Do not use semantic selectors; resolve them to coverage_ref first.",
    ),
    "exclude.remove": ActionContract(
        "exclude.remove", "_exclude_set", True,
        "Clear report-time exclusion state for exact coverage references.",
        "Do not use to remove immutable compile-time exclusions.",
    ),
    "export.exclude": ActionContract(
        "export.exclude", "_export_exclude", True,
        'Export current merged-test exclusions with save_exclude_file(path, "w").',
        "Do not request append or strict-save modes.",
    ),
    "exclude.unload_all": ActionContract(
        "exclude.unload_all", "_exclude_unload_all", True,
        "Clear all report-time exclusions after explicit confirmation.",
        "Do not use as an implementation of single-object removal.",
    ),
    "exclude.csv.validate": ActionContract(
        "exclude.csv.validate", "_exclude_csv_validate", False,
        "Validate the three grouped exclusion CSV source files.",
        "Do not use to access a VDB or mutate CSV files.",
    ),
    "exclude.csv.status": ActionContract(
        "exclude.csv.status", "_exclude_csv_git", False,
        "Compare each source group commit and worktree state.",
        "Do not use to resolve coverage objects in a VDB.",
    ),
    "exclude.csv.impact": ActionContract(
        "exclude.csv.impact", "_exclude_csv_git", False,
        "Classify source changes independently for every CSV group.",
        "Do not use to stamp commits or mutate exclusions.",
    ),
    "exclude.csv.resolve": ActionContract(
        "exclude.csv.resolve", "_exclude_csv_resolve", True,
        "Read-only resolve every CSV selector against the current merged VDB.",
        "Do not use to apply exclusions.",
    ),
    "exclude.csv.apply": ActionContract(
        "exclude.csv.apply", "_exclude_csv_apply", True,
        "Resolve and apply all exactly matched CSV exclusions to the current session.",
        "Do not publish native EL artifacts.",
    ),
    "exclude.csv.compile": ActionContract(
        "exclude.csv.compile", "_exclude_csv_compile", True,
        "Validate, resolve, apply, and atomically publish three native EL files.",
        "Do not publish partial output when any selector fails.",
    ),
    "exclude.csv.rebase": ActionContract(
        "exclude.csv.rebase", "_exclude_csv_rebase", False,
        "Generate rename and pure-line-shift review suggestions.",
        "Do not automatically accept source-content changes.",
    ),
    "exclude.csv.stamp_changed": ActionContract(
        "exclude.csv.stamp_changed", "_exclude_csv_stamp", True,
        "Stamp only clean source groups whose selectors all resolve exactly.",
        "Do not stamp dirty, missing, or ambiguous groups.",
    ),
    "exclude.csv.format": ActionContract(
        "exclude.csv.format", "_exclude_csv_format", False,
        "Check stable grouped CSV ordering, or write it only with write=true.",
        "Do not change exclusion semantics.",
    ),
}

if set(ACTION_REGISTRY) != set(schema_actions()):
    raise RuntimeError("xcov action registry and schema catalog are inconsistent")
if any(name != contract.name for name, contract in ACTION_REGISTRY.items()):
    raise RuntimeError("xcov action registry keys and bound contracts are inconsistent")


def _safe_error_response(req: Json, exc: XcovError) -> Json:
    detail = dict(exc.detail)
    if "action" in detail:
        detail["requested_action"] = detail.pop("action")
    action = req.get("action")
    request_id = req.get("request_id")
    response_action = ""
    if isinstance(action, str):
        try:
            response_action = validate_action_token(action)
        except XcovError:
            response_action = ""
    return error_response(
        response_action,
        request_id if isinstance(request_id, str) and request_id else "req-unknown",
        exc.code,
        exc.message,
        **detail,
    )


class Dispatcher:
    def __init__(self, sessions: SessionManager | None = None) -> None:
        self.sessions = sessions or SessionManager()

    def dispatch(self, req: Json) -> Json:
        start = time.monotonic()
        action = req.get("action", "")
        sid = _log_session_id(req)
        log_action_event("public", sid, action, "begin", True, 0,
                         {"request": request_summary_for_log(req)})
        try:
            validate_action_token(action)
            contract = ACTION_REGISTRY.get(str(action))
            if contract is None:
                raise XcovError("UNKNOWN_ACTION", "unknown action", action=action)
            contract.validate_request(req)
            normalized = normalize_request(req)
            action = normalized["action"]
            handler = getattr(self, contract.handler)
            if contract.needs_session:
                rsp = handler(normalized, self._session(normalized))
            else:
                rsp = handler(normalized)
            contract.validate_response(rsp)
            elapsed = int((time.monotonic() - start) * 1000)
            log_action_event("public", _response_log_session_id(normalized, rsp), action, "end",
                             bool(rsp.get("ok")), elapsed,
                             {"response": response_summary_for_log(rsp)})
            return rsp
        except XcovError as exc:
            rsp = _safe_error_response(req, exc)
            validate_action_response(str(action), rsp)
            elapsed = int((time.monotonic() - start) * 1000)
            log_action_event("public", sid, action, "end", False, elapsed,
                             {"response": response_summary_for_log(rsp)})
            return rsp
        except Exception as exc:
            raw_action = req.get("action")
            raw_request_id = req.get("request_id")
            rsp = error_response(
                raw_action if isinstance(raw_action, str) else "",
                raw_request_id
                if isinstance(raw_request_id, str) and raw_request_id
                else "req-unknown",
                "INTERNAL_ERROR",
                str(exc),
            )
            validate_action_response(str(action), rsp)
            elapsed = int((time.monotonic() - start) * 1000)
            log_action_event("public", sid, action, "end", False, elapsed,
                             {"response": response_summary_for_log(rsp)})
            return rsp

    def _session(self, req: Json):
        sid = req.get("target", {}).get("session_id")
        if not sid:
            raise XcovError("SESSION_NOT_FOUND", "target.session_id is required")
        return self.sessions.get(str(sid))

    def _actions(self, req: Json) -> Json:
        rows = [
            {
                "name": action,
                "status": "p0",
                "api_version": "xcov.v1",
                "use_when": contract.use_when,
                "do_not_use_when": contract.do_not_use_when,
            }
            for action, contract in ACTION_REGISTRY.items()
        ]
        return ok_response(
            req,
            completeness_summary(len(rows), len(rows)),
            {"items": rows},
        )

    def _schema(self, req: Json) -> Json:
        action = action_args(req).get("action")
        if action not in ACTION_REGISTRY:
            raise XcovError("UNKNOWN_ACTION", "schema action not found", requested_action=action)
        kind = str(action_args(req).get("kind", "request"))
        try:
            schema = schema_for_action(str(action), kind)
        except KeyError:
            raise XcovError("UNKNOWN_ACTION", "schema action not found",
                            requested_action=action, kind=kind)
        return ok_response(
            req,
            completeness_summary(1, 1),
            {"schema": schema},
        )

    def _session_open(self, req: Json) -> Json:
        target = req.get("target", {})
        args = action_args(req)
        vdb = target.get("vdb")
        if not vdb:
            raise XcovError("VDB_OPEN_FAILED", "target.vdb is required")
        self.sessions.require_available(args.get("name"))
        manifest_details = validate_run_manifest(target)
        sess = self.sessions.open(
            str(vdb),
            name=args.get("name"),
            exclusion_policy=str(args.get("exclusion_policy", "default")),
        )
        session_json = sess.public_json()
        update_session_manifest(sess.session_id, session_json)
        return ok_response(
            req,
            completeness_summary(1, 1),
            {
                "session": session_json,
                "resource_snapshot": {
                    "vdb": sess.vdb,
                    "run_manifest": manifest_details,
                },
            },
        )

    def _session_status(self, req: Json) -> Json:
        sess = self._session(req)
        return ok_response(
            req,
            completeness_summary(1, 1),
            {"session": sess.public_json(), "cached_indexes": "lazy"},
        )

    def _session_close(self, req: Json) -> Json:
        sid = req.get("target", {}).get("session_id")
        sess = self.sessions.close(str(sid))
        session_json = sess.public_json()
        update_session_manifest(sess.session_id, session_json)
        return ok_response(
            req,
            completeness_summary(1, 1),
            {"session": session_json},
        )

    def _tests_list(self, req: Json, sess) -> Json:
        args = action_args(req)
        query = query_args("tests.list", args)
        rows = filter_items(sess.backend.tests(), query)
        summary, inline, warnings = apply_output("tests.list", args, rows)
        summary["session_id"] = sess.session_id
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _metrics_list(self, req: Json, sess) -> Json:
        args = action_args(req)
        items = sess.backend.items(scope=args.get("scope"), test=str(args.get("test", "merged")))
        rows = _summary_from_items(_coverage_score_rows(items), "metric")
        rows = _project_code_coverage_summary_rows(rows)
        summary, inline, warnings = apply_output("metrics.list", args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": args.get("test", "merged")})
        return ok_response(req, summary, {"items": inline}, warnings)

    def _scope(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        query = query_args(action, args)
        scopes = _indexed_scopes(sess.backend.scopes())
        metrics = _selector_or_default(args, "metrics", METRICS)
        items = sess.backend.items(metrics=metrics, scope=args.get("scope"),
                                  test=str(args.get("test", "merged")))
        items = _coverage_score_rows(items)
        coverage = _scope_coverage(items, metrics)
        if action == "scope.summary":
            rows = _scope_summary_rows(scopes, coverage, args)
            rows = _project_scope_summary_rows(rows)
        elif action == "scope.children":
            rows = _scope_children_rows(scopes, coverage, args)
            rows = _project_scope_brief_rows(rows)
        else:
            rows = _scope_search_rows(scopes, coverage, args)
            rows = _project_scope_brief_rows(rows)
        rows = filter_items(rows, query)
        rows = sort_items(action, rows, args.get("sort"))
        summary, inline, warnings = apply_output(action, args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": args.get("test", "merged")})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _code_coverage(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        query = query_args(action, args)
        metrics = _selector_or_default(args, "metrics", _code_metrics())
        already_filtered = False
        if action == "code_coverage.holes":
            scopes = _indexed_scopes(sess.backend.scopes())
            items = sess.backend.items(metrics=metrics, scope=args.get("scope"),
                                      test=str(args.get("test", "merged")))
            rows = _code_coverage_hole_scope_rows(scopes, _coverage_score_rows(items), metrics, args)
            rows = _project_code_coverage_hole_rows(rows)
        else:
            rows = sess.backend.items(metrics=metrics, scope=args.get("scope"),
                                      test=str(args.get("test", "merged")))
            rows = _coverage_score_rows(rows)
            rows = _summary_from_items(rows, str(args.get("group_by", "metric")))
            rows = filter_items(rows, query)
            rows = _project_code_coverage_summary_rows(rows)
            already_filtered = True
        if not already_filtered:
            rows = filter_items(rows, query)
        rows = sort_items(action, rows, args.get("sort"))
        summary, inline, warnings = apply_output(action, args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": args.get("test", "merged"), "metrics": metrics})
        if action == "code_coverage.holes":
            summary["note"] = ("Detailed uncovered code coverage items are available via "
                               "export.code_coverage. For complex processing, use x-npi "
                               "and learn the pynpi coverage APIs.")
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _functional(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        query = query_args(action, args)
        rows = sess.backend.items(metrics=["functional"], scope=args.get("scope"),
                                  test=str(args.get("test", "merged")),
                                  functional_only=True)
        if action == "functional_coverage.holes":
            rows = _filter_functional_levels(rows, args.get("levels"))
            rows = [row for row in rows if row["missing"] > 0]
            rows = filter_items(rows, query)
            rows = _project_functional_coverage_hole_rows(rows)
        else:
            group_by = str(args.get("group_by", "covergroup"))
            rows = _functional_summary_rows(rows, group_by)
            rows = filter_items(rows, query)
            rows = _project_functional_coverage_summary_rows(rows, group_by)
        rows = sort_items(action, rows, args.get("sort"))
        summary, inline, warnings = apply_output(action, args, rows)
        summary.update({"session_id": sess.session_id, "test": args.get("test", "merged")})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _source_map(self, req: Json, sess) -> Json:
        args = action_args(req)
        query = query_args("source.map", args)
        file_name = args.get("file")
        line = args.get("line")
        window = int(args.get("window", 0))
        if file_name is None or line is None:
            raise XcovError("SCHEMA_INVALID", "source.map requires file and line")
        metrics = args.get("metrics")
        lo, hi = int(line) - window, int(line) + window
        rows = []
        items = sess.backend.items(metrics=metrics, test=str(args.get("test", "merged")))
        for item in _coverage_score_rows(items):
            ev = item["evidence"]
            if (
                _file_matches(ev["file"], file_name)
                and ev["line"] is not None
                and lo <= ev["line"] <= hi
            ):
                rows.append(item)
        rows = filter_items(rows, query)
        summary, inline, warnings = apply_output("source.map", args, rows)
        summary.update({"session_id": sess.session_id, "file": file_name, "line": line,
                        "window": window})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _source_annotate(self, req: Json, sess) -> Json:
        args = action_args(req)
        query = query_args("source.annotate", args)
        file_name = args.get("file")
        line = args.get("line")
        window = int(args.get("window", 3))
        include_source_text = bool(args.get("include_source_text", True))
        include_covered = bool(args.get("include_covered", True))
        if file_name is None or line is None:
            raise XcovError("SCHEMA_INVALID", "source.annotate requires file and line")
        metrics = args.get("metrics")
        lo, hi = int(line) - window, int(line) + window
        items = sess.backend.items(metrics=metrics, test=str(args.get("test", "merged")))
        rows = []
        by_line: Dict[int, List[Json]] = defaultdict(list)
        source_path = str(file_name)
        for item in _coverage_score_rows(items):
            ev = item["evidence"]
            if not _file_matches(ev["file"], file_name) or ev["line"] is None:
                continue
            item_line = ev["line"]
            if lo <= item_line <= hi:
                if ev["file"] is not None:
                    source_path = ev["file"]
                if include_covered or item["missing"] > 0:
                    by_line[item_line].append(item)
        source_lines = _read_source_window(source_path, lo, hi) if include_source_text else {}
        for line_no in range(lo, hi + 1):
            line_items = filter_items(by_line.get(line_no, []), query)
            if line_items or line_no in source_lines:
                rows.append({
                    "file": str(file_name),
                    "line": line_no,
                    "source": source_lines.get(line_no),
                    "annotations": [_source_annotation(item) for item in line_items],
                    "annotation_count": len(line_items),
                })
        summary, inline, warnings = apply_output("source.annotate", args, rows)
        summary.update({"session_id": sess.session_id, "file": file_name, "line": line,
                        "window": window, "include_source_text": include_source_text})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _assert_report(self, req: Json, sess) -> Json:
        args = action_args(req)
        query = query_args("assert.summary", args)
        rows, _sections = _assert_report_rows(sess.backend.items(metrics=["assert"], scope=args.get("scope"),
                                                                test=str(args.get("test", "merged"))),
                                              include_source=False)
        rows = _project_assert_summary_rows(rows)
        rows = filter_items(rows, query)
        rows = sort_items("assert.summary", rows, args.get("sort"))
        summary, inline, warnings = apply_output("assert.summary", args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": args.get("test", "merged")})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _export(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        threshold = float(args.get("threshold_pct", 100.0))
        output_path = _export_output_path(args)
        if action == "export.code_coverage":
            rows = _coverage_score_rows(sess.backend.items(
                metrics=_selector_or_default(
                    args,
                    "metrics",
                    _code_metrics(),
                ),
                scope=args.get("scope"),
                test=str(args.get("test", "merged"))))
            markdown, exported_count = _code_coverage_markdown(rows, threshold)
        elif action == "export.functional_coverage":
            rows = sess.backend.items(metrics=["functional"], scope=args.get("scope"),
                                      test=str(args.get("test", "merged")),
                                      functional_only=True)
            markdown, exported_count = _functional_coverage_markdown(
                rows, threshold, covergroup_filter=args.get("covergroup"))
        elif action == "export.assert":
            rows, sections = _assert_report_rows(sess.backend.items(
                metrics=["assert"], scope=args.get("scope"),
                test=str(args.get("test", "merged"))),
                include_source=True)
            markdown, exported_count = _assert_markdown(rows, sections, threshold)
        else:
            raise XcovError("UNKNOWN_ACTION", "unknown export action", action=action)
        resolved = _write_markdown_artifact(output_path, markdown,
                                            bool((args.get("output") or {}).get("allow_absolute_path")))
        summary = {
            "session_id": sess.session_id,
            "scope": args.get("scope"),
            "test": args.get("test", "merged"),
            "threshold_pct": threshold,
            **completeness_summary(exported_count, 0),
            "output_mode": "file",
            "output_path": resolved,
            "artifact_format": "md",
            "note": ("Markdown export only. For complex processing, use x-npi and "
                     "learn the pynpi coverage APIs."),
        }
        return ok_response(req, summary, {})

    def _exclude_list(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        rows = [
            _exclusion_row(row)
            for row in sess.backend.items(test="merged")
            if (
                "excluded_at_compile_time" in row["status"]
                or "excluded_at_report_time" in row["status"]
            )
        ]
        summary, inline, warnings = apply_output("exclude.list", args, rows)
        summary.update({"session_id": sess.session_id, "test": "merged"})
        return ok_response(req, summary, {"items": inline}, warnings)

    def _exclude_load(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        paths = [_existing_input_path(item, args) for item in args["paths"]]
        with tempfile.TemporaryDirectory(prefix=".xcov-load-") as temporary:
            baseline = Path(temporary) / "baseline.el"
            sess.backend.save_exclusions(str(baseline), test="merged")
            try:
                rows = sess.backend.load_exclusions(paths, test="merged")
            except Exception:
                sess.backend.unload_exclusions(test="merged")
                sess.backend.load_exclusions([str(baseline)], test="merged")
                raise
        return ok_response(
            req,
            completeness_summary(len(rows), len(rows)),
            {"items": rows},
        )

    def _exclude_set(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        excluded = req["action"] == "exclude.add"
        rows = [
            sess.backend.set_exclusion(ref, excluded, test="merged")
            for ref in args["coverage_refs"]
        ]
        return ok_response(
            req,
            completeness_summary(len(rows), len(rows)),
            {"items": rows},
        )

    def _export_exclude(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        path = _export_output_path(args)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        exported_count = sum(
            1
            for row in sess.backend.items(test="merged")
            if (
                "excluded_at_compile_time" in row["status"]
                or "excluded_at_report_time" in row["status"]
            )
        )
        sess.backend.save_exclusions(path, test="merged")
        summary = completeness_summary(exported_count, 0)
        summary.update({
            "session_id": sess.session_id,
            "test": "merged",
            "output_mode": "file",
            "output_path": path,
            "artifact_format": "el",
            "exported_count": exported_count,
        })
        return ok_response(req, summary, {})

    def _exclude_unload_all(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        if args.get("confirm") is not True:
            raise XcovError(
                "CONFIRMATION_REQUIRED",
                "exclude.unload_all requires confirm=true",
            )
        before = len([
            row for row in sess.backend.items(test="merged")
            if "excluded_at_report_time" in row["status"]
        ])
        sess.backend.unload_exclusions(test="merged")
        after = len([
            row for row in sess.backend.items(test="merged")
            if "excluded_at_report_time" in row["status"]
        ])
        return ok_response(
            req,
            completeness_summary(1, 1),
            {"items": [{"before_count": before, "after_count": after, "status": "changed"}]},
        )

    def _exclude_csv_validate(self, req: Json) -> Json:
        documents = parse_directory(_csv_directory(req))
        rows = [
            {
                "coverage_kind": document.kind,
                "path": str(document.path),
                "group_count": len(document.groups),
                "record_count": document.row_count,
                "status": "valid",
            }
            for document in documents
        ]
        return _items_ok(req, rows)

    def _exclude_csv_git(self, req: Json) -> Json:
        args = action_args(req)
        documents = parse_directory(_csv_directory(req))
        rows = git_group_status(
            documents,
            str(args.get("repo_root", os.getcwd())),
        )
        return _items_ok(req, rows)

    def _exclude_csv_resolve(self, req: Json, sess) -> Json:
        documents, rows = _resolve_csv(req, sess)
        del documents
        return _items_ok(req, rows)

    def _exclude_csv_apply(self, req: Json, sess) -> Json:
        _documents, resolutions = _resolve_csv(req, sess)
        failures = [row for row in resolutions if row["status"] != "matched"]
        if failures:
            raise XcovError(
                "EXCLUSION_RESOLVE_FAILED",
                "every CSV record must resolve exactly once before apply",
                failed_count=len(failures),
            )
        rows = _apply_csv_refs_transactionally(sess, resolutions)
        return _items_ok(req, rows)

    def _exclude_csv_compile(self, req: Json, sess) -> Json:
        args = action_args(req)
        documents, resolutions = _resolve_csv(req, sess)
        failures = [row for row in resolutions if row["status"] != "matched"]
        if failures:
            raise XcovError(
                "EXCLUSION_RESOLVE_FAILED",
                "compile publishes nothing unless every CSV record resolves exactly once",
                failed_count=len(failures),
            )
        output_dir = Path(args.get("output_directory", _csv_directory(req)))
        if output_dir.is_absolute() and not args.get("allow_absolute_path", False):
            raise XcovError(
                "OUTPUT_PATH_UNSAFE",
                "absolute output_directory requires allow_absolute_path=true",
                path=str(output_dir),
            )
        if any(part == ".." for part in output_dir.parts):
            raise XcovError(
                "OUTPUT_PATH_UNSAFE",
                "output_directory must not contain '..'",
                path=str(output_dir),
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        published: List[Json] = []
        with tempfile.TemporaryDirectory(
            prefix=".xcov-exclusions-",
            dir=str(output_dir),
        ) as temporary:
            temp_root = Path(temporary)
            temp_paths: Dict[str, Path] = {}
            baseline = temp_root / "baseline.el"
            sess.backend.save_exclusions(str(baseline), test="merged")
            try:
                sess.backend.unload_exclusions(test="merged")
                for document in documents:
                    kind_rows = [
                        row for row in resolutions
                        if row["coverage_kind"] == document.kind
                    ]
                    for row in kind_rows:
                        result = sess.backend.set_exclusion(
                            row["coverage_refs"][0],
                            True,
                            test="merged",
                        )
                        if result["status"] == "failed":
                            raise XcovError(
                                "EXCLUSION_APPLY_FAILED",
                                "compile setter failed; no artifacts were published",
                                coverage_kind=document.kind,
                            )
                    temp_path = temp_root / f"{document.kind}.el"
                    sess.backend.save_exclusions(str(temp_path), test="merged")
                    temp_paths[document.kind] = temp_path
                    sess.backend.unload_exclusions(test="merged")
                backups: Dict[str, Path] = {}
                replaced: List[str] = []
                try:
                    for kind in ("code", "functional", "assertion"):
                        destination = output_dir / f"{kind}.el"
                        if destination.exists():
                            backup = temp_root / f"{kind}.previous.el"
                            os.replace(destination, backup)
                            backups[kind] = backup
                        os.replace(temp_paths[kind], destination)
                        replaced.append(kind)
                        published.append({
                            "coverage_kind": kind,
                            "path": str(destination),
                            "status": "published",
                        })
                    sess.backend.load_exclusions(
                        [
                            str(output_dir / f"{kind}.el")
                            for kind in ("code", "functional", "assertion")
                        ],
                        test="merged",
                    )
                except Exception:
                    for kind in reversed(("code", "functional", "assertion")):
                        destination = output_dir / f"{kind}.el"
                        if kind in replaced and destination.exists():
                            destination.unlink()
                        if kind in backups:
                            os.replace(backups[kind], destination)
                    raise
            except Exception:
                sess.backend.unload_exclusions(test="merged")
                sess.backend.load_exclusions([str(baseline)], test="merged")
                raise
        return _items_ok(req, published)

    def _exclude_csv_rebase(self, req: Json) -> Json:
        args = action_args(req)
        documents = parse_directory(_csv_directory(req))
        rows = rebase_suggestions(
            documents,
            str(args.get("repo_root", os.getcwd())),
        )
        rows.extend(suggested_patches(documents, rows))
        if args.get("write") is True:
            rows.extend(apply_rebase_suggestions(documents, rows))
        report = review_markdown(rows)
        output = args.get("review_output")
        if output:
            path = resolve_artifact_path(
                output["path"],
                bool(output.get("allow_absolute_path", False)),
            )
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(report, encoding="utf-8")
        return _items_ok(req, rows)

    def _exclude_csv_stamp(self, req: Json, sess) -> Json:
        args = action_args(req)
        documents, resolutions = _resolve_csv(req, sess)
        rows = stamp_documents(
            documents,
            str(args.get("repo_root", os.getcwd())),
            resolutions,
        )
        return _items_ok(req, rows)

    def _exclude_csv_format(self, req: Json) -> Json:
        args = action_args(req)
        rows = format_directory(
            _csv_directory(req),
            write=bool(args.get("write", False)),
        )
        return _items_ok(req, rows)


def action_args(req: Json) -> Json:
    return dict(req.get("args") or {})


def _items_ok(req: Json, rows: List[Json]) -> Json:
    return ok_response(
        req,
        completeness_summary(len(rows), len(rows)),
        {"items": rows},
    )


def _require_merged(args: Json) -> None:
    test = str(args.get("test", "merged"))
    if test != "merged":
        raise XcovError(
            "TEST_MODE_NOT_SUPPORTED",
            'exclusion management requires test="merged"',
            test=test,
        )


def _existing_input_path(path: str, args: Json) -> str:
    candidate = Path(path)
    if candidate.is_absolute() and not args.get("allow_absolute_path", False):
        raise XcovError(
            "ABSOLUTE_PATH_NOT_ALLOWED",
            "absolute exclusion input path requires allow_absolute_path=true",
            path=path,
        )
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise XcovError(
            "EXCLUSION_FILE_NOT_FOUND",
            "native exclusion file does not exist",
            path=str(resolved),
        )
    return str(resolved)


def _exclusion_row(row: Json) -> Json:
    evidence = row["evidence"]
    return {
        "coverage_ref": row["coverage_ref"],
        "metric": row["metric"],
        "type": row["type"],
        "scope": row["scope"],
        "name": row["name"],
        "full_name": row["full_name"],
        "file": evidence.get("file"),
        "line": evidence.get("line"),
        "compile_time": "excluded_at_compile_time" in row["status"],
        "report_time": "excluded_at_report_time" in row["status"],
        "status": row["status"],
    }


def _csv_directory(req: Json) -> str:
    return str(action_args(req).get("directory", "coverage_exclusions"))


def _resolve_csv(req: Json, sess) -> tuple[List[Any], List[Json]]:
    args = action_args(req)
    _require_merged(args)
    documents = parse_directory(_csv_directory(req))
    rows = sess.backend.items(test="merged")
    return documents, resolve_documents(documents, rows)


def _apply_csv_refs_transactionally(sess, resolutions: List[Json]) -> List[Json]:
    with tempfile.TemporaryDirectory(prefix=".xcov-apply-") as temporary:
        baseline = Path(temporary) / "baseline.el"
        sess.backend.save_exclusions(str(baseline), test="merged")
        rows: List[Json] = []
        try:
            for resolution in resolutions:
                result = sess.backend.set_exclusion(
                    resolution["coverage_refs"][0],
                    True,
                    test="merged",
                )
                rows.append(result)
                if result["status"] == "failed":
                    raise XcovError(
                        "EXCLUSION_APPLY_FAILED",
                        "one or more report-time exclusion setters failed",
                        failed_count=1,
                    )
        except Exception:
            sess.backend.unload_exclusions(test="merged")
            sess.backend.load_exclusions([str(baseline)], test="merged")
            raise
    return rows


def _selector_or_default(
    args: Json,
    field: str,
    default: Iterable[str],
) -> List[str]:
    if field not in args:
        return list(default)
    selected = args[field]
    if not isinstance(selected, list) or not selected:
        raise XcovError(
            "INVALID_SELECTOR",
            f"args.{field} must be a non-empty array when provided",
            field=f"args.{field}",
        )
    return list(selected)


def _log_session_id(req: Json) -> str:
    target = req.get("target") if isinstance(req.get("target"), dict) else {}
    args = req.get("args") if isinstance(req.get("args"), dict) else {}
    if target.get("session_id"):
        return str(target["session_id"])
    if req.get("action") == "session.open" and args.get("name"):
        return str(args["name"])
    return "adhoc"


def _response_log_session_id(req: Json, rsp: Json) -> str:
    data = rsp.get("data") if isinstance(rsp.get("data"), dict) else {}
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    if session.get("session_id"):
        return str(session["session_id"])
    return _log_session_id(req)


def _scope_parent(full_name: str) -> Optional[str]:
    if "." not in full_name:
        return None
    return full_name.rsplit(".", 1)[0]


def _scope_ancestors(scope: str) -> Iterable[str]:
    parts = str(scope).split(".")
    for idx in range(1, len(parts) + 1):
        yield ".".join(parts[:idx])


def _indexed_scopes(scopes: List[Json]) -> Dict[str, Json]:
    return {
        row["full_name"]: row
        for row in sorted(scopes, key=lambda item: (item["depth"], item["full_name"]))
    }


def _is_descendant(scope: str, root: str) -> bool:
    return scope == root or scope.startswith(root + ".")


def _is_direct_child(scope: str, parent: Optional[str]) -> bool:
    return _scope_parent(scope) == parent


def _scope_search_rows(scopes: Dict[str, Json], coverage: Dict[str, Json], args: Json) -> List[Json]:
    root = args.get("scope")
    rows = list(scopes.values())
    if root:
        rows = [r for r in rows if _is_descendant(r["full_name"], str(root))]
    return [_merge_scope_coverage(r, coverage.get(r["full_name"])) for r in rows]


def _scope_summary_rows(scopes: Dict[str, Json], coverage: Dict[str, Json], args: Json) -> List[Json]:
    root = args.get("scope")
    if root:
        full = str(root)
        if full not in scopes:
            raise XcovError("SCOPE_NOT_FOUND", "coverage scope not found", scope=full)
        return [_merge_scope_coverage(scopes[full], coverage.get(full))]
    top_names = [name for name, row in scopes.items() if row["depth"] == 0]
    return [_merge_scope_coverage(scopes[name], coverage.get(name)) for name in top_names]


def _scope_children_rows(scopes: Dict[str, Json], coverage: Dict[str, Json], args: Json) -> List[Json]:
    root = args.get("scope")
    parent = str(root) if root else None
    recursive = bool(args.get("recursive", False))
    out = []
    for full, row in scopes.items():
        if root:
            selected = _is_descendant(full, parent) and full != parent if recursive else _is_direct_child(full, parent)
        else:
            selected = row["depth"] == 0
        if selected:
            out.append(_merge_scope_coverage(row, coverage.get(full)))
    return out


def _scope_coverage(items: List[Json], metrics: List[str]) -> Dict[str, Json]:
    grouped: Dict[str, Dict[str, List[Json]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        scope = item["scope"]
        if scope is None:
            continue
        metric = item["metric"]
        for ancestor in _scope_ancestors(scope):
            grouped[ancestor][metric].append(item)
    out: Dict[str, Json] = {}
    for scope, by_metric in grouped.items():
        metric_rows = []
        total_covered = 0
        total_coverable = 0
        for metric in metrics:
            subset = by_metric.get(metric, [])
            if metric == "functional":
                subset = _functional_summary_level_rows(subset, "covergroup")
            if not subset:
                continue
            coverable = sum(i["coverable"] for i in subset)
            covered = sum(i["covered"] for i in subset)
            total_covered += covered
            total_coverable += coverable
            metric_rows.append({"metric": metric, "covered": covered, "coverable": coverable,
                                "missing": coverable - covered,
                                "coverage_pct": coverage_pct(covered, coverable)})
        out[scope] = {"covered": total_covered, "coverable": total_coverable,
                      "missing": total_coverable - total_covered,
                      "coverage_pct": coverage_pct(total_covered, total_coverable),
                      "metrics": metric_rows}
    return out


def _coverage_score_rows(items: List[Json]) -> List[Json]:
    """Rows that contribute to URG dashboard-style code coverage totals."""
    return [item for item in items if is_score_bearing_row(item)]


def _merge_scope_coverage(scope: Json, cov: Optional[Json]) -> Json:
    out = dict(scope)
    cov = cov or {"covered": 0, "coverable": 0, "missing": 0,
                  "coverage_pct": None, "metrics": []}
    for key in ("covered", "coverable", "missing", "coverage_pct"):
        out[key] = cov.get(key)
    ev = out.pop("evidence", None)
    if isinstance(ev, dict):
        out["file"] = ev.get("file")
        out["line"] = ev.get("line")
    metrics = cov.get("metrics") if isinstance(cov.get("metrics"), list) else []
    for metric in METRICS:
        row = next((m for m in metrics if m.get("metric") == metric), None)
        out[f"{metric}_pct"] = row.get("coverage_pct") if row else None
    return out


def _project_columns(row: Json, columns: List[str]) -> Json:
    return {key: row.get(key) for key in columns}


def _project_scope_brief_rows(rows: List[Json]) -> List[Json]:
    return [_project_columns(row, ["name", "full_name", "coverage_pct"]) for row in rows]


def _project_scope_summary_rows(rows: List[Json]) -> List[Json]:
    columns = [
        "name", "full_name", "covered", "coverable", "missing", "coverage_pct",
        "line_pct", "toggle_pct", "branch_pct", "condition_pct",
        "fsm_pct", "assert_pct", "functional_pct", "file", "line",
    ]
    return [_project_columns(row, columns) for row in rows]


def _project_code_coverage_summary_rows(rows: List[Json]) -> List[Json]:
    forbidden = {"name", "full_name", "functional_pct"}
    return [{key: value for key, value in row.items() if key not in forbidden}
            for row in rows]


def _project_code_coverage_hole_rows(rows: List[Json]) -> List[Json]:
    columns = [
        "name", "full_name", "coverage_pct",
        "line_pct", "toggle_pct", "branch_pct", "condition_pct",
        "fsm_pct", "assert_pct",
    ]
    return [_project_columns(row, columns) for row in rows]


def _project_functional_coverage_summary_rows(rows: List[Json], group_by: str) -> List[Json]:
    columns = [
        group_by, "covered", "coverable", "missing",
        "coverage_pct",
    ]
    return [_project_columns(row, columns) for row in rows]


def _project_functional_coverage_hole_rows(rows: List[Json]) -> List[Json]:
    out: List[Json] = []
    for row in rows:
        ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        projected = _project_columns(row, [
            "covergroup", "coverpoint", "cross", "bin",
            "covered", "coverable", "count", "coverage_pct", "status",
        ])
        projected["file"] = ev.get("file")
        projected["line"] = ev.get("line")
        out.append(projected)
    return out


def _project_assert_summary_rows(rows: List[Json]) -> List[Json]:
    columns = [
        "name", "full_name", "covered", "coverable", "missing",
        "coverage_pct", "status", "attempts", "real_successes",
        "without_attempts",
    ]
    return [_project_columns(row, columns) for row in rows]


def _code_metrics() -> List[str]:
    return [m for m in METRICS if m != "functional"]


def _code_coverage_hole_scope_rows(scopes: Dict[str, Json], items: List[Json],
                                   metrics: List[str], args: Json) -> List[Json]:
    coverage = _scope_coverage(items, metrics)
    current = _scope_summary_rows(scopes, coverage, args)
    children = _scope_children_rows(scopes, coverage, args)
    seen = set()
    rows = []
    for row in current + children:
        full = row.get("full_name")
        if full in seen:
            continue
        seen.add(full)
        rows.append(row)
    return [
        row
        for row in rows
        if any(_pct_is_below_100(row[f"{metric}_pct"]) for metric in metrics)
    ]


def _pct_is_below_100(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "derived coverage percentage is not numeric",
            field="coverage_pct",
        )
    return value < 100.0


def _summary_from_items(items: List[Json], group_by: str) -> List[Json]:
    groups: Dict[str, List[Json]] = defaultdict(list)
    for item in items:
        if group_by == "source_file":
            key = item["evidence"]["file"] or "<unknown>"
        elif group_by == "metric":
            key = item["metric"]
        elif group_by == "scope":
            key = item["scope"] or "<unknown>"
        elif group_by == "type":
            key = item["type"]
        elif group_by in {"covergroup", "coverpoint", "cross", "bin"}:
            key = item.get(group_by) or "<unknown>"
        else:
            raise XcovError(
                "INTERNAL_CONTRACT_ERROR",
                "unsupported coverage summary grouping",
                group_by=group_by,
            )
        groups[key].append(item)
    rows: List[Json] = []
    for key, subset in groups.items():
        coverable = sum(i["coverable"] for i in subset)
        covered = sum(i["covered"] for i in subset)
        rows.append({group_by: key, "covered": covered, "coverable": coverable,
                     "missing": coverable - covered,
                     "coverage_pct": coverage_pct(covered, coverable),
                     "metric": key if group_by == "metric" else "summary",
                     "name": key, "full_name": key})
    return rows


def _file_matches(actual: Any, requested: Any) -> bool:
    if actual is None or requested is None:
        return False
    actual_s = str(actual)
    requested_s = str(requested)
    return actual_s == requested_s or actual_s.endswith(requested_s)


def _read_source_window(path: str, lo: int, hi: int) -> Dict[int, str]:
    out: Dict[int, str] = {}
    if lo < 1:
        lo = 1
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for idx, text in enumerate(fh, start=1):
                if idx < lo:
                    continue
                if idx > hi:
                    break
                out[idx] = text.rstrip("\n")
    except OSError as exc:
        raise XcovError(
            "SOURCE_READ_FAILED",
            "failed to read requested source text",
            path=path,
            cause_type=type(exc).__name__,
            cause_message=str(exc),
        ) from exc
    return out


def _source_annotation(item: Json) -> Json:
    ev = item["evidence"]
    out: Json = {
        "metric": item["metric"],
        "type": item["type"],
        "name": item["name"],
        "full_name": item["full_name"],
        "covered": item["covered"],
        "coverable": item["coverable"],
        "missing": item["missing"],
        "status": item["status"],
        "file": ev["file"],
        "line": ev["line"],
    }
    for key in ("branch", "branch_bin", "branch_terms", "condition", "condition_bin",
                "condition_terms", "toggle_signal", "toggle_bit", "toggle_transition",
                "assert_kind", "assert_object"):
        if item.get(key) not in (None, ""):
            out[key] = item.get(key)
    return out


def _toggle_transition_summary(rows: List[Json]) -> Json:
    out: Json = {}
    for wanted in ("0 -> 1", "1 -> 0", "npiCovToggle01", "npiCovToggle10"):
        matching = [row for row in rows if str(row.get("toggle_transition")) == wanted]
        if not matching:
            continue
        covered = sum(row["covered"] for row in matching)
        coverable = sum(row["coverable"] for row in matching)
        key = {"npiCovToggle01": "0 -> 1", "npiCovToggle10": "1 -> 0"}.get(wanted, wanted)
        out[key] = {"covered": covered, "coverable": coverable,
                    "missing": coverable - covered, "coverage_pct": coverage_pct(covered, coverable)}
    return out


ASSERT_OBJECT_TYPES = {"npiCovAssert", "npiCovCoverProperty", "npiCovCoverSequence"}
ASSERT_BIN_TO_FIELD = {
    "npiCovAttemptBin": "attempts",
    "npiCovSuccessBin": "real_successes",
    "npiCovFailureBin": "failures",
    "npiCovIncompleteBin": "incomplete",
    "npiCovFirstmatchBin": "first_match",
}


def _assert_report_rows(items: List[Json], include_source: bool) -> tuple[List[Json], Json]:
    objects = [row for row in items if row["type"] in ASSERT_OBJECT_TYPES]
    bins_by_object: Dict[str, List[Json]] = defaultdict(list)
    for row in items:
        if row["type"] in ASSERT_BIN_TO_FIELD:
            bins_by_object[row["assert_object"]].append(row)
    rows: List[Json] = []
    for obj in objects:
        full = obj["assert_object"]
        counts = _assert_counts(bins_by_object.get(full, []))
        row: Json = {
            "kind": obj["assert_kind"],
            "name": obj["name"],
            "full_name": full,
            "category": obj.get("category"),
            "severity": obj.get("severity"),
            "covered": obj["covered"],
            "coverable": obj["coverable"],
            "missing": obj["missing"],
            "coverage_pct": obj["coverage_pct"],
            "status": obj["status"],
            **counts,
        }
        if include_source:
            row["evidence"] = obj["evidence"]
        rows.append(row)
    sections = {
        "category_summary": _count_by(rows, "category"),
        "severity_summary": _count_by(rows, "severity"),
        "assert_summary": _kind_summary(rows, "assertion"),
        "cover_property_summary": _kind_summary(rows, "cover_property"),
        "cover_sequence_summary": _kind_summary(rows, "cover_sequence"),
    }
    return rows, sections


def _assert_counts(rows: List[Json]) -> Json:
    counts: Json = {
        "attempts": 0,
        "real_successes": 0,
        "failures": 0,
        "incomplete": 0,
        "first_match": 0,
    }
    for row in rows:
        field = ASSERT_BIN_TO_FIELD.get(row["type"])
        if not field:
            continue
        counts[field] += row["count"]
    if counts["attempts"] == 0:
        counts["without_attempts"] = 1
    else:
        counts["without_attempts"] = 0
    return counts


def _count_by(rows: List[Json], field: str) -> List[Json]:
    grouped: Dict[str, int] = defaultdict(int)
    for row in rows:
        key = row.get(field)
        if key is None:
            key = "unknown"
        grouped[str(key)] += 1
    return [{field: key, "count": count} for key, count in sorted(grouped.items())]


def _kind_summary(rows: List[Json], kind: str) -> Json:
    subset = [row for row in rows if row.get("kind") == kind]
    return {
        "kind": kind,
        "total": len(subset),
        "success": sum(1 for row in subset if row["missing"] == 0),
        "failure": sum(1 for row in subset if row["failures"] > 0),
        "incomplete": sum(1 for row in subset if row["incomplete"] > 0),
        "without_attempts": sum(row["without_attempts"] for row in subset),
        "attempts": sum(row["attempts"] for row in subset),
        "real_successes": sum(row["real_successes"] for row in subset),
        "first_match": sum(row["first_match"] for row in subset),
    }


def _first_evidence(rows: List[Json]) -> Json:
    for row in rows:
        ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        if ev.get("file") or ev.get("line") is not None:
            return dict(ev)
    return {}


def _export_output_path(args: Json) -> str:
    output = args.get("output") if isinstance(args.get("output"), dict) else {}
    path = output.get("path")
    if not path:
        raise XcovError("OUTPUT_PATH_REQUIRED", "output.path is required")
    return str(path)


def _write_markdown_artifact(path: str, text: str, allow_absolute_path: bool) -> str:
    resolved = resolve_artifact_path(path, allow_absolute_path=allow_absolute_path)
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
    except OSError as exc:
        raise XcovError("OUTPUT_WRITE_FAILED", str(exc), path=resolved) from exc
    return resolved


def _coverage_sort_key(row: Json) -> tuple[bool, float, str]:
    pct = row.get("coverage_pct")
    if pct is not None and (
        not isinstance(pct, (int, float)) or isinstance(pct, bool)
    ):
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "derived coverage percentage is not numeric",
            field="coverage_pct",
        )
    return (
        pct is None,
        0.0 if pct is None else float(pct),
        str(row.get("full_name") or row.get("name") or ""),
    )


def _below_threshold(row: Json, threshold: float) -> bool:
    pct = row.get("coverage_pct")
    if pct is None:
        return False
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "derived coverage percentage is not numeric",
            field="coverage_pct",
        )
    return float(pct) < threshold


def _evidence_loc(row: Json) -> str:
    ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    file_name = ev.get("file")
    line = ev.get("line")
    if file_name and line is not None:
        return f"{file_name}:{line}"
    if file_name:
        return str(file_name)
    return ""


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _yes_no_covered(value: Any) -> str:
    if value is None:
        return "unknown"
    if not isinstance(value, int) or isinstance(value, bool):
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "derived covered count is not an integer",
            field="covered",
        )
    return "yes" if value > 0 else "no"


def _code_coverage_markdown(rows: List[Json], threshold: float) -> tuple[str, int]:
    rows = [row for row in rows if row.get("metric") in _code_metrics() and _below_threshold(row, threshold)]
    rows.sort(key=_coverage_sort_key)
    lines = [
        "# Code Coverage Holes",
        "",
        f"Threshold: {threshold:g}%",
        "",
    ]
    exported = 0
    for metric in _code_metrics():
        subset = [row for row in rows if row.get("metric") == metric]
        lines.extend([f"## {metric}", ""])
        if not subset:
            lines.extend(["No items below threshold.", ""])
            continue
        if metric == "toggle":
            lines.extend([
                "| scope | signal | bit | 0->1 covered | 1->0 covered | coverage_pct | file:line |",
                "|---|---|---|---|---|---:|---|",
            ])
            for item in _toggle_export_rows(subset):
                exported += 1
                lines.append(
                    f"| {_md(item.get('scope'))} | {_md(item.get('signal'))} | {_md(item.get('bit'))} | "
                    f"{_md(item.get('0_to_1_covered'))} | {_md(item.get('1_to_0_covered'))} | "
                    f"{_md(item.get('coverage_pct'))} | {_md(item.get('location'))} |"
                )
        elif metric in {"branch", "condition", "fsm"}:
            label = {"branch": "branch/bin", "condition": "condition/bin", "fsm": "state/transition"}[metric]
            lines.extend([
                f"| scope | {label} | covered | coverage_pct | file:line |",
                "|---|---|---|---:|---|",
            ])
            for row in subset:
                exported += 1
                lines.append(
                    f"| {_md(row.get('scope'))} | {_md(_code_item_label(row))} | "
                    f"{_yes_no_covered(row.get('covered'))} | {_md(row.get('coverage_pct'))} | {_md(_evidence_loc(row))} |"
                )
        else:
            lines.extend([
                "| scope | object | covered | coverage_pct | file:line |",
                "|---|---|---|---:|---|",
            ])
            for row in subset:
                exported += 1
                lines.append(
                    f"| {_md(row.get('scope'))} | {_md(row.get('full_name') or row.get('name'))} | "
                    f"{_yes_no_covered(row.get('covered'))} | {_md(row.get('coverage_pct'))} | {_md(_evidence_loc(row))} |"
                )
        lines.append("")
    return "\n".join(lines), exported


def _toggle_export_rows(rows: List[Json]) -> List[Json]:
    grouped: Dict[tuple[str, str], List[Json]] = defaultdict(list)
    for row in rows:
        signal = str(row.get("toggle_signal") or row.get("full_name") or row.get("name") or "")
        bit = str(row.get("toggle_bit") or signal)
        grouped[(signal, bit)].append(row)
    out: List[Json] = []
    for (signal, bit), subset in grouped.items():
        transitions = _toggle_transition_summary(subset)
        covered = sum(row["covered"] for row in subset)
        coverable = sum(row["coverable"] for row in subset)
        out.append({
            "scope": subset[0].get("scope"),
            "signal": signal,
            "bit": bit,
            "0_to_1_covered": _yes_no_covered((transitions.get("0 -> 1") or {}).get("covered")),
            "1_to_0_covered": _yes_no_covered((transitions.get("1 -> 0") or {}).get("covered")),
            "coverage_pct": coverage_pct(covered, coverable),
            "location": _evidence_loc(_first_evidence_row(subset)),
        })
    return sorted(out, key=_coverage_sort_key)


def _first_evidence_row(rows: List[Json]) -> Json:
    ev = _first_evidence(rows)
    return {"evidence": ev}


def _code_item_label(row: Json) -> str:
    metric = row.get("metric")
    if metric == "branch":
        return " / ".join(str(v) for v in (row.get("branch"), row.get("branch_bin")) if v not in (None, ""))
    if metric == "condition":
        return " / ".join(str(v) for v in (row.get("condition"), row.get("condition_bin")) if v not in (None, ""))
    if metric == "fsm":
        return str(row.get("fsm_transition") or row.get("full_name") or row.get("name") or "")
    return str(row.get("full_name") or row.get("name") or "")


def _functional_coverage_markdown(rows: List[Json], threshold: float,
                                covergroup_filter: Any = None) -> tuple[str, int]:
    if covergroup_filter:
        rows = [row for row in rows if _covergroup_matches(row.get("covergroup"), str(covergroup_filter))]
    groups: Dict[str, List[Json]] = defaultdict(list)
    for row in rows:
        cg = row.get("covergroup")
        if cg:
            groups[str(cg)].append(row)
    lines = [
        "# Functional Coverage Holes",
        "",
        f"Threshold: {threshold:g}%",
        "",
    ]
    exported = 0
    for cg in sorted(groups):
        subset = groups[cg]
        cg_row = next((row for row in subset if _functional_level(row) == "covergroup"), None)
        loc = _evidence_loc(cg_row or {})
        header = f"## {cg}"
        if loc:
            header += f" ({loc})"
        lines.extend([header, ""])
        parents = [row for row in subset if _functional_level(row) in {"coverpoint", "cross"}]
        for parent in sorted(parents, key=lambda r: str(r.get("full_name") or r.get("name") or "")):
            parent_name = parent.get("coverpoint") or parent.get("cross") or parent.get("name")
            lines.extend([f"### {parent_name}", ""])
            bins = [
                row for row in subset
                if _functional_level(row) == "bin"
                and (row.get("coverpoint") == parent.get("coverpoint")
                     or row.get("cross") == parent.get("cross"))
                and _below_threshold(row, threshold)
            ]
            if not bins:
                lines.extend(["No bins below threshold.", ""])
                continue
            lines.extend([
                "| bin | covered | coverable | count | coverage_pct |",
                "|---|---:|---:|---:|---:|",
            ])
            for row in sorted(bins, key=_coverage_sort_key):
                exported += 1
                lines.append(
                    f"| {_md(row.get('bin') or row.get('name'))} | {_md(row.get('covered'))} | "
                    f"{_md(row.get('coverable'))} | {_md(row.get('count'))} | {_md(row.get('coverage_pct'))} |"
                )
            lines.append("")
    if not groups:
        lines.extend(["No covergroups matched.", ""])
    return "\n".join(lines), exported


def _covergroup_matches(covergroup: Any, pattern: str) -> bool:
    if covergroup is None:
        return False
    import fnmatch
    return fnmatch.fnmatchcase(str(covergroup), pattern)


def _assert_markdown(rows: List[Json], sections: Json, threshold: float) -> tuple[str, int]:
    selected = [
        row for row in rows
        if _below_threshold(row, threshold)
        or row["failures"] > 0
        or row["incomplete"] > 0
        or row["without_attempts"] > 0
    ]
    selected.sort(key=_coverage_sort_key)
    lines = [
        "# Assertion Coverage",
        "",
        f"Threshold: {threshold:g}%",
        "",
        "## Summary",
        "",
    ]
    for key in ("assert_summary", "cover_property_summary", "cover_sequence_summary"):
        row = sections.get(key) if isinstance(sections, dict) else None
        if isinstance(row, dict):
            lines.append(
                f"- {key}: total={row.get('total')} success={row.get('success')} "
                f"failure={row.get('failure')} incomplete={row.get('incomplete')} "
                f"without_attempts={row.get('without_attempts')}"
            )
    lines.extend(["", "## Items", ""])
    if selected:
        lines.extend([
            "| kind | object | attempts | real_successes | failures | incomplete | first_match | coverage_pct | file:line |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|",
        ])
        for row in selected:
            lines.append(
                f"| {_md(row.get('kind'))} | {_md(row.get('full_name') or row.get('name'))} | "
                f"{_md(row.get('attempts'))} | {_md(row.get('real_successes'))} | "
                f"{_md(row.get('failures'))} | {_md(row.get('incomplete'))} | "
                f"{_md(row.get('first_match'))} | {_md(row.get('coverage_pct'))} | {_md(_evidence_loc(row))} |"
            )
    else:
        lines.append("No assertion items below threshold.")
    lines.append("")
    return "\n".join(lines), len(selected)


def _functional_summary_rows(rows: List[Json], group_by: str) -> List[Json]:
    if group_by == "covergroup":
        return _functional_covergroup_score_rows(rows)
    return _summary_from_items(_functional_summary_level_rows(rows, group_by), group_by)


def _functional_covergroup_score_rows(rows: List[Json]) -> List[Json]:
    by_cg: Dict[str, List[Json]] = defaultdict(list)
    for row in rows:
        cg = row.get("covergroup")
        if cg:
            by_cg[str(cg)].append(row)
    out: List[Json] = []
    for cg, subset in by_cg.items():
        direct = [row for row in subset if _functional_level(row) in {"coverpoint", "cross"}]
        raw = next((row for row in subset if _functional_level(row) == "covergroup"), None)
        score_rows = direct or ([raw] if raw else [])
        pct_values = [
            float(row["coverage_pct"]) for row in score_rows
            if row and row.get("coverage_pct") is not None
        ]
        score_pct = round(sum(pct_values) / len(pct_values), 4) if pct_values else None
        raw_covered = raw["covered"] if raw else None
        raw_coverable = raw["coverable"] if raw else None
        out_row = {
            "covergroup": cg,
            "metric": "summary",
            "name": cg,
            "full_name": cg,
            "coverage_pct": score_pct,
            "score_basis": "average_direct_coverpoint_cross_pct" if direct else "covergroup_raw_pct",
            "score_item_count": len(score_rows),
            "raw_covered": raw_covered,
            "raw_coverable": raw_coverable,
            "raw_missing": raw["missing"] if raw else None,
            "raw_coverage_pct": raw["coverage_pct"] if raw else None,
        }
        if raw:
            out_row.update({
                "covered": raw["covered"],
                "coverable": raw["coverable"],
                "missing": raw["missing"],
            })
        out.append(out_row)
    return out
def _functional_level(row: Json) -> str:
    typ = row["type"]
    type_to_level = {
        "npiCovCovergroup": "covergroup",
        "npiCovCoverpoint": "coverpoint",
        "npiCovCross": "cross",
        "npiCovCoverBin": "bin",
    }
    try:
        return type_to_level[typ]
    except KeyError as exc:
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "functional row is not a canonical functional coverage type",
            coverage_type=typ,
        ) from exc


def _filter_functional_levels(rows: List[Json], levels: Any) -> List[Json]:
    if levels is None:
        return rows
    if not isinstance(levels, list) or not levels:
        raise XcovError(
            "INVALID_SELECTOR",
            "args.levels must be a non-empty array when provided",
            field="args.levels",
        )
    wanted = {str(level) for level in levels}
    return [row for row in rows if _functional_level(row) in wanted]


def _functional_summary_level_rows(rows: List[Json], group_by: str) -> List[Json]:
    if group_by not in {"covergroup", "coverpoint", "cross", "bin"}:
        return rows
    return [row for row in rows if _functional_level(row) == group_by]
