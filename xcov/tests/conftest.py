"""Hermetic runtime roots for every xcov pytest item."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_xcov_runtime_roots(monkeypatch, tmp_path):
    """Keep unit/real-suite runtime state out of the repository source tree."""

    monkeypatch.setenv("XVERIF_XCOV_CACHE_DIR", str(tmp_path / "xcov-cache"))
    monkeypatch.setenv("XVERIF_XCOV_LOG_DIR", str(tmp_path / "xcov-logs"))
