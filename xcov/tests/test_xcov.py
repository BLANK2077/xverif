from __future__ import annotations

from copy import deepcopy
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from xcov.actions import ACTION_REGISTRY, Dispatcher
from xcov import cli as xcov_cli
from xcov.backend import (
    CanonicalCoverageBackend,
    CoverageBackend,
    FakeCoverageBackend,
    NpiApiBinding,
    NpiCallFailure,
    NpiContractViolation,
    NpiCoverageBackend,
    _validate_functional_identity,
)
from xcov.errors import XcovError
from xcov.logging import log_root, sanitize_for_log
from xcov.provenance import resource_sha256
from xcov.protocol import (
    parse_request,
    render_xout,
)
from xcov.query import query_args, sort_items
from xcov.schemas import (
    STDIO_QUIT_REQUEST,
    schema_actions,
    stdio_control_actions,
    schema_for_action,
    validate_response,
)
from xcov.session import SessionManager, XcovSession

ROOT = Path(__file__).resolve().parents[2]
XCOV = ROOT / "tools" / "xcov"


def _data_pointer(suffix: str = "") -> str:
    base = "/" + "data"
    return f"{base}/{suffix}" if suffix else base


def _xout_row(pointer: str, kind: str, value: str) -> str:
    return f"  {json.dumps(pointer)}\t{kind}\t{value}"


def test_default_log_root_separates_runtime_and_test(monkeypatch, tmp_path):
    home = tmp_path / "home"
    test_tmp = tmp_path / "repo" / "tmp"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XVERIF_XCOV_LOG_DIR", raising=False)
    monkeypatch.delenv("XVERIF_TEST_TMPDIR", raising=False)
    assert log_root() == home / ".xverif" / "xcov"

    monkeypatch.setenv("XVERIF_TEST_TMPDIR", str(test_tmp))
    assert log_root() == test_tmp / ".xverif" / "xcov"


def _run_proc(req: dict, args: list[str] | None = None, env: dict | None = None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run([str(XCOV), *(args or ["-"])], input=json.dumps(req),
                          text=True, capture_output=True, check=False,
                          cwd=str(ROOT), env=merged_env)


def _read_last_json_line(path: Path) -> dict:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert lines
    return json.loads(lines[-1])


def _fake_dispatcher() -> Dispatcher:
    return Dispatcher(
        SessionManager(
            backend_factory=lambda vdb: FakeCoverageBackend(vdb),
        )
    )


def _stdio_exchange(
    requests: list[dict],
    dispatcher: Dispatcher | None = None,
) -> tuple[int, list[dict]]:
    input_stream = io.StringIO(
        "\n".join(json.dumps(request) for request in requests) + "\n"
    )
    output_stream = io.StringIO()
    previous_stdin = sys.stdin
    previous_output = xcov_cli._PROTOCOL_OUT
    try:
        sys.stdin = input_stream
        xcov_cli._PROTOCOL_OUT = output_stream
        rc = xcov_cli.stdio_loop(dispatcher or _fake_dispatcher())
    finally:
        sys.stdin = previous_stdin
        xcov_cli._PROTOCOL_OUT = previous_output
    return rc, [
        json.loads(line)
        for line in output_stream.getvalue().splitlines()
    ]


def test_cli_json_flag_outputs_json_not_xout(tmp_path):
    proc = _run_proc({
        "api_version": "xcov.v1",
        "request_id": "actions",
        "action": "actions",
    }, ["--json", "-"], {"XVERIF_XCOV_LOG_DIR": str(tmp_path / "logs")})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert proc.stdout.lstrip().startswith("{")
    assert "XOUT_BEGIN" not in proc.stdout
    assert json.loads(proc.stdout)["ok"] is True


def test_cli_default_xout_is_token_efficient(tmp_path):
    proc = _run_proc({
        "api_version": "xcov.v1",
        "request_id": "actions-xout",
        "action": "actions",
    }, ["-"], {"XVERIF_XCOV_LOG_DIR": str(tmp_path / "logs")})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert proc.stdout.startswith("@xcov.v1 ok action=actions request_id=actions-xout\n")
    assert "summary:\n" in proc.stdout
    assert "items:\n" in proc.stdout
    assert "pointer\tkind\tvalue" not in proc.stdout


def test_cli_default_error_xout_is_token_efficient(
    tmp_path,
):
    proc = subprocess.run(
        [str(XCOV), "-"],
        input="{not-json",
        text=True,
        capture_output=True,
        check=False,
        cwd=str(ROOT),
        env={
            **os.environ,
            "XVERIF_XCOV_LOG_DIR": str(tmp_path / "logs"),
        },
    )
    assert proc.returncode == 1
    assert proc.stdout.startswith("@xcov.v1 error action=error request_id=req-unknown\n")
    assert "error:\n" in proc.stdout
    assert "code: INVALID_JSON" in proc.stdout


def test_request_cannot_select_native_response_format(tmp_path):
    proc = _run_proc({
        "api_version": "xcov.v1",
        "request_id": "actions",
        "action": "actions",
        "output": {"response_format": "json"},
    }, ["--json", "-"], {"XVERIF_XCOV_LOG_DIR": str(tmp_path / "logs")})
    assert proc.returncode == 1, proc.stderr + proc.stdout
    rsp = json.loads(proc.stdout)
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$"


def test_invalid_json_uses_the_strict_public_error_envelope(tmp_path):
    proc = subprocess.run(
        [str(XCOV), "--json", "-"],
        input="{not-json",
        text=True,
        capture_output=True,
        check=False,
        cwd=str(ROOT),
        env={**os.environ, "XVERIF_XCOV_LOG_DIR": str(tmp_path / "logs")},
    )
    assert proc.returncode == 1
    rsp = json.loads(proc.stdout)
    assert rsp["error"]["code"] == "INVALID_JSON"
    assert rsp["data"] == {}
    assert set(rsp["summary"]) == {
        "total_count",
        "returned_count",
        "response_truncated",
        "scan_complete",
        "analysis_complete",
        "truncation_scopes",
    }


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_request_parser_rejects_nonfinite_json_numbers(constant):
    text = (
        '{"api_version":"xcov.v1","action":"export.code_coverage",'
        '"target":{"session_id":"cov0"},"args":{"threshold_pct":'
        + constant
        + ',"output":{"path":"holes.md"}}}'
    )

    with pytest.raises(XcovError) as raised:
        parse_request(text)
    assert raised.value.code == "INVALID_JSON"


def test_request_parser_rejects_duplicate_object_keys():
    with pytest.raises(XcovError) as raised:
        parse_request(
            '{"api_version":"xcov.v1","action":"actions","action":"schema"}'
        )
    assert raised.value.code == "INVALID_JSON"


@pytest.mark.parametrize("action", ["bad\naction", "bad\raction", "bad action"])
def test_header_unsafe_action_returns_canonical_error_xout_without_traceback(
    tmp_path,
    action,
):
    proc = _run_proc(
        {
            "api_version": "xcov.v1",
            "request_id": "unsafe-action",
            "action": action,
        },
        ["-"],
        {"XVERIF_XCOV_LOG_DIR": str(tmp_path / "logs")},
    )

    assert proc.returncode == 1
    assert proc.stderr == ""
    assert proc.stdout.startswith("@xcov.v1 error action=error request_id=req-unknown\n")
    assert "code: SCHEMA_INVALID" in proc.stdout
    assert "detail.path: $.action" in proc.stdout


def test_nonfinite_direct_request_is_rejected_before_artifact_write(tmp_path):
    artifact = tmp_path / "must-not-exist.md"
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "nonfinite-direct",
        "action": "export.code_coverage",
        "target": {"session_id": "cov0"},
        "args": {
            "threshold_pct": float("nan"),
            "output": {
                "path": str(artifact),
                "allow_absolute_path": True,
            },
        },
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$.args.threshold_pct"
    assert not artifact.exists()


def test_session_open_uses_only_the_injected_backend_factory():
    rsp = _fake_dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "open",
        "action": "session.open",
        "target": {"vdb": "unit-test.vdb"},
        "args": {"name": "cov0"},
    })
    assert rsp["ok"] is True
    assert rsp["data"]["session"]["session_id"] == "cov0"
    assert rsp["data"]["session"]["worker"] == "fake"


def _write_run_manifest(vdb: Path, manifest: Path) -> None:
    manifest.write_text(json.dumps({
        "schema_version": "xcov.run-manifest.v1",
        "state": "published",
        "resources": {
            "vdb": {
                "path": vdb.name,
                "size_bytes": vdb.stat().st_size,
                "sha256": resource_sha256(vdb),
            },
        },
    }), encoding="utf-8")


