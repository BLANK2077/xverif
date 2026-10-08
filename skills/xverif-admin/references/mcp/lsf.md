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
- `XVERIF_LSF_SESSION_WALL_TIME_SEC`，默认 `7200`（2 小时），提交为 `-W <分钟>`
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

## `-W` runtime limit

每个 session job 都带 LSF `-W`：`XVERIF_LSF_SESSION_WALL_TIME_SEC`（单位秒，无首尾空白的
有限正数，上限 31536000）向上取整到分钟，默认 7200 秒即 `-W 120`。它只接受秒值，不提供
`off`/无限语法；需要更长会话时显式调大数值。

- `scheduler.requested.wall_time_sec`、`scheduler.effective.wall_time_sec` 是 xverif 解析出的
  秒值；`scheduler.submitted.wall_time_minutes` 是真实 argv 里 `-W` 的分钟值。
- `XVERIF_LSF_BSUB` 自带 `-W` 时直接报错（不静默双写）；MCP session、SDK-free manager、
  `xdebug_lsf log` passthrough 与 doctor 共用这一个变量。
- 达到 `-W` 后由 LSF 终止 job，客户端侧只会看到 loop/bsub 提前退出（`SESSION_LOST` 或
  `startup_rejected`），此时按 `scheduler.wall_time_*` 判断是否撞上限，再按需 `gc` 残留记录。
  本机未安装 LSF，`-W` 在真实站点队列上的接受度与结束帧文本尚未实测。

xcov 外层 session job 与内层 URG job 是两个独立配置面：本页的 session queue 只控制
`bsub -I tools/xcov --stdio-loop`。若要把 cache miss 的 URG 也提交 LSF，另设
`XVERIF_XCOV_URG_BACKEND=lsf`、必填 `XVERIF_XCOV_URG_QUEUE`，以及可选
`XVERIF_XCOV_URG_RESOURCE`；内层固定 `bsub -K`。禁止从外层 queue 猜测内层 queue，任何
失败都不转 direct。

如果必须 LSF 但不能使用 MCP SDK，或要脚本化驱动 session，改用 [../sdk-free-loop/overview.md](../sdk-free-loop/overview.md)。
