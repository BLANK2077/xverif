from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

Json = Dict[str, Any]

MAX_STRING = 4096
MAX_ARRAY = 64
MAX_OBJECT = 128
MAX_DEPTH = 8
MAX_LINE = 256 * 1024

HEAVY_KEYS = {
    "items", "rows", "raw_rows", "data", "xout", "scopes",
    "metrics_by_scope", "source_text", "trace", "all_events",
}

_FAILURE_LOCK = threading.Lock()
_FAILURES: Dict[str, Json] = {}


def enabled() -> bool:
    return str(os.environ.get("XVERIF_XCOV_LOG", "1")).lower() not in {
        "0", "false", "no", "off",
    }


def log_root() -> Path:
    override = os.environ.get("XVERIF_XCOV_LOG_DIR")
    if override:
        return Path(override)
    test_tmp = os.environ.get("XVERIF_TEST_TMPDIR")
    if test_tmp:
        return Path(test_tmp) / ".xverif" / "xcov"
    return Path.home() / ".xverif" / "xcov"


def _safe_session_id(session_id: str | None) -> str:
    raw = session_id or "adhoc"
    out = []
    for ch in raw:
        out.append(ch if ch.isalnum() or ch in "_.-" else "_")
    return "".join(out) or "adhoc"


def public_session_dir(session_id: str | None) -> Path:
    return (
        log_root() / "sessions" / _safe_session_id(session_id) /
        "owners" / str(os.getpid())
    )


def public_action_log_path(session_id: str | None) -> Path:
    return public_session_dir(session_id) / "logs" / "actions.ndjson"


def backend_log_path(session_id: str | None, log_name: str) -> Path:
    return (
        log_root() / "backend" / "sessions" / _safe_session_id(session_id) /
        "owners" / str(os.getpid()) / "logs" / f"{log_name}.ndjson"
    )


def observability_status(session_id: str | None) -> Json:
    key = _safe_session_id(session_id)
    with _FAILURE_LOCK:
        failure = dict(_FAILURES.get(key, {}))
    return {
        "ok": not bool(failure),
        "failure_count": int(failure.get("failure_count", 0)),
        "last_failure_operation": failure.get("operation"),
        "last_failure_type": failure.get("error_type"),
    }


