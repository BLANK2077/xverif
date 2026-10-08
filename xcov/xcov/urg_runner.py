"""Strict direct/LSF runner for every URG invocation."""
from __future__ import annotations

import itertools
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .eda import get_urg_path
from .errors import XcovError
from .logging import log_lifecycle_event

Json = Dict[str, Any]

_JOB_RE = re.compile(r"Job\s+<(?P<job_id>\d+)>\s+is\s+submitted")
_WAIT_RE = re.compile(r"^<<Waiting for dispatch.*>>$")
_START_RE = re.compile(r"^<<Starting on.*>>$")
_JOB_COUNTER = itertools.count()
_PATH_OPTIONS = frozenset({"-dir", "-report", "-elfile", "-hier"})
_TERMINATION_GRACE_SEC = 5.0


def _drain_stream(stream: Any, target: List[str]) -> None:
    assert stream is not None
    for line in stream:
        target.append(line)


def _terminate_process_group(
    process: "subprocess.Popen[str]",
) -> Json:
    """Terminate one isolated URG child group and report the outcome.

    The child is started in its own group, so the whole group is signalled and
    an unconfirmed termination is never reported as success.
    """

    try:
        pgid = os.getpgid(process.pid)
    except OSError:
        pgid = process.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
        delivery = "signaled"
    except ProcessLookupError:
        delivery = "group_gone"
    except OSError:
        try:
            process.terminate()
            delivery = "leader_only"
        except OSError:
            delivery = "failed"
    cleanup: Json = {"signal_delivery": delivery}
    try:
        process.wait(timeout=_TERMINATION_GRACE_SEC)
        cleanup["process"] = "terminated"
        cleanup["complete"] = delivery != "failed"
        return cleanup
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=_TERMINATION_GRACE_SEC)
        cleanup["process"] = "killed"
        cleanup["complete"] = True
    except subprocess.TimeoutExpired:
        cleanup["process"] = "unresolved"
        cleanup["complete"] = False
    return cleanup


def _forward_signal_to_child(process: "subprocess.Popen[str]", signum: int) -> None:
    """Kill an isolated child group, then exit with the conventional code."""

    _terminate_process_group(process)
    raise SystemExit(128 + int(signum))


def _install_child_signal_guard(
    process: "subprocess.Popen[str]",
) -> Dict[int, Any]:
    """Best-effort SIGINT/SIGTERM forwarding for one isolated child."""

    if threading.current_thread() is not threading.main_thread():
        return {}
    previous: Dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        def _handler(sig: int, frame: Any, _process: "subprocess.Popen[str]" = process) -> None:
            del frame
            _forward_signal_to_child(_process, sig)

        try:
            previous[signum] = signal.signal(signum, _handler)
        except (ValueError, OSError):
            previous.pop(signum, None)
    return previous


