SHELL := /bin/bash

XAMBA_UVM_VIP_ROOT ?=
XAMBA_UVM_VIP_REVISION ?= 5fcd0c28da22bd10939f152b18e0a927c1d54834
OUTPUT_ROOT ?= $(CURDIR)/out

PROTOCOL := apb5
FILELIST := filelists/xamba_apb5_vip.f
TOP := xdebug_apb_xamba_fixture_top
TEST := xdebug_apb_xamba_fixture_test
SEED := 11
XAMBA_BUILD_ROOT := out/xverif-fixtures/build
XAMBA_RUN_ROOT := out/xverif-fixtures/run
FIXTURE_PACKAGE := $(abspath tb/xdebug_apb_xamba_fixture_pkg.sv)
FIXTURE_TOP := $(abspath tb/xdebug_apb_xamba_fixture_top.sv)
EXTRA_SOURCES := $(FIXTURE_PACKAGE) $(FIXTURE_TOP)
VCS_FLAGS_EXTRA := -debug_access+all
XAMBA_RUN_DIR := $(XAMBA_UVM_VIP_ROOT)/$(XAMBA_RUN_ROOT)/$(PROTOCOL)/$(TEST)/$(SEED)

.PHONY: check-env run clean

check-env:
	@test -n "$(XAMBA_UVM_VIP_ROOT)" || { echo "XAMBA_UVM_VIP_ROOT is required"; exit 2; }
	@test -d "$(XAMBA_UVM_VIP_ROOT)" || { echo "XAMBA_UVM_VIP_ROOT must be a directory"; exit 2; }
	@test -f "$(XAMBA_UVM_VIP_ROOT)/$(FILELIST)" || { echo "XAMBA APB5 filelist is missing"; exit 2; }
	@git -C "$(XAMBA_UVM_VIP_ROOT)" ls-files --error-unmatch "$(FILELIST)" >/dev/null
	@! grep -q 'tb_clean/' "$(XAMBA_UVM_VIP_ROOT)/$(FILELIST)" || { echo "XAMBA APB5 consumer filelist includes tb_clean"; exit 2; }
	@test -n "$(VERDI_HOME)" || { echo "VERDI_HOME is required for FSDB dumping"; exit 2; }
	@test -d "$(VERDI_HOME)" || { echo "VERDI_HOME must be a directory"; exit 2; }
	@git -C "$(XAMBA_UVM_VIP_ROOT)" cat-file -e "$(XAMBA_UVM_VIP_REVISION)^{commit}"
	@git -C "$(XAMBA_UVM_VIP_ROOT)" diff --quiet "$(XAMBA_UVM_VIP_REVISION)" -- \
		src_clean "$(FILELIST)" Makefile mk tools || { \
		echo "XAMBA build inputs differ from XAMBA_UVM_VIP_REVISION"; exit 2; }
	@$(MAKE) -C "$(XAMBA_UVM_VIP_ROOT)" --no-print-directory audit-consumer-contract

run: check-env
	$(MAKE) -C "$(XAMBA_UVM_VIP_ROOT)" --no-print-directory run \
		PROTOCOL=$(PROTOCOL) FILELIST=$(FILELIST) TOP=$(TOP) TEST=$(TEST) SEED=$(SEED) \
		BUILD_ROOT=$(XAMBA_BUILD_ROOT) RUN_ROOT=$(XAMBA_RUN_ROOT) \
		EXTRA_SOURCES="$(EXTRA_SOURCES)" \
		VCS_FLAGS_EXTRA="$(VCS_FLAGS_EXTRA)" \
		SIM_FLAGS_EXTRA="+fsdb+autoflush"
	@set -euo pipefail; \
		compile_key="$$( $(MAKE) -C "$(XAMBA_UVM_VIP_ROOT)" --no-print-directory -s compile-key \
			PROTOCOL=$(PROTOCOL) FILELIST=$(FILELIST) TOP=$(TOP) \
			BUILD_ROOT=$(XAMBA_BUILD_ROOT) EXTRA_SOURCES="$(EXTRA_SOURCES)" \
			VCS_FLAGS_EXTRA="$(VCS_FLAGS_EXTRA)" )"; \
		build_dir="$(XAMBA_UVM_VIP_ROOT)/$(XAMBA_BUILD_ROOT)/$$compile_key"; \
		test -s "$(XAMBA_RUN_DIR)/waves.fsdb"; \
		test -s "$(XAMBA_RUN_DIR)/run.log"; \
		test -s "$(XAMBA_RUN_DIR)/manifest.txt"; \
		test -d "$$build_dir/simv.daidir"; \
		test -s "$$build_dir/extra_sources.manifest"; \
		test -s "$$build_dir/resolved.f"; \
		! grep -q '/tb_clean/' "$$build_dir/resolved.f"; \
		grep -q "XDEBUG_XAMBA_APB_FIXTURE_PASS" "$(XAMBA_RUN_DIR)/run.log"; \
		install -d "$(OUTPUT_ROOT)"; \
		cp "$(XAMBA_RUN_DIR)/waves.fsdb" "$(OUTPUT_ROOT)/waves.fsdb"; \
		cp "$(XAMBA_RUN_DIR)/run.log" "$(OUTPUT_ROOT)/sim.log"; \
		cp "$(XAMBA_RUN_DIR)/manifest.txt" "$(OUTPUT_ROOT)/xamba-run-manifest.txt"; \
		cp "$$build_dir/extra_sources.manifest" "$(OUTPUT_ROOT)/xamba-extra-sources.manifest"; \
		cp "$$build_dir/resolved.f" "$(OUTPUT_ROOT)/xamba-resolved.f"; \
		cp -a "$$build_dir/simv.daidir" "$(OUTPUT_ROOT)/simv.daidir"

clean:
	@echo "fixture cache cleanup is managed by the xverif test infrastructure"
