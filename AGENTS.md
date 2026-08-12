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
- 10 个公开 AXI action 的 response schema 统一由 `xdebug/tools/sync_axi_response_schemas.py` 生成；AXI `summary/data`、transaction、config、finding 等业务对象必须在生成器中定义并关闭未知字段，禁止直接手改 checked-in AXI response schema。
- schema 的 AI-facing purpose、使用场景和参数说明由 `skills/xverif/references/xdebug/action-reference.md`、`actions.yaml` 和 `xdebug/tools/sync_action_schema_hints.py` 同步；需要修改提示时先改 source，不在生成 schema 中单独维护漂移副本。
- 所有公开 request 顶层和 `args` 默认使用 `additionalProperties: false`；`query`、`output`、`time_range`、`match` 等嵌套对象也必须显式列出属性并关闭未知字段，除非合同明确要求可扩展对象。
- handler 接受的每个公共参数都必须出现在 action-specific schema 中并实际生效；schema 中公开但实现不支持的参数必须删除或返回明确错误，禁止接受后静默忽略。参数名、enum、默认值、required/conditional-required 语义必须在 native CLI、MCP、schema、example 和 skill 中一致。
- request/response schema 与 `examples/requests`、`examples/responses` 必须成对维护。response 不得在 `summary` 和 `data` 重复同一事实；时间只发布一个 canonical 带单位字符串，截断必须区分完整分析计数与返回行数，并提供 `truncated`、`truncation_scope` 或对应完整性字段。
- request schema 可声明 Draft 2020-12，但运行时使用 embedded Draft-7 兼容子集；新增共享对象、条件约束或 response 投影后必须先更新 generator/source，再运行 runtime-compatibility audit，禁止直接编辑生成产物。
- AXI 时间字段统一使用语义化名称。已确认使用 `valid_begin_time` 表示当前 address/data payload 首次被采样为有效并持续到该 beat handshake 的时间；它不是字面意义上的 VALID 上升沿，back-to-back VALID 连续为 1 时，新 payload 在前一 beat handshake 后首次出现的采样点就是新的 `valid_begin_time`。
- 提交 schema 相关改动前至少执行：`python3 xdebug/tools/sync_runtime_request_schemas.py --check`、`python3 xdebug/tools/sync_axi_response_schemas.py --check`、`python3 xdebug/tools/sync_action_schema_hints.py --check`、`python3 xdebug/tools/audit_runtime_schema_compatibility.py`、`python3 xdebug/tools/validate_schema.py`、`python3 xdebug/tools/validate_examples.py`，并按变更范围运行 `xdebug.contract` 与对应 skill catalog suite。request schema 必须保持 embedded Draft-7 validator 可执行子集；不能因文件声明 Draft 2020-12 就使用运行时未支持关键字。`xdebug.contract` 涉及真实 FSDB/NPI 时必须整体在沙箱外运行。
- 生成检查发现仓库既有或无关 schema 漂移时，不允许静默忽略、过滤失败或顺手批量重写无关 action；必须区分本次引入与 baseline 漂移，明确报告，并把无关修复拆到独立计划或提交。

## xdebug 外部材料

xdebug 代码架构、添加 action 流程、统一组件、通信协议、log、session、schema 校验、编码要求和测试矩阵，维护在：

- [doc/agents/xdebug/README.md](doc/agents/xdebug/README.md)

修改 xdebug 架构、action、schema、session、transport、log、runtime 或测试体系时，必须检查该说明书是否需要同步更新。

## 环境错误复盘

每次 agent 犯环境相关错误后，必须向本文件追加一条简短复盘。格式如下：

```markdown
### YYYY-MM-DD 环境错误复盘

- 错误现象：
- 误判原因：
- 以后规则：
```

只记录对后续工作有复用价值的环境误判；不要写入 token、cookie、license 内容、完整 session id 或其它敏感信息。

### 2026-07-08 环境错误复盘

