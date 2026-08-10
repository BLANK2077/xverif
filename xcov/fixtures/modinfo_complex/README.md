# xcov complex modinfo fixture

该正式 fixture 覆盖多层参数化例化、interface/modport、generate-for、generate-if、
同 module 多实例及不同业务激励。

`lane_worker` 内包含六个互不相同的独立时序控制结构：if-chain、if+case、
unique case 内嵌 if、nested-if、priority casez、case 内嵌 if/else-if。
这些策略共同决定 response acceptance，不是无效 coverage 代码。

同一 module 还包含十二条 RHS 各异且参与可观察输出的 continuous assign，覆盖逻辑运算、
XOR、三目、inside、通配相等、归约、拼接比较、算术比较、indexed part-select 和系统函数。
连续赋值和既有 always_ff 数据通路内都包含三目运算，用于验证 URG standalone ternary
decision 与嵌套 decision-path marker。Active 与 sparse instance 共享 reset，只通过不同
业务数据激励形成不同且均低于 100% 的 code coverage。

正式验收由 `xcov.modinfo_complex` catalog suite 执行。VDB、simv、URG bundle、NPI log
和 pytest result 均为生成物，不进入版本控制。
