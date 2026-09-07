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
from .errors import bad_json, bad_xout, cli_failed, tool_timeout
from .framing import strict_json_loads, validate_xout_text

Json = Dict[str, Any]


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
            return tool_timeout(tool, effective_timeout)
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
            return tool_timeout(tool, effective_timeout)
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
            return tool_timeout(tool, effective_timeout)
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
        try:
            proc = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._effective_timeout(timeout_sec),
                check=False,
                env=env,
                cwd=cwd or os.getcwd(),
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "", "timed_out": True}
        except OSError as exc:
            return {"exit_code": -1, "stdout": "", "stderr": "", "error_type": type(exc).__name__}
        return {"exit_code": proc.returncode, "stdout": proc.stdout,
                "stderr": proc.stderr}
