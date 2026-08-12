# xdebug 综合代码评审报告

日期：2026-08-11

评审基线：`06d5df6`（当前工作树另有用户文件 `doc/xcov-code-review-2026-08-11.md`，本次未修改）

评审范围：`xdebug/src`、公开 action/schema/example、session/transport、APB/AXI/stream、
XOUT、测试 catalog、`xdebug/docs`、`doc/agents/xdebug`、`skills/xverif` 及 MCP 边界说明

评审方式：4 个审查线程并行只读检查、正式 catalog suite、无资源 CLI 定向探针、静态复杂度与
合同交叉核验；补充运行真实 NPI/FSDB 定向实验，未运行 VCS/VIP 全量回归，未修改 xdebug 源码

## 1. 结论摘要

xdebug 已经具备较清晰的 frontend/engine 分层、action-specific schema、统一完整性字段、
APB/AXI/stream canonical cache、严格生成检查和较丰富的 deterministic tests。它不是一个
“架构失控”的项目；当前主要风险集中在 session 恢复性、安全随机数、timeout 语义、缓存
元数据边界、transport I/O、AI 文档漂移和部分 action 的规模性能。

本次共整理 33 项发现：

- 1 项 P0：TCP 唯一认证 token 在安全随机失败时静默降级为可预测 LCG；
- 8 项 P1：阻塞查询可同时锁死 kill/close、timeout 不取消后台 action、资源变化后仍可返回
  旧数据库事实、cache generation 元数据不受预算约束、socket 请求固定 1 MiB 且逐字节读取、
  MCP batch 绕过 session 管理边界、XOUT 静默隐藏结果、batch mode 拼写静默改变控制流；
- 19 项 P2：session 只读/close 语义不实、transport 错误丢失、cache 热路径与 LRU 复杂度、
  AXI/APB 全量物化、性能门禁无效、非法环境变量静默默认、AI 文档和错误字段漂移、batch
  schema 巨型 payload、设计侧能力缺口等；
- 5 项 P3：重复 handler 桥接、生产二进制中的 test hook、确认的未调用 helper、异常路径静默
  丢日志/trace evidence。

建议先停止扩展新的 stateful action，优先修复 P0/P1，并把“timeout 可取消、管理动作可抢占、
资源身份 fail-closed”定义成统一 runtime 合同。性能方面应先修缓存元数据和 O(N²) 淘汰，
再优化单 action。AI 易用性方面，优先让文档、错误字段和真实 73-action catalog重新单源化。

## 2. 严重级别与发现总表

| ID | 级别 | 类型 | 结论 |
| --- | --- | --- | --- |
| XDBG-SEC-01 | P0 | 安全/无效 fallback | TCP auth token 在安全随机失败时退化为可预测 LCG |
| XDBG-LIFE-01 | P1 | 恢复性/并发 | 查询持有 lifecycle lease，卡住后 kill/close 也无法抢占 |
| XDBG-LIFE-02 | P1 | timeout | 客户端 timeout 不取消 server action，单线程 engine 继续被占用 |
| XDBG-COR-01 | P1 | 正确性 | 普通 query 不检查 FSDB/daidir 是否已变化，可返回旧 handle 的事实 |
| XDBG-MEM-01 | P1 | 内存边界 | cache generation 元数据不计预算且 `clear()` 不释放 |
| XDBG-IO-01 | P1 | transport/性能 | engine 请求逐字节读取、固定 1 MiB，超限没有专用错误 |
| XDBG-SEC-02 | P1 | MCP 生命周期 | native `batch` child 可绕过 managed-session action guard |
| XDBG-COR-02 | P1 | 输出完整性 | 默认 XOUT 对 batch 结果二次截断且没有完整性提示 |
| XDBG-COR-03 | P1 | 静默 fallback | `batch.args.mode` 任意拼写均退化为 continue |
| XDBG-LIFE-03 | P2 | action 副作用 | `session.list/open` 会隐式 kill 全局过期 session |
| XDBG-LIFE-04 | P2 | action 完备性 | `session.close` 和 `session.kill` 实现相同，没有 graceful/force 区别 |
| XDBG-ERR-01 | P2 | 错误合同 | file transport 丢弃 timeout/expired 等细分状态 |
| XDBG-IO-02 | P2 | I/O 健壮性 | client 单次 `write()`、忽略 `setsockopt`，TCP connect 不受 public deadline 约束 |
| XDBG-PERF-01 | P2 | cache 热路径 | 每次 cache event/hit 无条件多次全表统计 |
| XDBG-PERF-02 | P2 | 算法复杂度 | 多项 LRU 淘汰为 O(N²) |
| XDBG-PERF-03 | P2 | action 性能 | AXI outlier/window 与 APB window 在 limit 前全量物化/排序 |
| XDBG-TEST-01 | P2 | 性能门禁 | benchmark latency 阈值只打印，不参与断言 |
| XDBG-CFG-01 | P2 | 静默 fallback | 多个 transport/log/TTL 环境变量非法时静默使用默认值 |
| XDBG-AI-01 | P2 | 文档/AI | agent guide 推荐不存在 action 和已禁止字段 |
| XDBG-AI-02 | P2 | 错误提示 | 文档要求 `allowed_values`，runtime 实际发布 `available_values` |
| XDBG-AI-03 | P2 | schema payload | `batch` response schema 获取耗时、内存和输出体积过大 |
| XDBG-AI-04 | P2 | README/help | active-driver 等核心示例使用已删除字段 |
| XDBG-SCHEMA-01 | P2 | 维护闭环 | 规则要求的 AXI response generator 已不存在 |
| XDBG-AI-05 | P2 | XOUT 错误 | 默认 XOUT 不投影 `validation_issues` |
| XDBG-AI-06 | P2 | MCP schema | 复杂 oneOf/allOf action 的 invalid examples 为空 |
| XDBG-GAP-01 | P2 | action 缺口 | 设计侧层级发现、source/context、FSM/sequential 等公开能力不足 |
| XDBG-GAP-02 | P2 | action 对称性 | APB 无标准 export action，长结果只能进 response |
| XDBG-OBS-01 | P2 | session 可观测性 | list 丢 lifecycle state，默认输出又不 compact |
| XDBG-ARCH-01 | P3 | 可维护性 | 多个 action wrapper 仍走字符串二次 dispatcher |
| XDBG-TEST-02 | P3 | 生产隔离 | legacy stream differential oracle 编入生产 engine，可被环境变量启用 |
| XDBG-DEAD-01 | P3 | 死代码 | non-cached legacy stream wrapper 已链接但全仓无调用 |
| XDBG-OBS-02 | P3 | 异常可观测性 | logging/trace 内部异常可静默丢 evidence |
| XDBG-AI-07 | P3 | action routing | APB/AXI statistics 缺少 query/analysis alternatives |

