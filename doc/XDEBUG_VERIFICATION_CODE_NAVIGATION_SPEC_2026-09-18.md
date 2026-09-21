# xdebug 验证代码导航：NPI 能力验证与实施规格

日期：2026-09-18。状态：探针、临时持久化 demo 与100题对照完成，方案待实施。本文中的 `code.*` 均为拟新增 action，当前 xdebug 尚未提供这些接口。

大型 AXI 临时 demo、测试和两个代理的对照结果见 [实验报告](XDEBUG_NPI_DEMO_COMPARISON_REPORT_2026-09-18.md)。实验报告区分参试 v1 与实验结束后修正的 v2；不把原型当成已上线 action。

用户追加的持久化 session、100道题及两个全新代理的实际作答结果见 [持久化与100题报告](XDEBUG_NPI_SESSION_100_COMPARISON_REPORT_2026-09-18.md)。第16节补充生命周期与验收要求；正式产品实施范围仍由本文第一期/第二期合同限定。

本轮范围：读取仓库、本机 Synopsys 官方材料和已有 daidir，运行临时探针，编写本文。随后按用户追加要求，在临时目录制作 demo 和测试，并开展两个独立代理的理解对照实验。未修改产品源码、schema、仓库测试或构建配置，未重新编译仿真 fixture。已有工作区改动不属于本次交付。

## 1. 结论和交付目标

NPI Language Model 可以成为 AI 访问验证代码的结构化入口。本机真实数据库已验证 package、class、声明成员、继承、类型别名、类型参数、方法形参、部分默认值、源码位置、变量使用位置和部分静态调用目标。

建议增加独立的 `code.*` action 族。第一期提供 `code.search`、`code.describe`、`code.members`、`code.inheritance`、`code.source`；第二期增加经过明确边界约束的 `code.references` 和 `code.calls`。前端继续使用现有 JSON action、session、MCP、transport 与 engine 转发机制。

这项能力回答的是“本次编译数据库里有哪些声明，它们是什么关系，证据在哪里”。不能据此回答某一仿真时刻实际创建了哪些 UVM 对象、factory 最终覆盖成什么类型、某次虚方法实际调用了哪个实现。

第一期完成后，AI 应能连续完成以下任务，无需猜文件名或依靠文本命中判断类型：

1. 找到 `xif_event_pkg` 中的环境和 sequence 类。
2. 列出环境直接声明的 agent、FIFO 和方法。
3. 将 `rdy_agent` 的 typedef 追到 `xif_agent_pkg` 中的 `xif_agent` 定义。
4. 从 `xif_event_rdy_seq` 追到声明 `send_item` 的基类。
5. 获取 `send_item` 的六个形参，以及 `leading`、`post` 的常量默认值。
6. 按 NPI 的范围读取当前源码第 70–86 行，同时知道这不是经过编译版本校验的源码快照。

## 2. 证据来源与本轮执行记录

### 2.1 环境

| 项目 | 本轮事实 |
| --- | --- |
| 工作树 | `<repo>` |
| VCS / Verdi | 本机环境均指向 `X-2025.06-SP1` |
| NPI Python | 当前 Verdi 安装的 `pynpi.lang`，通过仓库 `x_npi.runtime` 初始化 |
| Python | 仓库 `.conda-xverif/bin/python`，3.12.13 |
| 执行位置 | host，无沙箱；显式设置 `XVERIF_TEST_EXECUTION_ENV=host` |
| 数据 | 已缓存的 `xdebug.xif_event`、`xdebug.apb_vip`；追加 demo 读取 `xdebug.axi_vip` daidir |
| 仿真 / 重建 | 未重建或仿真既有 fixture；100题提交后新增一个临时独立SV表达式探针，核验Q025评分勘误 |
| 结果核对 | 初始24项断言；demo v1的19项、v2的22项；持久化共34项测试；297次重放响应一致；100题双组作答与审计，详见两份报告 |

读取 fixture 的正式定位方式为：解析 `.xverif-test-cache/fixtures/<fixture-id>/current.json` 的 `version`，进入 `versions/<version>/resources`。本轮读取了 `xdebug.xif_event` 的 `out/simv.daidir` 和 `xdebug.apb_vip` 的 `out/regression/build/simv.daidir`，没有创建替代数据库。

探针使用 `json_stdout_quarantine()` 隔离 vendor stdout；native 日志保留在权限为 0600 的临时文件，不将 license 内容写入本报告。JSON、探针脚本和断言结果在 `<tmp>/xverif-npi-code-probe/`，该目录仅用于本次复核，不作为后续实现或测试依赖。

初始探索执行了三个临时脚本：`probe.py` 分别读取 XIF/APB，`boundary_probe.py` 验证位置与对象关系，`alias_probe.py` 验证别名、默认值、继承和调用目标。所有 NPI 子进程正常退出。随后追加的AXI原型与持久化实验分别记录在两份报告，持久化阶段复用既有离线索引，没有重新提取NPI。

### 2.2 官方接口依据

以下为本机 `$VERDI_HOME` 下的官方材料，不把第三方文章或搜索摘要当作接口合同：

| 材料 | 本文使用的部分 |
| --- | --- |
| `share/NPI/inc/npi_hdl.h` | `npiPackage`、`npiClassDefn`、`npiClassTypespec`、`npiExtends`、`npiMethods`、`npiVariables`、`npiTypedefAlias`、`npiLocation` 等 |
| `share/NPI/python/pynpi/lang.py`、`lang_l0_util.py` | Python 关系访问、属性读取与 handle 生命周期 |
| `share/NPI/L1/C/inc/npi_L1.h` | class 遍历辅助接口存在；正式设计优先采用 L0 结构化关系 |
| `doc/HTML/pdf/verdi_vc_apps_npi.pdf` | Language Model 对象定义和 support summary |

手册使用印刷页码：Class Definition 1857–1860，Class Typespec 1860–1863，Package/Instance 1899–1900，IO Declaration 1908，Typespec 1961–1962，Variable 1973；Location 1828–1829；support summary 中 Class Definition 3919、Package 3932、IO Declaration 3936、Function/Task 3946–3947、Type Parameter 3953、Method Function Call 3984。发行版变化后应重新核对页码及对应表格。

仓库证据入口：

- [现有 design action 注册](../xdebug/src/engine/service/actions/design/register_design_handlers.cpp)
- [action 目录合同](../xdebug/specs/actions/actions.yaml)
- [XIF 探针对应源码](../xdebug/testdata/waveform/xif_agent_event/tb/xif_event_pkg.sv)
- [XIF 随机配置类](../third_party/xif_agent/src/xif_cfg.svh)
- [XIF fixture 编译入口](../xdebug/testdata/waveform/xif_agent_event/Makefile)
- [fixture 清单](../testinfra/fixtures.v1.yaml)
- [xdebug 架构约定](agents/xdebug/architecture.md)
- [新增 action 流程](agents/xdebug/action-development.md)

### 2.3 能力与证据等级

“实测”只覆盖上面的环境和输入；“手册支持”表示接口存在，仍需实现阶段的边界 fixture 验证；“未验证”不得在公开合同中宣称支持。

| 能力 | 证据 | 决策 / 限制 |
| --- | --- | --- |
| 枚举 package、package 内 class | 实测 | 第一期开启 |
| 类直接声明的 property / function / task | 实测 | 第一期开启 |
| property 的类型、visibility、rand | 实测 | 可返回结构化属性 |
| constraint 名称和位置 | 实测 | 可列举；不解释约束求解结果 |
| typedef 链与真实 class 定义 | 实测 | 必须显式遍历 alias |
| 基类链 | 实测 | 可导航，参数化基类保留 typespec |
| 派生类 | 实测 NPI 能返回集合；未证明集合是否传递闭包 | 产品通过声明索引和直接 `Extends` 建反向边 |
| class type parameter / specialization | 实测部分关系 | 声明默认值与使用处实际绑定分开 |
| 方法形参方向、常量默认值 | 实测 | 不把 formal handle 当默认表达式 |
| 方法 NPI 起止行 | 实测 | 原样报告范围；宏可能只指向调用行 |
| 完整 class 源码范围 | 无稳定直接证据 | 第一期开启声明点上下文，不承诺整个 class body |
| 静态变量使用位置 | 实测 | 第二期，明确限定为 NPI reported uses |
| 直接 task call 的声明目标 | 实测 | 第二期；不能当运行时 dispatch |
| package typedef、嵌套 class、extern 方法 | 手册支持部分关系，未完整实测 | 第一期开启前以专用 fixture 验证 |
| class method 的 virtual / static / visibility | 本轮未验证；不能从 property 支持推断 | 第一版不公开这些 method 属性 |
| interface class / implements / covergroup 细节 | 手册有关系，未实测完整语义 | 不进入第一期公共参数和结果种类 |
| 宏展开全文、加密 VIP 内部源码恢复 | 未验证，不能保证 | 不提供恢复或绕过能力 |
| 运行时 UVM 对象、factory、config_db、phase 状态 | 本轮静态 LM 无此证据 | 不纳入本方案 |

