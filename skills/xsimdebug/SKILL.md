---
name: xsimdebug
description: 当 AI agent 需要定位 SystemVerilog/UVM 验证问题、重新编译代价过高或不允许再次编译，并需要直接通过终端 PTY 使用 Synopsys VCS UCLI 或 Cadence Xcelium/Xrun Tcl 实时调试正在运行的仿真时使用，包括断点、Ctrl-C 暂停、运行时变量查询和控制流。若已有仿真 log 已足以定位问题，则不使用本 skill。
---

# xsimdebug

直接持有模拟器 PTY session，通过 stdin/stdout/stderr 实时交互。不要为此搭建 Python、MCP、UDS 或额外 daemon。

## 是否触发

先阅读已有仿真 log。若 log 已经给出足够证据，可直接定位根因或明确下一步修复，则不触发本 skill。只有仍需观察运行时状态，并符合以下任一场景时才使用：

- 需要通过交互式运行时现场定位验证问题；
- 重新编译代价过高，希望复用已有可调试仿真产物；
- 当前流程不允许再次编译，只能在已有仿真上继续调查。

本 skill 不是默认的日志分析入口，也不应替代成本更低且证据已经充分的 log 定位流程。

## 路由

先确认实际模拟器，再只读取对应参考：

- VCS/simv：读取 [references/vcs-ucli.md](references/vcs-ucli.md)。它使用 UCLI；按 UVM hierarchy path 设置实例断点或查询成员时加载随 skill 携带的 [scripts/uvm_component_break.tcl](scripts/uvm_component_break.tcl)。
- Xcelium/Xrun：读取 [references/xrun-tcl.md](references/xrun-tcl.md)。优先使用 `$uvm:{...}` 逻辑路径和 Xcelium 原生 Tcl，不加载 VCS helper。

不要把两个模拟器的命令混用，也不要在一个入口失败后静默切换模拟器。

## 共同边界

- 遵守项目对 license 和真实 EDA 工具的宿主执行要求；在 xverif 仓库中直接在沙箱外运行。
- 保持同一个 PTY session。启动后持续向该 session 写命令，不为每条命令新建 shell 进程。
- 不确定命令、选项或版本差异时，先在模拟器 prompt 执行 `help` 和 `help <command>`；以当前安装版本返回的帮助为准。
- 运行中需要主动暂停时，向同一个 PTY 注入 Ctrl-C 字节 `0x03`；返回 prompt 后检查当前位置和调用栈。
- 交互运行会自动产生 key 命令历史文件：VCS 为启动目录下的 `ucli.key`，Xrun 为运行目录下的 `xrun.key`；不要为此修改启动参数。回看执行过哪些命令时第一选择是 key；需要命令输出、错误和上下文时，再读取启动命令现有 `-l` 所指向的 log，不依赖终端 scrollback。
- key/log 是模拟器生成的记录，不是 PTY 的逐字节录像；Ctrl-C 等控制字节、终端回显和 prompt 可能不会完整出现。
- 不把 prompt 返回当作命令成功；检查模拟器原始 error/warning 输出。
- 保留关键命令、断点 ID、时间、源码位置、实例路径和查询值作为证据。

## 交互终端与 tmux

优先使用 agent 自带的交互式 terminal/PTY 工具。若 agent 只能执行一次性 shell 命令、不能持续读写同一个 PTY，但宿主提供 `tmux`，可用一个唯一命名的 tmux session 承载模拟器：

```bash
tmux new-session -d -s xsimdebug-vcs \
  'cd /abs/path/to/run-dir && exec ./simv -ucli -no_save'
tmux capture-pane -p -S -200 -t xsimdebug-vcs
tmux send-keys -t xsimdebug-vcs 'help stop' Enter
sed -n '1,240p' /abs/path/to/run-dir/ucli.key
tmux send-keys -t xsimdebug-vcs C-c
```

Xrun 使用相同机制，把启动命令替换为项目实际的 `xrun ... -input /dev/null`，不要仅为记录历史追加 `-k` 或 `-l`。tmux 只替代 PTY 传输层，不改变 VCS UCLI 或 Xrun Tcl 命令语义。使用前确认 `tmux` 存在，保留同一 session；`capture-pane` 只用于确认 prompt/readiness。历史命令先看 key，输出和错误再查看已有 log。不要靠固定 sleep 猜测 ready，也不要为每条命令创建新 session。结束时先向模拟器发送 `exit`，只管理本次创建且名称明确的 session。

## 结果要求

- 明确断点是全实例还是指定 object/component 实例。
- 条件断点应报告实际条件和命中时变量值。
- 局部变量离开 block/frame 后不可见是正常生命周期，不误判为设计数据库损坏。
- 验证实例过滤时，确认非目标实例能够经过目标位置而不触发最终断点。