def test_session_open_validates_published_vdb_run_manifest_before_backend_open(tmp_path):
    vdb = tmp_path / "merged.vdb"
    vdb.mkdir()
    (vdb / "coverage.bin").write_bytes(b"coverage-data")
    manifest = tmp_path / "run-manifest.json"
    _write_run_manifest(vdb, manifest)

    rsp = _fake_dispatcher().dispatch({
        "api_version": "xcov.v1", "request_id": "manifest-open",
        "action": "session.open",
        "target": {"vdb": str(vdb), "run_manifest": str(manifest)},
        "args": {"name": "cov_manifest"},
    })

    assert rsp["ok"] is True
    snapshot = rsp["data"]["resource_snapshot"]
    assert snapshot["vdb"] == str(vdb)
    assert snapshot["run_manifest"]["schema_version"] == "xcov.run-manifest.v1"
    assert snapshot["run_manifest"]["manifest_path"] == str(manifest.resolve())


def test_session_open_rejects_changed_vdb_run_manifest_without_opening_backend(tmp_path):
    vdb = tmp_path / "merged.vdb"
    vdb.mkdir()
    content = vdb / "coverage.bin"
    content.write_bytes(b"coverage-data")
    manifest = tmp_path / "run-manifest.json"
    _write_run_manifest(vdb, manifest)
    content.write_bytes(b"changed-coverage-data")
    dispatcher = _fake_dispatcher()

    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "manifest-mismatch",
        "action": "session.open",
        "target": {"vdb": str(vdb), "run_manifest": str(manifest)},
        "args": {"name": "cov_manifest"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "RESOURCE_PROVENANCE_MISMATCH"
    assert set(rsp["error"]) == {"code", "message"}
    assert dispatcher.sessions.sessions == {}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: manifest.update({"unexpected_root": True}),
        lambda manifest: manifest["resources"].update({"unexpected_kind": {}}),
        lambda manifest: manifest["resources"]["vdb"].update(
            {"unexpected_resource": True}
        ),
        lambda manifest: manifest["resources"]["vdb"].update(
            {"size_bytes": True}
        ),
        lambda manifest: manifest["resources"]["vdb"].update(
            {"path": "../merged.vdb"}
        ),
    ],
    ids=[
        "unknown-root",
        "unknown-resources",
        "unknown-resource",
        "boolean-size",
        "parent-path",
    ],
)
def test_run_manifest_contract_fails_before_backend_and_session_side_effects(
    tmp_path,
    mutation,
):
    vdb = tmp_path / "merged.vdb"
    vdb.write_bytes(b"x")
    manifest_path = tmp_path / "run-manifest.json"
    manifest = {
        "schema_version": "xcov.run-manifest.v1",
        "state": "published",
        "resources": {
            "vdb": {
                "path": vdb.name,
                "size_bytes": vdb.stat().st_size,
                "sha256": resource_sha256(vdb),
            },
        },
    }
    mutation(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    opened_vdbs = []

    def factory(path):
        opened_vdbs.append(path)
        return FakeCoverageBackend(path)

    dispatcher = Dispatcher(SessionManager(backend_factory=factory))
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "strict-manifest",
        "action": "session.open",
        "target": {
            "vdb": str(vdb),
            "run_manifest": str(manifest_path),
        },
        "args": {"name": "cov0"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "RESOURCE_PROVENANCE_MISMATCH"
    assert opened_vdbs == []
    assert dispatcher.sessions.sessions == {}


@pytest.mark.parametrize(
    "manifest_text",
    [
        (
            '{"schema_version":"xcov.run-manifest.v1",'
            '"schema_version":"xcov.run-manifest.v1",'
            '"state":"published","resources":{}}'
        ),
        (
            '{"schema_version":"xcov.run-manifest.v1",'
            '"state":"published","resources":{"vdb":{'
            '"path":"merged.vdb","size_bytes":NaN,"sha256":"'
            + ("0" * 64)
            + '"}}}'
        ),
    ],
    ids=["duplicate-key", "non-finite-number"],
)
def test_run_manifest_rejects_noncanonical_json_before_backend_open(
    tmp_path,
    manifest_text,
):
    vdb = tmp_path / "merged.vdb"
    vdb.write_bytes(b"x")
    manifest_path = tmp_path / "run-manifest.json"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    opened_vdbs = []

    dispatcher = Dispatcher(SessionManager(
        backend_factory=lambda path: (
            opened_vdbs.append(path) or FakeCoverageBackend(path)
        ),
    ))
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "noncanonical-manifest",
        "action": "session.open",
        "target": {
            "vdb": str(vdb),
            "run_manifest": str(manifest_path),
        },
        "args": {"name": "cov0"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "RESOURCE_PROVENANCE_MISMATCH"
    assert opened_vdbs == []
    assert dispatcher.sessions.sessions == {}


@pytest.mark.parametrize("retired_arg", ["fake", "reuse", "reopen"])
def test_session_open_rejects_retired_backend_and_lifecycle_args(retired_arg):
    rsp = _fake_dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": f"retired-{retired_arg}",
        "action": "session.open",
        "target": {"vdb": "unit-test.vdb"},
        "args": {"name": "cov0", retired_arg: True},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$.args"


def test_duplicate_session_name_fails_before_manifest_or_backend_work(tmp_path):
    opened_vdbs = []

    def factory(vdb):
        opened_vdbs.append(vdb)
        return FakeCoverageBackend(vdb)

    dispatcher = Dispatcher(SessionManager(backend_factory=factory))
    first = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-first",
        "action": "session.open",
        "target": {"vdb": "first.vdb"},
        "args": {"name": "cov0"},
    })
    assert first["ok"] is True

    second = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-second",
        "action": "session.open",
        "target": {
            "vdb": "different.vdb",
            "run_manifest": str(tmp_path / "must-not-be-read.json"),
        },
        "args": {"name": "cov0"},
    })

    assert second["ok"] is False
    assert second["error"]["code"] == "SESSION_EXISTS"
    assert second["error"]["detail.session_id"] == "cov0"
    assert opened_vdbs == ["first.vdb"]
    assert dispatcher.sessions.get("cov0").vdb == "first.vdb"


def test_fake_backend_is_not_a_production_vdb_selector():
    manager = SessionManager()
    assert manager._backend_factory is NpiCoverageBackend

    opened_vdbs = []

    def factory(vdb):
        opened_vdbs.append(vdb)
        return FakeCoverageBackend(vdb)

    injected = SessionManager(backend_factory=factory)
    session = injected.open("fake", name="literal-fake")
    assert opened_vdbs == ["fake"]
    assert session.vdb == "fake"

    source = (ROOT / "xcov" / "xcov" / "session.py").read_text(
        encoding="utf-8"
    )
    assert "FakeCoverageBackend" not in source
    assert 'vdb == "fake"' not in source


def test_schema_registry_covers_all_p0_actions():
    dispatcher = Dispatcher()
    for action in schema_actions():
        rsp = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": f"schema-{action}",
            "action": "schema",
            "args": {"action": action},
        })
        assert rsp["ok"] is True, action
        schema = rsp["data"]["schema"]
        assert schema["properties"]["action"]["const"] == action


def test_stdio_control_actions_come_from_transport_request_contract():
    assert stdio_control_actions() == [
        STDIO_QUIT_REQUEST["properties"]["action"]["const"]
    ]
    assert set(stdio_control_actions()).isdisjoint(schema_actions())


def test_action_registry_binds_handler_guidance_and_both_schemas():
    assert set(ACTION_REGISTRY) == set(schema_actions())
    for action, contract in ACTION_REGISTRY.items():
        assert contract.name == action
        assert contract.handler.startswith("_")
        assert hasattr(Dispatcher, contract.handler)
        assert contract.use_when
        assert contract.do_not_use_when
        assert contract.request_schema == schema_for_action(action, "request")
        assert contract.response_schema == schema_for_action(action, "response")


def test_schema_required_fields_are_action_specific():
    dispatcher = Dispatcher()
    source = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "schema-source",
        "action": "schema", "args": {"action": "source.map"},
    })["data"]["schema"]
    session_open = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "schema-open",
        "action": "schema", "args": {"action": "session.open"},
    })["data"]["schema"]
    code_export = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "schema-export",
        "action": "schema", "args": {"action": "export.code_coverage"},
    })["data"]["schema"]
    assert set(source["properties"]["args"]["required"]) == {"file", "line"}
    assert session_open["properties"]["target"]["required"] == ["vdb"]
    assert "run_manifest" in session_open["properties"]["target"]["properties"]
    assert set(session_open["properties"]["args"]["properties"]) == {
        "name",
        "exclusion_policy",
    }
    assert "threshold_pct" in code_export["properties"]["args"]["properties"]


def test_request_schemas_close_every_declared_object():
    def walk(schema: dict, path: str):
        if schema.get("type") == "object" or "properties" in schema:
            assert schema.get("additionalProperties") is False, path
        for keyword in ("properties", "patternProperties"):
            for name, child in schema.get(keyword, {}).items():
                if isinstance(child, dict):
                    walk(child, f"{path}.{keyword}.{name}")
        for keyword in ("items",):
            child = schema.get(keyword)
            if isinstance(child, dict):
                walk(child, f"{path}.{keyword}")
        for keyword in ("anyOf", "oneOf"):
            for index, child in enumerate(schema.get(keyword, [])):
                walk(child, f"{path}.{keyword}[{index}]")

    for action in schema_actions():
        walk(schema_for_action(action, "request"), action)


