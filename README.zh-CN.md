# xverif

[English](README.md) | **简体中文**

> [!IMPORTANT]
> **开源范围与 Synopsys proprietary dependencies**
>
> 本仓库以 MIT License 发布的范围仅包括仓库中由本项目独立开发的 source code 和 documentation。仓库不包含、也不授权 Synopsys Verdi NPI、FSDB Reader、coverage runtime、headers、libraries 或 documentation。
>
> `xdebug` 和 `xcov` 的部分能力需要用户在本地另行取得合法授权并安装相应 Synopsys software；设置 `VERDI_HOME` 或能够访问相关文件本身不代表已经获得 NPI/FSDB API 的使用权或 redistribution 权。不得把 `libNPI.so`、`libnpiL1.so`、`libnffr.so`、Synopsys headers/documentation，或包含这些内容的 binary、package、container image 随本仓库分发。具体边界见 [`THIRD_PARTY.md`](THIRD_PARTY.md)。

`xverif` 是面向芯片验证 debug agent 的本地工具仓库，当前包含六个核心工具、两个 agent skill 和一个统一 MCP 入口：

- [`xdebug`](xdebug/README.md)：查询设计数据库和波形数据库里的事实。
- [`xbit`](xbit/README.md)：确定性计算 bit、literal、slice、表达式和 expected value。
- [`xentry`](xentry/README.md)：按配置解析多拍 byte fragments，输出 raw entry 域段。
- [`xloc`](xloc/README.md)：UVM 日志位置压缩与恢复，降低 LLM token 噪声。
- [`xwiki`](skills/xwiki/SKILL.md)：维护验证项目 LLM wiki 的持续记忆 skill，避免 agent 每次 session 从 0 理解项目。
- [`xsimdebug`](skills/xsimdebug/SKILL.md)：通过终端 PTY 实时操作 VCS UCLI 或 Xcelium Tcl 调试仿真。
- [`xsva`](xsva/README.md)：把 SystemVerilog Assertion 编译为结构化 IR，并生成确定性解释和可视化。
- [`xcov`](xcov/README.md)：查询 VCS/Verdi coverage database，输出 compact coverage evidence。
- [`xverif-mcp`](xverif_mcp/README.md)：统一 MCP server，xdebug/xcov 作为 stateful backend，其他工具以 stateless CLI adapter 接入。

简单说：`xdebug` 负责“事实从哪里来、某时刻发生了什么”，`xbit` 负责“这些值按 SystemVerilog 规则算出来到底是多少”，`xentry` 负责“这个 entry 的 bit 域段按配置切出来是什么”，`xloc` 负责“这条 log 在哪个文件的哪一行，但只在需要时才查”，`xwiki` 负责“把验证环境、DUT 功能、workflow、debug 入口等知识编译进持续 LLM wiki”，`xsimdebug` 负责“直接操作正在运行的 VCS 或 Xcelium 仿真”，`xsva` 负责”assertion 的 temporal 语义先降成 IR，再解释给人和 agent”，`xcov` 负责“coverage database 里哪些 scope/object/bin 已覆盖或未覆盖，并给出源码 evidence”，`xverif-mcp` 负责”把确定性工具统一暴露给 AI agent 的 MCP 协议入口”。

## 工具概览

### 默认输出格式：XOUT

除显式机器协议外，xverif 用户命令默认输出 `xout` 结构化文本，第一行形如：

```text
@xdebug.trace.driver.v1
```

`xout` 使用少量固定区块，例如 `target:`、`summary:`、`data:`、`evidence:`、`next:`，目的是让 AI 少读无用 JSON envelope。需要脚本解析、schema 校验或完整字段时，显式加 `--json`；内部 agent stdio/hook 协议仍保持 JSON。

### xdebug

`xdebug` 是 xtrace 与 xwave 合并后的统一调试工具。它通过 JSON API 查询 Verdi/VCS `daidir` 设计事实、FSDB 波形事实，或在两者同时存在时做 combined/debug join。

适合的问题：

- 查信号 driver、load、依赖图、路径和源码 evidence。
- 查波形值、事件、窗口验证、signal changes、handshake 异常。
- 查 APB/AXI 协议异常、latency、outstanding、error response。
- 在具体波形时间点定位当前生效 RTL driver：`trace.active_driver`。

入口示例：

```bash
tools/xdebug -h
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | tools/xdebug -
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | tools/xdebug --json -
tools/xverif-mcp
```

