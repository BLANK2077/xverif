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

## 远端 ssh backend

`python -m mcp_ssh` 是纯转发层，不是新的 backend：它对 MCP client 呈现远端 xverif server 的
工具面，并把 `tools/list` schema 与 `tools/call` 结果原样透传。排查顺序按下面走：

- 先 `python -m mcp_ssh --check`。它打印 host、远端仓库路径、远端解释器、转发变量的**名称**
  列表、变量个数与编码长度、上游工具数；**不打印任何变量取值**。退出码 2 表示
  `XVERIF_MCP_SSH_HOST`/`XVERIF_MCP_SSH_REMOTE_ROOT` 缺失或非法。
- 握手能成功但首个 `tools/list` 返回 `-32603` 错误，说明远端进程没有起来。错误文本里保留
  了上游原因；工具调用失败则以 `isError=true` 的内容返回，不会伪装成成功。
- 远端要求 Python >= 3.11、远端仓库路径存在、`xverif_mcp/src` 可导入；`XVERIF_MCP_SSH_REMOTE_PYTHON`
  默认 `python3`，远端 shell 非交互，不会加载 `~/.bashrc`。
- 站点的 `VERDI_HOME`、license 变量必须写在 MCP client 的 `env` 里，它们会被转发；凭据形状
  的名字（含 `TOKEN`/`PASSWORD`/`SECRET`/`COOKIE`）永不转发，描述本机的名字（`HOME`、`USER`、
  `SSH_AUTH_SOCK`）也不转发——远端进程保留自己的家目录。
- 需要核对远端实际收到的环境时，在远端经同一条链路跑 `python -m mcp_ssh.report <remote-root>`。
- session 状态落在**远端本机** `$HOME/.xdebug`，**不需要共享 `$HOME`**：会话完全在远端进程内，
  客户端不接触这些文件。跨机器共享 `~/.xdebug` 只对 xdebug 的 cluster file transport 有意义，
  那是另一套机制。
- 本程序只接受私钥**路径**（`XVERIF_MCP_SSH_IDENTITY`），不读取内容、不生成、不复制密钥；
  仓库和测试都不允许出现密钥材料，`.gitignore` 已显式拦截。
