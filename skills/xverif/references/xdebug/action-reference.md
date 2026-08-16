# Xdebug Action Reference
本文件按当前实现和 `xdebug/specs/actions/actions.yaml` 的公开 action 生成。已标记删除或未注册的 action 不列为可用入口。
## Contract Rules
- `required` 来自运行时 catalog、actions.yaml 和 request schema，contract test 会强制三者一致。
- `also one of` 表示实现除了基础 required 之外还需要满足一组替代参数，例如 inline config 或保存的 name。
- `when ...` 表示条件 required，例如某种导出 kind 才需要输出路径。
- design action 读取 daidir/NPI 设计事实；waveform action 读取 FSDB；combined action 同时使用两者。
- `trace.*` 和 `trace.active_driver*` 可通过 `XDEBUG_COMMON_BLOCKS` 追加 common block 提示；只在返回 payload 的 `file` 精确命中配置时追加 `data.common_blocks`，原有输出不改写。

## Recommended Field Dictionary

- session 标识在原生 xdebug request 中统一写 `target.session_id`；不要把 MCP query 的顶层 `session_id` 写进 CLI envelope。
- `value.at` 使用 `time` 表示单点，使用非空、有序且不重复的 `times` 表示一个或多个点。
- 时间窗口统一写 `time_range.begin` / `time_range.end`。
- 数量上限以 action-specific schema 为准。通用窗口/统计类使用
  `args.line_limit`；APB/AXI 查询类使用 `args.query.line_limit` /
  `args.query.index`；`trace.driver/load` 只使用 top-level
  `limits.max_results`；active-driver 链深度使用 top-level
  `limits.max_depth`。
- stream action 统一写 `stream`，不写 `name`。
- AXI/APB direction 以 action-specific schema 为准；query action 用 `read` / `write`，cursor/analysis 等 action 可按 schema 使用 `all`。
- 导出路径统一写 `args.output.path`；不同 action 可把该 path 解释为文件、目录或文件前缀。
- 参数错误时先读 `invalid_arg`、`expected`、`available_values`、`did_you_mean`、`required_any_of` 和 `correct_example`。这些字段可能来自 schema 层，也可能来自 action handler 层；错误响应不发布 `allowed_values`。action catalog descriptor 的 `allowed_values` 是参数到 enum 的元数据映射，不是错误候选；不要只凭 `message` 猜下一次请求。

## Waveform Action Boundaries

- `signal.anomaly.inspect`：raw waveform smoke scan。用于找 `unknown_xz`、周期内异常短脉冲/毛刺 `glitch`、长时间不变 `stuck`。可传多个信号；对 packed struct / aggregate payload，AI 必须直接传最终 leaf signal path，例如 `top.u.payload.opcode`，不要传 struct aggregate path 后期待 xdebug 自动展开。它不单独证明 valid/ready 协议 bug，`stuck` 命中后还要结合协议上下文解释。
- `event.find` / `event.export`：clock-edge sampled event query。用于按 `clock`、`edge`、`sample_point` 和 alias 表达式查 `valid && !ready`、`opcode >= 8'h10`、`data != 0` 这类采样点条件。默认优先用 `edge:"negedge"`；只有接口规范、monitor 语义或 race/skew 证据要求时才改用 `edge:"posedge"`。使用 posedge 时默认推荐 `sample_point:"before"`，因为数据与 clock edge 同 timestamp 变化时 before/after 语义不同；只有要观察沿后状态才用 `"after"`。`edge:"dual"` 只用于 DDR/双沿采样/不确定边沿 bring-up。packed struct 字段必须作为 direct leaf signal alias 传入，例如 `"opcode": "top.u.payload.opcode"`，不要只依赖 aggregate `payload`。
- `signal.sampled_pulse.inspect`：valid sampling explanation。用于回答“raw valid 脉冲存在，但没有被采样边沿看到”以及 `payloads` 在未采样窗口附近是否变化；payload 风险由 `rules.payload_changed_without_sampled_valid=off|summary|all` 控制，默认 `summary`，避免无界展开。它不是通用 glitch/stuck/XZ 扫描入口。
- `protocol.handshake.inspect`：valid/ready protocol inspection。用于统计 transfer、stall、ready-without-valid、stalled data stability violation；默认启用 `rules.require_valid_hold_until_handshake:true`；`rules.ready_without_valid` 默认 `summary`，可选 `intervals` 或 `all`；适合协议层风险，不替代 raw glitch 检测。
- `value.at`：统一读取单信号或已加载 list/APB/stream/AXI 在一个或多个时间点的值。`signal`、`list`、`apb`、`stream`、`axi` 恰好传一个，`time`、`times` 恰好传一个。`clock` 可选；省略时直接读取精确时间的 FSDB 最终值，传入时保留逐时间点 clock-sampled 上下文。无 `clock` 时不得传 `edge` / `sample_point`。`slice_hint` 仅允许 direct `signal`。用 `args.value_format:"hex"|"bin"|"dec"` 控制响应显示，默认 hex；aggregate 应传最终 leaf signal，xdebug 不猜测 indexed path。

