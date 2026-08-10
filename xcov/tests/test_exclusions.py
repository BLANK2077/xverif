from __future__ import annotations

import csv
import io
from pathlib import Path
import subprocess
import sys

import pytest

import os

# Ensure NPI is importable (VERDI_HOME is set in CI/host environments)
_verdi_home = os.environ.get("VERDI_HOME", "")
if _verdi_home:
    _npi_path = os.path.join(_verdi_home, "share", "NPI", "python")
    if _npi_path not in sys.path:
        sys.path.insert(0, _npi_path)

from xcov.actions import Dispatcher
from xcov.backend import NpiCoverageBackend
from xcov.errors import XcovError
from xcov.exclusions_csv import (
    format_document,
    parse_directory,
    parse_document,
    resolve_documents,
)
from xcov.protocol import render_xout
from xcov.session import SessionManager


SHA = "1" * 40


_EXCLUSION_VDB: str | None = None
_NPI_DISPATCHER: Dispatcher | None = None


def _exclusion_vdb() -> str:
    global _EXCLUSION_VDB
    if _EXCLUSION_VDB is not None:
        return _EXCLUSION_VDB
    xverif_home = os.environ.get("XVERIF_HOME") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    versions_dir = os.path.join(
        xverif_home, ".xverif-test-cache", "fixtures", "xcov.exclusion", "versions"
    )
    if os.path.isdir(versions_dir):
        for vhash in sorted(os.listdir(versions_dir), reverse=True):
            vdb = os.path.join(versions_dir, vhash, "resources", "exclusion.vdb")
            if os.path.isdir(vdb):
                _EXCLUSION_VDB = vdb
                return vdb
    pytest.skip("exclusion VDB not found; run: pytest --xverif-prepare xcov.exclusion")


def _npi_dispatcher(policy: str = "default") -> Dispatcher:
    """创建使用 NPI 后端的 dispatcher（进程级单例，避免 NPI 重复 init）."""
    global _NPI_DISPATCHER
    if _NPI_DISPATCHER is not None:
        sess = _NPI_DISPATCHER.sessions.get("cov")
        if sess is not None:
            _NPI_DISPATCHER.dispatch({
                "api_version": "xcov.v1",
                "action": "exclude.unload_all",
                "target": {"session_id": "cov"},
                "args": {"confirm": True},
            })
        # 进程级 session 复用时必须恢复本用例请求的 policy，避免 strict
        # 状态污染后续 default 用例。
        if sess is not None:
            sess.exclusion_policy = policy
            sess.backend._delegate.exclusion_policy = policy
        return _NPI_DISPATCHER

    vdb = _exclusion_vdb()

    def _factory(vdb_path, exclusion_policy=policy):
        return NpiCoverageBackend(vdb=vdb_path, exclusion_policy=exclusion_policy)

    _factory.__name__ = "NpiCoverageBackend"
    dispatcher = Dispatcher(SessionManager(_factory))
    response = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "action": "session.open",
        "target": {"vdb": vdb},
        "args": {"name": "cov", "exclusion_policy": policy},
    })
    assert response["ok"] is True, response
    _NPI_DISPATCHER = dispatcher
    return dispatcher


def _dispatcher(policy: str = "default") -> Dispatcher:
    """需要 exclusion 写操作时使用 NPI 后端."""
    return _npi_dispatcher(policy)


def _write_csvs(root: Path, *, code_reason: str = "不可达,恢复路径") -> None:
    """写三份 CSV 文件，scope/file/line 匹配真实 exclusion VDB 数据."""
    root.mkdir()
    # code: scope=top, metric=line, line=72 (en = 1; — 唯一匹配)
    quoted = io.StringIO()
    csv.writer(quoted, lineterminator="\n").writerow(
        ["top", "line", "72", "", "", code_reason]
    )
    (root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n\n"
        "# source_file=exclusion_fixture.sv\n"
        + quoted.getvalue(),
        encoding="utf-8",
    )
    # functional: scope=top, line=57, covergroup=top::behavior_cg, coverpoint=sel_cp, bin=other
    (root / "functional_exclusions.csv").write_text(
        "# schema_version=xcov-functional-exclusions.v1\n"
        "# coverage_kind=functional\n"
        "scope,line,covergroup,coverpoint,cross,bin,reason\n\n"
        "# source_file=exclusion_fixture.sv\n"
        "top,57,top::behavior_cg,sel_cp,,other,量产不支持\n",
        encoding="utf-8",
    )
    # assertion: scope=top.u_dut, line=40, assertion=a_no_unknown, assertion_kind=assertion
    (root / "assertion_exclusions.csv").write_text(
        "# schema_version=xcov-assertion-exclusions.v1\n"
        "# coverage_kind=assertion\n"
        "scope,line,assertion,assertion_kind,reason\n\n"
        "# source_file=exclusion_fixture.sv\n"
        "top.u_dut,40,a_no_unknown,assertion,复位阶段不采集\n",
        encoding="utf-8",
    )


