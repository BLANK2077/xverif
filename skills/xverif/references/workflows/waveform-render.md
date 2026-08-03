# 波形导出、渲染与多模态观察

用于宏观理解长窗口、多信号关系、burst、stall 分布和状态阶段：

1. 按 schema 生成 list JSON 并用 `list.load` 建立列表；只做一次性临时观察时可用
   `list.create` / `list.add`。
2. 用 `list.export` 导出 manifest 和逐信号数据。
3. 执行 `tools/xwaveform render --manifest <manifest>`，得到 JPG 与 stats JSON；精确 CLI 参数以 `tools/xwaveform --help` 为准。
4. 读取 stats JSON，并用多模态能力观察 JPG 的整体结构。
5. 把图片观察写成假设，再用 `event.find`、已加载 list 的
   `value.at(list="<name>", times=[...])`、`trace.active_driver` 或 `window.verify` 验证。

不要把大量原始 waveform rows 直接读入上下文，也不要把视觉判断当最终确定性证据。
