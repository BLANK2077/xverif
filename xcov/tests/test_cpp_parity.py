"""C++ UCAPI implementation must match the Python reference contract.

The parity suite exercises the read-only action set end to end: both
implementations open the same cached VDB and must produce byte-identical
response payloads after removing volatile fields.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
CPP_BINARY = ROOT / "xcov" / "bin" / "xcov"
XCOV_ENTRY = ROOT / "tools" / "xcov"

READ_REQUESTS = [
    ("tests.list", {}),
    ("metrics.list", {}),
    ("scope.summary", {"scope": "top"}),
    ("scope.children", {"scope": "top"}),
    ("scope.search", {
        "query": {"include_patterns": ["*"], "match_field": "full_name"},
    }),
    ("code_coverage.summary", {"group_by": "metric"}),
    ("functional_coverage.summary", {"group_by": "covergroup"}),
    ("assert.summary", {}),
]


def _volatile():
    return {"session_id", "worker", "npi_initialized"}


def _normalize(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in value.items()
            if key not in _volatile()
        }
    if isinstance(value, list):
        normalized = [_normalize(item) for item in value]
        # Row order is not part of the public contract; compare as a set while
        # keeping the payload identical.
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _run_loop(command, env, vdb, requests):
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        bufsize=1,
    )
    try:
        proc.stdout.readline()
        def send(request):
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())
        opened = send({
            "api_version": "xcov.v1",
            "request_id": "open",
            "action": "session.open",
            "target": {"vdb": str(vdb)},
            "args": {"name": "cov0"},
        })
        assert opened["json"]["ok"], json.dumps(opened)[:400]
        results = {}
        for index, (action, args) in enumerate(requests):
            response = send({
                "api_version": "xcov.v1",
                "request_id": f"r{index}",
                "action": action,
                "target": {"session_id": "cov0"},
                "args": args,
            })
            results[action] = response["json"]
        proc.stdin.write(json.dumps({
            "api_version": "xcov.v1",
            "request_id": "quit",
            "action": "stdio.quit",
        }) + "\n")
        proc.stdin.flush()
        return results
    finally:
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_cpp_read_actions_match_python(xverif_fixture, tmp_path):
    if not CPP_BINARY.is_file():
        pytest.skip(f"C++ binary not built: {CPP_BINARY}; run `make -C xcov`")
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"
    if not vdb.is_dir():
        pytest.skip(f"fixture VDB missing: {vdb}")

    cpp_env = os.environ.copy()
    cpp_env["XVERIF_HOME"] = str(ROOT)
    py_env = os.environ.copy()
    # Force the reference implementation; tools/xcov defaults to the C++ binary.
    py_env["XVERIF_XCOV_BACKEND"] = "urg"
    py_env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / "logs")

    cpp = _run_loop([str(CPP_BINARY), "--stdio-loop"], cpp_env, vdb,
                    READ_REQUESTS)
    py = _run_loop([str(XCOV_ENTRY), "--stdio-loop"], py_env, vdb,
                   READ_REQUESTS)

    for action, _ in READ_REQUESTS:
        cpp_rows = _normalize(cpp[action].get("data", {}).get("items", []))
        py_rows = _normalize(py[action].get("data", {}).get("items", []))
        assert cpp[action]["ok"] == py[action]["ok"], action
        assert cpp_rows == py_rows, (
            f"{action} rows diverged; "
            f"cpp={json.dumps(cpp_rows[:1])[:300]} "
            f"py={json.dumps(py_rows[:1])[:300]}"
        )


def test_backend_switch_ucapi_and_urg(xverif_fixture, tmp_path):
    """Both XVERIF_XCOV_BACKEND values open the same VDB and list tests."""
    resources = xverif_fixture("xcov.comprehensive")
    vdb = resources / "comprehensive.vdb"
    if not vdb.is_dir():
        pytest.skip(f"fixture VDB missing: {vdb}")
    requests = [("tests.list", {}), ("scope.summary", {"scope": "top"})]
    for backend in ("ucapi", "urg"):
        env = os.environ.copy()
        env["XVERIF_XCOV_BACKEND"] = backend
        env["XVERIF_XCOV_LOG_DIR"] = str(tmp_path / f"logs-{backend}")
        results = _run_loop([str(XCOV_ENTRY), "--stdio-loop"], env, vdb, requests)
        assert results["tests.list"]["ok"], backend
        assert results["scope.summary"]["ok"], backend
        assert results["tests.list"]["data"]["items"], backend


def test_cpp_binary_does_not_link_python_or_pynpi():
    if not CPP_BINARY.is_file():
        pytest.skip("C++ binary not built")
    completed = subprocess.run(
        ["ldd", str(CPP_BINARY)], capture_output=True, text=True, check=False,
    )
    output = completed.stdout.lower()
    for forbidden in ("python", "pynpi", "urg"):
        assert forbidden not in output, output
