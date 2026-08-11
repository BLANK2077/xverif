"""Immutable runtime configuration for xverif stateful loop owners."""
from __future__ import annotations

import math
import os
import shlex
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    """A typed failure for one invalid public environment setting."""

    def __init__(self, env_name: str, value: str, expected: str) -> None:
        self.env_name = env_name
        self.value = value
        self.expected = expected
        super().__init__(
            f"invalid {env_name}={value!r}; expected {expected}"
        )


@dataclass(frozen=True)
class RuntimeEnvNames:
    """The exact public environment namespace owned by one runtime."""

    backend: str
    timeout: str
    startup_timeout: str
    request_timeout: str
    close_timeout: str
    bkill_timeout: str
    fake_lsf: str
    log_dir: str


@dataclass(frozen=True)
class RuntimeConfig:
    """One composition-root snapshot; runtime code never re-reads its env."""

    owner: str
    env_names: RuntimeEnvNames
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

    def with_overrides(
        self,
        *,
        backend: str | None = None,
        startup_timeout_sec: float | None = None,
        request_timeout_sec: float | None = None,
    ) -> "RuntimeConfig":
        """Return another frozen snapshot for explicit constructor overrides."""

        return replace(
            self,
            backend=(
                self.backend
                if backend is None
                else validate_backend(backend, source="mode")
            ),
            startup_timeout_sec=(
                self.startup_timeout_sec
                if startup_timeout_sec is None
                else validate_positive_timeout(
                    startup_timeout_sec,
                    source="startup_timeout_sec",
                )
            ),
            request_timeout_sec=(
                self.request_timeout_sec
                if request_timeout_sec is None
                else validate_positive_timeout(
                    request_timeout_sec,
                    source="request_timeout_sec",
                )
            ),
        )


MCP_ENV_NAMES = RuntimeEnvNames(
    backend="XVERIF_MCP_BACKEND",
    timeout="XVERIF_MCP_TIMEOUT_SEC",
    startup_timeout="XVERIF_MCP_STARTUP_TIMEOUT_SEC",
    request_timeout="XVERIF_MCP_REQUEST_TIMEOUT_SEC",
    close_timeout="XVERIF_MCP_CLOSE_TIMEOUT_SEC",
    bkill_timeout="XVERIF_MCP_BKILL_TIMEOUT_SEC",
    fake_lsf="XVERIF_MCP_FAKE_LSF",
    log_dir="XVERIF_MCP_LOG_DIR",
)

LOOP_WRAPPER_ENV_NAMES = RuntimeEnvNames(
    backend="XVERIF_LOOP_BACKEND",
    timeout="XVERIF_LOOP_TIMEOUT_SEC",
    startup_timeout="XVERIF_LOOP_STARTUP_TIMEOUT_SEC",
    request_timeout="XVERIF_LOOP_REQUEST_TIMEOUT_SEC",
    close_timeout="XVERIF_LOOP_CLOSE_TIMEOUT_SEC",
    bkill_timeout="XVERIF_LOOP_BKILL_TIMEOUT_SEC",
    fake_lsf="XVERIF_LOOP_FAKE_LSF",
    log_dir="XVERIF_LOOP_LOG_DIR",
)


def validate_backend(value: str, *, source: str = "backend") -> str:
    if value not in {"direct", "lsf"}:
        raise ConfigError(source, value, "'direct' or 'lsf'")
    return value


