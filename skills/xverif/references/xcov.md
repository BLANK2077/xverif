# xcov coverage 查询

xcov 查询 VCS/Verdi coverage database（`simv.vdb`、`merged.vdb`）。它负责 coverage evidence，不负责自动解释 hole 根因或生成补测策略。

## 何时使用

- 查询 line/toggle/branch/condition/fsm/assert/function coverage。
- 用 `scope.*` 和 `code_coverage.*` 按 hierarchy scope 查看覆盖率概览。
- 按源码 file/line/window 反查 coverage item。
- 输出源码窗口和 coverage annotation。
- 输出 assert/cover property/cover sequence 的结构化 report。
- 通过 `export.code_coverage` 导出分 instance、分 metric 的 JSON/XOUT/raw URG bundle；
  `export.functional_coverage` 与 `export.assert` 同时保留 URG 原文并导出结构化 JSON/XOUT gap。

## CLI 入口

```bash
tools/xcov --json -
tools/xcov --stdio-loop
tools/xcov_lsf --json -  # 仅无 MCP 且必须经 LSF 时
```

一个 native stdio-loop 最多一个 live xcov session；需要多个 VDB session 时，由 MCP 或
`xcov_lsf` 内部 manager 为每个 session 启动独立 loop（LSF 下即独立 `bsub -I` job）。

本文件只讲原生 `xcov.v1` JSON envelope。MCP tool 参数和 MCP session 请使用
`xverif-mcp`；SDK-free LSF 的同 envelope 入口见 `xverif-admin`。

普通 coverage 查询与三类 gap 导出固定使用 URG，不加载 NPI。只有 exclusion
处理才惰性加载 pynpi、打开 VDB 并执行必要遍历；真实 exclusion 需要 Synopsys
license，受限沙箱内 license 可能不可达。

离线 Python 自定义 coverage 报告也使用 x-npi 的 `x_npi.urg`：固定命令为
`$VCS_HOME/bin/urg -full64 -dir <vdb> -report <staging> -xml_verbose -format text -show summary`，
已有 exclusion 时只追加 `-elfile <el>`。Python NPI coverage wrapper 没有 bulk summary，必须按
instance/metric/object/bin 全树遍历且容易重复计入 aggregate/leaf，因此不再用于 coverage read。
x-npi 的 NPI coverage helper 只保留 exclusion target 遍历和 EL load/set/save/unload；CSV→EL
内建 indexed resolver，不依赖项目模块或 xcov。code/assertion 按 scope+metric 裁剪，functional
受 pynpi 限制扫描该类全树；每个非空 kind 固定预检、应用两遍，不按 CSV 行重扫。CSV reason
是 sidecar，原生 EL 无法无损转换回带 reason 的 CSV。`+` 仅能用于 URG help 明确声明的 metric
list（如 `-show brief line+cond`），不能写成 `-show summary+tests` 组合多个信息类别。

## Exclusion 关键生命周期

> **不要在持久化前关闭 session。** `exclude.add` 的 reason 仅保存在当前 session 内存中；
> `session.close`、进程退出或 session 丢失都会永久丢失尚未导出的 reason。必须先成功执行
> `exclude.csv.export`，再执行 `export.exclude`，最后才能关闭 session。

Coverage 分析和 exclusion 的标准顺序：

1. 打开 VDB session。
2. 按用户需要选择一种初始状态：用 `exclude.load` 导入 EL、用 `exclude.csv.apply` 导入四类
   CSV，或不加载任何 exclusion。不要自动选择或静默 fallback。
3. 先用 `scope.summary`、`scope.children`、`code_coverage.summary` 查询覆盖率。
4. 用 `export.code_coverage`、`export.functional_coverage` 或 `export.assert` 导出具体缺口，不能
   只依据压缩摘要决定排除。
5. 对每个 gap 选择补充激励，或调用 `exclude.add` 并为每个条目提供具体非空 `reason`。
   容器级目标使用 `exclude.instance.add/remove` 或 `exclude.functional.add/remove`：instance 默认
   只作用于 self，`recursive=true` 只展开 fixed URG XML 的真实 instance；functional 仅支持
   covergroup、coverpoint、cross。module、wildcard、regex 均不支持。
