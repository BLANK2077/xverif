from __future__ import annotations

from dataclasses import dataclass
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

    def close(self) -> None:
        self.backend.close()
        self.state = "closed"

    def public_json(self) -> Json:
        summary = self.backend.summary()
        return {
            "session_id": self.session_id,
            "state": self.state,
            "vdb": self.vdb,
            "test_count": summary["test_count"],
            "top_scope_count": summary["top_scope_count"],
            "worker": self.worker,
            "exclusion_policy": self.exclusion_policy,
        }


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
    ) -> XcovSession:
        sid = self.require_available(name)
        log_lifecycle_event(sid, "session.open.begin", True, {"vdb": vdb})
        backend = (
            self._backend_factory(vdb, exclusion_policy=exclusion_policy)
            if self._backend_factory is NpiCoverageBackend
            else self._backend_factory(vdb)
        )
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
