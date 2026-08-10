# xcov Action 与 XOUT 合同样例

本文覆盖 `xcov.v1` 的全部 canonical action、最小请求和统一 XOUT grammar。
旧 `function_coverage.*` 与 `export.function_coverage` 已删除，不存在 alias；
canonical 名称是 `functional_coverage.*` 与 `export.functional_coverage`。

## Transport

one-shot 默认输出 XOUT：

```bash
printf '%s\n' \
  '{"api_version":"xcov.v1","request_id":"actions","action":"actions"}' |
  tools/xcov -
```

需要 JSON 时只使用 CLI 选项：

```bash
printf '%s\n' \
  '{"api_version":"xcov.v1","request_id":"actions","action":"actions"}' |
  tools/xcov --json -
```

request 中的 top-level `output` 不控制 transport，会返回 `SCHEMA_INVALID`。
stdio-loop 用 JSONL envelope 承担 framing；envelope 内同时提供经过 response
schema 校验的 `json` 和同一响应的人读 `xout`。

## XOUT grammar

人读文法为：

```text
@xcov.<action>.v1

summary:
  total_count: 0
  returned_count: 0

items:
```

每个 action 以 summary、filters、sections、items 和 coverage 分段展示领域事实，
列根据当前 action response 选取。XOUT 不可逆；完整机器合同使用 envelope 中的 `json`。
不再输出 `XOUT_BEGIN/XOUT_END`，也不再产生 `output_path:null`。
stdio-loop 外层 envelope 承载 `request_id/api_version/action/ok` framing；内层 XOUT
payload 不重复这些字段，header 仍保留 action 合同标识。

## 全量 canonical 请求

下面是每个 action 的最小或代表性原生请求。除 export 外，`args.output` 不存在；
查询数量只由 `args.limits` 控制。

### Catalog 与 schema

```json
{"api_version":"xcov.v1","request_id":"actions","action":"actions"}
```

```json
{"api_version":"xcov.v1","request_id":"schema","action":"schema","args":{"action":"code_coverage.holes","kind":"request"}}
```

### Session

```json
{"api_version":"xcov.v1","request_id":"open","action":"session.open","target":{"vdb":"merged.vdb"},"args":{"name":"cov0"}}
```

`session.open.args` 只允许 `name` 和可选
`exclusion_policy:"default|strict"`。再次用 `cov0` 打开任意 VDB 都返回
`SESSION_EXISTS`，不会比较或复用已打开的 VDB；调用方必须先显式 close。
以下旧选择器会在 handler 运行前被严格 schema 拒绝：

```json
{"api_version":"xcov.v1","request_id":"invalid-open","action":"session.open","target":{"vdb":"merged.vdb"},"args":{"name":"cov0","reuse":true}}
```

```json
{"api_version":"xcov.v1","request_id":"status","action":"session.status","target":{"session_id":"cov0"}}
```

```json
{"api_version":"xcov.v1","request_id":"close","action":"session.close","target":{"session_id":"cov0"}}
```

NPI traversal 或 fact 合同失败使用结构化错误，并明确声明结果不完整：

```json
{"ok":false,"api_version":"xcov.v1","request_id":"metrics","action":"metrics.list","summary":{"total_count":0,"returned_count":0,"response_truncated":false,"scan_complete":false,"analysis_complete":false,"truncation_scopes":[]},"data":{},"error":{"code":"NPI_CONTRACT_VIOLATION","message":"NPI operation coverage.covered violated covered(test)","detail.error_layer":"backend","detail.operation":"coverage.covered","detail.object_type":"CoverageHandle","detail.method":"covered","detail.expected_signature":"covered(test)","detail.cause_type":"RuntimeError","detail.cause_message":"coverage handle is invalid"},"warnings":[]}
```

### Tests、metrics 与 scope

```json
{"api_version":"xcov.v1","request_id":"tests","action":"tests.list","target":{"session_id":"cov0"},"args":{"query":{"include_patterns":["*uart*"],"match_field":"name"},"limits":{"max_items":100}}}
```

```json
{"api_version":"xcov.v1","request_id":"metrics","action":"metrics.list","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","test":"merged"}}
```

```json
{"api_version":"xcov.v1","request_id":"scope-summary","action":"scope.summary","target":{"session_id":"cov0"},"args":{"scope":"uart_tb"}}
```

```json
{"api_version":"xcov.v1","request_id":"scope-children","action":"scope.children","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","recursive":false}}
```

```json
{"api_version":"xcov.v1","request_id":"scope-search","action":"scope.search","target":{"session_id":"cov0"},"args":{"query":{"include_patterns":["*u_uart*"],"match_field":"full_name"}}}
```

