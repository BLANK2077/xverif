# xverif MCP

`xverif_mcp` 是 `tools/xverif-mcp` 的 Python 实现，基于 FastMCP SDK。它是 xverif 工具体系统一 MCP 入口：

- **xdebug**：stateful backend，通过 `tools/xdebug --stdio-loop` 提供设计/波形查询能力，支持 direct/LSF 模式。
- **xcov**：stateful backend，通过 `tools/xcov --stdio-loop` 提供 VCS/Verdi coverage database 查询能力，支持 direct/LSF 模式。
- **xbit / xentry / xloc**：stateless in-process adapter，调用各工具公开 Python contract。
- **xsva**：stateless CLI adapter，只调用 `tools/xsva` 公开 CLI；JSON 按公开合同校验，command-specific XOUT 领域文本原样传递，不导入 private serializer。

xdebug/xcov direct 和 LSF 共用 stdio-loop session manager，只在 `Launcher` 层分离。每 session 独立进程，同 session 的 query 通过独立 request lane 串行，多 session 可并行；生命周期状态锁不跨越阻塞的 backend request。

阻塞 query 不会阻塞 recovery lane：`kill` 会先原子摘除 loop handle，再终止进程，并按 backend 能力通过独立 fixed native admin path 完成条件清理；旧 query 的迟到异常不能覆盖最终 lifecycle 状态。普通 `close` 若 request lane 正忙，会立即返回可重试的 `SESSION_BUSY` 并保留 session；`doctor` 不等待 busy lane，xdebug 改走 fixed native admin path，无法独立探测的 backend 则明确报告 health unknown。

MCP 层保持轻量：它只负责启动/终止 `tools/xdebug --stdio-loop` 或
`tools/xcov --stdio-loop` 进程、维护单一 canonical `session_id` 索引、转发 JSON request、
处理 direct/LSF transport cleanup。设计/波形 session 状态由 xdebug 管理；
coverage database session、VDB/NPI handle、scope/cache/query 状态由 xcov 管理。

## Architecture

```text
                         +------------------------------+
                         |          MCP clients         |
                         | Claude Code / IDE / agents   |
                         +---------------+--------------+
                                         |
                                         | MCP stdio
                                         v
                         +------------------------------+
                         |       xverif_mcp server      |
                         | FastMCP tools / schemas      |
                         | output file handling         |
                         +---------------+--------------+
                                         |
             +---------------------------+---------------------------+
             |                           |                           |
             v                           v                           v
+-------------------------+  +-------------------------+  +-------------------------+
| xdebug tool adapter     |  | xcov tool adapter       |  | stateless adapters      |
| debug session/query     |  | cov session/query       |  | xbit/xentry/xloc/xsva   |
+------------+------------+  +------------+------------+  +------------+------------+
             |                            |                           |
             | stateful stdio-loop        | stateful stdio-loop       | in-process
             v                            v                           v
+-------------------------+  +-------------------------+  +-------------------------+
| McpSessionManager       |  | McpSessionManager       |  | Python APIs / CLIs      |
| alias/default mapping   |  | alias/default mapping   |  | no persistent session   |
| request_lock per sess   |  | request_lock per sess   |  +-------------------------+
+------------+------------+  +------------+------------+
             |                            |
             | direct or LSF launcher     | direct or LSF launcher
             v                            v
+-------------------------+  +-------------------------+
| tools/xdebug            |  | tools/xcov              |
| --stdio-loop frontend   |  | --stdio-loop frontend   |
+------------+------------+  +------------+------------+
             |                            |
             v                            v
+-------------------------+  +-------------------------+
| xdebug unified engine   |  | xcov backend            |
| daidir / FSDB sessions  |  | VDB coverage sessions   |
+-------------------------+  +-------------------------+
```

## 环境要求

| 组件 | 要求 |
|---|---|
| GCC | **5.0+** |
| Python | **3.11+**（`pip install "mcp[cli]"`） |
| Verdi | 当前基于 **V-2023.12-SP2** 开发与测试 |
| NPI | 随 Verdi 版本不同可能存在 API 参数差异 |

