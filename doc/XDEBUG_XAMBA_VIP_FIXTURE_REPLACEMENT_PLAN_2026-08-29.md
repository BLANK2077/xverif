# XDEBUG XAMBA AXI/APB VIP Fixture 并行接入计划

版本：2026-08-29

状态：P0–P4 已完成，全部验收门禁通过

工作仓库：`<xverif-repo>`

外部 VIP 仓库：`<xamba-vip-repo>`

## 1. 背景与目标

`xverif` 当前以 `xdebug.apb_vip` 和 `xdebug.axi_vip` 两套真实 SVT VIP fixture
提供 APB/AXI FSDB、daidir、仿真日志和协议 oracle。迁移期不能删除或改写这两套基线。

本任务新增两套使用 XAMBA UVM VIP 的并行 fixture 和对应测试：

- `xdebug.apb_xamba_vip`：由 XAMBA APB5 requester/completer 产生确定性 APB 波形；
- `xdebug.axi_xamba_vip`：由 XAMBA AXI4 manager/subordinate 产生确定性 AXI 波形；
- 两套 fixture 必须通过 XAMBA 仓库 checked-in filelist 直接集成；
- 新 suite 必须验证 fixture 产物和 xdebug 对协议波形的公开语义；
- 在 XAMBA 仓库新增一份基于其 README、API 文档、filelist 和公开测试合同的优化建议文档。

## 2. 约束与非目标

### 2.1 允许修改

- `xverif/testinfra/fixtures.v1.yaml` 中新增 fixture 登记；
- `xverif/testinfra/catalog.v1.yaml` 中新增 suite 登记；
- `xverif/testinfra/tests/` 中与新增登记直接对应的静态合同断言；
- `xverif/xdebug/testdata/waveform/` 下新增的 XAMBA fixture 文件；
- `xverif/xdebug/tests/synthetic/` 下新增的对应 pytest；
- 本计划书及其进度记录；
- XAMBA 仓库中一份新增的 VIP 优化建议文档。

### 2.2 禁止修改

- 不删除、不重命名、不改写现有 SVT fixture、suite 或测试；
- 不修改 xdebug 产品源码、action、schema、example、skill 或公共输出合同；
- 不修改 XAMBA 的 `src_clean/`、`tb_clean/`、filelist、Makefile 或工具脚本；
- 不复制 XAMBA 源码到 xverif，不绕过 XAMBA checked-in filelist 手工枚举 VIP 源文件；
- 不读取或反馈商业 VIP 内部实现信息到 XAMBA 仓库；优化建议仅使用 XAMBA 自身资料；
- 不静默切换 VIP、fixture、后端、数据源、测试层级或 transport；
- 不清理、不重建与本任务无关的 fixture cache。

## 3. 已确认的仓库事实

- xverif 测试唯一公开入口是根级 catalog-driven pytest；fixture 和 suite 分别以
  `testinfra/fixtures.v1.yaml`、`testinfra/catalog.v1.yaml` 为事实源；
- 普通 gate 只消费缓存，显式 `--xverif-prepare` 才能构建 fixture；
- 真实 VCS、VIP、FSDB/NPI 动作必须在 host 环境执行，并显式设置
  `XVERIF_TEST_EXECUTION_ENV=host`；
- XAMBA 对外提供 `filelists/apb5.f` 与 `filelists/axi4.f`，签核基线为
  VCS X-2025.06-SP1 和 UVM 1.2；
- XAMBA 当前工作树干净；xverif 当前存在与本任务无关的 xwiki/AGENTS 未提交改动，
  本任务提交必须逐次验证 staged 路径严格等于当前阶段白名单。

## 4. 集成设计

### 4.1 外部仓库合同

新增 fixture 使用显式环境变量 `XAMBA_UVM_VIP_ROOT`。Makefile 在编译前检查：

1. 变量非空且目录存在；
2. 对应 `filelists/apb5.f` 或 `filelists/axi4.f` 存在；
3. 从 XAMBA 仓库根目录解析 filelist，避免相对路径被 fixture 工作目录误解；
4. 只通过 `-f <XAMBA_UVM_VIP_ROOT>/filelists/<protocol>.f` 引入 VIP；
5. fixture 自有 top/package/sequence 文件仍由 fixture Makefile显式追加。

fixture registry 把 `XAMBA_UVM_VIP_ROOT` 纳入 fingerprint 环境合同，使不同 VIP checkout
或路径不会误用不兼容缓存。若现有 FixtureStore 不能表达外部 filelist 内容指纹，只允许先在
fixture 自有输入中加入可审计的版本/commit manifest；是否扩展 FixtureStore 属于测试基础设施代码修改，
需要先更新本计划，不得现场 fallback。

