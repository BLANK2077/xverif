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