P0 表示应立即修复的安全问题；P1 表示在继续扩大 MCP/长 session 使用前应修复；P2 应进入
近期版本；P3 可随相关重构清理。

## 3. P0/P1 详细发现

### XDBG-SEC-01：TCP auth token 存在可预测 fallback

`xdebug/src/core/session/transport_common.h:28-43` 从 `/dev/urandom` 单次读取 24 bytes；短读、
EINTR 或 open 失败后清零，再以 `time ^ pid` 为种子生成 LCG token。代码还用“前两字节均为
0”判断失败，安全随机自然命中该值的概率为 1/65536，也会错误降级。该 token 是 TCP server
在 `xdebug/src/engine/server.cpp:669-675` 的唯一认证凭据。

影响：非 loopback 或跨 namespace TCP surface 可能使用可预测 token；这也是明确的静默
fallback。应改成可返回错误的安全随机 API，循环处理 EINTR/short read，失败时以
`SECURE_RANDOM_UNAVAILABLE` fail-closed，不能根据随机内容判断读取成功。补充 urandom
失败/短读和非降级测试。

### XDBG-LIFE-01：卡住的 query 同时阻塞 kill/close

`xdebug/src/engine/session/client.cpp:62-69` 在 connect/RPC 前取得 `SessionLifecycleLease`，
直到完整 request 返回才释放；`session.kill` 在
`xdebug/src/engine/session/session_manager.cpp:923-933` 也需同一 lease；lease 本身在
`session_lifecycle_lease.h:18-31` 使用无超时 `flock(LOCK_EX)`。

因此阻塞 query 持锁时，原本用于恢复的 kill/close/doctor 也会阻塞在锁外。建议 lease 只
保护 generation 快照和 registry 变更，不覆盖阻塞 RPC；kill 使用有界或非阻塞获取，并提供
明确 `SESSION_BUSY`/强制终止路径。测试必须覆盖“查询正在阻塞时并发 kill 有界完成”。

### XDBG-LIFE-02：public timeout 不是 action cancellation

engine 在 `xdebug/src/engine/server.cpp:695-702` 只把 `limits.timeout_ms` 标成 consumed，
handler 仍在 `:718-735` 同步执行；accept loop 也是单线程串行。客户端在
`xdebug/src/engine/session/client.cpp:171-203` 超时后仅关闭 fd。file transport 同样只在
claim 前判断 deadline，claim 后没有取消。

影响：用户收到 `ENGINE_TIMEOUT` 后，NPI/FSDB 扫描仍占用 CPU/内存，后续 query、ping、quit
继续排队；和 XDBG-LIFE-01 叠加后 session 可能无法自恢复。应建立贯穿 scanner/handler 的
monotonic deadline/cancellation token，或使用可终止的请求 worker；响应要区分 cancellation
pending/confirmed。现有测试只验证客户端返回时间，没有验证后台停止及下一请求可服务。

### XDBG-COR-01：资源变化后仍可能返回旧事实

普通 session action 路径 `xdebug/src/api/dispatcher.cpp:1089-1143` 只检查 catalog 与 idle，
资源变化检查仅在 `session.doctor` 中执行。`xdebug/src/waveform/server/service/context.cpp:104-113`
定义了 `fsdb_changed()`，但无调用。backend 的内容匹配还主要依赖秒级 mtime+size，daidir
目录内文件原地变化更难发现。

这会让“确定性事实工具”在 FSDB/daidir 被替换或更新后继续从旧 NPI handle 返回成功结果。
建议每次 query 前做低成本 identity gate，daidir 使用发布 manifest/digest；发现变化返回
`RESOURCE_CHANGED`，不得自动 reopen。增加 open 后替换 FSDB/修改 daidir 再直接 query 的测试。

### XDBG-MEM-01：cache generation 元数据绕过预算

`xdebug/src/waveform/cache/analysis_repository.h:461-464` 长期保存 `generations_`、
`evicted_keys_`、cursor 和 stream bindings；每个新 key 在
`analysis_repository.cpp:475-480` 写入 generation。`clear()` 在 `:849-858` 清 canonical、
index、cursor、binding、evicted，却不清 `generations_`；预算/statistics 在 `:198-251`、
`:901-914` 只统计 canonical/index。

长 session 持续构造唯一 stream range/semantic key 时，即使 canonical 被 LRU 淘汰，带
normalized semantics/path/range 的 key 仍驻留，hard max 无法约束。应明确 generation 的
跨 invalidation 语义，使用有界 digest tombstone 或随淘汰回收，并把所有 metadata 纳入
estimator、hard budget 和 stats；增加 1e4/1e5 unique-key churn RSS 测试。

### XDBG-IO-01：socket request 固定 1 MiB 且逐字节读取

`xdebug/src/engine/server.cpp:392-401` 每次 `read(fd, ..., 1)`；`handle_client` 在
`:648-656` 使用固定 `char line[1024 * 1024]`。达到上限但未读到换行时函数仍返回 true，
随后把截断 JSON 报成普通 `INVALID_JSON`。公开 schema 对 batch/list/config 字符串和数组没有
相应 1 MiB 上限；file transport 则另有默认 64 MiB 合同。

这同时带来每请求数百/数千 syscall、跨 transport 大小语义不一致、合法大请求被隐式截断和
错误提示失真。应复用 block reader，定义统一 public max request bytes，超限返回
`REQUEST_TOO_LARGE` 和 limit/actual bytes，并在所有 transport、MCP 与 schema 提示中一致。

### XDBG-SEC-02：MCP 的 native session guard 可被 batch child 绕过

`xverif_mcp/src/xverif_mcp/server.py:608-609` 只检查顶层 action 是否属于 forbidden native
session action；`batch` 自身为 `requires:none`，child schema 允许完整 native envelope，
`xdebug/src/api/dispatcher.cpp:1160-1164` 又直接递归 dispatch child。

定向复现表明：直接从 `xverif_debug_query` 调 `session.list` 会被 wrapper 拒绝，但把同一请求包在
`batch.args.requests[]` 可成功读取 native catalog；open/close/kill/gc 同理可绕过 MCP 的 owner
tracking，造成泄漏或误杀。建议 MCP 面禁止 native batch，统一使用已经逐 tool 串行的
`xverif_batch`；如必须保留，wrapper 必须递归执行 action policy 和资源合同检查。

### XDBG-COR-02：默认 XOUT 可静默隐藏 batch child

通用 renderer 在 `xdebug/src/api/xout_renderer.cpp:90-109` 对数组硬编码最多 20 项；嵌套 batch
结果路径实测 25 个成功 child 时，JSON 有 `summary.count=25`、`data.results=25`，默认 XOUT
只显示 request 0..19，且该嵌套投影没有 `(+ 5 more)` 或 response truncation 字段。

