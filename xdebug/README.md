# xdebug

> [!IMPORTANT]
> `xdebug` 是 source-only wrapper，不随仓库提供或授权 Synopsys Verdi NPI/FSDB Reader。design、waveform 和 combined engine 需要用户自行取得适用的 Synopsys VC Apps license rights，并从其本地合法安装的 `VERDI_HOME` 编译和加载 NPI headers/libraries。请勿把 Synopsys headers、libraries、documentation 或链接这些 proprietary dependencies 的本地 build artifacts 放入源码分发包、GitHub Release、wheel/rpm/deb 或 container image。完整说明见 [`../THIRD_PARTY.md`](../THIRD_PARTY.md)。

xdebug 是 xtrace 与 xwave 合并后的统一调试工具。公开入口使用 JSON request 描述动作，默认输出 `xout` 结构化文本；需要机器解析、schema 校验或回归兼容时显式加 `--json` 获取原 JSON response。旧的 xtrace/xwave 人类 CLI 不再作为主路径维护。

仓库内验证能力的唯一通用入口是 [../skills/xverif/SKILL.md](../skills/xverif/SKILL.md)；MCP、transport、LSF、timeout 和 session 运维见 [../skills/xverif-admin/SKILL.md](../skills/xverif-admin/SKILL.md)。先按任务选择能力，再选择 MCP 或 CLI surface。

Action 协议由 `ActionSpec` / `ActionRegistry` 约束。`actions` 输出来自 runtime registry，并带有 `category`、`status`、`requires`、action-specific schema 和 example 信息；`xdebug/specs/actions/actions.yaml`、`xdebug/schemas/v1/actions` 与 `xdebug/examples` 由 contract test 校验一致。所有 non-removed action 都必须有自己的 request/response schema，不能退回通用 envelope schema。

## Architecture

```text
                         +-------------------------------+
                         |            callers            |
                         |  shell / scripts / MCP / AI   |
                         +---------------+---------------+
                                         |
                                         | JSON request
                                         v
                         +-------------------------------+
                         |        xdebug frontend        |
                         |  request parse / validation   |
                         |  action registry / xout/json  |
                         +---------------+---------------+
                                         |
                       session actions   | engine-forward actions
                    session.open/list/gc | value/trace/source/...
                                         v
        +--------------------------------+--------------------------------+
        |                         session catalog                         |
        |       ~/.xdebug/engine/registry.json + session manifests        |
        +----------------+--------------------------------+---------------+
                         |                                |
                         | spawn / reuse                  | direct request
                         v                                v
        +-------------------------------+   +-----------------------------+
        |       xdebug-engine process   |<->|  UDS / TCP / file transport |
        |  one process per session      |   |  request/response exchange  |
        +---------------+---------------+   +-----------------------------+
                        |
         +--------------+---------------+
         |                              |
         v                              v
+--------------------+        +-------------------------+
| design action code |        | waveform action code    |
| daidir / NPI DB    |        | FSDB / NPI FSDB handle  |
+--------------------+        +-------------------------+
         |                              |
         +--------------+---------------+
                        |
                        v
        +-----------------------------------------------+
        | unified engine session lifecycle              |
        | start timeout: XDEBUG_SESSION_START_TIMEOUT_SEC|
        | idle timeout : XDEBUG_SESSION_IDLE_TIMEOUT_SEC |
        +-----------------------------------------------+
```

## Quick Start

`-h` 和 `-help` 是 xdebug 唯一的非 JSON 命令，用于查看详尽的人类可读帮助：

```bash
tools/xdebug -h
tools/xdebug -help
```

默认输出是 `xout`，机器可读帮助仍通过 JSON action 获取；如果要让脚本读取完整字段，使用 `--json`：

```bash
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | tools/xdebug -
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | tools/xdebug --json -
printf '%s\n' '{"api_version":"xdebug.v1","action":"schema","args":{"action":"signal.statistics","kind":"request"}}' | tools/xdebug --json -
```

每个 action 的机器可读契约位于：

```text
xdebug/schemas/v1/actions/<action>.request.schema.json
xdebug/schemas/v1/actions/<action>.response.schema.json
xdebug/examples/requests/<action>.basic.json
xdebug/examples/responses/<action>.basic.json
```

`pytest --xverif-gate regression --xverif-suite xdebug.action_runtime_catalog` 会检查 runtime `actions` 输出、`specs/actions/actions.yaml`、schemas 和 examples 是否完全对齐；纯静态 schema/example 合同由 `pytest --xverif-gate fast --xverif-suite xdebug.static` 检查。

推荐通过仓库根目录的 wrapper 调用，它会设置 Verdi/NPI 运行所需环境。该设置只负责定位用户本地安装，不授予任何 Synopsys software、API 或 runtime 的 license rights：

> **环境与授权要求**：GCC 5.0+。当前基于 Verdi **V-2023.12-SP2** 开发与测试。用户必须自行确认其 Synopsys agreement（包括适用时的 VC Apps Access Program Agreement）允许使用对应 NPI/FSDB interfaces。NPI API 随 Verdi 版本不同可能存在参数差异——如果使用其他版本遇到编译或运行时 NPI 兼容性问题，可让 AI agent 根据编译错误和用户本地 NPI headers（`$VERDI_HOME/share/NPI/inc`）进行兼容性修复；这些 headers 不属于本项目的 MIT License 范围。

```bash
tools/xdebug -
```

从 stdin 传入 JSON request，默认返回 xout：

