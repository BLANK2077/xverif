# xcov 七项边界问题修复与正式回归计划

## 目标与验收标准

本任务把 2026-08-13 已由真实 RTL、VCS、VDB 和 URG 复现的七项问题纳入正式测试，修复
xcov 与 x-npi 的对应实现，并消除 `xdebug.native_xout_all` 修改 tracked 审查报告的副作用。
最终要求分阶段中文提交、宿主全量门禁通过并直接推送 `origin/master`，不创建 PR。

验收标准如下：

1. 任意顶层模块名下的 module-only detail fallback 正常工作，不依赖 `top`。
2. 真实 `0/0` 和缺少 functional score metric 的无 coverage object 节点被规范化为
   `covered=0, coverable=0, missing=0, pct=null`；正分母缺分数仍严格失败。
3. URG Line `0/N` 生成 N 个可独立定位的 gap，gap 总数与 missing 一致。
4. navigation 的 selected scope 和 child metric 均能稳定渲染 null 百分比。
5. Condition 同时支持同行 expression 和 `EXPRESSION` 后接 `Number Term` 的布局。
6. 单 metric `--` 与整个实例无详情严格区分；单 metric、多 metric 请求结论一致。
7. 空 FSM self section 返回零 group、零 gap、null pct，不强制要求 summary。
8. x-npi 不再假设 root scope 名为 `top`，且与 xcov 使用一致的零对象/可评分平均语义。
9. `xdebug.native_xout_all` 正式测试前后 tracked 审查文档内容和哈希不变；只有独立显式发布
   工具可以更新该文档。
10. 所有 focused suite、fast、regression、nightly 和 skill 安装一致性检查通过。

## 硬边界

- 不修改 `testinfra/xverif_test/fixtures.py`、FixtureStore、fingerprint 算法、缓存目录结构、
  跨进程锁、immutable generation、`current.json` 或 publish/validation 机制。
- 不准备 `all-generated`，不清理、迁移或重建任何既有 fixture 缓存；只对本任务新增的两个
  fixture ID 执行显式 prepare 和 validation。
- 普通 gate 只消费缓存，不在测试函数中编译 RTL 或启动 URG fixture builder。
- coverage read 继续固定使用 full64 URG；不引入 NPI traversal fallback。
- 不提交 VDB、simv、URG report 或其它生成产物。
- 不提交故意失败的中间 commit；红灯通过正式 suite 运行结果和本文进度记录保存。

## 实施阶段

### 阶段 A：正式红灯 fixture 与 suite

- 从 `tmp/xcov-seven-real-vdb-20260813/design.sv` 提炼共享正式 RTL，新增：
  - `xcov.modinfo_edge_layouts`：任意名顶层、module-only fallback、generate `0/4`、
    Condition Number-Term、metric `--` 与空 FSM。
  - `xcov.zero_coverable`：同一 RTL 增加零 coverable functional 变体。
- RTL 必须保留纯例化父层、coverage-off 后只剩例化的父层、generate 子模块、packed/unpacked
  二维数组、`value[4][4]` generate-for 赋值、连续/过程赋值以及四层复杂嵌套三目。
- 在 `testinfra/fixtures.v1.yaml` 和 `testinfra/catalog.v1.yaml` 仅登记新增 fixture/suite，
  不修改 fixture runtime。
- 新增 `xcov.edge_cases` regression/nightly suite，七项各自独立测试，避免前序错误遮挡。
- `skills.x_npi_real` 复用零对象 fixture，验证真实 URG/XML 和任意 root。
- 宿主 prepare 新 fixture 并运行红灯；记录 run id、错误和对应问题编号。

### 阶段 B：xcov 修复

- `code_export` 按真实 scope 解析 module self-instance；按请求 metric 判断 `--`。
- 无 self object 的 metric 使用统一 null coverage；缺失 detail artifact 只有在 summary 能证明
  空 selection 时才合法，其它缺失仍 fail-closed。
