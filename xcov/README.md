# xcov

`xcov` 是面向 AI/MCP 的 VCS/Verdi coverage database 查询工具。它读取
`simv.vdb`、`merged.vdb`，接受 `xcov.v1` JSON 请求，默认返回紧凑的
`xout`；需要机器 JSON 时使用 `tools/xcov --json -`。响应格式属于 CLI transport
选项，不是 request 字段；top-level `output` 会被严格 schema 拒绝。

xcov 的 summary 读取固定使用 URG
`-full64 -xml_verbose -format text -show summary` 生成的 typed `session.xml`
和五个 summary 文本文件，不生成完整 HTML、`modinfo.txt` 或 `grpinfo.txt`。
code、assertion 和 functional coverage 按各自 XML `type` 建模；详细 gap 导出
使用受限 URG text report。公开 summary 只发布该固定产物能够稳定支持的字段。

action、session、transport、backend 或 VDB 查询失败时不会静默切换 surface、
backend、data source 或测试层级。失败返回结构化错误；任何不同路径必须由调用方
显式发起。

## 快速开始

一次性 JSON 查询：

```bash
printf '%s\n' '{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"merged.vdb"},"args":{"name":"cov0"}}' \
  | tools/xcov --json -
```

MCP/长会话使用 stdio-loop：

```bash
tools/xcov --stdio-loop
```

stdio-loop 启动后输出 `protocol:"xcov-stdio-loop"` ready 行，后续每行接收一个
JSON request，并返回包含 `xout` 和 `json` payload 的 JSONL envelope。stdio 请求
一个 native stdio-loop 进程最多拥有一个 live xcov session；第二个不同 name 的
`session.open` 返回 `SESSION_CAPACITY_EXCEEDED`。MCP 多 session 由 manager 为每个 session
分别启动独立 `tools/xcov --stdio-loop`，不在同一 native loop 内复用多个 VDB。
stdio 请求
必须显式提供非空 `request_id`；历史 `id` 字段不是别名，会被严格拒绝。退出控制
帧只有以下三个字段，缺字段或增加 `target/args` 等未知字段都会返回
`SCHEMA_INVALID`：

```json
{"api_version":"xcov.v1","request_id":"quit","action":"stdio.quit"}
```

普通 session/read/export 路径不会加载 pynpi。只有 `exclude.*`、
`exclude.csv.*` 和 `export.exclude` 首次需要修改或读取原生 exclusion 状态时，
才在该 session 内惰性创建一次 NPI 上下文；NPI 诊断输出会导向 stderr，stdout
保持机器可解析。

## 真实 exclusion NPI 运行

URG coverage 查询需要 Synopsys URG；原生 exclusion 处理另需 Verdi/Python NPI
和 license。按项目规则，NPI、VCS、VIP、真实 coverage probe 必须在沙箱外运行。

已验证的本地形态：

```text
Python 3.11
VERDI_HOME=<verdi-install>
示例 VDB=<uart-example>/sim/merged.vdb
```

exclusion 真实回归使用正式 fixture/suite：

```bash
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-prepare xcov.exclusion
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate nightly --xverif-suite xcov.exclusion_npi
```

## MCP 工具

`xverif_mcp` 暴露 xcov stateful backend：

```text
xverif_cov_session_open
xverif_cov_session_list
xverif_cov_session_close
xverif_cov_query
xverif_cov_list_actions
xverif_cov_get_schema
```

环境变量：

- `VCS_HOME`：必填；URG 只允许使用规范化后的 `$VCS_HOME/bin/urg`，不会从 `PATH`
  查找或改用其它安装。
- `VERDI_HOME`：首次 exclusion 操作时必填；pynpi/cov/npisys 必须全部来自该安装的
  `share/NPI/python`，不会接受预加载的外部同名模块。
