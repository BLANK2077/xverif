from __future__ import annotations

from copy import deepcopy
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from xcov.actions import ACTION_REGISTRY, Dispatcher, _selected_scope_children
from xcov import cli as xcov_cli
from xcov.backend import (
    CanonicalCoverageBackend,
    CoverageBackend,
    NpiApiBinding,
    NpiCallFailure,
    NpiContractViolation,
    NpiCoverageBackend,
    UrgCoverageBackend,
    _validate_functional_identity,
)
from xcov.backend import CoverageBackend as _CoverageBackend

class _TestBackend(_CoverageBackend):
    """Minimal test-only backend. Not a production VDB selector."""
    worker_kind = "test"
    def __init__(self, vdb="test.vdb", exclusion_policy="default"):
        self.vdb = vdb; self.exclusion_policy = exclusion_policy
        self._items = [
            {"metric":"line","type":"npiCovStmtBin","scope":"top.u_dut","name":"s1","full_name":"top.u_dut.s1","covered":1,"coverable":1,"missing":0,"count":1,"coverage_pct":100.0,"status":["covered"],"evidence":{"file":"a.sv","line":1}},
            {"metric":"toggle","type":"npiCovToggleBin","scope":"top.u_dut","name":"t1","full_name":"top.u_dut.t1","toggle_signal":"s","toggle_bit":"s[0]","toggle_transition":"0->1","covered":0,"coverable":1,"missing":1,"count":0,"coverage_pct":0.0,"status":["not_covered"],"evidence":{"file":"a.sv","line":2}},
        ]
    def tests(self): return [{"name": f"{self.vdb}/test"}]
    def summary(self): return {"test_count":1,"top_scope_count":1}
    def top_scopes(self): return [{"name":"top","full_name":"top","parent":None,"depth":0,"type":"instance"}]
    def scopes(self): return self.top_scopes()
    def scope_metrics(self):
        return {
            "top": {
                "line": {"covered": 1, "coverable": 1, "missing": 0, "pct": 100.0},
                "toggle": {"covered": 0, "coverable": 1, "missing": 1, "pct": 0.0},
            }
        }
    def items(self, **kw):
        rows = list(self._items)
        metrics = kw.get("metrics")
        if metrics is not None:
            rows = [row for row in rows if row.get("metric") in metrics]
        scope = kw.get("scope")
        if scope is not None:
            rows = [row for row in rows if row.get("scope") == scope]
        if kw.get("functional_only"):
            rows = [row for row in rows if row.get("metric") == "functional"]
        return rows
    def load_exclusions(self,paths,test="merged"): return [{"path":p,"status":"loaded"} for p in paths]
    def set_exclusion(self,ref,excluded,test="merged"): return {"coverage_ref":ref,"status":"changed","before":False,"after":excluded}
    def save_exclusions(self,path,test="merged"): pass
    def unload_exclusions(self,test="merged"): pass
    def scope_functional_from_urg(self): return []
    def scope_assert_from_urg(self): return []
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


@pytest.mark.parametrize("size", [1_000, 10_000])
def test_scope_child_index_operation_count_is_linear(size):
    rows = [{
        "full_name": "top" if index == 0 else f"top.u{index}",
        "parent": None if index == 0 else "top",
    } for index in range(size)]
    selected = [row["full_name"] for row in rows]
    counter = {}
    children = _selected_scope_children(rows, selected, counter)
    assert counter["scope_index_operations"] == 2 * size
    assert len(children["top"]) == size - 1


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
                          text=True, encoding="utf-8", capture_output=True, check=False,
                          cwd=str(ROOT), env=merged_env)


def _read_last_json_line(path: Path) -> dict:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert lines
    return json.loads(lines[-1])


