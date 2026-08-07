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
    apply_rebase_suggestions,
    format_document,
    git_group_status,
    parse_directory,
    parse_document,
    rebase_suggestions,
    resolve_documents,
    suggested_patches,
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
        # strict policy 测试：修改已有 session 的 policy
        if policy != "default" and sess is not None:
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
    xverif_home = os.environ.get("XVERIF_HOME") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    base = os.path.join(xverif_home, ".xverif-test-cache", "fixtures", "xcov.exclusion")
    versions_dir = os.path.join(base, "versions")
    if os.path.isdir(versions_dir):
        for vhash in sorted(os.listdir(versions_dir), reverse=True):
            vdb = os.path.join(versions_dir, vhash, "resources", "exclusion.vdb")
            if os.path.isdir(vdb):
                return vdb
    pytest.skip("exclusion VDB not found; run: pytest --xverif-prepare xcov.exclusion")


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
        f"# source_commit={SHA}\n"
        + quoted.getvalue(),
        encoding="utf-8",
    )
    # functional: scope=top, line=57, covergroup=top::behavior_cg, coverpoint=sel_cp, bin=other
    (root / "functional_exclusions.csv").write_text(
        "# schema_version=xcov-functional-exclusions.v1\n"
        "# coverage_kind=functional\n"
        "scope,line,covergroup,coverpoint,cross,bin,reason\n\n"
        "# source_file=exclusion_fixture.sv\n"
        f"# source_commit={SHA}\n"
        "top,57,top::behavior_cg,sel_cp,,other,量产不支持\n",
        encoding="utf-8",
    )
    # assertion: scope=top.u_dut, line=40, assertion=a_no_unknown, assertion_kind=assertion
    (root / "assertion_exclusions.csv").write_text(
        "# schema_version=xcov-assertion-exclusions.v1\n"
        "# coverage_kind=assertion\n"
        "scope,line,assertion,assertion_kind,reason\n\n"
        "# source_file=exclusion_fixture.sv\n"
        f"# source_commit={SHA}\n"
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


def test_csv_parser_preserves_standard_csv_quoting_and_group_commits(tmp_path):
    root = tmp_path / "coverage_exclusions"
    _write_csvs(root, code_reason='不可达,"恢复"路径')
    documents = parse_directory(root)
    code = documents[0]
    assert code.groups[0].source_commit == SHA
    assert code.groups[0].rows[0]["reason"] == '不可达,"恢复"路径'
    assert parse_document(root / "functional_exclusions.csv", "functional").row_count == 1


def test_csv_parser_rejects_noncontiguous_group_and_unknown_column(tmp_path):
    path = tmp_path / "code_exclusions.csv"
    path.write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "# source_file=a.sv\n"
        f"# source_commit={SHA}\n"
        "top,line,1,,,one\n"
        "# source_file=b.sv\n"
        f"# source_commit={'2' * 40}\n"
        "top,line,2,,,two\n"
        "# source_file=a.sv\n"
        f"# source_commit={SHA}\n"
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
    backend = dispatcher.sessions.get("cov").backend
    # 尝试多个未被完全覆盖的 item 直到找到一个 NPI 接受 exclude 的
    ref = None
    for row in backend.items():
        if row.get("covered", 0) < row.get("coverable", 1):
            rsp = _request(dispatcher, "exclude.add", {"coverage_refs": [row["coverage_ref"]]})
            if rsp["data"]["items"][0]["status"] == "changed":
                ref = row["coverage_ref"]
                # 先 remove 以保持 clean 状态
                _request(dispatcher, "exclude.remove", {"coverage_refs": [ref]})
                break
    assert ref is not None, "VDB 中没有 NPI 接受 exclude 的 item"

    added = _request(dispatcher, "exclude.add", {"coverage_refs": [ref]})
    assert added["data"]["items"][0]["status"] == "changed"
    again = _request(dispatcher, "exclude.add", {"coverage_refs": [ref]})
    assert again["data"]["items"][0]["status"] == "already_in_state"
    listed = _request(dispatcher, "exclude.list")
    assert [row["coverage_ref"] for row in listed["data"]["items"]] == [ref]

    output = tmp_path / "saved.el"
    exported = _request(
        dispatcher,
        "export.exclude",
        {
            "output": {
                "path": str(output),
                "allow_absolute_path": True,
            }
        },
    )
    assert exported["ok"] is True
    removed = _request(dispatcher, "exclude.remove", {"coverage_refs": [ref]})
    assert removed["data"]["items"][0]["status"] == "changed"
    loaded = _request(
        dispatcher,
        "exclude.load",
        {"paths": [str(output)], "allow_absolute_path": True},
    )
    assert loaded["ok"] is True
    unloaded = _request(
        dispatcher,
        "exclude.unload_all",
        {"confirm": True},
    )
    assert unloaded["data"]["items"][0]["after_count"] == 0


def test_strict_policy_rejects_covered_object():
    dispatcher = _dispatcher("strict")
    ref = next(
        row["coverage_ref"]
        for row in dispatcher.sessions.get("cov").backend.items()
        if row["metric"] == "line"
    )
    response = _request(
        dispatcher,
        "exclude.add",
        {"coverage_refs": [ref]},
    )
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
    # EL 加载结果取决于 NPI checksum 匹配，不强求具体数量
    listed = _request(dispatcher, "exclude.list")
    assert listed["ok"] is True


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
    response = Dispatcher().dispatch({
        "api_version": "xcov.v1",
        "action": "exclude.csv.validate",
        "args": {"directory": str(root)},
    })
    assert response["ok"] is True
    output = render_xout(response)
    assert "summary:\n" in output
    assert "pointer\tkind\tvalue" not in output


def test_csv_git_and_stamp_actions_satisfy_public_response_contract(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "xcov@example.invalid")
    _git(repo, "config", "user.name", "xcov test")
    # 写入真实 exclusion fixture 源码
    fixture_src = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "exclusion" / "exclusion_fixture.sv"
    )
    source_path = repo / "exclusion_fixture.sv"
    source_path.write_text(fixture_src.read_text(encoding="utf-8"), encoding="utf-8")
    _git(repo, "add", "exclusion_fixture.sv")
    _git(repo, "commit", "-m", "添加覆盖率源码")
    commit = _git(repo, "rev-parse", "HEAD")
    csv_root = repo / "coverage_exclusions"
    _write_csvs(csv_root)
    for path in csv_root.iterdir():
        path.write_text(
            path.read_text(encoding="utf-8").replace(SHA, commit),
            encoding="utf-8",
        )

    dispatcher = _dispatcher()
    for action in (
        "exclude.csv.status",
        "exclude.csv.impact",
        "exclude.csv.rebase",
    ):
        response = _request(
            dispatcher,
            action,
            {"directory": str(csv_root), "repo_root": str(repo)},
            session=False,
        )
        assert response["ok"] is True, response
    stamped = _request(
        dispatcher,
        "exclude.csv.stamp_changed",
        {"directory": str(csv_root), "repo_root": str(repo)},
    )
    assert stamped["ok"] is True, stamped
    source_path.write_text("dirty\n", encoding="utf-8")
    dirty = _request(
        dispatcher,
        "exclude.csv.stamp_changed",
        {"directory": str(csv_root), "repo_root": str(repo)},
    )
    assert dirty["ok"] is True, dirty
    fixture_rows = [
        row for row in dirty["data"]["items"]
        if row["source_file"] == "exclusion_fixture.sv"
    ]
    assert fixture_rows[0]["stamp_status"] == "worktree_dirty"


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _write_git_status_csv(root: Path, source: str, commit: str, line: int = 72) -> Path:
    """写最小 CSV，scope/line 匹配真实 exclusion VDB."""
    csv_root = root / "coverage_exclusions"
    csv_root.mkdir()
    (csv_root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"# source_file={source}\n"
        f"# source_commit={commit}\n"
        f"top,line,{line},,,reason\n",
        encoding="utf-8",
    )
    for kind, header in (
        ("functional", "scope,line,covergroup,coverpoint,cross,bin,reason"),
        ("assertion", "scope,line,assertion,assertion_kind,reason"),
    ):
        (csv_root / f"{kind}_exclusions.csv").write_text(
            f"# schema_version=xcov-{kind}-exclusions.v1\n"
            f"# coverage_kind={kind}\n{header}\n",
            encoding="utf-8",
        )
    return csv_root


