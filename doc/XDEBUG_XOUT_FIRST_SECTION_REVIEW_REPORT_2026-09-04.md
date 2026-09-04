# XDEBUG XOUT 第一段逐 action 评审报告

## 1. 结论

本轮完成 73 个公开 action 的 XOUT 第一段逐条评审和实现。最终方案保持现有 section、
key/value、table 与 action header 风格，只改变第一段的字段投影；JSON response、schema、
NPI/FSDB 查询、扫描边界和第二段以后领域证据不变。

- 8 个 action 的 summary 对使用没有帮助，已整段删除：`apb.config.list/load`、
  `axi.config.list/load`、`event.config.list/load`、`stream.config.get`、
  `stream.describe`。原 `config` 或 `stream` 段直接成为第一段，无空 summary。
- `value.at` 继续由 `values` 表格直接作为第一段，不新增 summary。
- 其余 64 个 action 保留第一段，但只投影必要身份、直接结论、继续操作入口、查询语义、
  canonical 完整性和直接回答问题的统计。
- 导出 action 可直接取得 canonical output path；session open/doctor/close 可直接取得
  session identity；truncated/incomplete 响应保留状态与 scope。
- 删除 `output_written`、`all_passed`、相同 `termination_detail`、同义
  `checked_value_count`、可由完整性直接推导的 `full_scan_count` 等重复表达。

最终真实报告统计为 73/73 primary 成功、179 次调用、布局 review 失败 0；73 个 primary
XOUT 合计 73,195 bytes。此前公共投影首轮实现样本为 75,809 bytes，第二轮 action 级投影
继续减少 2,614 bytes；该数字不冒充改造前基线，只用于证明逐 action 复核仍有实际收敛。

## 2. 逐 action 评审

“删除”表示原 summary 整段删除；“直出”表示本来就以领域表格作为第一段；其余均为
保留 summary 后的最小必要字段合同。每行均由 `FIRST_SECTION_REQUIRED` 和真实 native
XOUT 验证，不是仅凭 schema 静态推断。

