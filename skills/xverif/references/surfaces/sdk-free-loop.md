# SDK-free LSF CLI Surface

只有在当前 AI 没有可用 xverif MCP，且 xdebug/xcov 必须经 LSF 运行时
才使用该 surface。如果无 LSF 限制，直接使用原生 CLI。

入口：

```bash
tools/xdebug_lsf --json -
tools/xcov_lsf --json -
tools/xverif_lsf_env_capture --dry-run
```

LSF CLI 与原生工具使用同一份 `xdebug.v1` / `xcov.v1` envelope：
session 仍在 `target.session_id` 中选择，action 参数仍放在 `args`。不要构造
`method/params`，不要显式启动 server/client，不要传 `--stdio-loop`。

xdebug action discovery 也直接使用 native 合同：

```json
{"api_version":"xdebug.v1","action":"actions","args":{"output":{"view":"guide"}}}
```

wrapper 不增加 guide flag 或二次格式化，返回与原生 CLI/MCP 共用的 native guide。

`session.open` 的 FSDB/DAIDIR/VDB、`run_manifest`、xcov exclusion/cache 参数和
xdebug ownership token 均按原生 schema 传入，不因 LSF surface 改变 provenance
或资源身份门禁。

协议、readiness、日志、timeout 和 LSF 配置详见 `xverif-admin`。任何失败
都不自动转 MCP、direct backend 或其它 transport。

入口同目录 `xverif_lsf.env.json` 的生成、权限、`bsub -env all` 和计算节点
环境指纹合同也见 `xverif-admin`；该配置不适用于 MCP。
