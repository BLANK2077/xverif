# 当前 73 个 action 的重建映射

只读对比结果：`53a9556` 有 75 个 action，`1c3ffc8` 有 73 个 action；其中 57 个名称不变、14 个规范化重命名、2 个真正新增、4 个删除或合并。

## 14 个重命名

| 旧名 | 当前名 |
|---|---|
| `apb.cursor` | `apb.transaction.cursor` |
| `axi.cursor` | `axi.transaction.cursor` |
| `cursor.delete` | `waveform.cursor.delete` |
| `cursor.get` | `waveform.cursor.get` |
| `cursor.list` | `waveform.cursor.list` |
| `cursor.set` | `waveform.cursor.set` |
| `cursor.use` | `waveform.cursor.use` |
| `detect_abnormal` | `signal.anomaly.inspect` |
| `handshake.inspect` | `protocol.handshake.inspect` |
| `list.diff` | `list.first_change` |
| `rc.generate` | `nwave.rc.generate` |
| `sampled_pulse.inspect` | `signal.sampled_pulse.inspect` |
| `stream.show` | `stream.describe` |
| `trace.x` | `trace.x_origin` |

旧名称必须从 registry、schema、examples、help 和 skill 全部删除，不保留 alias。

## 新增、删除与合并

- 新增 `stream.config.get`：读取保存的 Stream config；与解析后定义和信号元数据的 `stream.describe` 分工。
- 新增 `list.load`：严格 config/config_path 加载、append/replace 原子语义。
- 删除 `signal.search`：旧 catalog 已标记 removed，不恢复实现或 alias。
- 删除 `source.context`：不臆测映射到其它 action。
- 删除 `value.batch_at`：多点用途并入统一 `value.at`。
- 删除 `list.value_at`：由 `value.at` 的 list selector 加 time/times 取代。

## 不可随 XOUT 回退的公共合同

- action catalog、当前命名、registry、metadata、help、schema 和 example 闭环。
- ContractBoundRequest、参数消费、未知参数拒绝和 action-specific 条件语义。
- canonical success/error envelope、精确 invalid_arg/details/candidates、完整性与截断字段。
- resource/config、session/batch/internal request 生命周期。
- waveform/protocol/trace 的 JSON evidence 和 LogicValue 语义。
- MCP/SDK-free/LSF 的 schema projection、framing、request id、error 和 readiness。
- xbit、xcov、xentry、xloc、xsva 的 JSON/CLI/MCP 公共合同。
- generator、examples、skills、catalog 和 fixture 一致性门禁。

当前 action 集与公共 schema source 以重建时参考提交 `1c3ffc8` 的 `actions.yaml` 和唯一生成器为准；只从 `53a9556` 借回 XOUT 架构与领域文本布局，不借回旧业务 JSON。