```bash
printf '%s\n' '{"api_version":"xdebug.v1","action":"value.at","target":{"session_id":"case_a"},"args":{"signal":"top.clk","time":"10ns"}}' \
  | tools/xdebug -
```

同一请求需要 JSON response 时：

```bash
printf '%s\n' '{"api_version":"xdebug.v1","action":"value.at","target":{"session_id":"case_a"},"args":{"signal":"top.clk","time":"10ns"}}' \
  | tools/xdebug --json -
```

典型 xout 输出：

```text
@xdebug.value.at.v1

target:
  signal: top.clk
  time: 10ns

summary:
  value: 1
  known: true
```

也可以使用请求文件：

```bash
tools/xdebug request.json
```

### Shell 命令入口

为了在任意目录和 Claude Code 这类非交互 shell 中稳定调用，建议把仓库 `tools/` 加入 `PATH`。下面示例里的 `<xverif-root>` 表示本仓库根目录，请按本机实际路径替换；文档和 skill 中不固定记录个人机器路径。

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
xdebug -h
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | xdebug -
printf '%s\n' '{"api_version":"xdebug.v1","action":"actions"}' | xdebug --json -
xdebug request.json
```

推荐使用 `tools/xdebug` 或 `PATH` 中的 `xdebug`。

### Cluster file transport

当本机或登录机无法直接连接计算节点 TCP 端口时，不要尝试把 xdebug daemon 暴露给本机直连；使用原生 `transport:"file"`，让 xdebug daemon 通过共享文件系统交换 request/response。默认交换目录在 backend session 目录下：

```text
~/.xdebug/engine/sessions/<session_id>/transport/
```

启用方式：

```json
{
  "api_version": "xdebug.v1",
  "action": "session.open",
  "target": {
    "fsdb": "waves.fsdb"
  },
  "args": {
    "name": "wave_file",
    "transport": "file"
  }
}
```

也可以设置新建 session 的默认 transport：

```bash
export XDEBUG_TRANSPORT=file
```

file transport v2 使用明确的状态目录，不再依赖 file lock：

```text
file transport directory:
  requests/    client-published pending requests
  claims/      worker-claimed running requests
  responses/   unread responses
  done/        archived request/claim/response history
  failed/      client_timeout / expired / stale_claim / invalid_request
  tmp/         atomic write temp files
  heartbeat/   worker liveness files
```

request 先写到 `tmp/`，再 atomic publish 到 `requests/`；daemon 用 `rename()` 抢到 `claims/`；response 写到 `responses/`，client 读完后默认归档到 `done/`。过期 request、坏 request、stale claim 和 client timeout 进入 `failed/`。如果旧 session 目录里还有 `locks/`，它只是历史残留，可以忽略。

普通 file transport 请求默认等待 300 秒，可用 `XDEBUG_FILE_TRANSPORT_TIMEOUT_MS` 调整；ping/quit 默认等待 2 秒，可用 `XDEBUG_FILE_TRANSPORT_PING_TIMEOUT_MS` 调整。大窗口 `axi.analysis`、`signal.changes` 或深层 trace 展开如果确实需要更久，优先调普通请求 timeout，不要改 ping timeout。`XDEBUG_FILE_KEEP_HISTORY=1` 默认保留证据链；`XDEBUG_FILE_CLAIM_TIMEOUT_MS`、`XDEBUG_FILE_POLL_INTERVAL_MS`、`XDEBUG_FILE_MAX_JSON_BYTES`、`XDEBUG_FILE_DONE_TTL_SEC`、`XDEBUG_FILE_FAILED_TTL_SEC` 可用于高级排障和清理。

trace 类 XOUT 源码窗口默认显示有效行上下 3 行，可用 `XDEBUG_TRACE_SOURCE_CONTEXT_LINES` 调整；同文件有效行号差值小于 10 时默认合并显示，可用 `XDEBUG_TRACE_SOURCE_MERGE_THRESHOLD_LINES` 调整。

### MCP wrapper

`tools/xverif-mcp` 是基于 FastMCP SDK 的统一 MCP server。xdebug 作为设计/波形 stateful backend，通过 stdio-loop session 提供查询能力；xcov 作为 coverage stateful backend；其他 xverif 工具（xbit/xentry/xloc/xsva）以 stateless CLI adapter 方式接入。

MCP client 配置示例（direct 模式）：

```json
{
  "mcpServers": {
    "xverif": {
      "command": "<conda-env>/bin/python",
      "args": ["-m", "xverif_mcp.server"],
      "env": {
        "PYTHONPATH": "<xverif>/xverif_mcp/src:<xverif>",
        "XVERIF_HOME": "<xverif>",
        "XVERIF_MCP_BACKEND": "direct",
        "VERDI_HOME": "<verdi-install>",
        "LD_LIBRARY_PATH": "<verdi-install>/share/NPI/lib/LINUX64"
      }
    }
  }
}
```

可用 xdebug MCP tools（以 `xverif_` 前缀统一命名）：

- `xverif_debug_session_open`：打开命名 session。
- `xverif_debug_session_list`：列出 managed session；可按需包含 tombstone 或展开诊断字段。
- `xverif_debug_session_doctor`：只读诊断精确 name/session_id，不自动 reopen。
- `xverif_debug_session_close`：正常关闭并返回分层 cleanup 结果。
- `xverif_debug_session_kill`：强制清理一个精确 session；不支持 `all`。
- `xverif_debug_session_gc`：删除已确认终止的 tombstone，未确认 orphan 只报告 unresolved。
- `xverif_debug_query`：通过 loop session 调用 xdebug action。
- `xverif_debug_list_actions` / `xverif_debug_get_schema`：查询 action catalog 和 schema。
- action 统一通过 `xverif_debug_query(session_id, action, args, limits, output_format)` 调用，不暴露快捷别名。

`xverif_debug_get_schema` 默认返回 MCP 投影：结果中的
`args_schema` 和 `limits_schema` 是 query tool 内层同名参数的唯一字段合同；
`constraints` 只补充跨字段业务语义，`minimal_call` 可直接复制。
无需再查询一次 response schema；
只查看完整 response schema 时使用 `kind="response", view="response"`。

xcov 提供对称的 `xverif_cov_session_open/list/doctor/close/kill/gc`。debug/cov query 都禁止 native lifecycle action。xdebug dead loop 只使用固定 native admin path 精确 doctor/kill；xcov backend 随 loop 退出，kill 不虚构 native kill。清理部分失败会保留 tombstone，不切换 transport/backend。

#### MCP LSF backend

LSF 模式将 `XVERIF_MCP_BACKEND` 设为 `lsf`：

```json
"XVERIF_MCP_BACKEND": "lsf",
"XVERIF_LSF_SESSION_QUEUE": "interactive"
```

LSF backend 的链路是：

```text
AI MCP client
  -> xverif-mcp FastMCP server
  -> McpSessionManager
  -> LsfLauncher: bsub -I tools/xdebug --stdio-loop
