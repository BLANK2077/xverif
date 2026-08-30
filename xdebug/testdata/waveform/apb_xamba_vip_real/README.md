# APB XAMBA UVM VIP real-wave fixture

本 fixture 与现有 `apb_vip_real` SVT 基线并行存在，不替换或删除旧 fixture。

构建入口通过 XAMBA 仓库官方 Makefile 直接消费 product-only
`filelists/xamba_apb5_vip.f`。xverif 自己拥有 `xdebug_apb_xamba_fixture_pkg` 和 top，
只使用 XAMBA 公开的 `xam_apb_pkg`、APB interface、pin source 及 requester/completer
endpoint，生成 64 笔包含 wait、strobe 和 error 的确定性 read/write；不编译 XAMBA
`tb_clean/` 或内部 compile top。

XAMBA 的编译缓存和运行产物仍位于其规则允许的 `out/`，xverif fixture 只把 FSDB、
daidir、仿真日志、运行 manifest、解析后的 filelist 和外部附加源 manifest 发布到自己的
不可变 generation。

输入由 `XAMBA_UVM_VIP_ROOT` 指定，并以 `XAMBA_UVM_VIP_REVISION` 校验
`src_clean/`、所选 product-only filelist、Makefile、`mk/` 和 `tools/` 没有相对该版本漂移。
fixture package/top 通过 XAMBA 的 `EXTRA_SOURCES` 追加，其 canonical path 和内容摘要进入
compile key。

正式入口：

```bash
XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-prepare xdebug.apb_xamba_vip

XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-gate nightly \
  --xverif-suite xdebug.apb_xamba_vip
```
