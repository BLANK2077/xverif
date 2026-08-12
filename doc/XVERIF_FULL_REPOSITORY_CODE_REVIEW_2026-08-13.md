# xverif 全仓库代码与架构深度审查

## 1. 文档状态

- 审查日期：2026-08-13
- 审查基线：`63bec29d6f3565eef2773850cbb321a03960ae3f`
- 分支：`master`
- 初始工作树：干净
- 执行边界：只读审查；不修改源码、配置、schema、skill 或测试；不提交、不推送
- 允许写入：本报告，以及 `xverif/tmp/` 下不进入产品树的临时验证证据
- 当前阶段：R11 已完成

## 2. 审查目标

对 xverif 仓库进行全代码、全架构、全合同、全生命周期、全测试基础设施的系统审查，识别能够由
真实源码、合同、调用链、测试或运行证据支持的问题。审查不以代码风格罗列为目标，优先寻找：

1. 会产生错误结果、数据损坏、进程泄漏、死锁、竞态、越权访问或不可恢复状态的缺陷。
2. 公共 schema、CLI、MCP、native runtime、文档和 skill 之间的合同漂移。
3. session、transport、日志、缓存、fixture、LSF、NPI 资源生命周期中的一致性和恢复缺陷。
4. 架构边界模糊、重复 source of truth、隐式 fallback、失败被吞掉和观测性缺口。
5. 测试矩阵无法覆盖的高风险路径、伪确定性、共享状态污染和环境耦合。
6. 性能、可扩展性、可维护性问题；只有具备明确影响路径时才列为 finding。

## 3. 验收标准

最终报告必须满足：

- 覆盖所有主要产品目录：`xdebug`、`xcov`、`xbit`、`xentry`、`xloc`、`xsva`、`xwaveform`、
  `xverif_mcp`、`testinfra`、`skills` 及根级构建/打包/配置。
- 覆盖 C/C++、Python、SystemVerilog/fixture、YAML/JSON schema、shell/Makefile、Markdown 合同。
- 建立从入口、adapter、schema、handler、engine/backend、持久化、输出到测试的关键调用链。
- 每个正式 finding 包含严重级别、证据文件与行号、触发条件、影响、根因和建议修复方向。
- 区分“已证实缺陷”“高可信风险”“设计债务”“测试缺口”，不把猜测写成事实。
- 对候选问题做反证：搜索现有保护、调用方约束、测试覆盖和错误处理，避免重复或误报。
- 检查最近提交与当前架构是否引入回归，但审查范围不限于最近提交。
- 如执行测试，只使用仓库正式入口；真实 NPI/VCS/VIP/LSF 动作遵守 host 边界，不 prepare、
  不重建 fixture、不 fallback。临时脚本或输出只放在 `xverif/tmp/`。
- 最终再次确认除本报告外没有仓库改动；不进行 commit 或 push。

## 4. 严重级别

- P0：可直接导致广泛数据破坏、安全边界突破或核心功能不可用，且缺少有效缓解。
- P1：高概率产生错误结果、资源泄漏、并发一致性破坏或稳定性事故。
- P2：在合理条件下产生合同错误、错误诊断、性能退化或维护风险。
- P3：局部设计债务、低概率边界问题或明确测试缺口。

只有能够给出可验证触发路径的项目进入 P0-P2；其余放入观察项，不混入正式 finding。

## 5. 分阶段计划

| 阶段 | 内容 | 输出/验收 | 状态 |
| --- | --- | --- | --- |
| R00 | 冻结基线、规则、范围与方法 | 本文档、goal、工作树基线 | completed |
| R01 | 仓库清点与架构地图 | 语言/文件/LOC、入口、依赖、生成物、测试 catalog、信任边界 | completed |
| R02 | 根级构建、打包、发布与配置审查 | Makefile、pyproject、环境变量、安装、路径和版本合同 | completed |
| R03 | xdebug 全链路审查 | CLI/schema/handler/engine/session/transport/log/cache/NPI/输出 | completed |
| R04 | xcov 全链路审查 | session/backend/NPI/URG/exclusion/export/cache/输出 | completed |
| R05 | MCP 与 SDK-free 审查 | tool projection、adapter、stdio/UDS/LSF、timeout、cleanup、日志 | completed |
| R06 | 确定性工具审查 | xbit/xentry/xloc/xsva/xwaveform 的解析、数值和边界合同 | completed |
| R07 | testinfra 与 fixture 审查 | catalog、gate、缓存、并发 claim、环境、报告、测试隔离 | completed |
| R08 | schema、example、doc、skill 一致性审查 | source of truth、生成同步、公开参数、链接和示例覆盖 | completed |
| R09 | 横向安全与可靠性审查 | 输入验证、命令执行、路径遍历、权限、敏感信息、原子性、竞态 | completed |
| R10 | 静态/动态验证与候选反证 | 正式 gate/check、定向只读 probe、候选问题去伪存真 | completed |
| R11 | 最终报告与优先级排序 | findings、架构结论、测试缺口、修复路线、最终边界审计 | completed |

