# xdebug 排障

## 日志位置

- public actions：`~/.xdebug/sessions/<session_prefix>_<hash>/owners/*/logs/actions.ndjson`
- stdio-loop：同目录 `stdio.ndjson`
- engine lifecycle/transport/crash：`~/.xdebug/engine/sessions/<hashed-session>/owners/*/logs/`
- NPI startup：同目录 `npi_startup.log`，保存 init/load/open 阶段的原始 diagnostic
- health：各 logs 目录下的 `log_health.ndjson`

常用命令：

```bash
xdebug log doctor --session <id> --json
xdebug log tail --session <id> --lines 40
xdebug log bundle --session <id> --out debug_bundle.redacted.tgz --redact
```

## 定位顺序

1. 看 `actions.ndjson`：action、target、elapsed_ms、最终 error。
2. stdout/ready/invalid JSON 问题看 `stdio.ndjson`。
3. `session.open`、`SESSION_UNHEALTHY`、`INTERNAL_ENGINE_FAILED` 看 engine `lifecycle.ndjson`。
   若为 `NPI_INIT_FAILED`、`NPI_LOAD_DESIGN_FAILED` 或 `NPI_FSDB_OPEN_FAILED`，
   再用 `xdebug log tail --session <id>` 查看 `npi_startup.log`。
4. socket/TCP/ping/daemon 连接问题看 `transport.ndjson`。
5. crash 或异常退出看 `crash_marker.ndjson` 和 `log_health.ndjson`。

## 常见错误

- `SESSION_DEAD` / `SESSION_UNHEALTHY`：session 不可复用，先 close/gc，再重新 open。
- `INTERNAL_ENGINE_FAILED`：看 lifecycle 是否 NPI init、design load、FSDB open 或 daemon ready 失败。
- `socket.connect.failed`：确认 socket_path、transport、namespace、文件是否存在。
- `socket.read.timeout`：检查查询是否过大、daemon 是否卡住、timeout 是否过短。
- `REQUEST_TOO_LARGE`：根据 `received_bytes/max_bytes` 确认边界，并结合 `transport/phase` 定位拒绝位置；按 `next_actions` 拆分 batch、减少内联配置或使用有界 export。不要通过提高环境上限、截断 JSON 或切换 transport 绕过门禁。
- `INVALID_CONFIG`：根据 `config_key/config_source/expected` 修正配置后启动新进程；不要在当前进程重试或静默采用默认值。`received_redacted=true` 只表示敏感原值已隐藏，不影响配置键和来源的诊断。
- invalid JSON / stdout pollution：看 `stdio.ndjson` 的 `stdout.pollution`、`ready.stdout_non_json`。
- license/NPI 连接失败：在沙箱外复跑，确认 Verdi/NPI 环境和 license server。
- `LICENSE_ENV_NOT_EXPLICIT`：`SNPSLMD_LICENSE_FILE` 和 `LM_LICENSE_FILE` 都没有显式
  传入 engine；检查 MCP server 的 `env`，但不要据此排除 site 的其它 licensing mechanism。

## 路径脱敏

对外共享日志默认使用：

```bash
xdebug log bundle --session <id> --out debug_bundle.redacted.tgz --redact
```

原始 `npi_startup.log` 可能包含 site/license diagnostic，只进入普通 bundle；redacted
bundle 会排除它并保留结构化 lifecycle 摘要。

可用 `XDEBUG_LOG_PATH_MODE=basename|hash` 或 `XDEBUG_LOG_REDACT=1` 控制路径字段。
