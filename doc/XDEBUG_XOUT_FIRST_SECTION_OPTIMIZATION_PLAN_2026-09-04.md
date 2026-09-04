# XDEBUG XOUT 第一段精简与证据补齐计划

## 1. 任务目标

在不改变 JSON response、request/response schema、action 业务语义、NPI 数据路径和
XOUT 现有视觉风格的前提下，逐项优化 73 个公开 action 的 XOUT 第一段：

- 第一段只保留回答“本次做了什么、结果是什么、证据是否完整、下一步从哪里继续”
  所需的字段；
- 删除同义、可直接推导、恒定或对当前结论没有帮助的字段；
- 补齐当前被通用 renderer 丢弃的嵌套关键证据，例如导出路径、session 标识和
  `truncation_scopes`；
- 对以查询目标为中心的 action，确保首段先给目标答案，再给全局统计；
- 第一段之后的领域表格、finding、warning、next、common block 和源码证据保持原有
  顺序与格式。

本任务不比较或引入 FST、静态 trace 等替代路线，继续使用当前 NPI/FSDB/daidir
方案。不得运行 fixture prepare，不得删除、覆盖、迁移或重建现有 fixture cache。

## 2. 状态与进度

| 阶段 | 状态 | 产物/证据 |
|---|---|---|
| 基线评审 | 已完成 | 73 个 action 的真实 host/NPI XOUT 已采集并逐条检查 |
| 计划与验收设计 | 进行中 | 本文；Goal 已建立 |
| renderer 设计验证 | 未开始 | 首段边界与字段投影单元测试 |
| 分阶段实现 | 未开始 | 公共首段、专用首段、session/export 补强 |
| 静态与单元验证 | 未开始 | 生成一致性、schema、C++ unit、报告合同 |
| 真实 NPI 验证 | 未开始 | focused suites 与 73-action native XOUT |
| 最终复核 | 未开始 | 逐 action 新旧对照、缓存未变证明、遗留风险 |

进度更新必须写回本节，不另建失去上下文的临时状态文件。

## 3. 已确认基线

- runtime catalog 当前为 73 个公开 action。
- 2026-09-04 在 host 环境运行
  `XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate nightly
  --xverif-suite xdebug.native_xout_all`，结果为 `1 passed, 1403 deselected`。
- 当前 `emit_summary()` 只渲染 scalar；`summary.output`、`requested_range`、
  `scanned_range`、`truncation_scopes` 等嵌套对象/数组不会进入首段。
- generic renderer 不渲染顶层 `session`，因此 `session.open` 首段只有
  `status: opened`，缺少后续调用所需的 session id。
- `axi.export`、`event.export`、`list.export`、`stream.export` 和
  `nwave.rc.generate` 的成功 XOUT 可能报告 written，却不显示实际产物路径。
- `axi.outstanding_timeline`、`axi.request_response_pair`、`signal.changes` 的受限真实
  用例会出现 `response_truncated=true`，但首段没有明确显示
  `truncation_scopes`。
- 当前 native XOUT 测试主要验证 header、少量 required/forbidden token 和值格式，
  尚不能证明首段可用、非冗余或完整性证据充分。

## 4. “第一段”的精确定义

- 普通成功响应：action header 后第一个命名 section，通常是 `summary:`。
- `value.at`：现有专用布局的 `values:` 表格就是第一段，不强制增加 summary。
- error：`@xdebug.error.v1` 后的 action/code/message 是错误首段；本任务只做回归保护，
  不重写错误协议。
- 第一段边界：从首个 section 标题开始，到下一个同级 section 标题前结束。
- 若 action 当前只有一个 section，允许对该 section 精简，但不得因此隐藏唯一业务答案。
- 第一段不是强制结构：若删除后，紧随其后的领域 section 已完整表达结果且不会丢失
  完整性、对象身份、产物路径或不完整原因，则直接删除第一段，让原第二段成为第一段。

## 5. 首段字段选择规则

