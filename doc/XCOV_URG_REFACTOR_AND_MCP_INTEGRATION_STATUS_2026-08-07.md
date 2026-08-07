# xcov URG 重构与 MCP 集成状态

日期：2026-08-07

## 架构概述

### 双后端架构

| 后端 | 用途 | 依赖 |
|---|---|---|
| `UrgAggBackend` (`xcov/xcov/urg_backend.py`) | 读：scope 级聚合覆盖率数据 | `urg -xml_verbose` → `session.xml` |
| `NpiCoverageBackend` (`xcov/xcov/backend.py`) | 写：exclusion 操作 (add/remove/load/save) | `pynpi` (Verdi NPI) |

**读取路径**：`UrgAggBackend` 运行 `urg -xml_verbose` 生成 `session.xml`，解析其中的 scope 聚合数据（`value="covered/total"`），无需逐 leaf 遍历 NPI。相比旧方案（每次 `items()` 调用 1.4M 次 NPI 调用），性能有数量级提升。

**写入路径**：exclusion 操作仍走 `NpiCoverageBackend`，因为 URG 不支持 exclusion 写入。

**导出路径**：`export.*` action 调用 `urg -show brief -elfile -metric → output_dir` 生成 modinfo/grpinfo 文本文件。

### MCP 传输层

```
MCP client → xverif_cov_session_open
  → XverifCoverageAdapter.session_open()
    → McpSessionManager.open_session()
      → DirectLauncher.start()
        → JsonlProcess (subprocess.Popen)
          → tools/xcov --stdio-loop
            → python3 -m xcov.cli --stdio-loop
```

xcov stdio-loop 协议：JSONL over stdin/stdout，响应信封格式：
```json
{"request_id": "...", "ok": true/false, "payload_format": "xout", "json": {...}, "xout": "..."}
```

## 本次修改

### 1. MCP 子进程通信修复

**文件**：`xverif_mcp/src/xverif_loop/lsf/protocol.py`（及两个 build 副本）

**问题**：xcov stdio-loop 响应用 `request_id` 作为关联字段，但 `JsonlProcess.read_json_response()` 只检查 `id` 字段。导致所有 xcov session 操作返回 `SESSION_OPEN_TRANSPORT_FAILED`（proc 被 SIGTERM，4ms 内退出）。

**修复**：第 294 行 `msg_id = msg.get("id") or msg.get("request_id")`，同时接受两种字段名。

### 2. 删除所有 Fake Backend

**文件**：`xverif_mcp/tests/test_mcp_sdk_smoke.py`

- 删除 `_InjectedCoverageLoopManager` 类（约 65 行）
- 删除 `_inject_fake_coverage()` 函数
- `test_cov_session_fake_lifecycle` → `test_cov_session_real_lifecycle`：使用真实 VDB + 真实 `--stdio-loop` 子进程
- `test_batch_fake_lifecycle` → `test_batch_real_lifecycle`：同上

### 3. MCP SDK 全链路集成测试

**文件**：`xverif_mcp/tests/test_xcov_mcp_integration.py`（新增，14 个测试）

通过真实 `tools/xcov --stdio-loop` 子进程测试：

| 测试 | MCP Tool |
|---|---|
| `test_cov_list_actions` | `xverif_cov_list_actions` |
| `test_cov_session_open_close` | `xverif_cov_session_open/close` |
| `test_cov_code_coverage_summary` | `xverif_cov_query(code_coverage.summary)` |
| `test_cov_code_coverage_holes` | `xverif_cov_query(code_coverage.holes)` |
| `test_cov_scope_summary` | `xverif_cov_query(scope.summary)` |
| `test_cov_scope_children` | `xverif_cov_query(scope.children)` |
| `test_cov_export_code_coverage` | `xverif_cov_query(export.code_coverage)` |
| `test_cov_export_functional` | `xverif_cov_query(export.functional_coverage)` |
| `test_cov_export_assert` | `xverif_cov_query(export.assert)` |
| `test_cov_assert_summary` | `xverif_cov_query(assert.summary)` |
| `test_cov_functional_summary` | `xverif_cov_query(functional_coverage.summary)` |
| `test_cov_metrics_list` | `xverif_cov_query(metrics.list)` |
| `test_cov_tests_list` | `xverif_cov_query(tests.list)` |
| `test_cov_xout_output_format` | `xverif_cov_query(xout 格式)` |

### 4. 测试套件注册

