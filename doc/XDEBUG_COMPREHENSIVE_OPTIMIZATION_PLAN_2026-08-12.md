# xdebug 全量优化实施计划与进度账本

日期：2026-08-12

启动基线：`5fe239c`（包含综合评审、真实 NPI/FSDB 实验、最新 Native XOUT 证据和环境复盘）

目标分支：`master`；最终直接 fast-forward 推送 `origin/master`，不创建 PR，不使用 worktree。

## 1. 目标与完成定义

本任务基于 `doc/xdebug-comprehensive-code-review-2026-08-11.md`，一次性关闭其中 33 项评审
发现，实现经过真实 NPI 实验确认的 design-aware `scope.list` 和明确缺失的 `apb.export`，同步完成
native CLI、engine、session、MCP、SDK-free loop、schema、example、XOUT、skill、维护文档和测试闭环。

任务只有同时满足以下条件才算完成：

1. 1 项 P0、8 项 P1、19 项 P2、5 项 P3 均有实现、测试或按本计划明确的不优化处置。
2. `session.kill` 从 public catalog 删除，所有仓库内调用迁移到
   `session.close args.mode=force`；新增 `apb.export` 后 action catalog 仍为 73 项。
3. 同一 engine/session 的 NPI context 严格串行，禁止同 handle 并发进入 vendor API。
4. FSDB 被替换后，任一 session-bound query 在进入旧 handle 前返回 `RESOURCE_CHANGED`。
5. `scope.list source=design|merged` 正确覆盖 generate scope、interface array、modport 和 mpport。
6. 所有生成检查、schema/example/runtime compatibility 检查通过。
7. 全仓 fast、regression、nightly 的全部 required suite 通过，全 fixture validation 通过。
8. 两个依赖真实 LSF 的 optional suite 因本机未安装 LSF 不作为阻塞，但必须如实记录。
9. 受影响 skill 安装到 Codex/Claude 后逐目录 `diff -qr` 一致。
10. 工作树干净、commit ledger 完整、本地 HEAD 与远端 `origin/master` SHA/tree 一致。

## 2. 固定范围与明确不优化项

### 2.1 本轮范围

- 安全随机、session lifecycle、timeout/cancellation、NPI 串行化和 FSDB identity。
- batch/MCP 管理边界、XOUT 完整性、transport I/O、错误分类和严格配置。
- analysis cache 元数据边界、热路径统计、LRU 和 APB/AXI 有界算法。
- design-aware hierarchy、APB artifact export。
- schema payload、错误字段、文档/example、MCP negative example 和 generator 单源化。
- 重复 dispatcher、生产 test hook、死代码和静默 evidence 丢失清理。

### 2.2 明确不优化

- 不设计 daidir 强 identity marker、递归 hash 或 vendor-specific fingerprint。
- 不研究或调用 vendor 私有 NPI cancel API。
- 不新增 AXI/cache 延迟 SLO；只建立功能、资源边界、cardinality 和等价性门禁。
- 不实现 VHDL/mixed-language 或 bind instance traversal。
- 不实现 automatic reopen；资源变化后必须由用户显式 reopen。
- 不实现未经实验确认的 hierarchy child fallback。
- 不实现双 FSDB diff、assertion/log 自动入口、progress action、clock/reset 自动猜测、FSM 或
  sequential 新 action。

## 3. 公共接口与兼容决策

### 3.1 Session 生命周期破坏性迁移

本轮直接删除 public `session.kill`，不保留 alias。`session.close` request 新增：

```json
{
  "args": {
    "mode": "graceful|force",
    "ownership_token": "<force 且单一 session 时可选>"
  }
}
```

- `mode` 默认 `graceful`。
- graceful 只发送 quit 并有界等待；失败时保留 session record 和诊断状态。
- force 允许进程外 SIGTERM/SIGKILL；成功后移除记录，无法确认清理时保留
  `cleanup_failed` tombstone。
