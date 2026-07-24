# xdebug 常见 Debug Recipes

本文是面向 AI agent 的工作流速查。执行时仍以 runtime `actions`、`schema` 和 examples 为最终契约。

## CLI 入口规则

CLI 场景下，本文所有 xdebug action 都通过完整 `xdebug.v1` envelope 进入：先用原生 `session.open` 建立 session，再把后续 action 的 session 选择写到 `target.session_id`。不要把 MCP query 的顶层 `session_id` 或 `tool/args` 外壳写进 CLI request；MCP 调用请使用 `xverif-mcp`。

## 通用原则

- 先使用默认 compact 输出；证据不足时查询 action schema，只使用该 action 明确支持的 `verbose`、`limit` 或 `export` 参数。
- 先定位时间点，再做因果 join。
- 同一时间多信号取值用 `value.batch_at`。
- 不要导出全量 rows/samples/transactions 作为第一步。
- 最终结论必须保留 `signal/time/value/file:line/finding/confidence/truncated`。
- action 分工先定清楚：raw 异常用 `detect_abnormal`，clock-edge 条件用 `event.find/export`，valid 未采样解释用 `sampled_pulse.inspect`，协议 stall 用 `handshake.inspect`，窗口证明用 `window.verify`。
- 通用 vld-data / vld-rdy-data 任务优先考虑 `stream.*`：外部接口、模块内部握手、pipeline stage、FIFO/queue、仲裁请求授予、RM/scoreboard 任务流，只要能抽象成 `clock + vld + data`，并可选 `rdy/bp/sop/eop/channel_id`，就可以注册 stream 查询 transfer/stall/packet 或做多字段过滤。
- 对 `stream.config.load`、`axi.config.load`、`apb.config.load`、`event.config.load` 等需要加载配置的 action，先找项目内已有配置目录和信号路径文档，不要每次从 0 推导。若缺少，主动询问用户是否创建 `xdebug/configs/`、`xdebug/signals.md` 或项目约定路径，并建议写入项目 `AGENTS.md`；同时主动询问用户是否使用 xwiki 保存长期项目记忆，确认前不要写入 xwiki。
- clock sampling action 统一使用 `clock`、`edge`、`sample_point`；默认优先 `edge:"negedge"`。只有 monitor/interface 明确按上升沿采样，或 negedge 结果无法解释 race/skew 时才改 `edge:"posedge"`。使用 posedge 时必须注意 `sample_point:"before"` 与 `"after"` 在同 timestamp 数据变化时会不同；必须用 posedge 时默认推荐 `sample_point:"before"`，只有要观察沿后状态时才用 `"after"`。`edge:"dual"` 只用于 DDR、真实双沿协议或不确定边沿 bring-up，不作为普通 valid/ready 分析默认值。
- packed struct / aggregate payload 必须优先查最终 leaf signal path，例如 `top.u.payload.opcode`、`top.u.payload.data`；不要把 aggregate path 的 knownness 当最终结论，也不要期待 xdebug 自动展开 struct。

## 配置与信号路径复用

所有 `*.config.load` 类 action 都应优先复用项目内配置，不要在每次 debug 时重新推导相同信号列表。

建议被调试项目维护：

- `xdebug/configs/`：保存 stream、AXI、APB、event 等 JSON 配置，例如 `streams.json`、`axi.json`、`apb.json`、`events.json`。
- `xdebug/signals.md` 或 `doc/xdebug-signals.md`：记录 clock/reset、valid/ready/data、payload leaf fields、channel/id/opcode、常用 cursor/time 语义和信号路径证据。
- 项目 `AGENTS.md`：记录配置目录、信号文档位置、维护规则和是否使用 xwiki。

若当前用户工作目录没有这些材料，AI 必须先询问用户是否创建配置目录和信号路径文档，并建议把维护规则写入项目 `AGENTS.md`。同时询问用户是否启用/使用 xwiki，把稳定信号路径、debug 配置索引、接口语义和常见查询流程维护为长期项目记忆；用户确认前不要直接创建或写入 xwiki。

配置复用示例：