> 如果使用其他 Verdi 版本遇到编译或运行时 NPI 兼容性问题，可让 AI agent 根据编译错误和 NPI 头文件（`$VERDI_HOME/share/NPI/inc`）进行兼容性修复。

## 入口

运行时可作为独立包安装；测试门禁基础设施 `xverif-testinfra` 不再携带 MCP
运行时代码：

```bash
pip install ./xverif_mcp
xverif-mcp
```

仓库内运行时仍需设置 `XVERIF_HOME=<xverif 仓库根目录>`，使 stateless adapter
及 `tools/xdebug`、`tools/xcov` 能定位同一份工具源码和可执行入口。

```bash
tools/xverif-mcp
tools/xverif-lsf-doctor
tools/xdebug_lsf
tools/xcov_lsf
tools/xverif_lsf_env_capture
```

`tools/xdebug_lsf` / `tools/xcov_lsf` 是不依赖 MCP SDK 的单文件入口，只用于
“没有 MCP 且必须经 LSF”的场景。它们分别接受与原生 xdebug/xcov 完全相同的
request envelope，透明托管内部 UDS manager 与 LSF stdio-loop；用户不启动
server/client、不指定 socket，也不传 `--stdio-loop`。没有 LSF 限制时直接使用
`tools/xdebug` / `tools/xcov`，无需 Python wrapper。

两个 SDK-free 入口会默认检查入口同目录的 `xverif_lsf.env.json`。可先在已经
配置好 EDA、license 和 LSF 的终端运行 `tools/xverif_lsf_env_capture` 生成该
文件；随后 wrapper 用配置覆盖继承环境，并仅在 SDK-free 提交中加入
`bsub -env all`。计算节点会在启动 native stdio-loop 前校验环境指纹，避免
登录节点配置未完整传到 LSF job。MCP direct/LSF backend 不读取这个文件，
不启用 `-env all` 或环境指纹合同。

## MCP 配置

### Claude Code

在项目根目录创建 `.mcp.json`（与 `.git/` 同级，**不是** `.claude/` 目录下）。

**direct 模式：**