- 错误现象：新增 xdebug contract 用例在沙箱内启动 FSDB session 时返回 `SESSION_UNHEALTHY child_exited`。
- 误判原因：先在沙箱内运行了会启动 xdebug engine 并读取真实 FSDB/NPI 环境的 pytest。
- 以后规则：凡是会启动 xdebug engine 并访问真实 FSDB/NPI/Verdi 运行库的测试，直接申请沙箱外执行；沙箱内只跑纯 schema、纯文档或不依赖真实 EDA 运行库的检查。

### 2026-07-08 环境错误复盘

- 错误现象：修改 xdebug 后在默认沙箱内执行 `make -C xdebug test-regression`，其中 synthetic existing 回归触发 VCS/license 和 xdebug engine session 健康失败。
- 误判原因：`test-regression` 前段包含普通 schema/unit/contract，但后段会进入真实 VCS/NPI/FSDB 回归；没有在启动前按规则把整条命令视为沙箱外 EDA 动作。
- 以后规则：凡是 xdebug regression/nightly/VIP/existing synthetic 这类可能调用 VCS、NPI、license 或真实 FSDB 的目标，必须一开始就在沙箱外运行；沙箱内失败只作为环境误判处理，不当作产品回归。

### 2026-07-10 环境错误复盘

- 错误现象：在沙箱内执行 `make -C xdebug pytest-contract`，其中 7 个 runtime contract 用例启动真实 FSDB session 时返回 `SESSION_UNHEALTHY child_exited` 或 native open usage 错误。
- 误判原因：把 `pytest-contract` 当成纯 JSON/schema 合同测试，忽略了其中包含依赖 NPI/FSDB engine 的 handler error contract。
- 以后规则：`pytest-contract` 必须整体在沙箱外执行；只有 `schema-test`、静态 consolidation/audit 脚本和明确不启动 session 的检查可在沙箱内运行。

### 2026-07-13 环境错误复盘

- 错误现象：在仓库根目录执行真实 xdebug host 验证时，误把 README 中以 `xdebug/` 为当前目录的 `tools/xdebug` 写成了根目录路径，命令未启动 frontend。
- 误判原因：没有先将文档中的相对入口与当前工作目录、实际可执行文件位置核对。
- 以后规则：执行真实 EDA/MCP 入口前，先用当前工作目录解析文档相对路径，并确认目标可执行文件存在后再运行。

### 2026-07-13 环境错误复盘

- 错误现象：直接执行 AXI VIP fixture 的 `make mrun` 时，因未显式传入 `AXI_REFERENCE_ROOT`、`SVT_VIP_INCDIR` 和 `SVT_VIP_SRCDIR`，在 `check-env` 阶段退出，尚未进入 VCS 编译。
- 误判原因：已经读取 test catalog 的 fixture 默认环境，但直接运行 Makefile 时没有同步带入这些必需变量。
- 以后规则：直接执行真实 VIP fixture 前，先同时核对 Makefile 的 `check-env` 和 test catalog 的 `default_env`，将同一正式入口所需环境一次传全。

### 2026-07-14 环境错误复盘

- 错误现象：修改 AXI schema 后直接用文件路径调用裸 `pytest`，被仓库测试入口门禁在收集前拒绝。
- 误判原因：已知 contract 文件位置，但没有先按 test catalog 选择 `--xverif-gate` 和正式 suite id。
- 以后规则：即使只想运行单个静态 contract，也先用 `pytest --xverif-gate <gate> --xverif-plan` 或 catalog 查明 suite，再从正式 gate/suite 入口执行；不再把文件路径 pytest 当成可用入口。

### 2026-07-16 环境错误复盘

