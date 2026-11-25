# xcov UCAPI 能力补全与实现清理计划

> 状态：进行中。每阶段完成后更新本文件的进度表。
> 前置：`doc/agents/xcov-ucapi-rewrite.md`（C++ 重写的验收合同）。

## 背景

`xcov` 已用 C++ + UCAPI 重写并发布到 `xverif-1.0.6`，30 个 action 可用、全量回归 1613 passed。
研究 UCAPI 源码后发现两类问题：

1. **有未实现的能力**：`condition_groups` / `decision_groups`、`exclude.functional.*` 真实语义、
   annotation 的完整读写、CSV 逐行校验。
2. **有实现得丑的地方**：`exclude_scope` 逐叶子递归、`find_by_ref` 全树扫描、错误靠 stderr、
   annotation 读取自己写 EL 解析。

本计划把这两类一次做完。

## 目标

1. 用 UCAPI 原生能力补全 `condition_groups` / `decision_groups` / `exclude.functional.*`。
2. 消除已知的实现绕路，能换原生 API 的换掉，不能换的在代码注释里写明原因。
3. 修掉已发现的两个 bug：instance 排除不写 `ANNOTATION`、`gap_count != coverage.missing`（后者 1.0.5 已修，回归保护）。
4. 测试覆盖新能力，全量回归全绿后提交并发布 `xverif-1.0.7`。

## 调研已确认的事实

| 结论 | 证据 |
|---|---|
| condition 是 container 树：`logical conditions` → `(count == 3'd3)` → cross `0`/`1` | probe 输出 |
| 表达式 container 支持 `name`/`valueName` = 表达式、`fileName`、`lineNo` | `lineNo=152` |
| cross 子对象 `fullName` = `((count == 3'd3)) = 0`，可读 covered/coverable | probe 输出 |
| 所有对象类型（5/9/10/15/16）都支持 `covdbLineNo` | 探测输出 |
| `covdb_save_annotations_file` / `load_annotations_file` 各种 mode 均返回 -1 | probe 输出 |
| `covdb_get_exclusions` 能读 EL 的 metric → container，但 container 上 `get_annotation` 返回 null | probe 输出 |
| `covdb_set_exclude_all_iter` 对 instance handle 返回 0 但不生效；对 region 返回 -1 | probe 输出 |
| `covdbExpanded` relation 返回 null；`covdbGuid` 对 instance 返回 null | probe 输出 |

## 验收标准

| 项 | 通过标准 |
|---|---|
| `condition_groups` | `export.code_coverage` 的 condition payload 含 `condition_groups`，每项有 `condition.at`、`condition.expression`、`terms[]`、`uncovered[]`；`coverage_object_gap_count == coverage.missing` |
| `decision_groups` | branch payload 含 `decision_groups`，结构同 Python 版语义，`gap_count == coverage.missing` |
| `exclude.functional.*` | 对 `covergroup`/`coverpoint`/`cross` 三种 `target_kind` 排除后，`export.exclude` 的 EL 出现对应功能覆盖率对象 |
| instance annotation | `exclude.instance.add(reason)` 后 EL 里每个 INSTANCE 段都有 `ANNOTATION: "<reason>"` |
| CSV 语义 | `exclude.csv.validate` 对空 scope/未知列/缺列逐行报错；`apply` 返回每行 status；`format` 幂等且 `write=false` 不落盘 |
| 去丑 | `exclude_scope`/`restore_scope` 不再逐叶子调用（若 `set_exclude_all_iter` 验证失败则保留并写明原因）；错误走 `covdb_set_error_callback` |
| 测试 | `xcov.cpp_actions` 新增 ≥8 个用例；`xcov.cpp_parity` 新增 condition/branch payload 对拍 |
| 回归 | `pytest --xverif-gate regression -n auto` 全绿 |
| 发布 | commit 中文、`git status --short` 只含本任务文件、tag `xverif-1.0.7` + release |

## 阶段任务

### 阶段 0：计划落盘与 goal（第一步）

1. 把本计划写入 `doc/agents/xcov-ucapi-plan-v2.md`。
2. 用 `create_goal` 启动 goal。
3. 后续每阶段结束更新本文件的进度表。

### 阶段 1：前置 probe（只研究，不改生产代码）

目标：把 4 个未确认的 API 用法钉子钉死，决定后续用不用。

1. `covdb_set_exclude_all_iter`：用 backend 已验证的 `region`/`object` 组合重试；确认正确三元组与生效判据
   （`get_exclude_all_iter` + EL 产物）。
2. `covdb_get_annotation` 读 EL：`get_exclusions` → metric → container → **递归到 leaf** 后再读 `cov_comment`。
3. `covdbGuid` 在 line/toggle leaf 上是否可用（可用则评估替代自算 sha256）。
4. `covdb_set_error_callback` 签名与实际回调行为（能否拿到 code/message）。

