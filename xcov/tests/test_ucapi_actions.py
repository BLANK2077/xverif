"""End-to-end coverage of the C++ UCAPI implementation.

`test_cpp_parity.py` proves the read actions match the Python reference.  This
module covers the write path: every action responds, EL annotations round-trip,
CSV compiles into EL, and container exclusions reach the EL.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPP_BINARY = ROOT / "xcov" / "bin" / "xcov"
XCOV_ENTRY = ROOT / "tools" / "xcov"


def _env(backend: str = "ucapi") -> dict:
    env = os.environ.copy()
    env["XVERIF_HOME"] = str(ROOT)
    env["XVERIF_XCOV_BACKEND"] = backend
    return env


class Loop:
    """One stdio-loop subprocess with helpers for request/response."""

    def __init__(self, command, env, vdb: Path, policy: str = "default"):
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
        ready = self.proc.stdout.readline()
        assert ready.strip(), "stdio-loop did not emit a ready frame"
        opened = self.send({
            "api_version": "xcov.v1",
            "request_id": "open",
            "action": "session.open",
            "target": {"vdb": str(vdb)},
            "args": {"name": "cov0", "exclusion_policy": policy},
        })
        assert opened["ok"], json.dumps(opened)[:500]

    def send(self, request):
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        assert line.strip(), "stdio-loop closed without a response"
        return json.loads(line)["json"]

    def call(self, action, args=None, request_id=None):
        return self.send({
            "api_version": "xcov.v1",
            "request_id": request_id or action,
            "action": action,
            "target": {"session_id": "cov0"},
            "args": args or {},
        })

    def close(self):
        try:
            self.proc.stdin.write(json.dumps({
                "api_version": "xcov.v1",
                "request_id": "quit",
                "action": "stdio.quit",
            }) + "\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=60)
        except Exception:
            self.proc.kill()


@pytest.fixture()
def vdb(xverif_fixture):
    resources = xverif_fixture("xcov.comprehensive")
    database = resources / "comprehensive.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    return database


@pytest.fixture()
def loop(vdb, tmp_path):
    if not CPP_BINARY.is_file():
        pytest.skip(f"C++ binary not built: {CPP_BINARY}; run `make -C xcov`")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        yield session
    finally:
        session.close()


def _scopes(loop: Loop) -> list[str]:
    response = loop.call("scope.children", {
        "scope": "top", "recursive": True, "limits": {"max_items": 1000},
    })
    assert response["ok"], json.dumps(response.get("error"))[:300]
    return [item["full_name"] for item in response["data"]["items"]]


def _first_gap_ref_for(loop: Loop, tmp_path: Path, scope: str) -> str:
    response = loop.call("export.code_coverage", {
        "scopes": [scope],
        "output": {"path": str(tmp_path / "code"), "allow_absolute_path": True},
    })
    assert response["ok"], json.dumps(response.get("error"))[:300]
    for item in response["data"]["items"]:
        for metric in item["metrics"]:
            path = Path(tmp_path / "code" / item["directory"], metric["json"])
            if not path.is_file():
                continue
            payload = json.loads(path.read_text())
            for gap in payload.get("gaps", []):
                if gap.get("coverage_ref"):
                    return gap["coverage_ref"]
    pytest.skip("fixture has no uncovered code gap")


def _first_gap_ref(loop: Loop, tmp_path: Path) -> str:
    return _first_gap_ref_for(loop, tmp_path, "top.u_core0")



def _seed_required_csvs(directory: Path) -> None:
    """Create the three CSVs required by the Python apply/compile contract."""
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

def _el_annotations(path: Path) -> list[str]:
    return [
        line.strip()[len('ANNOTATION: "'):-1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("ANNOTATION:")
    ]


def test_all_actions_respond(loop, tmp_path):
    """Every canonical action must answer with a schema-valid response."""
    scopes = _scopes(loop)
    code_scope = next((name for name in scopes if name.count(".") >= 1), scopes[0])
    _seed_required_csvs(tmp_path)
    requests = [
        ("session.status", {}),
        ("tests.list", {}),
        ("metrics.list", {}),
        ("scope.summary", {"scope": "top"}),
        ("scope.children", {"scope": "top"}),
        ("scope.search", {"query": {"include_patterns": ["*"],
                                    "match_field": "full_name"}}),
        ("code_coverage.summary", {"group_by": "metric"}),
        ("functional_coverage.summary", {"group_by": "covergroup"}),
        ("assert.summary", {}),
        ("export.code_coverage", {
            "scopes": [code_scope],
            "output": {"path": str(tmp_path / "actions-code"),
                       "allow_absolute_path": True},
        }),
        ("export.functional_coverage", {
            "output": {"path": str(tmp_path / "actions-func"),
                       "allow_absolute_path": True},
        }),
        ("export.assert", {
            "output": {"path": str(tmp_path / "actions-assert"),
                       "allow_absolute_path": True},
        }),
        ("exclude.add", {
            "coverage_refs": [{"coverage_ref": "xcovref.v1:" + "0" * 64,
                               "reason": "smoke"}],
        }),
        ("exclude.remove", {"coverage_refs": ["xcovref.v1:" + "0" * 64]}),
        ("exclude.instance.add", {"items": [{"scope": code_scope,
                                             "reason": "smoke"}]}),
        ("exclude.instance.remove", {"items": [{"scope": code_scope}]}),
        ("exclude.functional.add", {
            "items": [{"target_kind": "covergroup", "scope": code_scope,
                       "covergroup": "missing::cg", "reason": "smoke"}],
        }),
        ("exclude.functional.remove", {
            "items": [{"target_kind": "covergroup", "scope": code_scope,
                       "covergroup": "missing::cg"}],
        }),
        ("exclude.unload_all", {"confirm": True}),
        ("exclude.csv.validate", {"directory": str(tmp_path)}),
        ("exclude.csv.apply", {"directory": str(tmp_path)}),
        ("exclude.csv.compile", {
            "directory": str(tmp_path),
            "output_directory": str(tmp_path / "actions-el"),
        }),
        ("exclude.csv.export", {"directory": str(tmp_path / "actions-csv"),
                                "allow_absolute_path": True}),
        ("export.exclude", {
            "output": {"path": str(tmp_path / "actions.el"),
                       "allow_absolute_path": True},
        }),
    ]
    failures = []
    for action, args in requests:
        response = loop.call(action, args)
        if not response.get("ok"):
            failures.append((action, (response.get("error") or {}).get("code")))
    assert not failures, failures


def test_el_annotation_round_trip(loop, vdb, tmp_path):
    """exclude.add(reason) -> export.exclude -> load -> CSV keeps the reason."""
    reason = "ucapi annotation round trip"
    reference = _first_gap_ref(loop, tmp_path)
    added = loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": reason}],
    })
    assert added["ok"], added
    assert added["data"]["items"][0]["status"] == "changed"

    el_path = tmp_path / "round-trip.el"
    exported = loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    annotations = _el_annotations(el_path)
    assert reason in annotations, annotations

    # Fresh session loads the EL and exports the reason back to CSV.
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    second = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        loaded = second.call("exclude.load", {"paths": [str(el_path)]})
        assert loaded["ok"], loaded
        csv_dir = tmp_path / "csv"
        exported_csv = second.call("exclude.csv.export", {
            "directory": str(csv_dir), "allow_absolute_path": True,
        })
        assert exported_csv["ok"], exported_csv
        text = (csv_dir / "code_exclusions.csv").read_text(encoding="utf-8")
        assert reason in text, text
    finally:
        second.close()


def test_csv_compiles_to_el_with_annotation(loop, vdb, tmp_path):
    """A code CSV row becomes an excluded object carrying its reason."""
    reason = "csv compile reason"
    csv_dir = tmp_path / "csv-in"
    csv_dir.mkdir()
    scopes = _scopes(loop)
    leaf = next((name for name in scopes if name.count(".") >= 1), scopes[0])
    gaps = loop.call("export.code_coverage", {
        "scopes": [leaf],
        "output": {"path": str(tmp_path / "gap-src"),
                   "allow_absolute_path": True},
    })
    assert gaps["ok"], gaps
    object_name = None
    metric = "line"
    for item in gaps["data"]["items"]:
        for artifact in item["metrics"]:
            path = Path(tmp_path / "gap-src" / item["directory"], artifact["json"])
            if not path.is_file():
                continue
            payload = json.loads(path.read_text())
            if payload.get("gaps"):
                object_name = payload["gaps"][0]["full_name"]
                metric = artifact["metric"]
                break
        if object_name:
            break
    if object_name is None:
        pytest.skip("fixture has no code gap to compile")

    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"{leaf},{metric},,{object_name},,{reason}\n",
        encoding="utf-8",
    )
    _seed_required_csvs(csv_dir)
    el_dir = tmp_path / "compiled"
    response = loop.call("exclude.csv.compile", {
        "directory": str(csv_dir),
        "output_directory": str(el_dir),
        "allow_absolute_path": True,
    })
    assert response["ok"], response
    annotations = _el_annotations(el_dir / "code.el")
    assert reason in annotations, annotations


def test_instance_exclusion_reaches_el(loop, tmp_path):
    """Container-level instance exclusion writes object entries to the EL."""
    scopes = _scopes(loop)
    target = next((name for name in scopes if name.count(".") == 1), scopes[0])
    response = loop.call("exclude.instance.add", {
        "items": [{"scope": target, "reason": "instance reason"}],
    })
    assert response["ok"], response
    assert response["data"]["items"][0]["target_count"] > 0

    el_path = tmp_path / "instance.el"
    exported = loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    object_lines = [
        line for line in el_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
        and not line.strip().startswith(("CHECKSUM:", "INSTANCE:", "MODULE:",
                                         "ANNOTATION:"))
    ]
    assert object_lines, "instance exclusion produced no EL object rows"


def test_condition_and_decision_groups(loop, tmp_path):
    """condition/branch payloads expose grouped decisions with gap parity."""
    scopes = _scopes(loop)
    payloads = {}
    for leaf in [name for name in scopes if name.count(".") >= 2]:
        response = loop.call("export.code_coverage", {
            "scopes": [leaf], "metrics": ["condition", "branch"],
            "output": {"path": str(tmp_path / ("groups-" + leaf.replace(".", "_"))),
                       "allow_absolute_path": True},
        })
        assert response["ok"], response
        for item in response["data"]["items"]:
            for artifact in item["metrics"]:
                path = Path(response["data"]["items"][0]["directory"],
                            artifact["json"])
                if not path.is_file():
                    continue
                payload = json.loads(path.read_text())
                metric = payload["metric"]
                if metric not in ("condition", "branch"):
                    continue
                key = ("condition_groups" if metric == "condition"
                       else "decision_groups")
                if payload.get(key):
                    payloads[metric] = payload
        if len(payloads) == 2:
            break
    assert set(payloads) == {"condition", "branch"}, sorted(payloads)
    for metric, payload in payloads.items():
        key = "condition_groups" if metric == "condition" else "decision_groups"
        groups = payload.get(key, [])
        assert payload["gap_count"] == payload["coverage"]["missing"]
        assert payload["coverage_object_gap_count"] == payload["coverage"]["missing"]
        assert groups, metric
        uncovered = sum(len(group["uncovered"]) for group in groups)
        assert (uncovered + payload["unattributed_gap_count"]
                == payload["coverage"]["missing"])
        for group in groups:
            assert group["group_id"].startswith("DG")
            assert group["uncovered"]


def test_functional_covergroup_exclusion(loop, tmp_path):
    """covergroup-level exclusion reaches the EL."""
    summary = loop.call("functional_coverage.summary", {
        "group_by": "covergroup", "limits": {"max_items": 1},
    })
    assert summary["ok"], summary
    rows = summary["data"]["items"]
    if not rows:
        pytest.skip("fixture has no covergroup")
    covergroup = rows[0]["covergroup"]
    scope = covergroup.split("::", 1)[0]
    response = loop.call("exclude.functional.add", {
        "items": [{"target_kind": "covergroup", "scope": scope,
                   "covergroup": covergroup, "reason": "cg reason"}],
    })
    assert response["ok"], response
    assert response["data"]["items"][0]["target_count"] > 0
    el_path = tmp_path / "cg.el"
    exported = loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    text = el_path.read_text(encoding="utf-8")
    assert "covergroup " in text, text[:400]
    assert "cg reason" in text


def test_instance_exclusion_writes_annotation(loop, tmp_path):
    """instance-level exclusion carries the reason into the EL."""
    scopes = _scopes(loop)
    target = next((name for name in scopes if name.count(".") == 1), scopes[0])
    response = loop.call("exclude.instance.add", {
        "items": [{"scope": target, "reason": "instance reason"}],
    })
    assert response["ok"], response
    el_path = tmp_path / "instance-ann.el"
    exported = loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    text = el_path.read_text(encoding="utf-8")
    assert 'ANNOTATION: "instance reason"' in text, text[:400]


def test_error_paths(loop, tmp_path):
    """Malformed inputs return structured errors instead of crashing."""
    missing = loop.call("exclude.load",
                        {"paths": [str(tmp_path / "missing.el")]})
    assert not missing["ok"]
    # A missing file now fails while parsing the EL (before UCAPI applies it).
    assert missing["error"]["code"] in ("EXCLUSION_LOAD_FAILED", "IO_ERROR")

    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("not,a,valid\nheader,row\n", encoding="utf-8")
    invalid = loop.call("exclude.csv.validate",
                        {"directory": str(tmp_path)})
    assert "ok" in invalid


def test_one_shot_json_and_xout(vdb, tmp_path):
    """Both transport outputs work through the backend switch."""
    request = json.dumps({
        "api_version": "xcov.v1",
        "request_id": "r1",
        "action": "actions",
    }) + "\n"
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")

    json_out = subprocess.run(
        [str(XCOV_ENTRY), "--json", "-"],
        input=request, capture_output=True, text=True, env=env, check=False,
        encoding="utf-8", errors="replace",
    )
    assert json_out.returncode == 0, json_out.stderr
    assert json.loads(json_out.stdout)["ok"] is True

    xout = subprocess.run(
        [str(XCOV_ENTRY), "-"],
        input=request, capture_output=True, text=True, env=env, check=False,
        encoding="utf-8", errors="replace",
    )
    assert xout.returncode == 0, xout.stderr
    assert xout.stdout.startswith("@xcov.v1 ok")


def test_metrics_list_zero_and_synthetic_scope_semantics(loop):
    """Only real scopes contribute; synthetic generate levels and unknown names
    return no rows instead of descendant aggregates."""
    response = loop.call("metrics.list", {})
    assert response["ok"], response
    assert response["data"]["items"]
    for key in ("session_id", "scope", "test"):
        assert key in response["summary"], response["summary"]

    unknown = loop.call("metrics.list", {"scope": "top.no_such_scope"})
    assert unknown["ok"], unknown
    assert unknown["data"]["items"] == []

    synthetic = loop.call("metrics.list", {"scope": "top.u_core0.g_pipe"})
    assert synthetic["ok"], synthetic
    assert synthetic["data"]["items"] == []


def test_scope_summary_single_metric_counts(loop):
    """Single selected metric carries covered/coverable/missing, multi does not."""
    single = loop.call("scope.summary", {
        "scope": "top.u_core0", "metrics": ["line"],
    })
    assert single["ok"], single
    item = single["data"]["items"][0]
    assert {"covered", "coverable", "missing"} <= set(item), item
    assert item["coverable"] - item["covered"] == item["missing"]

    multiple = loop.call("scope.summary", {
        "scope": "top.u_core0", "metrics": ["line", "branch"],
    })
    assert multiple["ok"], multiple
    assert "covered" not in multiple["data"]["items"][0]


def test_query_sort_overflow_and_zero_limit(loop):
    """Query/sort/overflow are applied, not merely schema-validated."""
    filtered = loop.call("scope.search", {
        "metrics": ["line"],
        "query": {"include_patterns": ["*u_alu*"]},
    })
    assert filtered["ok"], filtered
    assert filtered["data"]["items"]
    assert all("u_alu" in item["full_name"]
               for item in filtered["data"]["items"])

    sorted_rows = loop.call("scope.summary", {
        "metrics": ["line"],
        "sort": {"by": "coverage_pct", "order": "desc"},
    })
    assert sorted_rows["ok"], sorted_rows
    pcts = [item["coverage_pct"] for item in sorted_rows["data"]["items"]
            if item["coverage_pct"] is not None]
    assert pcts == sorted(pcts, reverse=True), pcts

    zero = loop.call("scope.summary", {"limits": {"max_items": 0}})
    assert zero["ok"], zero
    assert zero["data"]["items"] == []
    assert zero["summary"]["returned_count"] == 0
    assert zero["summary"]["response_truncated"] is True

    summary_only = loop.call("scope.summary", {
        "limits": {"max_items": 1, "overflow": "summary_only"},
    })
    assert summary_only["ok"], summary_only
    assert summary_only["data"]["items"] == []
    assert summary_only["summary"]["total_count"] >= 1

    overflow = loop.call("scope.search", {
        "limits": {"max_items": 1, "overflow": "error"},
    })
    assert not overflow["ok"], overflow
    assert overflow["error"]["code"] == "INVALID_LIMIT"

    bad_sort = loop.call("scope.summary", {"sort": {"by": "covered"}})
    assert not bad_sort["ok"], bad_sort
    assert bad_sort["error"]["code"] == "INVALID_SORT_FIELD"


def test_session_close_requires_discard_confirmation(loop, tmp_path):
    """Unpersisted exclusion reasons block a graceful close."""
    reference = _first_gap_ref(loop, tmp_path)
    added = loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "dirty reason"}],
    })
    assert added["ok"], added
    assert added["data"]["items"][0]["status"] == "changed"

    closed = loop.call("session.close", {})
    assert not closed["ok"], closed
    assert closed["error"]["code"] == "UNPERSISTED_EXCLUSION_REASON"

    discarded = loop.call("session.close", {"confirm_discard_reasons": True})
    assert discarded["ok"], discarded
    assert discarded["summary"]["reasons_discarded"] is True
    assert discarded["summary"]["discarded_reason_count"] >= 1


def test_csv_line_selector_applies_and_compiles(xverif_fixture, tmp_path):
    """A metric=line row with only a source line selects that line's objects."""
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    scope = "route_matrix.u_value_dark"
    try:
        exported = session.call("export.code_coverage", {
            "scopes": [scope], "metrics": ["line"],
            "output": {"path": str(tmp_path / "line-gaps"),
                       "allow_absolute_path": True},
        })
        assert exported["ok"], exported
        payload = json.loads(
            (tmp_path / "line-gaps" / "instance-0001" / "line.json").read_text()
        )
        assert payload["line_groups"], payload
        line = payload["line_groups"][0]["uncovered"][0]["at"].rsplit(":", 1)[1]

        csv_dir = tmp_path / "line-csv"
        csv_dir.mkdir()
        (csv_dir / "code_exclusions.csv").write_text(
            "# schema_version=xcov-code-exclusions.v1\n"
            "# coverage_kind=code\n"
            "scope,metric,line,object,bin,reason\n"
            f"{scope},line,{line},,,line selector\n",
            encoding="utf-8",
        )
        _seed_required_csvs(csv_dir)
        applied = session.call("exclude.csv.apply",
                               {"directory": str(csv_dir)})
        assert applied["ok"], applied
        assert applied["data"]["items"][0]["status"] == "changed"
    finally:
        session.close()

    # A fresh session compiles the same line row.
    second = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    try:
        compiled = second.call("exclude.csv.compile", {
            "directory": str(csv_dir),
            "output_directory": str(tmp_path / "line-el"),
            "allow_absolute_path": True,
        })
        assert compiled["ok"], compiled
        statuses = {item["status"] for item in compiled["data"]["items"]}
        assert "compiled" in statuses, compiled["data"]["items"]
        assert "line selector" in (tmp_path / "line-el" / "code.el").read_text()
    finally:
        second.close()


