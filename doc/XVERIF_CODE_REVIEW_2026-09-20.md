# xverif 代码深度审查报告（2026-09-20）

## 1. 文档状态

- 日期：2026-09-20
- 范围：`<repo>` 全仓当前工作树（含未提交改动）
- 性质：**只读审查**。本报告不修改任何项目代码；审查期间未运行 VCS/Verdi/NPI/license 动作，未重建 fixture。
- 基线：`master` @ `f2fd91f`（2026-09-07），工作树另有 16 个已跟踪文件修改 + 7 个未跟踪新增。
- 前序文档：[xverif 全仓库代码与架构深度审查（2026-08-13）](XVERIF_FULL_REPOSITORY_CODE_REVIEW_2026-08-13.md)、[八项 findings 修复计划与验收账本（2026-08-16）](XVERIF_EIGHT_FINDINGS_REMEDIATION_PLAN_2026-08-16.md)。本报告不重复其已关闭结论，只做状态复核并补充新发现。

## 2. 执行摘要

- **前序 8 项 finding 全部仍处于已修复状态**（各条修复提交可定位）；其中 `MCP-POLICY-01` 的权限模型已被 `21dd95f` 主动撤销，README 已声明"`mutation`/`artifact_write` 是描述性元数据而非权限开关"——属有意取舍，但部署方需用进程/文件系统边界替代工具开关。
- **本轮新增 12 项 P1 与约 20 项 P2**，集中在四个方向：
  1. **静默错误结论**：xsva 的 REPEAT/高级 sequence 丢失 obligation 且仍报 `exact`/`complete`（6.10）、antecedent 的 `##` 被压平成单拍合取（6.12）、测试对过期 fixture 证据断言并全绿（6.16/6.17）。
  2. **挂死与崩溃**：xsva 畸形输入无限循环（6.11，实测 `rc=124` 零输出）、xbit/xentry 错误路径自身抛异常并打死 stdio 服务（6.14，实测 `rc=1`）。
  3. **数值与资源边界**：xbit unsized based literal 位宽不符 SV、移位量未短路可放大为 0.5 GiB 分配（6.15）。
  4. **首次接触即失败**：5 个 `tools/*` wrapper 在系统 `python3` 下全部 SyntaxError（7.3）、`make -C xdebug` 链路同样受影响（6.7）。
- **当前工作树唯一门禁红灯**：`pytest --xverif-gate fast` = 667 passed / **1 failed**，失败源于四份**未跟踪文档**里的 40 处本机绝对路径（7.4），与本轮审查无关但会阻塞提交。
- **值得肯定的既有边界**：生成物同步链路（5 个 `--check` + runtime 兼容性审计 + 283 schema/231 examples）全部通过；`xdebug/specs/actions/actions.yaml` 与 skill 生成索引 73/73 一致；无 `shell=True`/命令注入面；xcov 导出与 batch 发布已实现原子化；fixture 缓存的并发发布与 claim 接管可靠。

## 3. 审查方法与证据来源

| 手段 | 说明 |
| --- | --- |
| 静态清点 | `git ls-files` + `wc -l` 统计规模；`ast` 扫描超长函数；Makefile/wrapper 入口核对 |
| 规则化 lint | `ruff 0.16.8`（装入 `tmp/review-tools/`，未污染仓库依赖），按"真实缺陷规则集"筛选：`F821,F841,F811,F823,B006,B008,B012,B017,S110,S112,PLW1510,PLW2901,PLW0603,TRY004,TRY203,RUF100,PLE,PLW0127,PLW0128,PLW0602` |
| 生成物一致性 | `sync_runtime_request_schemas.py --check`、`sync_response_schemas.py --check`、`sync_action_schema_hints.py --check`、`sync_action_metadata.py --check`、`sync_help_text.py --check`、`xdebug/tools/audit_runtime_schema_compatibility.py`、`xdebug/tools/validate_schema.py`、`xdebug/tools/validate_examples.py` |
| 门禁实测 | `pytest --xverif-gate fast --xverif-suite xdebug.static`（**123 passed**）；`pytest --xverif-gate fast` 全量（**667 passed / 1 failed**，失败项见 7.4）；`pytest --xverif-gate fast --xverif-suite testinfra.unit`（55 passed / 1 failed，同一失败项） |
| 入口实测 | 直接执行 `tools/xbit|xentry|xloc|xsva|xwaveform`，对照显式 `PYTHON=` 的成功路径 |
| 人工调用链核对 | 对每个 finding 沿调用方追到可达性结论，区分"不可达死代码"与"可触发运行时错误"；四个并行只读审查单元分别覆盖 xdebug C++（core/session/engine/transport/logging/cache）、xcov + xverif_mcp、小工具 + testinfra + skills 脚本，以及主线程横切核对 |
| 关键断言复核 | 主线程独立复核了**全部 P1 与关键 P2** 的代码路径与行为，且全部复核为"成立"：默认 deadline 传播与无限 poll、`EEXIST` 当成功、`flock` 无超时、锁外轮转、`full_name` 未绑定可达性、wrapper 解释器失败、生成物同步、xsva REPEAT/antecedent 语义与畸形输入挂死（实测 `rc=124`）、xbit stdio 被坏 JSON 打死（实测 `rc=1`）、`'hFF + 'h1` 位宽（实测 `8'h0`）、fixture 指纹漏 `wave.tcl`、`fnmatch` vs `Path.glob` 的 `**` 语义差异、xwiki hook 的 `deny` 响应 |

未做的验证（边界，必须说明）：未运行 `regression`/`nightly`（涉及 NPI/VCS/license），未做性能压测，未做 ASan/UBSan/valgrind 等动态内存检查。因此本报告不对"运行时内存错误"下结论。

## 4. 仓库规模（实测）

| 子系统 | 文件数 | 行数 |
| --- | ---: | ---: |
| `xdebug/src`（C++） | 318 | 61,889 |
| `xdebug/tests` | 296 | 35,438 |
| `xcov/xcov` | 21 | 14,388 |
| `skills/`（含脚本与文档） | 148 | 12,045 |
| `xverif_mcp/src` | 38 | 9,580 |
| `xsva/xsva` | 38 | 5,624 |
| `testinfra` | 40 | 5,539 |
| `xbit` / `xentry` / `xloc` / `xwaveform` | 15 / 14 / 11 / 4 | 2,042 / 1,713 / 1,100 / 382 |

## 5. 前序 8 项 finding 的状态复核

结论：**8 项全部仍处于已修复状态**，且修复提交可定位（`doc/XVERIF_EIGHT_FINDINGS_REMEDIATION_PLAN_2026-08-16.md:22-29,45-51`）。本次抽查了其中影响面最大的 5 项：

| Finding | 状态 | 本次抽查证据 |
| --- | --- | --- |
| MCP-BATCH-01（batch 输入输出同文件自反馈） | 已修复 | `xverif_mcp/src/xverif_mcp/server.py:439-460` 比对 `st_dev/st_ino` 拒绝同对象；改用 staging + `os.link`（`:566-575`）并 fsync 目录，冲突返回 `BATCH_OUTPUT_EXISTS` 且不覆盖 |
| XDEBUG-EXPORT-01（导出非原子） | 已修复 | 修复提交 `7b3a78a`；公共 atomic artifact publisher 已被 APB/AXI/stream 复用 |
| XCOV-CACHE-01（URG cache 容量竞态） | 已修复 | `xcov/xcov/urg_cache.py:243-267` 明确为 best-effort soft capacity（`_enforce_soft_capacity_before_build`） |
| XSVA-COR-01（sampled function 依赖） | 已修复 | `xsva/xsva/lower/sequence_to_timeline.py:343-355` 显式处理 `sampled_funcs` 与 `depends_on_captures` |
| MCP-LIFE-01（长 query 阻塞 kill/close） | 已修复 | `xverif_mcp/src/xverif_loop/sessions/loop_session.py:241` `abort()` + `xverif_mcp/src/xverif_loop/sessions/session_manager.py:659` `kill_session`；修复提交 `c81e4fc`、`519588f` |

**需要特别注意的一项语义变化**：`MCP-POLICY-01` 当初的"严格 mutation/artifact 权限模型"已被 `21dd95f`（2026-09-07）**主动撤销**。当前 `mutation` / `artifact_write` 只是工具目录中的描述性元数据（`xverif_mcp/src/xverif_mcp/server.py:1453-1454`），**没有任何拦截逻辑**；README 已明确声明这一姿态（`xverif_mcp/README.md:501-502`："group/mutation/artifact_write 是描述性元数据，不是权限开关"）。这是有意的设计取舍，不是缺陷——但它意味着**任何能连上该 MCP server 的客户端都具备全量状态变更与文件写出能力**，部署方必须用进程/文件系统边界而不是工具开关来控制影响面。

## 6. 新发现（按级别排序）

> 说明：本轮由四个并行只读审查单元覆盖不同子系统（xdebug C++、xcov+xverif_mcp、小工具+testinfra、以及主线程横切核对）。每条 finding 的 `文件:行号` 均由审查单元给出，其中主线程独立复核了全部 P1/P2 级别的关键断言（复核方式见各条"复核"标注）。

### 6.0 XDEBUG-NET-01（P2，已证实；审查单元初判 P1，主线程复核后降级）

**引擎请求读取无 deadline，单线程 accept 循环可被静默连接阻塞**

- **证据**：`xdebug/src/engine/server.cpp:663-665` 调用 `read_bounded_line_deadline(client_fd, line, kMaxSessionJsonBytes)` 未传 deadline；该函数默认参数为 `TransportDeadline()`（`xdebug/src/core/session/transport_common.h:88`），其默认构造为 `present_=false`（`:33`），`remaining_ms()` 返回 `-1`（`:39-44`），`wait_for_socket` 因此以 `poll(..., -1)` **无限阻塞**（`:51-77`）。accept 循环在 `xdebug/src/engine/server.cpp:1242-1247` 单线程内联调用 `handle_client`；TCP 鉴权发生在读完整行之后（`:689-693`）。
- **复核**：主线程逐行确认了上述四个环节（默认 deadline → `present_=false` → `-1` → 无限 poll），并确认合法路径不会触发——会话请求走 `session_transport`，其连接与轮询带显式 deadline（`xdebug/src/engine/session/session_transport.cpp:80,153`），frontend 亦按公共 `timeout_ms` 派生进程预算（`xdebug/src/backend/engine_adapter.cpp:100-121`）。
- **降级理由**：触发前提是"本机进程连上引擎端口后不发完整行"，属本机可达的自我 DoS，而非远程可利用缺陷；且正常客户端路径已有 deadline。故定级 P2（健壮性/可用性），不按 P1 处理。
- **触发条件**：本机任意进程（含意外的半开连接、调试工具、验证客户端）connect 后不发送换行。
- **影响**：该 session 的引擎在连接被关闭前无法服务任何请求，idle timeout 也不会触发（判定点在 `select` 分支 `:1233`，此时阻塞在读内部）。
- **建议方向**：读请求行时传入连接级 deadline；把鉴权前置到读完整行之前；或改为每连接线程/事件循环。

### 6.0b XDEBUG-RES-01（P2，已证实）：逻辑字面量位宽无上限，小请求可放大为 GB 级分配

