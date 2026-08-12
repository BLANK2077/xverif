from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft7Validator, Draft202012Validator


XDEBUG = Path(__file__).resolve().parents[2]


def _module(name: str):
    path = XDEBUG / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"xdebug_static_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _action_entries() -> dict[str, dict[str, object]]:
    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    return {entry["name"]: entry for entry in catalog["actions"]}


def _generated_response_schema(action: str) -> dict[str, object]:
    generator = _module("sync_response_schemas")
    return generator.response_schema(_action_entries()[action])


def _response_example(name: str) -> dict[str, object]:
    return json.loads(
        (XDEBUG / "examples/responses" / name).read_text(
            encoding="utf-8"
        )
    )


def _request_schema_and_example(
    entry: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    schemas = entry["schemas"]
    examples = entry["examples"]
    assert isinstance(schemas, dict)
    assert isinstance(examples, dict)
    request_examples = examples["request"]
    assert isinstance(request_examples, list) and request_examples
    return (
        json.loads(
            (XDEBUG / schemas["request"]).read_text(encoding="utf-8")
        ),
        json.loads(
            (XDEBUG / request_examples[0]).read_text(encoding="utf-8")
        ),
    )


def test_trace_active_driver_chain_schema_accepts_runtime_width_summary() -> None:
    response = _response_example("trace.active_driver_chain.basic.json")
    response["summary"]["value_width_complete"] = True
    response["summary"]["width_diagnostics"] = []
    Draft7Validator(
        _generated_response_schema("trace.active_driver_chain")
    ).validate(response)


def _discover_frontend_runtime_consumers() -> dict[str, str]:
    action_catalog = (
        XDEBUG / "src" / "api" / "action_catalog.cpp"
    ).read_text(encoding="utf-8")
    dispatcher = (
        XDEBUG / "src" / "api" / "dispatcher.cpp"
    ).read_text(encoding="utf-8")
    engine_query = (
        XDEBUG / "src" / "engine" / "engine_query.cpp"
    ).read_text(encoding="utf-8")

    frontend_functions = {
        "actions": (
            action_catalog,
            "Json catalog_actions_response(const Json& request)",
            "catalog_actions_response",
            "xdebug::catalog_actions_response(const Json&)",
        ),
        "schema": (
            action_catalog,
            "Json catalog_schema_response(const Json& request)",
            "catalog_schema_response",
            "xdebug::catalog_schema_response(const Json&)",
        ),
        "batch": (
            dispatcher,
            "Json Dispatcher::handle_batch(const Json& request,",
            "handle_batch",
            "xdebug::Dispatcher::handle_batch(const Json&, const Json&)",
        ),
    }
    actual: dict[str, str] = {}
    for action, (
        source,
        signature,
        call_name,
        consumer_id,
    ) in frontend_functions.items():
        assert signature in source
        assert re.search(
            rf'handler_kind == "{re.escape(action)}".*?'
            rf"{re.escape(call_name)}\(request",
            dispatcher,
            re.DOTALL,
        )
        actual[action] = consumer_id

    dispatcher_session = dispatcher.split(
        "Json Dispatcher::handle_session(", 1
    )[1].split("\nJson Dispatcher::dispatch_impl(", 1)[0]
    for action in ("session.list", "session.gc"):
        assert f'if (action == "{action}")' in dispatcher_session
        actual[action] = (
            f"xdebug::Dispatcher::handle_session[action={action}]"
        )
    assert 'if (action == "session.close")' in dispatcher_session
    actual["session.close"] = (
        "xdebug::Dispatcher::handle_session[action=session.close]"
    )

    session_consumer = engine_query.split(
        "OrderedJson handle_session_action(", 1
    )[1].split(
        "\nOrderedJson handle_engine_forward(", 1
    )[0]
    assert "ContractBoundRequest& bound_request" in session_consumer
    for action in ("session.open", "session.doctor", "session.close"):
        assert f'if (action == "{action}")' in session_consumer
        actual[action] = (
            "xdebug/src/engine/engine_query.cpp"
            f"::handle_session_action[action={action}]"
            "(ContractBoundRequest&)"
        )
    assert "request_transport_options(bound_request)" in session_consumer
    assert "request_session_name(bound_request)" in session_consumer
    return actual


def _discover_engine_runtime_consumers(
    engine_actions: set[str],
) -> dict[str, str]:
    handler_root = XDEBUG / "src" / "engine" / "service" / "actions"
    registration_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(handler_root.rglob("register_*_handlers.cpp"))
    )
    registered_factories = set(
        re.findall(
            r"r\.add\((make_[A-Za-z0-9_]+_handler)\(\)\);",
            registration_source,
        )
    )
    run_signature = re.compile(
        r"\bJson\s+run\s*\(\s*"
        r"ContractBoundRequest\s*&\s*(?P<request>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*,",
        re.DOTALL,
    )
    literal_action = re.compile(
        r"const char\*\s+action_name\(\)\s+const\s+override\s*"
        r'\{\s*return\s+"([^"]+)"\s*;\s*\}'
    )
    conditional_action = re.compile(
        r"const char\*\s+action_name\(\)\s+const\s+override\s*"
        r'\{\s*return\s+[A-Za-z0-9_]+\s*\?\s*"([^"]+)"'
        r'\s*:\s*"([^"]+)"\s*;\s*\}'
    )
    actual: dict[str, str] = {}

    for source in sorted(handler_root.rglob("*.cpp")):
        text = source.read_text(encoding="utf-8")
        if not re.search(r"\bJson\s+run\s*\(", text):
            continue

        run_matches = list(run_signature.finditer(text))
        assert len(run_matches) == 1, source
        request_name = re.escape(run_matches[0].group("request"))
        raw_args_extraction = re.compile(
            rf"\b{request_name}\s*(?:"
            r'\.value\s*\(\s*"args"'
            r'|\[\s*"args"\s*\]'
            r'|\.at\s*\(\s*"args"'
            r")"
        )
        assert raw_args_extraction.search(text) is None, source
        assert re.search(
            r"\bJson\s+run\s*\(\s*(?:const\s+)?Json\b",
            text,
            re.DOTALL,
        ) is None, source

        factories = re.findall(
            r"std::unique_ptr<EngineActionHandler>\s+"
            r"(make_[A-Za-z0-9_]+_handler)\(\)\s*\{",
            text,
        )
        assert len(factories) == 1, source
        factory = factories[0]
        assert factory in registered_factories, source

        literal_match = literal_action.search(text)
        if literal_match is not None:
            action = literal_match.group(1)
        else:
            conditional_match = conditional_action.search(text)
            if conditional_match is not None:
                factory_flag = re.search(
                    rf"{re.escape(factory)}\(\)\s*\{{.*?"
                    r"new\s+[A-Za-z0-9_]+\((true|false)\)",
                    text,
                    re.DOTALL,
                )
                assert factory_flag is not None, source
                action = conditional_match.group(
                    1 if factory_flag.group(1) == "true" else 2
                )
            else:
                factory_body = text.split(f"{factory}()", 1)[1]
                candidates = (
                    set(
                        re.findall(
                            r'new\s+[A-Za-z0-9_]+\(\s*"([^"]+)"',
                            factory_body,
                        )
                    )
                    & engine_actions
                )
                assert len(candidates) == 1, source
                action = next(iter(candidates))

        assert action in engine_actions, source
        assert action not in actual, action
        actual[action] = (
            f"EngineActionRegistry[action={action}]"
            "::run(ContractBoundRequest)"
        )

    assert registered_factories
    assert set(actual) == engine_actions
    assert len(registered_factories) == len(engine_actions)
    return actual


def test_schema_files() -> None:
    assert _module("validate_schema").main(["validate_schema", str(XDEBUG / "schemas/v1")]) == 0


def test_examples_match_action_schemas() -> None:
    assert _module("validate_examples").main(
        ["validate_examples", str(XDEBUG / "examples"), str(XDEBUG / "schemas/v1")]
    ) == 0


def test_all_response_schemas_are_generated_and_synced() -> None:
    assert _module("sync_response_schemas").main(["--check"]) == 0


def test_public_response_envelope_requires_runtime_owned_fields() -> None:
    generator = _module("sync_response_schemas")
    required = {
        "api_version",
        "ok",
        "action",
        "tool",
        "session",
        "summary",
        "data",
        "error",
    }
    for entry in generator.load_action_entries():
        schema = generator.response_schema(entry)
        assert required <= set(schema["required"]), entry["name"]
        for branch in schema["oneOf"]:
            assert required <= set(branch["required"]), entry["name"]

    generic = generator.generic_error_response_schema()
    assert required <= set(generic["required"])


def test_response_schema_generator_has_no_duplicate_literal_dict_keys() -> None:
    path = XDEBUG / "tools/sync_response_schemas.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    duplicates: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        ]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            duplicates.append((node.lineno, repeated))
    assert duplicates == []


def test_output_notes_only_name_fields_declared_by_success_schema() -> None:
    generator = _module("sync_response_schemas")
    completeness = set(generator.completeness_properties())
    actions_without_completeness: list[str] = []
    for entry in generator.load_action_entries():
        schema = generator.response_schema(entry)
        declared = {
            location: set(
                generator.schema_object_fields(
                    schema["$defs"][definition]
                )
            )
            for location, definition in (
                ("summary", "successSummary"),
                ("data", "successData"),
            )
        }
        mentioned = {
            (location, field)
            for location, field in re.findall(
                r"\b(summary|data)\.([A-Za-z_][A-Za-z0-9_]*)\b",
                schema["x-output_notes"],
            )
        }
        expected = {
            (location, field)
            for location, fields in declared.items()
            for field in fields
        }
        assert mentioned == expected, entry["name"]

        actual_completeness = {
            (location, field)
            for location, fields in declared.items()
            for field in completeness & fields
        }
        mentioned_completeness = {
            item for item in mentioned if item[1] in completeness
        }
        assert mentioned_completeness == actual_completeness, entry["name"]
        if not actual_completeness:
            actions_without_completeness.append(entry["name"])
    assert actions_without_completeness


def test_sampling_union_witnesses_are_registered_symmetrically() -> None:
    expected = {
        "counter.statistics": {
            "counter.statistics.basic.json",
            "counter.statistics.no_value.json",
        },
        "event.find": {
            "event.find.basic.json",
            "event.find.zero.json",
        },
        "event.export": {
            "event.export.basic.json",
            "event.export.zero.json",
            "event.export.aggregate_only.json",
            "event.export.artifact.json",
        },
        "expr.eval_at": {
            "expr.eval_at.basic.json",
            "expr.eval_at.false.json",
            "expr.eval_at.unknown.json",
        },
        "protocol.handshake.inspect": {
            "protocol.handshake.inspect.basic.json",
            "protocol.handshake.inspect.intervals.json",
            "protocol.handshake.inspect.all.json",
        },
        "signal.sampled_pulse.inspect": {
            "signal.sampled_pulse.inspect.basic.json",
            "signal.sampled_pulse.inspect.boundary_payload.json",
            "signal.sampled_pulse.inspect.sampled_high.json",
        },
        "signal.statistics": {
            "signal.statistics.basic.json",
            "signal.statistics.raw.json",
            "signal.statistics.clock_unknown.json",
            "signal.statistics.clock_no_transition.json",
            "signal.statistics.raw_empty.json",
        },
        "value.at": {
            "value.at.basic.json",
            "value.at.clock.json",
            "value.at.unknown.json",
            "value.at.clock_unknown.json",
            "value.at.missing_value.json",
            "value.at.xbit.json",
            "value.at.list.json",
        },
        "verify.conditions": {
            "verify.conditions.basic.json",
            "verify.conditions.unknown.json",
        },
        "window.verify": {
            "window.verify.basic.json",
            "window.verify.incomplete.json",
            "window.verify.empty.json",
        },
    }
    entries = _action_entries()
    for action, required_names in expected.items():
        request_names = {
            Path(path).name
            for path in entries[action]["examples"]["request"]
        }
        response_names = {
            Path(path).name
            for path in entries[action]["examples"]["response"]
        }
        assert request_names == response_names, action
        assert required_names <= response_names, action

    expr_statuses = {
        _response_example(name)["summary"]["status"]
        for name in expected["expr.eval_at"]
    }
    assert expr_statuses == {"true", "false", "unknown"}

    value_variants = {
        (
            response["summary"]["sampling_mode"],
            cell["status"],
            cell.get("value", {}).get("known", False),
        )
        for name in expected["value.at"]
        for response in [_response_example(name)]
        for sample in response["data"]["samples"]
        for cell in sample["values"]
    }
    assert {
        ("raw_time", "ok", True),
        ("raw_time", "ok", False),
        ("clock_sampled", "ok", True),
        ("clock_sampled", "ok", False),
        ("clock_sampled", "missing_value", False),
    } <= value_variants

    sampled_high_counts = {
        _response_example(name)["summary"]["sampled_high_cycles"]
        for name in expected["signal.sampled_pulse.inspect"]
    }
    assert 0 in sampled_high_counts
    assert any(count > 0 for count in sampled_high_counts)


