# MCP stateful sessions

MCP 的 xdebug/xcov stateful session 通过同一套 stdio-loop session manager 实现。

## xdebug

- `xverif_debug_session_open(name, fsdb=None, daidir=None, run_manifest=None, queue=None, resource=None)`
- `xverif_debug_query(session_id, action, args=None, limits=None, output_format="xout")`
- `xverif_debug_session_list(include_tombstones=False, verbose=False)`
- `xverif_debug_session_doctor(name=..., session_id=..., verbose=False)`
- `xverif_debug_session_close(name=..., session_id=...)`
- `xverif_debug_session_kill(name=..., session_id=...)`
- `xverif_debug_session_gc(verbose=False)`

## xcov

- `xverif_cov_session_open(name, vdb, run_manifest=None, queue=None, resource=None)`
- `xverif_cov_query(session_id, action, args=None, limits=None, output=None, output_format="xout")`
- `xverif_cov_session_list(include_tombstones=False, verbose=False)`
- `xverif_cov_session_doctor(session_id=..., verbose=False)`
- `xverif_cov_session_close(session_id=...)`
- `xverif_cov_session_kill(session_id=...)`
- `xverif_cov_session_gc(verbose=False)`

## 规则

- xdebug open 后保存 alias 或 backend `session_id`，query 时传 `session_id`。
- xcov open 后保存 alias 或 backend `session_id`，当前 query 参数名仍是 `session`。
- 同 session 请求串行；多 session 可并行。
- `output_format="json"` 用于脚本字段读取，`envelope` 用于定位 wrapper/stdio-loop。
- `xverif_cov_query(output_format="xout")` 返回给 MCP client 的文本直接从
  `@xcov.v1` 开始；native xcov stdio stream 的 `XOUT_BEGIN/XOUT_END` 只用于后端
  流式分帧，不进入单次 MCP tool result。
- single-session doctor/close/kill 必须传精确 name 或 session_id；kill 不支持 `all`。
- list 默认只列 active，`include_tombstones=true` 查看终止/未解决记录；`verbose=true` 才展开 PID、LSF job、完整资源路径和 cleanup 证据。
- doctor 只读，不会自动 reconnect/restart/reopen。
- xdebug detached engine 可能在 loop 死后存活，只使用固定 native admin path doctor/kill；无法确认清理时保留 `orphan_suspected` tombstone。
- xcov backend 随 loop 进程退出；xcov kill 终止 loop/process/LSF job，并明确标记 native kill 不支持。
- close/kill 分层返回 native backend、stdio loop、process、LSF job、manager record、tombstone 状态；部分失败为 `SESSION_CLEANUP_PARTIAL_FAILURE`，不得同名隐式 reopen。
- debug/cov query 都禁止 native lifecycle action；使用专用 tool，不做 transport/backend fallback。
- 两类 session-open 的 `run_manifest` 均为可选路径。提供时会在启动后端前校验
  `state:"published"`、相对资源路径、`size_bytes` 与 SHA-256；xdebug 使用
  `xdebug.run-manifest.v1`（`fsdb`/`daidir`），xcov 使用 `xcov.run-manifest.v1`（`vdb`）。
- xdebug 的 JSON 响应 `tool` 元数据包含 `build_id`、`git_revision` 和
  `schema_revision`；会话列表中的 `resource_identity.manifest_sha256` 只是 wrapper
  对已提供 manifest 的摘要，实际 provenance 校验仍由 native session.open 完成。
