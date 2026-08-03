import json
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _by_name(document: dict) -> dict[str, dict]:
    return {item["name"]: item for item in document["assertions"]}


def _nonzero_events(assertion: dict) -> set[tuple[int, int, str]]:
    return {
        (event["begin_time_raw"], event["end_time_raw"], event["value"])
        for event in assertion["events"]
        if event["begin_time_raw"] != event["end_time_raw"]
    }


def _by_full_name(items: list[dict], key: str = "full_name") -> dict[str, dict]:
    return {item[key]: item for item in items}


def _event_facts(assertion: dict) -> set[tuple[int, int, int, str]]:
    return {
        (
            event["time_raw"],
            event["begin_time_raw"],
            event["end_time_raw"],
            event["value"],
        )
        for event in assertion["events"]
    }


def test_npi_fsdb_sva_observed_contract(xverif_fixture) -> None:
    resources = xverif_fixture("xdebug.npi_fsdb_sva") / "out"
    positive = _load(resources / "positive/probe.json")
    success_only = _load(resources / "success_only/probe.json")
    control = _load(resources / "control/probe.json")

    assert positive["schema_version"] == "npi-fsdb-sva-probe.v1"
    assert positive["file_has_assertion_property_ok"] is True
    # X-2025.06-SP1 returns false even though assertion handles are iterable.
    # Keep this surprising observation explicit instead of treating the file
    # property as a reliable preflight.
    assert positive["file_has_assertion"] is False
    assert control["file_has_assertion_property_ok"] is True
    assert control["file_has_assertion"] is False
    assert control["assertions"] == []

    assertions = _by_name(positive)
    success_only_assertions = _by_name(success_only)
    assert set(assertions) == {
        "a_req_ack",
        "a_overlap",
        "a_incomplete",
        "u_guard",
        "c_req_ack",
        "unnamed$$_0",
    }
    assert {name: item["assertion_type"] for name, item in assertions.items()} == {
        "a_req_ack": "assert",
        "a_overlap": "assert",
        "a_incomplete": "assert",
        "u_guard": "assume",
        "c_req_ack": "cover",
        "unnamed$$_0": "assert",
    }
    assert all(
        item["derived_path"].startswith("sva_fsdb_fixture_top.")
        for item in assertions.values()
    )

    for assertion in assertions.values():
        for event in assertion["events"]:
            assert event["time_ok"] is True
            assert event["duration_ok"] is True
            assert event["value_format_ok"] is True
            assert event["value_ok"] is True
            assert event["sequence_number_ok"] is True
            assert event["native_value_format"] == "string"
            assert event["returned_value_format"] == "string"
            assert event["sequence_number"] == 0

    assert _nonzero_events(assertions["a_req_ack"]) == {
        (35000, 45000, "success"),
        (65000, 75000, "failure"),
    }
    assert _nonzero_events(assertions["a_overlap"]) == {
        (115000, 135000, "success"),
        (125000, 135000, "success"),
    }
    assert _nonzero_events(assertions["c_req_ack"]) == {
        (35000, 45000, "match"),
    }
    assert any(
        event["time_raw"] == 155000 and event["value"] == "failure"
        for event in assertions["u_guard"]["events"]
    )
    assert any(
        event["time_raw"] == 155000 and event["value"] == "failure"
        for event in assertions["unnamed$$_0"]["events"]
    )

    # The req sampled at 85 ns is disabled by reset at 95 ns. No abort or
    # incomplete record is exposed for that attempt in the FSDB event stream.
    assert not any(
        event["begin_time_raw"] == 85000
        for event in assertions["a_req_ack"]["events"]
    )
    assert _nonzero_events(assertions["a_incomplete"]) == {
        (175000, 200000, "incomplete"),
    }
    assert not any(
        event["value"] in {"abort", "aborted"}
        for assertion in assertions.values()
        for event in assertion["events"]
    )

    # +fsdb+sva_vacuous adds zero-duration implication outcomes, but NPI
    # encodes them as ordinary "success" instead of a distinct vacuous value.
    assert len(success_only_assertions["a_req_ack"]["events"]) == 2
    assert len(assertions["a_req_ack"]["events"]) == 16
    assert _nonzero_events(success_only_assertions["a_req_ack"]) == (
        _nonzero_events(assertions["a_req_ack"])
    )
    assert len(success_only_assertions["a_overlap"]["events"]) == 2
    assert len(assertions["a_overlap"]["events"]) == 17


