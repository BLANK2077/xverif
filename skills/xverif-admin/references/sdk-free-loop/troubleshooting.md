# SDK-free xdebug/xcov 排障

## 日志位置

默认根目录：`~/.xverif/lsf-cli`，可用 `XVERIF_LSF_CLI_LOG_DIR` 覆盖。

- UDS protocol：`logs/uds.ndjson`
- manager：`logs/server.ndjson`
- session lifecycle：`sessions/<session_id>/owners/*/session.ndjson`
- stdio-loop：`sessions/<session_id>/stdio.ndjson`
- LSF：`sessions/<session_id>/lsf.ndjson`

## 定位顺序

1. 请求 JSON 无响应或 invalid JSON：看 `logs/uds.ndjson`。
2. session open/query/close 错误：看 `sessions/<session_id>/session.ndjson`。
3. ready timeout、stdout pollution、backend exit：看 `stdio.ndjson`。
4. LSF bsub/job id/bkill/cleanup：看 `lsf.ndjson`。
5. 后端 native xdebug session/socket/engine 问题，再读 [xdebug capability](../../../xverif/references/capabilities/xdebug.md)；coverage 数据库问题读 [xcov capability](../../../xverif/references/xcov.md)。

## 常见错误

- `INVALID_REQUEST` / `INVALID_ARG`：原生 envelope、target 或 action 参数不符合 xdebug/xcov 合同。
- `SESSION_LOST`：stdio-loop backend 超时、退出或 backend 报告 session terminal；需要重新 open。
- job 在运行一段固定时长后消失，且 `scheduler.submitted.wall_time_minutes` 与存活时长接近：
  LSF `-W` runtime limit（`XVERIF_LSF_SESSION_WALL_TIME_SEC`，默认 7200 秒）到期，
  LSF 终止了 job；按需调大该值。残留记录用 session 层回收：native
  `session.close mode=force retire_unreachable=true`（引擎不可达时退役记录，响应
  `summary.retired_unreachable=true`，随后同名可重开）；`session.gc` 会对已判 unhealthy 的记录走
  同一条退役路径。同名 open 的冲突探测有界（内部 `limits.timeout_ms`，默认 2000ms），
  不再等 file transport 的 300s 请求超时。
- ready timeout：检查 LSF 队列、backend 是否能启动、`XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC`。
- query timeout：先缩小 time_range/limits，再考虑增大 `XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC`。
- manager 收到 SIGTERM/SIGINT：会在有界预算内（`close_timeout + bkill_timeout`，默认 60 秒，
  上限 300 秒）执行 `close_all` 再退出，日志为 `uds.shutdown.cleanup_begin/end`；被 SIGKILL
  时该清理不会执行，只能依赖 LSF `-W` 兜底。
- UDS bind 失败：检查 `XVERIF_LSF_CLI_SOCKET` 所在目录权限及同名路径类型；不要手工启动 manager 或 client。
- `--stdio-loop` 被拒绝：这是预期行为；该参数只由 wrapper 内部提交到计算节点。
- `CONFIG_ERROR`：检查 `xverif_lsf.env.json` 的 JSON、owner、普通文件类型和
  `0600` 权限；不要改成 symlink 或放宽权限。
- `LSF_ENV_MISMATCH`：登录节点 effective environment 未完整到达计算节点；
  检查站点 bsub wrapper 是否保留 `-env all`，不要改用 direct/MCP fallback。
- `CONFIG_MISMATCH`：旧 manager 仍有活动或未解决 session；先按原配置完成
  close/doctor/cleanup，再使用新配置。