这违反 `skills/xverif/references/core/output-formats.md` 和 help 的“不隐藏 handler 已返回行”承诺。
renderer 不应做 action 合同之外的二次截断；若必须压缩，必须发布 canonical total/returned/
truncation scope，并对嵌套结构同样成立。

### XDBG-COR-03：batch mode 拼写错误静默继续执行

`xdebug/schemas/v1/actions/batch.request.schema.json:39-42` 只声明任意 string；runtime 在
`xdebug/src/api/dispatcher.cpp:1159-1171` 仅判断是否精确等于 `stop_on_error`，其它任何值都等价
`continue_on_error`。定向复现 `mode=typo_silent_fallback` 时首 child 失败、次 child 仍执行。

应将 schema 收紧为 `continue_on_error|stop_on_error` enum，handler 对未知值 fail-closed，补
invalid mode contract。公开控制流参数不能用“非特定值即默认”的方式兼容。

## 4. P2 生命周期、错误与配置问题

### XDBG-LIFE-03：只读 discovery action 隐式清理 session

`session.list` 在 `xdebug/src/api/dispatcher.cpp:1194-1200` 先调用全局 expired cleanup；
`session.open` 在 `:1321-1325` 也会先 kill 所有过期记录。schema/action guidance 却将 list
描述为“不修改 lifecycle”的发现动作。

建议 list 纯读并返回 `expired=true` 与 `recommended_action=session.gc`；全局清理只归
`session.gc`。若保留副作用，必须在 schema/skill 明示并提供 dry-run。

### XDBG-LIFE-04：close 与 kill 是重复 action

frontend 在 `xdebug/src/api/dispatcher.cpp:1540-1555` 把两者统一改写成内部 `session.kill`；
backend `session_manager.cpp:849-895` 都执行 quit、等待、SIGTERM、SIGKILL。文档声称的 graceful
close 与 abnormal kill 并不存在。

建议真正区分：close 仅 graceful 且失败保留记录，kill 才强制；或者弃用一个 action 并明确
alias，减少 AI 的虚假选择。

### XDBG-ERR-01：file transport 丢失 canonical error

`xdebug/src/engine/session/session_transport.cpp:95-104` 把含 status/message 的
`FileExchangeResult` 压成 bool；`client.cpp:105-124` 再统一成 `transport_failed`。socket 的
EAGAIN/EWOULDBLOCK 才能映射 `ENGINE_TIMEOUT`。

因此同一 `limits.timeout_ms` 在 file transport 下可能被误报为 session unhealthy，且 expired、
stale claim、invalid response、layout/write failure 都丢失。transport 应返回结构体并统一
timeout/error code、phase、sanitized errno。

### XDBG-IO-02：socket client 对 partial I/O 和 connect deadline 不健壮

`xdebug/src/engine/session/client.cpp:19-22` 单次 `write()` 即要求完整发送，`:24-34` 忽略
`setsockopt` 失败；TCP 的 blocking DNS/connect 在 timeout 设置前执行
（`core/session/transport_common.h:85-103`）。大请求、EINTR、partial write 或网络黑洞会超出
public deadline，最终只得到笼统 transport failure。

建议统一 write-all/EINTR 处理，检查 setsockopt，以 nonblocking connect+poll 使用剩余 deadline，
bounded reader 返回 failure phase/errno；补 forced partial write、setsockopt failure 和 TCP
blackhole 测试。

### XDBG-CFG-01：非法环境变量静默使用默认值

`xdebug/src/core/common/env_config.cpp:91-110` 的 `env_*_or_default` 丢弃 parse error；file
transport timeout/poll/max JSON/claim、history TTL、log rotate/redact、trace context 等在
`:132-218` 广泛使用。与 session timeout 和 analysis cache 的 strict env 合同不一致。

影响 transport、资源和留存的 env 应 fail-fast；纯展示项至少写结构化 warning 和 effective
value。不要把拼写/范围错误悄悄解释成默认配置。

### XDBG-OBS-01：session list 状态和 compact 合同不足

backend registry 有 `lifecycle_state`，但 frontend `SessionRecord` 没有保存；list 无法区分
opening、active、cleanup_failed。默认记录同时包含 PID、daidir/fsdb、socket/file_dir 等完整
路径，和维护文档“默认 compact、verbose 才完整资源”矛盾。

建议默认只返回 id/mode/transport/state/health/last_active，显式 `verbose` 才投影 path/PID；
保留 lifecycle_state 并增加并发 opening/cleanup_failed 测试。

## 5. P2 性能与测试门禁

### XDBG-PERF-01：cache hit 仍执行多次 O(N) 统计

`analysis_repository.cpp:461-465`、`:595-610`、`:645-652` 的 hit 都调用 `emit()`；
`:917-925` 即使 test probe 未启用也先 `stats()`。stats 又遍历 canonical/index，并分别重复
计算 resident/build/charged bytes。APB/AXI analyzer 也在交给可能 disabled 的 probe 前调用
stats。

建议无 event sink/probe 时直接跳过，repository 维护增量计数和 byte totals，每个事件最多取
一次 snapshot。

### XDBG-PERF-02：LRU 批量淘汰为 O(N²)

`analysis_repository.cpp:269-309` 每淘汰一项都重新全表计算 charged bytes；`:311-381` 再全表
寻找最冷 index/canonical。大量 range/index 在 full build 前被清退时为 O(N²)。

建议维护 charged total 与确定性 LRU 队列/heap，或一次计算缺口并排序候选批量淘汰；增加千项
range churn + full promotion latency test。

### XDBG-PERF-03：小 limit 仍全量物化与排序

`xdebug/src/waveform/server/service/query_actions.cpp:55-70`、`:99-126` 的 APB/AXI window
先以 `-1` 获取窗口全部 transaction，之后才应用 direction/line_limit；AXI outlier 在
`:181-231` 对所有 candidates 排序后才处理 threshold/top_n/line_limit。

建议下推 filter/limit；threshold 单遍统计，top_n 用有界 heap/partial_sort。若必须保留精确
`matched_count`，单独轻量计数，不要为 compact response 物化全部对象。

### XDBG-TEST-01：latency threshold 不是测试门禁

`xdebug/tests/benchmark/test_analysis_cache_baseline.py:433-479` 明确只把 latency 和 phase
target 组成 boolean 后打印，只有 RSS/estimated/scanner 被 assert。catalog 却把 suite 标为
deterministic contract benchmark。

建议在稳定 host 使用宽松 p95/ratio 作为硬门禁，或明确拆成 non-gating observation；增加
cache-cardinality/churn 场景，当前单 key cold/hot 3 samples 捕获不到 O(N)/O(N²) 回归。

## 6. AI 易用性、schema 与 action 完备性

