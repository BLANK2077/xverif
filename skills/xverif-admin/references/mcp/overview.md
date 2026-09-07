# xverif MCP 总览

`tools/xverif-mcp` 是基于 FastMCP 的统一入口。交互式 AI 工具调用优先使用 MCP；
只有没有 MCP 且必须经 LSF 时，才使用 `xdebug_lsf` / `xcov_lsf`。

## 工具组

- xdebug：stateful backend，`xverif_debug_*`。
- xcov：stateful backend，`xverif_cov_*`。
- xbit/xentry/xloc：stateless in-process public API adapter。
- xsva：stateless public CLI adapter，保留 canonical analysis metadata。
- common：`xverif_tools`、`xverif_tool_help`、`xverif_batch`。

全部工具组、session 生命周期、配置/list/cursor、coverage exclusion 和文件写入始终可用。
选择 xdebug action 前调用 `xverif_tools`，工具详情使用 `xverif_tool_help`。
通用 `xverif_output_path` 相对 MCP 进程工作目录解析，也接受绝对路径；父目录需已存在。
xdebug/xcov action 参数原样转发，输出路径遵守 native 合同；xcov 绝对导出仍需显式
`allow_absolute_path` 和 `XVERIF_XCOV_EXPORT_ROOTS`，MCP 不自动注入许可。

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

`xverif_batch` 始终可用。batch 行里的 tool 参数需要嵌套在 `args` 里；每行 `args` 必须是 object。输入先冻结并受 16 MiB/10,000 条默认 hard limit 约束，输出受 64 MiB 默认 hard limit 约束；三项可通过 `XVERIF_MCP_BATCH_MAX_*` 严格正整数环境变量调整。输入输出同 inode（含 symlink/hardlink）会被拒绝，输出必须不存在并以同目录 staging no-clobber 发布。MCP 自身文件输出不限制根目录；写入失败不得把原 action 成功当作调用成功。
