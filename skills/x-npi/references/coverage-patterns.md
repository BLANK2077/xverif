# Coverage：URG 读取，NPI 仅处理 exclusion

## 固定分工

coverage 工作必须先区分读取与修改：

| 工作 | 正式入口 | 是否加载 pynpi |
| --- | --- | --- |
| test list、scope hierarchy、code/assert/functional summary | URG fixed summary | 否 |
| code/assert/functional gap detail | 受 scope/metric 限定的 URG text detail | 否 |
| EL load、report-time set/remove、save、unload | Python NPI | 是 |
| 严格 CSV 校验/格式化 | `x_npi.exclusion_csv` | 否 |
| CSV → EL | CSV parser + exclusion-only NPI resolver/compiler | 是 |

Python NPI coverage wrapper 没有 bulk summary 或按任意 bin 名直达的稳定接口。读取一个大型 VDB
必须执行 `database.instance_handles -> instance metric -> child_handles` 的全树递归，functional
还要从 `testbench_metric_handle` 重新遍历；复杂度至少与所有 coverage handle 数量成正比，Python
wrapper 调用和 handle release 成本很高。更危险的是中间 aggregate 与 leaf bin 同时出现，直接
相加会重复计分并偏离 URG SCORE。

因此，**不要用 NPI 构造 coverage summary/export**。x-npi 中的 NPI coverage helper 已收缩为
exclude-only；需要读取时使用 `x_npi.urg` 或直接使用 xcov。NPI 必须遍历的缺陷只在用户明确
修改 exclusion 时承担。内建 resolver 对每个非空 kind 固定执行预检和应用两遍扫描，要求
零/一/多匹配 fail-closed，不长期缓存 handle，也不按 CSV 行重新遍历。

## 推荐 URG 命令

固定 summary 命令：

```bash
"$VCS_HOME/bin/urg" \
  -full64 \
  -dir <absolute-vdb> \
  -report <same-filesystem-staging-report> \
  -xml_verbose \
  -format text \
  -show summary
```

需要把已有 exclusion 应用于统计时，只追加：

```bash
-elfile <absolute-working.el>
```

`x_npi.urg.export_summary()` 严格解析 `$VCS_HOME/bin/urg`，不查询 `PATH`；目标 report 必须
不存在。helper 在目标父目录创建随机 staging，运行 URG、校验六件套并解析 typed XML，成功后
才发布目录；URG 失败不会切换 NPI、HTML 或其它 backend。

```python
from x_npi.urg import export_summary

summary = export_summary(
    "merged.vdb",
    "coverage-report",
    elfile="working.el",  # 可省略
)
rows = summary.rows(metrics=["line", "toggle", "assert", "functional"])
```

固定产物必须全部存在且非空：

```text
session.xml
tests.txt
dashboard.txt
modlist.txt
groups.txt
asserts.txt
```

其中 `session.xml` 必须按 XML `type` 分开解析：code coverage 使用 instance subtree metric；
assertion/cover property 与 functional covergroup/variant/instance/point/cross 是不同结构，不能套用
code bin 模型。`tests.txt` 已包含 canonical merged test list，不再为 test list 启动第二次 URG。

## 选项作用与边界

| 选项 | 作用 | 不能推导的能力 |
| --- | --- | --- |
| `-full64` | 使用 64-bit URG；所有正式调用必带 | 不是可选性能 hint |
| `-dir <vdb>` | 指定 coverage database | 不接受 FSDB/daidir |
| `-report <dir>` | 指定完整 report 输出目录 | 应指向 staging，而非直接覆盖既有目标 |
| `-xml_verbose` | 生成完整 typed instance/assert/functional XML | `-xml_advanced` 不能替代完整 typed tree |
| `-format text` | 生成 tests/dashboard/modlist/groups/asserts 文本 | 单独使用会额外生成大型 modinfo/grpinfo |
| `-show summary` | 只保留 summary 六件套，抑制 HTML/modinfo/grpinfo/hierarchy | 不支持 gap/bin/source detail |
| `-metric <list>` | 在 URG 明确支持的 detail 模式中限制 metric | 不应把多个 action 各自启动 URG 当作 summary 优化 |
| `-tests <file>` | URG test 选择 | 当前 merged summary API 不支持 per-test selector |
| `-elfile <el>` | 在 URG report 中应用 opaque native exclusion | EL 不含 CSV reason |
| `-show brief` | 适合限定的 uncovered detail export | 不适合 session summary cache |

### `+` 的准确规则

`+` 不是通用 `-show` suboption 连接符。以下形式在已验证版本中均返回
`URG-US Unknown suboption`：

```text
-show summary+availabletests
-show summary+tests
-show summary+testrecords
```

只有 URG help 明确声明为 metric list 的位置才能使用 `+`，例如：

```text
-show brief line+cond
```

重复 `-show` 也不是可靠合并：`summary + availabletests` 会由 availabletests 主导并提前退出；
`summary + tests` 的 tests 表示每个对象的 test attribution，不是 test list，并会扩大 XML；
`summary + testrecords` 会增加 simulation record 表。普通 x-npi/xcov summary 不启用这些组合。

## Summary 语义