### 4.2 APB fixture

APB fixture 使用 XAMBA 公共 APB5 interface、requester/completer endpoint 和 operation API，覆盖：

- 固定数量的 write/read；
- setup/access、wait-state、back-to-back transfer；
- byte strobe 与一笔 error response（以 XAMBA 已公开 capability 为准）；
- 固定 seed、UVM 零 error/fatal、稳定 completion 摘要；
- FSDB 和 daidir 产物。

对应 pytest 至少验证 session/config、`apb.query`、`apb.statistics`、
`apb.transaction.cursor`、`apb.transfer_window` 的计数、方向、地址、数据、错误和时间顺序。

### 4.3 AXI fixture

AXI fixture 使用 XAMBA 公共 AXI4 interface、manager/subordinate endpoint、operation 和 reply API，覆盖：

- 多 ID write/read；
- INCR burst、WSTRB、AW/W 接受顺序变化；
- 固定且可复现的 response delay/outstanding；
- pin-handshake JSONL oracle、UVM 零 error/fatal、稳定 scoreboard 摘要；
- FSDB 和 daidir 产物。

对应 pytest 至少验证 xdebug canonical transaction 数量和关键字段，并复用正式 waveform
验证入口覆盖 query/analysis/pair/timeline/outlier/cursor 等与该 fixture 适配的公开 action。

### 4.4 与 SVT 基线的共存

新 fixture/suite 使用独立 ID、目录、manifest 和缓存 generation。原有 SVT ID、目录、catalog
membership、fixture consumer 和缓存不变。迁移效果通过并行可运行证明，不以删除旧版作为完成条件。

## 5. 分阶段实施与提交

### 阶段 P0：计划冻结

- 新增本计划书；
- 确认两个仓库状态、正式测试入口、XAMBA filelist 与公开 API；
- 以仅包含本文件的详细中文 commit 冻结计划。

退出条件：`git diff --cached --name-only` 精确等于本计划书，文档引用路径存在。

### 阶段 P1：APB fixture 与测试

- 新增 APB XAMBA fixture、manifest、README 和对应 pytest；
- 新增 fixture/catalog 登记及必要的 testinfra 静态断言；
- 先执行静态门禁，再在 host 环境显式 prepare；
- 同一 prepare 再执行一次，第二次必须命中缓存；
- 执行 APB nightly focused suite。

退出条件：APB fixture 构建、probe、缓存复用和 xdebug 语义断言全部通过。

### 阶段 P2：AXI fixture 与测试

- 新增 AXI XAMBA fixture、manifest、README、handshake oracle 和对应 pytest；
- 新增 fixture/catalog 登记及必要的 testinfra 静态断言；
- 先执行静态门禁，再在 host 环境显式 prepare；
- 同一 prepare 再执行一次，第二次必须命中缓存；
- 执行 AXI nightly focused suite。

退出条件：AXI fixture 构建、probe、缓存复用和 xdebug 语义断言全部通过。

### 阶段 P3：VIP 优化建议

- 只依据 XAMBA README、`doc/api/`、filelist、公开 testbench 和既有 audit 合同；
- 在 XAMBA 仓库新增优化建议文档，按优先级描述问题、证据、建议和验收方式；
- 不修改 VIP 实现，不引入商业 VIP 内部信息。

退出条件：XAMBA 工作树只新增该文档，文档内路径和命令可核对。

### 阶段 P4：总验收与进度收口

- 更新本计划书状态和每阶段证据；
- 复跑静态合同和两个 focused suite（若 fixture fingerprint 未变化必须消费缓存）；
- 检查两个仓库最终 diff 和 commit 边界；
- 不推送远端，除非用户另行明确要求。

退出条件：第 6 节门禁全绿，且改动范围未越界。

## 6. 验收门禁

以下命令以仓库当前 catalog/README 为准；实现时先用 `--xverif-plan` 再执行 focused suite。

### 6.1 静态和 catalog 合同

```bash
.conda-xverif/bin/pytest --xverif-gate fast --xverif-suite testinfra.unit
.conda-xverif/bin/pytest --xverif-gate nightly --xverif-plan
```

验收点：fixture/schema/catalog 可加载、ID 唯一、两个新 suite 属于 nightly、现有 SVT suite 仍存在。

### 6.2 XAMBA 输入审计

```bash
cd <xamba-vip-repo>
doc/clean_room/verify_export.sh
make audit-all
```