```

每个 session 一个独立 LSF job（不是 router + per-session TCP endpoint 的两层架构）。不同 session 并行，同一 session 串行（request_lock）。

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `XVERIF_MCP_BACKEND=lsf` | 启用 LSF backend |
| `XVERIF_LSF_BSUB` | 覆盖 `bsub` 命令，便于站点 wrapper 或测试 fake runner |
| `XVERIF_MCP_TIMEOUT_SEC` | 单次请求超时（默认 120s） |
| `PYTHON` | 指定运行 MCP/loop wrapper 的 Python，建议使用 Python 3.11+ |
| `XVERIF_HOME` | 指向仓库根目录，便于计算节点找到 `tools/xdebug` |

本地开发可用 fake LSF 跑 smoke，不需要真实 LSF：

```bash
PYTHON=python3 XVERIF_MCP_FAKE_LSF=1 tools/xverif-lsf-doctor --fake
```

真实环境建议先跑：

```bash
PYTHON=python3 tools/xverif-lsf-doctor
```

如果用户明确说”LSF 计算节点只能集群内部 TCP，登录机不能直连计算节点端口”，MCP 场景优先用 `XVERIF_MCP_BACKEND=lsf`。如果不能使用 MCP SDK，但仍希望由 Python wrapper 维护 LSF `--stdio-loop` session，使用 `tools/xverif-loop-server` / `tools/xverif-loop-client` 和 `XVERIF_LOOP_BACKEND=lsf`。如果不用 MCP/loop wrapper、只走 xdebug 原生命令，则优先使用上面的 `transport:”file”`。

非 MCP UDS wrapper 示例：

```bash
XVERIF_LOOP_BACKEND=lsf XVERIF_LOOP_SOCKET=<repo>/tmp/xverif-loop.sock tools/xverif-loop-server

tools/xverif-loop-client --socket <repo>/tmp/xverif-loop.sock --json \
  '{"id":"1","method":"debug.session.open","params":{"name":"s0","fsdb":"waves.fsdb"}}'
