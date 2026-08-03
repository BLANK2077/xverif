"""Unified config / path resolution for xverif stateful loop wrappers."""
from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    def __init__(self, env_name: str, value: str, expected: str) -> None:
        self.env_name = env_name
        self.value = value
        self.expected = expected
        super().__init__(f"invalid {env_name}={value!r}; expected {expected}")


def validate_positive_timeout(value: object, *, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(source, str(value), "a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ConfigError(source, str(value), "a finite positive number")
    return result


@dataclass(frozen=True)
class RuntimeConfig:
    owner: str
    backend: str
    default_timeout_sec: float
    startup_timeout_sec: float
    request_timeout_sec: float
    close_timeout_sec: float
    bkill_timeout_sec: float
    fake_lsf: bool
    lsf_bsub_command: str
    lsf_bkill_command: str
    session_queue: str
    session_resource: str | None
    log_root: Path


def _strict_env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None:
        return default
    if not raw or raw != raw.strip():
        raise ConfigError(name, raw, "a finite positive number")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(name, raw, "a finite positive number") from exc
    return validate_positive_timeout(value, source=name)


def resolve_mcp_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    snapshot = dict(os.environ if environ is None else environ)
    backend = snapshot.get("XVERIF_MCP_BACKEND", "direct")
    if backend not in {"direct", "lsf"}:
        raise ConfigError("XVERIF_MCP_BACKEND", backend, "'direct' or 'lsf'")
    fake_raw = snapshot.get("XVERIF_MCP_FAKE_LSF", "0")
    if fake_raw not in {"0", "1"}:
        raise ConfigError("XVERIF_MCP_FAKE_LSF", fake_raw, "'0' or '1'")
    return RuntimeConfig(
        owner="mcp",
        backend=backend,
        default_timeout_sec=_strict_env_float(snapshot, "XVERIF_MCP_TIMEOUT_SEC", 360.0),
        startup_timeout_sec=_strict_env_float(snapshot, "XVERIF_MCP_STARTUP_TIMEOUT_SEC", 180.0),
        request_timeout_sec=_strict_env_float(snapshot, "XVERIF_MCP_REQUEST_TIMEOUT_SEC", 360.0),
        close_timeout_sec=_strict_env_float(snapshot, "XVERIF_MCP_CLOSE_TIMEOUT_SEC", 30.0),
        bkill_timeout_sec=_strict_env_float(snapshot, "XVERIF_MCP_BKILL_TIMEOUT_SEC", 30.0),
        fake_lsf=fake_raw == "1",
        lsf_bsub_command=snapshot.get("XVERIF_LSF_BSUB", "bsub"),
        lsf_bkill_command=snapshot.get("XVERIF_LSF_BKILL", "bkill"),
        session_queue=snapshot.get("XVERIF_LSF_SESSION_QUEUE", "interactive"),
        session_resource=snapshot.get("XVERIF_LSF_SESSION_RESOURCE"),
        log_root=Path(snapshot.get("XVERIF_MCP_LOG_DIR", Path(snapshot.get("HOME", str(Path.home()))) / ".xverif/mcp")),
    )

_BACKEND_ENV = "XVERIF_MCP_BACKEND"
_TIMEOUT_ENV = "XVERIF_MCP_TIMEOUT_SEC"
_STARTUP_TIMEOUT_ENV = "XVERIF_MCP_STARTUP_TIMEOUT_SEC"
_REQUEST_TIMEOUT_ENV = "XVERIF_MCP_REQUEST_TIMEOUT_SEC"
_CLOSE_TIMEOUT_ENV = "XVERIF_MCP_CLOSE_TIMEOUT_SEC"
_BKILL_TIMEOUT_ENV = "XVERIF_MCP_BKILL_TIMEOUT_SEC"
_FAKE_LSF_ENV = "XVERIF_MCP_FAKE_LSF"


def configure_environment(
    *,
    backend_env: str = "XVERIF_MCP_BACKEND",
    timeout_env: str = "XVERIF_MCP_TIMEOUT_SEC",
    startup_timeout_env: str = "XVERIF_MCP_STARTUP_TIMEOUT_SEC",
    request_timeout_env: str = "XVERIF_MCP_REQUEST_TIMEOUT_SEC",
    close_timeout_env: str = "XVERIF_MCP_CLOSE_TIMEOUT_SEC",
    bkill_timeout_env: str = "XVERIF_MCP_BKILL_TIMEOUT_SEC",
    fake_lsf_env: str = "XVERIF_MCP_FAKE_LSF",
) -> None:
    """Configure process-wide environment variable names for loop wrappers."""
    global _BACKEND_ENV, _TIMEOUT_ENV, _STARTUP_TIMEOUT_ENV
    global _REQUEST_TIMEOUT_ENV, _CLOSE_TIMEOUT_ENV, _BKILL_TIMEOUT_ENV
    global _FAKE_LSF_ENV
    _BACKEND_ENV = backend_env
    _TIMEOUT_ENV = timeout_env
    _STARTUP_TIMEOUT_ENV = startup_timeout_env
    _REQUEST_TIMEOUT_ENV = request_timeout_env
    _CLOSE_TIMEOUT_ENV = close_timeout_env
    _BKILL_TIMEOUT_ENV = bkill_timeout_env
    _FAKE_LSF_ENV = fake_lsf_env


def configure_mcp_environment() -> None:
    configure_environment()


def configure_loop_wrapper_environment() -> None:
    configure_environment(
        backend_env="XVERIF_LOOP_BACKEND",
        timeout_env="XVERIF_LOOP_TIMEOUT_SEC",
        startup_timeout_env="XVERIF_LOOP_STARTUP_TIMEOUT_SEC",
        request_timeout_env="XVERIF_LOOP_REQUEST_TIMEOUT_SEC",
        close_timeout_env="XVERIF_LOOP_CLOSE_TIMEOUT_SEC",
        bkill_timeout_env="XVERIF_LOOP_BKILL_TIMEOUT_SEC",
        fake_lsf_env="XVERIF_LOOP_FAKE_LSF",
    )


def repo_root() -> str:
    return os.environ.get("XVERIF_HOME") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../..")
    )


def default_xdebug_bin() -> str:
    return os.path.join(repo_root(), "tools", "xdebug")


def default_xcov_bin() -> str:
    return os.environ.get("XVERIF_XCOV_BIN") or os.path.join(repo_root(), "tools", "xcov")


def default_tool_path(tool: str) -> str:
    return os.path.join(repo_root(), "tools", tool)


def loop_backend() -> str:
    return os.environ.get(_BACKEND_ENV, "direct")


def mcp_backend() -> str:
    return loop_backend()


def default_timeout() -> float:
    return float(os.environ.get(_TIMEOUT_ENV, "360"))


def startup_timeout() -> float:
    return float(os.environ.get(_STARTUP_TIMEOUT_ENV, "180"))


def request_timeout() -> float:
    return float(os.environ.get(_REQUEST_TIMEOUT_ENV, "360"))


def close_timeout() -> float:
    return float(os.environ.get(_CLOSE_TIMEOUT_ENV, "30"))


def bkill_timeout() -> float:
    return float(os.environ.get(_BKILL_TIMEOUT_ENV, "30"))


def fake_lsf_enabled() -> bool:
    return os.environ.get(_FAKE_LSF_ENV) == "1" or os.environ.get("XVERIF_MCP_FAKE_LSF") == "1"
