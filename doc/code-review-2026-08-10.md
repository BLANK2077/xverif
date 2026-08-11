# 2026-08-10 xcov 代码审查报告

**审查范围**: 21 个 commit（c2f2e31 至 dcd1eb3），覆盖 xcov 子系统代码覆盖率导出、exclusion 管理与 NPI 消除三大方向。

**审查方式**: 只读，逐个 commit diff + 当前源文件状态。

---

## 总体评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 逻辑正确性 | 良好 | 核心逻辑经过严格真实 EDA 回归验证，边界处理较完善 |
| 安全性 | 良好 | 路径推导使用显式环境变量验证 + 目录存在性检查，CSV 禁止 `..` traversal |
| 性能 | 优良 | NPI 全量遍历在多处已被 URG session.xml 缓存或 scope-local 精确定位替代 |
| 代码质量 | 良好 | 新建文件 code_export.py、eda.py 结构清晰；actions.py 部分函数较长 |
| 测试覆盖 | 良好 | 新增大量单元测试和真实 VDB fixture 回归，覆盖正常、边界、异常路径 |

**关键结论**: 整体方向正确，21 个 commit 有明确的递进关系。从初始的代码覆盖率导出基础，到条件/FSM 增强、排除管理、NPI 消除，是一条从数据层到加速层的完整链条。发现的问题均为中低严重度，无阻塞项。

---

## 逐 Commit 分析

### 1. c2f2e31 - 完善 xcov 实例级覆盖率导出与正式回归

**改动范围**: 32 文件，+1619/-47 行。新建 `code_export.py` (599 行)，创建复杂 VDB fixture 基础设施（lane_worker.sv、top.sv、packet_fabric.sv 等）。

**逻辑正确性**:
- `_export_code_coverage()` 通过 staging 目录 + `os.replace()` 实现原子发布，避免半成品目录。
- `_instance_has_no_self_metric()` 检查模块级 instance self 覆盖率是否为空，正则表达式可处理多行 SCORE 行。
- `_section()` 和 `_module_name()` 实现了从 modinfo.txt 文本中定位特定 instance 的 metric section，逻辑正确但依赖 URG 输出格式稳定性。

**安全性**: 输出路径使用 Path 操作，无注入风险。

**代码质量**:
- `code_export.py` 模块职责明确，命名合理。
- 函数较长（`_export_code_coverage` ~210 行，`parse_metric_report` ~55 行），但逻辑线清晰。

**测试覆盖**: 新增 `test_modinfo_complex.py` (97 行)，纳入 `xcov.modinfo_complex` catalog suite。

**发现的问题**:
- **中**: 原始代码为每个 scope x metric 发起一次 URG 调用（NxK 次），在 commit #6 (a0acfc4) 中被优化为单次合并调用。实际上初始设计就有优化的必要。
- **低**: `_instance_has_no_self_metric` 中 score row 的正则 `--\s+--\s*` 在多 metric 行可能匹配不足，已在 commit #6 修复为 `(?:--\s+)+\s*`。

---

### 2. 8a2968c - 支持 branch 三目决策并扩展复杂覆盖率回归

**改动范围**: 6 文件，+170/-8 行。branch parser 新增 ternary 分支支持。

**逻辑正确性**:
- `_source_statement()` 从文件读取多行源码语句，正确闭合分号。
- `_assignment_rhs()` 从源码行提取赋值 RHS，使用负向前瞻避免匹配 `>=`、`<=`、`!=`、`==` 等比较操作符。
- `_branch_terms()` 的三目条件提取逻辑：连续赋值三目优先使用整行表达式；过程内三目从 `prior_numbered` 获取前置行的 RHS。`start_line` 回溯逻辑处理了多行三目场景。
- 所有解析失败通过 `CoverageExportParseError` 清晰报错，不在静默 fallback。

**代码质量**: ternary 相关逻辑分离清晰。

**测试覆盖**: 新增 ternary 特定单元测试和 fixture 断言。

**发现的问题**:
- **中**: `_assignment_rhs()` 的正则 `r"(?<![=!<>])=(?!=)\s*(.+)$"` 使用 `(?<![=!<>])` 负向后顾，但 Python 只支持固定宽度的后顾；`[=!<>]` 是单一字符，实际可行。但 `<=` 的非阻塞赋值在 SystemVerilog 中是有效 assign，`_assignment_rhs` 用 `(?<![=!<>])=` 会正确排除 (`<=` 中 `=` 前面的 `<` 会触发负向后顾)，但 `=` 后面的 `=` 用 `(?!=)` 排除了 `==`。整体逻辑正确。