## 3. 已确认的行为细节

### 3.1 package 和类目录

在 XIF 缓存中，`uvm_pkg` 有 333 个直接 class，`xif_pkg` 有 1 个，`xif_agent_pkg` 有 5 个，`xif_event_pkg` 有 7 个。后者为 `xif_event_env`、`xif_event_base_seq`、`xif_event_rdy_seq`、`xif_event_bp_seq`、`xif_event_none_seq`、`xif_event_pair_seq`、`xif_event_multi_if_test`。

在 APB 缓存中，`svt_uvm_pkg` 有 168 个直接 class，`svt_amba_common_uvm_pkg` 有 9 个，`svt_apb_uvm_pkg` 有 107 个，`apb_vip_pkg` 有 3 个。该库中的 `uvm_pkg` 是 332 个 class。这说明目录随编译输入变化，不能把 UVM 类总数作为所有版本的固定断言。

XIF/APB 的一次加载与查询观察分别约 1.604 秒和 0.477 秒，包含不同查询工作量，没有重复采样，不能作为性能承诺或两种 fixture 的性能比较。

### 3.2 成员和继承

`xif_event_env` 声明在 `xif_event_pkg.sv:20`，有 10 个直接 property、6 个直接方法。其基类 typespec 可追到 `uvm_pkg.uvm_env`。`xif_pkg.xif_cfg` 中确认了 14 个 `rand` property 和 `c_default` constraint。UVM 类的 property 能区分 public、protected、local。

`xif_event_rdy_seq` 的直接方法列表不含 `send_item`。实际基类链为：

```text
xif_event_rdy_seq → xif_event_base_seq → uvm_sequence
  → uvm_sequence_base → uvm_sequence_item → uvm_transaction
  → uvm_object → uvm_void
```

因此“直接声明成员”与“沿继承链找到的声明”必须分开。不能只返回一个混合列表，让 AI 误判方法归属。

### 3.3 名称与类型解析陷阱

| 输入 / 操作 | 本轮结果 | 对实现的要求 |
| --- | --- | --- |
| `handle_by_name("xif_event_pkg.xif_event_env", NULL)` | ClassDefn | 可以作为加速入口，必须检查实际 kind |
| 同一字符串改成 `xif_event_pkg::xif_event_env` | NULL | public selector 不直接采用未经处理的 SV 名称字符串 |
| package handle 内查 `xif_event_env` | ClassDefn | 词法作用域有用 |
| package handle 内查导入的 `uvm_env` | 非空 `npiNIY`，不能追到定义 | 非空不等于解析成功 |
| 全限定查 `uvm_pkg.uvm_env` | ClassDefn | import 显示与精确声明解析分开 |
| `rdy_agent` 的 typespec 直接取 ClassDefn | NULL | 必须先检查 `npiTypedefAlias` |
| 沿 alias 到 `xif_agent` 再取 ClassDefn | `xif_agent_pkg.xif_agent` | 返回 alias 路径和最终定义 |

`ClassTypespec.FullName`、内建类型的 Name/FullName 为空是合法情况，不能据此认定句柄无效。NPI 的 definition 与使用处 typespec 不是同一对象。

### 3.4 参数、位置与静态调用

| 对象 | 观察 |
| --- | --- |
| `build_phase` | `npiLocation` 为 39–51 行，与当前源码核对一致 |
| `send_item` | 70–86 行；6 个 input 形参；`leading`、`post` 默认常量为 0 |
| `rdy_seq.body` | 96–102 行；5 个直接 task call，均指到基类 `send_item` 声明 |
| 宏生成的 `get_type` | 位置为 21–21 行，实际文本是 `uvm_component_utils` 调用 |
| `rdy_agent` uses | 41 行 assignment、55 行 class access 对象 |
| `rdy_fifo` uses | 46 行 assignment、55 行 class access 对象 |

`IODecl → Expr` 返回 formal variable；继续对 formal variable 取 `Expr` 才得到初始化表达式。非 constant 的默认表达式不得执行求值或伪装成常量。

方法的 `Variables` 可能同时包含 formal、返回变量和局部变量。局部变量分类必须按对象身份排除 formal 和返回变量，不能只按名字过滤。

`rdy_fifo` 的使用处 typespec Location 出现了“vendor 定义文件 + 第 29 行”的组合，而真实 class 定义在该文件第 200 行。无论这种位置组合的 SDK 内部原因是什么，都不能把 typespec 的 Location 当作 class body 范围。实现必须从正确的定义或方法对象取位置。

### 3.5 大型 AXI 环境补充探针

后续临时 demo 读取已有 `xdebug.axi_vip`，枚举到 7 个 package scope、1,390 个 class、6,341 条 property 记录、13,382 条 method 记录、341 条 constraint 记录、438 条 parameter 记录，声明位置涉及 336 个文件。成员合计 20,502 条原始记录，对应 20,480 个不同 path；22 个 path 有多个表示，不能将原始迭代条数直接命名为“唯一声明数”。这些重复表示的对象身份和 specialization 语义仍需区分。

补充探针对 `axi_scoreboard.master_fifo`、`slave_fifo`、`master_export` 均观察到：

- 使用处源码显式绑定 `svt_axi_transaction`。
- `ClassTypespec → Parameter(T) → Typespec / Expr / TypedefAlias` 返回声明默认的 int。
- `ClassTypespec → ParamAssign → Lhs` 返回 T，`→ Rhs` 返回 `svt_axi_transaction` ClassDefn。

因此不得将 Parameter 列表默认认定为实际绑定。生产实现必须合并并区分声明参数和显式 ParamAssign；Rhs 可能直接是 ClassDefn，不能假设它总是 Typespec。该结果修正了仅基于小型 XIF 探针作出的参数读取假设。

还确认 vendor extern 方法的 NPI File/Line 可以指向受保护实现块，例如几个 response 方法都指向第 22721 行；当前磁盘上的可读 extern 原型则位于更早的不同位置。正式输出需标明位置关系，不把这种坐标宣称为可读原型位置或完整正文。

## 4. 产品范围与不支持的情形

第一期查询域为 `loaded_package_declarations`：当前已加载 daidir 暴露的 package、package 中的 class、嵌套 class，以及这些作用域中的本方案成员种类。编译器生成、且 NPI 类型为 Package 的 compilation-unit scope 可以按原名列出，不能擅自重命名为 `$unit`。

第一期不扫描 module/program 内的 class；搜索结果的完整性只相对于上述查询域。未参与编译的源文件、未被保留的类、其它宏配置分支不在查询域内。不得把“没有找到”表述为“源码仓库里不存在”。

仅有 FSDB 的 session 不满足要求。输入必须有可用 daidir，或选择已加载 design 的 session。失败时返回现有 design-required 错误，不改走文本搜索、不导入源码、不编译新数据库。

本次 XIF fixture 已有 `-kdb`、`-debug_access+all`、`-lca` 等构建选项。本轮只证明该组合可用，未证明最小必要选项。实现阶段另用显式专用 fixture 做保留信息对照，不重建现有 fixture 来猜最小 flags。

第一期不提供：

- runtime class handle 枚举、对象字段当前值、UVM 动态拓扑或 factory/config_db 状态。
- 完整语言服务器功能，例如任意未编译文件解析、rename、编辑、全语言类型推断。
- 自动重写源文件、自动补建 daidir、隐式替换 SDK、自动选择另一数据源。
- 宏展开、加密源码恢复、完整 class body 复原、整个程序的精确调用图。

## 5. 总体接入方式

```text
AI / CLI / MCP
    ↓ 现有 public request 和 action schema
frontend → session / engine_forward → design action handlers
                                       ↓
                              CodeNavigationService
                              ├─ 声明索引与精确 selector
                              ├─ 类型、成员、继承适配
                              └─ NPI 位置 → 显式映射 → 源文件读取
                                       ↓
                              现有 NPI LM / daidir
```

不扩展 `signal.resolve` 的“signal”含义，不另起 Python daemon。Python 仅用于本轮探针和将来测试 oracle；正式能力在现有 C++ engine 内实现。

所有 NPI 调用串行进入 session 所属 engine。新 service 与 design 生命周期绑定；关闭或重新加载 design 时销毁索引。缓存仅保存复制后的值、selector 和关系，不跨 request 缓存裸 NPI handle，不持久化到磁盘。

`code.*` 的元数据读取采用 L0 对象关系；`code.source` 读取实际源文件。该功能不需要新增 `npi_util_decompile_t` 依赖。现有 `AstExtractor::decompile()` 及其它 action 的 L1 依赖属于另一项变更，不能据此删除整个 xdebug 的 L1 链接。

## 6. 公共合同

### 6.1 action 注册与版本

