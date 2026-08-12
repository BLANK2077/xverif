# xdebug 统一组件

本页列出 xdebug 中应该优先复用的统一组件。新增功能前先确认是否已有组件能覆盖，不要在 action handler 内临时重写一套。

## Request Envelope

路径：

- `src/api/request_envelope.*`
- `src/api/request_parser.*`
- `src/api/request_validator.*`

职责：

- 表达统一请求形状。
- 解析 JSON stdin/file。
- 提供 action、target、args、limits、output 的稳定访问入口。

要求：

- handler 不直接解析原始 stdin。
- 不要用字符串拼接方式检查 JSON 字段。

## Action Registry

路径：

- `src/api/action_registry.*`
- `src/api/action_registry_init.*`
- `src/api/action_catalog.*`
- `src/engine/service/engine_action_registry.*`

职责：

- 维护 action 名称到 handler 的映射。
- 提供 action catalog、help、contract audit 的运行时事实来源。

要求：

- action 注册必须和 `actions.yaml` 保持一致。
- 删除 action 时同步 schema、examples、docs、MCP、tests。

## Resource Resolver

路径：

- `src/api/resource_resolver.*`

职责：

- 根据 `target.daidir`、`target.fsdb`、`target.session_id` 判断资源类型。
- 为 dispatcher/engine adapter 提供资源上下文。

要求：

- 不要在各 action 中自行判断 daidir/fsdb/session 的优先级。
- public session 选择统一走 `target.session_id`。

## Design Hierarchy Relationship Walker

`scope.list source=design|merged` 的层级发现复用统一 relationship walker，不在 action
handler 内另写平行枚举器。hierarchy 关系沿 instance/internal scope 递归；interface 的
modport/mpport 是侧向关系，计入 visited/object budget，但不增加 hierarchy depth。

响应按 kind 保留分组数组。每个对象必须发布 canonical `path`、`kind`、`sources`、
`queryable` 和 `traceable`；merged 只按 canonical path 合并证据，不能把 design-only 对象
标成 waveform-queryable。summary 使用 `visited_count` 和统一的
`returned_count/response_truncated/truncation_scopes`，不新增同义完整性字段。

## Response Builder 与 XOUT Renderer

路径：

- `src/api/response.*`
- `src/api/response_builder.*`
- `src/api/text_response_builder.*`
- `src/api/xout_renderer.*`
- `src/core/output/`

职责：

- 构建 JSON response。
- 渲染 compact/full/debug XOUT。
- 统一 summary、data、findings、evidence、errors 的输出形状。

要求：

- 新 response 字段必须考虑 JSON 和 XOUT 两种消费者。
- 默认输出 compact，避免返回全量 trace/timeline/source。

## Common Blocks 与 AI Response

路径：

- `src/core/ai/common_blocks.*`
- `src/core/ai/ai_response.*`

职责：

- 复用 AI 可读 summary、evidence、suggested actions、diagnostics 等块。

要求：

- 重复出现的提示、诊断和建议不要散落在多个 handler。
- 用户可见建议必须锚定事实，不输出泛泛建议。

## Runtime Schema Validator

路径：

- `src/core/schema/runtime_schema_validator.*`

职责：

- 运行时加载 action-specific schema 并校验 request。

要求：

- 禁止绕过 validator 接受 public request。
- validator 报错应保留 action、字段路径和原因。

## Logic Value 与 Time Handling

路径：

- `src/waveform/value/logic_value.*`
- `src/waveform/common/time_spec.*`
- `src/waveform/common/clock_sampling.*`
- `src/core/npi/time_contract.*`

职责：

- 统一四态值、位宽、unknown、格式化。
- 统一时间字符串、FSDB time、clock edge、sample point、time range。

要求：

- 不在 action handler 中手写四态比较或时间单位换算。
- clock sampling 行为变化必须配套 tests 和文档。

## AXI Transaction Tracker

路径：

- `src/waveform/axi/axi_transaction_tracker.*`
- `src/waveform/axi/axi_analyzer.*`

职责与要求：

- 在纯采样事件层统一重建 AW/W/B/AR/R transaction、outstanding 和诊断。
- 必须支持 AW-first、same-cycle、W-first、多 W burst 先于 AW、跨 ID B 乱序。
- exporter 和 action 只消费 canonical `AxiResult`；禁止再次扫描 FSDB 或建立第二套
  pending queue。
- tracker 的 working-set estimator 必须覆盖 canonical result、pending AW/AR/W 状态、
  outstanding map 和动态 payload；扫描中按幂次采样更新 repository build 计费。
- address、ID 和 handshake index 只保存 canonical transaction/beat 下标。address+ID
  组合查询先缩小 address bucket，再使用既有 ID 比较，不建立组合缓存。
- handshake index 固定按 `time -> transaction seq -> beat index` 排序；canonical
  transaction 的既有 direction/all 顺序不因 index 建立而改变。

## APB/AXI Statistics Filter

路径：

- `src/engine/service/actions/protocol/protocol_statistics_filter.*`

职责与要求：

- 统一解析 direction、AXI ID 队列和 exact/range/mask 地址过滤，三类条件取 AND。
- 对 transaction address/ID 使用三态匹配；已知 false 优先于 unresolved。
- statistics handler 只遍历 canonical completed transaction，不复制匹配列表、不建立
  per-filter cache，也不重新扫描 FSDB。

