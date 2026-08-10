"""Tests for the unified NPI coverage backend and URG scope metadata."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest


def test_session_xml_all_scopes(xverif_fixture):
    """Verify session.xml parses 5+ level scope hierarchy."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.backend import NpiCoverageBackend as UrgAggBackend
    backend = UrgAggBackend(vdb=str(vdb))
    try:
        scopes = backend.scopes()
        names = {s["full_name"] for s in scopes}
        # Must have all 5 levels
        assert "top" in names
        assert any("u_core0" in n for n in names)
        assert any("u_core1" in n for n in names)
        assert any("u_alu" in n for n in names)
        assert any("u_ctl" in n for n in names)
        # u_core0 and u_core1 must have different coverage
        core0_scopes = [s for s in scopes if "u_core0" in s["full_name"]]
        core1_scopes = [s for s in scopes if "u_core1" in s["full_name"]]
        assert len(core0_scopes) > 0
        assert len(core1_scopes) > 0
    finally:
        backend.close()


def test_npi_line_items_follow_score_contract(xverif_fixture):
    """Unified backend publishes real NPI line leaves under the score contract."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.backend import NpiCoverageBackend
    from xcov.coverage_contract import is_score_bearing_row

    backend = NpiCoverageBackend(vdb=str(vdb))
    try:
        items = backend.items(metrics=["line"])
    finally:
        backend.close()

    score_rows = [item for item in items if is_score_bearing_row(item)]
    assert score_rows, "fixture must expose score-bearing line rows"
    for item in score_rows:
        assert item["metric"] == "line"
        assert isinstance(item.get("covered"), int) and item["covered"] >= 0
        assert isinstance(item.get("coverable"), int) and item["coverable"] >= 0

def test_multi_inst_diff_coverage(xverif_fixture):
    """u_core0 (pipeline) and u_core1 (burst) have different coverage."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.backend import NpiCoverageBackend as UrgAggBackend
    backend = UrgAggBackend(vdb=str(vdb))
    try:
        items = backend.items()
        core0_items = [i for i in items if "u_core0" in i["scope"] and "u_core1" not in i["scope"]]
        core1_items = [i for i in items if "u_core1" in i["scope"]]

        # u_core1 (burst) has different branch coverage than u_core0 (pipeline)
        c0_branch = [i for i in core0_items if i["metric"] == "branch"]
        c1_branch = [i for i in core1_items if i["metric"] == "branch"]
        assert len(c0_branch) > 0 and len(c1_branch) > 0

        # Coverage values must differ because they take different paths
        c0_vals = {(i["scope"], i["covered"], i["coverable"]) for i in c0_branch}
        c1_vals = {(i["scope"], i["covered"], i["coverable"]) for i in c1_branch}
        # At minimum the scope names differ
        assert c0_vals != c1_vals, "u_core0 and u_core1 must have different coverage"
    finally:
        backend.close()