- **证据**：`xdebug/src/core/value/logic_value.cpp:315`、`:356` 用 `std::atoi` 解析位宽（超过 `INT_MAX` 为 UB），随后经 `from_body` → `apply_width`（`:142-143` 的 `bits.insert(begin, width - bits.size(), '0')`）实际展开；用户字面量入口在 `xdebug/src/waveform/filter/value_filter.cpp:18` 与 `xdebug/src/waveform/stream/stream_analyzer.cpp:45`，而宽度上限检查位于展开**之后**（`xdebug/src/waveform/filter/value_filter.cpp:30`、`xdebug/src/waveform/stream/stream_analyzer.cpp:50`）。
- **触发条件**：filter/match value 传 `1000000000'h1`（约 14 字节请求）。
- **影响**：引擎单次分配约 1 GB；重复请求可导致 OOM。属资源放大缺陷（跨信任边界输入未做前置约束）。
- **建议方向**：位宽用严格整数解析并做范围检查，在展开之前施加硬上限；`atoi` 全部替换为 fail-closed 解析。

### 6.0c XDEBUG-LOCK-01（P2，已证实）：session 生命周期锁阻塞且跨引擎启动，错误归因被合并

- **证据**：`xdebug/src/engine/session/session_lifecycle_lease.h:24-31` 使用无超时 `flock(LOCK_EX)`，失败静默返回；租约在 `src/engine/session/session_manager.cpp:597/738/771` 的 `ensure_session` 全程持有，覆盖 spawn 与 `wait_for_server`（默认 300 s，`xdebug/src/core/common/env_config.cpp:236-240`）；三种不同失败共用同一条 `lifecycle_lock_failed` 文案（`session_manager.cpp:598-601/970-976/1054-1058`）。
- **触发条件**：同名 session 的 open/close/gc 并发；或 HOME/锁文件创建失败。
- **影响**：第二个调用方在 CLI 内静默阻塞数分钟；环境错误被误报为锁竞争，误导排障方向（与仓库"失败必须可诊断"的既有规则冲突）。
- **建议方向**：改用 `LOCK_NB` + 有界重试；区分"锁被占用"与"锁文件不可用"两类错误码。

### 6.0d XDEBUG-SIGNAL-01（P2，已证实）：SIGTERM/SIGINT 处理器非 async-signal-safe

- **证据**：`xdebug/src/engine/server.cpp:181-191` 的处理器内调用 `log_lifecycle_event`（涉及 `std::mutex`、malloc 与文件 IO）、`close_fsdb_file`、`fclose`、`exit`；同文件 `:219-233` 的 SIGSEGV 处理器只做 `write` + `_exit`，两者风格不一致；注册点 `:1078-1080`；`xdebug/src/core/logging/action_log.cpp:60,196` 为不可重入互斥量。
- **触发条件**：SIGTERM 恰好打断持有 `g_log_append_mutex` 的 `append_event`（file transport 工作线程也会写日志）。
- **影响**：处理器内自死锁 → SIGTERM 无法终止引擎，调用方只能退化到 SIGKILL，留下未清理的 session 目录与锁文件。
- **建议方向**：处理器只置标志位或写自管道，实际清理回到主循环；与 SIGSEGV 处理器采用同一最小化风格。

### 6.0e XDEBUG-FILE-01（P2，已证实）：file transport 把"已存在响应"当作成功，真实结果静默丢弃

- **证据**：`xdebug/src/engine/server.cpp:649-653` 忽略 `file_exchange_complete_claim` 的返回值；`xdebug/src/core/transport/file_exchange.cpp:214-216` 的 `write_response` 遇 `EEXIST` 直接 `return true`（`EEXIST` 也可能来自 `fail_claim`/`scan_stale_claims`，见 `:258,604`）；`:474` 忽略 `move_file` 结果。
- **触发条件**：claim 超时（默认 600 s，`xdebug/src/core/common/env_config.cpp:177-185`）或写盘失败。
- **影响**：服务端认为已应答，客户端实际读到 stale/timeout，真实结果被静默丢弃；另 `responses/` 无 TTL（`:612-618` 只清 done/failed），客户端超时后残留文件永久累积。
- **建议方向**：区分 `EEXIST` 的来源；把 `complete_claim` 与 `move_file` 的失败上传为明确错误；为 `responses/` 增加 TTL 回收。

### 6.0f XDEBUG-LOG-01（P2，已证实）：公共日志 owner 目录无回收路径，随每次 CLI 调用单调增长

- **证据**：`xdebug/src/core/logging/action_log.cpp:632-645` 与 `:215-229` 每次进程生成新 owner（pid-nonce），`:771-790` 创建 manifest 与 logs 目录；全仓检索无删除 `owners/*` 的代码；`session.gc`（`xdebug/src/api/dispatcher.cpp:1405-1417`）只清理引擎 session，不涉及公共日志 owner。
- **实测**：本机 `~/.xdebug/sessions/adhoc_*/owners` 已有 128 个 owner、399 个 ndjson、约 6.7 MB（`~/.xdebug` 合计约 24 MB）。
- **影响**：HOME 下磁盘与 inode 随使用单调增长，长期运行机器会累积。
- **建议方向**：在 `session.gc` 或 open 路径按 TTL/数量清理 owner 目录，并把清理结果计入 gc 报告。

### 6.0g XDEBUG-DIAG-01（P2，已证实）：参数错误归因依赖英文消息子串匹配

- **证据**：`xdebug/src/engine/server.cpp:455-490` 依次匹配 `"end time is before begin time"` → `args.time_range.end`、`"Signal not found"` → `args.signal`、`"Invalid time"` → `args.time` 等，命中后填充 `invalid_arg`/`expected`/`correct_example`（`:502-504`）。
- **触发条件**：任一 handler 改写文案，或同一文案实际来自 clock/interface 等其它参数。
- **影响**：`invalid_arg` 指向错误字段，`correct_example` 进而误导 AI 客户端（本仓库的核心使用场景）。注：example 本身是数据驱动（`xdebug/src/core/schema/runtime_schema_validator.cpp:1665-1668` 读 `examples/requests/*.basic.json`），并非硬编码，问题只在"归因靠字符串"。
- **建议方向**：由 handler 直接返回结构化 `invalid_arg`，文案匹配只作为最后兜底。

### 6.0h XDEBUG-ATTR-01（P3，已证实）：`atoi` 静默错误值

- **证据**：`xdebug/src/engine/server.cpp:882`（`--port` 非数字→0）、`xdebug/src/main.cpp:313`（`--lines abc`→0 后回退 40，`10x`→10，见 `:329`）、`xdebug/src/waveform/stream/stream_expr.cpp:70`、`:392`（`sig[4294967296]` 经 `atoi` 截断为 0，静默选错位；越界检查在 `:128-129` 已太晚）。
- **影响**：用户输入被静默解释成另一个值，无任何提示。
- **建议方向**：与 `xdebug/src/core/common/env_config.cpp:24-31`（已正确使用 `strtoll` + `errno` + 尾字符校验）保持一致，统一 fail-closed 解析。

### 6.0i XDEBUG-CACHE-01（P3，已证实）：内存回收路径为 O(n²) 且可能被报成请求超时

- **证据**：`xdebug/src/waveform/cache/analysis_repository.cpp:272-284` 的 `erase_one_releasable_metadata` 每次线性扫描 tombstone 取最小值；`:408-414` 的 `make_hard_room` 循环反复调用并在内部执行 `request_deadline_checkpoint()`。
- **触发条件**：`charged_bytes` 逼近硬上限且 tombstone 较多。
- **影响**：回收期间出现长停顿；checkpoint 抛出后请求被报成 `ENGINE_TIMEOUT`，掩盖真实的内存压力原因。
- **建议方向**：按 `access_sequence` 维护有序淘汰结构；回收触发的超时使用可区分的错误文案。

### 6.0j XDEBUG-DUP-01（P3，已证实）：同一解析/释放逻辑重复实现两份

- **证据**：`xdebug/src/combined/active_trace_common.h:240-297` 与 `xdebug/src/combined/active_trace_service.cpp:385-442` 为近乎逐行相同的手写 `npi_release_handle` 序列（inst/port_iter/port/highconn 各分支）。
- **影响**：任一份改动而另一份未同步时，出现泄漏或重复释放；维护成本翻倍。
- **建议方向**：抽成单一 RAII 复用函数。

### 6.0k XDEBUG-SCOPE-01（P2，疑似/需验证）：`ActionResourceScope` 无 owner 去重，存在重复 release 风险

- **证据**：`xdebug/src/engine/service/action_resource_scope.h:35-57` 的四个 `own_*` 仅 `push_back`，无去重与唯一性断言；`xdebug/src/design/hierarchy/relationship_walker.cpp:155-157`（`visit_scope` 内的 interface）与 `:102-103`（`visit_interface_relations`）对同一 interface scope 各调用一次 `own_npi(npi_handle(npiInstanceArray, scope))`。
- **未验证点**：若 NPI 对同一对象两次 `npi_handle` 返回相同指针，析构（`xdebug/src/engine/service/action_resource_scope.h:18-33`）会对其 release 两次。是否真会返回相同指针需在真实 design 上实测（本次未运行 NPI，故列为疑似）。
- **建议方向**：`own_*` 内做指针去重，或把 owner 唯一性写成显式断言并在 CI 的可运行环境中触发。

### 6.0l XDEBUG-STDIO-01（P3，已证实）：stdio loop 在 stdout 写失败后继续执行

- **证据**：`xdebug/src/api/stdio_loop.cpp:333-338` 的 `write_jsonl` 失败仅记录日志，不 `break`/`return`；循环继续读 stdin 并分发（后续响应全部丢弃）。
- **影响**：下游管道关闭后仍继续执行昂贵查询，结果静默丢失。
- **建议方向**：写失败即退出并在日志中给出终止原因。

### 6.0m XDEBUG-OBS-01（P3，已证实，仅影响可观测性）

- **证据**：`xdebug/src/waveform/cache/analysis_repository.cpp:880-884` 在 index 发布被内存拒绝时仅 `erase`，不发出 `build_failed` 事件；对照 `:697-700`、`:757-759`、`:933-936` 均有事件。
- **影响**：生命周期日志缺少 index 级构建失败信号，排障时看不到该分支。
- **建议方向**：与其它发布路径对齐，补发事件。

### 6.0z XCOV-NAME-01（P1，已证实）：功能性覆盖过滤可触发 `NameError`

- **证据**：`xcov/xcov/backend.py:1962`
  ```python
  if group_filter is not None and name not in group_filter and full_name not in group_filter:
      return
  ```
  同一函数内 `full_name` 直到 `:1968` 才被赋值，因此 `:1962` 的 `full_name not in group_filter` 在到达时属于**未绑定局部变量引用**。
