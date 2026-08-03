RUN_DIR ?= out
SOURCE := $(abspath exclusion_fixture.sv)
VDB := $(abspath $(RUN_DIR)/exclusion.vdb)
SIMV := $(abspath $(RUN_DIR)/simv)

.PHONY: fixture
fixture:
	mkdir -p "$(RUN_DIR)"
	cd "$(RUN_DIR)" && \
		vcs -full64 -sverilog -kdb -debug_access+all \
			-cm line+cond+branch+tgl+fsm+assert \
			-cm_dir "$(VDB)" -o "$(SIMV)" "$(SOURCE)"
	cd "$(RUN_DIR)" && \
		"$(SIMV)" +VARIANT=0 -cm line+cond+branch+tgl+fsm+assert \
			-cm_dir "$(VDB)" -cm_name variant0
	cd "$(RUN_DIR)" && \
		"$(SIMV)" +VARIANT=1 -cm line+cond+branch+tgl+fsm+assert \
			-cm_dir "$(VDB)" -cm_name variant1
