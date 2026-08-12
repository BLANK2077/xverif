from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from runner.raw_cli import RawCliResult

from .cases import CASES, ERROR_CASES, EXTERNAL_PROTECTION_CASES
from .report import (
    SPECIAL_XOUT_ACTIONS,
    read_report_bodies,
    verify_report,
    write_report,
)
from .test_native_xout_all import (
    MatrixRuntime,
    RESOURCE_PATHS,
    _request_schema_exposes_value_format,
)


def test_matrix_has_exact_runtime_action_inventory(repo_root: Path) -> None:
    specs = json.loads(
        (repo_root / "xdebug/specs/actions/actions.yaml").read_text(
            encoding="utf-8"
        )
    )
    runtime_actions = {item["name"] for item in specs["actions"]}
    matrix_actions = {item.action for item in CASES}
    assert len(CASES) == len(matrix_actions) == 73
    assert matrix_actions == runtime_actions


def test_binary_report_round_trip_preserves_body_bytes(tmp_path: Path) -> None:
    body = b"@xdebug.actions.v1\n\nbody:\n  utf8: \xe4\xb8\xad\xe6\x96\x87\n  fence: `````\n"
    setup_body = b"@xdebug.session.list.v1"
    setup = RawCliResult(
        action="session.list", phase="final", role="setup", request={"action": "session.list"},
        command=("xdebug", "-"), returncode=0,
        stdout=setup_body, stderr=b"", elapsed_ms=1,
        timed_out=False,
    )
    primary = RawCliResult(
        action="actions", phase="final", role="primary", request={"action": "actions"},
        command=("xdebug", "-"), returncode=0, stdout=body, stderr=b"",
        elapsed_ms=2, timed_out=False,
    )
    path = tmp_path / "report.md"
    path.touch()
    write_report(path, [setup, primary])
    verify_report(path, expected_primary_by_phase={"final": 1})
    bodies = read_report_bodies(path)
    assert [item.body for item in bodies] == [setup_body, body]
    assert [item.stdout_bytes for item in bodies] == [len(setup_body), len(body)]
    assert [item.has_trailing_newline for item in bodies] == [False, True]
    assert [item.stdout_sha256 for item in bodies] == [
        setup.stdout_sha256, primary.stdout_sha256,
    ]
    payload = path.read_bytes()
    assert body in payload
    assert str(len(body)).encode() in payload
    assert primary.stdout_sha256.encode() in payload


def test_final_report_replaces_prior_phase_instead_of_copying_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.md"
    historical = RawCliResult(
        action="actions", phase="baseline", role="primary",
        request={"action": "actions"}, command=("xdebug", "-"),
        returncode=0, stdout=b"HISTORICAL BASELINE\n", stderr=b"",
        elapsed_ms=1, timed_out=False,
    )
    helper = RawCliResult(
        action="session.list", phase="baseline", role="setup",
        request={"action": "session.list"}, command=("xdebug", "-"),
        returncode=0, stdout=b"baseline setup\n", stderr=b"",
        elapsed_ms=1, timed_out=False,
    )
    write_report(path, [helper, historical])
    final = RawCliResult(
        action="actions", phase="final", role="primary",
        request={"action": "actions"}, command=("xdebug", "-"),
        returncode=0, stdout=b"CURRENT BRANCH FINAL\n", stderr=b"",
        elapsed_ms=1, timed_out=False,
    )
    final_helper = RawCliResult(
        action="session.list", phase="final", role="setup",
        request={"action": "session.list"}, command=("xdebug", "-"),
        returncode=0, stdout=b"final setup\n", stderr=b"",
        elapsed_ms=1, timed_out=False,
    )
    write_report(path, [final_helper, final])
    verify_report(path, expected_primary_by_phase={"final": 1})
    assert b"HISTORICAL BASELINE" not in path.read_bytes()
    assert [item.phase for item in read_report_bodies(path)] == ["final", "final"]


def test_specialized_current_layout_is_a_protected_contract() -> None:
    by_action = {item.action: item for item in CASES}
    assert "preview:" in by_action["apb.export"].required_text
    assert "transactions:" in by_action["apb.query"].required_text
    assert "transactions:" in by_action["axi.query"].required_text
    assert "phase_order" in by_action["axi.query"].required_text
    assert "response_dependency_violation" in by_action["axi.query"].required_text
    assert "packet:" in by_action["stream.query"].required_text
    value = by_action["value.at"]
    assert "values:" in value.required_text
    assert set(value.forbidden_text) == {
        "summary:", "entry_details:", "sample_details:",
    }
    assert {"apb.export", "apb.query", "axi.query", "stream.query", "value.at"} <= (
        SPECIAL_XOUT_ACTIONS
    )