```json
{
  "mcpServers": {
    "xverif": {
      "type": "stdio",
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

**LSF 模式：**

```json
{
  "mcpServers": {
    "xverif": {
      "type": "stdio",
      "command": "<conda-env>/bin/python",
      "args": ["-m", "xverif_mcp.server"],
      "env": {
        "PYTHONPATH": "<xverif>/xverif_mcp/src:<xverif>",
        "XVERIF_HOME": "<xverif>",
        "XVERIF_MCP_BACKEND": "lsf",
        "XVERIF_LSF_SESSION_QUEUE": "interactive",
        "VERDI_HOME": "<verdi-install>",
        "LD_LIBRARY_PATH": "<verdi-install>/share/NPI/lib/LINUX64",
        "LSF_ENVDIR": "<lsf-install>/conf",
        "LSF_BINDIR": "<lsf-install>/bin",
        "LSF_LIBDIR": "<lsf-install>/lib",
        "LSF_SERVERDIR": "<lsf-install>/etc",
        "PATH": "<你的完整 PATH>",
        "SNPSLMD_LICENSE_FILE": "<synopsys-license>",
        "LM_LICENSE_FILE": "<cadence-license>",
        "MGLS_LICENSE_FILE": "<mentor-license>",
        "CDS_LIC_FILE": "<cadence-license>",
        "CDS_LIC_ONLY": "1",
        "DW_WAIT_LICENSE": "1"
      }
    }
  }
}
```

> **环境继承**：由 IDE 或客户端启动的 MCP server 不一定继承当前交互 shell 的配置。请在客户端的 MCP `env` 中显式配置站点必需变量；server 启动工具子进程时使用自己实际获得的环境。LSF 作业还受站点提交策略影响，`PATH` 必须能找到 `bsub`、`bkill`。MCP 不读取 SDK-free 的 `xverif_lsf.env.json`。

如果 FSDB/daidir 较大、LSF 排队或 Verdi/NPI 初始化较慢，配置 MCP 时也建议在
`.mcp.json` 的 `env` 中显式提高 timeout。MCP 层主要看
`XVERIF_MCP_STARTUP_TIMEOUT_SEC`、`XVERIF_MCP_REQUEST_TIMEOUT_SEC`；
xdebug backend session 启动等待主要看 `XDEBUG_SESSION_START_TIMEOUT_SEC`，
session 空闲最长存活时间看 `XDEBUG_SESSION_IDLE_TIMEOUT_SEC`（默认 86400s）。
这些变量必须写进 MCP server 的 `env`，只在外层 shell 里 `export` 通常不会生效。

```jsonc
"env": {
  "XVERIF_MCP_STARTUP_TIMEOUT_SEC": "300",
  "XVERIF_MCP_REQUEST_TIMEOUT_SEC": "900",
  "XDEBUG_SESSION_START_TIMEOUT_SEC": "300",
  "XDEBUG_SESSION_IDLE_TIMEOUT_SEC": "86400"
}
```

替换说明：
- `<conda-env>`：安装了 `mcp[cli]` 的 Python 3.11 环境路径
- `<xverif>`：xverif 仓库根目录
- `<verdi-install>`：Synopsys Verdi 安装根目录
- `<lsf-install>`：LSF 安装根目录

`XVERIF_MCP_BACKEND` 可选值：
- `direct`：本机启动 `tools/xdebug --stdio-loop` 或 `tools/xcov --stdio-loop`
- `lsf`：通过 `bsub -I tools/<backend> --stdio-loop` 提交到 LSF

每个 managed xdebug/xcov session 对应一个独立 stdio-loop 进程；LSF 模式下也对应一个
独立 interactive job。xcov native loop 本身只允许一个 live VDB session，多 VDB 并发由
manager 启动多个 loop/job 实现。

LSF queue/resource 的解析优先级固定为 session open 显式参数、
`XVERIF_LSF_SESSION_QUEUE`/`XVERIF_LSF_SESSION_RESOURCE`、最后 queue 默认
`interactive`（resource 默认省略）。session record 始终包含 `scheduler`，分别发布
`requested/effective/submitted` queue/resource、job name/id 和
`submitted|ready|startup_timeout|startup_rejected|closed|cleanup_partial` 状态；这些核心调度
事实不要求 `verbose=true`。已识别的 bsub job submission 与 interactive scheduler framing
不会进入 backend JSONL 队列，未知非 JSON stdout 仍 fail-closed。queue/resource 的环境值
和 open 显式值都必须是无首尾空白的非空字符串，禁止记录了 effective 值却在 argv 中静默
省略 `-q/-R`。

### 通用参数

所有 MCP tool 始终公开以下可选参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `xverif_output_path` | `str \| None` | `None` | 指定文件路径时，tool 响应会额外写入该文件；相对路径基于 MCP 进程工作目录，绝对路径直接使用；父目录必须已存在 |
| `xverif_output_append` | `bool` | `False` | True 为追加写入，False（默认）为覆盖写入 |

示例：
```python
# 文件写入 MCP server 工作目录；也可显式使用绝对路径
xverif_cov_query(action="code_coverage.holes", args={...},
                 xverif_output_path="holes.json")

# 追加模式
xverif_debug_query(session_id="case_a", action="value.at", args={...},
                   xverif_output_path="wave.log",
                   xverif_output_append=True)
