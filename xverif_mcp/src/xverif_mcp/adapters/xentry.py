"""Stateless xentry adapter — deterministic entry field decoder."""
from __future__ import annotations

from typing import Any, Optional

from xverif_mcp.import_paths import ensure_tool_import_paths

ensure_tool_import_paths()

from xentry.api import dispatch_request
from xentry.contracts import validate_response
from xentry.errors import RequestError
from xentry.format import error_response, to_xout


def _xentry_request(action: str, config_path: Optional[str] = None,
                    input_path: Optional[str] = None,
                    config: Optional[dict] = None,
                    fragments: Optional[list] = None,
                    output_format: str = "xout") -> Any:
    req: dict = {"api_version": "xentry.v1", "action": action}
    if config_path is not None:
        req["config_path"] = config_path
    if input_path is not None:
        req["input_path"] = input_path
    if config is not None:
        req["config"] = config
    if fragments is not None:
        req["fragments"] = fragments
    if output_format not in {"json", "xout"}:
        return error_response(RequestError("output_format must be json or xout", field="output_format"), action=action)
    try:
        payload = dispatch_request(req)
    except Exception as exc:
        payload = error_response(exc, action=action)
    validate_response(payload, expected_action=action)
    if output_format == "json":
        return payload
    return to_xout(payload)


def entry_decode(config_path: str = "", input_path: str = "",
                 config: Optional[dict] = None,
                 fragments: Optional[list] = None,
                 output_format: str = "xout") -> Any:
    """Decode multi-beat fragments into raw field slices per config."""
    return _xentry_request("decode", config_path=config_path or None,
                           input_path=input_path or None,
                           config=config, fragments=fragments,
                           output_format=output_format)


def entry_explain(config_path: str, output_format: str = "xout") -> Any:
    """Explain the field layout defined by a config."""
    return _xentry_request("explain", config_path=config_path,
                           output_format=output_format)


def entry_validate(config_path: str = "", input_path: Optional[str] = None,
                   config: Optional[dict] = None,
                   fragments: Optional[list] = None,
                   output_format: str = "xout") -> Any:
    """Validate a config (and optionally an input) without decoding."""
    return _xentry_request("validate", config_path=config_path or None,
                           input_path=input_path,
                           config=config, fragments=fragments,
                           output_format=output_format)
