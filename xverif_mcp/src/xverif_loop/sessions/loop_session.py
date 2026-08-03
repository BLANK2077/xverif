"""LoopSession — single --stdio-loop process backed session."""

from __future__ import annotations

import re
import hashlib
import os
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional

from xverif_loop.lsf.protocol import JsonlProcess, ProtocolError
from xverif_loop.json_contract import (
    redact_sensitive_json,
    strict_json_dumps,
    strict_json_loads,
)
from xverif_loop.logging import StructuredLogger, StructuredLoggingError

from xverif_loop.config import RuntimeConfig, default_xdebug_bin
from xverif_loop.sessions.launchers import LaunchConfig, Launcher
from xverif_loop.sessions.capabilities import lifecycle_capability
from xverif_loop.sessions.session_errors import response_says_session_terminal
from xverif_loop.xdebug_errors import translate_native_example_for_query

Json = Dict[str, Any]


def _serialized_lifecycle(method):
    """Linearize an operation and redact its terminal public value."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lifecycle_lock:
            result = method(self, *args, **kwargs)
            return redact_sensitive_json(
                result,
                secret_values=(self._ownership_token,),
            )

    return wrapped


def _safe_name(s: str, max_len: int = 64) -> str:
    x = re.sub(r"[^A-Za-z0-9_]", "_", s).strip("_")
    return (x or "unnamed")[:max_len]


def _error(code: str, message: str, **extra: Any) -> Json:
    err: Json = {"code": code, "message": message}
    err.update(extra)
    return {"ok": False, "error": err}


def _extract_session_id(response: Json, backend: str) -> Optional[str]:
    """Read the native session id from the backend's declared response path."""
    value: Any = response
    for key in lifecycle_capability(backend).session_id_path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, str) and value else None


def _trace_id(alias: str, request_id: str) -> str:
    return f"mcp-{_safe_name(alias)}-{request_id}"


def _attach_trace_id(request: Json, backend: str, alias: str) -> Optional[str]:
    """Attach a trace id only when it is part of the native backend contract."""
    capability = lifecycle_capability(backend)
    if not capability.accepts_trace_id:
        return None
    trace_id = _trace_id(alias, str(request["request_id"]))
    request["trace_id"] = trace_id
    return trace_id


def _backend_payload(response: Json) -> Json:
    payload = response.get("json")
    return payload if isinstance(payload, dict) else response


def _response_error_code(response: Json) -> Optional[str]:
    error = response.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    return None


def _request_native_json(request: Json, backend: str) -> Json:
    capability = lifecycle_capability(backend)
    if capability.json_request_style == "loop_marker":
        request["payload_format"] = "json"
    elif capability.json_request_style == "transport_envelope":
        # xcov stdio-loop always includes the structured JSON payload in its
        # transport envelope; public request fields remain untouched.
        pass
    else:
        raise ValueError(
            f"unsupported native JSON request style: {capability.json_request_style}"
        )
    return request