```

写文件是该调用的一部分；写入失败返回 `OUTPUT_WRITE_FAILED`，调用方不得把它当作完整成功；序列化失败返回 `OUTPUT_SERIALIZATION_FAILED`。

### 批量执行：`xverif_batch`

`xverif_batch` 允许 AI 将多个 tool 请求写入 NDJSON 文件，一次提交批量串行执行，
结果写入另一个 NDJSON 文件。适合需要按序执行 session.open → query → session.close
的场景。

每一条非空 NDJSON 行必须是带 string `tool` 和 object `args` 的 JSON object。格式错误行不会执行 tool，会在结果中写入带 `line_number` 的失败记录，然后继续处理后续行。

batch 在执行任何 tool 前冻结完整输入，并检查输入字节数和非空请求数。输入与输出若通过同一路径、
symlink 或 hardlink 指向同一 filesystem object，会返回 `BATCH_INPUT_OUTPUT_SAME_FILE`。输出使用
create-new 合同：目标必须不存在，所有结果先写入同目录 staging，检查输出字节预算并 fsync 后再
no-clobber 发布；超预算、写入失败或并发冲突都不会覆盖旧文件或发布部分 NDJSON。

**注意嵌套 args**：`xverif_debug_query` / `xverif_cov_query` 自身有 `args` 参数，
在 batch 行中需要再嵌套一层：
```jsonl
{"tool":"xverif_debug_query","args":{"session_id":"case_a","action":"value.at","args":{"signal":"top.clk","time":"10ns"}}}
```

`xverif_debug_query.session_id` 按 canonical action resource contract 条件提供：design/waveform/combined/any variant 必须提供；`requires:none` variant 禁止提供并走原生 one-shot。`expr.normalize` 的 `expr` 分支无 session，`signal` 分支要求 design session。

resource-free one-shot 支持 `xout` 和 `json`；`envelope` 只用于 managed stdio-loop。默认 `output_format:"xout"` 原样保留 native 工具的 token-efficient 领域文本，MCP adapter 不反解析、不重编码，也不添加 `XOUT_BEGIN/XOUT_END`。只有稳定字段编程、schema 校验、结构化持久化、确定性机器比较或用户明确要求时才选 JSON。

`xverif_cov_query` 的限制与 artifact 配置放在 action 内层 `args.limits` / `args.output`；`output_format` 只选择 MCP 返回格式，不写入 native `xcov.v1` request。

**1. 生成批量请求文件（bash inline）：**

```bash
cat > <repo>/tmp/batch_requests.ndjson << 'EOF'
{"tool": "xverif_cov_session_open", "args": {"name": "uart0", "vdb": "/path/to/merged.vdb"}}
{"tool": "xverif_cov_query", "args": {"session_id": "uart0", "action": "code_coverage.holes", "args": {"metrics": ["line"], "limits": {"max_items": 5}}, "output_format": "json"}}
{"tool": "xverif_cov_query", "args": {"session_id": "uart0", "action": "code_coverage.holes", "args": {"metrics": ["toggle"], "limits": {"max_items": 5}}, "output_format": "json"}}
{"tool": "xverif_cov_session_close", "args": {"session_id": "uart0"}}
EOF
```

或 Python inline：

```python
import json
requests = [
    {"tool": "xverif_cov_session_open", "args": {"name": "uart0", "vdb": "/path/to/merged.vdb"}},
    {"tool": "xverif_cov_query", "args": {"session_id": "uart0", "action": "code_coverage.holes",
        "args": {"metrics": ["line"], "limits": {"max_items": 5}}, "output_format": "json"}},
    {"tool": "xverif_cov_session_close", "args": {"session_id": "uart0"}},
]
with open("<repo>/tmp/batch_requests.ndjson", "w") as f:
    for req in requests:
        f.write(json.dumps(req) + "\n")
```

**2. 提交执行：**

```
xverif_batch(batch_file="<repo>/tmp/batch_requests.ndjson", output_file="<repo>/tmp/batch_results.ndjson")
```

**3. 查看结果：**

```python
import json
with open("<repo>/tmp/batch_results.ndjson") as f:
    for line in f:
        r = json.loads(line)
        status = "OK" if r["ok"] else f"FAIL: {r['error']}"
        print(f"[{status}] {r['tool']} ({r['elapsed_ms']}ms)")
```

输出格式：每行 `{"tool": "...", "ok": true/false, "elapsed_ms": 123, "error": null}`。
格式错误行 `tool` 为 `null`，`error` 包含错误原因。

### 通用 MCP client

```json
{
  "mcpServers": {
    "xverif": {
      "command": "<conda-env>/bin/python",
      "args": ["-m", "xverif_mcp.server"],
      "env": {
        "PYTHONPATH": "<xverif>/xverif_mcp/src:<xverif>",
        "XVERIF_HOME": "<xverif>"
      }
    }
  }
}
```

Claude Code 启动时自动加载项目根目录下的 `.mcp.json`，无需额外配置。

## 运行链路

```text
AI MCP client
  -> xverif-mcp FastMCP server
  -> XverifDebugAdapter (xdebug)
       -> McpSessionManager
       -> DirectLauncher:  tools/xdebug --stdio-loop  (direct)
       -> LsfLauncher:     bsub -I tools/xdebug --stdio-loop  (LSF)
  -> XverifCoverageAdapter (xcov)
       -> McpSessionManager
       -> DirectLauncher:  tools/xcov --stdio-loop  (direct)
       -> LsfLauncher:     bsub -I tools/xcov --stdio-loop  (LSF)
  -> In-process adapters (xbit/xentry/xloc)
       -> import corresponding public Python APIs in the MCP server process
  -> Stateless CLI adapter (xsva)
       -> tools/xsva public JSON / command-specific XOUT
