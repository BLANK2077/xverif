from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from xcov.actions import _code_coverage_from_urg, _coverage_from_urg, _metrics_from_urg
from xcov.errors import XcovError
from xcov.gap_export import build_gap_payload, parse_urg_gap_report
from xcov.urg_summary import REQUIRED_ARTIFACTS, parse_urg_summary


SESSION_XML = """\
<session version="1.1">
  <hvp><datadef>
    <metdef name="Line" type="ratio" aggregator="average" builtin="1" />
    <metdef name="Assert" type="ratio" aggregator="average" builtin="1" />
    <metdef name="Group" type="ratio" aggregator="average" builtin="1" />
  </datadef></hvp>
  <old_coverage>
    <scope type="instance" name="top">
      <metric name="Line" value="8/10" excl="0" />
      <metric name="Assert" value="1/2" excl="0" />
      <scope type="instance" name="u0">
        <metric name="Line" value="1/2" excl="0" />
        <metric name="Assert" value="1/1" excl="0" />
      </scope>
    </scope>
    <scope type="Groups" name="top">
      <attr type="Group Summary" value="3/4" excl="0" />
      <scope type="Cover Group" name="dut::cg">
        <scope type="Covergroup Variant" name="top.u0::cg">
          <metric name="Group" value="3/4" excl="0" />
          <attr name="Score" value="75%" />
          <scope type="Coverage Point" name="cp_direct">
            <metric name="Point" value="1/2" excl="0" />
            <attr name="Score" value="50%" />
          </scope>
          <scope type="Coverage Instance" name="cg_i">
            <metric name="Group" value="3/4" excl="0" />
            <attr name="Score" value="75%" />
            <scope type="Coverage Point" name="cp">
              <metric name="Point" value="1/2" excl="0" />
              <attr name="Score" value="50%" />
            </scope>
            <scope type="Cross Coverage" name="cx">
              <metric name="Cross" value="2/2" excl="0" />
              <attr name="Score" value="100%" />
            </scope>
          </scope>
        </scope>
      </scope>
    </scope>
    <scope type="Asserts" name="top">
      <scope type="Assertion" name="top.u0.a_ok">
        <attr type="attempt" value="12" />
        <attr type="success" value="9" />
        <attr type="failure" value="1" />
        <attr type="incomplete" value="0" />
      </scope>
      <scope type="Cover Property" name="top.u0.c_miss">
        <attr type="attempt" value="12" />
        <attr type="all match" value="0" />
        <attr type="mismatches" value="10" />
        <attr type="incomplete" value="0" />
      </scope>
    </scope>
    <scope type="assert" name="Statistics" />
  </old_coverage>
</session>
"""


def _report(tmp_path: Path, xml: str = SESSION_XML) -> Path:
    report = tmp_path / "report"
    report.mkdir()
    for name in REQUIRED_ARTIFACTS:
        content = "placeholder\n"
        if name == "session.xml":
            content = xml
        elif name == "tests.txt":
            content = (
                "Tests\n\nTotal tests in report: 1\n"
                "-------------------------------------------------------------------------------\n"
                "Data from the following tests was used to generate this report\n"
                "/shared/run/test_a\n"
            )
        (report / name).write_text(content, encoding="utf-8")
    return report


def test_urg_assert_detail_parser_builds_semantic_gaps(tmp_path):
    report = tmp_path / "asserts.txt"
    report.write_text(
        """Assertions Uncovered:
ASSERTIONS CATEGORY SEVERITY ATTEMPTS REAL SUCCESSES FAILURES INCOMPLETE
top.u0.a_missing 0 0 41 0 0 0
-------------------------------------------------------------------------------
Cover Properties Uncovered:
COVER PROPERTIES CATEGORY SEVERITY ATTEMPTS MATCHES INCOMPLETE
top.u0.c_missing 0 0 41 0 0
-------------------------------------------------------------------------------
""",
        encoding="utf-8",
    )
    rows = parse_urg_gap_report("assert", report)
    assert [(row["type"], row["scope"], row["name"]) for row in rows] == [
        ("npiCovAssert", "top.u0", "a_missing"),
        ("npiCovCoverProperty", "top.u0", "c_missing"),
    ]
    payload = build_gap_payload("assert", "sample.vdb", rows)
    assert payload["exclusion_locator"]["version"] == "xcov.urg_semantic.v1"
    assert "_exclude_targets" not in payload["gaps"][0]


def test_urg_functional_detail_parser_builds_bin_semantics(tmp_path):
    report = tmp_path / "grpinfo.txt"
    report.write_text(
        """Group : top::cg
===============================================================================
Group : top::cg
===============================================================================
Source File(s) :

/design/top.sv
Summary for Variable cp_data
User Defined Bins for cp_data
Uncovered bins
NAME COUNT AT LEAST NUMBER
other 0 1 1
-------------------------------------------------------------------------------
Summary for Cross cross_a
Automatically Generated Cross Bins for cross_a
Uncovered bins
A B COUNT AT LEAST NUMBER
[a] [b] 0 1 1
-------------------------------------------------------------------------------
""",
        encoding="utf-8",
    )
    rows = parse_urg_gap_report("functional", report)
    assert [(row["coverpoint"], row["cross"], row["bin"]) for row in rows] == [
        ("cp_data", None, "other"),
        (None, "cross_a", "[a] [b]"),
    ]
    assert all(row["type"] == "npiCovCoverBin" for row in rows)


