# xdebug Action Inventory

本文件冻结当前 `xdebug.v1` public action 清单，供 ActionSpec、schema、
example 和 contract test 迁移使用。状态定义：

| status | 含义 |
| --- | --- |
| `stable` | 已实现，默认可给 agent 使用，contract drift 必须被测试挡住 |
| `experimental` | 已实现但字段或行为仍可能调整，agent 不应默认优先使用 |

public catalog 只允许 `stable` 和 `experimental`。其它 status 都是 catalog
contract error，不表示存在兼容入口。

资源需求定义：

| resource | 含义 |
| --- | --- |
| `none` | 不需要 `target` 资源 |
| `design` | 需要 `target.daidir` 或包含 design 的 `session_id` |
| `waveform` | 需要 `target.fsdb` 或包含 waveform 的 `session_id` |
| `combined` | 需要 `target.daidir` + `target.fsdb`，或包含两者的 session |
| `session` | 主要操作 top-level session registry |
| `any` | `target.daidir`、`target.fsdb` 或两者至少一个 |

## Builtin / Session / Combined

| action | category | status | resource | implementation | test |
| --- | --- | --- | --- | --- | --- |
| `schema` | builtin | stable | none | top-level catalog | regression |
| `actions` | builtin | stable | none | top-level catalog | regression |
| `batch` | builtin | stable | none | top-level dispatcher | partial |
| `session.open` | session | stable | any | dispatcher + backend session managers | regression |
| `session.list` | session | stable | none | unified engine session registry | partial |
| `session.doctor` | session | stable | session | dispatcher + backend health | partial |
| `session.close` | session | stable | session | strict `target.session_id` graceful/force close path | partial |
| `session.gc` | session | stable | none | dispatcher + waveform gc | partial |
| `trace.active_driver` | combined | stable | combined | unified engine handler + combined helper | regression |
| `trace.active_driver_chain` | combined | stable | combined | unified engine handler + combined helper | partial |
| `trace.x_origin` | combined | experimental | combined | unified engine handler + per-branch X-onset DFS | regression |

## Design Actions

| action | category | status | resource | implementation | test |
| --- | --- | --- | --- | --- | --- |
| `trace.driver` | design | stable | design | design engine forward | regression |
| `trace.load` | design | stable | design | design engine forward | partial |
| `signal.resolve` | design | stable | design | design engine forward | partial |
| `signal.canonicalize` | design | stable | design | design engine forward | partial |
| `expr.normalize` | design | stable | none | design engine forward | partial |

## Waveform Actions

| action | category | status | resource | implementation | test |
| --- | --- | --- | --- | --- | --- |
| `waveform.cursor.set` | waveform | stable | waveform | waveform engine forward | partial |
| `waveform.cursor.get` | waveform | stable | waveform | waveform engine forward | partial |
| `waveform.cursor.list` | waveform | stable | waveform | waveform engine forward | partial |
| `waveform.cursor.delete` | waveform | stable | waveform | waveform engine forward | partial |
| `waveform.cursor.use` | waveform | stable | waveform | waveform engine forward | partial |
| `scope.list` | waveform | stable | any | unified engine forward | regression |
| `scope.roots` | waveform | stable | any | waveform engine forward | targeted |
| `nwave.rc.generate` | waveform | stable | waveform | waveform engine forward | partial |
| `value.at` | waveform | stable | waveform | waveform engine forward | regression |
| `list.create` | waveform | stable | waveform | waveform engine forward | partial |
| `list.load` | waveform | stable | waveform | waveform engine forward | regression |
| `list.add` | waveform | stable | waveform | waveform engine forward | partial |
| `list.delete` | waveform | stable | waveform | waveform engine forward | partial |
| `list.show` | waveform | stable | waveform | waveform engine forward | partial |
| `list.validate` | waveform | stable | waveform | waveform engine forward | partial |
| `list.first_change` | waveform | stable | waveform | waveform engine forward | partial |
| `list.export` | waveform | stable | waveform | waveform engine forward | targeted |
| `apb.config.load` | waveform | stable | waveform | waveform engine forward | partial |
| `apb.config.list` | waveform | stable | waveform | waveform engine forward | partial |
| `apb.query` | waveform | stable | waveform | waveform engine forward | regression |
| `apb.statistics` | waveform | stable | waveform | waveform engine forward | regression |
| `apb.transaction.cursor` | waveform | stable | waveform | waveform engine forward | partial |
| `axi.config.load` | waveform | stable | waveform | waveform engine forward | partial |
| `axi.config.list` | waveform | stable | waveform | waveform engine forward | partial |
| `axi.query` | waveform | stable | waveform | waveform engine forward | regression |
| `axi.statistics` | waveform | stable | waveform | waveform engine forward | regression |
| `axi.transaction.cursor` | waveform | stable | waveform | waveform engine forward | partial |
| `axi.analysis` | waveform | stable | waveform | waveform engine forward | regression |
| `axi.export` | waveform | stable | waveform | waveform engine forward | targeted |
| `event.config.load` | waveform | stable | waveform | waveform engine forward | partial |
| `event.config.list` | waveform | stable | waveform | waveform engine forward | partial |
| `event.find` | waveform | stable | waveform | waveform engine forward | partial |
| `event.export` | waveform | stable | waveform | waveform engine forward | regression |
| `verify.conditions` | waveform | stable | waveform | waveform engine forward | regression |
| `expr.eval_at` | waveform | stable | waveform | waveform engine forward | partial |
| `window.verify` | waveform | stable | waveform | waveform engine forward | partial |
| `signal.changes` | waveform | stable | waveform | waveform engine forward | regression |
| `signal.stability` | waveform | stable | waveform | waveform engine forward | partial |
| `signal.statistics` | waveform | stable | waveform | waveform engine forward | regression |
| `signal.xz_verify` | waveform | experimental | waveform | waveform engine forward | regression |
| `counter.statistics` | waveform | stable | waveform | waveform engine forward | targeted |
| `signal.sampled_pulse.inspect` | waveform | experimental | waveform | waveform engine forward | partial |
| `signal.anomaly.inspect` | waveform | stable | waveform | waveform engine forward | partial |
| `protocol.handshake.inspect` | waveform | stable | waveform | waveform engine forward | regression |
| `axi.channel_stall` | waveform | experimental | waveform | waveform engine forward | partial |
| `axi.outstanding_timeline` | waveform | experimental | waveform | waveform engine forward | partial |
| `axi.request_response_pair` | waveform | experimental | waveform | waveform engine forward | partial |
| `axi.latency_outlier` | waveform | experimental | waveform | waveform engine forward | partial |
| `apb.transfer_window` | waveform | experimental | waveform | waveform engine forward | partial |
| `stream.config.load` | waveform | stable | waveform | waveform engine forward | synthetic |
| `stream.config.list` | waveform | stable | waveform | waveform engine forward | synthetic |
| `stream.describe` | waveform | stable | waveform | waveform engine forward | synthetic |
| `stream.config.get` | waveform | stable | waveform | waveform engine forward | synthetic |
| `stream.validate` | waveform | stable | waveform | waveform engine forward | synthetic |
| `stream.query` | waveform | stable | waveform | waveform engine forward | synthetic |
| `stream.export` | waveform | stable | waveform | waveform engine forward | synthetic |
