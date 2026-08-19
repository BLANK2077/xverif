# SDK-free LSF 单入口实施与验收计划

## 1. 背景与目标

当登录节点与 LSF 计算节点之间的 UDS/TCP 不可达时，SDK-free Python
wrapper 通过 `bsub -I tools/xdebug --stdio-loop` 或
`bsub -I tools/xcov --stdio-loop` 托管长会话。当 MCP 已注入时应直接使用
MCP；不需要 LSF 时应直接使用原生 `xdebug` / `xcov`，不应额外
引入 Python wrapper。

本任务将当前分离的 `xverif-loop-server` / `xverif-loop-client`
收敛为两个面向用户的单文件入口：

- `tools/xdebug_lsf`
- `tools/xcov_lsf`

两者分别与原生 `tools/xdebug` / `tools/xcov` 的单请求 CLI 合同保持
一致，内部透明按需启动登录节点 manager，并通过 LSF stdio-loop
管理会话。

## 2. 固定决策

### 2.1 使用路由

1. AI 环境已注入 xverif MCP：使用 MCP。
2. 无 MCP 且必须经 LSF：使用 `xdebug_lsf` / `xcov_lsf`。
3. 无 LSF 限制：使用原生 `xdebug` / `xcov`。
4. 任何失败都不自动切换 MCP、direct backend、transport 或工具入口。

### 2.2 公开 CLI 合同

- `xdebug_lsf` 支持原生 xdebug 的 `-h/-help`、`--json|--text|--xout`、
  `request.json|-`/缺省 stdin 和 `log tail|doctor|bundle`。
- `xcov_lsf` 支持原生 xcov 的 `--json`、`--once`、`--request FILE`、
  positional file/缺省 stdin。
- 两个入口都明确拒绝用户传入 `--stdio-loop`；该协议只用于内部
  LSF backend。
- 输入直接使用原生 `xdebug.v1` / `xcov.v1` envelope，不再公开
  `id/method/params` wrapper envelope。
- stdout 仅输出原生 JSON/XOUT；manager/socket/job/cleanup 证据进结构化日志。
- 公开 response schema、输出格式和退出码与对应原生工具一致。

### 2.3 Manager 与 LSF

- SDK-free 公开模式固定为 LSF，移除公开 direct backend。MCP 内部的
  direct/LSF 能力不受影响。
- 首个请求透明启动本用户 manager，后续进程通过内部 UDS 复用。
- ready 以 server 成功进入 `listen()` 并通过显式 ready pipe 发布为准，
  不使用 socket 文件存在、固定 sleep 或静默 connect retry。
- 默认 socket 位于 `~/.xverif/lsf-cli/`，目录权限 `0700`，socket 权限
  `0600`；unsafe file/symlink/异主 socket 均 fail closed。
- 无 live/opening/unresolved session 且无请求时，manager 默认空闲 5 秒退出。
- session-bound 请求复用长期 LSF stdio-loop；stateless/无 session 请求
  使用临时 LSF stdio-loop，完成后发送 `stdio.quit` 并清理 job。

### 2.4 配置

SDK-free 公开配置收敛为 `XVERIF_LSF_CLI_*`：

- `SOCKET`、`LOG_DIR`
- `STARTUP_TIMEOUT_SEC`、`REQUEST_TIMEOUT_SEC`、`CLOSE_TIMEOUT_SEC`
- `BKILL_TIMEOUT_SEC`、`IDLE_TIMEOUT_SEC`
- `FAKE_LSF` 测试开关

LSF 命令和资源继续使用 `XVERIF_LSF_BSUB`、`XVERIF_LSF_BKILL`、
`XVERIF_LSF_SESSION_QUEUE`、`XVERIF_LSF_SESSION_RESOURCE`。

## 3. 实施阶段与提交

### Commit 1：文档：建立 SDK-free LSF 单入口实施计划

- 写入本计划和进度账本。
- 只提交本文档，不纳入工作树已有的 `AGENTS.md` 改动。

### Commit 2：运行时：收敛 SDK-free LSF manager 并加固透明启动

