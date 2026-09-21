# xdebug NPI 代码导航 demo：大型 AXI 环境与双代理对照报告

日期：2026-09-18。范围：临时 demo、真实数据库探针、临时测试、两个独立代理的静态环境理解实验。仓库只新增方案与报告文档，没有修改产品源码、schema、仓库测试、Makefile 或 fixture，也没有执行重新编译仿真。

对应实施方案见 [验证代码导航 spec](XDEBUG_VERIFICATION_CODE_NAVIGATION_SPEC_2026-09-18.md)。本文中的 demo 是临时 Python 原型，尚未接入 xdebug 的 CLI、MCP 或 action schema。

## 1. 结果

NPI 在大型验证环境中可以提供有效的结构化导航。对照实验中，demo 组和 `rg/read/search` 组均正确回答了主要事实问题，按事先冻结的评分标准都是 **44/44**。本轮没有观察到正确率差距。

demo 组更快完成了这组任务，用了更少查询，产生的工具输出也更少。文本组在宏定义、条件类型绑定和测试启动过程上给出了更多有效细节。这支持把 NPI 用于精确定位声明、成员和继承，再按明确入口查阅源码及编译配置；不支持宣称 NPI 已经覆盖全部验证代码理解能力。

| 指标 | demo 组 | rg/read/search 组 |
| --- | ---: | ---: |
| 主要事实得分 | 44 / 44 | 44 / 44 |
| 单列的编译集合覆盖题 | 2 / 2 | 1 / 2，正确声明无法证明数量 |
| 回答题数 | 12 / 12 | 12 / 12 |
| 代理自行记录的任务时间 | 218 秒，3 分 38 秒 | 301 秒，5 分 01 秒 |
| 包装器记录的查询命令 | 33 | 62 |
| 命令产生的 stdout | 102,295 字节，约 99.9 KiB | 409,716 字节，约 400.1 KiB |
| 命令执行时间之和 | 64.326 秒 | 6.770 秒 |
| 命令返回码 | 33 次为 0 | 55 次为 0，7 次 rg 为 1（无匹配） |
| 答案中的引用条数 | 59 | 86 |
| 引用涉及的不同文件 | 21 | 23 |
| 文件不存在或行号越界的引用 | 0 | 0 |

本次 demo 组的记录时间少 83 秒（约 27.6%），查询命令少 29 次（约 46.8%），stdout 产出少约 75.0%。这些是一次配对实验的观察值，不是稳定性能收益或统计显著性结论。

命令本身反而是文本工具更快。demo 每次启动 Python 都读取约 24.9 MB 的 JSON 索引，存在明显原型开销。命令时间相加还包含并行命令的重叠，不能当作任务的串行耗时。这里不宣称 demo 的查询引擎比 rg 快。

## 2. 环境规模与口径

### 2.1 使用的真实环境

- 数据库：仓库已缓存的 `xdebug.axi_vip` daidir。
- VCS / Verdi：本机 `X-2025.06-SP1`。
- UVM：本机 VCS 提供的 UVM 1.2。
- SVT common：`X-2025.06`；AMBA SVT：`X-2025.12`。
- Python：仓库 `.conda-xverif/bin/python`，3.12.13。
- NPI 探针在 host 执行，显式使用 `XVERIF_TEST_EXECUTION_ENV=host`；复用既有 license 环境。

没有生成一个只含少数演示类的小环境。被查询的编译数据库包含大量真实 UVM/SVT 类型；文本组面对其完整可访问源树，其中也有未编译的 simulator 变体与宏条件分支。

### 2.2 源树规模

文件统计后缀为 `.sv/.svh/.svp/.svi/.svip/.pkg/.v/.vp`。早期统计的 4,973 个文件未包含 `.svip`；实验后补计了 124 个此类宏/工具文件，完整口径为 **5,097 个文件、379,913,007 字节，约 362.3 MiB**。两组获准访问的源树从实验开始就相同，没有在补计时更换数据集。

| 源树 | 文件数 | 说明 |
| --- | ---: | --- |
| `xdebug/testdata/waveform/axi_vip_real` | 10 | 自定义 test、sequence、env、scoreboard、top |
| VCS `etc/uvm-1.2` | 183 | UVM class、TLM、sequence 和宏 |
| SVT common `X-2025.06/sverilog` | 738 | common class、include、工具宏、simulator 变体 |
| AMBA SVT `X-2025.12` | 4,166 | AXI 与其它 AMBA 组件、agent、transaction、配置等 |
| 合计 | 5,097 | 源树扫描域，不能当作全部参与本次编译的文件 |