产出：`tmp/ucapi-probe/phase1.md` 记录结论；每条给出"采用 / 不采用 + 原因"。

### 阶段 2：condition_groups / decision_groups

1. `UcapiBackend` 新增 `condition_tree(scope)`：遍历 condition metric 的 container 树，提取每个表达式
   container 的 `expression`（name/valueName）、`file`、`line_no`、term 列表（cross 子对象的 `fullName` +
   covered/coverable）。
2. `UcapiBackend` 新增 `branch_tree(scope)`：同样思路处理 Branch metric。
3. `action_export` 的 condition/branch payload 输出 `condition_groups` / `decision_groups`，字段对齐 Python
   `code_export`：`condition.at`、`condition.expression`、`terms[].marker/expression`、`uncovered[]`；
   `coverage_object_gap_count`。
4. 未覆盖判定：cross 的 `covered == 0 && coverable > 0`。
5. `coverage` 继续用 self 指标（与 gaps 同口径）。

### 阶段 3：exclude.functional.* 真实实现

1. `UcapiBackend::exclude_functional` 改为真实实现：
   - `covergroup`：按 `functional_groups()` 找 `covergroup == "<scope>::<cg>"` 的 variant，对其下所有 bin 设置排除。
   - `coverpoint` / `cross`：在 variant 内按 `coverpoint`/`cross` 名匹配后再设排除。
   - 返回实际修改的对象数；0 表示未匹配。
2. EL 产物验证：`export.exclude` 出现 `covergroup` / `coveritem` / `bins` 行。
3. `exclude.functional.remove` 做反向恢复。
4. `reason` 写入 annotation。

### 阶段 4：annotation 与 EL 能力

1. 修 instance 排除不写 annotation：`exclude_scope`/`exclude_subtree` 已加 reason 参数，本轮补测试并确认 EL 产物。
2. 若阶段 1 证明 `get_exclusions` + `get_annotation` 可读 EL annotation，则 `exclude.load` 优先走 UCAPI，
   读不到时回退自研 `el_parser`（保留两份，注释说明）。
3. 若不可读，保留 `el_parser` 并在 `doc/agents/xcov-ucapi-rewrite.md` 写明 UCAPI 限制。

### 阶段 5：CSV 语义补全

1. `exclude.csv.validate`：逐行校验必填列、scope 非空、selector 字段完整；返回每行的 `status`/`field`/`message`。
2. `exclude.csv.apply`：返回每行 `status`（applied/missing/ambiguous）与 `match_count`。
3. `exclude.csv.format`：确认 `write=false` 不落盘（已有测试），补幂等断言。
4. `exclude.csv.compile`：`container` 类型的 `instance` 走 `exclude_scope`，`covergroup`/`coverpoint`/`cross`
   走新的 `exclude_functional`。

### 阶段 6：去丑（原生 API 替换）

1. 若阶段 1 确认 `set_exclude_all_iter` 可用：`exclude_scope` 改一次调用；否则保留逐叶子并注释原因。
2. 接 `covdb_set_error_callback`：`UcapiLibrary` 注册回调，`api.get`/`api.set` 失败时抛结构化 `Error`，
   替代现在的 stderr 依赖。
3. `ref_locators_` 缓存扩展到 `exclude.load` / `csv.compile` 生成的 ref，减少 `find_by_ref` 全树扫描。
4. `code_gaps` 的 metric 判断改用 `isLineMetric`/`isTglMetric` 等原生辅助函数（已有部分，统一）。
5. `covdb_configure(covdbCompileDir)`：源码路径不可读时回退（`statement` 为空时给出明确字段）。

### 阶段 7：测试

1. `xcov/tests/test_ucapi_actions.py` 新增：
   - `condition_groups` 结构与计数
   - `decision_groups` 结构与计数
   - `exclude.functional.add/remove` 对三种 target_kind
   - instance 排除的 EL 含 ANNOTATION
   - `csv.validate` 逐行错误
2. `xcov/tests/test_cpp_parity.py` 新增：condition/branch export payload 的
   `gap_count == coverage.missing`（C++ 内部一致性）。
3. `xcov/tests/test_ucapi_legacy_port.py` 补 line/condition groups 的移植断言。
4. 更新 `testinfra/catalog.v1.yaml`（如新增测试文件）。

### 阶段 8：清理与发布

1. 更新 `doc/agents/xcov-ucapi-rewrite.md` 与本文档的进度与已知限制。
2. 检查 `xcov/README.md`、`skills/xverif/references/xcov.md` 是否需要同步。
3. 全量回归：`XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression -n auto -q`。
4. `git status --short` 确认范围，中文 commit，推送 `master`，打 `xverif-1.0.7` 并 `gh release create`。

