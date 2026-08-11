from __future__ import annotations

import os
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .backend import (
    CanonicalCoverageBackend,
    CoverageBackend,
    UrgCoverageBackend,
)
from .errors import XcovError
from .logging import log_lifecycle_event

Json = Dict[str, Any]
BackendFactory = Callable[[str], CoverageBackend]


@dataclass
class XcovSession:
    session_id: str
    vdb: str
    backend: CoverageBackend
    worker: str
    exclusion_policy: str = "default"
    state: str = "alive"
    cache_dir: Optional[str] = None

    _el_path: Optional[str] = None
    _el_dirty: bool = False
    exclusion_records: Dict[str, Json] = field(default_factory=dict)
    loaded_el_without_reasons: bool = False
    loaded_el_file_count: int = 0

    def close(self) -> None:
        self.backend.close()
        self.state = "closed"
        self._el_path = None
        self._el_dirty = False
        self.exclusion_records.clear()
        self.loaded_el_without_reasons = False
        self.loaded_el_file_count = 0

    def public_json(self) -> Json:
        summary = self.backend.summary()
        try:
            top_scopes = [s["full_name"] for s in self.backend.top_scopes()]
        except Exception:
            top_scopes = []
        return {
            "session_id": self.session_id,
            "state": self.state,
            "vdb": self.vdb,
            "test_count": summary["test_count"],
            "top_scope_count": summary["top_scope_count"],
            "top_scopes": top_scopes,
            "worker": self.worker,
            "exclusion_policy": self.exclusion_policy,
            "npi_initialized": bool(
                getattr(self.backend, "npi_initialized", False)
            ),
        }

    def cache_status(self) -> Json:
        info = self.backend.cache_info
        if info is None:
            return {
                "state": "lazy", "key": None, "hit": None,
                "urg_execution": None,
            }
        execution = info.get("urg_execution")
        public_execution = None
        if isinstance(execution, dict):
            public_execution = {
                "backend": execution.get("backend"),
                "submitted": bool(execution.get("submitted")),
                "status": execution.get("status"),
                "queue": execution.get("queue"),
                "resource": execution.get("resource"),
                "job_name": execution.get("job_name"),
                "job_id": execution.get("job_id"),
                "exit_status": execution.get("exit_status"),
            }
        return {
            "state": "ready",
            "key": info.get("key"),
            "hit": info.get("hit"),
            "urg_execution": public_execution,
        }

    def mark_exclusion_dirty(self) -> None:
        self._el_dirty = True
        self.backend.invalidate_summary()

    def set_el_path(self, path: Optional[str]) -> None:
        self._el_path = path
        self._el_dirty = False

    def clear_exclusions(self) -> None:
        self._el_path = None
        self._el_dirty = False
        self.exclusion_records.clear()
        self.loaded_el_without_reasons = False
        self.loaded_el_file_count = 0

    def record_exclusion(self, key: str, record: Json) -> str:
        previous = self.exclusion_records.get(key)
        status = "created" if previous is None else "unchanged" if previous == record else "updated"
        self.exclusion_records[key] = record
        return status

    def remove_exclusion_record(self, key: str) -> None:
        self.exclusion_records.pop(key, None)

    def ensure_el_ready(self) -> Optional[str]:
        if self._el_dirty:
            if self.cache_dir is None:
                self.cache_dir = tempfile.mkdtemp(prefix=".xcov-cache-")
            new_path = os.path.join(self.cache_dir, "current.el")
            self.backend.save_exclusions(new_path, test="merged")
            self._el_path = new_path
            self._el_dirty = False
            self.backend.set_summary_exclusion(new_path)
        return self._el_path

    def prepare_coverage_read(self) -> None:
        if self._el_dirty:
            self.ensure_el_ready()

    @property
    def el_file_arg(self) -> list:
        el = self.ensure_el_ready()
        return ["-elfile", el] if el else []