### 2.3 NPI 编译查询域规模

| package / scope | class 数 |
| --- | ---: |
| `uvm_pkg` | 332 |
| `svt_uvm_pkg` | 168 |
| `svt_axi_uvm_pkg` | 873 |
| `svt_amba_common_uvm_pkg` | 9 |
| 含 fixture 自定义类的 compilation-unit scope | 8 |
| 另外两个 compilation-unit scope | 0 |
| 合计 | **1,390** |

NPI 顶层枚举到 7 个 Package 类型的 scope，其中 4 个是上述命名 package，3 个是编译器生成的单元。demo 将后者显示为 `compilation_unit_N` 临时别名，不能称源码里定义了 7 个命名 package。这种别名仅属于 demo，正式产品 selector 规则见 spec。

| NPI 返回记录 | 数量 |
| --- | ---: |
| property | 6,341 |
| method（function/task） | 13,382 |
| constraint | 341 |
| parameter | 438 |
| 成员记录总数 | 20,502 |
| 成员不同 path 数 | 20,480 |
| 存在多个表示的 path | 22 |
| class/member 定位涉及的文件 | 336 |

这些成员数量是原始迭代记录数。22 个 path 的多个表示甚至具有相同 kind/file/line，尚未完成对象身份和 specialization 归并，不能称为 20,502 个唯一声明。

代表性复杂类 `svt_axi_transaction` 有 244 条直接 property、163 条 method、4 条 constraint 记录，所在 VCS 源文件约 28,572 行。实验确实覆盖了大类、多层继承和跨源树导航。

## 3. demo 做了什么

临时目录为 `<tmp>/npi-code-demo/`。主要组成：

| 文件 | 作用 |
| --- | --- |
| `build_index.py` | 从已有 daidir 读取 NPI LM；不启动编译或仿真 |
| `index.json` | 本地元数据索引；当前为修正后的 v2 |
| `demo.py` | stats、search、describe、members、inheritance、source 六种命令 |
| `test_demo.py` | 临时验收测试，最终 22 项 |
| `run_capture.py` | 记录两组每条命令、返回码、耗时、stdout/stderr 字节数 |
| `benchmark_brief.md` | 两组共同的冻结题目与限制 |
| `rubric.json` | 代理启动前冻结的评分项目 |
| `frozen-demo-v1/` | 完整保存实际参试的 v1 程序、索引、题目、评分规则与测试 |

索引从 Package→ClassDefn→Variables/Methods/Parameter/Constraint 等关系提取。基类经 Extends 的 typespec 追到 ClassDefn，类型解链保留 typedef 关系。方法形参通过 IODecl 读取，默认表达式必须再经过 formal variable。

`source` 根据 NPI 对象的文件与行范围读取当前文件，不做全文搜索 fallback，不重建 class body，不把 decompile 输出当成源码。它始终返回 `compiled_match=unknown`；SHA-256 只标识本次读取文件。

实验 v1 建索引耗时 **16.076 秒**，JSON 文件为 **24,864,517 字节**。这是单次观察，单独列为准备成本，没有混入代理任务时间，也没有据此做吞吐或 p95 承诺。demo 编写与环境准备的人工作业时间未纳入两组比较。

查询阶段读取离线索引，不再为每条查询加载 NPI。正式 xdebug 应使用 session 内 service 与内存索引；这个临时架构适合验证功能边界，不能直接代表未来 C++ engine 的性能。

## 4. 对照实验如何进行

用户明确要求启动两个子代理，因此实际启动了两个独立代理，分别使用 demo 和文本工具。两组没有继承主代理的探索答案；给相同题目、同一源环境、相同 12 分钟上限，未人为设置不同模型或推理档位。

### 4.1 两组限制

