# xdebug 完整测试环境规划

## 1. 文档目标与边界

本文档基于当前仓库中真实存在的 xdebug 源码、构建文件、文档、schema、
examples、现有 tests、testdata、xverif-mcp 接入代码以及近期相关提交制定。

目标是建立一套覆盖以下范围的测试体系：

- xdebug CLI、request、response、xout、JSON 和 schema 合同。
- xdebug 内部核心逻辑。
- 小 RTL、小 FSDB、小 daidir 的 synthetic 测试。
- 真实 FSDB、真实 daidir 的 realdata 测试。
- stdio-loop 和 session 生命周期测试。
- xverif-mcp 到 xdebug 的 direct 和 LSF 连接测试。
- 当前代码真实存在的 waveform、design、combined active trace、APB、AXI、
  list、cursor、event、interface/modport 等能力。

本文档只规划测试，不规划大范围重构。后续如果为了可测性需要调整产品代码，
应限制在小范围依赖注入、状态隔离或诊断信息补充。

测试环境默认具备完整 VCS、Verdi、NPI、FSDB、daidir 和 LSF 条件，不按
license 分类。真实 LSF 测试属于可选扩展项，不作为首版、日常回归或发布门禁
的强制条件；fake LSF 和 direct 完整链路仍是必测项。

## 2. 扫描依据

### 2.1 xdebug 源码与构建

主要依据：

- `xdebug/Makefile`
- `xdebug/src/main.cpp`
- `xdebug/src/api/`
- `xdebug/src/backend/engine_adapter.*`
- `xdebug/src/session/session_catalog.*`
- `xdebug/src/engine/`
- `xdebug/src/design/`
- `xdebug/src/waveform/`
- `xdebug/src/combined/`
- `tools/xdebug`

当前构建产物由 frontend `xdebug` 和统一后端
`xdebug/libexec/xdebug-engine` 组成。design、waveform 和 combined handler
均进入统一 engine。

### 2.2 文档、schema 和 examples

主要依据：

- `xdebug/README.md`
- `xdebug/help.txt`
- `xdebug/docs/JSON_API.md`
- `xdebug/docs/action-inventory.md`
- `xdebug/docs/AGENT_GUIDE.md`
- `xdebug/schemas/v1/`
- `xdebug/examples/requests/`
- `xdebug/examples/responses/`
- `xdebug/specs/actions/actions.yaml`

schema 和 example 已有静态校验工具，但当前校验主要证明文件存在、JSON/schema
合法和 action 名称基本对齐，不能替代真实 binary 行为测试。

### 2.3 现有测试

主要依据：

- `xdebug/tests/unit/`
- `xdebug/tests/waveform/run_complex_wave.py`
- `xdebug/tests/design/run_semantics.sh`
- `xdebug/tests/combined/run_active_driver_fixture.py`
- `xdebug/tests/active_trace_chain/`
- `xdebug/tests/realdata/run_system_wave.py`
- `xdebug/testdata/`

### 2.4 MCP 接入

主要依据：

- `xverif_mcp/src/xverif_mcp/adapters/xdebug.py`
- `xverif_mcp/src/xverif_mcp/sessions/session_manager.py`
- `xverif_mcp/src/xverif_mcp/sessions/loop_session.py`
- `xverif_mcp/src/xverif_mcp/sessions/launchers.py`
- `xverif_mcp/src/xverif_mcp/lsf/protocol.py`
- `xverif_mcp/src/xverif_mcp/lsf/fake_bsub.py`
- `xverif_mcp/src/xverif_mcp/server.py`
- `xverif_mcp/tests/`
- `xverif_mcp/tools/test_actions.py`

### 2.5 APB/AXI 环境参考

APB、AXI synthetic 环境如果需要独立编译和仿真环境，应区分“环境代码参考”
和“编译仿真选项参考”：

- AXI 环境代码以 `<axi-test-root>/test/` 的真实 SVT AXI VIP 工程为主要依据。
- APB 环境代码以该 AXI 工程的结构为模板，并结合 xring 中已经工作的
  `svt_apb_system_env`、APB configuration、interface 连接和 sequence 写法构建。
- VCS 编译分层、编译选项、elaboration、运行目录和 FSDB 生成方式仍以 xring
  Makefile 为准。

AXI 环境代码主要依据：

- `<axi-test-root>/test/Makefile`，仅用于理解工程入口和运行参数，不作为最终
  编译选项的权威来源
- `<axi-test-root>/test/tb/top.sv`
- `<axi-test-root>/test/tb/dut_wrapper.sv`
- `<axi-test-root>/test/tb/env/axi_tb_env.sv`
- `<axi-test-root>/test/tb/env/axi_virtual_sequencer.sv`
- `<axi-test-root>/test/tb/env/axi_scoreboard.sv`
- `<axi-test-root>/test/tests/axi_base_test.sv`
- `<axi-test-root>/test/tests/axi_multi_id_test.sv`
- `<axi-test-root>/test/tests/axi_multi_id_wr_rd_seq.sv`
- `<axi-test-root>/test/tests/axi_slave_mem_delayed_seq.sv`
- `<axi-test-root>/test/tests/test_pkg.sv`

xring 编译选项和 APB 环境主要依据：

- `<xring-root>/dv/cfg/Makefile`
- `<xring-root>/dv/cfg/xring_reuse.f`
- `<xring-root>/dv/tb/xring_top_if.sv`
- `<xring-root>/dv/tb/xring_top_if_connect.sv`
- `<xring-root>/dv/env/xring_env_pkg.sv`
- `<xring-root>/dv/env/xring_env.sv`
- `<xring-root>/dv/env/xring_virtual_sequencer.sv`
- `<xring-root>/dv/test/xring_base_test.sv`
- `<xring-root>/dv/seq/xring_cfg_sequence.sv`
- `<xring-root>/dv/seq/xring_reg_bus_seq.sv`
- `<xring-root>/dv/seq/xring_axi_slave_resp_seq.sv`

如果实现阶段在 environment class、configuration、sequencer、transaction 或
reactive slave response 的具体 API 上存在疑问，应优先查询已安装 VIP 源码和
本地示例。`svtref` 可以作为本机 Synopsys SVT HTML class reference 的辅助查询
工具，但不是测试环境、fixture 构建或实现阶段的强制依赖；`svtref` 不可用、依赖
缺失或索引过慢时，不应阻塞工作，直接改用本地 HTML、已安装 SystemVerilog 源码
和示例。仅当本地资料无法确认时，才搜索网络。