沿用 `api_version: "xdebug.v1"`。五个 action 均按现有 design action 登记：`requires: design`、现有 `engine_forward` handler 路径。接入后先使用目录现有的实验状态约定，完成第 13 节验收再调整发布状态。

target 沿用现有 daidir/session 互斥和校验规则。示例统一使用 `target.daidir`；不新增一种 session ID 格式。每个 action 的顶层、`args`、嵌套对象都关闭未知字段。未实现的参数不进入 schema。

### 6.2 SymbolSelector

```json
{
  "path": ["xif_event_pkg", "xif_event_env", "rdy_agent"],
  "kind": "property"
}
```

| 字段 | 约束 |
| --- | --- |
| `path` | 必填；1–64 个非空字符串；每段为 NPI 返回的声明名，逐段精确匹配；区分大小写 |
| `kind` | 必填；`package / class / property / function / task / parameter / typedef / constraint` |
| `declaration` | 可选；闭合对象 `{file: string, line: integer >= 1}`，用于同路径、同 kind 的精确消歧 |

路径首段必须是本查询域中的 package；后续为声明作用域与成员。段内的点号、冒号和转义字符按原字符保留，不当分隔符。`display_name` 仅用于阅读，不能反向 split 得到 selector。

selector 指向声明，不代表运行时对象，也不把不同参数化实例混为不同源码声明。使用处的实际类型绑定由 `code.describe(property)` 单独报告。第一期不提供将某个 specialization 套用到整个继承成员集合的“自动泛型替换”。

`declaration` 是 NPI 所报告的该声明对象定位点，可能指宏调用或受保护实现入口，不保证是磁盘上可读的 extern 原型行。若多个对象连 path/kind/file/line 都相同而 NPI 身份仍不同或无法确认，返回歧义并注明 `type_context_unavailable`；不要求用户用同一个 declaration 坐标解决不可消解的歧义，也不能让一个歧义成员阻断整个数据库的其它查询。

继承来的声明返回其真实 owner 路径，例如 `xif_event_base_seq.send_item`；不能返回看似在 `xif_event_rdy_seq` 中直接声明的假路径。没有跨 session 可复用的裸 handle ID。

### 6.3 共享响应对象

以下对象均为闭合对象。带 `?` 为可选；`| null` 表示字段必有但值可空。所有路径和行号均为证据，不从名称猜位置。

```text
SourcePoint = {file: string, line: integer >= 1}
SourceSpan = {file: string, begin_line: integer >= 1,
              end_line: integer >= begin_line, relation: "npiLocation"}
SymbolRef = {selector: SymbolSelector, display_name: string,
             npi_full_name: string | null}
Observed<T> = {state: "known" | "unavailable" | "not_applicable",
               value: T | null,
               reason: null | "npi_niy" | "missing_relation" |
                       "not_supported_for_kind" | "not_exposed"}
```

`known` 必须有非 null value；其它状态 value 必须为 null 且 reason 非空。`known:false` 与 unknown 不同。未知位置通过 selector 中省略 `declaration` 表达；不得产生第 0 行、第 -1 行等伪位置。

`SymbolRef.selector.declaration` 在有效定义点可得时必须包含；`npi_full_name` 原样保留，允许为空。`display_name` 使用作用域名称连接，只承担展示用途。`ClassDefn` 与 alias 解析后的定义位置优先于 typespec 使用位置。

`TypeInfo` 固定字段：

| 字段 | 类型 / 含义 |
| --- | --- |
| `npi_kind` | string；真实 typespec 类型，不公开整数枚举值 |
| `name` | string 或 null；允许内建类型没有名字 |
| `resolution` | `builtin / class / unresolved` |
| `alias_chain` | 有序数组 `{name: string|null, npi_kind: string, declaration: SourcePoint|null}` |
| `class_definition` | SymbolRef 或 null；只在关系校验成功时填写 |
| `bindings` | TypeBinding 数组，第一期只展开当前 typespec 的一层参数 |
| `bindings_complete` | boolean；遇到 NIY、缺关系或不能区分绑定来源时为 false |

`TypeBinding = {name, category: type|value, origin: declared_default|elaborated_actual|npi_reported_unverified, evidence_relation: parameter_default|param_assign_rhs|parameter_typespec, type: TypeAtom|null, constant: ConstantValue|null, state: known|unavailable}`。`TypeAtom = {npi_kind, name: string|null, class_definition: SymbolRef|null}`；不递归内嵌其它 TypeBinding，避免自引用无限展开。

声明上的默认参数来自 Parameter 的默认表达式关系。使用处显式绑定优先按合法 ParamAssign 的 Lhs 参数身份和 Rhs 对象读取，验证 kind 后记 elaborated_actual。单独 Parameter/Typespec 若没有经该种对象验证的实际绑定语义，只能记 npi_reported_unverified，并令 bindings_complete=false。默认与实际两者分别命名 origin，不因值相同而合并；不能通过猜测省略参数等价于默认值来填完整。缺省或无法解出的绑定用 unavailable；绝不能把“没有参数”与“参数尚未读出”混为一谈。

`ConstantValue` 使用闭合分支：integral 为 `{kind:"integral", literal:string}`，literal 必须带位宽和进制并保留 X/Z；string 为 `{kind:"string", text:string}`；real 为 `{kind:"real", text:string}`。第一期只在 NPI 明确给出常量时返回；不得先转窄整数再丢失四态或位宽。

### 6.4 分页、限制与完整性

`code.search`、`code.members`、`code.inheritance` 的 `args.offset` 为 0-based，默认 0。先完成请求范围的分析和稳定排序，再应用 offset 与 `limits.max_results`；不能用 max_results 提前停止扫描。

列表排序键为 `(selector.path 的逐段字节序, kind, declaration.file, declaration.line)`；未知位置排最后。同 key 多个 NPI handle 经身份比较确认属于同一声明后去重，不能仅按名字去重。分页在同一个未重载 design 的 session 内稳定。

| limit | 适用 action | 默认 / 范围 | 含义 |
| --- | --- | --- | --- |
| `max_results` | search / members / inheritance | 100；1–1000 | 返回列表行数 |
| `max_results` | source | 100；1–1000 | 返回源码行数 |
| `max_objects` | 五个 action | 100000；1–1000000 | 本请求最多检查的对象数，包括从缓存检查的元数据记录 |
| `timeout_ms` | 五个 action | 沿用已有 deadline 默认与合法范围 | 不创建另一套超时机制 |
| `max_source_bytes` | source | 8388608；1–67108864 | 完整源文件读取与 hash 的字节上限 |

`describe` 不公开 max_results，避免字段被静默忽略。`max_source_bytes` 不出现在其它 action。新增 max_objects/max_source_bytes 必须在各 action 的 runtime allowed set 和 schema 同步定义。

预算耗尽返回明确错误，不发布一个看似完整的半索引；临时构建的索引丢弃。完成的索引可以复用，但缓存命中不能改变响应事实和分页语义。全局新增元数据缓存占用上限初定 256 MiB，超限返回预算错误，不切换数据源；该值为实现预算，不是已测性能结论。

沿用现有 completeness 字段，并固定下列含义：

| summary 字段 | 合同 |
| --- | --- |
| `status` | `found / empty / partial`；partial 表示本次请求关系仍有明确的 unresolved 部分 |
| `scope_domain` | 固定 `loaded_package_declarations` |
| `scan_complete` | 请求定义域已枚举完；预算失败不得以成功响应返回 false 和伪总数 |
| `analysis_complete` | 本 action 要求的关系分析已完成；unresolved 类型/继承关系时为 false |
| `response_truncated` | 只描述输出分页是否省略了本次完整结果中的行 |
| `total_count` | 分页前符合请求的行数；不重复放到 data |
| `returned_count` | 实际返回行数 |
| `truncation_scopes` | 无则 `[]`；分页为 `["response.items"]` 或 `["response.lines"]` |
| `count_scope` | `all_matches / resolved_declarations`；后者仅用于尚有未知关系的已解析子集计数，describe/source 固定 all_matches |

列表 data 另有 `next_offset: integer|null`，只有存在下一页时返回非 null；offset 已超过总数时返回空页，status 仍依完整结果是否存在而为 found/empty。单对象 describe 的 count 单位为 symbol、正常为 1；source 的 count 单位为选定窗口内的行。

仅仅没有 FullName 或源码位置，不必令目录检索 analysis_complete=false；这些是允许缺失的元数据。describe 无法解析其被请求的类型、members 无法走完选定继承链、inheritance 无法判定基类时，必须 partial 并在 data 明示原因。

## 7. 第一期各 action 详细规格

### 7.1 `code.search`

用途：发现 package 和 class 定义。全库成员检索不在第一期；先找到类，再用 `code.members` 过滤成员。

| args | 约束 |
| --- | --- |
| `kinds` | 必填、非空且无重复；元素只允许 `package / class` |
| `name` | 可选 `{mode: exact|prefix|glob, value: string}`；省略表示所有名称；作用于声明的简单名称 |
| `scope` | 可选 SymbolSelector，只允许 package/class；省略表示所有已加载 package |
| `recursive` | boolean，默认 true；false 时只查起始层直接声明 |
| `offset` | integer >= 0，默认 0 |

