# xverif 测试内容评审（2026-08-09）

## 1. 评审原则

本评审按以下硬原则检查现有测试内容：

- 不能只有单元测试，必须包含真实 component/integration/system 测试。
- 必须覆盖 MCP 全链路。
- 除 LSF 调度仿真外，不允许 fake backend、fake engine、fake loop 或 fake CLI 冒充产品链路。
- 评审只形成发现和建议，不因评审修改代码。

## 2. 总体结论

当前 catalog 已明显超过单元测试层级，并拥有大量真实 EDA/NPI/FSDB/VDB 系统测试；最终 regression 1039 项和 nightly 1147 项证明正式门禁可执行。

但按上述硬原则，当前测试内容仍不能判定为完全合格，主要有两个 P0 缺口：

- MCP 覆盖分散在“真实 MCP process”和“真实 NPI/FSDB/VDB adapter”不同 suites 中，没有一条测试在同一用例内证明 MCP wire protocol 到真实数据库的完整链路。
- 非 LSF 测试中仍存在 fake loop、fake engine、fake CLI 和 `_TestBackend`。

因此当前状态应定义为：真实回归能力较强，但 MCP 单链路证据和 no-fake 合规性尚未闭环。

## 3. Findings

### P0：缺少单条 MCP wire 到真实数据库的端到端证据

现有相关 suites：

- `xverif_mcp.process`：验证真实 MCP server process、stdio initialize 和 tool 调用边界。
- `xverif_mcp.action_smoke`：启动实际 action smoke 流程，并使用真实 DAIDIR/FSDB/NPI fixture。
- `xdebug.mcp_direct`：使用真实 xdebug session、FSDB/NPI，但主要通过进程内 FastMCP 调用。
- `xcov.mcp_integration`：MCP adapter 会启动真实 `tools/xcov --stdio-loop` 并访问真实 VDB/NPI，但 MCP 调用仍主要发生在进程内 FastMCP 层。

缺失证据：

- 没有一个测试同时完成真实 MCP client wire handshake、真实 MCP server 独立进程、真实 adapter/stdio-loop、真实 xdebug 或 xcov 子进程、真实 FSDB/VDB/DAIDIR 查询，并验证最终业务结果与清理。

风险：

- 当前每一段分别通过，但进程环境继承、stdio framing、server 生命周期、adapter 路由和真实 EDA 后端组合在一起时仍可能出现集成缺陷。

建议：

- 新增一条 `mcp.real_fullchain` system suite。
- 至少覆盖 xdebug combined query 和 xcov exclusion/query 各一条真实链路。
- MCP client 必须走 JSON-RPC wire，不直接调用 FastMCP Python 函数。
- server、adapter、tool loop 和 EDA backend 都使用正式入口；禁止 monkeypatch/fake。
- 断言 initialize、tools/list、tools/call、真实业务字段、session close、子进程退出和日志清理。

### P0：非 LSF fake 仍存在

已发现的典型位置：

- `xcov/tests/test_xcov.py`：仍有最小 `_TestBackend`。
- `xverif_mcp/tests/test_loop_wrapper_uds.py`：存在 `_make_fake_loop`。
- `xdebug/tests/contract/test_session_lifecycle_internal_requests.py`：存在 `_FAKE_ENGINE`。
- xdebug legacy/unit 测试中仍有 fake CLI/runner 路径。
- `skills.x_npi` 的部分单元测试使用 fake coverage API。

这些 fake 即使位于 unit/component 层，也违反“除 LSF 外不允许 fake”的硬原则。

风险：

- fake 往往复刻预期实现，而不是验证真实进程、真实 schema、真实 NPI handle 生命周期。
- action 删除、参数变化和 session 生命周期错误可能在 fake 中继续通过。
- 本轮 xcov 旧 fake-dependent tests 大面积失败就是直接例证：生产 fake 被删除后，旧断言没有真实产品语义支撑。

建议：

- 用小型 generated fixture、真实临时 UDS server、真实 stdio-loop 或真实 NPI/VDB fixture 替换 fake。
- 对纯错误合同，优先构造真实非法输入，不伪造 engine 返回。
- LSF fake 保留在明确命名的 `mcp_fake_lsf` suite 中，并与 real LSF capability suite 严格分开。
- 在 catalog/static audit 增加 no-fake 检查，禁止非 LSF suite 新增 `Fake*`、`_fake_*`、monkeypatched backend/engine/loop。

### P1：xcov 删除旧 fake tests 后存在确定性细粒度覆盖缺口

本轮删除了 32 条依赖旧 rich fake backend 的测试。删除是必要的，因为继续扩充 fake 与 no-fake 原则冲突，而且这些测试假设已不符合统一后的 `NpiCoverageBackend`。

当前真实 suites 已覆盖：

- NPI items 和 score-bearing 合同。
- URG scopes、summary 和 EL。
- exclusion add/remove/load/export/CSV。
- xcov MCP query/exclusion 链路。

仍需补齐的细粒度场景：

- 多层 hierarchy filter 的边界组合。
- functional/assert metric 的小数据精确 golden。
- export 截断、排序和空结果。
- 多 test merge 与具体 test 选择。
- removed action 返回 `UNKNOWN_ACTION` 的公开回归。

建议使用可生成的最小真实 VDB fixtures，不恢复 fake backend。