`tools/xverif-mcp` 是统一 stdio MCP server（`python -m xverif_mcp.server`），xdebug 作为设计/波形 stateful backend，xcov 作为 coverage stateful backend，xbit/xentry/xloc/xsva 以 stateless CLI adapter 接入。
如果 AI 客户端在登录机、NPI/FSDB 查询需要跑到 LSF 计算节点，可以设置 `XVERIF_MCP_BACKEND=lsf`，让 MCP wrapper 通过 `bsub -I` 启动集群内 per-session stdio-loop 进程。不同 session 并行，同一 session 串行。
可用 `XVERIF_MCP_ENABLE_DEBUG/BIT/ENTRY/LOC/SVA` 等环境变量按工具组关闭 MCP 暴露面。
如果不走 MCP 且本机无法直连计算节点 TCP 端口，xdebug 原生支持 `transport:"file"`，通过共享文件系统在 session 目录下交换 request/response。

所有 MCP tool 通用支持 `xverif_output_path` / `xverif_output_append` 参数，可将响应同时写入文件；文件写入失败会返回 `OUTPUT_WRITE_FAILED`，不能把原 action 成功当作完整成功。

完整说明见 [`xdebug/README.md`](xdebug/README.md)。

### xbit

`xbit` 是确定性 bit/value/expression 计算器。它不读取 RTL、不分析层次结构，只负责把输入值按明确规则算对，避免 agent 靠心算处理位宽、符号位和表达式。

适合的问题：

- SV literal、hex/bin/decimal 转换。
- signed/unsigned 解释。
- bit slice/index、concat、repeat、mask、popcount、onehot。
- 常量表达式、valid-ready 条件、expected value 比较。
- 对 `xdebug` 返回的 compact values 做二次计算。

入口示例：

```bash
tools/xbit conv "8'shff"
tools/xbit eval "data[15:8] == 8'hbe" --var data=32'hdead_beef
```

完整说明见 [`xbit/README.md`](xbit/README.md)。

### xentry

`xentry` 是 JSON-first 的多拍 entry 域段解析器。它接收 canonical byte fragments，由外部 config 定义字段布局，只输出 raw field slices 和 provenance，不做协议理解或字段类型语义解码。

适合的问题：

- 解析 descriptor、metadata、table entry、WQE、CQE 或 header field。
- 把多拍 byte fragments 按有效 bit 拼成 entry。
- 按配置切出 field raw hex/bin。
- 查看跨拍 field 来自哪一拍、哪些 bit。

入口示例：

```bash
printf '%s\n' '{"api_version":"xentry.v1","action":"decode","config_path":"xentry/examples/entry.yaml","input_path":"xentry/examples/fragments.jsonl"}' | tools/xentry -
tools/xentry '{"api_version":"xentry.v1","action":"explain","config_path":"xentry/examples/entry.yaml"}'
tools/xentry --json '{"api_version":"xentry.v1","action":"explain","config_path":"xentry/examples/entry.yaml"}'
```

完整说明见 [`xentry/README.md`](xentry/README.md)。

### xloc

`xloc` 是 LLM-friendly 的 UVM 日志位置压缩与恢复工具。它将 UVM 仿真日志中冗长的文件路径替换为简短 `L_XXXXXXXX` ID，通过 sidecar JSONL 映射文件支持按需恢复源码上下文，降低 LLM 处理 log 的 token 噪声。

适合的问题：

- 解析仿真日志中 `L_XXXXXXXX` 对应的源码位置。
- 统计日志中高频报错的热点位置。
- 查看 loc_id 对应的源码上下文。
- 给带 loc_id 的日志添加可读注释。

入口示例：

```bash
tools/xloc resolve L_00000001 --map out/sim.log.xloc.jsonl
tools/xloc stats out/sim.log
```

完整说明见 [`xloc/README.md`](xloc/README.md)。

### xwiki

`xwiki` 是芯片验证持续记忆 skill。它要求 agent 通过 `XWIKI_DIR` 找到当前 session 的 LLM wiki，从 `index.md`、concept 页面、反向索引和 `rg` 逐步查询验证环境、DUT 功能、接口、testbench、workflow、debug 入口等信息，并把新的稳定发现编译回 wiki。

适合的问题：

- 给新 agent 复用验证项目持续记忆，避免每次从 0 阅读仓库。
- 查询 DUT、验证环境、接口、sequence、checker、scoreboard、coverage、workflow 和 debug 入口。
- 将源码、README、spec、test、wave/debug 报告或用户说明编译成 wiki concept。
- 用 hook/validator 检查 wiki frontmatter、相对链接、log、deprecated 页面和 backlinks。

入口示例：

```bash
export XWIKI_DIR=/path/to/project/wiki
python skills/xwiki/scripts/validate_xwiki.py
```

完整说明见 [`skills/xwiki/SKILL.md`](skills/xwiki/SKILL.md)。

### xsva

`xsva` 是 SystemVerilog Assertion 语义编译工具。它不替代 VCS/Formal，也不让 LLM 直接自由解释 SVA 原文；它把 property/assertion 从文本 lowering 成 Surface IR、Sequence IR、Timeline IR，再从 IR 生成文本、Markdown 或 JSON 输出。

