from __future__ import annotations

import json
from pathlib import Path

import pytest

from xverif_loop.sessions.capabilities import lifecycle_capability
from xverif_loop.sessions.loop_session import _extract_session_id


def test_xdebug_and_xcov_expose_symmetric_managed_lifecycle_with_different_native_capabilities() -> None:
    debug = lifecycle_capability("xdebug")
    cov = lifecycle_capability("xcov")

    assert debug.native_open_action == cov.native_open_action == "session.open"
    assert debug.native_close_action == cov.native_close_action == "session.close"
    assert debug.native_kill_action == "session.kill"
    assert debug.native_gc_action == "session.gc"
    assert debug.backend_survives_loop is True
    assert debug.fixed_admin_path is True
    assert debug.json_request_style == "loop_marker"
    assert debug.managed_transport == "uds"
    assert debug.accepts_trace_id is True
    assert debug.session_id_path == ("session", "session_id")
    assert cov.native_kill_action is None
    assert cov.native_gc_action is None
    assert cov.backend_survives_loop is False
    assert cov.fixed_admin_path is False
    assert cov.json_request_style == "transport_envelope"
    assert cov.managed_transport is None
    assert cov.accepts_trace_id is False
    assert cov.session_id_path == ("data", "session", "session_id")


def test_unknown_backend_has_no_implicit_capability_fallback() -> None:
    with pytest.raises(ValueError, match="unsupported lifecycle backend"):
        lifecycle_capability("unknown")


def test_xdebug_session_id_path_matches_canonical_response_and_rejects_old_summary() -> None:
    root = Path(__file__).resolve().parents[2]
    canonical = json.loads(
        (
            root
            / "xdebug"
            / "examples"
            / "responses"
            / "session.open.basic.json"
        ).read_text(encoding="utf-8")
    )

    assert _extract_session_id(canonical, "xdebug") == "case_a"
    assert _extract_session_id(
        {
            "ok": True,
            "action": "session.open",
            "summary": {
                "session_id": "removed_summary_location",
                "status": "opened",
            },
        },
        "xdebug",
    ) is None
