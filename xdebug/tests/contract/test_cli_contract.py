from __future__ import annotations

import json

import pytest

from runner import CliRunner


VALID_ACTIONS = {"api_version": "xdebug.v1", "action": "actions"}


@pytest.mark.contract
@pytest.mark.parametrize("input_mode", ["stdin", "file"])
def test_valid_json_input_modes(cli_runner: CliRunner, input_mode: str) -> None:
    result = cli_runner.run(
        VALID_ACTIONS,
        input_mode=input_mode,
        output_format="json",
    )
    assert result.returncode == 0
    assert result.stderr_raw == ""
    assert result.response["ok"] is True
    assert result.response["action"] == "actions"
    assert result.response["summary"]["action_count"] > 0


@pytest.mark.contract
def test_default_output_is_xout(cli_runner: CliRunner) -> None:
    result = cli_runner.run(VALID_ACTIONS, output_format="xout")
    assert result.returncode == 0
    assert isinstance(result.response, str)
    assert result.response.startswith("@xdebug.actions.v1")
    summary_block = result.response.split("summary:\n", 1)[1].split("\n\n", 1)[0]
    summary_lines = [line for line in summary_block.splitlines() if line.startswith("  ")]
    assert {line.split(":", 1)[0].strip() for line in summary_lines} >= {
        "action_count", "total_action_count", "verbose", "filtered"
    }
    assert len({line.index(":") for line in summary_lines}) == 1


@pytest.mark.contract
def test_top_level_output_is_rejected(cli_runner: CliRunner) -> None:
    request = dict(VALID_ACTIONS)
    request["output"] = {"format": "json"}
    result = cli_runner.run(request, output_format="json")
    assert result.returncode == 1
    assert result.response["ok"] is False
    assert result.response["error"]["code"] == "INVALID_REQUEST"
    assert "top-level output is not supported" in result.response["error"]["message"]
    assert "CLI --json" in result.response["error"]["message"]
    assert "args.output.file_format" in result.response["error"]["message"]


@pytest.mark.contract
def test_environment_output_format_overrides_default(cli_runner: CliRunner) -> None:
    result = cli_runner.run(
        VALID_ACTIONS,
        output_format="xout",
        env={"XVERIF_OUTPUT": "json"},
    )
    assert result.returncode == 0
    assert result.metadata["actual_output_format"] == "json"
    assert result.response["action"] == "actions"


@pytest.mark.contract
@pytest.mark.parametrize(
    ("request_body", "error_code"),
    [
        ("{bad", "INVALID_JSON"),
        ("[]", "INVALID_JSON"),
        ({"action": "actions"}, "UNSUPPORTED_API_VERSION"),
        (
            {"api_version": "xdebug.v0", "action": "actions"},
            "UNSUPPORTED_API_VERSION",
        ),
        ({"api_version": "xdebug.v1"}, "INVALID_REQUEST"),
        (
            {"api_version": "xdebug.v1", "action": "does.not.exist"},
            "UNKNOWN_ACTION",
        ),
        (
            {"api_version": "xdebug.v1", "action": "signal.search"},
            "UNKNOWN_ACTION",
        ),
    ],
)
def test_structured_cli_errors(
    cli_runner: CliRunner, request_body: object, error_code: str
) -> None:
    result = cli_runner.run(request_body, output_format="json")
    assert result.returncode == 1
    assert result.response["ok"] is False
    assert result.response["error"]["code"] == error_code
    assert result.response["error"]["message"]
    assert result.stderr_raw == ""


@pytest.mark.contract
def test_extra_cli_argument_returns_json_only_error(cli_runner: CliRunner) -> None:
    result = cli_runner.run(
        VALID_ACTIONS,
        output_format="json",
        extra_args=["unexpected-input"],
    )
    assert result.returncode == 1
    assert result.response["ok"] is False
    assert result.response["error"]["code"] == "JSON_ONLY"


@pytest.mark.contract
def test_json_response_is_single_document(cli_runner: CliRunner) -> None:
    result = cli_runner.run(VALID_ACTIONS, output_format="json")
    decoded = json.loads(result.stdout_raw)
    assert decoded == result.response