def test_config_load_recommendations_are_exact_and_actionable() -> None:
    expected = {
        "list.load": [
            "value.at",
            "list.show",
            "list.validate",
            "list.first_change",
            "list.export",
        ],
        "apb.config.load": [
            "value.at",
            "apb.query",
            "apb.export",
            "apb.transaction.cursor",
            "apb.statistics",
            "apb.transfer_window",
        ],
        "stream.config.load": [
            "value.at",
            "stream.describe",
            "stream.validate",
            "stream.query",
            "stream.export",
        ],
        "axi.config.load": [
            "value.at",
            "axi.query",
            "axi.transaction.cursor",
            "axi.analysis",
            "axi.statistics",
            "axi.export",
            "axi.channel_stall",
            "axi.latency_outlier",
            "axi.outstanding_timeline",
            "axi.request_response_pair",
        ],
    }
    entries = _action_entries()
    for action, recommendation_names in expected.items():
        assert entries[action]["recommended_actions"] == recommendation_names
        for path in entries[action]["examples"]["response"]:
            response = json.loads(
                (XDEBUG / path).read_text(encoding="utf-8")
            )
            recommendations = response["data"]["recommended_actions"]
            assert [
                item["action"] for item in recommendations
            ] == recommendation_names
            assert all(
                set(item) == {"action", "purpose"}
                and item["purpose"]
                for item in recommendations
            )


def test_sampling_response_contracts_are_shared_closed_and_conditional() -> None:
    generator = _module("sync_response_schemas")
    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    schemas = {
        entry["name"]: json.loads(
            (XDEBUG / entry["schemas"]["response"]).read_text(
                encoding="utf-8"
            )
        )
        for entry in catalog["actions"]
    }

    def contains_ref(node: object, reference: str) -> bool:
        if isinstance(node, dict):
            if node.get("$ref") == reference:
                return True
            return any(
                contains_ref(value, reference)
                for value in node.values()
            )
        if isinstance(node, list):
            return any(
                contains_ref(value, reference)
                for value in node
            )
        return False

    actual_clock_context_actions = {
        action
        for action, schema in schemas.items()
        if contains_ref(
            schema["$defs"]["successData"],
            "#/$defs/clockContext",
        )
    }
    actual_sampling_contract_actions = {
        action
        for action, schema in schemas.items()
        if contains_ref(
            schema["$defs"]["successData"],
            "#/$defs/samplingContract",
        )
    }
    assert actual_clock_context_actions == generator.CLOCK_CONTEXT_ACTIONS
    assert (
        actual_sampling_contract_actions
        == generator.SAMPLING_CONTRACT_ACTIONS
    )

    applicable = (
        generator.CLOCK_CONTEXT_ACTIONS
        | generator.SAMPLING_CONTRACT_ACTIONS
    )
    canonical_definitions = None
    for action in sorted(applicable):
        definitions = schemas[action]["$defs"]
        sampling_definitions = {
            name: definitions[name]
            for name in (
                "samplingSelection",
                "samplingContract",
                "clockContext",
            )
        }
        if canonical_definitions is None:
            canonical_definitions = sampling_definitions
        else:
            assert sampling_definitions == canonical_definitions
        for name, definition in sampling_definitions.items():
            assert definition["type"] == "object", (action, name)
            assert definition["additionalProperties"] is False, (
                action,
                name,
            )

    value_clock = json.loads(
        (
            XDEBUG / "examples/responses/value.at.clock.json"
        ).read_text(encoding="utf-8")
    )
    value_validator = Draft202012Validator(schemas["value.at"])
    value_validator.validate(value_clock)

    unknown_context_field = json.loads(json.dumps(value_clock))
    unknown_context_field["data"]["samples"][0]["clock_context"]["typo"] = True
    assert not value_validator.is_valid(unknown_context_field)

    posedge_default = json.loads(json.dumps(value_clock))
    context = posedge_default["data"]["samples"][0]["clock_context"]
    context["requested_sampling"]["sample_point"] = None
    context["effective_sampling"]["sample_point"] = "before"
    value_validator.validate(posedge_default)

    explicit_mismatch = json.loads(json.dumps(value_clock))
    explicit_mismatch["data"]["samples"][0]["clock_context"][
        "effective_sampling"
    ]["sample_point"] = "before"
    assert not value_validator.is_valid(explicit_mismatch)

    dual_default = json.loads(json.dumps(posedge_default))
    dual_default["data"]["samples"][0]["clock_context"][
        "requested_sampling"
    ]["edge"] = "dual"
    dual_default["data"]["samples"][0]["clock_context"][
        "effective_sampling"
    ]["edge"] = "dual"
    value_validator.validate(dual_default)

    dual_explicit = json.loads(json.dumps(value_clock))
    dual_explicit["data"]["samples"][0]["clock_context"][
        "requested_sampling"
    ]["edge"] = "dual"
    dual_explicit["data"]["samples"][0]["clock_context"][
        "effective_sampling"
    ]["edge"] = "dual"
    value_validator.validate(dual_explicit)
    dual_negedge = json.loads(json.dumps(dual_explicit))
    dual_negedge_context = dual_negedge["data"]["samples"][0]["clock_context"]
    dual_negedge_context["clock_edge_kind"] = "negedge"
    dual_negedge_context["requested_target_edge_hit"] = True
    value_validator.validate(dual_negedge)
    dual_negedge_context["requested_target_edge_hit"] = False
    assert not value_validator.is_valid(dual_negedge)

    no_actual_edge = json.loads(json.dumps(value_clock))
    no_actual_edge_context = no_actual_edge["data"]["samples"][0]["clock_context"]
    no_actual_edge_context["clock_edge_kind"] = None
    no_actual_edge_context["requested_any_edge_hit"] = False
    no_actual_edge_context["requested_target_edge_hit"] = False
    value_validator.validate(no_actual_edge)
    null_kind_with_any_hit = json.loads(json.dumps(no_actual_edge))
    null_kind_with_any_hit["data"]["samples"][0]["clock_context"][
        "requested_any_edge_hit"
    ] = True
    assert not value_validator.is_valid(null_kind_with_any_hit)
    null_kind_with_target_hit = json.loads(json.dumps(no_actual_edge))
    null_kind_with_target_hit["data"]["samples"][0]["clock_context"][
        "requested_target_edge_hit"
    ] = True
    assert not value_validator.is_valid(null_kind_with_target_hit)

    nonmatching_actual_edge = json.loads(json.dumps(value_clock))
    nonmatching_context = nonmatching_actual_edge["data"]["samples"][0]["clock_context"]
    nonmatching_context["clock_edge_kind"] = "negedge"
    nonmatching_context["requested_target_edge_hit"] = False
    value_validator.validate(nonmatching_actual_edge)
    nonmatching_context["requested_target_edge_hit"] = True
    assert not value_validator.is_valid(nonmatching_actual_edge)
    nonnull_kind_without_any_hit = json.loads(json.dumps(value_clock))
    nonnull_kind_without_any_hit["data"]["samples"][0]["clock_context"][
        "requested_any_edge_hit"
    ] = False
    assert not value_validator.is_valid(nonnull_kind_without_any_hit)

    reason_on_applied_sampling = json.loads(json.dumps(value_clock))
    reason_on_applied_sampling["data"]["samples"][0]["clock_context"][
        "sample_point_not_applied_reason"
    ] = generator.NEGEDGE_SAMPLE_POINT_REASON
    assert not value_validator.is_valid(reason_on_applied_sampling)

    incomplete_true_bracket = json.loads(json.dumps(value_clock))
    incomplete_true_bracket["data"]["samples"][0]["clock_context"][
        "previous_sample_time"
    ] = None
    assert not value_validator.is_valid(incomplete_true_bracket)
    complete_false_bracket = json.loads(json.dumps(value_clock))
    complete_false_bracket["data"]["samples"][0]["clock_context"][
        "bracket_complete"
    ] = False
    assert not value_validator.is_valid(complete_false_bracket)
    incomplete_false_bracket = json.loads(
        json.dumps(complete_false_bracket)
    )
    incomplete_false_bracket["data"]["samples"][0]["clock_context"][
        "next_sample_time"
    ] = None
    value_validator.validate(incomplete_false_bracket)
    empty_time_in_false_bracket = json.loads(
        json.dumps(incomplete_false_bracket)
    )
    empty_time_in_false_bracket["data"]["samples"][0]["clock_context"][
        "previous_sample_time"
    ] = ""
    assert not value_validator.is_valid(empty_time_in_false_bracket)

    sampling_response = json.loads(
        (
            XDEBUG
            / "examples/responses/signal.sampled_pulse.inspect.basic.json"
        ).read_text(encoding="utf-8")
    )
    sampling_validator = Draft202012Validator(
        schemas["signal.sampled_pulse.inspect"]
    )
    sampling_validator.validate(sampling_response)
    unknown_sampling_field = json.loads(
        json.dumps(sampling_response)
    )
    unknown_sampling_field["data"]["sampling"]["typo"] = True
    assert not sampling_validator.is_valid(unknown_sampling_field)


