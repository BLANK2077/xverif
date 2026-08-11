# xcov 全量代码安全、正确性与性能评审报告

日期：2026-08-11  
评审基线：`06d5df6`（`master`）  
评审方式：源码逐模块检查、公开合同对照、正式 catalog suite、真实 VDB/NPI/URG 实测、定向复杂度基准

## 1. 结论摘要

本次评审覆盖 `xcov/xcov` 全部 17 个 Python 模块、`xcov/tests`、三类真实 fixture、
`xverif_mcp` 的 xcov adapter/session 链路、`skills/xverif` 的 xcov 合同，以及相邻的
`skills/x-npi/scripts/x_npi/coverage.py`。

结论：当前实现的基础合同与真实回归较完整，但不能判定为“没有漏洞”。共识别：

- 4 项 P1：2 项安全/完整性漏洞、1 项可导致 exclusion reason 永久丢失的数据安全问题、
  1 项公开查询结果错误；
- 9 项 P2：scope 选择错误、二次复杂度、导出膨胀、关闭时重复 URG、资源上限缺失、
  CSV 解析退化、NPI 运行时隔离、模块/工具路径可信边界、相邻 x-npi 的静默 fallback；
- 3 项 P3：临时目录残留、非原子写入和可观测性写入静默失败。

建议先阻断 P1，再优化 P2。当前最危险的两个安全问题是：

1. `xcov.run-manifest.v1` 的目录哈希编码存在结构歧义，可构造不同目录树得到相同摘要，
   因而 provenance gate 不能提供其宣称的内容完整性保证。
2. 四类公开 export 都没有执行公开 schema 声明的输出路径策略，MCP/CLI 调用者可将
   URG、JSON、XOUT 或 EL 写入进程权限允许的任意目录。

## 2. 严重级别与发现总表

| ID | 级别 | 类型 | 结论 |
| --- | --- | --- | --- |
| XCOV-SEC-01 | P1 | 完整性 | VDB 目录树哈希编码存在确定性结构碰撞 |
| XCOV-SEC-02 | P1 | 任意文件写 | coverage export 绕过 `allow_absolute_path` 与相对路径安全策略 |
| XCOV-DATA-01 | P1 | 数据丢失 | `session.close` 无条件丢弃未持久化 exclusion reason |
| XCOV-COR-01 | P1 | 正确性 | `code_coverage.summary.metrics` 在 URG 快路径被忽略 |
| XCOV-COR-02 | P2 | 正确性 | NPI scope 使用裸前缀匹配，边界错误且不能剪枝 |
| XCOV-PERF-01 | P2 | 性能/DoS | scope coverage 聚合为 O(N²) |
| XCOV-PERF-02 | P2 | 性能/存储 | code export 为每个 scope×metric 重复保存完整 URG 原文 |
| XCOV-PERF-03 | P2 | 性能 | 正常关闭 session 会再次运行 URG |
| XCOV-PERF-04 | P2 | 性能/DoS | CSV 多行 quoted field 解析可退化为 O(N²) |
| XCOV-RES-01 | P2 | 资源耗尽 | stdio、schema 数组和扫描结果缺少前置资源上限 |
| XCOV-OPS-01 | P2 | 生命周期 | native SessionManager 宣称多 session，但 pynpi 是进程级单实例 |
| XCOV-SEC-03 | P2 | 供应链/执行 | `pynpi` 导入与 URG 解析允许早先 `sys.path`/`PATH` 覆盖正式工具 |
| XCOV-COR-03 | P2 | 相邻 skill 正确性 | x-npi coverage helper 静默吞掉 NPI 异常并做零参数 fallback |
| XCOV-REL-01 | P3 | 可靠性 | functional/assert export 与 CSV format 不是事务式发布 |
| XCOV-RES-02 | P3 | 资源泄漏 | 自动创建的 exclusion cache 目录在 close 后不清理 |
| XCOV-OBS-01 | P3 | 可观测性 | manifest/NDJSON 写入异常被静默吞掉且 manifest 非原子更新 |

P1 表示应在继续扩大 MCP/自动化使用前修复；P2 表示应进入近期版本；P3 可随相关重构处理。

## 3. P1 详细发现

### XCOV-SEC-01：VDB 目录树哈希存在结构碰撞

证据：`xcov/xcov/provenance.py:30-55` 将每个条目编码为：

```text
F\\0<relative-path>\\0<raw-file-bytes>
```

文件内容之后没有长度、结束标记或逐文件摘要。由于文件内容允许包含任意字节，它可以伪造
下一条 `F\\0...` 记录。本次实测构造：

```text
tree-one/a = b"XF\\0b\\0Y"

tree-two/a = b"X"
tree-two/b = b"Y"
```

两棵目录的 `stat().st_size` 都是 4096，`resource_sha256()` 均得到：

```text
42df9d2bc63e9d9c2362f76e16f244b53439929ac402a1ce1ddd62b3eb8efe09
```

这不是 SHA-256 密码学碰撞，而是摘要输入序列本身相同。攻击者只要能够替换待校验资源，
就可以用结构不同的目录绕过 `run_manifest` 内容身份校验。

修复建议：

- 使用无歧义编码，例如 `type + path_length + path + content_length + content`；
- 更推荐为每个条目计算独立摘要，再对 `(type, path, entry_digest)` 做 Merkle/长度前缀聚合；
- 明确编码并校验 regular file、directory、symlink 等 entry type；
- `size_bytes` 对目录不要使用目录 inode 的 `st_size`，改为 canonical tree byte count 或
  manifest 中的文件数/总字节数；
- 增加上述两棵树摘要必须不同的回归用例，并覆盖二进制文件名/内容、空文件、symlink。

### XCOV-SEC-02：coverage export 可绕过输出路径安全合同

统一路径函数 `xcov/xcov/query.py:160-171` 要求：绝对路径只有在
`allow_absolute_path=true` 时可用，相对路径不得含 `..`，并应归一到
`.xverif/xcov_exports/`。但该函数没有被任何 export handler 调用：

- `xcov/xcov/actions.py:528-536` 直接将用户 `output.path` 传给 `os.makedirs`；
- `xcov/xcov/actions.py:608-611` 直接对 code export 的 `Path(args["output"]["path"])`
  执行 `mkdir`；
- `xcov/xcov/actions.py:1072-1077` 的 EL export 调用 `_export_output_path()`，但
  `actions.py:2106-2111` 的该函数也只是原样返回字符串；
- `xcov/xcov/schemas.py:259-263` 却向调用者公开了 `allow_absolute_path`。

`actions.py` 虽然 import 了 `resolve_artifact_path`，全包搜索只有定义和 import，没有调用，
进一步证明当前安全函数是未接线的死路径。

真实 `xcov.modinfo_complex` 导出验证中，未提供 `allow_absolute_path` 的绝对 `/tmp/...` 路径
仍成功生成了 34 个文件。现有 `test_modinfo_complex.py` 和 `test_urg_backend.py` 也把这种行为
当作成功路径，说明这是被测试固化的合同漂移。

影响：通过 MCP/CLI 调用 xcov 的主体可以在 xcov 进程权限范围内创建目录，并覆盖固定名称
的 `.xcov_hier.txt`、URG 报告、`functional.json`、`assert.json` 等文件；相对 symlink 还可
绕过只检查字符串 `..` 的逻辑。

修复建议：

- 所有 export 统一调用一个 canonical `resolve_artifact_path()`；
- schema 与 handler 只保留一处 `allow_absolute_path` 语义；
- 对默认根目录做 `resolve()` 后的 containment 检查，并处理 symlink/TOCTOU；
- 使用 staging directory + `os.replace` 发布所有 export；
- 增加绝对路径未授权、`..`、相对 symlink、已有目标文件和并发发布测试。

### XCOV-DATA-01：关闭 session 会无条件丢失 exclusion reason

`xcov/xcov/actions.py:367-375` 直接关闭；`xcov/xcov/session.py:38-45` 随后清空
`exclusion_records`，没有检查 dirty reason、CSV 导出状态或 EL 导出状态。现有
`test_exclusions.py:318-329` 明确断言未持久化原因会在 close 后消失。

这与 `skills/xverif/SKILL.md` 和 `skills/xverif/references/xcov.md` 强调的生命周期风险一致，
但仅靠 agent 提示不能保护 CLI、MCP 或人工调用。reason 丢失后无法从原生 EL 恢复。

修复建议：

- session 维护 `reason_dirty`、`csv_export_revision`、`el_export_revision`；
- close 在 dirty 时返回 `UNPERSISTED_EXCLUSION_REASON`，默认不关闭；
- 如需强制关闭，公开显式 `confirm_discard_reasons=true`，并在响应中给出丢弃计数；
- MCP close/kill/GC 同步传播这一合同，kill/进程异常则记录不可恢复告警；
- 将当前“丢失即成功”的测试改为拒绝关闭和显式强制关闭两组测试。

### XCOV-COR-01：`code_coverage.summary.metrics` 被 URG 路径忽略

`xcov/xcov/actions.py:470-500` 解析了 `metrics`，但 URG 快路径直接把完整
`scope_metrics` 传给 `_code_coverage_from_urg()`；`actions.py:1858-1906` 聚合其中全部 metric，
没有接收或应用 requested metrics。

真实 comprehensive VDB 实测：

```json
{
  "requested_metrics": ["line"],
  "returned_metrics": ["branch", "condition", "fsm", "line", "toggle"]
}
```

响应同时在 `summary.metrics` 声明 `['line']`，因此 summary 与 data 自相矛盾，可能让 AI/脚本
误用未请求指标。

修复建议：让 `_code_coverage_from_urg(scope_metrics, group_by, metrics)` 显式接收白名单，
在聚合前过滤；增加真实 URG fixture 的单 metric、多 metric、scope+metric 交叉测试，断言
`data.items` 的 metric 集合精确等于请求集合。

## 4. P2 正确性、安全与生命周期问题

### XCOV-COR-02：scope 裸前缀匹配

`xcov/xcov/backend.py:1630-1659` 使用 `inst_full.startswith(scope)`；functional walker 在
`backend.py:1776` 同样使用裸前缀。相邻 x-npi helper 的
`skills/x-npi/scripts/x_npi/coverage.py` 也使用相同模式。

后果：请求 `top.u_core1` 会错误匹配 `top.u_core10`；请求不存在的前缀仍递归访问所有实例。
actions 层已有正确辅助函数 `_is_descendant(scope, root)`，但 backend 没有复用。

修复建议：统一为 `candidate == root or candidate.startswith(root + ".")`；在进入子树前根据
“当前节点是 root 祖先/后代/无关”剪枝；增加 `u1/u10`、escaped hierarchy、generate block 测试。

### XCOV-OPS-01：native 多 session 与进程级 pynpi 生命周期不兼容

native `SessionManager` 是 session 字典，可接受多个不同名称；每个
`NpiCoverageBackend.__post_init__()` 都调用一次 `npisys.init`，close 则调用 `npisys.end`。
真实实测在第一个 session alive 时打开第二个 session：vendor 报告 repeated `npi_init`，
第二次 open 返回 `NPI_INIT_FAILED`。

MCP manager 通过“每 session 一个 stdio-loop 子进程”规避了此问题，但 native CLI/嵌入式调用
仍暴露误导性的多 session 接口。

修复建议：native 端在调用 NPI 前明确限制单 alive session，返回
`NPI_PROCESS_SESSION_CAPACITY`；或将 native manager 也改成每 session 独立 worker 进程。

### XCOV-SEC-03：正式 pynpi/URG 工具可被搜索路径抢占

- `xcov/xcov/eda.py:71-75` 把 vendor NPI 路径追加到 `sys.path` 尾部，工作目录、调用者注入
  路径和 site-packages 中更早的同名 `pynpi` 可先被导入；
- `eda.py:48-56` 在 `VCS_HOME` 缺失或无效时静默改用 `PATH` 中的 `urg`；这既违反本仓库
  “不静默 fallback”的运行原则，也可能执行非预期二进制。

修复建议：通过显式 import spec 从已校验的 vendor 根加载并核对模块 `__file__`；URG 应选择
一个已确认来源，`VCS_HOME` 无效时返回明确错误，只有调用者显式选择 `tool_source=path`
时才解析 PATH；日志记录工具真实路径与版本，但不记录敏感环境。

### XCOV-COR-03：x-npi coverage helper 静默 fallback

`skills/x-npi/scripts/x_npi/coverage.py` 的 `_safe_call()` 捕获任意异常后再用零参数重试，失败后
返回 `None`；`_release()` 也吞掉所有异常。这会把 license、坏 handle、签名变化、vendor
内部错误重新解释成“字段不存在/空数据”，与 skill 的“不猜 API、不 fallback、保留完整性”
原则相反。scope 裸前缀问题也存在于该文件。

