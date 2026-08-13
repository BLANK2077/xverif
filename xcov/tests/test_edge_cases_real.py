"""真实 VCS/URG edge-case 回归；测试只消费正式 FixtureStore VDB。"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
from typing import Any, Iterator


EDGE_SCOPE = "route_matrix.u_value_dark"
BARE_SCOPE = "route_matrix.u_bare"
UNIQUE_SCOPE = "route_matrix.u_unique"
ZERO_SCOPE = "route_matrix.u_zero_coverable"
FIXTURE_SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "edge_cases" / "design.sv"
ALL_CODE_METRICS = ["line", "condition", "branch", "toggle", "fsm"]


@contextmanager
def _opened(vdb: Path, tmp_path: Path, name: str) -> Iterator[tuple[Any, Any]]:
    from xcov.actions import Dispatcher
    from xcov.session import SessionManager

    sessions = SessionManager()
    session = sessions.open(str(vdb), name=name, cache_dir=str(tmp_path))
    try:
        yield Dispatcher(sessions=sessions), session
    finally:
        session.close(confirm_discard_reasons=True)


def _export(
    dispatcher: Any,
    session_id: str,
    tmp_path: Path,
    scope: str,
    metrics: list[str],
    label: str,
) -> tuple[dict[str, Any], Path]:
    response = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": label,
        "action": "export.code_coverage",
        "target": {"session_id": session_id},
        "args": {
            "scopes": [scope],
            "metrics": metrics,
            "output": {
                "path": str(tmp_path / label),
                "allow_absolute_path": True,
            },
        },
    })
    assert response["ok"] is True, json.dumps(response, ensure_ascii=False, indent=2)
    return response, Path(response["data"]["items"][0]["directory"])


def _metric_payload(directory: Path, metric: str) -> dict[str, Any]:
    return json.loads((directory / f"{metric}.json").read_text(encoding="utf-8"))


def test_fixture_contains_all_requested_complex_rtl_shapes() -> None:
    text = FIXTURE_SOURCE.read_text(encoding="utf-8")

    assert "module route_matrix" in text
    assert re.search(r"module instance_only_shell\b", text)
    assert re.search(r"module bare_instance_shell;", text)
    assert "VCS coverage off" in text and "module excluded_code_shell" in text
    assert "for (genvar lane = 0; lane < 4; lane++)" in text
    assert "wire  [3:0] unpacked_value [0:3]" in text
    assert "wire  [3:0][3:0] packed_value" in text
    assert "assign unpacked_value[lane]" in text
    assert "assign packed_value[lane]" in text
    assert text.count("?") >= 12 and text.count(":") >= 12
    for operator in ("&&", "||", ">", "<", ">=", "<="):
        assert operator in text
    assert all(f"gap_{name}[lane]" in text for name in "abcd")


def test_arbitrary_top_name_supports_unique_module_detail(
    xverif_fixture: Any, tmp_path: Path, monkeypatch: Any,
) -> None:
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    monkeypatch.setenv("XVERIF_XCOV_EXPORT_ROOTS", str(tmp_path))
    with _opened(resources / "edge_cases.vdb", tmp_path, "edge-arbitrary-top") as (dispatcher, session):
        response, directory = _export(
            dispatcher, session.session_id, tmp_path, UNIQUE_SCOPE, ["line"], "arbitrary-top",
        )
    assert response["summary"]["analysis_complete"] is True
    assert _metric_payload(directory, "line")["scope"] == UNIQUE_SCOPE


def test_zero_coverable_nodes_and_null_multi_metric_scores_are_legal(
    xverif_fixture: Any, tmp_path: Path,
) -> None:
    resources = xverif_fixture("xcov.zero_coverable")
    with _opened(resources / "zero_coverable.vdb", tmp_path, "edge-zero") as (dispatcher, session):
        scope = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "zero-scope-score",
            "action": "scope.summary",
            "target": {"session_id": session.session_id},
            "args": {"scope": "route_matrix", "metrics": ["line", "functional"]},
        })
        functional = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": "zero-functional-score",
            "action": "functional_coverage.summary",
            "target": {"session_id": session.session_id},
            "args": {"scope": ZERO_SCOPE, "group_by": "covergroup"},
        })
    assert scope["ok"] is True, json.dumps(scope, ensure_ascii=False, indent=2)
    assert scope["data"]["items"][0]["coverage_pct"] is not None
    assert functional["ok"] is True, json.dumps(functional, ensure_ascii=False, indent=2)
    assert functional["data"]["items"]
    assert all(row["coverable"] == 0 for row in functional["data"]["items"])
    assert all(row["coverage_pct"] is None for row in functional["data"]["items"])


def test_line_zero_over_n_expands_one_gap_per_coverage_object(
    xverif_fixture: Any, tmp_path: Path, monkeypatch: Any,
) -> None:
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    monkeypatch.setenv("XVERIF_XCOV_EXPORT_ROOTS", str(tmp_path))
    with _opened(resources / "edge_cases.vdb", tmp_path, "edge-line") as (dispatcher, session):
        _, directory = _export(
            dispatcher, session.session_id, tmp_path, EDGE_SCOPE, ["line"], "line-zero-over-n",
        )
    payload = _metric_payload(directory, "line")
    gaps = [gap for group in payload["line_groups"] for gap in group["uncovered"]]
    assert payload["gap_count"] == payload["coverage"]["missing"] == len(gaps)
    repeated = {}
    for gap in gaps:
        repeated.setdefault((gap["at"], gap["statement"]), 0)
        repeated[(gap["at"], gap["statement"])] += 1
    assert any(count >= 4 and count % 4 == 0 for count in repeated.values())


def test_navigation_renders_real_null_percentage_for_selected_and_child(
    xverif_fixture: Any, tmp_path: Path,
) -> None:
    from xcov.code_export import navigation_payload, render_navigation_xout

    resources = xverif_fixture("xcov.zero_coverable")
    with _opened(resources / "zero_coverable.vdb", tmp_path, "edge-navigation") as (_, session):
        real_zero = session.backend.scope_metrics()[ZERO_SCOPE]["functional"]
    assert real_zero == {
        "covered": 0, "coverable": 0, "missing": 0, "excluded": 0, "pct": None,
    }
    selected_text = render_navigation_xout(
        navigation_payload(ZERO_SCOPE, {ZERO_SCOPE: {"fsm": real_zero}}, [])
    )
    parent_text = render_navigation_xout(navigation_payload(
        "route_matrix",
        {"route_matrix": {}, ZERO_SCOPE: {"fsm": real_zero}},
        [ZERO_SCOPE],
    ))
    expected = "fsm: covered=0 coverable=0 missing=0 pct=null"
    assert expected in selected_text
    assert ZERO_SCOPE in parent_text and expected in parent_text


def test_condition_number_term_layout_is_parsed_completely(
    xverif_fixture: Any, tmp_path: Path, monkeypatch: Any,
) -> None:
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    monkeypatch.setenv("XVERIF_XCOV_EXPORT_ROOTS", str(tmp_path))
    with _opened(resources / "edge_cases.vdb", tmp_path, "edge-condition") as (dispatcher, session):
        _, directory = _export(
            dispatcher, session.session_id, tmp_path, EDGE_SCOPE, ["condition"],
            "condition-number-term",
        )
    payload = _metric_payload(directory, "condition")
    assert payload["coverage_object_gap_count"] == payload["coverage"]["missing"]
    assert any(len(group["terms"]) >= 2 for group in payload["condition_groups"])
    assert any(
        any(operator in term["expression"] for operator in (">", "<", ">=", "<="))
        for group in payload["condition_groups"] for term in group["terms"]
    )


def test_single_metric_dash_matches_multi_metric_empty_self_result(
    xverif_fixture: Any, tmp_path: Path, monkeypatch: Any,
) -> None:
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    monkeypatch.setenv("XVERIF_XCOV_EXPORT_ROOTS", str(tmp_path))
    with _opened(resources / "edge_cases.vdb", tmp_path, "edge-single-dash") as (dispatcher, session):
        _, single = _export(
            dispatcher, session.session_id, tmp_path, EDGE_SCOPE, ["fsm"], "fsm-single",
        )
        _, combined = _export(
            dispatcher, session.session_id, tmp_path, EDGE_SCOPE, ALL_CODE_METRICS, "fsm-combined",
        )
    single_fsm = _metric_payload(single, "fsm")
    combined_fsm = _metric_payload(combined, "fsm")
    assert single_fsm["coverage"] == combined_fsm["coverage"] == {
        "covered": 0, "coverable": 0, "missing": 0, "pct": None,
    }
    assert single_fsm["fsm_groups"] == combined_fsm["fsm_groups"] == []


def test_empty_fsm_section_is_a_complete_empty_payload(
    xverif_fixture: Any, tmp_path: Path, monkeypatch: Any,
) -> None:
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    monkeypatch.setenv("XVERIF_XCOV_EXPORT_ROOTS", str(tmp_path))
    with _opened(resources / "edge_cases.vdb", tmp_path, "edge-empty-fsm") as (dispatcher, session):
        _, directory = _export(
            dispatcher, session.session_id, tmp_path, BARE_SCOPE, ["fsm"], "bare-empty-fsm",
        )
    payload = _metric_payload(directory, "fsm")
    assert payload["coverage"] == {
        "covered": 0, "coverable": 0, "missing": 0, "pct": None,
    }
    assert payload["fsm_group_count"] == payload["gap_count"] == 0
    assert payload["fsm_groups"] == []
    assert payload["analysis_complete"] is True