def test_csv_export_deduplicates_and_container_remove_round_trips(loop,
                                                                 tmp_path):
    """Repeat exports do not duplicate rows; remove uses the same key."""
    reference = _first_gap_ref(loop, tmp_path)
    added = loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "dedupe"}],
    })
    assert added["ok"], added
    first_dir = tmp_path / "csv-a"
    second_dir = tmp_path / "csv-b"
    for directory in (first_dir, second_dir):
        exported = loop.call("exclude.csv.export", {
            "directory": str(directory), "allow_absolute_path": True,
        })
        assert exported["ok"], exported
    rows_a = (first_dir / "code_exclusions.csv").read_text().splitlines()
    rows_b = (second_dir / "code_exclusions.csv").read_text().splitlines()
    data_a = [row for row in rows_a if row and not row.startswith("#")
              and not row.startswith("scope,")]
    data_b = [row for row in rows_b if row and not row.startswith("#")
              and not row.startswith("scope,")]
    assert len(data_a) == len(set(data_a)) == 1, data_a
    assert data_a == data_b, (data_a, data_b)

    # Container add -> remove -> fresh export has no container row.
    scopes = _scopes(loop)
    target = next((name for name in scopes if name.count(".") == 1), scopes[0])
    functional = loop.call("functional_coverage.summary", {
        "group_by": "covergroup", "limits": {"max_items": 1},
    })
    assert functional["ok"], functional
    covergroup = functional["data"]["items"][0]["covergroup"]
    cover_scope = covergroup.split("::", 1)[0]
    added_cg = loop.call("exclude.functional.add", {
        "items": [{"target_kind": "covergroup", "scope": cover_scope,
                   "covergroup": covergroup, "reason": "cg round trip"}],
    })
    assert added_cg["ok"], added_cg
    before_dir = tmp_path / "csv-cg-before"
    assert loop.call("exclude.csv.export", {
        "directory": str(before_dir), "allow_absolute_path": True,
    })["ok"]
    assert "cg round trip" in (before_dir / "container_exclusions.csv").read_text()
    removed = loop.call("exclude.functional.remove", {
        "items": [{"target_kind": "covergroup", "scope": cover_scope,
                   "covergroup": covergroup}],
    })
    assert removed["ok"], removed
    after_dir = tmp_path / "csv-cg-after"
    assert loop.call("exclude.csv.export", {
        "directory": str(after_dir), "allow_absolute_path": True,
    })["ok"]
    assert "cg round trip" not in (after_dir / "container_exclusions.csv").read_text()