建议迁移到 xcov 已有的显式 `NpiMethodContract` 风格：只允许声明过的签名、错误带 operation/
expected/actual，release 错误至少累计进完整性字段。该问题位于相邻 skill helper，不影响
xcov runtime 的严格 binding，但会影响用 x-npi 生成的 coverage 报告。

## 5. 性能与资源分析

### XCOV-PERF-01：scope 聚合为 O(N²)

`xcov/xcov/actions.py:1796-1855` 对每个 scope 再遍历所有叶 scope 计算 subtree totals。
合成但调用真实实现函数的基准如下：

| 叶 scope 数 | 耗时（秒） | 峰值 tracemalloc（KiB） |
| ---: | ---: | ---: |
| 100 | 0.0096 | 61.5 |
| 500 | 0.2261 | 294.3 |
| 1000 | 0.8975 | 562.5 |
| 2000 | 3.7373 | 1208.0 |

规模翻倍时耗时约 4 倍，和源码复杂度一致。大型 SoC hierarchy 会在一个本应轻量的
`scope.summary` 上消耗显著 CPU。

优化建议：一次遍历每个叶 scope，将计数沿祖先链累加，复杂度降为 O(N×depth)；指定 root
时只构造该 root 需要的祖先/后代；session 内缓存 immutable URG scope tree 和 rollup。

### XCOV-PERF-02：code export 原文为 scope×metric 重复保存

`xcov/xcov/actions.py:648-667` 已正确把多 scope、多 metric 合并为一次 URG，这是积极设计；
但 `actions.py:680-695` 在每个 metric 目录写入同一份 `combined_text`。

真实 modinfo_complex VDB、2 scope×5 metric 实测：

- 导出耗时：1.030 秒；
- artifact：34 个文件，共 1,433,044 bytes；
- raw URG：10 份，每份 110,780 bytes；
- 10 份 SHA-256 完全相同，共 1,107,800 bytes，占总产物约 77.3%。

优化建议：bundle 根目录只保留一个 `raw/modinfo.urg.txt`，metric XOUT 通过相对路径引用；
或按 metric/scope 裁剪原文 section，保证 raw 可追溯但不复制完整报告。解析前建立一次 section
索引，避免每个 scope×metric 重复 regex 扫描完整文本。

### XCOV-PERF-03：正常 close 再次执行 URG

`NpiCoverageBackend.close()` 在 `backend.py:931-936` 清空 URG cache；随后
`Dispatcher._session_close()` 调用 `sess.public_json()`，而 `session.py:47-52` 又调用 backend
`summary()/top_scopes()`，导致 `_ensure_urg()` 再跑一次 URG。

真实 comprehensive VDB：open 1.048 秒，close 0.869 秒；close 仍返回 top scope，证明关闭后
重新生成了 URG 数据。MCP 集成中每个测试都 open/close，这会直接放大总耗时和 license/tool
负载。

修复建议：close 前捕获 public snapshot，或让 close 响应只使用 session 已缓存的 immutable
metadata；backend close 不应触发新的外部工具。

### XCOV-RES-01：限制发生在完整扫描之后，输入本身无上限

- `cli.py:64` 的 stdio-loop 和 `cli.py:132-138` 的 once 模式读取任意长度输入；
- schema `_string()` 没有通用 `maxLength`，`_array()` 没有 `maxItems`；export scopes、exports、
  coverage_refs 都可任意增长；
- `backend.items()` 和 canonicalizer 物化完整 List；
- `query.apply_output()` 在完整扫描、过滤、排序后才执行 `max_items` 截断。

因此 `limits.max_items=1` 只限制响应，不限制 NPI 调用、内存和 CPU。stdio-loop/MCP 的可信边界
一旦扩大，单个请求即可造成高内存或长时间占用。

修复建议：增加 transport byte limit、字符串/数组 max、export scopes 上限；walker 接受
predicate/limit 并报告 `scan_complete=false`；需要完整聚合的 action 使用流式 accumulator，
不要物化所有 coverage row；对子进程设置整体 request timeout 与可取消点。

### XCOV-PERF-04：CSV 多行字段解析可退化为 O(n²)

`exclusions_csv.py:163-185` 每收到一个仍处于 quoted field 的物理行，都执行
`"".join(buffer)` 并从头扫描引号。超长多行 reason 会重复复制和扫描累计文本，且文件无大小/
行数限制。

建议用增量 quote state 或直接基于 `csv.reader` 的流式迭代；增加文件 byte/row/reason 长度上限。

## 6. P3 可靠性与可观测性

### XCOV-REL-01：部分写路径不是事务式发布

code export 使用 staging + `os.replace`，CSV export/compile 也有回滚，这是优点。但：

- functional/assert export 直接在最终目录运行 URG，再写 JSON/XOUT；结构化步骤失败会留下
  看似成功的部分报告；
- `exclude.csv.format(write=true)` 逐文件 `write_text`，中途失败会形成三类 CSV 版本不一致；
- `export.exclude` 直接让 vendor 写最终 EL 路径，没有 temp + publish 保护。

建议统一 staging、fsync（如需要跨崩溃保证）和单点 publish；响应只发布最终目录。

### XCOV-RES-02：自动 cache 目录不清理

`session.py:87-95` 在 exclusion dirty 且调用者未提供 cache 时用 `tempfile.mkdtemp()` 创建目录，
但 close 只清字段，不删除自有目录。长期 MCP/CLI 使用会在 `/tmp` 残留 EL cache。

建议记录 `cache_owned_by_session`，只在 close 时清理自动目录；用户提供目录绝不自动删除。

### XCOV-OBS-01：日志失败静默且 manifest 非原子

`logging.py:150-177` 用 `write_text` 直接覆盖 session manifest，解析/写入异常全部吞掉；
`logging.py:218-234` 对 append 异常也静默。并发进程写同一 session path 时可能出现 manifest
损坏或 NDJSON 交错，调用者不知道观测链已丢失。

建议 manifest 用同目录临时文件 + `os.replace`；session log 路径引入进程/owner namespace；
日志失败至少发到 stderr，并在公开响应附加 `observability` 状态（MCP manager 已有类似模式）。

## 7. 已确认的积极设计

以下实现明显降低了风险，应在修复时保留：

- JSON parser 拒绝重复 key 和 NaN/Infinity；公开 request/response schema 默认关闭未知字段；
- xcov runtime 的 NPI 调用使用显式 method contract，不做异常后变更签名的 fallback；
- coverage score 只计入 metric 对应 score-bearing 类型，百分比使用 `covered/coverable`；
- status 保留 excluded/unreachable/illegal/proven/attempted 等语义；
- NPI traversal 多数路径在 `finally` 中 release handle；
- exclusion add/apply 有 baseline、回滚和事务状态，CSV export/compile 有 staged publish；
- URG 子进程使用 argv list 且 `shell=False`，没有直接 shell 注入；
- code export 已将多 scope×metric 合并为一次 URG；后续优化应复用这一点。

## 8. 正式验证结果

所有命令均从 catalog 正式 gate/suite 入口运行；真实 NPI/VDB 命令使用
`XVERIF_TEST_EXECUTION_ENV=host` 和仓库 `.conda-xverif` Python。

| Suite | Gate | 结果 | 耗时 |
| --- | --- | ---: | ---: |
| `xcov.unit` | regression | 117 passed | 8.33s |
| `xcov.urg_backend` | regression/host | 7 passed | 11.39s |
| `xcov.modinfo_complex` | regression/host | 5 passed | 11.56s |
| `xcov.exclusion_npi` | nightly/host | 1 passed | 5.53s |
| `xcov.mcp_integration` | nightly/host | 16 passed | 40.01s |
| `skills.x_npi` | regression | 14 passed | 3.51s |
| `skills.x_npi_real` | regression/host | 4 passed | 14.47s |

合计 164 个选中用例通过。另执行 `compileall`，xcov 源码与测试均成功编译。

这些结果说明当前测试所描述的合同稳定，不代表上述问题不存在：绝对路径绕过、reason 丢失等
行为本身已被当前测试接受；metric 过滤、结构哈希碰撞、close 重跑 URG 等缺少对应断言。

## 9. 建议实施顺序

### 第一批：安全与数据正确性

1. 修复目录哈希编码并升级 manifest schema/生成器；保留旧版本只读拒绝或显式迁移。
2. 统一所有输出路径策略，补 symlink/containment 测试。
3. close 增加 dirty reason gate，并同步 MCP lifecycle。
4. 修复 URG summary 的 metric 过滤和 scope 边界。

### 第二批：性能闭环

1. scope rollup 改为 O(N×depth)，增加 1k/10k scope benchmark 门禁。
2. close 使用关闭前 snapshot，禁止新 URG。
3. code export 单份 raw artifact + 一次 section 索引。
4. walker 流式聚合、scope 剪枝和前置资源预算。

### 第三批：运行时与一致性

1. 明确 native 单 session 容量或 worker 隔离。
2. 固化 pynpi/URG 的可信加载路径，删除静默 PATH fallback。
3. 替换 x-npi `_safe_call`，统一 NPI contract/error completeness。
4. 统一 staged publish、cache ownership 和 observability 原子写入。

## 10. 评审边界

- 本次没有修改产品源码、schema、skill 或测试，只新增本报告。
- 性能数字来自仓库现有 synthetic VDB，能证明复杂度与重复工作，不等同于大型 SoC 的绝对耗时；
  大型项目通常只会放大 O(N²)、全量物化和 raw duplication 问题。
- 未使用第三方 bandit/semgrep；安全结论来自源码数据流、合同对照和定向可复现用例。
- 没有进行 fuzzing、长时间并发压力、真实 LSF 或故障注入；这些应在修复后作为独立验证阶段。

## 11. NPI 使用边界与 URG XML 专项复核（增补）

> 本节是针对 NPI/URG 数据源的进一步实测结论。关于 scope 聚合、summary 正确性和 NPI
> 使用边界，以本节为准；前文把 `XCOV-PERF-01` 主要归为性能问题并不完整，它同时是
> 可稳定复现的结果正确性问题。

### 11.1 对“NPI 只应用于加载 VDB 和处理 exclude”的判断

结论：方向基本正确，但可以进一步收紧为：**普通只读 session 连“加载 VDB”都不需要
NPI；NPI 应成为只在 exclusion 工作流中按需初始化的 mutation engine。**

这里实际存在两种“加载 VDB”：

1. URG 通过 `urg -dir <vdb>` 读取 VDB，生成 summary、层级和详细报告；这足以支撑普通
   session open 的有效性检查以及所有只读 coverage 查询。
2. pynpi 通过 `cov.open(vdb)` 建立可操作 coverage handle 的数据库上下文；它只在加载、
   定位、设置、保存、卸载 report-time exclusion 时具有不可替代性。

因此建议的边界是：

- `session.open/status/close`、`tests.list`、`metrics.list`、三类 `scope.*`、三类 summary 和
  三类 coverage export 均以 URG XML/文本为正式数据源，不初始化 pynpi；
- `exclude.load/add/remove/unload_all`、`exclude.csv.validate/apply/compile`、`export.exclude`
  才按需建立 NPI context；
- coverage export 只发布 URG 可携带的稳定语义身份。精确 NPI handle/path 的解析延后到
  `exclude.add/apply/compile`，解析失败必须 fail closed，不能为了让只读 export 成功而提前
  扫描整棵 NPI coverage tree；
- exclusion 修改成功时立即由 NPI 原子保存当前 EL 并递增 `exclusion_revision`；后续只读查询
  用 `urg -elfile <current.el>` 重建对应 revision 的 XML cache。

这个拆分还会消除前文 `XCOV-OPS-01` 的根因：当前每个 native session 都无条件执行一次
进程级 `npisys.init/end`，所以只读查询也受 NPI license、Python ABI、进程级单实例和 vendor
handle 生命周期限制。

### 11.2 三类 coverage 在 XML 中的真实结构

使用 X-2025.06-SP1 对 comprehensive、modinfo_complex 和 exclusion 三个真实 VDB 执行
`urg -full64 -dir <vdb> -report <dir> -xml_verbose`。结果确认 XML 同时包含三类 coverage，
但三者结构不同，必须按 `scope/@type` 分别建模：

| coverage | XML 结构 | 正确读取方式 |
| --- | --- | --- |
| code | `scope type="instance"`，子项为 `metric name="Line/Cond/Toggle/FSM/Branch"` | 每个 instance 的 metric 已是该 instance subtree 结果，直接读取，不能再次累加全部后代 |
| assert | `scope type="Asserts"`，子 scope 为 `Assertion` 或 `Cover Property`，计数在 `attr` | 以 assertion/property 为 coverage object；attempt/success/failure 是事件计数，不是 property 覆盖率分母 |
| functional | `scope type="Groups"`，层级为 `Cover Group -> Covergroup Variant/Coverage Instance -> Coverage Point/Cross Coverage` | 保留 Variant 与 Instance 的层级和身份；同一 metric 不能跨两层重复计数 |

