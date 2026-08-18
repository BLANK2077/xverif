# MCP 排障

## 日志位置

默认根目录：`~/.xverif/mcp`，可用 `XVERIF_MCP_LOG_DIR` 覆盖。

- server：`logs/server.ndjson`
- session：`sessions/<session_id>/session.ndjson`
- stdio-loop：`sessions/<session_id>/stdio.ndjson`
- LSF：`sessions/<session_id>/lsf.ndjson`

## 定位顺序

1. 工具不可见：调用 `xverif_tools`，先检查工具组开关；生命周期工具再检查 `XVERIF_MCP_ENABLE_MUTATION`（默认开启，可能被显式 `0` 关闭），batch 再检查 `XVERIF_MCP_ENABLE_ARTIFACT_WRITE`。
2. FastMCP/SDK 启动失败：确认 Python 3.11+ 和 `mcp[cli]`。
3. session open 失败：看 `session.ndjson` 和 `stdio.ndjson`。
4. ready timeout/stdout pollution/backend exit：看 `stdio.ndjson`。
5. LSF job id、bsub、bkill、cleanup：看 `lsf.ndjson`。
6. xdebug backend native 问题：继续读 xdebug troubleshooting。

## 常见错误

- `SESSION_LOST`：MCP 已清理失效 session；重新 open。
- `SESSION_STALE`：同名 session 记录存在但进程不健康；显式 close/gc 后重开。
- `TOOL_NOT_ENABLED`：对应工具组被 env policy 关闭。
- `MCP_MUTATION_DISABLED`：请求会改变 session/backend 状态，但 mutation 被显式关闭（默认开启）；如需启用改回 `XVERIF_MCP_ENABLE_MUTATION=1` 后重启 server。
- `MCP_ARTIFACT_WRITE_DISABLED`：artifact write 未开启、未配置 root，或路径逃逸 `XVERIF_MCP_ARTIFACT_ROOT`；修正最小授权或输出路径，不改用目录外路径。
- `BAD_JSON` 或 envelope 异常：检查 MCP tool 参数壳和 `output_format`；xdebug 原生 envelope 请改用 `xverif`。
