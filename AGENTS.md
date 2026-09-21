# AGENTS.md

本文件是本仓库的 agent 工作规则入口。所有 agent 先读本文件，再按任务读取更细的外部材料。

## 基本沟通

- 必须使用中文和用户沟通。
- 回答要直接、具体、证据驱动；不把猜测当事实。
- 当结论依赖仓库状态、schema、测试输出或环境行为时，先检查真实文件和命令结果。
- 用户明确要求实现时，直接完成实现、验证和交付说明；用户要求计划、评审或只读探索时，不越界修改。

## 执行前确认

- 除非用户明确要求直接执行，否则每次执行前至少给出三个可选方案，并交由用户选择。
- 计划阶段和实现阶段必须分清：计划阶段不修改 repo；实现阶段按已确认计划落地。
- 如果用户已经明确给出 `PLEASE IMPLEMENT THIS PLAN`、`开始实现`、`提交`、`推送` 等指令，可按该指令执行，不再重复询问同一决策。

## 权限与环境

- 所有 NPI、VCS 仿真、VIP、真实 license、真实 LSF、真实 EDA 工具动作，默认在沙箱外运行。
- 遇到进程通信、网络端口、文件系统、license、UDS/TCP/file transport、MCP stdio-loop 等问题，先判断是否为沙箱差异，再判断产品、SDK 或代码问题。
- 沙箱内失败不能直接当作产品回归；需要时做 sandbox-vs-host 对照，并在结果里说明执行位置。
- 不打印 access token、refresh token、cookie、完整唯一 ID 或其它敏感凭据。

## Fallback 规则

- 除非用户明确要求，不允许私自 fallback。
- 如果确实需要 fallback，必须先向用户说明原因、风险和替代路径，并等待确认。
- 不能因为某个环境动作失败就静默切换 transport、后端、数据源、测试层级或工具入口。

## Git 规则

- git commit 信息必须使用中文，并写清楚动机、范围和验证情况。
- 提交前必须运行 `git status --short`，确认只包含本次相关文件。
- 不使用 `git add .` 盲目打包；优先显式列文件，或在只提交已跟踪改动时使用 `git add -u`。
- 不回滚用户或其它进程产生的无关改动。
- 用户要求推送远端时，提交后推送当前目标分支，并回报 commit id 和推送结果。

## 项目概述

`xverif` 是面向芯片验证工作的工具集合，提供 debug、coverage、bit 计算、日志定位、协议/断言辅助和 agent/MCP 集成能力。

- `xdebug/`：统一的设计数据库、波形数据库和 combined debug 查询工具，提供 JSON action、schema、session、engine、log、transport 和测试体系。
- `xcov/`：coverage database 查询与报告工具，面向 VCS/Verdi coverage 数据。
- `xbit/`：确定性 bit、SystemVerilog literal、slice、mask 和表达式计算工具。
- `xentry/`：entry、descriptor、header、fragment 等结构化字段解析工具。
- `xloc/`：压缩日志位置 ID 与源码位置之间的还原、统计和标注工具。
- `xsva/`：SVA 解析、IR 生成和语义解释工具。
- `xverif_mcp/`：把 xverif 工具暴露给 MCP client 的 server、adapter 和测试。
- `skills/`：面向 Codex/Claude 等 agent 的工具使用说明、reference、脚本和可安装 skill。
- `doc/`：项目级报告、计划、架构说明和临时交付文档。

## 测试要求

- 一旦修改源码，在提交 git 前必须把关联测试全部跑通。
- 文档-only 修改可只做内容、链接、格式和引用检查；不需要运行源码测试。
- 测试命令必须来自当前仓库的 Makefile、README、pytest 配置或脚本，不凭旧记忆猜命令。
- 如果测试因 license、EDA 环境、真实数据、LSF 或沙箱限制无法运行，必须在最终说明和提交说明中写清楚阻塞原因。

常用入口：

