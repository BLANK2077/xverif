# xverif 八项 Review 问题修复计划与执行账本

## 1. 任务状态

- 日期：2026-08-16
- 基线：`2f80afb`
- 分支：`master`
- 当前阶段：P06 XCOV cache soft-limit 合同完成，准备进入 P07
- 用户已有改动：`AGENTS.md`，本任务不得修改、暂存或提交该文件。
- GitHub 边界：PR #3 与 issue #2 暂不处理，不移植、不回复、不关闭、不合并。

## 2. 目标与验收

本任务处理 `doc/XVERIF_FULL_REPOSITORY_CODE_REVIEW_2026-08-13.md` 的八项 finding：

| Finding | 处置 | 状态 |
| --- | --- | --- |
| XBIT-COR-01 | 完整修复混合 signed/unsigned 语义 | completed |
| XBIT-COR-02 | 完整修复大整数除法与负数取模 | completed |
| MCP-POLICY-01 | 完整实现严格 mutation/artifact 权限模型 | completed |
| MCP-BATCH-01 | 完整实现同对象防护、原子发布和资源预算 | completed |
| XDEBUG-EXPORT-01 | 抽取公共 atomic artifact publisher 并统一 APB/AXI/stream | completed |
| XSVA-COR-01 | 完整修复 sampled function 与层次信号依赖 | completed |
| XCOV-CACHE-01 | 将并发容量合同明确为 best-effort soft limit | completed |
| MCP-LIFE-01 | 完整实现可抢占 session 生命周期 | pending |

验收要求：

1. 七项代码/合同缺陷完成实现和定向测试；XCOV cache 完成 soft-limit 合同、文档与竞态测试。
2. MCP 默认真正只读；mutation 与 artifact write 分别显式授权，artifact 受 root containment 约束。
3. batch 默认限制输入 16 MiB、10,000 条、输出 64 MiB，并以 no-clobber 原子方式发布。
4. AXI/APB/stream 导出在失败、冲突和并发下不覆盖旧结果，不在返回后遗留部分 artifact set。
5. blocked query 不再阻塞同 session 的 kill；close/doctor 使用有界状态快照。
6. 关联 focused suites、schema/skill 检查、fast、host regression、host nightly 和 fixture validation 通过；若环境阻塞，必须保留原入口并明确记录，不 fallback。

## 3. 分阶段提交计划

| 阶段 | 内容 | 预期提交 | 状态 |
| --- | --- | --- | --- |
| P00 | 建立任务书、Goal 和基线 | 文档：建立八项评审修复计划与验收账本 | completed (`945644c`) |
| P01 | XBIT-COR-01/02 | 修复：统一 SystemVerilog 数值运算语义 | completed (`9a1b805`) |
| P02 | MCP-POLICY-01 | 安全：建立 MCP mutation 与 artifact 权限边界 | completed (`0ba0844`) |
| P03 | MCP-BATCH-01 | 安全：加固 MCP batch 输入输出与资源预算 | completed (`8966823`) |
| P04 | XDEBUG-EXPORT-01 | 导出：统一协议 artifact 原子发布 | completed (`7b3a78a`) |
| P05 | XSVA-COR-01 | 修复：规范 sampled function 证据信号提取 | completed (`d5324af`) |
| P06 | XCOV-CACHE-01 | 合同：明确 URG cache 并发软容量语义 | completed（待提交） |
| P07 | MCP-LIFE-01 | 生命周期：支持阻塞查询下的可抢占恢复 | pending |
| P08 | 全量验证、skill 安装和报告收口 | 文档：完成八项评审修复最终验收 | pending |

## 4. 公共合同

新增严格环境变量：

- `XVERIF_MCP_ENABLE_MUTATION=0|1`，默认 `0`。
- `XVERIF_MCP_ENABLE_ARTIFACT_WRITE=0|1`，默认 `0`。
- `XVERIF_MCP_ARTIFACT_ROOT=<directory>`；artifact write 开启时必需。
- `XVERIF_MCP_BATCH_MAX_INPUT_BYTES`，默认 `16777216`。
- `XVERIF_MCP_BATCH_MAX_REQUESTS`，默认 `10000`。
- `XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES`，默认 `67108864`。

tool/action capability 必须显式声明：