```

重复调试建议先打开 session，再用 `target.session_id` 访问：

```json
{
  "api_version": "xdebug.v1",
  "action": "session.open",
  "target": {
    "daidir": "simv.daidir",
    "fsdb": "waves.fsdb"
  },
  "args": {
    "name": "case_a"
  }
}
```

同名 `session.open` 永远不会复用或替换旧 session。已有 live session 时返回 `SESSION_ID_EXISTS`；已有 stale session 时返回 `SESSION_STALE`，需要显式 `session.close` 或 `session.gc` 后再重新 open。session name 必须以英文字母开头，只能包含英文、数字和下划线，最大 64 个字符。

`session.close` 推荐使用 `target.session_id`；为兼容脚本也接受 `args.session_id` 和 `args.id`。三者都缺失时返回 `MISSING_FIELD`。

## Test Entry Points

xdebug 与全仓其它组件共享根级 catalog-driven pytest plugin；Makefile 只负责构建。

常用入口（从仓库根目录运行）：

```bash
pytest --xverif-gate fast
export XVERIF_TEST_EXECUTION_ENV=host  # 仅在已经进入沙箱外 host 后设置
pytest --xverif-gate regression -n auto
pytest --xverif-gate nightly -n auto
pytest --xverif-gate regression --xverif-suite xdebug.contract
pytest --xverif-gate nightly --xverif-suite xdebug.axi_vip
pytest --xverif-gate nightly --xverif-suite xdebug.analysis_cache_benchmark
```

在 Codex 受限沙箱中，只运行 `fast`。所有涉及 NPI、Verdi/VCS、FSDB、daidir、`session.open`、Unix domain
socket、SVT VIP 编译/仿真的入口，应在沙箱外运行，否则可能得到 license 连接失败、
UDS bind 失败或 `SESSION_UNHEALTHY: child_exited` 等环境型失败。
沙箱外 gate 应显式设置 `XVERIF_TEST_EXECUTION_ENV=host` 记录证据；该变量不提供权限提升，也不触发 fallback。

普通 gate 不生成 FSDB/daidir；先显式 prepare：

```bash
pytest --xverif-prepare all-generated
pytest --xverif-fixture-validation --xverif-all-fixtures
```

nightly 中 real LSF 是 catalog optional suite；能力缺失会在 environment snapshot 和报告中明确 SKIP。required fixture 缺失则在执行前 ERROR，不会 fallback。原 xring realdata 资源已不存在，对应 optional suite 已移除；仓库不会用小型 synthetic fixture 冒充真实大规模数据覆盖。

## Core Concepts

### 资源与 fallback

xdebug 当前只支持两类输入资源：

- `daidir`：Verdi/VCS 设计数据库，例如 `simv.daidir`。
- `fsdb`：FSDB 波形数据库，例如 `waves.fsdb`。

`target` 决定路由：

| target | 行为 |
| --- | --- |
| 仅 `daidir` | 使用设计侧能力，覆盖原 xtrace 的 driver/load/graph/path/source 等事实查询 |
| 仅 `fsdb` | 使用波形侧能力，覆盖原 xwave 的 value/event/APB/AXI/verify 等事实查询 |
| 同时有 `daidir` 与 `fsdb` | 启用 combined/debug join 能力，把波形现象连接到设计因果 |

### Session Transport：UDS、TCP 与 file

xdebug session 默认使用本机 Unix domain socket：

```json
{
  "transport": "uds"
}
```

同一台机器上的普通调试优先使用默认 UDS。只有 socket 路径不可共享、容器或 namespace 隔离导致 UDS 不可达、或确实需要跨进程边界连接 daemon 时，才显式使用 TCP。

如果问题是“本机无法连接集群计算节点 TCP 端口”，不要用 TCP 直连；改用 `transport:"file"`，让计算节点上的 daemon 通过共享 session 目录交换请求。

本机 TCP session 示例：

```json
{
  "api_version": "xdebug.v1",
  "action": "session.open",
  "target": {
    "fsdb": "waves.fsdb"
  },
  "args": {
    "name": "wave_tcp",
    "transport": "tcp",
    "bind_host": "127.0.0.1",
    "port": 0
  }
}
```

`port:0` 或省略 `port` 表示由 daemon 自动分配端口；实际 endpoint 会写入 session endpoint/registry，后续查询继续通过 `target.session_id` 复用即可。远程或跨容器场景下，`bind_host` 是 daemon listen 地址，`host` 是 client 连接时使用的地址；只有用户明确需要远程访问时才设置公网或非 loopback 地址。

file session 示例：

```json
{
  "api_version": "xdebug.v1",
  "action": "session.open",
  "target": {
    "fsdb": "waves.fsdb"
  },
  "args": {
    "name": "wave_file",
    "transport": "file"
  }
}
```

`XDEBUG_TRANSPORT=uds|tcp|file` 只影响新建 session；JSON 中显式的 `args.transport` 或 `target.transport` 优先级更高。

跨登录机和计算节点访问同一个共享路径时，`stat()` 返回的 `dev/inode` 可能不同。xdebug 只把 `dev/inode` 作为 endpoint/fingerprint 诊断信息记录，资源 freshness 判定只使用 `mtime + size`；因此这类共享挂载差异不会单独触发 session unhealthy 或自动 restart。

### JSON envelope

所有请求统一使用这个 envelope：

```json
{
  "api_version": "xdebug.v1",
  "request_id": "optional-id",
  "action": "trace.driver",
  "target": {
    "daidir": "simv.daidir",
    "fsdb": "waves.fsdb"
  },
  "args": {
    "output": {"verbose": false}
  },
  "limits": {}
}
```

### 输出控制

action 默认返回 compact summary/evidence。需要 action schema 明确定义的详细字段时使用该 action 的输出参数；大列表使用 action-specific `line_limit`，完整数据使用对应 export action。AXI transaction action 使用 `args.output.include_data:true` 展开逐 beat payload；其它 action 仅在 schema 明确声明时使用 `args.output.verbose:true`。top-level `output` 和 `output.verbosity` 不受支持。

### 常见意图到 action

| 意图 | 推荐 action | 说明 |
| --- | --- | --- |
| 统计 high/active cycles | `signal.statistics` | 有 `clock` 时做 clock-sampled 统计；无 `clock` 时做 raw value-change 统计，并返回 `sampling_mode`。 |
| 统计 counter min/max/average | `counter.statistics` | 传 `clock`、`time_range`、`vld`、`cnt`，按周期采样最多 64 bit counter；`cnt` 可用 `{hi,lo}` 拼接。 |
| 看跳变时间线 | `signal.changes` | 用 `line_limit` 限制返回 rows，`mode:"head"` 或 `"tail"` 控制方向；只要聚合时用 `aggregate_only:true`。 |
| 判断窗口内保持 0/1 | `window.verify` 或 `signal.statistics` | 不要用 `signal.changes` 的 row count 当周期数。 |
| 找 first/last occurrence | `event.find`，或 `signal.changes` + `mode:"head"/"tail"` | `event.find` 支持布尔组合、相等比较和大小比较；`signal.changes aggregate_only:true` 适合先看首末值和跳变总数。 |

`signal.changes.summary.transition_count` 为兼容保留；新代码同时返回 `returned_change_rows`、`includes_initial_value`、`actual_transition_count` 和 `semantic_note`，优先读这些字段判断语义。

`signal.statistics` 的 clock 模式对多 bit 信号用 bit-string/value object 返回 `first`、`final`、`min`、`max`，避免宽信号被整数截断。

### 详细输出与限制

只有 action-specific schema 声明的输出参数才能展开详细字段。以下是支持 `verbose` 的 action 通用示例；AXI transaction action 改用 `output.include_data`：

```json
{
  "args": {
    "output": {"verbose": true},
    "line_limit": 100,
    "max_items": 20,
    "max_examples": 5
  },
  "limits": {
    "max_rows": 1000,
    "max_events": 1000,
    "max_samples": 1000000
  }
}
```

### TimeSpec

波形相关动作的时间字段接受 TimeSpec 字符串。常见形式：

```text
100ns
10us
@deadlock
@deadlock-20ns
@deadlock+5ns
@deadlock-10cycle(top.clk)
@deadlock+5posedge(top.clk)
```

绝对时间支持 `us`、`ns`、`ps`、`fs`。使用 cursor 时，优先让 xdebug 解析 `@name` 和 cycle offset，不要在 agent 里自己重算波形时间。

## Main Workflows

### 设计因果：driver / load

先用外部 `rg` 或源码索引找候选信号名，再把精确 RTL path 交给 xdebug 查询。

查询 driver：

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.driver",
  "target": {"daidir": "simv.daidir"},
  "args": {"signal": "top.u.ready"}
}
```