- 全仓快速门禁：`pytest --xverif-gate fast`
- 全仓确定性回归（沙箱外）：`XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression -n auto`
- 全仓 nightly（沙箱外）：`XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate nightly -n auto`
- focused suite：在对应 gate 后追加 `--xverif-suite <catalog-id>`
- 显式准备数据库：`pytest --xverif-prepare <fixture-id>` 或 `all-generated`
- 全量 Fixture 校验：`pytest --xverif-fixture-validation --xverif-all-fixtures`
- 查看选择计划：`pytest --xverif-gate <gate> --xverif-plan`
- 前置依赖检查：`XVERIF_TEST_EXECUTION_ENV=host python tools/check_test_environment.py --gate <gate>`

补充约束：

- `--xverif-fixture-validation` 内部以 `rebuild=True` 调用 prepare，会**强制重建全部选中 fixture**；只想消费缓存时不要运行它。
- 只重建失效 fixture：先用 `--xverif-fixture-validation --xverif-changed <ref>` 或比对每个 fixture 的当前指纹与 `current.json` 预判，再对确认失效的 id 单独 `--xverif-prepare`。
- 同一工作树的正式 pytest gate/suite 默认串行启动。

Makefile 不再提供测试 target；裸 `pytest` 是 usage error。普通 regression/nightly 只消费缓存，cache miss 不自动仿真、不降级、不把 required 变成 SKIP。

## Skill 维护

- `skills/<name>/` 是 Codex/Claude skill 的唯一 source of truth；安装目录不是编辑源。
- 修改 CLI、MCP tool、action/schema、session 生命周期、输出合同、SDK-free wrapper 或测试入口时，必须同步检查对应 skill 的 `SKILL.md`、references 和 `agents/openai.yaml`。
- 公共参数不允许接受后静默忽略；实现不支持的参数必须从公开 schema 删除或返回明确错误。
- skill 修改必须通过对应 `skills.*` catalog suite，至少检查 Markdown 链接、可复制 JSON 示例、action/tool 覆盖和附带脚本。
- repo skill 提交并通过测试后，使用 Makefile 安装目标同步到 `~/.codex/skills` 与 `~/.claude/skills`，并逐 skill 执行 `diff -qr` 验收。
- SDK-free UDS readiness 以 server 成功进入 `listen()` 为准；禁止用 socket 文件存在、固定 sleep 或静默 connect 重试替代 ready 合同。
- 仅修改 skill 文档时不要求真实 NPI、编译或仿真；涉及真实 NPI/FSDB/VDB 的 skill 验证仍按本文件权限规则在沙箱外执行。

## Schema 维护