- `ownership_token` 只允许 `mode=force` 且 `target.session_id` 是单一精确值；对 `all` 拒绝。
- `target.session_id=all` 逐 session 执行，返回成功、失败、保留记录的计数和明细。
- 旧请求返回 `UNKNOWN_ACTION`，并通过 `did_you_mean=session.close` 和 force example 指路。
- 删除 `xverif_debug_session_kill`、`debug.session.kill`；managed wrapper 条件清理迁到 force close。
- xcov 自身 session API 不在删除范围，共享 loop 层不得破坏 xcov 公共合同。

### 3.2 Design-aware `scope.list`

扩展为 `scope.list source=wave|design|merged`：

- 默认 `wave`，保持现有 waveform 调用兼容；action `requires` 改为 `any`。
- wave 要求 FSDB，design 要求 daidir，merged 要求两者。
- 保留 `level`，不新增同义 `max_depth`。
- `kind` 扩展为 all/module/interface/interface_array/gen_scope/internal_scope/modport/mpport/port/signal。
- design hierarchy 固定走 `npiInstance -> npiInternalScope`；`npiGenScope` 继续递归。
- interface array child 是展开后的 `npiInterface`；通过元素的 `npiInstanceArray` 取得并去重容器。
- interface 侧向遍历 `npiModport -> npiMpPort`；direction 只取 mpport。
- modport canonical path 由 interface path 与 modport name 组合，不依赖可能为空的 full name。
- hierarchy depth 与 object budget 分离；modport/mpport 不增加 hierarchy depth但计入 visited budget。
- response 发布 visited/returned count、truncated、truncation_scope、sources、queryable、traceable。

### 3.3 `apb.export`

- 新增 stable action，复用 canonical APB repository 与 `apb.query` 的 direction/address filter。
- required：name 和非空 time_range。
- optional：direction、address、render_time_unit、value_format、output。
- `output.file_format=tsv|csv`；指定 format 时必须提供 path。
- 无 path 返回有界 preview；有 path 写完整 artifact。
- response 分开发布扫描总数、匹配数、preview 行数、artifact path/format/bytes 和完整性。
- 禁止静默降级为 stream/list export。

### 3.4 其他公共合同

- 错误候选字段统一为 `available_values`，不发布双字段。
- `batch.args.mode` 只允许 continue_on_error/stop_on_error。
- `schema.args.view=full|summary`，默认 full；MCP 对 batch response 默认请求 summary。
- batch summary 是独立紧凑 artifact，不能先加载 4.8 MiB full schema再裁剪。
- XOUT validation issue 最多渲染 20 条，同时发布 issue_count/issues_truncated。
- XOUT 不对 handler 已返回的 batch children 再做隐式截断。

## 4. Finding 到阶段映射

| 阶段 | Finding |
| --- | --- |
| 安全与 batch | SEC-01、SEC-02、COR-02、COR-03、AI-05 |
| Session | LIFE-01、LIFE-02、LIFE-03、LIFE-04、OBS-01 |
| FSDB identity | COR-01 |
| Transport | IO-01、IO-02、ERR-01、CFG-01 |
| Cache/算法 | MEM-01、PERF-01、PERF-02、PERF-03、TEST-01 |
| Hierarchy | GAP-01 中已确认的 design hierarchy 缺口 |
| APB export | GAP-02 |
| AI/schema | AI-01、AI-02、AI-03、AI-04、AI-06、AI-07、SCHEMA-01 |
| 清理 | ARCH-01、TEST-02、DEAD-01、OBS-02 |

## 5. 分阶段 Commit

每阶段开始和结束都更新本文件状态；提交前必须验证 staged 文件精确属于该阶段。

### C01 计划与 Goal 基线

状态：`completed`

- 提交本计划书。
- 提交后按第 8 节创建 Goal。
- 验证：Markdown、链接、`git diff --cached --check`。
- commit：`431c615`。

### C02 安全随机与 batch/MCP 边界

状态：`completed`

- 安全随机循环读取，失败 `SECURE_RANDOM_UNAVAILABLE`。
- 递归阻止 managed MCP batch lifecycle child。
- batch mode enum fail-closed。
- 删除 XOUT batch 二次截断，补有界 validation issue 表。
- focused：xdebug.static、cpp_unit、contract、xverif_mcp.unit/process/action_smoke、native_xout_report。
- commit 主题：`安全：加固 xdebug 随机认证与 batch 管理边界`。
- commit：本提交。

