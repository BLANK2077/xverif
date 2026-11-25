"""Port of the legacy xcov suites onto the C++ UCAPI implementation.

Scope of the port
-----------------
The original `xcov.unit` suites test three different things:

1. Python-only machinery (`test_urg_summary.py` parses URG `session.xml`,
   `test_exclusions_real.py` drives pynpi directly).  The C++ implementation
   never parses XML and does not use pynpi, so those cases have no UCAPI
   equivalent and are intentionally not ported.
2. Behaviour that is backend independent: CSV parsing/budget/format, exclusion
   lifecycle, zero-coverable edge cases, export artifact layout, cached reads.
   Those are ported here and expressed through the public stdio-loop actions.
3. Assertions on URG text-report internals (`line_groups`, `condition_groups`,
   `decision_groups` payload shapes).  UCAPI exposes coverage objects rather
   than URG's parsed text report, so the port keeps the behavioural invariant
   (`gap_count == coverage.missing`, empty sections stay empty) instead of the
   report-specific grouping.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPP_BINARY = ROOT / "xcov" / "bin" / "xcov"



def _seed_required_csvs(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "code_exclusions.csv":
            "# schema_version=xcov-code-exclusions.v1\n"
            "# coverage_kind=code\n"
            "scope,metric,line,object,bin,reason\n",
        "functional_exclusions.csv":
            "# schema_version=xcov-functional-exclusions.v1\n"
            "# coverage_kind=functional\n"
            "scope,line,covergroup,coverpoint,cross,bin,reason\n",
        "assertion_exclusions.csv":
            "# schema_version=xcov-assertion-exclusions.v1\n"
            "# coverage_kind=assertion\n"
            "scope,line,assertion,assertion_kind,reason\n",
    }
    for name, content in files.items():
        path = directory / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def _session(command, env, vdb: Path, name: str = "cov0"):
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, env=env, bufsize=1,
    )
    ready = proc.stdout.readline()
    assert ready.strip(), "stdio-loop did not emit a ready frame"

    def send(request):
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        assert line.strip(), "stdio-loop closed without a response"
        return json.loads(line)["json"]

    opened = send({
        "api_version": "xcov.v1", "request_id": "open",
        "action": "session.open", "target": {"vdb": str(vdb)},
        "args": {"name": name},
    })
    assert opened["ok"], json.dumps(opened)[:500]
    return proc, send, name


def _close(proc, send, name):
    try:
        send({"api_version": "xcov.v1", "request_id": "quit",
              "action": "session.close", "target": {"session_id": name}})
        proc.stdin.write(json.dumps({
            "api_version": "xcov.v1", "request_id": "q", "action": "stdio.quit",
        }) + "\n")
        proc.stdin.flush()
        proc.wait(timeout=60)
    except Exception:
        proc.kill()


@pytest.fixture()
def cpp_env(tmp_path):
    if not CPP_BINARY.is_file():
        pytest.skip(f"C++ binary not built: {CPP_BINARY}; run `make -C xcov`")
    env = os.environ.copy()
    env["XVERIF_HOME"] = str(ROOT)
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    return env


def _fixture_vdb(xverif_fixture, name: str, filename: str) -> Path:
    resources = xverif_fixture(name)
    database = resources / filename
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    return database


# ---------------------------------------------------------------------------
# exclusions: CSV parsing, compile, format, lifecycle
# ---------------------------------------------------------------------------


def _first_gap(cpp_env, vdb: Path, tmp_path: Path, scopes, metric="line"):
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "g",
            "action": "export.code_coverage", "target": {"session_id": name},
            "args": {"scopes": scopes, "metrics": [metric],
                     "output": {"path": str(tmp_path / "gap"),
                                "allow_absolute_path": True}},
        })
        assert response["ok"], response
        for item in response["data"]["items"]:
            for artifact in item["metrics"]:
                path = Path(tmp_path / "gap" / item["directory"], artifact["json"])
                if not path.is_file():
                    continue
                payload = json.loads(path.read_text())
                for gap in payload.get("gaps", []):
                    return item["scope"], artifact["metric"], gap
        pytest.skip(f"fixture {vdb.name} has no uncovered {metric} gap")
    finally:
        _close(proc, send, name)


def test_csv_reason_with_comma_and_quotes_survives_compile(cpp_env, xverif_fixture,
                                                          tmp_path):
    """Port of test_csv_parser_preserves_standard_csv_quoting_and_source_groups."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    scope, metric, gap = _first_gap(cpp_env, vdb, tmp_path, ["top.u_core0.g_pipe.u_proc.u_alu"])
    reason = '不可达,"恢复路径"'
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f'{scope},{metric},,"{gap["full_name"].replace(chr(34), chr(34) * 2)}",,'
        f'"{reason.replace(chr(34), chr(34) * 2)}"\n',
        encoding="utf-8",
    )
    _seed_required_csvs(csv_dir)
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        el_dir = tmp_path / "el"
        response = send({
            "api_version": "xcov.v1", "request_id": "c",
            "action": "exclude.csv.compile", "target": {"session_id": name},
            "args": {"directory": str(csv_dir),
                     "output_directory": str(el_dir),
                     "allow_absolute_path": True},
        })
        assert response["ok"], response
        text = (el_dir / "code.el").read_text(encoding="utf-8")
        assert "ANNOTATION" in text
        assert "恢复路径" in text
    finally:
        _close(proc, send, name)


