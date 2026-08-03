ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
REPO_ROOT := $(abspath $(ROOT_DIR)/../../../..)
RUN_DIR ?= $(ROOT_DIR)/out
BUILD_DIR := $(RUN_DIR)/build
SIMV := $(BUILD_DIR)/simv
JOIN_BUILD_DIR := $(RUN_DIR)/join/build
JOIN_SIMV := $(JOIN_BUILD_DIR)/simv
PROBE := $(RUN_DIR)/bin/npi_fsdb_sva_probe
JOIN_PROBE := $(RUN_DIR)/bin/npi_daidir_fsdb_sva_probe
VCS ?= vcs
CXX ?= g++

include $(REPO_ROOT)/mk/npi.mk

VCS_OPTS := -full64 -sverilog -timescale=1ns/1ps -debug_access+all -kdb -lca \
	-assert enable_diag
CXXFLAGS += -std=c++17 -O2 -Wall -Wextra -Werror $(NPI_CXXFLAGS) \
	-I$(REPO_ROOT)/xdebug/third_party
LDFLAGS += $(NPI_LDFLAGS) -Wl,-rpath,$(NPI_LIB)

.PHONY: all fixture compile run-positive run-success-only run-control run-join probe probe-results join-probe join-results restrict-check clean

all: fixture

fixture: probe-results join-results restrict-check

$(BUILD_DIR):
	mkdir -p $@

$(SIMV): $(ROOT_DIR)/sva_fsdb_fixture.sv | $(BUILD_DIR)
	cd $(BUILD_DIR) && $(VCS) $(VCS_OPTS) $(ROOT_DIR)/sva_fsdb_fixture.sv \
		-top sva_fsdb_fixture_top -o $(SIMV) -l compile.log

compile: $(SIMV)

$(JOIN_BUILD_DIR):
	mkdir -p $@

$(JOIN_SIMV): $(ROOT_DIR)/sva_daidir_join_fixture.sv | $(JOIN_BUILD_DIR)
	cd $(JOIN_BUILD_DIR) && $(VCS) $(VCS_OPTS) \
		$(ROOT_DIR)/sva_daidir_join_fixture.sv \
		-top sva_daidir_join_fixture_top -o $(JOIN_SIMV) -l compile.log

run-positive: $(SIMV)
	mkdir -p $(RUN_DIR)/positive
	cd $(RUN_DIR)/positive && $(SIMV) -ucli -do $(ROOT_DIR)/wave_sva.tcl \
		-assert success +fsdb+sva_success +fsdb+sva_vacuous \
		+ORACLE=stimulus.jsonl -l sim.log
	test -s $(RUN_DIR)/positive/waves.fsdb
	test -s $(RUN_DIR)/positive/stimulus.jsonl

run-success-only: $(SIMV)
	mkdir -p $(RUN_DIR)/success_only
	cd $(RUN_DIR)/success_only && $(SIMV) -ucli -do $(ROOT_DIR)/wave_sva.tcl \
		-assert success +fsdb+sva_success \
		+ORACLE=stimulus.jsonl -l sim.log
	test -s $(RUN_DIR)/success_only/waves.fsdb
	test -s $(RUN_DIR)/success_only/stimulus.jsonl

run-control: $(SIMV)
	mkdir -p $(RUN_DIR)/control
	cd $(RUN_DIR)/control && $(SIMV) -ucli -do $(ROOT_DIR)/wave_control.tcl \
		-assert success +ORACLE=stimulus.jsonl -l sim.log
	test -s $(RUN_DIR)/control/waves.fsdb
	test -s $(RUN_DIR)/control/stimulus.jsonl

run-join: $(JOIN_SIMV)
	mkdir -p $(RUN_DIR)/join
	cd $(RUN_DIR)/join && $(JOIN_SIMV) -ucli -do $(ROOT_DIR)/wave_join.tcl \
		-assert success +fsdb+sva_success +fsdb+sva_vacuous -l sim.log
	test -s $(RUN_DIR)/join/waves.fsdb
	test -d $(JOIN_SIMV).daidir

$(PROBE): $(ROOT_DIR)/npi_fsdb_sva_probe.cpp
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

probe: $(PROBE)

$(JOIN_PROBE): $(ROOT_DIR)/npi_daidir_fsdb_sva_probe.cpp
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

join-probe: $(JOIN_PROBE)

probe-results: run-positive run-success-only run-control probe
	cd $(RUN_DIR)/positive && $(PROBE) waves.fsdb > probe.json
	cd $(RUN_DIR)/success_only && $(PROBE) waves.fsdb > probe.json
	cd $(RUN_DIR)/control && $(PROBE) waves.fsdb > probe.json
	test -s $(RUN_DIR)/positive/probe.json
	test -s $(RUN_DIR)/success_only/probe.json
	test -s $(RUN_DIR)/control/probe.json

join-results: run-join join-probe
	cd $(RUN_DIR)/join && $(JOIN_PROBE) \
		-dbdir $(JOIN_SIMV).daidir -ssf waves.fsdb > probe.json
	cd $(RUN_DIR)/join && $(JOIN_PROBE) \
		-dbdir $(JOIN_SIMV).daidir > design_probe.json
	cd $(RUN_DIR)/positive && $(JOIN_PROBE) \
		-dbdir $(SIMV).daidir -ssf waves.fsdb > combined_probe.json
	test -s $(RUN_DIR)/join/probe.json
	test -s $(RUN_DIR)/join/design_probe.json
	test -s $(RUN_DIR)/positive/combined_probe.json

restrict-check:
	mkdir -p $(RUN_DIR)/restrict
	cd $(RUN_DIR)/restrict && if $(VCS) $(VCS_OPTS) \
		$(ROOT_DIR)/restrict_compile_probe.sv -top restrict_compile_probe_top \
		-o restrict_simv -l compile.log; then \
		echo "restrict property unexpectedly compiled; update the research expectation"; \
		exit 1; \
	fi
	grep -q "token is 'restrict'" $(RUN_DIR)/restrict/compile.log

clean:
	rm -rf $(RUN_DIR)
