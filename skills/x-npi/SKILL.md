---
name: x-npi
description: 当 AI agent 需要使用 Synopsys pynpi 编写 Python 脚本，进行批量 FSDB 波形统计、值扫描、APB/AXI/valid-ready stream 协议分析、VCS/Verdi coverage database 查询，或静态设计 driver/load 查询时使用。离线大规模分析脚本和报告优先使用本 skill；xdebug 风格的实时 active-driver 根因定位或 PVC active-driver 检查不要使用本 skill。
---

# x-npi

> **License 环境优先规则：**如果当前 EDA/NPI 环境存在 license 约束，优先尝试使用
> `bsub` 提交到 LSF 队列运行。提交失败必须明确报告，不得静默回退到本机执行。

x-npi 用来教 AI agent 编写可复用的 Python `pynpi` 批量分析脚本。交互式会话查询和 active-driver 因果追踪继续使用 xdebug；当任务需要扫描大量信号、时间窗口、事务、coverage database 或设计 handle 时，使用 x-npi。

## 任务路由

| 任务 | 优先阅读 |
| --- | --- |
| 配置 `VERDI_HOME`、导入 `pynpi`、管理 `npisys.init/end` | [references/pynpi-runtime.md](references/pynpi-runtime.md) |
| 读取 FSDB 值、变化、统计信息或时钟沿采样 | [references/waveform-patterns.md](references/waveform-patterns.md) |
| 提取 APB、AXI 或 valid-ready stream 摘要 | [references/protocol-patterns.md](references/protocol-patterns.md) |
| 导出 VCS/Verdi coverage summary、coverage detail 或管理原生 exclusion | [references/coverage-patterns.md](references/coverage-patterns.md) |
| 从 daidir/design DB 查询静态 driver/load 事实 | [references/design-trace-patterns.md](references/design-trace-patterns.md) |

## 可复用 helper

可 import 的 helper 包位于 `scripts/x_npi/`。

```python
from x_npi.runtime import json_stdout_quarantine, pynpi_lifecycle
from x_npi.wave import open_fsdb, iter_edge_samples
from x_npi.protocol import axi_summary
from x_npi.urg import export_summary, parse_summary
from x_npi.coverage import load_exclusion_files, open_covdb, compile_csv_to_el
from x_npi.container import plan_container_records, write_csv_set
```

公共 helper 按模块分组：

- `runtime`：`verdi_home`、`configure_pynpi`、`json_stdout_quarantine`、`pynpi_lifecycle`。
- `wave`：`open_fsdb`、`close_fsdb`、`time_in`、`preflight_signals`、`sample_values`、`iter_signal_changes`、`iter_edge_samples`、`clock_edges`、`edge_samples`、`value_statistics`。
- `protocol`：`apb_transactions`、`apb_summary`、`axi_transactions`、`axi_summary`、`stream_summary`。
- `urg`：`urg_path`、`export_summary`、`parse_summary`；coverage read/export 的默认且推荐入口，
  固定 `-full64 -xml_verbose -format text -show summary`，不加载 pynpi。
- `coverage`：只负责 exclusion 的 `open_covdb`、`close_covdb`、`test_names`、
  `merged_test_handle`、`load_exclusion_files`、`set_report_time_excluded`、
  `save_exclusion_file`、`unload_exclusions`、`compile_csv_to_el`。不再提供 NPI coverage read。
- `exclusion_csv`：`parse_document`、`parse_directory`、`validate_directory`、
  `format_document`、`format_directory`；reason 只保存在 CSV sidecar。
- `design`：`handle_name`、`statement_row`、`trace_driver`、`trace_load`。
- `jsonio`：`ok`、`error`、`print_json`、`split_limited`。

运行示例时，可以把 skill 的 `scripts` 目录加入 `PYTHONPATH`，也可以直接执行 `scripts/examples/` 下的文件。

## 决策规则

