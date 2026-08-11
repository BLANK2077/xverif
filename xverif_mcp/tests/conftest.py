"""Hermetic runtime roots inherited by every MCP test and child process."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_xcov_runtime_roots(monkeypatch, tmp_path):
    """Keep spawned xcov loops' cache and logs outside the repository."""

    monkeypatch.setenv("XVERIF_XCOV_CACHE_DIR", str(tmp_path / "xcov-cache"))
    monkeypatch.setenv("XVERIF_XCOV_LOG_DIR", str(tmp_path / "xcov-logs"))