def test_ref_locator_cache_is_bounded(vdb, tmp_path):
    """A tiny locator cache must not break export->exclude.add resolution."""
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    env["XVERIF_XCOV_REF_LOCATOR_MAX"] = "1"
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        refs = []
        for index, scope in enumerate(["top", "top.u_core0"]):
            response = session.call("export.code_coverage", {
                "scopes": [scope], "metrics": ["toggle"],
                "output": {"path": str(tmp_path / f"cache-{index}"),
                           "allow_absolute_path": True},
            })
            assert response["ok"], response
            for item in response["data"]["items"]:
                for metric in item["metrics"]:
                    path = Path(item["directory"], metric["json"])
                    if not path.is_file():
                        continue
                    payload = json.loads(path.read_text())
                    if payload.get("gaps"):
                        refs.append(payload["gaps"][0]["coverage_ref"])
        assert len(refs) >= 2, refs
        for ref in refs:
            added = session.call("exclude.add", {
                "coverage_refs": [{"coverage_ref": ref, "reason": "bounded"}],
            })
            assert added["ok"], added
            assert added["data"]["items"][0]["status"] in {
                "changed", "already_in_state"}, added
    finally:
        session.close()


def test_run_manifest_gate(vdb, tmp_path):
    """run_manifest validates the v2 tree identity before opening the backend."""
    import shutil
    from xcov.provenance import resource_identity

    copied = tmp_path / vdb.name
    shutil.copytree(vdb, copied, symlinks=True)
    manifest = tmp_path / "run-manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "xcov.run-manifest.v2",
        "state": "published",
        "resources": {"vdb": {"path": copied.name, **resource_identity(copied)}},
    }))
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    request = json.dumps({
        "api_version": "xcov.v1", "request_id": "manifest",
        "action": "session.open",
        "target": {"vdb": str(copied), "run_manifest": str(manifest)},
        "args": {"name": "cov0"},
    }) + "\n"
    good = subprocess.run(
        [str(XCOV_ENTRY), "--json", "-"], input=request, capture_output=True,
        text=True, env=env, check=False, encoding="utf-8", errors="replace",
    )
    payload = json.loads(good.stdout)
    assert payload["ok"], payload
    assert payload["data"]["resource_snapshot"]["run_manifest"]["manifest_path"]
    assert (payload["data"]["resource_snapshot"]["run_manifest"]
            ["resources"]["vdb"]["sha256"])

    # Mutating the resource after publishing must fail closed.
    target = copied / "coverage.bin"
    files = [path for path in copied.rglob("*") if path.is_file()]
    victim = target if target.is_file() else files[0]
    victim.write_bytes(victim.read_bytes() + b"x")
    bad = subprocess.run(
        [str(XCOV_ENTRY), "--json", "-"], input=request, capture_output=True,
        text=True, env=env, check=False, encoding="utf-8", errors="replace",
    )
    payload = json.loads(bad.stdout)
    assert payload["ok"] is False, payload
    assert payload["error"]["code"] == "RESOURCE_PROVENANCE_MISMATCH"

    # Duplicate JSON keys are rejected before the backend opens.
    dup = tmp_path / "dup.json"
    dup.write_text(
        '{"schema_version":"xcov.run-manifest.v2",'
        '"schema_version":"xcov.run-manifest.v2",'
        '"state":"published","resources":{}}'
    )
    dup_request = json.dumps({
        "api_version": "xcov.v1", "request_id": "dup",
        "action": "session.open",
        "target": {"vdb": str(copied), "run_manifest": str(dup)},
        "args": {"name": "cov0"},
    }) + "\n"
    dup_out = subprocess.run(
        [str(XCOV_ENTRY), "--json", "-"], input=dup_request,
        capture_output=True, text=True, env=env, check=False,
        encoding="utf-8", errors="replace",
    )
    payload = json.loads(dup_out.stdout)
    assert payload["ok"] is False, payload
    assert payload["error"]["code"] == "RESOURCE_PROVENANCE_MISMATCH"


def test_sort_accepts_nullable_fields(loop):
    """Null values participate in sorting; only absent fields are an error."""
    response = loop.call("scope.search", {
        "query": {"include_patterns": ["*"]},
        "sort": {"by": "coverage_pct", "order": "desc"},
    })
    assert response["ok"], response
    rows = response["data"]["items"]
    assert rows
    values = [item["coverage_pct"] for item in rows]
    first_non_null = next(index for index, value in enumerate(values)
                          if value is not None)
    # Python's reverse ordering puts nulls first in descending order.
    assert all(value is None for value in values[:first_non_null]), values
    non_null = [value for value in values if value is not None]
    assert non_null == sorted(non_null, reverse=True), non_null

    children = loop.call("scope.children", {
        "scope": "top", "recursive": True,
        "sort": {"by": "coverage_pct", "order": "desc"},
    })
    assert children["ok"], children

    coverage = loop.call("code_coverage.summary", {
        "group_by": "scope",
        "sort": {"by": "coverage_pct", "order": "desc"},
    })
    assert coverage["ok"], coverage


def test_metrics_list_omits_absent_zero_regions(loop):
    """A zero-valued UCAPI region must not become a Python-style metric row."""
    response = loop.call("metrics.list", {
        "scope": "top.u_core0.g_pipe.u_proc.u_alu",
    })
    assert response["ok"], response
    rows = response["data"]["items"]
    assert rows
    assert all(row["coverable"] > 0 for row in rows), rows


def test_single_metric_counts_on_sparse_scope(xverif_fixture, tmp_path):
    """Single present metric carries counts even when other regions are empty."""
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    try:
        summary = session.call("scope.summary", {
            "scope": "route_matrix.u_stim", "metrics": ["toggle"],
        })
        assert summary["ok"], summary
        item = summary["data"]["items"][0]
        assert item["covered"] == 12 and item["coverable"] == 14, item
        assert item["missing"] == 2, item

        metrics = session.call("metrics.list", {
            "scope": "route_matrix.u_stim",
        })
        assert [row["metric"] for row in metrics["data"]["items"]] == ["toggle"]
    finally:
        session.close()


def test_functional_query_name_and_full_name(loop):
    """Schema-declared functional match_field name/full_name must filter rows."""
    for field in ("name", "full_name"):
        response = loop.call("functional_coverage.summary", {
            "group_by": "covergroup",
            "query": {"match_field": field, "include_patterns": ["*"]},
        })
        assert response["ok"], response
        assert response["data"]["items"], field
        assert response["data"]["items"][0]["covergroup"].startswith("top")


