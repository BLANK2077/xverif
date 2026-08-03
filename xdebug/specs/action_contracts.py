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
    "time": "Target sample time. Prefer a canonical string with a unit; a bare number is interpreted only with time_unit.",
    "time_range": "Closed analysis interval. begin and end may be omitted independently to use the available waveform bounds.",
    "time_unit": "Interprets only unitless time numbers; it never overrides a time string that already has a unit.",
    "edge": "Clock sampling edge. The schema default is authoritative; negedge often matches monitor semantics.",
    "sample_point": "Before/after observation point for posedge or dual sampling; it does not change the raw waveform range.",
    "line_limit": "Limits returned evidence rows only, not scanning, aggregation, or the verdict; read completeness fields as well.",
    "signal": "Final leaf signal path. Aggregate, array, and struct roots are not expanded automatically.",
    "signals": "Signal-path list or alias-to-path/expression map. Expressions must reference aliases rather than nested paths.",
    "output": "Export destination and rendering controls. path, file_format, and verbose are supported only where this action declares them.",
    "name": "Saved-object name in this action namespace; do not assume names are shared by cursors, lists, and protocol configs.",
    "mode": "Action processing or return mode. Its legal values, default, and interactions are action-specific.",
    "query": "Action-specific query selector. Do not copy index, channel, or filter forms from another action.",
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
    "aggregate_only": "为 true 时只返回聚合结论，不返回逐项变化 evidence。",
    "analysis": "选择协议分析视图；每个视图返回不同的 primary data 对象。",
    "begin": "闭区间起点；省略时使用可用波形窗口起点。",
    "cache_scope": "Stream 基础分析缓存范围；full 为默认并缓存完整 FSDB，range 只缓存规范化闭区间。range 未提供 time_range 时规范化为 full；engine 不自动 fallback。",
    "bind": "session server 的监听地址或 UDS 绑定设置。",
    "bind_host": "TCP session server 的监听主机地址。",
    "bp": "back-pressure 信号路径；与 rdy 只能按 stream 定义的其中一种流控语义使用。",
    "channel": "协议或 stream 的逻辑 channel 选择；可用值由本 action 的 enum 决定。",
    "clock": "采样、统计或协议检查使用的 clock 信号路径。",
    "conditions": "要在同一采样合同下验证的命名条件列表。",
    "config": "内联配置；字段定义接口 mapping、采样与输入信号，不读取外部文件。",
    "config_path": "配置文件路径；与内联 config 属于互斥输入来源。",
    "context_lines": "目标源码行前后各返回的上下文行数。",
    "data": "valid-ready 或协议 payload 信号路径；提供后才会产生 data 相关检查。",
    "direction": "协议 transaction 的方向过滤；read/write/all 的可用性以本 action enum 为准。",
    "dynamic": "为 true 时允许本 action 已声明的运行时动态检查；不开放未声明字段。",
    "edge": "clock 采样边沿；真实默认值必须读取 schema default。",
    "end": "闭区间终点；省略时使用可用波形窗口终点。",
    "events": "事件表达式或已保存事件名称；与 aggregate/group_by 一起决定返回粒度。",
    "expr": "在指定采样语义下求值或匹配的表达式。",
    "file": "输入配置或源码文件路径；不会隐式推断其它输入来源。",
    "file_format": "写入文件的格式；只允许该 action 明确列出的 enum。",
    "filter": "筛选对象；同级字段通常取 AND，数组候选值取 OR，具体组合由 constraints 说明。",
    "format": "本 action 的值或导出表示格式；不得把其他 action 的同名 format 语义迁入。",
    "group_by": "分组 key 列表；每项必须引用本 action 已定义的 signal alias 或字段。",
    "host": "要连接或启动 session server 的主机名。",
    "include_patterns": "相对当前 scope 的对象名称 glob 列表；列表内取 OR，空列表表示全部包含。",
    "id": "协议 ID 过滤值或候选值集合。",
    "include_data": "为 true 时在 response 中包含 payload/beat 数据；为 false 时只保留 transaction 摘要。",
    "index": "从 1 开始的查询、游标或列表位置；具体基准以本 action schema 说明为准。",
    "kind": "本 action 的结果种类或导出种类；合法值由 enum 限定。",
    "last": "协议 transaction 的最后 beat 或最后匹配条件。",
    "level": "相对当前 scope 进入真实 module 的层数；0 只列本层对象和直接子 module。",
    "line": "源码中的 1-based 行号。",
    "line_limit": "只限制返回 evidence 行数；不限制扫描、聚合或 verdict，必须结合 completeness 解读。",
    "max_depth": "递归 scope 或 trace 展开的最大层数；达到上限时 response 标记截断范围。",
    "max_chains": "trace.x 可返回的最大有效语义 chain 数；纯 port/interface/modport/ref alias 路径先归并，省略时默认为 8。",
    "max_events": "允许处理或写出的事件预算；耗尽会影响 analysis/file completeness。",
    "max_samples": "允许扫描的时钟采样预算；耗尽表示分析不完整而非仅 response 截断。",
    "mode": "该 action 的处理或返回模式；合法值、默认值和参数交互由本 action schema 定义。",
    "name": "本 action 所属命名空间中的已保存对象名称。",
    "exclude_patterns": "相对当前 scope 的对象名称 glob 列表；列表内取 OR，并优先于 include_patterns。",
    "op": "游标或协议浏览操作；begin/next/prev 等含义由本 action enum 限定。",
    "output": "导出目的地和显示控制；path、file_format、verbose 等只在本 action 明确支持时有效。",
    "packet_index": "当前请求窗口内从 0 开始的 packet 位置；只在 packet 查询模式中有效。",
    "path": "输出文件路径；不提供时 action 按其 response-only 合同返回结果。",
    "payload": "单个 payload 信号或表达式，用于脉冲、稳定性或协议检查。",
    "payloads": "payload 信号列表；每项按同一采样合同检查。",
    "port": "session TCP 端口号。",
    "position": "packet filter 的边界位置；sop/eop 决定字段在哪个 packet beat 取值。",
    "query": "本 action 的查询选择器；不要混用其它 action 的 index、channel 或 filter 形态。",
    "ready": "valid-ready 握手中的 ready 信号路径。",
    "reset": "Reset signal and polarity. Samples while reset is asserted do not participate in protocol or event analysis.",
    "role": "设计 trace 中节点的语义角色过滤。",
    "rules": "该 action 的检查规则；省略字段采用对应 schema default，未公开字段不会被接受。",
    "sample_point": "posedge 或 dual 采样的沿前/沿后观察点；不会改变 raw 波形时间范围。",
    "session_id": "目标 xdebug session 标识；MCP 调用使用外层 session_id，而非 native target。",
    "signal": "最终叶子信号路径；aggregate、数组根或 struct 根不会自动展开。",
    "signals": "信号路径列表，或 alias 到路径/表达式的映射；表达式引用 alias。",
    "slice_hint": "值显示的可选位段提示；不改变被读取的底层 signal。",
    "source": "scope roots 或证据的来源选择。",
    "stream": "已加载的 stream 配置名称。",
    "streams": "要加载或定义的 stream 配置列表。",
    "symbol": "源码中的设计符号或层次路径。",
    "time": "目标采样时间；带单位字符串优先，裸数字仅由 time_unit 解释。",
    "time_range": "分析时间闭区间；begin/end 可分别省略，begin 大于 end 是语义错误。",
    "time_unit": "仅解释无单位时间数字；不会覆盖带单位字符串。",
    "transport": "session transport 类型；只使用 schema enum 中明确支持的模式。",
    "valid": "valid-ready 握手中的 valid 信号路径。",
    "value_format": "返回 LogicValue 的显示格式；不改变比较、采样或底层四态值。",
    "verbose": "为 true 时请求该 action 已声明的详细输出；不改变分析范围。",
    "vld": "统计采样有效条件的信号路径或表达式。",
}


