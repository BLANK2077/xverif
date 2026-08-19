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
