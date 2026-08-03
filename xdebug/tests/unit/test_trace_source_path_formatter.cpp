#include "service/trace_source_path_formatter.h"
#include "test_temp_path.h"

#include <cassert>
#include <cstdlib>
#include <fcntl.h>
#include <fstream>
#include <string>
#include <unistd.h>

namespace {

using Json = nlohmann::ordered_json;

std::string make_source_file() {
    std::vector<char> path_storage = test_temp_template("xdebug-trace-source-XXXXXX");
    char* path = path_storage.data();
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);
    std::ofstream out(path);
    for (int i = 1; i <= 24; ++i) {
        out << "assign s" << i << " = in" << i << ";\n";
    }
    return path;
}

int count_substr(const std::string& text, const std::string& needle) {
    int count = 0;
    size_t pos = 0;
    while ((pos = text.find(needle, pos)) != std::string::npos) {
        ++count;
        pos += needle.size();
    }
    return count;
}

Json path_item(const std::string& file, int line, Json signal_path) {
    return Json{{"file", file}, {"line", line}, {"signal_path", signal_path}};
}

Json trace_raw_with_edges(const std::string& file, int count) {
    Json raw;
    raw["dependency_edges"] = Json::array();
    for (int i = 1; i <= count; ++i) {
        raw["dependency_edges"].push_back({
            {"from", "top.src" + std::to_string(i)},
            {"to", "top.dst" + std::to_string(i)},
            {"file", file},
            {"line", i}
        });
    }
    return raw;
}

} // namespace

