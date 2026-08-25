# SDK-free xdebug/xcov LSF CLI 总览

SDK-free LSF CLI 只用于“没有可用 xverif MCP，且必须经 LSF 运行”的
场景。它使用 Python 在登录节点透明托管内部 manager，再通过
`bsub -I tools/xdebug --stdio-loop` 或 `bsub -I tools/xcov --stdio-loop`
与计算节点通信，不要求登录节点直连计算节点 UDS/TCP。

公开入口：

```bash
tools/xdebug_lsf
tools/xcov_lsf
tools/xverif_lsf_env_capture
```

## 路由顺序

1. AI 已配置 xverif MCP：直接使用 MCP。
2. 无 MCP 且必须使用 LSF：使用 `xdebug_lsf` / `xcov_lsf`。
3. 无 LSF 限制：使用原生 `tools/xdebug` / `tools/xcov`。

不因失败自动切换入口、backend 或 transport。SDK-free 公开入口固定使用
LSF，不提供 direct 模式。

## 请求合同

`xdebug_lsf` 与 `xdebug`、`xcov_lsf` 与 `xcov` 使用同一份原生
JSON request envelope：

```bash
tools/xdebug_lsf --json - <<'EOF'
{"api_version":"xdebug.v1","request_id":"q1","action":"value.at","target":{"session_id":"s0"},"args":{"signal":"top.data","time":"10ns"}}
EOF
```

SDK-free 也可直接取得与 MCP/原生 CLI 共用的 action guide：

```bash
tools/xdebug_lsf --json - <<'EOF'
{"api_version":"xdebug.v1","action":"actions","args":{"output":{"view":"guide"}}}
EOF
```

guide 每行仅含 `name: description_en`，不含 status/`use_when`；native runtime
执行 10,000 UTF-8 字节硬门禁。wrapper 不增加专用参数，也不二次格式化。

```bash
tools/xcov_lsf --json - <<'EOF'
{"api_version":"xcov.v1","request_id":"q2","action":"code_coverage.summary","target":{"session_id":"cov0"},"args":{"group_by":"metric","metrics":["line","toggle"]}}
EOF
```

不再公开 `method/params` wrapper envelope，也不需要用户显式启动 server、
指定 socket 或调用 client。`--stdio-loop` 是内部协议，两个 LSF CLI
都明确拒绝该公开参数。

## 终端环境配置

两个入口默认读取自身同目录的 `xverif_lsf.env.json`。在已完成 EDA、license、
Python 和 LSF 初始化的终端生成配置：

```bash
tools/xverif_lsf_env_capture --dry-run
tools/xverif_lsf_env_capture
```

默认不覆盖已有文件；更新时显式使用 `--force`。站点变量用重复的
`--include NAME` 加入。也可设置 `XVERIF_LSF_CLI_CONFIG=/absolute/path.json`
覆盖默认路径。配置只影响 SDK-free 入口；MCP 不读取它。

## 能力边界

- session-bound 请求复用长期 LSF stdio-loop。
- `actions/schema` 和无 session 请求使用临时 LSF stdio-loop，请求后立即清理。
- manager 只在存在 live/unresolved session 或活动请求时保持，空闲后自动退出。
- xbit/xentry/xloc/xsva 不需要该 wrapper，继续使用各自原生入口。