- `mutation`：成功调用会改变 managed session、backend、配置、list、cursor 或 exclusion 状态。
- `artifact_write`：`never|conditional|required`；conditional 必须依据实际请求判定。
- 默认关闭时不注册固定 mutation/write tool；动态 query 在转发前返回 typed policy error。
- relative artifact path 基于 artifact root 解析；absolute path 仅允许位于 root 内；拒绝 traversal 和 symlink escape。

## 5. 测试矩阵

- XBIT：`xbit.unit`。
- MCP：`xverif_mcp.unit`、`xverif_mcp.process`、`xverif_mcp.action_smoke`、`xverif_mcp.real_fullchain`。
- xdebug：`xdebug.cpp_unit`、`xdebug.contract`、`xdebug.stream`、`xdebug.apb_vip`、`xdebug.axi_vip`。
- XSVA：`xsva.core`、`xsva.cli`、`xsva.vcs`。
- XCOV：`xcov.unit`、`xcov.urg_backend`。
- Skill：`skills.xverif`、`skills.xverif_admin`、`skills.public_docs`。
- 全仓：fast、host regression、host nightly、全量 fixture validation。

所有 NPI、FSDB、VDB、VCS、VIP 和真实 MCP process 验证使用 host 正式入口。每次提交前检查 `git status --short` 与 staged 白名单，不使用 `git add .`。

## 6. 执行记录

| 日期 | 阶段 | 结果 | 证据 |
| --- | --- | --- | --- |
| 2026-08-16 | P00 | 已建立任务书；待创建 Goal | 本文件 |
| 2026-08-16 | P00 | 已创建任务 Goal 并冻结验收范围 | goal `01a00a63-7b21-7e41-86cf-d9432fda70ec` |
| 2026-08-16 | P01 | xbit mixed-sign、共同位宽、64/128 位除法、负数余数与零除用例通过 | `xbit.unit`: 32 passed |
| 2026-08-16 | P02 | MCP 默认只读、固定工具隐藏、动态 action 拒绝和 artifact root containment 通过 | `xverif_mcp.unit`: 180 passed；`xverif_mcp.process`: 145 passed |
| 2026-08-16 | P02 | admin skill 权限与排障文档合同通过 | `skills.xverif_admin`: 1 passed |
| 2026-08-16 | P03 | batch 冻结输入并在执行前拒绝同路径、硬链接和软链接同对象，输入与请求数预算在执行前生效 | `xverif_mcp.process`: 151 passed |
| 2026-08-16 | P03 | batch 输出经同目录暂存、fsync 和 create-new 原子发布；输出超限及发布失败不遗留部分结果 | `xverif_mcp.unit`: 180 passed；`skills.xverif_admin`: 1 passed |
| 2026-08-16 | P04 | 公共 publisher 统一 APB/AXI/stream 的同目录暂存、逐文件 fsync、create-new、整组回滚和目录 fsync | `xdebug.cpp_unit`: 1 suite passed；host build `internal-engines` passed |
| 2026-08-16 | P04 | 真实 FSDB 与 VIP 导出保持既有文件名、meta 和 response 合同 | `xdebug.contract`: 114 passed；`xdebug.stream`: 2 passed；`xdebug.apb_vip`: 1 passed；`xdebug.axi_vip`: 1 passed |
| 2026-08-16 | P04 | xverif skill、公开文档与新增 C++ runner 纳管检查通过；并行 pytest 曾触发共享结果目录裁剪竞态，原入口串行重跑通过且已按仓库规则复盘 | `skills.xverif`: 16 passed；`skills.public_docs`: 4 passed；`testinfra.unit`: 54 passed |
| 2026-08-16 | P05 | sampled 参数递归提取、单 cursor 层次路径/select、依赖去重与畸形调用 partial diagnostic 通过 | `xsva.core`: 138 passed；`xsva.cli`: 14 passed；`skills.xverif`: 16 passed |
| 2026-08-16 | P05 | VCS 语义用例保持一致 | `xsva.vcs`: 4 passed |
| 2026-08-16 | P06 | URG cache 明确为已发布 entry 快照的 best-effort soft admission；不同 key 并发可超限，后续 cold admission 关闭，warm hit 与显式维护合同不变 | host `xcov.unit`: 170 passed；host `xcov.urg_backend`: 7 passed；`skills.xverif`: 16 passed；`skills.public_docs`: 4 passed |
