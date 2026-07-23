# xwiki LLM Wiki Compile Process

xwiki 要求 AI 严格执行 LLM Wiki 的编译过程。

## Layers

- Raw sources：源码、README、spec、test、用户说明，以及当次 debug 中观察到的 wave/debug 现象。它们是事实来源，不被 xwiki 改写。
- Wiki：Markdown 编译产物。它保存稳定概念、验证结论、接口关系、debug 入口、未确认项和 evidence。
- Schema：由 xwiki skill 规定，包括 frontmatter、index/log、链接、废弃流程和证据规则。

具体仿真产物不能作为 wiki 的长期 evidence 或 citation，包括单次 run 的 FSDB/VCD、simv 产物、临时日志、coverage 临时目录、scratch 报告和 `<repo>/tmp` 文件。它们只允许作为当次 debug 的 observation；写入 wiki 时必须转化为稳定结论，并引用可追踪的 spec、RTL、test、脚本、README 或已提交文档。

## Ingest Or Update

先判断本次操作属于哪种生命周期：

- **空骨架初始化**：只创建目录和 scaffold，不读取 topic prompt，不要求确定验证层次。
- **首次项目 ingest**：读取当前验证层次的全部 topic prompt，并创建 `_index/prompt-profile.md`。
- **增量 concept 更新**：只读取 prompt profile 映射到目标 topic 的 prompt。
- **issue/index/log 更新**：不读取 topic prompt。
- **全量刷新**：仅在 prompt profile 缺失、验证层次变化或用户明确要求全量重建/刷新时读取当前层次全部 prompt，并重建 profile。

获得写回授权后的首次项目 ingest、增量 concept/issue/index/log 更新或全量刷新必须完成：

1. 读取 `index.md` 和相关旧页面。
2. 第一次建立项目记忆时，确认用户已提供 spec 路径和 RTL 路径；缺失时必须询问。仅创建空骨架时不要求提供。
3. 阅读 raw source。
4. 按生命周期加载 prompt：
   - 首次项目 ingest 或全量刷新：确定验证层次 `bt/it/st/soc`；如果无法确定，必须询问用户。读取 `references/prompts/<level>/prompts/*.md` 下全部 prompt 文件，并结合 `references/prompt-output-requirements.md` 组织总结。
   - 增量 concept 更新：读取 `_index/prompt-profile.md`，确认验证层次，只读取目标 topic 映射到的一个或多个 prompt，并结合 `references/prompt-output-requirements.md` 组织总结。
   - issue、index 或 log 更新：不读取 topic prompt。
5. 抽取稳定事实、验证结论、接口关系、debug 入口、unknowns。
6. 按 object_type 选择目录：设计事实进入 `de/`，验证事实进入 `dv/`，设计/spec/RTL 问题进入 `de_issue/`，DV 问题进入 `dv_issue/`。`de_issue` 下必须继续区分 `spec/` 或 `rtl/`。
7. 优先更新已有 concept；只有没有合适页面时才新增。
8. 处理 contradiction：新材料推翻旧结论时，更新旧页面并记录 resolution。
9. 更新根 `index.md`、相关目录及沿途子目录的 `index.md`、出链、入链、可选 backlinks/tags。首次项目 ingest 或全量刷新还必须创建或更新 `_index/prompt-profile.md`，记录验证层次、初始化时间、已读取的 prompt 文件集合、topic 到 prompt 文件的映射和是否需要刷新，但不复制 prompt 正文。
10. 追加最接近更新页面的目录级 `log.md`；跨多个描述对象目录时分别追加各目录日志。
11. 如果创建新子目录，必须同时创建该目录的 `index.md` 和 `log.md`。
12. 运行 `validate_xwiki.py`。
13. 向用户汇报来源、更新页面、验证层次、实际读取的 prompt 集合、主要使用的 prompt、剩余 unknowns 和校验结果；本次没有读取 prompt 时省略 prompt 集合。

## Case Fail Debug

获得写回授权后，debug 完 case fail 时更新 xwiki wiki。根因主题只能归入以下三类之一：

- `env_bug`：写入 `dv_issue/`，描述 testbench、UVM env、sequence、checker、scoreboard、配置、脚本、仿真参数或环境依赖导致的问题。
- `rtl_bug`：写入 `de_issue/rtl/`，描述 DUT/RTL 实现、时序、状态机、接口行为、reset/clock、backpressure、ordering 等设计实现问题。
- `spec_bug`：写入 `de_issue/spec/`，描述 spec 不清、spec 与 RTL/DV 期望冲突、需求缺失或文档定义错误。

如果根因未完全确认，选择最可能的候选主题并标记为未确认，列出下一步证据需求。不要把临时仿真产物路径写成长期 citation。

## Query

回答问题时先查询 wiki；普通查询不读取 topic prompt。wiki 不足时查询 raw source；只有已获得写回授权时，才按上述生命周期将有价值的新知识编译回 wiki。不要让已获授权写回的重要结论只留在 chat history。