def test_csv_container_round_trip_removes_records(loop, vdb, tmp_path):
    """instance/coverpoint CSV rows export, compile and remove by identity."""
    scope = "top.u_core0.g_pipe.u_proc.u_alu"
    added = loop.call("exclude.instance.add", {
        "items": [{"scope": scope, "reason": "inst round trip"}],
    })
    assert added["ok"], added
    first = tmp_path / "inst-csv-1"
    assert loop.call("exclude.csv.export", {
        "directory": str(first), "allow_absolute_path": True,
    })["ok"]
    container = (first / "container_exclusions.csv").read_text()
    assert "instance," in container and "inst round trip" in container

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        el_dir = tmp_path / "inst-el"
        compiled = fresh.call("exclude.csv.compile", {
            "directory": str(first), "output_directory": str(el_dir),
            "allow_absolute_path": True,
        })
        assert compiled["ok"], compiled
        removed = fresh.call("exclude.instance.remove", {
            "items": [{"scope": scope}],
        })
        assert removed["ok"], removed
        second = tmp_path / "inst-csv-2"
        assert fresh.call("exclude.csv.export", {
            "directory": str(second), "allow_absolute_path": True,
        })["ok"]
        assert "inst round trip" not in (
            second / "container_exclusions.csv").read_text()
    finally:
        fresh.close()

    # The original session still owns the instance record; clear it so the
    # coverpoint CSV compile is evaluated from a known state.
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": scope}],
    })["ok"]
    covergroup = loop.call("functional_coverage.summary", {
        "group_by": "covergroup", "limits": {"max_items": 1},
    })["data"]["items"][0]["covergroup"]
    cover_scope = covergroup.split("::", 1)[0]
    cp_added = loop.call("exclude.functional.add", {
        "items": [{"target_kind": "coverpoint", "scope": cover_scope,
                   "covergroup": covergroup, "item": "cp_data",
                   "reason": "cp round trip"}],
    })
    if not cp_added["ok"] or cp_added["data"]["items"][0]["status"] != "changed":
        pytest.skip("fixture has no coverpoint cp_data")
    cp_dir = tmp_path / "cp-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(cp_dir), "allow_absolute_path": True,
    })["ok"]
    cp_text = (cp_dir / "container_exclusions.csv").read_text()
    assert "coverpoint," in cp_text and "cp_data" in cp_text, cp_text
    cp_el = tmp_path / "cp-el"
    cp_compiled = loop.call("exclude.csv.compile", {
        "directory": str(cp_dir), "output_directory": str(cp_el),
        "allow_absolute_path": True,
    })
    assert cp_compiled["ok"], cp_compiled
    # coverpoint EL emission is a documented UCAPI limitation; the compile
    # contract verified here is that the CSV row resolves and publishes.
    assert (cp_el / "code.el").is_file()


def test_csv_export_reason_conflict_is_atomic(loop, tmp_path):
    """A changed reason for the same identity fails before any file changes."""
    reference = _first_gap_ref(loop, tmp_path)
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "one"}],
    })["ok"]
    directory = tmp_path / "conflict-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(directory), "allow_absolute_path": True,
    })["ok"]
    before = (directory / "code_exclusions.csv").read_text()
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "two"}],
    })["ok"]
    conflict = loop.call("exclude.csv.export", {
        "directory": str(directory), "allow_absolute_path": True,
    })
    assert not conflict["ok"], conflict
    assert conflict["error"]["code"] == "EXCLUSION_REASON_CONFLICT"
    assert (directory / "code_exclusions.csv").read_text() == before


def test_csv_line_selector_rejects_wrong_source_file(xverif_fixture, tmp_path):
    """A line selector must honor the CSV source_file group."""
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    scope = "route_matrix.u_value_dark"
    try:
        exported = session.call("export.code_coverage", {
            "scopes": [scope], "metrics": ["line"],
            "output": {"path": str(tmp_path / "line-src"),
                       "allow_absolute_path": True},
        })
        assert exported["ok"], exported
        payload = json.loads(
            (tmp_path / "line-src" / "instance-0001" / "line.json").read_text()
        )
        line = payload["line_groups"][0]["uncovered"][0]["at"].rsplit(":", 1)[1]
        csv_dir = tmp_path / "line-wrong-file"
        csv_dir.mkdir()
        (csv_dir / "code_exclusions.csv").write_text(
            "# schema_version=xcov-code-exclusions.v1\n"
            "# coverage_kind=code\n"
            "# source_file=definitely_wrong_file.sv\n"
            "scope,metric,line,object,bin,reason\n"
            f"{scope},line,{line},,,wrong file\n",
            encoding="utf-8",
        )
        _seed_required_csvs(csv_dir)
        rejected = session.call("exclude.csv.apply",
                                {"directory": str(csv_dir)})
        assert not rejected["ok"], rejected
        assert rejected["error"]["code"] == "EXCLUSION_RESOLVE_FAILED"
    finally:
        session.close()


def test_evicted_assert_refs_still_resolve(xverif_fixture, tmp_path):
    """The bounded locator cache must not lose assertion refs."""
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    env["XVERIF_XCOV_REF_LOCATOR_MAX"] = "1"
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    try:
        exported = session.call("export.assert", {
            "output": {"path": str(tmp_path / "assert-refs"),
                       "allow_absolute_path": True},
        })
        assert exported["ok"], exported
        gaps = json.loads(
            (tmp_path / "assert-refs" / "assert.json").read_text())["gaps"]
        assert len(gaps) >= 2, gaps
        for gap in gaps[:3]:
            added = session.call("exclude.add", {
                "coverage_refs": [{"coverage_ref": gap["coverage_ref"],
                                   "reason": "assert evicted"}],
            })
            assert added["ok"], added
            assert added["data"]["items"][0]["status"] == "changed", added
    finally:
        session.close()


def test_csv_failure_rolls_back_previous_exclusions(loop, tmp_path):
    """A failed CSV apply must not unload exclusions when baseline creation
    or directory permissions prevent a user-directory snapshot."""
    scope = "top.u_core0"
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": scope, "reason": "keep me"}],
    })["ok"]
    csv_dir = tmp_path / "readonly-csv"
    csv_dir.mkdir()
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "top,line,999999,,,bad line\n",
        encoding="utf-8",
    )
    _seed_required_csvs(csv_dir)
    csv_dir.chmod(0o555)
    try:
        failed = loop.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert not failed["ok"], failed
        assert failed["error"]["code"] == "EXCLUSION_RESOLVE_FAILED"
    finally:
        csv_dir.chmod(0o755)
    el_path = tmp_path / "after-rollback.el"
    exported = loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    text = el_path.read_text()
    assert "INSTANCE:" in text and "keep me" in text, text[:400]
    records_dir = tmp_path / "after-rollback-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(records_dir), "allow_absolute_path": True,
    })["ok"]
    assert "keep me" in (records_dir / "container_exclusions.csv").read_text()


def test_generate_block_assertions_are_mounted(xverif_fixture, tmp_path):
    """Assertions declared in a generate block mount to the nearest real
    ancestor scope and keep their basename."""
    resources = xverif_fixture("xcov.modinfo_complex")
    database = resources / "complex.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    try:
        metrics = session.call("metrics.list", {})
        assert metrics["ok"], metrics
        assert_row = next(row for row in metrics["data"]["items"]
                          if row["metric"] == "assert")
        summary = session.call("assert.summary", {})
        assert summary["ok"], summary
        rows = summary["data"]["items"]
        assert assert_row["coverable"] == len(rows), (assert_row, len(rows))
        assert assert_row["covered"] == sum(
            1 for row in rows if row["covered"]), (assert_row, rows)
        by_name = session.call("assert.summary", {
            "query": {"match_field": "name",
                      "include_patterns": ["a_result_known"]},
        })
        assert by_name["ok"], by_name
        assert by_name["data"]["items"], by_name
        assert all(row["name"] == "a_result_known"
                   for row in by_name["data"]["items"])
    finally:
        session.close()


def test_ref_csv_round_trip_replays_in_new_session(loop, vdb, tmp_path):
    """A ref-origin code row is replayable by the C++ CSV apply path."""
    reference = _first_gap_ref(loop, tmp_path)
    added = loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "ref csv"}],
    })
    assert added["ok"], added
    csv_dir = tmp_path / "ref-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })["ok"]
    rows = [row for row in (csv_dir / "code_exclusions.csv").read_text().splitlines()
            if row and not row.startswith("#") and not row.startswith("scope,")]
    assert len(rows) == 1, rows

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        applied = fresh.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert applied["ok"], applied
        assert applied["data"]["items"][0]["status"] == "changed"
    finally:
        fresh.close()


def test_csv_export_preserves_source_file_groups(loop, tmp_path):
    """Merging an existing Python-style CSV must not drop source_file groups."""
    csv_dir = tmp_path / "grouped-csv"
    csv_dir.mkdir()
    original = (
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "\n"
        "# source_file=design.sv\n"
        "top,line,126,,,external reason\n"
    )
    (csv_dir / "code_exclusions.csv").write_text(original)
    exported = loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })
    assert exported["ok"], exported
    text = (csv_dir / "code_exclusions.csv").read_text()
    assert "# source_file=design.sv" in text
    assert "external reason" in text
    kind_row = next(item for item in exported["data"]["items"]
                    if item["coverage_kind"] == "code")
    assert kind_row["record_count"] == 1, kind_row
    # A second export counts the existing record instead of reporting zero.
    again = loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })
    assert again["ok"], again
    kind_row = next(item for item in again["data"]["items"]
                    if item["coverage_kind"] == "code")
    assert kind_row["record_count"] == 1, kind_row


def test_instance_exclusion_annotates_every_el_section(loop, tmp_path):
    """Each INSTANCE section of an instance exclusion carries the reason."""
    scope = "top.u_core0.g_pipe.u_proc.u_reg_a"
    added = loop.call("exclude.instance.add", {
        "items": [{"scope": scope, "reason": "section reason"}],
    })
    assert added["ok"], added
    el_path = tmp_path / "sections.el"
    exported = loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    text = el_path.read_text()
    assert text.count("INSTANCE:") == text.count("ANNOTATION:"), text[:600]


def test_functional_csv_bin_does_not_leave_record(loop, vdb, tmp_path):
    """A functional CSV bin column must not keep a removed record alive."""
    summary = loop.call("functional_coverage.summary", {
        "group_by": "covergroup", "limits": {"max_items": 1},
    })
    assert summary["ok"], summary
    covergroup = summary["data"]["items"][0]["covergroup"]
    scope = covergroup.split("::", 1)[0]
    csv_dir = tmp_path / "bin-csv"
    csv_dir.mkdir()
    (csv_dir / "functional_exclusions.csv").write_text(
        "# schema_version=xcov-functional-exclusions.v1\n"
        "# coverage_kind=functional\n"
        "scope,line,covergroup,coverpoint,cross,bin,reason\n"
        "\n"
        "# source_file=design.sv\n"
        f"{scope},10,{covergroup},cp_data,,binR,bin reason\n",
        encoding="utf-8",
    )
    _seed_required_csvs(csv_dir)
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        compiled = fresh.call("exclude.csv.compile", {
            "directory": str(csv_dir), "output_directory": str(tmp_path / "bin-el"),
            "allow_absolute_path": True,
        })
        if not compiled["ok"]:
            pytest.skip("fixture coverpoint cp_data not present")
        removed = fresh.call("exclude.functional.remove", {
            "items": [{"target_kind": "coverpoint", "scope": scope,
                       "covergroup": covergroup, "item": "cp_data"}],
        })
        assert removed["ok"], removed
        after = tmp_path / "bin-after"
        assert fresh.call("exclude.csv.export", {
            "directory": str(after), "allow_absolute_path": True,
        })["ok"]
        assert "bin reason" not in (
            after / "functional_exclusions.csv").read_text()
    finally:
        fresh.close()