comprehensive VDB 的 XML 实例值示例：

```text
top                 Line=86/92   Assert=5/5
top.u_core0         Line=36/42   Assert=4/4
top.u_core0.g_pipe.u_proc Line=36/42   Assert=4/4
top.u_core1         Line=20/20   Assert=1/1
```

这证明父 scope 与子 scope 不是互斥叶子集合。`top.u_core0` 已包含其 subtree；再把
`u_proc` 和下面四个叶实例相加就是重复计数。

边界也需要明确：当前 release 的 `session.xml` 虽包含 functional 的 covergroup、variant、
instance、coverpoint 和 cross 指标，但三个实测 VDB 中都没有 bin scope；comprehensive 的
XML 解析得到 0 个 bin row，而同一次 URG 的 `grpinfo.txt` 明确列出了 uncovered bins。
所以“XML 包含三类 coverage”是正确的，但不能据此推断 `session.xml` 单文件包含所有公开
detail 粒度。bin 级 summary/detail 应使用正式 URG text artifact，或删除无法兑现的公开
`group_by=bin` 合同；不能返回空结果并宣称分析完整。

测试身份也不在 `session.xml` 节点中，但同一次正式命令加 `-format text` 会同时生成
`session.xml` 和 `tests.txt`。实测 `tests.txt` 给出了 test 总数和 VDB 内 test 路径，因此
`tests.list` 仍可保持 URG-only，不需要 NPI。

### 11.3 当前 action 的 NPI 依赖与目标边界

| action/路径 | 当前数据源与 NPI 行为 | 评审结论 |
| --- | --- | --- |
| `session.open` | `NpiCoverageBackend.__post_init__()` 无条件 `npisys.init + cov.open + test_handles + merge_test`，随后才运行 URG | 不合理；应先 URG-only，exclude 首次使用时再开 NPI |
| `tests.list` | 从 NPI `test_map` 返回 | 不需要；解析同次 URG 的 `tests.txt` |
| `metrics.list` | 使用 XML，但对所有 instance subtree 再求和 | 不需要 NPI，但当前结果错误 |
| `scope.*` | code 用 XML；默认 assert/functional 通过 `backend.items()` 扫 NPI | 不需要；code/assert 可读 instance metric，functional 使用 Groups 类型树 |
| `code_coverage.summary` | `group_by=metric/scope` 用 XML，`source_file/type` 改扫 NPI | 前两者应修正 XML 语义；后两者由 URG modinfo 正式解析，不应切 NPI |
| `functional_coverage.summary` | XML-only | 方向正确，但当前 type flatten、重复计数、bin 空成功有缺陷 |
| `assert.summary` | XML-only | 方向正确，但 scope 未过滤且 coverage ratio 语义错误 |
| `export.code_coverage` | URG 生成 detail，随后每个 scope×metric 用 NPI `attach_gap_locators()` | locator 解析应延后到 exclude 动作 |
| `export.functional_coverage/assert` | URG 写文本，NPI `gap_items()` 再生成结构化 artifact | 结构化 gap 应由对应 Groups/Asserts XML 与 URG text 生成；NPI 只在应用 exclusion 时解析目标 |
| exclusion load/set/save/unload/CSV resolve | NPI handle 操作 | 合理，是 NPI 的正式使用范围 |

### 11.4 新增 P1：XML subtree 被重复累计，多个公开查询稳定返回错误结果

涉及代码：

- `xcov/xcov/backend.py:969-992` 已明确把 `scope_metrics()` 定义为 URG subtree ratios；
- `xcov/xcov/actions.py:1796-1855` 的 `_coverage_from_urg()` 却对每个 scope 再扫描并累加
  所有 descendant row；
- `xcov/xcov/actions.py:1886-1906` 的 `_metrics_from_urg()` 同样累加所有 instance row；
- `metrics.list`、`scope.summary/children/search` 和 `code_coverage.summary(group_by=metric)`
  都使用上述错误结果。

真实 comprehensive VDB 的 action 级结果：

| 查询 | XML authoritative 值 | 当前返回值 |
| --- | ---: | ---: |
| `metrics.list` line | top `86/92` | `230/254` |
| `code_coverage.summary(metrics=[line])` line | top `86/92` | `230/254`，并额外返回其余四种未请求 metric |
| `scope.summary(top.u_core0, metrics=[line])` | `36/42` | `104/122` |
| `scope.summary(top.u_core1, metrics=[line])` | `20/20` | `40/40` |

因此前文 O(N²) 基准只是症状。修复不能采用“把相同求和改成更快的一次 rollup”，否则会
更快地产生同一个错误结果。正确算法是：

- XML 中存在 exact instance row 时直接使用该 row；
- 全局 metric summary 只合并互不重叠的 top scope row；
- 对 URG 把 `g_pipe.u_proc` 压成一个 name、而 xcov 为导航人为拆出的 synthetic ancestor，
  只合并其最浅的互不重叠 concrete descendant frontier，不能把 frontier 的后代再加一次；
- 建立 scope trie 后可在 O(N×depth) 内完成，并缓存 exact/frontier 结果。

### 11.5 新增 P1：exclusion 后 XML cache 永久陈旧，summary 不反映当前 EL

`session.open` 在 `SessionManager.open()` 中调用 `canonical_backend.summary()`，因此一打开
session 就会执行 `_ensure_urg()` 并把未加载 report-time EL 的 XML 固定在内存中。

之后：

- `NpiCoverageBackend._ensure_urg()` 在 `backend.py:1024-1061` 只以 `_urg_loaded` 为 key，
  命令永远没有 `-elfile`；
- exclusion add/load 只调用 `sess.mark_exclusion_dirty()`，没有 invalidation API；
- unload 只清 session exclusion 字段，也没有 invalidation；
- `ensure_el_ready()` 虽能用 NPI 保存 `current.el`，但只在 export 读取 `sess.el_file_arg` 时
  被调用，summary 路径完全不使用它。

真实 exclusion VDB 实测：先缓存 XML，再用 NPI 排除一个未覆盖 line 并保存 EL：

```text
修改前 XML cache：Line=31/36
修改后再次 scope_metrics()：Line=31/36（与旧 cache 完全相同）
同一 VDB + 同一 EL 重新运行 URG：Line=31/35
```

这说明 code/functional/assert summary 在 exclusion 后均可能陈旧；`scope.*` 还会出现
“code 来自旧 XML、assert/functional 来自当前 NPI”的同一响应混合两个 revision 的问题。

修复要求：cache key 至少包含 `(canonical_vdb_identity, selected_test, exclusion_revision,
urg_options)`；exclusion transaction 成功提交后保存 EL、递增 revision 并废弃旧 cache；所有
summary/export 只消费同一 revision 的 URG artifacts。

### 11.6 新增 P1：公开 `test` selector 在 XML 快路径被静默忽略

`metrics.list`、`scope.*`、`code_coverage.summary`、`functional_coverage.summary` 和
`assert.summary` 都把 `args.test` 写回响应 summary，但 `_ensure_urg()` 只生成一次 merged VDB
报告，cache 也不含 test 维度：

- code XML 快路径不读取 `args.test`；
- functional/assert handler 直接读取同一 `_urg_groups/_urg_asserts`；
- 只有落入 NPI `items()` 的路径才解析具体 test handle；
- 因此同一 action 可能仅因 `group_by` 不同，就从“忽略 test”切换到“应用 test”。

这是接受参数后静默忽略，违反仓库公共参数规则。需要先确认 URG 对单 test 的正式选择方式并
把它纳入 artifact/cache key；若当前产品不支持 concrete/each test，就从这些 action 的公开
schema 删除该参数或返回明确 `TEST_MODE_NOT_SUPPORTED`，不能继续回显请求值伪装已生效。

### 11.7 新增 P1：functional XML parser 混淆 Variant/Instance，并对 bin 返回假完整

`backend.py:1104-1138` 的 walker 虽识别 `Covergroup Variant` 与 `Coverage Instance`，却只把
两者的 name 写入一个随后完全未输出的局部变量 `instance`；它继续递归，并把两层下面的
Point/Cross metric 全部追加到同一个扁平列表。

comprehensive XML 中同一 covergroup 的 variant 和 coverage instance 各有一套相同的
3 个 point + 1 个 cross。当前 parser 产生：

```text
真实直接 score item：4
当前 score_item_count：8
cp_op：XML 2/2，当前 group_by=coverpoint 返回 4/4
cp_data：XML 2/3，当前返回 4/6
cr_result：XML 2/6，当前返回 4/12
```

百分比碰巧相同，掩盖了 covered/coverable/missing 和 item count 已翻倍。复杂 VDB 中 parser
生成 147 行，并丢失 18 个 variant、12 个 coverage instance 的层级身份。

此外公开 schema 允许 `group_by=bin`，但 parser 从不创建 `npiCovCoverBin` row。真实 action
对包含明确 user bins 的 comprehensive VDB 返回 0 项，同时声明 `scan_complete=true`、
`analysis_complete=true`。现有单元测试只检查“返回项若存在则字段形状正确”，没有断言有 bin
的 fixture 必须返回 bin，因而没有发现该问题。

修复时必须建立 typed functional IR，至少保留 covergroup type、variant、coverage instance、
coverpoint/cross 的父子关系和唯一身份；summary 明确选择 aggregate layer 或 instance layer，
任何一次统计都不能同时消费父 aggregate 和其子 instance。bin 数据由 URG `grpinfo.txt` 的
正式 parser 补齐；parser 无法完整解释时返回明确 incomplete/error。

### 11.8 新增 P1：assert summary 忽略 scope，且把事件成功率误当 property 覆盖率

`actions.py:516-526` 读取 `args.scope` 后只把它回显到 summary，没有过滤 XML rows。真实请求
`assert.summary(scope=top.u_core1)` 返回了全部 5 条 assertion，其中 4 条位于
`top.u_core0`。

`backend.py:1142-1178` 又把：

```text
covered   = success count
coverable = attempt count
```

这与 XML 的 assertion coverage object 语义不一致。comprehensive 顶层 instance metric 是
`Assert=5/5`，五个 assertion/cover property 都至少成功一次；当前却返回：

```text
a_result_valid 11/12 = 91.67%
a_op_known      2/12 = 16.67%
c_burst_done    1/12 =  8.33%
```

attempt、success、failure 应作为独立事件计数字段；property 覆盖率应按 assertion/property
coverage object 是否命中建模，例如本例每项均为 `1/1`。scope 过滤应使用
`full_name == scope` 或 `full_name.startswith(scope + ".")` 的边界匹配。

### 11.9 新增 P2：XML 解析失败时可能以“空且完整”成功

`_ensure_urg()` 只检查 URG exit code、`session.xml` 是否存在以及 XML 是否可 parse；若
`old_coverage`、预期 type tree 或关键 metric 缺失，它仍设置 `_urg_loaded=true`。functional
bin 的真实空成功已经证明 completeness contract 没有被数据源校验约束。

建议为 typed IR 增加：

- URG release/XML version、必需 root/type、metric definition 与数值格式校验；
- 每类 parser 的 `source_complete`、`unsupported_types`、`parsed/expected` 计数；
- 公开 action 所需粒度不存在时返回明确错误，不以空数组和
  `analysis_complete=true` 代替；
- 三类真实 fixture 的 golden XML contract 测试，分别覆盖 code subtree、assert attrs、
  functional variant/instance/bin，以及 test/EL revision cache key。

### 11.10 推荐重构顺序

1. 先修正 typed XML IR 和所有 summary 语义：code exact subtree、assert property、functional
   variant/instance；同时补真实 VDB golden assertions。
2. 删除 `_coverage_from_urg()` 的 descendant 全量重复求和，修复 `metrics.list`、
   `code_coverage.summary` 和 `scope.*`；这一步优先于性能优化。
3. 引入以 test + exclusion revision 为 key 的 URG artifact cache；所有 summary/export 使用
   同一份带 EL 的 artifact snapshot。
4. 把 NPI 从 `NpiCoverageBackend.__post_init__()` 移到独立、lazy 的 exclusion engine；普通
   session open/close 不调用 `npisys.init/end`。
5. export 生成 URG semantic locator，exclude 时才做 NPI exact resolution；保留当前事务、
   baseline、rollback 和 fail-closed 约束。
6. 最后再做性能门禁：1k/10k typed scope、复杂 Groups tree、多 test、多 EL revision；禁止只
   以耗时通过而不核对 XML authoritative counts。

本专项复核没有修改 xcov 产品源码、schema、测试或 skill；只把结论追加到本报告。真实 VDB
动作均使用正式 URG/pynpi 环境完成，没有切换数据源或静默 fallback。

