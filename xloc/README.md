# xloc

`xloc` 是给 LLM debug agent 使用的 UVM 日志位置压缩与恢复工具。

它回答的问题很窄：

- 这个 `L_XXXXXXXX` 对应哪个源文件？
- 这段仿真日志里哪些位置报错最多？
- 这个 loc_id 附近源码是什么样的？

它明确不做：

- 不分析 RTL 逻辑
- 不读 FSDB 波形
- 不查设计层次结构
- 不做仿真或 formal

## 核心思路

UVM 仿真日志中大量出现这种内容：

```text
UVM_ERROR <project-root>/tb/env/scoreboard.sv(238) @ 100ns: packet mismatch
```

对 LLM 来说，长文件路径消耗 token；行号则是定位上下文所需的关键信息。

`xloc` 把它变成：

```text
UVM_ERROR L_00000001(238) @ 100ns: packet mismatch
```

当 LLM 需要知道具体位置时，调用 `xloc resolve L_00000001` 还原。

## Quick Start

所有 one-shot 命令默认输出 `xout` 结构化文本；`resolve/context/stats`
需要稳定字段编程时可加 `--json`。`annotate` 使用 `--format json` 取得 JSON
response，只有显式 `--format raw` 才把转换后的日志 artifact 写到 stdout。
raw 只允许在所有 loc_id 都成功解析时输出，不能隐藏 partial 结果。

```bash
pytest --xverif-gate fast --xverif-suite xloc.unit

# 用一个手动构造的 JSONL 试一下
echo '{"loc_id":"L_00000001","file":"tb/test.sv"}' > <repo>/tmp/test.xloc.jsonl
tools/xloc resolve L_00000001 --map <repo>/tmp/test.xloc.jsonl
tools/xloc resolve L_00000001 --map <repo>/tmp/test.xloc.jsonl --json
```

### Shell 命令入口

为了在任意目录和非交互 shell 中稳定调用，建议把仓库 `tools/` 加入 `PATH`。下面示例里的 `<xverif-root>` 表示本仓库根目录，请按本机实际路径替换。

Bash / Zsh：

```bash
export XVERIF_HOME=<xverif-root>
export PATH="$XVERIF_HOME/tools:$PATH"
```

Tcsh：

```tcsh
setenv XVERIF_HOME <xverif-root>
setenv PATH "$XVERIF_HOME/tools:$PATH"
```

配置后可以直接使用：

```bash
xloc resolve L_00000001 --map out/sim.log.xloc.jsonl
xloc stats out/sim.log
```

## Commands

### resolve — 还原源码位置

```bash
xloc resolve L_00000005 --map out/sim.log.xloc.jsonl
```

输出：

```text
loc_id:  L_00000005
file:    tb/simple_test.sv
```

### context — 查看源码上下文

```bash
xloc context L_00000005 --map out/sim.log.xloc.jsonl --line 3 --before 5 --after 5
```

行号由压缩日志中的 `L_XXXXXXXX(<line>)` 保留；`context` 必须通过 `--line`
显式提供该值。

`--before` / `--after` 默认各 20 行，且必须是非负整数。源码文件不存在、不是
UTF-8，或目标行超出文件范围时返回 typed error，不发布 warning-success。

### stats — 统计热点位置

```bash
xloc stats out/sim.log --top 20
```

自动查找同目录下的 `sim.log.xloc.jsonl`（或通过 `--map` 指定）。
日志扫描只使用仓库内的 UTF-8 Python 实现，不调用 `rg`、`grep` 或其它替代
扫描器。相同计数按 `loc_id` 排序，结果与 `PATH` 无关。

输出：

```text
loc_id          count  file
L_00000001        127  tb/scoreboard.sv
L_00000002         31  tb/monitor.sv
...
27 unique source files, 320 total occurrences
```

`top` 是明确的 response 行数限制。若总 location 数超过 `top`，response 设置
`status=partial`、`response_truncated=true`、`total_count/returned_count` 和
`truncation_scopes=["rows"]`。缺少可选 sidecar 或 map 中没有某个 loc_id 时，
对应 row 使用 `resolution_status=unresolved` 且不生成 `file` 字段，并同时发布
`unresolved_location_count` 和 typed diagnostics；不会用 `?` 冒充文件名。显式
传入但不存在的 map，以及任何损坏 map，直接返回 error。

### annotate — 给日志加注释

```bash
xloc annotate out/sim.log --map out/sim.log.xloc.jsonl
xloc annotate out/sim.log --map out/sim.log.xloc.jsonl --format raw
```

在 log 中每个首次出现的 loc_id 前插入一行：

```text
[loc] L_00000001 -> tb/test.sv
```

默认 XOUT 和 JSON response 的 `lines` 数组完整保留每一行及换行符，可以逆向
恢复 artifact。raw artifact 输出到 stdout，可重定向到文件；工具不会根据管道
或终端环境自动切换输出格式。只要存在未解析 loc_id，默认 XOUT/JSON 返回
partial 和 diagnostics，`--format raw` 则以 `RAW_OUTPUT_INCOMPLETE` 失败。

## 严格 map 合同

sidecar 是 UTF-8 JSONL，每个非空文件行必须是且只能是：

```json
{"loc_id":"L_00000001","file":"tb/test.sv"}
```

- `loc_id` 必须完整匹配 `L_[0-9A-F]{8}`；
- `file` 必须是非空 Unicode 字符串，且不能包含 control character 或孤立
  surrogate；