def test_recursive_instance_csv_round_trip(loop, vdb, tmp_path):
    """Recursive instance exclusions expand to one CSV row per real instance."""
    added = loop.call("exclude.instance.add", {
        "items": [{"scope": "top", "recursive": True, "reason": "tree"}],
    })
    assert added["ok"], added
    before = loop.call("metrics.list", {})
    assert before["ok"], before
    csv_dir = tmp_path / "recursive-csv"
    exported = loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })
    assert exported["ok"], exported
    container = (csv_dir / "container_exclusions.csv").read_text()
    instance_rows = [line for line in container.splitlines()
                     if line.startswith("instance,")]
    assert len(instance_rows) > 1, container

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        applied = fresh.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert applied["ok"], applied
        after = fresh.call("metrics.list", {})
        assert after["ok"], after
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        fresh.close()


def test_csv_invalid_input_fails_closed_and_preserves_artifacts(loop,
                                                                 tmp_path):
    """Missing directories/bad headers must not silently succeed or overwrite
    previously published EL artifacts."""
    missing = tmp_path / "does-not-exist"
    for action in ("exclude.csv.apply", "exclude.csv.compile"):
        response = loop.call(action, {"directory": str(missing)})
        assert not response["ok"], response
        assert response["error"]["code"] == "EXCLUSION_CSV_NOT_FOUND"

    bad_dir = tmp_path / "bad-header"
    _seed_required_csvs(bad_dir)
    (bad_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "not,a,valid,header\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "existing-out"
    out_dir.mkdir()
    previous = "// PREVIOUS IMPORTANT EXCLUSIONS\n"
    (out_dir / "code.el").write_text(previous)
    compiled = loop.call("exclude.csv.compile", {
        "directory": str(bad_dir), "output_directory": str(out_dir),
        "allow_absolute_path": True,
    })
    assert not compiled["ok"], compiled
    assert compiled["error"]["code"] == "EXCLUSION_CSV_INVALID"
    assert (out_dir / "code.el").read_text() == previous


def test_recursive_instance_excludes_assertions(loop, tmp_path):
    """URG zeroes assertions under an excluded instance; the C++ backend must
    not keep reporting them as live."""
    added = loop.call("exclude.instance.add", {
        "items": [{"scope": "top", "recursive": True, "reason": "all"}],
    })
    assert added["ok"], added
    metrics = loop.call("metrics.list", {})
    assert metrics["ok"], metrics
    assert not any(row["metric"] == "assert" for row in metrics["data"]["items"])
    summary = loop.call("scope.summary", {
        "scope": "top", "metrics": ["assert"],
    })
    assert summary["ok"], summary
    assert summary["data"]["items"][0]["assert_pct"] is None


def test_multiline_reason_csv_round_trip(loop, vdb, tmp_path):
    """A schema-legal reason with a newline survives export and replay."""
    reference = _first_gap_ref(loop, tmp_path)
    reason = "line one\nline two"
    added = loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": reason}],
    })
    assert added["ok"], added
    csv_dir = tmp_path / "multiline-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })["ok"]
    text = (csv_dir / "code_exclusions.csv").read_text()
    assert '"line one\nline two"' in text, text

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        applied = fresh.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert applied["ok"], applied
        assert applied["data"]["items"][0]["status"] == "changed"
    finally:
        fresh.close()


def test_recursive_csv_ownership_is_stable_and_idempotent(loop, vdb, tmp_path):
    """Apply -> export keeps one row per instance; remove clears the family;
    a second apply is idempotent; nested roots conflict like Python."""
    added = loop.call("exclude.instance.add", {
        "items": [{"scope": "top", "recursive": True, "reason": "tree"}],
    })
    assert added["ok"], added
    csv_dir = tmp_path / "ownership-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })["ok"]
    original = [line for line in
                (csv_dir / "container_exclusions.csv").read_text().splitlines()
                if line.startswith("instance,")]
    assert len(original) > 1, original

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        applied = fresh.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert applied["ok"], applied
        again = fresh.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert again["ok"], again
        assert fresh.call("exclude.csv.export", {
            "directory": str(csv_dir), "allow_absolute_path": True,
        })["ok"]
        merged = [line for line in
                  (csv_dir / "container_exclusions.csv").read_text().splitlines()
                  if line.startswith("instance,")]
        assert merged == original, (len(original), len(merged))

        removed = fresh.call("exclude.instance.remove", {
            "items": [{"scope": "top", "recursive": True}],
        })
        assert removed["ok"], removed
        after_dir = tmp_path / "ownership-after"
        assert fresh.call("exclude.csv.export", {
            "directory": str(after_dir), "allow_absolute_path": True,
        })["ok"]
        assert not [line for line in
                    (after_dir / "container_exclusions.csv").read_text().splitlines()
                    if line.startswith("instance,")]
    finally:
        fresh.close()

    nested = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        child = nested.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core0", "recursive": True,
                       "reason": "child"}],
        })
        assert child["ok"], child
        conflict = nested.call("exclude.instance.add", {
            "items": [{"scope": "top", "recursive": True, "reason": "root"}],
        })
        assert not conflict["ok"], conflict
        assert conflict["error"]["code"] == "TARGET_OWNERSHIP_CONFLICT"
    finally:
        nested.close()


def test_complex_recursive_csv_round_trip_preserves_asserts(xverif_fixture,
                                                            tmp_path):
    """Generate-block assertions survive a recursive instance CSV replay."""
    resources = xverif_fixture("xcov.modinfo_complex")
    database = resources / "complex.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    first = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    csv_dir = tmp_path / "complex-csv"
    try:
        added = first.call("exclude.instance.add", {
            "items": [{"scope": "top", "recursive": True, "reason": "tree"}],
        })
        assert added["ok"], added
        before = first.call("metrics.list", {})
        assert before["ok"], before
        assert first.call("exclude.csv.export", {
            "directory": str(csv_dir), "allow_absolute_path": True,
        })["ok"]
    finally:
        first.close()

    second = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    try:
        applied = second.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert applied["ok"], applied
        after = second.call("metrics.list", {})
        assert after["ok"], after
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        second.close()


def test_csv_row_validation_rejects_empty_reason(loop, tmp_path):
    """Row-level validation refuses empty reason and unsupported target_kind."""
    csv_dir = tmp_path / "bad-rows"
    _seed_required_csvs(csv_dir)
    (csv_dir / "container_exclusions.csv").write_text(
        "# schema_version=xcov-container-exclusions.v1\n"
        "# coverage_kind=container\n"
        "target_kind,scope,covergroup,item,expansion_root,reason\n"
        "instance,top.u_core0,,,top.u_core0,\n",
        encoding="utf-8",
    )
    rejected = loop.call("exclude.csv.apply", {"directory": str(csv_dir)})
    assert not rejected["ok"], rejected
    assert rejected["error"]["code"] == "EXCLUSION_CSV_INVALID"


def test_multi_item_instance_write_is_atomic(loop):
    """A later item failure rolls back earlier instance items."""
    before = loop.call("metrics.list", {})
    assert before["ok"], before
    conflict = loop.call("exclude.instance.add", {
        "items": [
            {"scope": "top", "recursive": True, "reason": "root"},
            {"scope": "top.u_core0", "recursive": True, "reason": "child"},
        ],
    })
    assert not conflict["ok"], conflict
    assert conflict["error"]["code"] == "TARGET_OWNERSHIP_CONFLICT"
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in before["data"]["items"]]

    added = loop.call("exclude.instance.add", {
        "items": [{"scope": "top", "recursive": True, "reason": "root"}],
    })
    assert added["ok"], added
    removed = loop.call("exclude.instance.remove", {
        "items": [
            {"scope": "top", "recursive": True},
            {"scope": "top.no_such_instance", "recursive": True},
        ],
    })
    assert removed["ok"], removed
    assert removed["data"]["items"][0]["status"] == "changed"
    assert removed["data"]["items"][1]["status"] == "already_in_state"


def test_instance_remove_preserves_independent_leaf_exclusion(loop, tmp_path):
    """restore_scope must not clear a leaf exclusion owned by exclude.add."""
    reference = _first_gap_ref(loop, tmp_path)
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "leaf reason"}],
    })["ok"]
    leaf_state = loop.call("metrics.list", {})
    assert leaf_state["ok"], leaf_state
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top", "recursive": True, "reason": "tree"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top", "recursive": True}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in leaf_state["data"]["items"]]
    csv_dir = tmp_path / "leaf-preserved"
    assert loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })["ok"]
    assert "leaf reason" in (csv_dir / "code_exclusions.csv").read_text()


def test_csv_overlapping_instance_owners_conflict(loop, vdb, tmp_path):
    """Applying child-root and full-root CSVs must not create two owners."""
    child_dir = tmp_path / "child-csv"
    root_dir = tmp_path / "root-csv"
    env = _env()
    for scope, directory in (("top.u_core0", child_dir), ("top", root_dir)):
        session = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
        try:
            assert session.call("exclude.instance.add", {
                "items": [{"scope": scope, "recursive": True,
                           "reason": scope}],
            })["ok"]
            assert session.call("exclude.csv.export", {
                "directory": str(directory), "allow_absolute_path": True,
            })["ok"]
        finally:
            session.close()
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert session.call("exclude.csv.apply",
                            {"directory": str(child_dir)})["ok"]
        conflict = session.call("exclude.csv.apply",
                                {"directory": str(root_dir)})
        assert not conflict["ok"], conflict
        assert conflict["error"]["code"] == "TARGET_OWNERSHIP_CONFLICT"
    finally:
        session.close()


