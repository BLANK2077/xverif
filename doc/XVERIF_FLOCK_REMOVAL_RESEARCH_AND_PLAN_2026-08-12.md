# xverif `flock` 热路径移除研究与实施计划

## 1. 文档状态

- 日期：2026-08-12
- 当前阶段：用户已授权实施，按七个阶段提交推进
- 本轮边界：只修改本文档，不修改产品源码、测试或公开合同
- 最终目标：普通 action、`session.list`、`session.doctor`、配置存储、日志和
  coverage cache hit 的执行链中不出现 `flock`；允许 session 生命周期写操作按
  session 粒度使用 `flock`
- 禁止事项：不通过关闭日志、取消持久化、切换 transport/backend/data source 或降低测试
  层级换取表面性能

## 2. 结论摘要

当前 `flock` 不能直接机械删除。部分锁已经被进程模型、单 session 单 engine、串行 accept loop、
`g_npi_request_mutex`、MCP manager/session 内部锁和原子文件发布重复覆盖，属于可以移除的保险；
另一些锁仍承担全局 JSON 读改写、共享日志追加、URG cache 唯一构建/淘汰以及 fixture 唯一构建
职责，必须先解除共享写结构，再删除锁。

推荐终态：

1. xdebug registry 从一份全局 JSON 改为每 session 一个目录和一个原子状态文件。
2. query 直接定位单 session 状态文件，list/gc 才遍历目录。
3. `session.open/close/kill/gc/timeout containment` 保留按 session lifecycle lease；query、doctor、
   list 不加文件锁。
4. 每 action 的 durable `last_active` registry touch 从同步返回链路删除。
5. 配置存储依赖 engine 单写者合同和进程内串行，不再使用跨进程锁。
6. 日志按 owner/process 分片，单文件只有一个 writer；聚合发生在 doctor/bundle/read 路径。
7. URG cache 使用不可变内容寻址 entry、唯一 staging、原子 claim/publish；自动 eviction 移出
   action 路径。
8. testinfra fixture prepare 使用原子 claim directory 和 immutable generation，不再使用
   `flock`。

## 3. 当前 `flock` 清单

### 3.1 xdebug session lifecycle lease

实现：`xdebug/src/engine/session/session_lifecycle_lease.h`。

当前调用点：

- `SessionManager::ensure_session()`：session open。
- `SessionManager::close_session()`：graceful/force close。
- `SessionManager::terminate_on_timeout()`：query 超时后的外部终止。
- `SessionManager::diagnose_session()`：doctor。
- `send_request_capture()`：普通 session query 的 registry/generation snapshot。

判断：open、close、timeout containment 仍需要按 session 排他；query 和 doctor 不需要。当前 query
只在读取 snapshot 时持有 lease，真正 vendor request 执行前已经释放，因此这把锁本来就不保证
query 与 close 的执行期互斥。

### 3.2 xdebug 全局 session registry lock

实现：`xdebug/src/engine/session/session_registry.cpp`。

当前一份 registry 保存所有 session。`load_all`、reserve、opening update、finalize、terminal
state、touch 和 remove 都使用同一全局 `registry.lock`。更新协议虽使用临时文件、文件
`fsync`、原子 `rename` 和目录 `fsync` 保证 crash consistency，但多 writer 的 read-modify-write
仍依赖全局锁。

普通成功 query 至少执行：

- helper 在发送请求前读取 registry；
- engine 完成请求后 touch 当前 generation；
- helper 收到成功响应后再次 touch 当前 generation。

`touch_if_generation()` 对同一秒内的 timestamp 会跳过写回，但仍抢全局锁并读取整份 registry；
跨秒时重写整份 registry 并执行两级 `fsync`。这是当前 action 热路径最重要的共享锁和扩展性问题。

### 3.3 xdebug structured logging

实现：`xdebug/src/core/logging/action_log.cpp`。

所有 public action、helper lifecycle、transport、engine lifecycle 与 analysis cache 事件最终通过
共享 NDJSON 路径同步 `flock + append`。普通成功 session action 的典型同步日志包括 public
begin/end、helper spawning/completed 和 transport success；特定 action 还会产生额外 cache、
lifecycle 或 error event。

当前 rotation 在 append lock 之外执行，因此现有 `flock` 只保护单次追加，并没有完整保护
`stat -> rotate -> append` 事务。正确方向是 owner shard，而不是简单删锁后继续共享 rotation。

### 3.4 xdebug versioned JSON config store

实现：`xdebug/src/waveform/common/versioned_json_store.cpp`。

list、event、APB、AXI、stream 和 waveform cursor 的 load/update 使用同一抽象。生产路径中每个
session 只有一个 engine，server accept loop 串行，handler 外层还有 `g_npi_request_mutex`；
direct-resource session 名又包含 PID 与单调时钟，天然唯一。因此生产路径不存在多个进程并发
更新同一 session config store 的合法入口。

