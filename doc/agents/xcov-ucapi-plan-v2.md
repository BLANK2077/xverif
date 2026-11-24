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
