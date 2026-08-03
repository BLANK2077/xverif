# a3d8241 之前的 XOUT 架构证据

证据来自子 agent 建立的独立临时 clone：

- 路径：`/home/RD/ryan/work/tmp/xverif-pre-a3-architecture.phTN2g/repo`
- 提交：`53a955616257db17335dfb639a3bcbdbcafcb7c1`
- 状态：detached HEAD、工作树干净、未运行 EDA

该版本的 XOUT 采用“公共文本构建器＋handler 虚函数＋server 生成文本＋frontend 原样透传”的分层架构，而不是把 JSON 编码为 Pointer 文本。

## 公共文本构建器

`TextResponseBuilder` 提供 header、section、键值、行、表格、JSON 表格、warning、error 和 raw primitive；`sanitize_xout_key/value` 负责单行安全和长度限制；`json_to_xout_value` 负责 scalar、LogicValue 和 field map 的紧凑文本；最终文本无行尾空格且只有一个末尾换行。

## 基类与 handler override

`EngineActionHandler` 声明虚函数：

```cpp
virtual std::string render_xout(const Json& response) const;
```

基类 fallback 输出 action header、summary、递归 data、findings 和公共阻塞信息。需要领域布局的 action 由具体 handler override，不在中央 renderer 按 action 名分支。

## server 与 frontend 数据流

1. engine handler 产生最终 JSON data。
2. server 应用 value format 和 width summary 后调用该 handler 的 `render_xout`，把文本写入 `resp["text"]`。
3. dispatcher 只复制 engine text，不重新渲染。
4. frontend 对成功响应优先透传 `response["text"]`；仅错误或无 handler text 时使用 generic fallback。
5. native CLI 和 stdio loop 最终调用同一 frontend 输出入口；stdio loop 只选择 json/xout，不覆盖领域文本。

仓库中没有 `XOUT_BEGIN` 或 `XOUT_END`。

## 旧版 11 个特殊 renderer

| action | 领域布局 |
|---|---|
| `trace.load` | source-path 源码窗口与公共阻塞块 |
| `trace.driver` | source-path 源码窗口与公共阻塞块 |
| `trace.active_driver` | active-driver/source-path 布局 |
| `trace.active_driver_chain` | active chain/source-path 布局 |
| `trace.x` | X 根因源码窗口 |
| `apb.statistics` | APB 统计布局 |
| `axi.statistics` | AXI 统计布局 |
| `list.value_at` | signal/value 表 |
| `scope.roots` | 摘要、roots 表和 limitations |
| `value.at` | 旧单信号 before/middle/after 或单值布局 |
| `value.batch_at` | 批量 value/sample 表 |

trace renderer 共同使用 trace source-path formatter；APB/AXI statistics 共同使用 statistics formatter。

## 重建边界

- 恢复 builder、基类虚函数、server text 生成和 frontend 原样透传。
- 恢复仍存在 action 的旧 override 架构位置；旧 `trace.x` 按当前名称 `trace.x_origin` 重建。
- 不恢复已删除的 `list.value_at` 和 `value.batch_at`。
- `value.at` 内容采用后续统一多 selector、多 time 合同，最终只输出 header＋values 矩阵。
- APB/AXI/Stream query 的专用 override 来自后续独立产品需求，补入 handler 层。
- frontend generic renderer 只作为 fallback，不重新成为全 action 领域 renderer。