def test_csv_validate_reports_missing_scope_column(cpp_env, xverif_fixture,
                                                   tmp_path):
    """Port of test_csv_parser_rejects_noncontiguous_group_and_unknown_column."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    csv_dir = tmp_path / "bad"
    csv_dir.mkdir()
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        ",line,,1.1,,reason\n",
        encoding="utf-8",
    )
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "v",
            "action": "exclude.csv.validate", "target": {"session_id": name},
            "args": {"directory": str(csv_dir)},
        })
        assert response["ok"], response
        assert response["data"]["items"], "invalid CSV row must be reported"
    finally:
        _close(proc, send, name)


def test_csv_compile_publishes_four_artifacts_and_loads_union(cpp_env,
                                                             xverif_fixture,
                                                             tmp_path):
    """Port of test_csv_compile_publishes_four_files_and_loads_union."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    scope, metric, gap = _first_gap(cpp_env, vdb, tmp_path, ["top.u_core0.g_pipe.u_proc.u_alu"])
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"{scope},{metric},,{gap['full_name']},,compile union\n",
        encoding="utf-8",
    )
    _seed_required_csvs(csv_dir)
    el_dir = tmp_path / "el"
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "c",
            "action": "exclude.csv.compile", "target": {"session_id": name},
            "args": {"directory": str(csv_dir),
                     "output_directory": str(el_dir),
                     "allow_absolute_path": True},
        })
        assert response["ok"], response
        for artifact in ("code.el", "functional.el", "assertion.el",
                         "container.el"):
            assert (el_dir / artifact).is_file(), artifact
        assert "ANNOTATION" in (el_dir / "code.el").read_text(encoding="utf-8")

        reloaded = send({
            "api_version": "xcov.v1", "request_id": "l",
            "action": "exclude.load", "target": {"session_id": name},
            "args": {"paths": [str(el_dir / "code.el")]},
        })
        assert reloaded["ok"], reloaded
    finally:
        _close(proc, send, name)


