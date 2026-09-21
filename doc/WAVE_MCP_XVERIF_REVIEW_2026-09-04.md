# wave-mcp 与 xverif 技术评审

日期：2026-09-04

## 1. 结论摘要

`wave-mcp` 值得学习，但学习重点不在它的 FST 数据通路或基于 RTL 解析的静态追踪。xverif 应继续坚持 NPI 作为设计数据库、FSDB、active-driver 和 coverage 的事实来源，不引入第二套会与 NPI 产生语义分叉的底层模型。

真正值得吸收的是 `wave-mcp` 在“产品最后一公里”上的四项做法：

1. **agent 与用户共享同一个可交互波形视图**：用 `desired/actual` 双向状态、revision、marker 和 annotation 把机器结论交给用户复核，并让 agent 读取用户移动后的游标和显示信号。
2. **面向保密项目的脱敏现场诊断包**：fieldkit 只导出统计、比例、耗时、错误分类和结构指纹，不泄露 RTL、路径和信号名。
3. **统一的一步式首次使用入口**：`prepare_session` 把输入检查、缓存复用、构建、打开和能力摘要串成一个明确工作流，降低首次接入成本。
4. **离线交付工程**：独立 Python、wheelhouse、glibc 分档、目标机 sanity check、升级/回滚说明完整，明显优于只给安装命令。

其中，第 1、2 项建议进入 xverif 的后续设计评审；第 3、4 项适合借鉴产品组织方式，但必须按 xverif 的 NPI、LSF、license 和现有 fixture/run-manifest 合同重新设计。

不建议吸收的部分包括：FST/VCD 转换链、pyslang 静态追踪、失败后继续提供降级数据、测试 prerequisite 自动 SKIP、把所有能力平铺成大量 MCP tool，以及通过 monkey patch 改写 MCP SDK 私有实现。

## 2. 评审范围与基线

### 2.1 代码基线

- `wave-mcp`：克隆于 `<wave-mcp-clone>`，上游为 <https://github.com/Tencent/wave-mcp>。
- `wave-mcp` 固定提交：`867df476d699275351fdc4caaedf8fd9d5164223`，提交时间 2026-09-03，版本 `v0.2.0`。
- xverif 固定提交：`5110099482b9433aa7db475c1498d7dc9d6819de`；评审同时读取了当前工作树，但未修改任何 xverif 源码、配置、schema、测试或 skill。
- `wave-mcp` 上游工作树保持源码干净；本次仅新增被 `.gitignore` 排除的本地 conda 环境 `.conda-wave-mcp/`。

### 2.2 明确排除

本报告不比较、也不建议采用以下技术路线：

- FST 读取、VCD/FSDB 转 FST、相关性能和 license 论述；
- pyslang/UHDM 风格的 RTL 静态 driver、fanin、fanout、guard 和 trace 实现；
- “开源波形格式对商用数据库”的路线选择；
- 用静态解析结果替代 NPI 设计数据库或 active-driver 证据。

这些能力只在理解 `wave-mcp` 的产品边界时作为背景，不进入 xverif 的技术选型。xverif 的底层事实来源继续保持 NPI。

### 2.3 证据类型

结论来自以下材料：

- `wave-mcp` 的 [README](../../wave-mcp/README.md)、[server.py](../../wave-mcp/wave_mcp/server.py)、[session.py](../../wave-mcp/wave_mcp/session.py)、[CLI query](../../wave-mcp/wave_mcp/cli/query.py)、[viewer 状态](../../wave-mcp/wave_mcp/viewer/state.py)、[viewer 生命周期](../../wave-mcp/wave_mcp/viewer/manager.py)、[测试入口](../../wave-mcp/tests/run_regression.py) 和 [fieldkit](../../wave-mcp/tests/fieldkit/README.md)；
- xverif 的 [MCP 架构](../xverif_mcp/README.md)、[MCP server](../xverif_mcp/src/xverif_mcp/server.py)、[tool policy](../xverif_mcp/src/xverif_mcp/tool_policy.py)、[action registry](../xdebug/specs/actions/actions.yaml)、[证据合同](../skills/xverif/references/core/evidence-contract.md) 和 [波形渲染工作流](../skills/xverif/references/workflows/waveform-render.md)；
- 本次在独立 conda 环境中的实际运行结果。

