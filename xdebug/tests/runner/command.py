from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import List, Mapping, Optional, Sequence

from .cli import RunResult
from .normalize import normalize_response


class CommandRunner:
    """Run fixture builders and existing regression entrypoints consistently."""

    def __init__(
        self,
        *,
        cwd: Optional[Path] = None,
        base_env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.cwd = Path(cwd or Path.cwd())
        self.base_env = dict(base_env or {})
        self.history: List[RunResult] = []

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_sec: float,
        cwd: Optional[Path] = None,
        env: Optional[Mapping[str, str]] = None,
        metadata: Optional[dict] = None,
    ) -> RunResult:
        argv = [str(item) for item in command]
        run_env = dict(os.environ)
        run_env.update(self.base_env)
        if env:
            run_env.update(env)
        run_cwd = str(Path(cwd or self.cwd))
        start = time.monotonic()
        timed_out = False
        proc = subprocess.Popen(
            argv,
            cwd=run_cwd,
            env=run_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        response = {
            "ok": proc.returncode == 0 and not timed_out,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        details = dict(metadata or {})
        details["timeout_sec"] = timeout_sec
        details["mode"] = "command"
        result = RunResult(
            command=argv,
            cwd=run_cwd,
            env=run_env,
            request={"command": argv},
            returncode=-1 if timed_out else proc.returncode,
            stdout_raw=stdout,
            stderr_raw=stderr,
            elapsed_ms=elapsed_ms,
            timed_out=timed_out,
            response=response,
            normalized_response=normalize_response(response),
            metadata=details,
        )
        self.history.append(result)
        return result
