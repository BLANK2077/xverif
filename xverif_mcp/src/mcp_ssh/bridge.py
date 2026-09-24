"""SSH bridge: expose a remote xverif MCP server over local stdio.

The program is an MCP server on its front (stdio, official SDK) and an MCP client
on its back (``ssh`` started through the SDK's stdio client). It forwards the tool
surface verbatim: tool schemas and results are relayed untouched, because
interpreting xdebug/xcov semantics is the remote server's job.

One client connection owns one upstream process. That is deliberate: the remote
xcov backend owns at most one live native session per MCP process and expects a
new process for a new session, so sharing one upstream between connections would
silently break that contract.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import tempfile

import anyio
from anyio.streams.memory import ObjectReceiveStream, ObjectSendStream

from mcp import ClientSession, McpError, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from .config import (
    BridgeConfig,
    ConfigError,
    build_env_frame,
    build_ssh_argv,
    load_config,
    with_remote_root,
)

SERVER_NAME = "xverif-mcp-ssh"
SERVER_VERSION = "1.0.0"


def _stderr(message: str) -> None:
    print(f"{SERVER_NAME}: {message}", file=sys.stderr, flush=True)


def _read_tail(handle, limit: int = 2000) -> str:
    """The tail of a child's stderr, for reporting why a remote command failed."""
    if handle is None:
        return ""
    try:
        handle.flush()
        handle.seek(0)
        text = handle.read().decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        return ""
    return text[-limit:]


class BridgeError(RuntimeError):
    """The upstream side could not be reached or stopped being usable.

    Raised from a request handler it becomes a JSON-RPC error response, which is the honest
    answer for a request that could not be served at all - as opposed to a tool result that
    reports why the tool failed.
    """


class _Upstream:
    """Owns the ssh child process and the MCP session against the remote server.

    The connection is opened on first use rather than at start-up, so a failure is reported
    to the client through the MCP error path instead of ending the process while the client
    is still waiting for an answer. Exactly one connection exists per bridge connection: the
    remote xcov backend owns at most one live native session per MCP process and expects a
    new process for a new session, so sharing an upstream between connections would silently
    break that contract.

    The child is owned by a dedicated task (``_serve``) rather than by whichever request
    handler happens to ask for it first. anyio cancel scopes have to be entered and exited
    in the same task, and request handlers are not; entering the transport in a handler and
    closing it when the connection ends is what produces "Attempted to exit cancel scope in
    a different task than it was entered in".
    """

    def __init__(self, cfg: BridgeConfig) -> None:
        self._cfg = cfg
        self._requests: ObjectSendStream[None] | None = None
        self._ready = anyio.Event()
        self._session: ClientSession | None = None
        self._error: BaseException | None = None
        self._remote_stderr = ""
        self._task_group: anyio.abc.TaskGroup | None = None

    async def open(self) -> None:
        """Start the owning task; it must be closed with :meth:`aclose`."""
        self._requests, request_reader = anyio.create_memory_object_stream[None](1)
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._serve, request_reader)

    async def _serve(self, requests: ObjectReceiveStream[None]) -> None:
        async with requests:
            remote_err = None
            try:
                frame_raw, frame_b64 = build_env_frame(
                    dict(os.environ), self._cfg.env_deny, self._cfg.remote_root
                )
                del frame_raw  # only the remote side needs the raw frame bytes
                argv = build_ssh_argv(with_remote_root(self._cfg, self._cfg.remote_root), frame_b64)
                params = StdioServerParameters(command=argv[0], args=argv[1:], env=dict(os.environ))
                remote_err = tempfile.TemporaryFile()
                async with stdio_client(params, errlog=remote_err) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        self._session = session
                        self._ready.set()
                        # Hold the connection open until the bridge connection ends.
                        async for _ in requests:
                            pass
            except BaseException as exc:  # noqa: BLE001 - handed to the waiting request
                self._error = exc
                self._remote_stderr = _read_tail(remote_err) if remote_err is not None else ""
                self._ready.set()

    async def session(self) -> ClientSession:
        """The live upstream session, or the reason it could not be established."""
        if self._session is not None:
            return self._session
        if self._requests is None:
            raise BridgeError("the upstream task was never started")
        with contextlib.suppress(anyio.ClosedResourceError, anyio.WouldBlock):
            await self._requests.send(None)
        await self._ready.wait()
        if self._session is None:
            detail = f": {self._remote_stderr}" if self._remote_stderr else ""
            raise BridgeError(
                f"cannot reach the remote xverif MCP server over ssh: {self._error}{detail}"
            )
        return self._session

    async def aclose(self) -> None:
        """Ask the owning task to finish and wait for the child to be reaped."""
        if self._requests is not None:
            with contextlib.suppress(anyio.ClosedResourceError):
                await self._requests.aclose()
        task_group, self._task_group = self._task_group, None
        self._session = None
        if task_group is not None:
            await task_group.__aexit__(None, None, None)


