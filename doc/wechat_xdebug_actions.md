# xdebug 常用 action 实战

> 从找 leaf path 到导出波形，一批常用 action 的用法、返回字段和边界。

xverif 1.0 发布后，xdebug 的 action 已经覆盖设计数据库、波形、协议、验证和导出。架构、分层与技术路线在上一篇文章里讲过，这篇只讲怎么用。

下面这些调用在本机直连、LSF 和 ssh 远端三种 MCP 部署方式下写法一致，区别只在 backend 进程跑在哪里。

## 按用途分组

73 个 action 按用途可以归成几组，定位问题时先找到组，再查对应 schema。

| 用途 | 主要 action |
| --- | --- |
| 找层次和解析路径 | `scope.roots`、`scope.list`、`signal.resolve`、`signal.canonicalize` |
| 取值和统计 | `value.at`、`signal.changes`、`signal.statistics`、`counter.statistics` |
| 保存信号组并复用 | `list.load`、`list.add`、`list.show`、`list.validate`、`list.first_change`、`list.export` |
| 按条件找发生时刻 | `event.find`、`event.export` |
| 验证和四态检查 | `verify.conditions`、`window.verify`、`signal.stability`、`signal.xz_verify`、`signal.anomaly.inspect` |
| 设计因果 | `trace.driver`、`trace.load` |
| 联合定位 | `trace.active_driver`、`trace.active_driver_chain`、`trace.x_origin` |
| 协议分析 | `apb.*`、`axi.*`、`stream.*`、`protocol.handshake.inspect` |
| 导出产物 | `list.export`、`apb.export`、`axi.export`、`stream.export`、`nwave.rc.generate` |

下面挑几个常用的展开说。例子都走 MCP 的 `xverif_debug_query(session_id, action, args, limits, output_format)`，只写 action 和 args，session 由 `session_id` 指定。

### 先拿到 leaf path：scope.list

`value.at` 只接受最终 leaf signal，查值之前要先确认路径。`scope.list` 从根或指定 path 开始列对象，`level` 控制进入 module 的层数，`kind` 可以只筛 module、interface、gen_scope、port、signal。

```json
{"action": "scope.list",
 "args": {"source": "wave", "path": "top", "level": 1, "kind": "all"}}
```

`source` 有三个取值：`wave` 读 FSDB 层次，`design` 读纯设计层次，`merged` 两边一起用。返回的每个对象带 `sources`、`queryable` 和 `traceable`，只有 `queryable=true` 才能继续做波形查询，`traceable=true` 才能进入设计追踪。结果被截断时先看 `visited_count`、`returned_count` 和 `truncation_scopes`，再缩小 path、level 或 kind 重查。

### 找区间里第一个变化的时间点：list.first_change

排查卡死时经常要回答一个问题：这组相关信号里，最早是哪一拍开始不对。如果信号组已经存进 list，直接用 `list.first_change` 查闭区间。

```json
{"action": "list.first_change",
 "args": {"name": "handshake_context",
          "time_range": {"begin": "100ns", "end": "200ns"}}}
```

返回的 `summary` 给出三个字段：`diff_found`、`diff_time`、`changed_signal_count`。`data.changed_signals[]` 逐个列出信号、`before_time`、`change_time` 以及变化前后的值。它回答的是这组信号里最早出现差异的时刻，并顺带把现场带回来。`time_range` 的 `begin` 和 `end` 可以分别省略，省略的一侧用可用波形窗口的边界。

需要单个信号的完整跳变时间线时用 `signal.changes`，只读某个精确时刻的值用 `value.at`。

### 按条件找发生时刻：event.find

`list.first_change` 看的是值变没变，`event.find` 看的是条件成不成立。表达式支持布尔组合和数值比较，可以直接写 counter 阈值。

```json
{"action": "event.find",
 "args": {"clock": "top.u.clk",
          "signals": {"valid": "top.u.valid", "ready": "top.u.ready",
                      "wait_count": "top.u.dbg_wait_count"},
          "expr": "valid && !ready && wait_count >= 512",
          "mode": "all", "line_limit": 5}}
```

`mode` 有 `first`、`last`、`all` 三种。临时查询直接传 `expr`、`clock` 和 `signals` 就行，不会留下持久 event config；要反复使用同一组条件再走 `event.config.load`。返回的 `summary` 里有 `first`、`last`、`sample_count` 和计数，`data.events` 是命中明细。`max_samples` 是采样预算，耗尽时 `analysis_complete` 为 `false`。

