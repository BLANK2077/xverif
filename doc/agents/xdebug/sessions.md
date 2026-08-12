# xdebug Session 系统

session 系统用于复用 daidir、fsdb、engine 和 transport 资源。session 合同错误会直接影响 MCP、stdio-loop、long-running debug 和环境排障。

## Public Session Actions

常见 action：

- `session.open`
- `session.list`
- `session.close`
- `session.gc`
- `session.doctor`

要求：

- `session.open` 的 `args.name` 必填。
- 后续原生 request 使用 `target.session_id` 选择 session。
- `session.close` 使用 `target.session_id`，`args.mode=graceful|force`，默认 graceful。
- `ownership_token` 只允许 force 且单一精确 session id；`all` 禁止 token。
- `session.gc` 不接受随意清理参数，按 schema 调用。
- `session.doctor` 用于诊断当前 session 资源、transport 和 backend 状态。

## Session 生命周期

典型流程：

1. `session.open` 读取 `target.daidir`、`target.fsdb` 和 `args.name`。
2. frontend session catalog 记录 name/session_id 和资源。
3. 需要 engine 的资源打开 backend session。
4. engine transport ready 后，query 可复用 session。
5. `session.close` 默认 graceful 释放资源；异常残留显式使用 `mode=force`。
6. `session.gc` 清理过期或不可用项。

registry 不再是全局 JSON。每个 session 使用
`~/.xdebug/engine/sessions/<session_hash>/state.json`，query 按规范化 id 直接定位，只有 list/gc
遍历 session 目录；terminal generation 归档到 `history/`，默认 list 跳过。open/close/kill/gc 和
timeout containment 在该 session 的 lifecycle lease 内更新状态，普通 query/list/doctor 不取得
lease，也不为同步 `last_active` 写入阻塞返回。

## FSDB 资源身份门禁

- per-session registry v4 在 open 时记录 canonical FSDB path、device、inode、size 和
  nanosecond mtime；open 完成前再次比较完整指纹。
- 所有 session-bound query 在进入旧 NPI/FSDB handle 前重新读取该指纹。任一变化、
  资源缺失、类型变化或旧 v2 指纹不足都返回 `RESOURCE_CHANGED`。
- `RESOURCE_CHANGED` 不自动 reopen、不清理 session、不切换 transport。先显式
  `session.close`（默认 graceful），再对当前 FSDB 创建新 session。
- 旧的非空全局 registry 必须停机后显式迁移；运行时返回 `REGISTRY_MIGRATION_REQUIRED`，不会
  与 v4 混跑或静默读取旧状态。
- 本轮强门禁只覆盖 FSDB。daidir 顶层目录 stat 仅用于 doctor 弱诊断，不能证明目录内部
  数据库内容未被原地修改；不实现递归 hash 或 vendor-specific identity marker。

## Frontend 与 Backend Session

frontend session：

- 面向用户和 MCP 暴露。
- 保存资源绑定和 backend 映射。

backend session：

- engine 内部资源实例。
- 管理 NPI/FSDB/transport/worker 生命周期。

要求：

- frontend/backend 映射必须可诊断。
- backend crash 后 frontend 不得假装 session 仍健康。
- close graceful/force 必须处理部分失败并保留错误上下文。

## SESSION_LOST

含义：

- MCP/stdio-loop 或 manager 侧已经丢失 session 映射。
- 旧 session 不可继续复用。

处理：

- 不要继续对同名 session query。
- 重新 `session.open` 一个明确名字。
- 保留原错误上下文，避免覆盖根因。

## SESSION_UNHEALTHY

常见原因：

- engine child exited。
- backend ready timeout。
- NPI/FSDB 初始化失败。
- transport endpoint 不可达。

处理：

- 先查 lifecycle/transport log。
- 不要自动切换 file transport。
- 先关闭旧 session、换新名字重开，或把错误上下文返回给用户。

## NPI startup failures

`session.open` 会把统一 engine 启动阶段细分为：

- `NPI_INIT_FAILED` / `failure_phase=npi_init`
- `NPI_LOAD_DESIGN_FAILED` / `failure_phase=npi_load_design`
- `NPI_FSDB_OPEN_FAILED` / `failure_phase=npi_fsdb_open`

三类错误都返回 `diagnostic_log=engine_npi_startup`，对应 engine session 的
`owners/<owner>/logs/npi_startup.log`。若 `npi_init` 失败且 `SNPSLMD_LICENSE_FILE`、
`LM_LICENSE_FILE` 均未显式设置，`error.advisories` 包含
`LICENSE_ENV_NOT_EXPLICIT`；该 advisory 不替代 NPI 结果，也不会提前 hard fail。

## SESSION_TRANSPORT_FAILED

常见原因：

- UDS socket 不存在或不可达。
- TCP connect failed。
- file transport request timeout、expired、stale claim。

处理：

- 不复用该 session。
- 检查 transport log 的 phase 和 endpoint。
- 如果是沙箱网络/文件系统差异，先做 sandbox-vs-host 对照。

## MCP Session 语义

MCP debug 工具：

- open：`xverif_debug_session_open(name, fsdb=None, daidir=None, ...)`
- query：`xverif_debug_query(session_id, action, args=None, ...)`
- list：`xverif_debug_session_list(include_tombstones=False, verbose=False)`
- doctor：`xverif_debug_session_doctor(name=..., session_id=..., verbose=False)`
- close：`xverif_debug_session_close(session_id=..., mode="graceful|force")`
- gc：`xverif_debug_session_gc(verbose=False)`

MCP coverage 工具使用对称的 `xverif_cov_session_open/list/doctor/close/kill/gc`，query 参数名为 `session`。

要求：

- MCP 参数名必须映射到原生 `target.session_id`。
- batch nested args 中，outer args 是 MCP tool 参数，inner args 是 xdebug action 参数。
- debug/cov query 禁止调用 native `session.*`；coverage 的 `session.status` 使用 `xverif_cov_session_doctor`。
- doctor 只读，不自动重连、重启或 reopen；MCP close 只接受一个精确 session，不支持 `all`。
- SESSION_LOST 后先查看 tombstone 并 doctor；xdebug detached engine 未确认清理前不得同名 reopen，精确 force close 后由 gc 删除 closed tombstone。
- xdebug dead loop 使用固定 native admin path；xcov backend 随 loop 退出。能力差异来自 capability 表，不允许失败后改 transport/backend。
- public record 默认 compact；只有 `verbose=true` 返回 PID、job、完整资源路径和分层清理诊断。

## Session 测试

优先测试：

- `pytest --xverif-gate regression --xverif-suite xdebug.session`
- `pytest --xverif-gate regression --xverif-suite xverif_mcp.process`
- `pytest --xverif-gate regression --xverif-suite xdebug.mcp_direct`
- `xverif_mcp/tests/test_session_errors.py`
- `xverif_mcp/tests/test_stdio_loop_session_lifecycle.py`

真实 LSF 或 license 相关 session 测试按根目录 `AGENTS.md` 在沙箱外执行。
