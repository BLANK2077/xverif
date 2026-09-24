# xbit × SystemVerilog 差分测试：实施记录与实测结论

本文记录 xbit 测试迁移到"Python 生成 SV → VCS 仿真 → 与 xbit 对比"过程中的**实测事实**，
尤其是 VCS 与 SV LRM 的具体行为差异。这些结论只能靠实测得到，逐条附最小复现，避免后续
重复踩坑。

状态：**已落地**——用例集、生成器、测试与 catalog suite 全部完成，门禁通过。

---

## 1. 目标与结构

- 目标：xbit 的值语义不再由人工硬编码期望值保证，而是与**真实仿真器**对比；用例范围按 SV LRM 扩充。
- 结构：`xbit/tests/sv_oracle/{cases.yaml, oracle.py, test_sv_oracle.py}`。
- **不使用** testinfra fixture 缓存：每次运行都重新生成 SV、重新编译、重新仿真。
- 一次生成+一次编译+一次仿真覆盖全部用例（不逐例编译）。

### 已实测确认可行的输出口径

```systemverilog
logic [W-1:0] c;
initial begin
  c = (expr);                                  // 单次求值
  if ($bits((expr)) != W) $display("WIDTH-MISMATCH ...");
  $display("<label>\t%0d\t%b", W, c);          // W 由 xbit 提供
end
```

- **`%b` 在 VCS 上按操作数"声明位宽"精确补零**：`logic [4:0] a = 5'd1` 打印 `00001`（5 字符）。
  这是本项目能找到的、唯一可用的"定宽位串"手段。
- **`%0*b` / `%*b` 不可用**：VCS 报 `Error-[IFSFDT] Illegal format specifier`（'%0*' is not a
  valid format specification for display task）。LRM 的动态宽度修饰符在本版本 VCS 未实现。
- `%h` 不可用于比较：对非 4 倍位宽会补齐到半字节，且去前导 0，无法判定位宽。
- 比较口径统一为 **(width, 精确位串)**；xbit 侧取 `to_bin_digits()`（去掉 `to_bin()` 的 `_` 分组）。

---

## 2. VCS 拒绝、xbit 接受的写法（必须避开或绑定）

| 写法 | VCS 结果 | 说明 | 处置 |
| --- | --- | --- | --- |
| `32'hdead_beef[15:8]` | `Error-[SE]` token is `[` | **字面量不能被位选**（不是数据对象） | 生成器把被选的字面量绑定到 `localparam` 再选 |
| `(32'hdead_beef)[15:8]` | 同样 `Error-[SE]` | 加括号**不能**让字面量可位选 | 同上，只能绑定 |
| `lit[15:8][3:0]` | `Error-[SE]` token is `[` | **链式 part-select 在 SV 中非法** | 从 oracle 用例移除，列入有意差异 |
| `8'sd-1`（负号在数字段内） | `Error-[UC]` The character `-` is illegal | VCS 不接受这种字面量 | 改用 `-8'sd1`；变量/绑定统一用**位串字面量** `<w>'b<bin>` 初始化 |
| `(8'sd-1)` | `Error-[UC]` | 括号使负号成为**一元运算符**，与"单字面量 token"不是同一个表达式 | 裸字面量不加括号 |
| `- -8'sd5` | `Error-[SE]` token is `-` | 双重一元负号被拒 | 移除该用例 |
| `16'hdead_beef` | `Warning-[TMBIN]` + 实际按 **32 位**取值 | VCS 对"位数超出声明宽度"的字面量**不截断**，与 LRM 不符 | 移除该用例（VCS 与 LRM 本身不一致，无法作为参考） |
| `'hff`（无尺寸进制字面量） | 可编译，`$bits` 报 32 | 见第 3 节：VCS 在赋值/`$bits` 语境把无尺寸字面量扩展为 32 位 | 见第 3 节处置 |

### 实测可用的等价写法

- `localparam logic [31:0] lit = 32'hdead_beef;` 然后 `lit[15:8]` → 正确。
- `{8'ha5, 8'h5a}[11:4]` → 合法（concat 结果可位选），实测得 `aa`，与 xbit 一致。
- `-8'sd1`、`-8'sd128` 作为 `localparam` 初值 → 合法。
- 变量与绑定统一用 `<width>'b<bits>`（如 `8'b11111111`）→ 同时避开"负数一元运算"与"无尺寸扩展"两类陷阱。

---

## 3. 位宽分歧：xbit 与 VCS（宽度守卫发现）

宽度守卫（`$bits(expr) != xbit_width` 即报 `WIDTH-MISMATCH`）一次性抓出 5 例：

| 用例 | 表达式 | VCS `$bits` | xbit width | 判断 |
| --- | --- | --- | --- | --- |
| `lit_unsized_hex` | `'hff` | 32 | 8 | VCS 把无尺寸进制字面量扩展为 32 位（赋值语境） |
| `lit_unsized_bin` | `'b1010` | 32 | 4 | 同上 |
| `lit_unsized_oct` | `'o777` | 32 | 9 | 同上 |
| `lit_unsized_dec_big` | `4294967296` | 32 | 33 | VCS `Warning-[DCTL]`：超过 32 位有符号常量，改用 0 |
| `tr_branch_width_unify` | `1'b1 ? 4'hf : 8'h0f` | 8 | 4 | **真缺陷候选**：LRM 11.4.11/11.6 规定条件表达式两分支统一到较宽位宽（8），xbit 取 4 |

