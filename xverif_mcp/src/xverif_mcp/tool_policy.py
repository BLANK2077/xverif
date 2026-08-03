"""Strict tool exposure policy for xverif MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ToolPolicy:
    """One immutable tool-exposure snapshot."""

    groups: tuple[tuple[str, bool], ...]
    write_enabled: bool = False

    def group_enabled(self, group: str) -> bool:
        return dict(self.groups).get(group, False)

    def tool_enabled(self, group: str, *, write: bool = False) -> bool:
        if write and not self.write_enabled:
            return False
        return self.group_enabled(group)

    def summary(self) -> dict[str, Any]:
        return {"groups": dict(self.groups), "write_enabled": self.write_enabled}


def _strict_env_flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise ConfigError(name, raw, "'0' or '1'")


def resolve_tool_policy(environ: Mapping[str, str] | None = None) -> ToolPolicy:
    snapshot = dict(os.environ if environ is None else environ)
    return ToolPolicy(
        groups=tuple(
            (group, _strict_env_flag(snapshot, env_name, default))
            for group, (env_name, default) in GROUP_ENV.items()
        )
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
        write = bool(item.get("write", False))
        if write and not include_write:
            continue
        group = str(item.get("group") or item.get("category") or "")
        if not policy.tool_enabled(group, write=write):
            continue
        tools.append(dict(item))
    return tools
