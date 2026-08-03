# SDK-free xdebug/xcov loop wrapper 总览

SDK-free loop wrapper 是非 MCP 的 Python UDS JSONL server/client，用于维护长期 `tools/xdebug --stdio-loop` 或 `tools/xcov --stdio-loop` session。它不需要 MCP SDK，适合脚本、批处理、或必须 LSF 但无法使用 MCP 的场景。

入口：

```bash
tools/xverif-loop-server
tools/xverif-loop-client
```

## 何时优先使用

- 必须使用 LSF，但不能安装或不能使用 MCP SDK。
- 需要 shell/python 脚本直接驱动 xdebug 或 xcov session。
- 需要非交互批处理保持一个长期 `--stdio-loop` backend。
- 不希望把 MCP 当脚本 API。

如果已有 MCP client 且 SDK 可用，交互式 AI 调用仍优先 MCP。只做一次性完整 JSON request 时，用 `xverif` 中的 raw xdebug/xcov CLI 即可。

## 能力边界

SDK-free wrapper 覆盖与 MCP SDK 对称的 stateful xdebug/xcov session：

- `debug.session.open`
- `debug.session.list`
- `debug.session.doctor`
- `debug.session.close`
- `debug.session.kill`
- `debug.session.gc`
- `debug.query`
- `cov.session.open/list/doctor/close/kill/gc/query`

它不覆盖 xbit/xentry/xloc/xsva，也不等价于完整 MCP 工具集。

## 与 raw CLI 的区别

raw CLI：

```text
tools/xdebug --json -   # 每次一个短进程
tools/xcov --json -     # 每次一个短进程
```

SDK-free wrapper：

```text
client -> UDS socket -> xverif-loop-server -> tools/xdebug --stdio-loop
client -> UDS socket -> xverif-loop-server -> tools/xcov --stdio-loop
```

wrapper 负责 canonical `session_id`、session manager、tombstone、stdio-loop 进程和 LSF job cleanup。open 的 backend `session_id` 必须与请求 `name` 完全一致；query/doctor/close/kill 都只接受精确 `session_id`，旧 `session`/`name` 字段严格拒绝。query 禁止 native lifecycle action；doctor 只读，partial cleanup 保留诊断证据且不切换 transport/backend。
