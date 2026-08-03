"""xdebug response shaping shared by SDK-free loop clients."""
from __future__ import annotations

from typing import Any, Dict, Optional

Json = Dict[str, Any]
FORBIDDEN_NATIVE_SESSION_ACTIONS = {"session.open", "session.close", "session.kill", "session.gc", "session.doctor", "session.status", "session.list"}


def is_forbidden_native_session_action(action: str | None) -> bool:
    return action in FORBIDDEN_NATIVE_SESSION_ACTIONS


def forbidden_native_session_error(action: str | None, backend: str = "debug") -> Json:
    prefix = "xverif_cov" if backend == "cov" else "xverif_debug"
    if action == "session.open":
        tool, args = f"{prefix}_session_open", ({"name": "cov_a", "vdb": "<merged.vdb>"} if backend == "cov" else {"name": "case_a", "fsdb": "<waves.fsdb>"})
    elif action in {"session.close", "session.kill"}:
        tool, args = f"{prefix}_session_{'kill' if action == 'session.kill' else 'close'}", {"session_id": "cov_a" if backend == "cov" else "case_a"}
    elif action in {"session.doctor", "session.status"}:
        tool, args = f"{prefix}_session_doctor", {"session_id": "cov_a" if backend == "cov" else "case_a"}
    elif action == "session.gc":
        tool, args = f"{prefix}_session_gc", {}
    else:
        tool, args = f"{prefix}_session_list", {}
    return {"ok": False, "error": {"code": "NATIVE_SESSION_ACTION_FORBIDDEN", "message": f"MCP {backend} query does not allow native lifecycle action {action or 'session.*'}; use {prefix}_session_* tools for managed session lifecycle", "recoverable": True, "error_layer": "wrapper", "example_note": f"不要在 {prefix}_query 中调用 native session.* action。", "correct_example": {"tool": tool, "args": args}}}


def translate_native_example_for_query(
    response: Json,
    *,
    session_id: Optional[str],
) -> Json:
    out = dict(response)
    error = out.get("error")
    if not isinstance(error, dict):
        return out
    example = error.get("correct_example")
    if not isinstance(example, dict):
        return out
    args: Json = {
        "action": example.get("action") or out.get("action"),
        "args": (
            example.get("args")
            if isinstance(example.get("args"), dict)
            else {}
        ),
    }
    if session_id is not None:
        args["session_id"] = session_id
    for key in ("limits", "output"):
        if isinstance(example.get(key), dict):
            args[key] = example[key]
    error = dict(error)
    error["correct_example"] = {"tool": "xverif_debug_query", "args": args}
    error["example_note"] = "示例仅说明 xverif_debug_query 的 MCP 参数形态；不要把 api_version/target 写进 MCP args。"
    out["error"] = error
    return out
