# xwiki Wiki Spec

xwiki wiki 是芯片验证项目的持久 LLM 记忆。根目录来自 `XWIKI_DIR`。

## Required Structure

- `index.md`：根正向总索引，按描述对象目录列出入口页面，必须有 YAML frontmatter，默认 `object_type: dv`。
- `de/index.md` 和 `de/log.md`：设计实现、RTL、接口、微架构、协议行为、设计参数和数据路径的索引与局部日志。
- `dv/index.md` 和 `dv/log.md`：验证环境、sequence、checker、scoreboard、coverage、test、debug workflow 和仿真入口的索引与局部日志。
- `de_issue/index.md` 和 `de_issue/log.md`：设计/spec/RTL 风险与问题的总索引和局部日志。
- `de_issue/spec/index.md` 和 `de_issue/spec/log.md`：spec、协议定义、性能需求、文档合同问题。
- `de_issue/rtl/index.md` 和 `de_issue/rtl/log.md`：RTL 实现、微架构、时序、状态机、接口行为问题。
- `dv_issue/index.md` 和 `dv_issue/log.md`：testbench、UVM env、RM、checker、scoreboard、sequence、配置、脚本、仿真参数或 DV 假设问题。
- `archive/` 或 `deprecated/`：废弃页面存放区。
- `_index/backlinks.md`：可选反向索引，也必须有 YAML frontmatter。
- `_index/tags.md`：可选 tag 索引，也必须有 YAML frontmatter。
- `_index/prompt-profile.md`：首次项目 ingest 后必须存在的 prompt 生命周期状态；空骨架初始化时不创建。

根目录不要求 `log.md`，时间追溯写入对应对象目录的 `log.md`。wiki 允许多层子目录；除 `_index/`、`archive/`、`deprecated/` 以外，任何包含 Markdown 页面或子目录的目录都必须同时包含 `index.md` 和 `log.md`。例如 `de/interfaces/axi/` 如果存在，则必须有 `de/interfaces/axi/index.md` 和 `de/interfaces/axi/log.md`。

推荐布局：

```text
$XWIKI_DIR/
├── index.md
├── de/
│   ├── index.md
│   └── log.md
├── dv/
│   ├── index.md
│   └── log.md
├── de_issue/
│   ├── index.md
│   ├── log.md
│   ├── spec/
│   │   ├── index.md
│   │   └── log.md
│   └── rtl/
│       ├── index.md
│       └── log.md
├── dv_issue/
│   ├── index.md
│   └── log.md
└── _index/
    ├── backlinks.md
    ├── tags.md
    └── prompt-profile.md
```

可用 `scripts/init_xwiki.py` 初始化该骨架：

```bash
python scripts/init_xwiki.py --wiki-dir "$XWIKI_DIR" --validate
```

脚本行为：

- 默认只创建缺失的目录和 scaffold Markdown，保留已有文件。
- `--dry-run` 只输出计划，不写文件。
- `--force` 覆盖脚本管理的 `index.md`、`log.md`、`_index/backlinks.md`、`_index/tags.md`。
- `--root` 用于解析相对 `--wiki-dir`。
- `--validate` 在写入后运行 `validate_xwiki.py`。

空骨架初始化不创建 `_index/prompt-profile.md`。agent 在首次项目 ingest 读取当前验证层次的全部 topic prompt 后创建该文件；后续增量更新用它定位目标 topic prompt。

## Prompt Profile

`_index/prompt-profile.md` 是首次项目 ingest 生成的持久状态，不是 topic prompt 正文的副本。它必须包含普通 Markdown frontmatter 的四个必填字段，并在 frontmatter 或正文中记录：

- `verification_level`：`bt`、`it`、`st` 或 `soc`。
- `initialized_at`：首次读取当前层次全部 prompt 的日期。
- `needs_refresh`：是否需要全量刷新。
- `prompt_files`：首次 ingest 或最近一次全量刷新实际读取的 prompt 文件集合。
- `topic_prompt_map`：topic 名称到一个或多个 prompt 文件的映射。

推荐格式：

```yaml
---
type: Prompt Profile
title: xwiki Prompt Profile
description: Prompt loading state for this verification-project wiki.
object_type: dv
verification_level: bt
initialized_at: 2026-07-23
needs_refresh: false
prompt_files:
  - references/prompts/bt/prompts/design_overview.md
  - references/prompts/bt/prompts/interfaces.md
topic_prompt_map:
  design_overview:
    - references/prompts/bt/prompts/design_overview.md
  interfaces:
    - references/prompts/bt/prompts/interfaces.md
---
```

prompt 文件路径使用相对于 xwiki skill 根目录的逻辑路径，不写本机绝对路径，也不把它们写成 wiki Markdown 链接。profile 应从根 `index.md` 的维护信息区域可达；创建或更新 profile 时在 `dv/log.md` 记录操作。

prompt 加载规则：

- 普通查询不读取 topic prompt。
- 增量 concept 更新先读取 profile，只读取目标 topic 映射到的 prompt。
- issue、index 和 log 更新不读取 topic prompt。
- profile 缺失、验证层次变化或用户明确要求全量重建/刷新时，重新读取当前层次全部 prompt 并重建 profile。

## Markdown Frontmatter

所有 Markdown 文件都必须以 YAML frontmatter 开头：

```yaml
---
type: Verification Topic
title: Block Interfaces
description: One-sentence summary used by index and agents.
object_type: de
tags: [interface, dut]
source_refs:
  - rtl/top.sv:10-80
updated_at: 2026-06-29
---
```

必填字段：

- `type`
- `title`
- `description`
- `object_type`

`object_type` 只能使用：

- `de`：设计实现、RTL、接口、微架构、协议行为、设计参数和数据路径。
- `dv`：验证环境、sequence、checker、scoreboard、coverage、test、debug workflow 和仿真入口。
- `de_issue`：持续记录设计、RTL、spec、协议定义、性能需求或微架构侧问题和风险。
- `dv_issue`：持续记录验证环境、RM、checker、scoreboard、sequence、testbench、脚本、配置或 DV 假设侧问题和风险。

推荐字段：

- `tags`
- `source_refs`
- `updated_at`
- `confidence`

## Links

- 使用相对 Markdown 链接。
- 禁止 `file://`。
- 禁止本机绝对路径链接，例如用户主目录或系统临时目录下的路径。
- 新页面必须从 `index.md` 或相关 topic 页面可达。
- 修改、移动、废弃页面后必须维护入链和出链。

## Log

各目录 `log.md` 的二级标题必须使用：

- `## YYYY-MM-DD`
- `## [YYYY-MM-DD] ingest | Title`

条目应说明 action、来源、更新页面、unknowns。

更新页面时必须追加最接近该页面的目录级 `log.md`。跨 `de`、`dv`、`de_issue`、`dv_issue` 多类对象的 ingest/update，应分别追加各相关目录的 `log.md`，不要只写根级日志。

## Deprecated Pages

不允许硬删除页面。废弃页面应移动到 `archive/` 或 `deprecated/`，并在 frontmatter 中包含：

```yaml
deprecated: true
deprecated_reason: Replaced by wiki/interfaces/apb.md
```