| # | action | 最终处理 | 第一段必要内容/理由 | 验收 |
|---:|---|---|---|---|
| 1 | `actions` | 精简 | `action_count`；默认不重复 total/false flags | PASS |
| 2 | `apb.config.list` | 删除 | `config` 已完整给出 name/interface | PASS |
| 3 | `apb.config.load` | 删除 | `config` 已完整证明加载结果 | PASS |
| 4 | `apb.export` | 精简+补强 | name/status/output、scan completeness/count | PASS |
| 5 | `apb.query` | 保留 | name、scan completeness/count | PASS |
| 6 | `apb.statistics` | 精简 | name、analysis completeness/count | PASS |
| 7 | `apb.transaction.cursor` | 精简 | op/index/count；不重复边界布尔值 | PASS |
| 8 | `apb.transfer_window` | 保留 | name、total/returned count | PASS |
| 9 | `axi.analysis` | 精简 | analysis、min/p95、analysis completeness | PASS |
| 10 | `axi.channel_stall` | 保留 | channel、stall、analysis completeness | PASS |
| 11 | `axi.config.list` | 删除 | `config` 已完整给出 name/interface | PASS |
| 12 | `axi.config.load` | 删除 | `config` 已完整证明加载结果 | PASS |
| 13 | `axi.export` | 精简+补强 | status、data/meta path、analysis completeness | PASS |
| 14 | `axi.latency_outlier` | 保留 | candidate/total/returned count | PASS |
| 15 | `axi.outstanding_timeline` | 补强 | read/write peak、analysis completeness | PASS |
| 16 | `axi.query` | 精简 | name/query mode、analysis completeness | PASS |
| 17 | `axi.request_response_pair` | 补强 | name/count、analysis completeness | PASS |
| 18 | `axi.statistics` | 精简 | name/count、analysis completeness | PASS |
| 19 | `axi.transaction.cursor` | 精简 | op/index/count；不重复边界布尔值 | PASS |
| 20 | `batch` | 保留 | count/all_ok/failed_count | PASS |
| 21 | `counter.statistics` | 补强 | min/max value、analysis completeness | PASS |
| 22 | `event.config.list` | 删除 | `config` 已完整给出 name/clock | PASS |
| 23 | `event.config.load` | 删除 | `config` 已完整证明加载结果 | PASS |
| 24 | `event.export` | 精简+补强 | status/output path、analysis completeness | PASS |
| 25 | `event.find` | 补强 | mode/first/last、analysis completeness | PASS |
| 26 | `expr.eval_at` | 精简 | expr/time/status | PASS |
| 27 | `expr.normalize` | 保留 | expr/confidence；下段不能完整替代 parser 结论 | PASS |
| 28 | `list.add` | 精简 | status/name/signal | PASS |
| 29 | `list.create` | 精简 | status/name/signal_count | PASS |
| 30 | `list.delete` | 保留 | name/deleted | PASS |
| 31 | `list.export` | 精简+补强 | status/data path/manifest path | PASS |
| 32 | `list.first_change` | 补强 | name/changed count/diff_found | PASS |
| 33 | `list.load` | 保留 | loaded/mode | PASS |
| 34 | `list.show` | 保留 | name/signal_count | PASS |
| 35 | `list.validate` | 补强 | name/all_found | PASS |
| 36 | `nwave.rc.generate` | 补强 | written/valid/canonical output path | PASS |
| 37 | `protocol.handshake.inspect` | 补强 | transfer count、analysis completeness | PASS |
| 38 | `schema` | 精简 | action/kind/schema path | PASS |
| 39 | `scope.list` | 精简 | path/kind/total/returned count | PASS |
| 40 | `scope.roots` | 补强 | recommended、analysis completeness/count | PASS |
| 41 | `session.close` | 补强 | removed/session_id | PASS |
| 42 | `session.doctor` | 补强 | healthy/session_id；正常时不铺资源长路径 | PASS |
| 43 | `session.gc` | 保留 | removed/kept count | PASS |
| 44 | `session.list` | 保留 | session_count | PASS |
| 45 | `session.open` | 补强 | status/session_id/mode/transport/资源 | PASS |
| 46 | `signal.anomaly.inspect` | 补强 | finding count/highest severity/completeness | PASS |
| 47 | `signal.canonicalize` | 保留 | status/query/match_count；保留歧义判断入口 | PASS |
| 48 | `signal.changes` | 补强 | signal/actual transitions/completeness | PASS |
| 49 | `signal.resolve` | 保留 | query/total/returned count | PASS |
| 50 | `signal.sampled_pulse.inspect` | 补强 | unsampled pulse count/completeness | PASS |
| 51 | `signal.stability` | 保留 | stable/completeness/count | PASS |
| 52 | `signal.statistics` | 补强 | signal/sample_count/completeness | PASS |
| 53 | `signal.xz_verify` | 精简 | signal/expected state/verdict | PASS |
| 54 | `stream.config.get` | 删除 | `stream` 已完整给出 name/clock/config | PASS |
| 55 | `stream.config.list` | 保留 | count | PASS |
| 56 | `stream.config.load` | 保留 | loaded/mode | PASS |
| 57 | `stream.describe` | 删除 | `config` 已完整给出 stream 定义 | PASS |
| 58 | `stream.export` | 精简+补强 | status/data/meta path/completeness | PASS |
| 59 | `stream.query` | 重排+精简 | query/found/packet index 优先，随后 completeness | PASS |
| 60 | `stream.validate` | 保留 | stream/ok/completeness | PASS |
| 61 | `trace.active_driver` | 精简 | signal/time/termination/completeness | PASS |
| 62 | `trace.active_driver_chain` | 精简 | signal/time/termination/completeness | PASS |
| 63 | `trace.driver` | 补强 | signal/completeness/truncation scope | PASS |
| 64 | `trace.load` | 补强 | signal/completeness/truncation scope | PASS |
| 65 | `trace.x_origin` | 保留 | signal/time/termination/completeness | PASS |
| 66 | `value.at` | 直出 | `values` 表格；summary 无助于使用 | PASS |
| 67 | `verify.conditions` | 精简 | verdict/condition_count/failed | PASS |
| 68 | `waveform.cursor.delete` | 精简 | name/status | PASS |
| 69 | `waveform.cursor.get` | 保留 | name/time/status | PASS |
| 70 | `waveform.cursor.list` | 保留 | cursor_count/active_cursor | PASS |
| 71 | `waveform.cursor.set` | 保留 | name/time/status | PASS |
| 72 | `waveform.cursor.use` | 精简 | active_cursor/time | PASS |
| 73 | `window.verify` | 精简+补强 | verdict/proof range/analysis completeness | PASS |