### XDBG-AI-01：官方 agent guide 推荐无效合同

`xdebug/docs/AGENT_GUIDE.md:9-15` 推荐已禁止的 top-level `output.verbosity` 和泛化
`include_*`；`:23` 宣称单资源会“回退”到旧能力；`:36-37` 推荐不存在的 `source.context`、
`include_source/include_trace/include_rows/include_transactions`；`:63-70` 又推荐未统一存在的
`max_items`。README 在 `xdebug/README.md:967-968` 仍把该文件列为正式最短指南。

`xdebug.static` 107 项全过但未发现这些问题，说明文档 fenced JSON/action 名称没有完整接入
schema/catalog 校验。应删除或标注历史文档，正式指南从 actions.yaml/schema/example 生成，
并将所有 public docs JSON/action token 纳入 static suite。

### XDBG-AI-02：错误字段命名与 skill 相反

维护文档和 skill 均要求读取 `allowed_values`，例如
`doc/agents/xdebug/schema-validation.md:121` 和
`skills/xverif/references/capabilities/xdebug.md:141`；runtime builder 只提供
`available_values`（`xdebug/src/core/diagnostic_error.h:173-175`），schema enum 错误和 handler
也都发布后者。定向 CLI probe 已确认 `schema.kind=req` 返回 `available_values`。

这会使严格 agent/下游按文档读取不到修复候选。应选定一个 canonical 名称并一次迁移
runtime、response schema、XOUT、skill、docs、examples；不要长期保留两个同义 public 字段。

### XDBG-AI-03：batch schema 不适合按需 AI 获取

`xdebug/schemas/v1/actions/batch.response.schema.json` 为 4.8 MiB、195435 行，内嵌全部 child
response。定向执行：

| 请求 | wall time | max RSS | JSON stdout |
| --- | ---: | ---: | ---: |
| `schema(value.at,response)` | 0.15 s | 62056 KiB | 150324 bytes |
| `schema(batch,response)` | 3.41 s | 117360 KiB | 5638822 bytes |

这会显著污染 MCP/AI context，也让简单“查 batch 合同”付出全量 action schema 成本。公开完整
schema 可保留为 artifact，但 `schema` action 应支持 summary/child selector/reference graph，
AI 默认只取 batch envelope 和选定 child；完整展开必须显式请求或导出。

### XDBG-AI-04：README/help 的核心示例已经不可执行

`trace.active_driver` schema 只允许 `signal/time/render_time_unit`，但
`xdebug/README.md:844-861` 使用已删除的 `requested_time/include_control`，
`xdebug/help.txt:293-300` 也使用 `requested_time`。README 通用 request 示例还给
`trace.driver` 同时带 daidir+fsdb、缺 signal，并加入不允许的 output。

这些是最显眼的复制入口，优先级高于边缘说明。应由 checked-in canonical example 生成
README/help 片段，并把所有 fenced JSON 纳入 action-specific schema 校验。

### XDBG-SCHEMA-01：AXI response schema 的规定生成入口缺失

根 `AGENTS.md` 与 `doc/agents/xdebug/schema-validation.md` 都要求
`xdebug/tools/sync_axi_response_schemas.py --check`，并声明它是 10 个 AXI response schema 的
生成 source；实际文件不存在，`rg --files xdebug/tools` 也找不到替代脚本。当前维护者无法按规定
重现或检查 AXI response 生成物。

应恢复 generator，或明确把 source 迁移到现存共享合同/生成器，并一次同步 AGENTS、维护文档、
static suite 与提交清单；不能让“必跑检查”永久指向不存在入口。

### XDBG-AI-05：默认 XOUT 丢失多 issue 错误上下文

runtime validator 可返回多项 `validation_issues`，但
`xdebug/src/api/text_response_builder.cpp:327-360` 的错误白名单不渲染它。复杂 oneOf 请求在 JSON
可同时看到缺 target、错误 selector 等多项，默认 XOUT 往往只显示第一项，导致 AI 多轮试错。

建议 XOUT 增加有上限的 `path/message` issues 表，并始终保留 `correct_example` 和完整 issue count；
这属于 presentation limit，应明确而不能悄悄丢字段。

### XDBG-AI-06：MCP 对复杂 action 生成不出错误反例

`xverif_mcp/src/xverif_mcp/schema_projection.py:72-89` 的 `_invalid_examples` 只读取 args schema
顶层 required/direct anyOf，忽略 allOf/oneOf。实测 `value.at`、`expr.normalize` 的
`invalid_examples=[]`，恰好是 selector/resource variant 最易误用的 action。

建议递归解析组合约束，或从 checked-in negative examples/contract notes 生成；全 action projection
测试应要求典型复杂 action 至少有一个可执行反例。

### XDBG-GAP-01：设计侧 action 与工具目标不平衡

73 个 action 中 56 个 waveform、5 个 design、3 个 combined。`scope.roots` 可发现 design root，
但 `scope.list` 在 `xdebug/src/engine/service/actions/waveform/scope_list.cpp:121-122` 强制 waveform，
纯 daidir 无法逐层发现 elaborated hierarchy；`signal.resolve` 又要求 final leaf。当前指南要求先用
外部 `rg`，这对 generate、interface/modport、bind 和 elaborated name 不可靠。

同时 skill/overview 仍宣称 graph/source/FSM/counter/sequential 设计能力，但 catalog 没有
`source.context`、assignment/sequential/FSM view。建议优先补最小的 design scope.list/search 与
source evidence action，再评估 FSM/sequential；不要一次恢复旧的宽表 action。其它值得单独立项
评估的缺口包括双 FSDB/session diff、clock/reset discovery、assertion failure 到 waveform/driver
的关联，以及长任务 progress/cancel。

### XDBG-GAP-02：APB 缺少标准 artifact export

action inventory 有 `axi.export` 和 `stream.export`，但 APB 只有 config/query/statistics/window/cursor。
APB 长仿真结果缺少统一持久化 artifact、preview、完整性与路径合同，用户只能拉大 query response，
或错误地把 APB 降级为 list/stream。建议评估 `apb.export`，直接复用 canonical APB cache 和统一
artifact path 合同；这是能力缺口，需用真实使用频度决定优先级。

## 7. P3 代码卫生与异常路径

### XDBG-ARCH-01：wrapper 与字符串 dispatcher 双层注册

waveform action 目录存在 14 份局部 `AiActionHandler` 桥接类，四个 AXI wrapper 核心逻辑近乎
相同；真正逻辑仍集中在 `waveform/server/service/query_actions.cpp:626-666` 的字符串分发。
这造成 registry + string dispatcher 双 source，action-specific 错误和性能优化需多点同步。

建议抽一个共享 typed adapter，随后逐 action 把逻辑迁到独立 handler，最终删除二次字符串分发。

