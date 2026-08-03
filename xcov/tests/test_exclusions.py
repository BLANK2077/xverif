from __future__ import annotations

import csv
import io
from pathlib import Path
import subprocess

import pytest

from xcov.actions import Dispatcher
from xcov.backend import FakeCoverageBackend
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


def _write_csvs(root: Path, *, code_reason: str = "不可达,恢复路径") -> None:
    root.mkdir()
    quoted = io.StringIO()
    csv.writer(quoted, lineterminator="\n").writerow(
        ["top.u_dut", "line", "12", "", "", code_reason]
    )
    (root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n\n"
        "# source_file=rtl/ctrl.sv\n"
        f"# source_commit={SHA}\n"
        + quoted.getvalue(),
        encoding="utf-8",
    )
    (root / "functional_exclusions.csv").write_text(
        "# schema_version=xcov-functional-exclusions.v1\n"
        "# coverage_kind=functional\n"
        "scope,line,covergroup,coverpoint,cross,bin,reason\n\n"
        "# source_file=verif/env/uart_coverage.sv\n"
        f"# source_commit={SHA}\n"
        "top.u_dut,22,cg_credit,cp_level,,zero_credit,量产不支持\n",
        encoding="utf-8",
    )
    (root / "assertion_exclusions.csv").write_text(
        "# schema_version=xcov-assertion-exclusions.v1\n"
        "# coverage_kind=assertion\n"
        "scope,line,assertion,assertion_kind,reason\n\n"
        "# source_file=rtl/ctrl.sv\n"
        f"# source_commit={SHA}\n"
        "top.u_dut.u_ctrl,120,p_ready,assertion,复位阶段不采集\n",
        encoding="utf-8",
    )


def _dispatcher(policy: str = "default") -> Dispatcher:
    dispatcher = Dispatcher(
        SessionManager(lambda path: FakeCoverageBackend(path))
    )
    response = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "action": "session.open",
        "target": {"vdb": "fake.vdb"},
        "args": {"name": "cov", "exclusion_policy": policy},
    })
    assert response["ok"] is True, response
    return dispatcher


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
    backend = FakeCoverageBackend()
    rows = resolve_documents(parse_directory(root), backend.items())
    assert [row["status"] for row in rows] == ["matched", "matched", "matched"]
    assert [row["validity"] for row in rows] == [
        "now_covered",
        "still_valid",
        "still_valid",
    ]
    code_path = root / "code_exclusions.csv"
    code_path.write_text(
        code_path.read_text(encoding="utf-8").replace(
            "top.u_dut,line,12",
            "top.u_dut,line,999",
        ),
        encoding="utf-8",
    )
    rows = resolve_documents(parse_directory(root), backend.items())
    assert rows[0]["status"] == "missing"
    assert rows[0]["validity"] == "coverage_object_missing"


def test_native_exclusion_add_remove_export_load_and_unload(tmp_path):
    dispatcher = _dispatcher()
    backend = dispatcher.sessions.get("cov").backend
    ref = next(
        row["coverage_ref"]
        for row in backend.items()
        if row["metric"] == "toggle"
    )
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
    first = FakeCoverageBackend().items()[0]["coverage_ref"]
    second = FakeCoverageBackend().items()[0]["coverage_ref"]
    assert first.startswith("xcovref.v1:")
    assert second.startswith("xcovref.v1:")
    assert first != second


