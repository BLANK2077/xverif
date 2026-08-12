from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NativeXoutCase:
    action: str
    resource: str | None
    args: dict[str, Any] = field(default_factory=dict)
    prerequisite: str | None = None
    error_family: str = "schema"
    required_text: tuple[str, ...] = ()
    forbidden_text: tuple[str, ...] = ()


def case(action: str, resource: str | None = None, args: dict[str, Any] | None = None,
         prerequisite: str | None = None, error_family: str = "schema",
         required_text: tuple[str, ...] = (),
         forbidden_text: tuple[str, ...] = ()) -> NativeXoutCase:
    return NativeXoutCase(action, resource, args or {}, prerequisite, error_family,
                          required_text, forbidden_text)


CASES = (
    case("actions", args={},
         required_text=("builtin:", "session:", "design:", "waveform:", "combined:"),
         forbidden_text=("\nactions:\n",)),
    case("apb.config.list", "P", {"name": "apb0"}, "apb", "config"),
    case("apb.config.load", "P", {"name": "apb_primary", "config": "$APB_CONFIG"}, error_family="signal/config"),
    case("apb.query", "P", {"name": "apb0", "query": {"line_limit": 2}}, "apb", "filter/config",
         ("transactions:", "time", "addr", "data", "is_write", "has_error")),
    case("apb.statistics", "P", {"name": "apb0"}, "apb", "filter/config"),
    case("apb.transaction.cursor", "P", {"name": "apb0", "op": "begin"}, "apb", "cursor/config"),
    case("apb.transfer_window", "P", {"name": "apb0"}, "apb", "index/config"),
    case("axi.analysis", "A", {"name": "axi0", "analysis": "latency", "direction": "all"}, "axi", "enum/config"),
    case("axi.channel_stall", "A", {"name": "axi0", "channel": "r", "line_limit": 2}, "axi", "channel/config"),
    case("axi.config.list", "A", {"name": "axi0"}, "axi", "config"),
    case("axi.config.load", "A", {"name": "axi_primary", "config": "$AXI_CONFIG"}, error_family="signal/config"),
    case("axi.export", "A", {"name": "axi0", "time_range": {"begin": "0ns", "end": "1us"}, "output": {"path": "$TMP/axi", "file_format": "tsv"}}, "axi", "output/config"),
    case("axi.latency_outlier", "A", {"name": "axi0", "method": "top_n", "top_n": 2, "line_limit": 2}, "axi", "method/config"),
    case("axi.outstanding_timeline", "A", {"name": "axi0", "direction": "all", "line_limit": 4}, "axi", "direction/config"),
    case("axi.query", "A", {"name": "axi0", "direction": "write", "query": {"line_limit": 2}}, "axi", "filter/config",
         ("transactions:", "direction", "phase_order", "latency",
          "response_dependency_violation", "address", "data", "response")),
    case("axi.request_response_pair", "A", {"name": "axi0", "direction": "all", "line_limit": 2}, "axi", "direction/config"),
    case("axi.statistics", "A", {"name": "axi0"}, "axi", "filter/config"),
    case("axi.transaction.cursor", "A", {"name": "axi0", "op": "begin", "direction": "all"}, "axi", "cursor/config"),
    case("batch", args={"requests": [{"api_version": "xdebug.v1", "action": "actions", "args": {}}]}, error_family="child request"),
    case("counter.statistics", "W", {"clock": "ai_complex_top.clk", "edge": "posedge", "time_range": {"begin": "55ns", "end": "95ns"}, "vld": "ai_complex_top.rst_n", "cnt": "ai_complex_top.counter_inc"}, error_family="signal/time"),
    case("event.config.list", "E", {"name": "rdy"}, "event", "config"),
    case("event.config.load", "E", {"name": "primary_event", "config_path": "$EVENT_CONFIG"}, error_family="file/config"),
    case("event.export", "E", {"name": "rdy", "expr": "vld && rdy", "output": {"path": "$TMP/events.json", "file_format": "json"}}, "event", "expression/output"),
    case("event.find", "E", {"name": "rdy", "expr": "vld && rdy", "mode": "all", "line_limit": 2}, "event", "expression/config"),
    case("expr.eval_at", "W", {"clock": "ai_complex_top.clk", "time": "145ns", "expr": "valid && !ready", "signals": {"valid": "ai_complex_top.hs_valid", "ready": "ai_complex_top.hs_ready"}}, error_family="expression/signal/time"),
    case("expr.normalize", args={"expr": "valid && !ready"}, error_family="expression"),
    case("list.add", "W", {"name": "basic_add", "signal": "ai_complex_top.hs_valid"}, "list", "list/signal"),
    case("list.create", "W", {"name": "primary_list", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}, error_family="list/signal"),
    case("list.delete", "W", {"name": "basic_delete", "index": 2}, "list", "list/index"),
    case("list.export", "W", {"name": "basic_export", "time_range": {"begin": "0ns", "end": "400ns"}, "output": {"path": "$TMP/list_export", "file_format": "u64bin"}}, "list", "list/output/time"),
    case("list.first_change", "W", {"name": "basic_first_change", "time_range": {"begin": "0ns", "end": "120ns"}}, "list", "list/time"),
    case("list.load", "W", {"config": {"lists": [{"name": "loaded", "signals": ["ai_complex_top.sig_a", "ai_complex_top.sig_b"]}]}}, error_family="config/signal"),
    case("list.show", "W", {"name": "basic_show"}, "list", "list"),
    case("list.validate", "W", {"name": "basic_validate"}, "list", "list/signal"),
    case("nwave.rc.generate", "W", {"config_path": "$RC_CONFIG", "output": {"path": "$TMP/signal.rc"}}, "rc", "file/output/signal"),
    case("protocol.handshake.inspect", "W", {"clock": "ai_complex_top.clk", "valid": "ai_complex_top.hs_valid", "ready": "ai_complex_top.hs_ready"}, error_family="signal/time"),
    case("schema", args={"action": "value.at", "kind": "request"},
         error_family="unknown action/kind",
         required_text=("arguments:", "limits:", "constraints:", "examples:"),
         forbidden_text=("additionalProperties", "\nschema:\n", "\nitems:\n")),
    case("scope.list", "W", {"path": "ai_complex_top", "level": 1, "kind": "all"}, error_family="scope/enum"),
    case("scope.roots", "C", {"source": "auto"}, error_family="resource/enum"),
    case("session.close", "W", {}, "disposable_session", "session"),
    case("session.doctor", "W", {}, None, "session"),
    case("session.gc", args={}, error_family="policy"),
    case("session.list", args={}, error_family="catalog"),
    case("session.open", "W", {"name": "primary_session_open"}, "open_action", "resource/session"),
    case("signal.anomaly.inspect", "E", {"signals": ["xif_event_top.xz_data"], "time_range": {"begin": "0ns", "end": "200ns"}, "checks": [{"type": "unknown_xz"}], "line_limit": 4}, error_family="signal/check"),
    case("signal.canonicalize", "C", {"signal": "active_semantics_tb.u_dut.mux_y"}, error_family="signal/ambiguity"),
    case("signal.changes", "W", {"signal": "ai_complex_top.sig_a", "time_range": {"begin": "0ns", "end": "120ns"}, "line_limit": 2}, error_family="signal/time"),
    case("signal.resolve", "C", {"signal": "active_semantics_tb.u_dut.mux_y"}, error_family="signal"),
    case("signal.sampled_pulse.inspect", "W", {"clock": "ai_complex_top.clk", "valid": "ai_complex_top.glitch_sig", "time_range": {"begin": "0ns", "end": "200ns"}, "line_limit": 5}, error_family="signal/time"),
    case("signal.stability", "W", {"signal": "ai_complex_top.stable_sig", "time_range": {"begin": "0ns", "end": "400ns"}}, error_family="signal/time"),
    case("signal.statistics", "W", {"signal": "ai_complex_top.hs_valid", "clock": "ai_complex_top.clk", "time_range": {"begin": "120ns", "end": "210ns"}}, error_family="signal/time"),
    case("signal.xz_verify", "W", {"signal": "ai_complex_top.xz_bus", "expected_state": "x", "time_range": {"begin": "86ns", "end": "94ns"}}, error_family="signal/state/time"),
    case("stream.config.get", "S", {"name": "ready_stream"}, "stream", "config"),
    case("stream.config.list", "S", {}, "stream", "config store"),
    case("stream.config.load", "S", {"config": {"streams": "$STREAM_PRIMARY"}, "mode": "append"}, error_family="config/signal"),
    case("stream.describe", "S", {"stream": "ready_stream"}, "stream", "config/signal"),
    case("stream.export", "S", {"stream": "ready_stream", "kind": "transfer", "cache_scope": "full", "time_range": {"begin": "0ns", "end": "1us"}, "output": {"path": "$TMP/stream.tsv", "file_format": "tsv"}}, "stream", "config/output/time"),
    case("stream.query", "S", {"stream": "ready_packet", "query": "packet_at", "packet_index": 3, "time_range": {"begin": "0ns", "end": "1us"}}, "stream", "config/query/filter",
         ("packet:", "packet_index", "head:", "fields", "first_fields", "last_fields"),
         ("{\"data\":{\"value\"", "\npackets:\n")),
    case("stream.validate", "S", {"stream": "ready_stream", "dynamic": True, "cache_scope": "full", "time_range": {"begin": "0ns", "end": "1us"}}, "stream", "config/time/cache"),
    case("trace.active_driver", "C", {"signal": "active_semantics_tb.u_dut.mux_y", "time": "26ns"}, error_family="signal/time/value"),
    case("trace.active_driver_chain", "C", {"signal": "active_semantics_tb.u_dut.mux_y", "time": "26ns"}, error_family="signal/time/limit"),
    case("trace.driver", "C", {"signal": "active_semantics_tb.u_dut.mux_y"}, error_family="signal/design"),
    case("trace.load", "C", {"signal": "active_semantics_tb.u_dut.mux_y"}, error_family="signal/design"),
    case("trace.x_origin", "X", {"signal": "trace_x_xprop_tb.observed", "time": "18ns", "value_format": "hex"}, error_family="signal/time/value/limit"),
    case("value.at", "W", {"signal": "ai_complex_top.sig_a", "times": ["75ns", "95ns"], "value_format": "hex"}, error_family="selector/signal/time",
         required_text=("values:", "name", "75ns", "95ns"),
         forbidden_text=("summary:", "entry_details:", "sample_details:")),
    case("verify.conditions", "W", {"clock": "ai_complex_top.clk", "time": "95ns", "signals": {"a": "ai_complex_top.sig_a"}, "conditions": [{"expr": "a == 8'hff"}]}, error_family="expression/signal/time"),
    case("waveform.cursor.delete", "W", {"name": "mark_delete"}, "cursor", "cursor"),
    case("waveform.cursor.get", "W", {"name": "mark_get"}, "cursor", "cursor"),
    case("waveform.cursor.list", "W", {}, "cursor", "cursor store"),
    case("waveform.cursor.set", "W", {"name": "mark_primary", "time": "75ns"}, error_family="cursor/time"),
    case("waveform.cursor.use", "W", {"name": "mark_use"}, "cursor", "cursor"),
    case("window.verify", "W", {"clock": "ai_complex_top.clk", "time_range": {"begin": "140ns", "end": "175ns"}, "signals": {"valid": "ai_complex_top.hs_valid"}, "conditions": [{"expr": "valid || !valid", "mode": "always"}]}, error_family="expression/signal/time/mode"),
)