字段按以下优先级排列；不存在的字段不合成、不推断：

1. **对象身份**：`session_id`、config/list/stream/interface 名、signal/path。
2. **直接结论**：`status`、`verdict`、`healthy`、`found`、`valid`、`written`。
3. **继续操作入口**：实际 output/write/read/meta/manifest path，必要的 mode/transport。
4. **查询范围/采样语义**：只有会改变结论含义时才保留 clock、edge、sample point、
   requested/effective range。
5. **canonical 完整性证据**：适用时保留
   `scan_complete`、`analysis_complete`、`response_truncated`、`total_count`、
   `returned_count`、`truncation_scopes`。
6. **核心统计**：仅保留直接回答当前 action 的计数、峰值、首末时间或 finding 总览。

去重规则：

- `status:written` 与 `output_written:true` 二选一，首段保留 `status` 和实际路径；
- `status:created` 与 `created:true`、`status:deleted` 与 `deleted:true` 二选一；
- `verdict` 与 `all_passed` 表达同一事实时只保留 `verdict`；
- `termination` 与相同文本的 `termination_detail` 只保留一个；
- `row_count`、`total_count`、`returned_count` 值相等且含义相同时，保留 canonical count；
- `full_scan_count:1` 在 `scan_complete:true` 已充分表达完整性时不显示；
- `known:true`、可由 literal 推导的 width/bits，以及完整值诊断中的空数组不进入首段；
- 零值诊断只有在“没有异常”本身就是 action 结论时才保留，否则移到既有后续证据或省略。

整段删除规则：

- success/header 已证明调用成功，第一段若只重复 action 名已表达的 `found/loaded`，且下一段
  直接给出同名完整 config，可删除；
- 第一段若只重复下一段对象的 name/clock/handshake 等字段，可删除；
- 第一段含任一 canonical 完整性字段、session id、output path、verdict、finding 总览或
  下一段无法直接复原的计数时，不得删除；
- 初始删除候选为 `apb.config.list/load`、`axi.config.list/load`、
  `event.config.list/load`、`stream.config.get`、`stream.describe`；
- `actions` 的总数、`schema` 的目标 action/kind、config collection 的 count 仍有助于判断
  响应范围，不因“可以人工数表格”而删除；
- `expr.normalize` 与 `signal.canonicalize` 暂不机械删除：其 parser 来源/confidence、match
  scope 是否可由下一段完全替代，必须通过真实输出逐字段证明后再决定。

## 6. 架构方案

### 6.1 公共 renderer

在 `xdebug/src/api/xout_renderer.cpp` 内把首段渲染拆成可单测的语义投影：

- 仍使用 `TextResponseBuilder` 的 section/kv/table 风格；不引入新的语法或 framing；
- 不建立覆盖 73 个 action 的中央 action-name switch；
- 对 canonical 完整性字段提供固定顺序与结构化渲染，尤其是非空
  `truncation_scopes`；
- 对 `summary.output` 只展开可继续操作的 path/file_format；
- 通过“字段含义 + 值关系”消除通用同义字段，而不是复制 handler 业务逻辑；
- 不修改 response 对象，不向 JSON 写入仅供 XOUT 使用的新字段。

### 6.2 专用 renderer

`value.at`、APB/AXI query、stream.query、event.find、trace 等现有 override 继续保留。
只修改 override 中 header 后的第一段，第二段及其后输出必须保持原顺序和格式。

- `stream.query`：先显示 query、定位条件与 found/index/range，再显示必要流统计；
- `trace.driver/load`：当 `analysis_complete=false` 时，把不完整原因放在同一首段；
- APB/AXI statistics/query：只做 canonical count 和同义字段精简，不改变领域表格。

### 6.3 frontend 内建 action

`session.open/close/doctor` 不经过 engine handler。为它们增加局部、明确的首段投影，
不把每个普通 action 的顶层 session 元数据都塞入 summary：