---

### 3. 4aba3bb - 按过程块重构 line coverage v2 输出

**改动范围**: 4 文件，+193/-0 行。新增 `_line_groups()` 实现 line coverage 按过程块分组。

**逻辑正确性**:
- 先解析所有过程块上下文（ALWAYS、INITIAL、FINAL 等各种 `[A-Z][A-Z0-9_-]*` 模式），按源码行排序。
- 将 flat line gap 归属到对应的过程块（通过比较 line number 找到最近的 context）。
- 只输出存在缺口（coverage < 100%）的过程块，符合"按过程块定位主要缺口"的设计意图。
- 空 groups（100% 覆盖）合法发布，与设计文档一致。

**代码质量**: `_line_groups()` 中 `next_line` 变量的使用正确但略微隐晦。

**发现的问题**: 无。

---

### 4. 35056a4 - 合并同义 condition 缺口并发布 v2 分组合同

**改动范围**: 4 文件，+277/-26 行。condition 从平铺式改为分组式输出。

**逻辑正确性**:
- `_condition_terms()` 通过 `label.start(1)` 和 annotation line 的 marker span 位置精确恢复每个 term 的表达式文本。
- `_strip_balanced_outer_parens()` 正确剥离外层平衡括号，但不打破内部非配对括号。
- 合并逻辑：以 `(at, terms)` 为 group key，同位置同 terms 的 EXPRESSION/SUB-EXPRESSION 共享一个 group；相同 values 只保留一个 gap，用 `origins` 数组记录来源。
- `coverage_object_gap_count` 保留 URG 原始 missing object 数，`gap_count` 为 AI 实际需要处理的语义 gap 数 -- 二者语义区分清晰。

**发现的问题**:
- **低**: `_condition_terms()` 中 `_strip_balanced_outer_parens` 对 term 从 expression column + span 范围提取后做了剥离，但 `span.start() - expression_column` 在 expression_column 为 None 时会触发 TypeError -- `label.start(1)` 除非 label==None（已在前面检查）否则总有返回值。

---

### 5. fb893bf - 修复三目覆盖率语义并实现 FSM 分组导出

**改动范围**: 2 文件，+377/-22 行。

**逻辑正确性**:
- `_split_ternary()` 实现完整的三目表达式分割器，正确处理引号、括号、嵌套三目（`?:` 的右结合性）、排除 `==` 和 `!=` 中的 `?`。
- `_ternary_outcomes()` 把分支结果映射为 `{"0": false_result, "1": true_result}`，支持递归匹配嵌套三目。
- `_fsm_block_gaps()` 替换原 `_fsm_gaps()`，按 FSM 分段输出 gaps 表格。
- 注释正确记录：`<=` 非阻塞赋值和带空格 case value 被纳入解析。
- `_branch_terms` 的 ternary outcomes 添加到 decision path 中。

**代码质量**: `_split_ternary` 是 commits 中最复杂的单一函数（~50 行），逻辑正确但可考虑提取为独立模块。

**发现的问题**:
- **低**: `_split_ternary` 中嵌套三目的 `nested` 计数器与 `question_depth` 的配合：在第 N 层嵌套 `?:` 中，嵌套计数器在遇到 `?` 后递增，直到遇到同层级的 `:` 后递减。但如果中间有额外的 `?`，`nested` 正确处理。逻辑正确，但在极端嵌套场景下建议增加深度上限保护。

---

### 6. 83a8dcd - 扩展复杂覆盖率用例验证双状态机

**改动范围**: 2 文件，+59/-4 行。fixture RTL 添加 `monitor_state` 状态机。

**逻辑正确性**:
- 新增 `always_comb` + `always_ff` 实现的双过程块状态机，正确使用 `unique casez`、`priority case`、嵌套 `casez` 等具有差异化的分支决策结构。
- 后续 commit (512b7fd) 将其重构为单过程块标准编码以适应 VCS 2025 的 NPI 发布行为。
- 测试期望值（line gap count、condition gap count、FSM group count）与真实 URG 输出匹配更新。

