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

    assert response["ok"] is True, json.dumps(response, ensure_ascii=False, indent=2)
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

        line = json.loads((instance_dir / "line.json").read_text(encoding="utf-8"))
        assert line["schema"] == "xcov.code_coverage.line.v2"
        assert line["line_group_count"] > 5
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
        assert condition["condition_group_count"] > 5
        assert condition["coverage_object_gap_count"] == condition["coverage"]["missing"]
        assert all(group["uncovered"] for group in condition["condition_groups"])
        assert all(group["condition"]["at"] != "lane_worker.sv:1"
                   for group in condition["condition_groups"])
        xor_group = next(
            group for group in condition["condition_groups"]
            if group["condition"]["expression"]
            == "(request.data[(WIDTH - 1)] ^ request.data[(WIDTH - 2)])"
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
        assert any("assign assign_features[3]" in node["source"] for node in ternary_nodes)
        assert any("response_class <=" in node["source"] for node in ternary_nodes)
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
def test_export_is_urg_only_and_exclusion_lazily_resolves_npi_targets(xverif_fixture, tmp_path):
    import json
    from pathlib import Path

    from xcov.actions import Dispatcher
    from xcov.backend import UrgCoverageBackend
    from xcov.session import SessionManager

    resources = xverif_fixture("xcov.modinfo_complex")
    vdb = resources / "complex.vdb"
    sessions = SessionManager()
    session = sessions.open(str(vdb), name="gap_exclusion", cache_dir=str(tmp_path))
    backend = session.backend._delegate
    assert isinstance(backend, UrgCoverageBackend)
    assert backend.npi_initialized is False
    dispatcher = Dispatcher(sessions=sessions)
    try:
        exported = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "export-for-exclusion",
            "action": "export.code_coverage",
            "target": {"session_id": session.session_id},
            "args": {
                "scopes": [SPARSE_SCOPE],
                "metrics": list(METRICS),
                "output": {"path": str(tmp_path / "export")},
            },
        })
        assert exported["ok"] is True, json.dumps(exported, ensure_ascii=False, indent=2)
        instance_dir = Path(exported["data"]["items"][0]["directory"])
        export_entries = []
        expected_ids = []
        for metric in METRICS:
            path = instance_dir / f"{metric}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            if metric == "line":
                ids = [gap["gap_id"] for group in payload["line_groups"] for gap in group["uncovered"]]
            elif metric == "condition":
                ids = [gap["gap_id"] for group in payload["condition_groups"] for gap in group["uncovered"]]
            elif metric == "branch":
                ids = [gap["gap_id"] for group in payload["decision_groups"] for gap in group["uncovered"]]
            elif metric == "toggle":
                ids = [gap["gap_id"] for gap in payload["gaps"]]
            else:
                ids = [gap["gap_id"] for group in payload["fsm_groups"] for gap in group["gaps"]]
            assert ids
            expected_ids.extend((metric, gap_id) for gap_id in ids)
            export_entries.append({
                "path": str(path),
                "items": [{"gap_id": gap_id, "reason": f"验证 {metric} gap exclude"} for gap_id in ids],
                })

        assert backend.npi_initialized is False

        excluded = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "exclude-all-export-gaps",
            "action": "exclude.add",
            "target": {"session_id": session.session_id},
            "args": {"exports": export_entries},
        })
        assert excluded["ok"] is True, json.dumps(excluded, ensure_ascii=False, indent=2)
        assert excluded["summary"]["result"] == "success"
        assert excluded["summary"]["successful_gap_count"] == len(expected_ids)
        assert excluded["summary"]["failed_gap_count"] == 0
        assert backend.npi_initialized is True
        assert [(item["metric"], item["gap_id"]) for item in excluded["data"]["items"]] == expected_ids
        assert all(item["status"] in {"changed", "already_in_state"} for item in excluded["data"]["items"])

        fsm_path = instance_dir / "fsm.json"
        fsm_payload = json.loads(fsm_path.read_text(encoding="utf-8"))
        fsm_gaps = [gap for group in fsm_payload["fsm_groups"] for gap in group["gaps"]]
        missing_fsm = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "exclude-fsm-missing-gap-id",
            "action": "exclude.add",
            "target": {"session_id": session.session_id},
            "args": {"exports": [{
                "path": str(fsm_path),
                "items": [
                    {"gap_id": fsm_gaps[0]["gap_id"], "reason": "有效 FSM gap"},
                    {"gap_id": "F999999", "reason": "不存在的 FSM gap"},
                ],
            }]},
        })
        assert missing_fsm["ok"] is False
        assert missing_fsm["error"]["code"] == "EXCLUSION_EXPORT_PREFLIGHT_FAILED"
        assert missing_fsm["error"]["detail.requested_gap_count"] == 2
        assert missing_fsm["error"]["detail.successful_gap_count"] == 0
        assert missing_fsm["error"]["detail.transaction_committed"] is False
        assert "未生效任何条目" in missing_fsm["error"]["message"]

        fsm_gaps[0]["object"] = "__missing_fsm_semantic_object__"
        broken_fsm_path = tmp_path / "fsm-broken.json"
        broken_fsm_path.write_text(json.dumps(fsm_payload), encoding="utf-8")
        partial = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "exclude-fsm-partial",
            "action": "exclude.add",
            "target": {"session_id": session.session_id},
            "args": {"exports": [{
                "path": str(broken_fsm_path),
                "items": [
                    {"gap_id": fsm_gaps[0]["gap_id"], "reason": "FSM 不可达路径"},
                    {"gap_id": fsm_gaps[1]["gap_id"], "reason": "FSM 未计划路径"},
                ],
            }]},
            })
        assert partial["ok"] is True, json.dumps(partial, ensure_ascii=False, indent=2)
        assert partial["summary"]["result"] == "partial_success"
        assert partial["summary"]["successful_gap_count"] == 0
        assert partial["summary"]["failed_gap_count"] == 2

        branch_path = instance_dir / "branch.json"
        branch_payload = json.loads(branch_path.read_text(encoding="utf-8"))
        branch_gap = branch_payload["decision_groups"][0]["uncovered"][0]
        branch_payload["scope"] = "top.__missing_scope__"
        broken_branch_path = tmp_path / "branch-broken.json"
        broken_branch_path.write_text(json.dumps(branch_payload), encoding="utf-8")
        rejected = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "exclude-branch-atomic-failure",
            "action": "exclude.add",
            "target": {"session_id": session.session_id},
            "args": {"exports": [{
                "path": str(broken_branch_path),
                "items": [{"gap_id": branch_gap["gap_id"], "reason": "分支异常回滚验证"}],
            }]},
        })
        assert rejected["ok"] is False
        assert rejected["error"]["code"] == "EXCLUSION_EXPORT_PREFLIGHT_FAILED"
        assert "未生效任何条目" in rejected["error"]["message"]
    finally:
        session.close()


