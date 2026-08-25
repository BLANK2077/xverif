---
name: xverif
description: >
  用于芯片验证中的确定性事实查询和计算：daidir/FSDB debug、coverage、
  SystemVerilog bit 计算、entry 解码、日志位置恢复、SVA 解释和波形渲染。
  先按任务选择能力，再按环境选择 MCP 或 CLI。批量 pynpi 分析用 x-npi，
  运维用 xverif-admin，持续知识用 xwiki。
---

# xverif

这是唯一通用隐式入口。先判断用户要解决的问题，不要先猜 CLI/MCP。

> **Coverage exclusion 必须先持久化再关闭 session。** `exclude.add` 的 reason 只存在于
> 当前 xcov session；关闭 session 会永久丢失尚未导出的 reason。完成 coverage 分析后，
> 必须先执行 `exclude.csv.export`，再执行 `export.exclude`，确认两类文件均成功后才能关闭。
> assert/function exclusion 先读取结构化 XOUT/JSON 的 `Axxxx`/`FCxxxx` gap；禁止使用已删除的
> exclusion selector 参数。关闭或丢失 session 后，尚未导出的 reason 无法恢复。
> Instance/covergroup/coverpoint/cross 容器使用专用 `exclude.instance.*` 与
> `exclude.functional.*` action；不支持 module selector。递归 instance 只依据 URG XML 真实层次，
> remove 只依据 session 已记录的 exact ownership。

## 任务路由

| 用户意图 | 能力参考 |
| --- | --- |
| 信号、scope、driver/load、波形、协议、active driver、窗口证明 | [xdebug](references/capabilities/xdebug.md) |
| VDB coverage、hole、scope、源码 evidence | [xcov](references/xcov.md) |
| literal、slice、mask、表达式 | [xbit](references/xbit.md) |
| entry/descriptor/header fields | [xentry](references/xentry.md) |
| 恢复 `L_XXXXXXXX` 源码位置 | [xloc](references/xloc.md) |
| SVA temporal semantics | [xsva](references/xsva.md) |
| `list.export` 后渲染 JPG/stats | [xwaveform workflow](references/workflows/waveform-render.md) |
| 全量 xdebug action 的用途和合同入口 | [全量 action 索引](references/generated/xdebug-actions.md) |
| MCP/CLI 请求包装 | [surface 选择](references/core/execution-model.md) |
| XOUT/JSON 输出选择 | [token-first 输出策略](references/core/output-formats.md) |
| 统一证据字段和完整性判定 | [证据合同](references/core/evidence-contract.md) |
| 同一 canonical example 的三种请求包装 | [生成的 surface 示例](references/generated/surface-examples.md) |

批量 FSDB 扫描或自定义报告使用 `x-npi`；coverage 读取即使通过 x-npi 编写离线脚本也应使用
其固定 full64 URG helper，不能启动 NPI 全树遍历。x-npi 的 coverage NPI 仅用于 exclusion target
必要遍历和 EL load/set/save/unload。安装、LSF、transport、timeout、session 运维使用
`xverif-admin`；项目长期知识使用 `xwiki`。

## 标准流程

1. 明确问题和必须保留的证据。
2. 任何 xdebug 任务先读取一次完整 action guide：MCP 调用无参数
   `xverif_tools`；原生 CLI 或 SDK-free LSF 提交 `actions` request，并设置
   `args.output.view="guide"`。guide 每行只有 action 名和精简 purpose，不含 status；
   不能按记忆、前缀或局部搜索猜 action。随后查询选定 action schema 获取精确参数
   和使用指导，并读取对应 capability/workflow；离线全量索引用于复核。
3. 优先 MCP；原生 envelope、shell 或一次性脚本使用 CLI。AI/MCP/交互查询默认
   使用 token-efficient XOUT；只有精确字段编程、schema 校验、结构化持久化或
   用户明确要求时才请求 JSON。具体包装见 surface 与输出格式 reference。
4. 对选定 action 调用 action-specific schema，不猜字段；MCP 同时遵守
   `session_contract`，resource variant 必须有 session，`requires:none` variant 禁止
   session。schema 返回 `skill_guidance` 时必须读取其中指定的本 skill reference。
5. 对关键接口或一组关键信号，先按 schema 生成 JSON config，并通过
   `list.load`、`stream.config.load`、`axi.config.load` 或 `apb.config.load`
   加载，再用对应 list/get/show/validate/describe 确认解析结果。
6. config load 成功后读取响应中的 `recommended_actions`，第一项应为
   `value.at`；它接受 `signal`、`list`、`apb`、`stream`、`axi` 中恰好一个
   selector，以及 `time` 或有序且不重复的 `times`。多个时间点一次提交。
7. 先执行最小受限查询，再根据证据扩展。
8. 输出结论、signal/path、time/range、value、file:line、action/tool、error/finding；
   同时报告 canonical 完整性字段并保留 action-specific status 与 unknowns。
9. xcov exclusion 任务严格遵循“可选加载 exclusion、查询摘要、导出具体缺口、补激励或带
   reason 排除、复查、先导出 CSV 再导出 EL、最后关闭 session”的流程；详见 xcov reference。

## 禁止事项

- 不把 MCP 参数壳写进原生 envelope，也不把 CLI target/envelope 写进 MCP query。
- 不因失败自动切换 surface、transport、backend、数据源或测试层级。
- `scan_complete=false`、`analysis_complete=false` 或
  `response_truncated=true` 时不作全量结论。
- 不把波形图片当唯一证据；图片用于宏观观察，结论回到确定性 action 验证。
- 不为多个信号或多个时间点反复调用 `xverif_batch`。`xverif_batch` 只用于彼此
  不同的 MCP tool/action 组成的严格串行工作流；多个时间点统一使用一次 `value.at`。
- 未授权时不修改 xwiki、不创建项目 config、不执行 EDA 命令。
