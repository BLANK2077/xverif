# xdebug response 字段约定

精确 response 字段以选定 action 的 checked-in response schema 为唯一合同。不要把
另一个 action 的 summary/data 形状投射过来，也不要从 XOUT 排版反推 JSON。

## 公共 envelope

- `api_version` 固定为 `xdebug.v1`。
- `ok` 表示 action 是否成功。
- `action` 必须与请求 action 相同。
- 成功响应按 action schema 提供 `summary`、`data`、`errors`；错误响应提供 typed
  error evidence。所有对象默认关闭未知字段。

## 完整性字段

产生扫描、分析或有界 collection 的 action，在 schema 指定的位置使用：

- `scan_complete`：是否到达数据源终点；
- `analysis_complete`：是否完成合同定义的分析；
- `response_truncated`：返回是否只携带 collection 子集；
- `total_count`：完整 collection 的 item 数；
- `returned_count`：实际返回 item 数；
- `truncation_scopes`：未完成或裁剪影响的业务范围。

不得重新引入裸 `truncated` 或单字符串 `truncation_scope`。业务
`status:partial`、`missing`、`unknown` 不替代上述完整性事实。

## LogicValue

JSON 保留 canonical LogicValue 对象；XOUT 使用按真实位宽渲染的紧凑 literal。
默认 hex，显式 `value_format=bin|dec` 时服从请求；decimal 遇逐 bit X/Z 时 effective
format 为 binary。不要从 literal 字符长度猜测原始信号宽度。

`value.at` 的 `signal/list/apb/stream/axi` selector 恰好一个；`time` 或 `times`
恰好一种。XOUT 只投影 action header、必要采样上下文和 values 矩阵，完整
summary/entries/samples 留在 JSON。

## expr.normalize

expr-only 分支的 `summary.source` 为 `deterministic_syntax_parser`，
`summary.confidence` 为 `syntax_validated`。它只证明表达式已由确定性 parser 验证，
不代表结合 design resource 验证了信号存在性或赋值语义。

## Trace 与协议

- `trace.active_driver` / `trace.active_driver_chain` 必须区分 resolved、control-only、
  unresolved 和 ambiguity evidence。
- `trace.x_origin` 区分 query time、连续 X onset 和 active-driver time；深度或预算停止
  时保留 frontier 与完整性证据。
- Stream、AXI、APB response 的 transaction/config/finding 字段仅按各自 schema
  解读；不能将一种协议的 count、time 或 status 名称套到另一种协议。

## XOUT

XOUT 是 token-efficient、action-specific 的核心证据投影。adapter 原样透传 native
正文，不反解析、不重排、不重编码，也不添加 `XOUT_BEGIN` / `XOUT_END`。
需要稳定字段编程、schema validation 或未投影嵌套字段时请求 JSON。
