from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runner import CliRunner


APB_TOP = "apb_vip_fixture_top"
APB_CLK = APB_TOP + ".clk"
APB_REGISTERS = APB_TOP + ".dut.registers"
APB_PACKED2D = APB_TOP + ".packed2d"
XIF_TOP = "xif_event_top"
XIF_CLK = XIF_TOP + ".clk"
XIF_STRUCT = XIF_TOP + ".if_rdy.pd"


def _query(
    cli_runner: CliRunner,
    action: str,
    args: dict[str, Any],
    *,
    session_id: str | None = None,
    expect_ok: bool,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "api_version": "xdebug.v1",
        "action": action,
        "args": args,
    }
    if session_id is not None:
        request["target"] = {"session_id": session_id}
    result = cli_runner.run(request, timeout_sec=120)
    response = result.response
    assert isinstance(response, dict), (
        f"{action} did not return JSON rc={result.returncode}: "
        f"{result.stdout_raw[-4000:]}\n{result.stderr_raw[-4000:]}"
    )
    assert response.get("ok") is expect_ok, (
        f"{action} expected ok={expect_ok}, rc={result.returncode}: "
        f"{json.dumps(response, indent=2)[:8000]}"
    )
    return response


def _open_session(
    cli_runner: CliRunner,
    fsdb: Path,
    daidir: Path,
    name: str,
) -> str:
    request = {
        "api_version": "xdebug.v1",
        "action": "session.open",
        "target": {"fsdb": str(fsdb), "daidir": str(daidir)},
        "args": {"name": name},
    }
    result = cli_runner.run(request, timeout_sec=120)
    response = result.response
    assert isinstance(response, dict) and response.get("ok") is True, (
        f"session.open failed rc={result.returncode}: "
        f"{json.dumps(response, indent=2)[:4000]}"
    )
    return response["session"]["session_id"]


def _close_session(cli_runner: CliRunner, session_id: str) -> None:
    request = {
        "api_version": "xdebug.v1",
        "action": "session.close",
        "target": {"session_id": session_id},
        "args": {"mode": "force"},
    }
    cli_runner.run(request, timeout_sec=60)


def _assert_signal_not_leaf(response: dict[str, Any], signal: str) -> None:
    error = response.get("error") or {}
    code = error.get("code")
    assert code == "SIGNAL_NOT_LEAF", json.dumps(response, indent=2)[:4000]
    assert not str(code).startswith("INTERNAL_")
    assert error.get("error_layer") == "handler", error
    text = " ".join(
        str(value)
        for value in (
            error.get("message"),
            error.get("expected"),
            " ".join(error.get("next_actions") or []),
        )
    ).lower()
    assert "leaf" in text or "element" in text or "member" in text, error
    assert signal in json.dumps(error), error
    if error.get("invalid_arg"):
        assert error["invalid_arg"]


def _aggregate_requests(kind: str) -> list[tuple[str, dict[str, Any]]]:
    if kind == "apb":
        clock = APB_CLK
        aggregate = APB_REGISTERS
        time_range = {"begin": "0ns", "end": "500ns"}
    elif kind == "xif":
        clock = XIF_CLK
        aggregate = XIF_STRUCT
        time_range = {"begin": "0ns", "end": "200ns"}
    else:
        raise AssertionError(kind)

    return [
        ("value.at", {"signal": aggregate, "time": "100ns"}),
        ("value.at", {"signal": aggregate, "time": "100ns", "clock": clock}),
        ("signal.changes", {"signal": aggregate, "mode": "summary", "time_range": time_range}),
        ("signal.statistics", {"signal": aggregate, "time_range": time_range}),
        ("signal.statistics", {"signal": aggregate, "clock": clock, "time_range": time_range}),
        ("signal.stability", {"signal": aggregate, "time_range": time_range}),
        ("signal.anomaly.inspect", {"signals": [aggregate], "time_range": time_range}),
        ("signal.xz_verify", {"signal": aggregate, "expected_state": "x", "time_range": time_range}),
        ("signal.sampled_pulse.inspect", {"clock": clock, "valid": aggregate, "time_range": time_range}),
        ("expr.eval_at", {"clock": clock, "time": "100ns", "signals": {"a": aggregate}, "expr": "a"}),
        ("verify.conditions", {"clock": clock, "time": "100ns", "signals": {"a": aggregate}, "conditions": [{"expr": "a"}]}),
        ("window.verify", {"clock": clock, "signals": {"a": aggregate}, "conditions": [{"expr": "a", "mode": "always"}], "time_range": time_range}),
        ("event.find", {"clock": clock, "expr": "a", "signals": {"a": aggregate}, "time_range": time_range}),
        ("list.create", {"name": "aggregate_list", "signals": [aggregate]}),
        ("list.load", {"config": {"lists": [{"name": "aggregate_list", "signals": [aggregate]}]}}),
    ]


