# xdebug 架构说明书维护日志

## 2026-08-12

- 新增 `apb.export` 公开合同：完整 time range、顶层 direction/address、固定 8 行 preview
  或单 TSV/CSV data artifact + meta；响应分别发布扫描/范围内/匹配/预览/artifact bytes
  与 canonical completeness，不提供 query/stream fallback。
- logging 降级改为进程内累计并仅首次向 stderr 输出无敏感上下文的稳定告警；公开
  session manifest 解析失败时保留原文件。`trace.driver/load` 内部 evidence JSON 解码
  失败改为聚合 diagnostic，并以 `analysis_complete:false` 和
  `analysis_internal_json` 完整性范围显式发布，JSON/XOUT 均透传。

## 2026-07-28

- `rc.generate` 删除 group 配置中的 `expanded` 输入；保留 subgroup 递归，生成的
  `addGroup` / `addSubGroup` 固定不带 `-e`，旧 `expanded` 配置明确报错。
- `trace.x` 以非 port 的 RHS/control 语义前缀归并 module port、
  interface/modport/ref alias 路线，只返回最终有效链，并在归并后应用
  `limits.max_chains`。
- `trace.active_driver_chain` 将 runtime/schema 的 `max_depth` 默认值统一为 8，并从
  公共 limits 合同删除未消费的 `max_alias_candidates`。

## 2026-07-20

- 清理运行时本机路径绑定：统一临时目录解析，ProcessRunner 支持通过 `PATH` 查找系统工具，日志打包不再固定工具或临时目录绝对路径。
- 删除未消费的旧 AXI/VIP 默认根与真实波形脚本死默认值；真实 VIP 环境只由 suite 依赖和环境变量提供。

## 2026-07-18

- `trace.x` 升级为受 `max_chains` 约束的多分支 DFS：RHS/control 同等按 X 可见性
  追踪，每个分支逐跳重新定位 X onset；XOUT 复用 source grouping 并在末尾列出 chain。
- `trace.x` 与 `trace.active_driver_chain` 在 max-depth frontier 返回 signal/time/value
  和可直接调用的续查/增深建议；含 X 的值统一使用带宽与 `'h`/`'b`/`'d` 前缀。

- 新增 experimental combined action `trace.x`：查询点含 X 时复用 active-trace 图穿过
  assignment、module port、interface/modport 和更早 active time；控制 X、动态 select
  等候选原因保持 `best_effort` 证据等级。
- `value.at` / `value.batch_at` 的 clock 改为可选：无 clock 直接点读精确 FSDB time，
  有 clock 保持原采样上下文；默认 hex，公开值统一使用 `'h` / `'b` / `'d` 前缀。
- 新增正式 VCS `-xprop=tmerge` fixture 与 regression suite，覆盖跨 always/module/
  interface、控制 X、直接 driver X、越界 bit-select 和 temporal active trace。

## 2026-07-16

- 建立分析缓存 Phase 0 test-only probe、APB/AXI/stream size estimator 与 nightly
  `xdebug.analysis_cache_benchmark`，固化独立 engine 的 cold/hot、scanner、RSS、
  estimated bytes 和 stream compact JSON/XOUT golden。
- 基于 AXI stress 与 20,000-transfer stream 实测冻结 estimator safety factor 2.0、
  soft 1 GiB、hard 2 GiB，以及后续 repository/columnar/cache 阶段的性能和内存门槛。
- Phase 0 不改变 public action、schema、扫描范围、排序或输出；AnalysisRepository
  仍按独立计划后续实施。
- 完成 Phase 1 engine-owned `AnalysisRepository`：strict soft/hard 环境合同、2.0
  safety-factor accounting、typed canonical store、独立 lazy index、index-first 纯 LRU、
  building/ready 回滚、oversize、hard-limit/bad_alloc 和 generation cursor。
- stream config replace 改为同目录 temp + fsync + atomic rename，并仅在成功后以忽略
  name/description 的语义 fingerprint 通知 repository；同语义复用，差异语义失效。
- 完成 Phase 2 AXI repository 迁移：保留既有 `AxiTransactionTracker`/`AxiResult` 和
  输出顺序，所有 AXI action 复用单次 canonical scan；address、ID、handshake index
  独立 lazy build，cursor 按 generation 在 soft LRU 重建后续用。
- AXI 扫描与 index 构建纳入 working-set/hard-limit accounting，best-effort bad_alloc
  转换为结构化内存错误；由 AXI response schema 生成器统一发布预算错误字段。
- 完成 Phase 3 APB repository 迁移：APB query/statistics/transfer_window/cursor 复用单次
  canonical scan；扫描期冻结既有地址解析语义，AddressIndex 独立 lazy build 和记账。
- APB canonical/index 构建纳入 working-set/hard-limit accounting，soft LRU 后 generation
  cursor 按原 position 续用；APB VIP 与 nightly benchmark 固化单扫描、逐出和硬上限合同。