| 条件 | demo 组 | 文本组 |
| --- | --- | --- |
| 环境访问 | 只能调用提供的 demo | 只能 rg/sed/cat/head/tail/wc/ls |
| 原始索引 / 探针 / oracle | 禁止读取 | 禁止读取 |
| 直接读环境源码 | 通过 demo.source | 通过文本工具 |
| 编译、仿真、运行时日志与波形 | 禁止 | 禁止 |
| 看另一组结果 / 互相沟通 | 禁止 | 禁止 |
| 写入范围 | 各自临时结果目录 | 各自临时结果目录 |
| 证据 | 文件行号或具体 selector | 文件行号 |

隔离依靠任务指令和独立输出目录，没有设置 OS 级访问隔离。查询包装器记录了指定命令，代理也声明遵守了范围；不能将这描述成密码学可证明的盲测。

### 4.2 题目覆盖

共 12 题，覆盖自定义环境架构、跨包继承、继承方法签名、泛型实际绑定、成员访问属性、精确方法集合、scoreboard 判定、配置计算、并发调度、宏来源、编译集合与运行时边界。

题目和评分规则在两组启动前冻结。主要事实题为 Q1–Q10、Q12，每题 4 个评分点，总计 44 分；Q11 是工具覆盖能力题，单列 2 分，不把文本工具拿不到的精确编译数量混入源码理解主分。

主代理依据独立源码阅读、原始 NPI 探针和类型参数补充探针核对答案。评分为人工事实审阅，并非独立盲审或模型裁判统计。所有主要评分点均能在双方答案中找到，没有因答案更长而加分。

### 4.3 记录与冻结检查

- demo 组自行记录：04:58:25–05:02:03 UTC。
- 文本组自行记录：04:58:40–05:03:41 UTC。
- 两组均提前于 12 分钟上限完成，均提交 `answers.json` 与 `report.md`。
- 实验结束后复核 8 个冻结文件的 SHA-256，全部与启动前一致，再归档 v1。
- 未将后续修正后的 v2 能力、测试或响应计入 v1 成绩。
- 引用检查确认双方引用文件存在、行号在文件范围内；该机械检查不替代人工检查“这行是否支持该事实”。

## 5. 逐题结果与理解差异

| 题号 / 内容 | demo | 文本组 | 实际差异 |
| --- | ---: | ---: | --- |
| Q1 八个自定义类、基类、连接关系 | 4 | 4 | 都正确区分 virtual sequencer 与 monitor 数据通路 |
| Q2 master sequence 完整继承链 | 4 | 4 | demo 一次结构查询得到链；文本组额外追了 UVM 映射宏 |
| Q3 get_response 归属、签名与默认值 | 4 | 4 | 都定位 UVM generic 声明；文本组进一步列出 SVT 宏的两个条件类型分支 |
| Q4 FIFO 使用处 T 与默认 T | 4 | 4 | demo 组识别了元数据默认值与使用处源码差异，没有误答 int FIFO |
| Q5 四个 property 的访问性、rand、类型 | 4 | 4 | 元数据与源码吻合；都保留位宽宏而未猜展开值 |
| Q6 五个直接 response 方法 | 4 | 4 | demo 给编译对象定位，文本组给可读 extern 原型行号；证据位置层次不同 |
| Q7 scoreboard snapshot / 在途写 / 比较 | 4 | 4 | 都指出有读 beat 被跳过，缺 snapshot 时 OK 计数不代表数据比较 |
| Q8 配置函数与计算 | 4 | 4 | 都区分局部默认与 Makefile 参数，并算出 128 |
| Q9 多 ID、读写并发与完成等待 | 4 | 4 | 都指出不存在先写完再读屏障；文本组额外追到 test 的 slave response drain |
| Q10 get_type 宏生成与源码版本 | 4 | 4 | 文本组读到了宏生成的 registry proxy 代码；demo 组明确没有取得完整展开体 |
| Q12 100 ns 的对象和动态调用 | 4 | 4 | 都拒绝无证据断言；文本组补充默认路径先等待 300 ns 的静态线索 |
| 主要事实合计 | **44** | **44** | 未观察到正确率差异 |
| Q11 编译集合覆盖，单独计分 | 2 | 1 | demo 给精确域内数量；文本组正确声明无法从文本证明 |

### 5.1 demo 的具体收益

继承链从自定义 sequence 进入 SVT AXI、SVT common、UVM，最后到 uvm_void，共 9 个类。结构化查询直接保留 package、文件、归属，不需要反复在多套 simulator 源树中找同名类。

