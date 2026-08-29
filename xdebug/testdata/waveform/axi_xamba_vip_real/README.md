# AXI XAMBA UVM VIP real-wave fixture

本 fixture 与现有 `axi_vip_real` SVT 基线并行存在，不替换或删除旧 fixture。

构建入口通过 XAMBA 仓库官方 Makefile 直接消费 checked-in
`filelists/axi4.f`，运行公开 `xam_i4_axi_random_test`。该 test 同时建立
XAMBA manager/subordinate active path，固定四类随机 seed 和 64 笔 mixed read/write
operation。fixture wrapper 只补充 FSDB dump 和 pin-handshake JSONL oracle。

XAMBA 的编译缓存和运行产物仍位于其规则允许的 `out/`，xverif fixture 只把
FSDB、daidir、仿真日志、运行 manifest 和 oracle 发布到自己的不可变 generation。

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