**文件**：`testinfra/catalog.v1.yaml`

```yaml
- id: xcov.mcp_integration
  owner: xcov
  level: system
  intent: [contract, lifecycle, integration]
  domains: [coverage, mcp]
  runner: {kind: pytest, path: xverif_mcp/tests/test_xcov_mcp_integration.py}
  fixtures: [xcov.comprehensive]
  capabilities: [child_process, npi]
  cost: {class: slow, estimate_sec: 120}
  timeouts: {execute_sec: 600, cleanup_sec: 30}
```

### 5. Exclusion 测试重构

**文件**：`xcov/tests/test_exclusions.py`

- 删除 `_FakeBackend` 类（约 160 行）
- `_dispatcher()` 改用 `NpiCoverageBackend` 单例（进程级缓存，避免 NPI 重复 init）
- `_write_csvs` 数据更新为真实 exclusion VDB 的 scope/file/line：
  - code: `scope=top, metric=line, line=72, file=exclusion_fixture.sv`
  - functional: `scope=top, line=57, covergroup=top::behavior_cg`
  - assertion: `scope=top.u_dut, line=40, assertion=a_no_unknown`
- Git 测试改用 `exclusion_fixture.sv` 作为源文件

### 6. Fixture 迁移

- 从 `tmp/comprehensive_test/` 迁移到正式目录：`xcov/fixtures/comprehensive/`
- VDB 已通过 testinfra 构建并缓存：`.xverif-test-cache/fixtures/xcov.comprehensive/`
- `tmp/comprehensive_test/` 已清理

### 7. 已删除的 Action

以下 action 及其 handler 在之前的重构中已被删除（`xcov/xcov/actions.py`）：
- `source.map`
- `source.annotate`
- `exclude.list`

### 8. FakeCoverageBackend 删除

`xcov/xcov/backend.py` 中的 `FakeCoverageBackend` 类（约 280 行）已完全删除。

## 测试状态

### 通过的套件

| 套件 | 数量 | Gate |
|---|---|---|
| `xverif_mcp.process` | 154 passed | regression |
| `xcov.mcp_integration` | 14 passed | nightly |
| `xcov.unit` (exclusion) | 10/19 passed | regression |
| `xcov.unit` (test_xcov) | 109/157 passed | regression |

### Exclusion 测试剩余失败（9 个）

| 测试 | 失败原因 |
|---|---|
| `test_native_exclusion_add_remove_export_load_and_unload` | NPI `exclude.add` 对大部分 item 返回 `failed`，需逐 item 尝试 |
| `test_csv_compile_publishes_three_files_and_loads_union` | NPI EL 生成后 load 回报 `Module checksum mismatch` |
| `test_csv_git_and_stamp_actions_satisfy_public_response_contract` | 全量运行受 NPI 单例状态影响（单独运行通过） |
| `test_git_status_is_per_source_group_and_detects_line_shift` | 同上 |
| `test_git_group_status_change_matrix` × 5 | 同上 |

### test_xcov.py 失败（48 个，已有问题）

原因：之前删除的 action (`source.map`, `source.annotate`, `exclude.list`) 和 `FakeCoverageBackend` 导致相关测试用例的 action/response 合同不匹配。这些测试需要更新以反映新的 action 集合和 `UrgAggBackend` 的响应结构。

## 环境依赖

- Python: `.conda-xverif/bin/python` (3.12)
- NPI: `PYTHONPATH=$VERDI_HOME/share/NPI/python`（Python 3.14 不兼容，segfault）
- VDB fixtures: 通过 `pytest --xverif-prepare <fixture-id>` 构建

### 构建 Fixture

```bash
# Comprehensive VDB (xcov.comprehensive)
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-prepare xcov.comprehensive

# Exclusion VDB (xcov.exclusion)
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-prepare xcov.exclusion
```

### 运行测试

```bash
# MCP 集成测试
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate nightly --xverif-suite xcov.mcp_integration -v

# Exclusion 测试
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression --xverif-suite xcov.unit -v -k exclusion
```

## 待办

1. 修复 `test_native_exclusion_add_remove_export_load_and_unload`：找到 NPI 稳定接受 exclude 的 item
2. 解决 EL checksum mismatch：可能与 VDB 编译参数有关
3. Git 测试 NPI 状态污染：考虑将 git 测试与 NPI 测试拆分为独立套件
4. 48 个 `test_xcov.py` 失败：更新测试以匹配新 action 集合和后端响应结构
