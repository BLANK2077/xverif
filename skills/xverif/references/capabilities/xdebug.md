# xdebug：按一次 Debug 流程取证

xdebug 是 daidir/FSDB 确定性事实入口。本文件覆盖高频决策链，不是全量 API 手册。每个阶段能力不足时，读取 [全量 xdebug action 索引](../generated/xdebug-actions.md)，再查询 runtime action catalog、action-specific schema 和 checked-in example；不要猜参数。

## 1. 建立资源、scope 和 config

- `daidir` 提供 scope、driver、load、source 和静态依赖；`fsdb` 提供值、事件、窗口和协议；combined session 支持 active driver。
- 用 `scope.roots` 找根，再用 `scope.list` 确认 hierarchy、真实信号和最终 leaf path。默认 `source=wave`；纯 daidir 层级发现使用 `source=design`，同时需要设计关系和波形可查询性时使用 `source=merged`。读取每项的 `sources/queryable/traceable`，不能把只有 design 证据的对象当作可直接波形查询。
- `scope.list` 的 `level` 控制 hierarchy 深度，`limits.max_rows` 控制对象预算；modport/mpport 计入 visited budget，但不增加 hierarchy depth。`response_truncated=true` 时结合 `visited_count/returned_count/truncation_scopes` 缩小 path、level 或 kind，不把截断结果当成完整层级。
- packed struct/aggregate 必须落实到 payload leaf；不能把 aggregate knownness 当最终结论。
- 记录 clock/reset、valid/ready/data、payload fields、state/counter、channel/id/opcode。
- 更完整的 scope/design/source/graph 能力见 [全量 action 索引](../generated/xdebug-actions.md)。

## 2. 定位异常时间和保存现场

| 问题 | action | 使用边界 |
| --- | --- | --- |
| 已知时间，只查一个信号 | `value.at` | 默认无 clock 直接点读；需要采样上下文时再传 clock |
| 已知时间，查一组相关信号 | `list.load` → `value.at(list, times)` | list 承载信号组，times 承载一个或多个有序时间点 |
| 查看单信号在受限窗口怎样变化 | `signal.changes` | 用于缩小范围，不先导出全量变化 |
| 查看活动率、变化次数、持续特征 | `signal.statistics` | 用于宏观定量筛选 |
| 不知道异常时间，找首次/下一次条件命中 | `event.find` | 边沿、组合条件、阈值、状态转换；X/Z 比较为 unknown |
| 已知单点，同时验证多个条件 | `verify.conditions` | 单点事实证明 |
| 验证条件在 clock-edge 窗口持续成立 | `window.verify` | 输出 pass/fail/unknown；不代替事件搜索 |
| 证明 raw 信号在窗口内持续为 X/Z | `signal.xz_verify` | 闭区间逐变化检查；`exact` 检查全位，`contains` 检查至少一位 |

推荐递进：`signal.statistics/changes` → `event.find` → `list.load` →
`value.at(list="name", times=[...])` → `verify.conditions/window.verify`。更多
value/signal/event/list/verify action 见 [全量 xdebug action 索引](../generated/xdebug-actions.md)。

`value.at` 省略 `clock` 时返回精确 `time` / `times` 的最终 FSDB 值和
`sampling_mode:"raw_time"`；传入 `clock` 时返回 `sampling_mode:"clock_sampled"` 及
clock context。无 `clock` 时不要传 `edge` 或 `sample_point`。所有返回逻辑值的
action 都用 `args.value_format:"hex"|"bin"|"dec"` 选择显示，默认 hex。已取得
NPI range size 的原始信号和可证明宽度的派生值始终以 `<实际位宽>'h`、
`<实际位宽>'b` 或 `<实际位宽>'d` 返回；decimal 遇 X/Z 时降为同宽 binary，并在
canonical value 对象中区分 requested/effective format。不要用 `args.format`
代替 `value_format`。

若某个值的真实位宽不可证明，响应不会按文本长度猜位宽，而会保留无位宽 literal；
同时读取 `summary.value_width_complete` 和 `summary.width_diagnostics[]` 判断
缺失来自 NPI range、冲突信号宽度还是派生表达式。

## 3. 解释异常、采样和握手

- `signal.anomaly.inspect`：X/Z、glitch、异常短脉冲和 stuck 的 raw waveform smoke。合法 idle/backpressure 不能仅凭 stuck 判为 bug。
- `signal.xz_verify`：对 raw waveform 闭区间给出持续 X/Z 的 pass/fail 证明；
  `match_mode=exact` 要求每一位均为目标态，`contains` 要求每个值至少含一位目标态。
- `signal.sampled_pulse.inspect`：解释 raw valid pulse 是否被指定 clock edge 采到，并保留 payload 在邻近边沿的现场。
- `protocol.handshake.inspect`：解释 valid/ready、backpressure 和 stall；可复用接口的连续分析优先进入 stream workflow。
- 其它 anomaly/handshake/protocol action 见 [全量 action 索引](../generated/xdebug-actions.md)。

