from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from runner import ArtifactWriter, CliRunner, RunResult


GROUPS = (
    "modules",
    "ports",
    "signals",
    "interfaces",
    "interface_arrays",
    "gen_scopes",
    "internal_scopes",
    "modports",
    "mpports",
)


def _require_success(
    result: RunResult,
    *,
    case_name: str,
    artifact_root: Path,
) -> dict[str, Any]:
    response = result.response
    if (
        result.returncode == 0
        and not result.timed_out
        and isinstance(response, dict)
        and response.get("ok") is True
    ):
        return response
    artifact_dir = ArtifactWriter(artifact_root).write(case_name, result)
    pytest.fail(
        f"{case_name} failed rc={result.returncode} "
        f"timeout={result.timed_out}; artifacts={artifact_dir}\n"
        f"stdout:\n{result.stdout_raw[-8000:]}\n"
        f"stderr:\n{result.stderr_raw[-8000:]}"
    )


@pytest.fixture
def hierarchy_session(
    persistent_cli_runner: CliRunner,
    xverif_fixture: Any,
    artifact_root: Path,
) -> Iterable[str]:
    resources = xverif_fixture("xdebug.design_hierarchy")
    daidir = resources / "simv.daidir"
    assert daidir.is_dir()
    response = _require_success(
        persistent_cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.open",
                "target": {"daidir": str(daidir)},
                "args": {"name": "design_hierarchy_semantics"},
            },
            timeout_sec=120,
        ),
        case_name="design-hierarchy-session-open",
        artifact_root=artifact_root,
    )
    session_id = response["session"]["session_id"]
    try:
        yield session_id
    finally:
        persistent_cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": {"session_id": session_id},
                "args": {"mode": "force"},
            },
            timeout_sec=60,
        )


def _scope_list(
    runner: CliRunner,
    session_id: str,
    artifact_root: Path,
    *,
    kind: str = "all",
    max_rows: int = 100,
) -> dict[str, Any]:
    return _require_success(
        runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "scope.list",
                "target": {"session_id": session_id},
                "args": {
                    "source": "design",
                    "path": "hierarchy_types_top",
                    "level": 2,
                    "kind": kind,
                },
                "limits": {"max_rows": max_rows},
            },
            timeout_sec=120,
        ),
        case_name=f"design-hierarchy-scope-list-{kind}-{max_rows}",
        artifact_root=artifact_root,
    )


def _by_path(response: dict[str, Any], group: str) -> dict[str, dict[str, Any]]:
    return {item["path"]: item for item in response["data"][group]}


def _assert_design_item(item: dict[str, Any], kind: str) -> None:
    assert item["kind"] == kind
    assert item["sources"] == ["design"]
    assert isinstance(item["name"], str) and item["name"]
    assert isinstance(item["path"], str) and item["path"].startswith(
        "hierarchy_types_top."
    )
    assert isinstance(item["queryable"], bool)
    assert isinstance(item["traceable"], bool)


