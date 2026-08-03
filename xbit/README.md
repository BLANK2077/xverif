# xbit

`xbit` 是给芯片验证 debug agent 使用的确定性 bit/value/expression 计算工具。

它回答的问题很窄：

- 这个 SV literal 到底是多少？
- 这个 slice、concat、repeat、mask、onehot、popcount 结果是多少？
- 这个 signed/unsigned 解释是否正确？
- 这个常量表达式或某一拍条件是否成立？

它明确不做：

- 不解析 RTL 文件
- 不读 filelist
- 不分析 module / instance / hierarchy
- 不做 parameter elaboration
- 不做 lint、formal 或仿真

## Quick Start

`xbit` wrapper 按固定顺序解析解释器：优先使用已配置的 Miniconda Python，否则使用声明的 `python3` 入口。该步骤只启动同一个 xbit 实现，不会切换 action、backend 或 data source。

默认输出 token-efficient `xout`，用紧凑字段减少 AI/LLM token；需要稳定字段编程、schema 校验、结构化持久化或用户明确要求时才加 `--json`。

```bash
pytest --xverif-gate regression --xverif-suite xbit.unit

xbit conv "8'shff"
xbit slice "32'hdead_beef" 15 8
xbit eval "data[15:8] == 8'hbe" --var data=32'hdead_beef
xbit check --expr "valid && ready" --var valid=1'b1 --var ready=1'b0
```

未安装 shell 命令时的仓库内临时入口：

```bash
tools/xbit conv "8'shff"
tools/xbit conv "8'shff" --json
```

### Shell 命令入口

为了在任意目录和非交互 shell 中稳定调用，建议把仓库 `tools/` 加入 `PATH`。下面示例里的 `<xverif-root>` 表示本仓库根目录，请按本机实际路径替换；文档和 skill 中不固定记录个人机器路径。

Bash：加入 `~/.bashrc`。

```bash
export XVERIF_HOME=<xverif-root>
export PATH="$XVERIF_HOME/tools:$PATH"
```

Zsh：加入 `~/.zshrc`。

```zsh
export XVERIF_HOME=<xverif-root>
export PATH="$XVERIF_HOME/tools:$PATH"
```

Tcsh：加入 `~/.tcshrc`。

```tcsh
setenv XVERIF_HOME <xverif-root>
setenv PATH "$XVERIF_HOME/tools:$PATH"
```

配置后可以直接使用：

```bash
xbit conv "8'shff" --json
xbit eval "data[15:8] == 8'hbe" --var data=32'hdead_beef --json
```

JSON 成功响应：

```json
{
  "ok": true,
  "schema": "xbit.result.v1",
  "op": "conv",
  "result": {
    "width": 8,
    "signed": true,
    "known": true,
    "unsigned": 255,
    "signed_value": -1,
    "hex": "0xff",
    "bin": "1111_1111",
    "sv": "8'shff"
  },
  "warnings": []
}
```

失败响应：

```json
{
  "ok": false,
  "schema": "xbit.error.v1",
  "error": {
    "code": "WIDTH_OUT_OF_RANGE",
    "message": "slice range is invalid for value width"
  }
}
```

## Commands

### Value conversion

```bash
xbit conv "16'hff80" --json
xbit conv "8'shff" --json
xbit conv "32'd-1" --json
```

`result` 默认同时给 `width`、`signed`、`unsigned`、`signed_value`、`hex`、`bin`、`sv`。

### Bit operation

```bash
xbit slice "32'hdead_beef" 15 8 --json
xbit index "8'h80" 7 --json
xbit concat "4'ha" "4'h5" --json
xbit repeat 4 "2'b10" --json
xbit trunc "16'h12ff" --to 8 --json
xbit zext "8'h80" --to 16 --json
xbit sext "8'h80" --to 16 --json
xbit reverse "8'b1000_0001" --json
xbit mask --width 13 --json
xbit align "13'd17" --to 8 --json
xbit popcount "32'hdead_beef" --json
xbit onehot "8'h20" --json
xbit onehot0 "8'h00" --json
xbit gray2bin "4'b1110" --json
xbit bin2gray "4'b1011" --json
```

### Expression evaluation

```bash
xbit eval "8'shff >>> 1" --json
xbit eval "{4{2'b10}}" --json
xbit eval "{4'hA, 4'h5}" --json
xbit eval "ADDR_W + ID_W - 1" --var ADDR_W=32 --var ID_W=4 --json
xbit eval "valid && ready" --var valid=1'b1 --var ready=1'b0 --json
xbit eval "data[15:8] == 8'hbe" --var data=32'hdead_beef --json
```

支持范围：

- SV numeric literal
- arithmetic：`+ - * / %`
- bitwise：`~ & | ^`
- logical：`! && ||`
- comparison：`== != < <= > >=`
- shift：`<< >> <<< >>>`
- concat/repeat：`{a,b}`、`{N{value}}`
- slice/index：`value[msb:lsb]`、`value[bit]`
- ternary：`cond ? a : b`
- 用户显式传入变量：`--var name=value`

不支持宏展开、函数调用、typedef、packed struct、enum、module parameter 自动解析。

### Wave/debug check

`check` 用于读取明确的变量字面量 map，并判断某个条件。

```bash
xbit check \
  --expr "valid && ready && data[15:8] == 8'hbe" \
  --var valid=1'b1 \
  --var ready=1'b1 \
  --var data=32'hdead_beef
```

`--values` 支持直接 map：

```json
{
  "valid": "1'b1",
  "ready": "1'b1",
  "data": "32'hdead_beef"
}
```

`--values` 文件只接受上面的直接 map；不接受包装对象或每个值的别名字段。
`--values` 与 `--var` 是互斥的变量来源，同时传入会直接报错。

### Agent stdio

```bash
xbit agent serve --stdio
```

输入一行 JSON request，输出一行 JSON response：

```json
{"id":1,"method":"xbit.eval","params":{"expr":"data[15:8] == 8'hbe","vars":{"data":"32'hdead_beef"}}}
```

支持方法：

- `xbit.conv`
- `xbit.eval`
- `xbit.slice`
- `xbit.concat`
- `xbit.repeat`
- `xbit.mask`
- `xbit.popcount`
- `xbit.check`

## 2-state 与 4-state

默认 `--state 2`。遇到 `x/z/?` 会失败，避免 agent 把未知值当确定值。

`--state 4` 可以保留 literal 中的 X/Z 展示信息，但表达式传播不是本轮目标；遇到无法确定的 4-state 运算会返回 `FOUR_STATE_UNSUPPORTED`。

## Agent 使用原则

当调试涉及以下内容时，agent 应调用 `xbit`，不要心算：

- 进制转换
- bit slice/index
- concat/repeat
- signed/unsigned 解释
- mask、popcount、onehot
- SystemVerilog literal
- 常量表达式
- valid-ready 条件判断
- expected value 比较

`xdebug` 负责查询 daidir/fsdb 事实，`xbit` 负责对这些事实做确定性 bit/value/expression 计算。