## 12. URG test list、输出格式与 summary 选项实测（增补）

本节所有命令均显式使用 `urg -full64`，未初始化 NPI。测试使用 comprehensive 和
modinfo_complex 两个真实 VDB；每种模式先预热一次，再按轮换顺序执行 4 次，以下时间为
wall time 中位数。

### 12.1 不使用 NPI 和 `-format text` 获取 test list

本机 X-2025.06-SP1 帮助提供正式入口：

```bash
urg -full64 -dir <vdb> -show availabletests
```

实测该命令：

- exit code 为 0；
- stdout 在 `Available tests names:` 后逐行输出 test；
- stderr 明确输出 `URG-NR No report generated`；
- 不创建 `urgReport` 或其它文件；
- comprehensive 与 modinfo_complex 的耗时中位数分别为 0.8303 秒和 0.8176 秒；
- 输出 test 与相同 VDB 的 `tests.html`、`tests.txt` 完全一致。

因此 standalone `tests.list` 可以保持 URG-only 且无需生成报告。若 session 已经生成 HTML
summary，也可以解析 `tests.html`，但 HTML 合同比专用 stdout/test text 更脆弱。

### 12.2 HTML、text 与 summary 的速度和产物

比较的正式 argv 后缀为：

```text
html_xml:         -xml_verbose
text_xml:         -xml_verbose -format text
html_summary_xml: -xml_verbose -show summary
text_summary_xml: -xml_verbose -format text -show summary
available_tests:  -show availabletests
```

| VDB | HTML | text | HTML summary | text summary | availabletests |
| --- | ---: | ---: | ---: | ---: | ---: |
| comprehensive | 0.8856s | 0.8394s | 0.8327s | 0.8369s | 0.8303s |
| modinfo_complex | 0.9167s | 0.9055s | 0.8468s | 0.8458s | 0.8176s |

当前两个 fixture 上没有观察到 `-format text` 变慢。comprehensive 的 text 比 HTML 快约
5.2%，modinfo_complex 快约 1.2%（接近运行波动）。小型 VDB 中约 0.8 秒的 URG 启动/加载
成本占主导，不能把该比例外推为大型 SoC 的绝对结果。

产物差异更明确：

| VDB/模式 | 文件数 | 总字节 | 主要 detail |
| --- | ---: | ---: | --- |
| comprehensive HTML | 26 | 678,759 | module/group HTML 与 7 个 JS、4 个 CSS |
| comprehensive text | 9 | 76,762 | `modinfo.txt` 52,448 B、`grpinfo.txt` 6,653 B |
| comprehensive text summary | 6 | 16,584 | 无 modinfo/grpinfo/hierarchy |
| modinfo_complex HTML | 42 | 1,816,924 | `mod2.html` 单文件 627,731 B |
| modinfo_complex text | 9 | 615,049 | `modinfo.txt` 403,304 B、`grpinfo.txt` 112,825 B |
| modinfo_complex text summary | 6 | 94,692 | 无 modinfo/grpinfo/hierarchy |

四种 report 模式的 canonical `old_coverage` SHA-256 完全一致，scope type 和 metric 数量也
一致；`session.xml` 文件大小的微小差别来自其中记录的 command/report path。由此确认
`-show summary` 只抑制展示详情，不裁掉 `-xml_verbose` 的 code/assert/functional typed data。

`-format text -show summary` 只产生：

```text
session.xml
tests.txt
dashboard.txt
modlist.txt
groups.txt
asserts.txt
```

所以如果 session open 同时需要 XML 和 test list，推荐一次执行：

```bash
urg -full64 -dir <vdb> -report <dir> -xml_verbose -format text -show summary
```

它不会生成此前担心的 `modinfo.txt`、`grpinfo.txt` 和 `hierarchy.txt`，也避免再付一次
`-show availabletests` 的 URG 启动成本。

### 12.3 `-show` 组合语法

`+` 不是通用的 show suboption 组合语法。以下三种写法均实测返回 exit code 1 和
`URG-US Unknown suboption`：

```text
-show summary+availabletests
-show summary+tests
-show summary+testrecords
```

帮助中明确声明的 metric 列表可以使用 `+`，例如 `-show brief line+cond`。

重复 `-show` 的行为：

- `-show summary -show availabletests`：`availabletests` 主导，列出后退出，不生成 summary；
- `-show summary -show tests`：生成 summary 并加入每个 coverage object 的 test attribution，
  comprehensive 的 `tests.txt` 从 514 B 增至 4,306 B，coverage XML 主体也改变；
- `-show summary -show testrecords`：增加 test record 表，`tests.txt` 增至 1,408 B，canonical
  coverage XML 主体不变。

`-show tests` 的语义是显示“哪些 test 覆盖了对象”，不是获取 test list；普通 `tests.list`
不应启用它。

### 12.4 其它候选选项

- `-tests <file>`：官方的 test 选择入口，应作为修复当前公开 `test` selector 被忽略问题的
  首选调查方向，并纳入 URG artifact cache key；
- `-metric <...>`：可以生成单 metric verbose XML。modinfo_complex 实测 line/assert/group
  XML 分别为 3,806/10,148/65,940 B；适合真正独立的按需查询，但多个 action 分别启动 URG
  可能比一次生成 82 KB 全 metric XML 更慢；
- `-xml_advanced`：text summary XML 仅 5,272 B，只包含 top/aggregate 结构，缺少完整
  instance、assert 和 functional typed hierarchy，不能代替 `-xml_verbose`；
- `-noreport`：与当前 `-xml_verbose` 组合时 exit code 为 1 且不生成 `session.xml`，不可用；
- `-format both`：同时生成 HTML 和 text，会扩大产物，不适合 xcov cache；
- `-show brief`：适合 uncovered detail export，不适合 summary cache；
- `-show testrecords`：只有公开合同确实需要 simulation metadata 时才启用；普通 test name
  列表不需要。

小型 fixture 只足以确定命令语义与产物差异。`-format text`、`-show summary` 对大型设计的
速度影响需要用至少 2 万行 RTL、数百 module/instance 的 VDB 再做一次相同方法的实测。

## 13. 2 万行以上 RTL 的大型 URG 性能复核（增补）

为验证上一节的小型 fixture 结论是否受 URG 固定启动成本主导，本次在仓库忽略目录
`tmp/xcov-urg-large-20260811/` 中建立了完全独立的 synthetic 实验。没有修改 xcov 产品源码，
也没有调用 NPI。

### 13.1 设计与 VDB 规模

实验脚本 `generate_large_rtl.py` 生成：

- 23,701 行、864,268 字节 SystemVerilog RTL；
- 320 个独立 `cov_leaf_*` module 和一个 top，共 321 个 module；
- 320 个 leaf instance；
- 每个 leaf 均包含 sequential/combinational 分支、8-state FSM、condition、toggle、一个
  assertion、一个 cover property，以及带 2 个 coverpoint 和 1 个 cross 的 covergroup；
- 仿真运行 53 个有效 assertion/cover-property sampling cycle。

使用与仓库 fixture 一致的正式 coverage 参数：

```bash
vcs -full64 -sverilog -kdb -debug_access+all \
  -cm line+cond+branch+tgl+fsm+assert \
  -cm_dir <large.vdb> -o <simv> large_design.sv

<simv> -cm line+cond+branch+tgl+fsm+assert \
  -cm_dir <large.vdb> -cm_name large
```

构建结果：

| 阶段 | wall time | 峰值 RSS |
| --- | ---: | ---: |
| VCS compile/elab/link | 22.57s | 287,496 KiB |
| simulation/coverage write | 1.52s | 248,428 KiB |

最终 VDB 约 628 KiB。`-xml_verbose` 解析出的 typed tree 包含：

| XML type | 数量 |
| --- | ---: |
| `instance` | 321 |
| `Assertion` | 320 |
| `Cover Property` | 320 |
| `Cover Group` | 320 |
| `Covergroup Variant` | 320 |
| `Coverage Instance` | 320 |
| `Coverage Point` | 1,280 |
| `Cross Coverage` | 640 |

### 13.2 基准方法

`benchmark_urg.py` 对五种模式各预热一次，再用轮换顺序执行 4 个 measured round。每次使用
新的、位于仓库 `tmp` 实验目录内的 report directory；计时后删除该 round 的临时产物，只保留
JSON 结果和一份推荐的 text summary report。所有 URG argv 均包含 `-full64`。

### 13.3 大型设计结果

| 模式 | wall 中位数 | min-max | 文件数 | 总字节 |
| --- | ---: | ---: | ---: | ---: |
| `-xml_verbose`（HTML） | 2.8197s | 2.7830-2.8607s | 666 | 26,862,581 |
| `-xml_verbose -format text` | 2.2421s | 2.1330-2.4452s | 9 | 10,037,298 |
| `-xml_verbose -show summary` | 1.2486s | 1.2277-1.3208s | 23 | 2,589,136 |
| `-xml_verbose -format text -show summary` | 1.2657s | 1.2488-1.4932s | 6 | 1,608,888 |
| `-show availabletests` | 0.8156s | 0.8025-0.8660s | 0 | 0 |

大型设计上的结论比小 fixture 更明确：

- 完整 text 比完整 HTML 快约 20.5%，产物减少约 62.6%；因此“text 因生成 modinfo 必然更慢”
  在本次实测中不成立。HTML 为 320 个独立 module/group 生成了大量页面；
- text 的主要 detail 是 `modinfo.txt` 5,916,657 B 和 `grpinfo.txt` 2,491,086 B，确实存在
  明显格式化/I/O 成本；
- 加 `-show summary` 后，text 不再生成 modinfo/grpinfo/hierarchy，较完整 text 快约 43.5%，
  产物减少约 84.0%；
- text summary 与 HTML summary 的中位数只差约 1.4%，属于当前 4 次样本波动范围；但 text
  summary 只有 6 个文件、1.61 MB，HTML summary 有 23 个文件、2.59 MB；
- 相比 xcov 当前 `_ensure_urg()` 的完整 HTML 模式，text summary 快约 55.1%，产物减少约
  94.0%；
- `availabletests` 保持约 0.82 秒，说明它避免报告生成，但仍需支付大部分 URG 启动/VDB
  discovery 成本；session 已经需要 XML 时，不应再额外运行一次。

四种 XML report 模式的 canonical `old_coverage` SHA-256 均为：

```text
5da540307da84d91bf999e491332ab1fdb773d59919a39dede1b7e01dfeb5333
```

scope type 计数也完全相同，再次确认 `-show summary` 没有裁掉 xcov 需要的 code/assert/
functional typed XML，只抑制详细展示文件。

### 13.4 最终建议

`NpiCoverageBackend._ensure_urg()` 的只读数据源应改为等价的 URG-only backend，并将 summary
正式命令固定为：

```bash
urg -full64 -dir <vdb> -report <cache-dir> \
  -xml_verbose -format text -show summary
```

该调用一次得到完整 `session.xml` 与 `tests.txt`；无需 NPI，也无需第二次 test discovery。
只有在尚未建立 summary cache、调用者只请求 test discovery 时，才使用：

```bash
urg -full64 -dir <vdb> -show availabletests
```

详细 code/functional/assert gap export 仍使用独立、按 metric/scope 限定的 URG detail 命令，
不能复用 summary 模式冒充 detail 完整性。

实验的生成脚本、RTL、VDB、原始 JSON 结果和推荐 report 均保存在仓库 ignored `tmp` 子目录，
便于本地复核，不会进入正常 Git 提交范围。

## 14. 37.5 万行、多端口宽接口设计的 URG 压力复核（增补）

用户进一步要求设计达到 20 万行以上、延长仿真、增加接口位宽，并且不能只靠位宽扩大规模。
因此本轮在仓库 ignored 目录 `tmp/xcov-urg-huge-20260811/` 重新生成一版多端口设计。此前仅扩大
位宽的中间编译已主动终止，其结果未纳入本节数据。

### 14.1 设计规模与端口构成

最终输入文件 `huge_design_manyports.sv` 的实测规模为：

- 375,053 个物理行、15,741,961 字节；
- 3,000 个彼此独立的 `cov_leaf_*` module，加一个 top，共 3,001 个 module/instance；
- 每个 leaf 有 25 个端口：14 个输入、11 个输出；
- 其中有 5 个 128-bit 输入数据口和 5 个 128-bit 输出数据口，另有 32-bit control/status、
  16-bit tag、valid/ready/flush/enable/error/busy 等独立控制与状态口；
- 每个 leaf 包含 sequential/combinational 分支、8-state FSM、condition/toggle、一个 assertion、
  一个 cover property，以及 5 个 coverpoint 和 2 个 cross；
- stimulus 运行 256 个主循环，最终仿真结束于 523 ns；每个 assertion/cover property 有 261 次
  sampling attempt。