`get_response` 直接被定位到 `uvm_pkg::uvm_sequence`，且继承深度为 3。`code.members` 类能力可以把“当前类声明”“从基类找到”“其它类同名”分开，对 AI 精确引用代码很有价值。

复杂 transaction 的 response 方法查询只返回 5 个 function、0 个 task，附真实 owner 与计数。文本组也找全了，但要排除注释、调用、同名方法和其它 simulator 变体；这在查询命令数和输出量上产生了本次差异。

这些观察支持降低定位成本的方向，但本实验只有一个大型环境和一对代理，不能把全部时间差因果归于工具。

### 5.2 文本组多获得了什么

文本组找到了 `SVT_AXI_MASTER_TRANSACTION_TYPE` 的条件定义：当前源码的 SVC 分支使用 `svt_axi_transaction`，另一分支使用 `svt_axi_master_transaction`。它仍正确保留了编译宏快照未知的限制。

文本组沿 `uvm_component_utils` 找到内部 registry 宏，说明 `get_type()` 返回 `type_id::get()`。demo 的 NPI source range 只指到 scoreboard 第 35 行宏调用，无法替代宏定义阅读。

文本组还追到默认 test 的 `wait_for_reset()` 先延迟 300 ns，再调用创建 sequence 的路径，因此提醒“100 ns 时对象是否已存在”也不能预设。这是比单纯回答运行时状态未知更具体的源码推论；它没有把这个推论说成实际运行观测。

正式产品规划因此应保留显式阅读宏、include、编译配置和 test 调用方的途径。任何工具切换都需要有明确入口与来源说明，不能在 NPI 失败时悄悄改用文本结果。

## 6. 实验揭示的四个关键边界

### 6.1 泛型默认值与实际绑定需要不同关系

`axi_scoreboard.master_fifo` 的当前源码写的是 `uvm_tlm_analysis_fifo#(svt_axi_transaction)`。但 v1 用 Parameter 关系读到 T 的 Typespec 是 int；同样现象还出现在 slave_fifo、master_export。

主代理另开只读 NPI 探针，三项均确认：

```text
ClassTypespec → Parameter(T) → Typespec/Expr/TypedefAlias = int
ClassTypespec → ParamAssign → Lhs = T
                            → Rhs = svt_axi_transaction (ClassDefn)
```

这不是“NPI 完全拿不到实际类型”。问题是读取了不足以表示实际绑定的关系。实际参数需要合并 ParamAssign，且 Rhs 可能是 ClassDefn，不能假设一定为 Typespec。

v2 已新增 `actual_bindings`，明确输出该关系证据；仍保留原 `parameters` 的未认证语义。对于 Rhs 仍为类型参数的情况，不声称完成了整个泛型继承体系的替换。

### 6.2 多个成员表示不能直接折叠

构建 demo 时发现 22 个 path 对应多个 NPI 记录，例如 `uvm_pool.pool`。它们可能具有相同名称、kind 和源码坐标，不能只按路径取第一个。

初始开发版本曾因此在整个索引初始化时失败，已在正式对照实验前修正为局部歧义：相关精确查询返回 `SYMBOL_AMBIGUOUS`，其它类查询照常工作。19 项参试测试中已覆盖这一行为。

对象身份与 specialization 的进一步归并仍未完成。spec 增加了不可消解歧义、计数口径和不阻塞其它查询的要求。

### 6.3 NPI 的方法位置不总是可读原型位置

在 `svt_axi_transaction.svp` 中，以下五个方法可以同时从 NPI 和源码确认：

| 方法 | NPI 报告行号 | 当前可读 extern 原型行号 |
| --- | ---: | ---: |
| get_response_status | 22721 | 9836 |
| get_response_assertion_time | 22721 | 9841 |
| get_response_assertion_time_of_addr | 22721 | 9846 |
| get_num_write_responses | 24083 | 10021 |
| is_read_response_without_data | 24083 | 10174 |

NPI 坐标指向受保护的实现块，不代表它可以返回该块的可读完整正文。方法“存在且归属正确”与“源码片段可读”应当分成不同能力。

v1 保留了原始位置，但没有完整的保护区域读取检查。实验后 v2 增加边界识别；请求范围涉及保护内容时返回 `SOURCE_PROTECTED_CONTENT`，不返回密文冒充方法体，也不改走 decompile。

### 6.4 宏与源版本必须保留不确定性