```json
{
  "api_version": "xdebug.v1",
  "action": "stream.config.load",
  "target": {"session_id": "case_a"},
  "args": {
    "config_path": "<project>/xdebug/configs/streams.json",
    "mode": "replace"
  }
}
```

## 通用 Stream / 模块内部交互

1. 用用户说明、`xdebug/signals.md`、xwiki 或 `scope.list` 确认 `clock/vld/rdy/data` 的最终 leaf signal path。
2. 用 `stream.config.load` 注册 stream。payload 是 packed struct 时，优先拆成 `beat_fields` leaf fields。
3. 用 `stream.validate` 确认信号可解析。
4. 用 `stream.query` 查 `first_transfer`、`last_transfer`、`first_stall`、`stall_window`、`packet_window`，或用 `filter.fields` 做多字段过滤。
5. 大量 beat/packet 输出用 `stream.export`，不要把全量 rows 放进首轮 compact 响应。

inline 配置示例：

```json
{
  "api_version": "xdebug.v1",
  "action": "stream.config.load",
  "target": {"session_id": "case_a"},
  "args": {
    "streams": [
      {
        "name": "req_stream",
        "signals": {
          "clk": "top.clk",
          "req_vld": "top.u_core.req_vld",
          "req_rdy": "top.u_core.req_rdy",
          "opcode_sig": "top.u_core.req_opcode",
          "id_sig": "top.u_core.req_id",
          "addr_sig": "top.u_core.req_addr",
          "data_sig": "top.u_core.req_data"
        },
        "clock": "clk",
        "edge": "negedge",
        "vld": "req_vld",
        "rdy": "req_rdy",
        "beat_fields": {
          "opcode": "opcode_sig",
          "id": "id_sig",
          "addr": "addr_sig",
          "data": "data_sig"
        }
      }
    ],
    "mode": "replace"
  }
}
```

查询示例：

```json
{
  "api_version": "xdebug.v1",
  "action": "stream.query",
  "target": {"session_id": "case_a"},
  "args": {
    "stream": "req_stream",
    "query": "transfer_window",
    "filter": {
      "fields": {
        "opcode": {"mode": "exact", "values": ["8'h5a"]}
      }
    },
    "time_range": {"begin": "0ns", "end": "100us"},
    "line_limit": 20
  }
}
```

## Ready 卡低

1. `value.batch_at` 取 `valid/ready/full/state/backpressure`。
2. `signal.changes` 查 `ready` 首次卡住或最后变化时间。
3. 有 `daidir + fsdb + time` 时用 `trace.active_driver` 查当前生效 driver。
4. 若 driver 指向 `full`、state 或 grant 条件，补 `value.at` / `value.batch_at` 查控制信号值。
5. 用 `source.context` 获取最终源码 evidence；需要更多上下文时使用 action-specific `context_lines` 或 `args.output.verbose:true`，不要传旧 include 参数。

请求骨架：

```json
{
  "api_version": "xdebug.v1",
  "action": "value.batch_at",
  "target": {"session_id": "case_a"},
  "args": {
    "time": "@stall",
    "clock": "top.clk",
    "signals": ["top.u.valid", "top.u.ready", "top.u.full", "top.u.state_q"],
    "value_format": "hex"
  }
}
```

## Valid 有脉冲但没被接受

1. 若怀疑 raw valid 是周期内异常短脉冲，先用 `detect_abnormal` 的 `glitch` check 扫 valid 或相关 control。
2. 若问题是“raw valid 有过，但采样边沿没看到”，用 `sampled_pulse.inspect`，并把 payload/payloads 传入保留现场。
3. 若问题是采样点上 valid 被 backpressure，用 `event.find` 或 `event.export` 查 `valid && !ready`，counter 阈值可直接写成 `wait_count >= 512`。
4. `handshake.inspect` 找 long stall、accept gap 或 stalled data stability violation。
5. `value.batch_at` 取 payload、ready、backpressure、state；struct payload 用最终 leaf signal path，如 `top.u.payload.opcode`。
6. `trace.driver` 或 `trace.active_driver` 查 ready/backpressure 的设计原因。

表达式查找：

