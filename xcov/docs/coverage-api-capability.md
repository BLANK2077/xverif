# xcov Coverage API 能力审计

本审计用于约束 xcov 公开接口：只有 Verdi/Python NPI 文档、headers 和真实 VDB
probe 证实可获取的字段才能进入 schema。未证实字段不做 fallback，不解析 URG
HTML，不返回占位 note。

## 本地依据

- Verdi 安装：`$VERDI_HOME=<verdi-install>`
- Python Coverage 文档：`$VERDI_HOME/doc/Python_NPI_Coverage.pdf`
- 可检索文本：`$VERDI_HOME/doc/.Python_NPI_Coverage.txt.gz`
- Coverage C header：`$VERDI_HOME/share/NPI/inc/npi_cov.h`
- 真实 VDB probe：`<uart-example>/sim/merged.vdb`

真实 probe 已在沙箱外运行，原因是 pynpi/VDB/license 访问属于 NPI/EDA 动作。

## 已证实能力

### score-bearing object

`npi_cov.h` 和 Python Coverage 文档证实以下 object type 存在，并已被 xcov 用于
URG score 对齐：

- line：`npiCovStmtBin`
- toggle：`npiCovToggleBin`
- condition：`npiCovConditionBin`
- branch：`npiCovBranchBin`
- fsm：`npiCovTransBin`
- assert：`npiCovAssert`、`npiCovCoverProperty`、`npiCovCoverSequence`

真实 VDB probe 已验证这些对象可通过 Python Coverage handle 遍历，并可读取
`covered(test)`、`coverable(test)`、`count(test)`、`file_name()`、
`line_no(test)` 和已声明的 `has_status_*(test)`。

### toggle transition evidence

文档和 header 证实：

- `npiCovSignal`
- `npiCovSignalBit`
- `npiCovToggleBin`
- `npiCovIsPort`
- `npiCovToggleType`

Python method 映射后可用：

- `is_port(test)`
- `toggle_type(test)`
- `covered(test)`
- `coverable(test)`
- `file_name()`
- `line_no(test)`

真实 VDB probe 证实 `npiCovToggleBin.toggle_type(test)` 返回 `npiCovToggle01` 或
`npiCovToggle10`，可聚合为 `0 -> 1` 和 `1 -> 0`。

公开接口：`export.code_coverage` 中的 toggle JSON/XOUT 记录，只表达 signal/bit、
`0 -> 1` 是否覆盖、`1 -> 0` 是否覆盖和 file:line。交互式 `code_coverage.holes`
只输出 hierarchy 覆盖率概览，不展开 bit 明细。

不公开字段：`direction`。当前 Python Coverage API 文档、`npi_cov.h` 和真实 VDB
probe 只证实 `is_port()`，未证实 coverage handle 可直接提供 port direction。

### assert report

文档和 header 证实：

- `npiCovAssert`
- `npiCovCoverProperty`
- `npiCovCoverSequence`
- `npiCovAttemptBin`
- `npiCovSuccessBin`
- `npiCovFailureBin`
- `npiCovIncompleteBin`
- `npiCovFirstmatchBin`
- `npiCovSeverity`
- `npiCovCategory`

Python method 映射后可用：

- `severity(test)`
- `category(test)`
- `count(test)`
- `covered(test)`
- `coverable(test)`
- `file_name()`
- `line_no(test)`
- `child_handles()`

真实 VDB probe 证实 assertion 对象可以读取 `severity/category`，子 bin 可以读取
`Attempt/Success/Failure/Incomplete` count。

公开接口：交互摘要使用 `assert.summary`，完整 Markdown 证据使用
`export.assert`。

### source annotate

Python Coverage API 证实 coverage object 可读取：

- `file_name()`
- `line_no(test)`

不公开字段：`MISSING_ELSE` 等 URG HTML 专有显示标签。当前 Python Coverage API
文档和 probe 没有证实这些标签可取。

### exclusion

当前安装的 Python Coverage API 已证实：

- 新版 `cov.open(vdb, config_opt=0)`，其中
  `cov.ConfigOpt.ExclusionInStrictMode` 用于 strict exclusion policy。
- 旧版 `cov.open(vdb)` 由 xcov 在调用前检查签名并用于默认模式；旧版请求 strict 时
  返回明确不支持错误，不静默忽略 strict，也不捕获 `TypeError` 重试。
- test handle 的 `load_exclude_file(path)`、`save_exclude_file(path, mode)` 和
  `unload_exclusion()`。