网络搜索仅用于学习 AMBA VIP 环境代码和公开 API 用法，不用于替换 xring 已经
确认的编译、elaboration 和仿真选项。网络资料应优先采用 Synopsys 官方文档或
官方公开材料。

## 3. 当前测试现状

### 3.1 已有能力

当前已有以下测试基础：

- C++ unit：
  - core types
  - action registry
  - action log
  - file exchange
  - process runner
  - session catalog
  - text/xout response builder
  - RC generator
- schema/example：
  - `validate_schema.py`
  - `validate_examples.py`
  - `audit_action_schema_coverage.py`
  - `check_action_contract.py`
- design：
  - UART daidir
  - P3 semantics daidir
  - trace、graph、path、source、FSM、counter、interface 等部分回归
- waveform：
  - value、scope、list、event、verify、signal analysis、handshake
  - APB 查询
  - 仓库外 AXI 环境查询
- combined：
  - `trace.active_driver`
  - interface/modport alias
  - force、assignment、control-only
- MCP：
  - fake stdio-loop
  - fake LSF
  - timeout、crash、session eviction
  - FastMCP tools/list
  - output format

### 3.2 已确认存在的功能

public runtime action 以 `xdebug/src/api/action_registry_init.cpp` 为准。

确认存在的功能域：

- Builtin：
  - `actions`
  - `schema`
  - `batch`
- Session：
  - `session.open`
  - `session.ensure`
  - `session.list`
  - `session.doctor`
  - `session.close`
  - `session.gc`
- Design：
  - driver/load/query
  - signal resolve/canonicalize
  - trace expand/graph/path/explain
  - control/source/expression
  - procedural/sequential/FSM/counter
  - port/instance/interface
- Waveform：
  - cursor
  - scope/value/list
  - APB/AXI
  - event
  - verify/window
  - signal analysis
  - anomaly/handshake
  - RC generation
- Combined：
  - `trace.active_driver`
  - `trace.active_driver_chain`
- CLI：
  - stdin
  - request file
  - 默认 xout
  - `--json`
  - `--stdio-loop`
- Session transport：
  - UDS
  - TCP
  - file transport
- MCP：
  - direct launcher
  - LSF launcher
  - fake LSF
  - stdio-loop session manager

本文档不列出猜测的 action。新增测试必须从 runtime `actions`、schema 或代码
动态发现 action，不再手工维护第二份完整 action 清单。

### 3.3 文档与代码未完全一致的内容

已观察到以下漂移：

- README、help 和 agent guide 应统一使用 `.xdebug/engine/sessions` 路径。
- frontend 当前读取统一的 `.xdebug/engine/registry.json`。
- action inventory 中 `session.list` 仍描述为旧 top-level session store。
- `source.context` 和 `expr.normalize` 的 runtime resource requirement 与
  inventory 描述不完全一致。
- MCP docstring 示例写有不存在的 `trace.drivers`，实际 action 是
  `trace.driver`。
- MCP xdebug raw request 入口已移除；完整 `xdebug.v1` envelope 验证走 CLI/SDK-free 入口。
- `xverif_mcp/tools/test_actions.py` 文案仍称 75 个 action，当前硬编码列表为
  76 个非 removed action。
- active-trace-chain README 提到的 `common/`、`expected/` 和 verdict 流程与
  当前目录内容不完全一致。

这些差异应由 contract test 自动检测，不能继续依赖人工同步。

## 4. 当前测试缺口

### 4.1 基础设施缺口

- C++、shell、Python 和 MCP 测试没有统一编排。
- 每个脚本重复实现 subprocess、JSON 解析、临时 HOME 和 cleanup。
- 没有统一 artifact 保存。
- 没有统一 response normalization。
- 没有 pytest marker 和执行成本分层。

### 4.2 合同缺口

- registry、YAML spec、schema、examples、MCP action list 多源维护。
- schema example 没有全部经过真实 binary 执行。
- 真实 response 没有统一经过 response schema 验证。
- JSON、xout、stdio-loop、MCP 之间缺少结果一致性测试。
- 对空成功、字段错位和错误码漂移防护不足。

### 4.3 功能缺口

重点缺口包括：

- `trace.active_driver_chain` 产品级回归。
- active trace 的 reset、enable、arbiter、valid-ready、截断语义。
- cursor 完整生命周期。
- list 默认对象、隔离、重复和删除边界。
- event `first`、`last`、scan limit 和截断。
- APB wait state、error、back-to-back transfer。
- AXI 多 ID、多 outstanding、乱序 response、AW/W 解耦和 incomplete
  transaction。
- direct UDS 请求 timeout。
- file transport 的真实 engine 集成。
- MCP direct 的真实 xdebug/FSDB/daidir/combined 链路。
- MCP fake LSF 使用真实 xdebug binary 的完整链路。
- 大 FSDB、大 daidir 和复杂 hierarchy 的 realdata 回归。

### 4.4 现有测试的判定风险

`xverif_mcp/tools/test_actions.py` 的 L2/L3 当前只要结果是字典就可能计为通过，
即使响应为 `ok:false`。该入口只能视为连通性探测，不能作为行为回归门禁。

`xdebug/tests/realdata/run_system_wave.py` 只有单个硬编码 FSDB smoke，且只检查
字段存在，不足以覆盖真实项目。

现有 combined 回归保留了缺少许可时跳过的逻辑。新的统一测试环境不按许可分类，
资源缺失应作为环境错误明确报告，不能静默当作测试通过。

## 5. 功能面建模

### 5.1 CLI、request、response、xout、JSON

- 真实入口：
  - `xdebug/src/main.cpp`
  - `xdebug/src/api/request_parser.cpp`
  - `xdebug/src/api/response.cpp`
  - `xdebug/src/api/text_response_builder.cpp`
  - `xdebug/src/api/xout_renderer.cpp`
- 输入：
  - stdin JSON
  - request file
  - CLI output flags
  - request `output`
- 输出：
  - JSON response
  - xout
  - exit code
  - stderr
- 高风险：
  - 默认输出漂移
  - exit code 与 `ok` 不一致
  - stderr/banner 污染 stdout
  - JSON 和 xout 字段语义不一致
- 测试类型：
  - unit
  - contract
  - golden