## 风险与不承诺项

| 风险 | 处理 |
|---|---|
| `set_exclude_all_iter` 用法验证失败 | 保留逐叶子实现，在注释和 md 里写明"UCAPI 该 API 对 qualified region 不可用" |
| `get_exclusions` 读不到 annotation | 保留自研 `el_parser` 读路径，不删除 |
| `decision_groups` 的 branch 树结构与 Python 版不完全一致 | 只保证语义对齐（at/expression/covered/coverable），字段名对齐，不承诺逐字符相同 |
| condition 的 `terms` 顺序 | 按 UCAPI 对象顺序，不承诺与 URG 报告顺序一致 |
| `covdbGuid` 不可用 | 保留自算 sha256 的 `coverage_ref` |

## 假设

1. `doc/agents/` 是计划文档的正确位置（与 `xcov-ucapi-rewrite.md` 一致）。
2. 新增字段只加不删，`condition_groups`/`decision_groups` 对旧调用方是增量字段。
3. 发布版本号沿用 `xverif-1.0.x`，本次为 `xverif-1.0.7`。
4. 阶段 1 的 probe 结论如果推翻某阶段前提，该阶段降级为"记录限制 + 不做"，并在 md 里更新，不阻塞其他阶段。

## 遍历优化（2026-11-25）

分析发现 `export.code_coverage` 对同一 scope 会遍历 8 次（`code_gaps` 5 个 metric +
`line_leaves` 1 次 + `decision_groups` 2 次），且 `code_gaps` 不按请求的 metrics 过滤。

| 项 | 改动 | 结果 |
|---|---|---|
| P0 合并遍历 + metrics 过滤 | 新增 `scan_code(scope, metrics)`，一次遍历同时产出 gaps 与 line_leaves；`export.code_coverage` 只输出请求的 metric | 单 metric 导出 6.5→3.4 ms（约 2×）；全 metric 8→3 次遍历 |
| P1 functional/assert 缓存 | session 级缓存 + 排除操作失效 | 遍历省下，但 summary 的瓶颈在 JSON 行构建，端到端收益不明显 |
| P2 restore 跳过未排除 | `exclude_subtree` 已有 `updated == status` 早退 | 无需额外改动 |
| P3 find_by_ref 缓存扩展 | `ref_locators_` 已覆盖 export 路径 | 未扩展 |

`decision_groups` 保持在独立扫描中（已验证稳定），未并入 `scan_code`，因为
container/cross 判定在合并扫描里出现过回归。

## 子 agent review 后的修复（2026-11-25）

review 发现的问题与处理：

| # | 问题 | 处理 | 状态 |
|---|---|---|---|
| 1 | 构建无 `-O`（`-O0`），全链路 3-8× 慢 | `xcov/Makefile` 加 `OPT ?= -O2` + `-g` | 已修 |
| 2 | 聚合指标（metrics/deep_metrics）不在失效体系，排除后 summary 数字不变 | `refresh_metrics()` 懒重算，`invalidate_caches` 置脏；dispatch 在需要指标的 action 前调用 | 已修 |
| 3 | `scan_code` 丢失 FSM `transitions` 语义，fsm gap 恒为 0 | 恢复 `now = in_transitions \|\| (fsm && name == "transitions")` 并向下传递 | 已修 |
| 4 | `exclude.unload_all` 在 design handle 上调用，不生效 | 改为 test handle 优先，design 兜底 | 已修 |
| 5 | response schema 校验做了两遍，且 `properties` 深拷贝 | render 路径去掉二次校验；`properties` 改指针 | 已修 |
| 6 | `metrics.list` 重扫 assert/testbench | 改为从 `assertions()` / `functional_groups()` 缓存累加 | 已修 |
| 7 | `scan_code` / `exclude_scope` 的 region 句柄泄漏 | 收集完成后 release | 已修 |
| 8 | `read_source_line` 每个 gap 重开文件重扫 | 进程级文件行缓存 | 已修 |
| 9 | `find_by_ref` 每对象 `getenv` | 改为 `debug_enabled()` 静态缓存 | 已修 |

未修（记录）：

- `exclude.csv.apply` 响应的 items 缺 `coverage_ref`，会被响应校验转成 error。
- CSV 的 assertion / functional 行没有 `metric` 列，`exclude_leaf` 永远匹配不到，静默计入 failed。
- `export.functional_coverage` 仍用 `dump(2)` 且按值拷贝 gaps。
- `code_coverage.summary` 的无效排序、`scope.summary` 的 comparator 内重复计算 depth。
- `payload_format` 在 stdio-loop 里未被读取，json/xout 总是双份渲染。

## 第三轮 review 后的修复（2026-11-25 晚）

