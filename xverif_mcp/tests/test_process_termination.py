"""Process-group termination contract for spawned xverif children.

These tests cover the fail-closed termination semantics: a termination that
cannot be confirmed must never be reported as a successful cleanup, and the
whole process group (not only the direct child) must be reclaimed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from xverif_loop.lsf.protocol import (
    signal_process_group,
    terminate_process_group,
)


def _pid_state(pid: int) -> str | None:
    """Return the Linux process state character, or None when it is gone."""

    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return None
    return text.rsplit(") ", 1)[-1].split(" ", 1)[0]


def _wait_until_exited(pid: int, *, deadline_sec: float = 10.0) -> None:
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        state = _pid_state(pid)
        if state is None or state == "Z":
            return
        time.sleep(0.05)
    raise AssertionError(f"pid {pid} is still running (state={_pid_state(pid)})")


def test_terminate_process_group_reports_already_exited() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(0)"],
        start_new_session=True,
    )
    proc.wait(timeout=30)

    result = terminate_process_group(proc)

    assert result["ok"] is True
    assert result["status"] == "already_exited"
    assert result["returncode"] == 0
    assert result["forced"] is False


def test_terminate_process_group_kills_grandchildren(tmp_path) -> None:
    marker = tmp_path / "grandchild.pid"
    script = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n"
        "time.sleep(600)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
    )
    deadline = time.monotonic() + 30.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "grandchild was not spawned in time"
    grandchild_pid = int(marker.read_text(encoding="utf-8"))
    assert _pid_state(grandchild_pid) not in (None, "Z")

    result = terminate_process_group(proc, timeout_sec=10.0)

    assert result["ok"] is True
    assert result["status"] == "terminated"
    _wait_until_exited(grandchild_pid)
    with pytest.raises(ProcessLookupError):
        os.killpg(os.getpgid(proc.pid), 0)


def test_signal_process_group_classifies_delivery(monkeypatch) -> None:
    class _FakeProc:
        pid = 424242

        def __init__(self, *, leader_error: bool = False) -> None:
            self.leader_error = leader_error

        def send_signal(self, signum: int) -> None:
            if self.leader_error:
                raise OSError("no such process")

    def _group_gone(pgid: int, signum: int) -> None:
        raise ProcessLookupError("group gone")

    monkeypatch.setattr(os, "killpg", _group_gone)
    assert signal_process_group(_FakeProc(), 15) == "group_gone"

    def _group_denied(pgid: int, signum: int) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "killpg", _group_denied)
    assert signal_process_group(_FakeProc(), 15) == "leader_only"
    assert signal_process_group(_FakeProc(leader_error=True), 15) == "failed"


def test_terminate_process_group_is_fail_closed(monkeypatch) -> None:
    class _StuckProc:
        pid = 424243
        returncode = None

        def poll(self):  # type: ignore[no-untyped-def]
            return None

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            raise subprocess.TimeoutExpired(cmd="stuck", timeout=timeout)

        def send_signal(self, signum: int) -> None:  # pragma: no cover
            return None

    monkeypatch.setattr(os, "killpg", lambda pgid, signum: None)

    result = terminate_process_group(_StuckProc(), timeout_sec=0.05)

    assert result["ok"] is False
    assert result["status"] == "unconfirmed"
    assert result["error_type"] == "TerminationTimeout"
    assert result["forced"] is True


def test_jsonl_process_caches_process_group() -> None:
    from xverif_loop.config import resolve_loop_wrapper_runtime_config
    from xverif_loop.logging import resolve_logger
    from xverif_loop.lsf.protocol import JsonlProcess

    runtime = resolve_loop_wrapper_runtime_config()
    logger = resolve_logger(runtime)
    handle = JsonlProcess.start(
        [sys.executable, "-c", "import time; time.sleep(600)"],
        runtime=runtime,
        logger=logger,
    )
    try:
        assert handle.pgid == handle.proc.pid
        result = handle.terminate(timeout_sec=10.0)
        assert result["ok"] is True
        assert result["status"] == "terminated"
        assert result["signal_delivery"] in {"signaled", "group_gone"}
    finally:
        if handle.proc.poll() is None:  # pragma: no cover - defensive
            handle.proc.kill()
            handle.proc.wait(timeout=10)
