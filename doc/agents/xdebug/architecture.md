# xdebug 架构分层

xdebug 是统一 JSON request 入口。它把设计数据库能力、波形数据库能力和 combined active-trace 能力整合为 action-based API，并用 session、schema、log、transport 和测试体系约束 public contract。

## 顶层构建形态

`xdebug/Makefile` 构建两个主要产物：

- `xdebug/xdebug`：frontend CLI/API 进程。
- `xdebug/libexec/xdebug-engine`：内部 unified engine 进程，包含 design、waveform、combined service handler。

frontend 不直接承载 NPI 重逻辑；NPI/FSDB/engine 能力集中在内部 engine 和相关 service 中。`src/core/` 中的通用组件同时被 frontend 和 engine 复用。

## CLI/API 层

主要路径：

- `src/main.cpp`
- `src/api/request_parser.*`
- `src/api/request_envelope.*`
- `src/api/request_validator.*`
- `src/api/dispatcher.*`
- `src/api/response.*`
- `src/api/response_builder.*`
- `src/api/text_response_builder.*`
- `src/api/xout_renderer.*`
- `src/api/stdio_loop.*`

职责：

- 接收 stdin、文件或 CLI JSON request。
- 解析 `api_version/request_id/action/target/args/limits/output` envelope。
- 做 action-specific schema 校验和资源解析。
- 分发本地 action、session action、engine_forward action 或 combined action。
- 输出 JSON 或 XOUT，保证 stdout 可被机器解析，诊断信息进入 log/stderr。

修改要求：

- 不要在 CLI 层手写 action-specific 参数规则；参数合同应来自 schema。
- 不要让日志污染 JSON stdout。
- 新增公共输出字段时同时考虑 JSON 和 XOUT。
- `session.open.target.run_manifest` 是可选的 provenance gate：提供时必须在 engine
  启动前完成 published state、canonical path、size 和 SHA-256 校验；不得通过自动
  reopen、固定 sleep 或其他 transport 绕过失败。

## Schema 与 Validator 层

主要路径：

- `specs/actions/actions.yaml`
- `schemas/v1/actions/*.request.schema.json`
- `schemas/v1/actions/*.response.schema.json`
- `examples/requests/*.json`
- `examples/responses/*.json`
- `src/core/schema/runtime_schema_validator.*`
- `src/api/request_validator.*`
- `tools/validate_schema.py`
- `tools/validate_examples.py`
- `tools/sync_runtime_request_schemas.py`
- `tools/sync_action_schema_hints.py`
- `tools/sync_action_metadata.py`
- `tools/audit_action_schema_coverage.py`
- `tools/check_action_contract.py`

职责：

- `actions.yaml` 描述 action inventory、category、requires、handler_kind、schema/example
  路径、required args，以及双语描述、purposes、适用/禁用范围和推荐替代；编译期
  action metadata 由此生成。
- action-specific schema 是 public request/response contract。
- runtime validator 在执行前拦截非法 envelope 和非法 action 参数。
- examples 是可执行合同样例，必须被 schema 校验。

修改要求：

- schema 是 source of truth；docs、skill、runtime 不能声明 schema 不接受的字段。
- `required`、`anyOf`、enum、`additionalProperties:false` 必须和 runtime 行为一致。
- 修改 spec 后运行同步脚本和 schema/contract 校验。

## Session Manager 层

主要路径：

- `src/session/session_catalog.*`
- `src/engine/session/session_registry.*`
- `src/engine/session/session_manager.*`
- `src/engine/session/session_transport.*`
- `src/engine/session/client.*`
- `src/core/session/session_types.*`

职责：

- 管理 `session.open/list/close/kill/gc/doctor`。
- 绑定 session name/session_id 与 daidir、fsdb、transport、engine 资源。
- 管理 frontend 到 backend session 的映射和生命周期。
- 在 engine crash、transport failure、timeout 时给出稳定错误码和日志证据。

公开合同：

- 原生 request 使用 `target.session_id` 选择已打开 session。
- MCP debug query 使用 `session_id` 参数。
- session 失效后不能继续复用，需要重新 open。

## Backend Engine Adapter 层

主要路径：

- `src/backend/engine_adapter.*`
- `src/core/process/process_runner.*`
- `src/runtime/work_dir.*`
- `src/engine/main.cpp`
- `src/engine/server.*`
- `src/engine/engine_query.*`

职责：

- frontend 按需启动或连接 `xdebug-engine`。
- 管理 engine 子进程、工作目录、transport endpoint、ready/ping/query/quit。
- 将 action request 转发给 engine service，并把 response 返回 frontend。

修改要求：

- 子进程生命周期、timeout、stderr/stdout 隔离是 public behavior 的一部分。
- transport 失败必须可诊断，不能吞掉 endpoint、phase、error code。

## Engine Service 层

主要路径：

- `src/engine/service/engine_action_registry.*`
- `src/engine/service/engine_action_handler.*`
- `src/engine/service/actions/**`
- `src/engine/service/design_postprocess.*`
- `src/engine/service/trace_bfs_engine.*`

