# xcov UCAPI C++ 重写：任务说明与验收指标

> **状态：C++/UCAPI 实现已完成（2026-11-25），最终发布策略为默认 `urg`、`ucapi` 可选试用。**
> 最终 review 状态、已知限制和提交索引以 [xcov-ucapi-handoff.md](xcov-ucapi-handoff.md) 与
> [xcov-ucapi-plan-v2.md](xcov-ucapi-plan-v2.md) 为准；本文保留原始实施合同，其中“默认 C++”
> 等表述是原始目标，不再是最终默认。

本文是 `xcov` 从 Python 重写为 C++ 的实施合同。所有阶段以本文的验收项为准；
未全部通过前不得推送 release。

## 1. 目标

把 `xcov` 重写为 C++ 可执行，直连 UCAPI（`libucapi.so`），作为可选试用后端；默认仍保留
Python/URG 实现，不强制移除 pynpi；
保留原有 30 个 action 的公共合同（action 名、schema、错误码、XOUT grammar、
stdio-loop 帧）；支持 CSV 与 EL+annotation 双向转换，并能读取 EL 的 annotation。

## 2. 不可违反的约束

1. 公共合同不变：30 个 action 的 request/response schema、错误码、`xcov-stdio-loop`
   ready/quit 帧、XOUT grammar 必须与 Python 版逐字段一致。
2. 不引入 XML 解析：UCAPI 直接读 VDB，C++ 版不实现 URG 后端，也不解析
   `session.xml`。
3. 显式后端选择：`XVERIF_XCOV_BACKEND=urg`（默认）或 `=ucapi`（可选试用）；非法值或不可用必须
   返回结构化错误，不静默 fallback。两种后端都必须通过回归测试：`ucapi` 走 C++
   实现，`urg` 走 legacy 实现（`XVERIF_XCOV_IMPL=py`）。
4. URG 后端保留 Python 实现：`XVERIF_XCOV_BACKEND=urg` 直接运行旧的 Python 入口。
5. annotation 语义：EL 的 `ANNOTATION:` 归属紧随其后的对象行；引号必须转义；
   修改 annotation 不得改变 `CHECKSUM:` 与对象 checksum。
6. 测试缓存复用：全量回归使用仓库既有 fixture 缓存，不重复 rebuild。

## 3. 验收指标

### 3.1 功能一致性

| 指标 | 通过标准 |
| --- | --- |
| 读 action 对拍 | 8 个 action（tests.list、metrics.list、scope.summary、scope.children、scope.search、code/functional/assert summary）在 large.vdb 上与 Python 输出逐字段一致，差异 0 |
| 导出一致性 | export.assert gap=94；export.functional gap=2119（UCAPI 口径）；export.code 320 scope=7027 gap（含 top=7028） |
| exclusion 闭环 | `export.code_coverage → coverage_ref → exclude.add(reason) → export.exclude` 产出的 EL 含 `ANNOTATION:`；新 session `exclude.load` 后 `exclude.csv.export` 的 CSV reason 正确 |
| action 覆盖 | 30 个 action 全部返回合法响应（成功或结构化错误），无 `ACTION_NOT_IMPLEMENTED` |
| 双后端切换 | `XVERIF_XCOV_BACKEND=ucapi`（C++）与 `XVERIF_XCOV_BACKEND=urg`（legacy）都能打开 VDB 并完成 8 个读 action；切换只由 `XVERIF_XCOV_BACKEND` 显式触发 |
| stdio-loop | ready 帧含 `protocol=xcov-stdio-loop`、`version=1`；`stdio.quit` 正常退出；单请求 JSON/XOUT 均可用 |

### 3.2 性能

| 场景 | 通过标准 |
| --- | --- |
| large.vdb 全能力 | ≤ 0.5 s |
| huge.vdb 全能力 | ≤ 6 s |
| gap 导出 | ≤ 6 s |
| 内存峰值 | 不高于现 URG 路径的 60% |

### 3.3 工程门禁

| 指标 | 通过标准 |
| --- | --- |
| 构建 | `make -C xcov` 零错误；`ldd xcov/bin/xcov` 不含 python/pynpi/urg |
| 测试 catalog | 新增 `xcov.cpp_parity` suite 并接入 catalog |
| 全量回归 | `XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression -n auto` 全绿，复用 fixture 缓存 |
| 清理 | `grep -r pynpi xcov/` 为空；`xcov/xcov/*.py` 已删除 |
| 文档 | `xcov/README.md`、`skills/xverif/references/xcov.md` 同步 |

### 3.4 提交与发布

- commit message 使用中文，写明动机、范围、验证结果。
- 提交前 `git status --short` 只包含本任务相关文件。
- 全部验收项通过后才推送远端并发布 release。

## 4. 阶段任务与当前状态

### 阶段 0：合同冻结（已完成）

- [x] 63 个 schema 导出为 JSON（`xcov/xcov/schemas_data/v1`）
- [x] Python 从 JSON 加载（`schemas.py` 末尾加载层）
- [x] `xcov/tests/test_schema_export.py` 验证等价
- [x] 30 个 action 元数据导出（`actions.json`）