class SessionManager:
    def __init__(
        self,
        backend_factory: BackendFactory = UrgCoverageBackend,
    ) -> None:
        self.sessions: Dict[str, XcovSession] = {}
        self._backend_factory = backend_factory

    def session_id(self, name: Optional[str] = None) -> str:
        return name or "cov0"

    def require_available(self, name: Optional[str] = None) -> str:
        sid = self.session_id(name)
        if sid in self.sessions and self.sessions[sid].state == "alive":
            log_lifecycle_event(
                sid,
                "session.open.exists",
                False,
                {},
            )
            raise XcovError(
                "SESSION_EXISTS",
                "session already exists; close it before opening a new VDB",
                session_id=sid,
            )
        live_sessions = [
            session_id
            for session_id, session in self.sessions.items()
            if session.state == "alive"
        ]
        if live_sessions:
            raise XcovError(
                "SESSION_CAPACITY_EXCEEDED",
                "one xcov stdio-loop process owns at most one live native session; "
                "open another managed MCP session to launch an independent process",
                requested_session_id=sid,
                live_session_id=live_sessions[0],
                capacity=1,
            )
        return sid

    def open(
        self,
        vdb: str,
        name: Optional[str] = None,
        exclusion_policy: str = "default",
        cache_dir: Optional[str] = None,
        run_manifest_digest: Optional[str] = None,
    ) -> XcovSession:
        sid = self.require_available(name)
        if cache_dir is not None:
            cache_path = Path(cache_dir)
            if not cache_path.exists():
                raise XcovError(
                    "CACHE_DIR_NOT_FOUND",
                    "cache_dir does not exist; create it before session.open",
                    cache_dir=cache_dir,
                )
            if not os.access(str(cache_path), os.W_OK):
                raise XcovError(
                    "CACHE_DIR_NOT_WRITABLE",
                    "cache_dir is not writable",
                    cache_dir=cache_dir,
                )
        session_cache_dir = cache_dir
        if session_cache_dir is None:
            session_cache_path = (
                Path.cwd().resolve() / ".xverif" / "xcov" / "cache" /
                "sessions" / sid
            )
            session_cache_path.mkdir(parents=True, exist_ok=True)
            session_cache_dir = str(session_cache_path)
        log_lifecycle_event(sid, "session.open.begin", True, {"vdb": vdb})
        backend = self._backend_factory(vdb, exclusion_policy=exclusion_policy)
        if hasattr(backend, "exclusion_policy"):
            backend.exclusion_policy = exclusion_policy
        if hasattr(backend, "session_id"):
            backend.session_id = sid
        if cache_dir is not None and hasattr(backend, "urg_cache_dir"):
            backend.urg_cache_dir = str(Path(cache_dir).resolve() / "urg-summary")
        if hasattr(backend, "run_manifest_digest"):
            backend.run_manifest_digest = run_manifest_digest
        if not isinstance(backend, CoverageBackend):
            raise XcovError(
                "BACKEND_CONTRACT_VIOLATION",
                "backend factory must return a CoverageBackend",
                backend_type=type(backend).__name__,
            )
        worker = backend.worker_kind
        if not isinstance(worker, str) or not worker:
            backend.close()
            raise XcovError(
                "BACKEND_CONTRACT_VIOLATION",
                "coverage backend must declare a non-empty worker_kind",
                backend_type=type(backend).__name__,
            )
        canonical_backend = CanonicalCoverageBackend(backend)
        try:
            canonical_backend.summary()
        except Exception:
            backend.close()
            raise
        sess = XcovSession(
            session_id=sid,
            vdb=vdb,
            backend=canonical_backend,
            worker=worker,
            exclusion_policy=exclusion_policy,
            cache_dir=session_cache_dir,
        )
        self.sessions[sid] = sess
        log_lifecycle_event(sid, "session.open.ok", True, {"vdb": vdb, "worker": worker})
        return sess

    def get(self, session_id: str) -> XcovSession:
        sess = self.sessions.get(session_id)
        if not sess or sess.state != "alive":
            raise XcovError("SESSION_NOT_FOUND", "coverage session not found",
                            session_id=session_id)
        return sess

    def close(self, session_id: str) -> XcovSession:
        sess = self.get(session_id)
        log_lifecycle_event(session_id, "session.close.begin", True, {"vdb": sess.vdb})
        sess.close()
        self.sessions.pop(session_id, None)
        log_lifecycle_event(session_id, "session.close.ok", True, {"vdb": sess.vdb})
        return sess