## 4. 从信号追到 RTL 根因

1. `trace.driver` 静态查可能驱动来源。
2. `trace.load` 查消费位置和影响范围，决定下一批观察信号。
3. 从 driver/load 结果保留候选 file:line 和 source evidence。
4. `event.find` 定位异常时间，已加载 list 的 `value.at` 保存控制现场。
5. 有 daidir + fsdb + signal + time 时用 `trace.active_driver` 查当前真正生效 driver。
6. 单级仍未到根因时用 `trace.active_driver_chain`；递归深度写顶层 `limits.max_depth`，默认 8，不能写 `args.depth`。本 action 不接受 `limits.max_alias_candidates`。若结果为 ambiguous，读取 `data.ambiguity_evidence`。若因深度停止，直接使用 `data.depth_frontiers` 和 `suggested_next_actions` 从 frontier 续查或提高深度重跑；不需要 `clk_period`。
7. 查询点本身为 X 时可直接用 `trace.x_origin`：它按 DFS 同等追踪含 X 的 RHS/control，
   穿过 module port、interface/modport，并在每一跳重新寻找该分支的 X onset。纯
   port/interface/modport/ref alias 路径会先归并，同一 RHS/control 语义路径只返回
   一个代表 chain。
   `query_time` 是请求时刻，`x_onset_time` 是该分支连续为 X 的起点，
   `active_time` 是 NPI active-driver 时刻；三者不能互相替代。
   `limits.max_chains` 默认 8，并在 alias 归并后应用；读取每个 chain 的
   status/current/pending，不能把 partial 当完整结果。深度停止时使用对应 chain 的
   frontier 继续。
8. 回到 `value.at` 验证链上的控制条件。

保留 `resolved`、`control_only`、`unresolved`；control evidence 不能冒充最终 data driver。更多 trace/source/graph action 见 [全量 action 索引](../generated/xdebug-actions.md)。

## 5. Stream 是通用数据流能力

`stream.*` 不限 AXI/APB。任何能表示为 `clock + vld + data`，可选 `rdy/bp/sop/eop/channel_id` 的 pipeline、FIFO、command/response、descriptor、packet、credit/backpressure 或自定义 valid-ready 都优先考虑 stream。

流程：确认 leaf paths → `stream.config.load` → `stream.config.list` / `stream.config.get`
验证 → `stream.describe` 确认字段 → `stream.query` 查 transfer/stall/packet → finding
时间补 `value.at` → `trace.active_driver` 解释 backpressure/control → `window.verify` 证明。

- packet 跨 beat 不变字段写 `packet_stable_fields`；过滤时它与 `data`、
  `beat_fields` 统一从 `filter.fields` 引用，但返回结构和稳定性检查仍保持独立。
- packet 汇总读取 `complete_packet_count`、`partial_packet_count` 和
  `packet_count_status=exact|not_configured|ambiguous`，不要从窗口内 partial packet
  推断精确总数。
- `stream.config.load/get` 返回静态预检：resolved signal path/width、sampling 和
  packet rules；先看该结果，再启动大窗口扫描。

APB/AXI action 只在需要协议专属 transaction、channel 或 violation 语义时使用。完整 stream/APB/AXI action 见 [全量 action 索引](../generated/xdebug-actions.md)。

`apb.query` 默认 `direction=all`，其 index/last/line_limit/address 都作用于按时间排序的
读写混合序列；只有明确只看读或写时才传 `direction=read|write`。APB 配置必须显式
提供 `PREADY` 和 `PSLVERR`；缺少任一信号时 `apb.config.load` 直接拒绝，不假设
zero-wait 或 no-error。

需要持久化 APB transaction 时使用 `apb.export`，不要改用通用 `stream.export`。它要求
完整 `time_range.begin/end`，顶层 `direction` 与 `address` exact/range/mask 取 AND；不传
`output.path` 时只返回固定最多 8 行 `data.preview`，传 path 时写一个按时间排序、混合读写的
TSV/CSV data artifact 及 meta。用 `scanned_transaction_count`、
`in_range_transaction_count`、`matched_transaction_count`、`preview_row_count`、
`artifact_bytes` 和 canonical completeness 判断结果，不能把 preview 当作完整导出。

只需要计数时使用 `apb.statistics`：`filter.direction` 与 `filter.address` 取 AND，address
只能选择 exact 队列、闭区间 range 或 value/mask 三种模式之一。它只统计已完成事务，
复用同一 session/config 的 canonical APB 缓存，不接受 `line_limit`，也不会重新扫描 FSDB。
需要逐笔 payload 时改用 `apb.query`，需要完整 artifact 时使用 `apb.export`，需要单笔
原始信号现场时使用 `apb.transfer_window`。