- open：session_id、mode、transport、资源路径；
- close：removed、被移除 session_id；
- doctor：session_id、healthy、mode/transport，message 仅在补充原因时显示。

### 6.4 明确不做

- 不改 handler 计算、NPI 调用、扫描范围、line limit 或 cache scope；
- 不改 action catalog、请求参数、response schema 和 response example 的 JSON 结构；
- 不让 MCP/adapter 解析或重编码 XOUT；
- 不增加 XOUT_BEGIN/XOUT_END，不恢复可逆 JSON 文本编码；
- 不修改第二段及以后内容来“顺便整理”整份输出；
- 不运行 `--xverif-prepare`，不使用其它 fixture/data source fallback。

## 7. 73 action 首段决策矩阵

状态含义：保留=字段基本合格；精简=删除冗余；补强=增加已存在于 response 的关键证据；
重排=先显示直接答案。矩阵中的字段是首段最小语义集合，不要求 action 不适用的字段。

| # | action | 决策 | 首段必要内容与处理 |
|---:|---|---|---|
| 1 | actions | 精简 | 保留分组与 action 数；无过滤时 `action_count`/`total_action_count` 只留一个 |
| 2 | apb.config.list | 删除首段 | 下一段 config 已含 name 和完整接口；success/header 已表达 found |
| 3 | apb.config.load | 删除首段 | 下一段 config 已含 name 和完整接口；action/header 已表达 load |
| 4 | apb.export | 精简+补强 | name、status、output path/format、canonical completeness；删除同义 row/full-scan 字段 |
| 5 | apb.query | 保留 | name、筛选范围、canonical completeness |
| 6 | apb.statistics | 精简 | name、核心统计、canonical completeness；删除同义 scanned/full-scan 字段 |
| 7 | apb.transaction.cursor | 精简 | cursor op/position；删除 begin 与 at_begin 的重复表达 |
| 8 | apb.transfer_window | 保留 | transfer identity、窗口范围、完整性 |
| 9 | axi.analysis | 精简 | analysis、关键 latency/anomaly 结果、canonical completeness；压缩零诊断 |
| 10 | axi.channel_stall | 保留 | channel、stall 结论/峰值、范围和完整性 |
| 11 | axi.config.list | 删除首段 | 下一段 config 已含 name 和完整接口；success/header 已表达 found |
| 12 | axi.config.load | 删除首段 | 下一段 config 已含 name 和完整接口；action/header 已表达 load |
| 13 | axi.export | 补强+精简 | name、status、write/read/meta path、format、canonical completeness；删除 output_written/row/full-scan 重复 |
| 14 | axi.latency_outlier | 保留 | direction/method、outlier 数、完整性 |
| 15 | axi.outstanding_timeline | 补强 | name、peak/final outstanding、canonical completeness、非空 truncation scopes |
| 16 | axi.query | 精简 | query/direction、找到的目标和 data scope、canonical completeness；长提示后置 |
| 17 | axi.request_response_pair | 补强 | name/范围、pair 数、canonical completeness、非空 truncation scopes |
| 18 | axi.statistics | 精简 | name、核心吞吐/延迟统计、canonical completeness；去同义计数 |
| 19 | axi.transaction.cursor | 精简 | cursor op/position；删除边界状态重复 |
| 20 | batch | 保留 | 请求总数、成功/失败总览 |
| 21 | counter.statistics | 补强 | signal/counter、edge/effective sample point、核心统计、完整性 |
| 22 | event.config.list | 删除首段 | 下一段 config 已含 name/clock/edge；单条查询无需重复 found |
| 23 | event.config.load | 删除首段 | 下一段 config 已含 name/clock/edge；action/header 已表达 load |
| 24 | event.export | 补强+精简 | name、status、output path/format、sampling identity、canonical completeness；去同义 row/output 字段 |
| 25 | event.find | 补强 | name/expression、edge/sample point、first/last/范围、canonical completeness |
| 26 | expr.eval_at | 精简 | expression/time 与明确 value/verdict；避免含义不清的 `status:true` |
| 27 | expr.normalize | 保留 | normalized expression 与有效性 |
| 28 | list.add | 精简 | list/signal 与单一 added 结论 |
| 29 | list.create | 精简 | name/signal count 与单一 created 结论 |
| 30 | list.delete | 保留 | list/index 与删除结论 |
| 31 | list.export | 补强+精简 | name、status、path/manifest、format、canonical completeness；去 row/output 重复 |
| 32 | list.first_change | 补强 | list、range、first change、canonical completeness |
| 33 | list.load | 保留 | loaded lists/signals、mode |
| 34 | list.show | 保留 | name、signal count |
| 35 | list.validate | 补强 | name、valid/all_found、total/found/missing 数 |
| 36 | nwave.rc.generate | 补强 | valid/written、output rc path、group/signal count；输入 config path 仅作来源 |
| 37 | protocol.handshake.inspect | 补强 | valid/ready/clock、edge/sample point、handshake/stall 数、完整性 |
| 38 | schema | 精简 | action/kind 与参数导航；仅在有条件差异时保留 response detail |
| 39 | scope.list | 精简 | path/level/kind、canonical counts/completeness；省略空 include/exclude |
| 40 | scope.roots | 保留 | source、root count、完整性 |
| 41 | session.close | 补强 | removed 与 removed session_id/mode |
| 42 | session.doctor | 补强 | session_id、healthy、mode/transport；正常时不重复固定 message |
| 43 | session.gc | 保留 | policy、removed/kept counts |
| 44 | session.list | 保留 | session count 与 verbose/filter 上下文 |
| 45 | session.open | 补强 | status、session_id、mode、transport、daidir/fsdb 中实际资源 |
| 46 | signal.anomaly.inspect | 补强 | signals/checks、finding count/最高 severity/总体状态、完整性 |
| 47 | signal.canonicalize | 保留 | requested 与 canonical signal、ambiguity |
| 48 | signal.changes | 补强 | signal/range、actual transition count、canonical completeness、非空 truncation scopes |
| 49 | signal.resolve | 保留 | signal、resolved identity/type |
| 50 | signal.sampled_pulse.inspect | 补强 | clock/valid、edge/sample point、pulse 结论与完整性 |
| 51 | signal.stability | 保留 | signal/range、stable/verdict、变化证据和完整性 |
| 52 | signal.statistics | 补强 | signal/clock、edge/sample point、核心 cycle 统计和完整性 |
| 53 | signal.xz_verify | 精简 | signal/range、expected/observed/verdict、canonical completeness；去同义 checked/total/returned |
| 54 | stream.config.get | 删除首段 | 下一段 stream 已含 name 和完整配置 |
| 55 | stream.config.list | 保留 | stream count/filter |
| 56 | stream.config.load | 保留 | mode、loaded/replaced counts、推荐动作 |
| 57 | stream.describe | 删除首段 | 下一段 config 已覆盖 stream/clock/handshake/packet 配置 |
| 58 | stream.export | 补强+精简 | stream/kind、status、path/meta/format、canonical completeness；不在首段铺满协议统计 |
| 59 | stream.query | 重排+精简 | query、packet/index/range/found 先于全局流统计；只留解释目标所需统计与完整性 |
| 60 | stream.validate | 保留 | stream、valid、主要 violation counts、完整性 |
| 61 | trace.active_driver | 精简 | signal/time/value、termination；相同 termination_detail 删除 |
| 62 | trace.active_driver_chain | 精简 | signal/time/value、termination、hop/ambiguity 总览；删除重复 detail |
| 63 | trace.driver | 补强 | signal/mode、canonical completeness；不完整时同段给 reason/scope |
| 64 | trace.load | 补强 | signal/mode、canonical completeness；不完整时同段给 reason/scope |
| 65 | trace.x_origin | 保留 | signal/time/value、origin/termination、完整性 |
| 66 | value.at | 保留 | 继续使用直接 values 矩阵，不新增 summary |
| 67 | verify.conditions | 精简 | time/clock、verdict、failed/total；删除同义 all_passed |
| 68 | waveform.cursor.delete | 精简 | name 与单一 deleted 结论 |
| 69 | waveform.cursor.get | 保留 | name/time/found |
| 70 | waveform.cursor.list | 保留 | cursor count/active cursor |
| 71 | waveform.cursor.set | 保留 | name/time/status |
| 72 | waveform.cursor.use | 精简 | active cursor；删除 status/active_cursor 同义表达 |
| 73 | window.verify | 补强+精简 | range/clock/edge/sample point、verdict、failed/total、完整性；删除 all_passed 重复 |

