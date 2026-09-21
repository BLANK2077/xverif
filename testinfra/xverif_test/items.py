from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from .catalog import Suite
from .errors import ExternalSuiteFailure


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    cwd: Path
    returncode: int
    elapsed_sec: float
    stdout: str
    stderr: str


class ExternalSuiteItem(pytest.Item):
    def __init__(self, *, suite: Suite, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.suite = suite
        self._result: CommandResult | None = None
        self.user_properties.append(("xverif_suite", suite.id))

    @classmethod
    def from_suite(cls, parent: pytest.Collector, suite: Suite) -> "ExternalSuiteItem":
        return cls.from_parent(parent=parent, name=f"suite::{suite.id}", suite=suite)

    def runtest(self) -> None:
        runner = self.suite.runner
        argv = _resolve_runner_argv(runner.get("argv", []))
        if not argv:
            raise ExternalSuiteFailure(
                self.suite.id,
                "command suite has no argv",
                "runner",
            )
        repo_root = Path(str(self.config.rootpath)).resolve()
        cwd_value = runner.get("cwd", ".")
        cwd = (repo_root / cwd_value).resolve()
        if not cwd.is_dir():
            raise ExternalSuiteFailure(
                self.suite.id,
                f"command cwd does not exist: {cwd_value}",
                "runner",
            )
        timeout = self.suite.timeouts.get("execute_sec", 300)
        cleanup_timeout = self.suite.timeouts.get("cleanup_sec", 20)
        result_manager = getattr(self.config, "_xverif_results", None)
        t0 = time.monotonic()
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process, cleanup_timeout)
            stdout, stderr = process.communicate()
            elapsed = time.monotonic() - t0
            if result_manager is not None:
                result_manager.write_external_logs(self.suite.id, stdout, stderr)
            raise ExternalSuiteFailure(
                self.suite.id,
                f"suite execute timeout after {timeout}s",
                "timeout",
                returncode=process.returncode,
                timed_out=True,
            )
        elapsed = time.monotonic() - t0
        self._result = CommandResult(
            argv=argv,
            cwd=cwd,
            returncode=process.returncode,
            elapsed_sec=elapsed,
            stdout=stdout,
            stderr=stderr,
        )
        if result_manager is not None:
            result_manager.write_external_logs(self.suite.id, stdout, stderr)
        if process.returncode != 0:
            raise ExternalSuiteFailure(
                self.suite.id,
                "external suite returned non-zero",
                "assertion",
                returncode=process.returncode,
            )

    def repr_failure(self, excinfo: pytest.ExceptionInfo[BaseException]) -> str:
        if isinstance(excinfo.value, ExternalSuiteFailure):
            failure = excinfo.value
            result_manager = getattr(self.config, "_xverif_results", None)
            suffix = ""
            if result_manager is not None:
                suffix = f"\nartifacts: {result_manager.relative_suite_dir(self.suite.id)}"
            return f"{failure}{suffix}"
        return super().repr_failure(excinfo)

    def reportinfo(self) -> tuple[Path, int, str]:
        # pytest requires an integer source line when a custom item is skipped
        # during setup; None causes TestReport construction to fail before the
        # intended optional-suite skip can be recorded.
        return Path(str(self.config.rootpath)) / "testinfra/catalog.v1.yaml", 0, self.name


def _resolve_runner_argv(raw: object) -> tuple[str, ...]:
    """Resolve a command runner's argv, honouring a ``python3`` interpreter marker.

    Catalog entries spell the interpreter as ``python3`` because that is the *concept*
    they mean - the Python that owns this test environment. Resolved through ``PATH`` it
    can instead be a system Python unrelated to the running suite, which made
    ``xloc.vim``/``xloc.nvim``/``xdebug.cpp_unit`` fail with
    ``SyntaxError: future feature annotations is not defined`` whenever the Conda
    environment was not active. The interpreter running this suite is by definition the
    right one (``python_test_runtime`` already guarantees it is 3.11+), so bind that
    name to it rather than to whatever ``PATH`` happens to hold.
    """
    argv = [str(value) for value in raw] if isinstance(raw, (list, tuple)) else []
    if argv and argv[0] == "python3":
        argv[0] = sys.executable
    return tuple(argv)


def _terminate_process_group(process: subprocess.Popen[str], timeout_sec: int) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=max(1, timeout_sec))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=max(1, timeout_sec))
