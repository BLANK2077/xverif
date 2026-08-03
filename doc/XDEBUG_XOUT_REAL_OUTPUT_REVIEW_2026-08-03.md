# XDEBUG Native XOUT 真实输出审查（重建分支）

# 阶段：final

- runtime action 数：73
- primary 成功数：73
- 捕获调用总数：178
- 布局 review 失败数：0
- 完整性：每个 body 均按原始 stdout bytes 计数并计算 SHA-256。

## 73 个 primary action 最终逐项 review

评审标准：输出只保留 action 结论所需内容；同一事实不重复；所有 LogicValue 默认紧凑十六进制，显式进制服从请求，仅 X/Z 十六进制补充逐 bit 诊断；受保护的 APB/AXI/Stream query 与 value.at 专用布局必须保留。

| action | runtime | 必要且不重复 | 数值格式 | renderer | 最终 |
|---|---:|---:|---:|---|---:|
| `actions` | PASS | PASS | N/A | handler override | PASS |
| `apb.config.list` | PASS | PASS | N/A | 基类 | PASS |
| `apb.config.load` | PASS | PASS | N/A | 基类 | PASS |
| `apb.query` | PASS | PASS | PASS | handler override | PASS |
| `apb.statistics` | PASS | PASS | PASS | handler override | PASS |
| `apb.transaction.cursor` | PASS | PASS | PASS | 基类 | PASS |
| `apb.transfer_window` | PASS | PASS | PASS | 基类 | PASS |
| `axi.analysis` | PASS | PASS | PASS | 基类 | PASS |
| `axi.channel_stall` | PASS | PASS | N/A | 基类 | PASS |
| `axi.config.list` | PASS | PASS | N/A | 基类 | PASS |
| `axi.config.load` | PASS | PASS | N/A | 基类 | PASS |
| `axi.export` | PASS | PASS | PASS | 基类 | PASS |
| `axi.latency_outlier` | PASS | PASS | PASS | 基类 | PASS |
| `axi.outstanding_timeline` | PASS | PASS | N/A | 基类 | PASS |
| `axi.query` | PASS | PASS | PASS | handler override | PASS |
| `axi.request_response_pair` | PASS | PASS | PASS | 基类 | PASS |
| `axi.statistics` | PASS | PASS | PASS | handler override | PASS |
| `axi.transaction.cursor` | PASS | PASS | PASS | 基类 | PASS |
| `batch` | PASS | PASS | N/A | 基类 | PASS |
| `counter.statistics` | PASS | PASS | PASS | 基类 | PASS |
| `event.config.list` | PASS | PASS | N/A | 基类 | PASS |
| `event.config.load` | PASS | PASS | N/A | 基类 | PASS |
| `event.export` | PASS | PASS | PASS | 基类 | PASS |
| `event.find` | PASS | PASS | PASS | 基类 | PASS |
| `expr.eval_at` | PASS | PASS | PASS | 基类 | PASS |
| `expr.normalize` | PASS | PASS | N/A | 基类 | PASS |
| `list.add` | PASS | PASS | N/A | 基类 | PASS |
| `list.create` | PASS | PASS | N/A | 基类 | PASS |
| `list.delete` | PASS | PASS | N/A | 基类 | PASS |
| `list.export` | PASS | PASS | N/A | 基类 | PASS |
| `list.first_change` | PASS | PASS | PASS | 基类 | PASS |
| `list.load` | PASS | PASS | N/A | 基类 | PASS |
| `list.show` | PASS | PASS | N/A | 基类 | PASS |
| `list.validate` | PASS | PASS | N/A | 基类 | PASS |
| `nwave.rc.generate` | PASS | PASS | N/A | 基类 | PASS |
| `protocol.handshake.inspect` | PASS | PASS | PASS | 基类 | PASS |
| `schema` | PASS | PASS | N/A | handler override | PASS |
| `scope.list` | PASS | PASS | N/A | handler override | PASS |
| `scope.roots` | PASS | PASS | N/A | handler override | PASS |
| `session.close` | PASS | PASS | N/A | 基类 | PASS |
| `session.doctor` | PASS | PASS | N/A | 基类 | PASS |
| `session.gc` | PASS | PASS | N/A | 基类 | PASS |
| `session.kill` | PASS | PASS | N/A | 基类 | PASS |
| `session.list` | PASS | PASS | N/A | 基类 | PASS |
| `session.open` | PASS | PASS | N/A | 基类 | PASS |
| `signal.anomaly.inspect` | PASS | PASS | PASS | 基类 | PASS |
| `signal.canonicalize` | PASS | PASS | N/A | 基类 | PASS |
| `signal.changes` | PASS | PASS | PASS | 基类 | PASS |
| `signal.resolve` | PASS | PASS | N/A | 基类 | PASS |
| `signal.sampled_pulse.inspect` | PASS | PASS | PASS | 基类 | PASS |
| `signal.stability` | PASS | PASS | PASS | 基类 | PASS |
| `signal.statistics` | PASS | PASS | PASS | 基类 | PASS |
| `signal.xz_verify` | PASS | PASS | PASS | 基类 | PASS |
| `stream.config.get` | PASS | PASS | N/A | 基类 | PASS |
| `stream.config.list` | PASS | PASS | N/A | 基类 | PASS |
| `stream.config.load` | PASS | PASS | N/A | 基类 | PASS |
| `stream.describe` | PASS | PASS | N/A | 基类 | PASS |
| `stream.export` | PASS | PASS | PASS | 基类 | PASS |
| `stream.query` | PASS | PASS | PASS | handler override | PASS |
| `stream.validate` | PASS | PASS | N/A | 基类 | PASS |
| `trace.active_driver` | PASS | PASS | N/A | handler override | PASS |
| `trace.active_driver_chain` | PASS | PASS | PASS | handler override | PASS |
| `trace.driver` | PASS | PASS | N/A | handler override | PASS |
| `trace.load` | PASS | PASS | N/A | handler override | PASS |
| `trace.x_origin` | PASS | PASS | PASS | handler override | PASS |
| `value.at` | PASS | PASS | PASS | handler override | PASS |
| `verify.conditions` | PASS | PASS | PASS | 基类 | PASS |
| `waveform.cursor.delete` | PASS | PASS | N/A | 基类 | PASS |
| `waveform.cursor.get` | PASS | PASS | N/A | 基类 | PASS |
| `waveform.cursor.list` | PASS | PASS | N/A | 基类 | PASS |
| `waveform.cursor.set` | PASS | PASS | N/A | 基类 | PASS |
| `waveform.cursor.use` | PASS | PASS | N/A | 基类 | PASS |
| `window.verify` | PASS | PASS | PASS | 基类 | PASS |

## 001. `actions` / `primary`

- returncode: 0
- elapsed_ms: 68
- bytes: 1495
- sha256: `b2d833867abea59c0221b6f3817434c2aa1b080053c80aea37df17ed58c5a00f`
- request: `{"action": "actions", "api_version": "xdebug.v1", "args": {}}`

<!-- XOUT_BODY phase=final action=actions role=primary bytes=1495 sha256=b2d833867abea59c0221b6f3817434c2aa1b080053c80aea37df17ed58c5a00f -->
```xout
@xdebug.actions.v1
summary:
  action_count      : 73
  total_action_count: 73
  verbose           : false
  filtered          : false

builtin:
  actions
  batch
  schema

session:
  session.close
  session.doctor
  session.gc
  session.kill
  session.list
  session.open

design:
  expr.normalize
  signal.canonicalize
  signal.resolve
  trace.driver
  trace.load

waveform:
  apb.config.list
  apb.config.load
  apb.query
  apb.statistics
  apb.transaction.cursor
  apb.transfer_window
  axi.analysis
  axi.channel_stall
  axi.config.list
  axi.config.load
  axi.export
  axi.latency_outlier
  axi.outstanding_timeline
  axi.query
  axi.request_response_pair
  axi.statistics
  axi.transaction.cursor
  counter.statistics
  event.config.list
  event.config.load
  event.export
  event.find
  expr.eval_at
  list.add
  list.create
  list.delete
  list.export
  list.first_change
  list.load
  list.show
  list.validate
  nwave.rc.generate
  protocol.handshake.inspect
  scope.list
  scope.roots
  signal.anomaly.inspect
  signal.changes
  signal.sampled_pulse.inspect
  signal.stability
  signal.statistics
  signal.xz_verify
  stream.config.get
  stream.config.list
  stream.config.load
  stream.describe
  stream.export
  stream.query
  stream.validate
  value.at
  verify.conditions
  waveform.cursor.delete
  waveform.cursor.get
  waveform.cursor.list
  waveform.cursor.set
  waveform.cursor.use
  window.verify

combined:
  trace.active_driver
  trace.active_driver_chain
  trace.x_origin
```

## 002. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 245
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_p"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.apb_vip/versions/5b0d1be836520bd8421bb4193d12949c5ba4c3098cc94bd1dede3d5a81fb4709-prepare-7hdsu4cf/resources/out/regression/test/apb_vip_test/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 003. `apb.config.load` / `setup`

- returncode: 0
- elapsed_ms: 119
- bytes: 712
- sha256: `527d57262376f9fdc430dbcb72e2e99f4e354eebe020c6bed988c7fa4fd74fc3`
- request: `{"action": "apb.config.load", "api_version": "xdebug.v1", "args": {"config": {"clock": "apb_vip_fixture_top.clk", "edge": "posedge", "paddr": "apb_vip_fixture_top.apb_if.paddr", "penable": "apb_vip_fixture_top.apb_if.penable", "prdata": "apb_vip_fixture_top.apb_if.prdata[0]", "pready": "apb_vip_fixture_top.apb_if.pready[0]", "psel": "apb_vip_fixture_top.apb_if.psel[0]", "pslverr": "apb_vip_fixture_top.apb_if.pslverr[0]", "pwdata": "apb_vip_fixture_top.apb_if.pwdata", "pwrite": "apb_vip_fixture_top.apb_if.pwrite", "reset": {"polarity": "active_low", "signal": "apb_vip_fixture_top.rst_n"}}, "name": "apb0"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.config.load role=setup bytes=712 sha256=527d57262376f9fdc430dbcb72e2e99f4e354eebe020c6bed988c7fa4fd74fc3 -->
```xout
@xdebug.apb.config.load.v1
summary:
  name  : apb0
  status: loaded

config:
  name         : apb0
  sampling_mode: clock_edge
  clock        : apb_vip_fixture_top.clk
  edge         : posedge
  paddr        : apb_vip_fixture_top.apb_if.paddr
  psel         : apb_vip_fixture_top.apb_if.psel[0]
  penable      : apb_vip_fixture_top.apb_if.penable
  pwrite       : apb_vip_fixture_top.apb_if.pwrite
  pwdata       : apb_vip_fixture_top.apb_if.pwdata
  prdata       : apb_vip_fixture_top.apb_if.prdata[0]
  sample_point : before
  pready       : apb_vip_fixture_top.apb_if.pready[0]
  pslverr      : apb_vip_fixture_top.apb_if.pslverr[0]

config.reset:
  signal  : apb_vip_fixture_top.rst_n
  polarity: active_low
