"""Stateless CLI runner for non-session tools (xbit, xentry, xloc, xsva)."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Union

from xverif_loop.config import (
    default_tool_path,
    resolve_mcp_cli_timeout,
    validate_positive_timeout,
)
from xverif_loop.lsf.protocol import terminate_process_group
from .errors import bad_json, bad_xout, cli_failed, tool_timeout
from .framing import strict_json_loads, validate_xout_text

Json = Dict[str, Any]


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class StatelessCliRunner:
    def __init__(self, timeout_sec: Optional[float] = None) -> None:
        self.timeout_sec = (
            resolve_mcp_cli_timeout()
            if timeout_sec is None
            else validate_positive_timeout(timeout_sec, source="timeout_sec")
        )

    def _effective_timeout(self, timeout_sec: Optional[float]) -> float:
        return (
            self.timeout_sec
            if timeout_sec is None
            else validate_positive_timeout(timeout_sec, source="timeout_sec")
        )

    def tool_path(self, tool: str) -> str:
        return default_tool_path(tool)

    def run_json(
        self,
        tool: str,
        argv: List[str],
        input_text: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        extra_env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> Json:
        effective_timeout = self._effective_timeout(timeout_sec)
        raw = self._run_raw(tool, argv, input_text, effective_timeout, extra_env,
                            cwd=cwd)
        if raw.get("timed_out"):
            return tool_timeout(
                tool,
                effective_timeout,
                stdout_tail=raw["stdout"],
                stderr_tail=raw["stderr"],
            )
        try:
            payload = strict_json_loads(raw["stdout"])
        except (json.JSONDecodeError, ValueError):
            if raw["exit_code"] != 0:
                return cli_failed(tool, raw["exit_code"], raw["stdout"], raw["stderr"])
            return bad_json(tool, raw["stdout"], raw["stderr"])
        if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
            return bad_json(tool, raw["stdout"], raw["stderr"])
        if raw["exit_code"] != 0 and payload["ok"]:
            return cli_failed(tool, raw["exit_code"], raw["stdout"], raw["stderr"])
        return payload

    def run_text(
        self,
        tool: str,
        argv: List[str],
        input_text: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        extra_env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> Union[str, Json]:
        effective_timeout = self._effective_timeout(timeout_sec)
        raw = self._run_raw(tool, argv, input_text, effective_timeout, extra_env,
                            cwd=cwd)
        if raw.get("timed_out"):
            return tool_timeout(
                tool,
                effective_timeout,
                stdout_tail=raw["stdout"],
                stderr_tail=raw["stderr"],
            )
        if raw["exit_code"] != 0:
            return cli_failed(tool, raw["exit_code"], raw["stdout"],
                              raw["stderr"])
        return raw["stdout"]

    def run_xout(
        self,
        tool: str,
        argv: List[str],
        input_text: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        extra_env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> Union[str, Json]:
        effective_timeout = self._effective_timeout(timeout_sec)
        raw = self._run_raw(tool, argv, input_text, effective_timeout, extra_env, cwd=cwd)
        if raw.get("timed_out"):
            return tool_timeout(
                tool,
                effective_timeout,
                stdout_tail=raw["stdout"],
                stderr_tail=raw["stderr"],
            )
        try:
            expected_action = None
            if tool in {"xdebug", "xcov"} and input_text:
                try:
                    request = strict_json_loads(input_text)
                except (json.JSONDecodeError, ValueError):
                    request = None
                if isinstance(request, dict) and isinstance(request.get("action"), str):
                    expected_action = request["action"]
            validate_xout_text(raw["stdout"], tool=tool, expected_action=expected_action)
        except ValueError:
            if raw["exit_code"] != 0:
                return cli_failed(tool, raw["exit_code"], raw["stdout"], raw["stderr"])
            return bad_xout(tool, raw["stdout"], raw["stderr"])
        if raw["exit_code"] != 0:
            return cli_failed(tool, raw["exit_code"], raw["stdout"], raw["stderr"])
        return raw["stdout"]

    def _run_raw(
        self,
        tool: str,
        argv: List[str],
        input_text: Optional[str] = None,
        timeout_sec: Optional[float] = None,
        extra_env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> dict:
        cmd = [self.tool_path(tool)] + argv
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        effective_timeout = self._effective_timeout(timeout_sec)
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=cwd or os.getcwd(),
                # Isolate the process group so a timed-out tool cannot leave
                # grandchildren behind.
                start_new_session=True,
            )
        except OSError as exc:
            return {"exit_code": -1, "stdout": "", "stderr": "",
                    "error_type": type(exc).__name__}
        try:
            stdout, stderr = proc.communicate(
                input=input_text,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            cleanup = terminate_process_group(proc)
            stdout, stderr = proc.communicate()
            return {
                "exit_code": -1,
                "stdout": _as_text(stdout) if stdout is not None else _as_text(exc.output),
                "stderr": _as_text(stderr) if stderr is not None else _as_text(exc.stderr),
                "timed_out": True,
                "cleanup": cleanup,
            }
        return {"exit_code": proc.returncode, "stdout": stdout,
                "stderr": stderr}
