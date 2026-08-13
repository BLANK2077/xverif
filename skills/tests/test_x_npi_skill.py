from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from skill_test_utils import assert_markdown_links


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "x-npi"
sys.path.insert(0, str(SKILL / "scripts"))

from x_npi.cli import require_output, sampling_contract  # noqa: E402
from x_npi.container import plan_container_records, write_csv_set  # noqa: E402
from x_npi.coverage import (  # noqa: E402
    CoverageExclusionError,
    compile_csv_to_el,
    load_exclusion_files,
    open_covdb,
    save_exclusion_file,
    set_report_time_excluded,
    unload_exclusions,
)
from x_npi.exclusion_csv import (  # noqa: E402
    ExclusionCsvError,
    format_directory,
    parse_directory,
)
from x_npi.jsonio import split_limited  # noqa: E402
from x_npi.protocol import (  # noqa: E402
    ProtocolAnalysisError,
    apb_summary,
    axi_summary,
    stream_summary,
)
from x_npi.wave import active, known  # noqa: E402
from x_npi.urg import UrgCoverageError, export_summary, parse_summary  # noqa: E402


def test_x_npi_links_and_examples_exist() -> None:
    assert_markdown_links(SKILL)
    examples = {path.name for path in (SKILL / "scripts/examples").glob("*.py")}
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert examples
    assert all(name in text for name in examples)
    assert "$VERDI_HOME/share/NPI/python/pynpi/" in text
    assert "TimeBasedHandle" in text
    assert '"rst_n", "valid"' in (SKILL / "scripts/examples/stream_summary.py").read_text(encoding="utf-8")


def test_trace_driver_error_has_structured_context() -> None:
    source = (SKILL / "scripts/examples/trace_driver_summary.py").read_text(encoding="utf-8")
    for field in ('stage="runtime"', "dbdir=args.dbdir", "signal=args.signal", "mode=args.mode"):
        assert field in source


def test_sampling_contract_is_canonical_and_output_is_required() -> None:
    assert sampling_contract({}) == ("negedge", None)
    assert sampling_contract({"edge": "posedge", "sample_point": "before"}) == ("posedge", "before")
    with pytest.raises(ValueError, match="legacy"):
        sampling_contract({"clock_edge": "negedge"})
    with pytest.raises(ValueError, match="requires sample_point"):
        sampling_contract({"edge": "posedge"})
    with pytest.raises(ValueError, match="--output"):
        require_output("transactions", None)


