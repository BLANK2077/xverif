"""Explicit MCP policy capabilities for dynamically dispatched actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionCapability:
    mutation: bool = False
    artifact_write: str = "never"

    def __post_init__(self) -> None:
        if self.artifact_write not in {"never", "conditional", "required"}:
            raise ValueError(f"invalid artifact_write capability: {self.artifact_write}")


XDEBUG_MUTATION_ACTIONS = frozenset({
    "apb.config.load",
    "apb.transaction.cursor",
    "axi.config.load",
    "axi.transaction.cursor",
    "event.config.load",
    "list.add",
    "list.create",
    "list.load",
    "list.delete",
    "trace.load",
    "waveform.cursor.delete",
    "waveform.cursor.set",
    "waveform.cursor.use",
})

XDEBUG_CONDITIONAL_ARTIFACT_ACTIONS = frozenset({
    "apb.export",
    "axi.export",
    "event.export",
    "list.export",
    "stream.export",
})

XDEBUG_REQUIRED_ARTIFACT_ACTIONS = frozenset({"nwave.rc.generate"})

XCOV_MUTATION_ACTIONS = frozenset({
    "exclude.load",
    "exclude.add",
    "exclude.remove",
    "exclude.instance.add",
    "exclude.instance.remove",
    "exclude.functional.add",
    "exclude.functional.remove",
    "exclude.unload_all",
    "exclude.csv.apply",
    "exclude.csv.compile",
    "exclude.csv.export",
})

XCOV_REQUIRED_ARTIFACT_ACTIONS = frozenset({
    "export.code_coverage",
    "export.functional_coverage",
    "export.assert",
    "export.exclude",
    "exclude.csv.compile",
    "exclude.csv.export",
})


def xdebug_capability(action: str, args: dict[str, Any]) -> ActionCapability:
    if action in XDEBUG_REQUIRED_ARTIFACT_ACTIONS:
        artifact_write = "required"
    elif action in XDEBUG_CONDITIONAL_ARTIFACT_ACTIONS:
        output = args.get("output")
        artifact_write = (
            "conditional"
            if isinstance(output, dict) and bool(output.get("path"))
            else "never"
        )
    else:
        artifact_write = "never"
    return ActionCapability(
        mutation=action in XDEBUG_MUTATION_ACTIONS,
        artifact_write=artifact_write,
    )


def xcov_capability(action: str, args: dict[str, Any]) -> ActionCapability:
    artifact_write = "required" if action in XCOV_REQUIRED_ARTIFACT_ACTIONS else "never"
    if action == "exclude.csv.format" and args.get("write") is True:
        artifact_write = "conditional"
    return ActionCapability(
        mutation=action in XCOV_MUTATION_ACTIONS,
        artifact_write=artifact_write,
    )
