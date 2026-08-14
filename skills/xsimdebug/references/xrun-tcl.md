# Xcelium/Xrun Tcl 实时调试

本文适用于已实测的 Xcelium 24.09。以当前安装版本的 `help <command>` 为准，不把 VCS UCLI 命令翻译后直接套用。

## 先查交互式帮助

在 `xcelium>` prompt 直接查询当前安装版本的命令和选项：

```tcl
help
help stop
help value
help describe
help run
help stack
help uvm_component
help uvm_phase
```

以交互帮助原始输出为准；命令报错或帮助中不存在某个选项时，不要假定它可用。

## 启动

普通 SystemVerilog：

```bash
xrun -64bit -sv -linedebug -access +rwc -enable_tpe \
  -input /dev/null -top tb tb.sv
```

UVM：

```bash
xrun -64bit -sv -uvm -uvmhome CDNS-1.2 \
  -linedebug -uvmlinedebug -access +rwc -enable_tpe \
  -input /dev/null -top tb tb.sv
```

- `-linedebug` 允许源码行断点。
- `-access +rwc` 保留对象读写和连接访问。
- `-uvm` 加载 UVM Tcl 接口；`-uvmlinedebug` 保留 UVM 调试信息。
- `-enable_tpe` 让 class 内行断点条件在运行时求值。
- `-input /dev/null` 让终端先停在 `xcelium>` prompt；否则 xrun 会直接执行默认 `run`。

项目有正式构建入口时沿用项目入口，只补齐缺失的调试参数。复用已有 snapshot 可使用 `xrun -R -input /dev/null`。

当前 Xcelium 24.09 实测行为：

- 不指定 `-k` 也会在运行目录自动生成 `xrun.key`；它只保存依次执行的 Tcl 命令，是回看操作历史的首选；
- Xrun 默认产生 `xrun.log`；若现有启动命令带有 `-l <logfile>`，则使用该路径。log 保存带 `xcelium>` prompt 的 Tcl 命令及命令输出，适合查看返回值和错误。

不要为历史回溯专门追加 `-k` 或 `-l`。先查看自动生成的 `xrun.key`；需要返回值、错误或周边输出时，再查看现有 `-l` 路径或默认 `xrun.log`：

```bash
sed -n '1,240p' ./xrun.key
tail -n 200 ./xrun.log
rg -n 'xcelium>|stop |value |run|\*[EWF],' ./xrun.log
```

key/log 不是 PTY 的逐字节录像，Ctrl-C 控制字节不会作为普通命令写入 key。日志是运行时持续写入的证据；读取到末尾后仍应结合当前 `xcelium>` prompt 判断命令是否已经完成。

## 最短的 UVM component 实例断点路径

第一步运行到 component 已创建。官方 UVM Tcl 直接支持停在 build phase 结束：

```tcl
uvm_phase -stop_at build -end
run
```

列出并核对 UVM hierarchy：

```tcl
uvm_component -list
uvm_component -describe uvm_test_top -depth -1
```

Xcelium 为 UVM component 提供 `$uvm:{...}` 逻辑路径。用外层 Tcl braces 防止 `$uvm` 被变量替换：

```tcl
describe {$uvm:{uvm_test_top.worker_b}}
stop -create -line 24 {$uvm:{uvm_test_top.worker_b}} \
  -file /abs/path/worker.sv
run
```

`stop -show` 应显示类似：

```text
Line: /abs/path/worker.sv:24 (scope: $uvm:{uvm_test_top.worker_b}.run_phase)
```

这已经是指定 component 实例断点，不需要 bootstrap breakpoint、glob 过滤循环或额外 Tcl helper。若用户给的是 glob，先用 `uvm_component -list` 得到名字并在 Tcl list 上用 `string match` 选择；选中后仍调用上面的原生 `stop -line`。

## 条件断点

指定 component、源码行和动态成员条件：

```tcl
stop -create -line 24 {$uvm:{uvm_test_top.worker_b}} \
  -file /abs/path/worker.sv \
  -if {[value hit_count] == 3}
```

针对同一 class 的全部实例：

```tcl
stop -create -line 24 -file /abs/path/worker.sv -all \
  -if {[value hit_count] == 3}
```

信号或变量变化断点使用：

```tcl
stop -object tb.watched
stop -condition {[value tb.cycle_count] == 3}
```

管理断点：

```tcl
stop -show
stop -disable <id>
stop -enable <id>
stop -delete <id>
stop -delete *
```

## 对象、成员和局部变量

UVM component 逻辑路径可直接描述，并显示 instance handle 与成员：

```tcl
describe {$uvm:{uvm_test_top.worker_b}}
```

普通 class handle 和成员：

```tcl
describe tb.item_a
value tb.item_a
value tb.item_a.value
value tb.item_a.name
```

命中动态 method 后，当前 scope 内的成员和 local 直接按名字读取；Xcelium 此处不需要 `this.`：

```tcl
where
stack -show
value hit_count
value instance_value
value bias
value sum
value i
```

`value {$uvm:{...}}` 会因为 component handle 本身没有标量值而报错；查询 component 使用 `describe`，查询其成员使用当前动态 scope 或明确成员路径。

for/while block 尚未进入或已经退出时，循环变量不可见；function/task frame 返回后，其参数和 local 也不可见。

## 控制流

```tcl
run -step
run -next
run -return
```

- `run -step`：执行一个 statement，并进入 function/task 调用。
- `run -next`：执行一个 statement，跨过当前行的 function/task 调用。
- `run -return`：运行到当前 function/task 返回 caller。

命中其它已启用断点会优先暂停 `run -return`；需要观察纯粹的 frame 返回行为时先禁用无关断点。返回 caller 后，赋值语句可能尚未把返回值写入 caller 变量；再执行一次 `run -step` 后查询。

运行到循环或 function 结束也可直接在已知出口行设置临时行断点，然后 `run`。结束整个模拟器 session 使用 `exit`；`finish` 会终止仿真，不等价于从当前 function 返回。

常用意图对应关系：循环外有已知源码行时设置临时行断点后 `run`；结束当前 function/task 用 `run -return`；只跨过当前调用用 `run -next`。运行前先用 `stop -show` 核对其它已启用断点，因为它们可能更早命中。

## 主动中断

向正在执行 `run` 的同一个 PTY 写入 Ctrl-C 字节 `0x03`。Xcelium 会打印：

```text
Simulation interrupted at <time>
xcelium>
```

随后使用 `where`、`stack -show` 和 `value` 检查现场。不要在 xrun 尚处于编译、加载 snapshot 阶段时注入 Ctrl-C，否则中断的是 xrun 进程而不是仿真运行。

## 本机官方文档入口

在 `$XCELIUM_HOME/doc` 中优先查阅：

- `tclcmdref/stop.html`、`run.html`、`value.html`、`describe.html`、`stack.html`；
- `tclcmdref/Using__uvm_to_Represent_Logical_UVM_Pathnames.html`；
- `svsim/Set_Line_Breakpoints_within_Classes_with_Tcl.html`；
- `sysverilog/Setting_a_Conditional_Breakpoint_Inside_a_Class.html`；
- `debugging_uvm/Using_the_UVM_Toolbar_and_Menu.html`。