`axi_scoreboard.get_type` 的 NPI 方法范围是 35–35，磁盘内容为一行注册宏。这个位置有用，但只能作为展开触发点。

所有 demo.source 响应都标注 current_filesystem、preprocessed=false、compiled_match=unknown。没有编译时源码 hash，就不能因为行号“看起来正确”而声称文件与建库输入一致。

## 7. 与验证环境本身有关的发现

双方独立指出 scoreboard 并非对所有读 beat 执行比较：

1. READ started 时，只有 expected_mem 已有值且该地址没有在途写，才设置 snapshot.compare_valid。
2. READ completed 时，只有有效 snapshot beat 执行实际数据相等比较。
3. 没有找到 snapshot 的分支，在 expected_mem 存在时仅增加 num_compare_ok，没有执行数据比较。

证据在 [axi_scoreboard.sv](../xdebug/testdata/waveform/axi_vip_real/tb/env/axi_scoreboard.sv) 的 started、completed 处理函数。这个结果体现了双方都读懂了多方法之间的判定关系，而不只是列出类名。

这是当前实现的静态行为观察，不是本轮新引入的问题，也没有在本轮修改其逻辑。是否需要改变该记分策略，应结合该 fixture 的验证意图单独决定。

## 8. 测试、版本与交付验证

### 8.1 实验 v1

参试前通过 19 项 unittest，覆盖：

- 八个自定义类与大型库规模；跨包继承链。
- declared/inherited 区别与声明 owner。
- 形参顺序、方向、默认表达式；一元负号表达式不冒充直接常量。
- property visibility/rand；真实方法范围、宏调用范围。
- 当前文件来源、hash、未知编译匹配状态。
- class body 不可用、符号不存在、局部歧义。
- 分页不改变完整计数；源码分页保留原始行号。
- FIFO 类型定义与使用处源码分开核对。

v1 测试运行结果为 19/19，0.637 秒。参试冻结文件哈希审计通过；v1 完整副本保存在 `frozen-demo-v1/`。

### 8.2 最终 demo v2

两组交卷并完成冻结检查后，才修正临时 demo：

- 从 ParamAssign 的 Lhs/Rhs 提取实际绑定证据。
- 读取源码前识别 protected 区域，明确返回不可读。
- 增加三个测试：三个真实参数化成员的实际绑定、真实 vendor protected 位置、注释中的伪保护指令。

最终 **22/22 测试通过，0.689 秒**。v2 只重新提取了一次既有 daidir 的元数据，没有重新构建或仿真 fixture。

这些是功能和边界测试，不是整个 xdebug 正式回归。本轮没有把 demo 伪装成已完成 native/MCP 集成，也没有运行与文档交付无关的全仓回归。

### 8.3 尚未验证或实现

- 多版本 VCS/Verdi/数据库兼容矩阵。
- 所有 NPI duplicate handle 的声明级归并。
- 任意参数化继承链的完整类型替换。
- 普遍的 extern 原型定位、宏展开追踪与完整 class body。
- 通用静态引用/调用图；本轮早期 XIF 探针只验证了部分关系。
- 真实运行时对象与动态分派。
- 生产接口的严格 JSON schema、deadline、资源预算、MCP 输出与稳定分页合同。

这些限制已进入 spec 的实施阶段与验收用例，不会因 demo 可以运行而视为已经完成。

## 9. 对 xdebug 规划的调整

第一期仍建议五个 action：`code.search`、`code.describe`、`code.members`、`code.inheritance`、`code.source`。本实验强化了以下实施要求：

| 优先级 | 具体要求 | 原因 |
| --- | --- | --- |
| P1 必须 | owner、kind、selector、declared/inherited 分开 | 结构化导航在本轮减少了定位操作 |
| P1 必须 | 参数默认、ParamAssign 实际绑定、未验证关系三者分开 | 避免把 transaction FIFO 误判为 int FIFO |
| P1 必须 | 局部歧义、对象身份、原始条数与唯一声明数分开 | 大型库已出现相同坐标的多个成员表示 |
| P2 必须 | 源位置标注语义、保护内容明确失败、宏调用不冒充方法体 | vendor/宏方法的 NPI 行号未必是可读正文 |
| P2 必须 | 当前文件与编译快照一致性明确 unknown | 当前 NPI 位置不包含编译源码版本证明 |
| P2 必须 | 保留每次结果的完整性和来源 | AI 需要区分已编译集合、当前文本和运行观测 |
| 后续独立研究 | 宏、include、编译宏配置的显式导航入口 | 文本组在这些问题上补充了更多细节 |
| 后续独立研究 | 原型位置与实现位置分别表示 | 精确阅读 extern 方法需要两种位置 |