- **可达性**：`group_filter` 由 `xcov/xcov/backend.py:1310-1314` 的 `functional_items_filtered(covergroups, ...)` 传入（非 None）。仅当 `name not in group_filter` 为真（即请求过滤的子集不含当前 covergroup）时才会求值 RHS，命中即抛 `NameError`；当 `group_filter is None` 时被短路，故常规路径掩盖了该缺陷。ruff `F821` 独立报出同一位置。
- **触发条件**：对 coverage VDB 调用按 covergroup 过滤的功能覆盖查询，且存在不在过滤集合内的 covergroup。
- **影响**：查询以 Python 异常终止（而非结构化 `xcov` 错误码），属产品级错误结果/不可用。
- **建议方向**：把 `full_name` 的解析提前到过滤判断之前，或在过滤分支内就地使用 `name`；并补一条"过滤集合为真子集"的回归用例（当前测试未覆盖该路径，否则不会漏过）。

### 6.0za XCOV-DEAD-01（P2，已证实）：`xcov/xcov/actions.py` 存在重构残留的不可达代码

- **证据**：`xcov/xcov/actions.py:2558-2571`
  ```python
  def _export_output_path(args: Json) -> str:
      ...
      return resolve_artifact_path(...)
      if file_name and line is not None:      # 不可达
          return f"{file_name}:{line}"
      if file_name:                            # 不可达
          return str(file_name)
      return ""                                # 不可达
  ```
  以及 `:2595` 的 `return {"evidence": ev}` 同样位于 `return` 之后、且 `ev` 未定义。
- **影响**：无运行时影响（不可达），但会把两个真实缺陷（4 处未定义名）长期隐藏在 lint 报告里，并让读者误判 `_export_output_path` 的返回语义；未来若有人把 `return` 上移即立刻变成崩溃点。
- **建议方向**：删除残留分支；若 `file:line` 拼接仍需保留，应作为独立 helper 并在别处显式调用。建议把 `ruff --select F821` 纳入 `fast` 门禁，防止同类回归。

### 6.3 ENTRY-PY-01（P2，已证实）：Python 工具 wrapper 在默认解释器下全部崩溃，且报错不可诊断

- **证据**：`tools/xbit`、`tools/xentry`、`tools/xloc`、`tools/xsva`、`tools/xwaveform` 均使用 `python_bin="${PYTHON:-python3}"`（例如 `tools/xbit:7`）。本机 `/bin/python3` 为 **3.6.8**，而这些包的源码普遍使用 `from __future__ import annotations`（3.7+），且 `requires-python` 声明为 `>=3.10`（`xbit/pyproject.toml`、`xsva/pyproject.toml`、`xcov/pyproject.toml`、`xwaveform/pyproject.toml`）。
- **实测**：5 个 wrapper 全部以 `SyntaxError: future feature annotations is not defined` 崩溃（栈顶指向 `xbit/src/xbit/bitvector.py:1` 等）；显式 `PYTHON=<repo>/.conda-xverif/bin/python` 后 `tools/xbit conv 8'shff` 返回 `@xbit.conv.v1`、`tools/xsva list ...` 正常。
- **根因**：wrapper 只校验"解释器是否存在"（`command -v`），不校验版本；版本不符时把解释器的语法错误原样抛给用户，没有任何"请设置 `PYTHON` 或激活 conda"的提示。
- **附带文档漂移**：`README.zh-CN.md:246` 声称"xbit/xentry/xloc 支持 3.6+"，与实际源码（需要 3.7+，声明 3.10+）不符；`xentry/`、`xloc/` 甚至没有 `pyproject.toml`，声明无处可查。
- **影响**：新用户按 README 走"把 `tools/` 加入 PATH"（`README.zh-CN.md:199-224`）后，5 个工具**全部不可用**，且错误信息会把问题误导到"代码有语法错误"。
- **建议方向**：wrapper 增加解释器版本检查（`sys.version_info >= (3, 10)`）并给出明确修复指引（不得静默 fallback 到其它解释器）；同步修正 README 的版本表格，为 `xentry`/`xloc` 补 `pyproject.toml`。

### 6.4 REPO-GATE-01（P2，已证实）：`fast` 门禁当前为红，阻塞在工作树既有的未跟踪文档

- **证据**：`pytest --xverif-gate fast` 全量结果为 **667 passed / 1 failed**；失败项是 `testinfra/tests/test_completeness.py:222` 的 `test_repository_has_no_machine_specific_local_paths`，报出 40 条本机绝对路径违规。
- **违规分布（本次实测统计）**：`doc/WAVE_MCP_XVERIF_REVIEW_2026-09-04.md` 2 条、`doc/XDEBUG_NPI_DEMO_COMPARISON_REPORT_2026-09-18.md` 16 条、`doc/XDEBUG_NPI_SESSION_100_COMPARISON_REPORT_2026-09-18.md` 19 条、`doc/XDEBUG_VERIFICATION_CODE_NAVIGATION_SPEC_2026-09-18.md` 3 条。四份均为**未跟踪新增**文件，即该红灯在本次审查开始前既已存在。
- **影响**：这是当前工作树唯一的门禁红灯，直接阻塞任何"提交前必须跑通关联测试"的提交动作；也说明文档写作流程没有在落盘后自动跑门禁。
- **建议方向**：按 `AGENTS.md` 既有约定把本机绝对路径改写为 `$HOME`/仓库相对路径/占位符（本报告自身已按该规则处理，且经 `testinfra.unit` 验证不再触发该断言）；若确有需要逐字固化路径的证据文档，应走 `testinfra/tests/test_completeness.py` 中 `EXACT_RUNTIME_EVIDENCE_PATHS` 的显式白名单，而不是绕过门禁。

### 6.5 XCOV-EXPORT-DOC-01（P2，已证实）：导出 action 的公开文本与实际产物不一致

- **证据**：`xcov/xcov/actions.py:159` 声称 `export.functional_coverage` 用于 "Write detailed functional-coverage holes to a **Markdown** artifact"，`:164` 对 `export.assert` 同样声称 Markdown；但 `xcov/xcov/gap_export.py:188-192` 实际只写 `f"{metric}.json"` 与 `f"{metric}.xout"`（TSV 载荷），全目录 `grep` 无任何 `.md` 产物构造。
- **加重项**：`xcov/docs/action-xout-examples.md:261,265` 给出的可复制示例把 `output.path` 写成 `functional_coverage.md` / `assert.md`，会诱导用户按不存在的格式预期调用。
- **影响**：action 目录文本（进入 AI 的 action 选择依据）与真实行为不符，属合同级漂移；用户按示例命名产物会得到与预期不同的内容格式。
- **建议方向**：二选一——要么修正 action 文案与示例为实际格式（推荐，改动小），要么实现 Markdown 产物。`xcov/xcov/actions.py` 的 `use_when` 文本同时是 MCP `xverif_cov_list_actions` 的输出源，因此该漂移会直接进入 AI 上下文。

### 6.6 SESSION-MIGRATE-01（P2，已证实，操作性陷阱）：legacy registry 的报错指引自相矛盾

- **证据**：`xdebug/src/engine/session/session_registry.cpp:118-122` 在发现旧格式 `~/.xdebug/engine/registry.json` 非空时返回：
  `REGISTRY_MIGRATION_REQUIRED: close or gc every legacy session with the old binary before upgrading`
  而该检查位于 `read_one`（`:143`）与 `load_all`（`:171`）的入口，即**新二进制在 registry 非空前无法服务任何 session 动作**，包括它建议的 `close` / `gc`；同时新 registry 只枚举每会话 `state.json`（`:185`），旧记录不会迁移。
- **实测**：本机 `~/.xdebug/engine/registry.json` 为 v2 格式、16 条 `lifecycle_state=active` 记录，`server_pid` 全部已不存在（进程已退出）、且 `fsdb_file` 全部指向旧仓库 `xdebug_oc`。按提示调用任何 session 动作都会失败；实际可行路径只有手工归档 registry 文件（本次审查中已备份为 `registry.json.legacy-v2.bak.20260920-103409` 后置空，新引擎随即自动改名为 `.v3.retired`）。
- **影响**：升级/换机场景下 `session.open` 会以误导性错误彻底失败，用户按提示操作无法自救；所有客户端（含 MCP 与另一个 agent 进程）同时受影响。
- **建议方向**：错误信息给出可执行的迁移入口（例如明确说明"新二进制无法读取旧 registry，请归档 `registry.json` 后重试"或提供 `session.registry.retire` 之类的显式动作）；`session.gc` 应在 registry 校验之前可用；文档（`doc/agents/xdebug/sessions.md`）补充该升级路径。

### 6.7 BUILD-PY-01（P2，已证实）：`make -C xdebug` 链路绑定系统 `python3`，与仓库实际解释器要求冲突

- **证据**：`xdebug/Makefile:24` `PYTHON ?= python3`；该变量被用于 `xdebug/tools/sync_action_metadata.py`（`:247`）、`xdebug/tools/sync_help_text.py`（`:252`）、`xdebug/tools/check_npi_toolchain.py`（`:268`）。三个脚本都使用 `from __future__ import annotations`。
- **实测**：裸 `make -C xdebug npi-toolchain-check` 在本机以 `SyntaxError: future feature annotations is not defined` 失败（系统 python3=3.6.8）；`make -C xdebug npi-toolchain-check PYTHON=<repo>/.conda-xverif/bin/python` 输出 `NPI_TOOLCHAIN_OK cxx11_abi=1`。
- **加重项**：本次未提交改动把 `npi-toolchain-check` 挂成 `internal-engines` 的前置依赖（`xdebug/Makefile:273`；`all` 目标在 `:265` 依赖 `internal-engines`），因此**构建路径也一起受影响**，不再只是可选检查。
- **附带**：四处文档（`README.md:164`、`README.zh-CN.md:254`、`xdebug/README.md:98`、`doc/agents/xdebug/tests.md:147`）都建议直接运行 `make -C xdebug npi-toolchain-check`，没有任何一处提到 `PYTHON` 覆盖。
- **建议方向**：Makefile 显式校验解释器版本并给出指引；或在文档中明确 `PYTHON=<conda python>` 的调用形态。不建议静默探测 `.conda-xverif`（与仓库禁止隐式 fallback 的规则冲突），但**明确失败**是必须的。

### 6.8 MCP-BATCH-DIAG-01（P3，已证实，可用性）：batch 失败行的顶层 `error` 丢失诊断维度

- **证据**：`xverif_mcp/src/xverif_mcp/server.py:299-301` 在结构化失败时构造
  `_batch_error("TOOL_RESULT_ERROR", "MCP tool returned a structured failure result")`，`:327` 对 JSON 失败行构造 `"MCP tool returned ok=false"`。两者都不携带内部 `error_code`/`invalid_arg`。
- **实测（本次 MCP 实验）**：批处理中 3 个参数错误行的顶层 `error` 只有 `{"code":"TOOL_RESULT_ERROR","message":"MCP tool returned ok=false"}`，而完整诊断（`INVALID_REQUEST`、`invalid_arg`、`available_values`、`correct_example`、`validation_issues`）保存在同一行的 `response` 字段里。
- **更正说明**：我在实验阶段曾口述"batch 完全吞掉错误详情"，**该表述不准确**——详情在 `response` 中完好；准确的问题是**失败行的顶层 `error` 无法用于快速分类**，消费方必须解析 `response` 才能知道是哪个参数错。
- **建议方向**：失败行顶层补充 `inner_code`（从 `response` 提取的 `error.code`）等聚合字段，保持 `response` 原文不变。

