# 调用表面选择

先选能力，再选表面。

1. 当前 agent 已配置 xverif MCP 时优先 [MCP](../surfaces/mcp.md)。
2. 一次性 shell、脚本和完整 envelope 使用 [CLI](../surfaces/cli.md)。
3. 没有可用 MCP 且必须经 LSF 运行时，使用
   [SDK-free LSF CLI](../surfaces/sdk-free-loop.md)，并读取 `xverif-admin`。
   无 LSF 限制时仍使用原生 CLI。
4. MCP、CLI 和 SDK-free 只改变外层包装，不改变 action 语义。精确字段查询 runtime tool/action schema。
5. 不因调用失败自动切换表面、transport、backend 或数据源。

xdebug 进入任何具体 action 前先完整读取一次 action guide：MCP 调用无参数
`xverif_tools`；原生 CLI 或 SDK-free LSF 调用 `actions` 并设置
`args.output.view="guide"`。三个 surface 读取同一 native guide；之后只对选定 action
查询 schema。关键接口/信号组先生成
schema-valid JSON，通过 `list.load`、`stream.config.load`、`axi.config.load` 或
`apb.config.load` 加载和确认，再执行查询。

CLI resource request 使用 `target.session_id`；MCP resource variant 使用顶层
`session_id`；`requires:none` variant 在两种表面都禁止 session。action 参数只放内层
`args`，具体条件读取 action schema/MCP `session_contract`。
