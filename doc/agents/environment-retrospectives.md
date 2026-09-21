# 环境错误复盘归档

本文件是 `AGENTS.md`「环境错误复盘」一节的历史归档，收录 64 条已发生的环境误判记录，按发生时间排列，每条格式为「错误现象 / 误判原因 / 以后规则」。

**这些条目是历史记录，不是现行规则清单。** 仍然有效的规则已去重并提升到 [`AGENTS.md`](../../AGENTS.md) 的「环境错误复盘」一节；本文件用于追溯某条规则的来历、核对当时的完整现场，或确认某个坑是否已经踩过。

维护方式：新的环境误判先按模板追加到 `AGENTS.md`；当该节再次累积到影响可读性时，整条搬移到本文件，并把其中仍然有效的规则合并进 `AGENTS.md` 的规则清单。

---

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

- 错误现象：清理一次明确中断留下的 result/staging 临时目录时，使用递归删除并与后续验证串在同一命令，整条命令在启动前被安全策略拒绝。
- 误判原因：目标虽已精确核对且只属于本轮诊断，仍没有优先使用可恢复的 trash，也把非必需清理和必需验证耦合到同一个执行单元。
- 以后规则：中断诊断产生的临时目录先逐项核对，再使用 `gio trash` 等可恢复入口单独处理；验证命令另行执行，不让清理策略阻断测试。

### 2026-08-12 环境错误复盘

- 错误现象：在仓库根目录测量 `schema` action 的 batch summary 时再次使用了不存在的 `xdebug/tools/xdebug`，命令以 127 退出，未启动产品逻辑。
- 误判原因：沿用了以 `xdebug/` 为工作目录时的 README 相对入口，没有在性能命令前核对根目录下的实际可执行文件。
- 以后规则：从仓库根目录执行 native xdebug probe 前先用 `test -x xdebug/xdebug` 核对入口，并固定使用该路径；不存在的 wrapper 入口失败不作为性能或功能结果。

### 2026-08-12 环境错误复盘

- 错误现象：找到正确 native binary 后仍用不存在的 `--output-format json` 参数测量 batch summary，CLI 返回 usage，未进入 `schema` action。
- 误判原因：根据其它 surface 的输出参数猜测 native CLI flags，没有先读取当前 `xdebug --help` 的 `--json|--text` 合同。
- 以后规则：native CLI probe 在拼接性能测量命令前先运行并读取当前 `--help`，JSON stdin 固定使用已确认的 `xdebug/xdebug --json -`；usage 失败不得计入产品测量。

### 2026-08-12 环境错误复盘

- 错误现象：C06 三个 owner 尚在共享工作树修改 cache、benchmark 和算法源码时，主线程提前启动 `make -C xdebug internal-engines`；已在首个对象编译阶段立即中止，未完成链接或启动回归。
- 误判原因：把可随时中止的增量编译当作只读检查，忽略编译会写共享 build 产物，且源码仍可能在编译期间变化。
- 以后规则：多 owner 阶段只有在所有 owner 明确交付并停止修改后才能启动任何 build、link 或正式测试；进行中只允许 `git diff --check`、文本审阅和不写 build 产物的静态检查。

### 2026-08-12 环境错误复盘

- 错误现象：C08 统一生成检查时，根据生成文档名称猜测了不存在的 `skills/xverif/scripts/generate_xdebug_action_refs.py`，命令未启动。
- 误判原因：把 checked-in generated action 索引误认为有独立脚本入口，没有先从实际文件和正式 skill suite 核对维护方式。
- 以后规则：skill 生成内容先通过 `rg --files skills` 与对应 catalog suite 确认真实 owner/入口；不存在独立生成器时运行正式 skill suite，不按产物名猜脚本。

### 2026-08-12 环境错误复盘

- 错误现象：复核新增 fixture/catalog 时，手写 Python probe 导入了不存在的 `testinfra.xverif_test.catalog.load_catalog`，未进入 registry 加载。
- 误判原因：根据模块用途猜测公共 helper 名，没有先检查实际 API 或直接使用正式 catalog suite。
- 以后规则：testinfra catalog/fixture 校验统一先查 `testinfra.unit` 的正式测试入口并从 gate/suite 执行；临时 Python probe 只有在核对真实导出符号后才使用。

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