- `XVERIF_MCP_ENABLE_COV=0`：隐藏 coverage 工具。
- `XVERIF_XCOV_BIN`：覆盖 xcov 可执行文件。
- `XVERIF_XCOV_PYTHON`：覆盖 xcov Python runtime。
- `XVERIF_XCOV_VERDI_HOME`：覆盖 `VERDI_HOME`。
- `XVERIF_XCOV_LOG_DIR`：覆盖日志目录。
- `XVERIF_XCOV_LOG=0`：关闭日志。
- `XVERIF_XCOV_EXPORT_ROOTS`：用 `os.pathsep` 分隔的绝对既存目录；只有同时设置
  `output.allow_absolute_path=true` 且目标位于这些根目录之一时，才允许绝对导出路径。
- `XVERIF_XCOV_CACHE_DIR`：覆盖默认 `.xverif/xcov/cache` 根目录；summary entry
  位于其 `urg-summary/` 子目录，session-owned exclusion working dir 位于其 `sessions/`
  子目录。两者不会再分别落到不同根。
- `XVERIF_XCOV_CACHE_MAX_BYTES`：cold build 的 cache 软准入字节阈值，默认 20 GiB。
- `XVERIF_XCOV_CACHE_MAX_ENTRIES`：cold build 的 cache 软准入 entry 阈值，默认 128。
- `XVERIF_XCOV_URG_BACKEND`：每次 URG 的执行 backend，只接受 `direct|lsf`，默认
  `direct`；不会从外层 `XVERIF_MCP_BACKEND` 或仅存在的 `XVERIF_LSF_BSUB` 推断。
- `XVERIF_XCOV_URG_QUEUE`：内层 URG LSF queue；backend=lsf 时必填。
- `XVERIF_XCOV_URG_RESOURCE`：可选内层 URG LSF resource string。
- `XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC`：等待 batch job 从 submitted/PEND 进入 running
  的超时，默认 120 秒。
- `XVERIF_XCOV_URG_RUN_TIMEOUT_SEC`：job running 后的 URG 执行超时，默认 600 秒。

固定 URG summary 使用内容寻址 cache。key 包含 VDB 内容 hash、可选 run-manifest
hash、URG 绝对路径/release/文件身份、固定 argv、parser/cache version、merged selection
和当前 EL hash。每个 entry 校验六文件 hash/size 与 semantic counts；per-key `fcntl`
per-key claim 保证同 key 并发 miss 只执行一次 URG，完成后经 fsync 和 atomic rename
发布。容量采用 `best_effort_soft_admission`：cold build 只检查当时已发布 entry，不为
其它 key 的 staging 预留条目或字节，因此不同 key 同时 cold miss 时可超过配置阈值；
超限后新的 cold miss 返回 `XCOV_CACHE_CAPACITY_EXCEEDED`，warm hit 仍可读取，直到显式
维护清理 immutable entry。该阈值不是并发 hard bound，也不会在 action 热路径自动驱逐。
损坏 entry
隔离后重建，超过 24 小时的 abandoned staging 才清理。`session.status` 的
`cached_indexes.state/key/hit/urg_execution` 可观察当前 index、cold/warm、direct/LSF、
submitted queue/resource、job name/id 和 exit status。warm hit 的 `submitted=false`，不会
调用 bsub。

内层 LSF 固定执行：

```text
bsub -K -J <job> -q <XVERIF_XCOV_URG_QUEUE> [-R <resource>] <urg> -full64 ...
```

`XVERIF_LSF_BSUB`/`XVERIF_LSF_BKILL` 只覆盖命令入口；不得预置 `-I/-K/-J/-q/-R`。
VDB、EL、cache、report、hier 和 log 必须位于登录节点与计算节点共同可见的绝对路径。
runner 会把 URG 的路径参数规范化为绝对路径，但不会把本地目录复制到计算节点。startup、
run timeout 或取消会按 job id（尚未取得 id 时按唯一 job name）执行 bkill，并终止本地
bsub process；失败不会改走 direct。

## 常用请求

打开 session：

```json
{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"merged.vdb"},"args":{"name":"cov0"}}
```