def test_response_schemas_have_strict_success_and_error_envelopes():
    for action in schema_actions():
        schema = schema_for_action(action, "response")
        assert len(schema["oneOf"]) == 2
        success, error = schema["oneOf"]
        for variant in (success, error):
            assert variant["additionalProperties"] is False
            assert variant["properties"]["summary"]["additionalProperties"] is False
            assert variant["properties"]["data"]["additionalProperties"] is False
        assert success["properties"]["ok"]["const"] is True
        assert error["properties"]["ok"]["const"] is False
        assert error["properties"]["error"]["additionalProperties"] is False


def test_response_schemas_are_recursively_closed_without_empty_nodes():
    def walk(schema: dict, path: str):
        assert schema, path
        assert "patternProperties" not in schema, path
        if schema.get("x-schema-node") is True:
            assert schema == {"type": "object", "x-schema-node": True}, path
            return
        if schema.get("type") == "object" or "properties" in schema:
            assert schema.get("additionalProperties") is False, path
        for name, child in schema.get("properties", {}).items():
            walk(child, f"{path}.properties.{name}")
        child = schema.get("items")
        if isinstance(child, dict):
            walk(child, f"{path}.items")
        for keyword in ("anyOf", "oneOf"):
            for index, variant in enumerate(schema.get(keyword, [])):
                walk(variant, f"{path}.{keyword}[{index}]")

    for action in schema_actions():
        walk(schema_for_action(action, "response"), action)


def test_schema_action_can_publish_strict_manifest_string_constraints():
    rsp = Dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "session-open-response-schema",
        "action": "schema",
        "args": {"action": "session.open", "kind": "response"},
    })

    assert rsp["ok"] is True
    validate_response("schema", rsp)
    encoded = json.dumps(rsp["data"]["schema"], sort_keys=True)
    assert '"maxLength": 64' in encoded
    assert '"pattern": "^[0-9a-f]{64}$"' in encoded


def test_schema_action_rejects_open_empty_and_unknown_schema_nodes():
    rsp = Dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "schema-contract",
        "action": "schema",
        "args": {"action": "actions", "kind": "response"},
    })
    assert rsp["ok"] is True

    mutations = []
    open_object = deepcopy(rsp)
    open_object["data"]["schema"]["oneOf"][0]["additionalProperties"] = True
    mutations.append(open_object)
    empty_property = deepcopy(rsp)
    empty_property["data"]["schema"]["oneOf"][0]["properties"]["ok"] = {}
    mutations.append(empty_property)
    unknown_keyword = deepcopy(rsp)
    unknown_keyword["data"]["schema"]["x-implicit-contract"] = True
    mutations.append(unknown_keyword)
    nullable_open_object = deepcopy(rsp)
    nullable_open_object["data"]["schema"]["oneOf"][0]["type"] = [
        "object",
        "null",
    ]
    nullable_open_object["data"]["schema"]["oneOf"][0][
        "additionalProperties"
    ] = True
    mutations.append(nullable_open_object)
    itemless_array = deepcopy(rsp)
    itemless_array["data"]["schema"]["oneOf"][0]["properties"]["warnings"] = {
        "type": "array"
    }
    mutations.append(itemless_array)

    for mutated in mutations:
        with pytest.raises(XcovError) as raised:
            validate_response("schema", mutated)
        assert raised.value.code == "RESPONSE_SCHEMA_INVALID"


def test_error_response_rejects_undeclared_detail_fields():
    rsp = Dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "unknown-action",
        "action": "not.an.action",
    })
    assert rsp["ok"] is False
    rsp["error"]["detail.arbitrary"] = {"input_owned": True}
    with pytest.raises(XcovError) as raised:
        validate_response("not.an.action", rsp)
    assert raised.value.code == "RESPONSE_SCHEMA_INVALID"


def test_response_completeness_is_bound_to_returned_items():
    rsp = Dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "completeness-contract",
        "action": "actions",
    })
    assert rsp["ok"] is True

    mutations = []
    impossible_count = deepcopy(rsp)
    impossible_count["summary"]["total_count"] = 0
    mutations.append(impossible_count)
    missing_item = deepcopy(rsp)
    missing_item["data"]["items"].pop()
    mutations.append(missing_item)
    false_truncation = deepcopy(rsp)
    false_truncation["summary"]["response_truncated"] = True
    false_truncation["summary"]["truncation_scopes"] = ["data.items"]
    mutations.append(false_truncation)

    for mutated in mutations:
        with pytest.raises(XcovError) as raised:
            validate_response("actions", mutated)
        assert raised.value.code == "RESPONSE_SCHEMA_INVALID"
        with pytest.raises(XcovError):
            render_xout(mutated)

    non_boolean_ok = deepcopy(rsp)
    non_boolean_ok["ok"] = 1
    with pytest.raises(XcovError) as raised:
        validate_response("actions", non_boolean_ok)
    assert raised.value.code == "RESPONSE_SCHEMA_INVALID"

    schema_rsp = Dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "schema-completeness",
        "action": "schema",
        "args": {"action": "actions", "kind": "response"},
    })
    session_rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "session-completeness",
        "action": "session.status",
        "target": {"session_id": "cov0"},
    })
    for action, singleton in (
        ("schema", schema_rsp),
        ("session.status", session_rsp),
    ):
        contradictory = deepcopy(singleton)
        contradictory["summary"]["total_count"] = 0
        contradictory["summary"]["returned_count"] = 0
        with pytest.raises(XcovError) as raised:
            validate_response(action, contradictory)
    assert raised.value.code == "RESPONSE_SCHEMA_INVALID"


def test_response_schema_rejects_nonfinite_json_numbers():
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "finite-response",
        "action": "scope.summary",
        "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut"},
    })
    mutated = deepcopy(rsp)
    mutated["data"]["items"][0]["coverage_pct"] = float("nan")

    with pytest.raises(XcovError) as raised:
        validate_response("scope.summary", mutated)
    assert raised.value.code == "RESPONSE_SCHEMA_INVALID"
    with pytest.raises(XcovError):
        render_xout(mutated)


def test_public_xout_rejects_undeclared_success_action():
    rsp = {
        "ok": True,
        "api_version": "xcov.v1",
        "request_id": "undeclared-action",
        "action": "roundtrip",
        "summary": {},
        "data": {},
        "warnings": [],
    }
    with pytest.raises(XcovError) as raised:
        render_xout(rsp)
    assert raised.value.code == "RESPONSE_SCHEMA_INVALID"


def test_unknown_fields_are_rejected_at_every_public_request_layer():
    dispatcher = _dispatch_opened()
    requests = [
        {
            "api_version": "xcov.v1", "action": "actions",
            "unexpected_top_level": True,
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.holes",
            "target": {"session_id": "cov0", "unexpected_target": True},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.holes",
            "target": {"session_id": "cov0"},
            "args": {"unexpected_arg": True},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.holes",
            "target": {"session_id": "cov0"},
            "args": {"query": {"unexpected_query": True}},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.holes",
            "target": {"session_id": "cov0"},
            "args": {"sort": {"unexpected_sort": True}},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.holes",
            "target": {"session_id": "cov0"},
            "args": {"limits": {"unexpected_limit": True}},
        },
        {
            "api_version": "xcov.v1", "action": "export.code_coverage",
            "target": {"session_id": "cov0"},
            "args": {
                "output": {"path": "holes.md", "unexpected_output": True},
            },
        },
    ]
    for req in requests:
        rsp = dispatcher.dispatch(req)
        assert rsp["ok"] is False, req
        assert rsp["error"]["code"] == "SCHEMA_INVALID", req
        assert "detail.path" in rsp["error"], req


@pytest.mark.parametrize(
    "action,args,field",
    [
        ("scope.summary", {"metrics": []}, "metrics"),
        ("code_coverage.summary", {"metrics": []}, "metrics"),
        ("code_coverage.holes", {"metrics": []}, "metrics"),
        (
            "source.map",
            {"file": "rtl/ctrl.sv", "line": 1, "metrics": []},
            "metrics",
        ),
        (
            "source.annotate",
            {
                "file": "rtl/ctrl.sv",
                "line": 1,
                "metrics": [],
                "include_source_text": False,
            },
            "metrics",
        ),
        ("functional_coverage.holes", {"levels": []}, "levels"),
        (
            "export.code_coverage",
            {"metrics": [], "output": {"path": "must-not-exist.md"}},
            "metrics",
        ),
    ],
)
def test_explicit_empty_selectors_are_rejected_instead_of_defaulted(
    action,
    args,
    field,
    tmp_path,
):
    args = deepcopy(args)
    artifact = tmp_path / "must-not-exist.md"
    if action == "export.code_coverage":
        args["output"] = {
            "path": str(artifact),
            "allow_absolute_path": True,
        }
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": f"empty-{field}",
        "action": action,
        "target": {"session_id": "cov0"},
        "args": args,
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == f"$.args.{field}"
    assert not artifact.exists()


def test_backend_empty_metric_selector_means_no_metrics_not_all_metrics():
    assert FakeCoverageBackend("unit.vdb").items(metrics=[]) == []