- APB、AXI、stream、event、signal、verify 等所有会返回逻辑值的 action 共享同一 `value_format` 合同。协议字段从配置中的真实 signal handle 取 NPI range size；stream select/concat 等派生表达式仅在操作数宽度均可证明时携带位宽。无法证明时不按 FSDB 文本长度猜测，检查 `summary.value_width_complete` 与 `summary.width_diagnostics`。
- `stream.*`：通用 vld-data / vld-rdy-data 任务抽取，是重要能力。凡是可抽象成 `clock + vld + data`，并可选 `rdy`、`bp`、`sop/eop`、`channel_id` 的外部接口、模块内部交互、pipeline stage、FIFO/queue 出入口、仲裁请求授予、RM/scoreboard 内部任务流，都可以注册 stream 后查询 transfer、stall、packet、多字段 filter 或导出 beats。一次性条件找点用 `event.find/export`；协议统计用 `protocol.handshake.inspect`；标准 AXI/APB 可优先用专用 action；非标准或模块内部 vld-data 任务优先考虑 stream。stream action 字段统一写 `stream`，不写 `name`。
- `stream.query`、`stream.export` 和 `stream.validate(dynamic:true)` 的 `cache_scope` 默认 `full`：完整 FSDB 只构建一次 base，response 仍严格使用请求的 `time_range`。预计连续 query/export/dynamic validate 或多个不同窗口时保持 `full`；明确的一次性窄窗口可显式用 `range`。`range` 必须同时提供非空 `time_range`，并使用独立 range key；不同 range 不合并，也不改用 full。
- `apb.export`、`axi.export` 和 `stream.export` 的 artifact 采用 create-new 整组发布：目标任一文件已存在时拒绝导出，不覆盖旧文件；写入、同步或并发发布失败会在返回前回滚本次整组文件。需要重试时必须换用新的 output path/prefix，不要先假定已有文件可被覆盖。
- 收到 `ANALYSIS_MEMORY_LIMIT_EXCEEDED` 后，agent 可以显式发起新的 `cache_scope:"range"` 窄窗口请求；这是用户可见的新请求，不是 engine fallback。range 仍失败时停止重试并建议使用 `x-npi` 做离线一次性分析。`stream.validate(dynamic:false)` 必须省略 `cache_scope`。
- `window.verify`：sampled proof。用于证明某个 clock window 内条件 always/eventually/never 是否成立；适合最终证明，不适合枚举原始 value-change timeline。
- `signal.changes`：raw timeline。用于列出某个信号的精确变化时间；需要按表达式关联多信号时改用 `event.find/export`。

