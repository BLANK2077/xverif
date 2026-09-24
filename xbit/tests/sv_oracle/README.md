# xbit × SystemVerilog 差分测试

xbit 的值语义不靠人工写期望值，而是与**真实仿真器**对比：Python 依据 `cases.yaml` 生成**一个**
SystemVerilog testbench，VCS 编译并仿真**一次**，全部用例的参考值就都拿到了，再逐例与 xbit 比。
不一致就是缺陷（或下文钉住的差异），不会静默通过。

本目录**不使用**仓库的 fixture 缓存：每次运行都重新生成、重新编译、重新仿真。

## 文件

| 文件 | 作用 |
| --- | --- |
| `cases.yaml` | 用例清单：按组（对应 LRM 章节）、`id`、`expr`、可选 `vars`、负例的 `expect_error` |
| `oracle.py` | 用例加载、testbench 生成、编译仿真、结果解析、xbit 对照 |
| `test_sv_oracle.py` | pytest 入口：会话级编译一次 + 逐例参数化断言 + 聚合 100% 对齐断言 |
| `SESSION_RECORD.md` | **实测记录**：VCS 的具体拒绝项与最小复现、位宽语境陷阱、已修缺陷 |

## 运行

```bash
# 需要 VCS（VCS_HOME + license），属沙箱外 host 动作
XVERIF_TEST_EXECUTION_ENV=host pytest --xverif-gate regression --xverif-suite xbit.sv_oracle
```

生成的 `tb_xbit_oracle.sv`、`compile.log`、`run.log`、`oracle.txt` 都在临时工作目录中，失败时
`OracleError` 会把日志尾部带出来。

## 断言口径

每个正例比较 **(位宽, 精确位串)**：

- testbench 为每个用例声明 `logic [W-1:0] c`（`W` 取自 xbit）并打印 `$bits(expr)` 与实际值；
- 值用 `%b` 输出。**`%b` 在 VCS 上按操作数声明位宽补零**，这是本项目唯一可用的"定宽位串"手段；
  `%0*b` / `%*b` 会被 VCS 报 `Illegal format specifier`，`%h` 会补齐到半字节且去前导 0，都不能用；
- 因此位宽回归（例如某运算结果从 8 位变成 32 位）不会藏在值里。

负例不进 testbench，直接断言 xbit 抛出的**错误码**。

## 钉住的差异

差异必须显式登记，且**两侧的值都被钉住**，任何一侧漂移都会失败：

- `VALUE_DIVERGENCES`：值与仿真不同。目前 1 例——无尺寸十进制 `4294967296`，VCS 在 32 位有符号
  上下文中把它置 0（`Warning-[DCTL]`，不符合 LRM），xbit 保留 33 位真值，此处 xbit 才是对的。
- `SELF_WIDTH_DIVERGENCES`：值相同，但 `$bits(<expr>)` 测量的位宽与 xbit 不同。目前 3 例——VCS
  把无尺寸进制字面量（`'hff` 等）按语境扩成 32 位，而 LRM 5.7.1 规定字面量自身宽度为数字位数；
  仿真器在这里不能作为位宽参考，值仍然必须一致。
- `UNSUPPORTED_BY_SYSTEMVERILOG`：xbit 比语言更宽松之处（链式 part-select `X[a:b][c:d]` 在 SV 中
  非法），由 xbit 自身的断言覆盖。

`test_positive_suite_is_one_hundred_percent_aligned` 汇总判定：每个正例要么与仿真完全一致，
要么在上述表中登记。

## 加用例

在 `cases.yaml` 对应组里加一条，`expr` 用 SystemVerilog 源码写法，并尽量在组头标注 LRM 章节。
生成器会处理 SV 侧的两个限制（见 `SESSION_RECORD.md`）：

- **字面量不能被位选**（`32'hdead_beef[15:8]` 非法）：生成器把被选的字面量自动绑定到
  `localparam` 再选，无需在用例里改写；
- **负数字面量的写法**：用例里写 `-8'sd1`（不要写 `8'sd-1`，VCS 拒绝），生成器统一用
  `<w>'b<bits>` 初始化变量与绑定。

新增用例若与仿真不一致，测试会失败并给出两侧的值，再决定是修 xbit 还是登记为差异。