6. 重新查询覆盖率并再次导出具体缺口，确认目的没有退化。
7. 调用 `exclude.csv.export` 原子合并 reason-bearing CSV；随后调用 `export.exclude` 保存 EL。
8. 确认 CSV 和 EL 均成功落盘后，才允许关闭 session。

EL 不保存 reason。从 EL 加载的既有 exclusion 无法补回原因；`exclude.csv.export` 会明确告警，
并只导出当前 session 中已知 reason 且具有可移植 CSV 身份的条目。CSV 是 reason 的持久化来源，
EL 是 Synopsys 原生 exclusion 状态的持久化来源，两者都应在关闭前导出。
`export.exclude.summary.native_entry_count_known=false` 表示当前 NPI save 接口不能返回 EL 内
原生条目数；不要把 `session_reason_record_count` 或 `loaded_el_file_count` 解释为排除条目数。

## 常用请求

open：

```json
{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"merged.vdb"},"args":{"name":"cov0"}}
```

assert summary：

```json
{"api_version":"xcov.v1","action":"assert.summary","target":{"session_id":"cov0"}}
```

code coverage export（首次读取同一 VDB/selection/EL 时生成并缓存固定 URG summary；
后续命中缓存，不再次调用 URG）：

```json
{"api_version":"xcov.v1","action":"export.code_coverage","target":{"session_id":"cov0"},"args":{"scopes":["uart_tb.u_uart"],"metrics":["line","toggle"],"output":{"path":"coverage_artifacts"}}}
```

按导出 gap 添加 exclusion；每个条目必须单独给出原因：

```json
{"api_version":"xcov.v1","action":"exclude.add","target":{"session_id":"cov0"},"args":{"exports":[{"path":"/abs/path/branch.json","items":[{"gap_id":"B0001","reason":"规格禁止该模式组合"},{"gap_id":"B0002","reason":"该分支仅用于失效保护"}]}]}}
```

关闭 session 前先导出 reason-bearing CSV，再导出原生 EL：

```json
{"api_version":"xcov.v1","action":"exclude.csv.export","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions"}}
```

```json
{"api_version":"xcov.v1","action":"export.exclude","target":{"session_id":"cov0"},"args":{"output":{"path":"coverage_exclusions/merged.el"}}}
```

functional coverage export（输出目录内保留 `grpinfo.txt`，并生成 `functional.json`、
`functional.xout`；gap ID 为 `FC0001` 起）：

```json
{"api_version":"xcov.v1","action":"export.functional_coverage","target":{"session_id":"cov0"},"args":{"output":{"path":"functional_coverage"}}}
```

assert export（输出目录内保留 `asserts.txt`，并生成 `assert.json`、`assert.xout`；gap ID 为
`A0001` 起）：

```json
{"api_version":"xcov.v1","action":"export.assert","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","output":{"path":"assert_coverage"}}}
```

## 读取规则

- 先看 `ok`。
- 看 `summary.matched_count/returned/truncated/output_path/note`。
- coverage item 关注 action 当前返回的字段；不要假设所有 action 都输出
  `metric/type/name/full_name/covered/coverable/missing/status/evidence.file/evidence.line`。
- coverage pct 用 `covered/coverable`，不要用 hit count 代替覆盖率。
- 保留 `excluded/unreachable/illegal` 状态，不要误判为普通 hole。
- 交互查询优先用 `scope.summary`、`scope.children`、`scope.search`、
  `code_coverage.summary` 看层次覆盖率。
- `scope.summary` 返回扁平覆盖率字段；不要期待 `metrics={...}`，也不要期待
  parent/depth/type/def_name 或 summary source file/line evidence。
- `scope.children` 和 `scope.search` 每项只返回 `name/full_name/coverage_pct`。
- `code_coverage.summary` 不输出 `name/full_name/functional_pct`。
- `code_coverage.summary` 只支持 `group_by=metric|scope`；summary query 固定使用 merged
  selection，不接受 `test` selector，也不支持 source file/type 聚合。