- 错误现象：复现 Codex xverif MCP stdio initialize 时，诊断命令在管道左侧设置了 `PYTHONPATH`，server 进程仍报 `No module named xverif_mcp.server`。
- 误判原因：没有核对 shell 管道中环境变量赋值只作用于所属命令，而不会自动传递给右侧 Python 进程。
- 以后规则：复现 MCP stdio server 时，把配置环境变量显式绑定到 server/`timeout` 命令一侧，或使用 `env ... <server>`；先验证 module import，再解释握手结果。

### 2026-07-16 环境错误复盘

- 错误现象：全仓 `pytest --xverif-gate regression -n auto` 在分发首个用例后报 xdist worker channel closed，看起来像 worker 崩溃。
- 误判原因：未先以同一 gate 的串行运行取得 pytest 的原始 preflight 错误；实际原因是 7 个 required fixture 的指纹缓存缺失，各 worker 抛出 `UsageError` 后被 xdist 包装成内部错误。
- 以后规则：遇到 xdist 在首个分配用例即退出时，先以相同 gate 串行运行，区分 fixture preflight、收集/配置错误和真实子进程崩溃；缓存缺失按 catalog 正式 `--xverif-prepare` 入口补齐后再判断回归结果。

### 2026-07-17 环境错误复盘

- 错误现象：新增 combined handler 后直接调用不存在的 `make -C xdebug xdebug-engine` target，构建未启动。
- 误判原因：根据产物名称猜测 Makefile target，没有先检查当前 Makefile 的公开目标。
- 以后规则：修改 xdebug C++ 后先核对 Makefile 的 `.PHONY` 和真实依赖目标；engine-only 构建使用当前存在的 `internal-engines`，不按产物名猜 target。

### 2026-07-19 环境错误复盘

- 错误现象：使用仓库 Miniconda 环境准备 generated fixture 时手工收窄 `PATH`，导致宿主已配置的 `vcs` 不可见，fixture 在编译前报 `vcs: command not found`。
- 误判原因：为固定 Python 解释器同时覆盖了完整宿主 `PATH`，忽略了 EDA 工具入口依赖登录环境中的路径配置。
- 以后规则：真实 VCS/NPI/VIP 回归只用绝对路径固定 conda Python/pytest，不覆盖宿主 `PATH`；启动前分别核对 Python 解释器和 `vcs` 可见性。

### 2026-07-20 环境错误复盘

- 错误现象：VIP 环境变量已写入 `~/.bashrc`，但沙箱外非交互命令准备 APB/AXI fixture 时仍报告 VIP 依赖不可用。
- 误判原因：误以为沙箱外执行会自动读取交互 shell 的 `~/.bashrc`；实际非交互 shell 没有加载其中新增的三个 VIP 变量。
- 以后规则：依赖 `~/.bashrc` 的真实 VIP 动作先通过交互 shell 启动，并在 prepare 前核对三个 VIP 变量可见；不把路径重新硬编码到命令或仓库。

### 2026-07-20 环境错误复盘

- 错误现象：执行 schema runtime compatibility audit 和 example validation 时使用系统 `python3`，因缺少 `jsonschema` 在脚本导入阶段退出。
- 误判原因：只按文档命令字面调用解释器，没有先核对仓库 `.conda-xverif` 已提供这些校验脚本的 Python 依赖。
- 以后规则：仓库 Python 校验和 pytest 默认使用 `.conda-xverif/bin/python` 或其中的 pytest；只有明确验证过依赖齐全时才使用系统 `python3`。

### 2026-07-24 环境错误复盘

- 错误现象：沙箱外 AXI VIP 回归运行期间，沙箱内并发链接同一个 `xdebug/xdebug` 可执行文件，测试进程短暂遇到 `Permission denied`。
- 误判原因：把编译和真实回归视为互不影响，忽略它们共享工作区中的同一可执行产物。
- 以后规则：真实 xdebug/NPI/VIP 回归运行期间禁止并发构建或链接 xdebug；先完成构建，再串行启动宿主回归。

### 2026-08-03 环境错误复盘