- 针对已经打开的 xdebug 会话做一次性 AI debug 时，使用 xdebug。
- 需要批量 FSDB 扫描、事务提取、coverage export、值分布统计或报告生成时，使用本 skill 编写 Python 脚本。coverage 读取优先 URG；不要把 x-npi 的名字误解为所有 coverage 工作都必须走 pynpi。
- 不确定 pynpi API、类名、枚举或调用约定时，AI 可以直接查看 `$VERDI_HOME/share/NPI/python/pynpi/` 下当前安装版本的 Python 包和实现；例如 waveform 的时间归并遍历可查 `pynpi/waveform.py` 中的 `TimeBasedHandle`。先核对当前安装 API，再写脚本，不凭记忆猜接口。这是正式 API 查证入口，不是失败后的 fallback。
- 做波形协议分析、事务统计、窗口验证或跨信号相关性判断时，必须基于同一个 `clock` 的 edge 采样。公开配置只接受 `edge=negedge|posedge`；`posedge` 还必须显式指定 `sample_point=before|after`，`negedge` 禁止 `sample_point`。默认使用 `negedge`。
- 大窗口优先使用流式 `iter_edge_samples`，让 Python 状态机边读边聚合；只有确实需要完整采样行时才使用会物化列表的 `edge_samples`。
- AI 可直接用 Python 对结构化结果做过滤、分组、关联、统计、临时索引或任务内缓存，具有很高的自定义自由度。优先一次扫描生成任务需要的聚合，不默认建设持久化缓存数据库，也不为通用示例增加固定业务过滤器。
- 需要 active-driver、active-driver-chain、`activeTime`、PVC active check、force/root-cause 分类，或在某个症状时间点做接口因果追踪时，改用 xdebug/C++ NPI。当前 Python `pynpi` 不暴露这些 active trace 所需 API。
- Python NPI coverage API 没有 bulk summary，必须从 instance/metric/object/bin 逐层遍历；设计越大，
  启动和遍历成本越高，而且容易把 parent aggregate 与 child bin 重复计分。普通 summary、层次、
  test list、code/assert/functional typed 统计和 detail export 一律优先 URG；NPI 在 coverage
  部分只用于 exclusion target 的必要遍历以及 EL load/set/save/unload。
- `compile_csv_to_el(db, test, csv_dir, output_dir)` 内建 indexed resolver：code/assertion 对 CSV 中
  唯一 exact scope 使用 `handle_by_name`，不遍历 instance hierarchy；functional 预检按请求的
  group/point/cross 前缀剪枝，apply 用短生命周期 locator trie 重放，不做第二次全树扫描。零/多匹配
  和两遍间身份变化均失败并回滚；不缓存 native handle、不建立全 bin 索引、不接受外接 resolver。
- `container_exclude.py` 是 x-npi 独立容器入口：从既有 fixed URG report 解析，或使用固定 full64
  URG 命令新生成 report；递归 instance 只展开 XML 真实节点，然后生成 exact container CSV 并原子
  发布四份 EL。NPI 在该流程只用于排除定位和 EL 操作。
- URG summary 百分比使用其 typed subtree ratio；root scope 从 XML 的 instance parent 关系推导，
  不假设名称为 `top`。单 metric pct 为 `covered/coverable`；多 root 时先按 metric 合并 root
  分子/分母，多 metric root/scope SCORE 再对可评分的非 null metric pct 做算术平均。无
  coverable object 的 `0/0` 保留 null 且不参与平均；全部不可评分时 SCORE 为 null。
  `count` 不是 coverage pct。
- 不支持从固定 summary 伪造 per-test attribution、source evidence 或 functional bin；需要 gap
  时使用受限 URG text detail，不回退 NPI 全树扫描。
- 脚本 stdout 必须只有一个 JSON document。使用 `json_stdout_quarantine` 隔离 NPI native banner；summary 默认输出到 stdout，`transactions|timeline|full` 必须配合 `--output` 写文件，stdout 只返回摘要和文件位置。协议工具不提供 `line_limit`。
- 时间字段保持 FSDB integer tick，并在 `meta.scale_unit` 返回数据库 time scale；不要先转换成 float 时间再做配对或排序。
- 当环境需要 Synopsys license 访问时，真实 `pynpi`/FSDB/daidir 验证应在受限沙箱外运行。

## 示例入口

- `scripts/examples/wave_stats.py`
- `scripts/examples/apb_summary.py`
- `scripts/examples/axi_summary.py`
- `scripts/examples/stream_summary.py`
- `scripts/examples/coverage_summary.py`
- `scripts/examples/csv_to_el.py`
- `scripts/examples/container_exclude.py`
- `scripts/examples/trace_driver_summary.py`