**发现的问题**: 无。

---

### 7. 7dee6ce - 移除覆盖率三目结果冗余字段

**改动范围**: 6 文件，+20/-112 行。从 condition 输出中删除 `outcomes` 字段及相关处理逻辑。

**逻辑正确性**:
- 删除 `_ternary_outcomes()` 和 `_split_ternary()` 两个函数（~70 行），以及 condition groups 中的 outcomes 赋值逻辑。
- 这些函数在 branch 路径中仍然被使用（branch 的 ternary decision 需要 outcomes），只在 condition 输出中移除。
- **注意**: 此 commit 先于 `fb893bf` 在 `code_export.py` 中删除了 outcomes 逻辑，但之后的 `fb893bf` 又重新添加了更完善的 `_split_ternary` 和 `_ternary_outcomes`。在时间线上这是正常的重构迭代（先删旧，后加新）。

**发现的问题**: 无。纯代码清理。

---

### 8. 92d09a5 - 同步 xcov 覆盖率输出合同与执行规则

**改动范围**: 4 文件（纯文档），+36/-7 行。

**内容**: 更新 skill 文档补齐 branch/condition outcomes、FSM 分组表格示例；记录真实 EDA fixture 环境复盘规则。

**发现的问题**: 无。文档更新与代码变更一致。

---

### 9. 98ae004 - 同步覆盖率导出文档并完成全仓回归验收

**改动范围**: 6 文件（纯文档），+71/-7 行。

**内容**: 将 line v2 / condition v2 / branch ternary / FSM v2 的合同更新同步到 README、capability、XOUT 示例、fixture 说明和 xverif skill。

**发现的问题**: 无。

---

### 10. cdae29a - 兼容不同版本的 pynpi coverage 打开接口

**改动范围**: 6 文件，+140/-9 行。

**逻辑正确性**:
- `_cov_open_contract()` 使用 `inspect.signature` 冻结 `cov.open` 的真实接口合同，避免了通过 `TypeError` 重试形成的隐式 fallback -- 这符合 AGENTS.md 中"不允许静默 fallback"的规则。
- 签名验证：只接受 `open(vdb)` 或 `open(vdb, config_opt=0)` 两种形式，拒绝 varargs。
- 在 `__post_init__` 中根据合同长度选择单参数或双参数调用，strict 模式在旧版 pynpi 返回明确错误而非静默忽略。

**代码质量**: 函数独立、职责单一。

**发现的问题**:
- **低**: `NPI_METHOD_CONTRACTS` 字典的定义位于模块顶层，紧跟在 `_cov_open_contract` 函数之后有一个没有缩进的空行，然后紧接着 `for _metric_method in METRIC_METHODS.values(): NPI_METHOD_CONTRACTS[...]`。这不是 `_cov_open_contract` 函数体的一部分（没有缩进），是模块级代码。位置正确，但可读性略差 -- 建议在 `_cov_open_contract` 函数定义后添加明确的模块级注释分隔。

---

### 11. 512b7fd - 支持按导出 gap ID 直接管理排除项

**改动范围**: 8 文件，+545/-49 行。

**逻辑正确性**:
- `attach_gap_locators()` 通过 `db.handle_by_name(scope)` + metric handle 的递归 walk 为每个 URG gap 附加 scope-local NPI path。
- `_exclude_export_gaps()` 接收按 gap ID 的批量排除请求：预检阶段验证文件存在、路径绝对、JSON 有效、VDB 匹配、gap ID 存在、locator 有效。
- 非 FSM 保持原子事务：预检失败或 setter 失败时恢复 baseline EL。FSM 允许 partial_success。
- fixture 重构：lane_worker 的 monitor_state 从两过程块改为单过程块标准编码，确保 VCS 2025 同时发布 state 和 monitor_state 的 NPI 对象。
- **禁止遍历守卫**: 测试中通过 monkey-patching `_npi_items` 为 `AssertionError` 验证排除路径不调用全库扫描。

**代码质量**:
- `_exclude_export_gaps()` 函数较长（~120 行），但逻辑分段清晰：预检 -> baseline 保存 -> 逐个 apply -> 回滚/成功。
- toggle gap 的 object 匹配使用 `_toggle_gap_object()` 解析 `signal[bit]` 或 `signal[msb:lsb]` 格式，与 `_toggle_gap_object` 中的正则配对。

