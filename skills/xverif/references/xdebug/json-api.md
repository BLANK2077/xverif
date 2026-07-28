# xdebug JSON API 速查

本文说明 xdebug 原生 `xdebug.v1` action 的 CLI request、target、output、transport 和示例。本文件只讲 `tools/xdebug --json -` / `xdebug --json -` 的完整 envelope；MCP tool 参数壳请使用 `xverif-mcp`。

## CLI 入口规则

CLI 场景下，AI agent 调用 xdebug 能力应构造完整 `xdebug.v1` JSON request：

1. 直接调用 `tools/xdebug --json -` 或 `xdebug --json -`。
2. stateful 查询先用原生 `session.open` action 打开 session。
3. 后续原生 request 用 `target.session_id` 选择已打开 session。
4. 不要把 MCP query 的顶层 `session_id`、`output_format`、`xverif_batch.tool` 写进 CLI envelope。
5. 只做一次性查询时也必须带 `api_version` 和 `action`；resource 放在 `target`，action 参数放在 `args`。

CLI envelope 示例：

默认优先使用 xout 输出；只有脚本需要稳定读取 JSON 字段，或专门验证 JSON response/schema 时，才给 CLI 加 `--json`。

```json
{
  "api_version": "xdebug.v1",
  "action": "value.batch_at",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "time": "100ns",
    "clock": "top.u.clk",
    "signals": [
      "top.u.valid",
      "top.u.ready",
      "top.u.data"
    ],
    "value_format": "hex"
  }
}
```

本文不是最终契约。最终契约优先级：

1. `xdebug --json -` 调用 `actions`
2. `schema` action 返回的 action-specific schema
3. `xdebug/schemas/v1/actions/*.schema.json`
4. `xdebug/examples/requests/*.basic.json` 与 `xdebug/examples/responses/*.basic.json`
5. 本 reference

不确定 action 参数或返回字段时，先查 runtime `actions` / `schema`，不要猜字段。

## 参数错误恢复

xdebug 有两层参数错误提示：

1. schema 层：字段缺失、类型错误、非法 enum、`additionalProperties:false` 禁止的多余字段、`anyOf` 必填组不满足。
2. action handler 层：schema 允许但语义非法的参数，例如反向 `time_range`、不存在的 signal/config、handler 内部枚举或时间解析失败。

两层错误都应尽量返回可恢复字段：

| 字段 | 用法 |
| --- | --- |
| `invalid_arg` | 直接指出错误字段路径，例如错误数量字段、`args.time_range.end` |
| `expected` | 说明期望类型、范围或语义 |
| `allowed_values` | enum 或有限取值列表 |
| `did_you_mean` | 常见错字段的正确字段，例如 `args.query.line_limit` |
| `required_any_of` | 至少提供其中一组字段 |
| `correct_example` | 可复制的最小正确 request 模板 |

AI agent 调用失败时先按这些字段修 request。不要仅凭 `message` 猜测，也不要静默 fallback 到旧字段、旧 transport 或其它 action。

## 请求 envelope

```json
{
  "api_version": "xdebug.v1",
  "request_id": "optional-id",
  "action": "trace.driver",
  "target": {
    "daidir": "simv.daidir",
    "fsdb": "waves.fsdb"
  },
  "args": {"signal": "top.u.ready"},
  "limits": {}
}
```

## Action-specific schema

所有当前公开且未移除的 action 都有独立 schema 和 basic example：

```text
xdebug/schemas/v1/actions/<action>.request.schema.json
xdebug/schemas/v1/actions/<action>.response.schema.json
xdebug/examples/requests/<action>.basic.json
xdebug/examples/responses/<action>.basic.json
```

调用 `actions` 默认在 `data.actions[]` 返回 compact action names；需要 `request_schema`、`response_schema`、`request_examples`、`response_examples` descriptor 时传 `args.output.verbose:true`。AI agent 需要精确契约时应使用这些 action-specific 文件；通用 envelope schema 不替代 action schema。

