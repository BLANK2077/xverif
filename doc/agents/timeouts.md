# xverif timeout 与进程生命周期说明书

本文件是 xverif timeout 机制、超时后清理语义与孤儿进程边界的**单一真源**。修改任何 timeout
默认值、新增/删除 timeout 环境变量、调整 `terminate`/`killpg`/`bkill` 路径或 session
生命周期时，必须同步更新本文件。

- 修改 timeout 前先读本文件的「修改检查清单」。
- 需要精确定位实现时，按本文件的 file 证据索引直接跳转，不要重新做全仓调查。
- 本文件不含真实 LSF/EDA 实测结论；标注「未实测」的条目必须在具备真实环境的站点验证。

## 1. 分层模型

```text
agent / MCP client
  └─ xverif-mcp（MCP stdio server，长驻；拥有若干 managed session）
       ├─ direct: tools/xdebug|x|cov --stdio-loop（独立进程组）
       │    └─ xdebug detached engine（setsid，持有 FSDB/NPI 句柄）
       └─ lsf:    bsub -I ... --stdio-loop（独立进程组 + LSF job，带 -W）
  └─ xdebug_lsf / xcov_lsf（SDK-free CLI，短命）
       └─ manager（UDS 守护进程，start_new_session，idle 后退出）
            └─ 同上的 direct/LSF loop
  └─ 原生 CLI（tools/xdebug、tools/xcov）one-shot：不经过 loop
```

关键事实：**父子关系没有任何 `PR_SET_PDEATHSIG` 之类的内核兜底**，进程回收完全依赖显式
`killpg`/`bkill` 与调停者（MCP server、manager）存活。因此每个 timeout 都必须回答两个问题：
「超时后谁负责杀」和「如果调停者已经不在，谁来兜底」。

## 2. timeout 清单

### 2.1 MCP 层（`xverif_mcp/src/xverif_loop/config.py:91-109`）

| 名称 | 环境变量 | 默认 | 作用 | 超时后 |
| --- | --- | --- | --- | --- |
| one-shot CLI | `XVERIF_MCP_TIMEOUT_SEC` | 360s | xbit/xentry/xloc/xsva 与 xdebug/xcov resource-free one-shot | `terminate_process_group`：SIGTERM → 5s → SIGKILL（整组），返回 `XVERIF_TOOL_TIMEOUT` |
| session open | `XVERIF_MCP_STARTUP_TIMEOUT_SEC` | 180s | loop ready envelope + native `session.open` | `abort()` → 进程组终止 + bkill；返回 `SESSION_OPEN_FAILED`（LSF 下 `scheduler.status=startup_timeout`） |
| query | `XVERIF_MCP_REQUEST_TIMEOUT_SEC` | 360s | 已 open session 的每次 query | `abort()` → 终止 + bkill；返回 `SESSION_LOST` |
| close | `XVERIF_MCP_CLOSE_TIMEOUT_SEC` | 30s | `session.close`、`stdio.quit`（用其 1/2） | 继续走 terminate+bkill；结果不完整时 `SESSION_CLEANUP_PARTIAL_FAILURE` + tombstone |
| bkill | `XVERIF_MCP_BKILL_TIMEOUT_SEC` | 30s | `bkill` 子进程 | `LauncherTerminationError` → `cleanup_partial`/`orphan_suspected` tombstone |
| LSF session wall time | `XVERIF_LSF_SESSION_WALL_TIME_SEC` | 7200s（→ `-W 120`） | 提交给 LSF 的 runtime limit | LSF 终止 job，客户端看到 loop 提前退出（`SESSION_LOST`/`startup_rejected`） |

### 2.2 SDK-free wrapper / manager（`XVERIF_LOOP_*`，由 `XVERIF_LSF_CLI_*` 映射）

| 名称 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| 阶段超时 | `XVERIF_LSF_CLI_STARTUP/REQUEST/CLOSE/BKILL_TIMEOUT_SEC` | 180/360/30/30 | 与 MCP 走同一 `RuntimeConfig` 代码路径 |
| manager idle | `XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC` | 5s | 三个条件同时满足才退出：idle 到期 + 无 in-flight 请求 + 无 live/unresolved session；**有 live session 时永不退出** |
| manager 启动 | `XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC` | 180s | 等待 manager 写 `READY\n`；失败走有界 killpg 阶梯 |
| LSF session wall time | `XVERIF_LSF_SESSION_WALL_TIME_SEC` | 7200s | 与 MCP 共用，提交为 `-W <分钟>` |

