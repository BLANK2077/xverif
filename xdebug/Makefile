TOP ?= ..

.DEFAULT_GOAL := all

include $(TOP)/mk/common_flags.mk

include $(TOP)/mk/npi.mk

NPI_CXXFLAGS ?=
NPI_LDFLAGS ?=
NPI_LIB ?=

BUILD_INFO = $(BUILD)/build_info.h
ACTION_METADATA = src/api/generated_action_metadata.inc
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
            src/core/process/process_runner.cpp \
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
              src/engine/session/client.cpp \
              src/engine/service/engine_action_registry.cpp \
              src/engine/service/engine_action_handler.cpp \
              src/engine/service/contract_bound_request.cpp \
              src/engine/service/trace_source_path_formatter.cpp \
              src/engine/service/actions/combined/register_combined_handlers.cpp \
              src/engine/service/actions/combined/trace_active_driver.cpp \
              src/engine/service/actions/combined/trace_active_driver_chain.cpp \
              src/engine/service/actions/combined/trace_x.cpp \
              src/engine/service/actions/design/expr_normalize.cpp \
              src/engine/service/actions/design/register_design_handlers.cpp \
              src/engine/service/actions/design/signal_canonicalize.cpp \
              src/engine/service/actions/design/signal_resolve.cpp \
              src/engine/service/actions/design/trace_driver.cpp \
              src/engine/service/actions/design/trace_load.cpp \
              src/engine/service/actions/protocol/apb_config_list.cpp \
              src/engine/service/actions/protocol/apb_config_load.cpp \
              src/engine/service/actions/protocol/apb_cursor.cpp \
              src/engine/service/actions/protocol/apb_query.cpp \
              src/engine/service/actions/protocol/apb_statistics.cpp \
              src/engine/service/actions/protocol/axi_analysis.cpp \
              src/engine/service/actions/protocol/axi_config_list.cpp \
              src/engine/service/actions/protocol/axi_config_load.cpp \
              src/engine/service/actions/protocol/axi_cursor.cpp \
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
              src/engine/service/actions/stream/stream_show.cpp \
              src/engine/service/actions/stream/stream_validate.cpp \
              src/engine/service/actions/waveform/apb_transfer_window.cpp \
              src/engine/service/actions/waveform/axi_channel_stall.cpp \
              src/engine/service/actions/waveform/axi_latency_outlier.cpp \
              src/engine/service/actions/waveform/axi_outstanding_timeline.cpp \
              src/engine/service/actions/waveform/axi_request_response_pair.cpp \
              src/engine/service/actions/waveform/clock_point_query.cpp \
              src/engine/service/actions/waveform/counter_statistics.cpp \
              src/engine/service/actions/waveform/cursor_delete.cpp \
              src/engine/service/actions/waveform/cursor_get.cpp \
              src/engine/service/actions/waveform/cursor_list.cpp \
              src/engine/service/actions/waveform/cursor_set.cpp \
              src/engine/service/actions/waveform/cursor_use.cpp \
              src/engine/service/actions/waveform/detect_abnormal.cpp \
              src/engine/service/actions/waveform/event_config_list.cpp \
              src/engine/service/actions/waveform/event_config_load.cpp \
              src/engine/service/actions/waveform/event_export.cpp \
              src/engine/service/actions/waveform/event_find.cpp \
              src/engine/service/actions/waveform/expr_eval_at.cpp \
              src/engine/service/actions/waveform/handshake_inspect.cpp \
              src/engine/service/actions/waveform/list_add.cpp \
              src/engine/service/actions/waveform/list_create.cpp \
              src/engine/service/actions/waveform/list_load.cpp \
              src/engine/service/actions/waveform/list_delete.cpp \
              src/engine/service/actions/waveform/list_diff.cpp \
              src/engine/service/actions/waveform/list_export.cpp \
              src/engine/service/actions/waveform/list_show.cpp \
              src/engine/service/actions/waveform/list_validate.cpp \
              src/engine/service/actions/waveform/rc_generate.cpp \
              src/engine/service/actions/waveform/register_waveform_handlers.cpp \
              src/engine/service/actions/waveform/sampled_pulse_inspect.cpp \
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
              src/api/xout_renderer.cpp \
              src/runtime/work_dir.cpp \
              src/combined/active_trace_service.cpp \
              src/combined/active_trace_chain.cpp


DESIGN_SRCS = src/design/service/action_support.cpp \
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
                src/waveform/common/time_spec.cpp \
                src/waveform/common/clock_sampling.cpp \
                src/waveform/common/reset_config.cpp \
                src/waveform/common/expression.cpp \
                src/waveform/cache/analysis_probe.cpp \
                src/waveform/cache/analysis_repository.cpp \
                src/waveform/cache/analysis_size_estimator.cpp \
                src/waveform/apb/apb_manager.cpp \
                src/waveform/apb/apb_analyzer.cpp \
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

$(BUILD)/%.o: %.cpp $(BUILD_INFO)
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) $(DEPFLAGS) -DXDEBUG_INTERNAL_ENGINE -c -o $@ $<