### 6.9 XDEBUG-TRACE-LINE0-01（P3，已证实）：无法解析的行号静默变成 0

- **证据**：`xdebug/src/engine/service/trace_source_path_formatter.cpp:137-146` 的 `scalar_int()` 在 `std::stoi` 抛错或类型不符时 `return 0`；该函数有 8 处调用（`:339, :387, :616, :623, :681, :695, :743` 等），用于构造 trace 结果的 `file:line` 证据。
- **影响**：当上游给出非法/非数值行号时，证据会显示为 `file:0` 而不是标记未知；AI 与用户可能把第 0 行当作真实位置。属证据质量问题，不改变波形数值结论。
- **建议方向**：返回可空值并在渲染层输出 `line_unknown`（与仓库既有的 `Observed<T>`/完整性字段风格一致），而不是用 0 填充。

### 6.0n XCOV-WORKDIR-01（P2，已证实）：xcov 自有 session 工作目录在 kill/force/EOF 路径永久泄漏

- **证据**：`xcov/xcov/session.py:255-263` 用 `tempfile.mkdtemp(prefix=f"{safe_sid}.", dir=<cache_root>/sessions)` 建目录并置 `cache_owned_by_session=True`；删除它的**唯一**位置是 `xcov/xcov/session.py:57-66`（`XcovSession.close()`）与失败回滚 `:301-308`。kill 不经过它：`xverif_mcp/src/xverif_loop/sessions/capabilities.py:47` 中 xcov 的 `native_kill_action=None`，`xverif_mcp/src/xverif_loop/sessions/loop_session.py:818-820` 在 force 时把 `backend_close/stdio_quit` 标为 `force_skipped`；`xcov/xcov/cli.py:115-130,156` 收到 `stdio.quit` 或 stdin EOF 直接 `return 0`，全树无 `atexit`、无 `sessions/` 清理器。
- **触发条件**：`xverif_cov_session_kill`、`xverif_debug_session_close(mode="force")`，或 MCP server 非优雅退出后 loop 读到 EOF 自退。
- **影响**：`<cache_root>/sessions/<sid>.<rand>/`（含 current.el 等）永久残留，无 gc、无上限，磁盘单调增长。
- **建议方向**：工作目录所有权收敛到进程级生命周期（EOF/quit 分支显式关闭活动 session），或在响应中如实标注"工作目录保留"。

### 6.0o XCOV-CLOSE-01（P2，已证实）：`NpiCoverageBackend.close()` 非幂等，重试可 double-free

- **证据**：`xcov/xcov/backend.py:1160-1183` 无 `_closed` 守卫，`locator_handles.clear()` 位于 release 循环之后，`self.db`/`self.npisys` 从不置空，异常时 `finally` 仍执行 `npisys.end()`；`xcov/xcov/session.py:330-341` 中 `sess.close()` 抛错会跳过 `self.sessions.pop()`，session 仍保持 `state="alive"`。
- **触发条件**：首次 close 在 `database.close` 或某个 `cov.release_handle` 处抛错后用户重试。
- **影响**：二次 release 已释放句柄、二次 `npisys.end()`（NPI 可能崩溃或挂死）；session 永久占用容量（native stdio-loop 每进程仅允许 1 个 live session），导致无法 reopen。
- **建议方向**：close 幂等化（先置位并摘除句柄表，`try/finally` 保证 `npisys=None`）；失败时把 session 移出 `self.sessions`，避免"半关闭"状态可被重试。

### 6.0p XCOV-LSF-01（P2，已证实代码路径；真实 LSF 行为待验证）：`_run_lsf` 启动判据被 job-id 帧二次门控

- **证据**：`xcov/xcov/urg_runner.py:343-349` 仅当匹配 `_JOB_RE`（`Job <N> is submitted`）才置 `job_event`；`:351-361` 的注释声称"首个非调度器输出即可作为 dispatch 证据"，但实现是 `if job_event.is_set() and stripped: started_event.set()`——兜底再次被 `job_event` 门控；`:370-379` 未置位即按 `startup_timeout` 处理并 `bkill`，返回 124。
- **触发条件**：站点 `bsub` 包装器既不输出 job-id 帧也不输出 `<<Starting on>>`，而作业实际已提交执行。
- **影响**：健康 URG 作业被判失败并被 bkill；默认 `startup_timeout=120s`，每次冷缓存都白等后失败，cache 永不填充。
- **建议方向**：把"首个非调度器输出"兜底与 `job_event` 解耦；`startup_timeout` 区分"已 dispatch 但无帧"与"未 dispatch"两种语义。
- **边界**：本次未运行真实 LSF，故 A3 的站点行为未实测，仅代码路径已证实。

### 6.0q XCOV-CACHE-02（P3，已证实）：URG cache 软容量可被并发突破，`quarantine/` 无回收

- **证据**：`xcov/xcov/urg_cache.py:243-251` docstring 自述 distinct-key 并发会 oversubscribe；`:271-274`、`:321-326` 把冲突条目与陈旧 claim 移入 `quarantine/`；全树仅 `xcov/tests/test_urg_summary.py:232` 读取该目录，无裁剪逻辑。
- **影响**：`XCOV_CACHE_CAPACITY_EXCEEDED` 在多进程下失效；quarantine 单调增长且无观测入口。
- **建议方向**：admission 采用"快照 + 本进程预留"，或在合同中显式发布软上限语义；为 quarantine 增加计数与显式维护入口。

### 6.0r XCOV-VALIDATE-01（P3，已证实为防护缺口，当前无实际漂移）：启动校验只覆盖 action 名

- **证据**：`xcov/xcov/actions.py:239-242` 仅校验 `set(ACTION_REGISTRY) == set(schema_actions())` 与 `name == contract.name`；不校验 handler 可解析、`needs_session` 与 request schema 的 target 约束是否一致、request/response 条目是否齐全。
- **当前状态**：静态核验 30/30 handler 存在、30 个 schema 均含 request+response，无实际漂移。
- **影响**：未来新增/改名 action 只改一处（handler 名拼错、schema 缺 response）时 import 期静默通过，运行时退化为 `INTERNAL_ERROR`/`KeyError`。
- **建议方向**：启动期做结构化审计（handler 可解析、request/response 存在、`needs_session` ↔ target 一致），fail-closed。

### 6.0s MCP-REQID-01（P2，已证实）：常量 `request_id` + `pending` 缓存导致超时重试拿到陈旧响应

- **证据**：`xverif_mcp/src/xverif_loop/lsf/protocol.py:305-310` 先 `pending.pop(request_id, None)`，命中即返回；`:363-365` 把 id 不匹配的响应存入 `pending`；生命周期请求 id 按 alias 恒定（`xverif_mcp/src/xverif_loop/sessions/loop_session.py:521-525` `open-<alias>`、`:753` `close-<alias>`、`:803` `quit-<alias>`、`:889-896` `doctor-<alias>`）；`:897-903` 中 doctor 超时只记 `DOCTOR_TRANSPORT_FAILED` 且不 abort。
- **触发条件**：任一生命周期调用超时，其响应稍后被任意读操作收进 `pending[同一常量 id]`；随后重试同一操作（典型是 doctor 超时后再 doctor）。
- **影响**：重试不等待、直接返回上次响应——doctor 报旧状态、close 报旧结果，真实响应被后续请求错配消费。
- **建议方向**：request_id 单调化（沿用 query 的 `alias-<seq>`），或超时时清理同 id pending，或加时间戳禁止跨调用复用。

### 6.0t MCP-GC-01（P2，已证实）：`gc_sessions` 脱离会话锁读写 `state`，与并发 kill/close 交错会把孤儿会话记成 closed

- **证据**：`xverif_mcp/src/xverif_loop/sessions/session_manager.py:695-719`（tombstone 循环 `:697-698` 无锁读 state；活动会话 `:708` 读、`:713` 直接写 `state="closed"`、`:714` 驱逐）；对照 `xverif_mcp/src/xverif_loop/sessions/loop_session.py:965-975`（kill 在 `_lifecycle_lock` 内置 `terminating` 并清 handle）与 `:1039-1048`（kill 失败写回 `orphan_suspected`/`cleanup_partial`）、`xverif_mcp/src/xverif_loop/sessions/session_manager.py:616-636`（正常路径在 manager 锁内置状态）。
- **并发来源**：`xverif_mcp/src/xverif_loop/wrapper.py:777-788` 每个 UDS 连接起一个线程，共享同一 manager。
- **触发条件**：一个连接正在 kill/close，另一连接调用 gc；gc 读到 `alive` 后 kill 已清空 handle，gc 的 `process_alive()` 因 `handle is None` 返回 False，于是判死、写 closed 并驱逐。
- **影响**：真实的 `orphan_suspected` 被覆盖为 closed tombstone；`has_live_or_unresolved_sessions()`（`xverif_mcp/src/xverif_loop/sessions/session_manager.py:360-367`）转 False，wrapper 可能 idle 退出，孤儿 LSF job/句柄不再被 list/gc 暴露。
- **建议方向**：gc 的状态读改写统一进会话生命周期锁，并把"判死 + 写 closed + 驱逐"做成带 `expected_generation` 的单临界区 CAS。

### 6.0u MCP-KILLPG-01（P2，已证实；孤儿真实性取决于子工具是否 fork）：三处终止路径不保证进程组回收却统一报成功

- **证据**：① `xverif_mcp/src/xverif_loop/lsf/protocol.py:384-411` 先 `poll()` 再 `os.getpgid(self.proc.pid)`，leader 在两步之间被 reap 会触发 `ProcessLookupError` 并退化为对已回收进程 no-op 的 `terminate()`，而 `:425-431` 仍返回 `{"ok":True,"status":"terminated"}`（与 `:403` 注释声称的"不孤儿化 child engines"矛盾）；② `xcov/xcov/urg_runner.py:238-246` 直连路径 `subprocess.run(timeout=)` 只杀直接子进程，对照 `:314-323` 的 LSF 路径（`start_new_session=True` + `_cleanup_lsf` 的 killpg）；③ `xverif_mcp/src/xverif_mcp/runner.py:128-140` 同样只有直接子进程语义，超时返回 `timed_out` 且无 cleanup 记录。
- **影响**：孤儿进程（持有 report 目录与 stdout 管道）被当作"已确认清理"，并沿 `cleanup_complete=True` 写 tombstone 且不再重试；直连路径还丢失超时时的部分 stdout 诊断。
- **建议方向**：缓存 pgid 并对 pgid 调用 killpg；把 `ProcessLookupError` 区分为 `group_gone` 与 `leader_reaped`，不得直接判成功；直连路径补进程组隔离。

### 6.0v MCP-DOCTOR-01（P2，已证实）：request lane 忙时 doctor 把健康会话报成 `unresolved=true`