### 2026-08-14 环境错误复盘

- 错误现象：直接执行 `skill-creator/scripts/init_skill.py` 和 `quick_validate.py` 时因文件没有执行位而返回 `Permission denied`。
- 误判原因：照用 skill 文档中的直接执行示例，没有先检查本机安装副本的脚本权限，也没有显式选择仓库 Python 环境。
- 以后规则：调用本机 skill-creator Python 脚本前先核对解释器和文件权限；仓库任务统一使用 `.conda-xverif/bin/python <script>`，不依赖脚本执行位。

### 2026-08-14 环境错误复盘

- 错误现象：创建 xsimdebug skill 后查询 fast gate plan 时误用裸 `pytest`，shell 返回 `pytest: command not found`。
- 误判原因：没有在每次仓库测试入口执行前坚持使用已确认的仓库 Conda pytest。
- 以后规则：仓库 pytest 始终使用 `.conda-xverif/bin/pytest`；即使只是查询 gate plan，也不调用裸 `pytest`。

### 2026-08-14 环境错误复盘

- 错误现象：复核 VCS UCLI 能力时直接执行 `vcs -ID`，当前 shell 的 `VCS_HOME` 指向缺少 `bin/vcs1` 的 `X-2025.06-SP1/linux`，命令未进入版本查询。
- 误判原因：只核对了 `vcs` wrapper 在 `PATH` 中可见，没有先核对 `VCS_HOME` 与实际 `linux64/bin/vcs1` 安装布局一致。
- 以后规则：真实 VCS 编译或版本查询前同时核对 `command -v vcs`、`VCS_HOME` 和 `$VCS_HOME/linux64/bin/vcs1`；已有 `simv` 的 UCLI 只读实验不因编译入口环境错误改用其它模拟器。

### 2026-08-14 环境错误复盘

- 错误现象：为查询 VCS runtime 的 `-l`/`-k` 选项直接执行已有 `simv -help`，该 runtime 没有按预期打印帮助，而是启动并跑完了仿真。
- 误判原因：把编译器 wrapper 的帮助入口类推到生成的 simulator executable，没有先用无执行副作用的手册搜索或隔离短交互验证。
- 以后规则：查询 `simv` runtime 参数时优先查当前安装手册；需确认行为时使用已有仿真产物并显式进入 `-ucli`，只执行可控的短命令后退出，不用猜测的 `-help` 参数。

### 2026-08-14 环境错误复盘

- 错误现象：为定位 xsimdebug 文档行号，在双引号 `rg` 模式中包含 Markdown 反引号，shell 把其中的 `-l` 和 `-k` 当成命令替换执行。
- 误判原因：组合多个搜索词时再次忽略了仓库已有的反引号搜索规则。
- 以后规则：所有包含 Markdown 反引号的搜索模式一律使用单引号；只为组合多个 pattern 时使用多个 `-e`，不改用双引号包裹反引号。

### 2026-08-14 环境错误复盘

- 错误现象：使用 Verdi `-play /dev/stdin` 配合 PTY 探测 Tcl 命令时，输入仅被回显且进程持续等待，脚本没有执行。
- 误判原因：把普通文件形式的 `-play` 行为类推到 PTY 标准输入，没有先验证 Verdi 对 `/dev/stdin` 的读取和结束语义。
- 以后规则：Verdi batch Tcl 探测使用经核对的临时 `.tcl` 文件；不再把 `-play /dev/stdin` 与交互 PTY 组合使用。

### 2026-08-14 环境错误复盘

- 错误现象：在 Verdi coverage batch Tcl 探测中无参数调用 `gui_process_add_edit_annotations`，命令打开交互对话框并持续等待。
- 误判原因：只根据 `info args` 为空判断 proc 可安全探测，没有先检查其 Tcl body 是否触发 GUI 交互。
- 以后规则：batch 模式不以无参数执行方式探测 `gui_*` proc；先读 Tcl body，只对确认无对话框的原生命令做参数验证，并为每次 Verdi batch probe 设置硬超时。

### 2026-08-14 环境错误复盘