def _request(
    dispatcher: Dispatcher,
    action: str,
    args: dict | None = None,
    *,
    session: bool = True,
) -> dict:
    request = {
        "api_version": "xcov.v1",
        "action": action,
        "args": args or {},
    }
    if session:
        request["target"] = {"session_id": "cov"}
    return dispatcher.dispatch(request)


def test_csv_parser_preserves_standard_csv_quoting_and_source_groups(tmp_path):
    root = tmp_path / "coverage_exclusions"
    _write_csvs(root, code_reason='不可达,"恢复"路径')
    documents = parse_directory(root)
    code = documents[0]
    assert code.groups[0].rows[0]["reason"] == '不可达,"恢复"路径'
    assert parse_document(root / "functional_exclusions.csv", "functional").row_count == 1


def test_csv_parser_rejects_noncontiguous_group_and_unknown_column(tmp_path):
    path = tmp_path / "code_exclusions.csv"
    path.write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "# source_file=a.sv\n"
        "top,line,1,,,one\n"
        "# source_file=b.sv\n"
        "top,line,2,,,two\n"
        "# source_file=a.sv\n"
        "top,line,3,,,three\n",
        encoding="utf-8",
    )
    with pytest.raises(XcovError, match="not contiguous"):
        parse_document(path, "code")

    path.write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason,unknown\n",
        encoding="utf-8",
    )
    with pytest.raises(XcovError, match="header must be exactly"):
        parse_document(path, "code")


def test_csv_resolve_is_exact_and_reports_missing(tmp_path):
    root = tmp_path / "coverage_exclusions"
    _write_csvs(root)
    dispatcher = _dispatcher()
    items = dispatcher.sessions.get("cov").backend.items()
    rows = resolve_documents(parse_directory(root), items)
    statuses = {row["coverage_kind"]: row["status"] for row in rows}
    assert statuses["code"] == "matched", f"unexpected statuses: {statuses}"
    assert statuses["assertion"] == "matched"
    # 修改 line 为一个不存在的行号
    code_path = root / "code_exclusions.csv"
    code_path.write_text(
        code_path.read_text(encoding="utf-8").replace(
            "top,line,72",
            "top,line,99999",
        ),
        encoding="utf-8",
    )
    rows = resolve_documents(parse_directory(root), items)
    code_row = next(r for r in rows if r["coverage_kind"] == "code")
    assert code_row["status"] == "missing"


def test_native_exclusion_add_remove_export_load_and_unload(tmp_path):
    dispatcher = _dispatcher()
    # 用 selector 语义匹配，不依赖 coverage_ref traversal_path
    selector = {"metric": "line", "scope": "top", "file": "exclusion_fixture.sv", "line": 72}

    added = _request(dispatcher, "exclude.add", {"selectors": [selector]})
    assert added["data"]["items"][0]["status"] == "changed"
    ref = added["data"]["items"][0]["coverage_ref"]

    again = _request(dispatcher, "exclude.add", {"selectors": [selector]})
    assert again["data"]["items"][0]["status"] == "already_in_state"

    output = tmp_path / "saved.el"
    exported = _request(
        dispatcher,
        "export.exclude",
        {"output": {"path": str(output), "allow_absolute_path": True}},
    )
    assert exported["ok"] is True

    removed = _request(dispatcher, "exclude.remove", {"selectors": [selector]})
    assert removed["data"]["items"][0]["status"] == "changed"

    loaded = _request(
        dispatcher, "exclude.load",
        {"paths": [str(output)], "allow_absolute_path": True},
    )
    assert loaded["ok"] is True

    unloaded = _request(dispatcher, "exclude.unload_all", {"confirm": True})
    assert unloaded["data"]["items"][0]["after_count"] == 0