## 8. 分阶段实施与提交边界

### 阶段 A：计划与测试护栏

- 提交本计划书；
- 为首段边界、字段顺序、同义去重、嵌套 output、truncation scopes 建立 C++ unit；
- 扩展 native XOUT case 元数据，使每个 action 能声明首段 required/forbidden token；
- 增加“仅首段可变化”的 suffix 保护方法，对选定专用 renderer 固定第二段以后输出。

### 阶段 B：公共首段投影

- 实现 canonical 完整性字段和嵌套对象输出；
- 实现可证明等价的通用去重；
- 先覆盖 generic renderer 的 export、anomaly、signal 与配置类 action；
- 单独提交，便于从专用 renderer 问题中隔离。

### 阶段 C：session/export 关键闭环

- 补齐 session.open/close/doctor；
- 补齐五类 export/rc output path；
- 验证路径与 response 中的 canonical path 完全一致，不根据 request 猜测。

### 阶段 D：专用 renderer 首段

- 调整 stream.query、trace.driver/load 及确有需要的 APB/AXI/event override；
- 每次只改首段，使用 suffix 测试保护领域表格；
- 不将专用领域逻辑下沉到公共 renderer。

### 阶段 E：73-action 真实验证与最终复核

- 消费现有缓存运行 native XOUT 全矩阵；
- 对每个 action 生成首段 before/after 与 token/line 统计；
- 人工复核补强字段真实可继续操作、删除字段可推导且不损失结论；
- 更新本文状态、测试证据、缓存保护证据和遗留风险。

