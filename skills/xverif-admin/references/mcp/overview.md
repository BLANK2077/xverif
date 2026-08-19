# xverif MCP 总览

`tools/xverif-mcp` 是基于 FastMCP 的统一入口。交互式 AI 工具调用优先使用 MCP；
只有没有 MCP 且必须经 LSF 时，才使用 `xdebug_lsf` / `xcov_lsf`。

## 工具组

- xdebug：stateful backend，`xverif_debug_*`。
- xcov：stateful backend，`xverif_cov_*`。
- xbit/xentry/xloc：stateless in-process public API adapter。
- xsva：stateless public CLI adapter，保留 canonical analysis metadata。
- common：`xverif_tools`、`xverif_tool_help`、`xverif_batch`。

如果不确定哪些工具暴露，先调用 `xverif_tools`。`XVERIF_MCP_ENABLE_*` 可能关闭部分工具组。

`XVERIF_MCP_ENABLE_MUTATION` 默认开启（`1`），open/close/kill/gc、配置/list/cursor、
coverage exclusion 等状态变更默认可用；需要只读部署时显式设为 `0`。
`XVERIF_MCP_ENABLE_ARTIFACT_WRITE` 默认关闭（`0`）。需要 batch、export artifact 或
`xverif_output_path` 时还要开启 artifact write，并把既有目录配置到
`XVERIF_MCP_ARTIFACT_ROOT`；相对和绝对输出都不得逃逸该根目录。按当前任务所需的最小能力授权。

连通性检查使用 `xverif_ping`。它不访问 backend、session、NPI 或 license，适合确认 MCP server 本身是否可调用。

direct backend 使用 NPI 时，MCP server 的显式 `env` 必须包含当前站点所需的
`VERDI_HOME` 和 license 变量；不要假设 Codex/IDE 会把交互 shell 的环境自动传入。
本地同机 xdebug transport 显式使用 `XDEBUG_TRANSPORT=uds`。

## xdebug 入口

- xdebug MCP 不暴露原生 envelope raw request。
- 常规 xdebug 调试使用 `xverif_debug_session_open` + `xverif_debug_query`。
- action 发现和 schema 查询使用 `xverif_debug_list_actions` / `xverif_debug_get_schema`。
- 需要完整原生 `xdebug.v1` envelope、验证 CLI 行为或做一次性脚本时，改用 `xverif`。
- xcov MCP 也不暴露原生 envelope raw request；完整 `xcov.v1` envelope 同样改用 `xverif`。
- xdebug 参数错误时，MCP 默认 xout 会显示 backend 的 `invalid_arg`、`did_you_mean`、`required_any_of` 和 `correct_example`。优先按这些字段修正请求；不要因为第一次参数写错就切换到其它 transport。

## batch

`xverif_batch` 需要 artifact write 权限；其中生命周期或 exclusion 调用还需要 mutation 权限。batch 行里的 tool 参数需要嵌套在 `args` 里；每行 `args` 必须是 object。输入先冻结并受 16 MiB/10,000 条默认 hard limit 约束，输出受 64 MiB 默认 hard limit 约束；三项可通过 `XVERIF_MCP_BATCH_MAX_*` 严格正整数环境变量调整。输入输出同 inode（含 symlink/hardlink）会被拒绝，输出必须不存在并以同目录 staging no-clobber 发布。所有 MCP tool 的 `xverif_output_path` 都受 artifact root containment 约束；写入失败不得把原 action 成功当作调用成功。
