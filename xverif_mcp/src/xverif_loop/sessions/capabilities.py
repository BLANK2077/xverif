"""Backend lifecycle capabilities for managed loop sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class BackendLifecycleCapability:
    backend: str
    native_open_action: str
    native_health_action: str
    native_close_action: str
    native_kill_action: Optional[str]
    native_gc_action: Optional[str]
    backend_survives_loop: bool
    fixed_admin_path: bool
    json_request_style: str
    managed_transport: Optional[str]
    accepts_trace_id: bool
    supports_conditional_cleanup_token: bool
    session_id_path: Tuple[str, ...]


CAPABILITIES = {
    "xdebug": BackendLifecycleCapability(
        backend="xdebug",
        native_open_action="session.open",
        native_health_action="session.doctor",
        native_close_action="session.close",
        native_kill_action="session.close",
        native_gc_action="session.gc",
        backend_survives_loop=True,
        fixed_admin_path=True,
        json_request_style="loop_marker",
        managed_transport="uds",
        accepts_trace_id=True,
        supports_conditional_cleanup_token=True,
        session_id_path=("session", "session_id"),
    ),
    "xcov": BackendLifecycleCapability(
        backend="xcov",
        native_open_action="session.open",
        native_health_action="session.status",
        native_close_action="session.close",
        native_kill_action=None,
        native_gc_action=None,
        backend_survives_loop=False,
        fixed_admin_path=False,
        json_request_style="transport_envelope",
        managed_transport=None,
        accepts_trace_id=False,
        supports_conditional_cleanup_token=False,
        session_id_path=("data", "session", "session_id"),
    ),
}


def lifecycle_capability(backend: str) -> BackendLifecycleCapability:
    try:
        return CAPABILITIES[backend]
    except KeyError as exc:
        raise ValueError(f"unsupported lifecycle backend: {backend}") from exc