根层的直接声明是 package；指定 package 的直接声明包括其 class，不包含 package 自身；指定 class 可搜索其嵌套 class，不包含自身。recursive=true 才进入子 class。根查询 class 时需 recursive=true。

glob 只定义 `*`（零或多个字符）、`?`（一个字符）、反斜杠转义；不支持字符组和正则。模式在一个名称段内匹配，不跨 path 段。空 value 仅允许 exact，以便明确查询空名并得到空结果；prefix/glob 必须非空。

```json
{
  "api_version": "xdebug.v1",
  "action": "code.search",
  "target": {"daidir": "simv.daidir"},
  "args": {
    "kinds": ["class"],
    "scope": {"path": ["xif_event_pkg"], "kind": "package"},
    "name": {"mode": "prefix", "value": "xif_event_"},
    "recursive": false,
    "offset": 0
  },
  "limits": {"max_results": 100, "max_objects": 100000}
}
```

成功 data 为 `{items: SymbolRef[], next_offset}`。上述缓存的完整结果应为 7 个 class。非法 scope kind 返回参数错误，scope 不存在返回 symbol-not-found，不能悄悄扩大到根。

### 7.2 `code.describe`

用途：精确查看一个声明的结构。args 仅包含必填 `symbol: SymbolSelector`。

```json
{
  "api_version": "xdebug.v1",
  "action": "code.describe",
  "target": {"daidir": "simv.daidir"},
  "args": {
    "symbol": {"path": ["xif_event_pkg", "xif_event_env", "rdy_agent"], "kind": "property"}
  }
}
```

data 为 `{symbol: SymbolRef, detail: <按 kind 判别的闭合对象>}`。不内嵌整个成员树；需要成员时调用 members。

| kind | detail 字段 |
| --- | --- |
| package | `imports: [{text:string, declaration:SourcePoint|null}]`；只报告 NPI import item，不宣称已做 import 名称解析 |
| class | `base: Observed<TypeInfo>`、`is_virtual: Observed<boolean>`、`parameters: ParameterInfo[]`；无基类为 not_applicable |
| property | `type: Observed<TypeInfo>`、`visibility: Observed<public|protected|local>`、`rand: Observed<none|rand|randc>` |
| function / task | `formals: FormalInfo[]`、`return_type: Observed<TypeInfo>`、`source_spans: SourceSpan[]`；task 返回类型 not_applicable |
| parameter | `parameter: ParameterInfo` |
| typedef | `aliased_type: Observed<TypeInfo>` |
| constraint | `representation: "declaration_only"` |

`ParameterInfo = {name, category:type|value, default_type:Observed<TypeInfo>, default_constant:Observed<ConstantValue>}`。不适用的分支必须用 not_applicable；非 constant 的 value 默认表达式为 unavailable，不能编造字符串常量。表达式源码查看走 source 的声明点上下文。

`FormalInfo = {name, position:integer>=0, direction:input|output|inout|ref|unknown, type:Observed<TypeInfo>, default:DefaultInfo, declaration:SourcePoint|null}`，按 NPI 形参顺序返回。`DefaultInfo = {state:constant|expression|absent|unavailable, constant:ConstantValue|null, declaration:SourcePoint|null}`。

只有已取得有效 formal variable 且其合法 initializer 关系为空，才记 absent；NIY/不支持关系记 unavailable。函数没有 Return handle 时不能直接认定为 void，必须用该发行版验证过的 void 识别规则；否则 return_type=unavailable。

方法不输出未经验证的 virtual/static/visibility。源位置为空不触发反编译。`rdy_agent` 的正确描述应保留 `xif_event_agent_t → xif_agent` alias 链和 `xif_agent_pkg.xif_agent` 定义；不会假定任意空 ClassDefn 都是 builtin。

### 7.3 `code.members`

用途：列 package/class 的声明成员，或沿类继承链发现基类声明。

| args | 约束 |
| --- | --- |
| `scope` | 必填 SymbolSelector，kind 为 package 或 class |
| `view` | `declared / inherited`，默认 declared；package 只允许 declared |
| `kinds` | 可选，非空且无重复；`class / property / function / task / parameter / typedef / constraint`；省略为该作用域所有已支持种类 |
| `name` | 与 search 的闭合名称匹配对象相同，作用于成员简单名称 |
| `offset` | integer >= 0，默认 0 |

`declared` 只返回当前 scope 自己声明的对象。`inherited` 返回当前 class 及完整基类链上的声明，**保留同名声明，不冒充 SystemVerilog 可访问成员的最终解析器**。第一期不公开 `effective` 选项。

每行 `{symbol:SymbolRef, declared_in:SymbolRef, inheritance_depth:integer>=0, same_name_nearer_declarations:SymbolRef[]}`。depth=0 表示当前作用域，深度越大越远。same_name_nearer_declarations 只报告更近层的同名声明，是导航线索，不声称 override、合法访问或虚方法 dispatch。

property visibility 在 describe 中读取。基类 local 成员可以作为“基类自己的声明”被浏览，但不能标成派生类可访问。方法的同名、constructor、protected/local 和语言查找规则未整体验证前，不做自动隐藏或合并。先形成完整关系再过滤 name/kinds，避免过滤改变归属证据。

```json
{
  "api_version": "xdebug.v1",
  "action": "code.members",
  "target": {"daidir": "simv.daidir"},
  "args": {
    "scope": {"path": ["xif_event_pkg", "xif_event_rdy_seq"], "kind": "class"},
    "view": "inherited",
    "kinds": ["task"],
    "name": {"mode": "exact", "value": "send_item"},
    "offset": 0
  }
}
```

该例应返回 depth=1、declared_in=`xif_event_base_seq` 的 task。data 为 `{items:MemberRow[], unresolved_bases:UnresolvedBase[], next_offset}`；unresolved 非空时 analysis_complete=false，已观察到的成员数不等于未知基类中的总数。

`UnresolvedBase = {derived:SymbolRef, reason:npi_niy|missing_relation|outside_domain, typespec_name:string|null}`。在此 partial 分支，total_count 明确定义为“已解析声明中的匹配行数”，summary 另必有 `count_scope:"resolved_declarations"`；完整分支为 `count_scope:"all_matches"`。所有列表 action 都使用这两个固定枚举，不把部分计数伪装成全集计数。

### 7.4 `code.inheritance`

| args | 约束 |
| --- | --- |
| `symbol` | 必填，class selector |
| `direction` | `bases / derived`，默认 bases |
| `transitive` | boolean，默认 true；false 只查直接边 |
| `offset` | integer >= 0，默认 0 |

data 为 `{items:InheritanceEdge[], unresolved_bases:UnresolvedBase[], next_offset}`。边固定表示 `{derived:SymbolRef, base:SymbolRef, base_type:TypeInfo, distance:integer>=1}`；方向不改变 derived/base 的含义。distance 是从查询根出发到这条边远端的距离。

```json
{
  "api_version": "xdebug.v1",
  "action": "code.inheritance",
  "target": {"daidir": "simv.daidir"},
  "args": {
    "symbol": {"path": ["xif_event_pkg", "xif_event_rdy_seq"], "kind": "class"},
    "direction": "bases",
    "transitive": true,
    "offset": 0
  }
}
```

该缓存应返回 7 条 extends 边，终点为 uvm_void。bases 按 distance 再按第 6.4 节的 derived selector 排序；derived 同样按 distance、derived selector 排序。

derived 查询不能假设 `npiDerivedClasses` 的结果都是直接子类。对查询域内每个 ClassDefn 获取直接 Extends，解析出基类后建立反向边，随后执行 BFS。若域内存在无法解析的 Extends，derived 的全集性可能受影响，必须返回 unresolved_bases 并令 analysis_complete=false、count_scope=resolved_declarations。

extends 解析发现基类在本查询域外时返回 outside_domain，不擅自扩域。检测循环和非 class 类型，返回明确错误，不无限追踪。

### 7.5 `code.source`

用途：从已定位声明读取当前磁盘源码。所有路径必须由成功解析的 symbol 及它的合法位置关系得出；不提供任意文件读取参数。

| args | 约束 |
| --- | --- |
| `symbol` | 必填，任一支持的 selector |
| `view` | `context / npi_range`，默认 context |
| `context_lines` | 仅 context 可用，0–100，默认 8；声明点前后各若干行 |
| `range_index` | 仅 npi_range 可用，integer >= 0，默认 0；选 describe 返回的 source_spans 下标 |
| `line_offset` | integer >= 0，默认 0；在已选定窗口内分页 |
| `relative_root` | 可选绝对目录，只用于 NPI 给出的相对路径 |
| `source_map` | 可选数组，每项 `{from:absolute_path, to:absolute_path}`；执行显式前缀映射 |

