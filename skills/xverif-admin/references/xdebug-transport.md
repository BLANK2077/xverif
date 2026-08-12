# xdebug transport 参考

本文聚焦 xdebug 原生 file transport。file transport 是显式例外路径：只有用户明确要求，或项目文档明确要求在共享 home/session 目录上跨边界通信时，才使用 xdebug 原生 `transport:"file"`。它不是额外 wrapper，不需要 agent 手工读写文件。

## 使用时机

使用 file transport：

- 用户明确要求使用 file transport，或项目文档明确要求该路径。
- LSF / batch 计算节点上的 daemon 不能被登录机 TCP 直连。
- UDS socket 不能跨节点或跨 namespace 使用。
- 用户明确说明共享文件系统可见。

不要使用 file transport：

- 同机本地普通调试；默认 UDS 即可。
- 远程 TCP 明确可达且用户授权使用 TCP。
- 想手工构造 request/response 文件；agent 必须走 xdebug JSON API。
- 仅因为 `SESSION_UNHEALTHY child_exited`、旧 session 冲突或 UDS bind 问题想做 fallback；应先关闭旧 session、换新名字重开或保留错误上下文。

## 打开 session

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

也可以设置新建 session 默认 transport：

```bash
export XDEBUG_TRANSPORT=file
```

JSON 中显式的 `session.open.args.transport` 优先级高于环境变量；
`target.transport` 不属于公开合同，会被严格 schema 拒绝。

## 状态目录

file transport v2 使用 backend session 的 `transport/` 目录：

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

协议要点：

- client 先写 `tmp/`，再 atomic publish 到 `requests/`。
- worker 用 `rename()` 抢占 request 到 `claims/`。
- worker claim 后先检查 deadline；过期 request 不执行 action。
- response 写到 `responses/`。
- client 读完后默认把 response 归档到 `done/`。
- expired、stale claim、invalid request、client timeout 进入 `failed/`。
- 旧 session 里若还有 `locks/`，按历史残留处理，不作为当前协议依赖。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `XDEBUG_FILE_TRANSPORT_TIMEOUT_MS` | `300000` | 普通 file request 等待时间 |
| `XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS` | `2000` | ping/quit 等短请求等待时间 |
| `XDEBUG_FILE_KEEP_HISTORY` | `1` | `1` 保留 `done/failed` 证据；`0` 丢弃成功 response 归档 |
| `XDEBUG_FILE_CLAIM_TIMEOUT_MS` | `max(2*request_timeout,600000)` | stale claim 判定时间 |
| `XDEBUG_FILE_POLL_INTERVAL_MS` | `20` | client/worker 轮询间隔 |
| `XDEBUG_FILE_MAX_JSON_BYTES` | `67108864` | 单个 JSON request/response 文件大小上限 |
| `XDEBUG_FILE_DONE_TTL_SEC` | `604800` | `done/` 历史清理 TTL；`0` 禁用 |
| `XDEBUG_FILE_FAILED_TTL_SEC` | `2592000` | `failed/` 历史清理 TTL；`0` 禁用 |

调大长窗口 action 的等待时间时，优先调整 `XDEBUG_FILE_TRANSPORT_TIMEOUT_MS`，不要随意放大 ping timeout。

## 排障流程

1. 先跑 `session.doctor`。
2. 看 public action log：`~/.xdebug/sessions/<session_id>/owners/*/logs/actions.ndjson`。
3. 看 stdio-loop log：`~/.xdebug/sessions/<session_id>/owners/*/logs/stdio.ndjson`。
4. 看 engine lifecycle：`~/.xdebug/engine/sessions/<hashed-session>/owners/*/logs/lifecycle.ndjson`。
5. 看 transport log：`~/.xdebug/engine/sessions/<hashed-session>/owners/*/logs/transport.ndjson`。
6. 可用 `xdebug log doctor --session <id> --json` 找实际 hashed 路径。
7. 对 file transport，检查 `done/` 和 `failed/`，确认 request 是 `client_timeout`、`expired`、`stale_claim` 还是 `invalid_request`。

不要手工修改 `requests/`、`claims/`、`responses/`。如果需要清理，优先用 `session.gc` 或关闭/重开 session。