## 6. 宏观波形和多模态观察

需要观察长时间趋势、多信号相对关系、burst、stall 分布或状态阶段时，使用 [waveform render workflow](../workflows/waveform-render.md)：`list.load` → `list.export` → `xwaveform render` → 查看 JPG 和 stats JSON → 形成假设 → 回到确定性 action 验证。

图片不是唯一证据。需要交付 nWave 可复查视图时使用 `nwave.rc.generate`，不要手写 RC。其它产物/export action 见 [全量 action 索引](../generated/xdebug-actions.md)。

## 7. 保存并复用 config

- `stream.config.load`、`axi.config.load`、`apb.config.load` 的稳定映射必须优先从项目已有 config 加载。
- 首次推导的稳定配置不能只留在 session：优先保存到现有目录；无约定时建议 `xdebug/configs/`，并在 `xdebug/signals.md` 记录 clock/reset、leaf path、字段含义、采样和时间约定。
- config 不保存临时 session id、一次性 finding 或临时输出路径。
- 保存后用对应 `*.config.list` 验证，后续 workflow 复用配置。
- 当前任务未授权写项目文件时先询问；不得静默写到其它路径。xwiki 只在获得授权时保存稳定知识。

## 8. AXI 事务与 AW/W 顺序

- AXI AW、W 是独立通道；W handshake 可以早于 AW、与 AW 同周期或晚于 AW。看到
  W-first 不能直接判协议错误。
- 先 `axi.config.load` 做 signal/width/clock-edge 预检，再按问题选择：完成事务用
  `axi.request_response_pair`，延迟用 `axi.analysis(analysis=latency)` 或
  `axi.latency_outlier`，积压曲线用 `axi.outstanding_timeline`，扫描结束未闭合事务用
  `axi.analysis(analysis=pending)`。
- 写事务重点检查 `address.valid_begin_time/address.handshake_time`、
  `data.valid_begin_time/data.first_handshake_time/data.last_handshake_time` 和
  `response.handshake_time`、
  `phase_order=aw_before_w|same_cycle|w_before_aw`、beat count 和
  `response_dependency_violation`。B 必须晚于 AW handshake 和 WLAST handshake。
- 已知 AW/W/B/AR/R 握手时间时，用 `axi.query` 的 `query.channel` 与
  `query.handshake_time` 精确反查；逐 beat payload 仅在 `output.include_data=true` 时返回。
- 同一 session/config 的 AXI action 与 export 共用 canonical result；诊断中的
  `full_scan_count` 应保持 1。若大窗口变慢，先确认没有换 config name 或重复 open
  session，不要用缩小数据源/切换 transport 作为静默 fallback。
- 只需要事务数时使用 `axi.statistics`。`filter.ids` 队列内部取 OR；direction、IDs、
  address 三类条件取 AND；address 只能选择 exact、range、mask 一种模式。该 action
  只遍历缓存中的 completed transaction，不返回 payload，也不处理 pending。
  逐笔 transaction/channel/beat 使用 `axi.query`，pending/latency/outstanding 使用
  `axi.analysis`，持久化事务证据使用 `axi.export`。
- 两个 statistics action 的 `unresolved_transaction_count` 只统计最终 AND 谓词仍无法
  判断的事务；XOUT `notes` block 会固定说明它是“被引用的 address/ID 含 X/Z 或不可解析”
  导致的计数，不应自行猜测其含义。

## Common failures

- 参数不确定：查询 action schema，读取错误中的 `invalid_arg/expected/available_values/did_you_mean/required_any_of/correct_example`。错误不发布 `allowed_values`；catalog descriptor 的同名 `allowed_values` 是参数 enum 元数据映射。
- 响应 truncated/partial：缩小查询或使用该 action 明确支持的 limits/export。
- `REQUEST_TOO_LARGE`：读取 `received_bytes/max_bytes/transport/phase`，按 `next_actions` 拆分 batch、减少内联配置或使用有界 export；不要原样重试、提高全局上限、截断请求或切换 transport。
- `INVALID_CONFIG`：读取 `config_key/config_source/expected`，按 `next_actions` 修正配置并启动新进程；`recoverable=false` 表示同一进程内重试无效，`received_redacted=true` 表示敏感原值已隐藏。
- session/transport/LSF/timeout：转 `xverif-admin`，不自动 retry/reopen/fallback。

## 深入参考

- [原生 JSON API](../xdebug/json-api.md)
- [完整 response fields](../xdebug/response-fields.md)
- [现有 recipes](../xdebug/recipes.md)
- [已校验 examples](../xdebug/examples.md)
- [能力 overview](../xdebug/overview.md)
- [历史手工 action reference](../xdebug/action-reference.md)：仅用于补充说明；全量性由生成索引保证。
- [RC 生成](../xdebug/rc-generate.md)
- transport 和 runtime troubleshooting 已迁移到 `xverif-admin`。
