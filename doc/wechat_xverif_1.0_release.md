# xverif 1.0 发布：xdebug 与 xcov 的架构和技术路线

xverif 1.0.0 正式发布。

仓库里的工具不少，但有两个需要链接商业 EDA 软件，架构上也最费功夫：`xdebug` 和 `xcov`。一个查设计和波形，一个查覆盖率。它们的输入都是 EDA 工具产出的数据库，都受同样的三个约束：打开成本高、扫描成本高、结论要能被复核。

这篇主要讲这两个工具怎么分层、做了哪些取舍，以及 1.0 定下来的技术路线。xdebug 的常用 action 用法另开一篇，这篇专注架构。其他工具和接入方式放在后面。

仓库地址：<https://github.com/BLANK2077/xverif>

## xdebug 解决什么问题

`xdebug` 的输入是编译产生的 `daidir` 和仿真产生的 FSDB。它回答的问题包括：

- 这个信号的 driver 和 load 分别是谁；
- 某个时间点的值是多少，某个条件在窗口内是否一直成立；
- APB、AXI、stream 接口上发生了什么，异常 transaction 是哪一笔；
- 某拍出现的 X 是从哪一级传播过来的；
- 某个波形值在那一刻由哪条 RTL 赋值语句驱动。

这五类问题的共同点是：答案必须能落到具体的信号路径、时间点和源码行。它对外提供 73 个公开 action，其中 65 个 stable、8 个 experimental。

## 分层：frontend 与 engine 分开

`xdebug` 构建出两个进程：

- `xdebug/xdebug`：frontend，负责请求解析、schema 校验、action 分发和输出渲染。
- `xdebug/libexec/xdebug-engine`：内部 engine，NPI、FSDB 和设计数据库的读取逻辑都在这里。

frontend 不承载 NPI 重逻辑。这样切之后，engine 可以按 session 长期复用，frontend 只做短生命周期的请求处理；engine 崩溃和 frontend 崩溃也能分开诊断。两边共享 `src/core/` 下的通用组件，session、schema、日志这些能力只有一份实现。

engine 内部按能力再分层：design 负责设计数据库解析、signal resolve、driver/load、AST 和控制依赖；waveform 负责 FSDB 读取、时间解析、clock sampling、event 表达式、协议分析；combined 同时使用两者，把波形时间点接到 RTL 因果关系上。

## action 是唯一入口，schema 是合同

所有能力都通过 action 暴露。`specs/actions/actions.yaml` 是 action 清单的 source of truth，记录每个 action 的名称、category、状态、所需资源、handler 类型、schema 和 example 路径。

每个 action 都有独立的 request schema 和 response schema，配一份可执行 example。contract test 会校验 runtime registry、`actions.yaml`、schema、example 四者一致。请求在填默认值之前先过 action-specific schema，handler 返回后再用同一 action 的 response schema 校验公开结果。未知字段直接返回 `SCHEMA_INVALID`，不会静默忽略。

维护这么多 schema 是有成本的，换来的是 MCP 工具、skill 文档和 runtime 不会各自漂移。参数名、enum、默认值和 required 语义只有一个来源。

## session：摊掉打开成本，同时盯住资源身份

FSDB 的打开成本很高，大型后仿波形尤其明显。`xdebug` 用持久 session 解决复用问题：`session.open` 之后，后续查询通过 `session_id` 走已经打开的 handle。

session 同时承担一个更重要的职责：确认查询用的还是同一份资源。open 时记录 FSDB 的 canonical path、device、inode、size 和纳秒级 mtime；每个 session-bound query 在进入旧 handle 前重新比对完整指纹。任一变化、资源缺失或类型变化，都返回 `RESOURCE_CHANGED`，不自动 reopen，也不切到别的数据源。

session 状态按目录存放：`~/.xdebug/engine/sessions/<hash>/state.json`。普通 query 按规范化 id 直接定位，只有 list 和 gc 才遍历目录；写 `last_active` 不会阻塞查询返回。frontend 和 backend 的 session 映射可以单独诊断，backend 崩溃后 frontend 不会假装 session 仍然健康。

