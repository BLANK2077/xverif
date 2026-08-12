TOP ?= ..

.DEFAULT_GOAL := all

include $(TOP)/mk/common_flags.mk

include $(TOP)/mk/npi.mk

NPI_CXXFLAGS ?=
NPI_LDFLAGS ?=
NPI_LIB ?=

BUILD_INFO = $(BUILD)/build_info.h
ACTION_METADATA = src/api/generated_action_metadata.inc
GENERATED_HELP_TEXT = src/api/generated_help_text.inc
CXXFLAGS = $(COMMON_CXXFLAGS) $(NPI_CXXFLAGS) -pthread -I$(BUILD) -Isrc -Isrc/core -Isrc/engine -Isrc/design -Isrc/waveform -isystem third_party -isystem third_party/json-schema-validator/src
LDFLAGS  = $(NPI_LDFLAGS) -pthread $(if $(NPI_LIB),-Xlinker -rpath -Xlinker $(NPI_LIB),)
DEPFLAGS = -MMD -MP
# Frontend does not need NPI (all NPI is in the engine subprocess).
FRONTEND_LDFLAGS = -pthread
BUILD    = build
LIBEXEC  = libexec
EXE      = xdebug
PYTHON  ?= python3

CORE_SRCS = src/core/common/tool_config.cpp \
            src/core/common/env_config.cpp \
            src/core/common/path_utils.cpp \
            src/core/common/sha256.cpp \
            src/core/value/logic_value.cpp \
            src/core/npi/time_contract.cpp \
            src/core/transport/file_exchange.cpp \
            src/core/logging/action_log.cpp \
            src/core/session/session_types.cpp \
            src/core/session/session_endpoint_contract.cpp \
            src/core/session/session_registry_contract.cpp \
            src/core/process/process_runner.cpp \
            src/engine/service/contract_bound_request.cpp \
            src/core/schema/internal_request_contract.cpp \
            src/core/schema/runtime_schema_validator.cpp \
            src/core/ai/common_blocks.cpp \
            src/core/ai/ai_response.cpp \
            third_party/json-schema-validator/src/smtp-address-validator.cpp \
            third_party/json-schema-validator/src/json-schema-draft7.json.cpp \
            third_party/json-schema-validator/src/json-uri.cpp \
            third_party/json-schema-validator/src/json-validator.cpp \
            third_party/json-schema-validator/src/json-patch.cpp \
            third_party/json-schema-validator/src/string-format-check.cpp

API_SUPPORT_SRCS = src/api/action_spec.cpp \
                   src/api/action_registry.cpp \
                   src/api/action_registry_init.cpp \
                   src/api/request_envelope.cpp \
                   src/api/request_validator.cpp \
                   src/api/resource_resolver.cpp \
                   src/api/response_builder.cpp

APP_SRCS = src/main.cpp \
           src/api/request_parser.cpp \
           src/api/response.cpp \
           src/api/help_text.cpp \
           src/api/text_response_builder.cpp \
           src/api/xout_renderer.cpp \
           src/api/action_catalog.cpp \
           src/api/dispatcher.cpp \
           src/api/stdio_loop.cpp \
           $(API_SUPPORT_SRCS) \
           src/session/session_catalog.cpp \
           src/backend/engine_adapter.cpp \
           src/runtime/work_dir.cpp