现有 unit test 人工 fork 12 个 writer，测试的是比生产合同更宽的通用多进程存储语义。移除锁时
应同步收窄组件合同和测试，而不是保留一个生产不需要的跨进程事务抽象。

### 3.5 xcov logging

实现：`xcov/xcov/logging.py`。

日志路径已经包含 `owners/<pid>`，session manifest 也位于 owner 目录，但 manifest update 和
NDJSON append 仍使用 `flock`。同一路径已经是进程单写者，文件锁属于重复保险；需要补充进程内
mutex 和单 write append，避免未来线程化产生同进程交错。

### 3.6 xcov URG content-addressed cache

实现：`xcov/xcov/urg_cache.py`。

当前锁职责：

- per-key blocking lock：cache lookup、损坏隔离、最长 300 秒 URG 构建、原子发布；
- global eviction lock：统计全局 entries/bytes 并执行 LRU；
- per-key nonblocking lock：避免删除正在生成/读取的 entry；
- abandoned staging cleanup：尝试取得 key lock 后删除。

这些锁当前承担真实跨 session 并发职责，不能直接删除。cache 已经具备 immutable entry、唯一
staging、完整 artifact hash、`COMPLETE` marker 和原子 rename，适合进一步改成原子 claim 与
无锁读取。

### 3.7 MCP/SDK-free structured logging

实现：`xverif_mcp/src/xverif_loop/logging.py`。

同一个 `StructuredLogger` 已使用 `_write_lock` 串行进程内 writer，但不同 MCP/loop owner 仍可
写同一 log root/path，因此又使用 `flock`。改成 owner instance shard 后，进程内 lock 足够。

### 3.8 testinfra fixture prepare

实现：`testinfra/xverif_test/fixtures.py`。

`.prepare.lock` 覆盖 cache lookup、EDA builder、probe、immutable generation publish 和
`current.json` 更新，确保一个 fixture 同时只有一个构建者。它不在生产 action 路径，但若全仓
静态规则要求只允许 session lifecycle `flock`，仍需改成原子 claim directory。

## 4. 普通 action 当前锁成本模型

一次成功的 xdebug session-bound action，典型路径至少包含以下 9 次 `flock` acquire：

1. public begin log；
2. helper spawning log；
3. query lifecycle snapshot；
4. global registry read；
5. engine-side generation touch；
6. helper-side generation touch；
7. transport success log；
8. helper completed log；
9. public end log。

其中 state touch 与日志都是同步执行。不同进程会竞争同一 registry 或 session log，等待无公开
上限；共享 home/NFS 的元数据与 `fsync` 延迟会进一步放大尾延迟。xcov MCP query 还会叠加
wrapper log、xcov log，以及 cold miss 时跨完整 URG 执行窗口的 key lock。

## 5. 已有代码级并发保证

以下保证允许安全缩小或移除锁：

- 每个 xdebug session 启动一个独立 engine process。
- engine server 当前串行 accept/handle client。
- engine handler 外层使用 `g_npi_request_mutex`，未来 transport 并发后仍保持同 session vendor
  context 串行。
- MCP `McpSessionManager` 使用 manager `RLock` 保护 session map 与 opening set。
- 每个 `XdebugLoopSession` 使用 lifecycle `RLock` 串行 query/lifecycle 操作。
- xcov stdio-loop 一个进程最多持有一个 live VDB session，多 VDB 由多个 manager-owned process
  隔离。
- file transport v2 已使用 tmp + atomic publish、request rename claim、response/done/failed
  状态目录，不依赖 `flock`。
- config store、generation marker、registry 和 cache entry 已广泛使用同文件系统 staging、
  `fsync` 与 atomic rename。

仍缺少的保证：

- 全局 registry 的多 writer 合并；
- xdebug/loop 共享日志的单 writer ownership；
- URG 相同 key 的唯一 builder 与安全 eviction；
- fixture 相同 id/fingerprint 的唯一 builder。

## 6. 目标 session registry 设计

建议目录：

```text
~/.xdebug/engine/sessions/
  <session-hash>/
    state.json
    generation
    endpoint.json
    activity
    logs/
    transport/
    history/
      <generation>.json
```

`state.json` 是当前 generation 的 canonical record，至少包含 schema version、原始 session id、
generation、lifecycle state、resource identity、transport/endpoint、PID/host、ownership hash、
created time、lifecycle updated time 和 cleanup evidence。

状态机：

```text
missing/closed
    -> opening
    -> active
    -> closing
       -> closed
       -> cleanup_failed
       -> terminated_on_timeout
```

规则：

- open 在按 session lease 内先原子发布 `opening` reservation，再启动 engine。
- endpoint ready 和 resource identity 二次检查完成后原子发布 `active`。
- close 在 lease 内先发布 `closing`，完成 cleanup 后发布 `closed` 或 terminal evidence。
- query 直接读取一个 `state.json`，验证 `active + generation + resource identity` 后连接，不拿
  lifecycle lease。
