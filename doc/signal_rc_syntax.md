# signal.rc 语法整理

本文整理 nWave `signal.rc` 的常用写法。主要依据 `doc/verdi.pdf` 中从第 1897 页开始的 `signal.rc` 章节；`addCounterSig` 语法按用户确认补充。

## 基础格式

用途：

`signal.rc` 用来保存和恢复 nWave 的窗口布局、已打开波形文件、显示范围、cursor/marker、已加载信号和信号属性。

语法：

```rc
Key Value(s)
```

常用规则：

- 以 `;` 开头的行是注释。
- 信号路径通常写完整层次路径，例如 `/top/u_dut/data[7:0]`。
- `$$top/signal_name` 中的 `$$top` 会按当前 active file 的 top scope 自动替换并尝试匹配。
- 字符串名称建议用双引号包起来，尤其是组名、表达式名、路径或包含特殊字符的内容。

示例：

```rc
; comment
addSignal -h 15 -UNSIGNED -HEX /top/u_dut/data[7:0]
```

注意事项：

- `signal.rc` 是 nWave 保存出来的资源文件格式，很多 key 可以由 GUI 自动生成；手写时重点保证命令顺序和信号路径可解析。
- 如果一个命令跨行，实际文件中仍要让 nWave 能按原有格式解析；手写时优先保持一条命令一行。

## 打开文件和视图设置

用途：

恢复 nWave 打开的波形文件、时间单位、视图范围、cursor、marker 和信号间距。

语法：

```rc
openDirFile [-d delimiter] [-s time_offset] [-rf auto_bus_rule_file] path_name file_name
fileTimeScale [file_name] time_scale
signalSpacing pixels
windowTimeUnit time_unit
zoom begin_time end_time
cursor time_pos
marker time_pos
top signal_index
markerPos line_index
curSTATUS ByChange|ByEvent|ByRising|ByFalling|ByValue|ByCmpError
activeDirFile [path_name] file_name
```

常用参数说明：

- `openDirFile`：打开 FSDB/VCD 等波形文件。
- `-d delimiter`：层次分隔符，常见为 `/`。
- `-s time_offset`：文件时间偏移。
- `-rf auto_bus_rule_file`：指定自动 bus grouping 规则文件。
- `fileTimeScale`：设置 active file 的时间尺度，影响整个 waveform pane 的显示尺。
- `signalSpacing`：信号之间的像素间距。
- `windowTimeUnit`：窗口中 zoom、cursor、marker 使用的时间单位。
- `zoom`：当前波形可视时间范围。
- `top`：当前第一条可见信号的索引。
- `markerPos`：marker 在信号 pane 中的行位置。
- `activeDirFile`：多文件打开时指定 active file，避免后续 `addSignal` 找错文件。

示例：

```rc
openDirFile -d / "" "/path/to/wave.fsdb"
fileTimeScale 1ns
signalSpacing 5
windowTimeUnit 1ns
zoom 0.0 1000.0
cursor 100.0
marker 0.0
top 0
markerPos 10
curSTATUS ByValue
activeDirFile "" "/path/to/wave.fsdb"
```

注意事项：

- 如果打开多个波形文件，建议显式写 `activeDirFile`，后续信号解析更稳定。
- `fileTimeScale` 和 `windowTimeUnit` 都是时间相关设置，但前者偏文件/波形尺，后者偏窗口交互单位。

## 添加普通信号：addSignal

用途：

把设计信号加入 nWave 信号列表，并设置高度、颜色、线型、显示进制、数值表示、波形类型等属性。

语法：

```rc
addSignal [options] signal
```

常用参数说明：

- `-h height`：信号显示高度。PDF 示例里常用 `-h 15`，不写时使用默认高度。
- `-c color_id`：信号颜色，例如 `ID_CYAN3`、`ID_RED5`。
- `-ls line_style`：线型，例如 `solid`、`l_dot`。
- `-lw line_width`：线宽。
- `-holdScope`：沿用上一条信号的 scope，后面可以只写 local signal 名。
- `-expanded`：展开信号。
- `-lF`：使用 local format。
- `-i`：反相显示波形。
- `-multiLayer`：展开 Property signal 的 overlap。
- `-hideAttr`：隐藏 classic Transaction/Message/Method signal 的属性。
- `-wildcard`：按 wildcard pattern 添加信号。

示例：

