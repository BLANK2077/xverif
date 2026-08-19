# SDK-free LSF 环境配置与远端继承实施计划

## 1. 目标

为 `xdebug_lsf` 和 `xcov_lsf` 增加共享 JSON 环境配置。两个入口默认检查
自身实际所在目录的 `xverif_lsf.env.json`，在启动 manager 前构造唯一的
effective environment，并确保该环境不仅在登录节点生效，还由 LSF 计算节点
上的 xdebug/xcov stdio-loop 确认继承。

新增 `xverif_lsf_env_capture`，把当前终端中与 xverif、EDA、license 和 LSF
相关的环境变量安全生成到入口同目录。配置、加载、LSF 提交和远端 ready
握手均 fail closed，不增加 direct/MCP fallback。

### 1.1 作用范围硬边界

本修改只作用于 SDK-free `xdebug_lsf`、`xcov_lsf`、它们自动启动的内部
manager，以及由该 manager 提交的 LSF job。MCP direct/LSF backend 不读取
该配置，不增加 `-env all`，不启用环境指纹校验，不改变 bsub argv、ready
合同、环境继承或 session 生命周期。共享底层代码只能增加默认关闭的能力，
且必须用差分测试证明 MCP 未启用该能力。

## 2. 固定公共合同

### 2.1 配置文件

默认路径：`<xdebug_lsf/xcov_lsf 实际入口目录>/xverif_lsf.env.json`。
`XVERIF_LSF_CLI_CONFIG=<path>` 可覆盖默认路径。文件不存在时保持当前继承
行为；存在但非法时立即失败。

```json
{
  "schema_version": "xverif-lsf-env.v1",
  "variables": {
    "VERDI_HOME": "/tools/verdi",
    "PATH": "/tools/lsf/bin:/usr/bin",
    "LD_LIBRARY_PATH": "/tools/verdi/share/NPI/lib/LINUX64",
    "SNPSLMD_LICENSE_FILE": "27000@license-server"
  }
}
```

- 顶层只允许 `schema_version` 和 `variables`。
- variables 的 key 必须是合法环境变量名，value 必须是 string。
- 拒绝重复 JSON key、NaN、未知字段、symlink、非当前 owner、非普通文件和
  group/world writable 文件；文件权限固定为 `0600`。
- 配置变量覆盖 inherited environment；wrapper 内部固定变量最后设置。
- stdout 不显示变量内容；结构化日志只发布路径、变量名和整体指纹。

### 2.2 捕获入口

新增 repo 与 wheel console entry：`xverif_lsf_env_capture`。

```bash
xverif_lsf_env_capture
xverif_lsf_env_capture --dry-run
xverif_lsf_env_capture --include SITE_VARIABLE
xverif_lsf_env_capture --output PATH
xverif_lsf_env_capture --force
```

默认捕获 `PATH`、`LD_LIBRARY_PATH`、`PYTHONPATH`、`VERDI_HOME`、`VCS_HOME`、
`LM_LICENSE_FILE`、`SNPSLMD_LICENSE_FILE` 以及稳定的 `XVERIF_*`、
`XDEBUG_*`、`XCOV_*`、`LSF_*`。排除 shell/作业临时状态，以及变量名包含
`TOKEN`、`PASSWORD`、`SECRET`、`COOKIE` 的值；额外变量只通过重复
`--include NAME` 加入。`--dry-run` 只显示变量名。

默认 no-clobber；`--force` 使用同目录 staging、fsync、chmod 0600 和原子
replace。默认配置文件加入 `.gitignore`。

## 3. LSF 环境继承硬合同

- SDK-free effective environment 在内部 manager 生命周期内冻结，显式传给 manager、bsub、
  bkill、xdebug log 和所有 stdio-loop/native 子进程。
- 仅 SDK-free LSF submission 显式添加 `bsub -env all`。自定义
  `XVERIF_LSF_BSUB` 若携带任何 `-env` 直接报配置错误，避免 `none` 或部分
  变量覆盖传播合同。