- **证据**：`xverif_mcp/src/xverif_loop/sessions/loop_session.py:897-910` 在 `_request_lock.acquire(blocking=False)` 失败且 `capability.fixed_admin_path=False`（xcov，见 `xverif_mcp/src/xverif_loop/sessions/capabilities.py:42-56`）时只置 `source="request_lane_busy"`、`backend_response=None`；`:914-919` 据此推出 `unresolved = (state=="alive" and not backend_ok)` 为 True。
- **触发条件**：xcov 长查询占住 lane（最长 `request_timeout_sec=360s`）期间调用 `xverif_cov_session_doctor`——恰是排查长查询的典型操作。
- **影响**：`unresolved` 是 agent 决定 kill/gc 的主要判据，假阳性会把健康 session 推进 kill，并顺带触发 6.0n 的工作目录泄漏。
- **建议方向**：lane 忙时输出 `backend_health_known=false`，`unresolved` 保持"未知"语义，不折叠为布尔判定。

### 6.0w MCP-FAKE-01（P3，已证实为覆盖盲区）：fake bsub 与真实 `bsub -I` 语义差异

- **证据**：`xverif_mcp/src/xverif_loop/lsf/fake_bsub.py:51-61` 仅在 `FAKE_BSUB_STDOUT_NOISE_BEFORE_READY` 打开时打印 job-id 帧（硬编码 id），默认既无 job-id 帧也无 `<<Starting on>>`；`:77-99` 用本地 `Popen` 且收 SIGTERM 即终止（真实 LSF 为远端执行 + bkill）；`xverif_mcp/src/xverif_loop/lsf/bsub.py:16-21` 的 `<<Job is finished>>` 帧 fake 从不产生；`-env all` 仅在 `FAKE_BSUB_REQUIRE_ENV_ALL`（`xverif_mcp/src/xverif_loop/lsf/fake_bsub.py:37-45`）下校验。
- **影响**：job_id → `bkill <id>` 链路、`-env all` 前置校验、finished 帧处理在真实 LSF 下缺少等价覆盖；fake 的"本地 SIGTERM 必成功"会掩盖 `job_identity_missing` 与 bkill 竞态类缺陷（与 6.0p 直接相关）。
- **建议方向**：让 fake 默认采用真实形态（默认输出 job-id 帧，噪声改为显式开关），并补一条"完全不打印帧"的 negative 用例来验证 6.0p 的兜底。

### 6.0x MCP-OSERR-01（P3，已证实）：`StatelessCliRunner` 丢弃 `OSError` 类型信息

- **证据**：`xverif_mcp/src/xverif_mcp/runner.py:141-142` 的 `OSError` 分支返回含 `error_type` 的字典，但 `:50-61` 只按 stdout/exit_code 分类，`xverif_mcp/src/xverif_mcp/errors.py:16-23` 因此生成 `XVERIF_CLI_FAILED`（`exit_code=-1`），`error_type` 从未被读取。
- **触发条件**：`default_tool_path()` 指向的 `tools/<tool>` 缺失或不可执行（未构建、被并发链接占用）。
- **影响**：无法区分"二进制缺失 / 无执行权限 / 环境未就绪"，与仓库"失败可诊断"合同不一致（也与 7.3 的 wrapper 问题同源）。
- **建议方向**：为 `OSError` 单独返回结构化错误，或在 `cli_failed` 中透传 `error_type`。

### 6.0y MCP-SCHEMA-01（P3，已证实为重复真源，当前无漂移）：session 工具投影与真实签名无自动一致性校验

- **证据**：`xverif_mcp/src/xverif_mcp/schema_projection.py:21-45` 手写 5 个 session 工具的 properties/required，`:214-231` 的 `_session_projection` 完全忽略传入的 `native` schema；真实签名在 `xverif_mcp/src/xverif_mcp/server.py:693-741`（debug）与 `:929-987`（cov）。逐条比对当前一致。
- **影响**：任一侧新增/改名/改默认值而未同步手写表时，`xverif_debug_get_schema(action="session.*")` 会发布工具实际拒绝（`extra=forbid`，`xverif_mcp/src/xverif_mcp/server.py:213-217`）或语义不同的形状。
- **建议方向**：投影改为从受校验的单一真源派生，或在 import 期断言投影与工具签名一致。

### 6.10 XSVA-SEM-01（P1，已证实，主线程复现）：高级 sequence 语义静默丢失 obligation，却仍报 `exact`/`complete`

- **证据**：`xsva/xsva/lower/sequence_to_timeline.py:253-260` 的分派只有 `EXPR`/`MATCH_ITEM` 会产出 obligation，兜底分支对 REPEAT（以及 AND/OR/STRONG/WEAK/OPAQUE）**既不产出 obligation 也不降级 status**；`:77-88` 一旦 `has_first_match_summary` 为真就把 `paths` 置为 `[[]]`；`:242-257` 对 INTERSECT/FIRST_MATCH/THROUGHOUT/WITHIN 只置 partial、不下降 children。
- **主线程复现**：输入 `req |-> ack[*3] ##1 done;`
  - `xsva explain` 输出 `Lowering status: exact`、`Path enumeration: 1/1 (complete)`，但正文**只有一条 note**（`ack needs to hold continuously for 3 clk cycles.`），没有任何 obligation 列表。
  - `xsva parse --emit timeline-ir` 的 `obligations` 只有一条 `done`，`failure_condition` 为 `"done is false at cycle +1"`；SVA 语义下 `ack[*3] ##1 done` 要求 `ack` 连续 3 拍后再过 1 拍，正确位置至少是 `+3`。`ack[*3]` 本身**完全消失**。
- **触发条件**：consequent 含 `[*N]`/`[->N]`/`[=N]`、`first_match`、`intersect`、`throughout`、`within`。
- **影响**：机器消费方（MCP/agent）得到"分析完整 + 待检查项齐全"的结论，但 obligation 缺失或拍号错误；`skills/xverif/references/xsva.md:18-24` 正指导 agent 据此做波形取证，会直接导致错误的时序结论。
- **加重项**：`xsva/xsva/xout.py:79-93` 与 `xsva/xsva/explain/markdown.py:49-59` 采用 `if semantic_notes: 打印 notes; else: 打印 obligations`，而 `xsva/xsva/lower/sequence_to_timeline.py:463-466` 几乎总为每个 property 生成一条 summary note —— 于是**obligation 列表在人类可读输出中永不显示**，该缺陷对用户完全不可见。`xsva/xsva/lower/path_expand.py:125` 的 `expand_first_match` 因短路永不可达；`xsva/tests/semantics/test_timeline_semantics.py:139,157` 用 `assert not timeline.obligations` 把错误行为锁成了期望值。
- **建议方向**：REPEAT 与高级构造至少降级为 `partial` 并交出可表达的 obligation；`first_match` 短路只应作用于其子树，后缀 obligation 必须保留；增加"`exact` 且 obligations 为空"的合同断言；修正被锁死的测试期望。

### 6.11 XSVA-HANG-01（P1，已证实，主线程复现）：畸形 SVA 触发无限循环，CLI 永久挂死

- **证据**：`xsva/xsva/parser/property_parser.py:73-77` 的 `while self._scanner.peek().kind != RPAREN: arg_tk = self._scanner.advance()`；`xsva/xsva/parser/scanner.py:257-258` 在 EOF 处 `advance()` 永远返回 EOF 且不推进 `_pos`。同型第二处为 `xsva/xsva/parser/property_parser.py:380-388` 的 `disable iff (` 收集循环（`depth > 0` 永不递减）。
- **主线程复现**（8 秒超时）：
  - `property p2 (sig`（属性参数缺右括号）→ `rc=124`，**输出 0 字节**；
  - `@(posedge clk) disable iff (rst_n a |-> b;`（缺右括号）→ `rc=124`，输出 0 字节；
  - `xsva list` 走 `list_properties()`，`rc=0` 正常（与审查结论一致）。
- **影响**：CI 与 agent 调用**永久阻塞**，且无任何输出与退出码可归因——比崩溃更难诊断，在没有外层超时的流水线里会挂死整个任务。
- **建议方向**：`Scanner.advance()` 在 EOF 时置位终止标志，所有 `while` 循环改为"无进展即报错"；对括号嵌套深度设显式上限并输出 typed diagnostic（审查单元另实测 600 层括号可触发 `RecursionError`，`xsva/xsva/cli.py:590-592` 把它降级为退出码 5）。

### 6.12 XSVA-ANT-01（P1，已证实）：antecedent 的 `##` 延迟被压平成单拍合取，status 仍为 `exact`

- **证据**：`xsva/xsva/lower/sequence_to_timeline.py:94-115` 只对 `SeqNodeKind.EXPR` 拼接 `&&`，DELAY 节点被无条件跳过，`:99-101` 还是一段 `pass` 空操作。
- **触发条件**：`a ##1 b |-> c` → `trigger.expr = "a && b"`；`a ##2 b ##3 c |-> d` → `"a && b && c"`，两者 `lowering_status` 均为 `exact`。而 SVA 语义要求 `a` 在 T-3、`b` 在 T-1、`c` 在 T。
- **影响**：任何按 `trigger.expr` 采样波形的消费方都会在**错误的拍**上取值并自认 `exact`；antecedent 的总时长信息完全丢失。
- **建议方向**：trigger 保留逐拍结构（或明确规定"trigger 只是合取摘要"并降级 status）。

### 6.13 XSVA-DIAG-01（P2，已证实）：诊断体系整体失效，error 不影响退出码/状态，码表与实现不一致

- **证据**：`xsva/xsva/ir/diagnostics.py:26-27` 的 `has_errors()` 全仓无调用者（`xsva/xsva/cli.py:181` 只看 `lowering_status == EXACT`）；`xsva/xsva/cli.py:267-317` 的 `cmd_lint` 缺少 `cmd_explain`/`cmd_parse`（`:320-326,353-359`）那样的 `try/except`，`xsva/xsva/parser/scanner.py:376-382` 抛出的裸 `ValueError` 会直达 `main()` 兜底。码表不一致：`xsva/xsva/parser/sequence_parser.py:279,290,307,312,318,321` 发射 `"SVA-E003"`，而 `xsva/xsva/lint/rules.py:37` 声明的是 `"XSVA-E003"`（且语义写成 "Unbalanced parentheses"，与实际用途 "invalid delay value" 不符）；`xsva/xsva/lower/sequence_to_timeline.py:129,136` 的 `XSVA-L001/L002` 无处声明；`W008/W010/E001/E004` 声明了但永不产生；`xsva/xsva/lint/rules.py` 无任何 import（`rule_message`/`rule_severity` 为死代码），诊断文案在 `xsva/xsva/lint/vacuity.py:22,31,39` 与 `xsva/xsva/lint/temporal.py:29,37` 各抄一份。
- **实测**：`a |-> ##b c` → `rc=0`、`Lowering status: exact`，同时携带 `[error] SVA-E003`；`a |-> ##[1:3 b` 经 lint → `rc=5`（声明的 parse error 应为 1）；非 UTF-8 文件经 `xsva/xsva/cli.py:78-84` 不被 `except OSError` 捕获，同样退化为 5。
- **影响**：解析/降级错误不会反映在退出码、`lowering_status` 与 `analysis_complete` 上，自动化消费方无法据此判断结果是否可信。
- **建议方向**：error 诊断必须参与 status/退出码/completeness；码表收敛为单一 source of truth 并加"声明码 == 发射码"的合同测试；`cmd_lint` 与其它命令共用同一异常转换。