## 同一 session，同一份分析只扫一遍 FSDB

协议分析是 `xdebug` 里开销最大的部分。如果每个 action 各扫一遍波形，光是重复遍历就够把交互拖垮。engine 里的 `AnalysisRepository` 负责避免这件事。

AXI 侧，`AxiAnalyzer` 对每个 session 和 config 只做一次完整的 FSDB clock scan。配对状态机只有一份：AW 和 W 按 AW acceptance order 绑定，允许整个 W burst 在 AW 之前完成；BID 绑定同 ID 最老的 data-complete write，RID 绑定同 ID 最老的 AR。之后 query、analysis、pair、timeline、outlier、cursor、export 全部复用同一份 `AxiResult`。address、ID 和 handshake 索引按需单独建立，不复制 transaction 本身。

APB 侧，`ApbAnalyzer` 把 completed transfer 发布到同一个 repository；按地址查询用独立的懒加载 `AddressIndex`，索引只保存 canonical position。

stream 侧拆成了两层：`StreamBaseAnalysis` 保存时间、控制、stall 和 X/Z 统计这类元数据，完整 field column 只在需要时与 transfer ordinal 对齐；`StreamQueryView` 从 base 重建窗口内的 cycle、packet index、stall 边界和 filter evidence，base 的内部 sample id 不进入公开响应。

这套 repository 由每个 engine 唯一持有，key 里包含 FSDB identity、版本化语义 fingerprint 和查询范围。内存预算分 soft 和 hard 两级，默认 1 GiB 和 2 GiB；计费用确定性估算值乘以固定的 safety factor 2.0；淘汰时先清索引，再清 canonical 结果；构建失败的对象不会发布。

## combined：把时间点接到设计因果上

只有 daidir 能回答“谁驱动这个信号”，只有 FSDB 能回答“这一刻它是什么值”。`trace.active_driver` 把两者合起来：给定信号和时间点，返回当前生效的驱动证据。

这类联合分析定了几条明确的限制。`trace.active_driver_chain` 只在 `npiRhs` 明确给出直接 signal 时继续往下追；遇到多个 active assignment 或多个 RHS source，就停在 `ambiguous`，同时按语句返回 `active_time` 之前和该时刻的最终值。它不接受 `clk_period`，也不引入半周期窗口或邻近时钟沿这类启发式。因 `max_depth` 停止时，响应会给出 `depth_frontiers` 和可直接续查的参数。

`trace.x_origin` 处理 X 传播。它先确认查询点的值里确实含 X，再按 DFS 同等追踪含 X 的 RHS 和控制信号，穿过 module port、interface 和 modport。每一跳都重新定位该信号连续 X 区间的起点，所以时间可以多次往更早推进。仅由 port、interface、modport 或 ref alias 跳转不同造成的重复路径会按非 port 语义前缀归并，最终返回的是有效语义链。Z 不等同于 X。

## 输出层：XOUT 默认，JSON 显式

`xdebug` 默认输出 XOUT 结构化文本，需要完整字段、schema 校验或结构化持久化时再取 JSON。

XOUT 的第一段不是固定模板。共享层负责 canonical 完整性字段、嵌套 output 和 range 的投影，以及可证明的同义去重；领域层只挑这个 action 必要的首段字段。如果 summary 只是重复紧随其后的 config 或 stream section，handler 可以整段省略，但 session identity、输出路径、verdict、finding 总览和 incomplete 证据不能丢。投影只生成渲染副本，不改 response、schema 和 example。

xdebug 的常用 action 用法、返回字段和边界条件写在另一篇《xdebug 常用 action 实战》里，覆盖 `scope.list`、`list.first_change`、`event.find`、`value.at` 多时间点取值、`counter.statistics`、`window.verify`、`protocol.handshake.inspect`、`stream.query`、`signal.xz_verify`、`nwave.rc.generate` 和 `list.export`。

## xcov 解决什么问题

`xcov` 的输入是 `simv.vdb` 或 `merged.vdb`。它回答的问题包括：

