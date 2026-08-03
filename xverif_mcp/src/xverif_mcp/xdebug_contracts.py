"""Canonical xdebug action/resource contracts used by the MCP surface."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xverif_loop.config import repo_root


Json = dict[str, Any]


class XdebugContractError(RuntimeError):
    """Raised when the canonical action registry cannot supply a contract."""


def action_specs_path() -> Path:
    """Return the configured canonical xdebug action registry path."""
    return Path(repo_root()) / "xdebug" / "specs" / "actions" / "actions.yaml"


def _load_action_specs() -> list[Json]:
    path = action_specs_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise XdebugContractError(
            f"cannot read canonical xdebug action contracts from {path}: {exc}"
        ) from exc
    actions = payload.get("actions") if isinstance(payload, dict) else None
    if not isinstance(actions, list) or not all(isinstance(item, dict) for item in actions):
        raise XdebugContractError(
            f"canonical xdebug action registry has invalid actions list: {path}"
        )
    for index, item in enumerate(actions):
        status = item.get("status")
        if status not in {"stable", "experimental"}:
            raise XdebugContractError(
                "canonical xdebug action registry entry "
                f"{index} has unsupported status: {status!r}; "
                "expected 'stable' or 'experimental'"
            )
    return actions


def action_spec(action: str) -> Json | None:
    """Return one canonical action spec, or ``None`` for an unknown action."""
    for item in _load_action_specs():
        if item.get("name") == action:
            return item
    return None


def _variant_session_contract(variant: Json) -> Json:
    name = variant.get("name")
    requires = variant.get("requires")
    required_args = variant.get("required_args")
    forbidden_args = variant.get("forbidden_args")
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(requires, str)
        or requires not in {"none", "design", "waveform", "combined", "any"}
        or not isinstance(required_args, list)
        or not all(isinstance(value, str) and value for value in required_args)
        or not isinstance(forbidden_args, list)
        or not all(isinstance(value, str) and value for value in forbidden_args)
    ):
        raise XdebugContractError(
            "resource_variants entries must define name, requires, "
            "required_args, and forbidden_args"
        )
    return {
        "name": name,
        "requires": requires,
        "required_args": list(required_args),
        "forbidden_args": list(forbidden_args),
        "session_id": "forbidden" if requires == "none" else "required",
    }


def session_contract(action: str) -> Json | None:
    """Project canonical resource metadata into an MCP session contract."""
    spec = action_spec(action)
    if spec is None:
        return None
    raw_variants = spec.get("resource_variants")
    if raw_variants is not None:
        if not isinstance(raw_variants, list) or not raw_variants:
            raise XdebugContractError(
                f"{action} resource_variants must be a non-empty array"
            )
        variants = [_variant_session_contract(item) for item in raw_variants]
        return {
            "parameter": "session_id",
            "mode": "conditional",
            "variants": variants,
        }
    requires = spec.get("requires")
    if not isinstance(requires, str) or requires not in {
        "none", "design", "waveform", "combined", "any", "session"
    }:
        raise XdebugContractError(
            f"{action} has unsupported canonical requires value: {requires!r}"
        )
    state = "forbidden" if requires == "none" else "required"
    return {
        "parameter": "session_id",
        "mode": state,
        "requires": requires,
        "session_id": state,
    }


def select_resource_variant(contract: Json, args: Json) -> Json | None:
    """Select the one canonical resource variant matching argument presence."""
    variants = contract.get("variants")
    if not isinstance(variants, list):
        return None
    matches = [
        variant
        for variant in variants
        if all(name in args for name in variant["required_args"])
        and all(name not in args for name in variant["forbidden_args"])
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def query_session_requirement(action: str, args: Json) -> tuple[Json | None, Json | None]:
    """Return ``(contract, selected_variant)`` for one MCP query."""
    contract = session_contract(action)
    if contract is None:
        return None, None
    if contract["mode"] != "conditional":
        return contract, None
    return contract, select_resource_variant(contract, args)
