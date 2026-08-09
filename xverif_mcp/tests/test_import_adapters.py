from __future__ import annotations

from pathlib import Path
from inspect import signature


ROOT = Path(__file__).resolve().parents[2]


def test_stateless_adapter_defaults_are_token_efficient_xout() -> None:
    from xverif_mcp.adapters.xbit import bit_check, bit_conv, bit_eval, bit_slice
    from xverif_mcp.adapters.xentry import entry_decode, entry_explain, entry_validate
    from xverif_mcp.adapters.xloc import loc_annotate, loc_context, loc_resolve, loc_stats
    from xverif_mcp.adapters.xsva import sva_explain, sva_list, sva_parse, sva_scan

    adapters = (
        bit_check, bit_conv, bit_eval, bit_slice,
        entry_decode, entry_explain, entry_validate,
        loc_annotate, loc_context, loc_resolve, loc_stats,
        sva_explain, sva_list, sva_parse, sva_scan,
    )
    assert all(signature(adapter).parameters["output_format"].default == "xout" for adapter in adapters)


def test_in_process_stateless_adapters_do_not_use_cli_runner(
    monkeypatch,
    tmp_path: Path,
):
    from xverif_mcp.runner import StatelessCliRunner

    def fail_run_raw(self, tool, argv, input_text=None, timeout_sec=None,
                     extra_env=None, cwd=None):
        raise AssertionError(f"unexpected CLI runner call: {tool} {argv}")

    monkeypatch.setattr(StatelessCliRunner, "_run_raw", fail_run_raw)

    from xverif_mcp.adapters.xbit import bit_eval
    from xverif_mcp.adapters.xentry import entry_decode
    from xverif_mcp.adapters.xloc import (
        loc_annotate,
        loc_context,
        loc_resolve,
        loc_stats,
    )

    bit = bit_eval("2 + 3", output_format="json")
    assert bit["ok"] is True
    assert bit["result"]["unsigned"] == 5

    entry = entry_decode(
        config_path=str(ROOT / "xentry/examples/entry.yaml"),
        input_path=str(ROOT / "xentry/examples/fragments.jsonl"),
        output_format="json",
    )
    assert entry["ok"] is True
    assert entry["api_version"] == "xentry.v1"

    source = tmp_path / "sample.sv"
    source.write_text("line 1\nline 2\n", encoding="utf-8")
    map_path = tmp_path / "sim.log.xloc.jsonl"
    map_path.write_text(
        '{"loc_id":"L_00000001","file":"' + str(source) + '"}\n',
        encoding="utf-8",
    )
    loc = loc_resolve(
        "L_00000001",
        str(map_path),
        output_format="json",
    )
    assert loc["ok"] is True
    assert loc["file"] == str(source)
    assert "line" not in loc

    context = loc_context("L_00000001", str(map_path), line=2, output_format="json")
    assert context["ok"] is True
    assert context["line"] == 2
    assert context["status"] == "complete"

    log_path = tmp_path / "sim.log"
    log_path.write_text("UVM_ERROR L_00000001(2)\n", encoding="utf-8")
    stats = loc_stats(str(log_path), str(map_path), output_format="json")
    assert stats["ok"] is True
    assert stats["analysis_complete"] is True
    assert stats["rows"][0]["resolution_status"] == "resolved"

    annotated = loc_annotate(str(log_path), str(map_path), output_format="xout")
    assert isinstance(annotated, str)
    assert "annotation_count" in annotated
    assert "pointer\tkind\tvalue" not in annotated

    bad_format = loc_resolve("L_00000001", str(map_path), output_format="text")
    assert bad_format["ok"] is False
    assert bad_format["error"]["code"] == "INVALID_OUTPUT_FORMAT"

    map_path.write_text("bad json\n", encoding="utf-8")
    bad_map = loc_resolve("L_00000001", str(map_path), output_format="json")
    assert bad_map["ok"] is False
    assert bad_map["error"]["code"] == "MAP_INVALID_JSON"


def test_xbit_adapter_rejects_aliases_conflicts_and_coercive_inputs():
    from xverif_mcp.adapters.xbit import bit_check, bit_conv, bit_eval

    failures = [
        bit_conv("8'hff", state="2state", output_format="json"),
        bit_conv("8'hff", signed=True, unsigned=True, output_format="json"),
        bit_eval("data", vars={"data": True}, output_format="json"),
        bit_eval("1", output_format="text"),
        bit_check(
            "valid",
            vars={"valid": "1'b1"},
            values="values.json",
            output_format="json",
        ),
    ]

    assert all(item["ok"] is False for item in failures)
    assert all(item["error"]["code"] == "EVAL_ERROR" for item in failures)



def test_xsva_adapter_rejects_malformed_tool_response(monkeypatch):
    class DummyRunner:
        def run_json(self, tool, argv):
            return {"ok": True, "action": "parse", "result": {}}

    monkeypatch.setattr("xverif_mcp.adapters.xsva.StatelessCliRunner", DummyRunner)
    from xverif_mcp.adapters.xsva import sva_parse

    result = sva_parse("input.sva", "p", output_format="json")
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_TOOL_RESPONSE"