def _fake_dispatcher() -> Dispatcher:
    return Dispatcher(
        SessionManager(
            backend_factory=lambda vdb, **_kwargs: _TestBackend(vdb),
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
        + ',"output":{"path":"export.md"}}}'
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

    def factory(path, **_kwargs):
        opened_vdbs.append(path)
        return _TestBackend(path)

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
        backend_factory=lambda path, **_kwargs: (
            opened_vdbs.append(path) or _TestBackend(path)
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

    def factory(vdb, **_kwargs):
        opened_vdbs.append(vdb)
        return _TestBackend(vdb)

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


def test_native_session_manager_allows_only_one_live_session_per_process():
    opened_vdbs = []

    def factory(vdb, **_kwargs):
        opened_vdbs.append(vdb)
        return _TestBackend(vdb)

    dispatcher = Dispatcher(SessionManager(backend_factory=factory))
    first = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-first-native",
        "action": "session.open",
        "target": {"vdb": "first.vdb"},
        "args": {"name": "cov_first"},
    })
    second = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "request_id": "open-second-native",
        "action": "session.open",
        "target": {"vdb": "second.vdb"},
        "args": {"name": "cov_second"},
    })

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"]["code"] == "SESSION_CAPACITY_EXCEEDED"
    assert second["error"]["detail.live_session_id"] == "cov_first"
    assert second["error"]["detail.capacity"] == 1
    assert opened_vdbs == ["first.vdb"]


def test_fake_backend_is_not_a_production_vdb_selector():
    manager = SessionManager()
    assert manager._backend_factory is UrgCoverageBackend

    opened_vdbs = []

    def factory(vdb, **_kwargs):
        opened_vdbs.append(vdb)
        return _TestBackend(vdb)

    injected = SessionManager(backend_factory=factory)
    session = injected.open("fake", name="literal-fake")
    assert opened_vdbs == ["fake"]
    assert session.vdb == "fake"

    source = (ROOT / "xcov" / "xcov" / "session.py").read_text(
        encoding="utf-8"
    )
    assert "_TestBackend" not in source
    assert 'vdb == "fake"' not in source


def test_urg_backend_initializes_npi_only_for_exclusion(monkeypatch, tmp_path):
    from xcov import backend as backend_module
    from xcov.urg_summary import UrgSummaryIndex

    index = UrgSummaryIndex(
        metric_names=("Line",),
        tests=("test0",),
        scopes=({
            "name": "top", "full_name": "top", "parent": None,
            "depth": 0, "type": "instance",
        },),
        scope_metrics={
            "top": {
                "line": {
                    "covered": 1, "coverable": 1, "missing": 0, "pct": 100.0,
                },
            },
        },
        functional_rows=(),
        assertion_rows=(),
    )
    monkeypatch.setattr(
        backend_module,
        "load_cached_urg_summary",
        lambda _vdb, **_kwargs: (index, {"key": "unit", "hit": False}),
    )
    created = []

    def npi_factory(vdb, **kwargs):
        created.append((vdb, kwargs))
        return _TestBackend(vdb, **kwargs)

    backend = UrgCoverageBackend("read-only.vdb", npi_factory=npi_factory)
    assert backend.summary() == {"test_count": 1, "top_scope_count": 1}
    assert backend.tests() == [{"name": "test0"}]
    assert backend.scopes()[0]["full_name"] == "top"
    assert backend.scope_metrics()["top"]["line"]["covered"] == 1
    assert created == []
    assert backend.npi_initialized is False

    backend.save_exclusions(str(tmp_path / "baseline.el"))
    backend.save_exclusions(str(tmp_path / "second.el"))
    assert len(created) == 1
    assert backend.npi_initialized is True
    backend.close()


