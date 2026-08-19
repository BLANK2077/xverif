# xdebug 通信协议

xdebug 有多层通信协议：用户到 frontend 的 JSON request、frontend 的 stdio-loop、frontend 到 engine 的 transport、MCP/SDK-free wrapper 到 xdebug 的托管协议。修改协议时必须明确影响层级。

## JSON Request Envelope

基本形状：

```json
{
  "api_version": "xdebug.v1",
  "request_id": "optional",
  "action": "value.at",
  "target": {
    "session_id": "case_a"
  },
  "args": {},
  "limits": {},
  "output": {}
}
```

规则：

- `api_version` 当前为 `xdebug.v1`。
- `action` 决定 action-specific schema。
- `target` 选择 daidir、fsdb 或 session。
- `args` 放 action 参数。
- `limits` 放通用资源限制。
- `output` 控制 JSON/XOUT、verbosity、pretty 等输出。

禁止：

- 把 session 选择写成 `args.session_id` 作为公开合同。
- 在 docs 中提供 schema 不接受的字段。
- 把 action 参数放到多个同义位置。

## CLI 单请求协议

frontend CLI 接受单个 JSON request，输出 JSON 或 XOUT。

要求：

- 机器可读输出只能出现在 stdout。
- log、debug、daemon lifecycle 信息写入 log 或 stderr。
- JSON parse 失败先返回 `INVALID_JSON` 相关错误，不猜测波形或设计问题。
- MCP xdebug 不暴露原生 envelope raw request；需要完整 `xdebug.v1` envelope 时使用原生 CLI，或在无 MCP 且必须经 LSF 时使用 `xdebug_lsf`。

## Stdio-loop 协议

路径：

- `src/api/stdio_loop.*`
- `xdebug/tests/session/test_stdio_loop_lifecycle.py`

用途：

- 长生命周期进程复用。
- MCP 与 SDK-free LSF CLI 的内部 manager 可通过 stdio-loop 发送多条请求。

要求：

- 每条 request/response 必须保持边界清晰。
- session lost、child exited、transport failed 后 wrapper 不能继续复用旧 session。
- stdout/stderr 必须隔离，避免破坏 protocol framing。

## Frontend 到 Engine 协议

路径：

- `src/backend/engine_adapter.*`
- `src/engine/server.*`
- `src/engine/engine_query.*`
- `src/engine/session/client.*`
- `src/engine/session/session_transport.*`

流程：

1. frontend 根据 target/action 判定需要 engine。
2. engine adapter 打开或复用 backend session。
3. transport 层等待 engine ready。
4. frontend 发送 action query。
5. engine service dispatch handler。
6. response 返回 frontend，再渲染给用户。

要求：

- ready、ping、query、quit 都要有 timeout 和日志。
- 子进程 crash 必须写 lifecycle log。
- transport 失败必须保留 endpoint、phase、errno/exception。

## UDS/TCP/File Transport

默认 transport 是 UDS。

- UDS：本机同用户优先，低开销。
- TCP：跨 namespace/container 或显式远程可达时使用。
- file transport：显式例外路径，依赖共享 session 目录，不作为环境失败的静默 fallback。

file transport 状态目录：

- `requests/`：client 发布的 pending request。
- `claims/`：worker claim 后的运行中 request。
- `responses/`：未读 response。
- `done/`：已完成历史。
- `failed/`：client_timeout、expired、stale_claim、invalid_request 等失败。
- `tmp/`：atomic write 临时文件。
- `heartbeat/`：worker liveness。

要求：

- agent 不直接写这些目录。
- 用户未明确要求时，不从 UDS/TCP 自动切到 file transport。

## MCP 边界

路径：

- `xverif_mcp/src/`
- `xverif_mcp/tests/`
- `xdebug/mcp/`

MCP 是 xdebug 的外层工具暴露，不是替代 xdebug 原生 schema 的 source of truth。

规则：

- MCP debug session open 后，query 使用 `session_id`。
- MCP adapter 参数必须映射到原生 xdebug public contract。
- MCP tests 覆盖 direct、stdio-loop、fake LSF、real LSF 等层级。

## SDK-free Wrapper 边界

SDK-free wrapper 只面向没有 MCP 且必须经 LSF 的场景。公开入口为
`xdebug_lsf` / `xcov_lsf`，请求 envelope 与对应原生 CLI 完全相同；内部 manager、
UDS 和 stdio-loop 不作为用户入口。

规则：

- wrapper 不重新定义 action schema。
- wrapper 不公开 `method/params`、server/client、socket 参数或 `--stdio-loop`。
- wrapper 不手写 xdebug file transport 内部目录协议。
- wrapper failure 必须保留底层 xdebug error context。
- 入口同目录的 `xverif_lsf.env.json` 及其 `bsub -env all`、远端环境指纹、
  manager 配置指纹只属于 SDK-free wrapper。MCP direct/LSF 不读取配置，不改变
  bsub argv 或 ready envelope 要求。