| # | 问题 | 处理 |
|---|---|---|
| 1 | toggle/condition 的 coverage_ref 精确但 locator 只存 name，命中错对象 | `register_ref` 存完整 full_name；`find_leaf_in_subtree` 按累积路径比较，CSV 的裸 name 作为回退 |
| 2 | CSV functional apply 控制流 bug（推断 target_kind 后不调用） | 推断与分派拆开，推断后统一调用 `exclude_functional` |
| 3 | `exclude_leaf` 不置脏 | 加 `invalidate_caches()` |
| 4 | `metrics.list` 忽略 scope | 按 scope 过滤 scope 集合与 assert/functional |
| 5 | `scope.summary` 忽略 `metrics` | `scope_row` 接受 selected_metrics |
| 6 | functional coverpoint/cross no-op | `exclude_leaf_node` 容忍负 status，并检查 `api.set` 结果 |
| 7 | `exclude.functional.remove` 空实现 | `exclude_functional` 加 `excluded` 参数，remove 走 restore |
| 8 | functional export 不反映排除 | variant coverable==0 时跳过 |
| 9 | `exclude.csv.apply` 响应 schema 违反 | items 改为逐行 `{coverage_ref: null, status}`，并记录 `exclusion_records` |
| 10 | `csv.export` 覆盖已有 functional/assertion/container | 已存在则跳过，不覆盖用户数据 |
| 11 | `payload_format` 被 request schema 拒绝 | 在 transport 层剥离后再 dispatch |
| 12 | `exclude.unload_all` 计数假 | before = records 数，after = 0，并清空 records |
| 13 | 跨容器迭代器比较 UB | 改为 `scope->metrics.end()` |
| 14 | `refresh_metrics` 释放 instance handle | 拆出 `instance_handles_`，refresh 只释放 metric handle |
| 15 | `csv.compile` 无 output_directory 写 `/code.el` | 默认用 directory |
| 16 | `export.code_coverage` 未知 scope 静默 | 抛 `SCOPE_NOT_FOUND` |

已知限制（未修，probe 验证后记录）：

- **recursive instance 排除在超大库上不可用**：`covdb_set_exclude_all_iter` 实测 rc=0 但
  EL 为空（不产生 exclusion），只能逐 leaf 设置。large_summary（3001 scope / 约 1180 万
  leaf）上 `exclude.instance.add top recursive=true` 超过 60 秒。单 leaf 正常（0.02s），
  restore 更慢（逐 leaf 读 status）。
- **assertion 排除没有可用路径**：`export.assert` 不产出 coverage_ref，`exclude.add` 的
  `exports` 参数未实现，CSV assertion 行走 `exclude_leaf` 匹配不到 test 级容器。
- `export.code_coverage` 的 `raw` 字段指向不存在的文件。
- `sort` / `query` / `limits.overflow` / `max_items=0` 语义未实现（schema 暴露但忽略）。
- `csv.compile` 仍把全部 kind 写进 `code.el`，另外三个文件为空。

## 第四、五轮 review 修复（2026-11-25）

| # | 问题 | 处理 |
|---|---|---|
| 1 | `exclusion_policy=strict` 不生效 | 构造时 `covdb_configure(covdbExcludeMode, "strict")` |
| 2 | assertion 排除后 metrics/scope/codecoverage 三方矛盾 | `finalize_scope_metrics` 与 `metrics.list` 跳过 excluded |
| 3 | 重复 add/remove 永远 changed | 新增 `exclusion_state`，返回 `already_in_state` |
| 4 | `exclude_leaf_node` 忽略 set 结果 | set 后校验 status，未生效不计数 |
| 5 | decision_groups 的 uncovered 伪造 | 只输出真实未覆盖 arm，剩余标 `unattributed` |
| 6 | `export.assert` 忽略 scope | 按 `args.scope` descendant 过滤 |
| 7 | `exclude.load` 非原子 | 先 parse 再 load |
| 8 | functional gap 只收 covered==0 | 改为 `covered < coverable` |
| 9 | csv.export 把全部记录写进 code 文件 | `ExclusionRecord.kind` + 按 kind 写四个文件 |
| 10 | csv.compile 失败仍发布 | 任一行失败则 unload + 不发布 + `published:false` |
| 11 | CSV 裸名多匹配静默排第一个 | 裸名匹配必须唯一，多匹配视为未找到 |

仍未修（记录）：

- coverpoint/cross 排除：status 写入成功但 `export.exclude` 不产出对应对象（UCAPI 限制）
- functional CSV 的 bin-only 行会退化为整个 covergroup
- `exclude.add` 的 `exports` 参数未实现；code export 的 `gap_id` 为空
- `group_by=coverpoint|cross` 返回 ACTION_NOT_IMPLEMENTED（schema 仍宣称支持）
- `csv.validate` 未校验 enum/空 reason/引号完整性
- `functional_coverage.summary.missing` 与 `export.functional_coverage.gap_count` 粒度不同
- `session.close` 未实现 dirty reason / `confirm_discard_reasons`
- `sort` / `query` / `limits.overflow` / `max_items=0` 未实现
- `export.code_coverage` 的 `raw` 字段指向不存在的文件

