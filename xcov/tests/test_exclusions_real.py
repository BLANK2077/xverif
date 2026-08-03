from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

def test_real_pynpi_exclusion_matrix_union_strict_and_reopen(
    xverif_fixture,
    tmp_path,
):
    resources = xverif_fixture("xcov.exclusion")
    vdb = resources / "exclusion.vdb"
    worker = Path(__file__).with_name("real_exclusion_worker.py")
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }

    def run(*args: str) -> dict:
        proc = subprocess.run(
            [sys.executable, str(worker), *args],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
        assert lines, proc.stdout + proc.stderr
        return json.loads(lines[-1])

    default = run("default", str(vdb), str(tmp_path))
    assert default["union"] is True
    assert all(
        statuses == ["changed", "already_in_state", "changed"]
        for statuses in default["matrix"].values()
    )

    reopened = run("reopen", str(vdb), default["persisted"])
    assert reopened["before"] == 0
    assert reopened["after"] >= 2

    strict = run("strict", str(vdb))
    assert strict == {"covered": "failed", "uncovered": "changed"}
