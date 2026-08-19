"""Native-compatible SDK-free LSF command frontends for xdebug and xcov."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from typing import Any

from xverif_loop.config import (
    default_xcov_bin,
    default_xdebug_bin,
    resolve_loop_wrapper_runtime_config,
)
from xverif_loop.json_contract import strict_json_dumps, strict_json_loads
from xverif_loop.lsf.bsub import BsubOptions, BsubRunner
from xverif_loop.wrapper import (
    LoopWrapperServer,
    LoopWrapperService,
    send_requests,
)


Json = dict[str, Any]


_ENV_MAP = {
    "XVERIF_LSF_CLI_TIMEOUT_SEC": "XVERIF_LOOP_TIMEOUT_SEC",
    "XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC": "XVERIF_LOOP_STARTUP_TIMEOUT_SEC",
    "XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC": "XVERIF_LOOP_REQUEST_TIMEOUT_SEC",
    "XVERIF_LSF_CLI_CLOSE_TIMEOUT_SEC": "XVERIF_LOOP_CLOSE_TIMEOUT_SEC",
    "XVERIF_LSF_CLI_BKILL_TIMEOUT_SEC": "XVERIF_LOOP_BKILL_TIMEOUT_SEC",
    "XVERIF_LSF_CLI_FAKE_LSF": "XVERIF_LOOP_FAKE_LSF",
    "XVERIF_LSF_CLI_LOG_DIR": "XVERIF_LOOP_LOG_DIR",
}


def _configure_lsf_environment() -> None:
    os.environ["XVERIF_LOOP_BACKEND"] = "lsf"
    for public, internal in _ENV_MAP.items():
        if public in os.environ:
            os.environ[internal] = os.environ[public]


def default_socket_path() -> str:
    configured = os.environ.get("XVERIF_LSF_CLI_SOCKET")
    if configured:
        return configured
    root = Path.home() / ".xverif" / "lsf-cli"
    return str(root / f"xverif-lsf-{os.getuid()}.sock")


def _idle_timeout() -> float:
    raw = os.environ.get("XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC", "5")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            "XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC must be a finite positive number"
        ) from exc
    if value <= 0 or value == float("inf") or value != value:
        raise ValueError(
            "XVERIF_LSF_CLI_IDLE_TIMEOUT_SEC must be a finite positive number"
        )
    return value


def manager_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--ready-fd", type=int, required=True)
    ns = parser.parse_args(argv)
    _configure_lsf_environment()
    socket_path = Path(ns.socket)
    parent_existed = socket_path.parent.exists()
    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed:
        os.chmod(socket_path.parent, 0o700)
    server = LoopWrapperServer(
        str(socket_path),
        service=LoopWrapperService(mode="lsf"),
        ready_fd=ns.ready_fd,
        idle_timeout_sec=_idle_timeout(),
    )
    server.serve_forever()
    return 0


def _ping(socket_path: str) -> bool:
    try:
        response = send_requests(
            socket_path,
            [{"id": "ping", "method": "server.ping", "params": {}}],
            timeout_sec=0.5,
        )[0]
    except (OSError, RuntimeError, TimeoutError):
        return False
    result = response.get("result") if isinstance(response, dict) else None
    return bool(
        response.get("ok") is True
        and isinstance(result, dict)
        and result.get("pong") is True
        and result.get("mode") == "lsf"
    )


def _ensure_manager(socket_path: str) -> None:
    if _ping(socket_path):
        return
    read_fd, write_fd = os.pipe()
    command = [
        sys.executable,
        "-m",
        "xverif_loop.native_cli",
        "--manager",
        "--socket",
        socket_path,
        "--ready-fd",
        str(write_fd),
    ]
    log_root = Path(
        os.environ.get(
            "XVERIF_LSF_CLI_LOG_DIR",
            str(Path.home() / ".xverif" / "lsf-cli"),
        )
    )
    log_root.mkdir(parents=True, exist_ok=True)
    with (log_root / "manager.stderr.log").open("ab") as manager_stderr:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=manager_stderr,
            start_new_session=True,
            pass_fds=(write_fd,),
            close_fds=True,
            env=dict(os.environ),
        )
    os.close(write_fd)
    deadline = time.monotonic() + float(
        os.environ.get("XVERIF_LSF_CLI_STARTUP_TIMEOUT_SEC", "180")
    )
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([read_fd], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                break
            message = os.read(read_fd, 64)
            if message == b"READY\n" and _ping(socket_path):
                return
            if not message:
                break
    finally:
        os.close(read_fd)
    if proc.poll() is None:
        proc.terminate()
    raise RuntimeError("LSF CLI manager did not publish listen readiness")


def _read_request(input_arg: str | None) -> Json:
    if input_arg in {None, "-"}:
        text = sys.stdin.read()
    else:
        text = Path(input_arg).read_text(encoding="utf-8")
    request = strict_json_loads(text)
    if not isinstance(request, dict):
        raise ValueError("request must be one JSON object")
    return request


def _native_error(tool: str, action: str, code: str, message: str) -> Json:
    return {
        "api_version": "xdebug.v1" if tool == "xdebug" else "xcov.v1",
        "ok": False,
        "action": action,
        "error": {"code": code, "message": message},
    }


def _emit_transport(tool: str, transport: Json, output_format: str) -> int:
    payload = transport.get("json")
    if output_format == "json":
        if not isinstance(payload, dict):
            payload = _native_error(
                tool, "", "INVALID_BACKEND_RESPONSE", "backend JSON response is missing"
            )
        sys.stdout.write(strict_json_dumps(payload) + "\n")
        return 0 if payload.get("ok") is True else 1
    xout = transport.get("xout")
    if isinstance(xout, str) and xout:
        sys.stdout.write(xout)
        if not xout.endswith("\n"):
            sys.stdout.write("\n")
    elif isinstance(payload, dict):
        sys.stdout.write(strict_json_dumps(payload) + "\n")
    else:
        sys.stdout.write(
            strict_json_dumps(
                _native_error(
                    tool, "", "INVALID_BACKEND_RESPONSE", "backend response is missing"
                )
            )
            + "\n"
        )
    return 0 if transport.get("ok") is True else 1


def _run_native_request(tool: str, request: Json, output_format: str) -> int:
    _configure_lsf_environment()
    socket_path = default_socket_path()
    _ensure_manager(socket_path)
    response = send_requests(
        socket_path,
        [{
            "id": str(request.get("request_id") or "native-request"),
            "method": "native.request",
            "params": {
                "tool": tool,
                "request": request,
                "output_format": output_format,
            },
        }],
        timeout_sec=float(os.environ.get("XVERIF_LSF_CLI_REQUEST_TIMEOUT_SEC", "360")),
    )[0]
    result = response.get("result") if isinstance(response, dict) else None
    transport = result.get("transport") if isinstance(result, dict) else None
    if not isinstance(transport, dict):
        error = response.get("error") if isinstance(response, dict) else None
        payload = _native_error(
            tool,
            str(request.get("action") or ""),
            str(error.get("code") if isinstance(error, dict) else "WRAPPER_FAILED"),
            str(error.get("message") if isinstance(error, dict) else "LSF wrapper failed"),
        )
        return _emit_transport(
            tool,
            {"ok": False, "payload_format": "json", "json": payload},
            output_format,
        )
    return _emit_transport(tool, transport, output_format)


def _print_native_help(tool: str) -> int:
    native = default_xdebug_bin() if tool == "xdebug" else default_xcov_bin()
    return subprocess.run([native, "-h"], check=False).returncode


def _run_lsf_passthrough(tool: str, argv: list[str]) -> int:
    _configure_lsf_environment()
    runtime = resolve_loop_wrapper_runtime_config()
    native = default_xdebug_bin() if tool == "xdebug" else default_xcov_bin()
    command = BsubRunner(runtime.lsf_bsub_command).build(
        [native, *argv],
        BsubOptions(
            queue=runtime.session_queue,
            resource=runtime.session_resource,
            job_name=f"xverif_{tool}_admin_{os.getpid()}",
        ),
    )
    completed = subprocess.run(command, check=False)
    return completed.returncode


def xdebug_main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--stdio-loop" for arg in args):
        print("xdebug_lsf does not expose --stdio-loop; it is an internal LSF protocol", file=sys.stderr)
        return 2
    if len(args) == 1 and args[0] in {"-h", "-help"}:
        return _print_native_help("xdebug")
    if args and args[0] == "log":
        return _run_lsf_passthrough("xdebug", args)
    output_format = "xout"
    input_arg: str | None = None
    for arg in args:
        if arg == "--json":
            output_format = "json"
        elif arg in {"--text", "--xout"}:
            output_format = "xout"
        elif input_arg is None:
            input_arg = arg
        else:
            print("usage: xdebug_lsf [--json|--text] [request.json|-]", file=sys.stderr)
            return 2
    try:
        request = _read_request(input_arg)
        return _run_native_request("xdebug", request, output_format)
    except Exception as exc:
        return _emit_transport(
            "xdebug",
            {"ok": False, "json": _native_error("xdebug", "", "INVALID_REQUEST", str(exc))},
            output_format,
        )


def xcov_main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--stdio-loop" in args:
        print("xcov_lsf does not expose --stdio-loop; it is an internal LSF protocol", file=sys.stderr)
        return 2
    if args == ["-h"] or args == ["--help"]:
        return _print_native_help("xcov")
    output_format = "xout"
    input_arg: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            output_format = "json"
        elif arg == "--once":
            pass
        elif arg == "--request":
            index += 1
            if index >= len(args):
                print("xcov_lsf --request requires a file", file=sys.stderr)
                return 2
            input_arg = args[index]
        elif input_arg is None:
            input_arg = arg
        else:
            print("usage: xcov_lsf [--json] [--request FILE|FILE|-]", file=sys.stderr)
            return 2
        index += 1
    try:
        request = _read_request(input_arg)
        return _run_native_request("xcov", request, output_format)
    except Exception as exc:
        return _emit_transport(
            "xcov",
            {"ok": False, "json": _native_error("xcov", "", "INVALID_REQUEST", str(exc))},
            output_format,
        )


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--manager":
        raise SystemExit(manager_main(sys.argv[2:]))
    raise SystemExit("invoke xdebug_main or xcov_main through the installed entry points")
