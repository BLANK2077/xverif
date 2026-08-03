# xloc 日志位置还原

xloc 将 UVM/仿真日志中的长文件路径压缩为 `L_XXXXXXXX`，同时保留日志中的源码行号 `L_XXXXXXXX(<line>)`；它可还原文件、统计热点或给日志加注释。

## 何时使用

- 用户给了带 `L_00000001` 的压缩日志。
- 需要还原 loc_id 对应源码位置。
- 需要查看源码上下文或统计高频 loc_id。
- 需要把压缩日志 annotate 成人类可读版本。

## 入口

命令行：

```bash
xloc resolve L_00000001 --map out/sim.log.xloc.jsonl
xloc context L_00000001 --map out/sim.log.xloc.jsonl --line 42 --before 5 --after 5
xloc stats out/sim.log --top 20
xloc annotate out/sim.log --map out/sim.log.xloc.jsonl
```

## 工作流

1. 整段日志先 `stats` 找热点。
2. 检查 `ok/status/analysis_complete/response_truncated`、
   `total_count/returned_count` 和 `diagnostics`；partial 不能当全量。
3. 对关键 loc_id 用 `resolve`。
4. 需要源码证据再用 `context`。
5. 回答引用日志中的 `loc_id(line)` 与 resolve 得到的 file。

默认 XOUT 是 resolve/context/stats/annotate 各自的 token-efficient 领域文本；
只有稳定字段编程、结构化持久化或用户明确要求时，`resolve/context/stats` 使用
`--json`，`annotate` 使用 `--format json`。
`stats --top` 截断会显式设置 `response_truncated` 和
`truncation_scopes=["rows"]`。

## 排障

- map 通常是 `<log>.xloc.jsonl`。
- `resolve/context` 必须有 map。
- map 是 strict UTF-8 JSONL：每行只能包含 string `loc_id/file`，非法 JSON、
  blank line、重复 JSON field、未知/缺失字段、非法类型或重复 loc_id 都使整个
  查询失败。
- 未显式给 map 且 canonical sidecar 不存在时，`stats/annotate` 返回带
  `MAP_UNAVAILABLE`/`LOC_ID_UNRESOLVED` diagnostics 的 partial response；
  不会把 `?` 当文件名。
- loc_id not found：检查是否拿错 sidecar map；不要猜或切换到其它 map。
- 源码文件缺失、非 UTF-8 或 line 越界时，`context` 返回 typed error；可以引用
  已成功 `resolve` 的 file 与日志原始 `loc_id(line)`，但不能声称已取得上下文。
- `annotate --format raw` 只接受 complete resolution；partial 时使用 XOUT/JSON
  查看 diagnostics，不会输出看似完整的 raw artifact。
