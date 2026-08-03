"""Stateless xsva adapter backed by the public CLI contract."""
from __future__ import annotations

from typing import Any, Iterable

from xsva.contracts import ResponseContractError, validate_response
from xverif_mcp.errors import error_payload
from xverif_mcp.runner import StatelessCliRunner

_RUNNER_ERROR_FIELDS = {
    "XVERIF_CLI_FAILED": {
        "code", "message", "tool", "exit_code", "stdout_present",
        "stderr_present", "stdout_length", "stderr_length",
    },
    "XVERIF_BAD_JSON_RESPONSE": {
        "code", "message", "tool", "stdout_present", "stderr_present",
        "stdout_length", "stderr_length",
    },
    "XVERIF_BAD_XOUT_RESPONSE": {
        "code", "message", "tool", "stdout_present", "stderr_present",
        "stdout_length", "stderr_length",
    },
    "XVERIF_TOOL_TIMEOUT": {"code", "message", "tool", "timeout_sec"},
}


def _is_strict_runner_error(result: Any) -> bool:
    if not isinstance(result, dict) or set(result) != {"ok", "error"}:
        return False
    if result["ok"] is not False or not isinstance(result["error"], dict):
        return False
    error = result["error"]
    code = error.get("code")
    if not isinstance(code, str):
        return False
    expected_fields = _RUNNER_ERROR_FIELDS.get(code)
    if expected_fields is None or set(error) != expected_fields:
        return False
    if not isinstance(error["message"], str) or not error["message"] or error["tool"] != "xsva":
        return False
    for field in ("stdout_present", "stderr_present"):
        if field in error and not isinstance(error[field], bool):
            return False
    for field in ("exit_code", "stdout_length", "stderr_length"):
        if field in error and (not isinstance(error[field], int) or isinstance(error[field], bool)):
            return False
    if "timeout_sec" in error and (
        not isinstance(error["timeout_sec"], (int, float))
        or isinstance(error["timeout_sec"], bool)
        or error["timeout_sec"] <= 0
    ):
        return False
    return True


def _invalid_tool_response(action: str, error: Exception | str) -> dict[str, Any]:
    return error_payload(
        "INVALID_TOOL_RESPONSE",
        f"xsva returned a response that violates its public contract: {error}",
        tool="xsva", action=action,
    )


def _validate_json_result(result: Any, action: str) -> Any:
    if _is_strict_runner_error(result):
        return result
    try:
        validate_response(result, expected_action=action)
    except (ResponseContractError, TypeError, ValueError) as exc:
        return _invalid_tool_response(action, exc)
    return result


def _invalid_output_format(output_format: str, *, allowed: Iterable[str]) -> dict[str, Any]:
    allowed_values = tuple(allowed)
    return error_payload(
        "INVALID_OUTPUT_FORMAT",
        f"unsupported output_format={output_format!r}; expected one of {allowed_values!r}",
        output_format=output_format,
        allowed_output_formats=list(allowed_values),
    )


def _run(
    action: str,
    *,
    file: str,
    output_format: str,
    extra_args: list[str] | None = None,
    allow_markdown: bool = False,
) -> Any:
    allowed = ("xout", "json", "markdown") if allow_markdown else ("xout", "json")
    if output_format not in allowed:
        return _invalid_output_format(output_format, allowed=allowed)
    argv = [action, "--file", file, *(extra_args or [])]
    runner = StatelessCliRunner()
    if output_format == "json":
        return _validate_json_result(runner.run_json("xsva", [*argv, "--json"]), action)
    if output_format == "xout":
        result = runner.run_xout("xsva", argv)
        return result if isinstance(result, str) else _validate_json_result(result, action)
    result = runner.run_text("xsva", [*argv, "--markdown"])
    return result if isinstance(result, str) else _validate_json_result(result, action)


def sva_list(file: str, output_format: str = "xout") -> Any:
    return _run("list", file=file, output_format=output_format)


def sva_scan(file: str, output_format: str = "xout") -> Any:
    return _run("scan", file=file, output_format=output_format)


def sva_parse(
    file: str,
    property: str,
    emit: str = "timeline-ir",
    output_format: str = "xout",
) -> Any:
    if emit not in {"surface-ir", "sequence-ir", "timeline-ir"}:
        return error_payload(
            "INVALID_EMIT",
            f"unsupported emit={emit!r}; expected 'surface-ir', 'sequence-ir', or 'timeline-ir'",
            emit=emit,
        )
    return _run(
        "parse", file=file, output_format=output_format,
        extra_args=["--property", property, "--emit", emit],
    )


def sva_explain(
    file: str,
    property: str,
    strict: bool = False,
    output_format: str = "xout",
) -> Any:
    extra_args = ["--property", property]
    if strict:
        extra_args.append("--strict")
    return _run(
        "explain", file=file, output_format=output_format,
        extra_args=extra_args, allow_markdown=True,
    )