- 实现内部 manager 启动、ready、并发竞争、空闲退出和安全 socket。
- 增加原生 request/response 内部路由，保留 MCP 共享 session manager。
- 同步提交 hermetic 单元/进程测试。

### Commit 3：CLI：增加 xdebug_lsf/xcov_lsf 并移除旧双入口

- 实现两个原生兼容 CLI 及 wheel console scripts。
- 移除 `xverif-loop-server/client` 脚本和 package entry point。
- 同步提交 CLI differential、packaging 和失败合同测试。

### Commit 4：测试：补齐 xdebug/xcov SDK-free fake-LSF 全链路

- 新增正向 `open -> query -> doctor/status -> close` 和 stateless 测试。
- 新增 timeout/crash/pollution/rejection/partial-cleanup/no-fallback 测试。
- 新增使用现有 xdebug/xcov cache 的宿主 fake-LSF 真实数据 suite。
- 更新 test catalog 和完整性检查。

### Commit 5：文档与 Skill：固化 MCP/LSF/原生入口路由

- 更新 README、xdebug agent 协议/session 文档和 xverif-admin SDK-free reference。
- 更新 xverif/xverif-admin `SKILL.md`、surface source 和 `agents/openai.yaml`。
- 运行 skill catalog tests，安装到 Codex/Claude 并逐项 `diff -qr`。

## 4. 测试矩阵

### 4.1 纯合同

- xdebug/xcov CLI argv、stdin/file、JSON/XOUT、退出码。
- 原生 envelope 无损映射，包括 xdebug ownership token 和 xcov
  exclusion/cache/confirm-discard 参数。
- unknown field、duplicate key、NaN、oversized input、`--stdio-loop` 拒绝。
- 所有 wrapper 产生的输出通过原生 response schema。

### 4.2 进程与 fake-LSF

- 透明首启、并发首启、ready pipe、复用和空闲退出。
- xdebug 和 xcov 对称的 session 正向链路。
- stateless 临时 loop 与 job/process 清理。
- timeout、stdout pollution、child crash、SESSION_LOST、bsub rejection、
  bkill partial failure、unsafe/stale socket。
- 断言 SDK-free 失败时没有启动 direct backend。

### 4.3 真实数据、fake-LSF

- `xdebug.ai_complex_wave` 现有 cache：`value.at`。
- `xcov.comprehensive` 现有 cache：`code_coverage.summary`。
- 在 host 环境运行真实 NPI/FSDB/VDB/stdloop，LSF 层使用 fake-LSF。
- 当前环境没有真实 LSF，不新增 real-LSF suite。

## 5. Cache 和执行约束

- 禁止调用任何 `--xverif-prepare`。
- 不修改 fixture source、`testinfra/fixtures.v1.yaml` 或 fixture fingerprint 环境。
- 实施前后记录 fixture `current.json` 指针；测试只消费现有 cache。
- 如果正式 suite 报 cache miss，立即停止并报告，不 fallback、不 prepare、
  不重建。
- 涉及 NPI/FSDB/VDB/stdloop 的测试整体在 host 执行。
- 不创建 PR，不推送远端，除非用户后续明确要求。

## 6. 验收标准

- 两个新入口可以仅替换原生命令名便执行同一份单请求。
- xdebug 和 xcov 的 stateful/stateless、JSON/XOUT 和错误路径均有正式测试。
- manager 只在 LSF SDK-free 场景启动，无 MCP/原生路径混淆，无 fallback。
- 旧 server/client 入口、公开文档和 package metadata 均已清理。
- focused suites、skill suites、packaging smoke 和 catalog checks 全部通过。
- Codex/Claude 安装后 skill 与仓库 source `diff -qr` 一致。
- fixture cache 指针未被重建或替换。

## 7. 进度账本

| 阶段 | 状态 | Commit | 验证/备注 |
| --- | --- | --- | --- |
| 计划书 | 进行中 | 待填写 | 首次写入 |
| Goal | 待开始 | - | 计划书提交后建立 |
| 内部 manager | 待开始 | - | - |
| 原生兼容 CLI | 待开始 | - | - |
| SDK-free 测试 | 待开始 | - | - |
| 文档与 skill | 待开始 | - | - |
| 最终验收 | 待开始 | - | - |
