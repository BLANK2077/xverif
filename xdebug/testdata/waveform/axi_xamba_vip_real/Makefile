SHELL := /bin/bash

XAMBA_UVM_VIP_ROOT ?=
XAMBA_UVM_VIP_REVISION ?= dc653589484006d5d08506265df8e37521039384
OUTPUT_ROOT ?= $(CURDIR)/out

PROTOCOL := axi4
FILELIST := filelists/axi4.f
TOP := xdebug_axi_xamba_fixture_top
TEST := xam_i4_axi_random_test
SEED := 7
XAMBA_BUILD_ROOT := out/xverif-fixtures/build
XAMBA_RUN_ROOT := out/xverif-fixtures/run
FIXTURE_TOP := $(abspath tb/xdebug_axi_xamba_fixture_top.sv)
FIXTURE_SHA := $(shell sha256sum $(FIXTURE_TOP) | cut -c1-16)
VCS_FLAGS_EXTRA := -debug_access+all $(FIXTURE_TOP) \
	+define+XDEBUG_XAMBA_AXI_FIXTURE_$(FIXTURE_SHA)
SIM_FLAGS_EXTRA := +fsdb+autoflush +XAM_SUITE_SEED=7 \
	+XAM_OPERATION_SEED=101 +XAM_TIMING_SEED=103 \
	+XAM_REPLY_SEED=107 +XAM_OPERATION_COUNT=64
XAMBA_RUN_DIR := $(XAMBA_UVM_VIP_ROOT)/$(XAMBA_RUN_ROOT)/$(PROTOCOL)/$(TEST)/$(SEED)

.PHONY: check-env run clean

check-env:
	@test -n "$(XAMBA_UVM_VIP_ROOT)" || { echo "XAMBA_UVM_VIP_ROOT is required"; exit 2; }
	@test -d "$(XAMBA_UVM_VIP_ROOT)" || { echo "XAMBA_UVM_VIP_ROOT must be a directory"; exit 2; }
	@test -f "$(XAMBA_UVM_VIP_ROOT)/$(FILELIST)" || { echo "XAMBA AXI4 filelist is missing"; exit 2; }
	@test -n "$(VERDI_HOME)" || { echo "VERDI_HOME is required for FSDB dumping"; exit 2; }
	@test -d "$(VERDI_HOME)" || { echo "VERDI_HOME must be a directory"; exit 2; }
	@git -C "$(XAMBA_UVM_VIP_ROOT)" cat-file -e "$(XAMBA_UVM_VIP_REVISION)^{commit}"
	@git -C "$(XAMBA_UVM_VIP_ROOT)" diff --quiet "$(XAMBA_UVM_VIP_REVISION)" -- \
		src_clean tb_clean filelists Makefile mk tools || { \
		echo "XAMBA build inputs differ from XAMBA_UVM_VIP_REVISION"; exit 2; }

run: check-env
	$(MAKE) -C "$(XAMBA_UVM_VIP_ROOT)" --no-print-directory run \
		PROTOCOL=$(PROTOCOL) FILELIST=$(FILELIST) TOP=$(TOP) TEST=$(TEST) SEED=$(SEED) \
		BUILD_ROOT=$(XAMBA_BUILD_ROOT) RUN_ROOT=$(XAMBA_RUN_ROOT) \
		VCS_FLAGS_EXTRA="$(VCS_FLAGS_EXTRA)" \
		SIM_FLAGS_EXTRA="$(SIM_FLAGS_EXTRA)"
	@set -euo pipefail; \
		compile_key="$$( $(MAKE) -C "$(XAMBA_UVM_VIP_ROOT)" --no-print-directory -s compile-key \
			PROTOCOL=$(PROTOCOL) FILELIST=$(FILELIST) TOP=$(TOP) \
			BUILD_ROOT=$(XAMBA_BUILD_ROOT) VCS_FLAGS_EXTRA="$(VCS_FLAGS_EXTRA)" )"; \
		build_dir="$(XAMBA_UVM_VIP_ROOT)/$(XAMBA_BUILD_ROOT)/$$compile_key"; \
		test -s "$(XAMBA_RUN_DIR)/waves.fsdb"; \
		test -s "$(XAMBA_RUN_DIR)/axi_handshake.jsonl"; \
		test -s "$(XAMBA_RUN_DIR)/run.log"; \
		test -s "$(XAMBA_RUN_DIR)/manifest.txt"; \
		test -d "$$build_dir/simv.daidir"; \
		grep -q "XAM_I4_AXI_RANDOM_PASS" "$(XAMBA_RUN_DIR)/run.log"; \
		install -d "$(OUTPUT_ROOT)"; \
		cp "$(XAMBA_RUN_DIR)/waves.fsdb" "$(OUTPUT_ROOT)/waves.fsdb"; \
		cp "$(XAMBA_RUN_DIR)/axi_handshake.jsonl" "$(OUTPUT_ROOT)/axi_handshake.jsonl"; \
		cp "$(XAMBA_RUN_DIR)/run.log" "$(OUTPUT_ROOT)/sim.log"; \
		cp "$(XAMBA_RUN_DIR)/manifest.txt" "$(OUTPUT_ROOT)/xamba-run-manifest.txt"; \
		cp -a "$$build_dir/simv.daidir" "$(OUTPUT_ROOT)/simv.daidir"

clean:
	@echo "fixture cache cleanup is managed by the xverif test infrastructure"
