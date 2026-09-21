# xwaveform

`xwaveform` 把 xdebug `list.export` 导出的波形数据渲染成一张 JPG 和一份 stats JSON，供 agent
做**宏观观察**。

它回答的问题是：

- 这段长窗口里，多个信号的整体形态是什么样（burst、stall 分布、状态阶段）？
- 哪些时间区间值得回到确定性 action 精查？

它明确不做：

- 不做确定性判据。图片是观察材料，不是证据；结论必须回到 `value.at`、`event.find`、
  `window.verify`、`trace.active_driver` 等 action 验证。
- 不直接读 FSDB。输入只有 xdebug 导出的 manifest。
- 不替代 `trace.*` 的因果定位。

## 入口

```bash
tools/xwaveform render --manifest <manifest> --output <image>.jpg [--stats-file <stats>.json]
```

`<manifest>` 来自 xdebug 的 `list.export`：先 `list.load` 建立列表，再 `list.export` 得到
manifest 和逐信号数据。完整流程见
[`skills/xverif/references/workflows/waveform-render.md`](../skills/xverif/references/workflows/waveform-render.md)。

## render

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--manifest` | 必填 | `list.export` 产出的 manifest 路径 |
| `--output` | 必填 | 输出 JPG 路径 |
| `--stats-file` | `<output>.stats.json` | stats JSON 路径 |
| `--width` | `4096` | 图像宽度（像素） |
| `--height-per-signal` | `24` | 每个信号行高 |
| `--cursor-count` | `32` | 时间游标刻度数量，最小按 2 处理 |
| `--quality` | `95` | JPEG 质量 |
| `--json` | 关 | 以 JSON 输出结果，而不是 `image_file=`/`stats_file=` 两行文本 |

输出：`image_file`（JPG）与 `stats_file`（JSON）。两者都由本命令创建。

## 环境要求

- Python >= 3.10（`xwaveform/pyproject.toml` 的 `requires-python`）。wrapper 取 `PATH` 上的
  `python3`，可用 `PYTHON=<path>` 覆盖；未激活仓库 conda 环境且 `python3` 过旧时会报
  `SyntaxError: future feature annotations is not defined`。
- 依赖 `numpy` 与 `Pillow`（`matplotlib` 为可选 `plot` extra，`render` 不需要）。
- 只需要文件系统，不需要 NPI、Verdi、license 或 FSDB。

## 测试

```bash
pytest --xverif-gate fast --xverif-suite xwaveform.unit
```
