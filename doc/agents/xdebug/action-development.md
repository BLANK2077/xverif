# 添加或修改 xdebug action

本页描述 action 从 public contract 到 runtime、docs、tests 的完整闭环。任何 action 变更都必须以 schema 和真实 runtime 为中心，不允许只改文档。

## 先判断 action 类型

添加 action 前先判断资源和执行位置：

- `requires: none`：不需要 daidir/fsdb/session，例如 `actions`、`schema`、纯规范化类 action。
- `requires: design`：需要 daidir 或 design session。
- `requires: waveform`：需要 fsdb 或 waveform session。
- `requires: combined`：同时需要 daidir 和 fsdb。
- `requires: session`：管理已打开 session。
- `requires: any`：可用多种资源打开或诊断。

再判断 handler_kind：

- local/frontend action：由 `src/api/dispatcher.*` 或 API registry 本地处理。
- session action：由 session manager/catalog 处理，必要时转发到 engine session。
- engine_forward action：frontend 校验后转发到 `xdebug-engine`。
- combined action：需要 design + waveform evidence 的 combined service。

## 修改 action inventory

入口：

- `xdebug/specs/actions/actions.yaml`

必须维护：

- `name`
- `category`
- `status`
- `requires`
- `handler_kind`
- request/response schema 路径
- request/response example 路径
- `required_args` 或其它合同元数据
- `description_en`、`description_zh`、`purposes`、`use_for`、`do_not_use_for`、
  `preferred_alternative`。这些字段以 `actions.yaml` 为 canonical source，必须通过
  `tools/sync_action_metadata.py` 生成编译期 metadata，禁止在 runtime 中逐 action
  手写另一份描述。

要求：

- action 名称稳定后不要随意重命名。
- `required_args` 必须和 request schema 的 required/anyOf 一致。
- status 从 experimental 到 stable 前必须补齐 schema、examples、docs、tests。

## 编写 schema

路径：

- `schemas/v1/actions/<action>.request.schema.json`
- `schemas/v1/actions/<action>.response.schema.json`

要求：

- request schema 顶层固定描述 envelope 字段：`api_version`、`request_id`、`action`、`target`、`args`、`limits`、`output`、`auth_token`。
- action-specific 参数放在 `args` 或明确约定的位置，不随意发明多个同义字段。
- 需要资源选择时优先使用 `target`；已打开 session 使用 `target.session_id`。
- 所有对象默认收紧 `additionalProperties:false`，除非确实需要透传扩展。
- enum 值必须和 runtime 分支完全一致。
- `time_range`、`output.path`、`line_limit`、`stream`、`direction` 等标准字段按现有词典使用，不引入同义别名。
- 不要为了 AI 误用保留旧 alias。发现常见误用时，优先通过 action-specific schema、错误提示、最小正确模板和错误反例修复；例如 APB/AXI query 使用 `query.index`，active-driver 链深度使用 top-level `limits.max_depth`。
- response schema 必须覆盖 summary/data/error 的稳定字段。
- schema 顶层 `description` 使用英文，`x-description-zh` 使用中文；生成器和手写
  schema 都必须保持这个双语字段约定，不得把中文写回 `description` 造成风格漂移。
- 参数错误路径必须设计清楚：schema 层负责结构性错误，handler 层负责语义错误；两层都应返回可恢复字段，尤其是 `invalid_arg` 和 `correct_example`。

## 编写 examples

路径：

- `examples/requests/<action>.basic.json`
- `examples/responses/<action>.basic.json`

要求：

- example 必须能通过 schema 校验。
- request example 必须只使用 schema 允许字段。
- response example 应代表 compact/default 形态，不要把 debug-only payload 当默认输出。
- 对 required/anyOf 合同复杂的 action，至少提供一个合法最小 request。

## 注册 runtime handler

常见路径：