`session.open` 的公开 `args` 只有 `name` 和可选
`exclusion_policy:"default|strict"`。打开 session 只生成/读取固定 URG summary，
不会 import pynpi 或调用 `cov.open`。首次 exclusion 操作才创建 NPI 上下文；此时
`strict` 在双参数接口上把 `cov.ConfigOpt.ExclusionInStrictMode` 传给 `cov.open`，
拒绝把已覆盖对象设为 report-time exclusion；xcov 从不公开 `ExcludeByStmtLevel`。同名
alive session 返回 `SESSION_EXISTS`；同一 native 进程的其它 alive name 返回
`SESSION_CAPACITY_EXCEEDED`。xcov 不比较旧、新 VDB，不复用旧 backend，也不隐式关闭后重开。
需要切换 VDB 时，调用方必须先显式执行 `session.close`，再发起新的
`session.open`。`fake`、`reuse`、`reopen` 都不是公开参数，字符串
`target.vdb:"fake"` 也没有特殊含义；`FakeCoverageBackend` 只允许测试通过
`SessionManager` 的 backend factory 注入。

首次 exclusion 操作会检查当前 pynpi 的真实 `cov.open` 签名。单参数旧版在默认模式调用
`cov.open(vdb)`；双参数版本调用 `cov.open(vdb, config_opt)`。单参数旧版不支持 strict，
会返回明确错误；不会先调用失败再 fallback。

### 可复现输入：run manifest

`target.run_manifest` 是可选的 provenance gate。提供时，xcov 在运行 URG 或打开
Python NPI 前校验 `xcov.run-manifest.v2` 的 `state:"published"`，以及相对 manifest 文件的
`resources.vdb.path`、资源类型、`sha256-entry-tree-v2`、真实 regular-file 总字节数、
file/directory/symlink 计数和 SHA-256。目录摘要对 entry type、路径长度、路径、文件大小与
独立内容摘要做无歧义编码；symlink 只编码 link target 且从不跟随。不匹配返回
`RESOURCE_PROVENANCE_MISMATCH`，不会启动后端；未提供则保持既有打开行为。

```json
{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"merged.vdb","run_manifest":"run-manifest.json"},"args":{"name":"cov0"}}
```

```json
{"schema_version":"xcov.run-manifest.v2","state":"published","resources":{"vdb":{"path":"merged.vdb","kind":"directory","hash_version":"sha256-entry-tree-v2","size_bytes":4096,"file_count":8,"directory_count":3,"symlink_count":1,"sha256":"<64-hex-sha256>"}}}
```

查询 code coverage summary：

```json
{"api_version":"xcov.v1","action":"code_coverage.summary","target":{"session_id":"cov0"},"args":{"group_by":"metric","metrics":["line","toggle","branch","condition","fsm"]}}
```

按通配过滤 scope：

```json
{"api_version":"xcov.v1","action":"scope.search","target":{"session_id":"cov0"},"args":{"query":{"include_patterns":["*u_uart*"],"exclude_patterns":["*uvm*"],"match_field":"full_name"}}}
```

导出 code coverage 详情（**每次 export 触发一次 URG，尽量一次提交多个 instance**）：

```json
{"api_version":"xcov.v1","action":"export.code_coverage","target":{"session_id":"cov0"},"args":{"scopes":["uart_tb.u_uart","uart_tb.u_ctrl"],"metrics":["line","branch"],"output":{"path":"coverage_artifacts"}}}
```



assert 汇总：

```json
{"api_version":"xcov.v1","action":"assert.summary","target":{"session_id":"cov0"}}
```

导出 code coverage 未达标项：

```json
{"api_version":"xcov.v1","action":"export.code_coverage","target":{"session_id":"cov0"},"args":{"scopes":["uart_tb.u_uart"],"metrics":["line","toggle"],"output":{"path":"coverage_artifacts"}}}
```

导出 functional coverage 未达标 bin：

```json
{"api_version":"xcov.v1","action":"export.functional_coverage","target":{"session_id":"cov0"},"args":{"output":{"path":"functional_coverage"}}}
```

