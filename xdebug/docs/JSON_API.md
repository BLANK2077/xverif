# xdebug JSON Request API

xdebug 是原 xtrace 与 xwave 的统一 JSON request 入口。agent 和自动化脚本应通过 JSON 请求访问工具能力，不再依赖传统人类 CLI 动作入口。默认输出为 `xout` 结构化文本；需要完整 JSON response 时使用 `--json` 或 `output.format:"json"`。

## 请求 Envelope

```json
{
  "api_version": "xdebug.v1",
  "request_id": "optional-id",
  "action": "trace.driver",
  "target": {
    "daidir": "path/to/simv.daidir",
    "fsdb": "path/to/waves.fsdb"
  },
  "args": {},
  "limits": {},
  "output": {
    "verbosity": "compact",
    "pretty": false
  }
}
```

## Action-specific Schema

`xdebug.v1` 的机器契约以 action-specific schema 为准。所有未移除的公开 action 都有独立 schema 和示例：

```text
schemas/v1/actions/<action>.request.schema.json
schemas/v1/actions/<action>.response.schema.json
examples/requests/<action>.basic.json
examples/responses/<action>.basic.json
```

不要把 `schemas/v1/xdebug.request.schema.json` 或 `schemas/v1/xdebug.response.schema.json` 当作具体 action 的主契约；它们只描述通用 envelope。`actions` 返回的 `request_schema`、`response_schema`、`request_examples`、`response_examples` 是 agent 和脚本查找具体契约的入口。

`schema` action 支持直接按 action 查询具体契约：

```json
{"api_version":"xdebug.v1","action":"schema","args":{"action":"signal.statistics","kind":"request"}}
```

若缺少对应 action-specific schema，会返回 `ACTION_SCHEMA_NOT_FOUND`，不会用 generic envelope 冒充成功。

`target` 决定路由：

| target | 行为 |
| --- | --- |
| 仅 `daidir` | 使用设计数据库能力，即原 xtrace 能力 |
| 仅 `fsdb` | 使用波形数据库能力，即原 xwave 能力 |
| 同时有 `daidir` 与 `fsdb` | 使用 combined/debug join 能力 |
| `session_id` | 使用已打开 session 的资源集合 |

## Session transport

session 默认使用 `uds`。本机同用户调试不需要显式设置 transport；当 UDS socket 因容器、namespace、挂载隔离或路径不可达而无法连接时，可以用 TCP。本机或登录机无法连接计算节点 TCP 端口时，用 `file` transport 通过共享 session 目录交换 request/response。

| 字段 | 位置 | 说明 |
| --- | --- | --- |
| `transport` | `args` 或 `target` | `uds`、`tcp` 或 `file`；默认 `uds`，可由 `XDEBUG_TRANSPORT` 控制 |
| `bind_host` / `bind` | `args` 或 `target` | daemon listen 地址；本机 TCP 推荐 `127.0.0.1` |
| `host` | `args` 或 `target` | client 连接 endpoint 时使用的地址；跨容器/远程时应是 agent 可达地址 |
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

`session.open` 使用 TCP：

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

