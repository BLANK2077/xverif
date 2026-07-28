"""Verify MCP backend wiring and adapter-local response shaping."""

from xverif_mcp.adapters.xcov import _strip_xout_stream_framing
from xverif_mcp.adapters.xdebug import XverifDebugAdapter
from xverif_mcp.sessions.session_manager import McpSessionManager


def test_backend_uses_session_manager():
    backend = XverifDebugAdapter(mode="direct")
    assert isinstance(backend._sessions, McpSessionManager)


def test_lsf_mode_rejected():
    import pytest
    from xverif_mcp.sessions.session_manager import McpSessionManager
    with pytest.raises(ValueError, match="unsupported"):
        McpSessionManager(mode="invalid")


def test_cov_adapter_strips_complete_native_xout_stream_framing():
    native = (
        "XOUT_BEGIN request_id=cov-1 action=code_coverage.summary\n"
        "@xcov.v1 ok action=code_coverage.summary request_id=cov-1\n"
        "\n"
        "summary:\n"
        "  returned: 1\n"
        "\n"
        "XOUT_END request_id=cov-1\n"
    )

    result = _strip_xout_stream_framing(native)

    assert result.startswith("@xcov.v1 ok action=code_coverage.summary")
    assert result.endswith("  returned: 1\n")
    assert "XOUT_BEGIN" not in result
    assert "XOUT_END" not in result


def test_cov_adapter_preserves_unframed_or_incomplete_xout():
    unframed = "@xcov.v1 ok action=metrics.list\n"
    incomplete = "XOUT_BEGIN request_id=cov-1 action=metrics.list\n" + unframed

    assert _strip_xout_stream_framing(unframed) == unframed
    assert _strip_xout_stream_framing(incomplete) == incomplete


def test_mcp_adapter_restores_its_config_after_loop_wrapper(monkeypatch):
    from xverif_loop.wrapper import LoopWrapperService
    from xverif_mcp.adapters.xcov import XverifCoverageAdapter

    wrapper = LoopWrapperService(mode="direct", xdebug_bin="xdebug", xcov_bin="xcov")
    monkeypatch.setenv("XVERIF_MCP_BACKEND", "lsf")
    debug = XverifDebugAdapter()
    cov = XverifCoverageAdapter()
    assert wrapper.mode == "direct"
    assert debug.mode == "lsf"
    assert cov.mode == "lsf"