## 3. 产品定位差异

| 维度 | wave-mcp | xverif | 评审判断 |
| --- | --- | --- | --- |
| 产品边界 | 单一 RTL 波形调试 MCP，session 构建、查询、diff、viewer 一体化 | 芯片验证工具集合，覆盖 debug、coverage、bit、entry、log location、SVA，并通过统一 MCP 接入 | xverif 的范围更广，不能用工具数量直接比较成熟度 |
| 底层事实源 | FST 值数据库与独立 RTL 精化结果组合 | NPI 设计数据库、FSDB、VDB 及 native engine | 坚持 xverif 方案，不引入双事实源 |
| MCP 暴露 | 34 个细粒度函数直接注册成工具 | 约 36 个 MCP 工具；xdebug 再通过 catalog/schema/query 投影 73 个 action | xverif 的两级发现机制更适合大能力面和严格 schema |
| session | Python 进程内字典；stdio 默认 session；HTTP 可多 session；同 ID 打开会替换旧 session | 每个 xdebug/xcov session 独立 stdio-loop 进程/job，支持 direct/LSF、doctor、gc、busy/recovery lane 和 canonical session ID | xverif 生命周期与调度能力明显更强 |
| 输出 | dict 同时进入 `structuredContent`，另渲染 YAML-like 文本 | action-specific request/response schema；JSON 与 token-first XOUT；完整性和错误字段统一 | xverif 合同更严格、更适合确定性结论 |
| 人机协作 | 浏览器交互 viewer，agent 写 desired，浏览器回 actual | `list.export` + JPG/stats + 确定性 action 回证；nWave rc 与 cursor 是单向控制为主 | wave-mcp 的双向 viewer 是最明显的可学习项 |
| 运维 | stdio 或 streamable HTTP；本机进程内管理 | stdio；direct/LSF、UDS、环境指纹、timeout、cleanup、tombstone | wave-mcp 更轻，xverif 更符合真实 EDA 场景 |
| 离线部署 | 两档 glibc bundle、独立 CPython、wheel 审计、安装/升级/回滚 | Python MCP 包加 native/EDA 环境配置，重点解决 direct/LSF/NPI | wave-mcp 的交付包装值得借鉴，底层依赖模型不能照搬 |
| 测试治理 | 自定义 runner，按环境自动跳过；含 viewer 并发和 browser e2e | catalog/gate/fixture/preflight，required cache miss 不自动构建或 SKIP | xverif 门禁更可信；wave-mcp 的 viewer 专项用例值得借鉴 |

## 4. 架构与合同分析

### 4.1 wave-mcp 的优势：端到端路径短

`wave-mcp` 的 34 个工具直接对应 Python 函数。CLI 从同一函数签名和 MCP registry 自动生成参数，因此新增工具天然获得 MCP 与 CLI 两种入口。这种方式在能力面较小、参数简单时非常高效，用户也容易从 README 复制命令开始使用。

它的 `prepare_session` 进一步把“准备数据—建立 session—打开 session—返回能力摘要”收敛为一个入口。session summary 会直接告诉 agent 当前是 `full` 还是 `static`、netlist health、时间范围、scope/signal 数量和可用工具，从而减少盲目试错。

代价是 public function、MCP schema、CLI 参数和业务实现紧密耦合。34 个 MCP input schema 均未显式发布 `additionalProperties: false`；运行时传入未知字段会失败，但本次探针只得到通用 `UnexpectedToolError`，错误定位不如 xverif 的 schema/error layer 清晰。复杂的 conditional-required、共享对象、response completeness 和版本迁移也较难在函数签名模型中表达。

### 4.2 xverif 的优势：native action 是唯一事实源

xverif 把 native action registry、request/response schema、example、MCP 投影和 skill guidance 分开维护。当前 xdebug registry 有 73 个 action，其中 65 个 stable、8 个 experimental。agent 先读取有界 action guide，再读取选定 action 的精确 schema，避免把 73 个动作全部平铺进 MCP 上下文。