- 对配置中的变量按名称排序并使用长度分隔编码计算 SHA-256。登录节点保存
  expected fingerprint；计算节点 xdebug/xcov stdio-loop 对实际环境计算
  observed fingerprint，并在 ready envelope 发布。
- ready 缺少指纹或 observed 不等于 expected 时返回 `LSF_ENV_MISMATCH`，
  终止并清理 job，不进入 session open，不 fallback。
- manager ping 发布配置指纹。一致时复用；不一致且无 live/opening/unresolved
  session 时正常关闭旧 manager 后重启；存在活动或未解决 session 时返回
  `CONFIG_MISMATCH`，不杀 session、不混用环境。
- MCP launcher 不读取上述内部指纹变量；其传播开关保持关闭，stdio-loop
  ready 不要求环境指纹。

## 4. 分阶段提交

1. 文档：提交本计划和进度账本。
2. 配置加载：严格 JSON、安全文件、入口定位、effective environment 和指纹。
3. LSF 传播：显式 subprocess env、`-env all`、远端 ready 指纹和 manager
   配置一致性。
4. 捕获脚本：allowlist、敏感过滤、include/dry-run/force、原子发布及 wheel
   entry。
5. 测试：配置、权限、捕获、fake-LSF 环境篡改、manager mismatch、repo/wheel
   入口和现有真实缓存。
6. 文档与 skill：README、xdebug agent 协议、xverif-admin references 和安装
   diff 验收。

## 5. 测试与验收

- 无配置时 xdebug/xcov 行为不变；共享配置覆盖 inherited environment。
- fake bsub 断言 argv 含 `-env all`，并验证 submission env 到计算节点。
- MCP LSF argv 差分测试必须证明同一 open 请求仍使用修改前的 bsub 参数，
  不含 SDK-free `-env all`，且 MCP ready 不要求环境指纹。
- fake LSF 删除或修改任一受管变量时必须 `LSF_ENV_MISMATCH`，不得创建 session。
- 覆盖 JSON/XOUT、stdin/file、xdebug log、manager 复用/切换和 clean wheel。
- 覆盖损坏 JSON、重复 key、未知字段、非 string、symlink、owner、mode、
  no-clobber、force、特殊字符和敏感变量过滤。
- 使用现有 `xdebug.ai_complex_wave` 与 `xcov.comprehensive` cache 运行 host
  fake-LSF 真实数据 suite，并由真实 stdio-loop 完成环境指纹握手。
- 运行 `xverif_mcp.unit`、`xverif_mcp.process`、runtime package、相关
  xdebug/xcov contract 和 `skills.xverif_admin`。
- 禁止调用 `--xverif-prepare`；实施前后 fixture `current.json` 指针必须一致。

## 6. 进度账本

| 阶段 | 状态 | Commit | 验证/备注 |
| --- | --- | --- | --- |
| 计划书 | 已完成 | `be0259d`, `9f4baa5` | 已明确仅限 SDK-free；不纳入用户已有 `AGENTS.md` 改动 |
| Goal | 已完成 | - | 已建立实现与验收目标 |
| 配置加载 | 已完成 | `98b4959` | 严格 JSON、0600/owner/regular-file、覆盖语义与双指纹 |
| LSF 远端继承 | 已完成 | `98b4959` | 仅 SDK-free opt-in `-env all`；计算节点 pre-exec 指纹校验 |
| 捕获脚本 | 已完成 | `98b4959` | repo/wheel entry、allowlist、敏感过滤、no-clobber/force |
| 测试 | 已完成 | `98b4959` | unit 227、process 173、wheel 1、真实缓存 1、xcov unit 170 |
| 文档与 skill | 进行中 | 待填写 | README、协议与 skill 已同步；待安装 diff 验收 |
| 最终验收 | 进行中 | - | 未调用 fixture prepare；待记录缓存指针与最终 status |
