from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

from .actions import Dispatcher
from .errors import XcovError, error_response
from .logging import (log_action_event, log_transport_event,
                      request_summary_for_log, response_summary_for_log)
from .limits import MAX_REQUEST_BYTES, enforce_request_budget
from .protocol import json_dumps, parse_request, render_transport_xout, render_xout
from .schemas import validate_response, validate_stdio_request

Json = Dict[str, Any]

_PROTOCOL_OUT = None


def _setup_protocol_stdout() -> None:
    global _PROTOCOL_OUT
    if _PROTOCOL_OUT is not None:
        return
    saved = os.dup(1)
    _PROTOCOL_OUT = os.fdopen(saved, "w", buffering=1, encoding="utf-8")
    os.dup2(2, 1)


def _protocol_write(text: str) -> None:
    out = _PROTOCOL_OUT or sys.stdout
    out.write(text)
    out.flush()


def _emit(rsp: Json, *, json_output: bool) -> None:
    if json_output:
        _protocol_write(json_dumps(rsp) + "\n")
    else:
        _protocol_write(render_xout(rsp))


def run_once(text: str, dispatcher: Dispatcher, *, json_output: bool = False) -> int:
    try:
        enforce_request_budget(text)
        req = parse_request(text)
    except XcovError as exc:
        req = {"request_id": "req-unknown", "action": ""}
        rsp = error_response("", "req-unknown", exc.code, exc.message, **exc.detail)
        validate_response("", rsp)
        log_action_event("public", "adhoc", "", "parse_failed", False, 0,
                         {"error": rsp.get("error")})
        _emit(rsp, json_output=json_output)
        return 1
    rsp = dispatcher.dispatch(req)
    _emit(rsp, json_output=json_output)
    return 0 if rsp.get("ok") else 1


def _bounded_input_lines():
    while True:
        line = sys.stdin.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return
        oversized = len(line.encode("utf-8")) > MAX_REQUEST_BYTES
        if len(line) > MAX_REQUEST_BYTES and not line.endswith("\n"):
            oversized = True
            while line and not line.endswith("\n"):
                line = sys.stdin.readline(MAX_REQUEST_BYTES + 1)
        yield None if oversized else line


def stdio_loop(dispatcher: Dispatcher) -> int:
    ready = {"type": "ready", "protocol": "xcov-stdio-loop", "version": 1,
             "pid": os.getpid()}
    _protocol_write(json.dumps(ready, separators=(",", ":")) + "\n")
    log_transport_event("adhoc", "ready", True, ready)
    for line in _bounded_input_lines():
        if line is None:
            rsp = error_response(
                "", "req-unknown", "REQUEST_BUDGET_EXCEEDED",
                "request exceeds the xcov transport byte budget",
                max_request_bytes=MAX_REQUEST_BYTES,
            )
            validate_response("", rsp)
            envelope = {
                "request_id": "req-unknown", "ok": False,
                "api_version": "xcov.v1", "action": "",
                "payload_format": "xout", "json": rsp,
                "xout": render_transport_xout(rsp),
            }
            _protocol_write(json.dumps(
                envelope, ensure_ascii=False, separators=(",", ":"),
            ) + "\n")
            log_transport_event(
                "adhoc", "request_budget_exceeded", False,
                {"max_request_bytes": MAX_REQUEST_BYTES},
            )
            continue
        line = line.strip()
        if not line:
            continue
        req: Json = {}
        try:
            req = parse_request(line)
            enforce_request_budget(line)
            validate_stdio_request(req)
            rid = req["request_id"]
            sid = _log_session_id(req)
            log_transport_event(sid, "request", True, {"request": request_summary_for_log(req)})
            if req.get("action") == "stdio.quit":
                _protocol_write(json.dumps({
                    "request_id": rid,
                    "ok": True,
                    "api_version": "xcov.v1",
                    "action": "stdio.quit",
                    "payload_format": "json",
                    "json": {
                        "ok": True,
                        "api_version": "xcov.v1",
                        "request_id": rid,
                        "action": "stdio.quit",
                    },
                }, separators=(",", ":")) + "\n")
                log_transport_event(sid, "stdio.quit", True, {"request_id": rid})
                return 0
            rsp = dispatcher.dispatch(req)
        except XcovError as exc:
            raw_request_id = req.get("request_id")
            rid = (
                raw_request_id
                if isinstance(raw_request_id, str) and raw_request_id
                else "req-unknown"
            )
            raw_action = req.get("action")
            action = raw_action if isinstance(raw_action, str) else ""
            req = {"request_id": rid, "action": action}
            rsp = error_response(action, rid, exc.code, exc.message, **exc.detail)
            validate_response(action, rsp)
            log_transport_event("adhoc", "parse_failed", False, {"error": rsp.get("error")})
        xout = render_transport_xout(rsp)
        envelope = {"request_id": req["request_id"],
                    "ok": bool(rsp.get("ok")),
                    "api_version": rsp.get("api_version", "xcov.v1"),
                    "action": rsp.get("action", req.get("action", "")),
                    "payload_format": "xout",
                    "json": rsp,
                    "xout": xout}
        _protocol_write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n")
        log_transport_event(_log_session_id(req), "response", bool(rsp.get("ok")),
                            {"response": response_summary_for_log(rsp)})
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_protocol_stdout()
    parser = argparse.ArgumentParser(prog="xcov")
    parser.add_argument("--stdio-loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--request")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("file", nargs="?")
    ns = parser.parse_args(argv)
    dispatcher = Dispatcher()
    if ns.stdio_loop:
        return stdio_loop(dispatcher)
    if ns.request:
        with open(ns.request, "r", encoding="utf-8") as fh:
            text = fh.read(MAX_REQUEST_BYTES + 1)
    elif ns.file and ns.file != "-":
        with open(ns.file, "r", encoding="utf-8") as fh:
            text = fh.read(MAX_REQUEST_BYTES + 1)
    else:
        text = sys.stdin.read(MAX_REQUEST_BYTES + 1)
    return run_once(text, dispatcher, json_output=bool(ns.json))


def _log_session_id(req: Json) -> str:
    target = req.get("target") if isinstance(req.get("target"), dict) else {}
    args = req.get("args") if isinstance(req.get("args"), dict) else {}
    if target.get("session_id"):
        return str(target["session_id"])
    if req.get("action") == "session.open" and args.get("name"):
        return str(args["name"])
    return "adhoc"


if __name__ == "__main__":
    raise SystemExit(main())