### 6.14 XBIT-ERR-01（P1，已证实，主线程复现）：xbit/xentry 的错误路径自身会抛，工具报错时 traceback 且 stdout 为空

- **证据**：`xbit/src/xbit/format.py:182` 的 `failure()` 末尾仍调用 `validate_response(response, expected_op=op)`；`:139` 要求 `response["op"] in OPS`，而 `:13-17` 的 `OPS` **不含 `agent`**；`:145-146` 要求 `error.code`/`message` 均为非空 str。`xbit/src/xbit/cli.py:221` 在 `except` 内调用 `failure(exc, op=getattr(args, "command", None))`，而 `agent` 子命令的 op 正是 `"agent"`；`xbit/src/xbit/agent/stdio.py:145-153` 同样在 `except` 内调用 `failure()`。xentry 同源：`xentry/src/xentry/format.py:166` 的 `error_response()` 末尾调用 `validate_response(...)`，而 `xentry/src/xentry/config.py:110` 在 name 校验（`:111-115`）**之前**就取 `field=raw.get("name", "")`（可为 `""` 或非 str），`xentry/src/xentry/cli.py:88` 又在 `except` 内调用它。
- **主线程复现**：`printf '{"method": 5}\n' | python -m xbit.cli agent serve --stdio` → **未捕获 traceback**（`xbit/src/xbit/agent/stdio.py:147 → :78 → :41`），进程 `rc=1`。
- **影响**：一行坏 JSON 打死 stdio 服务（后续请求全部丢失）；CLI 从"结构化错误"退化为"traceback + 空 stdout"，违反 `xbit/README.md:193` 的"一行 JSON 进、一行 JSON 出"，MCP 侧因此拿不到 `error.code`。
- **建议方向**：确立"错误路径永不抛"不变量——`failure()`/`error_response()` 做成 total（空 message 退化为异常类型名，op 仅允许白名单或省略，details 强制字符串化），并在错误发射外再兜一层裸 JSON。

### 6.15 XBIT-NUM-01（P1，已证实；4 个子例中 3 个已复现）：数值边界未短路或未按 SV 语义处理

- **B-2a 移位量无短路**：`xbit/src/xbit/ops.py:218-227` 先计算 `a.value << amount` 再 `& mask_value`（掩码在移位之后），缺少 `amount >= a.width → 0` 的短路。32 位 `-1` 的 amount 为 4294967295，将构造约 512 MiB 级中间整数（审查单元实测内存随 amount 线性增长）；而按 SV 语义结果本就是 0，无需构造。触发：`xbit eval "1 << -1"`。
- **B-2b unsized based literal 位宽不符 SV**：`xbit/src/xbit/literal.py:14-22` 对 `b/o/h` 用位数推导，只有 `d` 走 `max(32, …)`。**主线程复现**：`xbit eval "'hFF + 'h1"` → `result: 8'h0`、`width: 8`；而 IEEE 1800 §6.7.1 要求 unsized based literal 至少 32 位，正确结果应为 `32'h100`。
- **B-2c bitwise 未做 both-signed 符号扩展**：`xbit/src/xbit/ops.py:179-182` 用 `a.resize(width)`/`b.resize(width)`（`xbit/src/xbit/bitvector.py:93` 的 `signed_extend` 默认 False），与 `xbit/src/xbit/ops.py:11-23` 自己声明的"两侧均有符号则做符号扩展"相矛盾。实测 `8'sh80 & 16'sh8000` → `0x0`，SV 应为 `0x8000`。
- **B-2d xwaveform 解析不了自家 xdebug 的合法产出**：`xwaveform/src/xwaveform/render.py:141` 对未知单位直接 `float(raw)` 转换，而 `xwaveform/src/xwaveform/render.py:206` 用它解析 manifest 的 `end`；生产侧 `xdebug/src/engine/service/actions/waveform/list_export.cpp:74` 明确以 `allow_max=true` 解析并原样写入 `"max"`。实测 `_parse_time_spec("max", 1000)` → `ValueError`、`("inf")` → `OverflowError`，`xwaveform` CLI 无异常处理 → traceback。
- **影响**：极短输入（9 字符）造成 0.5 GiB 级分配，在并发 MCP 子进程下可触发 OOM/超时；expected-value 计算得到错误位宽与错误溢出；`waveform-render` workflow 在仓库自家两个工具之间断裂。
- **建议方向**：移位先判 `amount >= a.width`；unsized based literal 统一 `max(32, digits_width)`；bitwise 复用同一套 signedness coercion；`_parse_time_spec` 显式处理 `max`/`inf` 哨兵并给出 typed error。

### 6.16 FIX-FP-01（P1，已证实，主线程复核）：fixture 指纹输入集合系统性漏项，改动产物输入仍命中旧缓存（假绿）

- **证据**：`testinfra/xverif_test/fixtures.py:292-309` 的 `_source_files` 只收集 `inputs` glob（限 `source_dir` 内）+ `extra_inputs` + **probe argv 命中文件**，**builder argv 不计入**；`testinfra/xverif_test/fixtures.py:115-118` 的 `tool_env` 是显式白名单。
- **主线程复核**：`testinfra/fixtures.v1.yaml` 中 `xdebug.xif_event` 的 `inputs = ['Makefile', 'filelist.f', 'tb/**/*.sv', 'scripts/*.py', '*.json']`，**不含 `*.tcl`**；而该 fixture 目录内确有 `wave.tcl`，且 `xdebug/testdata/waveform/xif_agent_event/Makefile` 引用它（`WAVE_TCL`，用于 `-ucli -do`）。同一 `testinfra/fixtures.v1.yaml:488` 的 `xsva.vcs` 却写了 `"*.tcl"`，说明是**漏声明**而非约定。`tool_env=['VERDI_HOME']` 也不含其 Makefile 可覆盖的其它变量。
- **触发条件**：cache 已 warm，只修改 `wave.tcl`、`mk/npi.mk`（被 `xdebug/Makefile` include）、或 `SVT_*`/`DESIGNWARE_HOME` 等未声明变量，然后运行对应 required suite。
- **影响**：`FixtureStore.resolve` 复用旧 generation，测试对**过期证据**断言并全绿，报告中无法看出——这是最危险的一类缺陷。附带：`testinfra/xverif_test/fixtures.py:446-452` 的 `_compatibility_identity` 把 `V-2023.12-SP2` 折叠为 `V-2023.12`，SP 升级对指纹不可见。
- **建议方向**：指纹输入改为可机械推导（解析 Makefile 的 include 闭包与 builder 实际读取的仓库内文件）；`tool_env` 按 builder 实际使用的变量反向校验；补"每个声明输入改动 → 指纹必须变化"的合同测试。

### 6.17 FIX-CHANGED-01（P1，已证实，主线程复核）：changed→fixture 与指纹输入使用两套 glob 语义，`--xverif-changed` 校验端可静默报 passed

- **证据**：`testinfra/xverif_test/fixtures.py:273-290` 的 `affected_fixture_ids` 用 `fnmatch.fnmatch`，而 `testinfra/xverif_test/fixtures.py:296` 的指纹展开用 `Path.glob`。两者对 `**` 的语义不同。
- **主线程复核**：对 pattern `tb/**/*.sv`，`fnmatch("tb/xif_event_top.sv", ...)` → **False**，而 `Path.glob` 实际命中 `['tb/xif_event_pkg.sv', 'tb/xif_event_top.sv']`。即"被计入指纹的文件"有一半无法被反查。
- **后果**：`testinfra/xverif_test/plugin.py:336-338` 在 `--xverif-fixture-validation --xverif-changed BASE` 下 `fixture_ids` 可能为空，而 `testinfra/xverif_test/plugin.py:363-364` 仍 `progress.finish(outcome="passed")` 并返回 `ExitCode.OK` —— **一个 fixture 都没验证却显示 passed**。gate 侧 `testinfra/xverif_test/gates.py:78-85` 在 suite 缺 `impact.owns` 时保守展开为全 plan，而 `testinfra/catalog.v1.yaml` 中 `impact`/`owns` 从未出现，因此 `--xverif-changed` 在 gate 侧恒等于全量（不省时，但至少不假绿）。
- **建议方向**：changed→fixture 与指纹输入必须复用同一份推导（同一 glob 引擎）；选择集为空时失败而非 passed；`impact.owns` 要么补齐要么移除该参数。

### 6.18 XWIKI-HOOK-01（P1，已证实，主线程复现）：`validate_xwiki.py --hook claude-file` 在 `XWIKI_DIR` 未设置时拒绝所有文件写入

- **证据**：`skills/xwiki/scripts/validate_xwiki.py:541-546` 唯一的提前放行分支要求 `wiki_dir is not None`；而 `:55-68` 的 `_resolve_wiki_dir` 在 `XWIKI_DIR` 缺失时返回 `(None, [Finding("XWIKI_DIR_MISSING", …)])`。`wiki_dir is None` 使放行分支不成立，`.md` 与路径范围过滤同时失效，`:548-557` 落到 `_print_claude_file(_payload(False, None, findings))` → `permissionDecision: "deny"`。
- **主线程复现**：`env -u XWIKI_DIR python skills/xwiki/scripts/validate_xwiki.py --hook claude-file`（输入为非 `.md`、仓库外路径）→ 输出 `{"permissionDecision": "deny", "systemMessage": "… XWIKI_DIR_MISSING …"}`。
- **当前触发面**：本机 `~/.claude/settings.json` 无 hooks 段，且该 `--hook` 模式在 `skills/xwiki/SKILL.md`、references、`skills/xwiki/agents/openai.yaml` 与 `skills/tests/` 中**零声明、零覆盖**。因此这是"一旦接线即全局封锁写入"的潜在陷阱，而非当前已生效故障。
- **影响**：若有人按脚本自身 CLI 能力注册为 `PreToolUse` hook，会话内**任意** Write/Edit（含非 `.md` 与仓库外文件）都会被拒；与 `skills/xwiki/SKILL.md:18`"必须询问用户提供路径"的指引矛盾。
- **建议方向**：`wiki_dir is None` 时应放行或输出 ask 决策，绝不能 deny；要么把 hook 模式写入 SKILL.md 并补覆盖测试，要么删除该未声明能力（`AGENTS.md` 明确禁止"接受后静默"的公开参数）。

### 6.19 SKILL-DOC-01（P2，已证实）：skill 文档声明的执行方式在本机不可用；校验范围自相矛盾