def validate_positive_timeout(value: object, *, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(source, str(value), "a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ConfigError(source, str(value), "a finite positive number")
    return result


def _env_float(
    environ: Mapping[str, str],
    env_name: str,
    default: float,
) -> float:
    raw = environ.get(env_name)
    if raw is None:
        return default
    if not raw or raw != raw.strip():
        raise ConfigError(env_name, raw, "a finite positive number")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(
            env_name,
            raw,
            "a finite positive number",
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(env_name, raw, "a finite positive number")
    return value


def _env_bool(
    environ: Mapping[str, str],
    env_name: str,
    default: bool = False,
) -> bool:
    raw = environ.get(env_name)
    if raw is None:
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise ConfigError(env_name, raw, "'0' or '1'")


def _resolved_log_root(
    environ: Mapping[str, str],
    *,
    names: RuntimeEnvNames,
    default_subdir: str,
) -> Path:
    configured = environ.get(names.log_dir)
    if configured:
        return Path(configured)
    test_tmp = environ.get("XVERIF_TEST_TMPDIR")
    if test_tmp:
        return Path(test_tmp) / ".xverif" / default_subdir
    return Path(environ.get("HOME", str(Path.home()))) / ".xverif" / default_subdir


def _env_command(
    environ: Mapping[str, str],
    env_name: str,
    default: str,
) -> str:
    raw = environ.get(env_name)
    if raw is None:
        return default
    expected = "a non-empty shell command with valid quoting"
    if not raw or raw != raw.strip():
        raise ConfigError(env_name, raw, expected)
    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        raise ConfigError(env_name, raw, expected) from exc
    if not argv or not argv[0]:
        raise ConfigError(env_name, raw, expected)
    return raw


def _env_text(
    environ: Mapping[str, str],
    env_name: str,
    default: str | None,
) -> str | None:
    raw = environ.get(env_name)
    if raw is None:
        return default
    if not raw or raw != raw.strip():
        raise ConfigError(env_name, raw, "a non-empty string without surrounding whitespace")
    return raw


def _resolved_lsf_commands(
    environ: Mapping[str, str],
    *,
    fake_lsf: bool,
) -> tuple[str, str]:
    if fake_lsf:
        default_bsub = shlex.join(
            [sys.executable, "-m", "xverif_loop.lsf.fake_bsub"]
        )
        default_bkill = shlex.join(
            [sys.executable, "-m", "xverif_loop.lsf.fake_bkill"]
        )
    else:
        default_bsub = "bsub"
        default_bkill = "bkill"
    return (
        _env_command(environ, "XVERIF_LSF_BSUB", default_bsub),
        _env_command(environ, "XVERIF_LSF_BKILL", default_bkill),
    )


def _resolve_runtime_config(
    *,
    owner: str,
    names: RuntimeEnvNames,
    default_subdir: str,
    environ: Mapping[str, str] | None,
) -> RuntimeConfig:
    snapshot = dict(os.environ if environ is None else environ)
    fake_lsf = _env_bool(snapshot, names.fake_lsf)
    lsf_bsub_command, lsf_bkill_command = _resolved_lsf_commands(
        snapshot,
        fake_lsf=fake_lsf,
    )
    return RuntimeConfig(
        owner=owner,
        env_names=names,
        backend=validate_backend(
            snapshot.get(names.backend, "direct"),
            source=names.backend,
        ),
        default_timeout_sec=_env_float(snapshot, names.timeout, 360.0),
        startup_timeout_sec=_env_float(
            snapshot,
            names.startup_timeout,
            180.0,
        ),
        request_timeout_sec=_env_float(
            snapshot,
            names.request_timeout,
            360.0,
        ),
        close_timeout_sec=_env_float(snapshot, names.close_timeout, 30.0),
        bkill_timeout_sec=_env_float(snapshot, names.bkill_timeout, 30.0),
        fake_lsf=fake_lsf,
        lsf_bsub_command=lsf_bsub_command,
        lsf_bkill_command=lsf_bkill_command,
        session_queue=_env_text(
            snapshot,
            "XVERIF_LSF_SESSION_QUEUE",
            "interactive",
        ) or "interactive",
        session_resource=_env_text(
            snapshot,
            "XVERIF_LSF_SESSION_RESOURCE",
            None,
        ),
        log_root=_resolved_log_root(
            snapshot,
            names=names,
            default_subdir=default_subdir,
        ),
    )


def resolve_mcp_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    return _resolve_runtime_config(
        owner="mcp",
        names=MCP_ENV_NAMES,
        default_subdir="mcp",
        environ=environ,
    )


def resolve_loop_wrapper_runtime_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    return _resolve_runtime_config(
        owner="loop-wrapper",
        names=LOOP_WRAPPER_ENV_NAMES,
        default_subdir="loop-wrapper",
        environ=environ,
    )


def repo_root() -> str:
    return os.environ.get("XVERIF_HOME") or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../..")
    )


def default_xdebug_bin() -> str:
    return os.path.join(repo_root(), "tools", "xdebug")


def default_xcov_bin() -> str:
    return os.environ.get("XVERIF_XCOV_BIN") or os.path.join(
        repo_root(),
        "tools",
        "xcov",
    )


def default_tool_path(tool: str) -> str:
    return os.path.join(repo_root(), "tools", tool)
