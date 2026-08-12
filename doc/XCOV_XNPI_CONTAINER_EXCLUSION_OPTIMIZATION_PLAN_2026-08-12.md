# xcov 与 x-npi Coverage Exclusion 优化及容器级增强任务书

日期：2026-08-12

状态：实施中

分支：`master`

远端：`origin/master`
进度 source of truth：本文档

## 1. 任务目标

本任务在一次统一实施中优化 xcov 与 x-npi 的 coverage exclusion。coverage 读取继续固定使用
`urg -full64 -xml_verbose -format text -show summary`；NPI 只负责 exclusion 目标定位、状态设置和
EL load/save/unload。最终交付 instance、covergroup、coverpoint、cross 容器级排除，支持基于
URG XML 真实实例层次的递归 instance exclusion，并消除 code/assertion 与 functional resolver 中
已经实测确认的不必要全量遍历。

本任务不支持 module-definition selector，不加载 design/daidir 来反查 module instances，不通过
私有 EL 语法或 NPI hierarchy 补扫 fallback。CLI、MCP、schema、CSV、x-npi helper、skill、测试和
文档必须同步，所有批量修改必须先完整预检、再原子设置，失败恢复 baseline EL 与 reason metadata。

## 2. 已确认事实与基线

1. 固定 URG XML 已包含 code instance hierarchy、assertion 和 functional typed tree；xcov 内容寻址
   cache 已持久化 `session.xml`、`tests.txt`、`dashboard.txt`、`modlist.txt`、`groups.txt`、
   `asserts.txt`。
2. xcov session 内已解析 `full_name/parent/depth` scope IR，`scope.children recursive=true` 已使用
   该 IR；但 `_add_synthetic_hierarchy_scopes` 会补 synthetic ancestors，不能直接作为 NPI target。
3. coverage NPI 的 `handle_by_name` 只支持已知 instance fullname；coverage model 没有按 module
   definition 反查 instances 的接口，也没有 module-definition exclusion handle。
4. Language NPI 的 `mod_define_get_inst` 需要额外 `load_design`，不能仅凭 VDB 工作，本任务不引入。
5. instance exclusion 只排除 instance self，不递归传播到 child instances。父实例及全部后代必须
   分别设置，才能获得 subtree exclusion。
6. XML 真实 instance 展开加 `handle_by_name` 已在五层真实 VDB 上验证：6 个目标全部成功，NPI
   `instance_handles()` 调用为 0，URG 确认整个目标子树被排除且 sibling 不受影响。
7. covergroup、coverpoint、instance 均支持原生 container setter；point exclusion 会影响依赖 cross。
8. functional VDB 是 group→point/cross→bin 树，不是 bin 平铺。大型 VDB 实测全树 DFS 访问
   93,000 节点约 1.111 秒，request-pruned 访问 3,008 节点约 0.0190 秒，locator replay 访问 6 个
   业务节点约 0.00865 秒。
9. 合法 container exclusion 会令 URG ratio 出现 `0/0`；当前 x-npi parser 会执行
   `float(None)` 失败，xcov 也需要统一 null percentage 聚合语义。

## 3. 决策完成的公共合同

### 3.1 xcov actions

新增两组 action，CLI、native stdio-loop 和 MCP 同步发布：

- `exclude.instance.add/remove`
- `exclude.functional.add/remove`

Instance item 固定为 `scope`、`recursive`，add 额外要求非空 `reason`。一次请求最多 10,000 项；
`recursive=false` 只设置 exact instance self，`recursive=true` 从 URG XML 真实 adjacency 展开父及全部
后代。Module、def_name、wildcard、regex 均不接受。

Functional item 固定含 `target_kind=covergroup|coverpoint|cross`、`scope`、`covergroup`、`item`；add
额外要求 `reason`。covergroup 禁止 item，point/cross 必须提供 item；functional 不接受 recursive。

所有请求先展开、去重、检查 ownership、预检全部 handle/type/identity，再保存 baseline 并按稳定顺序
设置。任一失败必须 unload、reload baseline、恢复 metadata 并返回 `none_applied`。成功后更新 working
EL/revision/digest，使 URG cache key 自然失效。响应发布 requested/expanded/changed/already/removed、
target-kind 分布、atomic、transaction、rollback 与 request-root 到 exact-target 摘要。

### 3.2 Container CSV

既有三类 v1 不变，新增可选 `container_exclusions.csv`：

```text
# schema_version=xcov-container-exclusions.v1
# coverage_kind=container
target_kind,scope,covergroup,item,expansion_root,reason
```

- instance：scope 为 exact fullname；covergroup/item 为空；exact add 的 expansion_root 等于 scope，
  recursive add 的每个展开行保存原请求 root。
