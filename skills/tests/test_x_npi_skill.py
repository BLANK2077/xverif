from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from skill_test_utils import assert_markdown_links


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "x-npi"
sys.path.insert(0, str(SKILL / "scripts"))

from x_npi.cli import require_output, sampling_contract  # noqa: E402
from x_npi.coverage import (  # noqa: E402
    CoverageExclusionError,
    coverage_summary,
    load_exclusion_files,
    open_covdb,
    save_exclusion_file,
    set_report_time_excluded,
    unload_exclusions,
)
from x_npi.jsonio import split_limited  # noqa: E402
from x_npi.protocol import (  # noqa: E402
    ProtocolAnalysisError,
    apb_summary,
    axi_summary,
    stream_summary,
)
from x_npi.wave import active, known  # noqa: E402


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


def test_coverage_summary_uses_score_rows_and_functional_group_average() -> None:
    rows = [
        {"metric": "line", "type": "npiCovStmtBin", "covered": 3, "coverable": 4, "missing": 1},
        {"metric": "functional", "covergroup": "cg", "type": "npiCovCoverpoint", "coverage_pct": 50.0},
        {"metric": "functional", "covergroup": "cg", "type": "npiCovCross", "coverage_pct": 100.0},
    ]
    result = coverage_summary(rows)
    assert result["metrics"][0]["coverage_pct"] == 75.0
    assert result["functional_groups"][0]["coverage_pct"] == 75.0


class FakeExclusionItem:
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


class FakeExclusionTest:
    def __init__(self, results: dict[str, int] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[object, ...]] = []

    def load_exclude_file(self, path: str) -> int:
        self.calls.append(("load", path))
        return self.results.get("load", 1)

    def save_exclude_file(self, path: str, mode: str) -> int:
        self.calls.append(("save", path, mode))
        return self.results.get("save", 1)

    def unload_exclusion(self) -> int:
        self.calls.append(("unload",))
        return self.results.get("unload", 1)


def test_exclusion_helpers_use_strict_open_union_write_mode_and_unload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class FakeCov:
        class ConfigOpt:
            ExclusionInStrictMode = 8

        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def open(self, path: str, option: int) -> object:
            self.calls.append((path, option))
            return object()

    fake_cov = FakeCov()
    monkeypatch.setattr("x_npi.coverage._cov", lambda: fake_cov)
    assert open_covdb("merged.vdb", strict=True)
    assert fake_cov.calls == [("merged.vdb", 8)]

    paths = [
        tmp_path / "code.el",
        tmp_path / "functional.el",
        tmp_path / "assertion.el",
    ]
    for path in paths:
        path.write_text("opaque\n", encoding="utf-8")
    test = FakeExclusionTest()
    assert load_exclusion_files(test, paths) == [
        {"path": str(path), "status": "loaded"} for path in paths
    ]
    assert test.calls == [("load", str(path)) for path in paths]
    assert save_exclusion_file(test, tmp_path / "current.el").endswith("current.el")
    unload_exclusions(test)
    assert test.calls[-2:] == [
        ("save", str(tmp_path / "current.el"), "w"),
        ("unload",),
    ]


def test_exclusion_setter_reports_before_after_idempotent_immutable_and_failed() -> None:
    test = object()
    item = FakeExclusionItem()
    assert set_report_time_excluded(item, test, True) == {
        "status": "changed", "before": False, "after": True,
    }
    assert set_report_time_excluded(item, test, True)["status"] == "already_in_state"
    assert item.setter_values == [1]

    immutable = FakeExclusionItem(compile_time=True)
    assert set_report_time_excluded(immutable, test, False)["status"] == "immutable_compile_time"
    assert immutable.setter_values == []

    combined = FakeExclusionItem(report_time=True, compile_time=True)
    assert set_report_time_excluded(combined, test, False) == {
        "status": "immutable_compile_time", "before": True, "after": False,
    }
    assert combined.setter_values == [0]

    failed = FakeExclusionItem(setter_result=0)
    assert set_report_time_excluded(failed, test, True) == {
        "status": "failed", "before": False, "after": False,
    }


def test_exclusion_helpers_fail_explicitly_and_preflight_all_paths(tmp_path: Path) -> None:
    existing = tmp_path / "code.el"
    existing.write_text("opaque\n", encoding="utf-8")
    test = FakeExclusionTest()
    with pytest.raises(FileNotFoundError, match="missing.el"):
        load_exclusion_files(test, [existing, tmp_path / "missing.el"])
    assert test.calls == []

    for operation, invoke in [
        ("load_exclude_file", lambda target: load_exclusion_files(target, [existing])),
        ("save_exclude_file", lambda target: save_exclusion_file(target, tmp_path / "out.el")),
        ("unload_exclusion", unload_exclusions),
    ]:
        key = operation.split("_")[0]
        with pytest.raises(CoverageExclusionError, match=operation):
            invoke(FakeExclusionTest({key: 0}))


def test_value_and_json_helpers_are_deterministic() -> None:
    assert active("1") is True
    assert active("X") is False
    assert known("10xz") is False
    assert split_limited([1, 2, 3], 2) == ([1, 2], True)