@pytest.mark.parametrize(
    "action",
    ["code_coverage.summary", "code_coverage.holes"],
)
def test_code_coverage_actions_reject_functional_metric(action):
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "code-functional",
        "action": action,
        "target": {"session_id": "cov0"},
        "args": {"metrics": ["functional"]},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$.args.metrics[0]"


def test_functional_summary_rejects_redundant_levels_selector():
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "summary-levels",
        "action": "functional_coverage.summary",
        "target": {"session_id": "cov0"},
        "args": {"levels": ["bin"], "group_by": "bin"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$.args"


@pytest.mark.parametrize(
    "action,args,path",
    [
        (
            "scope.children",
            {"query": {"match_field": "definitely_not_a_field"}},
            "$.args.query.match_field",
        ),
        (
            "scope.children",
            {"sort": {"by": "definitely_not_a_field"}},
            "$.args.sort.by",
        ),
        (
            "scope.children",
            {"sort": {"order": "desc"}},
            "$.args.sort",
        ),
    ],
)
def test_query_and_sort_selector_typos_are_rejected_before_execution(
    action,
    args,
    path,
):
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "invalid-field-selector",
        "action": action,
        "target": {"session_id": "cov0"},
        "args": args,
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == path


def test_query_and_sort_runtime_guards_use_the_action_contract():
    with pytest.raises(XcovError) as query_error:
        query_args(
            "scope.children",
            {"query": {"match_field": "definitely_not_a_field"}},
        )
    assert query_error.value.code == "INVALID_QUERY_FIELD"

    with pytest.raises(XcovError) as sort_error:
        sort_items(
            "scope.children",
            [{"name": "u0", "full_name": "top.u0", "coverage_pct": 0.0}],
            {"by": "definitely_not_a_field"},
        )
    assert sort_error.value.code == "INVALID_SORT_FIELD"


def test_sort_field_valid_for_action_but_absent_from_variant_is_rejected():
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "variant-sort",
        "action": "code_coverage.summary",
        "target": {"session_id": "cov0"},
        "args": {
            "group_by": "metric",
            "sort": {"by": "scope"},
        },
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "INVALID_SORT_FIELD"
    assert rsp["error"]["detail.field"] == "scope"


def test_export_output_is_required_by_schema_before_handler_execution():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "action": "export.code_coverage",
        "target": {"session_id": "cov0"},
        "args": {},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$.args"


def test_new_urg_alignment_actions_are_in_schema_and_actions():
    dispatcher = Dispatcher()
    actions = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "actions",
        "action": "actions",
    })
    names = {row["name"] for row in actions["data"]["items"]}
    for action in ("code_coverage.summary", "code_coverage.holes",
                   "functional_coverage.summary", "functional_coverage.holes",
                   "source.annotate", "assert.summary", "export.code_coverage",
                   "export.functional_coverage", "export.assert"):
        assert action in names
        schema = dispatcher.dispatch({
            "api_version": "xcov.v1", "request_id": f"schema-{action}",
            "action": "schema", "args": {"action": action},
        })
        assert schema["ok"] is True
        assert schema["data"]["schema"]["properties"]["action"]["const"] == action
    removed = {"cov.summary", "cov.holes", "cov.object.get", "cov.object.search",
               "toggle.details", "export.summary", "export.holes",
               "export.scope_tree", "export.functional",
               "functional.summary", "functional.holes", "assert.report",
               "function_coverage.summary", "function_coverage.holes",
               "export.function_coverage"}
    assert not (names & removed)
    for action in removed:
        rsp = dispatcher.dispatch({
            "api_version": "xcov.v1", "request_id": f"schema-removed-{action}",
            "action": "schema", "args": {"action": action},
        })
        assert rsp["ok"] is False
        direct = dispatcher.dispatch({
            "api_version": "xcov.v1",
            "request_id": f"direct-removed-{action}",
            "action": action,
        })
        assert direct["ok"] is False
        assert direct["error"]["code"] == "UNKNOWN_ACTION"


def test_logging_sanitize_omits_heavy_fields():
    sanitized = sanitize_for_log({"data": {"items": [{"x": i} for i in range(100)]},
                                  "small": True})
    assert sanitized["data"] == "<omitted:large-field>"
    assert sanitized["small"] is True
    assert sanitized["log_truncated"] is True


def test_stdio_loop_with_injected_backend_holes():
    lines = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "holes",
         "action": "code_coverage.holes", "target": {"session_id": "cov0"},
         "args": {"metrics": ["toggle", "branch"]}},
    ]
    rc, out = _stdio_exchange(lines)
    assert rc == 0
    assert out[0]["protocol"] == "xcov-stdio-loop"
    assert out[2]["request_id"] == "holes"
    assert "id" not in out[2]
    assert out[2]["ok"] is True
    assert out[2]["api_version"] == "xcov.v1"
    assert out[2]["action"] == "code_coverage.holes"
    assert out[2]["xout"].startswith("@xcov.code_coverage.holes.v1\n")
    assert "XOUT_BEGIN" not in out[2]["xout"]
    assert "XOUT_END" not in out[2]["xout"]
    assert '"/request_id"' not in out[2]["xout"]
    assert '"/api_version"' not in out[2]["xout"]
    assert '"/action"' not in out[2]["xout"]
    assert '"/ok"' not in out[2]["xout"]
    assert "total_count: 1" in out[2]["xout"]
    assert out[2]["json"]["summary"]["total_count"] == 1


def test_stdio_loop_unknown_action_returns_error_without_crash():
    reqs = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "bad",
         "action": "cov.holes", "target": {"session_id": "cov0"}},
    ]
    rc, out = _stdio_exchange(reqs)
    assert rc == 0
    assert out[0]["protocol"] == "xcov-stdio-loop"
    assert out[2]["request_id"] == "bad"
    assert "id" not in out[2]
    assert out[2]["ok"] is False
    assert out[2]["action"] == "cov.holes"
    assert '"/request_id"' not in out[2]["xout"]
    assert '"/action"' not in out[2]["xout"]
    assert out[2]["json"]["error"]["code"] == "UNKNOWN_ACTION"
    assert out[2]["json"]["error"]["detail.requested_action"] == "cov.holes"


def test_tests_list_defaults_to_name_filter():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "tests",
        "action": "tests.list", "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is True
    assert rsp["summary"]["total_count"] == 1
    assert rsp["data"]["items"][0]["name"] == "unit-test.vdb/test"


def test_logging_writes_action_manifest_lifecycle_and_transport(
    monkeypatch,
    tmp_path,
):
    log_dir = tmp_path / "xcov_logs"
    monkeypatch.setenv("XVERIF_XCOV_LOG_DIR", str(log_dir))
    reqs = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "holes",
         "action": "code_coverage.holes", "target": {"session_id": "cov0"},
         "args": {"metrics": ["toggle"]}},
        {"api_version": "xcov.v1", "request_id": "close",
         "action": "session.close", "target": {"session_id": "cov0"}},
    ]
    rc, _ = _stdio_exchange(reqs)
    assert rc == 0
    action_log = log_dir / "sessions" / "cov0" / "logs" / "actions.ndjson"
    manifest = log_dir / "sessions" / "cov0" / "session.json"
    lifecycle = log_dir / "backend" / "sessions" / "cov0" / "logs" / "lifecycle.ndjson"
    transport = log_dir / "backend" / "sessions" / "cov0" / "logs" / "transport.ndjson"
    assert action_log.exists()
    assert manifest.exists()
    assert lifecycle.exists()
    assert transport.exists()
    assert _read_last_json_line(action_log)["component"] == "xcov"
    assert json.loads(manifest.read_text(encoding="utf-8"))["session_id"] == "cov0"


def test_logging_can_be_disabled(monkeypatch, tmp_path):
    log_dir = tmp_path / "disabled_logs"
    monkeypatch.setenv("XVERIF_XCOV_LOG_DIR", str(log_dir))
    monkeypatch.setenv("XVERIF_XCOV_LOG", "0")
    rsp = _fake_dispatcher().dispatch({
        "api_version": "xcov.v1",
        "request_id": "open",
        "action": "session.open",
        "target": {"vdb": "unit-test.vdb"},
        "args": {"name": "cov0"},
    })
    assert rsp["ok"] is True
    assert not log_dir.exists()


def test_regex_rejected():
    reqs = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "bad",
         "action": "code_coverage.holes", "target": {"session_id": "cov0"},
         "args": {"query": {"include_patterns": ["^top.*"]}}},
    ]
    _, out = _stdio_exchange(reqs)
    assert out[2]["ok"] is False
    assert out[2]["json"]["error"]["code"] == "REGEX_NOT_SUPPORTED"


def test_export_writes_file(tmp_path):
    path = tmp_path / "holes.md"
    reqs = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "export",
         "action": "export.code_coverage", "target": {"session_id": "cov0"},
         "args": {"output": {"path": str(path), "allow_absolute_path": True}}},
    ]
    rc, _ = _stdio_exchange(reqs)
    assert rc == 0
    assert path.exists()
    text = path.read_text()
    assert "# Code Coverage Holes" in text
    assert "0->1 covered" in text


