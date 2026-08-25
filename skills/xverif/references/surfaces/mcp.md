# MCP Surface

- xdebug resource action：`xverif_debug_session_open(name, fsdb=None, daidir=None, run_manifest=None)` → `xverif_debug_query(action, session_id, args, limits, output_format)` → `xverif_debug_session_close`。
- xdebug `requires:none` variant：直接调用 `xverif_debug_query(action, args, limits, output_format)`，禁止传 `session_id`。
- xcov：`xverif_cov_session_open(name, vdb, run_manifest=None)` → `xverif_cov_query(session_id, action, args, output_format)` → `xverif_cov_session_close(session_id, confirm_discard_reasons=False)`。coverage limits 与 export output 只放 action 内层 `args`。dirty exclusion reason 会拒绝普通 close 并保留 session；先持久化 CSV，或明确确认丢弃。
- action 参数只放内层 `args`；不传原生 `api_version/target/output` envelope。
- 任何 xdebug 任务先调用一次无参数 `xverif_tools`，完整读取它返回的全部 action
  名称和精简 purpose。该 tool 原样返回 native `actions` guide，每行仅
  `name: description_en`，不含 status/`use_when`，并受 10,000 UTF-8 字节硬门禁约束。
  不要按 category/keyword 反复调用；该 tool 故意不提供过滤参数。
- 选定 action 后调用 `xverif_debug_get_schema` 获取精确参数和使用指导。对关键普通信号、Stream、AXI、
  APB 接口，先按 schema 生成 JSON，分别经 `list.load`、
  `stream.config.load`、`axi.config.load`、`apb.config.load` 加载，再用
  list/show/validate、config.list/get、describe 或 query 确认。
- `xverif_batch` 只用于异构 MCP tool/action 的严格串行编排。多个信号或时间点
  使用 `list.load` + `value.at(list="<name>", times=[...])`，不要用 batch 重复点读。
- MCP/AI 查询默认使用 token-efficient XOUT。adapter 原样传递 native XOUT，不反
  解析、不重编码、不添加 `XOUT_BEGIN/XOUT_END`；稳定字段编程、schema 校验、
  结构化持久化、读取未投影字段或用户明确要求时才使用 JSON。

## Schema discovery

`xverif_debug_get_schema(action, kind="request", view="mcp")` 默认返回可直接用于 MCP
query 的投影：中英文 action 总览 `purpose_en`/`purpose_zh`、作为唯一字段合同的
`args_schema`/`limits_schema`、业务 `constraints`、`minimal_call`、无效调用 examples、
`session_contract`、适用/禁用边界与替代 action。`session_contract` 直接投影
canonical resource variant：`required` 必须传 managed session，`forbidden` 必须
省略，`conditional` 按 args 分支选择。不要把返回的 schema 再套入
`xverif_debug_query.args`，也不需要为 primary response fields 再查询一次 schema。

`expr.normalize` 的 `expr` 分支是 `requires:none`，禁止 session；`signal` 分支要求
design session。两者同时提供或都不提供都会失败。
expr-only 成功响应的 `summary.source` 固定为
`deterministic_syntax_parser`，`summary.confidence` 固定为
`syntax_validated`；这表示语法已经由确定性 parser 验证，
不代表已经结合 design resource 证明信号或赋值语义。

- `view="mcp"`：默认；用于构造 query tool 的内层 args/limits。
- `kind="response", view="response"`：查看 response schema。普通 action 省略
  `response_detail` 时返回完整 schema。`batch` 默认返回 token-efficient
  `response_detail="summary"`，只包含 outer envelope、selector 与完整性关系；
  用 `response_detail="child", child_action="<action>"` 精确读取一个 non-batch
  child response schema；只有确实需要完整 recursive union 时才显式使用
  `response_detail="full"`。不得把 summary 当作 child payload 的完整合同。
- session/transport/LSF/timeout 排障转 `xverif-admin`，不自动 reopen 或 fallback。
- `run_manifest` 可选；xdebug 提供时使用已发布的 `xdebug.run-manifest.v1`；xcov 使用
  `xcov.run-manifest.v2`，要求 `sha256-entry-tree-v2`、资源 kind、regular-file 总字节数和
  file/directory/symlink 计数。资源路径相对 manifest 文件，校验不匹配会返回
  `RESOURCE_PROVENANCE_MISMATCH`，不会启动后端；xcov 不接受旧 v1。
- xdebug 完成仿真后可用 `xdebug/tools/publish_run_manifest.py --fsdb waves.fsdb
  --output run-manifest.json` 原子发布 manifest；MCP session 元数据中的
  `resource_identity` 同时报告路径摘要、stat 快照和声明的 manifest 摘要，不能把路径摘要当作内容摘要。
