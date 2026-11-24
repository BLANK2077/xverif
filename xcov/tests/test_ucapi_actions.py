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

    def __init__(self, command, env, vdb: Path):
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
            "args": {"name": "cov0"},
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


def _first_gap_ref(loop: Loop, tmp_path: Path) -> str:
    response = loop.call("export.code_coverage", {
        "scopes": ["top.u_core0"],
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
                object_name = payload["gaps"][0]["name"]
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


def test_error_paths(loop, tmp_path):
    """Malformed inputs return structured errors instead of crashing."""
    missing = loop.call("exclude.load",
                        {"paths": [str(tmp_path / "missing.el")]})
    assert not missing["ok"]
    assert missing["error"]["code"] == "EXCLUSION_LOAD_FAILED"

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