- covergroup：scope/covergroup 必填，item/expansion_root 为空。
- coverpoint/cross：scope/covergroup/item 必填，expansion_root 为空。
- CSV 永远保存 exact native targets，不保存动态 recursive 表达式。
- 缺少 container CSV 的旧三文件目录继续合法。
- validate/format/apply/compile/export 扩展为四类；compile 原子发布 `code.el`、`functional.el`、
  `assertion.el`、`container.el`，全部成功后才替换并 reload union。
- 同一 exact target 只允许一个 owner/reason；不同 expansion root 或 reason 命中同一 target 时返回
  `TARGET_OWNERSHIP_CONFLICT`，不做引用计数或后写覆盖。
- recursive remove 只按已记录 expansion_root 的 exact 集合移除；缺少完整 ownership 时拒绝，不按
  当前 XML 重新扩大集合。

### 3.3 x-npi 独立入口

x-npi 不依赖 xcov package/cache。新增 container CLI，接受 VDB、可选 existing fixed-summary report、
未提供 report 时的新 report output、exact/recursive instance、functional containers、reason、CSV/output
目录和 strict。流程为解析或生成 URG→展开真实 XML instances→构造 exact records→ownership 和 NPI
全量预检→baseline→原子 setter→发布 exact container CSV 与四 EL。stdout 仅一个 JSON。

## 4. 内部实现设计

### 4.1 URG typed IR

xcov 与 x-npi 各自在自身包内建立等价但无反向依赖的不可变索引：

- `xml_instances`
- `xml_instance_set`
- `xml_instance_parent`
- `xml_instance_children`

现有 scopes 可继续含 synthetic ancestors 服务查询，但每行需标识 `origin=xml|synthetic`，container
resolver 只接受 XML 真实 instance。真实 child adjacency 在 XML streaming parse 时建立；首次为
`O(S)`，单次子树展开为 `O(K)`。

`0/0` ratio 保存 covered=0、coverable=0、excluded 原值、coverage_pct/pct=null；多 metric SCORE 忽略
null metric，全部为 null 时 aggregate 也为 null，禁止伪造成 0% 或 100%。

### 4.2 x-npi resolver

- code/assertion 按 CSV exact scope 去重，使用 `db.handle_by_name` 直达并只打开请求 metric；预检保存
  整数 child path/type/name，apply 重放并逐级验证，不再从 top 扫 instance hierarchy。
- functional 只为请求建立 `O(R)` group/point/cross 前缀索引。预检按 group→point/cross→bin 剪枝；
  container 命中即停止；bin 只扫描当前 point 并临时建立请求 bin map。
- apply 只重放 group/point locator；path 越界或身份改变返回
  `TARGET_CHANGED_BETWEEN_PASSES`，不得重新全树扫描。
- 不缓存 native handle，不建立 VDB 全 bin 索引，不持久化 locator。

### 4.3 性能与资源边界

- recursive instance：XML index `O(S)`，每次展开和 exact setter `O(K)`；NPI hierarchy/metric/bin
  traversal 均为 0。
- code/assertion：`O(U + requested metric subtree)`，U 为唯一 exact scope 数，不再 `O(I)` hierarchy。
- functional：preflight 为请求相关 group/point 子树，apply 为 locator replay；禁止 `O(H×P)` 全树两遍。
- 批量 action/CSV 最多 10,000 request rows，展开后的 exact targets 也受显式资源预算约束。

## 5. 分阶段实施与提交

### 阶段 1：任务书与 Goal

- 写入本文和评审实验结论。
- 中文详细文档 commit。
- commit 后建立 goal，目标抽象本文，明确全部验收门禁。

### 阶段 2：URG IR 与 ratio

- xcov/x-npi 真实 instance adjacency、origin 标记和 immutable index。
- `0/0` null percentage 及聚合。
- parser/cache/scope focused tests。

提交主题：`重构：建立 URG 真实实例层次索引并支持零分母排除结果`

### 阶段 3：Container CSV

- 新 container v1 parser/formatter/validator。
- 四类 apply/compile/export 与四 EL 原子发布。
- ownership/reason/旧目录兼容和安全预算测试。

提交主题：`扩展：新增独立容器排除 CSV 与四文件原子编译合同`

### 阶段 4：x-npi resolver 与 CLI

- code/assertion handle_by_name。
- functional lazy locator 与 container setter。
- 独立 fixed-URG+NPI container CLI。
- 大型 fixture 性能和真实 VDB roundtrip。

提交主题：`优化：重构 x-npi 排除定位并新增独立容器操作入口`

### 阶段 5：xcov actions 与 MCP

- 两组 add/remove actions、schema、atomic transaction、ownership、reason、cache invalidation。
- CLI、stdio-loop、MCP adapter/schema/action smoke/integration 同步。

提交主题：`增强：为 xcov 发布实例与功能容器原子排除 actions`

### 阶段 6：正式回归与 skill

