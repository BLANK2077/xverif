"""Shutdown contract for the MCP stdio server.

An MCP client that terminates the server must not leave the stateful sessions
(or their LSF jobs) behind, and the cleanup must run exactly once.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_ndjson(path: Path) -> list[dict]:
    assert path.exists(), path
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _server_events(log_root: Path) -> list[dict]:
    events: list[dict] = []
    for path in sorted((log_root / "owners").glob("*/logs/server.ndjson")):
        events.extend(_read_ndjson(path))
    return events


def test_cleanup_stateful_sessions_runs_exactly_once(monkeypatch) -> None:
    from xverif_mcp import server

    calls: list[str] = []

    class _Adapter:
        def __init__(self, name: str) -> None:
            self.mode = name

        def close_all(self) -> None:
            calls.append(self.mode)

    monkeypatch.setattr(server, "debug", _Adapter("xdebug"))
    monkeypatch.setattr(server, "cov", _Adapter("xcov"))
    monkeypatch.setattr(server, "_CLEANUP_COMPLETED", False)

    server._cleanup_stateful_sessions()
    server._cleanup_stateful_sessions()

    assert calls == ["xdebug", "xcov"]


def test_cleanup_stateful_sessions_reports_adapter_failure(monkeypatch) -> None:
    from xverif_mcp import server

    events: list[tuple[str, bool]] = []

    class _Broken:
        mode = "xdebug"

        def close_all(self) -> None:
            raise RuntimeError("boom")

    class _Logger:
        def try_server(self, phase, ok=True, **fields):  # type: ignore[no-untyped-def]
            events.append((phase, ok))
            return True

    monkeypatch.setattr(server, "debug", _Broken())
    monkeypatch.setattr(server, "cov", _Broken())
    monkeypatch.setattr(server, "MCP_LOGGER", _Logger())
    monkeypatch.setattr(server, "_CLEANUP_COMPLETED", False)

    server._cleanup_stateful_sessions()

    assert ("mcp.shutdown.cleanup_failed", False) in events


def test_mcp_server_cleans_up_and_exits_on_sigterm(tmp_path) -> None:
    log_root = tmp_path / "mcp-logs"
    env = dict(os.environ)
    env["XVERIF_MCP_LOG_DIR"] = str(log_root)
    env["XVERIF_HOME"] = str(REPO_ROOT)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (
            str(REPO_ROOT / "xverif_mcp" / "src"),
            str(REPO_ROOT),
            os.environ.get("PYTHONPATH", ""),
        ) if p
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from xverif_mcp.server import main; raise SystemExit(main())",
        ],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Wait until the SIGTERM handler is provably installed before signalling.
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if any(
                event.get("phase") == "mcp.shutdown.handlers_installed"
                for event in _server_events(log_root)
            ):
                break
            if proc.poll() is not None:
                pytest.fail(f"server exited early: {proc.communicate()}")
            time.sleep(0.1)
        else:  # pragma: no cover - timeout path
            pytest.fail("server never published its shutdown handler")
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:  # pragma: no cover - defensive
            proc.kill()
            proc.wait(timeout=30)

    assert proc.returncode == 128 + signal.SIGTERM, proc.stderr.read() if proc.stderr else ""
    phases = [event.get("phase") for event in _server_events(log_root)]
    assert "mcp.shutdown.cleanup_end" in phases
    assert "mcp.shutdown.cleanup_timeout" not in phases
