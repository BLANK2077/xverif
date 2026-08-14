# xcov 的设计理念：让覆盖率收敛成为可审查的工程流程

覆盖率工具很容易停留在“看数字”这一步：总代码覆盖率是多少，哪个模块低于目标，报告里还有多少红色条目。真正费时间的工作却在后面。每一个 coverage hole 为什么没有覆盖？应该补激励，还是可以排除？排除以后能否被复查？换一版 VDB，这些结论还能不能继续使用？

xcov 围绕这几个问题设计。它不试图用同一种接口包办所有事情，而是把覆盖率读取、缺口整理和 exclusion 执行拆开，让每一层使用最合适的工具。

## URG 负责读，NPI 负责写

xcov 对工具边界的划分很明确：覆盖率统计和报告导出由 URG 完成，NPI 只参与 exclusion。

读取 VDB 时，xcov 调用 URG 生成 XML summary。`session.xml` 提供实例层次和各类覆盖率数据，包括 line、condition、toggle、branch、FSM、assertion 和 functional coverage。父实例的统计直接采用 URG 给出的 subtree score，不再把子实例重复累加。这样得到的数字与 Verdi/URG 报告保持同一套语义，也避开了 NPI 全树遍历容易遇到的重复计数和性能问题。

summary 适合回答“哪里覆盖率低”，却不足以回答“具体缺了什么”。当用户或 AI 需要查看详细 hole 时，xcov 再让 URG 导出受限范围内的报告。代码覆盖率的详细信息来自 `modinfo`，assertion 和 functional coverage 则读取各自的 URG 产物。

整个读取过程不需要加载 NPI。只有确认某个 hole 应该排除时，xcov 才惰性打开 NPI，在当前 VDB 中定位目标并修改 report-time exclusion 状态。

这条边界很重要。URG 是覆盖率事实的来源，NPI 是 exclusion 的执行接口。两者各做一件事，结果更容易解释，出错时也知道该查哪一层。

## 从 modinfo 到 XOUT

原始 `modinfo` 面向传统报告工具，信息完整，但篇幅很大。一个条件表达式可能展开成多组 truth table，分支和 FSM 也会夹杂大量上下文。人可以在 Verdi 中逐页查看，AI 直接读取这些文本则会浪费大量上下文，还容易把报告结构误当成语义。

xcov 会解析 `modinfo`，保留定位 hole 所需的源码位置、实例、表达式、分支取值和状态跳转，再转换成信息密度更高的 XOUT。

XOUT 不是简单压缩文本。它会按 coverage 类型整理信息。例如，line coverage 按过程块列出未覆盖语句；condition 和 branch coverage 把表达式中的条件标成可引用的项，再列出尚未覆盖的取值组合；FSM 则按状态机组织缺失的 state、transition 和 sequence。重复表达同一事实的字段会被去掉，但用于判断和定位的信息仍然保留。

每个语义缺口都会得到一个 `gap_id`，例如 `L0001`、`B0002`、`C0003`、`F0001`、`A0001` 或 `FC0001`。这个 ID 是当前结构化导出中的操作句柄。AI 不必重新描述一长串源码位置和 truth table，只需引用对应导出文件中的 `gap_id`，便可以逐项提交 exclusion。

`gap_id` 也让 review 变得直接。审核者可以回到同一份 XOUT，看到这个 ID 对应哪条语句、哪种条件组合或哪个状态跳转，而不是面对一条难以核对的数据库内部 handle。

## 排除一个 hole，也可以排除一棵实例子树

逐项 exclusion 适合处理离散缺口。AI 读取 XOUT 后，可以判断某个 gap 应补充激励，还是确实属于不可达路径、失效保护逻辑或配置裁剪，并通过 `gap_id` 发起排除。

有些场景不适合逐条处理。比如一个实例在当前产品配置中根本不会启用，它下面可能有成百上千个 coverage hole。此时 xcov 提供与 Verdi 类似的实例级操作：可以只排除当前 instance，也可以设置递归选项，把它的真实子 instance 一起排除。