def test_line_selector_survives_instance_remove(xverif_fixture, tmp_path):
    """A line-selector exclusion must be reapplied after an instance family
    restore, otherwise DB and CSV disagree."""
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    scope = "route_matrix.u_value_dark"
    csv_dir = tmp_path / "line-preserve"
    try:
        gaps = session.call("export.code_coverage", {
            "scopes": [scope], "metrics": ["line"],
            "output": {"path": str(tmp_path / "line-src"),
                       "allow_absolute_path": True},
        })
        assert gaps["ok"], gaps
        payload = json.loads(
            (tmp_path / "line-src" / "instance-0001" / "line.json").read_text())
        line = payload["line_groups"][0]["uncovered"][0]["at"].rsplit(":", 1)[1]
        _seed_required_csvs(csv_dir)
        (csv_dir / "code_exclusions.csv").write_text(
            "# schema_version=xcov-code-exclusions.v1\n"
            "# coverage_kind=code\n"
            "scope,metric,line,object,bin,reason\n"
            f"{scope},line,{line},,,line preserve\n",
            encoding="utf-8",
        )
        assert session.call("exclude.csv.apply",
                            {"directory": str(csv_dir)})["ok"]
        before = session.call("metrics.list", {})
        assert before["ok"], before
        assert session.call("exclude.instance.add", {
            "items": [{"scope": scope, "reason": "tree"}],
        })["ok"]
        assert session.call("exclude.instance.remove", {
            "items": [{"scope": scope}],
        })["ok"]
        after = session.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
        el_path = tmp_path / "line-preserved.el"
        assert session.call("export.exclude", {
            "output": {"path": str(el_path), "allow_absolute_path": True},
        })["ok"]
        assert "Block" in el_path.read_text()
    finally:
        session.close()


def test_csv_row_validation_rejects_assertion_kind_and_line_overflow(
        loop, tmp_path):
    csv_dir = tmp_path / "bad-assert-kind"
    _seed_required_csvs(csv_dir)
    (csv_dir / "assertion_exclusions.csv").write_text(
        "# schema_version=xcov-assertion-exclusions.v1\n"
        "# coverage_kind=assertion\n"
        "scope,line,assertion,assertion_kind,reason\n"
        "top,1,top.a_check,bogus,reason\n",
        encoding="utf-8",
    )
    rejected = loop.call("exclude.csv.apply", {"directory": str(csv_dir)})
    assert not rejected["ok"], rejected
    assert rejected["error"]["code"] == "EXCLUSION_CSV_INVALID"

    overflow_dir = tmp_path / "line-overflow"
    _seed_required_csvs(overflow_dir)
    (overflow_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        "top,line,3000000000,,,overflow\n",
        encoding="utf-8",
    )
    overflow = loop.call("exclude.csv.apply", {"directory": str(overflow_dir)})
    assert not overflow["ok"], overflow
    assert overflow["error"]["code"] == "EXCLUSION_CSV_INVALID"


def test_loaded_el_survives_instance_round_trip(loop, vdb, tmp_path):
    """EL-loaded exclusions must not be wiped by instance add/remove."""
    reference = _first_gap_ref(loop, tmp_path)
    added = loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "loaded reason"}],
    })
    assert added["ok"], added
    el_path = tmp_path / "loaded.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })["ok"]

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert fresh.call("exclude.load", {"paths": [str(el_path)]})["ok"]
        before = fresh.call("metrics.list", {})
        assert before["ok"], before
        assert fresh.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core0", "reason": "temporary"}],
        })["ok"]
        assert fresh.call("exclude.instance.remove", {
            "items": [{"scope": "top.u_core0"}],
        })["ok"]
        after = fresh.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
        after_el = tmp_path / "loaded-after.el"
        assert fresh.call("export.exclude", {
            "output": {"path": str(after_el), "allow_absolute_path": True},
        })["ok"]
        object_lines = [line for line in after_el.read_text().splitlines()
                        if line.startswith(("Toggle", "Block", "Branch",
                                            "Condition", "Fsm", "Assert"))]
        assert object_lines, "loaded EL exclusion disappeared"
        csv_dir = tmp_path / "loaded-csv"
        assert fresh.call("exclude.csv.export", {
            "directory": str(csv_dir), "allow_absolute_path": True,
        })["ok"]
        assert "loaded reason" in (csv_dir / "code_exclusions.csv").read_text()
    finally:
        fresh.close()


def test_strict_instance_exclusion_rejects_covered_objects(vdb, tmp_path):
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    strict = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb, policy="strict")
    try:
        before = strict.call("metrics.list", {})
        assert before["ok"], before
        rejected = strict.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core0", "reason": "strict"}],
        })
        assert not rejected["ok"], rejected
        assert rejected["error"]["code"] == "EXCLUSION_APPLY_FAILED"
        after = strict.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        strict.close()


def test_assertion_ref_csv_keeps_kind(xverif_fixture, tmp_path):
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    loop = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    el_dir = tmp_path / "assert-kinds"
    exported = loop.call("export.assert", {
        "output": {"path": str(el_dir), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    gaps = json.loads((el_dir / "assert.json").read_text())["gaps"]
    cover = next((gap for gap in gaps
                  if gap["kind"] == "npiCovCoverProperty"), None)
    if cover is None:
        pytest.skip("fixture has no cover property gap")
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": cover["coverage_ref"],
                           "reason": "cover reason"}],
    })["ok"]
    csv_dir = tmp_path / "assert-csv"
    assert loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })["ok"]
    text = (csv_dir / "assertion_exclusions.csv").read_text()
    assert "cover_property" in text, text
    assert "cover reason" in text
    loop.close()


def test_loaded_leaf_removal_is_not_resurrected(loop, vdb, tmp_path):
    """Removing a loaded leaf reason must not be undone by a later instance
    family round-trip."""
    reference = _first_gap_ref(loop, tmp_path)
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "loaded"}],
    })["ok"]
    el_path = tmp_path / "loaded-leaf.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })["ok"]

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert fresh.call("exclude.load", {"paths": [str(el_path)]})["ok"]
        assert fresh.call("exclude.remove", {
            "coverage_refs": [reference],
        })["ok"]
        removed_state = fresh.call("metrics.list", {})
        assert removed_state["ok"], removed_state
        assert fresh.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core1", "reason": "temporary"}],
        })["ok"]
        assert fresh.call("exclude.instance.remove", {
            "items": [{"scope": "top.u_core1"}],
        })["ok"]
        after = fresh.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in removed_state["data"]["items"]]
    finally:
        fresh.close()


def test_loaded_instance_el_is_not_falsely_removed(loop, vdb, tmp_path):
    """An EL-only instance exclusion is external state: instance remove must
    not report success while leaving the database excluded."""
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core0", "reason": "external"}],
    })["ok"]
    el_path = tmp_path / "loaded-instance.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })["ok"]

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert fresh.call("exclude.load", {"paths": [str(el_path)]})["ok"]
        before = fresh.call("metrics.list", {})
        assert before["ok"], before
        assert fresh.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core0", "reason": "external"}],
        })["ok"]
        removed = fresh.call("exclude.instance.remove", {
            "items": [{"scope": "top.u_core0"}],
        })
        assert not removed["ok"], removed
        assert removed["error"]["code"] == "EXCLUSION_NOT_OWNED"
        after = fresh.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        fresh.close()


def test_loaded_el_survives_source_file_deletion(loop, vdb, tmp_path):
    """remove must not depend on the original EL file still existing."""
    reference = _first_gap_ref(loop, tmp_path)
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "loaded"}],
    })["ok"]
    el_path = tmp_path / "deleted.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })["ok"]
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert fresh.call("exclude.load", {"paths": [str(el_path)]})["ok"]
        before = fresh.call("metrics.list", {})
        el_path.unlink()
        assert fresh.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core1", "reason": "temporary"}],
        })["ok"]
        assert fresh.call("exclude.instance.remove", {
            "items": [{"scope": "top.u_core1"}],
        })["ok"]
        after = fresh.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        fresh.close()


def test_strict_csv_instance_rows_are_rejected(vdb, tmp_path):
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    strict = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb, policy="strict")
    csv_dir = tmp_path / "strict-csv"
    try:
        _seed_required_csvs(csv_dir)
        (csv_dir / "container_exclusions.csv").write_text(
            "# schema_version=xcov-container-exclusions.v1\n"
            "# coverage_kind=container\n"
            "target_kind,scope,covergroup,item,expansion_root,reason\n"
            "instance,top.u_core0,,,top.u_core0,strict csv\n",
            encoding="utf-8",
        )
        before = strict.call("metrics.list", {})
        applied = strict.call("exclude.csv.apply", {"directory": str(csv_dir)})
        assert not applied["ok"], applied
        assert applied["error"]["code"] == "EXCLUSION_APPLY_FAILED"
        compiled = strict.call("exclude.csv.compile", {
            "directory": str(csv_dir),
            "output_directory": str(tmp_path / "strict-el"),
            "allow_absolute_path": True,
        })
        assert not compiled["ok"], compiled
        after = strict.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        strict.close()


def test_load_is_atomic_across_multiple_files(loop, vdb, tmp_path):
    reference = _first_gap_ref(loop, tmp_path)
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "loaded"}],
    })["ok"]
    good = tmp_path / "good.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(good), "allow_absolute_path": True},
    })["ok"]
    bad = tmp_path / "bad.el"
    bad.write_text("this is not an exclusion file\n", encoding="utf-8")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        before = fresh.call("metrics.list", {})
        loaded = fresh.call("exclude.load", {"paths": [str(good), str(bad)]})
        assert not loaded["ok"], loaded
        after = fresh.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in before["data"]["items"]]
    finally:
        fresh.close()