这种设计维护成本更高，但对 xverif 是必要的：

- action 需要覆盖 design、waveform、combined、session、APB、AXI、stream、event 等不同合同；
- 同名参数必须在 CLI、MCP、schema、example 和实现中保持一致；
- session 要跨 MCP、native frontend、engine、UDS/LSF 和 NPI handle；
- response 必须明确扫描是否完整、分析是否完整、返回是否截断，以及 total/returned count。

因此，不建议照搬 `wave-mcp` 的“函数签名自动成为全部 surface”。可以学习的是自动生成体验：从 xverif 已有 action schema 生成 shell completion、示例命令或轻量 query client，而不是让 Python 签名取代 action registry。

### 4.3 完整性合同：xverif 明显更强

`wave-mcp` 的 `diff_waveforms` 已有较好的局部完整性表达：`coverage=complete|truncated`、完整 diverging 数量和 `diverging_truncated`。但这一设计没有贯穿所有 collection 工具。例如：

- `list_child_instances`、`list_signals` 和 `list_modules` 会按固定上限裁剪，却主要返回裁剪后的 `count`；
- `signal_values` 和 `signal_values_in_range` 返回受 `max_number_of_values` 限制的 rows，但没有统一的 total count、returned count 和 scan-complete 字段；
- `trace_value` 使用局部 `truncated`，未形成跨 action 的 canonical completeness 语义。

xverif 已统一要求 `scan_complete`、`analysis_complete`、`response_truncated`、`total_count`、`returned_count` 和 `truncation_scopes`，并规定不完整时不能作全量结论。这个方向不应退回 wave-mcp 的局部约定。

### 4.4 session 新鲜度：思路相同，强度不同

`wave-mcp` 会记录波形和 filelist 指纹，并在打开 session 时检查波形首段 hash及 RTL/netlist mtime。发现不一致时，它在 `warnings` 中提示“可能过期”，仍允许后续查询。本次内置 smoke session 就触发了 `RTL source newer than netlist maps`，但测试继续通过。

xverif 可选 `run_manifest` 使用发布态 schema 和资源 SHA-256 对 FSDB/daidir 做 fail-closed 校验；manifest 缺失、格式错误、状态未发布、资源或 digest 不匹配都会阻止 session.open。对确定性调试而言，xverif 的策略更合适。

可借鉴的不是降低强度，而是把 xverif 的 run-manifest/preflight 结果在 session.open 响应里组织得更接近“准备清单”：明确输入、命中缓存、耗时、能力和下一步建议，让用户更容易理解失败发生在哪一层。

### 4.5 生命周期和并发

`wave-mcp` 的 SessionManager 是进程内字典，没有显式锁；同 session ID 再次打开时直接关闭并替换。它支持 streamable HTTP 多 session，但生命周期模型仍以单本地用户为中心。viewer 的 `owner` 当前也只是标签，源码明确说明未来才做真正的多用户隔离。

xverif 已经处理同 session request 串行、多 session 并行、busy close、recovery lane、进程退出、LSF job、doctor/gc、timeout、cleanup partial 和 tombstone。这个复杂度来自 NPI/EDA 真实运行环境，不能用 wave-mcp 的进程内模型简化掉。

如果未来为 xverif 增加 HTTP，不应照搬 wave-mcp 当前实现。必须先解决认证、session ownership、路径授权、artifact root、资源限额、请求取消和远端 NPI/LSF 生命周期，再决定 transport。

## 5. 最值得学习的设计

### 5.1 P0：双向波形视图协议

这是本次评审最有价值的发现。

`wave-mcp` 没有把 viewer 仅仅当作“生成一张图”，而是定义了一个可同步状态文档：

- agent 写入 `desired`：信号、游标、viewport、marker、diff 和 annotation；
- 浏览器回写 `actual`：实际游标、viewport、selected/displayed signals 和 `user_dirty`；
- revision 保证 agent、server 和 browser 知道状态是否已应用；
- annotation 带 confidence 与 evidence，并以 append-only 时间线保留分析过程；
- 同一波形集复用流式后端，视图有 LRU 上限和显式 close；
- viewer 失败不影响分析工具，但失败状态会明确返回。