def test_native_matrix_role_counts_are_frozen(repo_root: Path) -> None:
    assert len(CASES) == 73
    assert len(ERROR_CASES) == 9
    value_format_actions = {
        item.action for item in CASES
        if _request_schema_exposes_value_format(repo_root, item.action)
    }
    assert len(value_format_actions) == 31
    assert len(value_format_actions) * 2 == 62
    assert 3 == len(("hex", "bin", "dec"))

    reusable_prerequisites = {
        (
            item.resource,
            item.prerequisite + (
                ":" + str(item.args.get(
                    "name",
                    "mark_for_list" if item.prerequisite == "cursor" else "basic",
                ))
                if item.prerequisite in {"list", "cursor"} else ""
            ),
        )
        for item in CASES
        if item.resource is not None and item.prerequisite not in {
            None, "open_action", "disposable_session", "rc",
        }
    }
    resource_sessions = set(RESOURCE_PATHS)
    disposable_sessions = sum(
        item.prerequisite == "disposable_session" for item in CASES
    )
    assert len(resource_sessions) + len(reusable_prerequisites) + disposable_sessions == 23
    assert len(resource_sessions) + 1 == 8  # session.open primary is also torn down


def test_external_transcript_contracts_do_not_expand_primary_matrix() -> None:
    assert set(EXTERNAL_PROTECTION_CASES) == {"008", "012", "013"}
    matrix_actions = {item.action for item in CASES}
    assert len(CASES) == len(matrix_actions) == 73
    assert {
        item["action"] for item in EXTERNAL_PROTECTION_CASES.values()
    } <= matrix_actions
    assert "requested:" in EXTERNAL_PROTECTION_CASES["008"]["required_text"]
    assert "ambiguous_rhs_samples:" in (
        EXTERNAL_PROTECTION_CASES["012"]["required_text"]
    )
    assert "active_signals:" in (
        EXTERNAL_PROTECTION_CASES["013"]["required_text"]
    )


def test_vip_configs_match_runtime_schema_and_real_fixture_shape(
    repo_root: Path, tmp_path: Path,
) -> None:
    runtime = MatrixRuntime.__new__(MatrixRuntime)
    runtime.repo_root = repo_root
    runtime.tmp_path = tmp_path
    runtime.rc_config = tmp_path / "wave.json"
    runtime.event_config = tmp_path / "event.json"
    replacements = runtime.replacements()
    apb = replacements["$APB_CONFIG"]
    assert set(apb) == {
        "paddr", "pwdata", "prdata", "pwrite", "penable", "psel",
        "pready", "pslverr", "clock", "reset", "edge",
    }
    axi_channels = {
        "awaddr", "awid", "awlen", "awsize", "awburst", "awvalid", "awready",
        "wdata", "wstrb", "wlast", "wvalid", "wready", "bid", "bresp",
        "bvalid", "bready", "araddr", "arid", "arlen", "arsize", "arburst",
        "arvalid", "arready", "rid", "rdata", "rresp", "rlast", "rvalid", "rready",
    }
    assert set(replacements["$AXI_CONFIG"]) == axi_channels | {
        "clock", "reset", "edge",
    }
    by_action = {item.action: item for item in CASES}
    for action in ("apb.config.load", "axi.config.load"):
        case = by_action[action]
        request = {
            "api_version": "xdebug.v1", "action": action,
            "target": {"session_id": "schema_only"},
            "args": runtime.expand(case.args),
        }
        schema = json.loads(
            (repo_root / "xdebug/schemas/v1/actions" /
             f"{action}.request.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft7Validator(schema).validate(request)


def test_primary_mutators_do_not_collide_with_prerequisite_state() -> None:
    by_action = {item.action: item for item in CASES}
    assert by_action["apb.config.load"].args["name"] != "apb0"
    assert by_action["axi.config.load"].args["name"] != "axi0"
    assert by_action["event.config.load"].args["name"] != "rdy"
    assert by_action["stream.config.load"].args == {
        "config": {"streams": "$STREAM_PRIMARY"}, "mode": "append",
    }
    list_prerequisites = {
        item.args["name"] for item in CASES
        if item.prerequisite == "list"
    }
    assert len(list_prerequisites) == 6
    assert by_action["list.create"].args["name"] not in list_prerequisites
    cursor_prerequisites = {
        item.args.get("name", "mark_for_list") for item in CASES
        if item.prerequisite == "cursor"
    }
    assert len(cursor_prerequisites) == 4
    assert by_action["waveform.cursor.set"].args["name"] not in cursor_prerequisites