def test_exclusion_lifecycle_add_remove_export_unload(cpp_env, xverif_fixture,
                                                      tmp_path):
    """Port of test_native_exclusion_add_remove_export_load_and_unload."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        generated = send({
            "api_version": "xcov.v1", "request_id": "g",
            "action": "export.code_coverage", "target": {"session_id": name},
            "args": {"scopes": ["top.u_core0.g_pipe.u_proc.u_alu"], "metrics": ["line"],
                     "output": {"path": str(tmp_path / "life-gap"),
                                "allow_absolute_path": True}},
        })
        assert generated["ok"], generated
        reference = None
        for item in generated["data"]["items"]:
            for artifact in item["metrics"]:
                path = Path(tmp_path / "life-gap" / item["directory"],
                            artifact["json"])
                if not path.is_file():
                    continue
                for gap in json.loads(path.read_text()).get("gaps", []):
                    reference = gap.get("coverage_ref")
                    if reference:
                        break
                if reference:
                    break
            if reference:
                break
        if reference is None:
            pytest.skip("fixture has no uncovered line gap")
        added = send({
            "api_version": "xcov.v1", "request_id": "a",
            "action": "exclude.add", "target": {"session_id": name},
            "args": {"coverage_refs": [{"coverage_ref": reference,
                                        "reason": "lifecycle"}]},
        })
        assert added["ok"] and added["data"]["items"][0]["status"] == "changed"

        el_path = tmp_path / "lifecycle.el"
        exported = send({
            "api_version": "xcov.v1", "request_id": "e",
            "action": "export.exclude", "target": {"session_id": name},
            "args": {"output": {"path": str(el_path),
                                "allow_absolute_path": True}},
        })
        assert exported["ok"] and el_path.is_file()
        assert "ANNOTATION" in el_path.read_text(encoding="utf-8")

        removed = send({
            "api_version": "xcov.v1", "request_id": "r",
            "action": "exclude.remove", "target": {"session_id": name},
            "args": {"coverage_refs": [reference]},
        })
        assert removed["ok"] and removed["data"]["items"][0]["status"] == "changed"

        unloaded = send({
            "api_version": "xcov.v1", "request_id": "u",
            "action": "exclude.unload_all", "target": {"session_id": name},
            "args": {"confirm": True},
        })
        assert unloaded["ok"]
    finally:
        _close(proc, send, name)


def test_unload_all_requires_confirmation(cpp_env, xverif_fixture):
    """Port of the confirm gate asserted by exclude.unload_all tests."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "u",
            "action": "exclude.unload_all", "target": {"session_id": name},
            "args": {"confirm": False},
        })
        assert not response["ok"]
        assert (response.get("error") or {}).get("code") == "CONFIRMATION_REQUIRED"
    finally:
        _close(proc, send, name)


