# MCP 环境配置清理计划与验收记录

## 目标与决策

移除 MCP 工具组、状态修改和文件写入权限开关，所有工具始终注册；删除 MCP artifact root 限制。修复无效 SDK-free 通用超时及代码与文档差异。

删除 `XVERIF_MCP_ENABLE_COMMON/DEBUG/COV/BIT/ENTRY/LOC/SVA` 七个变量、`XVERIF_MCP_ENABLE_MUTATION`、`XVERIF_MCP_ENABLE_ARTIFACT_WRITE`、`XVERIF_MCP_ARTIFACT_ROOT`、`XVERIF_LSF_CLI_TIMEOUT_SEC` 和 `XVERIF_LOOP_TIMEOUT_SEC`。旧变量完全停止读取，不提供别名、警告或启动拒绝；迁移时删除旧配置。

保留 batch 输入 16 MiB、请求 10000 条、输出 64 MiB 上限及其环境配置，保留有效的 backend、日志、阶段超时、LSF 和下游工具路径合同。不推送，不创建 PR，不重建 fixture。

## 实施阶段

1. 记录计划及工作树基线，提交计划；随后建立 goal。
2. 实现、测试、README、skill 同步后提交：
   - 无条件注册所有工具；每个工具始终公开 `xverif_output_path` 和 `xverif_output_append`。
   - 删除动态 mutation/artifact 授权、capability 私有实现及禁用错误；保留 managed session guard。
   - 目录 group/mutation/artifact_write 仅为描述性元数据；tool help 的 policy 仅保留 batch_limits。
   - MCP 自身输出的相对路径基于进程 cwd，绝对路径直接使用；不自动创建父目录；通用输出保留覆盖/追加及明确失败。
   - batch 保留输入冻结、上限、同 inode 检查、父目录检查、staging 和原子 no-clobber 发布。
   - 下游 action 参数原样传递，停止改写相对输出路径及注入 allow_absolute_path；保留 xcov 原生导出限制。
   - 删除 SDK-free 无效通用超时映射和存储；MCP one-shot 超时独立读取，默认 360 秒。保留的 SDK-free 超时严格校验有限正数且无首尾空白。
   - README 修正过期的 120 秒说明、环境继承绝对化表述和全量启动快照表述；补充 branch mask hint、配置分域与迁移说明。
   - 同步 xverif-admin skill references，并核对主文件、agents/openai.yaml、xverif skill 及 xdebug 维护材料。
3. 完成验收与 skill 安装，提交最终验收记录。

## 验证与验收标准

- 旧 MCP 配置缺失、为 0 或非法值时工具列表及 schema 不变，状态修改能到达后端；不再返回旧权限错误。
- 通用输出无需 root，支持相对/绝对路径、覆盖/追加；无效路径、父目录缺失、写入及序列化失败均明确失败。
- batch 保留三项上限、同 inode（含 symlink/hardlink）、不覆盖已有目标及原子发布约束。
- 下游输出参数原样传递，xcov 原生相对导出和显式绝对路径许可继续生效。
- SDK-free 废弃超时不读取；阶段超时分别生效并严格校验；MCP one-shot 保持 360 秒。
- 工具帮助 policy 只含 batch_limits；原生 schema/action 业务合同不改。
- 正式 pytest 入口使用 `.conda-xverif/bin/pytest`，每个 focused suite 前核对当前 gate plan。
- regression：xverif_mcp.unit、xverif_mcp.process、xverif_mcp.runtime_package、xverif_mcp.sdk_free_lsf_real_data、xverif_mcp.action_smoke、xdebug.mcp_direct、xdebug.mcp_fake_lsf、skills.xverif、skills.xverif_admin、skills.public_docs。
- nightly：xcov.mcp_integration、xverif_mcp.real_fullchain。
- MCP/真实数据库动作使用 host 并显式设置 XVERIF_TEST_EXECUTION_ENV=host；缓存缺失记录阻塞，不自动 prepare/fallback。
- 删除变量仅允许出现在迁移文档、此计划和删除行为测试；skill 源提交并通过 suite 后用 Makefile 安装修改的 skill，再对 Codex/Claude 两份安装逐一 diff -qr。

## 工作树基线

开始时已有改动：AGENTS.md、README.md、README.zh-CN.md、doc/agents/xdebug/tests.md、skills/tests/test_xwiki_skill.py、skills/xwiki 下多个文件、testinfra/catalog.v1.yaml、xdebug/Makefile、xdebug/README.md、xdebug/src/waveform/axi/{axi_analyzer.h,axi_exporter.h}；未跟踪 doc/WAVE_MCP_XVERIF_REVIEW_2026-09-04.md、xdebug/tests/static/test_npi_toolchain_contract.py、xdebug/tools/check_npi_toolchain.py。