- `code_coverage.summary` 和 `scope.*` 支持 `query.include_patterns` /
  `query.exclude_patterns` 通配过滤；只支持 glob `*`、`?`，不要使用 regex。
- `functional_coverage.summary` 不输出
  `metric/name/full_name/score_basis/score_item_count/raw_covered/raw_coverable/raw_missing`，
  也不输出 `raw_coverage_pct`；只支持 `covergroup|coverpoint|cross`，不支持 bin summary。
- scope 父节点直接使用 URG 已提供的 subtree metrics；多 metric `coverage_pct` 是所选 metric
  percentages 的算术平均，不要把不同 metric 的 covered/coverable 相加。
- xout 的 `items:` 是对齐纯文本表格，不是 Markdown 表格；JSON 响应结构不变。
- 详细 code coverage 未覆盖项使用 `export.code_coverage` 的分 metric JSON/XOUT 查看；
  functional/assertion 使用各自 export action 的 `functional.xout`/`assert.xout`，不要只读
  `grpinfo.txt`/`asserts.txt` 摘要。
- functional/assert XOUT 第一行是字段表头，后续每行一个未覆盖 gap；用 scope、kind、name、
  covergroup、coverpoint、cross、bin 判断具体需要补哪种激励，不要只按 gap 数压缩。
- `export.code_coverage` 不输出 Markdown。bundle v2 为每个具体 instance 建立独立目录，
  按 metric 输出 JSON/XOUT；所有 metric 共同引用 bundle 根目录唯一的
  `raw/modinfo.urg.txt`，不再复制相同 URG 原文。先读 `navigation.xout` 选择子层级，再读
  metric XOUT 获取目标 instance 自身的具体缺口。
- branch 使用 `xcov.code_coverage.branch.v2`：相同 decision path 的缺口合并为一个 group，
  先用字段表描述 marker 对应的源码 decision，随后紧接真值表列出各 `gap_id` 的
  marker value；这些行均为未覆盖缺口，因此不重复输出固定的 status 列；`-` 表示该
  decision 在这条路径中未求值。Decision kind 支持 `if/case/casez/casex/ternary`；
  多行三目的 `at` 指向 predicate 实际行；真值表中的 `0/1` 直接表示 predicate 的
  false/true 分支。
- line 使用 `xcov.code_coverage.line.v2`：只输出有缺口的过程块，先读 context 表的
  kind/at/covered/coverable/missing/pct，再读紧邻 uncovered 表的 gap_id/at/statement。
- condition 使用 `xcov.code_coverage.condition.v2`：condition 表给出位置与完整表达式，
  terms 表解释 marker，uncovered 真值表给出需补 values。相同位置、terms、values 的
  EXPRESSION/SUB-EXPRESSION 合并为一个 gap；`coverage_object_gap_count` 是 URG 原始
  missing object 数，`gap_count` 是 AI 实际需要处理的语义 gap 数；三目 condition
  的 `0/1` 同样直接表示 false/true 分支。
- fsm 使用 `xcov.code_coverage.fsm.v2`：实例内不同 FSM 分段输出，每段先给出 transition
  coverage，再以 `gap_id/kind/object/at` 表格逐行列出 state、transition 或 sequence 缺口。
- `exclude.add.args.exports` 接受 metric JSON 绝对路径及 `items` 数组；每项必须包含
  `gap_id` 和非空 `reason`。JSON 只包含 `xcov.urg_semantic.v1` 语义身份，导出阶段
  不启动 NPI。真正执行 `exclude.add` 时先用 URG hierarchy 拒绝未知 scope，再惰性
  打开 NPI 并做必要遍历，将所选语义 gap 唯一解析为临时 target；非 FSM 失败整批回滚，
  只有 FSM 允许返回明确的 `partial_success` 和逐 gap 失败原因。
- `exports` 支持 code、assert 与 functional 的结构化 JSON；不持久化 NPI handle、
  traversal path 或数据库内部唯一 ID。旧 artifact 对应的对象若已被排除并从 NPI score
  视图隐藏，应重新导出当前 gap，不能绕过 wrapper 调低层 `handle_by_name` 猜测对象。
  不要构造或发送已删除的 `args.selectors`。`coverage_ref` 只在生成它的 session 内有效。