`make audit-all` 是否需要全量重跑由实际改动范围决定；文档-only 阶段至少执行文档路径、链接和
命令核对。不得因耗时自行换成较低层级门禁。

### 6.3 Fixture prepare 与缓存复用

```bash
XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-prepare xdebug.apb_xamba_vip

XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-prepare xdebug.axi_xamba_vip
```

每条命令连续执行两次；第一次允许新建对应 generation，第二次必须为 cache hit。只准备这两个
新增 fixture，不使用 `all-generated`。

### 6.4 Focused runtime suite

```bash
XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-gate nightly --xverif-suite xdebug.apb_xamba_vip

XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-gate nightly --xverif-suite xdebug.axi_xamba_vip
```

验收点：VCS/simv 返回成功、UVM error/fatal 为零、FSDB/daidir/log/oracle 完整，且 xdebug
协议查询与 fixture oracle 一致。

### 6.5 范围与 Git 门禁

- 每次提交前运行 `git status --short`；
- 显式暂存当前阶段文件，不使用 `git add .`；
- `git diff --cached --name-only` 必须精确等于当前阶段白名单；
- xverif 既有 xwiki/AGENTS 改动不得进入本任务提交；
- XAMBA 仓库最终只允许新增优化建议文档；
- 所有 commit 使用中文，正文写清动机、范围和已执行验证。

## 7. Goal 摘要与完成定义

计划提交完成后建立 goal，目标摘要如下：

> 在不删除或修改现有 SVT VIP 基线、不修改产品源码的前提下，为 xverif 新增直接消费
> XAMBA checked-in APB5/AXI4 filelist 的两套真实 fixture 和对应 nightly 测试，并在 XAMBA
> 仓库输出基于其公开合同的优化建议。只有静态 catalog 合同、两套 fixture 的 host 构建与 probe、
> 第二次 prepare cache hit、两个 focused runtime suite、UVM 零错误及 Git 范围检查全部通过，
> 才可判定完成；任何无法直接 filelist 集成的问题必须明确报告并先更新计划，禁止 fallback。

## 8. 进度记录

| 阶段 | 状态 | Commit | 验证证据 | 备注 |
| --- | --- | --- | --- | --- |
| P0 计划冻结 | 已完成 | `fabd2a2` | 仓库、catalog、fixture、XAMBA filelist/API 已只读盘点 | 提交仅含本计划书 |
| P1 APB | 已完成 | `45e85ba` | `testinfra.unit` 55 passed；prepare 通过且二次 0.0s cache hit；nightly focused 1 passed | 使用 `filelists/apb5.f` 和公开 `xam_i6_apb_reply_test`；以 `-debug_access+all` 启用 FSDB |
| P2 AXI | 已完成 | `f85b9ac` | `testinfra.unit` 56 passed；prepare 通过且二次 0.0s cache hit；nightly focused 1 passed | 使用 `filelists/axi4.f` 和公开 `xam_i4_axi_random_test`；64 笔 mixed operation 与 pin-handshake oracle 对齐 |
| P3 优化建议 | 已完成 | XAMBA `137edb8` | `verify_export.sh` 通过；`make audit-all` 的 layout/clean-room/trace/release 全通过 | 仅新增文档，未修改 VIP 实现与构建合同 |
| P4 总验收 | 已完成 | 本文档收口提交 | `testinfra.unit` 56 passed；新旧四套 nightly suite 共存；APB/AXI prepare 均 0.0s cache hit；两个 focused suite 均 1 passed | 旧 SVT fixture/test 零差异；未重建缓存，未推送远端 |

### 8.1 最终验收记录

- 静态合同：`testinfra.unit` 共 56 项全部通过；
- catalog 共存：nightly plan 同时选中 `xdebug.apb_vip`、`xdebug.axi_vip`、
  `xdebug.apb_xamba_vip` 和 `xdebug.axi_xamba_vip`；
- fixture 缓存：APB 和 AXI 最终 prepare 均在 0.0s 内命中已有 generation，未重新调用 VCS；
- 真实 runtime：APB focused suite 1 passed，AXI focused suite 1 passed；
- XAMBA 审计：`XAM_LAYOUT_PASS`、clean-room audit、`XAM_TRACE_PASS`、
  `XAM_RELEASE_PASS` 全部通过；
- 范围：原 SVT APB/AXI fixture 目录和对应 pytest 相对 P0 冻结点零差异；
  xverif 中既有 xwiki/AGENTS 未提交改动未被纳入本任务提交；
- 交付：两个仓库均仅本地提交，未执行远端推送。