xverif 当前的 `list.export -> xwaveform JPG/stats -> action 回证` 很适合离线证据和批量报告，但人机交互是单向的。`waveform.cursor.*` 和 `nwave.rc.generate` 提供了控制基础，却还没有“用户把当前观察位置返还给 agent”的统一合同。

建议后续单独做一个设计评审，目标不是引入 FST viewer，而是定义 **NPI-backed view control protocol**：

```text
agent 确定性 action
        |
        v
view desired state（signals/cursor/window/markers/annotation/evidence refs）
        |
        v
nWave 或独立 UI 展示层
        |
        v
view actual state（cursor/window/selection/user_dirty/revision）
        |
        v
agent 用 NPI action 重新取证
```

底层值、层次、driver 和 active trace 始终来自 NPI；UI 只做呈现和交互，不成为事实源。annotation 中应保存 action、session、time/range、signal path、completeness 和 finding/error code 的引用，而不是自由文本证据。

### 5.2 P0：保密项目 fieldkit

`wave-mcp/tests/fieldkit` 的思路很适合企业验证环境：在不能外发 RTL、波形、路径和信号名时，输出可复现问题所需的结构指纹，例如：

- 数据方言和结构直方图；
- scope 深度、信号宽度分桶、命名模式类别；
- driver kind 分布、模块复杂度分桶、跳过成员计数；
- 阶段耗时、错误分类码和脱敏上下文 hash。

xverif 经常需要定位 NPI 版本、FSDB/VDB 方言、超大设计层次、特定 handle 类型或环境差异。建议建立 xverif 自己的只读诊断包，但所有采集仍通过 NPI 和现有 action/doctor：

- 默认禁止导出完整路径、信号名、RTL 片段、唯一 session ID 和环境凭据；
- 仅输出 schema 版本、工具/NPI 版本、计数/分桶、耗时、稳定错误码和不可逆短 hash；
- 报告自身带字段白名单 schema，unknown fields fail-closed；
- 把“允许外发”和“仅本地查看”字段分层；
- 用合成 fixture 验证报告足以复现问题类别，而不是只检查报告非空。

### 5.3 P1：一步式 preflight 与能力摘要

可以借鉴 `prepare_session` 的用户体验，但不应在 xverif 内偷偷生成数据库或 fallback。

建议优先改进文档/编排层，而非立即新增 action：

- 输入：显式 FSDB/daidir/run-manifest、backend、queue/resource；
- preflight：路径、manifest、NPI runtime、license、LSF 环境、缓存/fixture 状态；
- 输出：每一步 `not_run|passed|failed`、耗时、错误层、是否可恢复、session capability；
- 失败时停止，不自动切换 direct/LSF、transport、数据源或测试层级；
- 成功后给出最小 `recommended_actions`。

xverif 已有 session.open、doctor、LSF doctor、环境指纹和 action guide，所缺主要是把它们组织成首次接入时更短、更清晰的路径。

### 5.4 P1：离线 bundle 与兼容矩阵

`wave-mcp` 的离线文档明确区分构建机和目标机，提供 standalone Python、wheelhouse、glibc 2.17/2.28 分档、平台 tag 审计、sanity check、升级和回滚。这种交付工程值得复用。

xverif 不能照搬“全自包含”：NPI runtime、EDA 安装和 license 仍由站点提供。但可以把控制面做成版本化 bundle：

- 固定 Python 与 MCP SDK；
- 打包 xverif MCP、schema、skill、wrapper 和必要 native binary；
- 安装时只绑定站点的 `VERDI_HOME`、NPI lib、LSF 和 license；
- 启动前输出兼容矩阵和 machine-readable doctor；
- 发布物携带 schema/action/toolchain fingerprint；
- 保留上一个 bundle，以路径切换完成回滚。

### 5.5 P2：测试和文档中的产品化细节

可选择性借鉴：

