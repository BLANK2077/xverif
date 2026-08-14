# VCS UCLI 实时调试

本文只记录 xsimdebug 工作流需要的已验证命令。具体语法以当前 `simv` 的 `help <command>` 为准。

本文仅适用于 Synopsys VCS。Xcelium/Xrun 使用 [xrun-tcl.md](xrun-tcl.md)，不要混用命令。

## 先查交互式帮助

在 `ucli%` prompt 直接查询当前 `simv` 实际支持的语法：

```tcl
help
help stop
help get
help show
help run
help next
help stack
```

不同 VCS 版本的选项可能不同。以交互帮助原始输出为准；命令报错或帮助中不存在某个选项时，不要假定它可用。

## 编译与启动

普通 SystemVerilog：

```bash
vcs -full64 -sverilog -debug_access+all -o build/simv tb.sv
./build/simv -ucli -no_save
```

VCS 自带 UVM 1.2 的最小形式：

```bash
vcs -full64 -sverilog -ntb_opts uvm-1.2 \
  -timescale=1ns/1ps -debug_access+all -o build/simv tb.sv
./build/simv -ucli -no_save +UVM_NO_RELNOTES
```

项目已有正式编译入口时使用项目入口，只把上述命令作为参数合同参考。

当前 VCS X-2025.06-SP1 实测行为：

- 不指定 `-k` 也会在 `simv` 启动目录自动生成 `ucli.key`；它只保存依次执行的 UCLI 命令，是回看操作历史的首选；
- 若现有启动命令带有 `-l <logfile>`，该文件保存 UCLI 命令及命令输出，适合查看返回值和错误；本次实测 log 不包含 `ucli%` prompt。

不要为历史回溯专门追加 `-k` 或 `-l`。先查看自动生成的 `ucli.key`；需要返回值、错误或周边输出时，再从现有仿真启动命令确认 `-l` 的实际文件路径：

```bash
sed -n '1,240p' ./ucli.key
tail -n 200 /path/from/existing-l-option
rg -n 'stop |get |run|error|warning' /path/from/existing-l-option
```

key/log 不是 PTY 的逐字节录像，Ctrl-C 控制字节不会作为普通命令写入 key。日志是运行时持续写入的证据；读取到末尾后仍应结合当前 `ucli%` prompt 判断命令是否已经完成。

## 断点

```tcl
stop -line 87 -file my_driver.sv
stop -change tb.watched
stop -posedge tb.valid
stop -negedge tb.reset_n
stop -condition {tb.cycle_count == 3}
```

绑定特定 class object，并附加动态 local 条件：

```tcl
stop -line 27 -file worker.sv -object this -cond {iterations == 2}
```

object 必须先构造。`stop` 列表会显示解析后的 `-object_id {...Class @N}`。

预设 function/task 退出断点：

```tcl
stop -in DebugItem::accumulate -end
stop -in DebugSequence::body -end
```

管理断点：

```tcl
stop
stop -show <id>
stop -disable <id>
stop -enable <id>
stop -delete <id>
stop -delete *
```

`restart` 后断点 ID 可能重新编号；每次重新读取 `stop` 列表。

## 对象和值

```tcl
get tb.item_a.value -radix decimal
get tb.item_a.name
get this.value -radix decimal
get req.addr -radix hexadecimal
get req.tag
```

不要默认读取整个 UVM object。`get req` 或 `show req -value` 可能递归展开大量 UVM 基类状态；优先读取明确成员。

module scope 枚举：

```tcl
show tb -signals -variables -value -radix hexadecimal
search -scope tb -variables '*count*'
```

## 动态 local 与现场

```tcl
listing -active 4
stack
thread
scope
get bias -radix decimal
get sum -radix decimal
get i -radix decimal
get iterations -radix decimal
```

active function/task frame 中可直接读取 local。for/while block 退出后，`i/j/k` 会变为 unknown object；function/task local 在整个 frame 退出前仍可读。

UVM 中 `thread` 会标出当前断点所在的 `CURRENT` thread。只有明确需要查看另一线程时才使用 `thread -attach <tid>`。

## 控制流

```tcl
step
next
next -end
run -line 104 -file my_driver.sv
```

- `step`：执行一个 HDL statement，可以进入 function/task。
- `next`：跨过当前行调用的 function/task。
- `next -end`：完成当前 function/task，停在 caller 的调用语句。
- `run -line`：临时运行到循环出口或指定源码行。

`next -end` 返回 caller 时，调用结果赋给 caller 变量的动作可能尚未完成；再执行一次 `step` 后查询 caller 变量。

`finish` 表示让整个仿真完成，不是退出当前 function。退出当前动态 frame 使用 `next -end`。

常用意图对应关系：循环外有已知源码行时用 `run -line`；结束当前 function/task 用 `next -end`；只跨过当前调用用 `next`。运行前先用 `stop` 核对其它已启用断点，因为它们可能更早命中。

## 主动中断

向正在执行 `run` 的同一个 PTY 写入 Ctrl-C 字节 `0x03`。VCS 应打印当前源码位置并重新给出 `ucli%`。返回 prompt 后用 `listing -active` 和 `stack` 确认现场，再查询值。

`run -keep` 的内置帮助说明 Ctrl-C 会暂停而不是取消该 run 命令；未验证其恢复语义时不要依赖它。

## 按 UVM hierarchy path 调试 component

VCS 没有 Xcelium 的 `$uvm:{...}` 语法，但可从 `uvm_pkg::uvm_top` 沿 `m_children` 直接引用 component。加载随 skill 携带的薄包装：

```tcl
do <xsimdebug-skill-dir>/scripts/uvm_component_break.tcl
```

主接口：

```tcl
::uvmbp::break_at <uvm_path> <file> <line> ?<condition>?
::uvmbp::get_member <uvm_path> <member> ?<radix>?
```

component 必须已经构造。初始 prompt 下先显式完成 time-zero build：

```tcl
run 0
```

给指定 component 设置实例专属源码断点：

```tcl
set result [::uvmbp::break_at \
  uvm_test_top.env.agent_1.driver my_driver.sv 87]
```

附加动态成员条件：

```tcl
set result [::uvmbp::break_at \
  uvm_test_top.env.agent_1.driver my_driver.sv 87 \
  {hit_count == 3}]
```

查询指定 component 的实例成员：

```tcl
set value_result [::uvmbp::get_member \
  uvm_test_top.env.agent_1.driver hit_count decimal]
dict get $value_result value
```

`break_at` 返回 `uvm_path`、`top_index`、`object_expr`、`breakpoint_id` 和 `object_id`。helper 只转换路径和调用原生 `stop -object`/`get`：不自动运行、不做 glob、不在源码断点间循环。

路径转换示例：

```text
uvm_test_top.env.agent_1.driver
→ uvm_pkg::uvm_top.top_levels[0].m_children["env"].m_children["agent_1"].m_children["driver"]
```

若存在多个 UVM top，helper 会检查最多 64 个 `top_levels`，按第一段名称选择正确 index。
