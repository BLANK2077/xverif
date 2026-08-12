# xdebug Log 系统

xdebug 的 log 是工具可观测性合同的一部分。任何 session、transport、engine、runtime 错误都应能从结构化日志中定位阶段和原因。

## 日志原则

- stdout 保留给 JSON/XOUT 结果。
- stderr 可用于人类可读错误，但不能成为机器合同。结构化日志首次降级时只输出一条
  低依赖、无路径和无原始异常内容的告警；后续失败只累计进程内健康计数，避免刷屏。
- 结构化日志使用 ndjson，便于 grep、jq、agent 读取。
- error response 应给出 error code，log 应给出 phase、context、路径和底层错误。
- `logging_health_snapshot()` 提供进程内 degraded 状态、累计失败数和首次失败的稳定
  code/operation，供诊断与单元测试读取；它不改变 action response。
- 已存在的 public `session.json` 无法解析时必须保留原文件并返回失败，禁止用新 manifest
  覆盖损坏证据；可写时在该 session 的 `logs/log_health.ndjson` 记录健康事件。

## 常见日志类型

### Action log

用途：

- 记录 public action 请求、响应、错误、耗时、resource、session。

常见位置：

- 有 session：`~/.xdebug/sessions/<session_id>/logs/actions.ndjson`
- 无 session 或解析失败：`~/.xdebug/sessions/adhoc/logs/actions.ndjson`

使用场景：

- JSON parse/validate 失败。
- action 返回错误但 stdout 信息不够。
- 需要确认 request 是否到达 frontend。

### Lifecycle log

用途：

- 记录 engine 启动、ready、NPI/FSDB 初始化、crash、restart、quit、gc。

常见位置：

- `~/.xdebug/engine/sessions/<hashed-session>/logs/lifecycle.ndjson`

使用场景：

- `SESSION_UNHEALTHY`
- `child_exited`
- engine ready timeout
- NPI/FSDB 初始化失败

### Transport log

用途：

- 记录 UDS/TCP/file transport 的 bind、connect、ping、query、timeout、endpoint。

常见位置：

- `~/.xdebug/engine/sessions/<hashed-session>/logs/transport.ndjson`

使用场景：

- `SESSION_TRANSPORT_FAILED`
- UDS socket 不可达
- TCP connect refused/timeout
- file transport request expired/stale claim

### Daemon debug log

用途：

- 记录 engine daemon 的文本细节。

常见位置：

- 对应 engine session 目录下的 `debug.log`

使用场景：

- 结构化 lifecycle/transport 还不够定位时。
- 需要底层库或子进程输出上下文时。

### NPI startup diagnostic log

用途：保存 `npi_init()`、`npi_load_design()` 和 `npi_fsdb_open()` 启动窗口内的
stdout/stderr，包括 NPI、license 和 FSDB compatibility diagnostic。

位置：`~/.xdebug/engine/sessions/<hashed-session>/logs/npi_startup.log`。

- 文件权限固定为 `0600`，成功和失败 session 都保留。
- `env.snapshot` 只记录 `SNPSLMD_LICENSE_FILE`、`LM_LICENSE_FILE` 是否存在，不记录值。
- 普通 log bundle 包含原始文件；redacted bundle 排除原始文本，只保留 lifecycle 摘要。

### Analysis test probe

用途：

- Phase 0/benchmark 记录协议 scanner 次数、entry/index 数、hit/miss/evict、
  resident/build estimated bytes、engine PID 和单调 access sequence。

启用与边界：

- 仅测试进程显式设置 `XDEBUG_TEST_ANALYSIS_PROBE_PATH`；默认完全禁用。
- 输出文件为权限 `0600` 的 JSONL，key 只保留摘要。
- 它不是生产 action/lifecycle log，不是 public API，也不能作为用户清缓存入口。
- probe 文件写入失败不得影响 action 成败；生产 cache hit/miss/evict 仍应写正常的
  结构化内部日志。
- stream `build` estimated bytes 计量列式 `StreamBaseAnalysis`，不计请求级
  `StreamQueryView`；legacy differential 的第二次 oracle 扫描不写 probe，避免污染正式
  scanner/build 基线。Phase 4B 由 repository 发布跨 action 的 hit/miss/build/evict；
  full 成功替换同语义 range 时以 `invalidate` 和 `full_replaced_range` 记录，失败构建不得
  产生该失效事件。

## 排障顺序

1. 看 action response 的 error code 和 message。
2. 查 action log，确认 request envelope、action、target、session、耗时。
3. 查 lifecycle log，确认 engine 是否启动、ready、crash；若失败阶段是
   `npi_init`、`npi_load_design` 或 `npi_fsdb_open`，继续查看 `npi_startup.log`。
4. 查 transport log，确认 bind/connect/ping/query 阶段。
5. 查 daemon debug log，补充底层细节。
6. 若涉及沙箱、网络、license、文件系统，做 sandbox-vs-host 对照。

## 字段要求

新增 log event 时应包含：

- `timestamp`
- `phase`
- `event`
- `session_id` 或 backend session key
- `action`
- `status`
- `error_code`
- `message`
- `elapsed_ms`
- endpoint/path 等资源上下文

禁止：

- 写入 token、cookie、license 内容。
- 在用户可见回答中暴露不必要的本机绝对路径。
- 只写自由文本、不写结构化字段。

## 修改 log 的测试

- C++ log helper 变化：跑相关 unit test，例如 action log/file exchange/process runner。
- session lifecycle 变化：跑 `pytest --xverif-gate regression --xverif-suite xdebug.session`。
- transport 变化：跑 session/MCP focused tests。
- 如果测试需要真实 LSF/license/VIP，按根目录 `AGENTS.md` 规则在沙箱外执行。
- analysis probe/estimator：跑 `xdebug.cpp_unit`；真实 RSS/scanner 基线在沙箱外跑
  nightly `xdebug.analysis_cache_benchmark`。

### Analysis cache 生产日志

- engine 启动写 `analysis_cache.initialized`，只记录 soft/hard bytes 与 safety factor。
- repository 写 `analysis_cache.hit/miss/build/evict/invalidate/index_build/oversize_admitted/build_failed`。
- AXI Phase 2 的 index object kind 使用 `index:address`、`index:id` 和
  `index:handshake:<channel>`；canonical build 和各 lazy index 分别记账，不能把 index
  命中伪装成新的 FSDB scan。
- APB Phase 3 的 index object kind 使用 `index:address`；canonical 与 AddressIndex
  分开记账，query 内部重复定位使用无 access side effect 的 peek。
- 每条只包含 protocol、非敏感 key 摘要、object kind、reason、estimated bytes、
  generation 和单调 access sequence；不得记录规范化 config 或完整 signal path。
- `build_failed` 的 action 错误仍由 handler 返回；日志不能触发 scope/backend fallback。
- hard-limit 或 best-effort `bad_alloc` 转换统一返回
  `ANALYSIS_MEMORY_LIMIT_EXCEEDED`，并携带 estimated/hard bytes、protocol、key 摘要和
  显式建议；日志与 response 均不得包含完整规范化 signal config。
