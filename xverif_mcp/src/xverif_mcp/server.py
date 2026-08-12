"""xverif-mcp — unified MCP server for all xverif tools."""

import inspect
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from xverif_loop.config import resolve_mcp_runtime_config
from xverif_loop.json_contract import strict_json_dumps
from xverif_loop.logging import resolve_logger
from xverif_mcp.import_paths import ensure_tool_import_paths

ensure_tool_import_paths()

from xverif_mcp.adapters.xdebug import XverifDebugAdapter
from xverif_mcp.adapters.xcov import XverifCoverageAdapter
from xverif_mcp.adapters.xbit import bit_conv, bit_eval, bit_slice, bit_check
from xverif_mcp.adapters.xentry import entry_decode, entry_explain, entry_validate
from xverif_mcp.adapters.xloc import loc_resolve, loc_context, loc_stats, loc_annotate
from xverif_mcp.adapters.xsva import sva_list, sva_scan, sva_parse, sva_explain
from xverif_mcp.errors import error_payload
from xverif_mcp.framing import strict_json_loads, validate_xout_text
from xverif_mcp.tool_policy import filtered_catalog, resolve_tool_policy
from xverif_loop.xdebug_errors import (
    forbidden_native_session_error,
    is_forbidden_native_session_action,
)
from xverif_mcp.xdebug_contracts import (
    XdebugContractError,
    query_session_requirement,
)

# ---------------------------------------------------------------------------
# FastMCP application
# ---------------------------------------------------------------------------

INSTRUCTIONS = """Use xverif for deterministic chip verification: design/FSDB debug, coverage, bit math, entry decode, log locations, and SVA semantics. MCP details load via Tool Search. Before xdebug, call xverif_tools once for all action names, status, and purposes, then xverif_debug_get_schema(action); never guess. Resource-backed xdebug: session_open -> query -> session_close; requires:none forbids session_id. xcov query requires session_id. Never auto-retry/reopen/fallback or switch backend, transport, or data source.

| xdebug task | Action families |
|---|---|
| Catalog/resources | actions, schema, session.*, scope.* |
| Values/proof | value.*, signal.*, expr.*, verify.*, window.verify |
| Static/dynamic cause | signal.resolve/canonicalize, trace.* |
| APB | apb.config.*, query, statistics, transaction.cursor, transfer_window |
| AXI | axi.config.*, query/statistics/analysis/export, transaction.cursor, channel_stall, latency_outlier, outstanding_timeline, request_response_pair |
| Streams | stream.config.*, describe/validate/query/export, protocol.handshake.inspect |
| Events | event.config.*, find/export, counter.statistics |
| Collections | list.*, waveform.cursor.*, nwave.rc.generate |

For key signals/interfaces, build schema-valid JSON and load it with list.load, stream.config.load, axi.config.load, or apb.config.load before inspection. After a successful load, follow recommended_actions; value.at is first and accepts exactly one signal/list/apb/stream/axi selector plus time or ordered unique times. Prefer one value.at multi-time query over repeated batch calls; use list.first_change/export for ranges.

Other families: xcov=coverage; xbit=bit math; xentry=structured decode; xloc=location resolve/annotate; xsva=temporal semantics. xverif_batch is strict serial; put query parameters in inner args. Coverage limits/export output stay in action args. Check experimental status and completeness before conclusions. Detailed workflows: xverif and xverif-admin skills."""


def _cleanup_stateful_sessions() -> None:
    for adapter in (debug, cov):
        try:
            adapter.close_all()
        except Exception as exc:
            MCP_LOGGER.try_server(
                "mcp.shutdown.cleanup_failed",
                False,
                backend=getattr(adapter, "mode", adapter.__class__.__name__),
                error_type=type(exc).__name__,
            )


@asynccontextmanager
async def _mcp_lifespan(app):
    try:
        yield {}
    finally:
        _cleanup_stateful_sessions()


mcp = FastMCP(
    name="xverif",
    instructions=INSTRUCTIONS,
    lifespan=_mcp_lifespan,
)

MCP_RUNTIME = resolve_mcp_runtime_config()
MCP_LOGGER = resolve_logger(MCP_RUNTIME)
MCP_TOOL_POLICY = resolve_tool_policy()
debug = XverifDebugAdapter(runtime=MCP_RUNTIME, logger=MCP_LOGGER)
cov = XverifCoverageAdapter(runtime=MCP_RUNTIME, logger=MCP_LOGGER)


def _tool_error(code: str, message: str, **extra: Any) -> dict:
    return error_payload(code, message, **extra)


def _write_output(result: Any, path: str, append: bool) -> None:
    mode = "a" if append else "w"
    if isinstance(result, str):
        encoded = result
    else:
        encoded = strict_json_dumps(result, ensure_ascii=False, sort_keys=True)
    with open(path, mode, encoding="utf-8") as f:
        f.write(encoded)


def _output_write_failed(result: Any, path: str, exc: OSError) -> CallToolResult:
    payload = _tool_error(
        "OUTPUT_WRITE_FAILED",
        f"cannot write MCP tool output to {path}: {exc}",
        output_path=path,
        error_type=type(exc).__name__,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=strict_json_dumps(payload, ensure_ascii=False))],
        isError=True,
    )


def _output_serialization_failed(path: str, exc: Exception) -> CallToolResult:
    payload = _tool_error(
        "OUTPUT_SERIALIZATION_FAILED",
        f"MCP tool result cannot be encoded as strict JSON for {path}",
        output_path=path,
        error_type=type(exc).__name__,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=strict_json_dumps(payload, ensure_ascii=False))],
        isError=True,
    )


