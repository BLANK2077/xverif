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


def test_lane_worker_has_diverse_observable_continuous_and_procedural_ternaries():
    text = (FIXTURE_SOURCE / "lane_worker.sv").read_text(encoding="utf-8")
    assignments = re.findall(
        r"assign\s+assign_features\[(\d+)\]\s*=\s*(.*?);",
        text,
        re.DOTALL,
    )

    assert [int(index) for index, _ in assignments] == list(range(12))
    normalized_rhs = [" ".join(rhs.split()) for _, rhs in assignments]
    assert len(set(normalized_rhs)) == 12
    assert any("?" in rhs and ":" in rhs for rhs in normalized_rhs)
    assert re.search(
        r"always_ff\b.*?response_class\s*<=\s*"
        r"\(request\.data\[3:0\]\s*==\s*4'he\)\s*\?\s*2'b10\s*:\s*2'b01\s*;",
        text,
        re.DOTALL,
    )
    assert re.search(
        r"assign\s+request_rejected\s*=.*?\(\^assign_features\)\s*;",
        text,
        re.DOTALL,
    )


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
    expected_line = {
        ACTIVE_SCOPE: {"line_group_count": 7, "gap_count": 15},
        SPARSE_SCOPE: {"line_group_count": 8, "gap_count": 23},
    }
    expected_condition = {
        ACTIVE_SCOPE: {"coverage_object_gap_count": 33, "gap_count": 31},
        SPARSE_SCOPE: {"coverage_object_gap_count": 43, "gap_count": 40},
    }
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

        line = json.loads((instance_dir / "line.json").read_text(encoding="utf-8"))
        assert line["schema"] == "xcov.code_coverage.line.v2"
        assert line["line_group_count"] == expected_line[scope]["line_group_count"]
        assert line["gap_count"] == expected_line[scope]["gap_count"]
        assert line["gap_count"] == line["coverage"]["missing"]
        assert all(group["uncovered"] for group in line["line_groups"])
        assert all(group["context"]["pct"] < 100.0 for group in line["line_groups"])
        line_xout = (instance_dir / "line.xout").read_text(encoding="utf-8")
        assert "\n  uncovered:\n" in line_xout
        assert "\n\n  uncovered:\n" not in line_xout
        assert "hits" not in line_xout
        assert "required" not in line_xout

        condition = json.loads((instance_dir / "condition.json").read_text(encoding="utf-8"))
        assert condition["schema"] == "xcov.code_coverage.condition.v2"
        assert condition["coverage_object_gap_count"] == expected_condition[scope]["coverage_object_gap_count"]
        assert condition["gap_count"] == expected_condition[scope]["gap_count"]
        assert condition["coverage_object_gap_count"] == condition["coverage"]["missing"]
        assert all(group["uncovered"] for group in condition["condition_groups"])
        assert all(group["condition"]["at"] != "lane_worker.sv:1"
                   for group in condition["condition_groups"])
        xor_group = next(
            group for group in condition["condition_groups"]
            if group["condition"]["at"] == "lane_worker.sv:105"
        )
        assert [term["expression"] for term in xor_group["terms"]] == [
            "request.data[(WIDTH - 1)]",
            "request.data[(WIDTH - 2)]",
        ]
        condition_xout = (instance_dir / "condition.xout").read_text(encoding="utf-8")
        assert "\n  uncovered:\n" in condition_xout
        assert "\n\n  uncovered:\n" not in condition_xout
        assert "origins" not in condition_xout
        assert "urg_vector" not in condition_xout
        assert "decoded_vector" not in condition_xout
        assert "required" not in condition_xout

        branch = json.loads((instance_dir / "branch.json").read_text(encoding="utf-8"))
        assert branch["schema"] == "xcov.code_coverage.branch.v2"
        assert branch["decision_group_count"] > 5
        assert all(group["uncovered"] for group in branch["decision_groups"])
        kind_sequences = [
            tuple(node["kind"] for node in group["decision_path"])
            for group in branch["decision_groups"]
        ]
        assert len(set(kind_sequences)) == len(kind_sequences), kind_sequences
        ternary_nodes = [
            node
            for group in branch["decision_groups"]
            for node in group["decision_path"]
            if node["kind"] == "ternary"
        ]
        assert any(node["at"] == "lane_worker.sv:151" for node in ternary_nodes)
        assert any(node["at"] == "lane_worker.sv:47" for node in ternary_nodes)
        branch_xout = (instance_dir / "branch.xout").read_text(encoding="utf-8")
        assert "\n  uncovered:\n" in branch_xout
        assert "\n\n  uncovered:\n" not in branch_xout
        assert "outcomes" not in branch_xout

        fsm = json.loads((instance_dir / "fsm.json").read_text(encoding="utf-8"))
        assert fsm["schema"] == "xcov.code_coverage.fsm.v2"
        assert fsm["fsm_group_count"] == 2
        assert [group["fsm"] for group in fsm["fsm_groups"]] == ["state", "monitor_state"]
        assert all(group["transition_coverage"]["pct"] < 100.0 for group in fsm["fsm_groups"])
        assert all(group["gaps"] for group in fsm["fsm_groups"])
        fsm_xout = (instance_dir / "fsm.xout").read_text(encoding="utf-8")
        assert fsm_xout.startswith("@xcov.code_coverage.fsm.v2\n")
        assert fsm_xout.count("\n- fsm: ") == 2
        assert "gap_id  kind" in fsm_xout
        assert "required" not in fsm_xout

    assert any(scores[ACTIVE_SCOPE][metric] != scores[SPARSE_SCOPE][metric] for metric in METRICS)