### 5.2 Action registry、schema、examples

- 真实入口：
  - `xdebug/src/api/action_registry_init.cpp`
  - `xdebug/schemas/v1/actions/`
  - `xdebug/examples/`
  - `xdebug/specs/actions/actions.yaml`
- 高风险：
  - action 多源维护
  - handler 已迁移但 schema/example 未更新
  - resource requirement 漂移
  - removed action 再次暴露
- 测试类型：
  - unit
  - contract
  - golden

### 5.3 Target/resource/session

- 真实入口：
  - dispatcher
  - resource resolver
  - session catalog
  - engine session manager/registry
- 输入：
  - daidir
  - fsdb
  - combined target
  - session ID
  - reuse/reopen
- 高风险：
  - FSDB-only session 无法复用
  - alias/native ID 映射错误
  - 资源变更后错误复用
  - registry 残留和 daemon 泄漏
- 测试类型：
  - unit
  - integration
  - synthetic
  - MCP

### 5.4 Waveform

- 真实代码：
  - `xdebug/src/engine/service/engine_waveform_handlers.cpp`
  - `xdebug/src/waveform/`
- 输入：
  - FSDB
  - signal/time/window/config
- 输出：
  - value、event、change、statistics、transaction、finding
- 高风险：
  - X/Z 误判
  - 时间单位转换
  - 截断后 silent success
  - missing/unknown 混淆
  - large FSDB timeout
- 测试类型：
  - unit
  - synthetic
  - realdata
  - MCP

### 5.5 Design/daidir

- 真实代码：
  - `xdebug/src/engine/service/engine_design_handlers.cpp`
  - `xdebug/src/design/`
- 输入：
  - daidir
  - signal、instance、interface、path
- 输出：
  - assignment、dependency graph、source evidence、semantic explanation
- 高风险：
  - hierarchy canonicalization
  - generate/interface/modport
  - dependency edge 重复
  - 空 related signal
  - 截断统计错误
- 测试类型：
  - synthetic
  - integration
  - realdata

### 5.6 Combined active trace

- 真实代码：
  - `xdebug/src/combined/active_trace_service.cpp`
  - `xdebug/src/combined/active_trace_chain.cpp`
- 输入：
  - daidir
  - FSDB
  - signal
  - requested time
- 输出：
  - active/root driver
  - trace tree
  - candidate
  - active time
  - stop reason/limitation
- 高风险：
  - inactive branch 被追踪
  - reset/enable 优先级错误
  - flop 时间边界错误
  - control-only 被过度解释
  - waveform 截断后错误 resolved
- 测试类型：
  - synthetic
  - golden + invariant
  - realdata
  - MCP

### 5.7 APB/AXI

- 真实代码：
  - `xdebug/src/engine/service/engine_protocol_handlers.cpp`
  - `xdebug/src/waveform/apb/`
  - `xdebug/src/waveform/axi/`
- 真实环境参考：
  - xring SVT APB/AXI VIP 环境
- 高风险：
  - config path 和信号 mapping 错误
  - APB setup/access/wait-state 边界
  - AXI channel pairing 和 ID pairing
  - outstanding 计算
  - incomplete transaction
  - monitor/driver 接线方向错误
- 测试类型：
  - unit
  - synthetic VIP integration
  - realdata
  - MCP

### 5.8 stdio-loop/session/MCP

- 真实入口：
  - `xdebug/src/api/stdio_loop.cpp`
  - `xverif_mcp` session manager、launcher、JSONL protocol
- 高风险：
  - ready 前后 stdout 污染
  - timeout 后子进程和 engine 未清理
  - business error 被误判为 session lost
  - 多 session 映射错误
  - 同 session 并发没有串行化
- 测试类型：
  - unit
  - integration
  - MCP direct
  - fake LSF
  - 可选 real LSF

## 6. 推荐测试分层

| 层级 | 资源 | 验证目标 | 成本 |
| --- | --- | --- | --- |
| unit | 无 EDA 数据 | 纯 C++/Python 核心逻辑 | 秒级 |
| contract | xdebug binary | CLI、schema、输出合同 | 秒至分钟 |
| synthetic-design | 小 daidir | design 语义 | 分钟级 |
| synthetic-wave | 小 FSDB | waveform/event/list/protocol | 分钟级 |
| synthetic-combined | 小 FSDB+daidir | active trace | 分钟级 |
| session | binary+synthetic | daemon、registry、stdio-loop | 分钟级 |
| mcp-direct | FastMCP+binary | direct 完整链路 | 分钟级 |
| mcp-fake-lsf | fake bsub+binary | LSF 控制面和故障注入 | 分钟级 |
| realdata | 项目 FSDB/daidir | 规模、兼容性、稳定性 | 较高 |
| mcp-real-lsf | real LSF | 真实集群连通性 | 可选、高 |
| nightly | realdata+可选 real LSF | 大规模趋势和稳定性 | 很高 |

real LSF 不属于首版最小交付，也不作为合入门禁。具备稳定队列、资源配置和执行
窗口后，可通过 marker 独立启用。

## 7. 推荐目录结构

```text
xdebug/tests/
  conftest.py
  pytest.ini
  runner/
    cli.py
    stdio_loop.py
    normalize.py
    artifacts.py
    assertions.py
    manifests.py
    fixture_build.py
  contract/
    test_cli.py
    test_envelope.py
    test_registry.py
    test_schema_examples.py
    test_output_equivalence.py
  unit/
    cpp/
    python/
  synthetic/
    cases/
      comb_chain/
      register_chain/
      mux_branch/
      reset_enable/
      valid_ready/
      arbiter/
      apb_vip/
      axi_vip/
      interface_modport/
      generate_hierarchy/
      truncated_wave/
    test_design.py
    test_waveform.py
    test_active_trace.py
    test_apb.py
    test_axi.py
  session/
    test_lifecycle.py
    test_stdio_loop.py
    test_batch.py
    test_cleanup.py
  realdata/
    manifests/
    test_realdata.py
  mcp/
    test_direct.py
    test_fake_lsf.py
    test_real_lsf.py
    test_cli_equivalence.py
  golden/
    contract/
    synthetic/
  artifacts/
```

现有 tests 和 testdata 首阶段通过 adapter/manifest 复用，不立即搬迁全部目录。

## 8. 统一 pytest runner

### 8.1 统一结果对象

runner 应返回：

