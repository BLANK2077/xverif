# xcov complex modinfo fixture

该正式 fixture 覆盖多层参数化例化、interface/modport、generate-for、generate-if、
同 module 多实例及不同业务激励。

`lane_worker` 内包含六个互不相同的独立时序控制结构：if-chain、if+case、
unique case 内嵌 if、nested-if、priority casez、case 内嵌 if/else-if。
这些策略共同决定 response acceptance，不是无效 coverage 代码。

正式验收由 `xcov.modinfo_complex` catalog suite 执行。VDB、simv、URG bundle、NPI log
和 pytest result 均为生成物，不进入版本控制。