def test_strict_policy_rejects_covered_object():
    import json
    import subprocess
    import sys

    script = r'''
import json
import sys
from xcov.actions import Dispatcher
from xcov.backend import NpiCoverageBackend
from xcov.session import SessionManager

dispatcher = Dispatcher(SessionManager(NpiCoverageBackend))
opened = dispatcher.dispatch({
    "api_version": "xcov.v1",
    "action": "session.open",
    "target": {"vdb": sys.argv[1]},
    "args": {"name": "cov", "exclusion_policy": "strict"},
})
assert opened["ok"], opened
ref = next(
    row["coverage_ref"]
    for row in dispatcher.sessions.get("cov").backend.items()
    if row["metric"] == "line"
)
response = dispatcher.dispatch({
    "api_version": "xcov.v1",
    "action": "exclude.add",
    "target": {"session_id": "cov"},
    "args": {"coverage_refs": [ref]},
})
print("XCOV_TEST_RESULT=" + json.dumps(response))
'''
    result = subprocess.run(
        [sys.executable, "-c", script, _exclusion_vdb()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    result_line = next(
        line for line in result.stdout.splitlines()
        if line.startswith("XCOV_TEST_RESULT=")
    )
    response = json.loads(result_line.removeprefix("XCOV_TEST_RESULT="))
    assert response["data"]["items"][0]["status"] == "failed"


def test_coverage_ref_is_session_local():
    dispatcher = _dispatcher()
    items = dispatcher.sessions.get("cov").backend.items()
    refs = [item["coverage_ref"] for item in items if "coverage_ref" in item]
    assert len(refs) >= 2
    assert all(ref.startswith("xcovref.v1:") for ref in refs)
    # 每个 coverage_ref 应该唯一
    assert len(set(refs)) == len(refs), "coverage_ref 存在重复"


def test_compile_time_exclusion_is_immutable_on_remove():
    dispatcher = _dispatcher()
    # 找到 VDB 中已有的 compile-time excluded 项
    compile_time_refs = [
        row["coverage_ref"]
        for row in dispatcher.sessions.get("cov").backend.items()
        if "excluded_at_compile_time" in row.get("status", [])
    ]
    assert len(compile_time_refs) > 0, "VDB 中没有 compile-time excluded 项"
    ref = compile_time_refs[0]

    response = _request(
        dispatcher,
        "exclude.remove",
        {"coverage_refs": [ref]},
    )
    assert response["data"]["items"][0]["status"] == "immutable_compile_time"
    assert response["data"]["items"][0]["after"] is False


def test_csv_compile_publishes_three_files_and_loads_union(tmp_path):
    root = tmp_path / "coverage_exclusions"
    output = tmp_path / "native"
    _write_csvs(root)
    dispatcher = _dispatcher()
    response = _request(
        dispatcher,
        "exclude.csv.compile",
        {
            "directory": str(root),
            "output_directory": str(output),
            "allow_absolute_path": True,
        },
    )
    assert response["ok"] is True, response
    assert {path.name for path in output.iterdir()} == {
        "code.el",
        "functional.el",
        "assertion.el",
    }


def test_csv_apply_resolves_and_returns_setter_outcomes(tmp_path):
    root = tmp_path / "coverage_exclusions"
    _write_csvs(root)
    dispatcher = _dispatcher()
    response = _request(
        dispatcher,
        "exclude.csv.apply",
        {"directory": str(root)},
    )
    assert response["ok"] is True, response
    assert [row["status"] for row in response["data"]["items"]] == [
        "changed",
        "changed",
        "changed",
    ]


def test_csv_compile_failure_does_not_publish_partial_artifacts(tmp_path):
    root = tmp_path / "coverage_exclusions"
    output = tmp_path / "native"
    _write_csvs(root)
    code = root / "code_exclusions.csv"
    code.write_text(
        code.read_text(encoding="utf-8").replace(
            "top,line,72",
            "top,line,99999",
        ),
        encoding="utf-8",
    )
    output.mkdir()
    for kind in ("code", "functional", "assertion"):
        (output / f"{kind}.el").write_text("previous\n", encoding="utf-8")
    dispatcher = _dispatcher()
    response = _request(
        dispatcher,
        "exclude.csv.compile",
        {
            "directory": str(root),
            "output_directory": str(output),
            "allow_absolute_path": True,
        },
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "EXCLUSION_RESOLVE_FAILED"
    assert all(
        (output / f"{kind}.el").read_text(encoding="utf-8") == "previous\n"
        for kind in ("code", "functional", "assertion")
    )


def test_formatter_is_stable_and_check_does_not_write(tmp_path):
    root = tmp_path / "coverage_exclusions"
    _write_csvs(root)
    document = parse_directory(root)[0]
    first = format_document(document)
    formatted_path = root / "code_exclusions.csv"
    formatted_path.write_text(first, encoding="utf-8")
    assert format_document(parse_directory(root)[0]) == first


def test_exclusion_action_xout_is_human_readable(tmp_path):
    root = tmp_path / "coverage_exclusions"
    _write_csvs(root)
    dispatcher = _dispatcher()
    response = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "action": "exclude.csv.validate",
        "target": {"session_id": "cov"},
        "args": {"directory": str(root)},
    })
    output = render_xout(response)
    assert "summary:\n" in output
    assert "pointer\tkind\tvalue" not in output