**发现的问题**:
- **中**: `_exclude_export_gaps` 中非原子操作的 gap 逐个 apply 未使用显式 `try/finally` 包裹每个 gap 的 setter，但如果某 gap 因 NPI 不可见对象失败时，`set_exclusion_locator` 会返回非 `changed/already_in_state` 状态并被正确检测到。FSM 以外的 metric 失败后整批回滚，逻辑正确。
- **低**: `_toggle_gap_object` 使用了 `__import__("re")` 而非模块级 `import re` -- 这是一种运行时延迟导入。如果这是为了性能，建议改为模块级导入以保持一致性。

---

### 12. 82149b9 - 移除 exclusion CSV 的 Git 元数据合同

**改动范围**: 5 文件，+9/-60 行。

**逻辑正确性**:
- 从 `ExclusionGroup` dataclass 中移除 `source_commit` 字段。
- 从 parser 中移除 `pending_file` 状态和 `source_commit` 解析、验证逻辑。
- 从 `format_document` 中移除 `source_commit` 输出。
- 从 schema 中移除 `source_commit` 字段和 CSV workflow item 中的相应要求。
- 移除 `exclude.csv.status/impact/resolve/rebase/stamp_changed` 等 Git 工作流 action 的文档描述。

**代码质量**: 删除干净彻底，文档同步完整。

**发现的问题**: 无。

---

### 13. 61d8de6 - 实现 exclusion 原因持久化与 CSV 原子导出

**改动范围**: 9 文件，+525/-52 行。

**逻辑正确性**:
- Session 新增 `exclusion_records` 内存字典和 `loaded_el_without_reasons` 标记。
- `exclude.add` 中 coverage_refs 和 selectors 路径都记录 reason 到 session。
- `exclude.csv.export` 原子导出流程：读取既有 CSV -> 检测 reason 冲突 -> 临时目录写入新内容 -> 原子 replace。
- reason 冲突检测：同一 identity（scope+metric+line+object+bin）如果已有不同 reason，三类文件均不写入，要求用户决策 -- 这避免了静默覆盖。
- toggle coverage 支持空行号（NPI 对象可能无源码行）。
- `_gap_csv_rows()` 为每个 gap 的 locator targets 生成 CSV 行，使用 `_source_and_line()` 递归搜索源码位置。

**代码质量**:
- `_exclude_csv_export` 函数较长（~90 行），但原子写入的三阶段（stage -> replace -> rollback）正确实现。
- `_required_reason()` 提取为公共函数。

**发现的问题**:
- **低**: `_source_and_line()` 中 "从 gap/group 递归搜索源码位置" 的逻辑使用了 `pending` 队列遍历嵌套 dict/list，但实际上 `candidates` 只有两个固定元素（gap 和 group），递归深度也有限。逻辑正确但可能过于通用。
- **低**: `exclusion_records` 字段使用 `field(default_factory=dict)` 作为 dataclass 默认值 -- Python dataclass 中这需要 `field()` 但这里不是 dataclass（`XcovSession` 是一个普通类）故 OK。`exclusion_records` 是类属性 `Dict[str, Json] = field(default_factory=dict)` 但类体中没有 `@dataclass` 装饰器，`field()` 在此处会作为普通函数调用并赋值。检查 session.py 确认：`@dataclass` 出现在类定义上，所以 `field(default_factory=dict)` 正确定义。

---

### 14. b55b782 - 规范 xcov exclusion 分析与持久化流程

**改动范围**: 3 文件（纯文档），+53/-2 行。

**内容**: 在 xverif skill 主入口和 xcov reference 固化 exclusion 的完整生命周期流程。

**发现的问题**: 无。

---

### 15. a0acfc4 - 合并 URG 导出为单次调用（NxK -> 1 次）

**改动范围**: 2 文件，+232/-52 行。

**逻辑正确性**:
- 将原来每个 scope x metric 发起一次 URG 调用的模式改为一次合并调用：构建 combined hier 文件，包含所有 scope 及其子 scope 的 tree 指令。
- 多 metric 使用 `+` 连接（如 `line+cond+branch+tgl+fsm`），一次性从 modinfo.txt 解析所有 metric 的数据。
- `parse_metric_report(combined_text, scope, metric)` 从同一份文本中多次提取不同 scope/metric 对的数据 -- `_section()` 定位算法确保不同 instance 的数据不混淆。
- URG 超时从 300s 提高到 600s（因为一次处理更多内容）。
- `_instance_has_no_self_metric` 正则从 `--\s+--\s*` 改为 `(?:--\s+)+\s*`，修复多 metric SCORE 行匹配。