- `xdebug/specs/actions/actions.yaml` 是 action 名称、状态、handler、required args、required target、schema 路径和 example 路径的目录级 source of truth；修改公共 action 合同时必须先核对这里，不能只改 handler 或单个 JSON schema。
- runtime request 的允许参数集合、共享语义说明和 action-specific 补充参数维护在 `xdebug/tools/sync_runtime_request_schemas.py` 与 `xdebug/specs/action_contracts.py`。同名参数不得靠另一个 action 的既有 schema 推断业务语义；新增、删除或改名参数时必须同步 handler、`actions.yaml`、该生成脚本、checked-in schema 和 request example，禁止只手改生成后的 schema。
- 跨 action 的复用业务对象必须在共享合同组件中定义，再由生成器投影到各 action；例如 reset 一律为 `{"signal":"<one-bit waveform path>","polarity":"active_low|active_high"}`。不得重新引入 `rst_n`、裸 string reset、表达式 reset 或默认极性；外部 config 文件、持久化配置、runtime response 和 request schema 必须使用同一对象。
- 所有公开 action（包括 AXI）的 response schema 统一由 `xdebug/tools/sync_response_schemas.py` 生成；AXI `summary/data`、transaction、config、finding 等业务对象维护在 `xdebug/specs/non_sampling_response_contracts.py`，再由统一生成器投影并关闭未知字段，禁止直接手改 checked-in AXI response schema。
- schema 的 AI-facing purpose、使用场景和参数说明由 `skills/xverif/references/xdebug/action-reference.md`、`actions.yaml` 和 `xdebug/tools/sync_action_schema_hints.py` 同步；需要修改提示时先改 source，不在生成 schema 中单独维护漂移副本。
- 所有公开 request 顶层和 `args` 默认使用 `additionalProperties: false`；`query`、`output`、`time_range`、`match` 等嵌套对象也必须显式列出属性并关闭未知字段，除非合同明确要求可扩展对象。
- handler 接受的每个公共参数都必须出现在 action-specific schema 中并实际生效；schema 中公开但实现不支持的参数必须删除或返回明确错误，禁止接受后静默忽略。参数名、enum、默认值、required/conditional-required 语义必须在 native CLI、MCP、schema、example 和 skill 中一致。
- request/response schema 与 `examples/requests`、`examples/responses` 必须成对维护。response 不得在 `summary` 和 `data` 重复同一事实；时间只发布一个 canonical 带单位字符串，截断必须区分完整分析计数与返回行数，并提供 `truncated`、`truncation_scope` 或对应完整性字段。
- request schema 可声明 Draft 2020-12，但运行时使用 embedded Draft-7 兼容子集；新增共享对象、条件约束或 response 投影后必须先更新 generator/source，再运行 runtime-compatibility audit，禁止直接编辑生成产物。
- AXI 时间字段统一使用语义化名称。已确认使用 `valid_begin_time` 表示当前 address/data payload 首次被采样为有效并持续到该 beat handshake 的时间；它不是字面意义上的 VALID 上升沿，back-to-back VALID 连续为 1 时，新 payload 在前一 beat handshake 后首次出现的采样点就是新的 `valid_begin_time`。
- 提交 schema 相关改动前至少执行：`python3 xdebug/tools/sync_runtime_request_schemas.py --check`、`python3 xdebug/tools/sync_response_schemas.py --check`、`python3 xdebug/tools/sync_action_schema_hints.py --check`、`python3 xdebug/tools/audit_runtime_schema_compatibility.py`、`python3 xdebug/tools/validate_schema.py`、`python3 xdebug/tools/validate_examples.py`，并按变更范围运行 `xdebug.contract` 与对应 skill catalog suite。request schema 必须保持 embedded Draft-7 validator 可执行子集；不能因文件声明 Draft 2020-12 就使用运行时未支持关键字。`xdebug.contract` 涉及真实 FSDB/NPI 时必须整体在沙箱外运行。
- 生成检查发现仓库既有或无关 schema 漂移时，不允许静默忽略、过滤失败或顺手批量重写无关 action；必须区分本次引入与 baseline 漂移，明确报告，并把无关修复拆到独立计划或提交。

## xdebug 外部材料

xdebug 代码架构、添加 action 流程、统一组件、通信协议、log、session、schema 校验、编码要求和测试矩阵，维护在：

- [doc/agents/xdebug/README.md](doc/agents/xdebug/README.md)

修改 xdebug 架构、action、schema、session、transport、log、runtime 或测试体系时，必须检查该说明书是否需要同步更新。

## 环境错误复盘

每次 agent 犯环境相关错误后，必须按下面的模板在**本节**追加一条简短复盘。本节只保留最近发生的条目；累积到影响可读性时，把整条搬移到 [doc/agents/environment-retrospectives.md](doc/agents/environment-retrospectives.md)，并把其中仍然有效的规则合并进下面的规则清单。

格式：

```markdown
### YYYY-MM-DD 环境错误复盘

- 错误现象：
- 误判原因：
- 以后规则：
```

只记录对后续工作有复用价值的环境误判；不要写入 token、cookie、license 内容、完整 session id 或其它敏感信息。

### 来自历史复盘的现行规则

