from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Mapping, Optional, Sequence

from .cli import RunResult
from .normalize import NormalizeOptions, normalize_response


Json = Dict[str, Any]


class StdioLoopError(RuntimeError):
    pass


class StdioLoopRunner:
    def __init__(
        self,
        xdebug_bin: Path,
        *,
        cwd: Optional[Path] = None,
        env: Optional[Mapping[str, str]] = None,
        default_json: bool = False,
        wait_for_stderr_idle: bool = True,
        extra_args: Sequence[str] = (),
        normalize_options: Optional[NormalizeOptions] = None,
    ) -> None:
        self.command = [str(Path(xdebug_bin))]
        if default_json:
            self.command.append("--json")
        self.command.append("--stdio-loop")
        self.command.extend(extra_args)
        self.cwd = str(Path(cwd or Path.cwd()))
        self.env = dict(os.environ)
        if env:
            self.env.update(env)
        self.normalize_options = normalize_options or NormalizeOptions()
        self.wait_for_stderr_idle = wait_for_stderr_idle
        self.proc: Optional[subprocess.Popen[str]] = None
        self.stdout_queue: "queue.Queue[str]" = queue.Queue()
        self.stderr_tail: Deque[str] = deque(maxlen=4096)
        self.transcript: list[Json] = []
        self.history: list[RunResult] = []
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._seq = 0

    def start(self, timeout_sec: float = 30.0) -> Json:
        if self.proc is not None:
            raise StdioLoopError("stdio-loop already started")
        self.proc = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        ready = self._read_message(timeout_sec, allow_noise=True)
        if ready.get("type") != "ready" or ready.get("protocol") != "xdebug-stdio-loop":
            self.terminate()
            raise StdioLoopError("unexpected ready envelope: %r" % ready)
        return ready

    def _read_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            self.stdout_queue.put(line.rstrip("\n"))

    def _read_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip("\n"))

    def _wait_for_stderr_idle(
        self,
        *,
        idle_sec: float = 0.05,
        timeout_sec: float = 1.0,
    ) -> None:
        deadline = time.monotonic() + timeout_sec
        stable_since = time.monotonic()
        last_len = len(self.stderr_tail)
        while time.monotonic() < deadline:
            current_len = len(self.stderr_tail)
            now = time.monotonic()
            if current_len != last_len:
                last_len = current_len
                stable_since = now
            elif now - stable_since >= idle_sec:
                return
            time.sleep(0.01)

    def _read_message(self, timeout_sec: float, *, allow_noise: bool = False) -> Json:
        assert self.proc is not None
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise StdioLoopError(
                    "stdio-loop exited: rc=%s stderr=%s"
                    % (self.proc.returncode, "\n".join(self.stderr_tail))
                )
            try:
                line = self.stdout_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                if allow_noise:
                    self.transcript.append({"direction": "stdout-noise", "text": line})
                    continue
                raise StdioLoopError(
                    "stdout protocol pollution after ready: %r" % line
                ) from exc
            if not isinstance(message, dict):
                raise StdioLoopError("stdio-loop message is not an object: %r" % message)
            self.transcript.append({"direction": "response", "message": message})
            return message
        raise StdioLoopError("timeout waiting for stdio-loop response")

    def request(self, request: Json, timeout_sec: float = 60.0) -> RunResult:
        if self.proc is None or self.proc.stdin is None:
            raise StdioLoopError("stdio-loop is not started")
        self._seq += 1
        req = dict(request)
        request_id = req.get("request_id") or req.get("id")
        if not isinstance(request_id, str) or not request_id:
            request_id = "test-%d" % self._seq
            req["request_id"] = request_id
        encoded = json.dumps(req, ensure_ascii=False, separators=(",", ":"))
        self.transcript.append({"direction": "request", "message": req})
        start = time.monotonic()
        try:
            self.proc.stdin.write(encoded + "\n")
            self.proc.stdin.flush()
            envelope = self._read_message(timeout_sec)
            if self.wait_for_stderr_idle:
                self._wait_for_stderr_idle()
            timed_out = False
        except StdioLoopError as exc:
            if self.wait_for_stderr_idle:
                self._wait_for_stderr_idle()
            timed_out = "timeout" in str(exc).lower()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if timed_out:
                # A timed-out JSONL stream is no longer safely correlated:
                # the late response could be mistaken for the next request.
                self.terminate()
            result = RunResult(
                command=list(self.command),
                cwd=self.cwd,
                env=dict(self.env),
                request=req,
                returncode=-1,
                stdout_raw="",
                stderr_raw="\n".join(self.stderr_tail) + "\n" + str(exc),
                elapsed_ms=elapsed_ms,
                timed_out=timed_out,
                response=None,
                normalized_response=None,
                metadata={"mode": "stdio-loop", "request_id": request_id},
            )
            self.history.append(result)
            return result

        elapsed_ms = int((time.monotonic() - start) * 1000)
        if envelope.get("id") != request_id:
            raise StdioLoopError(
                "response id mismatch: actual=%r expected=%r"
                % (envelope.get("id"), request_id)
            )
        payload_format = envelope.get("payload_format")
        if payload_format == "json":
            response: Any = envelope.get("json")
            stdout_raw = json.dumps(envelope, ensure_ascii=False)
        elif payload_format == "xout":
            response = envelope.get("xout", "")
            stdout_raw = response
        else:
            response = envelope
            stdout_raw = json.dumps(envelope, ensure_ascii=False)
        result = RunResult(
            command=list(self.command),
            cwd=self.cwd,
            env=dict(self.env),
            request=req,
            returncode=0 if envelope.get("ok") else 1,
            stdout_raw=stdout_raw,
            stderr_raw="\n".join(self.stderr_tail),
            elapsed_ms=elapsed_ms,
            response=response,
            envelope=envelope,
            normalized_response=normalize_response(
                response, self.normalize_options
            ),
            metadata={
                "mode": "stdio-loop",
                "request_id": request_id,
                "payload_format": payload_format,
            },
        )
        self.history.append(result)
        return result

    def send_raw(self, line: str, timeout_sec: float = 5.0) -> Json:
        """Send one protocol line verbatim for malformed/edge-case tests."""
        if self.proc is None or self.proc.stdin is None:
            raise StdioLoopError("stdio-loop is not started")
        self.transcript.append({"direction": "request-raw", "text": line})
        self.proc.stdin.write(line.rstrip("\n") + "\n")
        self.proc.stdin.flush()
        return self._read_message(timeout_sec)

    def quit(self, timeout_sec: float = 5.0) -> Optional[RunResult]:
        if self.proc is None or self.proc.poll() is not None:
            return None
        result = self.request(
            {"api_version": "xdebug.v1", "action": "stdio.quit"},
            timeout_sec=timeout_sec,
        )
        try:
            self.proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            self.terminate()
        return result

    def terminate(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    self.proc.kill()
                self.proc.wait(timeout=2)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    def __enter__(self) -> "StdioLoopRunner":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            try:
                self.quit()
                return
            except Exception:
                pass
        self.terminate()
