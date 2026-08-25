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

存在 SDK-free 环境配置时，实际 submission 增加 `-env all`，并先在计算节点
验证配置变量的 SHA-256 指纹，再 exec native stdio-loop。指纹缺失或不一致返回
`LSF_ENV_MISMATCH`，不进入 session open，也不 fallback。

## 共享环境配置

默认配置为 `xdebug_lsf` / `xcov_lsf` 入口同目录的
`xverif_lsf.env.json`：

```json
{
  "schema_version": "xverif-lsf-env.v1",
  "variables": {
    "VERDI_HOME": "<verdi-root>",
    "PATH": "<lsf-root>/bin:/usr/bin",
    "SNPSLMD_LICENSE_FILE": "27000@license-server"
  }
}
```

推荐从已配置终端生成，避免手抄：

```bash
tools/xverif_lsf_env_capture
tools/xverif_lsf_env_capture --include SITE_EDA_ROOT --force
```

文件必须是当前用户拥有的普通文件、权限严格为 `0600`，不能是 symlink。
配置变量覆盖 wrapper 的 inherited environment。默认捕获 EDA/license/PATH、
`XVERIF_*`、`XDEBUG_*`、`XCOV_*`、`LSF_*` 稳定变量，排除 job 临时变量及名称
含 `TOKEN`、`PASSWORD`、`SECRET`、`COOKIE` 的变量。`--dry-run` 只打印变量名。

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
- `XVERIF_LSF_CLI_CONFIG`，覆盖默认环境配置绝对路径

布尔值只接受精确 `0|1`，timeout 只接受无首尾空白的有限正数。
无效配置、LSF 失败、stdio-loop 失败或 cleanup 失败都不转 direct/MCP/其它
transport。

LSF job 继承 CLI 环境。调用前必须使 `VERDI_HOME`、`LD_LIBRARY_PATH`、
license、PATH 和必需 Python 环境在计算节点可见。

配置内容改变时，空闲 manager 会退出并按新配置重启；若旧 manager 有
live/opening/unresolved session，则返回 `CONFIG_MISMATCH`，不混用环境也不杀
已有 session。以上配置、`-env all` 和指纹校验严格限定在 SDK-free；MCP LSF
仍按 MCP 自己的显式 env 与既有 bsub argv 工作。