**重要陷阱**：`$bits(<表达式>)` 在 VCS 中会受**赋值/使用语境**影响（语境定宽），因此"`$bits`
不等于 xbit 位宽"不能直接判定为 xbit 错误。构建 TB 时曾把表达式写成 `localparam logic [W-1:0] c = (expr);`
而 W 取自 xbit，VCS 会把 RHS 扩展到 W，导致 `$bits` 恒等于 W——这个反例说明**必须让 W 来自实际测量，
而不是来自 xbit**，否则守卫形同虚设。

处置方向：
- 位宽守卫改为**记录实测宽度**，与 xbit 宽度逐例对比，分歧进入差异表并要求显式声明；
- 无尺寸字面量（`'hff` 等）的位宽分歧属 VCS 语境扩展，需在差异表中标注为"VCS 语境定宽，不可作参考"；
- `tr_branch_width_unify` 需要按 LRM 判定后**修 xbit**（分支位宽统一）。

---

## 4. 已修的 xbit 缺陷

**嵌套 concat/repeat 无法解析**（真实缺陷，由用例集暴露）：

- `{2{4'hA, 4'h5}}`、`{2{{2'b10}, {2'b01}}}` → `ParseError: unexpected token`
- 根因：`Parser.parse_braces` 只能处理"重复体是单个表达式"，且 `{N{...}}` 与 `{a,b}` 的消解
  没有回溯，`{{2'b10}, {2'b01}}` 会被误判为重复形式。
- 修法（`xbit/src/xbit/eval.py`）：拆出 `parse_brace_body`，用**投机解析 + 回退**消解歧义——
  先按 concat 读，若未走到匹配 `}` 则回到起点按 `count{body}` 读；重复体递归调用
  `parse_brace_body`，因此支持 `{2{a,b}}` 与 `{2{{...},{...}}}`。
- 验证：`{2{4'hA, 4'h5}}` → 16 位 `1010010110100101`；`{2{{2'b10}, {2'b01}}}` → 8 位 `10011001`；
  原有 `{2{4'hA}}`、`{2'b10, 2'b01}`、`{1'b1, 8'hff}` 等行为不变。

## 5. 待判定：xbit 比 SV 更宽松（有意差异候选）

| 用例 | 表达式 | VCS | xbit | 说明 |
| --- | --- | --- | --- | --- |
| 链式 part-select | `32'hdead_beef[15:8][3:0]` | 语法非法 | 接受，得 4 位 `1110` | SV 不允许对 select 结果再 part-select；xbit 更宽松。需决定：保留为文档化差异，还是收紧为报错 |

---

## 5b. 本轮修的 xbit 缺陷汇总（3 处）

| 缺陷 | 证据 | 修法 |
| --- | --- | --- |
| 嵌套 concat/repeat 无法解析 | `{2{4'hA, 4'h5}}`、`{2{{2'b10}, {2'b01}}}` → ParseError | `eval.py`：`parse_brace_body` 投机解析 + 回退 |
| `?` 被当作 `x` | `4'b10??` xbit 给 `10xx`，VCS 给 `10zz` | `literal.py`：`?` → `z`（sv-bc 权威：字面量中 `?` 就是 `z`） |
| 条件表达式分支位宽未统一 | `1'b1 ? 4'hf : 8'h0f` xbit 4 位，VCS 8 位 | `eval.py`：两分支先统一到较宽位宽（LRM 11.4.11 / 11.6） |

## 6. 当前进度快照

- 用例集：**171**（正例 159、负例 12），分组覆盖 literals / bitwise / arithmetic / compare /
  shift / concat_repeat / slice_index / ternary / logical / unary / variables / negative /
  four_state_literal，每组标注 LRM 章节。
- 生成器：单 TB、单次编译、单次仿真，按 `xbit_<n>` 位置标签映射回用例 id（重命名不会错配）。
- 结果：**163 passed**（单次编译+仿真约 9 秒）；159 正例中 **155 与仿真完全一致**，
  4 例为钉住的差异（1 例值差异 + 3 例自定位宽测量差异，见第 3 节）。
- 迁移：`xbit/tests/test_xbit.py` 从 32 项降为 **11 项结构性契约测试**（响应契约、XOUT 形态、
  agent stdio、错误来源互斥、越界切片、除零、2-state 拒绝 X/Z、重复变量拒绝）；值语义由 oracle 承担。
- catalog：新增 suite `xbit.sv_oracle`（path `xbit/tests/sv_oracle`，capabilities
  `[child_process]`，进 regression/nightly，不进 fast）；最长前缀匹配使 `xbit.unit` 不再包含 oracle 测试。
- 反向验证：向 `ops.py` 的 `+` 注入 `+1` 后 oracle **15 例失败**；`git checkout` 回滚后 163 passed。
- 版本：`xbit/pyproject.toml` → **1.0.0**；顶层 README 的 Python 口径由错误的"3.6+"改为 3.10+。

## 7. 复跑方式

```bash
# 生成+编译+仿真+对比（需要 VCS，属沙箱外 host 动作）
PYTHONPATH=xbit/src python - <<'EOF'
import sys, pathlib
sys.path.insert(0, "xbit/tests/sv_oracle")
import oracle
cases = oracle.attach_xbit_results(oracle.load_cases())
res = oracle.simulate(cases, pathlib.Path("tmp/xbit-sv-oracle"))
xb = oracle.xbit_results(cases)
bad = [c for c in oracle.positive_cases(cases)
       if (res[c.id].width, res[c.id].bits) != xb[c.id]]
print("不一致:", len(bad), [c.id for c in bad])
EOF
```

生成的 TB、`compile.log`、`run.log`、`oracle.txt` 都留在 `tmp/xbit-sv-oracle/` 便于诊断。