## 6. 审查方法

### 6.1 静态清点

- 用 `rg --files`、`git ls-files` 和语言后缀统计受版本控制的真实源码，排除 cache/result/tmp。
- 读取 README、Makefile、pyproject、catalog、schema generator 和架构文档，建立 source-of-truth 图。
- 搜索高风险模式：subprocess/shell、临时文件、rename/fsync、锁、线程/进程、signal、timeout、
  broad exception、silent ignore、环境变量、绝对路径、JSON 解析、整数/时间单位和资源释放。

### 6.2 调用链审查

- 从公开 CLI/MCP action 进入 schema/adapter/handler，再到 engine/backend/persistence/output。
- 对 session open/query/close、timeout、crash、stale state、并发 open、cleanup 逐状态检查。
- 对缓存 hit/miss、claim、publish、corruption、capacity、stale takeover 检查原子性和失败闭合。
- 对 NPI handle、database、子进程、socket、文件描述符和线程检查所有成功/失败路径的释放。

### 6.3 合同审查

- 对照 action catalog、request/response schema、example、native CLI、MCP projection、skill reference。
- 检查参数是否真正生效，错误是否 typed，输出是否可区分完整/截断/未知/失败。
- 检查生成器与 checked-in 产物、runtime validator 兼容性和 additionalProperties 约束。

### 6.4 验证策略

- 优先复用现有静态检查与 fast gate；必要时按 catalog 选择 focused suite。
- 不执行 fixture prepare 或 validation rebuild；缓存缺失即记录，不改变入口或测试层级。
- 需要自定义只读 probe 时，脚本、临时 HOME 和输出均放入 `xverif/tmp/review-2026-08-13/`。
- 动态失败必须区分环境、测试基础设施和产品缺陷，并保存可复核命令与结果摘要。

## 7. 最终报告结构

1. 执行摘要与总体风险判断。
2. 架构地图与关键数据/控制流。
3. 按 P0/P1/P2/P3 排序的正式 findings。
4. 各子系统审查结论，包括无 finding 但已检查的边界。
5. 横向合同、安全、并发、性能、可维护性结论。
6. 测试和工具证据、未覆盖项与环境限制。
7. 分阶段修复建议；只给方向，不修改代码。
8. 基线和最终工作树审计。

## 8. 进度记录

### 2026-08-13 R00

- 已读取根 `AGENTS.md`，确认没有更深层 `AGENTS.md` 覆盖。
- 已冻结 commit、分支和干净工作树边界。
- 已创建本计划；下一步建立 goal，然后执行 R01 仓库清点。

### 2026-08-13 R01-R09

- 清点 2,145 个受版本控制文件，按仓库主要语言后缀统计约 73.6 万行；其中产品代码和测试的
  Python/C/C++/SystemVerilog 主体约 21 万行。
- 复核最近 12 个提交，重点跟踪 session registry、flock、owner-shard 日志、原子 claim、
  全仓测试门禁及其文档收口。
- 建立入口到 backend、持久化和输出的关键调用链，并逐项反查 schema、example、skill 和测试。
- 对旧审查报告的候选项逐一反证；随机数 fail-closed、batch 生命周期递归保护、64 MiB block I/O、
  cache metadata 预算/清理等旧问题已在当前基线修复，不重复列入本报告。

### 2026-08-13 R10-R11

- 正式 fast gate：574 passed，697 deselected，52.30 s。
- 八个无 fixture 重建的 focused suite：542 passed，729 deselected，37.80 s。
- 三项 schema generator check、runtime Draft-7 audit、283 个 schema 校验、229 个 example 和
  7 个 invalid witness 校验全部通过。
