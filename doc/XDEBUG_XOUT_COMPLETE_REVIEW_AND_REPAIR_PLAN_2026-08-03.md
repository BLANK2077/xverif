# 从 `a3d8241` 前完整重建 xverif

## 总结

- 重建基线：`53a955616257db17335dfb639a3bcbdbcafcb7c1`，即 `a3d8241^`。
- 审计范围：`a3d8241..1c3ffc8` 共 27 个提交，逐提交、逐文件、逐 hunk 登记处置，不允许出现“其它修改”或未分类差异。
- 不使用 merge、cherry-pick、revert 或补丁回放；以现有代码为参考手工复刻产品意图。
- 保留当前 73 个 action 的 JSON/schema/session/error 公共合同，以及 value/query、coverage 和性能优化。
- 不复刻因 `a3d8241` 破坏 XOUT 后产生的通用补救实现；以旧版“基类通用渲染＋handler 特殊渲染”为架构基线。
- 最终重建历史替换远端 `master`，使 `a3d8241` 不再位于其祖先链。

## 启动顺序与审计约束

1. 在 `/home/RD/ryan/work/tmp/` 创建独立重建仓库，从 `53a9556` 建立分支。
2. 第一项修改必须是把本计划全文写入本文件，并作为单独的中文 commit 提交。
3. 提交计划书后，以计划书全文原样创建 Goal；Goal 建立前不得开始代码修改。
4. Goal 模式下按阶段工作，每阶段使用多个边界清楚的中文 commit。
5. 子 agent 在另一个 `/home/RD/ryan/work/tmp/` 临时仓库 checkout `53a9556`，独立检查旧架构、历史真实输出和最终差异；不修改主重建仓库。
6. 建立机器可检查的 commit ledger：输入精确等于 `git rev-list --reverse 53a9556..1c3ffc8` 的 27 个 SHA；每个 SHA 只出现一次；每个变更 hunk 标记为 `rebuild`、`superseded`、`xout-repair-drop` 或 `regenerate`；未分类 hunk、重复 SHA 或遗漏 SHA 阻止提交和推送。

## 27 个提交的最终处置

| 提交 | 处置 | 手工重建内容 |
|---|---|---|
| `a3d8241` | 拆分 | 保留 ContractBoundRequest、参数消费、精确错误、schema/response consolidation、session/MCP 生命周期和当前公共合同；删除 Pointer/lossless XOUT、中央 action switch、XOUT 反解析及其 golden。恢复 `TextResponseBuilder`、`EngineActionHandler::render_xout`、handler text 透传和旧有 override。 |
| `864f3aa` | 选择性保留 | 保留 `list.load`、config/config_path、append/replace 原子语义、精确错误、删除 `value.batch_at`；不恢复随后被统一 `value.at` 取代的 `list.value_at`。 |
| `59521ae` | 保留并更新 | 保留零参数完整 runtime action 导航、fail-closed catalog、配置化工作流和 batch 限制；移除旧 `list.value_at` 引导，action 数从 runtime 当前 73 项派生。 |
| `d774f1a` | 完整保留产品意图 | 重建统一 `value.at`、五类 selector、多时间点、raw/clock、ValueCollectionProvider、entries/samples JSON 和 load 后导航；矩阵输出实现为 handler override，不复制中央 renderer 分支。 |
| `2932977` | 保留 | 重建 scope level/kind/include/exclude、相对名称、interface/composite 规则、排序/截断/资源释放及分节 handler XOUT。 |
| `19a54e1` | 完整保留产品意图 | 重建 APB address、AXI address/ID/time、beat projection 和 Stream 专用路由；三个 query 各自使用 handler 特殊渲染，不使用通用 query 表格编码。 |
| `b397315` | 保留 | 恢复 C++ unit binary 的精确文件依赖和增量链接；按重建后的测试集合重新计算依赖。 |
| `0d5d6ee` | 保留 | 纯 JSON/schema 合同复用 stateless stdio-loop；session、CLI、XOUT、环境覆盖继续使用 one-shot。 |
| `867e0d3` | 保留 | 静态 response issue 校验只投影错误分支及依赖定义闭包，不改变公开 schema。 |
| `7106ed2` | 保留 | 重建 batch 严格 envelope 投影和缓存；已知 child 依赖 action-specific 校验，未知 child 继续严格验证。 |
| `b9aa3e1` | 保留 | `build_info.h` 只直接触发 `response.o`，避免全量对象重编译。 |
| `2110c4d` | 保留 | 显式资源 token 继续约束 suite；推导的 `verdi_npi` token 只施加给实际使用 `xverif_fixture` 的 item。 |
| `076ee70` | 保留 | 重建 HybridCliRunner；只有合格 JSON 请求复用 frontend，XOUT/文件/CLI/env/cwd 保持 one-shot，阶段变化显式 restart。 |
| `8558557` | 保留 | 保留 MCP smoke 的 `--runtime-only`，与 `--schema-only` 互斥，默认行为不变。 |
| `e4eb93f` | 保留 | 缓存并 top-down 裁剪仓库遍历，禁止进入生成目录，各检查保持自身过滤语义。 |
| `6992b6f` | 保留并独立提交 | 功能合同留在 regression；性能 probe、阈值和配对测量迁入 nightly `skills.x_npi_perf`，不得弱化阈值。 |
| `451da61` | 严格拆分 | 仅保留 `value.at` JSON canonical 路径和 schema 层 `INVALID_REQUEST` 断言；删除 XOUT→JSON parser、fallback、通用 query grammar 和 `tables["packets"]` 结构化预期。 |
| `7152d10` | 完整保留 Coverage 产品 | 重建三类 CSV exclusion source、session-local coverage_ref、strict、管理/分析/apply/rebase/stamp 工作流、回滚与原子发布；XOUT 适配旧版 xcov 文本架构。 |
| `9341b5d` | 完整保留 Coverage 产品 | 重建 x-npi strict VDB、多个 EL 顺序加载、before/set/after 校验、固定写模式 export、unload 和真实 probe。 |
| `c83a9eb` | 不回放通用修复，吸收新增行为 | 不再次恢复 builder、sidecar、Python 工具 XOUT 或删除 Pointer codec，因为基线天然具备正确架构；仅把 post-a3 新增的 value/query/coverage exclusion 专属布局直接实现为 handler override。不得复制其错误的 value.at summary/details。 |
| `a924a10` | 选择性保留 | 保留“XOUT 默认用于节省 token”的全仓政策、`xout_result` 命名和格式枚举顺序；不得写成“AI 或机器默认优先 JSON”。历史旧计划警告不复制。 |
| `ed8e11d` | 替换 | 不复制旧的 `9341b5d/c83a9eb` 修复计划；由本计划书取代。 |
| `398462f` | 框架重建、数据重录 | 保留 byte-preserving runner、73-action case matrix、setup/primary/error/teardown、SHA-256 回读合同；历史 baseline 报告不复制，在重建代码上重新生成。 |
| `ab8040b` | 保留 | 保留统一 `value_format`、active-driver-chain 纳入格式集合、stream config/config_path 去重、sampled pulse payloads 去同义入口及 schema/tests。 |
| `71b24b8` | 拆分 | 保留 canonical LogicValue JSON、counter/window evidence、严格 response schema、stream enum/runtime 修正；不机械复制 c83 后的通用 renderer 补丁。按最终要求在旧 builder 中最小实现默认 hex、显式 bin/dec 和 X/Z。 |
| `72f235c` | 保留最终产品结果 | `value.at` 必须只有 header＋values 矩阵；Stream LogicValue 交给共享值 formatter；保护 APB/AXI/Stream 专用布局。旧修复报告 delta 不复制。 |
| `1c3ffc8` | 选择性重建 | 按重建结果更新当前 README、skill、response-field 文档和回归预期；最终报告重新生成，旧报告不复制；仅保留仍适用于当前环境的 AGENTS 复盘。 |

