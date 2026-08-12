# xverif 统一测试合同

全仓测试只有根级 catalog-driven pytest plugin 一个公开入口。suite 身份、gate、能力、Fixture、资源和 required/optional 归属以 `testinfra/catalog.v1.yaml` 为唯一事实源；数据库生成合同以 `testinfra/fixtures.v1.yaml` 为事实源。

## 门禁

```bash
python3 tools/create_python_environment.py
conda activate ./.conda-xverif
python3 tools/check_test_environment.py --gate fast
pytest --xverif-gate fast
export XVERIF_TEST_EXECUTION_ENV=host  # 仅在已经进入沙箱外 host 后设置
pytest --xverif-gate regression -n auto
pytest --xverif-gate nightly -n auto
```

依赖以 suite 为检查边界。focused suite 只检查自己的 capability 与 Fixture；普通 gate 消费缓存时不检查 Fixture builder 的 VCS/VIP/XIF 构建依赖。构建依赖只在对应 prepare/validation 前检查。

- `fast`：static/unit/component 中的 hermetic 测试，不启动 NPI、VCS、VIP、MCP 子进程。
- `regression`：全部 required deterministic fast/medium suite；可读取缓存 FSDB/daidir，但不生成。
- `nightly`：包含 regression，并增加 VIP、active-trace、xif-event、xsva VCS 和 optional real LSF。
- 裸 `pytest`、未知 suite、互斥操作组合都是 usage error。
- `XVERIF_TEST_EXECUTION_ENV` 只接受 `host`/`sandbox`；它只写 environment snapshot，不改变真实权限边界。沙箱外 gate 必须显式设为 `host`。

查看无副作用执行计划：

```bash
pytest --xverif-gate regression --xverif-plan
pytest --xverif-gate fast --xverif-plan --xverif-changed HEAD
```

focused 执行只能在 suite 所属 gate 内收窄：

```bash
pytest --xverif-gate fast --xverif-suite xdebug.static
pytest --xverif-gate regression --xverif-suite xdebug.contract
pytest --xverif-gate nightly --xverif-suite xdebug.active_trace.phase5
```

## 数据库 Fixture

普通 gate 不调用 VCS/simv。显式准备、校验和清理：

```bash
pytest --xverif-prepare xdebug.active_driver
pytest --xverif-prepare all-generated
pytest --xverif-fixture-validation --xverif-all-fixtures
pytest --xverif-fixture-validation --xverif-changed HEAD
pytest --xverif-fixture-clean
pytest --xverif-results-clean
```

Fixture 使用内容指纹、工具兼容 identity、跨进程锁、staging、backend-aware semantic probe、不可变 generation 和原子 `current.json` 切换。builder 与 probe 只在显式 prepare/validation 发布新 generation 时执行；普通 gate 和 cache-hit prepare 只读 manifest/产物，不重新编译或仿真。cache miss、指纹不符或输出不完整会在 suite 启动前形成 required preflight ERROR，并给出 prepare 命令；不会自动生成、SKIP 或换数据源。连续两次 prepare 的第二次必须命中缓存。

`xdebug.axi_vip` 一次编译后运行 stress、固定 delay，以及 seed 7/19/73 三组固定
seed 随机 delay。每组必须发布 FSDB、simulation log 和独立 pin-handshake oracle；
测试比较 VIP scoreboard、pin oracle 与 xdebug canonical transaction，并检查三种
AW/W phase order、最终 outstanding、dependency violation 和 `full_scan_count=1`。
同一 engine 的 query/analysis/pair/timeline/outlier/cursor/export 全流程还必须通过
test-only probe 证明只发布一次 AXI canonical build、只扫描一次 FSDB，并分别触发
address、ID 和 handshake lazy index；1-byte hard budget 必须稳定返回
`ANALYSIS_MEMORY_LIMIT_EXCEEDED`，不得改用 range、offline 或其它 backend。

`xdebug.apb_vip` 除 wait-state、PSLVERR、statistics filter 和 cursor 既有语义外，
还必须通过 test-only probe 证明 query/export/statistics/transfer_window/cursor 全流程只发布一次
APB canonical build、只扫描一次 FSDB，并触发独立 AddressIndex。1-byte soft budget
覆盖两个语义 config 逐出后 generation cursor 位置恢复；1-byte hard budget 必须返回
`ANALYSIS_MEMORY_LIMIT_EXCEEDED`，不得缩小范围或切换 backend。
`apb.export` 同时覆盖无 path 的 8 行 preview、TSV/CSV 单 data artifact + meta、
direction/address/time_range 过滤、artifact byte/count/range 一致性以及 preview/written
严格响应分支；不得把 preview 截断误报为扫描不完整。