def _dispatch_opened() -> Dispatcher:
    dispatcher = _fake_dispatcher()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "open",
        "action": "session.open", "target": {"vdb": "unit-test.vdb"},
        "args": {"name": "cov0"},
    })
    assert rsp["ok"] is True
    return dispatcher


def test_top_level_limits_are_rejected_before_dispatch():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "holes",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut", "metrics": ["toggle", "branch"]},
        "limits": {"max_items": 1},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$"


def test_action_args_limits_control_returned_items():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "holes",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut", "metrics": ["toggle", "branch"],
                 "limits": {"max_items": 2}},
    })
    assert rsp["ok"] is True
    assert rsp["summary"]["returned_count"] == 2


def test_scope_summary_returns_one_requested_scope():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "scope",
        "action": "scope.summary", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut"},
    })
    assert rsp["ok"] is True
    assert rsp["summary"]["total_count"] == 1
    item = rsp["data"]["items"][0]
    assert item["full_name"] == "top.u_dut"
    assert item["coverable"] == 9
    assert "metrics" not in item
    assert not (set(item) & {"parent", "depth", "type", "def_name"})
    assert item["toggle_pct"] == 0.0
    assert item["branch_pct"] == 0.0


def test_scope_children_direct_vs_recursive():
    dispatcher = _dispatch_opened()
    direct = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "children",
        "action": "scope.children", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut"},
    })
    recursive = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "children-rec",
        "action": "scope.children", "target": {"session_id": "cov0"},
        "args": {"scope": "top", "recursive": True},
    })
    assert {i["full_name"] for i in direct["data"]["items"]} == {
        "top.u_dut.u_ctrl", "top.u_dut.u_fifo"
    }
    assert all(set(i) == {"name", "full_name", "coverage_pct"}
               for i in direct["data"]["items"])
    assert "top.u_dut.u_fifo" in {i["full_name"] for i in recursive["data"]["items"]}


def test_scope_summary_xout_is_compact_and_path_aware():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "scope-xout",
        "action": "scope.summary", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut"},
    })
    xout = render_xout(rsp)
    assert xout.startswith("@xcov.v1 ok action=scope.summary request_id=scope-xout\n")
    assert "top.u_dut" in xout
    assert "coverage:\n" in xout
    assert "line" in xout and "100.0" in xout
    assert "pointer\tkind\tvalue" not in xout


def test_scope_children_xout_preserves_the_strict_response_rows():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "children-xout",
        "action": "scope.children", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut"},
    })
    xout = render_xout(rsp)
    assert "items:\n" in xout
    assert "top.u_dut.u_ctrl" in xout
    assert "pointer\tkind\tvalue" not in xout


def test_scope_search_returns_brief_coverage_rows():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "search",
        "action": "scope.search", "target": {"session_id": "cov0"},
        "args": {"query": {"include_patterns": ["*u_fifo"], "match_field": "full_name"}},
    })
    assert rsp["ok"] is True
    assert rsp["data"]["items"][0]["full_name"] == "top.u_dut.u_fifo"
    assert set(rsp["data"]["items"][0]) == {"name", "full_name", "coverage_pct"}
    assert rsp["data"]["items"][0]["coverage_pct"] == 0.0


def test_export_code_coverage_writes_markdown_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "code-export",
        "action": "export.code_coverage", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut", "output": {"path": "code.md"}},
    })
    assert rsp["ok"] is True
    assert rsp["summary"]["output_path"] == ".xverif/xcov_exports/code.md"
    assert rsp["summary"]["artifact_format"] == "md"
    assert "x-npi" in rsp["summary"]["note"]
    text = (tmp_path / ".xverif/xcov_exports/code.md").read_text(encoding="utf-8")
    assert "# Code Coverage Holes" in text
    assert "| scope | signal | bit | 0->1 covered | 1->0 covered | file:line |" in text


def test_functional_levels_filter():
    dispatcher = _dispatch_opened()
    bins = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-bin",
        "action": "functional_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"levels": ["bin"]},
    })
    cps = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-cp",
        "action": "functional_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"levels": ["coverpoint"]},
    })
    assert bins["summary"]["total_count"] == 1
    assert cps["summary"]["total_count"] == 1


def test_functional_coverage_holes_glob_filters_full_name_and_covergroup():
    dispatcher = _dispatch_opened()
    full_name = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-filter-full",
        "action": "functional_coverage.holes", "target": {"session_id": "cov0"},
        "args": {
            "levels": ["bin"],
            "query": {"include_patterns": ["*zero_credit"], "match_field": "full_name"},
        },
    })
    covergroup = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-filter-cg",
        "action": "functional_coverage.holes", "target": {"session_id": "cov0"},
        "args": {
            "levels": ["bin"],
            "query": {"include_patterns": ["cg_*"], "match_field": "covergroup"},
        },
    })
    assert full_name["ok"] is True
    assert full_name["summary"]["total_count"] == 1
    assert full_name["data"]["items"][0]["bin"] == "zero_credit"
    assert covergroup["ok"] is True
    assert covergroup["summary"]["total_count"] == 1
    assert covergroup["data"]["items"][0]["covergroup"] == "cg_credit"


def test_functional_summary_uses_requested_level_only():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-summary",
        "action": "functional_coverage.summary", "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is True
    assert rsp["summary"]["total_count"] == 1
    assert rsp["data"]["items"][0]["coverable"] == 1
    forbidden = {
        "metric", "name", "full_name", "score_basis", "score_item_count",
        "raw_covered", "raw_coverable", "raw_missing", "raw_coverage_pct",
    }
    assert not (set(rsp["data"]["items"][0]) & forbidden)


@pytest.mark.parametrize(
    "group_by",
    ["covergroup", "coverpoint", "cross", "bin"],
)
def test_functional_summary_every_public_group_by_is_executable(group_by):
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": f"functional-{group_by}",
        "action": "functional_coverage.summary",
        "target": {"session_id": "cov0"},
        "args": {"group_by": group_by},
    })

    assert rsp["ok"] is True, rsp
    for row in rsp["data"]["items"]:
        assert group_by in row
        assert set(row) == {
            group_by,
            "covered",
            "coverable",
            "missing",
            "coverage_pct",
        }


@pytest.mark.parametrize(
    "action,args,identity",
    [
        ("code_coverage.summary", {"group_by": "scope"}, "scope"),
        (
            "functional_coverage.summary",
            {"group_by": "covergroup"},
            "covergroup",
        ),
        (
            "functional_coverage.summary",
            {"group_by": "coverpoint"},
            "coverpoint",
        ),
        ("functional_coverage.summary", {"group_by": "bin"}, "bin"),
    ],
)
def test_summary_response_schema_requires_exact_group_identity(
    action,
    args,
    identity,
):
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": f"strict-{identity}",
        "action": action,
        "target": {"session_id": "cov0"},
        "args": args,
    })
    assert rsp["ok"] is True
    assert rsp["data"]["items"]

    missing_identity = deepcopy(rsp)
    missing_identity["data"]["items"][0].pop(identity)
    with pytest.raises(XcovError) as missing:
        validate_response(action, missing_identity)
    assert missing.value.code == "RESPONSE_SCHEMA_INVALID"

    extra_identity = deepcopy(rsp)
    alternative = (
        "type"
        if action == "code_coverage.summary"
        else "cross"
    )
    extra_identity["data"]["items"][0][alternative] = "unexpected"
    with pytest.raises(XcovError) as extra:
        validate_response(action, extra_identity)
    assert extra.value.code == "RESPONSE_SCHEMA_INVALID"


def test_code_coverage_summary_omits_display_only_fields():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "code-summary",
        "action": "code_coverage.summary", "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is True
    item = rsp["data"]["items"][0]
    assert "metric" in item
    assert not (set(item) & {"name", "full_name", "functional_pct"})


def test_code_summary_uses_urg_score_rows_only():
    from xcov.actions import _coverage_score_rows, _summary_from_items

    rows = [
        {"metric": "line", "type": "npiCovBlock", "covered": 1, "coverable": 2},
        {"metric": "line", "type": "npiCovStmtBin", "covered": 1, "coverable": 1},
        {"metric": "toggle", "type": "npiCovSignal", "covered": 1, "coverable": 4},
        {"metric": "toggle", "type": "npiCovToggleBin", "covered": 2, "coverable": 4},
        {"metric": "assert", "type": "npiCovSuccessBin", "covered": None, "coverable": None},
        {"metric": "assert", "type": "npiCovAssert", "covered": 1, "coverable": 1},
    ]
    summary = {row["metric"]: row for row in _summary_from_items(_coverage_score_rows(rows), "metric")}
    assert summary["line"]["covered"] == 1
    assert summary["line"]["coverable"] == 1
    assert summary["toggle"]["covered"] == 2
    assert summary["toggle"]["coverable"] == 4
    assert summary["assert"]["covered"] == 1
    assert summary["assert"]["coverable"] == 1


