# xdebug nwave.rc.generate 参考

`nwave.rc.generate` 根据外部 JSON 配置生成 nWave `signal.rc`。xdebug 会使用包含 fsdb 的 `session_id` 校验信号是否存在、marker 时间是否合法，然后写出 rc 文件。

第一版约束：

- 配置文件只支持 JSON。
- 配置里的信号路径使用点分层次，例如 `top.u.sig[3:0]`。
- 生成 rc 时自动转成 nWave slash 路径，例如 `/top/u/sig[3:0]`。
- 支持 `addSignal`、`addSignal -w analog`、`addExprSig`、`addGroup/addSubGroup`、`cursor/marker/userMarker/zoom`。
- group 配置不接受 `expanded`；生成的 `addGroup` / `addSubGroup` 固定不带 `-e`。
- 第一条非注释 RC 语句固定为 `windowTimeUnit 1ns`；配置中不得出现 `window_time_unit`。
- `user_markers[].time` 必须是带单位的时间字符串，生成的 `userMarker` 使用无后缀 ns 数值。
- 不写 `openDirFile` 和 `activeDirFile`。
- 校验失败默认不写 rc；`allow_invalid:true` 才允许带 warning 生成。

## JSON request

```json
{
  "api_version": "xdebug.v1",
  "action": "nwave.rc.generate",
  "target": {
    "session_id": "case_a"
  },
  "args": {
    "config_path": "wave_view.json",
    "output": {
      "path": "signal.rc"
    }
  }
}
```

参数：

| 字段 | 说明 |
| --- | --- |
| `args.config_path` | 必填；rc 配置 JSON 文件路径 |
| `args.output.path` | 必填；生成 rc 文件路径 |

## 配置示例

```json
{
  "file_time_scale": "1ns",
  "signal_spacing": 5,
  "cursor": "120ns",
  "main_marker": "120ns",
  "zoom": {
    "begin": "0ns",
    "end": "500ns"
  },
  "groups": [
    {
      "name": "ClockReset",
      "signals": [
        "top.clk",
        {
          "path": "top.rst_n",
          "radix": "bin",
          "height": 15
        }
      ]
    },
    {
      "name": "Analog",
      "signals": [
        {
          "path": "top.u_adc.sample[11:0]",
          "waveform": "analog",
          "height": 40,
          "analog": {
            "display_style": "pwl",
            "grid_x": true,
            "grid_y": true,
            "unit": "m"
          }
        }
      ]
    },
    {
      "name": "AXI",
      "subgroups": [
        {
          "name": "AW",
          "signals": [
            "top.u_axi.awvalid",
            "top.u_axi.awready",
            {
              "path": "top.u_axi.awaddr[31:0]",
              "radix": "hex",
              "notation": "unsigned",
              "height": 15
            }
          ],
          "expr_signals": [
            {
              "name": "aw_fire",
              "bit_size": 1,
              "notation": "UUU",
              "expr": "$valid & $ready",
              "signals": {
                "valid": "top.u_axi.awvalid",
                "ready": "top.u_axi.awready"
              }
            }
          ]
        }
      ]
    }
  ],
  "user_markers": [
    {
      "name": "reset_done",
      "time": "120ns",
      "color": "ID_YELLOW5",
      "linestyle": "solid"
    }
  ]
}
```

## 生成规则

点分路径转换：

```text
top.clk -> /top/clk
top.u_axi.awaddr[31:0] -> /top/u_axi/awaddr[31:0]
```

输入路径若以 `/` 开头，默认报 `RC_CONFIG_INVALID`，提示使用点分格式。

普通 signal：

```json
{
  "path": "top.u_axi.awaddr[31:0]",
  "radix": "hex",
  "notation": "unsigned",
  "height": 15,
  "color": "ID_GREEN5",
  "line_style": "solid",
  "line_width": 2
}
```

生成：

```rc
addSignal -h 15 -c ID_GREEN5 -ls solid -lw 2 -UNSIGNED -HEX /top/u_axi/awaddr[31:0]
```

analog signal：

```json
{
  "path": "top.u_adc.sample[11:0]",
  "waveform": "analog",
  "height": 40,
  "analog": {
    "display_style": "pwl",
    "grid_x": true,
    "grid_y": true,
    "unit": "m",
    "options": ["-gs2", "10"]
  }
}
```

生成：

```rc
addSignal -w analog -ds pwl -gx -gy -us m -gs2 10 -h 40 /top/u_adc/sample[11:0]
```

expression signal 推荐使用 `$alias` 引用 `signals` map：

```json
{
  "name": "aw_fire",
  "bit_size": 1,
  "notation": "UUU",
  "expr": "$valid & $ready",
  "signals": {
    "valid": "top.u_axi.awvalid",
    "ready": "top.u_axi.awready"
  }
}
```

生成：

```rc
addExprSig -b 1 -n UUU aw_fire "/top/u_axi/awvalid" & "/top/u_axi/awready"

addGroup "AW"
addSignal -h 18 /aw_fire
```

所有 `addExprSig` 会在第一个 group 前统一创建；expression 对应的 `addSignal -h 18` 则位于所属 group 内。

`raw_expr` 只是逃生口，仅当 `allow_raw_expr:true` 时允许；`raw_expr` 不做信号校验。

## 响应读取

成功时重点读：

- `summary.config_path`
- `summary.rc_path`
- `summary.group_count`
- `summary.signal_count`
- `summary.expr_signal_count`
- `summary.marker_count`
- `summary.written`
- `summary.valid`
- `data.validation.signals`
- `data.validation.times`
- `data.rc_preview`

失败错误码：

- `RC_CONFIG_INVALID`
- `RC_VALIDATION_FAILED`
- `RC_WRITE_FAILED`

默认不要把完整 rc 文本粘给用户。需要证明生成内容时使用 `args.output.verbose:true` 或读取生成的 rc 文件摘要；不要传旧 include 参数。
