"""Fail-closed structured NDJSON logging for stateful loop owners."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Optional

from xverif_loop.config import RuntimeConfig
from xverif_loop.json_contract import is_sensitive_json_key

Json = Dict[str, Any]

_PATH_KEYS = {
    "binary",
    "daidir",
    "dbdir",
    "diagnostic_log",
    "file_dir",
    "fsdb",
    "log_path",
    "manifest",
    "path",
    "resource_path",
    "run_manifest",
    "socket_path",
    "tool_bin",
    "vdb",
    "xdebug_bin",
}
_RAW_TEXT_KEYS = {
    "backend_response",
    "cleanup_error",
    "error",
    "exception",
    "reason",
    "response",
    "stderr",
    "stderr_tail",
    "stdout",
}
class StructuredLoggingError(RuntimeError):
    """A typed, path-safe failure to publish one structured log event."""

    def __init__(
        self,
        *,
        operation: str,
        path: Path,
        error_type: str,
    ) -> None:
        self.operation = operation
        self.path_basename = path.name
        self.path_sha256 = hashlib.sha256(
            str(path).encode("utf-8", errors="replace")
        ).hexdigest()
        self.error_type = error_type
        self.failure_evidence: Json = {}
        super().__init__(
            "structured logging failed "
            f"during {operation} for {self.path_basename} "
            f"(path_sha256={self.path_sha256}, error_type={error_type})"
        )


@dataclass(frozen=True)
class LoggingProfile:
    """Immutable identity for one runtime owner."""

    owner: str
    layer: str
    component: str


class _OwnerEventSequence:
    """A monotonic, owner-local event sequence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


def _profile_for_runtime(runtime: RuntimeConfig) -> LoggingProfile:
    if runtime.owner == "mcp":
        return LoggingProfile(
            owner="mcp",
            layer="mcp",
            component="xverif-mcp",
        )
    if runtime.owner == "loop-wrapper":
        return LoggingProfile(
            owner="loop-wrapper",
            layer="loop-wrapper",
            component="xverif-loop-wrapper",
        )
    raise ValueError(f"unsupported logging owner: {runtime.owner}")


def _safe_name(value: Optional[str], max_len: int = 64) -> str:
    normalized = re.sub(
        r"[^A-Za-z0-9_]",
        "_",
        value or "",
    ).strip("_")
    return (normalized or "adhoc")[:max_len]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def argv_hash(argv: Iterable[str]) -> str:
    h = 1469598103934665603
    for item in argv:
        for byte in item.encode("utf-8", errors="replace"):
            h ^= byte
            h *= 1099511628211
            h &= 0xFFFFFFFFFFFFFFFF
        h ^= 0
        h *= 1099511628211
        h &= 0xFFFFFFFFFFFFFFFF
    return f"{h:x}"


def _is_path_key(key: str) -> bool:
    return (
        key in _PATH_KEYS
        or key.endswith("_bin")
        or key.endswith("_path")
        or key.endswith("_dir")
    )


def _path_evidence(value: str) -> Json:
    return {
        "basename": Path(value).name,
        "sha256": hashlib.sha256(
            value.encode("utf-8", errors="replace")
        ).hexdigest(),
    }