- query snapshot 后 close 开始的竞态与当前实现相同：最终表现为成功响应或稳定 transport/session
  error，不能访问半写状态或错误 generation。
- list 遍历 session directories，默认跳过 `closed`，verbose/include-tombstones 可展示终止记录。
- 单个 record 损坏只影响该 session，不能使所有 session 返回 `REGISTRY_INVALID`。
- gc 对每个目标分别取得 lifecycle lease，不允许重新引入全局 registry lock。
- 同名 reopen 只允许覆盖 cleanup confirmed 的 `closed`；`cleanup_failed` 和 timeout tombstone
  必须显式 gc。

不能只在 close 时首次写状态。open 前必须存在原子 reservation，否则两个进程可能同时启动
同名 engine。

## 7. 分阶段实施与提交边界

### Phase 0：合同、测量与计划冻结

- 在本文档记录基线和进度。
- 使用 `strace -f -e flock` 记录 session-bound、direct-resource、xcov hit/miss、config、list 和
  doctor 的调用次数与等待时间。
- 冻结 no-fallback、generation、ownership、timeout containment、tombstone 和 crash consistency
  验收标准。
- 建立静态 allowlist：最终只有 session lifecycle mutation 可引用 `SessionLifecycleLease`。

### Phase 1：per-session registry v4

- 将 `SessionRegistry::get()` 改为直接读取单 session state。
- 将 list/latest 改为目录遍历。
- 将所有状态写改为 expected-generation/state CAS + atomic replace。
- close 保留 `closed` record，不再从全局数组删除。
- 删除全局 registry lock 和 monolithic read-modify-write。
- 提供显式离线 v3 -> v4 migration；不做运行时 dual-read 或静默 fallback。

### Phase 2：query/doctor 热路径零 session `flock`

- 删除 `send_request_capture()` 和 doctor 的 lifecycle lease。
- 删除 helper 与 engine 的同步 durable registry touch。
- idle timeout 继续使用 engine 内存 `last_active`。
- 如 public list 必须保留 activity，响应发出后 best-effort 更新独立 marker；失败不改变 action
  结果。
- direct-resource 使用进程 owner 的 ephemeral RAII session，不进入 durable registry。

### Phase 3：config store 与日志单写者化

- 将 VersionedJsonStore 合同收窄为 engine-owned single writer，保留原子写与故障注入。
- xdebug、MCP/SDK-free 日志增加 owner instance shard。
- xcov 使用既有 `owners/<pid>`，移除重复文件锁。
- 每条 NDJSON 一次 `O_APPEND` write；rotation 移至 close/gc/maintenance。
- doctor/log bundle 聚合 shards，并依据 timestamp、owner、event sequence 确定性排序。

### Phase 4：URG cache 原子 claim 与离线 GC

- cache hit 对 immutable entry 只读，不加锁。
- cold miss 通过 `mkdir(claims/<key>)` 原子选择唯一 builder。
- claim 记录 owner、host、heartbeat 和 deadline；stale takeover 使用原子 rename 隔离旧 claim。
- follower 只等待正式 `COMPLETE`，受 request deadline 限制；失败返回 typed error，不改 backend。
- 自动 LRU eviction 移出 action path；达到 hard capacity 时 fail-closed 并提示显式 cache GC。
- 显式 GC 只处理无 live claim/session 的 immutable entry，先 rename 到 trash 再删除。

### Phase 5：testinfra fixture 原子 claim

- `.prepare.lock` 改为 claim directory + owner/heartbeat。
- builder 继续使用独立 staging 和 immutable generation。
- `current.json` 使用唯一临时文件原子替换。
- stale claim 只由显式 prepare/clean 处理。

### Phase 6：删除、静态门禁与完整回归

- 删除 config/log/cache/fixture 中的 `fcntl`/`sys/file.h` 依赖。
- 静态检查只允许 session lifecycle lease 实现存在 `flock`。
- 先统一 clean build，再按 catalog 确认 gate membership 后执行 focused suites 和完整 gate。

## 8. 验收矩阵

### 8.1 锁与性能

- session-bound 普通 action：`strace -f -e flock` 为 0。
- direct-resource action：为 0。
- `session.list`、`session.doctor`：为 0。
- list/event/APB/AXI/stream/cursor config action：为 0。
- xcov cache hit：为 0。
- open/close 只出现当前 session hash 对应 lifecycle lock。
- 多 session 并发 action P95 不随 registry 中 session 数线性增长。
- 同 session query P50/P95 不因日志或 activity 持久化回归。

### 8.2 session correctness

