"""Unit tests for session_errors.py."""

from xverif_loop.sessions.session_errors import (
    TERMINAL_SESSION_ERROR_CODES,
    TERMINAL_BACKEND_STATES,
    error_code,
    response_says_session_terminal,
)


class TestErrorCode:
    def test_terminal_codes(self):
        for code in TERMINAL_SESSION_ERROR_CODES:
            rsp = {"ok": False, "error": {"code": code, "message": "test"}}
            assert response_says_session_terminal(rsp), f"should be terminal: {code}"

    def test_non_terminal_code(self):
        rsp = {"ok": False, "error": {"code": "SIGNAL_NOT_FOUND", "message": "nope"}}
        assert not response_says_session_terminal(rsp)

    def test_ok_response_is_not_terminal(self):
        rsp = {"ok": True, "summary": {}}
        assert not response_says_session_terminal(rsp)


class TestSessionState:
    def test_dead_state(self):
        rsp = {"ok": False, "session": {"state": "dead"}}
        assert response_says_session_terminal(rsp)

    def test_alive_state(self):
        rsp = {"ok": True, "session": {"state": "alive"}}
        assert not response_says_session_terminal(rsp)

    def test_nested_in_data(self):
        rsp = {"ok": True, "data": {"session": {"state": "lost"}}}
        assert response_says_session_terminal(rsp)

    def test_nested_in_json_envelope(self):
        """JSONL envelope: outer envelope contains nested xdebug json."""
        rsp = {
            "id": "q1",
            "ok": True,
            "payload_format": "json",
            "json": {"ok": False, "error": {"code": "SESSION_DEAD", "message": "gone"}},
        }
        assert response_says_session_terminal(rsp)

    def test_non_dict_is_not_terminal(self):
        assert not response_says_session_terminal("not a dict")  # type: ignore[arg-type]
        assert not response_says_session_terminal(None)  # type: ignore[arg-type]


class TestErrorCodeExtract:
    def test_simple(self):
        assert error_code({"error": {"code": "X"}}) == "X"

    def test_missing(self):
        assert error_code({"ok": True}) == ""
        assert error_code({}) == ""
