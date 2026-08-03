"""Doctor command for xdebug loop-session integration (direct + LSF)."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import sys
import time
from typing import Dict, List, Optional

from xverif_loop.config import default_xdebug_bin, resolve_mcp_runtime_config
from xverif_loop.lsf.bsub import BsubRunner, parse_lsf_job_id
from xverif_loop.lsf.protocol import JsonlProcess
from xverif_loop.logging import resolve_logger
from xverif_loop.sessions.launchers import DirectLauncher, LaunchConfig, LsfLauncher


def _check_mcp_sdk() -> str:
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
        return "ok"
    except Exception as exc:
        return f"missing: {exc}"


def _check_xdebug_bin() -> str:
    xbin = default_xdebug_bin()
    if os.path.isfile(xbin) and os.access(xbin, os.X_OK):
        return xbin
    # Also try PATH
    found = shutil.which("xdebug")
    return found or f"missing: {xbin}"


def run(fake: bool = False) -> Dict[str, object]:
    started = time.time()
    environment = dict(os.environ)
    if fake:
        environment["XVERIF_MCP_BACKEND"] = "lsf"
        environment["XVERIF_MCP_FAKE_LSF"] = "1"
    runtime = resolve_mcp_runtime_config(environment)
    logger = resolve_logger(runtime)
    mode = runtime.backend
    out: Dict[str, object] = {
        "python_version": sys.version.split()[0],
        "mcp_sdk_import": _check_mcp_sdk(),
        "mode": mode,
        "xdebug_bin": _check_xdebug_bin(),
    }

    try:
        if mode == "lsf":
            launcher = LsfLauncher(BsubRunner(runtime.lsf_bsub_command))
            out["bsub"] = "fake" if runtime.fake_lsf else ("ok" if shutil.which("bsub") else "missing")
        else:
            launcher = DirectLauncher()

        cfg = LaunchConfig(
            alias="doctor",
            xdebug_bin=default_xdebug_bin(),
            runtime=runtime,
            logger=logger,
            queue=runtime.session_queue,
            job_name=f"xverif_doctor_{os.getpid()}" if mode == "lsf" else None,
            startup_timeout_sec=30.0,
        )

        handle = launcher.start(cfg)
        try:
            out["process_started"] = True

            # Wait for ready
            ready = handle.wait_ready("xdebug-stdio-loop", 30.0)
            out["ready_pid"] = int(ready.get("pid") or 0)

            if mode == "lsf":
                # Collect job_id from stderr/stdout
                time.sleep(0.5)
                for line in list(handle.stderr_tail):
                    jid = parse_lsf_job_id(line)
                    if jid:
                        out["job_id"] = jid
                        break
                out["job_name"] = cfg.job_name

            # Send one request
            rsp = handle.request({
                "request_id": "doctor-actions",
                "api_version": "xdebug.v1",
                "action": "actions",
            }, timeout_sec=30.0)
            out["actions_ok"] = rsp.get("ok", False)

            # Quit
            rsp2 = handle.request({
                "request_id": "doctor-quit",
                "api_version": "xdebug.v1",
                "action": "stdio.quit",
            }, timeout_sec=10.0)
            out["quit_ok"] = rsp2.get("ok", False)
            stderr_text = "\n".join(list(handle.stderr_tail)[-5:])
            out["stderr_evidence"] = {
                "line_count": len(stderr_text.splitlines()),
                "sha256": hashlib.sha256(stderr_text.encode("utf-8", errors="replace")).hexdigest(),
            }
        finally:
            launcher.terminate(handle)

    except Exception as exc:
        out["error"] = {"code": "DOCTOR_FAILED", "error_type": type(exc).__name__}

    out["elapsed_ms"] = int((time.time() - started) * 1000)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    fake = "--fake" in (argv or sys.argv[1:])
    result = run(fake=fake)
    print("xverif_lsf_doctor:")
    for key, value in result.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        print(f"  {key}: {value}")
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
