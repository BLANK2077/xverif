from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest


XDEBUG = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACTS = _load_module(
    "xdebug_non_sampling_response_contracts",
    XDEBUG / "specs" / "non_sampling_response_contracts.py",
)
GENERATOR = _load_module(
    "xdebug_non_sampling_test_generator",
    XDEBUG / "tools" / "sync_response_schemas.py",
)
ACTION_CONTRACTS = sys.modules["action_contracts"]

DATA_POINTER = CONTRACTS.DATA_POINTER
NON_SAMPLING_EXTERNAL_DEFINITIONS = (
    CONTRACTS.NON_SAMPLING_EXTERNAL_DEFINITIONS
)
NON_SAMPLING_RESPONSE_ACTIONS = CONTRACTS.NON_SAMPLING_RESPONSE_ACTIONS
SUMMARY_POINTER = CONTRACTS.SUMMARY_POINTER
non_sampling_explicit_response_schema = (
    CONTRACTS.non_sampling_explicit_response_schema
)
non_sampling_required_external_definitions = (
    CONTRACTS.non_sampling_required_external_definitions
)
non_sampling_response_contract_definitions = (
    CONTRACTS.non_sampling_response_contract_definitions
)
non_sampling_success_pairing_schema = (
    CONTRACTS.non_sampling_success_pairing_schema
)
non_sampling_success_response_variants = (
    CONTRACTS.non_sampling_success_response_variants
)


EXPECTED_ACTIONS = {
    "apb.config.list",
    "apb.config.load",
    "apb.query",
    "apb.statistics",
    "apb.transaction.cursor",
    "apb.transfer_window",
    "axi.analysis",
    "axi.channel_stall",
    "axi.config.list",
    "axi.config.load",
    "axi.export",
    "axi.latency_outlier",
    "axi.outstanding_timeline",
    "axi.query",
    "axi.request_response_pair",
    "axi.statistics",
    "axi.transaction.cursor",
    "event.config.list",
    "event.config.load",
    "expr.normalize",
    "list.add",
    "list.create",
    "list.load",
    "list.delete",
    "list.export",
    "list.first_change",
    "list.show",
    "list.validate",
    "nwave.rc.generate",
    "scope.list",
    "signal.anomaly.inspect",
    "signal.canonicalize",
    "signal.changes",
    "signal.resolve",
    "signal.stability",
    "signal.xz_verify",
    "stream.config.get",
    "stream.config.list",
    "stream.config.load",
    "stream.describe",
    "stream.export",
    "stream.query",
    "stream.validate",
    "trace.active_driver",
    "trace.active_driver_chain",
    "trace.driver",
    "trace.load",
    "trace.x_origin",
    "waveform.cursor.delete",
    "waveform.cursor.get",
    "waveform.cursor.list",
    "waveform.cursor.set",
    "waveform.cursor.use",
}


def _definitions() -> dict[str, dict[str, Any]]:
    definitions = non_sampling_response_contract_definitions()
    definitions.update(
        {
            "commonBlock": GENERATOR.common_block_schema(),
            "logicValue": GENERATOR.logic_value_schema(),
            "reset": ACTION_CONTRACTS.reset_schema(),
            "suggestedNextAction": (
                GENERATOR.suggested_next_action_schema()
            ),
            "valueWidthDiagnostic": (
                GENERATOR.value_width_diagnostic_schema()
            ),
        }
    )
    return definitions


DEFINITIONS = _definitions()


def _root(schema: dict[str, Any]) -> dict[str, Any]:
    return {"$defs": copy.deepcopy(DEFINITIONS), **copy.deepcopy(schema)}


