# xdebug 原生 JSON API

原生入口读取一行一个 `xdebug.v1` request。CLI 默认输出 XOUT；只有稳定字段编程、
schema 校验、结构化持久化或用户明确要求时才选择 JSON。

## Envelope

Resource action 的 request 由以下部分组成：

- `api_version: xdebug.v1`；
- `action`：必须来自当前 canonical catalog；
- `target.session_id`：引用已打开的 managed session；
- `args`：action-specific 参数；
- `limits`：仅在该 action schema 公布时使用；
- `output.format: xout|json`：显式覆盖默认格式。

`requires:none` action/variant 禁止 `target`。例如 `expr.normalize(args.expr)` 不带
session；`expr.normalize(args.signal)` 必须有 design resource。不要把 MCP 的顶层
`session_id` 或 tool 参数壳写入原生 envelope。

## 发现与 schema

先读取完整 runtime catalog，再读取选定 action 的 request schema。schema 是参数名、
required/conditional-required、enum、unknown-field 和 resource variant 的唯一合同。
不要根据相似 action 猜 args，也不要接受后忽略公开参数。

多信号或多时间点读取使用：先 `list.load`，再一次
`value.at(list="<name>", times=[...])`。`xverif_batch` 不是多点采样接口。

## Response

JSON response 必须通过对应 action response schema；XOUT 是同一 action 的
token-efficient 核心证据投影，不是 JSON 的可逆编码。adapter 原样透传 native XOUT，
不反解析、不重排、不重编码，也不添加 `XOUT_BEGIN` / `XOUT_END`。

扫描或有界 collection 的结论必须读取 `scan_complete`、`analysis_complete`、
`response_truncated`、`total_count`、`returned_count`、`truncation_scopes`。
`status:partial` 是 action-specific 业务状态，不能替代这些字段。

## 相关资料

- [已校验请求示例](examples.md)
- [response 字段约定](response-fields.md)
- [高频 recipes](recipes.md)
- [全量生成 action 索引](../generated/xdebug-actions.md)
