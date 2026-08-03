"""Strict response-schema fragments for session lifecycle and ``batch``.

This module is intentionally independent from the response-schema generator.
It exposes pure functions so the generator can inline the returned definitions
without using an external schema loader at runtime.

All emitted keywords are supported by Draft 7.  ``$defs`` is used only as a
JSON-Pointer container (Draft 7 permits unknown annotation keywords and
resolves local ``$ref`` pointers into them).
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


Schema = dict[str, Any]

SESSION_MODES = ("design", "waveform", "combined")
SESSION_TRANSPORTS = ("uds", "tcp", "file")
SESSION_HEALTH_STATUSES = (
    "healthy",
    "registry_missing",
    "process_exited",
    "socket_missing",
    "connect_failed",
    "ping_failed",
    "dbdir_missing",
    "dbdir_changed",
    "fsdb_missing",
    "fsdb_changed",
)

_CORE_RESPONSE_FIELDS = (
    "api_version",
    "ok",
    "action",
    "tool",
    "session",
    "summary",
    "data",
    "error",
)
_DATA_POINTER = "/data"


def _closed(
    properties: Mapping[str, Schema],
    required: Iterable[str] = (),
) -> Schema:
    schema: Schema = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    required_fields = sorted(set(required))
    if required_fields:
        schema["required"] = required_fields
    return schema


def _array(
    items: Schema,
    *,
    min_items: int | None = None,
    max_items: int | None = None,
) -> Schema:
    schema: Schema = {"type": "array", "items": items}
    if min_items is not None:
        schema["minItems"] = min_items
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _ref(name: str) -> Schema:
    return {"$ref": f"#/$defs/{name}"}


def _error_summary_schema() -> Schema:
    return _closed(
        {
            "status": {"const": "error"},
            "error_code": {"type": "string", "minLength": 1},
        },
        ("status", "error_code"),
    )


def session_response_contract_definitions(
    *,
    tool_ref: str = "#/$defs/tool",
    session_record_ref: str = "#/$defs/sessionRecord",
    generic_error_ref: str = "#/$defs/genericError",
) -> dict[str, Schema]:
    """Return strict compact evidence definitions for session responses.

    Public lifecycle actions never embed another public response envelope.
    A live execution context belongs only to the top-level ``session`` field;
    removed records and cleanup diagnostics are compact evidence in ``data``.
    """

    del tool_ref, generic_error_ref
    health_evidence = _closed(
        {
            "code": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
            "health_status": {
                "enum": list(SESSION_HEALTH_STATUSES),
            },
        },
        ("code", "message"),
    )
    definitions: dict[str, Schema] = {
        "sessionHealthFailureEvidence": health_evidence,
    }
    cleanup_properties = {
        "removed_session": {"$ref": session_record_ref},
        "reason": {"enum": ["idle_timeout", "unhealthy"]},
        "health_evidence": _ref("sessionHealthFailureEvidence"),
        "idle_sec": {"type": "integer", "minimum": 0},
        "idle_timeout_sec": {"type": "integer", "minimum": 0},
    }
    cleanup_item = _closed(
        cleanup_properties,
        ("removed_session", "reason"),
    )
    cleanup_item["allOf"] = [
        {
            "oneOf": [
                {
                    "properties": {
                        "reason": {"const": "idle_timeout"},
                    },
                    "required": [
                        "reason",
                        "idle_sec",
                        "idle_timeout_sec",
                    ],
                    "not": {"required": ["health_evidence"]},
                },
                {
                    "properties": {
                        "reason": {"const": "unhealthy"},
                        "health_evidence": _ref(
                            "sessionHealthFailureEvidence"
                        ),
                    },
                    "required": ["reason", "health_evidence"],
                    "not": {
                        "anyOf": [
                            {"required": ["idle_sec"]},
                            {"required": ["idle_timeout_sec"]},
                        ]
                    },
                },
            ]
        }
    ]
    definitions["sessionCleanupItem"] = cleanup_item
    return definitions


@dataclass(frozen=True)
class SessionSuccessVariant:
    """One correlated public lifecycle success summary/data pair."""

    name: str
    summary: Schema
    data: Schema


def _non_negative_integer(*, minimum: int = 0) -> Schema:
    return {"type": "integer", "minimum": minimum}


def _session_open_contract() -> tuple[SessionSuccessVariant, ...]:
    return (
        SessionSuccessVariant(
            "opened",
            _closed(
                {"status": {"const": "opened"}},
                ("status",),
            ),
            _closed(
                {
                    "run_manifest": {
                        "anyOf": [
                            {"type": "null"},
                            _ref("runManifest"),
                        ]
                    }
                },
                ("run_manifest",),
            ),
        ),
    )


def _session_list_contract() -> tuple[SessionSuccessVariant, ...]:
    sessions = _array(_ref("sessionRecord"))
    removed = _array(_ref("sessionCleanupItem"))
    return (
        SessionSuccessVariant(
            "without_expired_cleanup",
            _closed(
                {
                    "session_count": _non_negative_integer(),
                    "expired_removed_count": {"const": 0},
                },
                ("session_count", "expired_removed_count"),
            ),
            _closed({"sessions": sessions}, ("sessions",)),
        ),
        SessionSuccessVariant(
            "with_expired_cleanup",
            _closed(
                {
                    "session_count": _non_negative_integer(),
                    "expired_removed_count": _non_negative_integer(
                        minimum=1
                    ),
                },
                ("session_count", "expired_removed_count"),
            ),
            _closed(
                {
                    "sessions": sessions,
                    "removed": _array(
                        _ref("sessionCleanupItem"),
                        min_items=1,
                    ),
                },
                ("sessions", "removed"),
            ),
        ),
    )


def _session_doctor_contract() -> tuple[SessionSuccessVariant, ...]:
    return (
        SessionSuccessVariant(
            "healthy",
            _closed({"healthy": {"const": True}}, ("healthy",)),
            _closed(
                {
                    "message": {
                        "type": "string",
                        "minLength": 1,
                    }
                },
                ("message",),
            ),
        ),
    )


def _session_remove_contract() -> tuple[SessionSuccessVariant, ...]:
    return (
        SessionSuccessVariant(
            "single",
            _closed({"removed": {"const": True}}, ("removed",)),
            _closed(
                {"removed_session": _ref("sessionRecord")},
                ("removed_session",),
            ),
        ),
        SessionSuccessVariant(
            "bulk_empty",
            _closed(
                {
                    "requested_count": {"const": 0},
                    "removed_count": {"const": 0},
                },
                ("requested_count", "removed_count"),
            ),
            _closed(
                {
                    "removed_sessions": _array(
                        _ref("sessionRecord"),
                        max_items=0,
                    )
                },
                ("removed_sessions",),
            ),
        ),
        SessionSuccessVariant(
            "bulk_populated",
            _closed(
                {
                    "requested_count": _non_negative_integer(minimum=1),
                    "removed_count": _non_negative_integer(minimum=1),
                },
                ("requested_count", "removed_count"),
            ),
            _closed(
                {
                    "removed_sessions": _array(
                        _ref("sessionRecord"),
                        min_items=1,
                    )
                },
                ("removed_sessions",),
            ),
        ),
    )


def _session_gc_contract() -> tuple[SessionSuccessVariant, ...]:
    kept = _ref("sessionRecord")
    removed = _ref("sessionCleanupItem")

    def variant(
        name: str,
        *,
        kept_present: bool,
        removed_present: bool,
    ) -> SessionSuccessVariant:
        kept_count: Schema = (
            _non_negative_integer(minimum=1)
            if kept_present
            else {"const": 0}
        )
        removed_count: Schema = (
            _non_negative_integer(minimum=1)
            if removed_present
            else {"const": 0}
        )
        minimum_before = int(kept_present) + int(removed_present)
        before_count: Schema = (
            _non_negative_integer(minimum=minimum_before)
            if minimum_before
            else {"const": 0}
        )
        return SessionSuccessVariant(
            name,
            _closed(
                {
                    "before_count": before_count,
                    "kept_count": kept_count,
                    "removed_count": removed_count,
                },
                ("before_count", "kept_count", "removed_count"),
            ),
            _closed(
                {
                    "kept_sessions": _array(
                        kept,
                        min_items=1 if kept_present else None,
                        max_items=None if kept_present else 0,
                    ),
                    "removed": _array(
                        removed,
                        min_items=1 if removed_present else None,
                        max_items=None if removed_present else 0,
                    ),
                },
                ("kept_sessions", "removed"),
            ),
        )

    return (
        variant(
            "empty",
            kept_present=False,
            removed_present=False,
        ),
        variant(
            "kept_only",
            kept_present=True,
            removed_present=False,
        ),
        variant(
            "removed_only",
            kept_present=False,
            removed_present=True,
        ),
        variant(
            "kept_and_removed",
            kept_present=True,
            removed_present=True,
        ),
    )


_SESSION_SUCCESS_CONTRACT_FACTORIES = {
    "session.open": _session_open_contract,
    "session.list": _session_list_contract,
    "session.doctor": _session_doctor_contract,
    "session.close": _session_remove_contract,
    "session.kill": _session_remove_contract,
    "session.gc": _session_gc_contract,
}
SESSION_RESPONSE_ACTIONS = frozenset(_SESSION_SUCCESS_CONTRACT_FACTORIES)


def session_success_response_variants(
    action: str,
) -> tuple[SessionSuccessVariant, ...]:
    """Return explicit correlated success variants for one lifecycle action."""

    factory = _SESSION_SUCCESS_CONTRACT_FACTORIES.get(action)
    if factory is None:
        raise ValueError(
            f"{action}: no explicit session success response contract"
        )
    return copy.deepcopy(factory())


_SESSION_EXPLICIT_DEFINITION = {
    ("session.close", _DATA_POINTER + "/removed_session"):
        "sessionRecord",
    ("session.kill", _DATA_POINTER + "/removed_session"):
        "sessionRecord",
    ("session.close", _DATA_POINTER + "/removed_sessions/*"):
        "sessionRecord",
    ("session.kill", _DATA_POINTER + "/removed_sessions/*"):
        "sessionRecord",
    ("session.gc", _DATA_POINTER + "/kept_sessions/*"):
        "sessionRecord",
    ("session.gc", _DATA_POINTER + "/removed/*"): "sessionCleanupItem",
    # session.list runs the same idle-expiry cleanup before returning records.
    ("session.list", _DATA_POINTER + "/removed/*"): "sessionCleanupItem",
}


def session_explicit_response_schema(
    action: str,
    pointer: str,
) -> Schema | None:
    """Return the strict generator override for a session response pointer."""

    name = _SESSION_EXPLICIT_DEFINITION.get((action, pointer))
    return _ref(name) if name is not None else None


def _pointer_escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _pointer_unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _definition_stem(prefix: str, action: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_]", "_", action).strip("_")
    if not readable:
        readable = "action"
    digest = hashlib.sha256(action.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{readable}_{digest}"


def _local_definition_ref(name: str) -> str:
    return f"#/$defs/{_pointer_escape(name)}"


def _rewrite_local_refs(
    value: Any,
    definition_names: Mapping[str, str],
) -> Any:
    if isinstance(value, list):
        return [
            _rewrite_local_refs(item, definition_names)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    rewritten: dict[str, Any] = {}
    for key, child in value.items():
        if key in {"$schema", "$id"}:
            raise ValueError(
                "nested schema scope keywords cannot be namespaced safely: "
                f"{key}"
            )
        if key == "$ref":
            if not isinstance(child, str):
                raise ValueError("$ref must be a string")
            prefix = "#/$defs/"
            if not child.startswith(prefix):
                raise ValueError(
                    "batch child response contains non-definition or "
                    f"external $ref: {child}"
                )
            tail = child[len(prefix) :]
            encoded_name, separator, suffix = tail.partition("/")
            local_name = _pointer_unescape(encoded_name)
            if local_name not in definition_names:
                raise ValueError(
                    "batch child response has unresolved local definition "
                    f"reference: {child}"
                )
            target = _local_definition_ref(
                definition_names[local_name]
            )
            rewritten[key] = (
                target
                if not separator
                else f"{target}/{suffix}"
            )
            continue
        rewritten[key] = _rewrite_local_refs(
            child,
            definition_names,
        )
    return rewritten


def _namespace_public_response_schema(
    action: str,
    schema: Mapping[str, Any],
    *,
    definition_prefix: str,
) -> tuple[str, dict[str, Schema]]:
    if not isinstance(schema, Mapping):
        raise TypeError(
            f"{action}: public response schema must be an object"
        )
    properties = schema.get("properties")
    discriminator = (
        properties.get("action")
        if isinstance(properties, Mapping)
        else None
    )
    if (
        not isinstance(discriminator, Mapping)
        or discriminator.get("const") != action
    ):
        raise ValueError(
            f"{action}: public response schema must use "
            "properties.action.const as its discriminator"
        )
    local_definitions = schema.get("$defs", {})
    if not isinstance(local_definitions, Mapping):
        raise ValueError(f"{action}: $defs must be an object")

    stem = _definition_stem(definition_prefix, action)
    root_name = f"{stem}__response"
    names = {
        name: f"{stem}__{name}"
        for name in local_definitions
    }
    rewritten_definitions: dict[str, Schema] = {}
    for local_name, local_schema in local_definitions.items():
        if not isinstance(local_name, str):
            raise ValueError(f"{action}: $defs keys must be strings")
        if not isinstance(local_schema, Mapping):
            raise ValueError(
                f"{action}: $defs.{local_name} must be an object"
            )
        rewritten_definitions[names[local_name]] = (
            _rewrite_local_refs(
                copy.deepcopy(dict(local_schema)),
                names,
            )
        )

    root = copy.deepcopy(dict(schema))
    root.pop("$defs", None)
    # The enclosing generated batch response owns the document scope.
    root.pop("$schema", None)
    root.pop("$id", None)
    rewritten_root = _rewrite_local_refs(root, names)
    rewritten_definitions[root_name] = rewritten_root
    return root_name, rewritten_definitions


def _unknown_child_error_schema(
    known_actions: Iterable[str],
    *,
    tool_ref: str,
    generic_error_ref: str,
) -> Schema:
    actions = sorted(set(known_actions))
    action_schema: Schema = {"type": "string"}
    if actions:
        action_schema["not"] = {"enum": actions}
    return _closed(
        {
            "api_version": {"const": "xdebug.v1"},
            "request_id": {"type": "string", "minLength": 1},
            "ok": {"const": False},
            "action": action_schema,
            "tool": {"$ref": tool_ref},
            # Dispatcher envelope/schema/unknown-action failures are created
            # before a child session can be attached.
            "session": {"type": "null"},
            "summary": _error_summary_schema(),
            "data": {"type": "null"},
            "error": {"$ref": generic_error_ref},
        },
        (*_CORE_RESPONSE_FIELDS, "error"),
    )


@dataclass(frozen=True)
class BatchResultContract:
    """A local item schema plus the definitions it references."""

    item_schema: Schema
    definitions: dict[str, Schema]
    known_actions: tuple[str, ...]


def build_batch_result_contract(
    action_response_schemas: Mapping[str, Mapping[str, Any]],
    *,
    known_actions: Iterable[str] | None = None,
    batch_action: str = "batch",
    batch_response_ref: str = "#",
    definition_prefix: str = "batchChild",
    tool_ref: str = "#/$defs/tool",
    generic_error_ref: str = "#/$defs/genericError",
) -> BatchResultContract:
    """Build an action-discriminated, fully local ``batch`` result union.

    ``action_response_schemas`` must contain every known non-batch public
    response schema.  Supplying a partial map is an error: this function never
    falls back to an open JSON branch.  If the map also contains ``batch``, its
    discriminator is checked but the schema is represented by
    ``batch_response_ref`` so nested batches recurse into the enclosing batch
    response instead of expanding indefinitely.
    """

    if not isinstance(action_response_schemas, Mapping):
        raise TypeError("action_response_schemas must be a mapping")
    if not batch_action:
        raise ValueError("batch_action must be non-empty")
    if not batch_response_ref.startswith("#"):
        raise ValueError(
            "batch_response_ref must be a local reference"
        )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", definition_prefix):
        raise ValueError(
            "definition_prefix must be a JSON-schema-safe identifier"
        )

    supplied = set(action_response_schemas)
    if any(not isinstance(action, str) or not action for action in supplied):
        raise ValueError("public action names must be non-empty strings")
    if known_actions is None:
        known = supplied | {batch_action}
    else:
        known = set(known_actions)
        if any(not isinstance(action, str) or not action for action in known):
            raise ValueError("known action names must be non-empty strings")
        known.add(batch_action)

    expected_non_batch = known - {batch_action}
    supplied_non_batch = supplied - {batch_action}
    missing = sorted(expected_non_batch - supplied_non_batch)
    extra = sorted(supplied_non_batch - expected_non_batch)
    if missing or extra:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise ValueError(
            "batch child response catalog mismatch ("
            + "; ".join(details)
            + ")"
        )

    if batch_action in action_response_schemas:
        batch_schema = action_response_schemas[batch_action]
        properties = (
            batch_schema.get("properties")
            if isinstance(batch_schema, Mapping)
            else None
        )
        discriminator = (
            properties.get("action")
            if isinstance(properties, Mapping)
            else None
        )
        if (
            not isinstance(discriminator, Mapping)
            or discriminator.get("const") != batch_action
        ):
            raise ValueError(
                f"{batch_action}: public response schema must use "
                "properties.action.const as its discriminator"
            )

    definitions: dict[str, Schema] = {}
    branches: list[Schema] = []
    for action in sorted(expected_non_batch):
        root_name, child_definitions = (
            _namespace_public_response_schema(
                action,
                action_response_schemas[action],
                definition_prefix=definition_prefix,
            )
        )
        overlap = set(definitions) & set(child_definitions)
        if overlap:
            raise ValueError(
                "namespaced batch definitions collided: "
                + ", ".join(sorted(overlap))
            )
        definitions.update(child_definitions)
        branches.append({"$ref": _local_definition_ref(root_name)})

    branches.append({"$ref": batch_response_ref})
    unknown_name = f"{definition_prefix}__unknown_child_error"
    if unknown_name in definitions:
        raise ValueError(
            f"batch definition name collided: {unknown_name}"
        )
    definitions[unknown_name] = _unknown_child_error_schema(
        known,
        tool_ref=tool_ref,
        generic_error_ref=generic_error_ref,
    )
    branches.append({"$ref": _local_definition_ref(unknown_name)})

    return BatchResultContract(
        item_schema={"oneOf": branches},
        definitions=definitions,
        known_actions=tuple(sorted(known)),
    )


__all__ = [
    "BatchResultContract",
    "SESSION_HEALTH_STATUSES",
    "SESSION_MODES",
    "SESSION_RESPONSE_ACTIONS",
    "SESSION_TRANSPORTS",
    "SessionSuccessVariant",
    "build_batch_result_contract",
    "session_explicit_response_schema",
    "session_response_contract_definitions",
    "session_success_response_variants",
]
