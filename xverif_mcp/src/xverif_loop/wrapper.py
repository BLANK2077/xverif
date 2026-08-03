"""SDK-free UDS JSONL wrapper for xverif stateful loop sessions."""

from __future__ import annotations

import argparse
import os
import socket
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from xverif_loop.config import (
    RuntimeConfig,
    default_xcov_bin,
    default_xdebug_bin,
    repo_root,
    resolve_loop_wrapper_runtime_config,
)
from xverif_loop.logging import (
    StructuredLogger,
    StructuredLoggingError,
    resolve_logger,
)
from xverif_loop.json_contract import strict_json_dumps, strict_json_loads
from xverif_loop.sessions.session_manager import McpSessionManager
from xverif_loop.xdebug_errors import (
    forbidden_native_session_error,
    is_forbidden_native_session_action,
)

Json = Dict[str, Any]


METHOD_PARAM_CONTRACTS: dict[str, dict[str, Any]] = {
    "server.ping": {"required": {}, "optional": {}, "any_of": ()},
    "server.shutdown": {"required": {}, "optional": {}, "any_of": ()},
    "debug.session.open": {
        "required": {"name": str},
        "optional": {
            "fsdb": str,
            "daidir": str,
            "run_manifest": str,
            "queue": str,
            "resource": str,
        },
        "any_of": ("fsdb", "daidir"),
    },
    "debug.session.list": {
        "required": {},
        "optional": {"include_tombstones": bool, "verbose": bool},
        "any_of": (),
    },
    "debug.session.doctor": {
        "required": {"session_id": str},
        "optional": {"verbose": bool},
        "any_of": (),
    },
    "debug.session.close": {
        "required": {"session_id": str}, "optional": {}, "any_of": (),
    },
    "debug.session.kill": {
        "required": {"session_id": str}, "optional": {}, "any_of": (),
    },
    "debug.session.gc": {
        "required": {}, "optional": {"verbose": bool}, "any_of": (),
    },
    "debug.query": {
        "required": {"session_id": str, "action": str},
        "optional": {
            "args": dict,
            "limits": dict,
            "output_format": str,
        },
        "any_of": (),
    },
    "cov.session.open": {
        "required": {"name": str, "vdb": str},
        "optional": {
            "run_manifest": str,
            "queue": str,
            "resource": str,
        },
        "any_of": (),
    },
    "cov.session.list": {
        "required": {},
        "optional": {"include_tombstones": bool, "verbose": bool},
        "any_of": (),
    },
    "cov.session.doctor": {
        "required": {"session_id": str},
        "optional": {"verbose": bool},
        "any_of": (),
    },
    "cov.session.close": {
        "required": {"session_id": str}, "optional": {}, "any_of": (),
    },
    "cov.session.kill": {
        "required": {"session_id": str}, "optional": {}, "any_of": (),
    },
    "cov.session.gc": {
        "required": {}, "optional": {"verbose": bool}, "any_of": (),
    },
    "cov.query": {
        "required": {"session_id": str, "action": str},
        "optional": {"args": dict, "output_format": str},
        "any_of": (),
    },
}


def _type_name(expected: type) -> str:
    return {
        bool: "boolean",
        dict: "object",
        str: "non-empty string",
    }[expected]


def validate_request_envelope(request: Any) -> tuple[str, str, Json]:
    if type(request) is not dict:
        raise TypeError("request must be a JSON object")
    required = {"id", "method", "params"}
    unexpected = sorted(set(request) - required)
    if unexpected:
        raise TypeError(
            "unexpected request fields: " + ", ".join(unexpected)
        )
    missing = sorted(required - set(request))
    if missing:
        raise TypeError(
            "missing required request fields: " + ", ".join(missing)
        )
    req_id = request["id"]
    if type(req_id) is not str or not req_id:
        raise TypeError("request.id must be a non-empty string")
    method = request["method"]
    if type(method) is not str or not method:
        raise TypeError("request.method must be a non-empty string")
    params = request["params"]
    if type(params) is not dict:
        raise TypeError("request.params must be an object")
    return req_id, method, params