## Builtin Actions
| action | status | resource | purpose | how it works | objective | args contract |
| --- | --- | --- | --- | --- | --- | --- |
| `actions` | stable | none | 列出当前运行时公开 action catalog。 | 默认返回 compact action names；`args.output.verbose=true` 时返回 descriptors，并同时返回按资源类别划分的 modes。 | 让 agent 在调用前发现真实可用能力。 | no required args |
| `batch` | stable | none | 批量执行多个 xdebug request。 | 按 requests 顺序复用同一入口逐条调度，汇总每条响应。 | 减少多轮 IPC 和保持一组查询的上下文一致。 | required: requests |
| `schema` | stable | none | 返回指定 action 的 request/response JSON schema。 | 按 action/kind 查 checked-in schema 文件并原样返回。 | 让调用方先校验参数和响应结构。 | none |
## Session Actions
| action | status | resource | purpose | how it works | objective | args contract |
| --- | --- | --- | --- | --- | --- | --- |
| `session.close` | stable | session | 以 graceful 或 force 模式关闭一个或全部 session。 | graceful 只请求退出且失败时保留诊断记录；force 可在身份校验后终止本机进程；`all` 返回移除与保留计数。 | 结束 session，或显式清理异常残留。 | required: target.session_id；mode 可取 graceful 或 force（默认 graceful）；ownership_token 仅允许 force 且精确单一 session_id |
| `session.doctor` | stable | session | 诊断当前 session。 | 检查 session 资源、路径和可访问状态。 | 定位 daidir/fsdb/session 绑定问题。 | none |
| `session.gc` | stable | none | 清理过期 session。 | 扫描 session 管理状态并回收可释放项。 | 避免长期运行时积累无用资源。 | none |
| `session.list` | stable | session | 列出当前 session。 | 读取 SessionManager 中的活动 session 元数据。 | 确认已有 session_id 和资源类型。 | none |
| `session.open` | stable | any | 打开 design/waveform session。 | 解析 target 中的 daidir/fsdb；可选 `target.run_manifest` 会在启动前校验 published state、canonical path、size 与 SHA-256；每次 backend open 前 frontend 都绑定 cleanup token，沿用 managed wrapper 提供值或 fail-closed 地内部高熵生成，catalog 只原子保存其 SHA-256 digest。 | 建立后续 design/waveform 查询的资源上下文。 | required: name；ownership_token 仅是 managed wrapper 可选提供的 conditional-cleanup token；普通 CLI caller 省略，但 frontend 仍绑定内部 token，所有输出禁止回显 |
## Design Actions
| action | status | resource | purpose | how it works | objective | args contract |
| --- | --- | --- | --- | --- | --- | --- |
| `expr.normalize` | stable | conditional | 规范化表达式或设计信号赋值。 | `expr` 分支纯字符串规范化且禁止 session；`signal` 分支结合 design 赋值信息且要求 design session。两者互斥。 | 把表达式或设计赋值转成 agent 更易处理的结构。 | exactly one of: expr / signal；signal 分支可用 line_limit/no_statement_only/role |
| `signal.canonicalize` | stable | design | 返回信号 canonical 名称。 | 基于设计解析结果选出规范路径。 | 让后续 action 使用稳定路径。 | required: signal |
| `signal.resolve` | stable | design | 解析设计信号。 | 在设计数据库里查找 signal 并返回候选/规范路径。 | 消除层次或别名不确定性。 | required: signal |
| `trace.driver` | stable | design | 查找信号直接 driver。 | 调用设计 trace 能力分析赋值、依赖和来源。 | 解释某个信号由什么驱动。 | required: signal |
| `trace.load` | stable | design | 查找信号 load。 | 从设计数据库遍历信号使用点。 | 回答信号影响到哪里。 | required: signal |
## Waveform Actions
| action | status | resource | purpose | how it works | objective | args contract |
| --- | --- | --- | --- | --- | --- | --- |
| `apb.config.list` | stable | waveform | 列出 APB 配置。 | 读取 APB 配置存储；`args:{}` 列全部，`args.name` 显示单个配置详情。 | 查看可用 APB interface 名称。 | args:{} list all; optional name shows one config |
| `apb.config.load` | stable | waveform | 加载 APB 配置。 | 保存 APB interface 信号映射。 | 定义后续 APB 查询对象。 | required: name; also one of: config / config_path |
| `apb.transaction.cursor` | stable | waveform | 在 APB transfer 间移动游标。 | 基于 APB 查询结果按 op/direction 定位 begin/next/prev 等。 | 交互式浏览 APB 事务。 | required: name, op |
| `apb.export` | stable | waveform | 预览或导出 APB 事务。 | 必须给出完整 time_range；direction 与顶层 address exact/range/mask 取 AND。无 output.path 时固定最多返回 8 行 data.preview；有 path 时写一个按时间排序的 TSV/CSV data artifact 和 meta，不回退到 query/stream。 | 把完整过滤结果交给外部表格或脚本，并保留扫描、匹配、字节数与完整性证据。 | required: name, time_range.begin/end<br>optional: direction, address, render_time_unit, value_format, output<br>output.file_format: tsv/csv; file_format requires path |
| `apb.query` | stable | waveform | 查询 APB transfer。 | direction 与 address exact/range/mask 取 AND；先过滤再应用 1-based `query.index`、`query.line_limit` 或 last。旧 `addr` 和标量 address 被拒绝。 | 抽取标准 APB completed transfer。 | required: name<br>address is exact/range/mask object |
| `apb.statistics` | stable | waveform | 统计已完成 APB 事务。 | 复用 canonical APB 缓存，按 direction 与一种 address 模式过滤并分别统计 read/write；逐笔 payload 用 apb.query，完整 artifact 用 apb.export，单笔信号现场用 apb.transfer_window。 | 按方向或地址核对 APB 访问次数。 | required: name<br>filter direction/address with AND; address mode is exact/range/mask |
| `apb.transfer_window` | experimental | waveform | 实验性 APB 窗口分析。 | 围绕指定 APB transfer 返回相关信号窗口。 | 解释单笔 APB 访问现场。 | required: name |
| `axi.analysis` | stable | waveform | 汇总 AXI 行为。 | `analysis` 取 `latency`、`osd` 或 `pending`，分别统计完成事务延迟、outstanding 变化和扫描结束未闭合事务。 | 快速判断 AXI 接口健康度。 | required: name |
| `axi.export` | stable | waveform | 导出 AXI 数据。 | 按 name 和 time_range 查询 AXI，再按 format/output.path 写出。 | 给外部表格或脚本分析。 | required: name<br>also one of: time_range |
| `axi.channel_stall` | experimental | waveform | 实验性 AXI stall 分析。 | 按 channel 检查 valid 高 ready 低的持续窗口。 | 定位背压和阻塞。 | required: name |
| `axi.config.list` | stable | waveform | 列出 AXI 配置。 | 读取 AXI 配置存储；`args:{}` 列全部，`args.name` 显示单个配置详情。 | 查看可用 AXI interface 名称。 | args:{} list all; optional name shows one config |
| `axi.config.load` | stable | waveform | 加载 AXI 配置。 | 保存 AXI channel 信号映射。 | 定义后续 AXI 查询对象。 | required: name; also one of: config / config_path |
| `axi.transaction.cursor` | stable | waveform | 在 AXI transfer 间移动游标。 | 基于 AXI 查询结果按 op/direction 定位事务。 | 交互式浏览 AXI 事务。 | required: name, op |
| `axi.latency_outlier` | experimental | waveform | 实验性 AXI latency 异常。 | 从配对结果中找超过阈值或分布异常的事务。 | 定位慢事务。 | required: name |
| `axi.outstanding_timeline` | experimental | waveform | 实验性 AXI outstanding 时间线。 | 跟踪请求和响应，统计未完成事务数量随时间变化。 | 发现 outstanding 积压或乱序风险。 | required: name |
| `axi.query` | stable | waveform | 查询 AXI channel/transaction。 | direction/address/id/time_range 取 AND，time_range 按 AW/AR handshake；默认每笔返回第一拍且第一笔返回全部 beats，true 展开全部返回事务。 | 抽取标准 AXI transaction 或从精确通道握手反查。 | required: name<br>address exact/range/mask; id exact/range |
| `axi.request_response_pair` | experimental | waveform | 实验性 AXI 请求响应配对。 | 用 ID/address/channel 信息把请求与响应关联。 | 分析 latency 和缺失响应。 | required: name |
| `axi.statistics` | stable | waveform | 统计已完成 AXI 事务。 | 复用 canonical AXI 缓存；ID 队列内部取 OR，direction、ID、address 三类条件取 AND；逐笔明细用 axi.query，pending/latency/outstanding 用 axi.analysis，artifact 用 axi.export。 | 按方向、ID 和地址核对 AXI 事务次数。 | required: name<br>filter direction/ids/address with AND; address mode is exact/range/mask |
| `counter.statistics` | stable | waveform | 统计计数器行为。 | 按 clock/vld/cnt 采样，分析递增、回绕、停顿和异常。 | 判断计数器是否符合预期。 | required: clock, time_range, vld, cnt |
| `waveform.cursor.delete` | stable | waveform | 删除游标。 | 按 name 从 CursorManager 删除记录。 | 清理不再需要的时间标记。 | required: name |
| `waveform.cursor.get` | stable | waveform | 读取命名游标。 | 从 CursorManager 按 name 取出保存的时间和元信息。 | 把自然语言中的“刚才那个点”变成确定时间。 | required: name |
| `waveform.cursor.list` | stable | waveform | 列出游标。 | 读取当前 session 的 cursor 存储。 | 查看可复用的命名时间点。 | none |
| `waveform.cursor.set` | stable | waveform | 保存命名时间游标。 | 解析必填的 `time` 为 FSDB 时间并写入 CursorManager；不接受旧 `at` 字段。 | 给后续窗口、比较和人工定位复用时间点。 | required: name, time |
| `waveform.cursor.use` | stable | waveform | 激活游标。 | 按 name 取游标并设为当前 active。 | 让后续交互默认围绕该时间点。 | required: name |
| `signal.anomaly.inspect` | stable | waveform | 扫描常见波形异常。 | 对 signals 执行 glitch/stuck/unknown 等检查并返回 findings；valid/ready 协议里的合法 idle/backpressure 不应只凭 stuck finding 判为 bug。 | 快速发现值得展开的异常窗口。 | required: signals |
| `event.config.list` | stable | waveform | 列出事件配置。 | 读取 EventManager 中保存的配置；`args:{}` 列全部，`args.name` 显示单个配置详情。 | 查看可用事件查询模板。 | args:{} list all; optional name shows one config |
| `event.config.load` | stable | waveform | 加载事件查询配置。 | request args 只传 name 和可选 config_path/render_time_unit；clock/edge/sample_point/signals/reset 来自配置文件内容。 | 复用常见事件查询上下文。 | required: name |
| `event.export` | stable | waveform | 导出满足表达式的事件。 | 与 event.find 同样分析，但按 export 模式返回/写出更多命中数据；表达式支持布尔组合、相等比较和大小比较。 | 把事件列表交给后处理或报告。 | required: expr<br>also one of: name / clock + signals |
| `event.find` | stable | waveform | 查找满足表达式的事件样例。 | 用 name 配置或 inline clock/signals 构建 EventQuery，按 clock sampling 模式扫描表达式命中；表达式支持布尔组合、相等比较和大小比较。 | 快速找到协议条件发生的时间。 | required: expr<br>also one of: name / clock + signals |
| `expr.eval_at` | stable | waveform | 在指定时间求布尔/表达式值。 | 把 signals alias 映射到 FSDB 信号，按 clock/time 采样后交给表达式求值器。 | 用自然表达式检查组合条件。 | required: expr, time, signals, clock |
| `protocol.handshake.inspect` | stable | waveform | 检查 valid/ready 握手。 | 按 clock 采样 valid/ready/data，统计 stall、transfer 和数据稳定性违规。 | 定位握手停顿和协议风险。 | required: clock, valid, ready |
| `list.add` | stable | waveform | 向信号列表追加一个信号。 | 检查 signal 在 FSDB 中存在后写入 ListManager。 | 逐步构建观察列表。 | required: name, signal |
| `list.create` | stable | waveform | 创建命名信号列表。 | 在 ListManager 存储中创建 list，并可追加初始 signals。 | 为一组信号建立可复用集合。 | required: name |
| `list.load` | stable | waveform | 从 JSON 配置加载命名信号列表。 | 原子校验 config/config_path 中的 lists、名称、重复项和 FSDB leaf paths，再按 replace/append 写入 ListManager。 | 在多信号、多时间点查询前加载一个或多个关键观察集合。 | also one of: config / config_path<br>optional: mode(default replace) |
| `list.delete` | stable | waveform | 从信号列表删除信号或 index。 | 按 name 找 list，再用 signal 或 index 删除条目。 | 维护已保存观察列表。 | required: name<br>also one of: signal / index |
| `list.first_change` | stable | waveform | 查找 list 在时间窗口内的首次差异。 | 解析 time_range.begin/end 后扫描 list 内信号变化。 | 定位一组信号何时开始不同。 | required: name, time_range |
| `list.export` | stable | waveform | 导出 list 数据。 | 读取 list 信号并写出 `u64bin` 波形表；manifest format 为 `u64bin.v1`。 | 把窗口数据交给外部分析。 | required: name<br>format: u64bin only |
| `list.show` | stable | waveform | 显示信号列表内容。 | 读取 ListManager 存储并返回 index/signal。 | 确认 list 当前包含哪些信号。 | required: name |
| `list.validate` | stable | waveform | 验证 list 中信号是否存在。 | 逐条检查 FSDB signal handle。 | 发现过期或错误路径。 | required: name |
| `signal.sampled_pulse.inspect` | experimental | waveform | 检查未被 clock 采到的 valid 短脉冲。 | 按 clock 采样 valid，同时扫描 valid 原始变化；若 valid 在两个采样边沿间拉高但没有采样边沿看到高电平，则报 unsampled_valid_pulse。可选 payloads 用于补风险现场。 | 解释仿真里“波形有脉冲但 DUT 没采到”的问题。 | required: clock, valid |
| `scope.list` | stable | any | 有界列出 waveform/design 层级对象。 | `source=wave`（默认）要求 FSDB，`design` 要求 daidir，`merged` 要求两者；保留 `level` 深度语义。kind 支持 module/interface/interface_array/gen_scope/internal_scope/modport/mpport/port/signal。每项发布 sources/queryable/traceable，summary 发布 visited_count 与 canonical 完整性字段。 | 发现 elaborated generate、interface array、modport/mpport，或把设计层级证据与波形可查询性合并。 | optional: source(default wave), path, level(default 0), kind(default all), include_patterns, exclude_patterns<br>limits: max_rows |
| `scope.roots` | stable | any | 发现 waveform/design 根。 | 合并 FSDB 根和可用设计根信息。 | 判断 session 绑定的顶层和路径规范。 | none |
| `signal.changes` | stable | waveform | 读取信号变化点。 | 扫描 FSDB value changes；`mode:"timeline"` 可配 `line_limit` 返回逐项证据，`mode:"summary"` 只返回聚合事实。 | 看信号何时跳变。 | required: signal |
| `signal.stability` | stable | waveform | 检查信号窗口内是否稳定。 | 基于 signal.changes 判断是否只有初始值或无变化。 | 确认控制/状态信号是否保持不变。 | required: signal |
| `signal.statistics` | stable | waveform | 统计信号活动。 | 无 clock 时统计原始变化；有 clock 时按边沿采样，统计 known/high/low/unknown。 | 量化活跃度、占空和采样质量。 | required: signal |
| `signal.xz_verify` | experimental | waveform | 检查信号在窗口内是否始终满足指定 X/Z 状态。 | 扫描 raw waveform 闭区间；exact 要求整向量全为目标态，contains 要求每个值至少含一位目标态。 | 证明信号持续全 X、全 Z，或持续包含指定未知态。 | required: signal, expected_state, time_range<br>optional: match_mode(default exact) |
| `nwave.rc.generate` | stable | waveform | 根据分组生成波形 rc。 | 读取配置并写出 output.path，返回 group/signal 统计。 | 把调试信号集合导入波形工具。 | required: config_path, output |
| `value.at` | stable | waveform | 统一读取信号集合在一个或多个时间点的值。 | 从 `signal/list/apb/stream/axi` 恰好一个来源建立有序 entry 集合，再按 `time/times` 逐点采样；stream 表达式同时返回语义 entry 和 namespaced raw alias。 | 一次比较单信号、关键列表或协议接口在多个离散时间点的现场。 | exactly one of: signal / list / apb / stream / axi<br>exactly one of: time / times<br>optional: clock, edge, sample_point |
| `verify.conditions` | stable | waveform | 在单个时间验证条件集合。 | 解析 clock/time，按 args.signals 采样 alias，并对 conditions[].expr 求值。 | 检查某个时间点的多条件事实。 | required: conditions, time, clock, signals |
| `window.verify` | stable | waveform | 按 clock 在窗口内验证条件。 | 按 clock edge 采样 args.signals 中的 alias，逐个 conditions[].expr 统计 pass/fail/unknown。 | 判断协议或断言类条件是否持续满足。 | required: clock, conditions, signals |