```python
RunResult(
    command,
    cwd,
    env,
    request,
    returncode,
    stdout_raw,
    stderr_raw,
    envelope,
    response,
    normalized_response,
    elapsed_ms,
    timed_out,
    artifacts_dir,
)
```

### 8.2 支持的执行模式

- xdebug request file mode
- stdin mode
- 默认 xout mode
- `--json`
- request `output.format=json`
- `--stdio-loop`
- batch request
- session request
- timeout
- stdout/stderr 分离
- 临时 HOME
- response normalize
- response schema validation
- fixture 编译和缓存
- artifact 保存

### 8.3 隔离原则

- 每个测试默认使用独立 HOME。
- session 名必须包含 worker/run ID。
- pytest-xdist 并行时不得共享 registry、socket、输出目录。
- teardown 后检查：
  - xdebug frontend
  - xdebug-engine
  - socket
  - registry
  - fake/real LSF job
- stdout 是协议通道，stderr 是诊断通道。
- stdio-loop ready 后出现非 JSON stdout 必须判失败。

## 9. Contract 测试规划

### 9.1 CLI 合同

覆盖：

- 无参数 stdin
- `-`
- request file
- 默认 xout
- `--json`
- request `output.format=json`
- 环境变量 JSON 输出选择
- 非法 JSON
- 非 object JSON
- 缺少 `api_version`
- 错误版本
- 缺少 action
- 未知 action
- removed action
- 多余 CLI 参数
- exit code 与 `ok` 一致性
- stderr 不污染 stdout

### 9.2 Registry/schema/example

测试从 runtime `actions` 动态枚举：

1. 每个非 removed action 有 request/response schema。
2. 每个 action 至少有 basic request/response example。
3. example 通过对应 schema。
4. 可执行 request example 经过真实 binary。
5. 真实 response 通过 response schema。
6. runtime status/resource/category 与 YAML spec 一致。
7. engine handler 与 public action 对齐。
8. MCP action discovery 与 runtime catalog 对齐。
9. removed action 不出现在 implemented catalog。

### 9.3 输出一致性

同一 request 分别通过以下入口执行：

- CLI JSON
- CLI xout
- stdio-loop JSON
- stdio-loop xout
- MCP direct JSON
- MCP direct xout

JSON normalize 后比较稳定字段。xout 检查 header、action、summary、error code 和
关键 rows，不对空白和动态字段做脆弱 diff。

## 10. Unit 测试规划

### 10.1 C++ unit

在现有测试上增加：

- request parser 类型矩阵
- validator required field
- resource resolver 的 daidir/fsdb/combined/session/mismatch
- response builder success/error/warning/truncated
- silent-success 防护
- registry 与 engine handler 一一对应
- session registry 原子写、损坏文件和并发更新
- direct socket timeout
- process runner 大 stdout/stderr、进程树和 SIGKILL fallback
- stdio-loop request ID、malformed line 和 quit
- APB setup/access 状态机
- AXI channel/ID pairing 算法
- active trace candidate 排序、stop reason、depth/node limit

### 10.2 Python unit

- response normalize
- golden diff
- invariant assertion
- manifest schema
- artifact writer
- JSONL pending response
- ready 前 noise
- ready 后 pollution
- MCP session eviction
- fake LSF job ID 和 cleanup

## 11. Synthetic fixture 总体策略

每个 synthetic case 应包含：

- RTL/UVM 源码。
- Makefile 或受控 build descriptor。
- 固定 seed。
- FSDB dump 配置。
- 预期 top、signal、interface 和时间点。
- fixture manifest。
- xdebug request 列表。
- golden/invariant。

fixture build 应缓存编译结果，区分：

- source hash
- VCS/Verdi 版本
- compile options
- VIP 环境
- seed

失败时保留 compile、elab、simulation 和 FSDB 生成日志。

## 12. 基础 synthetic case

### 12.1 Design/waveform

| Case | 主要覆盖 |
| --- | --- |
| combinational chain | driver、expand、path、value |
| register chain | sequential update、时间边界 |
| mux branch | active/inactive branch |
| reset-enable | reset/enable 优先级 |
| valid-ready | handshake 和 payload |
| arbiter | winner/loser |
| interface/modport | interface.resolve、port.trace、alias |
| generate hierarchy | scope、canonicalize、instance |
| truncated wave | 波形边界和不确定结论 |

### 12.2 Active trace 断言

支持以下结构化断言：

- `must_include`
- `must_not_include`
- `allowed_candidates`
- `stop_reason`
- `max_depth`
- `reason_contains`
- `path_count`
- `hop_count`
- `signal_path`
- `active_time`
- `waveform_complete`

重点防止：

- inactive MUX branch 被追踪。
- reset 生效时仍追 data。
- enable=0 时仍追上游更新源。
- arbiter loser 被当作 active cause。
- valid-ready 未握手却追 payload transfer。
- X/Z control 被过度解释。
- 波形截断后输出确定性 resolved。
- flop boundary 没有移动 active time。
- interface/modport alias evidence 丢失。

小型 fixture 可以锁 source line，但必须同时验证语义字段，避免只靠行号 golden。

## 13. APB/AXI synthetic 环境

### 13.1 基本原则

APB/AXI 如果需要单独环境，不应只写简单 signal toggle testbench。

环境代码采用以下路线：

1. 先从 `<axi-test-root>/test/` 提取一个能够稳定生成真实 AXI transaction 波形
   的最小 SVT VIP 环境。
2. 保留 multi-ID、multi-outstanding、master/slave agent、reactive slave
   response、memory model、scoreboard 和 FSDB dump 等真实行为。
3. 再以该 AXI 环境的 package/env/test/sequence/top 分层为模板构建 APB 环境。
4. APB 特有的 system configuration、master/slave transaction、interface 连接和
   wait-state/error response 参考 xring 中的实际 APB 代码。
5. 两套环境的 VCS 编译和仿真选项统一参考 xring Makefile。

目标不是复制完整 axi_test 或 xring，而是保留影响波形真实性的关键结构：

- SVT APB/AXI interface 和 UVM package。
- VCS/UVM/SVT 必需 define 和 include path。
- AXI master和 slave system agent。
- APB master和 slave system agent。
- config_db virtual interface 注入。
- 主动 stimulus sequence。
- reactive response sequence 和 memory model。
- monitor、analysis port 和最小 scoreboard。
- DUT/VIP 信号方向连接。
- FSDB 生成。