- 完成 Phase 4A Stream 列式 base 与单请求 QueryView：所有 sample 保留 summary/stall/XZ
  最小元数据，完整 beat/stable fields 仅按 transfer column 保存，packet 仅保存 transfer
  引用、边界、channel 与 stable mismatch。
- 三个动态 stream action 默认使用新 analyzer；test-only legacy adapter 在正式 stream
  suite 中逐字段比较 summary、transfer/stall、query packet projection 与 filter evidence，
  不提供 public bypass。nightly benchmark 固化 cold P95、RSS 上限和至少 25% RSS 降幅。
- Phase 4A 尚不启用跨请求 cache；stream full/range scope、repository 复用、预算/LRU 与
  schema/skill 合同留在独立 Phase 4B 实施。
- 完成 Phase 4B Stream repository 迁移：`stream.query`、`stream.export` 与动态
  `stream.validate` 共享版本化语义 base，`cache_scope` 默认 `full` 并支持显式 `range`；
  静态 validate 不创建 cache entry。
- range 优先复用同语义 full；full 成功发布后事务性清除同语义 ranges，失败保持旧
  ranges；不同 ranges 不合并或自动提升。soft LRU、hard-limit 预扫描拒绝和 config
  replace 语义失效均由正式 stream/unit/benchmark 回归固化。
- 同步 native schema、request examples、MCP schema projection 与 xverif skill 决策指导；
  hard-limit 后只允许调用方显式发起新的 range 请求，engine 不缩小范围或切换 backend。

## 2026-07-14

- 新增 `apb.statistics` / `axi.statistics`，基于 canonical 协议缓存按方向、AXI ID 与
  exact/range/mask 地址过滤统计 completed transaction；补齐 APB scan diagnostics，
  XOUT 固定解释 `unresolved_transaction_count`，避免 AI 猜测字段语义。
- 删除 Stream `data_fields` 配置和 runtime 兼容路径，命名逐拍字段统一使用
  `beat_fields`；inline schema 与 config file parser 均明确拒绝旧字段。
- 为 `stream.query` 增加扫描期多字段 exact/range/mask 过滤，data、beat 和
  packet-stable 字段在过滤视图内统一；packet 按 SOP/EOP 边界匹配并返回整包。
- 抽取通用任意位宽 value filter helper，Stream、APB statistics 和 AXI
  statistics 共用 literal 解析、三态 AND 与 mask/XZ 判断。

## 2026-07-07

- 初始化 `doc/agents/xdebug/` 说明书目录。
- 建立入口页、架构分层、action 开发、统一组件、通信协议、log、session、schema 校验、编码要求和测试矩阵。
- 根目录 `AGENTS.md` 引用本说明书，要求 xdebug 架构和 action 相关变更同步维护。

## 2026-07-09

- xverif skill 拆分为 `xverif-cli` 和 `xverif-mcp` 后，更新 `action-development.md` 的 skill 同步清单。
- 新增/修改 xdebug action 时，需要同时检查 CLI JSON envelope 文档和 MCP tool 参数壳文档是否需要同步。

## 2026-07-09

- 执行 xdebug 错误反馈、输出合同与表达式统一计划后，同步更新说明书中的 public 参数词典和错误提示要求。
- `schema-validation.md`、`coding-standards.md`、`action-development.md` 改为使用 `line_limit`、`args.output.verbose` 和 export action 描述大结果控制，移除旧 public `include_*` / 裸 `limit` 说法。
- skill 文档同步强调 `INVALID_TIME`、`correct_example`、`next_actions` 等结构化错误字段优先用于修复下一次请求。

## 2026-07-10

- xdebug/xcov MCP SDK 与 SDK-free wrapper 统一为 managed open/list/doctor/close/kill/gc 生命周期，backend 差异由 capability 表描述。
- 增加 tombstone、compact/verbose public record、固定 xdebug native admin path、xcov loop-owned cleanup 和 coverage native lifecycle guard。
- `actions` 默认返回 compact names，verbose 返回 descriptors；batch 汇总 failed indexes/codes/layers，unknown action 返回相近候选。
- 2026-07-14：收紧 P2 合同：`apb.query` 默认读写混合时间序列；Stream 使用
  `packet_stable_fields` 和 complete/partial packet 计数；`actions` catalog 增加
  category/requires/purposes/双语 keyword 过滤并移除 status 过滤；action 双语描述与
  purposes 统一由 `actions.yaml` 生成。

## 2026-07-20

- engine 在 `npi_init`、`npi_load_design`、`npi_fsdb_open` 启动窗口捕获原始
  stdout/stderr 到权限为 `0600` 的 `npi_startup.log`，成功与失败 session 均保留。
- `session.open` 按 NPI 启动阶段返回稳定错误码、`failure_phase` 和 diagnostic log
  标识；常见 license 变量均缺失时只给 advisory，不提前 hard fail。
- `env.snapshot` 增加 license environment presence，明确禁止记录 license value；
  log doctor/tail、schema、xdebug/xverif-admin 文档和回归测试同步更新。