查询 load：

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.load",
  "target": {"daidir": "simv.daidir"},
  "args": {"signal": "top.u.ready"}
}
```

### 波形取证：value / batch / verify

查询单点值：

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {"session_id": "case_a"},
  "args": {
    "signal": "top.u.valid",
    "time": "100ns",
    "format": "hex"
  }
}
```

批量查询同一时间的多个信号：

```json
{
  "api_version": "xdebug.v1",
  "action": "value.batch_at",
  "target": {"session_id": "case_a"},
  "args": {
    "time": "100ns",
    "signals": ["top.u.valid", "top.u.ready", "top.u.data"],
    "format": "hex"
  }
}
```

`value.batch_at` 对部分信号缺失仍返回整体 ok，并在 `summary.missing_by_reason` 和每个 row 的 `status/reason/suggested_next_actions` 里说明原因。常见状态包括 `signal_not_found`、`not_dumped_or_unreadable`、`time_out_of_range`、`unsupported_format`。

`value.at` / `value.batch_at` 的 `clock` 是可选参数。省略时直接读取 `time` 对应的
FSDB 最终值并返回 `sampling_mode:"raw_time"`；传入时保持原有 clock-sampled 行为并
返回 `sampling_mode:"clock_sampled"` 和 `clock_context`。无 `clock` 时传 `edge` 或
`sample_point` 会返回 `INVALID_ARGUMENT`。默认显示为十六进制，hex/bin/decimal 值
分别使用 `'h` / `'b` / `'d` 前缀。

查询点已经出现 X 时，可在 combined session 里一键反向追踪：

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.x",
  "target": {"session_id": "case_a"},
  "args": {"signal": "top.u.data", "time": "100ns"},
  "limits": {"max_depth": 8, "max_nodes": 256, "max_time_steps": 128, "max_chains": 8}
}
```

`trace.x` 会先证明查询值是否含 X，再按 DFS 同等追踪传播时刻含 X 的 RHS 与 control，
并穿过 module port、interface/modport。每个分支的每一跳都会重新定位该信号连续 X
区间的起点，因此时间可以多次向更早位置推进。仅由
port/interface/modport/ref alias 路线不同造成的重复 chain 会先归并；
`data.chains` 和 `summary.chain_count` 只返回最终有效语义链。`limits.max_chains`
默认 8，并在归并后应用；超额的真实语义分支保留在
`pending_x_dependencies`。因 `max_depth` 停止时，`data.depth_frontiers` 和
`suggested_next_actions` 会给出从 frontier 续查或提高深度重跑所需的完整参数。

unpacked/聚合数组可显式请求结构化显示：

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {"session_id": "case_a"},
  "args": {
    "signal": "top.u.array_sig",
    "time": "100ns",
    "format": "array_indexed"
  }
}
```

返回会保留 raw value，并按 FSDB 打印顺序给出 `elements` 和 `by_index`。普通 scalar 请求该格式时返回 `unsupported_format` 诊断。

需要把波形值交给 xbit 切字段时，显式传 `slice_hint`：

```json
{
  "api_version": "xdebug.v1",
  "action": "value.at",
  "target": {"session_id": "case_a"},
  "args": {
    "signal": "top.u.data",
    "time": "100ns",
    "format": "hex",
    "slice_hint": {"chunk_width": 32, "count": 4}
  }
}
```

响应里的 `data.xbit_hints.commands[]` 是可直接用 `tools/xbit` 执行的确定性 slice 命令。

验证条件：

```json
{
  "api_version": "xdebug.v1",
  "action": "verify.conditions",
  "target": {"session_id": "case_a"},
  "args": {
    "time": "100ns",
    "conditions": [
      {"signal": "top.u.valid", "op": "==", "value": "1"},
      {"signal": "top.u.ready", "op": "==", "value": "0"}
    ]
  }
}
```

### 生成 nWave signal.rc：rc.generate