字段说明：

| 字段 | 说明 |
| --- | --- |
| `api_version` | 固定使用 `xdebug.v1` |
| `request_id` | 可选，用于调用方关联请求 |
| `action` | 动作名，例如 `trace.driver`、`value.at` |
| `target` | `daidir`、`fsdb`、两者组合，或 `session_id` |
| `args` | action 参数 |
| `limits` | 行数、事件数、深度、路径数等限制 |

## target 行为矩阵

| target | 路由 |
| --- | --- |
| `{"daidir":"simv.daidir"}` | 设计侧 |
| `{"fsdb":"waves.fsdb"}` | 波形侧 |
| `{"daidir":"simv.daidir","fsdb":"waves.fsdb"}` | 联合侧，并允许回退到设计/波形 action |
| `{"session_id":"case_a"}` | 使用已打开 session 的资源集合 |

## session transport 字段

默认 transport 是 `uds`。只有 UDS socket 不可达、容器/namespace 隔离或用户明确需要跨边界连接 daemon 时，才考虑 TCP。除非用户明确要求或项目文档明确指定，不要使用 `file` transport；遇到 `SESSION_UNHEALTHY child_exited`、旧 session 冲突或 UDS 问题时，不要把 `file` transport 当 fallback。

| 字段 | 位置 | 说明 |
| --- | --- | --- |
| `transport` | `args` 或 `target` | `uds` / `tcp` / `file`，默认 `uds`，可由 `XDEBUG_TRANSPORT` 控制 |
| `bind_host` / `bind` | `args` 或 `target` | daemon listen 地址；本机 TCP 推荐 `127.0.0.1` |
| `host` | `args` 或 `target` | client 连接地址；远程/跨容器时应是 agent 可达地址 |
| `port` | `args` 或 `target` | TCP 端口；`0` 或省略表示自动分配 |
| `file_dir` | response/log | file transport 的 session 交换目录，由 xdebug 生成 |

`XDEBUG_TRANSPORT=uds|tcp|file` 只影响新建 session；JSON 中显式的 `args.transport` 或 `target.transport` 优先级更高。

file transport v2 使用以下状态目录，不依赖 file lock：

```text
file transport directory:
  requests/    client-published pending requests
  claims/      worker-claimed running requests
  responses/   unread responses
  done/        archived request/claim/response history
  failed/      client_timeout / expired / stale_claim / invalid_request
  tmp/         atomic write temp files
  heartbeat/   worker liveness files
```

普通请求默认等待 300 秒，可用 `XDEBUG_FILE_TRANSPORT_TIMEOUT_MS` 调整；ping/quit 默认等待 2 秒，可用 `XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS` 调整。`XDEBUG_FILE_KEEP_HISTORY=1` 默认保留 `done/failed` 证据链。`XDEBUG_FILE_MAX_JSON_BYTES` 限制单个 request/response JSON 文件大小，`XDEBUG_FILE_CLAIM_TIMEOUT_MS` 控制 stale claim 判定。

trace XOUT 源码窗口可用 `XDEBUG_TRACE_SOURCE_CONTEXT_LINES` 控制上下文行数（默认 3），并用 `XDEBUG_TRACE_SOURCE_MERGE_THRESHOLD_LINES` 控制同文件近距离源码块合并阈值（默认 10）。

`session.open` TCP 模板：

```json
{
  "api_version": "xdebug.v1",
  "action": "session.open",
  "target": {
    "fsdb": "waves.fsdb"
  },
  "args": {
    "name": "wave_tcp",
    "transport": "tcp",
    "bind_host": "127.0.0.1",
    "port": 0
  }
}
```