AXI fixture 应产生协议意义真实的 AW/W/B、AR/R 独立通道活动，不允许通过直接
修改波形或静态 force 伪造 transaction。APB fixture 应产生真实 setup/access
phase、PREADY wait state 和 PSLVERR response。

### 13.2 编译流程参考

无论 AXI 环境代码来源于 axi_test，还是 APB 环境代码由其派生，最终编译流程和
选项均参考 `<xring-root>/dv/cfg/Makefile`。synthetic VIP fixture 应支持：

1. `vlog_com`
   - UVM 和 VIP 公共编译环境。
2. `vlog_rtl`
   - DUT RTL。
3. `vlog_tb`
   - VIP interface/package、env、sequence、test 和 top。
4. `elab`
   - `-debug_access+all`
   - `-kdb`
   - 生成可用 daidir。
5. `ncrun`
   - 固定 testcase 和 seed。
   - 生成 FSDB。

可以提供 `cmp`、`mrun`、`run` 三种入口：

- `cmp`：全编译，不仿真。
- `mrun`：复用 RTL/common，只重编 TB 后仿真。
- `run`：全量编译和仿真。

测试 runner 应根据 source hash 选择最小必要入口。

### 13.3 必需编译选项

以 xring Makefile 为依据，至少评估并保留：

```text
-full64
-sverilog
-ntb_opts uvm-1.2
+define+SVT_UVM_TECHNOLOGY
+define+UVM_PACKER_MAX_BYTES=1500000
+define+UVM_DISABLE_AUTO_ITEM_RECORDING
+define+SVT_APB_MAX_ADDR_WIDTH=32
+define+SVT_APB_MAX_DATA_WIDTH=32
-timescale=1ns/1ps
-kdb
-lca
-debug_access+all
```

SVT VIP 路径不得硬编码在测试代码中。建议通过以下环境变量或 manifest 提供：

```text
SVT_VIP_INCDIR
SVT_VIP_SRCDIR
VERDI_HOME
VCS
VLOGAN
```

缺少路径时应输出环境诊断并失败，不得退化为不等价的 mock。

### 13.4 VIP 编译顺序

编译顺序以 xring `vlog_tb` 为准；axi_test 的单命令 Makefile 只用于理解其源码
依赖，不直接复制为最终构建入口。编译顺序至少保证：

1. `svt_apb_if.svi`
2. `svt_apb.uvm.pkg`
3. `svt_axi_if.svi`
4. `svt_axi.uvm.pkg`
5. fixture interface
6. env package
7. sequence package
8. test package
9. top/HVP

VIP package 必须在引用 `svt_apb_uvm_pkg`、`svt_axi_uvm_pkg` 的 env/test package
之前编译。

### 13.5 仿真和 FSDB

仿真选项参考 xring。AXI 环境代码中已有 `$fsdbDumpfile`、`$fsdbDumpvars`、
`$fsdbDumpSVA` 和 `$fsdbDumpMDA` 的直接 dump 方式，实现时可保留其需要的
MDA/SVA dump 能力，但最终文件名、run directory 和启动选项由统一 Makefile
控制，避免顶层代码和命令行同时配置不同 FSDB 文件。

基础运行选项：

```text
+UVM_TESTNAME=<test>
+UVM_VERBOSITY=UVM_MEDIUM
+fsdb+force
+fsdb+autoflush
+fsdbfile+waves.fsdb
-ucli
-do <wave.tcl>
```

fixture manifest 应记录：

- testcase
- seed
- FSDB path
- daidir path
- simulation log
- top instance
- APB/AXI interface path

### 13.6 APB 环境代码基线

APB 环境的目录分层和 UVM 组织方式以 AXI 环境为模板：

- `top` 实例化 `svt_apb_if`、clock/reset、DUT/loopback wrapper 和
  `run_test()`。
- `env` 创建 `svt_apb_system_env`、configuration、virtual sequencer 和最小
  scoreboard。
- `test` 读取 plusargs，启动 master stimulus 和 slave response。
- `sequence` 分离 master transaction 生成与 slave response/wait-state/error
  控制。

APB 类型和接线细节参考 xring：

- `svt_apb_if` 作为 APB interface。
- `svt_apb_system_env` 作为 UVM system env。
- `svt_apb_system_configuration` 设置：
  - master/slave 数量
  - address/data width
  - active/passive
- `uvm_config_db` 注入 virtual `svt_apb_if`。
- sequence 继承 `svt_apb_master_base_sequence`。
- transaction 使用 `svt_apb_master_transaction`。

APB slave 侧需要建立真正可控制的 response 模型，至少能够按 testcase 设置：

- 固定或随机 PREADY delay。
- 指定地址返回 PSLVERR。
- read data memory/register model。
- reset 中止当前 transfer。

如果当前安装版本提供合适的 `svt_apb_slave_base_sequence`、slave transaction
或内建 memory sequence，优先使用官方基类；具体类名和 member 必须通过本地
SVT reference 或已安装源码确认，不在实现时凭经验猜测。

连接方向参考 `<xring-root>/dv/tb/xring_top_if_connect.sv`：

- VIP 驱动 DUT 的 `paddr/psel/penable/pwrite/pwdata/pstrb/pprot`。
- DUT 返回 `prdata/pready/pslverr`。

APB fixture 至少包含：

- 基础写。
- 基础读。
- wait state。
- back-to-back transfer。
- slave error。
- reset 中断。
- 窗口截断。

验证：

- transaction 数量。
- direction。
- address/data。
- setup/access time。
- wait cycles。
- error。
- cursor begin/next/end。
- `apb.transfer_window` 的窗口边界。

### 13.7 AXI 环境代码基线

AXI 环境代码首先参考 `<axi-test-root>/test/`，该工程已经实现：

- `svt_axi_if` top-level interface。
- 一个 master agent 和一个 slave agent。
- master/slave interface channel loopback wrapper。
- `svt_axi_system_env` 和 `svt_axi_system_configuration`。
- master/slave monitor 到 scoreboard 的 analysis 连接。
- virtual sequencer 保存两个 VIP sequencer handle。
- multi-ID、read/write 并发和 per-ID outstanding 控制。
- reactive slave sequence。
- slave memory 初始化和 read/write 数据处理。
- BVALID/RVALID、address ready 和 WREADY 可控延迟。
- transaction 完成计数和仿真 watchdog。
- FSDB 全量、SVA 和 MDA dump。

