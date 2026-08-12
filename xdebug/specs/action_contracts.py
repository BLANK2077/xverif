"""Canonical AI-facing contracts for xdebug public actions.

The action directory owns registration; this module owns the semantics that an
agent needs in order to construct a request.  It deliberately keys overrides
by ``(action, argument)`` rather than bare argument name.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


Json = dict[str, Any]


COMMON_DESCRIPTIONS = {
    "time": "Target sample time. Prefer a canonical string with a unit; a bare number is interpreted as nanoseconds.",
    "times": "Ordered non-empty list of unique target sample times. Actions that also expose time use time for one point and times for one or more points.",
    "list": "Name of a loaded waveform signal list.",
    "apb": "Name of a loaded APB interface configuration.",
    "axi": "Name of a loaded AXI interface configuration.",
    "time_range": "Closed analysis interval. begin and end may be omitted independently to use the available waveform bounds.",
    "render_time_unit": "Controls only canonical response time rendering: auto, ps, ns, or us. It never changes input parsing, sampling, filtering, or ordering.",
    "edge": "Clock sampling edge. The schema default is authoritative; negedge often matches monitor semantics.",
    "sample_point": "Before/after observation point for posedge or dual sampling; it does not change the raw waveform range.",
    "line_limit": "Limits returned evidence rows only, not scanning, aggregation, or the verdict; read completeness fields as well.",
    "signal": "Final leaf signal path. Aggregate, array, and struct roots are not expanded automatically.",
    "signals": "Signal-path list or alias-to-path/expression map. Expressions must reference aliases rather than nested paths.",
    "output": "Export destination and rendering controls. path, file_format, and verbose are supported only where this action declares them.",
    "ownership_token": "Optional caller-supplied conditional-cleanup token for a managed wrapper. The frontend binds a fail-closed internally generated token when session.open omits it; when supplied to session.close it is allowed only with mode=force and one exact session id, and must match. Omission preserves explicit administrative cleanup semantics. It is never a response, error, or logging field.",
    "name": "Saved-object name in this action namespace; do not assume names are shared by cursors, lists, and protocol configs.",
    "mode": "Action processing or return mode. Its legal values, default, and interactions are action-specific.",
    "query": "Closed query selector; use only the index, channel, time, or filter branches declared by this action's schema.",
    "rules": "Protocol or check-rule object. Nested fields define each rule default and applicability.",
    "limits": "Execution resource limits. Use this action's top-level limits properties, never args.limits.",
    "vld": "Signal path or expression defining the valid sampling condition for counter statistics.",
    "data": "Valid-ready or protocol payload signal path. Data-specific checks run only when it is supplied.",
    "index": "One-based query, cursor, or list position; the action schema defines its exact reference set.",
}

# These descriptions are deliberately keyed by semantic field, not by the
# first action that happened to use the spelling.  Action-specific overrides
# below always win.  Keeping this dictionary here makes the generated schema,
# MCP guide and examples use exactly the same vocabulary.
FIELD_DESCRIPTIONS = {
    "addr": "要匹配或返回的总线地址；可使用本 action 定义的数值 literal 形式。",
    "address": "地址过滤条件；exact、range 和 mask 分支互斥。",
    "aggregate": "聚合请求；省略时返回逐项 evidence，提供时按 operation 返回汇总。",
    "analysis": "选择协议分析视图；每个视图返回不同的 primary data 对象。",
    "allow_interleaving": "为 true 时允许不同 channel_id 的 packet beat 交错；同一 channel 内仍按顺序组包。",
    "araddr": "AXI ARADDR 信号路径。",
    "arburst": "AXI ARBURST burst-type 信号路径。",
    "arid": "AXI ARID 信号路径；当前 AXI config schema 和 manager 要求显式提供。",
    "arlen": "AXI ARLEN burst-length 信号路径。",
    "arready": "AXI ARREADY 信号路径。",
    "arsize": "AXI ARSIZE beat-byte-size 信号路径。",
    "arvalid": "AXI ARVALID 信号路径。",
    "bid": "AXI BID 写响应 ID 信号路径。",
    "bready": "AXI BREADY 信号路径。",
    "bresp": "AXI BRESP 写响应状态信号路径。",
    "bvalid": "AXI BVALID 信号路径。",
    "begin": "闭区间起点；省略时使用可用波形窗口起点。",
    "cache_scope": "Stream 基础分析缓存范围；full 为默认并缓存完整 FSDB，range 只缓存显式 time_range 规范化后的闭区间。range 必须同时提供非空 time_range。",
    "category": "Action catalog 分类过滤值；用于筛选 action 所属的 builtin、design、waveform、protocol 或 combined 业务域。",
    "bind_host": "TCP session server 的监听主机地址。",
    "bp": "back-pressure 信号路径；与 rdy 只能按 stream 定义的其中一种流控语义使用。",
    "channel": "协议或 stream 的逻辑 channel 选择；可用值由本 action 的 enum 决定。",
    "channel_id": "用于区分可交错 stream channel 的 ID 信号路径。",
    "channel_id_valid": "指示 channel_id 在当前 stream beat 有效的信号路径。",
    "clock": "采样、统计或协议检查使用的 clock 信号路径。",
    "conditions": "要在同一采样合同下验证的命名条件列表。",
    "cnt": "要统计的 counter 信号路径；按 clock/vld 采样并计算递增、保持和异常跳变。",
    "config": "内联配置；字段定义接口 mapping、采样与输入信号，不读取外部文件。",
    "config_path": "配置文件路径；与内联 config 属于互斥输入来源。",
    "context_lines": "目标源码行前后各返回的上下文行数。",
    "direction": "协议 transaction 的方向过滤；read/write/all 的可用性以本 action enum 为准。",
    "description": "该保存对象的人类可读说明；不参与信号解析、匹配或采样语义。",
    "dynamic": "为 true 时允许本 action 已声明的运行时动态检查；不开放未声明字段。",
    "end": "闭区间终点；省略时使用可用波形窗口终点。",
    "events": "事件表达式或已保存事件名称；与 aggregate/group_by 一起决定返回粒度。",
    "expr": "在指定采样语义下求值或匹配的表达式。",
    "file": "输入配置或源码文件路径；不会隐式推断其它输入来源。",
    "file_format": "写入文件的格式；只允许该 action 明确列出的 enum。",
    "filter": "筛选对象；同级字段通常取 AND，数组候选值取 OR，具体组合由 constraints 说明。",
    "fields": "按 stream field 名组织的过滤条件；每个 key 必须是配置中声明的 beat 或 packet field。",
    "format": "本 action 的值或导出表示格式；不得把其他 action 的同名 format 语义迁入。",
    "group_by": "分组 key 列表；每项必须引用本 action 已定义的 signal alias 或字段。",
    "host": "要连接或启动 session server 的主机名。",
    "id": "协议 ID 过滤值或候选值集合。",
    "include_patterns": "相对当前 scope 的对象名称 glob 列表；列表内取 OR，空列表表示全部包含。",
    "include_data": "为 true 时在 response 中包含 payload/beat 数据；为 false 时只保留 transaction 摘要。",
    "handshake_time": "用于定位协议 channel handshake 的 canonical 时间；必须匹配该 channel 的 VALID&&READY 采样点。",
    "kind": "本 action 的结果种类或导出种类；合法值由 enum 限定。",
    "keyword": "Action catalog 关键词过滤文本；在 action 名称和已发布的语义描述中匹配。",
    "last": "协议 transaction 的最后 beat 或最后匹配条件。",
    "level": "相对当前 scope 进入真实 module 的层数；0 只列本层对象和直接子 module。",
    "line": "源码中的 1-based 行号。",
    "max_depth": "递归 scope 或 trace 展开的最大层数；达到上限时 response 标记截断范围。",
    "max_chains": "trace.x_origin 可返回的最大有效语义 chain 数；纯 port/interface/modport/ref alias 路径先归并，省略时默认为 8。",
    "max_events": "允许处理或写出的事件预算；耗尽会影响 analysis/file completeness。",
    "max_samples": "允许扫描的时钟采样预算；耗尽表示分析不完整而非仅 response 截断。",
    "method": "离群延迟判定方法；threshold 与其它参数的适用性由选定方法的 schema 分支决定。",
    "exclude_patterns": "相对当前 scope 的对象名称 glob 列表；列表内取 OR，并优先于 include_patterns。",
    "no_statement_only": "为 true 时排除只代表 statement、没有结构化设计对象语义的 trace 结果。",
    "op": "游标或协议浏览操作；begin/next/prev 等含义由本 action enum 限定。",
    "packet_index": "当前请求窗口内从 0 开始的 packet 位置；只在 packet 查询模式中有效。",
    "path": "输出文件路径；不提供时 action 按其 response-only 合同返回结果。",
    "payload": "单个 payload 信号或表达式，用于脉冲、稳定性或协议检查。",
    "payloads": "payload 信号列表；每项按同一采样合同检查。",
    "payload_changed_without_sampled_valid": "payload 在 sampled valid 未成立时发生变化的报告粒度：off 禁用，summary 仅汇总，all 返回逐项 evidence。",
    "paddr": "APB PADDR 信号路径。",
    "pready": "可选 APB PREADY 信号路径；省略表示该接口没有 PREADY，access phase 按 APB2 语义完成。",
    "prdata": "APB PRDATA 读数据总线信号路径。",
    "pwrite": "APB PWRITE 方向信号路径。",
    "pwdata": "APB PWDATA 写数据总线信号路径。",
    "port": "session TCP 端口号。",
    "position": "packet filter 的边界位置；sop/eop 决定字段在哪个 packet beat 取值。",
    "ready": "valid-ready 握手中的 ready 信号路径。",
    "rdy": "Stream valid-ready 流控中的 ready 信号路径；与 bp 流控分支互斥。",
    "rdata": "AXI RDATA 读数据总线信号路径。",
    "rid": "AXI RID 读数据 ID 信号路径。",
    "rlast": "AXI RLAST 最后一拍指示信号路径。",
    "rready": "AXI RREADY 信号路径。",
    "rresp": "AXI RRESP 读响应状态信号路径。",
    "rvalid": "AXI RVALID 信号路径。",
    "reset": "Reset signal and polarity. Samples while reset is asserted do not participate in protocol or event analysis.",
    "role": "设计 trace 中节点的语义角色过滤。",
    "slice_hint": "值显示的可选位段提示；不改变被读取的底层 signal。",
    "source": "scope roots 或证据的来源选择。",
    "stream": "已加载的 stream 配置名称。",
    "streams": "要加载或定义的 stream 配置列表；每项独立声明流控、packet 边界与字段 mapping。",
    "symbol": "源码中的设计符号或层次路径。",
    "transport": "session transport 类型；只使用 schema enum 中明确支持的模式。",
    "valid": "valid-ready 握手中的 valid 信号路径。",
    "values": "地址或字段过滤的候选值列表；候选之间按 OR 匹配，空列表不合法。",
    "value_format": "返回 LogicValue 的显示格式；不改变比较、采样或底层四态值。",
    "verbose": "为 true 时请求该 action 已声明的详细输出；不改变分析范围。",
    "requests": "Batch 中按顺序执行的完整 xdebug public request 列表；每个子请求仍按自身 action schema 严格校验。",
    "expected_state": "四态检查期望集合；用于区分已知、X、Z 或 action schema 声明的组合状态。",
    "awvalid": "AXI AWVALID 信号路径。",
    "awready": "AXI AWREADY 信号路径。",
    "awaddr": "AXI AWADDR 信号路径。",
    "awid": "AXI AWID 信号路径；当前 AXI config schema 和 manager 要求显式提供。",
    "awlen": "AXI AWLEN burst-length 信号路径。",
    "awsize": "AXI AWSIZE beat-byte-size 信号路径。",
    "awburst": "AXI AWBURST burst-type 信号路径。",
    "wdata": "AXI WDATA 写数据总线信号路径。",
    "wlast": "AXI WLAST 最后一拍指示信号路径。",
    "wready": "AXI WREADY 信号路径。",
    "wstrb": "AXI WSTRB 写字节使能信号路径。",
    "wvalid": "AXI WVALID 信号路径。",
    "beat_fields": "Stream 每个传输 beat 采样的命名字段到信号路径 mapping。",
    "packet_stable_fields": "Packet 从 SOP 到 EOP 期间必须保持稳定的命名字段到信号路径 mapping。",
    "pslverr": "APB PSLVERR 信号路径；接口不实现错误响应时可按 config schema 省略。",
    "eop": "Packet stream 的 end-of-packet 边界信号路径。",
    "match_mode": "四态匹配模式；exact 区分 0/1/X/Z，已声明的宽松模式仅按 schema 所述集合比较。",
    "penable": "APB PENABLE 信号路径。",
    "psel": "APB PSEL 信号路径。",
    "purposes": "Action catalog purpose 过滤值；用于筛选 discover、query、validate、trace、export 等使用意图。",
    "requires": "Action catalog 资源需求过滤值；用于筛选 none、design、waveform、combined 或 session action。",
    "sop": "Packet stream 的 start-of-packet 边界信号路径。",
    "threshold": "离群或规则判定阈值；单位和比较方向由同一 action 的 method/rule 分支定义。",
    "top_n": "按判定分数排序后最多返回的离群项数量；不改变完整分析集合。",
}


ACTION_ARG_OVERRIDES: dict[tuple[str, str], Json] = {
    ("list.delete", "name"): {
        "type": "string",
        "minLength": 1,
        "description": "Non-empty saved waveform-list name in the current session.",
    },
    ("list.delete", "signal"): {
        "type": "string",
        "minLength": 1,
        "description": "Non-empty exact signal path to remove; numeric-looking paths remain paths.",
    },
    ("signal.changes", "mode"): {
        "description": "Return mode: timeline emits each change evidence, while summary emits aggregate facts only.",
        "enum": ["timeline", "summary"], "default": "timeline",
    },
    ("event.find", "mode"): {
        "description": "first and last return the chronologically first or last match; all returns multiple matches. line_limit is valid only with all.",
        "enum": ["first", "last", "all"], "default": "first",
    },
    ("event.find", "max_samples"): {
        "description": "Maximum number of clock samples to inspect. Exhaustion makes analysis incomplete; it is not a response-row limit.",
        "type": "integer", "minimum": 1,
    },
    ("event.find", "reset"): {
        "description": "Optional reset signal. Samples while reset is asserted do not participate in event matching.",
    },
    ("protocol.handshake.inspect", "rules"): {
        "description": "Valid-ready inspection rules. Omitted fields use their declared schema defaults.",
        "type": "object", "properties": {
            "max_wait_cycles": {"type": "integer", "minimum": 0, "description": "Maximum consecutive wait cycles from a sampled valid=1 until handshake."},
            "check_data_stable_when_stalled": {"type": "boolean", "default": False, "description": "Effective only when data is supplied; checks whether data changes while valid=1 and ready=0."},
            "require_valid_hold_until_handshake": {"type": "boolean", "default": True, "description": "Checks that valid remains asserted from its first assertion through valid&&ready handshake."},
            "ready_without_valid": {"type": "string", "enum": ["summary", "intervals", "all"], "default": "summary", "description": "Reporting granularity for ready=1 and valid=0. This is activity information, not by itself a protocol violation."},
        }, "additionalProperties": False,
    },
    ("protocol.handshake.inspect", "data"): {
        "description": "可选 payload 信号路径或路径列表；仅提供时才可检查 stalled-data stability。",
    },
    ("axi.channel_stall", "rules"): {
        "description": "AXI channel stall 阈值规则。",
        "type": "object", "properties": {
            "max_wait_cycles": {"type": "integer", "minimum": 0, "default": 100,
                                "description": "超过该连续 valid&&!ready sample 数才返回 long_stall finding。"},
        }, "additionalProperties": False,
    },
    ("event.export", "aggregate"): {
        "description": "导出聚合控制。events=false 时只返回 aggregate；group_by 按 event fields 或 signal aliases 统计。",
        "type": "object", "properties": {
            "events": {"type": "boolean", "default": True,
                       "description": "为 false 时不在 response 中返回逐项 events，只返回 aggregate。"},
            "group_by": {"type": "array", "items": {"type": "string", "minLength": 1,
                         "description": "要参与聚合分组的 event field 或 signal alias。"}, "uniqueItems": True,
                         "description": "聚合分组 key 列表。"},
        }, "additionalProperties": False,
    },
    ("signal.anomaly.inspect", "checks"): {
        "description": "要执行的 raw-waveform 检查。省略时执行运行时默认检查集合；字符串 shorthand 不被接受。",
        "type": "array", "minItems": 1, "items": {"description": "一项由 type 判别的 abnormal 检查。", "oneOf": [
            {"type": "object", "description": "unknown_xz 检查项。", "required": ["type"], "properties": {"type": {"const": "unknown_xz", "description": "报告区间内出现的 X/Z。"}}, "additionalProperties": False},
            {"type": "object", "description": "glitch 检查项。", "required": ["type", "min_pulse_width"], "properties": {"type": {"const": "glitch", "description": "选择短脉冲检查。"}, "min_pulse_width": {"type": "string", "description": "报告严格短于该 canonical duration 的脉冲。"}}, "additionalProperties": False},
            {"type": "object", "description": "stuck 检查项。", "required": ["type", "min_duration"], "properties": {"type": {"const": "stuck", "description": "选择长时间不变检查。"}, "min_duration": {"type": "string", "description": "报告持续至少该 canonical duration 的不变区间。"}}, "additionalProperties": False},
        ]},
    },
    ("stream.query", "query"): {
        "description": "查询种类。beat stream 支持 summary、first/last_transfer、transfer_window、first/last_stall、stall_window；packet stream 还支持 first/last_packet、packet_at、packet_window。启用 filter 时可用集合进一步受 packet 边界限制。",
        "type": "string", "enum": ["summary", "first_transfer", "last_transfer", "transfer_window", "first_stall", "last_stall", "stall_window", "first_packet", "last_packet", "packet_at", "packet_window"],
    },
    ("stream.query", "cache_scope"): {
        "description": "Base-analysis cache scope. full (default) caches the complete FSDB while the response still honors time_range; range requires a non-empty time_range and caches only that normalized closed interval.",
        "type": "string", "enum": ["full", "range"], "default": "full",
    },
    ("stream.export", "cache_scope"): {
        "description": "Base-analysis cache scope. full (default) is reusable by query, export, and dynamic validate; range requires a non-empty time_range and caches only that one-off normalized interval.",
        "type": "string", "enum": ["full", "range"], "default": "full",
    },
    ("stream.validate", "cache_scope"): {
        "description": "Base-analysis cache scope for dynamic=true only. full (default) caches the complete FSDB; range requires a non-empty time_range and caches that normalized interval. Omit this argument when dynamic=false.",
        "type": "string", "enum": ["full", "range"], "default": "full",
    },
}


def actions_filter_schema() -> Json:
    """Return the shared closed filter contract for the actions catalog.

    The request accepts any non-empty subset of these four optional fields and
    the response echoes that exact object, including the canonical empty
    object when no filter was requested.  Keeping the shape here prevents the
    response contract from being inferred from one particular example.
    """

    def string_filter(values: list[str]) -> Json:
        return {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": values},
        }

    return {
        "type": "object",
        "properties": {
            "category": string_filter(
                ["builtin", "design", "waveform", "combined", "session"]
            ),
            "requires": string_filter(
                ["none", "design", "waveform", "combined", "any", "session"]
            ),
            "purposes": string_filter(
                [
                    "discover",
                    "configure",
                    "query",
                    "inspect",
                    "analyze",
                    "trace",
                    "verify",
                    "export",
                    "manage",
                    "transform",
                    "orchestrate",
                ]
            ),
            "keyword": {"type": "string", "pattern": ".*\\S.*"},
        },
        "additionalProperties": False,
    }


def reset_schema() -> Json:
    return {
        "type": "object",
        "required": ["signal", "polarity"],
        "properties": {
            "signal": {
                "type": "string", "minLength": 1,
                "description": "One-bit final waveform signal path used as reset.",
            },
            "polarity": {
                "type": "string", "enum": ["active_low", "active_high"],
                "description": "Level that asserts reset. X, Z, and unavailable samples are conservatively treated as asserted.",
            },
        },
        "additionalProperties": False,
        "description": "Reset definition. Both signal and polarity are required when reset is supplied.",
    }


def guidance_for(action: str) -> Json:
    specs_path = Path(__file__).with_name("actions") / "actions.yaml"
    try:
        specs = json.loads(specs_path.read_text(encoding="utf-8"))["actions"]
        spec = next(item for item in specs if item["name"] == action)
    except (OSError, ValueError, KeyError, StopIteration):
        raise ValueError(f"{action}: missing canonical action guidance")
    guidance = {
        "use_when": spec.get("use_when"),
        "do_not_use_when": spec.get("do_not_use_when"),
        "alternatives": spec.get("alternatives"),
    }
    if (
        not isinstance(guidance["use_when"], list)
        or not guidance["use_when"]
        or not isinstance(guidance["do_not_use_when"], list)
        or not guidance["do_not_use_when"]
        or not isinstance(guidance["alternatives"], list)
    ):
        raise ValueError(f"{action}: invalid canonical action guidance")
    return deepcopy(guidance)


def apply_argument_contract(action: str, name: str, schema: Json) -> Json:
    """Return the action-specific property contract without mutating its input."""
    result = deepcopy(schema)
    override = ACTION_ARG_OVERRIDES.get((action, name))
    if override:
        if "type" in override:
            for key in ("oneOf", "anyOf", "allOf"):
                result.pop(key, None)
        if "oneOf" in override:
            for key in ("type", "properties", "items", "required"):
                result.pop(key, None)
        result.update(deepcopy(override))
    elif name in COMMON_DESCRIPTIONS and not (
        isinstance(result.get("description"), str) and result["description"].strip()
    ):
        result["description"] = COMMON_DESCRIPTIONS[name]
        result.pop("x-description-zh", None)
    if "description" not in result and name in COMMON_DESCRIPTIONS:
        result["description"] = COMMON_DESCRIPTIONS[name]
    return result


def complete_descriptions(schema: Json, path: str) -> Json:
    """Fill structural descriptions for generated nested fields.

    Action-specific text must be supplied above for semantic fields; this
    keeps generated helper shapes discoverable instead of exposing anonymous
    JSON objects to an agent.
    """
    result = deepcopy(schema)
    result.pop("x-description-zh", None)
    field = path.rsplit(".", 1)[-1].replace("[]", "")
    semantic = FIELD_DESCRIPTIONS.get(field)
    english_common = COMMON_DESCRIPTIONS.get(field)
    generated_placeholder = (
        isinstance(result.get("description"), str)
        and (
            any(
                marker in result["description"]
                for marker in ("action-specific 参数值", "组合参数对象", "有序项目列表")
            )
            or result["description"].startswith(
                ("Action-specific ", "Structured ", "Ordered ")
            )
        )
    )
    if generated_placeholder:
        result.pop("description", None)
        result.pop("x-description-zh", None)
    existing_description = result.get("description")
    if isinstance(existing_description, str) and existing_description.strip():
        pass
    elif semantic:
        result["description"] = semantic
    elif english_common:
        result["description"] = english_common
    elif any(
        key in result
        for key in (
            "type", "properties", "items", "oneOf", "anyOf", "allOf",
            "enum", "const",
        )
    ):
        raise ValueError(
            f"{path}: public request contract is missing a maintained semantic description"
        )
    for key, value in list(result.get("properties", {}).items()):
        if isinstance(value, dict):
            result["properties"][key] = complete_descriptions(value, f"{path}.{key}")
    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = complete_descriptions(items, f"{path}[]")
    additional = result.get("additionalProperties")
    if isinstance(additional, dict):
        dynamic_name = field
        result["x-dynamic-map"] = True
        if dynamic_name == "signals":
            additional["description"] = "Value for a caller-defined signal alias key. Supply the real signal path or the action-supported expression for that alias."
            result["x-dynamic-contract"] = "Each property key is an alias referenced by this action; each value resolves that alias to a signal path or supported expression."
        elif dynamic_name in {"beat_fields", "packet_stable_fields"}:
            additional["description"] = "Value for a caller-defined stream field name. Supply the signal path sampled for that field."
            result["x-dynamic-contract"] = "Each property key is a stream field name and each value is its signal path."
        else:
            additional["description"] = f"Value for a caller-defined {dynamic_name} key."
            result["x-dynamic-contract"] = "The property name is caller-defined; the value must follow this declared schema."
        result["additionalProperties"] = complete_descriptions(additional, f"{path}.*")
    for keyword in ("oneOf", "anyOf", "allOf"):
        branches = result.get(keyword)
        if isinstance(branches, list):
            result[keyword] = [complete_descriptions(item, path) if isinstance(item, dict) else item for item in branches]
    return result