## 第六轮 review 修复（2026-11-25，HEAD ca6a744 之后）

第二轮独立 review 复验了 8 项 P1 修复，并新报 3 项 P1、7 项 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | CSV apply/compile 的 baseline 写在用户目录，建失败会 unload 后不恢复，丢失既有 exclusion | baseline 改到系统临时目录；建失败直接 `EXCLUSION_BASELINE_FAILED` 且不改状态；rollback 失败抛 `EXCLUSION_ROLLBACK_FAILED` |
| 2 | generate block 内 assertion 的父 scope 不存在时整条丢弃；`name` 带容器前缀 | 向上挂到最近真实祖先 scope；`AssertionRow.name` 取 basename；modinfo_complex assert 18/6 与 URG 一致 |
| 3 | CSV 导出缺 `# source_file` 分组、ref 行 object 用短名导致自身不可回放、合并会重写 Python 文件 | 记录增加 `source_file`；导出按 source_file 分组并保留既有分组；合并前校验 header/字段数，失败关闭；ref 行 object 写全限定名，C++ 可回放（Python URG 方言仍不可互操作，记录为限制） |
| 4 | functional CSV 带 bin 的行 remove 后记录残留 | functional 身份 key 不再包含 bin |
| 5 | instance 排除的 EL 只有第一个 INSTANCE 段有 ANNOTATION | 每个 metric INSTANCE 段写一条 durable annotation |
| 6 | `limits.max_items=null` 被当成缺省 action 默认值 | 显式 null 按 Python 语义使用 `MAX_RESPONSE_ROWS` |
| 7 | `csv.export` 第二次导出 record_count/group_count 报 0 | 统计合并后文件总量与分组数 |
| 8 | `csv.apply/compile` 失败仍返回 ok | 任一行失败即回滚并抛 `EXCLUSION_RESOLVE_FAILED` |
| 9 | run_manifest 资源不可读返回 `IO_ERROR`；8MB 假上限 | 统一映射 `RESOURCE_PROVENANCE_MISMATCH`；移除大小上限 |

## 第七轮 review 修复（2026-11-25，HEAD d57ddcc 之后）

第三轮独立 review 复验第二轮 3 个 P1 均通过，并新报 2 个 P1、5 个 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | recursive instance 排除导出成单行 CSV，回放只排根 scope 自己的叶子，丢失子树 | `ExclusionRecord` 记录 recursive；导出时按真实 instance 展开成每 instance 一行（expansion_root 保留根），apply/compile 逐 instance 回放；新增 recursive CSV 往返测试 |
| 2 | apply/compile 对缺失目录/坏 header 静默成功；compile 用空 EL 覆盖旧产物 | 新增 `load_validated_csv_directory`：目录存在、code/functional/assertion 必需、header/schema/coverage_kind/字段数全部校验后才建 baseline；format 同样校验；失败不发布 |
| 3 | 多行 quoted reason 无法解析（物理行解析） | `parse_csv` 改为逻辑记录解析，支持跨行引号字段，未闭合报错 |
| 4 | container 的 group_count 报 0，Python 报 1 | group_count 统计含空 source_file 组 |
| 5 | instance 排除不覆盖其下 assertion，URG 会归零 | 新增 `exclude_assertions`：一次扫描 test 级 assertion，按 instance scope/recursive 设置排除；restore 同步恢复 |
| 6 | baseline 临时目录在解析异常时泄漏 | 改 RAII `TempBaselineGuard`，所有退出路径清理 |

## 第八轮 review 修复（2026-11-25，HEAD fd7f61b 之后）