后续查询必须显式使用已打开 session：

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {
    "session_id": "wave_tcp"
  },
  "args": {
    "signal": "top.clk",
    "time": "10ns"
  }
}
```

`session.open` 使用 file transport：

```json
{
  "api_version": "xdebug.v1",
  "action": "session.open",
  "target": {
    "fsdb": "waves.fsdb"
  },
  "args": {
    "name": "wave_file",
    "transport": "file"
  }
}
```

不要默认把 daemon 绑定到公网地址。若必须远程访问，显式设置 `bind_host` 和 `host`，并用 `session.doctor` 与 `transport.ndjson` 检查 endpoint、connect、ping 和 timeout。

常见波形意图选择：

| 意图 | 推荐 action |
| --- | --- |
| active/high cycles | `signal.statistics` |
| counter min/max/average | `counter.statistics` |
| 跳变时间线 | `signal.changes` |
| 窗口保持 0/1 | `window.verify` 或 `signal.statistics` |
| first/last occurrence | `event.find` 或 `signal.changes` 的 head/tail |
| 临时事件表达式 | `event.find` with `expr` + `clock` + `signals`；默认 `edge:"negedge"`，posedge/dual 场景可用 `sample_point:"before"`，支持布尔组合、相等比较和大小比较 |
| packed value 切字段 | `value.at`/`value.batch_at` with `slice_hint`，再调用 `tools/xbit` |

## 输出档位

| verbosity | 行为 |
| --- | --- |
| `compact` | 默认，只保留 AI 决策所需事实 |
| `full` | 保留可用的详细旧 payload |
| `debug` | 保留 full 内容，并允许过程型调试字段 |

正常调试应先用 compact。只有 compact 结果缺少下一步所需证据时，再打开具体 `include_*`，不要一开始就请求 `debug`。

## Include 开关

设计侧开关：

```json
{
  "include_source": true,
  "include_ast": true,
  "include_candidates": true,
  "include_trace": true,
  "include_expanded_queries": true,
  "include_raw_edges": true,
  "include_graph": true,
  "include_debug": true
}
```

波形侧开关：

```json
{
  "include_raw": true,
  "include_signal_meta": true,
  "include_rows": true,
  "include_samples": true,
  "include_all_changes": true,
  "include_transactions": true,
  "include_beats": true,
  "include_accesses": true,
  "include_debug": true
}
```

通用限制：

```json
{
  "args": {
    "max_items": 20,
    "max_examples": 5
  },
  "limits": {
    "max_rows": 1000,
    "max_events": 1000
  }
}
```

## 示例

### 查询 driver

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.driver",
  "target": {"daidir": "simv.daidir"},
  "args": {"signal": "top.u.ready"}
}
```

### 查询波形值

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {"fsdb": "waves.fsdb"},
  "args": {
    "signal": "top.u.valid",
    "time": "100ns",
    "format": "hex"
  }
}
```

传 `format:"array_indexed"` 可把 FSDB 聚合数组值转成 `elements/by_index`。传 `slice_hint` 会返回 `xbit_hints.commands[]`，用于后续确定性 bit slice。

### 生成 signal.rc

```json
{
  "api_version": "xdebug.v1",
  "action": "rc.generate",
  "target": {"fsdb": "waves.fsdb"},
  "args": {
    "config_path": "wave_view.json",
    "rc_path": "signal.rc",
    "include_preview": true
  }
}
```

`config_path` 是 JSON 配置，不是 YAML。配置里的信号用点分路径，例如 `top.u.sig[3:0]`；生成 rc 时会转换成 `/top/u/sig[3:0]`。支持 `addSignal`、`addSignal -w analog`、`addExprSig`、`addGroup/addSubGroup` 和 `userMarker`。group 配置不接受 `expanded`，生成的 `addGroup` / `addSubGroup` 不带 `-e`。该 action 不写 `openDirFile` / `activeDirFile`。
slice 信号会先校验完整路径；若 FSDB signal lookup 不接受 slice，则回退校验 base signal。

`addExprSig` 推荐使用 `$alias`：

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

校验失败默认不写 rc；`allow_invalid:true` 才会带 warning 生成。

### 查找 inline event

```json
{
  "api_version": "xdebug.v1",
  "action": "event.find",
  "target": {"fsdb": "waves.fsdb"},
  "args": {
    "expr": "valid && !ready && wait_count >= 512",
    "clock": "top.clk",
    "edge": "negedge",
    "signals": {
      "valid": "top.u.valid",
      "ready": "top.u.ready",
      "wait_count": "top.u.dbg_wait_count"
    },
    "begin": "0ns",
    "end": "max",
    "mode": "last"
  }
}
```

### 导出 event rows

```json
{
  "api_version": "xdebug.v1",
  "action": "event.export",
  "target": {"fsdb": "waves.fsdb"},
  "args": {
    "name": "valid_rise",
    "expr": "valid",
    "begin": "0ns",
    "end": "max",
    "include_rows": true
  },
  "limits": {"max_rows": 1000}
}
```
```

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
    "requested_time": "120ns"
  }
}
```

## 错误与证据字段

常见错误码：

- `MISSING_FIELD`
- `UNKNOWN_ACTION`
- `INVALID_TARGET`
- `SESSION_NOT_FOUND`
- `SIGNAL_NOT_FOUND`
- `TIME_SPEC_INVALID`
- `WAVE_QUERY_FAILED`
- `INTERNAL_ERROR`

compact payload 优先返回 evidence，而不是大段源码文本：

```json
{
  "evidence": {
    "file": "rtl/foo.sv",
    "line": 123
  }
}
```

`meta.truncated=true` 表示结果被主动截断。需要更多明细时，使用精确 include 开关并设置限制。