### 一次看一组信号的多个时间点：list.load 与 value.at

已经知道几个可疑时刻，想把同一组信号在这些时刻的值并排看，不必一个信号一个信号地读。先把信号组装进 list：

```json
{"action": "list.load",
 "args": {"config": {"lists": [{"name": "handshake_context",
                                "signals": ["top.u.valid", "top.u.ready", "top.u.data"]}]},
          "mode": "replace"}}
```

再用同一个 `value.at` 一次提交多个时间点：

```json
{"action": "value.at",
 "args": {"list": "handshake_context",
          "times": ["100ns", "120ns", "140ns"],
          "value_format": "hex"}}
```

`times` 是有序且不重复的时间列表，按请求顺序返回。多个时间点一次提交就够，不要在 MCP 层面对同一个 action 反复调用 `xverif_batch`。省略 `clock` 时读的是这些时刻的 FSDB 最终值，返回的 `sampling_mode` 是 `raw_time`；带上 `clock` 时按边沿采样，同时返回 clock context。没有 `clock` 却传 `edge` 或 `sample_point` 会返回 `INVALID_ARGUMENT`。

`value.at` 只接受最终 leaf signal，unpacked array 和 struct 不会自动展开。要逐元素看，先把实际 leaf path 加进 list。

### 统计一个 counter：counter.statistics

想知道一个 counter 在有效窗口内的最小值、最大值和平均值，逐拍看波形太慢。`counter.statistics` 按 clock 采样 `cnt`，用 `vld` 限定哪些采样算有效。

```json
{"action": "counter.statistics",
 "args": {"clock": "top.clk", "edge": "posedge",
          "time_range": {"begin": "100ns", "end": "200ns"},
          "vld": {"expr": "gate_a && permit_b",
                  "signals": {"gate_a": "top.valid", "permit_b": "top.ready"}},
          "cnt": "{top.cnt_hi,top.cnt_lo}"}}
```

返回的 `summary` 有 `sample_count`、`valid_count`、`valid_false_count`、`unknown_count`，以及 `min_value`、`max_value`、`average_value`；`data` 里给 `min_first_time`、`max_first_time` 和 `evidence`。`vld` 可以是信号，也可以是带 `signals` 别名的表达式；`cnt` 支持把多个信号拼成一个宽 counter。只看一般信号的活动率和变化次数用 `signal.statistics`。

### 证明条件在区间内一直成立：window.verify

想知道 `ready` 拉低期间 `valid` 是不是一直保持，或者某个状态在窗口内从未出现，用 `window.verify`。它按 clock 采样，在窗口内验证一组条件，条件有三种模式：`always` 要求每个采样点都成立，`eventually` 要求至少成立一次，`never` 要求任何采样点都不成立。

```json
{"action": "window.verify",
 "args": {"clock": "top.u.clk",
          "signals": {"valid": "top.u.valid", "ready": "top.u.ready"},
          "conditions": [{"expr": "valid == 1", "mode": "always"}],
          "time_range": {"begin": "0ns", "end": "1us"}}}
```

返回里先看 `verdict`、`all_passed`、`sample_count`、`failed_samples` 和 `unknown_samples`。`proof_begin` 和 `proof_end` 给出实际证明覆盖的范围，`stop_reason` 说明扫描为什么结束。`max_samples` 是采样预算，预算耗尽时 `analysis_complete` 为 `false`，这时不能把结果当成整段窗口的证明。`edge` 和 `sample_point` 控制采样点，响应里会分别返回 requested 和 effective 采样设置。

`window.verify` 不替代事件搜索。找第一次出现用 `event.find`，只验证一个时刻用 `verify.conditions`，只看单信号稳定性用 `signal.stability`。

### 解释握手和 stall：protocol.handshake.inspect

valid/ready 接口上的空闲和 backpressure 不等于 bug，关键是分清哪些是正常的等待、哪些是违规。`protocol.handshake.inspect` 按 clock 采样 valid 和 ready，给出 transfer 数量、最大 stall 周期、data stability 和 valid hold 的违规情况。

```json
{"action": "protocol.handshake.inspect",
 "args": {"clock": "top.u.clk", "valid": "top.u.valid",
          "ready": "top.u.ready", "data": "top.u.data"}}
```