以上变动归用户所有，保留且不纳入本次提交。重叠 README 仅提交本次独立差异；每次提交核对完整 staged 白名单。

## 进度

- 计划阶段：已完成代码追踪、19 份 README 交叉检索、删除与兼容策略确认、regression/nightly gate plan 核对。
- 阶段 1：已提交计划 `5a5f452`，随后建立执行 goal。
- 阶段 2：实现、关联测试、README 和 xverif-admin references 已完成；正式矩阵合计 514 项全部通过，实现提交 `21dd95f`。
- 阶段 3：真实数据库验证、skill 安装及双端内容比对已完成，本记录作为最终验收提交。

## 实现与检查记录

- 生产 Python 中不再读取 10 个 MCP 权限/目录变量及 2 个 SDK-free 通用超时；只保留资源限制、有效超时和调度配置。
- 删除 action_capabilities.py；保留 managed native lifecycle guard、工具描述性元数据、batch 三项上限和原子 no-clobber 合同。
- MCP 工具帮助 policy 仅含 batch_limits；所有工具均公开通用输出参数。无效路径返回 OUTPUT_WRITE_FAILED，序列化失败不覆盖既有输出。
- xcov 原生参数原样转发，真实测试覆盖相对路径使用原生导出根目录、绝对路径无显式许可被拒绝、有许可成功。
- 已核对 skills/xverif-admin/SKILL.md 与 agents/openai.yaml：入口和路由说明仍适用，无需修改；更新三个 references。skills/xverif 主文件和相关输出说明无需修改，正式 suite 已覆盖。
- 旧变量残留仅在删除行为测试、当前迁移说明及历史计划中；两份历史计划新增已被本计划取代的声明，不重写历史证据。
- 原生 action/schema、fixture/catalog 和 C++ 源码均未修改；按已确认计划运行 focused 矩阵，不执行全仓 clean build 或 fixture prepare。

## 验证记录

| 检查 | 结果 | 证据目录 |
| --- | --- | --- |
| MCP unit 修复后重跑 | 245 passed | .xverif-test-results/20260907-104302-9r8zlq70 |
| SDK-free 真实数据、action smoke、xdebug direct/fake LSF | 9 passed | .xverif-test-results/20260907-104339-_0mcdv2_ |
| xcov MCP integration、真实 MCP stdio fullchain | 19 passed | .xverif-test-results/20260907-104429-3scj1n6z |
| 最终 unit/process/runtime package/skill/public docs 组合 | 486 passed | .xverif-test-results/20260907-104601-6kgk6ol_ |

所有上述进程与数据库检查均在 host 运行并显式设置 XVERIF_TEST_EXECUTION_ENV=host；缓存全部可用，没有 VCS fixture 重建或测试降级。

早期失败均已定位修正：
1. 新增 native batch 转发用例误带 session_id，按原生 requires:none 合同改为 one-shot 调用。
2. 新增 SDK-free timeout 测试泄漏内部环境变量；改用独立 os.environ 副本，并在 AGENTS.md 追加复盘。
3. 新增 coverage 拒绝用例误从顶层 error 取码；真实 xcov 失败保留 transport envelope，改为精确断言 json.error.code。

## 最终交付

- 正式验收共 514 项通过：组合门禁 486、真实 FSDB/VDB 与 direct/fake-LSF/SDK-free 9、coverage MCP 与 stdio 全链路 19；无未解决失败或环境阻塞。
- 2026-09-07 执行 make install-xverif-admin-skill，安装至 $HOME/.codex/skills/xverif-admin 和 $HOME/.claude/skills/xverif-admin。
- 两份安装分别执行 diff -qr，均 exit 0；按安装目标合同只排除 Python/test 缓存及安装时生成的 .xverif-skill-manifest。
- 旧 skill 可从两个用户配置目录下的 xverif-admin-skill.bak.20260907-104850 恢复。
- README.zh-CN.md、xdebug/README.md、AGENTS.md 的重叠修改按本次差异独立暂存；逆向消除本次修改后与进入任务时快照逐字节一致。其余用户修改留在工作树。
- 已删除的 action_capabilities.py 可从实现提交的父提交恢复；旧配置不再被读取，部署迁移及路径变化见 MCP README。
- 未推送远端，未创建 PR，未改 fixture/catalog/native schema，未重建 fixture。