- **证据 1（文档不可执行）**：`skills/x-npi/SKILL.md:51` 声明"也可以直接执行 `scripts/examples/` 下的文件"，但 `git ls-files -s skills/x-npi/scripts/examples/` 显示 8 个文件**全部为 100644**（无执行位）；`skills/xwiki/SKILL.md:23,29` 使用裸 `python`，本机不存在该命令，而 `python3` 为 3.6.8，`skills/xwiki/scripts/validate_xwiki.py:7` 的 `from __future__ import annotations` 在该版本下直接 `SyntaxError`。这与 `AGENTS.md` 的 `.conda-xverif/bin/python` 约定冲突，也与本报告 7.3/6.7 属同一根因族（解释器选择未固定）。
- **证据 2（校验范围矛盾）**：`skills/xwiki/scripts/validate_xwiki.py:448` 的 `sorted(root.rglob("*.md"))` **不跳过隐藏目录**，而同文件 `:376-384` 的 `_directory_has_wiki_content` 明确 `if child.name.startswith("."): continue`、`:370-373` 用 `SPECIAL_DIRS`（`:26`）过滤。wiki 内若存在 `.trash/x.md` 或 `.github/ISSUE_TEMPLATE/*.md`，会被强制要求 frontmatter 并做链接校验，产生假阳性失败（hook 模式下还会拒绝写入）。同函数 `:449-453` 只捕获 `UnicodeDecodeError`，悬空 symlink 或权限导致的 `OSError` 会直接 traceback。
- **建议方向**：`rglob` 统一套用 `SPECIAL_DIRS`/隐藏目录过滤并捕获 `OSError`；SKILL.md 改为显式 `<repo>/.conda-xverif/bin/python <script>`；examples 要么补执行位，要么把"直接执行"改为"`python <file>`"。

### 6.20 TEST-COVER-01（P2，已证实）：测试基础设施的校验覆盖缺口

- **C-4a catalog 交叉校验缺失**：`testinfra/xverif_test/catalog.py:91-92` 的 `Catalog` 只持有 `suites`/`path`，**不加载 fixtures**，因此 `_validate_semantics`（`:112-136`）结构上无法做 suite↔fixture 交叉校验；suite→fixture 的唯一解析发生在运行期（`testinfra/xverif_test/plugin.py:231-235` → `testinfra/xverif_test/fixtures.py:86-90`），写错 fixture id 的 optional suite 会退化成 `pytest.mark.skip`（`testinfra/xverif_test/plugin.py:443-444`）而非失败。同时 `testinfra/xverif_test/catalog.py:120-123` 的 level/cost 校验是**不可达分支**（`testinfra/xverif_test/catalog.py:105` 的 jsonschema 已用 enum 限死），校验预算花在重复字段名上。
- **C-4b report schema 属影子断言**：`testinfra/tests/test_report_schema.py:19-40,49-57` 手写两份 report dict 送 `jsonschema` 校验，而真正校验实现产物 `report.json`（写出逻辑在 `testinfra/xverif_test/reports.py:85-103`）的 `:60-108` 只断言字段值、**从不把产物送 schema**。改动 `ResultManager.finish` 的 payload 时手写 dict 不跟着变，测试仍全绿。
- **C-4c gate 只有插件一层**：全仓无根 `conftest.py`（仅四个子目录各有一份），唯一拒绝裸 pytest 的逻辑位于 `testinfra/xverif_test/plugin.py:159-165` 的 `pytest_configure`，入口为 `pyproject.toml:17-18` → `pytest -p no:xverif <path>` 可整体绕开 gate、preflight、host 校验与结果记录；`testinfra/xverif_test/plugin.py:43` 的 `--xverif-catalog` 允许替换为任意 yaml，从而重定义 gate membership。
- **当前状态**：实测 65 个 suite 恰好自洽（缺失 fixture 引用 0、孤儿 fixture 0、无 gate 选不到的 suite 0），属潜在缺陷而非现存错误。
- **建议方向**：在 `load_catalog` 之上做显式交叉引用校验并删除 schema 已覆盖的重复检查；report schema 改用 `ResultManager` 的真实产物校验；增加根 `conftest.py` 校验 `hasplugin("xverif")` 与 catalog 路径。

### 6.21 TEST-PRUNE-01（P2，已证实，与既有复盘同源）：结果目录裁剪的 TOCTOU 仍在，且超限以 INTERNALERROR 形式炸在 configure 期

- **证据**：`testinfra/xverif_test/reports.py:119` 的 `sorted((... root.iterdir() ...), key=lambda p: p.stat().st_mtime)` 在枚举与 `stat()` 之间无保护；`:139` 再次裸 `stat()`；`:170` 的 `_tree_size` 对每个文件裸 `stat()`。调用链 `reports.py:111 create_run_dir → _prune_results` 经 `plugin.py:175 ResultManager(...)` 进入，而该行位于 `testinfra/xverif_test/plugin.py:187` 的 `try:` **之外**，异常直接成为 configure 期的 pytest INTERNALERROR。删除侧 `:149` 使用了 `ignore_errors=True`，说明设计意图是容错，但枚举/统计侧没有。
- **附带**：`:155-162` 的体积回收 `if not success: continue` **只回收成功 run**；`:163-166` 在超过 10 GiB 且无可回收成功 run 时 `raise RuntimeError`，同样是 INTERNALERROR 而非可读的 usage error；`:123` 的 `.pin` 保护在全仓无生产者；保留策略（20 successful / 10 GiB / 30 天）在 README 与 `doc/` 中均无记载。
- **触发条件**：同工作树并发启动两个 pytest（`AGENTS.md` 2026-08-16 复盘已记录该现象）；或持续失败的 suite 让 30 天内的失败 run 撑爆磁盘。
- **影响**：非确定性 INTERNALERROR，门禁在收集前中止、CI 难以归因；目前仅靠"串行启动"的人工纪律兜着。
- **建议方向**：用一次 `os.scandir` 取 `DirEntry.stat()` 并吞掉 `FileNotFoundError`；删除前做二次身份校验或先原子 rename；体积超限改为 usage error 并输出可回收清单；失败 run 纳入回收。

### 6.22 DUP-CONTRACT-01（P2，已证实，与 7.1 同源）：合同校验器与文本响应构建器多份重复实现，且已出现语义漂移

- **证据**：四份手写合同校验器——`xsva/xsva/contracts.py:29-111`、`xloc/xloc/contracts.py:33-107`、`xentry/src/xentry/contracts.py:19-53`、`xbit/src/xbit/format.py:31-44`——各自实现 `_exact`/`_require`/`_string`/`_integer`；`xsva` 的 `_timeline_result` 单函数 155 行，`xentry` 的 `_layout` 又单独实现一遍位宽校验。文本响应构建器有两份近亲实现：`xloc/xloc/xout.py:76-118` 与 `xentry/src/xentry/format.py:40-100`，**语义已漂移**（`emit_header` 前者无条件前插、后者有 `if not self.lines` 守卫；`emit_kv` 前者不处理空串、后者 `if not text: return`），`xsva/xsva/xout.py` 是第三套。
- **影响**：同一"严格合同"在多工具间不可比较；XOUT 已出现真实行为差异；任一处规则变化需同步 3–4 个文件，漏改不会被测试发现（与 7.1 的 XOUT 渲染器分散问题同源）。
- **建议方向**：抽出共享的 contract 原语与 text-response builder，各工具只提供 schema 投影。

### 6.23 XSVA-DEAD-01（P3，已证实）：xsva `frontend/` 存在死代码与重复实现

- **证据**：`xsva/xsva/frontend/extractor.py`（262 行）、`xsva/xsva/frontend/comments.py`（63 行）、`xsva/xsva/frontend/source.py`（38 行）在 shipped 路径上**全仓无引用者**（仅 `xsva/xsva/frontend/macros.py` 被 `xsva/xsva/lint/__init__.py:37` 使用）；CLI 另在 `xsva/xsva/cli.py:78-84` 自己实现读文件。注释处理有两份实现（scanner 的 `_skip_comments` 与未被使用的 `xsva/xsva/frontend/comments.py`，后者处理字符串字面量而前者不处理）。`xsva/xsva/frontend/source.py:16-30` 的 `SourceFile.line_col` 每次调用都从头扫描，为 O(n)。
- **影响**：维护者可能修改无人使用的实现；注释语义在两个实现间不一致。
- **建议方向**：删除或接线死代码，统一注释处理入口。

## 7. 横向观察与改善空间

### 7.1 XOUT 渲染器存在 5 份独立实现

`xbit/src/xbit/format.py:191`、`xentry/src/xentry/format.py:102`、`xloc/xloc/xout.py:7`、`xsva/xsva/xout.py:11`、`xcov/xcov/protocol.py:125` 各自实现 `to_xout`/`render_xout`（xdebug 侧为 C++ 的 `api/text_response_builder`，另一实现）。XOUT 是**跨工具的统一 AI 可读合同**，5 份实现没有共享层意味着格式漂移无法被单点约束；本次未发现 5 份输出已互相矛盾，但新增字段/区块时的同步成本与漂移风险是结构性的。建议把"区块顺序、表头对齐、空区块表示、截断标记"等共性抽成一份最小共享实现或至少一份可执行的格式合同测试。

### 7.2 超长函数集中区

27 个 Python 函数超过 120 行，最长 5 个：`xsva/xsva/lower/sequence_to_timeline.py:48 lower_sequence_to_timeline`（284 行）、`xverif_loop/sessions/loop_session.py:454 open`（270）、`loop_session.py:1173 query`（270）、`xcov/xcov/actions.py:1097 _exclude_export_gaps`（262）、`xverif_mcp/src/xverif_mcp/server.py:398 xverif_batch`（209）。C++ 侧 10 个文件超过 1,100 行（最大 `xdebug/src/api/dispatcher.cpp` 2,168 行）。这些正是本次 P1/P2 finding 的集中区（`_export_output_path` 死代码、`_walk_functional_leaf` 未绑定变量都在超长文件里），建议按"一个 action 一个文件"的既有惯例继续拆分，并优先拆分上述 5 个函数。

### 7.3 生成物同步与门禁现状（正面结论）

以下检查本次全部通过，说明 schema/生成链路的自动化约束当前是有效的：

- `sync_runtime_request_schemas --check`、`sync_response_schemas --check`、`sync_action_schema_hints --check`、`sync_action_metadata --check`、`sync_help_text --check`：全部 OK
- `xdebug/tools/audit_runtime_schema_compatibility.py`：runtime request schemas 为 Draft-7 兼容子集
- `xdebug/tools/validate_schema.py`：283 个 schema；`xdebug/tools/validate_examples.py`：231 examples + 8 invalid witness
- `xdebug/specs/actions/actions.yaml` 73 个 action 与 `skills/xverif/references/generated/xdebug-actions.md` 索引**完全一致**（无缺、无多）
- `pytest --xverif-gate fast --xverif-suite xdebug.static`：**123 passed**（含本次未提交的新合同测试）

### 7.4 Python 生态与规则化 lint 的缺口

本次用 `ruff` 只选真实缺陷规则即命中 4 处未定义名（`F821`），说明**仓库当前没有把静态检查接入 fast 门禁**。仓库已有极强的"生成物/合同"检查，但缺少一层通用缺陷 lint；建议以最小规则集（`F821,F841,B006,B008,S110,PLW1510`）接入 `xdebug.static` 之外的独立 suite，先清零再设为 required。

### 6.5 需要人工确认的安全姿态（非缺陷）

MCP server 恒定暴露全部工具组、状态变更与文件写出能力（`README.zh-CN.md:60`、`xverif_mcp/README.md:501-502`）。这不是实现缺陷，但对"把 MCP server 暴露给不受信任 agent"的部署，唯一边界是进程与文件系统权限。建议在 `README` 与 `skills/xverif-admin` 中补一条部署建议（例如：只在本机 UDS/stdio 下运行、不要暴露 TCP、artifact 输出目录按最小权限挂载），把该风险的缓解方式写明。