- 在 `tmp/review-2026-08-13/` 完成 xbit、xsva、URG cache 并发和 MCP batch 同文件定向 probe。
- 最终确认 8 项正式 finding：5 项 P1、3 项 P2；没有 P0。

## 9. 执行摘要

当前基线的总体架构边界清楚，尤其是最近一轮 flock 优化已经把 action 热路径上的跨进程文件锁
移除：session registry 已拆成每个 session 独立目录和 `state.json`，查询按目录读取；日志采用
owner shard 单写者；URG/fixture 构建采用原子 claim。全仓搜索只剩
`session_lifecycle_lease.h` 中一处 `flock(LOCK_EX)` 和析构解锁，它仅由 session open/close/kill
调用，符合“flock 只存在于 session 生命周期”的既定目标。

本轮没有发现 flock 回归，但发现 8 个与它无关、具有明确触发路径的问题。最优先的是 xbit
错误的 SystemVerilog 数值语义、MCP 的写能力分类失效、MCP batch 输入输出同文件导致自增写，
以及 AXI/stream 导出缺少原子发布。这些问题可能产生错误计算、突破部署者预期的只读边界、
耗尽磁盘，或留下半套导出物。其次是 xsva evidence 信号提取、URG cache 容量并发超限，以及
MCP session 恢复操作被长查询锁住。

## 10. 架构地图与信任边界

```text
CLI / MCP client
  ├─ stateless: xbit / xentry / xloc / xsva / xwaveform
  ├─ xdebug adapter ─ schema/catalog ─ native frontend ─ per-session registry
  │                                           └─ engine ─ NPI/FSDB/daidir
  ├─ xcov adapter ─ stdio loop ─ backend ─ VDB/NPI 或 URG summary cache
  └─ xverif_loop manager ─ process/UDS/file/LSF transport ─ session lifecycle

testinfra catalog ─ gate selection ─ fixture fingerprint/claim/publish ─ pytest report
```

主要信任边界包括 MCP client 提供的路径和 action 参数、native JSONL、EDA/LSF 子进程、
FSDB/VDB/daidir 外部数据库、跨进程 session 状态、缓存与导出物。系统已经较好地实现严格 JSON、
schema fail-closed、ownership token 脱敏、资源 provenance、生成物同步检查和 fixture 显式 prepare；
本报告的问题主要位于这些边界之间尚未统一的语义或发布协议。

## 11. 正式 findings

### 11.1 XBIT-COR-01（P1，已证实）：混合 signed/unsigned 表达式按有符号计算

- 证据：[`xbit/src/xbit/ops.py`](../xbit/src/xbit/ops.py) 第 134-157、179-195 行使用
  `a.signed or b.signed` 决定算术和比较的符号性，并在统一位宽之前读取整数值。
- 触发：任一 operand 为 signed、另一 operand 为 unsigned，例如 `8'shff < 8'h01`。
- 复现：公开 evaluator 返回 true；按 SystemVerilog 混合 operand 规则应按 unsigned 比较，
  即 255 < 1 为 false。
- 影响：比较、加减乘除和取模都可能生成错误结果，且结果看起来是确定性的正常成功。
- 根因：把“存在 signed operand”误写成“表达式为 signed”，缺少统一的 SV sizing/sign coercion 层。
- 建议：先扩展到共同位宽，再按 SV 自决定/上下文决定规则统一解释符号；建立 signed/unsigned、
  不同位宽、unsized literal 的交叉测试矩阵。

### 11.2 XBIT-COR-02（P1，已证实）：除法经 float 丢精度，取模符号不符合 SV

- 证据：同一文件第 147-154 行用 `int(av / bv)` 和 Python `%`。
- 复现：`64'hffffffffffffffff / 64'd3` 得到 `0x5555555555555400`，正确值是
  `0x5555555555555555`；`-32'sd5 % 32'sd3` 得到 +1，SV 截零商对应的余数应为 -2。
- 影响：超过 53 位精确整数的除法静默错误；负数模运算也静默错误。
- 根因：任意精度整数被转换为 IEEE-754 double；Python `%` 的余数符号跟随 divisor，
  而不是以截向零 quotient 定义。
- 建议：用纯整数实现截向零的 quotient，再用 `remainder = a - quotient * b`；覆盖 64/128 位、
  正负组合、最小负数和零除。