@dataclass
class XdebugLoopSession:
    alias: str
    fsdb: Optional[str]
    daidir: Optional[str]
    launcher: Launcher
    runtime: RuntimeConfig
    logger: StructuredLogger
    xdebug_bin: str = field(default_factory=default_xdebug_bin)
    backend: str = "xdebug"
    api_version: str = "xdebug.v1"
    ready_protocol: str = "xdebug-stdio-loop"
    target_key: str = "fsdb"
    recovery_tool: str = "xverif_debug_session_open"
    run_manifest: Optional[str] = None
    queue: Optional[str] = None
    resource: Optional[str] = None
    job_name: Optional[str] = None
    session_id: Optional[str] = None
    state: str = "new"
    handle: Optional[JsonlProcess] = None
    pid: Optional[int] = None
    last_error: Optional[str] = None
    last_cleanup: Json = field(default_factory=dict)
    _ownership_token: Optional[str] = field(
        default=None,
        repr=False,
    )
    _seq: int = 0
    _lifecycle_lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )

    def _attach_observability(
        self,
        response: Json,
        cursor: int,
    ) -> Json:
        status = self.logger.observability_status(cursor)
        if not status["ok"]:
            response["observability"] = status
        return response

    def _observability_error(
        self,
        *,
        message: str,
        cursor: int,
        operation_started: bool,
    ) -> Json:
        return _error(
            "OBSERVABILITY_FAILURE",
            message,
            operation_started=operation_started,
            observability=self.logger.observability_status(cursor),
        )

    @_serialized_lifecycle
    def process_alive(self) -> bool:
        h = self.handle
        if h is None:
            return False
        proc = getattr(h, "proc", None)
        return proc is not None and proc.poll() is None

    @_serialized_lifecycle
    def abort(self, reason: str, source: str = "transport") -> Json:
        self.state = "dead"
        self.last_error = reason
        capability = lifecycle_capability(self.backend)
        cleanup: Json = {
            "source": source,
            "subprocess": "not_started",
            "lsf_job": "not_applicable",
            "backend_cleanup": (
                "unconfirmed"
                if capability.backend_survives_loop
                else "not_applicable"
            ),
        }
        self.logger.try_session(
            self.alias,
            "session.abort.begin",
            False,
            backend=self.backend,
            launcher=self.launcher.mode,
            session_id=self.session_id,
            reason=reason,
            source=source,
            state=self.state,
        )
        handle = self.handle
        self.handle = None
        if handle is not None:
            try:
                termination = self.launcher.terminate(handle)
                cleanup["subprocess"] = "terminated"
                cleanup["termination"] = termination
                if getattr(handle, "job_id", None) or getattr(handle, "job_name", None):
                    cleanup["lsf_job"] = "confirmed"
            except Exception as exc:
                cleanup["subprocess"] = "cleanup_failed"
                cleanup["cleanup_error"] = str(exc)
                cleanup["termination"] = getattr(
                    exc,
                    "result",
                    {"ok": False, "error_type": type(exc).__name__},
                )
        self.last_cleanup = cleanup
        self.logger.try_session(
            self.alias,
            "session.abort.end",
            cleanup.get("subprocess") != "cleanup_failed",
            backend=self.backend,
            launcher=self.launcher.mode,
            session_id=self.session_id,
            cleanup=cleanup,
            job_id=(
                getattr(handle, "job_id", None)
                if handle
                else None
            ),
            job_name=(
                getattr(handle, "job_name", None)
                if handle
                else None
            ),
        )
        return cleanup

    def _session_lost_error(self, message: str, *, source: str,
                             backend_response: Optional[Json] = None,
                             cleanup: Optional[Json] = None) -> Json:
        # Build recovery hint — for timeouts, include contextual advice
        if source == "transport" and "timeout" in message.lower():
            reason = (
                "session lost due to timeout — "
                "possible causes: large FSDB / deep trace / complex query, "
                "or LSF queue congestion delaying job start. "
                "If caused by large data, try narrowing time_range or limits. "
                "If caused by LSF queue delay, consider increasing "
                "XVERIF_MCP_STARTUP_TIMEOUT_SEC (session open, default 180s) "
                "or XVERIF_MCP_REQUEST_TIMEOUT_SEC (query, default 360s). "
                "Close or gc the stale session, then open a new session before retrying."
            )
        else:
            reason = "session is no longer reusable; close or gc it before opening a new session"

        return _error("SESSION_LOST", message,
                       session_id=self.session_id, mode=self.launcher.mode,
                       terminal_source=source, backend_response=backend_response,
                       cleanup=cleanup or self.last_cleanup,
                       recovery_hint={
                           "action": self.recovery_tool,
                           "reason": reason,
                           "env_vars": {
                               "XVERIF_MCP_STARTUP_TIMEOUT_SEC":
                                   "session open timeout (default 180s)",
                               "XVERIF_MCP_REQUEST_TIMEOUT_SEC":
                                   "query timeout (default 360s)",
                           },
                       })

    @staticmethod
    def _conditional_cleanup_outcome(response: Json) -> str:
        if response.get("ok") is True:
            return "cleaned"
        code = _response_error_code(response)
        if code == "SESSION_NOT_FOUND":
            return "not_created"
        if code == "SESSION_OWNERSHIP_TOKEN_MISMATCH":
            return "token_mismatch"
        return "cleanup_failed"

    def _finish_dispatched_open(
        self,
        *,
        code: str,
        message: str,
        backend_response: Optional[Json],
        source: str,
    ) -> Json:
        """Resolve a dispatched open by conditionally cleaning only our record."""

        cleanup = self.abort(message, source=source)
        capability = lifecycle_capability(self.backend)
        process_cleanup_complete = (
            cleanup.get("subprocess") in {"not_started", "terminated"}
        )

        cleanup_outcome = "not_applicable"
        conditional_response: Optional[Json] = None
        if capability.supports_conditional_cleanup_token:
            if (
                not capability.native_kill_action
                or not self._ownership_token
            ):
                cleanup_outcome = "cleanup_failed"
            else:
                conditional_response = self._call_native_admin(
                    capability.native_kill_action,
                    session_id=self.alias,
                    ownership_token=self._ownership_token,
                )
                cleanup_outcome = self._conditional_cleanup_outcome(
                    conditional_response
                )
            cleanup["backend_cleanup"] = cleanup_outcome
            cleanup["conditional_cleanup"] = {
                "outcome": cleanup_outcome,
                "backend_error_code": (
                    _response_error_code(conditional_response)
                    if isinstance(conditional_response, dict)
                    else None
                ),
            }
        elif capability.backend_survives_loop:
            cleanup_outcome = "cleanup_failed"
            cleanup["backend_cleanup"] = cleanup_outcome
        else:
            cleanup["backend_cleanup"] = "not_applicable"

        cleanup_complete = (
            process_cleanup_complete
            and cleanup_outcome != "cleanup_failed"
        )
        if cleanup_complete:
            self.state = "closed"
        else:
            self.state = (
                "orphan_suspected"
                if capability.backend_survives_loop
                else "cleanup_partial"
            )
        self.last_cleanup = cleanup
        return _error(
            code,
            message,
            requested_session_id=self.alias,
            backend_error_code=(
                _response_error_code(backend_response)
                if isinstance(backend_response, dict)
                else None
            ),
            ownership_confirmed=False,
            cleanup_complete=cleanup_complete,
            cleanup_outcome=(
                "cleanup_failed"
                if not cleanup_complete
                else cleanup_outcome
            ),
            cleanup=cleanup,
            backend_response=backend_response,
        )

    @_serialized_lifecycle
    def open(self) -> Json:
        if self.state not in ("new", "closed", "dead"):
            return _error("SESSION_EXISTS", f"session already opened: {self.alias}")
        observability_cursor = self.logger.failure_cursor()
        t0 = time.monotonic()
        capability = lifecycle_capability(self.backend)
        self._ownership_token = (
            secrets.token_hex(32)
            if capability.supports_conditional_cleanup_token
            else None
        )
        try:
            self.logger.session(
                self.alias,
                "session.open.begin",
                True,
                backend=self.backend,
                launcher=self.launcher.mode,
                fsdb=self.fsdb,
                daidir=self.daidir,
                queue=self.queue,
                resource=self.resource,
                job_name=self.job_name,
            )
        except StructuredLoggingError:
            self.state = "closed"
            return self._observability_error(
                message=(
                    "session.open was not started because its begin event "
                    "could not be published"
                ),
                cursor=observability_cursor,
                operation_started=False,
            )
        cfg = LaunchConfig(alias=self.alias, xdebug_bin=self.xdebug_bin,
                           runtime=self.runtime,
                           backend=self.backend,
                           tool_bin=self.xdebug_bin,
                           queue=self.queue, resource=self.resource,
                           job_name=self.job_name,
                           startup_timeout_sec=self.runtime.startup_timeout_sec,
                           logger=self.logger)
        native_open_started = False
        try:
            self.handle = self.launcher.start(cfg)
            ready = self.handle.wait_ready(
                self.ready_protocol,
                self.runtime.startup_timeout_sec,
            )
            self.pid = int(ready.get("pid") or 0)
            open_req: Json = {
                "request_id": f"open-{_safe_name(self.alias)}",
                "api_version": self.api_version,
                "action": lifecycle_capability(self.backend).native_open_action,
                "target": {},
                "args": {"name": self.alias},
            }
            _attach_trace_id(open_req, self.backend, self.alias)
            if capability.managed_transport:
                open_req["args"]["transport"] = capability.managed_transport
            if self._ownership_token:
                open_req["args"]["ownership_token"] = (
                    self._ownership_token
                )
            _request_native_json(open_req, self.backend)
            if self.fsdb:
                open_req["target"][self.target_key] = self.fsdb
            if self.daidir:
                open_req["target"]["daidir"] = self.daidir
            if self.run_manifest:
                open_req["target"]["run_manifest"] = self.run_manifest
            native_open_started = True
            rsp = self._call_raw(
                open_req,
                timeout=self.runtime.startup_timeout_sec,
            )
            if not rsp.get("ok"):
                result = self._finish_dispatched_open(
                    code="SESSION_OPEN_REJECTED",
                    message=(
                        "backend rejected session.open after dispatch; "
                        "conditional cleanup resolved whether the requested "
                        "session record belonged to this open"
                    ),
                    backend_response=_backend_payload(rsp),
                    source="open_rejected",
                )
                self.logger.try_session(
                    self.alias,
                    "session.open.end",
                    False,
                    backend=self.backend,
                    launcher=self.launcher.mode,
                    elapsed_ms=int(
                        (time.monotonic() - t0) * 1000
                    ),
                    response=result,
                )
                return self._attach_observability(
                    result,
                    observability_cursor,
                )
            payload = rsp.get("json", rsp)
            self.session_id = _extract_session_id(payload, self.backend)
            if not self.session_id:
                result = self._finish_dispatched_open(
                    code="BACKEND_SESSION_ID_MISSING",
                    message=(
                        "backend session.open response did not include the "
                        "canonical session.session_id"
                    ),
                    backend_response=payload,
                    source="open_response_invalid",
                )
                self.logger.try_session(
                    self.alias,
                    "session.open.end",
                    False,
                    backend=self.backend,
                    launcher=self.launcher.mode,
                    response=result,
                )
                return self._attach_observability(
                    result,
                    observability_cursor,
                )
            if self.session_id != self.alias:
                backend_session_id = self.session_id
                self.session_id = None
                mismatch = self._finish_dispatched_open(
                    code="BACKEND_SESSION_ID_MISMATCH",
                    message=(
                        "backend session.open did not preserve the requested "
                        "session_id"
                    ),
                    backend_response=payload,
                    source="open_response_invalid",
                )
                mismatch["error"]["backend_session_id"] = (
                    backend_session_id
                )
                self.logger.try_session(
                    self.alias,
                    "session.open.end",
                    False,
                    backend=self.backend,
                    launcher=self.launcher.mode,
                    response=mismatch,
                )
                return self._attach_observability(
                    mismatch,
                    observability_cursor,
                )
            self.state = "alive"
            self.logger.try_session(
                self.alias,
                "session.open.end",
                True,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                pid=self.pid,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                job_id=(
                    getattr(self.handle, "job_id", None)
                    if self.handle
                    else None
                ),
                job_name=(
                    getattr(self.handle, "job_name", None)
                    if self.handle
                    else None
                ),
            )
            return self._attach_observability(
                {"ok": True, "session": self.public_json()},
                observability_cursor,
            )
        except Exception as exc:
            if native_open_started:
                result = self._finish_dispatched_open(
                    code="SESSION_OPEN_TRANSPORT_FAILED",
                    message=(
                        "session.open transport failed after native dispatch; "
                        "conditional cleanup was executed against the "
                        "requested session id"
                    ),
                    backend_response=None,
                    source="open_transport",
                )
                self.logger.try_session(
                    self.alias,
                    "session.open.end",
                    False,
                    backend=self.backend,
                    launcher=self.launcher.mode,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                    error_type=type(exc).__name__,
                    cleanup=result["error"]["cleanup"],
                )
                return self._attach_observability(
                    result,
                    observability_cursor,
                )
            cleanup = self.abort(
                "session.open failed before native dispatch",
                source="open_startup",
            )
            self.logger.try_session(
                self.alias,
                "session.open.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                error_type=type(exc).__name__,
                cleanup=cleanup,
            )
            result = _error(
                "SESSION_OPEN_FAILED",
                "session.open failed before native dispatch",
                error_type=type(exc).__name__,
                cleanup_complete=(
                    cleanup.get("subprocess")
                    in {"not_started", "terminated"}
                ),
                cleanup=cleanup,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )

    @_serialized_lifecycle
    def close(self, force: bool = False) -> Json:
        observability_cursor = self.logger.failure_cursor()
        self.logger.try_session(
            self.alias,
            "session.close.begin",
            True,
            backend=self.backend,
            launcher=self.launcher.mode,
            session_id=self.session_id,
            force=force,
            state=self.state,
        )
        cleanup: Json = {
            "backend_close": "skipped",
            "stdio_quit": "skipped",
            "terminate": "skipped",
        }
        errors: Json = {}
        if self.handle and self.state == "alive" and self.session_id and not force:
            try:
                req = {
                    "request_id": f"close-{_safe_name(self.alias)}",
                    "api_version": self.api_version,
                    "action": lifecycle_capability(self.backend).native_close_action,
                    "target": {"session_id": self.session_id},
                }
                _attach_trace_id(req, self.backend, self.alias)
                _request_native_json(req, self.backend)
                backend_rsp = self._call_raw(
                    req,
                    timeout=self.runtime.close_timeout_sec,
                )
                backend_payload = _backend_payload(backend_rsp)
                if not backend_rsp.get("ok", False) or not backend_payload.get("ok", False):
                    cleanup["backend_close"] = "failed"
                    errors["backend_close"] = backend_payload
                else:
                    cleanup["backend_close"] = "ok"
            except Exception as exc:
                cleanup["backend_close"] = "failed"
                errors["backend_close"] = str(exc)
            try:
                req = {
                    "request_id": f"quit-{_safe_name(self.alias)}",
                    "api_version": self.api_version, "action": "stdio.quit",
                }
                _attach_trace_id(req, self.backend, self.alias)
                self._call_raw(
                    req,
                    timeout=self.runtime.close_timeout_sec / 2,
                )
                cleanup["stdio_quit"] = "ok"
            except Exception as exc:
                if not self.process_alive():
                    cleanup["stdio_quit"] = "ok_process_exited"
                else:
                    cleanup["stdio_quit"] = "failed"
                    errors["stdio_quit"] = str(exc)
        elif force:
            cleanup["backend_close"] = "force_skipped"
            cleanup["stdio_quit"] = "force_skipped"
        if self.handle:
            try:
                termination = self.launcher.terminate(self.handle)
                cleanup["terminate"] = "ok"
                cleanup["termination"] = termination
            except Exception as exc:
                cleanup["terminate"] = "failed"
                errors["terminate"] = str(exc)
                cleanup["termination"] = getattr(
                    exc,
                    "result",
                    {"ok": False, "error_type": type(exc).__name__},
                )
        self.last_cleanup = cleanup
        if errors:
            cleanup["errors"] = errors
            self.logger.try_session(
                self.alias,
                "session.close.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                state=self.state,
                cleanup=cleanup,
            )
            result = _error(
                "SESSION_CLEANUP_PARTIAL_FAILURE",
                "session cleanup failed; retry close or inspect cleanup details",
                cleanup_complete=False,
                cleanup=cleanup,
                session=self.public_json(),
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        self.state = "closed"
        self.logger.try_session(
            self.alias,
            "session.close.end",
            True,
            backend=self.backend,
            launcher=self.launcher.mode,
            session_id=self.session_id,
            state=self.state,
            cleanup=cleanup,
        )
        return self._attach_observability(
            {
                "ok": True,
                "closed": self.public_json(),
                "cleanup": cleanup,
            },
            observability_cursor,
        )

    @_serialized_lifecycle
    def doctor(self, verbose: bool = False) -> Json:
        capability = lifecycle_capability(self.backend)
        transport_alive = self.process_alive()
        backend_response: Optional[Json] = None
        source = "loop"
        if self.state == "alive" and transport_alive and self.session_id:
            req: Json = {
                "request_id": f"doctor-{_safe_name(self.alias)}",
                "api_version": self.api_version,
                "action": capability.native_health_action,
                "target": {"session_id": self.session_id},
            }
            _attach_trace_id(req, self.backend, self.alias)
            _request_native_json(req, self.backend)
            try:
                backend_response = _backend_payload(self._call_raw(req))
            except Exception as exc:
                backend_response = _error("DOCTOR_TRANSPORT_FAILED", str(exc))
        elif capability.fixed_admin_path and self.session_id:
            source = "fixed_native_admin"
            backend_response = self._call_native_admin(capability.native_health_action)
        backend_ok = bool(backend_response and backend_response.get("ok"))
        unresolved = (
            self.state == "alive" and not backend_ok
        ) or (
            self.state != "closed" and capability.backend_survives_loop and not backend_ok
        )
        return {
            "ok": True,
            "summary": {
                "session_id": self.session_id,
                "management_key": self.alias,
                "ownership": "managed",
                "ownership_confirmed": self.session_id is not None,
                "backend": self.backend,
                "state": self.state,
                "transport_alive": transport_alive,
                "backend_health_known": backend_response is not None,
                "backend_healthy": backend_ok,
                "unresolved": unresolved,
                "source": source,
                "read_only": True,
            },
            "session": self.public_json(verbose=verbose),
            "backend_response": backend_response if verbose else None,
            "observability": self.logger.observability_status(),
        }

    @_serialized_lifecycle
    def kill(self) -> Json:
        observability_cursor = self.logger.failure_cursor()
        capability = lifecycle_capability(self.backend)
        self.logger.try_session(
            self.alias,
            "session.kill.begin",
            True,
            backend=self.backend,
            launcher=self.launcher.mode,
            session_id=self.session_id,
            state=self.state,
        )
        stages: Json = {
            "native_kill": (
                "not_supported"
                if capability.native_kill_action is None
                else "pending"
            ),
            "loop_terminate": "not_started",
            "lsf_job": "not_applicable",
        }
        errors: Json = {}
        response: Optional[Json] = None
        transport_ambiguous = False
        conditional_target = self.session_id or self.alias
        conditional_token = (
            self._ownership_token
            if capability.supports_conditional_cleanup_token
            else None
        )

        if (
            capability.native_kill_action
            and self.session_id
            and self.state == "alive"
            and self.process_alive()
        ):
            req: Json = {
                "request_id": f"kill-{_safe_name(self.alias)}",
                "api_version": self.api_version,
                "action": capability.native_kill_action,
                "target": {"session_id": self.session_id},
            }
            if conditional_token:
                req["args"] = {
                    "ownership_token": conditional_token,
                }
            _attach_trace_id(req, self.backend, self.alias)
            _request_native_json(req, self.backend)
            try:
                response = _backend_payload(
                    self._call_raw(
                        req,
                        timeout=self.runtime.close_timeout_sec,
                    )
                )
            except Exception as exc:
                transport_ambiguous = True
                stages["native_kill"] = "transport_unresolved"
                errors["native_transport"] = {
                    "error_type": type(exc).__name__,
                }
        elif capability.native_kill_action and capability.fixed_admin_path:
            response = self._call_native_admin(
                capability.native_kill_action,
                session_id=conditional_target,
                ownership_token=conditional_token,
            )
        elif capability.native_kill_action:
            response = _error(
                "NATIVE_KILL_UNAVAILABLE",
                "native kill path unavailable",
            )

        handle = self.handle
        self.handle = None
        if handle is not None:
            try:
                termination = self.launcher.terminate(handle)
                stages["loop_terminate"] = "ok"
                stages["termination"] = termination
                if (
                    getattr(handle, "job_id", None)
                    or getattr(handle, "job_name", None)
                ):
                    stages["lsf_job"] = "confirmed"
            except Exception as exc:
                stages["loop_terminate"] = "failed"
                errors["loop_terminate"] = {
                    "error_type": type(exc).__name__,
                }
                stages["termination"] = getattr(
                    exc,
                    "result",
                    {"ok": False, "error_type": type(exc).__name__},
                )
        else:
            stages["loop_terminate"] = "already_exited"

        if (
            transport_ambiguous
            and capability.native_kill_action
            and capability.fixed_admin_path
        ):
            # The loop response is unknowable after transport loss.  Resolve
            # this same cleanup operation through the fixed admin path using
            # the conditional key; this cannot remove an alias owned by a
            # different session.open.
            response = self._call_native_admin(
                capability.native_kill_action,
                session_id=conditional_target,
                ownership_token=conditional_token,
            )
            stages["native_kill_resolution"] = "fixed_native_admin"
            errors.pop("native_transport", None)

        if capability.native_kill_action:
            if response is None:
                stages["native_kill"] = "failed"
                errors["native_kill"] = {
                    "code": "NATIVE_KILL_RESPONSE_MISSING",
                }
            elif response.get("ok") is True:
                stages["native_kill"] = "ok"
                stages["cleanup_outcome"] = "cleaned"
            else:
                outcome = (
                    self._conditional_cleanup_outcome(response)
                    if conditional_token
                    else "cleanup_failed"
                )
                stages["cleanup_outcome"] = outcome
                if outcome in {"not_created", "token_mismatch"}:
                    stages["native_kill"] = outcome
                else:
                    stages["native_kill"] = "failed"
                    errors["native_kill"] = response

        self.last_cleanup = stages
        if errors:
            stages["errors"] = errors
            self.state = (
                "orphan_suspected"
                if capability.backend_survives_loop
                else "cleanup_partial"
            )
            result = _error(
                "SESSION_CLEANUP_PARTIAL_FAILURE",
                "session kill cleanup was only partially confirmed",
                cleanup_complete=False,
                cleanup_outcome="cleanup_failed",
                cleanup=stages,
                session=self.public_json(),
            )
            self.logger.try_session(
                self.alias,
                "session.kill.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                cleanup=stages,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        self.state = "closed"
        self.logger.try_session(
            self.alias,
            "session.kill.end",
            True,
            backend=self.backend,
            launcher=self.launcher.mode,
            cleanup=stages,
        )
        return self._attach_observability({
            "ok": True,
            "killed": self.public_json(),
            "cleanup": stages,
        }, observability_cursor)

    def _call_native_admin(
        self,
        action: str,
        *,
        session_id: Optional[str] = None,
        ownership_token: Optional[str] = None,
    ) -> Json:
        target_session_id = session_id or self.session_id
        if not target_session_id:
            return _error(
                "SESSION_ID_MISSING",
                "backend session id is unavailable",
            )
        request: Json = {
            "api_version": self.api_version,
            "action": action,
            "target": {"session_id": target_session_id},
        }
        if ownership_token:
            if action != "session.kill":
                return _error(
                    "INVALID_ADMIN_REQUEST",
                    "conditional cleanup key is only valid for session.kill",
                )
            request["args"] = {
                "ownership_token": ownership_token,
            }
        try:
            proc = subprocess.run(
                [self.xdebug_bin, "--json", "-"],
                input=strict_json_dumps(request) + "\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.runtime.close_timeout_sec,
                check=False,
            )
        except Exception as exc:
            return _error(
                "ADMIN_PATH_FAILED",
                "native admin command could not be executed",
                action=action,
                error_type=type(exc).__name__,
            )
        try:
            payload = strict_json_loads(proc.stdout)
        except (TypeError, ValueError) as exc:
            return _error(
                "ADMIN_BAD_RESPONSE",
                "native admin response is not strict JSON",
                action=action,
                exit_code=proc.returncode,
                error_type=type(exc).__name__,
                stdout_present=bool(proc.stdout),
                stderr_present=bool(proc.stderr),
            )
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("ok"), bool)
        ):
            return _error(
                "ADMIN_BAD_RESPONSE",
                "native admin response must be an object with boolean ok",
                action=action,
                exit_code=proc.returncode,
                stdout_present=bool(proc.stdout),
                stderr_present=bool(proc.stderr),
            )
        if proc.returncode != 0 and payload["ok"]:
            return _error(
                "ADMIN_PATH_FAILED",
                "native admin command exited unsuccessfully",
                action=action,
                exit_code=proc.returncode,
                stdout_present=bool(proc.stdout),
                stderr_present=bool(proc.stderr),
            )
        return payload

    @_serialized_lifecycle
    def query(self, action: str, args: Optional[Json] = None,
              target: Optional[Json] = None, limits: Optional[Json] = None,
              output: Optional[Json] = None, output_format: str = "xout",
              retain_transport_envelope: bool = False) -> Any:
        if self.state != "alive" or not self.session_id:
            return _error("SESSION_DEAD", f"session is not alive: {self.alias}")
        if self.backend == "xcov" and (limits is not None or output is not None):
            return _error(
                "INVALID_ARGUMENT",
                "xcov limits and artifact output must be nested inside action args",
                error_layer="wrapper",
            )
        self._seq += 1
        req: Json = {
            "request_id": f"{_safe_name(self.alias)}-{self._seq}",
            "api_version": self.api_version, "action": action,
        }
        trace_id = _attach_trace_id(req, self.backend, self.alias)
        if args is not None:
            req["args"] = args
        req["target"] = {"session_id": self.session_id}
        if limits is not None:
            req["limits"] = limits
        if self.backend == "xcov":
            # xcov stdio-loop always returns both JSON and XOUT in its transport
            # envelope. Public response selection is a wrapper concern; native
            # xcov requests do not accept top-level output/response_format.
            pass
        elif output_format in ("json", "envelope"):
            req["payload_format"] = "json"
        else:
            req["payload_format"] = "xout"
        observability_cursor = self.logger.failure_cursor()
        try:
            self.logger.session(
                self.alias,
                "query.begin",
                True,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                request_id=req["request_id"],
                trace_id=trace_id,
                action=action,
            )
        except StructuredLoggingError:
            return self._observability_error(
                message=(
                    "query was not sent because its begin event could not "
                    "be published"
                ),
                cursor=observability_cursor,
                operation_started=False,
            )
        try:
            rsp = self._call_raw(req)
        except StructuredLoggingError:
            return self._observability_error(
                message=(
                    "query was not sent because the transport begin event "
                    "could not be published"
                ),
                cursor=observability_cursor,
                operation_started=False,
            )
        except ProtocolError as exc:
            cleanup = self.abort(str(exc), source="transport")
            self.logger.try_session(
                self.alias,
                "query.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                request_id=req["request_id"],
                action=action,
                terminal_source="transport",
                cleanup=cleanup,
                error_type=type(exc).__name__,
            )
            result = self._session_lost_error(
                f"{self.backend} stdio-loop transport lost: {exc}",
                source="transport",
                cleanup=cleanup,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        except OSError as exc:
            cleanup = self.abort(str(exc), source="io")
            self.logger.try_session(
                self.alias,
                "query.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                request_id=req["request_id"],
                action=action,
                terminal_source="io",
                cleanup=cleanup,
                error_type=type(exc).__name__,
            )
            result = self._session_lost_error(
                f"{self.backend} stdio-loop io error: {exc}",
                source="io",
                cleanup=cleanup,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        except Exception as exc:
            cleanup = self.abort(str(exc), source="unexpected")
            self.logger.try_session(
                self.alias,
                "query.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                request_id=req["request_id"],
                action=action,
                terminal_source="unexpected",
                cleanup=cleanup,
                error_type=type(exc).__name__,
            )
            result = self._session_lost_error(
                f"{self.backend} stdio-loop unexpected failure: {exc}",
                source="unexpected",
                cleanup=cleanup,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        if response_says_session_terminal(rsp):
            cleanup = self.abort(
                f"backend reported terminal session after action {action}",
                source="backend_response")
            self.logger.try_session(
                self.alias,
                "query.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                request_id=req["request_id"],
                action=action,
                terminal_source="backend_response",
                backend_response=rsp,
                cleanup=cleanup,
            )
            result = self._session_lost_error(
                f"{self.backend} backend reported terminal session after action {action}",
                source="backend_response",
                backend_response=rsp,
                cleanup=cleanup,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        if not rsp.get("ok"):
            self.logger.try_session(
                self.alias,
                "query.end",
                False,
                backend=self.backend,
                launcher=self.launcher.mode,
                session_id=self.session_id,
                request_id=req["request_id"],
                action=action,
                response=rsp,
            )
            if not self.logger.observability_status(
                observability_cursor
            )["ok"]:
                return self._observability_error(
                    message=(
                        "backend query completed, but its outcome could not "
                        "be fully published to the structured log"
                    ),
                    cursor=observability_cursor,
                    operation_started=True,
                )
            if self.backend == "xdebug":
                backend_response = rsp.get("json") if isinstance(rsp.get("json"), dict) else {
                    "ok": False,
                    "action": action,
                    "error": rsp.get("error", {}),
                }
                shaped = translate_native_example_for_query(
                    backend_response,
                    session_id=self.session_id,
                )
                if output_format == "xout":
                    # Wrapper-generated errors remain structured JSON. Only the
                    # Native frontend owns compact XOUT; do not invent
                    # a second error grammar in the loop layer.
                    if retain_transport_envelope:
                        out = dict(rsp)
                        out["json"] = shaped
                        out["error"] = shaped.get(
                            "error",
                            rsp.get("error", {}),
                        )
                        return out
                    return shaped
                if output_format == "json":
                    return shaped
                if output_format == "envelope":
                    out = dict(rsp)
                    out["json"] = shaped
                    out["error"] = shaped.get("error", rsp.get("error", {}))
                    return out
            return rsp
        self.logger.try_session(
            self.alias,
            "query.end",
            True,
            backend=self.backend,
            launcher=self.launcher.mode,
            session_id=self.session_id,
            request_id=req["request_id"],
            action=action,
        )
        if not self.logger.observability_status(
            observability_cursor
        )["ok"]:
            result = self._observability_error(
                message=(
                    "backend query completed, but its outcome could not be "
                    "fully published to the structured log"
                ),
                cursor=observability_cursor,
                operation_started=True,
            )
            result["error"]["backend_result"] = {
                "received": True,
                "ok": True,
                "output_format": output_format,
            }
            return result
        if output_format == "xout":
            return rsp if retain_transport_envelope else rsp.get("xout", "")
        if output_format == "json":
            return rsp.get("json", rsp)
        if output_format == "envelope":
            return rsp
        return _error("INVALID_OUTPUT_FORMAT", f"unsupported: {output_format}")

    def _call_raw(self, req: Json, timeout: Optional[float] = None) -> Json:
        if not self.handle:
            return _error("SESSION_PROCESS_MISSING", "no loop process")
        with self._lifecycle_lock:
            return self.handle.request(
                req,
                timeout_sec=(
                    self.runtime.request_timeout_sec
                    if timeout is None
                    else timeout
                ),
            )

    @_serialized_lifecycle
    def public_json(self, verbose: bool = False) -> Json:
        h = self.handle
        out: Json = {
            "session_id": self.session_id,
            "management_key": self.alias,
            "ownership": "managed",
            "ownership_confirmed": self.session_id is not None,
            "state": self.state,
            "launcher": self.launcher.mode,
            "backend": self.backend,
        }
        resource_path = self.fsdb or self.daidir
        if resource_path:
            out[self.target_key if self.fsdb else "daidir"] = os.path.basename(resource_path)
            path_hash = hashlib.sha256(
                os.path.abspath(resource_path).encode("utf-8")).hexdigest()[:12]
            identity: Json = {"path_hash": path_hash, "content_identity": "stat_snapshot"}
            try:
                stat = os.stat(resource_path)
                identity["stat"] = {"mtime_ns": stat.st_mtime_ns, "size_bytes": stat.st_size,
                                    "dev": stat.st_dev, "inode": stat.st_ino}
            except OSError:
                identity["stat"] = None
            if self.run_manifest:
                try:
                    identity["manifest_sha256"] = hashlib.sha256(
                        Path(self.run_manifest).read_bytes()).hexdigest()
                    # The native xdebug/xcov backend verifies the manifest at
                    # open time.  This wrapper only reports its own digest, so
                    # do not claim that the digest itself performed validation.
                    identity["content_identity"] = "manifest_declared"
                except OSError:
                    identity["manifest_sha256"] = None
            out["resource_identity"] = identity
        if verbose:
            out["resource_path"] = resource_path
            if self.run_manifest: out["run_manifest"] = self.run_manifest
            if self.queue: out["queue"] = self.queue
            if self.resource: out["lsf_resource"] = self.resource
            if self.job_name: out["job_name"] = self.job_name
            if h and getattr(h, "job_id", None): out["job_id"] = h.job_id
            if self.pid: out["pid"] = self.pid
            if self.last_cleanup: out["last_cleanup"] = self.last_cleanup
            if self.last_error: out["last_error"] = self.last_error
        return out