显式 session 查询模板只用 `target.session_id` 选择已打开 session；不要把 session 选择写到 `args.session_id`。

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "signal": "top.clk",
    "time": "10ns",
    "clock": "top.clk"
  }
}
```

file transport 是显式例外路径；需要时先读 [xverif-admin transport](../../../xverif-admin/references/xdebug-transport.md) 并保留用户要求或项目约束上下文，不在常规 JSON API 示例里提供可复制 fallback 模板。

## 输出与 include

CLI 输出默认优先使用 xout；需要脚本读取 JSON 字段时使用命令行 `--json`。native envelope 顶层不要放输出控制对象，action args 里也不要放旧的输出格式字段。导出文件格式只放在 `args.output.file_format`。

不要猜测通用 `include_*` 或 `verbose` 参数，只使用 action-specific schema 明确声明的输出参数。AXI transaction action 用 `args.output.include_data:true` 展开逐 beat payload；其它 action 常见为 `args.output.verbose:true`。schema 未声明时按默认 compact/xout 读取核心证据或使用对应 export action。

限制字段要以 action-specific schema 为准。不要把顶层数量字段当成所有 action 的通用字段；例如 APB/AXI query 使用 `args.query.line_limit`，active-driver 链深度使用 top-level `limits.max_depth`（默认 8，不接受 `limits.max_alias_candidates`），`trace.x` 另用 `limits.max_chains`（默认 8）限制 alias 归并后返回的有效语义 chain。常见形态如下：

`line_limit` 只限制 JSON/XOUT 的返回证据，不限制分析扫描。支持显式扫描预算的
action 使用 `max_samples`；`event.export` 另用 `max_events` 限制写文件和聚合输入。
预算耗尽时必须检查 `analysis_complete`、`scan_complete` 与 `truncation_scopes`，不能把
部分结果当全量结论。`event.find` 只有 `mode:all` 接受 `line_limit`；`first/last` 返回
精确单条结果。

```json
{
  "args": {
    "line_limit": 20
  },
  "limits": {
    "max_rows": 1000,
    "max_depth": 3,
    "max_paths": 10
  }
}
```

## 设计侧示例

### trace.driver

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.driver",
  "target": {"daidir": "simv.daidir"},
  "args": {"signal": "top.u.ready"}
}
```

### source.context

```json
{
  "api_version": "xdebug.v1",
  "action": "source.context",
  "target": {"daidir": "simv.daidir"},
  "args": {
    "file": "rtl/foo.sv",
    "line": 123,
    "symbol": "ready",
    "context_lines": 3
  }
}
```

## 波形侧示例