`npi_range` 第一版只支持 function/task。ClassDefn 无可靠完整范围时返回 `CODE_SOURCE_RANGE_UNAVAILABLE`，不能搜索最近的 endclass 补齐。未支持的 view 参数组合由 request schema 拒绝。

```json
{
  "api_version": "xdebug.v1",
  "action": "code.source",
  "target": {"daidir": "simv.daidir"},
  "args": {
    "symbol": {"path": ["xif_event_pkg", "xif_event_base_seq", "send_item"], "kind": "task"},
    "view": "npi_range",
    "range_index": 0,
    "line_offset": 0
  },
  "limits": {"max_results": 100, "max_source_bytes": 8388608}
}
```

该缓存对应的选定窗口为 70–86 行，共 17 行。source 的 data 固定为：

```text
{
  symbol: SymbolRef,
  source: {
    npi_file: string, resolved_file: string,
    content_origin: "current_filesystem",
    compiled_match: "unknown",
    sha256: string,
    interpretation: "declaration_context" | "npi_reported_range",
    preprocessed: false,
    available_range_count: integer >= 0,
    window: {begin_line: integer >= 1, end_line: integer >= begin_line}
  },
  lines: [{line: integer >= 1, text: string}],
  next_line_offset: integer | null
}
```

源码算法必须按下面顺序实现：

1. 从声明点或方法 `npiLocation` 取位置；不从 property typespec 猜 class 范围。
2. 多个 npiLocation 按 `(file, begin_line, end_line)` 去重排序，每段独立。不能将不同 include 文件拼成一个 min/max 区间。
3. 相对文件名必须有 relative_root；不把 engine cwd 当编译 cwd。先按 relative_root 形成绝对路径，再执行 source_map。
4. source_map 按路径分量的最长 from 前缀匹配；同 from 多条映射拒绝。只尝试映射后的唯一结果；读取失败不再尝试旧路径或 basename 搜索。
5. 按 max_source_bytes 检查大小，读取文件、计算 SHA-256，并比较读取前后的文件身份/大小/mtime 等状态。检测到变化返回 `CODE_SOURCE_CHANGED_DURING_READ`。
6. 第一版严格 UTF-8 解码；无法解码返回 `CODE_SOURCE_ENCODING_UNSUPPORTED`，不静默替换字节。按逻辑行输出，CRLF 去除行尾 CR，保留其它原文。识别真实 legacy protected/endprotected 和 IEEE protect 区域边界，跳过注释中的假指令；请求窗口与保护内容相交时返回 `CODE_SOURCE_UNAVAILABLE`，reason=protected_content，不把密文当成方法实现返回。
7. NPI 行范围超过文件边界返回 `CODE_SOURCE_LOCATION_MISMATCH`。context 的外围窗口可在文件首尾裁切，但中心声明行必须存在。
8. 应用 line_offset/max_results；window 是分页前窗口，返回行号仍是原文件 1-based 行号。

SHA-256 仅标识本次读取内容。没有编译时源文件 hash 或版本清单，因此 compiled_match 永远为 unknown。即使行内名称匹配也不能改成 true。

`get_type` 的 npi_range=21–21 可以合法返回宏调用行；interpretation 仍是 npi_reported_range，preprocessed=false。不得将它命名为“完整函数实现”。空文件、缺失源码、只有保护区而无可用正文、非法范围均不触发 decompile 或其它数据源补全。

## 8. 成功响应示例及错误语义

下例展示 code.members 的拟定完整 envelope；版本由构建填写，此处使用仓库当前示例版本。selector 位置为相对路径示意，真实输出保留 NPI 的文件定位。

```json
{
  "api_version": "xdebug.v1",
  "ok": true,
  "action": "code.members",
  "tool": {"name": "xdebug", "version": "0.1.0"},
  "session": null,
  "summary": {
    "status": "found",
    "scope_domain": "loaded_package_declarations",
    "scan_complete": true,
    "analysis_complete": true,
    "response_truncated": false,
    "count_scope": "all_matches",
    "total_count": 1,
    "returned_count": 1,
    "truncation_scopes": []
  },
  "data": {
    "items": [{
      "symbol": {
        "selector": {
          "path": ["xif_event_pkg", "xif_event_base_seq", "send_item"],
          "kind": "task",
          "declaration": {"file": "xdebug/testdata/waveform/xif_agent_event/tb/xif_event_pkg.sv", "line": 70}
        },
        "display_name": "xif_event_pkg::xif_event_base_seq::send_item",
        "npi_full_name": "xif_event_pkg.xif_event_base_seq.send_item"
      },
      "declared_in": {
        "selector": {
          "path": ["xif_event_pkg", "xif_event_base_seq"],
          "kind": "class",
          "declaration": {"file": "xdebug/testdata/waveform/xif_agent_event/tb/xif_event_pkg.sv", "line": 61}
        },
        "display_name": "xif_event_pkg::xif_event_base_seq",
        "npi_full_name": "xif_event_pkg.xif_event_base_seq"
      },
      "inheritance_depth": 1,
      "same_name_nearer_declarations": []
    }],
    "unresolved_bases": [],
    "next_offset": null
  },
  "error": null
}
```

错误沿用公共 error envelope，不把自由文本当机器合同。下列新增 code 在 action 合同中集中定义；已有 session、schema、design-required、deadline 错误直接复用原 code，不另造同义名称。

| 新增 code | 条件 / 必需 details |
| --- | --- |
| `CODE_SYMBOL_NOT_FOUND` | 完成指定范围解析仍无声明；`selector` |
| `CODE_SYMBOL_AMBIGUOUS` | 同路径同 kind 多个不同声明；`selector, candidates:SymbolRef[], candidate_count, candidates_truncated, reason:multiple_declarations|type_context_unavailable`；最多返回 20 个候选 |
| `CODE_SELECTOR_STALE` | path/kind 可解析，但提供的 declaration 与当前 DB 不符；`selector` |
| `CODE_NPI_OBJECT_UNSUPPORTED` | 查询入口为 NIY/不支持对象；`npi_kind, relation`，不能返回空 success |
| `CODE_QUERY_LIMIT_EXCEEDED` | 对象预算、响应 1 MiB 上限、缓存 256 MiB 上限；`limit_name, limit_value, observed_count` |
| `CODE_RELATION_CYCLE` | 继承或 typedef alias 出现循环；`relation, symbols:SymbolRef[]`，最多 20 项 |
| `CODE_SOURCE_RANGE_UNAVAILABLE` | 指定对象没有该类合法范围；`selector, view` |
| `CODE_SOURCE_UNAVAILABLE` | 无有效位置、文件不存在/不可读，或明确为不可展示的保护内容；`reason, npi_file:string|null` |
| `CODE_SOURCE_PATH_UNRESOLVED` | NPI 相对路径缺少 relative_root；`npi_file` |
| `CODE_SOURCE_LOCATION_MISMATCH` | 行号越界；`file, requested_begin, requested_end, file_line_count` |
| `CODE_SOURCE_CHANGED_DURING_READ` | 读取期间文件改变；`file` |
| `CODE_SOURCE_ENCODING_UNSUPPORTED` | UTF-8 解码失败；`file, encoding:"utf-8"` |

明确不支持的请求种类在 schema 阶段拒绝。不可判定的可选关系可以通过 Observed/unresolved 返回 partial；不可解析请求目标必须返回 error。接口保证不会把预算、NIY、缺文件、歧义当成“没有结果”。

## 9. 核心实现算法与资源约束

### 9.1 声明索引

1. 从 `npi_iterate(npiInstance, NULL)` 获取顶层对象，只纳入实际 kind 为 Package 的根。
2. package/class 的 `InternalScope` 只保留 ClassDefn；其它成员通过适用对象关系分别枚举。不要把 ClassTypespec 当独立 class 声明。
3. 建立 `(parent locator, raw name, normalized kind)` 到一组声明的索引；保留全部消歧候选。
4. 只有当前查询需要的作用域才展开；根 class 搜索和 derived 反向索引需要时才扫描整个查询域。
5. 不通过字符串替换 `::` 或点号推断 owner。handle_by_name 可用于经测量后加入的优化，但结果必须与逐段关系解析的 kind、scope、身份一致。
6. index 只保存有界值对象。超预算不发布半成品，不自动扩大 max_objects。

package/class 的 public kind 映射明确如下：InternalScope→class；Variables 中受支持的变量声明→property；Methods/TaskFunc 中 Function→function、Task→task；Parameter/TypeParameter→parameter；Typedef→typedef；Constraint→constraint。每条关系仅在手册支持的 owner kind 上调用，不通过“所有关系都试一次”发现接口。

package 的 property 指 package-scope 变量，不代表 class instance field。方法内局部变量不纳入第一期 selector 可搜索域，避免同名块作用域被抹平。

### 9.2 类型与继承