## 3. 实现边界

- `TextResponseBuilder` 统一渲染嵌套 output、紧凑 range、truncation scopes、session
  identity 与可证明的同义去重。
- `EngineActionHandler` 提供 `project_xout_summary()` 和
  `include_xout_summary()`；领域 handler 只选择本 action 的首段字段。
- config/get/describe 的 8 个 handler 显式关闭 summary；没有用空 section 或特殊
  framing 伪装删除。
- `stream.query` 只重排首段副本，packet/row 等后续领域输出继续使用原 renderer。
- JSON response 对象没有被修改，生成 schema 与 examples 检查全部无漂移。

## 4. 验证结果

| 层级 | 结果 | 证据目录/说明 |
|---|---|---|
| C++ unit | PASS | `20260904-120740-t10zc5pw` |
| static | 123 PASS | `20260904-121125-c95mpm2r` |
| native XOUT report | 11 PASS | `20260904-121125-gek9rym5` |
| contract | 116 PASS | `20260904-121309-gzessx44` |
| session | 39 PASS | `20260904-121525-0nl0voxo` |
| stream | 2 PASS | `20260904-121658-l3ta1s7m` |
| counter statistics | 1 PASS | `20260904-121745-43t31bhk` |
| synthetic existing | 2 PASS | `20260904-121751-70luh3u4` |
| XIF event | 2 PASS | `20260904-121807-xb5rt1ei` |
| APB VIP | 1 PASS | `20260904-121820-1ybxn43t` |
| AXI VIP | 1 PASS | `20260904-121833-jbdas5j8` |
| xverif skill | 16 PASS | `20260904-121928-d8kme_xi`；两处安装目录同步无差异 |
| final native 73-action | PASS | `20260904-122100-u_gvsdc8`；73 primary/179 calls/0 layout failures |
| fast gate | 649 PASS, 1 FAIL | 唯一失败来自既有未跟踪 wave-mcp 报告中的本机路径 |
| full regression | 未启动 | preflight 缺 `xdebug.stream_differential_tool` cache；按约束未 prepare |

此外，runtime request、response schema、action hint 三项同步检查、Draft-7 runtime
compatibility audit、283 schema validation、231 examples 与 8 个 invalid witnesses 均通过。

## 5. 缓存与工作树保护

- 全程未运行 `--xverif-prepare`，没有切换 fixture、backend、transport 或数据源。
- 测试前后各有 316 个 `current.json/manifest.json`；两份逐文件 SHA-256 清单的聚合哈希
  均为 `f1c5587b44e720a439e850711e1471f21e1d6e4877f11598b2907ad7f02e48aa`，
  `cmp=0`。
- 未删除 cache/result，未暂存或提交任务开始前的用户改动。

## 6. 遗留风险

- 完整 regression 尚无可用结论，唯一阻塞是既有 differential tool fixture cache miss。
  本任务禁止重建缓存，因此没有通过 prepare 消除阻塞。
- fast gate 的本机路径失败属于任务前未跟踪文档，不是 XOUT 回归；该文件没有被本任务
  修改。若要取得全绿全仓门禁，需要由其 owner 单独处理路径脱敏。
- XOUT 是不可逆语义投影；程序需要稳定字段全集时仍应显式使用 JSON，不应反解析首段。