### 2.3 native xdebug（C++，`xdebug/src/core/common/env_config.cpp`）

| 名称 | 环境变量 | 默认 | 超时后 |
| --- | --- | --- | --- |
| session 启动等待 | `XDEBUG_SESSION_START_TIMEOUT_SEC` | 300s | `compensate()` + force cleanup（SIGTERM 1500ms → SIGKILL 1500ms） |
| session 空闲 | `XDEBUG_SESSION_IDLE_TIMEOUT_SEC` | 86400s | 引擎自行退出（detached engine 的唯一自动回收路径） |
| file transport 请求 | `XDEBUG_FILE_TRANSPORT_TIMEOUT_MS` | 300000ms | 本地引擎写 `terminated_on_timeout` tombstone；**远端/LSF 引擎不确认、不写 tombstone** |
| file transport ping/quit | `XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS` | 2000ms | close 退化为 100ms → SIGTERM/SIGKILL |
| UDS/TCP 控制请求 | 硬编码 2000ms | 2000ms | 同上 |
| UDS/TCP 数据请求 | `limits.timeout_ms`（缺省无 deadline） | 无 | 只有显式给出才有限时；缺省可无限阻塞 |
| file claim 陈旧 | `XDEBUG_FILE_CLAIM_TIMEOUT_MS` | 600000ms | 只判 claim 失败，**不杀 worker** |
| helper 子进程 | `limits.timeout_ms`（0=不限时） | 0 | `kill(-pid, SIGTERM)` → grace → `kill(-pid, SIGKILL)`（整组） |

### 2.4 xcov

| 名称 | 环境变量 | 默认 | 超时后 |
| --- | --- | --- | --- |
| URG 启动 | `XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC` | 120s | `bkill <job_id>`/`bkill -J` + 本地 bsub 进程组 killpg |
| URG 运行 | `XVERIF_XCOV_URG_RUN_TIMEOUT_SEC` | 600s | direct：整组 SIGTERM→5s→SIGKILL，`scheduler.cleanup` 记录结果；LSF：bkill + killpg |
| URG wall time | `XVERIF_XCOV_URG_WALL_TIME_SEC` | 7200s（→ `-W 120`） | 内层 `bsub -K` job 的 LSF runtime limit |
| cache 构建权等待 | 无（硬编码） | 300s | 抛 `XCOV_CACHE_CLAIM_TIMEOUT`，不杀持锁者 |
| cache 陈旧隔离 | `ABANDONED_STAGING_SECONDS` | 24h | claim/staging 移入 `quarantine/` 或删除 |

### 2.5 硬编码但不属于 timeout 的常量

`JsonlProcess.terminate` 的 5s+5s、`_run_bkill` 的 `bkill_timeout_sec`、`bkill` 自身的 30s、
xdebug helper 的 200ms grace、`xdebug log bundle` 的 30s、`mcp_ssh` 的 `ConnectTimeout=10`
（连接后无 keepalive、无整体超时）。

## 3. `-W`：唯一的硬杀兜底

- 变量：`XVERIF_LSF_SESSION_WALL_TIME_SEC`（session job，MCP 与 SDK-free 共用）与
  `XVERIF_XCOV_URG_WALL_TIME_SEC`（内层 URG job），单位**秒**，默认 7200。
- 语义：无首尾空白的有限正数，上限 31536000（一年），向上取整到 LSF `-W` 的分钟粒度
  （7200 → `-W 120`）。不提供 `off`/无限语法；需要更长会话时显式调大数值。
- 隔离：`XVERIF_LSF_BSUB` 自带 `-W` 时 MCP 提交与 xcov URG 都 fail-closed，禁止静默双写。
- 可观测：session record 发布 `scheduler.requested/effective.wall_time_sec` 与
  `scheduler.submitted.wall_time_minutes`；URG 发布 `scheduler.wall_time_minutes`。
- 为什么必须有：见第 4 节「硬杀路径」——本地清理链需要调停者存活，`-W` 是唯一在调停者
  被 SIGKILL 后仍能回收 LSF 资源的机制。
