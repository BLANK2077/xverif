"""Strict batch resource limits for xverif MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from xverif_loop.config import ConfigError

BATCH_MAX_INPUT_BYTES_ENV = "XVERIF_MCP_BATCH_MAX_INPUT_BYTES"
BATCH_MAX_REQUESTS_ENV = "XVERIF_MCP_BATCH_MAX_REQUESTS"
BATCH_MAX_OUTPUT_BYTES_ENV = "XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES"

DEFAULT_BATCH_MAX_INPUT_BYTES = 16 * 1024 * 1024
DEFAULT_BATCH_MAX_REQUESTS = 10_000
DEFAULT_BATCH_MAX_OUTPUT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ToolPolicy:
    """One immutable batch-limits snapshot."""

    batch_max_input_bytes: int = DEFAULT_BATCH_MAX_INPUT_BYTES
    batch_max_requests: int = DEFAULT_BATCH_MAX_REQUESTS
    batch_max_output_bytes: int = DEFAULT_BATCH_MAX_OUTPUT_BYTES

    def summary(self) -> dict[str, Any]:
        return {
            "batch_limits": {
                "max_input_bytes": self.batch_max_input_bytes,
                "max_requests": self.batch_max_requests,
                "max_output_bytes": self.batch_max_output_bytes,
            },
        }


def _strict_env_positive_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    if not raw or raw != raw.strip() or not raw.isascii() or not raw.isdecimal():
        raise ConfigError(name, raw, "a positive base-10 integer")
    value = int(raw, 10)
    if value <= 0:
        raise ConfigError(name, raw, "a positive base-10 integer")
    return value


def resolve_tool_policy(environ: Mapping[str, str] | None = None) -> ToolPolicy:
    snapshot = dict(os.environ if environ is None else environ)
    return ToolPolicy(
        batch_max_input_bytes=_strict_env_positive_int(
            snapshot,
            BATCH_MAX_INPUT_BYTES_ENV,
            DEFAULT_BATCH_MAX_INPUT_BYTES,
        ),
        batch_max_requests=_strict_env_positive_int(
            snapshot,
            BATCH_MAX_REQUESTS_ENV,
            DEFAULT_BATCH_MAX_REQUESTS,
        ),
        batch_max_output_bytes=_strict_env_positive_int(
            snapshot,
            BATCH_MAX_OUTPUT_BYTES_ENV,
            DEFAULT_BATCH_MAX_OUTPUT_BYTES,
        ),
    )