职责：

- engine 内部 action registry 注册 design、waveform、protocol、stream、combined handlers。
- action handler 读取已校验 args，调用 design/waveform/combined helper。
- 返回稳定 JSON summary/data/errors。

修改要求：

### AXI canonical transaction reconstruction

- `src/waveform/axi/axi_transaction_tracker.*` 是 AXI AW/W/B/AR/R 配对的唯一状态机；
  handler 和 exporter 不得复制配对逻辑。
- AXI4 W burst 按 AW acceptance order 绑定，允许整个 W burst 在 AW 前完成；BID 绑定
  同 ID 最老的 data-complete write，RID 绑定同 ID 最老的 AR。
- `AxiAnalyzer` 每个 session/config 只做一次完整 FSDB clock scan，query、analysis、
  pair、timeline、outlier、cursor 和 export 复用 `AxiResult`。
- `AxiResult` 由 engine-owned `AnalysisRepository` 按 FSDB identity 和规范化 AXI
  语义持有；address、ID 与各 channel handshake index 独立按需构建、记账和淘汰，
  不改变 tracker 的 canonical transaction 与排序。
- AXI cursor 只保存 key、generation、direction 和 position，不 pin canonical entry；
  soft LRU 后同 key 重建时恢复 position，显式 config/session 失效则清除。
- 新增 AXI action 或输出时必须保留 `full_scan_count=1` 回归，并用独立 pin/VIP oracle
  验证，不能以另一个 xdebug action 作为期望值。

- 新 action 应进入对应 `actions/<domain>/` 子目录，并在对应 `register_*_handlers.cpp` 注册。
- handler 不应重新发明 schema 校验；只做业务语义检查。

### APB canonical transaction reconstruction

- `ApbAnalyzer` 按规范化 APB 语义和 FSDB identity 将 completed transfer 发布到
  engine-owned `AnalysisRepository`；query、statistics、transfer_window 和 cursor
  复用同一份 canonical result，不重复扫描 FSDB。
- scan 时一次性冻结既有十六进制地址解析结果，保留原始 `addr` 字符串；按地址查询
  使用独立 lazy `AddressIndex`，index 只保存 canonical position，不复制 transaction。
- APB cursor 与 AXI cursor 一样只保存 key、generation、direction 和 position；soft
  LRU 后同 key 重建时恢复位置，显式 config/session 失效则清除。
- APB canonical 与 AddressIndex 的 build working set 都受 hard limit 约束；失败返回统一
  结构化 cache error，不缩小扫描范围、不切换 backend。

## Design Engine 能力层

主要路径：

- `src/design/service/action_support.*`
- `src/design/service/trace_actions.*`
- `src/design/ast/`
- `src/design/control_dep/`
- `src/design/signal/`
- `src/design/trace/`
- `src/design/common/`

职责：

- 设计数据库解析、signal resolve/canonicalize、driver/load/source/context、AST/control dependency/trace 分析。
- 面向 `trace.*`、`signal.*`、`source.*`、`expr.*` 等 design action 提供底层能力。

修改要求：

- 保持 signal path、file:line、driver evidence 可追踪。
- 不要把波形时间语义混入纯 design helper。

## Waveform Engine 能力层

主要路径：

- `src/waveform/server/service/`
- `src/waveform/server/fsdb_value_reader.*`
- `src/waveform/common/`
- `src/waveform/value/`
- `src/waveform/event/`
- `src/waveform/list/`
- `src/waveform/cursor/`
- `src/waveform/apb/`
- `src/waveform/axi/`
- `src/waveform/stream/`
- `src/waveform/export/`

职责：

- FSDB value read、time parsing、clock sampling、event expression、signal statistics、changes、window verify。
- 管理 list/cursor/event/APB/AXI/stream 配置。
- 导出 waveform、AXI、stream、RC 等外部材料。

修改要求：

- clock/time/sample_point 语义必须集中复用统一 helper。
- value/logic 四态处理必须复用 `LogicValue` 相关组件。
- signal value 显示使用 `args.value_format`（`hex`、`bin`、`dec`）；decimal 遇 X/Z
  必须明确给出 binary effective format，不能丢失逐位信息。
- raw signal 的实际位宽只从 NPI range size 取得；派生表达式仅在宽度可证明时定宽，
  不得从 FSDB 值文本长度或前导零推断。所有 value-bearing action 在 summary 发布
  `value_width_complete` 与 `width_diagnostics`。
- `edge:"negedge"` 可以携带 `sample_point` 以统一请求形状，但它不改变既有 negedge
  current-value 采样；响应必须给出 requested/effective sampling。
- 大 payload 默认 compact；只使用 schema 声明的 action-specific 输出参数、`line_limit` 或 export action 返回细节。AXI transaction 的逐 beat payload 统一由 `args.output.include_data` 控制。

### AnalysisRepository 与测量边界

- `src/waveform/cache/analysis_probe.*` 是 test-only 内部 JSONL probe，仅在 engine
  启动时显式设置 `XDEBUG_TEST_ANALYSIS_PROBE_PATH` 才启用；不注册 public action，
  不进入 schema、MCP、JSON response 或 XOUT。
