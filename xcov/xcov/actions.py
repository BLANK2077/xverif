from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional

from .backend import METRICS
from .coverage_contract import is_score_bearing_row
from .errors import XcovError, error_response
from .exclusions_csv import (
    FILE_NAMES,
    KINDS,
    ExclusionDocument,
    ExclusionGroup,
    exclusion_paths,
    format_document,
    format_directory,
    parse_document,
    parse_directory,
    resolve_documents,
)
from .logging import (log_action_event, request_summary_for_log,
                      response_summary_for_log, update_session_manifest)
from .protocol import (
    completeness_summary,
    normalize_request,
    ok_response,
    validate_action_token,
)
from .provenance import resource_sha256, validate_run_manifest
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
        "Summarize merged coverage metrics for a scope from the URG summary index.",
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
    "functional_coverage.summary": ActionContract(
        "functional_coverage.summary", "_functional", True,
        "Aggregate functional coverage at covergroup, coverpoint, cross, or bin level.",
        "Do not use when only uncovered functional items are required.",
    ),
    "assert.summary": ActionContract(
        "assert.summary", "_assert_report", True,
        "Summarize assertion attempts, successes, and basic coverage.",
        "Do not use for the detailed assertion Markdown report.",
    ),
    "export.code_coverage": ActionContract(
        "export.code_coverage", "_export", True,
        "Write strict per-instance code-coverage JSON, XOUT, and raw URG artifacts.",
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
    "exclude.load": ActionContract(
        "exclude.load", "_exclude_load", True,
        "Load one or more native EL files in order using pynpi union semantics.",
        "Do not concatenate or parse native EL text.",
    ),
    "exclude.add": ActionContract(
        "exclude.add", "_exclude_set", True,
        "Set report-time exclusion state for exact coverage references.",
        "Use export gap IDs for portable exclusions; coverage_ref is session-local.",
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
        "exclude.csv.validate", "_exclude_csv_validate", True,
        "逐行校验 CSV 格式、selector 语句格式、VDB object 存在性。最多返回前 10 条错误。",
        "Do not use to apply or compile exclusions.",
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
    "exclude.csv.format": ActionContract(
        "exclude.csv.format", "_exclude_csv_format", False,
        "Check stable grouped CSV ordering, or write it only with write=true.",
        "Do not change exclusion semantics.",
    ),
    "exclude.csv.export": ActionContract(
        "exclude.csv.export", "_exclude_csv_export", True,
        "Atomically merge reason-bearing session exclusions into portable CSV files.",
        "Does not persist exclusions that originated only from native EL files.",
    ),
}

if set(ACTION_REGISTRY) != set(schema_actions()):
    raise RuntimeError("xcov action registry and schema catalog are inconsistent")
if any(name != contract.name for name, contract in ACTION_REGISTRY.items()):
    raise RuntimeError("xcov action registry keys and bound contracts are inconsistent")

COVERAGE_READ_ACTIONS = {
    "session.status",
    "tests.list",
    "metrics.list",
    "scope.summary",
    "scope.children",
    "scope.search",
    "code_coverage.summary",
    "functional_coverage.summary",
    "assert.summary",
    "export.code_coverage",
    "export.functional_coverage",
    "export.assert",
}


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
                session = self._session(normalized)
                if action in COVERAGE_READ_ACTIONS:
                    session.prepare_coverage_read()
                rsp = handler(normalized, session)
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
        manifest_digest = (
            resource_sha256(Path(target["run_manifest"]).resolve(strict=True))
            if target.get("run_manifest") else None
        )
        cache_dir = args.get("cache_dir") or target.get("cache_dir")
        sess = self.sessions.open(
            str(vdb),
            name=args.get("name"),
            exclusion_policy=str(args.get("exclusion_policy", "default")),
            cache_dir=str(cache_dir) if cache_dir else None,
            run_manifest_digest=manifest_digest,
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
            {"session": sess.public_json(), "cached_indexes": sess.cache_status()},
        )

    def _session_close(self, req: Json) -> Json:
        sid = req.get("target", {}).get("session_id")
        sess = self.sessions.get(str(sid))
        session_json = sess.public_json()
        self.sessions.close(str(sid))
        session_json["state"] = "closed"
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
        scope_metrics = sess.backend.scope_metrics()
        scope_filter = args.get("scope")
        if scope_filter:
            sf = str(scope_filter)
            scope_metrics = {
                s: m for s, m in scope_metrics.items()
                if s == sf or s.startswith(sf + ".")
            }
        rows = _metrics_from_urg(scope_metrics)
        rows = _project_code_coverage_summary_rows(rows)
        summary, inline, warnings = apply_output("metrics.list", args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": "merged"})
        return ok_response(req, summary, {"items": inline}, warnings)

    def _scope(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        query = query_args(action, args)
        scopes = _indexed_scopes(sess.backend.scopes())
        metrics = _selector_or_default(args, "metrics", METRICS)

        urg_metrics = sess.backend.scope_metrics()
        coverage = _coverage_from_urg(urg_metrics, scopes, metrics)
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
                        "test": "merged"})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _code_coverage(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        metrics = _selector_or_default(args, "metrics", _code_metrics())
        group_by = str(args.get("group_by", "metric"))
        query_source = dict(args)
        query_source["query"] = dict(args.get("query") or {})
        query_source["query"].setdefault("match_field", group_by)
        query = query_args(action, query_source)
        scope_metrics = sess.backend.scope_metrics()
        scope_filter = args.get("scope")
        if scope_filter:
            sf = str(scope_filter)
            scope_metrics = {
                s: m for s, m in scope_metrics.items()
                if s == sf or s.startswith(sf + ".")
            }
        rows = _code_coverage_from_urg(scope_metrics, group_by, metrics)
        rows = filter_items(rows, query)
        rows = _project_code_coverage_summary_rows(rows)
        rows = sort_items(action, rows, args.get("sort"))
        summary, inline, warnings = apply_output(action, args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": "merged", "metrics": metrics})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _functional(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        group_by = str(args.get("group_by", "covergroup"))
        query_source = dict(args)
        query_source["query"] = dict(args.get("query") or {})
        query_source["query"].setdefault("match_field", group_by)
        query = query_args(action, query_source)
        rows = sess.backend.scope_functional_from_urg()
        if args.get("scope"):
            selected_scope = str(args["scope"])
            rows = [
                row for row in rows
                if row.get("scope") == selected_scope
                or str(row.get("scope") or "").startswith(selected_scope + ".")
            ]
        rows = _functional_summary_rows(rows, group_by)
        rows = filter_items(rows, query)
        rows = _project_functional_coverage_summary_rows(rows, group_by)
        rows = sort_items(action, rows, args.get("sort"))
        summary, inline, warnings = apply_output(action, args, rows)
        summary.update({"session_id": sess.session_id, "test": "merged"})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _assert_report(self, req: Json, sess) -> Json:
        args = action_args(req)
        query = query_args("assert.summary", args)
        rows = sess.backend.scope_assert_from_urg()
        if args.get("scope"):
            selected_scope = str(args["scope"])
            rows = [
                row for row in rows
                if row.get("scope") == selected_scope
                or str(row.get("scope") or "").startswith(selected_scope + ".")
            ]
        rows = _project_assert_summary_rows(rows)
        rows = filter_items(rows, query)
        rows = sort_items("assert.summary", rows, args.get("sort"))
        summary, inline, warnings = apply_output("assert.summary", args, rows)
        summary.update({"session_id": sess.session_id, "scope": args.get("scope"),
                        "test": "merged"})
        return ok_response(req, summary, {"filters": filters_summary(query), "items": inline}, warnings)

    def _export(self, req: Json, sess) -> Json:
        action = req["action"]
        args = action_args(req)
        if action == "export.code_coverage":
            return self._export_code_coverage(req, sess, args)
        output_dir = (args.get("output") or {}).get("path") or args.get("output_dir")
        if not output_dir:
            raise XcovError("SCHEMA_INVALID", "export requires output.path or output_dir")
        os.makedirs(output_dir, exist_ok=True)

        urgentric = {
            "export.code_coverage": "line+tgl+cond+branch+fsm",
            "export.functional_coverage": "group",
            "export.assert": "assert",
        }
        metric = urgentric.get(action)
        if metric is None:
            raise XcovError("UNKNOWN_ACTION", "unknown export action", action=action)

        urg_args = ["urg", "-full64", "-dir", sess.vdb, "-report", output_dir,
                    "-format", "text", "-show", "brief", "-metric", metric]
        urg_args.extend(sess.el_file_arg)
        scope = args.get("scope")
        if scope:
            hier_file = os.path.join(output_dir, ".xcov_hier.txt")
            with open(hier_file, "w") as f:
                f.write(scope + "\n")
            urg_args.extend(["-hier", hier_file])

        from .urg_runner import UrgRunner
        result = UrgRunner().run(urg_args, timeout=300)
        if result.returncode != 0:
            raise XcovError("URG_FAILED", f"URG export failed (exit {result.returncode})",
                            detail={"stderr": result.stderr[:500]})

        structured = None
        if action in {"export.assert", "export.functional_coverage"}:
            from .gap_export import (
                build_gap_payload,
                parse_urg_gap_report,
                write_gap_artifacts,
            )
            structured_metric = "assert" if action == "export.assert" else "functional"
            report_name = "asserts.txt" if structured_metric == "assert" else "grpinfo.txt"
            report_path = Path(output_dir) / report_name
            if not report_path.is_file():
                raise XcovError(
                    "URG_ARTIFACT_MISSING",
                    f"URG did not produce {report_name}",
                )
            rows = parse_urg_gap_report(structured_metric, report_path)
            if scope:
                rows = [
                    row for row in rows
                    if row.get("scope") == scope
                    or str(row.get("scope") or "").startswith(scope + ".")
                ]
            payload = build_gap_payload(structured_metric, sess.vdb, rows)
            structured = write_gap_artifacts(output_dir, structured_metric, payload)

        summary: Json = {
            "session_id": sess.session_id,
            "scope": args.get("scope"),
            "output_mode": "file",
            "output_dir": output_dir,
            "artifact_format": "urg_text",
            "total_count": 0,
            "returned_count": 0,
            "response_truncated": False,
            "scan_complete": True,
            "analysis_complete": True,
            "truncation_scopes": [],
            "note": "URG text report written to output_dir. See modinfo.txt for details.",
        }
        return ok_response(req, summary, {"structured": structured} if structured else {})

    def _export_code_coverage(self, req: Json, sess, args: Json) -> Json:
        import json
        import os
        import shutil
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from .code_export import (
            CoverageExportParseError, PUBLIC_METRICS, URG_METRICS,
            navigation_payload, parse_metric_report, render_metric_xout,
            render_navigation_xout, write_json,
        )
        from .urg_runner import UrgRunner

        scopes = list(args["scopes"])
        metrics = list(args.get("metrics") or PUBLIC_METRICS)
        if len(set(scopes)) != len(scopes):
            raise XcovError("DUPLICATE_SCOPE", "scopes must not contain duplicates")
        if len(set(metrics)) != len(metrics):
            raise XcovError("DUPLICATE_METRIC", "metrics must not contain duplicates")
        output_root = Path(args["output"]["path"])
        output_root.mkdir(parents=True, exist_ok=True)
        if not output_root.is_dir():
            raise XcovError("OUTPUT_INVALID", "output.path is not a directory", path=str(output_root))

        scope_rows = sess.backend.scopes()
        known_scopes = {row["full_name"] for row in scope_rows}
        scope_metrics = sess.backend.scope_metrics()
        missing = [scope for scope in scopes if scope not in known_scopes or scope not in scope_metrics]
        if missing:
            raise XcovError("SCOPE_NOT_FOUND", "scope is not an elaborated coverage instance",
                            scopes=missing)
        top_scopes = [row["full_name"] for row in sess.backend.top_scopes()]
        children = _selected_scope_children(scope_rows, scopes)

        # Build combined hier file: all scopes in one, no per-scope URG loop
        combined_hier_lines: list = [f"-tree {top}" for top in top_scopes]
        for scope in scopes:
            combined_hier_lines.append(f"+tree {scope}")
            for child in children.get(scope, []):
                combined_hier_lines.append(f"-tree {child}")
        combined_hier = "\n".join(combined_hier_lines) + "\n"
        combined_urg_metric = "+".join(URG_METRICS[m] for m in metrics)

        run_name = "xcov_code_coverage_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        final_dir = output_root / run_name
        if final_dir.exists():
            raise XcovError("OUTPUT_RUN_DIR_EXISTS", "timestamped output directory already exists",
                            path=str(final_dir))
        stage_dir = output_root / f".{run_name}.tmp-{os.getpid()}"
        if stage_dir.exists():
            raise XcovError("OUTPUT_STAGING_EXISTS", "staging directory already exists",
                            path=str(stage_dir))
        stage_dir.mkdir()

        # ── Single URG call for all scopes × all metrics ──
        with tempfile.TemporaryDirectory(prefix=".xcov-urg-export-") as urg_dir:
            hier_path = Path(urg_dir) / "combined.hier"
            hier_path.write_text(combined_hier, encoding="utf-8")
            urg_args = [
                "urg", "-full64", "-dir", sess.vdb, "-report", urg_dir,
                "-format", "text", "-legacy", "-metric", combined_urg_metric,
                "-hier", str(hier_path),
            ]
            urg_args.extend(sess.el_file_arg)
            result = UrgRunner().run(urg_args, timeout=600)
            if result.returncode != 0:
                raise XcovError(
                    "URG_FAILED", f"URG export failed (exit {result.returncode})",
                    stderr=result.stderr[:500],
                )
            modinfo_path = Path(urg_dir) / "modinfo.txt"
            if not modinfo_path.is_file():
                raise XcovError("URG_ARTIFACT_MISSING", "URG did not produce modinfo.txt")
            combined_text = modinfo_path.read_text(encoding="utf-8", errors="replace")

        items: List[Json] = []
        try:
            raw_dir = stage_dir / "raw"
            raw_dir.mkdir()
            shared_raw_name = "modinfo.urg.txt"
            (raw_dir / shared_raw_name).write_text(combined_text, encoding="utf-8")
            raw_reference = f"../raw/{shared_raw_name}"
            for scope_index, scope in enumerate(scopes, 1):
                instance_dir = stage_dir / f"instance-{scope_index:04d}"
                instance_dir.mkdir()
                navigation = navigation_payload(scope, scope_metrics, children[scope])
                write_json(instance_dir / "navigation.json", navigation)
                (instance_dir / "navigation.xout").write_text(
                    render_navigation_xout(navigation), encoding="utf-8"
                )
                metric_artifacts = []
                for metric in metrics:
                    try:
                        payload = parse_metric_report(combined_text, scope, metric)
                        payload["exclusion_locator"] = {
                            "version": "xcov.urg_semantic.v1",
                            "vdb": os.path.realpath(sess.vdb),
                        }
                    except CoverageExportParseError as error:
                        raise XcovError(
                            "URG_DETAIL_PARSE_INCOMPLETE", error.reason,
                            scope=scope, metric=metric,
                        ) from error
                    json_name = f"{metric}.json"
                    xout_name = f"{metric}.xout"
                    write_json(instance_dir / json_name, payload)
                    (instance_dir / xout_name).write_text(
                        render_metric_xout(payload, raw_reference), encoding="utf-8"
                    )
                    metric_artifacts.append({
                        "metric": metric,
                        "json": json_name,
                        "xout": xout_name,
                        "raw": raw_reference,
                    })
                items.append({
                    "scope": scope,
                    "directory": f"instance-{scope_index:04d}",
                    "navigation": {"json": "navigation.json", "xout": "navigation.xout"},
                    "metrics": metric_artifacts,
                })
            os.replace(stage_dir, final_dir)
        except Exception:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise

        for item in items:
            item["directory"] = str(final_dir / item["directory"])
        summary: Json = {
            "session_id": sess.session_id,
            "scopes": scopes,
            "metrics": metrics,
            "output_mode": "file",
            "output_dir": str(final_dir),
            "artifact_format": "xcov_code_coverage_bundle.v2",
            "total_count": len(items),
            "returned_count": len(items),
            "response_truncated": False,
            "scan_complete": True,
            "analysis_complete": True,
            "truncation_scopes": [],
        }
        return ok_response(req, summary, {"items": items})

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
        sess.set_el_path(None)  # EL paths loaded via NPI — re-export on next URG call
        sess.mark_exclusion_dirty()
        sess.loaded_el_without_reasons = True
        sess.loaded_el_file_count += len(paths)
        return ok_response(
            req,
            completeness_summary(len(rows), len(rows)),
            {"items": rows},
        )

    def _exclude_set(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        ref_entries = args.get("coverage_refs") or []
        adding = req["action"] == "exclude.add"
        refs = [entry["coverage_ref"] for entry in ref_entries] if adding else list(ref_entries)
        ref_reasons = {
            entry["coverage_ref"]: _required_reason(entry["reason"])
            for entry in ref_entries
        } if adding else {}
        exports = args.get("exports") or []
        if exports:
            if req["action"] != "exclude.add" or refs:
                raise XcovError(
                    "SCHEMA_INVALID",
                    "exports 只允许用于 exclude.add，且不能与 coverage_refs 同时使用",
                    path="$.args",
                )
            return self._exclude_export_gaps(req, sess, exports)
        if not refs:
            raise XcovError(
                "SCHEMA_INVALID",
                "至少需要 coverage_refs 或 exports 之一",
                path="$.args",
            )
        excluded = adding
        rows: list = []

        with tempfile.TemporaryDirectory(prefix=".xcov-exclude-") as temporary:
            baseline = Path(temporary) / "baseline.el"
            try:
                sess.backend.save_exclusions(str(baseline), test="merged")
            except Exception as exc:
                raise XcovError(
                    "EXCLUSION_BASELINE_FAILED",
                    "无法建立排除事务基线，本次请求未生效任何条目",
                    atomic_result="none_applied", atomic=True, transaction_committed=False,
                    requested_count=len(refs), successful_count=0,
                    rollback_performed=False, cause=str(exc),
                ) from exc
            baseline_metadata = dict(sess.exclusion_records)
            staged_metadata = dict(baseline_metadata)
            failure = None
            try:
                for ref in refs:
                    result = sess.backend.set_exclusion(ref, excluded, test="merged")
                    csv_row = result.pop("_csv_row", None)
                    rows.append(result)
                    if result.get("status") not in {
                        "changed", "already_in_state", "immutable_compile_time"
                    }:
                        failure = result
                        break
                    key = "coverage_ref:" + ref
                    if excluded:
                        reason = ref_reasons[ref]
                        result["reason"] = reason
                        record = {
                            "reason": reason, "coverage_ref": ref, "csv_row": csv_row,
                        }
                        previous = staged_metadata.get(key)
                        result["metadata_status"] = (
                            "created" if previous is None
                            else "unchanged" if previous == record
                            else "updated"
                        )
                        staged_metadata[key] = record
                    else:
                        staged_metadata.pop(key, None)

            except Exception as exc:
                failure = {"status": "failed", "reason": "setter_exception", "message": str(exc)}

            if failure is not None:
                try:
                    sess.backend.unload_exclusions(test="merged")
                    sess.backend.load_exclusions([str(baseline)], test="merged")
                    sess.exclusion_records = baseline_metadata
                except Exception as rollback_exc:
                    raise XcovError(
                        "EXCLUSION_ROLLBACK_FAILED",
                        "排除应用失败且基线恢复失败，session 状态不再可信",
                        atomic_result="rollback_failed", atomic=True,
                        transaction_committed=False, failure=failure,
                        rollback_error=str(rollback_exc),
                    ) from rollback_exc
                raise XcovError(
                    "EXCLUSION_APPLY_FAILED",
                    "排除应用失败并已回滚，本次请求未生效任何条目",
                    atomic_result="none_applied", atomic=True, transaction_committed=False,
                    requested_count=len(refs), successful_count=0,
                    rollback_performed=True, failure=failure,
                )
            sess.exclusion_records = staged_metadata

        sess.mark_exclusion_dirty()
        return ok_response(
            req,
            completeness_summary(len(rows), len(rows)),
            {"items": rows},
        )

    def _exclude_export_gaps(self, req: Json, sess, exports: List[Json]) -> Json:
        requested: List[Json] = []
        seen = set()
        preflight_errors = []
        known_scopes = {row["full_name"] for row in sess.backend.scopes()}
        for entry in exports:
            path = Path(entry["path"])
            if not path.is_absolute():
                preflight_errors.append({"code": "EXPORT_PATH_NOT_ABSOLUTE", "path": str(path)})
                continue
            if not path.is_file():
                preflight_errors.append({"code": "EXPORT_FILE_NOT_FOUND", "path": str(path)})
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                preflight_errors.append({
                    "code": "EXPORT_FILE_INVALID", "path": str(path), "message": str(exc),
                })
                continue
            metric = payload.get("metric")
            locator_meta = payload.get("exclusion_locator") or {}
            if metric not in {"line", "condition", "branch", "toggle", "fsm", "assert", "functional"} \
                    or locator_meta.get("version") != "xcov.urg_semantic.v1":
                preflight_errors.append({"code": "EXPORT_FILE_INVALID", "path": str(path)})
                continue
            if os.path.realpath(str(locator_meta.get("vdb", ""))) != os.path.realpath(sess.backend.vdb):
                preflight_errors.append({"code": "EXPORT_VDB_MISMATCH", "path": str(path)})
                continue
            payload_scope = payload.get("scope")
            if metric in {"line", "condition", "branch", "toggle", "fsm"} \
                    and payload_scope not in known_scopes:
                preflight_errors.append({
                    "code": "EXPORT_SCOPE_NOT_FOUND",
                    "path": str(path),
                    "scope": payload_scope,
                })
                continue
            gap_rows = {}
            if metric == "line":
                groups = payload.get("line_groups", [])
            elif metric == "condition":
                groups = payload.get("condition_groups", [])
            elif metric == "branch":
                groups = payload.get("decision_groups", [])
            elif metric == "toggle":
                groups = [{"gaps": payload.get("gaps", [])}]
            elif metric in {"assert", "functional"}:
                groups = [{"gaps": payload.get("gaps", [])}]
            else:
                groups = payload.get("fsm_groups", [])
            for group in groups:
                rows = group.get("uncovered", group.get("gaps", []))
                for gap in rows:
                    gap_rows[gap.get("gap_id")] = (gap, group)
            for gap_entry in entry["items"]:
                gap_id = gap_entry["gap_id"]
                reason = _required_reason(gap_entry["reason"])
                key = (str(path.resolve()), gap_id)
                if key in seen:
                    preflight_errors.append({"code": "DUPLICATE_EXPORT_GAP", "path": str(path), "gap_id": gap_id})
                    continue
                seen.add(key)
                gap_record = gap_rows.get(gap_id)
                if gap_record is None:
                    preflight_errors.append({"code": "EXPORT_GAP_ID_NOT_FOUND", "path": str(path), "gap_id": gap_id})
                    continue
                gap, group = gap_record
                candidate = {
                    "path": str(path.resolve()), "gap_id": gap_id, "metric": metric,
                    "targets": [], "payload": payload,
                    "preflight_error": gap.get("_exclude_error"), "reason": reason,
                    "source_files": payload.get("source_files") or [], "gap": gap,
                    "group": group, "scope": payload.get("scope"),
                }
                requested.append(candidate)
        if preflight_errors:
            raise XcovError(
                "EXCLUSION_EXPORT_PREFLIGHT_FAILED",
                "本次 exclude.add 请求未生效任何条目",
                atomic_result="none_applied", atomic=True, transaction_committed=False,
                requested_gap_count=sum(len(entry["items"]) for entry in exports),
                successful_gap_count=0, applied_gap_count=0, applied_target_count=0,
                rollback_performed=False, errors=preflight_errors,
            )
        with tempfile.TemporaryDirectory(prefix=".xcov-gap-exclude-") as temporary:
            baseline = Path(temporary) / "baseline.el"
            try:
                sess.backend.save_exclusions(str(baseline), test="merged")
            except Exception as exc:
                raise XcovError(
                    "EXCLUSION_BASELINE_FAILED",
                    "本次 exclude.add 请求未生效任何条目；无法建立回滚基线",
                    atomic_result="none_applied", atomic=True,
                    transaction_committed=False, requested_gap_count=len(requested),
                    successful_gap_count=0, applied_gap_count=0,
                    applied_target_count=0, rollback_performed=False,
                    cause_message=str(exc),
                ) from exc
            metadata_baseline = dict(sess.exclusion_records)
            staged_metadata = dict(metadata_baseline)
            item_rows = {}
            applied_targets = 0
            non_fsm_failure = None
            resolved_payloads: set[int] = set()
            resolve_errors = []
            for item in requested:
                payload = item["payload"]
                payload_key = id(payload)
                if payload_key not in resolved_payloads:
                    try:
                        sess.backend.resolve_gap_payload(payload, test="merged")
                    except Exception as exc:
                        resolve_errors.append({
                            "path": item["path"],
                            "code": "EXPORT_GAP_RESOLVE_FAILED",
                            "message": str(exc),
                        })
                    resolved_payloads.add(payload_key)
                targets = item["gap"].get("_exclude_targets")
                if not isinstance(targets, list) or not targets:
                    if item["metric"] != "fsm":
                        resolve_errors.append({
                            "path": item["path"],
                            "gap_id": item["gap_id"],
                            "code": "EXPORT_GAP_RESOLVE_MISSING",
                            "message": item["gap"].get("_exclude_error"),
                        })
                    continue
                item["targets"] = targets
                try:
                    item["csv_rows"] = _gap_csv_rows(item)
                except XcovError as exc:
                    resolve_errors.append({
                        "path": item["path"],
                        "gap_id": item["gap_id"],
                        "code": "EXCLUSION_CSV_IDENTITY_MISSING",
                        "message": str(exc),
                    })
            if resolve_errors:
                raise XcovError(
                    "EXCLUSION_EXPORT_RESOLVE_FAILED",
                    "URG 语义 gap 无法唯一解析为 NPI 排除目标，本次请求未修改数据库",
                    atomic_result="none_applied", atomic=True,
                    transaction_committed=False,
                    requested_gap_count=len(requested), successful_gap_count=0,
                    applied_gap_count=0, applied_target_count=0,
                    rollback_performed=False, errors=resolve_errors,
                )
            execution_order = sorted(
                enumerate(requested),
                key=lambda pair: (
                    str((pair[1]["targets"][0] if pair[1]["targets"] else {}).get("root") or "instance"),
                    str((pair[1]["targets"][0] if pair[1]["targets"] else {}).get("scope") or ""),
                    pair[1]["metric"],
                    tuple((pair[1]["targets"][0] if pair[1]["targets"] else {}).get("path") or []),
                ),
                reverse=True,
            )
            for request_index, item in execution_order:
                target_results = []
                for target in sorted(
                    item["targets"], key=lambda value: tuple(value.get("path") or []), reverse=True
                ):
                    try:
                        result = sess.backend.set_exclusion_locator(
                            target, True, test="merged"
                        )
                    except Exception as exc:
                        result = {
                            "status": "failed",
                            "reason": "setter_exception",
                            "message": str(exc),
                        }
                    target_results.append(result)
                    if result.get("status") in {"changed", "already_in_state"}:
                        applied_targets += 1
                    else:
                        break
                success = bool(item["targets"]) and all(
                    result.get("status") in {"changed", "already_in_state"}
                    for result in target_results
                )
                row = {
                    "coverage_ref": f"{item['path']}#{item['gap_id']}",
                    "gap_id": item["gap_id"], "metric": item["metric"],
                    "status": "changed" if success else "failed",
                    "target_count": len(item["targets"]),
                    "error": (
                        item["preflight_error"]
                        or next(
                            (
                                result.get("message") or result.get("reason")
                                for result in target_results
                                if result.get("status") not in {"changed", "already_in_state"}
                            ),
                            "NPI exclusion target failed",
                        )
                    ) if not success else None,
                }
                if success:
                    statuses = []
                    for csv_row in item["csv_rows"]:
                        key = "csv:" + json.dumps(csv_row, sort_keys=True, separators=(",", ":"))
                        record = {"reason": item["reason"], "csv_row": csv_row}
                        previous = staged_metadata.get(key)
                        statuses.append(
                            "created" if previous is None
                            else "unchanged" if previous == record
                            else "updated"
                        )
                        staged_metadata[key] = record
                    row["reason"] = item["reason"]
                    row["metadata_status"] = (
                        "updated" if "updated" in statuses else "created" if "created" in statuses else "unchanged"
                    )
                item_rows[request_index] = row
                if not success and item["metric"] != "fsm":
                    non_fsm_failure = row
                    break
            if non_fsm_failure is not None:
                try:
                    sess.backend.unload_exclusions(test="merged")
                    sess.backend.load_exclusions([str(baseline)], test="merged")
                    sess.exclusion_records = metadata_baseline
                except Exception as rollback_error:
                    sess.close()
                    raise XcovError(
                        "EXCLUSION_ROLLBACK_FAILED", "本次 exclude.add 请求未生效任何条目；session 已作废",
                        atomic_result="none_applied", transaction_committed=False,
                        rollback_performed=False, cause_message=str(rollback_error),
                    ) from rollback_error
                raise XcovError(
                    "EXCLUSION_APPLY_FAILED", "本次 exclude.add 请求未生效任何条目",
                    atomic_result="none_applied", atomic=True, transaction_committed=False,
                    requested_gap_count=len(requested), successful_gap_count=0,
                    applied_gap_count=0, applied_target_count=0, rollback_performed=True,
                    failed_item=non_fsm_failure,
                )
            sess.exclusion_records = staged_metadata
            items = [item_rows[index] for index in range(len(requested))]
        failed = [item for item in items if item["status"] == "failed"]
        successful = len(items) - len(failed)
        sess.mark_exclusion_dirty()
        summary = completeness_summary(len(items), len(items))
        summary.update({
            "result": "partial_success" if failed else "success",
            "atomic": not bool(failed),
            "transaction_committed": True,
            "requested_gap_count": len(items),
            "successful_gap_count": successful,
            "failed_gap_count": len(failed),
            "applied_gap_count": successful,
            "applied_target_count": applied_targets,
        })
        return ok_response(req, summary, {"items": items})

    def _export_exclude(self, req: Json, sess) -> Json:
        args = action_args(req)
        _require_merged(args)
        path = _export_output_path(args)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        sess.backend.save_exclusions(path, test="merged")
        summary = completeness_summary(0, 0)
        summary.update({
            "session_id": sess.session_id,
            "test": "merged",
            "output_mode": "file",
            "output_path": path,
            "artifact_format": "el",
            "native_entry_count_known": False,
            "session_reason_record_count": len(sess.exclusion_records),
            "loaded_el_file_count": sess.loaded_el_file_count,
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
        before = len(sess.exclusion_records)
        sess.backend.unload_exclusions(test="merged")
        sess.clear_exclusions()
        after = 0
        return ok_response(
            req,
            completeness_summary(1, 1),
            {"items": [{"before_count": before, "after_count": after, "status": "changed"}]},
        )

    def _exclude_csv_validate(self, req: Json, sess) -> Json:
        from xcov.backend import _VALID_METRICS, _SELECTOR_FIELDS, _selector_note

        documents = parse_directory(_csv_directory(req))
        # 先做 object 级解析（复用 _resolve_csv）
        _discard, resolutions = _resolve_csv(req, sess)

        # 按 source_file + csv_line 索引 resolution 结果
        resolved_map: dict[tuple, dict] = {}
        for r in resolutions:
            resolved_map[(r["coverage_kind"], r["source_file"], r["csv_line"])] = r

        all_errors: list = []
        stats = {"csv_format": 0, "selector_format": 0, "object_not_found": 0,
                  "total_rows": 0, "matched": 0}

        for doc in documents:
            for group in doc.groups:
                for i, row in enumerate(group.rows):
                    stats["total_rows"] += 1
                    kind = doc.kind
                    csv_line = i + 1  # 1-based

                    # Level 1: CSV format check
                    err = _check_csv_row_format(kind, row, csv_line)
                    if err:
                        all_errors.append(err)
                        stats["csv_format"] += 1
                        continue

                    # Level 2: Selector format check
                    metric = (row.get("metric") or "").strip()
                    if not metric:
                        err = {
                            "status": "error", "row": csv_line, "coverage_kind": kind,
                            "source_file": group.source_file,
                            "error_type": "CSV_FORMAT", "field": "metric",
                            "message": "metric 列不能为空",
                        }
                        all_errors.append(err)
                        stats["csv_format"] += 1
                        continue

                    if metric not in _VALID_METRICS:
                        err = {
                            "status": "error", "row": csv_line, "coverage_kind": kind,
                            "source_file": group.source_file,
                            "error_type": "SELECTOR_FORMAT", "field": "metric",
                            "message": f"不支持的 metric: {metric}。合法值: {', '.join(sorted(_VALID_METRICS))}",
                            "note": _selector_note(metric),
                        }
                        all_errors.append(err)
                        stats["selector_format"] += 1
                        continue

                    # Level 3: Object existence (from resolutions)
                    key = (kind, group.source_file, csv_line)
                    resolution = resolved_map.get(key)
                    if resolution is None:
                        stats["object_not_found"] += 1
                        err = {
                            "status": "error", "row": csv_line, "coverage_kind": kind,
                            "source_file": group.source_file,
                            "error_type": "OBJECT_NOT_FOUND", "field": None,
                            "message": "CSV 行在 VDB 中无匹配对象",
                            "note": _selector_note(metric),
                        }
                        all_errors.append(err)
                    elif resolution["status"] == "matched":
                        stats["matched"] += 1
                    else:
                        stats["object_not_found"] += 1
                        err = {
                            "status": "error", "row": csv_line, "coverage_kind": kind,
                            "source_file": group.source_file,
                            "error_type": "OBJECT_NOT_FOUND", "field": None,
                            "message": f"解析状态: {resolution['status']} — {resolution.get('validity', resolution.get('reason', ''))}",
                            "note": _selector_note(metric),
                        }
                        all_errors.append(err)

        shown = all_errors[:10]
        summary = {
            "total_rows": stats["total_rows"],
            "total_errors": len(all_errors),
            "matched_count": stats["matched"],
            "csv_format_errors": stats["csv_format"],
            "selector_format_errors": stats["selector_format"],
            "object_not_found_errors": stats["object_not_found"],
            "returned_count": len(shown),
            "response_truncated": len(all_errors) > 10,
            "note": (
                "仅显示前 10 条错误。完整统计见 summary。"
                "CSV_FORMAT: CSV 格式/列值错误。"
                "SELECTOR_FORMAT: metric 不支持或字段缺失。"
                "OBJECT_NOT_FOUND: CSV 行在 VDB 中无匹配对象。"
                "运行 export action 获取 modinfo/grpinfo 确认准确的 scope/signal/branch/condition/coverpoint/bin 名称。"
            ),
        }
        if len(all_errors) > 10:
            summary["note"] += f" 另有 {len(all_errors) - 10} 条错误未显示。"

        return ok_response(req, completeness_summary(len(shown), len(all_errors)), {"items": shown})

    def _exclude_csv_apply(self, req: Json, sess) -> Json:
        documents, resolutions = _resolve_csv(req, sess)
        failures = [row for row in resolutions if row["status"] != "matched"]
        if failures:
            raise XcovError(
                "EXCLUSION_RESOLVE_FAILED",
                "every CSV record must resolve exactly once before apply",
                failed_count=len(failures),
            )
        rows = _apply_csv_refs_transactionally(sess, resolutions)
        _record_csv_documents(sess, documents)
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
                    sess.exclusion_records.clear()
                    _record_csv_documents(sess, documents)
                    sess.loaded_el_without_reasons = False
                    sess.loaded_el_file_count = 3
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

    def _exclude_csv_export(self, req: Json, sess) -> Json:
        args = action_args(req)
        directory = Path(_csv_directory(req))
        if directory.is_absolute() and not args.get("allow_absolute_path", False):
            raise XcovError(
                "OUTPUT_PATH_UNSAFE",
                "absolute directory requires allow_absolute_path=true",
                path=str(directory),
            )
        if any(part == ".." for part in directory.parts):
            raise XcovError(
                "OUTPUT_PATH_UNSAFE", "directory must not contain '..'", path=str(directory),
            )

        documents = []
        paths = exclusion_paths(directory)
        for kind in KINDS:
            path = paths[kind]
            documents.append(
                parse_document(path, kind) if path.exists()
                else ExclusionDocument(kind, path, [])
            )

        exportable = [
            record for record in sess.exclusion_records.values()
            if isinstance(record.get("csv_row"), dict)
        ]
        unexportable_count = len(sess.exclusion_records) - len(exportable)
        by_kind = {document.kind: document for document in documents}
        identities: Dict[tuple, str] = {}
        for document in documents:
            for group in document.groups:
                for row in group.rows:
                    identity = _csv_row_identity(document.kind, group.source_file, row)
                    identities[identity] = row["reason"]

        added_count = 0
        for record in exportable:
            row = dict(record["csv_row"])
            kind = row.pop("coverage_kind")
            source_file = row.pop("source_file")
            row["reason"] = record["reason"]
            identity = _csv_row_identity(kind, source_file, row)
            previous_reason = identities.get(identity)
            if previous_reason is not None and previous_reason != row["reason"]:
                raise XcovError(
                    "EXCLUSION_REASON_CONFLICT",
                    "同一 exclusion 身份已有不同 reason；本次 CSV 导出未写入任何文件",
                    coverage_kind=kind, source_file=source_file,
                    existing_reason=previous_reason, requested_reason=row["reason"],
                    atomic_result="none_published",
                )
            if previous_reason is not None:
                continue
            document = by_kind[kind]
            group = next((item for item in document.groups if item.source_file == source_file), None)
            if group is None:
                group = ExclusionGroup(source_file, [])
                document.groups.append(group)
            group.rows.append(row)
            identities[identity] = row["reason"]
            added_count += 1

        formatted = {document.kind: format_document(document) for document in documents}
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".xcov-csv-export-", dir=str(directory)) as temporary:
            temp_root = Path(temporary)
            staged = {}
            backups = {}
            replaced = []
            try:
                for document in documents:
                    staged_path = temp_root / FILE_NAMES[document.kind]
                    staged_path.write_text(formatted[document.kind], encoding="utf-8")
                    staged[document.kind] = staged_path
                for document in documents:
                    destination = document.path
                    if destination.exists():
                        backup = temp_root / (FILE_NAMES[document.kind] + ".previous")
                        os.replace(destination, backup)
                        backups[document.kind] = backup
                    os.replace(staged[document.kind], destination)
                    replaced.append(document.kind)
            except Exception:
                for kind in reversed(KINDS):
                    destination = paths[kind]
                    if kind in replaced and destination.exists():
                        destination.unlink()
                    if kind in backups:
                        os.replace(backups[kind], destination)
                raise

        items = [{
            "coverage_kind": document.kind,
            "path": str(document.path),
            "status": "published",
            "group_count": len(document.groups),
            "record_count": document.row_count,
        } for document in documents]
        summary = completeness_summary(len(items), len(items))
        summary.update({
            "exported_session_record_count": len(exportable),
            "added_record_count": added_count,
            "unexportable_session_record_count": unexportable_count,
            "el_reason_unknown": sess.loaded_el_without_reasons,
        })
        warnings = []
        if sess.loaded_el_without_reasons:
            warnings.append("当前 session 从 EL 导入的 exclusion 没有 reason，未写入 CSV")
        if unexportable_count:
            warnings.append(f"{unexportable_count} 条 session exclusion 缺少可移植 CSV 身份，未写入 CSV")
        return ok_response(req, summary, {"items": items}, warnings=warnings)

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
def _csv_directory(req: Json) -> str:
    return str(action_args(req).get("directory", "coverage_exclusions"))


def _check_csv_row_format(kind: str, row: dict, csv_line: int) -> dict | None:
    """校验单行 CSV 格式。返回 error dict 或 None。"""
    scope = (row.get("scope") or "").strip()
    if not scope:
        return {
            "status": "error", "row": csv_line, "coverage_kind": kind,
            "source_file": row.get("_source_file") or "",
            "error_type": "CSV_FORMAT", "field": "scope",
            "message": "scope 列不能为空",
        }
    line_val = row.get("line", "")
    if (line_val == "" or line_val is None) and not (
        kind == "code" and row.get("metric") == "toggle"
    ):
        return {
            "status": "error", "row": csv_line, "coverage_kind": kind,
            "source_file": row.get("_source_file") or "",
            "error_type": "CSV_FORMAT", "field": "line",
            "message": "line 列不能为空",
        }
    try:
        if line_val not in ("", None):
            int(line_val)
    except (ValueError, TypeError):
        return {
            "status": "error", "row": csv_line, "coverage_kind": kind,
            "source_file": row.get("_source_file") or "",
            "error_type": "CSV_FORMAT", "field": "line",
            "message": f"line 列值 '{line_val}' 不是合法数字",
        }
    return None


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
                result.pop("_csv_row", None)
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


def _required_reason(value: Any) -> str:
    reason = str(value).strip()
    if not reason:
        raise XcovError("SCHEMA_INVALID", "reason 不能为空", path="$.args")
    return reason


def _source_and_line(item: Json) -> tuple[str, int]:
    source_files = item.get("source_files") or []
    source_file = str(source_files[0]) if source_files else ""
    if source_file and Path(source_file).is_absolute():
        try:
            source_file = str(Path(source_file).resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            source_file = Path(source_file).name
    for target in item.get("targets") or []:
        target_line = target.get("csv_line")
        target_file = str(target.get("csv_source_file") or "")
        if isinstance(target_line, int) and target_line > 0:
            if target_file and Path(target_file).is_absolute():
                try:
                    target_file = str(Path(target_file).resolve().relative_to(Path.cwd().resolve()))
                except ValueError:
                    target_file = Path(target_file).name
            return source_file or target_file, target_line
    candidates = [item.get("gap") or {}, item.get("group") or {}]
    pending: List[Any] = list(candidates)
    while pending:
        candidate = pending.pop(0)
        if isinstance(candidate, dict):
            at = candidate.get("at")
            if isinstance(at, str) and ":" in at:
                file_name, line_text = at.rsplit(":", 1)
                if line_text.isdigit():
                    return source_file or file_name, int(line_text)
            line = candidate.get("line")
            if isinstance(line, int) and line > 0:
                candidate_file = str(candidate.get("file") or "")
                if candidate_file and Path(candidate_file).is_absolute():
                    try:
                        candidate_file = str(
                            Path(candidate_file).resolve().relative_to(Path.cwd().resolve())
                        )
                    except ValueError:
                        candidate_file = Path(candidate_file).name
                return source_file or candidate_file, line
            pending.extend(candidate.values())
        elif isinstance(candidate, list):
            pending.extend(candidate)
    if item.get("metric") == "toggle" and source_file:
        return source_file, 0
    raise XcovError(
        "EXCLUSION_CSV_IDENTITY_MISSING",
        "gap 缺少可持久化的源码行号；本次 exclude.add 未生效任何条目",
        gap_id=item.get("gap_id"), atomic_result="none_applied",
    )


def _gap_csv_rows(item: Json) -> List[Json]:
    source_file, line = _source_and_line(item)
    metric = item["metric"]
    gap = item["gap"]
    if metric == "functional":
        return [{
            "coverage_kind": "functional", "source_file": source_file,
            "scope": str(gap.get("scope") or ""), "line": str(line),
            "covergroup": str(gap.get("covergroup") or ""),
            "coverpoint": str(gap.get("coverpoint") or ""),
            "cross": str(gap.get("cross") or ""), "bin": str(gap.get("bin") or ""),
        }]
    if metric == "assert":
        return [{
            "coverage_kind": "assertion", "source_file": source_file,
            "scope": str(gap.get("scope") or ""), "line": str(line),
            "assertion": str(gap.get("full_name") or gap.get("name") or ""),
            "assertion_kind": str(gap.get("kind") or ""),
        }]
    rows = []
    for target in item["targets"]:
        obj = target.get("csv_object", "")
        bin_name = target.get("csv_bin", "")
        if metric != "line" and (not obj or not bin_name):
            raise XcovError(
                "EXCLUSION_CSV_IDENTITY_MISSING",
                "gap 的直接 NPI locator 缺少 CSV 身份；本次 exclude.add 未生效任何条目",
                gap_id=item.get("gap_id"), atomic_result="none_applied",
            )
        rows.append({
            "coverage_kind": "code", "source_file": source_file,
            "scope": item["scope"], "metric": metric,
            "line": "" if metric == "toggle" and line == 0 else str(line),
            "object": obj, "bin": bin_name,
        })
    return rows


def _record_csv_documents(sess, documents: List[Any]) -> None:
    for document in documents:
        for group in document.groups:
            for source_row in group.rows:
                row = {key: value for key, value in source_row.items() if not key.startswith("_") and key != "reason"}
                row.update({"coverage_kind": document.kind, "source_file": group.source_file})
                key = "csv:" + json.dumps(row, sort_keys=True, separators=(",", ":"))
                sess.record_exclusion(key, {"reason": source_row["reason"], "csv_row": row})


def _csv_row_identity(kind: str, source_file: str, row: Json) -> tuple:
    fields = {
        "code": ("scope", "metric", "line", "object", "bin"),
        "functional": ("scope", "line", "covergroup", "coverpoint", "cross", "bin"),
        "assertion": ("scope", "line", "assertion", "assertion_kind"),
    }[kind]
    return (kind, source_file, *(str(row.get(field, "")) for field in fields))


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


def _selected_scope_children(
    scope_rows: List[Json],
    selected_scopes: List[str],
    operation_counter: Optional[Json] = None,
) -> Dict[str, List[str]]:
    adjacency: Dict[str, List[str]] = defaultdict(list)
    scans = 0
    for row in scope_rows:
        scans += 1
        parent = row.get("parent")
        if isinstance(parent, str):
            adjacency[parent].append(row["full_name"])
    result: Dict[str, List[str]] = {}
    for scope in selected_scopes:
        scans += 1
        result[scope] = sorted(adjacency.get(scope, []))
    if operation_counter is not None:
        operation_counter["scope_index_operations"] = scans
    return result


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


# Metrics available in the fixed URG summary contract.
_URG_METRICS = frozenset(METRICS)


def _coverage_from_urg(
    scope_metrics: Dict[str, Json],
    scopes: Dict[str, Json],
    metrics: List[str],
) -> Dict[str, Json]:
    """Build per-scope coverage directly from URG subtree metrics.

    Every instance row in ``session.xml`` already describes that instance's
    subtree.  Summing descendants here would double count and become O(N^2).
    """
    if not scope_metrics:
        return {}
    result: Dict[str, Json] = {}
    for scope_name, available in scope_metrics.items():
        metric_rows: List[Json] = []
        for mname in metrics:
            mt = available.get(mname)
            if mt is None:
                continue
            metric_rows.append({
                "metric": mname,
                "covered": mt["covered"],
                "coverable": mt["coverable"],
                "missing": mt["coverable"] - mt["covered"],
                "coverage_pct": mt.get(
                    "pct",
                    coverage_pct(mt["covered"], mt["coverable"]),
                ),
            })
        percentages = [row["coverage_pct"] for row in metric_rows]
        row: Json = {
            "coverage_pct": (
                round(sum(percentages) / len(percentages), 4)
                if percentages else None
            ),
            "metrics": metric_rows,
        }
        if len(metric_rows) == 1:
            only = metric_rows[0]
            row.update({
                "covered": only["covered"],
                "coverable": only["coverable"],
                "missing": only["missing"],
            })
        if metric_rows or scope_name in scopes:
            result[scope_name] = row
    return result


def _code_coverage_from_urg(
    scope_metrics: Dict[str, Json],
    group_by: str,
    metrics: List[str],
) -> List[Json]:
    """Aggregate code coverage from URG scope_metrics by metric or scope."""
    if group_by == "metric":
        return _metrics_from_urg(scope_metrics, metrics)
    # group_by == "scope"
    rows: List[Json] = []
    for sname in sorted(scope_metrics):
        mets = scope_metrics[sname]
        selected = [mets[name] for name in metrics if name in mets]
        percentages = [
            value.get(
                "pct",
                coverage_pct(value["covered"], value["coverable"]),
            )
            for value in selected
        ]
        row: Json = {
            "scope": sname,
            "metric": "summary",
            "coverage_pct": (
                round(sum(percentages) / len(percentages), 4)
                if percentages else None
            ),
        }
        if len(selected) == 1:
            row.update({
                "covered": selected[0]["covered"],
                "coverable": selected[0]["coverable"],
                "missing": selected[0]["missing"],
            })
        rows.append(row)
    return rows


def _metrics_from_urg(
    scope_metrics: Dict[str, Json],
    metrics: Optional[List[str]] = None,
) -> List[Json]:
    """Aggregate only independent top-scope subtree metrics."""
    names = set(scope_metrics)
    roots = [
        name for name in names
        if "." not in name or name.rsplit(".", 1)[0] not in names
    ]
    wanted = metrics or sorted({metric for row in scope_metrics.values() for metric in row})
    totals: Dict[str, Dict[str, Any]] = {
        metric: {"covered": 0, "coverable": 0, "percentages": []}
        for metric in wanted
    }
    for scope_name in roots:
        mets = scope_metrics[scope_name]
        for mname, vals in mets.items():
            if mname not in totals:
                continue
            totals[mname]["covered"] += vals["covered"]
            totals[mname]["coverable"] += vals["coverable"]
            totals[mname]["percentages"].append(
                vals.get("pct", coverage_pct(vals["covered"], vals["coverable"]))
            )
    rows: List[Json] = []
    for mname in wanted:
        vals = totals[mname]
        if not vals["percentages"]:
            continue
        rows.append({
            "metric": mname,
            "covered": vals["covered"],
            "coverable": vals["coverable"],
            "missing": vals["coverable"] - vals["covered"],
            "coverage_pct": (
                vals["percentages"][0]
                if len(vals["percentages"]) == 1
                else coverage_pct(vals["covered"], vals["coverable"])
            ),
        })
    return rows


def _coverage_score_rows(items: List[Json]) -> List[Json]:
    """Rows that contribute to URG dashboard-style code coverage totals."""
    return [item for item in items if is_score_bearing_row(item)]


def _merge_scope_coverage(scope: Json, cov: Optional[Json]) -> Json:
    out = dict(scope)
    cov = cov or {"coverage_pct": None, "metrics": []}
    out["coverage_pct"] = cov.get("coverage_pct")
    for key in ("covered", "coverable", "missing"):
        if key in cov:
            out[key] = cov[key]
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
        "name", "full_name", "coverage_pct",
        "line_pct", "toggle_pct", "branch_pct", "condition_pct",
        "fsm_pct", "assert_pct", "functional_pct",
    ]
    projected = [_project_columns(row, columns) for row in rows]
    for source, target in zip(rows, projected):
        for key in ("covered", "coverable", "missing"):
            if key in source:
                target[key] = source[key]
    return projected


def _project_code_coverage_summary_rows(rows: List[Json]) -> List[Json]:
    forbidden = {"name", "full_name", "functional_pct"}
    return [{key: value for key, value in row.items() if key not in forbidden}
            for row in rows]


def _project_functional_coverage_summary_rows(rows: List[Json], group_by: str) -> List[Json]:
    columns = [
        group_by, "covered", "coverable", "missing",
        "coverage_pct",
    ]
    return [_project_columns(row, columns) for row in rows]


def _project_assert_summary_rows(rows: List[Json]) -> List[Json]:
    columns = [
        "name", "full_name", "covered", "coverable", "missing",
        "coverage_pct", "status", "attempts", "real_successes",
        "without_attempts",
    ]
    return [_project_columns(row, columns) for row in rows]


def _code_metrics() -> List[str]:
    return [m for m in METRICS if m != "functional"]


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
        "coverage_kind": kind,
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
    if file_name and line is not None:
        return f"{file_name}:{line}"
    if file_name:
        return str(file_name)
    return ""


def _md(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _yes_no_covered(value: Any, status: List[str] | None = None) -> str:
    if value is None:
        if status:
            for s in status:
                if s not in ("covered", "not_covered"):
                    return s
            if "not_covered" in status:
                return "no_collected"
            return status[0]
        return "no_collected"
    if not isinstance(value, int) or isinstance(value, bool):
        raise XcovError(
            "INTERNAL_CONTRACT_ERROR",
            "derived covered count is not an integer",
            field="covered",
        )
    return "yes" if value > 0 else "no"
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