应复用的环境模式：

- `axi_tb_env` 在 build phase 创建 configuration，并在创建
  `svt_axi_system_env` 前写入 config_db。
- configuration 设置 master/slave 数量后调用 `create_sub_cfgs(1, 1)`。
- master/slave 均明确配置 AXI4、data width、address width、ID width 和
  `num_outstanding_xact`。
- slave 配置有效 address range。
- connect phase 获取 master/slave sequencer，并连接 monitor analysis port。
- master sequence 继承 `svt_axi_master_base_sequence`。
- slave reactive sequence 继承 `svt_axi_slave_base_sequence`。
- slave sequence 从 `response_request_port` 读取请求，设置 cfg，产生 B/R
  response，并使用内建 memory helper 处理读写数据。

xring 仍作为 DUT 为 AXI master、VIP slave 响应模式的补充参考：

- `svt_axi_if` 作为 AXI interface。
- `svt_axi_system_env` 作为 UVM system env。
- DUT 为 AXI master 时，VIP slave 负责响应。
- `svt_axi_system_configuration` 配置：
  - AXI4
  - data width
  - address width
  - ID width
  - address range
  - active slave
- 使用 `svt_axi_slave_memory_sequence` 或其轻量派生类提供 memory-backed
  response。
- 需要时通过 `svt_axi_slave_agent.write_byte/read_byte` 预装或检查 memory。

首版 AXI fixture 不直接依赖 `<legacy-axi-vip-root>/sim_run` 中已经生成的
FSDB。应把必要环境代码提取到 xdebug synthetic testdata，重新编译和仿真生成
可重复的 FSDB/daidir。原工程可以作为对照环境：

- 同一组 seed/参数先在原环境运行。
- 提取后的 fixture 应产生等价的 transaction 数量、ID 集、outstanding 峰值和
  delay 分布。
- xdebug 在两份波形上的 normalized transaction 结果应满足相同 invariant。

连接方向参考 `<xring-root>/dv/tb/xring_top_if_connect.sv`：

- DUT 请求进入 VIP slave interface：
  - AR
  - AW
  - W
  - RREADY
  - BREADY
- VIP 返回 DUT：
  - ARREADY
  - R
  - AWREADY
  - WREADY
  - B

AXI fixture 至少包含：

- 单 ID 读写。
- 多 ID。
- 多 outstanding。
- response 乱序。
- AW/W 解耦。
- burst 和 last。
- R/B stall。
- incomplete transaction。
- 波形窗口截断。
- latency outlier。

验证：

- `axi.query`
- `axi.analysis`
- `axi.request_response_pair`
- `axi.outstanding_timeline`
- `axi.channel_stall`
- `axi.latency_outlier`

断言应覆盖 ID pairing、方向、地址、burst、response、latency、outstanding 和
incomplete reason。

### 13.8 AMBA VIP API 学习和网络搜索边界

实现环境代码时按以下证据优先级工作：

1. `<axi-test-root>/test/` 中已经运行过的环境代码。
2. xring 中已经运行过的 APB/AXI 环境代码。
3. 本机已安装的 SVT VIP SystemVerilog 源码和 example。
4. 本机 Synopsys SVT HTML class reference，可直接读取或可选使用 `svtref`。
5. 网络上的 Synopsys 官方文档或官方公开示例。

只有前四项无法确认以下问题时才进行网络搜索：

- environment/configuration 的标准创建顺序。
- master/slave agent active/passive 配置。
- reactive slave sequence 的 request/response API。
- memory model 的初始化和读写 API。
- APB wait-state/PSLVERR response 的推荐方式。
- AXI response delay、outstanding 和 ID 行为配置。

网络搜索只影响环境代码设计。以下内容不得因网络示例而改变：

- VCS 分阶段编译流程。
- xring 已使用的关键 define/include。
- `-kdb`、`-debug_access+all`、timescale 等 elaboration 需求。
- run directory、FSDB 生成和 artifact 规则。

任何通过网络确认的 API 都必须再与本机安装版本的 class reference 或源码交叉
核对，避免版本不兼容。

`svtref` 的状态不纳入 pytest prerequisite、环境 doctor、CI gate 或 fixture
manifest。测试基础设施不得为了调用 `svtref` 而引入运行时依赖；它只服务于人工
或 agent 在编写环境代码时的资料检索。

### 13.9 环境代码组织

建议 APB/AXI fixture 保留以下层次：

```text
apb_vip/ or axi_vip/
  Makefile
  cfg/
    wave.tcl
  rtl/
  tb/
    top.sv
    bus_if_connect.sv
  env/
    env_pkg.sv
    env.sv
  seq/
    seq_pkg.sv
    stimulus_seq.sv
    response_seq.sv
  test/
    test_pkg.sv
    testcases.sv
  manifest.yaml
```

首版允许 APB 和 AXI 分开，以减少编译时间和问题耦合。

## 14. Realdata 测试

### 14.1 Manifest

真实路径不得硬编码在 Python 测试中。

建议格式：

```yaml
name: project_case
fsdb: ${PROJECT_FSDB}
daidir: ${PROJECT_DAIDIR}
top: top_instance
tags: [smoke, regression]
timeout_sec: 600

signals:
  clock: top.clk
  reset:
    signal: top.rst_n
    polarity: active_low
  probes: []

interfaces:
  apb: {}
  axi: {}

queries:
  - action: value.at
    args: {}
    expect:
      ok: true
      required_paths: []
      non_empty: []
```

manifest 可描述：

- case 名。
- FSDB。
- daidir。
- top。
- signal/interface。
- action/request。
- invariant。
- timeout。
- smoke/regression/nightly。

### 14.2 Realdata 验证目标

- 大 FSDB 和大 daidir 不崩溃。
- 真实 hierarchy、generate、interface、modport 可解析。
- 真实 APB/AXI transaction 可查询。
- active trace 能返回候选和明确状态。
- X/Z/reset/截断窗口不 silent fail。
- response 非空。
- error code 可解释。
- timeout 后资源清理。

realdata 不做完整 JSON golden，使用 invariant：

- 关键字段存在。
- `ok` 和 status 符合预期。
- result 非空。
- 关键 signal/path/candidate/transaction 存在。
- 数量、时间、latency 在合理范围。
- `meta.truncated` 与返回数量一致。