- viewer 状态更新的原子性、revision、一百并发 annotation、socket 释放、幂等 close 和资源复用测试；
- README 中“按用户环境选安装路径”的决策表；
- CLI 与 MCP 同名示例、常见错误及部署限制集中呈现；
- 用真实规模数据说明验证范围，但必须附可审计的测试清单、版本和未覆盖项。

## 6. 不建议采用的做法

### 6.1 不采用 FST 和静态 trace

这是既定技术边界。即使这些路线在免 license 和轻部署方面有吸引力，也会让 xverif 同时维护 NPI 与独立 RTL/波形语义，带来 interface/modport、generate、加密 RTL、优化后对象、active driver、coverage 对齐和版本兼容的双重成本。

### 6.2 不采用“失败后继续服务”的默认策略

`wave-mcp` 明确宣传 netlist 失败后值查询继续可用、部分网表继续服务，viewer 缺失时分析工具继续。这种组件隔离本身合理，但对 agent 来说必须区分：

- 可选呈现能力缺失：可以返回 unavailable；
- 结论所依赖的数据源不完整：必须 fail-closed 或发布 canonical incomplete 状态；
- 用户要求的 backend/transport 不可用：不得自动切换。

xverif 现有完整性合同和 fallback 规则更严格，应保持。

### 6.3 不采用 SKIP 伪装成 PASS

`wave-mcp` 的 viewer e2e 在资产或 Playwright 缺失时打印 SKIP 并以 0 退出；外层 runner 只按 return code 判断，因此最终把该 suite 显示为 PASS。四态和项目级 suite 虽显示 SKIP，但也不会使 quick runner 失败。

xverif 当前 catalog/fixture/gate 设计更可靠：required fixture cache miss 是前置失败，普通 regression/nightly 不自动构建、不降级为 SKIP。这个原则应保留。若引入 viewer 测试，应把 `passed/skipped/not_selected/blocked` 作为机器可读的互斥状态，不能只看 exit code。

### 6.4 不平铺所有 xdebug action 为 MCP tool

34 个工具在 wave-mcp 规模下尚可管理，但 xdebug 当前已有 73 个 action，xverif 还有 coverage、bit、entry、location 和 SVA。继续使用“有界 guide + action schema + generic query”更节省模型上下文，也更容易保持 native/MCP 同合同。

### 6.5 不依赖 MCP SDK 私有 monkey patch

`wave-mcp` 为同时提供可读文本和完整 `structuredContent`，运行时替换 MCP SDK 私有 `_convert_to_content`；SDK 变化时会静默 no-op。目标体验是好的，但实现依赖私有符号且失败不可见。

xverif 已有稳定的 XOUT/JSON 策略，应通过公开 MCP result API 和自身 serializer 维持，不应照搬 monkey patch。

### 6.6 不直接开放无治理的 HTTP 多用户服务

`wave-mcp` HTTP 默认绑定 loopback，适合本机轻量使用；其 session 和 viewer owner 尚不是安全边界。xverif 涉及 EDA 数据路径、license、LSF job 和 artifact write，若未来支持 HTTP，必须先补齐认证授权、用户隔离、审计和限额，不能仅把 stdio transport 换成 streamable HTTP。

## 7. 本次测试记录

### 7.1 环境

- conda 环境：`<wave-mcp-clone>/.conda-wave-mcp`
- Python：3.11.16
- 安装：在该环境执行 `python -m pip install -e .`
- 未创建或修改 xverif Python 环境。

### 7.2 正式入口

执行：

```bash
NO_PROXY=127.0.0.1,localhost \
no_proxy=127.0.0.1,localhost \
.conda-wave-mcp/bin/python tests/run_regression.py --quick
```

结果：runner 返回 `overall: PASS`，但需要按实际覆盖拆解：

