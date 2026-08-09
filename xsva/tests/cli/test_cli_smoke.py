"""CLI contract and human XOUT tests for xsva."""

from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from xsva.contracts import ResponseContractError, validate_response
from xsva.cli import _success
from xsva.xout import to_xout

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(tmp_path, source: str, *args: str):
    path = tmp_path / "input.sva"
    path.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "xsva", *args, "--file", str(path)],
        cwd=PROJECT_ROOT, text=True, encoding="utf-8",
        capture_output=True, check=False,
    )


SOURCE = """
property p_req_ack;
  @(posedge clk) disable iff (!rst_n)
  req |-> ##[1:4] ack;
endproperty
a_req_ack: assert property (p_req_ack);
"""


def _assert_analysis_contract(payload: dict, status: str = "exact") -> None:
    assert payload["lowering_status"] == status
    assert set(payload["precision"]) == {"semantic_model", "path_enumeration", "reason_codes"}
    assert isinstance(payload["diagnostics"], list)
    completeness = payload["completeness"]
    assert set(completeness) == {
        "scan_complete", "analysis_complete", "response_truncated",
        "path_enumeration_complete", "total_path_count",
        "returned_path_count", "truncation_scopes",
    }
    expected_truncated = (
        completeness["total_path_count"] is not None
        and (
            completeness["path_enumeration_complete"] is False
            or completeness["returned_path_count"] < completeness["total_path_count"]
        )
    )
    assert completeness["response_truncated"] is expected_truncated
    assert completeness["truncation_scopes"] == (["analysis.match_paths"] if expected_truncated else [])


def test_default_list_scan_and_lint_are_human_xout(tmp_path):
    listed = _run(tmp_path, SOURCE, "list")
    assert listed.returncode == 0
    assert listed.stdout.startswith("Properties:\n")
    assert "a_req_ack: assert property (p_req_ack)" in listed.stdout
    scanned = _run(tmp_path, SOURCE, "scan")
    assert "Property blocks: 1" in scanned.stdout
    assert "##N" in scanned.stdout
    linted = _run(tmp_path, SOURCE, "lint")
    assert linted.returncode == 0
    assert "pointer\tkind\tvalue" not in listed.stdout + scanned.stdout + linted.stdout


def test_all_commands_keep_explicit_closed_json(tmp_path):
    commands = (
        ("list",), ("scan",), ("lint",),
        ("parse", "--property", "p_req_ack", "--emit", "timeline-ir"),
        ("explain", "--property", "p_req_ack"),
    )
    for command in commands:
        result = _run(tmp_path, SOURCE, *command, "--json")
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        validate_response(payload, expected_action=command[0])
        _assert_analysis_contract(payload)


def test_parse_defaults_to_domain_ir_and_explain_to_semantic_text(tmp_path):
    parsed = _run(tmp_path, SOURCE, "parse", "--property", "p_req_ack", "--emit", "timeline-ir")
    payload = json.loads(parsed.stdout)
    assert payload["schema_version"] == "xsva.timeline_ir.v1"
    assert payload["match_paths"][0]["obligations"]
    explained = _run(tmp_path, SOURCE, "explain", "--property", "p_req_ack")
    assert explained.returncode == 0
    assert "Property: p_req_ack" in explained.stdout
    assert "ack must be true at cycle +1 to +4" in explained.stdout


def test_default_error_is_xout_and_json_error_is_explicit(tmp_path):
    result = _run(tmp_path, SOURCE, "explain", "--property", "missing")
    assert result.returncode == 3
    assert result.stdout == "xsva error: property not found: missing\n"
    result = _run(tmp_path, SOURCE, "explain", "--property", "missing", "--json")
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    _assert_analysis_contract(payload, "unsupported")
    assert payload["error"]["code"] == "PROPERTY_NOT_FOUND"


def test_path_limit_is_explicit_in_response_and_strict_error(tmp_path):
    source = """
property p_many;
  req |-> ##[1:20] x ##[1:10] y ##1 z;
endproperty
"""
    result = _run(tmp_path, source, "parse", "--property", "p_many", "--emit", "timeline-ir", "--json")
    payload = json.loads(result.stdout)
    _assert_analysis_contract(payload, "partial")
    assert payload["completeness"]["total_path_count"] == 200
    assert payload["completeness"]["returned_path_count"] == 10
    assert "XSVA-L001" in payload["precision"]["reason_codes"]
    strict = _run(tmp_path, source, "explain", "--property", "p_many", "--strict", "--json")
    assert strict.returncode == 2
    strict_payload = json.loads(strict.stdout)
    assert strict_payload["error"]["code"] == "UNSUPPORTED_STRICT"
    assert strict_payload["completeness"] == payload["completeness"]