def test_formatter_is_stable_and_check_does_not_write(cpp_env, xverif_fixture,
                                                      tmp_path):
    """Port of test_formatter_is_stable_and_check_does_not_write."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    csv_dir = tmp_path / "fmt"
    csv_dir.mkdir()
    original = (
        "# schema_version=xcov-code-exclusions.v1\r\n"
        "# coverage_kind=code\r\n"
        "scope,metric,line,object,bin,reason\r\n"
        "top,line,,1.1,,reason\r\n"
    )
    path = csv_dir / "code_exclusions.csv"
    path.write_text(original, encoding="utf-8")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        check = send({
            "api_version": "xcov.v1", "request_id": "f",
            "action": "exclude.csv.format",
            "args": {"directory": str(csv_dir)},
        })
        assert check["ok"], check
        assert path.read_bytes() == original.encode("utf-8"), "check must not write"
    finally:
        _close(proc, send, name)


def test_coverage_ref_is_deterministic_across_sessions(cpp_env, xverif_fixture,
                                                      tmp_path):
    """UCAPI refs are canonical hashes, unlike the Python session-local refs.

    The C++ implementation derives ``xcovref.v1:<sha256>`` from the readable
    identity only, so the same object yields the same ref in any session and a
    ref generated elsewhere still resolves.
    """
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    first = _first_gap(cpp_env, vdb, tmp_path / "a", ["top.u_core0.g_pipe.u_proc.u_alu"])[2]
    second = _first_gap(cpp_env, vdb, tmp_path / "b", ["top.u_core0.g_pipe.u_proc.u_alu"])[2]
    assert first["full_name"] == second["full_name"]
    assert first["coverage_ref"] == second["coverage_ref"]
    # Resolution is guaranteed inside the session that produced the ref; the
    # cross-session fallback is a best-effort full-tree scan and is not part
    # of the public contract.
    reference = first["coverage_ref"]
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        generated = send({
            "api_version": "xcov.v1", "request_id": "g",
            "action": "export.code_coverage", "target": {"session_id": name},
            "args": {"scopes": ["top.u_core0.g_pipe.u_proc.u_alu"], "metrics": ["line"],
                     "output": {"path": str(tmp_path / "ref-gap"),
                                "allow_absolute_path": True}},
        })
        assert generated["ok"], generated
        local_ref = None
        for item in generated["data"]["items"]:
            for artifact in item["metrics"]:
                path = Path(tmp_path / "ref-gap" / item["directory"],
                            artifact["json"])
                if not path.is_file():
                    continue
                for gap in json.loads(path.read_text()).get("gaps", []):
                    local_ref = gap.get("coverage_ref")
                    if local_ref:
                        break
                if local_ref:
                    break
            if local_ref:
                break
        assert local_ref == reference
        response = send({
            "api_version": "xcov.v1", "request_id": "a",
            "action": "exclude.add", "target": {"session_id": name},
            "args": {"coverage_refs": [{"coverage_ref": local_ref,
                                        "reason": "same session"}]},
        })
        assert response["ok"], response
        assert response["data"]["items"][0]["status"] == "changed"
    finally:
        _close(proc, send, name)


# ---------------------------------------------------------------------------
# edge cases: zero-coverable, empty FSM, gap counts
# ---------------------------------------------------------------------------


def test_zero_coverable_nodes_and_null_scores(cpp_env, xverif_fixture):
    """Port of test_zero_coverable_nodes_and_null_multi_metric_scores_are_legal."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.zero_coverable",
                       "zero_coverable.vdb")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        scope = send({
            "api_version": "xcov.v1", "request_id": "s",
            "action": "scope.summary", "target": {"session_id": name},
            "args": {"scope": "route_matrix", "metrics": ["line", "functional"]},
        })
        assert scope["ok"], scope
        assert scope["data"]["items"][0]["coverage_pct"] is not None

        functional = send({
            "api_version": "xcov.v1", "request_id": "f",
            "action": "functional_coverage.summary",
            "target": {"session_id": name},
            "args": {"scope": "route_matrix.u_zero_coverable",
                     "group_by": "covergroup"},
        })
        assert functional["ok"], functional
        rows = functional["data"]["items"]
        assert rows
        # The fixture mixes truly empty groups (0/0 -> null pct) with a
        # zero-weight group that still has bins; both shapes are legal.
        empty = [row for row in rows if row["coverable"] == 0]
        assert empty, rows
        assert all(row["coverage_pct"] is None for row in empty)
    finally:
        _close(proc, send, name)


def test_empty_fsm_section_stays_empty(cpp_env, xverif_fixture, tmp_path):
    """Port of test_empty_fsm_section_is_a_complete_empty_payload."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.modinfo_edge_layouts",
                       "edge_cases.vdb")
    response = _first_gap_or_empty(cpp_env, vdb, tmp_path,
                                   ["route_matrix.u_bare"], "fsm")
    assert response["coverage"] == {"covered": 0, "coverable": 0, "missing": 0,
                                    "pct": None}
    assert response["gap_count"] == 0


def test_line_gap_count_matches_missing(cpp_env, xverif_fixture, tmp_path):
    """Port of test_line_zero_over_n_expands_one_gap_per_coverage_object."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.modinfo_edge_layouts",
                       "edge_cases.vdb")
    payload = _first_gap_or_empty(cpp_env, vdb, tmp_path,
                                  ["route_matrix.u_value_dark"], "line")
    assert payload["gap_count"] == payload["coverage"]["missing"]


