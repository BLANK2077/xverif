# CLI Surface

- xdebug 使用 `tools/xdebug --json -` 和完整 `xdebug.v1` envelope。
- xcov 使用 `tools/xcov --json -` 和完整 `xcov.v1` envelope。
- session 选择位于原生 `target.session_id`；不要使用 MCP query 的顶层 `session_id` 参数壳。
- AI、MCP 和交互查询默认使用 token-efficient XOUT；稳定字段编程、schema 校验、
  结构化持久化、读取未投影嵌套字段或用户明确要求时使用 JSON。
- XOUT 是 action-specific 领域文本，不是 JSON 的可逆编码；不解析其缩进或表格，
  不添加 `XOUT_BEGIN/XOUT_END`。
- 精确 target、args、limits 和 output 字段查询 action-specific schema。
- 进入具体 xdebug action 前可用同一 native envelope 获取完整精简 guide：
  `{"api_version":"xdebug.v1","action":"actions","args":{"output":{"view":"guide"}}}`。
  guide 不含 status/`use_when`，完整文本受 10,000 UTF-8 字节硬门禁约束。
- engine analysis cache 的 soft/hard 预算分别由
  `XDEBUG_ANALYSIS_CACHE_MAX_BYTES`（默认 1 GiB，`0` 关闭主动 soft LRU）和
  `XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES`（默认 2 GiB，必须为正且不小于 soft）设置。
  两者只在 engine 启动时严格解析一次；非法值会使 session 启动失败，不会使用默认值兜底。