cpp-unit-binaries: $(CORE_OBJS) $(API_SUPPORT_OBJS) $(BUILD)/src/api/response.o $(BUILD)/src/api/text_response_builder.o $(BUILD)/src/api/xout_renderer.o $(BUILD)/src/waveform/service/rc_generator.o $(BUILD)/src/waveform/filter/value_filter.o $(BUILD)/src/waveform/event/event_expr.o $(BUILD)/src/waveform/common/expression.o $(BUILD)/src/waveform/common/reset_config.o $(BUILD)/src/waveform/common/clock_sampling.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/value/value_collection.o $(BUILD)/src/waveform/server/fsdb_value_reader.o $(BUILD)/src/waveform/server/fsdb_scan_utils.o $(BUILD)/src/waveform/cache/analysis_probe.o $(BUILD)/src/waveform/cache/analysis_repository.o $(BUILD)/src/waveform/cache/analysis_size_estimator.o $(BUILD)/src/waveform/stream/stream_config.o $(BUILD)/src/waveform/stream/stream_manager.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/waveform/axi/axi_transaction_tracker.o $(BUILD)/src/engine/service/actions/protocol/protocol_query_filter.o $(BUILD)/src/engine/service/actions/protocol/protocol_statistics_filter.o $(BUILD)/src/session/session_catalog.o
	mkdir -p $(BUILD)/tests
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_core_types tests/unit/test_core_types.cpp $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_env_config tests/unit/test_env_config.cpp $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_unique_resource tests/unit/test_unique_resource.cpp
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_action_log tests/unit/test_action_log.cpp $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_file_exchange tests/unit/test_file_exchange.cpp $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_process_runner tests/unit/test_process_runner.cpp $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_session_catalog tests/unit/test_session_catalog.cpp $(BUILD)/src/session/session_catalog.o $(BUILD)/src/core/common/path_utils.o $(BUILD)/src/core/common/env_config.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_action_registry tests/unit/test_action_registry.cpp $(CORE_OBJS) $(API_SUPPORT_OBJS) $(BUILD)/src/api/response.o $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_request_contract tests/unit/test_request_contract.cpp $(CORE_OBJS) $(API_SUPPORT_OBJS) $(BUILD)/src/api/response.o $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_text_response_builder tests/unit/test_text_response_builder.cpp $(BUILD)/src/api/text_response_builder.o $(BUILD)/src/api/xout_renderer.o $(BUILD)/src/core/value/logic_value.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_value_collection tests/unit/test_value_collection.cpp $(BUILD)/src/waveform/value/value_collection.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/core/value/logic_value.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_protocol_query_filter tests/unit/test_protocol_query_filter.cpp $(BUILD)/src/engine/service/actions/protocol/protocol_query_filter.o $(BUILD)/src/waveform/filter/value_filter.o $(BUILD)/src/core/value/logic_value.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_protocol_statistics_filter tests/unit/test_protocol_statistics_filter.cpp $(BUILD)/src/engine/service/actions/protocol/protocol_statistics_filter.o $(BUILD)/src/waveform/filter/value_filter.o $(BUILD)/src/core/value/logic_value.o $(BUILD)/src/api/text_response_builder.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_trace_source_path_formatter tests/unit/test_trace_source_path_formatter.cpp $(BUILD)/src/engine/service/trace_source_path_formatter.o $(BUILD)/src/api/text_response_builder.o $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_trace_x_chain_identity tests/unit/test_trace_x_chain_identity.cpp
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_common_blocks tests/unit/test_common_blocks.cpp $(CORE_OBJS) $(BUILD)/src/api/text_response_builder.o $(BUILD)/src/api/xout_renderer.o $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_logic_value tests/unit/test_logic_value.cpp $(BUILD)/src/core/value/logic_value.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_event_expr tests/unit/test_event_expr.cpp $(BUILD)/src/waveform/event/event_expr.o $(BUILD)/src/waveform/common/expression.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/core/value/logic_value.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_expression tests/unit/test_expression.cpp $(BUILD)/src/waveform/common/expression.o $(BUILD)/src/waveform/stream/stream_expr.o $(BUILD)/src/core/value/logic_value.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_rc_generator tests/unit/test_rc_generator.cpp $(BUILD)/src/waveform/service/rc_generator.o $(CORE_OBJS) $(LDFLAGS)
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_sha256 tests/unit/test_sha256.cpp $(BUILD)/src/core/common/sha256.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_axi_transaction_tracker tests/unit/test_axi_transaction_tracker.cpp $(BUILD)/src/waveform/axi/axi_transaction_tracker.o $(BUILD)/src/waveform/cache/analysis_size_estimator.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_analysis_probe tests/unit/test_analysis_probe.cpp $(BUILD)/src/waveform/cache/analysis_probe.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_analysis_repository tests/unit/test_analysis_repository.cpp $(BUILD)/src/waveform/cache/analysis_repository.o $(BUILD)/src/waveform/cache/analysis_probe.o $(BUILD)/src/core/common/sha256.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_stream_base_analysis tests/unit/test_stream_base_analysis.cpp $(BUILD)/src/waveform/cache/analysis_size_estimator.o
	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_stream_manager tests/unit/test_stream_manager.cpp $(BUILD)/src/waveform/stream/stream_manager.o $(BUILD)/src/waveform/stream/stream_config.o $(BUILD)/src/waveform/common/xdebug_waveform_paths.o $(BUILD)/src/waveform/common/clock_sampling.o $(BUILD)/src/waveform/common/reset_config.o $(BUILD)/src/waveform/server/fsdb_value_reader.o $(BUILD)/src/waveform/server/fsdb_scan_utils.o $(CORE_OBJS) $(LDFLAGS)

	$(CXX) $(CXXFLAGS) -o $(BUILD)/tests/test_reset_config tests/unit/test_reset_config.cpp $(BUILD)/src/waveform/common/reset_config.o

clean:
	rm -rf $(BUILD) $(LIBEXEC) $(EXE)

-include $(DEPS)
