# MCP 环境变量默认合同测试补强计划

## 1. 背景与目标

2026-08-16 的 MCP 权限加固新增 mutation、artifact write、artifact root 和三项 batch
资源上限环境变量。随后发现 `XVERIF_MCP_ENABLE_MUTATION` 默认关闭会使标准 MCP 启动后不注册
session open/close 工具，而真实 lifecycle 测试又统一显式设置为 `1`，没有覆盖用户默认启动路径。
提交 `666e18d` 已将 mutation 默认值改为 `1`，本任务负责补齐测试合同，防止同类回归。

本任务覆盖以下六个环境变量：

- `XVERIF_MCP_ENABLE_MUTATION`
- `XVERIF_MCP_ENABLE_ARTIFACT_WRITE`
- `XVERIF_MCP_ARTIFACT_ROOT`
- `XVERIF_MCP_BATCH_MAX_INPUT_BYTES`
- `XVERIF_MCP_BATCH_MAX_REQUESTS`
- `XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES`

不修改上述变量的产品默认值、公开 schema 或运行时业务行为。

## 2. 验收标准

1. 未设置 mutation 环境变量时，debug/cov session lifecycle 工具正常注册，并至少完成一次
   无真实 EDA 数据依赖的 session open tool dispatch。
2. 显式设置 mutation 为 `0` 时，固定 lifecycle 工具隐藏，动态 mutation action 返回
   `MCP_MUTATION_DISABLED`。
3. artifact write 默认关闭；默认工具目录不注册 batch，也不公开通用输出文件参数。
4. artifact write 开启时必须提供既有 root，合法相对路径受 root containment 约束，逃逸路径被拒绝。
5. 三项 batch 上限具有精确默认值，合法正整数覆盖值生效，空、零、负数、空白和非数字被拒绝。
6. 正式 focused unit/process/真实 MCP suites 通过，所有真实 suite 只消费既有 fixture cache。
7. 测试前后 fixture 的 `current.json` 内容哈希、fingerprint 和 version 完全不变。

## 3. Fixture 冻结基线

禁止运行 `--xverif-prepare`、`--xverif-fixture-validation`、VCS fixture Makefile 或其它缓存生成入口。
若正式 focused suite 报 cache miss 或指纹不匹配，立即停止并报告，不重建、不 fallback。

| Fixture | current.json SHA-256 | Fingerprint | Version |
| --- | --- | --- | --- |
| `xdebug.active_driver` | `b2010743fe5f268d6181043e9861ef6e37666a6718e8bdda4ebd1be2fd2a39d9` | `133080dd144718dab3a521427d457d1128176b9678980c40123dc40ac33c439c` | `133080dd144718dab3a521427d457d1128176b9678980c40123dc40ac33c439c-prepare-z821urh5` |
| `xcov.comprehensive` | `757d4aa181908d7eea88729f1f52c2551e2c49c245d13eeb4ab5c440934fa247` | `6c6c9c1557c9604260b4d1198cdd690be24b075d8528c9fe634b6fae62d9182b` | `6c6c9c1557c9604260b4d1198cdd690be24b075d8528c9fe634b6fae62d9182b-prepare-1mgdsmek` |
| `xcov.exclusion` | `1b9f463d9b8d4aa8a8dcd1bfe69ff03ea4d2ddfe5a4860de670a64f3a2ce9018` | `18702a976f59626965990d199bbf58a71e823d89f249fcb8f7f80d4f18f7c3c6` | `18702a976f59626965990d199bbf58a71e823d89f249fcb8f7f80d4f18f7c3c6-prepare-2iil1p2a` |

## 4. 分阶段实施

| 阶段 | 内容 | 状态 | 提交 |
| --- | --- | --- | --- |
| P0 | 推送 `666e18d`、建立计划与 fixture 基线 | completed | 本计划提交 |
| P1 | 补齐纯策略、默认工具注册和 fake dispatch 测试 | completed | 本阶段测试提交 |
| P2 | 让真实 MCP lifecycle 测试消费 mutation 公共默认值 | completed | 本阶段真实链路提交 |
| P3 | focused suite 验收、fixture 哈希复核和报告收口 | pending | pending |

### P1：无 Fixture 测试

- 扩充 `xverif_mcp.unit` 的默认值、严格解析、artifact containment 和 batch 上限矩阵。
- 重构 MCP server 测试 helper，取消 mutation 隐式开启，区分公共默认与 artifact-enabled profile。
- 在公共默认 profile 下验证 lifecycle 工具注册、batch 隐藏、输出参数隐藏和 fake session open dispatch。
- 将旧的“默认只读”用例改为明确的“显式 mutation=0”合同。

### P2：真实 MCP 默认路径

- 从 xcov integration、action smoke 和 real fullchain 测试环境中移除显式 mutation=1。
- 需要落盘的测试继续显式开启 artifact write，并使用用例临时目录作为 artifact root。
- 不调整 fixture 定义、fingerprint 输入或 test catalog membership。

### P3：验证命令

1. `.conda-xverif/bin/pytest --xverif-gate fast --xverif-suite xverif_mcp.unit`
2. `XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xverif_mcp.process`
3. `XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xverif_mcp.action_smoke`
4. `XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate nightly --xverif-suite xcov.mcp_integration`
5. `XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate nightly --xverif-suite xverif_mcp.real_fullchain`

## 5. 进度与结果

- 2026-08-18：宿主推送 `master` 成功，`origin/master` 指向 `666e18dad2872f8908d9cf0abfd89e04a8cd8336`。
- 2026-08-18：记录三个 fixture 的冻结基线；未执行 prepare 或 fixture validation。
- 2026-08-18：建立 Goal，目标包含六变量合同、五个正式 focused suites、fixture 不变验收和禁止 fallback 约束。
- 2026-08-18：P1 已补入六变量解析矩阵、公共默认工具目录、无 mutation 环境变量的 fake session open dispatch 和 server 初始化失败合同，等待正式 suite 验证。
- 2026-08-18：fast `xverif_mcp.unit` 通过，`215 passed`；结果目录 `.xverif-test-results/20260818-210615-1oa2uxnq`。
- 2026-08-18：host regression `xverif_mcp.process` 通过，`164 passed`；结果目录 `.xverif-test-results/20260818-210631-d1j5l928`。
- 2026-08-18：P2 已从 xcov integration、action smoke 和 real fullchain 删除 mutation 显式开启；artifact 写测试继续使用隔离授权，等待真实 focused suites 验证。
- 2026-08-18：host regression `xverif_mcp.action_smoke` 通过，`1 passed`；结果目录 `.xverif-test-results/20260818-210752-6x6hioz7`。
- 2026-08-18：host nightly `xcov.mcp_integration` 通过，`17 passed`；结果目录 `.xverif-test-results/20260818-210812-jwp4d31k`。
- 2026-08-18：host nightly `xverif_mcp.real_fullchain` 通过，`1 passed`；结果目录 `.xverif-test-results/20260818-210917-8rvglrjm`。
- P1/P2/P3 的测试结果和提交 ID 在实施后追加到本节。