### C03 Session 生命周期与 NPI 串行化

状态：`completed`

- 缩小 lifecycle lease；建立单 NPI owner 序列。
- cooperative deadline checkpoint 和进程外 hard termination。
- list 纯读、compact/verbose、lifecycle state。
- 删除 session.kill，迁移 session.close graceful/force 及所有调用者。
- focused：cpp_unit、contract、session、MCP direct/fake LSF、xverif_mcp 全部非真实 LSF suite。
- commit 主题：`会话：重构可抢占生命周期并统一强制关闭语义`。

### C04 FSDB 资源身份门禁

状态：`completed`

- 所有 session-bound query dispatch 前比较 canonical path/device/inode/size/mtime-ns。
- 变化返回 RESOURCE_CHANGED，不 reopen，不进入旧 handle。
- focused：contract、session、synthetic_existing、combined suites。
- commit 主题：`正确性：为会话查询增加 FSDB 资源身份门禁`。

### C05 Transport 与严格配置

状态：`completed`

- block reader、统一 request size、REQUEST_TOO_LARGE。
- write-all/EINTR/partial I/O/nonblocking connect/remaining deadline。
- file transport 保留细分状态。
- 关键 env fail-fast，展示 env 发布 warning/effective value。
- focused：cpp_unit、contract、session、MCP process/direct/fake LSF。
- commit 主题：`传输：统一请求边界、截止时间与结构化错误`。

### C06 Cache 内存与算法

状态：`completed`

- generation/cursor/binding/tombstone 纳入预算并可释放。
- 增量 stats，禁用 probe 时无全表统计。
- 确定性 LRU 与批量淘汰。
- APB/AXI filter/limit 下推，outlier 有界 top-N。
- benchmark 改为资源/等价性硬门禁，不设新延迟 SLO。
- focused：cpp_unit、counter、stream、APB/AXI VIP、analysis_cache_benchmark。
- commit 主题：`性能：收紧分析缓存预算并消除全表热路径`。

### C07 Design-aware hierarchy

状态：`completed`

- 共享 relationship walker 和 scope.list source/kind 扩展。
- 将临时 generate/interface array/modport fixture 正式化。
- 删除未实现 design action 宣称。
- focused：static、cpp_unit、contract、design_semantics、synthetic_existing、skills.xverif。
- commit 主题：`功能：扩展 scope.list 支持设计层级与接口关系`。

### C08 APB export

状态：`completed`

- handler、catalog、schema、example、XOUT、MCP/skill 全闭环。
- action catalog 保持 73。
- focused：static、action_runtime_catalog、contract、apb_vip、native_xout_all、skills.xverif。
- commit 主题：`功能：新增 APB 标准事务导出能力`。

### C09 AI/schema/docs 单源化

状态：`completed`

- available_values 全链路统一。
- batch compact schema 和 MCP summary。
- canonical examples 生成 README/help，并检查所有 public fenced JSON/action token。
- oneOf/allOf negative example。
- statistics alternatives。
- 恢复或迁移 AXI response generator，只保留一个真实 source of truth。
- 更新 skill、action reference、agents/openai.yaml 和维护文档。
- focused：static、action_runtime_catalog、skills.xverif、skills.public_docs、xverif_mcp.unit。
- commit 主题：`合同：统一 xdebug schema、错误提示与 AI 使用指南`。

### C10 架构、测试钩子和死代码清理

状态：`completed`

- typed adapter 取代重复字符串 dispatcher。
- differential oracle 移到 test build/binary。
- 删除 non-cached legacy wrapper。
- logging once-degraded，trace parse failure 标记 analysis incomplete。
- focused：cpp_unit、contract、stream、active trace、trace_x、native_xout_all。
- commit 主题：`重构：清理重复分发、测试钩子与静默异常路径`。

### C11 全量回归与交付证据

状态：`pending`

- 更新本账本、综合评审处置状态、测试证据、commit ledger 和远端结果。
- commit 主题：`验证：记录 xdebug 全量优化回归与最终验收证据`。

## 6. 测试与验收

### 6.1 生成与静态检查

schema 相关变更至少执行：

