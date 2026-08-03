from __future__ import annotations

import pytest

from runner import CliRunner, StdioLoopRunner


def _batch(mode: str):
    return {
        "api_version": "xdebug.v1",
        "action": "batch",
        "args": {
            "mode": mode,
            "requests": [
                {"api_version": "xdebug.v1", "action": "actions"},
                {"api_version": "xdebug.v1", "action": "does.not.exist"},
                {
                    "api_version": "xdebug.v1",
                    "action": "schema",
                    "args": {"action": "actions", "kind": "request"},
                },
            ],
        },
    }


@pytest.mark.contract
def test_batch_continue_on_error_keeps_later_requests(
    stateless_stdio_loop: StdioLoopRunner,
) -> None:
    result = stateless_stdio_loop.request(_batch("continue_on_error"))
    assert result.returncode == 0
    response = result.response
    assert response["ok"] is True
    assert response["error"] is None
    assert response["summary"] == {
        "count": 3,
        "all_ok": False,
        "failed_count": 1,
        "failed_indexes": [1],
        "failed_codes": ["UNKNOWN_ACTION"],
        "failed_layers": ["handler"],
    }
    child_results = response["data"]["results"]
    assert [child["ok"] for child in child_results] == [True, False, True]
    assert child_results[1]["error"]["code"] == "UNKNOWN_ACTION"
    assert child_results[2]["action"] == "schema"


@pytest.mark.contract
def test_batch_stop_on_error_stops_after_first_failure(
    stateless_stdio_loop: StdioLoopRunner,
) -> None:
    result = stateless_stdio_loop.request(_batch("stop_on_error"))
    assert result.returncode == 0
    response = result.response
    assert response["ok"] is True
    assert response["error"] is None
    assert response["summary"] == {
        "count": 2,
        "all_ok": False,
        "failed_count": 1,
        "failed_indexes": [1],
        "failed_codes": ["UNKNOWN_ACTION"],
        "failed_layers": ["handler"],
    }
    child_results = response["data"]["results"]
    assert [child["ok"] for child in child_results] == [True, False]
    assert child_results[1]["error"]["code"] == "UNKNOWN_ACTION"


@pytest.mark.contract
def test_batch_failure_aggregation_is_visible_in_xout(cli_runner: CliRunner) -> None:
    result = cli_runner.run(_batch("stop_on_error"), output_format="xout")
    assert result.returncode == 0
    assert result.response.startswith("@xdebug.batch.v1\n")
    assert "failed_count" in result.response and ": 1" in result.response
    assert "UNKNOWN_ACTION" in result.response
    assert "handler" in result.response


@pytest.mark.contract
def test_batch_requires_requests_array(
    stateless_stdio_loop: StdioLoopRunner,
) -> None:
    result = stateless_stdio_loop.request(
        {
            "api_version": "xdebug.v1",
            "action": "batch",
            "args": {},
        }
    )
    assert result.returncode == 1
    assert result.response["ok"] is False
    assert result.response["error"]["code"] == "INVALID_REQUEST"
    assert result.response["error"]["invalid_arg"] == "args.requests"


@pytest.mark.contract
def test_batch_does_not_default_child_api_version(
    stateless_stdio_loop: StdioLoopRunner,
) -> None:
    request = _batch("continue_on_error")
    request["args"]["requests"][1] = {"action": "actions"}

    result = stateless_stdio_loop.request(request)

    assert result.returncode == 0
    response = result.response
    assert response["ok"] is True
    assert response["error"] is None
    assert response["summary"] == {
        "count": 3,
        "all_ok": False,
        "failed_count": 1,
        "failed_indexes": [1],
        "failed_codes": ["UNSUPPORTED_API_VERSION"],
        "failed_layers": ["schema"],
    }
    child = response["data"]["results"][1]
    assert child["ok"] is False
    assert child["error"]["code"] == "UNSUPPORTED_API_VERSION"
    assert child["summary"] == {
        "status": "error",
        "error_code": "UNSUPPORTED_API_VERSION",
    }
    assert child["data"] is None