**性能**: NxK 次 URG -> 1 次（另加 attach_gap_locators 的 O(leaves) NPI walk）。

**发现的问题**:
- **低**: `_export_code_coverage` 中 `urg_args = [...]` 又硬编码了 `"urg"` 字符串（添加 `-full64` 但使用 `"urg"` 而非 `get_urg_path()`），而在 commit #9 (03dae5f) 中才统一改为 `get_urg_path()`。这是在相邻 commit 之间的一致性改进。

---

### 16. e4e9c19 - 移除 code_coverage.holes 和 functional_coverage.holes action

**改动范围**: 9 文件，+72/-371 行。

**逻辑正确性**:
- 从 `ACTION_REGISTRY` 中删除两个 holes action 的注册和 handler 分支。
- 从 `schemas.py` 中删除对应 schema 定义（`CODE_HOLE_ITEM`、`FUNCTIONAL_HOLE_ITEM`、`CODE_HOLE_ITEM` 的 request/response 合同）。
- 从 `query.py` 中删除默认 limits。
- `_code_coverage()` 方法原本有 `if action == "code_coverage.holes"` 分支，删除后只剩 else 分支（现直接执行）。
- `_functional()` 方法中的 `functional_coverage.holes` 分支也被删除，只保留 summary 逻辑。

**清理彻底性**:
- 所有 holes 相关辅助函数已删除：`_code_coverage_hole_scope_rows()`、`_pct_is_below_100()`、`_project_code_coverage_hole_rows()`、`_project_functional_coverage_hole_rows()`、`_filter_functional_levels()`。
- 测试中 holes 引用全部替换为对应的 summary 或 export action。
- 文档同步更新 skill reference 和 README。

**发现的问题**:
- **低**: `_dispatch_opened()` 辅助函数中的 `CountingBackend` mock 新增了 `top_scopes()` 和 `scope_metrics()` 方法，因为 `scopes()` 不再被 `public_json` 调用。但 `CountingBackend` 中 `scopes()` 仍然抛出 `AssertionError` -- 这个守卫条件在 e4e9c19 之前就存在（`session public_json must not scan scopes`），此次修改保持了这一约束。
- **低**: 测试中 `test_code_coverage_actions_reject_functional_metric` 的 parametrize 从两个 action 减少到一个，但测试函数仍使用 `action` 参数 -- 可以用单参数或改为非参数化测试，更简洁。

---

### 17. d05b378 - 修复 MCP integration 测试中 exclude.add selector 缺少 reason 字段

**改动范围**: 1 文件，+6/-3 行。

**逻辑正确性**: 三个 MCP integration 测试用例的 `selector` 对象缺少必填 `reason` 字段，导致 handler 在 `_required_reason()` 处抛出 `KeyError`。为每个 selector 添加 `"reason": "test"` 后恢复正常。

**发现的问题**: 无。必要的 hotfix。

---

### 18. 03dae5f - 添加 eda.py 统一 NPI/URG 路径推导与安全导入

**改动范围**: 6 文件，+115/-35 行。

**逻辑正确性**:
- `resolve_verdi_home()` 优先使用 `XVERIF_XCOV_VERDI_HOME` 覆盖，再回退到 `VERDI_HOME`。
- `get_npi_python_path()` 验证路径存在性。
- `get_urg_path()` 从 `VCS_HOME/bin/urg` 解析，fallback 到 PATH 上的 `urg`，使用 `os.access(urg, os.X_OK)` 验证可执行性。
- `import_pynpi()` idempotent：检查 `npi_path` 是否已在 `sys.path`，避免重复追加。
- `UrgRunner.build_argv()` 中 `"urg"` 替换为 `get_urg_path()`，`_ensure_urg()` 和测试中使用 `get_urg_path()` 替代硬编码。
- `_ensure_urg` 添加 `-full64` 加速。

**安全性**:
- 路径推导使用 `os.path.abspath` 规范化，避免相对路径劫持。
- `os.environ.get` 不会抛出异常，空值正确处理。
- `get_urg_path()` 的 fallback 到 PATH 使用 `shutil.which` 而非硬编码。