## AnalysisRepository、Probe 与 Size Estimator

路径：

- `src/waveform/cache/analysis_probe.*`
- `src/waveform/cache/analysis_repository.*`
- `src/waveform/cache/analysis_size_estimator.*`
- `tests/stream_differential/legacy_stream_oracle.*`（仅 differential test build）

职责与要求：

- engine 只能有一个 repository；AXI/APB analyzer 与三个动态 stream action 已接入同一
  repository。stream analyzer 只负责 full/range base 构建和临时 `StreamQueryView`，
  repository 负责预算、LRU、building/ready 与发布；analyzer 不持有这些全局状态。
- stream `cache_scope` 默认 `full`。range 请求优先复用同语义 full；没有 full 时才缓存
  精确规范化 range。full 成功发布后清除同语义 range entries，失败则保留它们；不同
  range 不合并、不自动提升，静态 validate 不进入 repository。
- key 必须同时保存 SHA-256 摘要和规范化语义做等值确认；config name、description、
  JSON 字段顺序和 config 文件路径不进入语义 fingerprint。
- canonical 发布后不可变；lazy index 独立记账、优先淘汰，canonical 淘汰时释放全部
  index。building 对象只用于单线程重入保护，任何 failure 必须完整回滚。
- generation cursor 不 pin entry；soft LRU 淘汰后同 key 重建并沿原 position 续用，
  config/session invalidation 则清除 cursor。
- probe 只用于 catalog benchmark 和内部差分，必须由
  `XDEBUG_TEST_ANALYSIS_PROBE_PATH` 显式启用；key 只写摘要，不写完整 signal path。
- probe event 使用单调 `access_sequence`，并累计 scanner/hit/miss/evict；新增 cache
  层时复用该组件，不新增 public `cache.status` 或调试 action。
- size estimator 使用容器 capacity 和动态 string/map 内容形成确定性计量；新增
  canonical/index 数据结构时必须同步 estimator 和 unit/benchmark。
- APB scan 期在 canonical transaction 上冻结 `has_numeric_addr/numeric_addr`，既有
  address 字符串仍是 public 输出 source of truth；lazy AddressIndex 只保存 all/write/read
  三个 canonical view 的 position，并与 canonical 分开记账和淘汰。
- hard-limit 判定后续使用冻结的 safety factor；不能用 RSS 瞬时值作为运行时预算
  决策，也不能因 probe 写入失败改变 action 结果。
- `StreamBaseAnalysis` 对每个 sample 只保存 time、reset/flow/boundary、stall reason 和
  control/data X/Z 计数；完整 beat/stable field value 仅保存在 transfer-aligned columns。
  `StreamQueryView` 按请求窗口临时重建 row、stall 和 packet，并按 query kind 只保留所需
  packet body；summary、matched count、首末 evidence 与完整性仍遍历完整窗口。
- legacy oracle 是 stream 列式重构的 test-only 差分 seam，只编入
  `stream-differential-test-dist` 生成的独立 frontend/engine。该 test build 对同一
  FSDB/config/options 始终额外执行冻结的 `analyze_legacy`，逐字段比较 summary、transfer、
  stall、当前 query 所需 packet 与 filter evidence。正式 engine 不包含 legacy analyzer
  符号、不读取 differential 环境变量、不注册 public bypass，也不把 oracle 扫描计入 probe。
- stream 配置保存使用同目录 temp、完整 write、file `fsync`、atomic rename 和
  directory `fsync`；只有成功后才按语义 fingerprint 通知 repository。description-only
  或同语义 replace 复用，写入/rename 失败保留旧文件与旧 cache。

## Transport/File Exchange

路径：

- `src/core/transport/file_exchange.*`
- `src/engine/session/session_transport.*`
- `src/engine/session/client.*`

职责：

- 支持 UDS、TCP、file transport。
- file transport 管理 requests、claims、responses、done、failed、tmp、heartbeat 状态目录。

要求：

- 不让 agent 手工读写 file transport 内部目录。
- transport 切换必须显式，不做静默 fallback。

## Process Runner

路径：

- `src/core/process/process_runner.*`

职责：

- 管理子进程启动、timeout、stdout/stderr 捕获和退出状态。
- executable 含 `/` 时按显式路径执行；不含 `/` 时通过 `PATH` 查找，禁止在调用点硬编码系统工具路径。

要求：

- 所有外部进程调用必须保留错误上下文。
- stdout/stderr 隔离不可破坏 JSON 输出。
- 正常运行的临时目录统一通过 `xdebug_core::temporary_dir()` 定位到 `~/.xdebug/tmp`；测试框架显式设置 `XVERIF_TEST_TMPDIR=<repo>/tmp`，且仓库 `tmp/` 由根目录 `.gitignore` 忽略。

## Session Catalog

路径：

- `src/session/session_catalog.*`
- `src/engine/session/session_registry.*`
- `src/engine/session/session_manager.*`

职责：

- 记录 frontend/backend session 映射和生命周期。

要求：

- session close/kill/gc 必须清理 registry 和 backend 资源。
- SESSION_LOST 后不得继续复用旧 session。
