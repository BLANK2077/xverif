from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runner import ArtifactWriter, CliRunner, RunResult


def _success(result: RunResult, name: str, artifact_root: Path) -> dict[str, Any]:
    if (
        result.returncode == 0
        and not result.timed_out
        and isinstance(result.response, dict)
        and result.response.get("ok") is True
    ):
        return result.response
    artifacts = ArtifactWriter(artifact_root).write(name, result)
    pytest.fail(f"{name} failed; artifacts={artifacts}\n{result.stdout_raw}\n{result.stderr_raw}")


@pytest.mark.combined
@pytest.mark.active_trace
@pytest.mark.synthetic
@pytest.mark.regression
@pytest.mark.slow
def test_trace_x_xprop_and_clockless_point_reads(
    cli_runner: CliRunner,
    artifact_root: Path,
    xverif_fixture: Any,
) -> None:
    resources = xverif_fixture("xdebug.trace_x_xprop")
    daidir = resources / "out" / "simv.daidir"
    fsdb = resources / "out" / "waves.fsdb"
    assert daidir.is_dir()
    assert fsdb.is_file() and fsdb.stat().st_size > 1024
    assert (resources / "out" / "xprop.log").is_file()

    opened = _success(
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.open",
                "target": {"daidir": str(daidir), "fsdb": str(fsdb)},
                "args": {"name": "trace_x_xprop_test"},
            },
            timeout_sec=120,
        ),
        "trace_x_session_open",
        artifact_root,
    )
    session = opened["session"]
    session_id = session["session_id"]

    def run(
        action: str,
        args: dict[str, Any],
        *,
        limits: dict[str, Any] | None = None,
        output_format: str = "json",
    ) -> RunResult:
        request: dict[str, Any] = {
            "api_version": "xdebug.v1",
            "action": action,
            "target": {"session_id": session_id},
            "args": args,
        }
        if limits is not None:
            request["limits"] = limits
        return cli_runner.run(
            request,
            output_format=output_format,
            timeout_sec=120,
        )

    try:
        raw = _success(
            run("value.at", {"signal": "trace_x_xprop_tb.observed", "time": "18ns"}),
            "clockless_value_at",
            artifact_root,
        )
        assert raw["summary"]["sampling_mode"] == "raw_time"
        raw_cell = raw["data"]["samples"][0]["values"][0]
        assert "'h" in raw_cell["value"]["value"]
        assert raw_cell["value"]["has_x"] is True
        assert "clock_context" not in raw["data"]["samples"][0]

        _success(
            run(
                "list.load",
                {
                    "config": {
                        "lists": [{
                            "name": "x_context",
                            "signals": [
                                "trace_x_xprop_tb.observed",
                                "trace_x_xprop_tb.direct_x_out",
                            ],
                        }],
                    },
                },
            ),
            "list_load_x_context",
            artifact_root,
        )
        batch = _success(
            run(
                "value.at",
                {
                    "list": "x_context",
                    "times": ["18ns"],
                },
            ),
            "clockless_value_at_list",
            artifact_root,
        )
        sample = batch["data"]["samples"][0]
        assert sample["sampling_mode"] == "raw_time"
        assert len(sample["values"]) == 2
        assert all(
            "'h" in cell["value"]["value"]
            for cell in sample["values"]
        )

        invalid = run(
            "value.at",
            {
                "signal": "trace_x_xprop_tb.observed",
                "time": "18ns",
                "edge": "posedge",
            },
        )
        assert isinstance(invalid.response, dict)
        assert invalid.response["ok"] is False
        assert invalid.response["error"]["code"] == "INVALID_REQUEST"
        assert invalid.response["error"]["error_layer"] == "schema"
        assert invalid.response["error"]["invalid_arg"] == "args"

        clocked = _success(
            run(
                "value.at",
                {
                    "signal": "trace_x_xprop_tb.observed",
                    "clock": "trace_x_xprop_tb.clk",
                    "time": "18ns",
                },
            ),
            "clocked_value_at_compat",
            artifact_root,
        )
        assert clocked["summary"]["sampling_mode"] == "clock_sampled"
        assert (
            clocked["data"]["samples"][0]["clock_context"]["clock"]
            == "trace_x_xprop_tb.clk"
        )

        non_x = _success(
            run("trace.x_origin", {"signal": "trace_x_xprop_tb.direct_x_out", "time": "18ns"}),
            "trace_x_non_x",
            artifact_root,
        )
        assert non_x["summary"]["termination"] == "not_x_at_query_time"
        assert non_x["summary"]["evidence_status"] == "proven"
        assert non_x["summary"]["query_time"] == "18ns"
        assert non_x["data"]["query"]["query_time"] == "18ns"

        control_x = _success(
            run("trace.x_origin", {"signal": "trace_x_xprop_tb.observed", "time": "18ns"}),
            "trace_x_control_module_interface",
            artifact_root,
        )
        assert control_x["data"]["query"]["value"]["value"] == "8'hxx"
        assert control_x["data"]["query"]["value"]["width"] == 8
        assert control_x["data"]["query"]["x_mask"] == "8'b10011001"
        control_hops = [hop for chain in control_x["data"]["chains"] for hop in chain["hops"]]
        assert {"port", "rhs", "control"} <= {hop["relation"] for hop in control_hops}
        assert {"15ns", "10ns"} <= {hop["x_onset_time"] for hop in control_hops}
        assert any(chain["current"]["signal"].endswith("sel") for chain in control_x["data"]["chains"])
        assert control_x["summary"]["evidence_status"] in {"best_effort", "proven"}

        time_limited = _success(
            cli_runner.run(
                {
                    "api_version": "xdebug.v1",
                    "action": "trace.x_origin",
                    "target": {"session_id": session_id},
                    "args": {"signal": "trace_x_xprop_tb.observed", "time": "18ns"},
                    "limits": {"max_time_steps": 1},
                },
                timeout_sec=120,
            ),
            "trace_x_time_limit",
            artifact_root,
        )
        assert time_limited["summary"]["termination"] == "limit"
        assert "trace truncated by limits.max_time_steps" in time_limited["data"]["limitations"]

        multi_rhs = _success(
            run("trace.x_origin", {"signal": "trace_x_xprop_tb.multi_rhs_out", "time": "12ns"}),
            "trace_x_multiple_rhs_x",
            artifact_root,
        )
        assert multi_rhs["summary"]["chain_count"] == 2
        assert [chain["current"]["signal"] for chain in multi_rhs["data"]["chains"]] == [
            "trace_x_xprop_tb.multi_rhs_a",
            "trace_x_xprop_tb.multi_rhs_b",
        ]
        assert all(chain["status"] == "origin_found" for chain in multi_rhs["data"]["chains"])

        alias_effective = _success(
            run(
                "trace.x_origin",
                {"signal": "trace_x_xprop_tb.alias_effective_out", "time": "12ns"},
                limits={"max_chains": 2},
            ),
            "trace_x_effective_alias_chains",
            artifact_root,
        )
        assert alias_effective["summary"]["chain_count"] == 2
        assert alias_effective["summary"]["completed_chain_count"] == 2
        assert alias_effective["summary"]["limited_chain_count"] == 0
        alias_chains = alias_effective["data"]["chains"]
        assert [chain["chain_id"] for chain in alias_chains] == ["c0", "c1"]
        assert {
            chain["current"]["signal"].rsplit(".", 1)[-1]
            for chain in alias_chains
        } == {"alias_source_a", "alias_source_b"}
        assert any(
            hop["relation"] == "port"
            for chain in alias_chains
            for hop in chain["hops"]
        )

        alias_limited = _success(
            run(
                "trace.x_origin",
                {"signal": "trace_x_xprop_tb.alias_effective_out", "time": "12ns"},
                limits={"max_chains": 1},
            ),
            "trace_x_effective_alias_chain_limit",
            artifact_root,
        )
        assert alias_limited["summary"]["chain_count"] == 1
        assert alias_limited["summary"]["termination"] == "limit"
        assert alias_limited["summary"]["completed_chain_count"] == 0
        assert alias_limited["summary"]["limited_chain_count"] == 1
        alias_limited_chain = alias_limited["data"]["chains"][0]
        assert len(alias_limited_chain["pending_x_dependencies"]) == 1
        assert alias_limited_chain["pending_x_dependencies"][0]["relation"] != "port"
        alias_branch_event = alias_limited_chain["branch_events"][0]
        assert alias_branch_event["reason"] == "max_chains"
        assert alias_branch_event["x_dependency_count"] == 2
        assert alias_branch_event["returned_x_dependency_count"] == 1
        assert alias_branch_event["omitted_x_dependency_count"] == 1

        control_and_rhs = _success(
            run("trace.x_origin", {"signal": "trace_x_xprop_tb.ctrl_rhs_out", "time": "12ns"}),
            "trace_x_control_and_rhs_x",
            artifact_root,
        )
        assert control_and_rhs["summary"]["chain_count"] == 2
        relation_paths = [{hop["relation"] for hop in chain["hops"]} for chain in control_and_rhs["data"]["chains"]]
        assert any("control" in relations for relations in relation_paths)
        assert any("rhs" in relations for relations in relation_paths)

        branch_limited = _success(
            run(
                "trace.x_origin",
                {"signal": "trace_x_xprop_tb.multi_rhs_out", "time": "12ns"},
                limits={"max_depth": 1, "max_chains": 1},
            ),
            "trace_x_branch_and_depth_limit",
            artifact_root,
        )
        assert branch_limited["summary"]["chain_count"] == 1
        assert branch_limited["summary"]["termination"] == "limit"
        limited_chain = branch_limited["data"]["chains"][0]
        assert limited_chain["termination_detail"] == "max_depth"
        assert limited_chain["pending_x_dependencies"]
        frontier = branch_limited["data"]["depth_frontiers"][0]
        assert frontier["signal"] == limited_chain["current"]["signal"]
        assert frontier["continue_time"] == limited_chain["current"]["x_onset_time"]
        assert "'h" in frontier["value"]["value"]
        assert branch_limited["data"]["suggested_next_actions"][0]["args"]["signal"] == frontier["signal"]
        assert branch_limited["data"]["suggested_next_actions"][0]["args"]["time"] == frontier["continue_time"]

        active_chain_limited = _success(
            run(
                "trace.active_driver_chain",
                {"signal": "trace_x_xprop_tb.observed", "time": "18ns"},
                limits={"max_depth": 1},
            ),
            "active_chain_depth_frontier",
            artifact_root,
        )
        assert active_chain_limited["summary"]["termination_detail"] == "max_depth"
        active_frontier = active_chain_limited["data"]["depth_frontiers"][0]
        assert active_frontier["signal"] == "trace_x_xprop_tb.u_sink.bus.data"
        assert active_frontier["time"] == "15ns"
        assert "'h" in active_frontier["value"]
        assert active_chain_limited["data"]["suggested_next_actions"][0]["args"] == {
            "signal": active_frontier["signal"],
            "time": active_frontier["time"],
        }

        active_chain_default = _success(
            run(
                "trace.active_driver_chain",
                {"signal": "trace_x_xprop_tb.depth_10", "time": "22ns"},
            ),
            "active_chain_default_depth",
            artifact_root,
        )
        assert active_chain_default["summary"]["termination_detail"] == "max_depth"
        assert active_chain_default["summary"]["returned_count"] == 9
        assert active_chain_default["data"]["depth_frontiers"][0][
            "stopped_after_depth"
        ] == 8

        active_chain_deeper = _success(
            run(
                "trace.active_driver_chain",
                {"signal": "trace_x_xprop_tb.depth_10", "time": "22ns"},
                limits={"max_depth": 20},
            ),
            "active_chain_explicit_depth",
            artifact_root,
        )
        assert active_chain_deeper["summary"]["termination_detail"] != "max_depth"
        assert (
            active_chain_deeper["summary"]["returned_count"]
            > active_chain_default["summary"]["returned_count"]
        )

        driver_x = _success(
            run("trace.x_origin", {"signal": "trace_x_xprop_tb.direct_x_out", "time": "22ns"}),
            "trace_x_driver_x",
            artifact_root,
        )
        assert driver_x["data"]["query"]["value"]["has_x"] is True
        assert driver_x["summary"]["query_time"] == "22ns"
        assert driver_x["data"]["query"]["query_time"] == "22ns"
        assert driver_x["data"]["chains"][0]["hops"][0]["x_onset_time"] == "20ns"
        assert "time" not in driver_x["data"]["chains"][0]["hops"][0]
        assert driver_x["summary"]["termination"] != "not_x_at_query_time"

        indexed_x = _success(
            run("trace.x_origin", {"signal": "trace_x_xprop_tb.indexed_out", "time": "35ns"}),
            "trace_x_index_out_of_range",
            artifact_root,
        )
        assert indexed_x["data"]["query"]["value"]["has_x"] is True
        assert indexed_x["summary"]["termination"] in {
            "origin_found",
            "x_not_observable_upstream",
            "control_only",
            "limit",
        }

        xout = run(
            "trace.x_origin",
            {"signal": "trace_x_xprop_tb.observed", "time": "18ns"},
            output_format="xout",
        )
        assert xout.returncode == 0 and isinstance(xout.response, str)
        assert xout.response.startswith("@xdebug.trace.x_origin.v1\n")
        assert "pointer\tkind\tvalue" not in xout.response
        for evidence in (
            "summary:", "query_time", "18ns", "query:", "8'hxx",
            "x_mask", "source:", "active_signals:", "chains:",
            "x_onset_time", "active_time", "signal_path",
        ):
            assert evidence in xout.response
        assert "source__" not in xout.response
        assert "trace_hops:" not in xout.response
        assert "source_context" not in xout.response
    finally:
        cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": {"session_id": session_id},
                "args": {},
            },
            timeout_sec=120,
        )