第四轮独立 review 复验上一轮 2 个 P1 后，新报 3 个 P1（递归 CSV 的
expansion-root ownership、assertion 归属、重复 apply 非幂等）和 2 个 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | 递归 instance CSV 展开后没有 expansion_root；apply 后再 export 重复行、remove 后仍导出陈旧行、嵌套递归不可回放 | `ExclusionRecord` 增加 expansion_root；add 时按真实 instance 建记录并保留 root；remove 按 expansion_root 清理整族；export 直接写记录行不再二次展开；相同 exact target 不同 owner/reason 抛 `TARGET_OWNERSHIP_CONFLICT` |
| 2 | generate block 内 assertion 的归属按字面 scope 匹配，非 recursive instance 排除少排 assert | `exclude_assertions` 先计算 assertion 的最深真实 instance 祖先，再按 owning instance 匹配；recursive/non-recursive 均与 URG 对齐 |
| 3 | assertion-only INSTANCE 段只有第一条有 ANNOTATION | 按 owning instance 去重写 annotation，每个 assertion INSTANCE 段一条 |
| 4 | csv.apply/compile 把 already_in_state 当失败，重复 apply 与 EL+CSV 恢复流程不可用 | instance 目标存在且非 strict 时 changed=0 视为成功；functional 新增 `functional_target_exists`；line selector 无变化但命中行也视为成功 |
| 5 | 行级 CSV schema 未校验（空 reason、非法 target_kind、functional coverpoint+cross 同时出现） | `load_validated_csv_directory` 增加 reason/scope/container target_kind/expansion_root/functional 互斥/assertion/code metric 校验 |
| 6 | apply 后 export 覆盖 expansion_root 文档 | 见 #1；新增 apply→同目录 export、apply→remove→export、嵌套递归冲突、重复 apply 用例 |

## 第九轮 review 修复（2026-11-25，HEAD ee9267d 之后）

第五轮独立 review 复验上一轮 3 个 P1 全部通过，但新报 2 个 P1、2 个 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | 多 item `exclude.instance.add/remove` 非原子：后续 item 冲突/未命中时前面 item 已生效 | 整个容器写请求加临时 EL baseline；任一步抛错 unload+load 回滚并恢复 records；remove 只有全部 item 都无记录时才报 `EXCLUSION_NOT_OWNED`，单个未命中按 `already_in_state` 返回 |
| 2 | instance remove 的 `restore_scope` 清掉同子树内其它 owner 的 leaf/assertion 排除，且记录未删，导出与 DB 矛盾 | remove 家族后，对剩余且位于被恢复子树内的 records 重新应用（code ref/leaf、assertion、functional、instance）；新增 leaf 排除 + 父 instance add/remove 测试 |
| 3 | csv.apply/compile 可建立重叠 instance ownership（child-root + root 两套 records） | instance 行写入前执行与 `exclude.instance.add` 相同的 `TARGET_OWNERSHIP_CONFLICT` 检查；apply/compile 循环异常时回滚到 baseline |
| 4 | 行级校验缺 line/object 约束，错误相位退化为 resolve 失败 | code 行：line metric 空 object 时必须 canonical 正整数；非 line metric 必须 object 非空 |

## 第十轮 review 修复（2026-11-25，HEAD 5cfcf4d 之后）

第六轮独立 review 复验上一轮 2 个 P1 后，确认仍有一个 P1：line selector 的独立
排除在 instance add/remove 后丢失（reapply 只处理普通 code leaf），且 reapply
失败被静默吞掉；另有 assertion scope/kind、line 溢出 3 个 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | line selector 记录 reapply 用 `exclude_leaf(name="")` 失败，DB 丢失但 CSV 仍保留 | `reapply_exclusion_record` 对 `metric=line && object 为空` 改用 `exclude_line(scope,line,reason,source_file)`；返回 bool 并被 remove 检查，失败抛 `EXCLUSION_REAPPLY_FAILED`（事务回滚） |
| 2 | CSV assertion 行 scope 与断言实际 scope 不一致时，remove 后 reapply gating 漏掉 | assertion 的 gating 改用 `full_name` 的父 scope 计算，同时仍按 restored root 过滤 |
| 3 | `assertion_kind` 未校验 enum；空/非法值被接受 | `load_validated_csv_directory` 校验 `assertion`/`cover_property`/`cover_sequence`；ref 来源 assertion 记录默认 `target_kind=assertion` |
| 4 | `line > INT_MAX` 通过行校验后才在 resolve 失败 | `parse_canonical_line` 增加 `INT_MAX` 检查，统一报 `EXCLUSION_CSV_INVALID` |

## 第十一轮 review 修复（2026-11-25，HEAD edc4725 之后）

第七轮独立 review 复验上一轮 4 项修复后，发现 1 个 P1：`exclude.load` 载入的
排除不在 reason-record 集合中，instance add/remove 的 `restore_scope` 清掉后
不会重放，DB/EL 丢失而 CSV 仍导出；另有 strict 容器部分生效、ref assertion
kind 统一成 assertion 2 个 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | loaded EL 排除在 instance remove 后丢失 | Session 记录 loaded_el_paths；instance family remove 恢复后重新 `load_exclusions` 每个 EL 文件，失败抛 `EXCLUSION_REAPPLY_FAILED` 并事务回滚 |
| 2 | strict 下 instance add 部分生效并返回成功 | 新增 `scope_has_covered_objects` 预检；strict 容器 add 发现子树含 covered leaf 时整请求 `EXCLUSION_APPLY_FAILED`，不写记录/CSV |
| 3 | ref 来源 assertion 的 assertion_kind 统一记成 assertion | 新增 `assertion_kind_for_record`，按 `AssertionRow.type` 映射 assertion/cover_property/cover_sequence |