### XDBG-TEST-02：test-only differential 可进入生产路径

`legacy_stream_analyzer_adapter.cpp:68-91`、`:115-123` 被生产 engine 链接；设置
`XDEBUG_TEST_STREAM_DIFFERENTIAL=1` 会让 cached stream action 额外跑 legacy analyzer，并可能
把差异变成 public failure。测试 hook 应由 test build flag/独立 oracle binary 隔离，至少也要
严格 test-mode gate 和启动告警，避免宿主残留 env 使生产扫描翻倍。

### XDBG-DEAD-01：确认的未调用 helper

`analyze_stream_with_legacy_differential` 只在
`xdebug/src/waveform/stream/legacy_stream_analyzer_adapter.h:20-22` 声明、`.cpp:105-113` 定义，
全仓没有调用；`nm -C xdebug/libexec/xdebug-engine` 仍能看到符号。可删除该 non-cached wrapper；
同文件 cached variant 仍被三个 action 使用，不能整文件删除。

### XDBG-OBS-02：异常会静默丢日志或 trace evidence

`xdebug/src/core/logging/action_log.cpp:370-394` 外层 `catch (...) {}` 可让 action log 完全消失；
`design/trace/trace_engine.cpp:34-41` 把内部 JSON 解析失败变成空对象，后续可能仍把 analysis 表示
为完整。日志失败不应改变 action 结果，但应有进程级 once degraded 标志或低依赖 stderr；内部
trace JSON 失败必须令 `analysis_complete=false` 并带 diagnostic，或直接消除 string round-trip。

### XDBG-AI-07：statistics action 缺少 routing alternatives

73 项 metadata 中仅 `apb.statistics`、`axi.statistics` 的 `alternatives` 为空，尽管它们的
do-not-use 场景可明确转到 `apb.query`、`axi.query/analysis`。这会降低 catalog 对 AI 的路线纠错
能力。建议把非空 alternatives 纳入 metadata contract，至少覆盖这些明显的统计/明细切换。

## 8. action 功能覆盖与产品方向建议

现有 action 的强项是：点值/多时间值、signal activity、event、window verify、list、通用 stream、
APB/AXI canonical transaction、active driver/X origin，以及 session/transport 多形态。下一阶段不宜
继续堆相似的“专用 query wrapper”，建议围绕完整 debug 闭环补以下能力：

1. **可发现性**：纯 design hierarchy list/search、leaf 展开、interface/modport/generate-aware resolve。
2. **源码证据**：稳定 source context、assignment/control dependency 的 compact view；让 trace 结果能
   直接续查，而不是依赖历史 action 名。
3. **回归对比**：两份 FSDB/session 的 signal/event/transaction diff，明确时间对齐与完整性。
4. **失败入口**：assertion/log failure 定位到时间、scope、相关信号，再接 active trace。
5. **长任务控制**：progress、cancel、deadline confirmed，使 AI 能管理大窗口扫描而非只能 timeout。
6. **配置发现**：clock/reset/interface 候选只给事实和置信证据，不做静默猜测或自动加载。

这些是 capability gap，不等同于当前代码 bug；应先做用户任务频度和 oracle 可验证性评估，再进入
action proposal。新增 action 仍须遵守 actions.yaml、schema、example、runtime、XOUT、skill 和
catalog suite 的单源闭环。

## 9. 已验证的正向结论

- action catalog 当前为 73 项，65 stable、8 experimental；inventory/schema/example/runtime 有正式
  生成与 coverage 检查。
- request schema 默认严格拒绝未知字段；定向错误探针能返回 `invalid_arg`、`expected`、
  `received_type`、`correct_example` 和 validation issues。
- APB/AXI/stream 已共享 engine-owned repository，并有 scanner count、hard limit、cursor generation
  与 differential oracle 测试设计。
- response 有 `scan_complete`、`analysis_complete`、`response_truncated` 等细粒度完整性合同。
- session registry 使用 generation、atomic publication 和进程身份检查，避免了多类 PID reuse/旧
  generation 清理风险；问题主要在锁范围和取消语义，而不是完全没有生命周期设计。
- stdout/XOUT 与结构化日志的边界清楚，run manifest 也有 canonical path/size/SHA-256 gate。

## 10. 测试与实测记录

本次运行：

| 正式入口 | 结果 |
| --- | --- |
| `.conda-xverif/bin/pytest --xverif-gate fast --xverif-suite xdebug.static` | 107 passed |
| `.conda-xverif/bin/pytest --xverif-gate fast --xverif-suite xdebug.native_xout_report` | 8 passed |
| `XVERIF_TEST_EXECUTION_ENV=host ... --xverif-gate regression --xverif-suite xdebug.action_runtime_catalog` | 1 external suite passed |
| `XVERIF_TEST_EXECUTION_ENV=host ... --xverif-gate regression --xverif-suite xdebug.cpp_unit` | 1 external suite passed |
| `.conda-xverif/bin/pytest --xverif-gate fast --xverif-suite xverif_mcp.unit` | 152 passed（并行审查线程） |

定向无资源 CLI 探针覆盖 unknown action、unknown schema action、bad enum、additional property 和
`expr.normalize` 错字段；另测量 `value.at`/`batch` response schema 输出。临时材料位于忽略目录
`xverif/tmp/xdebug-review.RzlhoJ/`。

首次报告阶段未运行真实 NPI/FSDB/VCS/VIP/analysis benchmark；随后补充的真实 NPI/FSDB 定向实验
见第 13 节。它们收敛了资源替换、同 handle 并发和 design hierarchy traversal 三项判断，但仍不是
cache churn、AXI 大事务量或 TCP 网络黑洞的规模 benchmark。后续修复相关代码时，应在 host 按
catalog 运行 `xdebug.session`、`xdebug.contract`、`xdebug.analysis_cache_benchmark`、APB/AXI VIP
与对应 nightly suite。

## 11. 建议修复顺序

### 第一阶段：安全与可恢复性

1. 修复安全随机 token，失败 fail-closed。
2. 禁止 MCP batch 绕过 managed-session boundary，并修复 XOUT 二次截断和 batch mode enum。
3. 缩小 lifecycle lease 范围，让 kill/close 可抢占。
4. 建立 server cancellation/deadline，并统一 socket/file timeout code。
5. query 前执行资源 identity gate。
6. 修复 1 MiB/逐字节 request reader 和 partial socket I/O。

### 第二阶段：内存与规模性能

1. generation/cursor/binding metadata 纳入预算并有界回收。
2. repository 使用增量 stats 和确定性 LRU 数据结构。
3. 下推 APB/AXI filter/limit，outlier 使用单遍/有界 top-N。
4. 把 latency/churn 变成真实门禁。

### 第三阶段：合同与产品面