- 错误现象：在临时仓库重建时，通过 functions.exec 嵌套调用 apply_patch，误以为 apply_patch 会继承 exec_command 的 workdir，短暂作用到原始参考仓库；已立即原样恢复并确认参考仓库相关文件干净。
- 误判原因：混淆了 exec_command 子调用工作目录与 apply_patch 工具基于会话 cwd 解析相对路径的规则。
- 以后规则：对工作区外临时仓库使用 apply_patch 时，patch 文件路径必须从会话 cwd 写成经核对的显式相对路径；每次首次修改后立即分别检查参考仓库与临时仓库 status。

### 2026-08-03 环境错误复盘

- 错误现象：在临时仓库运行正式 pytest suite 时，首次使用了该临时仓库中不存在的 `.conda-xverif/bin/pytest`，命令未启动。
- 误判原因：把原始仓库的本地 Python 环境布局误认为会随临时 Git 仓库一同存在，没有先核对解释器路径。
- 以后规则：工作仓库外的临时仓库运行正式测试前，先确认测试解释器的绝对路径；临时仓库未包含环境时，使用已核实的原始仓库绝对 conda pytest 路径，不猜测相对路径。

### 2026-08-03 环境错误复盘

- 错误现象：等待缺失 fixture 由其它 agent 恢复时，在主 agent 的 owner 指派消息到达前又启动了一个处理同一路径的子 agent，形成短暂的重叠写入风险。
- 误判原因：已知该路径需要跨边界协调，却没有等主 agent 明确回复 owner 状态就自行扩展任务范围。
- 以后规则：共享工作树中遇到跨 owner 的缺失依赖时，必须先取得主 agent 的明确分工回复；等待期间保持原边界冻结，不以推进速度为由另行启动重叠 agent。

### 2026-08-03 环境错误复盘

- 错误现象：临时仓库使用原始仓库 conda pytest 运行 `testinfra.unit` 时，editable plugin 提前缓存了原始仓库的 `testinfra` 包，导致用例读取了错误工作树的 runner 清单。
- 误判原因：只固定了 pytest 解释器，没有核对 editable plugin 在 pytest 调整 rootdir 前的模块解析来源。
- 以后规则：用另一个工作树的 conda pytest 验证临时仓库时，显式将临时仓库置于 `PYTHONPATH` 首位，并用失败差异与模块来源确认测试读取的是目标工作树。

### 2026-08-03 环境错误复盘

- 错误现象：在临时重建仓库执行 Python 校验时再次调用仓库相对路径 `.conda-xverif/bin/python`，因临时仓库不携带本地环境而未启动校验。
- 误判原因：没有在每类 Python 校验入口执行前解析并核对解释器的绝对路径，沿用了原工作树的相对环境布局。
- 以后规则：`<work-tmp>/` 下的重建仓库统一使用已核实的原仓库 conda Python 绝对路径，并把临时仓库置于 `PYTHONPATH` 首位；禁止静默切换系统 Python。

### 2026-08-03 环境错误复盘

- 错误现象：在仓库根目录执行 xdebug C++ `-fsyntax-only` 时直接复用了 Makefile 中以 `xdebug/` 为工作目录的 `src/...` 相对输入，三个源文件均在编译前报路径不存在。
- 误判原因：只复用了编译 flags，没有同步 Makefile 目标所依赖的工作目录语义。
- 以后规则：手工复用 xdebug Makefile 编译参数时必须把工作目录固定为 `<repo>/xdebug`，或先把 `src/`、`build/`、`third_party/` 等全部解析成经核对的绝对路径。

### 2026-08-03 环境错误复盘

- 错误现象：共享重建工作树中另一个 owner 已暂存 runtime 文件时，主线程仅检查了目标文档的 status 便执行提交，错误地把共享 index 中既有的 29 个文件纳入文档 commit；在推送前发现并原样保留工作树后重写提交边界。
- 误判原因：把“显式 `git add` 当前文件”等同于“index 只包含当前文件”，提交前虽打印了 staged 清单，却没有在看到额外路径时中止。
- 以后规则：共享工作树并发阶段每次提交前必须验证 `git diff --cached --name-only` 精确等于本 owner 白名单；发现任何额外 staged 路径立即停止并协调 owner，不能继续 commit。