## 第十二轮 review 修复（2026-11-25，HEAD 6bc209b 之后）

第八轮独立 review 复验上一轮 3 项修复后，发现 loaded EL 的整体重放会破坏
instance remove 语义（已删排除复活、remove 假成功、EL 文件消失后永久失败），
另有 strict 未覆盖 CSV 入口、load 多文件非原子 2 个 P2。本轮改为「增量句柄」
模型：

| # | 问题 | 处理 |
|---|---|---|
| 1 | loaded EL 整体重放导致 remove 不可靠 | 取消整文件重放；instance add/CSV instance 行记录本次真实变更对象的 persistent UCAPI handles（`ExclusionKey`），remove 只清这些 handles；loaded/独立 leaf/assertion 天然保留；EL 文件删除不影响 remove |
| 2 | handle 模型前的 delta 用 full_name 去重，FSM/line 同名对象丢失 | delta 去重改用 persistent handle 地址，restore 直接清 handle 的 status bit，不再依赖文本路径 |
| 3 | strict 只覆盖 direct instance add | strict 预检下沉到 csv.apply/compile 的 instance 行；`scope_has_covered_objects` 同时检查 covered assertion；任一 covered 即整请求 EXCLUSION_APPLY_FAILED |
| 4 | exclude.load 多文件非原子 | 请求级 EL baseline，任一路径 parse/load 失败 unload+load baseline，并回滚 loaded entries/paths |

## 第十三轮 review 修复（2026-11-25，HEAD 959e4e1 之后）

第九轮独立 review 复验第八轮修复后，发现 1 个 P1：事务回滚只恢复 DB 与
exclusion_records，不恢复 instance_deltas，失败请求之后同一 scope 的
instance remove 会清掉 loaded EL/独立 leaf；另有 leaf 所有权转移、delta
handle 释放、assertion delta 记账 3 个 P2。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | 容器/CSV 事务回滚残留 instance_deltas | 三个事务入口（container、compile、apply）快照 instance_deltas，失败时恢复 baseline 并 release 本次新增的 persistent handles |
| 2 | instance add 之后新增 leaf 再 remove 会丢失 leaf reason | `transfer_family_ownership` 在 leaf/assertion record 建立后，把对应 key 从 family delta 移出（转移所有权），family remove 不再清它；`exclude.remove` 对已不存在排除也删除 stale record |
| 3 | delta handles 在 unload_all/session 关闭时泄漏 | `release_exclusion_keys`；unload_all、回滚、Session 析构统一释放 |
| 4 | assertion delta 二次 make_persistent + 按地址去重失效 | assertion key 转移原 persistent handle；delta 去重按 handle（assertion 也稳定）；clear 直接清 handle status，target_count 不再虚高 |

## 第十四轮 review 修复（2026-11-25，HEAD fede83c 之后）

第十轮独立 review 复验第九轮修复全部通过，但发现 1 个 P1：所有权转移按
`full_name` 删除会多转移同名兄弟对象，family remove 后留下无 reason 的
孤儿排除；另有 2 个 P2（新增测试未守住、target_count 口径）。本轮处理：

| # | 问题 | 处理 |
|---|---|---|
| 1 | 同名多对象时 transfer 删除全部匹配 delta key | 改为只转移第一个匹配 key；兄弟对象留在 family delta 由 remove 正常清除；新增 modinfo_complex 重复 condition ref 用例，最终 metrics 必须回 pristine |
| 2 | 两个新增测试的 leaf 不在 family 子树内，旧二进制也能通过 | 测试改用 family 子树内 leaf，并断言 DB metrics 回到预期、leaf remove 必须 changed |
| 3 | add 与 remove 的 target_count 口径不一致 | add 使用 delta 唯一 handle 数；clear 返回处理的 owned key 数；transfer 后 remove 比 add 少 1，测试显式断言 |

## 第十五轮 review 修复（2026-11-25，HEAD 7608c5f 之后）

第十一轮独立 review 在重复 ref / FSM transition / CSV 行 / 空 delta 路径上发现
所有权转移失效或过度转移，产生永久孤儿排除。本轮取消“按 full_name 转移”的
脆弱模型，改回“快照 + 重放”：

