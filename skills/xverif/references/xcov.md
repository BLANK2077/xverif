# xcov coverage 查询

xcov 查询 VCS/Verdi coverage database（`simv.vdb`、`merged.vdb`）。它负责 coverage evidence，不负责自动解释 hole 根因或生成补测策略。

## 何时使用

- 查询 line/toggle/branch/condition/fsm/assert/function coverage。
- 用 `scope.*` 和 `code_coverage.*` 按 hierarchy scope 查看覆盖率概览。
- 按源码 file/line/window 反查 coverage item。
- 输出源码窗口和 coverage annotation。
- 输出 assert/cover property/cover sequence 的结构化 report。
- 通过 `export.code_coverage` 导出分 instance、分 metric 的 JSON/XOUT/raw URG bundle；
  `export.functional_coverage`、`export.assert` 仍按各自合同导出报告。

## CLI 入口

```bash
tools/xcov --json -
tools/xcov --stdio-loop
```

本文件只讲原生 `xcov.v1` JSON envelope。MCP tool 参数、MCP session 和 SDK-free loop wrapper 请使用 `xverif-mcp`。

真实 NPI coverage 查询需要 Synopsys license；受限沙箱内 license 可能不可达。

## 常用请求

open：

```json
{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"merged.vdb"},"args":{"name":"cov0"}}
```

holes：

```json
{"api_version":"xcov.v1","action":"code_coverage.holes","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","metrics":["line","toggle","branch","condition","fsm","assert"],"limits":{"max_items":100}}}
```

code holes glob filter：

```json
{"api_version":"xcov.v1","action":"code_coverage.holes","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","query":{"include_patterns":["*u_uart*"],"exclude_patterns":["*uvm*"],"match_field":"full_name"}}}
```

function holes：

```json
{"api_version":"xcov.v1","action":"functional_coverage.holes","target":{"session_id":"cov0"},"args":{"levels":["bin"],"query":{"include_patterns":["*APB_accesses_cg*"],"match_field":"full_name"}}}
```



assert summary：

```json
{"api_version":"xcov.v1","action":"assert.summary","target":{"session_id":"cov0"}}
```

code coverage export：

```json
{"api_version":"xcov.v1","action":"export.code_coverage","target":{"session_id":"cov0"},"args":{"scopes":["uart_tb.u_uart"],"metrics":["line","toggle"],"output":{"path":"coverage_artifacts"}}}
```

function coverage export：

```json
{"api_version":"xcov.v1","action":"export.functional_coverage","target":{"session_id":"cov0"},"args":{"covergroup":"*uart*","output":{"path":"function_coverage.md"}}}
```

assert export：

```json
{"api_version":"xcov.v1","action":"export.assert","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","output":{"path":"assert.md"}}}
```

## 读取规则

- 先看 `ok`。
- 看 `summary.matched_count/returned/truncated/output_path/note`。
- coverage item 关注 action 当前返回的字段；不要假设所有 action 都输出
  `metric/type/name/full_name/covered/coverable/missing/status/evidence.file/evidence.line`。
- coverage pct 用 `covered/coverable`，不要用 hit count 代替覆盖率。
- 保留 `excluded/unreachable/illegal` 状态，不要误判为普通 hole。
- 交互查询优先用 `scope.summary`、`scope.children`、`scope.search`、
  `code_coverage.summary`、`code_coverage.holes` 看层次覆盖率。
- `scope.summary` 返回扁平覆盖率字段；不要期待 `metrics={...}`，也不要期待
  parent/depth/type/def_name。
- `scope.children` 和 `scope.search` 每项只返回 `name/full_name/coverage_pct`。
- `code_coverage.summary` 不输出 `name/full_name/functional_pct`。
- `code_coverage.holes` 只输出当前 hierarchy 与子模块覆盖率概览，只保留
  `name/full_name/coverage_pct/*_pct`，不展开具体未覆盖 signal、branch、condition 或
  bin，也不输出 parent/depth/type/def_name/covered/coverable/missing/file/line。
- `code_coverage.holes` 和 `functional_coverage.holes` 支持 `query.include_patterns` /
  `query.exclude_patterns` 通配过滤；只支持 glob `*`、`?`，不要使用 regex。
- `functional_coverage.holes` 默认按 `full_name` 过滤，可用 `match_field` 切到
  `covergroup`、`coverpoint`、`cross`、`bin` 或 `name`。
- `functional_coverage.summary` 和 `functional_coverage.holes` 不输出
  `metric/name/full_name/score_basis/score_item_count/raw_covered/raw_coverable/raw_missing`；
  `functional_coverage.summary` 也不输出 `raw_coverage_pct`。
- xout 的 `items:` 是对齐纯文本表格，不是 Markdown 表格；JSON 响应结构不变。
- 详细 code coverage 未覆盖项使用 `export.code_coverage` 的分 metric JSON/XOUT 查看；
  functional/assertion 使用各自 export action 的当前 schema。
- `export.code_coverage` 不输出 Markdown。它为每个具体 instance 建立独立目录，按 metric
  输出 JSON、XOUT 和原始 URG text；先读 `navigation.xout` 选择子层级，再读 metric XOUT
  获取目标 instance 自身的具体缺口。
- branch 使用 `xcov.code_coverage.branch.v2`：相同 decision path 的缺口合并为一个 group，
  先用字段表描述 marker 对应的源码 decision，随后紧接真值表列出各 `gap_id` 的
  marker value；这些行均为未覆盖缺口，因此不重复输出固定的 status 列；`-` 表示该
  decision 在这条路径中未求值。Decision kind 支持 `if/case/casez/casex/ternary`；
  多行三目的 `at` 指向 predicate 实际行，`outcomes` 列以
  `0:false-result | 1:true-result` 明确实际缺失的结果分支。
- line 使用 `xcov.code_coverage.line.v2`：只输出有缺口的过程块，先读 context 表的
  kind/at/covered/coverable/missing/pct，再读紧邻 uncovered 表的 gap_id/at/statement。
- condition 使用 `xcov.code_coverage.condition.v2`：condition 表给出位置与完整表达式，
  terms 表解释 marker，uncovered 真值表给出需补 values。相同位置、terms、values 的
  EXPRESSION/SUB-EXPRESSION 合并为一个 gap；`coverage_object_gap_count` 是 URG 原始
  missing object 数，`gap_count` 是 AI 实际需要处理的语义 gap 数；三目 condition
  同样使用 `outcomes` 映射 predicate value 与结果表达式。
- fsm 使用 `xcov.code_coverage.fsm.v2`：实例内不同 FSM 分段输出，每段先给出 transition
  coverage，再以 `gap_id/kind/object/at` 表格逐行列出 state、transition 或 sequence 缺口。
- `navigation.xout` 的覆盖率是 subtree 统计；metric XOUT 的覆盖率是 self 统计，不得混用。
- `assert.summary` 输出基础覆盖率和 attempts/real successes/without attempts；不输出
  kind/category/severity/failures/incomplete/first_match/file/line。需要完整 assertion
  Markdown 时使用 `export.assert`。
- 找不到 NPI API 支撑的 URG 字段时，不要做 fallback，不要要求 xcov 返回占位字段；应说明该字段做不到。

## 排障

- license/NPI 错误：在沙箱外确认 Verdi/NPI 和 license server。
- action 参数不确定：先用原生 `actions` 和 `schema` action 查询。
- 大结果：设置 limit，必要时 `overflow:"to_file"` 或 output path。
- MCP/LSF/session 问题：改用 `xverif-mcp` 对应 troubleshooting。