```rc
addSignal -h 15 /top/clk
addSignal -c ID_CYAN3 -h 15 /top/rst_n
addSignal -h 15 -UNSIGNED -HEX /top/u_dut/data[31:0]
addSignal -h 15 -UNSIGNED -HEX -holdScope addr[7:0]
addSignal -ls l_dot -lw 2 -h 15 /top/u_dut/valid
```

注意事项：

- `-holdScope` 依赖上一条信号的 scope，手写或移动顺序时要小心。
- 对 bus 建议显式写显示进制和 signed/unsigned 表示，避免不同环境默认显示不一致。

## 添加 CounterSig：addCounterSig

用途：

基于已有信号生成计数信号，用于统计任意变化、上升沿或下降沿。

语法：

```rc
addCounterSig -Rising signal
addCounterSig -Falling signal
addCounterSig -AnyChange signal
```

常用参数说明：

- `-Rising`：按上升沿计数。
- `-Falling`：按下降沿计数。
- `-AnyChange`：按任意 value change 计数。
- `signal`：被计数的源信号，通常写完整层次路径。

示例：

```rc
addCounterSig -Rising "/top/clk"
addCounterSig -Falling "/top/rst_n"
addCounterSig -AnyChange "/top/u_dut/state[3:0]"
```

注意事项：

- 此语法按用户确认补充；PDF 的 `signal.rc` 表格没有直接列出 `addCounterSig` key。
- nWave GUI 里的 Counter Signal 常见命名前缀包括 `AnyCounter_`、`RisingCounter_`、`FallingCounter_`。
- 对 vector/scalar 普通信号更适合使用；特殊 signal type 是否支持取决于 nWave 实际行为。

## 添加表达式信号：addExprSig

用途：

添加由已有信号组成的逻辑表达式信号。

语法：

```rc
addExprSig [-b bit_size] [-n notation] expr_name expression_string
```

常用参数说明：

- `-b bit_size`：表达式信号的 bit size。
- `-n notation`：表达式中每个元素信号的 notation。
- `expr_name`：新表达式信号名称。
- `expression_string`：表达式内容，信号路径通常用双引号包起来。

示例：

```rc
addExprSig -b 1 NotClock !"/system/i_cpu/i_ALUB/clock"
addExprSig -b 1 Test1 "/system/VMA" & "/system/clock->>300"
addExprSig -b 1 -n UUU ddr0_wr ("/top/rxreqflit[68:62]"=='h1c || "/top/rxreqflit[68:62]"=='h1d)& "/top/rxreqflitv"
```

注意事项：

- 仓库里的 `xdebug/signal.rc` 已有 `addExprSig -b 1 -n UUU ...` 示例，可以作为实际写法参考。
- 表达式中的信号名建议保留双引号；比较值常见写法如 `'h1c`、`'b1`。

## 设置 user marker：userMarker

用途：

在指定时间位置添加用户 marker，便于打开波形后直接定位关键时间点。

语法：

```rc
userMarker time_pos marker_name [color] [linestyle]
```

常用参数说明：

- `time_pos`：marker 时间位置，使用当前窗口时间单位解释。
- `marker_name`：marker 名称。
- `color`：marker 颜色，常见为 `ID_*` 风格颜色名。
- `linestyle`：marker 线型。

示例：

```rc
userMarker 100.0 reset_done ID_RED5 solid
userMarker 2500.0 first_error ID_YELLOW5 l_dot
```

注意事项：

- PDF 示例注释中列出的是 `userMarker time_pos marker_name`；仓库现有 `xdebug/signal.rc` 注释写法包含 `color linestyle`，因此这里按更完整格式整理。
- 配合 `windowTimeUnit`、`zoom`、`cursor` 使用，可以让打开波形后直接落到目标窗口。

## 设置分组：addGroup / addSubGroup

用途：

在信号列表中创建 group 或 sub-group，提升波形列表可读性。

语法：

```rc
addGroup [-e] "group_name"
addSubGroup [-e] "sub_group_name"
```

常用参数说明：

- `addGroup`：添加 group。若信号在不同组中，组名会在 `signal.rc` 中显式保存。
- `addSubGroup`：在目标 group 下添加 sub-group。
- `-e`：表示 group/sub-group 是否展开。

示例：

