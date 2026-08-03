# xdebug Schema 与合同校验

xdebug public API 以 action-specific schema 为 source of truth。任何文档、skill、runtime、MCP wrapper 都必须服从 schema。

## Source of Truth

核心文件：

- `xdebug/specs/actions/actions.yaml`
- `xdebug/schemas/v1/actions/*.request.schema.json`
- `xdebug/schemas/v1/actions/*.response.schema.json`
- `xdebug/schemas/v1/internal/engine.request.schema.json`
- `xdebug/schemas/v1/internal/engine.request.manifest.json`
- `xdebug/schemas/v1/internal/actions/*.request.schema.json`
- `xdebug/schemas/v1/internal/helper-actions/*.request.schema.json`
- `xdebug/examples/requests/*.json`
- `xdebug/examples/responses/*.json`

辅助生成/校验：

- `xdebug/tools/sync_runtime_request_schemas.py`
- `xdebug/tools/sync_internal_request_schema.py`
- `xdebug/tools/sync_value_response_schemas.py`
- `xdebug/tools/sync_axi_response_schemas.py`
- `xdebug/tools/sync_protocol_statistics_response_schemas.py`
- `xdebug/tools/sync_action_schema_hints.py`
- `xdebug/tools/audit_runtime_schema_compatibility.py`
- `xdebug/tools/validate_schema.py`
- `xdebug/tools/validate_examples.py`
- `xdebug/tools/audit_action_schema_coverage.py`
- `xdebug/tools/check_action_contract.py`

## Request Schema 要求

虽然 checked-in schema 声明 Draft 2020-12，frontend/engine 的 embedded
third-party validator 在运行时按 Draft-7 兼容子集编译 request schema。request 不得
使用 `$dynamicRef`、`unevaluatedProperties`、`prefixItems`、`dependentSchemas` 等未
确认支持的后期关键字；提交前运行 `audit_runtime_schema_compatibility.py`。response
schema 不进入 runtime request validator，但仍须经 example/contract 校验。

public request 进入 engine 时使用同源生成的 internal contract。完整 aggregate schema
保留作全量审计；runtime 根据 generated manifest 选择单 action schema，避免每个短命
helper 解析和编译整个 action union。仅已有 live session 的纯 `server_forward` 路径可先
使用严格 helper envelope，再由 server 对 args/target 执行完整 action 校验；session
不可达或发送前失败时 helper 必须补做完整校验，保持 schema 错误优先级。manifest、
aggregate、单 action schema 与 helper envelope 必须由
`sync_internal_request_schema.py` 一次生成并以 `--check` 验收，禁止手改投影产物。

每个 public action 必须有独立 request schema。

要求：

- `action` enum 只包含该 action。
- `target`、`args`、`limits`、`output` 的字段边界清晰。
- required/anyOf 表达真实必填语义。
- enum 与 runtime 分支一致。
- 默认 `additionalProperties:false`。
- 合同字段不使用多个同义别名。

常见标准字段：

- session：`target.session_id`
- 单点时间：`args.time`
- 时间窗口：`args.time_range.begin/end`
- 数量限制：以 action-specific schema 为准。通用窗口/统计常用 `args.line_limit`；APB/AXI query 使用 `args.query.line_limit` / `args.query.index`；active-driver 链深度使用 top-level `limits.max_depth`。
- stream 名称：`args.stream`
- AXI/APB direction：以 action-specific schema 为准；`axi.query` 接受 `read/write`，
  `apb.query` 接受 `read/write/all` 且默认 `all`，cursor/analysis 等 action 按各自
  schema 决定是否接受 `all`。
- APB signal mapping：`apb.config.load.args.config` 必须包含 `PREADY` 和 `PSLVERR`；
  schema 与 handler 都不得在缺失时假设 zero-wait 或 no-error。协议 config 的严格 shape
  必须在 `sync_runtime_request_schemas.py` 使用 action-specific template 生成，不能复用
  第一个同名 `config` 参数的通用 shape。
- 导出路径：`output.path`

特殊收紧合同：

- `line_limit` 只能限制 response/XOUT evidence，不得改变聚合、verdict 或扫描窗口。
- 需要限制扫描时使用 action-specific `max_samples`；`event.export` 的文件/聚合事件预算使用 `max_events`。预算耗尽必须返回 `analysis_complete:false`、`scan_complete:false` 和明确 `truncation_scopes`。
- 参数只在部分 mode 生效时，request schema 用条件约束收紧，并在 handler 再做语义校验；禁止接受后静默忽略。例如 `event.find(first/last)` 不接受 `line_limit`，`axi.analysis` 仅 `pending` 接受 `line_limit`。
- schema 生成器中的 `EXTRA_ARGS_BY_ACTION` 与 action-specific override 是公开参数白名单；修改生成产物时必须同时修改生成器，避免下一次同步回退。

- `list.export` 输入格式只允许 `args.format:"u64bin"`；manifest/response 可使用版本化 `u64bin.v1`。
- `stream.export.args.kind` 只允许 `transfer`、`packet`、`packet_beats`，不能写 `beats`。
- Stream 命名逐拍字段只允许 `beat_fields`；`data_fields` 已从 schema 和 runtime 删除，
  config file 中出现时必须明确报错，禁止自动迁移或静默忽略。