以下规则由 2026-07-08 至 2026-09-07 的 64 条复盘去重提升而来；每条括号内是首次记录日期，完整现场见归档。

**解释器与命令入口**

- 仓库校验、pytest 与实验脚本统一使用已核实的仓库 conda Python 绝对路径（`.conda-xverif/bin/python`、`.conda-xverif/bin/pytest`）；只有明确验证过依赖齐全时才用系统 `python3`，不因相对入口失败而切换解释器。（07-20、08-11、08-14、08-28）
- 运行 Python 脚本前核对解释器与脚本权限，使用显式解释器调用，不依赖文件执行位。（08-14、08-28）
- 仓库测试入口是 catalog-driven pytest plugin；裸 `pytest`、文件路径 pytest 都不是可用入口。（07-14）
- 使用正式 Makefile target 前先核对 `.PHONY` 与真实依赖目标，不按产物名猜 target。（07-17）
- 探测含递归 `$(MAKE)` 的目标时只用 `make -qp`、直接读 Makefile 或专用静态合同检查，不用 `make -n`。（08-30）
- native CLI probe 先核对入口存在（从仓库根目录用 `test -x xdebug/xdebug`）并固定该路径，再读当前 `--help` 拼命令；JSON stdin 固定 `xdebug/xdebug --json -`。入口不存在导致的 127 与 usage 失败都不计入功能或性能结论。（08-12）
- catalog、fixture 与 skill 生成物的校验一律走正式 suite 入口，不按常见命名猜校验脚本；临时 probe 先核对真实导出符号。（08-11、08-12）

**测试执行环境与门禁**

- 每个 focused suite 执行前都用目标 gate 的 `--xverif-plan` 核对 membership 与执行环境要求；不得根据 cost、level、测试语言、相邻 suite 或旧运行记录推断，也不得全仓 gate 含相邻能力为由跳过核对。（07-14、08-04、08-09、08-10、08-12）
- 需要 VCS、NPI、license、真实 FSDB 或 MCP 进程的动作（含 `--xverif-prepare`）首次执行即显式设置 `XVERIF_TEST_EXECUTION_ENV=host` 并在沙箱外运行；沙箱内只跑纯 schema、纯文档或不依赖 EDA 运行库的检查。（07-08、07-10、08-10、08-12、08-16）
- 沙箱内的 EDA 或进程失败先按环境差异处理，不判定为产品回归。（07-08）
- xdist 在首个分配用例即退出时，先用相同 gate 串行运行，区分 fixture preflight、收集/配置错误与真实子进程崩溃；缓存缺失按正式 `--xverif-prepare` 入口补齐后再判断。（07-16）
- 长运行 pytest 返回持久 session id 时只轮询该 session；结果目录存在 `RUNNING` 时先确认 session 状态，不用 `ps -p <session-id>` 推断是否退出。（08-09）
- 启动真实动作前一次核对齐全环境：Makefile `check-env` 与 test catalog `default_env` 一并传入；依赖 `~/.bashrc` 的 VIP 变量通过交互 shell 启动后确认可见，不把路径硬编码回命令或仓库。（07-13、07-20）
- 真实 VCS 动作前同时核对 `command -v vcs`、`VCS_HOME` 与 `$VCS_HOME/linux64/bin/vcs1`。（08-14）
- 查询 `simv` runtime 参数优先查本机安装手册；需实测时用已有仿真产物并显式进入 `-ucli`，只执行可控短命令，不用猜测的 `-help`。（08-14）
- Verdi batch 探测：用经核对的临时 `.tcl` 文件，不用 `-play /dev/stdin` 配 PTY；不以无参数方式探测 `gui_*` proc；`vdCov -batch` 由外层硬超时收口，不调用未经 `info commands` 确认的 `debExit`。（08-14）

**并发、构建与共享工作树**

