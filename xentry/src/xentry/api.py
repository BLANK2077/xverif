from __future__ import annotations

from typing import Any

from .config import load_config_file
from .contracts import validate_response
from .decode import decode_entry, explain_config, validate_entry
from .errors import RequestError
from .fragments import load_fragments_file


API_VERSION = "xentry.v1"
REQUEST_KEYS = {"api_version", "request_id", "action", "config", "config_path",
                "fragments", "input_path"}


def dispatch_request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise RequestError("request must be a JSON object")
    unknown = sorted(set(request) - REQUEST_KEYS)
    if unknown:
        raise RequestError("request contains unsupported fields", field=unknown[0])
    if request.get("api_version") != API_VERSION:
        raise RequestError("api_version must be xentry.v1", field="api_version")
    action = request.get("action")
    if action not in {"decode", "explain", "validate"}:
        raise RequestError("action must be decode, explain, or validate", field="action")
    if "request_id" in request and (not isinstance(request["request_id"], str) or not request["request_id"]):
        raise RequestError("request_id must be a non-empty string", field="request_id")
    if action == "explain" and ("fragments" in request or "input_path" in request):
        raise RequestError("explain does not accept fragments or input_path",
                           field="fragments" if "fragments" in request else "input_path")
    config = resolve_config(request)
    fragments = resolve_fragments(request, required=action == "decode")
    if action == "decode":
        assert fragments is not None
        payload = decode_entry(config, fragments)
    elif action == "explain":
        payload = explain_config(config)
    else:
        payload = validate_entry(config, fragments)
    if "request_id" in request:
        payload["request_id"] = request["request_id"]
    validate_response(payload, expected_action=action)
    return payload


def resolve_config(request: dict) -> dict:
    has_config = "config" in request
    has_path = "config_path" in request
    if has_config == has_path:
        raise RequestError("request must provide exactly one of config or config_path")
    if has_config:
        config = request["config"]
    else:
        config_path = request["config_path"]
        if not isinstance(config_path, str) or not config_path:
            raise RequestError("config_path must be a non-empty string")
        config = load_config_file(config_path)
    if not isinstance(config, dict):
        raise RequestError("config must be an object")
    return config


def resolve_fragments(request: dict, *, required: bool) -> list[dict] | None:
    has_fragments = "fragments" in request
    has_path = "input_path" in request
    if has_fragments and has_path:
        raise RequestError("request must not provide both fragments and input_path")
    if not has_fragments and not has_path:
        if required:
            raise RequestError("decode requires fragments or input_path")
        return None
    if has_fragments:
        fragments = request["fragments"]
    else:
        input_path = request["input_path"]
        if not isinstance(input_path, str) or not input_path:
            raise RequestError("input_path must be a non-empty string")
        fragments = load_fragments_file(input_path)
    if not isinstance(fragments, list):
        raise RequestError("fragments must be an array")
    return fragments