因此该样本不仅扩大了代码行数和数据位宽，也同时扩大了模块数、端口数、连接数、覆盖对象数和
仿真采样长度。

### 14.2 `-full64` 构建与仿真资源

正式构建命令为：

```bash
vcs -full64 -sverilog -kdb -debug_access+all \
  -cm line+cond+branch+tgl+fsm+assert \
  -cm_dir <huge.vdb> -o <simv> huge_design_manyports.sv

<simv> -cm line+cond+branch+tgl+fsm+assert \
  -cm_dir <huge.vdb> -cm_name huge_manyports
```

| 阶段 | wall time | 峰值 RSS | 结果 |
| --- | ---: | ---: | --- |
| VCS compile/elab/link | 379.19s | 1,307,968 KiB | exit 0，3,001/3,001 modules 完成 |
| simulation/coverage write | 54.18s | 900,452 KiB | exit 0，结束于 523 ns |

最终 VDB 约 5.8 MiB。`-xml_verbose` 中不同 coverage 类型不能混为同一种 scope；本样本的 typed
tree 分布为：

| coverage 类别 | XML `scope type` | 数量 |
| --- | --- | ---: |
| code | `instance` | 3,001 |
| assertion | `Asserts` / `Assertion` / `Cover Property` / `assert` | 1 / 3,000 / 3,000 / 1 |
| functional | `Groups` / `Cover Group` / `Covergroup Variant` | 1 / 3,000 / 3,000 |
| functional | `Coverage Instance` / `Coverage Point` / `Cross Coverage` | 3,000 / 30,000 / 12,000 |

这再次验证：XML 已同时包含 code、assert 和 functional coverage，但后三者的树形和 type 语义
不同；xcov parser 必须按 type 分派，不能用 code coverage 的 instance 聚合规则解释 assertion
或 functional subtree。

### 14.3 三轮 URG 对照结果

基准仍对五种模式各预热一次，再轮换执行 3 轮；所有 URG argv 都显式包含 `-full64`。整个基准
进程 wall time 为 409.39 秒，峰值 RSS 405,308 KiB。

| 模式 | wall 中位数 | min-max | 文件数 | 总字节 |
| --- | ---: | ---: | ---: | ---: |
| `-xml_verbose`（HTML） | 41.6659s | 41.1497-42.4971s | 6,096 | 351,597,002 |
| `-xml_verbose -format text` | 31.4622s | 31.1863-31.5099s | 9 | 142,192,230 |
| `-xml_verbose -show summary` | 6.9138s | 6.4249-7.2536s | 90 | 30,306,881 |
| `-xml_verbose -format text -show summary` | 6.5419s | 6.3821-6.6742s | 6 | 24,846,361 |
| `-show availabletests` | 0.8388s | 0.8165-0.8634s | 0 | 0 |

主要差异如下：

- 完整 text 比完整 HTML 快 24.5%，产物减少 59.6%，仍未观察到 text 因导出 modinfo 而比
  HTML 慢；不过完整 text 的 `modinfo.txt` 为 74,687,476 B，`grpinfo.txt` 为 42,466,206 B，
  两者确实构成主要格式化和 I/O 成本；
- HTML summary 比完整 HTML 快 6.03 倍，wall time 减少 83.4%，产物减少 91.4%；
- text summary 比完整 text 快 4.81 倍，wall time 减少 79.2%，产物减少 82.5%；
- text summary 比 HTML summary 再快 5.4%，产物减少 18.0%，并把文件数从 90 个降为 6 个；
- text summary 仍只产生 `session.xml`、`tests.txt`、`dashboard.txt`、`modlist.txt`、
  `groups.txt` 和 `asserts.txt`，没有 `modinfo.txt`、`grpinfo.txt` 或 `hierarchy.txt`；
- `availabletests` 保持约 0.84 秒，输出唯一 test `huge_manyports` 且不生成 report；它比 text
  summary 快 7.80 倍，但如果 session 已经要生成 XML，再单独启动一次仍是重复成本。

四种 XML report 的 canonical `old_coverage` SHA-256 完全一致：

```text
e622a71407b9aeaacd2eab3bc8f85b8af184b1bd4a6d17fb7ea6cdc40ed4dec0
```

其 scope type 计数也完全一致。约 23.7k 行到 375k 行时，源码增长 15.82 倍；完整 HTML/text
耗时分别增长 14.78/14.03 倍，接近线性，而 HTML/text summary 只增长 5.54/5.17 倍，
`availabletests` 只增长 1.03 倍。这份数据支持“详细页面/文本格式化随覆盖对象规模主导增长”，
不支持把当前观测解释为 XML summary 自身的 O(N²) 聚合。

### 14.4 对 xcov 实现决策的最终影响

37.5 万行、多端口、128-bit、3,000 module 的实测进一步加强第 13.4 节建议：普通 summary/session
加载应采用一次 URG-only 调用：

```bash
urg -full64 -dir <vdb> -report <cache-dir> \
  -xml_verbose -format text -show summary
```

该模式保留完整 typed XML 和 test list，同时避免 118 MB 以上的 modinfo/grpinfo text detail，
相对 xcov 当前完整 HTML 导出把中位 wall time 从 41.67 秒降至 6.54 秒。普通只读 session 连
NPI `cov.open(vdb)` 都不需要；只有 exclusion 工作流实际开始时，才按需初始化 NPI、加载 VDB
并解析/应用 exclude。summary、test discovery、XML typed parsing 和普通 detail export 不应
为了这些数据初始化或遍历 NPI。

本轮脚本、RTL、VDB、编译/仿真日志、三轮 JSON 结果和一份 text summary report 均保存在上述
仓库 `tmp` 子目录，便于复核且不会进入正常 Git 提交范围。

## 15. xcov 全面优化与 x-npi 同步改造实施计划

本节是后续实现、分阶段提交和最终验收的完整执行合同。实施时不得因为某个阶段集中处理
URG、NPI、LSF 或 fixture，就省略其它已确认的正确性、安全性、性能、文档和测试要求。

### 15.1 最终架构和不可变约束

目标运行链路为：

```text
MCP server
  `- session.open
      `- bsub -I <session queue/resource/job name>
          `- tools/xcov --stdio-loop
              |- coverage summary/tests/hierarchy/gap/detail
              |   `- bsub -K <URG queue/resource/job name> urg -full64 ...
              `- first exclusion action
                  `- lazy initialize pynpi and keep it until session close
```

必须保持以下边界：

1. 目标 EDA 环境的每个 xcov MCP session 从创建开始就直接通过 `bsub` 启动一个独立的
   `tools/xcov --stdio-loop`。本地 MCP server 只维护 `bsub` 交互进程、JSONL 管道、job identity、
   session index 和清理状态，不在本地先启动 xcov 再转发到 LSF。
2. 外层 xcov stdio-loop 是有状态双向协议，使用 `bsub -I`。内层 URG 是有限期批任务，使用
   `bsub -K` 同步等待。两层 job 分别配置 queue/resource、分别记录 job identity、分别处理
   timeout/cancel/bkill，任一层失败都不允许自动 fallback 到 direct。
3. URG 是 coverage 读取的唯一数据源。session open、tests、summary、scope hierarchy、code/assert/
   functional 统计和 gap/detail 都不依赖 NPI coverage tree traversal。
4. NPI 只负责 exclusion target resolution、EL load、set、save 和 unload。第一次 exclusion 前不得
   import pynpi、调用 `npisys.init`、执行 `cov.open` 或取得 merged test handle。
5. 第一次 exclusion 初始化的 NPI context 在当前 xcov stdio-loop 内常驻到 session close；多个 MCP
   session 因为本来就是多个独立 CLI/LSF job，不共享 NPI 全局状态。
6. 用户直接运行 native `tools/xcov --stdio-loop` 时，同一个进程最多允许一个 live native session，
   从合同上消除 pynpi 进程级 singleton 与多 VDB 并存的歧义。
7. 对 `urg -full64 -xml_verbose -format text -show summary` 不能可靠提供的维度不做伪实现，不使用
   NPI 补齐 summary。对应参数从 schema 删除，请求旧参数时返回 `SCHEMA_INVALID`。
8. 本次必须关闭第 2 节列出的全部 P1、P2、P3，不只完成 URG 加速。
9. 第 14 节的大型实验必须转为正式、可指纹缓存的回归 fixture，但不提交生成后的 15 MiB RTL、
   simv、VDB 或 URG report。
10. x-npi 修改是最后一个功能阶段；全部功能完成后再运行全仓 fast、fixture validation、regression、
    nightly 和真实 LSF full-chain，并用独立提交记录最终验证结果。

### 15.2 URG summary 数据合同

普通 session 加载和 summary 的 canonical 命令固定为：

```bash
urg -full64 \
  -dir <absolute-vdb-path> \
  -report <absolute-staging-or-cache-path> \
  -xml_verbose \
  -format text \
  -show summary
```

当前 exclusion 需要参与统计时追加：

```bash
-elfile <absolute-working-el-path>
```

一次 summary cache entry 必须包含并校验以下六个文件：

- `session.xml`：canonical typed XML，包含 code、assert 和 functional coverage 的不同节点树；
- `tests.txt`：merged VDB 中的 test list；
- `dashboard.txt`：metric catalog 和总体统计；
- `modlist.txt`：实例层次和 scope summary；
- `groups.txt`：functional coverage summary；
- `asserts.txt`：assertion/cover property summary。

这组固定产物支持 merged tests、metric catalog、nested scope hierarchy、实例级 Line/Cond/Toggle/FSM/
Branch/Assert、assert/cover property，以及 covergroup、variant、instance、coverpoint、cross。

明确不由 summary 合同支持：

- per-test attribution 或 summary 的 `test` selector；
- code coverage 按 source file/type 聚合；
- functional bin 级 summary；
- summary 中的源码 file/line evidence；
- 仅凭 summary XML 恢复全部 gap exclusion locator。

详细 code/functional/assert gap 继续由按 metric/scope 限定的 URG text detail 命令生成，不使用 NPI
遍历。`-show availabletests` 可以作为独立诊断命令记录在文档中，但正常 session 已生成 summary 时
直接使用 `tests.txt`，不得为了同一 test list 再启动一次 URG。

URG 选项说明和边界必须同步到 README、CLI/MCP 示例和 skill：

- `-full64`：所有正式 URG invocation 必须携带；
- `-dir`：输入 VDB；
- `-report`：原子 cache producer 的 staging 目录或 detail staging 目录；
- `-xml_verbose`：获得所需完整 typed XML；
- `-format text`：生成 tests/dashboard/modlist/groups/asserts 文本；
- `-show summary`：禁止完整 HTML/modinfo/grpinfo 膨胀；
- `-metric`：只组合 URG 明确支持的 coverage metrics；
- `-tests`：仅用于确实需要的 detail/per-test URG 场景，不进入当前 merged summary API；
- `-elfile`：将 working exclusion 应用于 summary/detail；
- `+` 只用于 URG 明确支持组合的 metric，不假定 `-show` 子项能够任意组合；
- `-xml_advanced` 不能替代 `-xml_verbose` 的完整 typed tree；
- `-noreport` 不能用于需要上述 XML/text report 文件的流程。

### 15.3 公开 schema、CLI 和 MCP 合同收紧

从 native CLI、stdio-loop request schema、MCP tool schema、examples、README 和 skill 中同步删除：

- 所有 coverage query 的 per-test `test` 参数；
- `code_coverage.summary.group_by=source_file|type`；
- `functional_coverage.summary.group_by=bin`；
- summary response 中不能从固定 URG summary 可靠得到的 file/line/bin 字段。

最终允许：

```text
code_coverage.summary.group_by:
  metric | scope

functional_coverage.summary.group_by:
  covergroup | coverpoint | cross
```

合同规则：

- `tests.list` 从 `tests.txt` 返回；
- summary 明确标注 selection 为 `merged`；
- `metrics` filter 必须真实影响 code summary，不允许接受后忽略；
- 未支持参数直接 `SCHEMA_INVALID`；
- 所有公开 request 顶层和嵌套对象继续关闭未知字段；
- response 不在 `summary` 和 `data` 重复同一事实；
- 完整分析计数和实际返回行数分离；
- 截断时包含 `truncated` 及明确的 truncation scope；
- CLI、MCP、schema、example 和 skill 的 enum、默认值、required 语义保持一致。

### 15.4 三类 coverage 的 typed IR

不能把 XML 中的 assertion、functional coverage 当作 code instance subtree 处理。实现三个严格 IR：

#### Code coverage IR

- nested scope identity、fullname、parent、direct children；
- Line、Cond、Toggle、FSM、Branch；
- 每 metric 的 covered、coverable、missing、coverage percentage 和 status；
- scope 与 metric 的直接索引。

