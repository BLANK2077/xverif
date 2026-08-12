# xdebug 已校验请求示例

这些示例只演示 canonical envelope；精确参数仍以 runtime action schema 为准。

## 发现 scope

```json
{"api_version":"xdebug.v1","action":"scope.roots","target":{"session_id":"case_a"},"args":{"source":"auto"}}
```

```json
{"api_version":"xdebug.v1","action":"scope.list","target":{"session_id":"case_a"},"args":{"source":"wave","path":"top","level":1,"kind":"all","include_patterns":[],"exclude_patterns":[]}}
```

纯 design 与 merged 层级分别显式选择 source；不要因某一资源缺失而自动切换：

```json
{"api_version":"xdebug.v1","action":"scope.list","target":{"daidir":"simv.daidir"},"args":{"source":"design","path":"top","level":2,"kind":"all"},"limits":{"max_rows":1000}}
```

```json
{"api_version":"xdebug.v1","action":"scope.list","target":{"daidir":"simv.daidir","fsdb":"waves.fsdb"},"args":{"source":"merged","path":"top","level":1,"kind":"interface"},"limits":{"max_rows":100}}
```

## 加载信号组并多时间点取值

```json
{"api_version":"xdebug.v1","action":"list.load","target":{"session_id":"case_a"},"args":{"config":{"lists":[{"name":"ready_path","signals":["top.u.valid","top.u.ready","top.u.full"]}]},"mode":"replace"}}
```

```json
{"api_version":"xdebug.v1","action":"value.at","target":{"session_id":"case_a"},"args":{"list":"ready_path","times":["100ns","120ns"],"clock":"top.clk"}}
```

单信号单点仍使用同一个 action：

```json
{"api_version":"xdebug.v1","action":"value.at","target":{"session_id":"case_a"},"args":{"signal":"top.u.ready","time":"100ns","value_format":"hex"}}
```

## 受限变化与事件

```json
{"api_version":"xdebug.v1","action":"signal.changes","target":{"session_id":"case_a"},"args":{"signal":"top.u.ready","time_range":{"begin":"100ns","end":"200ns"},"mode":"summary"}}
```

```json
{"api_version":"xdebug.v1","action":"event.find","target":{"session_id":"case_a"},"args":{"clock":"top.u.clk","signals":{"valid":"top.u.valid","ready":"top.u.ready","wait_count":"top.u.dbg_wait_count"},"expr":"valid && !ready && wait_count >= 512","mode":"all","line_limit":5}}
```

## 无 resource 的表达式解析

```json
{"api_version":"xdebug.v1","action":"expr.normalize","args":{"expr":"valid && !ready"}}
```

该分支禁止 `target`/session；成功响应的 parser 证据是
`deterministic_syntax_parser` 与 `syntax_validated`。design signal 分支则必须使用
design session，两种 args 不能混用。

## APB 有界预览与完整导出

预览固定最多返回 8 笔，完整时间范围的 begin/end 都必须提供：

```json
{"api_version":"xdebug.v1","action":"apb.export","target":{"session_id":"case_a"},"args":{"name":"apb0","time_range":{"begin":"0ns","end":"1us"},"direction":"all","value_format":"hex"}}
```

写文件时显式给 path；`file_format` 不能脱离 path 单独出现：

```json
{"api_version":"xdebug.v1","action":"apb.export","target":{"session_id":"case_a"},"args":{"name":"apb0","time_range":{"begin":"0ns","end":"1us"},"direction":"write","address":{"mode":"range","begin":"32'h1000","end":"32'h10ff"},"output":{"path":"artifacts/apb0","file_format":"tsv"}}}
```

written 响应的 `summary.output.data_path/meta_path`、`artifact_bytes`、匹配计数和 meta
必须一致；该 action 不回退到 `apb.query` 或 `stream.export`。