- 未知字段、缺字段、blank line、非 object、非法 JSON/UTF-8 均使整个 map 失败；
- 同一个 `loc_id` 出现两次即失败，后项不会覆盖前项；
- `resolve/context` 的 map 必填；`stats/annotate` 只有未显式给 map 且 canonical
  `<log>.xloc.jsonl` 不存在时，才发布明确的 unresolved partial response。

## UVM 集成

### 在你的验证环境中使用

将仓库中 `sv/xloc_pkg.sv` 和 `sv/xloc_report_server.sv` 两个文件复制到你的验证环境，然后在 testbench 顶层注册：

```systemverilog
import xloc_pkg::*;

xloc_report_server loc_svr;

initial begin
  loc_svr = new();
  loc_svr.copy(uvm_coreservice_t::get().get_report_server());
  uvm_coreservice_t::get().set_report_server(loc_svr);
end
```

仿真后产物：

- `sim.log` — 路径已替换为 `L_XXXXXXXX`，原始行号保留为 `L_XXXXXXXX(<line>)`
- `sim.log.xloc.jsonl` — sidecar 映射文件

可以通过 `set_map_path("custom/path.jsonl")` 自定义 JSONL 输出路径。

### 机制

- loc_id 使用递增序列号：`L_%08X`（零碰撞）
- 通过 static 关联数组去重：同一 file 只生成一次
- sidecar 每行仅保存 `loc_id` 和 `file`；行号和 msg_id 保留在日志正文中
- 每次仿真以写模式创建一份独立 sidecar，避免混入上一次运行的重复 loc_id
- file 经过完整 JSON string 转义；每条写入后 `fflush`，仿真中断时已写记录仍保留

## Vim / Neovim `gf` 跳转

`xloc` 提供 Vimscript 和 Neovim Lua 插件。打开 `sim.log` 后，将光标放在 `L_XXXXXXXX(<line>)` 上按 `gf`，插件从 sidecar 还原文件路径，并使用日志中的行号跳转。

安装方式任选一种：

```vim
" 在 ~/.vimrc 中 source 仓库内插件
source <xverif-root>/xloc/vim/plugin/xloc.vim
```

或复制到 Vim 插件目录：

```bash
mkdir -p ~/.vim/plugin
cp <xverif-root>/xloc/vim/plugin/xloc.vim ~/.vim/plugin/xloc.vim
```

固定 map 规则：

```text
<run-dir>/sim.log
<run-dir>/sim.log.xloc.jsonl
```

如果 JSONL 里的 `file` 是相对路径，建议在 `~/.vimrc` 设置工程根目录：

```vim
let g:xloc_repo_root = "<project-root>"
```

插件默认只在 `*.log` 且旁边存在 `<log>.xloc.jsonl` 时启用 buffer-local `gf`，不会全局覆盖普通源码文件里的 `gf`。如需关闭自动映射：

```vim
let g:xloc_auto_enable = 0
```

关闭自动映射后仍可手动执行：

```vim
:XlocGF
```

Vimscript 版本只使用 Vim 内建 `readfile()` 与 `json_decode()` 完整验证 map，
不调用 `rg`/`grep`，也没有正则 JSON parser。任意损坏或重复记录都会阻止跳转并
显示明确错误；验证后的记录按 map mtime 缓存。

### Neovim Lua

将 `xloc/nvim` 加入 Neovim runtimepath，然后在 `init.lua` 配置：

```lua
vim.opt.rtp:append("<xverif-root>/xloc/nvim")
require("xloc").setup({
  repo_root = "<project-root>",
  auto_enable = true,
})
```

也可以将整个 `xloc/nvim` 目录安装到 Neovim 的 `pack/*/start/` 下，插件会自动
加载。Lua 版本同样完整验证 closed-schema map，只使用 Neovim 原生 JSON 和文件
API，不依赖 `rg` 或 `grep`；它只在有 sidecar 的 `*.log` buffer 中建立
buffer-local `gf`，并提供 `:XlocGF`。

## 内建 UVM 测试环境

```bash
pytest --xverif-prepare xloc.uvm
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate nightly --xverif-suite xloc.uvm
```

测试环境位于 `xloc/tb/`，在不同文件中调用 `uvm_error`/`uvm_warning`/`uvm_info`，验证多文件 loc_id 生成和去重。显式 prepare 通过 `Makefile.fixture` 构建并发布内容寻址缓存；nightly 只消费缓存，不会隐式重复仿真。

## Agent 使用原则

当 LLM debug agent 处理带 loc_id 的日志时：

1. **不要猜 loc_id**。用 `xloc resolve` 查询。
2. **先 stats 后 resolve**。了解高频位置，优先查这些。
3. **需要源码证据时才 context**。只是想知道文件在哪用 resolve 就够了。
4. **先检查完整性**。只有 `ok=true`、`status=complete`、
   `analysis_complete=true` 且 `response_truncated=false` 才能当作全量事实。
5. **回答时引用 loc_id + 文件位置**。例如：`L_00000005 (simple_test.sv:3)`。

## 构建与测试

```bash
make -C xloc          # 语法检查
pytest --xverif-gate fast --xverif-suite xloc.unit
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression --xverif-suite xloc.vim
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression --xverif-suite xloc.nvim
pytest --xverif-prepare xloc.uvm
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate nightly --xverif-suite xloc.uvm
```

`xloc` 只依赖 Python 标准库，不依赖 NPI、Verdi 或任何 Synopsys 工具。UVM 测试环境需要 VCS。