```bash
.conda-xverif/bin/python xdebug/tools/sync_runtime_request_schemas.py --check
.conda-xverif/bin/python xdebug/tools/sync_response_schemas.py --check
.conda-xverif/bin/python xdebug/tools/sync_action_schema_hints.py --check
.conda-xverif/bin/python xdebug/tools/audit_runtime_schema_compatibility.py
.conda-xverif/bin/python xdebug/tools/validate_schema.py
.conda-xverif/bin/python xdebug/tools/validate_examples.py
```

若恢复独立 AXI generator，则将其 `--check` 加入正式 static suite；若迁入现有 response generator，
必须同步删除所有失效命令引用。

### 6.2 最终全仓回归

源码冻结并统一构建后，禁止在真实回归期间并发链接 xdebug。依次执行：

```bash
.conda-xverif/bin/pytest --xverif-gate fast
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate regression -n auto
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate nightly -n auto
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest \
  --xverif-fixture-validation --xverif-all-fixtures
```

- fast 当前 12 suites 必须全过。
- regression 当前 41 required suites 必须全过。
- nightly 当前 57 required suites 必须全过。
- `xverif_mcp.real_lsf_jobid`、`xdebug.mcp_real_lsf` 因本机无 LSF 不阻塞，但必须记录真实状态。
- required suite 不允许 SKIP/XFAIL/过滤失败。
- fixture validation 必须全过。
- 安装受影响 skill 后，对 Codex/Claude 安装目录逐项 `diff -qr`。

## 7. Git 与远端交付

- 每次 commit 前执行 `git status --short` 和 `git diff --cached --name-only`。
- 显式 `git add` 文件，不使用 `git add .`。
- commit 使用详细中文信息，写明动机、范围、验证。
- 最终在 host 执行 `git fetch origin`。
- 若远端仍为任务基线后的本地祖先，直接 `git push origin master`。
- 若远端前进，禁止 force push；rebase 最新 `origin/master` 后重跑全部 required regression、nightly
  和 fixture validation。
- 推送后验证远端 SHA、tree 和全部阶段 commit。
- 远端验证成功后才将 Goal 标记 complete。

## 8. Goal 任务书

计划书提交后创建无 token budget Goal：

> 依据本计划书完成 xdebug 综合优化：关闭评审报告中的 33 项发现，实现经过真实 NPI 实验确认的
> design-aware scope.list 和 apb.export，将 session.kill 迁移并删除，保持同一 session 内 NPI
> 严格串行，完成 schema/example/MCP/XOUT/skill/文档闭环；按阶段形成边界清楚的中文提交，最终使
> 全仓 fast、regression、nightly 的全部 required suites 和全 fixture validation 通过，并以
> fast-forward 方式推送 origin/master。明确不实现计划书列出的 daidir 强 identity、vendor 私有
> 取消、性能 SLO、mixed-language/bind、automatic reopen 和探索性新 action。验收以本计划书
> commit ledger、测试证据、干净工作树、远端 commit/tree 校验为准。

## 9. Commit Ledger

| 阶段 | 状态 | Commit | 验证摘要 |
| --- | --- | --- | --- |
| 前置评审基线 | completed | `5fe239c` | 三份文档；`git diff --cached --check` |
| C01 计划书 | completed | `431c615` | 文档检查、`git diff --cached --check` |
| C02 安全/batch | completed | `0fe1328` | 安全随机、batch/MCP、XOUT 边界及 focused suites 全绿 |
| C03 Session | completed | `111d386` | 生命周期 lease/NPI 串行、deadline/超时终止、list 纯读、close graceful/force 与全 surface 迁移完成 |
| C04 FSDB identity | completed | `7e27303` | registry v3 纳秒指纹、open 二次校验、query 前 fail-closed gate 与 RESOURCE_CHANGED AI 证据完成 |
| C05 Transport | completed | `0725a50` | 64 MiB 统一边界、block I/O、单调 deadline、严格 env 与结构化错误完成 |
| C06 Cache | completed | `477efdd` | 全元数据预算、O(1) stats、批量 LRU、有界 APB/AXI selection 与资源/等价性门禁完成 |
| C07 Hierarchy | completed | `7c26474` | `scope.list` 的 wave/design/merged 与 generate/interface array/modport/mpport 关系完成真实 VCS/NPI 验证；未扩展 mixed-language/bind |
| C08 APB export | completed | `da6e8c1` | 73-action catalog；APB preview/闭区间/方向地址过滤/TSV/CSV/meta/no-clobber/宽度完整性完成真实 VIP FSDB/NPI 与 native XOUT 验证 |
| C09 AI/schema | completed | `bc1ec2b` | available_values、batch summary/child/full、canonical public examples、复杂反例、statistics 路由、统一 response SOT 与 AI/MCP 文档闭环 |
| C10 清理 | completed | 本提交 | 15 个 wrapper typed binding；生产/test oracle 二进制隔离；删除 legacy wrapper；logging once-degraded 与 trace 内部 JSON 不完整诊断闭环 |
| C11 全量验收 | pending | - | - |