**代码质量**: `eda.py` 模块文档清晰，每个函数 docstring 说明输入输出和异常。

**发现的问题**:
- **低**: `get_urg_path()` 中 `VCS_HOME/bin/urg` 路径推导没有像 `get_npi_python_path()` 那样导出 `XVERIF_XCOV_VCS_HOME` 覆盖环境变量。如果用户需要自定义 VCS 安装路径但目前只能通过设置 `VCS_HOME` 或 PATH 实现。
- **低**: `import_pynpi` 返回 `(cov, npisys)` 两个模块，类型标注为 `Any`。如果后续需要类型安全，可以定义 Protocol 或 TypedDict。

---

### 19. 338646a - functional_coverage.summary 改用 session.xml Groups 缓存

**改动范围**: 3 文件，+121/-3 行。

**逻辑正确性**:
- `_ensure_urg()` 在解析 `old_coverage` 后额外扫描 Groups 和 Asserts 子 scope。
- `_parse_urg_groups()` 递归遍历 Groups scope XML，产出包含 type、covergroup、coverpoint、cross、bin、covered、coverable 的列表。
- `scope_functional_from_urg()` 返回缓存的 Groups 数据。
- `actions.py` 中 `_functional()` 的 `items(metrics=['functional'])` NPI 调用替换为 `scope_functional_from_urg()`。
- `_TestBackend` mock 补齐 `scope_functional_from_urg()`。

**性能**: 消除 functional coverage 查询对 NPI 全量 scan 的依赖，改为 session.xml 单次解析 + 内存缓存。

**发现的问题**:
- **低**: `_parse_urg_groups()` 中的 `_score_value()` 函数已定义但实际未在代码中使用（在 commit 中可见其定义但在 `rows.append` 中未被调用）。这可能是预留的辅助函数或残留代码。建议如果在最终版本中仍未被调用，考虑移除。

---

### 20. 13878f2 - assert.summary 改用 session.xml Asserts 缓存

**改动范围**: 2 文件，+19/-14 行。

**逻辑正确性**:
- `_parse_urg_asserts()` 解析 Asserts scope XML，处理 `Assertion` 和 `Cover Property` 两种类型。
- 使用 `attrs.get("success", attrs.get("all match", 0))` 兼容两种 URG 属性名。
- 正确计算 `status` 字段：successes > 0 = covered；failures > 0 = not_covered；attempts > 0 但无 successes/failures = not_covered；attempts = 0 = 空状态。
- `actions.py` 中 `_assert_report()` 删除了 `items(metrics=['assert'])` 全量 NPI 调用，替换为 `scope_assert_from_urg()`。
- 注意移除了 `include_source=False` 参数和 `_sections` 返回值的解包。

**性能**: 消除 assert summary 对 NPI 全量 scan 的依赖。

**发现的问题**:
- **低**: 旧版 `_assert_report` 中 `_assert_report_rows` 接受 `include_source` 参数控制是否附加源码信息。改用 `scope_assert_from_urg()` 后，源码信息不在 URG session.xml 中（Asserts scope 不包含源码行），如果下游依赖 `include_source=True` 的行为，需要确认无影响。commit message 确认了 `without_attempts` 字段的添加符合 schema 合同。

---

### 21. dcd1eb3 - export.exclude/unload_all 改用内存计数；resolve_selector 改用 scope 精确定位

**改动范围**: 2 文件，+98/-33 行。

**逻辑正确性**:
- `_export_exclude()` 和 `_exclude_unload_all()` 从 `items()` 全量遍历改为 `len(exclusion_records)` -- 直接读 session 内存计数。
- `resolve_selector()` 核心改进：从原来 `_npi_items()` 全量遍历 + regex 匹配改为 `db.handle_by_name(scope)` + metric handle 的 `child_handles()` 递归查找，深度上限 4 层。
- 文件匹配支持两种形式：`child_file.endswith("/" + sel_file)` 或 `child_file == sel_file`。
- `line` 条件：`sel_line is None or child_line == sel_line` -- 支持不传行号时的模糊匹配（匹配第一个 leaf）。
- `_find_in_children` 正确使用 `finally` 释放 child handle（无论是提前返回还是继续搜索）。
- `_exclude_set()` 中新增 `locator` 路径：如果 `resolve_selector` 返回 `locator` 而非 `coverage_ref`，使用 `set_exclusion_locator()` 进行直接 NPI 定位排除。
- 正确处理 `row.setdefault("coverage_ref", None)` 防止 locator 路径返回后缺少该字段。