ENGINE_SRCS = src/engine/main.cpp \
              src/engine/engine_query.cpp \
              src/engine/server.cpp \
              src/engine/session/session_registry.cpp \
              src/engine/session/session_manager.cpp \
              src/engine/session/session_transport.cpp \
              src/engine/session/json_line_reader.cpp \
              src/engine/session/client.cpp \
              src/engine/service/engine_action_registry.cpp \
              src/engine/service/engine_action_handler.cpp \
              src/engine/service/trace_source_path_formatter.cpp \
              src/engine/service/actions/combined/register_combined_handlers.cpp \
              src/engine/service/actions/combined/trace_active_driver.cpp \
              src/engine/service/actions/combined/trace_active_driver_chain.cpp \
              src/engine/service/actions/combined/trace_x_origin.cpp \
              src/engine/service/actions/design/expr_normalize.cpp \
              src/engine/service/actions/design/register_design_handlers.cpp \
              src/engine/service/actions/design/signal_canonicalize.cpp \
              src/engine/service/actions/design/signal_resolve.cpp \
              src/engine/service/actions/design/trace_driver.cpp \
              src/engine/service/actions/design/trace_load.cpp \
              src/engine/service/actions/protocol/apb_config_list.cpp \
              src/engine/service/actions/protocol/apb_config_load.cpp \
              src/engine/service/actions/protocol/apb_transaction_cursor.cpp \
              src/engine/service/actions/protocol/apb_export.cpp \
              src/engine/service/actions/protocol/apb_query.cpp \
              src/engine/service/actions/protocol/apb_statistics.cpp \
              src/engine/service/actions/protocol/axi_analysis.cpp \
              src/engine/service/actions/protocol/axi_config_list.cpp \
              src/engine/service/actions/protocol/axi_config_load.cpp \
              src/engine/service/actions/protocol/axi_transaction_cursor.cpp \
              src/engine/service/actions/protocol/axi_export.cpp \
              src/engine/service/actions/protocol/axi_query.cpp \
              src/engine/service/actions/protocol/axi_statistics.cpp \
              src/engine/service/actions/protocol/protocol_query_filter.cpp \
              src/engine/service/actions/protocol/protocol_statistics_filter.cpp \
              src/engine/service/actions/protocol/register_protocol_handlers.cpp \
              src/engine/service/actions/stream/register_stream_handlers.cpp \
              src/engine/service/actions/stream/stream_config_list.cpp \
              src/engine/service/actions/stream/stream_config_get.cpp \
              src/engine/service/actions/stream/stream_config_load.cpp \
              src/engine/service/actions/stream/stream_export.cpp \
              src/engine/service/actions/stream/stream_query.cpp \
              src/engine/service/actions/stream/stream_describe.cpp \
              src/engine/service/actions/stream/stream_validate.cpp \
              src/engine/service/actions/waveform/apb_transfer_window.cpp \
              src/engine/service/actions/waveform/axi_channel_stall.cpp \
              src/engine/service/actions/waveform/axi_latency_outlier.cpp \
              src/engine/service/actions/waveform/axi_outstanding_timeline.cpp \
              src/engine/service/actions/waveform/axi_request_response_pair.cpp \
              src/engine/service/actions/waveform/clock_point_query.cpp \
              src/engine/service/actions/waveform/counter_statistics.cpp \
              src/engine/service/actions/waveform/waveform_cursor_delete.cpp \
              src/engine/service/actions/waveform/waveform_cursor_get.cpp \
              src/engine/service/actions/waveform/waveform_cursor_list.cpp \
              src/engine/service/actions/waveform/waveform_cursor_set.cpp \
              src/engine/service/actions/waveform/waveform_cursor_use.cpp \
              src/engine/service/actions/waveform/signal_anomaly_inspect.cpp \
              src/engine/service/actions/waveform/event_config_list.cpp \
              src/engine/service/actions/waveform/event_config_load.cpp \
              src/engine/service/actions/waveform/event_export.cpp \
              src/engine/service/actions/waveform/event_find.cpp \
              src/engine/service/actions/waveform/expr_eval_at.cpp \
              src/engine/service/actions/waveform/protocol_handshake_inspect.cpp \
              src/engine/service/actions/waveform/list_add.cpp \
              src/engine/service/actions/waveform/list_create.cpp \
              src/engine/service/actions/waveform/list_load.cpp \
              src/engine/service/actions/waveform/list_delete.cpp \
              src/engine/service/actions/waveform/list_first_change.cpp \
              src/engine/service/actions/waveform/list_export.cpp \
              src/engine/service/actions/waveform/list_show.cpp \
              src/engine/service/actions/waveform/list_validate.cpp \
              src/engine/service/actions/waveform/nwave_rc_generate.cpp \
              src/engine/service/actions/waveform/register_waveform_handlers.cpp \
              src/engine/service/actions/waveform/signal_sampled_pulse_inspect.cpp \
              src/engine/service/actions/waveform/scope_list.cpp \
              src/engine/service/actions/waveform/scope_roots.cpp \
              src/engine/service/actions/waveform/signal_changes.cpp \
              src/engine/service/actions/waveform/signal_stability.cpp \
              src/engine/service/actions/waveform/signal_xz_verify.cpp \
              src/engine/service/actions/waveform/signal_statistics.cpp \
              src/engine/service/actions/waveform/value_at.cpp \
              src/engine/service/actions/waveform/verify_conditions.cpp \
              src/engine/service/actions/waveform/window_verify.cpp \
              src/engine/service/design_postprocess.cpp \
              src/engine/service/trace_bfs_engine.cpp \
              src/api/response.cpp \
              src/api/text_response_builder.cpp \
              src/runtime/work_dir.cpp \
              src/combined/active_trace_service.cpp \
              src/combined/active_trace_chain.cpp


