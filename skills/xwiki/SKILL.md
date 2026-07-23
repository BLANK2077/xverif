---
name: xwiki
description: >
  当 AI agent 需要在芯片验证任务中复用持续记忆时使用：查询或维护由
  XWIKI_DIR 指向的验证项目 LLM wiki，了解验证环境、DUT 功能、
  接口、testbench、sequence、checker、coverage、workflow、debug 入口、
  BT/IT/ST/SoC 项目上下文，并在用户明确要求、项目 AGENTS.md 授权或任务明确
  包含知识沉淀时把稳定发现编译回 wiki，避免每次 session 从 0 启动。
---

# xwiki 持续记忆 Skill

xwiki 用来维护芯片验证项目的 LLM wiki。它不是 CLI/MCP 工具，也不读取旧版运行时状态目录；它规定 AI 如何查询、增删改查和校验一个持久 Markdown wiki。

## 必须先做

1. 读取环境变量 `XWIKI_DIR`，它是当前 session 的 xwiki wiki 根目录。
2. 如果 `XWIKI_DIR` 未定义或为空，必须询问用户提供路径；不要 fallback 到 `doc/`、当前目录或其他猜测路径。
3. 第一次为项目 ingest 持续记忆时，如果用户没有告知 spec 路径或 RTL 路径，必须询问用户；不要自己猜测 spec/RTL 根目录。仅创建空 wiki 骨架不要求提供这些路径。
4. 需要校验格式时运行：

```bash
python <xverif-root>/skills/xwiki/scripts/validate_xwiki.py
```
5. 查询 wiki 可隐式触发；创建、修改、废弃或写回页面必须有用户明确要求、项目规则授权或任务范围授权。未授权时只在最终结果中列出建议写回的稳定结论。
6. 初始化空 wiki 目录时优先运行：

```bash
python <xverif-root>/skills/xwiki/scripts/init_xwiki.py --wiki-dir "$XWIKI_DIR" --validate
```

## 何时使用

- 需要了解验证环境、DUT 功能、接口、reset/clock、memory map、interrupt、testbench、agent、sequence、checker、scoreboard、coverage、workflow、debug 入口。
- 需要把源码、README、spec、test、wave/debug 报告或用户说明编译进持久项目记忆。
- 需要查询、创建、修改或废弃验证项目 wiki 页面。
- 需要检查 wiki 格式是否能被后续 agent 可靠读取。
- 获得写回授权且 debug 完一个 case fail 后，把稳定结论记录到 `de_issue` 或 `dv_issue` 描述对象中。

## 查询顺序

1. 从 `$XWIKI_DIR/index.md` 开始，找候选主题和入口页面。
2. 按描述对象进入 `$XWIKI_DIR/de/`、`dv/`、`de_issue/` 或 `dv_issue/`，先读该目录及沿途子目录的 `index.md` 和 `log.md`。
3. 读取相关 concept 页面，看 frontmatter、正文、出链、evidence 和 citations。
4. 如果存在 `_index/backlinks.md` 或 `_index/tags.md`，用它们做反向或 tag 索引。
5. 如果仍找不到，只在 `$XWIKI_DIR` 内用 `rg` 搜索 Markdown。
6. 搜索命中后必须回到页面级证据；不要只引用 grep 片段作答。
7. wiki 信息不足时再读 raw source；只有已获得写回授权时才把稳定发现编译回 wiki，未授权时在最终结果列出建议写回的页面和结论。

详细查询和 CRUD 规则见 [references/wiki-crud.md](references/wiki-crud.md)。

## 编译要求

严格执行 LLM Wiki 编译过程：raw sources 是事实来源，wiki 是编译产物，schema 由本 skill 规定。每次 ingest/update 必须读旧页面、抽取新事实、合并或新增 concept、更新 index/反向索引、追加 log、运行校验并汇报 unknowns。

### 验证层次 prompt 生命周期

prompt 的加载范围由当前操作阶段决定，不得在每次 xwiki 查询或写回时无条件读取同层全部 prompt：

1. **空骨架初始化**：只运行 `init_xwiki.py` 创建目录和 scaffold，不读取 topic prompt，也不要求确定验证层次。
2. **首次项目 ingest**：先确定当前验证层次是 `bt`、`it`、`st` 还是 `soc`。验证层次可来自用户说明、wiki index、已有 concept、仓库目录或验证环境命名；如果无法确定，必须询问用户，不得猜测。确定后读取该层次 `references/prompts/<level>/prompts/*.md` 下的全部 prompt，并创建 `$XWIKI_DIR/_index/prompt-profile.md`，持久记录验证层次、初始化时间、已读取的 prompt 文件集合、topic 到 prompt 文件的映射和是否需要刷新。profile 不复制 prompt 正文。
3. **普通查询**：不读取任何 topic prompt；只按查询顺序读取 wiki，必要时再读 raw source。
4. **增量 concept 更新**：先读取 `prompt-profile.md`，只读取目标 topic 对应的一个或多个 prompt，并结合 [references/prompt-output-requirements.md](references/prompt-output-requirements.md) 生成或更新页面。不得为了更新单个 topic 重新读取同层全部 prompt。
5. **issue、index 或 log 更新**：不读取 topic prompt；按 wiki schema、CRUD 和证据规则直接维护。
6. **全量刷新**：只有 prompt profile 缺失、验证层次发生变化或用户明确要求全量重建/刷新时，才重新读取当前层次的全部 prompt 并重建 profile。