- 某个 scope 的 line、toggle、branch、condition、fsm、functional 覆盖率是多少，子模块怎么排名；
- 具体缺哪个 bin，对应源码哪个文件的哪一行；
- 从源码 `file/line/window` 反查有哪些 coverage item 落在上面；
- 哪些缺口应该补激励，哪些应该带理由排除，排除记录怎么复查、怎么迁移到新 VDB。

最后一个问题决定了 `xcov` 的架构，它比其他覆盖率查询工具多了一层持久化和审核的设计。

## URG 负责读，NPI 负责写

`xcov` 把工具边界划得很清楚：覆盖率统计和报告导出交给 URG，NPI 只用于 exclusion。

读 summary 固定使用 `urg -full64 -xml_verbose -format text -show summary`，产出 typed `session.xml` 和五个 summary 文本，不生成完整 HTML，也不依赖 `modinfo.txt` 和 `grpinfo.txt`。父实例的统计直接采用 URG 给出的 subtree score，不把子实例重新累加。多 metric scope 的 `coverage_pct` 按 URG SCORE 语义取所选 metric 百分比的算术平均；不同 metric 的计数单位不能相加，所以多 metric scope 不返回 aggregate count。

只读路径不加载 pynpi。只有首次执行 exclusion、需要修改原生 exclusion 状态时，才在当前 session 内惰性创建一次 NPI 上下文，诊断输出走 stderr，stdout 保持机器可解析。

这样分工之后，日常覆盖率查询不碰 NPI，也就避开了 NPI 全树遍历容易出现的重复计数和性能问题。出错时能分清是 URG 读取层还是 NPI 写入层的问题。

## 从 modinfo 到 XOUT

原始 `modinfo` 面向传统报告工具，信息完整，篇幅也大。一个条件表达式可能展开成多组 truth table，分支和 FSM 还夹着大量上下文。人在 Verdi 里可以逐页翻，模型直接读这些文本会浪费大量上下文，还容易把报告结构当成语义。

`xcov` 解析 `modinfo`，只保留定位缺口需要的信息：源码位置、实例、表达式、分支取值、状态跳转，然后按 coverage 类型重新组织：

- line coverage 按过程块列出未覆盖语句；
- condition 和 branch coverage 把表达式中的条件标成可引用项，列出尚未覆盖的取值组合；
- FSM 按状态机组织缺失的 state、transition 和 sequence。

每个语义缺口得到一个 `gap_id`，例如 `L0001`、`B0002`、`C0003`、`F0001`、`A0001`、`FC0001`。这个 ID 是后续 exclusion 的操作句柄。模型不用重新描述一长串源码位置和 truth table，只要引用对应 `gap_id`；审核者回到同一份 XOUT，也能看到它对应哪条语句、哪组条件或哪个状态跳转。

condition 的分组做得更细：同一组 values 的 EXPRESSION 和 SUB-EXPRESSION 会合并成一个语义 gap。响应里 `coverage_object_gap_count` 对应 URG 原始 missing，`gap_count` 对应实际需要补的语义组合，两个数字分开给。

## exclusion：CSV 存决定，EL 存执行结果

原生 EL 文件能被 Synopsys 工具加载，但不适合管理 exclusion。

它不保存排除理由。过一段时间再看到某条 exclusion，很难判断它来自规格限制、不可达状态，还是一次临时规避。它还与生成它的设计和 VDB 存在 checksum 关系，RTL、编译参数或层次一变，旧 EL 就可能因为 module checksum mismatch 无法用于新 VDB。

`xcov` 因此把 CSV 作为自有 exclusion 的持久化来源。CSV 保存可移植的语义定位信息，每条记录必须带非空 `reason`。模型可以提出 exclusion，但不能只说“建议排除”，必须写清楚原因，例如规格禁止该状态组合、当前产品配置未例化该功能、分支只用于故障注入、该实例在此配置下被静态关闭。

完整流程是：

```text
旧 VDB
  -> URG 统计与导出
  -> XOUT gap
  -> gap_id / instance exclusion
  -> 带 reason 的 CSV
  -> 当前 VDB 的 EL

新 VDB
  -> 加载同一份 CSV
  -> 在新数据库中重新解析目标
  -> NPI 实时执行 exclusion
  -> 生成与新 VDB 匹配的新 EL
```