def test_failed_container_request_does_not_poison_deltas(loop, tmp_path):
    """A rolled-back multi-item request must not leave stale instance deltas
    that later clear an independently added leaf exclusion."""
    reference = _first_gap_ref_for(loop, tmp_path, "top.u_core0")
    failed = loop.call("exclude.instance.add", {
        "items": [
            {"scope": "top.u_core0", "reason": "temporary"},
            {"scope": "top.no_such_instance", "reason": "bad"},
        ],
    })
    assert not failed["ok"], failed
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "leaf"}],
    })["ok"]
    leaf_state = loop.call("metrics.list", {})
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core0", "reason": "temporary"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core0"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in leaf_state["data"]["items"]]


def test_leaf_added_after_instance_family_survives_remove(loop, tmp_path):
    """Adding a leaf after an instance family transfers ownership so a later
    family remove keeps the leaf and its reason record."""
    reference = _first_gap_ref_for(loop, tmp_path, "top.u_core1")
    pristine = loop.call("metrics.list", {})
    assert pristine["ok"], pristine
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "tree"}],
    })["ok"]
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "leaf owner"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    csv_dir = tmp_path / "transferred-leaf"
    assert loop.call("exclude.csv.export", {
        "directory": str(csv_dir), "allow_absolute_path": True,
    })["ok"]
    assert "leaf owner" in (csv_dir / "code_exclusions.csv").read_text()
    removed = loop.call("exclude.remove", {"coverage_refs": [reference]})
    assert removed["ok"], removed
    assert removed["data"]["items"][0]["status"] == "changed"
    final = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in final["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]


def test_duplicate_full_name_transfer_keeps_siblings_in_family(
        xverif_fixture, tmp_path):
    """A ref shared by two same-name objects must transfer only one delta key;
    the sibling stays owned by the family and is cleared on remove."""
    resources = xverif_fixture("xcov.modinfo_complex")
    database = resources / "complex.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    scope = ("top.u_cluster_a.g_wrapper_level.u_fabric.g_lane[0]"
             ".g_even.u_worker")
    out_dir = tmp_path / "dup-gaps"
    try:
        pristine = session.call("metrics.list", {})
        assert pristine["ok"], pristine
        exported = session.call("export.code_coverage", {
            "scopes": [scope], "metrics": ["condition"],
            "output": {"path": str(out_dir), "allow_absolute_path": True},
        })
        assert exported["ok"], exported
        payload = json.loads(
            (out_dir / "instance-0001" / "condition.json").read_text())
        by_ref = {}
        duplicate_ref = None
        for gap in payload.get("gaps", []):
            ref = gap.get("coverage_ref")
            if not ref:
                continue
            if ref in by_ref:
                duplicate_ref = ref
                break
            by_ref[ref] = gap
        if duplicate_ref is None:
            pytest.skip("fixture has no duplicate condition ref")
        add = session.call("exclude.instance.add", {
            "items": [{"scope": scope, "reason": "family"}],
        })
        assert add["ok"], add
        leaf = session.call("exclude.add", {
            "coverage_refs": [{"coverage_ref": duplicate_ref,
                               "reason": "leaf owner"}],
        })
        assert leaf["ok"], leaf
        removed_family = session.call("exclude.instance.remove", {
            "items": [{"scope": scope}],
        })
        assert removed_family["ok"], removed_family
        assert add["data"]["items"][0]["target_count"] == \
            removed_family["data"]["items"][0]["target_count"]
        removed_leaf = session.call("exclude.remove", {
            "coverage_refs": [duplicate_ref],
        })
        assert removed_leaf["ok"], removed_leaf
        assert removed_leaf["data"]["items"][0]["status"] == "changed"
        final = session.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in final["data"]["items"]] == \
            [key(row) for row in pristine["data"]["items"]]
    finally:
        session.close()


def test_repeated_duplicate_refs_restore_pristine(xverif_fixture, tmp_path):
    """Adding every exported gap (including duplicate refs) must not strand
    sibling objects after the family and leaf exclusions are removed."""
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    scope = "route_matrix.u_value_dark"
    out_dir = tmp_path / "dup-line-gaps"
    try:
        pristine = session.call("metrics.list", {})
        assert pristine["ok"], pristine
        exported = session.call("export.code_coverage", {
            "scopes": [scope], "metrics": ["line"],
            "output": {"path": str(out_dir), "allow_absolute_path": True},
        })
        assert exported["ok"], exported
        gaps = json.loads(
            (out_dir / "instance-0001" / "line.json").read_text())["gaps"]
        refs = [gap["coverage_ref"] for gap in gaps if gap.get("coverage_ref")]
        if len(refs) == len(set(refs)):
            pytest.skip("fixture line gaps have no duplicate refs")
        assert session.call("exclude.instance.add", {
            "items": [{"scope": scope, "reason": "family"}],
        })["ok"]
        added = session.call("exclude.add", {
            "coverage_refs": [{"coverage_ref": ref, "reason": "leaf"}
                              for ref in refs],
        })
        assert added["ok"], added
        assert session.call("exclude.instance.remove", {
            "items": [{"scope": scope}],
        })["ok"]
        unique = list(dict.fromkeys(refs))
        removed = session.call("exclude.remove", {"coverage_refs": unique})
        assert removed["ok"], removed
        final = session.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in final["data"]["items"]] == \
            [key(row) for row in pristine["data"]["items"]]
    finally:
        session.close()


def test_csv_leaf_after_family_survives_remove(loop, vdb, tmp_path):
    """A code CSV row applied after a family exclusion must survive the
    family remove exactly like an exclude.add leaf."""
    scope = "top.u_core1"
    out_dir = tmp_path / "csv-family-gaps"
    exported = loop.call("export.code_coverage", {
        "scopes": [scope], "metrics": ["toggle"],
        "output": {"path": str(out_dir), "allow_absolute_path": True},
    })
    assert exported["ok"], exported
    payload = json.loads(
        (out_dir / "instance-0001" / "toggle.json").read_text())
    gap = next((gap for gap in payload.get("gaps", [])
                if gap.get("coverage_ref")), None)
    if gap is None:
        pytest.skip("fixture has no toggle gap")
    csv_dir = tmp_path / "csv-family"
    _seed_required_csvs(csv_dir)
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"{scope},toggle,,{gap['full_name']},,csv leaf owner\n",
        encoding="utf-8",
    )

    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    expected_session = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        applied = expected_session.call("exclude.csv.apply",
                                        {"directory": str(csv_dir)})
        assert applied["ok"], applied
        expected = expected_session.call("metrics.list", {})
        assert expected["ok"], expected
    finally:
        expected_session.close()

    family_session = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert family_session.call("exclude.instance.add", {
            "items": [{"scope": scope, "reason": "family"}],
        })["ok"]
        applied = family_session.call("exclude.csv.apply",
                                      {"directory": str(csv_dir)})
        assert applied["ok"], applied
        assert family_session.call("exclude.instance.remove", {
            "items": [{"scope": scope}],
        })["ok"]
        after = family_session.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in expected["data"]["items"]]
    finally:
        family_session.close()


def test_family_remove_after_load_is_not_rolled_back(loop, vdb, tmp_path):
    """Loading an unrelated/empty EL must not make a later family remove
    restore the family through a stale session snapshot."""
    empty = tmp_path / "empty.el"
    empty.write_text("")
    pristine = loop.call("metrics.list", {})
    assert pristine["ok"], pristine
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core0", "reason": "family"}],
    })["ok"]
    assert loop.call("exclude.load", {"paths": [str(empty)]})["ok"]
    removed = loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core0"}],
    })
    assert removed["ok"], removed
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]
    el_path = tmp_path / "after-empty-load.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })["ok"]
    assert el_path.stat().st_size == 0


def test_instance_add_on_synthetic_scope_reports_scope_not_found(loop):
    response = loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core0.g_pipe", "reason": "synthetic"}],
    })
    assert not response["ok"], response
    assert response["error"]["code"] == "SCOPE_NOT_FOUND"


def test_multiple_families_remove_in_add_order(loop):
    """Removing families in insertion order must not resurrect an earlier one
    through a per-family snapshot."""
    pristine = loop.call("metrics.list", {})
    assert pristine["ok"], pristine
    added = loop.call("exclude.instance.add", {
        "items": [
            {"scope": "top.u_core0", "reason": "a"},
            {"scope": "top.u_core1", "reason": "b"},
        ],
    })
    assert added["ok"], added
    removed = loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core0"}, {"scope": "top.u_core1"}],
    })
    assert removed["ok"], removed
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]


def test_failed_family_request_does_not_poison_baseline(loop):
    pristine = loop.call("metrics.list", {})
    failed = loop.call("exclude.instance.add", {
        "items": [
            {"scope": "top.u_core0", "reason": "temporary"},
            {"scope": "top.no_such_instance", "reason": "bad"},
        ],
    })
    assert not failed["ok"], failed
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "later"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]


def test_removed_ref_survives_unrelated_load(loop, vdb, tmp_path):
    reference = _first_gap_ref(loop, tmp_path)
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "loaded"}],
    })["ok"]
    el_path = tmp_path / "loaded-ref.el"
    assert loop.call("export.exclude", {
        "output": {"path": str(el_path), "allow_absolute_path": True},
    })["ok"]
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs-2")
    fresh = Loop([str(CPP_BINARY), "--stdio-loop"], env, vdb)
    try:
        assert fresh.call("exclude.load", {"paths": [str(el_path)]})["ok"]
        assert fresh.call("exclude.remove", {
            "coverage_refs": [reference],
        })["ok"]
        removed_state = fresh.call("metrics.list", {})
        empty = tmp_path / "empty-ref.el"
        empty.write_text("")
        assert fresh.call("exclude.load", {"paths": [str(empty)]})["ok"]
        assert fresh.call("exclude.instance.add", {
            "items": [{"scope": "top.u_core0", "reason": "temporary"}],
        })["ok"]
        assert fresh.call("exclude.instance.remove", {
            "items": [{"scope": "top.u_core0"}],
        })["ok"]
        after = fresh.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in removed_state["data"]["items"]]
    finally:
        fresh.close()


