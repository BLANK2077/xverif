"""Cached real-URG regression for the generated 375k-line coverage design."""
from __future__ import annotations

import json
from pathlib import Path


EXPECTED_METADATA = {
    "schema_version": "xcov.large-summary-fixture.v1",
    "leaf_count": 3000,
    "expected_instance_scope_count": 3001,
    "port_count_per_leaf": 25,
    "data_port_count_per_leaf": 10,
    "data_width_bits": 128,
    "simulation_cycles": 256,
    "rtl_line_count": 375_053,
    "generated_rtl": "large_design.sv",
}
ROOT_METRICS = {"line", "condition", "toggle", "fsm", "branch", "assert"}


def test_large_summary_fixture_is_typed_read_only_and_cache_stable(
    xverif_fixture, tmp_path, monkeypatch,
):
    from xcov import backend as backend_module
    from xcov.session import SessionManager
    from xcov.urg_runner import UrgRunner

    resources = xverif_fixture("xcov.large_summary")
    metadata = json.loads(
        (resources / "fixture_metadata.json").read_text(encoding="utf-8")
    )
    assert metadata == EXPECTED_METADATA
    probe = json.loads(
        (resources / "large_summary_probe.json").read_text(encoding="utf-8")
    )
    assert probe["instance_scope_count"] == 3001
    assert probe["functional_node_count"] > 0
    assert probe["assertion_node_count"] > 0
    assert probe["urg_options"] == [
        "-full64", "-xml_verbose", "-format", "text", "-show", "summary",
    ]

    def forbidden_npi():
        raise AssertionError("read-only large summary must not import pynpi")

    monkeypatch.setattr(backend_module, "import_pynpi", forbidden_npi)
    original_run = UrgRunner.run
    executions: list[list[str]] = []

    def counted_run(self, argv, **kwargs):
        executions.append([str(value) for value in argv])
        return original_run(self, argv, **kwargs)

    monkeypatch.setattr(UrgRunner, "run", counted_run)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    vdb = resources / "large_summary.vdb"
    sessions = SessionManager()

    first = sessions.open(
        str(vdb), name="large-summary-cold", cache_dir=str(cache_dir),
    )
    try:
        scopes = first.backend.scopes()
        metrics = first.backend.scope_metrics()
        functional = first.backend.scope_functional_from_urg()
        assertions = first.backend.scope_assert_from_urg()
        assert len(scopes) == 3001
        assert scopes[0]["full_name"] == "top"
        assert ROOT_METRICS.issubset(metrics["top"])
        root_score = sum(
            metrics["top"][metric]["pct"] for metric in ROOT_METRICS
        ) / len(ROOT_METRICS)
        assert 0.0 <= root_score <= 100.0
        assert functional
        assert assertions
        assert first.public_json()["npi_initialized"] is False
        cold = first.cache_status()
        assert cold["state"] == "ready"
        assert cold["hit"] is False
        assert cold["urg_execution"]["backend"] == "direct"
        assert cold["urg_execution"]["submitted"] is False
        assert cold["urg_execution"]["status"] == "completed"
        assert len(executions) == 1
        assert "-full64" in executions[0]
    finally:
        sessions.close("large-summary-cold")

    second = sessions.open(
        str(vdb), name="large-summary-warm", cache_dir=str(cache_dir),
    )
    try:
        assert len(second.backend.scopes()) == 3001
        assert second.backend.scope_functional_from_urg()
        assert second.backend.scope_assert_from_urg()
        assert second.public_json()["npi_initialized"] is False
        warm = second.cache_status()
        assert warm["state"] == "ready"
        assert warm["hit"] is True
        assert warm["urg_execution"]["submitted"] is False
        assert warm["urg_execution"]["status"] == "cache_hit"
        assert warm["key"] == cold["key"]
        assert len(executions) == 1
    finally:
        sessions.close("large-summary-warm")


def test_large_summary_generator_contract_is_not_checked_in_as_generated_rtl():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "large_summary"
    assert sorted(path.name for path in fixture.iterdir() if path.is_file()) == [
        "Makefile", "generate_large_fixture.py", "probe_large_fixture.py",
    ]
    assert not list(fixture.glob("*.sv"))
    generator = (fixture / "generate_large_fixture.py").read_text(encoding="utf-8")
    assert "LEAF_COUNT = 3000" in generator
    assert "PORT_COUNT = 25" in generator
    assert "DATA_PORT_COUNT = 10" in generator
    assert "DATA_WIDTH = 128" in generator
    assert "SIM_CYCLES = 256" in generator
    assert "TARGET_RTL_LINES = 375_053" in generator
    recipe = (fixture / "Makefile").read_text(encoding="utf-8")
    assert recipe.count("-full64") == 1