- 容器 action 全部先预检再原子设置。递归 instance 的 reason 展开为 exact target metadata；
  remove 只按已记录 ownership 移除，不根据当前 XML 重新扩大范围。同一 exact target 若被不同
  reason 或 expansion root 请求，返回 `TARGET_OWNERSHIP_CONFLICT`。
- `container_exclusions.csv` 是可选第四份 sidecar，保存 instance/group/point/cross exact target；
  缺少它的旧三文件目录继续合法。compile 成功后发布并 union-load 四份 EL。
- 同一 session 内重复 add 同一身份但提供新 reason 时，内存 reason 更新；若
  `exclude.csv.export` 发现目标 CSV 已有同一身份但 reason 不同，则三类文件均不写入，必须
  先由用户决定保留哪一个原因。
- toggle coverage 的 NPI 对象可能没有源码行号；CSV 允许 toggle 的 `line` 为空，并通过
  `scope + signal + transition` 精确解析。其它 coverage 类型仍要求可验证的源码行号。
- `navigation.xout` 的覆盖率是 subtree 统计；metric XOUT 的覆盖率是 self 统计，不得混用。
- `assert.summary` 输出基础覆盖率和 attempts/real successes/without attempts；不输出
  kind/category/severity/failures/incomplete/first_match/file/line。需要完整 assertion
  Markdown 时使用 `export.assert`。
- 找不到 NPI API 支撑的 URG 字段时，不要做 fallback，不要要求 xcov 返回占位字段；应说明该字段做不到。

## 排障

- 普通查询失败：检查 URG、VDB 和固定六件套错误，不要切换到 NPI fallback。
- URG summary 默认缓存于 `.xverif/xcov/cache/urg-summary`；可用
  `XVERIF_XCOV_CACHE_DIR` 指定共享可见的绝对缓存根。`session.status` 的
  `cached_indexes.state/key/hit/urg_execution` 可区分尚未读取、cold miss、warm hit 与
  direct/LSF job；warm hit 的 `submitted=false`。
- 内层 URG LSF 必须显式设置 `XVERIF_XCOV_URG_BACKEND=lsf` 和独立的
  `XVERIF_XCOV_URG_QUEUE`，可选 `XVERIF_XCOV_URG_RESOURCE`；它固定使用 `bsub -K`，不继承
  外层 session queue，也不会因为存在 `XVERIF_LSF_BSUB` 自动启用。VDB、EL、cache、report、
  hier 与 log 必须是计算节点可见的绝对共享路径。
- `XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC` 管 PEND→running，
  `XVERIF_XCOV_URG_RUN_TIMEOUT_SEC` 管 URG 执行；timeout/cancel 使用 job id 或唯一 job name
  bkill，失败不会 fallback 到 direct。
- cache key 包含 VDB 内容、run manifest、URG provenance/固定参数、merged selection 和
  EL 内容；EL 变更会生成新 key。损坏 entry 会被隔离并重新生成，不会降级为 NPI 读取。
- 缓存默认 soft admission 阈值为 20 GiB/128 entries，可用
  `XVERIF_XCOV_CACHE_MAX_BYTES` 和 `XVERIF_XCOV_CACHE_MAX_ENTRIES` 调整。warm hit 是纯只读
  校验；cold miss 通过 per-key 原子 claim 保证同 key 只运行一次 URG。不同 key 并发 cold
  miss 不做全局 reservation，可能同时通过同一已发布 entry 快照而超过阈值，因此该配置
  不是并发 hard bound。超限后新的 cold miss 返回 `XCOV_CACHE_CAPACITY_EXCEEDED`；需要在
  显式维护窗口清理旧 immutable entry，不会在 action 返回路径同步 LRU 驱逐。
- exclusion 的 license/NPI 错误：在沙箱外确认 Verdi/NPI 和 license server。
- action 参数不确定：先用原生 `actions` 和 `schema` action 查询。
- 大结果：设置 limit，必要时 `overflow:"to_file"` 或 output path。
- MCP/LSF/session 问题：改用 `xverif-mcp` 对应 troubleshooting。