def test_session_close_uses_pre_close_snapshot_without_backend_read():
    class CloseSensitiveBackend(_TestBackend):
        def __init__(self, vdb, exclusion_policy="default"):
            super().__init__(vdb, exclusion_policy)
            self.closed = False

        def close(self):
            self.closed = True

        def summary(self):
            if self.closed:
                raise AssertionError("closed backend must not be queried")
            return super().summary()

    dispatcher = Dispatcher(SessionManager(backend_factory=CloseSensitiveBackend))
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "open-close-sensitive",
        "action": "session.open", "target": {"vdb": "close-sensitive.vdb"},
        "args": {"name": "cov0"},
    })
    assert opened["ok"] is True
    closed = dispatcher.dispatch({
        "api_version": "xcov.v1", "request_id": "close-sensitive",
        "action": "session.close", "target": {"session_id": "cov0"},
    })
    assert closed["ok"] is True
    assert closed["data"]["session"]["state"] == "closed"


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
    assert session_rsp["data"]["cached_indexes"] == {
        "state": "lazy", "key": None, "hit": None,
    }
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
            "api_version": "xcov.v1", "action": "code_coverage.summary",
            "target": {"session_id": "cov0", "unexpected_target": True},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.summary",
            "target": {"session_id": "cov0"},
            "args": {"unexpected_arg": True},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.summary",
            "target": {"session_id": "cov0"},
            "args": {"query": {"unexpected_query": True}},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.summary",
            "target": {"session_id": "cov0"},
            "args": {"sort": {"unexpected_sort": True}},
        },
        {
            "api_version": "xcov.v1", "action": "code_coverage.summary",
            "target": {"session_id": "cov0"},
            "args": {"limits": {"unexpected_limit": True}},
        },
        {
            "api_version": "xcov.v1", "action": "export.code_coverage",
            "target": {"session_id": "cov0"},
            "args": {
                "output": {"path": "export.md", "unexpected_output": True},
            },
        },
    ]
    for req in requests:
        rsp = dispatcher.dispatch(req)
        assert rsp["ok"] is False, req
        assert rsp["error"]["code"] == "SCHEMA_INVALID", req
        assert "detail.path" in rsp["error"], req




def test_backend_empty_metric_selector_means_no_metrics_not_all_metrics():
    assert _TestBackend("unit.vdb").items(metrics=[]) == []


@pytest.mark.parametrize(
    "action",
    ["code_coverage.summary"],
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
        ("metrics.list", {"test": "t0"}, "$.args"),
        ("scope.summary", {"test": "t0"}, "$.args"),
        ("code_coverage.summary", {"test": "t0"}, "$.args"),
        ("functional_coverage.summary", {"test": "t0"}, "$.args"),
        ("assert.summary", {"test": "t0"}, "$.args"),
        ("code_coverage.summary", {"group_by": "source_file"}, "$.args.group_by"),
        ("code_coverage.summary", {"group_by": "type"}, "$.args.group_by"),
        ("functional_coverage.summary", {"group_by": "bin"}, "$.args.group_by"),
    ],
)
def test_summary_contract_rejects_dimensions_absent_from_fixed_urg_summary(
    action,
    args,
    path,
):
    rsp = _dispatch_opened().dispatch({
        "api_version": "xcov.v1",
        "request_id": "unsupported-summary-dimension",
        "action": action,
        "target": {"session_id": "cov0"},
        "args": args,
    })

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == path


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
    for action in ("code_coverage.summary",
                   "functional_coverage.summary",
                   "assert.summary", "export.code_coverage",
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
               "export.function_coverage",
               "code_coverage.holes", "functional_coverage.holes"}
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


def test_stdio_loop_unknown_action_returns_error_without_crash():
    reqs = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "bad",
         "action": "cov.unknown", "target": {"session_id": "cov0"}},
    ]
    rc, out = _stdio_exchange(reqs)
    assert rc == 0
    assert out[0]["protocol"] == "xcov-stdio-loop"
    assert out[2]["request_id"] == "bad"
    assert "id" not in out[2]
    assert out[2]["ok"] is False
    assert out[2]["action"] == "cov.unknown"
    assert '"/request_id"' not in out[2]["xout"]
    assert '"/action"' not in out[2]["xout"]
    assert out[2]["json"]["error"]["code"] == "UNKNOWN_ACTION"
    assert out[2]["json"]["error"]["detail.requested_action"] == "cov.unknown"


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
        {"api_version": "xcov.v1", "request_id": "summary",
         "action": "code_coverage.summary", "target": {"session_id": "cov0"},
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


def test_regex_rejected():
    reqs = [
        {"api_version": "xcov.v1", "request_id": "open",
         "action": "session.open", "target": {"vdb": "unit-test.vdb"},
         "args": {"name": "cov0"}},
        {"api_version": "xcov.v1", "request_id": "bad",
         "action": "code_coverage.summary", "target": {"session_id": "cov0"},
         "args": {"query": {"include_patterns": ["^top.*"]}}},
    ]
    _, out = _stdio_exchange(reqs)
    assert out[2]["ok"] is False
    assert out[2]["json"]["error"]["code"] == "REGEX_NOT_SUPPORTED"




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
        "api_version": "xcov.v1", "request_id": "limits-test",
        "action": "code_coverage.summary", "target": {"session_id": "cov0"},
        "args": {"scope": "top.u_dut", "metrics": ["toggle", "branch"]},
        "limits": {"max_items": 1},
    })
    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "SCHEMA_INVALID"
    assert rsp["error"]["detail.path"] == "$"






