## 15. Session 和 stdio-loop

### 15.1 stdio-loop 合同

覆盖：

- ready envelope。
- request ID 回传。
- 空行。
- malformed JSON line。
- JSON output。
- xout output。
- `stdio.quit`。
- 多 request。
- out-of-order ID。
- ready 前 banner。
- ready 后 stdout pollution。
- stderr 大量输出。
- child exit。
- timeout。

### 15.2 Session 生命周期矩阵

资源类型：

- FSDB-only。
- daidir-only。
- combined。

状态操作：

- open。
- duplicate open。
- reuse。
- reopen。
- ensure。
- list。
- doctor。
- close。
- kill。
- gc。
- stale registry。
- engine crash。

每个测试检查：

- alias 和 native session ID。
- registry 内容。
- process alive/dead。
- socket/file transport 状态。
- cleanup 后无残留。

### 15.3 Batch

覆盖：

- `continue_on_error`
- `stop_on_error`
- mixed success/failure
- nested target
- session crash during batch
- timeout
- result count 和 failed count

## 16. MCP 测试

### 16.1 必测完整链路

```text
MCP client
  -> xverif-mcp FastMCP server
  -> XverifDebugAdapter
  -> McpSessionManager
  -> launcher
  -> xdebug --stdio-loop
  -> xdebug-engine
  -> action
  -> MCP response
```

不能只验证 server 启动或 tools/list。

### 16.2 Direct

direct 是强制链路，覆盖：

- tools/list。
- action/schema discovery。
- FSDB-only open/query/close。
- daidir-only open/query/close。
- combined open/query/close。
- waveform/design/active trace。
- batch。
- default session/use。
- 多 session。
- 同 session 串行化。
- 不同 session 并行。
- ordinary business error 保持 session。
- crash/timeout 返回 `SESSION_LOST`。
- 显式 reopen。
- CLI/MCP normalized response 一致。

### 16.3 Fake LSF

fake LSF 是强制链路，覆盖：

- pending delay。
- ready 前 stdout banner。
- stderr lines。
- ready 前退出。
- ready 后退出。
- child crash。
- request timeout。
- malformed stdout。
- job ID 解析。
- terminate。
- bkill by ID/name。
- session close cleanup。

fake LSF 不替代真实 xdebug。至少一组 fake LSF 测试应启动真实
`xdebug --stdio-loop`，只模拟 bsub 控制面。

### 16.4 Real LSF

real LSF 为可选扩展，不是首版或日常门禁。

启用条件：

- 提供稳定 queue/resource。
- 登录节点和执行节点均可访问 xdebug、FSDB、daidir。
- 有可控的最长排队和运行时间。
- 有权限查询和清理 job。

可选测试：

- real `bsub -I` open/query/close。
- FSDB、daidir、combined session。
- 多 job。
- queue delay。
- timeout。
- server 异常退出后的 job cleanup。

建议 marker：

```text
mcp_real_lsf
optional_lsf
nightly
```

未配置 real LSF 时应报告未选择该测试集，而不是影响必测集合结果。

### 16.5 MCP 判定修正

禁止使用“返回 dict 即通过”。

- 期望成功：`response["ok"] is True`。
- 期望失败：匹配指定 error code。
- JSON response 通过 schema。
- xout 有合法 header。
- envelope 有 request ID 和 payload format。
- session state 与 cleanup 结果符合预期。

## 17. Golden 和 invariant

### 17.1 Golden

适用于：

- CLI error contract。
- schema/example。
- xout header/summary。
- 小 value/event/list。
- 小 APB/AXI transaction。
- 小 design graph。
- active trace 确定性 fixture。
- CLI/MCP normalize 后结果。

normalize 时移除：

- PID。
- elapsed time。
- 临时路径。
- session hash。
- socket path。
- timestamp。
- LSF job ID。

### 17.2 Invariant

适用于：

- realdata。
- 大 trace graph。
- 大 AXI transaction 集。
- 性能结果。
- 工具版本可能影响顺序的 candidate 集。

数组只有在合同明确有序时做 exact diff，否则按稳定 key 排序或集合比较。

## 18. Artifact 保存

每个失败 case 保存：

```text
artifacts/<run-id>/<case>/
  command.json
  env.json
  request.json
  response.raw
  stdout.raw
  stderr.raw
  response.normalized.json
  expected.json
  diff.txt
  manifest.yaml
  summary.json
```

编译/仿真 fixture 额外保存：

- compile command。
- compile log。
- elab log。
- simulation command。
- simulation log。
- seed。
- FSDB path/size/time range。
- daidir path。

active trace 额外保存：

- trace tree。
- candidate drivers。
- stop reasons。
- signal values。
- requested/active time。
- waveform bounds。

APB/AXI 额外保存：

- bus config。
- VIP config 摘要。
- transactions。
- pairing report。
- outstanding report。
- stall/latency report。

MCP 额外保存：

- MCP request/response。
- stdio-loop transcript。
- session state。
- launcher command/log。
- child stdout/stderr。
- fake/real LSF job ID/name。

## 19. 执行入口

### 19.1 pytest markers

```text
unit
contract
synthetic
design
waveform
combined
active_trace
apb
axi
vip
session
stdio_loop
mcp
mcp_direct
mcp_fake_lsf
mcp_real_lsf
optional_lsf
realdata
smoke
regression
nightly
slow
```

### 19.2 Makefile 入口

```text
test-fast
test-contract
test-synthetic
test-vip
test-active-trace
test-session
test-mcp-direct
test-mcp-fake-lsf
test-realdata-smoke
test-regression
test-nightly
test-mcp-real-lsf
```

其中：

- `test-fast`：unit + contract。
- `test-regression`：不包含 real LSF。
- `test-nightly`：realdata；real LSF 根据显式配置决定是否加入。
- `test-mcp-real-lsf`：单独显式运行。

Python 解释器必须可配置，不能隐式依赖系统 `python3`。

## 20. 落地顺序

1. 建立 pytest 骨架、统一 runner 和 artifact manager。
2. 接入 CLI/schema/example contract。
3. 从 runtime 动态建立 action coverage。
4. 将现有 waveform/design/combined 脚本接入 pytest。
5. 建立 session/stdio-loop 真实 binary 测试。
6. 建立 MCP direct 真实链路。
7. 建立 fake LSF 完整链路。
8. 建立基础 synthetic fixture 和 build cache。
9. 从 `<axi-test-root>/test/` 提取并收敛 AXI SVT VIP 真实波形 fixture，编译
   选项按 xring Makefile 统一。