def test_content_addressed_urg_cache_cold_warm_corrupt_and_el_invalidation(
    monkeypatch,
    tmp_path,
):
    from xcov import urg_cache

    vdb = tmp_path / "sample.vdb"
    vdb.mkdir()
    (vdb / "content.bin").write_bytes(b"coverage-v1")
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": "/eda/urg", "size_bytes": 1, "mtime_ns": 1},
    )

    class FakeRunner:
        def __init__(self):
            self.calls = []

        def run(self, argv, timeout=None):
            self.calls.append(list(argv))
            report = Path(argv[argv.index("-report") + 1])
            for name in REQUIRED_ARTIFACTS:
                content = "placeholder\n"
                if name == "session.xml":
                    content = SESSION_XML
                elif name == "tests.txt":
                    content = (
                        "Total tests in report: 1\n"
                        "Data from the following tests was used to generate this report\n"
                        "test0\n"
                    )
                (report / name).write_text(content, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = FakeRunner()
    first, first_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, runner=runner,
    )
    second, second_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, runner=runner,
    )
    assert first.tests == second.tests == ("test0",)
    assert first_meta["hit"] is False
    assert second_meta["hit"] is True
    assert first_meta["key"] == second_meta["key"]
    assert len(runner.calls) == 1
    manifest = __import__("json").loads(
        (Path(first_meta["entry"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["complete"] is True
    assert set(manifest["artifacts"]) == set(REQUIRED_ARTIFACTS)
    assert manifest["semantic_counts"] == {
        "metric_count": 3,
        "test_count": 1,
        "scope_count": 2,
        "functional_row_count": 3,
        "assertion_row_count": 2,
    }
    assert (Path(first_meta["entry"]) / "COMPLETE").read_text().strip() == first_meta["key"]

    entry = Path(second_meta["entry"])
    (entry / "report" / "session.xml").write_text("", encoding="utf-8")
    _, repaired_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, runner=runner,
    )
    assert repaired_meta["hit"] is False
    assert len(runner.calls) == 2
    assert any((cache / "quarantine").iterdir())

    el = tmp_path / "current.el"
    el.write_bytes(b"exclude-v1")
    _, excluded_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache, el_path=str(el), runner=runner,
    )
    assert excluded_meta["hit"] is False
    assert excluded_meta["key"] != repaired_meta["key"]
    assert len(runner.calls) == 3
    assert "-elfile" in runner.calls[-1]
    _, manifest_meta = urg_cache.load_cached_urg_summary(
        str(vdb), cache_root=cache,
        run_manifest_digest="a" * 64, runner=runner,
    )
    assert manifest_meta["key"] not in {
        repaired_meta["key"], excluded_meta["key"],
    }
    assert len(runner.calls) == 4


def test_content_addressed_urg_cache_serializes_concurrent_miss(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from xcov import urg_cache

    vdb = tmp_path / "parallel.vdb"
    vdb.mkdir()
    (vdb / "content.bin").write_bytes(b"parallel")
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": "/eda/urg", "size_bytes": 1, "mtime_ns": 1},
    )
    entered = threading.Event()
    release = threading.Event()

    class BlockingRunner:
        def __init__(self):
            self.call_count = 0
            self.guard = threading.Lock()

        def run(self, argv, timeout=None):
            with self.guard:
                self.call_count += 1
            report = Path(argv[argv.index("-report") + 1])
            for name in REQUIRED_ARTIFACTS:
                content = "placeholder\n"
                if name == "session.xml":
                    content = SESSION_XML
                elif name == "tests.txt":
                    content = (
                        "Total tests in report: 1\n"
                        "Data from the following tests was used to generate this report\n"
                        "test0\n"
                    )
                (report / name).write_text(content, encoding="utf-8")
            entered.set()
            assert release.wait(timeout=5)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = BlockingRunner()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            urg_cache.load_cached_urg_summary,
            str(vdb), cache_root=cache, runner=runner,
        )
        assert entered.wait(timeout=5)
        second = pool.submit(
            urg_cache.load_cached_urg_summary,
            str(vdb), cache_root=cache, runner=runner,
        )
        release.set()
        first_meta = first.result(timeout=5)[1]
        second_meta = second.result(timeout=5)[1]
    assert runner.call_count == 1
    assert sorted([first_meta["hit"], second_meta["hit"]]) == [False, True]
    assert first_meta["key"] == second_meta["key"]


def test_urg_cache_lru_and_abandoned_staging_are_bounded(monkeypatch, tmp_path):
    from xcov import urg_cache

    monkeypatch.setattr(
        urg_cache,
        "_urg_identity",
        lambda: {"path": "/eda/urg", "release": "X-test", "size_bytes": 1, "mtime_ns": 1},
    )
    monkeypatch.setenv("XVERIF_XCOV_CACHE_MAX_ENTRIES", "1")
    cache = tmp_path / "cache"

    class Runner:
        def run(self, argv, timeout=None):
            report = Path(argv[argv.index("-report") + 1])
            for name in REQUIRED_ARTIFACTS:
                content = "placeholder\n"
                if name == "session.xml":
                    content = SESSION_XML
                elif name == "tests.txt":
                    content = (
                        "Total tests in report: 1\n"
                        "Data from the following tests was used to generate this report\n"
                        "test0\n"
                    )
                (report / name).write_text(content, encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    first_vdb = tmp_path / "first.vdb"
    second_vdb = tmp_path / "second.vdb"
    for index, vdb in enumerate((first_vdb, second_vdb), 1):
        vdb.mkdir()
        (vdb / "content").write_text(str(index), encoding="ascii")
    _, first_meta = urg_cache.load_cached_urg_summary(
        str(first_vdb), cache_root=cache, runner=Runner(),
    )
    _, second_meta = urg_cache.load_cached_urg_summary(
        str(second_vdb), cache_root=cache, runner=Runner(),
    )
    assert first_meta["key"] != second_meta["key"]
    entries = [path for path in (cache / "entries").iterdir() if path.is_dir()]
    assert [path.name for path in entries] == [second_meta["key"]]

    stale = cache / "staging" / ("a" * 64 + ".stale")
    stale.mkdir()
    old = __import__("time").time() - urg_cache.ABANDONED_STAGING_SECONDS - 1
    __import__("os").utime(stale, (old, old))
    urg_cache.load_cached_urg_summary(
        str(second_vdb), cache_root=cache, runner=Runner(),
    )
    assert not stale.exists()


def test_streaming_parser_keeps_code_assert_and_functional_types(tmp_path):
    index = parse_urg_summary(_report(tmp_path))

    assert index.tests == ("test_a",)
    assert [row["full_name"] for row in index.scopes] == ["top", "top.u0"]
    assert index.scope_metrics["top"]["line"]["covered"] == 8
    assert index.scope_metrics["top.u0"]["line"]["covered"] == 1
    assert index.scope_metrics["top"]["functional"]["pct"] == 75.0
    assert index.scope_metrics["top.u0"]["functional"]["pct"] == 75.0

    assert len(index.functional_rows) == 3
    group = next(row for row in index.functional_rows if row["type"] == "npiCovCovergroup")
    assert group["covergroup_type"] == "dut::cg"
    assert group["variant"] == "top.u0::cg"
    assert group["instance"] == "cg_i"
    assert {row.get("coverpoint") for row in index.functional_rows} == {None, "cp"}
    assert {row.get("cross") for row in index.functional_rows} == {None, "cx"}

    assertion, cover_property = index.assertion_rows
    assert assertion["scope"] == "top.u0"
    assert assertion["covered"] == 1
    assert assertion["coverable"] == 1
    assert assertion["attempts"] == 12
    assert assertion["real_successes"] == 9
    assert cover_property["covered"] == 0
    assert cover_property["missing"] == 1


def test_scope_aggregation_uses_parent_subtree_once_and_score_average(tmp_path):
    index = parse_urg_summary(_report(tmp_path))
    scopes = {row["full_name"]: row for row in index.scopes}
    coverage = _coverage_from_urg(
        index.scope_metrics,
        scopes,
        ["line", "assert", "functional"],
    )

    assert coverage["top"]["metrics"][0]["covered"] == 8
    assert coverage["top"]["coverage_pct"] == 68.3333
    assert "covered" not in coverage["top"]
    assert coverage["top.u0"]["coverage_pct"] == 75.0

    line_only = _code_coverage_from_urg(index.scope_metrics, "scope", ["line"])
    top = next(row for row in line_only if row["scope"] == "top")
    assert top["covered"] == 8
    assert top["coverable"] == 10

    metrics = _metrics_from_urg(index.scope_metrics, ["line"])
    assert metrics == [{
        "metric": "line",
        "covered": 8,
        "coverable": 10,
        "missing": 2,
        "coverage_pct": 80.0,
    }]


def test_parser_rejects_unknown_scope_type(tmp_path):
    xml = SESSION_XML.replace(
        '<scope type="assert" name="Statistics" />',
        '<scope type="Future Coverage" name="new" />',
    )
    with pytest.raises(XcovError) as raised:
        parse_urg_summary(_report(tmp_path, xml))
    assert raised.value.code == "URG_XML_UNSUPPORTED_SCOPE_TYPE"


def test_parser_rejects_missing_required_artifact(tmp_path):
    report = _report(tmp_path)
    (report / "groups.txt").unlink()
    with pytest.raises(XcovError) as raised:
        parse_urg_summary(report)
    assert raised.value.code == "URG_SUMMARY_INCOMPLETE"
