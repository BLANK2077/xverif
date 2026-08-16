# MCP stateful sessions

MCP 的 xdebug/xcov stateful session 通过同一套 stdio-loop session manager 实现。

## xdebug

- `xverif_debug_session_open(name, fsdb=None, daidir=None, run_manifest=None, queue=None, resource=None)`
- `xverif_debug_query(session_id, action, args=None, limits=None, output_format="xout")`
- `xverif_debug_session_list(include_tombstones=False, verbose=False)`
- `xverif_debug_session_doctor(session_id, verbose=False)`
- `xverif_debug_session_close(session_id)`
- `xverif_debug_session_close(session_id, mode="force")`
- `xverif_debug_session_gc(verbose=False)`

## xcov

- `xverif_cov_session_open(name, vdb, run_manifest=None, queue=None, resource=None)`
- `xverif_cov_query(session_id, action, args=None, output_format="xout")`
- `xverif_cov_session_list(include_tombstones=False, verbose=False)`
- `xverif_cov_session_doctor(session_id=..., verbose=False)`
- `xverif_cov_session_close(session_id=..., confirm_discard_reasons=False)`
- `xverif_cov_session_kill(session_id=...)`
- `xverif_cov_session_gc(verbose=False)`

## 规则

- xdebug/xcov open 的 `name` 是请求的 canonical `session_id`；backend 必须返回同一值，否则 open 失败并清理 backend。
- open 后只保存返回 record 的 `session_id`；query 参数名固定为 `session_id`，不接受 `session`/`name`。
- 同 session 请求串行；多 session 可并行。
- 每个 managed session 启动一个独立 stdio-loop 进程；xcov native loop 最多一个 live
  VDB session，多 VDB 并行依靠多个 manager-owned process/job。
- 默认 `output_format="xout"` 以减少 AI 上下文 token；稳定字段编程时使用
  `json`，`envelope` 用于定位 wrapper/stdio-loop。
- `xverif_cov_query(output_format="xout")` 原样返回 native 紧凑领域文本；首行使用
  `@xcov.v1 ... action=<action> ...`，不包含 `XOUT_BEGIN/XOUT_END`。stdio-loop
  外层 JSON envelope/sideband 单独负责机器 framing。
- single-session doctor/close/kill 只接受精确 `session_id`；`session`/`name` 都不是兼容字段，
  kill 不支持 `all`。
- list 默认只列 active，`include_tombstones=true` 查看终止/未解决记录。compact record 已
  包含 `scheduler.requested/effective/submitted/status`；`verbose=true` 再展开 PID、兼容
  LSF job 字段、完整资源路径和 cleanup 证据。
- doctor 只读，不会自动 reconnect/restart/reopen。
- 同一 managed session 的 query 由 request lane 串行，但 recovery lifecycle 不与阻塞 query 共用该锁。`kill` 会原子摘除 loop handle、终止进程，再按 backend 能力通过独立 fixed native admin path 做精确条件清理；已在途 query 的迟到异常不会把最终状态改回 dead。
- 普通 close 遇到 request lane 正忙时立即返回可重试的 `SESSION_BUSY`，并以 `session_preserved=true` 保留会话；调用方可在 query 完成后重试，或显式选择 kill。doctor 不等待 busy lane：xdebug 使用 fixed native admin path，缺少独立管理入口的 backend 明确返回 health unknown。
- xdebug detached engine 可能在 loop 死后存活，只使用固定 native admin path doctor/kill；无法确认清理时保留 `orphan_suspected` tombstone。
- xcov backend 随 loop 进程退出；xcov kill 终止 loop/process/LSF job，并明确标记 native kill 不支持。
- close/kill 分层返回 native backend、stdio loop、process、LSF job、manager record、tombstone 状态；部分失败为 `SESSION_CLEANUP_PARTIAL_FAILURE`，不得同名隐式 reopen。
- xcov reason revision 尚未通过 CSV export/compile/apply 持久化时，普通 close 返回
  `UNPERSISTED_EXCLUSION_REASON` 并保留 live loop；先导出 CSV，或仅在明确接受丢失时传
  `confirm_discard_reasons=true`。manager 不得把这种可恢复拒绝误判成 backend death。
- debug/cov query 都禁止 native lifecycle action；使用专用 tool，不做 transport/backend fallback。
- 两类 session-open 的 `run_manifest` 均为可选路径。提供时会在启动后端前校验
  `state:"published"`、相对资源路径、`size_bytes` 与 SHA-256；xdebug 使用
  `xdebug.run-manifest.v1`（`fsdb`/`daidir`），xcov 使用 `xcov.run-manifest.v2`（`vdb`）。
  xcov v2 使用 `sha256-entry-tree-v2`，要求 kind、regular-file 总字节数、
  file/directory/symlink 计数及无歧义 SHA-256；旧 v1 会 fail-closed。
- xdebug 的 JSON 响应 `tool` 元数据包含 `build_id`、`git_revision` 和
  `schema_revision`；会话列表中的 `resource_identity.manifest_sha256` 只是 wrapper
  对已提供 manifest 的摘要，实际 provenance 校验仍由 native session.open 完成。
