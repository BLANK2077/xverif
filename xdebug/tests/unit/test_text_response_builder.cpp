#include "api/text_response_builder.h"
#include "api/xout_renderer.h"

#include <cassert>
#include <string>

using namespace xdebug;

int main() {
    TextResponseBuilder out("xdebug");
    out.emit_header("trace.driver");
    out.emit_section("summary");
    out.emit_kv("signal", "top.u.valid");
    out.emit_kv("known", true);
    out.emit_kv("count", 2);
    out.emit_kv("empty", Json::array());
    out.emit_section("rows");
    out.emit_row({"n0", "top.u.valid", "reg with spaces"});
    out.emit_warning("W", "line1\nline2");
    std::string text = out.str();
    assert(text.find("@xdebug.trace.driver.v1") == 0);
    assert(text.find("summary:\n  signal: top.u.valid\n  known : true\n  count : 2") != std::string::npos);
    assert(text.find("rows:\n  n0 top.u.valid reg with spaces") != std::string::npos);
    assert(text.find("warnings:\n  code  message\n  W     line1\\nline2") != std::string::npos);
    assert(text.find("empty") == std::string::npos);

    Json response = {
        {"api_version", "xdebug.v1"},
        {"ok", true},
        {"action", "value.at"},
        {"data", {
            {"signal", "top.clk"},
            {"time", "10ns"},
            {"value", Json{{"value", "'h1"}, {"known", true}}},
            {"known", true}
        }}
    };
    text = render_xout_response(response);
    assert(text.find("@xdebug.value.at.v1") == 0);
    assert(text.find("data:\n  signal: top.clk\n  time  : 10ns") != std::string::npos);
    assert(text.find("value : 'h1") != std::string::npos);

    Json sized_value = {
        {"value", "32'h4000000c"},
        {"bits", "01000000000000000000000000001100"},
        {"known", true},
        {"width", 32}
    };
    assert(json_to_xout_value(sized_value) == "32'h4000000c");

    Json unsized_hex = {{"value", "'h22"}, {"known", true}};
    assert(json_to_xout_value(unsized_hex) == "'h22 width_unknown");

    Json binary_value = {{"value", "'b1010"}, {"known", true}};
    assert(json_to_xout_value(binary_value) == "'b1010 width_unknown");

    Json decimal_value = {
        {"value", "8'd143"}, {"known", true}, {"width", 8}};
    assert(json_to_xout_value(decimal_value) == "8'd143");

    Json unknown_value = {
        {"value", "4'hx"},
        {"bits", "10xz"},
        {"known", false},
        {"width", 4}
    };
    assert(json_to_xout_value(unknown_value) == "4'hx bits=10xz");

    Json z_value = {
        {"value", "8'hzz"},
        {"bits", "zzzzzzzz"},
        {"known", false},
        {"width", 8}
    };
    assert(json_to_xout_value(z_value) == "8'hz bits=zzzz_zzzz");

    Json decimal_xz_value = {
        {"value", "8'bx01xx10x"},
        {"bits", "x01xx10x"},
        {"known", false},
        {"width", 8},
        {"requested_value_format", "dec"},
        {"effective_value_format", "bin"},
        {"value_format_reason", "decimal cannot preserve per-bit X/Z"}
    };
    assert(json_to_xout_value(decimal_xz_value) ==
           "8'bx01xx10x requested=dec reason=X/Z");

    Json field_map = {
        {"data", sized_value},
        {"seq", Json{{"value", "16'h000c"}, {"bits", "0000000000001100"}, {"known", true}, {"width", 16}}}
    };
    assert(json_to_xout_value(field_map) == "data=32'h4000000c seq=16'hc");

    Json table_response = {
        {"api_version", "xdebug.v1"},
        {"ok", true},
        {"action", "stream.query"},
        {"data", {
            {"rows", Json::array({
                Json{{"cycle", 18}, {"time", "185ns"}, {"fields", field_map}}
            })}
        }}
    };
    text = render_xout_response(table_response);
    assert(text.find("cycle  time   fields\n  18     185ns  data=32'h4000000c seq=16'hc") != std::string::npos);
    assert(text.find("bits:") == std::string::npos);
    assert(text.find("known: true") == std::string::npos);

    Json events_response = {
        {"api_version", "xdebug.v1"},
        {"ok", true},
        {"action", "event.export"},
        {"data", {
            {"events", Json::array({
                Json{{"time", "10469.5ns"}, {"signals", Json{{"ready", "1'h0"}, {"valid", "1'h1"}}}},
                Json{{"time", "10470.5ns"}, {"signals", Json{{"ready", "1'h0"}, {"valid", "1'h1"}, {"last", "1'h0"}}}}
            })}
        }}
    };
    text = render_xout_response(events_response);
    assert(text.find("events:\n  time       ready  valid  last\n  10469.5ns  1'h0   1'h1") != std::string::npos);
    assert(text.find("10470.5ns  1'h0   1'h1   1'h0") != std::string::npos);

    Json common_block_response = {
        {"api_version", "xdebug.v1"},
        {"ok", true},
        {"action", "trace.load"},
        {"data", {
            {"rows", Json::array({Json{{"file", "rtl/top.sv"}, {"line", 7}}})},
            {"common_blocks", Json::array({
                Json{{"message", "This is a verified common block."},
                     {"file", "rtl/common/fifo.sv"},
                     {"card", "docs/common/fifo.md"}}
            })}
        }}
    };
    text = render_xout_response(common_block_response);
    size_t rows_pos = text.find("rows:");
    size_t common_pos = text.find("common_blocks:");
    assert(rows_pos != std::string::npos);
    assert(common_pos != std::string::npos);
    assert(common_pos > rows_pos);
    assert(text.find("message file card") == std::string::npos);
    assert(text.find("This is a verified common block.\n  file: rtl/common/fifo.sv\n  card: docs/common/fifo.md") != std::string::npos);

    Json schema_response = {
        {"api_version", "xdebug.v1"},
        {"ok", true},
        {"action", "schema"},
        {"summary", Json{{"action", "trace.driver"}, {"kind", "response"}}},
        {"data", Json{
            {"schema_path", "schemas/v1/actions/trace.driver.response.schema.json"},
            {"schema", Json{
                {"title", "trace.driver response"},
                {"required", Json::array({"api_version", "ok", "action", "summary", "data"})},
                {"properties", Json{{"data", Json{{"type", "object"}}}}}
            }}
        }}
    };
    text = render_xout_response(schema_response);
    assert(text.find("@xdebug.schema.v1") == 0);
    assert(text.find("summary:\n") != std::string::npos);
    assert(text.find("schema_path: schemas/v1/actions/trace.driver.response.schema.json") != std::string::npos);
    assert(text.find("ai_hint") == std::string::npos);
    assert(text.find("\nschema:\n") != std::string::npos);
    assert(text.find("\nrequired:\n") != std::string::npos);

    Json axi_response = {
        {"api_version", "xdebug.v1"},
        {"ok", true},
        {"action", "axi.query"},
        {"summary", Json{{"name", "axi0"}, {"query_mode", "handshake"}, {"found", true}}},
        {"data", Json{{"transaction", Json{
            {"direction", "write"},
            {"latency", "40ns"},
            {"response_dependency_violation", false},
            {"address", Json{
                {"channel", "aw"},
                {"valid_begin_time", "90ns"},
                {"handshake_time", "100ns"},
                {"addr", 240},
            }},
            {"response", Json{
                {"channel", "b"},
                {"handshake_time", "140ns"},
                {"resp", 0},
            }},
        }}}}
    };
    text = render_xout_response(axi_response);
    assert(text.find("@xdebug.axi.query.v1") == 0);
    assert(text.find("summary:\n  name      : axi0\n  query_mode: handshake\n  found     : true") != std::string::npos);
    assert(text.find("address:\n  channel         : aw\n  valid_begin_time: 90ns\n  handshake_time  : 100ns\n  addr            : 240") != std::string::npos);
    assert(text.find("response:\n  channel       : b\n  handshake_time: 140ns\n  resp          : 0") != std::string::npos);

    Json axi_detailed = axi_response;
    axi_detailed["data"]["transaction"]["data"] = Json{
        {"channel", "w"},
        {"valid_begin_time", "105ns"},
        {"first_handshake_time", "110ns"},
        {"last_handshake_time", "130ns"},
        {"beat_count", 2},
        {"expected_beat_count", 2},
        {"beats", Json::array({
            Json{{"index", 1}, {"handshake_time", "110ns"}, {"data", "11223344"}, {"wstrb", "f"}, {"last", false}},
            Json{{"index", 2}, {"handshake_time", "130ns"}, {"data", "55667788"}, {"wstrb", "f"}, {"last", true}},
        })},
    };
    text = render_xout_response(axi_detailed);
    assert(text.find("data:\n  channel             : w\n  valid_begin_time    : 105ns\n  first_handshake_time: 110ns") != std::string::npos);
    assert(text.find("beats:\n  index  handshake_time  data      wstrb  last\n  1      110ns           11223344  f      false\n  2      130ns           55667788  f      true") != std::string::npos);

    Json axi_not_found = {
        {"api_version", "xdebug.v1"}, {"ok", true}, {"action", "axi.query"},
        {"summary", Json{{"name", "axi0"}, {"query_mode", "handshake"}, {"found", false}}},
        {"data", Json{{"match", Json{{"channel", "aw"}, {"handshake_time", "1ps"}}}}},
    };
    text = render_xout_response(axi_not_found);
    assert(text.find("summary:\n  name      : axi0\n  query_mode: handshake\n  found     : false") != std::string::npos);
    assert(text.find("transaction:") == std::string::npos);

    Json axi_pending = {
        {"api_version", "xdebug.v1"}, {"ok", true}, {"action", "axi.analysis"},
        {"summary", Json{
            {"name", "axi0"}, {"analysis", "pending"},
            {"pending_count", 0}, {"returned_pending_count", 0}, {"truncated", false},
        }},
        {"data", Json{{"pending_transactions", Json::array()}}},
    };
    text = render_xout_response(axi_pending);
    assert(text.find("pending_count         : 0\n  returned_pending_count: 0") != std::string::npos);
    assert(text.find("pending_transactions: [empty]") != std::string::npos);

    Json axi_read = axi_response;
    axi_read["data"]["transaction"]["direction"] = "read";
    axi_read["data"]["transaction"]["address"]["channel"] = "ar";
    axi_read["data"]["transaction"]["response"]["channel"] = "r";
    text = render_xout_response(axi_read);
    assert(text.find("direction                    : read") != std::string::npos ||
           text.find("direction: read") != std::string::npos);
    assert(text.find("response:\n  channel       : r") != std::string::npos);

    Json axi_read_detailed = axi_read;
    axi_read_detailed["data"]["transaction"]["data"] = Json{
        {"channel", "r"},
        {"valid_begin_time", "105ns"},
        {"first_handshake_time", "110ns"},
        {"last_handshake_time", "130ns"},
        {"beat_count", 2},
        {"expected_beat_count", 2},
        {"beats", Json::array({
            Json{{"index", 1}, {"handshake_time", "110ns"}, {"data", "11223344"}, {"resp", "0"}, {"last", false}},
            Json{{"index", 2}, {"handshake_time", "130ns"}, {"data", "55667788"}, {"resp", "0"}, {"last", true}},
        })},
    };
    text = render_xout_response(axi_read_detailed);
    assert(text.find("data:\n  channel             : r\n  valid_begin_time    : 105ns") != std::string::npos);
    assert(text.find("beats:\n  index  handshake_time  data      resp  last\n  1      110ns           11223344  0     false\n  2      130ns           55667788  0     true") != std::string::npos);

    Json axi_error = {
        {"ok", false}, {"action", "axi.query"},
        {"error", Json{
            {"code", "INVALID_ARGUMENT"},
            {"message", "channel and handshake_time must appear together"},
            {"recoverable", true},
            {"error_layer", "handler"},
            {"invalid_arg", "args.query"},
        }},
    };
    text = render_xout_response(axi_error);
    assert(text.find("@xdebug.error.v1") == 0);
    assert(text.find("action     : axi.query") != std::string::npos);
    assert(text.find("invalid_arg: args.query") != std::string::npos);

    Json handler_text = {
        {"ok", true},
        {"action", "any.action"},
        {"text", "@xdebug.any.action.v1\nsummary:\n  ok: true\n"}
    };
    text = render_xout_response(handler_text);
    assert(text == "@xdebug.any.action.v1\nsummary:\n  ok: true\n");

    Json handler_response = {
        {"ok", true},
        {"action", "trace.active_driver_chain"},
        {"summary", {{"termination", "ambiguous"}}},
    };
    const std::string handler_xout =
        "@xdebug.trace.active_driver_chain.v1\n"
        "ambiguous_rhs_samples:\n"
        "  signal time before after\n"
        "  top.rhs 10ns 1'b0 1'b1\n\n";
    text = render_xout_response(handler_response, handler_xout);
    assert(text ==
           "@xdebug.trace.active_driver_chain.v1\n"
           "ambiguous_rhs_samples:\n"
           "  signal time before after\n"
           "  top.rhs 10ns 1'b0 1'b1\n");
    assert(text.find("termination") == std::string::npos);
    assert(text.find("XOUT_BEGIN") == std::string::npos);
    assert(text.find("XOUT_END") == std::string::npos);
    assert(render_xout_transport_payload(handler_response, handler_xout) == text);

    Json error = {
        {"ok", false},
        {"action", "trace.driver"},
        {"error", {
            {"code", "SIGNAL_NOT_FOUND"},
            {"message", "missing\nsignal"},
            {"recoverable", true},
            {"error_layer", "handler"},
            {"example_note", "示例仅说明当前入口参数形态。"},
            {"next_actions", Json::array({"scope.roots", "scope.list"})}
        }}
    };
    text = render_xout_response(error);
    assert(text.find("@xdebug.error.v1") == 0);
    assert(text.find("action      : trace.driver") != std::string::npos);
    assert(text.find("code        : SIGNAL_NOT_FOUND") != std::string::npos);
    assert(text.find("message     : missing\\nsignal") != std::string::npos);
    assert(text.find("error_layer : handler") != std::string::npos);
    assert(text.find("example_note:") != std::string::npos ||
           text.find("example_note :") != std::string::npos);
    assert(text.find("next_actions:") != std::string::npos);
    const std::string ignored_handler_xout = "@xdebug.should.not.pass.v1\n";
    assert(render_xout_response(error, ignored_handler_xout) == text);
    assert(render_xout_transport_payload(error, ignored_handler_xout) == text);
    return 0;
}
