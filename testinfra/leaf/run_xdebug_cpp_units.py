#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import os
from pathlib import Path


BINARIES = (
    "test_core_types",
    "test_env_config",
    "test_unique_resource",
    "test_action_log",
    "test_file_exchange",
    "test_process_runner",
    "test_session_catalog",
    "test_session_registry",
    "test_session_json_line_reader",
    "test_action_registry",
    "test_request_contract",
    "test_text_response_builder",
    "test_value_collection",
    "test_protocol_query_filter",
    "test_protocol_statistics_filter",
    "test_trace_source_path_formatter",
    "test_trace_x_chain_identity",
    "test_common_blocks",
    "test_contract_bound_request",
    "test_typed_waveform_action_adapter",
    "test_logic_value",
    "test_event_expr",
    "test_expression",
    "test_rc_generator",
    "test_reset_config",
    "test_sha256",
    "test_axi_transaction_tracker",
    "test_analysis_probe",
    "test_analysis_repository",
    "test_stream_base_analysis",
    "test_stream_manager",
    "test_apb_manager",
    "test_cursor_manager",
    "test_list_manager",
    "test_versioned_json_store",
    "test_clock_sampling_event_manager",
    "test_relationship_traversal",
)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    xdebug_root = root / "xdebug"
    env = os.environ.copy()
    env["XVERIF_HOME"] = str(root)
    env["XVERIF_TEST_TMPDIR"] = str(root / "tmp")
    subprocess.run(["make", "-C", "xdebug", "cpp-unit-binaries"], cwd=root, env=env, check=True)
    for name in BINARIES:
        subprocess.run([str(xdebug_root / "build/tests" / name)], cwd=xdebug_root, env=env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
