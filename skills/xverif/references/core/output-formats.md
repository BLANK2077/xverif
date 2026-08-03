# XOUT 与 JSON 选择策略

XOUT 是 xverif 面向 AI/LLM 上下文效率设计的默认响应格式。它用领域化摘要、
证据行、源码窗口和紧凑表格减少 JSON 键名、引号、括号和重复层级带来的 token
开销。便于人读只是附带收益，不是 XOUT 的首要设计目标。

## 默认选择

- AI agent、MCP 查询和交互式 CLI 默认使用 XOUT。
- XOUT 保留 action 定义的核心证据、错误和公开完整性状态，但不承担 JSON 的
  可逆编码或逐字段复制合同。
- transport sideband 可单独承载 request id、状态和 framing；不得向 native XOUT
  添加 `XOUT_BEGIN` / `XOUT_END`，也不得在 adapter 中反解析、重排或重编码正文。
- adapter 必须原样透传 native XOUT：不反解析、不重编码，禁止加入
  `XOUT_BEGIN/XOUT_END` transport markers。

仅在以下场景显式请求 JSON：

- 程序需要稳定字段编程，按字段名解析、排序、比较或持久化完整结构；
- 需要 action response schema 校验或 JSON round-trip；
- 需要读取 XOUT 未承诺投影的精确嵌套字段；
- 用户明确要求 JSON。

不要从 XOUT 的缩进或表格反解析 JSON，也不要把“不可逆”解释成“AI 应优先
JSON”。需要更多证据时，先按 action schema 调整查询范围、line limit、verbose
或 export 参数；不要仅为避免阅读 XOUT 而切换格式。

## LogicValue 紧凑规则

- 未指定 `value_format` 时显示真实位宽的紧凑十六进制，例如 `8'h8f`、`8'h0`；
  不重复输出可由 literal 推导的 `known`、`width` 或 `bits`。
- 显式指定 `bin` 或 `dec` 时服从请求。十进制无法表达逐 bit X/Z 时改用二进制
  literal，并只附简短的 requested/effective 说明。
- 只有十六进制值含 X/Z 时补充逐 bit 诊断，例如
  `8'hx bits=x01x_x10x`；不再重复 `has_x`、`has_z` 或 `width`。
- 成功的 `value.at` XOUT 使用 action header 和 `values` 矩阵；完整
  `summary`、`entries`、`samples` 保留在 JSON response 中。

## 完整性

无论选择 XOUT 还是 JSON，都必须读取 action 发布的
`scan_complete`、`analysis_complete`、`response_truncated`、`total_count`、
`returned_count` 和 `truncation_scopes`。XOUT renderer 不得私自隐藏 action 已返回
的行；action 自身通过公开合同决定分析和响应边界。
