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
- 阶段 1：计划已落盘，待提交并建立 goal。
- 阶段 2：待实现。
- 阶段 3：待验收。