- comprehensive：self 非递归、recursive 6 targets、synthetic 排除、sibling 不变。
- exclusion：group/point/cross/leaf instance、EL reload、0/0。
- large_summary：3,001 scopes、线性 adjacency、lazy locator、warm cache。
- fake NPI：missing/ambiguous/identity-change/setter-failure/rollback/ownership/remove metadata。
- MCP/fake LSF、CSV multiline/symlink/path/预算。
- 同步 x-npi/xverif SKILL、references、examples、agents/openai.yaml。

提交主题：`测试与文档：固化容器排除语义、性能门禁和 Agent 指南`

### 阶段 7：最终验证

- 安装 x-npi/xverif skill 到 Codex/Claude 并 `diff -qr`。
- 全仓 fast、全部 fixture validation、host regression、host nightly。
- 更新本文全部 commit、测试、性能、限制和 push 状态。

提交主题：`验证：记录 xcov 与 x-npi 全量回归及最终交付结果`

## 6. 测试与验收门禁

每次 focused suite 前先用正式 `--xverif-plan` 核对 gate。真实 VDB/NPI/URG/VCS 均使用
`XVERIF_TEST_EXECUTION_ENV=host`；本机没有真实 LSF，只运行仓库 fake LSF，不 fallback direct。

Focused suites：`xcov.unit`、`xcov.exclusion_npi`、`xcov.urg_backend`、`xcov.large_summary`、
`xcov.mcp_integration`、`skills.x_npi`、`skills.x_npi_real`、`skills.x_npi_perf`、`skills.xverif`、
`skills.public_docs`、`xverif_mcp.unit`、`xverif_mcp.action_smoke`、`xdebug.mcp_fake_lsf`。

最终命令：

```bash
.conda-xverif/bin/pytest --xverif-gate fast
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-fixture-validation --xverif-all-fixtures
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate regression -n auto
XVERIF_TEST_EXECUTION_ENV=host .conda-xverif/bin/pytest --xverif-gate nightly -n auto
```

Fixture cache miss 只通过正式 `--xverif-prepare` 补齐，不自动仿真、不降级 required、不换数据源。

## 7. 完成判定

- 四类 container 可直接 exclude；module selector 在 schema/CLI/CSV/skill 中不存在。
- exact instance 默认 self-only；recursive 只展开 URG XML 真实 nodes。
- recursive 路径 NPI `instance_handles()` 为 0，synthetic scope 不传给 `handle_by_name`。
- functional container 不扫描 bin；functional bin apply 不重复全树扫描。
- code/assertion exact scope 不扫描整个 instance hierarchy。
- 所有批量操作全原子、可回滚，ownership 冲突严格失败。
- recursive reason 展开为 exact rows，可审计 remove。
- `0/0` ratio 正确发布 null percentage。
- 四 CSV/四 EL 原子发布，CLI/MCP/schema/examples/skill 一致。
- focused、fast、fixture validation、regression、nightly 全部通过。
- skill 安装 diff 通过；所有阶段中文详细 commit；`master` 成功推送 `origin`。

## 8. 进度记录

| 阶段 | 状态 | Commit | 验证与证据 | 备注 |
| --- | --- | --- | --- | --- |
| 1. 任务书与 Goal | completed | `1ef17aa` | 文档 diff/check；goal active | 未纳入无关工作树改动 |
| 2. URG IR 与 ratio | completed | `830ed38` | `xcov.unit` 166 passed；`skills.x_npi` 22 passed | XML 真实/synthetic 分离；`0/0` pct=null |
| 3. Container CSV | completed | `a29fa0a` | `xcov.unit` 167 passed；`skills.x_npi` 23 passed | 旧三文件兼容；四 CSV/EL 原子发布；容器定位器接通 |
| 4. x-npi resolver 与 CLI | completed | `71f3dca` | `skills.x_npi` 24 passed；CLI py_compile | 独立 fixed-URG container CLI；exact `handle_by_name`；locator trie replay |
| 5. xcov actions 与 MCP | completed | `bbfc108` | `xcov.unit` 169；`xverif_mcp.unit` 163；action smoke 1；fake LSF 3 passed | 四 action 动态发布；atomic ownership；fake LSF only |
| 6. 正式回归与 skill | completed | 本阶段提交 | exclusion 1；URG 7；large 2；x-npi real 7/perf 2；MCP 17；skills 16+3 passed | xcov CSV 也改为 exact scope 与 group-pruned resolver；四文件文档同步 |
| 7. 全仓验证与推送 | pending | - | - | - |

## 9. Git 与推送约束

每次提交前运行 `git status --short` 和 `git diff --cached --name-only`，staged 集合必须精确等于阶段
白名单；不用 `git add .`，不回滚用户改动。Commit 使用中文并写清动机、范围和验证。推送前确认
远端可 fast-forward；若远端前进则停止，不自行 pull/rebase/merge/force push。