ERROR_CASES = (
    ("unknown-action", None, {"api_version": "xdebug.v1", "action": "not.a.real.action"}),
    ("schema-missing-field", None, {"api_version": "xdebug.v1", "action": "schema", "args": {}}),
    ("session-not-found", None, {"api_version": "xdebug.v1", "action": "session.doctor", "target": {"session_id": "missing"}, "args": {}}),
    ("expression-syntax", None, {"api_version": "xdebug.v1", "action": "expr.normalize", "args": {"expr": "valid &&"}}),
    ("signal-not-found", "W", {"api_version": "xdebug.v1", "action": "value.at", "args": {"signal": "ai_complex_top.no_such", "time": "10ns"}}),
    ("invalid-time", "W", {"api_version": "xdebug.v1", "action": "signal.changes", "args": {"signal": "ai_complex_top.sig_a", "time_range": {"begin": "bad", "end": "10ns"}}}),
    ("config-not-found", "S", {"api_version": "xdebug.v1", "action": "stream.query", "args": {"stream": "missing_stream", "query": "summary"}}),
    ("invalid-output-format", "S", {"api_version": "xdebug.v1", "action": "stream.export", "args": {"stream": "ready_stream", "output": {"path": "$TMP/bad", "file_format": "binary"}}}),
    ("cursor-not-found", "W", {"api_version": "xdebug.v1", "action": "waveform.cursor.get", "args": {"name": "missing_cursor"}}),
)


# External transcript cases protect renderer semantics but are intentionally
# not runtime-matrix entries: the matrix remains one primary call per action.
EXTERNAL_PROTECTION_CASES = {
    "008": {
        "action": "event.find",
        "required_text": ("requested:", "effective:", "events:"),
        "forbidden_text": ("width_diagnostics", "XOUT_BEGIN", "XOUT_END"),
    },
    "012": {
        "action": "trace.active_driver_chain",
        "resource": "C",
        "args": {"signal": "active_semantics_tb.u_dut.ambiguous_rhs_out", "time": "26ns"},
        "required_text": ("ambiguous_rhs_samples:", "signal", "time", "before", "after"),
        "forbidden_text": ("ambiguity:", "XOUT_BEGIN", "XOUT_END"),
    },
    "013": {
        "action": "trace.active_driver_chain",
        "resource": "C",
        "args": {"signal": "active_semantics_tb.u_dut.chain_out", "time": "26ns"},
        "required_text": ("source:", "active_signals:", "chain", "hop", "relation"),
        "forbidden_text": ("width_diagnostics", "active_time", "XOUT_BEGIN", "XOUT_END"),
    },
}
