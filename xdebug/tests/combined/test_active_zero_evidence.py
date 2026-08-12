from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runner import ArtifactWriter, CliRunner, RunResult


@pytest.fixture
def cli_runner(persistent_cli_runner: CliRunner) -> CliRunner:
    return persistent_cli_runner


def _require_success(
    result: RunResult,
    *,
    case_name: str,
    artifact_root: Path,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = result.response
    if (
        result.returncode == 0
        and not result.timed_out
        and isinstance(response, dict)
        and response.get("ok") is True
    ):
        return response
    artifact_dir = ArtifactWriter(artifact_root).write(case_name, result, extra=extra)
    pytest.fail(
        "%s failed rc=%s timeout=%s; artifacts=%s\nstdout:\n%s\nstderr:\n%s"
        % (
            case_name,
            result.returncode,
            result.timed_out,
            artifact_dir,
            result.stdout_raw[-8000:],
            result.stderr_raw[-8000:],
        )
    )


@pytest.fixture
def active_zero_evidence_fixture(
    xverif_fixture: Any,
) -> tuple[Path, Path]:
    resources = xverif_fixture("xdebug.active_zero_evidence")
    daidir = resources / "out" / "simv.daidir"
    fsdb = resources / "out" / "waves.fsdb"
    assert daidir.is_dir()
    assert fsdb.is_file() and fsdb.stat().st_size > 0
    return daidir, fsdb


@pytest.fixture
def active_zero_evidence_session(
    cli_runner: CliRunner,
    active_zero_evidence_fixture: tuple[Path, Path],
    artifact_root: Path,
) -> str:
    daidir, fsdb = active_zero_evidence_fixture
    response = _require_success(
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.open",
                "target": {"daidir": str(daidir), "fsdb": str(fsdb)},
                "args": {"name": "active_zero_evidence"},
            },
            timeout_sec=120,
        ),
        case_name="active-zero-evidence-session-open",
        artifact_root=artifact_root,
    )
    session = response["session"]
    session_id = session.get("session_id")
    assert isinstance(session_id, str) and session_id
    try:
        yield session_id
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close", "args": {"mode": "force"},
                "target": {"session_id": session_id},
            },
            timeout_sec=60,
        )


def _query(
    cli_runner: CliRunner,
    session_id: str,
    action: str,
    signal: str,
    requested_time: str,
    *,
    artifact_root: Path,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "signal": signal,
        "time": requested_time,
    }
    return _require_success(
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": action,
                "target": {"session_id": session_id},
                "args": args,
            },
            timeout_sec=120,
        ),
        case_name=f"{action}-{signal.rsplit('.', 1)[-1]}-{requested_time}",
        artifact_root=artifact_root,
        extra={"args": args},
    )


def _simple_query(
    cli_runner: CliRunner,
    session_id: str,
    action: str,
    args: dict[str, Any] | None,
    *,
    artifact_root: Path,
    output_format: str = "json",
) -> dict[str, Any] | str:
    result = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": action,
            "target": {"session_id": session_id},
            "args": args or {},
        },
        output_format=output_format,
        timeout_sec=120,
    )
    if output_format == "xout":
        if result.returncode == 0 and not result.timed_out and isinstance(result.response, str):
            return result.response
        artifact_dir = ArtifactWriter(artifact_root).write(
            f"{action}-xout", result, extra={"args": args or {}}
        )
        pytest.fail(f"{action} xout failed; artifacts={artifact_dir}")
    return _require_success(
        result,
        case_name=action,
        artifact_root=artifact_root,
        extra={"args": args or {}},
    )


def _path_lines(response: dict[str, Any]) -> set[int]:
    return {
        path["line"]
        for path in response.get("data", {}).get("paths", [])
        if isinstance(path, dict) and isinstance(path.get("line"), int)
    }


def _hop_lines(response: dict[str, Any]) -> list[int]:
    return [
        hop["line"]
        for hop in response.get("data", {}).get("hops", [])
        if isinstance(hop, dict) and isinstance(hop.get("line"), int)
    ]