首次 ingest、增量 concept 更新或全量刷新完成后，汇报验证层次、实际读取的 prompt 集合和主要使用的 prompt；没有读取 prompt 时不需要汇报 prompt 集合。

### Wiki 描述对象分类硬规则

所有 wiki Markdown 文件的 frontmatter 必须包含 `object_type`，且只能使用 `de`、`dv`、`de_issue`、`dv_issue` 四个值之一。该字段用于区分页面描述对象，不等同于页面标题、tag 或验证层次。

- `de`：描述设计实现、RTL、接口、微架构、协议行为、设计参数和数据路径。
- `dv`：描述验证环境、sequence、checker、scoreboard、coverage、test、debug workflow 和仿真入口。
- `de_issue`：持续记录设计、RTL、spec、协议定义、性能需求或微架构侧问题和风险。
- `dv_issue`：持续记录验证环境、RM、checker、scoreboard、sequence、testbench、脚本、配置或 DV 假设侧问题和风险。

根 `index.md` 默认使用 `object_type: dv`；每个目录的 `index.md` 使用该目录对应的 `object_type`，`de_issue/spec/index.md` 和 `de_issue/rtl/index.md` 使用 `object_type: de_issue`。`log.md` 默认使用所在目录对应的 issue 类型：`de/` 下使用 `de_issue`，`dv/` 下使用 `dv_issue`，`de_issue/` 及其子目录使用 `de_issue`，`dv_issue/` 下使用 `dv_issue`。获得写回授权后，debug 完 case fail 时更新 `de_issue` 或 `dv_issue` 页面；根因未完全确认时，也要作为候选 issue 记录 unknown 和下一步证据。

禁止把具体仿真产物作为 wiki evidence 或 citation，例如单次 run 的 FSDB/VCD、simv 产物、临时日志、coverage 临时目录、scratch 报告、`<repo>/tmp` 文件。这些不会进入 git，只能作为当次 debug 的 raw observation；写入 wiki 时必须编译成稳定结论，并引用可追踪的 spec、RTL、test、脚本、README 或已提交文档。

获得写回授权后，case fail debug 结束时写回 wiki：

- 设计、RTL、spec、协议定义、性能需求或微架构侧问题写入 `de_issue`。
- testbench、UVM env、RM、checker、scoreboard、sequence、配置、脚本、仿真参数或 DV 假设问题写入 `dv_issue`。
- 如果根因未完全确认，仍要更新对应候选 issue 页面，把结论标为未确认，并记录下一步需要的证据。

根因主题与存储对象固定映射：`env_bug` 写入 `dv_issue/`，`rtl_bug` 写入 `de_issue/rtl/`，`spec_bug` 写入 `de_issue/spec/`。主题名用于问题分类，frontmatter 的 `object_type` 仍只能使用 `dv_issue` 或 `de_issue`，不能写成 `env_bug`、`rtl_bug`、`spec_bug`。

详细流程见 [references/compile-process.md](references/compile-process.md)。

## Wiki 格式

wiki 根目录必须包含 `index.md`、`de/`、`dv/`、`de_issue/`、`dv_issue/`。根目录不再要求 `log.md`；各描述对象目录必须包含自己的 `index.md` 和 `log.md`。`de_issue/` 下必须再区分 `spec/` 与 `rtl/`，且二者也必须各自包含 `index.md` 和 `log.md`。

wiki 允许多层子目录，但 `$XWIKI_DIR` 下除 `_index/`、`archive/`、`deprecated/` 以外，任何包含 Markdown 页面或子目录的目录都必须同时包含 `index.md` 和 `log.md`，形成可局部查询、可局部追溯的分层记忆。所有 Markdown 文件都必须有 YAML frontmatter，至少包含 `type`、`title`、`description`、`object_type`。`object_type` 只能是 `de`、`dv`、`de_issue`、`dv_issue`。链接必须相对可解析，禁止本机绝对路径和 `file://`。

创建空 wiki 骨架时使用 `scripts/init_xwiki.py`，不要手写目录骨架。脚本默认保留已有文件；需要重建脚本管理的 index/log/_index 文件时显式传 `--force`；只查看计划时传 `--dry-run`。

完整格式见 [references/wiki-spec.md](references/wiki-spec.md)。

## 验证 topic prompts

BT/IT/ST/SoC prompt 保存在 [references/prompts](references/prompts)。首次项目 ingest 和全量刷新读取对应层次 `prompts/` 目录下的全部 Markdown 文件；后续增量 concept 更新只读取 `prompt-profile.md` 映射到目标 topic 的 prompt。普通查询及 issue、index、log 更新不读取 topic prompt。