| suite | 本次事实 | 说明 |
| --- | --- | --- |
| unit/smoke | PASS | 打开内置 session，层次、信号、值、driver、fanin、connectivity、active driver、trace_value 均执行；同时报告 RTL/netlist stale warning |
| unit/definition_name | PASS，8/8 | 覆盖层次 anchor、DUT root、interface 不误推断和 fallback |
| unit/diff | PASS，31/31 | 覆盖首分歧、clock aligned、X/Z、missing、截断和 MCP wrapper |
| unit/viewer | PASS，62/62 | 覆盖状态原子更新、长轮询、HTTP API、并发 annotation、端口释放与幂等停止 |
| viewer/e2e | **实际 SKIP** | viewer assets 缺失；子脚本 exit 0，外层显示 PASS |
| fourstate | SKIP | `iverilog/vvp` 不在 PATH |
| projects | SKIP | 使用了 `--quick` |

首次执行未设置 `NO_PROXY` 时，viewer localhost 请求被宿主 HTTP proxy 转发并返回 502，导致 runner FAIL。确认环境没有 `NO_PROXY` 后，在不改变测试层级、代码或数据源的前提下显式排除 `127.0.0.1/localhost`，同一 viewer 单测 62/62 通过。因此第一次失败属于运行环境代理差异，不是 viewer 产品回归；同时也说明测试入口可增加 loopback proxy preflight。

### 7.3 未验证项

- 未安装 viewer assets、Playwright 和 Chromium，未执行真实 browser e2e；
- 未安装 `iverilog/vvp`，未执行 four-state suite；
- 未配置私有 project assets，未复核 README 中 225 万信号和 310 万次调用的生产验证数字；
- 未运行 FSDB/VCD/FST 转换和静态 trace 对比，因为明确不在本次路线评审范围；
- 未做 wave-mcp 与 xverif 的性能 benchmark，因为底层数据源不同，直接 benchmark 不具备决策意义；
- 未运行 xverif 回归，因为本任务是只读评审，且没有修改 xverif 代码。

## 8. 建议的后续工作及验收标准

本报告不授权实施以下事项；建议另行确认后分阶段开展。

### 阶段 A：NPI-backed 双向 viewer RFC

交付物：只写设计文档和 schema 草案，不修改 runtime。

验收标准：

- 明确 UI 不是事实源，所有值和因果结论回到 NPI action 验证；
- 定义 versioned `desired/actual` schema、revision、ownership 和 lifecycle；
- annotation 可引用 session/action/signal/time/completeness/finding；
- 说明 nWave 集成与独立 UI 两种实现的边界和安全模型；
- 定义 stdio、LSF、SSH 和无图形计算节点下的使用路径；
- 给出并发、断线重连、用户移动游标、session 关闭和资源回收测试矩阵。

### 阶段 B：脱敏 fieldkit RFC/原型

交付物：字段白名单、隐私威胁模型、合成 fixture 上的样例报告。

验收标准：

- 不包含完整路径、信号名、RTL、波形值、凭据、license 内容或完整唯一 ID；
- 报告能区分 NPI 加载、session、schema、transport、LSF 和 action 层错误；
- 关键统计带完整性字段，截断不可被误解为全量；
- 同一问题类别在脱敏后仍可用合成 fixture 复现；
- schema unknown fields fail-closed，并有自动隐私审计测试。

### 阶段 C：首次接入与离线交付优化

交付物：preflight 编排说明、兼容矩阵、版本化 bundle 方案。

验收标准：

- 不自动切换 backend、transport、数据源或测试层级；
- 逐步报告 Python/MCP、native binary、NPI、Verdi、license、LSF 和 run-manifest 状态；
- 控制面 bundle 可离线安装、sanity check、升级和路径级回滚；
- bundle 与 schema/action/toolchain fingerprint 一一对应；
- 不把站点 EDA runtime 或 license 打包进发布物。

## 9. 最终判断

`wave-mcp` 对 xverif 的最大启发不是“换一种方式读波形”，而是把已经得到的调试结论变成用户可见、可操纵、可继续对话的工作空间，并把保密现场反馈和离线交付做成产品能力。

xverif 在确定性合同、NPI 深度、协议分析、coverage、session/LSF 生命周期和测试门禁上已经明显更强。后续最合理的策略是：**保留 xverif 的 NPI 与严格合同内核，选择性吸收 wave-mcp 的双向视图协议、脱敏诊断包和交付体验。**