### P1：native XOUT suite 的阶段合同没有在 catalog 命令中自包含

`xdebug.native_xout_all` 要求 `XDEBUG_XOUT_PHASE=baseline|final`，但普通 nightly 命令没有从 catalog 自动注入该值。本轮必须显式设置 `XDEBUG_XOUT_PHASE=final` 才能执行完整 nightly。

风险：

- 用户按 AGENTS.md 的通用 nightly 命令运行时，会在测试体内因 phase 为空失败。
- suite 的必需环境合同分散在 runner 实现和历史复盘中。

建议：

- 在 catalog 为 final nightly 明确声明默认环境，或拆成 `native_xout_baseline` 与 `native_xout_final` 两个 suite。
- 保持 phase 显式，禁止测试自行猜测或 fallback。

### P1：benchmark 将宿主调度噪声与产品回归混在同一硬断言中

本轮同一代码连续运行出现：

- RSS 超限 32 KiB。
- APB cold p95 99 ms 对目标 80 ms。
- Stream cold p95 1115 ms 对目标 1000 ms。

同时 scanner invocation、功能 golden 和较宽 regression limits 均稳定通过。

已作为回归修复增加统一噪声带，但测试架构仍建议进一步区分：

- 功能/扫描次数硬门禁。
- 宿主性能 regression limit。
- phase target 趋势指标。

建议输出 metrics artifact 并做多次历史基线比较，避免单次 host 调度决定 nightly 成败。

### P2：新 AXI DW64 数据未进入正式 catalog

工作区存在未跟踪目录 `xdebug/testdata/waveform/axi_vip_real_dw64/`，但当前 catalog 正式 `xdebug.axi_vip` 仍不能据此宣称覆盖 DW64 fixture。

建议在该数据完成后显式注册 fixture、fingerprint、suite membership 和 expected contract；注册前不要把它计入全仓覆盖结论。

## 4. 已具备的真实测试能力

当前测试体系的有效部分包括：

- `regression` 38 个 suites，覆盖 unit/static/component/integration/system 的确定性回归。
- `nightly` 56 个 suites，覆盖真实 NPI、FSDB、VDB、DAIDIR、URG、VCS/VIP、active trace、native XOUT 和 benchmark。
- xdebug session、schema、contract、stream、APB、AXI、active-driver/active-trace 等真实数据库测试。
- xcov NPI exclusion、URG backend 和 MCP integration。
- xsva VCS/真实编译链路。
- fixture fingerprint、required preflight 和显式 prepare 合同。
- real LSF capability 与 fake LSF suite 分离；本轮 real LSF 因工具缺失明确 skip，没有伪造通过。

## 5. 建议整改顺序

1. 建立 `mcp.real_fullchain`，形成 wire 到真实数据库的单条可审计证据。
2. 建立 no-fake static audit，并列出 LSF 唯一豁免目录/suite。
3. 逐步替换 `_TestBackend`、fake loop、fake engine、fake CLI；每替换一类就增加真实 fixture 测试。
4. 用小型真实 VDB 补齐 xcov 删除 fake tests 后的细粒度合同覆盖。
5. 把 native XOUT phase 写入 catalog 的显式 suite 合同。
6. 将 benchmark phase target 改为趋势报告，保留 regression limits 作为稳定硬门禁。

## 6. 评审边界声明

- 本文仅记录测试内容评审。
- 本文中的 P0/P1/P2 建议没有在本轮实施，也没有因评审修改代码。
- 本轮实际代码修改均由已执行回归的明确失败，或用户要求检查的近期 xcov 明显错误驱动。

## 计划实施状态

### 已关闭缺口

- MCP 全链路：新增 xverif_mcp.real_fullchain nightly suite，通过 MCP SDK stdio_client 启动真实 server，覆盖 initialize、tools/list、xdebug FSDB 查询、xcov VDB summary、exclusion 写回和 session 清理。
- xcov 真实数据：正常 summary 与 exclusion 语义由真实 comprehensive/exclusion VDB 验证，不再以 backend 替身证明正常行为。
- fake 政策：新增 testinfra/fault_injection_exceptions.v1.json 和 AST 静态审计。正常测试引用行为替身会直接失败；异常注入例外必须精确登记原因，LSF 保持既定例外。
- 正常替身测试：移除 action smoke、loop lifecycle、adapter output、test runner 和 x-npi exclusion 中重复验证正常行为的替身版本，由真实 MCP/native/fixture suite 接管。
- native XOUT：catalog runner 支持声明环境变量，xdebug.native_xout_all 固定执行 final phase。
- benchmark：阈值 artifact 明确区分硬回归边界和信息性目标；避免把宿主 CPU/wall-clock 抖动误判为产品回归，同时保留 scanner、样本、RSS 和估算内存硬门禁。
- DW64：按最终需求删除，不纳入 fixture 或测试矩阵。

### 最终结论

- 正常产品路径已由真实 CLI、真实 MCP stdio、真实 FSDB/VDB/NPI 覆盖。
- fake/mock/dummy/stub 产品行为只允许出现在明确的故障注入测试或 LSF 测试中，并由静态门禁持续约束。
- 最终 nightly 为 1119 passed, 2 skipped, 39 subtests passed；skip 仅为真实 LSF 工具缺失。
