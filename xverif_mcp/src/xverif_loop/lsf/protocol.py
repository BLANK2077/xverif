"""Shared JSONL process protocol helpers."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, List, Optional

from xverif_loop.config import RuntimeConfig
from xverif_loop.logging import (
    StructuredLogger,
    StructuredLoggingError,
    argv_hash,
)
from xverif_loop.json_contract import strict_json_dumps, strict_json_loads


Json = Dict[str, Any]


class ProtocolError(RuntimeError):
    pass


@dataclass
class JsonlProcess:
    argv: List[str]
    proc: subprocess.Popen[str]
    runtime: RuntimeConfig
    logger: StructuredLogger
    stdout_queue: "queue.Queue[str]" = field(default_factory=queue.Queue)
    stderr_tail: Deque[str] = field(default_factory=lambda: deque(maxlen=200))
    pending: Dict[str, Json] = field(default_factory=dict)
    read_lock: threading.Lock = field(default_factory=threading.Lock)
    job_name: Optional[str] = None
    job_id: Optional[str] = None
    submitted_queue: Optional[str] = None
    submitted_resource: Optional[str] = None
    log_alias: Optional[str] = None
    log_backend: Optional[str] = None
    log_launcher: Optional[str] = None
    _stdout_thread: Optional[threading.Thread] = None
    _stderr_thread: Optional[threading.Thread] = None

    @classmethod
    def start(
        cls,
        argv: Iterable[str],
        *,
        runtime: RuntimeConfig,
        logger: StructuredLogger,
        log_context: Optional[Json] = None,
    ) -> "JsonlProcess":
        args = list(argv)
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=True,  # isolate process group for clean kill of children
        )
        item = cls(args, proc, runtime, logger)
        if log_context:
            item.log_alias = log_context.get("alias")
            item.log_backend = log_context.get("backend")
            item.log_launcher = log_context.get("launcher")
        item._stdout_thread = threading.Thread(target=item._read_stdout, daemon=True)
        item._stderr_thread = threading.Thread(target=item._read_stderr, daemon=True)
        item._stdout_thread.start()
        item._stderr_thread.start()
        try:
            item._log_stdio(
                "process.start",
                True,
                argv_hash=argv_hash(args),
                pid=proc.pid,
            )
        except StructuredLoggingError:
            # Startup observability is a precondition.  The subprocess has
            # already been created at this layer, so restore fail-closed
            # semantics before propagating the typed logging error.
            item.terminate()
            raise
        return item

    def _common(self) -> Json:
        return {
            "backend": self.log_backend,
            "launcher": self.log_launcher,
            "pid": self.proc.pid,
            "job_name": self.job_name,
            "job_id": self.job_id,
        }

    def _log_stdio(self, phase: str, ok: bool = True, **fields: Any) -> None:
        data = self._common()
        data.update(fields)
        self.logger.stdio(self.log_alias, phase, ok, **data)

    def _log_lsf(self, phase: str, ok: bool = True, **fields: Any) -> None:
        data = self._common()
        data.update(fields)
        self.logger.lsf(self.log_alias, phase, ok, **data)

    def _try_log_stdio(
        self,
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> None:
        data = self._common()
        data.update(fields)
        self.logger.try_stdio(
            self.log_alias,
            phase,
            ok,
            **data,
        )

    def _try_log_lsf(
        self,
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> None:
        data = self._common()
        data.update(fields)
        self.logger.try_lsf(
            self.log_alias,
            phase,
            ok,
            **data,
        )

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        stream = self.proc.stdout
        from xverif_loop.lsf.bsub import (
            is_lsf_scheduler_framing as _is_framing,
            parse_lsf_job_id as _parse,
        )
        try:
            for line in stream:
                stripped = line.rstrip("\n")
                jid = _parse(stripped)
                if jid and not self.job_id:
                    self.job_id = jid
                    self._try_log_lsf(
                        "job_id.detected",
                        True,
                        job_id=jid,
                    )
                if self.log_launcher == "lsf" and (
                    jid is not None or _is_framing(stripped)
                ):
                    # LSF scheduler framing is never backend JSONL protocol
                    # data, including lines emitted after the job id was
                    # already seen.
                    self._try_log_lsf("scheduler.framing", True)
                    continue
                self.stdout_queue.put(stripped)
        except ValueError:
            if stream.closed:
                return
            raise

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        stream = self.proc.stderr
        # Lazy import to avoid circular dependency
        from xverif_loop.lsf.bsub import parse_lsf_job_id as _parse
        try:
            for line in stream:
                stripped = line.rstrip("\n")
                self.stderr_tail.append(stripped)
                if not self.job_id:
                    jid = _parse(stripped)
                    if jid:
                        self.job_id = jid
                        self._try_log_lsf(
                            "job_id.detected",
                            True,
                            job_id=jid,
                        )
        except ValueError:
            if stream.closed:
                return
            raise

    def wait_ready(self, protocol: str, timeout_sec: float = 30.0) -> Json:
        self._log_stdio("ready.wait.begin", True, protocol=protocol, timeout_sec=timeout_sec)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if self.proc.poll() is not None:
                # The scheduler may flush its submission record immediately
                # before exiting. Give the pipe readers a bounded opportunity
                # to publish that identity before constructing the typed
                # startup-rejection response and cleanup request.
                self._join_reader_threads(timeout_sec=0.2)
                self._log_stdio("ready.process_exited", False,
                                protocol=protocol, returncode=self.proc.returncode,
                                stderr_tail=list(self.stderr_tail))
                raise ProtocolError(f"process exited before ready: rc={self.proc.returncode}")
            try:
                line = self.stdout_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                msg = strict_json_loads(line)
            except (ValueError, TypeError) as exc:
                self._log_stdio("ready.stdout_non_json", False)
                raise ProtocolError(
                    "non-JSON stdout before the ready envelope"
                ) from exc
            if not isinstance(msg, dict):
                self._log_stdio("ready.invalid_envelope", False)
                raise ProtocolError("ready envelope must be a JSON object")
            if msg.get("type") == "ready" and msg.get("protocol") == protocol:
                self._log_stdio("ready.ok", True, protocol=protocol, message=msg)
                return msg
            self._log_stdio("ready.unexpected_envelope", False)
            raise ProtocolError(
                f"unexpected JSON envelope before ready protocol {protocol}"
            )
        self._log_stdio("ready.timeout", False, protocol=protocol,
                        timeout_sec=timeout_sec, stderr_tail=list(self.stderr_tail))
        raise ProtocolError(f"timeout waiting for ready protocol {protocol}")

    def request(self, obj: Json, timeout_sec: float = 30.0) -> Json:
        """Send a JSONL request and wait for the matching response."""
        if not isinstance(obj, dict):
            raise ProtocolError("request envelope must be a JSON object")
        req_id = obj.get("request_id")
        if req_id is None:
            req_id = obj.get("id")
        if not isinstance(req_id, str) or not req_id:
            raise ProtocolError(
                "request envelope requires a non-empty string request_id or id"
            )
        self._log_stdio("request.begin", True, request_id=req_id,
                        action=obj.get("action"), timeout_sec=timeout_sec)
        self.write_json(obj)
        try:
            rsp = self.read_json_response(req_id, timeout_sec)
            self._try_log_stdio(
                "request.end",
                bool(rsp.get("ok")),
                request_id=req_id,
                action=obj.get("action"),
                response_ok=rsp.get("ok"),
            )
            return rsp
        except Exception as exc:
            self._try_log_stdio(
                "request.error",
                False,
                request_id=req_id,
                action=obj.get("action"),
                error_type=type(exc).__name__,
                stderr_tail=list(self.stderr_tail),
            )
            raise

    def write_json(self, msg: Json) -> None:
        if not isinstance(msg, dict):
            raise ProtocolError("JSONL message must be an object")
        if self.proc.stdin is None:
            self._log_stdio("stdin.closed", False)
            raise ProtocolError("process stdin is closed")
        try:
            encoded = strict_json_dumps(
                msg,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ProtocolError("JSONL message is not strict JSON") from exc
        self.proc.stdin.write(encoded + "\n")
        self.proc.stdin.flush()

    def read_json_response(self, request_id: str, timeout_sec: float = 30.0) -> Json:
        deadline = time.time() + timeout_sec
        with self.read_lock:
            cached = self.pending.pop(request_id, None)
            if cached is not None:
                return cached
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    self._try_log_stdio(
                        "response.process_exited",
                        False,
                        request_id=request_id,
                        returncode=self.proc.returncode,
                        stderr_tail=list(self.stderr_tail),
                    )
                    raise ProtocolError(f"process exited while waiting response: rc={self.proc.returncode}")
                try:
                    line = self.stdout_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    msg = strict_json_loads(line)
                except (ValueError, TypeError) as exc:
                    self._try_log_stdio(
                        "stdout.pollution",
                        False,
                        request_id=request_id,
                    )
                    raise ProtocolError(
                        "non-JSON stdout after ready"
                    ) from exc
                if not isinstance(msg, dict):
                    self._try_log_stdio(
                        "response.invalid_envelope",
                        False,
                        request_id=request_id,
                    )
                    raise ProtocolError("response envelope must be a JSON object")
                msg_id = msg.get("id") or msg.get("request_id")
                if not isinstance(msg_id, str) or not msg_id:
                    self._try_log_stdio(
                        "response.missing_id",
                        False,
                        request_id=request_id,
                    )
                    raise ProtocolError(
                        "response envelope requires a non-empty string id or request_id"
                    )
                if not isinstance(msg.get("ok"), bool):
                    self._try_log_stdio(
                        "response.invalid_ok",
                        False,
                        request_id=request_id,
                        response_id=msg_id,
                    )
                    raise ProtocolError(
                        "response envelope requires a boolean ok field"
                    )
                if msg_id == request_id:
                    return msg
                self.pending[msg_id] = msg
                self._try_log_stdio(
                    "response.pending",
                    True,
                    request_id=request_id,
                    pending_id=msg_id,
                )
        self._try_log_stdio(
            "response.timeout",
            False,
            request_id=request_id,
            timeout_sec=timeout_sec,
            stderr_tail=list(self.stderr_tail),
        )
        raise ProtocolError(f"timeout waiting response {request_id}")

    def terminate(self, timeout_sec: float = 5.0) -> Json:
        started = time.monotonic()
        try:
            if self.proc.poll() is not None:
                self._close_pipes()
                result = {
                    "ok": True,
                    "status": "already_exited",
                    "returncode": self.proc.returncode,
                    "forced": False,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                }
                self._try_log_stdio(
                    "process.terminate.end",
                    True,
                    **{
                        key: value
                        for key, value in result.items()
                        if key != "ok"
                    },
                )
                return result
            # Kill the entire process group so child engines are not orphaned.
            forced = False
            try:
                os.killpg(
                    os.getpgid(self.proc.pid),
                    __import__("signal").SIGTERM,
                )
            except (ProcessLookupError, OSError):
                self.proc.terminate()
            try:
                self.proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                forced = True
                try:
                    os.killpg(
                        os.getpgid(self.proc.pid),
                        __import__("signal").SIGKILL,
                    )
                except (ProcessLookupError, OSError):
                    self.proc.kill()
                self.proc.wait(timeout=timeout_sec)
            self._close_pipes()
            result = {
                "ok": True,
                "status": "terminated",
                "returncode": self.proc.returncode,
                "forced": forced,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
            self._try_log_stdio(
                "process.terminate.end",
                True,
                **{
                    key: value
                    for key, value in result.items()
                    if key != "ok"
                },
            )
            return result
        except Exception as exc:
            self._try_log_stdio(
                "process.terminate.end",
                False,
                error_type=type(exc).__name__,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            raise

    def _close_pipes(self) -> None:
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass

    def _join_reader_threads(self, *, timeout_sec: float) -> None:
        deadline = time.monotonic() + timeout_sec
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is None:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    @property
    def stderr_text(self) -> str:
        return "\n".join(self.stderr_tail)