- score object 的 `has_status_excluded_at_compile_time(test)`、
  `has_status_excluded_at_report_time(test)` 与
  `set_status_excluded_at_report_time(test, 1|0)`。

xcov 固定用 `save_exclude_file(path, "w")`，不使用 `a/as/ws`；单项 add/remove
固定用 report-time setter，不调用 `set_status_excluded()`。原生 EL 始终由 pynpi
针对当前 VDB 生成或加载，xcov 不解析、拼接或改写 EL 文本。P0 只允许 merged test，
对象 handle 不跨 traversal 缓存；公开 `coverage_ref` 由可读 identity 生成，写操作
会重新遍历并复核恰好一个对象。

`ExcludeByStmtLevel` 虽由 SDK 枚举声明，但本项目明确不公开、不启用。

正式宿主 suite `xcov.exclusion_npi` 使用 `xcov.exclusion` VCS fixture，已覆盖
line/toggle/branch/condition/FSM transition、assert/cover property、functional
covergroup bin 的 report-time add/remove，重复 add 的幂等分类、两份 EL 连续加载
union、strict mode 对 covered/uncovered 对象的差异，以及新进程只通过已保存 EL
恢复 exclusion。

## 实现边界

- 不读取 `urgReport/asserts.html` 或 `mod*.html`，不把 HTML 作为数据源。
- `export.code_coverage` 使用 URG `session.xml` 生成 subtree navigation，并解析严格
  hierarchy 过滤后的单 metric `modinfo.txt` 生成 instance-self JSON/XOUT。
- Line detail 使用 `xcov.code_coverage.line.v2`，按 URG 过程块发布局部覆盖率和未覆盖
  statement；continuous assign 未被 URG 计入 line 时不构造虚假对象。
- Condition detail 使用 `xcov.code_coverage.condition.v2`，按 `LINE` 与 underline marker
  恢复 term，并合并相同位置、terms、values 的 EXPRESSION/SUB-EXPRESSION。原始 object
  数由 `coverage_object_gap_count` 表达，语义 gap 数由 `gap_count` 表达。三目表达式的
  predicate 值 `0` 和 `1` 分别表示 false 和 true 分支。
- Branch v2 的 decision kind 包括 `if/case/casez/casex/ternary`；多行 ternary 的位置
  指向 predicate 实际源码行，source 保存归一化后的完整赋值语句；真值表中的 `0/1`
  直接表示 predicate 的 false/true 分支。
- FSM detail 使用 `xcov.code_coverage.fsm.v2`，解析实例内全部 FSM，聚合 transition
  coverage，并按 FSM 分段输出 state/transition/sequence gap 表格。
- 不在 schema 中放未证实字段。
- 不用 `note/unavailable_fields` 伪装接口兼容；字段做不到就不暴露。
- Python NPI backend 初始化时建立唯一的 method/signature 合同；每个 operation
  只调用一次已声明签名，不探测或重试其它参数个数。
- NPI method 缺失、调用异常、traversal 返回 `None`/非 iterable 或必需 fact
  类型错误统一返回 `NPI_CONTRACT_VIOLATION`，不转换成零值、`None` 或空列表。
- `SessionManager` 对 NPI、Fake 和 factory 注入 backend 强制安装同一个 canonical
  adapter；`summary/tests/scopes/items` 没有绕过路径。item 按 metric/type 区分
  score-bearing、context/container 与 assertion count bin，并统一检查 identity、
  status、闭合 `file/line` evidence 和 score 跨字段关系。
- backend/action canonical score/count 不接受 `-1` sentinel；不适用值使用
  JSON `null`。只有 NPI SDK 层可以依据已声明 metric/type 把文档定义的“不适用”
  返回值映射成 `null`，非法负值仍返回 `NPI_CONTRACT_VIOLATION`。

- `NPI_CONTRACT_VIOLATION` 响应必须声明
  `scan_complete:false`、`analysis_complete:false`，调用方不得把部分遍历结果视为
  完整 coverage 事实。
- exclusion load/set/save/unload 的 SDK 返回值必须为 `1`；`0` 是明确失败，不尝试
  其它 mode、backend、数据源或 URG fallback。

## 后续重新评估条件

以下情况出现时，可以重新审计并扩展接口：

- Verdi/Python Coverage API 新版本明确暴露 port direction。
- NPI Language/Netlist API 能稳定把 coverage signal 绑定到 design port handle。
- Coverage API 明确暴露 URG 源码页中的专有 annotation label。

重新评估必须先更新本文件，再更新 schema、README、skill 文档和测试。
