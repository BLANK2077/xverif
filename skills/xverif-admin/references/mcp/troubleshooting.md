# MCP 排障

## 日志位置

默认根目录：`~/.xverif/mcp`，可用 `XVERIF_MCP_LOG_DIR` 覆盖。

- server：`logs/server.ndjson`
- session：`sessions/<session_id>/session.ndjson`
- stdio-loop：`sessions/<session_id>/stdio.ndjson`
- LSF：`sessions/<session_id>/lsf.ndjson`

## 定位顺序

1. 工具不可见：确认连接的是当前版本 MCP server 并刷新客户端工具列表；全部工具组始终注册。工具详情用 `xverif_tool_help`，xdebug action 发现用 `xverif_tools`。
2. FastMCP/SDK 启动失败：确认 Python 3.11+ 和 `mcp[cli]`。
3. session open 失败：看 `session.ndjson` 和 `stdio.ndjson`。
4. ready timeout/stdout pollution/backend exit：看 `stdio.ndjson`。
5. LSF job id、bsub、bkill、cleanup：看 `lsf.ndjson`。
6. xdebug backend native 问题：继续读 xdebug troubleshooting。

## 常见错误

- `SESSION_LOST`：MCP 已清理失效 session；重新 open。
- `SESSION_STALE`：同名 session 记录存在但进程不健康；显式 close/gc 后重开。
- `OUTPUT_WRITE_FAILED`：检查 MCP 进程工作目录、输出父目录是否存在以及写权限。
- `OUTPUT_SERIALIZATION_FAILED`：响应不能编码为严格 JSON；写入失败不能当作调用成功。
- `BAD_JSON` 或 envelope 异常：检查 MCP tool 参数壳和 `output_format`；xdebug 原生 envelope 请改用 `xverif`。
