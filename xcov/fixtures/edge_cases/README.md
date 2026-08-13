# xcov edge-case fixture

该 fixture 由同一份真实 SystemVerilog 生成两个独立 VDB：

- `VARIANT=edge`：任意顶层名、module-only detail、generate `0/N`、Condition Number-Term、
  单 metric `--` 与空 FSM。
- `VARIANT=zero`：额外启用无 coverable object 的 functional coverage。

RTL 同时覆盖纯例化父层、coverage-off 父层、generate 子模块、packed/unpacked 4x4 数组、
generate-for 赋值、连续/过程赋值和四层复杂嵌套三目。正式数据库只通过根级 FixtureStore
显式 prepare 生成；测试本身不运行 VCS。
