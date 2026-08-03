# xdebug 时间处理 Review 与测试矩阵

## 阶段状态

本阶段已进入实现：xdebug runtime、schema、response examples、xwaveform manifest/render 路径和合同测试已按本文档的 P0/P1 输出合同收敛。时间解析、FSDB tick 转换、formatter、duration formatter、range formatter 已集中到公共 helper，合同测试不再保留时间处理 `xfail`。输出渲染默认单位为 `ns`，只有请求显式传入 `args.render_time_unit` 时才改变输出单位。

任何 NPI、VCS、FSDB、VIP、MCP 实机验证都必须在沙箱外运行。涉及 VIP 环境变量时，按 xring `dv/cfg/Makefile` 口径使用：

- `AXI_REFERENCE_ROOT=<legacy-axi-vip-root>`
- `SVT_VIP_INCDIR=<legacy-axi-vip-root>/include/sverilog`
- `SVT_VIP_SRCDIR=<legacy-axi-vip-root>/src/sverilog/vcs`

## 输出合同

目标合同如下：

- 同一个逻辑时间只输出一份 canonical 时间字符串。
- JSON 与 xout 对同一个逻辑时间必须显示同一份字符串。
- 同一输出块内的同一时间范围必须使用同一单位，例如 `begin`/`end` 不能一个是 `ns`、一个是 `us` 或 `ps`。
- 同一表格内的同一时间列或时长列必须使用同一单位，例如 `duration`、`time`、`match_time` 不能逐行切换单位。
- 禁止 `*_ps` 数字字段，例如 `time_ps`、`begin_ps`、`end_ps`。
- 禁止用 `time_value` 或其他公共数字字段并行表达同一时间。
- 时长、latency、duration 这类非时间点字段也必须显式带单位；不得输出裸数字让用户猜单位。
- 默认无单位时间范围按 ns；如果 action 接受 `0`、`100` 这类无单位范围，含义必须等价于 `0ns`、`100ns`。
- 默认输出渲染单位按 ns；`args.render_time_unit` 只允许 `ns`、`ps`、`us`、`auto`，且只影响输出字符串渲染，不影响解析、查询、排序、过滤、range 计算或 active trace 决策。
- 内部可以用 `npiFsdbTime` 整数 tick 计算，但公共输出不得暴露 raw tick 来弥补字符串精度问题。

canonical 时间字符串必须来自解析后的 FSDB 整数时间，而不是原始请求文本或 double 近似值。默认输出单位为 `ns`，因此 `1ns`、`1000ps`、`0.001us` 这类等价输入在输出层应归一为同一 `ns` 字符串；只有 `args.render_time_unit=auto` 时才使用自动单位策略。

## xring 反馈对齐

参考 `<xring-repo>/dv/doc/feedback/2026-06-27-xdebug-time-unit-issues.md` 的 v28 xout 审阅反馈，本阶段采纳以下约束：

- P0：同一输出块内 `begin`/`end` 强制同单位；反馈中 `signal.stability`、`counter.statistics`、`apb.transfer_window`、`signal.statistics` 暴露了 `ns/us/ps` 混用问题。
- P0：同一表内同列强制同单位；反馈中 `detect_abnormal` 的 `duration` 列逐行混用 `ps` 与 `ns`。
- P0：删除冗余无单位 `_ps` 列；反馈中 `time` + `time_ps`、`match_time` + `match_time_ps` 属于同一逻辑时间双输出。
- P1：AXI analysis latency/avg/min/max 不能输出裸数字；在本合同下应改为带单位字符串，而不是新增 `*_ps` 数字字段。

参考文档中的 P2 建议推广 `time_text` 人类可读字段；本阶段不采纳双字段形态。原因是用户已明确要求同一个时间只输出一份时间，不能再输出一个专门 ps 数字字段或第二份可读字段。可读性应通过唯一 canonical 字符串解决，而不是 `time` + `time_text` 并存。

## 当前实现地图

当前公共输出已经收敛到唯一 canonical 字符串；时间值解析、FSDB tick 转换和格式化入口集中在公共层：

- `xdebug/src/core/npi/time_contract.{h,cpp}`：统一实现时间解析、FSDB tick 转换、render-only time_unit scope、formatter、duration formatter 和 range 同单位 formatter，供 waveform / stream / combined / engine action 共同使用。
- `xdebug/src/waveform/server/service/context.cpp`：只保留 waveform session 语义入口，例如 cursor TimeSpec、cycle offset 和 `json_time_range()`，裸时间解析与格式化委托给 core helper。
- `xdebug/src/waveform/common/time_spec.cpp`：只解析 TimeSpec 文法和 duration 文法，不做 FSDB tick 转换。

## 主要风险