```rc
addGroup "ClockReset"
addSignal -h 15 /top/clk
addSignal -h 15 /top/rst_n

addGroup -e "AXI"
addSubGroup -e "AW"
addSignal -h 15 -UNSIGNED -HEX /top/u_axi/awaddr[31:0]
addSignal -h 15 /top/u_axi/awvalid
```

注意事项：

- `addSignal` 会按当前 signal list 位置追加；手写文件时通常先写 `addGroup`，再写该组下的 `addSignal`。
- group 展开状态属于显示属性，不影响信号本身。
- 上述 `-e` 仅作为手写 RC 语法参考；`xdebug rc.generate` 不接受配置字段 `expanded`，并固定生成不带 `-e` 的 `addGroup` / `addSubGroup`。

## 设置模拟波形：addSignal -w analog

用途：

把信号按 analog waveform 显示，而不是普通 digital waveform。

语法：

```rc
addSignal -w analog [analog_options] signal
```

常用参数说明：

- `-w analog`：设置 waveform type 为 analog。相对地，普通数字波形可理解为 digital。
- `-ds pwc|pwl|point`：analog drawing style。
  - `pwc`：piecewise constant。
  - `pwl`：piecewise linear。
  - `point`：点状显示。
- `-gx`：显示 analog 垂直 grid。
- `-gy`：显示 analog 水平 grid。
- `-gs2 value`：设置 analog 水平 grid distance。
- `-gl value`：设置 analog 水平 reference line。
- `-rx`：显示 analog 垂直 ruler。
- `-ry`：显示 analog 水平 ruler。
- `-us unit`：设置 analog value unit，例如 `m`。
- `-va ...`：设置 vertical analog value viewable range。

示例：

```rc
addSignal -w analog /top/u_adc/sample[11:0]
addSignal -w analog -ds pwl -gx -gy /top/u_adc/sample[11:0]
addSignal -w analog -ds point -gs2 10 -gl 20 -rx -ry -us m /top/u_sensor/value
addSignal -w analog -va 63.224.0.0.0.0.0.0 0.0.0.0.0.0.0.0 /top/u_sensor/value
```

注意事项：

- PDF 里 `-va` 的例子是 nWave 保存出的参数串，手写时建议优先由 GUI 保存一次后复用。
- `-ds`、grid、ruler、unit、range 都是显示属性，不改变 FSDB/VCD 内的原始值。

## 设置显示进制和数值表示

用途：

控制 bus/vector 信号在 nWave value column 和 waveform 中的显示进制、signed/unsigned 解释方式。

语法：

```rc
addSignal [radix_options] [notation_options] signal
```

常用参数说明：

- 进制选项：
  - `-HEX`：hexadecimal。
  - `-OCT`：octal。
  - `-UDEC`：unsigned decimal。
  - `-BIN`：binary。
  - `-ASC`：ASCII。
  - `-IEEE754`：IEEE754 浮点显示。
- 数值表示选项：
  - `-UNSIGNED`：无符号。
  - `-2COMP`：two's complement。
  - `-1COMP`：one's complement。
  - `-MAGN`：magnitude。

示例：

```rc
addSignal -h 15 -UNSIGNED -HEX /top/u_dut/data[31:0]
addSignal -h 15 -UNSIGNED -UDEC /top/u_dut/count[15:0]
addSignal -h 15 -MAGN -BIN /top/u_dut/mux_sel[1:0]
addSignal -h 15 -IEEE754 /top/u_dut/fp_value[31:0]
```

注意事项：

- 进制和 notation 是可选项；不写时由 nWave 默认设置决定。
- 对协议字段、计数器、地址类信号，建议显式写 `-UNSIGNED -HEX` 或 `-UNSIGNED -UDEC`。

## 运行时 bus：userBusMem / saveRunSig

用途：

把多个已有信号成员组合成一个 runtime bus。

语法：

```rc
userBusMem member_signal
userBusMem member_signal
saveRunSig "bus_name[msb:lsb]"
```

常用参数说明：

- `userBusMem`：指定一个 runtime bus 成员；每个成员一行。
- `saveRunSig`：创建 runtime bus 名称；必须出现在一个或多个 `userBusMem` 之后。

示例：

```rc
userBusMem /system/i_cpu/i_ALUB/PC[3]
userBusMem /system/i_cpu/i_ALUB/PC[2]
userBusMem /system/i_cpu/i_ALUB/PC[1]
saveRunSig "PC_addrSelector[3:1]"
```

注意事项：