```

SDK-free LSF CLI 链路：

```text
tools/xdebug_lsf / tools/xcov_lsf + native request envelope
  -> transparent local Unix domain socket manager
  -> LoopWrapperService (internal)
       -> McpSessionManager (xdebug)
       -> LsfLauncher:    bsub -I -env all <environment verifier> tools/xdebug --stdio-loop
       -> McpSessionManager (xcov)
       -> LsfLauncher:    bsub -I -env all <environment verifier> tools/xcov --stdio-loop
```

示例：

```bash
tools/xdebug_lsf --json - <<'EOF'
{"api_version":"xdebug.v1","request_id":"1","action":"session.open","target":{"fsdb":"waves.fsdb"},"args":{"name":"s0"}}
EOF

tools/xdebug_lsf --json - <<'EOF'
{"api_version":"xdebug.v1","request_id":"2","action":"value.at","target":{"session_id":"s0"},"args":{"signal":"top.clk","time":"10ns"}}
EOF
```

环境配置生成与检查：

```bash
tools/xverif_lsf_env_capture --dry-run
tools/xverif_lsf_env_capture
chmod 600 tools/xverif_lsf.env.json
tools/xdebug_lsf --json request.json
```

默认生成不覆盖已有文件；确认更新时显式加 `--force`。站点自定义变量用重复的
`--include NAME` 加入。变量名包含 `TOKEN`、`PASSWORD`、`SECRET` 或 `COOKIE`
时默认排除。JSON 只允许 `schema_version` 和 string-valued `variables`，并拒绝
symlink、非当前用户 owner 和非 `0600` 文件。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `XVERIF_HOME` | 仓库根目录 |
| `XVERIF_MCP_BACKEND` | 只接受 `direct`（默认）或 `lsf` |
| `XVERIF_MCP_TIMEOUT_SEC` | one-shot 请求超时（默认 360s） |
| `XVERIF_MCP_STARTUP_TIMEOUT_SEC` | session open 超时（默认 180s） |
| `XVERIF_MCP_REQUEST_TIMEOUT_SEC` | query 请求超时（默认 360s） |
| `XVERIF_MCP_CLOSE_TIMEOUT_SEC` | session close 超时（默认 30s） |
| `XVERIF_MCP_BKILL_TIMEOUT_SEC` | bkill 超时（默认 30s） |
| `XDEBUG_SESSION_START_TIMEOUT_SEC` | xdebug 统一 engine daemon 启动等待超时（默认 300s） |
| `XDEBUG_SESSION_IDLE_TIMEOUT_SEC` | xdebug 统一 engine session 空闲超时（默认 86400s） |
| `XVERIF_MCP_LOG_DIR` | MCP structured log 根目录，默认 `~/.xverif/mcp` |
| `XVERIF_MCP_BATCH_MAX_INPUT_BYTES` | batch 输入 hard limit，严格正整数，默认 16777216（16 MiB） |
| `XVERIF_MCP_BATCH_MAX_REQUESTS` | batch 非空请求行 hard limit，严格正整数，默认 10000 |
| `XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES` | batch 输出 hard limit，严格正整数，默认 67108864（64 MiB） |
| `XVERIF_LSF_BSUB` | 覆盖 `bsub` 命令（默认 `bsub`） |
| `XVERIF_LSF_SESSION_QUEUE` | session job 的 LSF 队列（默认 `interactive`） |
| `XVERIF_LSF_SESSION_RESOURCE` | session job 的 LSF resource string（默认省略） |
| `XVERIF_LSF_BKILL` | 覆盖 `bkill` 命令 |
| `XVERIF_XCOV_BIN` | 覆盖 xcov 可执行文件路径，默认 `tools/xcov` |
| `XVERIF_XCOV_PYTHON` | 覆盖 xcov 使用的 Python runtime |
| `XVERIF_XCOV_VERDI_HOME` | 覆盖 xcov 使用的 Verdi 安装路径 |
| `XVERIF_XCOV_LOG_DIR` | 覆盖 xcov 日志目录，默认 `~/.xverif/xcov` |
| `XVERIF_XCOV_LOG=0` | 关闭 xcov 日志 |
| `XVERIF_XCOV_BRANCH_MASK_HINT` | 默认 `1`，提供 branch bin 的 branch_mask 解释；`0/false/no/off` 关闭 |
| `XVERIF_XCOV_URG_BACKEND` | xcov 内层 URG backend，只接受 `direct|lsf`，默认 `direct` |
| `XVERIF_XCOV_URG_QUEUE` | 内层 `bsub -K` URG queue；backend=lsf 时必填，不继承 session queue |
| `XVERIF_XCOV_URG_RESOURCE` | 可选内层 URG resource string |
| `XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC` | 内层 URG job PEND→running 超时，默认 120s |
| `XVERIF_XCOV_URG_RUN_TIMEOUT_SEC` | 内层 URG running 超时，默认 600s |
| `XVERIF_MCP_FAKE_LSF` | 仅 MCP namespace 的显式 fake LSF，严格布尔 `0|1` |
| `XVERIF_LSF_CLI_SOCKET` | SDK-free LSF CLI 内部 socket 路径；不提供公开 `--socket` 参数 |
| `XVERIF_LSF_CLI_LOG_DIR` | SDK-free LSF CLI structured log 根目录，默认 `~/.xverif/lsf-cli` |
| `XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC` | SDK-free LSF session open 超时 |
| `XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC` | SDK-free LSF query 请求超时 |
| `XVERIF_LSF_CLI_CLOSE_TIMEOUT_SEC` | SDK-free LSF session close 超时 |
| `XVERIF_LSF_CLI_BKILL_TIMEOUT_SEC` | SDK-free LSF bkill 超时 |
| `XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC` | 内部 manager 无活动 session/request 后退出等待，默认 5 秒 |
| `XVERIF_LSF_CLI_FAKE_LSF` | 仅 SDK-free LSF CLI namespace 的显式 fake LSF，严格布尔 `0|1` |
| `XVERIF_LSF_CLI_CONFIG` | 覆盖 SDK-free 环境配置路径；默认入口同目录 `xverif_lsf.env.json` |
| `VERDI_HOME` | Verdi 安装目录 |
| `LD_LIBRARY_PATH` | 需包含 `<verdi-install>/share/NPI/lib/LINUX64` |

所有 timeout 变量只接受无首尾空白的有限正数；布尔或 timeout 配置非法时立即返回明确错误。MCP 与 SDK-free LSF CLI 的 fake LSF 开关互不别名，也不会在启动、请求或 cleanup 失败时自动切换 backend。

当外层 xcov session 和内层 URG 都使用 LSF 时，外层始终是一个长期
`bsub -I tools/xcov --stdio-loop`，每个 cold URG 则是独立 `bsub -K`。两个 queue/resource
命名空间必须分别配置；warm summary cache hit 不提交内层 job。所有 coverage 输入、EL、
cache、report 与临时 hier 必须位于登录节点和计算节点共同可见的绝对路径。

xdebug/xcov stateful session 会写结构化 MCP 日志：

- server：`~/.xverif/mcp/owners/<owner>/logs/server.ndjson`
- session lifecycle：`~/.xverif/mcp/sessions/<alias>/owners/<owner>/session.ndjson`
- stdio-loop protocol：`~/.xverif/mcp/sessions/<alias>/owners/<owner>/stdio.ndjson`
- LSF launcher / job / cleanup：`~/.xverif/mcp/sessions/<alias>/owners/<owner>/lsf.ndjson`

当 open/query 返回 `SESSION_LOST`、ready timeout、stdout pollution、fake/real LSF
启动失败或 cleanup 失败时，优先读这些日志；事件会包含 alias、backend、launcher、
pid、job_id/job_name、request_id、stderr_tail 和 cleanup 结果。
`owner` 是 fork-safe 的 `pid-start_nonce`，每个 runtime 进程实例只写自己的 shard。

SDK-free LSF CLI 会写结构化日志：

- manager：`~/.xverif/lsf-cli/owners/<owner>/logs/server.ndjson`
- UDS protocol：`~/.xverif/lsf-cli/owners/<owner>/logs/uds.ndjson`
- session lifecycle：`~/.xverif/lsf-cli/sessions/<alias>/owners/<owner>/session.ndjson`
- stdio-loop protocol：`~/.xverif/lsf-cli/sessions/<alias>/owners/<owner>/stdio.ndjson`
- LSF launcher / job / cleanup：`~/.xverif/lsf-cli/sessions/<alias>/owners/<owner>/lsf.ndjson`

配置日志只记录配置路径证据、变量名和整体指纹，不记录变量值。远端环境不一致
返回 `LSF_ENV_MISMATCH`；配置改变但旧 manager 仍有 live/unresolved session
返回 `CONFIG_MISMATCH`，不会杀掉旧 session 或切换 backend。

xdebug session 工具使用明确前缀：

```text
xverif_debug_session_open
xverif_debug_session_list
xverif_debug_session_doctor
xverif_debug_session_close
xverif_debug_session_gc
```

xcov session 工具使用 coverage 前缀：

```text
xverif_cov_session_open
xverif_cov_session_list
xverif_cov_session_doctor
xverif_cov_session_close
xverif_cov_session_kill
xverif_cov_session_gc
xverif_cov_query
```

两组生命周期工具遵循相同 managed contract：open 使用 `name` 请求 canonical `session_id`，且 backend 返回值必须与 `name` 完全一致；query/doctor/close/kill 只接受精确 `session_id`，不接受 `session` 或 `name`，kill 不接受 `all`。list 支持 `include_tombstones`/`verbose`，doctor 只读且不会 reopen。compact record 返回 session_id/ownership/backend/launcher/state、资源 basename/hash 和结构化 scheduler truth；verbose 再展开 PID、兼容 job 字段、完整路径和 cleanup 诊断。

xdebug detached backend 可能比 stdio-loop 活得更久，dead loop 只由固定 native admin path 精确 doctor/kill；xcov backend 由 loop 进程拥有，kill 只终止 loop/process/LSF job，并明确返回 native kill `not_supported`。任一 cleanup 阶段失败时返回 `SESSION_CLEANUP_PARTIAL_FAILURE`、`error_layer=session_manager` 并保留 unresolved tombstone。debug/cov query 均拒绝 native lifecycle action，不会 fallback 到其它 transport 或 backend。

`xverif_debug_session_open` 与 `xverif_cov_session_open` 都接受可选 `run_manifest`。
它们会在启动后端前严格校验已发布的资源清单：xdebug 使用
`xdebug.run-manifest.v1`（FSDB/daidir），xcov 使用 `xcov.run-manifest.v2`（VDB）。xcov v2
要求 `sha256-entry-tree-v2` 无歧义目录摘要、资源类型、regular-file 总字节数以及
file/directory/symlink 计数；不接受旧 v1 清单。
清单内资源路径相对 manifest 文件，且必须匹配路径、`size_bytes` 与 SHA-256；失败返回
`RESOURCE_PROVENANCE_MISMATCH`，不会自动重试、重开或切换后端。

xcov exclusion reason 只由 CSV sidecar 持久化。reason revision 尚未经
`exclude.csv.export/compile/apply` 成功持久化时，普通 cov session close 返回
`UNPERSISTED_EXCLUSION_REASON`，manager 保留原 stdio-loop 和 session；调用方应先导出 CSV，
或明确使用 `confirm_discard_reasons=true` 强制关闭。该确认值会原样传入 native
`session.close`，响应同时报告是否丢弃及丢弃计数。

## 工具与输出行为

common/debug/cov/bit/entry/loc/sva 全部注册；session 生命周期、配置/list/cursor、
coverage exclusion 和 batch 均可调用。工具目录的 group/mutation/artifact_write 是
描述性元数据，不是权限开关。工具帮助的 policy 只包含 batch_limits。

MCP 自身的 batch 输出和通用响应文件相对 server 工作目录解析，不限制输出根目录。
batch 保留输入冻结、三项上限、同 inode 检查及原子 no-clobber 发布；通用响应文件
按 xverif_output_append 选择追加或覆盖。
xdebug/xcov action 的输出参数原样传递给 native backend：MCP 不改写路径，也不注入
allow_absolute_path。xcov 相对路径使用其原生导出目录；绝对路径必须显式允许并符合
XVERIF_XCOV_EXPORT_ROOTS，详见 [xcov README](../xcov/README.md)。

### 配置迁移

以下旧变量已停止读取，旧值（包括 0 或非法值）不会限制工具或阻止启动，请从部署配置删除：

- XVERIF_MCP_ENABLE_COMMON、XVERIF_MCP_ENABLE_DEBUG、XVERIF_MCP_ENABLE_COV、
  XVERIF_MCP_ENABLE_BIT、XVERIF_MCP_ENABLE_ENTRY、XVERIF_MCP_ENABLE_LOC、
  XVERIF_MCP_ENABLE_SVA。
- XVERIF_MCP_ENABLE_MUTATION、XVERIF_MCP_ENABLE_ARTIFACT_WRITE、XVERIF_MCP_ARTIFACT_ROOT。
- 无实际消费者的 XVERIF_LSF_CLI_TIMEOUT_SEC、XVERIF_LOOP_TIMEOUT_SEC；
  SDK-free 使用已有的 STARTUP/REQUEST/CLOSE/BKILL/IDLE 阶段超时。

旧 artifact root 下的相对输出不会继续映射到旧根目录。需要保持原输出位置时，显式提供
绝对路径；下游 coverage 导出同时遵守 native 的绝对路径许可合同。

### 配置归属与读取时机

XVERIF_MCP_* 属于 MCP；XVERIF_LSF_SESSION_* 和 BSUB/BKILL 是共享调度配置；
XVERIF_LSF_CLI_* 属于 SDK-free CLI，XVERIF_LOOP_* 属于内部 wrapper。
XVERIF_LSF_ENV_* 指纹和 CLI ENTRY_DIR/LOADED_CONFIG_PATH/CONFIG_FINGERPRINT
是 SDK-free 内部元数据；FAKE_BSUB_*、XVERIF_TEST_TMPDIR 用于测试。
XDEBUG_*、XVERIF_XCOV_* 由对应下游工具处理；PATH/PYTHON/PYTHONPATH、
VERDI_HOME/VCS_HOME、动态库和 license 变量属于启动环境。

MCP 的 session runtime 和 batch 上限在 server 初始化时形成快照；
XVERIF_MCP_TIMEOUT_SEC 在构造 one-shot runner 时读取，默认 360 秒。
下游 xcov 的部分日志、缓存和输出选项按操作读取，不能把所有环境变量都视为启动快照。
修改客户端部署环境后，需要重启 MCP server 才能让新环境进入该进程。

`xverif_tools` 是无参数的 xdebug action discovery 入口。它请求 native
`actions` 的 `args.output.view="guide"` 并原样返回 `data.guide`；每行只包含 action
名和精简英文 purpose，不含 status/`use_when`。native runtime 对完整 guide 执行
10,000 UTF-8 字节硬门禁，超限明确失败，不截断。选择 action 后再调用
`xverif_debug_get_schema(action)` 获取精确参数和使用指导，不要按 category/keyword
反复筛选。原生 CLI 与 SDK-free `xdebug_lsf` 可提交同一 `actions` envelope 获得该 guide。

## 测试

```bash
pytest --xverif-gate fast --xverif-suite xverif_mcp.unit
pytest --xverif-gate regression --xverif-suite xverif_mcp.process
pytest --xverif-gate regression --xverif-suite xverif_mcp.action_smoke
PYTHON=python3 XVERIF_MCP_FAKE_LSF=1 tools/xverif-lsf-doctor --fake
```

MCP stdio/UDS、NPI 和 fake/real LSF 测试必须在沙箱外运行。real LSF 由 nightly catalog optional capability 控制，不会切换到 fake backend。