def test_json_stdout_quarantine_rejects_delayed_native_pollution() -> None:
    source = """
import json, os
from x_npi.jsonio import print_json
from x_npi.runtime import json_stdout_quarantine
with json_stdout_quarantine() as out:
    print_json({'ok': True}, out)
    os.write(1, b'native banner\\n')
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SKILL / "scripts")
    proc = subprocess.run([sys.executable, "-c", source], text=True, capture_output=True, env=env, check=False)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"ok": True}
    assert "native banner" in proc.stderr


def test_apb_summary_tracks_setup_access_wait_and_error() -> None:
    cfg = {key: key for key in (
        "psel", "penable", "pready", "pslverr", "pwrite", "paddr", "pwdata", "prdata",
    )}
    rows = [
        {"time": 1, "values": {"psel": "1", "penable": "0", "pready": "0", "pslverr": "0",
                                "pwrite": "1", "paddr": "10", "pwdata": "aa", "prdata": "00"}},
        {"time": 2, "values": {"psel": "1", "penable": "1", "pready": "0", "pslverr": "0",
                                "pwrite": "1", "paddr": "10", "pwdata": "aa", "prdata": "00"}},
        {"time": 3, "values": {"psel": "1", "penable": "1", "pready": "1", "pslverr": "1",
                                "pwrite": "1", "paddr": "10", "pwdata": "aa", "prdata": "00"}},
        {"time": 4, "values": {"psel": "0", "penable": "0", "pready": "1", "pslverr": "0",
                                "pwrite": "0", "paddr": "00", "pwdata": "00", "prdata": "00"}},
    ]
    result = apb_summary(rows, cfg, detail="full")
    assert result["summary"]["total"] == 1
    assert result["summary"]["writes"] == 1
    assert result["summary"]["errors"] == 1
    txn = result["data"]["transactions"][0]
    assert (txn["setup_begin_time"], txn["access_begin_time"], txn["completion_time"]) == (1, 2, 3)
    assert txn["wait_cycles"] == 1


def test_apb_requires_pready_and_pslverr() -> None:
    with pytest.raises(ValueError, match="pslverr"):
        apb_summary([], {"psel": "s", "penable": "e", "pready": "r", "pwrite": "w",
                         "paddr": "a", "pwdata": "wd", "prdata": "rd"})


AXI_CFG = {key: key for key in (
    "awvalid", "awready", "awaddr", "awid", "awlen",
    "wvalid", "wready", "wdata", "wstrb", "wlast",
    "bvalid", "bready", "bid", "bresp",
    "arvalid", "arready", "araddr", "arid", "arlen",
    "rvalid", "rready", "rdata", "rresp", "rlast", "rid",
)}


def axi_row(time: int, **updates: str) -> dict:
    values = {key: "0" for key in AXI_CFG}
    values.update(updates)
    return {"time": time, "values": values}


def test_axi_supports_w_before_aw_and_phase_evidence() -> None:
    rows = [
        axi_row(10, wvalid="1", wready="1", wdata="1010", wlast="1"),
        axi_row(20, awvalid="1", awready="1", awaddr="100", awid="1", awlen="0"),
        axi_row(30, bvalid="1", bready="1", bid="1", bresp="0"),
    ]
    result = axi_summary(rows, AXI_CFG, detail="transactions")
    assert result["summary"]["writes"] == 1
    txn = result["data"]["transactions"]["writes"][0]
    assert txn["phase_order"] == "w_before_aw"
    assert txn["first_data_time"] == 10
    assert txn["addr_time"] == 20
    assert txn["resp_time"] == 30
    assert "data" not in txn


def test_axi_matches_b_out_of_order_across_ids() -> None:
    rows = [
        axi_row(10, awvalid="1", awready="1", awid="0", awaddr="1", awlen="0",
                wvalid="1", wready="1", wdata="1", wlast="1"),
        axi_row(20, awvalid="1", awready="1", awid="1", awaddr="2", awlen="0",
                wvalid="1", wready="1", wdata="2", wlast="1"),
        axi_row(30, bvalid="1", bready="1", bid="1"),
        axi_row(40, bvalid="1", bready="1", bid="0"),
    ]
    result = axi_summary(rows, AXI_CFG, detail="transactions")
    assert [txn["id"] for txn in result["data"]["transactions"]["writes"]] == ["1", "0"]
    assert result["summary"]["final_write_outstanding"] == 0


def test_axi_rid_is_strict_and_wid_is_rejected() -> None:
    with pytest.raises(ValueError, match="WID"):
        axi_summary([], {**AXI_CFG, "wid": "wid"})
    rows = [
        axi_row(10, arvalid="1", arready="1", arid="0", araddr="1", arlen="0"),
        axi_row(20, rvalid="1", rready="1", rid="1", rdata="1", rlast="1"),
    ]
    with pytest.raises(ProtocolAnalysisError) as info:
        axi_summary(rows, AXI_CFG)
    assert info.value.code == "AXI_ORPHAN_R"


def test_axi_unknown_marks_quality_ambiguous_without_transfer() -> None:
    result = axi_summary([axi_row(10, awvalid="X", awready="1")], AXI_CFG)
    assert result["meta"]["analysis_quality"] == "ambiguous"
    assert result["summary"]["channels"]["AW"]["valid_unknown"] == 1


def test_stream_supports_ready_and_bp_and_strict_packets() -> None:
    cfg = {"valid": "v", "ready": "r", "data": "d", "sop": "s", "eop": "e"}
    rows = [
        {"time": 1, "values": {"v": "1", "r": "0", "d": "a", "s": "0", "e": "0"}},
        {"time": 2, "values": {"v": "1", "r": "1", "d": "a", "s": "1", "e": "0"}},
        {"time": 3, "values": {"v": "1", "r": "1", "d": "b", "s": "0", "e": "1"}},
    ]
    result = stream_summary(rows, cfg, detail="full")
    assert result["summary"]["transfers"] == 2
    assert result["summary"]["stall_cycles"] == 1
    assert result["summary"]["packets"] == 1
    bp_result = stream_summary([
        {"time": 1, "values": {"v": "1", "bp": "0"}},
    ], {"valid": "v", "bp": "bp"})
    assert bp_result["summary"]["transfers"] == 1


def test_stream_rejects_partial_boundary_and_orphan_packet_beat() -> None:
    with pytest.raises(ValueError, match="both sop and eop"):
        stream_summary([], {"valid": "v", "ready": "r", "sop": "s"})
    with pytest.raises(ProtocolAnalysisError) as info:
        stream_summary([
            {"time": 1, "values": {"v": "1", "r": "1", "s": "0", "e": "0"}},
        ], {"valid": "v", "ready": "r", "sop": "s", "eop": "e"})
    assert info.value.code == "STREAM_ORPHAN_BEAT"


class RecordingExclusionItem:
    def __init__(self, report_time: bool = False, compile_time: bool = False,
                 setter_result: int = 1) -> None:
        self.report_time = report_time
        self.compile_time = compile_time
        self.setter_result = setter_result
        self.setter_values: list[int] = []

    def has_status_excluded_at_report_time(self, test: object) -> bool:
        return self.report_time

    def has_status_excluded_at_compile_time(self, test: object) -> bool:
        return self.compile_time

    def set_status_excluded_at_report_time(self, test: object, value: int) -> int:
        self.setter_values.append(value)
        if self.setter_result == 1:
            self.report_time = bool(value)
        return self.setter_result


class RecordingExclusionTest:
    def __init__(self, results: dict[str, int] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[object, ...]] = []

    def load_exclude_file(self, path: str) -> int:
        self.calls.append(("load", path))
        return self.results.get("load", 1)

    def save_exclude_file(self, path: str, mode: str) -> int:
        self.calls.append(("save", path, mode))
        Path(path).write_text("opaque native el\n", encoding="utf-8")
        return self.results.get("save", 1)

    def unload_exclusion(self) -> int:
        self.calls.append(("unload",))
        return self.results.get("unload", 1)


class SyntheticCoverageHandle(RecordingExclusionItem):
    def __init__(self, typ: str, name: str, full_name: str, source: str = "",
                 line: int = -1, children: list["SyntheticCoverageHandle"] | None = None) -> None:
        super().__init__()
        self._type = typ
        self._name = name
        self._full_name = full_name
        self._source = source
        self._line = line
        self._children = children or []

    def type(self) -> str:
        return self._type

    def name(self) -> str:
        return self._name

    def full_name(self) -> str:
        return self._full_name

    def file_name(self) -> str:
        return self._source

    def line_no(self, test: object) -> int:
        return self._line

    def child_handles(self) -> list["SyntheticCoverageHandle"]:
        return list(self._children)

    def toggle_type(self, test: object) -> str:
        return self._name


class SyntheticInstance:
    def __init__(self, name: str, metrics: dict[str, SyntheticCoverageHandle]) -> None:
        self._name = name
        self._metrics = metrics

    def full_name(self) -> str:
        return self._name

    def type(self) -> str:
        return "npiCovInstance"

    def instance_handles(self) -> list["SyntheticInstance"]:
        return []

    def line_metric_handle(self) -> SyntheticCoverageHandle | None:
        return self._metrics.get("line")

    def assert_metric_handle(self) -> SyntheticCoverageHandle | None:
        return self._metrics.get("assert")


class SyntheticCoverageDb:
    def __init__(self, instance: SyntheticInstance) -> None:
        self.instance = instance

    def instance_handles(self) -> list[SyntheticInstance]:
        return [self.instance]

    def handle_by_name(self, name: str) -> SyntheticInstance | None:
        return self.instance if name == self.instance.full_name() else None


class SyntheticCovModule:
    def __init__(self) -> None:
        self.release_count = 0

    def release_handle(self, handle: object) -> None:
        self.release_count += 1


class SyntheticCompileTest(RecordingExclusionTest):
    def __init__(self, functional: SyntheticCoverageHandle) -> None:
        super().__init__()
        self.functional = functional

    def testbench_metric_handle(self) -> SyntheticCoverageHandle:
        return self.functional


def _write_csv_set(root: Path, *, reason: str = "architectural unreachable") -> None:
    root.mkdir()
    reason_field = '"' + reason.replace('"', '""') + '"'
    documents = {
        "code_exclusions.csv": (
            "xcov-code-exclusions.v1", "code",
            "scope,metric,line,object,bin,reason\n"
            "# source_file=rtl/design.sv\n"
            f"top,line,10,,,{reason_field}\n",
        ),
        "functional_exclusions.csv": (
            "xcov-functional-exclusions.v1", "functional",
            "scope,line,covergroup,coverpoint,cross,bin,reason\n"
            "# source_file=tb/coverage.sv\n"
            "top,20,cg_mode,cp_mode,,idle,not reachable\n",
        ),
        "assertion_exclusions.csv": (
            "xcov-assertion-exclusions.v1", "assertion",
            "scope,line,assertion,assertion_kind,reason\n"
            "# source_file=tb/assertions.sv\n"
            "top,30,a_reset,assertion,disabled by configuration\n",
        ),
    }
    for name, (schema, kind, body) in documents.items():
        (root / name).write_text(
            f"# schema_version={schema}\n# coverage_kind={kind}\n{body}",
            encoding="utf-8",
        )


def _write_urg_report(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.xml").write_text(
        """<session><hvp><old_coverage>