def _record_failure(session_id: str | None, operation: str, exc: BaseException) -> None:
    key = _safe_session_id(session_id)
    with _FAILURE_LOCK:
        previous = _FAILURES.get(key, {})
        _FAILURES[key] = {
            "failure_count": int(previous.get("failure_count", 0)) + 1,
            "operation": operation,
            "error_type": type(exc).__name__,
        }
    try:
        print(
            f"xcov observability failure: operation={operation} "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        # There is no further trustworthy observability sink at this point.
        return


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _event_id() -> str:
    counter = getattr(_event_id, "_counter", 0)
    setattr(_event_id, "_counter", counter + 1)
    return f"{int(time.time() * 1000000):x}-{os.getpid()}-{counter:x}"


def sanitize_for_log(value: Any, depth: int = 0) -> Any:
    truncated = {"value": False}
    out = _sanitize(value, depth, truncated)
    if truncated["value"] and isinstance(out, dict):
        out["log_truncated"] = True
    return out


def _sanitize(value: Any, depth: int, truncated: Json) -> Any:
    if depth > MAX_DEPTH:
        truncated["value"] = True
        return "<truncated:depth>"
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            truncated["value"] = True
            return value[:MAX_STRING] + "...<truncated:string>"
        return value
    if isinstance(value, list):
        out = [_sanitize(item, depth + 1, truncated) for item in value[:MAX_ARRAY]]
        if len(value) > MAX_ARRAY:
            truncated["value"] = True
            out.append("<truncated:array>")
        return out
    if isinstance(value, dict):
        out: Json = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= MAX_OBJECT:
                truncated["value"] = True
                out["<truncated>"] = "object"
                break
            if key in HEAVY_KEYS:
                truncated["value"] = True
                out[key] = "<omitted:large-field>"
            else:
                out[key] = _sanitize(item, depth + 1, truncated)
        return out
    return value


def request_summary_for_log(request: Json) -> Json:
    target = request.get("target") if isinstance(request.get("target"), dict) else {}
    args = request.get("args") if isinstance(request.get("args"), dict) else {}
    out: Json = {
        "request_id": request.get("request_id"),
        "action": request.get("action", ""),
    }
    keys = ("session_id", "name", "vdb")
    out["target"] = sanitize_for_log({k: target[k] for k in keys if k in target})
    out["arg_keys"] = list(args.keys())
    if "name" in args:
        out["name"] = args["name"]
    if "session_id" in args:
        out["arg_session_id"] = args["session_id"]
    if "limits" in request:
        out["limits"] = sanitize_for_log(request["limits"])
    if "output" in request:
        out["output"] = sanitize_for_log(request["output"])
    if "limits" in args:
        out["args_limits"] = sanitize_for_log(args["limits"])
    if "output" in args:
        out["args_output"] = sanitize_for_log(args["output"])
    return out


def response_summary_for_log(response: Json) -> Json:
    out: Json = {
        "ok": response.get("ok", False),
        "action": response.get("action", ""),
        "request_id": response.get("request_id"),
    }
    if "summary" in response:
        out["summary"] = sanitize_for_log(response["summary"])
    if "meta" in response:
        out["meta"] = sanitize_for_log(response["meta"])
    if response.get("error") is not None:
        out["error"] = sanitize_for_log(response.get("error"))
    return out


def update_session_manifest(session_id: str, session: Json) -> None:
    if not enabled():
        return
    try:
        path = public_session_dir(session_id) / "session.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(".session.lock")
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            old: Json = {}
            if path.exists():
                old = json.loads(path.read_text(encoding="utf-8"))
            now = _now_iso8601()
            manifest = {
                "session_id": session_id or "adhoc",
                "vdb": session.get("vdb"),
                "state": session.get("state"),
                "worker": session.get("worker"),
                "test_count": session.get("test_count"),
                "top_scope_count": session.get("top_scope_count"),
                "created_at": old.get("created_at", now),
                "last_log_at": now,
                "log_path": str(public_action_log_path(session_id)),
            }
            descriptor, temporary = tempfile.mkstemp(
                prefix=".session.", suffix=".tmp", dir=str(path.parent),
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                        + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                _fsync_directory(path.parent)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
    except Exception as exc:
        _record_failure(session_id, "session_manifest", exc)


def log_action_event(layer: str, session_id: str | None, action: str, phase: str,
                     ok: bool, elapsed_ms: int = 0, context: Json | None = None) -> None:
    event = _base_event(layer, session_id, action, phase, ok, context or {})
    event["elapsed_ms"] = elapsed_ms
    if layer == "public":
        _append_event(public_action_log_path(session_id), event)
    else:
        _append_event(backend_log_path(session_id, "actions"), event)


def log_lifecycle_event(session_id: str | None, phase: str, ok: bool,
                        context: Json | None = None) -> None:
    _append_event(backend_log_path(session_id, "lifecycle"),
                  _base_event("backend", session_id, "", phase, ok, context or {}))


def log_transport_event(session_id: str | None, phase: str, ok: bool,
                        context: Json | None = None) -> None:
    _append_event(backend_log_path(session_id, "transport"),
                  _base_event("backend", session_id, "", phase, ok, context or {}))


def _base_event(layer: str, session_id: str | None, action: str, phase: str,
                ok: bool, context: Json) -> Json:
    return {
        "ts": _now_iso8601(),
        "event_id": _event_id(),
        "pid": os.getpid(),
        "layer": layer,
        "component": "xcov",
        "session_id": session_id or "adhoc",
        "action": action,
        "phase": phase,
        "ok": ok,
        "context": sanitize_for_log(context),
    }


def _append_event(path: Path, event: Json) -> None:
    if not enabled():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        if len(line) > MAX_LINE:
            event = {
                **event,
                "log_truncated": True,
                "context": {"message": "log event exceeded max line size and was truncated"},
            }
            line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        payload = (line + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("zero-byte NDJSON append")
                offset += written
        finally:
            os.close(descriptor)
    except Exception as exc:
        _record_failure(event.get("session_id"), "ndjson_append", exc)