### value.at

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {"session_id": "case_a"},
  "args": {
    "signal": "top.u.valid",
    "time": "100ns",
    "clock": "top.clk",
    "value_format": "hex"
  }
}
```

### value.batch_at

```json
{
  "api_version": "xdebug.v1",
  "action": "value.batch_at",
  "target": {"session_id": "case_a"},
  "args": {
    "time": "100ns",
    "signals": ["top.u.valid", "top.u.ready", "top.u.data"],
    "value_format": "hex"
  }
}
```

省略 `clock` 时直接读取 `100ns` 的最终值并返回 `sampling_mode:"raw_time"`；需要
clock-sampled 上下文时再传 `clock`，此时可以同时传 `edge` / `sample_point`。
`value.batch_at` 部分缺失仍返回 ok；检查 `summary.missing_by_reason` 和 full 输出每个 row 的 `status/reason`。需要 xbit 切字段时给 `value.at` 或 `value.batch_at` 加：

```text
"slice_hint": {"chunk_width": 32, "count": 4}
```

响应里的 `xbit_hints.commands[]` 可直接交给 `tools/xbit`。

### rc.generate

```json
{
  "api_version": "xdebug.v1",
  "action": "rc.generate",
  "target": {"session_id": "case_a"},
  "args": {
    "config_path": "wave_view.json",
    "output": {
      "path": "signal.rc"
    }
  }
}
```

`config_path` 指向 JSON 配置。配置中信号写点分路径，如 `top.u.sig[3:0]`；生成 rc 时转成 `/top/u/sig[3:0]`。支持普通 `addSignal`、`addSignal -w analog`、`addExprSig`、group/subgroup 和 user marker。不写 `openDirFile` / `activeDirFile`。

`addExprSig` 推荐：

```json
{
  "name": "aw_fire",
  "bit_size": 1,
  "notation": "UUU",
  "expr": "$valid & $ready",
  "signals": {
    "valid": "top.u_axi.awvalid",
    "ready": "top.u_axi.awready"
  }
}
```

### event.find inline

```json
{
  "api_version": "xdebug.v1",
  "action": "event.find",
  "target": {"session_id": "case_a"},
  "args": {
    "expr": "valid && !ready && wait_count >= 512",
    "clock": "top.clk",
    "signals": {
      "valid": "top.u.valid",
      "ready": "top.u.ready",
      "wait_count": "top.u.dbg_wait_count"
    },
    "time_range": {"begin": "0ns", "end": "100us"},
    "mode": "last"
  }
}
```

`event.find` / `event.export` 表达式支持 `!`、`&&`、`||`、`==`、`!=`、`<`、`<=`、`>`、`>=`。任一侧包含 X/Z 时，比较结果为 unknown，不会作为命中事件。

### event.export

```json
{
  "api_version": "xdebug.v1",
  "action": "event.export",
  "target": {"session_id": "case_a"},
  "args": {
    "name": "if0",
    "expr": "valid && !ready",
    "time_range": {
      "begin": "0ns",
      "end": "100us"
    }
  }
}
```

### verify.conditions

```json
{
  "api_version": "xdebug.v1",
  "action": "verify.conditions",
  "target": {"session_id": "case_a"},
  "args": {
    "time": "100ns",
    "clock": "top.clk",
    "signals": {
      "valid": "top.u.valid",
      "ready": "top.u.ready"
    },
    "conditions": [
      {"expr": "valid == 1"},
      {"expr": "ready == 0"}
    ]
  }
}
```

## 联合侧示例

### trace.active_driver

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.active_driver",
  "target": {
    "daidir": "simv.daidir",
    "fsdb": "waves.fsdb"
  },
  "args": {
    "signal": "top.u.ready",
    "time": "120ns"
  }
}
```

## 错误处理

脚本必须先检查 `ok`：

```bash
tools/xdebug --json - < request.json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ok"], d.get("error"))'
```

常见错误码：

```text
MISSING_FIELD
UNKNOWN_ACTION
INVALID_TARGET
SESSION_NOT_FOUND
SIGNAL_NOT_FOUND
INVALID_TIME
TIME_RANGE_INVALID
WAVE_QUERY_FAILED
INTERNAL_ENGINE_FAILED
INTERNAL_ERROR
```

参数错误示例：

```json-invalid
{
  "api_version": "xdebug.v1",
  "action": "apb.query",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "name": "apb0",
    "direction": "read",
    "line_limit": 10
  }
}
```

该请求会返回 `invalid_arg`、`did_you_mean:"args.query.line_limit"` 和 `correct_example`。修正后应写成：

```json
{
  "api_version": "xdebug.v1",
  "action": "apb.query",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "name": "apb0",
    "direction": "read",
    "query": {
      "line_limit": 10
    }
  }
}
```

已完成协议事务计数使用独立 action，不把统计塞进 query：

```json
{
  "api_version": "xdebug.v1",
  "action": "apb.statistics",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "name": "apb0",
    "filter": {
      "direction": "write",
      "address": {
        "mode": "exact",
        "values": ["0x0", "0x4"]
      }
    }
  }
}
```

AXI 的 `filter.ids` 为非空队列，队列内部取 OR；direction、IDs、address 三类条件取
AND。address 的 exact/range/mask 只能出现一种。返回中的
`data.notes.unresolved_transaction_count` 与 XOUT `notes` block 固定解释 unresolved 计数。
