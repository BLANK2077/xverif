from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_full_action_smoke_uses_published_combined_fixture(tmp_path, xverif_fixture) -> None:
    resources = xverif_fixture("xdebug.active_driver") / "out"
    config = tmp_path / "action-smoke.json"
    config.write_text(
        json.dumps(
            {
                "daidir": str(resources / "simv.daidir"),
                "fsdb": str(resources / "waves.fsdb"),
                "signal": "active_driver_tb.u_dut.q",
                "clock": "active_driver_tb.clk",
                "reset": "active_driver_tb.rst_n",
                "session_name": "catalog_action_smoke",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "xverif_mcp/tools/test_actions.py"),
            "-c",
            str(config),
            "--runtime-only",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failed" in result.stdout
    assert "0 failed" in result.stdout