def test_npi_daidir_fsdb_sva_join_contract(xverif_fixture) -> None:
    resources = xverif_fixture("xdebug.npi_fsdb_sva") / "out"
    combined = _load(resources / "join/probe.json")
    design_only = _load(resources / "join/design_probe.json")

    assert combined["schema_version"] == "npi-daidir-fsdb-sva-probe.v1"
    assert combined["diagnostics"] == {
        "design_assertion_count": 17,
        "wave_assertion_count": 17,
        "exact_join_count": 17,
        "ambiguous_join_count": 0,
        "unmatched_join_count": 0,
        "join_policy": "exact canonical hierarchical path plus assertion kind",
        "local_name_candidates_are_diagnostic_only": True,
    }
    assert all(join["status"] == "exact" for join in combined["joins"])
    assert all(len(join["design_indices"]) == 1 for join in combined["joins"])

    design = _by_full_name(combined["design_assertions"])
    wave = _by_full_name(combined["wave_assertions"], "canonical_path")
    assert set(design) == set(wave)
    assert {
        item["assertion_kind"] for item in combined["design_assertions"]
    } == {"assert", "assume", "cover"}
    assert all(item["file"].endswith("sva_daidir_join_fixture.sv") for item in design.values())
    assert all(item["line"] > 0 for item in design.values())
    # X-2025.06-SP1 exposes the SVA AST but returns an empty npiDecompile
    # string for every assertion and property/sequence object in this fixture.
    assert all(item["decompile"] == "" for item in design.values())

    named = design["sva_daidir_join_fixture_top.a_top_named"]
    assert named["property"]["object_type"] == "property_inst"
    assert named["property_declaration"]["full_name"] == (
        "sva_daidir_join_fixture_top.p_top_req_ack"
    )
    assert named["property_expression"]["operation_type"] == (
        "overlap_implication"
    )
    assert named["clocking_event"]["operation_type"] == "posedge"
    assert named["disable_condition"]["operation_type"] == "logical_not"
    assert {item["name"] for item in named["references"]} == {"req", "ack"}
    assert named["has_pass_statement"] is False
    assert named["has_fail_statement"] is False

    inline = design["sva_daidir_join_fixture_top.a_top_inline"]
    assert inline["property"]["object_type"] == "property_spec"
    assert inline["property_declaration"] is None

    immediate = design["sva_daidir_join_fixture_top.unnamed$$_0"]
    assert immediate["object_type"] == "immediate_assert"
    assert immediate["is_deferred"] is False
    assert immediate["has_pass_statement"] is False
    assert immediate["has_fail_statement"] is True
    assert immediate["fail_statement"]["object_type"] == "system_task_call"

    properties = _by_full_name(combined["design_property_declarations"])
    top_property = properties["sva_daidir_join_fixture_top.p_top_req_ack"]
    assert top_property["expression_tree"]["operation_type"] == (
        "overlap_implication"
    )
    assert top_property["clocking_event_tree"]["operands"][0]["name"] == "clk"
    assert top_property["disable_condition_tree"]["operands"][0]["name"] == (
        "rst_n"
    )

    sequences = _by_full_name(combined["design_sequence_declarations"])
    top_sequence = sequences["sva_daidir_join_fixture_top.s_top_req_ack"]
    assert top_sequence["expression_tree"]["operation_type"] == "cycle_delay"
    assert {item["name"] for item in top_sequence["references"]} == {"req", "ack"}

    generated = {
        path for path in design if ".g_leaf[" in path and path.endswith(".a_local")
    }
    assert generated == {
        "sva_daidir_join_fixture_top.g_leaf[0].u_leaf.a_local",
        "sva_daidir_join_fixture_top.g_leaf[1].u_leaf.a_local",
    }
    bound = {path for path in design if path.endswith(".u_bound.b_req_ack")}
    assert len(bound) == 3

    # Every repeated local name has two diagnostic candidates, but the exact
    # hierarchy remains unique and is the only accepted join.
    repeated = [
        join
        for join in combined["joins"]
        if join["wave_path"].endswith(".a_local")
    ]
    assert len(repeated) == 3
    assert all(len(join["local_name_candidates"]) == 2 for join in repeated)

    assert any(
        event["value"] == "failure" and event["time_raw"] == 75000
        for event in wave["sva_daidir_join_fixture_top.a_top_named"]["events"]
    )
    assert any(
        event["value"] == "match"
        for event in wave["sva_daidir_join_fixture_top.c_top_sequence"]["events"]
    )

    assert design_only["inputs"]["fsdb"] is None
    assert design_only["wave_assertions"] == []
    assert design_only["joins"] == []
    assert design_only["design_assertions"] == combined["design_assertions"]


def test_combined_load_preserves_fsdb_sva_events(xverif_fixture) -> None:
    resources = xverif_fixture("xdebug.npi_fsdb_sva") / "out"
    fsdb_only = _load(resources / "positive/probe.json")
    combined = _load(resources / "positive/combined_probe.json")

    fsdb_assertions = {
        item["derived_path"]: item for item in fsdb_only["assertions"]
    }
    combined_assertions = {
        item["canonical_path"]: item for item in combined["wave_assertions"]
    }
    assert set(fsdb_assertions) == set(combined_assertions)
    for path, assertion in fsdb_assertions.items():
        assert _event_facts(assertion) == _event_facts(combined_assertions[path])
    assert combined["diagnostics"]["exact_join_count"] == 6
    assert combined["diagnostics"]["unmatched_join_count"] == 0
