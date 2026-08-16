# xsva SVA IR 解释

xsva 把 SystemVerilog Assertion 编译为 Surface IR、Sequence IR、Timeline IR，再基于 IR 生成确定性解释。不要直接让 LLM 自由解释 SVA temporal semantics。

## 入口

命令行：

```bash
xsva list --file input.sva
xsva parse --file input.sva --property p_name --emit timeline-ir
xsva explain --file input.sva --property p_name
xsva explain --file input.sva --property p_name --markdown
```

## 工作流

1. 先 `list` 确认 property/assertion 名称。
2. 对目标 property 取 timeline IR。
3. 优先基于 `semantic_notes` 解释用户语义。
4. local variable 看 captures 和 depends_on_captures。
5. 波形取证只使用 obligation 的 `signals_to_query` canonical 依赖；它保留层次路径与
   固定 bit/part select，并包含 sampled function 参数内递归提取的信号。出现
   `XSVA-W011` 时依赖不完整，不能自行猜补缺失信号。
6. `first_match`、`throughout`、`intersect`、`within`、`[*]`、`[->]`、`[=]` 等高级 sequence 必须依赖 IR/semantic_notes。
7. JSON/XOUT 响应先检查 `completeness`：路径返回数小于总数或
   `path_enumeration_complete=false` 时，`response_truncated=true` 且
   `truncation_scopes=["analysis.match_paths"]`；此时不能把返回路径当作全集。

XSVA 的 XOUT 保留 command-specific 领域文本，`explain` 使用 timeline 解释；它不
强制统一 header，也不是 JSON 的可逆编码。需要读取 `completeness` 等字段时请求 JSON。

## 排障和维护

- 不支持的 SVA 构造应给 conservative diagnostic，不要补语义。
- list/scan/lint/explain/parse 的成功与错误响应都使用 action-specific 封闭合同；
  未声明字段或互相矛盾的完整性字段属于内部合同错误，不做客户端兼容。
- 修改 parser/lowering 时先加失败语义测试，再修实现，最后更新 golden IR。
- 回归入口在仓库根目录运行 `pytest --xverif-gate fast --xverif-suite xsva.core`；VCS 语义缓存消费使用 nightly 的 `xsva.vcs` suite。