def test_assert_and_functional_exports_are_structured_and_fully_excludable(xverif_fixture, tmp_path):
    import json
    from pathlib import Path

    from xcov.actions import Dispatcher
    from xcov.backend import UrgCoverageBackend
    from xcov.session import SessionManager

    resources = xverif_fixture("xcov.modinfo_complex")
    vdb = resources / "complex.vdb"
    sessions = SessionManager()
    session = sessions.open(str(vdb), name="structured_gaps", cache_dir=str(tmp_path))
    backend = session.backend._delegate
    assert isinstance(backend, UrgCoverageBackend)
    assert backend.npi_initialized is False
    dispatcher = Dispatcher(sessions=sessions)
    exports = []
    try:
        payloads = {}
        for action, metric, raw_name, prefix in (
            ("export.assert", "assert", "asserts.txt", "A"),
            ("export.functional_coverage", "functional", "grpinfo.txt", "FC"),
        ):
            output = tmp_path / metric
            response = dispatcher.dispatch({
                "api_version": "xcov.v1", "request_id": f"export-{metric}",
                "action": action, "target": {"session_id": session.session_id},
                "args": {"output": {"path": str(output)}},
            })
            assert response["ok"] is True, json.dumps(response, ensure_ascii=False, indent=2)
            assert (output / raw_name).is_file()
            payload = json.loads((output / f"{metric}.json").read_text(encoding="utf-8"))
            xout = (output / f"{metric}.xout").read_text(encoding="utf-8")
            assert xout.startswith("gap_id\tscope\tkind\tname")
            assert payload["gap_count"] == len(payload["gaps"])
            assert payload["gap_count"] > 10
            assert [gap["gap_id"] for gap in payload["gaps"]] == [
                f"{prefix}{index:04d}" for index in range(1, payload["gap_count"] + 1)
            ]
            assert len({gap["scope"] for gap in payload["gaps"]}) > 1
            payloads[metric] = payload
            exports.append({
                "path": str(output / f"{metric}.json"),
                "items": [
                    {"gap_id": gap["gap_id"], "reason": f"验证 {metric} 结构化 gap"}
                    for gap in payload["gaps"]
                ],
            })

        assert backend.npi_initialized is False

        functional_groups = {gap["covergroup"] for gap in payloads["functional"]["gaps"]}
        assert any("lane_instance_cg" in group for group in functional_groups)
        assert any("lane_aggregate_cg" in group for group in functional_groups)
        assert any(group == "top::traffic_cg" for group in functional_groups)
        excluded = dispatcher.dispatch({
            "api_version": "xcov.v1", "request_id": "exclude-structured-gaps",
            "action": "exclude.add", "target": {"session_id": session.session_id},
            "args": {"exports": exports},
        })
        assert excluded["ok"] is True, json.dumps(excluded, ensure_ascii=False, indent=2)
        assert excluded["summary"]["failed_gap_count"] == 0
        assert backend.npi_initialized is True
        assert excluded["summary"]["successful_gap_count"] == sum(
            payload["gap_count"] for payload in payloads.values()
        )
    finally:
        session.close()