- frontend/API：`src/api/dispatcher.*`、`src/api/action_registry_init.*`
- engine registry：`src/engine/service/engine_action_registry.*`
- design handlers：`src/engine/service/actions/design/`
- waveform handlers：`src/engine/service/actions/waveform/`
- protocol handlers：`src/engine/service/actions/protocol/`
- stream handlers：`src/engine/service/actions/stream/`
- combined handlers：`src/engine/service/actions/combined/`

要求：

- 新 action 文件放到对应 domain 子目录。
- 在对应 `register_*_handlers.cpp` 注册。
- 采用 `waveform/service/typed_query_actions.h` 的 waveform action 必须在独立 wrapper
  中把 action 名直接绑定到具体 `ai_*` 函数，并通过共享
  `typed_waveform_action_adapter` 接管 args/limits 与错误适配；不增加字符串二次分发。
- handler 接收已校验 request，但仍要检查业务语义，例如 signal 不存在、时间窗口为空、资源不匹配。
- 错误返回使用稳定 error code，不用自由文本当机器合同。
- 大数据默认摘要化，详细数据通过 action-specific `line_limit`、schema 明确声明的 `args.output` 参数或 export action 控制；AXI transaction 使用 `output.include_data`，其它 action 不得照抄该参数或新增裸 `limit`。
- `line_limit` 只控制 response/XOUT 证据缓存；扫描预算使用 `max_samples`，文件/聚合事件预算按 action 使用 `max_events`。实现不得把 `line_limit` 直接传入 clock scanner。
- 完整扫描的大结果要在线累计 summary，并有界保留 first/last/前 N 条证据；不得为 compact response 无界缓存所有 transfer/finding。

`actions` catalog 的公开过滤字段固定为 `category`、`requires`、`purposes` 和
`keyword`；`status` 只作为 descriptor metadata，不是过滤条件。默认返回 compact
action name，`args.output.verbose=true` 返回字段恒定存在的完整 descriptor；
`args.output.view="guide"` 返回按 action 名排序的 `name: description_en` 文本，不含
status 或 `use_when`。`view` 与 `verbose` 互斥，guide 必须在 native runtime 中按
UTF-8 字节执行 10,000-byte hard limit，超限明确失败，禁止截断或 fallback。

## 更新 docs 和 skill

必须检查：

- `xdebug/docs/action-inventory.md`
- `skills/xverif/references/capabilities/xdebug.md`
- `skills/xverif/references/generated/xdebug-actions.md`
- `skills/xverif/references/xdebug/json-api.md`
- `skills/xverif/references/xdebug/response-fields.md`
- `skills/xverif/specs/examples.yaml`
- 两个 skill 中相关 recipe/example 文档
- 本目录说明书相关页面

要求：

- docs 不得推荐 schema 不接受的字段。
- skill 示例必须能过 action-specific schema。
- 如果 repo 内 skill 需要安装版同步，使用项目 Makefile 或明确同步流程。

## 更新 tests

最小要求：

- schema/example 变化：`pytest --xverif-gate fast --xverif-suite xdebug.static`
- action inventory/runtime 变化：`pytest --xverif-gate regression --xverif-suite xdebug.action_runtime_catalog`
- C++ helper 变化：相关 unit test 或新增 unit test。
- waveform/design/combined 行为变化：添加 focused pytest 或 fixture。
- MCP 暴露变化：更新 `xverif_mcp/tests/`，运行 `pytest --xverif-gate regression --xverif-suite xverif_mcp.action_smoke`。

提交前必须按变更范围跑通关联测试。

## 常见错误

- 只改 runtime 不改 schema，导致 agent 继续生成非法 request。
- 只改 schema 不改 runtime，导致合法 request 运行失败。
- docs 中保留旧 alias，造成 AI 继续使用过期字段。
- response 新字段没有 schema/example，导致下游无法稳定解析。
- action handler 直接读取多个同义字段，短期兼容没有 deprecated 说明。
