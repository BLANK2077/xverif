"""McpSessionManager — multi-session lifecycle for stdio-loop backends."""

from __future__ import annotations

import getpass
import os
import re
import threading
import uuid as _uuid
from typing import Any, Dict, Optional

from xverif_loop.lsf.bsub import BsubRunner

from xverif_loop.config import (
    RuntimeConfig,
    default_xdebug_bin,
)
from xverif_loop.logging import StructuredLogger, StructuredLoggingError
from xverif_loop.sessions.launchers import DirectLauncher, Launcher, LsfLauncher
from xverif_loop.sessions.loop_session import XdebugLoopSession
from xverif_loop.sessions.capabilities import lifecycle_capability

Json = Dict[str, Any]


def _safe_name(s: str, max_len: int = 64) -> str:
    x = re.sub(r"[^A-Za-z0-9_]", "_", s).strip("_")
    return (x or "unnamed")[:max_len]


def _valid_session_name(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", s or ""))


def _valid_scheduler_value(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
    )


def _error(code: str, message: str, **extra: Any) -> Json:
    error: Json = {"code": code, "message": message}
    error.update(extra)
    return {"ok": False, "error": error}


def _management_key(session: XdebugLoopSession) -> str:
    """Stable manager key even when the backend did not confirm an ID."""

    return session.session_id or session.alias


def _cleanup_success(operation: str, session: XdebugLoopSession,
                     cleanup: Json, **summary_fields: Any) -> Json:
    stages = dict(cleanup)
    stages["manager_record"] = "evicted"
    stages["tombstone"] = "retained_closed"
    summary: Json = {
        "status": "closed",
        "operation": operation,
        "ownership": "managed",
        "backend": session.backend,
        "session_id": session.session_id,
        "cleanup_complete": True,
    }
    summary.update(summary_fields)
    return {
        "ok": True,
        "summary": summary,
        "data": {
            "session": session.public_json(),
            "cleanup": stages,
        },
    }


def _cleanup_failure(response: Json, session: XdebugLoopSession) -> Json:
    error = response.setdefault("error", {})
    error.setdefault("error_layer", "session_manager")
    cleanup = error.setdefault("cleanup", {})
    cleanup["manager_record"] = "evicted"
    cleanup["tombstone"] = "retained_unresolved"
    error["session"] = session.public_json()
    return response


class McpSessionManager:
    def __init__(self, *, runtime: RuntimeConfig,
                 xdebug_bin: Optional[str] = None,
                 backend: str = "xdebug", api_version: str = "xdebug.v1",
                 ready_protocol: str = "xdebug-stdio-loop",
                 target_key: str = "fsdb",
                 recovery_tool: str = "xverif_debug_session_open",
                 logger: StructuredLogger) -> None:
        self.runtime = runtime
        self.logger = logger
        self.mode = runtime.backend
        self.xdebug_bin = xdebug_bin or default_xdebug_bin()
        self.backend = backend
        self.api_version = api_version
        self.ready_protocol = ready_protocol
        self.target_key = target_key
        self.recovery_tool = recovery_tool
        self._session_queue = runtime.session_queue
        self._session_resource = runtime.session_resource
        if self.mode == "direct":
            self.launcher: Launcher = DirectLauncher()
        elif self.mode == "lsf":
            self.launcher = LsfLauncher(
                BsubRunner(runtime.lsf_bsub_command)
            )
        self._job_prefix = (
            f"xverif_{_safe_name(getpass.getuser())}_{os.getpid()}_"
            f"{_uuid.uuid4().hex[:8]}"
        )
        self.sessions: Dict[str, XdebugLoopSession] = {}
        self.tombstones: Dict[str, XdebugLoopSession] = {}
        self._manager_lock = threading.RLock()
        self._opening: set[str] = set()
        self.logger.server("manager.init", True, backend=self.backend,
                           launcher=self.mode, xdebug_bin=self.xdebug_bin)

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
        cursor: int,
        message: str,
        operation_started: bool,
    ) -> Json:
        return _error(
            "OBSERVABILITY_FAILURE",
            message,
            operation_started=operation_started,
            observability=self.logger.observability_status(cursor),
        )

    def open_session(self, name: str, fsdb: Optional[str] = None,
                     daidir: Optional[str] = None,
                     queue: Optional[str] = None, resource: Optional[str] = None,
                     run_manifest: Optional[str] = None,
                     **kwargs: Any) -> Json:
        observability_cursor = self.logger.failure_cursor()
        for option_name, option_value in (("queue", queue), ("resource", resource)):
            if option_value is not None and not _valid_scheduler_value(option_value):
                return self._attach_observability(_error(
                    "INVALID_LSF_OPTION",
                    f"{option_name} must be a non-empty string without surrounding whitespace",
                    option=option_name,
                ), observability_cursor)
        if not _valid_session_name(name):
            self.logger.try_session(
                name,
                "manager.open.rejected",
                False,
                backend=self.backend,
                launcher=self.mode,
                error_code="INVALID_SESSION_NAME",
            )
            return self._attach_observability(_error(
                "INVALID_SESSION_NAME",
                "session name must start with an ASCII letter and contain only "
                "ASCII letters, digits, and underscores, with maximum length 64",
            ), observability_cursor)
        if not fsdb and not daidir:
            self.logger.try_session(
                name,
                "manager.open.rejected",
                False,
                backend=self.backend,
                launcher=self.mode,
                error_code="RESOURCE_REQUIRED",
            )
            return self._attach_observability(
                _error(
                    "RESOURCE_REQUIRED",
                    "provide fsdb or daidir",
                ),
                observability_cursor,
            )
        with self._manager_lock:
            if name in self._opening:
                return _error("SESSION_ID_EXISTS", f"session id is opening: {name}")
            if name in self.sessions:
                existing = self.sessions[name]
                if existing.state == "alive":
                    if existing.process_alive():
                        return _error("SESSION_ID_EXISTS", f"session id already exists: {name}")
                    return _error("SESSION_STALE", "session id exists but is stale: "
                                  f"{name}; close it explicitly before opening again")
            if name in self.tombstones:
                return _error("SESSION_TOMBSTONE_EXISTS",
                              f"session tombstone exists: {name}; inspect doctor and run gc or kill explicitly")
            self._opening.add(name)
        job_name = None
        actual_queue = (
            queue if queue is not None else self._session_queue
        ) if self.mode == "lsf" else None
        actual_resource = (
            resource if resource is not None else self._session_resource
        ) if self.mode == "lsf" else None
        if self.mode == "lsf":
            job_name = f"{self._job_prefix}_{_safe_name(self.backend)}_{_safe_name(name)}"
        try:
            self.logger.session(
                name,
                "manager.open.begin",
                True,
                backend=self.backend,
                launcher=self.mode,
                fsdb=fsdb,
                daidir=daidir,
                run_manifest=run_manifest,
                queue=actual_queue,
                resource=actual_resource,
                job_name=job_name,
            )
        except StructuredLoggingError:
            with self._manager_lock:
                self._opening.discard(name)
            return self._observability_error(
                cursor=observability_cursor,
                message=(
                    "session.open was not started because its manager begin "
                    "event could not be published"
                ),
                operation_started=False,
            )
        try:
            session = XdebugLoopSession(
                alias=name, fsdb=fsdb, daidir=daidir,
                launcher=self.launcher, xdebug_bin=self.xdebug_bin,
                requested_queue=queue, requested_resource=resource,
                queue=actual_queue, resource=actual_resource,
                job_name=job_name, runtime=self.runtime,
                backend=self.backend, api_version=self.api_version,
                ready_protocol=self.ready_protocol,
                target_key=self.target_key,
                recovery_tool=self.recovery_tool,
                run_manifest=run_manifest, logger=self.logger,
            )
        except BaseException:
            with self._manager_lock:
                self._opening.discard(name)
            raise
        try:
            result = session.open()
        except BaseException:
            with self._manager_lock:
                self.tombstones[name] = session
                self._opening.discard(name)
            raise
        if not result.get("ok"):
            with self._manager_lock:
                if session.state in {
                    "cleanup_partial",
                    "orphan_suspected",
                }:
                    self.tombstones[name] = session
                    result.setdefault("error", {}).setdefault(
                        "manager_record",
                        "retained_unresolved",
                    )
                self._opening.discard(name)
            self.logger.try_session(
                name,
                "manager.open.end",
                False,
                backend=self.backend,
                launcher=self.mode,
                response=result,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        if session.session_id != name:
            cleanup = session.kill()
            result = _error(
                "BACKEND_SESSION_ID_MISMATCH",
                "backend session.open did not preserve the requested session_id",
                requested_session_id=name,
                backend_session_id=session.session_id,
                cleanup_complete=bool(cleanup.get("ok")),
                cleanup=cleanup.get("cleanup", {}),
            )
            with self._manager_lock:
                if not cleanup.get("ok"):
                    self.tombstones[name] = session
                    result.setdefault("error", {}).setdefault(
                        "manager_record",
                        "retained_unresolved",
                    )
                self._opening.discard(name)
            self.logger.try_session(
                name,
                "manager.open.end",
                False,
                backend=self.backend,
                launcher=self.mode,
                response=result,
            )
            return self._attach_observability(
                result,
                observability_cursor,
            )
        with self._manager_lock:
            self.sessions[name] = session
            self._opening.discard(name)
        self.logger.try_session(
            name,
            "manager.open.end",
            True,
            backend=self.backend,
            launcher=self.mode,
            session_id=session.session_id,
            public=session.public_json(),
        )
        return self._attach_observability(
            {"ok": True, "session": session.public_json()},
            observability_cursor,
        )

    def query(self, session_id: Optional[str], action: str,
              args: Optional[Json] = None, output_format: str = "xout",
              **kwargs: Any) -> Any:
        observability_cursor = self.logger.failure_cursor()
        if not session_id:
            self.logger.try_session(
                "adhoc",
                "manager.query.rejected",
                False,
                backend=self.backend,
                launcher=self.mode,
                action=action,
                error_code="SESSION_REQUIRED",
            )
            return self._attach_observability(
                _error(
                    "SESSION_REQUIRED",
                    "explicit session_id is required",
                ),
                observability_cursor,
            )
        with self._manager_lock:
            s = self.sessions.get(session_id)
        if not s:
            self.logger.try_session(
                session_id,
                "manager.query.rejected",
                False,
                backend=self.backend,
                launcher=self.mode,
                action=action,
                error_code="SESSION_NOT_FOUND",
            )
            return self._attach_observability(_error(
                "SESSION_NOT_FOUND",
                f"session_id not found: {session_id}",
            ), observability_cursor)
        try:
            self.logger.session(
                s.alias,
                "manager.query.begin",
                True,
                backend=self.backend,
                launcher=self.mode,
                session_id=s.session_id,
                action=action,
            )
        except StructuredLoggingError:
            return self._observability_error(
                cursor=observability_cursor,
                message=(
                    "query was not sent because its manager begin event "
                    "could not be published"
                ),
                operation_started=False,
            )
        rsp = s.query(action=action, args=args,
                       limits=kwargs.get("limits"), output=kwargs.get("output"),
                       output_format=output_format,
                       retain_transport_envelope=bool(
                           kwargs.get("retain_transport_envelope", False)
                       ))
        if s.state in {"dead", "orphan_suspected"}:
            with self._manager_lock:
                if self.sessions.get(session_id) is s:
                    self._evict_session_locked(s)
        self.logger.try_session(
            s.alias,
            "manager.query.end",
            not (isinstance(rsp, dict) and not rsp.get("ok", True)),
            backend=self.backend,
            launcher=self.mode,
            session_id=s.session_id,
            action=action,
            response=rsp if isinstance(rsp, dict) else None,
        )
        status = self.logger.observability_status(
            observability_cursor
        )
        if not status["ok"]:
            response_error = (
                rsp.get("error")
                if isinstance(rsp, dict)
                else None
            )
            if (
                isinstance(rsp, dict)
                and isinstance(response_error, dict)
                and response_error.get("code")
                    == "OBSERVABILITY_FAILURE"
            ):
                rsp["observability"] = status
                return rsp
            result = self._observability_error(
                cursor=observability_cursor,
                message=(
                    "backend query completed, but its manager outcome could "
                    "not be fully published"
                ),
                operation_started=True,
            )
            result["error"]["backend_result"] = {
                "received": True,
                "ok": not (
                    isinstance(rsp, dict)
                    and rsp.get("ok") is False
                ),
                "output_format": output_format,
            }
            return result
        return rsp

    def close_session(self, session_id: str) -> Json:
        observability_cursor = self.logger.failure_cursor()
        with self._manager_lock:
            s = self.sessions.get(session_id) or self.tombstones.get(
                session_id
            )
        if not s:
            self.logger.try_session(
                session_id,
                "manager.close.rejected",
                False,
                backend=self.backend,
                launcher=self.mode,
                error_code="SESSION_NOT_FOUND",
            )
            return self._attach_observability(_error(
                "SESSION_NOT_FOUND",
                f"session_id not found: {session_id}",
            ), observability_cursor)
        old_state = s.state
        capability = lifecycle_capability(s.backend)
        if s.state == "alive":
            rsp = s.close()
        elif capability.backend_survives_loop:
            self._evict_session(s)
            return self._attach_observability(_error(
                "SESSION_CLEANUP_REQUIRED",
                "backend may outlive its loop; use session doctor and exact session kill",
                error_layer="session_manager",
                session=s.public_json(),
            ), observability_cursor)
        else:
            rsp = s.kill()
        if not rsp.get("ok", True):
            s.state = "cleanup_partial"
            self._evict_session(s, tombstone_state=s.state)
            self.logger.try_session(
                s.alias,
                "manager.close.end",
                False,
                backend=self.backend,
                launcher=self.mode,
                session_id=s.session_id,
                previous_state=old_state,
                response=rsp,
            )
            return self._attach_observability(
                _cleanup_failure(rsp, s),
                observability_cursor,
            )
        self._evict_session(s, tombstone_state="closed")
        self.logger.try_session(
            s.alias,
            "manager.close.end",
            True,
            backend=self.backend,
            launcher=self.mode,
            session_id=s.session_id,
            previous_state=old_state,
        )
        return self._attach_observability(
            _cleanup_success(
                "close",
                s,
                rsp.get("cleanup", {}),
                previous_state=old_state,
            ),
            observability_cursor,
        )

    def list_sessions(self, include_tombstones: bool = False,
                      verbose: bool = False) -> Json:
        observability_cursor = self.logger.failure_cursor()
        with self._manager_lock:
            active_snapshot = list(self.sessions.values())
            tombstone_snapshot = (
                list(self.tombstones.values())
                if include_tombstones
                else []
            )
        rows = [
            session.public_json(verbose=verbose)
            for session in active_snapshot
        ]
        tombstones = []
        for session in tombstone_snapshot:
            row = session.public_json(verbose=verbose)
            row["tombstone"] = True
            tombstones.append(row)
        self.logger.try_server(
            "manager.list",
            True,
            backend=self.backend,
            launcher=self.mode,
            session_count=len(rows),
        )
        return self._attach_observability(
            {
                "ok": True,
                "summary": {
                    "active_count": len(rows),
                    "tombstone_count": len(tombstones),
                },
                "sessions": rows,
                "tombstones": tombstones,
            },
            observability_cursor,
        )

    def _evict_session(self, s: XdebugLoopSession,
                       tombstone_state: Optional[str] = None) -> None:
        with self._manager_lock:
            self._evict_session_locked(s, tombstone_state=tombstone_state)

    def _evict_session_locked(
        self,
        s: XdebugLoopSession,
        tombstone_state: Optional[str] = None,
    ) -> None:
        for key, value in list(self.sessions.items()):
            if value is s:
                self.sessions.pop(key, None)
        if tombstone_state:
            s.state = tombstone_state
        elif s.state == "dead" and lifecycle_capability(s.backend).backend_survives_loop:
            s.state = "orphan_suspected"
        key = _management_key(s)
        existing = self.tombstones.get(key)
        if (
            existing is not None
            and existing.state == "closed"
            and s.state != "closed"
        ):
            return
        self.tombstones[key] = s
        self.logger.try_session(
            s.alias,
            "manager.evict",
            True,
            backend=self.backend,
            launcher=self.mode,
            session_id=s.session_id,
            state=s.state,
        )

    def doctor_session(self, session_id: str, verbose: bool = False) -> Json:
        with self._manager_lock:
            s = self.sessions.get(session_id) or self.tombstones.get(
                session_id
            )
        if not s:
            return _error(
                "SESSION_NOT_FOUND",
                f"session_id not found: {session_id}",
            )
        return s.doctor(verbose=verbose)

    def kill_session(self, session_id: str) -> Json:
        observability_cursor = self.logger.failure_cursor()
        with self._manager_lock:
            s = self.sessions.get(session_id) or self.tombstones.get(
                session_id
            )
        if not s:
            return self._attach_observability(_error(
                "SESSION_NOT_FOUND",
                f"session_id not found: {session_id}",
            ), observability_cursor)
        rsp = s.kill()
        if rsp.get("ok"):
            self._evict_session(s, tombstone_state="closed")
            return self._attach_observability(
                _cleanup_success(
                    "kill",
                    s,
                    rsp.get("cleanup", {}),
                ),
                observability_cursor,
            )
        else:
            self._evict_session(s, tombstone_state=s.state)
            return self._attach_observability(
                _cleanup_failure(rsp, s),
                observability_cursor,
            )

    def gc_sessions(self, verbose: bool = False) -> Json:
        observability_cursor = self.logger.failure_cursor()
        removed = []
        unresolved = []
        with self._manager_lock:
            tombstone_snapshot = list(self.tombstones.values())
            session_snapshot = list(self.sessions.values())
        for s in tombstone_snapshot:
            capability = lifecycle_capability(s.backend)
            removable = s.state == "closed" or (
                s.state == "dead" and not capability.backend_survives_loop)
            if removable:
                removed.append(s.public_json(verbose=verbose))
                with self._manager_lock:
                    for key, value in list(self.tombstones.items()):
                        if value is s:
                            self.tombstones.pop(key, None)
            else:
                unresolved.append(s.public_json(verbose=verbose))
        for s in session_snapshot:
            if s.state == "alive" and not s.process_alive():
                capability = lifecycle_capability(s.backend)
                if capability.backend_survives_loop:
                    unresolved.append(s.public_json(verbose=verbose))
                else:
                    s.state = "closed"
                    self._evict_session(s, tombstone_state="closed")
                    removed.append(s.public_json(verbose=verbose))
                    with self._manager_lock:
                        for key, value in list(self.tombstones.items()):
                            if value is s:
                                self.tombstones.pop(key, None)
        return self._attach_observability({
            "ok": True,
            "summary": {
                "status": "gc_completed",
                "operation": "gc",
                "ownership": "managed",
                "backend": self.backend,
                "cleanup_complete": not unresolved,
                "removed_count": len(removed),
                "unresolved_count": len(unresolved),
            },
            "data": {"removed": removed, "unresolved": unresolved},
        }, observability_cursor)

    def session_open(self, name: str, fsdb: Optional[str] = None,
                     **kwargs: Any) -> Json:
        return self.open_session(name=name, fsdb=fsdb, **kwargs)

    def session_list(self, **kwargs: Any) -> Json:
        return self.list_sessions(**kwargs)

    def session_close(self, session_id: str) -> Json:
        return self.close_session(session_id)

    def session_doctor(self, session_id: str, verbose: bool = False) -> Json:
        return self.doctor_session(session_id, verbose=verbose)

    def session_kill(self, session_id: str) -> Json:
        return self.kill_session(session_id)

    def session_gc(self, verbose: bool = False) -> Json:
        return self.gc_sessions(verbose=verbose)

    def close_all(self) -> Json:
        observability_cursor = self.logger.failure_cursor()
        closed = []
        unresolved = []
        with self._manager_lock:
            managed = list({
                id(session): session
                for session in (
                    list(self.sessions.values())
                    + list(self.tombstones.values())
                )
            }.values())
        for s in managed:
            try:
                if s.state == "closed":
                    closed.append(s.public_json())
                    continue
                if s.state == "alive":
                    rsp = s.close()
                else:
                    rsp = s.kill()
                if rsp.get("ok"):
                    self._evict_session(s, tombstone_state="closed")
                    closed.append(s.public_json())
                else:
                    self._evict_session(s, tombstone_state=s.state)
                    unresolved.append(s.public_json(verbose=True))
            except Exception as exc:
                try:
                    s.abort(f"manager shutdown cleanup failed: {exc}",
                            source="manager_close_all")
                finally:
                    self._evict_session(s, tombstone_state=s.state)
                    unresolved.append(s.public_json(verbose=True))
        with self._manager_lock:
            self.sessions.clear()
        return self._attach_observability({
            "ok": not unresolved,
            "summary": {
                "closed_count": len(closed),
                "unresolved_count": len(unresolved),
            },
            "closed": closed,
            "unresolved": unresolved,
        }, observability_cursor)