- Line `0/N` 按覆盖对象数展开，并与 NPI ordered locator 保持一一对应。
- Condition parser 同时解析两种 URG 布局并保持原始 object count 与语义合并 count。
- 空 FSM 返回合法空 payload；navigation 明确区分 `pct=null` 与 `unavailable`。
- 所有 scope/root 多 metric 平均过滤不可评分 null；全部不可评分时返回 null。
- functional XML 仅在可证明无 coverage object 时允许缺少 score metric。

### 阶段 C：x-npi 同步

- `x_npi.urg` 同步无对象 functional 节点和可评分平均语义。
- `coverage_summary.py` 从 XML root 集合计算 root score，不查找固定 `top`。
- 多 root 按 metric 聚合 root covered/coverable，再对可评分 metric pct 做算术平均。
- 更新 `SKILL.md`、coverage reference、unit/real tests；不改变 URG/NPI 分工。
- 通过正式 skill suite 后安装到 Codex/Claude，并执行 `diff -qr`。

### 阶段 D：native XOUT 测试纯净化

- native XOUT matrix 始终写 pytest 临时报告并原地验证，不再替换 tracked 文档。
- 新增独立发布工具；只有显式调用且输入为验证通过的 final/73-action 报告时，才原子发布
  `doc/XDEBUG_XOUT_REAL_OUTPUT_REVIEW_2026-08-03.md`。
- 增加报告损坏、phase/action 数错误、原子发布和测试不污染工作树的合同测试。
- 同步 catalog 合同和 `doc/agents/xdebug/tests.md`。

## 验证顺序

1. 查询正式 gate plan，核对 focused suite membership。
2. 宿主 prepare `xcov.modinfo_edge_layouts` 和 `xcov.zero_coverable`；第二次 prepare 必须 cache hit。
3. 只校验两个新增 fixture，不运行全 fixture validation。
4. `xcov.unit`、`xcov.edge_cases`、`xcov.modinfo_complex`、`xcov.urg_backend`。
5. `skills.x_npi`、`skills.x_npi_real`。
6. `xdebug.native_xout_report`、`xdebug.native_xout_all`，并比较 tracked 文档哈希。
7. `make clean all`、fast、宿主 regression、宿主 nightly。
8. skill 安装和 Codex/Claude 目录一致性检查。
9. `git status --short` 确认无测试污染。

## 提交计划

1. `文档：建立 xcov 七项边界修复计划与验收矩阵`
2. `修复：完善 xcov URG 边界解析与真实 VDB 回归`
3. `同步：修正 x-npi coverage 根层级与空对象语义`
4. `测试：隔离 native XOUT 报告发布副作用`
5. `文档：记录 xcov 七项修复的完整验收结果`

每次提交前检查 `git status --short` 和 staged 文件精确白名单；提交信息使用中文并记录动机、
范围和验证。最终直接推送当前 `master` 到 `origin/master`。

## 进度记录

| 阶段 | 状态 | 证据 |
|---|---|---|
| 计划文档与 goal | 完成 | 计划提交 `b2eeb4c`；已建立带明确验收标准的执行 goal |
| 正式 fixture/suite 红灯 | 完成 | `20260813-150414-j776aguz`：1 个静态复杂度测试通过，七项真实 VDB 测试全部按预期失败 |
| xcov 修复 | 完成 | 提交 `6ef9573`；focused suite 共 189 项通过，七项真实 VDB 用例全部转绿 |
| x-npi 同步 | 完成 | 提交 `470c4af`；unit 25 项、real VDB 8 项通过，并同步安装到 Codex/Claude |
| native XOUT 纯净化 | 完成 | 提交 `0305de7`；report 11 项、all-actions 1 项通过，tracked 报告 SHA 不变 |
| 全量验收与推送 | 完成（待本文提交后推送） | clean build、fast 579、regression 1187、nightly 1288 通过 |

### 2026-08-13 正式红灯记录

- registry/catalog 静态门禁：`20260813-150308-otee0wwy`，54 passed。
- `xcov.modinfo_edge_layouts` 首次 prepare 发布 fingerprint
  `ab3f85e4d7598a20bd55ff552af7e60d04b6851776f1dc734de6a26c83f7733b`；第二次为
  `cache_validation` 命中。
