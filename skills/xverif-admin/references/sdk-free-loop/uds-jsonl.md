# SDK-free UDS JSONL 协议

启动 server：

```bash
XVERIF_LOOP_SOCKET=<repo>/tmp/xverif-loop.sock tools/xverif-loop-server
```

发送单个请求：

```bash
tools/xverif-loop-client --socket <repo>/tmp/xverif-loop.sock --json \
  '{"id":"1","method":"debug.session.open","params":{"name":"s0","fsdb":"waves.fsdb","run_manifest":"run-manifest.json"}}'
```

也可从 stdin 发送 JSONL。

## 请求格式

```json
{"id":"1","method":"debug.query","params":{"session_id":"s0","action":"value.at","args":{"signal":"top.data","time":"10ns","clock":"top.clk"}}}
```

成功：

```json
{"id":"1","ok":true,"result":{}}
```

失败：

```json
{"id":"1","ok":false,"error":{"code":"SESSION_LOST","message":"..."}}
```

## 方法

- `server.ping`
- `server.shutdown`
- `debug.session.open`
- `debug.session.list`
- `debug.session.doctor`
- `debug.session.close`
- `debug.session.kill`
- `debug.session.gc`
- `debug.query`
- `cov.session.open`
- `cov.session.list`
- `cov.session.doctor`
- `cov.session.close`
- `cov.session.kill`
- `cov.session.gc`
- `cov.query`

`debug.query` 会把 `action/args/limits/output_format` 转给当前 managed session；`cov.query` 会把 `action/args/output_format` 转给 coverage backend。两者都要求并只接受 canonical `session_id`，固定 target 为该 managed session；旧 `session`/`name` 字段作为未知参数拒绝。xdebug action 专用输出配置只放在 schema 允许的 `args.output`。不要用 query 发送 lifecycle raw request（coverage 的 `session.status` 使用 `cov.session.doctor`）。list 接受 `include_tombstones`/`verbose`，doctor 接受精确 `session_id` 和 `verbose`，close/kill 只接受精确 `session_id`，gc 接受 `verbose`；kill 的 `all` 明确拒绝。

脚本化拉起 server 时，Unix socket 文件在 `bind()` 后已经存在，但只有 `listen()` 成功后才真正可连接。编排程序必须等待明确的 server ready 信号或一次成功的 `server.ping`；不要把路径存在、固定 sleep 或静默 connect 重试当作 readiness 合同。

## 环境变量

- `XVERIF_LOOP_SOCKET`：socket 路径。
- `XVERIF_LOOP_BACKEND=direct|lsf`：启动模式。
- `XVERIF_LOOP_LOG_DIR`：日志根目录。
- `XVERIF_LOOP_STARTUP_TIMEOUT_SEC`：open timeout。
- `XVERIF_LOOP_REQUEST_TIMEOUT_SEC`：query timeout。
- `XVERIF_LOOP_CLOSE_TIMEOUT_SEC`：close timeout。