### 2026-08-04 环境错误复盘

- 错误现象：为临时重建仓库接入已授权的共享 fixture cache 时，另一个测试进程在“确认目标不存在”和创建软链接之间生成了同名本地目录，导致链接被创建到目录内部而未成为 FixtureStore 的缓存根。
- 误判原因：把分离的存在性检查和 `ln -s` 当成原子操作，没有在创建后立即断言目标自身的文件类型。
- 以后规则：共享工作树创建缓存入口时先冻结会写 cache 的测试；创建后必须用 `test -L`、`readlink` 和所需 manifest 可见性三项一起验收。若发生竞态，完整移动既有目录保留可恢复性，不覆盖或删除其中内容。

### 2026-08-04 环境错误复盘

- 错误现象：临时重建仓库尚未完成统一构建时先运行 `xdebug.counter_statistics` 正式 runtime suite，wrapper 因本仓库 `xdebug/xdebug` 不存在以 127 退出，未进入产品逻辑。
- 误判原因：把 Python 合同和源码 syntax closure 当成 runtime suite 已具备可执行产物，没有先核对正式 wrapper 解析到的目标 binary。
- 以后规则：临时重建仓库的 runtime、FSDB、NPI 或 native XOUT suite 必须在源码冻结并完成本仓库统一 clean build 后运行；启动前先核对 wrapper 与 binary 的实际路径，禁止改用其它工作树 binary fallback。

### 2026-08-04 环境错误复盘

- 错误现象：在双引号包裹的 `rg` 搜索模式中写入 Markdown 反引号，shell 再次把 action 标题片段当作命令替换执行。
- 误判原因：组合多个报告标题模式时没有继续遵守仓库既有的反引号搜索规则。
- 以后规则：任何包含 Markdown 反引号的 shell 搜索模式一律使用单引号；需要组合变量时拆成多个不含反引号的模式，不在双引号中嵌入反引号。

### 2026-08-04 环境错误复盘

- 错误现象：子 agent 正在重生成 internal runtime manifest/schema 时，主线程用旧二进制并行运行 AXI VIP，旧二进制读取新 manifest 后返回 `SCHEMA_VALIDATION_CONFIG_ERROR`。
- 误判原因：只冻结了二进制，忽略 runtime schema 会在进程启动或请求时从共享工作树动态读取；源码和生成产物更新同样会使已构建产物失配。
- 以后规则：任何 runtime schema、manifest 或 generator owner 修改期间禁止并行真实回归；owner 冻结后先执行生成一致性检查，再统一重建，之后才启动宿主回归。

### 2026-08-04 环境错误复盘

- 错误现象：统一构建后对 `xdebug.axi_vip` 做 focused 验证时误用 `--xverif-gate regression`，被 suite membership 门禁在收集前拒绝。
- 误判原因：沿用此前大部分 xdebug runtime suite 的 gate，没有先从当前 catalog 或 `--xverif-plan` 核对 AXI VIP 实际属于 nightly。
- 以后规则：每个 focused suite 即使本轮此前运行过，也必须在执行前以当前 catalog 或目标 gate 的 `--xverif-plan` 核实 membership；不能依据相邻 suite 或旧运行记录推断 gate。

### 2026-08-04 环境错误复盘