```

## 004. `apb.config.list` / `primary`

- returncode: 0
- elapsed_ms: 122
- bytes: 711
- sha256: `866fdce04303810e6b94e97a8df0e0d64b89ec91f3b4be6907558bbcae2ae42a`
- request: `{"action": "apb.config.list", "api_version": "xdebug.v1", "args": {"name": "apb0"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.config.list role=primary bytes=711 sha256=866fdce04303810e6b94e97a8df0e0d64b89ec91f3b4be6907558bbcae2ae42a -->
```xout
@xdebug.apb.config.list.v1
summary:
  name  : apb0
  status: found

config:
  name         : apb0
  sampling_mode: clock_edge
  clock        : apb_vip_fixture_top.clk
  edge         : posedge
  paddr        : apb_vip_fixture_top.apb_if.paddr
  psel         : apb_vip_fixture_top.apb_if.psel[0]
  penable      : apb_vip_fixture_top.apb_if.penable
  pwrite       : apb_vip_fixture_top.apb_if.pwrite
  pwdata       : apb_vip_fixture_top.apb_if.pwdata
  prdata       : apb_vip_fixture_top.apb_if.prdata[0]
  sample_point : before
  pready       : apb_vip_fixture_top.apb_if.pready[0]
  pslverr      : apb_vip_fixture_top.apb_if.pslverr[0]

config.reset:
  signal  : apb_vip_fixture_top.rst_n
  polarity: active_low
```

## 005. `apb.config.load` / `primary`

- returncode: 0
- elapsed_ms: 107
- bytes: 726
- sha256: `5da1cf98401ccbe230106c251cbd97f14c5f30d1f3063afb509dae113b30aec1`
- request: `{"action": "apb.config.load", "api_version": "xdebug.v1", "args": {"config": {"clock": "apb_vip_fixture_top.clk", "edge": "posedge", "paddr": "apb_vip_fixture_top.apb_if.paddr", "penable": "apb_vip_fixture_top.apb_if.penable", "prdata": "apb_vip_fixture_top.apb_if.prdata[0]", "pready": "apb_vip_fixture_top.apb_if.pready[0]", "psel": "apb_vip_fixture_top.apb_if.psel[0]", "pslverr": "apb_vip_fixture_top.apb_if.pslverr[0]", "pwdata": "apb_vip_fixture_top.apb_if.pwdata", "pwrite": "apb_vip_fixture_top.apb_if.pwrite", "reset": {"polarity": "active_low", "signal": "apb_vip_fixture_top.rst_n"}}, "name": "apb_primary"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.config.load role=primary bytes=726 sha256=5da1cf98401ccbe230106c251cbd97f14c5f30d1f3063afb509dae113b30aec1 -->
```xout
@xdebug.apb.config.load.v1
summary:
  name  : apb_primary
  status: loaded

config:
  name         : apb_primary
  sampling_mode: clock_edge
  clock        : apb_vip_fixture_top.clk
  edge         : posedge
  paddr        : apb_vip_fixture_top.apb_if.paddr
  psel         : apb_vip_fixture_top.apb_if.psel[0]
  penable      : apb_vip_fixture_top.apb_if.penable
  pwrite       : apb_vip_fixture_top.apb_if.pwrite
  pwdata       : apb_vip_fixture_top.apb_if.pwdata
  prdata       : apb_vip_fixture_top.apb_if.prdata[0]
  sample_point : before
  pready       : apb_vip_fixture_top.apb_if.pready[0]
  pslverr      : apb_vip_fixture_top.apb_if.pslverr[0]

config.reset:
  signal  : apb_vip_fixture_top.rst_n
  polarity: active_low
```

## 006. `apb.query` / `primary`

- returncode: 0
- elapsed_ms: 185
- bytes: 549
- sha256: `782dd84ec43b51afaf1b376b84ab562eadd46053172d956a16fa0664530d5bc9`
- request: `{"action": "apb.query", "api_version": "xdebug.v1", "args": {"name": "apb0", "query": {"line_limit": 2}}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.query role=primary bytes=549 sha256=782dd84ec43b51afaf1b376b84ab562eadd46053172d956a16fa0664530d5bc9 -->
```xout
@xdebug.apb.query.v1
summary:
  name              : apb0
  direction         : all
  query_mode        : list
  scan_complete     : true
  analysis_complete : true
  response_truncated: true
  total_count       : 10
  returned_count    : 2

truncation_scopes:
  response_transactions
  value_width_complete: true
  width_diagnostics   : [empty]

filter:
  direction: all

transactions:
  time   addr          data          is_write  has_error
  125ns  32'h00000000  32'h11223344  true      false
  165ns  32'h00000004  32'h55667788  true      false
```

## 007. `apb.statistics` / `primary`

- returncode: 0
- elapsed_ms: 149
- bytes: 725
- sha256: `43e0861890315acdb7b2f2ec079254aae44f0366334ff89f39ba1d88af419ee7`
- request: `{"action": "apb.statistics", "api_version": "xdebug.v1", "args": {"name": "apb0"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.statistics role=primary bytes=725 sha256=43e0861890315acdb7b2f2ec079254aae44f0366334ff89f39ba1d88af419ee7 -->
```xout
@xdebug.apb.statistics.v1
summary:
  name                        : apb0
  scanned_transaction_count   : 10
  matched_transaction_count   : 10
  matched_read_count          : 5
  matched_write_count         : 5
  unresolved_transaction_count: 0
  filter_applied              : false
  analysis_quality            : complete
  full_scan_count             : 1
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 10
  returned_count              : 10

filter:
  direction: all

notes:
  unresolved_transaction_count: 因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。
```

## 008. `apb.transaction.cursor` / `primary`

- returncode: 0
- elapsed_ms: 110
- bytes: 562
- sha256: `b478c3f7915aac5f3ce45cdeac3b209479aae22f8b3591bd7cd77b4795b8830b`
- request: `{"action": "apb.transaction.cursor", "api_version": "xdebug.v1", "args": {"name": "apb0", "op": "begin"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.transaction.cursor role=primary bytes=562 sha256=b478c3f7915aac5f3ce45cdeac3b209479aae22f8b3591bd7cd77b4795b8830b -->
```xout
@xdebug.apb.transaction.cursor.v1
summary:
  name                : apb0
  op                  : begin
  direction           : all
  found               : true
  index               : 1
  index_base          : 1
  at_begin            : true
  at_end              : false
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 10
  returned_count      : 1
  value_width_complete: true

transaction:
  time     : 125ns
  addr     : 32'h00000000
  data     : 32'h11223344
  is_write : true
  has_error: false
```

## 009. `apb.transfer_window` / `primary`

- returncode: 0
- elapsed_ms: 112
- bytes: 853
- sha256: `6ac825d2e2e28e8cc29efa6372f938cba60eb3195b87d5a7d77713e8ca5a4340`
- request: `{"action": "apb.transfer_window", "api_version": "xdebug.v1", "args": {"name": "apb0"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.transfer_window role=primary bytes=853 sha256=6ac825d2e2e28e8cc29efa6372f938cba60eb3195b87d5a7d77713e8ca5a4340 -->
```xout
@xdebug.apb.transfer_window.v1
summary:
  name                : apb0
  begin               : 0ns
  end                 : max
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 10
  returned_count      : 10
  value_width_complete: true

transactions:
  time   type  addr          data          has_error
  125ns  WR    32'h00000000  32'h11223344  false
  165ns  WR    32'h00000004  32'h55667788  false
  215ns  WR    32'h00000008  32'ha5a55a5a  false
  275ns  WR    32'h0000000c  32'hdeadbeef  false
  315ns  WR    32'h00000004  32'h0000abcd  false
  345ns  RD    32'h00000000  32'h11223344  false
  385ns  RD    32'h00000004  32'h5566abcd  false
  435ns  RD    32'h00000008  32'ha5a55a5a  false
  495ns  RD    32'h0000000c  32'hdeadbeef  false
  525ns  RD    32'h000000f0  32'hbad000f0  true
```

## 010. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 211
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_a"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.axi_vip/versions/b7a0d81ad90d77fb97c0da6239e1e69a10671089527be0adf5e7a21e5507c1f0-prepare-21inkxj8/resources/out/regression/test/axi_multi_id_test/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 011. `axi.config.load` / `setup`

- returncode: 0
- elapsed_ms: 180
- bytes: 4917
- sha256: `b8702f457b14ada684c774ffeb3d262e82475fe813c0c3f0cbaf433903d661fb`
- request: `{"action": "axi.config.load", "api_version": "xdebug.v1", "args": {"config": {"araddr": "axi_vip_fixture_top.axi_vip_if.master_if[0].araddr", "arburst": "axi_vip_fixture_top.axi_vip_if.master_if[0].arburst", "arid": "axi_vip_fixture_top.axi_vip_if.master_if[0].arid", "arlen": "axi_vip_fixture_top.axi_vip_if.master_if[0].arlen", "arready": "axi_vip_fixture_top.axi_vip_if.master_if[0].arready", "arsize": "axi_vip_fixture_top.axi_vip_if.master_if[0].arsize", "arvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid", "awaddr": "axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr", "awburst": "axi_vip_fixture_top.axi_vip_if.master_if[0].awburst", "awid": "axi_vip_fixture_top.axi_vip_if.master_if[0].awid", "awlen": "axi_vip_fixture_top.axi_vip_if.master_if[0].awlen", "awready": "axi_vip_fixture_top.axi_vip_if.master_if[0].awready", "awsize": "axi_vip_fixture_top.axi_vip_if.master_if[0].awsize", "awvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid", "bid": "axi_vip_fixture_top.axi_vip_if.master_if[0].bid", "bready": "axi_vip_fixture_top.axi_vip_if.master_if[0].bready", "bresp": "axi_vip_fixture_top.axi_vip_if.master_if[0].bresp", "bvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid", "clock": "axi_vip_fixture_top.clk", "edge": "posedge", "rdata": "axi_vip_fixture_top.axi_vip_if.master_if[0].rdata", "reset": {"polarity": "active_low", "signal": "axi_vip_fixture_top.rst_n"}, "rid": "axi_vip_fixture_top.axi_vip_if.master_if[0].rid", "rlast": "axi_vip_fixture_top.axi_vip_if.master_if[0].rlast", "rready": "axi_vip_fixture_top.axi_vip_if.master_if[0].rready", "rresp": "axi_vip_fixture_top.axi_vip_if.master_if[0].rresp", "rvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].rvalid", "wdata": "axi_vip_fixture_top.axi_vip_if.master_if[0].wdata", "wlast": "axi_vip_fixture_top.axi_vip_if.master_if[0].wlast", "wready": "axi_vip_fixture_top.axi_vip_if.master_if[0].wready", "wstrb": "axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb", "wvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid"}, "name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.config.load role=setup bytes=4917 sha256=b8702f457b14ada684c774ffeb3d262e82475fe813c0c3f0cbaf433903d661fb -->
```xout
@xdebug.axi.config.load.v1
summary:
  name  : axi0
  status: loaded

config:
  name         : axi0
  sampling_mode: clock_edge
  clock        : axi_vip_fixture_top.clk
  edge         : posedge
  sample_point : before

config.reset:
  signal  : axi_vip_fixture_top.rst_n
  polarity: active_low

config.channels.aw:
  addr : axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].awid
  len  : axi_vip_fixture_top.axi_vip_if.master_if[0].awlen
  size : axi_vip_fixture_top.axi_vip_if.master_if[0].awsize
  burst: axi_vip_fixture_top.axi_vip_if.master_if[0].awburst
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].awready

config.channels.w:
  data : axi_vip_fixture_top.axi_vip_if.master_if[0].wdata
  strb : axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb
  last : axi_vip_fixture_top.axi_vip_if.master_if[0].wlast
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].wready

config.channels.b:
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].bid
  resp : axi_vip_fixture_top.axi_vip_if.master_if[0].bresp
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].bready

config.channels.ar:
  addr : axi_vip_fixture_top.axi_vip_if.master_if[0].araddr
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].arid
  len  : axi_vip_fixture_top.axi_vip_if.master_if[0].arlen
  size : axi_vip_fixture_top.axi_vip_if.master_if[0].arsize
  burst: axi_vip_fixture_top.axi_vip_if.master_if[0].arburst
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].arready

config.channels.r:
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].rid
  data : axi_vip_fixture_top.axi_vip_if.master_if[0].rdata
  resp : axi_vip_fixture_top.axi_vip_if.master_if[0].rresp
  last : axi_vip_fixture_top.axi_vip_if.master_if[0].rlast
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].rvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].rready

validation:
  status: ok

validation.signals:
  field    requested_path                                       resolved_path                                        width  status
  clock    axi_vip_fixture_top.clk                              axi_vip_fixture_top.clk                              1      ok
  reset    axi_vip_fixture_top.rst_n                            axi_vip_fixture_top.rst_n                            1      ok
  awvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid  1      ok
  awready  axi_vip_fixture_top.axi_vip_if.master_if[0].awready  axi_vip_fixture_top.axi_vip_if.master_if[0].awready  1      ok
  awaddr   axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr   axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr   64     ok
  awid     axi_vip_fixture_top.axi_vip_if.master_if[0].awid     axi_vip_fixture_top.axi_vip_if.master_if[0].awid     8      ok
  awlen    axi_vip_fixture_top.axi_vip_if.master_if[0].awlen    axi_vip_fixture_top.axi_vip_if.master_if[0].awlen    10     ok
  awsize   axi_vip_fixture_top.axi_vip_if.master_if[0].awsize   axi_vip_fixture_top.axi_vip_if.master_if[0].awsize   3      ok
  awburst  axi_vip_fixture_top.axi_vip_if.master_if[0].awburst  axi_vip_fixture_top.axi_vip_if.master_if[0].awburst  2      ok
  wvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid   1      ok
  wready   axi_vip_fixture_top.axi_vip_if.master_if[0].wready   axi_vip_fixture_top.axi_vip_if.master_if[0].wready   1      ok
  wdata    axi_vip_fixture_top.axi_vip_if.master_if[0].wdata    axi_vip_fixture_top.axi_vip_if.master_if[0].wdata    1024   ok
  wstrb    axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb    axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb    128    ok
  wlast    axi_vip_fixture_top.axi_vip_if.master_if[0].wlast    axi_vip_fixture_top.axi_vip_if.master_if[0].wlast    1      ok
  bvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid   1      ok
  bready   axi_vip_fixture_top.axi_vip_if.master_if[0].bready   axi_vip_fixture_top.axi_vip_if.master_if[0].bready   1      ok
  bid      axi_vip_fixture_top.axi_vip_if.master_if[0].bid      axi_vip_fixture_top.axi_vip_if.master_if[0].bid      8      ok
  bresp    axi_vip_fixture_top.axi_vip_if.master_if[0].bresp    axi_vip_fixture_top.axi_vip_if.master_if[0].bresp    4      ok
  arvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid  1      ok
  arready  axi_vip_fixture_top.axi_vip_if.master_if[0].arready  axi_vip_fixture_top.axi_vip_if.master_if[0].arready  1      ok

validation.clock:
  status    : ok
  edge      : posedge
  first_edge: 5000
```

## 012. `axi.analysis` / `primary`

- returncode: 0
- elapsed_ms: 6116
- bytes: 2431
- sha256: `4fc0baf21bc0887186a68c197dc2f64212044d8c9cfd92dca05d9f4c958c26d6`
- request: `{"action": "axi.analysis", "api_version": "xdebug.v1", "args": {"analysis": "latency", "direction": "all", "name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.analysis role=primary bytes=2431 sha256=4fc0baf21bc0887186a68c197dc2f64212044d8c9cfd92dca05d9f4c958c26d6 -->
```xout
@xdebug.axi.analysis.v1
summary:
  name                               : axi0
  analysis                           : latency
  direction                          : all
  sample_count                       : 323517
  full_scan_count                    : 1
  completed_read_count               : 3200
  completed_write_count              : 3200
  incomplete_read_count              : 0
  incomplete_write_count             : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0
  samples                            : 6400
  min                                : 60ns
  max                                : 106560ns
  avg                                : 37837.368ns
  p50                                : 16790ns
  p95                                : 81730ns
  p99                                : 95360ns
  scan_complete                      : true
  analysis_complete                  : true
  response_truncated                 : false
  total_count                        : 6400
  returned_count                     : 6400
  value_width_complete               : true

latency.read:
  samples: 3200
  min    : 650ns
  max    : 106560ns
  avg    : 63114.828ns
  p50    : 63860ns
  p95    : 87350ns
  p99    : 99660ns

latency.write:
  samples: 3200
  min    : 60ns
  max    : 17060ns
  avg    : 12559.909ns
  p50    : 12860ns
  p95    : 15350ns
  p99    : 16170ns

latency.definitions:
  read : AR handshake to RLAST handshake
  write: AW handshake to B handshake

latency.write_phase_order_counts:
  aw_before_w: 1474
  same_cycle : 578
  w_before_aw: 1148
  unknown    : 0

slowest:
  direction                    : read
  latency                      : 106560ns
  response_dependency_violation: false

slowest.address:
  channel         : ar
  valid_begin_time: 2285365ns
  handshake_time  : 2285365ns
  addr            : 64'h0000000000005f10
  id              : 8'h06
  len             : 10'h009
  size            : 3'h3
  burst           : 2'h1

slowest.data:
  channel             : r
  valid_begin_time    : 2390305ns
  first_handshake_time: 2390305ns
  last_handshake_time : 2391925ns
  beat_count          : 10
  expected_beat_count : 10

slowest.response:
  channel       : r
  handshake_time: 2391925ns
  resp          : 4'h0
```

## 013. `axi.channel_stall` / `primary`

- returncode: 0
- elapsed_ms: 722
- bytes: 699
- sha256: `1f500655f1aba4aac24c7cc9930bd6502f0fc172fd5e861b4c428932589da8df`
- request: `{"action": "axi.channel_stall", "api_version": "xdebug.v1", "args": {"channel": "r", "line_limit": 2, "name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.channel_stall role=primary bytes=699 sha256=1f500655f1aba4aac24c7cc9930bd6502f0fc172fd5e861b4c428932589da8df -->
```xout
@xdebug.axi.channel_stall.v1
summary:
  name                      : axi0
  channel                   : r
  sampling_mode             : clock_edge
  clock                     : axi_vip_fixture_top.clk
  edge                      : posedge
  sample_time_semantics     : time is sample_time
  sample_count              : 323517
  transfer_count            : 21091
  max_stall_cycles          : 0
  ready_without_valid_cycles: 302425
  first_activity_time       : 15ns
  scan_complete             : true
  analysis_complete         : true
  response_truncated        : false
  total_count               : 0
  returned_count            : 0
  sample_point              : before

data:
  findings: [empty]
```

## 014. `axi.config.list` / `primary`

- returncode: 0
- elapsed_ms: 127
- bytes: 2121
- sha256: `2886a23c78dc23680659052a01ba0f0c72dbfbfae7048b5dd8bc45ee2d83715e`
- request: `{"action": "axi.config.list", "api_version": "xdebug.v1", "args": {"name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.config.list role=primary bytes=2121 sha256=2886a23c78dc23680659052a01ba0f0c72dbfbfae7048b5dd8bc45ee2d83715e -->
```xout
@xdebug.axi.config.list.v1
summary:
  name  : axi0
  status: found

config:
  name         : axi0
  sampling_mode: clock_edge
  clock        : axi_vip_fixture_top.clk
  edge         : posedge
  sample_point : before

config.reset:
  signal  : axi_vip_fixture_top.rst_n
  polarity: active_low

config.channels.aw:
  addr : axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].awid
  len  : axi_vip_fixture_top.axi_vip_if.master_if[0].awlen
  size : axi_vip_fixture_top.axi_vip_if.master_if[0].awsize
  burst: axi_vip_fixture_top.axi_vip_if.master_if[0].awburst
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].awready

config.channels.w:
  data : axi_vip_fixture_top.axi_vip_if.master_if[0].wdata
  strb : axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb
  last : axi_vip_fixture_top.axi_vip_if.master_if[0].wlast
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].wready

config.channels.b:
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].bid
  resp : axi_vip_fixture_top.axi_vip_if.master_if[0].bresp
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].bready

config.channels.ar:
  addr : axi_vip_fixture_top.axi_vip_if.master_if[0].araddr
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].arid
  len  : axi_vip_fixture_top.axi_vip_if.master_if[0].arlen
  size : axi_vip_fixture_top.axi_vip_if.master_if[0].arsize
  burst: axi_vip_fixture_top.axi_vip_if.master_if[0].arburst
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].arready

config.channels.r:
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].rid
  data : axi_vip_fixture_top.axi_vip_if.master_if[0].rdata
  resp : axi_vip_fixture_top.axi_vip_if.master_if[0].rresp
  last : axi_vip_fixture_top.axi_vip_if.master_if[0].rlast
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].rvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].rready
```

## 015. `axi.config.load` / `primary`

- returncode: 0
- elapsed_ms: 124
- bytes: 4931
- sha256: `e014799f2b8b40fabe905a092243e03c4be43dd10d280c7e4c9bcf35bf05d429`
- request: `{"action": "axi.config.load", "api_version": "xdebug.v1", "args": {"config": {"araddr": "axi_vip_fixture_top.axi_vip_if.master_if[0].araddr", "arburst": "axi_vip_fixture_top.axi_vip_if.master_if[0].arburst", "arid": "axi_vip_fixture_top.axi_vip_if.master_if[0].arid", "arlen": "axi_vip_fixture_top.axi_vip_if.master_if[0].arlen", "arready": "axi_vip_fixture_top.axi_vip_if.master_if[0].arready", "arsize": "axi_vip_fixture_top.axi_vip_if.master_if[0].arsize", "arvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid", "awaddr": "axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr", "awburst": "axi_vip_fixture_top.axi_vip_if.master_if[0].awburst", "awid": "axi_vip_fixture_top.axi_vip_if.master_if[0].awid", "awlen": "axi_vip_fixture_top.axi_vip_if.master_if[0].awlen", "awready": "axi_vip_fixture_top.axi_vip_if.master_if[0].awready", "awsize": "axi_vip_fixture_top.axi_vip_if.master_if[0].awsize", "awvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid", "bid": "axi_vip_fixture_top.axi_vip_if.master_if[0].bid", "bready": "axi_vip_fixture_top.axi_vip_if.master_if[0].bready", "bresp": "axi_vip_fixture_top.axi_vip_if.master_if[0].bresp", "bvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid", "clock": "axi_vip_fixture_top.clk", "edge": "posedge", "rdata": "axi_vip_fixture_top.axi_vip_if.master_if[0].rdata", "reset": {"polarity": "active_low", "signal": "axi_vip_fixture_top.rst_n"}, "rid": "axi_vip_fixture_top.axi_vip_if.master_if[0].rid", "rlast": "axi_vip_fixture_top.axi_vip_if.master_if[0].rlast", "rready": "axi_vip_fixture_top.axi_vip_if.master_if[0].rready", "rresp": "axi_vip_fixture_top.axi_vip_if.master_if[0].rresp", "rvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].rvalid", "wdata": "axi_vip_fixture_top.axi_vip_if.master_if[0].wdata", "wlast": "axi_vip_fixture_top.axi_vip_if.master_if[0].wlast", "wready": "axi_vip_fixture_top.axi_vip_if.master_if[0].wready", "wstrb": "axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb", "wvalid": "axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid"}, "name": "axi_primary"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.config.load role=primary bytes=4931 sha256=e014799f2b8b40fabe905a092243e03c4be43dd10d280c7e4c9bcf35bf05d429 -->
```xout
@xdebug.axi.config.load.v1
summary:
  name  : axi_primary
  status: loaded

config:
  name         : axi_primary
  sampling_mode: clock_edge
  clock        : axi_vip_fixture_top.clk
  edge         : posedge
  sample_point : before

config.reset:
  signal  : axi_vip_fixture_top.rst_n
  polarity: active_low

config.channels.aw:
  addr : axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].awid
  len  : axi_vip_fixture_top.axi_vip_if.master_if[0].awlen
  size : axi_vip_fixture_top.axi_vip_if.master_if[0].awsize
  burst: axi_vip_fixture_top.axi_vip_if.master_if[0].awburst
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].awready

config.channels.w:
  data : axi_vip_fixture_top.axi_vip_if.master_if[0].wdata
  strb : axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb
  last : axi_vip_fixture_top.axi_vip_if.master_if[0].wlast
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].wready

config.channels.b:
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].bid
  resp : axi_vip_fixture_top.axi_vip_if.master_if[0].bresp
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].bready

config.channels.ar:
  addr : axi_vip_fixture_top.axi_vip_if.master_if[0].araddr
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].arid
  len  : axi_vip_fixture_top.axi_vip_if.master_if[0].arlen
  size : axi_vip_fixture_top.axi_vip_if.master_if[0].arsize
  burst: axi_vip_fixture_top.axi_vip_if.master_if[0].arburst
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].arready

config.channels.r:
  id   : axi_vip_fixture_top.axi_vip_if.master_if[0].rid
  data : axi_vip_fixture_top.axi_vip_if.master_if[0].rdata
  resp : axi_vip_fixture_top.axi_vip_if.master_if[0].rresp
  last : axi_vip_fixture_top.axi_vip_if.master_if[0].rlast
  valid: axi_vip_fixture_top.axi_vip_if.master_if[0].rvalid
  ready: axi_vip_fixture_top.axi_vip_if.master_if[0].rready

validation:
  status: ok

validation.signals:
  field    requested_path                                       resolved_path                                        width  status
  clock    axi_vip_fixture_top.clk                              axi_vip_fixture_top.clk                              1      ok
  reset    axi_vip_fixture_top.rst_n                            axi_vip_fixture_top.rst_n                            1      ok
  awvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].awvalid  1      ok
  awready  axi_vip_fixture_top.axi_vip_if.master_if[0].awready  axi_vip_fixture_top.axi_vip_if.master_if[0].awready  1      ok
  awaddr   axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr   axi_vip_fixture_top.axi_vip_if.master_if[0].awaddr   64     ok
  awid     axi_vip_fixture_top.axi_vip_if.master_if[0].awid     axi_vip_fixture_top.axi_vip_if.master_if[0].awid     8      ok
  awlen    axi_vip_fixture_top.axi_vip_if.master_if[0].awlen    axi_vip_fixture_top.axi_vip_if.master_if[0].awlen    10     ok
  awsize   axi_vip_fixture_top.axi_vip_if.master_if[0].awsize   axi_vip_fixture_top.axi_vip_if.master_if[0].awsize   3      ok
  awburst  axi_vip_fixture_top.axi_vip_if.master_if[0].awburst  axi_vip_fixture_top.axi_vip_if.master_if[0].awburst  2      ok
  wvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].wvalid   1      ok
  wready   axi_vip_fixture_top.axi_vip_if.master_if[0].wready   axi_vip_fixture_top.axi_vip_if.master_if[0].wready   1      ok
  wdata    axi_vip_fixture_top.axi_vip_if.master_if[0].wdata    axi_vip_fixture_top.axi_vip_if.master_if[0].wdata    1024   ok
  wstrb    axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb    axi_vip_fixture_top.axi_vip_if.master_if[0].wstrb    128    ok
  wlast    axi_vip_fixture_top.axi_vip_if.master_if[0].wlast    axi_vip_fixture_top.axi_vip_if.master_if[0].wlast    1      ok
  bvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid   axi_vip_fixture_top.axi_vip_if.master_if[0].bvalid   1      ok
  bready   axi_vip_fixture_top.axi_vip_if.master_if[0].bready   axi_vip_fixture_top.axi_vip_if.master_if[0].bready   1      ok
  bid      axi_vip_fixture_top.axi_vip_if.master_if[0].bid      axi_vip_fixture_top.axi_vip_if.master_if[0].bid      8      ok
  bresp    axi_vip_fixture_top.axi_vip_if.master_if[0].bresp    axi_vip_fixture_top.axi_vip_if.master_if[0].bresp    4      ok
  arvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid  axi_vip_fixture_top.axi_vip_if.master_if[0].arvalid  1      ok
  arready  axi_vip_fixture_top.axi_vip_if.master_if[0].arready  axi_vip_fixture_top.axi_vip_if.master_if[0].arready  1      ok

validation.clock:
  status    : ok
  edge      : posedge
  first_edge: 5000
```

## 016. `axi.export` / `primary`

- returncode: 0
- elapsed_ms: 112
- bytes: 962
- sha256: `d0651474b53df0e8fcaa299c62f27ddb2bd6a7188117e86fe2d2d98c527942e6`
- request: `{"action": "axi.export", "api_version": "xdebug.v1", "args": {"name": "axi0", "output": {"file_format": "tsv", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/axi"}, "time_range": {"begin": "0ns", "end": "1us"}}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.export role=primary bytes=962 sha256=d0651474b53df0e8fcaa299c62f27ddb2bd6a7188117e86fe2d2d98c527942e6 -->
```xout
@xdebug.axi.export.v1
summary:
  name                               : axi0
  write_count                        : 3
  read_count                         : 0
  total_count                        : 3
  row_count                          : 3
  format                             : tsv
  status                             : written
  output_written                     : true
  sample_count                       : 323517
  full_scan_count                    : 1
  incomplete_write_count             : 0
  incomplete_read_count              : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0
  scan_complete                      : true
  analysis_complete                  : true
  response_truncated                 : false
  returned_count                     : 3
```

## 017. `axi.latency_outlier` / `primary`

- returncode: 0
- elapsed_ms: 142
- bytes: 1607
- sha256: `c5a523737c6374e05e585dc7f5b86cec79f13982c721ba350dfa253203bfad01`
- request: `{"action": "axi.latency_outlier", "api_version": "xdebug.v1", "args": {"line_limit": 2, "method": "top_n", "name": "axi0", "top_n": 2}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.latency_outlier role=primary bytes=1607 sha256=c5a523737c6374e05e585dc7f5b86cec79f13982c721ba350dfa253203bfad01 -->
```xout
@xdebug.axi.latency_outlier.v1
summary:
  name                : axi0
  begin               : 0ns
  end                 : max
  candidate_count     : 6400
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 2
  returned_count      : 2
  value_width_complete: true

outliers:
  direction  latency   response_dependency_violation  address.channel  address.valid_begin_time  address.handshake_time  address.addr          address.id  address.len  address.size  address.burst  data.channel  data.valid_begin_time  data.first_handshake_time  data.last_handshake_time  data.beat_count  data.expected_beat_count  response.channel  response.handshake_time  response.resp  match_time
  read       106560ns  false                          ar               2285365ns                 2285365ns               64'h0000000000005f10  8'h06       10'h009      3'h3          2'h1           r             2390305ns              2390305ns                  2391925ns                 10               10                        r                 2391925ns                4'h0           2285365ns
  read       105000ns  false                          ar               2285295ns                 2285295ns               64'h000000000000eaf0  8'h05       10'h00f      3'h3          2'h1           r             2389545ns              2389545ns                  2390295ns                 16               16                        r                 2390295ns                4'h0           2285295ns
  method        : top_n
  classification: slowest_ranking
  top_n         : 2
```

## 018. `axi.outstanding_timeline` / `primary`

- returncode: 0
- elapsed_ms: 121
- bytes: 1025
- sha256: `0da3fa40cb1a3743c65965c53e2cfd70d9304f16036fb6ba0d1766eda3226b2d`
- request: `{"action": "axi.outstanding_timeline", "api_version": "xdebug.v1", "args": {"direction": "all", "line_limit": 4, "name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.outstanding_timeline role=primary bytes=1025 sha256=0da3fa40cb1a3743c65965c53e2cfd70d9304f16036fb6ba0d1766eda3226b2d -->
```xout
@xdebug.axi.outstanding_timeline.v1
summary:
  name                 : axi0
  sampling_mode        : clock_edge
  clock                : axi_vip_fixture_top.clk
  edge                 : posedge
  sample_time_semantics: time is sample_time
  sample_count         : 323497
  peak_read            : 64
  peak_write           : 64
  peak_read_time       : 85015ns
  peak_write_time      : 19615ns
  first_nonzero_time   : 415ns
  final_read           : 0
  final_write          : 0
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : true
  total_count          : 11355
  returned_count       : 4
  sample_point         : before

change_points:
  time   read  write  read_delta  read_event    write_delta  write_event
  205ns  0     0      0           none          0            none
  415ns  1     1      1           ar_handshake  1            aw_handshake
  475ns  1     0      0           none          -1           b_handshake
  495ns  2     0      1           ar_handshake  0            none
```

## 019. `axi.query` / `primary`

- returncode: 0
- elapsed_ms: 163
- bytes: 3345
- sha256: `d3a63bbbb68ec9dce529d8324a28363f52f8fcaf7fec9b059fd0b09db2e975c3`
- request: `{"action": "axi.query", "api_version": "xdebug.v1", "args": {"direction": "write", "name": "axi0", "query": {"line_limit": 2}}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.query role=primary bytes=3345 sha256=d3a63bbbb68ec9dce529d8324a28363f52f8fcaf7fec9b059fd0b09db2e975c3 -->
```xout
@xdebug.axi.query.v1
summary:
  name              : axi0
  direction         : write
  data_scope        : first_beat_each_with_first_transaction_full
  query_mode        : list
  data_hint         : Each transaction includes its first beat and the first transaction includes all beats. To inspect complete data for another transaction, narrow it with query.index, last, address, id, or time_range, then set output.include_data=true.
  scan_complete     : true
  analysis_complete : true
  response_truncated: true
  total_count       : 3200
  returned_count    : 2

truncation_scopes:
  response_transactions
  value_width_complete: true
  width_diagnostics   : [empty]

filter:
  direction: write

transactions:
  index  direction  phase_order  latency  response_dependency_violation  match_time
  1      write      aw_before_w  60ns     false
  2      write      w_before_aw  90ns     false

transaction_1_address:
  channel         : aw
  valid_begin_time: 415ns
  handshake_time  : 415ns
  addr            : 64'h00000000000008c0
  id              : 8'h00
  len             : 10'h000
  size            : 3'h3
  burst           : 2'h1

transaction_1_data:
  channel             : w
  valid_begin_time    : 465ns
  first_handshake_time: 465ns
  last_handshake_time : 465ns
  beat_count          : 1
  expected_beat_count : 1

transaction_1_beats:
  index  handshake_time  data                                                                                                                                                                                                                                                                    wstrb                                  resp  last
  1      465ns           1024'h000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f82beac4c2e319e8  128'h000000000000000000000000000000ff        true

transaction_1_response:
  channel       : b
  handshake_time: 475ns
  resp          : 4'h0

transaction_2_address:
  channel         : aw
  valid_begin_time: 515ns
  handshake_time  : 515ns
  addr            : 64'h000000000000ef28
  id              : 8'h01
  len             : 10'h002
  size            : 3'h3
  burst           : 2'h1

transaction_2_data:
  channel             : w
  valid_begin_time    : 475ns
  first_handshake_time: 475ns
  last_handshake_time : 495ns
  beat_count          : 3
  expected_beat_count : 3

transaction_2_beats:
  index  handshake_time  data                                                                                                                                                                                                                                                                    wstrb                                  resp  last
  1      475ns           1024'h0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000009cc9ee7cbc9be89d  128'h000000000000000000000000000000ff        false

transaction_2_response:
  channel       : b
  handshake_time: 605ns
  resp          : 4'h0
```

## 020. `axi.request_response_pair` / `primary`

- returncode: 0
- elapsed_ms: 130
- bytes: 2128
- sha256: `1940670fa637b449146b4e0104c3f9e0e2ee4fd2af996423605347632726d3c7`
- request: `{"action": "axi.request_response_pair", "api_version": "xdebug.v1", "args": {"direction": "all", "line_limit": 2, "name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.request_response_pair role=primary bytes=2128 sha256=1940670fa637b449146b4e0104c3f9e0e2ee4fd2af996423605347632726d3c7 -->
```xout
@xdebug.axi.request_response_pair.v1
summary:
  name                : axi0
  begin               : 0ns
  end                 : max
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : true
  total_count         : 6400
  returned_count      : 2
  value_width_complete: true

pairing_rule:
  write_data    : AXI4 W bursts bind in AW acceptance order
  write_response: BID binds to the oldest data-complete AW with the same ID
  read_response : RID binds to the oldest AR with the same ID

diagnostics:
  full_scan_count                    : 1
  incomplete_write_count             : 0
  incomplete_read_count              : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0

transactions:
  direction  latency  response_dependency_violation  address.channel  address.valid_begin_time  address.handshake_time  address.addr          address.id  address.len  address.size  address.burst  data.channel  data.valid_begin_time  data.first_handshake_time  data.last_handshake_time  data.beat_count  data.expected_beat_count  response.channel  response.handshake_time  response.resp  match_time  phase_order
  read       650ns    false                          ar               415ns                     415ns                   64'h000000000000ef58  8'h00       10'h00c      3'h3          2'h1           r             465ns                  465ns                      1065ns                    13               13                        r                 1065ns                   4'h0           415ns
  write      60ns     false                          aw               415ns                     415ns                   64'h00000000000008c0  8'h00       10'h000      3'h3          2'h1           w             465ns                  465ns                      465ns                     1                1                         b                 475ns                    4'h0           415ns       aw_before_w
```

## 021. `axi.statistics` / `primary`

- returncode: 0
- elapsed_ms: 157
- bytes: 739
- sha256: `74f6c70d189cb790e9b09fb8b4f0c89b7199418027cc3b260e035ee6adaf462c`
- request: `{"action": "axi.statistics", "api_version": "xdebug.v1", "args": {"name": "axi0"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.statistics role=primary bytes=739 sha256=74f6c70d189cb790e9b09fb8b4f0c89b7199418027cc3b260e035ee6adaf462c -->
```xout
@xdebug.axi.statistics.v1
summary:
  name                        : axi0
  scanned_transaction_count   : 6400
  matched_transaction_count   : 6400
  matched_read_count          : 3200
  matched_write_count         : 3200
  unresolved_transaction_count: 0
  filter_applied              : false
  analysis_quality            : complete
  full_scan_count             : 1
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 6400
  returned_count              : 6400

filter:
  direction: all

notes:
  unresolved_transaction_count: 因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。
```

## 022. `axi.transaction.cursor` / `primary`

- returncode: 0
- elapsed_ms: 126
- bytes: 1136
- sha256: `fc17728ee28f616725abf94908c4c96d00fdf1d81abe8df2dbf8c919a087a714`
- request: `{"action": "axi.transaction.cursor", "api_version": "xdebug.v1", "args": {"direction": "all", "name": "axi0", "op": "begin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.transaction.cursor role=primary bytes=1136 sha256=fc17728ee28f616725abf94908c4c96d00fdf1d81abe8df2dbf8c919a087a714 -->
```xout
@xdebug.axi.transaction.cursor.v1
summary:
  name                : axi0
  op                  : begin
  direction           : all
  found               : true
  index               : 1
  index_base          : 1
  at_begin            : true
  at_end              : false
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 6400
  returned_count      : 1
  value_width_complete: true

transaction:
  direction                    : write
  phase_order                  : aw_before_w
  latency                      : 60ns
  response_dependency_violation: false

transaction.address:
  channel         : aw
  valid_begin_time: 415ns
  handshake_time  : 415ns
  addr            : 64'h00000000000008c0
  id              : 8'h00
  len             : 10'h000
  size            : 3'h3
  burst           : 2'h1

transaction.data:
  channel             : w
  valid_begin_time    : 465ns
  first_handshake_time: 465ns
  last_handshake_time : 465ns
  beat_count          : 1
  expected_beat_count : 1

transaction.response:
  channel       : b
  handshake_time: 475ns
  resp          : 4'h0
```

## 023. `batch` / `primary`

- returncode: 0
- elapsed_ms: 652
- bytes: 688
- sha256: `8fe16061c846d93c374ac8ccc1daf88b7173768eb23b562e8c327c311d9e700f`
- request: `{"action": "batch", "api_version": "xdebug.v1", "args": {"requests": [{"action": "actions", "api_version": "xdebug.v1", "args": {}}]}}`

<!-- XOUT_BODY phase=final action=batch role=primary bytes=688 sha256=8fe16061c846d93c374ac8ccc1daf88b7173768eb23b562e8c327c311d9e700f -->
```xout
@xdebug.batch.v1
summary:
  count       : 1
  all_ok      : true
  failed_count: 0

results:
  api_version  ok    action   tool.name  tool.version  tool.build_id                                                                  tool.git_revision  tool.schema_revision                                              summary.action_count  summary.total_action_count  summary.verbose  summary.filtered
  xdebug.v1    true  actions  xdebug     0.1.0         69cd811f92b4-c45099040abf3dbe194d3ba27c207d7637b39ba9f9d662fad3d9d50dda99fb2c  69cd811f92b4       c45099040abf3dbe194d3ba27c207d7637b39ba9f9d662fad3d9d50dda99fb2c  73                    73                          false            false
```

## 024. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 271
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_w"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 025. `counter.statistics` / `primary`

- returncode: 0
- elapsed_ms: 163
- bytes: 1141
- sha256: `1f0061f9e520f876eaa50024ba14add470e6714b2008d52810375e5daae553d6`
- request: `{"action": "counter.statistics", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "cnt": "ai_complex_top.counter_inc", "edge": "posedge", "time_range": {"begin": "55ns", "end": "95ns"}, "vld": "ai_complex_top.rst_n"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=counter.statistics role=primary bytes=1141 sha256=1f0061f9e520f876eaa50024ba14add470e6714b2008d52810375e5daae553d6 -->
```xout
@xdebug.counter.statistics.v1
summary:
  sample_count         : 5
  valid_count          : 5
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  begin                : 55ns
  end                  : 95ns
  valid_false_count    : 0
  unknown_count        : 0
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 5
  returned_count       : 5
  min_value            : 8'h0
  max_value            : 8'h4
  average_value        : 2
  value_width_complete : true

evidence:
  time  kind          value
  55ns  initial       8'h0
  65ns  value_change  8'h1
  75ns  value_change  8'h2
  85ns  value_change  8'h3
  95ns  value_change  8'h4

sampling:
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: posedge

sampling.effective:
  edge          : posedge
  sample_point  : before
  cnt           : ai_complex_top.counter_inc
  vld           : ai_complex_top.rst_n
  min_count     : 1
  max_count     : 1
  min_first_time: 55ns
  max_first_time: 95ns
```

## 026. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 251
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_e"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.xif_event/versions/664ac163a4de5950f40c81bafad04508bf5ea6a1fadbf1eca21aeabe1306ee44-prepare-kh7pipx2/resources/out/waves/xif_event_multi_if_test.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 027. `event.config.load` / `setup`

- returncode: 0
- elapsed_ms: 123
- bytes: 272
- sha256: `566f8525eaf715b96cbe953d036a99a50925389c18cb123dcee8648c215dc01d`
- request: `{"action": "event.config.load", "api_version": "xdebug.v1", "args": {"config_path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/event_rdy_leaf.json", "name": "rdy"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.config.load role=setup bytes=272 sha256=566f8525eaf715b96cbe953d036a99a50925389c18cb123dcee8648c215dc01d -->
```xout
@xdebug.event.config.load.v1
summary:
  status: loaded

config:
  name : rdy
  clock: xif_event_top.clk
  edge : posedge

config.reset:
  signal  : xif_event_top.rst_n
  polarity: active_low

config.signals:
  rdy: xif_event_top.if_rdy.rdy
  vld: xif_event_top.if_rdy.vld
```

## 028. `event.config.list` / `primary`

- returncode: 0
- elapsed_ms: 138
- bytes: 271
- sha256: `ae8331ce28aebdeff087d43354d9b1f906e27d8e2aff1b66fdcf4266a03cc0e6`
- request: `{"action": "event.config.list", "api_version": "xdebug.v1", "args": {"name": "rdy"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.config.list role=primary bytes=271 sha256=ae8331ce28aebdeff087d43354d9b1f906e27d8e2aff1b66fdcf4266a03cc0e6 -->
```xout
@xdebug.event.config.list.v1
summary:
  status: found

config:
  name : rdy
  clock: xif_event_top.clk
  edge : posedge

config.reset:
  signal  : xif_event_top.rst_n
  polarity: active_low

config.signals:
  rdy: xif_event_top.if_rdy.rdy
  vld: xif_event_top.if_rdy.vld
```

## 029. `event.config.load` / `primary`

- returncode: 0
- elapsed_ms: 173
- bytes: 282
- sha256: `5056e09b47e561f3d03e868f342babfef4a8ab81dbef684cfb92d277ecd0b5be`
- request: `{"action": "event.config.load", "api_version": "xdebug.v1", "args": {"config_path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/event_rdy_leaf.json", "name": "primary_event"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.config.load role=primary bytes=282 sha256=5056e09b47e561f3d03e868f342babfef4a8ab81dbef684cfb92d277ecd0b5be -->
```xout
@xdebug.event.config.load.v1
summary:
  status: loaded

config:
  name : primary_event
  clock: xif_event_top.clk
  edge : posedge

config.reset:
  signal  : xif_event_top.rst_n
  polarity: active_low

config.signals:
  rdy: xif_event_top.if_rdy.rdy
  vld: xif_event_top.if_rdy.vld
```

## 030. `event.export` / `primary`

- returncode: 0
- elapsed_ms: 137
- bytes: 831
- sha256: `4d832feeed88d4bc83333c53b81c5ba0e0da2266ea9e4fb2879ac2f7895e3699`
- request: `{"action": "event.export", "api_version": "xdebug.v1", "args": {"expr": "vld && rdy", "name": "rdy", "output": {"file_format": "json", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/events.json"}}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.export role=primary bytes=831 sha256=4d832feeed88d4bc83333c53b81c5ba0e0da2266ea9e4fb2879ac2f7895e3699 -->
```xout
@xdebug.event.export.v1
summary:
  sample_count         : 20
  mode                 : export
  inline               : false
  sampling_mode        : clock_edge
  clock                : xif_event_top.clk
  sample_time_semantics: time is sample_time
  first                : 85ns
  last                 : 135ns
  begin                : 0ns
  end                  : max
  status               : written
  output_written       : true
  row_count            : 5
  line_limit           : 1000
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 5
  returned_count       : 5

sampling:
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: posedge

sampling.effective:
  edge        : posedge
  sample_point: before
```

## 031. `event.find` / `primary`

- returncode: 0
- elapsed_ms: 107
- bytes: 844
- sha256: `94e9b7c8841eb67368353cbe3ed40d52c62753243bd647509ba75fd1f6c7d9df`
- request: `{"action": "event.find", "api_version": "xdebug.v1", "args": {"expr": "vld && rdy", "line_limit": 2, "mode": "all", "name": "rdy"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.find role=primary bytes=844 sha256=94e9b7c8841eb67368353cbe3ed40d52c62753243bd647509ba75fd1f6c7d9df -->
```xout
@xdebug.event.find.v1
summary:
  sample_count         : 20
  mode                 : all
  inline               : false
  sampling_mode        : clock_edge
  clock                : xif_event_top.clk
  sample_time_semantics: time is sample_time
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : true
  total_count          : 5
  returned_count       : 2

truncation_scopes:
  response_events
  first               : 85ns
  last                : 135ns
  begin               : 0ns
  end                 : max
  value_width_complete: true

requested:
  edge: posedge

effective:
  edge                            : posedge
  sample_point                    : before
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

events:
  time  rdy   vld
  85ns  1'h1  1'h1
  95ns  1'h1  1'h1
```

## 032. `expr.eval_at` / `primary`

- returncode: 0
- elapsed_ms: 167
- bytes: 849
- sha256: `64d6731b0eca71d98de9e45e6d82a518c87d14607594d7827a5998e86b5f364a`
- request: `{"action": "expr.eval_at", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "expr": "valid && !ready", "signals": {"ready": "ai_complex_top.hs_ready", "valid": "ai_complex_top.hs_valid"}, "time": "145ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=expr.eval_at role=primary bytes=849 sha256=64d6731b0eca71d98de9e45e6d82a518c87d14607594d7827a5998e86b5f364a -->
```xout
@xdebug.expr.eval_at.v1
summary:
  expr                : valid&&!ready
  time                : 145ns
  status              : true
  value_width_complete: true

data:
  expr_value: true

operands:
  alias  signal                   value
  ready  ai_complex_top.hs_ready  1'h0
  valid  ai_complex_top.hs_valid  1'h1

clock_context:
  clock                           : ai_complex_top.clk
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false
  requested_time                  : 145ns
  requested_any_edge_hit          : false
  requested_target_edge_hit       : false
  previous_sample_time            : 90ns
  bracket_complete                : false

clock_context.requested_sampling:
  edge: negedge

clock_context.effective_sampling:
  edge: negedge

expr_samples:
  before: false
  middle: true
  after : missing_edge
```

## 033. `expr.normalize` / `primary`

- returncode: 0
- elapsed_ms: 133
- bytes: 360
- sha256: `5fde614b01217921eb708f1b91c177220ff229dc18ba7ece1359feac7cf28b28`
- request: `{"action": "expr.normalize", "api_version": "xdebug.v1", "args": {"expr": "valid && !ready"}}`

<!-- XOUT_BODY phase=final action=expr.normalize role=primary bytes=360 sha256=5fde614b01217921eb708f1b91c177220ff229dc18ba7ece1359feac7cf28b28 -->
```xout
@xdebug.expr.normalize.v1
summary:
  expr      : valid && !ready
  source    : deterministic_syntax_parser
  confidence: syntax_validated

expr:
  op: and

expr.args:
  name   type    op
  valid  signal
                 not
  confidence       : syntax_validated
  confidence_reason: expression syntax was validated and parsed without design-resource semantics
```

## 034. `list.create` / `setup`

- returncode: 0
- elapsed_ms: 107
- bytes: 177
- sha256: `63653cf3482bf1715ef56edce6ce332c881447dd4ebc620e2a528e085792a6d9`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "basic_add", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=setup bytes=177 sha256=63653cf3482bf1715ef56edce6ce332c881447dd4ebc620e2a528e085792a6d9 -->
```xout
@xdebug.list.create.v1
summary:
  name        : basic_add
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 035. `list.add` / `primary`

- returncode: 0
- elapsed_ms: 83
- bytes: 114
- sha256: `d9e393bd77b63b0952796d57d7441523123f715731379b210aabbc87c0e5c764`
- request: `{"action": "list.add", "api_version": "xdebug.v1", "args": {"name": "basic_add", "signal": "ai_complex_top.hs_valid"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.add role=primary bytes=114 sha256=d9e393bd77b63b0952796d57d7441523123f715731379b210aabbc87c0e5c764 -->
```xout
@xdebug.list.add.v1
summary:
  name  : basic_add
  signal: ai_complex_top.hs_valid
  status: added
  added : true
```

## 036. `list.create` / `primary`

- returncode: 0
- elapsed_ms: 101
- bytes: 180
- sha256: `a1dfb16f43beb29e71bd0f6b5ccc26aacafdb9b8e3d0f14790e0a51c99bb1efb`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "primary_list", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=primary bytes=180 sha256=a1dfb16f43beb29e71bd0f6b5ccc26aacafdb9b8e3d0f14790e0a51c99bb1efb -->
```xout
@xdebug.list.create.v1
summary:
  name        : primary_list
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 037. `list.create` / `setup`

- returncode: 0
- elapsed_ms: 105
- bytes: 180
- sha256: `8cd0ed9262b969773421369a7bd9ad60b0c942248f8ba46c41c05cee5335e678`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "basic_delete", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=setup bytes=180 sha256=8cd0ed9262b969773421369a7bd9ad60b0c942248f8ba46c41c05cee5335e678 -->
```xout
@xdebug.list.create.v1
summary:
  name        : basic_delete
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 038. `list.delete` / `primary`

- returncode: 0
- elapsed_ms: 111
- bytes: 104
- sha256: `2dac639a8acb0fb08a53fda9ab0facc961723b5eff1c83448251033e7bba05d8`
- request: `{"action": "list.delete", "api_version": "xdebug.v1", "args": {"index": 2, "name": "basic_delete"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.delete role=primary bytes=104 sha256=2dac639a8acb0fb08a53fda9ab0facc961723b5eff1c83448251033e7bba05d8 -->
```xout
@xdebug.list.delete.v1
summary:
  name   : basic_delete
  deleted: true
  removed: ai_complex_top.sig_b
```

## 039. `list.create` / `setup`

- returncode: 0
- elapsed_ms: 107
- bytes: 180
- sha256: `fe91d3ece656a8ef6e8d416d50b4629694e107bfe08d539618a496672ae29213`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "basic_export", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=setup bytes=180 sha256=fe91d3ece656a8ef6e8d416d50b4629694e107bfe08d539618a496672ae29213 -->
```xout
@xdebug.list.create.v1
summary:
  name        : basic_export
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 040. `list.export` / `primary`

- returncode: 0
- elapsed_ms: 133
- bytes: 364
- sha256: `178cd42f3c9d1ad4facb0ba1f83126f3f6bc65b317f88c6da3b28037b5f1c932`
- request: `{"action": "list.export", "api_version": "xdebug.v1", "args": {"name": "basic_export", "output": {"file_format": "u64bin", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/list_export"}, "time_range": {"begin": "0ns", "end": "400ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.export role=primary bytes=364 sha256=178cd42f3c9d1ad4facb0ba1f83126f3f6bc65b317f88c6da3b28037b5f1c932 -->
```xout
@xdebug.list.export.v1
summary:
  name              : basic_export
  row_count         : 6
  format            : u64bin.v1
  status            : written
  output_written    : true
  begin             : 0ns
  end               : 400ns
  scan_complete     : true
  analysis_complete : true
  response_truncated: false
  total_count       : 2
  returned_count    : 2
```

## 041. `list.create` / `setup`

- returncode: 0
- elapsed_ms: 109
- bytes: 186
- sha256: `bab932511115b69a3692bd9a4b0c64427edcda550fcf9a040c6d16c4f1511601`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "basic_first_change", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=setup bytes=186 sha256=bab932511115b69a3692bd9a4b0c64427edcda550fcf9a040c6d16c4f1511601 -->
```xout
@xdebug.list.create.v1
summary:
  name        : basic_first_change
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 042. `list.first_change` / `primary`

- returncode: 0
- elapsed_ms: 129
- bytes: 404
- sha256: `8f89714cf53c54a5692f8338fd8b5911cfd4963bdef876cf493a68ff8c357ec9`
- request: `{"action": "list.first_change", "api_version": "xdebug.v1", "args": {"name": "basic_first_change", "time_range": {"begin": "0ns", "end": "120ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.first_change role=primary bytes=404 sha256=8f89714cf53c54a5692f8338fd8b5911cfd4963bdef876cf493a68ff8c357ec9 -->
```xout
@xdebug.list.first_change.v1
summary:
  name                : basic_first_change
  diff_found          : true
  diff_time           : 55ns
  changed_signal_count: 2
  value_width_complete: true

changed_signals:
  signal                before_time  change_time  before  after
  ai_complex_top.sig_b  0ns          55ns         8'h0    8'h11
  ai_complex_top.sig_a  0ns          55ns         8'h0    8'h11
```

## 043. `list.load` / `primary`

- returncode: 0
- elapsed_ms: 117
- bytes: 120
- sha256: `d2c5332bee266055fcb259e707521af4616b65fe9cc19aeba7034e59c611e1d7`
- request: `{"action": "list.load", "api_version": "xdebug.v1", "args": {"config": {"lists": [{"name": "loaded", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}]}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.load role=primary bytes=120 sha256=d2c5332bee266055fcb259e707521af4616b65fe9cc19aeba7034e59c611e1d7 -->
```xout
@xdebug.list.load.v1
summary:
  loaded: 1
  mode  : replace

lists:
  loaded

validation:
  name    status
  loaded  ok
```

## 044. `list.create` / `setup`

- returncode: 0
- elapsed_ms: 109
- bytes: 178
- sha256: `183dee611969b33b74f648f63c6afc49f24b2a3c4d6036ad17f8838c9bb389b1`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "basic_show", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=setup bytes=178 sha256=183dee611969b33b74f648f63c6afc49f24b2a3c4d6036ad17f8838c9bb389b1 -->
```xout
@xdebug.list.create.v1
summary:
  name        : basic_show
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 045. `list.show` / `primary`

- returncode: 0
- elapsed_ms: 108
- bytes: 161
- sha256: `ae6da1e74e206af655370687b339dd88f1e368587fb27cc2c1d5bde2ff657ad0`
- request: `{"action": "list.show", "api_version": "xdebug.v1", "args": {"name": "basic_show"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.show role=primary bytes=161 sha256=ae6da1e74e206af655370687b339dd88f1e368587fb27cc2c1d5bde2ff657ad0 -->
```xout
@xdebug.list.show.v1
summary:
  name        : basic_show
  signal_count: 2

signals:
  index  signal
  1      ai_complex_top.sig_a
  2      ai_complex_top.sig_b
```

## 046. `list.create` / `setup`

- returncode: 0
- elapsed_ms: 109
- bytes: 182
- sha256: `eb11335d075c36ff1ad23f4cc390fbd17b654480d8915a8653965a2c977c7d8d`
- request: `{"action": "list.create", "api_version": "xdebug.v1", "args": {"name": "basic_validate", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.create role=setup bytes=182 sha256=eb11335d075c36ff1ad23f4cc390fbd17b654480d8915a8653965a2c977c7d8d -->
```xout
@xdebug.list.create.v1
summary:
  name        : basic_validate
  status      : created
  created     : true
  signal_count: 2

signals:
  ai_complex_top.sig_a
  ai_complex_top.sig_b
```

## 047. `list.validate` / `primary`

- returncode: 0
- elapsed_ms: 121
- bytes: 175
- sha256: `62f6a3a07c21059ed640996aab25aea91e6f445cccfa32493f55868e01b10ce4`
- request: `{"action": "list.validate", "api_version": "xdebug.v1", "args": {"name": "basic_validate"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.validate role=primary bytes=175 sha256=62f6a3a07c21059ed640996aab25aea91e6f445cccfa32493f55868e01b10ce4 -->
```xout
@xdebug.list.validate.v1
summary:
  name     : basic_validate
  all_found: true

signals:
  signal                status
  ai_complex_top.sig_a  ok
  ai_complex_top.sig_b  ok
```

## 048. `nwave.rc.generate` / `primary`

- returncode: 0
- elapsed_ms: 167
- bytes: 507
- sha256: `58ad51c7472edc3a2601be07a7336c4249c3ecc33b7ac71b0b3c649a09a6b53f`
- request: `{"action": "nwave.rc.generate", "api_version": "xdebug.v1", "args": {"config_path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/wave_view.json", "output": {"path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/signal.rc"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=nwave.rc.generate role=primary bytes=507 sha256=58ad51c7472edc3a2601be07a7336c4249c3ecc33b7ac71b0b3c649a09a6b53f -->
```xout
@xdebug.nwave.rc.generate.v1
summary:
  written     : true
  config_path : /tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/wave_view.json
  valid       : true
  group_count : 1
  signal_count: 1

validation:
  signals: 1
  times  : 0

rc_preview:
  ; Generated by xdebug nwave.rc.generate
  ; Signal list/view rc only; open the FSDB separately in nWave.
  windowTimeUnit 1ns
  fileTimeScale 1ns
  signalSpacing 5
  top 0
  curSTATUS ByValue
  addGroup "clock"
  addSignal /ai_complex_top/clk
```

## 049. `protocol.handshake.inspect` / `primary`

- returncode: 0
- elapsed_ms: 135
- bytes: 1029
- sha256: `80e7303148e4b8b83421c85d9ebc98d0fd2958a9e03e92a24375ac0c7171d2ea`
- request: `{"action": "protocol.handshake.inspect", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "ready": "ai_complex_top.hs_ready", "valid": "ai_complex_top.hs_valid"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=protocol.handshake.inspect role=primary bytes=1029 sha256=80e7303148e4b8b83421c85d9ebc98d0fd2958a9e03e92a24375ac0c7171d2ea -->
```xout
@xdebug.protocol.handshake.inspect.v1
summary:
  sampling_mode                     : clock_edge
  clock                             : ai_complex_top.clk
  sample_time_semantics             : time is sample_time
  sample_count                      : 48
  transfer_count                    : 3
  max_stall_cycles                  : 4
  ready_without_valid_cycles        : 29
  ready_without_valid_reporting     : summary
  ready_without_valid_interval_count: 1
  data_stability_violations         : 0
  require_valid_hold_until_handshake: true
  valid_hold_violations             : 0
  valid_wait_open_at_window_end     : false
  scan_complete                     : true
  analysis_complete                 : true
  response_truncated                : false
  total_count                       : 0
  returned_count                    : 0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge    : negedge
  findings: [empty]
```

## 050. `schema` / `primary`

- returncode: 0
- elapsed_ms: 77
- bytes: 2877
- sha256: `73b5ea0c99fbde9e27833eb0a55c1ab40c0590b3444c080c41613cdfd010cb0e`
- request: `{"action": "schema", "api_version": "xdebug.v1", "args": {"action": "value.at", "kind": "request"}}`

<!-- XOUT_BODY phase=final action=schema role=primary bytes=2877 sha256=73b5ea0c99fbde9e27833eb0a55c1ab40c0590b3444c080c41613cdfd010cb0e -->
```xout
@xdebug.schema.v1
summary:
  action        : value.at
  kind          : request
  schema_path   : schemas/v1/actions/value.at.request.schema.json
  x-purpose     : 统一读取信号集合在一个或多个时间点的值。
  x-how_it_works: 从 signal/list/apb/stream/axi 恰好一个来源建立有序 entry 集合，再按 time/times 逐点采样；stream 表达式同时返回语义 entry 和 namespaced raw alias。
  x-when_to_use : 一次比较单信号、关键列表或协议接口在多个离散时间点的现场。

arguments:
  name              type    required  description
  apb               string  no        Name of a loaded APB interface configuration.
  axi               string  no        Name of a loaded AXI interface configuration.
  clock             string  no        采样、统计或协议检查使用的 clock 信号路径。
  edge              string  no        Clock sampling edge. The schema default is authoritative; negedge often matches monitor semantics.
  list              string  no        Name of a loaded waveform signal list.
  render_time_unit  string  no        Controls only canonical response time rendering: auto, ps, ns, or us. It never changes input parsing, sampling, filtering, or ordering. values=auto|ps|ns|us
  sample_point      string  no        Before/after observation point for posedge or dual sampling; it does not change the raw waveform range. values=before|after
  signal            string  no        Final leaf signal path. Aggregate, array, and struct roots are not expanded automatically.
  slice_hint        object  no        值显示的可选位段提示；不改变被读取的底层 signal。
  stream            string  no        已加载的 stream 配置名称。
  time              string  no        Target sample time. Prefer a canonical string with a unit; a bare number is interpreted as nanoseconds.
  times             array   no        按请求顺序提供的非空且不重复时间列表；同时公开 time 的 action 使用 time 表示单点，使用 times 表示一个或多个点。
  value_format      string  no        返回 LogicValue 的显示格式；不改变比较、采样或底层四态值。 values=hex|bin|dec default=hex

limits:
  name        type     required  description
  timeout_ms  integer  no        Positive public frontend-to-engine request timeout in milliseconds. Omit limits.timeout_ms to disable the public watchdog.

constraints:
  exactly one of: signal / list / apb / stream / axi; exactly one of: time / times; optional: clock, edge, sample_point

examples:
  examples/requests/value.at.basic.json
  examples/requests/value.at.clock.json
  examples/requests/value.at.unknown.json
  examples/requests/value.at.clock_unknown.json
  examples/requests/value.at.missing_value.json
  examples/requests/value.at.xbit.json
  examples/requests/value.at.list.json
```

## 051. `scope.list` / `primary`

- returncode: 0
- elapsed_ms: 120
- bytes: 1107
- sha256: `38fc0c25dc2fffde4fbf8b92910ea48ea8109662527790f5b5cbb6677647f90f`
- request: `{"action": "scope.list", "api_version": "xdebug.v1", "args": {"kind": "all", "level": 1, "path": "ai_complex_top"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=scope.list role=primary bytes=1107 sha256=38fc0c25dc2fffde4fbf8b92910ea48ea8109662527790f5b5cbb6677647f90f -->
```xout
@xdebug.scope.list.v1
summary:
  path                 : ai_complex_top
  level                : 1
  kind                 : all
  include_patterns     : [empty]
  exclude_patterns     : [empty]
  scanned_row_count    : 24
  returned_module_count: 0
  returned_port_count  : 0
  returned_signal_count: 24
  total_module_count   : 0
  total_port_count     : 0
  total_signal_count   : 24
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 24
  returned_count       : 24
  truncation_scopes    : [empty]

signals:
  name             width
  clk              1
  counter_inc      8
  counter_nonmono  8
  event_payload    8
  event_race       1
  event_rdy        1
  event_vld        1
  glitch_sig       1
  hs_data          8
  hs_ready         1
  hs_valid         1
  mixed_xz_bus     8
  paddr            16
  penable          1
  prdata           32
  psel             1
  pwdata           32
  pwrite           1
  rst_n            1
  sig_a            8
  sig_b            8
  stable_sig       1
  stuck_sig        1
  xz_bus           8
```

## 052. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 237
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_c"}, "target": {"daidir": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/simv.daidir", "fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 053. `scope.roots` / `primary`

- returncode: 0
- elapsed_ms: 116
- bytes: 322
- sha256: `55a2b79887a5678f6077161064f8b6d7da692632eea95d6a8369a018cddbca63`
- request: `{"action": "scope.roots", "api_version": "xdebug.v1", "args": {"source": "auto"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=scope.roots role=primary bytes=322 sha256=55a2b79887a5678f6077161064f8b6d7da692632eea95d6a8369a018cddbca63 -->
```xout
@xdebug.scope.roots.v1
summary:
  recommended: active_semantics_tb
  source     : auto
  roots      : 1
  matched    : 1
  wave       : 1
  design     : 1

roots:
  path                 status   sources      wave                 design
  active_semantics_tb  matched  design,wave  active_semantics_tb  active_semantics_tb
```

## 054. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 244
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_disposable_close"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 055. `session.close` / `primary`

- returncode: 0
- elapsed_ms: 195
- bytes: 658
- sha256: `0cce3aa7ea714d879b3e077d1f29afcc539b492961702733ac4d6c36bea68620`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_disposable_close"}}`

<!-- XOUT_BODY phase=final action=session.close role=primary bytes=658 sha256=0cce3aa7ea714d879b3e077d1f29afcc539b492961702733ac4d6c36bea68620 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_disposable_close
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-12b7eeedcd83f8b3.sock
  server_pid : 1640772
  created_at : 1785788283
  last_active: 1785788284
  fsdb_mtime : 1785305001
  fsdb_size  : 9232
  fsdb_dev   : 64770
  fsdb_inode : 53480732
```

## 056. `session.doctor` / `primary`

- returncode: 0
- elapsed_ms: 148
- bytes: 88
- sha256: `2124fd9d04461327832ce03da6bf9b11baaaf6782c7ad73163341f38c7d7f0a2`
- request: `{"action": "session.doctor", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=session.doctor role=primary bytes=88 sha256=2124fd9d04461327832ce03da6bf9b11baaaf6782c7ad73163341f38c7d7f0a2 -->
```xout
@xdebug.session.doctor.v1
summary:
  healthy: true

data:
  message: Session is healthy
```

## 057. `session.gc` / `primary`

- returncode: 0
- elapsed_ms: 344
- bytes: 3279
- sha256: `2ad26a126c31a83a6b01e9d60a5d4d923866df08d3fa8eb499439393ab692254`
- request: `{"action": "session.gc", "api_version": "xdebug.v1", "args": {}}`

<!-- XOUT_BODY phase=final action=session.gc role=primary bytes=3279 sha256=2ad26a126c31a83a6b01e9d60a5d4d923866df08d3fa8eb499439393ab692254 -->
```xout
@xdebug.session.gc.v1
summary:
  before_count : 5
  kept_count   : 5
  removed_count: 0

kept_sessions:
  session_id     mode      transport  server_host  fsdb                                                                                                                                                                                                                        socket_path                                                                                  server_pid  created_at  last_active  fsdb_mtime  fsdb_size  fsdb_dev  fsdb_inode  daidir                                                                                                                                                                                              daidir_mtime  daidir_size  daidir_dev  daidir_inode
  native_xout_p  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.apb_vip/versions/5b0d1be836520bd8421bb4193d12949c5ba4c3098cc94bd1dede3d5a81fb4709-prepare-7hdsu4cf/resources/out/regression/test/apb_vip_test/waves.fsdb       /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-f7e10f18f07ae65d.sock  1640280     1785788269  1785788270   1785305080  21053      64770     53481561
  native_xout_a  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.axi_vip/versions/b7a0d81ad90d77fb97c0da6239e1e69a10671089527be0adf5e7a21e5507c1f0-prepare-21inkxj8/resources/out/regression/test/axi_multi_id_test/waves.fsdb  /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-2ff3d0ff242e4327.sock  1640334     1785788270  1785788278   1785305487  4464084    64770     53481826
  native_xout_w  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb                            /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-4ad5c73dc970c961.sock  1640500     1785788279  1785788284   1785305001  9232       64770     53480732
  native_xout_e  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.xif_event/versions/664ac163a4de5950f40c81bafad04508bf5ea6a1fadbf1eca21aeabe1306ee44-prepare-kh7pipx2/resources/out/waves/xif_event_multi_if_test.fsdb          /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-e799fe8782371102.sock  1640518     1785788280  1785788281   1785305859  12029      64770     53742495
  native_xout_c  combined  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/waves.fsdb                           /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-39188bccaca42ae0.sock  1640751     1785788283  1785788283   1785304981  10908      64770     53220060    /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/simv.daidir  1785304981    4096         64770       53220003
  removed: [empty]
```

## 058. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 254
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_disposable_kill"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 059. `session.kill` / `primary`

- returncode: 0
- elapsed_ms: 188
- bytes: 656
- sha256: `d23b1614cdcfd194108973e70227478d549134112d66317305206c2f9c5f6862`
- request: `{"action": "session.kill", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_disposable_kill"}}`

<!-- XOUT_BODY phase=final action=session.kill role=primary bytes=656 sha256=d23b1614cdcfd194108973e70227478d549134112d66317305206c2f9c5f6862 -->
```xout
@xdebug.session.kill.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_disposable_kill
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-9cdfe61bf12ffb96.sock
  server_pid : 1640806
  created_at : 1785788284
  last_active: 1785788284
  fsdb_mtime : 1785305001
  fsdb_size  : 9232
  fsdb_dev   : 64770
  fsdb_inode : 53480732
```

## 060. `session.list` / `primary`

- returncode: 0
- elapsed_ms: 45
- bytes: 3254
- sha256: `47049b40b9f2302197fbf721e2c95ca21045e63d9feeeaba9389a6498ed07e96`
- request: `{"action": "session.list", "api_version": "xdebug.v1", "args": {}}`

<!-- XOUT_BODY phase=final action=session.list role=primary bytes=3254 sha256=47049b40b9f2302197fbf721e2c95ca21045e63d9feeeaba9389a6498ed07e96 -->
```xout
@xdebug.session.list.v1
summary:
  session_count        : 5
  expired_removed_count: 0

sessions:
  session_id     mode      transport  server_host  fsdb                                                                                                                                                                                                                        socket_path                                                                                  server_pid  created_at  last_active  fsdb_mtime  fsdb_size  fsdb_dev  fsdb_inode  daidir                                                                                                                                                                                              daidir_mtime  daidir_size  daidir_dev  daidir_inode
  native_xout_p  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.apb_vip/versions/5b0d1be836520bd8421bb4193d12949c5ba4c3098cc94bd1dede3d5a81fb4709-prepare-7hdsu4cf/resources/out/regression/test/apb_vip_test/waves.fsdb       /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-f7e10f18f07ae65d.sock  1640280     1785788269  1785788284   1785305080  21053      64770     53481561
  native_xout_a  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.axi_vip/versions/b7a0d81ad90d77fb97c0da6239e1e69a10671089527be0adf5e7a21e5507c1f0-prepare-21inkxj8/resources/out/regression/test/axi_multi_id_test/waves.fsdb  /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-2ff3d0ff242e4327.sock  1640334     1785788270  1785788284   1785305487  4464084    64770     53481826
  native_xout_w  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb                            /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-4ad5c73dc970c961.sock  1640500     1785788279  1785788284   1785305001  9232       64770     53480732
  native_xout_e  waveform  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.xif_event/versions/664ac163a4de5950f40c81bafad04508bf5ea6a1fadbf1eca21aeabe1306ee44-prepare-kh7pipx2/resources/out/waves/xif_event_multi_if_test.fsdb          /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-e799fe8782371102.sock  1640518     1785788280  1785788284   1785305859  12029      64770     53742495
  native_xout_c  combined  uds        eda.ic       /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/waves.fsdb                           /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-39188bccaca42ae0.sock  1640751     1785788283  1785788284   1785304981  10908      64770     53220060    /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/simv.daidir  1785304981    4096         64770       53220003
```

## 061. `session.open` / `primary`

- returncode: 0
- elapsed_ms: 286
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "primary_session_open"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=primary bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 062. `signal.anomaly.inspect` / `primary`

- returncode: 0
- elapsed_ms: 129
- bytes: 562
- sha256: `deed83ad3ad7cc9b6805528a59b5b7abe2dff0fe676441b8921d1ccf1f7491ef`
- request: `{"action": "signal.anomaly.inspect", "api_version": "xdebug.v1", "args": {"checks": [{"type": "unknown_xz"}], "line_limit": 4, "signals": ["xif_event_top.xz_data"], "time_range": {"begin": "0ns", "end": "200ns"}}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=signal.anomaly.inspect role=primary bytes=562 sha256=deed83ad3ad7cc9b6805528a59b5b7abe2dff0fe676441b8921d1ccf1f7491ef -->
```xout
@xdebug.signal.anomaly.inspect.v1
summary:
  signal_count        : 1
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: true

findings:
  type        signal                 severity  time  value
  unknown_xz  xif_event_top.xz_data  warning   65ns  16'hx bits=xxxx_xxxx_xxxx_xxxx

scan_status:
  signal                 status  analysis_complete  change_row_count  finding_count
  xif_event_top.xz_data  ok      true               3                 1
```

## 063. `signal.canonicalize` / `primary`

- returncode: 0
- elapsed_ms: 137
- bytes: 594
- sha256: `b874df7a237f984c7240f7f3f0db73f5b1c5baac126363eae738a4628ed4378d`
- request: `{"action": "signal.canonicalize", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=signal.canonicalize role=primary bytes=594 sha256=b874df7a237f984c7240f7f3f0db73f5b1c5baac126363eae738a4628ed4378d -->
```xout
@xdebug.signal.canonicalize.v1
summary:
  status                : found
  query                 : active_semantics_tb.u_dut.mux_y
  match_count           : 1
  canonicalization_scope: static_design_connectivity

data:
  resolved_path  : active_semantics_tb.u_dut.mux_y
  canonical_path : active_semantics_tb.u_dut.mux_y
  mapping_kind   : identity
  selection_basis: unique_exact_design_match
  scope          : active_semantics_tb.u_dut
  leaf           : mux_y

connection:
  instance : active_semantics_tb.u_dut
  port     : mux_y
  direction: output
  evidence : npi_static_port_connection
```

## 064. `signal.changes` / `primary`

- returncode: 0
- elapsed_ms: 158
- bytes: 808
- sha256: `82b1ebbaaae1a5cfa9c11c6a1b562a4c2603fffec30bac219ac3807b0c99acc7`
- request: `{"action": "signal.changes", "api_version": "xdebug.v1", "args": {"line_limit": 2, "signal": "ai_complex_top.sig_a", "time_range": {"begin": "0ns", "end": "120ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.changes role=primary bytes=808 sha256=82b1ebbaaae1a5cfa9c11c6a1b562a4c2603fffec30bac219ac3807b0c99acc7 -->
```xout
@xdebug.signal.changes.v1
summary:
  signal                 : ai_complex_top.sig_a
  actual_transition_count: 2
  scan_complete          : true
  analysis_complete      : true
  response_truncated     : true
  total_count            : 3
  returned_count         : 2
  value_width_complete   : true

data:
  begin                 : 0ns
  end                   : 120ns
  includes_initial_value: true
  semantic_note         : signal.changes returns value-change rows for timeline inspection. Do not use row counts as sampled high cycles; use signal.statistics.high_cycles for clock-sampled activity.
  initial_value         : 8'h0
  final_value           : 8'h22
  first_change          : 0ns
  last_change           : 65ns
  mode                  : timeline

changes:
  time  value
  0ns   8'h0
  55ns  8'h11
```

## 065. `signal.resolve` / `primary`

- returncode: 0
- elapsed_ms: 107
- bytes: 531
- sha256: `5ec7613753f10b379a6049b25b2fac8f522e7f38698e4ef138f6b7b8ca2d806e`
- request: `{"action": "signal.resolve", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=signal.resolve role=primary bytes=531 sha256=5ec7613753f10b379a6049b25b2fac8f522e7f38698e4ef138f6b7b8ca2d806e -->
```xout
@xdebug.signal.resolve.v1
summary:
  status            : found
  query             : active_semantics_tb.u_dut.mux_y
  scan_complete     : true
  analysis_complete : true
  response_truncated: false
  total_count       : 1
  returned_count    : 1

matches:
  signal                           type  file                                                                                        line
  active_semantics_tb.u_dut.mux_y  reg   /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv  19
```

## 066. `signal.sampled_pulse.inspect` / `primary`

- returncode: 0
- elapsed_ms: 135
- bytes: 1710
- sha256: `046df8eb176367f4327ffb6ed53f4eb1db331e1a36de0076cd61e251d9cf0dd7`
- request: `{"action": "signal.sampled_pulse.inspect", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "line_limit": 5, "time_range": {"begin": "0ns", "end": "200ns"}, "valid": "ai_complex_top.glitch_sig"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.sampled_pulse.inspect role=primary bytes=1710 sha256=046df8eb176367f4327ffb6ed53f4eb1db331e1a36de0076cd61e251d9cf0dd7 -->
```xout
@xdebug.signal.sampled_pulse.inspect.v1
summary:
  sampling_mode                                  : clock_edge
  clock                                          : ai_complex_top.clk
  sample_time_semantics                          : time is sample_time
  sample_count                                   : 20
  sampled_high_cycles                            : 0
  unsampled_valid_pulse_count                    : 1
  payload_risk_count                             : 0
  payload_changed_without_sampled_valid_reporting: summary
  scan_complete                                  : true
  analysis_complete                              : true
  response_truncated                             : false
  total_count                                    : 1
  returned_count                                 : 1
  value_width_complete                           : true

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge                      : negedge
  valid                     : ai_complex_top.glitch_sig
  payloads                  : [empty]
  begin                     : 0ns
  end                       : 200ns
  sampled_low_cycles        : 20
  sampled_unknown_cycles    : 0
  raw_valid_transition_count: 3
  payload_transition_count  : 0

findings:
  type                   severity  raw_begin  raw_end  previous_sample_edge  next_sample_edge  nearest_sample_edge  raw_valid  sampled_valid  reason
  unsampled_valid_pulse  warning   96ns       96.2ns   90ns                  100ns             100ns                1'h1       1'h0           valid was high between sample edges but not high at any sampled edge
```

## 067. `signal.stability` / `primary`

- returncode: 0
- elapsed_ms: 140
- bytes: 578
- sha256: `6cf87dd7d614c029f869df3cf71c828d9ef584c4fed34c8d938e50a6c5f8ec55`
- request: `{"action": "signal.stability", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.stable_sig", "time_range": {"begin": "0ns", "end": "400ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.stability role=primary bytes=578 sha256=6cf87dd7d614c029f869df3cf71c828d9ef584c4fed34c8d938e50a6c5f8ec55 -->
```xout
@xdebug.signal.stability.v1
summary:
  stable                          : true
  change_row_count                : 1
  actual_transition_count         : 0
  scan_stopped_on_first_transition: false
  scan_complete                   : true
  analysis_complete               : true
  response_truncated              : false
  total_count                     : 1
  returned_count                  : 1
  value_width_complete            : true

data:
  signal: ai_complex_top.stable_sig
  begin : 0ns
  end   : 400ns

changes:
  time  value
  0ns   1'h1
  includes_initial_value: true
```

## 068. `signal.statistics` / `primary`

- returncode: 0
- elapsed_ms: 138
- bytes: 1195
- sha256: `9440f5d725df46f29211a88ddfadb56a361ac8f76e3e97dcd8cf9c78588269c9`
- request: `{"action": "signal.statistics", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "signal": "ai_complex_top.hs_valid", "time_range": {"begin": "120ns", "end": "210ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.statistics role=primary bytes=1195 sha256=9440f5d725df46f29211a88ddfadb56a361ac8f76e3e97dcd8cf9c78588269c9 -->
```xout
@xdebug.signal.statistics.v1
summary:
  signal               : ai_complex_top.hs_valid
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  sample_count         : 10
  known_count          : 10
  unknown_count        : 0
  begin                : 120ns
  end                  : 210ns
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 2
  returned_count       : 2
  value_width_complete : true

evidence:
  time   kind          value
  130ns  value_change  1'h1
  200ns  value_change  1'h0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge             : negedge
  transition_count : 2
  first            : 1'h0
  final            : 1'h0
  min              : 1'h0
  max              : 1'h1
  low_cycles       : 3
  high_cycles      : 7
  high_ratio       : 0.7
  first_change_time: 130ns
  last_change_time : 200ns

activity:
  high_burst_count: 1
  first_high_time : 130ns
  last_high_time  : 190ns
  last_fall_time  : 200ns
  max_high_cycles : 7
```

## 069. `signal.xz_verify` / `primary`

- returncode: 0
- elapsed_ms: 137
- bytes: 653
- sha256: `dd19a24d4aa3433f8f4ff794ec223860ac75362649d07a5c0c06b599bfb65b67`
- request: `{"action": "signal.xz_verify", "api_version": "xdebug.v1", "args": {"expected_state": "x", "signal": "ai_complex_top.xz_bus", "time_range": {"begin": "86ns", "end": "94ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.xz_verify role=primary bytes=653 sha256=dd19a24d4aa3433f8f4ff794ec223860ac75362649d07a5c0c06b599bfb65b67 -->
```xout
@xdebug.signal.xz_verify.v1
summary:
  signal              : ai_complex_top.xz_bus
  expected_state      : x
  match_mode          : exact
  verdict             : pass
  always_matched      : true
  checked_value_count : 1
  stop_reason         : window_end
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: true

time_range:
  begin                : 86ns
  end                  : 94ns
  initial_value        : 8'hx bits=xxxx_xxxx
  sample_time_semantics: sample_time is the finalized raw waveform value-change time in the closed interval
```

## 070. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 238
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_s"}, "target": {"fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.stream_v1/versions/5eca27af24084f076f68c6a77c6fe0cb9e0a152332912dbf074cabc3b4600ede-prepare-qrcrom97/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 071. `stream.config.load` / `setup`

- returncode: 0
- elapsed_ms: 138
- bytes: 1754
- sha256: `082f0826afa4d56d66eb64b07bc2de80b169677010703bb05b74af3d000f2789`
- request: `{"action": "stream.config.load", "api_version": "xdebug.v1", "args": {"config_path": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/xdebug/testdata/waveform/stream_v1/config/streams.json", "mode": "replace"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.config.load role=setup bytes=1754 sha256=082f0826afa4d56d66eb64b07bc2de80b169677010703bb05b74af3d000f2789 -->
```xout
@xdebug.stream.config.load.v1
summary:
  loaded: 7
  mode  : replace

streams:
  valid_only
  ready_stream
  bp_stream
  ready_packet
  bp_packet
  ready_bp_packet_negedge
  interleaved_packet

issues:
  stream      severity  code           message
  valid_only  WARNING   CLOCK_COMPLEX  clock expression is not a plain signal; edge detection uses expression dependency changes

validation:
  status  sampling.clock  sampling.edge  sampling.sample_point  packet_rules.packet_enabled  packet_rules.channel_id_valid  packet_rules.allow_interleaving  stream
  ok      clk || 1'b0     posedge        before                 false                        every_beat                     false                            valid_only
  ok      clk             posedge        before                 false                        every_beat                     false                            ready_stream
  ok      clk             posedge        before                 false                        every_beat                     false                            bp_stream
  ok      clk             posedge        before                 true                         every_beat                     false                            ready_packet
  ok      clk             posedge        before                 true                         every_beat                     false                            bp_packet
  ok      clk             negedge                               true                         every_beat                     false                            ready_bp_packet_negedge
  ok      clk             posedge        before                 true                         every_beat                     true                             interleaved_packet
```

## 072. `stream.config.get` / `primary`

- returncode: 0
- elapsed_ms: 117
- bytes: 958
- sha256: `699952b1d0fef9a2713afdb868031cc3d0db63b9a81068b6e3483d322003f6e8`
- request: `{"action": "stream.config.get", "api_version": "xdebug.v1", "args": {"name": "ready_stream"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.config.get role=primary bytes=958 sha256=699952b1d0fef9a2713afdb868031cc3d0db63b9a81068b6e3483d322003f6e8 -->
```xout
@xdebug.stream.config.get.v1
summary:
  name: ready_stream

stream:
  name              : ready_stream
  clock             : clk
  edge              : posedge
  sample_point      : before
  vld               : vld && !flush
  rdy               : rdy
  channel_id        : chid
  channel_id_valid  : every_beat
  allow_interleaving: false
  description       : vld/rdy stream with gated valid, slice, concat, compare, and channel

stream.signals:
  addr_hi : stream_v1_top.ready_addr_hi
  addr_lo : stream_v1_top.ready_addr_lo
  chid    : stream_v1_top.ready_chid
  clk     : stream_v1_top.clk
  cmd     : stream_v1_top.ready_cmd
  data_sig: stream_v1_top.ready_data
  flush   : stream_v1_top.ready_flush
  rdy     : stream_v1_top.ready_rdy
  vld     : stream_v1_top.ready_vld

stream.reset:
  signal  : stream_v1_top.rst_n
  polarity: active_low

stream.beat_fields:
  addr : {addr_hi, addr_lo}
  data : data_sig
  is_wr: cmd == 2'b01
  low8 : data_sig[7:0]
```

## 073. `stream.config.list` / `primary`

- returncode: 0
- elapsed_ms: 138
- bytes: 1189
- sha256: `1a10b2480b41680a1f2a7b5a3885bc94c2d28783de312aedfc69a28c4e3956b8`
- request: `{"action": "stream.config.list", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.config.list role=primary bytes=1189 sha256=1a10b2480b41680a1f2a7b5a3885bc94c2d28783de312aedfc69a28c4e3956b8 -->
```xout
@xdebug.stream.config.list.v1
summary:
  count: 7

streams:
  name                     sampling_mode  clock        edge     handshake   packet   field_count  channel_id_valid  allow_interleaving  sample_point
  bp_packet                clock_edge     clk          posedge  vld/bp      sop/eop  3            every_beat        false               before
  bp_stream                clock_edge     clk          posedge  vld/bp      none     1            every_beat        false               before
  interleaved_packet       clock_edge     clk          posedge  vld/rdy     sop/eop  3            every_beat        true                before
  ready_bp_packet_negedge  clock_edge     clk          negedge  vld/rdy/bp  sop/eop  2            every_beat        false
  ready_packet             clock_edge     clk          posedge  vld/rdy     sop/eop  3            every_beat        false               before
  ready_stream             clock_edge     clk          posedge  vld/rdy     none     4            every_beat        false               before
  valid_only               clock_edge     clk || 1'b0  posedge  vld         none     1            every_beat        false               before
```

## 074. `stream.config.load` / `primary`

- returncode: 0
- elapsed_ms: 92
- bytes: 665
- sha256: `f027eb64dd4adbb8b2bf92bfe5772db39e46f63a094a3d0b3b21d0922a052030`
- request: `{"action": "stream.config.load", "api_version": "xdebug.v1", "args": {"config": {"streams": [{"clock": "clk || 1'b0", "data": "data", "description": "valid-only stream", "edge": "posedge", "name": "native_primary_stream", "reset": {"polarity": "active_low", "signal": "stream_v1_top.rst_n"}, "signals": {"clk": "stream_v1_top.clk", "data": "stream_v1_top.vo_data", "vld": "stream_v1_top.vo_vld"}, "vld": "vld"}]}, "mode": "append"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.config.load role=primary bytes=665 sha256=f027eb64dd4adbb8b2bf92bfe5772db39e46f63a094a3d0b3b21d0922a052030 -->
```xout
@xdebug.stream.config.load.v1
summary:
  loaded: 1
  mode  : append

streams:
  native_primary_stream

issues:
  stream                 severity  code           message
  native_primary_stream  WARNING   CLOCK_COMPLEX  clock expression is not a plain signal; edge detection uses expression dependency changes

validation:
  status  sampling.clock  sampling.edge  sampling.sample_point  packet_rules.packet_enabled  packet_rules.channel_id_valid  packet_rules.allow_interleaving  stream
  ok      clk || 1'b0     posedge        before                 false                        every_beat                     false                            native_primary_stream
```

## 075. `stream.describe` / `primary`

- returncode: 0
- elapsed_ms: 142
- bytes: 2145
- sha256: `b116a3300d15098ba61f3552c2ac3f27a34a623a6beaa41e3b8555f5f540cae3`
- request: `{"action": "stream.describe", "api_version": "xdebug.v1", "args": {"stream": "ready_stream"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.describe role=primary bytes=2145 sha256=b116a3300d15098ba61f3552c2ac3f27a34a623a6beaa41e3b8555f5f540cae3 -->
```xout
@xdebug.stream.describe.v1
summary:
  stream        : ready_stream
  handshake     : vld/rdy
  packet_enabled: false

config:
  name              : ready_stream
  clock             : clk
  edge              : posedge
  sample_point      : before
  vld               : vld && !flush
  rdy               : rdy
  channel_id        : chid
  channel_id_valid  : every_beat
  allow_interleaving: false
  description       : vld/rdy stream with gated valid, slice, concat, compare, and channel

config.signals:
  addr_hi : stream_v1_top.ready_addr_hi
  addr_lo : stream_v1_top.ready_addr_lo
  chid    : stream_v1_top.ready_chid
  clk     : stream_v1_top.clk
  cmd     : stream_v1_top.ready_cmd
  data_sig: stream_v1_top.ready_data
  flush   : stream_v1_top.ready_flush
  rdy     : stream_v1_top.ready_rdy
  vld     : stream_v1_top.ready_vld

config.reset:
  signal  : stream_v1_top.rst_n
  polarity: active_low

config.beat_fields:
  addr  : {addr_hi, addr_lo}
  data  : data_sig
  is_wr : cmd == 2'b01
  low8  : data_sig[7:0]
  issues: [empty]

validation:
  status: ok

validation.signals:
  alias     requested_path               resolved_path                width  status
  addr_hi   stream_v1_top.ready_addr_hi  stream_v1_top.ready_addr_hi  16     ok
  addr_lo   stream_v1_top.ready_addr_lo  stream_v1_top.ready_addr_lo  16     ok
  chid      stream_v1_top.ready_chid     stream_v1_top.ready_chid     2      ok
  clk       stream_v1_top.clk            stream_v1_top.clk            1      ok
  cmd       stream_v1_top.ready_cmd      stream_v1_top.ready_cmd      2      ok
  data_sig  stream_v1_top.ready_data     stream_v1_top.ready_data     32     ok
  flush     stream_v1_top.ready_flush    stream_v1_top.ready_flush    1      ok
  rdy       stream_v1_top.ready_rdy      stream_v1_top.ready_rdy      1      ok
  vld       stream_v1_top.ready_vld      stream_v1_top.ready_vld      1      ok

validation.sampling:
  clock       : clk
  edge        : posedge
  sample_point: before

validation.packet_rules:
  packet_enabled    : false
  channel_id_valid  : every_beat
  allow_interleaving: false

semantics:
  transfer: vld/rdy
  stall   : enabled
```

## 076. `stream.export` / `primary`

- returncode: 0
- elapsed_ms: 872
- bytes: 1315
- sha256: `4d6181ade4b402525b2f20b884b9565b9e80e35c0a66e8d9168660353eef60de`
- request: `{"action": "stream.export", "api_version": "xdebug.v1", "args": {"cache_scope": "full", "kind": "transfer", "output": {"file_format": "tsv", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/stream.tsv"}, "stream": "ready_stream", "time_range": {"begin": "0ns", "end": "1us"}}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.export role=primary bytes=1315 sha256=4d6181ade4b402525b2f20b884b9565b9e80e35c0a66e8d9168660353eef60de -->
```xout
@xdebug.stream.export.v1
summary:
  stream                      : ready_stream
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : false
  clock_edges                 : 100
  vld_cycles                  : 88
  transfer_count              : 71
  stall_cycles                : 17
  stall_windows               : 17
  complete_packet_count       : 0
  partial_packet_count        : 0
  packet_count_status         : not_configured
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 71
  returned_count              : 71
  first_transfer_time         : 75ns
  last_transfer_time          : 995ns
  first_stall_time            : 115ns
  last_stall_time             : 965ns
  status                      : written
  output_written              : true
  row_count                   : 71
  line_limit                  : 16
  kind                        : transfer
```

## 077. `stream.query` / `primary`

- returncode: 0
- elapsed_ms: 1117
- bytes: 2308
- sha256: `3b3b4023c3b0f061970b2fa3d21db7acfed431ea342bb4330515952e6bf1b73a`
- request: `{"action": "stream.query", "api_version": "xdebug.v1", "args": {"packet_index": 3, "query": "packet_at", "stream": "ready_packet", "time_range": {"begin": "0ns", "end": "1us"}}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.query role=primary bytes=2308 sha256=3b3b4023c3b0f061970b2fa3d21db7acfed431ea342bb4330515952e6bf1b73a -->
```xout
@xdebug.stream.query.v1
summary:
  stream                      : ready_packet
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : true
  clock_edges                 : 100
  vld_cycles                  : 94
  transfer_count              : 94
  stall_cycles                : 0
  stall_windows               : 0
  complete_packet_count       : 23
  partial_packet_count        : 1
  packet_count_status         : ambiguous
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 1
  returned_count              : 1
  truncation_scopes           : [empty]

requested_range:
  begin: 0ns
  end  : 1000ns

scanned_range:
  begin               : 5ns
  end                 : 995ns
  first_transfer_time : 65ns
  last_transfer_time  : 995ns
  query               : packet_at
  filter_applied      : false
  value_width_complete: true
  width_diagnostics   : [empty]
  found               : true

packet:
  packet_index            : 3
  start_cycle             : 18
  end_cycle               : 21
  start_time              : 185ns
  end_time                : 215ns
  beat_count              : 4
  partial_begin           : false
  partial_end             : false
  packet_stable_fields    : opcode=8'ha3
  packet_stable_mismatches: [empty]
  first_fields            : data=32'h4000000c seq=16'hc
  last_fields             : data=32'h4000000f seq=16'hf

packet.beat_fields_preview:
  tail              : [empty]
  scan_complete     : true
  analysis_complete : true
  response_truncated: false
  total_count       : 4
  returned_count    : 4
  truncation_scopes : [empty]

packet.beat_fields_preview.head:
  cycle  time   beat_index  fields
  18     185ns  0           data=32'h4000000c seq=16'hc
  19     195ns  1           data=32'h4000000d seq=16'hd
  20     205ns  2           data=32'h4000000e seq=16'he
  21     215ns  3           data=32'h4000000f seq=16'hf
```

## 078. `stream.validate` / `primary`

- returncode: 0
- elapsed_ms: 137
- bytes: 1407
- sha256: `75d0680a4f2adbd91230eab42edc95723999a368efddb287121022080848ea0a`
- request: `{"action": "stream.validate", "api_version": "xdebug.v1", "args": {"cache_scope": "full", "dynamic": true, "stream": "ready_stream", "time_range": {"begin": "0ns", "end": "1us"}}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.validate role=primary bytes=1407 sha256=75d0680a4f2adbd91230eab42edc95723999a368efddb287121022080848ea0a -->
```xout
@xdebug.stream.validate.v1
summary:
  stream                    : ready_stream
  ok                        : true
  static_validation_complete: true
  dynamic_requested         : true
  scan_complete             : true
  analysis_complete         : true
  response_truncated        : false
  total_count               : 0
  returned_count            : 0

data:
  issues: [empty]

dynamic:
  stream                      : ready_stream
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : false
  clock_edges                 : 100
  vld_cycles                  : 88
  transfer_count              : 71
  stall_cycles                : 17
  stall_windows               : 17
  complete_packet_count       : 0
  partial_packet_count        : 0
  packet_count_status         : not_configured
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  first_transfer_time         : 75ns
  last_transfer_time          : 995ns
  first_stall_time            : 115ns
  last_stall_time             : 965ns

dynamic.requested_range:
  begin: 0ns
  end  : 1000ns

dynamic.scanned_range:
  begin: 5ns
  end  : 995ns
```

## 079. `trace.active_driver` / `primary`

- returncode: 0
- elapsed_ms: 114
- bytes: 960
- sha256: `bb35686965188a76981ee8fcfd016fed1fe1fd6c59ce3132afc938376d2e0980`
- request: `{"action": "trace.active_driver", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y", "time": "26ns"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.active_driver role=primary bytes=960 sha256=bb35686965188a76981ee8fcfd016fed1fe1fd6c59ce3132afc938376d2e0980 -->
```xout
@xdebug.trace.active_driver.v1
summary:
  signal            : active_semantics_tb.u_dut.mux_y
  time              : 26ns
  active_time       : 22ns
  termination       : assignment
  termination_detail: assignment
  scan_complete     : true
  analysis_complete : true
  response_truncated: false
  total_count       : 2
  returned_count    : 2
  truncation_scopes : [empty]

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:45-48
   42 |   end
   43 | 
   44 |   always_comb begin
>  45 |     if (sel)
   46 |       mux_y = data_a;                 // MUX_ACTIVE_A
   47 |     else
>  48 |       mux_y = data_b;                 // MUX_ACTIVE_B
   49 |   end
   50 | 
   51 |   always_ff @(posedge clk or negedge rst_n) begin

active_signals:
  line  signal_path
  48    active_semantics_tb.u_dut.data_b -> active_semantics_tb.u_dut.mux_y
  45    active_semantics_tb.u_dut.sel -> active_semantics_tb.u_dut.mux_y
```

## 080. `trace.active_driver_chain` / `primary`

- returncode: 0
- elapsed_ms: 149
- bytes: 1424
- sha256: `04e8d4a857b07eac33662176ae3a59470f701bbe53f1e94ac7be69a55382444c`
- request: `{"action": "trace.active_driver_chain", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y", "time": "26ns"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.active_driver_chain role=primary bytes=1424 sha256=04e8d4a857b07eac33662176ae3a59470f701bbe53f1e94ac7be69a55382444c -->
```xout
@xdebug.trace.active_driver_chain.v1
summary:
  signal              : active_semantics_tb.u_dut.mux_y
  time                : 26ns
  termination         : unresolved
  termination_detail  : unresolved
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 2
  returned_count      : 2
  value_width_complete: false
  truncation_scopes   : [empty]

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:48
   45 |     if (sel)
   46 |       mux_y = data_a;                 // MUX_ACTIVE_A
   47 |     else
>  48 |       mux_y = data_b;                 // MUX_ACTIVE_B
   49 |   end
   50 | 
   51 |   always_ff @(posedge clk or negedge rst_n) begin

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     0    26ns  root      48    active_semantics_tb.u_dut.data_b -> active_semantics_tb.u_dut.mux_y

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:169
  166 |     req0 = 1'b0;
  167 |     req1 = 1'b1;         // arb_q captures payload1 at 25ns
  168 |     data_a = 8'hA1;
> 169 |     data_b = 8'hB2;
  170 |     payload = 8'h11;
  171 |     payload0 = 8'hC1;
  172 |     payload1 = 8'hD1;

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     1    22ns  driver    169   active_semantics_tb.data_b -> active_semantics_tb.u_dut.data_b
```

## 081. `trace.driver` / `primary`

- returncode: 0
- elapsed_ms: 129
- bytes: 957
- sha256: `32e4e14997026b35f7da2e6acae558d49f39358dc1cf4f29ed74259a0397e536`
- request: `{"action": "trace.driver", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.driver role=primary bytes=957 sha256=32e4e14997026b35f7da2e6acae558d49f39358dc1cf4f29ed74259a0397e536 -->
```xout
@xdebug.trace.driver.v1
summary:
  signal            : active_semantics_tb.u_dut.mux_y
  mode              : driver
  scan_complete     : true
  analysis_complete : false
  response_truncated: false
  total_count       : 3
  returned_count    : 3

truncation_scopes:
  analysis_trace_resolution

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:45-48
   42 |   end
   43 | 
   44 |   always_comb begin
>  45 |     if (sel)
>  46 |       mux_y = data_a;                 // MUX_ACTIVE_A
   47 |     else
>  48 |       mux_y = data_b;                 // MUX_ACTIVE_B
   49 |   end
   50 | 
   51 |   always_ff @(posedge clk or negedge rst_n) begin

active_signals:
  line  signal_path
  46    active_semantics_tb.u_dut.data_a -> active_semantics_tb.u_dut.mux_y
  48    active_semantics_tb.u_dut.data_b -> active_semantics_tb.u_dut.mux_y
  45    active_semantics_tb.u_dut.sel -> active_semantics_tb.u_dut.mux_y
```

## 082. `trace.load` / `primary`

- returncode: 0
- elapsed_ms: 128
- bytes: 768
- sha256: `c34f9fbad2aca0e2e12efefac4286f4cee72806665ec48d469afa5ea6745023d`
- request: `{"action": "trace.load", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.load role=primary bytes=768 sha256=c34f9fbad2aca0e2e12efefac4286f4cee72806665ec48d469afa5ea6745023d -->
```xout
@xdebug.trace.load.v1
summary:
  signal            : active_semantics_tb.u_dut.mux_y
  mode              : load
  scan_complete     : true
  analysis_complete : false
  response_truncated: false
  total_count       : 1
  returned_count    : 1

truncation_scopes:
  analysis_trace_resolution

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:19
   16 |   input  logic [7:0] payload1,
   17 |   input  logic [7:0] chain_src,
   18 |   output logic [7:0] q_en,
>  19 |   output logic [7:0] mux_y,
   20 |   output logic [7:0] handshake_q,
   21 |   output logic [7:0] arb_q,
   22 |   output logic [7:0] chain_out,

active_signals:
  line  signal_path
  19    active_semantics_tb.u_dut.mux_y -> active_semantics_tb.mux_y
```

## 083. `session.open` / `setup`

- returncode: 0
- elapsed_ms: 237
- bytes: 50
- sha256: `801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4`
- request: `{"action": "session.open", "api_version": "xdebug.v1", "args": {"name": "native_xout_x"}, "target": {"daidir": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.trace_x_xprop/versions/8efd40845b015e9729763fe8fad3cff590e4399458e80b01b29874d830af18da-prepare-xe7akjqx/resources/out/simv.daidir", "fsdb": "/home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/.xverif-test-cache/fixtures/xdebug.trace_x_xprop/versions/8efd40845b015e9729763fe8fad3cff590e4399458e80b01b29874d830af18da-prepare-xe7akjqx/resources/out/waves.fsdb"}}`

<!-- XOUT_BODY phase=final action=session.open role=setup bytes=50 sha256=801dae73579a41aae7974fb6f2a87487c435c4d93f3e58f31d52451fd6af19f4 -->
```xout
@xdebug.session.open.v1
summary:
  status: opened
```

## 084. `trace.x_origin` / `primary`

- returncode: 0
- elapsed_ms: 164
- bytes: 3267
- sha256: `310b88bc25fb0d87e27049c7ea6ca40d8393a80f2b711e313a54d721e6f7dff6`
- request: `{"action": "trace.x_origin", "api_version": "xdebug.v1", "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "hex"}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=trace.x_origin role=primary bytes=3267 sha256=310b88bc25fb0d87e27049c7ea6ca40d8393a80f2b711e313a54d721e6f7dff6 -->
```xout
@xdebug.trace.x_origin.v1
summary:
  signal               : trace_x_xprop_tb.observed
  query_time           : 18ns
  termination          : origin_found
  evidence_status      : best_effort
  chain_count          : 1
  completed_chain_count: 1
  limited_chain_count  : 0
  hop_count            : 8
  origin_count         : 1
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 1
  returned_count       : 1
  value_width_complete : true
  truncation_scopes    : [empty]

query:
  query_time: 18ns
  value     : 8'hxx
  x_mask    : 8'b10011001

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:40-43
   37 |     if (!rst_n)
   38 |       observed_q <= '0;
   39 |     else
>  40 |       observed_q <= bus.data;
   41 |   end
   42 | 
>  43 |   always_comb observed = observed_q;
   44 | endmodule
   45 | 
   46 | module trace_x_alias_source(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     0    15ns          15ns         root      43    trace_x_xprop_tb.observed
  c0     1    15ns          15ns         rhs       40    trace_x_xprop_tb.u_sink.observed_q

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:6
    3 | interface trace_x_if(input logic clk);
    4 |   logic [7:0] data;
    5 |   modport source(output data, input clk);
>   6 |   modport sink(input data, input clk);
    7 | endinterface
    8 | 
    9 | module trace_x_source(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     2    10ns          10ns         rhs       6     trace_x_xprop_tb.u_sink.bus.data

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:24-27
   21 |     if (sel)
   22 |       stage1 = stage0;
   23 |     else
>  24 |       stage1 = alternate_data;
   25 |   end
   26 | 
>  27 |   always_comb bus.data = stage1;
   28 | endmodule
   29 | 
   30 | module trace_x_sink(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     3    10ns          10ns         port      27    trace_x_xprop_tb.link.data
  c0     4    10ns          10ns         port      27    trace_x_xprop_tb.link.source.data
  c0     5    10ns          10ns         rhs       24    trace_x_xprop_tb.u_source.stage1

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:171
  168 | 
  169 |     #7 rst_n = 1'b1;
  170 |     #3 begin
> 171 |       sel = 1'bx;              // tmerge: two different branches produce X
  172 |       multi_rhs_a = 8'hxx;     // two simultaneous RHS X sources
  173 |       multi_rhs_b = 8'hxx;
  174 |       ctrl_x = 1'bx;           // control and selected RHS are both X

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     6    10ns          10ns         control   171   trace_x_xprop_tb.u_source.sel
  c0     7    10ns          10ns         port      171   trace_x_xprop_tb.sel

chains:
  chain  status        current_signal        current_x_onset_time  value        reason
  c0     origin_found  trace_x_xprop_tb.sel  10ns                  1'hx bits=x  candidate_x_source
```

## 085. `value.at` / `primary`

- returncode: 0
- elapsed_ms: 177
- bytes: 101
- sha256: `f73705a07e913aa95c8c0f8eebc4bac5e6a2050de440057f9d936e83aa9b90de`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.sig_a", "times": ["75ns", "95ns"], "value_format": "hex"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=value.at role=primary bytes=101 sha256=f73705a07e913aa95c8c0f8eebc4bac5e6a2050de440057f9d936e83aa9b90de -->
```xout
@xdebug.value.at.v1
values:
  name                  75ns   95ns
  ai_complex_top.sig_a  8'h22  8'h22
```

## 086. `verify.conditions` / `primary`

- returncode: 0
- elapsed_ms: 129
- bytes: 857
- sha256: `746abce87927da529d404179108813dc06b176fcb84e92594d62bfc9d8c2092c`
- request: `{"action": "verify.conditions", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "conditions": [{"expr": "a == 8'hff"}], "signals": {"a": "ai_complex_top.sig_a"}, "time": "95ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=verify.conditions role=primary bytes=857 sha256=746abce87927da529d404179108813dc06b176fcb84e92594d62bfc9d8c2092c -->
```xout
@xdebug.verify.conditions.v1
summary:
  time                : 95ns
  execution_ok        : true
  verdict             : fail
  condition_count     : 1
  all_passed          : false
  passed              : 0
  failed              : 1
  unknown             : 0
  value_width_complete: true

checks:
  time  expr        known  status  pass   value
  95ns  a == 8'hff  true   fail    false  1'h0

clock_context:
  clock                           : ai_complex_top.clk
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false
  requested_time                  : 95ns
  requested_any_edge_hit          : false
  requested_target_edge_hit       : false
  previous_sample_time            : 90ns
  bracket_complete                : false

clock_context.requested_sampling:
  edge: negedge

clock_context.effective_sampling:
  edge: negedge
```

## 087. `waveform.cursor.set` / `setup`

- returncode: 0
- elapsed_ms: 117
- bytes: 180
- sha256: `7d0f88b6136a069f5948a080a428308918e0acf1e6f15082cbff94e8b3642e49`
- request: `{"action": "waveform.cursor.set", "api_version": "xdebug.v1", "args": {"name": "mark_delete", "time": "75ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.set role=setup bytes=180 sha256=7d0f88b6136a069f5948a080a428308918e0acf1e6f15082cbff94e8b3642e49 -->
```xout
@xdebug.waveform.cursor.set.v1
summary:
  name  : mark_delete
  time  : 75ns
  status: set
  active: true

resolved_time:
  source: 75ns
  time  : 75ns

metadata:
  origin: manual
```

## 088. `waveform.cursor.delete` / `primary`

- returncode: 0
- elapsed_ms: 117
- bytes: 101
- sha256: `59bf99b00ace9f13a7ef4feb05b3ccc2515c3adce1a94cc790ceb537985f29b4`
- request: `{"action": "waveform.cursor.delete", "api_version": "xdebug.v1", "args": {"name": "mark_delete"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.delete role=primary bytes=101 sha256=59bf99b00ace9f13a7ef4feb05b3ccc2515c3adce1a94cc790ceb537985f29b4 -->
```xout
@xdebug.waveform.cursor.delete.v1
summary:
  status : deleted
  name   : mark_delete
  deleted: true
```

## 089. `waveform.cursor.set` / `setup`

- returncode: 0
- elapsed_ms: 120
- bytes: 177
- sha256: `26e183e4d55e02b4cf02aa3c31ae2275ec9c79846d8e612d6cb7ae74d4cca702`
- request: `{"action": "waveform.cursor.set", "api_version": "xdebug.v1", "args": {"name": "mark_get", "time": "75ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.set role=setup bytes=177 sha256=26e183e4d55e02b4cf02aa3c31ae2275ec9c79846d8e612d6cb7ae74d4cca702 -->
```xout
@xdebug.waveform.cursor.set.v1
summary:
  name  : mark_get
  time  : 75ns
  status: set
  active: true

resolved_time:
  source: 75ns
  time  : 75ns

metadata:
  origin: manual
```

## 090. `waveform.cursor.get` / `primary`

- returncode: 0
- elapsed_ms: 125
- bytes: 118
- sha256: `b4b37c93b48c206c689f5613447b5484e2e3061dffa2295809c6f15ad07a665d`
- request: `{"action": "waveform.cursor.get", "api_version": "xdebug.v1", "args": {"name": "mark_get"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.get role=primary bytes=118 sha256=b4b37c93b48c206c689f5613447b5484e2e3061dffa2295809c6f15ad07a665d -->
```xout
@xdebug.waveform.cursor.get.v1
summary:
  name  : mark_get
  time  : 75ns
  status: found

metadata:
  origin: manual
```

## 091. `waveform.cursor.set` / `setup`

- returncode: 0
- elapsed_ms: 121
- bytes: 182
- sha256: `9b9b0d1bdae37f456519405d387b08720c37fe6c8beed4187a56b5527ed5e100`
- request: `{"action": "waveform.cursor.set", "api_version": "xdebug.v1", "args": {"name": "mark_for_list", "time": "75ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.set role=setup bytes=182 sha256=9b9b0d1bdae37f456519405d387b08720c37fe6c8beed4187a56b5527ed5e100 -->
```xout
@xdebug.waveform.cursor.set.v1
summary:
  name  : mark_for_list
  time  : 75ns
  status: set
  active: true

resolved_time:
  source: 75ns
  time  : 75ns

metadata:
  origin: manual
```

## 092. `waveform.cursor.list` / `primary`

- returncode: 0
- elapsed_ms: 138
- bytes: 302
- sha256: `98074ae98cd2dc899e906411fdb323a602fedc85ad4e8c51f17139eb0a764fe2`
- request: `{"action": "waveform.cursor.list", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.list role=primary bytes=302 sha256=98074ae98cd2dc899e906411fdb323a602fedc85ad4e8c51f17139eb0a764fe2 -->
```xout
@xdebug.waveform.cursor.list.v1
summary:
  cursor_count : 2
  active_cursor: mark_for_list

cursors:
  name           time  note  origin  clock  created_at  updated_at
  mark_get       75ns        manual         1785788291  1785788291
  mark_for_list  75ns        manual         1785788291  1785788291
```

## 093. `waveform.cursor.set` / `primary`

- returncode: 0
- elapsed_ms: 132
- bytes: 181
- sha256: `8c1072d673f4e061d81e419a43e8d0e21df83cb53e04e19ab5baa597ae2f6b14`
- request: `{"action": "waveform.cursor.set", "api_version": "xdebug.v1", "args": {"name": "mark_primary", "time": "75ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.set role=primary bytes=181 sha256=8c1072d673f4e061d81e419a43e8d0e21df83cb53e04e19ab5baa597ae2f6b14 -->
```xout
@xdebug.waveform.cursor.set.v1
summary:
  name  : mark_primary
  time  : 75ns
  status: set
  active: true

resolved_time:
  source: 75ns
  time  : 75ns

metadata:
  origin: manual
```

## 094. `waveform.cursor.set` / `setup`

- returncode: 0
- elapsed_ms: 116
- bytes: 177
- sha256: `1f84cdf3e567a52744003b46fc200058841c911d3fd15ca9c99d592ff3efed7c`
- request: `{"action": "waveform.cursor.set", "api_version": "xdebug.v1", "args": {"name": "mark_use", "time": "75ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.set role=setup bytes=177 sha256=1f84cdf3e567a52744003b46fc200058841c911d3fd15ca9c99d592ff3efed7c -->
```xout
@xdebug.waveform.cursor.set.v1
summary:
  name  : mark_use
  time  : 75ns
  status: set
  active: true

resolved_time:
  source: 75ns
  time  : 75ns

metadata:
  origin: manual
```

## 095. `waveform.cursor.use` / `primary`

- returncode: 0
- elapsed_ms: 112
- bytes: 140
- sha256: `c725b84a7a395887e7a38b2490f17c603e25cccaa5f8043472bdd253cccb449f`
- request: `{"action": "waveform.cursor.use", "api_version": "xdebug.v1", "args": {"name": "mark_use"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.use role=primary bytes=140 sha256=c725b84a7a395887e7a38b2490f17c603e25cccaa5f8043472bdd253cccb449f -->
```xout
@xdebug.waveform.cursor.use.v1
summary:
  status       : active
  active_cursor: mark_use
  time         : 75ns

metadata:
  origin: manual
```

## 096. `window.verify` / `primary`

- returncode: 0
- elapsed_ms: 135
- bytes: 919
- sha256: `e4d501dfb7671826e9670ac17eabf461f11d4b121c028119e9c860f808b51445`
- request: `{"action": "window.verify", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "conditions": [{"expr": "valid || !valid", "mode": "always"}], "signals": {"valid": "ai_complex_top.hs_valid"}, "time_range": {"begin": "140ns", "end": "175ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=window.verify role=primary bytes=919 sha256=e4d501dfb7671826e9670ac17eabf461f11d4b121c028119e9c860f808b51445 -->
```xout
@xdebug.window.verify.v1
summary:
  execution_ok         : true
  verdict              : pass
  all_passed           : true
  sample_count         : 4
  failed_samples       : 0
  unknown_samples      : 0
  proof_begin          : 140ns
  proof_end            : 175ns
  stop_reason          : window_end
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 0
  returned_count       : 0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge: negedge

conditions:
  expr           mode    passed  pass_samples  failed_samples  unknown_samples
  valid||!valid  always  true    4             0               0
  findings: [empty]
```

## 097. `trace.active_driver_chain` / `protection:012`

- returncode: 0
- elapsed_ms: 149
- bytes: 1243
- sha256: `f507e12613367fd9c651184ed2074ef19de09e65cab6873075651dcc54d83c0d`
- request: `{"action": "trace.active_driver_chain", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.ambiguous_rhs_out", "time": "26ns"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.active_driver_chain role=protection:012 bytes=1243 sha256=f507e12613367fd9c651184ed2074ef19de09e65cab6873075651dcc54d83c0d -->
```xout
@xdebug.trace.active_driver_chain.v1
summary:
  signal              : active_semantics_tb.u_dut.ambiguous_rhs_out
  time                : 26ns
  termination         : ambiguous
  termination_detail  : multiple_rhs_sources
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: false
  truncation_scopes   : [empty]

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:31
   28 | 
   29 |   assign chain_mid = chain_src;       // CHAIN_MID_ASSIGN
   30 |   assign chain_out = chain_mid;       // CHAIN_OUT_ASSIGN
>  31 |   assign ambiguous_rhs_out = data_a ^ data_b; // AMBIGUOUS_RHS_ASSIGN
   32 |   assign multiple_driver_out = data_a;        // MULTIPLE_DRIVER_A
   33 |   assign multiple_driver_out = data_b ^ 8'h10; // MULTIPLE_DRIVER_B
   34 | 

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     0    26ns  root      31    active_semantics_tb.u_dut.ambiguous_rhs_out

ambiguous_rhs_samples:
  signal                            time  before  after
  active_semantics_tb.u_dut.data_a  22ns  8'ha0   8'ha1
  active_semantics_tb.u_dut.data_b  22ns  8'hb0   8'hb2
```

## 098. `trace.active_driver_chain` / `protection:013`

- returncode: 0
- elapsed_ms: 152
- bytes: 1804
- sha256: `a8a9bd19cdf4bd70f4e3ed28ae79c8271140b6d67a085a02bc654eca891e3302`
- request: `{"action": "trace.active_driver_chain", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.chain_out", "time": "26ns"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.active_driver_chain role=protection:013 bytes=1804 sha256=a8a9bd19cdf4bd70f4e3ed28ae79c8271140b6d67a085a02bc654eca891e3302 -->
```xout
@xdebug.trace.active_driver_chain.v1
summary:
  signal              : active_semantics_tb.u_dut.chain_out
  time                : 26ns
  termination         : assignment
  termination_detail  : constant_or_no_rhs_signal
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 4
  returned_count      : 4
  value_width_complete: false
  truncation_scopes   : [empty]

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:29-30
   26 | 
   27 |   logic [7:0] chain_mid;
   28 | 
>  29 |   assign chain_mid = chain_src;       // CHAIN_MID_ASSIGN
>  30 |   assign chain_out = chain_mid;       // CHAIN_OUT_ASSIGN
   31 |   assign ambiguous_rhs_out = data_a ^ data_b; // AMBIGUOUS_RHS_ASSIGN
   32 |   assign multiple_driver_out = data_a;        // MULTIPLE_DRIVER_A
   33 |   assign multiple_driver_out = data_b ^ 8'h10; // MULTIPLE_DRIVER_B

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     0    26ns  root      30    active_semantics_tb.u_dut.chain_mid -> active_semantics_tb.u_dut.chain_out
  c0     1    22ns  driver    29    active_semantics_tb.u_dut.chain_src -> active_semantics_tb.u_dut.chain_mid

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:173
  170 |     payload = 8'h11;
  171 |     payload0 = 8'hC1;
  172 |     payload1 = 8'hD1;
> 173 |     chain_src = 8'h31;    // CHAIN_SRC_DRIVE
  174 | 
  175 |     #10;
  176 |     en = 1'b1;           // q_en captures new data_a at 35ns

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     2    22ns  driver    173   active_semantics_tb.chain_src -> active_semantics_tb.u_dut.chain_src
  c0     3    22ns  driver    173   active_semantics_tb.chain_src
```

## 099. `not.a.real.action` / `error:unknown-action`

- returncode: 1
- elapsed_ms: 50
- bytes: 309
- sha256: `ae6d50970066f5f62b3d6d150632d251985017a1d8041ac11c7402c41ae00d4e`
- request: `{"action": "not.a.real.action", "api_version": "xdebug.v1"}`

<!-- XOUT_BODY phase=final action=not.a.real.action role=error:unknown-action bytes=309 sha256=ae6d50970066f5f62b3d6d150632d251985017a1d8041ac11c7402c41ae00d4e -->
```xout
@xdebug.error.v1

action          : not.a.real.action
code            : UNKNOWN_ACTION
message         : unknown action: not.a.real.action
recoverable     : true
error_layer     : handler
invalid_arg     : action
received        : not.a.real.action
available_values: ["actions","axi.analysis","expr.eval_at"]
```

## 100. `schema` / `error:schema-missing-field`

- returncode: 1
- elapsed_ms: 58
- bytes: 436
- sha256: `39bd6a0c52779cd447c80be96e16e3ddd89c6f54c61e8229a6090f224a35f119`
- request: `{"action": "schema", "api_version": "xdebug.v1", "args": {}}`

<!-- XOUT_BODY phase=final action=schema role=error:schema-missing-field bytes=436 sha256=39bd6a0c52779cd447c80be96e16e3ddd89c6f54c61e8229a6090f224a35f119 -->
```xout
@xdebug.error.v1

action       : schema
code         : INVALID_REQUEST
message      : invalid parameter args.action: required property 'action' not found in object; expected type "string"
recoverable  : true
error_layer  : schema
invalid_arg  : args.action
expected     : type "string"
received_type: missing

correct_example:
  json: {"api_version":"xdebug.v1","action":"schema","args":{"action":"signal.statistics","kind":"request"}}
```

## 101. `session.doctor` / `error:session-not-found`

- returncode: 1
- elapsed_ms: 60
- bytes: 164
- sha256: `f920b3aebe5ff1269b357203185374ce503c3dc636e74e74b0e2845b79109d0c`
- request: `{"action": "session.doctor", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "missing"}}`

<!-- XOUT_BODY phase=final action=session.doctor role=error:session-not-found bytes=164 sha256=f920b3aebe5ff1269b357203185374ce503c3dc636e74e74b0e2845b79109d0c -->
```xout
@xdebug.error.v1

action     : session.doctor
code       : SESSION_NOT_FOUND
message    : session not found: missing
recoverable: true
error_layer: session_manager
```

## 102. `expr.normalize` / `error:expression-syntax`

- returncode: 1
- elapsed_ms: 107
- bytes: 472
- sha256: `b504f051cb25bde7f906d4d0f5b1688bba326950057d3a8b45dfe53caf61c7b9`
- request: `{"action": "expr.normalize", "api_version": "xdebug.v1", "args": {"expr": "valid &&"}}`

<!-- XOUT_BODY phase=final action=expr.normalize role=error:expression-syntax bytes=472 sha256=b504f051cb25bde7f906d4d0f5b1688bba326950057d3a8b45dfe53caf61c7b9 -->
```xout
@xdebug.error.v1

action     : expr.normalize
code       : EXPR_SYNTAX_INVALID
message    : expression ends with operator '&&'
recoverable: true
error_layer: handler
invalid_arg: args.expr
expected   : balanced expression with complete operands and operators
received   : valid &&

correct_example:
  json: {"api_version":"xdebug.v1","action":"expr.normalize","args":{"expr":"valid && ready"}}

next_actions:
  Fix the expression syntax before using it for debug queries.
```

## 103. `value.at` / `error:signal-not-found`

- returncode: 1
- elapsed_ms: 120
- bytes: 595
- sha256: `7e6a5c42e9127368cda7257c66ecec412a668bd20af94a36e4ad0ced9a6a1e39`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.no_such", "time": "10ns"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=value.at role=error:signal-not-found bytes=595 sha256=7e6a5c42e9127368cda7257c66ecec412a668bd20af94a36e4ad0ced9a6a1e39 -->
```xout
@xdebug.error.v1

action          : value.at
code            : SIGNAL_NOT_FOUND
message         : signal not found: ai_complex_top.no_such
recoverable     : true
error_layer     : handler
invalid_arg     : args.signal
expected        : existing waveform signal path
missing_name    : ai_complex_top.no_such
missing_resource: signal

correct_example:
  json: {"action":"value.at","api_version":"xdebug.v1","args":{"clock":"top.u.clk","signal":"top.u.valid","time":"10ns"},"target":{"session_id":"case_a"}}

next_actions:
  Use scope.list or signal.resolve to find the exact waveform signal path.
```

## 104. `signal.changes` / `error:invalid-time`

- returncode: 1
- elapsed_ms: 112
- bytes: 449
- sha256: `812f2c5e5dd19df67d9c1dd32ec61ffdeacac436ad2379094ae5e8d637b14de0`
- request: `{"action": "signal.changes", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.sig_a", "time_range": {"begin": "bad", "end": "10ns"}}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.changes role=error:invalid-time bytes=449 sha256=812f2c5e5dd19df67d9c1dd32ec61ffdeacac436ad2379094ae5e8d637b14de0 -->
```xout
@xdebug.error.v1

action     : signal.changes
code       : INVALID_ARGUMENT
message    : Invalid time 'bad'
recoverable: true
error_layer: handler
invalid_arg: args.time_range.begin
expected   : time string such as 10ns, 100ps, or max for end

correct_example:
  json: {"action":"signal.changes","api_version":"xdebug.v1","args":{"mode":"timeline","signal":"top.u.ready","time_range":{"begin":"0ns","end":"100ns"}},"target":{"session_id":"case_a"}}
```

## 105. `stream.query` / `error:config-not-found`

- returncode: 1
- elapsed_ms: 212
- bytes: 753
- sha256: `07340ac1a2e4873129c0352bd2ddd667c2a5528f3236239b81fe56a08d315068`
- request: `{"action": "stream.query", "api_version": "xdebug.v1", "args": {"query": "summary", "stream": "missing_stream"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.query role=error:config-not-found bytes=753 sha256=07340ac1a2e4873129c0352bd2ddd667c2a5528f3236239b81fe56a08d315068 -->
```xout
@xdebug.error.v1

action          : stream.query
code            : CONFIG_NOT_FOUND
message         : stream config not found: missing_stream
recoverable     : true
error_layer     : handler
invalid_arg     : args.stream
expected        : name of a previously loaded stream config
missing_name    : missing_stream
missing_resource: stream config
example_note    : Example only; replace target.session_id and args.stream with the active session and loaded stream name.

correct_example:
  json: {"action":"stream.query","api_version":"xdebug.v1","args":{"query":"summary","stream":"req_stream"},"target":{"session_id":"case_a"}}

next_actions:
  Call stream.config.list to inspect loaded stream names.
  Call stream.config.load before querying a stream.
```

## 106. `stream.export` / `error:invalid-output-format`

- returncode: 1
- elapsed_ms: 93
- bytes: 719
- sha256: `6e9bb667e6d5175ab596d27cb133016ef9d48883cfd29a8b7cda8f78f43d1e2b`
- request: `{"action": "stream.export", "api_version": "xdebug.v1", "args": {"output": {"file_format": "binary", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/bad"}, "stream": "ready_stream"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.export role=error:invalid-output-format bytes=719 sha256=6e9bb667e6d5175ab596d27cb133016ef9d48883cfd29a8b7cda8f78f43d1e2b -->
```xout
@xdebug.error.v1

action          : stream.export
code            : INVALID_REQUEST
message         : invalid parameter args.output.file_format: instance not found in required enum; expected type "string"; available values: ["tsv","csv","xout"]
recoverable     : true
error_layer     : schema
invalid_arg     : args.output.file_format
expected        : type "string"
received_type   : string
available_values: ["tsv","csv","xout"]

correct_example:
  json: {"api_version":"xdebug.v1","action":"stream.export","target":{"session_id":"case_a"},"args":{"stream":"req_stream","kind":"transfer","cache_scope":"full","time_range":{"begin":"0ns","end":"1us"},"output":{"path":"artifacts/req_stream.tsv","file_format":"tsv"}}}
```

## 107. `waveform.cursor.get` / `error:cursor-not-found`

- returncode: 1
- elapsed_ms: 142
- bytes: 166
- sha256: `5caf66507014c4ffe3106f69fe430102c109ac7b8787301570513064a14c0b4b`
- request: `{"action": "waveform.cursor.get", "api_version": "xdebug.v1", "args": {"name": "missing_cursor"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=waveform.cursor.get role=error:cursor-not-found bytes=166 sha256=5caf66507014c4ffe3106f69fe430102c109ac7b8787301570513064a14c0b4b -->
```xout
@xdebug.error.v1

action     : waveform.cursor.get
code       : CURSOR_NOT_FOUND
message    : cursor not found: missing_cursor
recoverable: true
error_layer: handler
```

## 108. `apb.query` / `value-format:bin`

- returncode: 0
- elapsed_ms: 156
- bytes: 693
- sha256: `b7e6f8b5face476166ab8e38b64fcd6737c81b89ced24f096d16e6adfc222c9b`
- request: `{"action": "apb.query", "api_version": "xdebug.v1", "args": {"name": "apb0", "query": {"line_limit": 2}, "value_format": "bin"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.query role=value-format:bin bytes=693 sha256=b7e6f8b5face476166ab8e38b64fcd6737c81b89ced24f096d16e6adfc222c9b -->
```xout
@xdebug.apb.query.v1
summary:
  name              : apb0
  direction         : all
  query_mode        : list
  scan_complete     : true
  analysis_complete : true
  response_truncated: true
  total_count       : 10
  returned_count    : 2

truncation_scopes:
  response_transactions
  value_width_complete: true
  width_diagnostics   : [empty]

filter:
  direction: all

transactions:
  time   addr                                  data                                  is_write  has_error
  125ns  32'b00000000000000000000000000000000  32'b00010001001000100011001101000100  true      false
  165ns  32'b00000000000000000000000000000100  32'b01010101011001100111011110001000  true      false
```

## 109. `apb.query` / `value-format:dec`

- returncode: 0
- elapsed_ms: 133
- bytes: 534
- sha256: `2be2e051fb7fae045fe7e557b47d5f45354d235c9898b3a7e19f67fd0b5b9eae`
- request: `{"action": "apb.query", "api_version": "xdebug.v1", "args": {"name": "apb0", "query": {"line_limit": 2}, "value_format": "dec"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.query role=value-format:dec bytes=534 sha256=2be2e051fb7fae045fe7e557b47d5f45354d235c9898b3a7e19f67fd0b5b9eae -->
```xout
@xdebug.apb.query.v1
summary:
  name              : apb0
  direction         : all
  query_mode        : list
  scan_complete     : true
  analysis_complete : true
  response_truncated: true
  total_count       : 10
  returned_count    : 2

truncation_scopes:
  response_transactions
  value_width_complete: true
  width_diagnostics   : [empty]

filter:
  direction: all

transactions:
  time   addr   data            is_write  has_error
  125ns  32'd0  32'd287454020   true      false
  165ns  32'd4  32'd1432778632  true      false
```

## 110. `apb.statistics` / `value-format:bin`

- returncode: 0
- elapsed_ms: 193
- bytes: 725
- sha256: `43e0861890315acdb7b2f2ec079254aae44f0366334ff89f39ba1d88af419ee7`
- request: `{"action": "apb.statistics", "api_version": "xdebug.v1", "args": {"name": "apb0", "value_format": "bin"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.statistics role=value-format:bin bytes=725 sha256=43e0861890315acdb7b2f2ec079254aae44f0366334ff89f39ba1d88af419ee7 -->
```xout
@xdebug.apb.statistics.v1
summary:
  name                        : apb0
  scanned_transaction_count   : 10
  matched_transaction_count   : 10
  matched_read_count          : 5
  matched_write_count         : 5
  unresolved_transaction_count: 0
  filter_applied              : false
  analysis_quality            : complete
  full_scan_count             : 1
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 10
  returned_count              : 10

filter:
  direction: all

notes:
  unresolved_transaction_count: 因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。
```

## 111. `apb.statistics` / `value-format:dec`

- returncode: 0
- elapsed_ms: 157
- bytes: 725
- sha256: `43e0861890315acdb7b2f2ec079254aae44f0366334ff89f39ba1d88af419ee7`
- request: `{"action": "apb.statistics", "api_version": "xdebug.v1", "args": {"name": "apb0", "value_format": "dec"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.statistics role=value-format:dec bytes=725 sha256=43e0861890315acdb7b2f2ec079254aae44f0366334ff89f39ba1d88af419ee7 -->
```xout
@xdebug.apb.statistics.v1
summary:
  name                        : apb0
  scanned_transaction_count   : 10
  matched_transaction_count   : 10
  matched_read_count          : 5
  matched_write_count         : 5
  unresolved_transaction_count: 0
  filter_applied              : false
  analysis_quality            : complete
  full_scan_count             : 1
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 10
  returned_count              : 10

filter:
  direction: all

notes:
  unresolved_transaction_count: 因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。
```

## 112. `apb.transaction.cursor` / `value-format:bin`

- returncode: 0
- elapsed_ms: 257
- bytes: 610
- sha256: `0b93de36628cdc40b35d73f957ab2e0c8a3577aeedd8a5b5a7fe0e1eedae9601`
- request: `{"action": "apb.transaction.cursor", "api_version": "xdebug.v1", "args": {"name": "apb0", "op": "begin", "value_format": "bin"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.transaction.cursor role=value-format:bin bytes=610 sha256=0b93de36628cdc40b35d73f957ab2e0c8a3577aeedd8a5b5a7fe0e1eedae9601 -->
```xout
@xdebug.apb.transaction.cursor.v1
summary:
  name                : apb0
  op                  : begin
  direction           : all
  found               : true
  index               : 1
  index_base          : 1
  at_begin            : true
  at_end              : false
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 10
  returned_count      : 1
  value_width_complete: true

transaction:
  time     : 125ns
  addr     : 32'b00000000000000000000000000000000
  data     : 32'b00010001001000100011001101000100
  is_write : true
  has_error: false
```

## 113. `apb.transaction.cursor` / `value-format:dec`

- returncode: 0
- elapsed_ms: 115
- bytes: 556
- sha256: `427f1c65dbd740fc8491785d6558e4076c471ed9b5e97f16d6d5b3a28bf50fe1`
- request: `{"action": "apb.transaction.cursor", "api_version": "xdebug.v1", "args": {"name": "apb0", "op": "begin", "value_format": "dec"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.transaction.cursor role=value-format:dec bytes=556 sha256=427f1c65dbd740fc8491785d6558e4076c471ed9b5e97f16d6d5b3a28bf50fe1 -->
```xout
@xdebug.apb.transaction.cursor.v1
summary:
  name                : apb0
  op                  : begin
  direction           : all
  found               : true
  index               : 1
  index_base          : 1
  at_begin            : true
  at_end              : false
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 10
  returned_count      : 1
  value_width_complete: true

transaction:
  time     : 125ns
  addr     : 32'd0
  data     : 32'd287454020
  is_write : true
  has_error: false
```

## 114. `apb.transfer_window` / `value-format:bin`

- returncode: 0
- elapsed_ms: 120
- bytes: 1381
- sha256: `367a909efe285e39b7b2aa070930d7991dd534ebb76d30b2511cdb71d05f2772`
- request: `{"action": "apb.transfer_window", "api_version": "xdebug.v1", "args": {"name": "apb0", "value_format": "bin"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.transfer_window role=value-format:bin bytes=1381 sha256=367a909efe285e39b7b2aa070930d7991dd534ebb76d30b2511cdb71d05f2772 -->
```xout
@xdebug.apb.transfer_window.v1
summary:
  name                : apb0
  begin               : 0ns
  end                 : max
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 10
  returned_count      : 10
  value_width_complete: true

transactions:
  time   type  addr                                  data                                  has_error
  125ns  WR    32'b00000000000000000000000000000000  32'b00010001001000100011001101000100  false
  165ns  WR    32'b00000000000000000000000000000100  32'b01010101011001100111011110001000  false
  215ns  WR    32'b00000000000000000000000000001000  32'b10100101101001010101101001011010  false
  275ns  WR    32'b00000000000000000000000000001100  32'b11011110101011011011111011101111  false
  315ns  WR    32'b00000000000000000000000000000100  32'b00000000000000001010101111001101  false
  345ns  RD    32'b00000000000000000000000000000000  32'b00010001001000100011001101000100  false
  385ns  RD    32'b00000000000000000000000000000100  32'b01010101011001101010101111001101  false
  435ns  RD    32'b00000000000000000000000000001000  32'b10100101101001010101101001011010  false
  495ns  RD    32'b00000000000000000000000000001100  32'b11011110101011011011111011101111  false
  525ns  RD    32'b00000000000000000000000011110000  32'b10111010110100000000000011110000  true
```

## 115. `apb.transfer_window` / `value-format:dec`

- returncode: 0
- elapsed_ms: 123
- bytes: 820
- sha256: `ee7c7f8d23a7e7a40ed48d593af4b0146efb9f5e8508e4925780ef21b0e06b9c`
- request: `{"action": "apb.transfer_window", "api_version": "xdebug.v1", "args": {"name": "apb0", "value_format": "dec"}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=apb.transfer_window role=value-format:dec bytes=820 sha256=ee7c7f8d23a7e7a40ed48d593af4b0146efb9f5e8508e4925780ef21b0e06b9c -->
```xout
@xdebug.apb.transfer_window.v1
summary:
  name                : apb0
  begin               : 0ns
  end                 : max
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 10
  returned_count      : 10
  value_width_complete: true

transactions:
  time   type  addr     data            has_error
  125ns  WR    32'd0    32'd287454020   false
  165ns  WR    32'd4    32'd1432778632  false
  215ns  WR    32'd8    32'd2779077210  false
  275ns  WR    32'd12   32'd3735928559  false
  315ns  WR    32'd4    32'd43981       false
  345ns  RD    32'd0    32'd287454020   false
  385ns  RD    32'd4    32'd1432792013  false
  435ns  RD    32'd8    32'd2779077210  false
  495ns  RD    32'd12   32'd3735928559  false
  525ns  RD    32'd240  32'd3134193904  true
```

## 116. `axi.analysis` / `value-format:bin`

- returncode: 0
- elapsed_ms: 188
- bytes: 2498
- sha256: `95bf87e961d9b440f3bf5af3e62357494eb5fc3149d5fb70b76ad9b103cb650b`
- request: `{"action": "axi.analysis", "api_version": "xdebug.v1", "args": {"analysis": "latency", "direction": "all", "name": "axi0", "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.analysis role=value-format:bin bytes=2498 sha256=95bf87e961d9b440f3bf5af3e62357494eb5fc3149d5fb70b76ad9b103cb650b -->
```xout
@xdebug.axi.analysis.v1
summary:
  name                               : axi0
  analysis                           : latency
  direction                          : all
  sample_count                       : 323517
  full_scan_count                    : 1
  completed_read_count               : 3200
  completed_write_count              : 3200
  incomplete_read_count              : 0
  incomplete_write_count             : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0
  samples                            : 6400
  min                                : 60ns
  max                                : 106560ns
  avg                                : 37837.368ns
  p50                                : 16790ns
  p95                                : 81730ns
  p99                                : 95360ns
  scan_complete                      : true
  analysis_complete                  : true
  response_truncated                 : false
  total_count                        : 6400
  returned_count                     : 6400
  value_width_complete               : true

latency.read:
  samples: 3200
  min    : 650ns
  max    : 106560ns
  avg    : 63114.828ns
  p50    : 63860ns
  p95    : 87350ns
  p99    : 99660ns

latency.write:
  samples: 3200
  min    : 60ns
  max    : 17060ns
  avg    : 12559.909ns
  p50    : 12860ns
  p95    : 15350ns
  p99    : 16170ns

latency.definitions:
  read : AR handshake to RLAST handshake
  write: AW handshake to B handshake

latency.write_phase_order_counts:
  aw_before_w: 1474
  same_cycle : 578
  w_before_aw: 1148
  unknown    : 0

slowest:
  direction                    : read
  latency                      : 106560ns
  response_dependency_violation: false

slowest.address:
  channel         : ar
  valid_begin_time: 2285365ns
  handshake_time  : 2285365ns
  addr            : 64'b0000000000000000000000000000000000000000000000000101111100010000
  id              : 8'b00000110
  len             : 10'b0000001001
  size            : 3'b011
  burst           : 2'b01

slowest.data:
  channel             : r
  valid_begin_time    : 2390305ns
  first_handshake_time: 2390305ns
  last_handshake_time : 2391925ns
  beat_count          : 10
  expected_beat_count : 10

slowest.response:
  channel       : r
  handshake_time: 2391925ns
  resp          : 4'b0000
```

## 117. `axi.analysis` / `value-format:dec`

- returncode: 0
- elapsed_ms: 177
- bytes: 2417
- sha256: `a545402cc62083cf2289490655ec31738396a11fc22b199db1dec22ecef855f7`
- request: `{"action": "axi.analysis", "api_version": "xdebug.v1", "args": {"analysis": "latency", "direction": "all", "name": "axi0", "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.analysis role=value-format:dec bytes=2417 sha256=a545402cc62083cf2289490655ec31738396a11fc22b199db1dec22ecef855f7 -->
```xout
@xdebug.axi.analysis.v1
summary:
  name                               : axi0
  analysis                           : latency
  direction                          : all
  sample_count                       : 323517
  full_scan_count                    : 1
  completed_read_count               : 3200
  completed_write_count              : 3200
  incomplete_read_count              : 0
  incomplete_write_count             : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0
  samples                            : 6400
  min                                : 60ns
  max                                : 106560ns
  avg                                : 37837.368ns
  p50                                : 16790ns
  p95                                : 81730ns
  p99                                : 95360ns
  scan_complete                      : true
  analysis_complete                  : true
  response_truncated                 : false
  total_count                        : 6400
  returned_count                     : 6400
  value_width_complete               : true

latency.read:
  samples: 3200
  min    : 650ns
  max    : 106560ns
  avg    : 63114.828ns
  p50    : 63860ns
  p95    : 87350ns
  p99    : 99660ns

latency.write:
  samples: 3200
  min    : 60ns
  max    : 17060ns
  avg    : 12559.909ns
  p50    : 12860ns
  p95    : 15350ns
  p99    : 16170ns

latency.definitions:
  read : AR handshake to RLAST handshake
  write: AW handshake to B handshake

latency.write_phase_order_counts:
  aw_before_w: 1474
  same_cycle : 578
  w_before_aw: 1148
  unknown    : 0

slowest:
  direction                    : read
  latency                      : 106560ns
  response_dependency_violation: false

slowest.address:
  channel         : ar
  valid_begin_time: 2285365ns
  handshake_time  : 2285365ns
  addr            : 64'd24336
  id              : 8'd6
  len             : 10'd9
  size            : 3'd3
  burst           : 2'd1

slowest.data:
  channel             : r
  valid_begin_time    : 2390305ns
  first_handshake_time: 2390305ns
  last_handshake_time : 2391925ns
  beat_count          : 10
  expected_beat_count : 10

slowest.response:
  channel       : r
  handshake_time: 2391925ns
  resp          : 4'd0
```

## 118. `axi.export` / `value-format:bin`

- returncode: 0
- elapsed_ms: 129
- bytes: 962
- sha256: `d0651474b53df0e8fcaa299c62f27ddb2bd6a7188117e86fe2d2d98c527942e6`
- request: `{"action": "axi.export", "api_version": "xdebug.v1", "args": {"name": "axi0", "output": {"file_format": "tsv", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/axi-bin"}, "time_range": {"begin": "0ns", "end": "1us"}, "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.export role=value-format:bin bytes=962 sha256=d0651474b53df0e8fcaa299c62f27ddb2bd6a7188117e86fe2d2d98c527942e6 -->
```xout
@xdebug.axi.export.v1
summary:
  name                               : axi0
  write_count                        : 3
  read_count                         : 0
  total_count                        : 3
  row_count                          : 3
  format                             : tsv
  status                             : written
  output_written                     : true
  sample_count                       : 323517
  full_scan_count                    : 1
  incomplete_write_count             : 0
  incomplete_read_count              : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0
  scan_complete                      : true
  analysis_complete                  : true
  response_truncated                 : false
  returned_count                     : 3
```

## 119. `axi.export` / `value-format:dec`

- returncode: 0
- elapsed_ms: 174
- bytes: 962
- sha256: `d0651474b53df0e8fcaa299c62f27ddb2bd6a7188117e86fe2d2d98c527942e6`
- request: `{"action": "axi.export", "api_version": "xdebug.v1", "args": {"name": "axi0", "output": {"file_format": "tsv", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/axi-dec"}, "time_range": {"begin": "0ns", "end": "1us"}, "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.export role=value-format:dec bytes=962 sha256=d0651474b53df0e8fcaa299c62f27ddb2bd6a7188117e86fe2d2d98c527942e6 -->
```xout
@xdebug.axi.export.v1
summary:
  name                               : axi0
  write_count                        : 3
  read_count                         : 0
  total_count                        : 3
  row_count                          : 3
  format                             : tsv
  status                             : written
  output_written                     : true
  sample_count                       : 323517
  full_scan_count                    : 1
  incomplete_write_count             : 0
  incomplete_read_count              : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0
  scan_complete                      : true
  analysis_complete                  : true
  response_truncated                 : false
  returned_count                     : 3
```

## 120. `axi.latency_outlier` / `value-format:bin`

- returncode: 0
- elapsed_ms: 200
- bytes: 1763
- sha256: `329dff0700f1be4280451702a972d1c84b6d82a11ca460b1c8bbdc2bbbfb7c77`
- request: `{"action": "axi.latency_outlier", "api_version": "xdebug.v1", "args": {"line_limit": 2, "method": "top_n", "name": "axi0", "top_n": 2, "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.latency_outlier role=value-format:bin bytes=1763 sha256=329dff0700f1be4280451702a972d1c84b6d82a11ca460b1c8bbdc2bbbfb7c77 -->
```xout
@xdebug.axi.latency_outlier.v1
summary:
  name                : axi0
  begin               : 0ns
  end                 : max
  candidate_count     : 6400
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 2
  returned_count      : 2
  value_width_complete: true

outliers:
  direction  latency   response_dependency_violation  address.channel  address.valid_begin_time  address.handshake_time  address.addr                                                          address.id   address.len     address.size  address.burst  data.channel  data.valid_begin_time  data.first_handshake_time  data.last_handshake_time  data.beat_count  data.expected_beat_count  response.channel  response.handshake_time  response.resp  match_time
  read       106560ns  false                          ar               2285365ns                 2285365ns               64'b0000000000000000000000000000000000000000000000000101111100010000  8'b00000110  10'b0000001001  3'b011        2'b01          r             2390305ns              2390305ns                  2391925ns                 10               10                        r                 2391925ns                4'b0000        2285365ns
  read       105000ns  false                          ar               2285295ns                 2285295ns               64'b0000000000000000000000000000000000000000000000001110101011110000  8'b00000101  10'b0000001111  3'b011        2'b01          r             2389545ns              2389545ns                  2390295ns                 16               16                        r                 2390295ns                4'b0000        2285295ns
  method        : top_n
  classification: slowest_ranking
  top_n         : 2
```

## 121. `axi.latency_outlier` / `value-format:dec`

- returncode: 0
- elapsed_ms: 164
- bytes: 1583
- sha256: `679682f7e95f44009635bed1f5e982878651916d567c4d49687c8a4792c4f930`
- request: `{"action": "axi.latency_outlier", "api_version": "xdebug.v1", "args": {"line_limit": 2, "method": "top_n", "name": "axi0", "top_n": 2, "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.latency_outlier role=value-format:dec bytes=1583 sha256=679682f7e95f44009635bed1f5e982878651916d567c4d49687c8a4792c4f930 -->
```xout
@xdebug.axi.latency_outlier.v1
summary:
  name                : axi0
  begin               : 0ns
  end                 : max
  candidate_count     : 6400
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 2
  returned_count      : 2
  value_width_complete: true

outliers:
  direction  latency   response_dependency_violation  address.channel  address.valid_begin_time  address.handshake_time  address.addr  address.id  address.len  address.size  address.burst  data.channel  data.valid_begin_time  data.first_handshake_time  data.last_handshake_time  data.beat_count  data.expected_beat_count  response.channel  response.handshake_time  response.resp  match_time
  read       106560ns  false                          ar               2285365ns                 2285365ns               64'd24336     8'd6        10'd9        3'd3          2'd1           r             2390305ns              2390305ns                  2391925ns                 10               10                        r                 2391925ns                4'd0           2285365ns
  read       105000ns  false                          ar               2285295ns                 2285295ns               64'd60144     8'd5        10'd15       3'd3          2'd1           r             2389545ns              2389545ns                  2390295ns                 16               16                        r                 2390295ns                4'd0           2285295ns
  method        : top_n
  classification: slowest_ranking
  top_n         : 2
```

## 122. `axi.query` / `value-format:bin`

- returncode: 0
- elapsed_ms: 186
- bytes: 6935
- sha256: `4b897c29254c008736984e09cc7f988dca1c3fb1f211b82fbdb15f3edf9f2e9b`
- request: `{"action": "axi.query", "api_version": "xdebug.v1", "args": {"direction": "write", "name": "axi0", "query": {"line_limit": 2}, "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.query role=value-format:bin bytes=6935 sha256=4b897c29254c008736984e09cc7f988dca1c3fb1f211b82fbdb15f3edf9f2e9b -->
```xout
@xdebug.axi.query.v1
summary:
  name              : axi0
  direction         : write
  data_scope        : first_beat_each_with_first_transaction_full
  query_mode        : list
  data_hint         : Each transaction includes its first beat and the first transaction includes all beats. To inspect complete data for another transaction, narrow it with query.index, last, address, id, or time_range, then set output.include_data=true.
  scan_complete     : true
  analysis_complete : true
  response_truncated: true
  total_count       : 3200
  returned_count    : 2

truncation_scopes:
  response_transactions
  value_width_complete: true
  width_diagnostics   : [empty]

filter:
  direction: write

transactions:
  index  direction  phase_order  latency  response_dependency_violation  match_time
  1      write      aw_before_w  60ns     false
  2      write      w_before_aw  90ns     false

transaction_1_address:
  channel         : aw
  valid_begin_time: 415ns
  handshake_time  : 415ns
  addr            : 64'b0000000000000000000000000000000000000000000000000000100011000000
  id              : 8'b00000000
  len             : 10'b0000000000
  size            : 3'b011
  burst           : 2'b01

transaction_1_data:
  channel             : w
  valid_begin_time    : 465ns
  first_handshake_time: 465ns
  last_handshake_time : 465ns
  beat_count          : 1
  expected_beat_count : 1

transaction_1_beats:
  index  handshake_time  data                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    wstrb                                                                                                                                  resp  last
  1      465ns           1024'b0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001111100000101011111010101100010011000010111000110001100111101000  128'b00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000011111111        true

transaction_1_response:
  channel       : b
  handshake_time: 475ns
  resp          : 4'b0000

transaction_2_address:
  channel         : aw
  valid_begin_time: 515ns
  handshake_time  : 515ns
  addr            : 64'b0000000000000000000000000000000000000000000000001110111100101000
  id              : 8'b00000001
  len             : 10'b0000000010
  size            : 3'b011
  burst           : 2'b01

transaction_2_data:
  channel             : w
  valid_begin_time    : 475ns
  first_handshake_time: 475ns
  last_handshake_time : 495ns
  beat_count          : 3
  expected_beat_count : 3

transaction_2_beats:
  index  handshake_time  data                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    wstrb                                                                                                                                  resp  last
  1      475ns           1024'b0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001001110011001001111011100111110010111100100110111110100010011101  128'b00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000011111111        false

transaction_2_response:
  channel       : b
  handshake_time: 605ns
  resp          : 4'b0000
```

## 123. `axi.query` / `value-format:dec`

- returncode: 0
- elapsed_ms: 144
- bytes: 2256
- sha256: `c7619a4cecb2dfb00505df6ad7606aa6eacaff33f6f3535746c3ba6361c4f671`
- request: `{"action": "axi.query", "api_version": "xdebug.v1", "args": {"direction": "write", "name": "axi0", "query": {"line_limit": 2}, "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.query role=value-format:dec bytes=2256 sha256=c7619a4cecb2dfb00505df6ad7606aa6eacaff33f6f3535746c3ba6361c4f671 -->
```xout
@xdebug.axi.query.v1
summary:
  name              : axi0
  direction         : write
  data_scope        : first_beat_each_with_first_transaction_full
  query_mode        : list
  data_hint         : Each transaction includes its first beat and the first transaction includes all beats. To inspect complete data for another transaction, narrow it with query.index, last, address, id, or time_range, then set output.include_data=true.
  scan_complete     : true
  analysis_complete : true
  response_truncated: true
  total_count       : 3200
  returned_count    : 2

truncation_scopes:
  response_transactions
  value_width_complete: true
  width_diagnostics   : [empty]

filter:
  direction: write

transactions:
  index  direction  phase_order  latency  response_dependency_violation  match_time
  1      write      aw_before_w  60ns     false
  2      write      w_before_aw  90ns     false

transaction_1_address:
  channel         : aw
  valid_begin_time: 415ns
  handshake_time  : 415ns
  addr            : 64'd2240
  id              : 8'd0
  len             : 10'd0
  size            : 3'd3
  burst           : 2'd1

transaction_1_data:
  channel             : w
  valid_begin_time    : 465ns
  first_handshake_time: 465ns
  last_handshake_time : 465ns
  beat_count          : 1
  expected_beat_count : 1

transaction_1_beats:
  index  handshake_time  data                        wstrb     resp  last
  1      465ns           1024'd17882644876208839144  128'd255        true

transaction_1_response:
  channel       : b
  handshake_time: 475ns
  resp          : 4'd0

transaction_2_address:
  channel         : aw
  valid_begin_time: 515ns
  handshake_time  : 515ns
  addr            : 64'd61224
  id              : 8'd1
  len             : 10'd2
  size            : 3'd3
  burst           : 2'd1

transaction_2_data:
  channel             : w
  valid_begin_time    : 475ns
  first_handshake_time: 475ns
  last_handshake_time : 495ns
  beat_count          : 3
  expected_beat_count : 3

transaction_2_beats:
  index  handshake_time  data                        wstrb     resp  last
  1      475ns           1024'd11297823359743289501  128'd255        false

transaction_2_response:
  channel       : b
  handshake_time: 605ns
  resp          : 4'd0
```

## 124. `axi.request_response_pair` / `value-format:bin`

- returncode: 0
- elapsed_ms: 126
- bytes: 2284
- sha256: `5bcac6c186d340d6b3e32c59f436e1feac1190c69b7d256d89c956f32b0dc3e9`
- request: `{"action": "axi.request_response_pair", "api_version": "xdebug.v1", "args": {"direction": "all", "line_limit": 2, "name": "axi0", "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.request_response_pair role=value-format:bin bytes=2284 sha256=5bcac6c186d340d6b3e32c59f436e1feac1190c69b7d256d89c956f32b0dc3e9 -->
```xout
@xdebug.axi.request_response_pair.v1
summary:
  name                : axi0
  begin               : 0ns
  end                 : max
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : true
  total_count         : 6400
  returned_count      : 2
  value_width_complete: true

pairing_rule:
  write_data    : AXI4 W bursts bind in AW acceptance order
  write_response: BID binds to the oldest data-complete AW with the same ID
  read_response : RID binds to the oldest AR with the same ID

diagnostics:
  full_scan_count                    : 1
  incomplete_write_count             : 0
  incomplete_read_count              : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0

transactions:
  direction  latency  response_dependency_violation  address.channel  address.valid_begin_time  address.handshake_time  address.addr                                                          address.id   address.len     address.size  address.burst  data.channel  data.valid_begin_time  data.first_handshake_time  data.last_handshake_time  data.beat_count  data.expected_beat_count  response.channel  response.handshake_time  response.resp  match_time  phase_order
  read       650ns    false                          ar               415ns                     415ns                   64'b0000000000000000000000000000000000000000000000001110111101011000  8'b00000000  10'b0000001100  3'b011        2'b01          r             465ns                  465ns                      1065ns                    13               13                        r                 1065ns                   4'b0000        415ns
  write      60ns     false                          aw               415ns                     415ns                   64'b0000000000000000000000000000000000000000000000000000100011000000  8'b00000000  10'b0000000000  3'b011        2'b01          w             465ns                  465ns                      465ns                     1                1                         b                 475ns                    4'b0000        415ns       aw_before_w
```

## 125. `axi.request_response_pair` / `value-format:dec`

- returncode: 0
- elapsed_ms: 127
- bytes: 2104
- sha256: `1d5e86040944dee00b0f87aa70760d23ee15272b14946148de0b3d716e6a3932`
- request: `{"action": "axi.request_response_pair", "api_version": "xdebug.v1", "args": {"direction": "all", "line_limit": 2, "name": "axi0", "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.request_response_pair role=value-format:dec bytes=2104 sha256=1d5e86040944dee00b0f87aa70760d23ee15272b14946148de0b3d716e6a3932 -->
```xout
@xdebug.axi.request_response_pair.v1
summary:
  name                : axi0
  begin               : 0ns
  end                 : max
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : true
  total_count         : 6400
  returned_count      : 2
  value_width_complete: true

pairing_rule:
  write_data    : AXI4 W bursts bind in AW acceptance order
  write_response: BID binds to the oldest data-complete AW with the same ID
  read_response : RID binds to the oldest AR with the same ID

diagnostics:
  full_scan_count                    : 1
  incomplete_write_count             : 0
  incomplete_read_count              : 0
  buffered_w_beat_count              : 0
  buffered_w_burst_count             : 0
  orphan_w_beat_count                : 0
  orphan_b_count                     : 0
  orphan_r_beat_count                : 0
  response_dependency_violation_count: 0

transactions:
  direction  latency  response_dependency_violation  address.channel  address.valid_begin_time  address.handshake_time  address.addr  address.id  address.len  address.size  address.burst  data.channel  data.valid_begin_time  data.first_handshake_time  data.last_handshake_time  data.beat_count  data.expected_beat_count  response.channel  response.handshake_time  response.resp  match_time  phase_order
  read       650ns    false                          ar               415ns                     415ns                   64'd61272     8'd0        10'd12       3'd3          2'd1           r             465ns                  465ns                      1065ns                    13               13                        r                 1065ns                   4'd0           415ns
  write      60ns     false                          aw               415ns                     415ns                   64'd2240      8'd0        10'd0        3'd3          2'd1           w             465ns                  465ns                      465ns                     1                1                         b                 475ns                    4'd0           415ns       aw_before_w
```

## 126. `axi.statistics` / `value-format:bin`

- returncode: 0
- elapsed_ms: 126
- bytes: 739
- sha256: `74f6c70d189cb790e9b09fb8b4f0c89b7199418027cc3b260e035ee6adaf462c`
- request: `{"action": "axi.statistics", "api_version": "xdebug.v1", "args": {"name": "axi0", "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.statistics role=value-format:bin bytes=739 sha256=74f6c70d189cb790e9b09fb8b4f0c89b7199418027cc3b260e035ee6adaf462c -->
```xout
@xdebug.axi.statistics.v1
summary:
  name                        : axi0
  scanned_transaction_count   : 6400
  matched_transaction_count   : 6400
  matched_read_count          : 3200
  matched_write_count         : 3200
  unresolved_transaction_count: 0
  filter_applied              : false
  analysis_quality            : complete
  full_scan_count             : 1
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 6400
  returned_count              : 6400

filter:
  direction: all

notes:
  unresolved_transaction_count: 因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。
```

## 127. `axi.statistics` / `value-format:dec`

- returncode: 0
- elapsed_ms: 137
- bytes: 739
- sha256: `74f6c70d189cb790e9b09fb8b4f0c89b7199418027cc3b260e035ee6adaf462c`
- request: `{"action": "axi.statistics", "api_version": "xdebug.v1", "args": {"name": "axi0", "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.statistics role=value-format:dec bytes=739 sha256=74f6c70d189cb790e9b09fb8b4f0c89b7199418027cc3b260e035ee6adaf462c -->
```xout
@xdebug.axi.statistics.v1
summary:
  name                        : axi0
  scanned_transaction_count   : 6400
  matched_transaction_count   : 6400
  matched_read_count          : 3200
  matched_write_count         : 3200
  unresolved_transaction_count: 0
  filter_applied              : false
  analysis_quality            : complete
  full_scan_count             : 1
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 6400
  returned_count              : 6400

filter:
  direction: all

notes:
  unresolved_transaction_count: 因被引用的 address/ID 含 X/Z 或不可解析，导致无法判断是否匹配过滤条件的已完成事务数。
```

## 128. `axi.transaction.cursor` / `value-format:bin`

- returncode: 0
- elapsed_ms: 121
- bytes: 1203
- sha256: `d2e1154d0efcc89e56e457d169b76635e430450152cf0ddea60bb28630ab9e51`
- request: `{"action": "axi.transaction.cursor", "api_version": "xdebug.v1", "args": {"direction": "all", "name": "axi0", "op": "begin", "value_format": "bin"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.transaction.cursor role=value-format:bin bytes=1203 sha256=d2e1154d0efcc89e56e457d169b76635e430450152cf0ddea60bb28630ab9e51 -->
```xout
@xdebug.axi.transaction.cursor.v1
summary:
  name                : axi0
  op                  : begin
  direction           : all
  found               : true
  index               : 1
  index_base          : 1
  at_begin            : true
  at_end              : false
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 6400
  returned_count      : 1
  value_width_complete: true

transaction:
  direction                    : write
  phase_order                  : aw_before_w
  latency                      : 60ns
  response_dependency_violation: false

transaction.address:
  channel         : aw
  valid_begin_time: 415ns
  handshake_time  : 415ns
  addr            : 64'b0000000000000000000000000000000000000000000000000000100011000000
  id              : 8'b00000000
  len             : 10'b0000000000
  size            : 3'b011
  burst           : 2'b01

transaction.data:
  channel             : w
  valid_begin_time    : 465ns
  first_handshake_time: 465ns
  last_handshake_time : 465ns
  beat_count          : 1
  expected_beat_count : 1

transaction.response:
  channel       : b
  handshake_time: 475ns
  resp          : 4'b0000
```

## 129. `axi.transaction.cursor` / `value-format:dec`

- returncode: 0
- elapsed_ms: 119
- bytes: 1121
- sha256: `0ed82c5a39f0eace56f395361e881a7f2a083d26a98c60ce2f212cc3ee52b0cf`
- request: `{"action": "axi.transaction.cursor", "api_version": "xdebug.v1", "args": {"direction": "all", "name": "axi0", "op": "begin", "value_format": "dec"}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=axi.transaction.cursor role=value-format:dec bytes=1121 sha256=0ed82c5a39f0eace56f395361e881a7f2a083d26a98c60ce2f212cc3ee52b0cf -->
```xout
@xdebug.axi.transaction.cursor.v1
summary:
  name                : axi0
  op                  : begin
  direction           : all
  found               : true
  index               : 1
  index_base          : 1
  at_begin            : true
  at_end              : false
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 6400
  returned_count      : 1
  value_width_complete: true

transaction:
  direction                    : write
  phase_order                  : aw_before_w
  latency                      : 60ns
  response_dependency_violation: false

transaction.address:
  channel         : aw
  valid_begin_time: 415ns
  handshake_time  : 415ns
  addr            : 64'd2240
  id              : 8'd0
  len             : 10'd0
  size            : 3'd3
  burst           : 2'd1

transaction.data:
  channel             : w
  valid_begin_time    : 465ns
  first_handshake_time: 465ns
  last_handshake_time : 465ns
  beat_count          : 1
  expected_beat_count : 1

transaction.response:
  channel       : b
  handshake_time: 475ns
  resp          : 4'd0
```

## 130. `counter.statistics` / `value-format:bin`

- returncode: 0
- elapsed_ms: 126
- bytes: 1190
- sha256: `5b41a1c0f4c283b3a48f2c813c4c03c567ec7d888678c4db24bd0eb9aedf1356`
- request: `{"action": "counter.statistics", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "cnt": "ai_complex_top.counter_inc", "edge": "posedge", "time_range": {"begin": "55ns", "end": "95ns"}, "value_format": "bin", "vld": "ai_complex_top.rst_n"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=counter.statistics role=value-format:bin bytes=1190 sha256=5b41a1c0f4c283b3a48f2c813c4c03c567ec7d888678c4db24bd0eb9aedf1356 -->
```xout
@xdebug.counter.statistics.v1
summary:
  sample_count         : 5
  valid_count          : 5
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  begin                : 55ns
  end                  : 95ns
  valid_false_count    : 0
  unknown_count        : 0
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 5
  returned_count       : 5
  min_value            : 8'b00000000
  max_value            : 8'b00000100
  average_value        : 2
  value_width_complete : true

evidence:
  time  kind          value
  55ns  initial       8'b00000000
  65ns  value_change  8'b00000001
  75ns  value_change  8'b00000010
  85ns  value_change  8'b00000011
  95ns  value_change  8'b00000100

sampling:
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: posedge

sampling.effective:
  edge          : posedge
  sample_point  : before
  cnt           : ai_complex_top.counter_inc
  vld           : ai_complex_top.rst_n
  min_count     : 1
  max_count     : 1
  min_first_time: 55ns
  max_first_time: 95ns
```

## 131. `counter.statistics` / `value-format:dec`

- returncode: 0
- elapsed_ms: 129
- bytes: 1141
- sha256: `99a04d43d293aac95184875966b7ed0e01c2d6494ce3868b75b691cbc925bbc4`
- request: `{"action": "counter.statistics", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "cnt": "ai_complex_top.counter_inc", "edge": "posedge", "time_range": {"begin": "55ns", "end": "95ns"}, "value_format": "dec", "vld": "ai_complex_top.rst_n"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=counter.statistics role=value-format:dec bytes=1141 sha256=99a04d43d293aac95184875966b7ed0e01c2d6494ce3868b75b691cbc925bbc4 -->
```xout
@xdebug.counter.statistics.v1
summary:
  sample_count         : 5
  valid_count          : 5
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  begin                : 55ns
  end                  : 95ns
  valid_false_count    : 0
  unknown_count        : 0
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 5
  returned_count       : 5
  min_value            : 8'd0
  max_value            : 8'd4
  average_value        : 2
  value_width_complete : true

evidence:
  time  kind          value
  55ns  initial       8'd0
  65ns  value_change  8'd1
  75ns  value_change  8'd2
  85ns  value_change  8'd3
  95ns  value_change  8'd4

sampling:
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: posedge

sampling.effective:
  edge          : posedge
  sample_point  : before
  cnt           : ai_complex_top.counter_inc
  vld           : ai_complex_top.rst_n
  min_count     : 1
  max_count     : 1
  min_first_time: 55ns
  max_first_time: 95ns
```

## 132. `event.export` / `value-format:bin`

- returncode: 0
- elapsed_ms: 141
- bytes: 831
- sha256: `4d832feeed88d4bc83333c53b81c5ba0e0da2266ea9e4fb2879ac2f7895e3699`
- request: `{"action": "event.export", "api_version": "xdebug.v1", "args": {"expr": "vld && rdy", "name": "rdy", "output": {"file_format": "json", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/events.json-bin"}, "value_format": "bin"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.export role=value-format:bin bytes=831 sha256=4d832feeed88d4bc83333c53b81c5ba0e0da2266ea9e4fb2879ac2f7895e3699 -->
```xout
@xdebug.event.export.v1
summary:
  sample_count         : 20
  mode                 : export
  inline               : false
  sampling_mode        : clock_edge
  clock                : xif_event_top.clk
  sample_time_semantics: time is sample_time
  first                : 85ns
  last                 : 135ns
  begin                : 0ns
  end                  : max
  status               : written
  output_written       : true
  row_count            : 5
  line_limit           : 1000
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 5
  returned_count       : 5

sampling:
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: posedge

sampling.effective:
  edge        : posedge
  sample_point: before
```

## 133. `event.export` / `value-format:dec`

- returncode: 0
- elapsed_ms: 132
- bytes: 831
- sha256: `4d832feeed88d4bc83333c53b81c5ba0e0da2266ea9e4fb2879ac2f7895e3699`
- request: `{"action": "event.export", "api_version": "xdebug.v1", "args": {"expr": "vld && rdy", "name": "rdy", "output": {"file_format": "json", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/events.json-dec"}, "value_format": "dec"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.export role=value-format:dec bytes=831 sha256=4d832feeed88d4bc83333c53b81c5ba0e0da2266ea9e4fb2879ac2f7895e3699 -->
```xout
@xdebug.event.export.v1
summary:
  sample_count         : 20
  mode                 : export
  inline               : false
  sampling_mode        : clock_edge
  clock                : xif_event_top.clk
  sample_time_semantics: time is sample_time
  first                : 85ns
  last                 : 135ns
  begin                : 0ns
  end                  : max
  status               : written
  output_written       : true
  row_count            : 5
  line_limit           : 1000
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 5
  returned_count       : 5

sampling:
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: posedge

sampling.effective:
  edge        : posedge
  sample_point: before
```

## 134. `event.find` / `value-format:bin`

- returncode: 0
- elapsed_ms: 137
- bytes: 844
- sha256: `90f53944a09c31d3f98b3dc61f80a855027be27849a336c8299dba1e4e01c381`
- request: `{"action": "event.find", "api_version": "xdebug.v1", "args": {"expr": "vld && rdy", "line_limit": 2, "mode": "all", "name": "rdy", "value_format": "bin"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.find role=value-format:bin bytes=844 sha256=90f53944a09c31d3f98b3dc61f80a855027be27849a336c8299dba1e4e01c381 -->
```xout
@xdebug.event.find.v1
summary:
  sample_count         : 20
  mode                 : all
  inline               : false
  sampling_mode        : clock_edge
  clock                : xif_event_top.clk
  sample_time_semantics: time is sample_time
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : true
  total_count          : 5
  returned_count       : 2

truncation_scopes:
  response_events
  first               : 85ns
  last                : 135ns
  begin               : 0ns
  end                 : max
  value_width_complete: true

requested:
  edge: posedge

effective:
  edge                            : posedge
  sample_point                    : before
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

events:
  time  rdy   vld
  85ns  1'b1  1'b1
  95ns  1'b1  1'b1
```

## 135. `event.find` / `value-format:dec`

- returncode: 0
- elapsed_ms: 172
- bytes: 844
- sha256: `82f964cbd5943b05aa4ea3452406d30095103352adef03a38c41a8cc6e826efd`
- request: `{"action": "event.find", "api_version": "xdebug.v1", "args": {"expr": "vld && rdy", "line_limit": 2, "mode": "all", "name": "rdy", "value_format": "dec"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=event.find role=value-format:dec bytes=844 sha256=82f964cbd5943b05aa4ea3452406d30095103352adef03a38c41a8cc6e826efd -->
```xout
@xdebug.event.find.v1
summary:
  sample_count         : 20
  mode                 : all
  inline               : false
  sampling_mode        : clock_edge
  clock                : xif_event_top.clk
  sample_time_semantics: time is sample_time
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : true
  total_count          : 5
  returned_count       : 2

truncation_scopes:
  response_events
  first               : 85ns
  last                : 135ns
  begin               : 0ns
  end                 : max
  value_width_complete: true

requested:
  edge: posedge

effective:
  edge                            : posedge
  sample_point                    : before
  sample_point_applied            : true
  sample_point_ignored_for_negedge: false

events:
  time  rdy   vld
  85ns  1'd1  1'd1
  95ns  1'd1  1'd1
```

## 136. `expr.eval_at` / `value-format:bin`

- returncode: 0
- elapsed_ms: 162
- bytes: 849
- sha256: `6e131b5cb9a7c1217ad1636027e53fd2ccdc02c2d6487e1977da85878703086f`
- request: `{"action": "expr.eval_at", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "expr": "valid && !ready", "signals": {"ready": "ai_complex_top.hs_ready", "valid": "ai_complex_top.hs_valid"}, "time": "145ns", "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=expr.eval_at role=value-format:bin bytes=849 sha256=6e131b5cb9a7c1217ad1636027e53fd2ccdc02c2d6487e1977da85878703086f -->
```xout
@xdebug.expr.eval_at.v1
summary:
  expr                : valid&&!ready
  time                : 145ns
  status              : true
  value_width_complete: true

data:
  expr_value: true

operands:
  alias  signal                   value
  ready  ai_complex_top.hs_ready  1'b0
  valid  ai_complex_top.hs_valid  1'b1

clock_context:
  clock                           : ai_complex_top.clk
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false
  requested_time                  : 145ns
  requested_any_edge_hit          : false
  requested_target_edge_hit       : false
  previous_sample_time            : 90ns
  bracket_complete                : false

clock_context.requested_sampling:
  edge: negedge

clock_context.effective_sampling:
  edge: negedge

expr_samples:
  before: false
  middle: true
  after : missing_edge
```

## 137. `expr.eval_at` / `value-format:dec`

- returncode: 0
- elapsed_ms: 132
- bytes: 926
- sha256: `e15e0d8e4be9bb9bf4c1c8ae0d97ea29ef059746640b4727485aa55ba4d6c43e`
- request: `{"action": "expr.eval_at", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "expr": "valid && !ready", "signals": {"ready": "ai_complex_top.hs_ready", "valid": "ai_complex_top.hs_valid"}, "time": "145ns", "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=expr.eval_at role=value-format:dec bytes=926 sha256=e15e0d8e4be9bb9bf4c1c8ae0d97ea29ef059746640b4727485aa55ba4d6c43e -->
```xout
@xdebug.expr.eval_at.v1
summary:
  expr                : valid&&!ready
  time                : 145ns
  status              : true
  value_width_complete: true

data:
  expr_value: true

operands:
  alias  signal                   value
  ready  ai_complex_top.hs_ready  1'd0
  valid  ai_complex_top.hs_valid  1'd1

clock_context:
  clock                           : ai_complex_top.clk
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false
  requested_time                  : 145ns
  requested_any_edge_hit          : true
  clock_edge_kind                 : posedge
  requested_target_edge_hit       : false
  previous_sample_time            : 140ns
  next_sample_time                : 150ns
  bracket_complete                : true

clock_context.requested_sampling:
  edge: negedge

clock_context.effective_sampling:
  edge: negedge

expr_samples:
  before: false
  middle: true
  after : true
```

## 138. `list.first_change` / `value-format:bin`

- returncode: 0
- elapsed_ms: 193
- bytes: 431
- sha256: `f5c6b80cdc0afe5093339c9299c0c7f5a25e4703ca545cf3aa6e65ecb6f01cde`
- request: `{"action": "list.first_change", "api_version": "xdebug.v1", "args": {"name": "basic_first_change", "time_range": {"begin": "0ns", "end": "120ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.first_change role=value-format:bin bytes=431 sha256=f5c6b80cdc0afe5093339c9299c0c7f5a25e4703ca545cf3aa6e65ecb6f01cde -->
```xout
@xdebug.list.first_change.v1
summary:
  name                : basic_first_change
  diff_found          : true
  diff_time           : 55ns
  changed_signal_count: 2
  value_width_complete: true

changed_signals:
  signal                before_time  change_time  before       after
  ai_complex_top.sig_b  0ns          55ns         8'b00000000  8'b00010001
  ai_complex_top.sig_a  0ns          55ns         8'b00000000  8'b00010001
```

## 139. `list.first_change` / `value-format:dec`

- returncode: 0
- elapsed_ms: 133
- bytes: 404
- sha256: `43dd0a7603894c6bd76afe40b7b7e0307883703142da8ec2e370a184c2738781`
- request: `{"action": "list.first_change", "api_version": "xdebug.v1", "args": {"name": "basic_first_change", "time_range": {"begin": "0ns", "end": "120ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=list.first_change role=value-format:dec bytes=404 sha256=43dd0a7603894c6bd76afe40b7b7e0307883703142da8ec2e370a184c2738781 -->
```xout
@xdebug.list.first_change.v1
summary:
  name                : basic_first_change
  diff_found          : true
  diff_time           : 55ns
  changed_signal_count: 2
  value_width_complete: true

changed_signals:
  signal                before_time  change_time  before  after
  ai_complex_top.sig_b  0ns          55ns         8'd0    8'd17
  ai_complex_top.sig_a  0ns          55ns         8'd0    8'd17
```

## 140. `protocol.handshake.inspect` / `value-format:bin`

- returncode: 0
- elapsed_ms: 147
- bytes: 1029
- sha256: `80e7303148e4b8b83421c85d9ebc98d0fd2958a9e03e92a24375ac0c7171d2ea`
- request: `{"action": "protocol.handshake.inspect", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "ready": "ai_complex_top.hs_ready", "valid": "ai_complex_top.hs_valid", "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=protocol.handshake.inspect role=value-format:bin bytes=1029 sha256=80e7303148e4b8b83421c85d9ebc98d0fd2958a9e03e92a24375ac0c7171d2ea -->
```xout
@xdebug.protocol.handshake.inspect.v1
summary:
  sampling_mode                     : clock_edge
  clock                             : ai_complex_top.clk
  sample_time_semantics             : time is sample_time
  sample_count                      : 48
  transfer_count                    : 3
  max_stall_cycles                  : 4
  ready_without_valid_cycles        : 29
  ready_without_valid_reporting     : summary
  ready_without_valid_interval_count: 1
  data_stability_violations         : 0
  require_valid_hold_until_handshake: true
  valid_hold_violations             : 0
  valid_wait_open_at_window_end     : false
  scan_complete                     : true
  analysis_complete                 : true
  response_truncated                : false
  total_count                       : 0
  returned_count                    : 0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge    : negedge
  findings: [empty]
```

## 141. `protocol.handshake.inspect` / `value-format:dec`

- returncode: 0
- elapsed_ms: 133
- bytes: 1029
- sha256: `80e7303148e4b8b83421c85d9ebc98d0fd2958a9e03e92a24375ac0c7171d2ea`
- request: `{"action": "protocol.handshake.inspect", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "ready": "ai_complex_top.hs_ready", "valid": "ai_complex_top.hs_valid", "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=protocol.handshake.inspect role=value-format:dec bytes=1029 sha256=80e7303148e4b8b83421c85d9ebc98d0fd2958a9e03e92a24375ac0c7171d2ea -->
```xout
@xdebug.protocol.handshake.inspect.v1
summary:
  sampling_mode                     : clock_edge
  clock                             : ai_complex_top.clk
  sample_time_semantics             : time is sample_time
  sample_count                      : 48
  transfer_count                    : 3
  max_stall_cycles                  : 4
  ready_without_valid_cycles        : 29
  ready_without_valid_reporting     : summary
  ready_without_valid_interval_count: 1
  data_stability_violations         : 0
  require_valid_hold_until_handshake: true
  valid_hold_violations             : 0
  valid_wait_open_at_window_end     : false
  scan_complete                     : true
  analysis_complete                 : true
  response_truncated                : false
  total_count                       : 0
  returned_count                    : 0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge    : negedge
  findings: [empty]
```

## 142. `signal.anomaly.inspect` / `value-format:bin`

- returncode: 0
- elapsed_ms: 138
- bytes: 552
- sha256: `574b9df787b808fa58006fff898b4ed77a48cd33886cfa8099ccd2c58e9e51aa`
- request: `{"action": "signal.anomaly.inspect", "api_version": "xdebug.v1", "args": {"checks": [{"type": "unknown_xz"}], "line_limit": 4, "signals": ["xif_event_top.xz_data"], "time_range": {"begin": "0ns", "end": "200ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=signal.anomaly.inspect role=value-format:bin bytes=552 sha256=574b9df787b808fa58006fff898b4ed77a48cd33886cfa8099ccd2c58e9e51aa -->
```xout
@xdebug.signal.anomaly.inspect.v1
summary:
  signal_count        : 1
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: true

findings:
  type        signal                 severity  time  value
  unknown_xz  xif_event_top.xz_data  warning   65ns  16'bxxxxxxxxxxxxxxxx

scan_status:
  signal                 status  analysis_complete  change_row_count  finding_count
  xif_event_top.xz_data  ok      true               3                 1
```

## 143. `signal.anomaly.inspect` / `value-format:dec`

- returncode: 0
- elapsed_ms: 122
- bytes: 577
- sha256: `da842a120b74269215a0346d618882cb3aeba42f6724c1872ce845caaf8192a3`
- request: `{"action": "signal.anomaly.inspect", "api_version": "xdebug.v1", "args": {"checks": [{"type": "unknown_xz"}], "line_limit": 4, "signals": ["xif_event_top.xz_data"], "time_range": {"begin": "0ns", "end": "200ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=signal.anomaly.inspect role=value-format:dec bytes=577 sha256=da842a120b74269215a0346d618882cb3aeba42f6724c1872ce845caaf8192a3 -->
```xout
@xdebug.signal.anomaly.inspect.v1
summary:
  signal_count        : 1
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: true

findings:
  type        signal                 severity  time  value
  unknown_xz  xif_event_top.xz_data  warning   65ns  16'bxxxxxxxxxxxxxxxx requested=dec reason=X/Z

scan_status:
  signal                 status  analysis_complete  change_row_count  finding_count
  xif_event_top.xz_data  ok      true               3                 1
```

## 144. `signal.changes` / `value-format:bin`

- returncode: 0
- elapsed_ms: 135
- bytes: 834
- sha256: `1f0bb5537d858b4c81d7a08d3d7975de858743318229e2a3d25e9be1df5c6613`
- request: `{"action": "signal.changes", "api_version": "xdebug.v1", "args": {"line_limit": 2, "signal": "ai_complex_top.sig_a", "time_range": {"begin": "0ns", "end": "120ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.changes role=value-format:bin bytes=834 sha256=1f0bb5537d858b4c81d7a08d3d7975de858743318229e2a3d25e9be1df5c6613 -->
```xout
@xdebug.signal.changes.v1
summary:
  signal                 : ai_complex_top.sig_a
  actual_transition_count: 2
  scan_complete          : true
  analysis_complete      : true
  response_truncated     : true
  total_count            : 3
  returned_count         : 2
  value_width_complete   : true

data:
  begin                 : 0ns
  end                   : 120ns
  includes_initial_value: true
  semantic_note         : signal.changes returns value-change rows for timeline inspection. Do not use row counts as sampled high cycles; use signal.statistics.high_cycles for clock-sampled activity.
  initial_value         : 8'b00000000
  final_value           : 8'b00100010
  first_change          : 0ns
  last_change           : 65ns
  mode                  : timeline

changes:
  time  value
  0ns   8'b00000000
  55ns  8'b00010001
```

## 145. `signal.changes` / `value-format:dec`

- returncode: 0
- elapsed_ms: 200
- bytes: 808
- sha256: `a8be00f77b781ca0c394250354e8a80a9230436ce2d922f718cc4aa2dfcdf72f`
- request: `{"action": "signal.changes", "api_version": "xdebug.v1", "args": {"line_limit": 2, "signal": "ai_complex_top.sig_a", "time_range": {"begin": "0ns", "end": "120ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.changes role=value-format:dec bytes=808 sha256=a8be00f77b781ca0c394250354e8a80a9230436ce2d922f718cc4aa2dfcdf72f -->
```xout
@xdebug.signal.changes.v1
summary:
  signal                 : ai_complex_top.sig_a
  actual_transition_count: 2
  scan_complete          : true
  analysis_complete      : true
  response_truncated     : true
  total_count            : 3
  returned_count         : 2
  value_width_complete   : true

data:
  begin                 : 0ns
  end                   : 120ns
  includes_initial_value: true
  semantic_note         : signal.changes returns value-change rows for timeline inspection. Do not use row counts as sampled high cycles; use signal.statistics.high_cycles for clock-sampled activity.
  initial_value         : 8'd0
  final_value           : 8'd34
  first_change          : 0ns
  last_change           : 65ns
  mode                  : timeline

changes:
  time  value
  0ns   8'd0
  55ns  8'd17
```

## 146. `signal.sampled_pulse.inspect` / `value-format:bin`

- returncode: 0
- elapsed_ms: 162
- bytes: 1710
- sha256: `0545c752451bb852c483db75ba95d916c204628957cf3105db09193b6a524894`
- request: `{"action": "signal.sampled_pulse.inspect", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "line_limit": 5, "time_range": {"begin": "0ns", "end": "200ns"}, "valid": "ai_complex_top.glitch_sig", "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.sampled_pulse.inspect role=value-format:bin bytes=1710 sha256=0545c752451bb852c483db75ba95d916c204628957cf3105db09193b6a524894 -->
```xout
@xdebug.signal.sampled_pulse.inspect.v1
summary:
  sampling_mode                                  : clock_edge
  clock                                          : ai_complex_top.clk
  sample_time_semantics                          : time is sample_time
  sample_count                                   : 20
  sampled_high_cycles                            : 0
  unsampled_valid_pulse_count                    : 1
  payload_risk_count                             : 0
  payload_changed_without_sampled_valid_reporting: summary
  scan_complete                                  : true
  analysis_complete                              : true
  response_truncated                             : false
  total_count                                    : 1
  returned_count                                 : 1
  value_width_complete                           : true

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge                      : negedge
  valid                     : ai_complex_top.glitch_sig
  payloads                  : [empty]
  begin                     : 0ns
  end                       : 200ns
  sampled_low_cycles        : 20
  sampled_unknown_cycles    : 0
  raw_valid_transition_count: 3
  payload_transition_count  : 0

findings:
  type                   severity  raw_begin  raw_end  previous_sample_edge  next_sample_edge  nearest_sample_edge  raw_valid  sampled_valid  reason
  unsampled_valid_pulse  warning   96ns       96.2ns   90ns                  100ns             100ns                1'b1       1'b0           valid was high between sample edges but not high at any sampled edge
```

## 147. `signal.sampled_pulse.inspect` / `value-format:dec`

- returncode: 0
- elapsed_ms: 125
- bytes: 1710
- sha256: `66eb1f892d463cdab8601b9ad4fa19b5cbf4e247d62a46007a9eb4f3f048a1dd`
- request: `{"action": "signal.sampled_pulse.inspect", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "line_limit": 5, "time_range": {"begin": "0ns", "end": "200ns"}, "valid": "ai_complex_top.glitch_sig", "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.sampled_pulse.inspect role=value-format:dec bytes=1710 sha256=66eb1f892d463cdab8601b9ad4fa19b5cbf4e247d62a46007a9eb4f3f048a1dd -->
```xout
@xdebug.signal.sampled_pulse.inspect.v1
summary:
  sampling_mode                                  : clock_edge
  clock                                          : ai_complex_top.clk
  sample_time_semantics                          : time is sample_time
  sample_count                                   : 20
  sampled_high_cycles                            : 0
  unsampled_valid_pulse_count                    : 1
  payload_risk_count                             : 0
  payload_changed_without_sampled_valid_reporting: summary
  scan_complete                                  : true
  analysis_complete                              : true
  response_truncated                             : false
  total_count                                    : 1
  returned_count                                 : 1
  value_width_complete                           : true

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge                      : negedge
  valid                     : ai_complex_top.glitch_sig
  payloads                  : [empty]
  begin                     : 0ns
  end                       : 200ns
  sampled_low_cycles        : 20
  sampled_unknown_cycles    : 0
  raw_valid_transition_count: 3
  payload_transition_count  : 0

findings:
  type                   severity  raw_begin  raw_end  previous_sample_edge  next_sample_edge  nearest_sample_edge  raw_valid  sampled_valid  reason
  unsampled_valid_pulse  warning   96ns       96.2ns   90ns                  100ns             100ns                1'd1       1'd0           valid was high between sample edges but not high at any sampled edge
```

## 148. `signal.stability` / `value-format:bin`

- returncode: 0
- elapsed_ms: 141
- bytes: 578
- sha256: `63769af11c24abfa8519d95a37c9b42b6f0cc6f1eebbc82e756700b89a59728e`
- request: `{"action": "signal.stability", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.stable_sig", "time_range": {"begin": "0ns", "end": "400ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.stability role=value-format:bin bytes=578 sha256=63769af11c24abfa8519d95a37c9b42b6f0cc6f1eebbc82e756700b89a59728e -->
```xout
@xdebug.signal.stability.v1
summary:
  stable                          : true
  change_row_count                : 1
  actual_transition_count         : 0
  scan_stopped_on_first_transition: false
  scan_complete                   : true
  analysis_complete               : true
  response_truncated              : false
  total_count                     : 1
  returned_count                  : 1
  value_width_complete            : true

data:
  signal: ai_complex_top.stable_sig
  begin : 0ns
  end   : 400ns

changes:
  time  value
  0ns   1'b1
  includes_initial_value: true
```

## 149. `signal.stability` / `value-format:dec`

- returncode: 0
- elapsed_ms: 133
- bytes: 578
- sha256: `bd2adb7c4be69fbacabdbd69ba383ef32d298cf877a83c46a6819ccf4e435983`
- request: `{"action": "signal.stability", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.stable_sig", "time_range": {"begin": "0ns", "end": "400ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.stability role=value-format:dec bytes=578 sha256=bd2adb7c4be69fbacabdbd69ba383ef32d298cf877a83c46a6819ccf4e435983 -->
```xout
@xdebug.signal.stability.v1
summary:
  stable                          : true
  change_row_count                : 1
  actual_transition_count         : 0
  scan_stopped_on_first_transition: false
  scan_complete                   : true
  analysis_complete               : true
  response_truncated              : false
  total_count                     : 1
  returned_count                  : 1
  value_width_complete            : true

data:
  signal: ai_complex_top.stable_sig
  begin : 0ns
  end   : 400ns

changes:
  time  value
  0ns   1'd1
  includes_initial_value: true
```

## 150. `signal.statistics` / `value-format:bin`

- returncode: 0
- elapsed_ms: 153
- bytes: 1195
- sha256: `f5ce190ec93e439e2602c5589b501b0cc92257b8a8c7b82ceb4df2b22d5508bc`
- request: `{"action": "signal.statistics", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "signal": "ai_complex_top.hs_valid", "time_range": {"begin": "120ns", "end": "210ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.statistics role=value-format:bin bytes=1195 sha256=f5ce190ec93e439e2602c5589b501b0cc92257b8a8c7b82ceb4df2b22d5508bc -->
```xout
@xdebug.signal.statistics.v1
summary:
  signal               : ai_complex_top.hs_valid
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  sample_count         : 10
  known_count          : 10
  unknown_count        : 0
  begin                : 120ns
  end                  : 210ns
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 2
  returned_count       : 2
  value_width_complete : true

evidence:
  time   kind          value
  130ns  value_change  1'b1
  200ns  value_change  1'b0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge             : negedge
  transition_count : 2
  first            : 1'b0
  final            : 1'b0
  min              : 1'b0
  max              : 1'b1
  low_cycles       : 3
  high_cycles      : 7
  high_ratio       : 0.7
  first_change_time: 130ns
  last_change_time : 200ns

activity:
  high_burst_count: 1
  first_high_time : 130ns
  last_high_time  : 190ns
  last_fall_time  : 200ns
  max_high_cycles : 7
```

## 151. `signal.statistics` / `value-format:dec`

- returncode: 0
- elapsed_ms: 169
- bytes: 1195
- sha256: `c89044b2b9bbc51c97f41b08def4f42ba80a8e08c034d0c7900f4ccab12b96ad`
- request: `{"action": "signal.statistics", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "signal": "ai_complex_top.hs_valid", "time_range": {"begin": "120ns", "end": "210ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.statistics role=value-format:dec bytes=1195 sha256=c89044b2b9bbc51c97f41b08def4f42ba80a8e08c034d0c7900f4ccab12b96ad -->
```xout
@xdebug.signal.statistics.v1
summary:
  signal               : ai_complex_top.hs_valid
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  sample_count         : 10
  known_count          : 10
  unknown_count        : 0
  begin                : 120ns
  end                  : 210ns
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 2
  returned_count       : 2
  value_width_complete : true

evidence:
  time   kind          value
  130ns  value_change  1'd1
  200ns  value_change  1'd0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge             : negedge
  transition_count : 2
  first            : 1'd0
  final            : 1'd0
  min              : 1'd0
  max              : 1'd1
  low_cycles       : 3
  high_cycles      : 7
  high_ratio       : 0.7
  first_change_time: 130ns
  last_change_time : 200ns

activity:
  high_burst_count: 1
  first_high_time : 130ns
  last_high_time  : 190ns
  last_fall_time  : 200ns
  max_high_cycles : 7
```

## 152. `signal.xz_verify` / `value-format:bin`

- returncode: 0
- elapsed_ms: 133
- bytes: 645
- sha256: `01cc078bacfa8f241f9722e99e24a476ab9fa57bb32acfcbef166e26179b2c42`
- request: `{"action": "signal.xz_verify", "api_version": "xdebug.v1", "args": {"expected_state": "x", "signal": "ai_complex_top.xz_bus", "time_range": {"begin": "86ns", "end": "94ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.xz_verify role=value-format:bin bytes=645 sha256=01cc078bacfa8f241f9722e99e24a476ab9fa57bb32acfcbef166e26179b2c42 -->
```xout
@xdebug.signal.xz_verify.v1
summary:
  signal              : ai_complex_top.xz_bus
  expected_state      : x
  match_mode          : exact
  verdict             : pass
  always_matched      : true
  checked_value_count : 1
  stop_reason         : window_end
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: true

time_range:
  begin                : 86ns
  end                  : 94ns
  initial_value        : 8'bxxxxxxxx
  sample_time_semantics: sample_time is the finalized raw waveform value-change time in the closed interval
```

## 153. `signal.xz_verify` / `value-format:dec`

- returncode: 0
- elapsed_ms: 144
- bytes: 670
- sha256: `ee3f95dfecd0a92e52ec6f5f833eb25be5548351005973802556dab2806cfc9c`
- request: `{"action": "signal.xz_verify", "api_version": "xdebug.v1", "args": {"expected_state": "x", "signal": "ai_complex_top.xz_bus", "time_range": {"begin": "86ns", "end": "94ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=signal.xz_verify role=value-format:dec bytes=670 sha256=ee3f95dfecd0a92e52ec6f5f833eb25be5548351005973802556dab2806cfc9c -->
```xout
@xdebug.signal.xz_verify.v1
summary:
  signal              : ai_complex_top.xz_bus
  expected_state      : x
  match_mode          : exact
  verdict             : pass
  always_matched      : true
  checked_value_count : 1
  stop_reason         : window_end
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 1
  returned_count      : 1
  value_width_complete: true

time_range:
  begin                : 86ns
  end                  : 94ns
  initial_value        : 8'bxxxxxxxx requested=dec reason=X/Z
  sample_time_semantics: sample_time is the finalized raw waveform value-change time in the closed interval
```

## 154. `stream.export` / `value-format:bin`

- returncode: 0
- elapsed_ms: 177
- bytes: 1315
- sha256: `4d6181ade4b402525b2f20b884b9565b9e80e35c0a66e8d9168660353eef60de`
- request: `{"action": "stream.export", "api_version": "xdebug.v1", "args": {"cache_scope": "full", "kind": "transfer", "output": {"file_format": "tsv", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/stream.tsv-bin"}, "stream": "ready_stream", "time_range": {"begin": "0ns", "end": "1us"}, "value_format": "bin"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.export role=value-format:bin bytes=1315 sha256=4d6181ade4b402525b2f20b884b9565b9e80e35c0a66e8d9168660353eef60de -->
```xout
@xdebug.stream.export.v1
summary:
  stream                      : ready_stream
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : false
  clock_edges                 : 100
  vld_cycles                  : 88
  transfer_count              : 71
  stall_cycles                : 17
  stall_windows               : 17
  complete_packet_count       : 0
  partial_packet_count        : 0
  packet_count_status         : not_configured
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 71
  returned_count              : 71
  first_transfer_time         : 75ns
  last_transfer_time          : 995ns
  first_stall_time            : 115ns
  last_stall_time             : 965ns
  status                      : written
  output_written              : true
  row_count                   : 71
  line_limit                  : 16
  kind                        : transfer
```

## 155. `stream.export` / `value-format:dec`

- returncode: 0
- elapsed_ms: 181
- bytes: 1315
- sha256: `4d6181ade4b402525b2f20b884b9565b9e80e35c0a66e8d9168660353eef60de`
- request: `{"action": "stream.export", "api_version": "xdebug.v1", "args": {"cache_scope": "full", "kind": "transfer", "output": {"file_format": "tsv", "path": "/tmp/pytest-of-ryan/pytest-591/test_all_runtime_actions_emit_0/stream.tsv-dec"}, "stream": "ready_stream", "time_range": {"begin": "0ns", "end": "1us"}, "value_format": "dec"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.export role=value-format:dec bytes=1315 sha256=4d6181ade4b402525b2f20b884b9565b9e80e35c0a66e8d9168660353eef60de -->
```xout
@xdebug.stream.export.v1
summary:
  stream                      : ready_stream
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : false
  clock_edges                 : 100
  vld_cycles                  : 88
  transfer_count              : 71
  stall_cycles                : 17
  stall_windows               : 17
  complete_packet_count       : 0
  partial_packet_count        : 0
  packet_count_status         : not_configured
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 71
  returned_count              : 71
  first_transfer_time         : 75ns
  last_transfer_time          : 995ns
  first_stall_time            : 115ns
  last_stall_time             : 965ns
  status                      : written
  output_written              : true
  row_count                   : 71
  line_limit                  : 16
  kind                        : transfer
```

## 156. `stream.query` / `value-format:bin`

- returncode: 0
- elapsed_ms: 391
- bytes: 2548
- sha256: `d275ed1977cd63b00ca028e540974ffcbaacb50fa1ace76669c8c502e0a082d2`
- request: `{"action": "stream.query", "api_version": "xdebug.v1", "args": {"packet_index": 3, "query": "packet_at", "stream": "ready_packet", "time_range": {"begin": "0ns", "end": "1us"}, "value_format": "bin"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.query role=value-format:bin bytes=2548 sha256=d275ed1977cd63b00ca028e540974ffcbaacb50fa1ace76669c8c502e0a082d2 -->
```xout
@xdebug.stream.query.v1
summary:
  stream                      : ready_packet
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : true
  clock_edges                 : 100
  vld_cycles                  : 94
  transfer_count              : 94
  stall_cycles                : 0
  stall_windows               : 0
  complete_packet_count       : 23
  partial_packet_count        : 1
  packet_count_status         : ambiguous
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 1
  returned_count              : 1
  truncation_scopes           : [empty]

requested_range:
  begin: 0ns
  end  : 1000ns

scanned_range:
  begin               : 5ns
  end                 : 995ns
  first_transfer_time : 65ns
  last_transfer_time  : 995ns
  query               : packet_at
  filter_applied      : false
  value_width_complete: true
  width_diagnostics   : [empty]
  found               : true

packet:
  packet_index            : 3
  start_cycle             : 18
  end_cycle               : 21
  start_time              : 185ns
  end_time                : 215ns
  beat_count              : 4
  partial_begin           : false
  partial_end             : false
  packet_stable_fields    : opcode=8'b10100011
  packet_stable_mismatches: [empty]
  first_fields            : data=32'b01000000000000000000000000001100 seq=16'b0000000000001100
  last_fields             : data=32'b01000000000000000000000000001111 seq=16'b0000000000001111

packet.beat_fields_preview:
  tail              : [empty]
  scan_complete     : true
  analysis_complete : true
  response_truncated: false
  total_count       : 4
  returned_count    : 4
  truncation_scopes : [empty]

packet.beat_fields_preview.head:
  cycle  time   beat_index  fields
  18     185ns  0           data=32'b01000000000000000000000000001100 seq=16'b0000000000001100
  19     195ns  1           data=32'b01000000000000000000000000001101 seq=16'b0000000000001101
  20     205ns  2           data=32'b01000000000000000000000000001110 seq=16'b0000000000001110
  21     215ns  3           data=32'b01000000000000000000000000001111 seq=16'b0000000000001111
```

## 157. `stream.query` / `value-format:dec`

- returncode: 0
- elapsed_ms: 403
- bytes: 2327
- sha256: `6210af302ad35b881ee7431a44d4d45136a196bba55387a95aa483fe78fb9ee1`
- request: `{"action": "stream.query", "api_version": "xdebug.v1", "args": {"packet_index": 3, "query": "packet_at", "stream": "ready_packet", "time_range": {"begin": "0ns", "end": "1us"}, "value_format": "dec"}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=stream.query role=value-format:dec bytes=2327 sha256=6210af302ad35b881ee7431a44d4d45136a196bba55387a95aa483fe78fb9ee1 -->
```xout
@xdebug.stream.query.v1
summary:
  stream                      : ready_packet
  sampling_mode               : clock_edge
  clock                       : clk
  edge                        : posedge
  sample_point                : before
  sample_time_semantics       : time is sample_time
  handshake                   : vld/rdy
  packet_enabled              : true
  clock_edges                 : 100
  vld_cycles                  : 94
  transfer_count              : 94
  stall_cycles                : 0
  stall_windows               : 0
  complete_packet_count       : 23
  partial_packet_count        : 1
  packet_count_status         : ambiguous
  control_xz_count            : 0
  data_xz_count               : 0
  ready_bp_conflict_count     : 0
  packet_stable_mismatch_count: 0
  scan_complete               : true
  analysis_complete           : true
  response_truncated          : false
  total_count                 : 1
  returned_count              : 1
  truncation_scopes           : [empty]

requested_range:
  begin: 0ns
  end  : 1000ns

scanned_range:
  begin               : 5ns
  end                 : 995ns
  first_transfer_time : 65ns
  last_transfer_time  : 995ns
  query               : packet_at
  filter_applied      : false
  value_width_complete: true
  width_diagnostics   : [empty]
  found               : true

packet:
  packet_index            : 3
  start_cycle             : 18
  end_cycle               : 21
  start_time              : 185ns
  end_time                : 215ns
  beat_count              : 4
  partial_begin           : false
  partial_end             : false
  packet_stable_fields    : opcode=8'd163
  packet_stable_mismatches: [empty]
  first_fields            : data=32'd1073741836 seq=16'd12
  last_fields             : data=32'd1073741839 seq=16'd15

packet.beat_fields_preview:
  tail              : [empty]
  scan_complete     : true
  analysis_complete : true
  response_truncated: false
  total_count       : 4
  returned_count    : 4
  truncation_scopes : [empty]

packet.beat_fields_preview.head:
  cycle  time   beat_index  fields
  18     185ns  0           data=32'd1073741836 seq=16'd12
  19     195ns  1           data=32'd1073741837 seq=16'd13
  20     205ns  2           data=32'd1073741838 seq=16'd14
  21     215ns  3           data=32'd1073741839 seq=16'd15
```

## 158. `trace.active_driver_chain` / `value-format:bin`

- returncode: 0
- elapsed_ms: 151
- bytes: 1424
- sha256: `04e8d4a857b07eac33662176ae3a59470f701bbe53f1e94ac7be69a55382444c`
- request: `{"action": "trace.active_driver_chain", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y", "time": "26ns", "value_format": "bin"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.active_driver_chain role=value-format:bin bytes=1424 sha256=04e8d4a857b07eac33662176ae3a59470f701bbe53f1e94ac7be69a55382444c -->
```xout
@xdebug.trace.active_driver_chain.v1
summary:
  signal              : active_semantics_tb.u_dut.mux_y
  time                : 26ns
  termination         : unresolved
  termination_detail  : unresolved
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 2
  returned_count      : 2
  value_width_complete: false
  truncation_scopes   : [empty]

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:48
   45 |     if (sel)
   46 |       mux_y = data_a;                 // MUX_ACTIVE_A
   47 |     else
>  48 |       mux_y = data_b;                 // MUX_ACTIVE_B
   49 |   end
   50 | 
   51 |   always_ff @(posedge clk or negedge rst_n) begin

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     0    26ns  root      48    active_semantics_tb.u_dut.data_b -> active_semantics_tb.u_dut.mux_y

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:169
  166 |     req0 = 1'b0;
  167 |     req1 = 1'b1;         // arb_q captures payload1 at 25ns
  168 |     data_a = 8'hA1;
> 169 |     data_b = 8'hB2;
  170 |     payload = 8'h11;
  171 |     payload0 = 8'hC1;
  172 |     payload1 = 8'hD1;

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     1    22ns  driver    169   active_semantics_tb.data_b -> active_semantics_tb.u_dut.data_b
```

## 159. `trace.active_driver_chain` / `value-format:dec`

- returncode: 0
- elapsed_ms: 143
- bytes: 1424
- sha256: `04e8d4a857b07eac33662176ae3a59470f701bbe53f1e94ac7be69a55382444c`
- request: `{"action": "trace.active_driver_chain", "api_version": "xdebug.v1", "args": {"signal": "active_semantics_tb.u_dut.mux_y", "time": "26ns", "value_format": "dec"}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=trace.active_driver_chain role=value-format:dec bytes=1424 sha256=04e8d4a857b07eac33662176ae3a59470f701bbe53f1e94ac7be69a55382444c -->
```xout
@xdebug.trace.active_driver_chain.v1
summary:
  signal              : active_semantics_tb.u_dut.mux_y
  time                : 26ns
  termination         : unresolved
  termination_detail  : unresolved
  scan_complete       : true
  analysis_complete   : true
  response_truncated  : false
  total_count         : 2
  returned_count      : 2
  value_width_complete: false
  truncation_scopes   : [empty]

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:48
   45 |     if (sel)
   46 |       mux_y = data_a;                 // MUX_ACTIVE_A
   47 |     else
>  48 |       mux_y = data_b;                 // MUX_ACTIVE_B
   49 |   end
   50 | 
   51 |   always_ff @(posedge clk or negedge rst_n) begin

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     0    26ns  root      48    active_semantics_tb.u_dut.data_b -> active_semantics_tb.u_dut.mux_y

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/active_semantics/active_semantics_tb.sv:169
  166 |     req0 = 1'b0;
  167 |     req1 = 1'b1;         // arb_q captures payload1 at 25ns
  168 |     data_a = 8'hA1;
> 169 |     data_b = 8'hB2;
  170 |     payload = 8'h11;
  171 |     payload0 = 8'hC1;
  172 |     payload1 = 8'hD1;

active_signals:
  chain  hop  time  relation  line  signal_path
  c0     1    22ns  driver    169   active_semantics_tb.data_b -> active_semantics_tb.u_dut.data_b
```

## 160. `trace.x_origin` / `value-format:bin`

- returncode: 0
- elapsed_ms: 206
- bytes: 3261
- sha256: `063acdf91eafc3d830c907f5dc571c03f8167564b24c9f4361a884d088bc3ac4`
- request: `{"action": "trace.x_origin", "api_version": "xdebug.v1", "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "bin"}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=trace.x_origin role=value-format:bin bytes=3261 sha256=063acdf91eafc3d830c907f5dc571c03f8167564b24c9f4361a884d088bc3ac4 -->
```xout
@xdebug.trace.x_origin.v1
summary:
  signal               : trace_x_xprop_tb.observed
  query_time           : 18ns
  termination          : origin_found
  evidence_status      : best_effort
  chain_count          : 1
  completed_chain_count: 1
  limited_chain_count  : 0
  hop_count            : 8
  origin_count         : 1
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 1
  returned_count       : 1
  value_width_complete : true
  truncation_scopes    : [empty]

query:
  query_time: 18ns
  value     : 8'bx01xx10x
  x_mask    : 8'b10011001

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:40-43
   37 |     if (!rst_n)
   38 |       observed_q <= '0;
   39 |     else
>  40 |       observed_q <= bus.data;
   41 |   end
   42 | 
>  43 |   always_comb observed = observed_q;
   44 | endmodule
   45 | 
   46 | module trace_x_alias_source(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     0    15ns          15ns         root      43    trace_x_xprop_tb.observed
  c0     1    15ns          15ns         rhs       40    trace_x_xprop_tb.u_sink.observed_q

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:6
    3 | interface trace_x_if(input logic clk);
    4 |   logic [7:0] data;
    5 |   modport source(output data, input clk);
>   6 |   modport sink(input data, input clk);
    7 | endinterface
    8 | 
    9 | module trace_x_source(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     2    10ns          10ns         rhs       6     trace_x_xprop_tb.u_sink.bus.data

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:24-27
   21 |     if (sel)
   22 |       stage1 = stage0;
   23 |     else
>  24 |       stage1 = alternate_data;
   25 |   end
   26 | 
>  27 |   always_comb bus.data = stage1;
   28 | endmodule
   29 | 
   30 | module trace_x_sink(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     3    10ns          10ns         port      27    trace_x_xprop_tb.link.data
  c0     4    10ns          10ns         port      27    trace_x_xprop_tb.link.source.data
  c0     5    10ns          10ns         rhs       24    trace_x_xprop_tb.u_source.stage1

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:171
  168 | 
  169 |     #7 rst_n = 1'b1;
  170 |     #3 begin
> 171 |       sel = 1'bx;              // tmerge: two different branches produce X
  172 |       multi_rhs_a = 8'hxx;     // two simultaneous RHS X sources
  173 |       multi_rhs_b = 8'hxx;
  174 |       ctrl_x = 1'bx;           // control and selected RHS are both X

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     6    10ns          10ns         control   171   trace_x_xprop_tb.u_source.sel
  c0     7    10ns          10ns         port      171   trace_x_xprop_tb.sel

chains:
  chain  status        current_signal        current_x_onset_time  value  reason
  c0     origin_found  trace_x_xprop_tb.sel  10ns                  1'bx   candidate_x_source
```

## 161. `trace.x_origin` / `value-format:dec`

- returncode: 0
- elapsed_ms: 248
- bytes: 3309
- sha256: `4265df69f90a8c8ca3e72ec33614acfe2e8ce72725a1bcaeada3a6874e023168`
- request: `{"action": "trace.x_origin", "api_version": "xdebug.v1", "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "dec"}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=trace.x_origin role=value-format:dec bytes=3309 sha256=4265df69f90a8c8ca3e72ec33614acfe2e8ce72725a1bcaeada3a6874e023168 -->
```xout
@xdebug.trace.x_origin.v1
summary:
  signal               : trace_x_xprop_tb.observed
  query_time           : 18ns
  termination          : origin_found
  evidence_status      : best_effort
  chain_count          : 1
  completed_chain_count: 1
  limited_chain_count  : 0
  hop_count            : 8
  origin_count         : 1
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 1
  returned_count       : 1
  value_width_complete : true
  truncation_scopes    : [empty]

query:
  query_time: 18ns
  value     : 8'bx01xx10x
  x_mask    : 8'b10011001

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:40-43
   37 |     if (!rst_n)
   38 |       observed_q <= '0;
   39 |     else
>  40 |       observed_q <= bus.data;
   41 |   end
   42 | 
>  43 |   always_comb observed = observed_q;
   44 | endmodule
   45 | 
   46 | module trace_x_alias_source(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     0    15ns          15ns         root      43    trace_x_xprop_tb.observed
  c0     1    15ns          15ns         rhs       40    trace_x_xprop_tb.u_sink.observed_q

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:6
    3 | interface trace_x_if(input logic clk);
    4 |   logic [7:0] data;
    5 |   modport source(output data, input clk);
>   6 |   modport sink(input data, input clk);
    7 | endinterface
    8 | 
    9 | module trace_x_source(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     2    10ns          10ns         rhs       6     trace_x_xprop_tb.u_sink.bus.data

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:24-27
   21 |     if (sel)
   22 |       stage1 = stage0;
   23 |     else
>  24 |       stage1 = alternate_data;
   25 |   end
   26 | 
>  27 |   always_comb bus.data = stage1;
   28 | endmodule
   29 | 
   30 | module trace_x_sink(

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     3    10ns          10ns         port      27    trace_x_xprop_tb.link.data
  c0     4    10ns          10ns         port      27    trace_x_xprop_tb.link.source.data
  c0     5    10ns          10ns         rhs       24    trace_x_xprop_tb.u_source.stage1

source: /home/RD/ryan/work/xverif/xdebug/testdata/combined/trace_x_xprop/trace_x_xprop_tb.sv:171
  168 | 
  169 |     #7 rst_n = 1'b1;
  170 |     #3 begin
> 171 |       sel = 1'bx;              // tmerge: two different branches produce X
  172 |       multi_rhs_a = 8'hxx;     // two simultaneous RHS X sources
  173 |       multi_rhs_b = 8'hxx;
  174 |       ctrl_x = 1'bx;           // control and selected RHS are both X

active_signals:
  chain  hop  x_onset_time  active_time  relation  line  signal_path
  c0     6    10ns          10ns         control   171   trace_x_xprop_tb.u_source.sel
  c0     7    10ns          10ns         port      171   trace_x_xprop_tb.sel

chains:
  chain  status        current_signal        current_x_onset_time  value                          reason
  c0     origin_found  trace_x_xprop_tb.sel  10ns                  1'bx requested=dec reason=X/Z  candidate_x_source
```

## 162. `value.at` / `value-format:bin`

- returncode: 0
- elapsed_ms: 166
- bytes: 119
- sha256: `843245e8f83466ccbad100de026136634fdb9d434f5811376f522ef4c3dd86f9`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.sig_a", "times": ["75ns", "95ns"], "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=value.at role=value-format:bin bytes=119 sha256=843245e8f83466ccbad100de026136634fdb9d434f5811376f522ef4c3dd86f9 -->
```xout
@xdebug.value.at.v1
values:
  name                  75ns         95ns
  ai_complex_top.sig_a  8'b00100010  8'b00100010
```

## 163. `value.at` / `value-format:dec`

- returncode: 0
- elapsed_ms: 178
- bytes: 101
- sha256: `33d0a421548e602b17094cb87e8a4bcfc2904eddf9d64707ecc19d54aaf95345`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "ai_complex_top.sig_a", "times": ["75ns", "95ns"], "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=value.at role=value-format:dec bytes=101 sha256=33d0a421548e602b17094cb87e8a4bcfc2904eddf9d64707ecc19d54aaf95345 -->
```xout
@xdebug.value.at.v1
values:
  name                  75ns   95ns
  ai_complex_top.sig_a  8'd34  8'd34
```

## 164. `verify.conditions` / `value-format:bin`

- returncode: 0
- elapsed_ms: 131
- bytes: 857
- sha256: `9602a028664d503826affbddb26c4ab1da0eca4692df194b57a8628f68af27de`
- request: `{"action": "verify.conditions", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "conditions": [{"expr": "a == 8'hff"}], "signals": {"a": "ai_complex_top.sig_a"}, "time": "95ns", "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=verify.conditions role=value-format:bin bytes=857 sha256=9602a028664d503826affbddb26c4ab1da0eca4692df194b57a8628f68af27de -->
```xout
@xdebug.verify.conditions.v1
summary:
  time                : 95ns
  execution_ok        : true
  verdict             : fail
  condition_count     : 1
  all_passed          : false
  passed              : 0
  failed              : 1
  unknown             : 0
  value_width_complete: true

checks:
  time  expr        known  status  pass   value
  95ns  a == 8'hff  true   fail    false  1'b0

clock_context:
  clock                           : ai_complex_top.clk
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false
  requested_time                  : 95ns
  requested_any_edge_hit          : false
  requested_target_edge_hit       : false
  previous_sample_time            : 90ns
  bracket_complete                : false

clock_context.requested_sampling:
  edge: negedge

clock_context.effective_sampling:
  edge: negedge
```

## 165. `verify.conditions` / `value-format:dec`

- returncode: 0
- elapsed_ms: 132
- bytes: 941
- sha256: `8d6c70905dca83081832d9ac6f619cdd5c6243f21088c44b3f0ebeb02f22b103`
- request: `{"action": "verify.conditions", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "conditions": [{"expr": "a == 8'hff"}], "signals": {"a": "ai_complex_top.sig_a"}, "time": "95ns", "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=verify.conditions role=value-format:dec bytes=941 sha256=8d6c70905dca83081832d9ac6f619cdd5c6243f21088c44b3f0ebeb02f22b103 -->
```xout
@xdebug.verify.conditions.v1
summary:
  time                : 95ns
  execution_ok        : true
  verdict             : fail
  condition_count     : 1
  all_passed          : false
  passed              : 0
  failed              : 1
  unknown             : 0
  value_width_complete: true

checks:
  time  expr        known  status  pass   value
  95ns  a == 8'hff  true   fail    false  1'd0

clock_context:
  clock                           : ai_complex_top.clk
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false
  requested_time                  : 95ns
  requested_any_edge_hit          : true
  clock_edge_kind                 : posedge
  requested_target_edge_hit       : false
  previous_sample_time            : 90ns
  next_sample_time                : 100ns
  bracket_complete                : true

clock_context.requested_sampling:
  edge: negedge

clock_context.effective_sampling:
  edge: negedge
```

## 166. `window.verify` / `value-format:bin`

- returncode: 0
- elapsed_ms: 126
- bytes: 919
- sha256: `e4d501dfb7671826e9670ac17eabf461f11d4b121c028119e9c860f808b51445`
- request: `{"action": "window.verify", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "conditions": [{"expr": "valid || !valid", "mode": "always"}], "signals": {"valid": "ai_complex_top.hs_valid"}, "time_range": {"begin": "140ns", "end": "175ns"}, "value_format": "bin"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=window.verify role=value-format:bin bytes=919 sha256=e4d501dfb7671826e9670ac17eabf461f11d4b121c028119e9c860f808b51445 -->
```xout
@xdebug.window.verify.v1
summary:
  execution_ok         : true
  verdict              : pass
  all_passed           : true
  sample_count         : 4
  failed_samples       : 0
  unknown_samples      : 0
  proof_begin          : 140ns
  proof_end            : 175ns
  stop_reason          : window_end
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 0
  returned_count       : 0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge: negedge

conditions:
  expr           mode    passed  pass_samples  failed_samples  unknown_samples
  valid||!valid  always  true    4             0               0
  findings: [empty]
```

## 167. `window.verify` / `value-format:dec`

- returncode: 0
- elapsed_ms: 138
- bytes: 919
- sha256: `e4d501dfb7671826e9670ac17eabf461f11d4b121c028119e9c860f808b51445`
- request: `{"action": "window.verify", "api_version": "xdebug.v1", "args": {"clock": "ai_complex_top.clk", "conditions": [{"expr": "valid || !valid", "mode": "always"}], "signals": {"valid": "ai_complex_top.hs_valid"}, "time_range": {"begin": "140ns", "end": "175ns"}, "value_format": "dec"}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=window.verify role=value-format:dec bytes=919 sha256=e4d501dfb7671826e9670ac17eabf461f11d4b121c028119e9c860f808b51445 -->
```xout
@xdebug.window.verify.v1
summary:
  execution_ok         : true
  verdict              : pass
  all_passed           : true
  sample_count         : 4
  failed_samples       : 0
  unknown_samples      : 0
  proof_begin          : 140ns
  proof_end            : 175ns
  stop_reason          : window_end
  sampling_mode        : clock_edge
  clock                : ai_complex_top.clk
  sample_time_semantics: time is sample_time
  scan_complete        : true
  analysis_complete    : true
  response_truncated   : false
  total_count          : 0
  returned_count       : 0

sampling:
  sample_point_applied            : false
  sample_point_ignored_for_negedge: false

sampling.requested:
  edge: negedge

sampling.effective:
  edge: negedge

conditions:
  expr           mode    passed  pass_samples  failed_samples  unknown_samples
  valid||!valid  always  true    4             0               0
  findings: [empty]
```

## 168. `value.at` / `xz:hex`

- returncode: 0
- elapsed_ms: 235
- bytes: 111
- sha256: `5f5830c4d127197971d9d219fa05fc16535def3176ca79a1bcf26fdac6fe9b53`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "hex"}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=value.at role=xz:hex bytes=111 sha256=5f5830c4d127197971d9d219fa05fc16535def3176ca79a1bcf26fdac6fe9b53 -->
```xout
@xdebug.value.at.v1
values:
  name                       18ns
  trace_x_xprop_tb.observed  8'hx bits=x01x_x10x
```

## 169. `value.at` / `xz:bin`

- returncode: 0
- elapsed_ms: 162
- bytes: 103
- sha256: `40fa208e243de4c2ae90b483bd48830e29be5e0828eb290c2ab7762cab2a4c02`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "bin"}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=value.at role=xz:bin bytes=103 sha256=40fa208e243de4c2ae90b483bd48830e29be5e0828eb290c2ab7762cab2a4c02 -->
```xout
@xdebug.value.at.v1
values:
  name                       18ns
  trace_x_xprop_tb.observed  8'bx01xx10x
```

## 170. `value.at` / `xz:dec`

- returncode: 0
- elapsed_ms: 167
- bytes: 128
- sha256: `33797e31f288eb8e6135343d6a833e1c10cdce19c855fcb8302aa0c4e4ae5b27`
- request: `{"action": "value.at", "api_version": "xdebug.v1", "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "dec"}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=value.at role=xz:dec bytes=128 sha256=33797e31f288eb8e6135343d6a833e1c10cdce19c855fcb8302aa0c4e4ae5b27 -->
```xout
@xdebug.value.at.v1
values:
  name                       18ns
  trace_x_xprop_tb.observed  8'bx01xx10x requested=dec reason=X/Z
```

## 171. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 159
- bytes: 665
- sha256: `1014891e0f273bd507de96fa8542351142363f14edce395338d00c6d353b1663`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_p"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=665 sha256=1014891e0f273bd507de96fa8542351142363f14edce395338d00c6d353b1663 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_p
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.apb_vip/versions/5b0d1be836520bd8421bb4193d12949c5ba4c3098cc94bd1dede3d5a81fb4709-prepare-7hdsu4cf/resources/out/regression/test/apb_vip_test/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-f7e10f18f07ae65d.sock
  server_pid : 1640280
  created_at : 1785788269
  last_active: 1785788294
  fsdb_mtime : 1785305080
  fsdb_size  : 21053
  fsdb_dev   : 64770
  fsdb_inode : 53481561
```

## 172. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 710
- bytes: 672
- sha256: `6df6f3dfccaaa91a37e12b65c47fd56fbcb77daaf1447693ed130816cc3da868`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_a"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=672 sha256=6df6f3dfccaaa91a37e12b65c47fd56fbcb77daaf1447693ed130816cc3da868 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_a
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.axi_vip/versions/b7a0d81ad90d77fb97c0da6239e1e69a10671089527be0adf5e7a21e5507c1f0-prepare-21inkxj8/resources/out/regression/test/axi_multi_id_test/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-2ff3d0ff242e4327.sock
  server_pid : 1640334
  created_at : 1785788270
  last_active: 1785788296
  fsdb_mtime : 1785305487
  fsdb_size  : 4464084
  fsdb_dev   : 64770
  fsdb_inode : 53481826
```

## 173. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 184
- bytes: 643
- sha256: `5bda6e293fa785dfe26a02e5e8546a2fe82adf9f1717e496c834896772add5c7`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_w"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=643 sha256=5bda6e293fa785dfe26a02e5e8546a2fe82adf9f1717e496c834896772add5c7 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_w
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-4ad5c73dc970c961.sock
  server_pid : 1640500
  created_at : 1785788279
  last_active: 1785788303
  fsdb_mtime : 1785305001
  fsdb_size  : 9232
  fsdb_dev   : 64770
  fsdb_inode : 53480732
```

## 174. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 193
- bytes: 662
- sha256: `2c9a2b230f81ba630c915b29841c3601c518261b261a16645b1d282edd11b1d9`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_e"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=662 sha256=2c9a2b230f81ba630c915b29841c3601c518261b261a16645b1d282edd11b1d9 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_e
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.xif_event/versions/664ac163a4de5950f40c81bafad04508bf5ea6a1fadbf1eca21aeabe1306ee44-prepare-kh7pipx2/resources/out/waves/xif_event_multi_if_test.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-e799fe8782371102.sock
  server_pid : 1640518
  created_at : 1785788280
  last_active: 1785788298
  fsdb_mtime : 1785305859
  fsdb_size  : 12029
  fsdb_dev   : 64770
  fsdb_inode : 53742495
```

## 175. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 214
- bytes: 964
- sha256: `6c5f808650d9641864215785791b259f7f57a2ad55f0521f744fdcd983c47126`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_c"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=964 sha256=6c5f808650d9641864215785791b259f7f57a2ad55f0521f744fdcd983c47126 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id  : native_xout_c
  mode        : combined
  transport   : uds
  server_host : eda.ic
  daidir      : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/simv.daidir
  fsdb        : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.active_semantics/versions/585596a0b185a09e028b04fdc2653542b7a5eef8b0293f4cd5746ca579a54ea3-prepare-8nux5yqa/resources/out/waves.fsdb
  socket_path : /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-39188bccaca42ae0.sock
  server_pid  : 1640751
  created_at  : 1785788283
  last_active : 1785788301
  daidir_mtime: 1785304981
  daidir_size : 4096
  daidir_dev  : 64770
  daidir_inode: 53220003
  fsdb_mtime  : 1785304981
  fsdb_size   : 10908
  fsdb_dev    : 64770
  fsdb_inode  : 53220060
```

## 176. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 184
- bytes: 650
- sha256: `46db7a8a12cd80c6c5f8beb7e30513bc83afdd480e3fcac5fee184cbf02299ca`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "primary_session_open"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=650 sha256=46db7a8a12cd80c6c5f8beb7e30513bc83afdd480e3fcac5fee184cbf02299ca -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : primary_session_open
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.ai_complex_wave/versions/a5da8054a5d15693369316da2fb212b16fc10e5e065bc3fe560800ce7e14ee17-prepare-6mprgsuo/resources/out/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-5587796343cff99d.sock
  server_pid : 1640829
  created_at : 1785788285
  last_active: 1785788285
  fsdb_mtime : 1785305001
  fsdb_size  : 9232
  fsdb_dev   : 64770
  fsdb_inode : 53480732
```

## 177. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 210
- bytes: 638
- sha256: `7517ca19b6d0a159fc3f8ac11997c8b9d58826effaab206ad30eb193ced632a2`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_s"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=638 sha256=7517ca19b6d0a159fc3f8ac11997c8b9d58826effaab206ad30eb193ced632a2 -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id : native_xout_s
  mode       : waveform
  transport  : uds
  server_host: eda.ic
  fsdb       : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.stream_v1/versions/5eca27af24084f076f68c6a77c6fe0cb9e0a152332912dbf074cabc3b4600ede-prepare-qrcrom97/resources/out/waves.fsdb
  socket_path: /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-329e20c50517aa11.sock
  server_pid : 1640890
  created_at : 1785788286
  last_active: 1785788301
  fsdb_mtime : 1785305005
  fsdb_size  : 60523
  fsdb_dev   : 64770
  fsdb_inode : 53480884
```

## 178. `session.close` / `teardown`

- returncode: 0
- elapsed_ms: 217
- bytes: 958
- sha256: `f8bfe73e5a91823f8ad5095aa804c0e2f9e14de52893e8898140e1dfd6731f8d`
- request: `{"action": "session.close", "api_version": "xdebug.v1", "args": {}, "target": {"session_id": "native_xout_x"}}`

<!-- XOUT_BODY phase=final action=session.close role=teardown bytes=958 sha256=f8bfe73e5a91823f8ad5095aa804c0e2f9e14de52893e8898140e1dfd6731f8d -->
```xout
@xdebug.session.close.v1
summary:
  removed: true

removed_session:
  session_id  : native_xout_x
  mode        : combined
  transport   : uds
  server_host : eda.ic
  daidir      : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.trace_x_xprop/versions/8efd40845b015e9729763fe8fad3cff590e4399458e80b01b29874d830af18da-prepare-xe7akjqx/resources/out/simv.daidir
  fsdb        : /home/RD/ryan/work/xverif/.xverif-test-cache/fixtures/xdebug.trace_x_xprop/versions/8efd40845b015e9729763fe8fad3cff590e4399458e80b01b29874d830af18da-prepare-xe7akjqx/resources/out/waves.fsdb
  socket_path : /home/RD/ryan/work/tmp/xverif-a3d-rebuild.J9L50K/repo/tmp/xdebug-1001-792645f4a0f30d8c.sock
  server_pid  : 1640979
  created_at  : 1785788290
  last_active : 1785788303
  daidir_mtime: 1785304995
  daidir_size : 4096
  daidir_dev  : 64770
  daidir_inode: 53480428
  fsdb_mtime  : 1785304996
  fsdb_size   : 10730
  fsdb_dev    : 64770
  fsdb_inode  : 53480581
```