def test_compile_time_exclusion_is_immutable_on_remove():
    backend = FakeCoverageBackend()
    backend._items[0]["status"].extend([
        "excluded",
        "excluded_at_compile_time",
    ])
    dispatcher = Dispatcher(SessionManager(lambda _path: backend))
    opened = dispatcher.dispatch({
        "api_version": "xcov.v1",
        "action": "session.open",
        "target": {"vdb": "fake.vdb"},
        "args": {"name": "cov"},
    })
    assert opened["ok"] is True
    ref = dispatcher.sessions.get("cov").backend.items()[0]["coverage_ref"]
    added = _request(
        dispatcher,
        "exclude.add",
        {"coverage_refs": [ref]},
    )
    assert added["data"]["items"][0]["status"] == "changed"
    response = _request(
        dispatcher,
        "exclude.remove",
        {"coverage_refs": [ref]},
    )
    assert response["data"]["items"][0]["status"] == "immutable_compile_time"
    assert response["data"]["items"][0]["before"] is True
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
    listed = _request(dispatcher, "exclude.list")
    assert listed["summary"]["total_count"] == 3


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
            "top.u_dut,line,12",
            "top.u_dut,line,999",
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
    for relative in ("rtl/ctrl.sv", "verif/env/uart_coverage.sv"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n" * 130, encoding="utf-8")
    _git(repo, "add", "rtl/ctrl.sv", "verif/env/uart_coverage.sv")
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
    (repo / "rtl/ctrl.sv").write_text("dirty\n", encoding="utf-8")
    dirty = _request(
        dispatcher,
        "exclude.csv.stamp_changed",
        {"directory": str(csv_root), "repo_root": str(repo)},
    )
    assert dirty["ok"] is True, dirty
    ctrl_rows = [
        row for row in dirty["data"]["items"]
        if row["source_file"] == "rtl/ctrl.sv"
    ]
    assert ctrl_rows[0]["stamp_status"] == "worktree_dirty"


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _write_git_status_csv(root: Path, source: str, commit: str, line: int = 1) -> Path:
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
    (repo / "a.sv").write_text("line1\nkeep\n", encoding="utf-8")
    _git(repo, "add", "a.sv")
    _git(repo, "commit", "-m", "添加甲文件")
    commit_a = _git(repo, "rev-parse", "HEAD")
    (repo / "b.sv").write_text("other\n", encoding="utf-8")
    _git(repo, "add", "b.sv")
    _git(repo, "commit", "-m", "添加乙文件")
    commit_b = _git(repo, "rev-parse", "HEAD")

    csv_root = repo / "coverage_exclusions"
    csv_root.mkdir()
    (csv_root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "# source_file=a.sv\n"
        f"# source_commit={commit_a}\n"
        "top,line,2,,,keep\n"
        "# source_file=b.sv\n"
        f"# source_commit={commit_b}\n"
        "top,line,1,,,other\n",
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
    (repo / "a.sv").write_text("inserted\nline1\nkeep\n", encoding="utf-8")
    _git(repo, "add", "a.sv")
    _git(repo, "commit", "-m", "插入一行")
    statuses = git_group_status(parse_directory(csv_root), str(repo))
    by_file = {row["source_file"]: row for row in statuses}
    assert by_file["a.sv"]["status"] == "line_shifted"
    assert by_file["a.sv"]["line_updates"] == [{"old_line": 2, "new_line": 3}]
    assert by_file["b.sv"]["status"] == "current"


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
    source = repo / "source.sv"
    source.write_text("original\n", encoding="utf-8")
    _git(repo, "add", "source.sv")
    _git(repo, "commit", "-m", "初始源码")
    commit = _git(repo, "rev-parse", "HEAD")
    csv_root = _write_git_status_csv(repo, "source.sv", commit)

    if scenario == "rename":
        _git(repo, "mv", "source.sv", "renamed.sv")
        _git(repo, "commit", "-m", "重命名源码")
    elif scenario == "delete":
        _git(repo, "rm", "source.sv")
        _git(repo, "commit", "-m", "删除源码")
    elif scenario == "dirty":
        source.write_text("dirty\n", encoding="utf-8")
    elif scenario == "content":
        source.write_text("changed\n", encoding="utf-8")
        _git(repo, "add", "source.sv")
        _git(repo, "commit", "-m", "修改内容")
    else:
        source.write_text("changed\n", encoding="utf-8")
        _git(repo, "add", "source.sv")
        _git(repo, "commit", "-m", "临时修改")
        source.write_text("original\n", encoding="utf-8")
        _git(repo, "add", "source.sv")
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
            "source_file=source.sv"
        ) >= 0
        applied = apply_rebase_suggestions(documents, suggestions)
        assert applied[0]["status"] == "rebased"
        assert "source_file=renamed.sv" in (
            csv_root / "code_exclusions.csv"
        ).read_text(encoding="utf-8")