- 错误现象：在临时重建仓库运行 `xdebug.native_xout_all` 时，第一次遗漏已确认的 `XIF_AGENT` 导致 xif fixture 指纹 cache miss，第二次遗漏 `XDEBUG_XOUT_PHASE` 导致测试在采集前拒绝启动。
- 误判原因：只复用了 host、Python 与 gate 参数，没有从 native XOUT runner 和 fixture default environment 重新核对该 suite 的完整显式环境合同；临时仓库绝对路径还会参与 XIF fixture 指纹。
- 以后规则：native XOUT 最终采集必须一次显式传入 `XVERIF_TEST_EXECUTION_ENV=host`、已缓存构建对应的 `XIF_AGENT`、`XDEBUG_XOUT_PHASE=final` 和当前重建仓库 `PYTHONPATH`；启动前先核对 runner phase enum 与 fixture fingerprint 环境，不以 preflight 失败逐项补参数。

### 2026-08-09 环境错误复盘

- 错误现象：host regression 的外层执行单元返回持久执行 session id 后，误把外层单元完成判断为 pytest 提前结束，并把 session id 当作进程 PID 查询。
- 误判原因：混淆了 functions.exec cell、exec_command 持久 session 与宿主进程 PID 三种标识。
- 以后规则：长运行 pytest 返回 SESSION_ID 时只用 write_stdin 继续轮询该 session；结果目录存在 RUNNING 时先确认持久 session 状态，不用 ps -p session-id 推断测试是否退出。

### 2026-08-09 环境错误复盘

- 错误现象：运行 `xcov.unit` focused suite 时误用 fast gate，被 suite membership 门禁在收集前拒绝。
- 误判原因：根据 suite 的 cost=fast 推断 gate membership，没有先查询当前 catalog plan；cost class 不等于 gate。
- 以后规则：focused suite 执行前先用目标 gate 的 `--xverif-plan` 核对 membership；不能根据 cost、level 或相邻 suite 推断 gate。

### 2026-08-10 环境错误复盘

- 错误现象：准备 `xcov.modinfo_complex` fixture 时遗漏 `XVERIF_TEST_EXECUTION_ENV=host`，测试基础设施在启动 VCS 前拒绝执行。
- 误判原因：只按 fixture id 调用了正式 prepare 入口，没有同步带上真实 EDA fixture 的显式 host 执行合同。
- 以后规则：所有需要 VCS、NPI 或 license 的 `--xverif-prepare` 命令都必须在首次执行时显式设置 `XVERIF_TEST_EXECUTION_ENV=host`。

### 2026-08-10 环境错误复盘

- 错误现象：复现 `export.code_coverage` 失败详情时，诊断脚本向 `SessionManager.open` 传入尚未创建的 ignored cache 目录，未进入 NPI 即返回错误。
- 误判原因：把导出 action 会自动创建的 `output.path` 语义误套到 session `cache_dir`，忽略后者要求调用前已存在。
- 以后规则：手工复现 xcov session 前分别核对 cache 与 output 生命周期；先显式创建 ignored `cache_dir`，不依赖导出 action 代建。

### 2026-08-10 环境错误复盘

- 错误现象：读取正式 fixture 当前版本时预设 `current.json` 包含通用 path 字段，诊断命令未解析出 VDB 路径便退出。
- 误判原因：没有先按 FixtureStore 的真实指针 schema 读取 `version` 字段，错误套用了其它缓存入口的路径表达。
- 以后规则：手工定位 `.xverif-test-cache/fixtures/<id>` 时先读取 `current.json.version`，再解析到 `versions/<version>/resources`；不猜测 path/current/version_path 字段。

### 2026-08-10 环境错误复盘

- 错误现象：运行 `xcov.mcp_integration` focused suite 时沿用 regression gate，被 suite membership 门禁拒绝。
- 误判原因：按本轮其它 xcov suite 的 gate 推断 MCP 集成 suite，未先核对当前 catalog 中它只属于 nightly。
- 以后规则：每个 focused suite 启动前都用目标 gate 的 `--xverif-plan` 核对当前 membership；同一子系统和同一轮已运行过的相邻 suite 也不能替代核对。

### 2026-08-10 环境错误复盘

