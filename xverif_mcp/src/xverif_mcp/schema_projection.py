"""Agent-oriented MCP projection for native xdebug schemas."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xverif_loop.config import repo_root
from xverif_mcp.xdebug_contracts import (
    XdebugContractError,
    action_spec,
    query_session_requirement,
    session_contract,
)

Json = dict[str, Any]

_SESSION_TOOL_CONTRACTS: dict[str, Json] = {
    "session.open": {"tool": "xverif_debug_session_open", "required": ["name"], "properties": {
        "name": {"type": "string", "description": "Stable name for the new managed session."},
        "daidir": {"type": "string", "description": "Optional simulation daidir path."},
        "fsdb": {"type": "string", "description": "Optional waveform FSDB path."},
        "run_manifest": {"type": "string", "description": "Optional published run-manifest path to verify before opening."},
        "queue": {"type": "string", "description": "Optional backend queue selection."},
        "resource": {"type": "string", "description": "Optional backend resource request."},
    }},
    "session.list": {"tool": "xverif_debug_session_list", "properties": {
        "include_tombstones": {"type": "boolean", "default": False, "description": "Include terminal tombstone records."},
        "verbose": {"type": "boolean", "default": False, "description": "Include detailed session metadata."},
    }},
    "session.doctor": {"tool": "xverif_debug_session_doctor", "required": ["session_id"], "properties": {
        "session_id": {"type": "string", "description": "Managed session identifier."},
        "verbose": {"type": "boolean", "default": False, "description": "Include detailed health diagnostics."},
    }},
    "session.close": {"tool": "xverif_debug_session_close", "required": ["session_id"], "properties": {
        "session_id": {"type": "string", "description": "Managed session identifier to close."},
        "mode": {"type": "string", "enum": ["graceful", "force"], "default": "graceful", "description": "Explicit lifecycle close mode."},
    }},
    "session.gc": {"tool": "xverif_debug_session_gc", "properties": {
        "verbose": {"type": "boolean", "default": False, "description": "Include unresolved-session detail in the cleanup report."},
    }},
}


def _minimal_call(action: str) -> Json | None:
    spec = action_spec(action)
    if spec is None:
        raise XdebugContractError(f"{action} is absent from the canonical action registry")
    examples = spec.get("examples")
    request_paths = examples.get("request") if isinstance(examples, dict) else None
    if (
        not isinstance(request_paths, list)
        or not request_paths
        or not isinstance(request_paths[0], str)
        or not request_paths[0]
    ):
        raise XdebugContractError(
            f"{action} has no primary request example in the canonical action registry"
        )
    path = Path(repo_root()) / "xdebug" / request_paths[0]
    if not path.is_file():
        raise XdebugContractError(f"{action} primary request example does not exist: {path}")
    request = json.loads(path.read_text(encoding="utf-8"))
    args = request.get("args", {})
    if not isinstance(args, dict):
        raise XdebugContractError(f"{action} basic example args must be an object")
    contract, variant = query_session_requirement(action, args)
    if contract is None:
        raise XdebugContractError(f"{action} is absent from the canonical action registry")
    if contract["mode"] == "conditional":
        if variant is None:
            raise XdebugContractError(f"{action} basic example does not match exactly one resource variant")
        session_state = variant["session_id"]
    else:
        session_state = contract["session_id"]
    call: Json = {"action": action, "args": args}
    if session_state == "required":
        call["session_id"] = "<session_id>"
    if request.get("limits"):
        call["limits"] = request["limits"]
    return call


def _invalid_examples(minimal: Json | None, args_schema: Json) -> list[Json]:
    required = args_schema.get("required", [])
    selector_groups = [group.get("required", []) for group in args_schema.get("anyOf", []) if isinstance(group, dict)]
    if not minimal or not required and not selector_groups:
        return []
    invalid = dict(minimal)
    if "args" in invalid:
        invalid["args"] = {}
    else:
        for name in required:
            invalid.pop(name, None)
        for group in selector_groups:
            for name in group:
                invalid.pop(name, None)
    violations = [f"args.{name}" for name in required]
    if selector_groups:
        violations.append("one required selector group")
    return [{"description": "Invalid: omits every required argument or selector.", "call": invalid, "violates": violations}]


def _constraints(action: str, args_schema: Json) -> list[str]:
    del args_schema
    action_constraints = {
        "apb.export": "标准 APB completed transfer 导出使用顶层 direction/address 与闭合 time_range；省略 output.path 返回最多 8 行 preview，提供 path 时写完整 TSV/CSV artifact。",
        "apb.query": "标准 APB completed transfer 使用 apb.query；address 只接受 exact/range/mask 对象，过滤后再应用 index/line_limit/last。",
        "axi.query": "标准 AXI reconstructed transaction 或精确 channel handshake 使用 axi.query；transaction 模式按 direction/address/id/address-handshake time 取 AND。",
        "event.find": "line_limit 仅在 mode=all 时合法，且只限制返回 evidence，不限制扫描。",
        "stream.query": "仅用 stream.query 查询通用 valid-ready/FIFO/packet/自定义字段；标准 APB/AXI 专用事务分别使用 apb.query/axi.query。field filter 各字段取 AND；cache_scope 默认 full，窄 time_range 可显式使用 range。",
        "stream.export": "cache_scope 默认 full，并与 stream.query 和 dynamic validate 复用同一 base；一次性窄 time_range 可显式使用 range。",
        "stream.validate": "cache_scope 仅在 dynamic=true 时合法；dynamic=false 必须省略。默认 full，窄窗口可显式使用 range。",
        "protocol.handshake.inspect": "check_data_stable_when_stalled 仅在提供 data 时产生 data-stability finding。",
        "signal.anomaly.inspect": "checks 的每项由 type 判别；glitch 必须带 min_pulse_width，stuck 必须带 min_duration。",
    }
    return [action_constraints[action]] if action in action_constraints else []


def _skill_guidance(action: str) -> Json:
    guidance: Json = {
        "skill": "$xverif",
        "reference": "references/capabilities/xdebug.md",
        "instruction": "构造请求前读取 $xverif 的 xdebug workflow、action 路由和完整性合同；不要仅凭本 schema 猜跨 action 语义。",
    }
    routing = {
        "apb.export": "标准 APB completed transfer 的有界预览或完整 artifact 使用 apb.export；交互式行查询使用 apb.query，聚合计数使用 apb.statistics。",
        "apb.query": "标准 APB completed transfer 使用 apb.query；只需聚合计数使用 apb.statistics，自定义 valid-ready 字段使用 stream.query。",
        "axi.query": "标准 AXI channel/reconstructed transaction 使用 axi.query；默认返回每笔第一拍并完整展开第一笔，精确查询后用 output.include_data=true 展开所有 beats。",
        "stream.query": "通用 valid-ready、FIFO、packet 和任意命名字段使用 stream.query；标准 APB/AXI 专用语义分别转 apb.query/axi.query。",
    }
    if action in routing:
        guidance["routing_hint"] = routing[action]
    return guidance


def _canonical_discoverability(action: str, schema: Json) -> Json:
    spec = action_spec(action)
    if spec is None:
        raise XdebugContractError(f"{action} is absent from the canonical action registry")
    use_when = spec.get("use_when")
    do_not_use_when = spec.get("do_not_use_when")
    alternatives = spec.get("alternatives")
    if (
        not isinstance(use_when, list) or not use_when
        or not all(isinstance(value, str) and value for value in use_when)
        or not isinstance(do_not_use_when, list) or not do_not_use_when
        or not all(isinstance(value, str) and value for value in do_not_use_when)
        or not isinstance(alternatives, list)
        or not all(isinstance(value, dict) and isinstance(value.get("action"), str) and value["action"] and isinstance(value.get("when"), str) and value["when"] for value in alternatives)
    ):
        raise XdebugContractError(f"{action} has incomplete canonical discoverability metadata")
    return {
        "purpose_en": spec.get("description_en") or schema.get("description", action),
        "purpose_zh": spec.get("description_zh") or schema.get("x-description-zh") or action,
        "use_when": list(use_when),
        "do_not_use_when": list(do_not_use_when),
        "alternatives": list(alternatives),
    }


def _session_projection(action: str, discoverability: Json, include_examples: bool) -> Json:
    contract = _SESSION_TOOL_CONTRACTS[action]
    args_schema: Json = {"type": "object", "properties": contract["properties"], "additionalProperties": False}
    if contract.get("required"):
        args_schema["required"] = contract["required"]
    minimal = {name: f"<{name}>" for name in contract.get("required", [])}
    payload: Json = {
        "action": action, "kind": "request", "view": "mcp",
        "call_with": contract["tool"], **discoverability,
        "skill_guidance": _skill_guidance(action),
        "session_contract": {"parameter": "session_id", "mode": "dedicated_tool"},
        "fixed_arguments": {}, "args_schema": args_schema,
        "limits_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "constraints": _constraints(action, args_schema), "minimal_call": minimal,
    }
    if include_examples:
        payload["invalid_examples"] = _invalid_examples(minimal, args_schema)
    return payload


def project(action: str, kind: str, view: str, native: Json, include_examples: bool = True) -> Json:
    if native.get("ok") is not True:
        return native
    data = native.get("data", {})
    schema = data.get("schema", {}) if isinstance(data, dict) else {}
    if view == "response":
        if kind != "response":
            return {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": "view=response requires kind=response"}}
        return {"ok": True, "action": "schema", "summary": {"action": action, "kind": kind, "view": view}, "data": {"schema": schema, "schema_path": data.get("schema_path")}}
    if kind != "request":
        return {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": "request MCP projections require kind=request; use view=response"}}
    root = schema.get("properties", {})
    args_schema = root.get("args", {"type": "object", "properties": {}, "additionalProperties": False})
    limits_schema = root.get("limits", {"type": "object", "properties": {}, "additionalProperties": False})
    try:
        discoverability = _canonical_discoverability(action, schema)
        resource_contract = session_contract(action)
        if resource_contract is None:
            raise XdebugContractError(f"{action} is absent from the canonical action registry")
        if action in _SESSION_TOOL_CONTRACTS:
            projected = _session_projection(action, discoverability, include_examples)
            return {"ok": True, "action": "schema", "summary": {"action": action, "kind": kind, "view": view}, "data": projected}
        minimal = _minimal_call(action)
    except XdebugContractError as exc:
        return {"ok": False, "error": {"code": "CONTRACT_UNAVAILABLE", "message": str(exc), "recoverable": False, "error_layer": "projection"}}
    payload: Json = {
        "action": action, "kind": kind, "view": view,
        "call_with": "xverif_debug_query", **discoverability,
        "skill_guidance": _skill_guidance(action),
        "session_contract": resource_contract,
        "fixed_arguments": {"action": action},
        "args_schema": args_schema, "limits_schema": limits_schema,
        "constraints": _constraints(action, args_schema), "minimal_call": minimal,
    }
    if include_examples:
        payload["invalid_examples"] = _invalid_examples(minimal, args_schema)
    return {"ok": True, "action": "schema", "summary": {"action": action, "kind": kind, "view": view}, "data": payload}
