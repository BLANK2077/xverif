RUN_DIR ?= out
VARIANT ?= edge
SOURCE := $(abspath design.sv)
COVERAGE := line+cond+branch+tgl+fsm+assert

ifeq ($(VARIANT),edge)
VDB_NAME := edge_cases.vdb
DEFINES :=
else ifeq ($(VARIANT),zero)
VDB_NAME := zero_coverable.vdb
DEFINES := +define+INCLUDE_ZERO_COVERABLE
else
$(error VARIANT must be edge or zero)
endif

VDB := $(abspath $(RUN_DIR)/$(VDB_NAME))
SIMV := $(abspath $(RUN_DIR)/simv-$(VARIANT))

.PHONY: fixture
fixture:
	mkdir -p "$(RUN_DIR)"
	cd "$(RUN_DIR)" && \
		vcs -full64 -sverilog -lca -kdb -debug_access+all \
			-cm $(COVERAGE) -cm_dir "$(VDB)" $(DEFINES) \
			"$(SOURCE)" -top route_matrix -o "$(SIMV)"
	cd "$(RUN_DIR)" && \
		"$(SIMV)" -cm $(COVERAGE) -cm_dir "$(VDB)" -cm_name "$(VARIANT)"

.PHONY: clean
clean:
	rm -rf "$(RUN_DIR)"