`rc.generate` 从 JSON 配置生成 nWave `signal.rc`。配置中信号路径使用点分层次，xdebug 会校验信号存在于 FSDB，并在生成 rc 时转换成 `/top/u/sig` 风格路径。group 配置不接受 `expanded`，生成的 `addGroup` / `addSubGroup` 固定不带 `-e`，subgroup 递归保持支持。该 action 只生成 signal list/view rc，不写 `openDirFile` / `activeDirFile`，打开 FSDB 仍由 nWave 会话或外部脚本负责。语法背景见 [signal_rc_syntax.md](../doc/signal_rc_syntax.md)。
对于 `top.u.bus[15:0]` 这类 slice，校验会先查完整路径；若 FSDB 不接受 slice handle，则回退校验 base signal `top.u.bus` 是否存在。

请求：

```json
{
  "api_version": "xdebug.v1",
  "action": "rc.generate",
  "target": {"session_id": "case_a"},
  "args": {
    "config_path": "wave_view.json",
    "output": {"path": "signal.rc"}
  }
}
```

配置示例：

```json
{
  "file_time_scale": "1ns",
  "cursor": "120ns",
  "main_marker": "120ns",
  "zoom": {"begin": "0ns", "end": "500ns"},
  "groups": [
    {
      "name": "Analog",
      "signals": [
        {
          "path": "top.u_adc.sample[11:0]",
          "waveform": "analog",
          "height": 40,
          "analog": {"display_style": "pwl", "grid_x": true, "grid_y": true}
        }
      ]
    },
    {
      "name": "AXI",
      "subgroups": [
        {
          "name": "AW",
          "signals": ["top.u_axi.awvalid", "top.u_axi.awready"],
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
    {"name": "reset_done", "time": "120ns", "color": "ID_YELLOW5", "linestyle": "solid"}
  ]
}
```

`windowTimeUnit` 不可配置，生成文件始终以 `windowTimeUnit 1ns` 作为第一条非注释语句。`user_markers[].time` 必须带单位输入，生成时按 ns 归一化并移除后缀。

### 协议与事件：event / APB / AXI

`stream.query`、`stream.export` 和动态 `stream.validate` 使用同一 repository base cache。
`args.cache_scope` 可为 `full` 或 `range`，默认 `full`；它只控制 base 扫描与缓存范围，
不改变响应 `time_range`。一次性窄窗口可显式使用 `range`；重复查询、跨 action 复用或
多个窗口优先使用 `full`。同语义 full 已存在时 range 直接复用 full；full 成功发布后
清除同语义 range entries。达到 hard limit 时返回 `ANALYSIS_MEMORY_LIMIT_EXCEEDED`，
不会静默缩小范围或切换 backend。静态 `stream.validate` 不接受 `cache_scope`。

AXI 的 AW 与 W 是独立通道，`axi.*` 会处理 `aw_before_w`、`same_cycle` 和
`w_before_aw`，不能假设每个 W handshake 旁边都有 AW handshake。首次
`axi.query/analysis/pair/timeline/outlier/export` 会为同一 config 建立并缓存唯一
canonical transaction result，后续 action（包括 export）复用该结果，不再重复扫描
FSDB。`axi.analysis` 的 `latency`、`osd`、`pending` 分别表示完成事务延迟、
outstanding 统计和扫描结束仍未闭合的事务；`summary.full_scan_count` 应为 1。

`axi.query` 可按 transaction selector 查询，也可用精确握手锚点查询：

```json
{
  "api_version": "xdebug.v1",
  "action": "axi.query",
  "target": {"session_id": "case_a"},
  "args": {
    "name": "axi0",
    "query": {"channel": "w", "handshake_time": "110ns"},
    "output": {"include_data": false}
  }
}
```

transaction 按 `address/data/response` 分组。address 和 data 返回 `valid_begin_time`；
data 默认只返回首、末 handshake 时间，`include_data:true` 时才增加逐 beat `beats[]`。

`axi.config.load` 在保存前解析全部信号、检查控制/ID/data-strobe 位宽关系，并确认
请求的 clock edge 在 FSDB 中存在。写事务同时返回 AW/首末 W/B 时间、
`phase_order`、beat count 和 B response dependency 诊断。

`event.find` 查 first/last/all occurrence。已有 event config 时传 `name`；临时查询可直接传 `expr` + `clk` + `signals`，不会留下持久 event config。表达式支持布尔组合和数值比较，可直接写 counter 阈值，例如 `wait_count >= 512`：

```json
{
  "api_version": "xdebug.v1",
  "action": "event.find",
  "target": {"session_id": "case_a"},
  "args": {
    "expr": "valid && !ready && wait_count >= 512",
    "clk": "top.clk",
    "signals": {
      "valid": "top.u.valid",
      "ready": "top.u.ready",
      "wait_count": "top.u.dbg_wait_count"
    },
    "time_range": {
      "begin": "0ns",
      "end": "100us"
    },
    "mode": "last"
  }
}
```

`mode` 可为 `first`、`last` 或 `all`。`last` 会按 `scan_limit` 或 `limits.max_rows` 扫描后返回最后一个匹配点。

对 valid/ready 类协议，合法 idle 或 backpressure 窗口不等价于 bug。优先用 valid-qualified `event.find`、`signal.changes` 和 `window.verify` 证明超时路径；`detect_abnormal` 只适合作为粗粒度 smoke。payload knownness 建议检查 leaf field，不要直接把 packed struct aggregate 的 unknown finding 当作最终结论。

导出事件默认只返回聚合信息和少量 examples。完整 rows 必须显式请求：

```json
{
  "api_version": "xdebug.v1",
  "action": "event.export",
  "target": {"session_id": "case_a"},
  "args": {
    "name": "if0",
    "expr": "valid && !ready",
    "time_range": {
      "begin": "0ns",
      "end": "100us"
    }
  },
  "limits": {
    "max_events": 1000
  }
}
```