def _signal_paths(response: dict[str, Any]) -> list[list[str]]:
    return [
        path.get("signal_path", [])
        for path in response.get("data", {}).get("paths", [])
        if isinstance(path, dict)
    ]


@pytest.mark.combined
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_scope_roots_discovers_combined_top(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "scope.roots",
        {"source": "auto"},
        artifact_root=artifact_root,
    )

    assert isinstance(response, dict)
    assert response["summary"]["recommended_root"] == "active_zero_evidence_tb"
    assert response["summary"]["matched_count"] == 1
    roots = response["data"]["roots"]
    root = next(item for item in roots if item["path"] == "active_zero_evidence_tb")
    assert root["status"] == "matched"
    assert root["sources"] == ["design", "wave"]
    assert root["wave"]["queryable"] is True
    assert root["design"]["traceable"] is True
    assert root["design"]["discovery"] in {"npi_top", "verified_wave_root"}

    scope_response = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "scope.list",
        {"path": response["summary"]["recommended_root"], "level": 0},
        artifact_root=artifact_root,
    )
    assert isinstance(scope_response, dict)
    assert scope_response["data"]["signals"]
    modules = {item["name"]: item for item in scope_response["data"]["modules"]}
    assert modules["u_primitive"]["module_name"] == "primitive_output_dut"
    assert modules["u_input_child"]["module_name"] == "input_trace_child"
    assert {
        (item["name"], item["direction"], item["width"])
        for item in scope_response["data"]["ports"]
    } >= {("top_input_i", "input", 1)}
    assert all(
        not item["name"].startswith("active_zero_evidence_tb.")
        for section in ("modules", "ports", "signals")
        for item in scope_response["data"][section]
    )

    child_ports = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "scope.list",
        {
            "path": response["summary"]["recommended_root"],
            "level": 1,
            "kind": "port",
            "include_patterns": ["u_input_child.*"],
            "exclude_patterns": ["*data_q"],
        },
        artifact_root=artifact_root,
    )
    assert {
        (item["name"], item["direction"], item["width"])
        for item in child_ports["data"]["ports"]
    } == {
        ("u_input_child.clk", "input", 1),
        ("u_input_child.data_i", "input", 1),
        ("u_input_child.rst_n", "input", 1),
    }


@pytest.mark.combined
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_trace_driver_runs_in_combined_session(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "trace.driver",
        {"signal": "active_zero_evidence_tb.u_input_child.data_q"},
        artifact_root=artifact_root,
    )
    assert isinstance(response, dict)
    assert response["data"]["paths"]
    assert response["summary"]["returned_count"] == len(response["data"]["paths"])


@pytest.mark.combined
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_scope_roots_supports_source_filters_and_xout(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    wave = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "scope.roots",
        {"source": "wave"},
        artifact_root=artifact_root,
    )
    design = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "scope.roots",
        {"source": "design"},
        artifact_root=artifact_root,
    )
    xout = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "scope.roots",
        {"source": "auto"},
        artifact_root=artifact_root,
        output_format="xout",
    )

    assert isinstance(wave, dict)
    assert wave["summary"]["wave_count"] == 1
    assert wave["summary"]["design_count"] == 0
    assert wave["summary"]["recommended_root"] == "active_zero_evidence_tb"
    assert wave["data"]["roots"][0]["status"] == "wave_only"
    assert wave["data"]["roots"][0]["design"] is None

    assert isinstance(design, dict)
    assert design["summary"]["design_count"] == 1
    assert design["summary"]["wave_count"] == 0
    assert design["summary"]["recommended_root"] == "active_zero_evidence_tb"
    assert design["data"]["roots"][0]["status"] == "design_only"
    assert design["data"]["roots"][0]["wave"] is None
    assert design["data"]["roots"][0]["design"]["discovery"] in {
        "npi_top",
        "verified_wave_root",
    }

    assert isinstance(xout, str)
    assert xout.startswith("@xdebug.scope.roots.v1")
    assert "pointer\tkind\tvalue" not in xout
    for evidence in (
        "summary:", "recommended: active_zero_evidence_tb", "source     : auto",
        "roots      : 1", "matched    : 1", "wave       : 1",
        "design     : 1", "roots:",
        "active_zero_evidence_tb  matched  design,wave",
    ):
        assert evidence in xout
    for generic_key in (
        "recommended_root", "recommended_reason", "matched_count",
        "response_truncated", "scan_complete", "analysis_complete",
    ):
        assert generic_key not in xout
    roots_block = xout.split("roots:\n", 1)[1]
    header = roots_block.splitlines()[0].split()
    assert header == ["path", "status", "sources", "wave", "design"]