#### Assertion coverage IR

- assertion container scope；
- Assertion 和 Cover Property 分开建模；
- property name、scope、attempt/success/status 等 assertion 专用属性；
- 不把 assertion successes/attempts 机械冒充 code covered/coverable；
- 保留 assertion XML 中可验证的状态和完整性。

#### Functional coverage IR

- Cover Group；
- Covergroup Variant；
- Coverage Instance；
- Coverage Point；
- Cross Coverage；
- 保留 type/variant/instance 身份，禁止合并同名但不同 variant/instance 的节点；
- 不生成 `bin=None` 的虚假 complete bin。

parser 必须按 XML `type` 和结构严格 dispatch。未知 type、缺失必填 attribute、非法数值、重复 identity、
破损文件或不完整 report 必须返回 typed parse/validation error，不得返回 empty result 并声称
`complete=true`。

解析使用流式 `iterparse`，一次构建不可变索引：

- scope fullname → scope node；
- parent → direct children；
- scope → code metrics；
- scope → assertion properties；
- covergroup type/variant/instance → functional nodes；
- metric catalog；
- merged test catalog。

查询只能访问已建索引，不得在每个 scope 或每个 metric 上重新扫描整棵 XML tree。

### 15.5 scope 和 SCORE 语义

- URG XML 父 scope 数值已经表示其 subtree，禁止再累加所有 descendants；
- 单 metric `coverage_pct` 使用该 metric 的 covered/coverable；
- 多 metric scope `coverage_pct` 与 URG `SCORE` 对齐，对选中且有效的 metric percentages 做算术平均；
- 多 metric scope response 删除无统一计数单位的 aggregate `covered/coverable/missing`；
- 只选一个 metric 时可以保留该 metric 的真实 covered/coverable/missing；
- scope selector 使用规范化完整层次边界；
- exact scope 与显式 subtree selector 分开；
- `top.a` 不得误匹配 `top.ab`；
- parent/child 不再重复计数；
- metric filter 必须在 typed IR 查询层生效。

这部分直接关闭当前 XML subtree double count、`XCOV-COR-01`、`XCOV-COR-02` 和
`XCOV-PERF-01`。

### 15.6 session 和 lazy NPI exclusion 生命周期

session 内部状态拆分为：

```text
Session
  |- immutable URG snapshot/index
  |- mutable exclusion revision and EL digest
  |- optional working EL
  |- optional reason CSV state
  `- optional LazyNpiExclusionContext
```

`session.open` 只执行：

- VDB/run manifest 校验；
- URG provenance 校验；
- cache root 和 shared path 校验；
- cache hit 加载或 cache miss summary producer；
- typed XML/text parse 和 index 构建。

`session.open` 明确不得：

- import pynpi；
- 调用 `npisys.init`；
- 调用 `cov.open`；
- 取得 NPI merged test handle；
- 遍历 NPI coverage tree。

第一次 exclusion action 才执行：

- 校验 `VERDI_HOME`；
- 配置并验证 pynpi 实际 module path；
- import pynpi；
- `npisys.init`；
- `cov.open`；
- 取得 merged test；
- 加载当前 working EL；
- 建立当前 session 专属 exclusion context。

后续 exclusion：

- 复用同一个 context；
- 只对请求涉及的 grouped target roots 做必要 NPI resolution；
- 在 session 内缓存已验证 handle；
- no match 或 ambiguous match 必须 fail closed；
- 禁止 catch 后更换参数重试；
- 禁止 NPI 失败后用 URG 或其它 backend 模拟成功。

每次 exclusion mutation 后：

- 原子保存 working EL；
- exclusion revision 加一；
- 重新计算 EL digest；
- 失效当前 in-memory summary snapshot；
- 下一次 summary/detail 使用 `-elfile` 并以新 EL digest 查询 cache。

reason/EL 状态分离：

- `reason_dirty`；
- `el_revision`；
- `csv_export_revision`；
- `el_export_revision`。

存在未持久化 reason 时，close 返回 `UNPERSISTED_EXCLUSION_REASON` 并保持 session 可恢复；只有
公开且显式的 `confirm_discard_reasons=true` 才允许丢弃。close 不得为了保存、导出或刷新统计再次
运行 URG。

正常 close 按严格顺序释放 exclusion handles、merged test、coverage database 和 NPI runtime。任一
释放阶段失败进入 partial cleanup/tombstone，不得伪装成功。

### 15.7 内容寻址 URG cache

默认 cache 根目录：

```text
.xverif/xcov/cache
```

允许 session/MCP 显式覆盖 `cache_dir`，但必须通过共享路径和安全边界校验。

cache key 必须包含：

- cache schema version；
- parser/IR contract version；
- secure VDB identity；
- run manifest digest；
- URG 绝对路径；
- URG version；
- fixed argv contract；
- merged selection；
- exclusion EL digest；
- 所有会影响 summary 的公开参数。

immutable entry 内容：

- 六项 summary 文件；
- entry manifest；
- 每文件 sha256 和 size；
- scope/test/metric/covergroup/assertion counts；
- VDB/tool/EL provenance；
- generation timestamp；
- complete marker。

并发和原子发布：

- 每个 key 使用 `fcntl` lock；
- producer 在同一文件系统的 sibling staging directory 生成；
- 完成后验证六项文件、hash、size 和 semantic counts；
- fsync 必要文件和目录；
- atomic rename 发布；
- reader 只承认完整且 manifest 校验通过的 entry；
- failed/partial staging 永远不能成为 cache hit；
- 同 key 的其它请求等待当前 producer，不重复提交 URG job。

LRU 默认合同：

- 最大20 GiB；
- 最大128 entries；
- 两项均可显式配置；
- eviction 使用 global lock；
- 不驱逐被锁或被 live session pin 的 entry；
- 超过24小时的 abandoned staging 可以清理；
- immutable summary cache 跨 session 保留；
- mutable exclusion working directory 在确认安全 close 后清理。

性能要求：

- 一次 parse 建立所有索引；
- 禁止 parent/descendant 重复累计；
- 禁止每 scope 扫描整树；
- 禁止每 metric 扫描整树；
- summary 同一 key 只运行一次 URG；
- detail 在 URG 支持范围内合并 scope/metric；
- close 不运行 URG；
- CSV multiline 使用线性状态机；
- 提供 operation counters 供 1k/10k scope 测试断言近似 O(N)。

### 15.8 外层 xcov stdio-loop 的 LSF 队列合同

外层必须直接复用 xdebug 的共享层：

```text
McpSessionManager
  -> LsfLauncher
  -> BsubRunner
  -> JsonlProcess
  -> shared cleanup/tombstone state machine
```

不得在 xcov 内复制或简化 launcher。

外层 canonical argv：

```text
bsub -I
  -J <unique-xcov-session-job-name>
  -q <effective-session-queue>
  [-R <effective-session-resource>]
  <absolute-tools-xcov> --stdio-loop
```

queue/resource 优先级：

1. `session.open.queue/resource`；
2. `XVERIF_LSF_SESSION_QUEUE/RESOURCE`；
3. queue 默认 `interactive`；
4. resource 默认不传。

队列处理必须与 xdebug 一致并补齐 xcov adapter 验证：

- queue/resource 去除首尾空白后必须非空；
- 使用 argv 加入 `-q/-R/-J`，不拼 shell 字符串；
- job name 使用共享的安全唯一命名策略；
- 捕获 LSF submission 中的 job id 和 submitted queue；
- scheduler framing 不得进入 xcov JSONL ready/response 队列；
- 同时记录 requested queue/resource、effective queue/resource、submitted queue、job name、job id、
  launcher mode 和 lifecycle state；
- 如果 LSF 把任务重定向到其它 queue，保留 requested/submitted 两者并明确标记；
- `session.open/status/list/doctor` 提供必要队列和 job 信息；
- bsub 在 ready 前退出返回 scheduler 层错误；
- PEND 超过 startup timeout 明确报告 queue congestion，不能误报 VDB、NPI 或 parser 错误；
- timeout/cancel/open failure 优先按 job id `bkill`；未取得 job id 时按唯一 job name 清理；
- 无法确认清理结果时保留 unresolved tombstone；
- tombstone 存在时拒绝同 alias reopen；
- close、kill、gc、transport loss 和 server shutdown 复用共享分阶段清理；
- bkill/本地 wrapper 只部分成功时返回 `SESSION_CLEANUP_PARTIAL_FAILURE`；
- xcov adapter 接受的 queue/resource 必须真实转发，不能静默忽略。

### 15.9 内层 URG 的独立 LSF 作业合同

新增明确配置：

```text
XVERIF_XCOV_URG_BACKEND=direct|lsf
XVERIF_XCOV_URG_QUEUE=<required when lsf>
XVERIF_XCOV_URG_RESOURCE=<optional>
XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC=<finite positive number>
XVERIF_XCOV_URG_RUN_TIMEOUT_SEC=<finite positive number>
XVERIF_LSF_BSUB=<validated command>
XVERIF_LSF_BKILL=<validated command>
```

目标部署固定 `XVERIF_XCOV_URG_BACKEND=lsf`。是否 direct 由显式配置决定，不能因为 PATH 中存在
`bsub` 或 `XVERIF_LSF_BSUB` 就自动切换；LSF 失败也不得改为 direct。

内层 canonical argv：

```text
bsub -K
  -J <unique-urg-job-name>
  -q <urg-queue>
  [-R <urg-resource>]
  -oo <session-working-dir>/urg.<request>.stdout
  -eo <session-working-dir>/urg.<request>.stderr
  <absolute-urg-path> -full64 ...