- `stream.query` 字段过滤只允许 `filter.fields.<name>` 下的 exact 值队列、闭区间
  range、value/mask 三种互斥模式；旧 `match_field`、`args.match` 和
  `field_scope` 已删除且不提供兼容。packet stream 必须指定
  `filter.position=sop|eop`。
- `apb.query` / `axi.query` 不接受旧 `args.num`、`args.limit` 或猜测的顶层数量字段。
- `apb.statistics` / `axi.statistics` 使用严格 `args.filter`：direction、ID、address 三类
  条件取 AND；ID 队列内部取 OR；address 的 exact/range/mask 只能选择一种。APB schema
  不公开 IDs，mask=0、标准化重复值和反向 range 由 handler 返回明确语义错误。三类
  action 共用通用 value filter helper，禁止复制 literal、range、mask 或 X/Z 比较逻辑。

## Response Schema 要求

每个 public action 必须有 response schema。

要求：

- 覆盖 compact/default response 的稳定字段。
- 错误响应字段稳定。
- summary/data/findings/evidence 的类型明确。
- 新增字段后同步 example。
- 截断必须区分 `scan_complete`、`analysis_complete`、`response_truncated` 和 `render_truncated`；兼容字段 `truncated` 不能替代这些精确字段。

## 参数错误提示合同

xdebug 参数错误有两层：

- schema 层：request schema 校验失败，包括 missing required、wrong type、bad enum、additionalProperties、anyOf/oneOf 不满足。
- action handler 层：schema 已通过但运行语义非法，包括反向 time_range、不存在的 signal/config、handler 内部枚举、time parse 失败等。

两层都应尽量返回可恢复字段，并让 JSON 和 XOUT 都能看到：

- `invalid_arg`：错误字段路径。
- `expected`：期望类型、范围或语义。
- `received_type`：实际 JSON 类型。
- `allowed_values`：合法 enum。
- `did_you_mean`：常见错字段的正确字段路径。
- `required_any_of`：至少提供其中一组参数。
- `correct_example`：最小正确请求模板。

新增或修改 action 时，如果发现 AI 容易把参数写错，应优先通过 action-specific schema、handler 语义错误 enrichment 和 `correct_example` 修复，而不是在文档里继续保留旧 alias。

## actions.yaml 同步

`actions.yaml` 中的 `required_args`、schema 路径、example 路径、requires、handler_kind
必须和 runtime 一致。action 的英文/中文描述、purposes、适用范围、禁用范围和推荐替代
也以该文件为唯一事实源；runtime descriptor 由生成文件承载，不维护平行硬编码。

修改后运行：

```bash
python3 xdebug/tools/sync_runtime_request_schemas.py
python3 xdebug/tools/sync_internal_request_schema.py
python3 xdebug/tools/sync_value_response_schemas.py
python3 xdebug/tools/sync_axi_response_schemas.py
python3 xdebug/tools/sync_protocol_statistics_response_schemas.py
python3 xdebug/tools/sync_action_schema_hints.py
python3 xdebug/tools/sync_action_metadata.py
```

检查模式：

```bash
python3 xdebug/tools/sync_runtime_request_schemas.py --check
python3 xdebug/tools/sync_internal_request_schema.py --check
python3 xdebug/tools/sync_value_response_schemas.py --check
python3 xdebug/tools/sync_axi_response_schemas.py --check
python3 xdebug/tools/sync_protocol_statistics_response_schemas.py --check
python3 xdebug/tools/sync_action_schema_hints.py --check
python3 xdebug/tools/sync_action_metadata.py --check
```

## Batch response 组合校验

- batch 的公开 response schema 仍完整枚举所有 action-specific child 合同。运行时
  采用组合式等价校验：递归 dispatch 在 child 写入 `data.results[]` 前按对应 action
  response schema 校验；batch 外层使用从同一公开 schema 投影出的严格 envelope
  校验；未知 action child 单独使用公开 schema 中的
  `batchChild__unknown_child_error` 定义校验。不得把未知 child 或 envelope 当作已由
  递归边界覆盖，也不得修改公开 schema 来换取运行时性能。

## 基础校验

```bash
pytest --xverif-gate fast --xverif-suite xdebug.static
pytest --xverif-gate regression --xverif-suite xdebug.action_runtime_catalog
```

`schema-test` 覆盖 schema 文件和 examples。

`contract-test` 覆盖 action inventory、runtime action 输出、schema coverage、clock sampling static guard 等。

## Docs/Skill 校验

修改 skill 或 docs 中的 JSON 示例后，应抽取 Markdown fenced JSON，并用 action-specific schema 校验。

要求：

- JSON 示例必须带 `api_version` 和 `action`。
- 示例字段必须被对应 schema 接受。
- enum 值必须合法。
- docs 中不保留旧 alias 作为推荐字段。

## Runtime 校验

runtime 不应接受 schema 明确禁止的 public 字段。若短期保留旧 alias：

- 必须标 deprecated。
- 不得作为文档推荐合同。
- 必须有测试覆盖 warning 或兼容边界。

## 常见漂移

- docs 写 required，schema 未 required。
- schema required，example 缺字段。
- runtime 接受 alias，docs 推荐 alias。
- MCP wrapper 参数名与 native xdebug target/args 不一致。
- `x-arg_contract_notes` 与 required/anyOf 不一致。
- 通用 include 示例列出 action schema 不支持的字段。