ACTION_GUIDANCE: dict[str, Json] = {
    "actions": {"use_when": ["需要发现当前 runtime 公开的 action、状态和适用资源。"],
                "do_not_use_when": ["已经知道 action 且需要它的字段、枚举或 response 合同。"],
                "alternatives": [{"action": "schema", "when": "需要一个已知 action 的完整调用合同。"}]},
    "batch": {"use_when": ["需要按顺序执行多个相互独立的 native xdebug request。"],
              "do_not_use_when": ["需要一个 MCP session 中的单个 action 查询或跨请求共享结果。"],
              "alternatives": [{"action": "schema", "when": "需要先验证单个 request 合同。"}]},
    "trace.active_driver_chain": {
        "use_when": ["需要从指定 signal/time 递归展开单条 active-driver chain；limits.max_depth 默认 8。"],
        "do_not_use_when": ["查询点是 X，且需要同时追踪多个 X RHS/control 分支。"],
        "alternatives": [{"action": "trace.x_origin", "when": "需要按 X 可见性进行多分支追踪。"}],
    },
    "trace.x_origin": {
        "use_when": ["查询点含 X，需要按 DFS 同时追踪 RHS、control、端口和时间边界；纯 port/interface/modport/ref alias 路径会归并，响应会区分 query_time、x_onset_time 与 active_time。"],
        "do_not_use_when": ["只需要静态 driver 枚举，或查询点不含 X。"],
        "alternatives": [
            {"action": "trace.active_driver", "when": "只需要指定时刻的单级 active driver。"},
            {"action": "trace.active_driver_chain", "when": "需要传统单链 active-driver 展开。"},
        ],
    },
    "signal.xz_verify": {
        "use_when": ["需要证明 raw waveform 在整个闭区间内始终为指定 X/Z 状态。"],
        "do_not_use_when": ["只需要寻找一次 X/Z，或需要 clock-edge 表达式验证。"],
        "alternatives": [
            {"action": "signal.anomaly.inspect", "when": "只需要发现窗口内是否曾出现 X/Z。"},
            {"action": "window.verify", "when": "需要按 clock edge 验证已知值表达式。"},
        ],
    },
    "counter.statistics": {"use_when": ["需要按采样 clock 统计一个 counter 的增量、回绕或活动。"],
                           "do_not_use_when": ["需要多个一般信号的活动统计或原始变化列表。"],
                           "alternatives": [{"action": "signal.statistics", "when": "需要一般信号而非 counter 语义的统计。"}]},
    "signal.sampled_pulse.inspect": {"use_when": ["需要发现未被指定 clock sample 捕获的 valid 短脉冲。"],
                               "do_not_use_when": ["需要 raw glitch/stuck 扫描或 valid-ready 协议违规结论。"],
                               "alternatives": [{"action": "signal.anomaly.inspect", "when": "需要 raw pulse/glitch/stuck 异常。"}, {"action": "protocol.handshake.inspect", "when": "需要 valid-ready 协议检查。"}]},
    "schema": {"use_when": ["已知 action 名称，需要其 request 或 response 合同。"],
               "do_not_use_when": ["尚未知道 action 名称，或需要实际执行一个 debug 查询。"],
               "alternatives": [{"action": "actions", "when": "需要先发现 action catalog。"}]},
    "nwave.rc.generate": {"use_when": ["需要从分组信号生成可复用 waveform rc 配置。"],
                    "do_not_use_when": ["需要直接导出当前 waveform evidence 或查询一个信号。"],
                    "alternatives": [{"action": "list.export", "when": "需要导出 list 的当前数据。"}]},
    "verify.conditions": {"use_when": ["需要在一个采样时刻验证命名条件集合。"],
                          "do_not_use_when": ["需要跨时间窗口的持续性结论或原始表达式求值。"],
                          "alternatives": [{"action": "window.verify", "when": "需要跨时间窗口验证。"}, {"action": "expr.eval_at", "when": "需要一个表达式在一个时刻的值。"}]},
    "window.verify": {"use_when": ["需要在时间窗口内按 clock sample 验证多个条件。"],
                      "do_not_use_when": ["只需要单个采样时刻的条件结果或单个信号稳定性。"],
                      "alternatives": [{"action": "verify.conditions", "when": "需要单个时刻的条件验证。"}, {"action": "signal.stability", "when": "需要单信号稳定性检查。"}]},
    "value.at": {
        "use_when": ["需要一个最终叶子信号在精确时间的 raw 值，或显式 clock 采样上下文。"],
        "do_not_use_when": ["需要原始值变化时间线。", "需要多信号布尔表达式求值。"],
        "alternatives": [
            {"action": "signal.changes", "when": "需要每次原始值变化。"},
            {"action": "expr.eval_at", "when": "需要在同一采样时刻求多信号表达式。"},
        ],
    },
    "signal.changes": {
        "use_when": ["需要一个信号的原始波形变化时间线或聚合变化统计。"],
        "do_not_use_when": ["需要按 clock edge 的协议语义采样。"],
        "alternatives": [{"action": "event.find", "when": "需要按 clock 对表达式采样。"}],
    },
    "event.find": {
        "use_when": ["需要按 clock edge 查找满足表达式的采样事件。"],
        "do_not_use_when": ["需要原始 value-change timeline 或标准 AXI/APB transaction。"],
        "alternatives": [{"action": "signal.changes", "when": "需要原始跳变。"}],
    },
    "protocol.handshake.inspect": {
        "use_when": ["需要检查通用 valid-ready transfer、stall 或数据稳定性。"],
        "do_not_use_when": ["需要 AXI/APB 专用 transaction 关联。"],
        "alternatives": [{"action": "axi.query", "when": "接口是标准 AXI。"}],
    },
    "signal.anomaly.inspect": {
        "use_when": ["需要在 raw waveform 中检查 X/Z、短脉冲或长时间不变。"],
        "do_not_use_when": ["需要证明 valid-ready 协议违规。"],
        "alternatives": [{"action": "protocol.handshake.inspect", "when": "需要协议层 stall 或稳定性结论。"}],
    },
    "stream.query": {
        "use_when": ["已加载通用 stream 配置，需要查询 transfer、stall、packet 或字段；连续查询默认 full，一次性窄窗口可显式 range。"],
        "do_not_use_when": ["接口是 AXI/APB 且需要其标准专用语义。"],
        "alternatives": [{"action": "event.find", "when": "只需一次性表达式找点。"}],
    },
}