```

规则：

- URG queue 在 LSF 模式必须显式配置，不猜测或继承外层 session queue；
- 每次 URG invocation 有独立 job name/job id；
- 记录 requested/submitted queue、resource、job id、exit status、开始/结束时间、argv hash 和 report path；
- 不记录完整敏感环境、license 或不必要的全局唯一信息；
- submission failure、PEND timeout、RUN timeout、URG nonzero exit、report incomplete 使用不同错误码；
- timeout、request cancel、session close 或 outer job shutdown 时精确 bkill；
- 无法确认内层 job 清理时，外层 session 进入 cleanup partial/tombstone；
- VDB、EL、cache、report、stdout/stderr 都必须是相关计算节点可见的绝对共享路径；
- cache producer 持锁等待内层 job；cache hit 不提交新 job；
- session close 前确认没有运行中的 URG job，才能清理 mutable working files。

### 15.10 安全、完整性和可靠性修复

#### VDB identity / XCOV-SEC-01

将 `xcov.run-manifest.v1` 升级为无歧义版本：

- path 使用长度前缀或 canonical serialization；
- 每个 entry 独立 digest；
- entry type 参与 hash；
- symlink 明确拒绝或编码 link type/target；
- 文件内容用真实 byte count；
- directory inode size 不作为内容大小；
- entry 排序；
- 旧版歧义 manifest 拒绝或通过正式入口重建。

#### Tool provenance / XCOV-SEC-03

- `VCS_HOME`/`VERDI_HOME` 已配置但无效时直接失败；
- URG 必须来自验证过的绝对路径；
- 记录并校验 URG version；
- pynpi import 后校验实际 `__file__`；
- 禁止从 PATH 或提前插入的 `sys.path` 静默选择另一套安装；
- 禁止任何 provenance failure fallback。

#### Export path / XCOV-SEC-02

所有 export action 使用同一个 resolver：

- 默认 root 为 `.xverif/xcov_exports`；
- relative path 解析后必须留在 root 内；
- 拒绝 `..` escape；
- 拒绝中间 symlink escape；
- absolute path 只有公开合同显式允许且位于 configured export roots 时才接受；
- code/assert/functional/CSV/EL 使用同一规则；
- 写入同文件系统 staging；
- 校验、fsync 后 atomic replace/publish。

#### Exclusion consistency / XCOV-DATA-01、XCOV-RES-02

- close 不丢失 dirty reason；
- EL、CSV reason、summary revision 明确关联；
- save/unload/mutation 正确使 summary cache 失效；
- 自动创建的 exclusion working directory 在安全 close 后清理；
- partial cleanup 保留 tombstone 和可恢复路径。

#### Resource limits / XCOV-RES-01、XCOV-PERF-04

在完整扫描或生成前执行：

- 最大 scope selector 数；
- 最大 metric 数；
- 最大 gap/detail 条数；
- 最大 CSV bytes、record 数和单字段长度；
- 最大 XML/text artifact bytes；
- 最大 response rows/bytes；
- 完整分析计数与返回计数分离；
- 截断包含 `truncated` 和 truncation scope。

#### Atomicity and observability / XCOV-REL-01、XCOV-OBS-01

- functional/assert/CSV/EL 全部事务式发布；
- manifest 原子更新；
- logging failure 不能完全吞掉；
- 响应/日志可观察 cache hit/miss、parser counts、URG job state 和 NPI initialized state；
- 不输出 token、license、cookie、完整敏感 session/job id 或其它凭据。

### 15.11 超大型 full64 fixture 正式化

将第 14 节 ignored tmp 实验的 generator 和构建 recipe 迁入：

```text
xcov/fixtures/large_summary
```

不提交生成后的 RTL、simv、VDB、URG report 和巨型日志。

固定生成规模：

- 3,000 个 leaf module 加 1 个 top；
- 总 RTL 约 375,053 行，必须大于 200,000 行；
- 每个 leaf 25 个端口；
- 14 个 input、11 个 output；
- 5 个 128-bit input 和 5 个 128-bit output；
- 另有 control/status/tag/valid/ready/flush/enable/error/busy；
- sequential/combinational branch、8-state FSM、condition/toggle；
- 每 leaf 一个 assertion、一个 cover property、五个 coverpoint、两个 cross；
- stimulus 256 个主循环，结束约 523 ns；
- VCS compile、simulation 和 coverage tooling 使用 `-full64`。

在 fixture catalog 注册 `xcov.large_summary`。FixtureStore fingerprint 包含：

- generator source hash；
- generator arguments；
- build recipe；
- semantic probe version；
- VCS tool identity；
- coverage compile/simulation options；
- 会影响输出的正式环境变量。

semantic probe 校验：

- RTL 行数；
- module/leaf 数；
- 每 leaf 端口数；
- 128-bit input/output 数；
- 仿真周期和结束 marker；
- VDB marker；
- root scope 可见；
- `design_stats.json` 与实际生成内容一致。

缓存规则：

- 只允许正式 `pytest --xverif-prepare xcov.large_summary` 构建；
- prepare 在 host/EDA 环境执行；
- regression/nightly 只消费 FixtureStore cache；
- cache miss 是明确 preflight/usage failure；
- 不自动仿真、不换小 fixture、不降级为 SKIP。

新增 `xcov.large_summary_regression`，验证：

- 3,001 个 code instance scope；
- assertion 和 cover property typed parse；
- functional covergroup/variant/instance/point/cross typed parse；
- root SCORE 与 URG 一致；
- read-only open/query/close 的 NPI init count 为 0；
- cold query 只提交一个 summary URG job；
- warm cache hit 不再提交 URG job；
- multi-scope/multi-metric 不重复生成 summary；
- close 不运行 URG；
- parse/aggregate operation count 近似线性。

性能门禁不使用受集群负载影响的严格 wall-time 比值；使用 URG invocation count、cache hit、IR node
visit count 和宽松总 timeout。另增加 1k/10k synthetic IR unit benchmark，专门阻断 O(N²) 回归。

### 15.12 x-npi 最后阶段

x-npi coverage 文档改为两条明确路径：

- URG：summary、tests、hierarchy、统计、gap 和 report/export 的推荐路径；
- NPI：exclusion target resolution、EL load/set/save/unload。

必须明确告诉 AI：pynpi coverage API 的对象模型存在必须遍历 coverage tree 的结构性缺陷，大规模
summary/report 不应优先使用 NPI；xcov 已验证的 fixed URG summary 是推荐方案。

代码调整：

- 删除 coverage helper 中 `_safe_call` 的异常吞掉、零参数重试和 None fallback；
- public exclusion helper 使用严格签名和明确错误；
- handle 生命周期使用共享 release helper，不猜测 `Handle.release()`；
- 加入可独立使用的 URG read/export helper；
- 加入与 xcov canonical CSV 合同一致的 parser、formatter、validator；
- 加入 CSV→EL compiler；
- 加入 EL load/save/unload；
- reason 继续保存在 CSV sidecar；
- 明确不支持无损 EL→CSV；
- x-npi 安装后必须独立可用，不能 import 未安装的 xcov 私有 module；
- xcov 与 x-npi 使用共享测试向量保证 CSV/EL 行为不漂移。

同步范围：

- `skills/x-npi/SKILL.md`；
- coverage/runtime references；
- scripts/examples；
- `agents/openai.yaml`；
- `skills/xverif` 的 xcov 路由和 exclusion 工作流；
- xcov README/MCP examples。

skill 验收：

- 对应 `skills.*` catalog suite；
- Markdown links；
- 可复制 shell/Python/JSON 示例；
- strict error propagation；
- CSV multiline、invalid columns、duplicate locator；
- CSV→EL；
- EL load/save/unload；
- 不存在 EL→CSV 错误承诺；
- URG command snapshot；
- 正式安装到 `~/.codex/skills` 和 `~/.claude/skills`；
- 逐 skill 执行 `diff -qr`。

### 15.13 分阶段提交边界

实施过程按以下顺序提交，不能把全部改动压成一个不可审查的 commit：

1. `补充 xcov URG 实测、XML 能力边界与全面优化基线`
   - 只提交本报告的基线、完整计划和实验结论。
2. `重构 xcov URG 读取后端并建立三类覆盖率严格 IR`
   - typed parser、IR、schema 收紧、score/scope 修复及 focused tests。
3. `拆分 xcov URG 查询与延迟 NPI exclusion 生命周期`
   - session open 无 NPI、lazy exclusion context、dirty reason 和 close 语义。
4. `引入 xcov 内容寻址 URG 缓存并消除平方级聚合`
   - cache、locks、atomic publish、LRU、stream parse、complexity tests。
5. `复用 xdebug LSF 队列合同并完善 xcov session 作业生命周期`
   - 外层 `bsub -I`、queue/resource、job identity、cleanup/tombstone。
6. `为 xcov URG 增加独立 bsub 队列、超时与清理管理`
   - 内层 `bsub -K`、独立 queue/resource、timeout、bkill、cache producer 集成。
7. `修复 xcov VDB 身份、导出边界、资源限制与数据可靠性`
   - 全部剩余 P1/P2/P3 安全、可靠性和资源问题。
8. `将超大型 full64 coverage fixture 纳入缓存回归`
   - generator、catalog、probe、大型回归和缓存合同。
9. `重构 x-npi coverage 指南并加入严格 CSV 转 EL 能力`
   - 最后一个功能阶段，同步 x-npi/xverif skill 并安装验收。
10. `完成 xcov 全量优化并记录全仓与真实 LSF 验证结果`
    - 只在全部门禁完成后更新最终结果和状态，不混入未验证功能。

每次 commit 前必须：

- 执行 `git status --short`；
- 执行 `git diff --cached --name-only`；
- staged 清单精确等于该阶段白名单；
- 不使用 `git add .`；
- 不纳入用户的 `AGENTS.md` 改动和无关的
  `doc/xdebug-comprehensive-code-review-2026-08-11.md`；
- commit message 使用中文，详细说明动机、范围和验证结果。

### 15.14 P1/P2/P3 闭环映射

| ID/新增缺陷 | 解决阶段与验收 |
| --- | --- |
| XCOV-SEC-01 | manifest v2 无歧义 hash；collision regression |
| XCOV-SEC-02 | 统一 export resolver；absolute/relative/`..`/symlink tests |
| XCOV-DATA-01 | dirty reason close gate；explicit discard tests |
| XCOV-COR-01 | typed query 实际应用 metrics filter |
| XML parent/child double count | 父 scope 直接采用 URG subtree 数值；root SCORE 对照 |
| exclusion stale summary | EL digest/revision 纳入 cache key |
| ignored test selector | 从 schema 删除并返回 `SCHEMA_INVALID` |
| functional identity/bin | typed functional IR；variant/instance regression |
| assert scope/semantics | typed assertion IR；property/scope regression |
| XCOV-COR-02 | exact/subtree hierarchy boundary selector |
| XCOV-PERF-01 | 一次建索引；1k/10k operation-count gate |
| XCOV-PERF-02 | summary cache；合并 detail invocation；不复制完整 URG 原文 |
| XCOV-PERF-03 | close invocation count 为 0 |
| XCOV-PERF-04 | 线性 CSV state machine benchmark |
| XCOV-RES-01 | scan/generation 前置 budgets 和 truncation contract |
| XCOV-OPS-01 | MCP 一 session 一进程；native 一 live session；lazy NPI |
| XCOV-SEC-03 | exact tool/module provenance；无 PATH/sys.path fallback |
| XCOV-COR-03 | x-npi strict call，无重试/吞错 fallback |
| XML false completeness | corrupt/missing/unknown type 明确失败 |
| XCOV-REL-01 | 所有 export staging + atomic publish |
| XCOV-RES-02 | safe close 清理 owned working directory |
| XCOV-OBS-01 | atomic manifest、observable logging failure 和 job/cache 状态 |

### 15.15 分阶段测试和最终验收门禁

每阶段先从 `testinfra/fixtures.v1.yaml` 和 suite catalog 核对正式 fixture/suite/gate membership，不根据
cost 或相邻 suite 猜 gate。源码修改必须运行关联 focused suite；VCS、URG、NPI、真实 VDB、真实
LSF 和 MCP stdio-loop 全链路测试在 host 环境执行。

#### 静态和单元门禁

- request/response schema 和 examples；
- strict JSON/closed schema；
- code/assert/functional parser；
- scope/SCORE/metric filter；
- cache key/lock/atomic/LRU；
- CSV linear parser；
- provenance manifest v2；
- export path safety；
- fake LSF queue/job/cleanup；
- x-npi strict helper 和 CSV→EL；
- skill links/examples/catalog。

#### 真实 xcov focused 门禁

- 现有 unit/URG backend/export/code/assert/functional/exclusion suite；
-真实 VDB summary 与 URG 输出对照；
- read-only lifecycle 的 pynpi init count 为 0；
- exclusion 首次 lazy init 和后续复用；
- EL mutation 后 cache invalidation；
- close 无 URG；
- fullchain MCP stdio-loop。

#### 真实 LSF full-chain 门禁

必须逐项证明：

1. MCP `session.open` 直接提交外层 `bsub -I ... tools/xcov --stdio-loop`；
2. requested/effective/submitted session queue 信息正确；
3. queue/resource 真实进入 bsub argv；
4. outer job name/job id 可用于 status 和 cleanup；
5. PEND、ready、rejection、startup timeout 可诊断；
6. summary cache miss 提交内层 `bsub -K urg -full64 ...`；
7. 内层 requested/submitted queue/resource/job id 和 exit status 正确；
8. cache hit 不再提交 URG job；
9. read-only session 不加载 NPI；
10. 第一次 exclusion 在外层 xcov job 中初始化 NPI；
11. exclusion 后 `-elfile` 和新 EL digest 生效；
12. close/cancel/timeout/server shutdown 无未记录的 orphan job；
13. bkill 部分失败返回 partial failure 并保留 tombstone；
14. 任一路径均没有 direct fallback。

#### 超大型 fixture 门禁

- fixture semantic validation 全部通过；
- 3,001 scope 和三类 typed coverage 完整；
- root SCORE 与 URG 一致；
- cold/warm invocation count 正确；
- operation count 未退化到 O(N²)；
- regression/nightly 只消费缓存；
- cache miss 通过正式 `--xverif-prepare` 补齐，不自动构建或 SKIP。

#### 全仓最终命令

```bash
.conda-xverif/bin/pytest --xverif-gate fast
```

```bash
XVERIF_TEST_EXECUTION_ENV=host \
  .conda-xverif/bin/pytest \
  --xverif-fixture-validation \
  --xverif-all-fixtures
```

```bash
XVERIF_TEST_EXECUTION_ENV=host \
  .conda-xverif/bin/pytest \
  --xverif-gate regression \
  -n auto
```

```bash
XVERIF_TEST_EXECUTION_ENV=host \
  .conda-xverif/bin/pytest \
  --xverif-gate nightly \
  -n auto