**性能**: resolve_selector 从 O(all_items) 降为 O(metric_leaves)，典型场景下 metric_leaves << all_items。

**代码质量**: `_find_in_children` 的递归深度上限 (4) 基于 NPI hierarchy 的经验值；如果层级更深，可能漏匹配。

**发现的问题**:
- **中**: `_find_in_children` 中 `coverage.covered(child, test_hdl)` 调用用于确认目标确实未被覆盖（返回未覆盖时抛异常或返回特定值）。但 `current_status` 硬编码为 `["not_covered"]` -- 如果目标实际上已经被覆盖（`coverage.covered` 通过），这个返回值可能是误导性的。需要确认 `self._api().call("coverage.covered", child, test_hdl)` 在已覆盖对象的实际行为。
- **低**: `_find_in_children` 中 `locator` 返回了 `path` 和 `type`/`name` 用于后续的 `set_exclusion_locator`，但 `path` 是基于 metric handle 的 children 索引（不是基于 instance/database 的全局路径）。这是正确的，因为 `set_exclusion_locator` 也是从同一个 metric handle 按相同路径 navigate。但如果在 resolve 和 set 之间 NPI 对象变化（同一 session 内不太可能但理论上），会导致不一致。

---

## 发现的问题汇总

### 中等严重度

1. **dcd1eb3**: `resolve_selector._find_in_children` 中 `coverage.covered` 调用的语义需确认 -- 当前假定通过 `coverage.covered` 不抛异常即表示 `not_covered`，但没有显式检查返回值。
2. **512b7fd**: `_exclude_export_gaps` 中对非 FSM gap 逐个 apply 后检测失败，但没有显式保护每个 gap 的 setter 调用；失败检测依赖返回值的 status 字段。

### 低严重度

3. **338646a**: `_parse_urg_groups()` 中 `_score_value()` 函数定义但未使用，可能是残留代码。
4. **dcd1eb3**: `_find_in_children` 的递归深度上限 4 是经验值，如果 NPI hierarchy 更深可能漏匹配。
5. **03dae5f**: `get_urg_path()` 未提供 `XVERIF_XCOV_VCS_HOME` override 环境变量，对标 `resolve_verdi_home()` 的不一致性。
6. **512b7fd**: `_toggle_gap_object()` 中使用 `__import__("re")` 而非模块级 import。
7. **e4e9c19**: `test_code_coverage_actions_reject_functional_metric` 参数化从 2 个减为 1 个后，可考虑改为非参数化测试。
8. **a0acfc4**: `_export_code_coverage` 中的 URG 调用仍硬编码 `"urg"` 字符串（在 commit #9 中才改为 `get_urg_path()`），属于相邻 commit 之间的一致性问题。

---

## 建议

1. **NPI 函数语义验证**: 在 `resolve_selector._find_in_children` 和 `set_exclusion_locator` 中建议增加对 `coverage.covered` 返回值的显式检查，而非依赖异常信号。考虑将 NPI 调用合同显式文档化（类似 `_cov_open_contract` 的做法）。

2. **递归深度保护**: `_find_in_children` 和 `attach_gap_locators.walk` 的递归深度上限建议从常量改为可配置参数，并在超出上限时返回明确错误而非静默跳过。

3. **EDA 路径统一**: 建议为 `get_urg_path()` 添加 `XVERIF_XCOV_VCS_HOME` 环境变量支持，与 `resolve_verdi_home()` 对称。

4. **actions.py 函数拆分**: `_export_code_coverage` (~110 行) 和 `_exclude_export_gaps` (~90 行) 建议拆分为更小的子函数以提高可测试性。

5. **闲置代码清理**: `_score_value()` 在 `_parse_urg_groups()` 中如确实未使用，建议移除。

6. **测试加固**: 对于 NPI 消除的边界场景（如 Groups/Asserts scope 在 session.xml 中不存在、NPI hierarchy 超过 4 层、metric handle 为空），建议增加专门测试覆盖。

---