这里的“递归”不是字符串前缀匹配。xcov 使用 URG XML 中记录的实例层次展开目标，只处理实际存在的 elaborated instance。这样可以避开 generate scope、相似实例名和层次前缀带来的误伤。每一个展开后的目标都会保留精确身份，后续 remove 也只撤销原来记录的 ownership，不会根据新层次重新扩大范围。

## CSV 保存的是决定，EL 保存的是执行结果

原生 EL 文件适合被 Synopsys 工具加载，却不适合承担 exclusion 的长期管理。

首先，EL 不保存排除理由。过一段时间再看到某条 exclusion，很难知道它来自规格限制、不可达状态，还是一次临时规避。其次，EL 与生成它的设计和 VDB 存在 checksum 关系。RTL、编译参数或层次发生变化后，旧 EL 可能因为 module checksum mismatch 而无法用于新 VDB。

xcov 因此把 CSV 作为自有 exclusion 的持久化来源。CSV 保存可移植的语义定位信息，并强制每条记录带有非空 `reason`。AI 可以提出 exclusion，但不能只说“建议排除”；它必须写明理由，例如：

- 规格禁止该状态组合；
- 当前产品配置未例化该功能；
- 分支只用于仿真故障注入；
- 该实例及其子实例在此配置下被静态关闭。

这些理由会进入 review。审核者检查的是一项工程决定，而不只是工具状态。

EL 的定位则更简单：它是针对某个 VDB 生成的原生执行产物。完成分析后，xcov 先把带 reason 的 exclusion 导出到 CSV，再通过 NPI 保存 EL。两类文件都成功落盘后，session 才能关闭。

## 用语义记录跨过 checksum

CSV 也提供了应对 EL checksum 问题的办法，但它不是去修改或绕过 checksum。

面对新的 VDB，xcov 读取 CSV 中的语义 selector，在当前 coverage database 中重新解析每个目标。解析必须得到唯一对象；零匹配和多匹配都会失败，避免把旧设计中的决定错误套到新设计上。目标确认后，NPI 在新 VDB 中实时设置 exclusion，最后再导出一份属于这个 VDB 的 EL。

流程可以概括为：

```text
旧 VDB
  → URG 统计与导出
  → XOUT gap
  → gap_id / instance exclusion
  → 带 reason 的 CSV
  → 当前 VDB 的 EL

新 VDB
  → 加载同一份 CSV
  → 在新数据库中重新解析目标
  → NPI 实时执行 exclusion
  → 生成与新 VDB 匹配的新 EL
```

真正被复用的不是旧 EL，而是经过 review 的 exclusion 决定。EL 每次根据当前 VDB 重新生成，因此不需要冒险编辑原生文件，也不会把 checksum mismatch 当成可以忽略的警告。

## 一次完整的覆盖率收敛

从使用者的角度看，xcov 的流程并不复杂。

先打开 VDB，选择是否加载已有 CSV 或 EL。随后通过 URG summary 查看实例层次和覆盖率分布，定位需要分析的范围。对低覆盖率实例导出详细报告，把 `modinfo` 等 URG 产物整理成 XOUT。

AI 阅读 XOUT 后逐项处理 gap。能通过合理激励覆盖的，进入补测计划；确认无需覆盖的，通过 `gap_id` 添加 exclusion，并给出可供 review 的理由。对于整体关闭的功能块，可以选择 instance 级排除，必要时递归处理其真实子实例。

修改完成后重新运行统计和详细导出，确认排除范围符合预期，没有掩盖其它 hole。最后先导出 CSV，再导出 EL。CSV 保存决定和理由，EL 保存当前 VDB 的原生 exclusion 状态。

xcov 的设计重点不在于替人“消灭”coverage hole，而在于把每一个 hole 变成可以定位、操作、复查和迁移的条目。URG 提供覆盖率事实，XOUT 把事实整理成适合 AI 阅读的工作集，CSV 留下审核记录，NPI 把批准后的决定写回当前 VDB。工具之间的边界清楚了，覆盖率收敛才不会变成一堆无法追溯的百分比和 EL 文件。
