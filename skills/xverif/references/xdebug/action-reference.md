# xdebug action 使用边界

本页只解释高频选择边界。73 个公开 action 的名称、状态、resource、用途、禁用场景、
替代 action、request schema 和 example 由 canonical registry 生成到
[全量 action 索引](../generated/xdebug-actions.md)。调用前先用 `xverif_tools` 完整发现，
再对选定 action 调用 action-specific schema。

## 值与时间

- `value.at` 同时覆盖单信号、已加载 list、APB、stream、AXI selector；selector
  五选一，时间使用 `time` 或有序不重复的 `times`。
- 多信号先用 `list.load` 加载 schema-valid JSON，再用一次
  `value.at(list="<name>", times=[...])`；不要按信号或时间拆成 batch。
- `signal.changes` / `signal.statistics` 用于受限范围变化和统计；`event.find`
  用于找条件命中点；`window.verify` 用于在已知窗口证明条件。
- `signal.xz_verify` 提供 X/Z 窗口证明；`signal.anomaly.inspect` 是 raw waveform
  smoke scan；`signal.sampled_pulse.inspect` 解释脉冲是否被采样；
  `protocol.handshake.inspect` 检查 valid-ready 协议事实。

## 设计与根因

- `scope.roots` / `scope.list` 确认 hierarchy 和 leaf path。
- `trace.driver` / `trace.load` 给出静态连接；`trace.active_driver` 在精确时间判断
  生效 driver；`trace.active_driver_chain` 沿控制和数据依赖递归；
  `trace.x_origin` 从 X 值回溯候选来源。
- `expr.normalize` 有两个互斥 variant：`expr` 不需要 resource 且禁止 session；
  `signal` 需要 design session。expr-only 的确定性 parser 证据是
  `summary.source=deterministic_syntax_parser` 与
  `summary.confidence=syntax_validated`。

## 配置与协议

- 普通信号组：`list.load` 后用 `list.show` / `list.validate` 确认。
- Stream：`stream.config.load` 后用 `stream.config.get`、`stream.describe` 确认，
  再用 `stream.query`。
- AXI/APB：分别先 `axi.config.load` / `apb.config.load`，再按 schema 选择 query、
  statistics 或 analysis action。
- 配置加载成功后读取 `recommended_actions`，优先使用第一项 `value.at` 保留现场。

## 产物

- `list.export` 为 xwaveform workflow 导出 manifest 和逐信号数据。
- `nwave.rc.generate` 生成 nWave signal list/view rc；不要让 agent 手写 rc。

## 完整性

扫描和有界 collection 只认 canonical 完整性字段：`scan_complete`、
`analysis_complete`、`response_truncated`、`total_count`、`returned_count`、
`truncation_scopes`。action-specific `status:partial` 不能替代这些字段。