def _build_server(upstream: _Upstream) -> Server:
    """Build the local stdio server whose tools mirror the upstream server."""
    server: Server = Server(SERVER_NAME, version=SERVER_VERSION)

    @server.list_tools()
    async def _list_tools(_req: types.ListToolsRequest) -> list[types.Tool]:
        try:
            session = await upstream.session()
            result = await session.list_tools()
        except Exception as exc:  # noqa: BLE001 - reported to the client as a failure
            # tools/list has no per-item failure channel, so this must be an error response.
            raise McpError(
                types.ErrorData(
                    code=types.INTERNAL_ERROR,
                    message=f"upstream tools/list failed: {exc}",
                )
            ) from exc
        # Relay the remote definitions untouched, including inputSchema/outputSchema.
        return list(result.tools)

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict) -> types.CallToolResult:
        # The SDK calls this handler as (name, arguments); validation stays off because the
        # remote server's own schema is the authority and it is relayed untouched.
        try:
            session = await upstream.session()
            return await session.call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001 - reported to the client as a failure
            raise BridgeError(f"upstream tools/call {name!r} failed: {exc}") from exc

    return server


async def serve_connection(cfg: BridgeConfig, read, write) -> None:
    """Serve exactly one client connection with its own upstream process."""
    upstream = _Upstream(cfg)
    await upstream.open()
    try:
        server = _build_server(upstream)
        await server.run(
            read,
            write,
            server.create_initialization_options(),
            raise_exceptions=False,
        )
    finally:
        await upstream.aclose()


async def run_stdio(cfg: BridgeConfig) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await serve_connection(cfg, read_stream, write_stream)


async def check(cfg: BridgeConfig) -> int:
    """Verify configuration and upstream reachability; diagnostics go to stderr only.

    Only environment variable *names* are printed, never values: the frame can carry
    site credentials that a log must not capture.
    """
    from .config import forwarded_names

    environ = dict(os.environ)
    names = forwarded_names(environ, cfg.env_deny)
    _frame, frame_b64 = build_env_frame(environ, cfg.env_deny, cfg.remote_root)
    argv = build_ssh_argv(cfg, frame_b64)
    _stderr(f"host={cfg.host} remote_root={cfg.remote_root} remote_python={cfg.remote_python}")
    _stderr("ssh argv: " + " ".join(argv[: argv.index(cfg.host) + 2]) + " <bootstrap>")
    _stderr(f"forwarded env: {len(names)} variables ({len(frame_b64)} base64 bytes)")
    _stderr("forwarded env names: " + ", ".join(names))
    upstream = _Upstream(cfg)
    await upstream.open()
    try:
        session = await upstream.session()
        tools = await session.list_tools()
        _stderr(f"upstream initialized; {len(tools.tools)} tools exposed")
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic path
        _stderr(f"check failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        await upstream.aclose()
    _stderr("check ok")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="python -m mcp_ssh",
        description=(
            "Expose a remote xverif MCP server over local stdio by running it through ssh. "
            "Configure with XVERIF_MCP_SSH_* environment variables in the MCP client env block."
        ),
    )
    result.add_argument(
        "--check",
        action="store_true",
        help="verify configuration and upstream connectivity, print diagnostics to stderr, then exit",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        cfg = load_config()
    except ConfigError as exc:
        _stderr(str(exc))
        return 2
    try:
        if args.check:
            return asyncio.run(check(cfg))
        asyncio.run(run_stdio(cfg))
        return 0
    except KeyboardInterrupt:
        return 130
    except BridgeError as exc:
        _stderr(str(exc))
        return 1
    except ConfigError as exc:
        _stderr(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
