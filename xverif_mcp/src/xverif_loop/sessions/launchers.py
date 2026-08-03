"""Launchers for --stdio-loop backend processes (direct and LSF)."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

from xverif_loop.lsf.bsub import BsubOptions, BsubRunner
from xverif_loop.lsf.protocol import JsonlProcess

from xverif_loop.config import RuntimeConfig
from xverif_loop.logging import StructuredLogger, argv_hash

Json = dict[str, Any]


@dataclass
class LaunchConfig:
    alias: str
    xdebug_bin: str
    runtime: RuntimeConfig
    logger: StructuredLogger
    backend: str = "xdebug"
    tool_bin: Optional[str] = None
    queue: Optional[str] = None
    resource: Optional[str] = None
    job_name: Optional[str] = None
    startup_timeout_sec: float = 60.0


class LauncherTerminationError(RuntimeError):
    """Termination failed after all applicable cleanup stages were attempted."""

    def __init__(self, message: str, result: Json) -> None:
        self.result = result
        super().__init__(message)


def _terminate_process(handle: JsonlProcess) -> Json:
    started = time.monotonic()
    try:
        result = handle.terminate()
    except LauncherTerminationError:
        raise
    except Exception as exc:
        structured = {
            "ok": False,
            "stage": "process",
            "error_type": type(exc).__name__,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        raise LauncherTerminationError(
            "loop process termination failed",
            structured,
        ) from exc
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("ok"), bool)
    ):
        raise LauncherTerminationError(
            "loop process termination returned an invalid result",
            {
                "ok": False,
                "stage": "process",
                "error_type": "InvalidTerminationResult",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )
    if not result["ok"]:
        raise LauncherTerminationError(
            "loop process termination was not confirmed",
            result,
        )
    return result


def _run_bkill(*, job_id: str | None = None,
               job_name: str | None = None,
               alias: str | None = None,
               runtime: RuntimeConfig,
               logger: StructuredLogger) -> Json:
    if (job_id is None) == (job_name is None):
        raise ValueError("exactly one of job_id or job_name is required")
    command = shlex.split(runtime.lsf_bkill_command)
    if not command:
        raise LauncherTerminationError(
            "XVERIF_LSF_BKILL resolved to an empty command",
            {"ok": False, "stage": "bkill", "error_type": "EmptyCommand"},
        )
    target_type = "job_id" if job_id is not None else "job_name"
    target = job_id if job_id is not None else job_name
    argv = command + ([str(job_id)] if job_id is not None else ["-J", str(job_name)])
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            timeout=runtime.bkill_timeout_sec,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "stage": "bkill",
            "target_type": target_type,
            "target": target,
            "error_type": type(exc).__name__,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        logger.try_lsf(
            alias,
            f"bkill.by_{target_type}",
            False,
            **{key: value for key, value in result.items() if key != "ok"},
        )
        raise LauncherTerminationError("LSF bkill invocation failed", result) from exc
    result = {
        "ok": completed.returncode == 0,
        "stage": "bkill",
        "target_type": target_type,
        "target": target,
        "returncode": completed.returncode,
        "stdout_present": bool(completed.stdout),
        "stderr_present": bool(completed.stderr),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
    logger.try_lsf(
        alias,
        f"bkill.by_{target_type}",
        result["ok"],
        **{key: value for key, value in result.items() if key != "ok"},
    )
    if not result["ok"]:
        raise LauncherTerminationError(
            f"LSF bkill exited with status {completed.returncode}",
            result,
        )
    return result


def _loop_cmd(cfg: LaunchConfig) -> list[str]:
    cmd = [cfg.tool_bin or cfg.xdebug_bin, "--stdio-loop"]
    if cfg.backend == "xdebug":
        cmd.append("--json")
    return cmd


class Launcher:
    mode: str = "unknown"

    def start(self, cfg: LaunchConfig) -> JsonlProcess:
        raise NotImplementedError

    def terminate(self, handle: JsonlProcess) -> Json:
        return {
            "ok": True,
            "launcher": self.mode,
            "process": _terminate_process(handle),
            "scheduler": {"status": "not_applicable"},
        }


class DirectLauncher(Launcher):
    mode = "direct"

    def start(self, cfg: LaunchConfig) -> JsonlProcess:
        cmd = _loop_cmd(cfg)
        cfg.logger.stdio(cfg.alias, "launcher.direct.start", True,
                         backend=cfg.backend, launcher=self.mode,
                         argv_hash=argv_hash(cmd))
        proc = JsonlProcess.start(
            cmd,
            runtime=cfg.runtime,
            logger=cfg.logger,
            log_context={
                "alias": cfg.alias,
                "backend": cfg.backend,
                "launcher": self.mode,
            },
        )
        proc.job_name = None
        proc.job_id = None
        return proc


class LsfLauncher(Launcher):
    mode = "lsf"

    def __init__(self, bsub: BsubRunner) -> None:
        self.bsub = bsub

    def start(self, cfg: LaunchConfig) -> JsonlProcess:
        cmd = _loop_cmd(cfg)
        cfg.logger.lsf(cfg.alias, "launcher.lsf.start", True,
                       backend=cfg.backend, launcher=self.mode,
                       queue=cfg.queue, resource=cfg.resource,
                       job_name=cfg.job_name, argv_hash=argv_hash(cmd))
        proc = self.bsub.start(
            cmd,
            BsubOptions(
                queue=cfg.queue,
                resource=cfg.resource,
                job_name=cfg.job_name,
            ),
            runtime=cfg.runtime,
            logger=cfg.logger,
            log_context={
                "alias": cfg.alias,
                "backend": cfg.backend,
                "launcher": self.mode,
            },
        )
        return proc

    def terminate(self, handle: JsonlProcess) -> Json:
        result: Json = {
            "ok": True,
            "launcher": self.mode,
            "process": None,
            "scheduler": {"status": "not_attempted"},
        }
        errors: Json = {}
        try:
            result["process"] = _terminate_process(handle)
        except LauncherTerminationError as exc:
            errors["process"] = exc.result
            result["process"] = exc.result
        jid = getattr(handle, "job_id", None)
        jname = getattr(handle, "job_name", None)
        try:
            if jid:
                result["scheduler"] = _run_bkill(
                    job_id=jid,
                    alias=getattr(handle, "log_alias", None),
                    runtime=handle.runtime,
                    logger=handle.logger,
                )
            elif jname:
                result["scheduler"] = _run_bkill(
                    job_name=jname,
                    alias=getattr(handle, "log_alias", None),
                    runtime=handle.runtime,
                    logger=handle.logger,
                )
            else:
                result["scheduler"] = {
                    "ok": False,
                    "status": "job_identity_missing",
                }
                errors["scheduler"] = result["scheduler"]
        except LauncherTerminationError as exc:
            errors["scheduler"] = exc.result
            result["scheduler"] = exc.result
        if errors:
            result["ok"] = False
            result["errors"] = errors
            handle.logger.try_lsf(
                getattr(handle, "log_alias", None),
                "launcher.lsf.terminate",
                False,
                result=result,
            )
            raise LauncherTerminationError(
                "LSF launcher termination was only partially confirmed",
                result,
            )
        handle.logger.try_lsf(
            getattr(handle, "log_alias", None),
            "launcher.lsf.terminate",
            True,
            result=result,
        )
        return result