- 父 scope 直接使用 URG 提供的 subtree ratio，不再累计 descendants。
- root scope 由 XML instance 的 `parent=null` 关系确定，不依赖 `top`、`tb` 等命名约定。
- 单 metric `coverage_pct = covered / coverable * 100`。
- 多 metric scope/root SCORE 是所选 metric pct 的算术平均；不要发布没有明确分母的跨 metric
  `covered/coverable/missing`。
- 多 root 先按 metric 汇总各 root 的 covered/coverable；`0/0` 的 percentage 为 null，不参与
  多 metric 平均，全部选中 metric 均不可评分时 SCORE 为 null。
- functional Group SCORE 按 URG typed XML 发布，不从 code coverage 结构推断。
- 固定 summary 不支持 per-test attribution、code source-file/type 聚合、functional bin、源码
  file/line 或完整 gap locator。缺字段就是不支持，不能静默回退 NPI traversal。

## Exclusion-only NPI

```python
from x_npi.runtime import pynpi_lifecycle
from x_npi.coverage import (
    close_covdb,
    load_exclusion_files,
    merged_test_handle,
    open_covdb,
    save_exclusion_file,
    set_report_time_excluded,
    unload_exclusions,
)

with pynpi_lifecycle(["exclude-job"]):
    db = open_covdb("merged.vdb", strict=False)
    try:
        test = merged_test_handle(db)
        load_exclusion_files(test, ["existing.el"])
        # target 必须由当前 VDB traversal 唯一解析，使用后立即 release。
        result = set_report_time_excluded(target, test, True)
        save_exclusion_file(test, "working.el")
        unload_exclusions(test)
    finally:
        close_covdb(db)
```

- `open_covdb()` 先检查真实 `cov.open` 签名，每次只调用一次。旧版单参数只支持默认模式；
  双参数版本才可传 `ExclusionInStrictMode`。不通过捕获 `TypeError` 换参数重试。
- load 先验证全部 EL 是普通非 symlink 文件，再按给定顺序调用 `load_exclude_file`。
- setter 固定调用 `set_status_excluded_at_report_time(test, 1|0)`，并核对 before/after。
- save 固定使用 `save_exclude_file(path, "w")`；不得读取、拼接、格式化或追加 EL 文本。
- unload 固定使用 `unload_exclusion()`。vendor 返回值不是成功值 `1` 时明确失败。
- helper 不含 `_safe_call`，缺方法、签名错误、调用异常和非法返回全部直接报错；绝不改用无参
  调用、吞异常或返回 `None`。

## CSV sidecar 与 CSV → EL

三个 CSV 文件名和 schema 固定为：

```text
code_exclusions.csv       xcov-code-exclusions.v1
functional_exclusions.csv xcov-functional-exclusions.v1
assertion_exclusions.csv  xcov-assertion-exclusions.v1
```

CSV 使用 `# source_file=<portable-relative-path>` 的连续分组，`reason` 必填。parser 拒绝未知
metadata、非精确 header、绝对/`..` source path、重复/非连续分组、重复 selector、非法 metric/
assertion kind、超 64 MiB 文件、超 100,000 records、超 16 KiB field 和未闭合 multiline quote。
formatter 稳定排序；write 模式使用同目录 staging 与失败回滚。

```python
from x_npi.exclusion_csv import validate_directory, format_directory

validate_directory("coverage_exclusions")
format_directory("coverage_exclusions", write=True)
```

`compile_csv_to_el()` 内建严格 resolver，不依赖项目模块或 xcov：

```python
from x_npi.coverage import compile_csv_to_el

published = compile_csv_to_el(
    db,
    test,
    "coverage_exclusions",
    "compiled_el",
)
```

compiler 先建立 CSV selector 哈希索引。code/assertion 对唯一 exact scope 使用
`db.handle_by_name()`，只打开请求 metric，不遍历 instance hierarchy。functional 预检从 merged
testbench metric 根出发，但按请求 group/point/cross 前缀剪枝；应用阶段重放短生命周期 locator
trie，共享路径只访问一次，不做第二次全树扫描。实现不物化全库 coverage row、不保存 native handle、
不建立全 bin 索引，也不按 CSV 行重扫 VDB。某类 CSV 为空时不扫描该类。

source file 规范化分隔符后按完整路径段后缀匹配，最终 selector 仍必须唯一；零匹配、多匹配或
两遍间身份变化均失败。转换先保存 baseline EL；任一 scan/set/save/publish/load 失败都会恢复
native baseline 和旧文件。成功输出
`code.el/functional.el/assertion.el/container.el` 并按该顺序 load；缺少可选 container CSV 的旧
三文件目录仍合法，并生成空 `container.el`。

CSV 的 `reason` 只存在 sidecar，原生 EL 不保存 reason。因此：

- CSV → EL 有定义；
- EL load/save/unload 有定义；
- **不支持无损 EL → CSV**，也不能为 EL 条目编造 reason；
- dirty reason 必须先持久化 CSV，单独 save EL 不算 reason 已保存。

可执行模板为 `scripts/examples/csv_to_el.py`，只需提供 `--vdb`、`--csv-directory`、
`--output-directory`，需要严格 exclusion 模式时增加 `--strict`。脚本不接受外接 resolver，
也不 import xcov 私有模块。

容器级独立入口是 `scripts/examples/container_exclude.py`。它支持 exact/recursive instance 以及
covergroup、coverpoint、cross。recursive instance 只根据 fixed URG XML 的真实 instance adjacency
展开，不接受 module selector，也不调用 NPI `instance_handles()` 补扫。