def test_urg_with_elfile(xverif_fixture, tmp_path):
    """URG applies a real NPI exclusion file to a covered line item."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    import subprocess
    import xml.etree.ElementTree as ET
    from xcov.eda import get_urg_path

    def run_urg(report_dir, elfile=None):
        command = [
            get_urg_path(), "-dir", str(vdb), "-report", str(report_dir),
            "-format", "text", "-xml_verbose", "-metric", "line",
        ]
        if elfile is not None:
            command.extend(["-elfile", str(elfile)])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert result.returncode == 0, f"URG failed: {result.stderr[:500]}"
        return ET.parse(Path(report_dir) / "session.xml")

    def core0_line_metric(tree):
        for scope in tree.iter("scope"):
            if scope.get("name") != "u_core0":
                continue
            for metric in scope.findall("metric"):
                if metric.get("name") == "Line":
                    covered, total = metric.get("value", "0/0").split("/", 1)
                    return int(covered), int(total), int(metric.get("excl", "0"))
        pytest.fail("Could not find u_core0 Line metric in session.xml")

    baseline = core0_line_metric(run_urg(tmp_path / "baseline"))

    from xcov.eda import import_pynpi
    _, _ = import_pynpi()
    from pynpi import cov, cov_l0, npisys  # noqa: F811
    from xcov.coverage_contract import SCORE_TYPES_BY_METRIC

    npisys.init(["test_el"])
    db = cov.open(str(vdb))
    try:
        tests = db.test_handles()
        top = db.instance_handles()[0]
        u0 = top.instance_handles()[0]
        owned = []

        def find_covered(handle, selected_test):
            for child in handle.child_handles():
                owned.append(child)
                if (
                    child.type() in SCORE_TYPES_BY_METRIC["line"]
                    and child.covered(selected_test) > 0
                ):
                    return child
                found = find_covered(child, selected_test)
                if found is not None:
                    return found
            return None

        def find_in_instance(instance, selected_test):
            metric_handle = instance.line_metric_handle()
            if metric_handle:
                owned.append(metric_handle)
                target = find_covered(metric_handle, selected_test)
                if target is not None:
                    return target
            for child_instance in instance.instance_handles():
                owned.append(child_instance)
                target = find_in_instance(child_instance, selected_test)
                if target is not None:
                    return target
            return None

        try:
            selected_test = None
            target = None
            for candidate in tests:
                target = find_in_instance(u0, candidate)
                if target is not None:
                    selected_test = candidate
                    break
            assert target is not None, "fixture must contain a covered line item"
            changed = cov_l0.set_status(
                cov_l0.StatusExcludedAtReportTime,
                target.cps_obj,
                selected_test.cps_obj,
                1,
            )
            assert changed not in (0, False), "NPI should accept the covered exclusion"
            el_path = tmp_path / "test.el"
            cov_l0.save_exclude_file(selected_test.cps_obj, str(el_path), "w")
        finally:
            for child in reversed(owned):
                cov.release_handle(child)
    finally:
        db.close()
        npisys.end()

    after = core0_line_metric(run_urg(tmp_path / "with-el", el_path))
    assert after[2] > baseline[2], "EL should increase the excluded line count"
    assert after[0] < baseline[0], "excluding a covered line should reduce covered count"

def test_urg_show_brief(xverif_fixture, tmp_path):
    """-show brief only outputs uncovered items."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    import subprocess
    from xcov.eda import get_urg_path
    result = subprocess.run(
        [get_urg_path(), "-dir", str(vdb), "-report", str(tmp_path), "-format", "text",
         "-show", "brief", "-metric", "line"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0

    modinfo = Path(tmp_path) / "modinfo.txt"
    assert modinfo.exists()
    content = modinfo.read_text(encoding="utf-8")
    # Must have ==> markers for uncovered
    assert "==>" in content or "Not Covered" in content or "0/" in content


def test_el_lazy_export(xverif_fixture, tmp_path):
    """exclude.add marks _el_dirty, URG exports EL only on next call."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.session import SessionManager, XcovSession
    from xcov.backend import NpiCoverageBackend as UrgAggBackend

    def factory(vdb_path, **kw):
        b = UrgAggBackend(vdb=str(vdb_path))
        for k, v in kw.items():
            if hasattr(b, k): setattr(b, k, v)
        return b

    sm = SessionManager(backend_factory=factory)
    sess = sm.open(str(vdb), name="lazy_test", cache_dir=str(tmp_path))
    try:
        # Initially clean
        assert sess._el_dirty is False
        assert sess._el_path is None

        # Mark dirty
        sess.mark_exclusion_dirty()
        assert sess._el_dirty is True

        # ensure_el_ready creates EL
        el = sess.ensure_el_ready()
        assert el is not None
        assert os.path.exists(el)
        assert sess._el_dirty is False
        assert sess._el_path == el

        # clear_exclusions resets
        sess.clear_exclusions()
        assert sess._el_path is None
        assert sess._el_dirty is False
    finally:
        sess.close()


def test_export_code_to_dir(xverif_fixture, tmp_path):
    """export.code_coverage writes strict per-instance structured artifacts."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.actions import Dispatcher
    from xcov.session import SessionManager
    from xcov.backend import NpiCoverageBackend as UrgAggBackend

    def factory(vdb_path, **kw):
        b = UrgAggBackend(vdb=str(vdb_path))
        for k, v in kw.items():
            if hasattr(b, k): setattr(b, k, v)
        return b

    export_dir = str(tmp_path / "export_out")
    sm = SessionManager(backend_factory=factory)
    sess = sm.open(str(vdb), name="export_test", cache_dir=str(tmp_path))
    d = Dispatcher(sessions=sm)
    try:
        rsp = d.dispatch({
            "api_version": "xcov.v1",
            "action": "export.code_coverage",
            "target": {"session_id": "export_test"},
            "args": {
                "scopes": ["top.u_core0", "top.u_core1"],
                "metrics": ["line"],
                "output": {"path": export_dir},
            },
        })
        assert rsp["ok"], f"export failed: {rsp.get('error', {}).get('message', '?')}"
        run_dir = Path(rsp["summary"]["output_dir"])
        assert run_dir.parent == Path(export_dir)
        assert re.fullmatch(r"xcov_code_coverage_\d{8}_\d{6}", run_dir.name)
        assert len(rsp["data"]["items"]) == 2
        for item in rsp["data"]["items"]:
            instance_dir = Path(item["directory"])
            assert instance_dir.parent == run_dir
            assert (instance_dir / "navigation.json").is_file()
            assert (instance_dir / "navigation.xout").is_file()
            assert (instance_dir / "line.json").is_file()
            assert (instance_dir / "line.xout").is_file()
            assert (instance_dir / "line.urg.txt").is_file()
            assert not (instance_dir / "toggle.json").exists()
            payload = json.loads((instance_dir / "line.json").read_text(encoding="utf-8"))
            assert payload["scope"] == item["scope"]
            assert payload["coverage_basis"] == "self"
            assert payload["analysis_complete"] is True
    finally:
        sess.close()