Stream 配置必须使用 `signals` map：真实信号路径只写在 `signals` 的 value 里，`clock`、`reset`、`vld`、`rdy`、`bp`、`sop/eop`、`channel_id`、`data`、`*_fields` 只能引用 alias 或 alias 表达式。
命名逐拍 payload 字段只使用 `beat_fields`；`data_fields` 已删除且不会兼容解析。

| `stream.config.load` | stable | waveform | 加载 stream 配置。 | 把 stream 定义写入 stream manager。 | 定义 valid/ready/data 类流接口。 | also one of: config / config_path |
| `stream.config.list` | stable | waveform | 列出 stream 配置。 | 只列出已保存配置的名称和摘要，不接受 name。 | 查看可查询的 stream。 | no required args |
| `stream.config.get` | stable | waveform | 读取一个原始 stream 配置。 | 按 name 返回保存时的原始配置，不做解析或活动语义投影。 | 精确读取已保存配置内容。 | required: name |
| `stream.describe` | stable | waveform | 描述 stream 的解析结果和活动语义。 | 按 stream 名解析信号、静态验证、采样与 packet 规则，并返回活动语义。 | 查询前确认 stream 的可执行定义。 | required: stream |
| `stream.validate` | stable | waveform | 验证 stream 配置。 | static validation 不建 base；`dynamic:true` 与 query/export 复用 `cache_scope` 选择的 base。 | 提前发现错误信号路径和动态流行为问题。 | required: stream<br>cache_scope: full(default) / range only when dynamic=true |
| `stream.query` | stable | waveform | 查询并过滤 stream transfer/packet。 | 无 `sop/eop` 时按 transfer 在线过滤；packet stream 必须用 `filter.position=sop/eop` 选择边界拍并返回整包；默认 full base 仍只投影 time_range response。 | 按多个 data/beat/stable 字段筛选流事务并复用基础分析。 | required: stream, query<br>cache_scope: full(default) / range<br>filter.fields conditions AND; each mode exact/range/mask<br>packet filter requires position sop/eop |
| `stream.export` | stable | waveform | 导出 stream 查询结果。 | 按 kind/format 从 query/dynamic validate 共用的 full/range base 写出；`kind` 只能是 `transfer`、`packet`、`packet_beats`。 | 把流数据输出给外部脚本并避免重复扫描。 | required: stream<br>cache_scope: full(default) / range<br>kind: transfer / packet / packet_beats<br>format: tsv / csv / xout<br>when kind=packet_beats: output |
## Combined Actions
| action | status | resource | purpose | how it works | objective | args contract |
| --- | --- | --- | --- | --- | --- | --- |
| `trace.active_driver` | stable | combined | 在指定时间找 active driver。 | 结合 waveform 当前值和 design 依赖，定位 time 的有效驱动证据。 | 回答“此刻是谁真正驱动了它”。 | required: signal, time |
| `trace.active_driver_chain` | stable | combined | 展开 active driver 链。 | 从 signal/time 递归追溯 active driver；`value_format` 支持 hex、bin、dec 并统一控制链上采样值显示，默认 hex；深度限制写 top-level `limits.max_depth`，默认 8。遇到多个 active assignments 或多个 RHS sources 时在精确 `active_time` 返回前后值证据并停止。因 max_depth 停止时读取 `data.depth_frontiers` 与 `suggested_next_actions`，可从 frontier 续查或提高深度重跑。 | 给出跨级根因链及 ambiguous RHS 现场。 | required: signal, time<br>limits: max_depth(default 8), max_nodes(default 50), max_trace_signals(default 64)<br>do not use `args.depth`, `args.clk_period` or `limits.max_alias_candidates` |
| `trace.x_origin` | experimental | combined | 从指定 signal/time 追溯 X。 | 先确认查询值含 X，再按 DFS 同等追踪含 X 的 RHS/control；纯 port/interface/modport/ref alias 路径先归并为一个有效链，再应用 `max_chains`。`query_time` 保留请求时刻，逐跳 `x_onset_time` 表示连续 X 区间起点，`active_time` 表示 NPI active-driver 时刻。深度停止时以 `continue_time` 返回可直接续查的 frontier。 | 返回最终有效 X 链，找到一个或多个 X 候选源、不可见边界或受限现场。 | required: signal, time<br>optional: value_format<br>limits: max_depth, max_nodes, max_time_steps, max_trace_signals, max_chains(default 8; after alias coalescing) |