def _text_evidence(value: Any) -> Json:
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        return {
            "present": bool(value),
            "byte_count": len(encoded),
            "line_count": len(value.splitlines()),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    if isinstance(value, (list, tuple)):
        encoded = "\n".join(str(item) for item in value).encode(
            "utf-8",
            errors="replace",
        )
        return {
            "present": bool(value),
            "item_count": len(value),
            "byte_count": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    if isinstance(value, dict):
        error = value.get("error")
        error_code = (
            error.get("code")
            if isinstance(error, dict)
            and isinstance(error.get("code"), str)
            else None
        )
        evidence: Json = {
            "present": True,
            "ok": value.get("ok")
            if isinstance(value.get("ok"), bool)
            else None,
            "action": value.get("action")
            if isinstance(value.get("action"), str)
            else None,
            "error_code": error_code,
            "field_names": sorted(str(key) for key in value),
        }
        return {
            key: item
            for key, item in evidence.items()
            if item is not None
        }
    return {
        "present": value is not None,
        "value_type": type(value).__name__,
    }


def _sanitize(value: Any, key: str = "") -> Any:
    if is_sensitive_json_key(key):
        return {"redacted": True}
    if key in _RAW_TEXT_KEYS:
        return _text_evidence(value)
    if isinstance(value, str):
        return _path_evidence(value) if _is_path_key(key) else value
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, dict):
        return {
            str(nested_key): _sanitize(nested_value, str(nested_key))
            for nested_key, nested_value in value.items()
        }
    return value


@dataclass(frozen=True)
class StructuredLogger:
    """Owner-bound logger with a frozen sink and no runtime env lookup."""

    profile: LoggingProfile
    root: Path
    _sequence: _OwnerEventSequence = field(
        default_factory=_OwnerEventSequence,
        repr=False,
        compare=False,
    )
    _write_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )
    _failure_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )
    _failure_sequence: _OwnerEventSequence = field(
        default_factory=_OwnerEventSequence,
        repr=False,
        compare=False,
    )
    _failures: Deque[Json] = field(
        default_factory=lambda: deque(maxlen=256),
        repr=False,
        compare=False,
    )

    def log_root(self) -> Path:
        return self.root

    def server_log_path(self) -> Path:
        return self.root / "logs" / "server.ndjson"

    def session_log_path(self, alias: Optional[str], name: str) -> Path:
        return (
            self.root
            / "sessions"
            / _safe_name(alias)
            / f"{name}.ndjson"
        )

    def validate_sink(self) -> None:
        """Prove the frozen sink is creatable and append-openable."""

        path = self.server_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8"):
                pass
        except (OSError, ValueError) as exc:
            error = StructuredLoggingError(
                operation="resolve_sink",
                path=path,
                error_type=type(exc).__name__,
            )
            self._record_failure(error, phase="logger.resolve")
            raise error from exc

    def _record_failure(
        self,
        error: StructuredLoggingError,
        *,
        phase: str,
    ) -> None:
        evidence: Json = {
            "failure_sequence": self._failure_sequence.next(),
            "phase": phase,
            "operation": error.operation,
            "path_basename": error.path_basename,
            "path_sha256": error.path_sha256,
            "error_type": error.error_type,
        }
        with self._failure_lock:
            self._failures.append(evidence)
        error.failure_evidence = dict(evidence)

    def failure_cursor(self) -> int:
        with self._failure_lock:
            if not self._failures:
                return 0
            return int(self._failures[-1]["failure_sequence"])

    def failures_since(self, cursor: int) -> list[Json]:
        with self._failure_lock:
            return [
                dict(item)
                for item in self._failures
                if int(item["failure_sequence"]) > cursor
            ]

    def observability_status(self, cursor: int = 0) -> Json:
        failures = self.failures_since(cursor)
        return {
            "ok": not failures,
            "failure_count": len(failures),
            "failures": failures,
        }

    def _base(self, phase: str, ok: bool, **fields: Any) -> Json:
        sequence = self._sequence.next()
        event: Json = {
            "ts": _now(),
            "event_id": (
                f"{self.profile.owner}-{os.getpid()}-{sequence}"
            ),
            "event_sequence": sequence,
            "pid": os.getpid(),
            "layer": self.profile.layer,
            "component": self.profile.component,
            "phase": phase,
            "ok": ok,
        }
        for key, value in fields.items():
            if value is not None:
                event[key] = _sanitize(value, key)
        return event

    def _append(self, path: Path, event: Json) -> None:
        try:
            encoded = json.dumps(
                event,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            error = StructuredLoggingError(
                operation="serialize",
                path=path,
                error_type=type(exc).__name__,
            )
            self._record_failure(
                error,
                phase=str(event.get("phase", "unknown")),
            )
            raise error from exc
        try:
            with self._write_lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                    stream.write(encoded + "\n")
                    stream.flush()
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            error = StructuredLoggingError(
                operation="append",
                path=path,
                error_type=type(exc).__name__,
            )
            self._record_failure(
                error,
                phase=str(event.get("phase", "unknown")),
            )
            raise error from exc

    def server(self, phase: str, ok: bool = True, **fields: Any) -> None:
        self._append(
            self.server_log_path(),
            self._base(phase, ok, **fields),
        )

    def session(
        self,
        alias: Optional[str],
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> None:
        self._append(
            self.session_log_path(alias, "session"),
            self._base(
                phase,
                ok,
                alias=_safe_name(alias),
                **fields,
            ),
        )

    def stdio(
        self,
        alias: Optional[str],
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> None:
        self._append(
            self.session_log_path(alias, "stdio"),
            self._base(
                phase,
                ok,
                alias=_safe_name(alias),
                **fields,
            ),
        )

    def lsf(
        self,
        alias: Optional[str],
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> None:
        self._append(
            self.session_log_path(alias, "lsf"),
            self._base(
                phase,
                ok,
                alias=_safe_name(alias),
                **fields,
            ),
        )

    def uds(self, phase: str, ok: bool = True, **fields: Any) -> None:
        self._append(
            self.root / "logs" / "uds.ndjson",
            self._base(phase, ok, **fields),
        )

    def try_server(
        self,
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> Optional[Json]:
        try:
            self.server(phase, ok, **fields)
        except StructuredLoggingError as exc:
            return dict(exc.failure_evidence)
        return None

    def try_session(
        self,
        alias: Optional[str],
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> Optional[Json]:
        try:
            self.session(alias, phase, ok, **fields)
        except StructuredLoggingError as exc:
            return dict(exc.failure_evidence)
        return None

    def try_stdio(
        self,
        alias: Optional[str],
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> Optional[Json]:
        try:
            self.stdio(alias, phase, ok, **fields)
        except StructuredLoggingError as exc:
            return dict(exc.failure_evidence)
        return None

    def try_lsf(
        self,
        alias: Optional[str],
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> Optional[Json]:
        try:
            self.lsf(alias, phase, ok, **fields)
        except StructuredLoggingError as exc:
            return dict(exc.failure_evidence)
        return None

    def try_uds(
        self,
        phase: str,
        ok: bool = True,
        **fields: Any,
    ) -> Optional[Json]:
        try:
            self.uds(phase, ok, **fields)
        except StructuredLoggingError as exc:
            return dict(exc.failure_evidence)
        return None


def resolve_logger(runtime: RuntimeConfig) -> StructuredLogger:
    """Create one frozen logger from an already-resolved runtime snapshot."""

    logger = StructuredLogger(
        profile=_profile_for_runtime(runtime),
        root=runtime.log_root,
    )
    logger.validate_sink()
    return logger


def resolve_mcp_logger() -> StructuredLogger:
    """Standalone MCP composition root used by direct library consumers."""

    from xverif_loop.config import resolve_mcp_runtime_config

    return resolve_logger(resolve_mcp_runtime_config())


def resolve_loop_wrapper_logger() -> StructuredLogger:
    """Standalone loop-wrapper composition root used by direct consumers."""

    from xverif_loop.config import resolve_loop_wrapper_runtime_config

    return resolve_logger(resolve_loop_wrapper_runtime_config())