DESIGN_SRCS = src/design/service/action_support.cpp \
              src/design/hierarchy/relationship_walker.cpp \
              src/design/service/trace_actions.cpp \
              src/design/common/xdebug_design_paths.cpp \
              src/design/ast/ast_extractor.cpp \
              src/design/control_dep/control_dep.cpp \
              src/design/trace/trace_engine.cpp \
              src/design/signal/signal_finder.cpp

WAVEFORM_SRCS = src/waveform/service/action_support.cpp \
                src/waveform/service/value_support.cpp \
                src/waveform/service/config_support.cpp \
                src/waveform/service/rc_generator.cpp \
                src/waveform/filter/value_filter.cpp \
                src/waveform/server/service/context.cpp \
                src/waveform/server/service/value_scope.cpp \
                src/waveform/server/service/signal_analysis.cpp \
                src/waveform/server/service/signal_inspect.cpp \
                src/waveform/server/service/query_actions.cpp \
                src/waveform/server/service/event_handlers.cpp \
                src/waveform/server/fsdb_value_reader.cpp \
                src/waveform/server/fsdb_scan_utils.cpp \
                src/waveform/export/waveform_exporter.cpp \
                src/waveform/value/value_collection.cpp \
                src/waveform/list/list_manager.cpp \
                src/waveform/cursor/cursor_manager.cpp \
                src/waveform/common/xdebug_waveform_paths.cpp \
                src/waveform/common/versioned_json_store.cpp \
                src/waveform/common/time_spec.cpp \
                src/waveform/common/clock_sampling.cpp \
                src/waveform/common/clock_sampling_response.cpp \
                src/waveform/common/reset_config.cpp \
                src/waveform/common/expression.cpp \
                src/waveform/cache/analysis_probe.cpp \
                src/waveform/cache/analysis_repository.cpp \
                src/waveform/cache/analysis_size_estimator.cpp \
                src/waveform/apb/apb_manager.cpp \
                src/waveform/apb/apb_analyzer.cpp \
                src/waveform/apb/apb_exporter.cpp \
                src/waveform/axi/axi_manager.cpp \
                src/waveform/axi/axi_transaction_tracker.cpp \
                src/waveform/axi/axi_transaction_json.cpp \
                src/waveform/axi/axi_analyzer.cpp \
                src/waveform/axi/axi_exporter.cpp \
                src/waveform/event/event_manager.cpp \
                src/waveform/event/event_expr.cpp \
                src/waveform/event/event_analyzer.cpp \
                src/waveform/stream/stream_config.cpp \
                src/waveform/stream/stream_manager.cpp \
                src/waveform/stream/stream_expr.cpp \
                src/waveform/stream/stream_signal_values.cpp \
                src/waveform/stream/stream_analyzer.cpp \
                src/waveform/stream/legacy_stream_analyzer_adapter.cpp \
                src/waveform/stream/stream_exporter.cpp

CORE_OBJS = $(CORE_SRCS:%.cpp=$(BUILD)/%.o)
API_SUPPORT_OBJS = $(API_SUPPORT_SRCS:%.cpp=$(BUILD)/%.o)
APP_OBJS = $(APP_SRCS:%.cpp=$(BUILD)/%.o)
ENGINE_OBJS = $(ENGINE_SRCS:%.cpp=$(BUILD)/%.o)
DESIGN_OBJS = $(DESIGN_SRCS:%.cpp=$(BUILD)/%.o)
WAVEFORM_OBJS = $(WAVEFORM_SRCS:%.cpp=$(BUILD)/%.o)
DEPS = $(sort $(CORE_OBJS:.o=.d) \
       $(API_SUPPORT_OBJS:.o=.d) \
       $(APP_OBJS:.o=.d) \
       $(ENGINE_OBJS:.o=.d) \
       $(DESIGN_OBJS:.o=.d) \
       $(WAVEFORM_OBJS:.o=.d))

.PHONY: all internal-engines cpp-unit-binaries clean FORCE

FORCE:

$(ACTION_METADATA): specs/actions/actions.yaml tools/sync_action_metadata.py
	$(PYTHON) tools/sync_action_metadata.py

$(BUILD)/src/api/action_registry_init.o: $(ACTION_METADATA)

$(GENERATED_HELP_TEXT): help.txt tools/sync_help_text.py
	$(PYTHON) tools/sync_help_text.py

$(BUILD)/src/api/help_text.o: $(GENERATED_HELP_TEXT)