新 VDB 上的重新解析必须得到唯一对象，零匹配和多匹配都会失败，避免把旧设计里的决定套到新设计上。被复用的是经过 review 的 exclusion 决定，EL 每次根据当前 VDB 重新生成。既不用改原生文件，也不会把 checksum mismatch 当成可以忽略的警告。

## 实例级 exclusion 按真实 elaborate 层次展开

一个实例在当前配置里根本不启用时，它下面可能有成百上千个缺口。逐条处理不现实，`xcov` 提供实例级排除，可以只排除当前 instance，也可以带上它的子 instance。

这里的“递归”不是字符串前缀匹配。`xcov` 用 URG XML 里记录的实例层次展开目标，只处理真实存在的 elaborated instance，避开 generate scope、相似实例名和层次前缀带来的误伤。每个展开后的目标保留精确身份，后续 remove 只撤销原来记录的 ownership，不会根据新层次扩大范围。

## 内容寻址缓存：把 URG 的重复执行压到一次

URG 的执行成本不低，同样的 VDB 反复跑 summary 是浪费。`xcov` 的固定 summary 使用内容寻址 cache。

key 里包含 VDB 内容 hash、URG 的绝对路径和 release、URG 文件身份、固定 argv、parser 和 cache 版本、merged selection，以及当前 EL hash。命中时校验六个文件的 hash、size 和 semantic count。同一个 key 的并发冷启动用 per-key `fcntl` claim 保证只真正执行一次 URG，完成后经 fsync 和 atomic rename 发布。

容量是软准入，默认 20 GiB 和 128 个 entry。超过阈值后新的冷启动返回 `XCOV_CACHE_CAPACITY_EXCEEDED`，已经发布的 entry 仍可读取，直到显式维护清理。损坏的 entry 会被隔离并重建，超过 24 小时的 abandoned staging 才会清理。

## fail-closed 的 schema 与预算

`xcov` 的 schema 校验比一般查询工具严。dispatcher 在填充 `request_id`、`target`、`args` 默认值之前，先用 action-specific request schema 校验原始请求；handler 返回后、公开结果之前，再用同一 action 的严格 response schema 校验一次。top-level、`target`、`args`、`query`、`sort`、`limits` 和导出参数里的未知字段都会返回 `SCHEMA_INVALID`。

`SessionManager` 把真实 NPI、测试 Fake 和 factory 注入统一包成同一个严格 adapter。score 的 primitive、值域、`covered <= coverable`、`missing`、百分比、status 和 evidence 任一项不一致就 fail-closed：真实 NPI 返回 `NPI_CONTRACT_VIOLATION`，注入 backend 返回 `BACKEND_CONTRACT_VIOLATION`。不接受 `-1` 表示不适用，不适用值必须是 JSON `null`。

资源预算也是前置的：请求上限 1 MiB，inline response 上限 16 MiB 且最多 10,000 行，单个 artifact 上限 1 GiB，六件套合计 2 GiB。超限返回 `REQUEST_BUDGET_EXCEEDED`、`RESPONSE_BUDGET_EXCEEDED` 或 `RESOURCE_BUDGET_EXCEEDED`，不会先构造一个无限大的内存对象再截断。

导出路径同样收紧：相对路径写到 `.xverif/xcov_exports/`，包含 `..` 的路径直接拒绝，绝对路径必须显式开启并落在声明的根目录内。任一中间路径是 symlink、规范化后逃逸允许范围或超出发布预算，都 fail-closed。文件在同一个 staging 目录里生成、校验、fsync 之后才发布；CSV 多文件更新会先保留逐文件 backup，任一步失败就按逆序恢复。

## 两个工具共用的技术路线

把上面这些取舍归拢一下，`xdebug` 和 `xcov` 走的是同一条路线。

结果必须可追溯。每条结论都要能落到 action、信号路径或 scope、时间点或源码行。