`xdebug.analysis_cache_benchmark` 是 nightly 的独立 performance/semantic suite，消费
APB VIP、AXI VIP 和 stream v1 三个已发布 fixture，不生成数据库。它在三个独立
engine 上记录 cold/hot P50/P95、scanner、estimated bytes 和 RSS delta，并校验 compact
stream JSON/XOUT golden。冻结数据与阶段阈值维护在
`xdebug/tests/benchmark/analysis_cache_thresholds.v1.json`；wall-time 阈值不得复制到
普通 unit/contract suite。Phase 4A 额外强制 stream columnar cold P95、RSS 上限和相对
Phase 0 至少 25% RSS 降幅；Phase 4B 再要求 stream cold scanner 为 1、热请求 scanner
为 0 且满足 hot P95 门槛。阈值失败必须修正实现或重新取得正式基线，不能放宽断言。

`xdebug.cpp_unit` 的 `test_analysis_repository` 用 fake entry 覆盖版本化 key、full/range、
strict env、building 重入、failure/bad_alloc 回滚、index-first 与跨协议 LRU、soft
oversize entry/index、hard/saturated accounting、typed ensure、无 access side effect 的
peek、generation cursor，以及 stream full 成功替换同语义 ranges、full 失败保留 ranges
的事务性合同；`test_axi_transaction_tracker` 同时检查 pending working-set
估算覆盖动态 payload；
`test_stream_manager` 覆盖语义 fingerprint、同目录原子 replace 及 write/rename fault。
`test_stream_base_analysis` 构造 1000-transfer legacy/columnar 形状，检查所有 field column
与 transfer ordinal 对齐，并要求 base estimator 小于 legacy estimator。

`xdebug.stream` 设置 `XDEBUG_TEST_STREAM_DIFFERENTIAL=1`，对真实 stream v1
fixture 的 config/query/export/dynamic validate 矩阵同时执行新 QueryView 与 legacy
oracle。差分只比较各 action 实际消费的 packet projection，同时总是覆盖完整 summary、
transfer/stall、matched count 和首末 evidence；不暴露 public legacy action。Phase 4B
同时检查跨 action 热命中、两个独立 range、full 事务性替换 ranges、range 复用 full、
同语义 replace 复用、语义变更失效、soft LRU 重建、hard-limit 预扫描拒绝，以及静态
validate 不创建 cache entry。builtin `batch` 用同一 engine 覆盖
query→export→dynamic validate、range→range→full→range，并以连续 hard-limit 失败证明
失败子请求不留下 building entry。

## 结果与诊断

每次 gate 写入 `.xverif-test-results/<run>/`：

- `report.json`：suite/node、phase、outcome、duration、error layer。
- `junit.xml`：标准 JUnit 报告。
- `environment.json`：去敏 capability 与 host/sandbox 类别。
- `suites/<id>/`：external stdout/stderr 与 pytest 捕获日志。

失败 suite 可显式诊断重跑：

```bash
pytest --rerun-failed .xverif-test-results/<run>/report.json
```

重跑生成独立 run，并记录 `parent_report`；不会改写原 gate 结论，也不会自动 retry。

## 执行环境

- 沙箱内：plan/collect、catalog/schema/testinfra、`fast`。
- 沙箱外：NPI/FSDB/daidir engine、MCP stdio/UDS/process、fake/real LSF、VCS/simv、VIP、fixture prepare/validation。
- 沙箱内的 EDA/进程失败不能判定为产品回归。
- real LSF 仅在 nightly 中 optional；缺失会明确 SKIP。其它 required suite 不得自行 skip。失效的 xring realdata suite 已移除。

## 维护规则

- 新增测试必须先登记 catalog；不得新增 Makefile test target、独立 gate shell 或局部 pytest.ini。
- 测试消费数据库必须声明 Fixture；测试函数不得执行 `make clean run/fixture`。
- active-trace case 由公共 `testinfra/leaf/prepare_active_trace.py` 和 `cases.v1.yaml` 管理，不恢复逐 case Makefile。
- C++/Vim/命令测试通过 catalog external item 运行，stdout/stderr 归档并受 process-group timeout/cleanup 管理。
- 正式 pytest 入口统一设置 `XVERIF_TEST_TMPDIR=<repo>/tmp`，测试进程不得把运行态文件写入用户的 `~/.xdebug` 或 `~/.xverif`。
- pytest 主进程为本轮测试设置共享 `XDEBUG_TEST_OWNER_TOKEN`；所有 xdist worker 和 external suite 继承该 token。session finish 必须清理带本轮 token 的全部 `xdebug-engine`，先发 `SIGTERM`，超时后发 `SIGKILL` 并等待退出；仍有残留时整轮测试判失败。
- 修改源码后跑 focused suite；跨层或高风险变更跑 regression/nightly。最终交付必须先 `make clean all`，再跑完整 gate。