## 10. 测试证据账本

| 时间 | 阶段 | 命令/检查 | 环境 | 结果 | 日志/备注 |
| --- | --- | --- | --- | --- | --- |
| 2026-08-12 | 前置 | `git diff --cached --check` | host | PASS | commit `5fe239c` |
| 2026-08-12 | C01 | 计划书内容及 `git diff --cached --check` | host | PASS | commit `431c615`；Goal 已创建 |
| 2026-08-12 | C02 | `xdebug.cpp_unit` / `xdebug.static` | host | PASS | 1 passed；107 passed |
| 2026-08-12 | C02 | `xdebug.contract` / `xdebug.session` | host | PASS | 111 passed；38 passed |
| 2026-08-12 | C02 | `xverif_mcp.unit` / `process` / `action_smoke` | host | PASS | 165 / 141 / 1 passed |
| 2026-08-12 | C02 | `xdebug.native_xout_report` | host | PASS | 8 passed |
| 2026-08-12 | C02 | request/schema/hint/runtime compatibility/examples | host | PASS | 281 schemas；218 examples；生成一致 |
| 2026-08-12 | C03 | `make -C xdebug all` / `xdebug.cpp_unit` / `xdebug.static` | host | PASS | 构建通过；1 / 107 passed（组合复验 108 passed） |
| 2026-08-12 | C03 | `xdebug.contract` / `xdebug.session` | host | PASS | 111 / 40 passed |
| 2026-08-12 | C03 | `xdebug.mcp_direct` + `xdebug.mcp_fake_lsf` | host | PASS | 7 passed |
| 2026-08-12 | C04 | response schema generator/check、schema/example validate | host | PASS | 279 schemas；216 examples |
| 2026-08-12 | C04 | `xdebug.contract` / `xdebug.cpp_unit` / `xdebug.static` | host | PASS | 112 / 1 / 107 passed |
| 2026-08-12 | C04 | `xdebug.session` | host | PASS | 41 passed；含同 size/mtime-ns 原子替换 inode 回归 |
| 2026-08-12 | C04 | `xdebug.synthetic_existing` + `xdebug.active_semantics` | host | PASS | 3 passed |
| 2026-08-12 | C05 | `make -C xdebug all` / response schema 生成检查 / schema / examples | host | PASS | 构建通过；279 schemas；218 examples；生成一致 |
| 2026-08-12 | C05 | `xdebug.cpp_unit` / `xdebug.static` / `xdebug.contract` | host | PASS | 1 / 108 / 112 passed |
| 2026-08-12 | C05 | `xdebug.session` / MCP direct / MCP fake LSF | host | PASS | 41 / 4 / 3 passed |
| 2026-08-12 | C05 | `skills.xverif` / `skills.xverif_admin` | host | PASS | 16 / 1 passed |
| 2026-08-12 | C06 | `make -C xdebug all` / `xdebug.cpp_unit` / `xdebug.static` | host | PASS | 构建通过；1 / 108 passed |
| 2026-08-12 | C06 | counter / synthetic existing / stream | host | PASS | 1 / 2 / 2 passed |
| 2026-08-12 | C06 | APB VIP / AXI VIP / analysis cache benchmark | host | PASS | nightly required 各 1 passed；benchmark 含等价、RSS、估算字节、scanner 与 cardinality 硬门禁 |
| 2026-08-12 | C07 | build / request、response、hint、internal、current sample 生成检查 / schema / examples / runtime compatibility | host | PASS | 构建通过；279 schemas；222 examples；全部生成产物一致 |
| 2026-08-12 | C07 | `xdebug.design_semantics` / `xdebug.static` / `xdebug.cpp_unit` | host | PASS | 6 / 108 / 1 passed；新 fixture 由 VCS 生成 daidir，真实 NPI 验证 generate/interface array/modport/mpport |
| 2026-08-12 | C07 | `xdebug.contract` / `xdebug.synthetic_existing` / `skills.xverif` | host | PASS | 112 / 2 / 16 passed |
| 2026-08-12 | C07 | `testinfra.unit` | host | PARTIAL | C07 相关 catalog、fixture、C++ runner 检查通过；39 passed，唯一失败来自另一个任务未跟踪 flock 报告中的机器绝对路径，未修改、未过滤 |
| 2026-08-12 | C08 | build / request、response、hint、internal、metadata、help、current sample 生成检查 / schema / examples / runtime compatibility | host | PASS | 构建通过；283 schemas；226 examples；71 internal actions / 64 helper envelopes；全部生成产物一致 |
| 2026-08-12 | C08 | `xdebug.static` / `xdebug.action_runtime_catalog` / `xdebug.cpp_unit` / `xdebug.contract` | host | PASS | 111 / 1 / 1 / 112 passed |
| 2026-08-12 | C08 | `skills.xverif` / `skills.public_docs` / `xverif_mcp.unit` | host | PASS | 16 / 3 / 166 passed；MCP minimal call 读取 catalog 首个 canonical request example |
| 2026-08-12 | C08 | `xdebug.apb_vip` | host，真实 VCS/NPI fixture | PASS | 1 passed；10 笔真实 APB completed transfer，验证 8 行 preview、闭区间、direction/address、decimal、TSV/CSV、meta parity、artifact width 和错误路径 |
| 2026-08-12 | C08 | prepare `xdebug.xif_event` / `xdebug.native_xout_all` | host，真实 VCS/NPI fixtures | PASS | 缺失 fixture 按正式 prepare 入口生成并通过 probe；73 actions + 9 error cases 的 native XOUT 矩阵 1 passed |
| 2026-08-12 | C09 | build / request、response、hint、metadata、help、current sample、skill reference 生成检查 / schema / examples / runtime compatibility | host | PASS | 构建通过；283 schemas；228 正例 + 7 canonical 反例；全部生成产物一致；Draft-7/2020-12 verdict 一致 |
| 2026-08-12 | C09 | `xdebug.static` / `xdebug.action_runtime_catalog` / `xdebug.cpp_unit` / `xdebug.contract` | host | PASS | 116 / 1 / 1 / 114 passed；contract 包含 compact schema metaschema 与真实 batch success response 验证 |
| 2026-08-12 | C09 | `skills.xverif` / `skills.public_docs` / `xverif_mcp.unit` | host | PASS | 16 / 4 / 178 passed；公开 strict JSON fence 对 live native/MCP schema 校验 |
| 2026-08-12 | C09 | native `schema(batch,response)` summary/child/full 与非法组合 probe | host | PASS | summary 7,708 bytes、72 non-batch child、无 recursive child defs；default full 5,570,443 bytes；child 148,773 bytes；非法组合 schema-rejected |
| 2026-08-12 | C10 | build / request、response、hint、metadata 生成检查 / schema / examples / runtime compatibility | host | PASS | 生产构建通过；283 schemas；229 正例 + 7 canonical 反例；全部生成产物一致；Draft-7 compatible |
| 2026-08-12 | C10 | production/test stream binary symbol and string audit | host | PASS | 生产 engine 无 legacy analyzer/oracle/旧 env；独立 fixture engine 同时包含 `analyze_legacy` 与 cached differential oracle |
| 2026-08-12 | C10 | `xdebug.static` / `xdebug.cpp_unit` / `xdebug.contract` | host | PASS | 119 / 1 / 114 passed；覆盖 typed adapter、logging once-degraded、损坏 manifest 保留和 trace diagnostic 配对 |
| 2026-08-12 | C10 | `xdebug.stream` / `xdebug.stream_differential` | host，真实 FSDB/NPI fixture | PASS | 2 / 2 passed；生产矩阵与独立 test-only legacy oracle 的 action/cache/batch 差分全部通过 |
| 2026-08-12 | C10 | `xdebug.active_semantics` / `xdebug.trace_x_xprop` / `xdebug.active_zero_evidence` | host，真实 daidir/FSDB/NPI fixture | PASS | 1 / 1 / 16 passed；正常 trace/active/X-origin 合同未回归 |
| 2026-08-12 | C10 | `xdebug.native_xout_all` | host，真实 daidir/FSDB/NPI/VIP fixture | PASS | 73 actions + error cases 的 final XOUT 矩阵 1 passed；真实报告原子重建 |
| 2026-08-12 | C10 | `testinfra.unit` | host | PARTIAL | C10 新 suite/catalog/fixture 被正式 gate 接受；39 passed，唯一失败仍来自另一个任务未跟踪 flock 报告的机器绝对路径，未修改、未过滤 |