导出 assertion coverage：

```json
{"api_version":"xcov.v1","action":"export.assert","target":{"session_id":"cov0"},"args":{"scope":"uart_tb","output":{"path":"assert_coverage"}}}
```

## Exclusion 管理

仓库长期维护三份 CSV source of truth：

```text
coverage_exclusions/
├── code_exclusions.csv
├── functional_exclusions.csv
└── assertion_exclusions.csv
```

CSV 用 `# source_file=...` 划分连续源码分组；`reason` 必填，同一
源码文件只能出现一个连续分组。CSV 只保存可移植的语义 selector；xcov 不读写、
拼接或解释原生 EL 文本。

原生 EL action：

- `exclude.list`：列出 merged test 的 compile/report-time exclusion，并给出当前
  session 的 `coverage_ref`。
- `exclude.load`：按输入顺序加载一个或多个 EL，使用 pynpi union 语义。
- `exclude.add`：每个 `coverage_ref` 或 export gap 都必须携带非空 `reason`；reason 仅保存在当前 session
- `exclude.remove`：按精确 `coverage_ref` 撤销 report-time exclusion
  before/after，返回 `changed`、`already_in_state`、
  `immutable_compile_time` 或 `failed`。
- `export.exclude`：固定调用 `save_exclude_file(path, "w")`。
- `exclude.unload_all`：仅在 `confirm:true` 时清除全部 report-time exclusion，
  不用于单项删除。

```json
{"api_version":"xcov.v1","action":"exclude.add","target":{"session_id":"cov0"},"args":{"coverage_refs":[{"coverage_ref":"xcovref.v1:<sha256>","reason":"确认无法在当前配置下触发"}]}}
```

`exclude.add` 还可直接消费 `export.code_coverage` 生成的 metric JSON：

```json
{"api_version":"xcov.v1","action":"exclude.add","target":{"session_id":"cov0"},"args":{"exports":[{"path":"/abs/path/branch.json","items":[{"gap_id":"B0001","reason":"非法输入组合"},{"gap_id":"B0002","reason":"规格禁止路径"}]}]}}

关闭 session 不允许静默丢失尚未持久化的 reason。存在 dirty reason 时，普通
`session.close` 返回 `UNPERSISTED_EXCLUSION_REASON` 并保留可继续查询/导出的 live session；
只有显式传入 `{"confirm_discard_reasons":true}` 才关闭并报告丢弃计数。完成排除后应先调用
`exclude.csv.export`，将当前 session 中具备可移植身份的 exclusion 原子合并到四类 CSV；
再调用 `export.exclude` 导出原生 EL。EL 不保存 reason，只有 CSV export/compile/apply
成功才把 reason revision 标记为已持久化；仅从 EL 导入的条目没有 reason，CSV 导出会明确
告警并省略这些条目。

```json
{"api_version":"xcov.v1","action":"exclude.csv.export","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions"}}
```
```

导出 JSON 只保存 `xcov.urg_semantic.v1` 语义身份，不启动 NPI，也不泄露或持久化
NPI traversal path/handle。`exclude.add` 首先用 URG hierarchy 拒绝未知 scope，随后才
惰性启动 NPI，并在 exclusion 阶段做必要遍历，把所选 gap 唯一解析成临时 target。
line/condition/branch/toggle 保持原子提交；只有 FSM 允许因 NPI 不可见对象返回
`partial_success`，响应逐 gap 标明成功或失败。旧 artifact 在目标已被排除后可能因
NPI score 视图隐藏而不再可解析，应重新导出当前 gap，不会调用不稳定的低层查询强行恢复。

```json
{"api_version":"xcov.v1","action":"exclude.load","target":{"session_id":"cov0"},"args":{"paths":["code.el","functional.el","assertion.el","container.el"]}}
```

CSV action：

- `exclude.csv.validate/apply/compile/format` 分别负责静态合同、session 应用、四 EL
  发布和稳定排序；CSV 工作流不读取 Git 状态或 commit。