- 错误现象：实现 branch XOUT v2 后直接以 regression gate 运行 `xcov.urg_backend`，被 suite membership 门禁拒绝。
- 误判原因：只检查了 catalog 中的 suite 定义和既有经验，没有在执行 focused suite 前查询当前 gate plan。
- 以后规则：每次运行 focused suite 都先查询目标 gate 的 `--xverif-plan`；若产品要求调整 membership，显式修改并测试 catalog gate 合同，不通过 cost 分类伪装。

### 2026-08-11 环境错误复盘

- 错误现象：生成真实 URG 样例时，把删除旧临时目录与 URG 调用组合在同一命令，整条命令在启动 EDA 工具前被安全策略拒绝。
- 误判原因：没有把可选清理与必需的只新增诊断动作隔离，导致无关的删除动作阻断正式工具调用。
- 以后规则：诊断报告统一写入新的时间戳目录；不为复用目录先做删除，清理作为独立且明确授权的后续动作。

### 2026-08-11 环境错误复盘

- 错误现象：为验证 toggle coverage 能否按名直达，向 pynpi L0 `cov_l0.handle_by_name` 传入 signal 名后触发 vendor `libNPI.so` SIGSEGV；后续只读方法探测的清理代码又误调用了不存在的 `Handle.release()`。
- 误判原因：只依据 C header 中通用的 `scope` 参数推断 coverage object 可按名查询，没有先遵守 Python wrapper 明确限定的“database 上按 instance fullname 查询”合同；同时未复用仓库已有的 `release_if_handle` 生命周期入口。
- 以后规则：Python coverage 的 `handle_by_name` 只用于 database instance fullname；不得用 L0 绕过 wrapper 尝试 signal/bin 查询。临时 NPI probe 也统一通过 backend 的 handle release helper 清理，不猜测 wrapper 方法。

### 2026-08-11 环境错误复盘

- 错误现象：复核 pynpi coverage instance lookup 时使用系统 Python 3.14，`cov.open` 在 `_cov_l0.so` 的 SWIG 字符串转换中触发 SIGSEGV，尚未进入 lookup。
- 误判原因：执行临时 inline probe 时只设置了 Verdi `PYTHONPATH`，没有遵守仓库已确认的 `.conda-xverif` Python 兼容环境合同。
- 以后规则：所有 pynpi coverage probe 都使用仓库 `.conda-xverif/bin/python`，启动前同时核对解释器版本和 Verdi Python 路径；系统 Python 的 SWIG 崩溃不作为 NPI coverage 产品结论。

### 2026-08-12 环境错误复盘

- 错误现象：C06 三个 owner 尚在共享工作树修改 cache、benchmark 和算法源码时，主线程提前启动 `make -C xdebug internal-engines`；已在首个对象编译阶段立即中止，未完成链接或启动回归。
- 误判原因：把可随时中止的增量编译当作只读检查，忽略编译会写共享 build 产物，且源码仍可能在编译期间变化。
- 以后规则：多 owner 阶段只有在所有 owner 明确交付并停止修改后才能启动任何 build、link 或正式测试；进行中只允许 `git diff --check`、文本审阅和不写 build 产物的静态检查。

### 2026-08-12 环境错误复盘

- 错误现象：运行 `xverif_mcp.process` focused suite 时未显式设置 `XVERIF_TEST_EXECUTION_ENV=host`，被 required suite preflight 在收集前拒绝。
- 误判原因：按该 suite 无真实 NPI/EDA 能力推断可直接执行，忽略 catalog 对进程集成测试声明了 host 执行边界。
- 以后规则：focused suite 启动前除核对 gate membership 外，还必须从 plan/catalog 核对执行环境要求；凡 preflight 要求 host，首次命令即显式设置 `XVERIF_TEST_EXECUTION_ENV=host`。

### 2026-08-12 环境错误复盘