```json
{
  "api_version": "xdebug.v1",
  "action": "event.find",
  "target": {"session_id": "case_a"},
  "args": {
    "expr": "valid && !ready",
    "clock": "top.clk",
    "signals": {
      "valid": "top.u.valid",
      "ready": "top.u.ready"
    },
    "time_range": {"begin": "0ns", "end": "100us"},
    "mode": "first"
  }
}
```

合法 idle/backpressure 窗口不等于 bug。对 valid-ready timeout，`detect_abnormal` 只负责 raw abnormal smoke；最终协议证明用 valid-qualified `event.find/export`、`handshake.inspect`、`signal.changes` 和 `window.verify`。

## Struct 字段

1. AI 必须直接传最终 leaf signal path；xdebug 不自动展开 packed struct / aggregate。例如先用 `scope.list` 或 `value.at` 确认 `top.u.payload.opcode`、`top.u.payload.channel`、`top.u.payload.id`、`top.u.payload.data` 可读。
2. `event.find/export` 的 `signals` 里直接配置这些 leaf fields：

```json
{
  "opcode": "top.u.payload.opcode",
  "channel": "top.u.payload.channel",
  "id": "top.u.payload.id",
  "data": "top.u.payload.data"
}
```

3. 表达式直接写 leaf alias，例如 `vld && rdy && opcode == 8'h5a && data >= 16'h1000`。
4. `detect_abnormal` 也传 leaf field path 列表做多信号扫描；aggregate path 可作为辅助信号，但不能替代 leaf field 结论。

## AXI latency 异常

1. `axi.analysis(analysis=latency)` 查 read/write 分项、phase-order 和完整性；
   `analysis=pending` 只查扫描结束仍未闭合事务，不能用 `osd` 代替。
2. 用 `axi.latency_outlier(method=top_n|threshold)` 从完整候选集筛慢事务，
   `line_limit` 只限制展示。
3. 已知握手锚点时优先用 `axi.query(query.channel, query.handshake_time)` 精确反查完整
   transaction；只有还需旁路信号时，再用 `value.batch_at` 查 AW/W/B/AR/R。
4. W-first 是合法顺序；检查 `phase_order` 和 B 是否晚于 AW 与 WLAST。需要批量事实用
   `axi.export`，它复用 canonical result，`full_scan_count` 应为 1。
5. 默认 transaction 只给 address/data/response 的关键时间和信息；只有必须检查逐 beat
   payload 时才传 `args.output.include_data:true`。

```json
{
  "api_version": "xdebug.v1",
  "action": "axi.analysis",
  "target": {"session_id": "wave_case"},
  "args": {
    "name": "axi0",
    "analysis": "latency",
    "direction": "read"
  }
}
```

## APB slow/error access

1. `apb.query` 查 error/slow findings。
2. 对 finding 的 time/window 用 `value.batch_at` 取 `psel/penable/pready/pslverr/paddr/pwrite`。
3. 需要具体 access 时用 `apb.query` 的 `query.index` / `query.line_limit`；需要窗口上下文时用 `apb.transfer_window`。

## X/Z 传播

1. `detect_abnormal` 查 `unknown_xz`。
2. `signal.changes` 找第一个 X/Z 出现时间。
3. 有 combined 资源时用 `trace.active_driver` 在该时间查生效 driver。
4. 用 `trace.driver` 向上游查询，寻找 X/Z 源。

## Counter / FSM 异常

1. `value.at` 或 `signal.statistics` 确认状态/计数异常。
2. `trace.driver` 获取状态更新来源。
3. `trace.driver` 查更新条件。
4. `source.context` 获取 `file:line` evidence。

## 当前生效 driver join

使用条件：必须有 `daidir + fsdb + signal + time`。