- apply/compile 对每行要求恰好一个 score object；零匹配或多匹配都会明确失败。
- `compile` 先完成四类 validate/resolve/apply，在同一输出目录写临时 EL；全部成功
  后发布 `code.el`、`functional.el`、`assertion.el`、`container.el`，随后按该顺序重新加载。
  任一记录失败不发布产物，并恢复 compile 前的 session exclusion。
- `format` 默认 check，只有 `write:true` 才写文件。

```json
{"api_version":"xcov.v1","action":"exclude.csv.compile","target":{"session_id":"cov0"},"args":{"directory":"coverage_exclusions","output_directory":"coverage_exclusions"}}
```

## URG 对齐语义

`code_coverage.summary`、`metrics.list` 和 `scope.summary` 直接使用 URG
`session.xml` 的 subtree score：

- Line：`npiCovStmtBin`
- Condition：`npiCovConditionBin`
- Toggle：`npiCovToggleBin`
- Branch：`npiCovBranchBin`
- FSM：`npiCovTransBin`
- Assert：`npiCovAssert`、`npiCovCoverProperty`、`npiCovCoverSequence`

父 scope 的 metric 已经包含 subtree，不能再累加 descendants。多 metric scope 的
`coverage_pct` 按 URG SCORE 语义取所选 metric percentages 的算术平均；因为不同
metric 的计数单位不可相加，多 metric scope 不返回 aggregate covered/coverable/missing。

`functional_coverage.summary` 的 covergroup score 按 URG group 页语义计算：优先取直接
coverpoint/cross coverage 百分比的平均值；交互输出不暴露 score_basis/raw count
等中间计算字段。

## Action 合同

dispatcher 在填充 `request_id/target/args` 默认值前，先使用 action-specific request
schema 校验原始请求；top-level、`target`、`args`、`query`、`sort`、`limits` 和
export `args.output` 的未知字段都会返回 `SCHEMA_INVALID`。handler 返回后、公开输出
前还会使用同一 action 的严格 response schema 校验结果。普通查询只在 `args.limits`
控制 inline 数量；三个 coverage report export 写 Markdown，`export.exclude` 写原生
EL。

惰性 Python NPI exclusion backend 在初始化时绑定唯一的已声明 method/signature 合同，并且每次
调用只执行该签名一次。缺失方法、参数不匹配、调用异常、遍历返回非 iterable，
以及必需事实类型错误都会返回 `NPI_CONTRACT_VIOLATION`，错误中包含 operation、
method、expected_signature 和 cause；不会改用零参数签名，也不会把异常转换成
`None` 或空列表。此类错误响应的 `scan_complete` 和 `analysis_complete` 均为
`false`，不能被当作完整 coverage 结果。

`SessionManager` 会强制把真实 NPI、测试 Fake 和 factory 注入 backend 包装成同一个
严格 adapter。`summary/tests/scopes/items` 在 action 可见前统一校验；coverage item
按 metric/type 明确区分 score-bearing row、context/container 和 assertion count
bin。score 的 primitive、值域、`covered <= coverable`、`missing`、百分比、status
和 evidence 任一不一致都会 fail-closed：真实 NPI 返回
`NPI_CONTRACT_VIOLATION`，注入 backend 返回 `BACKEND_CONTRACT_VIOLATION`。
backend/action 合同不接受 `-1` score/count sentinel；不适用值必须是 JSON `null`。
Python NPI 层只把文档定义的 SDK “不适用”返回值映射为 `null`，未知或位置错误的
负值仍由统一边界拒绝。

- `scope.summary`：返回当前层次的扁平覆盖率字段，例如
  `coverage_pct`、`line_pct`、`toggle_pct`、`branch_pct`、`condition_pct`、
  `fsm_pct`、`assert_pct`、`functional_pct`；不输出 summary XML 无法稳定提供的
  file/line evidence，也不输出 parent/depth/type/def_name。
