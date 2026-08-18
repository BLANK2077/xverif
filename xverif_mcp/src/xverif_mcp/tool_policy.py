"""Strict tool exposure policy for xverif MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from xverif_loop.config import ConfigError

GROUP_ENV = {
    "common": ("XVERIF_MCP_ENABLE_COMMON", True),
    "debug": ("XVERIF_MCP_ENABLE_DEBUG", True),
    "cov": ("XVERIF_MCP_ENABLE_COV", True),
    "bit": ("XVERIF_MCP_ENABLE_BIT", True),
    "entry": ("XVERIF_MCP_ENABLE_ENTRY", True),
    "loc": ("XVERIF_MCP_ENABLE_LOC", True),
    "sva": ("XVERIF_MCP_ENABLE_SVA", True),
}

MUTATION_ENV = "XVERIF_MCP_ENABLE_MUTATION"
ARTIFACT_WRITE_ENV = "XVERIF_MCP_ENABLE_ARTIFACT_WRITE"
ARTIFACT_ROOT_ENV = "XVERIF_MCP_ARTIFACT_ROOT"
BATCH_MAX_INPUT_BYTES_ENV = "XVERIF_MCP_BATCH_MAX_INPUT_BYTES"
BATCH_MAX_REQUESTS_ENV = "XVERIF_MCP_BATCH_MAX_REQUESTS"
BATCH_MAX_OUTPUT_BYTES_ENV = "XVERIF_MCP_BATCH_MAX_OUTPUT_BYTES"

DEFAULT_BATCH_MAX_INPUT_BYTES = 16 * 1024 * 1024
DEFAULT_BATCH_MAX_REQUESTS = 10_000
DEFAULT_BATCH_MAX_OUTPUT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ToolPolicy:
    """One immutable tool-exposure snapshot."""

    groups: tuple[tuple[str, bool], ...]
    mutation_enabled: bool = True
    artifact_write_enabled: bool = False
    artifact_root: Path | None = None
    batch_max_input_bytes: int = DEFAULT_BATCH_MAX_INPUT_BYTES
    batch_max_requests: int = DEFAULT_BATCH_MAX_REQUESTS
    batch_max_output_bytes: int = DEFAULT_BATCH_MAX_OUTPUT_BYTES

    def group_enabled(self, group: str) -> bool:
        return dict(self.groups).get(group, False)

    def tool_enabled(
        self,
        group: str,
        *,
        mutation: bool = False,
        artifact_write: bool = False,
    ) -> bool:
        if mutation and not self.mutation_enabled:
            return False
        if artifact_write and not self.artifact_write_enabled:
            return False
        return self.group_enabled(group)

    def summary(self) -> dict[str, Any]:
        return {
            "groups": dict(self.groups),
            "mutation_enabled": self.mutation_enabled,
            "artifact_write_enabled": self.artifact_write_enabled,
            "artifact_root": str(self.artifact_root) if self.artifact_root else None,
            "batch_limits": {
                "max_input_bytes": self.batch_max_input_bytes,
                "max_requests": self.batch_max_requests,
                "max_output_bytes": self.batch_max_output_bytes,
            },
        }

    def resolve_artifact_path(self, raw_path: str) -> Path:
        if not self.artifact_write_enabled or self.artifact_root is None:
            raise ConfigError(
                ARTIFACT_WRITE_ENV,
                "0",
                "'1' with XVERIF_MCP_ARTIFACT_ROOT configured",
            )
        if not isinstance(raw_path, str) or not raw_path or raw_path != raw_path.strip():
            raise ConfigError(ARTIFACT_ROOT_ENV, str(raw_path), "a non-empty artifact path")
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.artifact_root / candidate
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.artifact_root):
            raise ConfigError(
                ARTIFACT_ROOT_ENV,
                raw_path,
                f"a path contained by {self.artifact_root}",
            )
        return resolved


def _strict_env_flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise ConfigError(name, raw, "'0' or '1'")


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
    mutation_enabled = _strict_env_flag(snapshot, MUTATION_ENV, True)
    artifact_write_enabled = _strict_env_flag(snapshot, ARTIFACT_WRITE_ENV, False)
    configured_root = snapshot.get(ARTIFACT_ROOT_ENV)
    artifact_root: Path | None = None
    if artifact_write_enabled:
        if not configured_root or configured_root != configured_root.strip():
            raise ConfigError(
                ARTIFACT_ROOT_ENV,
                configured_root or "",
                "an existing directory when artifact writes are enabled",
            )
        artifact_root = Path(configured_root).resolve(strict=False)
        if not artifact_root.is_dir():
            raise ConfigError(
                ARTIFACT_ROOT_ENV,
                configured_root,
                "an existing directory when artifact writes are enabled",
            )
    return ToolPolicy(
        groups=tuple(
            (group, _strict_env_flag(snapshot, env_name, default))
            for group, (env_name, default) in GROUP_ENV.items()
        ),
        mutation_enabled=mutation_enabled,
        artifact_write_enabled=artifact_write_enabled,
        artifact_root=artifact_root,
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


def filtered_catalog(
    policy: ToolPolicy,
    catalog: Iterable[dict[str, Any]],
    category: Optional[str] = None,
    include_write: bool = False,
) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for item in catalog:
        if category and item.get("category") != category:
            continue
        mutation = bool(item.get("mutation", False))
        artifact_write = bool(item.get("artifact_write", False))
        if (mutation or artifact_write) and not include_write:
            continue
        group = str(item.get("group") or item.get("category") or "")
        if not policy.tool_enabled(
            group,
            mutation=mutation,
            artifact_write=artifact_write,
        ):
            continue
        tools.append(dict(item))
    return tools