def validate_method_params(method: str, params: Json) -> None:
    if type(params) is not dict:
        raise TypeError(f"params for {method} must be an object")
    contract = METHOD_PARAM_CONTRACTS.get(method)
    if contract is None:
        return
    required: dict[str, type] = contract["required"]
    optional: dict[str, type] = contract["optional"]
    allowed = set(required) | set(optional)
    unexpected = sorted(set(params) - allowed)
    if unexpected:
        raise TypeError(f"unexpected params for {method}: {', '.join(unexpected)}")
    missing = [key for key in required if key not in params]
    if missing:
        raise TypeError(f"missing required params for {method}: {', '.join(missing)}")
    for key, expected in {**required, **optional}.items():
        if key not in params:
            continue
        value = params[key]
        if type(value) is not expected or (
            expected is str and not value
        ):
            raise TypeError(
                f"param {key} for {method} must be a "
                f"{_type_name(expected)}"
            )
    if (
        "output_format" in params
        and params["output_format"] not in {"json", "xout", "envelope"}
    ):
        raise TypeError(
            f"param output_format for {method} must be one of: "
            "json, xout, envelope"
        )
    any_of = contract["any_of"]
    if any_of and not any(key in params for key in any_of):
        raise TypeError(f"provide one of for {method}: {', '.join(any_of)}")


def default_socket_path() -> str:
    test_tmp = os.environ.get("XVERIF_TEST_TMPDIR")
    default_root = Path(test_tmp) if test_tmp else Path.home() / ".xverif" / "loop-wrapper"
    return os.environ.get(
        "XVERIF_LOOP_SOCKET",
        str(default_root / f"xverif-loop-{os.getuid()}.sock"),
    )


def _error(code: str, message: str, **extra: Any) -> Json:
    err: Json = {"code": code, "message": message}
    err.update(extra)
    return {"ok": False, "error": err}


def _response(req_id: Any, result: Any) -> Json:
    if isinstance(result, dict) and result.get("ok") is False and isinstance(result.get("error"), dict):
        return {"id": req_id, "ok": False, "error": result["error"]}
    return {"id": req_id, "ok": True, "result": result}


def _observability_failure_response(
    req_id: Any,
    *,
    logger: StructuredLogger,
    cursor: int,
    operation_started: bool,
    backend_result: Optional[Json] = None,
) -> Json:
    error: Json = {
        "code": "OBSERVABILITY_FAILURE",
        "message": (
            "request processing completed, but its outcome could not be "
            "fully published"
            if operation_started
            else
            "request processing was not started because its begin event "
            "could not be published"
        ),
        "operation_started": operation_started,
        "observability": logger.observability_status(cursor),
    }
    if backend_result is not None:
        error["backend_result"] = {
            "received": True,
            "ok": backend_result.get("ok") is True,
        }
    return {"id": req_id, "ok": False, "error": error}