需要 event rows：

```json
{
  "api_version": "xdebug.v1",
  "action": "event.export",
  "target": {"session_id": "case_a"},
  "args": {
    "name": "if0",
    "expr": "valid && ready",
    "time_range": {
      "begin": "0ns",
      "end": "100us"
    },
    "line_limit": 1000
  }
}
```

APB/AXI 查询应先加载对应配置，再执行 `apb.query`、`axi.query` 或分析动作。compact 默认优先返回 error/slow/high-latency/outstanding finding，而不是所有正常 transaction/beat。

APB 配置的基础字段为 `paddr/pwdata/prdata/pwrite/penable/psel/clk/rst_n`。
真实 APB3/APB4 波形建议同时配置可选的 `pready` 和 `pslverr`：

- 配置 `pready` 后，xdebug 只在 access phase 完成时记录一笔 transfer，
  wait-state 周期不会被重复计数。
- 配置 `pslverr` 后，transaction 输出包含 `has_error`。
- 旧配置不带这两个字段仍可使用，但不能可靠区分 wait-state 或报告 slave
  error response。

同一 session 和同一 APB 语义配置的 query、statistics、transfer_window 与 cursor
复用一次完整 FSDB 扫描；地址查询按需构建独立索引。分析缓存达到 hard limit 时返回
明确错误，不会静默缩小时间范围或切换数据源。

### 联合定位：trace.active_driver

当同时有 `daidir` 和 `fsdb` 时，用 `trace.active_driver` 把“某时刻波形值”连接到“当前生效的设计驱动证据”：

```json
{
  "api_version": "xdebug.v1",
  "action": "trace.active_driver",
  "target": {
    "daidir": "simv.daidir",
    "fsdb": "waves.fsdb"
  },
  "args": {
    "signal": "top.u.ready",
    "requested_time": "120ns",
    "include_control": true
  }
}
```

推荐 debug flow：

1. 用 `value.at` 或 `event.export` 找到异常时间。
2. 用 `value.batch_at` 取相关握手、状态、数据寄存器。
3. 用 `trace.driver` 或 `trace.load` 查设计依赖。
4. 如果两类资源都有，用 `trace.active_driver` 给出当前时间点的生效驱动。
5. 只有当 compact 证据不足且 schema 支持时，再使用该 action 的详细输出参数（AXI transaction 为 `args.output.include_data:true`，其它 action 常见为 `verbose:true`）；大结果优先 export。

## 错误、截断与证据

常见错误码：

- `MISSING_FIELD`
- `UNKNOWN_ACTION`
- `INVALID_TARGET`
- `SESSION_NOT_FOUND`
- `SIGNAL_NOT_FOUND`
- `TIME_SPEC_INVALID`
- `WAVE_QUERY_FAILED`
- `INTERNAL_ENGINE_FAILED`
- `INTERNAL_ERROR`

所有脚本必须先检查 `ok`。失败时读取 `error.code` 和 `error.message`，不要解析 stderr 或人类文本。

`meta.truncated=true` 表示结果被主动截断。优先缩小查询范围或提高 action-specific `line_limit`；需要完整结果时使用对应 export action。

compact payload 优先返回 evidence，而不是大段源码：

```json
{
  "evidence": {
    "file": "rtl/foo.sv",
    "line": 123
  }
}
```

## 日志与排障

xdebug 默认静默记录结构化日志。日志只写文件，不打印到 stdout/stderr，不改变 JSON API 响应；日志写入失败也不会影响 action 执行。

主要位置：

- public action：`~/.xdebug/sessions/<session_id>/logs/actions.ndjson`
- stdio-loop 协议：`~/.xdebug/sessions/<session_id>/logs/stdio.ndjson`
- 无 session 或解析失败：`~/.xdebug/sessions/adhoc/logs/actions.ndjson`
- engine lifecycle：`~/.xdebug/engine/sessions/<hashed-session>/logs/lifecycle.ndjson`
- engine transport：`~/.xdebug/engine/sessions/<hashed-session>/logs/transport.ndjson`
- engine crash marker：`~/.xdebug/engine/sessions/<hashed-session>/logs/crash_marker.ndjson`
- NPI startup diagnostic：`~/.xdebug/engine/sessions/<hashed-session>/logs/npi_startup.log`
- log health：各 `logs/` 目录下的 `log_health.ndjson`
- MCP session：`~/.xverif/mcp/sessions/<alias>/session.ndjson`
- MCP stdio：`~/.xverif/mcp/sessions/<alias>/stdio.ndjson`
- MCP LSF：`~/.xverif/mcp/sessions/<alias>/lsf.ndjson`

每行都是一个 JSON event，常见字段包括 `ts`、`event_id`、`trace_id`、`request_id`、`layer`、`component`、`session_id`、`action`、`phase`、`elapsed_ms`、`ok`、`context`。成功 action 默认只记录摘要、路由、耗时和 `summary/meta`；失败 action 会额外记录裁剪后的 request/response。超大 compact payload 会写入 `logs/*_payload/` sidecar，主日志保留路径和 hash。

