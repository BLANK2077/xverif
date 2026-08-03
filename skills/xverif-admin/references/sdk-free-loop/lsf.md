# SDK-free xdebug/xcov LSF

必须 LSF 且无法使用 MCP 或需要脚本化运行时，优先使用 SDK-free wrapper：

```bash
XVERIF_LOOP_BACKEND=lsf \
XVERIF_LOOP_SOCKET=<repo>/tmp/xverif-loop.sock \
tools/xverif-loop-server
```

server 会通过 LSF 启动：

```text
bsub -I tools/xdebug --stdio-loop
bsub -I tools/xcov --stdio-loop
```

## 常用环境变量

- `XVERIF_LOOP_BACKEND=lsf`（只接受 `direct|lsf`）
- `XVERIF_LSF_BSUB`：覆盖 bsub 命令。
- `XVERIF_LSF_BKILL`：覆盖 bkill 命令。
- `XVERIF_LSF_SESSION_QUEUE`：session job queue，默认 `interactive`。
- `XVERIF_LSF_SESSION_RESOURCE`：LSF resource string。
- `XVERIF_LOOP_FAKE_LSF=0|1`：只属于 SDK-free wrapper namespace 的显式
  fake LSF 测试。

启用 fake LSF 后，runtime 会在唯一配置入口成对使用
`xverif_loop.lsf.fake_bsub` 与 `xverif_loop.lsf.fake_bkill`；显式设置
`XVERIF_LSF_BSUB` 或 `XVERIF_LSF_BKILL` 时仍以对应设置为准。

布尔值只接受精确的 `0` 或 `1`；timeout 只接受无首尾空白的有限正数。
非法配置直接产生 typed config error。wrapper 不读取
`XVERIF_MCP_FAKE_LSF`，启动、ready、请求或 cleanup 失败也不会切换到其它
backend。

LSF job 从 wrapper server 继承环境。脚本启动 server 时必须显式设置计算节点需要的 `VERDI_HOME`、`LD_LIBRARY_PATH`、license 和 PATH。

## 使用建议

- 每个 wrapper session 对应一个 backend process；LSF 模式下是一个 LSF interactive job。
- 同一 session 请求串行；不同 session 可并行。
- 关闭 session 或 server shutdown 时 wrapper 会尝试清理 subprocess 和 LSF job。
