---
name: xverif-admin
description: >
  用于 xverif 的安装配置、MCP direct/LSF backend、ssh 远端 MCP（mcp_ssh）、
  SDK-free LSF CLI、UDS/TCP/file transport、session tombstone/gc、timeout、
  环境变量、license 和 server 启动排障。普通波形、coverage、bit 或协议查询使用 xverif。
---

# xverif Admin

只处理运行环境和托管生命周期，不承载 xdebug/xcov 业务语义。

## 路由

| 任务 | 读取 |
| --- | --- |
| MCP 工具定位与配置 | [MCP overview](references/mcp/overview.md) |
| ssh 远端 MCP（`mcp_ssh`）配置与排障 | [远端 ssh backend](references/mcp/overview.md) |
| stateful session 生命周期 | [stateful sessions](references/mcp/stateful-sessions.md) |
| MCP LSF backend | [MCP LSF](references/mcp/lsf.md) |
| MCP 排障 | [MCP troubleshooting](references/mcp/troubleshooting.md) |
| SDK-free LSF CLI | [SDK-free overview](references/sdk-free-loop/overview.md) |
| UDS JSONL | [UDS JSONL](references/sdk-free-loop/uds-jsonl.md) |
| SDK-free LSF | [SDK-free LSF](references/sdk-free-loop/lsf.md) |
| xdebug transport | [transport](references/xdebug-transport.md) |
| engine/session 排障 | [xdebug troubleshooting](references/xdebug-troubleshooting.md) |

## 规则

- 常规验证查询回到 `xverif`。
- 不自动 retry、reopen 或切换 direct/LSF、UDS/TCP/file。
- SESSION_LOST 先检查 terminal source、tombstone 和 doctor，再由用户决定 cleanup/reopen。
- NPI、真实 FSDB/VDB、LSF、license、MCP stdio-loop 和 transport 实机动作在沙箱外执行。
- 路由的唯一权威是 `skills/xverif/references/core/execution-model.md`；本 skill 只补充运维侧约束：
  已注入 MCP 时使用 MCP；MCP 为 `mcp_ssh` 远端注入时语义与 session 都在 EDA 机器；无 MCP 且
  必须 LSF 时使用 `xdebug_lsf` / `xcov_lsf`（固定 LSF，不提供 direct）；不需要 LSF 时使用原生工具。
- 远端 ssh 形态下，站点 `VERDI_HOME`/license 变量写在 MCP client 的 `env` 里并转发，`HOME`
  等本机身份变量不转发；session 状态在远端本机 `$HOME`，不需要共享 `$HOME`。
- 终端环境捕获、入口同目录配置、`-env all` 和远端环境指纹只属于 SDK-free
  LSF；不得把这些行为扩展到 MCP direct/LSF 或 `mcp_ssh`。
