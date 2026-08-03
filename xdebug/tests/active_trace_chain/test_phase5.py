import pytest

from catalog_cases import cases, run_case
from runner import CliRunner


@pytest.mark.parametrize(
    "case", cases("phase5"), ids=lambda item: f"{item['signal']}@{item['time']}"
)
def test_phase5(case, xverif_fixture, tmp_path) -> None:
    runner = xverif_fixture("xdebug.active_trace_runner") / "build/chain_test"
    run_case(runner, xverif_fixture("xdebug.active_trace_phase5"), case, tmp_path)


def test_phase5_public_chain_reports_exact_ambiguous_rhs(
    cli_runner: CliRunner,
    xverif_fixture,
) -> None:
    resources = xverif_fixture("xdebug.active_trace_phase5") / "cases/phase5/out"
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {
                "daidir": str(resources / "simv.daidir"),
                "fsdb": str(resources / "waves.fsdb"),
            },
            "args": {"name": "active_trace_phase5_public"},
        },
        timeout_sec=120,
    )
    assert opened.returncode == 0, opened.stdout_raw + opened.stderr_raw
    assert isinstance(opened.response, dict) and opened.response.get("ok") is True
    session = opened.response["session"]
    session_id = session["session_id"]
    try:
        queried = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "trace.active_driver_chain",
                "target": {"session_id": session_id},
                "args": {"signal": "top.u_dut.dout[2]", "time": "10ns"},
            },
            timeout_sec=120,
        )
        assert queried.returncode == 0, queried.stdout_raw + queried.stderr_raw
        response = queried.response
        assert isinstance(response, dict) and response.get("ok") is True
        assert response["summary"]["termination"] == "ambiguous"
        assert response["summary"]["termination_detail"] == "multiple_rhs_sources"
        evidence = response["data"]["ambiguity_evidence"]
        assert evidence["active_time"] == "10ns"
        assert evidence["statement_count"] == 1
        statement = evidence["statements"][0]
        assert statement["line"] == 37
        assert {sample["signal"] for sample in statement["rhs_samples"]} == {
            "top.u_dut.en1",
            "top.u_dut.src_a",
            "top.u_dut.ctrl_sel",
            "top.u_dut.ctrl_mode",
            "top.u_dut.src_b",
            "top.u_dut.src_c",
        }
        changed_by_signal = {
            sample["signal"]: sample["changed"]
            for sample in statement["rhs_samples"]
        }
        assert changed_by_signal == {
            "top.u_dut.en1": False,
            "top.u_dut.src_a": False,
            "top.u_dut.ctrl_sel": True,
            "top.u_dut.ctrl_mode": False,
            "top.u_dut.src_b": True,
            "top.u_dut.src_c": False,
        }
        for sample in statement["rhs_samples"]:
            assert set(sample) == {"signal", "before", "after", "changed"}
            assert sample["after"]["value_time"] == "10ns"
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.kill",
                "target": {"session_id": session_id},
            },
            timeout_sec=60,
        )