失败必须显式。session 打不开不自动重建，资源变了不自动 reopen，数据源不可用不静默切换，部分枚举不伪装成完整结果。所有成功和错误响应都带完整性字段，`truncated`、`scan_complete`、`analysis_complete` 这类状态调用方一定看得到。

合同必须可执行。schema 不只是文档，runtime 用它拦请求，也用它校验响应。示例是可执行合同，不是宣传材料。

成本必须摊开。打开一次的资源用 session 复用，扫描一次的分析用 repository 复用，执行一次的外部工具用内容寻址 cache 复用。三处复用都带明确的生命周期和失效条件。

## MCP：统一的接入方式

xverif 通过一个 MCP server 暴露全部能力。`xdebug` 和 `xcov` 是 stateful backend，每个 MCP session 对应一个独立的 backend 进程，不同 session 可以并行，同一 session 内的请求串行。`xbit`、`xentry`、`xloc`、`xsva` 都是 stateless adapter，不持有跨请求的会话。

debug 侧工具：

- `xverif_debug_session_open` / `list` / `doctor` / `close` / `gc`
- `xverif_debug_query`
- `xverif_debug_list_actions` / `xverif_debug_get_schema`

cov 侧工具：

- `xverif_cov_session_open` / `list` / `doctor` / `close` / `kill` / `gc`
- `xverif_cov_query`
- `xverif_cov_list_actions` / `xverif_cov_get_schema`

公共工具：

- `xverif_tools`：无参数的 action 发现入口，返回精简的 action 名和用途；
- `xverif_batch`：按 NDJSON 文件接收一批 MCP tool 请求，严格串行执行后把结果写到另一个 NDJSON 文件；
- `xverif_output_path` / `xverif_output_append`：把响应同时写入文件，写入失败返回 `OUTPUT_WRITE_FAILED`。

查询统一走 `xverif_debug_query(session_id, action, args, limits, output_format)` 和对称的 `xverif_cov_query`。MCP 不通过 query 暴露 native session 生命周期，open、close、doctor、gc 各有独立工具。`xverif_debug_get_schema` 返回的是 MCP 投影：`args_schema` 和 `limits_schema` 是 query 内层参数的字段合同，`constraints` 补充跨字段语义，`minimal_call` 可以直接复制。

一个最小配置：

```json
{
  "mcpServers": {
    "xverif": {
      "command": "<conda-env>/bin/python",
      "args": ["-m", "xverif_mcp.server"],
      "env": {
        "PYTHONPATH": "<xverif>/xverif_mcp/src:<xverif>",
        "XVERIF_HOME": "<xverif>",
        "VERDI_HOME": "<verdi-install>",
        "LD_LIBRARY_PATH": "<verdi-install>/share/NPI/lib/LINUX64"
      }
    }
  }
}
```

### MCP 的三种运行形态

调用面不随部署方式变化，变的只是 backend 进程跑在哪里。

本地直连是最简单的形态：MCP server 在本机启动 `xdebug` 和 `xcov` 的 backend 进程，上面那段配置就是它。

LSF 把 `XVERIF_MCP_BACKEND` 设为 `lsf`，MCP server 改用 `bsub -I` 把每个 session 的 backend 提交成一个独立的 interactive job。不同 session 是不同的 job，可以并行；同一 session 内的请求仍然串行。队列用 `XVERIF_LSF_SESSION_QUEUE` 指定，`PATH` 要能找到 `bsub` 和 `bkill`。xcov 的 native loop 本身只允许一个 live VDB session，多 VDB 并发由 MCP manager 起多个 job 完成。

```json
"env": {
  "XVERIF_MCP_BACKEND": "lsf",
  "XVERIF_LSF_SESSION_QUEUE": "interactive"
}
```

FSDB 或 daidir 较大、LSF 排队较久时，把 `XVERIF_MCP_STARTUP_TIMEOUT_SEC`、`XVERIF_MCP_REQUEST_TIMEOUT_SEC` 和 `XDEBUG_SESSION_START_TIMEOUT_SEC` 一起调大。这些变量要写进 MCP client 的 `env`，只在外层 shell 里 export 通常不会生效。