$(BUILD_INFO): FORCE specs/actions/actions.yaml
	@mkdir -p $(dir $@)
	@rev=$$(git -C $(TOP) rev-parse --short=12 HEAD 2>/dev/null || echo unknown); \
	schema=$$(sha256sum specs/actions/actions.yaml 2>/dev/null | awk '{print $$1}' || echo unknown); \
	{ echo '#pragma once'; echo "#define XDEBUG_GIT_REVISION \"$$rev\""; \
	  echo "#define XDEBUG_SCHEMA_REVISION \"$$schema\""; \
	  echo "#define XDEBUG_BUILD_ID \"$$rev-$$schema\""; } > $@.tmp; \
	cmp -s $@.tmp $@ 2>/dev/null || mv $@.tmp $@; rm -f $@.tmp

all: $(EXE) internal-engines

internal-engines: $(LIBEXEC)/xdebug-engine

# Unified engine: engine + design helper + waveform helper objects.
UNIFIED_OBJS = $(ENGINE_OBJS) $(DESIGN_OBJS) $(WAVEFORM_OBJS)
$(LIBEXEC)/xdebug-engine: $(CORE_OBJS) $(UNIFIED_OBJS)
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -DXDEBUG_INTERNAL_ENGINE -o $@ $^ $(LDFLAGS)

