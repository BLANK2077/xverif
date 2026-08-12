import json
from types import SimpleNamespace
from pathlib import Path

import jsonschema

from testinfra.xverif_test.reports import ResultManager, _prune_results


ROOT = Path(__file__).resolve().parents[2]


def test_minimal_execution_report_matches_schema() -> None:
    schema = json.loads(
        (ROOT / "testinfra/schemas/execution-report.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    report = {
        "schema_version": "xverif-execution-report.v1",
        "gate": "fast",
        "catalog_version": "xverif-test-catalog.v1",
        "exitstatus": 0,
        "started_at": "2026-08-12T20:00:00+08:00",
        "finished_at": "2026-08-12T20:00:01+08:00",
        "duration_sec": 1.0,
        "counts": {"passed": 1},
        "suite_duration_sec": {"testinfra.unit": 0.01},
        "items": [
            {
                "nodeid": "testinfra/tests/test_catalog.py::test_catalog_loads",
                "suite_id": "testinfra.unit",
                "phase": "call",
                "outcome": "passed",
                "duration_sec": 0.01,
                "error_layer": None,
            }
        ],
    }
    jsonschema.Draft202012Validator(schema).validate(report)


def test_legacy_execution_report_without_wall_time_still_matches_v1_schema() -> None:
    schema = json.loads(
        (ROOT / "testinfra/schemas/execution-report.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    report = {
        "schema_version": "xverif-execution-report.v1",
        "gate": "fast",
        "catalog_version": "xverif-test-catalog.v1",
        "exitstatus": 0,
        "counts": {},
        "items": [],
    }
    jsonschema.Draft202012Validator(schema).validate(report)


def test_setup_skip_is_counted_in_json_report(tmp_path: Path) -> None:
    manager = ResultManager(tmp_path, "nightly", "xverif-test-catalog.v1")
    report = SimpleNamespace(
        when="setup",
        user_properties=[("xverif_suite", "optional.demo")],
        skipped=True,
        passed=False,
        failed=False,
        nodeid="::suite::optional.demo",
        outcome="skipped",
        duration=0.01,
        capstdout="",
        capstderr="",
        longrepr=None,
    )
    manager.record_report(report)
    manager.finish(0)
    payload = json.loads((manager.run_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["counts"] == {"skipped": 1}
    assert payload["duration_sec"] >= 0
    assert payload["suite_duration_sec"] == {"optional.demo": 0.01}
    assert payload["items"][0]["phase"] == "setup"


def test_failed_teardown_preserves_error_layer_and_captured_output(tmp_path: Path) -> None:
    manager = ResultManager(tmp_path, "regression", "xverif-test-catalog.v1")
    report = SimpleNamespace(
        when="teardown",
        user_properties=[("xverif_suite", "xdebug.session")],
        skipped=False,
        passed=False,
        failed=True,
        nodeid="xdebug/tests/session/test_lifecycle.py::test_close",
        outcome="failed",
        duration=1.25,
        capstdout="stdout evidence\n",
        capstderr="stderr evidence\n",
        longrepr="cleanup failed; error_layer=session_manager; more",
    )
    manager.record_report(report)
    manager.finish(1)
    payload = json.loads((manager.run_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["counts"] == {"failed": 1}
    assert payload["items"] == [{
        "nodeid": report.nodeid, "suite_id": "xdebug.session", "phase": "teardown",
        "outcome": "failed", "duration_sec": 1.25, "error_layer": "session_manager",
    }]
    captured = (manager.run_dir / "suites/xdebug.session/pytest-captured.log").read_text(encoding="utf-8")
    assert captured == "stdout evidence\nstderr evidence\n"


def test_result_pruning_recognizes_fixture_timing_only_run(tmp_path: Path) -> None:
    results = tmp_path / ".xverif-test-results"
    run = results / "fixture-operation"
    run.mkdir(parents=True)
    (run / "timing.json").write_text(json.dumps({
        "schema_version": "xverif-operation-timing.v1",
        "operation": "fixture-prepare",
        "outcome": "passed",
    }))

    _prune_results(results)

    assert run.exists()
