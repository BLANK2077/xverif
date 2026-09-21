# 调用表面选择

先选能力，再选表面与环境。

本文是**路由的唯一权威**：其它 skill 只保留各自特有约束（如 SDK-free 固定 LSF、不提供
direct），不再各自复述整套路由。新增任何入口时只改这里。

## 环境维度

先确认本机 agent 面对的是哪个执行环境，再在同一环境的 surface 集合内选择：

1. **本地 MCP**：MCP client 启动本地 xverif server，`VERDI_HOME`/license 来自本机。
2. **ssh 远端 MCP（`mcp_ssh`）**：本机 MCP client 通过 ssh 使用 EDA 机器上的 xverif server。
   语义、session 与 NPI 都在远端。站点 `VERDI_HOME`/license 变量写在 MCP `env` 里并转发；
   `HOME` 等本机身份变量不转发。两侧都要求 Python >= 3.11，配置自检用
   `python -m mcp_ssh --check`（只打印变量名，不打印取值）。session 状态落在远端本机
   `$HOME/.xdebug`，本机不持有该状态、也不需要共享 `$HOME`；运维细节见 `xverif-admin`。
3. **无 MCP**：按下节顺序选择 CLI 表面。

## 表面顺序

1. 当前 agent 已配置 xverif MCP 时优先 [MCP](../surfaces/mcp.md)。
2. 一次性 shell、脚本和完整 envelope 使用 [CLI](../surfaces/cli.md)。
3. 没有可用 MCP 且必须经 LSF 运行时，使用
   [SDK-free LSF CLI](../surfaces/sdk-free-loop.md)，并读取 `xverif-admin`。
   无 LSF 限制时仍使用原生 CLI。
4. MCP、CLI 和 SDK-free 只改变外层包装，不改变 action 语义。精确字段查询 runtime tool/action schema。
5. 不因调用失败自动切换表面、环境、transport、backend 或数据源：远端 MCP 不可达时报错并由
   用户决定，不静默改走本地 CLI 或 SDK-free。

xdebug 进入任何具体 action 前先完整读取一次 action guide：MCP 调用无参数
`xverif_tools`；原生 CLI 或 SDK-free LSF 调用 `actions` 并设置
`args.output.view="guide"`。三个 surface 读取同一 native guide；之后只对选定 action
查询 schema。关键接口/信号组先生成
schema-valid JSON，通过 `list.load`、`stream.config.load`、`axi.config.load` 或
`apb.config.load` 加载和确认，再执行查询。

CLI resource request 使用 `target.session_id`；MCP resource variant 使用顶层
`session_id`；`requires:none` variant 在两种表面都禁止 session。action 参数只放内层
`args`，具体条件读取 action schema/MCP `session_contract`。