适合的问题：

- 列出 `.sva/.sv` 文件中的 property/assert/assume/cover。
- 检查 `|->`、`|=>`、`##N`、`##[m:n]`、range suffix path expansion 等 temporal 语义。
- 查看 local variable capture、per-attempt binding 和后续 `depends_on_captures`。
- 对 `first_match`、`intersect` 等高级 sequence 输出语义摘要，内部保留保守状态但不在用户解释中暴露。
- 为 SVA review、agent debug 和 golden regression 生成确定性 IR/解释。

入口示例：

```bash
tools/xsva list --file xsva/tests/golden_ir/simple_impl/input.sva
tools/xsva parse --file xsva/tests/golden_ir/ranged_delay/input.sva --property p_ranged --emit timeline-ir
tools/xsva explain --file xsva/tests/golden_ir/path_expand/input.sva --property p_path
```

完整说明见 [`xsva/README.md`](xsva/README.md)。

### xcov

`xcov` 是面向 AI/MCP 的 VCS/Verdi coverage database 查询引擎。它用 `xcov.v1` JSON request 查询 `simv.vdb` / `merged.vdb`，默认输出 `xout`，支持 code coverage、functional coverage、scope summary、coverage holes、source file/line 映射和大结果导出。

适合的问题：

- 打开大型 coverage database，并通过 session 复用打开成本。
- 查询 line/toggle/branch/condition/fsm/assert/functional coverage。
- 按 hierarchy scope 查看 summary、children 排名和 scope search。
- 查 coverage holes，并保留 `file/line` evidence。
- 根据源码 `file/line/window` 反查 coverage item。
- 导出 summary/holes/scope_tree/functional 为 `json/ndjson/csv/md`。

入口示例：

```bash
printf '%s\n' '{"api_version":"xcov.v1","action":"session.open","target":{"vdb":"fake"},"args":{"name":"cov0","fake":true}}' | tools/xcov --json -
tools/xcov --stdio-loop
```

MCP 工具入口使用对称的 `xverif_cov_session_open/list/doctor/close/kill/gc` 和 `xverif_cov_query`。coverage query 禁止绕过 manager 直接调用 native lifecycle action；真实 NPI coverage 查询需要可访问 Synopsys license server，环境不满足时直接报告，不自动切换 Python 或 backend。

完整说明见 [`xcov/README.md`](xcov/README.md)，agent 能力说明见 [`skills/xverif/references/xcov.md`](skills/xverif/references/xcov.md)，MCP 运行环境问题见 [`skills/xverif-admin/SKILL.md`](skills/xverif-admin/SKILL.md)。

## 推荐 Shell 入口

为了在任意目录和非交互 shell 中稳定调用，建议把统一 wrapper 目录加入 `PATH`。示例中的 `<xverif-root>` 表示本仓库根目录，请按本机实际路径替换。

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

配置后：

```bash
xdebug -h
xbit conv "8'shff" --json
xentry '{"api_version":"xentry.v1","action":"explain","config_path":"xentry/examples/entry.yaml"}'
xloc resolve L_00000001 --map out/sim.log.xloc.jsonl
xsva list --file xsva/tests/golden_ir/simple_impl/input.sva
xcov --stdio-loop
```

所有工具入口统一放在 `tools/` 目录下。

## 同步 Agent 环境变量

Claude Code、Codex 等 AI agent 通常由 IDE、插件或独立进程启动，不一定继承当前交互 shell 里已经 `source` 过的 Verdi、license、LSF、Python、`PATH` 等环境。这样会出现命令行里 `xdebug`/`xcov`/MCP 能跑，但 agent 里找不到工具、license 或动态库的问题。

根目录脚本 [`sync_agent_env.py`](sync_agent_env.py) 用来把当前 `env` 增量写入项目级 agent 配置。脚本零第三方依赖，兼容 Python 3.8+：

```bash
./sync_agent_env.py --target claude       # 写入 .claude/settings.json 的 env
./sync_agent_env.py --target claude-local # 写入 .claude/settings.local.json 的 env
./sync_agent_env.py --target codex        # 写入 .codex/config.toml 的 shell_environment_policy.set
./sync_agent_env.py --target codex --dry-run
```

同步规则是“当前环境中存在的变量覆盖配置里的同名变量；当前环境中没有的旧变量保持不变”。脚本不做敏感变量过滤，运行前请确认当前 shell 里允许落盘的 token、key、password 等变量。

## 环境要求

| 组件 | 要求 |
|---|---|
| GCC | **5.0+** |
| Python | 3.11+（xverif-mcp、xsva、xcov）；xbit/xentry/xloc 支持 3.6+ |
| Verdi | 当前基于 **V-2023.12-SP2** 开发与测试，NPI API 随版本不同可能存在参数差异 |

