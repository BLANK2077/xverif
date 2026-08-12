# SDK-free xdebug/xcov 排障

## 日志位置

默认根目录：`~/.xverif/loop-wrapper`，可用 `XVERIF_LOOP_LOG_DIR` 覆盖。

- UDS protocol：`logs/uds.ndjson`
- server：`logs/server.ndjson`
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

- `UNKNOWN_METHOD`：method 不在 SDK-free wrapper 第一版支持范围。
- `INVALID_PARAMS`：open 缺少 `name/fsdb/vdb`，或 query/lifecycle 缺少 canonical `session_id`/`action`。
- `SESSION_LOST`：stdio-loop backend 超时、退出或 backend 报告 session terminal；需要重新 open。
- ready timeout：检查 LSF 队列、backend 是否能启动、`XVERIF_LOOP_STARTUP_TIMEOUT_SEC`。
- query timeout：先缩小 time_range/limits，再考虑增大 `XVERIF_LOOP_REQUEST_TIMEOUT_SEC`。
- UDS bind 失败：检查 socket path 目录权限和旧 socket 文件。
- server 启动后立即 `ECONNREFUSED`：socket 文件存在只说明 `bind()` 已完成，不代表已经 `listen()`；测试或编排必须等待明确 ready，不使用固定 sleep 或静默重试。