- `xcov.zero_coverable` 首次 prepare 发布 fingerprint
  `752ef23a3a10c7180df3cf56bdbb11cf0ccd189cfbca12821f65dbf4228b9f03`；第二次为
  `cache_validation` 命中。
- 正式提交前只清理了新增 RTL 的末尾空白，因此仅对上述两个新增 ID 再次定向 prepare：
  - `xcov.modinfo_edge_layouts`：`20260813-153514-dp1vzoea`，最终 fingerprint
    `c3593f709bde233b12dceb014238a36b00a72dfc0954819691e71598c33af070`；
    `20260813-153536-pvmo96_z` 再次 prepare 为 cache hit。
  - `xcov.zero_coverable`：`20260813-153524-l_iezadj`，最终 fingerprint
    `f2ce2d0a1b19517fc48a4d9e44ec05f8c7b01a391dd48118690d9e97e65e8257`；
    `20260813-153542-ee9tjjcz` 再次 prepare 为 cache hit。
- 未执行 `all-generated`、fixture clean、全量 fixture validation，未修改 FixtureStore 或
  任何既有 fixture 定义/缓存指针。
- `xcov.edge_cases`：`20260813-150414-j776aguz`，1 passed、7 failed：
  1. 任意顶层：`target instance detail section is missing`。
  2. 零对象：`functional scope is missing its score metric`。
  3. Line `0/N`：`line construct missing count does not match gaps`。
  4. null navigation 前置空 selection：`URG did not produce modinfo.txt`。
  5. Condition Number-Term：`condition coverage object gap count does not match coverage missing`。
  6. 单 metric `--`：`FSM summary is missing`。
  7. 空 FSM：`URG did not produce modinfo.txt`。

### 2026-08-13 修复与 focused 验收记录

- xcov 提交 `6ef9573`：
  - `xcov.unit`：`20260813-151912-fkh0bd72`，169 passed。
  - `xcov.edge_cases`：`20260813-151944-sampp69n`，8 passed；其中 1 项验证正式 RTL
    复杂度，7 项分别对应七个红灯。
  - `xcov.modinfo_complex`：`20260813-152014-5b1no8i8`，5 passed。
  - `xcov.urg_backend`：`20260813-152036-aabkpqnc`，7 passed。
- x-npi 提交 `470c4af`：
  - `skills.x_npi`：`20260813-151408-wvx2230e`，25 passed。
  - `skills.x_npi_real`：`20260813-151431-pl9or62v`，8 passed。
  - `make install-x-npi-skill` 完成；排除安装器私有 manifest 后，repo source 与
    `~/.codex/skills/x-npi`、`~/.claude/skills/x-npi` 的 `diff -qr` 均为空。
- native XOUT 提交 `0305de7`：
  - `xdebug.native_xout_report`：`20260813-151709-1l5hvpnj`，11 passed。
  - `xdebug.native_xout_all`：`20260813-151753-beuvjorz`，1 passed。
  - 测试改为写 pytest `tmp_path`；显式发布工具独立验证 final/73-action 报告后才允许
    更新 tracked 审阅文档。
  - focused suite 前后及完整 nightly 后，`doc/XDEBUG_XOUT_REAL_OUTPUT_REVIEW_2026-08-03.md`
    SHA256 均为 `5d89c7609597959658efb55206ad6771ece782279110a2a2993a7fd984aa0810`。

### 2026-08-13 全仓最终验收记录

- `make clean all`：通过；统一重建 native xdebug engine 及各 Python 子工具。
- fast：`20260813-153550-7s_y9zja`，579 passed、706 deselected。
- host regression：`20260813-153645-yo0m6u3f`，1187 passed。
- host nightly：`20260813-154236-vzjd66_0`，1288 passed、2 skipped；两项 skip 均为
  环境未提供 `bsub`/`bjobs`/`bkill` 的真实 LSF 条件用例，与本次 coverage 修改无关。
- regression/nightly 均只消费已发布缓存，没有自动 prepare、fallback 或 fixture 迁移。
- 最终 `git status --short` 仅包含本文进度更新；fixture runtime 与 tracked XOUT 审阅文档
  均无 diff。
