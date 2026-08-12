from __future__ import annotations

import json
from pathlib import Path

import pytest

from xverif_mcp.schema_projection import project


def _native_request() -> dict:
    return {
        "ok": True,
        "data": {
            "schema_path": "schemas/v1/actions/value.at.request.schema.json",
            "schema": {
                "x-description-zh": "读取一个采样点的值。",
                "properties": {
                    "args": {
                        "type": "object", "required": ["signal", "time"],
                        "properties": {
                            "signal": {"type": "string", "description": "目标叶子信号。"},
                            "time": {"type": "string", "description": "目标时间。"},
                        }, "additionalProperties": False,
                    },
                    "limits": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            },
        },
    }


def test_mcp_projection_exposes_compact_schema_without_native_envelope() -> None:
    result = project("value.at", "request", "mcp", _native_request())
    payload = result["data"]
    assert payload["call_with"] == "xverif_debug_query"
    assert payload["purpose_en"] == (
        "Read a signal or every value maintained by a named list, APB, stream, or AXI "
        "configuration at one or more exact waveform times."
    )
    assert payload["purpose_zh"] == "按一个或多个指定时间读取单信号、命名信号列表或接口配置维护的值。"
    assert "api_version" not in payload["args_schema"]["properties"]
    assert payload["minimal_call"]["action"] == "value.at"
    assert payload["minimal_call"]["session_id"] == "<session_id>"
    assert payload["session_contract"] == {
        "parameter": "session_id",
        "mode": "required",
        "requires": "waveform",
        "session_id": "required",
    }
    assert payload["skill_guidance"] == {
        "skill": "$xverif",
        "reference": "references/capabilities/xdebug.md",
        "instruction": (
            "构造请求前读取 $xverif 的 xdebug workflow、action 路由和"
            "完整性合同；不要仅凭本 schema 猜跨 action 语义。"
        ),
    }
    assert {"purpose", "parameter_guide", "common_examples", "corrected_examples"}.isdisjoint(payload)


def test_response_view_requires_response_kind() -> None:
    result = project("value.at", "request", "response", _native_request())
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_response_kind_does_not_implicitly_change_view() -> None:
    result = project("value.at", "response", "mcp", _native_request())
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_session_actions_use_the_dedicated_mcp_tool() -> None:
    result = project("session.open", "request", "mcp", _native_request())
    payload = result["data"]
    assert payload["call_with"] == "xverif_debug_session_open"
    assert payload["session_contract"] == {
        "parameter": "session_id",
        "mode": "dedicated_tool",
    }
    assert payload["args_schema"]["required"] == ["name"]


def test_session_selector_schema_and_invalid_example_are_consistent() -> None:
    result = project("session.close", "request", "mcp", _native_request())
    payload = result["data"]
    assert payload["args_schema"]["required"] == ["session_id"]
    assert "anyOf" not in payload["args_schema"]
    assert "name" not in payload["args_schema"]["properties"]
    assert payload["invalid_examples"][0]["call"] == {}


def test_all_action_projections_have_one_field_contract_and_one_success_example() -> None:
    root = Path(__file__).resolve().parents[2]
    actions = json.loads((root / "xdebug/specs/actions/actions.yaml").read_text(encoding="utf-8"))["actions"]
    redundant = {"purpose", "parameter_guide", "common_examples", "corrected_examples"}
    for action in actions:
        assert action["status"] in {"stable", "experimental"}
        schema = json.loads((root / "xdebug" / action["schemas"]["request"]).read_text(encoding="utf-8"))
        payload = project(action["name"], "request", "mcp", {"ok": True, "data": {"schema": schema}})["data"]
        assert redundant.isdisjoint(payload), action["name"]
        assert "args_schema" in payload and "minimal_call" in payload, action["name"]
        assert not _contains_key(payload["args_schema"], "x-description-zh"), action["name"]
        assert not any(item.startswith(("必须提供：", "还必须满足以下一组参数：", "当 "))
                       for item in payload["constraints"]), action["name"]


def test_action_contract_registry_rejects_unknown_status_fail_closed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from xverif_mcp import xdebug_contracts

    registry = tmp_path / "actions.json"
    registry.write_text(
        json.dumps({
            "actions": [
                {
                    "name": "future.action",
                    "status": "removed",
                },
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(xdebug_contracts, "action_specs_path", lambda: registry)

    with pytest.raises(
        xdebug_contracts.XdebugContractError,
        match=(
            r"unsupported status: 'removed'; "
            r"expected 'stable' or 'experimental'"
        ),
    ):
        xdebug_contracts.action_spec("other.action")


def test_expr_normalize_projection_exposes_both_resource_variants() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((
        root / "xdebug/schemas/v1/actions/expr.normalize.request.schema.json"
    ).read_text(encoding="utf-8"))

    payload = project(
        "expr.normalize",
        "request",
        "mcp",
        {"ok": True, "data": {"schema": schema}},
    )["data"]

    assert payload["session_contract"] == {
        "parameter": "session_id",
        "mode": "conditional",
        "variants": [
            {
                "name": "expression",
                "requires": "none",
                "required_args": ["expr"],
                "forbidden_args": [
                    "signal", "line_limit", "no_statement_only", "role",
                ],
                "session_id": "forbidden",
            },
            {
                "name": "design_signal",
                "requires": "design",
                "required_args": ["signal"],
                "forbidden_args": ["expr"],
                "session_id": "required",
            },
        ],
    }
    assert "session_id" not in payload["minimal_call"]
    assert payload["minimal_call"]["args"] == {"expr": "valid && !ready"}


def test_builtin_projection_forbids_session_id() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((
        root / "xdebug/schemas/v1/actions/actions.request.schema.json"
    ).read_text(encoding="utf-8"))

    payload = project(
        "actions",
        "request",
        "mcp",
        {"ok": True, "data": {"schema": schema}},
    )["data"]

    assert payload["session_contract"]["mode"] == "forbidden"
    assert "session_id" not in payload["minimal_call"]


def test_stream_cache_scope_is_visible_in_mcp_projection() -> None:
    root = Path(__file__).resolve().parents[2]
    for action in ("stream.query", "stream.export", "stream.validate"):
        schema = json.loads((
            root / "xdebug/schemas/v1/actions" /
            (action + ".request.schema.json")
        ).read_text(encoding="utf-8"))
        payload = project(
            action, "request", "mcp",
            {"ok": True, "data": {"schema": schema}},
        )["data"]
        cache_scope = payload["args_schema"]["properties"]["cache_scope"]
        assert cache_scope["enum"] == ["full", "range"]
        assert cache_scope["default"] == "full"
        assert any("cache_scope" in item for item in payload["constraints"])
    validate_schema = json.loads((
        root / "xdebug/schemas/v1/actions/stream.validate.request.schema.json"
    ).read_text(encoding="utf-8"))
    validate_args = project(
        "stream.validate", "request", "mcp",
        {"ok": True, "data": {"schema": validate_schema}},
    )["data"]["args_schema"]
    assert validate_args["allOf"][0]["then"]["not"]["required"] == [
        "cache_scope"
    ]


def test_protocol_query_projections_publish_strong_skill_routing() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = {
        "apb.query": "apb.statistics",
        "axi.query": "output.include_data=true",
        "stream.query": "apb.query/axi.query",
    }
    for action, marker in expected.items():
        schema = json.loads((
            root / "xdebug/schemas/v1/actions" /
            (action + ".request.schema.json")
        ).read_text(encoding="utf-8"))
        payload = project(
            action, "request", "mcp",
            {"ok": True, "data": {"schema": schema}},
        )["data"]
        assert payload["skill_guidance"]["skill"] == "$xverif"
        assert marker in payload["skill_guidance"]["routing_hint"]
        assert any(action.split(".")[0] in item
                   for item in payload["constraints"])


def test_apb_export_projection_explains_preview_and_artifact_modes() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((
        root / "xdebug/schemas/v1/actions/apb.export.request.schema.json"
    ).read_text(encoding="utf-8"))
    payload = project(
        "apb.export", "request", "mcp",
        {"ok": True, "data": {"schema": schema}},
    )["data"]
    assert "最多 8 行 preview" in payload["constraints"][0]
    assert "apb.query" in payload["skill_guidance"]["routing_hint"]
    assert payload["minimal_call"]["action"] == "apb.export"


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(child, key) for child in value.values())
    if isinstance(value, list):
        return any(_contains_key(child, key) for child in value)
    return False