def test_aggregate_roots_return_signal_not_leaf_on_apb_fixture(
    cli_runner: CliRunner,
    xverif_fixture: Any,
) -> None:
    resources = xverif_fixture("xdebug.apb_vip")
    fsdb = resources / "out/regression/test/apb_vip_test/waves.fsdb"
    daidir = resources / "out/regression/build/simv.daidir"
    session_id = _open_session(cli_runner, fsdb, daidir, "aggregate_rejection_apb")
    try:
        for action, args in _aggregate_requests("apb"):
            response = _query(
                cli_runner,
                action,
                args,
                session_id=session_id,
                expect_ok=False,
            )
            _assert_signal_not_leaf(response, str(args.get("signal", APB_REGISTERS)))

        handshake = _query(
            cli_runner,
            "protocol.handshake.inspect",
            {
                "clock": APB_CLK,
                "valid": APB_REGISTERS,
                "ready": APB_TOP + ".dut.pready",
                "time_range": {"begin": "0ns", "end": "500ns"},
            },
            session_id=session_id,
            expect_ok=False,
        )
        _assert_signal_not_leaf(handshake, APB_REGISTERS)

        counter = _query(
            cli_runner,
            "counter.statistics",
            {
                "clock": APB_CLK,
                "vld": APB_TOP + ".dut.pready",
                "cnt": APB_REGISTERS,
                "time_range": {"begin": "0ns", "end": "500ns"},
            },
            session_id=session_id,
            expect_ok=False,
        )
        _assert_signal_not_leaf(counter, APB_REGISTERS)
    finally:
        _close_session(cli_runner, session_id)


def test_packed_array_root_returns_signal_not_leaf(
    cli_runner: CliRunner,
    xverif_fixture: Any,
) -> None:
    resources = xverif_fixture("xdebug.apb_vip")
    fsdb = resources / "out/regression/test/apb_vip_test/waves.fsdb"
    daidir = resources / "out/regression/build/simv.daidir"
    session_id = _open_session(cli_runner, fsdb, daidir, "aggregate_rejection_packed")
    try:
        response = _query(
            cli_runner,
            "value.at",
            {"signal": APB_PACKED2D, "time": "100ns"},
            session_id=session_id,
            expect_ok=False,
        )
        _assert_signal_not_leaf(response, APB_PACKED2D)
    finally:
        _close_session(cli_runner, session_id)


def test_packed_struct_root_returns_signal_not_leaf(
    cli_runner: CliRunner,
    xverif_fixture: Any,
) -> None:
    resources = xverif_fixture("xdebug.xif_event")
    fsdb = resources / "out/waves/xif_event_multi_if_test.fsdb"
    daidir = resources / "out/simv.daidir"
    session_id = _open_session(cli_runner, fsdb, daidir, "aggregate_rejection_xif")
    try:
        for action, args in _aggregate_requests("xif"):
            response = _query(
                cli_runner,
                action,
                args,
                session_id=session_id,
                expect_ok=False,
            )
            _assert_signal_not_leaf(response, XIF_STRUCT)
    finally:
        _close_session(cli_runner, session_id)


def test_event_config_load_rejects_aggregate_alias(
    cli_runner: CliRunner,
    xverif_fixture: Any,
    tmp_path: Path,
) -> None:
    resources = xverif_fixture("xdebug.xif_event")
    fsdb = resources / "out/waves/xif_event_multi_if_test.fsdb"
    daidir = resources / "out/simv.daidir"
    config_path = tmp_path / "aggregate_event.json"
    config_path.write_text(
        json.dumps(
            {
                "clock": XIF_CLK,
                "signals": {"pd": XIF_STRUCT},
            }
        ),
        encoding="utf-8",
    )
    session_id = _open_session(cli_runner, fsdb, daidir, "aggregate_event_config")
    try:
        response = _query(
            cli_runner,
            "event.config.load",
            {"name": "aggregate_event", "config_path": str(config_path)},
            session_id=session_id,
            expect_ok=False,
        )
        _assert_signal_not_leaf(response, XIF_STRUCT)
    finally:
        _close_session(cli_runner, session_id)


def test_leaf_paths_and_dynamic_index_keep_existing_behavior(
    cli_runner: CliRunner,
    xverif_fixture: Any,
) -> None:
    apb_resources = xverif_fixture("xdebug.apb_vip")
    apb_fsdb = apb_resources / "out/regression/test/apb_vip_test/waves.fsdb"
    apb_daidir = apb_resources / "out/regression/build/simv.daidir"
    apb_session = _open_session(cli_runner, apb_fsdb, apb_daidir, "aggregate_leaf_apb")
    try:
        for signal in (
            APB_REGISTERS + "[0]",
            APB_REGISTERS + "[0][1]",
            APB_PACKED2D + "[0]",
            APB_PACKED2D + "[0][7:4]",
        ):
            _query(
                cli_runner,
                "value.at",
                {"signal": signal, "time": "100ns"},
                session_id=apb_session,
                expect_ok=True,
            )

        dynamic = _query(
            cli_runner,
            "value.at",
            {"signal": APB_REGISTERS + "[" + APB_TOP + ".dut.i]", "time": "100ns"},
            session_id=apb_session,
            expect_ok=False,
        )
        assert dynamic["error"]["code"] == "SIGNAL_NOT_FOUND"
    finally:
        _close_session(cli_runner, apb_session)

    xif_resources = xverif_fixture("xdebug.xif_event")
    xif_fsdb = xif_resources / "out/waves/xif_event_multi_if_test.fsdb"
    xif_daidir = xif_resources / "out/simv.daidir"
    xif_session = _open_session(cli_runner, xif_fsdb, xif_daidir, "aggregate_leaf_xif")
    try:
        leaf = _query(
            cli_runner,
            "value.at",
            {"signal": XIF_STRUCT + ".opcode", "time": "100ns"},
            session_id=xif_session,
            expect_ok=True,
        )
        cell = leaf["data"]["samples"][0]["values"][0]
        assert cell["status"] == "ok"
        assert cell["value"]["value"] == "8'h10"

        discovery = _query(
            cli_runner,
            "signal.resolve",
            {"signal": XIF_STRUCT},
            session_id=xif_session,
            expect_ok=True,
        )
        assert discovery["summary"]["status"] == "found", discovery
    finally:
        _close_session(cli_runner, xif_session)