1. 让 session.list 纯读，区分 close/kill，补 lifecycle state/compact projection。
2. 统一 `available_values` 命名，清理旧 agent guide 并生成校验 public docs。
3. 为 batch schema 提供 token-efficient selector/summary。
4. 补 design hierarchy/source 最小闭环，再评估 diff/assertion/progress action。
5. 清理重复 wrapper、test hook 与确认死代码。

## 12. 边界说明

本报告没有修改 xdebug 代码。首次报告的 confirmed 项均有明确可达代码路径或本地无资源实测；
第 13 节进一步标明哪些风险已由真实 NPI/FSDB fixture 复现。标为规模/异常路径的其余结论仍需
针对性 fixture、故障注入或 benchmark 验证。报告之外的用户文件保持原样。

## 13. 补充实验：NPI 行为与推荐方案收敛

### 13.1 实验环境、边界与材料

本节在 host 使用 Verdi/NPI `X-2025.06-SP1`、仓库正式入口 `tools/xdebug` 和已有 fixture cache，
没有重新仿真、没有修改产品代码。临时 C++/Python probe、原始 stdout/stderr、JSON 结果和首次入口
失败证据均位于忽略目录 `xverif/tmp/xdebug-npi-review-20260811/`。

首次 Python probe 直接执行内部产物 `xdebug/xdebug`，session engine 因没有 wrapper 设置的
`XVERIF_HOME` 而找不到 `xdebug/schemas/v1/internal/engine.request.manifest.json`。该次结果没有作为
产品行为证据；失败 JSON 被保留为 `product-experiments.failed-direct.json`。README、test catalog
和公开帮助均以 `tools/xdebug` 为正式入口，随后只修正为该入口并原样重跑。这同时提示：内部 binary
不是自包含入口，若继续允许测试或文档直接引用它，应明确 internal-only，或让 binary 自行从
`/proc/self/exe` 推导安装根，避免把缺环境误报为 schema 配置损坏。

### 13.2 实验结果总表

| 实验 | 观察结果 | 结论强度 |
| --- | --- | --- |
| 打开 9,232-byte FSDB 后原子替换为另一份 9,993-byte FSDB，再直接 `value.at` | inode 已变化；替换前后均成功返回旧 handle 中的 `8'h22`；随后 `session.doctor` 返回 `RESOURCE_CHANGED` | 已复现产品正确性问题 |
| 4,464,084-byte AXI FSDB 上以 `limits.timeout_ms=1` 执行 `axi.query` | frontend 返回 `ENGINE_TIMEOUT`；约 202 ms 后的紧接 `value.at` 成功，`session.doctor` healthy | 只确认本小样例可恢复，不能证明底层 NPI 已取消 |
| 同一 FSDB handle 串行执行 4,000 次 `npi_fsdb_sig_value_at` | 0 failure，约 0.12 s | 有效对照 |
| 同一 FSDB handle 上两个线程各执行 2,000 次相同读取 | 两次独立运行均在开始阶段出现 FSDB reader 内部错误并 SIGSEGV，退出 139 | 当前 NPI 版本/调用形态下的强反例 |
| 对 interface design DB 使用 `npi_iterate(npiInterface, nullptr)` | 返回 0 | 全局按 kind 枚举不可用 |
| 从 `npiInstance` 顶层沿 `npiInternalScope` 递归同一 design DB | 找到 3 module + 1 interface；UART DB 找到 6 module + 1 unnamed internal scope | relationship traversal 可行 |
| 最小 generate-for fixture 沿 `npiInternalScope` 递归 | 找到 `g_lane[0]`、`g_lane[1]` 两个 `npiGenScope`，并继续找到各自的 module children | generate scope 遍历合同已确认 |
| 最小 interface array fixture | `links` 按名解析为 `npiInterfaceArray`；递归 child 是 `links[0]`、`links[1]` 两个 `npiInterface`，元素通过 `npiInstanceArray` 关联容器 | array 容器/元素关系已确认 |
| 对两个 interface array 元素迭代 modport | 每个元素找到 producer/consumer 两个 `npiModport` 和 6 个 `npiMpPort`；方向分别从 mpport 得到 input/output | modport 层级与方向合同已确认 |

### 13.3 XDBG-COR-01：资源 identity gate 的最佳落点已明确

此前对“资源替换后可能继续返回旧 handle 数据”的判断现已复现。`session.doctor` 已有正确检测逻辑，
但普通 query 不调用它，所以 action 可以携带 `ok=true` 返回 stale fact。最佳修法不是在每个 handler
散落检查，而是在 frontend 取得 session record、发送 engine request 之前执行统一 pre-dispatch
identity gate：

1. FSDB 至少比较 canonical path、device、inode、size、mtime-ns；任一变化立即返回
   `RESOURCE_CHANGED`，不自动 reopen、不继续调用旧 handle。
2. 检查结果只允许在一个请求的极短 dispatch 窗口内复用；不能把 doctor 的人工调用当一致性屏障。
3. session metadata 返回 `identity_strength` 和已校验时间，便于 AI 区分 strong/weak evidence。
4. 增加“open -> 原子替换 -> 直接 query”的 contract test；只测 doctor 不足以守住正确性。

纯 daidir 仍有一个未完全解决的边界：只 stat 顶层目录不能发现内部数据库文件被原地修改，而每次
递归 hash 整个 daidir 成本过高。推荐优先绑定 immutable run manifest/generation digest；没有 manifest
时只发布 `identity_strength=weak`，并对一组由本地 NPI DB 格式确认的稳定 marker 做 fingerprint。
在 marker 集未被 vendor 文档或 fixture 实验确认前，不应声称强一致性，也不应静默 reopen。

### 13.4 XDBG-LIFE-02：timeout 应分成 cooperative cancel 与 hard containment

1 ms AXI 实验只能说明 frontend 能返回 timeout、该小 session 随后可用。总 wall time 仍约 179 ms，
且源码没有向正在执行的 handler/NPI call 传 cancellation token，因此不能把它描述为“action 已取消”。
结合 NPI 同 handle 并发会崩溃的实测，最佳方案不应让另一个线程进入 NPI 做 cancel/cleanup：

1. handler、scanner 和 transaction reconstruction 接收统一 deadline/cancel token，在每个可控循环、
   batch 边界和缓存构建阶段协作退出，并返回 `cancel_state=confirmed`。
2. 单次不可分割 vendor call 超时后只能标记 `cancel_state=unknown`；在其返回前不允许同 session 新 NPI
   请求并发进入。
3. hard deadline 由 session 进程外 supervisor 实现进程终止，而不是在 NPI context 内跨线程关闭
   handle。终止后 session 明确进入 `unhealthy/terminated_on_timeout`，由用户显式 reopen；禁止自动
   fallback 或假装原 session healthy。
