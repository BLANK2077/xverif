# xdebug 公共 action guide 实施计划

## 目标与验收标准

将 `xverif_tools` 当前在 MCP Python 层生成的精简 action guide 下沉到 canonical
xdebug `actions` runtime，使原生 CLI、MCP 和 SDK-free LSF 使用同一份 guide。

验收标准：

- `actions.args.output.view="guide"` 是公开且 schema-valid 的 opt-in 视图。
- 既有 compact 默认输出和 `verbose=true` descriptor 输出保持兼容。
- guide 覆盖全部 action，每行只含 `action: description_en`，不含 status 或 `use_when`。
- 完整 guide 不超过 10,000 UTF-8 字节；超限明确失败，不截断、不 fallback。
- MCP `xverif_tools` 原样返回 native guide；SDK-free 透明转发同一 native envelope。
- schema、examples、runtime、MCP、SDK-free、docs 和 skills 同步并通过正式门禁。

## 实施阶段

### 阶段一：canonical action 合同与 runtime

- 在 request schema 生成源加入 `output.view="guide"`，并与 `output.verbose` 互斥。
- 为 compact/verbose/guide 建立明确 response variant；guide response 发布字节数、上限、
  filter 和单一 `data.guide`，不重复 descriptors/modes。
- 在 action catalog runtime 生成公共 guide，先应用现有 filter，再按 action 名排序输出。
- guide 超过 10,000 UTF-8 字节时返回 `ACTION_GUIDE_TOO_LARGE`。
- XOUT guide 仍使用标准 `@xdebug.actions.v1` framing。
- 更新 actions request/response examples、internal schema 和生成产物。

### 阶段二：MCP 与 SDK-free 共用

- MCP adapter 请求 native guide view；`xverif_tools` 只校验并返回 `data.guide`。
- 删除 MCP Python 侧 formatter 和重复的 catalog 描述字段检查。
- SDK-free wrapper 不新增参数或伪 action；通过现有 `xdebug_lsf` 原生 envelope 调用。
- 增加 native、stdio-loop、MCP、SDK-free fake-LSF 的请求与输出合同测试。

### 阶段三：文档、skill 与最终验证

- 同步 xdebug 维护文档、MCP README、`xverif` 和 `xverif-admin` skill。
- 运行 schema 生成一致性、runtime compatibility、schema/example validation。
- 构建 xdebug，并运行 focused fast/host regression suites。
- 最终执行 clean build、全仓 fast 和 host regression；只消费已有 fixture cache。
- 不修改用户现有 `AGENTS.md`，不自动准备或重建 fixture，不 fallback。

## 进度记录

- [x] 2026-08-25：完成现状探索和公开调用形态决策，选择 canonical `actions` guide 视图。
- [x] 阶段一：canonical action 合同与 runtime 已完成；真实 native guide 为 73 个
  action、5336 UTF-8 字节，静态门禁 119/119 通过。
- [x] 阶段二：MCP 改为 native guide passthrough，SDK-free 透明转发合同及测试已完成。
- [x] 阶段三：文档与 skill、生成检查、clean build、focused suites、全仓 fast
  和 host regression 全部完成。用户显式授权后仅准备
  `xdebug.stream_differential_tool` 新指纹 fixture；全仓 fast 为 642/642 passed，
  host regression 为 1296/1296 passed。
