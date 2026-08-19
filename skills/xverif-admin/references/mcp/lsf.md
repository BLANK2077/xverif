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

每个 managed session 都启动一个独立 stdio-loop；LSF 模式下一一对应独立 interactive
job。xcov native loop 只允许一个 live VDB session，多 session 由 manager 启动多个 loop，
不是在同一进程里创建多个 VDB session。

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
非法配置直接产生 typed config error。MCP 不读取 SDK-free LSF CLI 的
`XVERIF_LSF_CLI_FAKE_LSF`，
启动、ready、请求或 cleanup 失败也不会切换到 fake/direct 等其它 backend。

MCP server 子进程不会自动继承 IDE/shell 外的环境。必须在 MCP 配置里显式列出计算节点需要的 Verdi、NPI、license、PATH、LSF 变量。

queue/resource 优先级为 session open 显式参数、`XVERIF_LSF_SESSION_QUEUE` /
`XVERIF_LSF_SESSION_RESOURCE`，随后 queue 默认 `interactive`、resource 省略。session record
的 `scheduler` 始终发布 requested/effective/submitted queue/resource、job name/id 与状态；
不需要开启 verbose。`startup_timeout` 常见于 PEND 超时，`startup_rejected` 表示 bsub/job
在 ready 前退出；两者都会执行原有 process+bkill 清理，不会转 direct。
环境和 open 参数中的 queue/resource 都必须是无首尾空白的非空字符串；空值不会被接受后
静默省略 `-q/-R`，避免 effective/submitted 与真实 argv 漂移。

xcov 外层 session job 与内层 URG job 是两个独立配置面：本页的 session queue 只控制
`bsub -I tools/xcov --stdio-loop`。若要把 cache miss 的 URG 也提交 LSF，另设
`XVERIF_XCOV_URG_BACKEND=lsf`、必填 `XVERIF_XCOV_URG_QUEUE`，以及可选
`XVERIF_XCOV_URG_RESOURCE`；内层固定 `bsub -K`。禁止从外层 queue 猜测内层 queue，任何
失败都不转 direct。

如果必须 LSF 但不能使用 MCP SDK，或要脚本化驱动 session，改用 [../sdk-free-loop/overview.md](../sdk-free-loop/overview.md)。
