from __future__ import annotations

from pathlib import Path

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