- 错误现象：在 `vdCov -batch` Tcl 脚本末尾沿用普通 Verdi 的 `debExit`，coverage executable 报 unknown command，最终由外层 timeout 终止。
- 误判原因：把 Verdi/NPI 手册中的通用 Tcl 退出命令直接套到独立 `vdCov` executable，没有先确认该 surface 的命令集。
- 以后规则：`vdCov -batch` 实验统一由外层硬超时收口，脚本不调用未经 `info commands` 确认的 `debExit`；完成输出后使用该 surface 已验证的退出入口。

### 2026-08-16 环境错误复盘

- 错误现象：并行启动多个正式 pytest gate 时，多个进程同时裁剪 `.xverif-test-results`，其中一个进程在目录枚举后、`stat()` 前遇到目录被另一进程删除，产生 pytest INTERNALERROR。
- 误判原因：把不同 focused suite 视为只读且可安全并行，忽略了它们共享同一个结果目录并在启动阶段执行无并发保护的保留数量裁剪。
- 以后规则：同一工作树的正式 pytest gate/suite 默认串行启动；在结果目录裁剪实现具备竞态容错前，不并行运行多个 pytest 进程。

### 2026-08-16 环境错误复盘

- 错误现象：运行 `xcov.unit` focused suite 时未显式设置 `XVERIF_TEST_EXECUTION_ENV=host`，其中 exclusion 用例实际加载了真实 NPI；本次因执行环境 unrestricted 而通过，但命令没有明确表达仓库的 host 合同。
- 误判原因：依据 catalog 的 `capabilities: [child_process]` 把整个 unit suite 当成纯 Python，未同时核对 suite 内 exclusion 测试的真实 NPI 行为。
- 以后规则：focused suite 启动前除 catalog capabilities 外还要核对测试内容；`xcov.unit` 按包含真实 exclusion NPI 的整体处理，首次命令即显式设置 `XVERIF_TEST_EXECUTION_ENV=host`。

### 2026-08-28 环境错误复盘

- 错误现象：直接执行 skill-creator 的 `quick_validate.py` 时因脚本没有可执行位返回 `Permission denied`，校验未启动。
- 误判原因：按文档展示的脚本路径直接执行，没有先检查文件权限并显式选择 Python 解释器。
- 以后规则：运行 Python skill 校验脚本前先核对解释器和脚本权限；未设置可执行位时使用已确认的仓库 Python 显式调用，不把脚本路径当作 executable。

### 2026-08-30 环境错误复盘

- 错误现象：为检查 XAMBA fixture 展开的命令而对 `run` 目标使用 `make -n`，包含递归 `$(MAKE)` 的 recipe 仍被 Make 执行，并在尚未提交的新 filelist 版本门禁处退出。
- 误判原因：把 `-n` 当成所有 recipe 都绝不执行，忽略 GNU Make 会执行包含递归 Make 标记的命令行。
- 以后规则：含递归 Make 的目标只用 `make -qp`、直接读取 Makefile 或专用静态合同检查变量展开；不再用 `make -n` 探测这类 `run/prepare` 目标。

### 2026-09-07 环境错误复盘

- 错误现象：新增 SDK-free timeout 单元测试调用环境映射函数后，将非法 XVERIF_LOOP_REQUEST_TIMEOUT_SEC 留在 pytest 进程，导致后续四项 session guard 检查失败。
- 误判原因：只用 monkeypatch 管理公开变量，忽略被测函数直接向 os.environ 写入内部变量，teardown 不会自动撤销这些写入。
- 以后规则：测试会捕获、映射或发布环境变量的函数时，先用 monkeypatch 将 os.environ 替换为独立副本；不能只跟踪输入变量而让派生变量跨测试泄漏。

### 2026-09-07 环境错误复盘

- 错误现象：最终验收文档提交被本机 Git 路径门禁拒绝，原因是记录了带本机用户名的绝对 skill 安装路径。
- 误判原因：把本地执行证据的实际路径直接写入可提交文档，没有先转换成可移植表达。
- 以后规则：提交文档中的用户目录统一写为 $HOME、仓库相对路径或占位符；本机绝对路径只用于执行与检查，不写入版本控制文档。