1. 波形侧先定位异常时间。
2. `value.batch_at` 取相关信号。
3. `trace.active_driver` 做 active trace。
4. `resolved`：保留 driver kind、file/line、active_time、control evidence。
5. `control_only`：继续查 control signal 值，不要宣称已解析 direct data driver。
6. `unresolved`：回到 `trace.driver` 或源码 `rg` 缩小信号路径。

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.active_driver",
  "target": {"session_id": "case_a"},
  "args": {
    "signal": "top.u.ready",
    "time": "@stall"
  }
}
```

## 生成波形证据视图

当用户需要给 nWave 打开同一组信号、marker、analog 波形或表达式信号时，用 `rc.generate`。不要让 AI 手写 rc；由 xdebug 校验 FSDB 信号和 marker 时间后生成。

详细配置见 [rc-generate.md](rc-generate.md)。

## APB/AXI 协议查询

**必须先用 config.load 注册信号映射，再进行任何 query/analysis。**

### 前置条件：加载配置

APB 示例（10 信号）：

```json
{
  "api_version": "xdebug.v1",
  "action": "apb.config.load",
  "target": {"session_id": "case_a"},
  "args": {
    "name": "apb0",
    "config": {
      "clock": "top.pclk",
      "reset": {"signal": "top.presetn", "polarity": "active_low"},
      "paddr": "top.u_dut.paddr",
      "psel": "top.u_dut.psel",
      "penable": "top.u_dut.penable",
      "pwrite": "top.u_dut.pwrite",
      "pwdata": "top.u_dut.pwdata",
      "prdata": "top.u_dut.prdata",
      "pready": "top.u_dut.pready",
      "pslverr": "top.u_dut.pslverr"
    }
  }
}
```

AXI 示例（26 信号，5 通道各需 valid/ready + data/addr/id/last/strobe + clk + reset）：

```json
{
  "api_version": "xdebug.v1",
  "action": "axi.config.load",
  "target": {"session_id": "case_a"},
  "args": {
    "name": "axi0",
    "config": {
      "clock": "top.aclk",
      "reset": {"signal": "top.aresetn", "polarity": "active_low"},
      "awvalid": "top.u_dut.awvalid",
      "awready": "top.u_dut.awready",
      "awaddr": "top.u_dut.awaddr",
      "awlen": "top.u_dut.awlen",
      "awsize": "top.u_dut.awsize",
      "awburst": "top.u_dut.awburst",
      "awid": "top.u_dut.awid",
      "wvalid": "top.u_dut.wvalid",
      "wready": "top.u_dut.wready",
      "wdata": "top.u_dut.wdata",
      "wstrb": "top.u_dut.wstrb",
      "wlast": "top.u_dut.wlast",
      "bvalid": "top.u_dut.bvalid",
      "bready": "top.u_dut.bready",
      "bid": "top.u_dut.bid",
      "bresp": "top.u_dut.bresp",
      "arvalid": "top.u_dut.arvalid",
      "arready": "top.u_dut.arready",
      "araddr": "top.u_dut.araddr",
      "arlen": "top.u_dut.arlen",
      "arsize": "top.u_dut.arsize",
      "arburst": "top.u_dut.arburst",
      "arid": "top.u_dut.arid",
      "rvalid": "top.u_dut.rvalid",
      "rready": "top.u_dut.rready",
      "rdata": "top.u_dut.rdata",
      "rresp": "top.u_dut.rresp",
      "rid": "top.u_dut.rid",
      "rlast": "top.u_dut.rlast"
    }
  }
}
```

### 查询

加载后用 `apb.config.list` / `axi.config.list` 确认已注册，然后：

- `apb.query` / `axi.query`：查指定方向、地址或第 N 个传输；第 N 个写 1-based `args.query.index`，前 N 条写 `args.query.line_limit`，不要写旧数量字段。
- `axi.analysis`：查异常（protocol violation、timing outlier 等）。
- `axi.channel_stall`：查通道级停顿热点。
- `axi.latency_outlier`：查延迟异常。
- `axi.outstanding_timeline`：查未完成事务的时间线。

**没有 config.load，query 会报 `MISSING_FIELD: requires args.name or latest config`。** config 字段名以实际代码中的 VIP/DUT 信号名为准，没有自动检测。

APB/AXI query 最小形态：

```json
{
  "api_version": "xdebug.v1",
  "action": "axi.query",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "name": "axi0",
    "direction": "write",
    "query": {
      "index": 1
    }
  }
}
```
