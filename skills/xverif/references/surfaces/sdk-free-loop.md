# SDK-free Loop Surface

只有没有 MCP SDK 或必须脚本化/托管 LSF stdio-loop 时使用。该 surface 使用 `method/params` JSONL，所有 query/doctor/close/kill method 的 session 参数名统一且只允许 `session_id`；旧 `session`/`name` 字段严格拒绝。原生 xdebug envelope 仍在 `target.session_id` 中选择 session，不与 loop params 混用。

协议、readiness、UDS 和 LSF 细节统一转到 `xverif-admin`；普通 action 语义仍回到对应 capability。

`cov.query.params` 只接受 `session_id/action/args/output_format`；coverage limits 与
artifact output 必须继续位于 action 内层 `args.limits` / `args.output`，不能作为
loop params 或 native top-level 字段传入。

`debug.session.open` 与 `cov.session.open` 同样可传 `run_manifest`；其校验语义与 MCP
session-open 完全相同，不会因 SDK-free surface 而跳过 provenance gate。