4. lifecycle lease 只保护 registry 状态转换，不覆盖等待 reply 的整个请求；`session.kill` 必须能从
   进程外有界终止卡死 engine。测试需覆盖 cooperative cancel、vendor-call unknown 和 forced terminate
   三条路径。

仍不确定的是各 L1/L0 vendor call 是否存在该版本专用的可中断接口；本机已读 header 与当前产品代码
没有发现通用 cancellation contract。在 vendor 明确文档出现前，进程终止是唯一可证明的 hard
containment，不应基于一次小 AXI 查询的恢复现象推断可安全中断。

### 13.5 NPI 并发模型：session 内串行化应成为硬架构约束

串行对照完全成功，而同一 file handle 双线程读取稳定触发 vendor reader 崩溃，已经排除“信号不存在”
或“时间范围非法”这类基本探针错误。建议明确并测试以下 invariant：

- 每个 engine process 只拥有一个 NPI context；同一 context/FSDB handle 的所有 NPI 调用严格串行。
- 并行性只放在 session/process 之间，或放在不触碰 NPI handle 的纯 C++ 后处理阶段。
- 不用 mutex 包装后就宣称 NPI thread-safe；mutex 只能实现产品侧串行合同。
- close、cancel、doctor 和 action 共享同一 owner 序列；需要抢占时由进程外 supervisor 终止，不能让
  管理线程并发调用 `npi_fsdb_close`/`npi_end`。
- 新增一个 opt-in host negative probe 可记录 vendor release 的并发崩溃行为，但不应放入日常 gate
  直接制造 core；日常测试验证产品绝不会产生并发 NPI entry 即可。

这个结论限于 `X-2025.06-SP1`、同一 FSDB handle 和 `npi_fsdb_sig_value_at`。它足以否定 xdebug 采用
同 context 多线程并发的架构，却不足以声称所有 NPI API、所有未来版本都必然崩溃。

### 13.6 design hierarchy/action 方案：复用关系递归，不新增平行枚举器

实测证明 interface 与内部 scope 可从 elaborated design DB 发现，但必须遵守 NPI relationship 模型：
先 `npi_iterate(npiInstance, nullptr)` 获取 top，再对每个 scope 递归
`npi_iterate(npiInternalScope, parent)`，按 handle 的实际 `npiType` 分类。全局
`npi_iterate(npiInterface, nullptr)` 返回 0，不能作为 interface 不存在的证据。

建议优先扩展现有 `scope.list`，增加显式 `source=wave|design|merged`（默认保持 `wave` 兼容），而不是
新增一个语义重叠的 `design.hierarchy`：

- `source=design` 使用共享 relationship walker，返回 module/interface/program/gen/internal scope；
  interface、modport 与 generate 必须保留 kind，不能伪装成 waveform signal/module。
- `source=merged` 以 canonical path 合并 FSDB 与 design evidence，逐项标记 `sources`、`queryable`、
  `traceable` 和 mismatch；根层继续复用 `scope.roots` 的 merge 语义。
- 必须提供 `path`、`max_depth`、`kind`、`include_patterns`、`exclude_patterns`、`limits.max_rows`，并同时
  报 `visited_count`、`returned_count`、`truncated` 与 `truncation_scope`，防止大 SoC 无界遍历。
- walker 作为 engine 统一组件供 scope discovery、active trace 和未来 source context 共用，避免每个
  action 各自猜 npi relationship。

补充最小 VCS fixture 后，generate scope、interface array 和 modport 的实际关系已经确认：

- generate-for 元素是 `npiGenScope`，由父 scope 的 `npiInternalScope` 关系返回；它自身还要继续沿
  `npiInternalScope` 递归，才能得到内部 module/interface instance。
- interface array 容器 `hierarchy_types_top.links` 可由 `npi_handle_by_name` 解析为
  `npiInterfaceArray`，但它没有作为本轮 `npiInternalScope` child 返回；child 是展开后的
  `links[0]`、`links[1]` 两个 `npiInterface`。每个元素的 `npiInstanceArray` 一对一关系指回同一个
  array 容器。walker 应以元素为可递归/可查询节点，并按需发布去重后的 array container metadata，
  不能等待一个全局或 child `npiInterfaceArray` iterator。
- 每个 interface 元素通过 `npi_iterate(npiModport, interface)` 得到 producer/consumer；modport 的
  `npiFullName` 在本版本为空，因此 canonical path 应由 interface element path + modport name 组合，
  不能直接信任空属性。随后以 `npi_iterate(npiMpPort, modport)` 得到成员，并从 mpport 的
  `npiDirection` 读取 input/output；不能从 interface member signal 推断方向。

因此共享 walker 的明确边界是：`npiInstance -> npiInternalScope` 负责 hierarchy，遇到 interface 再
走 `npiModport -> npiMpPort` 的侧向关系，遇到 interface element 可用 `npiInstanceArray` 补充容器
归属。三类关系都必须分别设预算，modport/mpport 不计入 hierarchy depth，但计入 visited/object limit。
原始 fixture、probe 和输出位于 `xverif/tmp/xdebug-npi-review-20260811/`。

### 13.7 对原建议优先级的修订

补充实验不改变 1 项 P0、8 项 P1、19 项 P2、5 项 P3 的总数，但把三个建议从“结构风险”提升为明确
实施约束：

1. `RESOURCE_CHANGED` pre-dispatch gate 提到第一阶段正确性修复，且必须覆盖所有 session-bound action。
2. 禁止 session 内 NPI 并发，与 process-per-session、kill 可抢占一起作为 lifecycle 重构验收条件。
3. design hierarchy 缺口不再需要先验证 NPI 是否能遍历；直接按 relationship walker + 有界
   `scope.list source` 方案设计合同即可。

### 13.8 明确不优化项

按本轮范围决定，除 generate scope、interface array、modport traversal 外，其余此前未完全确定的
方向全部标记为**不优化**，不进入后续实现建议、实验计划或验收范围。本节决定覆盖第 13.3、13.4
及更早章节中针对下列未决方向的探索性建议；保留那些文字仅作为风险背景，不作为待办：

- daidir 强 identity 的 vendor marker 集：不优化；保留当前风险说明，不设计新的递归 hash/marker。
- 不可分割 NPI call 的 vendor 专用取消能力：不优化；不继续查私有 API，不新增 vendor cancel 路径。
- AXI/cache 规模性能预算：不优化；不新增 benchmark 阈值或据本轮样例设 SLO。
- VHDL/mixed-language 与 bind instance relationship：不优化；walker 不为未验证类型新增猜测分支。
- automatic reopen：不优化；维持禁止静默 reopen，由用户显式 reopen，不新增 fallback。

