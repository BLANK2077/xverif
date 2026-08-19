"""Clean-environment smoke tests for the SDK-free runtime distribution."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "xverif_mcp"


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]


def test_sdk_free_loop_runtime_installs_in_clean_venv(tmp_path: Path) -> None:
    """The loop package must run without checkout-relative imports or MCP SDK."""
    venv = tmp_path / "runtime-venv"
    wheel_dir = tmp_path / "wheelhouse"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["XVERIF_HOME"] = str(ROOT)
    # Build in the test environment, then install only the wheel in the clean
    # venv.  New Python venvs need not bundle setuptools, so source installs
    # would test a build frontend rather than the distributed runtime.
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(PACKAGE),
        ],
        cwd=tmp_path,
        env=env,
    )
    wheels = sorted(wheel_dir.glob("xverif_mcp-*.whl"))
    assert len(wheels) == 1
    _run([sys.executable, "-m", "venv", str(venv)], cwd=tmp_path, env=env)

    python = venv / "bin" / "python"
    _run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        env=env,
    )
    _run(
        [str(python), "-c", "import xverif_loop; print(xverif_loop.__file__)"],
        cwd=tmp_path,
        env=env,
    )
    _run([str(venv / "bin" / "xdebug_lsf"), "-help"], cwd=tmp_path, env=env)
    _run([str(venv / "bin" / "xcov_lsf"), "--help"], cwd=tmp_path, env=env)
    assert not (venv / "bin" / "xverif-loop-server").exists()
    assert not (venv / "bin" / "xverif-loop-client").exists()