## 8. 已检查且未发现问题的边界

| 边界 | 检查内容 | 结论 |
| --- | --- | --- |
| C 内存安全 | `strcpy/strcat/sprintf/gets/malloc/free` 全仓扫描 | 0 处 `strcpy/strcat/sprintf`；无 `malloc/free` 手工内存管理（RAII/容器） |
| C++ 异常处理 | 25 处 `catch (...)` 逐点核对 | 绝大多数映射为结构化错误码；仅 `xdebug/src/engine/service/trace_source_path_formatter.cpp:143` 的静默 0 记为 6.8 |
| 命令注入 | Python 侧 `subprocess` 调用点核对 | 未发现 `shell=True` 拼接；LSF/URG 调用以 argv 列表传递 |
| 生成物漂移 | 5 个 `--check` + runtime 兼容性审计 | 全部同步，无漂移 |
| action 合同 | `xdebug/specs/actions/actions.yaml` ↔ 生成索引 ↔ schema/examples 计数 | 73/73/283/231 自洽 |
| 测试基础设施 | fixture 指纹输入核对（`testinfra/xverif_test/fixtures.py:99-133`） | 覆盖源码内容、builder、probes、工具兼容身份与 effective env；不依赖 mtime，设计合理 |
| Session 资源 | `session_lifecycle_lease` 的 flock 使用范围 | 与既有完整性测试约束一致（全仓仅该文件允许 `flock`）；但租约本身的无超时阻塞记为 6.0c |
| NPI 句柄释放 | `action_resource_scope` 析构时机 + 手工释放抽样（`design/control_dep`、`design/ast`、`design/signal`） | 正常/异常/超时三条路径都先释放再应答；抽样点成对释放，未发现泄漏或重复释放（潜在去重缺口见 6.0k） |
| 锁顺序 | 日志追加锁持锁期间的行为 | 持锁期间不回调其它加锁路径，未发现锁序反转 |
| 缓存容量 | `analysis_repository` 记账与硬上限 | tombstone/游标/绑定均计入 `charged_bytes`，每次 publish 重新强制上限，未发现无上限增长（性能问题见 6.0i） |
| env 解析 | `xdebug/src/core/common/env_config.cpp:24-31` | `strtoll` + `errno` + 尾字符校验，非法值 fail-closed（有问题的 `atoi` 点单列于 6.0h） |
| 传输部分写/TOCTOU | `xdebug/src/core/session/transport_common.h:86-169`、`xdebug/src/core/transport/file_exchange.cpp:316-381` | 正确处理 EINTR/EAGAIN 并恢复 O_NONBLOCK；tmp + link/rename + fsync 发布，读侧看不到半写 JSON |
| xsva 路径展开 | `##[m:n]` 笛卡尔展开、`##[m:$]` | 实测展开正确；越界与 unbounded 均按设计降级或报错 |
| xbit 除零与切片 | `/`、`%`、`slice`、`mask`、`resize`、`>>`/`>>>` | 除零为 typed error 且全程无 float；切片越界、mask 非法宽度均报错；4-state 符号扩展正确；逻辑/算术移位区分正确 |
| xloc 映射鲁棒性 | map 重复 loc_id/重复键/非 object/非法 UTF-8/越界行/源文件缺失 | 全部 typed error；`annotate` 每个 loc_id 只插一次并保留 CRLF |
| xcov 命令注入与路径来源 | `xcov/xcov/urg_runner.py`、`xcov/xcov/eda.py`、`xverif_mcp/src/xverif_loop/lsf/bsub.py`、`xverif_mcp/src/xverif_loop/sessions/launchers.py` | 未发现 `shell=True`；EDA 路径不查 PATH 且须在 `VCS_HOME` 内；job 名与 resource 校验非空 |
| xcov 导出原子性 | `xcov/xcov/actions.py:582-645`、`:716-808`、`:2506-2530` | staging → `_fsync_tree` → `os.replace` → 目录 fsync；发布前拒绝 symlink；已存在时 fail-closed |
| xcov 响应完整性 | `xcov/xcov/schemas.py:1813-1853`、`xcov/xcov/actions.py:314-336` | returned/total/truncated 语义校验齐全；`ok=false ⇒ 空 data`，未见"失败当成功返回" |
| session 主路径加锁 | `session_manager` 的 open/close/kill/list/close_all | 均在 `_manager_lock` 内读写与驱逐，tombstone 键经 `_management_key` 归一（例外见 6.0t） |
| testinfra 参数组合 | `--xverif-suite` 收窄、操作互斥、`--xverif-plan` 约束 | 只能收窄不能扩展；gate/prepare/validation 互斥；空 plan 不会假绿 |
| testinfra 并发 prepare | claim + staging + 原子发布 | `mkdir` 原子抢占、staging `os.replace`、`current.json` mkstemp/fsync 发布可靠，stale claim 24h 接管 |
| skills 生成物 | `generate_references.py --check` | 不写文件、按内容比较、输出确定；漂移由 `skills.xverif` suite 覆盖，产物另由真实 schema 独立校验（无自证闭环） |

## 9. 建议处置顺序

本轮共确认 **12 项 P1**（其中 11 项由主线程复现）与约 20 项 P2。按"是否产生错误结论或挂死"优先排序：

| 顺序 | 项目 | 级别 | 理由 |
| --- | --- | --- | --- |
| 1 | 6.11 XSVA-HANG-01 | **P1** | 畸形输入导致**永久挂死**且零输出，CI/agent 无法归因；修复成本极低（EOF 终止 + 无进展即报错） |
| 2 | 6.10 XSVA-SEM-01 / 6.12 XSVA-ANT-01 | **P1** | **静默产出错误时序结论**（obligation 丢失、拍号错误、antecedent 压平）却报 `exact`/`complete`；skill 正指导 agent 据此取证 |
| 3 | 6.16 FIX-FP-01 / 6.17 FIX-CHANGED-01 | **P1** | 测试对**过期证据**断言并全绿；`--xverif-changed` 可"零验证报 passed"，直接损害整套门禁的可信度 |
| 4 | 6.14 XBIT-ERR-01 / 6.15 XBIT-NUM-01 | **P1** | 错误路径自身崩溃（服务被打死）与数值语义错误（位宽/符号/移位放大），影响 MCP 与 CLI 两条入口 |
| 5 | 6.0z XCOV-NAME-01 | **P1** | coverage 过滤路径可确定性触发 `NameError` |
| 6 | 6.18 XWIKI-HOOK-01 | **P1** | 一旦接线即全局封锁文件写入；当前无声明无覆盖，应优先消除或补齐声明与测试 |
| 7 | 6.0za XCOV-DEAD-01 + 7.4 lint 接入 | P2 | 一次消除"未定义名/不可达代码"整类回归面，成本最低 |
| 8 | 6.3 ENTRY-PY-01 / 6.7 BUILD-PY-01 / 6.19 SKILL-DOC-01 | P2 | 新用户与构建"首次接触即失败"，且报错误导方向（同一解释器选择根因族） |
| 9 | 6.0n XCOV-WORKDIR-01 / 6.0o XCOV-CLOSE-01 | P2 | 确定的资源泄漏与 double-free 风险，改动局部 |
| 10 | 6.0s MCP-REQID-01 / 6.0t MCP-GC-01 / 6.0v MCP-DOCTOR-01 | P2 | 会话生命周期正确性，影响 agent 的 kill/gc 决策 |
| 11 | 6.0 XDEBUG-NET-01 / 6.0b XDEBUG-RES-01 / 6.0c XDEBUG-LOCK-01 / 6.0d XDEBUG-SIGNAL-01 / 6.0e XDEBUG-FILE-01 | P2 | 资源放大、阻塞、信号安全与静默丢结果，属引擎稳健性 |
| 12 | 6.0f XDEBUG-LOG-01 / 6.0g XDEBUG-DIAG-01 / 6.13 XSVA-DIAG-01 | P2 | 磁盘单调增长、错误归因误导、诊断不影响退出码 |
| 13 | 6.5 XCOV-EXPORT-DOC-01 / 6.4 REPO-GATE-01 / 6.6 SESSION-MIGRATE-01 | P2 | 合同漂移与当前唯一门禁红灯；迁移陷阱需产品或文档决策 |
| 14 | 6.0p XCOV-LSF-01 / 6.0u MCP-KILLPG-01 / 6.0w MCP-FAKE-01 | P2–P3 | 需真实 LSF 闭环验证，建议一并补 fake 覆盖 |
| 15 | 6.20 TEST-COVER-01 / 6.21 TEST-PRUNE-01 / 6.22 DUP-CONTRACT-01 | P2 | 测试与合同的自我校验缺口；与第 3 项同属门禁可信度 |
| 16 | 其余 P3（6.0h–6.0m、6.0q、6.0r、6.0x、6.0y、6.8、6.9、6.23） | P3 | 可用性与证据质量，可批量随版本收口 |
| 17 | 7.1 / 7.2 / 7.3（XOUT 渲染器合并、超长函数拆分、结构债） | 结构性 | 需独立计划，不建议混入缺陷修复提交 |

## 10. 最终边界审计

- 本报告全部 finding 均给出 `文件:行号`，并区分"已证实（有代码路径或实测复现）"与"疑似/需验证"。
- **主线程独立复现的 P1（11 项）**：xsva REPEAT 语义丢失与错误拍号（`xsva explain` 报 `exact`/`1/1 complete` 但 obligation 只有错误的 `cycle +1`）、xsva 畸形输入挂死（两例 `rc=124`、零输出）、xbit stdio 被坏 JSON 打死（`rc=1` traceback）、xbit `'hFF + 'h1` 位宽（`8'h0`，应为 32 位）、fixture 指纹漏 `wave.tcl`、`fnmatch` 与 `Path.glob` 对 `**` 的语义差异（`tb/**/*.sv` 反查失败）、xwiki hook 的 `deny` 响应；另有 xcov `NameError`、`full_name` 未绑定可达性、wrapper 解释器失败等经代码路径逐环节确认。唯一未由主线程复现的 P1 是 6.16/6.17 中涉及完整 `FixtureStore` 流程的端到端行为（已复核其构成要件：glob 语义、`inputs` 声明、`testinfra/xverif_test/plugin.py` 的 passed 分支）。
- **未覆盖**：动态内存正确性（无 ASan/UBSan/valgrind）、并发压力下的真实竞态复现、真实 LSF 语义（`bkill` 对已完成 job 的返回码、bsub 包装器是否吞 job-id 帧）、真实 VDB/FSDB 上的性能与内存峰值、`nightly` 专属 suite 的当前通过状态。这些需要 host 环境与 EDA 资源，超出只读审查范围。
- **审查期间的仓库状态变化**：无源码改动。仅向 `tmp/review-tools/`（git-ignored）安装静态检查工具，并在 `doc/` 写入本报告。报告初稿曾触发 `test_repository_has_no_machine_specific_local_paths`，已按 `AGENTS.md` 约定把本机绝对路径改为占位符，该断言对本文档不再报错。
- **需要读者注意的既存红灯**：`fast` 门禁当前仍为 1 failed（来源是四份未跟踪文档，见 7.4），与本报告无关但会阻塞提交。