- `scope.children` / `scope.search`：只返回 `name/full_name/coverage_pct`，用于定位
  hierarchy 名称和快速查看当前覆盖率。
- `code_coverage.summary`：只支持按 `metric` 或 `scope` 汇总代码覆盖率；不输出
  name/full_name/functional_pct，不支持 source file/type summary。
- `export.code_coverage`：详细 code coverage 导出；首次读取同一内容身份时生成 URG
  summary，后续命中缓存。尽量一次提交多个要查看的 instance。按 scope 分目录、按 metric
  输出 JSON/XOUT；完整 URG 原文只在
  bundle 根目录的 `raw/modinfo.urg.txt` 保存一份，各 metric 通过相对路径引用。
- `functional_coverage.summary`：按 covergroup、coverpoint 或 cross 汇总功能覆盖率，
  不输出 metric/name/full_name/score_basis/score_item_count/raw_* 字段，包括
  raw_coverage_pct；summary 不提供 bin 级结构。
- `query.match_field` 与 `sort.by` 都是 action-specific enum；拼错或选择该 action
  不支持的字段会在执行前返回 `SCHEMA_INVALID`。显式 `metrics`/`levels` 必须是
  非空数组，空数组不会回退成默认全集。
- `code_coverage.summary` 的 `metrics` 只接受 line/toggle/branch/condition/
  fsm/assert；functional metric 只能通过 `functional_coverage.*` 查询。


- `assert.summary`：输出 assert/cover property/cover sequence 的基础覆盖率和
  attempts/real successes/without attempts；不输出 kind/category/severity/failures/
  incomplete/first_match/file/line。详细报告请使用 `export.assert`。

## 文件导出

`export.code_coverage` 不输出 Markdown。它要求 `scopes` 指定一个或多个具体 elaborated
instance，在 `output.path` 下建立秒级时间戳目录，并为每个 instance、每个请求 metric
分别输出 JSON 和 XOUT；`xcov_code_coverage_bundle.v2` 只在根目录保存一份
`raw/modinfo.urg.txt`。`navigation.json/xout` 使用总体 `session.xml`
提供直接子实例的 subtree 统计；metric detail 严格只表示所选 instance 自身。

Line 与 condition detail 使用 v2 分组合同：line 只列出存在缺口的过程块，以 context 表
发布局部覆盖率并紧接 uncovered statement 表；condition 按源码位置和 marker term 分组，
同一 values 的 EXPRESSION/SUB-EXPRESSION 合并为一个语义 gap。Condition 的
`coverage_object_gap_count` 对应 URG 原始 missing，`gap_count` 对应实际需要补的语义
组合。Branch v2 支持 if/case/casez/casex/ternary decision，连续赋值三目可独立成组，
过程内三目保留在所属 decision path。三类 XOUT 的 uncovered 表都不重复输出固定 status。

`export.functional_coverage` 与 `export.assert` 保持各自既有合同。

## XOUT 输出

one-shot XOUT 使用人读 summary/filter/table 格式：

```text
@xcov.v1 ok action=<action> request_id=<request-id>

summary:
  total_count: 2

items:
  name  coverage_pct
  top   95.0
```

renderer 不使用隐藏行数上限，也不输出 `XOUT_BEGIN/XOUT_END`。XOUT 首先用于减少
JSON 标点、键名和重复层级带来的 token 开销，易读性是附带收益；只有调用方确实
需要完整结构、字段级程序访问或无损消费时才选择 JSON。stdio-loop 的 JSONL
envelope 负责 framing。
stdio-loop 外层承载 `request_id/api_version/action/ok`；内层 XOUT payload 不重复这些
framing 字段，header 仍保留 action 合同标识。

所有成功与错误响应都使用统一完整性字段：
`total_count/returned_count/response_truncated/scan_complete/analysis_complete/`
`truncation_scopes`。普通成功响应不再生成 `output_path:null` 等无意义 summary 字段。

导出路径使用 `args.output.path`：

