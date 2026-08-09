from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .normalize import NormalizeOptions, normalize_response


Json = Dict[str, Any]


@dataclass
class RunResult:
    command: List[str]
    cwd: str
    env: Dict[str, str]
    request: Any
    returncode: int
    stdout_raw: str
    stderr_raw: str
    elapsed_ms: int
    timed_out: bool = False
    response: Any = None
    envelope: Optional[Json] = None
    normalized_response: Any = None
    metadata: Json = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        if isinstance(self.response, dict) and "ok" in self.response:
            return bool(self.response["ok"])
        return self.returncode == 0 and not self.timed_out


def _terminate_process_group(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()
        proc.wait(timeout=2)


class CliRunner:
    """Run the real xdebug CLI without duplicating subprocess details in cases."""

    def __init__(
        self,
        xdebug_bin: Path,
        *,
        cwd: Optional[Path] = None,
        base_env: Optional[Mapping[str, str]] = None,
        normalize_options: Optional[NormalizeOptions] = None,
    ) -> None:
        self.xdebug_bin = Path(xdebug_bin)
        self.cwd = Path(cwd or Path.cwd())
        self.base_env = dict(base_env or {})
        self.normalize_options = normalize_options or NormalizeOptions()
        self.history: List[RunResult] = []

    def run(
        self,
        request: Any,
        *,
        output_format: str = "json",
        input_mode: str = "stdin",
        timeout_sec: float = 60.0,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[Path] = None,
        extra_args: Sequence[str] = (),
    ) -> RunResult:
        if output_format not in ("json", "xout"):
            raise ValueError("output_format must be 'json' or 'xout'")
        if input_mode not in ("stdin", "file"):
            raise ValueError("input_mode must be 'stdin' or 'file'")

        request_text = request if isinstance(request, str) else json.dumps(request)
        command = [str(self.xdebug_bin)]
        if output_format == "json":
            command.append("--json")
        command.extend(extra_args)

        input_text: Optional[str] = None
        request_file: Optional[Path] = None
        temp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
        if input_mode == "stdin":
            command.append("-")
            input_text = request_text + ("" if request_text.endswith("\n") else "\n")
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="xdebug-request-")
            request_file = Path(temp_dir.name) / "request.json"
            request_file.write_text(request_text, encoding="utf-8")
            command.append(str(request_file))

        run_env = dict(os.environ)
        run_env.update(self.base_env)
        if env:
            run_env.update(env)
        run_cwd = str(Path(cwd or self.cwd))

        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.Popen(
                command,
                cwd=run_cwd,
                env=run_env,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(input=input_text, timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process_group(proc)
                stdout, stderr = proc.communicate()
            returncode = proc.returncode if not timed_out else -1
        except OSError as exc:
            stdout = ""
            stderr = str(exc)
            returncode = -1
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        response: Any = None
        actual_output_format = output_format
        if stdout.strip():
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                response = parsed
                actual_output_format = "json"
            elif output_format == "xout":
                response = stdout
        elif output_format == "xout":
            response = stdout

        normalized = normalize_response(response, self.normalize_options)
        metadata: Json = {
            "output_format": output_format,
            "actual_output_format": actual_output_format,
            "input_mode": input_mode,
            "timeout_sec": timeout_sec,
        }
        if request_file is not None:
            metadata["request_file_mode"] = True

        result = RunResult(
            command=command,
            cwd=run_cwd,
            env=run_env,
            request=request,
            returncode=returncode,
            stdout_raw=stdout,
            stderr_raw=stderr,
            elapsed_ms=elapsed_ms,
            timed_out=timed_out,
            response=response,
            normalized_response=normalized,
            metadata=metadata,
        )
        self.history.append(result)
        return result
