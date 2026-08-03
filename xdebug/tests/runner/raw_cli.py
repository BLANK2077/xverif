from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RawCliResult:
    action: str
    phase: str
    role: str
    request: dict[str, Any]
    command: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_ms: int
    timed_out: bool

    @property
    def stdout_bytes(self) -> int:
        return len(self.stdout)

    @property
    def stdout_sha256(self) -> str:
        return hashlib.sha256(self.stdout).hexdigest()

    @property
    def stderr_sha256(self) -> str:
        return hashlib.sha256(self.stderr).hexdigest()

    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="strict")


class RawCliRunner:
    """Invoke the native CLI without decoding or re-encoding its output."""

    def __init__(
        self,
        xdebug_bin: Path,
        *,
        cwd: Path,
        base_env: Mapping[str, str],
        phase: str,
    ) -> None:
        self.xdebug_bin = Path(xdebug_bin)
        self.cwd = Path(cwd)
        self.base_env = dict(base_env)
        if phase not in {"baseline", "final"}:
            raise ValueError("phase must be baseline or final")
        self.phase = phase
        self.history: list[RawCliResult] = []

    def run(
        self,
        request: dict[str, Any],
        *,
        role: str,
        timeout_sec: float = 120.0,
        extra_args: Sequence[str] = (),
    ) -> RawCliResult:
        action = str(request.get("action", "unknown"))
        command = (str(self.xdebug_bin), *map(str, extra_args), "-")
        request_body = (
            json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        env = os.environ.copy()
        env.update(self.base_env)
        started = time.monotonic()
        timed_out = False
        proc = subprocess.Popen(
            command,
            cwd=self.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(request_body, timeout=timeout_sec)
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
        result = RawCliResult(
            action=action,
            phase=self.phase,
            role=role,
            request=request,
            command=command,
            returncode=-1 if timed_out else int(proc.returncode),
            stdout=stdout,
            stderr=stderr,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            timed_out=timed_out,
        )
        self.history.append(result)
        return result