- 同一工作树的正式 pytest gate/suite 默认串行启动，不并行运行多个 pytest 进程。（08-16）
- 多 agent 改 xdebug 时，任何 contract/session/NPI/runtime suite 启动前先取得所有 owner 的"停止构建"确认；源码冻结后由主线程统一构建，并在冻结期间串行完成 runtime 验证。（08-01、08-12）
- 真实 xdebug/NPI/VIP 回归期间禁止并发构建或链接同一可执行产物；源码、生成产物或 runtime schema 变更后先做生成一致性检查再统一重建。（07-24、08-04）
- 多 owner 变更只有在所有 owner 明确交付并停止修改后才能启动 build、link 或正式测试；进行中只允许 `git diff --check`、文本审阅等不写 build 产物的检查。（08-12）
- 共享工作树遇到跨 owner 的缺失依赖时，先取得明确分工回复；等待期间保持原边界冻结，不自行启动重叠 agent。（08-03）
- 共享工作树并发阶段每次提交前校验 `git diff --cached --name-only` 精确等于本 owner 白名单；发现额外 staged 路径立即停止并协调。（08-03）
- 共享工作树创建缓存入口前先冻结会写 cache 的测试；创建后用 `test -L`、`readlink` 与 manifest 可见性三项验收；发生竞态时完整移动既有目录保留可恢复性。（08-04）

**路径、工作目录与临时工作树**

- 执行真实 EDA/MCP 入口前先按当前工作目录解析文档相对路径，并确认目标可执行文件存在。（07-13）
- 手工复用 Makefile 编译参数时把工作目录固定为 `xdebug/`，或把 `src/`、`build/`、`third_party/` 等活动解析成经核对的绝对路径。（08-03）
- 从仓库任意子目录运行脚本时使用仓库 conda Python 的绝对路径。（08-11）
- 以新目录作为命令工作目录前，先从已存在的父目录单独创建并核对；不依赖命令内部创建自身工作目录。（08-12）
- 工作仓库外的临时仓库：使用已核实的原仓库 conda 绝对路径，把目标工作树置于 `PYTHONPATH` 首位，先完成本仓库统一 clean build 再运行 runtime/FSDB/NPI/native suite，并核对 wrapper 与 binary 实际路径；禁止改用其它工作树的 binary fallback。（08-03、08-04）
- 对工作区外临时仓库打 patch 时，路径从会话 cwd 写成经核对的显式相对路径；首次修改后立即分别检查参考仓库与临时仓库 status。（08-03）
- 手工定位 fixture 缓存时先读 `.xverif-test-cache/fixtures/<id>/current.json` 的 `version`，再解析到 `versions/<version>/resources`，不猜字段名。（08-10）
- 手工复现 xcov session 前分别核对 cache 与 output 生命周期：先显式创建 ignored `cache_dir`，不依赖导出 action 代建。（08-10）

**搜索、清理与文档**

- 任何包含 Markdown 反引号的 shell 搜索模式一律使用单引号；需要组合多个 pattern 时用多个 `-e`，不在双引号中嵌入反引号。（08-04、08-14）
- 诊断报告写入新的时间戳目录；不为复用目录先做删除，清理使用 `gio trash` 等可恢复入口并作为独立后续动作，不与验证命令耦合。（08-11、08-12）
- 可提交文档中的用户目录统一写为 `$HOME`、仓库相对路径或占位符；本机绝对路径只用于执行与检查。（09-07）
- 测试会捕获、映射或发布环境变量的函数时，先用 monkeypatch 把 `os.environ` 替换为独立副本，避免派生变量跨测试泄漏。（09-07）
- 复现 MCP stdio server 时把配置环境变量显式绑定到 server/`timeout` 命令一侧或用 `env ... <server>`；先验证 module import 再解释握手结果。（07-16）
- pynpi coverage：`handle_by_name` 只用于 database instance fullname，不用 L0 绕过 wrapper 查 signal/bin；probe 用仓库 conda Python 并通过 backend 的 handle release helper 清理。（08-11）
