# SDK-free xdebug/xcov LSF

当没有可用 MCP 且必须经 LSF 时，直接使用原生兼容入口：

```bash
tools/xdebug_lsf --json request.json
tools/xcov_lsf --json request.json
```

入口透明启动：

```text
bsub -I tools/xdebug --stdio-loop
bsub -I tools/xcov --stdio-loop
```

## 环境变量

- `XVERIF_LSF_BSUB`、`XVERIF_LSF_BKILL`
- `XVERIF_LSF_SESSION_QUEUE`，默认 `interactive`
- `XVERIF_LSF_SESSION_RESOURCE`
- `XVERIF_LSF_CLI_SOCKET`、`XVERIF_LSF_CLI_LOG_DIR`
- `XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC`
- `XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC`
- `XVERIF_LSF_CLI_CLOSE_TIMEOUT_SEC`
- `XVERIF_LSF_CLI_BKILL_TIMEOUT_SEC`
- `XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC`，默认 5 秒
- `XVERIF_LSF_CLI_FAKE_LSF=0|1`，仅用于测试

布尔值只接受精确 `0|1`，timeout 只接受无首尾空白的有限正数。
无效配置、LSF 失败、stdio-loop 失败或 cleanup 失败都不转 direct/MCP/其它
transport。

LSF job 继承 CLI 环境。调用前必须使 `VERDI_HOME`、`LD_LIBRARY_PATH`、
license、PATH 和必需 Python 环境在计算节点可见。