## 分阶段多 Commit 实施

1. 计划书、Goal、commit ledger 和历史架构证据分别交付。
2. 公共基础按 builder/handler、公共 action/schema/error/session、生成产物拆分提交。
3. xdebug 产品能力按 list、value.at、scope、APB、AXI、Stream、MCP 导航分别提交。
4. 构建、runtime 和测试性能按原始独立意图分别提交。
5. Coverage 分为 x-npi performance gate、xcov CSV exclusion、x-npi exclusion helper 三个提交。
6. XOUT 最终合同按共享值格式、handler 专属布局、全仓文案、Native XOUT 审查分别提交。

## 公共接口与 XOUT 验收

- 当前 runtime catalog 保持 73 个 action，request/response schema 与当前公共合同语义一致。
- JSON 保持完整结构化合同；XOUT 不要求可逆，是 AI 默认的 token-efficient 输出。只有确实需要完整结构、程序字段访问或无损消费时才选择 JSON。
- 信号值默认使用紧凑十六进制，如 `8'h0`、`8'h8f`；显式请求 bin/dec 时遵从请求；存在 X/Z 时才附加必要 bit 证据。
- `value.at` 只输出 values 矩阵；APB/AXI/Stream query 保留各自领域表格；`event.find` 不嵌入 JSON；trace chain 保留 hop、时间、值和歧义证据。
- MCP 对 native XOUT 只做 header/非空/安全字符校验并原样透传，不从 XOUT 重建 JSON。
- 禁止 `XOUT_BEGIN/XOUT_END`、Pointer codec 和中央 action-name renderer switch。

## 测试与证据

- 先用正式 `--xverif-plan` 核对 suite gate，再运行 schema/help/example 生成检查、runtime compatibility、action catalog、相关 focused suite、全仓 fast 和宿主 regression。
- 覆盖 `value.at` 五类 selector、raw/clock、missing dependency、hex/bin/dec/X/Z；覆盖 APB exact/range/mask、AXI address/ID/time/两种模式和 data projection、Stream 既有语义及专用文本。
- Coverage 运行 `xcov.unit`、宿主 `xcov.exclusion_npi`、`skills.x_npi`、宿主 `skills.x_npi_real`、nightly `skills.x_npi_perf`。
- 使用当前缓存运行 `xdebug.native_xout_all`，不重新仿真、不 fallback；73 个 primary 和全部 setup/error/teardown stdout 逐字写入 Markdown，记录字节数、SHA-256 和末尾换行并回读验证。
- 指定验收：008 无嵌套 JSON；012/013 trace 非空且证据完整；协议 query 专用字段不丢失；value.at 无三段重复详情。
- 安装 `xverif`、`x-npi` skill 到 Codex/Claude 并执行 `diff -qr`。

## 远端交付

- 每次提交前运行 `git status --short`，显式添加文件，使用详细中文 commit message。
- 推送前要求工作树干净、ledger 27/27、73 action 通过、真实输出审查零失败。
- 确认 `origin/master` 仍为 `1c3ffc85d1bc3859bfa5f75c314cccaecc05e4d5`。
- 先推送备份分支 `backup/master-before-a3d-rebuild-20260803-1c3ffc8`，再用精确 `--force-with-lease` 替换远端 `master`，不创建 PR。
- 推送后验证远端 tree、测试证据及 `a3d8241` 不在 `origin/master` 祖先链中，随后完成 Goal。