def _resolve(schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    prefix = "#/$defs/"
    assert ref.startswith(prefix)
    return DEFINITIONS[ref[len(prefix) :]]


def _materialize(schema: dict[str, Any]) -> Any:
    schema = _resolve(schema)
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if "oneOf" in schema:
        return _materialize(schema["oneOf"][0])
    if "anyOf" in schema:
        return _materialize(schema["anyOf"][0])
    if "enum" in schema:
        return copy.deepcopy(schema["enum"][0])

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = schema_type[0]
    if schema_type == "null":
        return None
    if schema_type == "boolean":
        return False
    if schema_type == "integer":
        return max(0, schema.get("minimum", 0))
    if schema_type == "number":
        return max(0, schema.get("minimum", 0))
    if schema_type == "string":
        return "x" if schema.get("minLength", 0) else ""
    if schema_type == "array":
        count = schema.get("minItems", 0)
        value = [_materialize(schema["items"]) for _ in range(count)]
        if "contains" in schema and not value:
            value.append(_materialize(schema["contains"]))
        elif "contains" in schema:
            value[0] = _materialize(schema["contains"])
        contains_constraints = [
            constraint["contains"]
            for constraint in schema.get("allOf", [])
            if isinstance(constraint, dict)
            and isinstance(constraint.get("contains"), dict)
        ]
        for index, constraint in enumerate(contains_constraints):
            while len(value) <= index:
                value.append(_materialize(schema["items"]))
            if isinstance(value[index], dict):
                item_schema = _resolve(schema["items"])
                _apply_constraint(
                    value[index],
                    constraint,
                    item_schema.get("properties", {}),
                )
        return value
    if schema_type == "object":
        value: dict[str, Any] = {}
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            value[name] = _materialize(properties[name])
        additional = schema.get("additionalProperties")
        while (
            isinstance(additional, dict)
            and len(value) < schema.get("minProperties", 0)
        ):
            value[f"key_{len(value)}"] = _materialize(additional)
        for constraint in schema.get("allOf", []):
            _apply_constraint(value, constraint, properties)
        return value
    raise AssertionError(f"cannot materialize schema: {schema}")


def _apply_constraint(
    value: dict[str, Any],
    schema: dict[str, Any],
    available_properties: dict[str, Any] | None = None,
) -> None:
    schema = _resolve(schema)
    properties = {
        **(available_properties or {}),
        **schema.get("properties", {}),
    }
    if "oneOf" in schema:
        _apply_constraint(value, schema["oneOf"][0], properties)
        return
    if "anyOf" in schema:
        _apply_constraint(value, schema["anyOf"][0], properties)
        return
    for constraint in schema.get("allOf", []):
        _apply_constraint(value, constraint, properties)
    for name in schema.get("required", []):
        value[name] = _materialize(properties.get(name, {}))
    for name, child in schema.get("properties", {}).items():
        if "const" in child:
            value[name] = copy.deepcopy(child["const"])
    forbidden = schema.get("not", {}).get("anyOf", [])
    for item in forbidden:
        for name in item.get("required", []):
            value.pop(name, None)


def _variant(action: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for variant in non_sampling_success_response_variants(action):
        if variant.name == name:
            return (
                _materialize(variant.summary),
                _materialize(variant.data),
            )
    raise AssertionError(f"{action}: unknown variant {name}")


def _assert_pair_valid(
    action: str,
    summary: dict[str, Any],
    data: dict[str, Any],
) -> None:
    jsonschema.Draft7Validator(_root(
        non_sampling_success_pairing_schema(action)
    )).validate({"summary": summary, "data": data})


def _assert_pair_invalid(
    action: str,
    summary: dict[str, Any],
    data: dict[str, Any],
) -> None:
    with pytest.raises(jsonschema.ValidationError):
        _assert_pair_valid(action, summary, data)


def test_exact_action_and_external_definition_coverage() -> None:
    assert set(NON_SAMPLING_RESPONSE_ACTIONS) == EXPECTED_ACTIONS
    assert len(NON_SAMPLING_RESPONSE_ACTIONS) == 53
    assert non_sampling_required_external_definitions() == {
        "commonBlock",
        "logicValue",
        "reset",
        "suggestedNextAction",
        "valueWidthDiagnostic",
    }
    assert (
        NON_SAMPLING_EXTERNAL_DEFINITIONS
        == non_sampling_required_external_definitions()
    )


def test_all_reachable_variants_have_valid_minimal_witnesses() -> None:
    variant_count = 0
    for action in sorted(NON_SAMPLING_RESPONSE_ACTIONS):
        pairing = _root(non_sampling_success_pairing_schema(action))
        jsonschema.Draft7Validator.check_schema(pairing)
        validator = jsonschema.Draft7Validator(pairing)
        variants = non_sampling_success_response_variants(action)
        assert variants
        for variant in variants:
            variant_count += 1
            instance = {
                "summary": _materialize(variant.summary),
                "data": _materialize(variant.data),
            }
            errors = list(validator.iter_errors(instance))
            assert not errors, (
                f"{action}/{variant.name}: "
                + "; ".join(error.message for error in errors)
            )
    assert variant_count == 130


def test_all_registered_success_examples_match_a_correlated_variant() -> None:
    failures: list[str] = []
    response_count = 0
    witness_count = 0
    entries = {
        entry["name"]: entry
        for entry in GENERATOR.load_action_entries()
        if entry["name"] in EXPECTED_ACTIONS
    }
    assert set(entries) == EXPECTED_ACTIONS
    for action in sorted(entries):
        validator = jsonschema.Draft7Validator(
            _root(non_sampling_success_pairing_schema(action))
        )
        for example in GENERATOR.response_examples(entries[action]):
            response_count += 1
            if not example["ok"]:
                continue
            witness_count += 1
            errors = list(
                validator.iter_errors(
                    {
                        "summary": example["summary"],
                        "data": example["data"],
                    }
                )
            )
            if errors:
                failures.append(
                    f"{action}: {errors[0].json_path}: "
                    f"{errors[0].message}"
                )
    assert response_count == 60
    assert witness_count == 59
    assert not failures, "\n".join(failures)


def test_response_generator_uses_the_strict_correlated_variants() -> None:
    entries = {
        entry["name"]: entry
        for entry in GENERATOR.load_action_entries()
        if entry["name"] in EXPECTED_ACTIONS
    }
    for action in sorted(entries):
        generated = GENERATOR.response_schema(entries[action])
        variants = non_sampling_success_response_variants(action)
        for index, variant in enumerate(variants):
            assert generated["$defs"][f"successSummary{index}"] == (
                GENERATOR.add_shared_success_fields(
                    action, variant.summary
                )
            )
            assert generated["$defs"][f"successData{index}"] == (
                variant.data
            )


def test_response_definition_closure_has_deterministic_order() -> None:
    selected = GENERATOR.referenced_definition_closure(
        [
            {
                "allOf": [
                    {"$ref": "#/$defs/zRoot"},
                    {"$ref": "#/$defs/aRoot"},
                ]
            }
        ],
        {
            "zRoot": {"$ref": "#/$defs/mLeaf"},
            "aRoot": {"type": "string"},
            "mLeaf": {"type": "integer"},
        },
        external=frozenset(),
        owner="determinism-test",
    )
    assert list(selected) == ["aRoot", "mLeaf", "zRoot"]


def test_old_witness_optional_trace_members_remain_reachable() -> None:
    summary, data = _variant("trace.x_origin", "traced")
    data["chains"] = [
        _materialize(DEFINITIONS["nonSamplingXOriginChain"])
    ]
    summary["chain_count"] = 1
    summary["returned_count"] = 1
    summary["total_count"] = 1
    assert "origin" not in data["chains"][0]
    assert "depth_frontiers" not in data
    assert "suggested_next_actions" not in data
    _assert_pair_valid("trace.x_origin", summary, data)

    summary, data = _variant("trace.active_driver_chain", "normal")
    assert "ambiguity_evidence" not in data
    assert "depth_frontiers" not in data
    assert "suggested_next_actions" not in data
    _assert_pair_valid("trace.active_driver_chain", summary, data)


def test_projection_api_preserves_strict_root_shapes() -> None:
    for action in EXPECTED_ACTIONS:
        assert non_sampling_explicit_response_schema(
            action, SUMMARY_POINTER
        )
        assert non_sampling_explicit_response_schema(
            action, DATA_POINTER
        )
    assert non_sampling_explicit_response_schema(
        "value.at", SUMMARY_POINTER
    ) is None
    assert non_sampling_explicit_response_schema(
        "list.add", DATA_POINTER + "/signals"
    ) is None


def test_signal_stability_publishes_one_canonical_evidence_series() -> None:
    expected_data_fields = {
        "signal",
        "begin",
        "end",
        "changes",
        "includes_initial_value",
    }
    for variant in non_sampling_success_response_variants(
        "signal.stability"
    ):
        summary_properties = set(variant.summary["properties"])
        data_properties = set(variant.data["properties"])
        assert not {"signal", "value"}.intersection(summary_properties)
        assert data_properties == expected_data_fields
        assert not {
            "initial_value",
            "final_value",
            "first_change",
            "last_change",
            "first_change_time",
        }.intersection(data_properties)

    summary, data = _variant("signal.stability", "stable_populated")
    data["initial_value"] = _materialize(DEFINITIONS["logicValue"])
    _assert_pair_invalid("signal.stability", summary, data)

    unstable_summary, unstable_data = _variant(
        "signal.stability", "unstable"
    )
    assert unstable_summary["scan_complete"] is False
    assert unstable_summary["analysis_complete"] is True
    assert unstable_summary["response_truncated"] is False
    assert unstable_summary["truncation_scopes"] == [
        "scan_after_first_transition"
    ]
    _assert_pair_valid(
        "signal.stability", unstable_summary, unstable_data
    )
    for field, invalid_value in (
        ("scan_complete", True),
        ("analysis_complete", False),
        ("response_truncated", True),
        ("truncation_scopes", []),
        ("truncation_scopes", ["analysis_changes"]),
    ):
        mutated_summary = copy.deepcopy(unstable_summary)
        mutated_summary[field] = invalid_value
        _assert_pair_invalid(
            "signal.stability", mutated_summary, unstable_data
        )


def test_signal_stability_runtime_marks_intentional_early_stop() -> None:
    source = (
        XDEBUG
        / "src"
        / "waveform"
        / "server"
        / "service"
        / "signal_analysis.cpp"
    ).read_text(encoding="utf-8")
    assert 'truncation_scopes.push_back("scan_after_first_transition")' in source
    assert "if (!stable)" in source
    assert "stable,\n        true,\n        false," in source
    assert "change_row_count,\n        truncation_scopes);" in source


def test_every_business_object_is_closed_or_a_narrow_dynamic_map() -> None:
    roots: list[dict[str, Any]] = list(DEFINITIONS.values())
    for action in EXPECTED_ACTIONS:
        for variant in non_sampling_success_response_variants(action):
            roots.extend((variant.summary, variant.data))

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            assert "additionalProperties" in node
            additional = node["additionalProperties"]
            assert additional is not True
            if node.get("x-dynamic-map"):
                assert isinstance(additional, dict)
                assert additional
            else:
                assert additional is False
        ref = node.get("$ref")
        if isinstance(ref, str):
            assert "jsonValue" not in ref
            assert "jsonObject" not in ref
        for child in node.values():
            visit(child)

    for root in roots:
        visit(root)


def test_unknown_fields_and_type_or_enum_drift_are_rejected() -> None:
    summary, data = _variant("list.add", "added")
    data["unknown"] = True
    _assert_pair_invalid("list.add", summary, data)

    summary, data = _variant("list.show", "shown")
    data["signals"] = [{"index": 0, "signal": "top.sig"}]
    _assert_pair_invalid("list.show", summary, data)

    summary, data = _variant("list.validate", "all_found")
    data["signals"] = [{"signal": "top.sig", "status": "maybe"}]
    _assert_pair_invalid("list.validate", summary, data)

    summary, data = _variant("scope.list", "listed")
    summary["kind"] = "whatever"
    _assert_pair_invalid("scope.list", summary, data)

    summary, data = _variant("apb.config.load", "loaded")
    summary["status"] = "ok"
    _assert_pair_invalid("apb.config.load", summary, data)


def test_axi_analysis_osd_extrema_are_exact_integer_counts() -> None:
    summary, data = _variant("axi.analysis", "osd")
    _assert_pair_valid("axi.analysis", summary, data)

    fractional_summary = copy.deepcopy(summary)
    fractional_summary["min"] = 0.5
    _assert_pair_invalid("axi.analysis", fractional_summary, data)

    nonempty_data = copy.deepcopy(data)
    nonempty_data["osd"]["read"] = {
        "samples": 2,
        "min": 0,
        "max": 1,
        "avg": 0.5,
    }
    _assert_pair_valid("axi.analysis", summary, nonempty_data)

    fractional_data = copy.deepcopy(nonempty_data)
    fractional_data["osd"]["read"]["max"] = 1.5
    _assert_pair_invalid("axi.analysis", summary, fractional_data)


@pytest.mark.parametrize(
    ("action", "summary_variant", "data_variant"),
    [
        ("apb.config.list", "named", "list"),
        ("event.config.list", "named", "list"),
        ("apb.query", "count", "single_found"),
        ("axi.query", "transaction_count", "transaction_found"),
        ("list.export", "preview", "written"),
        ("list.first_change", "found", "not_found"),
        ("signal.xz_verify", "pass", "fail"),
        ("axi.analysis", "latency_nonempty", "osd"),
        ("stream.export", "transfer_preview", "transfer_written"),
        ("trace.x_origin", "not_x", "traced"),
    ],
)
def test_cross_variant_summary_data_pairing_is_rejected(
    action: str,
    summary_variant: str,
    data_variant: str,
) -> None:
    summary, _ = _variant(action, summary_variant)
    _, data = _variant(action, data_variant)
    if action == "trace.x_origin" and data_variant == "traced":
        data["chains"] = [
            _materialize(DEFINITIONS["nonSamplingXOriginChain"])
        ]
    _assert_pair_invalid(action, summary, data)


def test_trace_continuation_advice_is_data_not_summary() -> None:
    summary, data = _variant(
        "trace.active_driver_chain", "depth_limited"
    )
    assert "suggested_next_actions" not in summary
    assert "suggested_next_actions" in data
    _assert_pair_valid("trace.active_driver_chain", summary, data)

    summary, data = _variant("trace.x_origin", "traced")
    data["depth_frontiers"] = [
        _materialize(
            DEFINITIONS["nonSamplingXOriginDepthFrontier"]
        )
    ]
    data["suggested_next_actions"] = [
        _materialize(DEFINITIONS["suggestedNextAction"])
    ]
    assert "suggested_next_actions" not in summary
    _assert_pair_valid("trace.x_origin", summary, data)


def test_axi_export_preview_shape_is_not_reachable() -> None:
    variants = non_sampling_success_response_variants("axi.export")
    assert [variant.name for variant in variants] == ["written"]
    summary, data = _variant("axi.export", "written")
    summary["status"] = "preview"
    summary["output_written"] = False
    _assert_pair_invalid("axi.export", summary, data)
