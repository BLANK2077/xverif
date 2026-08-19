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
- ready timeout：检查 LSF 队列、backend 是否能启动、`XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC`。
- query timeout：先缩小 time_range/limits，再考虑增大 `XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC`。
- UDS bind 失败：检查 `XVERIF_LSF_CLI_SOCKET` 所在目录权限及同名路径类型；不要手工启动 manager 或 client。
- `--stdio-loop` 被拒绝：这是预期行为；该参数只由 wrapper 内部提交到计算节点。
- `CONFIG_ERROR`：检查 `xverif_lsf.env.json` 的 JSON、owner、普通文件类型和
  `0600` 权限；不要改成 symlink 或放宽权限。
- `LSF_ENV_MISMATCH`：登录节点 effective environment 未完整到达计算节点；
  检查站点 bsub wrapper 是否保留 `-env all`，不要改用 direct/MCP fallback。
- `CONFIG_MISMATCH`：旧 manager 仍有活动或未解决 session；先按原配置完成
  close/doctor/cleanup，再使用新配置。