`summary` 里的 `transfer_count`、`max_stall_cycles`、`ready_without_valid_cycles`、`data_stability_violations`、`valid_hold_violations` 是主要判据。`ready_without_valid` 默认按 summary 粒度报告，它本身是活动信息，不算协议违规。传 `data` 并把 `rules.check_data_stable_when_stalled` 打开，才会检查 stalled 期间数据是否变化。`valid_wait_open_at_window_end` 说明窗口结束时还有一笔等待没完成，不能据此判定 hang。需要 AXI 或 APB 专用事务语义时改用 `axi.*` 或 `apb.*`。

### 通用 valid-ready 数据流：stream.query

接口只要能表示成 `clock + vld + data`，可选 `rdy`、`bp`、`sop`、`eop`、`channel_id`，就可以用 stream 分析，不必是标准协议。加载 `stream.config.load` 之后用 `stream.query` 查 transfer、stall 或 packet。

```json
{"action": "stream.query",
 "args": {"stream": "req_stream", "query": "summary",
          "time_range": {"begin": "0ns", "end": "1us"}}}
```

`query` 支持 `summary`、`first_transfer`、`last_transfer`、`transfer_window`、`first_stall`、`last_stall`、`stall_window`；配置了 packet 字段后还支持 packet 查询。首次查询建立 canonical 分析并缓存，后续查询复用同一份结果。跨窗口重复查询用默认的 `cache_scope: full`，一次性窄窗口可以显式用 `range`。`stream.config.load` 的返回值里已经包含解析后的信号路径、位宽和采样预检，先看它再启动大窗口扫描。

### 证明闭区间内一直是 X 或 Z：signal.xz_verify

X 只出现过一次，和 X 在整个区间里一直存在，是两个不同的问题。`signal.xz_verify` 回答后者。

```json
{"action": "signal.xz_verify",
 "args": {"signal": "top.xz_bus", "expected_state": "x", "match_mode": "exact",
          "time_range": {"begin": "85ns", "end": "94ns"}}}
```

`match_mode` 为 `exact` 时要求区间内每一位都是目标态，为 `contains` 时只要求每个值至少有一位是目标态。返回的 `verdict`、`always_matched`、`checked_value_count` 和 `stop_reason` 是结论，`data.first_mismatch` 给出第一个不匹配的位置和值。只想知道窗口内有没有出现过 X/Z，用 `signal.anomaly.inspect`；按 clock 验证已知值表达式用 `window.verify`。

### 生成 nWave 的 rc 文件：nwave.rc.generate

调完一轮，想把这次用到的信号组和分组结构留给 nWave，下次直接加载，用 `nwave.rc.generate` 生成 `signal.rc`。

```json
{"action": "nwave.rc.generate",
 "args": {"config_path": "wave_view.json", "output": {"path": "signal.rc"}}}
```

配置里的信号路径用点分层次写，生成前会校验信号在 FSDB 里存在，写 rc 时转换成 `/top/u/sig` 风格。分组支持 subgroup，生成的 `addGroup` 和 `addSubGroup` 固定不带 `-e`。返回的 `summary` 给出 `group_count`、`signal_count`、`written`、`valid`，并附一段 `rc_preview`。

这个 action 只写 signal list 和 view 部分，不写 `openDirFile` 和 `activeDirFile`，打开 FSDB 仍由 nWave 会话负责。

### 导出波形数据：list.export

`xwaveform` 需要 `list.export` 产出的 manifest。还是先 `list.load` 建 list，再由 `list.export` 写出逐信号数据和 manifest，然后渲染成 JPG 和 stats JSON。

```json
{"action": "list.export",
 "args": {"name": "handshake_context",
          "time_range": {"begin": "0ns", "end": "1us"},
          "output": {"path": "artifacts/handshake_export", "file_format": "u64bin"}}}
```

返回的 `summary` 给 `row_count`、`format`、`status`、`output_written` 和 `manifest_path`。不传 `output.path` 时只返回 export preview，不是完整导出。渲染出来的图片用于观察长窗口的整体形态，结论仍要回到 `value.at`、`event.find`、`window.verify` 这些 action 上确认。

仓库地址：<https://github.com/BLANK2077/xverif>

这篇是 xdebug 的用法部分，架构和分层见《xverif 1.0 发布：xdebug 与 xcov 的架构和技术路线》。