这里的“不优化”表示不纳入本轮及报告建议的实施范围，并不表示风险已经消失或 vendor 行为已经得到
证明。后续如果产品范围改变，需要由新的明确需求重新立项，不能把这些项作为 hierarchy walker 的
隐含 fallback 一并实现。

## 14. 最终处置审计（2026-08-12）

本节以实施后的仓库、阶段提交和正式测试证据为准，关闭第 2 节列出的全部 33 项发现。这里的“关闭”
表示已经实现并有对应门禁，或已按第 13.8 节和实施计划明确固定为不优化边界；不把未验证方向包装为
fallback，也不以相邻测试代替对应合同验证。

| Finding | 最终状态 | 阶段/提交 | 处置与验收证据 |
| --- | --- | --- | --- |
| XDBG-SEC-01 | 已修复 | C02 `0fe1328` | secure random 失败返回 `SECURE_RANDOM_UNAVAILABLE`，删除可预测 LCG fallback；unit/static/contract 通过 |
| XDBG-LIFE-01 | 已修复 | C03 `111d386` | lifecycle lease 不再覆盖整段等待；进程外 supervisor 可抢占终止；session/MCP suite 通过 |
| XDBG-LIFE-02 | 已修复 | C03 `111d386` | cooperative deadline checkpoint 与 hard containment 分层；超时终止状态可观测，不自动 reopen |
| XDBG-COR-01 | 已修复 | C04 `7e27303` | 所有 session-bound query 在进入旧 handle 前执行 path/device/inode/size/mtime-ns identity gate，变化返回 `RESOURCE_CHANGED` |
| XDBG-MEM-01 | 已修复 | C06 `477efdd` | generation/cursor/binding/tombstone 纳入统一预算并可释放；资源与 cardinality 门禁通过 |
| XDBG-IO-01 | 已修复 | C05 `0725a50` | block reader 与统一 64 MiB 请求边界，超限返回 `REQUEST_TOO_LARGE` |
| XDBG-SEC-02 | 已修复 | C02 `0fe1328` | managed MCP batch child 递归 guard，禁止 lifecycle action 绕过 |
| XDBG-COR-02 | 已修复 | C02 `0fe1328` | 删除 XOUT 对 handler batch children 的二次截断，完整性合同由 native XOUT report 锁定 |
| XDBG-COR-03 | 已修复 | C02 `0fe1328` | batch mode 只接受两个 enum，非法拼写 fail-closed |
| XDBG-LIFE-03 | 已修复 | C03 `111d386` | session discovery/list 改为纯读，不再隐式清理全局 session |
| XDBG-LIFE-04 | 已修复 | C03 `111d386` | 删除 public `session.kill` 及所有 surface，统一迁移至 `session.close mode=graceful|force` |
| XDBG-ERR-01 | 已修复 | C05 `0725a50` | file transport 保留 timeout/expired 等 canonical 细分错误 |
| XDBG-IO-02 | 已修复 | C05 `0725a50` | write-all、EINTR/partial I/O、nonblocking connect 与 remaining deadline 闭环 |
| XDBG-PERF-01 | 已修复 | C06 `477efdd` | cache stats 改为增量 O(1)，禁用 probe 时不做全表统计 |
| XDBG-PERF-02 | 已修复 | C06 `477efdd` | 确定性 LRU 与批量淘汰消除 O(N²) 路径 |
| XDBG-PERF-03 | 已修复 | C06 `477efdd` | APB/AXI filter/limit 下推，outlier 使用有界 top-N |
| XDBG-TEST-01 | 已修复 | C06 `477efdd` | benchmark 以等价性、RSS、估算字节、scanner 和 cardinality 作硬断言；按固定边界不新增延迟 SLO |
| XDBG-CFG-01 | 已修复 | C05 `0725a50` | 关键 env 非法值 fail-fast；展示类 env 明确发布 warning/effective value |
| XDBG-AI-01 | 已修复 | C09 `bc1ec2b` | skill/action reference 删除不存在 action 与禁止字段，并由 catalog suite 验证 |
| XDBG-AI-02 | 已修复 | C09 `bc1ec2b` | runtime、schema、skill 统一只发布 `available_values` |
| XDBG-AI-03 | 已修复 | C09 `bc1ec2b` | batch response schema 提供 summary/child/full；MCP 默认 summary，summary 不先加载 full artifact |
| XDBG-AI-04 | 已修复 | C09 `bc1ec2b` | README/help 从 canonical checked-in example 生成，公开 JSON fence 对 live schema 校验 |
| XDBG-SCHEMA-01 | 已修复 | C09 `bc1ec2b` | AXI response schema 迁入统一 `sync_response_schemas.py` source of truth，删除失效入口引用 |
| XDBG-AI-05 | 已修复 | C02 `0fe1328` | XOUT 投影有界 validation issue 表并发布 `issue_count/issues_truncated` |
| XDBG-AI-06 | 已修复 | C09 `bc1ec2b` | oneOf/allOf 复杂请求增加 7 个 canonical invalid witness，并做 Draft-7/2020-12 一致性验证 |
| XDBG-GAP-01 | 已修复（固定边界） | C07 `7c26474` | `scope.list source=wave|design|merged` 以真实 VCS/NPI 验证 generate/interface array/modport/mpport；mixed-language/bind、FSM/sequential 等未实验方向明确不优化 |
| XDBG-GAP-02 | 已修复 | C08 `da6e8c1` | 新增 stable `apb.export`，preview/TSV/CSV、过滤、完整性、no-clobber 与真实 APB VIP/XOUT 全闭环；catalog 保持 73 |
| XDBG-OBS-01 | 已修复 | C03 `111d386` | session list 发布 lifecycle state，支持 compact/verbose，保持 discovery 纯读 |
| XDBG-ARCH-01 | 已修复 | C10 `3ae5818` | 15 个 wrapper 使用 typed binding，移除字符串二次 dispatcher |
| XDBG-TEST-02 | 已修复 | C10 `3ae5818` | differential oracle 移至独立 test fixture binary；production engine 无 legacy symbol/env |
| XDBG-DEAD-01 | 已修复 | C10 `3ae5818` | 删除无调用的 non-cached legacy stream wrapper |
| XDBG-OBS-02 | 已修复 | C10 `3ae5818` | logging once-degraded 保留稳定诊断；trace 内部 JSON 失败聚合并强制 `analysis_complete=false` |
| XDBG-AI-07 | 已修复 | C09 `bc1ec2b` | APB/AXI statistics 在 catalog/schema/MCP 中发布可执行 routing alternatives |

计数复核：1 项 P0、8 项 P1、19 项 P2、5 项 P3，共 33/33 项完成最终处置。跨阶段最终证据见
`doc/XDEBUG_COMPREHENSIVE_OPTIMIZATION_PLAN_2026-08-12.md` 的 commit ledger 与 C11 测试账本。
