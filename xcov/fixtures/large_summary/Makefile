RUN_DIR ?= out
GENERATOR := $(abspath generate_large_fixture.py)
GENERATED_DIR := $(abspath $(RUN_DIR)/generated)
RTL := $(GENERATED_DIR)/large_design.sv
METADATA := $(abspath $(RUN_DIR)/fixture_metadata.json)
VDB := $(abspath $(RUN_DIR)/large_summary.vdb)
SIMV := $(abspath $(RUN_DIR)/simv)
CM := line+cond+branch+tgl+fsm+assert

.PHONY: fixture
fixture:
	mkdir -p "$(GENERATED_DIR)"
	python3 "$(GENERATOR)" --output "$(RTL)" --metadata "$(METADATA)"
	cd "$(RUN_DIR)" && vcs -full64 -sverilog -kdb -debug_access+all \
		-cm $(CM) -cm_dir "$(VDB)" -Mdir="$(abspath $(RUN_DIR)/csrc)" \
		-o "$(SIMV)" "$(RTL)"
	cd "$(RUN_DIR)" && "$(SIMV)" -cm $(CM) -cm_dir "$(VDB)" \
		-cm_name large_summary
