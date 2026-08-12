# xdebug 编码要求

本页定义修改 xdebug 代码时的工程要求。原则是：schema 优先、合同稳定、输出可解析、错误可诊断、测试分层。

## API 合同

- schema 是 public contract，不从 runtime 反向猜合同。
- action 参数只能使用 schema 允许字段。
- 不引入同义字段，除非有明确迁移计划和 deprecated 说明。
- 删除或收紧字段时，同步 runtime、schema、examples、docs、skill、MCP、tests。
- 错误码是机器合同，不能只依赖 message 文本。
- 参数错误必须可恢复：schema 层和 action handler 层都应尽量返回 `invalid_arg`、`expected`、`available_values`、`did_you_mean`、`required_any_of`、`correct_example` 等结构化字段。错误候选只使用 `error.available_values`；action catalog descriptor 的 `allowed_values` 是参数到 enum 的元数据映射，不是错误字段。
- `REQUEST_TOO_LARGE` 必须返回 `limit_name=request_bytes`、实际/上限字节数、`transport`、`phase` 和可执行的 `next_actions`，并固定 `recoverable=false`。不得截断后继续解析、自动提高全局上限或静默切换 transport。
- `INVALID_CONFIG` 必须返回非空 `config_key`、`config_source=environment|default|request`、`expected` 和 `next_actions`，并固定 `recoverable=false`。敏感配置值不得写入 `received`、message 或日志；需要表达“已收到但已隐藏”时使用 `received_redacted=true`。

## JSON 处理

- 使用 nlohmann/json 和现有 request/response helper。
- 不用 ad hoc string parsing 解析 JSON。
- 不手写 JSON 字符串拼接 response。
- 字段读取要区分 missing、null、wrong type、empty value。

## 输出纪律

- 默认 compact-first。
- full/debug 只用于维护工具或排查工具本身。
- 大列表、timeline、trace、source_text 必须受 action-specific `line_limit`、schema 明确声明的 `args.output` 参数或 export action 控制；AXI transaction 的逐 beat payload 使用 `output.include_data`，其它 action 不得照抄该参数或新增裸 `limit`。
- XOUT 与 JSON 输出都要保持结构稳定。
- 新增错误字段时必须同时检查 JSON response 和 XOUT 渲染；AI 默认看 xout 时也应能直接修正下一次请求。

## 时间和值语义

- 时间解析复用统一 time helper。
- clock sampling 复用统一 sampling helper。
- 四态值和 bit 表示复用 `LogicValue` 等统一组件。
- 不在局部 handler 里写特殊时间单位或四态比较。

## Session 和 Transport

- public session 选择使用 `target.session_id`。
- SESSION_LOST/SESSION_TRANSPORT_FAILED 后不复用旧 session。
- transport 不静默 fallback。
- file transport 只作为显式例外路径。

## Logging

- 结构化日志必须包含 phase 和 error context。
- stdout 不输出调试噪声。
- 不记录敏感凭据。
- 环境问题要能从 lifecycle/transport/action log 追踪。

## C++ 代码风格

- 优先使用现有 helper 和 domain service。
- handler 保持薄层：读参数、调用 service、整理 response。
- 复杂逻辑下沉到可单测 helper。
- 避免跨 domain 直接依赖，例如 waveform helper 不直接承担 design trace 语义。
- 新增文件同步 Makefile source list。

## Python 工具风格

- Python 脚本优先使用 `python3` 运行。
- 校验脚本应支持 check 模式，避免无意修改 tracked 文件。
- 脚本输出要能被 CI/agent 清楚判断成功失败。

## 文档要求

- docs 描述当前实现，不写未实现愿景。
- public 示例必须可执行或可 schema 校验。
- 复杂行为要说明 source of truth 和测试入口。
- 修改 xdebug 架构或 action 流程时，同步本目录相关页面。

## 提交前检查

源码修改提交前：

1. `git status --short`
2. 根据影响面选择 tests。
3. 确认 schema/examples/docs/skill/MCP 是否需要同步。
4. 确认本目录说明书是否需要同步。
5. commit message 用中文写明验证结果。