def _restore_signal_guard(previous: Dict[int, Any]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (ValueError, OSError, TypeError):
            continue


@dataclass
class UrgRunResult:
    returncode: int
    stdout: str
    stderr: str
    argv: List[str]
    scheduler: Json = field(default_factory=dict)


def _config_error(message: str, **detail: Any) -> XcovError:
    return XcovError("XCOV_URG_CONFIG_INVALID", message, **detail)


def _strict_text(value: object, name: str, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise _config_error(f"{name} is required")
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise _config_error(
            f"{name} must be a non-empty string without surrounding whitespace",
            option=name,
        )
    return value


def _positive_timeout(value: object, name: str, default: float) -> float:
    raw = default if value is None else value
    if isinstance(raw, str) and (not raw or raw != raw.strip()):
        raise _config_error(
            f"{name} must be a finite positive number without surrounding whitespace"
        )
    if isinstance(raw, bool):
        raise _config_error(f"{name} must be a finite positive number")
    try:
        parsed = float(raw)
    except (TypeError, ValueError) as exc:
        raise _config_error(f"{name} must be a finite positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise _config_error(f"{name} must be a finite positive number")
    return parsed


_MAX_WALL_TIME_SEC = 31536000.0


def _wall_time_minutes(value: object, name: str, default: float) -> int:
    """Resolve one LSF ``-W`` runtime limit from a seconds value."""

    seconds = _positive_timeout(value, name, default)
    if seconds > _MAX_WALL_TIME_SEC:
        raise _config_error(
            f"{name} must be a finite positive number of seconds "
            f"in (0, {_MAX_WALL_TIME_SEC:g}]"
        )
    return max(1, math.ceil(seconds / 60.0))


def _command(value: str | None, env_name: str, default: str) -> list[str]:
    raw = value if value is not None else os.environ.get(env_name, default)
    if not raw or raw != raw.strip():
        raise _config_error(f"{env_name} must be a non-empty shell command")
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        raise _config_error(f"{env_name} has invalid shell quoting") from exc
    if not argv:
        raise _config_error(f"{env_name} must be a non-empty shell command")
    return argv


def _canonicalize_tool_paths(argv: Sequence[str]) -> list[str]:
    result = list(argv)
    if result and result[0] == "urg":
        result[0] = get_urg_path()
    for index, token in enumerate(result[:-1]):
        if token in _PATH_OPTIONS:
            result[index + 1] = str(Path(result[index + 1]).expanduser().resolve())
    return result


class UrgRunner:
    def __init__(
        self,
        *,
        backend: Optional[str] = None,
        bsub_cmd: Optional[str] = None,
        bkill_cmd: Optional[str] = None,
        queue: Optional[str] = None,
        resource: Optional[str] = None,
        startup_timeout_sec: Optional[float] = None,
        run_timeout_sec: Optional[float] = None,
        wall_time_sec: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> None:
        selected_backend = backend or os.environ.get(
            "XVERIF_XCOV_URG_BACKEND", "direct"
        )
        if selected_backend not in {"direct", "lsf"}:
            raise _config_error(
                "XVERIF_XCOV_URG_BACKEND must be 'direct' or 'lsf'",
                backend=selected_backend,
            )
        self.backend = selected_backend
        self.queue = _strict_text(
            queue if queue is not None else os.environ.get("XVERIF_XCOV_URG_QUEUE"),
            "XVERIF_XCOV_URG_QUEUE",
            required=self.backend == "lsf",
        )
        self.resource = _strict_text(
            resource if resource is not None else os.environ.get("XVERIF_XCOV_URG_RESOURCE"),
            "XVERIF_XCOV_URG_RESOURCE",
            required=False,
        )
        self.startup_timeout_sec = _positive_timeout(
            startup_timeout_sec
            if startup_timeout_sec is not None
            else os.environ.get("XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC"),
            "XVERIF_XCOV_URG_STARTUP_TIMEOUT_SEC",
            120.0,
        )
        self.run_timeout_sec = _positive_timeout(
            run_timeout_sec
            if run_timeout_sec is not None
            else os.environ.get("XVERIF_XCOV_URG_RUN_TIMEOUT_SEC"),
            "XVERIF_XCOV_URG_RUN_TIMEOUT_SEC",
            600.0,
        )
        self.wall_time_minutes = _wall_time_minutes(
            wall_time_sec
            if wall_time_sec is not None
            else os.environ.get("XVERIF_XCOV_URG_WALL_TIME_SEC"),
            "XVERIF_XCOV_URG_WALL_TIME_SEC",
            7200.0,
        )
        self._bsub = (
            _command(bsub_cmd, "XVERIF_LSF_BSUB", "bsub")
            if self.backend == "lsf" else []
        )
        self._bkill = (
            _command(bkill_cmd, "XVERIF_LSF_BKILL", "bkill")
            if self.backend == "lsf" else []
        )
        scheduler_flags = {"-I", "-Is", "-Ip", "-K", "-q", "-R", "-J", "-W"}
        conflicting = [token for token in self._bsub if token in scheduler_flags]
        if conflicting:
            raise _config_error(
                "XVERIF_LSF_BSUB must not preconfigure inner URG scheduler flags; "
                "xcov owns -K/-J/-q/-R/-W",
                conflicting_flags=conflicting,
            )
        self.session_id = session_id or "adhoc"

    @property
    def use_bsub(self) -> bool:
        return self.backend == "lsf"

    def _job_name(self) -> str:
        return (
            f"xverif_xcov_urg_{os.getpid()}_"
            f"{time.time_ns()}_{next(_JOB_COUNTER)}"
        )

    def build_argv(
        self,
        urg_args: Sequence[str],
        *,
        job_name: Optional[str] = None,
    ) -> List[str]:
        tool_argv = _canonicalize_tool_paths(urg_args)
        if not self.use_bsub:
            return tool_argv
        name = job_name or self._job_name()
        base = list(self._bsub)
        if "-K" not in base:
            base.append("-K")
        base.extend(["-J", name, "-q", str(self.queue)])
        base.extend(["-W", str(self.wall_time_minutes)])
        if self.resource:
            base.extend(["-R", self.resource])
        base.extend(tool_argv)
        return base

    def cache_hit_metadata(self) -> Json:
        return {
            "backend": self.backend,
            "submitted": False,
            "status": "cache_hit",
            "queue": self.queue,
            "resource": self.resource,
            "wall_time_minutes": None,
            "job_name": None,
            "job_id": None,
            "exit_status": None,
        }

    def run(
        self,
        urg_args: Sequence[str],
        *,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> UrgRunResult:
        effective_timeout = min(
            self.run_timeout_sec,
            _positive_timeout(timeout, "timeout", self.run_timeout_sec),
        )
        if not self.use_bsub:
            return self._run_direct(
                urg_args,
                timeout=effective_timeout,
                cwd=cwd,
                env=env,
            )
        return self._run_lsf(
            urg_args,
            timeout=effective_timeout,
            cwd=cwd,
            env=env,
        )

    def _run_direct(
        self,
        urg_args: Sequence[str],
        *,
        timeout: float,
        cwd: Optional[str],
        env: Optional[dict],
    ) -> UrgRunResult:
        argv = self.build_argv(urg_args)
        started = time.monotonic()
        log_lifecycle_event(
            self.session_id,
            "urg.direct.start",
            True,
            {"backend": "direct", "submitted": False},
        )
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=cwd,
                env=env if env is not None else os.environ,
                # Isolate the group so a timed-out URG cannot leave
                # grandchildren behind; signals are forwarded explicitly.
                start_new_session=True,
            )
        except OSError as exc:
            scheduler = {
                "backend": "direct",
                "submitted": False,
                "status": "submission_failed",
                "queue": None,
                "resource": None,
                "job_name": None,
                "job_id": None,
                "exit_status": 127,
                "error_type": type(exc).__name__,
            }
            log_lifecycle_event(self.session_id, "urg.direct.end", False, scheduler)
            return UrgRunResult(127, "", str(exc), argv, scheduler)
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        threads = [
            threading.Thread(
                target=_drain_stream,
                args=(process.stdout, stdout_lines),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_lines),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        previous_handlers = _install_child_signal_guard(process)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            cleanup = _terminate_process_group(process)
            for thread in threads:
                thread.join(timeout=1.0)
            scheduler = {
                "backend": "direct",
                "submitted": False,
                "status": "run_timeout",
                "queue": None,
                "resource": None,
                "job_name": None,
                "job_id": None,
                "exit_status": 124,
                "cleanup": cleanup,
            }
            log_lifecycle_event(self.session_id, "urg.direct.timeout", False, scheduler)
            return UrgRunResult(
                124,
                "".join(stdout_lines),
                "".join(stderr_lines),
                argv,
                scheduler,
            )
        finally:
            _restore_signal_guard(previous_handlers)
        for thread in threads:
            thread.join(timeout=1.0)
        returncode = process.returncode
        scheduler = {
            "backend": "direct",
            "submitted": False,
            "status": "completed",
            "queue": None,
            "resource": None,
            "job_name": None,
            "job_id": None,
            "exit_status": returncode,
        }
        log_lifecycle_event(
            self.session_id,
            "urg.direct.end",
            returncode == 0,
            {**scheduler, "elapsed_ms": int((time.monotonic() - started) * 1000)},
        )
        return UrgRunResult(
            int(returncode if returncode is not None else 1),
            "".join(stdout_lines),
            "".join(stderr_lines),
            argv,
            scheduler,
        )

    def _run_lsf(
        self,
        urg_args: Sequence[str],
        *,
        timeout: float,
        cwd: Optional[str],
        env: Optional[dict],
    ) -> UrgRunResult:
        job_name = self._job_name()
        argv = self.build_argv(urg_args, job_name=job_name)
        scheduler: Json = {
            "backend": "lsf",
            # Starting the local bsub client is only a submission attempt.  A
            # scheduler job exists only after the canonical Job <id> frame.
            "submitted": False,
            "status": "submitting",
            "queue": self.queue,
            "resource": self.resource,
            "wall_time_minutes": self.wall_time_minutes,
            "job_name": job_name,
            "job_id": None,
            "exit_status": None,
        }
        log_lifecycle_event(self.session_id, "urg.lsf.submit", True, scheduler)
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=cwd,
                env=env if env is not None else os.environ,
                start_new_session=True,
            )
        except OSError as exc:
            scheduler["submitted"] = False
            scheduler["status"] = "submission_failed"
            scheduler["exit_status"] = 127
            scheduler["error_type"] = type(exc).__name__
            log_lifecycle_event(self.session_id, "urg.lsf.end", False, scheduler)
            return UrgRunResult(127, "", str(exc), argv, scheduler)
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        job_event = threading.Event()
        started_event = threading.Event()
        accept_job_identity = threading.Event()
        accept_job_identity.set()
        job_lock = threading.Lock()

        def drain(stream, target: list[str]) -> None:
            assert stream is not None
            for line in stream:
                target.append(line)
                match = _JOB_RE.search(line)
                if match:
                    with job_lock:
                        if accept_job_identity.is_set():
                            scheduler["job_id"] = match.group("job_id")
                            scheduler["submitted"] = True
                            job_event.set()
                    continue
                stripped = line.strip()
                if _START_RE.fullmatch(stripped):
                    started_event.set()
                    continue
                if _WAIT_RE.fullmatch(stripped):
                    continue
                # Some site wrappers suppress the standard Starting framing.
                # The first non-scheduler job output is still positive evidence
                # that dispatch completed.
                if job_event.is_set() and stripped:
                    started_event.set()

        threads = [
            threading.Thread(target=drain, args=(process.stdout, stdout_lines), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr_lines), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            startup_deadline = time.monotonic() + self.startup_timeout_sec
            while not started_event.is_set() and process.poll() is None:
                if job_event.is_set():
                    scheduler["status"] = "pending"
                if time.monotonic() >= startup_deadline:
                    scheduler["status"] = "startup_timeout"
                    with job_lock:
                        accept_job_identity.clear()
                    scheduler["cleanup"] = self._cleanup_lsf(process, scheduler)
                    return self._result(process, argv, stdout_lines, stderr_lines, scheduler, 124, threads)
                started_event.wait(0.02)
            if process.poll() is not None:
                scheduler["status"] = (
                    "completed" if process.returncode == 0 else "submission_rejected"
                )
                scheduler["exit_status"] = process.returncode
                return self._result(
                    process, argv, stdout_lines, stderr_lines, scheduler,
                    int(process.returncode if process.returncode is not None else 1),
                    threads,
                )
            scheduler["status"] = "running"
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                scheduler["status"] = "run_timeout"
                with job_lock:
                    accept_job_identity.clear()
                scheduler["cleanup"] = self._cleanup_lsf(process, scheduler)
                return self._result(process, argv, stdout_lines, stderr_lines, scheduler, 124, threads)
            scheduler["status"] = (
                "completed" if process.returncode == 0 else "failed"
            )
            scheduler["exit_status"] = process.returncode
            return self._result(
                process, argv, stdout_lines, stderr_lines, scheduler,
                int(process.returncode or 0), threads,
            )
        except BaseException:
            scheduler["status"] = "cancelled"
            with job_lock:
                accept_job_identity.clear()
            scheduler["cleanup"] = self._cleanup_lsf(process, scheduler)
            raise

    def _cleanup_lsf(self, process: subprocess.Popen[str], scheduler: Json) -> Json:
        target = (
            [str(scheduler["job_id"])]
            if scheduler.get("job_id")
            else ["-J", str(scheduler["job_name"])]
        )
        cleanup: Json = {"target": "job_id" if scheduler.get("job_id") else "job_name"}
        try:
            killed = subprocess.run(
                [*self._bkill, *target],
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False,
            )
            cleanup["bkill_returncode"] = killed.returncode
            cleanup["bkill_ok"] = killed.returncode == 0
        except Exception as exc:
            cleanup["bkill_ok"] = False
            cleanup["bkill_error_type"] = type(exc).__name__
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5.0)
                cleanup["process"] = "terminated"
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5.0)
                    cleanup["process"] = "killed"
                except (OSError, subprocess.TimeoutExpired):
                    cleanup["process"] = "unresolved"
        else:
            cleanup["process"] = "already_exited"
        cleanup["complete"] = bool(cleanup.get("bkill_ok")) and cleanup["process"] != "unresolved"
        log_lifecycle_event(
            self.session_id,
            "urg.lsf.cleanup",
            bool(cleanup["complete"]),
            {**scheduler, "cleanup": cleanup},
        )
        return cleanup

    def _result(
        self,
        process: subprocess.Popen[str],
        argv: list[str],
        stdout_lines: list[str],
        stderr_lines: list[str],
        scheduler: Json,
        returncode: int,
        threads: list[threading.Thread],
    ) -> UrgRunResult:
        for thread in threads:
            thread.join(timeout=1.0)
        scheduler["exit_status"] = returncode
        ok = returncode == 0 and scheduler.get("status") == "completed"
        log_lifecycle_event(self.session_id, "urg.lsf.end", ok, scheduler)
        return UrgRunResult(
            returncode,
            "".join(stdout_lines),
            "".join(stderr_lines),
            argv,
            dict(scheduler),
        )
