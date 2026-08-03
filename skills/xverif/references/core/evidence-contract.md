# 证据合同

验证结论应保留可复核的确定性证据：

- signal、hierarchy path、scope；
- time、time range、clock edge；
- sampled value 和 known/unknown；
- driver/load、file:line、source context；
- action/tool 和 finding/error code；
- config 名称及来源；
- action-specific status、missing 和 unknown 状态。

产生扫描、分析或有界 collection 的 action，只通过以下六个 canonical 字段表达
完整性；字段位置、required 条件和 count 对象以当前 action response schema 为准：

- `summary.scan_complete`：是否扫描到合同定义的数据源终点；
- `summary.analysis_complete`：是否完成合同定义的分析；
- `summary.response_truncated`：response 是否只携带完整 collection 的子集；
- `summary.total_count`：当前 action 定义的完整 collection item 数；
- `summary.returned_count`：response 实际携带的 item 数；
- `summary.truncation_scopes`：未完成或裁剪影响的明确业务范围。

`scan_complete=false`、`analysis_complete=false` 或
`response_truncated=true` 时不能作全量结论。action-specific
`status:partial`、`missing` 或 `unknown` 是业务状态，不能代替上述完整性字段，
也不能从另一个 action 推断其含义。不得读取或生成裸 `truncated`、单字符串
`truncation_scope` 等旧字段。

需要收敛证据时，只使用当前 action schema 明确支持的范围、预算、行数或 export
参数；不自动切换 surface、transport、backend 或数据源。XOUT 是默认的
token-efficient 核心证据投影；需要按稳定字段名解析、校验 schema 或读取未投影
嵌套字段时才请求 JSON。任何形态都不能从 XOUT 行数推断完整性。

图片用于发现宏观模式，不替代确定性 action 证据。