每阶段提交前必须验证 staged path 精确等于本任务白名单，避免把当前工作树中的既有
改动带入提交。commit message 使用中文并写明动机、范围和验证。

## 9. 测试方案

所有 focused suite 先通过 catalog/`--xverif-plan` 核对 gate membership。真实 NPI、
FSDB、daidir 测试统一设置 `XVERIF_TEST_EXECUTION_ENV=host`。

### 9.1 静态与生成一致性

- `sync_runtime_request_schemas.py --check`
- `sync_response_schemas.py --check`
- `sync_action_schema_hints.py --check`
- `audit_runtime_schema_compatibility.py`
- `validate_schema.py`
- `validate_examples.py`

即使预期 schema 无改动，也用这些检查证明没有公共合同漂移。使用仓库
`.conda-xverif/bin/python`，不使用依赖不完整的系统 Python。

### 9.2 单元与纯报告测试

- `xdebug.cpp_unit`：覆盖公共和专用首段渲染；
- `xdebug.native_xout_report`：覆盖 73-action 报告、首段 required/forbidden 和 suffix
  保护合同；
- `xdebug.static`：覆盖 catalog/schema/source 静态一致性；
- 必要时 `skills.xverif`：若文档中的 XOUT 合同需要同步才运行并安装核对；不无故修改 skill。

### 9.3 真实 NPI focused suites