class LoopWrapperService:
    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        xdebug_bin: Optional[str] = None,
        xcov_bin: Optional[str] = None,
        startup_timeout_sec: Optional[float] = None,
        request_timeout_sec: Optional[float] = None,
        runtime: RuntimeConfig | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.runtime = (
            runtime or resolve_loop_wrapper_runtime_config()
        ).with_overrides(
            backend=mode,
            startup_timeout_sec=startup_timeout_sec,
            request_timeout_sec=request_timeout_sec,
        )
        self.logger = logger or resolve_logger(self.runtime)
        self.mode = self.runtime.backend
        self.debug = McpSessionManager(
            runtime=self.runtime,
            xdebug_bin=xdebug_bin or default_xdebug_bin(),
            backend="xdebug",
            api_version="xdebug.v1",
            ready_protocol="xdebug-stdio-loop",
            target_key="fsdb",
            recovery_tool="debug.session.open",
            logger=self.logger,
        )
        self.cov = McpSessionManager(
            runtime=self.runtime,
            xdebug_bin=xcov_bin or default_xcov_bin(),
            backend="xcov",
            api_version="xcov.v1",
            ready_protocol="xcov-stdio-loop",
            target_key="vdb",
            recovery_tool="cov.session.open",
            logger=self.logger,
        )
        self.logger.server("wrapper.service.init", True, launcher=self.mode)

    def dispatch(self, request: Any) -> Json:
        req_id = (
            request.get("id")
            if type(request) is dict
            and type(request.get("id")) is str
            else None
        )
        try:
            req_id, method, params = validate_request_envelope(request)
        except TypeError as exc:
            return {"id": req_id, **_error("INVALID_REQUEST", str(exc))}
        try:
            validate_method_params(method, params)
            result = self._dispatch_method(method, params)
        except TypeError as exc:
            return {"id": req_id, **_error("INVALID_PARAMS", str(exc))}
        except Exception as exc:
            return {"id": req_id, **_error("INTERNAL_ERROR", str(exc))}
        return _response(req_id, result)

    def _dispatch_method(self, method: str, params: Json) -> Any:
        if method == "server.ping":
            return {"ok": True, "pong": True, "mode": self.mode}
        if method == "server.shutdown":
            return {"ok": True, "shutdown": True}
        if method == "debug.session.open":
            name = _required_str(params, "name")
            return self.debug.open_session(
                name=name,
                fsdb=params.get("fsdb"),
                daidir=params.get("daidir"),
                run_manifest=params.get("run_manifest"),
                queue=params.get("queue"),
                resource=params.get("resource"),
            )
        if method == "debug.session.list":
            return self.debug.list_sessions(
                include_tombstones=params.get("include_tombstones", False),
                verbose=params.get("verbose", False),
            )
        if method == "debug.session.doctor":
            return self.debug.doctor_session(
                _required_str(params, "session_id"),
                verbose=params.get("verbose", False),
            )
        if method == "debug.session.close":
            return self.debug.close_session(_required_str(params, "session_id"))
        if method == "debug.session.kill":
            session_id = _required_str(params, "session_id")
            if session_id == "all":
                return _error(
                    "INVALID_ARGUMENT",
                    "all is not supported; provide one exact session_id",
                )
            return self.debug.kill_session(session_id)
        if method == "debug.session.gc":
            return self.debug.gc_sessions(
                verbose=params.get("verbose", False)
            )
        if method == "debug.query":
            action = _required_str(params, "action")
            if is_forbidden_native_session_action(action):
                return forbidden_native_session_error(action)
            return self.debug.query(
                session_id=_required_str(params, "session_id"),
                action=action,
                args=params["args"] if "args" in params else {},
                limits=params.get("limits"),
                output_format=params.get("output_format", "xout"),
            )
        if method == "cov.session.open":
            return self.cov.open_session(
                name=_required_str(params, "name"),
                fsdb=_required_str(params, "vdb"),
                run_manifest=params.get("run_manifest"),
                queue=params.get("queue"),
                resource=params.get("resource"),
            )
        if method == "cov.session.list":
            return self.cov.list_sessions(
                include_tombstones=params.get("include_tombstones", False),
                verbose=params.get("verbose", False),
            )
        if method == "cov.session.doctor":
            return self.cov.doctor_session(
                _required_str(params, "session_id"),
                verbose=params.get("verbose", False),
            )
        if method == "cov.session.close":
            return self.cov.close_session(_required_str(params, "session_id"))
        if method == "cov.session.kill":
            session_id = _required_str(params, "session_id")
            if session_id == "all":
                return _error(
                    "INVALID_ARGUMENT",
                    "all is not supported; provide one exact session_id",
                )
            return self.cov.kill_session(session_id)
        if method == "cov.session.gc":
            return self.cov.gc_sessions(
                verbose=params.get("verbose", False)
            )
        if method == "cov.query":
            action = _required_str(params, "action")
            if is_forbidden_native_session_action(action):
                return forbidden_native_session_error(action, backend="cov")
            return self.cov.query(
                session_id=_required_str(params, "session_id"),
                action=action,
                args=params["args"] if "args" in params else {},
                output_format=params.get("output_format", "xout"),
            )
        return _error("UNKNOWN_METHOD", f"unsupported method: {method}")

    def close_all(self) -> None:
        self.debug.close_all()
        self.cov.close_all()