- **未实测**：本机无 LSF，`-W` 在站点 interactive 队列/esub 上的接受度、到期后的结束帧
  文本与 bsub 退出码尚未实测；目前不对结束帧做字符串映射，只保留通用错误 + 结构化字段。

## 4. 进程所有权与孤儿边界

### 4.1 三条退出路径

| 路径 | 触发 | 清理 |
| --- | --- | --- |
| 正常 | stdin EOF、正常退出、显式 close | MCP lifespan + `atexit` → `close_all`；manager `_shutdown_cleanup` → `close_all` |
| 信号 | SIGTERM | MCP：handler 起 daemon 线程执行有界 `close_all`（预算 `close_timeout + bkill_timeout`，默认 60s，上限 300s）后 `os._exit(128+15)`；manager：handler 置 `_stop` 让 accept 循环退出 → `finally` 清理，另有无条件 watchdog |
| 硬杀 | SIGKILL、OOM、终端断连 | 本地清理**不会**执行。LSF：由 `-W` 兜底；direct：loop 读到 stdin EOF 自行退出；detached engine：`XDEBUG_SESSION_IDLE_TIMEOUT_SEC`（默认 24h）或后续 `session.gc` |

### 4.2 终止语义（必须 fail-closed）

`terminate_process_group`（`xverif_mcp/src/xverif_loop/lsf/protocol.py`）与 xcov 的
`_terminate_process_group` 统一遵守：

1. spawn 时缓存 pgid（`start_new_session=True` 使 pgid == pid），之后不再重新 `getpgid`，
   避免 leader 被 reap 后的竞态；
2. SIGTERM → 有界等待 → SIGKILL → 有界等待；
3. 只有确认 leader 退出才返回 `ok/complete`；两次等待都超时返回 `status="unconfirmed"`，
   上层据此写 `cleanup_partial`/`orphan_suspected` tombstone，**不得**报成功。

### 4.3 退役（retire）语义：自退出/超时后如何 kill 并复用同名

session 自行退出（loop/引擎崩溃、`-W` 到期、EOF）后不能只靠"杀进程"回收，必须显式退役记录：

1. MCP `refresh_state()`：`state=="alive"` 且自有 loop 进程已退出 → 降级为 `dead`
   （`terminal_source="loop_exit"`，证据含 `loop_returncode`/`job_id`/`wall_time_minutes`），
   并把证据存进 `last_cleanup.loop_exit`；在 `kill`/`close`/`doctor`/`open` 入口刷新。
2. MCP `kill`（= `session_close(mode="force")`）：只在"已观察到自有 loop 退出"时给 native admin 请求
   附加 `args.retire_unreachable=true`；其余情况完全不发送该参数。
3. native `session.close mode=force`：`cleanup_session_locked` 先做 2s 级 ping/quit 探测；若引擎完全
   不可达且调用方显式要求退役，则 `stopped=true, retired_unreachable=true`，随后走既有
   `xdebug_design_remove_session_generation()`（按 generation 守卫删除 state/socket/endpoint/transport，
   保留 generation marker、history 与 logs）。**不声称引擎进程已停止**；响应
   `summary.retired_unreachable=true`。
4. native 约束：`retire_unreachable` 仅允许 `mode=force` + 精确单一 `target.session_id`（`all`、
   graceful 都在 CLI 与引擎两层拒绝）；`session.gc` 的 idle/unhealthy 回收路径内部固定带该参数；
   `session.open` 的同名冲突探测使用内部 `limits.timeout_ms`（默认
   `XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS` 2000ms）有界化，失败即 `SESSION_STALE` +
   `error.unreachable` + `next_actions`/`correct_example`。
5. 名字复用规则：MCP `closed` tombstone **不再**阻止同名 `session_open`（旧记录仅作证据）；
   `cleanup_partial`/`orphan_suspected` 仍阻止并返回 `next_actions` → `xverif_debug_session_kill`；
   `gc` 对"loop 已确认退出"的未解决记录重试一次 kill，成功即转 `closed` 并移除，发布 `retired_count`。
6. gracefully close 遇到 loop 已退出不静默升级：返回 `SESSION_LOST` + `next_actions` 指向 kill。