### 11.3 MCP-POLICY-01（P1，高可信合同缺陷）：声明的只读默认策略没有约束实际写能力

- 证据：[`tool_policy.py`](../xverif_mcp/src/xverif_mcp/tool_policy.py) 第 22-59 行把
  `write_enabled` 固定为 false，但没有解析写开关；[`server.py`](../xverif_mcp/src/xverif_mcp/server.py)
  第 135-198 行向所有 tool 注入可覆盖/追加任意路径的参数，所有现有 decorator 又都沿用
  `write=False`。同文件第 1160 行起的 catalog 也没有给 session open/close/kill/gc、exclusion、
  export、batch 等能力标记 `write`。
- 合同冲突：[`xverif_mcp/README.md`](../xverif_mcp/README.md) 第 470-486 行宣称 read-only 默认开放、
  write tool 默认不暴露；第 201-222 行却说明每个 tool 都可覆盖任意输出路径。
- 触发：以默认 policy 启动 MCP，调用 session 生命周期、持久化 exclusion/export、batch，或给任一
  tool 传 `xverif_output_path`。
- 影响：部署者看到 `write_enabled=false` 仍无法得到只读 server；MCP client 可修改进程/session
  状态并写 server 身份可访问的文件，形成策略绕过和覆盖风险。
- 根因：group exposure、业务 mutation、artifact output 三种不同权限被压成一个从未真正使用的布尔值。
- 建议：建立显式 capability 分类；每个 tool/action 声明 mutation 和 artifact-write，默认禁用；
  输出只能落入配置的 artifact root，使用 create-new/原子发布；启动时严格解析独立写开关。

### 11.4 MCP-BATCH-01（P1，已证实）：batch 输入输出同文件会自反馈追加直至资源耗尽

- 证据：[`server.py`](../xverif_mcp/src/xverif_mcp/server.py) 第 374-450 行持续迭代输入文件，
  第 218-233 行对输出逐行 append，未检查路径或 inode 是否相同。
- 复现：一个只含一行 `xverif_ping` 的文件同时作为两参数；在 1 MiB file-size 限制下增长到
  1,048,576 bytes、3,917 行才停止。新增的结果行又被当成下一条 batch 输入，失败结果也继续追加。
- 影响：无 file-size 限制时可长期占用 MCP worker、重复调用 tool 并耗尽磁盘；如果原始 tool 有副作用，
  还可能被非预期重复执行。
- 根因：流式读取和 append 发布没有对象身份隔离，也没有先冻结输入快照。
- 建议：打开后用 device/inode（并覆盖 symlink/hardlink）拒绝同一对象；输出默认 create-new；
  更稳妥的是在同目录临时文件完整生成后原子发布，并设置最大行数/输入字节/输出字节预算。

### 11.5 XDEBUG-EXPORT-01（P1，高可信数据完整性缺陷）：AXI/stream 导出不是原子 artifact-set

- 证据：[`axi_exporter.cpp`](../xdebug/src/waveform/axi/axi_exporter.cpp) 第 26-46、167-196 行忽略
  `mkdir` 错误并依次截断三个目标文件，写完后不检查 stream 状态；
  [`stream_exporter.cpp`](../xdebug/src/waveform/stream/stream_exporter.cpp) 第 20-76、81-206 行也直接截断
  data/meta，且返回值主要取决于 meta 写入入口是否成功。
- 反证：[`apb_exporter.cpp`](../xdebug/src/waveform/apb/apb_exporter.cpp) 第 206-280 行已有 collision check、
  同目录临时文件、close 后状态检查、create-new publication 和失败回滚，证明仓库内已有正确模式。
- 触发：相同 prefix 重试/并发导出、目标已存在、ENOSPC、延迟 I/O 错误或中途进程退出。
- 影响：覆盖既有结果、多个 writer 交错、返回成功但数据不完整，或只留下 data/meta 的一部分。
- 根因：三种协议 exporter 没有共享 artifact-set 发布抽象，安全语义发生漂移。
- 建议：抽出公共 atomic artifact publisher；同目录临时写、逐文件 close/fsync 检查、create-new 发布、
  全组 rollback、目录 fsync，并增加 collision/ENOSPC/concurrent writer/fault-injection 测试。

### 11.6 XSVA-COR-01（P2，已证实）：sampled function 和层次信号依赖提取错误