10. 以 AXI fixture 的环境分层为模板，结合 xring APB 代码建立 APB SVT VIP
    真实波形 fixture。
11. 补 active trace 高风险语义 case。
12. 建立 realdata manifest。
13. 建立 nightly 性能和稳定性趋势。
14. 条件成熟后再接入可选 real LSF。

## 21. 分阶段提交与远端同步

测试环境按上述落地顺序分阶段实现。每个阶段应形成独立、可审查、可回退的
commit，不把 runner、fixture、MCP、realdata 和文档等多个大主题堆入同一提交。

### 21.1 提交原则

- 每个阶段开始前确认 worktree，避免带入用户无关修改。
- 每个 commit 只包含该阶段必要的代码、测试和文档。
- commit message 使用中文，并详细说明：
  - 本阶段新增或修复的内容。
  - 行为合同和测试范围。
  - 使用的 fixture/资源。
  - 已执行的验证命令和结果。
  - 已知限制及后续阶段。
- golden 更新必须与产生该变化的代码在同一 commit，不能单独用无解释的
  “更新 golden”提交掩盖行为变化。
- synthetic fixture 的源码、manifest、runner 接入和最小验证应在同一阶段闭环。
- 不提交生成的 FSDB、daidir、临时 HOME、session registry、编译产物和失败
  artifact，除非仓库明确选择了小型受控 fixture 数据。

### 21.2 阶段门禁

提交前至少运行该阶段的 focused tests，并运行所有受影响的较低层门禁。例如：

- runner/contract 阶段：
  - unit
  - schema
  - contract
- synthetic design/waveform 阶段：
  - contract
  - 对应 synthetic marker
- session/MCP 阶段：
  - session
  - stdio-loop
  - MCP direct 或 fake LSF
- APB/AXI VIP 阶段：
  - fixture compile/elab/simulation
  - FSDB/daidir 存在性和完整性检查
  - 对应 xdebug APB/AXI assertions
- realdata 阶段：
  - manifest validation
  - selected smoke cases

测试失败时不得为了保持提交节奏而提交已知红灯；应先修复，或者把未完成部分留在
后续 commit，并确保当前 commit 自身完整。

### 21.3 推送远端

每个阶段的 commit 和阶段门禁完成后，应及时推送到当前跟踪的远端分支，避免所有
工作只停留在本地直到任务末尾。

推送前检查：

- `git status` 只包含预期状态。
- 当前分支和 upstream 正确。
- 本阶段 commit 已存在且 message 完整。
- focused tests 已通过。
- 未包含本地路径、敏感配置、大型生成物或 scratch 文件。

推送后记录：

- commit hash。
- 远端分支。
- 本阶段测试结果。
- 下一阶段起点。

如果远端拒绝推送、upstream 发生变化或需要 rebase，应停止继续堆叠新阶段，
先保守同步远端并重新运行受影响门禁。不得使用破坏性 reset 或强制推送覆盖他人
提交，除非用户明确授权。

建议阶段边界：

1. pytest runner、normalize 和 artifact。
2. CLI/schema/contract。
3. 现有 design/waveform/combined 接入。
4. session/stdio-loop。
5. MCP direct。
6. fake LSF。
7. 基础 synthetic。
8. AXI VIP 真实波形 fixture。
9. APB VIP 真实波形 fixture。
10. active trace 高风险 case。
11. realdata manifest 和 smoke。
12. nightly 与可选 real LSF。

## 22. 首版最小可交付范围

首版必须包含：

- pytest 基础设施。
- 统一 CLI/stdio-loop runner。
- artifact 保存。
- CLI/JSON/xout contract。
- runtime action/schema/example 一致性。
- 现有 waveform/design/combined 回归接入。
- FSDB-only、daidir-only、combined session 生命周期。
- MCP direct 完整链路。
- fake LSF 完整链路。
- 一个 realdata manifest。
- active trace 的 MUX、reset/enable、wave truncation case。
- APB 基础 VIP fixture。
- AXI 基础 VIP fixture，包括至少两个 ID 和 outstanding pairing。

首版不强制：

- real LSF。
- 大规模性能硬阈值。
- 所有 experimental action 的完整 golden。

## 23. 风险与人工确认项

### 23.1 已确认风险

- action 合同多源维护。
- MCP L2/L3 假阳性。
- session 路径文档漂移。
- MCP docstring action/default 漂移。
- active-trace-chain 文档和目录漂移。
- 当前 AXI 回归依赖仓库外固定环境，尚未把必要环境代码收敛到可重复 fixture。
- realdata 路径硬编码。
- direct socket timeout 缺少端到端验证。
- cleanup、normalize 和 artifact 未统一。
- APB/AXI 简化 testbench 可能无法产生真实 VIP 等价波形。
- axi_test 环境代码和 xring 编译选项来自不同工程，提取时存在版本、路径、define
  和 package 编译顺序不一致风险。

### 23.2 实现前确认

- SVT VIP 安装路径如何通过统一环境配置提供。
- 从 axi_test 提取 AXI 环境代码时，哪些 scoreboard/XML/debug 功能属于首版
  必需，哪些可以裁剪。
- APB reactive slave response 应采用当前安装版本的哪组官方 sequence/transaction
  API；实现时必须通过本地 reference 或源码确认。
- 首批 realdata manifest 的 FSDB、daidir、top 和关键信号。
- nightly 可接受时长。
- golden 更新是否要求人工审批。
- real LSF 的 queue/resource 配置何时具备；这不阻塞其他测试落地。

## 24. 验收标准

测试环境首版完成时应满足：

- 一个 pytest 命令可运行 fast/contract 集。
- 一个 pytest/Makefile 命令可构建并运行 synthetic FSDB/daidir。
- APB/AXI fixture 使用经核对的 SVT VIP 编译和环境模式。
- direct MCP 能完成 open/query/batch/close。
- fake LSF 能完成正常链路和故障注入。
- realdata 通过 manifest 选择，不在代码中硬编码路径。
- 所有失败测试保存完整复现 artifact。
- 不存在 `ok:false` 被计为通过。
- cleanup 后无 xdebug-engine、socket、registry 或 fake LSF 残留。
- real LSF 未启用不影响必测集合通过。
