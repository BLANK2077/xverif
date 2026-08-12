# xverif 测试持续进度与耗时定位报告

日期：2026-08-12

## 1. 结论

本轮最终验收耗时长的主因不是 fast/regression/nightly 本身失去响应，而是最后执行的
`--xverif-fixture-validation --xverif-all-fixtures` 会**串行强制重建全部 27 个 fixture**。旧入口只在
每个 fixture 完成后打印，因此遇到 6～13 分钟的 builder 时终端长时间没有输出，也没有正式的
fixture/phase duration 文件。

依据 2026-08-12 20:06～20:44 发布的不可变 fixture generation 时间与 builder/probe log 关闭时刻，
四组工作约占 34.8 分钟：

| Fixture/组 | 近似时长 | 主要阶段 | 证据与原因 |
| --- | ---: | --- | --- |
| `xdebug.stream_differential_tool` | 784.1 s | builder 783.9 s | 从零编译带 test-only legacy oracle 的整套 xdebug engine；probe 约 0 s |
| `xdebug.axi_vip` | 592.8 s | builder 590.5 s | 完整 VCS/SVT AXI VIP 编译及多场景仿真；probe 约 0 s |
| `xcov.large_summary` | 407.7 s | builder 402.7 s | 生成大 coverage 设计、VCS coverage 编译和 515 ns 仿真；probe 4.9 s |
| active-trace 五组 | 300.8 s | builder 为主 | 多个独立 SystemVerilog case 的 VCS 编译/仿真；其中 composite 101.3 s、phase4 103.9 s |

上述四组合计约 2085 秒（34.8 分钟）。27 个 generation 连续发布时刻覆盖约 38.4 分钟；其余时间来自
其它 fixture、dependency/fingerprint、发布以及 pytest 入口开销。因此全 fixture validation 是整套
最终验收的绝对关键路径。

## 2. Gate 内部耗时

最终 nightly 结果目录 `.xverif-test-results/20260812-195659-cgf2mtk5/` 的 JUnit/report 记录：

- wall-clock：534.23 s（约 8 分 54 秒）；
- 8 个 worker 的 item duration 累计：1031.0 s，因此累计值不能当 wall-clock；
- 最慢单项：stream differential 81.9 s、AXI VIP 55.5 s、native XOUT 全矩阵 41.1 s、x-npi
  performance 40.9 s、analysis cache benchmark 33.4 s；
- suite 累计最高的是 `xcov.mcp_integration` 181.2 s，但它由多个用例组成并能与其它 resource group
  并行，不能直接解释 nightly 的 534 s 关键路径。

regression wall-clock 331.81 s，fast wall-clock 50.97 s。三档 gate 合计约 15 分 17 秒，而全 fixture
validation 单项约 38～42 分钟；因此用户感知的“最终回归很长”主要来自最后的强制重建，而不是 pytest
点阵阶段。

## 3. 已实现的持续进度与耗时合同

所有正式 gate、fixture prepare 和 fixture validation 现在统一具备：

- 默认每 30 秒打印 `[xverif-progress]`；可通过 `--xverif-progress-interval` 设置正数秒数；
- gate 心跳显示 completed/total、wall elapsed 和当前 nodeid；pytest 默认 `tee-sys`，实时打印同时保留
  捕获证据；
- fixture 在 start、phase 切换和 finish 时立即打印，并在长 phase 中持续心跳；phase 包含
  dependencies、fingerprint、lock、builder、output validation、逐个 probe 和 publish；
- 每次运行持续 flush `.xverif-test-results/<run>/progress.jsonl`，结束原子写入 `timing.json`；
- gate `report.json` 增加 started/finished、wall duration 和 suite duration 聚合；终端结束时输出最慢
  5 项，fixture 最慢项同时显示其最慢 phase；
- Ctrl-C/KeyboardInterrupt 保留 failed timing、清理未发布 staging，并原样传播中断，不误报成功。

## 4. 后续性能优化建议

本提交只解决可观测性和确定性定位，不改变 fixture validation 的“从源重建”语义。若要缩短总时长，
建议另立性能任务，优先评估：

1. differential test engine 是否可以复用正式 engine 的已编译对象，仅增量链接 test-only oracle；
2. AXI VIP 多场景是否能在一次编译产物上复用 elaboration/simv；
3. `large_summary` 是否可把结构生成与 coverage 编译缓存分层，同时保持全 validation 的独立证明；
4. active-trace case 是否可以按共享 RTL/config 分组编译，而不是逐 case 重复启动 VCS；
5. fixture validation 是否可按明确 resource group 有界并行。该项必须先证明 VCS/license、共享产物、
   NPI context 和 publish lock 相互隔离，不能直接将当前串行循环改为无界并行。
