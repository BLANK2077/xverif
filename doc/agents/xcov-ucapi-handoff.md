# xcov UCAPI C++ 重写 · 交接说明（Handoff）

> 交接时间：2026-11-25。当前 HEAD：`3e7d7bb`。
> 本文给下一个会话用：现状、已验证/未验证、已知限制、验证命令、待办。

## 1. 项目与代码位置

| 项 | 值 |
|---|---|
| 仓库 | `$REPO`（仓库根，当前工作目录） |
| 当前分支 | `master`，HEAD `3e7d7bb`（已推送 GitHub） |
| 构建 | `make -C xcov`（`-O2 -g`，产物 `xcov/bin/xcov`，不入 git） |
| 入口 | `tools/xcov`（`XVERIF_XCOV_BACKEND=ucapi` 默认走 C++；`=urg` 走 Python 旧实现） |
| 计划文档 | `doc/agents/xcov-ucapi-plan-v2.md`（含历次 review 修复记录和已知限制） |
| 原始合同 | `doc/agents/xcov-ucapi-rewrite.md` |
| 环境 | VCS `X-2025.06-SP1`，`libucapi.so` 在 `$VCS_HOME/linux64/lib/` |
| 测试入口 | `.conda-xverif/bin/pytest --xverif-gate regression --xverif-suite <id>` |

## 2. 架构

```
xcov/src/
  main.cpp                 CLI: --stdio-loop / --once / --json
  api/schema.cpp           Draft-7 子集校验器 + 从 schemas_data JSON 加载
  api/protocol.cpp         parse_request / XOUT 渲染
  coverage/ucapi_abi.h     硬编码 UCAPI 枚举与属性 id
  coverage/ucapi_loader.*  dlopen/dlsym，error callback
  coverage/ucapi_backend.* 核心：scope 树、deep 聚合、code/functional/assert、
                           exclusion、decision_groups、scan_code
  coverage/coverage_ref.*  xcovref.v1:<sha256>
  exclusion/el_parser.*    EL 解析（含 ANNOTATION、test 级 covergroup 段）
  exclusion/csv_parser.*   CSV 解析
  session/session.*        SessionManager（单 live session）
  actions/catalog.*        actions.json 加载
  actions/dispatch.cpp     action 分发与响应投影（约 2000 行）
```

Schema/action 元数据是**生成物**：`xcov/xcov/schemas_data/v1/`（63 个 schema + actions.json），
由 `xcov/tools/export_schemas.py` / `export_actions.py` 从 Python 定义导出；
`test_schema_export.py` 校验等价性。**不要手改 JSON**，改 Python 定义后重新导出。

## 3. 当前能力状态

### 已验证通过（多次回归）

- 全量回归：`XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression -n auto` → **1616 passed**
- `xcov.cpp_parity` 3 passed：8 个读 action 与 Python 参考（`XVERIF_XCOV_BACKEND=urg`）一致；
  双后端切换；二进制不链接 python/pynpi
- `xcov.cpp_actions` 24 passed：30 action 冒烟、EL/CSV 往返、strict、幂等、聚合一致性
- `xcov.unit` 179 passed（Python 参考实现 + schema 导出）
- code export 的 `gap_count == coverage.missing`（line/toggle/branch/condition/fsm，含排除后）
- 排除后 `metrics.list` / `code_coverage.summary` / `scope.summary` 对 code 与 assert 一致
  （含 generate scope 的聚合父链）
- EL 四类（code/instance/functional/assert）回放
- CSV code/assertion/container 往返；functional covergroup 往返
- strict 五个写入口拒绝 covered（instance 路径按"只排 uncovered"语义，其它入口拒绝）
- compile 失败用 baseline EL 回滚，不再清空既有排除
- stdio 协议校验（request_id、quit 字段）、session 容量（capacity=1）
- 性能（large_summary，3001 scope / 约 1180 万 leaf）：
  open ≈1.6 s / 168 MB，`metrics.list` ≈30 ms，`code_coverage.summary` ≈1.5 ms，
  `scope.summary` ≈1 ms，`functional_coverage.summary` ≈10 ms（100 行），
  `assert.summary` ≈7 ms，单 leaf `export.code_coverage` ≈50 ms，
  `export.functional_coverage` ≈170 ms，`export.assert` ≈50 ms

### 已知限制（**已记录，不要再当 bug 报**）

见 `doc/agents/xcov-ucapi-plan-v2.md` 末节，摘要：

1. **recursive instance 排除在超大库 >60 s**：`covdb_set_exclude_all_iter` 实测不产生 exclusion，
   只能逐 leaf；1180 万 leaf 时不可用。单 leaf 正常。