按对象类型选择合法关系，再沿 TypedefAlias 解链；每一步记录原始名称、类型、位置。使用 NPI 对象身份判断循环，不能只用 name 判断。抵达 ClassTypespec 后取得 ClassDefn，并再次检查实际类型。

Extends 返回的是 typespec。先保留该 typespec 的参数和 ParamAssign 证据，再沿 alias/ClassDefn 找定义。Lhs 必须按参数对象身份关联，Rhs 必须区分 ClassDefn、Typespec、常量和其它表达式；不能只取 Parameter 列表后标注 elaborated_actual。发现 NIY、未公开 builtin definition 或域外声明时保留原因，不伪造一个仅有名字的“已解析定义”。

property 的类型允许 builtin resolved 而 ClassDefn=null；已知 class typespec 缺 ClassDefn 则通常 unresolved。判断由 npi_kind 与合法关系共同决定，不能仅看空指针。

members(inherited) 沿单继承链走完整声明，保留每层 declared_in/depth。同名线索在完整层级上计算。interface-class implements 另留后续能力，不冒充 extends 边。

### 9.3 handle 与超时

复用 [NPI RAII](../xdebug/src/core/npi/resource_guard.h)、[ActionResourceScope](../xdebug/src/engine/service/action_resource_scope.h) 与 request deadline。每个 handle 必须只有一个 owner，不同时注册到两套释放机制。

NPI iterator 的耗尽和主动释放规则按当前 SDK 实现包装；尤其不能在 npi_scan 到 NULL 后再次释放已被 SDK 回收的 iterator。提前退出、异常、预算和 timeout 路径都要做资源测试。

每扫描一个有界批次执行 `ctx.checkpoint()`，批次最多 128 个对象；不能只在序列化结束后检查 timeout。vendor 单个阻塞调用的硬超时处理沿用现有 engine/session 隔离机制，不调用未公开 cancel API。

### 9.4 性能验收方法

先测再承诺时延。实现阶段记录 fixture、SDK、CPU、index cold/warm、对象数、峰值 RSS 和输出字节数；每种代表查询至少测 10 次，报告中位数与 p95，不把 license 初始化混进 warm query。

硬性验收：分页不减少分析范围；小 scope 查询不预扫所有 VIP 方法体；describe 不启动全库引用索引；缓存不保留 NPI handle；关闭 session 后资源释放；超限可重复得到同一种明确错误。256 MiB 缓存和 1 MiB 单响应限额是初始工程约束，若需改动必须更新合同与性能记录。

## 10. 后续阶段：引用与调用

这两个 action 不随第一期占位发布。下述合同用于后续实现计划，发布前必须通过专用 AST fixture；未通过则保持未注册，不能静默提供文本搜索替代。

### 10.1 `code.references`

- args：必填 `symbol`，第一版只允许 property；可选 `offset >= 0`。
- limits：max_results、max_objects、timeout_ms，语义沿用第一期列表。
- 取 `npiUse`，每行 `{location:SourcePoint|null, npi_kind:string, owner:SymbolRef|null}`；按位置、npi_kind、owner 排序，不能只按同一行号合并不同 AST 对象。
- data：`{items, next_offset}`；summary 增加固定 `evidence_domain:"npi_reported_uses"`。
- `scan_complete=true` 只表示 npiUse iterator 完整消费。空列表只能说该对象没有 NPI reported uses，不能声称全源码无引用。
- 不发布 read/write 分类，除非之后对 assignment LHS/RHS、ref、method access、索引和 read-modify-write 逐项验证并扩展合同。
- 首个真实验收：rdy_agent 的 41/55 行两项证据与 npi kind 均保留。

### 10.2 `code.calls`

- args：必填 function/task `symbol`，可选 `offset >= 0`。第一版只查询 outgoing，不公开 incoming、runtime 或 include_dynamic 开关。
- limits：max_results、max_objects、timeout_ms。
- 从方法 Stmt 和合法的 statement/expression 子关系遍历方法体，不只检查顶层语句；每个 AST 对象去重，禁止沿 Scope/Use/父节点回边无限递归。
- 每行 `{location:SourcePoint|null, npi_kind:string, resolution:declaration|system|unresolved, callee:SymbolRef|null, reason:null|dynamic_target|unsupported_relation|outside_domain, dispatch:"static_evidence_only"}`。
- 只有 SDK 明确的调用目标关系可产生 declaration。`npiTaskCall → npiTask` 已实测；function call、嵌套表达式和 method call 必须逐种类验证后才填 traversal dispatch 表。
- MethodFuncCall 等若没有已验证的声明关系，返回 unresolved；不能根据同名方法或 receiver 声明类型猜目标。
- data 为 `{items, unsupported_nodes:[{npi_kind, location:SourcePoint|null}], next_offset}`。summary 固定 `evidence_domain:"supported_npi_ast_calls"`；遇到可能含调用的未支持 AST 容器，analysis_complete=false。
- 即便 callee 已解析，也不声称运行时曾执行、执行次数、virtual 最终目标或 factory 创建的实际类型。

后续实现的准入条件：nested begin/if/case/loop、表达式 function call、直接 task call、super call、system call、virtual receiver、宏生成方法、NIY 容器全部有独立预期。已验证的简单 5 个 send_item 调用不能替代这些覆盖。

## 11. 未来修改点清单

以下是实施时的文件边界，未在本轮创建这些产品文件。

| 位置 | 工作内容 |
| --- | --- |
| `xdebug/src/design/code/`（新增） | selector、值对象、NPI kind 适配、声明索引、类型/继承、source resolver |
| `xdebug/src/engine/service/actions/design/code_*.cpp`（新增） | 五个薄 handler，仅做合同绑定、调用 service、输出 |
| `register_design_handlers.cpp` | 注册真实实现的 action |
| `xdebug/src/engine/service/engine_globals.*` 及真实 design 初始化/销毁入口 | 接入 service 生命周期；实施前核对实际 owner，不能引入独立全局 NPI session |
| `xdebug/Makefile` | 按现有模式纳入新源文件；保留当前工具链检查，不改变用户已有相关修改 |
| `xdebug/specs/actions/actions.yaml` | 首先登记 action、状态、handler、required args/target、schema 和 example 路径 |
| `xdebug/specs/action_contracts.py` | action-specific 语义，尤其 symbol、scope、view、limits，不能套用其它 action 的同名参数 |
| `xdebug/tools/sync_runtime_request_schemas.py` | 允许参数集合、条件约束和共享 selector/limit 投影 |
| `xdebug/specs/code_navigation_contracts.py`（建议新增） | 共享请求对象和响应业务对象的单一 Python 定义源 |
| `xdebug/specs/non_sampling_response_contracts.py`、`xdebug/tools/sync_response_schemas.py` | 接入新共享对象到现有统一响应生成流程，禁止手改生成 schema |
| `xdebug/tools/sync_action_schema_hints.py` | 由现有 source 同步 AI-facing hints |
| `xdebug/examples/requests/`、`examples/responses/` | 每个 action 成对样例，包含空、分页、partial 和错误分支 |
| `xverif_mcp/` | 核对现有通用 action 入口、输出预算和 action smoke；不为每个 action 新建一套工具入口 |
| `skills/xverif/` | SKILL、action-reference、openai.yaml 与工作流示例同步 |
| `doc/agents/xdebug/`、xdebug README | 架构、action 接入、测试矩阵和源码一致性边界 |
| `testinfra/catalog.v1.yaml`、`fixtures.v1.yaml` | 新 suite / fixture 精确登记，已有 fixture 按指纹复用 |

所有 shared schema 要投影为运行时 embedded Draft-7 可执行子集。不要因为顶层声明 Draft 2020-12 就使用运行时不支持关键字。未知字段拒绝、条件分支以及 response additionalProperties=false 都需要生成后审计。

## 12. 实施阶段、提交边界和退出条件

下列是将来明确进入实现阶段后的提交建议；本轮不提交 git、不推送、不创建 PR。

| 阶段 | 状态 | 内容 | 退出条件 / 建议提交 |
| --- | --- | --- | --- |
| P0 能力探索 | 已完成 | 官方材料、XIF/APB/AXI 探针、临时持久化 demo/测试、100题双代理对照、本文 | 24项初始断言、34项最终临时测试、297次重放、100题审计及Q025独立勘误探针通过；结果见报告 |
| P1 声明与类型基础 | 待实施 | selector、NPI adapter、search/describe、统一合同与样例；C++ 最小 fixture；第16节缓存所有权/代际/计数 | 两个 action 不接受未实现字段；别名、NIY、重复名、参数和索引复用全部有验证；中文提交说明含动机与验证 |
| P2 第一期开启 | 待实施，依赖 P1 | members、inheritance、source、MCP/skill/documentation | 五个 action 全部达到第 13 节第一期验收；正式 gate 通过；单独中文提交 |
| P3 引用与调用 | 待实施，依赖 P2 | references、calls、AST 种类覆盖、unresolved 语义 | 第 10 节准入 fixture 通过后才注册发布；单独中文提交 |
| P4 扩域研究 | 非本次实施承诺 | module/program class、effective 语言查找、covergroup、编译源版本证明、运行时对象通道 | 每项独立探针和后续 spec，不往现有参数塞占位语义 |