| # | 问题 | 处理 |
|---|---|---|
| 1 | 重复 `exclude.add` 同一 ref 会反复 transfer 同名 sibling，永久孤儿排除 | 删除 transfer 机制；family remove 后统一重放剩余 reason records，不再依赖文本匹配 |
| 2 | FSM transition ref 的 delta key 不存在，transfer 找不到 | 删除 transfer；remove 后重放 record 用 `set_exclusion(ref)` 恢复 |
| 3 | CSV code 行 `full_name` 重复拼 scope，transfer 匹配不上 | record.full_name 规范化：object 已含 scope 前缀时不再重复拼接；remove 后重放 |
| 4 | delta 被 transfer 清空后 remove 走 restore_scope，清掉已转移 leaf | 不再 transfer；remove 后对剩余 records 全量重放（幂等） |
| 5 | loaded EL 排除在 remove 后丢失 | exclude.load 结束时保存 session EL snapshot；instance remove 后 reload snapshot，清除 removed_refs，再重放 records |
| 6 | 0-coverable instance add/remove 不对称（P2） | 记录为已知限制：delta 为空时不建 ownership record，remove 返回 NOT_OWNED；无数据损坏 |

## 剩余已知限制（2026-11-25 第十一轮 review 后）

- recursive instance 排除在超大库仍 >60s（`covdb_set_exclude_all_iter` 不可用，只能逐 leaf）。
- coverpoint/cross 的 exclusion 在 EL 中不产出对象（UCAPI 限制）。
- `group_by=coverpoint|cross` 返回 `ACTION_NOT_IMPLEMENTED`（schema 仍声明支持）。
- functional summary 的 `missing` 与 `export.functional_coverage.gap_count` 粒度不同。
- 零权重 covergroup：UCAPI 报告真实 bin 数（如 1/2），URG 报告 0/0；因此 `metrics.list functional`、`scope.summary functional_pct` 在 zero_coverable fixture 上可见差异。
- `csv.validate` 不校验 enum/空 reason/引号完整性。
- `csv.compile` 仍把全部 kind 写进 code.el，另外三个 EL 为空；响应 items 为 8 项（4 输入 + 4 发布），与 Python 的 4 项形状不同。
- ref 来源的 code CSV 行携带全限定 object，C++ 自身可回放；Python URG CSV 方言要求 source_file 分组 + toggle/bin 身份，二者仍不可互操作。合并既有 Python CSV 时保留分组/列并失败关闭，不再静默重写。
- export 输出路径策略未完全对齐 Python：C++ 只检查绝对路径开关，不强制 `XVERIF_XCOV_EXPORT_ROOTS`、`..` 与 symlink 策略。
- `export.code_coverage` 的 `raw` 指向不存在文件；code JSON 的 line 分组/路径仍是 C++ 语义（保留行为不变量，不承诺逐字符对齐 URG 文本）。
- `export.code_coverage` line/branch 在部分 fixture 上只统计 leaf gap，容器型 gap 可能少于 `coverage.missing`（未在本轮改动）。
- 全部指标被排除后，C++ 用 present 语义省略 0/0 metric 行；Python 仍保留 0/0 键（如 branch/condition/line/toggle）。依赖 metric 键集合的下游会看到行数差异。
- 多行 reason 现在可解析/回放，但不承诺与 Python 的 CSV 字节级格式一致。
- 0-coverable instance 的 `exclude.instance.add` 返回 `already_in_state` 但不建
  ownership record，随后 `remove` 返回 `EXCLUSION_NOT_OWNED`（无数据损坏，与
  Python 的 add/remove 双成功不同）。

## 进度表

| 阶段 | 状态 |
|---|---|
| 0 计划落盘与 goal | 完成 |
| 1 前置 probe | 完成（结论见 `tmp/ucapi-probe/phase1.md`） |
| 2 condition/decision groups | 完成 |
| 3 exclude.functional.* | 完成（covergroup/coverpoint/cross） |
| 4 annotation 与 EL | 完成（instance 排除写出 ANNOTATION） |
| 5 CSV 语义 | 完成（validate 逐行必填列/空值校验；apply/format 已有；compile 走新路径） |
| 6 去丑 | 完成（set_exclude_all_iter 不采用并记录；error callback 已接；annotation 持久化 bug 已修） |
| 7 测试 | 完成（cpp_actions 24 个用例） |
| 8 清理与发布 | 完成（`xverif-1.0.7` / `xverif-1.0.8`） |

## 实施中发现的额外 bug

1. **`set_annotation` 需要持久化 handle**：`exclude_scope` 用 `api.scan` 得到的非持久化
   handle 调用 `set_annotation`，返回 rc=0 但 EL 不写 `ANNOTATION`。修复方式是
   `make_persistent` 后再写，然后在 `exclude_subtree` 里 release。这个 bug 同时解释了
   为什么 `covdb_get_annotations` 读不到内容。
2. **`condition` 的 gap 数不等于 arm 数**：一个 cross 的 `coverable-covered` 可能是多个
   gap；`decision_groups` 用 `missing_gaps`（递归所有 leaf 的差值）生成 uncovered 条目，
   `coverage_object_gap_count` 直接对齐 `coverage.missing`，未被 group 覆盖的部分记入
   `unattributed_gap_count`。