ssh 远端用于 EDA 机器和 agent 不在同一台的情况。用 `mcp_ssh` 把远端的 xverif MCP server 通过 ssh 暴露成本地 stdio server，对 MCP client 来说它和本地 server 没有区别。

```json
{"command": "<conda-env>/bin/python",
 "args": ["-m", "mcp_ssh"],
 "env": {"PYTHONPATH": "<xverif>/xverif_mcp/src",
         "XVERIF_MCP_SSH_HOST": "user@eda-host",
         "XVERIF_MCP_SSH_REMOTE_ROOT": "/shared/xverif",
         "XVERIF_MCP_SSH_REMOTE_PYTHON": "<shared>/xverif/.conda-xverif/bin/python"}}
```

`XVERIF_MCP_SSH_HOST` 是 ssh 目标，`XVERIF_MCP_SSH_REMOTE_ROOT` 是远端仓库根目录，`XVERIF_MCP_SSH_REMOTE_PYTHON` 是远端解释器，要求 Python 3.11 以上。`mcp_ssh` 只做转发：`tools/list` 的 schema 和 `tools/call` 的结果原样透传，工具语义始终由远端 server 决定，每个 MCP 连接对应一个独立的远端进程。凭据形状的变量名和描述本机的变量（`HOME`、`USER`、`SSH_AUTH_SOCK` 等）不会转发，两台机器也不需要共享 `$HOME`，session 状态落在远端自己的 `$HOME/.xdebug` 下。

## 其他工具在 MCP 里的位置

`xbit` 负责确定性的 bit 和表达式计算：SV literal 转换、signed/unsigned 解释、slice、concat、mask、popcount、onehot、常量表达式和条件检查。它的语义用 SystemVerilog 仿真跑过 oracle 对照。

`xentry` 按外部 config 把多拍 byte fragments 拼起来，切出 raw field slices 和 provenance。它不读波形、不判断 valid/ready、不做字段类型解码。

`xloc` 把 UVM 日志里的长路径压成 `L_XXXXXXXX`，需要时再还原，另附热点统计和源码上下文查询。

`xsva` 把 SVA 从文本编译成 Surface、Sequence、Timeline 三层 IR，解释全部从 IR 生成，并输出 `match_paths`、`obligations` 和 `signals_to_query`。

`xwaveform` 把 `list.export` 的波形数据渲染成 JPG 和 stats，用于观察长窗口的整体形态；结论仍要回到确定性 action 验证。

仓库里还有五个面向 agent 的 skill：`xverif` 做能力路由，`xverif-admin` 负责安装、会话和运维排障，`x-npi` 负责用 pynpi 写批量离线分析脚本，`xsimdebug` 通过终端 PTY 实时操作 VCS UCLI 或 Xcelium Tcl，`xwiki` 维护项目的持续记忆。

## 版本与验证

1.0.0 把全部组件的版本号统一，仓库打上 `xverif-1.0.0` tag。

测试走统一的 catalog-driven pytest 门禁。最近一次 `fast` 门禁 716 项通过；沙箱外的 `regression` 门禁在真实 NPI 和 license 环境下 1582 项通过。schema、example、skill 和 runtime registry 之间的一致性由 contract test 保证。

环境要求：Python 3.11+ 用于 MCP、xsva 和 xcov，xbit、xentry、xloc 为 3.10+；GCC 5.0+，且编译器的 libstdc++ ABI 要与本地 `libnpiL1.so` 一致；当前基于 Verdi V-2023.12-SP2 开发和测试。NPI engine 是 source-only wrapper，构建前会先做一个最小链接预检，把环境问题和代码问题分开。

授权边界需要说明：本仓库以 MIT License 发布的范围只包含项目独立开发的源码和文档。Synopsys Verdi NPI、FSDB Reader、coverage runtime 及其 headers、libraries、documentation 不在其中。`xdebug` 和 `xcov` 的部分能力需要你自行取得合法授权并在本地安装对应软件，能访问这些文件不代表获得了 NPI/FSDB API 的使用权。

仓库地址：<https://github.com/BLANK2077/xverif>
