from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


XDEBUG = Path(__file__).resolve().parents[2]
TOOLS = XDEBUG / "tools"


@lru_cache(maxsize=1)
def _generator() -> Any:
    sys.path.insert(0, str(TOOLS))
    path = TOOLS / "sync_runtime_request_schemas.py"
    spec = importlib.util.spec_from_file_location(
        "composite_parameter_schema_generator", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _schemas() -> dict[str, dict[str, Any]]:
    generator = _generator()
    specs = generator.action_specs()
    arg_schemas = generator.collect_arg_schemas(specs)
    generated = {
        item["name"]: generator.sync_schema(
            generator.load_json(
                generator.XDEBUG_ROOT / item["schemas"]["request"]
            ),
            item,
            arg_schemas,
        )
        for item in specs
    }
    generator.attach_strict_batch_child_envelope(generated)
    return generated


def _args_schema(action: str) -> dict[str, Any]:
    return _schemas()[action]["properties"]["args"]


def _arg_schema(action: str, name: str) -> dict[str, Any]:
    return _args_schema(action)["properties"][name]


def _valid_args(action: str, value: dict[str, Any]) -> bool:
    return Draft7Validator(_args_schema(action)).is_valid(value)


def _valid_target(action: str, value: dict[str, Any]) -> bool:
    target = _schemas()[action]["properties"]["target"]
    return Draft7Validator(target).is_valid(value)


def test_signal_containers_are_action_specific_and_nonempty() -> None:
    alias_map_actions = {
        "event.find",
        "event.export",
        "expr.eval_at",
        "verify.conditions",
        "window.verify",
    }
    array_actions = {
        "signal.anomaly.inspect",
        "list.create",
    }
    for action in alias_map_actions:
        schema = _arg_schema(action, "signals")
        assert schema["type"] == "object"
        assert schema["minProperties"] == 1
        assert schema["propertyNames"]["minLength"] == 1
        assert schema["additionalProperties"]["minLength"] == 1
        validator = Draft7Validator(schema)
        assert validator.is_valid({"v": "top.v"})
        assert not validator.is_valid([])
        assert not validator.is_valid({})
        assert not validator.is_valid({"": "top.v"})
        assert not validator.is_valid({"v": ""})

    for action in array_actions:
        schema = _arg_schema(action, "signals")
        assert schema["type"] == "array"
        assert schema["minItems"] == 1
        assert schema["uniqueItems"] is True
        validator = Draft7Validator(schema)
        assert validator.is_valid(["top.v"])
        assert not validator.is_valid({})
        assert not validator.is_valid([])
        assert not validator.is_valid([""])


def test_conditions_and_anomaly_checks_have_closed_leaf_contracts() -> None:
    verify = _arg_schema("verify.conditions", "conditions")
    window = _arg_schema("window.verify", "conditions")
    assert verify["minItems"] == 1
    assert window["minItems"] == 1
    assert set(verify["items"]["properties"]) == {"expr", "name"}
    assert set(window["items"]["properties"]) == {"expr", "mode"}
    assert verify["items"]["properties"]["expr"]["minLength"] == 1
    assert window["items"]["properties"]["expr"]["minLength"] == 1

    checks = Draft7Validator(
        _arg_schema("signal.anomaly.inspect", "checks")
    )
    assert checks.is_valid([{"type": "unknown_xz"}])
    assert checks.is_valid(
        [{"type": "glitch", "min_pulse_width": "1ns"}]
    )
    assert checks.is_valid(
        [{"type": "stuck", "min_duration": "1us"}]
    )
    assert not checks.is_valid([])
    assert not checks.is_valid(
        [{"type": "unknown_xz", "min_duration": "1us"}]
    )
    assert not checks.is_valid(
        [{"type": "glitch", "min_duration": "1us"}]
    )
    assert not checks.is_valid(
        [{"type": "glitch"}, {"type": "glitch"}]
    )


def test_counter_valid_expression_requires_nonempty_aliases_and_paths() -> None:
    counter = {
        "clock": "top.clk",
        "time_range": {"begin": "0ns"},
        "vld": {
            "expr": "valid",
            "signals": {"valid": "top.valid"},
        },
        "cnt": "top.count",
    }
    assert _valid_args("counter.statistics", counter)
    assert not _valid_args(
        "counter.statistics",
        {
            **counter,
            "vld": {
                "expr": "valid",
                "signals": {"": "top.valid"},
            },
        },
    )
    assert not _valid_args(
        "counter.statistics",
        {
            **counter,
            "vld": {
                "expr": "valid",
                "signals": {"valid": ""},
            },
        },
    )


def test_handshake_data_and_sampled_payload_controls_are_effective() -> None:
    handshake = {
        "clock": "top.clk",
        "valid": "top.valid",
        "ready": "top.ready",
    }
    assert _valid_args("protocol.handshake.inspect", handshake)
    assert not _valid_args(
        "protocol.handshake.inspect",
        {**handshake, "data": "top.data"},
    )
    assert not _valid_args(
        "protocol.handshake.inspect",
        {
            **handshake,
            "rules": {"check_data_stable_when_stalled": True},
        },
    )
    assert _valid_args(
        "protocol.handshake.inspect",
        {
            **handshake,
            "data": "top.data",
            "rules": {"check_data_stable_when_stalled": True},
        },
    )
    assert _valid_args(
        "protocol.handshake.inspect",
        {
            **handshake,
            "data": ["top.data", "top.strb"],
            "rules": {"check_data_stable_when_stalled": True},
        },
    )
    assert not _valid_args(
        "protocol.handshake.inspect",
        {
            **handshake,
            "data": [],
            "rules": {"check_data_stable_when_stalled": True},
        },
    )

    pulse = {"clock": "top.clk", "valid": "top.valid"}
    assert _valid_args("signal.sampled_pulse.inspect", pulse)
    assert not _valid_args(
        "signal.sampled_pulse.inspect",
        {
            **pulse,
            "rules": {
                "payload_changed_without_sampled_valid": "all"
            },
        },
    )
    assert _valid_args(
        "signal.sampled_pulse.inspect",
        {
            **pulse,
            "payloads": ["top.data"],
            "rules": {
                "payload_changed_without_sampled_valid": "all"
            },
        },
    )
    assert not _valid_args(
        "signal.sampled_pulse.inspect",
        {
            **pulse,
            "payload": "top.data",
        },
    )


def test_protocol_query_index_and_line_limit_can_be_combined() -> None:
    for action in ("apb.query", "axi.query"):
        base = {"name": "bus0"}
        address = {
            "mode": "exact",
            "values": ["16'h10"],
        }
        assert _valid_args(action, base)
        assert _valid_args(action, {**base, "query": {"index": 1}})
        assert _valid_args(
            action, {**base, "query": {"line_limit": 8}}
        )
        assert not _valid_args(action, {**base, "query": {}})
        assert _valid_args(
            action,
            {
                **base,
                "query": {"index": 1, "line_limit": 8},
            },
        )
        assert not _valid_args(
            action, {**base, "last": True, "query": {"index": 1}}
        )
        assert not _valid_args(
            action,
            {**base, "address": address, "addr": "16'h10"},
        )
        assert not _valid_args(action, {**base, "last": False})
        assert not _valid_args(action, {**base, "address": "0x10"})
        assert _valid_args(action, {**base, "address": address})
        assert _valid_args(
            action,
            {
                **base,
                "address": {
                    "mode": "range",
                    "begin": "16'h10",
                    "end": "16'h1f",
                },
            },
        )
        assert _valid_args(
            action,
            {
                **base,
                "address": {
                    "mode": "mask",
                    "value": "16'h10",
                    "mask": "16'hf0",
                },
            },
        )

    axi_id = {"mode": "exact", "values": ["4'h3"]}
    assert _valid_args("axi.query", {"name": "axi0", "id": axi_id})
    assert _valid_args(
        "axi.query",
        {
            "name": "axi0",
            "id": {
                "mode": "range",
                "begin": "4'h2",
                "end": "4'h5",
            },
        },
    )
    assert not _valid_args("axi.query", {"name": "axi0", "id": "4'h3"})
    assert not _valid_args(
        "axi.query",
        {
            "name": "axi0",
            "id": axi_id,
            "output": {"include_data": True},
        },
    )
    assert _valid_args(
        "axi.query",
        {
            "name": "axi0",
            "id": axi_id,
            "query": {"index": 1},
            "output": {"include_data": True},
        },
    )
    assert _valid_args(
        "axi.query",
        {
            "name": "axi0",
            "time_range": {"begin": "10ns", "end": "20ns"},
        },
    )
    assert _valid_args(
        "axi.query",
        {
            "name": "axi0",
            "query": {"channel": "aw", "handshake_time": "12ns"},
        },
    )
    assert not _valid_args(
        "axi.query",
        {
            "name": "axi0",
            "direction": "write",
            "query": {"channel": "aw", "handshake_time": "12ns"},
        },
    )


def test_apb_export_requires_complete_range_and_strict_top_level_filters() -> None:
    base = {
        "name": "apb0",
        "time_range": {"begin": "0ns", "end": "1us"},
    }
    assert _valid_args("apb.export", base)
    assert _valid_args(
        "apb.export",
        {
            **base,
            "direction": "write",
            "address": {"mode": "exact", "values": ["32'h1000"]},
            "output": {"path": "artifacts/apb", "file_format": "csv"},
        },
    )
    assert not _valid_args(
        "apb.export", {"name": "apb0", "time_range": {"begin": "0ns"}}
    )
    assert not _valid_args(
        "apb.export", {"name": "apb0", "time_range": {"end": "1us"}}
    )
    assert not _valid_args("apb.export", {**base, "address": "0x1000"})
    assert not _valid_args("apb.export", {**base, "line_limit": 8})
    assert not _valid_args(
        "apb.export", {**base, "output": {"file_format": "tsv"}}
    )
def test_list_delete_has_one_typed_selector_from_schema_to_storage() -> None:
    assert _valid_args(
        "list.delete",
        {"name": "basic", "signal": "2"},
    )
    assert _valid_args(
        "list.delete",
        {"name": "basic", "index": 1},
    )
    for invalid in (
        {"name": "basic"},
        {"name": "", "index": 1},
        {"name": "basic", "signal": ""},
        {"name": "basic", "index": "1"},
        {"name": "basic", "index": 0},
        {"name": "basic", "index": -1},
        {"name": "basic", "signal": "2", "index": 1},
    ):
        assert not _valid_args("list.delete", invalid)

    manager_header = (
        XDEBUG / "src" / "waveform" / "list" / "list_manager.h"
    ).read_text(encoding="utf-8")
    manager_source = (
        XDEBUG / "src" / "waveform" / "list" / "list_manager.cpp"
    ).read_text(encoding="utf-8")
    handler_source = (
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "waveform"
        / "list_delete.cpp"
    ).read_text(encoding="utf-8")

    assert "delete_signal_by_path(" in manager_header
    assert "delete_signal_by_one_based_index(" in manager_header
    assert "del_signal(" not in manager_header
    assert "parse_one_based_index" not in manager_source
    assert "delete_signal_by_path(" in handler_source
    assert "delete_signal_by_one_based_index(" in handler_source
    assert "list_delete_one_based_index_parser" in handler_source
    assert "get<int>()" not in handler_source


def test_signal_changes_has_one_canonical_return_mode_contract() -> None:
    generator = _generator()
    assert "aggregate_only" not in generator.collect_arg_schemas(
        generator.action_specs()
    )
    base = {"signal": "top.sig"}
    assert _valid_args("signal.changes", base)
    assert _valid_args(
        "signal.changes",
        {**base, "mode": "timeline", "line_limit": 8},
    )
    assert _valid_args(
        "signal.changes", {**base, "mode": "summary"}
    )
    assert not _valid_args(
        "signal.changes",
        {**base, "mode": "summary", "line_limit": 8},
    )
    assert not _valid_args(
        "signal.changes", {**base, "aggregate_only": True}
    )
    assert not _valid_args(
        "signal.changes", {**base, "mode": "head"}
    )
    assert not _valid_args(
        "signal.changes", {**base, "mode": "tail"}
    )

    source = (
        XDEBUG / "src" / "waveform" / "server" / "service"
        / "signal_analysis.cpp"
    ).read_text(encoding="utf-8")
    assert 'std::string("timeline")' in source
    assert 'mode == "summary"' in source
    assert 'data["mode"] = mode' in source
    assert "aggregate_only" not in source
    assert 'mode == "tail"' not in source


def test_config_sources_stream_items_and_export_options_are_closed() -> None:
    assert _valid_args(
        "apb.config.load",
        {"name": "apb0", "config_path": "apb.json"},
    )
    assert not _valid_args(
        "apb.config.load",
        {
            "name": "apb0",
            "config": {},
            "config_path": "apb.json",
        },
    )
    assert _valid_args(
        "stream.config.load", {"config_path": "streams.json"}
    )
    assert not _valid_args(
        "stream.config.load",
        {"config_path": "streams.json", "file": "other.json"},
    )
    assert not _valid_args(
        "stream.config.load",
        {"streams": []},
    )
    assert not _valid_args(
        "event.config.load",
        {"name": "evt", "config_path": ""},
    )

    item = _arg_schema("stream.config.load", "config")["properties"]["streams"]["items"]
    validator = Draft7Validator(item)
    valid = {
        "name": "req",
        "signals": {
            "clk": "top.clk",
            "vld": "top.vld",
            "data": "top.data",
        },
        "clock": "clk",
        "vld": "vld",
        "data": "data",
    }
    assert validator.is_valid(valid)
    assert not validator.is_valid({**valid, "description": ""})
    assert not validator.is_valid({**valid, "beat_fields": {}})
    assert not validator.is_valid({**valid, "unknown": "ignored"})


def test_value_format_is_centralized_and_removed_aliases_are_not_consumed() -> None:
    generator = _generator()
    assert "trace.active_driver_chain" in generator.VALUE_BEARING_ACTIONS
    schema = _arg_schema("trace.active_driver_chain", "value_format")
    assert schema["enum"] == ["hex", "bin", "dec"]
    assert schema["default"] == "hex"

    source = (TOOLS / "sync_runtime_request_schemas.py").read_text(
        encoding="utf-8"
    )
    declaration_prefix = source.split("VALUE_BEARING_ACTIONS =", 1)[0]
    assert '"value_format"' not in declaration_prefix.split(
        "RUNTIME_CONSUMER_CONTRACTS_BY_ACTION", 1
    )[1]

    stream_handler = (
        XDEBUG / "src" / "engine" / "service" / "actions" / "stream"
        / "stream_config_load.cpp"
    ).read_text(encoding="utf-8")
    stream_manager = (
        XDEBUG / "src" / "waveform" / "stream" / "stream_manager.cpp"
    ).read_text(encoding="utf-8")
    pulse_handler = (
        XDEBUG / "src" / "waveform" / "server" / "service"
        / "signal_inspect.cpp"
    ).read_text(encoding="utf-8")
    for retired in ('args["streams"]', 'args["file"]'):
        assert retired not in stream_handler
        assert retired not in stream_manager
    assert 'args["payload"]' not in pulse_handler

    for action in (
        "apb.export",
        "axi.export",
        "event.export",
        "list.export",
        "stream.export",
    ):
        output = _arg_schema(action, "output")
        output_validator = Draft7Validator(output)
        assert output_validator.is_valid({})
        assert output_validator.is_valid({"path": "artifact"})
        assert not output_validator.is_valid(
            {"file_format": output["properties"]["file_format"]["enum"][0]}
        )
    assert not _valid_args(
        "event.export",
        {
            "clock": "top.clk",
            "signals": {"valid": "top.valid"},
            "expr": "valid",
            "line_limit": 8,
            "output": {"path": "events.json"},
        },
    )
    assert not _valid_args(
        "event.export",
        {
            "clock": "top.clk",
            "signals": {"valid": "top.valid"},
            "expr": "valid",
            "line_limit": 8,
            "aggregate": {"events": False},
        },
    )


def test_time_ranges_session_transport_and_targets_are_unambiguous() -> None:
    for action, schema in _schemas().items():
        properties = schema["properties"]["args"].get("properties", {})
        if "time_range" not in properties:
            continue
        time_range = properties["time_range"]
        assert time_range["minProperties"] == 1, action
        assert time_range["properties"]["begin"]["minLength"] == 1, action
        assert time_range["properties"]["end"]["minLength"] == 1, action

    session = {"name": "case_a"}
    assert _valid_args("session.open", session)
    assert _valid_args(
        "session.open",
        {
            **session,
            "transport": "tcp",
            "bind_host": "127.0.0.1",
            "port": 0,
        },
    )
    assert not _valid_args(
        "session.open", {**session, "bind_host": "127.0.0.1"}
    )
    assert not _valid_args(
        "session.open",
        {
            **session,
            "transport": "uds",
            "host": "127.0.0.1",
        },
    )
    assert not _valid_args(
        "session.open",
        {**session, "transport": "tcp", "port": 65536},
    )
    assert _valid_target(
        "session.open",
        {"fsdb": "waves.fsdb", "run_manifest": "run.json"},
    )
    assert not _valid_target(
        "session.open",
        {"daidir": "simv.daidir", "run_manifest": "run.json"},
    )

    assert _valid_target("trace.driver", {"session_id": "case"})
    assert _valid_target("trace.driver", {"daidir": "simv.daidir"})
    assert not _valid_target(
        "trace.driver",
        {"session_id": "case", "daidir": "simv.daidir"},
    )
    assert _valid_target(
        "trace.active_driver",
        {"daidir": "simv.daidir", "fsdb": "waves.fsdb"},
    )
    assert not _valid_target(
        "trace.active_driver", {"daidir": "simv.daidir"}
    )
    assert not _valid_target(
        "trace.active_driver",
        {
            "session_id": "case",
            "daidir": "simv.daidir",
            "fsdb": "waves.fsdb",
        },
    )
    assert _valid_target("scope.roots", {"fsdb": "waves.fsdb"})
    assert _valid_target(
        "scope.roots",
        {"daidir": "simv.daidir", "fsdb": "waves.fsdb"},
    )
    assert not _valid_target(
        "scope.roots",
        {"session_id": "case", "fsdb": "waves.fsdb"},
    )


AUDITED_BROAD_CONSUMER_FILES = {
    "api/dispatcher.cpp": "catalog/batch/session target envelope dispatch",
    "engine/service/actions/combined/trace_x_origin.cpp": "closed limits object",
    "engine/service/actions/protocol/apb_config_load.cpp": "strict APB config parser",
    "engine/service/actions/protocol/apb_export.cpp": "closed APB export/filter/output parser",
    "engine/service/actions/protocol/apb_query.cpp": "closed APB query and filter parser",
    "engine/service/actions/protocol/apb_statistics.cpp": "closed APB statistics filter",
    "engine/service/actions/protocol/axi_config_load.cpp": "strict AXI config parser",
    "engine/service/actions/protocol/axi_query.cpp": "closed AXI query and filter parser",
    "engine/service/actions/protocol/axi_statistics.cpp": "closed AXI statistics filter",
    "engine/service/actions/stream/stream_config_load.cpp": "strict stream config parser",
    "engine/service/actions/stream/stream_query.cpp": "closed stream field filter",
    "engine/service/actions/waveform/apb_transfer_window.cpp": "action-specific closed args",
    "engine/service/actions/waveform/axi_channel_stall.cpp": "action-specific closed args",
    "engine/service/actions/waveform/axi_latency_outlier.cpp": "action-specific closed args",
    "engine/service/actions/waveform/axi_outstanding_timeline.cpp": "action-specific closed args",
    "engine/service/actions/waveform/axi_request_response_pair.cpp": "action-specific closed args",
    "engine/service/actions/waveform/counter_statistics.cpp": "closed vld/time contracts",
    "engine/service/actions/waveform/event_export.cpp": "strict signals/group_by parsers",
    "engine/service/actions/waveform/event_find.cpp": "strict inline signals parser",
    "engine/service/actions/waveform/expr_eval_at.cpp": "strict alias map parser",
    "engine/service/actions/waveform/list_create.cpp": "strict signal list parser",
    "engine/service/actions/waveform/list_load.cpp": "list_load_config_parser",
    "engine/service/actions/waveform/list_delete.cpp": "typed list selector parser",
    "engine/service/actions/waveform/protocol_handshake_inspect.cpp": "strict data/rules parser",
    "engine/service/actions/waveform/signal_anomaly_inspect.cpp": "type-specific checks parser",
    "engine/service/actions/waveform/signal_changes.cpp": "closed time/output args",
    "engine/service/actions/waveform/signal_sampled_pulse_inspect.cpp": "strict payload/rules parser",
    "engine/service/actions/waveform/scope_list.cpp": "closed include/exclude glob lists",
    "engine/service/actions/waveform/signal_stability.cpp": "closed time-range args",
    "engine/service/actions/waveform/signal_statistics.cpp": "closed sampling args",
    "engine/service/actions/waveform/signal_xz_verify.cpp": "closed verification args",
    "engine/service/actions/waveform/value_at.cpp": "strict ordered multi-time parser",
    "engine/service/actions/waveform/verify_conditions.cpp": "strict condition/alias parsers",
    "engine/service/actions/waveform/waveform_cursor_delete.cpp": "closed cursor args",
    "engine/service/actions/waveform/waveform_cursor_get.cpp": "closed cursor args",
    "engine/service/actions/waveform/waveform_cursor_list.cpp": "closed cursor args",
    "engine/service/actions/waveform/waveform_cursor_set.cpp": "closed cursor args",
    "engine/service/actions/waveform/waveform_cursor_use.cpp": "closed cursor args",
    "engine/service/actions/waveform/window_verify.cpp": "strict condition/alias parsers",
}


def test_every_broad_runtime_consumer_is_in_the_audit_matrix() -> None:
    source_root = XDEBUG / "src"
    candidates = [source_root / "api" / "dispatcher.cpp"]
    candidates.extend(
        (source_root / "engine" / "service" / "actions").rglob("*.cpp")
    )
    actual = {
        path.relative_to(source_root).as_posix()
        for path in candidates
        if "consume_subtree(" in path.read_text(encoding="utf-8")
        or "consume_args_request(" in path.read_text(encoding="utf-8")
    }
    assert actual == set(AUDITED_BROAD_CONSUMER_FILES)
    assert all(AUDITED_BROAD_CONSUMER_FILES.values())


def test_strict_external_parsers_and_manifest_canonicalization_are_present() -> None:
    config_support = (
        XDEBUG / "src" / "waveform" / "service" / "config_support.cpp"
    ).read_text(encoding="utf-8")
    stream_config = (
        XDEBUG / "src" / "waveform" / "stream" / "stream_config.cpp"
    ).read_text(encoding="utf-8")
    stream_manager = (
        XDEBUG / "src" / "waveform" / "stream" / "stream_manager.cpp"
    ).read_text(encoding="utf-8")
    stream_query = (
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "stream"
        / "stream_query.cpp"
    ).read_text(encoding="utf-8")
    handshake = (
        XDEBUG
        / "src"
        / "waveform"
        / "server"
        / "service"
        / "signal_inspect.cpp"
    ).read_text(encoding="utf-8")
    signal_analysis = (
        XDEBUG
        / "src"
        / "waveform"
        / "server"
        / "service"
        / "signal_analysis.cpp"
    ).read_text(encoding="utf-8")
    event_export = (
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "waveform"
        / "event_export.cpp"
    ).read_text(encoding="utf-8")
    axi_query = (
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "protocol"
        / "axi_query.cpp"
    ).read_text(encoding="utf-8")
    dispatcher = (
        XDEBUG / "src" / "api" / "dispatcher.cpp"
    ).read_text(encoding="utf-8")

    assert "config contains unknown field" in config_support
    assert "event signal aliases and paths must be non-empty" in config_support
    assert "stream config contains unknown field" in stream_config
    assert "must contain exactly one root field: streams" in stream_manager
    assert "parse_options.require_nonzero_mask = true" in stream_query
    assert 'signals["data0"] = path' in handshake
    assert "has_data != check_data" in handshake
    assert "args.vld.signals contains alias not used by expr" in signal_analysis
    assert "args.signals contains alias unused by every condition" in signal_analysis
    assert "unknown event group_by name" in event_export
    assert "parse_protocol_query_filter" in axi_query
    assert "match_protocol_query_filter" in axi_query
    assert "transaction.addr_time" in axi_query
    assert "manifest_object_has_only" in dispatcher
    assert "valid_manifest_sha256" in dispatcher
    assert "resources must exactly match target.fsdb" in dispatcher
    assert 'details = {' in dispatcher