class LoopWrapperServer:
    def __init__(self, socket_path: str, service: Optional[LoopWrapperService] = None) -> None:
        self.socket_path = socket_path
        self.service = service or LoopWrapperService()
        self.logger = self.service.logger
        self._stop = threading.Event()
        self._server_socket: Optional[socket.socket] = None
        self._threads: list[threading.Thread] = []
        self._created_socket = False
        self._ready = threading.Event()
        self._startup_finished = threading.Event()
        self._startup_error: Optional[BaseException] = None

    def wait_until_ready(self, timeout_sec: float) -> None:
        if not self._startup_finished.wait(timeout_sec):
            raise TimeoutError(
                f"loop wrapper server did not finish startup within {timeout_sec} seconds")
        if self._startup_error is not None:
            raise RuntimeError(
                f"loop wrapper server startup failed: {self._startup_error}") from self._startup_error
        if not self._ready.is_set():
            raise RuntimeError("loop wrapper server startup finished without becoming ready")

    def serve_forever(self) -> None:
        path = Path(self.socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise RuntimeError("SOCKET_PATH_UNSAFE")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.2)
                    probe.connect(self.socket_path)
                raise RuntimeError("SOCKET_PATH_UNSAFE")
        except ConnectionRefusedError:
            path.unlink()
        except FileNotFoundError:
            pass
        except Exception as exc:
            self._startup_error = exc
            self._startup_finished.set()
            raise
        try:
            self.logger.uds(
                "uds.listen.begin",
                True,
                socket_path=self.socket_path,
            )
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
                self._server_socket = srv
                srv.bind(self.socket_path)
                self._created_socket = True
                os.chmod(self.socket_path, 0o600)
                srv.listen()
                srv.settimeout(0.2)
                self.logger.uds(
                    "uds.listen.ready",
                    True,
                    socket_path=self.socket_path,
                )
                self._ready.set()
                self._startup_finished.set()
                while not self._stop.is_set():
                    try:
                        conn, _ = srv.accept()
                    except socket.timeout:
                        continue
                    except OSError as exc:
                        if self._stop.is_set():
                            break
                        if self.logger.try_uds(
                            "uds.accept.failed",
                            False,
                            error_type=type(exc).__name__,
                        ):
                            self._stop.set()
                            break
                        continue
                    accept_cursor = self.logger.failure_cursor()
                    accept_failure = self.logger.try_uds(
                        "uds.accept",
                        True,
                    )
                    thread = threading.Thread(
                        target=self._handle_client,
                        args=(
                            conn,
                            accept_cursor
                            if accept_failure is not None
                            else None,
                        ),
                        daemon=True,
                    )
                    self._threads.append(thread)
                    thread.start()
        except Exception as exc:
            if not self._startup_finished.is_set():
                self._startup_error = exc
                self._startup_finished.set()
            raise
        finally:
            self._server_socket = None
            self._shutdown_cleanup()

    def shutdown(self) -> None:
        self._stop.set()
        sock = self._server_socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _handle_client(
        self,
        conn: socket.socket,
        inherited_observability_cursor: Optional[int] = None,
    ) -> None:
        with conn:
            reader = conn.makefile("r", encoding="utf-8")
            writer = conn.makefile("w", encoding="utf-8")
            for raw in reader:
                line = raw.strip()
                if not line:
                    continue
                observability_cursor = (
                    inherited_observability_cursor
                    if inherited_observability_cursor is not None
                    else self.logger.failure_cursor()
                )
                inherited_observability_cursor = None
                t0 = time.monotonic()
                try:
                    request = strict_json_loads(line)
                except Exception as exc:
                    self.logger.try_uds(
                        "uds.request.invalid_json",
                        False,
                        error_type=type(exc).__name__,
                        input_length=len(line),
                    )
                    response = {
                        "id": None,
                        **_error(
                            "INVALID_JSON",
                            "request must be one strict JSON object",
                        ),
                    }
                    if not self.logger.observability_status(
                        observability_cursor
                    )["ok"]:
                        response = _observability_failure_response(
                            None,
                            logger=self.logger,
                            cursor=observability_cursor,
                            operation_started=False,
                        )
                    self._write_response(
                        writer,
                        response,
                    )
                    continue
                req_id = (
                    request.get("id")
                    if type(request) is dict
                    and type(request.get("id")) is str
                    and request.get("id")
                    else None
                )
                method = (
                    request.get("method")
                    if type(request) is dict
                    and type(request.get("method")) is str
                    else None
                )
                try:
                    self.logger.uds(
                        "uds.request.begin",
                        True,
                        request_id=req_id,
                        method=method,
                    )
                except StructuredLoggingError:
                    self._write_response(
                        writer,
                        _observability_failure_response(
                            req_id,
                            logger=self.logger,
                            cursor=observability_cursor,
                            operation_started=False,
                        ),
                    )
                    continue
                rsp = self.service.dispatch(request)
                if (
                    method == "server.shutdown"
                    and rsp.get("ok") is True
                ):
                    self.logger.try_uds(
                        "uds.shutdown.begin",
                        True,
                        request_id=req_id,
                    )
                    self.shutdown()
                    self.logger.try_uds(
                        "uds.shutdown.end",
                        True,
                        request_id=req_id,
                    )
                    self.logger.try_uds(
                        "uds.request.end",
                        True,
                        request_id=req_id,
                        method=method,
                        elapsed_ms=int(
                            (time.monotonic() - t0) * 1000
                        ),
                    )
                    if not self.logger.observability_status(
                        observability_cursor
                    )["ok"]:
                        rsp = _observability_failure_response(
                            req_id,
                            logger=self.logger,
                            cursor=observability_cursor,
                            operation_started=True,
                            backend_result=rsp,
                        )
                    self._write_response(writer, rsp)
                    break
                self.logger.try_uds(
                    "uds.request.end",
                    rsp.get("ok") is True,
                    request_id=req_id,
                    method=method,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
                if not self.logger.observability_status(
                    observability_cursor
                )["ok"]:
                    rsp = _observability_failure_response(
                        req_id,
                        logger=self.logger,
                        cursor=observability_cursor,
                        operation_started=True,
                        backend_result=rsp,
                    )
                self._write_response(writer, rsp)

    def _write_response(self, writer: Any, response: Json) -> None:
        try:
            writer.write(
                strict_json_dumps(
                    response,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            writer.flush()
        except (OSError, TypeError, ValueError) as exc:
            self.logger.try_uds(
                "uds.response.write_failed",
                False,
                error_type=type(exc).__name__,
            )

    def _shutdown_cleanup(self) -> None:
        self.service.close_all()
        if self._created_socket:
            try:
                Path(self.socket_path).unlink()
            except FileNotFoundError:
                pass


def send_requests(socket_path: str, requests: Iterable[Json], timeout_sec: float = 30.0) -> list[Json]:
    responses: list[Json] = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_sec)
        sock.connect(socket_path)
        reader = sock.makefile("r", encoding="utf-8")
        writer = sock.makefile("w", encoding="utf-8")
        for req in requests:
            writer.write(
                strict_json_dumps(
                    req,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            writer.flush()
            line = reader.readline()
            if not line:
                raise RuntimeError("loop wrapper server closed connection")
            response = strict_json_loads(line)
            if not isinstance(response, dict):
                raise RuntimeError(
                    "loop wrapper response must be one strict JSON object"
                )
            responses.append(response)
    return responses


def _required_str(params: Json, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError(f"missing required string param: {key}")
    return value


def server_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the xverif SDK-free loop wrapper server")
    parser.add_argument("--socket", default=default_socket_path())
    parser.add_argument("--backend", choices=("direct", "lsf"), default=None)
    args = parser.parse_args(argv)
    if args.backend:
        os.environ["XVERIF_LOOP_BACKEND"] = args.backend
    server = LoopWrapperServer(args.socket)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


def client_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Send JSONL requests to xverif-loop-server")
    parser.add_argument("--socket", default=default_socket_path())
    parser.add_argument("--json", help="single JSON request object")
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.json:
        requests = [strict_json_loads(args.json)]
    else:
        requests = [
            strict_json_loads(line)
            for line in sys.stdin
            if line.strip()
        ]
    for rsp in send_requests(args.socket, requests, timeout_sec=args.timeout_sec):
        print(
            strict_json_dumps(
                rsp,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(server_main())