def _wrap_with_output(fn):
    """Wrap a tool function so it accepts ``xverif_output_path`` and
    ``xverif_output_append`` keyword arguments.  When *output_path* is
    given the raw return value is also written to that file."""
    sig = inspect.signature(fn)
    new_params = list(sig.parameters.values()) + [
        inspect.Parameter("xverif_output_path", inspect.Parameter.KEYWORD_ONLY,
                          default=None, annotation=Optional[str]),
        inspect.Parameter("xverif_output_append", inspect.Parameter.KEYWORD_ONLY,
                          default=False, annotation=bool),
    ]
    new_sig = sig.replace(parameters=new_params, return_annotation=Any)

    if inspect.iscoroutinefunction(fn):
        async def wrapper(*args, **kwargs):
            output_path = kwargs.pop("xverif_output_path", None)
            output_append = kwargs.pop("xverif_output_append", False)
            result = await fn(*args, **kwargs)
            if output_path:
                try:
                    _write_output(result, output_path, output_append)
                except OSError as exc:
                    return _output_write_failed(result, output_path, exc)
                except (TypeError, ValueError) as exc:
                    return _output_serialization_failed(output_path, exc)
            return result
    else:
        def wrapper(*args, **kwargs):
            output_path = kwargs.pop("xverif_output_path", None)
            output_append = kwargs.pop("xverif_output_append", False)
            result = fn(*args, **kwargs)
            if output_path:
                try:
                    _write_output(result, output_path, output_append)
                except OSError as exc:
                    return _output_write_failed(result, output_path, exc)
                except (TypeError, ValueError) as exc:
                    return _output_serialization_failed(output_path, exc)
            return result

    wrapper.__signature__ = new_sig
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__annotations__ = {}
    return wrapper


def xverif_tool(group: str, write: bool = False):
    """Conditionally register a FastMCP tool according to env policy."""
    def decorator(fn):
        fn = _wrap_with_output(fn)
        if MCP_TOOL_POLICY.tool_enabled(group, write=write):
            registered = mcp.tool()(fn)
            tool = mcp._tool_manager.get_tool(fn.__name__)
            if tool is None:  # pragma: no cover
                raise RuntimeError(f"registered MCP tool not found: {fn.__name__}")
            arg_model = tool.fn_metadata.arg_model
            arg_model.model_config["extra"] = "forbid"
            arg_model.model_config["strict"] = True
            arg_model.model_rebuild(force=True)
            tool.parameters = arg_model.model_json_schema(by_alias=True)
            return registered
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


@xverif_tool("common")
def xverif_ping() -> dict:
    """Ping the xverif MCP server. Use this to check whether the server is alive."""
    return {"ok": True, "result": debug.ping()}


def _batch_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(details)
    return error