@pytest.mark.parametrize(
    "group_by",
    ["covergroup", "coverpoint", "cross"],
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






class CountingBackend(CoverageBackend):
    def __init__(self) -> None:
        self.scopes_called = 0

    def tests(self):
        return [{"name": "t0"}]

    def summary(self):
        return {"test_count": 1, "top_scope_count": 1}

    def top_scopes(self):
        return [{"name": "top", "full_name": "top", "parent": None, "depth": 0, "type": "instance"}]

    def scopes(self):
        self.scopes_called += 1
        raise AssertionError("session public_json must not scan scopes")

    def scope_metrics(self):
        return {}

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

    def scope_metrics(self):
        return {
            "top": {
                "line": {
                    "covered": 1,
                    "coverable": 1,
                    "missing": 0,
                    "pct": 100.0,
                }
            }
        }

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


def test_summary_query_does_not_call_npi_items():
    dispatcher = Dispatcher(
        SessionManager(
            backend_factory=lambda _vdb, **_kwargs: ContractFailingBackend(),
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

    assert rsp["ok"] is True
    assert rsp["data"]["items"] == [{
        "metric": "line",
        "covered": 1,
        "coverable": 1,
        "missing": 0,
        "coverage_pct": 100.0,
    }]


def test_npi_backend_source_has_no_safe_call_or_arity_fallback():
    source = (ROOT / "xcov" / "xcov" / "backend.py").read_text(
        encoding="utf-8"
    )
    assert "_safe_call" not in source
    assert "_safe_list" not in source
    assert "return fn()" not in source


class MutatingCoverageBackend(_TestBackend):
    def __init__(self, vdb, mutate, *, worker_kind="custom", scope_mutate=False) -> None:
        super().__init__(vdb)
        self._mutate = mutate
        self.worker_kind = worker_kind
        self._scope_mutate = scope_mutate

    def items(self, metrics=None, scope=None, test="merged", functional_only=False):
        rows = super().items(
            metrics=metrics,
            scope=scope,
            test=test,
            functional_only=functional_only,
        )
        self._mutate(rows)
        return rows

    def scope_metrics(self):
        rows = super().scope_metrics()
        if self._scope_mutate:
            self._mutate(rows)
        return rows


def _dispatch_with_mutating_backend(
    mutate,
    *,
    worker_kind="custom",
    scope_mutate=False,
) -> Dispatcher:
    dispatcher = Dispatcher(
        SessionManager(
            backend_factory=lambda vdb, **_kwargs: MutatingCoverageBackend(
                vdb,
                mutate,
                worker_kind=worker_kind,
                scope_mutate=scope_mutate,
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
        (lambda rows: rows["top"]["line"].__setitem__("covered", "1"), "covered"),
        (lambda rows: rows["top"]["line"].__setitem__("covered", 2), "covered/coverable/missing"),
        (
            lambda rows: rows["top"]["line"].update({
                "covered": -1,
                "coverable": -1,
                "missing": 0,
                "pct": 0.0,
            }),
            "covered",
        ),
        (lambda rows: rows["top"]["line"].__setitem__("missing", 1), "covered/coverable/missing"),
        (lambda rows: rows["top"]["line"].__setitem__("pct", 99.0), "pct"),
        (
            lambda rows: rows["top"]["line"].__setitem__("unexpected", True),
            "metric_values",
        ),
    ],
)
def test_injected_backend_semantic_corruption_is_typed_and_incomplete(
    mutate,
    field,
):
    rsp = _query_mutating_backend(
        _dispatch_with_mutating_backend(mutate, scope_mutate=True)
    )

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.operation"] == "scope_metrics.canonicalize"
    assert rsp["error"]["detail.field"] == field
    assert rsp["summary"]["scan_complete"] is False
    assert rsp["summary"]["analysis_complete"] is False
    assert rsp["data"] == {}


def test_urg_scope_metric_with_invalid_percentage_is_typed_backend_failure():
    def mutate(rows):
        rows["top"]["line"]["pct"] = 42.0

    rsp = _query_mutating_backend(
        _dispatch_with_mutating_backend(
            mutate,
            worker_kind="npi_python_test",
            scope_mutate=True,
        )
    )

    assert rsp["ok"] is False
    assert rsp["error"]["code"] == "BACKEND_CONTRACT_VIOLATION"
    assert rsp["error"]["detail.operation"] == "scope_metrics.canonicalize"
    assert rsp["error"]["detail.field"] == "pct"
    assert rsp["summary"]["scan_complete"] is False
    assert rsp["summary"]["analysis_complete"] is False






def test_absent_evidence_is_canonical_empty_evidence_and_not_an_error():
    def mutate(rows):
        rows[0].pop("evidence")

    dispatcher = _dispatch_with_mutating_backend(mutate)
    row = dispatcher.sessions.get("cov0").backend.items(metrics=["line"])[0]
    assert row["evidence"] == {"file": None, "line": None}


class InvalidSummaryBackend(_TestBackend):
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


class InvalidTestsBackend(_TestBackend):
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


class InvalidScopesBackend(_TestBackend):
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


class InvalidScopeParentBackend(_TestBackend):
    worker_kind = "custom"

    def scopes(self):
        rows = super().scopes()
        child = next(row for row in rows if row["depth"] == 1)
        child["parent"] = "wrong_parent"
        return rows




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


def test_branch_v2_groups_real_urg_vectors_by_decision_path():
    from xcov.code_export import parse_metric_report, render_metric_xout

    scope = "top.u_dut"
    report = """===============================================================================
Module : dut
===============================================================================
Source File(s) :

/workspace/dut.sv

Module self-instances :

SCORE  BRANCH NAME
 75.00  75.00 top.u_dut

===============================================================================
Module Instance : top.u_dut
===============================================================================

Branch Coverage for Instance : top.u_dut
         Line No. Total Covered Percent
Branches          4     2       50.00
IF       7        4     2       50.00

7              if (a == 0) sum = b;
               -1-
               ==>
8              else if (b == 0) sum = a;
                    -2-
               ==>
9              else if (a == b) sum = a + 1;
                    -3-
               ==>
10             else sum = a + b;
               ==>

Branches:

-1- -2- -3- Status
1   -   -   Covered
0   1   -   Not Covered
0   0   1   Covered
0   0   0   Not Covered

"""
    payload = parse_metric_report(report, scope, "branch")

    assert payload["schema"] == "xcov.code_coverage.branch.v2"
    assert payload["decision_group_count"] == 1
    assert payload["gap_count"] == 2
    group = payload["decision_groups"][0]
    assert [item["marker"] for item in group["decision_path"]] == ["-1-", "-2-", "-3-"]
    assert [row["values"] for row in group["uncovered"]] == [["0", "1", "-"], ["0", "0", "0"]]
    assert [row["gap_id"] for row in group["uncovered"]] == ["B0001", "B0002"]
    xout = render_metric_xout(payload, "branch.urg.txt")
    assert xout.startswith("@xcov.code_coverage.branch.v2\n")
    assert "marker  kind" in xout
    assert "gap_id  -1-  -2-  -3-" in xout
    assert "status" not in xout
    assert "\n  uncovered:\n" in xout
    assert "\n\n  uncovered:\n" not in xout


def test_branch_v2_recovers_multiline_continuous_assign_ternary(tmp_path):
    from xcov.code_export import parse_metric_report, render_metric_xout

    source = tmp_path / "dut.sv"
    source.write_text(
        "\n" * 150
        + "  assign feature = (data[7:4] == 4'hd)\n"
        + "                 ? reject\n"
        + "                 : data[0];\n",
        encoding="utf-8",
    )
    scope = "top.u_dut"
    report = f"""===============================================================================
Module : dut
===============================================================================
Source File(s) :

{source}

Module self-instances :

SCORE  BRANCH NAME
 50.00  50.00 top.u_dut

===============================================================================
Module Instance : top.u_dut
===============================================================================

Branch Coverage for Instance : top.u_dut
         Line No. Total Covered Percent
Branches          2     1       50.00

151          assign feature = (data[7:4] == 4'hd)
152                           ? reject
                              -1-
                              ==>
                              ==>

Branches:

-1- Status
1   Not Covered
0   Covered

"""

    payload = parse_metric_report(report, scope, "branch")

    assert payload["gap_count"] == 1
    decision = payload["decision_groups"][0]["decision_path"][0]
    assert decision == {
        "marker": "-1-",
        "kind": "ternary",
        "at": "dut.sv:151",
        "expression": "data[7:4] == 4'hd",
        "source": "assign feature = (data[7:4] == 4'hd) ? reject : data[0];",
    }
    xout = render_metric_xout(payload, "branch.urg.txt")
    assert "-1-     ternary  dut.sv:151" in xout
    assert "outcomes" not in xout


def test_branch_v2_preserves_spaced_concatenation_case_value():
    from xcov.code_export import parse_metric_report

    scope = "top.u_dut"
    report = """===============================================================================
Module : dut
===============================================================================
Source File(s) :

/workspace/dut.sv

Module Instance : top.u_dut
===============================================================================

Branch Coverage for Instance : top.u_dut
         Line No. Total Covered Percent
Branches          8     7       87.50
CASE     20        8     7       87.50

20             unique casez ({state, valid, data[1:0]})
                         -1-
21               {BUSY, 1'b1, 2'b10}: next_state = HALT;
                 ==>

Branches:

-1-                       Status
{BUSY, 1'b1, 2'b10}       Not Covered
"""

    payload = parse_metric_report(report, scope, "branch")

    assert payload["decision_groups"][0]["uncovered"][0]["values"] == [
        "{BUSY, 1'b1, 2'b10}",
    ]


def test_branch_v2_recovers_multiline_nonblocking_ternary(tmp_path):
    from xcov.code_export import parse_metric_report

    source = tmp_path / "dut.sv"
    source.write_text(
        "\n" * 45
        + "      2'b01: response_class <=\n"
        + "        (data[3:0] == 4'he) ? 2'b10 : 2'b01;\n",
        encoding="utf-8",
    )
    scope = "top.u_dut"
    report = f"""===============================================================================
Module : dut
===============================================================================
Source File(s) :

{source}

Module Instance : top.u_dut
===============================================================================

Branch Coverage for Instance : top.u_dut
         Line No. Total Covered Percent
Branches          2     1       50.00

46             2'b01: response_class <=
47               (data[3:0] == 4'he) ? 2'b10 : 2'b01;
                                      -1-

Branches:

-1- Status
1   Not Covered
"""

    payload = parse_metric_report(report, scope, "branch")

    decision = payload["decision_groups"][0]["decision_path"][0]
    assert decision["at"] == "dut.sv:47"
    assert "outcomes" not in decision


def test_line_v2_groups_uncovered_statements_by_construct():
    from xcov.code_export import parse_metric_report, render_metric_xout

    scope = "top.u_dut"
    report = """===============================================================================
Module : dut
===============================================================================
Source File(s) :

/workspace/dut.sv

Module self-instances :

SCORE  LINE NAME
 40.00  40.00 top.u_dut

===============================================================================
Module Instance : top.u_dut
===============================================================================

Line Coverage for Instance : top.u_dut

             Line No.   Total   Covered  Percent
TOTAL                        5        2    40.00
ALWAYS             10        3        1    33.33
ALWAYS             20        2        1    50.00

12         0/1     ==>      first <= 1'b1;
13         0/1     ==>      second <= 1'b1;
21         0/1     ==>      third <= 1'b1;

"""

    payload = parse_metric_report(report, scope, "line")

    assert payload["schema"] == "xcov.code_coverage.line.v2"
    assert payload["line_group_count"] == 2
    assert payload["gap_count"] == 3
    assert payload["line_groups"][0]["context"] == {
        "kind": "always",
        "at": "dut.sv:10",
        "covered": 1,
        "coverable": 3,
        "missing": 2,
        "pct": 33.33,
    }
    assert [row["gap_id"] for row in payload["line_groups"][0]["uncovered"]] == ["L0001", "L0002"]
    xout = render_metric_xout(payload, "line.urg.txt")
    assert xout.startswith("@xcov.code_coverage.line.v2\n")
    assert "kind    at         covered  coverable  missing  pct" in xout
    assert "\n  uncovered:\n" in xout
    assert "\n\n  uncovered:\n" not in xout
    assert "hits" not in xout
    assert "required" not in xout


def test_condition_v2_merges_equivalent_expression_and_subexpression_gaps():
    from xcov.code_export import parse_metric_report, render_metric_xout

    scope = "top.u_dut"
    report = """===============================================================================
Module : dut
===============================================================================
Source File(s) :

/workspace/dut.sv

Module self-instances :

SCORE  COND NAME
 50.00  50.00 top.u_dut

===============================================================================
Module Instance : top.u_dut
===============================================================================

Cond Coverage for Instance : top.u_dut

               Total   Covered  Percent
Conditions          2        0     0.00
Logical             2        0     0.00
Non-Logical         0        0
Event               0        0

 LINE       46
 EXPRESSION ((request.data[3:0] == 4'he) ? 2'b10 : 2'b1)
             -------------1-------------

-1- Status
 1  Not Covered

 LINE       46
 SUB-EXPRESSION (request.data[3:0] == 4'he)
                -------------1-------------

-1- Status
 1  Not Covered

"""

    payload = parse_metric_report(report, scope, "condition")

    assert payload["schema"] == "xcov.code_coverage.condition.v2"
    assert payload["condition_group_count"] == 1
    assert payload["coverage_object_gap_count"] == 2
    assert payload["gap_count"] == 1
    group = payload["condition_groups"][0]
    assert group["condition"] == {
        "at": "dut.sv:46",
        "expression": "((request.data[3:0] == 4'he) ? 2'b10 : 2'b1)",
    }
    assert group["terms"] == [{"marker": "-1-", "expression": "request.data[3:0] == 4'he"}]
    assert group["uncovered"] == [{
        "values": ["1"],
        "origins": [
            {
                "kind": "expression",
                "raw_expression": "((request.data[3:0] == 4'he) ? 2'b10 : 2'b1)",
            },
            {
                "kind": "sub_expression",
                "raw_expression": "(request.data[3:0] == 4'he)",
            },
        ],
        "gap_id": "C0001",
    }]
    xout = render_metric_xout(payload, "condition.urg.txt")
    assert xout.startswith("@xcov.code_coverage.condition.v2\n")
    assert "coverage_object_gap_count: 2" in xout
    assert "gap_count: 1" in xout
    assert xout.count("C0001") == 1
    assert "origins" not in xout
    assert "urg_vector" not in xout
    assert "decoded_vector" not in xout
    assert "required" not in xout
    assert "outcomes" not in xout
    assert "\n  uncovered:\n" in xout
    assert "\n\n  uncovered:\n" not in xout


def test_fsm_v2_groups_multiple_fsms_and_renders_gap_tables():
    from xcov.code_export import parse_metric_report, render_metric_xout

    scope = "top.u_dut"
    report = """===============================================================================
Module : dut
===============================================================================
Source File(s) :

/workspace/dut.sv

Module self-instances :

SCORE  FSM NAME
 54.55 54.55 top.u_dut

===============================================================================
Module Instance : top.u_dut
===============================================================================

FSM Coverage for Instance : top.u_dut
Summary for FSM :: state
            Total Covered Percent
States      4     4       100.00  (Not included in score)
Transitions 6     4       66.67
Sequences   0     0

State, Transition and Sequence Details for FSM :: state
states  Line No. Covered
IDLE    37       Covered
transitions   Line No. Covered
ACCEPT->IDLE  37       Not Covered
EXECUTE->IDLE 37       Not Covered

Summary for FSM :: monitor_state
            Total Covered Percent
States      4     3       75.00  (Not included in score)
Transitions 5     2       40.00
Sequences   0     0

State, Transition and Sequence Details for FSM :: monitor_state
states  Line No. Covered
MON_HALT 205 Not Covered
transitions   Line No. Covered
MON_BUSY->MON_HALT 211 Not Covered
MON_RETRY->MON_HALT 212 Not Covered
"""

    payload = parse_metric_report(report, scope, "fsm")

    assert payload["schema"] == "xcov.code_coverage.fsm.v2"
    assert payload["coverage"] == {
        "covered": 6, "coverable": 11, "missing": 5, "pct": 54.55,
    }
    assert payload["fsm_group_count"] == 2
    assert payload["gap_count"] == 5
    assert [group["fsm"] for group in payload["fsm_groups"]] == ["state", "monitor_state"]
    assert [gap["gap_id"] for group in payload["fsm_groups"] for gap in group["gaps"]] == [
        "F0001", "F0002", "F0003", "F0004", "F0005",
    ]
    xout = render_metric_xout(payload, "fsm.urg.txt")
    assert xout.startswith("@xcov.code_coverage.fsm.v2\n")
    assert "gap_id  kind        object" in xout
    assert "- fsm: state" in xout
    assert "\n\n- fsm: monitor_state" in xout
    assert "required" not in xout
def _x_npi_coverage_helper_for_open_compat():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "skills/x-npi/scripts/x_npi/coverage.py"
    spec = importlib.util.spec_from_file_location("x_npi_coverage_compat", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cov_open_contract_accepts_supported_signatures():
    from xcov.backend import _cov_open_contract

    def old_open(vdb):
        return vdb

    def new_open(vdb, config_opt=0):
        return vdb, config_opt

    assert _cov_open_contract(old_open).positional_args == ("vdb",)
    assert _cov_open_contract(new_open).positional_args == ("vdb", "config_opt")


def test_x_npi_open_covdb_calls_old_interface_once(monkeypatch):
    from types import SimpleNamespace
    import pytest

    helper = _x_npi_coverage_helper_for_open_compat()
    calls = []

    def old_open(vdb):
        calls.append((vdb,))
        return object()

    monkeypatch.setattr(helper, "_cov", lambda: SimpleNamespace(open=old_open))
    helper.open_covdb("old.vdb")
    assert calls == [("old.vdb",)]
    with pytest.raises(RuntimeError, match="does not support strict"):
        helper.open_covdb("old.vdb", strict=True)
    assert calls == [("old.vdb",)]


def test_x_npi_open_covdb_calls_new_interface_once(monkeypatch):
    from types import SimpleNamespace

    helper = _x_npi_coverage_helper_for_open_compat()
    calls = []

    def new_open(vdb, config_opt=0):
        calls.append((vdb, config_opt))
        return object()

    cov = SimpleNamespace(
        open=new_open,
        ConfigOpt=SimpleNamespace(ExclusionInStrictMode=7),
    )
    monkeypatch.setattr(helper, "_cov", lambda: cov)
    helper.open_covdb("default.vdb")
    helper.open_covdb("strict.vdb", strict=True)
    assert calls == [("default.vdb", 0), ("strict.vdb", 7)]