engine 启动时会在 `lifecycle.ndjson` 写入 `env.snapshot`，记录 hostname、cwd、argv0、构建时间、EDA/LSF 环境摘要，以及 `LD_LIBRARY_PATH` hash；路径字段受 `XDEBUG_LOG_PATH_MODE` / `XDEBUG_LOG_REDACT` 控制。license 只记录 `SNPSLMD_LICENSE_FILE`、`LM_LICENSE_FILE` 的 presence，不记录值。`npi_init()`、`npi_load_design()`、`npi_fsdb_open()` 启动阶段的 stdout/stderr 写入权限为 `0600` 的 `npi_startup.log`；失败分别返回 `NPI_INIT_FAILED`、`NPI_LOAD_DESIGN_FAILED`、`NPI_FSDB_OPEN_FAILED` 和对应 `failure_phase`。普通 log bundle 包含该原始日志，redacted bundle 将其排除。

辅助命令：

```bash
xdebug log doctor --session <id> --json
xdebug log tail --session <id> --lines 40
xdebug log bundle --session <id> --out debug_bundle.tgz
xdebug log bundle --session <id> --out debug_bundle.redacted.tgz --redact
```

可选环境变量：

- `XDEBUG_ANALYSIS_CACHE_MAX_BYTES`：engine analysis cache soft budget，默认
  `1073741824`（1 GiB）；`0` 关闭主动 soft LRU，但 hard limit 仍生效。
- `XDEBUG_ANALYSIS_CACHE_HARD_MAX_BYTES`：analysis cache hard limit，默认
  `2147483648`（2 GiB），必须为正整数且不小于 soft budget。
- 两个 cache 变量只在 engine 启动时严格解析一次；空字符串、负数、空白/尾随字符、溢出、
  hard=0 或 soft>hard 都会令 session 启动失败，不会静默使用默认值。
- AXI query/analysis/cursor/export 与四个 AXI AI action 在同一 engine 内复用一份
  canonical `AxiResult`；address、ID 和 handshake index 按需建立。达到 hard limit 时
  action 返回 `ANALYSIS_MEMORY_LIMIT_EXCEEDED` 及预算/key 摘要，不会自动缩小时间范围、
  切换 backend 或改用离线工具。
- `XDEBUG_LOG_PATH_MODE=full|basename|hash` / `XDEBUG_LOG_REDACT=1`：控制日志路径字段脱敏。
- `XDEBUG_LOG_MAX_BYTES` / `XDEBUG_LOG_MAX_FILES`：启用单文件大小滚动。
- `XVERIF_MCP_LOG_DIR`：覆盖 MCP structured log 根目录，默认 `~/.xverif/mcp`。
- `XVERIF_LOOP_LOG_DIR`：覆盖非 MCP UDS wrapper structured log 根目录，默认 `~/.xverif/loop-wrapper`。

定位工具问题时推荐顺序：

1. 先看 public `actions.ndjson`，确认 action、session、路由和最终 error。
2. 如果 stdout 协议、ready 前退出、invalid JSON 或 MCP envelope 异常，看 `stdio.ndjson`。
3. 如果是 `session.open`、`SESSION_UNHEALTHY` 或 `INTERNAL_ENGINE_FAILED`，再看 engine `lifecycle.ndjson`；NPI init/load/open 失败继续查看 `npi_startup.log`。
4. 如果怀疑 socket/TCP/ping/daemon 连接问题，看 `transport.ndjson`。
5. 如果是 MCP/LSF 启动、ready timeout、stdout pollution 或 cleanup 问题，看 `~/.xverif/mcp/sessions/<alias>/*.ndjson`。
6. 如果是非 MCP UDS wrapper 的请求解析、socket、LSF 或 cleanup 问题，看 `~/.xverif/loop-wrapper/logs/uds.ndjson` 和 `~/.xverif/loop-wrapper/sessions/<alias>/*.ndjson`。

日志相关 focused 回归入口：

```bash
pytest --xverif-gate regression --xverif-suite xdebug.session
```

## 参考文档

- [docs/JSON_API.md](docs/JSON_API.md)：JSON envelope、target、输出策略。
- [docs/PAYLOAD_COMPACT.md](docs/PAYLOAD_COMPACT.md)：业务 payload 压缩契约。
- [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)：面向 agent 的最短调试指南。
- [../skills/xverif/SKILL.md](../skills/xverif/SKILL.md)：xverif 能力路由 source-of-truth。
- [../skills/xverif/references/capabilities/xdebug.md](../skills/xverif/references/capabilities/xdebug.md)：按一次 debug 流程组织的 xdebug 主参考。
- [../skills/xverif/references/generated/xdebug-actions.md](../skills/xverif/references/generated/xdebug-actions.md)：自动生成的全量 action 索引。
- [../skills/xverif-admin/SKILL.md](../skills/xverif-admin/SKILL.md)：MCP、transport 和 session 运维。
- [../skills/xverif/references/xdebug/json-api.md](../skills/xverif/references/xdebug/json-api.md)：CLI JSON envelope API 速查。
- [../skills/xverif/references/xdebug/response-fields.md](../skills/xverif/references/xdebug/response-fields.md)：CLI 响应字段字典。
- [../skills/xverif/references/xdebug/recipes.md](../skills/xverif/references/xdebug/recipes.md)：CLI 常见 debug workflow。
- [../skills/xverif-admin/references/mcp/lsf.md](../skills/xverif-admin/references/mcp/lsf.md)：MCP LSF backend 说明。
- [../skills/xverif-admin/references/sdk-free-loop/uds-jsonl.md](../skills/xverif-admin/references/sdk-free-loop/uds-jsonl.md)：SDK-free UDS JSONL 说明。
- [../skills/xverif/references/xdebug/rc-generate.md](../skills/xverif/references/xdebug/rc-generate.md)：CLI nWave `signal.rc` 生成说明。