每阶段在本文更新状态、实际测试结果、已知边界和计划变更。源码阶段提交前先确认 `git status --short` 和 staged 文件精确属于本阶段；已有用户修改由其 owner 管理，不能顺带提交。

P1 必须优先验证第一期里目前只有手册依据的 package typedef、nested class、extern 和类型参数差异。若结果不支持本文合同，先修订本文及未来 schema，再实现；不能把“理想字段”留在公共 API 中返回猜测。

## 13. 验收矩阵与测试入口

### 13.1 真实证据与新增 fixture

先复用已缓存 XIF/APB 作为集成基线；不因写新测试就重新 prepare 这些 fixture。另计划新建 `xdebug.code_navigation` 专用 fixture，不改已有 fixture 来迁就测试。

新 fixture 至少包括两个有同名 class 的 package、nested class、多层继承与同名成员、public/protected/local property、rand/randc、类型和值参数、两种 specialization、两级 typedef、package function/task/variable、extern method、include 文件、宏生成方法、escaped identifier，以及一个未实例化但已编译的类。

第二期在该 fixture 增加调用表达式时，按 fixture 指纹规则显式准备新版本。未编译包/宏分支采用明确独立构建变体；不把“未实例化”先验等同于“未被 NPI 保留”。源码移动、缺失、行号变化测试只对临时副本操作，不修改用户真实源码。

| ID | 输入 / 场景 | 必须验证的结果 | 阶段 / 现有证据 |
| --- | --- | --- | --- |
| A01 | XIF package class search | 7 个预期类，scope 无混入 UVM | P1 / 已有探针 |
| A02 | APB vendor package search | 可列 SVT 类；不承诺源码正文 | P1 / 已有探针 |
| A03 | 两 package 同名 class | 返回两个 selector；精确选择不串包 | P1 / 新 fixture |
| A04 | 导入名、NIY、SV `::` 原始文本 | 无假成功、无字符串替换误解析 | P1 / 已有探针 + unit |
| A05 | rdy_agent typedef | alias 链终点为 xif_agent 定义 | P1 / 已有探针 |
| A06 | parameter default 与两种 specialization | origin 分开，实际参数不覆盖声明默认值 | P1 / 部分探针 + 新 fixture |
| A07 | xif_cfg、UVM property | 14 rand 与三种 visibility；method 不伪报属性 | P1 / 已有探针 |
| A08 | send_item 形参 | 6 input，leading/post=0；formal 不是 default expr | P1 / 已有探针 |
| A09 | void / constructor / task / 非常量默认值 | absent、unavailable、not_applicable 正确区分 | P1 / 新 fixture |
| A10 | nested class、escaped name、package typedef | selector 原样往返；不会拆错分隔符 | P1 / 新 fixture |
| A11 | declared vs inherited send_item | declared 无结果；inherited depth=1、真实 owner | P2 / 已有探针 |
| A12 | 同名 / local / protected / constructor | 保留声明归属，不宣称语言可访问性或覆盖关系 | P2 / 新 fixture |
| A13 | bases 查询 | 8 个类组成 7 条边，终点 uvm_void | P2 / 已有探针 |
| A14 | derived 查询 | 根据直接 Extends 建反向边；跨 package 闭包正确 | P2 / 新 fixture |
| A15 | missing/NIY base | partial 和 count_scope 正确，无假“没有基类” | P2 / mock + 真实边界 |
| A16 | send_item / build_phase 源码 | 分别 70–86、39–51；与文件逐行一致 | P2 / 已有探针 |
| A17 | 宏 get_type | 只返回 21 行调用位置，不标完整实现或预处理文本 | P2 / 已有探针 |
| A18 | class body / typespec 范围 | class npi_range 拒绝；不使用错位 typespec Location | P2 / 已有探针 |
| A19 | extern / include 多范围 | 按方法定义合法范围分段，不跨文件拼接 | P2 / 新 fixture |
| A20 | 当前源码不同于编译输入 | compiled_match 保持 unknown；越界明确错误 | P2 / 临时副本 |
| A21 | 缺文件、source_map、相对路径 | 显式路径规则生效；无隐式第二路径尝试 | P2 / 临时副本 |
| A22 | offset/max_results 小页 | 完整分析数不变，分页稳定、next_offset 正确 | P1/P2 / 新 contract |
| A23 | max_objects、timeout、超大输出 | 明确错误，无半索引和资源泄露 | P1/P2 / unit + runtime |
| A24 | 所有未知参数与非法组合 | CLI/MCP/schema 一致拒绝 | P1/P2 / contract |
| A25 | FSDB-only、重开/关闭 session | 缺 design 正确报错；缓存和 handle 不跨生命周期 | P1/P2 / runtime |
| A26 | rdy_agent references | 41/55 行和真实 node kind；不伪造读写 | P3 / 已有探针 |
| A27 | rdy_seq.body calls | 5 个 callsite 均指基类 send_item | P3 / 已有探针 |
| A28 | 嵌套 AST / 虚调用 / system / 未支持节点 | 分别报告已解析或 unresolved，完整性准确 | P3 / 新 fixture |
| A29 | AXI scoreboard 三个 T 参数化成员 | Parameter 的 int 默认与 ParamAssign 的 transaction 实际绑定分开 | P1 / 补充真实探针 |
| A30 | uvm_pool.pool 等相同坐标多表示 | 局部歧义明确失败，其它类查询仍正常；统计区分原始记录与声明 | P1 / 大型 demo 实测 |
| A31 | vendor extern 方法指向保护块 | 位置语义准确；source 不返回密文冒充正文 | P2 / 大型 demo 实测 |

### 13.2 正式门禁

本轮只新增文档，执行文档格式、JSON 示例、链接及事实检查，不运行源码回归。以下命令是未来实现后的正式流程，均以仓库根目录为 cwd。

生成与审计命令：

```bash
.conda-xverif/bin/python xdebug/tools/sync_runtime_request_schemas.py --check
.conda-xverif/bin/python xdebug/tools/sync_response_schemas.py --check
.conda-xverif/bin/python xdebug/tools/sync_action_schema_hints.py --check
.conda-xverif/bin/python xdebug/tools/audit_runtime_schema_compatibility.py
.conda-xverif/bin/python xdebug/tools/validate_schema.py
.conda-xverif/bin/python xdebug/tools/validate_examples.py
```

先运行 generator 的正式生成模式再执行 --check；发现既有无关漂移必须单列，不能为让本功能通过而批量重写无关 action。

2026-09-18 已根据当前 catalog 选择函数核对 membership：

| suite | 可选正式 gate |
| --- | --- |
| `xdebug.static`、`skills.xverif`、`skills.xverif_admin` | fast / regression / nightly |
| `xdebug.action_runtime_catalog`、`xdebug.cpp_unit`、`xdebug.contract`、`xdebug.design_semantics`、`xverif_mcp.action_smoke` | regression / nightly |
| `xdebug.xif_event`、`xdebug.apb_vip` | nightly |
| 拟新增 `xdebug.code_navigation` suite | 计划显式加入 regression / nightly，尚未存在 |

运行每个 focused suite 前，先用对应 gate 的 `--xverif-plan` 核对当时 membership。下面以 contract 为例；其它 suite 同样先 plan 后执行，不能照成本标签猜 gate：

```bash
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xdebug.contract --xverif-plan
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate regression --xverif-suite xdebug.contract
```

新 fixture 已正式登记且需要首次准备时，才执行：

```bash
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-prepare xdebug.code_navigation
```

这是未来命令，当前 fixture 尚不存在。不得现在执行，也不得 cache miss 后自动改用其它数据库。

C++ 构建使用当前 Makefile 的真实目标；先完成生成和 `make -C xdebug all`，再串行运行真实 runtime/NPI 测试，期间冻结 binary、schema、manifest。`xdebug.cpp_unit` 可能构建单元产物，应放在真实回归之前。不要一边链接 xdebug 一边跑 VIP。

需同步验收 native JSON/text、MCP action 转发、action catalog、request/response 示例、skill 引导和资源错误。skill 源文件提交并通过对应 suite 后，按 Makefile 安装目标同步两处安装目录并做 diff；不在本轮提前安装。

## 14. 与版本切换、decompile 的关系

本轮支持结论限定于 Verdi/VCS X-2025.06-SP1 及已缓存数据库，不构成跨版本 ABI 或 daidir 兼容保证。

切换 `VERDI_HOME`/`VCS_HOME` 不等于已运行 xdebug engine 自动换库，也不能仅凭环境变量判断它实际加载了哪份 `libNPI`。现有构建的链接/RPATH、启动环境和 database 生成版本都需核对；新 code 功能复用现有工具链校验和 session 隔离，不增加混装支持承诺。跨版本支持必须用对应头文件、实际加载库和目标 daidir 做独立矩阵验证。