ACTION_ARG_OVERRIDES: dict[tuple[str, str], Json] = {
    ("value.at", "format"): {
        "description": "Low-level display format for the sampled value. Hexadecimal, binary, and decimal forms return sampled values. array_indexed is accepted only to return the explicit UNSUPPORTED_AGGREGATE_QUERY capability error; export formats are invalid.",
        "type": "string", "enum": ["h", "hex", "b", "bin", "binary", "d", "dec", "decimal", "array_indexed"], "default": "h",
    },
    ("signal.changes", "mode"): {
        "description": "Return mode: timeline emits each change evidence, while summary emits aggregate facts only. Do not combine it with aggregate_only.",
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
        "description": "Base-analysis cache scope. full (default) caches the complete FSDB while the response still honors time_range; range caches only that normalized closed interval. range without time_range reuses full. The engine never falls back automatically.",
        "type": "string", "enum": ["full", "range"], "default": "full",
    },
    ("stream.export", "cache_scope"): {
        "description": "Base-analysis cache scope. full (default) is reusable by query, export, and dynamic validate; use range explicitly for a one-off narrow interval. range without time_range reuses full.",
        "type": "string", "enum": ["full", "range"], "default": "full",
    },
    ("stream.validate", "cache_scope"): {
        "description": "Base-analysis cache scope for dynamic=true only. full (default) caches the complete FSDB; range caches the normalized time_range. Omit this argument when dynamic=false.",
        "type": "string", "enum": ["full", "range"], "default": "full",
    },
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
    if action in ACTION_GUIDANCE:
        return deepcopy(ACTION_GUIDANCE[action])
    specs_path = Path(__file__).with_name("actions") / "actions.yaml"
    try:
        specs = json.loads(specs_path.read_text(encoding="utf-8"))["actions"]
        spec = next(item for item in specs if item["name"] == action)
    except (OSError, ValueError, KeyError, StopIteration):
        return {"use_when": [f"需要执行 {action} 的公开能力。"],
                "do_not_use_when": [f"不适用于 {action} 以外的资源或分析目标。"],
                "alternatives": []}
    purpose = spec.get("description_zh", action)
    peers = [item for item in specs if item["name"] != action and item.get("status") != "removed"
             and item["name"].split(".", 1)[0] == action.split(".", 1)[0]]
    if not peers:
        peers = [item for item in specs if item["name"] != action and item.get("status") != "removed"
                 and item["name"].split(".", 1)[0] == spec.get("category")]
    alternatives = [
        {"action": item["name"], "when": item.get("description_zh", item["name"])}
        for item in peers[:2]
    ]
    if alternatives:
        names = "、".join(item["action"] for item in alternatives)
        do_not_use = f"不要把本 action 用于 {names} 的业务目标；请改用列出的同域 action。"
    else:
        do_not_use = "不要把本 action 用作不属于其已声明业务对象的查询；当前没有更近的公开替代 action。"
    return {"use_when": [purpose], "do_not_use_when": [do_not_use], "alternatives": alternatives}


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
    elif name in COMMON_DESCRIPTIONS:
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
    generated_placeholder = isinstance(result.get("description"), str) and any(
        marker in result["description"]
        for marker in ("action-specific 参数值", "组合参数对象", "有序项目列表")
    )
    if generated_placeholder:
        result.pop("description", None)
        result.pop("x-description-zh", None)
    existing_description = result.get("description")
    if isinstance(existing_description, str) and existing_description.isascii():
        pass
    elif english_common:
        result["description"] = english_common
    elif result.get("type") == "object" or "properties" in result:
        result["description"] = f"Structured {field} configuration. Only the declared properties are accepted."
    elif result.get("type") == "array":
        result["description"] = f"Ordered {field} entries. Each item must satisfy the declared item contract."
    elif result.get("type") in {"string", "integer", "number", "boolean"}:
        result["description"] = f"Action-specific {field} input. Its type and accepted values are defined by this schema."
    elif semantic and "description" not in result:
        result["description"] = f"Action-specific {field} contract."
    for key, value in list(result.get("properties", {}).items()):
        if isinstance(value, dict):
            result["properties"][key] = complete_descriptions(value, f"{path}.{key}")
    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = complete_descriptions(items, f"{path}[]")
    additional = result.get("additionalProperties")
    if isinstance(additional, dict):
        dynamic_name = field
        if dynamic_name == "signals":
            additional["description"] = "Value for a caller-defined signal alias key. Supply the real signal path or the action-supported expression for that alias."
            additional["x-dynamic-contract"] = "Each property key is an alias referenced by this action; each value resolves that alias to a signal path or supported expression."
        elif dynamic_name in {"beat_fields", "packet_stable_fields"}:
            additional["description"] = "Value for a caller-defined stream field name. Supply the signal path sampled for that field."
            additional["x-dynamic-contract"] = "Each property key is a stream field name and each value is its signal path."
        else:
            additional["description"] = f"Value for a caller-defined {dynamic_name} key."
            additional["x-dynamic-contract"] = "The property name is caller-defined; the value must follow this declared schema."
        result["additionalProperties"] = complete_descriptions(additional, f"{path}.*")
    for keyword in ("oneOf", "anyOf", "allOf"):
        branches = result.get(keyword)
        if isinstance(branches, list):
            result[keyword] = [complete_descriptions(item, path) if isinstance(item, dict) else item for item in branches]
    return result