2. **coverpoint/cross 的 exclusion 在 EL 中不产出对象**（status 可写，EL 空）。
3. functional CSV 的 bin-only 行会退化为整个 covergroup。
4. `exclude.add` 的 `exports` 参数未实现；code export 的 `gap_id` 为空。
5. `group_by=coverpoint|cross` 返回 `ACTION_NOT_IMPLEMENTED`（schema 仍声明支持）。
6. `csv.validate` 不校验 enum/空 reason/引号完整性。
7. functional 的 `summary.missing` 与 `export.gap_count` 粒度不同。
8. `session.close` 未实现 dirty reason / `confirm_discard_reasons`。
9. `sort` / `query` / `limits.overflow` / `max_items=0` 未实现。
10. `export.code_coverage` 的 `raw` 字段指向不存在的文件。
11. `session.open.target.run_manifest` 未实现（provenance gate 缺失）。
12. EL→CSV 不可回放（写原始 EL 行）；`csv.export` 不去重（重复导出会追加）。
13. `ref_locators_` 无上限（多 scope 导出内存线性增长，约 1 MB/leaf scope）。
14. strict 未覆盖 `exclude.load`；EL 的 `ExclMode` 字段由 UCAPI 固定为 default。
15. 已存在输出目录时 export 会覆盖（Python 返回 `OUTPUT_ALREADY_EXISTS`）。

### 第 9 轮 review 剩余（P1/P2，未全部修）

- `metrics.list` 对零指标/未知 scope/synthetic scope 的行数与 Python 不一致
  （C++ 无条件追加 assert/functional 行；synthetic scope 返回后代聚合）
- `scope.summary` / `code_coverage.summary group_by=scope` 在"只有一个有值 metric"时
  缺 `covered/coverable/missing`（Python 有）
- CSV 的 `line` selector 被 validate 接受但 apply/compile 不使用
- container/functional 写入口把所有"未变化"报成 `already_in_state`（无法区分不存在/strict 拒绝）
- `export.assert`/`export.functional_coverage` 不检查输出目录已存在
- 大 VDB 反复 open/close RSS 缓慢增长（约 1.8 MB/cycle，疑似 UCAPI/allocator 保留）
- `payload_format` 非字符串返回 INTERNAL_ERROR；非法枚举被静默当 xout
- strict `exclude.instance.add` 部分生效而非整请求拒绝（与 Python 参考行为不同）

## 4. 验证命令

```bash
# 构建
make -C xcov

# 三个核心 suite
.conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xcov.unit
.conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xcov.cpp_parity
.conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xcov.cpp_actions

# 全量回归（需要 host 环境，约 5.5 分钟）
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression -n auto
```

手工探测模板：

```bash
printf '%s\n' \
  '{"api_version":"xcov.v1","request_id":"1","action":"session.open","target":{"vdb":"<ABS_VDB>"},"args":{"name":"c"}}' \
  '{"api_version":"xcov.v1","request_id":"2","action":"metrics.list","target":{"session_id":"c"},"args":{}}' \
  | VCS_HOME=$VCS_HOME XVERIF_HOME=$PWD ./xcov/bin/xcov --stdio-loop
```

Fixtures：`.xverif-test-cache/fixtures/xcov.{comprehensive,exclusion,large_summary,modinfo_edge_layouts,zero_coverable}/versions/<hash>/resources/*.vdb`。
`tmp/` 是 gitignored 的临时目录，可放 probe。

## 5. 重要约定与坑

1. **`tools/xcov` 默认 C++**：对拍 Python 必须显式 `XVERIF_XCOV_BACKEND=urg`（`test_cpp_parity.py` 已修）。
2. **`set_annotation` 需要持久化 handle**（`make_persistent`），否则 rc=0 但 EL 不写。
3. **`covdb_get` 对不支持属性返回 0 / -1**，不抛错；批量设置后必须回读 status 验证。
4. **`covdb_configure(covdbExcludeMode)` 的枚举值是 28**（不是 94）；但 UCAPI 本身不拒绝 covered，
   strict 由 xcov 自己检查。
5. **generate 层是合成的**：导航父链含合成 scope，deep 聚合用 `metric_parent` 跳到最近真实祖先。
   改动 `fill_missing_scopes`/`finalize_scope_metrics` 必须重跑 `xcov.cpp_parity`。
6. **`scan_code` 的 FSM 只统计 `transitions` 子树**（`in_transitions` 必须向下传递）。
7. **`coverage` 块用 self 指标**（`scope->metrics`），与 gaps 同口径；summary 用 deep。
8. **`el_parser` 接受 test 级 covergroup 段**（section_name 为空 → TEST）。
9. **CSV 记录 key 不统一是历史坑**：`ExclusionRecord` 有 `kind`/`scope`/`name`/`full_name`，
   remove 与 export 必须用同一 key 公式。
10. **invalidate 只在真正修改后调用**，否则触发全库 refresh（large 上 240 ms）。

## 6. 待办优先级建议

1. 修第 9 轮剩余 P1（metrics.list 行数/synthetic、scope.summary 计数、line selector）
2. 修 CSV 记录 key 统一（container/functional 的 remove/export）
3. 实现 `run_manifest` provenance gate 或从 schema 删除
4. 决策：`sort`/`query`/`overflow`/`max_items=0` 是实现还是从 schema 删除（AGENTS.md 禁止静默忽略）
5. `session.close` 的 dirty reason（README 有合同）
6. 评估 `ref_locators_` 上限（大规模导出内存）
7. 重新跑全量回归 + 发布（**当前未发布任何 release**）