`decompile` 可以服务现有 AST/表达式文本输出，但 package/class/member 检索本身不依赖它。本文源码方案优先给出真实文件片段及 NPI 位置证据，缺文件时明确失败。若以后要展示 NPI 重建文本，应另设明确的生成文本视图，标注来源与语义损失；不能把它偷偷当原始源码返回。

## 15. 本轮交付检查记录

- [x] 阅读本机官方 NPI 接口和当前仓库架构、action、fixture 合同。
- [x] host 上读取已有 XIF/APB daidir，未运行编译仿真。
- [x] 核对 package/class/member/type/位置/继承/引用/静态调用边界。
- [x] 24 项探针与当前源码断言通过。
- [x] 设计 action、selector、响应、错误、完整性、源码一致性、生命周期、阶段及验收矩阵。
- [x] 追加大型 AXI demo、22 项最终临时测试和两个独立代理对照；原型与实验产物均在临时目录。
- [x] 初轮文档链接、7个JSON示例、内部合同一致性和文件边界检查；初轮仓库仅新增本文与初轮报告。
- [x] 临时目录增加持久化session；34项查询/session测试通过，297次同版本重放业务响应一致。
- [x] 两个全新代理各自完成100题；题目、评分点、索引和参考源指纹未变，评分和来源审计完成。
- [x] 保留Q025原始错误评分点，另附勘误与独立host VCS表达式探针；两组正确答案不受错误标准惩罚。
- [x] 本轮仓库只增加题库、持久化/100题报告并补充本文；临时代码、探针与测试不进入源码树。

实施状态仅 P0 完成。P1–P4 不因本文存在而视为已经实现。

## 16. 持久化 session 补充验收（2026-09-18）

本节补充第5节和第9节的生命周期要求，不改变第一期action名称与参数。临时session原型与100题对照见 [持久化与100题报告](XDEBUG_NPI_SESSION_100_COMPARISON_REPORT_2026-09-18.md)，题目见 [冻结100题](XDEBUG_NPI_100_QUESTION_BENCHMARK_2026-09-18.md)。临时代码均位于 `<tmp>/npi-code-session`。

临时原型已通过34项查询/session测试；同一v2、同一33条查询三轮重放，297次响应语义一致。平均每请求：单次载入索引681.938ms，常驻服务配轻客户端78.520ms，复用连接3.291ms。数字只用于确认重复初始化成本已消除，不作为正式NPI性能SLA，也不替代真实NPI生命周期测试。

### 16.1 P1/P2必须实现的状态与所有权

1. `CodeNavigationService`由已有design engine持有，不能在每个action handler内重新构造全库索引。原有session ready继续只表示engine可服务；代码索引按第9.1节按需展开，不为了ready提前扫描所有VIP方法。
2. 内部以design generation标识已加载数据库的一代。每个scope缓存的状态为`empty/building/ready`；错误或deadline中止回到empty，不发布半成品。只有完整构建并校验预算后才原子发布ready。
3. 缓存保存复制后的声明/关系值。请求期间的NPI handle仍由现有RAII/request scope释放；不能为了持久化性能而把裸handle留到下次请求。
4. 同一engine的NPI调用串行。客户端连接关闭不销毁design缓存；显式关闭design、重载design或engine退出时先停止接收该generation的新工作，再释放缓存和上下文。
5. datasource路径、generation、scope定位和构建策略共同限定缓存。重开同名daidir也属于新generation；不能只按文件路径复用旧selector解析结果。重载失败不静默继续以旧库冒充新库。
6. source查询依然读取当前磁盘文本，不能把元数据常驻等同于源码常驻；索引稳定与当前源码一致性分别报告。未取得编译源摘要时保持`compiled_match=unknown`。
7. 诊断日志中记录generation、索引构建次数、查询次数、冷/热耗时和缓存字节数。复用已有日志机制，不未经schema设计将临时demo的PID字段加进公共响应。
8. 继续使用已有frontend/MCP/transport连接能力，不为code动作再起Python daemon。持久连接优化必须保持逐请求deadline、错误隔离和现有session关闭合同；断线后不得自动换数据源或临时单次NPI进程。

### 16.2 新增验收用例

| ID | 场景 | 验收结果 | 临时原型证据与正式实施要求 |
| --- | --- | --- | --- |
| A32 | 同一session重复查询相同scope | 同一generation且scope只成功构建一次，返回语义一致 | 临时服务PID/加载计数通过；正式C++需真实NPI计数验证 |
| A33 | 不同客户端访问同一design | 串行NPI调用，无重复并发建索引；空闲连接不独占服务 | 4客户端8查询通过；正式transport做等价测试 |
| A34 | 未找到/歧义/参数错误后再查询 | 错误局部化，服务和其它scope继续可用 | 临时错误后继续查询通过；正式覆盖request deadline |
| A35 | 构建中超预算/超时 | 不发布半索引，下次请求得到明确状态而非读取半成品 | 需正式带预算fixture验证，不以临时JSON加载测试代替 |
| A36 | 关闭并重开、数据库重载 | 旧generation失效；无裸handle跨代；新索引来自新库 | 临时close/reopen通过；真实NPI重载待实施 |
| A37 | 索引保持而源码发生变化 | 元数据不自动冒充新编译，source读当前文本并保留unknown | 临时副本变化测试通过 |
| A38 | 单次客户端与复用连接重放 | 规范化业务响应完全一致，启动与warm query单独计时 | 297次响应一致；正式至少10次/代表查询并报告p95/RSS |

阶段提交仍按第12节：P1接入缓存所有权/代际/计数，P2完成source与生命周期合同测试。禁止先发布每请求全库重建的实现，再将持久化标为可选优化；同样禁止为了复用缓存取消完整性和预算校验。

### 16.3 100题暴露的来源缺口与后续准入

本轮共享推理得分接近上限，不能以此承诺结构查询会提高AI推理正确率。可执行的产品目标仍是提供本次编译的确定性结构证据，并明确返回未知或不可读。Q089的extern位置缺口、Q005/Q030/Q096的宏来源缺口不能靠静默文本搜索或decompile补全。

以下任务先做独立探针，产物与判据明确；在结论确认前不增加第一期公开参数：

| 探针 | 最小输入与操作 | 必须保存的证据 | 准入结果 |
| --- | --- | --- | --- |
| E1 extern双位置 | 临时fixture含类内extern原型、另一include中的类外实现、不同class同名方法和一个保护实现；按SDK已文档化的关系遍历方法及Location | 每个位置的NPI对象kind、查询关系、文件/行范围、所属方法身份；与明文原型/实现逐行对照 | 只有可可靠区分prototype/definition时才单独修订SourceSpan；只有实现位置时保持现合同，不推测原型行 |
| E2 宏来源链 | 临时fixture含utils宏、两层嵌套宏、同名宏的两个编译变体；对比生成成员定位与当前可读宏定义 | 编译命令/define、调用点、生成符号、SDK实际可得的宏定义或展开关系及缺失状态 | 调用点、当前文件宏定义、编译展开分别标来源；无展开关系不能伪造preprocessed正文 |
| E3 顶层上下文 | 临时fixture将局部sequence timeout与module独立全局timeout放到不同文件，记录当前class-only域能回答的范围 | 两个定时入口的源码/作用域和查询命中范围 | 作为后续module/program/file浏览spec输入；不默默扩大第一期package/class定义域 |

E1/E2可与第13节计划新增的code_navigation fixture一起设计；只新增专用fixture，不改变或重建已缓存XIF/APB/AXI来迁就探针。未读到的受保护实现不能换成另一个工具版本的同名明文文件。

若未来需要显式文件阅读或宏检索，应单独定义action/参数、来源映射、预算、错误和测试，再按第11节完整同步action目录、schema生成器与skill。第一期code.source仍只接受现有selector与窗口合同，不接受一个未设计的任意file参数。

### 16.4 本轮验收结论与尚未证明事项

- 临时session只加载离线JSON索引一次；100题104次查询序号连续且同一进程。真实C++ NPI上下文、长时间license存活、数据库reload和原生handle泄漏尚未验证，必须在P1/P2完成。
- 100题共享分为demo 378/380、rg 379.5/380；编译专项19.5/20与9.5/20。详细逐项分值及原标准勘误在报告附件，不用总分替代能力边界。
- 速度验收分开测engine冷启动、scope首次构建、复用连接查询、轻客户端查询、输出序列化与整段AI任务。不得用207倍离线查询加速承诺AI或正式NPI同倍加速。
- 当前源码与编译来源一致性仍为unknown，除非未来取得并核对编译时内容指纹；常驻索引本身不提供该证明。
- 用户可复用临时服务和批量示例；它不是新增公开xdebug API，也不是未来正式测试可依赖的缓存。