- 已收敛：公共 response examples、schema 和 xdebug/xwaveform 输出路径不再暴露 `time_ps`、`begin_ps`、`end_ps`、`time_value` 这类并行数字时间字段。
- 已收敛：范围输出通过 `format_time_range()` 选择同一单位；无单位范围默认按 ns 解析。
- 已收敛：输出渲染默认按 ns；`args.render_time_unit` 在 action 入口设置 request-scoped render policy，不进入 parser/converter/分析逻辑。
- 已收敛：AXI latency 等时长字段输出带单位字符串，不再新增裸数字或 `_ps` 数字字段。
- 已收敛：engine waveform handlers、stream handlers、active trace 不再保留局部 `strtod` / `npi_fsdb_convert_time_in/out()` 转换代码。
- 已收敛：旧 `waveform/common/time_parser.*` 已移除，不再存在未知单位静默按 ns 的 fallback。
- 剩余关注：运行型 JSON/xout parity 覆盖仍需随真实 FSDB/VIP 回归持续扩展。

## 新增测试矩阵

新增测试文件：`xdebug/tests/contract/test_time_output_contract.py`。

| 测试 | 类型 | 当前预期 | 目的 |
| --- | --- | --- | --- |
| `test_time_handling_review_doc_exists_and_names_output_contract` | contract | pass | 保证本文档存在，并明确输出合同关键词 |
| `test_response_examples_publish_only_one_canonical_time_string` | contract | pass | 扫描 response examples，禁止公共 `*_ps` / `time_value` 数字时间字段 |
| `test_time_parsing_has_single_contract_entrypoint` | contract | pass | 扫描非统一入口里的 `strtod` / `npi_fsdb_convert_time_in/out` 时间转换 |
| `test_time_formatting_and_default_units_are_centralized` | contract | pass | 固定 legacy formatter/default-unit/fallback 风险 |
| `test_render_time_unit_is_render_only_and_defaults_to_ns` | contract | pass | 固定 `args.render_time_unit` 是 render-only，默认输出单位为 ns |

时间处理合同不再保留 `xfail`；新增或迁移 action 时必须继续通过这些门禁。

下一轮测试应继续补充：

- 同块范围单位一致性：扫描/运行 `begin`、`end`、`start_time`、`end_time`，确认同一对象内单位一致。
- 同表同列单位一致性：对 xout 表格中的 `time`、`duration`、`match_time`、`latency` 列做列级单位检查。
- 裸数字时长检查：`latency`、`duration`、`min`、`max`、`avg` 等字段如果表达时间或时长，必须是带单位字符串。

## 实现验收场景

实现阶段至少需要覆盖以下运行型验证：

- point read：统一 `value.at` 的 signal/list/APB/stream/AXI selector 对 `1ns`、`1000ps`、`0.001us` 默认输出同一 `ns` 时间字符串；显式 `args.render_time_unit=auto` 才使用自动单位。
- range query：`signal.changes`、`event.find`、`event.export`、`stream.query`、`stream.export`、`list.export` 不输出 `*_ps` 数字字段。
- range consistency：`signal.stability`、`counter.statistics`、`apb.transfer_window`、`signal.statistics` 的 `begin/end` 输出单位一致，优先保留用户输入范围单位；无单位输入按 ns。
- table consistency：`detect_abnormal`、APB/AXI transaction 表、stream stall/packet 表中同一列单位一致。
- active trace：`trace.active_driver`、`trace.active_driver_chain` 在 `requested_time != active_time` 时只输出 `requested_time` 和 `active_time` 两个语义不同的字符串，不输出 raw tick。
- latency/duration：AXI latency、stall duration、pulse width 等时长字段输出带单位字符串，不输出裸数字或 `_ps` 数字。
- default unit：无单位范围输入按 ns 解释；非法单位和负 absolute time 必须返回结构化错误，不允许 fallback。
- xout parity：对同一 action 的 JSON 和 xout 做对照，确认时间字符串一致，不在 xout 中重新格式化成另一种精度；不同 `args.render_time_unit` 只改变时间字符串，不改变结果集合。

## 后续维护建议

后续新增或迁移 action 时：

- 裸时间解析、tick 转换、formatter 只使用 `core/npi/time_contract`。
- cursor TimeSpec / cycle offset 继续从 waveform session 入口进入，但不得新增局部转换。
- `args.render_time_unit` 只能在 action 入口设置 render scope，不允许被解析、查询、排序、过滤、range 或 active trace 逻辑读取。
- xout 不重新格式化时间，只消费 JSON 同源 canonical string。

## 本轮验证记录

- `make -C xdebug all`：通过，沙箱外运行。
- `make -C xdebug unit-test`：通过，沙箱外运行。
- `make -C xdebug contract-test`：通过。
- `make -C xdebug pytest-contract`：通过，39 passed，无 xfail。
- `python3 -m pytest -c xdebug/tests/pytest.ini -q xdebug/tests/contract/test_time_output_contract.py`：通过，4 passed。
- `make -C xdebug schema-test`：通过，validated 182 schema files / 175 examples。
- `make -C xwaveform test`：通过，5 tests OK。
