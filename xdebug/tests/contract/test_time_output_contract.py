from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import pytest

from runner import CliRunner


DOC_PATH = Path("docs/XDEBUG_TIME_HANDLING_REVIEW_AND_TEST_MATRIX.md")
FORBIDDEN_NUMERIC_TIME_KEYS = {"time_value"}
FORBIDDEN_NUMERIC_TIME_SUFFIXES = ("_ps",)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_json(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _forbidden_numeric_time_paths(example: Any) -> list[str]:
    offenders: list[str] = []
    for path, value in _walk_json(example):
        key = path.rsplit(".", 1)[-1]
        if key in FORBIDDEN_NUMERIC_TIME_KEYS or key.endswith(
            FORBIDDEN_NUMERIC_TIME_SUFFIXES
        ):
            if isinstance(value, (int, float)):
                offenders.append(path)
    return offenders


@pytest.mark.contract
def test_time_handling_review_doc_exists_and_names_output_contract(
    xdebug_root: Path,
) -> None:
    text = (xdebug_root / DOC_PATH).read_text(encoding="utf-8")
    required_phrases = [
        "同一个逻辑时间只输出一份 canonical 时间字符串",
        "禁止 `*_ps` 数字字段",
        "JSON 与 xout",
        "默认无单位时间范围按 ns",
        "默认输出渲染单位按 ns",
        "args.render_time_unit",
        "本阶段已进入实现",
    ]
    for phrase in required_phrases:
        assert phrase in text


@pytest.mark.contract
def test_response_examples_publish_only_one_canonical_time_string(
    xdebug_root: Path,
) -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted((xdebug_root / "examples" / "responses").glob("*.json")):
        fields = _forbidden_numeric_time_paths(_load_json(path))
        if fields:
            offenders[path.name] = fields
    assert not offenders


@pytest.mark.contract
def test_time_parsing_has_single_contract_entrypoint(xdebug_root: Path) -> None:
    source_root = xdebug_root / "src"
    allowed = {
        source_root / "core" / "npi" / "time_contract.cpp",
        source_root / "waveform" / "common" / "time_spec.cpp",
    }
    offenders: dict[str, list[str]] = {}
    pattern = re.compile(
        r"\bstrtod\s*\(|npi_fsdb_convert_time_in\s*\(|npi_fsdb_convert_time_out\s*\("
    )
    for path in sorted(source_root.rglob("*.cpp")):
        if path in allowed:
            continue
        matches = [
            f"{index}: {line.strip()}"
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if pattern.search(line)
        ]
        if matches:
            offenders[str(path.relative_to(xdebug_root))] = matches
    assert not offenders


@pytest.mark.contract
def test_time_formatting_and_default_units_are_centralized(xdebug_root: Path) -> None:
    risky_patterns = {
        "src/waveform/server/service/context.cpp": [
            'snprintf(buf, sizeof(buf), "%.6g", value)',
            "npi_fsdb_convert_time_out",
            "npi_fsdb_convert_time_in",
        ],
        "src/combined/active_trace_common.h": [
            "std::setprecision(15) << value",
            "fsdb_time_to_precise_text",
        ],
    }
    offenders: dict[str, list[str]] = {}
    for rel_path, patterns in risky_patterns.items():
        text = (xdebug_root / rel_path).read_text(encoding="utf-8")
        hits = [pattern for pattern in patterns if pattern in text]
        if hits:
            offenders[rel_path] = hits
    assert not offenders


@pytest.mark.contract
def test_render_time_unit_is_render_only_and_defaults_to_ns(xdebug_root: Path) -> None:
    header = (xdebug_root / "src/core/npi/time_contract.h").read_text(encoding="utf-8")
    assert "TimeRenderUnit::Ns" in header
    assert 'std::string default_unit = "ns"' in header

    allowed = {
        Path("src/core/npi/time_contract.cpp"),
        Path("src/core/npi/time_contract.h"),
        Path("src/engine/server.cpp"),
        Path("src/waveform/server/service/query_actions.cpp"),
    }
    offenders: dict[str, list[str]] = {}
    for path in sorted((xdebug_root / "src").rglob("*")):
        if path.suffix not in {".cpp", ".h"}:
            continue
        rel = path.relative_to(xdebug_root)
        if rel in allowed:
            continue
        matches = [
            f"{index}: {line.strip()}"
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if '"render_time_unit"' in line or "args.render_time_unit" in line
        ]
        if matches:
            offenders[str(rel)] = matches
    assert not offenders


@pytest.mark.contract
def test_render_time_unit_schema_has_exact_public_enum(
    xdebug_root: Path,
) -> None:
    schema = _load_json(
        xdebug_root
        / "schemas"
        / "v1"
        / "actions"
        / "value.at.request.schema.json"
    )
    validator = jsonschema.Draft202012Validator(schema)
    base = {
        "api_version": "xdebug.v1",
        "action": "value.at",
        "target": {"session_id": "render-time-unit-contract"},
        "args": {
            "signal": "ai_complex_top.sig_a",
            "time": "10ns",
        },
    }
    for unit in ("auto", "ps", "ns", "us"):
        request = {
            **base,
            "args": {**base["args"], "render_time_unit": unit},
        }
        validator.validate(request)

    for invalid in ("", "n", "NS", "fs", "ms", "s"):
        request = {
            **base,
            "args": {**base["args"], "render_time_unit": invalid},
        }
        with pytest.raises(jsonschema.ValidationError) as caught:
            validator.validate(request)
        assert list(caught.value.absolute_path) == [
            "args",
            "render_time_unit",
        ]

    retired = {
        **base,
        "args": {**base["args"], "time_unit": "ns"},
    }
    with pytest.raises(jsonschema.ValidationError) as caught:
        validator.validate(retired)
    assert list(caught.value.absolute_path) == ["args"]
    assert caught.value.validator == "additionalProperties"


@pytest.mark.contract
def test_render_time_unit_runtime_matches_schema_exactly(
    cli_runner: CliRunner,
    complex_wave_fsdb: Path,
) -> None:
    opened = cli_runner.run(
        {
            "api_version": "xdebug.v1",
            "action": "session.open",
            "target": {"fsdb": str(complex_wave_fsdb)},
            "args": {"name": "render_time_unit_contract"},
        },
        output_format="json",
        timeout_sec=120,
    )
    assert opened.ok, opened.stdout_raw + opened.stderr_raw
    session = opened.response["session"]
    target = {"session_id": session["session_id"]}
    expected_time = {
        "auto": "10ns",
        "ps": "10000ps",
        "ns": "10ns",
        "us": "0.01us",
    }
    try:
        for unit, expected in expected_time.items():
            result = cli_runner.run(
                {
                    "api_version": "xdebug.v1",
                    "action": "value.at",
                    "target": target,
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "time": "10ns",
                        "render_time_unit": unit,
                    },
                },
                output_format="json",
                timeout_sec=120,
            )
            assert result.ok, result.stdout_raw + result.stderr_raw
            assert result.response["data"]["samples"][0]["time"] == expected

        invalid_requests = [
            {"render_time_unit": unit}
            for unit in ("", "n", "NS", "fs", "ms", "s")
        ]
        invalid_requests.append({"time_unit": "ns"})
        for invalid_fields in invalid_requests:
            result = cli_runner.run(
                {
                    "api_version": "xdebug.v1",
                    "action": "value.at",
                    "target": target,
                    "args": {
                        "signal": "ai_complex_top.sig_a",
                        "time": "10ns",
                        **invalid_fields,
                    },
                },
                output_format="json",
                timeout_sec=120,
            )
            assert not result.ok, invalid_fields
            assert result.response["error"]["code"] == "INVALID_REQUEST"
            assert result.response["error"]["error_layer"] == "schema"
    finally:
        closed = cli_runner.run(
            {
                "api_version": "xdebug.v1",
                "action": "session.close",
                "target": target,
            },
            output_format="json",
            timeout_sec=120,
        )
        assert closed.ok, closed.stdout_raw + closed.stderr_raw