```

真实 LSF focused suite 使用 catalog 的正式 suite id 和明确配置的 session/URG queues。fixture cache miss
只通过：

```bash
pytest --xverif-prepare <fixture-id>
```

补齐，不自动仿真、不切换数据源、不降低测试层级、不把 required 变成 SKIP。

最终报告必须记录：

- 每个 P1/P2/P3 对应的修复 commit；
- URG/NPI 边界验证；
- cache key、cold/warm 和 invalidation 结果；
- 大型 fixture 指纹和 design stats；
- 外层/内层 LSF queue 与 cleanup 结果；
- fast、fixture validation、regression、nightly 和真实 LSF suite 结果；
- 任何未运行门禁的真实阻塞原因；
- 不记录敏感 license、token、cookie 或完整唯一 job/session id。

## 16. 分阶段实施记录

### 16.1 阶段 1：固定 URG 合同和三类 typed IR

提交 `20eadf4` 已完成以下闭环：

- summary 固定执行 `urg -full64 -dir <vdb> -report <dir> -xml_verbose -format text -show summary`；
- 六件套 `session.xml/tests.txt/dashboard.txt/modlist.txt/groups.txt/asserts.txt` 缺失或为空均 fail-closed；
- `session.xml` 使用 streaming `iterparse`，code、assert 和 functional 按各自 XML `type`
  进入独立 IR，不再把后三者套用 code coverage 结构；
- test list 只从 `tests.txt` 读取；scope hierarchy、subtree metric、assert object 和
  functional variant/instance 选择均建立明确合同；
- summary 读取路径删除 NPI fallback，公开 schema 删除固定 URG 结构无法可靠支撑的字段。

验收结果：`xcov.unit` 127 passed，host `xcov.urg_backend` 7 passed，
`skills.xverif` 16 passed。

### 16.2 阶段 2：URG-only session 与 exclude-only lazy NPI

本阶段实码审计确认，旧边界比“构造函数立即 import pynpi”更深：

1. `SessionManager.open` 默认构造 `NpiCoverageBackend`，因此 read-only session 也执行
   `npisys.init + cov.open + test handle merge`；
2. code gap export 调用 `attach_gap_locators` 遍历 NPI，并把 scope/path/type/name 写入 JSON；
3. assert/functional gap export 直接调用 `gap_items` 全量遍历 NPI；
4. 所以只把 backend 构造改为 lazy 不能满足“summary/scope/gap/detail 零 NPI”。

当前实现改为：

- 默认 `UrgCoverageBackend` 只持有固定 URG index；`session.open`、`tests.list`、summary、
  scope、assert/functional summary、三类 export 和 session close 均不创建 NPI；
- `exclude.*`、`exclude.csv.*`、`export.exclude` 首次执行时，session 内只创建一个
  `NpiCoverageBackend` exclusion context，后续复用，close 时仅在确实创建过时关闭；
- code/assert/functional 导出统一发布 `xcov.urg_semantic.v1`，不再持久化 NPI handle、
  traversal path 或数据库内部 ID；
- assert detail 从 `asserts.txt` 的 assertion/cover property/cover sequence 表解析；
  functional detail 从 `grpinfo.txt` 的 Group/Group Instance、Variable/Cross 和 uncovered
  bin 表解析；export 阶段不 import pynpi；
- `exclude.add` 才把选中的 URG 语义 gap 解析为临时 NPI target。assertion 名会规范化
  NPI 内部 `.assert.<index>.` 路径；functional cross bin 会规范化 URG 的 `] [` 与 NPI
  的 `|` 表达，真实复杂 fixture 的 12 个 assertion gap 和 115 个 functional gap 均可解析；
- 在调用 `database.handle_by_name` 前，必须先用 URG hierarchy 验证 code payload scope。
  实测把未知 scope 直接交给 vendor API 会在 `libNPI.so` 的
  `chdl_database_hdl_t::get_handle_by_name` 内 SIGSEGV；现在未知 scope 返回
  `EXCLUSION_EXPORT_PREFLIGHT_FAILED/EXPORT_SCOPE_NOT_FOUND`，不会进入 NPI；
- 已排除对象可能从 NPI score 视图隐藏，旧 gap artifact 因而可能无法再次解析。曾尝试
  对所有 leaf 探测 report-time status 以恢复目标，但 vendor NPI 以 139 退出，已删除该路径。
  正式合同是重新导出当前 gap，禁止绕过 wrapper 或调用低层 handle lookup 猜测对象。

当前验收证据：

- `xcov.unit`：130 passed；
- host `xcov.modinfo_complex`：5 passed；
- 单元 instrumentation 证明 read path 的 NPI factory 调用次数为 0，首次 exclusion 为 1，
  后续 exclusion 保存仍为 1；
- 真实 fixture 在 code/assert/functional export 后均断言 `npi_initialized=false`，执行
  `exclude.add` 后才变为 `true`；
- 两次 vendor 139 已通过 core stack 定位并形成前置 scope gate 与禁止 status-probe 的
  产品约束，不作为可接受测试结果；最终阶段仍需重新运行全部关联门禁。

提交 `703b0c6` 已完成本阶段闭环。

### 16.3 阶段 3：内容寻址缓存与线性聚合

本阶段实现默认位于 `.xverif/xcov/cache/urg-summary` 的内容寻址 URG summary cache。
cache key 不依赖 VDB 路径或 mtime 的表象，而包含 VDB 资源内容摘要、可选 run manifest
摘要、URG 绝对路径/版本/文件身份、固定 argv、merged selection、parser/cache 版本以及
可选 EL 内容摘要。相同输入只生成一次；EL 或 run manifest 内容改变均产生不同 key。

发布协议采用每 key `flock`、同文件系统 sibling staging、六件套严格解析、artifact
SHA-256/size 与语义计数 manifest、文件和目录 `fsync`、原子 rename 以及最后写入的
`COMPLETE` marker。读取时重新验证 manifest 和六件套哈希；损坏 entry 被隔离后重新生成，
不会被当作命中，也不会回退到 NPI。并发 cold miss 的两个调用者只允许一个真正执行 URG。

资源治理包括：默认 20 GiB/128 entries LRU、全局 eviction lock、正在生成或被读取的
per-key lock 保护、24 小时 abandoned staging 清理以及可配置的 bytes/entries 上限。
缓存返回前已把 immutable typed IR 全量解析到内存，session 后续不再读取 entry 文件，
因此释放 key lock 后不需要额外 pin；LRU 删除磁盘 entry 不会影响 live session。

同时完成三项热点修复：

- scope 导出先一次建立 selected-parent adjacency，再生成 navigation，操作数从逐 scope
  扫描全集的 O(N²) 降为严格 2N；1,000/10,000 scope 门禁分别验证 2,000/20,000 次操作；
- 删除未被合同使用且会重复累加 ancestor 的 `_scope_coverage` 路径，父 scope 继续直接采用
  URG subtree 数值；
- code export bundle 升级为 v2，所有 scope/metric JSON 和 XOUT 共用唯一
  `raw/modinfo.urg.txt`，不再为每个 metric 复制相同原文；session close 先读取已有状态快照，
  不会为关闭动作触发一次 URG。

真实复杂 fixture 实测：旧导出 10 份重复 raw、总计 1,257,575 bytes；新 bundle 仅一份
110,780-byte raw、总计 264,735 bytes，体积减少约 79%。同一 VDB 的固定 summary cold
耗时 0.894242 秒，warm hit 为 0.017770 秒，约 50 倍加速；两次状态使用相同 key，且
`hit` 依次为 false/true。

阶段门禁结果：`xcov.unit` 136 passed，host `xcov.urg_backend` 7 passed，host
`xcov.modinfo_complex` 5 passed，`skills.xverif` 16 passed；全部使用正式 catalog focused
入口并通过。

### 16.4 阶段 4：MCP 外层独立 stdio-loop 与 fake LSF

代码复核确认，共享 MCP 层原本已经使用 `McpSessionManager -> LsfLauncher -> BsubRunner`
链路；xcov 的每个 managed session 会直接提交
`bsub -I -J <job> -q <queue> [-R <resource>] tools/xcov --stdio-loop`。因此不存在“同一个
native stdio-loop 同时承载多个 MCP xcov session”的架构缺陷，本阶段没有重造 manager，
而是补齐原实现缺失的 native capacity 和调度事实合同。

具体修复包括：

- native `SessionManager` 最多保留一个 live VDB session；同进程第二次用不同 name open
  在读取 manifest 或创建 backend 前返回 `SESSION_CAPACITY_EXCEEDED`；
- MCP 多 session 继续一 session 一进程/一 LSF job，fake LSF 以两个并行 xcov session 的
  不同 subprocess PID 证明隔离；
- queue/resource 优先级固定为 open 显式值、`XVERIF_LSF_SESSION_QUEUE/RESOURCE`、queue
  默认 `interactive` 与 resource 省略；direct 模式只保留 requested 事实，不伪造 effective
  或 submitted LSF 参数；环境值和显式值均严格拒绝空值或首尾空白，避免记录与 argv 漂移；
- compact session record 始终发布 `scheduler.requested/effective/submitted/status`，包含
  queue、resource、job name/id，能够区分 submitting、submitted、ready、PEND 导致的
  startup timeout、ready 前 rejection、closed 和 cleanup partial；
- bsub job submission 行以及 job-id 已识别后继续出现的 `<<Waiting for dispatch>>`、
  `<<Starting on ...>>` framing 均不会污染 xcov JSONL；其它未知非 JSON stdout 仍立即失败；
- startup timeout/rejection 均保留 submitted 参数和 job identity，执行 process terminate
  与精确 bkill；任一路径不切换 direct，也不启动另一个 backend。

本机没有真实 LSF，按用户要求复用 xdebug 的 repository fake LSF。阶段门禁当前为
`xcov.unit` 137 passed、`xverif_mcp.unit` 163 passed、host `xverif_mcp.process` 141 passed、
`skills.xverif` 16 passed 和 `skills.xverif_admin` 1 passed；全部通过正式 catalog focused
入口执行。

### 16.5 阶段 5：内层 URG batch LSF 与 fake LSF

旧 `UrgRunner` 只要发现通用 `XVERIF_LSF_BSUB` 就自动进入 LSF，并在命令缺少 interactive
flag 时追加 `-I`。这会把外层 MCP session 的 LSF 环境误解释为内层 URG 配置，既没有独立
queue，也没有 job id、PEND/run timeout 或 bkill，确认属于实际架构缺陷。

本阶段改为：

- `XVERIF_XCOV_URG_BACKEND=direct|lsf` 是唯一 backend 选择，默认 direct；仅设置
  `XVERIF_LSF_BSUB` 或外层 `XVERIF_MCP_BACKEND=lsf` 不会触发内层 LSF；
- backend=lsf 必须显式提供 `XVERIF_XCOV_URG_QUEUE`，resource 只来自独立的
  `XVERIF_XCOV_URG_RESOURCE`；禁止继承或猜测外层 session queue；
- 每次 cache miss/detail export 独立执行
  `bsub -K -J <unique> -q <queue> [-R <resource>] <urg> -full64 ...`；override command
  不得预置 `-I/-K/-J/-q/-R`，避免重复或互相覆盖；
- runner 分别记录 submitting、submitted/PEND、running、completed/failed、startup timeout、
  run timeout、submission failure 和 cancel；job id、job name、queue/resource、exit status
  写入 lifecycle log，summary cache 的 `urg_execution` 同时提供公开观察面；
- job submission 后继续等待 `<<Starting on ...>>` 或首个真实 job 输出，job id 本身不再被
  误判为 PEND 已结束；startup timeout 与 run timeout 分开配置；
- timeout/cancel 优先按 job id bkill，尚未取得 id 时按唯一 job name；随后终止本地 bsub
  process group。bkill partial failure 明确记录，不执行 direct fallback；
- URG 的 `-dir/-report/-elfile/-hier` 全部规范化为绝对路径；code export 的临时 hier/report
  移到 output staging 同一文件系统，避免默认 `/tmp` 对计算节点不可见；调用方仍必须保证
  VDB、EL、cache、report、hier 与 log 是共享存储；
- warm cache hit 在校验 LSF 配置后直接返回 `submitted=false,status=cache_hit`，不创建
  bsub process/job。

fake LSF 覆盖精确 `-K/-J/-q/-R`、cold 一次提交/warm 零提交、submitted→PEND→running、
startup/run timeout、按 job identity bkill、bkill partial failure、direct 与外层环境隔离。
本机没有安装真实 LSF，因此依照用户要求复用 xdebug 的 repository fake LSF，不把 fake
结果表述成真实集群验收。full-chain 用例实际启动外层 `bsub -I tools/xcov --stdio-loop`，再由
该独立 loop 在 cold cache miss 时启动内层 `bsub -K urg ...`；两层使用不同 queue，公开状态
可观察 requested/effective/submitted queue、job name/id 和 lifecycle。第一次 summary 后
`npi_initialized=false`，第二次相同 summary 命中 warm cache 且内层 `submitted=false`，证明
read-only coverage 没有加载 NPI，cache hit 也没有提交 URG job。

阶段门禁结果：

| suite | 执行面 | 结果 |
|---|---|---:|
| `xcov.unit` | regression/catalog | 148 passed |
| `xcov.urg_backend` | regression/host，真实 URG/VDB | 7 passed |
| `xcov.modinfo_complex` | regression/host，真实 URG/VDB | 5 passed |
| `xcov.mcp_integration` | nightly/host，含 full-chain fake LSF | 17 passed |
| `xverif_mcp.process` | regression/host | 141 passed |
| `skills.xverif` | catalog | 16 passed |
| `skills.xverif_admin` | catalog | 1 passed |

以上 focused suite 均由正式 catalog gate 入口执行；不存在失败后切换 direct、继承外层 queue
或用窄化测试替代 full-chain 的情况。
