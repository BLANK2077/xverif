# APB XAMBA UVM VIP real-wave fixture

本 fixture 与现有 `apb_vip_real` SVT 基线并行存在，不替换或删除旧 fixture。

构建入口通过 XAMBA 仓库官方 Makefile 直接消费 checked-in
`filelists/apb5.f`，运行其公开 `xam_i6_apb_reply_test`，并由 fixture wrapper
补充 FSDB dump。XAMBA 的编译缓存和运行产物仍位于其规则允许的 `out/`，xverif
fixture 只把 FSDB、daidir、仿真日志和运行 manifest 发布到自己的不可变 generation。

输入由 `XAMBA_UVM_VIP_ROOT` 指定，并以 `XAMBA_UVM_VIP_REVISION` 校验
`src_clean/`、`tb_clean/`、filelist、Makefile、`mk/` 和 `tools/` 没有相对该版本漂移。

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