def _append_result(output_file: str, tool: str | None, ok: bool,
                   error: dict[str, Any] | None, elapsed_ms: int,
                   response: str | None = None,
                   line_number: int | None = None) -> None:
    entry: dict = {
        "tool": tool,
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "error": error,
    }
    if response is not None:
        entry["response"] = response
    if line_number is not None:
        entry["line_number"] = line_number
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(strict_json_dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


async def _execute_one(
    name: str,
    args: dict,
) -> tuple[bool, dict[str, Any] | None, int, str | None]:
    t0 = time.monotonic()
    try:
        result = await mcp.call_tool(name, args)
    except Exception as exc:
        return (
            False,
            _batch_error("MCP_CALL_ERROR", "MCP tool call failed", error_type=type(exc).__name__),
            int((time.monotonic() - t0) * 1000),
            None,
        )

    try:
        is_error = False
        structured: dict[str, Any] | None = None
        if isinstance(result, CallToolResult):
            is_error = result.isError
            content = result.content
            structured = result.structuredContent
        elif isinstance(result, tuple):
            content, structured = result
        elif isinstance(result, dict):
            content = []
            structured = result
        else:
            content = result

        if structured is not None:
            if type(structured) is not dict:
                raise ValueError("structured MCP result must be an object")
            structured_ok = structured.get("ok")
            if structured_ok is not None and type(structured_ok) is not bool:
                raise ValueError("structured MCP result ok must be boolean")
            ok = not is_error if structured_ok is None else structured_ok and not is_error
            response = strict_json_dumps(structured, ensure_ascii=False, sort_keys=True)
            return (
                ok,
                None if ok else _batch_error(
                    "TOOL_RESULT_ERROR",
                    "MCP tool returned a structured failure result",
                ),
                int((time.monotonic() - t0) * 1000),
                response,
            )

        if not isinstance(content, list) or len(content) != 1:
            raise ValueError("unstructured MCP result must contain exactly one content block")
        block = content[0]
        if not isinstance(block, TextContent):
            raise ValueError("batch supports only text MCP results")
        text = block.text
        if is_error:
            return (
                False,
                _batch_error("MCP_CALL_ERROR", "MCP tool call returned isError=true"),
                int((time.monotonic() - t0) * 1000),
                None,
            )
        try:
            payload = strict_json_loads(text)
            if type(payload) is not dict:
                raise ValueError("JSON MCP result must be an object")
            ok = payload.get("ok")
            if type(ok) is not bool:
                raise ValueError("JSON MCP result requires boolean ok")
        except (json.JSONDecodeError, ValueError):
            validate_xout_text(text)
            ok = True
        return (
            ok,
            None if ok else _batch_error("TOOL_RESULT_ERROR", "MCP tool returned ok=false"),
            int((time.monotonic() - t0) * 1000),
            text,
        )
    except Exception as exc:
        return (
            False,
            _batch_error(
                "BATCH_RESULT_INVALID",
                "MCP tool result violates the batch result contract",
                error_type=type(exc).__name__,
            ),
            int((time.monotonic() - t0) * 1000),
            None,
        )


class _BatchRequestError(ValueError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.error = _batch_error(code, message, **details)


def _validate_batch_request(value: Any) -> tuple[str, dict[str, Any]]:
    if type(value) is not dict:
        raise _BatchRequestError(
            "INVALID_BATCH_REQUEST",
            "batch line must be a JSON object",
            actual_type=type(value).__name__,
        )
    required = {"tool", "args"}
    unexpected = sorted(set(value) - required)
    if unexpected:
        raise _BatchRequestError(
            "INVALID_BATCH_REQUEST",
            "unexpected batch request fields: " + ", ".join(unexpected),
            unexpected_fields=unexpected,
        )
    missing = sorted(required - set(value))
    if missing:
        raise _BatchRequestError(
            "INVALID_BATCH_REQUEST",
            "missing required batch request fields: " + ", ".join(missing),
            missing_fields=missing,
        )
    tool_name = value["tool"]
    if type(tool_name) is not str or not tool_name:
        raise _BatchRequestError(
            "INVALID_BATCH_REQUEST",
            "batch request tool must be a non-empty string",
            invalid_arg="tool",
            expected="non-empty string",
        )
    tool_args = value["args"]
    if type(tool_args) is not dict:
        raise _BatchRequestError(
            "INVALID_BATCH_ARGUMENTS",
            "batch request args must be an object",
            invalid_arg="args",
            expected="object",
            actual_type=type(tool_args).__name__,
        )
    return tool_name, tool_args


@xverif_tool("common")
async def xverif_batch(batch_file: str, output_file: str) -> dict:
    """Execute multiple MCP tool requests from an NDJSON batch file serially.

    Each line is a JSON object with ``tool`` (tool name) and ``args``
    (arguments dict passed to that tool).  Results are written to
    ``output_file`` as NDJSON, one line per request (including parse errors).

    For tools that have their own nested ``args`` parameter (e.g.
    xverif_debug_query, xverif_cov_query), the inner args must be nested:
    ``{"tool":"xverif_debug_query","args":{"session_id":"s0","action":"value.at","args":{"signal":"top.clk","time":"10ns","clock":"top.clk"}}}``

    Returns ``{total, ok_count, failed_count, output_file}``.
    """
    stats = {"total": 0, "ok": 0, "failed": 0}
    if not Path(batch_file).is_file():
        return _tool_error("FILE_NOT_FOUND",
                           f"batch file not found: {batch_file}")

    try:
        with open(batch_file, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    req = strict_json_loads(line)
                except (json.JSONDecodeError, ValueError) as e:
                    _append_result(
                        output_file, None, False,
                        _batch_error(
                            "INVALID_JSON", "batch line is not strict JSON",
                            error_type=type(e).__name__,
                        ),
                        0, line_number=line_number,
                    )
                    stats["failed"] += 1
                    stats["total"] += 1
                    continue

                tool_hint = (
                    req.get("tool")
                    if type(req) is dict and type(req.get("tool")) is str and req.get("tool")
                    else None
                )
                try:
                    tool_name, tool_args = _validate_batch_request(req)
                except _BatchRequestError as exc:
                    _append_result(
                        output_file, tool_hint, False, exc.error, 0,
                        line_number=line_number,
                    )
                    stats["failed"] += 1
                    stats["total"] += 1
                    continue

                ok, error, elapsed_ms, response = await _execute_one(tool_name, tool_args)
                _append_result(output_file, tool_name, ok, error, elapsed_ms, response,
                               line_number=line_number)
                if ok:
                    stats["ok"] += 1
                else:
                    stats["failed"] += 1
                stats["total"] += 1
    except OSError as exc:
        return _tool_error("BATCH_OUTPUT_WRITE_FAILED",
                           f"cannot write batch results to {output_file}: {exc}",
                           output_file=output_file,
                           error_type=type(exc).__name__)
    return {
        "ok": True,
        "total": stats["total"],
        "ok_count": stats["ok"],
        "failed_count": stats["failed"],
        "output_file": output_file,
    }


# ---------------------------------------------------------------------------
# Debug tools (xdebug)
# ---------------------------------------------------------------------------


@xverif_tool("debug")
def xverif_debug_list_actions(
    verbose: bool = False,
    category: Optional[list[str]] = None,
    requires: Optional[list[str]] = None,
    purposes: Optional[list[str]] = None,
    keyword: Optional[str] = None,
) -> dict:
    """Return the xdebug action catalog.

    Call this before xverif_debug_query when you are unsure which action to use.
    Default returns compact action names. Set verbose=true for descriptors,
    schemas, examples, required args, and usage guidance. Optional category,
    requires, purposes, and keyword filters are combined with AND semantics;
    values within an array are combined with OR semantics.
    """
    return debug.actions(verbose=verbose, category=category, requires=requires,
                         purposes=purposes, keyword=keyword)


@xverif_tool("debug")
def xverif_debug_get_schema(
    action: str,
    kind: Literal["request", "response"] = "request",
    view: Literal["mcp", "response"] = "mcp",
    include_examples: bool = True,
) -> dict:
    """Return a self-explanatory action-specific xdebug schema.

    Request projections include skill_guidance. Read the referenced $xverif
    workflow before constructing a call, especially for APB/AXI/stream query
    routing.

    Args:
        action: The xdebug action name (e.g. "value.at", "trace.driver").
        kind: "request" for input schema, "response" for output schema.
        view: "mcp" (default) or "response".
        include_examples: Include invalid MCP call examples.
    """
    if kind not in ("request", "response"):
        return _tool_error("INVALID_ARGUMENT", "kind must be 'request' or 'response'")
    if view not in ("mcp", "response"):
        return _tool_error("INVALID_ARGUMENT", "view must be 'mcp' or 'response'")
    if view == "response" and kind != "response":
        return _tool_error("INVALID_ARGUMENT", "view='response' requires kind='response'")
    if kind == "response" and view != "response":
        return _tool_error("INVALID_ARGUMENT", "response kind requires view='response'")
    return debug.schema(action, kind, view=view, include_examples=include_examples)


@xverif_tool("debug")
def xverif_debug_session_open(
    name: str,
    daidir: Optional[str] = None,
    fsdb: Optional[str] = None,
    run_manifest: Optional[str] = None,
    queue: Optional[str] = None,
    resource: Optional[str] = None,
) -> dict:
    """Open a loop-backed xdebug session, optionally verifying a published run manifest."""
    return debug.session_open(
        name=name, daidir=daidir, fsdb=fsdb, run_manifest=run_manifest, queue=queue,
        resource=resource,
    )


@xverif_tool("debug")
def xverif_debug_session_list(
    include_tombstones: bool = False,
    verbose: bool = False,
) -> dict:
    """List xdebug sessions managed by this server."""
    return debug.session_list(include_tombstones=include_tombstones, verbose=verbose)


@xverif_tool("debug")
def xverif_debug_session_doctor(
    session_id: str,
    verbose: bool = False,
) -> dict:
    """Read-only health diagnosis for one managed xdebug session."""
    return debug.session_doctor(session_id, verbose=verbose)


@xverif_tool("debug")
def xverif_debug_session_close(
    session_id: str,
) -> dict:
    """Close and cleanup an xdebug session."""
    return debug.session_close(session_id)


@xverif_tool("debug")
def xverif_debug_session_kill(
    session_id: str,
) -> dict:
    """Force cleanup of exactly one managed xdebug session."""
    if session_id == "all":
        return _tool_error("INVALID_ARGUMENT", "provide one exact session_id; all is not supported")
    return debug.session_kill(session_id)


@xverif_tool("debug")
def xverif_debug_session_gc(verbose: bool = False) -> dict:
    """Remove confirmed terminal xdebug tombstones; report unresolved sessions."""
    return debug.session_gc(verbose=verbose)


def _forbidden_batch_lifecycle_action(args: dict) -> tuple[str, str] | None:
    """Find the first forbidden native session action in a nested batch."""
    requests = args.get("requests")
    if not isinstance(requests, list):
        return None

    pending: list[tuple[Any, str]] = [
        (child, f"args.requests[{index}]")
        for index, child in reversed(list(enumerate(requests)))
    ]
    while pending:
        child, path = pending.pop()
        if not isinstance(child, dict):
            continue
        child_action = child.get("action")
        if is_forbidden_native_session_action(child_action):
            return child_action, f"{path}.action"
        if child_action != "batch":
            continue
        child_args = child.get("args")
        child_requests = (
            child_args.get("requests") if isinstance(child_args, dict) else None
        )
        if not isinstance(child_requests, list):
            continue
        pending.extend(
            (nested, f"{path}.args.requests[{index}]")
            for index, nested in reversed(list(enumerate(child_requests)))
        )
    return None


@xverif_tool("debug")
def xverif_debug_query(
    action: str,
    session_id: Annotated[
        Optional[str],
        Field(description=(
            "Managed session for resource-backed action variants. "
            "Omit for requires:none variants; requires:none forbids session_id."
        )),
    ] = None,
    args: Optional[dict] = None,
    limits: Optional[dict] = None,
    output_format: Literal["xout", "json", "envelope"] = "xout",
) -> Any:
    """Run an xdebug action through a loop session.

    Recommended workflow:
    1. Call xverif_debug_list_actions if you don't know available actions.
    2. Call xverif_debug_get_schema(action) if you need the exact request shape.
    3. Call xverif_debug_session_open first for resource-backed variants.
    4. Call xverif_debug_query with action + args.

    Args:
        action: The xdebug action name (e.g. "value.at", "trace.driver").
        session_id:
            Exact session identifier for a resource-backed variant.
            Omit it for a requires:none variant; requires:none forbids
            session_id.
        args: Action-specific arguments dict.
        limits:
            Action-specific limits dict. Query the action schema before
            supplying fields; `timeout_ms` is the common deadline field, while
            bounds such as `max_results`, `max_depth`, or `max_rows` exist only
            on the actions that explicitly declare them.
        output_format:
            "xout" (default) — AI-readable structured text.
            "json" — raw xdebug JSON dict.
            "envelope" — wrapper envelope for debugging.
    """
    if output_format not in ("xout", "json", "envelope"):
        return _tool_error("INVALID_ARGUMENT",
                           "output_format must be 'xout', 'json', or 'envelope'")
    if is_forbidden_native_session_action(action):
        return forbidden_native_session_error(action)
    if args is not None and not isinstance(args, dict):
        return _tool_error(
            "INVALID_ARGUMENT", "args must be an object",
            recoverable=True, error_layer="wrapper",
        )
    if action == "batch":
        forbidden_child = _forbidden_batch_lifecycle_action(args or {})
        if forbidden_child is not None:
            child_action, child_path = forbidden_child
            error = forbidden_native_session_error(child_action)
            error["error"]["invalid_arg"] = child_path
            error["error"]["batch_child_path"] = child_path
            return error
    if limits is not None and not isinstance(limits, dict):
        return _tool_error(
            "INVALID_ARGUMENT", "limits must be an object",
            recoverable=True, error_layer="wrapper",
        )
    action_args = args or {}
    try:
        contract, variant = query_session_requirement(action, action_args)
    except XdebugContractError as exc:
        return _tool_error(
            "CONTRACT_UNAVAILABLE", str(exc),
            recoverable=False, error_layer="wrapper",
        )
    if contract is None:
        return _tool_error(
            "UNKNOWN_ACTION", f"unknown xdebug action: {action}",
            recoverable=True, error_layer="wrapper",
        )
    if contract["mode"] == "conditional":
        if variant is None:
            return _tool_error(
                "INVALID_RESOURCE_VARIANT",
                f"{action} arguments do not match exactly one canonical resource variant",
                recoverable=True,
                error_layer="wrapper",
                variants=contract["variants"],
            )
        session_state = variant["session_id"]
        requires = variant["requires"]
        variant_name = variant["name"]
    else:
        session_state = contract["session_id"]
        requires = contract["requires"]
        variant_name = None
    if session_state == "required" and (
        not isinstance(session_id, str) or not session_id.strip()
    ):
        return _tool_error(
            "SESSION_REQUIRED",
            f"{action}" + (f" variant {variant_name}" if variant_name else "")
            + f" requires a managed {requires} session",
            recoverable=True,
            error_layer="wrapper",
            action=action,
            variant=variant_name,
            requires=requires,
        )
    if session_state == "forbidden" and session_id is not None:
        return _tool_error(
            "SESSION_FORBIDDEN",
            f"{action}" + (f" variant {variant_name}" if variant_name else "")
            + " is resource-free and forbids session_id",
            recoverable=True,
            error_layer="wrapper",
            action=action,
            variant=variant_name,
            requires=requires,
        )
    if session_state == "forbidden":
        return debug.query_one_shot(
            action=action,
            args=action_args,
            limits=limits,
            output_format=output_format,
        )
    return debug.query(
        action=action,
        args=action_args,
        session_id=session_id,
        limits=limits,
        output_format=output_format,
    )


# ---------------------------------------------------------------------------
# Coverage tools (xcov — stateful backend)
# ---------------------------------------------------------------------------


@xverif_tool("cov")
def xverif_cov_list_actions() -> dict:
    """Return the xcov action catalog."""
    return cov.actions()


@xverif_tool("cov")
def xverif_cov_get_schema(
    action: str,
    kind: Literal["request", "response"] = "request",
) -> dict:
    """Return an xcov action schema."""
    if kind not in ("request", "response"):
        return _tool_error("INVALID_ARGUMENT", "kind must be 'request' or 'response'")
    return cov.schema(action, kind)


@xverif_tool("cov")
def xverif_cov_session_open(
    name: str,
    vdb: str,
    run_manifest: Optional[str] = None,
    queue: Optional[str] = None,
    resource: Optional[str] = None,
) -> dict:
    """Open a loop-backed xcov session, optionally verifying a published run manifest."""
    return cov.session_open(
        name=name, vdb=vdb, run_manifest=run_manifest, queue=queue, resource=resource,
    )


@xverif_tool("cov")
def xverif_cov_session_list(
    include_tombstones: bool = False,
    verbose: bool = False,
) -> dict:
    """List xcov sessions managed by this server."""
    return cov.session_list(include_tombstones=include_tombstones, verbose=verbose)


@xverif_tool("cov")
def xverif_cov_session_doctor(
    session_id: str,
    verbose: bool = False,
) -> dict:
    """Read-only health diagnosis for one managed xcov session."""
    return cov.session_doctor(session_id, verbose=verbose)


@xverif_tool("cov")
def xverif_cov_session_close(
    session_id: str,
    confirm_discard_reasons: bool = False,
) -> dict:
    """Close xcov; dirty reasons require explicit discard confirmation."""
    return cov.session_close(
        session_id,
        confirm_discard_reasons=confirm_discard_reasons,
    )


@xverif_tool("cov")
def xverif_cov_session_kill(
    session_id: str,
) -> dict:
    """Terminate exactly one managed xcov loop session."""
    if session_id == "all":
        return _tool_error("INVALID_ARGUMENT", "provide one exact session_id; all is not supported")
    return cov.session_kill(session_id)


@xverif_tool("cov")
def xverif_cov_session_gc(verbose: bool = False) -> dict:
    """Remove confirmed terminal xcov tombstones; report unresolved sessions."""
    return cov.session_gc(verbose=verbose)


@xverif_tool("cov")
def xverif_cov_query(
    session_id: str,
    action: str,
    args: Optional[dict] = None,
    output_format: Literal["xout", "json", "envelope"] = "xout",
) -> Any:
    """Run an xcov action through a coverage session.

    Action-specific limits and artifact output belong inside ``args`` exactly
    where the xcov action schema declares them. ``output_format`` controls only
    the MCP result representation.
    """
    if output_format not in ("xout", "json", "envelope"):
        return _tool_error("INVALID_ARGUMENT",
                           "output_format must be 'xout', 'json', or 'envelope'")
    if is_forbidden_native_session_action(action):
        return forbidden_native_session_error(action, backend="cov")
    return cov.query(
        action=action,
        args=args or {},
        session_id=session_id,
        output_format=output_format,
    )


# ---------------------------------------------------------------------------
# Bit tools (xbit - stateless in-process adapter)
# ---------------------------------------------------------------------------


@xverif_tool("bit")
def xverif_bit_convert(
    value: str,
    width: int = 0,
    signed: bool = False,
    unsigned: bool = False,
    state: Literal["2", "4"] = "2",
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Convert a value between radices and SV literal formats.

    Args:
        value: The value to convert (hex, binary, SV literal, etc.).
        width: Resize result to N bits (0 = keep original).
        signed: Treat as signed value.
        unsigned: Treat as unsigned value.
        state: 2 or 4 state encoding (default: 2).
        output_format: "json" or "xout".
    """
    return bit_conv(value, width=width, signed=signed, unsigned=unsigned,
                    state=state, output_format=output_format)


@xverif_tool("bit")
def xverif_bit_eval(expr: str, vars: Optional[dict] = None, width: int = 0,
                     signed: bool = False, unsigned: bool = False,
                     state: Literal["2", "4"] = "2",
                     output_format: Literal["xout", "json"] = "xout") -> Any:
    """Evaluate a deterministic bit/expression calculation.

    Args:
        expr: Expression string (e.g. "0x10 + 0x1", "sig_a & sig_b").
        vars: Dict of variable name to literal value.
        width: Resize result to N bits.
        signed: Treat as signed value.
        unsigned: Treat as unsigned value.
        state: 2 or 4 state encoding (default: 2).
        output_format: "json" or "xout".
    """
    return bit_eval(expr, vars=vars, width=width, signed=signed,
                    unsigned=unsigned, state=state, output_format=output_format)


@xverif_tool("bit")
def xverif_bit_slice(value: str, msb: int, lsb: int,
                     state: Literal["2", "4"] = "2",
                     output_format: Literal["xout", "json"] = "xout") -> Any:
    """Extract a bit slice from a value.

    Args:
        value: The source value.
        msb: Most significant bit index.
        lsb: Least significant bit index.
        state: 2 or 4 state encoding (default: 2).
        output_format: "json" or "xout".
    """
    return bit_slice(value, msb, lsb, state=state, output_format=output_format)


@xverif_tool("bit")
def xverif_bit_check(expr: str, vars: Optional[dict] = None,
                      values: Optional[str] = None,
                      state: Literal["2", "4"] = "2",
                      output_format: Literal["xout", "json"] = "xout") -> Any:
    """Check a bit expression against expected values.

    Args:
        expr: Expression to evaluate.
        vars: Dict of variable name to literal value.
        values: Expected values to check against.
        state: 2 or 4 state encoding (default: 2).
        output_format: "json" or "xout".
    """
    return bit_check(expr, vars=vars, values=values, state=state,
                     output_format=output_format)


# ---------------------------------------------------------------------------
# Entry tools (xentry - stateless in-process adapter)
# ---------------------------------------------------------------------------


@xverif_tool("entry")
def xverif_entry_decode(config_path: Optional[str] = None,
                         input_path: Optional[str] = None,
                         config: Optional[dict] = None,
                         fragments: Optional[list] = None,
                         output_format: Literal["xout", "json"] = "xout") -> Any:
    """Decode multi-beat byte fragments into raw field slices per config.

    Provide either (config_path + input_path) or (config + fragments).

    Args:
        config_path: Path to YAML/JSON entry config file.
        input_path: Path to JSONL fragments input file.
        config: Inline entry config dict (alternative to config_path).
        fragments: Inline fragments list (alternative to input_path).
        output_format: "json" or "xout".
    """
    if not config_path and not config:
        return _tool_error("INVALID_ARGUMENT",
                           "provide config_path or config")
    return entry_decode(config_path=config_path or "",
                         input_path=input_path or "",
                         config=config, fragments=fragments,
                         output_format=output_format)


@xverif_tool("entry")
def xverif_entry_explain(
    config_path: str,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Explain the field layout defined by an entry config.

    Args:
        config_path: Path to YAML/JSON entry config file.
        output_format: "json" or "xout".
    """
    return entry_explain(config_path, output_format=output_format)


@xverif_tool("entry")
def xverif_entry_validate(config_path: Optional[str] = None,
                           input_path: Optional[str] = None,
                           config: Optional[dict] = None,
                           fragments: Optional[list] = None,
                           output_format: Literal["xout", "json"] = "xout") -> Any:
    """Validate an entry config (and optionally an input) without decoding.

    Provide either (config_path + input_path) or (config + fragments).

    Args:
        config_path: Path to YAML/JSON entry config file.
        input_path: Optional path to JSONL fragments for deeper validation.
        config: Inline entry config dict (alternative to config_path).
        fragments: Inline fragments list (alternative to input_path).
        output_format: "json" or "xout".
    """
    if not config_path and not config:
        return _tool_error("INVALID_ARGUMENT",
                           "provide config_path or config")
    return entry_validate(config_path=config_path or "",
                           input_path=input_path,
                           config=config, fragments=fragments,
                           output_format=output_format)


# ---------------------------------------------------------------------------
# Location tools (xloc - stateless in-process adapter)
# ---------------------------------------------------------------------------


@xverif_tool("loc")
def xverif_loc_resolve(
    loc_id: Annotated[str, Field(pattern=r"^L_[0-9A-F]{8}$")],
    map_path: str,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Resolve a compressed loc_id (L_XXXXXXXX) to a source file.

    Args:
        loc_id: The loc_id to resolve (e.g. L_00000001).
        map_path: Path to JSONL sidecar map file.
        output_format: "json" or "xout".
    """
    return loc_resolve(loc_id, map_path, output_format=output_format)


@xverif_tool("loc")
def xverif_loc_context(
    loc_id: Annotated[str, Field(pattern=r"^L_[0-9A-F]{8}$")],
    map_path: str,
    line: Annotated[int, Field(ge=1)],
    before: Annotated[int, Field(ge=0)] = 20,
    after: Annotated[int, Field(ge=0)] = 20,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Resolve a loc_id and show source context at an explicit line.

    Args:
        loc_id: The loc_id to resolve.
        map_path: Path to JSONL sidecar map file.
        line: Positive source line number preserved in the log.
        before: Lines to show before the target line.
        after: Lines to show after the target line.
        output_format: "json" or "xout".
    """
    return loc_context(loc_id, map_path, line, before=before, after=after,
                       output_format=output_format)


@xverif_tool("loc")
def xverif_loc_stats(
    log_path: str,
    map_path: Optional[str] = None,
    top: Annotated[int, Field(ge=1)] = 20,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Count loc_id frequency in a simulation log (hotspot analysis).

    Args:
        log_path: Path to simulation log.
        map_path: Optional path to JSONL sidecar map file for resolution.
        top: Show top N source files (default: 20).
        output_format: "json" or "xout".
    """
    return loc_stats(log_path, map_path=map_path, top=top,
                     output_format=output_format)


@xverif_tool("loc")
def xverif_loc_annotate(
    log_path: str,
    map_path: Optional[str] = None,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Insert source location hints into a simulation log.

    Args:
        log_path: Path to simulation log.
        map_path: Optional path to JSONL sidecar map file.
        output_format: "xout" (annotated text).
    """
    return loc_annotate(log_path, map_path=map_path,
                        output_format=output_format)


# ---------------------------------------------------------------------------
# SVA tools (xsva - stateless in-process adapter)
# ---------------------------------------------------------------------------


@xverif_tool("sva")
def xverif_sva_list_properties(
    file: str,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """List all property/assertion names in a SVA source file.

    Args:
        file: Path to SVA source file (.sv/.sva/.v).
    """
    return sva_list(file, output_format=output_format)


@xverif_tool("sva")
def xverif_sva_scan_constructs(
    file: str,
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Scan syntax constructs used in a SVA source file.

    Args:
        file: Path to SVA source file.
    """
    return sva_scan(file, output_format=output_format)


@xverif_tool("sva")
def xverif_sva_parse_property(
    file: str,
    property: str,
    emit: Literal["surface-ir", "sequence-ir", "timeline-ir"] = "timeline-ir",
    output_format: Literal["xout", "json"] = "xout",
) -> Any:
    """Parse a SVA property into IR.

    Args:
        file: Path to SVA source file.
        property: Property/assertion name.
        emit: IR level — "surface-ir", "sequence-ir", or "timeline-ir".
    """
    return sva_parse(file, property, emit=emit, output_format=output_format)


@xverif_tool("sva")
def xverif_sva_explain_property(file: str, property: str, strict: bool = False,
                        output_format: Literal[
                            "xout", "json", "markdown"
                        ] = "xout") -> Any:
    """Generate a human-readable explanation of a SVA property.

    Args:
        file: Path to SVA source file.
        property: Property/assertion name.
        strict: If True, error on unsupported constructs.
        output_format: "json", "markdown", or "xout".
    """
    return sva_explain(file, property, strict=strict, output_format=output_format)


# ---------------------------------------------------------------------------
# Tool catalog (meta-tools for AI discovery)
# ---------------------------------------------------------------------------

TOOL_CATALOG = [
    {"name": "xverif_ping", "category": "common", "backend": "builtin",
     "stateful": False, "requires_session": False,
     "description": "Ping the xverif MCP server."},
    {"name": "xverif_tools", "category": "common", "backend": "builtin",
     "stateful": False, "requires_session": False,
     "description": "Return the complete xdebug action guide with every action's status, purpose, and use cases."},
    {"name": "xverif_tool_help", "category": "common", "backend": "builtin",
     "stateful": False, "requires_session": False,
     "description": "Get help for a specific tool."},
    {"name": "xverif_batch", "category": "common", "backend": "builtin",
     "stateful": False, "requires_session": False,
     "description": "Execute MCP tools from NDJSON batch file serially. "
                    "Line: {\"tool\":\"<name>\",\"args\":{<params>}}. "
                    "Nested args for debug_query/cov_query: "
                    "{\"tool\":\"xverif_debug_query\",\"args\":"
                    "{\"session_id\":\"case_a\",\"action\":\"value.at\","
                    "\"args\":{\"signal\":\"top.clk\",\"time\":\"10ns\",\"clock\":\"top.clk\"}}}"},
    # debug
    {"name": "xverif_debug_list_actions", "category": "debug", "backend": "xdebug",
     "stateful": False, "requires_session": False,
     "description": "Return the xdebug action catalog."},
    {"name": "xverif_debug_get_schema", "category": "debug", "backend": "xdebug",
     "stateful": False, "requires_session": False,
     "description": "Return an action-specific xdebug JSON schema."},
    {"name": "xverif_debug_session_open", "category": "debug", "backend": "xdebug",
     "stateful": True, "requires_session": True,
     "description": "Open a loop-backed xdebug session, optionally verifying a published run manifest."},
    {"name": "xverif_debug_session_list", "category": "debug", "backend": "xdebug",
     "stateful": True, "requires_session": False,
     "description": "List xdebug sessions managed by this server."},
    {"name": "xverif_debug_session_doctor", "category": "debug", "backend": "xdebug",
     "stateful": True, "requires_session": True,
     "description": "Read-only diagnosis for one managed xdebug session."},
    {"name": "xverif_debug_session_close", "category": "debug", "backend": "xdebug",
     "stateful": True, "requires_session": True,
     "description": "Close and cleanup an xdebug session."},
    {"name": "xverif_debug_session_kill", "category": "debug", "backend": "xdebug",
     "stateful": True, "requires_session": True,
     "description": "Force cleanup of exactly one managed xdebug session."},
    {"name": "xverif_debug_session_gc", "category": "debug", "backend": "xdebug",
     "stateful": True, "requires_session": False,
     "description": "Remove confirmed terminal xdebug tombstones."},
    {"name": "xverif_debug_query", "category": "debug", "backend": "xdebug",
     "stateful": True, "session_requirement": "conditional",
     "description": "Run an xdebug action using its canonical resource variant; "
                    "resource variants require session_id and requires:none variants forbid it."},
    # coverage
    {"name": "xverif_cov_list_actions", "category": "cov", "backend": "xcov",
     "stateful": False, "requires_session": False,
     "description": "Return the xcov action catalog."},
    {"name": "xverif_cov_get_schema", "category": "cov", "backend": "xcov",
     "stateful": False, "requires_session": False,
     "description": "Return an xcov action schema."},
    {"name": "xverif_cov_session_open", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": True,
     "description": "Open a loop-backed xcov session, optionally verifying a published run manifest."},
    {"name": "xverif_cov_session_list", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": False,
     "description": "List xcov sessions managed by this server."},
    {"name": "xverif_cov_session_doctor", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": True,
     "description": "Read-only diagnosis for one managed xcov session."},
    {"name": "xverif_cov_session_close", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": True,
     "description": "Close and cleanup an xcov session."},
    {"name": "xverif_cov_session_kill", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": True,
     "description": "Terminate exactly one managed xcov loop session."},
    {"name": "xverif_cov_session_gc", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": False,
     "description": "Remove confirmed terminal xcov tombstones."},
    {"name": "xverif_cov_query", "category": "cov", "backend": "xcov",
     "stateful": True, "requires_session": True,
     "description": "Run an xcov action through a coverage session; limits and "
                    "artifact output belong inside action-specific args."},
    # bit
    {"name": "xverif_bit_convert", "category": "bit", "backend": "xbit",
     "stateful": False, "requires_session": False,
     "description": "Convert a value between radices and SV literal formats."},
    {"name": "xverif_bit_eval", "category": "bit", "backend": "xbit",
     "stateful": False, "requires_session": False,
     "description": "Evaluate a deterministic bit/expression calculation."},
    {"name": "xverif_bit_slice", "category": "bit", "backend": "xbit",
     "stateful": False, "requires_session": False,
     "description": "Extract a bit slice from a value."},
    {"name": "xverif_bit_check", "category": "bit", "backend": "xbit",
     "stateful": False, "requires_session": False,
     "description": "Check a bit expression against expected values."},
    # entry
    {"name": "xverif_entry_decode", "category": "entry", "backend": "xentry",
     "stateful": False, "requires_session": False,
     "description": "Decode multi-beat fragments into raw field slices."},
    {"name": "xverif_entry_explain", "category": "entry", "backend": "xentry",
     "stateful": False, "requires_session": False,
     "description": "Explain field layout defined by an entry config."},
    {"name": "xverif_entry_validate", "category": "entry", "backend": "xentry",
     "stateful": False, "requires_session": False,
     "description": "Validate an entry config and optionally its input."},
    # loc
    {"name": "xverif_loc_resolve", "category": "loc", "backend": "xloc",
     "stateful": False, "requires_session": False,
     "description": "Resolve a loc_id to its source file."},
    {"name": "xverif_loc_context", "category": "loc", "backend": "xloc",
     "stateful": False, "requires_session": False,
     "description": "Resolve a loc_id and show source context at an explicit line."},
    {"name": "xverif_loc_stats", "category": "loc", "backend": "xloc",
     "stateful": False, "requires_session": False,
     "description": "Count loc_id frequency in a simulation log."},
    {"name": "xverif_loc_annotate", "category": "loc", "backend": "xloc",
     "stateful": False, "requires_session": False,
     "description": "Insert source location hints into a simulation log."},
    # sva
    {"name": "xverif_sva_list_properties", "category": "sva", "backend": "xsva",
     "stateful": False, "requires_session": False,
     "description": "List all property/assertion names in a SVA file."},
    {"name": "xverif_sva_scan_constructs", "category": "sva", "backend": "xsva",
     "stateful": False, "requires_session": False,
     "description": "Scan syntax constructs in a SVA file."},
    {"name": "xverif_sva_parse_property", "category": "sva", "backend": "xsva",
     "stateful": False, "requires_session": False,
     "description": "Parse a SVA property into IR."},
    {"name": "xverif_sva_explain_property", "category": "sva", "backend": "xsva",
     "stateful": False, "requires_session": False,
     "description": "Generate a human-readable SVA property explanation."},
]

for _tool in TOOL_CATALOG:
    _tool.setdefault("group", _tool["category"])
    _tool.setdefault("write", False)


def _xdebug_action_guide(payload: Any) -> str:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError(
            "xverif_tools could not load the canonical xdebug action catalog"
        )
    data = payload.get("data")
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list) or not actions:
        raise RuntimeError(
            "xverif_tools received a malformed xdebug action catalog"
        )
    lines = [
        (
            f"xdebug actions ({len(actions)} total). "
            "Read this complete list before selecting an action, then call "
            "xverif_debug_get_schema(action) for the exact request contract."
        )
    ]
    names: set[str] = set()
    for index, entry in enumerate(actions):
        if not isinstance(entry, dict):
            raise RuntimeError(f"xverif_tools action entry {index} is not an object")
        name = entry.get("name")
        status = entry.get("status")
        description = entry.get("description_en")
        use_when = entry.get("use_when")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or status not in {"stable", "experimental"}
            or not isinstance(description, str)
            or not description
            or not isinstance(use_when, list)
            or not use_when
            or not all(isinstance(item, str) and item for item in use_when)
        ):
            raise RuntimeError(
                f"xverif_tools action entry {index} violates the guide contract"
            )
        names.add(name)
        lines.append(
            f"{name} [{status}] — {description} Use when: {'; '.join(use_when)}"
        )
    return "\n".join(lines)


@xverif_tool("common")
def xverif_tools() -> str:
    """Return the complete xdebug action guide.

    Call this once before choosing any xdebug action. The result contains every
    runtime action name, stable/experimental status, purpose, and all declared
    use cases. Then call xverif_debug_get_schema(action) for exact arguments.
    """
    return _xdebug_action_guide(debug.actions(verbose=True))


@xverif_tool("common")
def xverif_tool_help(name: str) -> dict:
    """Get detailed help for a specific xverif tool.

    Args:
        name: Exact tool name (e.g. "xverif_debug_query").
    """
    for t in filtered_catalog(MCP_TOOL_POLICY, TOOL_CATALOG, include_write=True):
        if t["name"] == name:
            return {"ok": True, "tool": t, "policy": MCP_TOOL_POLICY.summary()}
    for t in TOOL_CATALOG:
        if t["name"] == name:
            return _tool_error("TOOL_NOT_ENABLED", f"tool is disabled by MCP policy: {name}")
    return _tool_error("TOOL_NOT_FOUND", f"tool not found: {name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the MCP stdio server and release all stateful sessions on exit."""
    try:
        mcp.run()
    finally:
        _cleanup_stateful_sessions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