def test_functional_covergroup_summary_uses_urg_score_average():
    from xcov.actions import _functional_summary_rows

    rows = [
        {"metric": "functional", "type": "npiCovCovergroup", "covergroup": "cg",
         "covered": 5, "coverable": 8, "missing": 3, "coverage_pct": 62.5},
        {"metric": "functional", "type": "npiCovCoverpoint", "covergroup": "cg",
         "coverpoint": "cp_a", "covered": 2, "coverable": 2, "coverage_pct": 100.0},
        {"metric": "functional", "type": "npiCovCoverpoint", "covergroup": "cg",
         "coverpoint": "cp_b", "covered": 1, "coverable": 2, "coverage_pct": 50.0},
        {"metric": "functional", "type": "npiCovCross", "covergroup": "cg",
         "cross": "cx", "covered": 2, "coverable": 4, "coverage_pct": 50.0},
    ]
    summary = _functional_summary_rows(rows, "covergroup")
    assert summary[0]["coverage_pct"] == 66.6667
    assert summary[0]["raw_coverage_pct"] == 62.5
    assert summary[0]["score_basis"] == "average_direct_coverpoint_cross_pct"


def test_functional_bin_evidence_is_inherited_from_parent():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-bin-evidence",
        "action": "functional_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"levels": ["bin"]},
    })
    assert rsp["ok"] is True
    item = rsp["data"]["items"][0]
    assert item["file"] == "verif/env/uart_coverage.sv"
    assert item["line"] == 22
    forbidden = {
        "metric", "name", "full_name", "score_basis", "score_item_count",
        "raw_covered", "raw_coverable", "raw_missing", "evidence", "evidence_source",
    }
    assert not (set(item) & forbidden)


def test_code_coverage_holes_reports_hierarchy_coverage_only():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "code-details",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut", "metrics": ["toggle", "branch", "condition"]},
    })
    assert rsp["ok"] is True
    rows = rsp["data"]["items"]
    assert {row["full_name"] for row in rows} == {
        "top.u_dut", "top.u_dut.u_ctrl", "top.u_dut.u_fifo"
    }
    item = next(row for row in rows if row["full_name"] == "top.u_dut.u_ctrl")
    assert item["branch_pct"] == 0.0
    assert item["condition_pct"] == 0.0
    assert "branch_bin" not in item
    assert "toggle_signal" not in item
    forbidden = {"parent", "depth", "type", "def_name", "covered", "coverable", "missing",
                 "file", "line"}
    assert not (set(item) & forbidden)
    assert "note" in rsp["summary"]


def test_code_coverage_holes_glob_filters_hierarchy_rows():
    dispatcher = _dispatch_opened()
    include = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "code-filter-include",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {
            "scope": "top.u_dut",
            "metrics": ["toggle", "branch", "condition"],
            "query": {"include_patterns": ["*u_ctrl"], "match_field": "full_name"},
        },
    })
    exclude = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "code-filter-exclude",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {
            "scope": "top.u_dut",
            "metrics": ["toggle", "branch", "condition"],
            "query": {"exclude_patterns": ["*u_fifo"], "match_field": "full_name"},
        },
    })
    assert include["ok"] is True
    assert [row["full_name"] for row in include["data"]["items"]] == ["top.u_dut.u_ctrl"]
    assert exclude["ok"] is True
    assert "top.u_dut.u_fifo" not in {row["full_name"] for row in exclude["data"]["items"]}


def test_source_annotate_returns_source_window_and_annotations(tmp_path):
    src = tmp_path / "ctrl.sv"
    src.write_text("\n".join([
        "module ctrl;",
        "  logic enable;",
        "  assert property (p_ready);",
        "endmodule",
    ]) + "\n", encoding="utf-8")
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "annotate",
        "action": "source.annotate", "target": {"session_id": "cov0"},
        "args": {"file": "rtl/ctrl.sv", "line": 120, "window": 0,
                 "include_source_text": False},
    })
    assert rsp["ok"] is True
    assert rsp["summary"]["total_count"] == 1
    row = rsp["data"]["items"][0]
    assert row["line"] == 120
    assert row["annotation_count"] == 1
    assert row["annotations"][0]["metric"] == "assert"
    contradictory = deepcopy(rsp)
    contradictory["data"]["items"][0]["annotation_count"] = 0
    with pytest.raises(XcovError) as raised:
        validate_response("source.annotate", contradictory)
    assert raised.value.code == "RESPONSE_SCHEMA_INVALID"


def test_functional_coverage_export_groups_bins_by_covergroup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-export",
        "action": "export.functional_coverage", "target": {"session_id": "cov0"},
        "args": {"covergroup": "cg_credit", "output": {"path": "func.md"}},
    })
    assert rsp["ok"] is True
    text = (tmp_path / ".xverif/xcov_exports/func.md").read_text(encoding="utf-8")
    assert "# Functional Coverage Holes" in text
    assert "## cg_credit (verif/env/uart_coverage.sv:21)" in text
    assert "### cp_level" in text
    assert "zero_credit" in text
    assert "verif/env/uart_coverage.sv:22" not in text


def test_assert_summary_summarizes_bins_without_report_fields():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "assert-summary",
        "action": "assert.summary", "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is True
    item = next(row for row in rsp["data"]["items"]
                if row["full_name"] == "top.u_dut.u_ctrl.p_ready")
    assert item["attempts"] == 10
    assert item["real_successes"] == 8
    forbidden = {"kind", "category", "severity", "failures", "incomplete",
                 "first_match", "file", "line", "evidence"}
    assert not (set(item) & forbidden)
    assert "sections" not in rsp["data"]


def test_xout_functional_coverage_holes_uses_projected_fields():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "func-bin-xout",
        "action": "functional_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"levels": ["bin"]},
    })
    xout = render_xout(rsp)
    assert "cg_credit" in xout
    assert "items:\n" in xout
    assert "pointer\tkind\tvalue" not in xout


def test_xout_items_keep_every_metric_field():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "metrics-xout",
        "action": "metrics.list", "target": {"session_id": "cov0"},
    })
    xout = render_xout(rsp)
    assert "metric" in xout
    assert "coverage_pct" in xout
    assert "line" in xout and "100.0" in xout


def test_xout_contains_only_the_code_coverage_hierarchy_contract():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "code-detail-xout",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut", "metrics": ["condition"], "limits": {"max_items": 1}},
    })
    xout = render_xout(rsp)
    assert "condition_pct" in xout
    assert "0.0" in xout
    assert "condition_bin" not in xout


def test_xout_assert_summary_omits_report_fields():
    dispatcher = _dispatch_opened()
    assert_rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "assert-xout",
        "action": "assert.summary", "target": {"session_id": "cov0"},
    })
    assert_xout = render_xout(assert_rsp)
    assert "items:\n" in assert_xout
    assert "name" in assert_xout
    assert "full_name" in assert_xout
    assert "attempts" in assert_xout
    assert "real_successes" in assert_xout
    assert "failures" not in assert_xout
    assert "incomplete" not in assert_xout


def test_branch_mask_hint_decoding():
    from xcov.backend import _branch_mask_hint
    # one_hot: single '1' bit, no '-'
    assert _branch_mask_hint("000000100") == {"encoding": "one_hot",
                                               "branch_arm_index": 2}
    assert _branch_mask_hint("1") == {"encoding": "one_hot",
                                       "branch_arm_index": 0}
    assert _branch_mask_hint("1000000") == {"encoding": "one_hot",
                                             "branch_arm_index": 6}
    # multi_bit: multiple '1's or all zeros
    assert _branch_mask_hint("001001000") == {"encoding": "multi_bit",
                                               "one_positions": [3, 6]}
    assert _branch_mask_hint("000000000") == {"encoding": "multi_bit",
                                               "one_positions": []}
    # path: contains '-'
    result = _branch_mask_hint("---001-1--")
    assert result["encoding"] == "path"
    assert result["dontcare_bits"] > 0
    assert result["active_bits"] > 0
    # invalid
    assert _branch_mask_hint("") is None
    assert _branch_mask_hint("else") is None
    assert _branch_mask_hint("0b1010") is None


def test_branch_mask_hint_enabled(monkeypatch):
    from xcov.backend import _branch_mask_hint_enabled
    monkeypatch.delenv("XVERIF_XCOV_BRANCH_MASK_HINT", raising=False)
    assert _branch_mask_hint_enabled() is True
    for v in ("1", "true", "yes", "on"):
        monkeypatch.setenv("XVERIF_XCOV_BRANCH_MASK_HINT", v)
        assert _branch_mask_hint_enabled() is True
    for v in ("0", "false", "no", "off"):
        monkeypatch.setenv("XVERIF_XCOV_BRANCH_MASK_HINT", v)
        assert _branch_mask_hint_enabled() is False