<scope type="instance" name="top"><metric name="Line" value="3/4" />
  <scope type="instance" name="u0"><metric name="Line" value="1/2" /></scope>
</scope>
<scope type="Groups" name="top"><attr type="Group Summary" value="1/2" />
 <scope type="Cover Group" name="cg_mode">
  <scope type="Covergroup Variant" name="top::cg_mode"><metric name="Group" value="1/2" />
   <scope type="Coverage Instance" name="cg0"><metric name="Group" value="1/2" />
    <scope type="Coverage Point" name="cp_mode"><metric name="Point" value="1/2" /></scope>
    <scope type="Cross Coverage" name="cx_mode"><metric name="Cross" value="0/1" /></scope>
   </scope>
  </scope>
 </scope>
</scope>
<scope type="Asserts" name="top">
 <scope type="Assertion" name="top.a_valid"><attr type="attempt" value="3" />
  <attr type="success" value="2" /><attr type="failure" value="1" />
  <attr type="incomplete" value="0" /></scope>
 <scope type="Cover Property" name="top.c_ready"><attr type="attempt" value="2" />
  <attr type="all match" value="0" /><attr type="mismatches" value="2" />
  <attr type="incomplete" value="0" /></scope>
</scope>
</old_coverage></hvp></session>\n""",
        encoding="utf-8",
    )
    (root / "tests.txt").write_text(
        "Tests\n\nTotal tests in report: 1\n"
        "Data from the following tests was used to generate this report\n"
        "/shared/run/case_a\n\n",
        encoding="utf-8",
    )
    for name in ("dashboard.txt", "modlist.txt", "groups.txt", "asserts.txt"):
        (root / name).write_text(f"{name}\n", encoding="utf-8")


def test_urg_parser_keeps_code_functional_and_assertion_types_separate(tmp_path: Path) -> None:
    report = tmp_path / "urg-report"
    _write_urg_report(report)
    summary = parse_summary(report)
    assert summary.tests == ("case_a",)
    assert len(summary.scopes) == 2
    assert summary.xml_instances == ("top", "top.u0")
    assert summary.xml_instance_parent == {"top": None, "top.u0": "top"}
    assert summary.xml_instance_children == {"top": ("top.u0",), "top.u0": ()}
    assert summary.expand_xml_instances("top", recursive=True) == ("top", "top.u0")
    root = next(row for row in summary.scopes if row["full_name"] == "top")
    assert root["metrics"]["line"]["coverage_pct"] == 75.0
    assert {row["node_kind"] for row in summary.functional} == {
        "Covergroup Variant", "Coverage Instance", "Coverage Point", "Cross Coverage",
    }
    assert [row["kind"] for row in summary.assertions] == [
        "assertion", "cover_property",
    ]
    assert summary.assertions[0]["attempts"] == 3
    assert summary.assertions[1]["coverage_pct"] == 0.0
    assert not any(row["coverage_kind"] == "code" for row in summary.functional)


def test_x_npi_urg_parser_keeps_zero_denominator_exclusion(tmp_path: Path) -> None:
    report = tmp_path / "urg-report"
    _write_urg_report(report)
    xml = report / "session.xml"
    text = xml.read_text(encoding="utf-8").replace(
        '<metric name="Line" value="1/2" />',
        '<metric name="Line" value="0/0" excl="2" />',
    ).replace(
        '<metric name="Group" value="1/2" />',
        '<metric name="Group" value="0/0" excl="2" />',
    )
    xml.write_text(text, encoding="utf-8")

    summary = parse_summary(report)
    child = next(row for row in summary.scopes if row["full_name"] == "top.u0")
    assert child["metrics"]["line"] == {
        "covered": 0, "coverable": 0, "missing": 0,
        "coverage_pct": None, "excluded": 2,
    }
    group = next(
        row for row in summary.functional
        if row["node_kind"] == "Coverage Instance"
    )
    assert group["coverage_pct"] is None
    assert group["excluded"] == 2


def test_x_npi_urg_parser_accepts_missing_score_only_for_zero_object_summary(
    tmp_path: Path,
) -> None:
    report = tmp_path / "urg-report"
    _write_urg_report(report)
    xml = report / "session.xml"
    text = xml.read_text(encoding="utf-8").replace(
        '<attr type="Group Summary" value="1/2" />',
        '<attr type="Group Summary" value="1/2" />\n'
        '<attr type="Group Instance Summary" value="0/0" />',
    ).replace(
        '<scope type="Coverage Instance" name="cg0"><metric name="Group" value="1/2" />',
        '<scope type="Coverage Instance" name="cg0">',
    )
    xml.write_text(text, encoding="utf-8")

    summary = parse_summary(report)
    instance = next(
        row for row in summary.functional
        if row["node_kind"] == "Coverage Instance"
    )
    assert instance["covered"] == instance["coverable"] == 0
    assert instance["coverage_pct"] is None

    xml.write_text(
        text.replace('<attr type="Group Instance Summary" value="0/0" />', ""),
        encoding="utf-8",
    )
    with pytest.raises(UrgCoverageError, match="lacks 'Group' metric"):
        parse_summary(report)


def test_container_planner_expands_only_real_xml_instances(tmp_path: Path) -> None:
    report = tmp_path / "urg-report"
    _write_urg_report(report)
    summary = parse_summary(report)
    rows = plan_container_records(
        summary,
        recursive_instances=["top"],
        covergroups=[("top", "cg_mode")],
        coverpoints=[("top", "cg_mode", "cp_mode")],
        crosses=[("top", "cg_mode", "cx_mode")],
        reason="container regression",
    )
    instance_rows = [row for row in rows if row["target_kind"] == "instance"]
    assert [(row["scope"], row["expansion_root"]) for row in instance_rows] == [
        ("top", "top"), ("top.u0", "top"),
    ]
    csv_root = tmp_path / "csv"
    paths = write_csv_set(csv_root, rows)
    assert len(paths) == 4
    assert parse_directory(csv_root)[-1].row_count == 5
    with pytest.raises(UrgCoverageError, match="real instance"):
        plan_container_records(
            summary, recursive_instances=["synthetic"], reason="invalid",
        )


def test_urg_export_uses_only_fixed_full64_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database = tmp_path / "input.vdb"
    database.mkdir()
    executable = tmp_path / "vcs" / "bin" / "urg"
    executable.parent.mkdir(parents=True)
    executable.write_text("urg test executable placeholder\n", encoding="utf-8")
    executable.chmod(0o755)
    report = tmp_path / "published"
    observed: list[list[str]] = []

    def recording_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        observed.append(argv)
        staging = Path(argv[argv.index("-report") + 1])
        _write_urg_report(staging)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("VCS_HOME", str(executable.parents[1]))
    monkeypatch.setattr(subprocess, "run", recording_run)
    summary = export_summary(database, report)
    assert summary.tests == ("case_a",)
    assert observed == [[
        str(executable.resolve()), "-full64", "-dir", str(database.resolve()),
        "-report", observed[0][5], "-xml_verbose", "-format", "text",
        "-show", "summary",
    ]]
    coverage_source = (SKILL / "scripts/x_npi/coverage.py").read_text(encoding="utf-8")
    urg_source = (SKILL / "scripts/x_npi/urg.py").read_text(encoding="utf-8")
    assert "_safe_call" not in coverage_source
    assert "coverage_items" not in coverage_source
    assert "shutil.which" not in urg_source


def test_exclusion_csv_is_strict_stable_and_preserves_multiline_reason(tmp_path: Path) -> None:
    csv_root = tmp_path / "csv"
    _write_csv_set(csv_root, reason="first line\nsecond line")
    documents = parse_directory(csv_root)
    assert documents[0].groups[0].rows[0]["reason"] == "first line\nsecond line"
    first = format_directory(csv_root, write=True)
    second = format_directory(csv_root, write=False)
    assert any(row["status"] == "formatted" for row in first)
    assert all(row["status"] == "current" for row in second)
    bad = (csv_root / "code_exclusions.csv").read_text(encoding="utf-8").replace(
        "rtl/design.sv", "../rtl/design.sv",
    )
    (csv_root / "code_exclusions.csv").write_text(bad, encoding="utf-8")
    with pytest.raises(ExclusionCsvError, match="portable relative"):
        parse_directory(csv_root)


def test_csv_to_el_uses_builtin_two_pass_index_and_publishes_four_native_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_root = tmp_path / "csv"
    _write_csv_set(csv_root)
    line = SyntheticCoverageHandle(
        "npiCovStmtBin", "statement", "top.line.statement",
        "/build/project/rtl/design.sv", 10,
    )
    assertion = SyntheticCoverageHandle(
        "npiCovAssert", "a_reset", "top.a_reset",
        "/build/project/tb/assertions.sv", 30,
    )
    functional = SyntheticCoverageHandle(
        "npiCovCovergroup", "cg_mode", "top.cg_mode", "/build/project/tb/coverage.sv", 20,
        [SyntheticCoverageHandle(
            "npiCovCoverpoint", "cp_mode", "top.cg_mode.cp_mode", children=[
                SyntheticCoverageHandle(
                    "npiCovCoverBin", "idle", "top.cg_mode.cp_mode.idle",
                ),
            ],
        )],
    )
    native_test = SyntheticCompileTest(functional)
    database = SyntheticCoverageDb(SyntheticInstance(
        "top",
        {
            "line": SyntheticCoverageHandle("npiCovMetric", "line", "top.line", children=[line]),
            "assert": SyntheticCoverageHandle(
                "npiCovMetric", "assert", "top.assert", children=[assertion],
            ),
        },
    ))
    cov = SyntheticCovModule()
    monkeypatch.setattr("x_npi.coverage._cov", lambda: cov)

    published = compile_csv_to_el(database, native_test, csv_root, tmp_path / "el")
    assert [row["coverage_kind"] for row in published] == [
        "code", "functional", "assertion", "container",
    ]
    assert all(row["preflight_passes"] == 1 for row in published[:3])
    assert all(row["apply_passes"] == 1 for row in published[:3])
    assert all(row["matched_count"] == 1 for row in published[:3])
    assert published[3]["preflight_passes"] == 0
    assert published[3]["apply_passes"] == 0
    assert published[3]["matched_count"] == 0
    assert line.setter_values == [1]
    assert assertion.setter_values == [1]
    assert functional._children[0]._children[0].setter_values == [1]
    assert cov.release_count > 0
    assert all(Path(row["path"]).read_text(encoding="utf-8") for row in published)
    assert native_test.calls[-4:] == [
        ("load", str(tmp_path / "el" / "code.el")),
        ("load", str(tmp_path / "el" / "functional.el")),
        ("load", str(tmp_path / "el" / "assertion.el")),
        ("load", str(tmp_path / "el" / "container.el")),
    ]


def test_container_csv_is_optional_and_has_strict_target_shapes(tmp_path: Path) -> None:
    csv_root = tmp_path / "csv"
    _write_csv_set(csv_root)
    documents = parse_directory(csv_root)
    assert [document.kind for document in documents] == [
        "code", "functional", "assertion", "container",
    ]
    assert documents[-1].groups == []

    (csv_root / "container_exclusions.csv").write_text(
        "# schema_version=xcov-container-exclusions.v1\n"
        "# coverage_kind=container\n"
        "target_kind,scope,covergroup,item,expansion_root,reason\n"
        "instance,top.u0,,,top,recursive root\n"
        "covergroup,top,top::cg_mode,,,whole group\n"
        "coverpoint,top,top::cg_mode,cp_mode,,whole point\n"
        "cross,top,top::cg_mode,cx_mode,,whole cross\n",
        encoding="utf-8",
    )
    container = parse_directory(csv_root)[-1]
    assert [row["target_kind"] for row in container.groups[0].rows] == [
        "instance", "covergroup", "coverpoint", "cross",
    ]
    format_directory(csv_root, write=True)
    assert "# source_file=" not in (
        csv_root / "container_exclusions.csv"
    ).read_text(encoding="utf-8")

    bad = (csv_root / "container_exclusions.csv").read_text(encoding="utf-8").replace(
        "covergroup,top,top::cg_mode,,,whole group",
        "covergroup,top,top::cg_mode,cp_mode,,whole group",
    )
    (csv_root / "container_exclusions.csv").write_text(bad, encoding="utf-8")
    with pytest.raises(ExclusionCsvError, match="empty item"):
        parse_directory(csv_root)


def test_csv_to_el_missing_target_does_not_mutate_or_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    csv_root = tmp_path / "csv"
    _write_csv_set(csv_root)
    database = SyntheticCoverageDb(SyntheticInstance("top", {}))
    native_test = SyntheticCompileTest(SyntheticCoverageHandle(
        "npiCovMetric", "functional", "functional",
    ))
    monkeypatch.setattr("x_npi.coverage._cov", lambda: SyntheticCovModule())
    with pytest.raises(CoverageExclusionError, match="TARGET_MISSING"):
        compile_csv_to_el(database, native_test, csv_root, tmp_path / "el")
    assert native_test.calls == []
    assert not (tmp_path / "el" / "code.el").exists()


def test_csv_to_el_cli_has_no_external_resolver_contract() -> None:
    script = SKILL / "scripts/examples/csv_to_el.py"
    source = script.read_text(encoding="utf-8")
    assert "--resolver" not in source
    assert "importlib" not in source
    assert "from xcov" not in source
    assert "import xcov" not in source
    proc = subprocess.run(
        [sys.executable, str(script), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0
    assert "--resolver" not in proc.stdout
    for option in ("--vdb", "--csv-directory", "--output-directory", "--strict"):
        assert option in proc.stdout


@pytest.mark.parametrize("record_count", [1_000, 10_000])
def test_csv_to_el_operation_count_is_linear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_count: int,
) -> None:
    csv_root = tmp_path / "csv"
    csv_root.mkdir()
    rows = "".join(
        f"top,line,{line},,,linear guard\n"
        for line in range(1, record_count + 1)
    )
    (csv_root / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "# source_file=rtl/linear.sv\n" + rows,
        encoding="utf-8",
    )
    (csv_root / "functional_exclusions.csv").write_text(
        "# schema_version=xcov-functional-exclusions.v1\n"
        "# coverage_kind=functional\n"
        "scope,line,covergroup,coverpoint,cross,bin,reason\n",
        encoding="utf-8",
    )
    (csv_root / "assertion_exclusions.csv").write_text(
        "# schema_version=xcov-assertion-exclusions.v1\n"
        "# coverage_kind=assertion\n"
        "scope,line,assertion,assertion_kind,reason\n",
        encoding="utf-8",
    )
    leaves = [
        SyntheticCoverageHandle(
            "npiCovStmtBin", f"statement_{line}", f"top.line.statement_{line}",
            "/build/project/rtl/linear.sv", line,
        )
        for line in range(1, record_count + 1)
    ]
    database = SyntheticCoverageDb(SyntheticInstance("top", {
        "line": SyntheticCoverageHandle("npiCovMetric", "line", "top.line", children=leaves),
    }))
    native_test = SyntheticCompileTest(SyntheticCoverageHandle(
        "npiCovMetric", "functional", "functional",
    ))
    monkeypatch.setattr("x_npi.coverage._cov", lambda: SyntheticCovModule())

    published = compile_csv_to_el(database, native_test, csv_root, tmp_path / "el")
    code = published[0]
    assert code["preflight_passes"] == 1
    assert code["apply_passes"] == 1
    assert code["visited_handle_count"] == 2 * (record_count + 1)
    assert code["matched_count"] == record_count
    assert published[1]["visited_handle_count"] == 0
    assert published[2]["visited_handle_count"] == 0


def test_value_and_json_helpers_are_deterministic() -> None:
    assert active("1") is True
    assert active("X") is False
    assert known("10xz") is False
    assert split_limited([1, 2, 3], 2) == ([1, 2], True)