*审查人: AI Code Review Agent*  
*审查日期: 2026-08-10*  
*审查范围: 21 commits (c2f2e31..dcd1eb3)*

---

## 2026-08-11 真实 VDB 风险验证与后续路线

### 已确认风险

| 项目 | 真实结果 | 处置 |
|------|----------|------|
| selector 精确性 | 4040 个候选中 3880 个 identity mismatch，64 个 assertion 异常，58 组 locator 碰撞 | 不再修补；全部 metric 建立 gap ID 后删除 selector |
| exclusion 异常回滚 | 第二个 setter 抛异常后，第一个 NPI 状态和 1 条 session metadata 均未恢复 | 统一 preflight、staging metadata、baseline EL 和回滚合同 |
| FSM gap ID 预检 | `F0001` 与不存在的 `F999999` 同批提交时，后者被静默忽略并错误返回 success | 所有输入错误均在 setter 前使整批失败；只有执行阶段 FSM 目标失败可 partial success |
| EL 状态计数 | EL 重新导出的文件非空，但 `exported_count` 与 unload `before_count` 返回 0 | 区分 tracked metadata、loaded file 和未知 native entry count，禁止 unknown 冒充 0 |
| coverage_ref CSV 身份 | exclusion 和 reason 加入成功，但 CSV 导出报告 1 条 unexportable | setter 前要求 portable CSV identity，不允许制造无法持久化 reason 的成功记录 |

`coverage.covered()` 的真实返回值是覆盖计数而非“调用成功”标志：真实 leaf 分别观测到 covered `1/1` 与 uncovered `0/1`。该事实用于新的 gap/locator 合同；selector 不再投入状态或匹配修复。

### Toggle 名称直达调查

Verdi X-2025.06-SP1 的 C header、Python wrapper、PDF/HTML 文档、动态符号和 `libNPI.so` 反汇编结论一致：

- `npi_cov_handle_by_name` 只接受 database 或 instance scope。
- database scope 直接使用输入 fullname；instance scope只拼接 `instance.full_name + "." + name`。
- metric、signal、signal bit、toggle bin scope 在函数内部直接拒绝。
- 已安装的 NPI shared objects 没有导出 signal/toggle/bin 专用 lookup 或 handle factory。
- toggle signal、bit、bin 的 `npiCovFullName` 在真实 VDB 中为空，显示名称不是可反查的唯一身份。

因此不能从序列化名称或 gap ID直接构造 NPI handle。可靠方案是：export 时保存 root、child path和完整父链 identity；恢复时先按 fullname定位 instance，再按 root分组且每棵相关 metric tree只遍历一次。

复杂度目标：

```text
同一 session：O(G)，通过 canonical export path + gap ID 的 live handle cache
跨 session：O(S + K * Cinst + Nk + G)，通常简化为 O(S + Nk + G)
禁止实现：O(G * N) 的逐 gap重复遍历
```

其中 `S` 是 export总 gap数，`G` 是请求 gap数，`K` 是相关 instance数，`Nk` 是相关 metric tree对象总数。该性能优化必须在 assertion和functional gap ID全链路完成后实施。

### 评审项处置状态

- **当前必须修复**：batch preflight/rollback、FSM未知 ID、EL count真实性、coverage_ref portable CSV identity、固定深度 walker、长函数职责混杂、显式 VCS_HOME override、缺失 Groups/Asserts/metric测试。
- **由新架构替代**：selector mismatch、selector assertion异常、selector current status和selector遍历性能；最终直接删除，不增加过渡优化。
- **已由后续提交修复**：NxK URG调用、多 metric SCORE正则、硬编码 URG入口、三目 branch定位、condition同义 gap合并、FSM分组。
- **经核对不构成缺陷**：`_assignment_rhs` 固定宽度后顾、condition expression column、dataclass `default_factory`。
- **仅需维护性收敛**：未使用 `_score_value`、动态 `__import__("re")`、单参数 parametrize、模块级合同分区和关键 pynpi Protocol。

### 实施与发布顺序

先完成原始 correctness和持久化问题，再依次完成 assertion gap ID、functional gap ID、locator v2、同 session cache、跨 session分组索引，最后删除 selector并同步 skill。全部阶段只形成独立本地 commit；focused、真实 NPI、MCP、skill和全仓 regression全部通过后才统一推送远端。