def test_branch_mask_in_response():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "branch-mask",
        "action": "source.map", "target": {"session_id": "cov0"},
        "args": {"file": "rtl/ctrl.sv", "line": 95, "window": 10, "metrics": ["branch"]},
    })
    assert rsp["ok"] is True
    rows = rsp["data"]["items"]
    # one-hot item: "000000100" -> branch_mask
    bin_item = next(row for row in rows
                    if row.get("branch_bin") == "000000100")
    assert "branch_mask" in bin_item
    assert bin_item["branch_mask"]["encoding"] == "one_hot"
    assert bin_item["branch_mask"]["branch_arm_index"] == 2
    # non-bitmask item: "else" -> no branch_mask
    else_item = next(row for row in rows
                     if row.get("branch_bin") == "else")
    assert "branch_mask" not in else_item


def test_branch_mask_in_xout():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "branch-mask-xout",
        "action": "source.map", "target": {"session_id": "cov0"},
        "args": {"file": "rtl/ctrl.sv", "line": 95, "window": 10, "metrics": ["branch"]},
    })
    xout = render_xout(rsp)
    assert "branch_mask.encoding" in xout
    assert "branch_mask.branch_arm_index" in xout


def test_test_each_is_explicitly_unsupported():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "each",
        "action": "code_coverage.holes", "target": {"session_id": "cov0"},
        "args": {"test": "each"},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "TEST_MODE_NOT_SUPPORTED"


def test_export_path_safety(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dispatcher = _dispatch_opened()
    bad_parent = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "bad-parent",
        "action": "export.code_coverage", "target": {"session_id": "cov0"},
        "args": {"output": {"path": "../holes.md"}},
    })
    bad_abs = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "bad-abs",
        "action": "export.code_coverage", "target": {"session_id": "cov0"},
        "args": {"output": {"path": str(tmp_path / "holes.md")}},
    })
    ok = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "ok-rel",
        "action": "export.code_coverage", "target": {"session_id": "cov0"},
        "args": {"output": {"path": "holes.md"}},
    })
    assert bad_parent["error"]["code"] == "OUTPUT_PATH_UNSAFE"
    assert bad_abs["error"]["code"] == "OUTPUT_PATH_UNSAFE"
    assert ok["ok"] is True
    assert (tmp_path / ".xverif/xcov_exports/holes.md").exists()


class CountingBackend(CoverageBackend):
    def __init__(self) -> None:
        self.scopes_called = 0

    def tests(self):
        return [{"name": "t0"}]

    def summary(self):
        return {"test_count": 1, "top_scope_count": 1}

    def scopes(self):
        self.scopes_called += 1
        raise AssertionError("session public_json must not scan scopes")

    def metrics_for_scope(self, scope, test):
        return []

    def items(self, metrics=None, scope=None, test="merged", functional_only=False):
        return []


def test_session_public_json_does_not_scan_scopes():
    backend = CountingBackend()
    session = XcovSession("cov0", "unit-test.vdb", backend, "custom")
    assert session.public_json()["top_scope_count"] == 1
    assert backend.scopes_called == 0


class _FakeNpiSysModule:
    def init(self, argv):
        return 1

    def end(self):
        return 1


class _FakeCovModule:
    def open(self, vdb):
        return object()

    def merge_test(self, left, right):
        return object()

    def release_handle(self, handle):
        return None


def _npi_binding() -> NpiApiBinding:
    return NpiApiBinding(_FakeCovModule(), _FakeNpiSysModule())


def test_functional_identity_is_the_scoped_npi_full_name():
    api = _npi_binding()
    handle = object()
    path = {
        "covergroup": "cg",
        "coverpoint": "cp",
        "bin": "hit",
    }

    assert (
        _validate_functional_identity(
            api,
            handle,
            "top.u_left.cg.cp.hit",
            path,
        )
        == "top.u_left"
    )
    assert (
        _validate_functional_identity(
            api,
            handle,
            "top.u_right.cg.cp.hit",
            path,
        )
        == "top.u_right"
    )

    source = (ROOT / "xcov" / "xcov" / "backend.py").read_text(
        encoding="utf-8"
    )
    assert "_functional_full_name" not in source


def test_functional_component_evidence_must_match_npi_identity():
    with pytest.raises(NpiContractViolation) as raised:
        _validate_functional_identity(
            _npi_binding(),
            object(),
            "top.u0.cg.other.hit",
            {
                "covergroup": "cg",
                "coverpoint": "cp",
                "bin": "hit",
            },
        )

    assert raised.value.failure.operation == "coverage.full_name"
    assert raised.value.failure.cause_type == "NpiResultTypeError"


def test_npi_call_uses_one_declared_signature_without_zero_arg_retry():
    class Handle:
        def __init__(self):
            self.calls = []

        def value(self, *args):
            self.calls.append(args)
            if args:
                raise TypeError("value(test) contract failed")
            return "zero-arg fallback must not run"

    handle = Handle()
    test_handle = object()
    with pytest.raises(NpiContractViolation) as raised:
        _npi_binding().call("coverage.value", handle, test_handle)

    assert handle.calls == [(test_handle,)]
    failure = raised.value.failure
    assert failure.operation == "coverage.value"
    assert failure.method == "value"
    assert failure.expected_signature == "value(test)"
    assert failure.cause_type == "TypeError"


def test_npi_binding_rejects_missing_required_module_method_at_init():
    class CovWithoutMerge:
        def open(self, vdb):
            return object()

        def release_handle(self, handle):
            return None

    with pytest.raises(NpiContractViolation) as raised:
        NpiApiBinding(CovWithoutMerge(), _FakeNpiSysModule())

    failure = raised.value.failure
    assert failure.operation == "cov.merge_test"
    assert failure.method == "merge_test"
    assert failure.expected_signature == "merge_test(left_test, right_test)"
    assert failure.cause_type == "AttributeError"


def test_npi_missing_fact_method_is_a_typed_contract_violation():
    with pytest.raises(NpiContractViolation) as raised:
        _npi_binding().call("coverage.covered", object(), object())

    failure = raised.value.failure
    assert failure.operation == "coverage.covered"
    assert failure.method == "covered"
    assert failure.expected_signature == "covered(test)"
    assert failure.cause_type == "AttributeError"


def test_npi_traversal_none_is_a_contract_violation_not_an_empty_result():
    class Handle:
        def child_handles(self):
            return None

    with pytest.raises(NpiContractViolation) as raised:
        _npi_binding().call("coverage.child_handles", Handle())

    assert raised.value.failure.operation == "coverage.child_handles"
    assert raised.value.failure.cause_type == "TypeError"


def test_npi_traversal_rejects_string_instead_of_iterating_characters():
    class Handle:
        def child_handles(self):
            return "not-a-handle-list"

    with pytest.raises(NpiContractViolation) as raised:
        _npi_binding().call("coverage.child_handles", Handle())

    assert raised.value.failure.operation == "coverage.child_handles"
    assert raised.value.failure.cause_type == "TypeError"


class ContractFailingBackend(CoverageBackend):
    worker_kind = "npi_contract_test"

    def summary(self):
        return {"test_count": 1, "top_scope_count": 1}

    def tests(self):
        return [{"name": "t0"}]

    def scopes(self):
        return []

    def metrics_for_scope(self, scope, test):
        return []

    def items(self, metrics=None, scope=None, test="merged", functional_only=False):
        raise NpiContractViolation(
            NpiCallFailure(
                operation="coverage.covered",
                object_type="BrokenCoverageHandle",
                method="covered",
                expected_signature="covered(test)",
                cause_type="RuntimeError",
                cause_message="coverage handle is invalid",
            )
        )


def test_npi_contract_failure_propagates_to_incomplete_action_error():
    dispatcher = Dispatcher(
        SessionManager(
            backend_factory=lambda _vdb: ContractFailingBackend(),
        )
    )
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-contract-failure",
        "action": "session.open",
        "target": {"vdb": "contract-failure.vdb"},
        "args": {"name": "cov0"},
    })
    assert opened["ok"] is True

    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "query-contract-failure",
        "action": "metrics.list",
        "target": {"session_id": "cov0"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "NPI_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.error_layer"] == "backend"
    assert rsp["error"]["detail.operation"] == "coverage.covered"
    assert rsp["error"]["detail.expected_signature"] == "covered(test)"
    assert rsp["summary"]["scan_complete"] is False
    assert rsp["summary"]["analysis_complete"] is False
    assert rsp["summary"]["total_count"] == 0
    assert rsp["summary"]["returned_count"] == 0
    assert rsp["data"] == {}


def test_npi_backend_source_has_no_safe_call_or_arity_fallback():
    source = (ROOT / "xcov" / "xcov" / "backend.py").read_text(
        encoding="utf-8"
    )
    assert "_safe_call" not in source
    assert "_safe_list" not in source
    assert "return fn()" not in source


class MutatingCoverageBackend(FakeCoverageBackend):
    def __init__(self, vdb, mutate, *, worker_kind="custom") -> None:
        super().__init__(vdb)
        self._mutate = mutate
        self.worker_kind = worker_kind

    def items(self, metrics=None, scope=None, test="merged", functional_only=False):
        rows = super().items(
            metrics=metrics,
            scope=scope,
            test=test,
            functional_only=functional_only,
        )
        self._mutate(rows)
        return rows


