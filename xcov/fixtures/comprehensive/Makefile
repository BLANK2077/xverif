RUN_DIR ?= out
SOURCE := $(abspath comprehensive.sv)
VDB := $(abspath $(RUN_DIR)/comprehensive.vdb)
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

.PHONY: clean
clean:
	rm -rf "$(RUN_DIR)"