- 证据：[`expr_parser.py`](../xsva/xsva/parser/expr_parser.py) 第 72-125 行记录 sampled function 的
  inner text，却不递归提取其中信号；第 127-179 行构造层次路径后没有把主 cursor 前移到路径末端，
  select 后的层次位置计算也错误。下游 [`sequence_to_timeline.py`](../xsva/xsva/lower/sequence_to_timeline.py)
  第 36-39、338-419 行直接把该列表作为 `signals_to_query`，并假设 `$past` 总有 dependency[0]。
- 复现：`$past(top.u_bus.data[3:0],2)` 的 signals 为 `[]`；`top.u.sig` 生成
  `top.u.sig`、`u.sig`、`sig` 三条重复/伪引用；残缺 `$past` 返回 `INTERNAL_ERROR: list index out of range`。
- 隐蔽性：[`timeline.py`](../xsva/xsva/ir/timeline.py) 第 67-89 行将 `signals_to_query` 定义为 Evidence IR
  标准接口，但 [`cli.py`](../xsva/xsva/cli.py) 第 394-429 行未序列化该字段，公开输出无法暴露错误。
- 影响：后续波形证据查询缺失或查询错误路径；畸形输入泄漏内部异常，而 lowering 仍可能标记 exact。
- 建议：递归解析 sampled argument，以单一 cursor 消费完整 signal reference；依赖不完整时降级为 partial；
  对残缺函数返回 typed diagnostic，并在 CLI 输出和测试中公开 canonical dependencies。

### 11.7 XCOV-CACHE-01（P2，已证实并发竞态）：不同 key 可突破 URG cache 容量上限

- 证据：[`urg_cache.py`](../xcov/xcov/urg_cache.py) 第 242-259 行在 build 前扫描容量；第 291 行起的
  claim 只按 key 串行化；第 348-394 行通过检查后才生成和发布。
- 复现：配置 `XVERIF_XCOV_CACHE_MAX_ENTRIES=1`，两个不同 key 并发 cold miss 都通过前置检查，
  最终 `entries/` 中发布 2 项。
- 影响：容量是软提示而非 hard bound；多项大型 URG cold build 可同时超出条目数和字节预算。
- 根因：check 与 publish 之间没有跨 key reservation；现有测试只覆盖 same-key 并发和顺序容量。
- 建议：只在 reserve/publish 的短临界区使用全局容量 claim 或 slot token，不把锁带回 cache hit/action
  热路径；容量计算纳入 reservation/staging 估算，并增加 distinct-key barrier race 测试。

### 11.8 MCP-LIFE-01（P2，高可信可恢复性风险）：长 query 阻止同 session 的 kill/close/doctor

- 证据：[`loop_session.py`](../xverif_mcp/src/xverif_loop/sessions/loop_session.py) 第 34-46 行的 decorator
  持有 `_lifecycle_lock`；query、close、doctor、kill 都使用它；第 1362-1373 行又在同一 RLock 内执行
  最长到 request timeout 的阻塞 transport request。manager 虽在
  [`session_manager.py`](../xverif_mcp/src/xverif_loop/sessions/session_manager.py) 第 356-396 行释放全局锁后
  查询，但无法绕过 per-session 锁。
- 触发：backend/NPI query 卡住或 transport 半开时，同一 session 发起 force close、kill 或 doctor。
- 影响：恢复动作必须等原 query 返回/超时，放大故障恢复延迟；若底层 request 没有及时响应取消，
  操作者无法立即终止该 session。
- 根因：请求串行化与生命周期控制共用一个覆盖整个 blocking I/O 的互斥区。
- 建议：拆分 request lane 与 lifecycle state lock；kill 可在短锁内原子 detach handle，随后从控制路径终止；
  close/doctor 使用有界状态快照，并增加 blocked-query-vs-kill/close 并发测试。

## 12. flock 专项结论

本轮对最近提交 `38eea24` 至 `63bec29` 的实现和验证记录做了复核，结论如下：

1. 全局 `registry.json` 已退出正常读写路径。engine 以
   `sessions/<encoded-session>/state.json` 保存活动 generation，list 通过遍历读取，单个坏 shard 被隔离；
   close 将 generation 归档到 session 自己的 `history/` 后删除活动 state。
2. action/query 不再持有 registry flock。活跃时间使用每 session 的 `activity` marker 更新，状态写采用
   原子文件替换；日志由每 owner 独占 shard，聚合读取不要求全局 writer lock。
