# xdebug 总览

xdebug 是 xverif 的 daidir/FSDB 事实查询入口，用 JSON request 查询设计、波形和 combined 因果证据。设计事实来自 `daidir`，波形事实来自 `fsdb`，两者同时存在时可做 active-driver、协议异常和源码 evidence join。

## 何时使用

- 用户给出 `daidir`、`fsdb`、`session_id`、信号路径、时间点、APB/AXI/handshake/debug 现象。
- 需要查某个 signal 的值、变化、driver、load、依赖路径、源码证据、协议 finding。
- 需要把波形异常时间点连接到当前生效 RTL driver：优先用 `trace.active_driver`。
- 需要生成 nWave `signal.rc` 证据视图：用 `nwave.rc.generate`。

不要用 xdebug 做 bit 计算、entry decode 或日志位置还原；分别用 xbit、xentry、xloc。

## CLI 入口

本 skill 只讲原生 CLI。所有 xdebug action 通过完整 `xdebug.v1` envelope 进入：

命令入口：

```bash
xdebug --json -
tools/xdebug --json -
```

默认优先使用 token-efficient `xout`，首要目标是减少 AI/LLM 上下文开销；便于阅读是附带收益。只有脚本需要稳定读取字段、校验 JSON response schema、读取未投影嵌套字段，或用户明确要求 JSON 时，才请求 JSON；机器字段比较必须请求 JSON。XOUT 是 action-specific 领域文本，不反解析为 JSON，也不添加 `XOUT_BEGIN/XOUT_END`。

如果已有 MCP，使用 `xverif-mcp`；没有 MCP 且必须经 LSF 时，把同一 envelope
交给 `tools/xdebug_lsf`。无 LSF 限制时仍使用原生 `tools/xdebug`。

## target 决策

| target | 能力 |
| --- | --- |
| `{"daidir":"simv.daidir"}` | 设计侧：driver/load/query、graph、source、expr、FSM/counter/sequential |
| `{"fsdb":"waves.fsdb"}` | 波形侧：scope、value、list、event、APB、AXI、verify、signal、handshake、anomaly、rc |
| `{"daidir":"simv.daidir","fsdb":"waves.fsdb"}` | combined：波形时间点和 RTL 因果 join |
| `{"session_id":"case_a"}` | 复用已打开 session |

## session 规则

- stateful 查询先 `session.open`，后续用 `target.session_id`。
- session name 必须匹配 `^[A-Za-z][A-Za-z0-9_]{0,63}$`。
- 同名 live session 返回 `SESSION_ID_EXISTS`；同名 stale session 返回 `SESSION_STALE`，需要显式 close/gc 后重开。
- 不要依赖 auto-open 或隐式复用。

## 高频 action

| 意图 | 首选 action | 备注 |
| --- | --- | --- |
| 多信号、多时间点查值 | `list.load` → `value.at(list, times)` | 一个 list 可含多个信号，一次请求可含多个时间点 |
| 单信号查值 | `value.at` | 需要精确 time |
| 找事件/边沿 | `event.find` | 不要先导出全量 changes |
| 验证窗口条件 | `window.verify` | 保留 pass/fail/evidence |
| 查 driver | `trace.driver` | 设计侧 |
| 查当前生效 driver | `trace.active_driver` | 需要 daidir + fsdb + time |
| 从 X 反向追到候选来源 | `trace.x_origin` | 需要 daidir + fsdb + signal + time；best-effort 要保留证据等级 |
| APB/AXI 异常 | `apb.config.load` / `axi.config.load` 后 query/analysis | 先注册信号映射 |
| 生成波形证据 | `nwave.rc.generate` | 见 rc reference |

`value.at` 默认不需要 clock，直接点读指定 time/times；只有需要
clock-sampled context 时才传 `clock`。值默认十六进制并带 `'h` 前缀。