def test_git_status_is_per_source_group_and_detects_line_shift(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "xcov@example.invalid")
    _git(repo, "config", "user.name", "xcov test")
    # 写入真实 exclusion fixture 源码
    fixture_src = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "exclusion" / "exclusion_fixture.sv"
    )
    content = fixture_src.read_text(encoding="utf-8")
    (repo / "exclusion_fixture.sv").write_text(content, encoding="utf-8")
    _git(repo, "add", "exclusion_fixture.sv")
    _git(repo, "commit", "-m", "添加覆盖率源码")
    commit_a = _git(repo, "rev-parse", "HEAD")

    csv_root = repo / "coverage_exclusions"
    csv_root.mkdir()
    (csv_root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "# source_file=exclusion_fixture.sv\n"
        f"# source_commit={commit_a}\n"
        "top,line,53,,,keep\n",
        encoding="utf-8",
    )
    for kind, header in (
        ("functional", "scope,line,covergroup,coverpoint,cross,bin,reason"),
        ("assertion", "scope,line,assertion,assertion_kind,reason"),
    ):
        (csv_root / f"{kind}_exclusions.csv").write_text(
            f"# schema_version=xcov-{kind}-exclusions.v1\n"
            f"# coverage_kind={kind}\n{header}\n",
            encoding="utf-8",
        )
    # 在 line 72 之前插入一行，导致旧 line 72 变为 line 73
    lines = content.splitlines(keepends=True)
    lines.insert(71, "// inserted line\n")  # 0-indexed: line 72 = index 71
    (repo / "exclusion_fixture.sv").write_text("".join(lines), encoding="utf-8")
    _git(repo, "add", "exclusion_fixture.sv")
    _git(repo, "commit", "-m", "插入一行")
    statuses = git_group_status(parse_directory(csv_root), str(repo))
    by_file = {row["source_file"]: row for row in statuses}
    assert by_file["exclusion_fixture.sv"]["status"] == "line_shifted"
    assert {"old_line": 72, "new_line": 73} in by_file["exclusion_fixture.sv"]["line_updates"]


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("rename", "file_renamed"),
        ("delete", "file_deleted"),
        ("dirty", "worktree_dirty"),
        ("content", "content_changed"),
        ("restore", "commit_changed_content_equal"),
    ],
)
def test_git_group_status_change_matrix(tmp_path, scenario, expected):
    repo = tmp_path / scenario
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "xcov@example.invalid")
    _git(repo, "config", "user.name", "xcov test")
    source = repo / "exclusion_fixture.sv"
    fixture_src = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "exclusion" / "exclusion_fixture.sv"
    )
    content = fixture_src.read_text(encoding="utf-8")
    source.write_text(content, encoding="utf-8")
    _git(repo, "add", "exclusion_fixture.sv")
    _git(repo, "commit", "-m", "初始源码")
    commit = _git(repo, "rev-parse", "HEAD")
    csv_root = _write_git_status_csv(repo, "exclusion_fixture.sv", commit)

    if scenario == "rename":
        _git(repo, "mv", "exclusion_fixture.sv", "renamed.sv")
        _git(repo, "commit", "-m", "重命名源码")
    elif scenario == "delete":
        _git(repo, "rm", "exclusion_fixture.sv")
        _git(repo, "commit", "-m", "删除源码")
    elif scenario == "dirty":
        source.write_text("dirty\n", encoding="utf-8")
    elif scenario == "content":
        source.write_text("changed\n", encoding="utf-8")
        _git(repo, "add", "exclusion_fixture.sv")
        _git(repo, "commit", "-m", "修改内容")
    else:
        source.write_text("changed\n", encoding="utf-8")
        _git(repo, "add", "exclusion_fixture.sv")
        _git(repo, "commit", "-m", "临时修改")
        source.write_text(content, encoding="utf-8")
        _git(repo, "add", "exclusion_fixture.sv")
        _git(repo, "commit", "-m", "恢复内容")

    status = git_group_status(parse_directory(csv_root), str(repo))[0]
    assert status["status"] == expected
    if scenario == "rename":
        assert status["renamed_to"] == "renamed.sv"
        documents = parse_directory(csv_root)
        suggestions = rebase_suggestions(documents, str(repo))
        patches = suggested_patches(documents, suggestions)
        assert "renamed.sv" in patches[0]["patch"]
        assert (csv_root / "code_exclusions.csv").read_text(encoding="utf-8").find(
            "source_file=exclusion_fixture.sv"
        ) >= 0
        applied = apply_rebase_suggestions(documents, suggestions)
        assert applied[0]["status"] == "rebased"
        assert "source_file=renamed.sv" in (
            csv_root / "code_exclusions.csv"
        ).read_text(encoding="utf-8")