验收命令：`pytest --xverif-gate regression --xverif-suite xcov.unit`

### 阶段 1：C++ 骨架 + UCAPI 读能力（已完成）

- [x] `xcov/Makefile`、`src/main.cpp`、api/core 层
- [x] `ucapi_loader`（dlopen + dlsym）、`ucapi_backend`（deep 聚合）
- [x] 8 个读 action 与 Python 对拍一致

验收命令：`python tmp/ucapi-vs-urg-20261124/parity_read.py`

### 阶段 2：导出与 exclusion（进行中）

- [x] export.assert（94 gap）
- [x] export.functional_coverage（2119 gap）
- [x] export.code_coverage（7027 gap）
- [x] exclude.add/remove/load/unload、export.exclude
- [ ] `exclude.csv.compile`（CSV→EL）
- [ ] `exclude.instance.add/remove`、`exclude.functional.add/remove`
- [ ] `exclude.csv.validate/apply/format`

### 阶段 3：EL 与 annotation（部分完成）

- [x] EL 写入 annotation（UCAPI set_annotation + durable）
- [x] EL 读取 annotation（自研 `el_parser`，`exclude.load` 解析）
- [x] `exclude.csv.export` 输出 reason
- [ ] CSV→EL+annotation 转换 action
- [ ] EL→CSV 的完整 locator 映射

### 阶段 4：切换与对拍 suite（未开始）

- [ ] `xcov.cpp_parity` suite 接入 `testinfra/catalog.v1.yaml`
- [x] `tools/xcov` 按 `XVERIF_XCOV_BACKEND` 选择实现（ucapi→C++，urg→Python）
- [ ] 双后端冒烟测试

### 阶段 5：移除 Python 与发布（未开始）

- [x] 发布时保留 Python 实现作为默认 `urg` 后端（不删除）
- [x] 保留 catalog 的 `npi` capability 与 `xcov.exclusion_npi`
- [x] 全量回归
- [x] 提交 + 推送 + 发布最终 release（`xverif-1.0.7`）

## 5. 技术要点（实现参考）

### 5.1 UCAPI 语义对齐

- FSM 只统计 `transitions` 子树。
- Assert 用 `covdbCovCount`；cover property 用 all-match，assertion 用 realsuccesses。
- scope 指标是子树聚合：自底向上累加 `deep_metrics`。
- covergroup 用 variant 的 `covdbFullName`，score 为直接 coverpoint/cross 的 pct 平均。
- 顶层 container 的 `covdbCovered/coverable` 求和恒等于 leaf 递归。

### 5.2 关键文件

| 文件 | 作用 |
| --- | --- |
| `xcov/src/main.cpp` | CLI / `--stdio-loop` |
| `xcov/src/api/schema.cpp` | JSON schema 加载与 Draft-7 子集校验 |
| `xcov/src/api/protocol.cpp` | request 解析、JSON/XOUT 渲染 |
| `xcov/src/coverage/ucapi_loader.cpp` | dlopen libucapi |
| `xcov/src/coverage/ucapi_backend.cpp` | 遍历、聚合、exclusion |
| `xcov/src/coverage/coverage_ref.cpp` | `xcovref.v1:` 引用 |
| `xcov/src/exclusion/el_parser.cpp` | EL 解析（含 ANNOTATION） |
| `xcov/src/exclusion/csv_parser.cpp` | CSV 解析 |
| `xcov/src/actions/dispatch.cpp` | action 分发与响应投影 |

### 5.3 已知失败模式

| 场景 | 期望 |
| --- | --- |
| libucapi 缺失 | `UCAPI_LIBRARY_NOT_FOUND`，不切 URG |
| `XVERIF_XCOV_BACKEND=urg` + impl=cpp | `BACKEND_UNSUPPORTED_BY_IMPL` |
| EL 语法错误 | `EL_PARSE_FAILED` + file:line |
| annotation 未转义引号 | 写入自动 `\"`；解析报 `EL_PARSE_FAILED` |
| `CHECKSUM` 不匹配 | 保留 `Module checksum mismatch` 语义 |
| `detail.returncode` | schema 要求 `minimum: 0`，负数必须归一为 0 |

## 6. 回归与发布流程

1. `make -C xcov` 零错误。
2. `pytest --xverif-gate regression --xverif-suite xcov.unit`
3. `pytest --xverif-gate regression --xverif-suite xcov.cpp_parity`
4. `XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression -n auto`（复用缓存）
5. `git status --short` 检查范围，中文 commit。
6. 推送当前分支，创建 release tag。

## 7. 当前进度快照

- 已完成：阶段 0、阶段 1、阶段 2 的导出与基础 exclusion、阶段 3 的 EL annotation 读写。
- 进行中：阶段 2 的 CSV compile 与容器排除。
- 未开始：阶段 4、阶段 5。
- 最后更新：2026-11-24。