- `xdebug.contract`：CLI/action response 与错误合同；
- `xdebug.session`：open/close/doctor 首段与生命周期；
- `xdebug.stream`：stream.query/export/validate 专用布局；
- `xdebug.counter_statistics`、`xdebug.synthetic_existing`、`xdebug.xif_event`：受影响 waveform/event/trace 行为；
- `xdebug.apb_vip`、`xdebug.axi_vip`：协议 query/statistics/export 首段；
- `xdebug.native_xout_all`：73 primary、保护用例、error、value-format 全矩阵最终验收。

### 9.4 回归层级

- 先跑受影响 focused suites，再跑 fast gate；
- focused 全部通过后跑 host regression；
- `xdebug.native_xout_all` 属于 nightly，最终单独运行；若本任务风险评估要求全仓 nightly，
  只消费现有缓存运行，不触发 prepare；
- cache miss 是阻塞，不得自动 prepare、降级 gate、换 fixture 或转用 mock。

## 10. 验收标准

### 功能与输出

1. 73 个 action 均有首段 expected/forbidden 断言，且本矩阵逐条关闭。
2. 对首段删除候选，删除后原第二段成为第一段且具备自解释性；测试禁止残留空 summary。
3. 首段保留直接结论、必要身份、继续操作入口和适用的 canonical 完整性证据。
4. `response_truncated=true` 时 XOUT 明确显示非空 `truncation_scopes`；不可作全量结论。
5. `session.open` 可直接取得 session_id；close/doctor 可识别目标 session。
6. 所有成功写文件 action 显示 canonical output path；多产物导出显示必要子路径。
7. `stream.query packet_at` 首先显示被请求 packet 的 found/index/range，再显示必要统计。
8. `trace.driver/load analysis_complete=false` 时首段同时显示不完整原因。
9. 同义字段对不再同时出现；删除字段必须能由保留字段直接推导或确认与结论无关。
10. 第一段之外的领域证据、表格顺序和格式无非预期变化。
11. JSON response、schema 和 examples 的结构化合同零漂移。

### 质量与测试

1. 生成一致性、runtime compatibility、schema/example validation 全部通过。
2. C++ unit、native XOUT report contract、xdebug contract 和受影响 focused suites 通过。
3. 73-action native XOUT 最终阶段全通过，并产出逐 action review 报告。
4. error cases 与 value_format bin/dec/X/Z 保护无回归。
5. 真实测试明确记录 host 环境、结果目录和通过/失败/阻塞计数。

### 缓存与工作树保护

1. 全程不运行任何 `--xverif-prepare` 或 fixture 构建入口。
2. 测试前后记录 `.xverif-test-cache` 的入口/manifest 指纹快照；允许正常读取时间变化，
   不允许版本、目标、manifest 内容或目录拓扑被本任务改变。
3. 不删除或清理 cache/result；每次测试使用新的 result 目录。
4. 不回滚、覆盖、暂存或提交任务开始前已存在的用户改动。

## 11. 风险与控制

- **过度精简**：首段变短但失去否定结论依据。控制：每个删除字段写明可推导来源，
  对 finding/zero diagnostic 保留 action 级例外。
- **伪完整**：显示 `response_truncated` 却遗漏范围。控制：完整性六字段形成组合测试；
  incomplete/truncated case 必须使用真实受限请求。
- **专用布局被公共逻辑污染**：控制：handler_xout 仍优先透传，公共 renderer 不覆盖它；
  suffix 回归保护第二段以后。
- **路径来自 request 而非结果**：控制：只投影 response 已发布的 canonical output 对象。
- **缓存误写/重建**：控制：不调用 prepare；测试前后快照；cache miss 直接报告阻塞。
- **共享工作树误提交**：控制：每阶段提交前比较 staged path 与白名单；发现额外 staged
  文件立即停止提交并协调，不修改其 index/worktree 状态。

## 12. 交付物

- 本计划与持续进度记录；
- renderer/专用首段的最小源码修改；
- 73-action 首段合同测试与真实 XOUT review report；
- 生成一致性、单元、focused、regression/nightly 验证记录；
- 最终中文评审报告：逐 action 结论、before/after、删减理由、遗留风险与缓存保护结果。