### Code coverage

```json
{"api_version":"xcov.v1","request_id":"code-summary","action":"code_coverage.summary","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","group_by":"metric"}}
```

```json
{"api_version":"xcov.v1","request_id":"code-holes","action":"code_coverage.holes","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","metrics":["line","toggle","branch","condition","fsm","assert"],"limits":{"max_items":100,"overflow":"truncate"}}}
```

### Functional coverage

```json
{"api_version":"xcov.v1","request_id":"functional-summary","action":"functional_coverage.summary","target":{"session_id":"cov0"},"args":{"group_by":"covergroup"}}
```

```json
{"api_version":"xcov.v1","request_id":"functional-holes","action":"functional_coverage.holes","target":{"session_id":"cov0"},"args":{"levels":["bin"],"query":{"include_patterns":["*APB_accesses_cg*"],"match_field":"full_name"}}}
```

### Source 与 assertion



```json
{"api_version":"xcov.v1","request_id":"assert-summary","action":"assert.summary","target":{"session_id":"cov0"}}
```

### Markdown export

三个 export action 的 `args.output.path` 都是 required；artifact 固定为 Markdown。

### Exclusion

```json
{"api_version":"xcov.v1","request_id":"exclude-list","action":"exclude.list","target":{"session_id":"cov0"}}
```

```json
{"api_version":"xcov.v1","request_id":"exclude-load","action":"exclude.load","target":{"session_id":"cov0"},"args":{"paths":["code.el","functional.el","assertion.el"]}}
```

```json
{"api_version":"xcov.v1","request_id":"exclude-add","action":"exclude.add","target":{"session_id":"cov0"},"args":{"coverage_refs":["xcovref.v1:<sha256>"]}}
```

```json
{"api_version":"xcov.v1","request_id":"exclude-remove","action":"exclude.remove","target":{"session_id":"cov0"},"args":{"coverage_refs":["xcovref.v1:<sha256>"]}}
```

```json
{"api_version":"xcov.v1","request_id":"exclude-export","action":"export.exclude","target":{"session_id":"cov0"},"args":{"output":{"path":"current.el"}}}
```

```json
{"api_version":"xcov.v1","request_id":"exclude-unload","action":"exclude.unload_all","target":{"session_id":"cov0"},"args":{"confirm":true}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-validate","action":"exclude.csv.validate","args":{"directory":"coverage_exclusions"}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-status","action":"exclude.csv.status","args":{"directory":"coverage_exclusions","repo_root":"."}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-impact","action":"exclude.csv.impact","args":{"directory":"coverage_exclusions","repo_root":"."}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-resolve","action":"exclude.csv.resolve","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions"}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-apply","action":"exclude.csv.apply","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions"}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-compile","action":"exclude.csv.compile","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions","output_directory":"coverage_exclusions"}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-rebase","action":"exclude.csv.rebase","args":{"directory":"coverage_exclusions","repo_root":"."}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-stamp","action":"exclude.csv.stamp_changed","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions","repo_root":"."}}
```

```json
{"api_version":"xcov.v1","request_id":"csv-format","action":"exclude.csv.format","args":{"directory":"coverage_exclusions","write":false}}
```

原生 EL 不通过文本拼接合并；按顺序多次 `exclude.load` 使用 pynpi union 语义。
`export.exclude` 固定为 `save_exclude_file(path, "w")`，不接受 mode。CSV compile
只有在所有记录都精确匹配后才发布三份 EL。

### Markdown export 请求

```json
{"api_version":"xcov.v1","request_id":"export-code","action":"export.code_coverage","target":{"session_id":"cov0"},"args":{"scopes":["uart_tb.u_uart"],"metrics":["line","condition","branch","toggle","fsm"],"output":{"path":"coverage_artifacts"}}}
```

```json
{"api_version":"xcov.v1","request_id":"export-functional","action":"export.functional_coverage","target":{"session_id":"cov0"},"args":{"covergroup":"*uart*","output":{"path":"functional_coverage.md"}}}
```

```json
{"api_version":"xcov.v1","request_id":"export-assert","action":"export.assert","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","output":{"path":"assert.md"}}}
```

## 完整性字段

成功与错误响应都严格声明：

- `total_count`
- `returned_count`
- `response_truncated`
- `scan_complete`
- `analysis_complete`
- `truncation_scopes`

例如 `limits.max_items` 只限制 `data.items` 时，完整扫描与分析仍为 true，
`response_truncated:true` 且 `truncation_scopes:["data.items"]`。非法字段或不完整
export 请求在 handler 执行前返回严格 error response；任何旧 action 名返回
`UNKNOWN_ACTION`。