> 如果使用其他 Verdi 版本遇到编译或运行时 NPI 兼容性问题，可让 AI agent 根据编译错误和 NPI 头文件进行兼容性修复。

## 构建与测试

构建仍由 Makefile 负责；测试只有根级 catalog-driven pytest plugin 一个公开入口。首次使用可用 Miniconda 一键建立仓库本地 Python 环境；`requirements-test.txt` 是 pip 安装入口。普通 gate 只消费 `.xverif-test-cache/` 中已经发布的数据库，不会隐式运行 VCS/simv。

```bash
python3 tools/create_python_environment.py
conda activate ./.conda-xverif
python3 tools/check_test_environment.py --gate fast
make -C xdebug
pytest --xverif-gate fast
export XVERIF_TEST_EXECUTION_ENV=host  # 仅在已经进入沙箱外 host 后设置
python3 tools/check_test_environment.py --gate regression
pytest --xverif-gate regression -n auto
pytest --xverif-gate nightly -n auto
```

显式准备或校验数据库 Fixture：

```bash
pytest --xverif-prepare all-generated
pytest --xverif-fixture-validation --xverif-all-fixtures
pytest --xverif-fixture-clean
pytest --xverif-results-clean
```

依赖检查按 suite 隔离：focused suite 不会检查其它 suite 的 Vim/Neovim、NPI、VIP、VCS 或 LSF 依赖。普通 gate 只检查运行依赖和已发布 Fixture；VCS/VIP/XIF 构建依赖只在对应 prepare/validation 前检查。`xloc.nvim` 要求 `nvim` 在 `PATH` 中；本机安装在 `~/.local/bin` 时应确保 Conda 激活后仍保留该目录。

`fast` 是无外部 EDA 进程的 hermetic 门禁；`regression`、`nightly`、fixture prepare/validation 涉及 NPI、MCP 进程或 VCS 时必须在沙箱外执行。`XVERIF_TEST_EXECUTION_ENV=host` 只记录执行证据，不会提升权限或切换环境。cache miss 对 required suite 是 ERROR，并给出精确 prepare 命令；不会自动 prepare、SKIP 或切换 backend。裸 `pytest` 是 usage error。完整合同见 [`doc/agents/xdebug/tests.md`](doc/agents/xdebug/tests.md)。

## 文档入口

- xdebug 用户文档：[`xdebug/README.md`](xdebug/README.md)
- xverif 能力路由 skill：[`skills/xverif/SKILL.md`](skills/xverif/SKILL.md)
- xverif 运维 skill：[`skills/xverif-admin/SKILL.md`](skills/xverif-admin/SKILL.md)
- x-npi agent skill：[`skills/x-npi/SKILL.md`](skills/x-npi/SKILL.md)，用于 AI 编写 Python `pynpi` 批量波形统计、APB/AXI/stream 离线分析和静态 driver/load 脚本；实时 active-driver 因果追踪仍用 xdebug。
- xsimdebug 实时 VCS/Xcelium skill：[`skills/xsimdebug/SKILL.md`](skills/xsimdebug/SKILL.md)
- xdebug CLI reference：[`skills/xverif/references/xdebug/overview.md`](skills/xverif/references/xdebug/overview.md)
- xdebug JSON API 速查：[`skills/xverif/references/xdebug/json-api.md`](skills/xverif/references/xdebug/json-api.md)
- SDK-free loop wrapper：[`skills/xverif-admin/references/sdk-free-loop/overview.md`](skills/xverif-admin/references/sdk-free-loop/overview.md)
- MCP reference：[`skills/xverif-admin/references/mcp/overview.md`](skills/xverif-admin/references/mcp/overview.md)
- xbit 用户文档：[`xbit/README.md`](xbit/README.md)
- xbit agent reference：[`skills/xverif/references/xbit.md`](skills/xverif/references/xbit.md)
- xentry 用户文档：[`xentry/README.md`](xentry/README.md)
- xentry agent reference：[`skills/xverif/references/xentry.md`](skills/xverif/references/xentry.md)
- xloc 用户文档：[`xloc/README.md`](xloc/README.md)
- xloc agent reference：[`skills/xverif/references/xloc.md`](skills/xverif/references/xloc.md)
- xwiki 持续记忆 skill：[`skills/xwiki/SKILL.md`](skills/xwiki/SKILL.md)
- xsva 用户文档：[`xsva/README.md`](xsva/README.md)
- xsva agent reference：[`skills/xverif/references/xsva.md`](skills/xverif/references/xsva.md)
- xcov 用户文档：[`xcov/README.md`](xcov/README.md)
- xcov agent reference：[`skills/xverif/references/xcov.md`](skills/xverif/references/xcov.md)
- xverif-mcp 用户文档：[`xverif_mcp/README.md`](xverif_mcp/README.md)