推荐给 AI 的使用顺序是：先按 package/class 取得精确声明，再沿 owner/继承/类型关系缩小范围，然后读取对应源码。遇到宏、include、编译配置时，显式选择相应文本证据；静态接口不能回答的问题保留 unknown，运行时问题另需运行时通道。

不建议第一期直接宣称“验证代码知识图谱完整”“支持任意 UVM 对象查询”或“自动恢复 VIP 实现”。当前证据没有支持这些能力。

## 10. 复现和查看结果

临时目录仍保留完整 demo 和实验产物。可直接运行：

```bash
NPI_DEMO_DIR=<tmp>/npi-code-demo
NPI_DEMO_PYTHON=$HOME/.conda-xverif/bin/python

"$NPI_DEMO_PYTHON" "$NPI_DEMO_DIR/demo.py" stats
"$NPI_DEMO_PYTHON" "$NPI_DEMO_DIR/demo.py" inheritance --path compilation_unit_1 axi_multi_id_master_seq
"$NPI_DEMO_PYTHON" "$NPI_DEMO_DIR/demo.py" describe --path compilation_unit_1 axi_scoreboard master_fifo
"$NPI_DEMO_PYTHON" "$NPI_DEMO_DIR/demo.py" source --path compilation_unit_1 axi_tb_env connect_phase --view range
```

运行最终临时测试：

```bash
cd <tmp>/npi-code-demo
PYTHONDONTWRITEBYTECODE=1 $HOME/.conda-xverif/bin/python -m unittest -v test_demo
```

v1 的复现入口为同一目录下 `frozen-demo-v1/demo.py`；它使用该子目录中的冻结 index，不会读取 v2 index。

关键产物：

- [demo 使用说明](<tmp>/npi-code-demo/demo_usage.md)
- [最终 demo](<tmp>/npi-code-demo/demo.py)
- [临时测试](<tmp>/npi-code-demo/test_demo.py)
- [共同题目](<tmp>/npi-code-demo/benchmark_brief.md)
- [冻结评分规则](<tmp>/npi-code-demo/rubric.json)
- [demo 组答案](<tmp>/npi-code-demo/arms/demo/answers.json)
- [文本组答案](<tmp>/npi-code-demo/arms/rg/answers.json)
- [逐项评分](<tmp>/npi-code-demo/grading.json)
- [命令统计](<tmp>/npi-code-demo/metrics.json)
- [冻结检查](<tmp>/npi-code-demo/freeze_audit.json)
- [v2 测试日志](<tmp>/npi-code-demo/tests-v2.log)

每条原始命令及输出位于 `arms/<arm>/commands/`。native 日志没有复制进仓库报告。`/tmp` 产物可能被系统清理；本文与 spec 已保留环境、合同、方法、主要事实、评分和限制，但不将临时路径当作长期产品依赖。

## 11. 解读限制

本实验只有一个环境、一个题集、一对代理，没有重复运行、交换工具、交叉验证或置信区间。题目包含结构化导航任务，可能使这一类工具的优势更容易显现。两组工具可见内容也不同：demo 提供编译结构，文本组可读未编译分支、宏定义和配置；Q11 因此单列。

工具输出字节数是包装器捕获的完整 stdout，包含可能在工具界面被截断的内容，不等于模型真正看到的字符数或 token 消耗。没有得到可靠的逐代理 token 计费数据，不据此计算 token 节省或费用收益。

任务时间由代理记录，包含其检索和答案组织过程，但不是受控的纯推理耗时。机器负载、并发、代理检索策略与生成长度也会影响结果。索引准备、demo 开发和主代理复核时间没有计入两组任务时间。

据此可以支持的结论是：**本轮 NPI demo 在保持主要事实正确性的同时减少了结构定位操作；文本检索在宏和跨文件实现细节上仍提供了额外信息。** 下一步应按 spec 实施有限、可验证的导航合同，再用不同环境和交换工具的重复实验验证收益。
