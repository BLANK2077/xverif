"""Real VCS/URG coverage export contract for heterogeneous branch decisions."""
from __future__ import annotations

import json
import re
from pathlib import Path


ACTIVE_SCOPE = "top.u_cluster_a.g_wrapper_level.u_fabric.g_lane[0].g_even.u_worker"
SPARSE_SCOPE = "top.u_cluster_sparse.g_wrapper_level.u_fabric.g_lane[0].g_even.u_worker"
METRICS = ("line", "condition", "branch", "toggle", "fsm")
DESIGN_UNITS = (
    "packet_if.sv",
    "lane_math.sv",
    "lane_worker.sv",
    "packet_fabric.sv",
    "hierarchy_shell.sv",
    "top.sv",
)
FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "modinfo_complex"


def test_fixture_keeps_one_design_unit_per_source_file():
    for filename in DESIGN_UNITS:
        text = (FIXTURE_SOURCE / filename).read_text(encoding="utf-8")
        units = re.findall(r"^(?:module|interface)\s+\w+", text, re.MULTILINE)
        assert len(units) == 1, (filename, units)


def test_complex_modinfo_export_has_diverse_incomplete_branch_groups(xverif_fixture, tmp_path):
    from xcov.actions import Dispatcher
    from xcov.backend import NpiCoverageBackend
    from xcov.session import SessionManager

    resources = xverif_fixture("xcov.modinfo_complex")
    vdb = resources / "complex.vdb"

    def factory(vdb_path, **kwargs):
        backend = NpiCoverageBackend(vdb=str(vdb_path))
        for name, value in kwargs.items():
            if hasattr(backend, name):
                setattr(backend, name, value)
        return backend

    sessions = SessionManager(backend_factory=factory)
    session = sessions.open(str(vdb), name="modinfo_complex", cache_dir=str(tmp_path))
    try:
        response = Dispatcher(sessions=sessions).dispatch({
            "api_version": "xcov.v1",
            "request_id": "export-modinfo-complex",
            "action": "export.code_coverage",
            "target": {"session_id": session.session_id},
            "args": {
                "scopes": [ACTIVE_SCOPE, SPARSE_SCOPE],
                "metrics": list(METRICS),
                "output": {"path": str(tmp_path / "export")},
            },
        })
    finally:
        session.close()

    assert response["ok"] is True, response
    assert response["summary"]["analysis_complete"] is True
    run_dir = Path(response["summary"]["output_dir"])
    assert re.fullmatch(r"xcov_code_coverage_\d{8}_\d{6}", run_dir.name)
    assert [item["scope"] for item in response["data"]["items"]] == [ACTIVE_SCOPE, SPARSE_SCOPE]

    scores = {}
    for item in response["data"]["items"]:
        scope = item["scope"]
        instance_dir = Path(item["directory"])
        scores[scope] = {}
        for metric in METRICS:
            payload = json.loads((instance_dir / f"{metric}.json").read_text(encoding="utf-8"))
            coverage = payload["coverage"]
            assert payload["scope"] == scope
            assert coverage["coverable"] > 0
            assert coverage["missing"] > 0
            assert 0.0 <= coverage["pct"] < 100.0
            assert payload["analysis_complete"] is True
            assert (instance_dir / f"{metric}.urg.txt").is_file()
            scores[scope][metric] = coverage["pct"]

        branch = json.loads((instance_dir / "branch.json").read_text(encoding="utf-8"))
        assert branch["schema"] == "xcov.code_coverage.branch.v2"
        assert branch["decision_group_count"] > 5
        assert all(group["uncovered"] for group in branch["decision_groups"])
        kind_sequences = [
            tuple(node["kind"] for node in group["decision_path"])
            for group in branch["decision_groups"]
        ]
        assert len(set(kind_sequences)) == len(kind_sequences), kind_sequences
        branch_xout = (instance_dir / "branch.xout").read_text(encoding="utf-8")
        assert "\n  uncovered:\n" in branch_xout
        assert "\n\n  uncovered:\n" not in branch_xout

    assert any(scores[ACTIVE_SCOPE][metric] != scores[SPARSE_SCOPE][metric] for metric in METRICS)