- `userBusMem` 和 `saveRunSig` 是顺序相关的，不能把成员写在 `saveRunSig` 后面。
- bus bit 顺序按 `userBusMem` 的排列和保存出的格式理解，手写时要特别核对。

## 重命名信号：addRenameSig

用途：

给已有信号添加一个显示用的新名称。

语法：

```rc
addRenameSig new_name original_name
```

常用参数说明：

- `new_name`：重命名后的信号名。
- `original_name`：原始信号路径。

示例：

```rc
addRenameSig "/system/i_cpu/i_ALUB/ALU_en" "/system/i_cpu/i_ALUB/ALU[0]"
```

注意事项：

- PDF 表格说明为先写 renamed signal，再写 original signal。
- 重命名不改变底层波形数据库，只影响 nWave 显示和 signal list。

## alias / slice 显示映射

用途：

给后续信号应用 alias map 或 slice map，让 value 显示成更易读的字符串或分段格式。

语法：

```rc
aliasmapname map_name
nalias alias value NULL

slicemapname map_name
nslice range display_format

aliasname map_name
addSignal [options] signal
```

常用参数说明：

- `aliasmapname`：定义 alias map，后面跟一个或多个 `nalias`。
- `nalias`：定义 value 到 alias string 的映射。
- `slicemapname`：定义 slice map，后面跟一个或多个 `nslice`。
- `nslice`：定义某个 bit range 的显示格式。
- `aliasname`：把 alias/slice map 应用到下一条 `addSignal`。

示例：

```rc
aliasmapname ALU_en
nalias OK 0 NULL
nalias NO 1 NULL

slicemapname slice_ALU
nslice 7:4 Hexadecimal
nslice 3:2 Binary
nslice 1:0 number2string

aliasname slice_ALU
addSignal -h 15 -UNSIGNED -HEX /system/i_cpu/ALU[7:0]

aliasname ALU_en
addSignal -h 15 -UNSIGNED -HEX -holdScope ALU_en
```

注意事项：

- `aliasname` 只作用于后续信号，常见写法是在目标 `addSignal` 前一行设置。
- alias/slice map 适合状态机、枚举值、字段拆分等显示增强场景。

## include 和 waveDefine

用途：

拆分多个 rc 文件并用宏复用 scope，让同一份 signal list 可以在不同层次下加载。

语法：

```rc
include rc_file
waveDefine macro_name token_string
addSignal -h 15 /${macro_name}/signal
```

常用参数说明：

- `include`：包含其他资源文件。恢复 top resource file 时，也会恢复被包含的 sub-resource files。
- `waveDefine`：定义宏名和替换文本。
- `${macro_name}`：在后续 signal path 中引用宏。

示例：

```rc
; rc_file_1
waveDefine TOP tb/top
waveDefine ALUB i_cpu/i_ALUB
include rc_file_2

; rc_file_2
addSignal -h 15 /${TOP}/${ALUB}/clock
addSignal -h 15 -UNSIGNED -HEX /${TOP}/${ALUB}/data[7:0]
```

注意事项：

- `waveDefine` 宏名大小写敏感；`${TOP}` 和 `${top}` 不是同一个宏。
- 宏替换适合把模块级 signal list 搬到 testbench 或 wrapper 层复用。

## 一个最小完整示例

```rc
; File list
openDirFile -d / "" "/path/to/wave.fsdb"
activeDirFile "" "/path/to/wave.fsdb"

; Time and view (xdebug rc.generate fixes this as the first executable statement)
windowTimeUnit 1ns
fileTimeScale 1ns
signalSpacing 5
zoom 0.0 1000.0
cursor 100.0
marker 0.0
userMarker 100.0 reset_release ID_RED5 solid
top 0

; Expressions are created before groups, then attached inside their group
addExprSig -b 1 fire "/top/u_dut/valid" & "/top/u_dut/ready"

; Groups and signals
addGroup "ClockReset"
addSignal -h 15 /top/clk
addSignal -h 15 /top/rst_n
addCounterSig -Rising "/top/clk"

addGroup "Bus"
addSignal -h 15 -UNSIGNED -HEX /top/u_dut/addr[31:0]
addSignal -h 15 -UNSIGNED -UDEC /top/u_dut/count[15:0]

addGroup "Expr"
addSignal -h 18 /fire

addGroup "Analog"
addSignal -w analog -ds pwl -gx -gy /top/u_adc/sample[11:0]
```