- `src/waveform/cache/analysis_size_estimator.*` 对当前 APB/AXI canonical result 和
  stream analysis 的动态容器容量做确定性估算。估算不是 allocator/RSS 的替代；
  safety factor 与预算默认值以 nightly benchmark 的 RSS 对照冻结。
- `src/waveform/cache/analysis_repository.*` 由每个 engine 唯一持有，统一管理带
  FSDB identity、版本化语义 fingerprint 和 scope/range 的 key、typed ensure 入口、
  canonical/index 独立对象、building/ready、generation cursor 及跨协议确定性 LRU。
- soft/hard 分别由 `XDEBUG_ANALYSIS_CACHE_MAX_BYTES`（默认 1 GiB，0 关闭主动 soft
  LRU）和 `XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES`（默认 2 GiB，必须大于 0）控制；
  engine 启动时严格解析一次，非法值直接启动失败，不使用默认值兜底。
- 预算按 estimator bytes 乘冻结 safety factor 2.0 计费；index 先于 canonical 淘汰，
  单一 oversize entry 或 owner+index 可越过 soft 但不能越过 hard。失败构建不发布对象。
- Phase 2 已迁移 AXI canonical、address/ID/handshake lazy index 与 cursor；Phase 3
  已迁移 APB canonical、AddressIndex 与 cursor。Phase 4A 已把 stream 单次分析拆为
  `StreamBaseAnalysis` 与请求级 `StreamQueryView`：所有 sample 只保留时间、控制、
  stall 和 X/Z 统计元数据，完整 field column 只与 transfer ordinal 对齐；packet 只保存
  transfer 引用、边界、channel 和 stable mismatch。Phase 4B 已把 `stream.query`、
  `stream.export` 和动态 `stream.validate` 接入 repository：`cache_scope` 默认 `full`，
  显式 `range` 只构建规范化请求窗口；静态 validate 不创建 base。
- 同语义 full 已存在时，range 请求直接从 full 构建 QueryView，不新增 range entry；
  full 构建成功后事务性清除同语义 ranges，构建或 hard-limit 失败则保留旧 ranges。
  不同 range 不合并、不自动提升为 full，达到 hard limit 时返回结构化错误。
- `StreamQueryView` 从 base 重建窗口局部 cycle、packet index、stall 边界、partial 标记、
  filter evidence 与完整 summary；base sample/transfer ID 不进入 public response。
  query-specific projection 只限制 packet body materialize，不改变完整计数、首末 evidence
  或 truncation 语义。所有 public APB/AXI/stream response 与排序保持不变，hard limit
  通过统一 handler error 返回，不切换 scope/backend。

## Combined Active Trace 层

主要路径：

- `src/combined/active_trace_service.*`
- `src/combined/active_trace_chain.*`
- `src/combined/active_trace_common.h`
- `src/engine/service/actions/combined/`

职责：

- 同时使用 daidir 和 fsdb，把波形时间点的现象连接到当前生效 RTL driver。
- 支持 active driver、active driver chain 和 `trace.x` 等 combined action。

修改要求：

- combined action 必须保留 design evidence 和 waveform time evidence。
- 对未解析、control-only、zero evidence 等状态要稳定表达，不要假装 resolved。
- active driver chain 只在 `npiRhs` 明确给出直接 signal 时继续追踪。多个 active
  assignments 或多个 RHS sources 必须停止为 ambiguous，并按 statement 返回 RHS
  在精确 `active_time` 严格之前和该时刻最终值；该证据不得参与根因猜测。
- active chain 不接受 `clk_period`，也不得重新引入半周期窗口、邻近时钟沿或其它
  waveform heuristic/fallback。RHS evidence 截断必须通过 `limits.max_trace_signals`
  的完整性字段显式表达。
- active chain 因 `max_depth` 停止时必须点读尚未处理的下一信号，并通过
  `depth_frontiers` 与 `suggested_next_actions` 发布可直接续查的 signal/time/value。
- `trace.x` 必须先确认查询点任一 bit 为 X，再按 DFS 同等处理含 X 的 RHS/control，
  穿过 port/interface，并为每一跳重新定位连续 X 区间起点；Z 不等同于 X。
  `limits.max_chains` 默认 8，超额分支保留 pending 现场。控制 X、动态 select 等无法
  严格证明的原因只能标为 `best_effort`；所有 limit 必须明确保留 chain 当前状态。

## Runtime/Work Dir 层

主要路径：

- `src/runtime/work_dir.*`
- `src/core/common/env_config.*`
- `src/core/common/tool_config.*`
- `src/core/common/path_utils.*`

职责：

- 统一工作目录、session/log 路径、环境变量读取和路径处理。
- 避免 action handler 自行拼接不一致的临时路径。

修改要求：

- 新增环境变量时必须写清默认值、优先级和日志可见性。
- 不要把本机绝对路径泄漏到用户可见文档，除非是执行证据必需。
