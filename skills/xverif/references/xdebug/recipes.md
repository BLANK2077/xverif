# xdebug 高频 recipes

每条流程都先调用一次 `xverif_tools` 完整发现，再读取选定 action schema。下面是选型，
不是参数替代品。

## Ready 拉低根因

1. `signal.statistics` / `signal.changes` 缩小时间范围。
2. `event.find` 找第一处 valid 且非 ready。
3. 用 `list.load` 注册 valid/ready/full/state 等 leaf signal。
4. 一次 `value.at(list="ready_path", times=[...])` 保存异常前后现场。
5. `trace.driver` / `trace.load` 建立静态因果范围。
6. `trace.active_driver` 或 `trace.active_driver_chain` 找异常时间真正生效的赋值。
7. `window.verify` 证明条件是否持续。

## X 来源

1. `value.at` 确认精确时间和真实位宽的值确含 X。
2. `signal.xz_verify` 证明受限窗口中的 X/Z 状态。
3. `trace.x_origin` 回溯数据和控制候选，区分 query time、X onset 和 active time。
4. 若深度或预算停止，按 frontier 续查；partial 不能当完整根因。

## Valid-ready 与短脉冲

- raw X/Z/glitch/stuck smoke 使用 `signal.anomaly.inspect`；
- raw pulse 是否被 clock edge 看到使用 `signal.sampled_pulse.inspect`；
- transfer、stall、ready-without-valid 和 stalled payload 稳定性使用
  `protocol.handshake.inspect`；
- 可复用接口的长窗口分析先 `stream.config.load`，用 `stream.config.get` 与
  `stream.describe` 确认后再 `stream.query`。

## AXI/APB

先生成 schema-valid config，再用 `axi.config.load` / `apb.config.load` 加载。根据
schema routing hint 选择 query、statistics、latency/outstanding/pending 等 action。
finding 时间的旁路信号统一放入 list，再用 `value.at` 批量读取。

## 波形交付

- 宏观观察：`list.load` → `list.export` → xwaveform render → 回到确定性 action 验证。
- nWave 视图：`nwave.rc.generate`；不要手写 rc。
- 图片不是唯一证据，最终结论保留 action、path、time、value、file:line、完整性字段。