残余风险：单线程引擎正在执行长查询时 ping 也会失败，因此"不可达"≠"进程已死"；退役只在显式
kill/gc 车道发生，被退役记录对应的引擎（若仍活着）会自行跑到 `XDEBUG_SESSION_IDLE_TIMEOUT_SEC`
空闲退出；若它之后重新 touch 自己的 registry 记录，同名 open 会再次看到 `SESSION_STALE`，
重复 kill 即可再次退役。

### 4.4 已知残余风险（未在本次治理范围内）

| 风险 | 现状 | 兜底 |
| --- | --- | --- |
| detached xdebug engine 长期存活 | `setsid()` + 无 PDEATHSIG，最长 24h | `XDEBUG_SESSION_IDLE_TIMEOUT_SEC`、`session.gc` |
| 远端/LSF 引擎超时收容不确认 | `session_manager.cpp` 对非本地进程直接 return，不写 tombstone | 显式 retire 车道（4.3）可退役记录；`-W`/bkill 回收 job |
| 忙引擎被判定为不可达 | ping 失败不等于进程死亡 | retire 仅在显式 kill/gc 且 loop 已退出时触发；不回收时保持 unresolved |
| `xdebug --stdio-loop` 无信号处理、EOF 退出不关 session | C++ 侧未改 | MCP 层 SIGTERM 清理已覆盖常见路径 |
| `mcp_ssh` 无 keepalive / upstream ready 无超时 | 未改 | 连接断开由 MCP SDK killpg 处理 |
| `xverif_batch` 无整体时限 | 未改 | 每行受 request/one-shot 超时约束 |
| 无 `bjobs` 台账与无主 job 回收器 | 未实现 | 依赖 `-W` 与人工 `bjobs -J` 排查 |

## 5. 修改检查清单

新增或调整 timeout / 终止路径时必须同时处理：

1. 实现：`xverif_mcp/src/xverif_loop/config.py`（变量、默认值、严格校验）、对应的
   `protocol.py` / `launchers.py` / `runner.py` / `urg_runner.py` 调用点。
2. 孤儿语义：明确「谁杀、超时后是否仍可确认」，必要时返回 fail-closed 结果而不是成功。
3. 公开合同：`xverif_mcp/README.md` 环境变量表、`xcov/README.md`（xcov 侧）。
4. skill：`skills/xverif-admin/references/{mcp,sdk-free-loop}/*.md` 与
   `skills/xverif-admin/SKILL.md` 的路由；改完跑 `skills.xverif_admin` suite 并执行
   `make install-xverif-admin-skill` + `diff -qr` 验收。
5. 测试：unit 用严格的非法值矩阵与默认值断言；进程组回收必须用「父+孙」真实进程验证；
   涉及 fake 行为替身的用例要按 `testinfra/fault_injection_exceptions.v1.json` 精确登记。
6. 本文件：更新清单、默认值与残余风险。

## 6. 证据索引

- MCP/loop 配置与默认值：`xverif_mcp/src/xverif_loop/config.py`
- 进程启动与终止：`xverif_mcp/src/xverif_loop/lsf/protocol.py`、`sessions/launchers.py`
- session 生命周期与 tombstone：`xverif_mcp/src/xverif_loop/sessions/loop_session.py`、
  `sessions/session_manager.py`、`sessions/capabilities.py`
- manager/UDS 与信号处理：`xverif_mcp/src/xverif_loop/wrapper.py`、`native_cli.py`
- MCP one-shot 与关停：`xverif_mcp/src/xverif_mcp/runner.py`、`server.py`
- bsub `-W` 组装：`xverif_mcp/src/xverif_loop/lsf/bsub.py`（fake：`lsf/fake_bsub.py`）
- xdebug 超时：`xdebug/src/core/common/env_config.cpp`、`xdebug/src/engine/session/*`、
  `xdebug/src/engine/server.cpp`、`xdebug/src/api/stdio_loop.cpp`
- xcov URG：`xcov/xcov/urg_runner.py`、`xcov/xcov/urg_cache.py`、`xcov/xcov/session.py`
- 相关历史结论：`doc/XVERIF_CODE_REVIEW_2026-09-20.md`（6.0u MCP-KILLPG-01、6.0t MCP-GC-01、
  6.0w MCP-FAKE-01）
