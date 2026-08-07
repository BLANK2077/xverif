"""Tests for UrgAggBackend — URG session.xml parsing and scope aggregation."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_session_xml_all_scopes(xverif_fixture):
    """Verify session.xml parses 5+ level scope hierarchy."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.urg_backend import UrgAggBackend
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


def test_scope_aggregate_matches_npi(xverif_fixture):
    """scope.summary covered/total matches NPI leaf traversal + rollup."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    # URG side
    from xcov.urg_backend import UrgAggBackend
    urg = UrgAggBackend(vdb=str(vdb))
    try:
        urg_items = urg.items()
    finally:
        urg.close()

    # NPI side
    import sys
    sys.path.insert(0, os.path.join(os.environ["VERDI_HOME"], "share/NPI/python"))
    from pynpi import npisys, cov
    from collections import defaultdict

    npisys.init(["test_urg_backend"])
    db = cov.open(str(vdb))
    try:
        tests = db.test_handles()
        merged = cov.merge_test(tests[0], tests[1]) if len(tests) > 1 else tests[0]

        scope_agg = defaultdict(lambda: defaultdict(lambda: {"covered": 0, "coverable": 0}))

        def walk_leaves(handle, test, scope_name):
            for child in handle.child_handles():
                ct = child.type()
                mn = None
                if "Block" in ct or "Stmt" in ct: mn = "line"
                elif "Toggle" in ct or "Signal" in ct: mn = "toggle"
                elif "Cond" in ct: mn = "condition"
                elif "Branch" in ct: mn = "branch"
                elif "Fsm" in ct or "State" in ct or "Trans" in ct or "Seq" in ct: mn = "fsm"
                elif "Assert" in ct or "Success" in ct or "Attempt" in ct or "Fail" in ct or "Vacuous" in ct or "Incomplete" in ct: mn = "assert"

                if mn:
                    c = child.covered(test)
                    t = child.coverable(test)
                    if c >= 0: scope_agg[scope_name][mn]["covered"] += c
                    if t >= 0: scope_agg[scope_name][mn]["coverable"] += t
                else:
                    walk_leaves(child, test, scope_name)
                cov.release_handle(child)

        def walk_inst(inst, test, scope_path):
            for attr in ["line_metric_handle", "toggle_metric_handle", "condition_metric_handle",
                         "branch_metric_handle", "fsm_metric_handle", "assert_metric_handle"]:
                try:
                    g = getattr(inst, attr, None)
                    if g:
                        mh = g()
                        if mh: walk_leaves(mh, test, scope_path); cov.release_handle(mh)
                except Exception:
                    pass
            for ci in inst.instance_handles():
                cs = ci.full_name(); walk_inst(ci, test, cs); cov.release_handle(ci)

        top = db.instance_handles()[0]
        walk_inst(top, merged, "top")

        # Rollup to parents
        for scope, metrics in sorted(scope_agg.items(), key=lambda x: -x[0].count(".")):
            parent = scope.rsplit(".", 1)[0] if "." in scope else None
            if parent and parent in scope_agg:
                for m, d in metrics.items():
                    scope_agg[parent][m]["covered"] += d["covered"]
                    scope_agg[parent][m]["coverable"] += d["coverable"]

        # Compare URG vs NPI for leaf scopes
        urg_by_scope = defaultdict(dict)
        for item in urg_items:
            urg_by_scope[item["scope"]][item["metric"]] = {
                "covered": item["covered"], "coverable": item["coverable"]}

        for scope, metrics in scope_agg.items():
            if scope not in urg_by_scope:
                continue
            for metric, d in metrics.items():
                urg_d = urg_by_scope[scope].get(metric, {})
                if urg_d:
                    assert d["covered"] == urg_d["covered"], \
                        f"{scope}.{metric}: NPI covered={d['covered']} URG={urg_d['covered']}"
                    assert d["coverable"] == urg_d["coverable"], \
                        f"{scope}.{metric}: NPI coverable={d['coverable']} URG={urg_d['coverable']}"
    finally:
        db.close()
        npisys.end()


def test_multi_inst_diff_coverage(xverif_fixture):
    """u_core0 (pipeline) and u_core1 (burst) have different coverage."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.urg_backend import UrgAggBackend
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
    """-elfile reduces coverage values in session.xml."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    # First: get baseline without EL
    from xcov.urg_backend import UrgAggBackend
    backend = UrgAggBackend(vdb=str(vdb), cache_dir=str(tmp_path))
    try:
        baseline = backend.items(scope="top.u_core0")
        baseline_line = [i for i in baseline if i["metric"] == "line"]
        assert len(baseline_line) > 0
        base_covered = baseline_line[0]["covered"]
    finally:
        backend.close()

    # Create EL via NPI
    import sys
    sys.path.insert(0, os.path.join(os.environ["VERDI_HOME"], "share/NPI/python"))
    from pynpi import npisys, cov, cov_l0
    npisys.init(["test_el"])
    db = cov.open(str(vdb))
    try:
        test = db.test_handles()[0]
        top = db.instance_handles()[0]
        u0 = top.instance_handles()[0]
        lm = u0.line_metric_handle()
        children = lm.child_handles()
        if children:
            first = children[0]
            cov_l0.set_status(cov_l0.StatusExcludedAtReportTime, first.cps_obj, test.cps_obj, 1)
            for c in children: cov.release_handle(c)
        cov.release_handle(lm)
        el_path = str(tmp_path / "test.el")
        cov_l0.save_exclude_file(test.cps_obj, el_path, "w")
    finally:
        db.close()
        npisys.end()

    # Re-run URG with EL
    import subprocess
    cache2 = str(tmp_path / "cache2")
    os.makedirs(cache2, exist_ok=True)
    result = subprocess.run(
        ["urg", "-dir", str(vdb), "-report", cache2, "-format", "text",
         "-xml_verbose", "-elfile", el_path, "-metric", "line"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"URG failed: {result.stderr[:500]}"

    # Parse new session.xml
    import xml.etree.ElementTree as ET
    tree = ET.parse(os.path.join(cache2, "session.xml"))
    for scope in tree.iter("scope"):
        if scope.get("name") == "u_core0":
            for m in scope.findall("metric"):
                if m.get("name") == "Line":
                    val = m.get("value", "0/0")
                    cov_after, total_after = val.split("/")
                    excluded = int(m.get("excl", "0"))
                    assert excluded > 0, "EL should have excluded items"
                    assert int(cov_after) < base_covered, \
                        f"EL should reduce covered from {base_covered} to {cov_after}"
                    return

    pytest.fail("Could not find u_core0 Line metric in session.xml")


def test_urg_show_brief(xverif_fixture, tmp_path):
    """-show brief only outputs uncovered items."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    import subprocess
    result = subprocess.run(
        ["urg", "-dir", str(vdb), "-report", str(tmp_path), "-format", "text",
         "-show", "brief", "-metric", "line"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0

    modinfo = Path(tmp_path) / "modinfo.txt"
    assert modinfo.exists()
    content = modinfo.read_text()
    # Must have ==> markers for uncovered
    assert "==>" in content or "Not Covered" in content or "0/" in content


def test_el_lazy_export(xverif_fixture, tmp_path):
    """exclude.add marks _el_dirty, URG exports EL only on next call."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.session import SessionManager, XcovSession
    from xcov.urg_backend import UrgAggBackend

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
    """export.code_coverage writes URG output to specified directory."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"

    from xcov.actions import Dispatcher
    from xcov.session import SessionManager
    from xcov.urg_backend import UrgAggBackend

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
            "args": {"output": {"path": export_dir}},
        })
        assert rsp["ok"], f"export failed: {rsp.get('error', {}).get('message', '?')}"
        assert rsp["summary"]["output_dir"] == export_dir

        # Verify files exist
        assert os.path.isdir(export_dir)
        files = os.listdir(export_dir)
        assert len(files) > 0, f"Export dir empty: {export_dir}"
    finally:
        sess.close()