- 错误现象：C02 多 owner 并行实现期间，主线程在子 agent 尚可能触发构建时启动 `xdebug.contract`，19 个用例和 2 个 teardown 在共享 `xdebug/xdebug` 链接窗口报 `Permission denied`。
- 误判原因：只把主线程显式启动的测试视为并发边界，没有先确认所有子 agent 已停止会重建同一可执行产物的命令。
- 以后规则：多 agent 修改 xdebug 时，任何 contract/session/NPI/runtime suite 启动前必须先取得所有 owner 的“停止构建”确认；随后由主线程统一构建，并在源码冻结期间串行完成 runtime 验证。

### 2026-08-12 环境错误复盘

- 错误现象：运行 `xdebug.cpp_unit` focused suite 时先尝试了 fast gate，被 suite membership 门禁在收集前拒绝。
- 误判原因：根据 suite 的 unit 层级和 C++ 定向测试性质推断 fast membership，没有先查询当前 catalog gate plan；测试层级不等于 gate。
- 以后规则：每次运行 focused suite 前先用候选 gate 的 `--xverif-plan` 核对当前 membership；不能根据 level、cost 或测试语言推断 gate。

### 2026-08-12 环境错误复盘

- 错误现象：共享工作树仍有其它 pytest/build 流程时启动 `xdebug.session`，后段 stdio-loop 用例在并发链接 `xdebug/xdebug` 的窗口遇到 `Permission denied`，相邻启动失败用例也取得空响应。
- 误判原因：启动前只确认当时没有活跃 `make`/`g++`，但没有等待其它会在后续阶段触发构建的 pytest 流程结束，未冻结整个 runtime suite 的共享可执行产物。
- 以后规则：运行 xdebug session/NPI/runtime suite 前不仅要确认没有即时编译进程，还必须确认共享工作树中其它可能触发 xdebug 构建的 pytest 流程已全部结束；统一构建完成后再串行启动 runtime suite。

### 2026-08-12 环境错误复盘

- 错误现象：准备在新的临时 build 目录运行 VCS 时，直接把尚未创建的目录设为命令工作目录，进程在 shell 启动前因路径不存在而失败。
- 误判原因：把命令内部的 `mkdir` 误认为能先于执行器切换工作目录生效。
- 以后规则：以新目录作为命令工作目录前，必须先从已存在的父目录单独创建并核对目标目录；不能在同一次调用中依赖命令内部创建自身工作目录。

### 2026-08-12 环境错误复盘

- 错误现象：对 `xverif_mcp.real_fullchain` 做 focused 验证时误用 regression gate，被 suite membership 门禁在收集前拒绝。
- 误判原因：根据全仓 regression 中相邻 MCP/xcov 用例推断了 real-fullchain membership，没有在 focused 启动前查询该 suite 的准确 gate。
- 以后规则：每次 focused suite 启动前都从当前 catalog plan 核对目标 suite 的 gate；全仓 gate 已包含相邻能力不能替代单 suite membership 核对。

### 2026-08-11 环境错误复盘

- 错误现象：新增大型 fixture catalog 后猜测执行不存在的 `testinfra/tools/validate_catalog.py`，命令未进入校验逻辑。
- 误判原因：根据目录职责臆测独立校验脚本，没有先从仓库正式 pytest catalog suite 或已有文件中确认入口。
- 以后规则：fixture/catalog 变更先查询 `pytest --xverif-gate fast --xverif-plan` 与 `testinfra.unit` 正式 suite；不按常见命名猜测校验脚本。

### 2026-08-11 环境错误复盘

- 错误现象：在仓库 `tmp/` 子目录启动大型 URG 基准脚本时使用仓库相对 `.conda-xverif/bin/python`，命令在进入脚本和 EDA 工具前因解释器路径不存在退出。
- 误判原因：切换工作目录后仍沿用只在仓库根成立的 Python 相对路径，没有在启动前按当前 cwd 解析入口。
- 以后规则：从仓库任意子目录运行实验脚本时使用已核实的仓库 conda Python 绝对路径；不因相对入口失败切换系统 Python。