3. 仓库内只剩 [`session_lifecycle_lease.h`](../xdebug/src/engine/session/session_lifecycle_lease.h)
   第 13-48 行的 per-session lifecycle lease，并仅在 `session_manager.cpp` 的 open、close、kill 边界使用。
4. 这把锁仍有必要：generation compare-and-swap 只能防止陈旧 writer 覆盖已发布 generation，无法单独阻止
   两个进程同时为同名 session 启动 backend、竞争 socket/file endpoint 或交错清理旧 generation。
   per-session flock 的作用域很窄，不会造成不同 session 或普通 action 相互等待。

因此，不建议继续追求“完全零 flock”。当前形态是合理的最小保险：只串行化同名 session 的破坏性
生命周期转换。若将来要去掉，必须先用 create-new lifecycle claim、generation ownership token、
endpoint publish CAS 和可回收 stale claim 完整替代，而不能只依赖原子写 `state.json`。

## 13. 其它子系统结论与观察项

- `xentry`、`xloc`：未发现可证实的 P0-P2 correctness 问题；公开输入合同严格，核心转换测试已通过。
- `xwaveform`：manifest 的相对文件、row/word count 直接决定 memmap shape，render 参数也较信任调用方；
  当前是显式本地 CLI 边界，列为 P3 hardening，不提升为正式 finding。若未来接入 MCP，应增加 artifact
  root containment、文件大小/shape 一致性和像素预算。
- `testinfra`：fixture claim 和 immutable generation 能正确处理常见并发；`current.json` 在 fsync 临时文件后
  replace，但没有 fsync `fixture_root`，属于断电耐久性 P3，而非普通进程并发错误。
- 根级构建/打包、action catalog、request/response schema 生成器、skill 引用未发现当前漂移。
- 第三方目录只审查集成边界、license/版本和调用方式，不把 vendored 实现风格作为本项目 finding。

## 14. 验证证据

| 类别 | 正式命令/动作 | 结果 |
| --- | --- | --- |
| 全仓快速门禁 | `.conda-xverif/bin/pytest --xverif-gate fast` | 574 passed |
| focused regression | regression gate 下运行 xbit、xentry、xcov、xwaveform、xsva、xverif_mcp 共 8 个 suite | 542 passed |
| request schema | `sync_runtime_request_schemas.py --check` | 通过 |
| response schema | `sync_response_schemas.py --check` | 通过 |
| AI hints | `sync_action_schema_hints.py --check` | 通过 |
| runtime compatibility | `audit_runtime_schema_compatibility.py` | 通过 |
| schema/example | `validate_schema.py`、`validate_examples.py` | 283 schema、229 example、7 invalid witness 通过 |
| 定向 probe | xbit、xsva、URG distinct-key race、MCP batch same-file | 复现结果见对应 finding |

本轮没有运行 regression/nightly 全集，也没有 prepare/rebuild fixture：用户要求的是只读 review，现有缓存
不足时不应借审查隐式改变测试资产。已运行的正式测试没有失败，不能反证上述边界缺陷，因为相关 race、
mixed-sign、large-int、same-file 和 fault-injection case 当前均不在覆盖矩阵中。

## 15. 建议修复顺序

1. 第一批：XBIT-COR-01/02、MCP-BATCH-01。修改面相对集中，先阻断错误计算和资源耗尽。
2. 第二批：MCP-POLICY-01。先冻结权限模型和兼容策略，再改 catalog/decorator/schema/doc，避免只补一层。
3. 第三批：XDEBUG-EXPORT-01。复用 APB 模式抽公共组件，一次统一 AXI/stream 及后续 exporter。
4. 第四批：XSVA-COR-01、XCOV-CACHE-01、MCP-LIFE-01，分别补 typed IR、容量 reservation 和可抢占恢复。
5. 每批独立提交并运行对应 focused suite；最终再运行 fast、host regression、nightly 与全量 fixture validation。

## 16. 最终边界审计

- 源码、配置、schema、skill、测试：未修改。
- Git：未 commit、未 push。
- 新增受版本控制内容：仅本报告。
- 临时 probe 和输出：仅位于被忽略的 `tmp/review-2026-08-13/`。
- 正式测试产生的 `.xverif-test-results/`、`npiLog/` 等均为仓库既定 ignored runtime output；没有触发
  fixture prepare 或重建。
