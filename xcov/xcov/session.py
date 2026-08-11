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
    NpiCoverageBackend,
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
        }

    def mark_exclusion_dirty(self) -> None:
        self._el_dirty = True

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
        return self._el_path

    @property
    def el_file_arg(self) -> list:
        el = self.ensure_el_ready()
        return ["-elfile", el] if el else []


class SessionManager:
    def __init__(
        self,
        backend_factory: BackendFactory = NpiCoverageBackend,
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
        return sid

    def open(
        self,
        vdb: str,
        name: Optional[str] = None,
        exclusion_policy: str = "default",
        cache_dir: Optional[str] = None,
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
        log_lifecycle_event(sid, "session.open.begin", True, {"vdb": vdb})
        backend = self._backend_factory(vdb, exclusion_policy=exclusion_policy)
        if hasattr(backend, "exclusion_policy"):
            backend.exclusion_policy = exclusion_policy
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
            cache_dir=cache_dir,
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
