# MCP LSF backend

MCP 使用 LSF 时设置：

```bash
XVERIF_MCP_BACKEND=lsf
```

链路：

```text
MCP client -> xverif-mcp -> LsfLauncher -> bsub -I tools/xdebug --stdio-loop
```

xcov 同理启动 `tools/xcov --stdio-loop`。

## 环境变量

- `XVERIF_MCP_BACKEND=lsf`（只接受 `direct|lsf`）
- `XVERIF_LSF_BSUB`
- `XVERIF_LSF_BKILL`
- `XVERIF_LSF_SESSION_QUEUE`
- `XVERIF_LSF_SESSION_RESOURCE`
- `XVERIF_MCP_STARTUP_TIMEOUT_SEC`
- `XVERIF_MCP_REQUEST_TIMEOUT_SEC`
- `XVERIF_MCP_FAKE_LSF=0|1`：只属于 MCP namespace 的显式 fake LSF

启用 fake LSF 后，runtime 会在唯一配置入口成对使用
`xverif_loop.lsf.fake_bsub` 与 `xverif_loop.lsf.fake_bkill`；显式设置
`XVERIF_LSF_BSUB` 或 `XVERIF_LSF_BKILL` 时仍以对应设置为准。

布尔值只接受精确的 `0` 或 `1`；timeout 只接受无首尾空白的有限正数。
非法配置直接产生 typed config error。MCP 不读取 `XVERIF_LOOP_FAKE_LSF`，
启动、ready、请求或 cleanup 失败也不会切换到 fake/direct 等其它 backend。

MCP server 子进程不会自动继承 IDE/shell 外的环境。必须在 MCP 配置里显式列出计算节点需要的 Verdi、NPI、license、PATH、LSF 变量。

如果必须 LSF 但不能使用 MCP SDK，或要脚本化驱动 session，改用 [../sdk-free-loop/overview.md](../sdk-free-loop/overview.md)。