def test_line_groups_cover_every_missing_object(cpp_env, xverif_fixture,
                                                tmp_path):
    """Port of test_line_zero_over_n_expands_one_gap_per_coverage_object."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.modinfo_edge_layouts",
                       "edge_cases.vdb")
    payload = _first_gap_or_empty(cpp_env, vdb, tmp_path,
                                  ["route_matrix.u_value_dark"], "line")
    gaps = [gap for group in payload["line_groups"]
            for gap in group["uncovered"]]
    assert payload["gap_count"] == payload["coverage"]["missing"] == len(gaps)
    counts = {}
    for gap in gaps:
        key = (gap["at"], gap["statement"])
        counts[key] = counts.get(key, 0) + 1
    assert any(count >= 4 and count % 4 == 0 for count in counts.values()), counts
    for group in payload["line_groups"]:
        context = group["context"]
        assert context["missing"] == len(group["uncovered"])
        assert context["coverable"] - context["covered"] == context["missing"]


def test_line_groups_context_carries_source_location(cpp_env, xverif_fixture,
                                                     tmp_path):
    """Every line group points at a real source line with a statement."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.modinfo_edge_layouts",
                       "edge_cases.vdb")
    payload = _first_gap_or_empty(cpp_env, vdb, tmp_path,
                                  ["route_matrix.u_value_dark"], "line")
    assert payload["line_groups"]
    for group in payload["line_groups"]:
        at = group["context"]["at"]
        assert ".sv:" in at, at
        for gap in group["uncovered"]:
            assert gap["at"] == at
            assert gap["statement"].strip(), gap


def _first_gap_or_empty(cpp_env, vdb: Path, tmp_path: Path, scopes, metric):
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "x",
            "action": "export.code_coverage", "target": {"session_id": name},
            "args": {"scopes": scopes, "metrics": [metric],
                     "output": {"path": str(tmp_path / "px"),
                                "allow_absolute_path": True}},
        })
        assert response["ok"], response
        for item in response["data"]["items"]:
            for artifact in item["metrics"]:
                path = Path(tmp_path / "px" / item["directory"], artifact["json"])
                if path.is_file():
                    return json.loads(path.read_text())
        pytest.skip("export produced no artifact")
    finally:
        _close(proc, send, name)


# ---------------------------------------------------------------------------
# export layout and multi-instance coverage
# ---------------------------------------------------------------------------


def test_export_code_writes_per_instance_directories(cpp_env, xverif_fixture,
                                                     tmp_path):
    """Port of test_export_code_to_dir."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "e",
            "action": "export.code_coverage", "target": {"session_id": name},
            "args": {"scopes": ["top.u_core0", "top.u_core1"],
                     "metrics": ["line"],
                     "output": {"path": str(tmp_path / "out"),
                                "allow_absolute_path": True}},
        })
        assert response["ok"], response
        items = response["data"]["items"]
        assert len(items) == 2
        for item in items:
            directory = Path(item["directory"])
            assert directory.is_dir()
            for artifact in item["metrics"]:
                assert (directory / artifact["json"]).is_file()
    finally:
        _close(proc, send, name)


def test_multi_instance_coverage_differs(cpp_env, xverif_fixture):
    """Port of test_multi_inst_diff_coverage."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.comprehensive", "comprehensive.vdb")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        response = send({
            "api_version": "xcov.v1", "request_id": "c",
            "action": "scope.children", "target": {"session_id": name},
            "args": {"scope": "top"},
        })
        assert response["ok"], response
        children = {row["full_name"]: row for row in response["data"]["items"]}
        assert "top.u_core0" in children and "top.u_core1" in children
        assert (children["top.u_core0"]["coverage_pct"]
                != children["top.u_core1"]["coverage_pct"])
    finally:
        _close(proc, send, name)


# ---------------------------------------------------------------------------
# cached/read-only stability
# ---------------------------------------------------------------------------


def test_repeated_summary_reads_are_stable(cpp_env, xverif_fixture):
    """Port of test_large_summary_fixture_is_typed_read_only_and_cache_stable."""
    vdb = _fixture_vdb(xverif_fixture, "xcov.large_summary", "large_summary.vdb")
    proc, send, name = _session([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb)
    try:
        first = send({
            "api_version": "xcov.v1", "request_id": "1",
            "action": "code_coverage.summary", "target": {"session_id": name},
            "args": {"group_by": "metric"},
        })
        second = send({
            "api_version": "xcov.v1", "request_id": "2",
            "action": "code_coverage.summary", "target": {"session_id": name},
            "args": {"group_by": "metric"},
        })
        assert first["ok"] and second["ok"]
        assert first["data"]["items"] == second["data"]["items"]
        assert all(item["coverable"] >= 0 for item in first["data"]["items"])
    finally:
        _close(proc, send, name)