- 两个进程同时 open 同名 session，只能一个成功。
- 不同 session 同时 open 不互相等待。
- query 与 close 竞争只允许成功或稳定 session/transport error。
- close 后立即同名 reopen，旧 generation 不得清理新 generation。
- timeout containment 只终止 expected generation。
- 一个 state record 损坏不影响其它 session list/query。
- state write/rename/fsync 任一步崩溃后只能看到旧完整记录或新完整记录。

### 8.3 log/config/cache/fixture correctness

- 多进程 owner shard 的每一行都是独立合法 JSON，聚合不丢 event。
- rotation/cleanup 不影响 active writer。
- config store write/rename fault 不产生半文件；合法请求仍按 engine 顺序生效。
- 两个 URG cold miss 只能一个 builder；builder crash 后可确定性接管。
- cache hit 不启动 URG，不进入 eviction/cleanup。
- cache 达到 hard capacity 明确失败，不删除 live entry，不 fallback。
- fixture builder crash 保留可诊断 staging/claim，不发布 partial generation。

### 8.4 正式 suite

- `testinfra.unit`
- `xcov.unit`
- `xcov.urg_backend`
- `xverif_mcp.process`
- `xdebug.cpp_unit`
- `xdebug.session`
- `xdebug.contract`
- `xdebug.mcp_direct`
- `skills.xverif`
- `skills.xverif_admin`

每个 focused suite 执行前必须查询当前 catalog gate membership 和 execution environment；涉及
NPI、FSDB、MCP process、VCS、VIP 或真实 EDA 的测试统一在 host 执行。

## 9. 开源调研计划

后续调研按问题而不是按项目罗列：

1. 每 session/单位对象一个状态文件并通过目录枚举：关注 systemd runtime state 等实现。
2. 单 writer 日志与多进程收集：关注 systemd-journald、Python logging listener、异步日志库。
3. immutable content-addressed publish：关注 Git object store、Bazel/BuildKit/Nix cache。
4. 生命周期 reservation 与 CAS：关注 Git ref lockfile、runtime directory、lease/claim 模型。
5. 明确反例：SQLite WAL、通用 file lock、全局 daemon 等方案为何不适合直接放进 action 热路径。

调研结果必须引用上游官方文档或真实源码位置，并明确区分：

- 可直接复用的模式；
- 需要适配 xverif session/EDA 特性的模式；
- 因全局锁、后台 daemon、数据库依赖或共享文件系统语义而不采用的模式。

## 10. 进度记录

- 2026-08-12：完成全仓 `flock` 静态清单、普通 action 锁成本模型、已有并发保证审计、
  per-session registry 设计和六阶段实施方案。
- 2026-08-12：用户确认允许 session open/close 生命周期保留按 session `flock`，其余 action
  路径目标为零 `flock`。
- 2026-08-12：开始开源实现与官方资料调研。
- 2026-08-12：完成 systemd、Git、Python logging、Bazel remote cache 和 SQLite 的官方文档/
  源码调研，形成采用、适配和不采用结论；没有修改产品源码。

## 11. 开源实现调研方法与版本

本轮只把上游官方文档和真实源码作为架构证据。源码克隆位于工作区之外的临时研究目录：

```text
<work-root>/xverif-flock-oss.<temporary-id>/
```

已检查版本：

- systemd：`40315add9176d2a7c28d8d90490f74e9e982e87b`
- Git：`11c6700f10234578d10523faf35656ca491425c9`
- ccache：远端 HEAD 为 `aa5642289037ab1998f4d4815e5b2c4244e1b560`，但 checkout 两次因
  GitHub TLS `SSL_ERROR_SYSCALL` 未完成，因此不把 ccache 工作树作为本报告结论依据，也没有切换
  非官方镜像。

官方资料：