@pytest.mark.design
@pytest.mark.regression
@pytest.mark.slow
def test_scope_list_design_preserves_generate_interface_array_and_modport_relationships(
    persistent_cli_runner: CliRunner,
    hierarchy_session: str,
    artifact_root: Path,
) -> None:
    response = _scope_list(
        persistent_cli_runner,
        hierarchy_session,
        artifact_root,
    )
    summary = response["summary"]
    assert summary["source"] == "design"
    assert summary["path"] == "hierarchy_types_top"
    assert summary["level"] == 2
    assert summary["kind"] == "all"
    assert summary["visited_count"] >= summary["total_count"]
    assert summary["returned_count"] == summary["total_count"]
    assert summary["scan_complete"] is True
    assert summary["analysis_complete"] is True
    assert summary["response_truncated"] is False
    assert summary["truncation_scopes"] == []
    for group in GROUPS:
        assert isinstance(response["data"][group], list)

    interfaces = _by_path(response, "interfaces")
    assert set(interfaces) == {
        "hierarchy_types_top.links[0]",
        "hierarchy_types_top.links[1]",
    }
    for index in range(2):
        item = interfaces[f"hierarchy_types_top.links[{index}]"]
        _assert_design_item(item, "interface")
        assert item["array_path"] == "hierarchy_types_top.links"

    interface_arrays = _by_path(response, "interface_arrays")
    assert set(interface_arrays) == {"hierarchy_types_top.links"}
    _assert_design_item(
        interface_arrays["hierarchy_types_top.links"], "interface_array"
    )

    gen_scopes = _by_path(response, "gen_scopes")
    assert set(gen_scopes) == {
        "hierarchy_types_top.g_lane[0]",
        "hierarchy_types_top.g_lane[1]",
    }
    for item in gen_scopes.values():
        _assert_design_item(item, "gen_scope")

    modules = _by_path(response, "modules")
    assert {
        "hierarchy_types_top.g_lane[0].u_source",
        "hierarchy_types_top.g_lane[0].u_sink",
        "hierarchy_types_top.g_lane[1].u_source",
        "hierarchy_types_top.g_lane[1].u_sink",
    } <= set(modules)

    modports = _by_path(response, "modports")
    assert set(modports) == {
        f"hierarchy_types_top.links[{index}].{name}"
        for index in range(2)
        for name in ("producer", "consumer")
    }
    for item in modports.values():
        _assert_design_item(item, "modport")

    mpports = _by_path(response, "mpports")
    assert len(mpports) == 12
    for item in mpports.values():
        _assert_design_item(item, "mpport")
        assert item["direction"] in {"input", "output"}
    assert mpports["hierarchy_types_top.links[0].producer.data"]["direction"] == "output"
    assert mpports["hierarchy_types_top.links[0].consumer.data"]["direction"] == "input"


@pytest.mark.design
@pytest.mark.regression
@pytest.mark.slow
@pytest.mark.parametrize(
    ("kind", "group", "expected_paths"),
    (
        (
            "interface_array",
            "interface_arrays",
            {"hierarchy_types_top.links"},
        ),
        (
            "gen_scope",
            "gen_scopes",
            {
                "hierarchy_types_top.g_lane[0]",
                "hierarchy_types_top.g_lane[1]",
            },
        ),
        (
            "modport",
            "modports",
            {
                f"hierarchy_types_top.links[{index}].{name}"
                for index in range(2)
                for name in ("producer", "consumer")
            },
        ),
    ),
)
def test_scope_list_design_kind_filters_are_effective(
    persistent_cli_runner: CliRunner,
    hierarchy_session: str,
    artifact_root: Path,
    kind: str,
    group: str,
    expected_paths: set[str],
) -> None:
    response = _scope_list(
        persistent_cli_runner,
        hierarchy_session,
        artifact_root,
        kind=kind,
    )
    assert response["summary"]["kind"] == kind
    assert set(_by_path(response, group)) == expected_paths
    assert response["summary"]["returned_count"] == len(expected_paths)
    assert all(
        not response["data"][other]
        for other in GROUPS
        if other != group
    )


@pytest.mark.design
@pytest.mark.regression
@pytest.mark.slow
def test_scope_list_design_limit_only_truncates_response_not_scan_facts(
    persistent_cli_runner: CliRunner,
    hierarchy_session: str,
    artifact_root: Path,
) -> None:
    complete = _scope_list(
        persistent_cli_runner,
        hierarchy_session,
        artifact_root,
        kind="mpport",
    )
    limited = _scope_list(
        persistent_cli_runner,
        hierarchy_session,
        artifact_root,
        kind="mpport",
        max_rows=3,
    )
    assert complete["summary"]["total_count"] == 12
    assert limited["summary"]["visited_count"] == complete["summary"]["visited_count"]
    assert limited["summary"]["total_count"] == complete["summary"]["total_count"]
    assert limited["summary"]["returned_count"] == 3
    assert len(limited["data"]["mpports"]) == 3
    assert limited["summary"]["scan_complete"] is True
    assert limited["summary"]["analysis_complete"] is True
    assert limited["summary"]["response_truncated"] is True
    assert limited["summary"]["truncation_scopes"]