- 相对路径写到 `.xverif/xcov_exports/`。
- 包含 `..` 的路径会被拒绝。
- 绝对路径必须显式设置 `output.allow_absolute_path=true`，并位于
  `XVERIF_XCOV_EXPORT_ROOTS` 声明的根目录内。
- 任一中间路径为 symlink、规范化后逃逸允许根或发布预算超限都会 fail-closed；要求新建的
  report bundle 还会拒绝既有目标。文件/目录在同一文件系统 staging 中完整生成、校验并
  fsync 后才发布；CSV 多文件更新会先保留逐文件 backup，任一步失败即按逆序恢复。

请求 transport 上限为 1 MiB；inline response 上限为 16 MiB，并硬限制最多 10,000 行。
固定 summary 的单 artifact 上限为 1 GiB、六件套合计 2 GiB；scope、typed row、gap、CSV
文件/record/field 也有前置 hard budget。超限返回 `REQUEST_BUDGET_EXCEEDED`、
`RESPONSE_BUDGET_EXCEEDED` 或 `RESOURCE_BUDGET_EXCEEDED`，不会先构造无限内存对象再截断。

## 日志

xcov 日志默认写入：

```text
~/.xverif/xcov/sessions/<session_id>/owners/<pid-start_nonce>/session.json
~/.xverif/xcov/sessions/<session_id>/owners/<pid-start_nonce>/logs/actions.ndjson
~/.xverif/xcov/backend/sessions/<session_id>/owners/<pid-start_nonce>/logs/lifecycle.ndjson
~/.xverif/xcov/backend/sessions/<session_id>/owners/<pid-start_nonce>/logs/transport.ndjson
```

日志事件包含 `ts/event_id/pid/layer/component/session_id/action/phase/ok/context`，
不会记录完整大型 `items` payload。每个进程实例只写自己的 owner shard；manifest 使用同目录
唯一临时文件、fsync 和原子替换，NDJSON 使用进程内 mutex 与 `O_APPEND` 单记录写入。日志或
manifest 写入失败不会伪装成功，
`session.status/session.list/session.doctor` 的 `observability` 会报告 failure count 和最近错误，
stderr 只输出 operation/error type，不泄露路径或 payload。

## 审阅材料

- API 能力审计：[docs/coverage-api-capability.md](docs/coverage-api-capability.md)
- 全量 action 与 `xout` 合同样例：[docs/action-xout-examples.md](docs/action-xout-examples.md)

## 大型 summary 回归 fixture

`xcov.large_summary` 只在仓库中保存 generator、Makefile recipe 和 semantic probe，不保存
生成 RTL、simv、VDB 或 URG report。正式准备入口为：

```bash
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-prepare xcov.large_summary
```

generator 固定产生 3,000 个不同 leaf module 和 3,000 个实例，加 top 共 3,001 个 instance
scope；每 leaf 有 25 个端口，其中 10 个为 128-bit data port，仿真 256 cycles，RTL 恰好
375,053 行。VCS recipe 使用 `-full64`，probe 再使用
`urg -full64 -xml_verbose -format text -show summary` 验证六件套、root 六类 metric、functional
和 assertion typed node。FixtureStore fingerprint 覆盖三个 source、builder/probe argv、timeout、
`VCS_HOME` 和 `VERDI_HOME` 工具兼容身份；只有 `--xverif-prepare` 构建，regression/nightly
只消费已发布 cache，cache miss 是 usage error，不会自动仿真或降级。

正式消费门禁：

```bash
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest \
  --xverif-gate regression --xverif-suite xcov.large_summary
```

该 suite 验证 3,001 scopes、code/assertion/functional 三类 typed IR、root SCORE、read-only
零 pynpi、cold 恰好一次 URG 和 warm 零 URG；1,000/10,000 scope 的严格 2N adjacency 操作数
门禁保留在 `xcov.unit`。

## 当前限制

- summary 查询固定使用 merged selection；请求 schema 不接受 per-test `test` selector。
- source file/type 和 functional bin 不属于 summary 合同；需要具体 gap 时使用对应 export。