- [systemd session 状态保存源码](https://github.com/systemd/systemd/blob/40315add9176d2a7c28d8d90490f74e9e982e87b/src/login/logind-session.c#L337-L443)
- [systemd session 目录枚举源码](https://github.com/systemd/systemd/blob/40315add9176d2a7c28d8d90490f74e9e982e87b/src/login/logind.c#L542-L577)
- [systemd-journald native socket 源码](https://github.com/systemd/systemd/blob/40315add9176d2a7c28d8d90490f74e9e982e87b/src/journal/journald-native.c#L521-L558)
- [Git immutable object 发布源码](https://github.com/git/git/blob/11c6700f10234578d10523faf35656ca491425c9/object-file.c#L381-L454)
- [Git lockfile 退避源码](https://github.com/git/git/blob/11c6700f10234578d10523faf35656ca491425c9/lockfile.c#L168-L251)
- [Python Logging Cookbook：多进程日志](https://docs.python.org/3.10/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes)
- [Bazel remote cache：Action Cache 与 CAS](https://bazel.build/remote/caching)
- [SQLite WAL 并发与限制](https://www.sqlite.org/wal.html)
- [SQLite 文件锁模型](https://www.sqlite.org/lockingv3.html)

## 12. 各类开源方案怎么解决类似问题

### 12.1 systemd-logind：每对象状态文件、目录枚举、原子替换

systemd-logind 为每个 session 使用 `/run/systemd/sessions/<id>` 独立状态文件，而不是把所有
session 放进一个全局 JSON。`session_save()` 写临时文件，再用 replace 语义把完整文件原子发布；
manager 启动恢复时遍历 `/run/systemd/sessions`，按文件名创建 session 并逐个加载。单个文件创建
或反序列化失败时记录告警并继续枚举，不会阻断其它 session。

这与用户提出的 registry 简化方向高度一致，能够直接解决：

- 不同 session 的状态写互不覆盖；
- query 可按 session id 直接定位，不扫描全局 registry；
- list 才遍历目录；
- 单条损坏被限制在一个 session；
- 原子替换继续提供 crash consistency，不需要为纯读取加锁。

差异也必须保留：logind 是一个长期运行的 manager，天然拥有 session 状态单写者；xverif 的
open/close 可由多个 helper process 发起。因此 xverif 不能照搬为完全无锁，仍应在 open、close、
kill、gc 和 timeout containment 中持有对应 session 的 lifecycle lease。

systemd 在 session 释放时直接删除运行时状态文件。xverif 不能照搬删除语义，因为 timeout、
cleanup failure、generation 防误杀和 doctor 诊断需要 tombstone。xverif 应保留 `closed`/terminal
record，并让默认 list 跳过，而不是立即 unlink。

### 12.2 Git：不可变内容无锁竞争发布，可变引用只锁局部对象

Git object 以内容 hash 命名。新 object 先写临时文件，再通过 `link()` 抢占最终名称；目的文件
已经存在时检查碰撞，内容一致即可接受。这允许两个 writer 同时生成相同不可变对象，不需要一个
覆盖整个 object store 的全局锁。

Git 对可变 ref 采用另一条路径：只为目标 ref 创建相邻 `.lock` 文件，使用原子 exclusive-create
取得所有权，完成后 rename 提交；冲突时进行有上限的随机二次退避。它锁的是具体 ref，不是整个
repository。

对 xverif 的启示：

- session 的 `state.json` 是可变指针，只在该 session 生命周期写操作上互斥；
- generation 历史、完成后的 URG artifact 和 fixture generation 应视为不可变对象，用唯一 staging
  加原子发布；
- cache lookup 只校验 immutable entry 与 `COMPLETE`，不取得 key lock；
- 不应把 Git 的 `.lock` 文件原样替换 lifecycle `flock`。lockfile 在进程崩溃后会遗留 stale file，
  还需要 PID/owner 检查；内核 `flock` 会随 fd/process 退出释放，对短暂的 session open/close 临界区
  更简单可靠。

### 12.3 systemd-journald 与 Python logging：共享日志使用单 writer

systemd-journald 让 producer 通过 Unix datagram socket 发送消息，由 journald event loop 接收并在
manager 内集中调用 journal append。Python 官方 Logging Cookbook 同样明确：标准库不支持多个
process 直接安全写同一个日志文件，推荐通过 `SocketHandler` 或 `QueueHandler` 汇聚到单独 listener，
由一个 writer 写文件。

两者的共同原则不是“多个 writer 抢更快的锁”，而是消除共享 writer。对 xverif 有两种实现形态：

1. 全局日志 daemon/listener：模式成熟，但新增可用性、启动、权限、backpressure 和 cleanup 合同；
2. owner shard：每个 helper/engine/MCP manager 只写自己的 NDJSON，doctor/bundle/read 时聚合。

本方案选择 owner shard。它保留多进程独立性，不引入一个新的全局故障点；已有 MCP manager 内部
可以继续用进程内 mutex/queue，但不要求所有 CLI action 依赖常驻 daemon。每条 JSON 必须通过一次
`O_APPEND` write 发布，rotation/压缩移出 action 返回链路。

### 12.4 Bazel remote cache：可变索引与不可变 CAS 分离

Bazel remote cache 将 action cache 与 content-addressable store 分开：action key 指向输出元数据，
实际文件/目录内容按 digest 存入 CAS；cache miss 执行后上传，cache hit 直接取 immutable result。

这验证了 xcov URG cache 应把两类数据分开：

- immutable artifact：按完整输入 digest 定位，发布后不再原地修改；
- mutable metadata：access time、LRU、容量统计、claim heartbeat，不参与 hit 的正确性判定。

不过不能直接采用“允许重复构建、先发布者获胜”：URG 构建昂贵且消耗 license，同 key 重复执行不
可接受。因此 cold miss 仍需 `mkdir` 原子 claim、owner heartbeat 和 stale takeover；只是 follower
等待 claim/`COMPLETE`，而 hit 不进入 claim、cleanup 或 eviction。

### 12.5 SQLite WAL：适合事务状态，但不是去锁方案

SQLite WAL 能让 reader 与 writer 并行，但官方文档明确同一 WAL 同时只能有一个 writer；WAL index
依赖共享内存，因此不支持 network filesystem。SQLite 的非 WAL 模式同样通过 SHARED、RESERVED、
PENDING、EXCLUSIVE 等 OS 文件锁实现并发，繁忙和恢复路径会返回 `SQLITE_BUSY` 或持有 exclusive
lock。

因此把全局 registry JSON 换成一个 SQLite database，只是把当前全局 `flock` 迁移成数据库内部的
单写者锁与 checkpoint/recovery 复杂度。它不能满足“普通 action、list、doctor 不因共享锁产生尾
延迟”，也会给共享 home/NFS 带来新的运行环境约束。本方案不采用 SQLite 作为 registry、日志或
activity store。

## 13. 调研后的最终架构判断

### 13.1 可直接采用

- systemd 模式：每 session 独立状态文件、目录枚举、单条损坏隔离、临时文件原子替换。
- Git 模式：immutable generation/artifact 使用唯一 staging 和原子 publish；重复完整对象幂等。
- 单 writer 原则：日志按 owner 分片，读路径聚合。
- Bazel 模式：immutable payload 与 mutable index/access metadata 分离。

### 13.2 需要针对 xverif 适配

- open 前必须写 `opening` reservation，不能等 close 时才首次记录，否则同名并发 open 无法仲裁。
- open/close/kill/gc/timeout containment 保留 per-session `flock`，普通 action 不取得它。
- close 不删除记录，而是发布 `closed` 或 terminal tombstone；默认 list 跳过 closed。
- URG 不允许同 key 乐观重复构建，需要原子 claim 和可诊断 stale takeover。
- owner-sharded 日志需要稳定 owner id、单调 event sequence 和确定性聚合排序。

### 13.3 明确不采用

- 一个 SQLite/WAL 全局 registry：仍然单 writer、仍有 OS locks/`SQLITE_BUSY`，且共享文件系统受限。
- 一个新的全局日志 daemon 作为所有 action 的强依赖：增加全局故障点；owner shard 已足够。
- Git 式 stale `.lock` 文件替代 session lifecycle `flock`：crash cleanup 更复杂，没有稳定性收益。
- query 成功后同步写 durable `last_active`：即使拆成 per-session file，也会把元数据写和 `fsync`
  留在 action 返回路径。
- “只在 close 时才创建 session 状态”：无法防止并发 open，也无法在 open crash 后留下可恢复证据。

## 14. 对用户方案的最终回答

“每个 session 一个文件夹，下属一个文件记录状态，session 查询按需定位、list 遍历；close 后记录
closed，遍历时默认跳过”是比全局 registry 更简单、隔离性更好的主方向，并且有 systemd-logind
的成熟实现作为旁证。

需要做两点修正：

1. query 不应遍历全部 session；它应由规范化 session id/hash 直接定位 `state.json`。只有 list、
   doctor-all 和 gc 才遍历。
2. 状态不能只在 close 时记录。open 必须先在 per-session lifecycle `flock` 内发布 `opening`，成功
   后发布 `active`；close 再发布 `closing -> closed/terminal`。这样才能同时保证并发 open 仲裁、
   generation 安全、open crash 恢复和稳定诊断。

由此得到最终锁边界：

```text
允许 flock：session open / close / kill / gc / timeout containment
禁止 flock：普通 action / query / list / doctor / config / log / cache hit
```

这不是把保险全部撤掉，而是把互斥约束放回真正改变生命周期的局部临界区。普通 action 已由每
session 单 engine、engine 串行请求、NPI mutex、MCP session lock、generation/resource identity
检查和原子文件发布提供足够保证，不需要再用 `flock` 保护日志、activity touch 或只读 snapshot。

## 15. 已确认实施决策

- 基线 commit：`beef27235abccb2a39f1dd346e033d116fea26f8`。
- registry 升级采用停机切换：禁止新旧 engine 混跑；非空 v3 registry 明确返回
  `REGISTRY_MIGRATION_REQUIRED`，空 v3 registry 才允许原子归档。
- 最终测试独立运行 fast、regression、nightly 三档门禁。
- 初始约束是不执行 `--xverif-prepare`；F06 确认唯一缺口后，用户明确授权克制重建，因此只对
  `xdebug.stream_differential_tool` 执行一次精确 prepare。仍不执行会扩大重建范围的
  `--xverif-fixture-validation`。
- cache miss、fixture fingerprint mismatch 或 required fixture 缺失时先停止并审计；除用户随后
  明确授权的单一精确 prepare 外，不扩大重建范围、不 fallback、不把 required suite 改为 skip。
- 采用分阶段中文详细提交，不创建 PR，不推送远端。
- `kill`、`gc` 和 timeout containment 不建立新的锁类别，统一复用 session close/cleanup
  生命周期临界区。

## 16. 实施提交与进度

| 阶段 | 内容 | 状态 | 提交 |
| --- | --- | --- | --- |
| F00 | 计划、基线与 goal | completed | `27da5d4` |
| F01 | per-session registry 与 action 热路径 | completed | `38eea24` |
| F02 | xdebug config 与 owner-sharded logging | completed | `c224b16` |
| F03 | xcov 与 MCP owner logging | completed | `393a276` |
| F04 | URG cache 与 fixture atomic claim | completed | `918ab52` |
| F05 | 静态/strace 门禁、文档与 skill | completed | `eb1d9f8` |
| F06 | clean build、三档全量回归与最终证据 | completed | `7160694`、`8c94793`、最终证据提交 |

最终必须满足：产品和 testinfra 源码中只有 session lifecycle lease 实现可以引用 `flock`；普通
query、list、doctor、config、log 与 xcov cache hit 的 `strace -f -e trace=flock` 结果为零。

### 2026-08-12 F01 验证

- `make -C xdebug all -j4`：通过。
- `xdebug.cpp_unit`：通过，1 suite passed。
- `xdebug.static`：119 passed。
- `xdebug.session`：39 passed；使用正式 regression suite 和既有 fixture cache，没有 prepare。
- registry 已改为每 session `state.json`；关闭 generation 归档到 `history/`；query/doctor 不再取得
  lifecycle lease；activity 使用独立 marker。

### 2026-08-12 F02 验证

- VersionedJsonStore 去除跨进程 `flock`，保留临时文件、`fsync` 和原子 rename；cursor、stream、
  protocol config 的生产写入仍由每 session 单 engine 的串行 action loop 承担。
- xdebug public/engine 日志改为
  `sessions/<session>/owners/<pid-start_nonce>/logs/*.ndjson`；每个进程只写自己的 shard，进程内
  mutex 保证线程写入完整，tail、doctor、普通 bundle 与 redacted bundle 遍历聚合全部 shard。
- NPI startup capture 与 lifecycle 日志使用同一个 engine owner shard；frontend 和 engine 分属不同
  owner 是预期行为，不再假设一个 session 只有一个日志文件。
- `make -C xdebug all cpp-unit-binaries -j4`：通过。
- `xdebug.cpp_unit`：通过，1 suite passed；包含 owner shard 多进程聚合与 config 原子写验证。
- `xdebug.session`：39 passed；使用正式 regression suite 和既有 fixture cache，没有 prepare。

### 2026-08-12 F03 验证

- xcov 日志 owner id 从裸 PID 升级为 fork-safe 的 `pid-start_nonce`；manifest 位于 owner 目录，
  NDJSON 由进程内 mutex 串行追加，不再取得跨进程 `flock`。
- MCP 与 SDK-free loop logger 使用运行实例 owner shard；logger 即使被 fork 继承也会检测 PID 变化并
  生成新 owner id。server、UDS、session、stdio 与 LSF 日志都不再共享一个写入文件。
- `xcov.unit`：169 passed。
- `xverif_mcp.unit`：178 passed。
- `xverif_mcp.process`：141 passed；使用正式 host regression suite，没有 prepare。

### 2026-08-12 F04 验证

- URG cache hit 只校验 immutable entry、manifest、`COMPLETE` 和 artifact hash，不写 access marker、
  不清理、不驱逐、不取得锁。
- cold miss 使用 `claims/<key>/` 原子 mkdir 选出唯一 builder；follower 等待 `COMPLETE`，claim 超时和
  超过 24 小时的 stale takeover 都返回或保留明确证据。构建仍经唯一 staging、完整校验、fsync 和
  rename 发布。
- action 路径不再做 LRU eviction。容量已满返回 `XCOV_CACHE_CAPACITY_EXCEEDED`，清理由显式维护窗口
  处理，避免 query/action 为其它 cache entry 付出同步删除延迟。
- fixture prepare 在 cache hit 时直接验证并返回；cache miss/rebuild 使用每 fixture 原子 mkdir claim，
  follower 只等待发布。`current.json` 改用唯一临时文件、fsync 和原子 rename，消除固定 temp 名竞争。
- `xcov.unit`：169 passed，包含同 key concurrent miss 仅执行一次 runner、容量硬失败和 stale staging
  清理验证。
- `testinfra.unit`：52 passed，包含两个并发 prepare 只执行一次 builder；本轮没有调用任何正式
  `--xverif-prepare`，没有重建 fixture cache。

### 2026-08-12 F05 验证

- `testinfra.unit` 新增跨产品源码静态 allowlist：只有
  `xdebug/src/engine/session/session_lifecycle_lease.h` 可以调用 `flock`；xdebug、xcov、MCP 与
  fixture 产品源码的其它位置出现调用会使门禁失败。
- 使用独立临时 HOME 执行 `strace -f -e trace=flock`：`actions`、`session.list`、不存在 session
  的 `session.doctor`、`stream.config.list`、`axi.config.list` 均为 0 次 `flock`。后 3 个请求按
  合同返回资源/session 错误，没有 fallback；trace 证据位于
  `<temporary-dir>/xverif-flock-strace.5tr0ya`。
- 同步更新 xdebug embedded help、README、xdebug agent 说明、xcov/MCP README、xverif 与
  xverif-admin references，明确 per-session registry、owner shard 和 cache claim/容量合同。
- `testinfra.unit`：53 passed；`xdebug.static`：119 passed；`skills.xverif`：16 passed；
  `skills.xverif_admin`：1 passed。
- 已通过 Makefile 安装并逐目录验收 `xverif`、`xverif-admin` 到 `~/.codex/skills` 与
  `~/.claude/skills`。

### 2026-08-12 F06 初次验收阻塞记录

- 根目录 `make clean && make all -j4`：通过。`clean` 只清理构建产物，没有删除或准备 fixture
  cache。
- fast 全量 gate：574 passed。首次运行因本文档记录真实临时路径触发静态门禁，改为抽象
  `<temporary-dir>` 后从同一正式入口重跑通过。
- host regression：required suite preflight 在收集前停止，缺失当前指纹的
  `xdebug.stream_differential_tool` fixture cache；0 tests executed。
- host nightly：同一 required fixture preflight 在收集前停止；0 tests executed。
- 后续使用 `Catalog.select_gate()` 与 `FixtureStore.resolve()` 做只读全量依赖审计：regression 的
  18 个 required fixture 中 17 个当前有效，nightly 的 27 个中 26 个当前有效；两档唯一缺口均为
  `xdebug.stream_differential_tool`。该 fixture 当前期望指纹前缀为 `459101d9c140`，已有
  `current.json` 指纹前缀为 `49e0a000589e`，确认不是 preflight 只报告首个错误而掩盖其它缺口。
- 阻塞是本次 xdebug 源码变更必然改变该 tool fixture 的 fingerprint，而现有 `current.json` 仍指向
  旧 generation。完成 regression/nightly 必须显式运行
  `pytest --xverif-prepare xdebug.stream_differential_tool`，这会重建缓存，与本任务“不要触发缓存
  重建”的硬约束冲突，因此没有执行，也没有切换 runner、fixture 或测试层级。

### 2026-08-13 F06 授权后最终验收

- 用户明确授权“允许重建，但是要克制”后，仅执行一次正式入口
  `pytest --xverif-prepare xdebug.stream_differential_tool`。发布 fingerprint 为
  `459101d9c14005d6b2704a26b50223a137ad328026f2ae0eb0620ce31ee3f9bb`；重建后只读审计确认
  regression 的 18 个、nightly 的 27 个 required fixture 均无缺口，且时间窗口内只有该 fixture
  的 `current.json` 更新。没有运行 `all-generated` 或全量 fixture validation。
- 第一轮 host regression 真正执行 1173 项并暴露 7 项失败：5 项来自 contract helper 仍写 v3
  全局 registry，1 项来自 heartbeat 固定睡眠，1 项来自 LSF rejection 与 pipe reader 的 job id
  竞态。修正在 `7160694` 提交；正式 focused suite 分别通过 `xdebug.contract` 114、
  `testinfra.unit` 53、`xverif_mcp.process` 141。
- 修正后 host regression 全量通过：1173 passed，结果目录
  `.xverif-test-results/20260812-233732-23uc9oeh`。
- 第一轮 host nightly 的产品、NPI 与 fixture 尚未进入唯一失败点：MCP SDK 在 pytest `tee-sys`
  捕获下取得不支持 `fileno()` 的 stderr 对象。`8c94793` 仅让真实 wire 测试显式使用
  `sys.__stderr__`，没有改变 server、backend 或 transport；focused real fullchain 1 passed。
- 修正后 host nightly 全量通过：1274 passed、2 skipped，结果目录
  `.xverif-test-results/20260812-235449-v_bikaab`。两个 skip 均来自 catalog 声明的 `real_lsf`
  可选依赖，宿主缺少 `bsub`、`bjobs`、`bkill`；没有把 required suite 降级为 skip。
- 最终 fast 全量重跑通过：574 passed，结果目录
  `.xverif-test-results/20260813-000517-i0ubhbch`。
- nightly 的 native XOUT 采集会把运行时路径、PID、时间戳写回历史审阅文档；两轮均在测试结束后
  对该已确认副作用应用精确逆补丁，没有保留动态证据或覆盖用户改动。
- 最终源码审计仍只有 `xdebug/src/engine/session/session_lifecycle_lease.h` 两处 `flock()` 调用，分别
  对应生命周期 lease 的加锁与解锁；普通 action/query/list/doctor/config/log/cache hit 没有新增
  `flock`。工作树在最终记录前为干净状态。
