RUN_DIR ?= out
SOURCES := $(abspath packet_if.sv lane_math.sv lane_worker.sv packet_fabric.sv hierarchy_shell.sv top.sv)
VDB := $(abspath $(RUN_DIR)/complex.vdb)
SIMV := $(abspath $(RUN_DIR)/simv)
COVERAGE := line+cond+branch+tgl+fsm+assert

.PHONY: fixture
fixture:
	mkdir -p "$(RUN_DIR)"
	cd "$(RUN_DIR)" && \
		vcs -full64 -sverilog -kdb -debug_access+all \
			-cm $(COVERAGE) -cm_dir "$(VDB)" -o "$(SIMV)" $(SOURCES)
	cd "$(RUN_DIR)" && \
		"$(SIMV)" -cm $(COVERAGE) -cm_dir "$(VDB)" -cm_name complex

.PHONY: clean
clean:
	rm -rf "$(RUN_DIR)"