def _dispatch_with_mutating_backend(mutate, *, worker_kind="custom") -> Dispatcher:
    dispatcher = Dispatcher(
        SessionManager(
            backend_factory=lambda vdb: MutatingCoverageBackend(
                vdb,
                mutate,
                worker_kind=worker_kind,
            ),
        )
    )
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-mutating",
        "action": "session.open",
        "target": {"vdb": "mutating.vdb"},
        "args": {"name": "cov0"},
    })
    assert opened["ok"] is True
    return dispatcher


def _query_mutating_backend(dispatcher: Dispatcher) -> dict:
    return dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "query-mutating",
        "action": "metrics.list",
        "target": {"session_id": "cov0"},
    })


@pytest.mark.parametrize(
    "mutate,field",
    [
        (lambda rows: rows[0].__setitem__("covered", "1"), "covered"),
        (lambda rows: rows[0].__setitem__("covered", 2), "covered"),
        (
            lambda rows: rows[0].update({
                "covered": -1,
                "coverable": -1,
                "missing": None,
                "coverage_pct": None,
            }),
            "covered/coverable",
        ),
        (lambda rows: rows[0].__setitem__("missing", 1), "missing"),
        (lambda rows: rows[0].__setitem__("coverage_pct", 99.0), "coverage_pct"),
        (
            lambda rows: rows[0].__setitem__(
                "evidence",
                {"file": "rtl/ctrl.sv", "line": "12"},
            ),
            "evidence.line",
        ),
        (
            lambda rows: rows[0].__setitem__(
                "evidence",
                {"file": "rtl/ctrl.sv", "line": 12, "column": 3},
            ),
            "evidence",
        ),
    ],
)
def test_injected_backend_semantic_corruption_is_typed_and_incomplete(
    mutate,
    field,
):
    rsp = _query_mutating_backend(_dispatch_with_mutating_backend(mutate))

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.operation"] == "items.canonicalize"
    assert rsp["error"]["detail.field"] == field
    assert rsp["summary"]["scan_complete"] is False
    assert rsp["summary"]["analysis_complete"] is False
    assert rsp["data"] == {}


def test_npi_success_with_semantically_invalid_percentage_is_typed_npi_failure():
    def mutate(rows):
        rows[0]["coverage_pct"] = 42.0

    rsp = _query_mutating_backend(
        _dispatch_with_mutating_backend(mutate, worker_kind="npi_python_test")
    )

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "NPI_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.operation"] == "items.canonicalize"
    assert rsp["error"]["detail.field"] == "coverage_pct"
    assert rsp["summary"]["scan_complete"] is False
    assert rsp["summary"]["analysis_complete"] is False


def test_assert_count_bin_must_have_nonnegative_count():
    def mutate(rows):
        count_bin = next(
            row for row in rows if row["type"] == "npiCovAttemptBin"
        )
        count_bin["count"] = -1

    dispatcher = _dispatch_with_mutating_backend(mutate)
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "bad-assert-count",
        "action": "assert.summary",
        "target": {"session_id": "cov0"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.field"] == "count"
    assert rsp["summary"]["analysis_complete"] is False


def test_non_applicable_backend_values_are_canonical_nulls_not_query_guesses():
    dispatcher = _dispatch_with_mutating_backend(lambda rows: None)
    backend = dispatcher.sessions.get("cov0").backend
    assert isinstance(backend, CanonicalCoverageBackend)

    rows = backend.items(metrics=["assert"])
    count_bin = next(row for row in rows if row["type"] == "npiCovAttemptBin")
    assert count_bin["covered"] is None
    assert count_bin["coverable"] is None
    assert count_bin["missing"] is None
    assert count_bin["coverage_pct"] is None
    assert count_bin["count"] == 10

    assert_object = next(row for row in rows if row["type"] == "npiCovAssert")
    assert assert_object["count"] is None


def test_absent_evidence_is_canonical_empty_evidence_and_not_an_error():
    def mutate(rows):
        rows[0].pop("evidence")

    dispatcher = _dispatch_with_mutating_backend(mutate)
    row = dispatcher.sessions.get("cov0").backend.items(metrics=["line"])[0]
    assert row["evidence"] == {"file": None, "line": None}


class InvalidSummaryBackend(FakeCoverageBackend):
    worker_kind = "custom"

    def summary(self):
        return {"test_count": "1", "top_scope_count": 1}


def test_backend_summary_shape_is_validated_before_session_publication():
    dispatcher = Dispatcher(
        SessionManager(backend_factory=InvalidSummaryBackend)
    )
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "bad-summary",
        "action": "session.open",
        "target": {"vdb": "bad-summary.vdb"},
        "args": {"name": "cov0"},
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.field"] == "summary.test_count"
    assert dispatcher.sessions.sessions == {}


class InvalidTestsBackend(FakeCoverageBackend):
    worker_kind = "custom"

    def tests(self):
        return [{"name": ""}]


def test_backend_test_identity_is_fail_closed():
    dispatcher = Dispatcher(
        SessionManager(backend_factory=InvalidTestsBackend)
    )
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-bad-tests",
        "action": "session.open",
        "target": {"vdb": "bad-tests.vdb"},
        "args": {"name": "cov0"},
    })
    assert opened["ok"] is True

    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "bad-tests",
        "action": "tests.list",
        "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.field"] == "tests.name"


class InvalidScopesBackend(FakeCoverageBackend):
    worker_kind = "custom"

    def scopes(self):
        rows = super().scopes()
        rows[0]["depth"] = 99
        return rows


def test_backend_scope_hierarchy_is_fail_closed():
    dispatcher = Dispatcher(
        SessionManager(backend_factory=InvalidScopesBackend)
    )
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-bad-scopes",
        "action": "session.open",
        "target": {"vdb": "bad-scopes.vdb"},
        "args": {"name": "cov0"},
    })
    assert opened["ok"] is True

    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "bad-scopes",
        "action": "scope.summary",
        "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.field"] == "scopes.depth"


class InvalidScopeParentBackend(FakeCoverageBackend):
    worker_kind = "custom"

    def scopes(self):
        rows = super().scopes()
        child = next(row for row in rows if row["depth"] == 1)
        child["parent"] = "wrong_parent"
        return rows


def test_backend_scope_parent_mismatch_is_a_typed_contract_violation():
    dispatcher = Dispatcher(
        SessionManager(backend_factory=InvalidScopeParentBackend)
    )
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-bad-scope-parent",
        "action": "session.open",
        "target": {"vdb": "bad-scope-parent.vdb"},
        "args": {"name": "cov0"},
    })
    assert opened["ok"] is True

    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "bad-scope-parent",
        "action": "scope.summary",
        "target": {"session_id": "cov0"},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.field"] == "scopes.parent"
    assert rsp["summary"]["analysis_complete"] is False


def test_source_annotate_source_read_failure_is_typed_without_annotation_fallback():
    dispatcher = _dispatch_opened()
    rsp = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "source-read-failed",
        "action": "source.annotate",
        "target": {"session_id": "cov0"},
        "args": {
            "file": "rtl/ctrl.sv",
            "line": 12,
            "window": 0,
            "include_source_text": True,
        },
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SOURCE_READ_FAILED"
    assert rsp["summary"]["scan_complete"] is False
    assert rsp["summary"]["analysis_complete"] is False
    assert rsp["data"] == {}


def test_stdio_uses_only_request_id_and_rejects_id_alias():
    rc, out = _stdio_exchange([{
        "api_version": "xcov.v1",
        "id": "legacy-id",
        "action": "actions",
    }])

    assert rc == 0
    assert out[1]["request_id"] == "req-unknown"
    assert "id" not in out[1]
    assert out[1]["ok"] is False
    assert out[1]["json"]["error"]["code"] == "SCHEMA_INVALID"
    assert out[1]["json"]["error"]["detail.path"] == "$"


def test_stdio_quit_uses_a_separate_strict_control_envelope():
    rc, out = _stdio_exchange([{
        "api_version": "xcov.v1",
        "request_id": "quit",
        "action": "stdio.quit",
    }])

    assert rc == 0
    assert out[1] == {
        "request_id": "quit",
        "ok": True,
        "api_version": "xcov.v1",
        "action": "stdio.quit",
        "payload_format": "json",
        "json": {
            "ok": True,
            "api_version": "xcov.v1",
            "request_id": "quit",
            "action": "stdio.quit",
        },
    }


@pytest.mark.parametrize(
    "control,code",
    [
        (
            {"request_id": "quit", "action": "stdio.quit"},
            "API_VERSION_UNSUPPORTED",
        ),
        (
            {"api_version": "xcov.v1", "action": "stdio.quit"},
            "SCHEMA_INVALID",
        ),
        (
            {
                "api_version": "xcov.v1",
                "request_id": "quit",
                "action": "stdio.quit",
                "args": {},
            },
            "SCHEMA_INVALID",
        ),
    ],
)
def test_stdio_quit_rejects_missing_or_unknown_control_fields(control, code):
    rc, out = _stdio_exchange([control])

    assert rc == 0
    assert out[1]["ok"] is False
    assert out[1]["json"]["error"]["code"] == code