$(EXE): $(CORE_OBJS) $(APP_OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^ $(LDFLAGS)

$(BUILD)/%.o: %.cpp
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(DEPFLAGS) -DXDEBUG_INTERNAL_ENGINE -c -o $@ $<

$(BUILD)/src/api/response.o: $(BUILD_INFO)

CPP_UNIT_BINARIES =

define CPP_UNIT_BINARY
CPP_UNIT_BINARIES += $(BUILD)/tests/$(1)
$(BUILD)/tests/$(1): tests/unit/$(1).cpp $(2)
	@mkdir -p $$(dir $$@)
	$$(CXX) $$(CXXFLAGS) -o $$@ $$< $(2) $(3)
endef

$(eval $(call CPP_UNIT_BINARY,test_core_types,$(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_env_config,$(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_unique_resource,,))
$(eval $(call CPP_UNIT_BINARY,test_action_log,$(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_file_exchange,$(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_process_runner,$(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_session_catalog,$(BUILD)/src/session/session_catalog.o $(BUILD)/src/core/session/session_registry_contract.o $(BUILD)/src/core/session/session_types.o $(BUILD)/src/core/common/path_utils.o $(BUILD)/src/core/common/env_config.o,))
$(eval $(call CPP_UNIT_BINARY,test_session_registry,$(BUILD)/src/engine/session/session_registry.o $(BUILD)/src/design/common/xdebug_design_paths.o $(BUILD)/src/core/session/session_registry_contract.o $(BUILD)/src/core/session/session_types.o $(BUILD)/src/core/common/path_utils.o $(BUILD)/src/core/common/env_config.o $(BUILD)/src/core/common/tool_config.o,$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_session_json_line_reader,$(BUILD)/src/engine/session/json_line_reader.o,))
$(eval $(call CPP_UNIT_BINARY,test_action_registry,$(CORE_OBJS) $(API_SUPPORT_OBJS) $(BUILD)/src/api/response.o,$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_request_contract,$(CORE_OBJS) $(API_SUPPORT_OBJS) $(BUILD)/src/api/response.o,$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_text_response_builder,$(BUILD)/src/api/text_response_builder.o $(BUILD)/src/api/xout_renderer.o $(BUILD)/src/core/value/logic_value.o,))
$(eval $(call CPP_UNIT_BINARY,test_value_collection,$(BUILD)/src/waveform/value/value_collection.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/core/value/logic_value.o,))
$(eval $(call CPP_UNIT_BINARY,test_protocol_query_filter,$(BUILD)/src/engine/service/actions/protocol/protocol_query_filter.o $(BUILD)/src/waveform/filter/value_filter.o $(BUILD)/src/core/value/logic_value.o,))
$(eval $(call CPP_UNIT_BINARY,test_protocol_statistics_filter,$(BUILD)/src/engine/service/actions/protocol/protocol_statistics_filter.o $(BUILD)/src/waveform/filter/value_filter.o $(BUILD)/src/core/value/logic_value.o $(BUILD)/src/api/text_response_builder.o,))
$(eval $(call CPP_UNIT_BINARY,test_trace_source_path_formatter,$(BUILD)/src/engine/service/trace_source_path_formatter.o $(BUILD)/src/api/text_response_builder.o $(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_trace_x_chain_identity,,))
$(eval $(call CPP_UNIT_BINARY,test_relationship_traversal,,))
$(eval $(call CPP_UNIT_BINARY,test_common_blocks,$(CORE_OBJS) $(BUILD)/src/api/text_response_builder.o $(BUILD)/src/api/xout_renderer.o,$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_contract_bound_request,$(BUILD)/src/engine/service/contract_bound_request.o,))
$(eval $(call CPP_UNIT_BINARY,test_logic_value,$(BUILD)/src/core/value/logic_value.o,))
$(eval $(call CPP_UNIT_BINARY,test_event_expr,$(BUILD)/src/waveform/event/event_expr.o $(BUILD)/src/waveform/common/expression.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/core/value/logic_value.o,))
$(eval $(call CPP_UNIT_BINARY,test_expression,$(BUILD)/src/waveform/common/expression.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/core/value/logic_value.o,))
$(eval $(call CPP_UNIT_BINARY,test_rc_generator,$(BUILD)/src/waveform/service/rc_generator.o $(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_reset_config,$(BUILD)/src/waveform/common/reset_config.o,))
$(eval $(call CPP_UNIT_BINARY,test_sha256,$(BUILD)/src/core/common/sha256.o,))
$(eval $(call CPP_UNIT_BINARY,test_axi_transaction_tracker,$(BUILD)/src/waveform/axi/axi_transaction_tracker.o $(BUILD)/src/waveform/cache/analysis_size_estimator.o,))
$(eval $(call CPP_UNIT_BINARY,test_analysis_probe,$(BUILD)/src/waveform/cache/analysis_probe.o,))
$(eval $(call CPP_UNIT_BINARY,test_analysis_repository,$(BUILD)/src/waveform/cache/analysis_repository.o $(BUILD)/src/waveform/cache/analysis_probe.o $(BUILD)/src/core/common/sha256.o,))
$(eval $(call CPP_UNIT_BINARY,test_stream_base_analysis,$(BUILD)/src/waveform/cache/analysis_size_estimator.o,))
$(eval $(call CPP_UNIT_BINARY,test_stream_manager,$(BUILD)/src/waveform/stream/stream_manager.o $(BUILD)/src/waveform/stream/stream_config.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/common/versioned_json_store.o $(BUILD)/src/waveform/common/clock_sampling.o $(BUILD)/src/waveform/common/reset_config.o $(BUILD)/src/waveform/server/fsdb_value_reader.o $(BUILD)/src/waveform/server/fsdb_scan_utils.o $(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_apb_manager,$(BUILD)/src/waveform/apb/apb_manager.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/common/versioned_json_store.o $(BUILD)/src/waveform/common/clock_sampling.o $(BUILD)/src/waveform/common/reset_config.o $(BUILD)/src/waveform/server/fsdb_value_reader.o $(BUILD)/src/waveform/server/fsdb_scan_utils.o $(CORE_OBJS),$(LDFLAGS)))
$(eval $(call CPP_UNIT_BINARY,test_cursor_manager,$(BUILD)/src/waveform/cursor/cursor_manager.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/common/versioned_json_store.o $(BUILD)/src/core/common/tool_config.o $(BUILD)/src/core/common/path_utils.o $(BUILD)/src/core/common/env_config.o,))
$(eval $(call CPP_UNIT_BINARY,test_list_manager,$(BUILD)/src/waveform/list/list_manager.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/common/versioned_json_store.o $(BUILD)/src/core/common/tool_config.o $(BUILD)/src/core/common/path_utils.o $(BUILD)/src/core/common/env_config.o,))
$(eval $(call CPP_UNIT_BINARY,test_versioned_json_store,$(BUILD)/src/waveform/common/versioned_json_store.o,))
$(eval $(call CPP_UNIT_BINARY,test_clock_sampling_event_manager,$(BUILD)/src/waveform/service/action_support.o $(BUILD)/src/waveform/service/config_support.o $(BUILD)/src/waveform/event/event_manager.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/common/versioned_json_store.o $(BUILD)/src/waveform/common/clock_sampling.o $(BUILD)/src/waveform/common/clock_sampling_response.o $(BUILD)/src/waveform/common/reset_config.o $(BUILD)/src/waveform/server/fsdb_value_reader.o $(BUILD)/src/waveform/server/fsdb_scan_utils.o $(CORE_OBJS),$(LDFLAGS)))

cpp-unit-binaries: $(CPP_UNIT_BINARIES)

clean:
	rm -rf $(BUILD) $(LIBEXEC) $(EXE)

-include $(DEPS)
