# xsva

SystemVerilog Assertion 语义编译工具。

把 SVA 从文本语法编译为结构化 IR（Surface → Sequence → Timeline），所有解释从 IR 生成。
所有 one-shot 命令默认输出 token-efficient XOUT；`explain --markdown` 可显式生成
面向用户的英文语义摘要。结构化响应保留 `match_paths` / `obligations`、范围
delay、range suffix、repeat 和高级 sequence 的 semantic notes；若路径枚举受到
`max_paths` 限制，响应会同时发布精确候选总数和明确的不完整状态。

## 命令

```bash
xsva list    --file <file>                       # 默认 XOUT
xsva scan    --file <file>                       # 默认 XOUT
xsva lint    --file <file> [--property <name>]   # 默认 XOUT
xsva explain --file <file> --property <name>     # 默认 XOUT
xsva parse   --file <file> --property <name> --emit surface-ir|sequence-ir|timeline-ir
```

五个命令都支持显式 `--json`。`explain` 额外支持与 `--json` 互斥的
`--markdown`。

默认文本恢复各命令原有的领域格式：`list` 列出 property/assertion，`scan` 列出
计数，`lint` 列出 diagnostics，`explain` 生成 timeline 解释，`parse` 输出所选 IR。

```text
Properties:
  p_req_ack
Assertions:
  a_req_ack: assert property (p_req_ack)
```

需要稳定字段编程、schema 校验、结构化持久化或用户明确要求时使用 `--json`；
普通 AI 分析默认保留 XOUT。

## 精度与完整性合同

每个 JSON/XOUT 成功或错误响应都包含 `lowering_status`、`precision`、
`diagnostics` 与 `completeness`。有限范围 delay 的候选总数由 lowering 精确计算；
达到 `max_paths` 后发布 `partial`、`XSVA-L001`、精确的
`total_path_count`/`returned_path_count`，以及
`truncation_scopes=["analysis.match_paths"]`，不会把部分枚举伪装成完整结果。

Sequence IR 使用单一 canonical 结构：property 关系存于 `implication`，两侧分别
存于 `antecedent` 与 `consequent`。Timeline IR 使用 `trigger`、`match_paths` 和
显式 `disable_obligation`；`match_paths[].obligations` 只引用同一 Timeline IR 中
`obligations[].id` 的 canonical ID。每个 obligation 通过 `signals_to_query` 发布去重后的
canonical 波形依赖，保留完整层次路径和固定 bit/part select；sampled function 的表达式
参数会递归提取依赖。缺失参数、未闭合调用或无效 `$past` depth 返回 `XSVA-W011` 并将
lowering 标为 `partial`，不会泄漏内部索引异常。

## 示例

```bash
python -m xsva list --file tests/golden_ir/simple_impl/input.sva
python -m xsva explain --file tests/golden_ir/simple_impl/input.sva --property p_simple --markdown
python -m xsva parse --file tests/golden_ir/simple_impl/input.sva --property p_simple --emit timeline-ir --json
```

范围和高级语法示例：

```systemverilog
property p_first;
  req |-> first_match(##[1:4] ack) ##1 done;
endproperty
```

解释输出会说明：`ack must be the first match at cycle +1 to +4; done must be true 1 clk after that first ack.`

```systemverilog
property p_intersect;
  req |-> (a ##1 b) intersect (c ##1 d);
endproperty
```

解释输出会按 `Sequence 1`、`Sequence 2` 和 `Relation` 分别说明两个 sequence 的内部时序以及二者必须同时开始、同时结束。

## 测试

```bash
pytest --xverif-gate fast --xverif-suite xsva.core
pytest --xverif-gate regression --xverif-suite xsva.cli
pytest --xverif-gate nightly --xverif-suite xsva.vcs
```
