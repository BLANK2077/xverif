"""xsva CLI — argparse 入口。

命令（对齐 spec 第五章）：
  xsva list    --file <file>
  xsva scan    --file <file>
  xsva lint    --file <file>
  xsva explain --file <file> --property <name> [--json] [--markdown] [--strict]
  xsva parse   --file <file> --property <name> --emit surface-ir|sequence-ir|timeline-ir

Exit code (对齐 spec 5.7):
  0 = success, 1 = parse error, 2 = unsupported in strict mode,
  3 = property not found, 4 = file error, 5 = internal error
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

from xsva.contracts import validate_response
from xsva.ir.common import LoweringStatus
from xsva.ir.diagnostics import DiagnosticBag
from xsva.ir.sequence import SequenceIR
from xsva.ir.surface import SurfaceIR
from xsva.ir.timeline import TimelineIR
from xsva.parser.property_parser import PropertyParser
from xsva.parser.scanner import Scanner
from xsva.lower.surface_to_sequence import lower_surface_to_sequence
from xsva.lower.sequence_to_timeline import lower_sequence_to_timeline
from xsva.explain.markdown import render_timeline_markdown
from xsva.util.json import dump_json, to_jsonable
from xsva.xout import to_xout

EXIT_SUCCESS = 0
EXIT_PARSE_ERROR = 1
EXIT_UNSUPPORTED_STRICT = 2
EXIT_PROPERTY_NOT_FOUND = 3
EXIT_FILE_ERROR = 4
EXIT_INTERNAL_ERROR = 5


class XsvaCliError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        exit_code: int,
        *,
        analysis_lowering_status: LoweringStatus = LoweringStatus.UNSUPPORTED,
        analysis_diagnostics: list | None = None,
        analysis_scan_complete: bool = False,
        analysis_path_total_count: int | None = None,
        analysis_path_returned_count: int | None = None,
        analysis_path_enumeration_complete: bool = True,
        file: str | None = None,
        property_name: str | None = None,
        emit: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.analysis_lowering_status = analysis_lowering_status
        self.analysis_diagnostics = list(analysis_diagnostics or [])
        self.analysis_scan_complete = analysis_scan_complete
        self.analysis_path_total_count = analysis_path_total_count
        self.analysis_path_returned_count = analysis_path_returned_count
        self.analysis_path_enumeration_complete = analysis_path_enumeration_complete
        self.details = {
            key: value
            for key, value in {"file": file, "property": property_name, "emit": emit}.items()
            if value is not None
        }


def _read_file(filepath: str) -> str:
    try:
        return Path(filepath).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise XsvaCliError("FILE_NOT_FOUND", f"file not found: {filepath}", EXIT_FILE_ERROR, file=filepath) from exc
    except OSError as exc:
        raise XsvaCliError("FILE_ERROR", f"cannot read file: {filepath}: {exc}", EXIT_FILE_ERROR, file=filepath) from exc


def _has_semantic_body(surface: SurfaceIR) -> bool:
    return bool(surface.antecedent_raw.strip() or surface.implication or surface.consequent_raw.strip())


def _find_property(results: list, name: str, diagnostics: list | None = None):
    for ir in results:
        if ir.name == name and _has_semantic_body(ir):
            return ir
    raise XsvaCliError(
        "PROPERTY_NOT_FOUND", f"property not found: {name}", EXIT_PROPERTY_NOT_FOUND,
        analysis_diagnostics=diagnostics, analysis_scan_complete=True,
        property_name=name,
    )


def _parse_and_lower(args):
    """通用：读取文件→解析→lowering→返回 timeline + surface。"""
    text = _read_file(args.file)
    diag = DiagnosticBag()
    scanner = Scanner(text, file=args.file)
    parser = PropertyParser(scanner, diag)
    results = parser.parse_file()
    surface_ir = _find_property(results, args.property, diag.diagnostics)
    seq_ir = lower_surface_to_sequence(surface_ir, diag)
    timeline = lower_sequence_to_timeline(seq_ir, surface_ir=surface_ir, diag=diag)
    return timeline, surface_ir, diag


def _parse_surface_only(args):
    """仅解析到 SurfaceIR。"""
    text = _read_file(args.file)
    diag = DiagnosticBag()
    scanner = Scanner(text, file=args.file)
    parser = PropertyParser(scanner, diag)
    results = parser.parse_file()
    return _find_property(results, args.property, diag.diagnostics), diag


# ── 命令实现 ──

def _diagnostics(diags: list) -> list[dict]:
    return [asdict(item) for item in diags]


def _analysis_fields(
    lowering_status: LoweringStatus = LoweringStatus.EXACT,
    diagnostics: list | None = None,
    *,
    scan_complete: bool = True,
    path_total_count: int | None = None,
    path_returned_count: int | None = None,
    path_enumeration_complete: bool = True,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    if path_total_count is None:
        if path_returned_count is not None:
            raise ValueError("returned path count requires a total path count")
        response_truncated = False
    else:
        if (
            not isinstance(path_total_count, int) or isinstance(path_total_count, bool)
            or path_total_count < 0
            or not isinstance(path_returned_count, int) or isinstance(path_returned_count, bool)
            or path_returned_count < 0 or path_returned_count > path_total_count
        ):
            raise ValueError("path counts must be non-negative integers with returned <= total")
        if path_enumeration_complete != (path_returned_count == path_total_count):
            raise ValueError("path_enumeration_complete must agree with path counts")
        response_truncated = not path_enumeration_complete or path_returned_count < path_total_count
    serialized = _diagnostics(diagnostics or [])
    reasons = list(reason_codes or [])
    reasons.extend(
        str(item["code"])
        for item in serialized
        if item.get("code") and str(item["code"]) not in reasons
    )
    path_state = "not_applicable" if path_total_count is None else ("partial" if response_truncated else "complete")
    semantic_model = {
        LoweringStatus.EXACT: "complete",
        LoweringStatus.PARTIAL: "partial",
        LoweringStatus.OPAQUE: "opaque",
        LoweringStatus.UNSUPPORTED: "unavailable",
        LoweringStatus.UNSAFE_TO_EXPLAIN: "unsafe",
    }[lowering_status]
    return {
        "lowering_status": lowering_status.value,
        "precision": {
            "semantic_model": semantic_model,
            "path_enumeration": path_state,
            "reason_codes": reasons,
        },
        "diagnostics": serialized,
        "completeness": {
            "scan_complete": scan_complete,
            "analysis_complete": scan_complete and lowering_status == LoweringStatus.EXACT and not response_truncated,
            "response_truncated": response_truncated,
            "path_enumeration_complete": path_enumeration_complete if path_total_count is not None else None,
            "total_path_count": path_total_count,
            "returned_path_count": path_returned_count,
            "truncation_scopes": ["analysis.match_paths"] if response_truncated else [],
        },
    }


_MISSING = object()


def _success(
    action: str,
    *,
    file: str,
    result: dict[str, Any],
    lowering_status: LoweringStatus = LoweringStatus.EXACT,
    diagnostics: list | None = None,
    path_total_count: int | None = None,
    path_returned_count: int | None = None,
    path_enumeration_complete: bool = True,
    property_name: str | None | object = _MISSING,
    emit: str | object = _MISSING,
) -> dict:
    payload = {
        "ok": True, "tool": "xsva", "action": action,
        **_analysis_fields(
            lowering_status, diagnostics,
            path_total_count=path_total_count,
            path_returned_count=path_returned_count,
            path_enumeration_complete=path_enumeration_complete,
        ),
        "file": file, "result": result,
    }
    if action in {"lint", "explain", "parse"}:
        if property_name is _MISSING:
            raise ValueError(f"{action} response requires property")
        payload["property"] = property_name
    elif property_name is not _MISSING:
        raise ValueError(f"{action} response does not declare property")
    if action == "parse":
        if emit is _MISSING:
            raise ValueError("parse response requires emit")
        payload["emit"] = emit
    normalized = to_jsonable(payload)
    validate_response(normalized, expected_action=action)
    return normalized


def _lowering_rank(status: LoweringStatus) -> int:
    return {
        LoweringStatus.EXACT: 0, LoweringStatus.PARTIAL: 1,
        LoweringStatus.OPAQUE: 2, LoweringStatus.UNSUPPORTED: 3,
        LoweringStatus.UNSAFE_TO_EXPLAIN: 4,
    }[status]

def cmd_list(args: argparse.Namespace) -> dict:
    text = _read_file(args.file)
    scanner = Scanner(text, file=args.file)
    diag = DiagnosticBag()
    parser = PropertyParser(scanner, diag)
    items = parser.list_properties()

    properties = [i for i in items if i["type"] == "property"]
    assertions = [i for i in items if i["type"] in ("assert", "assume", "cover")]

    return _success(
        "list", diagnostics=diag.diagnostics, file=args.file,
        result={"properties": properties, "assertions": assertions},
    )


def cmd_scan(args: argparse.Namespace) -> dict:
    text = _read_file(args.file)
    scanner = Scanner(text, file=args.file)
    diag = DiagnosticBag()
    parser = PropertyParser(scanner, diag)
    stats = parser.scan_statistics()
    stats.pop("file", None)
    return _success("scan", diagnostics=diag.diagnostics, file=args.file, result=stats)


def cmd_lint(args: argparse.Namespace) -> dict:
    from xsva.lint import lint_timeline

    text = _read_file(args.file)
    scanner = Scanner(text, file=args.file)
    diag = DiagnosticBag()
    parser = PropertyParser(scanner, diag)
    results = parser.parse_file()
    statuses: list[LoweringStatus] = []
    timelines: list[TimelineIR] = []

    if not args.property:
        all_diags: list = []
        named_definitions = {
            ir.name for ir in results
            if ir.is_named_property and _has_semantic_body(ir)
        }
        lint_targets = [ir for ir in results if _has_semantic_body(ir)]
        unresolved = {
            ir.name for ir in results
            if not _has_semantic_body(ir) and ir.name not in named_definitions
        }
        for name in sorted(unresolved):
            diag.error("XSVA-E002", f"property body not found in the analyzed file: {name}")
        if unresolved:
            statuses.append(LoweringStatus.UNSUPPORTED)
        for ir in lint_targets:
            seq = lower_surface_to_sequence(ir, diag)
            timeline = lower_sequence_to_timeline(seq, surface_ir=ir, diag=diag)
            timelines.append(timeline)
            statuses.append(timeline.lowering_status)
            all_diags.extend(lint_timeline(timeline, surface_ir=ir))
        diags = list(diag.diagnostics) + all_diags
    else:
        surface = _find_property(results, args.property, diag.diagnostics)
        seq = lower_surface_to_sequence(surface, diag)
        timeline = lower_sequence_to_timeline(seq, surface_ir=surface, diag=diag)
        timelines.append(timeline)
        statuses.append(timeline.lowering_status)
        diags = list(diag.diagnostics) + lint_timeline(timeline, surface_ir=surface)
    status = max(statuses, key=_lowering_rank) if statuses else LoweringStatus.EXACT
    path_total_count = sum(item.path_total_count for item in timelines) if timelines else None
    path_returned_count = sum(item.path_returned_count for item in timelines) if timelines else None
    return _success(
        "lint", lowering_status=status, diagnostics=diags,
        path_total_count=path_total_count,
        path_returned_count=path_returned_count,
        path_enumeration_complete=all(item.path_enumeration_complete for item in timelines),
        file=args.file, property_name=args.property,
        result={"issue_count": len(diags)},
    )


def cmd_explain(args: argparse.Namespace) -> dict | str:
    try:
        timeline, surface, diag = _parse_and_lower(args)
    except XsvaCliError:
        raise
    except Exception as e:
        raise XsvaCliError("PARSE_ERROR", f"parse failed: {e}", EXIT_PARSE_ERROR, property_name=args.property) from e

    if args.strict and timeline.lowering_status.value != "exact":
        raise XsvaCliError(
            "UNSUPPORTED_STRICT",
            "strict mode cannot produce a fully precise explanation for this advanced sequence",
            EXIT_UNSUPPORTED_STRICT,
            analysis_lowering_status=timeline.lowering_status,
            analysis_diagnostics=diag.diagnostics,
            analysis_scan_complete=True,
            analysis_path_total_count=timeline.path_total_count,
            analysis_path_returned_count=timeline.path_returned_count,
            analysis_path_enumeration_complete=timeline.path_enumeration_complete,
            property_name=args.property,
        )
    payload = _success(
        "explain", lowering_status=timeline.lowering_status,
        diagnostics=diag.diagnostics,
        path_total_count=timeline.path_total_count,
        path_returned_count=timeline.path_returned_count,
        path_enumeration_complete=timeline.path_enumeration_complete,
        file=args.file, property_name=args.property,
        result=_serialize_timeline_ir(timeline),
    )
    return render_timeline_markdown(timeline) if args.markdown else payload


def cmd_parse(args: argparse.Namespace) -> dict:
    try:
        surface, diag = _parse_surface_only(args)
    except XsvaCliError:
        raise
    except Exception as e:
        raise XsvaCliError("PARSE_ERROR", f"parse failed: {e}", EXIT_PARSE_ERROR, property_name=args.property) from e

    metadata_source: SurfaceIR | SequenceIR | TimelineIR
    if args.emit == "surface-ir":
        output = _serialize_surface_ir(surface)
        metadata_source = surface
    elif args.emit == "sequence-ir":
        seq_ir = lower_surface_to_sequence(surface, diag)
        output = _serialize_sequence_ir(seq_ir)
        metadata_source = seq_ir
    elif args.emit == "timeline-ir":
        seq_ir = lower_surface_to_sequence(surface, diag)
        timeline = lower_sequence_to_timeline(seq_ir, surface_ir=surface, diag=diag)
        output = _serialize_timeline_ir(timeline)
        metadata_source = timeline
    else:
        raise XsvaCliError("UNKNOWN_EMIT_TARGET", f"unknown emit target: {args.emit}", EXIT_INTERNAL_ERROR, emit=args.emit)
    metadata: dict[str, Any] = {
        "lowering_status": metadata_source.lowering_status,
        "diagnostics": diag.diagnostics,
    }
    if isinstance(metadata_source, TimelineIR):
        metadata.update({
            "path_total_count": metadata_source.path_total_count,
            "path_returned_count": metadata_source.path_returned_count,
            "path_enumeration_complete": metadata_source.path_enumeration_complete,
        })
    return _success(
        "parse", **metadata, file=args.file, property_name=args.property,
        emit=args.emit, result=output,
    )


# ── 序列化 helpers ──

def _serialize_timeline_ir(timeline: TimelineIR) -> dict[str, Any]:
    return {
        "schema_version": timeline.schema_version,
        "property": timeline.property_name,
        "kind": timeline.kind,
        "clock": {"edge": timeline.clock.edge, "signal": timeline.clock.signal},
        "disable_expr": timeline.disable_expr,
        "trigger": {
            "cycle": timeline.trigger.cycle,
            "expr": timeline.trigger.expr,
            "captures": [
                {"var": c.var, "value_expr": c.value_expr,
                 "relative_cycle": c.relative_cycle}
                for c in timeline.trigger.captures
            ],
        },
        "obligations": [
            {"id": ob.id, "kind": ob.kind.value, "expr": ob.expr,
             "has_window": ob.has_window,
             "window": {"start": ob.window.start, "end": ob.window.end, "unbounded": ob.window.unbounded} if ob.window else None,
             "depends_on_captures": ob.depends_on_captures,
             "requirement": ob.requirement,
             "failure_condition": ob.failure_condition}
            for ob in timeline.obligations
        ],
        "match_paths": [
            {"id": p.id, "description": p.description,
             "obligations": [ob.id for ob in p.obligations]}
            for p in timeline.match_paths
        ],
        "failure_conditions": [fc.condition for fc in timeline.failure_conditions],
        "semantic_notes": [
            {"kind": n.kind, "expr": n.expr, "text": n.text}
            for n in timeline.semantic_notes
        ],
    }


def _serialize_surface_ir(surface: SurfaceIR) -> dict[str, Any]:
    output = asdict(surface)
    output.pop("lowering_status", None)
    output.pop("diagnostics", None)
    return output


def _serialize_seq_node(node) -> dict[str, Any]:
    delay = None
    if node.kind.value == "delay":
        delay = {
            "min": node.min_delay,
            "max": None if node.unbounded else node.max_delay,
            "unbounded": node.unbounded,
        }
    repeat = None
    if node.kind.value == "repeat":
        repeat = {
            "kind": node.repeat_kind,
            "min": node.repeat_min,
            "max": None if node.repeat_unbounded else node.repeat_max,
            "unbounded": node.repeat_unbounded,
        }
    return {
        "kind": node.kind.value,
        "lowering_status": node.lowering_status.value,
        "raw": node.raw,
        "expr": node.expr.raw if node.expr else None,
        "guard_expr": node.guard_expr.raw if node.guard_expr else None,
        "actions": [
            {"lhs": action.lhs, "rhs": action.rhs, "action_kind": action.action_kind}
            for action in node.actions
        ],
        "delay": delay,
        "repeat": repeat,
        "children": [_serialize_seq_node(child) for child in node.children],
        "semantic_risk": node.semantic_risk,
        "diagnostics": [asdict(item) for item in node.diagnostics],
    }


def _serialize_sequence_ir(seq_ir: SequenceIR) -> dict[str, Any]:
    return {
        "schema_version": seq_ir.schema_version,
        "name": seq_ir.name,
        "implication": seq_ir.implication,
        "antecedent": [_serialize_seq_node(node) for node in seq_ir.antecedent],
        "consequent": [_serialize_seq_node(node) for node in seq_ir.consequent],
    }


def _print_diagnostics(diags: list) -> None:
    if not diags:
        print("No issues found.")
        return
    for d in diags:
        print(f"[{d.severity}] {d.code}: {d.message}")


def _error_payload(action: str, error: XsvaCliError) -> dict:
    detail = {"code": error.code, "message": error.message}
    if error.details:
        detail["details"] = error.details
    payload = {
        "ok": False, "tool": "xsva", "action": action or "error",
        **_analysis_fields(
            error.analysis_lowering_status,
            error.analysis_diagnostics,
            scan_complete=error.analysis_scan_complete,
            path_total_count=error.analysis_path_total_count,
            path_returned_count=error.analysis_path_returned_count,
            path_enumeration_complete=error.analysis_path_enumeration_complete,
            reason_codes=[error.code],
        ),
        "error": detail,
    }
    normalized = to_jsonable(payload)
    validate_response(normalized, expected_action=action or "error")
    return normalized


def _emit(payload: dict, *, json_mode: bool) -> None:
    validate_response(payload)
    print(dump_json(payload) if json_mode else to_xout(payload), end="" if not json_mode else "\n")


# ── main ──

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xsva", description="SystemVerilog Assertion 语义编译工具")
    subparsers = parser.add_subparsers(dest="command")

    # list
    list_p = subparsers.add_parser("list", help="列出文件中所有 property/assertion")
    list_p.add_argument("--file", required=True, help="SVA 源文件路径")
    list_p.add_argument("--json", action="store_true", help="输出 JSON 格式")

    # scan
    scan_p = subparsers.add_parser("scan", help="扫描语法构造分布")
    scan_p.add_argument("--file", required=True, help="SVA 源文件路径")
    scan_p.add_argument("--json", action="store_true", help="输出 JSON 格式")

    # lint
    lint_p = subparsers.add_parser("lint", help="静态规则检查")
    lint_p.add_argument("--file", required=True, help="SVA 源文件路径")
    lint_p.add_argument("--property", default=None, help="property 名称（可选，不指定则检查全部）")
    lint_p.add_argument("--json", action="store_true", help="输出 JSON 格式")

    # explain
    explain_p = subparsers.add_parser("explain", help="生成 property 解释")
    explain_p.add_argument("--file", required=True, help="SVA 源文件路径")
    explain_p.add_argument("--property", required=True, help="property 名称")
    explain_output = explain_p.add_mutually_exclusive_group()
    explain_output.add_argument("--json", action="store_true", help="输出 JSON 格式")
    explain_output.add_argument("--markdown", action="store_true", help="输出 Markdown 格式")
    explain_p.add_argument("--strict", action="store_true", help="strict 模式：unsupported 时报错退出")

    # parse
    parse_p = subparsers.add_parser("parse", help="输出 IR JSON")
    parse_p.add_argument("--file", required=True, help="SVA 源文件路径")
    parse_p.add_argument("--property", required=True, help="property 名称")
    parse_p.add_argument("--emit", required=True,
                         choices=["surface-ir", "sequence-ir", "timeline-ir"],
                         help="输出 IR 层级")
    parse_p.add_argument("--json", action="store_true", help="输出 JSON 格式")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_SUCCESS

    try:
        dispatch = {
            "list": cmd_list,
            "scan": cmd_scan,
            "lint": cmd_lint,
            "explain": cmd_explain,
            "parse": cmd_parse,
        }
        result = dispatch[args.command](args)
        if isinstance(result, str):
            print(result)
        else:
            _emit(result, json_mode=bool(getattr(args, "json", False)))
        return EXIT_SUCCESS
    except XsvaCliError as error:
        _emit(_error_payload(str(args.command or "error"), error), json_mode=bool(getattr(args, "json", False)))
        return error.exit_code
    except Exception as exc:
        error = XsvaCliError("INTERNAL_ERROR", str(exc), EXIT_INTERNAL_ERROR)
        _emit(_error_payload(str(args.command or "error"), error), json_mode=bool(getattr(args, "json", False)))
        return EXIT_INTERNAL_ERROR