def test_raw_and_clock_sampling_response_variants_cannot_cross_pair() -> None:
    pairs = {
        "value.at": ("value.at.basic.json", "value.at.clock.json"),
        "signal.statistics": (
            "signal.statistics.raw.json",
            "signal.statistics.basic.json",
        ),
    }
    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    entries = {entry["name"]: entry for entry in catalog["actions"]}
    for action, (raw_name, clock_name) in pairs.items():
        schema = json.loads(
            (
                XDEBUG / entries[action]["schemas"]["response"]
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema)
        raw = json.loads(
            (
                XDEBUG / "examples/responses" / raw_name
            ).read_text(encoding="utf-8")
        )
        clock = json.loads(
            (
                XDEBUG / "examples/responses" / clock_name
            ).read_text(encoding="utf-8")
        )
        validator.validate(raw)
        validator.validate(clock)

        raw_summary_clock_data = json.loads(json.dumps(raw))
        raw_summary_clock_data["data"] = clock["data"]
        assert not validator.is_valid(raw_summary_clock_data), action

        clock_summary_raw_data = json.loads(json.dumps(clock))
        clock_summary_raw_data["data"] = raw["data"]
        assert not validator.is_valid(clock_summary_raw_data), action


def test_sampling_selection_has_one_owner_in_success_responses() -> None:
    generator = _module("sync_response_schemas")
    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    entries = {entry["name"]: entry for entry in catalog["actions"]}
    for action in sorted(generator.SAMPLING_CONTRACT_ACTIONS):
        for relative in entries[action]["examples"]["response"]:
            response = json.loads(
                (XDEBUG / relative).read_text(encoding="utf-8")
            )
            if not response["ok"]:
                continue
            summary = response["summary"]
            if summary.get("sampling_mode") != "clock_edge":
                continue
            assert "edge" not in summary, (action, relative)
            assert "sample_point" not in summary, (action, relative)
            assert "sampling" in response["data"], (
                action,
                relative,
            )
    for action in sorted(generator.CLOCK_CONTEXT_ACTIONS):
        for relative in entries[action]["examples"]["response"]:
            response = json.loads(
                (XDEBUG / relative).read_text(encoding="utf-8")
            )
            context = response.get("data", {}).get("clock_context")
            if context is not None:
                assert "edge" not in context, (action, relative)


def test_clock_sampled_summary_literals_cannot_drift_from_sampling_data() -> None:
    generator = _module("sync_response_schemas")
    entries = _action_entries()
    for action in sorted(generator.SAMPLING_CONTRACT_ACTIONS):
        validator = Draft202012Validator(
            generator.response_schema(entries[action])
        )
        for relative in entries[action]["examples"]["response"]:
            response = json.loads(
                (XDEBUG / relative).read_text(encoding="utf-8")
            )
            if (
                not response["ok"]
                or response["summary"].get("sampling_mode")
                != "clock_edge"
            ):
                continue
            validator.validate(response)
            wrong_mode = json.loads(json.dumps(response))
            wrong_mode["summary"]["sampling_mode"] = "clock_sampled"
            assert not validator.is_valid(wrong_mode), (
                action,
                relative,
                "sampling_mode",
            )
            wrong_semantics = json.loads(json.dumps(response))
            wrong_semantics["summary"][
                "sample_time_semantics"
            ] = "time is request_time"
            assert not validator.is_valid(wrong_semantics), (
                action,
                relative,
                "sample_time_semantics",
            )


def test_event_counter_and_signal_empty_branches_are_predicate_closed() -> None:
    cases = {
        "event.find": (
            "event.find.basic.json",
            "event.find.zero.json",
        ),
        "event.export": (
            "event.export.basic.json",
            "event.export.zero.json",
        ),
        "counter.statistics": (
            "counter.statistics.basic.json",
            "counter.statistics.no_value.json",
        ),
        "signal.statistics": (
            "signal.statistics.basic.json",
            "signal.statistics.clock_unknown.json",
        ),
    }
    validators = {
        action: Draft202012Validator(
            _generated_response_schema(action)
        )
        for action in cases
    }
    for action, names in cases.items():
        for name in names:
            validators[action].validate(_response_example(name))

    event_find = validators["event.find"]
    event_positive = _response_example("event.find.basic.json")
    event_zero = _response_example("event.find.zero.json")
    zero_with_first = json.loads(json.dumps(event_zero))
    zero_with_first["summary"]["first"] = "0ns"
    zero_with_first["summary"]["last"] = "0ns"
    assert not event_find.is_valid(zero_with_first)
    positive_without_first = json.loads(json.dumps(event_positive))
    positive_without_first["summary"].pop("first")
    assert not event_find.is_valid(positive_without_first)
    zero_with_event = json.loads(json.dumps(event_zero))
    zero_with_event["data"]["events"] = event_positive["data"]["events"]
    assert not event_find.is_valid(zero_with_event)
    event_without_fields = json.loads(json.dumps(event_positive))
    event_without_fields["data"]["events"][0].pop("fields")
    assert not event_find.is_valid(event_without_fields)
    multi_alias_event = json.loads(json.dumps(event_positive))
    multi_alias_event["data"]["events"][0]["signals"][
        "caller_defined_alias"
    ] = {
        "value": "1'b0",
        "known": True,
        "width": 1,
        "bits": "0",
    }
    multi_alias_event["data"]["events"][0]["fields"]["opcode"] = {
        "value": "3'b101",
        "known": True,
        "width": 3,
        "bits": "101",
    }
    event_find.validate(multi_alias_event)
    event_outer_typo = json.loads(json.dumps(event_positive))
    event_outer_typo["data"]["events"][0]["typo"] = True
    assert not event_find.is_valid(event_outer_typo)
    event_value_typo = json.loads(json.dumps(event_positive))
    event_value_typo["data"]["events"][0]["signals"]["valid"][
        "typo"
    ] = True
    assert not event_find.is_valid(event_value_typo)

    event_export = validators["event.export"]
    aggregate = _response_example("event.export.aggregate_only.json")
    artifact = _response_example("event.export.artifact.json")
    event_export.validate(aggregate)
    event_export.validate(artifact)
    preview_without_payload = json.loads(json.dumps(aggregate))
    preview_without_payload["data"].pop("aggregate")
    assert not event_export.is_valid(preview_without_payload)
    artifact_with_events = json.loads(json.dumps(artifact))
    artifact_with_events["data"]["events"] = []
    assert not event_export.is_valid(artifact_with_events)
    preview_with_output = json.loads(json.dumps(aggregate))
    preview_with_output["summary"]["output"] = {
        "path": "event.json",
        "file_format": "json",
    }
    assert not event_export.is_valid(preview_with_output)

    counter = validators["counter.statistics"]
    counter_positive = _response_example(
        "counter.statistics.basic.json"
    )
    counter_empty = _response_example(
        "counter.statistics.no_value.json"
    )
    no_value_with_min = json.loads(json.dumps(counter_empty))
    no_value_with_min["summary"]["min_value"] = "0"
    assert not counter.is_valid(no_value_with_min)
    no_value_with_count = json.loads(json.dumps(counter_empty))
    no_value_with_count["data"]["min_count"] = 1
    assert not counter.is_valid(no_value_with_count)
    value_without_average = json.loads(json.dumps(counter_positive))
    value_without_average["summary"].pop("average_value")
    assert not counter.is_valid(value_without_average)
    predicate_typo = json.loads(json.dumps(counter_positive))
    predicate_typo["data"]["vld"]["typo"] = "top.typo"
    assert not counter.is_valid(predicate_typo)
    unknown_with_numeric_value = json.loads(json.dumps(counter_empty))
    unknown_with_numeric_value["data"]["evidence"][0]["value"] = "0"
    assert not counter.is_valid(unknown_with_numeric_value)
    known_with_null_value = json.loads(json.dumps(counter_positive))
    known_with_null_value["data"]["evidence"][0]["value"] = None
    assert not counter.is_valid(known_with_null_value)

    signal = validators["signal.statistics"]
    clock_unknown = _response_example(
        "signal.statistics.clock_unknown.json"
    )
    clock_no_transition = _response_example(
        "signal.statistics.clock_no_transition.json"
    )
    clock_transition = _response_example(
        "signal.statistics.basic.json"
    )
    raw_empty = _response_example(
        "signal.statistics.raw_empty.json"
    )
    raw_nonempty = _response_example(
        "signal.statistics.raw.json"
    )
    for response in (
        clock_unknown,
        clock_no_transition,
        clock_transition,
        raw_empty,
        raw_nonempty,
    ):
        signal.validate(response)
    unknown_with_known_value = json.loads(json.dumps(clock_unknown))
    unknown_with_known_value["data"]["first"] = {
        "value": "1'b0",
        "known": True,
    }
    assert not signal.is_valid(unknown_with_known_value)
    unknown_with_transition = json.loads(json.dumps(clock_unknown))
    unknown_with_transition["data"]["transition_count"] = 1
    assert not signal.is_valid(unknown_with_transition)
    known_without_activity = json.loads(json.dumps(clock_no_transition))
    known_without_activity["data"].pop("activity")
    assert not signal.is_valid(known_without_activity)
    no_transition_with_time = json.loads(
        json.dumps(clock_no_transition)
    )
    no_transition_with_time["data"]["first_change_time"] = "120ns"
    assert not signal.is_valid(no_transition_with_time)
    transition_without_time = json.loads(json.dumps(clock_transition))
    transition_without_time["data"].pop("last_change_time")
    assert not signal.is_valid(transition_without_time)
    raw_empty_with_value = json.loads(json.dumps(raw_empty))
    raw_empty_with_value["data"]["initial_value"] = {
        "value": "1'b0",
        "known": True,
    }
    assert not signal.is_valid(raw_empty_with_value)
    raw_empty_with_transition = json.loads(json.dumps(raw_empty))
    raw_empty_with_transition["summary"]["actual_transition_count"] = 1
    assert not signal.is_valid(raw_empty_with_transition)
    raw_nonempty_without_value = json.loads(json.dumps(raw_nonempty))
    raw_nonempty_without_value["data"].pop("initial_value")
    assert not signal.is_valid(raw_nonempty_without_value)


def test_canonical_logic_value_matrix_is_exact_and_shared() -> None:
    actions = (
        "event.find",
        "expr.eval_at",
        "signal.statistics",
        "value.at",
        "verify.conditions",
    )
    definitions = [
        _generated_response_schema(action)["$defs"]["logicValue"]
        for action in actions
    ]
    assert all(definition == definitions[0] for definition in definitions)
    schema = definitions[0]
    validators = (
        Draft7Validator(schema),
        Draft202012Validator(schema),
    )
    valid = [
        {"value": "'h1", "known": True},
        {
            "value": "4'h1",
            "known": True,
            "width": 4,
            "bits": "0001",
        },
        {
            "value": "'bx",
            "known": False,
            "has_x": True,
            "has_z": False,
        },
        {
            "value": "4'bx01z",
            "known": False,
            "width": 4,
            "bits": "x01z",
            "has_x": True,
            "has_z": True,
        },
        {
            "value": "'bx",
            "known": False,
            "has_x": True,
            "has_z": False,
            "requested_value_format": "dec",
            "effective_value_format": "bin",
            "value_format_reason": (
                "decimal cannot preserve per-bit X/Z"
            ),
        },
        {
            "value": "4'bx01z",
            "known": False,
            "width": 4,
            "bits": "x01z",
            "has_x": True,
            "has_z": True,
            "requested_value_format": "dec",
            "effective_value_format": "bin",
            "value_format_reason": (
                "decimal cannot preserve per-bit X/Z"
            ),
        },
    ]
    invalid = [
        {"value": "4'h1", "known": True, "width": 4},
        {"value": "4'h1", "known": True, "bits": "0001"},
        {
            "value": "1'b1",
            "known": True,
            "has_x": False,
            "has_z": False,
        },
        {"value": "'bx", "known": False},
        {
            "value": "'bx",
            "known": False,
            "has_x": False,
            "has_z": False,
        },
        {
            "value": "'bx",
            "known": False,
            "has_x": True,
            "has_z": False,
            "requested_value_format": "dec",
        },
        {
            "value": "1'd1",
            "known": True,
            "requested_value_format": "dec",
            "effective_value_format": "bin",
            "value_format_reason": (
                "decimal cannot preserve per-bit X/Z"
            ),
        },
        {
            "value": "'bx",
            "known": False,
            "has_x": True,
            "has_z": False,
            "typo": True,
        },
    ]
    for validator in validators:
        for value in valid:
            validator.validate(value)
        assert all(
            not validator.is_valid(value)
            for value in invalid
        )


def test_value_expression_and_condition_response_variants_are_closed() -> None:
    value_at = Draft202012Validator(
        _generated_response_schema("value.at")
    )
    value_basic = _response_example("value.at.basic.json")
    value_clock = _response_example("value.at.clock.json")
    value_unknown = _response_example("value.at.unknown.json")
    value_clock_unknown = _response_example(
        "value.at.clock_unknown.json"
    )
    value_missing = _response_example("value.at.missing_value.json")
    value_xbit = _response_example("value.at.xbit.json")
    value_list = _response_example("value.at.list.json")
    for response in (
        value_basic,
        value_clock,
        value_unknown,
        value_clock_unknown,
        value_missing,
        value_xbit,
        value_list,
    ):
        value_at.validate(response)
    raw_with_clock_context = json.loads(json.dumps(value_basic))
    raw_with_clock_context["data"]["samples"][0]["clock_context"] = (
        value_clock["data"]["samples"][0]["clock_context"]
    )
    assert not value_at.is_valid(raw_with_clock_context)
    clock_without_context = json.loads(json.dumps(value_clock))
    clock_without_context["data"]["samples"][0].pop("clock_context")
    assert not value_at.is_valid(clock_without_context)
    hint_typo = json.loads(json.dumps(value_xbit))
    hint_typo["data"]["samples"][0]["values"][0]["xbit_hints"][
        "typo"
    ] = True
    assert not value_at.is_valid(hint_typo)
    dead_hint_status = json.loads(json.dumps(value_xbit))
    dead_hint_status["data"]["samples"][0]["values"][0][
        "xbit_hints"
    ] = {
        "status": "needs_slice_hint",
        "signal": "top.u.payload",
        "raw_value": "64'h0",
    }
    assert not value_at.is_valid(dead_hint_status)
    missing_with_xbit = json.loads(json.dumps(value_missing))
    missing_with_xbit["data"]["samples"][0]["values"][0][
        "xbit_hints"
    ] = value_xbit["data"]["samples"][0]["values"][0]["xbit_hints"]
    assert not value_at.is_valid(missing_with_xbit)

    list_signal_not_found = json.loads(json.dumps(value_list))
    list_signal_not_found["data"]["samples"][0]["values"][1] = {
        "key": "top.u.ready",
        "status": "signal_not_found",
    }
    value_at.validate(list_signal_not_found)
    bad_list_status = json.loads(json.dumps(value_list))
    bad_list_status["data"]["samples"][0]["values"][1]["status"] = (
        "not_dumped_or_unreadable"
    )
    assert not value_at.is_valid(bad_list_status)
    bad_list_value = json.loads(json.dumps(value_list))
    bad_list_value["data"]["samples"][0]["values"][0]["value"][
        "typo"
    ] = True
    assert not value_at.is_valid(bad_list_value)
    raw_with_context = json.loads(json.dumps(value_list))
    raw_with_context["data"]["samples"][0]["clock_context"] = (
        value_clock["data"]["samples"][0]["clock_context"]
    )
    assert not value_at.is_valid(raw_with_context)

    expr_validator = Draft202012Validator(
        _generated_response_schema("expr.eval_at")
    )
    expr_known = _response_example("expr.eval_at.basic.json")
    expr_false = _response_example("expr.eval_at.false.json")
    expr_unknown = _response_example("expr.eval_at.unknown.json")
    expr_validator.validate(expr_known)
    expr_validator.validate(expr_false)
    expr_validator.validate(expr_unknown)
    false_summary_true_data = json.loads(json.dumps(expr_false))
    false_summary_true_data["data"] = expr_known["data"]
    assert not expr_validator.is_valid(false_summary_true_data)
    known_null = json.loads(json.dumps(expr_known))
    known_null["data"]["expr_value"] = None
    assert not expr_validator.is_valid(known_null)
    unknown_boolean = json.loads(json.dumps(expr_unknown))
    unknown_boolean["data"]["expr_value"] = False
    assert not expr_validator.is_valid(unknown_boolean)
    operand_typo = json.loads(json.dumps(expr_unknown))
    operand_typo["data"]["operands"][0]["typo"] = True
    assert not expr_validator.is_valid(operand_typo)

    verify_validator = Draft202012Validator(
        _generated_response_schema("verify.conditions")
    )
    verify_known = _response_example("verify.conditions.basic.json")
    verify_unknown = _response_example(
        "verify.conditions.unknown.json"
    )
    verify_validator.validate(verify_known)
    verify_validator.validate(verify_unknown)
    error_with_value = json.loads(json.dumps(verify_unknown))
    error_with_value["data"]["checks"][1]["value"] = {
        "value": "'bx",
        "known": False,
        "has_x": True,
        "has_z": False,
    }
    assert not verify_validator.is_valid(error_with_value)
    unknown_without_value = json.loads(json.dumps(verify_unknown))
    unknown_without_value["data"]["checks"][0].pop("value")
    assert not verify_validator.is_valid(unknown_without_value)
    pass_with_error = json.loads(json.dumps(verify_known))
    pass_with_error["data"]["checks"][0]["error_code"] = "TYPO"
    pass_with_error["data"]["checks"][0]["error"] = "not legal"
    assert not verify_validator.is_valid(pass_with_error)


def test_slice_hint_and_condition_request_subtrees_are_action_exact() -> None:
    entries = _action_entries()
    for action, example_name in (
        ("value.at", "value.at.xbit.json"),
    ):
        schema = json.loads(
            (XDEBUG / entries[action]["schemas"]["request"]).read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(schema)
        request = json.loads(
            (
                XDEBUG / "examples/requests" / example_name
            ).read_text(encoding="utf-8")
        )
        validator.validate(request)
        for invalid_hint in (
            {},
            {"chunk_width": 0},
            {"chunk_width": 1, "count": 0},
        ):
            invalid = json.loads(json.dumps(request))
            invalid["args"]["slice_hint"] = invalid_hint
            assert not validator.is_valid(invalid), (
                action,
                invalid_hint,
            )

    verify_schema = json.loads(
        (
            XDEBUG
            / entries["verify.conditions"]["schemas"]["request"]
        ).read_text(encoding="utf-8")
    )
    verify_validator = Draft202012Validator(verify_schema)
    verify = json.loads(
        (
            XDEBUG
            / "examples/requests/verify.conditions.basic.json"
        ).read_text(encoding="utf-8")
    )
    verify_with_name = json.loads(json.dumps(verify))
    verify_with_name["args"]["conditions"][0]["name"] = "valid_high"
    verify_validator.validate(verify_with_name)
    verify_with_mode = json.loads(json.dumps(verify))
    verify_with_mode["args"]["conditions"][0]["mode"] = "always"
    assert not verify_validator.is_valid(verify_with_mode)

    window_schema = json.loads(
        (
            XDEBUG / entries["window.verify"]["schemas"]["request"]
        ).read_text(encoding="utf-8")
    )
    window_validator = Draft202012Validator(window_schema)
    window = json.loads(
        (
            XDEBUG / "examples/requests/window.verify.basic.json"
        ).read_text(encoding="utf-8")
    )
    window_validator.validate(window)
    window_with_name = json.loads(json.dumps(window))
    window_with_name["args"]["conditions"][0]["name"] = "valid_high"
    assert not window_validator.is_valid(window_with_name)


def test_handshake_sampled_pulse_and_window_variants_are_closed() -> None:
    handshake = Draft202012Validator(
        _generated_response_schema("protocol.handshake.inspect")
    )
    summary = _response_example(
        "protocol.handshake.inspect.basic.json"
    )
    intervals = _response_example(
        "protocol.handshake.inspect.intervals.json"
    )
    all_rows = _response_example(
        "protocol.handshake.inspect.all.json"
    )
    for response in (summary, intervals, all_rows):
        handshake.validate(response)
    summary_with_intervals = json.loads(json.dumps(summary))
    summary_with_intervals["data"][
        "ready_without_valid_intervals"
    ] = []
    assert not handshake.is_valid(summary_with_intervals)
    intervals_without_rows = json.loads(json.dumps(intervals))
    intervals_without_rows["data"].pop(
        "ready_without_valid_intervals"
    )
    assert not handshake.is_valid(intervals_without_rows)
    interval_with_compat_field = json.loads(json.dumps(intervals))
    interval_with_compat_field["data"][
        "ready_without_valid_intervals"
    ][0]["cycles"] = 2
    assert not handshake.is_valid(interval_with_compat_field)
    interval_without_canonical_count = json.loads(
        json.dumps(intervals)
    )
    interval_without_canonical_count["data"][
        "ready_without_valid_intervals"
    ][0].pop("cycle_count")
    assert not handshake.is_valid(interval_without_canonical_count)
    wrong_finding_payload = json.loads(json.dumps(all_rows))
    wrong_finding_payload["data"]["findings"][0]["cycles"] = 1
    assert not handshake.is_valid(wrong_finding_payload)

    sampled = Draft202012Validator(
        _generated_response_schema(
            "signal.sampled_pulse.inspect"
        )
    )
    pulse = _response_example(
        "signal.sampled_pulse.inspect.basic.json"
    )
    boundary = _response_example(
        "signal.sampled_pulse.inspect.boundary_payload.json"
    )
    sampled_high = _response_example(
        "signal.sampled_pulse.inspect.sampled_high.json"
    )
    for response in (pulse, boundary, sampled_high):
        sampled.validate(response)
    boundary_bad_payload = json.loads(json.dumps(boundary))
    boundary_bad_payload["data"]["findings"][0]["payload"].pop(
        "alias"
    )
    assert not sampled.is_valid(boundary_bad_payload)
    boundary_bad_edge = json.loads(json.dumps(boundary))
    boundary_bad_edge["data"]["findings"][0][
        "previous_sample_edge"
    ] = 0
    assert not sampled.is_valid(boundary_bad_edge)
    zero_high_with_time = json.loads(json.dumps(boundary))
    zero_high_with_time["data"]["first_sampled_high_time"] = "5ns"
    assert not sampled.is_valid(zero_high_with_time)
    positive_high_without_time = json.loads(json.dumps(sampled_high))
    positive_high_without_time["data"]["first_sampled_high_time"] = None
    assert not sampled.is_valid(positive_high_without_time)
    finding_typo = json.loads(json.dumps(pulse))
    finding_typo["data"]["findings"][0]["typo"] = True
    assert not sampled.is_valid(finding_typo)

    window = Draft202012Validator(
        _generated_response_schema("window.verify")
    )
    complete = _response_example("window.verify.basic.json")
    incomplete = _response_example("window.verify.incomplete.json")
    empty = _response_example("window.verify.empty.json")
    for response in (complete, incomplete, empty):
        window.validate(response)
    incomplete_boolean = json.loads(json.dumps(incomplete))
    incomplete_boolean["summary"]["all_passed"] = False
    assert not window.is_valid(incomplete_boolean)
    empty_with_scanned_time = json.loads(json.dumps(empty))
    empty_with_scanned_time["summary"]["scanned_range"][
        "begin"
    ] = "0ns"
    assert not window.is_valid(empty_with_scanned_time)
    empty_with_finding = json.loads(json.dumps(empty))
    empty_with_finding["data"]["findings"] = incomplete["data"][
        "findings"
    ]
    assert not window.is_valid(empty_with_finding)
    empty_with_failure_count = json.loads(json.dumps(empty))
    empty_with_failure_count["summary"]["failed_samples"] = 1
    assert not window.is_valid(empty_with_failure_count)
    finding_signal_object = json.loads(json.dumps(incomplete))
    finding_signal_object["data"]["findings"][0]["signals"][
        "valid"
    ] = {"value": "'bx", "known": False}
    assert not window.is_valid(finding_signal_object)
    window_finding_typo = json.loads(json.dumps(incomplete))
    window_finding_typo["data"]["findings"][0]["typo"] = True
    assert not window.is_valid(window_finding_typo)


def test_event_config_response_schema_preserves_negedge_sample_point() -> None:
    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    entries = {entry["name"]: entry for entry in catalog["actions"]}
    validators = {
        action: Draft202012Validator(
            json.loads(
                (
                    XDEBUG / entries[action]["schemas"]["response"]
                ).read_text(encoding="utf-8")
            )
        )
        for action in ("event.config.load", "event.config.list")
    }
    load_definition = validators[
        "event.config.load"
    ].schema["$defs"]["eventConfig"]
    list_definition = validators[
        "event.config.list"
    ].schema["$defs"]["eventConfig"]
    assert load_definition == list_definition
    assert load_definition["additionalProperties"] is False
    explicit_negedge = json.loads(
        (
            XDEBUG
            / "examples/responses"
            / "event.config.load.negedge_sample_point.json"
        ).read_text(encoding="utf-8")
    )
    validators["event.config.load"].validate(explicit_negedge)
    assert (
        explicit_negedge["data"]["config"]["edge"] == "negedge"
    )
    assert (
        explicit_negedge["data"]["config"]["sample_point"] == "after"
    )

    unknown_config_field = json.loads(json.dumps(explicit_negedge))
    unknown_config_field["data"]["config"]["typo"] = True
    assert not validators["event.config.load"].is_valid(
        unknown_config_field
    )

    named = json.loads(
        (
            XDEBUG
            / "examples/responses/event.config.list.basic.json"
        ).read_text(encoding="utf-8")
    )
    all_configs = json.loads(
        (
            XDEBUG
            / "examples/responses/event.config.list.all.json"
        ).read_text(encoding="utf-8")
    )
    validators["event.config.list"].validate(named)
    validators["event.config.list"].validate(all_configs)
    named_summary_all_data = json.loads(json.dumps(named))
    named_summary_all_data["data"] = all_configs["data"]
    assert not validators["event.config.list"].is_valid(
        named_summary_all_data
    )
    all_summary_named_data = json.loads(json.dumps(all_configs))
    all_summary_named_data["data"] = named["data"]
    assert not validators["event.config.list"].is_valid(
        all_summary_named_data
    )


def test_actions_filter_request_and_response_share_one_closed_shape() -> None:
    request_schema = json.loads(
        (
            XDEBUG / "schemas/v1/actions/actions.request.schema.json"
        ).read_text(encoding="utf-8")
    )
    response_schema = json.loads(
        (
            XDEBUG / "schemas/v1/actions/actions.response.schema.json"
        ).read_text(encoding="utf-8")
    )
    request_filter = request_schema["properties"]["args"][
        "properties"
    ]["filter"]
    response_filter = response_schema["$defs"]["successData"][
        "properties"
    ]["filters"]

    def contract_shape(node: object) -> object:
        if isinstance(node, dict):
            return {
                key: contract_shape(value)
                for key, value in node.items()
                if key not in {"description", "x-description-zh"}
            }
        if isinstance(node, list):
            return [contract_shape(value) for value in node]
        return node

    assert contract_shape(request_filter) == response_filter
    assert response_filter["additionalProperties"] is False
    assert set(response_filter["properties"]) == {
        "category",
        "requires",
        "purposes",
        "keyword",
    }

    response = json.loads(
        (
            XDEBUG / "examples/responses/actions.basic.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(response_schema)
    filters = [
        {},
        {"category": ["builtin"]},
        {"requires": ["none"]},
        {"purposes": ["discover"]},
        {"keyword": "schema"},
        {
            "category": ["builtin", "waveform"],
            "requires": ["none", "waveform"],
            "purposes": ["discover", "query"],
            "keyword": "schema",
        },
    ]
    for value in filters:
        candidate = json.loads(json.dumps(response))
        candidate["data"]["filters"] = value
        validator.validate(candidate)
    typo = json.loads(json.dumps(response))
    typo["data"]["filters"] = {"keywrod": "schema"}
    assert not validator.is_valid(typo)


def test_session_list_is_a_targetless_catalog_action() -> None:
    catalog = json.loads(
        (XDEBUG / "specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    entry = next(
        action
        for action in catalog["actions"]
        if action["name"] == "session.list"
    )
    assert entry["requires"] == "none"
    schema = json.loads(
        (XDEBUG / entry["schemas"]["request"]).read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    request = json.loads(
        (
            XDEBUG / "examples/requests/session.list.basic.json"
        ).read_text(encoding="utf-8")
    )
    assert "target" not in request
    validator.validate(request)
    with_target = json.loads(json.dumps(request))
    with_target["target"] = {"session_id": "case_a"}
    assert not validator.is_valid(with_target)


def test_session_success_responses_have_one_canonical_fact_owner() -> None:
    examples = {
        "session.open": (
            "session.open.basic.json",
            "session.open.duplicate_resource.json",
        ),
        "session.list": (
            "session.list.basic.json",
            "session.list.verbose.json",
        ),
        "session.doctor": ("session.doctor.basic.json",),
        "session.close": (
            "session.close.basic.json",
            "session.close.all.json",
        ),
        "session.gc": ("session.gc.basic.json",),
    }
    validators = {
        action: Draft202012Validator(
            _generated_response_schema(action)
        )
        for action in examples
    }
    for action, names in examples.items():
        validator = validators[action]
        for name in names:
            response = _response_example(name)
            validator.validate(response)

        response = _response_example(names[-1])
        if action in {"session.open", "session.doctor"}:
            assert isinstance(response["session"], dict)
            missing_live_context = json.loads(json.dumps(response))
            missing_live_context["session"] = None
            assert not validator.is_valid(missing_live_context)
        else:
            assert response["session"] is None
            false_live_context = json.loads(json.dumps(response))
            if action == "session.list":
                record = response["data"]["sessions"][0]
            elif action == "session.gc":
                record = response["data"]["kept_sessions"][0]
            elif "removed_session" in response["data"]:
                record = response["data"]["removed_session"]
            else:
                record = response["data"]["removed_sessions"][0]
            false_live_context["session"] = record
            assert not validator.is_valid(false_live_context)

        nested_envelope = json.loads(json.dumps(response))
        nested_envelope["data"]["backend"] = {
            "api_version": "xdebug.v1",
            "ok": True,
            "action": "session.close",
        }
        assert not validator.is_valid(nested_envelope)

    outcome_mutations = (
        ("session.open", "session.open.basic.json", "status", "existing"),
        ("session.doctor", "session.doctor.basic.json", "healthy", False),
        ("session.close", "session.close.basic.json", "removed", False),
    )
    for action, name, field, value in outcome_mutations:
        response = _response_example(name)
        response["summary"][field] = value
        assert not validators[action].is_valid(response)

    for action, name, field in (
        ("session.list", "session.list.basic.json", "session_count"),
        ("session.close", "session.close.all.json", "requested_count"),
        ("session.gc", "session.gc.basic.json", "before_count"),
    ):
        response = _response_example(name)
        response["summary"][field] = -1
        assert not validators[action].is_valid(response)

    for action in ("session.close",):
        response = _response_example(f"{action}.all.json")
        response["summary"] = {
            "requested_count": 0,
            "removed_count": 0,
            "retained_count": 0,
        }
        response["data"]["removed_sessions"] = []
        validators[action].validate(response)

    gc = _response_example("session.gc.basic.json")
    gc_variants = []
    empty = json.loads(json.dumps(gc))
    empty["summary"] = {
        "before_count": 0,
        "kept_count": 0,
        "removed_count": 0,
    }
    empty["data"] = {"kept_sessions": [], "removed": []}
    gc_variants.append(empty)
    kept_only = json.loads(json.dumps(gc))
    kept_only["summary"] = {
        "before_count": 1,
        "kept_count": 1,
        "removed_count": 0,
    }
    kept_only["data"]["removed"] = []
    gc_variants.append(kept_only)
    removed_only = json.loads(json.dumps(gc))
    removed_only["summary"] = {
        "before_count": 1,
        "kept_count": 0,
        "removed_count": 1,
    }
    removed_only["data"]["kept_sessions"] = []
    gc_variants.append(removed_only)
    gc_variants.append(gc)
    for response in gc_variants:
        validators["session.gc"].validate(response)

    audit = _module("audit_json_responses")
    dynamic_count_mutations = []
    bulk_mismatch = _response_example("session.close.all.json")
    bulk_mismatch["summary"]["requested_count"] = 2
    dynamic_count_mutations.append(bulk_mismatch)
    gc_mismatch = _response_example("session.gc.basic.json")
    gc_mismatch["summary"]["before_count"] = 3
    dynamic_count_mutations.append(gc_mismatch)
    for response in dynamic_count_mutations:
        validator = Draft202012Validator(
            _generated_response_schema(response["action"])
        )
        validator.validate(response)
        errors = audit.audit_response(Path("mutation.json"), response)
        assert errors


def test_session_success_contracts_do_not_use_witness_inference() -> None:
    generator = _module("sync_response_schemas")

    def forbidden_inference(*_args, **_kwargs):
        raise AssertionError("session success contract used witness inference")

    generator.infer_schema = forbidden_inference
    entries = _action_entries()
    for action in (
        "session.open",
        "session.list",
        "session.doctor",
        "session.close",
        "session.gc",
    ):
        generator.response_schema(entries[action])


def test_session_open_run_manifest_response_is_strict_and_canonical() -> None:
    schema = _generated_response_schema("session.open")
    validator = Draft202012Validator(schema)
    response = _response_example("session.open.basic.json")
    manifest = {
        "schema_version": "xdebug.run-manifest.v1",
        "state": "published",
        "resources": {
            "fsdb": {
                "path": "../waves.fsdb",
                "size_bytes": 4096,
                "sha256": "a" * 64,
            },
            "daidir": {
                "path": "../simv.daidir",
                "size_bytes": 8192,
                "sha256": "b" * 64,
            },
        },
        "manifest_path": "/" + "work/run-manifest.json",
    }
    response["data"]["run_manifest"] = manifest
    validator.validate(response)

    unknown = json.loads(json.dumps(response))
    unknown["data"]["run_manifest"]["typo"] = True
    assert not validator.is_valid(unknown)

    absolute_resource = json.loads(json.dumps(response))
    absolute_resource["data"]["run_manifest"][
        "resources"
    ]["fsdb"]["path"] = "/" + "tmp/waves.fsdb"
    assert not validator.is_valid(absolute_resource)

    uppercase_digest = json.loads(json.dumps(response))
    uppercase_digest["data"]["run_manifest"][
        "resources"
    ]["fsdb"]["sha256"] = "A" * 64
    assert not validator.is_valid(uppercase_digest)


def test_scope_roots_response_schema_enforces_root_state_machine() -> None:
    schema = json.loads(
        (
            XDEBUG
            / "schemas/v1/actions/scope.roots.response.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    examples = {
        name: json.loads(
            (
                XDEBUG / "examples/responses" / f"scope.roots.{name}.json"
            ).read_text(encoding="utf-8")
        )
        for name in ("basic", "mismatch", "wave_only")
    }
    for response in examples.values():
        validator.validate(response)

    verified_wave_root = json.loads(json.dumps(examples["basic"]))
    verified_wave_root["data"]["roots"][0]["design"]["discovery"] = (
        "verified_wave_root"
    )
    verified_wave_root["data"]["design_roots"][0]["discovery"] = (
        "verified_wave_root"
    )
    validator.validate(verified_wave_root)

    empty_roots = json.loads(json.dumps(examples["wave_only"]))
    empty_roots["summary"].update(
        {
            "root_count": 0,
            "wave_count": 0,
            "matched_count": 0,
            "recommended_root": None,
            "recommended_reason": "no roots discovered",
            "total_count": 0,
            "returned_count": 0,
        }
    )
    empty_roots["data"]["roots"] = []
    empty_roots["data"]["wave_roots"] = []
    empty_roots["data"]["limitations"].append(
        "wave root iterator returned no scopes"
    )
    validator.validate(empty_roots)

    invalid_discovery = json.loads(json.dumps(examples["basic"]))
    invalid_discovery["data"]["roots"][0]["design"]["discovery"] = "guessed"
    assert not validator.is_valid(invalid_discovery)

    invalid_status = json.loads(json.dumps(examples["basic"]))
    invalid_status["data"]["roots"][0]["status"] = "design_only"
    assert not validator.is_valid(invalid_status)

    invalid_sources = json.loads(json.dumps(examples["basic"]))
    invalid_sources["data"]["roots"][0]["sources"] = ["wave", "design"]
    assert not validator.is_valid(invalid_sources)

    invalid_nullability = json.loads(json.dumps(examples["wave_only"]))
    invalid_nullability["data"]["roots"][0]["design"] = (
        examples["basic"]["data"]["roots"][0]["design"]
    )
    assert not validator.is_valid(invalid_nullability)


def test_trace_common_blocks_are_exposed_by_their_public_schemas() -> None:
    expected = {
        "trace.driver",
        "trace.load",
        "trace.active_driver",
        "trace.active_driver_chain",
    }
    catalog = json.loads(
        (XDEBUG / "specs" / "actions" / "actions.yaml").read_text(
            encoding="utf-8"
        )
    )

    def exposes_common_blocks(node: object) -> bool:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "common_blocks" in properties:
                return True
            return any(exposes_common_blocks(value) for value in node.values())
        if isinstance(node, list):
            return any(exposes_common_blocks(value) for value in node)
        return False

    actual = set()
    for action in catalog["actions"]:
        schema = json.loads(
            (XDEBUG / action["schemas"]["response"]).read_text(encoding="utf-8")
        )
        if exposes_common_blocks(schema["$defs"]["successData"]):
            actual.add(action["name"])
    assert actual == expected


def test_clock_sampling_is_consolidated() -> None:
    assert _module("check_clock_sampling_consolidation").main() == 0


def test_error_contract_is_consolidated() -> None:
    assert _module("check_error_contract_consolidation").main() == 0


def test_response_contract_is_consolidated() -> None:
    assert _module("check_response_contract_consolidation").main() == 0


def test_unreachable_legacy_limit_policy_is_removed() -> None:
    assert not (XDEBUG / "src" / "core" / "output" / "limit_policy.h").exists()
    for source in (XDEBUG / "src").rglob("*"):
        if source.suffix not in {".h", ".cpp"}:
            continue
        text = source.read_text(encoding="utf-8")
        assert "LimitPolicy" not in text, source
        assert "limit_policy.h" not in text, source


def test_trace_resolution_never_substitutes_noncanonical_source_evidence() -> None:
    ast_source = (
        XDEBUG / "src" / "design" / "ast" / "ast_extractor.cpp"
    ).read_text(encoding="utf-8")
    decompile_body = ast_source.split(
        "std::string AstExtractor::decompile(npiHandle hdl) const {", 1
    )[1].split("\n}", 1)[0]
    assert "decomp.decompile(" in decompile_body
    assert "npi_get_str(" not in decompile_body
    assert "npiDecompile" not in decompile_body
    assert "npiFullName" not in decompile_body
    assert "npiName" not in decompile_body

    control_source = (
        XDEBUG / "src" / "design" / "control_dep" / "control_dep.cpp"
    ).read_text(encoding="utf-8")
    evidence_body = control_source.split(
        "ControlDepInfo ControlDepTracer::make_control_dep_info(", 1
    )[1].split(
        "\nvoid ControlDepTracer::extract_signals_from_expr_with_info", 1
    )[0]
    assert "if (!control_stmt)" in evidence_body
    assert "return info;" in evidence_body
    assert "npi_ut_get_hdl_info" not in evidence_body
    assert "npi_ut_get_hdl_info" not in control_source

    trace_source = (
        XDEBUG / "src" / "design" / "trace" / "trace_engine.cpp"
    ).read_text(encoding="utf-8")
    assert '"analysis_trace_resolution"' in trace_source
    assert "fallback AST" not in trace_source
    assert "fallback records" not in trace_source


def test_action_schema_coverage_is_complete() -> None:
    assert _module("audit_action_schema_coverage").main(
        ["audit_action_schema_coverage", str(XDEBUG)]
    ) == 0


def test_schema_batch_response_detail_contract_is_strict_and_token_aware() -> None:
    schema = json.loads(
        (XDEBUG / "schemas/v1/actions/schema.request.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)

    def request(**args):
        return {
            "api_version": "xdebug.v1",
            "action": "schema",
            "args": args,
        }

    assert validator.is_valid(request(action="batch", kind="response"))
    assert validator.is_valid(request(
        action="batch", kind="response", response_detail="summary",
    ))
    assert validator.is_valid(request(
        action="batch", kind="response", response_detail="full",
    ))
    assert validator.is_valid(request(
        action="batch", kind="response", response_detail="child",
        child_action="value.at",
    ))
    assert not validator.is_valid(request(
        action="batch", kind="response", response_detail="child",
    ))
    assert not validator.is_valid(request(
        action="batch", kind="response", response_detail="summary",
        child_action="value.at",
    ))
    assert not validator.is_valid(request(
        action="value.at", kind="response", response_detail="summary",
    ))
    assert not validator.is_valid(request(
        action="batch", kind="request", response_detail="summary",
    ))


def test_native_schema_batch_projection_keeps_full_expansion_explicit() -> None:
    source = (XDEBUG / "src/api/action_catalog.cpp").read_text(encoding="utf-8")
    assert 'args.value("response_detail", std::string("full"))' in source
    assert 'response_detail == "summary"' in source
    assert 'response_detail == "child"' in source
    assert "compact_batch_response_schema" in source
    assert '"complete-recursive-union"' in source
    assert '"outer-envelope-only"' in source
    assert '"selected-child-response"' in source


def test_current_json_samples_are_generated_from_canonical_examples() -> None:
    generator = _module("sync_json_after_cleanup_samples")
    assert generator.sync(check=True) == []


def test_request_schemas_are_agent_discoverable() -> None:
    assert _module("audit_agent_schema_quality").main() == 0


def test_request_schemas_are_runtime_draft7_compatible() -> None:
    assert _module("audit_runtime_schema_compatibility").main() == 0


def test_runtime_request_generator_is_importable_in_isolated_process() -> None:
    generator_path = XDEBUG / "tools" / "sync_runtime_request_schemas.py"
    import_script = """
import importlib.util
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "isolated_sync_runtime_request_schemas",
    path,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.action_specs()
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            import_script,
            str(generator_path),
        ],
        cwd=XDEBUG.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_public_args_have_explicit_runtime_consumers() -> None:
    generator = _module("sync_runtime_request_schemas")
    specs = generator.action_specs()
    arg_schemas = generator.collect_arg_schemas(specs)
    assert generator.audit_runtime_consumer_contract(specs, arg_schemas) == []
    assert not hasattr(
        generator, "RUNTIME_CONSUMED_OPTIONAL_ARGS_BY_ACTION"
    )
    contracts = generator.RUNTIME_CONSUMER_CONTRACTS_BY_ACTION
    assert set(contracts) == {spec["name"] for spec in specs}
    actual_frontend_consumers = _discover_frontend_runtime_consumers()
    for spec in specs:
        contract = contracts[spec["name"]]
        assert isinstance(contract, generator.RuntimeConsumerContract)
        assert contract.consumer_id.strip()
        if spec["name"] in actual_frontend_consumers:
            expected_kind = (
                "session"
                if spec["name"].startswith("session.")
                else spec["name"]
            )
            assert spec["handler_kind"] == expected_kind
            assert (
                contract.consumer_id
                == actual_frontend_consumers[spec["name"]]
            )
        schema = json.loads(
            (XDEBUG / spec["schemas"]["request"]).read_text(encoding="utf-8")
        )
        published = set(
            schema["properties"]["args"].get("properties", {})
        )
        declared = (
            generator.required_related_args(spec)
            | contract.optional_args
        )
        assert published == declared, spec["name"]
        assert published == generator.allowed_args_for_spec(spec), spec["name"]

    assert set(actual_frontend_consumers) == {
        spec["name"]
        for spec in specs
        if spec["handler_kind"] != "engine_forward"
    }


def test_engine_forward_timeout_is_positive_or_omitted() -> None:
    for action, entry in _action_entries().items():
        if entry["handler_kind"] != "engine_forward":
            continue
        schema, example = _request_schema_and_example(entry)
        timeout_schema = schema["properties"]["limits"]["properties"][
            "timeout_ms"
        ]
        assert timeout_schema["minimum"] == 1, action
        validator = Draft7Validator(schema)

        positive = json.loads(json.dumps(example))
        positive.setdefault("limits", {})["timeout_ms"] = 1
        assert validator.is_valid(positive), (
            action,
            list(validator.iter_errors(positive)),
        )

        zero = json.loads(json.dumps(example))
        zero.setdefault("limits", {})["timeout_ms"] = 0
        assert not validator.is_valid(zero), action


def test_session_transport_does_not_invent_a_public_timeout() -> None:
    client = (
        XDEBUG / "src/engine/session/client.cpp"
    ).read_text(encoding="utf-8")
    transport_header = (
        XDEBUG / "src/engine/session/session_transport.h"
    ).read_text(encoding="utf-8")
    transport = (
        XDEBUG / "src/engine/session/session_transport.cpp"
    ).read_text(encoding="utf-8")
    timeout_contract = (
        XDEBUG / "src/core/session/transport_timeout.h"
    ).read_text(encoding="utf-8")
    env_config = (
        XDEBUG / "src/core/common/env_config.cpp"
    ).read_text(encoding="utf-8")

    assert "return 30000;" not in client
    assert "public_request_timeout_override_ms(request)" in client
    assert "TransportDeadline socket_deadline" in client
    assert "socket_deadline" in client
    assert "set_public_socket_timeout_override" not in client
    assert "TransportTimeoutOverrideMs" in transport_header
    assert "std::optional" not in transport_header
    assert (
        "effective_file_transport_request_timeout_ms("
        in transport
    )
    assert (
        "timeout_override_ms.present"
        in timeout_contract
    )
    assert (
        '"XDEBUG_FILE_TRANSPORT_TIMEOUT_MS", 300000, 1, INT_MAX'
        in env_config
    )
    assert "strict_env_ll(" in env_config


def test_static_trace_result_limit_has_one_public_owner() -> None:
    runtime_int_max = 2_147_483_647
    huge_json_integer = 10**100
    for action in (
        "trace.driver",
        "trace.load",
        "trace.active_driver",
        "trace.active_driver_chain",
    ):
        schema, example = _request_schema_and_example(
            _action_entries()[action]
        )
        args_properties = schema["properties"]["args"]["properties"]
        limits_properties = schema["properties"]["limits"]["properties"]
        if action in {"trace.driver", "trace.load"}:
            assert "line_limit" not in args_properties
        assert limits_properties["max_results"]["minimum"] == 1
        assert (
            limits_properties["max_results"]["maximum"]
            == runtime_int_max
        )

        validator = Draft7Validator(schema)
        canonical = json.loads(json.dumps(example))
        canonical.setdefault("limits", {})["max_results"] = runtime_int_max
        assert validator.is_valid(canonical), list(
            validator.iter_errors(canonical)
        )

        for invalid_limit in (
            runtime_int_max + 1,
            huge_json_integer,
        ):
            invalid = json.loads(json.dumps(example))
            invalid.setdefault("limits", {})["max_results"] = invalid_limit
            assert not validator.is_valid(invalid)

        if action in {"trace.driver", "trace.load"}:
            legacy = json.loads(json.dumps(example))
            legacy["args"]["line_limit"] = 3
            assert not validator.is_valid(legacy)

    internal_schema = json.loads(
        (
            XDEBUG
            / "schemas/v1/internal/engine.request.schema.json"
        ).read_text(encoding="utf-8")
    )
    internal_validator = Draft7Validator(internal_schema)
    internal_requests = {
        "trace.driver": {
            "api_version": "xdebug.internal.v1",
            "action": "trace.driver",
            "target": {"session_id": "case_a"},
            "args": {"signal": "top.q"},
            "routing": {
                "session_id": "case_a",
                "daidir": "simv.daidir",
                "mode": "design",
            },
        },
        "trace.load": {
            "api_version": "xdebug.internal.v1",
            "action": "trace.load",
            "target": {"session_id": "case_a"},
            "args": {"signal": "top.q"},
            "routing": {
                "session_id": "case_a",
                "daidir": "simv.daidir",
                "mode": "design",
            },
        },
        "trace.active_driver": {
            "api_version": "xdebug.internal.v1",
            "action": "trace.active_driver",
            "target": {"session_id": "case_a"},
            "args": {"signal": "top.q", "time": "10ns"},
            "routing": {
                "session_id": "case_a",
                "daidir": "simv.daidir",
                "fsdb": "waves.fsdb",
                "mode": "combined",
            },
        },
        "trace.active_driver_chain": {
            "api_version": "xdebug.internal.v1",
            "action": "trace.active_driver_chain",
            "target": {"session_id": "case_a"},
            "args": {"signal": "top.q", "time": "10ns"},
            "routing": {
                "session_id": "case_a",
                "daidir": "simv.daidir",
                "fsdb": "waves.fsdb",
                "mode": "combined",
            },
        },
    }
    for request in internal_requests.values():
        at_maximum = json.loads(json.dumps(request))
        at_maximum["limits"] = {"max_results": runtime_int_max}
        assert internal_validator.is_valid(at_maximum), list(
            internal_validator.iter_errors(at_maximum)
        )
        for invalid_limit in (
            runtime_int_max + 1,
            huge_json_integer,
        ):
            invalid = json.loads(json.dumps(request))
            invalid["limits"] = {"max_results": invalid_limit}
            assert not internal_validator.is_valid(invalid)


def test_managed_session_ownership_token_is_sensitive_and_action_scoped() -> None:
    entries = _action_entries()
    managed_examples = {
        "session.open": "examples/requests/session.open.managed.json",
        "session.close": "examples/requests/session.close.managed.json",
    }
    token_shape = {
        "type": "string",
        "minLength": 64,
        "maxLength": 64,
        "pattern": "^[0-9a-f]{64}$",
    }

    for action, entry in entries.items():
        schema, basic_example = _request_schema_and_example(entry)
        args_properties = schema["properties"]["args"]["properties"]
        target_properties = schema["properties"]["target"].get(
            "properties", {}
        )
        assert "ownership_token" not in schema["properties"]
        assert "ownership_token" not in target_properties

        if action not in managed_examples:
            assert "ownership_token" not in args_properties, action
            continue

        published_shape = args_properties["ownership_token"]
        for key, value in token_shape.items():
            assert published_shape[key] == value
        assert "ownership_token" not in schema["properties"]["args"].get(
            "required", []
        )
        assert "ownership_token" not in basic_example["args"]

        validator = Draft7Validator(schema)
        managed_example = json.loads(
            (XDEBUG / managed_examples[action]).read_text(encoding="utf-8")
        )
        assert validator.is_valid(managed_example), list(
            validator.iter_errors(managed_example)
        )

        for invalid_token in (
            "0",
            "g" * 64,
            "A" * 64,
            "0" * 63,
            "0" * 65,
        ):
            invalid = json.loads(json.dumps(managed_example))
            invalid["args"]["ownership_token"] = invalid_token
            assert not validator.is_valid(invalid)

        misplaced_top_level = json.loads(json.dumps(basic_example))
        misplaced_top_level["ownership_token"] = "0" * 64
        assert not validator.is_valid(misplaced_top_level)
        misplaced_target = json.loads(json.dumps(basic_example))
        misplaced_target["target"]["ownership_token"] = "0" * 64
        assert not validator.is_valid(misplaced_target)

    for response_root in (
        XDEBUG / "schemas/v1/actions",
        XDEBUG / "examples/responses",
    ):
        for path in response_root.glob("*.response.schema.json"):
            assert '"ownership_token"' not in path.read_text(encoding="utf-8")
        if response_root.name == "responses":
            for path in response_root.glob("*.json"):
                assert '"ownership_token"' not in path.read_text(
                    encoding="utf-8"
                )


def test_engine_handlers_consume_contract_bound_requests() -> None:
    generator = _module("sync_runtime_request_schemas")
    specs = generator.action_specs()
    engine_actions = {
        spec["name"]
        for spec in specs
        if spec["handler_kind"] == "engine_forward"
    }
    actual_consumers = _discover_engine_runtime_consumers(engine_actions)
    contracts = generator.RUNTIME_CONSUMER_CONTRACTS_BY_ACTION
    assert set(actual_consumers) == engine_actions
    for action, consumer_id in actual_consumers.items():
        assert contracts[action].consumer_id == consumer_id


def test_session_transport_has_no_implicit_uds_default() -> None:
    dispatcher = (
        XDEBUG / "src" / "api" / "dispatcher.cpp"
    ).read_text(encoding="utf-8")
    assert 'record.transport.empty() ? "uds"' not in dispatcher
    assert (
        'backend_session.value("transport", std::string("uds"))'
        not in dispatcher
    )
    missing_transport = re.search(
        r'if \(!has_string\(backend_session, "transport"\)\) \{'
        r'.*?"INTERNAL_ENGINE_RESPONSE_INVALID"',
        dispatcher,
        re.DOTALL,
    )
    invalid_transport = re.search(
        r'if \(backend_transport != "uds" &&'
        r'.*?backend_transport != "tcp" &&'
        r'.*?backend_transport != "file"\) \{'
        r'.*?"INTERNAL_ENGINE_RESPONSE_INVALID"',
        dispatcher,
        re.DOTALL,
    )
    assert missing_transport is not None
    assert invalid_transport is not None


def test_internal_request_schema_is_generated_and_synced() -> None:
    assert _module("sync_internal_request_schema").main(["--check"]) == 0


def test_internal_runtime_manifest_and_action_schemas_match_union() -> None:
    module = _module("sync_internal_request_schema")
    aggregate = module.generate()
    expected_manifest, expected_actions, expected_helper_actions = (
        module.generate_runtime_artifacts(aggregate)
    )
    internal_root = XDEBUG / "schemas" / "v1" / "internal"
    manifest = json.loads(
        (internal_root / "engine.request.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest == expected_manifest
    assert manifest["action_count"] == len(expected_actions)
    assert set(manifest["actions"]) == set(expected_actions)

    action_root = internal_root / "actions"
    actual_paths = set(action_root.glob("*.request.schema.json"))
    expected_paths = {
        XDEBUG / schema_ref
        for schema_ref in manifest["actions"].values()
    }
    assert actual_paths == expected_paths
    for action, schema_ref in manifest["actions"].items():
        action_schema = json.loads(
            (XDEBUG / schema_ref).read_text(encoding="utf-8")
        )
        assert action_schema == expected_actions[action]
        Draft7Validator.check_schema(action_schema)

    helper_paths = set(
        (internal_root / "helper-actions").glob(
            "*.request.schema.json"
        )
    )
    expected_helper_paths = {
        XDEBUG / schema_ref
        for schema_ref in manifest["helper_envelope_schemas"].values()
    }
    assert helper_paths == expected_helper_paths
    assert set(manifest["helper_dispatch_kinds"]) == set(expected_actions)
    assert set(manifest["helper_envelope_schemas"]) == {
        action
        for action, kind in manifest["helper_dispatch_kinds"].items()
        if kind == "server_forward"
    }
    assert manifest["helper_dispatch_kinds"]["session.open"] == (
        "session_local"
    )
    assert manifest["helper_dispatch_kinds"]["server.ping"] == (
        "server_control"
    )
    assert manifest["helper_dispatch_kinds"]["expr.normalize"] == (
        "hybrid_local_forward"
    )
    assert manifest["helper_dispatch_kinds"]["apb.query"] == (
        "server_forward"
    )
    for action, schema_ref in manifest["helper_envelope_schemas"].items():
        helper_schema = json.loads(
            (XDEBUG / schema_ref).read_text(encoding="utf-8")
        )
        assert helper_schema == expected_helper_actions[action]
        assert helper_schema["additionalProperties"] is False
        assert helper_schema["properties"]["routing"][
            "additionalProperties"
        ] is False
        assert helper_schema["properties"]["limits"][
            "additionalProperties"
        ] is False
        Draft7Validator.check_schema(helper_schema)


def test_internal_helper_fast_path_preserves_server_full_validation() -> None:
    engine_query = (
        XDEBUG / "src" / "engine" / "engine_query.cpp"
    ).read_text(encoding="utf-8")
    server = (
        XDEBUG / "src" / "engine" / "server.cpp"
    ).read_text(encoding="utf-8")
    assert "validate_internal_request_for_helper" in engine_query
    forward = engine_query.split(
        "OrderedJson handle_engine_forward(", 1
    )[1].split("\nOrderedJson handle_query(", 1)[0]
    assert "used_forward_envelope && !sent && engine_error.is_null()" in (
        forward
    )
    assert "validator.validate_internal_request(request)" in forward
    assert forward.index("validator.validate_internal_request(request)") < (
        forward.index("if (!pending_error.is_null())")
    )
    assert "schema_validator.validate_internal_request(request)" in server
    assert "validate_internal_request_for_helper" not in server


def test_internal_request_schema_closes_payload_routing_and_observability() -> None:
    schema = json.loads(
        (
            XDEBUG
            / "schemas"
            / "v1"
            / "internal"
            / "engine.request.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft7Validator(schema)
    valid = {
        "api_version": "xdebug.internal.v1",
        "action": "value.at",
        "target": {"session_id": "case_a"},
        "args": {"signal": "top.clk", "time": "10ns"},
        "routing": {
            "session_id": "case_a",
            "fsdb": "/canonical/waves.fsdb",
            "mode": "waveform",
        },
        "observability": {
            "request_id": "r1",
            "trace_id": "trace-1",
            "span_id": "span-1",
            "parent_span_id": "span-0",
        },
    }
    assert validator.is_valid(valid)
    direct_waveform = {
        "api_version": "xdebug.internal.v1",
        "action": "value.at",
        "target": {"fsdb": "waves.fsdb"},
        "args": {"signal": "top.clk", "time": "10ns"},
        "routing": {
            "fsdb": "waves.fsdb",
            "mode": "waveform",
        },
    }
    assert validator.is_valid(direct_waveform)
    positive_timeout = json.loads(json.dumps(valid))
    positive_timeout["limits"] = {"timeout_ms": 1}
    assert validator.is_valid(positive_timeout)
    expression_only = {
        "api_version": "xdebug.internal.v1",
        "action": "expr.normalize",
        "args": {"expr": "a && b"},
    }
    assert validator.is_valid(expression_only)

    invalid_documents = []
    for path, value in (
        (("unexpected",), True),
        (("args", "typo"), True),
        (("routing", "auth_token"), "secret"),
        (("observability", "typo"), "x"),
        (("observability", "trace_id"), ""),
    ):
        bad = json.loads(json.dumps(valid))
        cursor = bad
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        invalid_documents.append(bad)
    for field in (
        "id",
        "trace_id",
        "span_id",
        "parent_span_id",
        "auth_token",
    ):
        bad = json.loads(json.dumps(valid))
        bad[field] = "transport-only"
        invalid_documents.append(bad)
    wrong_version = json.loads(json.dumps(valid))
    wrong_version["api_version"] = "xdebug.v1"
    invalid_documents.append(wrong_version)
    unknown_action = json.loads(json.dumps(valid))
    unknown_action["action"] = "value.at_typo"
    invalid_documents.append(unknown_action)
    output_leak = json.loads(json.dumps(valid))
    output_leak["output"] = {"format": "json"}
    invalid_documents.append(output_leak)
    missing_routing = json.loads(json.dumps(direct_waveform))
    missing_routing.pop("routing")
    invalid_documents.append(missing_routing)
    inconsistent_routing = json.loads(json.dumps(direct_waveform))
    inconsistent_routing["routing"]["mode"] = "combined"
    invalid_documents.append(inconsistent_routing)
    expression_with_routing = json.loads(json.dumps(expression_only))
    expression_with_routing["routing"] = {
        "daidir": "simv.daidir",
        "mode": "design",
    }
    invalid_documents.append(expression_with_routing)
    signal_without_routing = {
        "api_version": "xdebug.internal.v1",
        "action": "expr.normalize",
        "target": {"daidir": "simv.daidir"},
        "args": {"signal": "top.sig"},
    }
    invalid_documents.append(signal_without_routing)
    zero_timeout = json.loads(json.dumps(valid))
    zero_timeout["limits"] = {"timeout_ms": 0}
    invalid_documents.append(zero_timeout)

    assert all(
        not validator.is_valid(document)
        for document in invalid_documents
    )


def test_public_request_envelope_excludes_transport_metadata() -> None:
    catalog = json.loads(
        (XDEBUG / "specs" / "actions" / "actions.yaml").read_text(encoding="utf-8")
    )
    forbidden = {
        "id",
        "trace_id",
        "span_id",
        "parent_span_id",
        "auth_token",
    }
    for action in catalog["actions"]:
        schema = json.loads(
            (XDEBUG / action["schemas"]["request"]).read_text(encoding="utf-8")
        )
        properties = set(schema["properties"])
        assert not (properties & forbidden), action["name"]


def test_generated_action_metadata_is_synced() -> None:
    assert _module("sync_action_metadata").main(["--check"]) == 0


def test_embedded_help_text_is_synced() -> None:
    assert _module("sync_help_text").main(["--check"]) == 0


def test_xout_projection_uses_handler_base_and_overrides() -> None:
    renderer = XDEBUG / "src" / "api" / "xout_renderer.cpp"
    assert renderer.is_file()
    assert (XDEBUG / "src" / "api" / "text_response_builder.cpp").is_file()
    assert (XDEBUG / "src" / "api" / "text_response_builder.h").is_file()
    handler = (
        XDEBUG / "src" / "engine" / "service" / "engine_action_handler.h"
    ).read_text(encoding="utf-8")
    assert "virtual std::string render_xout" in handler
    renderer_text = renderer.read_text(encoding="utf-8")
    for action in ("value.at", "scope.list", "apb.query", "axi.query",
                   "stream.query", "trace.x_origin"):
        assert f'"{action}"' not in renderer_text
    assert "parse_xout" not in renderer_text
    engine_renderer_text = (
        XDEBUG / "src" / "engine" / "service" /
        "engine_action_handler.cpp"
    ).read_text(encoding="utf-8")
    for generic_renderer in (renderer_text, engine_renderer_text):
        assert "std::min(20" not in generic_renderer
        assert "(+ " not in generic_renderer

    makefile = (XDEBUG / "Makefile").read_text(encoding="utf-8")
    engine_sources = makefile.split("ENGINE_SRCS =", 1)[1].split("DESIGN_SRCS =", 1)[0]
    assert "xout_renderer.cpp" not in engine_sources
    assert "text_response_builder.cpp" in engine_sources


def test_trace_xout_uses_merged_source_windows_not_json_dump_tables() -> None:
    source = (
        XDEBUG / "src" / "engine" / "service" /
        "trace_source_path_formatter.cpp"
    ).read_text(encoding="utf-8")
    renderer = source.split(
        "std::string render_source_path_xout", 1
    )[1]
    assert 'text += "source: "' in source
    assert 'row.value("active", false) ? ">" : " "' in source
    assert 'out.emit_section("active_signals")' in source
    assert "group_source_items(" in renderer
    assert "emit_source_group_xout(" in renderer
    assert "emit_json_table(" not in renderer
    assert '"trace_hops"' not in renderer
    assert '"source_" + key' not in renderer


def test_stream_describe_runtime_identifiers_are_canonical() -> None:
    runtime_files = (
        XDEBUG / "src" / "engine" / "service" / "actions" / "stream",
        XDEBUG / "tests" / "unit" / "test_request_contract.cpp",
    )
    forbidden = ("stream_show", "StreamShow", "make_stream_show_handler")
    for root in runtime_files:
        sources = [root] if root.is_file() else [
            *root.rglob("*.cpp"),
            *root.rglob("*.h"),
        ]
        for source in sources:
            text = source.read_text(encoding="utf-8")
            for symbol in forbidden:
                assert symbol not in text, (
                    f"{source.relative_to(XDEBUG)} retains legacy identifier "
                    f"{symbol}"
                )


def test_renamed_action_runtime_identifiers_are_canonical() -> None:
    runtime_roots = (
        XDEBUG / "src",
        XDEBUG / "tests" / "unit",
    )
    forbidden_patterns = {
        "apb_cursor": re.compile(r"apb_cursor|ApbCursor"),
        "axi_cursor": re.compile(r"axi_cursor|AxiCursor"),
        "list_diff": re.compile(r"list_diff|ListDiff"),
        "rc_generate": re.compile(
            r"(?<!nwave_)rc_generate|(?<!Nwave)RcGenerate"
        ),
        "sampled_pulse_inspect": re.compile(
            r"(?<!signal_)sampled_pulse_inspect"
        ),
        "handshake_inspect": re.compile(
            r"(?<!protocol_)handshake_inspect"
        ),
        "detect_abnormal": re.compile(r"detect_abnormal|DetectAbnormal"),
        "trace_x": re.compile(
            r"trace_x_(?!origin_)|TraceX(?!Origin)"
        ),
    }
    for root in runtime_roots:
        for source in (*root.rglob("*.cpp"), *root.rglob("*.h")):
            text = source.read_text(encoding="utf-8")
            for retired_action, pattern in forbidden_patterns.items():
                assert pattern.search(text) is None, (
                    f"{source.relative_to(XDEBUG)} retains identifier for "
                    f"retired action {retired_action}: {pattern.pattern}"
                )

    required_identifiers = {
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "protocol"
        / "apb_transaction_cursor.cpp": (
            "ApbTransactionCursorHandler",
            "make_apb_transaction_cursor_handler",
        ),
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "protocol"
        / "axi_transaction_cursor.cpp": (
            "AxiTransactionCursorHandler",
            "make_axi_transaction_cursor_handler",
        ),
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "waveform"
        / "list_first_change.cpp": (
            "ListFirstChangeHandler",
            "make_list_first_change_handler",
        ),
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "waveform"
        / "nwave_rc_generate.cpp": (
            "NwaveRcGenerateHandler",
            "make_nwave_rc_generate_handler",
        ),
        XDEBUG
        / "src"
        / "engine"
        / "service"
        / "actions"
        / "combined"
        / "trace_x_origin.cpp": (
            "TraceXOriginHandler",
            "make_trace_x_origin_handler",
        ),
    }
    for source, identifiers in required_identifiers.items():
        text = source.read_text(encoding="utf-8")
        for identifier in identifiers:
            assert identifier in text, (
                f"{source.relative_to(XDEBUG)} is missing canonical "
                f"identifier {identifier}"
            )


def test_session_success_assertions_use_canonical_top_level_context() -> None:
    forbidden = '.get("session") ' + "or"
    retired_data_session = '["data"]' + '["session"]'
    for source in (XDEBUG / "tests").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert forbidden not in text, (
            f"{source.relative_to(XDEBUG)} falls back from canonical "
            "top-level session to a retired response shape"
        )
        assert retired_data_session not in text, (
            f"{source.relative_to(XDEBUG)} reads the retired duplicated "
            "session.open data.session record"
        )


def test_logic_value_has_single_core_owner() -> None:
    compatibility_header = (
        XDEBUG / "src" / "waveform" / "value" / "logic_value.h"
    )
    assert not compatibility_header.exists()

    allowed_local_include = (
        XDEBUG / "src" / "core" / "value" / "logic_value.cpp"
    )
    include_pattern = re.compile(
        r'#include\s+"(?P<path>[^"]*logic_value\.h)"'
    )
    waveform_namespace_exports = re.compile(
        r"xdebug_waveform::(?:"
        r"LogicValue|ScopedValueRenderFormat|ValueRenderFormat|"
        r"apply_value_render_format|apply_value_width_summary|"
        r"logic_value_compare_key|logic_value_compact_string|"
        r"logic_value_from_bits|logic_value_from_fsdb_raw|"
        r"logic_value_has_xz|logic_value_json|"
        r"parse_user_logic_literal|parse_value_render_format|"
        r"render_logic_value|current_value_render_format|"
        r"value_format_invalid_message|value_render_format_text"
        r")"
    )
    compatibility_text = (
        "Transitional source-" + "compatibility surface"
    )
    source_roots = (
        XDEBUG / "src",
        XDEBUG / "tests" / "unit",
    )
    for root in source_roots:
        for source in (*root.rglob("*.cpp"), *root.rglob("*.h")):
            text = source.read_text(encoding="utf-8")
            for include in include_pattern.finditer(text):
                if source == allowed_local_include:
                    assert include.group("path") == "logic_value.h"
                else:
                    assert include.group("path") == (
                        "core/value/logic_value.h"
                    ), (
                        f"{source.relative_to(XDEBUG)} includes non-canonical "
                        f"logic value header {include.group('path')}"
                    )
            assert waveform_namespace_exports.search(text) is None, (
                f"{source.relative_to(XDEBUG)} accesses canonical logic "
                "value APIs through the retired waveform namespace"
            )
            assert compatibility_text not in text, (
                f"{source.relative_to(XDEBUG)} retains compatibility surface"
            )


def test_stream_query_xout_restores_compact_domain_projection() -> None:
    source = (
        XDEBUG / "src" / "engine" / "service" / "actions" / "stream"
        / "stream_query.cpp"
    ).read_text(encoding="utf-8")

    assert "render_stream_query_xout(response)" in source
    assert "compact_stream_xout_value" in source
    assert "stream_fields_text" in source
    assert 'it.key() == "fields"' in source
    assert 'it.key() == "first_fields"' in source
    assert 'it.key() == "last_fields"' in source
    assert 'it.key() == "packet_stable_fields"' in source
    assert '"beat_fields_preview.total_beats"' in source
    assert '"beat_fields_preview.truncated"' in source