## 11. 偏差与阻塞记录

- C02 首轮 runtime 验证与并行链接发生竞态，统一冻结构建并重建后串行复验全部通过；已按仓库规则写入环境复盘，不计为产品失败。
- C06 首轮 probe unit 的 symlink escape 测试把目标误建在允许目录内；修正为同级真实外部目标后正式 cpp_unit 通过。AXI VIP 首轮因其独立 runner 未传递 probe marker 而未生成测试 artifact，补齐每个 runner 自有 tmp marker 后完整复验通过。
- C08 首轮 static 暴露测试函数边界误置与 C 风格地址字面量，修正测试后通过；首轮 contract 暴露新 action primary example 未遵守 runtime `.basic.json` 约定，统一 primary 命名并让 MCP 从 catalog 读取后通过。真实 APB VIP 进一步确认默认时间输出必须将 `1us` canonicalize 为 `1000ns`，以及 artifact-only 分支必须主动发布宽度完整性；按统一时间/宽度合同修正后完整通过。
- C07 首轮 design runtime 因 action catalog 已改为 `requires:any`、但 internal request schema 尚未重生成而在 helper routing 层拒绝 design-only session；重生成并加入一致性复验后 6 个真实 NPI 用例全过。旧 synthetic fixture 还按字段全集比较 wave item，更新为验证新增 source/capability 证据。`testinfra.unit` 剩余唯一失败属于另一个任务的未跟踪 flock 报告，不进入本阶段提交。
- C09 首轮 public docs 门禁发现 `xverif_mcp/README.md` 把 JSON fragment 标成 strict JSON，改为 `jsonc`；MCP 反例测试曾用普通 args schema 错验 session 专用 projection，按各自合同拆分。首轮 host contract 发现测试硬编码旧 primary example，改为核对 catalog canonical example。最终审阅又发现 compact schema 的空 initializer 被序列化为 `null` schema，改成明确 object/null 并增加 metaschema + 真实 batch response 验证。两次 native 性能 probe 因入口路径/CLI flag 误判未进入产品，已按 AGENTS.md 记录且未计入证据，第三次使用核实后的 `xdebug/xdebug --json -` 取得正式数据。
- C10 首轮 static 只暴露新增两个 trace variant 与一个 response example 后的覆盖账本常量仍为旧值，更新为 134 variants / 65 responses / 64 success witnesses 后 119 项全过。首轮 differential preflight 暴露 fixture 指纹误把 pytest `__pycache__` 当 C++ 构建输入，收紧为 `*.cpp/*.h` 后连续 resolve 稳定；首轮 cache 差分暴露新 fixture 直接使用一次性 `CliRunner`、缺少正式测试依赖的 `restart()` 生命周期，改用同一 `HybridCliRunner` 封装后完整 2 项通过。`testinfra.unit` 唯一失败仍是另一个任务未跟踪 flock 报告，未纳入、未过滤。调用不存在的旧 AXI 独立 response generator 在校验前退出；仓库当前规则和文档已确认 C09 后统一入口为 `sync_response_schemas.py`，随后按正式清单完整复验通过。
- 任何 fallback、范围扩展、required suite 降级、公共合同偏离必须先取得用户确认，再记录于此。