@pytest.mark.combined
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_scope_roots_repeated_queries_keep_session_stable(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    for i in range(50):
        response = _simple_query(
            cli_runner,
            active_zero_evidence_session,
            "scope.roots",
            {"source": "auto"},
            artifact_root=artifact_root,
        )
        assert isinstance(response, dict), "iteration %d returned non-json" % i
        assert response["summary"]["recommended_root"] == "active_zero_evidence_tb"
        assert response["summary"]["matched_count"] == 1

    doctor = _simple_query(
        cli_runner,
        active_zero_evidence_session,
        "session.doctor",
        {},
        artifact_root=artifact_root,
    )
    assert isinstance(doctor, dict)
    assert doctor["summary"]["healthy"] is True


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_reports_precise_active_time_for_delayed_query(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver",
        "active_zero_evidence_tb.u_reduction_10ns.sample_flag",
        "15ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["active_time"] == "10ns"
    assert response["summary"]["returned_count"] == len(response["data"]["paths"])
    assert {50, 74, 77}.issubset(_path_lines(response))
    assert "driver" not in response["data"]
    assert "trace" not in response["data"]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_uses_precise_fsdb_time_for_us_scale_reduction_output(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver",
        "active_zero_evidence_tb.u_reduction_us_pulse.sample_flag",
        "10000ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["active_time"] == "9995ns"
    assert response["summary"]["returned_count"] == len(response["data"]["paths"])
    assert {142, 167}.issubset(_path_lines(response))
    assert "driver" not in response["data"]
    assert "root_driver" not in response["data"]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_chain_uses_precise_fsdb_time_for_us_scale_reduction_output(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver_chain",
        "active_zero_evidence_tb.u_reduction_us_pulse.sample_flag",
        "10000ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["termination"] == "assignment"
    assert response["summary"]["termination_detail"] == "non_direct_rhs_expression"
    assert response["summary"]["returned_count"] == len(response["data"]["hops"])
    assert response["summary"]["returned_count"] == 2
    assert _hop_lines(response) == [167, 142]
    assert "chain" not in response["data"]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_reduction_output_zero_evidence_is_unresolved(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver",
        "active_zero_evidence_tb.u_reduction.sample_flag",
        "16ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["total_count"] == 0
    assert response["summary"]["returned_count"] == 0
    assert response["data"]["paths"] == []
    assert "driver" not in response["data"]
    assert "root_driver" not in response["data"]
    assert "trace" not in response["data"]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_chain_reduction_output_zero_evidence_is_unresolved(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver_chain",
        "active_zero_evidence_tb.u_reduction.sample_flag",
        "16ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["termination"] == "unresolved"
    assert "chain" not in response["data"]
    assert response["summary"]["returned_count"] == len(response["data"]["hops"])


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_chain_primitive_output_uses_real_evidence_not_fake_primary(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver_chain",
        "active_zero_evidence_tb.u_primitive.out_bufif",
        "16ns",
        artifact_root=artifact_root,
    )

    hops = response["data"]["hops"]
    assert not (
        response["summary"]["termination"] == "primary_input"
        and len(hops) <= 1
    )
    assert response["summary"]["returned_count"] == len(hops)
    assert response["summary"]["termination"] != "unresolved"


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_direct_module_input_follows_parent_connection(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver",
        "active_zero_evidence_tb.u_input_child.data_i",
        "16ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["returned_count"] == len(response["data"]["paths"])
    assert response["summary"]["returned_count"] >= 1
    assert any(
        "active_zero_evidence_tb.parent_src" in path
        for path in _signal_paths(response)
    )
    assert "root_driver" not in response["data"]
    assert "trace" not in response["data"]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_chain_direct_module_input_follows_parent_connection(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver_chain",
        "active_zero_evidence_tb.u_input_child.data_i",
        "16ns",
        artifact_root=artifact_root,
    )

    assert "text" not in response["data"]
    assert "chain" not in response["data"]
    hops = response["data"]["hops"]
    assert len(hops) >= 2
    assert "active_zero_evidence_tb.parent_src" in hops[0]["signal_path"]
    assert not (response["summary"]["termination"] == "primary_input" and len(hops) == 1)


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_top_input_without_parent_connection_is_primary_input(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver",
        "active_zero_evidence_tb.top_input_i",
        "16ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["returned_count"] == len(response["data"]["paths"])
    if response["data"]["paths"]:
        assert any(
            "active_zero_evidence_tb.top_input_i" in path.get("signal_path", [])
            for path in response["data"]["paths"]
        )
    assert "root_driver" not in response["data"]
    assert "trace" not in response["data"]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_chain_top_input_without_parent_connection_is_primary_input(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    response = _query(
        cli_runner,
        active_zero_evidence_session,
        "trace.active_driver_chain",
        "active_zero_evidence_tb.top_input_i",
        "16ns",
        artifact_root=artifact_root,
    )

    assert response["summary"]["termination"] == "primary_input"
    assert response["summary"]["returned_count"] == len(response["data"]["hops"])
    if response["data"]["hops"]:
        assert "active_zero_evidence_tb.top_input_i" in response["data"]["hops"][0]["signal_path"]


EXPR_ZERO_EVIDENCE_OUTPUTS = [
    "q_reduce_or",
    "q_reduce_and",
    "q_reduce_xor",
    "q_bit_or_ne0",
    "q_bit_and_ne0",
    "q_xor_reduce_mask",
    "q_logic_and",
    "q_logic_or",
    "q_reduce_and_enable",
    "q_ternary_reduce",
    "q_compare_ne0",
    "q_compare_eq_const",
    "q_compare_gt",
    "q_bit_select",
    "q_const_part_reduce",
    "q_indexed_part_reduce",
    "q_concat_reduce",
    "q_nested_mix",
]


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_expr_output_zero_evidence_is_unresolved(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    failures: list[str] = []
    for output_name in EXPR_ZERO_EVIDENCE_OUTPUTS:
        response = _query(
            cli_runner,
            active_zero_evidence_session,
            "trace.active_driver",
            f"active_zero_evidence_tb.u_expr.{output_name}",
            "16ns",
            artifact_root=artifact_root,
        )
        checks = [
            response["summary"]["total_count"] == 0,
            response["summary"]["returned_count"] == 0,
            response["data"]["paths"] == [],
            "driver" not in response["data"],
            "root_driver" not in response["data"],
            "trace" not in response["data"],
        ]
        if not all(checks):
            failures.append(
                "%s: total_count=%s returned_count=%s paths=%s data_keys=%s"
                % (
                    output_name,
                    response["summary"]["total_count"],
                    response["summary"]["returned_count"],
                    response["data"]["paths"],
                    sorted(response["data"].keys()),
                )
            )
    assert not failures, "\n".join(failures)


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_active_driver_chain_expr_output_zero_evidence_is_unresolved(
    cli_runner: CliRunner,
    active_zero_evidence_session: str,
    artifact_root: Path,
) -> None:
    failures: list[str] = []
    for output_name in EXPR_ZERO_EVIDENCE_OUTPUTS:
        response = _query(
            cli_runner,
            active_zero_evidence_session,
            "trace.active_driver_chain",
            f"active_zero_evidence_tb.u_expr.{output_name}",
            "16ns",
            artifact_root=artifact_root,
        )
        checks = [
            response["summary"]["termination"] == "unresolved",
            "chain" not in response["data"],
            response["summary"]["returned_count"] == len(response["data"]["hops"]),
        ]
        if not all(checks):
            failures.append(
                "%s: termination=%s hops=%s data_keys=%s"
                % (
                    output_name,
                    response["summary"]["termination"],
                    response["data"].get("hops", [])[:1],
                    sorted(response["data"].keys()),
                )
            )
    assert not failures, "\n".join(failures)
