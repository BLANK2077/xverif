"""Real cached FSDB/VDB smoke tests through the SDK-free fake-LSF CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]


def _env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "XVERIF_HOME": str(ROOT),
        "XVERIF_LSF_CLI_SOCKET": str(tmp_path / "manager.sock"),
        "XVERIF_LSF_CLI_LOG_DIR": str(tmp_path / "logs"),
        "XVERIF_LSF_CLI_FAKE_LSF": "1",
        "XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC": "2",
        "XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC": "60",
        "XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC": "180",
        "PYTHON": str(ROOT / ".conda-xverif" / "bin" / "python"),
    })
    config = tmp_path / "xverif_lsf.env.json"
    config.write_text(json.dumps({
        "schema_version": "xverif-lsf-env.v1",
        "variables": {"XVERIF_REAL_DATA_ENV_MARKER": "compute-node-verified"},
    }), encoding="utf-8")
    config.chmod(0o600)
    env["XVERIF_LSF_CLI_CONFIG"] = str(config)
    env["FAKE_BSUB_REQUIRE_ENV_ALL"] = "1"
    return env


def _call(tool: str, request: dict, env: dict[str, str]) -> dict:
    completed = subprocess.run(
        [str(ROOT / "tools" / f"{tool}_lsf"), "--json", "-"],
        input=json.dumps(request) + "\n",
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        env=env,
        timeout=240,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True, payload
    return payload


def test_sdk_free_fake_lsf_real_xdebug_and_xcov(
    tmp_path: Path,
    xverif_fixture,
) -> None:
    env = _env(tmp_path)
    fsdb = xverif_fixture("xdebug.ai_complex_wave") / "out" / "waves.fsdb"
    vdb = xverif_fixture("xcov.comprehensive") / "comprehensive.vdb"

    debug_name = "sdk_free_real_wave"
    opened = _call("xdebug", {
        "api_version": "xdebug.v1",
        "request_id": "debug-open",
        "action": "session.open",
        "target": {"fsdb": str(fsdb)},
        "args": {"name": debug_name},
    }, env)
    assert opened["session"]["session_id"] == debug_name
    sampled = _call("xdebug", {
        "api_version": "xdebug.v1",
        "request_id": "debug-value",
        "action": "value.at",
        "target": {"session_id": debug_name},
        "args": {
            "signal": "ai_complex_top.sig_a",
            "time": "75ns",
            "value_format": "hex",
        },
    }, env)
    value = sampled["data"]["samples"][0]["values"][0]["value"]
    assert value["known"] is True
    assert value["value"] == "8'h22"
    _call("xdebug", {
        "api_version": "xdebug.v1",
        "request_id": "debug-close",
        "action": "session.close",
        "target": {"session_id": debug_name},
        "args": {"mode": "graceful"},
    }, env)

    cov_name = "sdk_free_real_cov"
    opened_cov = _call("xcov", {
        "api_version": "xcov.v1",
        "request_id": "cov-open",
        "action": "session.open",
        "target": {"vdb": str(vdb)},
        "args": {"name": cov_name},
    }, env)
    assert opened_cov["data"]["session"]["session_id"] == cov_name
    summary = _call("xcov", {
        "api_version": "xcov.v1",
        "request_id": "cov-summary",
        "action": "code_coverage.summary",
        "target": {"session_id": cov_name},
        "args": {
            "group_by": "metric",
            "metrics": ["line", "toggle", "branch", "condition", "fsm"],
        },
    }, env)
    assert summary["summary"]["total_count"] == 5
    assert {row["metric"] for row in summary["data"]["items"]} == {
        "line", "toggle", "branch", "condition", "fsm",
    }
    _call("xcov", {
        "api_version": "xcov.v1",
        "request_id": "cov-close",
        "action": "session.close",
        "target": {"session_id": cov_name},
        "args": {},
    }, env)
