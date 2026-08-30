# AXI XAMBA UVM VIP real-wave fixture

本 fixture 与现有 `axi_vip_real` SVT 基线并行存在，不替换或删除旧 fixture。

构建入口通过 XAMBA 仓库官方 Makefile 直接消费 product-only
`filelists/xamba_axi4_vip.f`。xverif 自己拥有 `xdebug_axi_xamba_fixture_pkg` 和 top，
只使用 XAMBA 公开的 `xam_axi_pkg`、AXI interface、pin source 及 manager/subordinate
endpoint，生成 64 笔确定性的多 ID、INCR burst mixed read/write；不编译 XAMBA
`tb_clean/` 或内部 compile top。fixture top 补充 FSDB dump 和 pin-handshake JSONL oracle。

XAMBA 的编译缓存和运行产物仍位于其规则允许的 `out/`，xverif fixture 只把
FSDB、daidir、仿真日志、运行 manifest、解析后的 filelist、外部附加源 manifest 和 oracle
发布到自己的不可变 generation。fixture package/top 通过 XAMBA 的 `EXTRA_SOURCES` 追加，
其 canonical path 和内容摘要进入 compile key。

正式入口：

```bash
XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-prepare xdebug.axi_xamba_vip

XAMBA_UVM_VIP_ROOT=<xamba-vip-repo> \
XVERIF_TEST_EXECUTION_ENV=host \
.conda-xverif/bin/pytest --xverif-gate nightly \
  --xverif-suite xdebug.axi_xamba_vip
```