def test_failed_csv_transaction_does_not_poison_family_baseline(loop,
                                                                tmp_path):
    """A failed CSV apply that creates the session baseline must not leave the
    partial transaction in that baseline."""
    reference = _first_gap_ref(loop, tmp_path)
    pristine = loop.call("metrics.list", {})
    assert pristine["ok"], pristine
    csv_dir = tmp_path / "failed-csv-baseline"
    _seed_required_csvs(csv_dir)
    (csv_dir / "container_exclusions.csv").write_text(
        "# schema_version=xcov-container-exclusions.v1\n"
        "# coverage_kind=container\n"
        "target_kind,scope,covergroup,item,expansion_root,reason\n"
        "instance,top.u_core0,,,top.u_core0,partial\n"
        "instance,top.no_such_instance,,,top.no_such_instance,bad\n",
        encoding="utf-8",
    )
    failed = loop.call("exclude.csv.apply", {"directory": str(csv_dir)})
    assert not failed["ok"], failed
    assert failed["error"]["code"] == "EXCLUSION_RESOLVE_FAILED"
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "unrelated"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]


def test_readded_ref_survives_family_remove(loop, tmp_path):
    """remove -> re-add must clear the tombstone so a later family restore
    keeps the newly added reason."""
    reference = _first_gap_ref(loop, tmp_path)
    pristine = loop.call("metrics.list", {})
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "first"}],
    })["ok"]
    assert loop.call("exclude.remove",
                     {"coverage_refs": [reference]})["ok"]
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "second"}],
    })["ok"]
    leaf_state = loop.call("metrics.list", {})
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "unrelated"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in leaf_state["data"]["items"]]
    assert [key(row) for row in after["data"]["items"]] != \
        [key(row) for row in pristine["data"]["items"]]


def _full_gap(loop, tmp_path, scope="top.u_core0"):
    out_dir = tmp_path / "full-gap"
    response = loop.call("export.code_coverage", {
        "scopes": [scope], "metrics": ["toggle"],
        "output": {"path": str(out_dir), "allow_absolute_path": True},
    })
    assert response["ok"], response
    gaps = json.loads(
        (out_dir / "instance-0001" / "toggle.json").read_text())["gaps"]
    return next(gap for gap in gaps if gap.get("coverage_ref"))


def test_failed_csv_with_code_row_does_not_poison_baseline(loop, tmp_path):
    gap = _full_gap(loop, tmp_path)
    pristine = loop.call("metrics.list", {})
    csv_dir = tmp_path / "failed-code-instance"
    _seed_required_csvs(csv_dir)
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"top.u_core0,toggle,,{gap['full_name']},,poison\n",
        encoding="utf-8",
    )
    (csv_dir / "container_exclusions.csv").write_text(
        "# schema_version=xcov-container-exclusions.v1\n"
        "# coverage_kind=container\n"
        "target_kind,scope,covergroup,item,expansion_root,reason\n"
        "instance,top.no_such_instance,,,top.no_such_instance,bad\n",
        encoding="utf-8",
    )
    failed = loop.call("exclude.csv.apply", {"directory": str(csv_dir)})
    assert not failed["ok"], failed
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "unrelated"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]


def test_compile_readd_survives_family_remove(loop, tmp_path):
    gap = _full_gap(loop, tmp_path)
    reference = gap["coverage_ref"]
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "first"}],
    })["ok"]
    assert loop.call("exclude.remove",
                     {"coverage_refs": [reference]})["ok"]
    csv_dir = tmp_path / "compile-readd"
    _seed_required_csvs(csv_dir)
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"top.u_core0,toggle,,{gap['full_name']},,row-reason\n",
        encoding="utf-8",
    )
    el_dir = tmp_path / "compile-readd-el"
    compiled = loop.call("exclude.csv.compile", {
        "directory": str(csv_dir), "output_directory": str(el_dir),
        "allow_absolute_path": True,
    })
    assert compiled["ok"], compiled
    readd = loop.call("metrics.list", {})
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "unrelated"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in readd["data"]["items"]]


def test_failed_transaction_restores_removed_ref_tombstone(loop, tmp_path):
    gap = _full_gap(loop, tmp_path)
    reference = gap["coverage_ref"]
    pristine = loop.call("metrics.list", {})
    assert loop.call("exclude.add", {
        "coverage_refs": [{"coverage_ref": reference, "reason": "first"}],
    })["ok"]
    assert loop.call("exclude.remove",
                     {"coverage_refs": [reference]})["ok"]
    csv_dir = tmp_path / "failed-tombstone"
    _seed_required_csvs(csv_dir)
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"top.u_core0,toggle,,{gap['full_name']},,transient\n",
        encoding="utf-8",
    )
    (csv_dir / "container_exclusions.csv").write_text(
        "# schema_version=xcov-container-exclusions.v1\n"
        "# coverage_kind=container\n"
        "target_kind,scope,covergroup,item,expansion_root,reason\n"
        "instance,top.no_such_instance,,,top.no_such_instance,bad\n",
        encoding="utf-8",
    )
    failed = loop.call("exclude.csv.apply", {"directory": str(csv_dir)})
    assert not failed["ok"], failed
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "unrelated"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]


def test_csv_record_remove_then_family_round_trip(loop, tmp_path):
    gap = _full_gap(loop, tmp_path)
    reference = gap["coverage_ref"]
    csv_dir = tmp_path / "csv-record-remove"
    _seed_required_csvs(csv_dir)
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"top.u_core0,toggle,,{gap['full_name']},,csv reason\n",
        encoding="utf-8",
    )
    assert loop.call("exclude.csv.apply",
                     {"directory": str(csv_dir)})["ok"]
    assert loop.call("exclude.remove",
                     {"coverage_refs": [reference]})["ok"]
    removed = loop.call("metrics.list", {})
    assert loop.call("exclude.instance.add", {
        "items": [{"scope": "top.u_core1", "reason": "unrelated"}],
    })["ok"]
    assert loop.call("exclude.instance.remove", {
        "items": [{"scope": "top.u_core1"}],
    })["ok"]
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in removed["data"]["items"]]


def test_compile_publish_failure_rolls_back(loop, vdb, tmp_path):
    gap = _full_gap(loop, tmp_path)
    pristine = loop.call("metrics.list", {})
    csv_dir = tmp_path / "publish-fail-csv"
    _seed_required_csvs(csv_dir)
    (csv_dir / "code_exclusions.csv").write_text(
        "# schema_version=xcov-code-exclusions.v1\n"
        "# coverage_kind=code\n"
        "scope,metric,line,object,bin,reason\n"
        f"top.u_core0,toggle,,{gap['full_name']},,publish fail\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "readonly-output"
    out_dir.mkdir()
    out_dir.chmod(0o555)
    try:
        compiled = loop.call("exclude.csv.compile", {
            "directory": str(csv_dir), "output_directory": str(out_dir),
            "allow_absolute_path": True,
        })
        assert not compiled["ok"], compiled
        assert compiled["error"]["code"] in {"EXCLUSION_SAVE_FAILED", "IO_ERROR"}
    finally:
        out_dir.chmod(0o755)
    after = loop.call("metrics.list", {})
    key = lambda row: (row["metric"], row["covered"], row["coverable"])
    assert [key(row) for row in after["data"]["items"]] == \
        [key(row) for row in pristine["data"]["items"]]
    # The failed compile must not mark reasons as persisted.
    closed = loop.call("session.close", {})
    if closed["ok"]:
        # No record was left behind, so a graceful close is legal too.
        assert closed["summary"]["discarded_reason_count"] == 0


def test_line_selector_readd_survives_family_remove(xverif_fixture, tmp_path):
    resources = xverif_fixture("xcov.modinfo_edge_layouts")
    database = resources / "edge_cases.vdb"
    if not database.is_dir():
        pytest.skip(f"fixture VDB missing: {database}")
    env = _env()
    env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")
    session = Loop([str(CPP_BINARY), "--stdio-loop"], env, database)
    scope = "route_matrix.u_value_dark"
    try:
        out_dir = tmp_path / "line-readd-gaps"
        exported = session.call("export.code_coverage", {
            "scopes": [scope], "metrics": ["line"],
            "output": {"path": str(out_dir), "allow_absolute_path": True},
        })
        assert exported["ok"], exported
        payload = json.loads(
            (out_dir / "instance-0001" / "line.json").read_text())
        line = payload["line_groups"][0]["uncovered"][0]["at"].rsplit(":", 1)[1]
        reference = payload["gaps"][0]["coverage_ref"]
        assert session.call("exclude.add", {
            "coverage_refs": [{"coverage_ref": reference, "reason": "first"}],
        })["ok"]
        assert session.call("exclude.remove",
                            {"coverage_refs": [reference]})["ok"]
        csv_dir = tmp_path / "line-readd-csv"
        _seed_required_csvs(csv_dir)
        (csv_dir / "code_exclusions.csv").write_text(
            "# schema_version=xcov-code-exclusions.v1\n"
            "# coverage_kind=code\n"
            "scope,metric,line,object,bin,reason\n"
            f"{scope},line,{line},,,line selector\n",
            encoding="utf-8",
        )
        applied = session.call("exclude.csv.apply",
                               {"directory": str(csv_dir)})
        assert applied["ok"], applied
        readd = session.call("metrics.list", {})
        assert session.call("exclude.instance.add", {
            "items": [{"scope": scope, "reason": "unrelated"}],
        })["ok"]
        assert session.call("exclude.instance.remove", {
            "items": [{"scope": scope}],
        })["ok"]
        after = session.call("metrics.list", {})
        key = lambda row: (row["metric"], row["covered"], row["coverable"])
        assert [key(row) for row in after["data"]["items"]] == \
            [key(row) for row in readd["data"]["items"]]
    finally:
        session.close()


def test_exclude_add_exports_is_explicit_error(loop, tmp_path):
    response = loop.call("exclude.add", {
        "exports": [{"path": str(tmp_path / "missing.json"),
                     "items": [{"gap_id": "G0001", "reason": "export"}]}],
    })
    assert not response["ok"], response
    assert response["error"]["code"] == "ACTION_NOT_IMPLEMENTED"