def test_response_contract_is_action_specific_and_shared_with_xout(tmp_path):
    payload = json.loads(_run(tmp_path, SOURCE, "list", "--json").stdout)
    rendered = to_xout(payload)
    assert rendered.startswith("Properties:\n")
    assert "pointer\tkind\tvalue" not in rendered
    mutations = []
    unknown = deepcopy(payload)
    unknown["fallback"] = True
    mutations.append(unknown)
    wrong_result = deepcopy(payload)
    wrong_result["result"]["properties"][0]["compat_name"] = "p_req_ack"
    mutations.append(wrong_result)
    contradictory = deepcopy(payload)
    contradictory["completeness"]["response_truncated"] = True
    mutations.append(contradictory)
    for mutated in mutations:
        with pytest.raises(ResponseContractError):
            validate_response(mutated)
        with pytest.raises(ResponseContractError):
            to_xout(mutated)


def test_timeline_contract_binds_windows_obligations_and_path_count(tmp_path):
    payload = json.loads(_run(tmp_path, SOURCE, "parse", "--property", "p_req_ack", "--emit", "timeline-ir", "--json").stdout)
    obligation = payload["result"]["obligations"][0]
    obligation["has_window"] = not obligation["has_window"]
    with pytest.raises(ResponseContractError, match="has_window"):
        validate_response(payload, expected_action="parse")

    payload = json.loads(_run(tmp_path, SOURCE, "parse", "--property", "p_req_ack", "--emit", "timeline-ir", "--json").stdout)
    payload["result"]["match_paths"][0]["obligations"] = ["not-canonical"]
    with pytest.raises(ResponseContractError, match="canonical"):
        validate_response(payload, expected_action="parse")

    payload = json.loads(_run(tmp_path, SOURCE, "parse", "--property", "p_req_ack", "--emit", "timeline-ir", "--json").stdout)
    payload["result"]["match_paths"] = []
    with pytest.raises(ResponseContractError, match="returned_path_count"):
        to_xout(payload)


def test_xout_rejects_non_string_object_keys(tmp_path):
    payload = json.loads(_run(tmp_path, SOURCE, "list", "--json").stdout)
    payload[1] = "coercion-is-not-allowed"
    with pytest.raises(TypeError, match="object key type"):
        to_xout(payload)


def test_parse_nested_results_are_closed_for_every_emit(tmp_path):
    mutations = []
    for emit in ("surface-ir", "sequence-ir", "timeline-ir"):
        result = _run(
            tmp_path,
            SOURCE,
            "parse",
            "--property",
            "p_req_ack",
            "--emit",
            emit,
            "--json",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        validate_response(payload, expected_action="parse")
        mutated = deepcopy(payload)
        if emit == "surface-ir":
            mutated["result"]["clock"]["fallback"] = True
        elif emit == "sequence-ir":
            mutated["result"]["antecedent"][0]["fallback"] = True
        else:
            mutated["result"]["trigger"]["fallback"] = True
        mutations.append(mutated)

    for payload in mutations:
        with pytest.raises(ResponseContractError, match="unknown fields"):
            validate_response(payload, expected_action="parse")


def test_diagnostics_and_lint_facts_are_closed_and_correlated(tmp_path):
    result = _run(
        tmp_path,
        "a_missing: assert property (p_missing);",
        "lint",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["lowering_status"] == "unsupported"
    assert payload["result"]["issue_count"] == len(payload["diagnostics"]) == 1
    assert payload["diagnostics"][0]["code"] == "XSVA-E002"

    wrong_count = deepcopy(payload)
    wrong_count["result"]["issue_count"] += 1
    with pytest.raises(ResponseContractError, match="issue_count"):
        validate_response(wrong_count, expected_action="lint")

    unknown_span = deepcopy(payload)
    unknown_span["diagnostics"][0]["span"]["fallback"] = 0
    with pytest.raises(ResponseContractError, match="unknown fields"):
        validate_response(unknown_span, expected_action="lint")


def test_timeline_failure_conditions_are_bound_to_obligations(tmp_path):
    payload = json.loads(
        _run(
            tmp_path,
            SOURCE,
            "parse",
            "--property",
            "p_req_ack",
            "--emit",
            "timeline-ir",
            "--json",
        ).stdout
    )
    assert payload["result"]["failure_conditions"]
    payload["result"]["failure_conditions"][0] = "compatibility fallback"
    with pytest.raises(ResponseContractError, match="canonical"):
        validate_response(payload, expected_action="parse")


def test_non_parse_success_cannot_publish_emit():
    with pytest.raises(ValueError, match="does not declare emit"):
        _success(
            "list",
            file="input.sva",
            result={"properties": [], "assertions": []},
            emit="timeline-ir",
        )