int main() {
    std::string file = make_source_file();
    setenv("XDEBUG_TRACE_SOURCE_CONTEXT_LINES", "1", 1);
    setenv("XDEBUG_TRACE_SOURCE_MERGE_THRESHOLD_LINES", "10", 1);

    Json response = {
        {"summary", Json{{"signal", "top.out"}, {"mode", "load"}, {"path_count", 4}}},
        {"data", Json{{"paths", Json::array({
            path_item(file, 5, Json::array({"top.a", "top.b"})),
            path_item(file, 9, Json::array({"top.b", "top.c"})),
            path_item(file, 9, Json::array({"top.b", "top.c"})),
            path_item(file, 20, Json::array({"top.x", "top.y"})),
        })}}},
    };

    std::string text = xdebug_design::render_source_path_xout("trace.load", response);
    assert(text.find("@xdebug.trace.load.v1") == 0);
    assert(text.find("source: " + file + ":5-9") != std::string::npos);
    assert(text.find("source: " + file + ":20") != std::string::npos);
    assert(count_substr(text, "\nsource: ") == 2);
    assert(text.find(">   5 | assign s5 = in5;") != std::string::npos);
    assert(text.find(">   9 | assign s9 = in9;") != std::string::npos);
    assert(text.find("   10 | assign s10 = in10;") != std::string::npos);
    assert(text.find("   11 | assign s11 = in11;") == std::string::npos);
    assert(text.find("\nactive_signals:\n") != std::string::npos);
    assert(text.find("line  signal_path") != std::string::npos);
    assert(text.find("5     top.a -> top.b") != std::string::npos);
    assert(count_substr(text, "9     top.b -> top.c") == 1);
    assert(text.find("\nsignal_path: ") == std::string::npos);

    assert(xdebug_design::trace_result_limit_from_request(Json::object()) == 10);
    assert(xdebug_design::trace_result_limit_from_request(
               Json{{"limits", Json{{"max_results", 6}}}}) == 6);
    assert(xdebug_design::trace_result_limit_from_request(
               Json{{"args", Json{{"line_limit", 4}}}, {"limits", Json{{"max_results", 6}}}}) == 4);
    assert(xdebug_design::trace_result_limit_from_request(
               Json{{"args", Json{{"line_limit", 0}}}, {"limits", Json{{"max_results", 6}}}}) == 6);

    Json next_action = {
        {"chain_id", "c0"}, {"reason", "continue_from_depth_frontier"},
        {"action", "trace.active_driver_chain"},
        {"args", Json{{"signal", "top.c"}, {"time", "10ns"}}},
        {"limits", Json{{"max_depth", 2}}}
    };
    Json chain_data = {
        {"hops", Json::array({
            Json{{"index", 1}, {"chain_id", "c0"}, {"time", "20ns"}, {"relation", "root"},
                 {"file", file}, {"line", 5}, {"signal_path", Json::array({"top.a", "top.b"})}},
            Json{{"index", 2}, {"chain_id", "c0"}, {"time", "10ns"}, {"relation", "driver"},
                 {"file", file}, {"line", 9}, {"signal_path", Json::array({"top.b", "top.c"})}},
        })},
        {"depth_frontiers", Json::array({Json{{"chain_id", "c0"}, {"signal", "top.c"},
            {"time", "10ns"}, {"value", "8'hxx"}, {"stopped_after_depth", 2}}})},
        {"suggested_next_actions", Json::array({next_action})}
    };
    Json chain_response = {
        {"summary", Json{{"signal", "top.out"}, {"time", "20ns"},
            {"termination", "control_only"}, {"termination_detail", "control_only"},
            {"scan_complete", true}, {"analysis_complete", true},
            {"response_truncated", false}, {"total_count", 2},
            {"returned_count", 2}, {"truncation_scopes", Json::array()},
            {"value_width_complete", false},
            {"width_diagnostics", Json::array({Json{{"signal", "top.out"},
                {"role", "hops[0].value"}, {"reason", "width unavailable"}}})}}},
        {"data", chain_data},
    };
    std::string chain_text = xdebug_design::render_source_path_xout("trace.active_driver_chain", chain_response);
    assert(chain_text.find("chain  hop  time") != std::string::npos);
    assert(chain_text.find("c0     1    20ns  root") != std::string::npos);
    assert(chain_text.find("c0     2    10ns  driver") != std::string::npos);
    assert(chain_text.find("\ndepth_frontiers:\n") != std::string::npos);
    assert(chain_text.find("top.c   10ns  8'hxx") != std::string::npos);
    assert(chain_text.find("\nnext:\n") != std::string::npos);
    assert(chain_text.find("trace.active_driver_chain  top.c   10ns  2") != std::string::npos);
    assert(chain_text.find("truncation_scopes") != std::string::npos);
    assert(chain_text.find("[empty]") != std::string::npos);
    assert(chain_text.find("width_diagnostics") == std::string::npos);
    assert(chain_text.find("width unavailable") == std::string::npos);
    assert(chain_text.find("{") == std::string::npos);
    assert(chain_text.find("XOUT_BEGIN") == std::string::npos);
    assert(!chain_text.empty() && chain_text.back() == '\n');

    Json ambiguous_response = {
        {"summary", Json{{"signal", "top.out"}, {"termination", "ambiguous"}}},
        {"data", Json{{"ambiguity_evidence", Json{
            {"kind", "multiple_rhs_sources"},
            {"signal", "top.out"},
            {"active_time", "10ns"},
            {"complete", true},
            {"rhs_signal_count", 1},
            {"returned_rhs_signal_count", 1},
            {"omitted_rhs_signal_count", 0},
            {"truncation_scope", nullptr},
            {"statements", Json::array({Json{
                {"file", "rtl/top.sv"},
                {"line", 12},
                {"rhs_samples", Json::array({
                    Json{
                        {"signal", "top.raw_bin"},
                        {"before", Json{{"status", "ok"}, {"value", "1010"}}},
                        {"after", Json{{"status", "ok"}, {"value", "0011"}}},
                        {"changed", true}
                    },
                    Json{
                        {"signal", "top.prefixed_hex"},
                        {"before", Json{{"status", "ok"}, {"value", "8'ha0"}}},
                        {"after", Json{{"status", "ok"}, {"value", "8'ha1"}}},
                        {"changed", true}
                    },
                    Json{
                        {"signal", "top.raw_xz"},
                        {"before", Json{{"status", "ok"}, {"value", "xxxx0010"}}},
                        {"after", Json{{"status", "ok"}, {"value", "zzzz0011"}}},
                        {"changed", true}
                    },
                    Json{
                        {"signal", "top.prefixed_bin"},
                        {"before", Json{{"status", "ok"}, {"value", "8'b10100000"}}},
                        {"after", Json{{"status", "ok"}, {"value", "8'b10100001"}}},
                        {"changed", true}
                    },
                    Json{
                        {"signal", "top.prefixed_dec"},
                        {"before", Json{{"status", "ok"}, {"value", "8'd160"}}},
                        {"after", Json{{"status", "missing_value"}, {"value", nullptr}}},
                        {"changed", nullptr}
                    }
                })}
            }})}
        }}, {"hops", Json::array({
            Json{{"index", 0}, {"file", file}, {"line", 5},
                 {"signal_path", Json::array({"top.out"})}}
        })}}}
    };
    std::string ambiguous_text = xdebug_design::render_source_path_xout(
        "trace.active_driver_chain", ambiguous_response);
    size_t active_signals_pos = ambiguous_text.find("\nactive_signals:\n");
    size_t ambiguity_pos = ambiguous_text.find("\nambiguous_rhs_samples:\n");
    assert(active_signals_pos != std::string::npos);
    assert(ambiguity_pos != std::string::npos);
    assert(ambiguity_pos > active_signals_pos);
    assert(ambiguous_text.find("signal            time  before", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("top.raw_bin       10ns  4'ha", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("4'h3", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("top.raw_xz        10ns  8'hx2", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("8'hz3", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("8'ha0", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("8'b10100000", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("8'd160", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("null", ambiguity_pos) != std::string::npos);
    assert(ambiguous_text.find("statement", ambiguity_pos) == std::string::npos);
    assert(ambiguous_text.find("changed", ambiguity_pos) == std::string::npos);
    assert(ambiguous_text.find("status", ambiguity_pos) == std::string::npos);

    Json canonical_raw = {
        {"summary", Json{{"termination", "control_only"},
            {"termination_detail", "control_only"}}},
        {"chain", Json{{"chain", Json::array({Json{
            {"index", 0}, {"signal", "top.a"}, {"next", "top.b"},
            {"time", "20ns"}, {"active_time", "20ns"},
            {"value", Json{{"value", "'h1"}, {"known", true}}},
            {"file", file}, {"line", 5}
        }})}}}
    };
    Json canonical = xdebug_design::simplify_active_driver_chain_payload(
        canonical_raw, "top.b", "20ns", 10);
    assert(canonical["summary"]["scan_complete"] == true);
    assert(canonical["summary"]["analysis_complete"] == true);
    assert(canonical["summary"]["response_truncated"] == false);
    assert(canonical["summary"]["total_count"] == 1);
    assert(canonical["summary"]["returned_count"] == 1);
    assert(canonical["summary"]["truncation_scopes"].empty());
    assert(!canonical["summary"].contains("hop_count"));
    assert(!canonical["summary"].contains("truncated"));
    assert(canonical["hops"][0]["value"].is_object());
    assert(canonical["hops"][0]["value"]["value"] == "'h1");

    Json default_limited = xdebug_design::simplify_trace_driver_load_payload(
        trace_raw_with_edges(file, 12), "trace.load", "top.out", "load");
    assert(default_limited["summary"]["path_count"] == 10);
    assert(default_limited["summary"]["truncated"] == true);
    assert(default_limited["summary"]["limit_hint"] ==
           "returned first 10 trace entries; increase limits.max_results to return all results");
    assert(default_limited["paths"].size() == 10);

    Json explicit_limited = xdebug_design::simplify_trace_driver_load_payload(
        trace_raw_with_edges(file, 12), "trace.load", "top.out", "load", 3);
    assert(explicit_limited["summary"]["path_count"] == 3);
    assert(explicit_limited["summary"]["truncated"] == true);
    assert(explicit_limited["summary"]["limit_hint"] ==
           "returned first 3 trace entries; increase limits.max_results to return all results");
    assert(explicit_limited["paths"].size() == 3);

    Json limited_response = {
        {"summary", default_limited["summary"]},
        {"data", Json{{"paths", default_limited["paths"]}}},
    };
    std::string limited_text = xdebug_design::render_source_path_xout("trace.load", limited_response);
    assert(limited_text.find("limit_hint: returned first 10 trace entries; increase limits.max_results to return all results") != std::string::npos);

    unlink(file.c_str());
    unsetenv("XDEBUG_TRACE_SOURCE_CONTEXT_LINES");
    unsetenv("XDEBUG_TRACE_SOURCE_MERGE_THRESHOLD_LINES");
    return 0;
}
